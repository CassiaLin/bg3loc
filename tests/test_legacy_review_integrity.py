"""Synthetic legacy decision regression; no proprietary data or transport."""
from pathlib import Path
from contextlib import closing
import sqlite3
import hashlib
import json
import shutil
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import pytest

from bg3loc.production_review import ProductionReviewStore
from bg3loc.qa_state import TranslationQaStore
from bg3loc.execution_state import TranslationExecutionStore
from bg3loc.qa import QaInput, evaluate_translation
from bg3loc.protected_syntax import extract_protected_tokens
from bg3loc.production_completion import build_production_completion_view
from bg3loc.production_finalize import ProductionFinalizeRequest, finalize_production_workspace
from bg3loc.final_merge_bridge import build_final_merge_bridge
from bg3loc.production_orchestration import prepare_production_workspace
from bg3loc.production_workspace import verify_production_workspace
from bg3loc.production_qa_orchestration import run_workspace_qa
from bg3loc.rebuilder import write_loca_xml, LocaRecord
import test_production_review as raw_fixture
import test_production_finalize as final_fixture
import test_production_context as context_fixture

NOW = '2026-10-11T00:00:00Z'
def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()
def dump(db):
    with closing(sqlite3.connect(db)) as conn:
        return tuple(conn.iterdump())
def arguments(decision, key='uid-review', plan=None, source=''):
    return dict(content_uid=key, decision=decision, reviewer='SYNTHETIC reviewer',
                note='engineering test', resolved_at=NOW, batch_plan_path=plan,
                revised_text='SYNTHETIC revised '+source if decision=='REVISE' else None)


@pytest.mark.parametrize('version',['1.0','1.1','1.2'])
@pytest.mark.parametrize('decision',['ACCEPT','REVISE'])
def test_stale_actual_base_rejects_without_data_or_history_writes(version, decision):
    temp, db, plan, source = raw_fixture.TestProductionReviewResolution()._fixture()
    try:
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute("UPDATE metadata SET value=? WHERE key='schemaVersion'",(version,))
            conn.execute("UPDATE content_state SET translated_text='SYNTHETIC changed bytes' WHERE content_uid='uid-review'")
        before = dump(db)
        with pytest.raises(ValueError):
            ProductionReviewStore(db).resolve(**arguments(decision,plan=plan,source=source))
        assert dump(db) == before
    finally:
        temp.cleanup()


@pytest.mark.parametrize('decision',['ACCEPT','REVISE'])
@pytest.mark.parametrize('tuple_mode',['absent','current','stale'])
def test_valid_current_decisions_and_optional_expected_tuple(decision, tuple_mode):
    temp, db, plan, source = raw_fixture.TestProductionReviewResolution()._fixture()
    try:
        qa = TranslationQaStore(db); review = ProductionReviewStore(db)
        current = qa.get_result('uid-review')
        args = arguments(decision,plan=plan,source=source)
        if tuple_mode != 'absent':
            args.update(expected_execution_input_hash=current.execution_input_hash,
                        expected_output_hash=current.output_hash, expected_qa_input_hash=current.qa_input_hash,
                        expected_qa_rule_set_version=current.qa_rule_set_version)
            if tuple_mode == 'stale':args['expected_output_hash']=digest('old')
        before = dump(db)
        if tuple_mode == 'stale':
            with pytest.raises(ValueError):review.resolve(**args)
            assert dump(db)==before
        else:
            old_qa = current
            result = review.resolve(**args)
            state = TranslationExecutionStore(db).get_state('uid-review')
            assert digest(state['translated_text'])==result.resolved_output_hash==state['output_hash']
            after = qa.get_result('uid-review')
            assert after.qa_status==('checked' if decision=='ACCEPT' else 'stale')
            assert after.qa_input_hash==old_qa.qa_input_hash  # Legacy never persists revised QA.
    finally:temp.cleanup()


@pytest.mark.parametrize('attack',['missing','ambiguous','changed','duplicate','wrong-category','malformed'])
@pytest.mark.parametrize('decision',['ACCEPT','REVISE'])
def test_material_errors_reject_without_database_mutation(attack, decision):
    temp, db, plan, source = raw_fixture.TestProductionReviewResolution()._fixture()
    try:
        path = plan.parent/'materials/bark-0001.jsonl'
        row = json.loads(path.read_text())
        if attack=='missing':path.unlink()
        elif attack=='ambiguous':shutil.copytree(plan.parent,db.parent/'batches')
        elif attack=='changed':row['SourceText']='SYNTHETIC replaced source';path.write_text(json.dumps(row)+'\n')
        elif attack=='duplicate':path.write_text(path.read_text()*2)
        elif attack=='wrong-category':row['primaryCategory']='other';path.write_text(json.dumps(row)+'\n')
        else:path.write_text('{not JSON')
        before = dump(db)
        with pytest.raises(ValueError):
            ProductionReviewStore(db).resolve(**arguments(decision, source=source))
        assert dump(db)==before
        assert TranslationQaStore(db).get_result('uid-review').qa_status=='stale'
    finally:temp.cleanup()


@pytest.mark.parametrize('decision',['ACCEPT','REVISE'])
@pytest.mark.parametrize('changed',['bytes','source','qa','input'])
def test_committed_change_after_preflight_is_rechecked_in_writer(tmp_path, monkeypatch, decision, changed):
    temp, db, plan, source = raw_fixture.TestProductionReviewResolution()._fixture()
    try:
        original = TranslationQaStore.get_result
        baseline = []
        def race(self,*args,**kwargs):
            result = original(self,*args,**kwargs)
            if changed=='source':
                path=plan.parent/'materials/bark-0001.jsonl';row=json.loads(path.read_text());row['SourceText']='SYNTHETIC mutated';path.write_text(json.dumps(row)+'\n')
            else:
                with closing(sqlite3.connect(db)) as conn,conn:
                    if changed=='bytes':conn.execute("UPDATE content_state SET translated_text='SYNTHETIC tampered'")
                    elif changed=='qa':conn.execute("UPDATE qa_results SET qa_input_hash='mutated'")
                    else:conn.execute("UPDATE content_state SET input_hash='mutated'")
            baseline[:] = dump(db)
            return result
        monkeypatch.setattr(TranslationQaStore,'get_result',race)
        with pytest.raises(ValueError):ProductionReviewStore(db).resolve(**arguments(decision,source=source))
        assert dump(db)==tuple(baseline)
    finally:temp.cleanup()


@pytest.mark.parametrize('mode',['WAL','DELETE'])
@pytest.mark.parametrize('decision',['ACCEPT','REVISE'])
def test_competing_sql_writer_is_blocked_during_validation(mode, decision, monkeypatch):
    from bg3loc.legacy_qa_material import LegacyQaMaterial
    temp, db, plan, source = raw_fixture.TestProductionReviewResolution()._fixture()
    try:
        with closing(sqlite3.connect(db)) as conn:assert conn.execute('PRAGMA journal_mode='+mode).fetchone()[0].upper()==mode
        original=LegacyQaMaterial.current; observed=[]
        def wrapped(self,*args):
            if not observed:
                def competitor():
                    with closing(sqlite3.connect(db,timeout=0.03)) as conn,conn:
                        with pytest.raises(sqlite3.OperationalError,match='locked'):
                            conn.execute("UPDATE content_state SET translated_text='concurrent'")
                # Only run when the review writer lock is active, not preflight read.
                with closing(sqlite3.connect(db,timeout=0.03)) as other:
                    try:other.execute('BEGIN IMMEDIATE');other.rollback();return original(self,*args)
                    except sqlite3.OperationalError:pass
                with ThreadPoolExecutor(max_workers=1) as pool:pool.submit(competitor).result(timeout=3)
                observed.append(True)
            return original(self,*args)
        monkeypatch.setattr(LegacyQaMaterial,'current',wrapped)
        ProductionReviewStore(db).resolve(**arguments(decision,source=source))
        assert observed==[True]
    finally:temp.cleanup()


def test_late_revise_sql_failure_rolls_back_every_table():
    temp, db, plan, source=raw_fixture.TestProductionReviewResolution()._fixture()
    try:
        with closing(sqlite3.connect(db)) as conn,conn:
            conn.execute("CREATE TRIGGER reject_decision BEFORE INSERT ON qa_review_resolutions BEGIN SELECT RAISE(ABORT,'synthetic late failure'); END")
        before=dump(db)
        with pytest.raises(sqlite3.IntegrityError):ProductionReviewStore(db).resolve(**arguments('REVISE',source=source))
        assert dump(db)==before
    finally:temp.cleanup()


def test_old_ddl_null_is_not_fabricated_and_valid_acceptance_remains_current():
    temp, db, plan, source=raw_fixture.TestProductionReviewResolution()._fixture()
    try:
        with closing(sqlite3.connect(db)) as conn,conn:
            conn.execute('ALTER TABLE qa_results DROP COLUMN execution_input_hash')
            conn.execute('ALTER TABLE qa_review_resolutions DROP COLUMN execution_input_hash')
        qa=TranslationQaStore(db);review=ProductionReviewStore(db)
        for _ in range(2):qa.initialize();review.initialize()
        assert qa.get_result('uid-review').execution_input_hash is None
        before=dump(db);review.resolve(**arguments('ACCEPT',source=source))
        assert qa.get_result('uid-review').execution_input_hash is None
        with closing(sqlite3.connect(db)) as conn:assert conn.execute('SELECT execution_input_hash FROM qa_results').fetchone()[0] is None
        assert review.get_current_acceptance('uid-review',current_output_hash=digest(source)) is not None
    finally:temp.cleanup()


def test_closed_snapshot_cannot_certify_a_later_qa_read():
    from bg3loc.legacy_qa_material import LegacyQaMaterial
    temp, db, plan, source=raw_fixture.TestProductionReviewResolution()._fixture()
    try:
        snapshot=LegacyQaMaterial(db);snapshot.close()
        assert TranslationQaStore(db).get_result('uid-review',_material_snapshot=snapshot).qa_status=='stale'
    finally:temp.cleanup()


def sealed_h0():
    return final_fixture.TestProductionFinalize()._workspace(({
        'ContentUid':'uid-audit','SourceText':'Invented trigger {TARGET}',
        'primaryCategory':'bark','batchId':'bark-0001'},))


@pytest.mark.parametrize('decision',['ACCEPT','REVISE'])
def test_matching_declared_sha_does_not_allow_qa_for_other_base_bytes(decision):
    temp, workspace, db, extract = sealed_h0()
    try:
        source = 'Invented trigger {TARGET}'
        old = evaluate_translation(QaInput('uid-audit',source,source,'bark',('{TARGET}',)))
        state = TranslationExecutionStore(db).get_state('uid-audit')
        changed = 'SYNTHETIC other base preserving {TARGET}'
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute("UPDATE content_state SET status='succeeded',translated_text=?,output_hash=? WHERE content_uid='uid-audit'",
                         (changed,digest(changed)))
        qa = TranslationQaStore(db); qa.initialize()
        qa.record_result(old,checked_at=NOW,expected_input_hash=state['input_hash'],expected_output_hash=digest(changed))
        review = ProductionReviewStore(db); review.initialize()
        before = dump(db)
        with pytest.raises(ValueError):
            review.resolve(**arguments(decision,'uid-audit',workspace/'batches/batch-plan.json',source))
        assert dump(db) == before
    finally:
        temp.cleanup()


def prepared_hse(root):
    root.mkdir(parents=True)
    request, _ = context_fixture.fixture(root)
    rows=context_fixture.read_rows(request.source)
    for row in rows:row['version']=1
    context_fixture.write_rows(request.source, rows)
    directory=request.extract_manifest.parent
    target=directory/'target.jsonl'
    targets=[dict(contentUid=r['contentUid'],localeId='ChineseTraditional',version=7,text='SYNTHETIC baseline') for r in rows]
    context_fixture.write_rows(target,targets)
    locales=[]
    for locale,items,normalized in [('English',rows,request.source),('ChineseTraditional',targets,target)]:
        xml=directory/(locale+'.xml');write_loca_xml(xml,[LocaRecord(r['contentUid'],r['version'],r['text']) for r in items])
        xml.with_suffix('.loca').write_bytes(xml.read_bytes());xml.with_suffix('.pak').write_bytes(b'SYNTHETIC')
        locales.append(dict(localeId=locale,packageFile=str(xml.with_suffix('.pak')),locaEntry=f'Localization/{locale}/source.loca',
                            sourceLoca=str(xml.with_suffix('.loca')),sourceXml=str(xml),normalized=str(normalized),nodeCount=len(items)))
    request.extract_manifest.write_text(json.dumps(dict(schemaVersion='1.0',scanManifest='unused',sourceLocale='English',
        targetLocale='ChineseTraditional',referenceLocales=[],backend={'id':'fake'},locales=locales,aligned='unused',roundtripValidation='unused')))
    prepare_production_workspace(request)
    return request.output_dir,request.output_dir/'execution.sqlite3',request.extract_manifest


def seed_sealed(workspace, db):
    binding=verify_production_workspace(workspace)
    rows={}
    for p in (workspace/'batches/materials').glob('*.jsonl'):
        for row in context_fixture.read_rows(p):rows[str(row.get('contentUid',row.get('ContentUid')))]=row
    key=next(k for k,row in rows.items() if 'sameEntityContext' in row) if binding.manifest['schemaVersion']=='1.2' else next(iter(rows))
    qa=TranslationQaStore(db);qa.initialize();ProductionReviewStore(db).initialize()
    for uid,row in rows.items():
        source=row.get('sourceText',row.get('SourceText'));text=source if uid==key else 'SYNTHETIC translation '+source
        with closing(sqlite3.connect(db)) as conn,conn:
            conn.execute("UPDATE content_state SET status='succeeded',translated_text=?,output_hash=? WHERE content_uid=?",(text,digest(text),uid))
        state=TranslationExecutionStore(db).get_state(uid)
        qa.record_result(evaluate_translation(QaInput(uid,source,text,row['primaryCategory'],tuple(extract_protected_tokens(source)))),
                         checked_at=NOW,expected_input_hash=state['input_hash'],expected_output_hash=digest(text))
    return binding,key,rows[key],qa


@pytest.mark.parametrize('version',['1.0','1.1','1.2'])
@pytest.mark.parametrize('decision',['ACCEPT','REVISE'])
def test_sealed_stale_base_and_valid_normal_flows(tmp_path, version, decision):
    temp=None
    if version=='1.2':workspace,db,extract=prepared_hse(tmp_path/'input')
    else:
        temp,workspace,db,extract=sealed_h0()
        path=workspace/'production-manifest.json';manifest=json.loads(path.read_text());manifest['schemaVersion']=version;path.write_text(json.dumps(manifest))
    try:
        binding,key,row,qa=seed_sealed(workspace,db);source=row.get('sourceText',row.get('SourceText'))
        current=qa.get_result(key);review=ProductionReviewStore(db)
        with closing(sqlite3.connect(db)) as conn,conn:conn.execute('UPDATE content_state SET translated_text=? WHERE content_uid=?',('SYNTHETIC changed',key))
        before=dump(db)
        with pytest.raises(ValueError):review.resolve(**arguments(decision,key,source=source))
        assert dump(db)==before
        assert qa.get_result(key).qa_status=='stale'
        assert review.get_current_acceptance(key,current_output_hash=digest(source)) is None
        assert next(r.disposition for r in build_production_completion_view(db,binding.batch_plan).rows if r.content_uid==key)=='BLOCKED'
        with closing(sqlite3.connect(db)) as conn,conn:conn.execute('UPDATE content_state SET translated_text=? WHERE content_uid=?',(source,key))
        review.resolve(**arguments(decision,key,source=source))
        if decision=='REVISE':
            assert qa.get_result(key).qa_status=='stale'
            run_workspace_qa(workspace)
            assert qa.get_result(key).qa_status=='checked'
        final=finalize_production_workspace(ProductionFinalizeRequest(workspace,tmp_path/'final',container='loca-only'),
                                            rebuild_backend=final_fixture.FakeFinalizeBackend())
        assert final.manifest['status']=='pass'
    finally:
        if temp:temp.cleanup()


def test_rebound_qa_missing_token_cannot_be_current_ready_or_finalized(tmp_path):
    temp,workspace,db,extract=sealed_h0()
    try:
        binding,key,row,qa=seed_sealed(workspace,db);source=row['SourceText'];old=qa.get_result(key)
        invalid='SYNTHETIC missing token'
        with closing(sqlite3.connect(db)) as conn,conn:
            conn.execute('UPDATE content_state SET translated_text=?,output_hash=? WHERE content_uid=?',(invalid,digest(invalid),key))
        state=TranslationExecutionStore(db).get_state(key)
        qa.record_result(evaluate_translation(QaInput(key,source,source,'bark',('{TARGET}',))),checked_at=NOW,
                         expected_input_hash=state['input_hash'],expected_output_hash=digest(invalid))
        assert qa.get_result(key).qa_status=='stale'
        assert qa.list_by_route('REVIEW')[0].qa_status=='stale'
        review=ProductionReviewStore(db);before=dump(db)
        with pytest.raises(ValueError):review.resolve(**arguments('ACCEPT',key))
        assert dump(db)==before
        assert review.get_current_acceptance(key,current_output_hash=digest(invalid)) is None
        assert build_production_completion_view(db,binding.batch_plan).rows[0].disposition=='BLOCKED'
        bridge=build_final_merge_bridge(db_path=db,batch_plan_path=binding.batch_plan,extract_manifest_path=extract,output_dir=tmp_path/'bridge')
        assert bridge['mergeReadyCount']==0
        with pytest.raises(RuntimeError):finalize_production_workspace(ProductionFinalizeRequest(workspace,tmp_path/'final',container='loca-only'),rebuild_backend=final_fixture.FakeFinalizeBackend())
        assert not (tmp_path/'final/production-final-manifest.json').exists()
        run_workspace_qa(workspace)
        assert qa.get_result(key).route=='RETRY'
    finally:temp.cleanup()
