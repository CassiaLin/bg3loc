"""Fictional final pipeline gate, including standalone completion/bridge boundaries."""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sqlite3
from unittest.mock import patch

import pytest

from bg3loc.final_merge_bridge import build_final_merge_bridge
from bg3loc.production_completion import build_production_completion_view
from bg3loc.production_execution import execute_openai_compatible, OpenAICompatibleExecutionRequest
from bg3loc.production_finalize import finalize_production_workspace, ProductionFinalizeRequest
from bg3loc.production_orchestration import prepare_production_workspace
from bg3loc.production_qa_orchestration import run_workspace_qa
from bg3loc.production_workspace import verify_production_workspace
from bg3loc.execution_state import ClaimedAttempt
from bg3loc.translation_request import BatchMaterialResolver
from bg3loc.prompt_assembly import assemble_translation_prompt
from bg3loc.chat_prompt import render_chat_messages, chat_messages_fingerprint
from bg3loc.ruleset_io import load_ruleset
from bg3loc.same_entity_context import fingerprint
from test_production_context import fixture as public_fixture, material_rows, read_rows, write_rows
from test_production_finalize import FakeFinalizeBackend


def prepare_fixture(root, *, enabled=True):
    request, labels = public_fixture(root)
    source_rows = read_rows(request.source)
    for row in source_rows:
        row['version'] = 1
    write_rows(request.source, source_rows)
    assets = request.source.parent / 'locale-baseline'
    assets.mkdir()
    target = assets / 'ChineseTraditional.jsonl'
    write_rows(target, [{'contentUid': 'fictional-baseline-only', 'localeId': 'ChineseTraditional', 'text': '保留', 'version': 1}])
    xml = assets / 'source.xml'
    xml.write_text('<contentList><content contentuid="fictional-baseline-only" version="1">保留</content></contentList>', encoding='utf8')
    loca = assets / 'source.loca'; loca.write_bytes(xml.read_bytes())
    payload = {'schemaVersion': '1.0', 'scanManifest': str(assets / 'scan.json'), 'sourceLocale': 'English',
        'targetLocale': 'ChineseTraditional', 'referenceLocales': [], 'backend': {'id': 'fake'},
        'aligned': str(assets / 'aligned.jsonl'), 'roundtripValidation': str(assets / 'roundtrip.json'),
        'locales': [{'localeId': 'English', 'packageFile': str(assets / 'English.pak'), 'locaEntry': 'Localization/English/english.loca',
                    'sourceLoca': str(loca), 'sourceXml': str(xml), 'normalized': str(request.source), 'nodeCount': len(source_rows)},
                   {'localeId': 'ChineseTraditional', 'packageFile': str(assets / 'ChineseTraditional.pak'), 'locaEntry': 'Localization/ChineseTraditional/chinesetraditional.loca',
                    'sourceLoca': str(loca), 'sourceXml': str(xml), 'normalized': str(target), 'nodeCount': 1}]}
    request.extract_manifest.write_text(json.dumps(payload), encoding='utf8')
    if not enabled:
        request = replace(request, structural_provenance=None)
    manifest = prepare_production_workspace(request)
    return request, labels, manifest


def complete_mock(workspace, run_id='fictional-gate-run'):
    calls = []
    def post(_self, *, url, headers, payload, timeout_seconds):
        calls.append(payload)
        return 200, {'choices': [{'message': {'content': '這是一段用於測試的虛構譯文'}}]}
    with patch('bg3loc.providers.openai_compatible.UrllibJsonTransport.post_json', new=post):
        result = execute_openai_compatible(OpenAICompatibleExecutionRequest(workspace=workspace, base_url='https://example.test',
            model='fictional', run_id=run_id, worker_id='fixture', api_key_env='', retry_backoff_base_seconds=0))
    return result, calls


def snapshot_finalize_assets(request, manifest):
    # Finalize requires locale baseline/rebuild assets independently of B1-02.
    # Keep these fictional assets inside the prepared fixture so its isolation
    # test can forbid all research/game/source-universe paths.
    destination = request.output_dir / 'inputs/finalize-assets'
    destination.mkdir()
    payload = json.loads(request.extract_manifest.read_text())
    for locale in payload['locales']:
        for key in ('normalized', 'sourceXml', 'sourceLoca'):
            original = Path(locale[key])
            copied = destination / (locale['localeId'] + '-' + original.name)
            shutil.copyfile(original, copied)
            locale[key] = str(copied)
    extract = destination / 'extract-manifest.json'
    extract.write_text(json.dumps(payload), encoding='utf8')
    import hashlib
    manifest['inputs']['extractManifest'] = {'path': str(extract), 'sha256': hashlib.sha256(extract.read_bytes()).hexdigest()}
    (request.output_dir / 'production-manifest.json').write_text(json.dumps(manifest), encoding='utf8')


def test_completion_and_standalone_bridge_reject_changed_material_before_old_success(tmp_path):
    request, _, _ = prepare_fixture(tmp_path)
    result, calls = complete_mock(request.output_dir)
    assert result.succeeded == len(calls) == len(material_rows(request.output_dir))
    run_workspace_qa(request.output_dir)
    assert build_production_completion_view(request.output_dir / 'execution.sqlite3', request.output_dir / 'batches/batch-plan.json').counts['MERGE_READY'] == len(calls)
    path = next(path for path in (request.output_dir / 'batches/materials').glob('*.jsonl') if 'sameEntityContext' in path.read_text())
    rows = read_rows(path)
    row = next(row for row in rows if 'sameEntityContext' in row)
    context = row['sameEntityContext']; context['relatedFields'][0]['sourceText'] = 'Different fictional context after success.'
    context['contextFingerprint'] = fingerprint({key: value for key, value in context.items() if key != 'contextFingerprint'})
    write_rows(path, rows)
    with pytest.raises(RuntimeError, match='integrity'):
        build_production_completion_view(request.output_dir / 'execution.sqlite3', request.output_dir / 'batches/batch-plan.json')
    with pytest.raises(RuntimeError, match='integrity'):
        build_final_merge_bridge(db_path=request.output_dir / 'execution.sqlite3', batch_plan_path=request.output_dir / 'batches/batch-plan.json', extract_manifest_path=request.extract_manifest, output_dir=tmp_path / 'must-not-rebuild')
    assert not (tmp_path / 'must-not-rebuild').exists()


def test_pending_finalize_gates_before_any_external_extract_lookup(tmp_path):
    request, _, _ = prepare_fixture(tmp_path)
    shutil.rmtree(tmp_path / 'public-inputs')
    with patch('bg3loc.production_finalize._resolve_recorded_extract', side_effect=AssertionError('external lookup before completion')) as lookup:
        with pytest.raises(RuntimeError, match='completion gate'):
            finalize_production_workspace(ProductionFinalizeRequest(request.output_dir, tmp_path / 'must-not-finalize'))
        assert lookup.call_count == 0


@pytest.mark.parametrize('declaration', ['missing', 'legacy'])
def test_context_db_cannot_bypass_completion_by_removing_or_downgrading_manifest(tmp_path, declaration):
    request, _, manifest = prepare_fixture(tmp_path)
    path = request.output_dir / 'production-manifest.json'
    if declaration == 'missing':
        path.unlink()
    else:
        manifest['schemaVersion'] = '1.1'
        path.write_text(json.dumps(manifest), encoding='utf8')
    with pytest.raises(RuntimeError, match='sealed production workspace'):
        build_production_completion_view(request.output_dir / 'execution.sqlite3', request.output_dir / 'batches/batch-plan.json')


def test_complete_context_pipeline_isolated_finalize_rebuild_has_target_inventory_only(tmp_path):
    request, _, manifest = prepare_fixture(tmp_path)
    result, calls = complete_mock(request.output_dir)
    target_count = len(material_rows(request.output_dir))
    assert result.claimed == result.succeeded == len(calls) == target_count
    report = run_workspace_qa(request.output_dir)
    assert report.completion.counts['MERGE_READY'] == target_count
    snapshot_finalize_assets(request, manifest)
    shutil.rmtree(tmp_path / 'public-inputs')
    original_open = Path.open
    original_schema_load = __import__('bg3loc.schema', fromlist=['SchemaStore']).SchemaStore.load
    def guarded(path, *args, **kwargs):
        assert path.resolve().is_relative_to(request.output_dir.resolve()), 'external input read'
        return original_open(path, *args, **kwargs)
    # The installed code/schema dependency is allowed; only artifact input reads
    # are constrained. Schema loading itself never touches research/game data.
    def schema_load(store, name):
        with patch.object(Path, 'open', original_open):
            return original_schema_load(store, name)
    output = request.output_dir / 'final'
    with patch.object(Path, 'open', guarded), patch('bg3loc.schema.SchemaStore.load', new=schema_load), patch('bg3loc.backends.resolve_backend', side_effect=AssertionError('game scan forbidden')), patch('bg3loc.production_context.build_same_entity_context', side_effect=AssertionError('context rebuild forbidden')):
        binding = verify_production_workspace(request.output_dir)
        final = finalize_production_workspace(ProductionFinalizeRequest(binding.workspace, output, container='loca-only'), rebuild_backend=FakeFinalizeBackend())
    assert final.manifest['completion']['total'] == final.manifest['completion']['mergeReadyCount'] == target_count
    assert len(read_rows(output / 'bridge/accepted-target.jsonl')) == target_count
    assert len(read_rows(output / 'bridge/merge-ready-binding.jsonl')) == target_count
    assert final.manifest['rebuild']['validation']['uidSetIntegrity'] == 'pass'
    assert all((output / artifact['path']).is_file() for artifact in final.manifest['artifacts'])
    with sqlite3.connect(binding.database) as conn:
        attempts = conn.execute('SELECT input_hash,context_fingerprint,effective_prompt_hash,chat_messages_fingerprint FROM attempts').fetchall()
    assert len(attempts) == target_count
    assert all(row[0] and row[2] and row[3] for row in attempts)
    assert sum(row[1] is not None for row in attempts) == manifest['sameEntityContext']['withContext']


@pytest.mark.parametrize('schema', ['1.0', '1.1'])
def test_legacy_manifest_old_db_mock_workflow_and_resume_remain_valid(tmp_path, schema):
    request, _, manifest = prepare_fixture(tmp_path, enabled=False)
    manifest['schemaVersion'] = schema
    (request.output_dir / 'production-manifest.json').write_text(json.dumps(manifest), encoding='utf8')
    db = request.output_dir / 'execution.sqlite3'
    with sqlite3.connect(db) as conn:
        for column in ('context_fingerprint', 'effective_prompt_hash', 'chat_messages_fingerprint', 'prompt_renderer_version'):
            conn.execute('ALTER TABLE attempts DROP COLUMN ' + column)
    result, calls = complete_mock(request.output_dir)
    assert result.succeeded == len(calls) == len(material_rows(request.output_dir))
    assert all('relatedFields' not in json.loads(call['messages'][1]['content']) for call in calls)
    run_workspace_qa(request.output_dir)
    assert build_production_completion_view(db, request.output_dir / 'batches/batch-plan.json').counts['MERGE_READY'] == len(calls)
    resumed, more = complete_mock(request.output_dir, run_id='legacy-resume')
    assert resumed.claimed == 0 and more == []


def test_repeat_split_and_reverse_resolve_order_preserve_identity_and_render(tmp_path):
    request, _, first = prepare_fixture(tmp_path)
    repeat = replace(request, output_dir=tmp_path / 'repeat')
    second = prepare_production_workspace(repeat)
    split = replace(request, output_dir=tmp_path / 'split', max_records=('skill_spell=1', 'item=1', 'quest=1', 'bark=1'))
    third = prepare_production_workspace(split)
    assert first['sameEntityContext'] == second['sameEntityContext'] == third['sameEntityContext']
    assert first['execution']['contextContract'] == second['execution']['contextContract'] == third['execution']['contextContract']
    original_files = {path.name: path.read_bytes() for path in (request.output_dir / 'batches/materials').glob('*.jsonl')}
    assert original_files == {path.name: path.read_bytes() for path in (repeat.output_dir / 'batches/materials').glob('*.jsonl')}
    def resolve_all(workspace, reverse=False):
        rules = load_ruleset(workspace / 'inputs/ruleset.json')
        resolver = BatchMaterialResolver(workspace / 'batches/batch-plan.json')
        with sqlite3.connect(workspace / 'execution.sqlite3') as conn:
            rows = conn.execute('SELECT content_uid,batch_id,input_hash FROM content_state ORDER BY content_uid').fetchall()
        if reverse: rows.reverse()
        result = {}
        for uid, batch, digest in rows:
            request_row = resolver.resolve(ClaimedAttempt(1, 'offline-order', uid, batch, 1, digest, 'fixture', ''))
            prompt = assemble_translation_prompt(request_row, rules)
            # Batching/group metadata legitimately belongs to prompt identity;
            # each prepared target keeps its same canonical/context group keys.
            result[uid] = (digest, request_row.same_entity_context,
                           prompt.effective_prompt_hash, chat_messages_fingerprint(render_chat_messages(prompt)))
        return result
    assert resolve_all(request.output_dir) == resolve_all(repeat.output_dir, reverse=True) == resolve_all(split.output_dir, reverse=True)
