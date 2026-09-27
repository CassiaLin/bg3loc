from __future__ import annotations

from contextlib import closing, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from bg3loc.cli import main
from bg3loc.commands.translation_qa import _read_material_batch
from bg3loc.commands.translation_state import load_execution_items
from bg3loc.execution_state import TranslationExecutionStore
from bg3loc.production_qa_orchestration import build_operator_report
from bg3loc.production_workspace import (
    batch_materials_fingerprint,
    execution_inventory_fingerprint,
    sha256_file,
)
from bg3loc.qa_state import TranslationQaStore
from bg3loc.ruleset_io import load_ruleset


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestProductionQaOrchestration(unittest.TestCase):
    def _workspace(
        self,
        rows: tuple[dict[str, str], ...],
    ) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        workspace = root / "production"
        batches_dir = workspace / "batches"
        materials_dir = batches_dir / "materials"
        inputs_dir = workspace / "inputs"
        materials_dir.mkdir(parents=True)
        inputs_dir.mkdir()

        grouped: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            grouped.setdefault(row["primaryCategory"], []).append(row)
        batches = []
        for category, category_rows in sorted(grouped.items()):
            batch_id = f"{category}-0001"
            material = materials_dir / f"{batch_id}.jsonl"
            normalized = []
            for row in category_rows:
                normalized.append(
                    {
                        "ContentUid": row["ContentUid"],
                        "SourceText": row["SourceText"],
                        "primaryCategory": category,
                        "batchId": batch_id,
                    }
                )
            material.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in normalized),
                encoding="utf-8",
            )
            batches.append(
                {
                    "batchId": batch_id,
                    "primaryCategory": category,
                    "recordCount": len(normalized),
                }
            )

        plan = batches_dir / "batch-plan.json"
        plan.write_text(
            json.dumps(
                {
                    "batchPlanFingerprint": "fp-03c",
                    "batches": batches,
                }
            ),
            encoding="utf-8",
        )
        ruleset_path = inputs_dir / "ruleset.json"
        ruleset_path.write_text(
            json.dumps(
                {
                    "version": "rules-03c",
                    "sourceLocale": "English",
                    "targetLocale": "ChineseTraditional",
                    "commonRules": ["Preserve meaning."],
                    "categoryRules": {
                        category: ["Use the supplied category."]
                        for category in grouped
                    },
                    "glossary": [],
                }
            ),
            encoding="utf-8",
        )
        ruleset = load_ruleset(ruleset_path)
        fingerprint, items = load_execution_items(
            plan,
            prompt_version=ruleset.version,
            ruleset_fingerprint=ruleset.fingerprint(),
            source_locale=ruleset.source_locale,
            target_locale=ruleset.target_locale,
        )
        db = workspace / "execution.sqlite3"
        execution = TranslationExecutionStore(db)
        execution.initialize()
        execution.seed_items(items, updated_at="seed")
        execution.set_metadata(
            {
                "batchPlanFingerprint": fingerprint,
                "promptVersion": ruleset.version,
                "rulesetFingerprint": ruleset.fingerprint(),
                "sourceLocale": ruleset.source_locale,
                "targetLocale": ruleset.target_locale,
            }
        )
        manifest = {
            "schemaVersion": "1.1",
            "sourceLocale": "English",
            "targetLocale": "ChineseTraditional",
            "inputs": {
                "ruleset": {
                    "path": "inputs/ruleset.json",
                    "sha256": sha256_file(ruleset_path),
                    "version": ruleset.version,
                    "fingerprint": ruleset.fingerprint(),
                }
            },
            "batching": {
                "batchPlan": "batches/batch-plan.json",
                "batchPlanFingerprint": fingerprint,
                "batchPlanSha256": sha256_file(plan),
                "batchMaterialsFingerprint": batch_materials_fingerprint(plan),
            },
            "execution": {
                "database": "execution.sqlite3",
                "batchPlanFingerprint": fingerprint,
                "rulesetFingerprint": ruleset.fingerprint(),
                "inventoryFingerprint": execution_inventory_fingerprint(db),
            },
        }
        (workspace / "production-manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        return temp, workspace, db

    def _succeed(self, db: Path, uid: str, text: str, *, attempts: int = 1) -> None:
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                """
                UPDATE content_state
                SET status='succeeded', translated_text=?, output_hash=?,
                    attempt_count=?, updated_at='succeeded'
                WHERE content_uid=?
                """,
                (text, _hash(text), attempts, uid),
            )

    def _run(self, *args: str) -> str:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(list(args)), 0)
        return output.getvalue()

    def test_succeeded_translation_qa_pass_becomes_merge_ready(self) -> None:
        temp, workspace, db = self._workspace(
            ({"ContentUid": "uid-pass", "SourceText": "Hello", "primaryCategory": "bark"},)
        )
        self.addCleanup(temp.cleanup)
        self._succeed(db, "uid-pass", "你好")

        output = self._run("production", "qa", "--workspace", str(workspace))
        self.assertIn("PASS: 1", output)
        self.assertIn("MERGE_READY: 1", output)

    def test_retry_handoff_reopens_only_retry_row(self) -> None:
        temp, workspace, db = self._workspace(
            ({"ContentUid": "uid-retry", "SourceText": "Hello {PLAYER}", "primaryCategory": "bark"},)
        )
        self.addCleanup(temp.cleanup)
        self._succeed(db, "uid-retry", "你好")
        self._run("production", "qa", "--workspace", str(workspace))
        self._run(
            "production", "retry", "--workspace", str(workspace),
            "--content-uid", "uid-retry",
        )

        state = TranslationExecutionStore(db).get_state("uid-retry")
        self.assertEqual(state["status"], "failed-retryable")
        self.assertIsNone(state["translated_text"])
        self.assertEqual(
            build_operator_report(workspace).completion.counts["WAITING_RETRY"], 1
        )

    def test_review_export_and_accept_becomes_merge_ready(self) -> None:
        source = "Open the ancient gate"
        temp, workspace, db = self._workspace(
            ({"ContentUid": "uid-review", "SourceText": source, "primaryCategory": "bark"},)
        )
        self.addCleanup(temp.cleanup)
        self._succeed(db, "uid-review", source)
        self._run("production", "qa", "--workspace", str(workspace))
        review_path = Path(temp.name) / "review.jsonl"
        self._run(
            "production", "review-export", "--workspace", str(workspace),
            "--output", str(review_path),
        )
        exported = json.loads(review_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(exported["ContentUid"], "uid-review")
        self.assertNotIn("apiKey", exported)
        self._run(
            "production", "review-resolve", "--workspace", str(workspace),
            "--content-uid", "uid-review", "--decision", "accept",
            "--reviewer", "reviewer-a", "--note", "approved",
        )
        self.assertEqual(
            build_operator_report(workspace).completion.counts["MERGE_READY"], 1
        )

    def test_review_export_reads_each_material_batch_once(self) -> None:
        rows = (
            {
                "ContentUid": "uid-review-a",
                "SourceText": "Open the ancient gate",
                "primaryCategory": "bark",
            },
            {
                "ContentUid": "uid-review-b",
                "SourceText": "Close the ancient gate",
                "primaryCategory": "bark",
            },
        )
        temp, workspace, db = self._workspace(rows)
        self.addCleanup(temp.cleanup)
        for row in rows:
            self._succeed(db, row["ContentUid"], row["SourceText"])
        self._run("production", "qa", "--workspace", str(workspace))

        review_path = Path(temp.name) / "review.jsonl"
        with patch(
            "bg3loc.commands.translation_qa._read_material_batch",
            wraps=_read_material_batch,
        ) as read_material:
            self._run(
                "production", "review-export", "--workspace", str(workspace),
                "--output", str(review_path),
            )

        self.assertEqual(read_material.call_count, 1)
        self.assertEqual(len(review_path.read_text(encoding="utf-8").splitlines()), 2)

    def test_review_revise_makes_qa_stale_until_rerun(self) -> None:
        source = "Open the ancient gate"
        temp, workspace, db = self._workspace(
            ({"ContentUid": "uid-review", "SourceText": source, "primaryCategory": "bark"},)
        )
        self.addCleanup(temp.cleanup)
        self._succeed(db, "uid-review", source)
        self._run("production", "qa", "--workspace", str(workspace))
        self._run(
            "production", "review-resolve", "--workspace", str(workspace),
            "--content-uid", "uid-review", "--decision", "revise",
            "--reviewer", "reviewer-b", "--text", "開啟古老的大門",
        )
        stale = build_operator_report(workspace)
        self.assertEqual(stale.qa_counts["stale"], 1)
        self.assertEqual(stale.completion.counts["BLOCKED"], 1)

        self._run("production", "qa", "--workspace", str(workspace))
        current = build_operator_report(workspace)
        self.assertEqual(current.qa_counts["PASS"], 1)
        self.assertEqual(current.completion.counts["MERGE_READY"], 1)

    def test_qa_fail_is_blocked(self) -> None:
        temp, workspace, db = self._workspace(
            ({"ContentUid": "uid-fail", "SourceText": "Hello", "primaryCategory": "unknown"},)
        )
        self.addCleanup(temp.cleanup)
        self._succeed(db, "uid-fail", "你好")
        self._run("production", "qa", "--workspace", str(workspace))
        report = build_operator_report(workspace)
        self.assertEqual(report.qa_counts["FAIL"], 1)
        self.assertEqual(report.completion.counts["BLOCKED"], 1)

    def test_workspace_mismatch_fails_before_qa_mutation(self) -> None:
        temp, workspace, db = self._workspace(
            ({"ContentUid": "uid-pass", "SourceText": "Hello", "primaryCategory": "bark"},)
        )
        self.addCleanup(temp.cleanup)
        self._succeed(db, "uid-pass", "你好")
        manifest_path = workspace / "production-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["batching"]["batchPlanFingerprint"] = "wrong"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "batch fingerprint"):
            main(["production", "qa", "--workspace", str(workspace)])
        with closing(sqlite3.connect(db)) as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='qa_results'"
            ).fetchone()
        self.assertIsNone(exists)

    def test_unknown_content_uid_fails_closed(self) -> None:
        temp, workspace, _db = self._workspace(
            ({"ContentUid": "uid-pass", "SourceText": "Hello", "primaryCategory": "bark"},)
        )
        self.addCleanup(temp.cleanup)
        with self.assertRaisesRegex(RuntimeError, "QA result not found"):
            main(
                [
                    "production", "retry", "--workspace", str(workspace),
                    "--content-uid", "unknown",
                ]
            )

    def test_report_is_read_only(self) -> None:
        temp, workspace, db = self._workspace(
            ({"ContentUid": "uid-pass", "SourceText": "Hello", "primaryCategory": "bark"},)
        )
        self.addCleanup(temp.cleanup)
        before = sha256_file(db)
        self._run("production", "report", "--workspace", str(workspace))
        self.assertEqual(sha256_file(db), before)

    def test_low_level_qa_reads_same_database(self) -> None:
        temp, workspace, db = self._workspace(
            ({"ContentUid": "uid-pass", "SourceText": "Hello", "primaryCategory": "bark"},)
        )
        self.addCleanup(temp.cleanup)
        self._succeed(db, "uid-pass", "你好")
        self._run("production", "qa", "--workspace", str(workspace))
        output = self._run("qa", "summary", "--db", str(db))
        self.assertIn("PASS: 1", output)

    def test_03b_succeeded_row_flows_directly_into_03c(self) -> None:
        temp, workspace, _db = self._workspace(
            ({"ContentUid": "uid-provider", "SourceText": "Hello", "primaryCategory": "bark"},)
        )
        self.addCleanup(temp.cleanup)

        def fake_post(_self, *, url, headers, payload, timeout_seconds):
            return 200, {"id": "req-03c", "choices": [{"message": {"content": "你好"}}]}

        with patch(
            "bg3loc.providers.openai_compatible.UrllibJsonTransport.post_json",
            new=fake_post,
        ):
            self._run(
                "production", "execute-openai-compatible", "--workspace", str(workspace),
                "--base-url", "http://localhost:8080", "--model", "mock-model",
                "--run-id", "run-03c", "--worker-id", "worker-03c",
            )
        output = self._run("production", "qa", "--workspace", str(workspace))
        self.assertIn("MERGE_READY: 1", output)

    def test_prepare_execute_qa_review_and_retry_share_one_state_chain(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "English.jsonl"
            source.write_text(
                "".join(
                    json.dumps(row) + "\n"
                    for row in (
                        {
                            "contentUid": "uid-review",
                            "text": "Open the ancient gate",
                            "localeId": "English",
                        },
                        {
                            "contentUid": "uid-retry",
                            "text": "Hello {PLAYER}",
                            "localeId": "English",
                        },
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
                "".join(
                    json.dumps(
                        {
                            "contentUid": uid,
                            "mappingType": "bark-speaker",
                            "classification": "bark",
                            "evidence": [],
                            "version": "1",
                            "metadata": {},
                        }
                    )
                    + "\n"
                    for uid in ("uid-review", "uid-retry")
                ),
                encoding="utf-8",
            )
            ruleset = root / "ruleset.json"
            ruleset.write_text(
                json.dumps(
                    {
                        "version": "e2e-v1",
                        "sourceLocale": "English",
                        "targetLocale": "ChineseTraditional",
                        "commonRules": ["Preserve meaning."],
                        "categoryRules": {"bark": ["Keep it concise."]},
                        "glossary": [],
                    }
                ),
                encoding="utf-8",
            )
            workspace = root / "production"
            self._run(
                "production", "prepare", "--extract", str(extract),
                "--source", str(source), "--research-mappings", str(mappings),
                "--ruleset", str(ruleset), "--output", str(workspace),
            )

            def fake_post(_self, *, url, headers, payload, timeout_seconds):
                prompt = str(payload["messages"][-1]["content"])
                translated = (
                    "你好 {PLAYER}"
                    if "{PLAYER}" in prompt
                    else "Open the ancient gate"
                )
                return 200, {
                    "id": "req-e2e",
                    "choices": [{"message": {"content": translated}}],
                }

            with patch(
                "bg3loc.providers.openai_compatible.UrllibJsonTransport.post_json",
                new=fake_post,
            ):
                self._run(
                    "production", "execute-openai-compatible", "--workspace", str(workspace),
                    "--base-url", "http://localhost:8080", "--model", "mock-model",
                    "--run-id", "run-e2e", "--worker-id", "worker-e2e",
                )
            # The OpenAI-compatible adapter rejects protected-token damage before
            # persistence. Inject one controlled accepted-01C succeeded candidate
            # to exercise the downstream QA RETRY handoff in the same database.
            db = workspace / "execution.sqlite3"
            self._succeed(db, "uid-retry", "你好")
            self._run("production", "qa", "--workspace", str(workspace))
            initial = build_operator_report(workspace)
            self.assertEqual(initial.qa_counts["REVIEW"], 1)
            self.assertEqual(initial.qa_counts["RETRY"], 1)

            self._run(
                "production", "review-resolve", "--workspace", str(workspace),
                "--content-uid", "uid-review", "--decision", "accept",
                "--reviewer", "integration-reviewer",
            )
            self._run(
                "production", "retry", "--workspace", str(workspace),
                "--content-uid", "uid-retry",
            )
            final = build_operator_report(workspace)
            self.assertEqual(final.completion.counts["MERGE_READY"], 1)
            self.assertEqual(final.completion.counts["WAITING_RETRY"], 1)


if __name__ == "__main__":
    unittest.main()
