from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import time
from typing import Callable, Protocol

from bg3loc.execution_state import ClaimedAttempt, TranslationExecutionStore
from bg3loc.translation_request import TranslationRequest


@dataclass(frozen=True, slots=True)
class ProviderTokenUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class TranslationSuccess:
    text: str
    provider_request_id: str | None = None
    usage: ProviderTokenUsage | None = None


@dataclass(frozen=True, slots=True)
class TranslationFailure:
    error_code: str
    error_message: str
    retryable: bool
    provider_request_id: str | None = None
    retry_after_seconds: float | None = None
    usage: ProviderTokenUsage | None = None


TranslationOutcome = TranslationSuccess | TranslationFailure


class TranslationProvider(Protocol):
    def __call__(self, request: TranslationRequest) -> TranslationOutcome:
        ...


class TranslationRequestResolver(Protocol):
    def __call__(self, claim: ClaimedAttempt) -> TranslationRequest:
        ...


@dataclass(frozen=True, slots=True)
class WorkerSummary:
    claimed: int
    succeeded: int
    failed_retryable: int
    failed_final: int


@dataclass(frozen=True, slots=True)
class RetryPacingPolicy:
    backoff_base_seconds: float = 2.0
    backoff_max_seconds: float = 60.0
    min_request_interval_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.backoff_base_seconds < 0:
            raise ValueError("backoff_base_seconds must be non-negative")
        if self.backoff_max_seconds < 0:
            raise ValueError("backoff_max_seconds must be non-negative")
        if self.min_request_interval_seconds < 0:
            raise ValueError("min_request_interval_seconds must be non-negative")

    def retry_delay(self, failure: TranslationFailure, *, streak: int) -> float:
        if failure.retry_after_seconds is not None:
            requested = max(0.0, float(failure.retry_after_seconds))
            return min(requested, self.backoff_max_seconds)
        if self.backoff_base_seconds == 0 or self.backoff_max_seconds == 0:
            return 0.0
        return min(
            self.backoff_max_seconds,
            self.backoff_base_seconds * (2 ** max(0, streak - 1)),
        )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def run_worker(
    store: TranslationExecutionStore,
    *,
    run_id: str,
    worker_id: str,
    provider: TranslationProvider,
    request_resolver: TranslationRequestResolver | None = None,
    max_attempts: int = 3,
    lease_seconds: int = 300,
    max_items: int | None = None,
    clock: Callable[[], datetime] = utc_now,
    retry_policy: RetryPacingPolicy | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> WorkerSummary:
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    if max_items is not None and max_items <= 0:
        raise ValueError("max_items must be positive when provided")

    claimed = 0
    succeeded = 0
    failed_retryable = 0
    failed_final = 0
    retryable_streak = 0
    pending_retry_delay = 0.0
    last_request_started: float | None = None

    while max_items is None or claimed < max_items:
        started = clock()
        if retry_policy is not None:
            interval_delay = 0.0
            if last_request_started is not None:
                interval_delay = max(
                    0.0,
                    retry_policy.min_request_interval_seconds
                    - (monotonic() - last_request_started),
                )
            delay = max(pending_retry_delay, interval_delay)
            if delay > 0 and store.has_executable(
                now=iso_utc(started), max_attempts=max_attempts
            ):
                sleeper(delay)
                started = clock()
            pending_retry_delay = 0.0
        claim = store.claim_next(
            run_id=run_id,
            worker_id=worker_id,
            lease_expires_at=iso_utc(started + timedelta(seconds=lease_seconds)),
            started_at=iso_utc(started),
            max_attempts=max_attempts,
        )
        if claim is None:
            break

        claimed += 1

        if request_resolver is None:
            request = TranslationRequest(
                content_uid=claim.content_uid,
                batch_id=claim.batch_id,
                attempt_number=claim.attempt_number,
                input_hash=claim.input_hash,
                source_text="",
                primary_category="",
                canonical_group_key="",
                context_group_keys=(),
                protected_tokens=(),
            )
        else:
            try:
                request = request_resolver(claim)
            except Exception as exc:
                outcome = TranslationFailure(
                    error_code="MATERIAL_RESOLUTION_ERROR",
                    error_message=f"{type(exc).__name__}: {exc}",
                    retryable=False,
                )
            else:
                try:
                    last_request_started = monotonic()
                    outcome = provider(request)
                except Exception as exc:
                    outcome = TranslationFailure(
                        error_code="PROVIDER_EXCEPTION",
                        error_message=f"{type(exc).__name__}: {exc}",
                        retryable=False,
                    )
        if request_resolver is None:
            try:
                last_request_started = monotonic()
                outcome = provider(request)
            except Exception as exc:
                outcome = TranslationFailure(
                    error_code="PROVIDER_EXCEPTION",
                    error_message=f"{type(exc).__name__}: {exc}",
                    retryable=False,
                )

        finished_at = iso_utc(clock())

        if isinstance(outcome, TranslationSuccess):
            output_hash = hashlib.sha256(outcome.text.encode("utf-8")).hexdigest()
            store.complete_success(
                attempt_id=claim.attempt_id,
                worker_id=worker_id,
                translated_text=outcome.text,
                output_hash=output_hash,
                finished_at=finished_at,
                provider_request_id=outcome.provider_request_id,
                prompt_tokens=(outcome.usage.prompt_tokens if outcome.usage else None),
                completion_tokens=(
                    outcome.usage.completion_tokens if outcome.usage else None
                ),
                total_tokens=(outcome.usage.total_tokens if outcome.usage else None),
            )
            succeeded += 1
            retryable_streak = 0
            pending_retry_delay = 0.0
            continue

        status = store.complete_failure(
            attempt_id=claim.attempt_id,
            worker_id=worker_id,
            error_code=outcome.error_code,
            error_message=outcome.error_message,
            retryable=outcome.retryable,
            max_attempts=max_attempts,
            finished_at=finished_at,
            provider_request_id=outcome.provider_request_id,
            prompt_tokens=(outcome.usage.prompt_tokens if outcome.usage else None),
            completion_tokens=(
                outcome.usage.completion_tokens if outcome.usage else None
            ),
            total_tokens=(outcome.usage.total_tokens if outcome.usage else None),
        )
        if status == "failed-retryable":
            failed_retryable += 1
        else:
            failed_final += 1
        if outcome.retryable:
            retryable_streak += 1
            if retry_policy is not None:
                pending_retry_delay = retry_policy.retry_delay(
                    outcome, streak=retryable_streak
                )
        else:
            retryable_streak = 0
            pending_retry_delay = 0.0

    return WorkerSummary(
        claimed=claimed,
        succeeded=succeeded,
        failed_retryable=failed_retryable,
        failed_final=failed_final,
    )
