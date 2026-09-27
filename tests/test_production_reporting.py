from __future__ import annotations

from contextlib import closing, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from bg3loc.cli import main
from bg3loc.commands.translation_state import load_execution_items
from bg3loc.execution_state import EXECUTION_SCHEMA_VERSION, TranslationExecutionStore
from bg3loc.production_reporting import build_production_accounting_report
from bg3loc.production_workspace import (
    batch_materials_fingerprint,
    execution_inventory_fingerprint,
    sha256_file,
)
from bg3loc.ruleset_io import load_ruleset


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class TestProductionReporting(unittest.TestCase):
    def _workspace(self, root: Path, categories: list[str]) -> tuple[Path, Path]:
        workspace = root / "production"
        materials = workspace / "batches" / "materials"
        inputs = workspace / "inputs"
        materials.mkdir(parents=True)
        inputs.mkdir()

        grouped: dict[str, list[dict[str, str]]] = {}
        for ordinal, category in enumerate(categories):
            grouped.setdefault(category, []).append(
                {
                    "ContentUid": f"uid-{ordinal:05d}",
                    "SourceText": f"Source {ordinal}",
                    "primaryCategory": category,
                    "batchId": f"{category}-0001",
                }
            )
        batches = []
        for category, rows in sorted(grouped.items()):
            batch_id = f"{category}-0001"
            (materials / f"{batch_id}.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
            )
            batches.append(
                {
                    "batchId": batch_id,
                    "primaryCategory": category,
                    "recordCount": len(rows),
                }
            )
        plan = workspace / "batches" / "batch-plan.json"
        plan.write_text(
            json.dumps({"batchPlanFingerprint": "report-plan", "batches": batches}),
            encoding="utf-8",
        )
        ruleset_path = inputs / "ruleset.json"
        ruleset_path.write_text(
            json.dumps(
                {
                    "version": "report-rules",
                    "sourceLocale": "English",
                    "targetLocale": "ChineseTraditional",
                    "commonRules": ["Preserve meaning."],
                    "categoryRules": {
                        category: ["Use the category context."] for category in grouped
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
        store = TranslationExecutionStore(db)
        store.initialize()
        store.seed_items(items, updated_at="2026-09-28T00:00:00+00:00")
        store.set_metadata(
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
            "sourceLocale": ruleset.source_locale,
            "targetLocale": ruleset.target_locale,
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
        return workspace, db

    def _seed_accounting_history(self, db: Path) -> None:
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.executemany(
                """
                INSERT INTO runs(
                    run_id, batch_plan_fingerprint, provider, model, prompt_version,
                    execution_config_hash, started_at, finished_at, status
                ) VALUES (?, 'report-plan', ?, ?, 'report-rules', ?, ?, ?, ?)
                """,
                (
                    (
                        "run-a", "provider-a", "model-a", "config-a",
                        "2026-09-28T00:00:00+00:00", "2026-09-28T00:10:00+00:00",
                        "completed",
                    ),
                    (
                        "run-b", "provider-b", "model-b", "config-b",
                        "2026-09-28T01:00:00+00:00", "2026-09-28T01:05:00+00:00",
                        "incomplete",
                    ),
                ),
            )
            for ordinal in range(10):
                uid = f"uid-{ordinal:05d}"
                output = f"譯文 {ordinal}"
                cursor = conn.execute(
                    """
                    INSERT INTO attempts(
                        run_id, content_uid, batch_id, attempt_number, provider, model,
                        started_at, finished_at, outcome, provider_request_id,
                        input_hash, output_hash, prompt_tokens, completion_tokens, total_tokens
                    ) VALUES (
                        'run-a', ?, 'bark-0001', 1, 'provider-a', 'model-a',
                        '2026-09-28T00:00:00+00:00', '2026-09-28T00:00:02+00:00',
                        'succeeded', ?, 'input', ?, 100, 20, 120
                    )
                    """,
                    (uid, f"req-{ordinal}", _hash(output)),
                )
                conn.execute(
                    """
                    UPDATE content_state SET status='succeeded', translated_text=?,
                        output_hash=?, last_successful_run_id='run-a', last_attempt_id=?,
                        attempt_count=1, updated_at='2026-09-28T00:00:02+00:00'
                    WHERE content_uid=?
                    """,
                    (output, _hash(output), cursor.lastrowid, uid),
                )
            for uid, status, code in (
                ("uid-00010", "failed-retryable", "HTTP_429"),
                ("uid-00012", "failed-final", "PROVIDER_TRANSPORT_ERROR"),
            ):
                category = "bark" if uid == "uid-00010" else "quest"
                cursor = conn.execute(
                    """
                    INSERT INTO attempts(
                        run_id, content_uid, batch_id, attempt_number, provider, model,
                        started_at, finished_at, outcome, error_code, input_hash
                    ) VALUES (
                        'run-b', ?, ?, 1, 'provider-b', 'model-b',
                        '2026-09-28T01:00:00+00:00', '2026-09-28T01:00:01+00:00',
                        ?, ?, 'input'
                    )
                    """,
                    (uid, f"{category}-0001", status, code),
                )
                conn.execute(
                    """
                    UPDATE content_state SET status=?, last_attempt_id=?, attempt_count=1,
                        updated_at='2026-09-28T01:00:01+00:00' WHERE content_uid=?
                    """,
                    (status, cursor.lastrowid, uid),
                )

    def _business_snapshot(self, db: Path) -> dict[str, list[tuple[object, ...]]]:
        with closing(sqlite3.connect(db)) as conn:
            tables = ("content_state", "attempts", "runs", "qa_results")
            result = {}
            for table in tables:
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()
                result[table] = (
                    conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                    if exists
                    else []
                )
            return result

    def test_progress_runs_usage_pricing_estimate_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace, db = self._workspace(
                Path(td), ["bark"] * 12 + ["quest"] * 2
            )
            self._seed_accounting_history(db)
            pricing = Path(td) / "pricing.json"
            pricing.write_text(
                json.dumps(
                    {
                        "schemaVersion": "1.0",
                        "currency": "USD",
                        "models": [
                            {
                                "provider": "provider-a",
                                "model": "model-a",
                                "inputPerMillion": 1,
                                "outputPerMillion": 2,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            before = self._business_snapshot(db)
            report = build_production_accounting_report(
                workspace, pricing_path=pricing
            )
            self.assertEqual(self._business_snapshot(db), before)

            self.assertEqual(report["execution"]["succeeded"]["count"], 10)
            self.assertEqual(report["execution"]["pending"]["count"], 2)
            self.assertEqual(report["execution"]["failed-final"]["count"], 1)
            self.assertEqual(report["attempts"]["totalAttempts"], 12)
            self.assertEqual(report["errors"], {"HTTP_429": 1, "PROVIDER_TRANSPORT_ERROR": 1})
            self.assertEqual(len(report["runs"]), 2)
            self.assertEqual(report["runs"][1]["http429Count"], 1)
            self.assertEqual(report["runs"][1]["transportErrorCount"], 1)
            self.assertEqual(report["usage"]["knownUsageAttempts"], 10)
            self.assertEqual(report["usage"]["unknownUsageAttempts"], 2)
            self.assertEqual(report["usage"]["promptTokens"], 1000)
            self.assertEqual(report["usage"]["completionTokens"], 200)
            self.assertEqual(report["cost"]["status"], "partial")
            self.assertAlmostEqual(report["cost"]["inputCost"], 0.001)
            self.assertAlmostEqual(report["cost"]["outputCost"], 0.0004)
            self.assertAlmostEqual(report["cost"]["knownCost"], 0.0014)
            self.assertEqual(report["remainingEstimate"]["status"], "available")
            self.assertEqual(report["remainingEstimate"]["remainingExecutableItems"], 3)
            self.assertEqual(report["remainingEstimate"]["estimatedPromptTokens"], 300)
            self.assertEqual(report["remainingEstimate"]["estimatedCompletionTokens"], 60)
            categories = {row["primaryCategory"]: row for row in report["categories"]}
            self.assertEqual(categories["bark"]["succeeded"], 10)
            self.assertEqual(categories["bark"]["retry"], 1)
            self.assertEqual(categories["quest"]["failedFinal"], 1)

            json_path = Path(td) / "report.json"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(
                    main(
                        [
                            "production", "report", "--workspace", str(workspace),
                            "--pricing", str(pricing), "--json", str(json_path),
                        ]
                    ),
                    0,
                )
            self.assertIn("Known usage attempts".lower(), stdout.getvalue().lower())
            self.assertEqual(json.loads(json_path.read_text())["schemaVersion"], "1.0")

    def test_insufficient_samples_and_unknown_usage_never_claim_complete_cost(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace, db = self._workspace(Path(td), ["bark", "bark"])
            with closing(sqlite3.connect(db)) as conn, conn:
                conn.execute(
                    """
                    INSERT INTO runs VALUES(
                        'run-a', 'report-plan', 'provider-a', 'model-a', 'report-rules',
                        'config', '2026-09-28T00:00:00+00:00',
                        '2026-09-28T00:00:01+00:00', 'completed'
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO attempts(
                        run_id, content_uid, batch_id, attempt_number, provider, model,
                        started_at, finished_at, outcome, input_hash
                    ) VALUES(
                        'run-a', 'uid-00000', 'bark-0001', 1, 'provider-a', 'model-a',
                        '2026-09-28T00:00:00+00:00', '2026-09-28T00:00:01+00:00',
                        'failed-retryable', 'input'
                    )
                    """
                )
                conn.execute(
                    "UPDATE content_state SET status='failed-retryable', attempt_count=1 WHERE content_uid='uid-00000'"
                )
            pricing = Path(td) / "pricing.json"
            pricing.write_text(
                json.dumps(
                    {
                        "schemaVersion": "1.0", "currency": "USD",
                        "models": [{
                            "provider": "provider-a", "model": "model-a",
                            "inputPerMillion": 1, "outputPerMillion": 2,
                        }],
                    }
                ),
                encoding="utf-8",
            )
            report = build_production_accounting_report(workspace, pricing_path=pricing)
            self.assertEqual(report["usage"]["unknownUsageAttempts"], 1)
            self.assertEqual(report["cost"]["status"], "unavailable")
            self.assertEqual(report["cost"]["unpricedAttempts"], 1)
            self.assertEqual(report["remainingEstimate"]["status"], "unavailable")

    def test_old_database_additive_migration_preserves_rows(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "old.sqlite3"
            with closing(sqlite3.connect(db)) as conn, conn:
                conn.executescript(
                    """
                    CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE runs(
                        run_id TEXT PRIMARY KEY, batch_plan_fingerprint TEXT NOT NULL,
                        provider TEXT NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL,
                        execution_config_hash TEXT NOT NULL, started_at TEXT NOT NULL,
                        finished_at TEXT, status TEXT NOT NULL
                    );
                    CREATE TABLE content_state(
                        content_uid TEXT PRIMARY KEY, batch_id TEXT NOT NULL, status TEXT NOT NULL,
                        translated_text TEXT, input_hash TEXT NOT NULL, output_hash TEXT,
                        last_successful_run_id TEXT, last_attempt_id INTEGER,
                        attempt_count INTEGER NOT NULL DEFAULT 0, lease_owner TEXT,
                        lease_expires_at TEXT, updated_at TEXT NOT NULL
                    );
                    CREATE TABLE attempts(
                        attempt_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                        content_uid TEXT NOT NULL, batch_id TEXT NOT NULL,
                        attempt_number INTEGER NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
                        started_at TEXT NOT NULL, finished_at TEXT, outcome TEXT NOT NULL,
                        error_code TEXT, error_message TEXT, provider_request_id TEXT,
                        input_hash TEXT NOT NULL, output_hash TEXT
                    );
                    INSERT INTO metadata VALUES('schemaVersion', '1.0');
                    INSERT INTO runs VALUES(
                        'run-old', 'fp', 'p', 'm', 'rules', 'config', 'start', 'finish', 'completed'
                    );
                    INSERT INTO attempts(
                        run_id, content_uid, batch_id, attempt_number, provider, model,
                        started_at, finished_at, outcome, input_hash
                    ) VALUES('run-old', 'uid-old', 'b-1', 1, 'p', 'm', 'start', 'finish', 'succeeded', 'in');
                    INSERT INTO content_state VALUES(
                        'uid-old', 'b-1', 'succeeded', '譯文', 'in', 'out', 'run-old', 1,
                        1, NULL, NULL, 'finish'
                    );
                    """
                )
            store = TranslationExecutionStore(db)
            store.initialize()
            with closing(sqlite3.connect(db)) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(attempts)")}
                self.assertTrue(
                    {"prompt_tokens", "completion_tokens", "total_tokens"} <= columns
                )
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM content_state").fetchone()[0], 1)
                usage = conn.execute(
                    "SELECT prompt_tokens, completion_tokens, total_tokens FROM attempts"
                ).fetchone()
                self.assertEqual(usage, (None, None, None))
                version = conn.execute(
                    "SELECT value FROM metadata WHERE key='schemaVersion'"
                ).fetchone()[0]
                self.assertEqual(version, EXECUTION_SCHEMA_VERSION)

    def test_controlled_resume_persists_only_reported_usage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace, db = self._workspace(Path(td), ["bark", "bark"])
            responses = iter(
                (
                    (200, {
                        "id": "req-1", "choices": [{"message": {"content": "譯文一"}}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                    }),
                    (429, {"error": {"message": "slow down"}}),
                    (200, {
                        "id": "req-2", "choices": [{"message": {"content": "譯文二"}}],
                        "usage": {"input_tokens": 80, "output_tokens": 10, "total_tokens": 90},
                    }),
                )
            )

            def fake_post(_self, *, url, headers, payload, timeout_seconds):
                return next(responses)

            def run(run_id: str, max_items: int) -> None:
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        main(
                            [
                                "production", "execute-openai-compatible",
                                "--workspace", str(workspace), "--base-url", "http://local",
                                "--model", "model-a", "--run-id", run_id,
                                "--worker-id", f"worker-{run_id}", "--max-items", str(max_items),
                                "--retry-backoff-base-seconds", "0",
                            ]
                        ),
                        0,
                    )

            with patch(
                "bg3loc.providers.openai_compatible.UrllibJsonTransport.post_json",
                new=fake_post,
            ):
                run("run-1", 2)
                run("run-2", 1)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(["production", "qa", "--workspace", str(workspace)]), 0
                )
            report = build_production_accounting_report(workspace)
            self.assertEqual(report["execution"]["succeeded"]["count"], 2)
            self.assertEqual(report["qa"]["PASS"]["count"], 2)
            self.assertEqual(report["completion"]["MERGE_READY"]["count"], 2)
            self.assertEqual(report["attempts"]["totalAttempts"], 3)
            self.assertEqual(report["errors"], {"HTTP_429": 1})
            self.assertEqual(report["usage"]["knownUsageAttempts"], 2)
            self.assertEqual(report["usage"]["unknownUsageAttempts"], 1)
            self.assertEqual(report["usage"]["promptTokens"], 180)
            self.assertEqual(report["usage"]["completionTokens"], 30)
            attempts = TranslationExecutionStore(db).get_attempts("uid-00001")
            self.assertEqual([row["outcome"] for row in attempts], ["failed-retryable", "succeeded"])
            self.assertIsNone(attempts[0]["prompt_tokens"])
            self.assertEqual(attempts[1]["prompt_tokens"], 80)

    def test_large_pending_fixture_is_linear_and_fast(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            workspace, _db = self._workspace(Path(td), ["bark"] * 3000)
            started = time.perf_counter()
            report = build_production_accounting_report(workspace)
            elapsed = time.perf_counter() - started
            self.assertEqual(report["execution"]["pending"]["count"], 3000)
            self.assertEqual(report["usage"]["knownUsageAttempts"], 0)
            self.assertLess(elapsed, 5.0)


if __name__ == "__main__":
    unittest.main()
