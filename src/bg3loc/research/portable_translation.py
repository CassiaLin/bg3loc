"""Provider-neutral portable translation exchange for B1-02 Phase 2A.

This research-only module exports the frozen Phase 2 pilot, validates returned
translations, restores hidden experiment identity, and builds blind review
artifacts.  It never calls a translation provider or writes production state.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable

from bg3loc.protected_syntax import extract_protected_tokens, validate_protected_syntax
from bg3loc.research.context_experiment import blind_candidate_order, canonical, digest
from bg3loc.research.context_pilot import read_jsonl, validate_pair, write_json, write_jsonl


REQUEST_SCHEMA_VERSION = "portable-translation-request/1"
RESPONSE_SCHEMA_VERSION = "portable-translation-response/1"
MANIFEST_SCHEMA_VERSION = "portable-package-manifest/1"
PACKAGE_SALT = "b1-02-phase2a-portable-v1"
CANONICAL_PILOT_FINGERPRINT = "a9ad899d2bd2d64b4bf971af2b354aeec4e8012a97ef45bb17cb5ca2e9d783b1"
CANONICAL_SAMPLE_COUNTS = {"skill_spell": 40, "item": 40, "quest": 20}
ORDERING_POLICY = "sort SHA256(sampleId + variant + packageSalt); assign sequential requestId"
CREATED_WITH_VERSION = "bg3loc-1.3.0"
PUBLIC_FIELDS = (
    "requestId", "sourceLocale", "targetLocale", "category", "fieldRole",
    "instructions", "sourceText", "context", "promptText",
)
RESPONSE_FIELDS = ("requestId", "translatedText", "translatorNotes")
BLIND_FIELDS = (
    "sampleId", "category", "fieldRole", "sourceText", "candidate1", "candidate2",
    "meaningAccuracy1", "meaningAccuracy2", "naturalness1", "naturalness2",
    "terminologyConsistency1", "terminologyConsistency2", "entityConsistency1",
    "entityConsistency2", "preferredCandidate", "bothBad",
    "contaminationSuspected", "notes",
)


class PortableResponseError(ValueError):
    """A response file cannot be safely associated with this package."""

    def __init__(self, message: str, report: dict[str, Any]):
        super().__init__(message)
        self.report = report


def _write_csv(path: Path, fieldnames: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(fieldnames), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _context_text(context: list[dict[str, str]]) -> str:
    return "\n".join(f"[{field['fieldRole']}] {field['sourceText']}" for field in context)


def _prompt_text(messages: list[dict[str, str]]) -> str:
    """Preserve renderer semantics while removing experiment-internal identity."""
    payload = json.loads(messages[1]["content"])
    payload.pop("ContentUid", None)
    payload.pop("contextGroupKeys", None)
    return messages[0]["content"] + "\n\n" + canonical(payload)


def _load_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("manifest must be an object")
    return value


def _validated_sample(sample_path: Path, pilot_manifest_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sample = read_jsonl(sample_path)
    manifest = _load_manifest(pilot_manifest_path)
    if not sample:
        raise ValueError("pilot sample is empty")
    if digest([row["contextPack"] for row in sample]) != manifest.get("pilotSampleFingerprint"):
        raise ValueError("frozen pilot sample fingerprint mismatch")
    if manifest.get("plannedCalls") != len(sample) * 2:
        raise ValueError("pilot planned call count mismatch")
    seen = set()
    for row in sample:
        validate_pair(row)
        sample_id = row.get("sampleId")
        if sample_id != digest(row["contextPack"]["target"]):
            raise ValueError("sample ID differs from frozen target")
        if sample_id in seen:
            raise ValueError("duplicate sample ID")
        seen.add(sample_id)
    return sample, manifest


def _build_entries(sample: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = []
    for row in sample:
        target = row["contextPack"]["target"]
        for variant, prefix in (("A", "baseline"), ("B", "context")):
            messages = row[prefix + "Prompt"]
            instructions = messages[0]["content"]
            context = [] if variant == "A" else [
                {"fieldRole": field["fieldRole"], "sourceText": field["sourceText"]}
                for field in row["contextPack"]["relatedFields"]
            ]
            prompt_fingerprint = row[prefix + "PromptHash"]
            if prompt_fingerprint != digest(messages):
                raise ValueError("frozen prompt fingerprint mismatch")
            entries.append({
                "sampleId": row["sampleId"],
                "variant": variant,
                "contentUid": target["contentUid"],
                "promptFingerprint": prompt_fingerprint,
                "sortKey": sha256((row["sampleId"] + variant + PACKAGE_SALT).encode("utf-8")).hexdigest(),
                "public": {
                    "sourceLocale": "English",
                    "targetLocale": "ChineseTraditional",
                    "category": target["category"],
                    "fieldRole": target["fieldRole"],
                    "instructions": instructions,
                    "sourceText": target["sourceText"],
                    "context": context,
                    "promptText": _prompt_text(messages),
                },
            })
    entries.sort(key=lambda entry: (entry["sortKey"], entry["sampleId"], entry["variant"]))
    return entries


def _package_readme() -> str:
    return """# B1-02 Portable Translation Package

This package contains anonymous, provider-neutral translation requests.

1. Do not change `requestId`.
2. Translate only the target `sourceText`.
3. `context` is provided only to help understanding.
4. Do not translate, return, or add information found only in context.
5. Put only the translation in `translatedText`.
6. Return either CSV or JSONL. `translatorNotes` is optional.

## Human translation team (CSV)

Fill `translatedText`, optionally fill `translatorNotes`, and do not edit `requestId`.

## External LLM

Send `promptText` to the model. Store only the returned translation in
`translatedText`; do not store model explanations.
"""


def export_package(sample_path: Path, pilot_manifest_path: Path, output: Path,
                   require_canonical_pilot: bool = False) -> dict[str, Any]:
    """Export one deterministic portable package from the frozen pilot sample."""
    sample, pilot_manifest = _validated_sample(sample_path, pilot_manifest_path)
    if require_canonical_pilot:
        counts = Counter(row["contextPack"]["target"]["category"] for row in sample)
        if pilot_manifest["pilotSampleFingerprint"] != CANONICAL_PILOT_FINGERPRINT:
            raise ValueError("pilot fingerprint is not the frozen B1-02 Phase 2 sample")
        if dict(counts) != CANONICAL_SAMPLE_COUNTS:
            raise ValueError("pilot category counts must be skill_spell=40, item=40, quest=20")
    entries = _build_entries(sample)
    requests = []
    internal = []
    for index, entry in enumerate(entries, 1):
        request_id = f"req-{index:06d}"
        public = {"requestId": request_id, **entry["public"]}
        requests.append(public)
        internal.append({
            "requestId": request_id,
            "sampleId": entry["sampleId"],
            "variant": entry["variant"],
            "ContentUid": entry["contentUid"],
            "promptFingerprint": entry["promptFingerprint"],
        })

    category_counts = dict(Counter(row["contextPack"]["target"]["category"] for row in sample))
    package_fingerprint = digest(requests)
    manifest = {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "experiment": "B1-02 Same-Entity Context Experiment Phase 2A",
        "sourceLocale": "English",
        "targetLocale": "ChineseTraditional",
        "requestCount": len(requests),
        "sampleCount": len(sample),
        "categoryCounts": {category: category_counts.get(category, 0) for category in ("skill_spell", "item", "quest")},
        "pilotSampleFingerprint": pilot_manifest["pilotSampleFingerprint"],
        "requestPackageFingerprint": package_fingerprint,
        "orderingPolicy": {"description": ORDERING_POLICY, "packageSalt": PACKAGE_SALT},
        "createdWithVersion": CREATED_WITH_VERSION,
        "requestIds": [row["requestId"] for row in requests],
    }

    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "translation-requests.jsonl", requests)
    _write_csv(output / "translation-requests.csv",
               ("requestId", "category", "fieldRole", "sourceText", "contextText", "promptText", "translatedText", "translatorNotes"),
               ({"requestId": row["requestId"], "category": row["category"], "fieldRole": row["fieldRole"],
                 "sourceText": row["sourceText"], "contextText": _context_text(row["context"]),
                 "promptText": row["promptText"], "translatedText": "", "translatorNotes": ""}
                for row in requests))
    response_rows = [{"requestId": row["requestId"], "translatedText": "", "translatorNotes": ""} for row in requests]
    write_jsonl(output / "response-template.jsonl", response_rows)
    write_json(output / "package-manifest.json", manifest)
    write_json(output / "internal-request-map.json", internal)
    (output / "README.md").write_text(_package_readme(), encoding="utf-8")
    write_json(output / "package-audit.json", audit_package(output))
    return manifest


def _load_package(package: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    manifest = _load_manifest(package / "package-manifest.json")
    public_rows = read_jsonl(package / "translation-requests.jsonl")
    internal_rows = json.loads((package / "internal-request-map.json").read_text(encoding="utf-8-sig"))
    expected = manifest.get("requestIds", [])
    if manifest.get("requestPackageFingerprint") != digest(public_rows):
        raise ValueError("portable request package fingerprint mismatch")
    if expected != [row["requestId"] for row in public_rows]:
        raise ValueError("manifest request IDs differ from canonical requests")
    if len(internal_rows) != len(expected) or {row["requestId"] for row in internal_rows} != set(expected):
        raise ValueError("internal request map differs from manifest")
    return manifest, public_rows, internal_rows


def audit_package(package: Path) -> dict[str, Any]:
    """Produce the required static anonymity and pair-completeness audit."""
    manifest, public_rows, internal_rows = _load_package(package)
    variants: dict[str, set[str]] = defaultdict(set)
    for row in internal_rows:
        variants[row["sampleId"]].add(row["variant"])
    public = [canonical(row) for row in public_rows]
    return {
        "requestCount": len(public_rows),
        "uniqueRequestIds": len({row["requestId"] for row in public_rows}),
        "samplePairs": sum(len(value) == 2 for value in variants.values()),
        "completePairMappings": sum(value == {"A", "B"} for value in variants.values()),
        "contentUidExposedExternally": sum('"ContentUid"' in row or '"contentUid"' in row for row in public),
        "variantLabelsExposedExternally": sum('"variant"' in row for row in public),
        "sampleIdExposedExternally": sum('"sampleId"' in row for row in public),
        "requestPackageFingerprint": manifest["requestPackageFingerprint"],
    }


def _read_responses(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        rows = read_jsonl(path)
    elif suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    else:
        raise ValueError("response file must be JSONL or CSV")
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("response row must be an object")
        normalized.append({
            "requestId": str(row.get("requestId", "")).strip(),
            "translatedText": row.get("translatedText", "") if isinstance(row.get("translatedText", ""), str) else "",
            "translatorNotes": row.get("translatorNotes", "") if isinstance(row.get("translatorNotes", ""), str) else "",
        })
    return normalized


def import_responses(package: Path, responses_path: Path, output: Path) -> dict[str, Any]:
    """Validate portable responses and restore hidden sample/variant identity."""
    manifest, public_rows, internal_rows = _load_package(package)
    expected = manifest["requestIds"]

    responses = _read_responses(responses_path)
    counts = Counter(row["requestId"] for row in responses)
    duplicates = sorted(request_id for request_id, count in counts.items() if count > 1)
    unknown = sorted(set(counts) - set(expected))
    report = {
        "schemaVersion": "portable-import-report/1",
        "requestCount": len(expected),
        "received": len(set(counts) & set(expected)),
        "missing": len(set(expected) - set(counts)),
        "duplicate": len(duplicates),
        "unknown": len(unknown),
        "invalid": 0,
        "valid": 0,
        "complete": False,
        "duplicateRequestIds": duplicates,
        "unknownRequestIds": unknown,
        "missingRequestIds": sorted(set(expected) - set(counts)),
    }
    output.mkdir(parents=True, exist_ok=True)
    if duplicates or unknown:
        write_json(output / "import-report.json", report)
        raise PortableResponseError("duplicate or unknown request ID", report)

    response_by_id = {row["requestId"]: row for row in responses}
    public_by_id = {row["requestId"]: row for row in public_rows}
    internal_by_id = {row["requestId"]: row for row in internal_rows}
    imported = []
    for request_id in expected:
        response = response_by_id.get(request_id)
        mapping = internal_by_id[request_id]
        error_codes = []
        if response is None:
            status = "missing"
            translated = notes = ""
        else:
            translated = response["translatedText"]
            notes = response["translatorNotes"]
            if not translated.strip():
                error_codes.append("EMPTY_TRANSLATION")
            for issue in validate_protected_syntax(
                    extract_protected_tokens(public_by_id[request_id]["sourceText"]), translated):
                error_codes.append({
                    "missing": "PROTECTED_TOKEN_MISSING",
                    "added": "PROTECTED_TOKEN_ADDED",
                    "markup": "PROTECTED_MARKUP_INVALID",
                }[issue.kind])
            status = "invalid" if error_codes else "valid"
        imported.append({
            "requestId": request_id,
            "sampleId": mapping["sampleId"],
            "variant": mapping["variant"],
            "ContentUid": mapping["ContentUid"],
            "status": status,
            "errorCodes": sorted(set(error_codes)),
            "translatedText": translated,
            "translatorNotes": notes,
        })
    report["valid"] = sum(row["status"] == "valid" for row in imported)
    report["invalid"] = sum(row["status"] == "invalid" for row in imported)
    report["complete"] = report["received"] == report["requestCount"] and report["invalid"] == 0
    write_jsonl(output / "imported-results.jsonl", imported)
    write_json(output / "import-report.json", report)
    return report


def build_blind_review(package: Path, imported_results: Path, output: Path) -> dict[str, Any]:
    """Build deterministic blind pairs only where both hidden variants are valid."""
    _, public_rows, internal_rows = _load_package(package)
    public = {row["requestId"]: row for row in public_rows}
    internal = {row["requestId"]: row for row in internal_rows}
    results = read_jsonl(imported_results)
    if len({row.get("requestId") for row in results}) != len(results):
        raise ValueError("imported results contain duplicate request IDs")
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in results:
        request_id = row.get("requestId")
        if request_id not in internal:
            raise ValueError("imported results contain unknown request ID")
        mapping = internal[request_id]
        if any(row.get(key) != mapping[key] for key in ("sampleId", "variant", "ContentUid")):
            raise ValueError("imported result identity differs from internal map")
        grouped[row["sampleId"]][row["variant"]] = row
    blind_rows = []
    hidden_key = []
    diagnostics = []
    for sample_id in sorted(grouped):
        pair = grouped[sample_id]
        if set(pair) != {"A", "B"} or any(pair[v]["status"] != "valid" for v in ("A", "B")):
            continue
        order = blind_candidate_order(sample_id, "A", "B")
        first, second = pair[order[0]], pair[order[1]]
        target = public[first["requestId"]]
        blind_rows.append({
            "sampleId": sample_id,
            "category": target["category"],
            "fieldRole": target["fieldRole"],
            "sourceText": target["sourceText"],
            "candidate1": first["translatedText"],
            "candidate2": second["translatedText"],
            "meaningAccuracy1": "", "meaningAccuracy2": "",
            "naturalness1": "", "naturalness2": "",
            "terminologyConsistency1": "", "terminologyConsistency2": "",
            "entityConsistency1": "", "entityConsistency2": "",
            "preferredCandidate": "", "bothBad": "",
            "contaminationSuspected": "", "notes": "",
        })
        hidden_key.append({
            "sampleId": sample_id,
            "candidate1Variant": order[0],
            "candidate2Variant": order[1],
            "candidate1RequestId": first["requestId"],
            "candidate2RequestId": second["requestId"],
        })
        context_request = pair["B"]["requestId"]
        diagnostics.append({"sampleId": sample_id, "context": public[context_request]["context"]})
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "blind-review.jsonl", blind_rows)
    _write_csv(output / "blind-review.csv", BLIND_FIELDS, blind_rows)
    write_json(output / "blind-review-key.json", hidden_key)
    write_jsonl(output / "diagnostics-context.jsonl", diagnostics)
    return {"reviewablePairs": len(blind_rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--pilot-sample", type=Path, default=Path("workspace/b1-02/phase2/pilot-sample.jsonl"))
    export.add_argument("--pilot-manifest", type=Path, default=Path("workspace/b1-02/phase2/b1-02-phase2-pilot-manifest.json"))
    export.add_argument("--output", type=Path, default=Path("workspace/b1-02/phase2a"))
    imp = commands.add_parser("import")
    imp.add_argument("--package", type=Path, default=Path("workspace/b1-02/phase2a"))
    imp.add_argument("--responses", type=Path, required=True)
    imp.add_argument("--output", type=Path, default=Path("workspace/b1-02/phase2a/import"))
    review = commands.add_parser("build-review")
    review.add_argument("--package", type=Path, default=Path("workspace/b1-02/phase2a"))
    review.add_argument("--imported-results", type=Path, default=Path("workspace/b1-02/phase2a/import/imported-results.jsonl"))
    review.add_argument("--output", type=Path, default=Path("workspace/b1-02/phase2a/review"))
    args = parser.parse_args()
    if args.command == "export":
        result = export_package(args.pilot_sample, args.pilot_manifest, args.output, require_canonical_pilot=True)
        print(canonical({key: result[key] for key in ("sampleCount", "requestCount", "requestPackageFingerprint")}))
    elif args.command == "import":
        try:
            print(canonical(import_responses(args.package, args.responses, args.output)))
        except PortableResponseError as exc:
            parser.error(str(exc))
    else:
        print(canonical(build_blind_review(args.package, args.imported_results, args.output)))


if __name__ == "__main__":
    main()
