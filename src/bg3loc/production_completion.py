from __future__ import annotations

from contextlib import closing, nullcontext, ExitStack
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import hashlib
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
    dialogue_context_required: bool = False,
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
    elif dialogue_context_required and (qa_result.execution_input_hash != str(execution_state.get("input_hash") or "")
            or hashlib.sha256(str(translated_text).encode("utf-8")).hexdigest() != output_hash):
        disposition = DISPOSITION_BLOCKED
        reason_code = REASON_QA_STALE
    elif dialogue_context_required and qa_result.route in {QA_ROUTE_PASS, QA_ROUTE_REVIEW} and (
            qa_result.route != QA_ROUTE_REVIEW or not _semantic_gate_present(qa_result.issues)):
        disposition = DISPOSITION_BLOCKED
        reason_code = "DIALOGUE_REVIEW_GATE_NOT_APPLIED"
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


def _semantic_gate_present(issues) -> bool:
    from bg3loc.dialogue_review import semantic_gate_present
    return semantic_gate_present(issues)

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
    from bg3loc.dialogue_execution_contract import material_workspace_version, guard_material_family
    manifest_version = material_workspace_version(batch_plan_path)
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
                guard_material_family(row, manifest_version)
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
    stage3_validation_only: bool = False,
    _connection: sqlite3.Connection | None = None,
) -> ProductionCompletionView:
    db = Path(db_path)
    plan = Path(batch_plan_path)
    if not db.is_file():
        raise RuntimeError(f"execution database not found: {db}")

    # Completion/bridge are public entry points too. A sealed context workspace
    # must not bypass the material/current-input gate used by execute/finalize.
    manifest_path = plan.parent.parent / "production-manifest.json"
    context_workspace_verified = False
    from bg3loc.dialogue_review import is_dialogue_workspace, validated_stage3_material
    validated = None
    if is_dialogue_workspace(db,_connection=_connection):
        validated = validated_stage3_material(db, batch_plan=plan, validation_only=stage3_validation_only,_connection=_connection)
        context_workspace_verified = True
    if manifest_path.is_file():
        declared = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if declared.get("schemaVersion") == "1.2":
            from bg3loc.production_workspace import verify_production_workspace
            binding = verify_production_workspace(manifest_path.parent)
            if binding.database.resolve() != db.resolve() or binding.batch_plan.resolve() != plan.resolve():
                raise RuntimeError("completion paths do not match sealed context workspace")
            context_workspace_verified = True

    material_index = _load_material_index(plan)

    conn = _connection if _connection is not None else sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    with ExitStack() as sources, closing(conn) if _connection is None else nullcontext(conn):
        if _connection is None:
            conn.execute("BEGIN")
        legacy = None
        if validated is None:
            from bg3loc.legacy_qa_material import LegacyQaMaterial
            try:
                legacy = sources.enter_context(LegacyQaMaterial(db, plan, connection=conn))
            except (ValueError, KeyError, OSError):
                pass  # No current QA can be certified from invalid material.
        bound_required = requires_input_binding(conn)
        if bound_required and not context_workspace_verified:
            raise RuntimeError("context completion requires its sealed production workspace")
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
        issues_by_uid = {}
        if validated is not None and conn.execute("SELECT 1 FROM sqlite_master WHERE name='qa_issues'").fetchone():
            for issue in conn.execute("SELECT content_uid,issue_code,severity,action,message,details_json FROM qa_issues ORDER BY content_uid,ordinal"):
                issues_by_uid.setdefault(str(issue[0]), []).append({"issueCode":issue[1],"severity":issue[2],"action":issue[3],"message":issue[4],"details":tuple(json.loads(issue[5]))})
        review_table = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='qa_review_resolutions'"
        ).fetchone()
        if review_table is not None:
            review_binding = stored_input_binding_expression(conn, "qa_review_resolutions")
            review_acceptance_rows = conn.execute(
                f"""
                SELECT content_uid, decision, qa_rule_set_version, qa_input_hash,
                       base_output_hash, resolved_output_hash, {review_binding} AS execution_input_hash
                FROM qa_review_resolutions
                WHERE decision IN ('ACCEPT', 'REVISE')
                ORDER BY resolution_id
                """
            ).fetchall()

        legacy_current = {}
        if validated is None and legacy is not None:
            qa_lookup = {str(q['content_uid']): q for q in qa_rows}
            for state in execution_rows:
                uid = str(state['content_uid'])
                q = qa_lookup.get(uid)
                try:
                    legacy_current[uid] = q is not None and legacy.current(uid, state, q['qa_input_hash'])
                except (ValueError, KeyError):
                    legacy_current[uid] = False

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
            str(row["resolved_output_hash"]),
        )
        for row in review_acceptance_rows
        if input_binding_current(row["execution_input_hash"], str(execution_by_uid.get(str(row["content_uid"]), {}).get("input_hash", "")), required=bound_required)
        and (row["decision"] == "REVISE" or row["base_output_hash"] == row["resolved_output_hash"])
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
            if validated is not None and (type(state.get("translated_text")) is not str
                    or hashlib.sha256(state["translated_text"].encode("utf-8")).hexdigest()!=current_output_hash):
                # Every family in 1.3 must bind the actual output bytes, even
                # when a corrupt writer leaves its declared hash unchanged.
                qa_status = QA_STATUS_STALE
            if validated is None and not legacy_current.get(uid, False):
                qa_status = QA_STATUS_STALE

            qa_result = StoredQaResult(
                content_uid=uid,
                qa_status=qa_status,
                route=str(qa_row["route"]),
                issue_count=len(issues_by_uid.get(uid, ())),
                qa_rule_set_version=str(qa_row["qa_rule_set_version"]),
                qa_input_hash=str(qa_row["qa_input_hash"]),
                output_hash=qa_output_hash,
                checked_at=str(qa_row["checked_at"]),
                issues=tuple(issues_by_uid.get(uid, ())),
                execution_input_hash=qa_row["execution_input_hash"],
            )

        current_output_hash = str(state.get("output_hash") or "")
        human_review_accepted = (
            uid,
            current_rule_set_version,
            qa_result.qa_input_hash if qa_result is not None else "",
            current_output_hash,
        ) in review_acceptances

        disposition = derive_production_disposition(
            state,
            primary_category=category,
            qa_result=qa_result,
            human_review_accepted=human_review_accepted,
            dialogue_context_required=validated is not None and "dialogueContext" in validated[uid],
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
