from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from bg3loc.protected_syntax import validate_protected_syntax
from bg3loc.review.bark import (
    _json_cell,
    _review_protected_tokens,
    _sha256,
    _write_csv,
    load_locales,
)
from bg3loc.schema import SchemaStore

RULE_TAIWAN_USAGE_REVIEW = "BG3-TAIWAN-USAGE-HUMAN-REVIEW"


class TaiwanUsageDecision(str, Enum):
    PENDING = "Pending"
    ACCEPT_AS_IS = "AcceptAsIs"
    REVISE = "Revise"
    NOT_APPLICABLE = "NotApplicable"
    NEEDS_CONTEXT = "NeedsContext"


@dataclass(frozen=True, slots=True)
class TaiwanUsageRule:
    rule_id: str
    kind: str
    pattern: str
    category: str
    rationale: str
    recommendation: str
    ignore_case: bool


@dataclass(frozen=True, slots=True)
class TaiwanUsageFinding:
    rule_id: str
    category: str
    matched_text: str
    start: int
    end: int
    rationale: str
    recommendation: str


@dataclass(frozen=True, slots=True)
class TaiwanUsageCandidate:
    candidate_id: str
    content_uid: str
    source_text: str
    target_text: str
    findings: tuple[TaiwanUsageFinding, ...]
    protected_tokens: tuple[str, ...]

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["findings"] = [asdict(item) for item in self.findings]
        raw["protected_tokens"] = list(self.protected_tokens)
        raw["finding_count"] = self.finding_count
        return raw


REVIEW_COLUMNS = (
    "CandidateId", "ContentUid", "SourceText", "TargetText",
    "FindingCount", "Findings", "ProtectedTokens",
    "ReviewerDecision", "ReviewerNote", "ProposedText", "ValidationStatus",
)
_IMMUTABLE_COLUMNS = (
    "CandidateId", "ContentUid", "SourceText", "TargetText",
    "FindingCount", "Findings", "ProtectedTokens",
)


def _candidate_id(uid: str) -> str:
    digest = hashlib.sha256(uid.casefold().encode("utf-8")).hexdigest()[:16].upper()
    return f"TWUSAGE-{digest}"


def load_taiwan_usage_rules(path: Path) -> tuple[TaiwanUsageRule, ...]:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    SchemaStore().validate("taiwan-usage-rules.schema.json", raw)
    rules: list[TaiwanUsageRule] = []
    seen: set[str] = set()
    for item in raw.get("rules", []):
        rule_id = str(item["ruleId"])
        if rule_id in seen:
            raise ValueError(f"duplicate Taiwan usage ruleId: {rule_id}")
        seen.add(rule_id)
        rule = TaiwanUsageRule(
            rule_id=rule_id,
            kind=str(item["kind"]),
            pattern=str(item["pattern"]),
            category=str(item["category"]),
            rationale=str(item["rationale"]),
            recommendation=str(item.get("recommendation", "")),
            ignore_case=bool(item.get("ignoreCase", False)),
        )
        if rule.kind == "regex":
            try:
                re.compile(rule.pattern, re.IGNORECASE if rule.ignore_case else 0)
            except re.error as exc:
                raise ValueError(f"invalid regex for {rule.rule_id}: {exc}") from exc
        rules.append(rule)
    if not rules:
        raise ValueError("Taiwan usage rule set contains no rules")
    return tuple(rules)


def _rule_matches(text: str, rule: TaiwanUsageRule) -> Iterable[re.Match[str]]:
    flags = re.IGNORECASE if rule.ignore_case else 0
    pattern = re.escape(rule.pattern) if rule.kind == "literal" else rule.pattern
    return re.finditer(pattern, text, flags)


def candidates_from_target(
    *,
    source_records: dict[str, str],
    target_records: dict[str, str],
    rules: Iterable[TaiwanUsageRule],
) -> tuple[TaiwanUsageCandidate, ...]:
    rules_tuple = tuple(rules)
    candidates: list[TaiwanUsageCandidate] = []
    for uid in sorted(target_records):
        target_text = target_records[uid]
        findings: list[TaiwanUsageFinding] = []
        for rule in rules_tuple:
            for match in _rule_matches(target_text, rule):
                findings.append(TaiwanUsageFinding(
                    rule_id=rule.rule_id,
                    category=rule.category,
                    matched_text=match.group(0),
                    start=match.start(),
                    end=match.end(),
                    rationale=rule.rationale,
                    recommendation=rule.recommendation,
                ))
        if not findings:
            continue
        findings.sort(key=lambda item: (item.start, item.end, item.rule_id))
        candidates.append(TaiwanUsageCandidate(
            candidate_id=_candidate_id(uid),
            content_uid=uid,
            source_text=source_records.get(uid, ""),
            target_text=target_text,
            findings=tuple(findings),
            protected_tokens=_review_protected_tokens(target_text),
        ))
    return tuple(candidates)


def _surface_row(candidate: TaiwanUsageCandidate) -> dict[str, str]:
    return {
        "CandidateId": candidate.candidate_id,
        "ContentUid": candidate.content_uid,
        "SourceText": candidate.source_text,
        "TargetText": candidate.target_text,
        "FindingCount": str(candidate.finding_count),
        "Findings": _json_cell([asdict(item) for item in candidate.findings]),
        "ProtectedTokens": _json_cell(list(candidate.protected_tokens)),
        "ReviewerDecision": TaiwanUsageDecision.PENDING.value,
        "ReviewerNote": "",
        "ProposedText": "",
        "ValidationStatus": "NotChecked",
    }


def prepare_taiwan_usage_review(
    *, extract_manifest: Path, rules_path: Path, output_dir: Path,
) -> dict[str, Any]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"Output directory must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    source, target, references, locales = load_locales(extract_manifest)
    rules = load_taiwan_usage_rules(rules_path)
    candidates = candidates_from_target(
        source_records=locales[source],
        target_records=locales[target],
        rules=rules,
    )

    review_path = output_dir / "taiwan-usage-review.csv"
    _write_csv(review_path, REVIEW_COLUMNS, [_surface_row(item) for item in candidates])

    category_counts: dict[str, int] = {}
    rule_counts: dict[str, int] = {}
    for candidate in candidates:
        for finding in candidate.findings:
            category_counts[finding.category] = category_counts.get(finding.category, 0) + 1
            rule_counts[finding.rule_id] = rule_counts.get(finding.rule_id, 0) + 1

    manifest = {
        "schemaVersion": "1.0",
        "packageType": "TaiwanUsageReviewPackage",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "sourceLocale": source,
        "targetLocale": target,
        "referenceLocales": list(references),
        "ruleId": RULE_TAIWAN_USAGE_REVIEW,
        "generationInputs": {
            "currentSourceLocale": True,
            "currentTargetLocale": True,
            "reviewerSuppliedRuleSet": True,
            "historicalWorkbook": False,
            "historicalUidList": False,
            "historicalReviewDecision": False,
            "bundledTaiwanLexicon": False,
        },
        "sourceEvidence": {
            "extractManifest": str(extract_manifest),
            "ruleSet": str(rules_path),
            "ruleSetSha256": _sha256(rules_path),
        },
        "counts": {
            "total": len(candidates),
            "findings": sum(item.finding_count for item in candidates),
            "categories": category_counts,
            "rules": rule_counts,
        },
        "artifacts": [
            {"kind": "review", "path": str(review_path), "sha256": _sha256(review_path)}
        ],
        "rules": [asdict(item) for item in rules],
        "candidates": [item.to_dict() for item in candidates],
    }
    SchemaStore().validate("taiwan-usage-review-package.schema.json", manifest)
    manifest_path = output_dir / "taiwan-usage-review-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _expected_row(raw: dict[str, Any]) -> dict[str, str]:
    return {
        "CandidateId": str(raw["candidate_id"]),
        "ContentUid": str(raw["content_uid"]),
        "SourceText": str(raw["source_text"]),
        "TargetText": str(raw["target_text"]),
        "FindingCount": str(raw["finding_count"]),
        "Findings": _json_cell(raw.get("findings", [])),
        "ProtectedTokens": _json_cell(raw.get("protected_tokens", [])),
    }


def validate_taiwan_usage_review(
    *, input_path: Path, manifest_path: Path, output_dir: Path,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {item["candidate_id"]: _expected_row(item) for item in manifest.get("candidates", [])}
    output_dir.mkdir(parents=True, exist_ok=True)
    findings: list[dict[str, Any]] = []
    reviewed: list[dict[str, str]] = []
    seen: set[str] = set()

    with input_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        for row_number, row in enumerate(reader, 2):
            record = row.get("CandidateId") or f"row {row_number}"
            if record in seen:
                findings.append({"code": "TWU002", "record": record, "row": row_number, "message": "duplicate CandidateId"})
            seen.add(record)
            exp = expected.get(record)
            if exp is None:
                findings.append({"code": "TWU001", "record": record, "row": row_number, "message": "unknown CandidateId"})
                continue
            for column in _IMMUTABLE_COLUMNS:
                if str(row.get(column, "")) != exp[column]:
                    findings.append({"code": "TWU003", "record": record, "row": row_number, "message": f"immutable evidence changed: {column}"})

            decision = str(row.get("ReviewerDecision", ""))
            if decision not in {item.value for item in TaiwanUsageDecision}:
                findings.append({"code": "TWU004", "record": record, "row": row_number, "message": f"invalid decision: {decision}"})
            proposed = str(row.get("ProposedText", ""))
            if decision == TaiwanUsageDecision.REVISE.value and not proposed:
                findings.append({"code": "TWU005", "record": record, "row": row_number, "message": "Revise decision requires ProposedText"})
            if proposed:
                try:
                    protected = json.loads(exp["ProtectedTokens"])
                except json.JSONDecodeError:
                    protected = []
                syntax_issues = validate_protected_syntax(protected, proposed)
                if syntax_issues:
                    details = "; ".join(
                        f"{issue.kind}: {', '.join(issue.details)}" if issue.details else issue.kind
                        for issue in syntax_issues
                    )
                    findings.append({"code": "TWU006", "record": record, "row": row_number, "message": details})
            reviewed.append(dict(row))

    for missing in sorted(set(expected) - seen):
        findings.append({"code": "TWU007", "record": missing, "message": "candidate missing from completed review"})

    reviewed_path = output_dir / "taiwan-usage-reviewed.csv"
    if reviewed:
        _write_csv(reviewed_path, list(reviewed[0].keys()), reviewed)
    else:
        reviewed_path.write_text("", encoding="utf-8")
    result = {
        "status": "passed" if not findings else "failed",
        "findingCount": len(findings),
        "findings": findings,
        "reviewedOutput": str(reviewed_path),
    }
    (output_dir / "taiwan-usage-review-validation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result
