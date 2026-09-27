from __future__ import annotations

from contextlib import closing, redirect_stdout
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from bg3loc.cli import main
from bg3loc.production_workspace import verify_production_workspace


class TestProductionPrepare(unittest.TestCase):
    def _fixture(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)

        source = root / "English.jsonl"
        source.write_text(
            "".join(
                json.dumps(row) + "\n"
                for row in (
                    {"contentUid": "uid-bark", "text": "Hello", "localeId": "English"},
                    {"contentUid": "uid-other", "text": "Unknown", "localeId": "English"},
                )
            ),
            encoding="utf-8",
        )

        extract = root / "extract-manifest.json"
        extract.write_text(
            json.dumps(
                {
                    "sourceLocale": "English",
                    "targetLocale": "ChineseTraditional",
                    "locales": [
                        {"localeId": "English", "normalized": str(source)}
                    ],
                }
            ),
            encoding="utf-8",
        )

        mappings = root / "research-mappings.jsonl"
        mappings.write_text(
            json.dumps(
                {
                    "contentUid": "uid-bark",
                    "mappingType": "bark-speaker",
                    "classification": "bark",
                    "evidence": [],
                    "version": "1",
                    "metadata": {},
                }
            )
            + "\n",
            encoding="utf-8",
        )

        ruleset = root / "ruleset.json"
        ruleset.write_text(
            json.dumps(
                {
                    "version": "test-v1",
                    "sourceLocale": "English",
                    "targetLocale": "ChineseTraditional",
                    "commonRules": ["Preserve meaning."],
                    "categoryRules": {
                        "bark": ["Keep it short."],
                        "item": ["Use stable item naming."],
                    },
                    "glossary": [],
                }
            ),
            encoding="utf-8",
        )
        return temp, root, extract, source, mappings, ruleset

    def test_prepare_builds_workspace_and_execution_binding(self) -> None:
        temp, root, extract, source, mappings, ruleset = self._fixture()
        self.addCleanup(temp.cleanup)
        output = root / "production"

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = main(
                [
                    "production",
                    "prepare",
                    "--extract",
                    str(extract),
                    "--source",
                    str(source),
                    "--research-mappings",
                    str(mappings),
                    "--ruleset",
                    str(ruleset),
                    "--output",
                    str(output),
                ]
            )

        self.assertEqual(rc, 0)
        self.assertIn("Production prepare PASS", stdout.getvalue())
        manifest_path = output / "production-manifest.json"
        self.assertTrue(manifest_path.is_file())
        self.assertTrue((output / "classification" / "functional-classification.jsonl").is_file())
        self.assertTrue((output / "batches" / "batch-plan.json").is_file())
        self.assertTrue((output / "execution.sqlite3").is_file())

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["sourceLocale"], "English")
        self.assertEqual(manifest["targetLocale"], "ChineseTraditional")
        self.assertEqual(manifest["batching"]["classifiedInputCount"], 1)
        self.assertEqual(manifest["batching"]["unresolvedCount"], 1)
        self.assertEqual(manifest["execution"]["seededContentUidCount"], 1)
        self.assertEqual(
            manifest["batching"]["batchPlanFingerprint"],
            manifest["execution"]["batchPlanFingerprint"],
        )
        self.assertEqual(
            manifest["inputs"]["ruleset"]["fingerprint"],
            manifest["execution"]["rulesetFingerprint"],
        )

        with closing(sqlite3.connect(output / "execution.sqlite3")) as conn:
            rows = conn.execute(
                "SELECT content_uid, status FROM content_state ORDER BY content_uid"
            ).fetchall()
        self.assertEqual(rows, [("uid-bark", "pending")])

    def test_prepare_decision_overlay_preserves_automatic_ledger(self) -> None:
        temp, root, extract, source, mappings, ruleset = self._fixture()
        self.addCleanup(temp.cleanup)
        decisions = root / "decisions.jsonl"
        decisions.write_text(
            json.dumps(
                {
                    "ContentUid": "uid-other",
                    "action": "assign",
                    "category": "item",
                    "reviewer": "tester",
                    "note": "fixture assignment",
                    "decidedAt": "2026-09-27T00:00:00Z",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        output = root / "production"

        self.assertEqual(
            main(
                [
                    "production",
                    "prepare",
                    "--extract",
                    str(extract),
                    "--source",
                    str(source),
                    "--research-mappings",
                    str(mappings),
                    "--ruleset",
                    str(ruleset),
                    "--unclassified-decisions",
                    str(decisions),
                    "--output",
                    str(output),
                ]
            ),
            0,
        )

        automatic = output / "classification" / "functional-classification.jsonl"
        resolved = output / "classification" / "resolved-classification.jsonl"
        automatic_rows = {
            row["contentUid"]: row
            for row in (
                json.loads(line)
                for line in automatic.read_text(encoding="utf-8").splitlines()
            )
        }
        resolved_rows = {
            row["contentUid"]: row
            for row in (
                json.loads(line)
                for line in resolved.read_text(encoding="utf-8").splitlines()
            )
        }
        self.assertEqual(automatic_rows["uid-other"]["classificationStatus"], "unclassified")
        self.assertEqual(automatic_rows["uid-other"]["primaryCategory"], "other")
        self.assertEqual(resolved_rows["uid-other"]["classificationStatus"], "classified")
        self.assertEqual(resolved_rows["uid-other"]["primaryCategory"], "item")

        manifest = json.loads(
            (output / "production-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["batching"]["classifiedInputCount"], 2)
        self.assertEqual(manifest["batching"]["unresolvedCount"], 0)
        self.assertEqual(manifest["execution"]["seededContentUidCount"], 2)
        self.assertEqual(
            output / Path(manifest["classification"]["batchInputPath"]),
            resolved,
        )

    def test_prepare_fails_closed_on_nonempty_workspace(self) -> None:
        temp, root, extract, source, mappings, ruleset = self._fixture()
        self.addCleanup(temp.cleanup)
        output = root / "production"
        output.mkdir()
        (output / "keep.txt").write_text("do not overwrite", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "not empty"):
            main(
                [
                    "production",
                    "prepare",
                    "--extract",
                    str(extract),
                    "--source",
                    str(source),
                    "--research-mappings",
                    str(mappings),
                    "--ruleset",
                    str(ruleset),
                    "--output",
                    str(output),
                ]
            )
        self.assertFalse((output / "production-manifest.json").exists())
        self.assertEqual(
            (output / "keep.txt").read_text(encoding="utf-8"),
            "do not overwrite",
        )

    def test_prepare_fails_closed_on_ruleset_locale_mismatch(self) -> None:
        temp, root, extract, source, mappings, ruleset = self._fixture()
        self.addCleanup(temp.cleanup)
        payload = json.loads(ruleset.read_text(encoding="utf-8"))
        payload["targetLocale"] = "French"
        ruleset.write_text(json.dumps(payload), encoding="utf-8")

        output = root / "production"
        with self.assertRaisesRegex(RuntimeError, "targetLocale mismatch"):
            main(
                [
                    "production",
                    "prepare",
                    "--extract",
                    str(extract),
                    "--source",
                    str(source),
                    "--research-mappings",
                    str(mappings),
                    "--ruleset",
                    str(ruleset),
                    "--output",
                    str(output),
                ]
            )
        self.assertFalse((output / "production-manifest.json").exists())

    def test_prepare_resolves_relative_extract_source_from_manifest_directory(self) -> None:
        temp, root, extract, source, mappings, ruleset = self._fixture()
        self.addCleanup(temp.cleanup)
        payload = json.loads(extract.read_text(encoding="utf-8"))
        payload["locales"][0]["normalized"] = source.name
        extract.write_text(json.dumps(payload), encoding="utf-8")
        output = root / "production"

        with patch("pathlib.Path.cwd", return_value=root / "unrelated-cwd"):
            self.assertEqual(
                main(
                    [
                        "production",
                        "prepare",
                        "--extract",
                        str(extract),
                        "--source",
                        str(source),
                        "--research-mappings",
                        str(mappings),
                        "--ruleset",
                        str(ruleset),
                        "--output",
                        str(output),
                    ]
                ),
                0,
            )

        self.assertTrue((output / "production-manifest.json").is_file())

    def test_prepared_workspace_can_be_relocated_without_cwd_fallbacks(self) -> None:
        temp, root, extract, source, mappings, ruleset = self._fixture()
        self.addCleanup(temp.cleanup)
        output = root / "production"
        self.assertEqual(
            main(
                [
                    "production",
                    "prepare",
                    "--extract",
                    str(extract),
                    "--source",
                    str(source),
                    "--research-mappings",
                    str(mappings),
                    "--ruleset",
                    str(ruleset),
                    "--output",
                    str(output),
                ]
            ),
            0,
        )

        relocated = root / "relocated-production"
        shutil.move(output, relocated)
        binding = verify_production_workspace(relocated)
        self.assertEqual(binding.workspace, relocated.resolve())
        self.assertEqual(binding.batch_plan, relocated / "batches" / "batch-plan.json")
        self.assertEqual(binding.database, relocated / "execution.sqlite3")
        self.assertEqual(binding.ruleset, relocated / "inputs" / "ruleset.json")


if __name__ == "__main__":
    unittest.main()
