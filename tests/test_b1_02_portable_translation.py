from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from jsonschema import validate

from bg3loc.protected_syntax import extract_protected_tokens
from bg3loc.research.context_experiment import build_packs, digest, read_rows, render_pair
from bg3loc.research.context_pilot import write_json, write_jsonl
from bg3loc.research.portable_translation import (
    PortableResponseError,
    audit_package,
    build_blind_review,
    export_package,
    import_responses,
)
from bg3loc.ruleset_io import load_ruleset


ROOT = Path(__file__).parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "b1_02"


def _frozen_pilot(tmp_path: Path) -> tuple[Path, Path]:
    packs, _ = build_packs(read_rows(FIXTURE / "portable_source_rows.jsonl"))
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
        "plannedCalls": len(sample) * 2,
    })
    return sample_path, manifest_path


def _package(tmp_path: Path, name: str = "package") -> Path:
    sample, manifest = _frozen_pilot(tmp_path)
    output = tmp_path / name
    export_package(sample, manifest, output)
    return output


def _valid_responses(package: Path) -> list[dict[str, str]]:
    rows = [json.loads(line) for line in (package / "translation-requests.jsonl").read_text().splitlines()]
    result = []
    for row in rows:
        tokens = " ".join(extract_protected_tokens(row["sourceText"]))
        result.append({
            "requestId": row["requestId"],
            "translatedText": ("虛構譯文 " + tokens).strip(),
            "translatorNotes": "",
        })
    return result


def _write_responses(path: Path, rows: list[dict[str, str]]) -> None:
    write_jsonl(path, rows)


def test_export_is_deterministic_anonymous_and_schema_valid(tmp_path):
    sample, pilot_manifest = _frozen_pilot(tmp_path)
    first, second = tmp_path / "a", tmp_path / "b"
    manifest_a = export_package(sample, pilot_manifest, first)
    manifest_b = export_package(sample, pilot_manifest, second)
    assert manifest_a == manifest_b
    assert manifest_a["sampleCount"] == 6 and manifest_a["requestCount"] == 12
    assert manifest_a["categoryCounts"] == {"skill_spell": 2, "item": 2, "quest": 2}
    for name in ("translation-requests.jsonl", "translation-requests.csv", "response-template.jsonl"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    assert (first / "translation-requests.csv").read_bytes().startswith(b"\xef\xbb\xbf")

    request_schema = json.loads((ROOT / "schemas/research/portable-translation-request-v1.schema.json").read_text())
    response_schema = json.loads((ROOT / "schemas/research/portable-translation-response-v1.schema.json").read_text())
    manifest_schema = json.loads((ROOT / "schemas/research/portable-package-manifest-v1.schema.json").read_text())
    validate(manifest_a, manifest_schema)
    public = [json.loads(line) for line in (first / "translation-requests.jsonl").read_text().splitlines()]
    assert len({row["requestId"] for row in public}) == 12
    for row in public:
        validate(row, request_schema)
        serialized = json.dumps(row)
        assert "sampleId" not in serialized and "ContentUid" not in serialized
        assert '"variant"' not in serialized and '"baseline"' not in serialized
    internal = json.loads((first / "internal-request-map.json").read_text())
    assert {(row["sampleId"], row["variant"]) for row in internal} == {
        (row["sampleId"], variant)
        for row in [json.loads(line) for line in sample.read_text().splitlines()]
        for variant in ("A", "B")
    }
    assert sum(not row["context"] for row in public) == 6
    assert sum(bool(row["context"]) for row in public) == 6
    audit = audit_package(first)
    assert audit["requestCount"] == audit["uniqueRequestIds"] == 12
    assert audit["samplePairs"] == audit["completePairMappings"] == 6
    assert audit["contentUidExposedExternally"] == 0
    assert audit["variantLabelsExposedExternally"] == 0
    assert audit["sampleIdExposedExternally"] == 0
    assert json.loads((first / "package-audit.json").read_text()) == audit
    templates = [json.loads(line) for line in (first / "response-template.jsonl").read_text().splitlines()]
    assert len(templates) == 12
    for row in templates:
        validate(row, response_schema)


def test_import_complete_jsonl_and_csv(tmp_path):
    package = _package(tmp_path)
    rows = _valid_responses(package)
    jsonl = tmp_path / "responses.jsonl"
    _write_responses(jsonl, rows)
    report = import_responses(package, jsonl, tmp_path / "json-import")
    assert report["complete"] is True and report["valid"] == 12

    csv_path = tmp_path / "responses.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("requestId", "translatedText", "translatorNotes"))
        writer.writeheader()
        writer.writerows(rows)
    csv_report = import_responses(package, csv_path, tmp_path / "csv-import")
    assert csv_report == report


def test_import_partial_empty_and_protected_corruption(tmp_path):
    package = _package(tmp_path)
    rows = _valid_responses(package)
    public = [json.loads(line) for line in (package / "translation-requests.jsonl").read_text().splitlines()]
    protected_id = next(row["requestId"] for row in public if "{Damage}" in row["sourceText"])
    by_id = {row["requestId"]: row for row in rows}
    by_id[protected_id]["translatedText"] = "遺失保護 token"
    another_id = next(request_id for request_id in by_id if request_id != protected_id)
    by_id[another_id]["translatedText"] = ""
    partial = [by_id[protected_id], by_id[another_id]]
    path = tmp_path / "partial.jsonl"
    _write_responses(path, partial)
    report = import_responses(package, path, tmp_path / "partial-import")
    assert report["complete"] is False
    assert report["received"] == 2 and report["missing"] == 10 and report["invalid"] == 2
    imported = [json.loads(line) for line in (tmp_path / "partial-import/imported-results.jsonl").read_text().splitlines()]
    assert next(row for row in imported if row["requestId"] == protected_id)["errorCodes"] == ["PROTECTED_TOKEN_MISSING"]
    assert next(row for row in imported if row["requestId"] == another_id)["errorCodes"] == ["EMPTY_TRANSLATION"]
    assert sum(row["status"] == "missing" for row in imported) == 10


@pytest.mark.parametrize("kind", ("duplicate", "unknown"))
def test_import_rejects_duplicate_and_unknown_ids(tmp_path, kind):
    package = _package(tmp_path)
    rows = _valid_responses(package)
    if kind == "duplicate":
        rows.append(dict(rows[0]))
    else:
        rows.append({"requestId": "req-999999", "translatedText": "虛構", "translatorNotes": ""})
    path = tmp_path / f"{kind}.jsonl"
    _write_responses(path, rows)
    with pytest.raises(PortableResponseError):
        import_responses(package, path, tmp_path / f"{kind}-import")
    report = json.loads((tmp_path / f"{kind}-import/import-report.json").read_text())
    assert report[kind] == 1


def test_blind_review_pairs_only_valid_ab_and_keeps_key_separate(tmp_path):
    package = _package(tmp_path)
    responses = tmp_path / "responses.jsonl"
    _write_responses(responses, _valid_responses(package))
    import_dir = tmp_path / "import"
    import_responses(package, responses, import_dir)
    imported_path = import_dir / "imported-results.jsonl"
    imported = [json.loads(line) for line in imported_path.read_text().splitlines()]
    excluded_sample = imported[0]["sampleId"]
    imported[0]["status"] = "invalid"
    imported[0]["errorCodes"] = ["SYNTHETIC_INVALID"]
    write_jsonl(imported_path, imported)

    review_dir = tmp_path / "review"
    summary = build_blind_review(package, imported_path, review_dir)
    assert summary["reviewablePairs"] == 5
    blind = [json.loads(line) for line in (review_dir / "blind-review.jsonl").read_text().splitlines()]
    assert excluded_sample not in {row["sampleId"] for row in blind}
    for row in blind:
        assert not ({"variant", "requestId", "context"} & row.keys())
        assert row["candidate1"] and row["candidate2"]
    key = json.loads((review_dir / "blind-review-key.json").read_text())
    assert len(key) == 5 and all(set((row["candidate1Variant"], row["candidate2Variant"])) == {"A", "B"} for row in key)
    diagnostics = [json.loads(line) for line in (review_dir / "diagnostics-context.jsonl").read_text().splitlines()]
    assert len(diagnostics) == 5 and all(row["context"] for row in diagnostics)


def test_blank_template_has_zero_reviewable_pairs(tmp_path):
    package = _package(tmp_path)
    import_dir = tmp_path / "blank-import"
    report = import_responses(package, package / "response-template.jsonl", import_dir)
    assert report["invalid"] == 12 and report["valid"] == 0
    summary = build_blind_review(package, import_dir / "imported-results.jsonl", tmp_path / "blank-review")
    assert summary["reviewablePairs"] == 0
