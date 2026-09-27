from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from bg3loc.protected_syntax import validate_protected_syntax
from bg3loc.review.bark import (
    BarkReviewDecision,
    _json_cell,
    _read_jsonl,
    _review_protected_tokens,
    _sha256,
    _write_csv,
    load_locales,
)
from bg3loc.schema import SchemaStore

RULE_MULTILINGUAL_REVIEW = "BG3-MULTILINGUAL-HUMAN-REVIEW"


@dataclass(frozen=True, slots=True)
class MultilingualReviewCandidate:
    candidate_id: str
    content_uid: str
    english_text: str
    exact_reuse_class: str
    reusable_target_occurrence_count: int
    reusable_target_distinct_count: int
    same_uid_reference_locales: tuple[str, ...]
    protected_tokens: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["same_uid_reference_locales"] = list(self.same_uid_reference_locales)
        raw["protected_tokens"] = list(self.protected_tokens)
        return raw


PASS1_COLUMNS = (
    "CandidateId", "ContentUid", "EnglishText", "ExactReuseClass",
    "ReusableTargetOccurrenceCount", "ReusableTargetDistinctCount",
    "SameUidReferenceLocales", "ProtectedTokens", "ReviewerDecision",
    "ReviewerNote", "EvidenceSufficient", "DraftText", "ValidationStatus",
)
PASS2_COLUMNS = PASS1_COLUMNS + (
    "ExactReuseCandidates", "ReferenceComparison", "ApprovedAuthority",
    "FinalDecision", "FinalText", "FinalValidationStatus",
)
_IMMUTABLE_COLUMNS = (
    "CandidateId", "ContentUid", "EnglishText", "ExactReuseClass",
    "ReusableTargetOccurrenceCount", "ReusableTargetDistinctCount",
    "SameUidReferenceLocales", "ProtectedTokens",
)
_PASS1_FORBIDDEN = {
    "ExactReuseCandidates", "ReferenceComparison", "ApprovedAuthority",
    "FinalDecision", "FinalText",
}


def _candidate_id(uid: str) -> str:
    digest = hashlib.sha256(uid.casefold().encode("utf-8")).hexdigest()[:16].upper()
    return f"MULTI-{digest}"


def candidates_from_mappings(
    mappings: Iterable[dict[str, Any]],
    *,
    source_text: dict[str, str],
) -> tuple[MultilingualReviewCandidate, ...]:
    candidates: list[MultilingualReviewCandidate] = []
    seen: set[str] = set()
    for mapping in mappings:
        if mapping.get("mappingType") != "multilingual-reference":
            continue
        uid = str(mapping.get("contentUid", ""))
        if not uid or uid in seen or uid not in source_text:
            continue
        seen.add(uid)
        metadata = mapping.get("metadata") or {}
        refs = tuple(sorted(
            key[len("hasSameUid"):]
            for key, value in metadata.items()
            if key.startswith("hasSameUid") and bool(value)
        ))
        candidates.append(MultilingualReviewCandidate(
            candidate_id=_candidate_id(uid),
            content_uid=uid,
            english_text=source_text[uid],
            exact_reuse_class=str(metadata.get("referenceType") or mapping.get("classification") or "NO_EXACT_CANDIDATE"),
            reusable_target_occurrence_count=int(metadata.get("reusableTargetOccurrenceCount", 0) or 0),
            reusable_target_distinct_count=int(metadata.get("reusableTargetDistinctCount", metadata.get("reusableTargetCount", 0)) or 0),
            same_uid_reference_locales=refs,
            protected_tokens=_review_protected_tokens(source_text[uid]),
        ))
    return tuple(sorted(candidates, key=lambda item: item.content_uid))


def _surface_row(candidate: MultilingualReviewCandidate) -> dict[str, str]:
    return {
        "CandidateId": candidate.candidate_id,
        "ContentUid": candidate.content_uid,
        "EnglishText": candidate.english_text,
        "ExactReuseClass": candidate.exact_reuse_class,
        "ReusableTargetOccurrenceCount": str(candidate.reusable_target_occurrence_count),
        "ReusableTargetDistinctCount": str(candidate.reusable_target_distinct_count),
        "SameUidReferenceLocales": _json_cell(list(candidate.same_uid_reference_locales)),
        "ProtectedTokens": _json_cell(list(candidate.protected_tokens)),
        "ReviewerDecision": BarkReviewDecision.PENDING.value,
        "ReviewerNote": "",
        "EvidenceSufficient": "",
        "DraftText": "",
        "ValidationStatus": "NotChecked",
    }


def _reuse_index(source: dict[str, str], target: dict[str, str], boundary: set[str]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for uid, source_value in source.items():
        if uid in boundary or uid not in target:
            continue
        values.setdefault(source_value, []).append(target[uid])
    return values


def prepare_multilingual_review(
    *, mappings_path: Path, extract_manifest: Path, output_dir: Path,
    include_pass2: bool = False,
) -> dict[str, Any]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"Output directory must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    source, target, references, locales = load_locales(extract_manifest)
    mappings = _read_jsonl(mappings_path)
    candidates = candidates_from_mappings(mappings, source_text=locales[source])
    if not candidates:
        raise ValueError("No multilingual-reference candidates found")

    uids = [item.content_uid for item in candidates]
    if len(uids) != len(set(uids)):
        raise ValueError("duplicate multilingual ContentUid")
    boundary = set(uids)
    expected_boundary = set(locales[source]) - set(locales[target])
    if boundary != expected_boundary:
        missing = len(expected_boundary - boundary)
        extra = len(boundary - expected_boundary)
        raise ValueError(f"multilingual boundary mismatch: missing={missing}, extra={extra}")

    pass1_path = output_dir / "multilingual-review-pass1.csv"
    pass1_rows = [_surface_row(item) for item in candidates]
    _write_csv(pass1_path, PASS1_COLUMNS, pass1_rows)
    artifacts: list[dict[str, Any]] = [
        {"kind": "pass1", "path": str(pass1_path), "sha256": _sha256(pass1_path)}
    ]

    comparison_evidence: dict[str, dict[str, Any]] = {}
    reuse = _reuse_index(locales[source], locales[target], boundary)
    if include_pass2:
        pass2_path = output_dir / "multilingual-review-pass2.csv"
        pass2_rows: list[dict[str, str]] = []
        for candidate, row in zip(candidates, pass1_rows, strict=True):
            exact_values = sorted(set(reuse.get(candidate.english_text, [])))
            refs = {locale: locales[locale].get(candidate.content_uid, "") for locale in references}
            row2 = dict(row)
            row2.update({
                "ExactReuseCandidates": _json_cell(exact_values),
                "ReferenceComparison": _json_cell(refs),
                "ApprovedAuthority": "",
                "FinalDecision": BarkReviewDecision.PENDING.value,
                "FinalText": "",
                "FinalValidationStatus": "NotChecked",
            })
            pass2_rows.append(row2)
            comparison_evidence[candidate.candidate_id] = {
                "exactReuseCandidateCount": len(exact_values),
                "referenceLocalesPresent": [locale for locale, text in refs.items() if text],
            }
        _write_csv(pass2_path, PASS2_COLUMNS, pass2_rows)
        artifacts.append({"kind": "pass2", "path": str(pass2_path), "sha256": _sha256(pass2_path)})

    class_counts: dict[str, int] = {}
    for item in candidates:
        class_counts[item.exact_reuse_class] = class_counts.get(item.exact_reuse_class, 0) + 1

    manifest = {
        "schemaVersion": "1.0",
        "packageType": "MultilingualReviewPackage",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "sourceLocale": source,
        "targetLocale": target,
        "referenceLocales": list(references),
        "generationInputs": {
            "currentSourceLocale": True,
            "currentTargetLocale": True,
            "optionalReferenceLocales": bool(references),
            "historicalWorkbook": False,
            "historicalUidList": False,
            "historicalReviewDecision": False,
        },
        "counts": {
            "total": len(candidates),
            "classifications": class_counts,
            "referenceLocales": len(references),
        },
        "allowedAuthorities": [],
        "artifacts": artifacts,
        "comparisonEvidence": comparison_evidence,
        "candidates": [item.to_dict() for item in candidates],
        "ruleId": RULE_MULTILINGUAL_REVIEW,
    }
    SchemaStore().validate("multilingual-review-package.schema.json", manifest)
    manifest_path = output_dir / "multilingual-review-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _expected_row(raw: dict[str, Any]) -> dict[str, str]:
    return {
        "CandidateId": str(raw["candidate_id"]),
        "ContentUid": str(raw["content_uid"]),
        "EnglishText": str(raw["english_text"]),
        "ExactReuseClass": str(raw["exact_reuse_class"]),
        "ReusableTargetOccurrenceCount": str(raw["reusable_target_occurrence_count"]),
        "ReusableTargetDistinctCount": str(raw["reusable_target_distinct_count"]),
        "SameUidReferenceLocales": _json_cell(raw.get("same_uid_reference_locales", [])),
        "ProtectedTokens": _json_cell(raw.get("protected_tokens", [])),
    }


def validate_multilingual_review(*, input_path: Path, manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {item["candidate_id"]: _expected_row(item) for item in manifest.get("candidates", [])}
    output_dir.mkdir(parents=True, exist_ok=True)
    findings: list[dict[str, Any]] = []
    reviewed: list[dict[str, str]] = []
    seen: set[str] = set()

    with input_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = set(reader.fieldnames or [])
        is_pass2 = "FinalText" in headers
        if not is_pass2:
            for column in sorted(headers & _PASS1_FORBIDDEN):
                findings.append({"code": "MUL006", "record": "<header>", "message": f"Pass 1 comparison-text leakage column: {column}"})

        for row_number, row in enumerate(reader, 2):
            record = row.get("CandidateId") or f"row {row_number}"
            if record in seen:
                findings.append({"code": "MUL002", "record": record, "row": row_number, "message": "duplicate CandidateId"})
            seen.add(record)
            exp = expected.get(record)
            if exp is None:
                findings.append({"code": "MUL001", "record": record, "row": row_number, "message": "unknown CandidateId"})
                continue
            for column in _IMMUTABLE_COLUMNS:
                if str(row.get(column, "")) != exp[column]:
                    findings.append({"code": "MUL003", "record": record, "row": row_number, "message": f"immutable evidence changed: {column}"})

            text_field = "FinalText" if is_pass2 else "DraftText"
            decision_field = "FinalDecision" if is_pass2 else "ReviewerDecision"
            text = str(row.get(text_field, ""))
            decision = str(row.get(decision_field, ""))
            if decision not in {item.value for item in BarkReviewDecision}:
                findings.append({"code": "MUL004", "record": record, "row": row_number, "message": f"invalid decision: {decision}"})
            if text:
                required_tokens = json.loads(exp["ProtectedTokens"])
                syntax_issues = validate_protected_syntax(required_tokens, text)
                if syntax_issues:
                    details = "; ".join(
                        f"{issue.kind}: {', '.join(issue.details)}" if issue.details else issue.kind
                        for issue in syntax_issues
                    )
                    findings.append({"code": "MUL005", "record": record, "row": row_number, "message": details})
            reviewed.append(dict(row))

    for missing in sorted(set(expected) - seen):
        findings.append({"code": "MUL007", "record": missing, "message": "candidate missing from completed review"})

    reviewed_path = output_dir / "multilingual-reviewed.csv"
    if reviewed:
        columns = list(reviewed[0].keys())
        _write_csv(reviewed_path, columns, reviewed)
    else:
        reviewed_path.write_text("", encoding="utf-8")
    result = {
        "status": "passed" if not findings else "failed",
        "findingCount": len(findings),
        "findings": findings,
        "reviewedOutput": str(reviewed_path),
    }
    (output_dir / "multilingual-review-validation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result
