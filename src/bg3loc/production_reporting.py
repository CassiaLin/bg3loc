from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3
from typing import Any

from bg3loc.execution_state import EXECUTABLE_STATUSES
from bg3loc.production_completion import (
    DISPOSITION_MERGE_READY,
    DISPOSITION_WAITING_RETRY,
)
from bg3loc.production_qa_orchestration import build_operator_report
from bg3loc.qa import QA_ROUTE_PASS, QA_ROUTE_REVIEW


REPORT_SCHEMA_VERSION = "1.0"
MINIMUM_ESTIMATE_SAMPLES = 10


def _percent(value: int, total: int) -> float:
    return round((value / total * 100.0) if total else 0.0, 2)


def _parse_timestamp(raw: object) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_pricing(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    if not path.is_file():
        raise RuntimeError(f"pricing file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid pricing file: {exc}") from exc
    if not isinstance(payload, dict) or str(payload.get("schemaVersion", "")) != "1.0":
        raise RuntimeError("pricing file must be a schemaVersion 1.0 object")
    currency = str(payload.get("currency", "")).strip()
    models = payload.get("models")
    if not currency or not isinstance(models, list):
        raise RuntimeError("pricing file requires currency and models")

    entries: dict[tuple[str, str], tuple[Decimal, Decimal]] = {}
    for item in models:
        if not isinstance(item, dict):
            raise RuntimeError("pricing models must contain objects")
        provider = str(item.get("provider", "")).strip()
        model = str(item.get("model", "")).strip()
        try:
            input_price = Decimal(str(item.get("inputPerMillion")))
            output_price = Decimal(str(item.get("outputPerMillion")))
        except (InvalidOperation, ValueError) as exc:
            raise RuntimeError("pricing values must be finite non-negative numbers") from exc
        if (
            not provider
            or not model
            or not input_price.is_finite()
            or not output_price.is_finite()
            or input_price < 0
            or output_price < 0
        ):
            raise RuntimeError("pricing entries require exact provider/model and non-negative prices")
        key = (provider, model)
        if key in entries:
            raise RuntimeError(f"duplicate pricing entry: {provider}/{model}")
        entries[key] = (input_price, output_price)
    return {"currency": currency, "entries": entries}


def _cost(
    prompt_tokens: int,
    completion_tokens: int,
    prices: tuple[Decimal, Decimal],
) -> Decimal:
    million = Decimal(1_000_000)
    return (
        Decimal(prompt_tokens) / million * prices[0]
        + Decimal(completion_tokens) / million * prices[1]
    )


def _usage_expressions(columns: set[str]) -> tuple[str, str, str]:
    return tuple(
        column if column in columns else "NULL"
        for column in ("prompt_tokens", "completion_tokens", "total_tokens")
    )  # type: ignore[return-value]


def _run_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            r.run_id, r.provider, r.model, r.prompt_version,
            r.execution_config_hash, r.started_at, r.finished_at, r.status,
            COUNT(a.attempt_id) AS attempt_count,
            SUM(CASE WHEN a.outcome = 'succeeded' THEN 1 ELSE 0 END) AS success_count,
            SUM(CASE WHEN a.outcome = 'failed-retryable' THEN 1 ELSE 0 END) AS retryable_failures,
            SUM(CASE WHEN a.outcome = 'failed-final' THEN 1 ELSE 0 END) AS final_failures,
            SUM(CASE WHEN a.attempt_number > 1 THEN 1 ELSE 0 END) AS retry_count,
            SUM(CASE WHEN a.error_code = 'HTTP_429' THEN 1 ELSE 0 END) AS http_429_count,
            SUM(CASE WHEN a.error_code GLOB 'HTTP_5??' THEN 1 ELSE 0 END) AS http_5xx_count,
            SUM(CASE WHEN a.error_code = 'PROVIDER_TRANSPORT_ERROR' THEN 1 ELSE 0 END) AS transport_error_count,
            AVG(CASE WHEN a.outcome = 'succeeded' AND a.finished_at IS NOT NULL
                THEN (julianday(a.finished_at) - julianday(a.started_at)) * 86400.0 END)
                AS average_success_latency_seconds,
            MAX(a.finished_at) AS last_observed_at
        FROM runs AS r
        LEFT JOIN attempts AS a USING(run_id)
        GROUP BY r.run_id
        ORDER BY r.started_at, r.run_id
        """
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        success_count = int(row["success_count"] or 0)
        started = _parse_timestamp(row["started_at"])
        ended = _parse_timestamp(row["finished_at"] or row["last_observed_at"])
        throughput: float | None = None
        if started is not None and ended is not None:
            minutes = (ended - started).total_seconds() / 60.0
            if minutes > 0:
                throughput = round(success_count / minutes, 4)
        latency = row["average_success_latency_seconds"]
        result.append(
            {
                "runId": str(row["run_id"]),
                "provider": str(row["provider"]),
                "model": str(row["model"]),
                "promptVersion": str(row["prompt_version"]),
                "executionConfigHash": str(row["execution_config_hash"]),
                "startedAt": str(row["started_at"]),
                "finishedAt": str(row["finished_at"]) if row["finished_at"] else None,
                "status": str(row["status"]),
                "attemptCount": int(row["attempt_count"] or 0),
                "successCount": success_count,
                "retryableFailures": int(row["retryable_failures"] or 0),
                "finalFailures": int(row["final_failures"] or 0),
                "retryCount": int(row["retry_count"] or 0),
                "http429Count": int(row["http_429_count"] or 0),
                "http5xxCount": int(row["http_5xx_count"] or 0),
                "transportErrorCount": int(row["transport_error_count"] or 0),
                "averageSuccessfulAttemptSeconds": (
                    round(float(latency), 4) if latency is not None else None
                ),
                "observedSuccessesPerMinute": throughput,
            }
        )
    return result


def _attempt_and_usage_report(
    conn: sqlite3.Connection,
    *,
    pricing: dict[str, Any] | None,
    batch_categories: dict[str, str],
    remaining_by_category: dict[str, int],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, int]]:
    columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(attempts)")
    }
    prompt_expr, completion_expr, total_expr = _usage_expressions(columns)
    attempts = conn.execute(
        f"""
        SELECT
            COUNT(*) AS total_attempts,
            SUM(CASE WHEN attempt_number > 1 THEN 1 ELSE 0 END) AS retry_count,
            SUM(CASE WHEN outcome = 'succeeded' THEN 1 ELSE 0 END) AS success_count,
            SUM(CASE WHEN outcome = 'failed-final' THEN 1 ELSE 0 END) AS failed_final_count
        FROM attempts
        """
    ).fetchone()
    total_attempts = int(attempts["total_attempts"] or 0)
    retry_count = int(attempts["retry_count"] or 0)
    success_count = int(attempts["success_count"] or 0)
    failed_final_count = int(attempts["failed_final_count"] or 0)
    attempt_report = {
        "totalAttempts": total_attempts,
        "successCount": success_count,
        "retryCount": retry_count,
        "retryRatePercent": _percent(retry_count, total_attempts),
        "failedFinalCount": failed_final_count,
        "failedFinalRatePercent": _percent(failed_final_count, total_attempts),
        "attemptsPerSuccess": (
            round(total_attempts / success_count, 4) if success_count else None
        ),
    }
    error_breakdown = {
        str(row["error_code"]): int(row["count"])
        for row in conn.execute(
            """
            SELECT error_code, COUNT(*) AS count
            FROM attempts
            WHERE error_code IS NOT NULL
            GROUP BY error_code
            ORDER BY count DESC, error_code
            """
        )
    }

    usage_rows = conn.execute(
        f"""
        SELECT provider, model,
            COUNT(*) AS terminal_attempts,
            SUM(CASE WHEN {prompt_expr} IS NOT NULL OR {completion_expr} IS NOT NULL
                          OR {total_expr} IS NOT NULL THEN 1 ELSE 0 END) AS known_attempts,
            SUM(CASE WHEN {prompt_expr} IS NULL AND {completion_expr} IS NULL
                          AND {total_expr} IS NULL THEN 1 ELSE 0 END) AS unknown_attempts,
            COALESCE(SUM({prompt_expr}), 0) AS prompt_tokens,
            COALESCE(SUM({completion_expr}), 0) AS completion_tokens,
            COALESCE(SUM({total_expr}), 0) AS total_tokens,
            SUM(CASE WHEN {prompt_expr} IS NOT NULL AND {completion_expr} IS NOT NULL
                     THEN 1 ELSE 0 END) AS costable_attempts,
            COALESCE(SUM(CASE WHEN {prompt_expr} IS NOT NULL AND {completion_expr} IS NOT NULL
                              THEN {prompt_expr} ELSE 0 END), 0) AS cost_prompt_tokens,
            COALESCE(SUM(CASE WHEN {prompt_expr} IS NOT NULL AND {completion_expr} IS NOT NULL
                              THEN {completion_expr} ELSE 0 END), 0) AS cost_completion_tokens
        FROM attempts
        WHERE outcome <> 'running'
        GROUP BY provider, model
        ORDER BY provider, model
        """
    ).fetchall()
    terminal = known = unknown = prompt = completion = total = 0
    priced_attempts = 0
    known_input_cost = Decimal(0)
    known_output_cost = Decimal(0)
    known_cost = Decimal(0)
    pricing_entries = pricing["entries"] if pricing is not None else {}
    by_model: list[dict[str, Any]] = []
    for row in usage_rows:
        provider = str(row["provider"])
        model = str(row["model"])
        row_terminal = int(row["terminal_attempts"] or 0)
        row_known = int(row["known_attempts"] or 0)
        row_unknown = int(row["unknown_attempts"] or 0)
        row_prompt = int(row["prompt_tokens"] or 0)
        row_completion = int(row["completion_tokens"] or 0)
        row_total = int(row["total_tokens"] or 0)
        terminal += row_terminal
        known += row_known
        unknown += row_unknown
        prompt += row_prompt
        completion += row_completion
        total += row_total
        prices = pricing_entries.get((provider, model))
        model_cost: float | None = None
        model_input_cost: float | None = None
        model_output_cost: float | None = None
        model_priced = 0
        if prices is not None:
            model_priced = int(row["costable_attempts"] or 0)
            priced_prompt = int(row["cost_prompt_tokens"] or 0)
            priced_completion = int(row["cost_completion_tokens"] or 0)
            input_amount = Decimal(priced_prompt) / Decimal(1_000_000) * prices[0]
            output_amount = Decimal(priced_completion) / Decimal(1_000_000) * prices[1]
            amount = input_amount + output_amount
            known_input_cost += input_amount
            known_output_cost += output_amount
            known_cost += amount
            priced_attempts += model_priced
            model_input_cost = float(input_amount)
            model_output_cost = float(output_amount)
            model_cost = float(amount)
        by_model.append(
            {
                "provider": provider,
                "model": model,
                "terminalAttempts": row_terminal,
                "knownUsageAttempts": row_known,
                "unknownUsageAttempts": row_unknown,
                "promptTokens": row_prompt,
                "completionTokens": row_completion,
                "totalTokens": row_total,
                "pricedAttempts": model_priced,
                "inputCost": model_input_cost,
                "outputCost": model_output_cost,
                "knownCost": model_cost,
            }
        )
    usage_report = {
        "source": "provider-reported",
        "schemaAvailable": all(
            column in columns
            for column in ("prompt_tokens", "completion_tokens", "total_tokens")
        ),
        "terminalAttempts": terminal,
        "knownUsageAttempts": known,
        "unknownUsageAttempts": unknown,
        "promptTokens": prompt,
        "completionTokens": completion,
        "totalTokens": total,
        "byProviderModel": by_model,
    }
    unpriced_attempts = terminal - priced_attempts
    cost_report = {
        "status": (
            "unavailable"
            if pricing is None or (terminal and priced_attempts == 0)
            else ("complete" if unpriced_attempts == 0 else "partial")
        ),
        "currency": pricing["currency"] if pricing is not None else None,
        "pricedAttempts": priced_attempts,
        "unpricedAttempts": unpriced_attempts,
        "inputCost": float(known_input_cost) if pricing is not None else None,
        "outputCost": float(known_output_cost) if pricing is not None else None,
        "knownCost": float(known_cost) if pricing is not None else None,
        "isProviderInvoice": False,
    }

    sample_rows = conn.execute(
        f"""
        SELECT batch_id, provider, model,
            COUNT(*) AS sample_count,
            SUM({prompt_expr}) AS prompt_tokens,
            SUM({completion_expr}) AS completion_tokens
        FROM attempts
        WHERE outcome = 'succeeded'
          AND {prompt_expr} IS NOT NULL
          AND {completion_expr} IS NOT NULL
        GROUP BY batch_id, provider, model
        """
    ).fetchall()
    global_sample = [0, 0, 0]
    category_samples: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    global_priced = [0, Decimal(0)]
    category_priced: dict[str, list[Any]] = defaultdict(lambda: [0, Decimal(0)])
    for row in sample_rows:
        category = batch_categories.get(str(row["batch_id"]), "")
        if not category:
            continue
        count = int(row["sample_count"])
        prompt_sum = int(row["prompt_tokens"])
        completion_sum = int(row["completion_tokens"])
        global_sample[0] += count
        global_sample[1] += prompt_sum
        global_sample[2] += completion_sum
        category_samples[category][0] += count
        category_samples[category][1] += prompt_sum
        category_samples[category][2] += completion_sum
        prices = pricing_entries.get((str(row["provider"]), str(row["model"])))
        if prices is not None:
            amount = _cost(prompt_sum, completion_sum, prices)
            global_priced[0] += count
            global_priced[1] += amount
            category_priced[category][0] += count
            category_priced[category][1] += amount

    remaining_items = sum(remaining_by_category.values())
    estimate: dict[str, Any] = {
        "status": "unavailable",
        "minimumSampleSize": MINIMUM_ESTIMATE_SAMPLES,
        "remainingExecutableItems": remaining_items,
        "sampledSucceededAttempts": global_sample[0],
        "estimatedPromptTokens": None,
        "estimatedCompletionTokens": None,
        "estimatedCost": None,
        "currency": pricing["currency"] if pricing is not None else None,
    }
    if remaining_items == 0:
        estimate.update(
            status="available",
            estimatedPromptTokens=0,
            estimatedCompletionTokens=0,
            estimatedCost=0.0 if pricing is not None else None,
        )
    elif global_sample[0] >= MINIMUM_ESTIMATE_SAMPLES:
        estimated_prompt = Decimal(0)
        estimated_completion = Decimal(0)
        for category, remaining in remaining_by_category.items():
            sample = category_samples.get(category, [0, 0, 0])
            chosen = sample if sample[0] >= MINIMUM_ESTIMATE_SAMPLES else global_sample
            estimated_prompt += Decimal(chosen[1]) / Decimal(chosen[0]) * remaining
            estimated_completion += Decimal(chosen[2]) / Decimal(chosen[0]) * remaining
        estimate.update(
            status="available",
            estimatedPromptTokens=int(estimated_prompt.to_integral_value()),
            estimatedCompletionTokens=int(estimated_completion.to_integral_value()),
        )
        if pricing is not None and global_priced[0] >= MINIMUM_ESTIMATE_SAMPLES:
            estimated_cost = Decimal(0)
            for category, remaining in remaining_by_category.items():
                priced = category_priced.get(category, [0, Decimal(0)])
                chosen = (
                    priced
                    if priced[0] >= MINIMUM_ESTIMATE_SAMPLES
                    else global_priced
                )
                estimated_cost += chosen[1] / Decimal(chosen[0]) * remaining
            estimate["estimatedCost"] = float(estimated_cost)
    return attempt_report, usage_report, cost_report, error_breakdown | {"__estimate__": estimate}


def build_production_accounting_report(
    workspace: Path,
    *,
    pricing_path: Path | None = None,
) -> dict[str, Any]:
    operator = build_operator_report(workspace)
    pricing = _load_pricing(pricing_path)
    total = operator.completion.total
    execution = {
        status: {
            "count": int(operator.execution_counts.get(status, 0)),
            "percent": _percent(int(operator.execution_counts.get(status, 0)), total),
        }
        for status in (
            "pending", "running", "succeeded", "failed-retryable",
            "failed-final", "invalidated", "skipped",
        )
    }
    qa = {
        status: {
            "count": int(operator.qa_counts.get(status, 0)),
            "percent": _percent(int(operator.qa_counts.get(status, 0)), total),
        }
        for status in ("not checked", "stale", "PASS", "RETRY", "REVIEW", "FAIL")
    }
    completion = {
        status: {
            "count": int(operator.completion.counts.get(status, 0)),
            "percent": _percent(int(operator.completion.counts.get(status, 0)), total),
        }
        for status in (
            "MERGE_READY", "WAITING_TRANSLATION", "WAITING_RETRY",
            "WAITING_REVIEW", "BLOCKED",
        )
    }

    category_data: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "total": 0, "succeeded": 0, "remaining": 0, "retry": 0,
            "failedFinal": 0, "qaPass": 0, "qaReview": 0, "mergeReady": 0,
        }
    )
    batch_categories: dict[str, str] = {}
    remaining_by_category: dict[str, int] = defaultdict(int)
    for row in operator.completion.rows:
        item = category_data[row.primary_category]
        batch_categories[row.batch_id] = row.primary_category
        item["total"] += 1
        if row.execution_status == "succeeded":
            item["succeeded"] += 1
        else:
            item["remaining"] += 1
        if row.disposition == DISPOSITION_WAITING_RETRY:
            item["retry"] += 1
        if row.execution_status == "failed-final":
            item["failedFinal"] += 1
        if row.qa_status == "checked" and row.qa_route == QA_ROUTE_PASS:
            item["qaPass"] += 1
        if row.qa_status == "checked" and row.qa_route == QA_ROUTE_REVIEW:
            item["qaReview"] += 1
        if row.disposition == DISPOSITION_MERGE_READY:
            item["mergeReady"] += 1
        if row.execution_status in EXECUTABLE_STATUSES:
            remaining_by_category[row.primary_category] += 1
    categories = []
    for category, item in category_data.items():
        categories.append(
            {
                "primaryCategory": category,
                **item,
                "succeededPercent": _percent(item["succeeded"], item["total"]),
                "mergeReadyPercent": _percent(item["mergeReady"], item["total"]),
            }
        )
    categories.sort(key=lambda item: (-int(item["remaining"]), str(item["primaryCategory"])))

    db = operator.database
    uri = db.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        runs = _run_rows(conn)
        attempts, usage, cost, errors_and_estimate = _attempt_and_usage_report(
            conn,
            pricing=pricing,
            batch_categories=batch_categories,
            remaining_by_category=remaining_by_category,
        )
    estimate = errors_and_estimate.pop("__estimate__")
    return {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "workspace": {
            "sourceLocale": operator.source_locale,
            "targetLocale": operator.target_locale,
            "batchPlanFingerprint": operator.batch_plan_fingerprint,
            "rulesetVersion": operator.ruleset_version,
            "rulesetFingerprint": operator.ruleset_fingerprint,
            "totalExecutionUniverse": total,
        },
        "execution": execution,
        "qa": qa,
        "completion": completion,
        "categories": categories,
        "runs": runs,
        "attempts": attempts,
        "errors": errors_and_estimate,
        "usage": usage,
        "cost": cost,
        "remainingEstimate": estimate,
    }


def write_production_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def print_production_accounting_report(report: dict[str, Any]) -> None:
    workspace = report["workspace"]
    total = int(workspace["totalExecutionUniverse"])
    succeeded = report["execution"]["succeeded"]
    remaining = total - int(succeeded["count"])
    print("Production report")
    print(f"Source locale: {workspace['sourceLocale']}")
    print(f"Target locale: {workspace['targetLocale']}")
    print(f"Batch fingerprint: {workspace['batchPlanFingerprint']}")
    print("Overall:")
    print(f"  total: {total}")
    print(f"  succeeded: {succeeded['count']} ({succeeded['percent']:.2f}%)")
    print(f"  remaining: {remaining} ({_percent(remaining, total):.2f}%)")
    for section_name in ("execution", "qa", "completion"):
        print(f"{section_name.title()}:")
        for name, value in report[section_name].items():
            print(f"  {name}: {value['count']} ({value['percent']:.2f}%)")
    usage = report["usage"]
    print("Usage (provider-reported):")
    print(f"  input/prompt tokens: {usage['promptTokens']}")
    print(f"  output/completion tokens: {usage['completionTokens']}")
    print(f"  total tokens: {usage['totalTokens']}")
    print(f"  known usage attempts: {usage['knownUsageAttempts']}")
    print(f"  unknown usage attempts: {usage['unknownUsageAttempts']}")
    cost = report["cost"]
    print("Cost:")
    if cost["knownCost"] is None:
        print("  unavailable (provide an exact provider/model pricing file)")
    else:
        print(f"  known input cost {cost['currency']}: {cost['inputCost']:.6f}")
        print(f"  known output cost {cost['currency']}: {cost['outputCost']:.6f}")
        print(f"  known cost {cost['currency']}: {cost['knownCost']:.6f}")
        print(f"  coverage: {cost['status']} ({cost['unpricedAttempts']} unpriced attempts)")
    estimate = report["remainingEstimate"]
    print("Remaining estimate:")
    if estimate["status"] != "available":
        print(
            "  unavailable "
            f"(requires {estimate['minimumSampleSize']} succeeded usage samples; "
            f"have {estimate['sampledSucceededAttempts']})"
        )
    else:
        print(f"  executable items: {estimate['remainingExecutableItems']}")
        print(f"  estimated input/prompt tokens: {estimate['estimatedPromptTokens']}")
        print(f"  estimated output/completion tokens: {estimate['estimatedCompletionTokens']}")
        if estimate["estimatedCost"] is not None:
            print(
                f"  estimated remaining {estimate['currency']}: "
                f"{estimate['estimatedCost']:.6f}"
            )
    print("Top errors:")
    if report["errors"]:
        for code, count in list(report["errors"].items())[:10]:
            print(f"  {code}: {count}")
    else:
        print("  none")
    print("Categories:")
    for item in report["categories"]:
        print(
            f"  {item['primaryCategory']}: total={item['total']} "
            f"succeeded={item['succeeded']} ({item['succeededPercent']:.2f}%) "
            f"remaining={item['remaining']} retry={item['retry']} "
            f"QA_PASS={item['qaPass']} QA_REVIEW={item['qaReview']} "
            f"MERGE_READY={item['mergeReady']} ({item['mergeReadyPercent']:.2f}%)"
        )
    print("Runs:")
    if report["runs"]:
        for run in report["runs"]:
            print(
                f"  {run['runId']}: {run['provider']}/{run['model']} "
                f"status={run['status']} attempts={run['attemptCount']} "
                f"success={run['successCount']} retryable={run['retryableFailures']} "
                f"final={run['finalFailures']} HTTP_429={run['http429Count']} "
                f"HTTP_5xx={run['http5xxCount']}"
            )
    else:
        print("  none")
