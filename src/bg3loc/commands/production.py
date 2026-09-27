from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import shutil

from bg3loc.execution_state import TranslationExecutionStore
from bg3loc.final_merge_bridge import FinalMergeBridgeError, build_final_merge_bridge
from bg3loc.protected_syntax import extract_protected_tokens
from bg3loc.qa import QaInput, evaluate_translation
from bg3loc.qa_state import TranslationQaStore
from bg3loc.commands.translation_state import load_execution_items
from bg3loc.production_orchestration import ProductionPrepareRequest, prepare_production_workspace
from bg3loc.production_execution import OpenAICompatibleExecutionRequest, execute_openai_compatible
from bg3loc.production_qa_orchestration import (
    build_operator_report,
    export_workspace_review,
    handoff_workspace_retry,
    print_operator_report,
    resolve_workspace_review,
    run_workspace_qa,
)
from bg3loc.production_completion import (
    DISPOSITION_BLOCKED,
    DISPOSITION_MERGE_READY,
    DISPOSITION_WAITING_RETRY,
    DISPOSITION_WAITING_REVIEW,
    DISPOSITION_WAITING_TRANSLATION,
    ProductionDisposition,
    build_production_completion_view,
)
from bg3loc.production_finalize import (
    ProductionFinalizeRequest,
    finalize_production_workspace,
)
from bg3loc.production_reporting import (
    build_production_accounting_report,
    print_production_accounting_report,
    write_production_report,
)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "production",
        help="Prepare, translate, QA, report, and finalize a resumable project",
        epilog=(
            "Typical flow: prepare -> execute-openai-compatible -> qa -> report "
            "-> review-export/review-resolve if needed -> finalize. "
            "See docs/getting-started.md."
        ),
    )
    subs = parser.add_subparsers(dest="production_command", required=True)

    prepare_p = subs.add_parser(
        "prepare",
        help="Prepare a fresh workspace from extract, research mappings, and ruleset",
    )
    prepare_p.add_argument("--extract", required=True, help="Path to extract-manifest.json")
    prepare_p.add_argument("--source", required=True, help="Path to normalized source-locale JSONL")
    prepare_p.add_argument("--research-mappings", required=True, help="Path to research-mappings.jsonl")
    prepare_p.add_argument("--ruleset", required=True, help="Versioned translation ruleset JSON")
    prepare_p.add_argument("--output", required=True, help="Fresh production workspace directory")
    prepare_p.add_argument("--story-ledger", help="Optional story-occurrence-ledger.csv")
    prepare_p.add_argument("--ui-skill-universe", help="Optional ui-skill-universe.csv")
    prepare_p.add_argument("--unclassified-decisions", help="Optional unclassified decision JSONL")
    prepare_p.add_argument(
        "--max-records",
        action="append",
        default=[],
        metavar="CATEGORY=N",
        help="Override a category batch size; repeatable",
    )
    prepare_p.set_defaults(handler=run_prepare)

    execute_p = subs.add_parser(
        "execute-openai-compatible",
        help="Execute a prepared production workspace through an OpenAI-compatible provider",
    )
    execute_p.add_argument("--workspace", required=True, help="Prepared production workspace")
    execute_p.add_argument("--base-url", required=True)
    execute_p.add_argument("--model", required=True)
    execute_p.add_argument("--run-id", required=True)
    execute_p.add_argument("--worker-id", required=True)
    execute_p.add_argument("--api-key-env", default="BG3LOC_API_KEY")
    execute_p.add_argument("--timeout-seconds", type=float, default=120.0)
    execute_p.add_argument("--max-output-tokens", type=int)
    execute_p.add_argument("--temperature", type=float)
    execute_p.add_argument("--lease-seconds", type=int, default=300)
    execute_p.add_argument("--max-attempts", type=int, default=3)
    execute_p.add_argument("--max-items", type=int)
    execute_p.add_argument("--retry-backoff-base-seconds", type=float, default=2.0)
    execute_p.add_argument("--retry-backoff-max-seconds", type=float, default=60.0)
    execute_p.add_argument("--min-request-interval-seconds", type=float, default=0.0)
    execute_p.set_defaults(handler=run_execute_openai_compatible)

    qa_p = subs.add_parser(
        "qa",
        help="Check translations and route PASS, RETRY, REVIEW, or FAIL",
    )
    qa_p.add_argument("--workspace", required=True)
    qa_p.add_argument("--max-items", type=int)
    qa_p.set_defaults(handler=run_production_qa)

    retry_p = subs.add_parser(
        "retry",
        help="Hand one current QA RETRY row back to translation execution",
    )
    retry_p.add_argument("--workspace", required=True)
    retry_p.add_argument("--content-uid", required=True)
    retry_p.add_argument("--max-attempts", type=int, default=3)
    retry_p.set_defaults(handler=run_production_retry)

    review_export_p = subs.add_parser(
        "review-export",
        help="Export current human-review candidates from a production workspace",
    )
    review_export_p.add_argument("--workspace", required=True)
    review_export_p.add_argument("--output", required=True)
    review_export_p.set_defaults(handler=run_production_review_export)

    review_resolve_p = subs.add_parser(
        "review-resolve",
        help="Record a human decision for one current REVIEW candidate",
    )
    review_resolve_p.add_argument("--workspace", required=True)
    review_resolve_p.add_argument("--content-uid", required=True)
    review_resolve_p.add_argument(
        "--decision", required=True, choices=["accept", "revise"]
    )
    review_resolve_p.add_argument("--reviewer", required=True)
    review_resolve_p.add_argument("--note", default="")
    review_resolve_p.add_argument("--text")
    review_resolve_p.set_defaults(handler=run_production_review_resolve)

    report_p = subs.add_parser(
        "report",
        help="Show read-only progress, errors, usage, and optional cost",
    )
    report_p.add_argument("--workspace", required=True)
    report_p.add_argument(
        "--pricing",
        help="Optional exact provider/model pricing JSON for cost accounting",
    )
    report_p.add_argument("--json", dest="json_output", help="Optional JSON report path")
    report_p.set_defaults(handler=run_production_report)

    finalize_p = subs.add_parser(
        "finalize",
        help="Rebuild language files after all classified rows are merge-ready",
    )
    finalize_p.add_argument("--workspace", required=True)
    finalize_p.add_argument("--output", required=True)
    finalize_p.add_argument(
        "--container", choices=["auto", "loca-only", "repack"], default="auto"
    )
    finalize_p.add_argument("--backend", default="auto")
    finalize_p.set_defaults(handler=run_production_finalize)

    status_p = subs.add_parser(
        "status",
        help="Show whole-corpus and per-category production completion counts",
    )
    _add_common_args(status_p)
    status_p.set_defaults(handler=run_status)

    unresolved_p = subs.add_parser(
        "unresolved",
        help="List or export rows that are not merge-ready",
    )
    _add_common_args(unresolved_p)
    unresolved_p.add_argument("--output", help="Optional JSONL output path")
    unresolved_p.set_defaults(handler=run_unresolved)

    ready_p = subs.add_parser(
        "merge-ready",
        help="List or export rows that are safe to pass to the merge stage",
    )
    _add_common_args(ready_p)
    ready_p.add_argument("--output", help="Optional JSONL output path")
    ready_p.set_defaults(handler=run_merge_ready)

    probe_p = subs.add_parser(
        "smoke-probe",
        help="Create an isolated real-material production-completion probe",
    )
    probe_p.add_argument("--batch-plan", required=True)
    probe_p.add_argument("--work-dir", required=True)
    probe_p.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing probe work directory",
    )
    probe_p.set_defaults(handler=run_smoke_probe)

    bridge_p = subs.add_parser(
        "bridge",
        help="Convert the current MERGE_READY set into validated rebuild input",
    )
    _add_common_args(bridge_p)
    bridge_p.add_argument(
        "--extract",
        required=True,
        help="Path to the authoritative extract-manifest.json",
    )
    bridge_p.add_argument(
        "--output",
        required=True,
        help="Output directory for bridge artifacts",
    )
    bridge_p.set_defaults(handler=run_bridge)


def run_prepare(args: argparse.Namespace) -> int:
    manifest = prepare_production_workspace(
        ProductionPrepareRequest(
            extract_manifest=Path(args.extract),
            source=Path(args.source),
            research_mappings=Path(args.research_mappings),
            ruleset=Path(args.ruleset),
            output_dir=Path(args.output),
            story_ledger=Path(args.story_ledger) if args.story_ledger else None,
            ui_skill_universe=Path(args.ui_skill_universe) if args.ui_skill_universe else None,
            unclassified_decisions=(
                Path(args.unclassified_decisions)
                if args.unclassified_decisions
                else None
            ),
            max_records=tuple(args.max_records),
        )
    )
    print("Production prepare PASS")
    print(f"Workspace: {args.output}")
    print(f"Source locale: {manifest['sourceLocale']}")
    print(f"Target locale: {manifest['targetLocale']}")
    print(f"Batch plan fingerprint: {manifest['batching']['batchPlanFingerprint']}")
    print(f"Batches: {manifest['batching']['batchCount']}")
    print(f"Seeded ContentUids: {manifest['execution']['seededContentUidCount']}")
    print(f"Unresolved: {manifest['batching']['unresolvedCount']}")
    print(f"Excluded: {manifest['batching']['excludedCount']}")
    print(f"Manifest: {Path(args.output) / 'production-manifest.json'}")
    return 0


def run_execute_openai_compatible(args: argparse.Namespace) -> int:
    result = execute_openai_compatible(
        OpenAICompatibleExecutionRequest(
            workspace=Path(args.workspace),
            base_url=str(args.base_url),
            model=str(args.model),
            run_id=str(args.run_id),
            worker_id=str(args.worker_id),
            api_key_env=str(args.api_key_env),
            timeout_seconds=float(args.timeout_seconds),
            max_output_tokens=(
                int(args.max_output_tokens)
                if args.max_output_tokens is not None
                else None
            ),
            temperature=(
                float(args.temperature)
                if args.temperature is not None
                else None
            ),
            lease_seconds=int(args.lease_seconds),
            max_attempts=int(args.max_attempts),
            max_items=int(args.max_items) if args.max_items is not None else None,
            retry_backoff_base_seconds=float(args.retry_backoff_base_seconds),
            retry_backoff_max_seconds=float(args.retry_backoff_max_seconds),
            min_request_interval_seconds=float(args.min_request_interval_seconds),
        )
    )
    print("Production execute PASS")
    print(f"runId: {result.run_id}")
    print(f"run status: {result.run_status}")
    print(f"provider: {result.provider}")
    print(f"model: {result.model}")
    print(
        "retry backoff seconds: "
        f"base={args.retry_backoff_base_seconds:g} "
        f"max={args.retry_backoff_max_seconds:g}"
    )
    print(f"minimum request interval seconds: {args.min_request_interval_seconds:g}")
    print(f"claimed: {result.claimed}")
    print(f"succeeded: {result.succeeded}")
    print(f"failed-retryable: {result.failed_retryable}")
    print(f"failed-final: {result.failed_final}")
    for status, count in sorted(result.database_summary.items()):
        print(f"database {status}: {count}")
    return 0


def run_production_qa(args: argparse.Namespace) -> int:
    report = run_workspace_qa(
        Path(args.workspace),
        max_items=int(args.max_items) if args.max_items is not None else None,
    )
    print("Production QA PASS")
    print_operator_report(report)
    return 0


def run_production_retry(args: argparse.Namespace) -> int:
    handoff_workspace_retry(
        Path(args.workspace),
        content_uid=str(args.content_uid),
        max_attempts=int(args.max_attempts),
    )
    print("Production retry handoff PASS")
    return 0


def run_production_review_export(args: argparse.Namespace) -> int:
    export_workspace_review(
        Path(args.workspace),
        output=Path(args.output),
    )
    print("Production review export PASS")
    return 0


def run_production_review_resolve(args: argparse.Namespace) -> int:
    resolve_workspace_review(
        Path(args.workspace),
        content_uid=str(args.content_uid),
        decision=str(args.decision),
        reviewer=str(args.reviewer),
        note=str(args.note),
        text=str(args.text) if args.text is not None else None,
    )
    print("Production review resolution PASS")
    return 0


def run_production_report(args: argparse.Namespace) -> int:
    report = build_production_accounting_report(
        Path(args.workspace),
        pricing_path=Path(args.pricing) if args.pricing else None,
    )
    print_production_accounting_report(report)
    if args.json_output:
        output = Path(args.json_output)
        write_production_report(output, report)
        print(f"JSON report: {output}")
    return 0


def run_production_finalize(args: argparse.Namespace) -> int:
    result = finalize_production_workspace(
        ProductionFinalizeRequest(
            workspace=Path(args.workspace),
            output=Path(args.output),
            container=str(args.container),
            backend=str(args.backend),
        )
    )
    manifest = result.manifest
    print("Finalize PASS")
    print(f"Source locale: {manifest['sourceLocale']}")
    print(f"Target locale: {manifest['targetLocale']}")
    print(f"MERGE_READY count: {manifest['completion']['mergeReadyCount']}")
    print(
        "Batch fingerprint: "
        f"{manifest['productionWorkspace']['batchPlanFingerprint']}"
    )
    for artifact in manifest["artifacts"]:
        label = str(artifact["type"]).upper()
        print(f"{label} path: {Path(args.output) / artifact['path']}")
        print(f"{label} SHA256: {artifact['sha256']}")
    print(f"Final manifest: {result.manifest_path}")
    return 0


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", required=True, help="Path to execution.sqlite3")
    parser.add_argument("--batch-plan", required=True, help="Path to LSTP-01B batch-plan.json")


def _view(args: argparse.Namespace):
    return build_production_completion_view(
        Path(args.db),
        Path(args.batch_plan),
    )


def _row_payload(row: ProductionDisposition) -> dict[str, object]:
    return {
        "ContentUid": row.content_uid,
        "primaryCategory": row.primary_category,
        "batchId": row.batch_id,
        "executionStatus": row.execution_status,
        "qaStatus": row.qa_status,
        "qaRoute": row.qa_route,
        "disposition": row.disposition,
        "reasonCode": row.reason_code,
        "lastAttemptId": row.last_attempt_id,
        "attemptCount": row.attempt_count,
    }


def _write_jsonl(path: Path, rows: list[ProductionDisposition]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(
                json.dumps(
                    _row_payload(row),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )


def run_bridge(args: argparse.Namespace) -> int:
    try:
        manifest = build_final_merge_bridge(
            db_path=Path(args.db),
            batch_plan_path=Path(args.batch_plan),
            extract_manifest_path=Path(args.extract),
            output_dir=Path(args.output),
        )
    except FinalMergeBridgeError as exc:
        raise RuntimeError(f"production bridge failed: {exc}") from exc

    print("Production bridge PASS")
    print(f"Merge-ready rows: {manifest['mergeReadyCount']}")
    print(f"Target locale: {manifest['targetLocale']}")
    print(f"Accepted target: {manifest['acceptedTarget']['path']}")
    print(f"Accepted target SHA256: {manifest['acceptedTarget']['sha256']}")
    print(f"Validate manifest: {manifest['validateManifest']['path']}")
    print(f"Bridge manifest: {Path(args.output) / 'bridge-manifest.json'}")
    return 0


def run_status(args: argparse.Namespace) -> int:
    view = _view(args)
    print(f"Total: {view.total}")
    print(f"{DISPOSITION_MERGE_READY}: {view.counts[DISPOSITION_MERGE_READY]}")
    print(f"{DISPOSITION_WAITING_TRANSLATION}: {view.counts[DISPOSITION_WAITING_TRANSLATION]}")
    print(f"{DISPOSITION_WAITING_RETRY}: {view.counts[DISPOSITION_WAITING_RETRY]}")
    print(f"{DISPOSITION_WAITING_REVIEW}: {view.counts[DISPOSITION_WAITING_REVIEW]}")
    print(f"{DISPOSITION_BLOCKED}: {view.counts[DISPOSITION_BLOCKED]}")

    print("By category:")
    for category, counts in view.by_category.items():
        print(
            f"{category}: "
            f"total={sum(counts.values())} "
            f"mergeReady={counts[DISPOSITION_MERGE_READY]} "
            f"waitingTranslation={counts[DISPOSITION_WAITING_TRANSLATION]} "
            f"waitingRetry={counts[DISPOSITION_WAITING_RETRY]} "
            f"waitingReview={counts[DISPOSITION_WAITING_REVIEW]} "
            f"blocked={counts[DISPOSITION_BLOCKED]}"
        )
    return 0


def run_unresolved(args: argparse.Namespace) -> int:
    view = _view(args)
    rows = [
        row
        for row in view.rows
        if row.disposition != DISPOSITION_MERGE_READY
    ]
    if args.output:
        output = Path(args.output)
        _write_jsonl(output, rows)
        print(f"Unresolved rows: {len(rows)}")
        print(f"Output: {output}")
        return 0

    print(f"Unresolved rows: {len(rows)}")
    for row in rows:
        print(
            f"{row.content_uid}\t{row.primary_category}\t{row.batch_id}\t"
            f"{row.disposition}\t{row.reason_code}"
        )
    return 0


def run_merge_ready(args: argparse.Namespace) -> int:
    view = _view(args)
    rows = [
        row
        for row in view.rows
        if row.disposition == DISPOSITION_MERGE_READY
    ]
    if args.output:
        output = Path(args.output)
        _write_jsonl(output, rows)
        print(f"Merge-ready rows: {len(rows)}")
        print(f"Output: {output}")
        return 0

    print(f"Merge-ready rows: {len(rows)}")
    for row in rows:
        print(f"{row.content_uid}\t{row.primary_category}\t{row.batch_id}")
    return 0


_LANGUAGE_BEARING_RE = re.compile(r"[A-Za-z]{4,}")


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_pass_candidate(source: str) -> str:
    protected = extract_protected_tokens(source)
    candidate = "譯" * max(4, len(source) // 2)
    if protected:
        candidate += " " + " ".join(protected)
    return candidate


def _select_probe_rows(batch_plan: Path) -> list[dict[str, str]]:
    with batch_plan.open("r", encoding="utf-8") as handle:
        plan = json.load(handle)

    usable: list[dict[str, str]] = []
    review_row: dict[str, str] | None = None
    seen: set[str] = set()

    for batch in plan.get("batches", []):
        if not isinstance(batch, dict):
            continue
        batch_id = str(batch.get("batchId", ""))
        category = str(batch.get("primaryCategory", ""))
        if not batch_id or not category:
            continue
        material = batch_plan.parent / "materials" / f"{batch_id}.jsonl"
        if not material.is_file():
            raise RuntimeError(f"batch material not found: {material}")

        with material.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    continue
                uid = str(row.get("ContentUid", row.get("contentUid", "")))
                source = str(row.get("SourceText", row.get("sourceText", "")))
                row_category = str(row.get("primaryCategory", category))
                if not uid or not source or not row_category or uid in seen:
                    continue
                seen.add(uid)
                normalized = {
                    "ContentUid": uid,
                    "SourceText": source,
                    "primaryCategory": row_category,
                    "batchId": batch_id,
                }
                usable.append(normalized)
                if review_row is None and _LANGUAGE_BEARING_RE.search(source):
                    review_row = normalized

                if len(usable) >= 4 and review_row is not None:
                    others = [
                        item
                        for item in usable
                        if item["ContentUid"] != review_row["ContentUid"]
                    ]
                    if len(others) >= 3:
                        return [others[0], review_row, others[1], others[2]]

    raise RuntimeError(
        "batch plan does not contain four usable rows including one language-bearing row"
    )


def run_smoke_probe(args: argparse.Namespace) -> int:
    batch_plan = Path(args.batch_plan)
    work_dir = Path(args.work_dir)
    if not batch_plan.is_file():
        raise RuntimeError(f"batch plan not found: {batch_plan}")

    if work_dir.exists():
        if not args.force:
            raise RuntimeError(
                f"work directory already exists; use --force to replace it: {work_dir}"
            )
        if work_dir.resolve() in {Path.cwd().resolve(), Path(work_dir.anchor).resolve()}:
            raise RuntimeError(f"refusing to remove unsafe work directory: {work_dir}")
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    fingerprint, items = load_execution_items(
        batch_plan,
        prompt_version="production-smoke",
    )
    selected = _select_probe_rows(batch_plan)
    db = work_dir / "execution.sqlite3"

    execution = TranslationExecutionStore(db)
    execution.initialize()
    execution.seed_items(items, updated_at=f"production-smoke:{fingerprint}")

    pass_row, review_row, retry_row, blocked_row = selected
    pass_text = _safe_pass_candidate(pass_row["SourceText"])
    review_text = review_row["SourceText"]

    with closing(execution.connect()) as conn, conn:
        conn.execute(
            """
            UPDATE content_state
            SET status='succeeded', translated_text=?, output_hash=?, attempt_count=1
            WHERE content_uid=?
            """,
            (pass_text, _hash_text(pass_text), pass_row["ContentUid"]),
        )
        conn.execute(
            """
            UPDATE content_state
            SET status='succeeded', translated_text=?, output_hash=?, attempt_count=1
            WHERE content_uid=?
            """,
            (review_text, _hash_text(review_text), review_row["ContentUid"]),
        )
        conn.execute(
            """
            UPDATE content_state
            SET status='failed-retryable', attempt_count=1
            WHERE content_uid=?
            """,
            (retry_row["ContentUid"],),
        )
        conn.execute(
            """
            UPDATE content_state
            SET status='failed-final', attempt_count=3
            WHERE content_uid=?
            """,
            (blocked_row["ContentUid"],),
        )

    qa = TranslationQaStore(db)
    qa.initialize()

    pass_result = evaluate_translation(
        QaInput(
            content_uid=pass_row["ContentUid"],
            source_text=pass_row["SourceText"],
            translated_text=pass_text,
            primary_category=pass_row["primaryCategory"],
            required_protected_tokens=tuple(extract_protected_tokens(pass_row["SourceText"])),
        )
    )
    review_result = evaluate_translation(
        QaInput(
            content_uid=review_row["ContentUid"],
            source_text=review_row["SourceText"],
            translated_text=review_text,
            primary_category=review_row["primaryCategory"],
            required_protected_tokens=tuple(extract_protected_tokens(review_row["SourceText"])),
        )
    )
    qa.record_result(pass_result, checked_at="2026-09-24T00:00:00Z")
    qa.record_result(review_result, checked_at="2026-09-24T00:00:01Z")

    view = build_production_completion_view(db, batch_plan)

    manifest = {
        "batchPlanFingerprint": fingerprint,
        "database": str(db),
        "total": view.total,
        "counts": view.counts,
        "roles": {
            "MERGE_READY": pass_row["ContentUid"],
            "WAITING_REVIEW": review_row["ContentUid"],
            "WAITING_RETRY": retry_row["ContentUid"],
            "BLOCKED": blocked_row["ContentUid"],
        },
    }
    manifest_path = work_dir / "probe-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Production smoke probe database: {db}")
    print(f"Manifest: {manifest_path}")
    print(f"Total: {view.total}")
    for disposition, count in view.counts.items():
        print(f"{disposition}: {count}")
    for role, uid in manifest["roles"].items():
        print(f"{role}: {uid}")
    return 0
