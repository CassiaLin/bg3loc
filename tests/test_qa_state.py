from __future__ import annotations

from contextlib import closing
from pathlib import Path
import tempfile
import unittest

from bg3loc.execution_state import ExecutionItem, TranslationExecutionStore
from bg3loc.qa import (
    QA_ROUTE_PASS,
    QA_ROUTE_RETRY,
    QA_ROUTE_REVIEW,
    QaInput,
    evaluate_translation,
)
from bg3loc.qa_state import (
    QA_STATUS_CHECKED,
    QA_STATUS_STALE,
    TranslationQaStore,
)


class TestTranslationQaState(unittest.TestCase):
    def _completed_db(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        temp = tempfile.TemporaryDirectory()
        db = Path(temp.name) / "execution.sqlite3"
        execution = TranslationExecutionStore(db)
        execution.initialize()
        execution.seed_items(
            [ExecutionItem("uid-a", "batch-a", "input-a")],
            updated_at="seed",
        )
        execution.start_run(
            run_id="run-a",
            batch_plan_fingerprint="plan-a",
            provider="test",
            model="test",
            prompt_version="test",
            execution_config_hash="config-a",
            started_at="2026-09-23T00:00:00Z",
        )
        claim = execution.claim_next(
            run_id="run-a",
            worker_id="worker-a",
            lease_expires_at="2026-09-23T01:00:00Z",
            started_at="2026-09-23T00:00:01Z",
            max_attempts=3,
        )
        assert claim is not None
        execution.complete_success(
            attempt_id=claim.attempt_id,
            worker_id="worker-a",
            translated_text="你好",
            output_hash="output-a",
            finished_at="2026-09-23T00:00:02Z",
        )
        return temp, db

    def test_record_and_read_checked_result(self) -> None:
        temp, db = self._completed_db()
        self.addCleanup(temp.cleanup)

        qa = TranslationQaStore(db)
        qa.initialize()
        result = evaluate_translation(
            QaInput(
                content_uid="uid-a",
                source_text="Hello",
                translated_text="你好",
                primary_category="dialogue_general",
                required_protected_tokens=(),
            )
        )
        self.assertEqual(result.route, QA_ROUTE_PASS)

        qa.record_result(result, checked_at="2026-09-23T00:00:03Z")
        stored = qa.get_result("uid-a", current_rule_set_version=result.qa_rule_set_version)

        assert stored is not None
        self.assertEqual(stored.qa_status, QA_STATUS_CHECKED)
        self.assertEqual(stored.route, QA_ROUTE_PASS)
        self.assertEqual(stored.issue_count, 0)
        self.assertEqual(stored.qa_input_hash, result.qa_input_hash)

    def test_output_change_marks_previous_result_stale(self) -> None:
        temp, db = self._completed_db()
        self.addCleanup(temp.cleanup)

        qa = TranslationQaStore(db)
        qa.initialize()
        result = evaluate_translation(
            QaInput(
                content_uid="uid-a",
                source_text="Hello",
                translated_text="你好",
                primary_category="dialogue_general",
                required_protected_tokens=(),
            )
        )
        qa.record_result(result, checked_at="2026-09-23T00:00:03Z")

        execution = TranslationExecutionStore(db)
        with closing(execution.connect()) as conn, conn:
            conn.execute(
                """
                UPDATE content_state
                SET translated_text = ?, output_hash = ?, updated_at = ?
                WHERE content_uid = ?
                """,
                ("哈囉", "output-b", "2026-09-23T00:00:04Z", "uid-a"),
            )

        stored = qa.get_result("uid-a", current_rule_set_version=result.qa_rule_set_version)
        assert stored is not None
        self.assertEqual(stored.qa_status, QA_STATUS_STALE)

    def test_ruleset_change_marks_previous_result_stale(self) -> None:
        temp, db = self._completed_db()
        self.addCleanup(temp.cleanup)

        qa = TranslationQaStore(db)
        qa.initialize()
        result = evaluate_translation(
            QaInput(
                content_uid="uid-a",
                source_text="Hello",
                translated_text="你好",
                primary_category="dialogue_general",
                required_protected_tokens=(),
            )
        )
        qa.record_result(result, checked_at="2026-09-23T00:00:03Z")

        stored = qa.get_result("uid-a", current_rule_set_version="future-version")
        assert stored is not None
        self.assertEqual(stored.qa_status, QA_STATUS_STALE)

    def test_issue_rows_are_persisted_for_review_queue(self) -> None:
        temp, db = self._completed_db()
        self.addCleanup(temp.cleanup)

        qa = TranslationQaStore(db)
        qa.initialize()
        result = evaluate_translation(
            QaInput(
                content_uid="uid-a",
                source_text="Open the ancient gate",
                translated_text="Open the ancient gate",
                primary_category="dialogue_general",
                required_protected_tokens=(),
            )
        )
        self.assertEqual(result.route, QA_ROUTE_REVIEW)

        qa.record_result(result, checked_at="2026-09-23T00:00:03Z")
        queued = qa.list_by_route(
            QA_ROUTE_REVIEW,
            current_rule_set_version=result.qa_rule_set_version,
        )

        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0].content_uid, "uid-a")
        self.assertEqual(queued[0].qa_status, QA_STATUS_CHECKED)
        self.assertGreaterEqual(queued[0].issue_count, 1)

    def test_retry_handoff_archives_candidate_and_reopens_execution(self) -> None:
        temp, db = self._completed_db()
        self.addCleanup(temp.cleanup)

        qa = TranslationQaStore(db)
        qa.initialize()
        result = evaluate_translation(
            QaInput(
                content_uid="uid-a",
                source_text="Hello {PLAYER}",
                translated_text="你好",
                primary_category="dialogue_general",
                required_protected_tokens=("{PLAYER}",),
            )
        )
        self.assertEqual(result.route, QA_ROUTE_RETRY)
        qa.record_result(result, checked_at="2026-09-23T00:00:03Z")

        status = qa.handoff_retry(
            result,
            max_attempts=3,
            rejected_at="2026-09-23T00:00:04Z",
        )

        self.assertEqual(status, "failed-retryable")

        execution = TranslationExecutionStore(db)
        state = execution.get_state("uid-a")
        assert state is not None
        self.assertEqual(state["status"], "failed-retryable")
        self.assertIsNone(state["translated_text"])
        self.assertIsNone(state["output_hash"])

        rejected = qa.get_rejected_candidates("uid-a")
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["translated_text"], "你好")
        self.assertEqual(rejected[0]["output_hash"], "output-a")
        self.assertEqual(rejected[0]["route"], QA_ROUTE_RETRY)

        second = execution.claim_next(
            run_id="run-a",
            worker_id="worker-b",
            lease_expires_at="2026-09-23T02:00:00Z",
            started_at="2026-09-23T01:00:01Z",
            max_attempts=3,
        )
        assert second is not None
        self.assertEqual(second.content_uid, "uid-a")
        self.assertEqual(second.attempt_number, 2)

    def test_retry_handoff_respects_execution_retry_limit(self) -> None:
        temp, db = self._completed_db()
        self.addCleanup(temp.cleanup)

        qa = TranslationQaStore(db)
        qa.initialize()
        result = evaluate_translation(
            QaInput(
                content_uid="uid-a",
                source_text="Hello {PLAYER}",
                translated_text="你好",
                primary_category="dialogue_general",
                required_protected_tokens=("{PLAYER}",),
            )
        )
        qa.record_result(result, checked_at="2026-09-23T00:00:03Z")

        status = qa.handoff_retry(
            result,
            max_attempts=1,
            rejected_at="2026-09-23T00:00:04Z",
        )

        self.assertEqual(status, "failed-final")
        execution = TranslationExecutionStore(db)
        state = execution.get_state("uid-a")
        assert state is not None
        self.assertEqual(state["status"], "failed-final")
        self.assertIsNone(
            execution.claim_next(
                run_id="run-a",
                worker_id="worker-b",
                lease_expires_at="2026-09-23T02:00:00Z",
                started_at="2026-09-23T01:00:01Z",
                max_attempts=1,
            )
        )
        self.assertEqual(len(qa.get_rejected_candidates("uid-a")), 1)

    def test_retry_handoff_rejects_non_retry_result(self) -> None:
        temp, db = self._completed_db()
        self.addCleanup(temp.cleanup)

        qa = TranslationQaStore(db)
        qa.initialize()
        result = evaluate_translation(
            QaInput(
                content_uid="uid-a",
                source_text="Hello",
                translated_text="你好",
                primary_category="dialogue_general",
                required_protected_tokens=(),
            )
        )
        self.assertEqual(result.route, QA_ROUTE_PASS)
        qa.record_result(result, checked_at="2026-09-23T00:00:03Z")

        with self.assertRaisesRegex(ValueError, "requires a RETRY result"):
            qa.handoff_retry(
                result,
                max_attempts=3,
                rejected_at="2026-09-23T00:00:04Z",
            )

    def test_record_requires_completed_translation_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "execution.sqlite3"
            execution = TranslationExecutionStore(db)
            execution.initialize()
            execution.seed_items(
                [ExecutionItem("uid-a", "batch-a", "input-a")],
                updated_at="seed",
            )

            qa = TranslationQaStore(db)
            qa.initialize()
            result = evaluate_translation(
                QaInput(
                    content_uid="uid-a",
                    source_text="Hello",
                    translated_text="你好",
                    primary_category="dialogue_general",
                    required_protected_tokens=(),
                )
            )

            with self.assertRaisesRegex(ValueError, "no completed translation output"):
                qa.record_result(result, checked_at="2026-09-23T00:00:03Z")


if __name__ == "__main__":
    unittest.main()
