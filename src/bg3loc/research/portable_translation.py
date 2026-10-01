"""Provider-neutral portable translation exchange for B1-02 Phase 2A."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path

from bg3loc.protected_syntax import extract_protected_tokens, validate_protected_syntax
from bg3loc.research.context_experiment import SAFETY, canonical, digest
from bg3loc.research.context_pilot import read_jsonl, validate_pair, write_json, write_jsonl

SCHEMA_VERSION = "b1-02-portable-package/1"
REQUEST_SCHEMA = "b1-02-portable-request/1"
RESPONSE_SCHEMA = "b1-02-portable-response/1"
PACKAGE_SALT = "b1-02-phase2a-portable-order-v1"
ORDERING_POLICY = "SHA256(sampleId + ':' + variant + ':' + packageSalt), ascending; sequential anonymous requestId"
CREATED_WITH_VERSION = "b1-02-phase2a/1"
EXPECTED_PILOT_FINGERPRINT = "a9ad899d2bd2d64b4bf971af2b354aeec4e8012a97ef45bb17cb5ca2e9d783b1"
REQUEST_FIELDS = ("requestId", "sourceLocale", "targetLocale", "category", "fieldRole", "instructions", "sourceText", "context", "promptText")
FORBIDDEN_PUBLIC_KEYS = {"sampleId", "variant", "contentUid", "ContentUid", "promptFingerprint", "baselinePrompt", "contextPrompt"}


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _csv_write(path: Path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _instructions(messages):
    return messages[0]["content"]


def _prompt_text(instructions, source_locale, target_locale, category, field_role, source_text, context):
    lines = [instructions, "", f"Source locale: {source_locale}", f"Target locale: {target_locale}",
             f"Category: {category}", f"Field role: {field_role}", "", "Target source text:", source_text]
    if context:
        lines.extend(["", "Related source fields (context only):"])
        lines.extend(f"[{field['fieldRole']}] {field['sourceText']}" for field in context)
    lines.extend(["", "Return only the translation of the target source text."])
    return "\n".join(lines)


def _validate_pilot(sample, pilot_manifest):
    if pilot_manifest.get("pilotSampleFingerprint") != EXPECTED_PILOT_FINGERPRINT:
        raise ValueError("unexpected pilot sample fingerprint")
    if digest([row["contextPack"] for row in sample]) != EXPECTED_PILOT_FINGERPRINT:
        raise ValueError("pilot sample content does not match frozen fingerprint")
    if len(sample) != 100:
        raise ValueError("portable package requires the frozen 100-row pilot")
    if Counter(row["contextPack"]["target"]["category"] for row in sample) != {"skill_spell": 40, "item": 40, "quest": 20}:
        raise ValueError("pilot category counts differ from frozen policy")
    for row in sample:
        validate_pair(row)
        if row["sampleId"] != digest(row["contextPack"]["target"]):
            raise ValueError("pilot sample ID mismatch")


def _portable_rows(sample):
    arms = []
    for row in sample:
        target = row["contextPack"]["target"]
        for variant, prompt_key in (("A", "baseline"), ("B", "context")):
            messages = row[prompt_key + "Prompt"]
            context = [] if variant == "A" else [
                {"fieldRole": field["fieldRole"], "sourceText": field["sourceText"]}
                for field in row["contextPack"]["relatedFields"]
            ]
            instructions = _instructions(messages)
            arms.append({"sampleId": row["sampleId"], "variant": variant,
                         "contentUid": target["contentUid"], "promptFingerprint": row[prompt_key + "PromptHash"],
                         "sortKey": sha256(f"{row['sampleId']}:{variant}:{PACKAGE_SALT}".encode()).hexdigest(),
                         "public": {"sourceLocale": "English", "targetLocale": "ChineseTraditional",
                                    "category": target["category"], "fieldRole": target["fieldRole"],
                                    "instructions": instructions, "sourceText": target["sourceText"], "context": context,
                                    "promptText": _prompt_text(instructions, "English", "ChineseTraditional",
                                                               target["category"], target["fieldRole"], target["sourceText"], context)}})
    arms.sort(key=lambda arm: (arm["sortKey"], arm["sampleId"], arm["variant"]))
    requests, internal = [], []
    for index, arm in enumerate(arms, 1):
        request_id = f"req-{index:06d}"
        public = {"requestId": request_id, **arm["public"]}
        if FORBIDDEN_PUBLIC_KEYS & public.keys():
            raise ValueError("public request contains internal identity")
        requests.append(public)
        internal.append({"requestId": request_id, "sampleId": arm["sampleId"], "variant": arm["variant"],
                         "contentUid": arm["contentUid"], "promptFingerprint": arm["promptFingerprint"]})
    return requests, internal


def _package_readme():
    return """# B1-02 portable translation package

This package contains anonymous translation requests. Each request is independent.

1. Do not edit `requestId`.
2. Translate only `sourceText`.
3. `context` is provided only to help you understand the target.
4. Do not translate context fields or add facts that appear only in context.
5. Put only the translation in `translatedText`.
6. Return either JSONL or CSV. `translatorNotes` is optional.

## Human translation team using CSV

Fill `translatedText`, optionally fill `translatorNotes`, and do not edit `requestId`. Keep the file in UTF-8 format.

## External language model

Send `promptText` as a standalone prompt. Store only the returned translation in `translatedText`; do not store model explanations.

The files do not identify experiment arms. Do not try to pair or reorder requests. Return partial work if needed; the importer will report missing rows.
"""


def export_package(pilot_sample: Path, pilot_manifest_path: Path, output: Path):
    sample = read_jsonl(pilot_sample)
    pilot_manifest = _read_json(pilot_manifest_path)
    _validate_pilot(sample, pilot_manifest)
    requests, internal = _portable_rows(sample)
    request_fingerprint = digest(requests)
    manifest = {"schemaVersion": SCHEMA_VERSION, "experiment": "B1-02 Same-Entity Context Experiment Phase 2A",
                "sourceLocale": "English", "targetLocale": "ChineseTraditional", "requestCount": len(requests),
                "sampleCount": len(sample),
                "categoryCounts": dict(sorted(Counter(r["contextPack"]["target"]["category"] for r in sample).items())),
                "requestCategoryCounts": dict(sorted(Counter(r["category"] for r in requests).items())),
                "pilotSampleFingerprint": pilot_manifest["pilotSampleFingerprint"],
                "requestPackageFingerprint": request_fingerprint, "orderingPolicy": ORDERING_POLICY,
                "packageSalt": PACKAGE_SALT, "createdWithVersion": CREATED_WITH_VERSION,
                "requestIdsFingerprint": digest([r["requestId"] for r in requests])}
    write_jsonl(output / "translation-requests.jsonl", requests)
    _csv_write(output / "translation-requests.csv",
               ("requestId", "category", "fieldRole", "sourceText", "contextText", "promptText", "translatedText", "translatorNotes"),
               ({"requestId": row["requestId"], "category": row["category"], "fieldRole": row["fieldRole"],
                 "sourceText": row["sourceText"], "contextText": "\n".join(f"[{f['fieldRole']}] {f['sourceText']}" for f in row["context"]),
                 "promptText": row["promptText"], "translatedText": "", "translatorNotes": ""} for row in requests))
    write_jsonl(output / "response-template.jsonl",
                ({"requestId": row["requestId"], "translatedText": "", "translatorNotes": ""} for row in requests))
    write_json(output / "package-manifest.json", manifest)
    write_json(output / "internal-request-map.json", {"schemaVersion": "b1-02-internal-request-map/1",
                                                       "requestPackageFingerprint": request_fingerprint, "requests": internal})
    (output / "README.md").write_text(_package_readme(), encoding="utf-8")
    audit = audit_package(output)
    write_json(output / "package-audit.json", audit)
    return manifest


def _load_requests(package: Path):
    manifest = _read_json(package / "package-manifest.json")
    requests = read_jsonl(package / "translation-requests.jsonl")
    internal_doc = _read_json(package / "internal-request-map.json")
    if digest(requests) != manifest.get("requestPackageFingerprint"):
        raise ValueError("request package fingerprint mismatch")
    if internal_doc.get("requestPackageFingerprint") != manifest.get("requestPackageFingerprint"):
        raise ValueError("internal map belongs to a different package")
    if len(requests) != manifest.get("requestCount") or len(internal_doc.get("requests", [])) != len(requests):
        raise ValueError("package request count mismatch")
    public = {row["requestId"]: row for row in requests}
    internal = {row["requestId"]: row for row in internal_doc["requests"]}
    if len(public) != len(requests) or len(internal) != len(requests) or set(public) != set(internal):
        raise ValueError("package IDs are duplicate or inconsistent")
    return manifest, requests, public, internal


def audit_package(package: Path):
    manifest, requests, public, internal = _load_requests(package)
    pairs = Counter(row["sampleId"] for row in internal.values())
    public_text = "\n".join(canonical(row) for row in requests)
    return {"requestCount": len(requests), "uniqueRequestIds": len(public), "samplePairs": sum(v == 2 for v in pairs.values()),
            "completePairMappings": sum({r["variant"] for r in internal.values() if r["sampleId"] == sid} == {"A", "B"} for sid in pairs),
            "contentUidExposedExternally": sum('"contentUid"' in canonical(row) or '"ContentUid"' in canonical(row) for row in requests),
            "variantLabelsExposedExternally": sum('"variant"' in canonical(row) or '"baseline"' in canonical(row) for row in requests),
            "sampleIdExposedExternally": sum('"sampleId"' in canonical(row) for row in requests),
            "requestPackageFingerprint": manifest["requestPackageFingerprint"],
            "publicContainsInternalIdentity": any(token in public_text for token in ('"sampleId"', '"contentUid"', '"variant"'))}


def _load_responses(path: Path):
    suffix = path.suffix.casefold()
    if suffix == ".jsonl":
        return read_jsonl(path)
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))
    raise ValueError("responses must be JSONL or CSV")


def import_responses(package: Path, responses_path: Path, output: Path):
    manifest, requests, public, internal = _load_requests(package)
    responses = _load_responses(responses_path)
    seen, duplicate = {}, set()
    for row in responses:
        request_id = str(row.get("requestId", "")).strip()
        if request_id in seen:
            duplicate.add(request_id)
        seen[request_id] = row
    if duplicate:
        raise ValueError("duplicate request IDs: " + ", ".join(sorted(duplicate)))
    unknown = sorted(set(seen) - set(public))
    if unknown:
        raise ValueError("unknown request IDs: " + ", ".join(unknown))
    imported = []
    counts = Counter()
    for request in requests:
        request_id = request["requestId"]
        mapping = internal[request_id]
        raw = seen.get(request_id)
        errors = []
        if raw is None:
            status, translated, notes = "missing", "", ""
        else:
            translated = str(raw.get("translatedText", ""))
            notes = str(raw.get("translatorNotes", ""))
            if not translated.strip():
                errors.append("EMPTY_TRANSLATION")
            for issue in validate_protected_syntax(extract_protected_tokens(request["sourceText"]), translated):
                errors.append("PROTECTED_SYNTAX_" + issue.kind.upper())
            status = "valid" if not errors else "invalid"
        counts[status] += 1
        imported.append({"requestId": request_id, "sampleId": mapping["sampleId"], "variant": mapping["variant"],
                         "contentUid": mapping["contentUid"], "promptFingerprint": mapping["promptFingerprint"],
                         "category": request["category"], "fieldRole": request["fieldRole"], "sourceText": request["sourceText"],
                         "translatedText": translated, "translatorNotes": notes, "status": status, "errorCodes": sorted(set(errors))})
    summary = {"schemaVersion": "b1-02-portable-import/1", "requestPackageFingerprint": manifest["requestPackageFingerprint"],
               "expected": len(requests), "received": len(seen), "valid": counts["valid"], "invalid": counts["invalid"],
               "missing": counts["missing"], "duplicate": 0, "unknown": 0,
               "packageComplete": len(seen) == len(requests) and counts["valid"] == len(requests)}
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "imported-results.jsonl", imported)
    write_json(output / "import-summary.json", summary)
    return summary


def build_review(package: Path, imported_path: Path, output: Path):
    manifest, requests, public, internal = _load_requests(package)
    imported = read_jsonl(imported_path)
    if len({row["requestId"] for row in imported}) != len(imported):
        raise ValueError("imported results contain duplicate request IDs")
    import_summary_path = imported_path.parent / "import-summary.json"
    if import_summary_path.is_file() and _read_json(import_summary_path).get("requestPackageFingerprint") != manifest["requestPackageFingerprint"]:
        raise ValueError("imported results belong to a different package")
    for row in imported:
        request_id = row.get("requestId")
        if request_id not in internal:
            raise ValueError("imported results contain unknown request ID")
        mapping = internal[request_id]
        if any(row.get(key) != mapping[key] for key in ("sampleId", "variant", "contentUid", "promptFingerprint")):
            raise ValueError("imported result identity differs from internal map")
    results = {row["requestId"]: row for row in imported}
    by_sample = defaultdict(dict)
    for request_id, mapping in internal.items():
        row = results.get(request_id)
        if row and row.get("status") == "valid":
            by_sample[mapping["sampleId"]][mapping["variant"]] = (request_id, row)
    blind, keys, diagnostics = [], [], []
    for sample_id in sorted(by_sample):
        pair = by_sample[sample_id]
        if set(pair) != {"A", "B"}:
            continue
        variants = ("B", "A") if int(sha256(sample_id.encode()).hexdigest(), 16) & 1 else ("A", "B")
        first_id, first = pair[variants[0]]
        second_id, second = pair[variants[1]]
        blind.append({"sampleId": sample_id, "category": first["category"], "fieldRole": first["fieldRole"],
                      "sourceText": first["sourceText"], "candidate1": first["translatedText"], "candidate2": second["translatedText"]})
        keys.append({"sampleId": sample_id, "candidate1Variant": variants[0], "candidate2Variant": variants[1],
                     "candidate1RequestId": first_id, "candidate2RequestId": second_id})
        context_request_id = pair["B"][0]
        diagnostics.append({"sampleId": sample_id, "context": public[context_request_id]["context"]})
    write_jsonl(output / "blind-review.jsonl", blind)
    _csv_write(output / "blind-review.csv",
               ("sampleId", "category", "fieldRole", "sourceText", "candidate1", "candidate2",
                "meaningAccuracy1", "meaningAccuracy2", "naturalness1", "naturalness2",
                "terminologyConsistency1", "terminologyConsistency2", "entityConsistency1", "entityConsistency2",
                "preferredCandidate", "bothBad", "contaminationSuspected", "notes"),
               ({**row, "meaningAccuracy1": "", "meaningAccuracy2": "", "naturalness1": "", "naturalness2": "",
                 "terminologyConsistency1": "", "terminologyConsistency2": "", "entityConsistency1": "", "entityConsistency2": "",
                 "preferredCandidate": "", "bothBad": "", "contaminationSuspected": "", "notes": ""} for row in blind))
    write_json(output / "blind-review-key.json", {"schemaVersion": "b1-02-portable-review-key/1", "pairs": keys})
    write_jsonl(output / "diagnostics-context.jsonl", diagnostics)
    summary = {"requestPackageFingerprint": manifest["requestPackageFingerprint"], "reviewablePairs": len(blind),
               "candidateOrdering": "SHA256(sampleId) parity", "variantKeySeparate": True}
    write_json(output / "review-summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("--pilot-sample", type=Path, default=Path("workspace/b1-02/phase2/pilot-sample.jsonl"))
    export.add_argument("--pilot-manifest", type=Path, default=Path("workspace/b1-02/phase2/b1-02-phase2-pilot-manifest.json"))
    export.add_argument("--output", type=Path, default=Path("workspace/b1-02/phase2a"))
    imp = sub.add_parser("import")
    imp.add_argument("--package", type=Path, required=True)
    imp.add_argument("--responses", type=Path, required=True)
    imp.add_argument("--output", type=Path, required=True)
    review = sub.add_parser("build-review")
    review.add_argument("--package", type=Path, required=True)
    review.add_argument("--imported-results", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "export":
        result = export_package(args.pilot_sample, args.pilot_manifest, args.output)
    elif args.command == "import":
        result = import_responses(args.package, args.responses, args.output)
    else:
        result = build_review(args.package, args.imported_results, args.output)
    print(canonical(result))


if __name__ == "__main__":
    main()
