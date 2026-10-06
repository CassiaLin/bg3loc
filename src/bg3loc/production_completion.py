from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Mapping

from bg3loc.execution_state import (
    STATUS_FAILED_FINAL,
    STATUS_FAILED_RETRYABLE,
    STATUS_INVALIDATED,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_SKIPPED,
    STATUS_SUCCEEDED,
)
from bg3loc.qa import QA_ROUTE_FAIL, QA_ROUTE_PASS, QA_ROUTE_RETRY, QA_ROUTE_REVIEW, QA_RULESET_VERSION
from bg3loc.qa_state import QA_STATUS_CHECKED, QA_STATUS_STALE, StoredQaResult, input_binding_current, requires_input_binding, stored_input_binding_expression


DISPOSITION_MERGE_READY = "MERGE_READY"
DISPOSITION_WAITING_TRANSLATION = "WAITING_TRANSLATION"
DISPOSITION_WAITING_RETRY = "WAITING_RETRY"
DISPOSITION_WAITING_REVIEW = "WAITING_REVIEW"
DISPOSITION_BLOCKED = "BLOCKED"

REASON_READY = "READY"
REASON_PENDING = "EXECUTION_PENDING"
REASON_RUNNING = "EXECUTION_RUNNING"
REASON_INVALIDATED = "EXECUTION_INVALIDATED"
REASON_RETRYABLE = "EXECUTION_FAILED_RETRYABLE"
REASON_FAILED_FINAL = "EXECUTION_FAILED_FINAL"
REASON_SKIPPED = "EXECUTION_SKIPPED"
REASON_MISSING_OUTPUT = "SUCCEEDED_OUTPUT_MISSING"
REASON_QA_MISSING = "QA_RESULT_MISSING"
REASON_QA_STALE = "QA_RESULT_STALE"
REASON_QA_OUTPUT_MISMATCH = "QA_OUTPUT_MISMATCH"
REASON_QA_RETRY = "QA_RETRY"
REASON_QA_REVIEW = "QA_REVIEW"
REASON_HUMAN_REVIEW_ACCEPTED = "HUMAN_REVIEW_ACCEPTED"
REASON_QA_FAIL = "QA_FAIL"
REASON_UNKNOWN_QA_ROUTE = "QA_ROUTE_UNKNOWN"
REASON_UNKNOWN_EXECUTION_STATUS = "EXECUTION_STATUS_UNKNOWN"


@dataclass(frozen=True, slots=True)
class ProductionDisposition:
    content_uid: str
    primary_category: str
    batch_id: str
    execution_status: str
    qa_status: str | None
    qa_route: str | None
    disposition: str
    reason_code: str
    last_attempt_id: int | None
    attempt_count: int


def derive_production_disposition(
    execution_state: Mapping[str, object],
    *,
    primary_category: str,
    qa_result: StoredQaResult | None,
    human_review_accepted: bool = False,
) -> ProductionDisposition:
    content_uid = str(execution_state.get("content_uid") or "")
    batch_id = str(execution_state.get("batch_id") or "")
    status = str(execution_state.get("status") or "")
    translated_text = execution_state.get("translated_text")
    output_hash = str(execution_state.get("output_hash") or "")
    last_attempt_raw = execution_state.get("last_attempt_id")
    last_attempt_id = int(last_attempt_raw) if last_attempt_raw is not None else None
    attempt_count = int(execution_state.get("attempt_count") or 0)

    qa_status = qa_result.qa_status if qa_result is not None else None
    qa_route = qa_result.route if qa_result is not None else None

    disposition: str
    reason_code: str

    if status == STATUS_PENDING:
        disposition = DISPOSITION_WAITING_TRANSLATION
        reason_code = REASON_PENDING
    elif status == STATUS_RUNNING:
        disposition = DISPOSITION_WAITING_TRANSLATION
        reason_code = REASON_RUNNING
    elif status == STATUS_INVALIDATED:
        disposition = DISPOSITION_WAITING_TRANSLATION
        reason_code = REASON_INVALIDATED
    elif status == STATUS_FAILED_RETRYABLE:
        disposition = DISPOSITION_WAITING_RETRY
        reason_code = REASON_RETRYABLE
    elif status == STATUS_FAILED_FINAL:
        disposition = DISPOSITION_BLOCKED
        reason_code = REASON_FAILED_FINAL
    elif status == STATUS_SKIPPED:
        disposition = DISPOSITION_BLOCKED
        reason_code = REASON_SKIPPED
    elif status != STATUS_SUCCEEDED:
        disposition = DISPOSITION_BLOCKED
        reason_code = REASON_UNKNOWN_EXECUTION_STATUS
    elif translated_text is None or not output_hash:
        disposition = DISPOSITION_BLOCKED
        reason_code = REASON_MISSING_OUTPUT
    elif qa_result is None:
        disposition = DISPOSITION_BLOCKED
        reason_code = REASON_QA_MISSING
    elif qa_result.qa_status == QA_STATUS_STALE:
        disposition = DISPOSITION_BLOCKED
        reason_code = REASON_QA_STALE
    elif qa_result.qa_status != QA_STATUS_CHECKED:
        disposition = DISPOSITION_BLOCKED
        reason_code = REASON_QA_STALE
    elif qa_result.output_hash != output_hash:
        disposition = DISPOSITION_BLOCKED
        reason_code = REASON_QA_OUTPUT_MISMATCH
    elif qa_result.route == QA_ROUTE_PASS:
        disposition = DISPOSITION_MERGE_READY
        reason_code = REASON_READY
    elif qa_result.route == QA_ROUTE_RETRY:
        disposition = DISPOSITION_WAITING_RETRY
        reason_code = REASON_QA_RETRY
    elif qa_result.route == QA_ROUTE_REVIEW and human_review_accepted:
        disposition = DISPOSITION_MERGE_READY
        reason_code = REASON_HUMAN_REVIEW_ACCEPTED
    elif qa_result.route == QA_ROUTE_REVIEW:
        disposition = DISPOSITION_WAITING_REVIEW
        reason_code = REASON_QA_REVIEW
    elif qa_result.route == QA_ROUTE_FAIL:
        disposition = DISPOSITION_BLOCKED
        reason_code = REASON_QA_FAIL
    else:
        disposition = DISPOSITION_BLOCKED
        reason_code = REASON_UNKNOWN_QA_ROUTE

    return ProductionDisposition(
        content_uid=content_uid,
        primary_category=primary_category,
        batch_id=batch_id,
        execution_status=status,
        qa_status=qa_status,
        qa_route=qa_route,
        disposition=disposition,
        reason_code=reason_code,
        last_attempt_id=last_attempt_id,
        attempt_count=attempt_count,
    )

@dataclass(frozen=True, slots=True)
class ProductionCompletionView:
    rows: tuple[ProductionDisposition, ...]
    counts: dict[str, int]
    by_category: dict[str, dict[str, int]]

    @property
    def total(self) -> int:
        return len(self.rows)


def _load_material_index(batch_plan_path: Path) -> dict[str, tuple[str, str]]:
    if not batch_plan_path.is_file():
        raise RuntimeError(f"batch plan not found: {batch_plan_path}")

    with batch_plan_path.open("r", encoding="utf-8") as handle:
        plan = json.load(handle)

    batches = plan.get("batches", [])
    if not isinstance(batches, list):
        raise RuntimeError("batch plan batches must be a list")

    index: dict[str, tuple[str, str]] = {}
    seen_batches: set[str] = set()

    for batch in batches:
        if not isinstance(batch, dict):
            raise RuntimeError("batch plan contains a non-object batch")
        batch_id = str(batch.get("batchId", ""))
        category = str(batch.get("primaryCategory", ""))
        if not batch_id:
            raise RuntimeError("batch plan contains a batch without batchId")
        if batch_id in seen_batches:
            raise RuntimeError(f"duplicate batchId in batch plan: {batch_id}")
        seen_batches.add(batch_id)
        if not category:
            raise RuntimeError(f"batch plan batch missing primaryCategory: {batch_id}")

        material_path = batch_plan_path.parent / "materials" / f"{batch_id}.jsonl"
        if not material_path.is_file():
            raise RuntimeError(f"batch material not found: {material_path}")

        count = 0
        with material_path.open("r", encoding="utf-8-sig") as material:
            for line_no, line in enumerate(material, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise RuntimeError(f"{material_path}:{line_no}: expected JSON object")
                uid = str(row.get("ContentUid", row.get("contentUid", "")))
                if not uid:
                    raise RuntimeError(f"{material_path}:{line_no}: missing ContentUid")
                row_batch = str(row.get("batchId", batch_id))
                row_category = str(row.get("primaryCategory", category))
                if row_batch != batch_id:
                    raise RuntimeError(
                        f"{material_path}:{line_no}: batchId mismatch: {row_batch} != {batch_id}"
                    )
                if row_category != category:
                    raise RuntimeError(
                        f"{material_path}:{line_no}: primaryCategory mismatch: "
                        f"{row_category} != {category}"
                    )
                if uid in index:
                    raise RuntimeError(f"duplicate ContentUid across batch materials: {uid}")
                index[uid] = (batch_id, category)
                count += 1

        expected = int(batch.get("recordCount", 0) or 0)
        if expected and count != expected:
            raise RuntimeError(
                f"batch material count mismatch for {batch_id}: "
                f"plan={expected}, materialRows={count}"
            )

    return index


def build_production_completion_view(
    db_path: str | Path,
    batch_plan_path: str | Path,
    *,
    current_rule_set_version: str = QA_RULESET_VERSION,
) -> ProductionCompletionView:
    db = Path(db_path)
    plan = Path(batch_plan_path)
    if not db.is_file():
        raise RuntimeError(f"execution database not found: {db}")

    material_index = _load_material_index(plan)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    with closing(conn):
        bound_required = requires_input_binding(conn)
        execution_rows = conn.execute(
            "SELECT * FROM content_state ORDER BY batch_id, content_uid"
        ).fetchall()
        try:
            qa_binding = stored_input_binding_expression(conn, "qa_results")
            qa_rows = conn.execute(
                f"""
                SELECT
                    content_uid,
                    route,
                    qa_rule_set_version,
                    qa_input_hash,
                    output_hash,
                    checked_at, {qa_binding} AS execution_input_hash
                FROM qa_results
                ORDER BY content_uid
                """
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table: qa_results" not in str(exc):
                raise
            qa_rows = []

        review_acceptance_rows = []
        review_table = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='qa_review_resolutions'"
        ).fetchone()
        if review_table is not None:
            review_binding = stored_input_binding_expression(conn, "qa_review_resolutions")
            review_acceptance_rows = conn.execute(
                f"""
                SELECT content_uid, qa_rule_set_version, qa_input_hash,
                       base_output_hash, resolved_output_hash, {review_binding} AS execution_input_hash
                FROM qa_review_resolutions
                WHERE decision = 'ACCEPT'
                ORDER BY resolution_id
                """
            ).fetchall()

    execution_by_uid = {
        str(row["content_uid"]): dict(row)
        for row in execution_rows
    }

    execution_uids = set(execution_by_uid)
    material_uids = set(material_index)

    missing_state = sorted(material_uids - execution_uids)
    if missing_state:
        raise RuntimeError(
            f"execution state missing ContentUid from batch material: {missing_state[0]}"
        )

    foreign_state = sorted(execution_uids - material_uids)
    if foreign_state:
        raise RuntimeError(
            f"execution state contains ContentUid outside batch material: {foreign_state[0]}"
        )

    qa_by_uid = {str(row["content_uid"]): row for row in qa_rows}
    review_acceptances = {
        (
            str(row["content_uid"]),
            str(row["qa_rule_set_version"]),
            str(row["qa_input_hash"]),
            str(row["base_output_hash"]),
            str(row["resolved_output_hash"]),
        )
        for row in review_acceptance_rows
        if input_binding_current(row["execution_input_hash"], str(execution_by_uid.get(str(row["content_uid"]), {}).get("input_hash", "")), required=bound_required)
    }

    rows: list[ProductionDisposition] = []
    counts = {
        DISPOSITION_MERGE_READY: 0,
        DISPOSITION_WAITING_TRANSLATION: 0,
        DISPOSITION_WAITING_RETRY: 0,
        DISPOSITION_WAITING_REVIEW: 0,
        DISPOSITION_BLOCKED: 0,
    }
    by_category: dict[str, dict[str, int]] = {}

    for uid in sorted(material_index):
        expected_batch_id, category = material_index[uid]
        state = execution_by_uid[uid]
        actual_batch_id = str(state.get("batch_id") or "")
        if actual_batch_id != expected_batch_id:
            raise RuntimeError(
                f"execution batchId mismatch for {uid}: "
                f"{actual_batch_id} != {expected_batch_id}"
            )

        qa_row = qa_by_uid.get(uid)
        qa_result: StoredQaResult | None = None
        if qa_row is not None:
            qa_output_hash = str(qa_row["output_hash"] or "")
            current_output_hash = str(state.get("output_hash") or "")
            qa_status = QA_STATUS_CHECKED
            if (
                qa_output_hash != current_output_hash
                or str(qa_row["qa_rule_set_version"]) != current_rule_set_version
                or not input_binding_current(qa_row["execution_input_hash"], str(state["input_hash"]), required=bound_required)
            ):
                qa_status = QA_STATUS_STALE

            qa_result = StoredQaResult(
                content_uid=uid,
                qa_status=qa_status,
                route=str(qa_row["route"]),
                issue_count=0,
                qa_rule_set_version=str(qa_row["qa_rule_set_version"]),
                qa_input_hash=str(qa_row["qa_input_hash"]),
                output_hash=qa_output_hash,
                checked_at=str(qa_row["checked_at"]),
                issues=(),
            )

        current_output_hash = str(state.get("output_hash") or "")
        human_review_accepted = (
            uid,
            current_rule_set_version,
            qa_result.qa_input_hash if qa_result is not None else "",
            current_output_hash,
            current_output_hash,
        ) in review_acceptances

        disposition = derive_production_disposition(
            state,
            primary_category=category,
            qa_result=qa_result,
            human_review_accepted=human_review_accepted,
        )
        rows.append(disposition)
        counts[disposition.disposition] += 1

        category_counts = by_category.setdefault(
            category,
            {
                DISPOSITION_MERGE_READY: 0,
                DISPOSITION_WAITING_TRANSLATION: 0,
                DISPOSITION_WAITING_RETRY: 0,
                DISPOSITION_WAITING_REVIEW: 0,
                DISPOSITION_BLOCKED: 0,
            },
        )
        category_counts[disposition.disposition] += 1

    return ProductionCompletionView(
        rows=tuple(rows),
        counts=counts,
        by_category={
            category: by_category[category]
            for category in sorted(by_category)
        },
    )
