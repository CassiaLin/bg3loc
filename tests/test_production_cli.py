from __future__ import annotations

from contextlib import closing, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from bg3loc.cli import main
from bg3loc.execution_state import ExecutionItem, TranslationExecutionStore
from bg3loc.qa import QaInput, evaluate_translation
from bg3loc.qa_state import TranslationQaStore


class TestProductionCli(unittest.TestCase):
    def _fixture(self) -> tuple[tempfile.TemporaryDirectory, Path, Path]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        plan_dir = root / "plan"
        materials = plan_dir / "materials"
        materials.mkdir(parents=True)

        plan = {
            "batchPlanFingerprint": "production-cli-plan",
            "batches": [
                {
                    "batchId": "bark-0001",
                    "primaryCategory": "bark",
                    "recordCount": 3,
                }
            ],
        }
        plan_path = plan_dir / "batch-plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        (materials / "bark-0001.jsonl").write_text(
            "".join(
                json.dumps(row, ensure_ascii=False) + "\n"
                for row in (
                    {
                        "ContentUid": "uid-pass",
                        "batchId": "bark-0001",
                        "primaryCategory": "bark",
                        "SourceText": "Hello",
                    },
                    {
                        "ContentUid": "uid-review",
                        "batchId": "bark-0001",
                        "primaryCategory": "bark",
                        "SourceText": "Open the ancient gate",
                    },
                    {
                        "ContentUid": "uid-pending",
                        "batchId": "bark-0001",
                        "primaryCategory": "bark",
                        "SourceText": "Pending",
                    },
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
                ExecutionItem("uid-pending", "bark-0001", "input-pending"),
            ],
            updated_at="seed",
        )
        with closing(execution.connect()) as conn, conn:
            conn.execute(
                "UPDATE content_state "
                "SET status='succeeded', translated_text='你好', output_hash='out-pass' "
                "WHERE content_uid='uid-pass'"
            )
            conn.execute(
                "UPDATE content_state "
                "SET status='succeeded', translated_text='Open the ancient gate', output_hash='out-review' "
                "WHERE content_uid='uid-review'"
            )

        qa = TranslationQaStore(db)
        qa.initialize()
        qa.record_result(
            evaluate_translation(
                QaInput(
                    content_uid="uid-pass",
                    source_text="Hello",
                    translated_text="你好",
                    primary_category="bark",
                    required_protected_tokens=(),
                )
            ),
            checked_at="2026-09-24T00:00:00Z",
        )
        qa.record_result(
            evaluate_translation(
                QaInput(
                    content_uid="uid-review",
                    source_text="Open the ancient gate",
                    translated_text="Open the ancient gate",
                    primary_category="bark",
                    required_protected_tokens=(),
                )
            ),
            checked_at="2026-09-24T00:00:01Z",
        )

        return temp, db, plan_path

    def test_status_cli_reports_reconciled_counts(self) -> None:
        temp, db, plan = self._fixture()
        self.addCleanup(temp.cleanup)

        output = io.StringIO()
        with redirect_stdout(output):
            rc = main(
                [
                    "production",
                    "status",
                    "--db",
                    str(db),
                    "--batch-plan",
                    str(plan),
                ]
            )

        self.assertEqual(rc, 0)
        text = output.getvalue()
        self.assertIn("Total: 3", text)
        self.assertIn("MERGE_READY: 1", text)
        self.assertIn("WAITING_TRANSLATION: 1", text)
        self.assertIn("WAITING_REVIEW: 1", text)

    def test_unresolved_and_merge_ready_exports_are_disjoint_and_complete(self) -> None:
        temp, db, plan = self._fixture()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        unresolved = root / "unresolved.jsonl"
        ready = root / "ready.jsonl"

        self.assertEqual(
            main(
                [
                    "production",
                    "unresolved",
                    "--db",
                    str(db),
                    "--batch-plan",
                    str(plan),
                    "--output",
                    str(unresolved),
                ]
            ),
            0,
        )
        self.assertEqual(
            main(
                [
                    "production",
                    "merge-ready",
                    "--db",
                    str(db),
                    "--batch-plan",
                    str(plan),
                    "--output",
                    str(ready),
                ]
            ),
            0,
        )

        unresolved_rows = [
            json.loads(line)
            for line in unresolved.read_text(encoding="utf-8").splitlines()
            if line
        ]
        ready_rows = [
            json.loads(line)
            for line in ready.read_text(encoding="utf-8").splitlines()
            if line
        ]

        unresolved_uids = {row["ContentUid"] for row in unresolved_rows}
        ready_uids = {row["ContentUid"] for row in ready_rows}
        self.assertEqual(unresolved_uids, {"uid-pending", "uid-review"})
        self.assertEqual(ready_uids, {"uid-pass"})
        self.assertFalse(unresolved_uids & ready_uids)
        self.assertEqual(
            unresolved_uids | ready_uids,
            {"uid-pass", "uid-review", "uid-pending"},
        )

    def test_exports_are_deterministic_on_repeat(self) -> None:
        temp, db, plan = self._fixture()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        first = root / "first.jsonl"
        second = root / "second.jsonl"

        argv = [
            "production",
            "unresolved",
            "--db",
            str(db),
            "--batch-plan",
            str(plan),
        ]
        self.assertEqual(main(argv + ["--output", str(first)]), 0)
        self.assertEqual(main(argv + ["--output", str(second)]), 0)
        self.assertEqual(
            first.read_bytes(),
            second.read_bytes(),
        )


    def test_smoke_probe_builds_full_material_state_and_all_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan_dir = root / "plan"
            materials = plan_dir / "materials"
            materials.mkdir(parents=True)
            batch_id = "dialogue_general-0001"
            plan = {
                "batchPlanFingerprint": "production-smoke-plan",
                "batches": [
                    {
                        "batchId": batch_id,
                        "primaryCategory": "dialogue_general",
                        "recordCount": 5,
                    }
                ],
            }
            plan_path = plan_dir / "batch-plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            rows = [
                {"ContentUid": "uid-1", "SourceText": "Hello adventurer", "primaryCategory": "dialogue_general", "batchId": batch_id},
                {"ContentUid": "uid-2", "SourceText": "Open the ancient gate", "primaryCategory": "dialogue_general", "batchId": batch_id},
                {"ContentUid": "uid-3", "SourceText": "Farewell friend", "primaryCategory": "dialogue_general", "batchId": batch_id},
                {"ContentUid": "uid-4", "SourceText": "Another line", "primaryCategory": "dialogue_general", "batchId": batch_id},
                {"ContentUid": "uid-5", "SourceText": "Keep pending", "primaryCategory": "dialogue_general", "batchId": batch_id},
            ]
            (materials / f"{batch_id}.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            work_dir = root / "probe"
            self.assertEqual(
                main(
                    [
                        "production",
                        "smoke-probe",
                        "--batch-plan",
                        str(plan_path),
                        "--work-dir",
                        str(work_dir),
                    ]
                ),
                0,
            )

            manifest = json.loads(
                (work_dir / "probe-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["total"], 5)
            self.assertEqual(manifest["counts"]["MERGE_READY"], 1)
            self.assertEqual(manifest["counts"]["WAITING_REVIEW"], 1)
            self.assertEqual(manifest["counts"]["WAITING_RETRY"], 1)
            self.assertEqual(manifest["counts"]["BLOCKED"], 1)
            self.assertEqual(manifest["counts"]["WAITING_TRANSLATION"], 1)

            with self.assertRaisesRegex(RuntimeError, "work directory already exists"):
                main(
                    [
                        "production",
                        "smoke-probe",
                        "--batch-plan",
                        str(plan_path),
                        "--work-dir",
                        str(work_dir),
                    ]
                )


if __name__ == "__main__":
    unittest.main()
