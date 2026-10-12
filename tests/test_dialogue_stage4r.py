"""Snapshot equivalence/mutation/concurrency and anonymous replay fixtures."""
from pathlib import Path
from dataclasses import replace
import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from bg3loc.dialogue_context import DialogueContextValidationError, canonical_bytes, fingerprint
from bg3loc.sealed_snapshot import SealedRunSnapshot
from bg3loc.translation_request import BatchMaterialResolver
from bg3loc.execution_state import ClaimedAttempt
from bg3loc.dialogue_semantic_replay import prepare_semantic_replay, import_semantic_replay_responses, validate_semantic_replay_review
from test_dialogue_stage2 import fixture, parameters, ruleset, request
from test_dialogue_stage1 import context


def resolver_fixture(root):
    manifest,store,plan,materials,_=fixture(root)
    resolver=BatchMaterialResolver(plan,input_parameters=parameters(),stage2_validation_only=True)
    state=store.get_state(context().target_binding.content_uid)
    claim=ClaimedAttempt(1,'preview',state['content_uid'],state['batch_id'],1,state['input_hash'],'owner','future')
    return manifest,store,plan,materials,resolver,claim


def test_full_validation_once_and_no_shared_mutable_material(tmp_path):
    from bg3loc.sealed_snapshot import validate_stage2_workspace as original
    with patch('bg3loc.sealed_snapshot.validate_stage2_workspace',wraps=original) as validate:
        *_,resolver,claim=resolver_fixture(tmp_path/'fixture')
        first=resolver.resolve(claim)
        for _ in range(20):assert resolver.resolve(claim)==first
        assert validate.call_count==1
        with pytest.raises(TypeError):resolver._sealed_snapshot.items[claim.content_uid]=None
        with pytest.raises(AttributeError):resolver._sealed_snapshot.items={}
        copy=resolver._sealed_snapshot.items[claim.content_uid].material_copy();copy['sourceText']='changed'
        assert resolver.resolve(claim).source_text!=copy['sourceText']
        resolver.close()


@pytest.mark.parametrize('artifact',['manifest','plan','material','ruleset','summary','classification','asset_manifest'])
def test_runtime_file_mutation_prevented_or_fails_closed(tmp_path,artifact):
    manifest,store,plan,materials,resolver,claim=resolver_fixture(tmp_path/'fixture');root=store.path.parent
    paths={'manifest':root/'production-manifest.json','plan':plan,'material':materials[0],'ruleset':root/manifest['inputs']['ruleset']['path'],
           'summary':root/manifest['dialogueContext']['summaryPath'],'classification':root/manifest['classification']['automaticPath'],'asset_manifest':root/manifest['finalizeAssets']['path']}
    path=paths[artifact]
    try:path.write_bytes(path.read_bytes()+b' ')
    except PermissionError:
        assert resolver.resolve(claim).input_hash==claim.input_hash
    else:
        with pytest.raises(DialogueContextValidationError):resolver.resolve(claim)
    resolver.close()


def test_nonlocking_fallback_rehashes_even_when_size_and_mtime_are_preserved(tmp_path,monkeypatch):
    import os
    from bg3loc.sealed_snapshot import _PinnedFiles
    def no_lock(self):
        self.handles=[];self.paths=set();self.identities={};self.windows=False
    monkeypatch.setattr(_PinnedFiles,'__init__',no_lock)
    manifest,store,_,_,resolver,claim=resolver_fixture(tmp_path/'fixture');resolver.resolve(claim)
    path=store.path.parent/manifest['dialogueContext']['summaryPath'];info=path.stat();data=path.read_bytes()
    path.write_bytes(data[:-1]+(b' ' if data[-1:]==b'\n' else b'\n'))
    os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns))
    assert path.stat().st_size==info.st_size and path.stat().st_mtime_ns==info.st_mtime_ns
    with pytest.raises(DialogueContextValidationError):resolver.resolve(claim)
    resolver.close()


def test_cross_process_write_and_stripping_are_denied_while_snapshot_alive(tmp_path):
    *_,resolver,claim=resolver_fixture(tmp_path/'fixture')
    code="from pathlib import Path; import sys; p=Path(sys.argv[1]);\ntry:p.unlink()\nexcept PermissionError:print('DENIED')\nelse:print('REMOVED')"
    result=subprocess.run([sys.executable,'-c',code,str(resolver.batch_plan_path.parent.parent/'production-manifest.json')],text=True,capture_output=True,check=True)
    if resolver._sealed_snapshot._pins.windows:assert 'DENIED' in result.stdout
    else:
        with pytest.raises((DialogueContextValidationError,OSError)):resolver.resolve(claim)
    resolver.close()


@pytest.mark.parametrize('mutation',['input','foreign_item','missing_item','metadata','batch'])
def test_db_mutation_coverage_after_generation_change(tmp_path,mutation):
    _,store,_,_,resolver,claim=resolver_fixture(tmp_path/'fixture');resolver.resolve(claim)
    with store.connect() as conn:
        if mutation=='input':conn.execute('UPDATE content_state SET input_hash=? WHERE content_uid=?',(fingerprint('new'),claim.content_uid))
        elif mutation=='metadata':conn.execute("UPDATE metadata SET value='stripped' WHERE key='executionContextContractFingerprint'")
        elif mutation=='batch':conn.execute("UPDATE content_state SET batch_id='foreign' WHERE content_uid=?",(claim.content_uid,))
        elif mutation=='missing_item':conn.execute('DELETE FROM content_state WHERE content_uid!=?',(claim.content_uid,))
        else:conn.execute("INSERT INTO content_state(content_uid,batch_id,status,input_hash,updated_at) VALUES('foreign','foreign','pending','foreign','now')")
        conn.commit()
    with pytest.raises(DialogueContextValidationError):resolver.resolve(claim)
    resolver.close()


def test_legal_qa_output_changes_and_shared_worker_reads_remain_current(tmp_path):
    _,store,_,_,resolver,claim=resolver_fixture(tmp_path/'fixture');first=resolver.resolve(claim)
    with store.connect() as conn:conn.execute("UPDATE content_state SET updated_at='QA commit' WHERE content_uid=?",(claim.content_uid,));conn.commit()
    assert resolver.resolve(claim)==first
    with ThreadPoolExecutor(max_workers=4) as pool:assert all(r==first for r in pool.map(lambda _:resolver.resolve(claim),range(30)))
    resolver.close()


def test_current_running_owner_and_attempt_are_not_cached(tmp_path):
    _,store,_,_,resolver,claim=resolver_fixture(tmp_path/'fixture')
    with store.connect() as conn:
        conn.execute("UPDATE content_state SET status='running',last_attempt_id=NULL,lease_owner='other-owner',lease_expires_at='future' WHERE content_uid=?",(claim.content_uid,));conn.commit()
    with pytest.raises(DialogueContextValidationError):resolver.resolve(claim)
    resolver.close()


def test_startup_mutation_between_capture_and_validation_is_detected(tmp_path,monkeypatch):
    from bg3loc.sealed_snapshot import validate_stage2_workspace as original
    manifest,store,plan,materials,_=fixture(tmp_path/'fixture')
    def race(*a,**kw):
        try:materials[0].write_bytes(materials[0].read_bytes()+b' ')
        except PermissionError:pass
        return original(*a,**kw)
    monkeypatch.setattr('bg3loc.sealed_snapshot.validate_stage2_workspace',race)
    try:snapshot=SealedRunSnapshot(store.path.parent)
    except DialogueContextValidationError:return
    assert snapshot._pins.windows;snapshot.close()


def test_closed_snapshot_and_resume_use_new_full_validation(tmp_path):
    _,store,plan,materials,resolver,claim=resolver_fixture(tmp_path/'fixture');resolver.resolve(claim);resolver.close()
    with pytest.raises(DialogueContextValidationError):resolver.resolve(claim)
    materials[0].write_bytes(materials[0].read_bytes()+b' ')
    with pytest.raises(DialogueContextValidationError):BatchMaterialResolver(plan,input_parameters=parameters(),stage2_validation_only=True)


def test_database_file_cannot_be_replaced_beneath_live_snapshot(tmp_path):
    _,store,_,_,resolver,claim=resolver_fixture(tmp_path/'fixture');resolver.resolve(claim)
    import shutil
    replacement=tmp_path/'replacement.sqlite3';shutil.copyfile(store.path,replacement)
    try:replacement.replace(store.path)
    except PermissionError:assert resolver.resolve(claim).input_hash==claim.input_hash
    else:
        with pytest.raises(DialogueContextValidationError):resolver.resolve(claim)
    resolver.close()


@pytest.mark.parametrize('race_read',['SELECT key,value FROM metadata','SELECT * FROM content_state WHERE'])
def test_db_commit_between_current_read_and_return_is_rechecked(tmp_path,race_read):
    _,store,_,_,resolver,claim=resolver_fixture(tmp_path/'fixture');resolver.resolve(claim)
    snapshot=resolver._sealed_snapshot;original=snapshot._db
    class RaceConnection:
        def __init__(self):self.changed=False
        def execute(self,sql,*args):
            result=original.execute(sql,*args)
            if sql=='COMMIT':raise AssertionError('commit method required')
            if sql.startswith(race_read) and not self.changed:
                self.changed=True
                with store.connect() as writer:
                    writer.execute('UPDATE content_state SET input_hash=? WHERE content_uid=?',(fingerprint('raced'),claim.content_uid));writer.commit()
            return result
        def __getattr__(self,name):return getattr(original,name)
    snapshot._db=RaceConnection()
    with pytest.raises(DialogueContextValidationError):resolver.resolve(claim)
    assert snapshot._db.changed;resolver.close()


def test_finalize_snapshot_change_rolls_back_and_never_publishes(tmp_path):
    from test_dialogue_stage4 import prepared,finish_all
    from bg3loc.portable_finalize import finalize_portable_workspace
    from bg3loc.portable_assets import PortableAssetsError
    request,backend,_=prepared(tmp_path/'input');finish_all(request,backend)
    def mutate(conn):conn.execute("UPDATE qa_results SET route='PASS' WHERE route='REVIEW'")
    with pytest.raises(PortableAssetsError):finalize_portable_workspace(request.output_dir,tmp_path/'final',backend=backend,observer=mutate)
    assert not (tmp_path/'final').exists()
    with sqlite3.connect(request.output_dir/'execution.sqlite3') as conn:
        assert conn.execute("SELECT count(*) FROM qa_results WHERE route='REVIEW'").fetchone()[0]>0


def test_finalize_barrier_release_failure_retracts_published_output(tmp_path,monkeypatch):
    from test_dialogue_stage4 import prepared,finish_all
    from bg3loc.portable_finalize import finalize_portable_workspace
    request,backend,_=prepared(tmp_path/'input');finish_all(request,backend)
    original=sqlite3.connect
    class FailingCommit:
        def __init__(self,*args,**kw):self.conn=original(*args,**kw)
        def __getattr__(self,name):return getattr(self.conn,name)
        @property
        def row_factory(self):return self.conn.row_factory
        @row_factory.setter
        def row_factory(self,value):self.conn.row_factory=value
        def commit(self):raise sqlite3.OperationalError('fixture barrier release failure')
    # Only the finalizer's writer connection is replaced; independent read-only
    # validation connections continue using the real SQLite implementation.
    import bg3loc.portable_finalize as module
    from types import SimpleNamespace
    monkeypatch.setattr(module,'sqlite3',SimpleNamespace(connect=FailingCommit,Row=sqlite3.Row))
    with pytest.raises(sqlite3.OperationalError,match='fixture barrier release'):
        finalize_portable_workspace(request.output_dir,tmp_path/'final',backend=backend)
    assert not (tmp_path/'final').exists()


def replay_fixture(tmp_path):
    package=tmp_path/'replay';prepare_semantic_replay(package,request(context()),ruleset())
    rows=[json.loads(line) for line in (package/'chatgpt-translation-requests.jsonl').read_text(encoding="utf-8").splitlines()]
    responses=tmp_path/'responses.jsonl';responses.write_bytes(b''.join(canonical_bytes({'requestId':r['requestId'],'translationText':'虛構譯文'})+b'\n' for r in rows))
    return package,rows,responses


def test_anonymous_formal_replay_and_blind_import_never_verdict(tmp_path):
    package,rows,responses=replay_fixture(tmp_path)
    assert len(rows)==2 and all(set(r)=={'requestId','messages'} for r in rows)
    wire=[json.loads(r['messages'][1]['content']) for r in rows]
    assert sum('dialogueContext'in r for r in wire)==1
    assert not any('condition'in r or 'variantId'in r for r in rows)
    result=import_semantic_replay_responses(package,responses,translation_source='external fictional source')
    assert result['safetyRegression']=='NOT_EVALUATED'
    review=json.loads((package/'blind-review-ready.jsonl').read_text(encoding="utf-8"))
    assert set(review['translations'])=={'variant-1','variant-2'} and 'condition' not in review
    assert all(v is None for v in review['assessment'].values())


@pytest.mark.parametrize('bad',['missing','duplicate','unknown','null','unknown_field','runtime_token'])
def test_replay_import_rejects_bad_outputs_without_blind_publication(tmp_path,bad):
    package,rows,responses=replay_fixture(tmp_path);data=[{'requestId':r['requestId'],'translationText':'虛構譯文'} for r in rows]
    if bad=='missing':data.pop()
    elif bad=='duplicate':data.append(data[0])
    elif bad=='unknown':data[0]['requestId']='unknown'
    elif bad=='null':data[0]['translationText']=None
    elif bad=='unknown_field':data[0]['condition']='leak'
    else:data[0]['translationText']='虛構 {UNSUPPORTED}'
    responses.write_bytes(b''.join(canonical_bytes(r)+b'\n' for r in data))
    with pytest.raises(ValueError):import_semantic_replay_responses(package,responses,translation_source='fixture')
    assert not (package/'blind-review-ready.jsonl').exists()


def test_review_schema_source_translation_binding_and_limited_scope(tmp_path):
    package,_,responses=replay_fixture(tmp_path);import_semantic_replay_responses(package,responses,translation_source='fixture')
    review=json.loads((package/'blind-review-ready.jsonl').read_text(encoding="utf-8"))
    review['assessment']={'sourceMeaningPreserved':{'variant-1':True,'variant-2':True},'semanticDriftVariant':'neither',
        'sourceAbsentInformation':{'variant-1':False,'variant-2':False},'alternativesAsSequence':{'variant-1':False,'variant-2':False},'reviewer':'fixture','notes':'known-risk case only'}
    completed=tmp_path/'completed.jsonl';completed.write_bytes(canonical_bytes(review)+b'\n')
    result=validate_semantic_replay_review(package,completed);assert result['scope']=='known-risk-case-only' and 'PASS' not in result['safetyRegression']
    review['translations']['variant-1']='changed';completed.write_bytes(canonical_bytes(review)+b'\n')
    with pytest.raises(ValueError):validate_semantic_replay_review(package,completed)


def test_changed_original_blind_review_cannot_rebind_completed_review(tmp_path):
    package,_,responses=replay_fixture(tmp_path);import_semantic_replay_responses(package,responses,translation_source='fixture')
    review=json.loads((package/'blind-review-ready.jsonl').read_text(encoding="utf-8"));review['targetSource']='changed source'
    (package/'blind-review-ready.jsonl').write_bytes(canonical_bytes(review)+b'\n')
    completed=tmp_path/'completed.jsonl';completed.write_bytes(canonical_bytes(review)+b'\n')
    with pytest.raises(ValueError,match='seal mismatch'):validate_semantic_replay_review(package,completed)
