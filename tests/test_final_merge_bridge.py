from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from bg3loc.cli import main

from bg3loc.execution_state import ExecutionItem, TranslationExecutionStore
from bg3loc.final_merge_bridge import FinalMergeBridgeError, build_final_merge_bridge
from bg3loc.qa import QaInput, evaluate_translation
from bg3loc.qa_state import TranslationQaStore


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestFinalMergeBridge(unittest.TestCase):
    def _fixture(self) -> tuple[tempfile.TemporaryDirectory, Path, Path, Path]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)

        plan_dir = root / "plan"
        materials = plan_dir / "materials"
        materials.mkdir(parents=True)
        plan = {
            "batchPlanFingerprint": "bridge-plan",
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
                    {"ContentUid": "uid-target", "SourceText": "Hello", "primaryCategory": "bark", "batchId": "bark-0001"},
                    {"ContentUid": "uid-source-only", "SourceText": "New line", "primaryCategory": "bark", "batchId": "bark-0001"},
                    {"ContentUid": "uid-pending", "SourceText": "Pending", "primaryCategory": "bark", "batchId": "bark-0001"},
                )
            ),
            encoding="utf-8",
        )

        extract_dir = root / "extract"
        normalized = extract_dir / "normalized"
        normalized.mkdir(parents=True)
        source_path = normalized / "English.jsonl"
        target_path = normalized / "ChineseTraditional.jsonl"
        source_rows = [
            {"contentUid": "uid-target", "localeId": "English", "text": "Hello", "version": 11},
            {"contentUid": "uid-source-only", "localeId": "English", "text": "New line", "version": 22},
            {"contentUid": "uid-pending", "localeId": "English", "text": "Pending", "version": 33},
        ]
        target_rows = [
            {"contentUid": "uid-target", "localeId": "ChineseTraditional", "text": "舊譯", "version": 44},
            {"contentUid": "uid-pending", "localeId": "ChineseTraditional", "text": "待處理", "version": 55},
        ]
        source_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in source_rows),
            encoding="utf-8",
        )
        target_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in target_rows),
            encoding="utf-8",
        )
        extract_manifest = {
            "schemaVersion": "1.0",
            "scanManifest": "scan.json",
            "sourceLocale": "English",
            "targetLocale": "ChineseTraditional",
            "referenceLocales": [],
            "backend": {"id": "test"},
            "locales": [
                {
                    "localeId": "English",
                    "packageFile": "english.pak",
                    "locaEntry": "Localization/English/English.loca",
                    "sourceLoca": "english.loca",
                    "sourceXml": "english.xml",
                    "normalized": str(source_path),
                    "nodeCount": 3,
                },
                {
                    "localeId": "ChineseTraditional",
                    "packageFile": "target.pak",
                    "locaEntry": "Localization/ChineseTraditional/ChineseTraditional.loca",
                    "sourceLoca": "target.loca",
                    "sourceXml": "target.xml",
                    "normalized": str(target_path),
                    "nodeCount": 2,
                },
            ],
            "aligned": "aligned.jsonl",
            "roundtripValidation": "roundtrip.json",
        }
        extract_manifest_path = extract_dir / "extract-manifest.json"
        extract_manifest_path.write_text(
            json.dumps(extract_manifest, ensure_ascii=False),
            encoding="utf-8",
        )

        db = root / "execution.sqlite3"
        execution = TranslationExecutionStore(db)
        execution.initialize()
        execution.seed_items(
            [
                ExecutionItem("uid-target", "bark-0001", "input-target"),
                ExecutionItem("uid-source-only", "bark-0001", "input-source-only"),
                ExecutionItem("uid-pending", "bark-0001", "input-pending"),
            ],
            updated_at="seed",
        )
        target_text = "新譯文"
        source_only_text = "新增譯文"
        with closing(execution.connect()) as conn, conn:
            conn.execute(
                "UPDATE content_state SET status='succeeded', translated_text=?, output_hash=? WHERE content_uid='uid-target'",
                (target_text, _hash(target_text)),
            )
            conn.execute(
                "UPDATE content_state SET status='succeeded', translated_text=?, output_hash=? WHERE content_uid='uid-source-only'",
                (source_only_text, _hash(source_only_text)),
            )

        qa = TranslationQaStore(db)
        qa.initialize()
        qa.record_result(
            evaluate_translation(QaInput(
                content_uid="uid-target",
                source_text="Hello",
                translated_text=target_text,
                primary_category="bark",
                required_protected_tokens=(),
            )),
            checked_at="2026-09-25T00:00:00Z",
        )
        qa.record_result(
            evaluate_translation(QaInput(
                content_uid="uid-source-only",
                source_text="New line",
                translated_text=source_only_text,
                primary_category="bark",
                required_protected_tokens=(),
            )),
            checked_at="2026-09-25T00:00:01Z",
        )

        return temp, db, plan_path, extract_manifest_path

    def test_bridge_exports_only_merge_ready_with_authoritative_versions(self) -> None:
        temp, db, plan, extract = self._fixture()
        self.addCleanup(temp.cleanup)
        output = Path(temp.name) / "bridge"

        manifest = build_final_merge_bridge(
            db_path=db,
            batch_plan_path=plan,
            extract_manifest_path=extract,
            output_dir=output,
        )

        rows = [
            json.loads(line)
            for line in (output / "accepted-target.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
        self.assertEqual([row["contentUid"] for row in rows], ["uid-source-only", "uid-target"])
        by_uid = {row["contentUid"]: row for row in rows}
        self.assertEqual(by_uid["uid-target"]["localeId"], "ChineseTraditional")
        self.assertEqual(by_uid["uid-target"]["version"], 44)
        self.assertEqual(by_uid["uid-source-only"]["version"], 22)
        self.assertNotIn("uid-pending", by_uid)
        self.assertEqual(manifest["mergeReadyCount"], 2)
        self.assertEqual(manifest["batchPlanFingerprint"], "bridge-plan")
        self.assertTrue(manifest["executionDatabaseSha256"])
        self.assertTrue(manifest["qaRuleSetVersion"])

        binding = [
            json.loads(line)
            for line in (output / "merge-ready-binding.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
        binding_by_uid = {row["ContentUid"]: row for row in binding}
        self.assertEqual(binding_by_uid["uid-target"]["versionSource"], "target")
        self.assertEqual(binding_by_uid["uid-source-only"]["versionSource"], "source")

    def test_bridge_output_is_byte_deterministic(self) -> None:
        temp, db, plan, extract = self._fixture()
        self.addCleanup(temp.cleanup)
        first = Path(temp.name) / "bridge-a"
        second = Path(temp.name) / "bridge-b"

        build_final_merge_bridge(
            db_path=db, batch_plan_path=plan, extract_manifest_path=extract, output_dir=first
        )
        build_final_merge_bridge(
            db_path=db, batch_plan_path=plan, extract_manifest_path=extract, output_dir=second
        )

        self.assertEqual(
            (first / "accepted-target.jsonl").read_bytes(),
            (second / "accepted-target.jsonl").read_bytes(),
        )
        self.assertEqual(
            (first / "merge-ready-binding.jsonl").read_bytes(),
            (second / "merge-ready-binding.jsonl").read_bytes(),
        )

    def test_bridge_fails_if_current_text_hash_is_inconsistent(self) -> None:
        temp, db, plan, extract = self._fixture()
        self.addCleanup(temp.cleanup)
        execution = TranslationExecutionStore(db)
        with closing(execution.connect()) as conn, conn:
            conn.execute(
                "UPDATE content_state SET translated_text='tampered' WHERE content_uid='uid-target'"
            )

        with self.assertRaisesRegex(FinalMergeBridgeError, "output hash mismatch"):
            build_final_merge_bridge(
                db_path=db,
                batch_plan_path=plan,
                extract_manifest_path=extract,
                output_dir=Path(temp.name) / "bridge",
            )


    def test_bridge_fails_without_batch_plan_fingerprint(self) -> None:
        temp, db, plan, extract = self._fixture()
        self.addCleanup(temp.cleanup)
        data = json.loads(plan.read_text(encoding="utf-8"))
        data.pop("batchPlanFingerprint")
        plan.write_text(json.dumps(data), encoding="utf-8")

        with self.assertRaisesRegex(FinalMergeBridgeError, "batchPlanFingerprint"):
            build_final_merge_bridge(
                db_path=db,
                batch_plan_path=plan,
                extract_manifest_path=extract,
                output_dir=Path(temp.name) / "bridge",
            )


    def test_bridge_cli_writes_expected_artifacts(self) -> None:
        temp, db, plan, extract = self._fixture()
        self.addCleanup(temp.cleanup)
        output = Path(temp.name) / "bridge-cli"

        rc = main(
            [
                "production",
                "bridge",
                "--db",
                str(db),
                "--batch-plan",
                str(plan),
                "--extract",
                str(extract),
                "--output",
                str(output),
            ]
        )

        self.assertEqual(rc, 0)
        self.assertTrue((output / "accepted-target.jsonl").is_file())
        self.assertTrue((output / "merge-ready-binding.jsonl").is_file())
        self.assertTrue((output / "validate-manifest.json").is_file())
        self.assertTrue((output / "bridge-manifest.json").is_file())

        bridge = json.loads(
            (output / "bridge-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(bridge["mergeReadyCount"], 2)
        self.assertEqual(bridge["targetLocale"], "ChineseTraditional")


if __name__ == "__main__":
    unittest.main()