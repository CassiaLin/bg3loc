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
    _review_protected_tokens,
    _sha256,
    _text_sha256,
    _write_csv,
    load_locales,
)

RULE_UI_SKILL_REVIEW = "BG3-UI-SKILL-REVIEW-EVIDENCE"

@dataclass(frozen=True, slots=True)
class UiSkillReviewEvidence:
    relation_id: str
    rule: str
    classification: str
    domain: str
    workstream: str
    effective_provider: str
    defining_provider: str
    package: str
    internal_path: str
    source_families: tuple[str, ...]
    domains: tuple[str, ...]
    entity_type: str
    entity: str
    field: str
    inherited_from: str
    inheritance_depth: int
    explicit_or_inherited: str
    provider_override_applied: bool
    comment_only: bool


@dataclass(frozen=True, slots=True)
class UiSkillReviewCandidate:
    candidate_id: str
    content_uid: str
    english_text: str
    workstreams: tuple[str, ...]
    domains: tuple[str, ...]
    relations: tuple[UiSkillReviewEvidence, ...]
    context_summary: str
    protected_tokens: tuple[str, ...]

    @property
    def relation_count(self) -> int:
        return len(self.relations)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["workstreams"] = list(self.workstreams)
        result["domains"] = list(self.domains)
        result["relations"] = []
        for item in self.relations:
            relation = asdict(item)
            relation["source_families"] = list(item.source_families)
            relation["domains"] = list(item.domains)
            result["relations"].append(relation)
        result["relation_count"] = self.relation_count
        result["protected_tokens"] = list(self.protected_tokens)
        return result


PASS1_COLUMNS = (
    "CandidateId", "ContentUid", "EnglishText", "Workstreams", "Domains",
    "RelationCount", "Relations", "ContextSummary", "ProtectedTokens",
    "ReviewerDecision", "ReviewerNote", "EvidenceSufficient", "DraftText",
    "ValidationStatus",
)
PASS2_COLUMNS = PASS1_COLUMNS + (
    "OfficialTarget", "ReferenceComparison", "ApprovedAuthority", "FinalDecision",
    "FinalText", "FinalValidationStatus",
)
_IMMUTABLE_COLUMNS = (
    "CandidateId", "ContentUid", "EnglishText", "Workstreams", "Domains",
    "RelationCount", "Relations", "ContextSummary", "ProtectedTokens",
)
_PASS1_FORBIDDEN = {
    "OfficialTarget", "ReferenceComparison", "ApprovedAuthority", "FinalDecision", "FinalText"
}


def _candidate_id(content_uid: str) -> str:
    digest = hashlib.sha256(content_uid.encode("utf-8")).hexdigest()[:16].upper()
    return f"UISKILL-{digest}"


def _bool_cell(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def _relation_id(row: dict[str, str]) -> str:
    material = "\n".join(
        str(row.get(name, ""))
        for name in (
            "ContentUid", "Status", "Workstream", "Provider", "Package", "InternalPath",
            "SourceFamilies", "Domains", "EntityType", "EntityName", "FieldName",
            "ParentName", "InheritanceDepth", "ExplicitOrInherited", "CommentOnly",
            "DefiningProvider", "ProviderOverrideApplied",
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16].upper()


def read_ui_skill_universe(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def candidates_from_universe(
    rows: Iterable[dict[str, str]],
    *,
    source_text: dict[str, str],
) -> tuple[UiSkillReviewCandidate, ...]:
    grouped: dict[str, list[UiSkillReviewEvidence]] = {}

    for row in rows:
        uid = str(row.get("ContentUid", ""))
        if not uid or uid not in source_text:
            continue
        if str(row.get("Status", "")) != "Eligible" or _bool_cell(str(row.get("CommentOnly", ""))):
            continue
        domains = tuple(filter(None, str(row.get("Domains", "")).split(";")))
        source_families = tuple(filter(None, str(row.get("SourceFamilies", "")).split(";")))
        workstream = str(row.get("Workstream", "")) or "OtherMultiDomain"
        provider = str(row.get("Provider", ""))
        relation = UiSkillReviewEvidence(
            relation_id=_relation_id(row),
            rule=RULE_UI_SKILL_REVIEW,
            classification="SemanticTarget",
            domain=domains[0] if domains else "Unknown",
            workstream=workstream,
            effective_provider=provider,
            defining_provider=str(row.get("DefiningProvider", "")) or provider,
            package=str(row.get("Package", "")),
            internal_path=str(row.get("InternalPath", "")),
            source_families=source_families,
            domains=domains,
            entity_type=str(row.get("EntityType", "")),
            entity=str(row.get("EntityName", "")),
            field=str(row.get("FieldName", "")),
            inherited_from=str(row.get("ParentName", "")),
            inheritance_depth=int(row.get("InheritanceDepth", "0") or 0),
            explicit_or_inherited=str(row.get("ExplicitOrInherited", "")),
            provider_override_applied=_bool_cell(str(row.get("ProviderOverrideApplied", ""))),
            comment_only=False,
        )
        grouped.setdefault(uid, []).append(relation)

    candidates: list[UiSkillReviewCandidate] = []
    for uid, raw_relations in grouped.items():
        unique = {item.relation_id: item for item in raw_relations}
        relations = tuple(sorted(unique.values(), key=lambda item: item.relation_id))
        domains = tuple(sorted({domain for item in relations for domain in item.domains}))
        workstreams = tuple(sorted({item.workstream for item in relations}))
        providers = sorted({item.effective_provider for item in relations if item.effective_provider})
        summary = (
            f"{len(relations)} relation(s); "
            f"workstreams={','.join(workstreams)}; providers={','.join(providers)}"
        )
        text = source_text.get(uid, "")
        candidates.append(
            UiSkillReviewCandidate(
                candidate_id=_candidate_id(uid),
                content_uid=uid,
                english_text=text,
                workstreams=workstreams,
                domains=domains,
                relations=relations,
                context_summary=summary,
                protected_tokens=_review_protected_tokens(text),
            )
        )
    return tuple(sorted(candidates, key=lambda item: (item.content_uid, item.candidate_id)))


def _surface_row(candidate: UiSkillReviewCandidate) -> dict[str, str]:
    return {
        "CandidateId": candidate.candidate_id,
        "ContentUid": candidate.content_uid,
        "EnglishText": candidate.english_text,
        "Workstreams": _json_cell(list(candidate.workstreams)),
        "Domains": _json_cell(list(candidate.domains)),
        "RelationCount": str(candidate.relation_count),
        "Relations": _json_cell([asdict(item) for item in candidate.relations]),
        "ContextSummary": candidate.context_summary,
        "ProtectedTokens": _json_cell(list(candidate.protected_tokens)),
        "ReviewerDecision": BarkReviewDecision.PENDING.value,
        "ReviewerNote": "",
        "EvidenceSufficient": "",
        "DraftText": "",
        "ValidationStatus": "NotChecked",
    }


def _validate_prepared_candidates(candidates: Sequence[UiSkillReviewCandidate]) -> None:
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
        if not candidate.relations:
            raise ValueError(f"{candidate.candidate_id}: missing relation evidence")
        if len(candidate.workstreams) != 1:
            raise ValueError(f"{candidate.candidate_id}: expected exactly one workstream")
        for relation in candidate.relations:
            if not relation.internal_path or not relation.entity or not relation.field:
                raise ValueError(f"{candidate.candidate_id}: incomplete relation provenance")
            if not relation.effective_provider or not relation.defining_provider:
                raise ValueError(f"{candidate.candidate_id}: incomplete provider provenance")
            if relation.classification != "SemanticTarget":
                raise ValueError(f"{candidate.candidate_id}: non-semantic relation in review package")


def prepare_ui_skill_review(
    *, universe_path: Path, extract_manifest: Path, output_dir: Path,
    include_pass2: bool = False,
) -> dict[str, Any]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"Output directory must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    source, target, references, locales = load_locales(extract_manifest)
    rows = read_ui_skill_universe(universe_path)
    candidates = candidates_from_universe(rows, source_text=locales[source])
    _validate_prepared_candidates(candidates)

    pass1_path = output_dir / "ui-skill-review-pass1.csv"
    pass1_rows = [_surface_row(candidate) for candidate in candidates]
    _write_csv(pass1_path, PASS1_COLUMNS, pass1_rows)
    artifacts: list[dict[str, Any]] = [
        {"kind": "pass1", "path": str(pass1_path), "sha256": _sha256(pass1_path)}
    ]

    if include_pass2:
        pass2_path = output_dir / "ui-skill-review-pass2.csv"
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
    workstream_counts: dict[str, int] = {}
    for candidate in candidates:
        for workstream in candidate.workstreams:
            workstream_counts[workstream] = workstream_counts.get(workstream, 0) + 1

    manifest = {
        "schemaVersion": "1.0",
        "packageType": "UiSkillReviewPackage",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "sourceLocale": source,
        "targetLocale": target,
        "referenceLocales": list(references),
        "generationInputs": {
            "gameEvidence": True,
            "uiSkillUniverse": True,
            "sourceOnlyBoundary": False,
            "historicalWorkbook": False,
            "historicalUidList": False,
            "historicalReviewDecision": False,
        },
        "sourceEvidence": {
            "uiSkillUniverse": str(universe_path),
            "extractManifest": str(extract_manifest),
        },
        "counts": {
            "total": len(candidates),
            "relations": sum(item.relation_count for item in candidates),
            "workstreams": workstream_counts,
            "domains": sorted({domain for item in candidates for domain in item.domains}),
        },
        "allowedAuthorities": [
            f"OfficialTarget:{target}",
            *[f"ReferenceLocale:{locale}" for locale in references],
        ],
        "artifacts": artifacts,
        "comparisonEvidence": comparison_evidence,
        "candidates": [candidate.to_dict() for candidate in candidates],
    }
    SchemaStore().validate("ui-skill-review-package.schema.json", manifest)
    (output_dir / "ui-skill-review-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _expected_row(raw: dict[str, Any]) -> dict[str, str]:
    return {
        "CandidateId": str(raw["candidate_id"]),
        "ContentUid": str(raw["content_uid"]),
        "EnglishText": str(raw["english_text"]),
        "Workstreams": _json_cell(raw.get("workstreams", [])),
        "Domains": _json_cell(raw.get("domains", [])),
        "RelationCount": str(raw["relation_count"]),
        "Relations": _json_cell(raw.get("relations", [])),
        "ContextSummary": str(raw["context_summary"]),
        "ProtectedTokens": _json_cell(raw.get("protected_tokens", [])),
    }


def validate_ui_skill_review(*, input_path: Path, manifest_path: Path, output_dir: Path) -> dict[str, Any]:
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
                    "code": "UIS006", "record": "<header>",
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
                issue("UIS001", "duplicate CandidateId")
            seen_ids.add(candidate_id)
            if content_uid in seen_uids:
                issue("UIS002", "duplicate ContentUid")
            seen_uids.add(content_uid)
            baseline = expected.get(candidate_id)

            if not content_uid:
                issue("UIS003", "missing ContentUid")
            if not row.get("EnglishText"):
                issue("UIS004", "missing English source")
            if not row.get("Relations"):
                issue("UIS005", "missing relation evidence")

            if baseline is None:
                issue("UIS011", "CandidateId is not present in the package manifest")
            else:
                for column in _IMMUTABLE_COLUMNS:
                    if row.get(column, "") != baseline[column]:
                        code = "UIS009" if column in ("RelationCount", "Relations", "Workstreams", "Domains") else "UIS011"
                        issue(code, f"immutable {column} changed")

            decisions = [("ReviewerDecision", row.get("ReviewerDecision", ""))]
            if is_pass2:
                decisions.append(("FinalDecision", row.get("FinalDecision", "")))
            allowed_decisions = {item.value for item in BarkReviewDecision}
            for column, value in decisions:
                if value not in allowed_decisions:
                    issue("UIS007", f"invalid {column}: {value}")

            if row.get("EvidenceSufficient", "") not in ("", "true", "false", "TRUE", "FALSE"):
                issue("UIS008", "EvidenceSufficient must be true, false, or blank")

            authority = row.get("ApprovedAuthority", "")
            if authority and authority not in allowed_authorities:
                issue("UIS010", f"invalid ApprovedAuthority: {authority}")

            if is_pass2 and baseline is not None:
                comparisons: dict[str, str] = {
                    f"OfficialTarget:{manifest['targetLocale']}": row.get("OfficialTarget", "")
                }
                try:
                    references = json.loads(row.get("ReferenceComparison", "{}") or "{}")
                    if not isinstance(references, dict):
                        raise ValueError("not an object")
                except (json.JSONDecodeError, ValueError) as exc:
                    issue("UIS014", f"invalid ReferenceComparison JSON: {exc}")
                    references = {}
                comparisons.update({f"ReferenceLocale:{locale}": str(value) for locale, value in references.items()})
                expected_comparisons = comparison_evidence.get(candidate_id, {})
                for label, expected_value in expected_comparisons.items():
                    if _text_sha256(comparisons.get(label, "")) != expected_value.get("sha256"):
                        issue("UIS014", f"comparison evidence changed: {label}")
                if authority in allowed_authorities:
                    authority_evidence = expected_comparisons.get(authority, {})
                    if not authority_evidence.get("present"):
                        issue("UIS010", f"ApprovedAuthority has no evidence for this candidate: {authority}")
                    if row.get("FinalDecision") == BarkReviewDecision.PENDING.value:
                        issue("UIS010", "ApprovedAuthority cannot be recorded while FinalDecision is Pending")

            text_column = "FinalText" if is_pass2 else "DraftText"
            candidate_text = row.get(text_column, "")
            if candidate_text and baseline is not None:
                required = json.loads(baseline["ProtectedTokens"])
                exact_required = [
                    token for token in required if not token.startswith("<LSTag") and token != "</LSTag>"
                ]
                for syntax_issue in validate_protected_syntax(exact_required, candidate_text):
                    issue(
                        "UIS012",
                        f"protected-token drift ({syntax_issue.kind}): {', '.join(syntax_issue.details)}",
                    )
                expected_lstag = [
                    token for token in required if token.startswith("<LSTag") or token == "</LSTag>"
                ]
                actual_lstag = [
                    token for token in _review_protected_tokens(candidate_text)
                    if token.startswith("<LSTag") or token == "</LSTag>"
                ]
                if expected_lstag != actual_lstag:
                    issue(
                        "UIS012",
                        f"protected-token drift (LSTag): expected {expected_lstag}, got {actual_lstag}",
                    )

            result_column = "FinalValidationStatus" if is_pass2 else "ValidationStatus"
            row[result_column] = "Failed" if row_findings else "Passed"
            reviewed.append(dict(row))

    for missing in sorted(expected.keys() - seen_ids):
        findings.append({"code": "UIS013", "record": missing, "message": "candidate missing from review input"})

    reviewed_path = output_dir / "ui-skill-reviewed.csv"
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
    (output_dir / "ui-skill-review-validation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result
