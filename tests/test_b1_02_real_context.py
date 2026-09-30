from __future__ import annotations

import csv
import json

from bg3loc.research.context_experiment import build_packs, read_rows
from bg3loc.research.real_context import adapt, summarize


def test_real_adapter_conflicts_holds_and_source_boundary(tmp_path):
    source = tmp_path / "English.jsonl"
    source.write_text("".join(json.dumps({"localeId": "English", "contentUid": uid, "text": text}) + "\n"
                              for uid, text in [("name", "Fictional flame"), ("desc", "A bright fictional effect."),
                                                ("conflict", "Conflicting fictional effect."), ("item", "A fictional item.")]), encoding="utf-8")
    mappings = tmp_path / "mappings.jsonl"
    rows = []
    for uid, entity, role in [("name", "Spell_One", "DisplayName"), ("desc", "Spell_One", "Description"),
                              ("conflict", "Spell_One", "Tooltip"), ("conflict", "Spell_Two", "Tooltip")]:
        rows.append({"contentUid": uid, "mappingType": "stat-reference", "evidence": [{"evidenceType": "StatsDefinition",
                     "resourcePath": "fictional.txt", "properties": {"entryType": "SpellData", "entryName": entity, "fieldName": role}}]})
    mappings.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    universe = tmp_path / "universe.csv"
    with universe.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["ContentUid", "Status", "Workstream", "EntityType", "EntityName", "FieldName", "SourceFamilies", "Provider"])
        writer.writeheader()
        writer.writerow({"ContentUid": "item", "Status": "Hold", "Workstream": "ItemsEquipment", "EntityType": "GameObjects",
                         "EntityName": "fictional-uuid", "FieldName": "DisplayName", "SourceFamilies": "Root Templates", "Provider": "fictional::template"})
    records, all_counts, exclusions = adapt(source, mappings, universe)
    assert {row["contentUid"] for row in records} == {"name", "desc"}
    assert all_counts == {"skill_spell": 3, "item": 1}
    assert exclusions[("skill_spell", "structuralConflictRows")] == 1
    assert exclusions[("item", "holdRows")] == 1
    assert next(row for row in records if row["contentUid"] == "desc")["fieldRole"] == "Description"
    assert all(row["entityKey"] == "Spell_One" and row["entityType"] == "StatsEntry" for row in records)
    normalized = [json.loads(json.dumps(row)) for row in records]
    path = tmp_path / "records.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in normalized), encoding="utf-8")
    packs, _ = build_packs(read_rows(path))
    assert len(packs) == 2
    assert all(pack["target"]["entityKey"] == "Spell_One" for pack in packs)


def test_summary_counts_distinct_entities():
    rows = [
        {"contentUid": "a", "category": "item", "entityKey": "one", "fieldRole": "DisplayName", "sourceText": "A fictional hat", "structuralEvidence": {}},
        {"contentUid": "b", "category": "item", "entityKey": "one", "fieldRole": "Description", "sourceText": "A fictional description", "structuralEvidence": {}},
        {"contentUid": "c", "category": "item", "entityKey": "two", "fieldRole": "DisplayName", "sourceText": "A fictional boot", "structuralEvidence": {}},
    ]
    data = summarize(rows, {"item": 3}, {}, [])
    assert data["item"]["entities"]["count"] == 2
    assert data["item"]["entities"]["singleField"] == 1
    assert data["item"]["entities"]["multiField"] == 1
