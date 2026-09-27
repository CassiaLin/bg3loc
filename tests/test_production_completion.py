from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest

from bg3loc.production_completion import (
    DISPOSITION_BLOCKED,
    DISPOSITION_MERGE_READY,
    DISPOSITION_WAITING_RETRY,
    DISPOSITION_WAITING_REVIEW,
    DISPOSITION_WAITING_TRANSLATION,
    REASON_FAILED_FINAL,
    REASON_INVALIDATED,
    REASON_MISSING_OUTPUT,
    REASON_PENDING,
    REASON_QA_FAIL,
    REASON_QA_MISSING,
    REASON_QA_OUTPUT_MISMATCH,
    REASON_QA_RETRY,
    REASON_QA_REVIEW,
    REASON_QA_STALE,
    REASON_READY,
    REASON_RETRYABLE,
    REASON_RUNNING,
    REASON_SKIPPED,
    REASON_UNKNOWN_EXECUTION_STATUS,
    REASON_UNKNOWN_QA_ROUTE,
    build_production_completion_view,
    derive_production_disposition,
)
from bg3loc.execution_state import ExecutionItem, TranslationExecutionStore
from bg3loc.qa import QaInput, evaluate_translation
from bg3loc.qa_state import QA_STATUS_CHECKED, QA_STATUS_STALE, StoredQaResult, TranslationQaStore


def _state(status: str, *, text: object = "譯文", output_hash: object = "out") -> dict[str, object]:
    return {
        "content_uid": "uid-a",
        "batch_id": "batch-a",
        "status": status,
        "translated_text": text,
        "output_hash": output_hash,
        "last_attempt_id": 7,
        "attempt_count": 2,
    }


def _qa(route: str, *, status: str = QA_STATUS_CHECKED, output_hash: str = "out") -> StoredQaResult:
    return StoredQaResult(
        content_uid="uid-a",
        qa_status=status,
        route=route,
        issue_count=0,
        qa_rule_set_version="1.2",
        qa_input_hash="qa-hash",
        output_hash=output_hash,
        checked_at="2026-09-24T00:00:00Z",
        issues=(),
    )


class TestProductionCompletion(unittest.TestCase):
    def test_succeeded_current_pass_is_merge_ready(self) -> None:
        result = derive_production_disposition(_state("succeeded"), primary_category="bark", qa_result=_qa("PASS"))
        self.assertEqual((result.disposition, result.reason_code), (DISPOSITION_MERGE_READY, REASON_READY))

    def test_execution_waiting_states(self) -> None:
        cases = (
            ("pending", REASON_PENDING),
            ("running", REASON_RUNNING),
            ("invalidated", REASON_INVALIDATED),
        )
        for status, reason in cases:
            with self.subTest(status=status):
                result = derive_production_disposition(_state(status), primary_category="bark", qa_result=None)
                self.assertEqual(result.disposition, DISPOSITION_WAITING_TRANSLATION)
                self.assertEqual(result.reason_code, reason)

    def test_failed_retryable_waits_for_retry(self) -> None:
        result = derive_production_disposition(_state("failed-retryable", text=None, output_hash=None), primary_category="bark", qa_result=None)
        self.assertEqual((result.disposition, result.reason_code), (DISPOSITION_WAITING_RETRY, REASON_RETRYABLE))

    def test_succeeded_retry_and_review_routes(self) -> None:
        retry = derive_production_disposition(_state("succeeded"), primary_category="bark", qa_result=_qa("RETRY"))
        review = derive_production_disposition(_state("succeeded"), primary_category="bark", qa_result=_qa("REVIEW"))
        self.assertEqual((retry.disposition, retry.reason_code), (DISPOSITION_WAITING_RETRY, REASON_QA_RETRY))
        self.assertEqual((review.disposition, review.reason_code), (DISPOSITION_WAITING_REVIEW, REASON_QA_REVIEW))

    def test_blocked_states_fail_closed(self) -> None:
        cases = (
            (_state("failed-final", text=None, output_hash=None), None, REASON_FAILED_FINAL),
            (_state("skipped", text=None, output_hash=None), None, REASON_SKIPPED),
            (_state("mystery"), None, REASON_UNKNOWN_EXECUTION_STATUS),
            (_state("succeeded", text=None, output_hash=None), _qa("PASS"), REASON_MISSING_OUTPUT),
            (_state("succeeded"), None, REASON_QA_MISSING),
            (_state("succeeded"), _qa("PASS", status=QA_STATUS_STALE), REASON_QA_STALE),
            (_state("succeeded"), _qa("PASS", output_hash="old"), REASON_QA_OUTPUT_MISMATCH),
            (_state("succeeded"), _qa("FAIL"), REASON_QA_FAIL),
            (_state("succeeded"), _qa("UNKNOWN"), REASON_UNKNOWN_QA_ROUTE),
        )
        for state, qa_result, reason in cases:
            with self.subTest(reason=reason):
                result = derive_production_disposition(state, primary_category="bark", qa_result=qa_result)
                self.assertEqual(result.disposition, DISPOSITION_BLOCKED)
                self.assertEqual(result.reason_code, reason)

    def test_result_preserves_operational_identity(self) -> None:
        result = derive_production_disposition(_state("succeeded"), primary_category="bark", qa_result=_qa("PASS"))
        self.assertEqual(result.content_uid, "uid-a")
        self.assertEqual(result.primary_category, "bark")
        self.assertEqual(result.batch_id, "batch-a")
        self.assertEqual(result.last_attempt_id, 7)
        self.assertEqual(result.attempt_count, 2)


class TestProductionCompletionView(unittest.TestCase):
    def _fixture(self) -> tuple[tempfile.TemporaryDirectory, Path, Path]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        plan_dir = root / "plan"
        materials = plan_dir / "materials"
        materials.mkdir(parents=True)

        plan = {
            "batchPlanFingerprint": "completion-plan",
            "batches": [
                {
                    "batchId": "bark-0001",
                    "primaryCategory": "bark",
                    "recordCount": 3,
                },
                {
                    "batchId": "ui-0001",
                    "primaryCategory": "ui",
                    "recordCount": 3,
                },
            ],
        }
        plan_path = plan_dir / "batch-plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        (materials / "bark-0001.jsonl").write_text(
            "".join(
                json.dumps(row, ensure_ascii=False) + "\n"
                for row in (
                    {"ContentUid": "uid-pass", "batchId": "bark-0001", "primaryCategory": "bark", "SourceText": "Hello"},
                    {"ContentUid": "uid-review", "batchId": "bark-0001", "primaryCategory": "bark", "SourceText": "Open the ancient gate"},
                    {"ContentUid": "uid-retry", "batchId": "bark-0001", "primaryCategory": "bark", "SourceText": "Retry me"},
                )
            ),
            encoding="utf-8",
        )
        (materials / "ui-0001.jsonl").write_text(
            "".join(
                json.dumps(row, ensure_ascii=False) + "\n"
                for row in (
                    {"ContentUid": "uid-pending", "batchId": "ui-0001", "primaryCategory": "ui", "SourceText": "Pending"},
                    {"ContentUid": "uid-final", "batchId": "ui-0001", "primaryCategory": "ui", "SourceText": "Final"},
                    {"ContentUid": "uid-stale", "batchId": "ui-0001", "primaryCategory": "ui", "SourceText": "Save"},
                )
            ),
            encoding="utf-8",
        )

        db = root / "execution.sqlite3"
        execution = TranslationExecutionStore(db)
        execution.initialize()
        execution.seed_items(
            [
                ExecutionItem("uid-pass", "bark-0001", "input-pass"),
                ExecutionItem("uid-review", "bark-0001", "input-review"),
                ExecutionItem("uid-retry", "bark-0001", "input-retry"),
                ExecutionItem("uid-pending", "ui-0001", "input-pending"),
                ExecutionItem("uid-final", "ui-0001", "input-final"),
                ExecutionItem("uid-stale", "ui-0001", "input-stale"),
            ],
            updated_at="seed",
        )

        with closing(execution.connect()) as conn, conn:
            conn.execute(
                "UPDATE content_state SET status='succeeded', translated_text='你好', output_hash='out-pass' WHERE content_uid='uid-pass'"
            )
            conn.execute(
                "UPDATE content_state SET status='succeeded', translated_text='Open the ancient gate', output_hash='out-review' WHERE content_uid='uid-review'"
            )
            conn.execute(
                "UPDATE content_state SET status='failed-retryable', attempt_count=1 WHERE content_uid='uid-retry'"
            )
            conn.execute(
                "UPDATE content_state SET status='failed-final', attempt_count=3 WHERE content_uid='uid-final'"
            )
            conn.execute(
                "UPDATE content_state SET status='succeeded', translated_text='儲存', output_hash='out-stale' WHERE content_uid='uid-stale'"
            )

        qa = TranslationQaStore(db)
        qa.initialize()
        pass_result = evaluate_translation(
            QaInput(
                content_uid="uid-pass",
                source_text="Hello",
                translated_text="你好",
                primary_category="bark",
                required_protected_tokens=(),
            )
        )
        review_result = evaluate_translation(
            QaInput(
                content_uid="uid-review",
                source_text="Open the ancient gate",
                translated_text="Open the ancient gate",
                primary_category="bark",
                required_protected_tokens=(),
            )
        )
        stale_result = evaluate_translation(
            QaInput(
                content_uid="uid-stale",
                source_text="Save",
                translated_text="儲存",
                primary_category="ui",
                required_protected_tokens=(),
            )
        )
        qa.record_result(pass_result, checked_at="2026-09-24T00:00:00Z")
        qa.record_result(review_result, checked_at="2026-09-24T00:00:01Z")
        qa.record_result(stale_result, checked_at="2026-09-24T00:00:02Z")

        with closing(execution.connect()) as conn, conn:
            conn.execute(
                "UPDATE content_state SET translated_text='存檔', output_hash='out-stale-new' WHERE content_uid='uid-stale'"
            )

        return temp, db, plan_path

    def test_view_covers_every_uid_once_and_reconciles_counts(self) -> None:
        temp, db, plan = self._fixture()
        self.addCleanup(temp.cleanup)

        view = build_production_completion_view(db, plan)

        self.assertEqual(view.total, 6)
        self.assertEqual(
            view.counts,
            {
                DISPOSITION_MERGE_READY: 1,
                DISPOSITION_WAITING_TRANSLATION: 1,
                DISPOSITION_WAITING_RETRY: 1,
                DISPOSITION_WAITING_REVIEW: 1,
                DISPOSITION_BLOCKED: 2,
            },
        )
        self.assertEqual(sum(view.counts.values()), view.total)
        self.assertEqual(len({row.content_uid for row in view.rows}), view.total)

        by_uid = {row.content_uid: row for row in view.rows}
        self.assertEqual(by_uid["uid-pass"].disposition, DISPOSITION_MERGE_READY)
        self.assertEqual(by_uid["uid-review"].disposition, DISPOSITION_WAITING_REVIEW)
        self.assertEqual(by_uid["uid-retry"].disposition, DISPOSITION_WAITING_RETRY)
        self.assertEqual(by_uid["uid-pending"].disposition, DISPOSITION_WAITING_TRANSLATION)
        self.assertEqual(by_uid["uid-final"].disposition, DISPOSITION_BLOCKED)
        self.assertEqual(by_uid["uid-stale"].reason_code, REASON_QA_STALE)

    def test_view_reports_per_category_counts(self) -> None:
        temp, db, plan = self._fixture()
        self.addCleanup(temp.cleanup)

        view = build_production_completion_view(db, plan)

        self.assertEqual(view.by_category["bark"][DISPOSITION_MERGE_READY], 1)
        self.assertEqual(view.by_category["bark"][DISPOSITION_WAITING_REVIEW], 1)
        self.assertEqual(view.by_category["bark"][DISPOSITION_WAITING_RETRY], 1)
        self.assertEqual(view.by_category["ui"][DISPOSITION_WAITING_TRANSLATION], 1)
        self.assertEqual(view.by_category["ui"][DISPOSITION_BLOCKED], 2)

    def test_view_is_deterministic_on_repeat(self) -> None:
        temp, db, plan = self._fixture()
        self.addCleanup(temp.cleanup)

        first = build_production_completion_view(db, plan)
        second = build_production_completion_view(db, plan)

        self.assertEqual(first, second)

    def test_missing_execution_uid_fails_closed(self) -> None:
        temp, db, plan = self._fixture()
        self.addCleanup(temp.cleanup)

        execution = TranslationExecutionStore(db)
        with closing(execution.connect()) as conn, conn:
            conn.execute("DELETE FROM qa_results WHERE content_uid='uid-pending'")
            conn.execute("DELETE FROM content_state WHERE content_uid='uid-pending'")

        with self.assertRaisesRegex(
            RuntimeError,
            "execution state missing ContentUid from batch material: uid-pending",
        ):
            build_production_completion_view(db, plan)

    def test_foreign_execution_uid_fails_closed(self) -> None:
        temp, db, plan = self._fixture()
        self.addCleanup(temp.cleanup)

        execution = TranslationExecutionStore(db)
        execution.seed_items(
            [ExecutionItem("uid-foreign", "bark-0001", "input-foreign")],
            updated_at="foreign",
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "execution state contains ContentUid outside batch material: uid-foreign",
        ):
            build_production_completion_view(db, plan)


if __name__ == "__main__":
    unittest.main()