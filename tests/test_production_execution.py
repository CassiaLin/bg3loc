from __future__ import annotations

from contextlib import closing, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bg3loc.cli import main
from bg3loc.execution_state import TranslationExecutionStore
from bg3loc.production_execution import (
    OpenAICompatibleExecutionRequest,
    _preflight_workspace,
    execute_openai_compatible,
)
from bg3loc.production_workspace import (
    batch_materials_fingerprint,
    execution_inventory_fingerprint,
)
from bg3loc.ruleset_io import load_ruleset


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestProductionExecution(unittest.TestCase):
    def _workspace(self, root: Path) -> tuple[Path, Path]:
        workspace = root / "production"
        materials = workspace / "batches" / "materials"
        materials.mkdir(parents=True)

        plan = workspace / "batches" / "batch-plan.json"
        plan.write_text(
            json.dumps(
                {
                    "batchPlanFingerprint": "fp-production-execution",
                    "batches": [
                        {
                            "batchId": "bark-0001",
                            "primaryCategory": "bark",
                            "recordCount": 2,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (materials / "bark-0001.jsonl").write_text(
            "".join(
                json.dumps(row, ensure_ascii=False) + "\n"
                for row in (
                    {
                        "ContentUid": "uid-a",
                        "SourceText": "Hello {PLAYER}",
                        "primaryCategory": "bark",
                        "batchId": "bark-0001",
                    },
                    {
                        "ContentUid": "uid-b",
                        "SourceText": "Goodbye",
                        "primaryCategory": "bark",
                        "batchId": "bark-0001",
                    },
                )
            ),
            encoding="utf-8",
        )

        inputs = workspace / "inputs"
        inputs.mkdir()
        ruleset = inputs / "ruleset.json"
        ruleset.write_text(
            json.dumps(
                {
                    "version": "rules-v1",
                    "sourceLocale": "English",
                    "targetLocale": "ChineseTraditional",
                    "commonRules": [
                        "Preserve meaning.",
                        "Preserve protected tokens exactly.",
                    ],
                    "categoryRules": {
                        "bark": ["Keep bark lines concise."]
                    },
                    "glossary": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        db = workspace / "execution.sqlite3"
        self.assertEqual(
            main(
                [
                    "translation-state",
                    "init",
                    "--batch-plan",
                    str(plan),
                    "--db",
                    str(db),
                    "--ruleset",
                    str(ruleset),
                ]
            ),
            0,
        )

        loaded = load_ruleset(ruleset)
        manifest = {
            "schemaVersion": "1.0",
            "sourceLocale": "English",
            "targetLocale": "ChineseTraditional",
            "inputs": {
                "ruleset": {
                    "path": "inputs/ruleset.json",
                    "sha256": _sha256(ruleset),
                    "version": loaded.version,
                    "fingerprint": loaded.fingerprint(),
                }
            },
            "batching": {
                "batchPlan": "batches/batch-plan.json",
                "batchPlanFingerprint": "fp-production-execution",
                "batchPlanSha256": _sha256(plan),
                "batchMaterialsFingerprint": batch_materials_fingerprint(plan),
            },
            "execution": {
                "database": "execution.sqlite3",
                "batchPlanFingerprint": "fp-production-execution",
                "rulesetFingerprint": loaded.fingerprint(),
                "inventoryFingerprint": execution_inventory_fingerprint(db),
            },
        }
        (workspace / "production-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return workspace, db

    def test_bounded_run_is_incomplete_then_new_run_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace, db = self._workspace(Path(td))
            calls: list[str] = []

            def fake_post(_self, *, url, headers, payload, timeout_seconds):
                source = payload["messages"][-1]["content"]
                calls.append(source)
                text = "你好 {PLAYER}" if "{PLAYER}" in source else "再見"
                return 200, {
                    "id": f"req-{len(calls)}",
                    "choices": [{"message": {"content": text}}],
                }

            with patch(
                "bg3loc.providers.openai_compatible.UrllibJsonTransport.post_json",
                new=fake_post,
            ):
                first = io.StringIO()
                with redirect_stdout(first):
                    self.assertEqual(
                        main(
                            [
                                "production",
                                "execute-openai-compatible",
                                "--workspace",
                                str(workspace),
                                "--base-url",
                                "http://localhost:8080",
                                "--model",
                                "local-model",
                                "--run-id",
                                "run-1",
                                "--worker-id",
                                "worker-1",
                                "--max-items",
                                "1",
                            ]
                        ),
                        0,
                    )
                self.assertIn("run status: incomplete", first.getvalue())

                store = TranslationExecutionStore(db)
                self.assertEqual(store.get_state("uid-a")["status"], "succeeded")
                self.assertEqual(store.get_state("uid-b")["status"], "pending")

                second = io.StringIO()
                with redirect_stdout(second):
                    self.assertEqual(
                        main(
                            [
                                "production",
                                "execute-openai-compatible",
                                "--workspace",
                                str(workspace),
                                "--base-url",
                                "http://localhost:8080",
                                "--model",
                                "local-model",
                                "--run-id",
                                "run-2",
                                "--worker-id",
                                "worker-2",
                                "--max-items",
                                "1",
                            ]
                        ),
                        0,
                    )
                self.assertIn("run status: completed", second.getvalue())

            self.assertEqual(len(calls), 2)
            store = TranslationExecutionStore(db)
            self.assertEqual(store.get_state("uid-a")["status"], "succeeded")
            self.assertEqual(store.get_state("uid-b")["status"], "succeeded")
            self.assertEqual(len(store.get_attempts("uid-a")), 1)
            self.assertEqual(len(store.get_attempts("uid-b")), 1)

    def test_secret_is_used_for_http_but_not_persisted_or_printed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace, db = self._workspace(Path(td))
            seen_auth: list[str] = []

            def fake_post(_self, *, url, headers, payload, timeout_seconds):
                seen_auth.append(headers.get("Authorization", ""))
                return 200, {
                    "id": "req-secret",
                    "choices": [{"message": {"content": "你好 {PLAYER}"}}],
                }

            output = io.StringIO()
            with patch.dict(
                os.environ,
                {"BG3LOC_TEST_SECRET": "super-secret-value"},
                clear=False,
            ):
                with patch(
                    "bg3loc.providers.openai_compatible.UrllibJsonTransport.post_json",
                    new=fake_post,
                ):
                    with redirect_stdout(output):
                        self.assertEqual(
                            main(
                                [
                                    "production",
                                    "execute-openai-compatible",
                                    "--workspace",
                                    str(workspace),
                                    "--base-url",
                                    "http://localhost:8080",
                                    "--model",
                                    "local-model",
                                    "--run-id",
                                    "run-secret",
                                    "--worker-id",
                                    "worker-secret",
                                    "--api-key-env",
                                    "BG3LOC_TEST_SECRET",
                                    "--max-items",
                                    "1",
                                ]
                            ),
                            0,
                        )

            self.assertEqual(seen_auth, ["Bearer super-secret-value"])
            self.assertNotIn("super-secret-value", output.getvalue())
            store = TranslationExecutionStore(db)
            self.assertNotIn(
                "super-secret-value",
                json.dumps(store.get_run("run-secret")),
            )
            self.assertNotIn(
                "super-secret-value",
                (workspace / "production-manifest.json").read_text(encoding="utf-8"),
            )

    def test_workspace_fingerprint_mismatch_fails_before_http_and_run_creation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace, db = self._workspace(Path(td))
            manifest_path = workspace / "production-manifest.json"
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["batching"]["batchPlanFingerprint"] = "wrong-fingerprint"
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")

            called = False

            def fake_post(_self, **_kwargs):
                nonlocal called
                called = True
                return 200, {"choices": [{"message": {"content": "unused"}}]}

            with patch(
                "bg3loc.providers.openai_compatible.UrllibJsonTransport.post_json",
                new=fake_post,
            ):
                with self.assertRaisesRegex(RuntimeError, "batch fingerprint"):
                    main(
                        [
                            "production",
                            "execute-openai-compatible",
                            "--workspace",
                            str(workspace),
                            "--base-url",
                            "http://localhost:8080",
                            "--model",
                            "local-model",
                            "--run-id",
                            "run-bad",
                            "--worker-id",
                            "worker-bad",
                        ]
                    )

            self.assertFalse(called)
            self.assertIsNone(TranslationExecutionStore(db).get_run("run-bad"))

    def test_workspace_rejects_batch_plan_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace, _db = self._workspace(root)
            external = root / "external-plan.json"
            external.write_text(
                json.dumps(
                    {
                        "batchPlanFingerprint": "fp-production-execution",
                        "batches": [],
                    }
                ),
                encoding="utf-8",
            )
            manifest_path = workspace / "production-manifest.json"
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["batching"]["batchPlan"] = str(external)
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "outside production workspace"):
                _preflight_workspace(workspace)

    def test_workspace_rejects_material_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace, _db = self._workspace(Path(td))
            material = workspace / "batches" / "materials" / "bark-0001.jsonl"
            material.write_text(
                material.read_text(encoding="utf-8").replace("Hello", "Tampered"),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "material.*integrity"):
                _preflight_workspace(workspace)

    def test_workspace_rejects_execution_inventory_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace, db = self._workspace(Path(td))
            import sqlite3

            with closing(sqlite3.connect(db)) as conn, conn:
                conn.execute(
                    "UPDATE content_state SET batch_id='foreign-batch' WHERE content_uid='uid-a'"
                )

            with self.assertRaisesRegex(RuntimeError, "execution inventory"):
                _preflight_workspace(workspace)

    def test_workspace_rejects_unknown_manifest_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace, _db = self._workspace(Path(td))
            manifest_path = workspace / "production-manifest.json"
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload["schemaVersion"] = "99.0"
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "schemaVersion"):
                _preflight_workspace(workspace)

    def test_duplicate_run_id_fails_closed_before_http(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace, db = self._workspace(Path(td))
            calls = 0

            def fake_post(_self, *, url, headers, payload, timeout_seconds):
                nonlocal calls
                calls += 1
                return 200, {
                    "id": "req-dup",
                    "choices": [{"message": {"content": "你好 {PLAYER}"}}],
                }

            with patch(
                "bg3loc.providers.openai_compatible.UrllibJsonTransport.post_json",
                new=fake_post,
            ):
                self.assertEqual(
                    main(
                        [
                            "production",
                            "execute-openai-compatible",
                            "--workspace",
                            str(workspace),
                            "--base-url",
                            "http://localhost:8080",
                            "--model",
                            "local-model",
                            "--run-id",
                            "same-run",
                            "--worker-id",
                            "worker-1",
                            "--max-items",
                            "1",
                        ]
                    ),
                    0,
                )
                with self.assertRaisesRegex(RuntimeError, "already exists"):
                    main(
                        [
                            "production",
                            "execute-openai-compatible",
                            "--workspace",
                            str(workspace),
                            "--base-url",
                            "http://localhost:8080",
                            "--model",
                            "local-model",
                            "--run-id",
                            "same-run",
                            "--worker-id",
                            "worker-2",
                            "--max-items",
                            "1",
                        ]
                    )

            self.assertEqual(calls, 1)
            self.assertIsNotNone(TranslationExecutionStore(db).get_run("same-run"))

    def test_retryable_provider_error_reaches_failed_final_at_limit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace, db = self._workspace(Path(td))

            def fake_post(_self, *, url, headers, payload, timeout_seconds):
                return 429, {
                    "id": "req-rate-limit",
                    "error": {"message": "rate limited"},
                }

            output = io.StringIO()
            with patch(
                "bg3loc.providers.openai_compatible.UrllibJsonTransport.post_json",
                new=fake_post,
            ):
                with redirect_stdout(output):
                    self.assertEqual(
                        main(
                            [
                                "production",
                                "execute-openai-compatible",
                                "--workspace",
                                str(workspace),
                                "--base-url",
                                "http://localhost:8080",
                                "--model",
                                "local-model",
                                "--run-id",
                                "run-retry",
                                "--worker-id",
                                "worker-retry",
                                "--max-attempts",
                                "2",
                                "--retry-backoff-base-seconds",
                                "0",
                            ]
                        ),
                        0,
                    )

            store = TranslationExecutionStore(db)
            self.assertEqual(store.get_state("uid-a")["status"], "failed-final")
            self.assertEqual(store.get_state("uid-b")["status"], "failed-final")
            self.assertEqual(len(store.get_attempts("uid-a")), 2)
            self.assertEqual(len(store.get_attempts("uid-b")), 2)
            text = output.getvalue()
            self.assertIn("failed-retryable: 2", text)
            self.assertIn("failed-final: 2", text)
            self.assertIn("run status: completed", text)

    def test_production_policy_honors_retry_after_without_real_sleep(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace, db = self._workspace(Path(td))
            calls = 0
            sleeps: list[float] = []

            def fake_post(_self, *, url, headers, payload, timeout_seconds):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return (
                        429,
                        {"id": "req-rate-limit", "error": {"message": "rate limited"}},
                        {"Retry-After": "10"},
                    )
                return 200, {
                    "id": "req-success",
                    "choices": [{"message": {"content": "你好 {PLAYER}"}}],
                }

            with patch(
                "bg3loc.providers.openai_compatible.UrllibJsonTransport.post_json",
                new=fake_post,
            ):
                result = execute_openai_compatible(
                    OpenAICompatibleExecutionRequest(
                        workspace=workspace,
                        base_url="http://localhost:8080",
                        model="local-model",
                        run_id="run-policy",
                        worker_id="worker-policy",
                        max_items=2,
                    ),
                    sleeper=sleeps.append,
                    monotonic=lambda: 0.0,
                )

            self.assertEqual(sleeps, [10])
            self.assertEqual(result.claimed, 2)
            self.assertEqual(result.failed_retryable, 1)
            self.assertEqual(result.succeeded, 1)
            self.assertEqual(len(TranslationExecutionStore(db).get_attempts("uid-a")), 2)


if __name__ == "__main__":
    unittest.main()
