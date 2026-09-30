from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import validate

from bg3loc.research.context_experiment import ContextSourceRecord, blind_candidate_order, build_packs, normalize_records, read_rows, render_pair, run
from bg3loc.ruleset_io import load_ruleset

FIXTURE = Path(__file__).parent / "fixtures" / "b1_02"
ROOT = Path(__file__).parents[1]


def test_fictional_fixture_and_reproducibility(tmp_path):
    rows = read_rows(FIXTURE / "source_rows.jsonl")
    packs, coverage = build_packs(rows)
    assert len(packs) == 6
    assert all(coverage[c]["rowsWithRelatedField"] == 2 for c in coverage)
    schema = json.loads((ROOT / "schemas/research/context-pack-v1.schema.json").read_text())
    for pack in packs:
        validate(pack, schema)
    first = run(FIXTURE / "source_rows.jsonl", FIXTURE / "ruleset.json", tmp_path / "a")
    second = run(FIXTURE / "source_rows.jsonl", FIXTURE / "ruleset.json", tmp_path / "b")
    assert first == second
    assert (tmp_path / "a/b1-02-prompts.jsonl").read_bytes() == (tmp_path / "b/b1-02-prompts.jsonl").read_bytes()


def test_target_exclusion_duplicates_priority_limits_and_leakage():
    rows = read_rows(FIXTURE / "source_rows.jsonl")
    base = next(r for r in rows if r["contentUid"] == "f-skill-desc")
    rows.extend([
        {**base, "contentUid": "duplicate", "fieldRole": "ExtraDescription"},
        {**base, "contentUid": "alias", "fieldRole": "Tooltip", "sourceText": base["sourceText"].upper()},
        {**base, "contentUid": "extra", "fieldRole": "ExtraDescription", "sourceText": "A different detail."},
        {**base, "contentUid": "short", "fieldRole": "ShortDescription", "sourceText": "A short detail."},
        {**base, "contentUid": "tooltip", "fieldRole": "Tooltip", "sourceText": "A tooltip detail."},
    ])
    packs, _ = build_packs(rows, max_fields=2, max_chars=50)
    pack = next(p for p in packs if p["target"]["contentUid"] == "f-skill-desc")
    assert [f["fieldRole"] for f in pack["relatedFields"]] == ["DisplayName", "ExtraDescription"]
    assert sum(len(f["sourceText"]) for f in pack["relatedFields"]) <= 50
    assert all(f["contentUid"] != pack["target"]["contentUid"] for f in pack["relatedFields"])
    a, b = render_pair(pack, load_ruleset(FIXTURE / "ruleset.json"))
    assert "relatedFields" not in a[1]["content"]
    assert "The related fields are context only." in b[0]["content"]
    assert "護符" in a[0]["content"] and "護符" in b[0]["content"]
    assert "ExistingTargetText" not in json.dumps(b)


def test_unproved_item_identity_rejected(tmp_path):
    row = json.loads((FIXTURE / "source_rows.jsonl").read_text().splitlines()[2])
    del row["structuralEvidence"]["templateId"]
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="templateId"):
        read_rows(path)


def test_manifest_schema_and_input_order_independence(tmp_path):
    lines = (FIXTURE / "source_rows.jsonl").read_text().splitlines()
    reversed_input = tmp_path / "reversed.jsonl"
    reversed_input.write_text("\n".join(reversed(lines)) + "\n")
    first = run(FIXTURE / "source_rows.jsonl", FIXTURE / "ruleset.json", tmp_path / "a")
    second = run(reversed_input, FIXTURE / "ruleset.json", tmp_path / "b")
    assert first == second
    schema = json.loads((ROOT / "schemas/research/context-experiment-manifest-v1.schema.json").read_text())
    validate(first, schema)
    prompts = [json.loads(line) for line in (tmp_path / "a/b1-02-prompts.jsonl").read_text().splitlines()]
    assert len({row["contextPackFingerprint"] for row in prompts}) == len(prompts)
    assert all(row["deltaChars"] > 0 for row in prompts)


def test_different_entity_empty_and_unknown_role():
    rows = read_rows(FIXTURE / "source_rows.jsonl")
    base = next(r for r in rows if r["contentUid"] == "f-item-desc")
    rows.extend([
        {**base, "contentUid": "other-item", "entityKey": "fictional-item-002", "sourceText": "Never merge this object."},
        {**base, "contentUid": "empty", "fieldRole": "Tooltip", "sourceText": ""},
        {**base, "contentUid": "unknown", "fieldRole": "MysteryField", "sourceText": "An unknown-role clue."},
        {**base, "contentUid": "tooltip", "fieldRole": "Tooltip", "sourceText": "A known-role clue."},
    ])
    packs, _ = build_packs(rows)
    target = next(p for p in packs if p["target"]["contentUid"] == "f-item-desc")
    assert [f["fieldRole"] for f in target["relatedFields"]] == ["DisplayName", "Tooltip", "MysteryField"]
    assert "Never merge this object." not in json.dumps(target)
    assert "empty" not in [f["contentUid"] for f in target["relatedFields"]]


def test_same_uid_occurrence_and_target_translation_discarded(tmp_path):
    lines = (FIXTURE / "source_rows.jsonl").read_text().splitlines()
    row = json.loads(lines[0])
    row["ExistingTargetText"] = "FAKE TARGET TRANSLATION DO NOT LEAK"
    row["referenceTranslation"] = "REFERENCE SECRET"
    lines.append(json.dumps(row))
    path = tmp_path / "rows.jsonl"
    path.write_text("\n".join(lines) + "\n")
    rows = read_rows(path)
    packs, _ = build_packs(rows)
    assert "FAKE TARGET TRANSLATION" not in json.dumps(packs)
    assert "REFERENCE SECRET" not in json.dumps(packs)
    target = next(p for p in packs if p["target"]["contentUid"] == "f-skill-desc")
    assert [f["contentUid"] for f in target["relatedFields"]].count("f-skill-name") == 1


def test_oversized_field_truncation_and_whole_field_preference():
    rows = read_rows(FIXTURE / "source_rows.jsonl")
    base = next(r for r in rows if r["contentUid"] == "f-item-desc")
    rows += [
        {**base, "contentUid": "long", "fieldRole": "Tooltip", "sourceText": "L" * 21},
        {**base, "contentUid": "small", "fieldRole": "MysteryField", "sourceText": "Tiny."},
    ]
    packs, _ = build_packs(rows, max_fields=4, max_chars=20)
    target = next(p for p in packs if p["target"]["contentUid"] == "f-item-desc")
    assert target["relatedFields"][0]["sourceText"] == "Moonstone Charm"
    assert target["relatedFields"][1]["sourceText"] == "Tiny."
    assert all(not f["truncated"] for f in target["relatedFields"])
    oversized = next(p for p in packs if p["target"]["contentUid"] == "f-item-name")
    # Description is itself longer than the total budget and may be cut.
    assert oversized["relatedFields"][0]["truncated"] is True
    assert len(oversized["relatedFields"][0]["sourceText"]) == 20


def test_prompt_variants_have_identical_target_and_rules():
    rows = read_rows(FIXTURE / "source_rows.jsonl")
    packs, _ = build_packs(rows)
    pack = next(p for p in packs if p["target"]["contentUid"] == "f-quest-desc")
    a, b = render_pair(pack, load_ruleset(FIXTURE / "ruleset.json"))
    ap = json.loads(a[1]["content"])
    bp = json.loads(b[1]["content"])
    assert ap["sourceText"] == bp["sourceText"]
    assert ap["primaryCategory"] == bp["primaryCategory"]
    assert ap["targetFieldRole"] == bp["targetFieldRole"]
    assert "Find the Lost Courier" not in json.dumps(a)
    assert "Find the Lost Courier" in json.dumps(b)
    assert all(s in b[0]["content"] for s in (
        "The related fields are context only.",
        "Translate only the target source text.",
        "Do not add information that appears only in the context.",
        "Do not translate or return the context fields.",
    ))


def test_blind_candidate_order_is_stable():
    assert blind_candidate_order("sample-1", "A", "B") == blind_candidate_order("sample-1", "A", "B")
    assert set(blind_candidate_order("sample-1", "A", "B")) == {"A", "B"}


def test_in_memory_record_adapter_and_protected_tokens():
    records = [
        ContextSourceRecord("token-name", "skill_spell", "Skill_Test", "StatsEntry", "DisplayName",
                            "Frost Spark", "StatsDefinition"),
        ContextSourceRecord("token-desc", "skill_spell", "Skill_Test", "StatsEntry", "Description",
                            "Deal {Damage} cold damage.", "StatsDefinition"),
    ]
    packs, _ = build_packs(normalize_records(records))
    target = next(p for p in packs if p["target"]["contentUid"] == "token-desc")
    a, b = render_pair(target, load_ruleset(FIXTURE / "ruleset.json"))
    assert "Protected runtime tokens" in a[0]["content"]
    assert "Protected runtime tokens" in b[0]["content"]
    with pytest.raises(ValueError, match="entity_type"):
        normalize_records([ContextSourceRecord("x", "quest", "Q", "StatsEntry", "QuestTitle", "Title", "QuestJournal")])
