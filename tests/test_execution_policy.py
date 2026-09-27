from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from bg3loc.execution_runner import (
    RetryPacingPolicy,
    TranslationFailure,
    TranslationSuccess,
    run_worker,
)
from bg3loc.execution_state import ExecutionItem, TranslationExecutionStore


class FakeTime:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 28, tzinfo=timezone.utc)
        self.monotonic_value = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> datetime:
        return self.current

    def monotonic(self) -> float:
        return self.monotonic_value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.monotonic_value += seconds
        self.current += timedelta(seconds=seconds)


class TestExecutionPolicy(unittest.TestCase):
    def _store(self, root: Path, *uids: str) -> TranslationExecutionStore:
        store = TranslationExecutionStore(root / "execution.sqlite3")
        store.initialize()
        store.seed_items(
            [ExecutionItem(uid, "batch-0001", f"input-{uid}") for uid in uids],
            updated_at="seed",
        )
        store.start_run(
            run_id="run-policy",
            batch_plan_fingerprint="plan",
            provider="test",
            model="test",
            prompt_version="test",
            execution_config_hash="config",
            started_at="2026-09-28T00:00:00Z",
        )
        return store

    def test_retry_after_waits_after_durable_failure_before_next_claim(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = self._store(Path(td), "uid-a")
            fake_time = FakeTime()
            calls = 0

            def provider(_request):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return TranslationFailure(
                        error_code="HTTP_429",
                        error_message="rate limited",
                        retryable=True,
                        retry_after_seconds=10,
                    )
                return TranslationSuccess("完成")

            def sleeper(seconds: float) -> None:
                state = store.get_state("uid-a")
                assert state is not None
                self.assertEqual(state["status"], "failed-retryable")
                self.assertEqual(store.get_attempts("uid-a")[0]["outcome"], "failed-retryable")
                fake_time.sleep(seconds)

            summary = run_worker(
                store,
                run_id="run-policy",
                worker_id="worker",
                provider=provider,
                max_attempts=3,
                retry_policy=RetryPacingPolicy(2, 60, 0),
                clock=fake_time.clock,
                monotonic=fake_time.monotonic,
                sleeper=sleeper,
            )

            self.assertEqual(fake_time.sleeps, [10])
            self.assertEqual(summary.claimed, 2)
            self.assertEqual(store.get_state("uid-a")["status"], "succeeded")

    def test_exponential_fallback_grows_and_caps(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = self._store(Path(td), "uid-a")
            fake_time = FakeTime()
            calls = 0

            def provider(_request):
                nonlocal calls
                calls += 1
                if calls <= 3:
                    return TranslationFailure("HTTP_503", "busy", True)
                return TranslationSuccess("完成")

            run_worker(
                store,
                run_id="run-policy",
                worker_id="worker",
                provider=provider,
                max_attempts=4,
                retry_policy=RetryPacingPolicy(2, 5, 0),
                clock=fake_time.clock,
                monotonic=fake_time.monotonic,
                sleeper=fake_time.sleep,
            )

            self.assertEqual(fake_time.sleeps, [2, 4, 5])
            self.assertEqual(len(store.get_attempts("uid-a")), 4)

    def test_success_resets_global_retryable_streak(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = self._store(Path(td), "uid-a", "uid-b")
            fake_time = FakeTime()
            calls: dict[str, int] = {}

            def provider(request):
                calls[request.content_uid] = calls.get(request.content_uid, 0) + 1
                if calls[request.content_uid] == 1:
                    return TranslationFailure("HTTP_429", "busy", True)
                return TranslationSuccess(f"完成:{request.content_uid}")

            run_worker(
                store,
                run_id="run-policy",
                worker_id="worker",
                provider=provider,
                max_attempts=3,
                retry_policy=RetryPacingPolicy(2, 60, 0),
                clock=fake_time.clock,
                monotonic=fake_time.monotonic,
                sleeper=fake_time.sleep,
            )

            self.assertEqual(fake_time.sleeps, [2, 2])

    def test_max_attempts_remains_attempt_count(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = self._store(Path(td), "uid-a")
            fake_time = FakeTime()

            summary = run_worker(
                store,
                run_id="run-policy",
                worker_id="worker",
                provider=lambda _request: TranslationFailure("HTTP_429", "busy", True),
                max_attempts=2,
                retry_policy=RetryPacingPolicy(3, 60, 0),
                clock=fake_time.clock,
                monotonic=fake_time.monotonic,
                sleeper=fake_time.sleep,
            )

            self.assertEqual(summary.claimed, 2)
            self.assertEqual(len(store.get_attempts("uid-a")), 2)
            self.assertEqual(store.get_state("uid-a")["status"], "failed-final")
            self.assertEqual(fake_time.sleeps, [3])

    def test_max_items_one_does_not_sleep_or_claim_twice(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = self._store(Path(td), "uid-a")
            fake_time = FakeTime()

            summary = run_worker(
                store,
                run_id="run-policy",
                worker_id="worker",
                provider=lambda _request: TranslationFailure(
                    "HTTP_429", "busy", True, retry_after_seconds=10
                ),
                max_attempts=3,
                max_items=1,
                retry_policy=RetryPacingPolicy(2, 60, 0),
                clock=fake_time.clock,
                monotonic=fake_time.monotonic,
                sleeper=fake_time.sleep,
            )

            self.assertEqual(summary.claimed, 1)
            self.assertEqual(fake_time.sleeps, [])
            self.assertEqual(len(store.get_attempts("uid-a")), 1)

    def test_minimum_request_interval_paces_distinct_rows(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = self._store(Path(td), "uid-a", "uid-b")
            fake_time = FakeTime()

            run_worker(
                store,
                run_id="run-policy",
                worker_id="worker",
                provider=lambda request: TranslationSuccess(f"完成:{request.content_uid}"),
                max_attempts=3,
                retry_policy=RetryPacingPolicy(0, 60, 7),
                clock=fake_time.clock,
                monotonic=fake_time.monotonic,
                sleeper=fake_time.sleep,
            )

            self.assertEqual(fake_time.sleeps, [7])


if __name__ == "__main__":
    unittest.main()
