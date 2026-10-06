"""Fictional hash, resume, attempt and stale-acceptance boundaries. Mock HTTP only."""
from argparse import Namespace
from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import random
import sqlite3
from unittest.mock import patch

import pytest

from bg3loc.chat_prompt import chat_messages_fingerprint, render_chat_messages
from bg3loc.commands.translation_state import load_execution_items, run_init, run_openai_compatible_start, run_openai_compatible_worker
from bg3loc.execution_runner import run_worker
from bg3loc.execution_state import TranslationExecutionStore, ExecutionItem
from bg3loc.production_completion import build_production_completion_view
from bg3loc.production_finalize import _require_completion_ready
from bg3loc.production_orchestration import prepare_production_workspace
from bg3loc.production_review import ProductionReviewStore
from bg3loc.production_workspace import verify_production_workspace
from bg3loc.prompt_assembly import assemble_translation_prompt
from bg3loc.providers.openai_compatible import openai_compatible_execution_config_hash
from bg3loc.qa import QaInput, evaluate_translation
from bg3loc.qa_state import TranslationQaStore
from bg3loc.same_entity_context import fingerprint, source_text_sha256, build_same_entity_context, SameEntitySourceRecord, StructuralIdentityKind
from bg3loc.translation_identity import TranslationInputParameters, translation_input_hash, execution_context_contract
from bg3loc.translation_request import BatchMaterialResolver
from test_same_entity_prompt_integration import baseline_request, with_context, resign, material_fixture, write_material, provider, ruleset, Transport
from test_production_context import fixture as public_fixture

GOLDEN = json.loads((Path(__file__).parent / 'fixtures/b1_02/p4-identity-baseline.json').read_text(encoding='utf8'))


def parameters():
    return TranslationInputParameters(**GOLDEN['parameters'])


def item_hash(request, params=None, protected=None):
    return translation_input_hash(content_uid=request.content_uid, source_text=request.source_text,
        category=request.primary_category, protected_syntax=protected, parameters=params or parameters(), context=request.same_entity_context)


def store_for(root, request):
    plan, path, row = material_fixture(root, request, context=request.same_entity_context is not None)
    _, items = load_execution_items(plan, **GOLDEN['parameters'])
    store = TranslationExecutionStore(root / 'execution.sqlite3')
    store.initialize()
    store.seed_items(items, updated_at='fictional-seed')
    return store, plan, path, row


def start(store, name):
    store.start_run(run_id=name, batch_plan_fingerprint='fictional-p3-plan', provider='mock', model='fictional',
        prompt_version='fictional-p3-v1', execution_config_hash='fictional-config', started_at='2026-10-06T00:00:00Z')


def execute(store, plan, transport, name='fictional-run', max_attempts=1):
    start(store, name)
    engine = provider(transport)
    resolver = BatchMaterialResolver(plan, input_parameters=parameters())
    return run_worker(store, run_id=name, worker_id='fictional-worker', provider=engine,
                      request_resolver=resolver.resolve, max_attempts=max_attempts)


def test_exact_legacy_hash_and_execution_config_golden(tmp_path):
    request = baseline_request()
    plan, _, _ = material_fixture(tmp_path, request, context=False)
    _, items = load_execution_items(plan, **GOLDEN['parameters'])
    assert items[0].input_hash == item_hash(request) == GOLDEN['inputHash']
    assert openai_compatible_execution_config_hash(provider(Transport()).config, ruleset()) == GOLDEN['executionConfigHash']


def test_context_add_remove_identity_branches():
    absent, present = baseline_request(), with_context()
    assert item_hash(present) != item_hash(absent)
    assert item_hash(replace(present, same_entity_context=None)) == GOLDEN['inputHash']


@pytest.mark.parametrize('field', ['source', 'related_role', 'target_role', 'truncated', 'evidence'])
def test_context_component_change_changes_input_hash(field):
    request = with_context(text='Frozen energy ' * 400, truncated=True) if field == 'truncated' else with_context()
    context = request.same_entity_context
    if field == 'target_role':
        changed = replace(context, target_field_role='TechnicalDescription')
    elif field == 'evidence':
        changed = replace(context, evidence_fingerprint=fingerprint('fictional-other-definition-evidence'))
    else:
        sibling = context.related_fields[0]
        sibling = replace(sibling, **{'source': {'source_text': 'Different frozen contextual energy.'},
            'related_role': {'field_role': 'ShortDescription'}, 'truncated': {'truncated': False}}[field])
        changed = replace(context, related_fields=(sibling,))
    assert item_hash(request) != item_hash(replace(request, same_entity_context=resign(changed)))


@pytest.mark.parametrize('key', ['prompt_version', 'ruleset_fingerprint', 'source_locale', 'target_locale'])
def test_legacy_components_change_both_branches(key):
    modified = replace(parameters(), **{key: 'fictional-changed-value'})
    for request in (baseline_request(), with_context()):
        assert item_hash(request, modified) != item_hash(request)


def test_target_source_category_and_protected_syntax_binding():
    for request in (baseline_request(), with_context()):
        changed_source = 'Another Frost Spark {TARGET}'
        context = request.same_entity_context
        if context is not None:
            context = resign(replace(context, target_binding=replace(context.target_binding, source_text_sha256=source_text_sha256(changed_source))))
        assert item_hash(replace(request, source_text=changed_source, same_entity_context=context)) != item_hash(request)
        assert item_hash(request, protected=['{TARGET}']) != item_hash(request)
    assert item_hash(with_context('item')) != item_hash(with_context('skill_spell'))


@pytest.mark.parametrize('version_field,module_name', [('policy_version', 'POLICY_VERSION'), ('schema_version', 'SCHEMA_VERSION')])
def test_future_supported_context_version_changes_identity_without_reopening_current_policy(monkeypatch, version_field, module_name):
    request = with_context()
    previous = item_hash(request)
    modified = resign(replace(request.same_entity_context, **{version_field: 'fictional-supported-next/999'}))
    with pytest.raises(ValueError):
        item_hash(replace(request, same_entity_context=modified))
    # Simulate a future supported runtime in a test only. Production constants
    # remain same-entity-context/1 and b1-02-structural/2.
    monkeypatch.setattr('bg3loc.same_entity_context.' + module_name, 'fictional-supported-next/999')
    assert item_hash(replace(request, same_entity_context=modified)) != previous


def test_renderer_version_and_fixed_safety_bind_only_context_items(monkeypatch):
    context_hash = item_hash(with_context())
    monkeypatch.setattr('bg3loc.prompt_assembly.SAME_ENTITY_PROMPT_VERSION', 'same-entity-prompt/999')
    assert item_hash(with_context()) != context_hash
    assert item_hash(baseline_request()) == GOLDEN['inputHash']
    version_hash = item_hash(with_context())
    from bg3loc.prompt_assembly import SAME_ENTITY_CONTEXT_SAFETY_INSTRUCTIONS
    new_policy = (*SAME_ENTITY_CONTEXT_SAFETY_INSTRUCTIONS, 'Fictional revised safety policy.')
    monkeypatch.setattr('bg3loc.prompt_assembly.SAME_ENTITY_CONTEXT_SAFETY_INSTRUCTIONS', new_policy)
    monkeypatch.setattr('bg3loc.chat_prompt.SAME_ENTITY_CONTEXT_SAFETY_INSTRUCTIONS', new_policy)
    assert item_hash(with_context()) != version_hash
    assert item_hash(baseline_request()) == GOLDEN['inputHash']


def test_source_record_order_does_not_change_canonical_context_hash():
    request = baseline_request()
    target = SameEntitySourceRecord(request.content_uid, 'skill_spell', 'StatsEntry', 'Skill_FrostSpark', 'DisplayName', request.source_text,
        StructuralIdentityKind.STATS_ENTRY_NAME, 'Fixture.pak/Public/Spells.txt', fingerprint('target'), fingerprint('whole'))
    records = [target, replace(target, content_uid='fictional-description', field_role='Description', source_text='Frozen energy.', evidence_fingerprint=fingerprint('detail')),
               replace(target, content_uid='fictional-short', field_role='ShortDescription', source_text='Brief frozen energy.', evidence_fingerprint=fingerprint('short'))]
    first = build_same_entity_context(target, records).context
    random.Random(15).shuffle(records)
    second = build_same_entity_context(target, records).context
    assert first == second
    assert item_hash(replace(request, same_entity_context=first)) == item_hash(replace(request, same_entity_context=second))


@pytest.mark.parametrize('transition', ['same', 'changed', 'added', 'removed'])
def test_success_resume_only_for_same_identity(tmp_path, transition):
    original = baseline_request() if transition == 'added' else with_context()
    store, plan, path, row = store_for(tmp_path, original)
    assert execute(store, plan, Transport()).succeeded == 1
    if transition == 'added':
        changed = with_context()
    elif transition == 'removed':
        changed = replace(original, same_entity_context=None)
    elif transition == 'changed':
        field = replace(original.same_entity_context.related_fields[0], source_text='New frozen contextual details.')
        changed = replace(original, same_entity_context=resign(replace(original.same_entity_context, related_fields=(field,))))
    else:
        changed = original
    old_hash = store.get_state(original.content_uid)['input_hash']
    if changed.same_entity_context is None:
        row.pop('sameEntityContext', None)
    else:
        row['sameEntityContext'] = changed.same_entity_context.to_dict()
    write_material(path, row)
    _, items = load_execution_items(plan, **GOLDEN['parameters'])
    store.seed_items(items, updated_at='fictional-reconciliation-test')
    state = store.get_state(original.content_uid)
    assert (state['input_hash'] == old_hash) == (transition == 'same')
    assert state['status'] == ('succeeded' if transition == 'same' else 'invalidated')
    assert build_production_completion_view(store.path, plan).counts['MERGE_READY'] == 0
    if transition == 'same':
        assert execute(store, plan, Transport(), name='same-resume').claimed == 0


@pytest.mark.parametrize('mode', ['success', 'http500', 'timeout', 'absent'])
def test_actual_attempt_provenance_persisted_before_transport_even_on_failures(tmp_path, mode):
    request = baseline_request() if mode == 'absent' else with_context()
    store, plan, _, _ = store_for(tmp_path, request)
    class ObservingTransport(Transport):
        def post_json(self, **kwargs):
            records = store.get_attempts(request.content_uid)
            attempt = records[-1]
            assert attempt['outcome'] == 'running'
            assert attempt['input_hash'] == item_hash(request)
            assert attempt['context_fingerprint'] == (request.same_entity_context.context_fingerprint if request.same_entity_context else None)
            actual = kwargs['payload']['messages']
            from bg3loc.chat_prompt import ChatMessage
            assert attempt['chat_messages_fingerprint'] == chat_messages_fingerprint(tuple(ChatMessage(**value) for value in actual))
            prompt = assemble_translation_prompt(replace(request, input_hash=attempt['input_hash']), ruleset())
            assert attempt['effective_prompt_hash'] == prompt.effective_prompt_hash
            self.calls.append(kwargs)
            if mode == 'timeout': raise TimeoutError('fictional timeout')
            if mode == 'http500': return 500, {'error': {'message': 'fictional server failure'}}
            return 200, {'choices': [{'message': {'content': self.output}}]}
    transport = ObservingTransport()
    result = execute(store, plan, transport)
    assert result.succeeded == (mode in {'success', 'absent'})
    attempt = store.get_attempts(request.content_uid)[0]
    assert all(attempt[key] for key in ('input_hash', 'effective_prompt_hash', 'chat_messages_fingerprint'))
    assert attempt['prompt_renderer_version'] == (None if mode == 'absent' else 'same-entity-prompt/1')
    assert 'relatedFields' not in attempt and 'sourceText' not in attempt


def test_retry_provenance_is_stable_and_render_occurs_once_per_send(tmp_path):
    request = with_context()
    store, plan, _, _ = store_for(tmp_path, request)
    class RetryTransport(Transport):
        def post_json(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1: return 500, {'error': {'message': 'retry'}}
            return 200, {'choices': [{'message': {'content': self.output}}]}
    transport = RetryTransport()
    from bg3loc.providers.openai_compatible import render_chat_messages as render
    with patch('bg3loc.providers.openai_compatible.render_chat_messages', wraps=render) as renderer:
        result = execute(store, plan, transport, max_attempts=2)
    assert result.succeeded == 1 and renderer.call_count == len(transport.calls) == 2
    first, second = store.get_attempts(request.content_uid)
    assert (first['attempt_number'], second['attempt_number']) == (1, 2)
    for key in ('input_hash', 'context_fingerprint', 'effective_prompt_hash', 'chat_messages_fingerprint'):
        assert first[key] == second[key]


def test_corrupt_after_seed_has_no_normal_provider_provenance(tmp_path):
    request = with_context()
    store, plan, path, row = store_for(tmp_path, request)
    row['sameEntityContext']['contextFingerprint'] = '0' * 64
    write_material(path, row)
    transport = Transport()
    assert execute(store, plan, transport).failed_final == 1
    attempt = store.get_attempts(request.content_uid)[0]
    assert attempt['error_code'] == 'MATERIAL_RESOLUTION_ERROR'
    assert transport.calls == []
    assert all(attempt[key] is None for key in ('context_fingerprint', 'effective_prompt_hash', 'chat_messages_fingerprint'))


def test_valid_changed_context_after_seed_also_stops_before_provider(tmp_path):
    request = with_context()
    store, plan, path, row = store_for(tmp_path, request)
    field = replace(request.same_entity_context.related_fields[0], source_text='Changed but well-formed frozen context.')
    row['sameEntityContext'] = resign(replace(request.same_entity_context, related_fields=(field,))).to_dict()
    write_material(path, row)
    transport = Transport()
    assert execute(store, plan, transport).failed_final == 1
    assert transport.calls == []


def test_old_qa_review_and_identical_new_output_cannot_reuse_acceptance(tmp_path):
    request = with_context()
    store, plan, path, row = store_for(tmp_path, request)
    # Source-equal output goes to REVIEW; a human accepts this exact old input.
    assert execute(store, plan, Transport(request.source_text)).succeeded == 1
    qa = TranslationQaStore(store.path); qa.initialize()
    result = evaluate_translation(QaInput(request.content_uid, request.source_text, request.source_text, request.primary_category, request.protected_tokens))
    qa.record_result(result, checked_at='fixture-a')
    review = ProductionReviewStore(store.path); review.initialize()
    review.resolve(content_uid=request.content_uid, decision='ACCEPT', reviewer='fictional-reviewer', note='fixture', resolved_at='fixture-a')
    assert build_production_completion_view(store.path, plan).counts['MERGE_READY'] == 1
    field = replace(request.same_entity_context.related_fields[0], source_text='Revised frozen energy description.')
    changed = resign(replace(request.same_entity_context, related_fields=(field,)))
    row['sameEntityContext'] = changed.to_dict(); write_material(path, row)
    _, items = load_execution_items(plan, **GOLDEN['parameters'])
    store.seed_items(items, updated_at='new-input')
    assert qa.get_result(request.content_uid).qa_status == 'stale'
    assert review.get_current_acceptance(request.content_uid, current_output_hash=hashlib.sha256(request.source_text.encode()).hexdigest()) is None
    view = build_production_completion_view(store.path, plan)
    with pytest.raises(RuntimeError, match='completion gate'):
        _require_completion_ready(view)
    # Even after the new input produces byte-identical text, old QA is stale.
    assert execute(store, plan, Transport(request.source_text), name='new-context-run').succeeded == 1
    assert qa.get_result(request.content_uid).qa_status == 'stale'
    assert build_production_completion_view(store.path, plan).counts['MERGE_READY'] == 0
    qa.record_result(result, checked_at='fixture-b')
    # QA rerun is current, but previous human acceptance remains tied to old input.
    assert qa.get_result(request.content_uid).qa_status == 'checked'
    assert build_production_completion_view(store.path, plan).counts['WAITING_REVIEW'] == 1
    review.resolve(content_uid=request.content_uid, decision='ACCEPT', reviewer='fictional-reviewer', note='new input checked', resolved_at='fixture-b')
    _require_completion_ready(build_production_completion_view(store.path, plan))


@pytest.mark.parametrize('mutation', ['renderer', 'policy', 'material'])
def test_sealed_contract_runtime_mismatch_and_material_tamper_fail_before_start(tmp_path, monkeypatch, mutation):
    prepare, _ = public_fixture(tmp_path)
    manifest = prepare_production_workspace(prepare)
    if mutation == 'renderer':
        monkeypatch.setattr('bg3loc.prompt_assembly.SAME_ENTITY_PROMPT_VERSION', 'unsupported/999')
    elif mutation == 'policy':
        path = prepare.output_dir / 'production-manifest.json'
        manifest['execution']['contextContract']['policyVersion'] = 'unsupported/999'
        path.write_text(json.dumps(manifest), encoding='utf8')
    else:
        path = next(path for path in (prepare.output_dir / 'batches/materials').glob('*.jsonl') if 'sameEntityContext' in path.read_text())
        path.write_text(path.read_text().replace('"contextFingerprint":"', '"contextFingerprint":"0'), encoding='utf8')
    args = Namespace(db=str(prepare.output_dir / 'execution.sqlite3'), batch_plan=str(prepare.output_dir / 'batches/batch-plan.json'),
                     ruleset=str(prepare.output_dir / 'inputs/ruleset.json'), base_url='https://example.test', model='fictional', timeout_seconds=12.5, max_output_tokens=None, temperature=None, run_id='must-not-start')
    with patch('bg3loc.providers.openai_compatible.UrllibJsonTransport.post_json') as transport:
        with pytest.raises(RuntimeError): run_openai_compatible_start(args)
        assert transport.call_count == 0
    assert TranslationExecutionStore(Path(args.db)).get_run('must-not-start') is None


def test_pre_p4_workspace_rejected_without_touching_db(tmp_path):
    prepare, _ = public_fixture(tmp_path)
    manifest = prepare_production_workspace(prepare)
    path = prepare.output_dir / 'production-manifest.json'
    del manifest['execution']['contextContract']; path.write_text(json.dumps(manifest), encoding='utf8')
    db = prepare.output_dir / 'execution.sqlite3'; before = db.read_bytes()
    with pytest.raises(RuntimeError, match='fresh prepare'): verify_production_workspace(prepare.output_dir)
    with pytest.raises(RuntimeError, match='fresh prepare'):
        run_init(Namespace(batch_plan=str(prepare.output_dir / 'batches/batch-plan.json'), db=str(db), ruleset=str(prepare.ruleset), prompt_version='unused'))
    assert before == db.read_bytes()


def test_execution_config_binds_material_policy_and_renderer():
    engine = provider(Transport())
    contract = execution_context_contract('0' * 64)
    original = openai_compatible_execution_config_hash(engine.config, ruleset(), context_contract=contract)
    for key in ('schemaVersion', 'policyVersion', 'promptRendererVersion', 'sameEntityContextMaterialFingerprint'):
        altered = {**contract, key: 'fictional-other-version-or-digest'}
        assert openai_compatible_execution_config_hash(engine.config, ruleset(), context_contract=altered) != original


def test_additive_old_attempt_migration_is_idempotent_and_never_fabricates(tmp_path):
    store, plan, _, _ = store_for(tmp_path, baseline_request())
    assert execute(store, plan, Transport()).succeeded == 1
    before = store.get_state(baseline_request().content_uid)
    with sqlite3.connect(store.path) as conn:
        for column in ('context_fingerprint', 'effective_prompt_hash', 'chat_messages_fingerprint', 'prompt_renderer_version'):
            conn.execute('ALTER TABLE attempts DROP COLUMN ' + column)
    store.initialize(); store.initialize()
    record = store.get_attempts(baseline_request().content_uid)[0]
    assert record['outcome'] == 'succeeded'
    assert all(record[key] is None for key in ('context_fingerprint', 'effective_prompt_hash', 'chat_messages_fingerprint', 'prompt_renderer_version'))
    assert store.get_state(baseline_request().content_uid) == before


def test_start_and_worker_config_binding_and_nullable_absent_rows(tmp_path):
    prepare, _ = public_fixture(tmp_path)
    manifest = prepare_production_workspace(prepare)
    contract = manifest['execution']['contextContract']
    assert contract['inputIdentityVersion'] == 'translation-input/2'
    assert contract['promptRendererVersion'] == 'same-entity-prompt/1'
    args = Namespace(db=str(prepare.output_dir / 'execution.sqlite3'), batch_plan=str(prepare.output_dir / 'batches/batch-plan.json'),
        ruleset=str(prepare.output_dir / 'inputs/ruleset.json'), base_url='https://example.test', model='fictional', timeout_seconds=12.5,
        max_output_tokens=None, temperature=None, run_id='bound-run', worker_id='fixture', api_key_env='', lease_seconds=300,
        max_attempts=1, max_items=1)
    run_openai_compatible_start(args)
    with patch('bg3loc.providers.openai_compatible.UrllibJsonTransport.post_json') as transport:
        with pytest.raises(RuntimeError, match='config hash'):
            run_openai_compatible_worker(Namespace(**{**vars(args), 'temperature': .5}))
        assert transport.call_count == 0
    # An otherwise valid runtime with a different context renderer is rejected
    # before claiming, even if provider configuration is unchanged.
    with patch('bg3loc.prompt_assembly.SAME_ENTITY_PROMPT_VERSION', 'same-entity-prompt/999'), patch('bg3loc.providers.openai_compatible.UrllibJsonTransport.post_json') as transport:
        with pytest.raises(RuntimeError, match='context contract'):
            run_openai_compatible_worker(args)
        assert transport.call_count == 0
    with sqlite3.connect(args.db) as conn:
        assert conn.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0


def test_live_owner_guards_and_idempotent_attempt_binding(tmp_path):
    request = with_context()
    store, _, _, _ = store_for(tmp_path, request)
    start(store, 'owner-run')
    lease = store.claim_next(run_id='owner-run', worker_id='owner-a', lease_expires_at='2099-01-01T00:00:00Z', started_at='2026-10-06T00:00:00Z', max_attempts=2)
    start(store, 'competing-run')
    assert store.claim_next(run_id='competing-run', worker_id='owner-b', lease_expires_at='2099-01-01T00:00:00Z', started_at='2026-10-06T00:00:01Z', max_attempts=2) is None
    prompt = assemble_translation_prompt(request, ruleset())
    values = dict(attempt_id=lease.attempt_id, input_hash=lease.input_hash, context_fingerprint=request.same_entity_context.context_fingerprint,
                  effective_prompt_hash=prompt.effective_prompt_hash, chat_messages_fingerprint=chat_messages_fingerprint(render_chat_messages(prompt)), prompt_renderer_version='same-entity-prompt/1')
    with pytest.raises(ValueError, match='lease'):
        store.record_prompt_provenance(worker_id='owner-b', **values)
    store.record_prompt_provenance(worker_id='owner-a', **values)
    store.record_prompt_provenance(worker_id='owner-a', **values)
    with pytest.raises(ValueError, match='already bound'):
        store.record_prompt_provenance(worker_id='owner-a', **{**values, 'context_fingerprint': '0' * 64})


def test_qa_retry_handoff_preserves_input_and_context_provenance(tmp_path):
    request = with_context()
    store, plan, _, _ = store_for(tmp_path, request)
    # Existing QA retry path, using a synthetic successful candidate whose
    # target token is missing. No provider response is needed to seed it.
    start(store, 'qa-origin')
    lease = store.claim_next(run_id='qa-origin', worker_id='fixture', lease_expires_at='2099-01-01T00:00:00Z', started_at='2026-10-06T00:00:00Z', max_attempts=3)
    bad = 'Fictional invalid candidate'
    store.complete_success(attempt_id=lease.attempt_id, worker_id='fixture', translated_text=bad, output_hash=hashlib.sha256(bad.encode()).hexdigest(), finished_at='2026-10-06T00:01:00Z')
    qa = TranslationQaStore(store.path); qa.initialize()
    result = evaluate_translation(QaInput(request.content_uid, request.source_text, bad, request.primary_category, request.protected_tokens))
    assert result.route == 'RETRY'
    qa.record_result(result, checked_at='fixture')
    old_hash = store.get_state(request.content_uid)['input_hash']
    qa.handoff_retry(result, max_attempts=3, rejected_at='2026-10-06T00:02:00Z')
    assert store.get_state(request.content_uid)['input_hash'] == old_hash
    assert execute(store, plan, Transport(), name='qa-retry', max_attempts=3).succeeded == 1
    actual = store.get_attempts(request.content_uid)[-1]
    assert actual['input_hash'] == old_hash
    assert actual['context_fingerprint'] == request.same_entity_context.context_fingerprint


def test_legacy_qa_and_review_rows_remain_readable_without_fabricated_binding(tmp_path):
    request = baseline_request()
    store, plan, _, _ = store_for(tmp_path, request)
    assert execute(store, plan, Transport(request.source_text)).succeeded == 1
    qa = TranslationQaStore(store.path); qa.initialize()
    qa.record_result(evaluate_translation(QaInput(request.content_uid, request.source_text, request.source_text, request.primary_category, request.protected_tokens)), checked_at='fixture')
    review = ProductionReviewStore(store.path); review.initialize()
    review.resolve(content_uid=request.content_uid, decision='ACCEPT', reviewer='fixture', note='', resolved_at='fixture')
    with sqlite3.connect(store.path) as conn:
        conn.execute('ALTER TABLE qa_results DROP COLUMN execution_input_hash')
        conn.execute('ALTER TABLE qa_review_resolutions DROP COLUMN execution_input_hash')
    assert qa.get_result(request.content_uid).qa_status == 'checked'
    assert build_production_completion_view(store.path, plan).counts['MERGE_READY'] == 1
    qa.initialize(); qa.initialize(); review.initialize(); review.initialize()
    assert qa.get_result(request.content_uid).execution_input_hash is None
    assert review.get_current_acceptance(request.content_uid, current_output_hash=hashlib.sha256(request.source_text.encode()).hexdigest()) is not None


def test_qa_evaluation_snapshot_cannot_be_rebound_to_a_different_input(tmp_path):
    request = with_context()
    store, plan, _, _ = store_for(tmp_path, request)
    assert execute(store, plan, Transport(request.source_text)).succeeded == 1
    before = store.get_state(request.content_uid)
    result = evaluate_translation(QaInput(request.content_uid, request.source_text, request.source_text, request.primary_category, request.protected_tokens))
    qa = TranslationQaStore(store.path); qa.initialize()
    store.seed_items([ExecutionItem(request.content_uid, request.batch_id, 'changed-input')], updated_at='changed')
    with pytest.raises(ValueError, match='changed during evaluation'):
        qa.record_result(result, checked_at='stale', expected_input_hash=before['input_hash'], expected_output_hash=before['output_hash'])
    # Model an identical completed output under the new identity. The old
    # evaluated snapshot still cannot be attached to it.
    with closing(store.connect()) as conn, conn:
        conn.execute("UPDATE content_state SET status='succeeded' WHERE content_uid=?", (request.content_uid,))
    with pytest.raises(ValueError, match='changed during evaluation'):
        qa.record_result(result, checked_at='stale', expected_input_hash=before['input_hash'], expected_output_hash=before['output_hash'])
    assert qa.get_result(request.content_uid) is None
