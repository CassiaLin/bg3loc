"""B1-02 small, provider-neutral safety validation package.

The module selects a deterministic 10/10/5 subset from the frozen Phase 2
pilot, exports 50 anonymous A/B requests, and aggregates human safety review.
It never calls a provider or changes production state.
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
from bg3loc.research.context_experiment import CATEGORIES, blind_candidate_order, canonical, digest
from bg3loc.research.context_pilot import read_jsonl, write_json, write_jsonl
from bg3loc.research.portable_translation import (
    CANONICAL_PILOT_FINGERPRINT,
    CANONICAL_SAMPLE_COUNTS,
    CREATED_WITH_VERSION,
    _read_responses,
    _prompt_text,
    _validated_sample,
)


SAFETY_COUNTS = {"skill_spell": 10, "item": 10, "quest": 5}
SAFETY_SALT = "b1-02-safety-validation-v1"
SELECTION_POLICY = (
    "within each category, round robin over fieldRole:length(<80,<250,>=250):"
    "relatedCount strata; SHA256 target then ContentUid"
)
ORDERING_POLICY = "sort SHA256(sampleId + variant + safetySalt); assign sequential requestId"
REVIEW_FIELDS = (
    "sampleId", "category", "fieldRole", "sourceText", "candidate1", "candidate2",
    "bWorseThanA", "contextContamination", "reason", "worseCandidate",
    "contaminationCandidate", "bBetterThanA", "failurePattern",
)
FAILURE_PATTERNS = (
    "context contamination", "wrong sense selection", "over-translation",
    "cross-field leakage", "unnatural wording caused by context",
)


def _write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=REVIEW_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _stratum(row: dict[str, Any]) -> tuple[str, str, str, int]:
    target = row["contextPack"]["target"]
    size = len(target["sourceText"])
    length = "short" if size < 80 else "medium" if size < 250 else "long"
    return target["category"], target["fieldRole"], length, len(row["contextPack"]["relatedFields"])


def select_safety_subset(sample: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select the fixed 10/10/5 safety subset without modifying the frozen pilot."""
    buckets: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in sample:
        buckets[_stratum(row)].append(row)
    selected: list[dict[str, Any]] = []
    for category in CATEGORIES:
        keys = sorted(key for key in buckets if key[0] == category)
        for key in keys:
            buckets[key].sort(key=lambda row: (
                digest(row["contextPack"]["target"]),
                row["contextPack"]["target"]["contentUid"],
            ))
        while sum(row["contextPack"]["target"]["category"] == category for row in selected) < SAFETY_COUNTS[category]:
            progressed = False
            for key in keys:
                category_count = sum(row["contextPack"]["target"]["category"] == category for row in selected)
                if category_count >= SAFETY_COUNTS[category]:
                    break
                if buckets[key]:
                    selected.append(buckets[key].pop(0))
                    progressed = True
            if not progressed:
                raise ValueError(f"frozen pilot does not contain {SAFETY_COUNTS[category]} {category} rows")
    return selected


def _entries(sample: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = []
    for row in sample:
        target = row["contextPack"]["target"]
        for variant, prefix in (("A", "baseline"), ("B", "context")):
            messages = row[prefix + "Prompt"]
            context = [] if variant == "A" else [
                {"fieldRole": field["fieldRole"], "sourceText": field["sourceText"]}
                for field in row["contextPack"]["relatedFields"]
            ]
            entries.append({
                "sampleId": row["sampleId"],
                "variant": variant,
                "ContentUid": target["contentUid"],
                "promptFingerprint": row[prefix + "PromptHash"],
                "sortKey": sha256((row["sampleId"] + variant + SAFETY_SALT).encode()).hexdigest(),
                "public": {
                    "sourceLocale": "English",
                    "targetLocale": "ChineseTraditional",
                    "category": target["category"],
                    "fieldRole": target["fieldRole"],
                    "instructions": messages[0]["content"],
                    "sourceText": target["sourceText"],
                    "context": context,
                    "promptText": _prompt_text(messages),
                },
            })
    return sorted(entries, key=lambda row: (row["sortKey"], row["sampleId"], row["variant"]))


def export_safety_package(sample_path: Path, pilot_manifest_path: Path, output: Path,
                          require_canonical_pilot: bool = True) -> dict[str, Any]:
    """Export the safety package from the unchanged frozen Phase 2 pilot."""
    sample, pilot_manifest = _validated_sample(sample_path, pilot_manifest_path)
    counts = Counter(row["contextPack"]["target"]["category"] for row in sample)
    if require_canonical_pilot:
        if pilot_manifest.get("pilotSampleFingerprint") != CANONICAL_PILOT_FINGERPRINT:
            raise ValueError("pilot fingerprint is not the frozen B1-02 Phase 2 sample")
        if dict(counts) != CANONICAL_SAMPLE_COUNTS:
            raise ValueError("pilot category counts must be skill_spell=40, item=40, quest=20")
    subset = select_safety_subset(sample)
    entries = _entries(subset)
    requests, internal = [], []
    for index, entry in enumerate(entries, 1):
        request_id = f"safety-req-{index:06d}"
        requests.append({"requestId": request_id, **entry["public"]})
        internal.append({
            "requestId": request_id,
            "sampleId": entry["sampleId"],
            "variant": entry["variant"],
            "ContentUid": entry["ContentUid"],
            "promptFingerprint": entry["promptFingerprint"],
        })
    request_by_sample: dict[str, dict[str, str]] = defaultdict(dict)
    target_by_sample = {row["sampleId"]: row["contextPack"]["target"] for row in subset}
    for row in internal:
        request_by_sample[row["sampleId"]][row["variant"]] = row["requestId"]
    review_rows, hidden_key = [], []
    for sample_id in sorted(request_by_sample):
        first_variant, second_variant = blind_candidate_order(sample_id, "A", "B")
        target = target_by_sample[sample_id]
        review_rows.append({
            "sampleId": sample_id, "category": target["category"], "fieldRole": target["fieldRole"],
            "sourceText": target["sourceText"], "candidate1": "", "candidate2": "",
            "bWorseThanA": "", "contextContamination": "", "reason": "",
            "worseCandidate": "", "contaminationCandidate": "", "bBetterThanA": "",
            "failurePattern": "",
        })
        hidden_key.append({
            "sampleId": sample_id,
            "candidate1Variant": first_variant,
            "candidate2Variant": second_variant,
            "candidate1RequestId": request_by_sample[sample_id][first_variant],
            "candidate2RequestId": request_by_sample[sample_id][second_variant],
        })
    category_counts = Counter(row["contextPack"]["target"]["category"] for row in subset)
    manifest = {
        "schemaVersion": "b1-02-safety-package/1",
        "experiment": "B1-02 Same-Entity Context Safety Validation",
        "status": "READY",
        "reviewStatus": "PENDING",
        "sourceLocale": "English",
        "targetLocale": "ChineseTraditional",
        "pilotSampleFingerprint": pilot_manifest["pilotSampleFingerprint"],
        "safetySubsetFingerprint": digest([row["contextPack"] for row in subset]),
        "requestPackageFingerprint": digest(requests),
        "sampleCount": len(subset),
        "requestCount": len(requests),
        "categoryCounts": {category: category_counts[category] for category in CATEGORIES},
        "selectionPolicy": SELECTION_POLICY,
        "orderingPolicy": {"description": ORDERING_POLICY, "safetySalt": SAFETY_SALT},
        "acceptancePrinciple": "reliable structural context plus no meaningful systematic degradation",
        "safetyQuestions": [
            "Does B add information absent from the source?",
            "Does context cause B to misinterpret the target sentence?",
            "Is B clearly less natural than A?",
            "Does B break terminology or entity consistency?",
            "Does B translate context into the output?",
        ],
        "trackedFailurePatterns": list(FAILURE_PATTERNS),
        "requestIds": [row["requestId"] for row in requests],
        "createdWithVersion": CREATED_WITH_VERSION,
    }
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "safety-requests.jsonl", requests)
    write_jsonl(output / "safety-response-template.jsonl", (
        {"requestId": row["requestId"], "translatedText": "", "translatorNotes": ""}
        for row in requests
    ))
    _write_csv(output / "safety-review.csv", review_rows)
    write_json(output / "safety-manifest.json", manifest)
    write_json(output / "safety-internal-request-map.json", internal)
    write_json(output / "safety-review-hidden-key.json", hidden_key)
    return manifest


def build_safety_review(package: Path, responses_path: Path) -> dict[str, Any]:
    """Validate a complete provider-neutral response file and populate blind candidates."""
    manifest = json.loads((package / "safety-manifest.json").read_text(encoding="utf-8-sig"))
    requests = read_jsonl(package / "safety-requests.jsonl")
    hidden_key = json.loads((package / "safety-review-hidden-key.json").read_text(encoding="utf-8-sig"))
    responses = _read_responses(responses_path)
    expected = manifest["requestIds"]
    counts = Counter(row["requestId"] for row in responses)
    duplicate = sorted(key for key, count in counts.items() if count > 1)
    unknown = sorted(set(counts) - set(expected))
    missing = sorted(set(expected) - set(counts))
    if duplicate or unknown or missing:
        raise ValueError("responses must contain each safety request ID exactly once")
    request_by_id = {row["requestId"]: row for row in requests}
    response_by_id = {row["requestId"]: row for row in responses}
    invalid = []
    for request_id in expected:
        translated = response_by_id[request_id]["translatedText"]
        if not translated.strip() or validate_protected_syntax(
                extract_protected_tokens(request_by_id[request_id]["sourceText"]), translated):
            invalid.append(request_id)
    if invalid:
        raise ValueError(f"responses contain {len(invalid)} empty or protected-syntax-invalid translations")
    with (package / "safety-review.csv").open("r", encoding="utf-8-sig", newline="") as stream:
        review_by_sample = {row["sampleId"]: row for row in csv.DictReader(stream)}
    for key in hidden_key:
        row = review_by_sample[key["sampleId"]]
        row["candidate1"] = response_by_id[key["candidate1RequestId"]]["translatedText"]
        row["candidate2"] = response_by_id[key["candidate2RequestId"]]["translatedText"]
    rows = [review_by_sample[key["sampleId"]] for key in hidden_key]
    _write_csv(package / "safety-review.csv", rows)
    return {"reviewablePairs": len(rows), "invalidResponses": 0, "complete": True}


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", " ")


def _direct_verdict(value: Any, *, allow_unclear: bool = True) -> str | None:
    normalized = _normalized(value)
    allowed = {"yes": "YES", "no": "NO"}
    if allow_unclear:
        allowed["unclear"] = "UNCLEAR"
    return allowed.get(normalized)


def _derived_verdict(row: dict[str, Any], key: dict[str, Any], field: str) -> str | None:
    direct_field = "bWorseThanA" if field == "worseCandidate" else "contextContamination"
    direct = _direct_verdict(row.get(direct_field), allow_unclear=True)
    if direct:
        return direct
    value = _normalized(row.get(field))
    if not value:
        return None
    if value == "unclear":
        return "UNCLEAR"
    b_candidate = "candidate1" if key["candidate1Variant"] == "B" else "candidate2"
    if field == "worseCandidate":
        if value == b_candidate:
            return "YES"
        if value in {"candidate1", "candidate2", "neither"}:
            return "NO"
    else:
        if value in {b_candidate, "both"}:
            return "YES"
        if value in {"candidate1", "candidate2", "neither"}:
            return "NO"
    raise ValueError(f"invalid {field} value for {row.get('sampleId')}")


def summarize_review(review_path: Path, hidden_key_path: Path, output: Path | None = None) -> dict[str, Any]:
    """Aggregate reviewed safety pairs by category and field role; never auto-adopt."""
    with review_path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    keys = json.loads(hidden_key_path.read_text(encoding="utf-8-sig"))
    key_by_sample = {row["sampleId"]: row for row in keys}
    if len(key_by_sample) != len(keys):
        raise ValueError("hidden review key contains duplicate sample IDs")
    aggregates: dict[tuple[str, str | None], dict[str, Any]] = {}

    def add(group: tuple[str, str | None], worse: str | None, contamination: str | None,
            patterns: list[str]) -> None:
        value = aggregates.setdefault(group, {
            "reviewedPairs": 0, "bWorseCount": 0, "contaminationCount": 0,
            "unclearCount": 0, "patterns": Counter(),
        })
        if worse is None and contamination is None:
            return
        value["reviewedPairs"] += 1
        value["bWorseCount"] += worse == "YES"
        value["contaminationCount"] += contamination == "YES"
        value["unclearCount"] += worse == "UNCLEAR" or contamination == "UNCLEAR"
        value["patterns"].update(patterns)

    seen = set()
    for row in rows:
        sample_id = row.get("sampleId", "")
        if sample_id in seen or sample_id not in key_by_sample:
            raise ValueError("review sample IDs are duplicate or absent from hidden key")
        seen.add(sample_id)
        worse = _derived_verdict(row, key_by_sample[sample_id], "worseCandidate")
        contamination = _derived_verdict(row, key_by_sample[sample_id], "contaminationCandidate")
        patterns = sorted({part.strip().lower() for part in str(row.get("failurePattern", "")).split(";") if part.strip()})
        add((row["category"], None), worse, contamination, patterns)
        add((row["category"], row["fieldRole"]), worse, contamination, patterns)

    def render(group: tuple[str, str | None], values: dict[str, Any]) -> dict[str, Any]:
        result = {
            "category": group[0], "reviewedPairs": values["reviewedPairs"],
            "bWorseCount": values["bWorseCount"],
            "contaminationCount": values["contaminationCount"],
            "unclearCount": values["unclearCount"],
            "recurringFailurePatterns": [
                {"pattern": pattern, "count": count}
                for pattern, count in sorted(values["patterns"].items()) if count >= 2
            ],
        }
        if group[1] is not None:
            result["fieldRole"] = group[1]
        return result

    summary = {
        "schemaVersion": "b1-02-safety-summary/1",
        "decision": "HUMAN_DECISION_REQUIRED",
        "categories": [render(group, aggregates.get(group, {
            "reviewedPairs": 0, "bWorseCount": 0, "contaminationCount": 0,
            "unclearCount": 0, "patterns": Counter(),
        })) for group in ((category, None) for category in CATEGORIES)],
        "fieldRoles": [render(group, values) for group, values in sorted(
            ((group, values) for group, values in aggregates.items() if group[1] is not None),
            key=lambda item: (item[0][0], item[0][1]),
        )],
    }
    if output:
        write_json(output, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--pilot-sample", type=Path, default=Path("workspace/b1-02/phase2/pilot-sample.jsonl"))
    export.add_argument("--pilot-manifest", type=Path, default=Path("workspace/b1-02/phase2/b1-02-phase2-pilot-manifest.json"))
    export.add_argument("--output", type=Path, default=Path("workspace/b1-02/safety-validation"))
    summary = commands.add_parser("summarize")
    summary.add_argument("--review", type=Path, default=Path("workspace/b1-02/safety-validation/safety-review.csv"))
    summary.add_argument("--hidden-key", type=Path, default=Path("workspace/b1-02/safety-validation/safety-review-hidden-key.json"))
    summary.add_argument("--output", type=Path, default=Path("workspace/b1-02/safety-validation/safety-summary.json"))
    review = commands.add_parser("build-review")
    review.add_argument("--package", type=Path, default=Path("workspace/b1-02/safety-validation"))
    review.add_argument("--responses", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "export":
        result = export_safety_package(args.pilot_sample, args.pilot_manifest, args.output)
        print(canonical({key: result[key] for key in ("sampleCount", "requestCount", "safetySubsetFingerprint")}))
    elif args.command == "build-review":
        print(canonical(build_safety_review(args.package, args.responses)))
    else:
        print(canonical(summarize_review(args.review, args.hidden_key, args.output)))


if __name__ == "__main__":
    main()
