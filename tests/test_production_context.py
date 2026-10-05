"""Fictional public provenance -> real prepare -> isolated preflight."""
from dataclasses import replace
import csv
import json
from pathlib import Path
import random
import shutil
import sqlite3

import pytest

from bg3loc.cli import main
from bg3loc.execution_state import ClaimedAttempt
from bg3loc.production_completion import build_production_completion_view
from bg3loc.production_context import context_from_material
from bg3loc.production_orchestration import ProductionPrepareRequest, prepare_production_workspace
from bg3loc.production_workspace import batch_materials_fingerprint, verify_production_workspace
from bg3loc.research.structural_provenance import parse_structural_stats, parse_structural_xml, write_structural_provenance
from bg3loc.same_entity_context import ContextBuildResult
from bg3loc.translation_request import BatchMaterialResolver


def uid(index):
    return f'h{index:08x}g1111g2222g3333g444444444444'


def write_rows(path, rows):
    path.write_text(''.join(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n' for row in rows), encoding='utf-8')


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def fixture(root):
    inputs = root / 'public-inputs'
    inputs.mkdir()
    definitions, sources, mappings = [], [], []
    labels = {}

    def entity(label, category, *, origin='MapKey', template_type='item', single=False):
        start = len(sources) + 1
        pair = [uid(start)] if single else [uid(start), uid(start + 1)]
        labels[label] = pair
        for index, handle in enumerate(pair):
            sources.append({'contentUid': handle, 'text': f'Fictional {label} ' + ('name' if index == 0 else 'details'), 'localeId': 'English'})
            mapping_type = {'skill_spell': 'stat-reference', 'item': 'ui-skill-candidate', 'quest': 'quest-journal', 'bark': 'bark-speaker'}[category]
            evidence = [] if category == 'bark' else [{'sourceRole': 'FictionalPublicDefinition', 'resourcePath': f'Public/Fixture/{label}.lsx',
                'evidenceType': {'skill_spell': 'StatsDefinition', 'item': 'UiSkillProvider', 'quest': 'QuestJournal'}[category], 'ruleId': 'fictional-structural',
                'properties': {'entryType': 'SpellData', 'entryName': f'Skill_{label}', 'entityId': label, 'fieldRole': 'Title' if index == 0 else 'Description', 'domain': 'ItemsAndEquipment'}}]
            mappings.append({'contentUid': handle, 'mappingType': mapping_type, 'classification': category, 'evidence': evidence,
                             'metadata': {'domain': 'AbilityOrSkill' if category == 'skill_spell' else 'ItemsAndEquipment'}})
        if category == 'skill_spell':
            text = f'new entry "Skill_{label}"\ntype "SpellData"\ndata "DisplayName" "{pair[0]};1"\n'
            if len(pair) > 1:
                text += f'data "Description" "{pair[1]};1"\n'
            parsed = parse_structural_stats(text, resource_path=f'Public/Fixture/Stats/{label}.txt', package='Fixture.pak')
        elif category == 'bark':
            parsed = []
        else:
            native = '' if not origin else f'<attribute id="{origin}" value="{label if origin != "UUID" else "11111111-2222-4333-8444-555555555555"}"/>'
            fields = ''.join(f'<attribute id="{("Title" if category == "quest" else "DisplayName") if index == 0 else "Description"}" handle="{handle}"/>' for index, handle in enumerate(pair))
            xml = f'<save><node id="{"JournalEntity" if category == "quest" else "GameObjects"}">{native}<attribute id="Type" value="{template_type}"/>{fields}</node></save>'
            parsed = parse_structural_xml(xml, kind='quest' if category == 'quest' else 'item', resource_path=f'Public/Fixture/{label}.lsx', package='Fixture.pak')
        definitions.extend(parsed)
        return parsed

    entity('FrostSpark', 'skill_spell')
    entity('ExplicitCharm', 'item', origin='UUID')
    duplicate = entity('MoonstoneCharm', 'item')
    definitions.append(replace(duplicate[0], source_resource='Other.pak/Public/Fixture/MoonstoneCharm.lsx'))
    entity('ConflictCharm', 'item')
    # Conflicting definition without localization, wrong native Type: retained.
    conflict_xml = '<save><node id="GameObjects"><attribute id="MapKey" value="ConflictCharm"/><attribute id="Type" value="character"/></node></save>'
    definitions.extend(parse_structural_xml(conflict_xml, resource_path='Public/Fixture/conflicting.lsx', package='Other.pak'))
    entity('Character', 'item', template_type='character')
    entity('NameFallback', 'item', origin='Name')
    entity('LostCourier', 'quest', origin='ID')
    entity('OrdinalQuest', 'quest', origin='')
    entity('Solo', 'skill_spell', single=True)
    entity('Greeting', 'bark', single=True)
    entity('HeldCharm', 'item')
    # A missing source occurrence stays in the universe; never seeds an item.
    definitions.extend(parse_structural_stats(f'new entry "Skill_Missing"\ntype "SpellData"\ndata "Description" "{uid(999)};1"\n', resource_path='Public/Fixture/missing.txt', package='Fixture.pak'))
    source = inputs / 'English.jsonl'
    write_rows(source, sources)
    mapping = inputs / 'research-mappings.jsonl'
    write_rows(mapping, mappings)
    extract = inputs / 'extract-manifest.json'
    extract.write_text(json.dumps({'sourceLocale': 'English', 'targetLocale': 'ChineseTraditional', 'locales': [{'localeId': 'English', 'normalized': str(source)}]}), encoding='utf-8')
    rules = inputs / 'ruleset.json'
    rules.write_text(json.dumps({'version': 'fictional-v1', 'sourceLocale': 'English', 'targetLocale': 'ChineseTraditional', 'commonRules': ['Preserve meaning.'], 'categoryRules': {cat: ['Use concise wording.'] for cat in ('skill_spell', 'item', 'quest', 'bark')}, 'glossary': []}), encoding='utf-8')
    holds = inputs / 'ui-skill-universe.csv'
    with holds.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['ContentUid', 'Status'])
        writer.writeheader()
        writer.writerows({'ContentUid': handle, 'Status': 'Hold'} for handle in labels['HeldCharm'])
    provenance = inputs / 'provenance'
    write_structural_provenance(provenance, definitions)
    return ProductionPrepareRequest(extract, source, mapping, rules, root / 'prepared', structural_provenance=provenance), labels


def material_rows(output):
    return {row['contentUid']: row for path in (output / 'batches/materials').glob('*.jsonl') for row in read_rows(path)}


def summary(output):
    return json.loads((output / 'context-materialization-summary.json').read_text(encoding='utf-8'))


def contexts(output):
    return {handle: row.get('sameEntityContext') for handle, row in material_rows(output).items()}


def test_public_prepare_policy_inventory_and_isolation(tmp_path):
    request, labels = fixture(tmp_path)
    manifest = prepare_production_workspace(request)
    rows = material_rows(request.output_dir)
    for label in ('FrostSpark', 'ExplicitCharm', 'MoonstoneCharm', 'LostCourier'):
        for handle in labels[label]:
            context = context_from_material(rows[handle])
            assert context is not None
            assert context.to_dict() == rows[handle]['sameEntityContext']
    for label in ('ConflictCharm', 'Character', 'NameFallback', 'OrdinalQuest', 'Solo', 'Greeting', 'HeldCharm'):
        assert all('sameEntityContext' not in rows[handle] for handle in labels[label])
    report = summary(request.output_dir)
    assert report['absenceReasonCounts'] == {'HOLD_OR_INELIGIBLE': 2, 'NO_RELATED_FIELDS': 1, 'NO_RELIABLE_IDENTITY': 6, 'STRUCTURAL_CONFLICT': 2, 'UNSUPPORTED_CATEGORY': 1}
    assert report['categories']['item']['eligibleTargets'] == 10
    assert report['categories']['item']['withContext'] == 4
    assert report['itemSanity']['structuralConflictExcludedTargets'] == 2
    assert manifest['schemaVersion'] == '1.2'
    assert manifest['execution']['seededContentUidCount'] == len(rows)
    assert str(tmp_path) not in json.dumps(manifest['sameEntityContext'])
    with sqlite3.connect(request.output_dir / 'execution.sqlite3') as conn:
        assert dict(conn.execute('SELECT content_uid, status FROM content_state')) == {handle: 'pending' for handle in rows}
        assert conn.execute('SELECT sum(attempt_count) FROM content_state').fetchone()[0] == 0
    # Inputs, research outputs, source snapshot and raw fixture are unavailable.
    shutil.rmtree(tmp_path / 'public-inputs')
    binding = verify_production_workspace(request.output_dir)
    resolver = BatchMaterialResolver(binding.batch_plan)
    for handle, row in rows.items():
        claim = ClaimedAttempt(1, 'fictional-read-only', handle, row['batchId'], 1, 'fictional-hash', 'fixture', '')
        request_row = resolver.resolve(claim)
        assert request_row.source_text == row['sourceText']
        assert not hasattr(request_row, 'same_entity_context')
    assert build_production_completion_view(binding.database, binding.batch_plan).total == len(rows)
    assert material_rows(request.output_dir) == rows


def test_repeat_reorder_and_batch_split_determinism(tmp_path):
    request, _ = fixture(tmp_path)
    prepare_production_workspace(request)
    repeat = replace(request, output_dir=tmp_path / 'repeat')
    prepare_production_workspace(repeat)
    assert summary(repeat.output_dir) == summary(request.output_dir)
    files = lambda output: {path.name: path.read_bytes() for path in (output / 'batches/materials').glob('*.jsonl')}
    assert files(repeat.output_dir) == files(request.output_dir)
    generator = random.Random(42)
    for path in (request.source, request.structural_provenance / 'structural-definitions.jsonl', request.structural_provenance / 'structural-occurrences.jsonl'):
        rows = read_rows(path)
        generator.shuffle(rows)
        write_rows(path, rows)
    reordered = replace(request, output_dir=tmp_path / 'reordered')
    prepare_production_workspace(reordered)
    assert contexts(reordered.output_dir) == contexts(request.output_dir)
    assert summary(reordered.output_dir) == summary(request.output_dir)
    split = replace(request, output_dir=tmp_path / 'split', max_records=('skill_spell=1', 'item=1', 'quest=1', 'bark=1'))
    split_manifest = prepare_production_workspace(split)
    assert contexts(split.output_dir) == contexts(request.output_dir)
    assert summary(split.output_dir) == summary(request.output_dir)
    assert split_manifest['batching']['batchCount'] > json.loads((request.output_dir / 'production-manifest.json').read_text())['batching']['batchCount']
    split_summary = json.loads((split.output_dir / 'batches/batch-summary.json').read_text())
    assert split_summary['oversizeGroupSplitCount'] > 0


def test_absent_bytes_and_legacy_execution_hashes_unchanged(tmp_path):
    request, _ = fixture(tmp_path)
    prepare_production_workspace(request)
    legacy = replace(request, structural_provenance=None, output_dir=tmp_path / 'legacy')
    legacy_manifest = prepare_production_workspace(legacy)
    assert legacy_manifest['schemaVersion'] == '1.1'
    original = material_rows(legacy.output_dir)
    for handle, row in material_rows(request.output_dir).items():
        assert {key: value for key, value in row.items() if key != 'sameEntityContext'} == original[handle]
    for path in (request.output_dir / 'batches/materials').glob('*.jsonl'):
        absent = [line for line in path.read_bytes().splitlines(keepends=True) if b'sameEntityContext' not in line]
        legacy_lines = (legacy.output_dir / 'batches/materials' / path.name).read_bytes().splitlines(keepends=True)
        assert all(line in legacy_lines for line in absent)
    def inventory(output):
        with sqlite3.connect(output / 'execution.sqlite3') as conn:
            return conn.execute('SELECT content_uid,batch_id,input_hash FROM content_state ORDER BY content_uid').fetchall()
    assert inventory(request.output_dir) == inventory(legacy.output_dir)
    verify_production_workspace(legacy.output_dir)


@pytest.mark.parametrize('mutation', ['fingerprint', 'binding', 'text', 'null', 'empty', 'missing'])
@pytest.mark.parametrize('reseal_outer', [False, True])
def test_corrupt_present_fails_preflight_even_with_updated_outer_hash(tmp_path, mutation, reseal_outer):
    request, _ = fixture(tmp_path)
    prepare_production_workspace(request)
    path = next(path for path in (request.output_dir / 'batches/materials').glob('*.jsonl') if 'sameEntityContext' in path.read_text())
    rows = read_rows(path)
    row = next(row for row in rows if 'sameEntityContext' in row)
    context = row['sameEntityContext']
    if mutation == 'fingerprint':
        context['contextFingerprint'] = '0' * 64
    elif mutation == 'binding':
        context['targetBinding']['contentUid'] = uid(987)
    elif mutation == 'text':
        context['relatedFields'][0]['sourceText'] = 'Tampered fictional detail'
    elif mutation == 'missing':
        del row['sameEntityContext']
    else:
        row['sameEntityContext'] = None if mutation == 'null' else {}
    write_rows(path, rows)
    if reseal_outer:
        manifest_path = request.output_dir / 'production-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['batching']['batchMaterialsFingerprint'] = batch_materials_fingerprint(request.output_dir / 'batches/batch-plan.json')
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises((RuntimeError, ValueError)):
        verify_production_workspace(request.output_dir)


def test_invalid_builder_result_fails_before_any_context_write_or_init(tmp_path, monkeypatch):
    request, _ = fixture(tmp_path)
    prepare_production_workspace(request)
    present = next(row for row in material_rows(request.output_dir).values() if 'sameEntityContext' in row)
    valid = context_from_material(present)
    invalid = replace(valid, context_fingerprint='0' * 64)
    monkeypatch.setattr('bg3loc.production_context.build_same_entity_context', lambda *args: ContextBuildResult(invalid, None))
    broken = replace(request, output_dir=tmp_path / 'broken')
    with pytest.raises(ValueError):
        prepare_production_workspace(broken)
    assert not (broken.output_dir / 'execution.sqlite3').exists()
    assert all('sameEntityContext' not in path.read_text() for path in (broken.output_dir / 'batches/materials').glob('*.jsonl'))


@pytest.mark.parametrize('malformation', ['schema', 'orphan', 'non_english', 'duplicate_source'])
def test_malformed_public_inputs_hard_fail_before_init(tmp_path, malformation):
    request, _ = fixture(tmp_path)
    if malformation in ('schema', 'orphan'):
        path = request.structural_provenance / 'structural-occurrences.jsonl'
        rows = read_rows(path)
        rows[0]['definitionFingerprint'] = 'bad' if malformation == 'schema' else '0' * 64
    else:
        path = request.source
        rows = read_rows(path)
        if malformation == 'non_english':
            rows[0]['localeId'] = 'ChineseTraditional'
        else:
            rows.append(rows[0])
    write_rows(path, rows)
    with pytest.raises(RuntimeError):
        prepare_production_workspace(request)
    assert not (request.output_dir / 'execution.sqlite3').exists()


def test_cli_enables_context_and_missing_proof_is_normal_absence(tmp_path):
    request, labels = fixture(tmp_path)
    for name in ('structural-definitions.jsonl', 'structural-occurrences.jsonl'):
        path = request.structural_provenance / name
        rows = read_rows(path)
        for row in rows:
            for key in ('templateType', 'identityIsNative', 'fieldIsDirect'):
                row.pop(key, None)
        write_rows(path, rows)
    assert main(['production', 'prepare', '--extract', str(request.extract_manifest), '--source', str(request.source), '--research-mappings', str(request.research_mappings), '--ruleset', str(request.ruleset), '--output', str(request.output_dir), '--structural-provenance', str(request.structural_provenance)]) == 0
    rows = material_rows(request.output_dir)
    assert all('sameEntityContext' not in rows[handle] for handle in labels['MoonstoneCharm'])
    verify_production_workspace(request.output_dir)


def test_missing_related_source_is_normal_absence_and_never_seeds_uid(tmp_path):
    request, labels = fixture(tmp_path)
    solo = labels['Solo'][0]
    occurrence_path = request.structural_provenance / 'structural-occurrences.jsonl'
    occurrences = read_rows(occurrence_path)
    # Fictional ledger has a structurally bound sibling with no English record.
    sibling = next(row.copy() for row in occurrences if row['contentUid'] == solo)
    sibling.update(contentUid=uid(998), fieldRole='Description', fieldName='Description')
    occurrences.append(sibling)
    write_rows(occurrence_path, occurrences)
    manifest = prepare_production_workspace(request)
    assert 'sameEntityContext' not in material_rows(request.output_dir)[solo]
    assert uid(998) not in material_rows(request.output_dir)
    assert summary(request.output_dir)['absenceReasonCounts']['NO_RELATED_FIELDS'] == 1
    assert manifest['execution']['seededContentUidCount'] == 20


@pytest.mark.parametrize('section', ['sameEntityContext', 'summary'])
def test_materialization_contract_and_summary_integrity(tmp_path, section):
    request, _ = fixture(tmp_path)
    prepare_production_workspace(request)
    if section == 'sameEntityContext':
        path = request.output_dir / 'production-manifest.json'
        payload = json.loads(path.read_text())
        payload[section]['policyVersion'] = 'b1-02-structural/1'
    else:
        path = request.output_dir / 'context-materialization-summary.json'
        payload = json.loads(path.read_text())
        payload['withContext'] += 1
    path.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(RuntimeError):
        verify_production_workspace(request.output_dir)


@pytest.mark.parametrize('mutation,reason', [('quest_conflict', 'STRUCTURAL_CONFLICT'), ('role_ambiguity', 'AMBIGUOUS_FIELD_ROLE'), ('non_item_alias', 'CATEGORY_MISMATCH')])
def test_full_universe_conflicts_and_uid_aliases_are_preserved(tmp_path, mutation, reason):
    request, labels = fixture(tmp_path)
    definition_path = request.structural_provenance / 'structural-definitions.jsonl'
    occurrence_path = request.structural_provenance / 'structural-occurrences.jsonl'
    definitions, occurrences = read_rows(definition_path), read_rows(occurrence_path)
    if mutation == 'quest_conflict':
        handle = labels['LostCourier'][0]
        original = next(row for row in occurrences if row['contentUid'] == handle)
        conflict = next(row.copy() for row in definitions if row['definitionFingerprint'] == original['definitionFingerprint'])
        conflict['definitionFingerprint'] = '0' * 64
        conflict['sourceResource'] = 'Other.pak/Public/Fixture/quest.lsx'
        definitions.append(conflict)
    elif mutation == 'role_ambiguity':
        handle = labels['FrostSpark'][0]
        alias = next(row.copy() for row in occurrences if row['contentUid'] == handle)
        alias.update(fieldRole='Description', fieldName='Description', occurrenceIndex=2)
        occurrences.append(alias)
    else:
        handle = labels['MoonstoneCharm'][0]
        alias = next(row.copy() for row in occurrences if row['contentUid'] == labels['Character'][0])
        alias['contentUid'] = handle
        occurrences.append(alias)
    write_rows(definition_path, definitions)
    write_rows(occurrence_path, occurrences)
    prepare_production_workspace(request)
    assert 'sameEntityContext' not in material_rows(request.output_dir)[handle]
    assert summary(request.output_dir)['absenceReasonCounts'][reason] > 0
