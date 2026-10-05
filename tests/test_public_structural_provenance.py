"""Fictional definitions only: public reconstruction, retention and P1 gates."""
from dataclasses import replace
import json
from pathlib import Path
import random
import re
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import patch

import jsonschema
import pytest

from bg3loc.cli import main
from bg3loc.research.context import ContextAggregator, extract_passive_context_hits
from bg3loc.research.model import ResearchScanResource
from bg3loc.research.provenance_export import export_public_structural_provenance
from bg3loc.research.quest import filter_quest_context_candidates, parse_quest_xml
from bg3loc.research.stats import parse_stats_text
from bg3loc.research.structural_provenance import (
    IdentityOrigin as Origin, definition_fingerprint, parse_structural_stats,
    parse_structural_xml, write_structural_provenance,
)
from bg3loc.research.ui_skill_universe import UiSkillProvider, parse_ui_skill_provider, write_ui_skill_universe
from bg3loc.same_entity_context import (
    ENTITY_TYPES, ContextAbsenceReason, SameEntitySourceRecord,
    StructuralIdentityKind as Kind, build_same_entity_context, fingerprint,
)

UID = "h11111111g2222g3333g4444g555555555555"
DETAIL = "h66666666g7777g8888g9999g000000000000"
UUID = "11111111-2222-4333-8444-555555555555"


def stats(extra='data "Power" "1"', entry="FictionalSpell"):
    return (f'new entry "{entry}"\ntype "SpellData"\ndata "DisplayName" "{UID};1"\n'
            f'data "Description" "{DETAIL};2"\nusing "FictionalParent"\n{extra}\n')


def xml(kind="item", identity_field="UUID", identity=UUID, extra=""):
    node = "GameObjects" if kind == "item" else "JournalEntity"
    field = "DisplayName" if kind == "item" else "Title"
    native = f'<attribute id="{identity_field}" value="{identity}"/>' if identity_field else ""
    return (f'<save><region id="Fixture"><node id="{node}">{native}'
            f'<attribute id="{field}" type="TranslatedString" handle="{UID}" version="1"/>'
            f'<attribute id="Description" handle="{DETAIL}" version="2"/>{extra}'
            '</node></region></save>')


def definitions(kind, *, path="Public/Fixture/definition.txt", extra=""):
    if kind == "stats":
        return parse_structural_stats(stats(extra or 'data "Power" "1"'), resource_path=path, package="Fixture.pak")
    return parse_structural_xml(xml(kind, extra=extra), kind=kind, resource_path=path, package="Fixture.pak")


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_stats_origin_full_boundary_and_parent_after_occurrences():
    rows = list(parse_stats_text(stats(), resource_path="Public/Fixture/Spell.txt", provider="Fixture.pak"))
    assert len(rows) == 2
    assert {row.metadata["identityOrigin"] for row in rows} == {"ENTRY_NAME"}
    assert {row.metadata["entityIdentity"] for row in rows} == {"FictionalSpell"}
    assert len({row.metadata["definitionFingerprint"] for row in rows}) == 1
    assert all(row.evidence[0].properties["using"] == "FictionalParent" for row in rows)
    assert rows[0].metadata["definitionFingerprint"] != list(parse_stats_text(
        stats('data "Power" "2"')))[0].metadata["definitionFingerprint"]
    assert rows[0].metadata["definitionFingerprint"] != list(parse_stats_text(
        stats().replace("FictionalParent", "OtherParent")))[0].metadata["definitionFingerprint"]


@pytest.mark.parametrize("kind", ["stats", "item", "quest"])
def test_digest_whole_definition_order_path_and_semantic_change(kind):
    definition = definitions(kind)[0]
    changed = definitions(kind, extra='data "Power" "2"' if kind == "stats" else '<attribute id="Power" value="2"/>')[0]
    assert definition.fingerprint != changed.fingerprint
    assert re.fullmatch("[0-9a-f]{64}", definition.fingerprint)
    assert definition.fingerprint == definitions(kind, path="Other/Archive/definition.lsx")[0].fingerprint
    # The end-to-end CLI test separately repeats under different absolute installs.
    assert definition_fingerprint(dict(reversed(list(definition.payload.items())))) == definition.fingerprint
    if kind == "stats":
        lines = stats().splitlines()
        reordered = "\n".join([lines[0], *reversed(lines[1:])])
        reordered_definition = parse_structural_stats(reordered)[0]
    else:
        root = ET.fromstring(xml(kind))
        node = root.find("./region/node")
        node[:] = list(reversed(list(node)))
        node.attrib = dict(reversed(list(node.attrib.items())))
        reordered_definition = parse_structural_xml(ET.tostring(root, encoding="unicode"), kind=kind)[0]
    assert reordered_definition.fingerprint == definition.fingerprint


@pytest.mark.parametrize("native,expected", [
    ("UUID", Origin.UUID), ("MapKey", Origin.MAP_KEY), ("Name", Origin.NAME),
    ("", Origin.FALLBACK_ORDINAL),
])
def test_item_native_origin_and_additive_csv(native, expected, tmp_path):
    path = tmp_path / "template.lsx"
    path.write_text(xml(identity_field=native), encoding="utf-8")
    provider = UiSkillProvider("Fixture.pak", "Public/Fixture/RootTemplates/template.lsx", "LSX",
                              "Fixture", ("Root Templates",), ("RootTemplate",), ("Item.Unknown",))
    rows = parse_ui_skill_provider(path, provider)
    assert len(rows) == 2
    assert all(row.identity_origin == expected for row in rows)
    assert all(row.entity_identity == (UUID if native else "GameObjects#1") for row in rows)
    assert all(re.fullmatch("[0-9a-f]{64}", row.definition_fingerprint) for row in rows)
    output = tmp_path / "ui.csv"
    write_ui_skill_universe(output, rows)
    import csv
    exported = list(csv.DictReader(output.open(encoding="utf-8")))
    assert all(row["IdentityOrigin"] == expected.value for row in exported)
    assert all(row["EntityIdentity"] for row in exported)
    write_ui_skill_universe(tmp_path / "reversed.csv", list(reversed(rows)))
    assert output.read_bytes() == (tmp_path / "reversed.csv").read_bytes()


def test_item_identity_priority_and_nested_definition_payload():
    text = xml(extra='<attribute id="Name" value="FictionalItem"/>'
               '<children><node id="Nested"><attribute id="Power" value="1"/></node></children>')
    definition = parse_structural_xml(text)[0]
    assert definition.entity_identity == UUID and definition.identity_origin == Origin.UUID
    assert len(definition.occurrences) == 2
    assert definition.fingerprint != parse_structural_xml(text.replace('value="1"', 'value="2"'))[0].fingerprint
    assert definition.fingerprint != parse_structural_xml(text.replace('value="FictionalItem"', 'value="OtherItem"'))[0].fingerprint


@pytest.mark.parametrize("field,expected", [("ID", "ENTITY_ID"), ("entityId", "ENTITY_ID"),
                                            ("", "FALLBACK_ORDINAL")])
def test_quest_native_vs_fallback_origin(field, expected):
    rows = list(parse_quest_xml(xml("quest", identity_field=field, identity="FictionalQuest"),
                               resource_path="Mods/Fixture/Journal/quest.lsx", pak_name="Fixture.pak"))
    assert len(rows) == 2
    assert all(row.metadata["identityOrigin"] == expected for row in rows)
    assert all(row.evidence[0].properties["definitionFingerprint"] == row.metadata["definitionFingerprint"] for row in rows)
    assert {row.classification for row in rows} == {"QuestTitle", "QuestDescription"}


def test_quest_node_fallback_and_nested_boundaries():
    row = list(parse_quest_xml(f'<save><attribute id="Title" handle="{UID}"/></save>'))[0]
    assert row.metadata["identityOrigin"] == "FALLBACK_NODE"
    text = xml("quest", identity_field="ID", identity="FictionalQuest", extra=
               f'<children><node id="Step"><attribute id="ID" value="FictionalStep"/>'
               f'<attribute id="Description" handle="{DETAIL}"/></node></children>')
    definitions = parse_structural_xml(text, kind="quest")
    assert len(definitions) == 2
    assert [len(row.occurrences) for row in definitions] == [2, 1]
    assert definitions[0].fingerprint != parse_structural_xml(text.replace("FictionalStep", "ChangedStep"), kind="quest")[0].fingerprint


@pytest.mark.parametrize("kind", ["stats", "item", "quest"])
def test_multi_definition_retention_exact_dedup_and_byte_determinism(kind, tmp_path):
    first = definitions(kind)[0]
    equivalent = replace(first, source_resource="Other.pak/Public/Fixture/definition")
    changed = definitions(kind, extra='data "Power" "2"' if kind == "stats" else '<attribute id="Power" value="2"/>')[0]
    no_occurrence = replace(changed, payload={**changed.payload, "fictionalUnlocalized": True}, occurrences=())
    items = [first, equivalent, changed, no_occurrence, first]
    summary = write_structural_provenance(tmp_path / "one", items)
    random.Random(17).shuffle(items)
    second = write_structural_provenance(tmp_path / "two", items)
    assert summary == second
    assert summary["definitionCount"] == 4
    assert summary["identitiesWithMultipleDefinitions"][first.definition_type] == 1
    assert summary["identitiesWithDistinctFingerprints"][first.definition_type] == 1
    for filename in ("structural-definitions.jsonl", "structural-occurrences.jsonl", "structural-provenance-summary.json"):
        assert (tmp_path / "one" / filename).read_bytes() == (tmp_path / "two" / filename).read_bytes()
    ledger = read_rows(tmp_path / "one" / "structural-definitions.jsonl")
    assert len({row["definitionFingerprint"] for row in ledger}) == 3
    assert all("payload" not in row and "sourceText" not in row for row in ledger)


def test_quest_and_context_aggregation_retain_every_definition_evidence():
    first = list(parse_quest_xml(xml("quest", identity_field="ID", identity="FictionalQuest"),
                                 resource_path="Mods/Fixture/Journal/a.lsx"))
    second = list(parse_quest_xml(xml("quest", identity_field="ID", identity="FictionalQuest",
                                    extra='<attribute id="Power" value="2"/>'),
                                  resource_path="Mods/Fixture/Journal/b.lsx"))
    candidates = filter_quest_context_candidates(first + second)
    assert len(candidates) == 2
    aggregator = ContextAggregator()
    aggregator.add_mappings(candidates)
    assert all(len({ev.properties["definitionFingerprint"] for ev in row.evidence}) == 2
               for row in aggregator.get_mappings())
    passive = stats().replace("SpellData", "PassiveData")
    hits = list(extract_passive_context_hits(passive, target_uids={UID, DETAIL}))
    assert len(hits) == 2
    assert all(hit.evidence[0].properties["identityOrigin"] == "ENTRY_NAME" for hit in hits)
    assert len({hit.evidence[0].properties["definitionFingerprint"] for hit in hits}) == 1


def adapt_public(row, category):
    origins = {"ENTRY_NAME": Kind.STATS_ENTRY_NAME, "UUID": Kind.TEMPLATE_UUID,
               "ENTITY_ID": Kind.JOURNAL_ENTITY_ID, "FALLBACK_ORDINAL": Kind.ORDINAL_FALLBACK}
    return SameEntitySourceRecord(
        content_uid=row["contentUid"], category=category, entity_type=ENTITY_TYPES[category],
        entity_identity=row["entityIdentity"], field_role=row["fieldRole"],
        source_text="Fictional title" if row["contentUid"] == UID else "A fictional source description.",
        identity_kind=origins.get(row["identityOrigin"], Kind.GENERIC_NODE),
        evidence_source=row["sourceResource"], evidence_fingerprint=fingerprint(row),
        definition_fingerprint=row["definitionFingerprint"],
    )


@pytest.mark.parametrize("kind,category", [("stats", "skill_spell"), ("item", "item"), ("quest", "quest")])
def test_public_only_rows_construct_reliable_p1_records_and_detect_conflicts(kind, category, tmp_path):
    definition = (definitions("stats")[0] if kind == "stats" else parse_structural_xml(
        xml(kind, identity_field="UUID" if kind == "item" else "ID", identity=UUID if kind == "item" else "FictionalQuest"),
        kind=kind, resource_path="Public/Fixture/definition.lsx", package="Fixture.pak")[0])
    write_structural_provenance(tmp_path, [definition])
    records = [adapt_public(row, category) for row in read_rows(tmp_path / "structural-occurrences.jsonl")]
    target = next(row for row in records if row.content_uid == UID)
    assert build_same_entity_context(target, records).context is not None
    conflict = replace(definition, payload={**definition.payload, "fictionalPower": "changed"})
    write_structural_provenance(tmp_path, [definition, conflict])
    records = [adapt_public(row, category) for row in read_rows(tmp_path / "structural-occurrences.jsonl")]
    assert build_same_entity_context(target, records).absence_reason == ContextAbsenceReason.STRUCTURAL_CONFLICT


@pytest.mark.parametrize("kind,field,category", [("item", "Name", "item"), ("item", "MapKey", "item"),
                                               ("quest", "", "quest")])
def test_public_origin_does_not_relax_p1_reliability(kind, field, category):
    definition = parse_structural_xml(xml(kind, identity_field=field), kind=kind)[0]
    records = [adapt_public(row, category) for row in definition.occurrence_rows()]
    assert build_same_entity_context(records[0], records).absence_reason == ContextAbsenceReason.NO_RELIABLE_IDENTITY


@pytest.mark.parametrize("bad", ["C:/fictional/private.lsx", "/Users/fictional/private.lsx",
                                 "../private.lsx", "\\\\server\\private.lsx"])
def test_absolute_and_private_source_paths_rejected(bad):
    with pytest.raises(ValueError):
        parse_structural_stats(stats(), resource_path=bad)
    with pytest.raises(ValueError):
        parse_structural_xml(xml(), resource_path=bad)


def test_schema_validation_and_no_source_text_export(tmp_path):
    all_defs = [definitions(kind)[0] for kind in ("stats", "item", "quest")]
    write_structural_provenance(tmp_path, all_defs)
    schema_dir = Path(__file__).resolve().parents[1] / "schemas" / "research"
    for stem in ("definition", "occurrence"):
        schema = json.loads((schema_dir / f"public-structural-{stem}-v1.schema.json").read_text(encoding="utf-8"))
        for row in read_rows(tmp_path / f"structural-{stem}s.jsonl"):
            jsonschema.validate(row, schema)
            assert "sourceText" not in row
            assert row["sourceResource"] == "Fixture.pak/Public/Fixture/definition.txt"


def test_public_cli_reads_all_resource_layers_and_repeats_across_install_paths(tmp_path):
    stats_path = "Public/Fixture/Stats/Generated/Data/Spell_Fictional.txt"
    item_path = "Public/Fixture/RootTemplates/template.lsf"
    quest_path = "Mods/Fixture/Journal/quest.lsx"
    payloads = {("First.pak", stats_path): stats(), ("Second.pak", stats_path): stats('data "Power" "2"'),
                ("First.pak", item_path): xml(), ("First.pak", quest_path): xml("quest")}

    class Backend:
        def list_archive(self, archive):
            return []

        def extract_single_file(self, archive, path, destination):
            destination.write_text(payloads[(archive.name, path)], encoding="utf-8")

        def convert_resource(self, source, destination):
            destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    resources = [ResearchScanResource(package, path, "LSF" if path.endswith(".lsf") else "TXT" if path.endswith(".txt") else "LSX",
                                     "StatsResource" if path.endswith(".txt") else "RootTemplates" if path.endswith(".lsf") else "JournalQuest")
                 for package, path in payloads]
    for iteration in range(2):
        game = tmp_path / f"install-{iteration}"
        (game / "Data").mkdir(parents=True)
        for package in ("First.pak", "Second.pak"):
            (game / "Data" / package).touch()
        scan_path = tmp_path / "scan.json"
        scan_path.write_text(json.dumps({"gameDir": str(game), "resources": [row.to_dict() for row in resources]}), encoding="utf-8")
        with patch("bg3loc.commands.research.resolve_backend"), patch(
            "bg3loc.commands.research.backend_from_probe", return_value=Backend()):
            assert main(["research", "export-provenance", "--scan", str(scan_path),
                         "--output-dir", str(tmp_path / f"out-{iteration}")]) == 0
        resources.reverse()
    for filename in ("structural-definitions.jsonl", "structural-occurrences.jsonl", "structural-provenance-summary.json"):
        assert (tmp_path / "out-0" / filename).read_bytes() == (tmp_path / "out-1" / filename).read_bytes()
    rows = read_rows(tmp_path / "out-0" / "structural-definitions.jsonl")
    assert len(rows) == 4
    spell_rows = [row for row in rows if row["definitionType"] == "StatsEntry"]
    assert len({row["definitionFingerprint"] for row in spell_rows}) == 2


def test_exporter_missing_archive_and_malformed_resource_fail_closed(tmp_path):
    resource = ResearchScanResource("Missing.pak", "Public/Fixture/Stats/Generated/Data/Spell.txt", "TXT", "StatsResource")
    with patch("bg3loc.research.provenance_export.discover_ui_skill_providers", return_value=[]), pytest.raises(ValueError):
        export_public_structural_provenance(tmp_path, SimpleNamespace(), tmp_path / "output", [resource])
    with pytest.raises(ET.ParseError):
        parse_structural_xml("<malformed")


def test_stats_inline_comments_do_not_merge_boundaries_or_modify_values():
    base = parse_structural_stats(stats())[0]
    commented = "\n".join(line + " // fictional comment" for line in stats().splitlines())
    assert parse_structural_stats(commented)[0].fingerprint == base.fingerprint
    assert len(parse_structural_stats(commented + '\nnew entry "Other" // separate boundary')) == 2
    value = parse_structural_stats(stats('data "Reference" "folder//asset#part"'))[0]
    assert value.payload["fields"]["Reference"] == ["folder//asset#part"]
    with pytest.raises(ValueError):
        parse_structural_stats(stats() + '\nnew entry "unterminated')


def test_repeated_fields_and_ordered_children_are_semantic():
    first = stats('data "Power" "1"\ndata "Power" "2"')
    second = stats('data "Power" "2"\ndata "Power" "1"')
    assert parse_structural_stats(first)[0].fingerprint != parse_structural_stats(second)[0].fingerprint
    extra = '<children><node id="First"/><node id="Second"/></children>'
    assert parse_structural_xml(xml(extra=extra))[0].fingerprint != parse_structural_xml(
        xml(extra=extra.replace('<node id="First"/><node id="Second"/>', '<node id="Second"/><node id="First"/>')))[0].fingerprint
    extra = '<attribute id="Power" value="1"/><attribute id="Power" value="2"/>'
    assert parse_structural_xml(xml(extra=extra))[0].fingerprint != parse_structural_xml(
        xml(extra=extra.replace('value="1"', 'value="3"')))[0].fingerprint


def test_repeated_occurrences_survive_exact_definition_dedup(tmp_path):
    definition = parse_structural_stats(stats(f'data "DisplayName" "{UID};1"'),
                                         resource_path="Public/Fixture/Spell.txt", package="Fixture.pak")[0]
    summary = write_structural_provenance(tmp_path, [definition, definition])
    assert summary["definitionCount"] == 1 and summary["occurrenceCount"] == 3
    rows = read_rows(tmp_path / "structural-occurrences.jsonl")
    assert {row["occurrenceIndex"] for row in rows if row["contentUid"] == UID} == {1, 2}


def test_ambiguous_native_identity_retains_payload_and_marks_unknown():
    definition = parse_structural_xml(xml(extra='<attribute id="UUID" value="OtherUuid"/>'))[0]
    assert definition.identity_origin == Origin.UNKNOWN
    assert len(definition.payload["node"]["fields"]["UUID"]) == 2


def test_provider_discovery_retains_support_definitions_without_uid_lists(tmp_path):
    game = tmp_path / "game"
    (game / "Data").mkdir(parents=True)
    for package in ("Game.pak", "Shared.pak"):
        (game / "Data" / package).touch()
    path = "Public/Shared/Stats/Generated/Data/Spell_Fictional.txt"

    class Backend:
        def list_archive(self, archive):
            return [SimpleNamespace(path=path)]

        def extract_single_file(self, archive, internal_path, destination):
            destination.write_text(stats('data "Power" "2"' if archive.name == "Shared.pak" else 'data "Power" "1"'), encoding="utf-8")

    summary = export_public_structural_provenance(game, Backend(), tmp_path / "out", [])
    assert summary["definitionCount"] == 2
    assert summary["identitiesWithDistinctFingerprints"]["StatsEntry"] == 1


@pytest.mark.parametrize("field", ["DisplayName", "Description", "using", "entryName"])
def test_stats_localization_and_native_identity_changes_digest(field):
    source = stats()
    replacements = {"DisplayName": (UID, DETAIL), "Description": (DETAIL, UID),
                    "using": ("FictionalParent", "OtherParent"), "entryName": ("FictionalSpell", "OtherSpell")}
    before, after = replacements[field]
    assert parse_structural_stats(source)[0].fingerprint != parse_structural_stats(source.replace(before, after))[0].fingerprint
