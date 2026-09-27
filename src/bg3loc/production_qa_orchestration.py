from __future__ import annotations

from argparse import Namespace
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from bg3loc.commands.translation_qa import (
    run_qa,
    run_review_export,
    run_review_resolve,
    run_retry_handoff,
)
from bg3loc.production_completion import (
    DISPOSITION_BLOCKED,
    DISPOSITION_MERGE_READY,
    DISPOSITION_WAITING_RETRY,
    DISPOSITION_WAITING_REVIEW,
    DISPOSITION_WAITING_TRANSLATION,
    ProductionCompletionView,
    build_production_completion_view,
)
from bg3loc.production_workspace import (
    ProductionWorkspaceBinding,
    verify_production_workspace,
)
from bg3loc.qa import QA_ROUTE_FAIL, QA_ROUTE_PASS, QA_ROUTE_RETRY, QA_ROUTE_REVIEW, QA_RULESET_VERSION


@dataclass(frozen=True, slots=True)
class ProductionOperatorReport:
    workspace: Path
    database: Path
    source_locale: str
    target_locale: str
    batch_plan_fingerprint: str
    ruleset_version: str
    ruleset_fingerprint: str
    execution_counts: dict[str, int]
    qa_counts: dict[str, int]
    completion: ProductionCompletionView


def _read_counts(binding: ProductionWorkspaceBinding) -> tuple[dict[str, int], dict[str, int]]:
    uri = binding.database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        execution_counts = {
            str(status): int(count)
            for status, count in conn.execute(
                "SELECT status, COUNT(*) FROM content_state GROUP BY status"
            )
        }
        total = sum(execution_counts.values())
        qa_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='qa_results'"
        ).fetchone()
        qa_counts = {
            "not checked": total,
            "stale": 0,
            QA_ROUTE_PASS: 0,
            QA_ROUTE_RETRY: 0,
            QA_ROUTE_REVIEW: 0,
            QA_ROUTE_FAIL: 0,
        }
        if qa_table is not None:
            rows = conn.execute(
                """
                SELECT
                    q.route,
                    CASE
                        WHEN q.qa_rule_set_version = ?
                         AND q.output_hash = COALESCE(c.output_hash, '')
                        THEN 'checked'
                        ELSE 'stale'
                    END AS qa_status,
                    COUNT(*)
                FROM qa_results AS q
                JOIN content_state AS c USING(content_uid)
                GROUP BY q.route, qa_status
                """,
                (QA_RULESET_VERSION,),
            ).fetchall()
            persisted = 0
            for route, qa_status, count in rows:
                count = int(count)
                persisted += count
                if str(qa_status) == "stale":
                    qa_counts["stale"] += count
                else:
                    qa_counts[str(route)] = qa_counts.get(str(route), 0) + count
            qa_counts["not checked"] = total - persisted
    return execution_counts, qa_counts


def build_operator_report(workspace: Path) -> ProductionOperatorReport:
    binding = verify_production_workspace(workspace)
    execution_counts, qa_counts = _read_counts(binding)
    manifest = binding.manifest
    batching = manifest["batching"]
    ruleset = manifest["inputs"]["ruleset"]
    completion = build_production_completion_view(
        binding.database,
        binding.batch_plan,
    )
    return ProductionOperatorReport(
        workspace=binding.workspace,
        database=binding.database,
        source_locale=str(manifest["sourceLocale"]),
        target_locale=str(manifest["targetLocale"]),
        batch_plan_fingerprint=str(batching["batchPlanFingerprint"]),
        ruleset_version=str(ruleset["version"]),
        ruleset_fingerprint=str(ruleset["fingerprint"]),
        execution_counts=execution_counts,
        qa_counts=qa_counts,
        completion=completion,
    )


def run_workspace_qa(workspace: Path, *, max_items: int | None = None) -> ProductionOperatorReport:
    binding = verify_production_workspace(workspace)
    run_qa(
        Namespace(
            db=str(binding.database),
            batch_plan=str(binding.batch_plan),
            max_items=max_items,
        )
    )
    return build_operator_report(workspace)


def handoff_workspace_retry(
    workspace: Path,
    *,
    content_uid: str,
    max_attempts: int = 3,
) -> None:
    binding = verify_production_workspace(workspace)
    run_retry_handoff(
        Namespace(
            db=str(binding.database),
            content_uid=content_uid,
            max_attempts=max_attempts,
        )
    )


def export_workspace_review(workspace: Path, *, output: Path) -> None:
    binding = verify_production_workspace(workspace)
    run_review_export(
        Namespace(
            db=str(binding.database),
            batch_plan=str(binding.batch_plan),
            output=str(output),
        )
    )


def resolve_workspace_review(
    workspace: Path,
    *,
    content_uid: str,
    decision: str,
    reviewer: str,
    note: str = "",
    text: str | None = None,
) -> None:
    binding = verify_production_workspace(workspace)
    run_review_resolve(
        Namespace(
            db=str(binding.database),
            content_uid=content_uid,
            decision=decision,
            reviewer=reviewer,
            note=note,
            text=text,
        )
    )


def print_operator_report(report: ProductionOperatorReport) -> None:
    print(f"Production workspace: {report.workspace}")
    print(f"Source locale: {report.source_locale}")
    print(f"Target locale: {report.target_locale}")
    print(f"Batch fingerprint: {report.batch_plan_fingerprint}")
    print(f"Ruleset version: {report.ruleset_version}")
    print(f"Ruleset fingerprint: {report.ruleset_fingerprint}")
    print("Execution:")
    for status in (
        "pending",
        "running",
        "succeeded",
        "failed-retryable",
        "failed-final",
        "invalidated",
        "skipped",
    ):
        print(f"  {status}: {report.execution_counts.get(status, 0)}")
    print("QA:")
    for status in ("not checked", "stale", QA_ROUTE_PASS, QA_ROUTE_RETRY, QA_ROUTE_REVIEW, QA_ROUTE_FAIL):
        print(f"  {status}: {report.qa_counts.get(status, 0)}")
    print("Completion:")
    for disposition in (
        DISPOSITION_MERGE_READY,
        DISPOSITION_WAITING_TRANSLATION,
        DISPOSITION_WAITING_RETRY,
        DISPOSITION_WAITING_REVIEW,
        DISPOSITION_BLOCKED,
    ):
        print(f"  {disposition}: {report.completion.counts[disposition]}")
    print("By category:")
    for category, counts in report.completion.by_category.items():
        print(
            f"  {category}: total={sum(counts.values())} "
            f"MERGE_READY={counts[DISPOSITION_MERGE_READY]} "
            f"WAITING_TRANSLATION={counts[DISPOSITION_WAITING_TRANSLATION]} "
            f"WAITING_RETRY={counts[DISPOSITION_WAITING_RETRY]} "
            f"WAITING_REVIEW={counts[DISPOSITION_WAITING_REVIEW]} "
            f"BLOCKED={counts[DISPOSITION_BLOCKED]}"
        )
