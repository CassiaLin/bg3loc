from __future__ import annotations

import csv
import json
from pathlib import Path

from jsonschema import validate

from bg3loc.research.context_experiment import build_packs, digest, read_rows, render_pair
from bg3loc.research.context_pilot import write_json, write_jsonl
from bg3loc.research.safety_validation import (
    REVIEW_FIELDS,
    build_safety_review,
    export_safety_package,
    summarize_review,
)
from bg3loc.ruleset_io import load_ruleset


FIXTURE = Path(__file__).parent / "fixtures" / "b1_02"
ROOT = Path(__file__).parents[1]


def _records() -> list[dict]:
    rows = []
    specifications = (
        ("skill_spell", 20, "entryName", "StatsDefinition", "Skill", ("DisplayName", "Description")),
        ("item", 20, "templateId", "GameObjectTemplate", "Item", ("DisplayName", "Description")),
        ("quest", 10, "entityId", "QuestJournal", "Quest", ("QuestTitle", "QuestDescription")),
    )
    for category, entity_count, identity_key, evidence_type, prefix, roles in specifications:
        for index in range(entity_count):
            identity = f"Synthetic_{prefix}_{index:02d}"
            for role in roles:
                rows.append({
                    "contentUid": f"synthetic-{category}-{index:02d}-{role.lower()}",
                    "category": category,
                    "fieldRole": role,
                    "sourceText": f"Fictional {prefix} {index:02d} {role} text.",
                    "structuralEvidence": {
                        identity_key: identity,
                        "evidenceType": evidence_type,
                        "resourceIdentity": f"Fictional/{prefix}.lsx",
                    },
                })
    return rows


def _frozen_pilot(tmp_path: Path) -> tuple[Path, Path]:
    source_path = tmp_path / "synthetic-source.jsonl"
    write_jsonl(source_path, _records())
    packs, _ = build_packs(read_rows(source_path))
    ruleset = load_ruleset(FIXTURE / "ruleset.json")
    sample = []
    for pack in packs:
        baseline, context = render_pair(pack, ruleset)
        sample.append({
            "sampleId": digest(pack["target"]),
            "contextPack": pack,
            "baselinePrompt": baseline,
            "contextPrompt": context,
            "baselinePromptHash": digest(baseline),
            "contextPromptHash": digest(context),
        })
    sample_path = tmp_path / "pilot-sample.jsonl"
    manifest_path = tmp_path / "pilot-manifest.json"
    write_jsonl(sample_path, sample)
    write_json(manifest_path, {
        "pilotSampleFingerprint": digest([row["contextPack"] for row in sample]),
        "plannedCalls": 200,
    })
    return sample_path, manifest_path


def test_safety_export_is_deterministic_10_10_5_and_anonymous(tmp_path):
    sample, pilot_manifest = _frozen_pilot(tmp_path)
    first, second = tmp_path / "first", tmp_path / "second"
    manifest_a = export_safety_package(sample, pilot_manifest, first, require_canonical_pilot=False)
    manifest_b = export_safety_package(sample, pilot_manifest, second, require_canonical_pilot=False)

    assert manifest_a == manifest_b
    assert manifest_a["categoryCounts"] == {"skill_spell": 10, "item": 10, "quest": 5}
    assert manifest_a["sampleCount"] == 25
    assert manifest_a["requestCount"] == 50
    schema = json.loads((ROOT / "schemas/research/b1-02-safety-package-v1.schema.json").read_text())
    validate(manifest_a, schema)
    for name in ("safety-requests.jsonl", "safety-response-template.jsonl", "safety-review.csv"):
        assert (first / name).read_bytes() == (second / name).read_bytes()

    requests = [json.loads(line) for line in (first / "safety-requests.jsonl").read_text().splitlines()]
    assert len(requests) == len({row["requestId"] for row in requests}) == 50
    assert sum(bool(row["context"]) for row in requests) == 25
    for row in requests:
        serialized = json.dumps(row)
        assert "sampleId" not in serialized
        assert "ContentUid" not in serialized
        assert '"variant"' not in serialized

    internal = json.loads((first / "safety-internal-request-map.json").read_text())
    assert {row["variant"] for row in internal} == {"A", "B"}
    hidden = json.loads((first / "safety-review-hidden-key.json").read_text())
    assert len(hidden) == 25
    assert all({row["candidate1Variant"], row["candidate2Variant"]} == {"A", "B"} for row in hidden)

    with (first / "safety-review.csv").open(encoding="utf-8-sig", newline="") as stream:
        review = list(csv.DictReader(stream))
    assert len(review) == 25
    assert tuple(review[0]) == REVIEW_FIELDS
    assert all(not row["candidate1"] and not row["candidate2"] for row in review)
    assert all(not row["bWorseThanA"] and not row["contextContamination"] for row in review)

    responses = [{"requestId": row["requestId"], "translatedText": f"虛構譯文 {index}", "translatorNotes": ""}
                 for index, row in enumerate(requests)]
    response_path = tmp_path / "responses.jsonl"
    write_jsonl(response_path, responses)
    report = build_safety_review(first, response_path)
    assert report == {"reviewablePairs": 25, "invalidResponses": 0, "complete": True}
    with (first / "safety-review.csv").open(encoding="utf-8-sig", newline="") as stream:
        populated = list(csv.DictReader(stream))
    assert all(row["candidate1"] and row["candidate2"] for row in populated)


def test_safety_summary_derives_hidden_b_and_tracks_recurring_patterns(tmp_path):
    sample, pilot_manifest = _frozen_pilot(tmp_path)
    package = tmp_path / "package"
    export_safety_package(sample, pilot_manifest, package, require_canonical_pilot=False)
    hidden = json.loads((package / "safety-review-hidden-key.json").read_text())
    key_by_sample = {row["sampleId"]: row for row in hidden}
    with (package / "safety-review.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))

    skill_rows = [row for row in rows if row["category"] == "skill_spell"][:2]
    for row in skill_rows:
        key = key_by_sample[row["sampleId"]]
        row["worseCandidate"] = "candidate1" if key["candidate1Variant"] == "B" else "candidate2"
        row["contaminationCandidate"] = "neither"
        row["failurePattern"] = "wrong sense selection"
        row["reason"] = "Synthetic reviewer note"
    item_row = next(row for row in rows if row["category"] == "item")
    item_row["worseCandidate"] = "unclear"
    item_row["contaminationCandidate"] = "unclear"

    reviewed = tmp_path / "reviewed.csv"
    with reviewed.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=REVIEW_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary = summarize_review(reviewed, package / "safety-review-hidden-key.json")
    by_category = {row["category"]: row for row in summary["categories"]}
    assert by_category["skill_spell"]["reviewedPairs"] == 2
    assert by_category["skill_spell"]["bWorseCount"] == 2
    assert by_category["skill_spell"]["contaminationCount"] == 0
    assert by_category["skill_spell"]["recurringFailurePatterns"] == [
        {"pattern": "wrong sense selection", "count": 2}
    ]
    assert by_category["item"]["reviewedPairs"] == 1
    assert by_category["item"]["unclearCount"] == 1
    assert by_category["quest"]["reviewedPairs"] == 0
    assert summary["decision"] == "HUMAN_DECISION_REQUIRED"
