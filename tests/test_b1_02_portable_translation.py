from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from jsonschema import validate

from bg3loc.research.context_experiment import digest, read_rows, render_pair
from bg3loc.research.context_pilot import write_json, write_jsonl
from bg3loc.research import portable_translation as portable
from bg3loc.ruleset_io import load_ruleset

ROOT = Path(__file__).parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "b1_02"


def synthetic_pilot(tmp_path, monkeypatch):
    entities = json.loads((FIXTURE / "portable_entities.json").read_text(encoding="utf-8"))
    assert [row["entityKey"] for row in entities] == ["Skill_FrostSpark", "Item_MoonstoneCharm", "Quest_LostCourier"]
    originals = {row["category"]: row for row in read_rows(FIXTURE / "source_rows.jsonl")}
    rules = load_ruleset(FIXTURE / "ruleset.json")
    counts = {"skill_spell": 40, "item": 40, "quest": 20}
    rows = []
    for descriptor in entities:
        category = descriptor["category"]
        original = originals[category]
        for index in range(counts[category]):
            source = descriptor["sourceText"] + (" A longer fictional sentence." * (index % 3))
            target = {"contentUid": f"fictional-{category}-{index}", "category": category,
                      "entityKey": f"{descriptor['entityKey']}_{index}", "fieldRole": descriptor["fieldRole"],
                      "sourceText": source}
            related = [{"contentUid": f"fictional-related-{category}-{index}",
                        "fieldRole": descriptor["context"][0]["fieldRole"],
                        "sourceText": descriptor["context"][0]["sourceText"], "truncated": False}]
            pack = {"schemaVersion": "b1-02-context-pack/1", "target": target, "relatedFields": related,
                    "structuralEvidence": original["structuralEvidence"]}
            baseline, context = render_pair(pack, rules)
            row = {"contextPack": pack, "baselinePrompt": baseline, "contextPrompt": context,
                   "baselinePromptHash": digest(baseline), "contextPromptHash": digest(context)}
            row["sampleId"] = digest(target)
            rows.append(row)
    fingerprint = digest([row["contextPack"] for row in rows])
    monkeypatch.setattr(portable, "EXPECTED_PILOT_FINGERPRINT", fingerprint)
    sample_path = tmp_path / "pilot-sample.jsonl"
    manifest_path = tmp_path / "pilot-manifest.json"
    write_jsonl(sample_path, rows)
    write_json(manifest_path, {"pilotSampleFingerprint": fingerprint})
    return sample_path, manifest_path


def exported(tmp_path, monkeypatch, name="package"):
    sample, manifest = synthetic_pilot(tmp_path, monkeypatch)
    output = tmp_path / name
    portable.export_package(sample, manifest, output)
    return output


def response_rows(package, count=None, corrupt_index=None):
    requests = portable.read_jsonl(package / "translation-requests.jsonl")
    selected = requests if count is None else requests[:count]
    rows = []
    for index, row in enumerate(selected):
        text = f"虛構譯文 {row['requestId']}"
        for token in portable.extract_protected_tokens(row["sourceText"]):
            text += " " + token
        if corrupt_index == index:
            text = "損壞的虛構譯文"
        rows.append({"requestId": row["requestId"], "translatedText": text, "translatorNotes": ""})
    return rows


def test_deterministic_export_schemas_anonymization_and_bom(tmp_path, monkeypatch):
    first = exported(tmp_path, monkeypatch, "first")
    second = exported(tmp_path, monkeypatch, "second")
    request_schema = json.loads((ROOT / "schemas/research/portable-translation-request-v1.schema.json").read_text())
    manifest_schema = json.loads((ROOT / "schemas/research/portable-package-manifest-v1.schema.json").read_text())
    requests = portable.read_jsonl(first / "translation-requests.jsonl")
    manifest = json.loads((first / "package-manifest.json").read_text())
    validate(manifest, manifest_schema)
    for row in requests:
        validate(row, request_schema)
        assert not portable.FORBIDDEN_PUBLIC_KEYS & row.keys()
    assert len(requests) == len({row["requestId"] for row in requests}) == 200
    assert manifest["categoryCounts"] == {"item": 40, "quest": 20, "skill_spell": 40}
    assert manifest["requestCategoryCounts"] == {"item": 80, "quest": 40, "skill_spell": 80}
    assert (first / "translation-requests.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    assert len(portable.read_jsonl(first / "response-template.jsonl")) == 200
    for name in ("translation-requests.jsonl", "translation-requests.csv", "response-template.jsonl", "package-manifest.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    audit = json.loads((first / "package-audit.json").read_text())
    assert audit["samplePairs"] == audit["completePairMappings"] == 100
    assert audit["contentUidExposedExternally"] == audit["variantLabelsExposedExternally"] == audit["sampleIdExposedExternally"] == 0


def test_complete_jsonl_round_trip_and_blind_review(tmp_path, monkeypatch):
    package = exported(tmp_path, monkeypatch)
    responses = tmp_path / "responses.jsonl"
    rows = response_rows(package)
    response_schema = json.loads((ROOT / "schemas/research/portable-translation-response-v1.schema.json").read_text())
    for row in rows:
        validate(row, response_schema)
    write_jsonl(responses, rows)
    imported = tmp_path / "imported"
    summary = portable.import_responses(package, responses, imported)
    assert summary == {"schemaVersion": "b1-02-portable-import/1",
                       "requestPackageFingerprint": json.loads((package / "package-manifest.json").read_text())["requestPackageFingerprint"],
                       "expected": 200, "received": 200, "valid": 200, "invalid": 0, "missing": 0,
                       "duplicate": 0, "unknown": 0, "packageComplete": True}
    review = tmp_path / "review"
    result = portable.build_review(package, imported / "imported-results.jsonl", review)
    assert result["reviewablePairs"] == 100
    blind = portable.read_jsonl(review / "blind-review.jsonl")
    assert len(blind) == 100
    assert all("variant" not in row and "requestId" not in row and "context" not in row for row in blind)
    keys = json.loads((review / "blind-review-key.json").read_text())["pairs"]
    assert len(keys) == 100 and all({row["candidate1Variant"], row["candidate2Variant"]} == {"A", "B"} for row in keys)
    assert (review / "blind-review.csv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_partial_csv_import_missing_empty_and_protected_syntax(tmp_path, monkeypatch):
    package = exported(tmp_path, monkeypatch)
    rows = response_rows(package, 4, corrupt_index=1)
    rows[2]["translatedText"] = ""
    path = tmp_path / "responses.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("requestId", "translatedText", "translatorNotes"), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    output = tmp_path / "partial"
    summary = portable.import_responses(package, path, output)
    assert summary["received"] == 4 and summary["valid"] == 2 and summary["invalid"] == 2 and summary["missing"] == 196
    assert summary["packageComplete"] is False
    results = portable.read_jsonl(output / "imported-results.jsonl")
    assert "PROTECTED_SYNTAX_MISSING" in results[1]["errorCodes"]
    assert results[2]["errorCodes"] == ["EMPTY_TRANSLATION", "PROTECTED_SYNTAX_MISSING"]


@pytest.mark.parametrize("mode", ("duplicate", "unknown"))
def test_import_rejects_duplicate_and_unknown_ids(tmp_path, monkeypatch, mode):
    package = exported(tmp_path, monkeypatch)
    rows = response_rows(package, 2)
    if mode == "duplicate":
        rows.append(dict(rows[0]))
    else:
        rows.append({"requestId": "req-999999", "translatedText": "虛構譯文", "translatorNotes": ""})
    path = tmp_path / "bad.jsonl"
    write_jsonl(path, rows)
    with pytest.raises(ValueError, match=mode):
        portable.import_responses(package, path, tmp_path / "bad-import")


def test_blind_pair_requires_both_valid_and_candidate_order_is_stable(tmp_path, monkeypatch):
    package = exported(tmp_path, monkeypatch)
    internal = json.loads((package / "internal-request-map.json").read_text())["requests"]
    first_sample = internal[0]["sampleId"]
    pair_ids = [row["requestId"] for row in internal if row["sampleId"] == first_sample]
    requests = {row["requestId"]: row for row in portable.read_jsonl(package / "translation-requests.jsonl")}
    responses = []
    for request_id in pair_ids:
        text = "成對虛構譯文 " + " ".join(portable.extract_protected_tokens(requests[request_id]["sourceText"]))
        responses.append({"requestId": request_id, "translatedText": text, "translatorNotes": ""})
    other = next(row for row in internal if row["sampleId"] != first_sample)
    text = "單邊虛構譯文 " + " ".join(portable.extract_protected_tokens(requests[other["requestId"]]["sourceText"]))
    responses.append({"requestId": other["requestId"], "translatedText": text, "translatorNotes": ""})
    path = tmp_path / "pair.jsonl"
    write_jsonl(path, responses)
    imported = tmp_path / "pair-import"
    portable.import_responses(package, path, imported)
    one = tmp_path / "review-one"
    two = tmp_path / "review-two"
    assert portable.build_review(package, imported / "imported-results.jsonl", one)["reviewablePairs"] == 1
    assert portable.build_review(package, imported / "imported-results.jsonl", two)["reviewablePairs"] == 1
    for name in ("blind-review.jsonl", "blind-review.csv", "blind-review-key.json"):
        assert (one / name).read_bytes() == (two / name).read_bytes()
