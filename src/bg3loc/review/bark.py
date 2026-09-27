from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Sequence

from bg3loc.protected_syntax import extract_protected_tokens, validate_protected_syntax
from bg3loc.schema import SchemaStore


class BarkReviewDecision(str, Enum):
    PENDING = "Pending"
    APPROVED = "Approved"
    NEEDS_REVISION = "NeedsRevision"
    INSUFFICIENT_EVIDENCE = "InsufficientEvidence"
    NOT_APPLICABLE = "NotApplicable"


@dataclass(frozen=True, slots=True)
class BarkSpeakerMember:
    identity: str
    provenance: str


@dataclass(frozen=True, slots=True)
class BarkReviewEvidence:
    rule: str
    source_role: str
    evidence_type: str
    pak_name: str
    internal_path: str
    node_id: str
    entity_identity: str
    speaker_slot: str


@dataclass(frozen=True, slots=True)
class BarkReviewCandidate:
    candidate_id: str
    content_uid: str
    english_text: str
    speaker_mode: str
    speakers: tuple[BarkSpeakerMember, ...]
    shared_group_id: str
    evidence: BarkReviewEvidence
    context_summary: str
    protected_tokens: tuple[str, ...]

    @property
    def speaker_count(self) -> int:
        return len(self.speakers)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["speakers"] = [asdict(member) for member in self.speakers]
        result["protected_tokens"] = list(self.protected_tokens)
        result["speaker_count"] = self.speaker_count
        return result


@dataclass(frozen=True, slots=True)
class BarkReviewPackage:
    candidates: tuple[BarkReviewCandidate, ...]
    source_locale: str
    target_locale: str
    reference_locales: tuple[str, ...] = ()
    authorities: dict[str, dict[str, str]] = field(default_factory=dict)


PASS1_COLUMNS = (
    "CandidateId", "ContentUid", "EnglishText", "SpeakerMode", "SpeakerCount",
    "Speakers", "SpeakerEvidence", "SharedGroupId", "PakName", "InternalPath",
    "NodeId", "EntityIdentity", "EvidenceRule", "ContextSummary", "ProtectedTokens",
    "ReviewerDecision", "ReviewerNote", "EvidenceSufficient", "DraftText", "ValidationStatus",
)
PASS2_COLUMNS = PASS1_COLUMNS + (
    "OfficialTarget", "ReferenceComparison", "ApprovedAuthority", "FinalDecision",
    "FinalText", "FinalValidationStatus",
)
_IMMUTABLE_COLUMNS = (
    "CandidateId", "ContentUid", "EnglishText", "SpeakerMode", "SpeakerCount", "Speakers",
    "SpeakerEvidence", "SharedGroupId", "PakName", "InternalPath", "NodeId",
    "EntityIdentity", "EvidenceRule", "ContextSummary", "ProtectedTokens",
)
_PASS1_FORBIDDEN = {"OfficialTarget", "ReferenceComparison", "ApprovedAuthority", "FinalDecision", "FinalText"}
_LSTAG_TOKEN_RE = re.compile(r"<\s*(/?)\s*LSTag\b([^>]*)>", re.IGNORECASE)


def _candidate_id(content_uid: str) -> str:
    digest = hashlib.sha256(content_uid.casefold().encode("utf-8")).hexdigest()[:16].upper()
    return f"BARK-{digest}"


def _json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _review_protected_tokens(text: str) -> tuple[str, ...]:
    tokens = list(extract_protected_tokens(text))
    for match in _LSTAG_TOKEN_RE.finditer(text):
        closing, attributes = match.groups()
        if closing:
            tokens.append("</LSTag>")
        elif attributes.strip().endswith("/"):
            tokens.append("<LSTag/>")
        else:
            tokens.append("<LSTag>")
    return tuple(tokens)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected JSON object")
            rows.append(value)
    return rows


def _path_from_manifest(manifest_path: Path, raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return manifest_path.parent / path


def load_locales(extract_manifest: Path) -> tuple[str, str, tuple[str, ...], dict[str, dict[str, str]]]:
    manifest = json.loads(extract_manifest.read_text(encoding="utf-8-sig"))
    source = str(manifest["sourceLocale"])
    target = str(manifest["targetLocale"])
    references = tuple(str(item) for item in manifest.get("referenceLocales", []))
    wanted = {source, target, *references}
    locales: dict[str, dict[str, str]] = {}
    for item in manifest.get("locales", []):
        locale = str(item.get("localeId", ""))
        if locale not in wanted:
            continue
        records_path = _path_from_manifest(extract_manifest, str(item["normalized"]))
        locales[locale] = {
            str(row.get("contentUid", "")): str(row.get("text", ""))
            for row in _read_jsonl(records_path)
        }
    missing = wanted - locales.keys()
    if missing:
        raise ValueError(f"Extract manifest is missing normalized locales: {', '.join(sorted(missing))}")
    return source, target, references, locales


def candidates_from_evidence(
    mappings: Iterable[dict[str, Any]], source_text: dict[str, str]
) -> tuple[BarkReviewCandidate, ...]:
    candidates: list[BarkReviewCandidate] = []
    for mapping in mappings:
        if mapping.get("mappingType") != "context-evidence" or mapping.get("classification") not in ("SingleSpeaker", "SharedSpeaker"):
            continue
        uid = str(mapping.get("contentUid", ""))
        raw_evidence = mapping.get("evidence") or []
        evidence = next(
            (item for item in raw_evidence if isinstance(item, dict) and item.get("evidenceType") == "BarkSpeakerStructure"),
            raw_evidence[0] if raw_evidence else {},
        )
        props = evidence.get("properties") or {}
        raw_members = props.get("speakerMembers") or mapping.get("metadata", {}).get("speakerMembers") or []
        members = tuple(
            BarkSpeakerMember(identity=str(item.get("identity", "")), provenance=str(item.get("provenance", "")))
            for item in raw_members if isinstance(item, dict)
        )
        mode = str(mapping.get("classification"))
        path = str(evidence.get("resourcePath", ""))
        pak = str(props.get("pakName", ""))
        node = str(props.get("nodeUuid", mapping.get("metadata", {}).get("nodeUuid", "")))
        entity = str(props.get("dialogUuid", mapping.get("metadata", {}).get("dialogUuid", "")))
        rule = str(evidence.get("ruleId", ""))
        speaker_slot = str(props.get("speakerSlot", mapping.get("metadata", {}).get("speakerSlot", "")))
        group_id = str(props.get("sharedGroupId", mapping.get("metadata", {}).get("sharedGroupId", "")))
        text = source_text.get(uid, "")
        summary = f"{mode}; {evidence.get('evidenceType', '')}; speaker slot {speaker_slot or 'ambiguous'}; {Path(path).name}"
        candidates.append(BarkReviewCandidate(
            candidate_id=_candidate_id(uid), content_uid=uid, english_text=text,
            speaker_mode=mode, speakers=members, shared_group_id=group_id,
            evidence=BarkReviewEvidence(
                rule=rule, source_role=str(evidence.get("sourceRole", "")),
                evidence_type=str(evidence.get("evidenceType", "")), pak_name=pak,
                internal_path=path, node_id=node, entity_identity=entity, speaker_slot=speaker_slot,
            ),
            context_summary=summary, protected_tokens=_review_protected_tokens(text),
        ))
    return tuple(sorted(candidates, key=lambda item: (item.content_uid.casefold(), item.candidate_id)))


def _surface_row(candidate: BarkReviewCandidate) -> dict[str, str]:
    speakers = [asdict(member) for member in candidate.speakers]
    evidence = asdict(candidate.evidence)
    return {
        "CandidateId": candidate.candidate_id, "ContentUid": candidate.content_uid,
        "EnglishText": candidate.english_text, "SpeakerMode": candidate.speaker_mode,
        "SpeakerCount": str(candidate.speaker_count), "Speakers": _json_cell(speakers),
        "SpeakerEvidence": _json_cell(evidence), "SharedGroupId": candidate.shared_group_id,
        "PakName": candidate.evidence.pak_name, "InternalPath": candidate.evidence.internal_path,
        "NodeId": candidate.evidence.node_id, "EntityIdentity": candidate.evidence.entity_identity,
        "EvidenceRule": candidate.evidence.rule, "ContextSummary": candidate.context_summary,
        "ProtectedTokens": _json_cell(list(candidate.protected_tokens)),
        "ReviewerDecision": BarkReviewDecision.PENDING.value, "ReviewerNote": "",
        "EvidenceSufficient": "", "DraftText": "", "ValidationStatus": "NotChecked",
    }


def _write_csv(path: Path, columns: Sequence[str], rows: Iterable[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prepare_bark_review(
    *, mappings_path: Path, extract_manifest: Path, output_dir: Path, include_pass2: bool = False
) -> dict[str, Any]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"Output directory must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    source, target, references, locales = load_locales(extract_manifest)
    candidates = candidates_from_evidence(_read_jsonl(mappings_path), locales[source])
    _validate_prepared_candidates(candidates)
    package = BarkReviewPackage(candidates, source, target, references, {
        target: locales[target], **{locale: locales[locale] for locale in references}
    })
    pass1_path = output_dir / "bark-review-pass1.csv"
    pass1_rows = [_surface_row(candidate) for candidate in candidates]
    _write_csv(pass1_path, PASS1_COLUMNS, pass1_rows)
    artifacts: list[dict[str, Any]] = [{"kind": "pass1", "path": str(pass1_path), "sha256": _sha256(pass1_path)}]
    if include_pass2:
        pass2_path = output_dir / "bark-review-pass2.csv"
        pass2_rows: list[dict[str, str]] = []
        for candidate, row in zip(candidates, pass1_rows, strict=True):
            refs = {locale: package.authorities[locale].get(candidate.content_uid, "") for locale in references}
            row2 = dict(row)
            row2.update({
                "OfficialTarget": package.authorities[target].get(candidate.content_uid, ""),
                "ReferenceComparison": _json_cell(refs), "ApprovedAuthority": "",
                "FinalDecision": BarkReviewDecision.PENDING.value, "FinalText": "",
                "FinalValidationStatus": "NotChecked",
            })
            pass2_rows.append(row2)
        _write_csv(pass2_path, PASS2_COLUMNS, pass2_rows)
        artifacts.append({"kind": "pass2", "path": str(pass2_path), "sha256": _sha256(pass2_path)})

    comparison_evidence = {
        candidate.candidate_id: {
            f"OfficialTarget:{target}": {
                "present": bool(package.authorities[target].get(candidate.content_uid, "")),
                "sha256": _text_sha256(package.authorities[target].get(candidate.content_uid, "")),
            },
            **{
                f"ReferenceLocale:{locale}": {
                    "present": bool(package.authorities[locale].get(candidate.content_uid, "")),
                    "sha256": _text_sha256(package.authorities[locale].get(candidate.content_uid, "")),
                }
                for locale in references
            },
        }
        for candidate in candidates
    }
    manifest = {
        "schemaVersion": "1.0", "packageType": "BarkReviewPackage",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "sourceLocale": source, "targetLocale": target, "referenceLocales": list(references),
        "generationInputs": {"gameEvidence": True, "historicalWorkbook": False, "historicalUidList": False, "historicalReviewDecision": False},
        "sourceEvidence": {"researchMappings": str(mappings_path), "extractManifest": str(extract_manifest)},
        "counts": {
            "total": len(candidates),
            "SingleSpeaker": sum(c.speaker_mode == "SingleSpeaker" for c in candidates),
            "SharedSpeaker": sum(c.speaker_mode == "SharedSpeaker" for c in candidates),
        },
        "allowedAuthorities": [f"OfficialTarget:{target}", *[f"ReferenceLocale:{locale}" for locale in references]],
        "artifacts": artifacts, "comparisonEvidence": comparison_evidence,
        "candidates": [candidate.to_dict() for candidate in candidates],
    }
    SchemaStore().validate("bark-review-package.schema.json", manifest)
    manifest_path = output_dir / "bark-review-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _validate_prepared_candidates(candidates: Sequence[BarkReviewCandidate]) -> None:
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
        ev = candidate.evidence
        if not ev.rule or not ev.internal_path or not ev.node_id or not ev.entity_identity:
            raise ValueError(f"{candidate.candidate_id}: missing evidence provenance")
        if any(not member.identity or not member.provenance for member in candidate.speakers):
            raise ValueError(f"{candidate.candidate_id}: incomplete speaker provenance")
        if candidate.speaker_mode == "SharedSpeaker" and (candidate.speaker_count < 2 or not candidate.shared_group_id):
            raise ValueError(f"{candidate.candidate_id}: SharedSpeaker membership is incomplete")


def _expected_row(raw: dict[str, Any]) -> dict[str, str]:
    evidence = raw["evidence"]
    speakers = raw.get("speakers", [])
    return {
        "CandidateId": str(raw["candidate_id"]), "ContentUid": str(raw["content_uid"]),
        "EnglishText": str(raw["english_text"]), "SpeakerMode": str(raw["speaker_mode"]),
        "SpeakerCount": str(raw["speaker_count"]), "Speakers": _json_cell(speakers),
        "SpeakerEvidence": _json_cell(evidence), "SharedGroupId": str(raw.get("shared_group_id", "")),
        "PakName": str(evidence["pak_name"]), "InternalPath": str(evidence["internal_path"]),
        "NodeId": str(evidence["node_id"]), "EntityIdentity": str(evidence["entity_identity"]),
        "EvidenceRule": str(evidence["rule"]), "ContextSummary": str(raw["context_summary"]),
        "ProtectedTokens": _json_cell(raw.get("protected_tokens", [])),
    }


def validate_bark_review(*, input_path: Path, manifest_path: Path, output_dir: Path) -> dict[str, Any]:
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
                findings.append({"code": "BRK006", "record": "<header>", "message": f"Pass 1 target-text leakage column: {column}"})
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
                issue("BRK001", "duplicate CandidateId")
            seen_ids.add(candidate_id)
            if content_uid in seen_uids:
                issue("BRK002", "duplicate ContentUid")
            seen_uids.add(content_uid)
            baseline = expected.get(candidate_id)
            if not content_uid:
                issue("BRK003", "missing ContentUid")
            if not row.get("EnglishText"):
                issue("BRK004", "missing English source")
            if not row.get("EvidenceRule") or not row.get("InternalPath") or not row.get("SpeakerEvidence"):
                issue("BRK005", "missing evidence provenance")
            if baseline is None:
                issue("BRK011", "CandidateId is not present in the package manifest")
            else:
                for column in _IMMUTABLE_COLUMNS:
                    if row.get(column, "") != baseline[column]:
                        code = "BRK009" if baseline["SpeakerMode"] == "SharedSpeaker" and column in ("SpeakerCount", "Speakers", "SharedGroupId") else "BRK011"
                        issue(code, f"immutable {column} changed")
            decisions = [("ReviewerDecision", row.get("ReviewerDecision", ""))]
            if is_pass2:
                decisions.append(("FinalDecision", row.get("FinalDecision", "")))
            for column, value in decisions:
                if value not in {item.value for item in BarkReviewDecision}:
                    issue("BRK007", f"invalid {column}: {value}")
            if row.get("EvidenceSufficient", "") not in ("", "true", "false", "TRUE", "FALSE"):
                issue("BRK008", "EvidenceSufficient must be true, false, or blank")
            authority = row.get("ApprovedAuthority", "")
            if authority and authority not in allowed_authorities:
                issue("BRK010", f"invalid ApprovedAuthority: {authority}")
            if is_pass2 and baseline is not None:
                comparisons: dict[str, str] = {
                    f"OfficialTarget:{manifest['targetLocale']}": row.get("OfficialTarget", "")
                }
                try:
                    references = json.loads(row.get("ReferenceComparison", "{}") or "{}")
                    if not isinstance(references, dict):
                        raise ValueError("not an object")
                except (json.JSONDecodeError, ValueError) as exc:
                    issue("BRK014", f"invalid ReferenceComparison JSON: {exc}")
                    references = {}
                comparisons.update({f"ReferenceLocale:{locale}": str(value) for locale, value in references.items()})
                expected_comparisons = comparison_evidence.get(candidate_id, {})
                for label, expected_value in expected_comparisons.items():
                    actual_text = comparisons.get(label, "")
                    if _text_sha256(actual_text) != expected_value.get("sha256"):
                        issue("BRK014", f"comparison evidence changed: {label}")
                if authority in allowed_authorities:
                    authority_evidence = expected_comparisons.get(authority, {})
                    if not authority_evidence.get("present"):
                        issue("BRK010", f"ApprovedAuthority has no evidence for this candidate: {authority}")
                    if row.get("FinalDecision") == BarkReviewDecision.PENDING.value:
                        issue("BRK010", "ApprovedAuthority cannot be recorded while FinalDecision is Pending")
            text_column = "FinalText" if is_pass2 else "DraftText"
            candidate_text = row.get(text_column, "")
            if candidate_text and baseline is not None:
                required = json.loads(baseline["ProtectedTokens"])
                exact_required = [token for token in required if not token.startswith("<LSTag") and token != "</LSTag>"]
                for syntax_issue in validate_protected_syntax(exact_required, candidate_text):
                    issue("BRK012", f"protected-token drift ({syntax_issue.kind}): {', '.join(syntax_issue.details)}")
                expected_lstag = [token for token in required if token.startswith("<LSTag") or token == "</LSTag>"]
                actual_lstag = [token for token in _review_protected_tokens(candidate_text) if token.startswith("<LSTag") or token == "</LSTag>"]
                if expected_lstag != actual_lstag:
                    issue("BRK012", f"protected-token drift (LSTag): expected {expected_lstag}, got {actual_lstag}")
            result_column = "FinalValidationStatus" if is_pass2 else "ValidationStatus"
            row[result_column] = "Failed" if row_findings else "Passed"
            reviewed.append(dict(row))

    for missing in sorted(expected.keys() - seen_ids):
        findings.append({"code": "BRK013", "record": missing, "message": "candidate missing from review input"})
    reviewed_path = output_dir / "bark-reviewed.csv"
    columns = PASS2_COLUMNS if reviewed and "FinalText" in reviewed[0] else PASS1_COLUMNS
    _write_csv(reviewed_path, columns, reviewed)
    result = {
        "schemaVersion": "1.0", "status": "failed" if findings else "passed",
        "input": str(input_path), "manifest": str(manifest_path),
        "recordCount": len(reviewed), "findingCount": len(findings), "findings": findings,
        "reviewedOutput": str(reviewed_path),
    }
    (output_dir / "bark-review-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
