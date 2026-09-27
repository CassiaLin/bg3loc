from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from bg3loc.cli import main
from bg3loc.execution_state import ExecutionItem, TranslationExecutionStore
from bg3loc.qa_state import TranslationQaStore


class TestTranslationQaCli(unittest.TestCase):
    def _fixture(self, temp: str, *, source: str, target: str) -> tuple[Path, Path]:
        root = Path(temp)
        plan_dir = root / "plan"
        materials = plan_dir / "materials"
        materials.mkdir(parents=True)

        batch_id = "dialogue_general-0001"
        uid = "uid-a"
        plan = {
            "batchPlanFingerprint": "plan-fingerprint",
            "batches": [
                {
                    "batchId": batch_id,
                    "primaryCategory": "dialogue_general",
                    "recordCount": 1,
                }
            ],
        }
        (plan_dir / "batch-plan.json").write_text(
            json.dumps(plan, ensure_ascii=False),
            encoding="utf-8",
        )
        (materials / f"{batch_id}.jsonl").write_text(
            json.dumps(
                {
                    "ContentUid": uid,
                    "SourceText": source,
                    "primaryCategory": "dialogue_general",
                    "batchId": batch_id,
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        db = root / "execution.sqlite3"
        store = TranslationExecutionStore(db)
        store.initialize()
        store.seed_items(
            [ExecutionItem(uid, batch_id, "input-hash")],
            updated_at="seed",
        )
        store.start_run(
            run_id="run-a",
            batch_plan_fingerprint="plan-fingerprint",
            provider="test",
            model="test",
            prompt_version="test",
            execution_config_hash="config",
            started_at="2026-09-23T00:00:00Z",
        )
        claim = store.claim_next(
            run_id="run-a",
            worker_id="worker",
            lease_expires_at="2026-09-23T01:00:00Z",
            started_at="2026-09-23T00:00:01Z",
            max_attempts=3,
        )
        assert claim is not None
        store.complete_success(
            attempt_id=claim.attempt_id,
            worker_id="worker",
            translated_text=target,
            output_hash="output-hash",
            finished_at="2026-09-23T00:00:02Z",
        )
        return db, plan_dir / "batch-plan.json"

    def test_qa_run_and_summary_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db, plan = self._fixture(temp, source="Hello", target="你好")

            self.assertEqual(
                main(["qa", "run", "--db", str(db), "--batch-plan", str(plan)]),
                0,
            )
            self.assertEqual(main(["qa", "summary", "--db", str(db)]), 0)

    def test_review_list_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db, plan = self._fixture(
                temp,
                source="Open the ancient gate",
                target="Open the ancient gate",
            )

            self.assertEqual(
                main(["qa", "run", "--db", str(db), "--batch-plan", str(plan)]),
                0,
            )
            self.assertEqual(
                main(["qa", "review-list", "--db", str(db), "--limit", "10"]),
                0,
            )

    def test_smoke_probe_builds_controlled_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan_dir = root / "plan"
            materials = plan_dir / "materials"
            materials.mkdir(parents=True)
            batch_id = "dialogue_general-0001"
            plan = {
                "batchPlanFingerprint": "probe-plan",
                "batches": [{
                    "batchId": batch_id,
                    "primaryCategory": "dialogue_general",
                    "recordCount": 3,
                }],
            }
            plan_path = plan_dir / "batch-plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            rows = [
                {"ContentUid": "uid-1", "SourceText": "Hello adventurer", "primaryCategory": "dialogue_general", "batchId": batch_id},
                {"ContentUid": "uid-2", "SourceText": "Open the ancient gate", "primaryCategory": "dialogue_general", "batchId": batch_id},
                {"ContentUid": "uid-3", "SourceText": "Farewell friend", "primaryCategory": "dialogue_general", "batchId": batch_id},
            ]
            (materials / f"{batch_id}.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            work_dir = root / "probe"
            self.assertEqual(
                main(["qa", "smoke-probe", "--batch-plan", str(plan_path), "--work-dir", str(work_dir)]),
                0,
            )
            db = work_dir / "execution.sqlite3"
            self.assertTrue(db.is_file())
            self.assertEqual(
                main(["qa", "run", "--db", str(db), "--batch-plan", str(plan_path)]),
                0,
            )

            qa = TranslationQaStore(db)
            routes = {}
            for route in ("PASS", "REVIEW", "RETRY", "FAIL"):
                items = qa.list_by_route(route)
                if items:
                    routes[route] = len(items)
            self.assertEqual(routes, {"PASS": 1, "RETRY": 1, "REVIEW": 1})
    def test_retry_handoff_cli_reopens_execution_and_preserves_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db, plan = self._fixture(
                temp,
                source="Hello {PLAYER}",
                target="你好",
            )
            self.assertEqual(
                main(["qa", "run", "--db", str(db), "--batch-plan", str(plan)]),
                0,
            )
            self.assertEqual(
                main([
                    "qa", "retry-handoff",
                    "--db", str(db),
                    "--content-uid", "uid-a",
                    "--max-attempts", "3",
                ]),
                0,
            )

            store = TranslationExecutionStore(db)
            state = store.get_state("uid-a")
            assert state is not None
            self.assertEqual(state["status"], "failed-retryable")
            self.assertIsNone(state["translated_text"])
            self.assertIsNone(state["output_hash"])

            qa = TranslationQaStore(db)
            rejected = qa.get_rejected_candidates("uid-a")
            self.assertEqual(len(rejected), 1)
            self.assertEqual(rejected[0]["translated_text"], "你好")
            self.assertIn("PROTECTED_TOKEN_MISSING", rejected[0]["issues_json"])

            claim = store.claim_next(
                run_id="run-a",
                worker_id="worker-b",
                lease_expires_at="2026-09-23T02:00:00Z",
                started_at="2026-09-23T01:00:00Z",
                max_attempts=3,
            )
            assert claim is not None
            self.assertEqual(claim.content_uid, "uid-a")
            self.assertEqual(claim.attempt_number, 2)
    def test_qa_run_skips_current_result_on_repeat(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db, plan = self._fixture(temp, source="Hello", target="你好")
            argv = ["qa", "run", "--db", str(db), "--batch-plan", str(plan)]

            self.assertEqual(main(argv), 0)
            self.assertEqual(main(argv), 0)


if __name__ == "__main__":
    unittest.main()
