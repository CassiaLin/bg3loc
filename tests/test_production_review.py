from __future__ import annotations

from contextlib import closing, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from bg3loc.cli import main
from bg3loc.execution_state import ExecutionItem, TranslationExecutionStore
from bg3loc.production_completion import (
    DISPOSITION_BLOCKED,
    DISPOSITION_MERGE_READY,
    REASON_HUMAN_REVIEW_ACCEPTED,
    build_production_completion_view,
)
from bg3loc.production_review import (
    ProductionReviewStore,
    REVIEW_DECISION_ACCEPT,
    REVIEW_DECISION_REVISE,
)
from bg3loc.qa import QaInput, evaluate_translation
from bg3loc.qa_state import QA_STATUS_STALE, TranslationQaStore


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestProductionReviewResolution(unittest.TestCase):
    def _fixture(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        plan_dir = root / "plan"
        materials = plan_dir / "materials"
        materials.mkdir(parents=True)
        plan = {
            "batchPlanFingerprint": "review-plan",
            "batches": [
                {
                    "batchId": "bark-0001",
                    "primaryCategory": "bark",
                    "recordCount": 1,
                }
            ],
        }
        plan_path = plan_dir / "batch-plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        source_text = "Open the ancient gate"
        (materials / "bark-0001.jsonl").write_text(
            json.dumps({
                "ContentUid": "uid-review",
                "SourceText": source_text,
                "primaryCategory": "bark",
                "batchId": "bark-0001",
            }) + "\n",
            encoding="utf-8",
        )

        db = root / "execution.sqlite3"
        execution = TranslationExecutionStore(db)
        execution.initialize()
        execution.seed_items(
            [ExecutionItem("uid-review", "bark-0001", "input-review")],
            updated_at="seed",
        )
        with closing(execution.connect()) as conn, conn:
            conn.execute(
                "UPDATE content_state SET status='succeeded', translated_text=?, output_hash=? WHERE content_uid='uid-review'",
                (source_text, _hash(source_text)),
            )

        qa = TranslationQaStore(db)
        qa.initialize()
        qa.record_result(
            evaluate_translation(QaInput(
                content_uid="uid-review",
                source_text=source_text,
                translated_text=source_text,
                primary_category="bark",
                required_protected_tokens=(),
            )),
            checked_at="2026-09-27T00:00:00Z",
        )

        review = ProductionReviewStore(db)
        review.initialize()
        return temp, db, plan_path, source_text

    def test_accept_current_review_becomes_merge_ready(self) -> None:
        temp, db, plan, _ = self._fixture()
        self.addCleanup(temp.cleanup)

        store = ProductionReviewStore(db)
        resolution = store.resolve(
            content_uid="uid-review",
            decision=REVIEW_DECISION_ACCEPT,
            reviewer="reviewer-a",
            note="checked in context",
            resolved_at="2026-09-27T00:01:00Z",
        )
        self.assertEqual(resolution.decision, REVIEW_DECISION_ACCEPT)

        view = build_production_completion_view(db, plan)
        row = view.rows[0]
        self.assertEqual(row.disposition, DISPOSITION_MERGE_READY)
        self.assertEqual(row.reason_code, REASON_HUMAN_REVIEW_ACCEPTED)

    def test_acceptance_does_not_follow_changed_output(self) -> None:
        temp, db, plan, _ = self._fixture()
        self.addCleanup(temp.cleanup)

        store = ProductionReviewStore(db)
        store.resolve(
            content_uid="uid-review",
            decision=REVIEW_DECISION_ACCEPT,
            reviewer="reviewer-a",
            note="accepted",
            resolved_at="2026-09-27T00:01:00Z",
        )
        execution = TranslationExecutionStore(db)
        changed = "changed after approval"
        with closing(execution.connect()) as conn, conn:
            conn.execute(
                "UPDATE content_state SET translated_text=?, output_hash=? WHERE content_uid='uid-review'",
                (changed, _hash(changed)),
            )

        view = build_production_completion_view(db, plan)
        self.assertEqual(view.rows[0].disposition, DISPOSITION_BLOCKED)

    def test_duplicate_accept_for_same_qa_evidence_fails_closed(self) -> None:
        temp, db, _plan, _ = self._fixture()
        self.addCleanup(temp.cleanup)
        store = ProductionReviewStore(db)
        store.resolve(
            content_uid="uid-review",
            decision=REVIEW_DECISION_ACCEPT,
            reviewer="reviewer-a",
            note="accepted",
            resolved_at="2026-09-27T00:01:00Z",
        )

        with self.assertRaisesRegex(ValueError, "duplicate review decision"):
            store.resolve(
                content_uid="uid-review",
                decision=REVIEW_DECISION_ACCEPT,
                reviewer="reviewer-b",
                note="duplicate",
                resolved_at="2026-09-27T00:02:00Z",
            )

    def test_acceptance_does_not_follow_changed_qa_input_identity(self) -> None:
        temp, db, plan, _ = self._fixture()
        self.addCleanup(temp.cleanup)

        store = ProductionReviewStore(db)
        store.resolve(
            content_uid="uid-review",
            decision=REVIEW_DECISION_ACCEPT,
            reviewer="reviewer-a",
            note="accepted",
            resolved_at="2026-09-27T00:01:00Z",
        )

        qa = TranslationQaStore(db)
        current = qa.get_result("uid-review")
        self.assertIsNotNone(current)
        assert current is not None

        with closing(qa.connect()) as conn, conn:
            conn.execute(
                "UPDATE qa_results SET qa_input_hash='changed-qa-input' WHERE content_uid='uid-review'"
            )

        view = build_production_completion_view(db, plan)
        self.assertNotEqual(view.rows[0].disposition, DISPOSITION_MERGE_READY)


    def test_revise_changes_output_and_makes_old_qa_stale(self) -> None:
        temp, db, plan, _ = self._fixture()
        self.addCleanup(temp.cleanup)

        store = ProductionReviewStore(db)
        revised = "開啟古老的大門"
        resolution = store.resolve(
            content_uid="uid-review",
            decision=REVIEW_DECISION_REVISE,
            reviewer="reviewer-b",
            note="manual correction",
            resolved_at="2026-09-27T00:02:00Z",
            revised_text=revised,
        )
        self.assertEqual(resolution.decision, REVIEW_DECISION_REVISE)
        self.assertEqual(resolution.resolved_output_hash, _hash(revised))

        qa = TranslationQaStore(db).get_result("uid-review")
        self.assertIsNotNone(qa)
        assert qa is not None
        self.assertEqual(qa.qa_status, QA_STATUS_STALE)

        view = build_production_completion_view(db, plan)
        self.assertEqual(view.rows[0].disposition, DISPOSITION_BLOCKED)

    def test_cli_export_and_accept(self) -> None:
        temp, db, plan, _ = self._fixture()
        self.addCleanup(temp.cleanup)
        output = Path(temp.name) / "review.jsonl"

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = main([
                "qa", "review-export",
                "--db", str(db),
                "--batch-plan", str(plan),
                "--output", str(output),
            ])
        self.assertEqual(rc, 0)
        rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ContentUid"], "uid-review")
        self.assertEqual(rows[0]["Decision"], "")
        self.assertTrue(rows[0]["Issues"])

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = main([
                "qa", "review-resolve",
                "--db", str(db),
                "--content-uid", "uid-review",
                "--decision", "accept",
                "--reviewer", "reviewer-cli",
                "--note", "approved",
            ])
        self.assertEqual(rc, 0)
        self.assertIn("Decision: ACCEPT", stdout.getvalue())
        view = build_production_completion_view(db, plan)
        self.assertEqual(view.rows[0].disposition, DISPOSITION_MERGE_READY)


if __name__ == "__main__":
    unittest.main()
