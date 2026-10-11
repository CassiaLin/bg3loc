"""Fictional offline lifecycle; no production or network transport permitted."""
from argparse import Namespace
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
import sqlite3
from unittest.mock import Mock, patch

import pytest

from bg3loc.commands.translation_qa import run_qa
from bg3loc.dialogue_context import DialogueContextValidationError, fingerprint
from bg3loc.dialogue_review import apply_dialogue_semantic_review, semantic_gate_present, DIALOGUE_SEMANTIC_REVIEW_REQUIRED
from bg3loc.execution_runner import run_worker
from bg3loc.execution_state import TranslationExecutionStore
from bg3loc.prompt_provenance import PromptProvenance
from bg3loc.production_completion import build_production_completion_view, derive_production_disposition
from bg3loc.production_finalize import ProductionFinalizeRequest, finalize_production_workspace, _require_completion_ready
from bg3loc.production_review import ProductionReviewStore
from bg3loc.qa import QaInput, QaResult, QaIssue, QA_RULESET_VERSION, evaluate_translation
from bg3loc.qa_state import TranslationQaStore, StoredQaResult
from bg3loc.translation_request import BatchMaterialResolver
from bg3loc.translation_send import prepare_translation_send
from bg3loc.providers.openai_compatible import OpenAICompatibleChatProvider, OpenAICompatibleChatConfig
from bg3loc.final_merge_bridge import build_final_merge_bridge
from test_dialogue_stage2 import fixture, parameters, ruleset, request
from test_dialogue_stage1 import context
from test_dialogue_context_research import uid, dialogue, node

NOW = '2026-10-10T00:00:00Z'
LATER = '2026-10-10T00:10:00Z'
TEXT = '虛構譯文'


def h(text):
    return sha256(text.encode('utf-8')).hexdigest()


def setup(root):
    manifest,store,plan,materials,results=fixture(root)
    qa=TranslationQaStore(store.path);qa.initialize()
    review=ProductionReviewStore(store.path);review.initialize()
    return store,plan,qa,review


def claim(store, key=uid(1)):
    """Insert fictional running state; public 1.3 start/claim remain blocked."""
    state=store.get_state(key)
    with store.connect() as conn:
        conn.execute("INSERT OR IGNORE INTO runs(run_id,batch_plan_fingerprint,provider,model,prompt_version,execution_config_hash,started_at,status) VALUES('offline','fixture','synthetic','fictional','fixture','fixture',?,'running')",(NOW,))
        number=int(state['attempt_count'])+1
        cursor=conn.execute("INSERT INTO attempts(run_id,content_uid,batch_id,attempt_number,provider,model,started_at,outcome,input_hash) VALUES('offline',?,?,?,'synthetic','fictional',?,'running',?)",
            (key,state['batch_id'],number,NOW,state['input_hash']))
        attempt=int(cursor.lastrowid)
        conn.execute("UPDATE content_state SET status='running',attempt_count=?,last_attempt_id=?,lease_owner='owner',lease_expires_at=? WHERE content_uid=?",(number,attempt,LATER,key));conn.commit()
    return attempt


def resolved_request(store,plan,key=uid(1),attempt=1):
    from bg3loc.execution_state import ClaimedAttempt
    state=store.get_state(key)
    return BatchMaterialResolver(plan,input_parameters=parameters(),stage2_validation_only=True).resolve(
        ClaimedAttempt(attempt,'offline',key,state['batch_id'],state['attempt_count'],state['input_hash'],'owner',LATER))


def persist(store,attempt,prepared,**changes):
    p=prepared.provenance
    kwargs={'attempt_id':attempt,'worker_id':'owner','input_hash':p.input_hash,'context_fingerprint':p.context_fingerprint,
            'dialogue_context_fingerprint':p.dialogue_context_fingerprint,'effective_prompt_hash':p.effective_prompt_hash,
            'chat_messages_fingerprint':p.chat_messages_fingerprint,'prompt_renderer_version':p.prompt_renderer_version,'sent_at':NOW}
    kwargs.update(changes);store.record_prompt_provenance(**kwargs)


def succeeded(store,plan,key=uid(1),text=TEXT):
    attempt=claim(store,key);req=resolved_request(store,plan,key,attempt)
    prepared=prepare_translation_send(req,ruleset());persist(store,attempt,prepared)
    store.complete_success(attempt_id=attempt,worker_id='owner',translated_text=text,output_hash=h(text),finished_at=NOW,stage3_validation_only=True)
    return attempt,prepared


def run_offline_qa(store,plan):
    return run_qa(Namespace(db=store.path,batch_plan=plan,max_items=None,stage3_validation_only=True))


def completion(store,plan):
    return build_production_completion_view(store.path,plan,stage3_validation_only=True)


def human_resolve(review, **kwargs):
    qa = TranslationQaStore(review.path).get_result(kwargs['content_uid'])
    return review.resolve(**kwargs, expected_execution_input_hash=qa.execution_input_hash,
        expected_output_hash=qa.output_hash, expected_qa_input_hash=qa.qa_input_hash,
        expected_qa_rule_set_version=qa.qa_rule_set_version)


def candidate(view,key=uid(1)):
    return next(row for row in view.rows if row.content_uid==key)


def test_migrations_are_additive_idempotent_and_null_history_unknown(tmp_path):
    store,plan,qa,_=setup(tmp_path/'fixture');attempt=claim(store)
    with store.connect() as conn:
        conn.execute('ALTER TABLE attempts DROP COLUMN dialogue_context_fingerprint')
        conn.execute('ALTER TABLE qa_rejected_candidates DROP COLUMN execution_input_hash')
        conn.execute("INSERT INTO qa_rejected_candidates(content_uid,translated_text,output_hash,qa_rule_set_version,qa_input_hash,route,issues_json,rejected_at) VALUES(?,?,'history','history','history','RETRY','[]','history')",(uid(1),TEXT));conn.commit()
    before=store.get_state(uid(1));old=store.get_attempts(uid(1))[0]
    store.initialize(schema_version='1.3');store.initialize(schema_version='1.3');qa.initialize();qa.initialize()
    assert store.get_state(uid(1))==before
    after=store.get_attempts(uid(1))[0]
    assert after['dialogue_context_fingerprint'] is None and all(after[k]==v for k,v in old.items())
    assert qa.get_rejected_candidates(uid(1))[0]['execution_input_hash'] is None
    assert PromptProvenance('input',None,'effective','messages',None).dialogue_context_fingerprint is None


@pytest.mark.parametrize('mode',['success','http500','timeout','retry'])
def test_hd_single_render_persisted_before_offline_delivery_and_failures(tmp_path,mode):
    store,plan,_,_=setup(tmp_path/'fixture');attempt=claim(store)
    req=resolved_request(store,plan,attempt=attempt)
    with patch('bg3loc.translation_send.assemble_translation_prompt',wraps=__import__('bg3loc.prompt_assembly',fromlist=['assemble_translation_prompt']).assemble_translation_prompt) as assembly,\
         patch('bg3loc.translation_send.render_chat_messages',wraps=__import__('bg3loc.chat_prompt',fromlist=['render_chat_messages']).render_chat_messages) as renderer:
        prepared=prepare_translation_send(req,ruleset());persist(store,attempt,prepared)
        assert assembly.call_count==renderer.call_count==1
    def synthetic_delivery():
        record=store.get_attempts(uid(1))[-1]
        assert record['outcome']=='running' and record['dialogue_context_fingerprint']==req.dialogue_context.context_fingerprint
        assert record['context_fingerprint'] is None and record['input_hash']==req.input_hash
        from bg3loc.chat_prompt import chat_messages_fingerprint
        assert record['chat_messages_fingerprint']==chat_messages_fingerprint(prepared.messages)
        assert record['effective_prompt_hash']==prepared.prompt.effective_prompt_hash
        if mode=='timeout':raise TimeoutError('fictional offline timeout')
        return 500 if mode in {'http500','retry'} else 200
    try:status=synthetic_delivery()
    except TimeoutError:status=500
    if status==200:
        store.complete_success(attempt_id=attempt,worker_id='owner',translated_text=TEXT,output_hash=h(TEXT),finished_at=NOW,stage3_validation_only=True)
    else:
        store.complete_failure(attempt_id=attempt,worker_id='owner',error_code='SYNTHETIC_FAILURE',error_message='offline',retryable=True,max_attempts=3,finished_at=NOW)
        assert store.get_attempts(uid(1))[0]['dialogue_context_fingerprint']==prepared.provenance.dialogue_context_fingerprint
    if mode=='retry':
        second=claim(store);again=prepare_translation_send(resolved_request(store,plan,attempt=second),ruleset());persist(store,second,again)
        assert again.provenance==prepared.provenance
        assert [r['attempt_number'] for r in store.get_attempts(uid(1))]==[1,2]


@pytest.mark.parametrize('bad',['owner','input','attempt','lease','fingerprint','renderer','both'])
def test_current_attempt_owner_input_and_provenance_guards(tmp_path,bad):
    store,plan,_,_=setup(tmp_path/'fixture');attempt=claim(store)
    prepared=prepare_translation_send(resolved_request(store,plan,attempt=attempt),ruleset())
    changes={}
    if bad=='owner':changes['worker_id']='other'
    elif bad=='input':changes['input_hash']=fingerprint('stale')
    elif bad=='attempt':
        with store.connect() as conn:conn.execute('UPDATE content_state SET last_attempt_id=NULL WHERE content_uid=?',(uid(1),));conn.commit()
    elif bad=='lease':changes['sent_at']=LATER
    elif bad=='fingerprint':changes['dialogue_context_fingerprint']=fingerprint('other')
    elif bad=='renderer':changes['prompt_renderer_version']='same-entity-prompt/1'
    else:changes['context_fingerprint']=fingerprint('se')
    with pytest.raises(ValueError):persist(store,attempt,prepared,**changes)
    assert store.get_attempts(uid(1))[0]['dialogue_context_fingerprint'] is None


def test_provenance_idempotent_not_overwritable_and_success_requires_it(tmp_path):
    store,plan,_,_=setup(tmp_path/'fixture');attempt=claim(store)
    with pytest.raises(ValueError,match='provenance required'):
        store.complete_success(attempt_id=attempt,worker_id='owner',translated_text=TEXT,output_hash=h(TEXT),finished_at=NOW,stage3_validation_only=True)
    prepared=prepare_translation_send(resolved_request(store,plan,attempt=attempt),ruleset());persist(store,attempt,prepared);persist(store,attempt,prepared)
    with pytest.raises(ValueError,match='already bound'):persist(store,attempt,prepared,effective_prompt_hash=fingerprint('different'))
    with pytest.raises(ValueError):prepare_translation_send(replace(resolved_request(store,plan,attempt=attempt),input_hash=fingerprint('stale')),ruleset())


@pytest.mark.parametrize('family',['H0','HSE','HD'])
@pytest.mark.parametrize('route',['PASS','REVIEW','RETRY','FAIL'])
def test_frozen_qa_route_matrix(family,route):
    technical=QaResult('fictional',route,(),QA_RULESET_VERSION,'qa')
    effective=apply_dialogue_semantic_review(technical,dialogue_context_present=family=='HD')
    expected='REVIEW' if family=='HD' and route in {'PASS','REVIEW'} else route
    assert effective.route==expected and effective.qa_input_hash==technical.qa_input_hash
    assert semantic_gate_present(effective.issues)==(family=='HD' and route in {'PASS','REVIEW'})
    assert apply_dialogue_semantic_review(effective,dialogue_context_present=family=='HD')==effective
    if semantic_gate_present(effective.issues):assert 'not a detected semantic error' in effective.issues[-1].message


def test_missing_semantic_gate_is_not_current_and_run_qa_reroutes(tmp_path):
    store,plan,qa,_=setup(tmp_path/'fixture');succeeded(store,plan)
    result=evaluate_translation(QaInput(uid(1),'Fictional target.',TEXT,'dialogue_general',()))
    assert result.route=='PASS';state=store.get_state(uid(1))
    qa.record_result(result,checked_at=NOW,expected_input_hash=state['input_hash'],expected_output_hash=state['output_hash'])
    view=completion(store,plan)
    assert candidate(view).disposition=='BLOCKED' and candidate(view).reason_code=='DIALOGUE_REVIEW_GATE_NOT_APPLIED'
    assert qa.get_result(uid(1),dialogue_context_required=True).qa_status=='stale'
    run_offline_qa(store,plan)
    gated=qa.get_result(uid(1),dialogue_context_required=True)
    assert gated.qa_status=='checked' and gated.route=='REVIEW' and semantic_gate_present(gated.issues)
    assert candidate(completion(store,plan)).disposition=='WAITING_REVIEW'


def test_current_accept_and_revise_match_identity_and_qa_snapshot(tmp_path):
    store,plan,qa,review=setup(tmp_path/'fixture');succeeded(store,plan);run_offline_qa(store,plan)
    accepted=human_resolve(review, content_uid=uid(1),decision='ACCEPT',reviewer='fictional-human',note='reviewed',resolved_at=NOW,stage3_validation_only=True)
    assert candidate(completion(store,plan)).disposition=='MERGE_READY'
    assert review.get_current_acceptance(uid(1),current_output_hash=h(TEXT)).resolution_id==accepted.resolution_id
    revised=human_resolve(review, content_uid=uid(1),decision='REVISE',reviewer='fictional-human',note='semantic correction',resolved_at=NOW,
                          revised_text='另一段虛構譯文',stage3_validation_only=True)
    current=store.get_state(uid(1));stored=qa.get_result(uid(1),dialogue_context_required=True)
    assert current['output_hash']==revised.resolved_output_hash and stored.output_hash==current['output_hash']
    assert stored.route=='REVIEW' and stored.qa_status=='checked'
    assert candidate(completion(store,plan)).disposition=='MERGE_READY'
    assert review.get_current_acceptance(uid(1),current_output_hash=current['output_hash']).decision=='REVISE'


@pytest.mark.parametrize('text',['','虛構 {UNSUPPORTED}'])
def test_revise_technical_failure_rolls_back_everything(tmp_path,text):
    store,plan,qa,review=setup(tmp_path/'fixture');succeeded(store,plan);run_offline_qa(store,plan)
    before=store.get_state(uid(1));oldqa=qa.get_result(uid(1))
    with pytest.raises(ValueError,match='technical QA'):
        human_resolve(review, content_uid=uid(1),decision='REVISE',reviewer='fictional',note='',resolved_at=NOW,revised_text=text,stage3_validation_only=True)
    assert store.get_state(uid(1))==before and qa.get_result(uid(1))==oldqa
    assert store.connect().execute('SELECT count(*) FROM qa_review_resolutions').fetchone()[0]==0


@pytest.mark.parametrize('change',['input','output','qa_hash','qa_version','missing_gate'])
def test_stale_acceptance_never_reused(tmp_path,change):
    store,plan,qa,review=setup(tmp_path/'fixture');succeeded(store,plan);run_offline_qa(store,plan)
    human_resolve(review, content_uid=uid(1),decision='ACCEPT',reviewer='fictional',note='',resolved_at=NOW,stage3_validation_only=True)
    with store.connect() as conn:
        if change=='input':conn.execute('UPDATE content_state SET input_hash=? WHERE content_uid=?',(fingerprint('new context same output'),uid(1)))
        elif change=='output':conn.execute('UPDATE content_state SET translated_text=?,output_hash=? WHERE content_uid=?',('changed',h('changed'),uid(1)))
        elif change=='qa_hash':conn.execute('UPDATE qa_results SET qa_input_hash=? WHERE content_uid=?',(fingerprint('changed QA'),uid(1)))
        elif change=='qa_version':conn.execute('UPDATE qa_results SET qa_rule_set_version=? WHERE content_uid=?',('unsupported',uid(1)))
        else:conn.execute('DELETE FROM qa_issues WHERE content_uid=?',(uid(1),))
        conn.commit()
    if change=='input':
        with pytest.raises(DialogueContextValidationError):completion(store,plan)
        return
    assert candidate(completion(store,plan)).disposition!='MERGE_READY'
    assert review.get_current_acceptance(uid(1),current_output_hash=store.get_state(uid(1))['output_hash']) is None


def test_retry_archive_and_reopen_are_atomic_and_input_bound(tmp_path):
    store,plan,qa,_=setup(tmp_path/'fixture');succeeded(store,plan,text='虛構 {UNSUPPORTED}');run_offline_qa(store,plan)
    stored=qa.get_result(uid(1));assert stored.route=='RETRY'
    result=evaluate_translation(QaInput(uid(1),'Fictional target.','虛構 {UNSUPPORTED}','dialogue_general',()))
    original=store.get_state(uid(1));qa.handoff_retry(result,max_attempts=3,rejected_at=NOW,expected_input_hash=original['input_hash'],expected_output_hash=original['output_hash'])
    archive=qa.get_rejected_candidates(uid(1))[0];new=store.get_state(uid(1))
    assert archive['execution_input_hash']==original['input_hash']==new['input_hash']
    assert archive['translated_text']==original['translated_text'] and new['translated_text'] is None and new['status']=='failed-retryable'


def test_retry_archive_rolls_back_when_reopen_fails(tmp_path):
    store,plan,qa,_=setup(tmp_path/'fixture');succeeded(store,plan,text='虛構 {UNSUPPORTED}');run_offline_qa(store,plan)
    result=evaluate_translation(QaInput(uid(1),'Fictional target.','虛構 {UNSUPPORTED}','dialogue_general',()))
    before=store.get_state(uid(1))
    with store.connect() as conn:
        conn.execute("CREATE TRIGGER forbid_reopen BEFORE UPDATE OF status ON content_state WHEN NEW.status='failed-retryable' BEGIN SELECT RAISE(ABORT,'fixture rollback'); END");conn.commit()
    with pytest.raises(sqlite3.IntegrityError):qa.handoff_retry(result,max_attempts=3,rejected_at=NOW,
        expected_input_hash=before['input_hash'],expected_output_hash=before['output_hash'])
    assert qa.get_rejected_candidates(uid(1))==[] and store.get_state(uid(1))==before


def test_review_transaction_detects_qa_snapshot_race(tmp_path,monkeypatch):
    store,plan,qa,review=setup(tmp_path/'fixture');succeeded(store,plan);run_offline_qa(store,plan)
    original=TranslationQaStore.get_result
    def changed(self,*a,**kw):
        result=original(self,*a,**kw)
        with store.connect() as conn:conn.execute('UPDATE qa_results SET qa_input_hash=? WHERE content_uid=?',(fingerprint('raced QA'),uid(1)));conn.commit()
        return result
    monkeypatch.setattr(TranslationQaStore,'get_result',changed)
    with pytest.raises(ValueError,match='snapshot changed'):
        human_resolve(review, content_uid=uid(1),decision='ACCEPT',reviewer='fixture',note='',resolved_at=NOW,stage3_validation_only=True)
    assert store.connect().execute('SELECT count(*) FROM qa_review_resolutions').fetchone()[0]==0


def test_production_stop_guards_and_finalize_cannot_be_bypassed(tmp_path):
    store,plan,_,_=setup(tmp_path/'fixture');transport=Mock()
    engine=OpenAICompatibleChatProvider(config=OpenAICompatibleChatConfig('https://example.test','fictional'),ruleset=ruleset(),transport=transport)
    assert engine(request(context())).error_code=='CONTEXT_CONTRACT_MISMATCH';transport.post_json.assert_not_called()
    with pytest.raises(DialogueContextValidationError):run_worker(store,run_id='fake',worker_id='fake',provider=Mock())
    with pytest.raises(DialogueContextValidationError):build_production_completion_view(store.path,plan)
    backend=Mock()
    with pytest.raises(DialogueContextValidationError):finalize_production_workspace(ProductionFinalizeRequest(store.path.parent,tmp_path/'output'),rebuild_backend=backend)
    assert not (tmp_path/'output').exists()
    with pytest.raises(DialogueContextValidationError):build_final_merge_bridge(db_path=store.path,batch_plan_path=plan,extract_manifest_path=store.path.parent/'production-manifest.json',output_dir=tmp_path/'bridge')
    assert not (tmp_path/'bridge').exists()
    with pytest.raises(RuntimeError):_require_completion_ready(completion(store,plan))


def test_case006_style_offline_human_semantic_correction(tmp_path,monkeypatch):
    import test_dialogue_stage2 as producer
    data=dialogue([node('T',text=uid(1),children=[f'S{i}' for i in range(13)])]+
                  [node(f'P{i}',text=uid(10+i),children=['T']) for i in range(3)]+
                  [node(f'S{i}',text=uid(20+i)) for i in range(13)])
    source={uid(1):'Fictional target.',**{uid(10+i):f'Possible fictional predecessor {i}.' for i in range(3)},
            **{uid(20+i):f'Possible fictional branch {i}.' for i in range(13)}}
    monkeypatch.setattr(producer,'sources',lambda:source);monkeypatch.setattr(producer,'graph_data',lambda:data)
    store,plan,_,review=setup(tmp_path/'fixture');succeeded(store,plan);run_offline_qa(store,plan)
    assert candidate(completion(store,plan)).disposition=='WAITING_REVIEW'
    human_resolve(review, content_uid=uid(1),decision='REVISE',reviewer='fictional-human',note='correct possible meaning drift',resolved_at=NOW,
                   revised_text='人工修正的虛構譯文',stage3_validation_only=True)
    assert candidate(completion(store,plan)).disposition=='MERGE_READY'


def test_missing_dialogue_provenance_cannot_be_recorded_as_baseline(tmp_path):
    store,plan,_,_=setup(tmp_path/'fixture');attempt=claim(store)
    prepared=prepare_translation_send(resolved_request(store,plan,attempt=attempt),ruleset())
    with pytest.raises(ValueError):persist(store,attempt,prepared,dialogue_context_fingerprint=None,prompt_renderer_version=None)
    assert store.get_attempts(uid(1))[0]['effective_prompt_hash'] is None


@pytest.mark.parametrize('change',['input','output','route','qa_version','missing_snapshot'])
def test_retry_handoff_rejects_stale_snapshot_without_archiving(tmp_path,change):
    store,plan,qa,_=setup(tmp_path/'fixture');succeeded(store,plan,text='虛構 {UNSUPPORTED}');run_offline_qa(store,plan)
    before=store.get_state(uid(1));result=evaluate_translation(QaInput(uid(1),'Fictional target.','虛構 {UNSUPPORTED}','dialogue_general',()))
    with store.connect() as conn:
        if change=='input':conn.execute('UPDATE content_state SET input_hash=? WHERE content_uid=?',(fingerprint('new context'),uid(1)))
        elif change=='output':conn.execute('UPDATE content_state SET output_hash=? WHERE content_uid=?',(h('changed output'),uid(1)))
        elif change=='route':conn.execute("UPDATE qa_results SET route='REVIEW' WHERE content_uid=?",(uid(1),))
        elif change=='qa_version':conn.execute("UPDATE qa_results SET qa_rule_set_version='other' WHERE content_uid=?",(uid(1),))
        conn.commit()
    kwargs={} if change=='missing_snapshot' else {'expected_input_hash':before['input_hash'],'expected_output_hash':before['output_hash']}
    with pytest.raises(ValueError):qa.handoff_retry(result,max_attempts=3,rejected_at=NOW,**kwargs)
    assert qa.get_rejected_candidates(uid(1))==[]


@pytest.mark.parametrize('route',['FAIL','RETRY'])
def test_hd_technical_failure_routes_do_not_become_review_or_merge_ready(tmp_path,route):
    store,plan,qa,_=setup(tmp_path/'fixture');succeeded(store,plan)
    state=store.get_state(uid(1))
    result=apply_dialogue_semantic_review(QaResult(uid(1),route,(),QA_RULESET_VERSION,fingerprint('technical QA')),dialogue_context_present=True)
    qa.record_result(result,checked_at=NOW,expected_input_hash=state['input_hash'],expected_output_hash=state['output_hash'])
    row=candidate(completion(store,plan))
    assert row.qa_route==route and row.disposition==('BLOCKED' if route=='FAIL' else 'WAITING_RETRY')


def test_null_bound_qa_and_review_stay_unknown_in_hd_workspace(tmp_path):
    store,plan,qa,review=setup(tmp_path/'fixture');succeeded(store,plan);run_offline_qa(store,plan)
    human_resolve(review, content_uid=uid(1),decision='ACCEPT',reviewer='fixture',note='',resolved_at=NOW,stage3_validation_only=True)
    with store.connect() as conn:conn.execute('UPDATE qa_review_resolutions SET execution_input_hash=NULL');conn.commit()
    assert candidate(completion(store,plan)).disposition=='WAITING_REVIEW'
    assert review.get_current_acceptance(uid(1),current_output_hash=h(TEXT)) is None
    with store.connect() as conn:conn.execute('UPDATE qa_results SET execution_input_hash=NULL');conn.commit()
    assert candidate(completion(store,plan)).disposition=='BLOCKED'
    assert qa.get_result(uid(1),dialogue_context_required=True).qa_status=='stale'


def test_human_snapshot_is_required_and_stale_same_output_submission_rejected(tmp_path):
    store,plan,qa,review=setup(tmp_path/'fixture');succeeded(store,plan);run_offline_qa(store,plan)
    snapshot=qa.get_result(uid(1))
    with pytest.raises(ValueError,match='snapshot'):
        review.resolve(content_uid=uid(1),decision='ACCEPT',reviewer='fictional',note='',resolved_at=NOW,stage3_validation_only=True)
    with pytest.raises(ValueError,match='snapshot'):
        review.resolve(content_uid=uid(1),decision='ACCEPT',reviewer='fictional',note='',resolved_at=NOW,stage3_validation_only=True,
            expected_execution_input_hash=fingerprint('old context identical output'),expected_output_hash=snapshot.output_hash,
            expected_qa_input_hash=snapshot.qa_input_hash,expected_qa_rule_set_version=snapshot.qa_rule_set_version)
    assert store.connect().execute('SELECT count(*) FROM qa_review_resolutions').fetchone()[0]==0


def test_hd_export_carries_review_snapshot_and_source_only_grouping(tmp_path):
    from bg3loc.commands.translation_qa import run_review_export
    store,plan,qa,_=setup(tmp_path/'fixture');succeeded(store,plan);run_offline_qa(store,plan)
    path=tmp_path/'review.jsonl'
    run_review_export(Namespace(db=store.path,batch_plan=plan,output=path,stage3_validation_only=True))
    rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    assert len(rows)==1
    row=rows[0];assert row['ExecutionInputHash']==store.get_state(uid(1))['input_hash']
    assert row['QaInputHash']==qa.get_result(uid(1)).qa_input_hash
    assert set(row['dialogueContext'])=={'relationType','relationSemantics','possiblePredecessors','possibleSuccessors'}
    for group in row['dialogueContext']['possiblePredecessors']+row['dialogueContext']['possibleSuccessors']:
        assert set(group)=={'sourceVariants'} and all(set(v)=={'sourceText'} for v in group['sourceVariants'])


def test_fresh_context_identical_output_cannot_reuse_old_review_or_submission(tmp_path,monkeypatch):
    first,plan1,qa1,review1=setup(tmp_path/'before');succeeded(first,plan1);run_offline_qa(first,plan1)
    oldqa=qa1.get_result(uid(1));human_resolve(review1,content_uid=uid(1),decision='ACCEPT',reviewer='fixture',note='',resolved_at=NOW,stage3_validation_only=True)
    record=dict(first.connect().execute('SELECT * FROM qa_review_resolutions').fetchone())
    import test_dialogue_stage2 as producer
    source=producer.sources();source[uid(4)]='Different fictional context wording.'
    monkeypatch.setattr(producer,'sources',lambda:source)
    second,plan2,qa2,review2=setup(tmp_path/'after');succeeded(second,plan2);run_offline_qa(second,plan2)
    newqa=qa2.get_result(uid(1))
    assert oldqa.qa_input_hash==newqa.qa_input_hash and oldqa.output_hash==newqa.output_hash
    assert oldqa.execution_input_hash!=newqa.execution_input_hash
    columns=[k for k in record if k!='resolution_id']
    with second.connect() as conn:
        conn.execute('INSERT INTO qa_review_resolutions('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',tuple(record[k] for k in columns));conn.commit()
    assert candidate(completion(second,plan2)).disposition=='WAITING_REVIEW'
    assert review2.get_current_acceptance(uid(1),current_output_hash=h(TEXT)) is None
    with pytest.raises(ValueError,match='snapshot'):
        review2.resolve(content_uid=uid(1),decision='ACCEPT',reviewer='fixture',note='',resolved_at=NOW,stage3_validation_only=True,
            expected_execution_input_hash=oldqa.execution_input_hash,expected_output_hash=oldqa.output_hash,
            expected_qa_input_hash=oldqa.qa_input_hash,expected_qa_rule_set_version=oldqa.qa_rule_set_version)


@pytest.mark.parametrize('route',['PASS','REVIEW'])
def test_human_acceptance_cannot_override_missing_semantic_gate(route):
    state={'content_uid':'fictional','batch_id':'fictional','status':'succeeded','translated_text':TEXT,'output_hash':h(TEXT),
           'input_hash':fingerprint('HD'),'attempt_count':1}
    qa=StoredQaResult('fictional','checked',route,0,QA_RULESET_VERSION,fingerprint('QA'),h(TEXT),NOW,(),state['input_hash'])
    row=derive_production_disposition(state,primary_category='dialogue_general',qa_result=qa,human_review_accepted=True,dialogue_context_required=True)
    assert row.disposition=='BLOCKED' and row.reason_code=='DIALOGUE_REVIEW_GATE_NOT_APPLIED'
