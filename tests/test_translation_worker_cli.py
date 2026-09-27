from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bg3loc.cli import main
from bg3loc.execution_state import TranslationExecutionStore


class TestTranslationWorkerCli(unittest.TestCase):
    def make_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        materials = root / "materials"
        materials.mkdir()
        plan = root / "batch-plan.json"
        plan.write_text(
            json.dumps(
                {
                    "batchPlanFingerprint": "fp-worker-cli",
                    "batches": [
                        {
                            "batchId": "bark-0001",
                            "primaryCategory": "bark",
                            "recordCount": 1,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (materials / "bark-0001.jsonl").write_text(
            json.dumps(
                {
                    "contentUid": "uid-a",
                    "sourceText": "Hello {PLAYER}",
                    "translationText": "",
                    "primaryCategory": "bark",
                    "batchId": "bark-0001",
                    "canonicalGroupKey": "dialog:act1/foo",
                    "contextGroupKeys": ["dialog:act1/foo"],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        ruleset = root / "ruleset.json"
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
                        "bark": ["Keep bark lines concise."],
                    },
                    "glossary": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        db = root / "execution.sqlite3"
        return plan, ruleset, db

    def init_and_start(self, plan: Path, ruleset: Path, db: Path) -> None:
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
        self.assertEqual(
            main(
                [
                    "translation-state",
                    "run-start-openai-compatible",
                    "--db",
                    str(db),
                    "--batch-plan",
                    str(plan),
                    "--ruleset",
                    str(ruleset),
                    "--base-url",
                    "http://localhost:8080",
                    "--model",
                    "local-model",
                    "--run-id",
                    "run-1",
                    "--temperature",
                    "0.2",
                    "--max-output-tokens",
                    "128",
                ]
            ),
            0,
        )

    def test_worker_cli_executes_one_material_row(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan, ruleset, db = self.make_fixture(root)
            self.init_and_start(plan, ruleset, db)

            calls: list[dict[str, object]] = []

            def fake_post(_self, *, url, headers, payload, timeout_seconds):
                calls.append(
                    {
                        "url": url,
                        "headers": dict(headers),
                        "payload": payload,
                        "timeout": timeout_seconds,
                    }
                )
                return (
                    200,
                    {
                        "id": "req-cli-1",
                        "choices": [
                            {"message": {"content": "你好 {PLAYER}"}}
                        ],
                    },
                )

            with patch.dict(os.environ, {"BG3LOC_TEST_API_KEY": "secret-cli"}, clear=False):
                with patch(
                    "bg3loc.providers.openai_compatible.UrllibJsonTransport.post_json",
                    new=fake_post,
                ):
                    code = main(
                        [
                            "translation-state",
                            "worker-openai-compatible",
                            "--db",
                            str(db),
                            "--batch-plan",
                            str(plan),
                            "--ruleset",
                            str(ruleset),
                            "--base-url",
                            "http://localhost:8080",
                            "--model",
                            "local-model",
                            "--run-id",
                            "run-1",
                            "--worker-id",
                            "worker-1",
                            "--api-key-env",
                            "BG3LOC_TEST_API_KEY",
                            "--temperature",
                            "0.2",
                            "--max-output-tokens",
                            "128",
                            "--max-items",
                            "1",
                        ]
                    )

            self.assertEqual(code, 0)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["url"], "http://localhost:8080/v1/chat/completions")
            self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer secret-cli")
            self.assertNotIn("secret-cli", json.dumps(calls[0]["payload"]))
            system_prompt = calls[0]["payload"]["messages"][0]["content"]
            self.assertIn("from English to ChineseTraditional", system_prompt)

            store = TranslationExecutionStore(db)
            state = store.get_state("uid-a")
            assert state is not None
            self.assertEqual(state["status"], "succeeded")
            self.assertEqual(state["translated_text"], "你好 {PLAYER}")
            attempts = store.get_attempts("uid-a")
            self.assertEqual(attempts[-1]["provider_request_id"], "req-cli-1")

            run = store.get_run("run-1")
            assert run is not None
            self.assertNotIn("secret-cli", json.dumps(run))

    def test_target_locale_change_invalidates_existing_success_on_reinit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan, ruleset, db = self.make_fixture(root)
            self.init_and_start(plan, ruleset, db)

            def fake_post(_self, *, url, headers, payload, timeout_seconds):
                return (
                    200,
                    {
                        "id": "req-cli-1",
                        "choices": [
                            {"message": {"content": "你好 {PLAYER}"}}
                        ],
                    },
                )

            with patch(
                "bg3loc.providers.openai_compatible.UrllibJsonTransport.post_json",
                new=fake_post,
            ):
                self.assertEqual(
                    main(
                        [
                            "translation-state",
                            "worker-openai-compatible",
                            "--db",
                            str(db),
                            "--batch-plan",
                            str(plan),
                            "--ruleset",
                            str(ruleset),
                            "--base-url",
                            "http://localhost:8080",
                            "--model",
                            "local-model",
                            "--run-id",
                            "run-1",
                            "--worker-id",
                            "worker-1",
                            "--temperature",
                            "0.2",
                            "--max-output-tokens",
                            "128",
                            "--max-items",
                            "1",
                        ]
                    ),
                    0,
                )

            store = TranslationExecutionStore(db)
            self.assertEqual(store.get_state("uid-a")["status"], "succeeded")

            payload = json.loads(ruleset.read_text(encoding="utf-8"))
            payload["targetLocale"] = "Japanese"
            japanese = root / "ruleset-japanese.json"
            japanese.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

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
                        str(japanese),
                    ]
                ),
                0,
            )

            state = store.get_state("uid-a")
            assert state is not None
            self.assertEqual(state["status"], "invalidated")
            metadata = store.get_metadata()
            self.assertEqual(metadata["targetLocale"], "Japanese")
            self.assertNotEqual(metadata["rulesetFingerprint"], "")

    def test_worker_config_mismatch_fails_before_http(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan, ruleset, db = self.make_fixture(root)
            self.init_and_start(plan, ruleset, db)

            called = False

            def fake_post(_self, **_kwargs):
                nonlocal called
                called = True
                return 200, {
                    "choices": [{"message": {"content": "unused {PLAYER}"}}]
                }

            with patch(
                "bg3loc.providers.openai_compatible.UrllibJsonTransport.post_json",
                new=fake_post,
            ):
                with self.assertRaisesRegex(RuntimeError, "execution config hash"):
                    main(
                        [
                            "translation-state",
                            "worker-openai-compatible",
                            "--db",
                            str(db),
                            "--batch-plan",
                            str(plan),
                            "--ruleset",
                            str(ruleset),
                            "--base-url",
                            "http://localhost:9999",
                            "--model",
                            "local-model",
                            "--run-id",
                            "run-1",
                            "--worker-id",
                            "worker-1",
                            "--temperature",
                            "0.2",
                            "--max-output-tokens",
                            "128",
                            "--max-items",
                            "1",
                        ]
                    )

            self.assertFalse(called)
            store = TranslationExecutionStore(db)
            state = store.get_state("uid-a")
            assert state is not None
            self.assertEqual(state["status"], "pending")
            self.assertEqual(store.get_attempts("uid-a"), [])

    def test_ruleset_loader_and_prompt_version_mismatch_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan, ruleset, db = self.make_fixture(root)
            self.init_and_start(plan, ruleset, db)

            payload = json.loads(ruleset.read_text(encoding="utf-8"))
            payload["version"] = "rules-v2"
            changed = root / "ruleset-v2.json"
            changed.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "prompt/ruleset mismatch"):
                main(
                    [
                        "translation-state",
                        "worker-openai-compatible",
                        "--db",
                        str(db),
                        "--batch-plan",
                        str(plan),
                        "--ruleset",
                        str(changed),
                        "--base-url",
                        "http://localhost:8080",
                        "--model",
                        "local-model",
                        "--run-id",
                        "run-1",
                        "--worker-id",
                        "worker-1",
                        "--temperature",
                        "0.2",
                        "--max-output-tokens",
                        "128",
                        "--max-items",
                        "1",
                    ]
                )

            store = TranslationExecutionStore(db)
            state = store.get_state("uid-a")
            assert state is not None
            self.assertEqual(state["status"], "pending")


if __name__ == "__main__":
    unittest.main()
