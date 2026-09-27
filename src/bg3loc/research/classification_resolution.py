from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from bg3loc.research.batching import DEFAULT_MAX_RECORDS


ACTION_ASSIGN = "assign"
ACTION_EXCLUDE = "exclude"
ACTION_PENDING = "pending"
ALLOWED_ASSIGN_CATEGORIES = frozenset(DEFAULT_MAX_RECORDS)


@dataclass(frozen=True, slots=True)
class ResolutionSummary:
    total_unresolved_input: int
    assigned: int
    excluded: int
    pending: int
    unresolved_without_decision: int
    output_sha256: str


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_no, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSONL at {path}:{line_no}: {exc}") from exc
            if not isinstance(value, dict):
                raise RuntimeError(f"expected JSON object at {path}:{line_no}")
            rows.append(value)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_unclassified(
    *,
    classification_path: str | Path,
    decisions_path: str | Path,
    output_path: str | Path,
) -> ResolutionSummary:
    classification_file = Path(classification_path)
    decisions_file = Path(decisions_path)
    output_file = Path(output_path)
    if not classification_file.is_file():
        raise RuntimeError(f"classification ledger not found: {classification_file}")
    if not decisions_file.is_file():
        raise RuntimeError(f"decision file not found: {decisions_file}")

    classification = _read_jsonl(classification_file)
    decisions = _read_jsonl(decisions_file)

    by_uid: dict[str, dict[str, Any]] = {}
    unresolved: set[str] = set()
    for row in classification:
        uid = str(row.get("contentUid", ""))
        if not uid:
            raise RuntimeError("classification row missing contentUid")
        if uid in by_uid:
            raise RuntimeError(f"duplicate ContentUid in classification ledger: {uid}")
        by_uid[uid] = row
        if str(row.get("classificationStatus", "")) != "classified" or str(row.get("primaryCategory", "")) == "other":
            unresolved.add(uid)

    decision_by_uid: dict[str, dict[str, Any]] = {}
    for row in decisions:
        uid = str(row.get("ContentUid", row.get("contentUid", "")))
        if not uid:
            raise RuntimeError("decision row missing ContentUid")
        if uid in decision_by_uid:
            raise RuntimeError(f"duplicate ContentUid in decision file: {uid}")
        if uid not in by_uid:
            raise RuntimeError(f"decision ContentUid not found in classification ledger: {uid}")
        if uid not in unresolved:
            raise RuntimeError(f"decision ContentUid is not unresolved: {uid}")

        action = str(row.get("action", "")).strip().casefold()
        if action not in {ACTION_ASSIGN, ACTION_EXCLUDE, ACTION_PENDING}:
            raise RuntimeError(f"unsupported decision action for {uid}: {action}")
        reviewer = str(row.get("reviewer", "")).strip()
        note = str(row.get("note", "")).strip()
        decided_at = str(row.get("decidedAt", "")).strip()
        if action in {ACTION_ASSIGN, ACTION_EXCLUDE} and not reviewer:
            raise RuntimeError(f"reviewer is required for {action}: {uid}")
        if action in {ACTION_ASSIGN, ACTION_EXCLUDE} and not decided_at:
            raise RuntimeError(f"decidedAt is required for {action}: {uid}")

        category = str(row.get("category", "")).strip()
        if action == ACTION_ASSIGN:
            if category not in ALLOWED_ASSIGN_CATEGORIES:
                allowed = ", ".join(sorted(ALLOWED_ASSIGN_CATEGORIES))
                raise RuntimeError(f"invalid assigned category for {uid}: {category}; allowed: {allowed}")
        elif category:
            raise RuntimeError(f"category is only valid for assign decisions: {uid}")

        decision_by_uid[uid] = {
            "action": action,
            "category": category,
            "reviewer": reviewer,
            "note": note,
            "decidedAt": decided_at,
        }

    assigned = excluded = pending = 0
    output_rows: list[dict[str, Any]] = []
    for uid in sorted(by_uid, key=str.casefold):
        source = by_uid[uid]
        row = dict(source)
        decision = decision_by_uid.get(uid)
        if decision is None:
            output_rows.append(row)
            continue

        action = str(decision["action"])
        row["resolution"] = {
            "action": action,
            "reviewer": decision["reviewer"],
            "note": decision["note"],
            "decidedAt": decision["decidedAt"],
            "sourceClassificationStatus": str(source.get("classificationStatus", "")),
            "sourcePrimaryCategory": str(source.get("primaryCategory", "")),
        }
        if action == ACTION_ASSIGN:
            row["primaryCategory"] = decision["category"]
            row["classificationStatus"] = "classified"
            assigned += 1
        elif action == ACTION_EXCLUDE:
            row["primaryCategory"] = "other"
            row["classificationStatus"] = "excluded"
            excluded += 1
        else:
            pending += 1
        output_rows.append(row)

    _write_jsonl(output_file, output_rows)
    unresolved_without_decision = len(unresolved - set(decision_by_uid))
    return ResolutionSummary(
        total_unresolved_input=len(unresolved),
        assigned=assigned,
        excluded=excluded,
        pending=pending,
        unresolved_without_decision=unresolved_without_decision,
        output_sha256=_sha256_file(output_file),
    )