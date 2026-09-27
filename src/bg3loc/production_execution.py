from __future__ import annotations

from argparse import Namespace
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time
from typing import Callable

from bg3loc.commands.translation_state import (
    run_openai_compatible_start,
    run_openai_compatible_worker,
    run_run_finish,
)
from bg3loc.execution_state import TranslationExecutionStore
from bg3loc.execution_runner import RetryPacingPolicy
from bg3loc.production_workspace import verify_production_workspace


@dataclass(frozen=True, slots=True)
class OpenAICompatibleExecutionRequest:
    workspace: Path
    base_url: str
    model: str
    run_id: str
    worker_id: str
    api_key_env: str = "BG3LOC_API_KEY"
    timeout_seconds: float = 120.0
    max_output_tokens: int | None = None
    temperature: float | None = None
    lease_seconds: int = 300
    max_attempts: int = 3
    max_items: int | None = None
    retry_backoff_base_seconds: float = 2.0
    retry_backoff_max_seconds: float = 60.0
    min_request_interval_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class OpenAICompatibleExecutionResult:
    run_id: str
    run_status: str
    provider: str
    model: str
    claimed: int
    succeeded: int
    failed_retryable: int
    failed_final: int
    database_summary: dict[str, int]


def _preflight_workspace(workspace: Path) -> tuple[Path, Path, Path, dict[str, object]]:
    binding = verify_production_workspace(workspace)
    return binding.database, binding.batch_plan, binding.ruleset, binding.manifest


def _attempt_summary(db_path: Path, run_id: str) -> dict[str, int]:
    with closing(sqlite3.connect(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT outcome, COUNT(*)
            FROM attempts
            WHERE run_id = ?
            GROUP BY outcome
            """,
            (run_id,),
        ).fetchall()
    counts = {str(outcome): int(count) for outcome, count in rows}
    return {
        "claimed": sum(counts.values()),
        "succeeded": counts.get("succeeded", 0),
        "failed_retryable": counts.get("failed-retryable", 0),
        "failed_final": counts.get("failed-final", 0),
    }


def execute_openai_compatible(
    request: OpenAICompatibleExecutionRequest,
    *,
    sleeper: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> OpenAICompatibleExecutionResult:
    if not request.base_url.strip():
        raise RuntimeError("--base-url must not be empty")
    if not request.model.strip():
        raise RuntimeError("--model must not be empty")
    if not request.run_id.strip():
        raise RuntimeError("--run-id must not be empty")
    if not request.worker_id.strip():
        raise RuntimeError("--worker-id must not be empty")
    if request.timeout_seconds <= 0:
        raise RuntimeError("--timeout-seconds must be positive")
    if request.lease_seconds <= 0:
        raise RuntimeError("--lease-seconds must be positive")
    if request.max_attempts <= 0:
        raise RuntimeError("--max-attempts must be positive")
    if request.max_items is not None and request.max_items <= 0:
        raise RuntimeError("--max-items must be positive")
    if request.max_output_tokens is not None and request.max_output_tokens <= 0:
        raise RuntimeError("--max-output-tokens must be positive")
    if request.retry_backoff_base_seconds < 0:
        raise RuntimeError("--retry-backoff-base-seconds must be non-negative")
    if request.retry_backoff_max_seconds < 0:
        raise RuntimeError("--retry-backoff-max-seconds must be non-negative")
    if request.min_request_interval_seconds < 0:
        raise RuntimeError("--min-request-interval-seconds must be non-negative")

    retry_policy = RetryPacingPolicy(
        backoff_base_seconds=request.retry_backoff_base_seconds,
        backoff_max_seconds=request.retry_backoff_max_seconds,
        min_request_interval_seconds=request.min_request_interval_seconds,
    )

    db_path, batch_plan, ruleset_path, _manifest = _preflight_workspace(
        request.workspace
    )
    store = TranslationExecutionStore(db_path)
    if store.get_run(request.run_id) is not None:
        raise RuntimeError(
            f"run_id already exists: {request.run_id}; choose a new --run-id to resume"
        )

    common = {
        "db": str(db_path),
        "batch_plan": str(batch_plan),
        "ruleset": str(ruleset_path),
        "base_url": request.base_url,
        "model": request.model,
        "timeout_seconds": request.timeout_seconds,
        "max_output_tokens": request.max_output_tokens,
        "temperature": request.temperature,
    }

    run_openai_compatible_start(
        Namespace(
            **common,
            run_id=request.run_id,
        )
    )

    run_openai_compatible_worker(
        Namespace(
            **common,
            run_id=request.run_id,
            worker_id=request.worker_id,
            api_key_env=request.api_key_env,
            lease_seconds=request.lease_seconds,
            max_attempts=request.max_attempts,
            max_items=request.max_items,
            retry_policy=retry_policy,
            sleeper=sleeper,
            monotonic=monotonic,
        )
    )

    run_run_finish(Namespace(db=str(db_path), run_id=request.run_id))

    run = store.get_run(request.run_id)
    if run is None:
        raise RuntimeError(f"run disappeared after execution: {request.run_id}")
    attempts = _attempt_summary(db_path, request.run_id)
    return OpenAICompatibleExecutionResult(
        run_id=request.run_id,
        run_status=str(run["status"]),
        provider=str(run["provider"]),
        model=str(run["model"]),
        claimed=attempts["claimed"],
        succeeded=attempts["succeeded"],
        failed_retryable=attempts["failed_retryable"],
        failed_final=attempts["failed_final"],
        database_summary=store.summary(),
    )
