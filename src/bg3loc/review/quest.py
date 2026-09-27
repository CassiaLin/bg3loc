from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from bg3loc.protected_syntax import validate_protected_syntax
from bg3loc.schema import SchemaStore
from bg3loc.review.bark import (
    BarkReviewDecision,
    _json_cell,
    _read_jsonl,
    _review_protected_tokens,
    _sha256,
    _text_sha256,
    _write_csv,
    load_locales,
)


@dataclass(frozen=True, slots=True)
class QuestReviewEvidence:
    occurrence_id: str
    rule: str
    source_role: str
    evidence_type: str
    pak_name: str
    internal_path: str
    field_name: str
    field_role: str
    node_identity: str = ""


@dataclass(frozen=True, slots=True)
class QuestReviewCandidate:
    candidate_id: str
    content_uid: str
    english_text: str
    quest_role: str
    occurrences: tuple[QuestReviewEvidence, ...]
    context_summary: str
    protected_tokens: tuple[str, ...]

    @property
    def occurrence_count(self) -> int:
        return len(self.occurrences)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["occurrences"] = [asdict(item) for item in self.occurrences]
        result["occurrence_count"] = self.occurrence_count
        result["protected_tokens"] = list(self.protected_tokens)
        return result


PASS1_COLUMNS = (
    "CandidateId", "ContentUid", "EnglishText", "QuestRole", "OccurrenceCount",
    "Occurrences", "ContextSummary", "ProtectedTokens", "ReviewerDecision",
    "ReviewerNote", "EvidenceSufficient", "DraftText", "ValidationStatus",
)
PASS2_COLUMNS = PASS1_COLUMNS + (
    "OfficialTarget", "ReferenceComparison", "ApprovedAuthority", "FinalDecision",
    "FinalText", "FinalValidationStatus",
)
_IMMUTABLE_COLUMNS = (
    "CandidateId", "ContentUid", "EnglishText", "QuestRole", "OccurrenceCount",
    "Occurrences", "ContextSummary", "ProtectedTokens",
)
_PASS1_FORBIDDEN = {"OfficialTarget", "ReferenceComparison", "ApprovedAuthority", "FinalDecision", "FinalText"}
_ALLOWED_ROLES = {"QuestTitle", "QuestDescription"}


def _candidate_id(content_uid: str) -> str:
    digest = hashlib.sha256(content_uid.casefold().encode("utf-8")).hexdigest()[:16].upper()
    return f"QUEST-{digest}"


def _occurrence_id(
    *, uid: str, path: str, field_name: str, field_role: str, rule: str, node_identity: str
) -> str:
    material = "\n".join((
        uid.casefold(), path.replace("\\", "/"), field_name, field_role, rule, node_identity,
    ))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16].upper()


def candidates_from_evidence(
    mappings: Iterable[dict[str, Any]], source_text: dict[str, str]
) -> tuple[QuestReviewCandidate, ...]:
    grouped: dict[str, list[QuestReviewEvidence]] = {}
    roles: dict[str, set[str]] = {}

    for mapping in mappings:
        if mapping.get("mappingType") != "context-evidence":
            continue
        uid = str(mapping.get("contentUid", ""))
        quest_evidence = [
            item for item in (mapping.get("evidence") or [])
            if isinstance(item, dict) and item.get("evidenceType") == "QuestJournal"
        ]
        if not quest_evidence:
            continue
        for evidence in quest_evidence:
            props = evidence.get("properties") or {}
            field_role = str(props.get("fieldRole", mapping.get("classification", "")))
            if field_role not in _ALLOWED_ROLES:
                continue
            field_name = str(props.get("fieldName", mapping.get("metadata", {}).get("fieldName", "")))
            path = str(evidence.get("resourcePath", ""))
            rule = str(evidence.get("ruleId", ""))
            node_identity = str(
                props.get("nodeId", props.get("nodeUuid", props.get("elementIndex", "")))
            )
            occurrence = QuestReviewEvidence(
                occurrence_id=_occurrence_id(
                    uid=uid,
                    path=path,
                    field_name=field_name,
                    field_role=field_role,
                    rule=rule,
                    node_identity=node_identity,
                ),
                rule=rule,
                source_role=str(evidence.get("sourceRole", "")),
                evidence_type=str(evidence.get("evidenceType", "")),
                pak_name=str(props.get("pakName", "")),
                internal_path=path,
                field_name=field_name,
                field_role=field_role,
                node_identity=node_identity,
            )
            grouped.setdefault(uid, []).append(occurrence)
            roles.setdefault(uid, set()).add(field_role)

    candidates: list[QuestReviewCandidate] = []
    for uid, raw_occurrences in grouped.items():
        unique_by_id = {item.occurrence_id: item for item in raw_occurrences}
        occurrences = tuple(sorted(unique_by_id.values(), key=lambda item: item.occurrence_id))
        role_set = roles.get(uid, set())
        if len(role_set) != 1:
            raise ValueError(f"{uid}: ambiguous QuestRole values: {', '.join(sorted(role_set))}")
        role = next(iter(role_set))
        text = source_text.get(uid, "")
        paths = sorted({Path(item.internal_path).name for item in occurrences if item.internal_path})
        summary = f"{role}; {len(occurrences)} occurrence(s); " + ", ".join(paths)
        candidates.append(QuestReviewCandidate(
            candidate_id=_candidate_id(uid),
            content_uid=uid,
            english_text=text,
            quest_role=role,
            occurrences=occurrences,
            context_summary=summary,
            protected_tokens=_review_protected_tokens(text),
        ))
    return tuple(sorted(candidates, key=lambda item: (item.content_uid.casefold(), item.candidate_id)))


def _surface_row(candidate: QuestReviewCandidate) -> dict[str, str]:
    return {
        "CandidateId": candidate.candidate_id,
        "ContentUid": candidate.content_uid,
        "EnglishText": candidate.english_text,
        "QuestRole": candidate.quest_role,
        "OccurrenceCount": str(candidate.occurrence_count),
        "Occurrences": _json_cell([asdict(item) for item in candidate.occurrences]),
        "ContextSummary": candidate.context_summary,
        "ProtectedTokens": _json_cell(list(candidate.protected_tokens)),
        "ReviewerDecision": BarkReviewDecision.PENDING.value,
        "ReviewerNote": "",
        "EvidenceSufficient": "",
        "DraftText": "",
        "ValidationStatus": "NotChecked",
    }


def _validate_prepared_candidates(candidates: Sequence[QuestReviewCandidate]) -> None:
    seen_ids: set[str] = set()
    seen_uids: set[str] = set()
    for candidate in candidates:
        if candidate.candidate_id in seen_ids:
            raise ValueError(f"duplicate CandidateId: {candidate.candidate_id}")
        if candidate.content_uid in seen_uids:
            raise ValueError(f"duplicate ContentUid: {candidate.content_uid}")
        seen_ids.add(candidate.candidate_id)
        seen_uids.add(candidate.content_uid)
        if not candidate.content_uid:
            raise ValueError(f"{candidate.candidate_id}: missing ContentUid")
        if not candidate.english_text:
            raise ValueError(f"{candidate.candidate_id}: missing English source")
        if candidate.quest_role not in _ALLOWED_ROLES:
            raise ValueError(f"{candidate.candidate_id}: invalid QuestRole {candidate.quest_role}")
        if not candidate.occurrences:
            raise ValueError(f"{candidate.candidate_id}: missing occurrence evidence")
        for occurrence in candidate.occurrences:
            if not occurrence.rule or not occurrence.internal_path or not occurrence.field_name:
                raise ValueError(f"{candidate.candidate_id}: incomplete occurrence provenance")
            if occurrence.field_role != candidate.quest_role:
                raise ValueError(f"{candidate.candidate_id}: occurrence role mismatch")


def prepare_quest_review(
    *, mappings_path: Path, extract_manifest: Path, output_dir: Path, include_pass2: bool = False
) -> dict[str, Any]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"Output directory must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    source, target, references, locales = load_locales(extract_manifest)
    candidates = candidates_from_evidence(_read_jsonl(mappings_path), locales[source])
    _validate_prepared_candidates(candidates)

    pass1_path = output_dir / "quest-review-pass1.csv"
    pass1_rows = [_surface_row(candidate) for candidate in candidates]
    _write_csv(pass1_path, PASS1_COLUMNS, pass1_rows)
    artifacts: list[dict[str, Any]] = [
        {"kind": "pass1", "path": str(pass1_path), "sha256": _sha256(pass1_path)}
    ]

    if include_pass2:
        pass2_path = output_dir / "quest-review-pass2.csv"
        pass2_rows: list[dict[str, str]] = []
        for candidate, row in zip(candidates, pass1_rows, strict=True):
            refs = {locale: locales[locale].get(candidate.content_uid, "") for locale in references}
            row2 = dict(row)
            row2.update({
                "OfficialTarget": locales[target].get(candidate.content_uid, ""),
                "ReferenceComparison": _json_cell(refs),
                "ApprovedAuthority": "",
                "FinalDecision": BarkReviewDecision.PENDING.value,
                "FinalText": "",
                "FinalValidationStatus": "NotChecked",
            })
            pass2_rows.append(row2)
        _write_csv(pass2_path, PASS2_COLUMNS, pass2_rows)
        artifacts.append({"kind": "pass2", "path": str(pass2_path), "sha256": _sha256(pass2_path)})

    comparison_evidence = {
        candidate.candidate_id: {
            f"OfficialTarget:{target}": {
                "present": bool(locales[target].get(candidate.content_uid, "")),
                "sha256": _text_sha256(locales[target].get(candidate.content_uid, "")),
            },
            **{
                f"ReferenceLocale:{locale}": {
                    "present": bool(locales[locale].get(candidate.content_uid, "")),
                    "sha256": _text_sha256(locales[locale].get(candidate.content_uid, "")),
                }
                for locale in references
            },
        }
        for candidate in candidates
    }

    manifest = {
        "schemaVersion": "1.0",
        "packageType": "QuestReviewPackage",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "sourceLocale": source,
        "targetLocale": target,
        "referenceLocales": list(references),
        "generationInputs": {
            "gameEvidence": True,
            "historicalWorkbook": False,
            "historicalUidList": False,
            "historicalReviewDecision": False,
        },
        "sourceEvidence": {
            "researchMappings": str(mappings_path),
            "extractManifest": str(extract_manifest),
        },
        "counts": {
            "total": len(candidates),
            "occurrences": sum(item.occurrence_count for item in candidates),
            "QuestTitle": sum(item.quest_role == "QuestTitle" for item in candidates),
            "QuestDescription": sum(item.quest_role == "QuestDescription" for item in candidates),
        },
        "allowedAuthorities": [
            f"OfficialTarget:{target}",
            *[f"ReferenceLocale:{locale}" for locale in references],
        ],
        "artifacts": artifacts,
        "comparisonEvidence": comparison_evidence,
        "candidates": [candidate.to_dict() for candidate in candidates],
    }
    SchemaStore().validate("quest-review-package.schema.json", manifest)
    (output_dir / "quest-review-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _expected_row(raw: dict[str, Any]) -> dict[str, str]:
    return {
        "CandidateId": str(raw["candidate_id"]),
        "ContentUid": str(raw["content_uid"]),
        "EnglishText": str(raw["english_text"]),
        "QuestRole": str(raw["quest_role"]),
        "OccurrenceCount": str(raw["occurrence_count"]),
        "Occurrences": _json_cell(raw.get("occurrences", [])),
        "ContextSummary": str(raw["context_summary"]),
        "ProtectedTokens": _json_cell(raw.get("protected_tokens", [])),
    }


def validate_quest_review(*, input_path: Path, manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {item["candidate_id"]: _expected_row(item) for item in manifest.get("candidates", [])}
    allowed_authorities = set(manifest.get("allowedAuthorities", []))
    comparison_evidence = manifest.get("comparisonEvidence", {})
    output_dir.mkdir(parents=True, exist_ok=True)
    findings: list[dict[str, Any]] = []
    reviewed: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_uids: set[str] = set()

    with input_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = set(reader.fieldnames or [])
        is_pass2 = "FinalText" in headers
        if not is_pass2:
            for column in sorted(headers & _PASS1_FORBIDDEN):
                findings.append({
                    "code": "QST006", "record": "<header>",
                    "message": f"Pass 1 target-text leakage column: {column}",
                })

        for row_number, row in enumerate(reader, 2):
            record = row.get("CandidateId") or f"row {row_number}"
            row_findings: list[dict[str, Any]] = []

            def issue(code: str, message: str) -> None:
                finding = {"code": code, "record": record, "row": row_number, "message": message}
                findings.append(finding)
                row_findings.append(finding)

            candidate_id = row.get("CandidateId", "")
            content_uid = row.get("ContentUid", "")
            if candidate_id in seen_ids:
                issue("QST001", "duplicate CandidateId")
            seen_ids.add(candidate_id)
            if content_uid in seen_uids:
                issue("QST002", "duplicate ContentUid")
            seen_uids.add(content_uid)
            baseline = expected.get(candidate_id)

            if not content_uid:
                issue("QST003", "missing ContentUid")
            if not row.get("EnglishText"):
                issue("QST004", "missing English source")
            if row.get("QuestRole") not in _ALLOWED_ROLES:
                issue("QST005", f"invalid QuestRole: {row.get('QuestRole', '')}")
            if not row.get("Occurrences"):
                issue("QST009", "missing occurrence evidence")

            if baseline is None:
                issue("QST011", "CandidateId is not present in the package manifest")
            else:
                for column in _IMMUTABLE_COLUMNS:
                    if row.get(column, "") != baseline[column]:
                        code = "QST009" if column in ("OccurrenceCount", "Occurrences", "QuestRole") else "QST011"
                        issue(code, f"immutable {column} changed")

            decisions = [("ReviewerDecision", row.get("ReviewerDecision", ""))]
            if is_pass2:
                decisions.append(("FinalDecision", row.get("FinalDecision", "")))
            allowed_decisions = {item.value for item in BarkReviewDecision}
            for column, value in decisions:
                if value not in allowed_decisions:
                    issue("QST007", f"invalid {column}: {value}")

            if row.get("EvidenceSufficient", "") not in ("", "true", "false", "TRUE", "FALSE"):
                issue("QST008", "EvidenceSufficient must be true, false, or blank")

            authority = row.get("ApprovedAuthority", "")
            if authority and authority not in allowed_authorities:
                issue("QST010", f"invalid ApprovedAuthority: {authority}")

            if is_pass2 and baseline is not None:
                comparisons: dict[str, str] = {
                    f"OfficialTarget:{manifest['targetLocale']}": row.get("OfficialTarget", "")
                }
                try:
                    references = json.loads(row.get("ReferenceComparison", "{}") or "{}")
                    if not isinstance(references, dict):
                        raise ValueError("not an object")
                except (json.JSONDecodeError, ValueError) as exc:
                    issue("QST014", f"invalid ReferenceComparison JSON: {exc}")
                    references = {}
                comparisons.update({
                    f"ReferenceLocale:{locale}": str(value)
                    for locale, value in references.items()
                })
                expected_comparisons = comparison_evidence.get(candidate_id, {})
                for label, expected_value in expected_comparisons.items():
                    actual_text = comparisons.get(label, "")
                    if _text_sha256(actual_text) != expected_value.get("sha256"):
                        issue("QST014", f"comparison evidence changed: {label}")
                if authority in allowed_authorities:
                    authority_evidence = expected_comparisons.get(authority, {})
                    if not authority_evidence.get("present"):
                        issue("QST010", f"ApprovedAuthority has no evidence for this candidate: {authority}")
                    if row.get("FinalDecision") == BarkReviewDecision.PENDING.value:
                        issue("QST010", "ApprovedAuthority cannot be recorded while FinalDecision is Pending")

            text_column = "FinalText" if is_pass2 else "DraftText"
            candidate_text = row.get(text_column, "")
            if candidate_text and baseline is not None:
                required = json.loads(baseline["ProtectedTokens"])
                exact_required = [
                    token for token in required
                    if not token.startswith("<LSTag") and token != "</LSTag>"
                ]
                for syntax_issue in validate_protected_syntax(exact_required, candidate_text):
                    issue(
                        "QST012",
                        f"protected-token drift ({syntax_issue.kind}): {', '.join(syntax_issue.details)}",
                    )
                expected_lstag = [
                    token for token in required
                    if token.startswith("<LSTag") or token == "</LSTag>"
                ]
                actual_lstag = [
                    token for token in _review_protected_tokens(candidate_text)
                    if token.startswith("<LSTag") or token == "</LSTag>"
                ]
                if expected_lstag != actual_lstag:
                    issue(
                        "QST012",
                        f"protected-token drift (LSTag): expected {expected_lstag}, got {actual_lstag}",
                    )

            result_column = "FinalValidationStatus" if is_pass2 else "ValidationStatus"
            row[result_column] = "Failed" if row_findings else "Passed"
            reviewed.append(dict(row))

    for missing in sorted(expected.keys() - seen_ids):
        findings.append({"code": "QST013", "record": missing, "message": "candidate missing from review input"})

    reviewed_path = output_dir / "quest-reviewed.csv"
    columns = PASS2_COLUMNS if reviewed and "FinalText" in reviewed[0] else PASS1_COLUMNS
    _write_csv(reviewed_path, columns, reviewed)
    result = {
        "schemaVersion": "1.0",
        "status": "failed" if findings else "passed",
        "input": str(input_path),
        "manifest": str(manifest_path),
        "recordCount": len(reviewed),
        "findingCount": len(findings),
        "findings": findings,
        "reviewedOutput": str(reviewed_path),
    }
    (output_dir / "quest-review-validation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result
