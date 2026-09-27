from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json

from bg3loc.commands.qa_probe import register_probe
from pathlib import Path

from bg3loc.execution_state import STATUS_SUCCEEDED, TranslationExecutionStore
from bg3loc.protected_syntax import extract_protected_tokens
from bg3loc.qa import QA_ROUTE_RETRY, QA_ROUTE_REVIEW, QA_RULESET_VERSION, QaInput, QaIssue, QaResult, evaluate_translation
from bg3loc.qa_state import QA_STATUS_CHECKED, TranslationQaStore
from bg3loc.production_review import (
    ProductionReviewStore,
    REVIEW_DECISION_ACCEPT,
    REVIEW_DECISION_REVISE,
)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "qa",
        help="Run and inspect translation QA",
    )
    subs = parser.add_subparsers(dest="qa_command", required=True)

    run_p = subs.add_parser("run", help="Run QA for succeeded translation rows")
    run_p.add_argument("--db", required=True, help="Path to execution.sqlite3")
    run_p.add_argument("--batch-plan", required=True, help="Path to LSTP-01B batch-plan.json")
    run_p.add_argument("--max-items", type=int)
    run_p.set_defaults(handler=run_qa)

    summary_p = subs.add_parser("summary", help="Show persisted QA routing counts")
    summary_p.add_argument("--db", required=True)
    summary_p.set_defaults(handler=run_summary)

    review_p = subs.add_parser("review-list", help="List rows routed to human review")
    review_p.add_argument("--db", required=True)
    review_p.add_argument("--limit", type=int, default=50)
    review_p.set_defaults(handler=run_review_list)

    review_export_p = subs.add_parser(
        "review-export",
        help="Export current REVIEW candidates with source, candidate text, and issues",
    )
    review_export_p.add_argument("--db", required=True)
    review_export_p.add_argument("--batch-plan", required=True)
    review_export_p.add_argument("--output", required=True)
    review_export_p.set_defaults(handler=run_review_export)

    review_resolve_p = subs.add_parser(
        "review-resolve",
        help="Record one human decision for a current REVIEW candidate",
    )
    review_resolve_p.add_argument("--db", required=True)
    review_resolve_p.add_argument("--content-uid", required=True)
    review_resolve_p.add_argument(
        "--decision",
        required=True,
        choices=["accept", "revise"],
    )
    review_resolve_p.add_argument("--reviewer", required=True)
    review_resolve_p.add_argument("--note", default="")
    review_resolve_p.add_argument("--text")
    review_resolve_p.set_defaults(handler=run_review_resolve)
    retry_p = subs.add_parser(
        "retry-handoff",
        help="Archive one current RETRY candidate and reopen it in translation execution",
    )
    retry_p.add_argument("--db", required=True)
    retry_p.add_argument("--content-uid", required=True)
    retry_p.add_argument("--max-attempts", type=int, default=3)
    retry_p.set_defaults(handler=run_retry_handoff)

    register_probe(subs)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_material_batch(batch_plan_path: Path, batch_id: str) -> dict[str, dict[str, object]]:
    path = batch_plan_path.parent / "materials" / f"{batch_id}.jsonl"
    if not path.is_file():
        raise RuntimeError(f"batch material not found: {path}")

    rows: dict[str, dict[str, object]] = {}
    with path.open("r", encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise RuntimeError(f"{path}:{line_no}: expected JSON object")
            uid = str(row.get("contentUid", row.get("ContentUid", "")))
            if not uid:
                raise RuntimeError(f"{path}:{line_no}: missing ContentUid")
            rows[uid] = row
    return rows


def run_qa(args: argparse.Namespace) -> int:
    db = Path(args.db)
    batch_plan = Path(args.batch_plan)
    if not db.is_file():
        raise RuntimeError(f"execution database not found: {db}")
    if not batch_plan.is_file():
        raise RuntimeError(f"batch plan not found: {batch_plan}")
    if args.max_items is not None and args.max_items <= 0:
        raise RuntimeError("--max-items must be positive")

    execution = TranslationExecutionStore(db)
    qa_store = TranslationQaStore(db)
    qa_store.initialize()

    states = execution.list_states_by_status(STATUS_SUCCEEDED)
    checked = 0
    skipped_current = 0
    route_counts: dict[str, int] = {}
    current_batch_id: str | None = None
    material_rows: dict[str, dict[str, object]] = {}

    for state in states:
        if args.max_items is not None and checked >= int(args.max_items):
            break

        uid = str(state["content_uid"])
        existing = qa_store.get_result(uid, current_rule_set_version=QA_RULESET_VERSION)
        if existing is not None and existing.qa_status == QA_STATUS_CHECKED:
            skipped_current += 1
            continue

        batch_id = str(state["batch_id"])
        if batch_id != current_batch_id:
            material_rows = _read_material_batch(batch_plan, batch_id)
            current_batch_id = batch_id

        row = material_rows.get(uid)
        if row is None:
            raise RuntimeError(f"ContentUid {uid} missing from material for {batch_id}")

        source_text = str(row.get("sourceText", row.get("SourceText", "")))
        category = str(row.get("primaryCategory", ""))
        translated_text = str(state.get("translated_text") or "")

        result = evaluate_translation(
            QaInput(
                content_uid=uid,
                source_text=source_text,
                translated_text=translated_text,
                primary_category=category,
                required_protected_tokens=tuple(extract_protected_tokens(source_text)),
            )
        )
        qa_store.record_result(result, checked_at=_utc_now_iso())
        checked += 1
        route_counts[result.route] = route_counts.get(result.route, 0) + 1

    print(f"QA ruleset version: {QA_RULESET_VERSION}")
    print(f"Succeeded execution rows: {len(states)}")
    print(f"Checked this run: {checked}")
    print(f"Skipped current QA: {skipped_current}")
    for route, count in sorted(route_counts.items()):
        print(f"{route}: {count}")
    return 0


def run_summary(args: argparse.Namespace) -> int:
    db = Path(args.db)
    if not db.is_file():
        raise RuntimeError(f"execution database not found: {db}")

    qa_store = TranslationQaStore(db)
    qa_store.initialize()

    total = 0
    checked = 0
    stale = 0
    routes: dict[str, int] = {}

    for route in ("PASS", "RETRY", "REVIEW", "FAIL"):
        rows = qa_store.list_by_route(route, current_rule_set_version=QA_RULESET_VERSION)
        if not rows:
            continue
        routes[route] = len(rows)
        total += len(rows)
        checked += sum(1 for row in rows if row.qa_status == "checked")
        stale += sum(1 for row in rows if row.qa_status == "stale")

    print(f"QA ruleset version: {QA_RULESET_VERSION}")
    print(f"Persisted QA rows: {total}")
    print(f"checked: {checked}")
    print(f"stale: {stale}")
    for route, count in sorted(routes.items()):
        print(f"{route}: {count}")
    return 0


def run_review_list(args: argparse.Namespace) -> int:
    db = Path(args.db)
    if not db.is_file():
        raise RuntimeError(f"execution database not found: {db}")
    if args.limit <= 0:
        raise RuntimeError("--limit must be positive")

    qa_store = TranslationQaStore(db)
    qa_store.initialize()
    rows = qa_store.list_by_route(
        QA_ROUTE_REVIEW,
        current_rule_set_version=QA_RULESET_VERSION,
    )

    print(f"Review rows: {len(rows)}")
    for row in rows[: int(args.limit)]:
        issue_codes = ",".join(str(issue["issueCode"]) for issue in row.issues)
        print(
            f"{row.content_uid}\t{row.qa_status}\t{row.issue_count}\t{issue_codes}"
        )
    return 0


def run_review_export(args: argparse.Namespace) -> int:
    db = Path(args.db)
    batch_plan = Path(args.batch_plan)
    output = Path(args.output)
    if not db.is_file():
        raise RuntimeError(f"execution database not found: {db}")
    if not batch_plan.is_file():
        raise RuntimeError(f"batch plan not found: {batch_plan}")

    qa_store = TranslationQaStore(db)
    qa_store.initialize()
    rows = qa_store.list_by_route(
        QA_ROUTE_REVIEW,
        current_rule_set_version=QA_RULESET_VERSION,
    )

    execution = TranslationExecutionStore(db)
    execution_states = {
        str(state["content_uid"]): state
        for state in execution.list_states_by_status(STATUS_SUCCEEDED)
    }
    materials_by_batch: dict[str, dict[str, dict[str, object]]] = {}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for qa in rows:
            if qa.qa_status != QA_STATUS_CHECKED:
                continue
            state = execution_states.get(qa.content_uid)
            if state is None:
                raise RuntimeError(f"execution state not found: {qa.content_uid}")
            batch_id = str(state["batch_id"])
            material = materials_by_batch.get(batch_id)
            if material is None:
                material = _read_material_batch(batch_plan, batch_id)
                materials_by_batch[batch_id] = material
            source = material.get(qa.content_uid)
            if source is None:
                raise RuntimeError(
                    f"ContentUid {qa.content_uid} missing from material for {batch_id}"
                )
            payload = {
                "ContentUid": qa.content_uid,
                "SourceText": str(source.get("sourceText", source.get("SourceText", ""))),
                "TranslatedText": str(state.get("translated_text") or ""),
                "OutputHash": str(state.get("output_hash") or ""),
                "QaRuleSetVersion": qa.qa_rule_set_version,
                "QaInputHash": qa.qa_input_hash,
                "Issues": list(qa.issues),
                "Decision": "",
                "ResolvedText": "",
                "Reviewer": "",
                "Note": "",
            }
            handle.write(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
            )

    print(f"Review rows exported: {sum(1 for row in rows if row.qa_status == QA_STATUS_CHECKED)}")
    print(f"Output: {output}")
    return 0


def run_review_resolve(args: argparse.Namespace) -> int:
    db = Path(args.db)
    if not db.is_file():
        raise RuntimeError(f"execution database not found: {db}")

    decision = (
        REVIEW_DECISION_ACCEPT
        if str(args.decision) == "accept"
        else REVIEW_DECISION_REVISE
    )
    if decision == REVIEW_DECISION_REVISE and args.text is None:
        raise RuntimeError("--text is required for --decision revise")
    if decision == REVIEW_DECISION_ACCEPT and args.text is not None:
        raise RuntimeError("--text must not be supplied for --decision accept")

    store = ProductionReviewStore(db)
    store.initialize()
    resolution = store.resolve(
        content_uid=str(args.content_uid),
        decision=decision,
        reviewer=str(args.reviewer),
        note=str(args.note),
        resolved_at=_utc_now_iso(),
        revised_text=str(args.text) if args.text is not None else None,
    )

    print(f"ContentUid: {resolution.content_uid}")
    print(f"Decision: {resolution.decision}")
    print(f"Resolution ID: {resolution.resolution_id}")
    print(f"Base output hash: {resolution.base_output_hash}")
    print(f"Resolved output hash: {resolution.resolved_output_hash}")
    if resolution.decision == REVIEW_DECISION_ACCEPT:
        print("Next: production status will treat this current output as human-approved.")
    else:
        print("Next: rerun bg3loc qa run before checking production readiness.")
    return 0


def run_retry_handoff(args: argparse.Namespace) -> int:
    db = Path(args.db)
    if not db.is_file():
        raise RuntimeError(f"execution database not found: {db}")
    if args.max_attempts <= 0:
        raise RuntimeError("--max-attempts must be positive")

    qa_store = TranslationQaStore(db)
    qa_store.initialize()
    stored = qa_store.get_result(
        str(args.content_uid),
        current_rule_set_version=QA_RULESET_VERSION,
    )
    if stored is None:
        raise RuntimeError(f"QA result not found: {args.content_uid}")
    if stored.qa_status != QA_STATUS_CHECKED:
        raise RuntimeError(f"QA result is stale: {args.content_uid}")
    if stored.route != QA_ROUTE_RETRY:
        raise RuntimeError(
            f"QA route is not RETRY for {args.content_uid}: {stored.route}"
        )

    result = QaResult(
        content_uid=stored.content_uid,
        route=stored.route,
        qa_rule_set_version=stored.qa_rule_set_version,
        qa_input_hash=stored.qa_input_hash,
        issues=tuple(
            QaIssue(
                issue_code=str(issue["issueCode"]),
                severity=str(issue["severity"]),
                action=str(issue["action"]),
                message=str(issue["message"]),
                details=tuple(str(value) for value in issue["details"]),
            )
            for issue in stored.issues
        ),
    )
    status = qa_store.handoff_retry(
        result,
        max_attempts=int(args.max_attempts),
        rejected_at=f"qa-retry:{QA_RULESET_VERSION}",
    )
    rejected = qa_store.get_rejected_candidates(stored.content_uid)
    print(f"ContentUid: {stored.content_uid}")
    print(f"Previous QA route: {stored.route}")
    print(f"Execution status: {status}")
    print(f"Rejected candidates archived: {len(rejected)}")
    return 0
