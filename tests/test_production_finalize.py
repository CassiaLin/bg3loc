from __future__ import annotations

from contextlib import closing, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from bg3loc.backends import ArchiveEntry
from bg3loc.cli import main
from bg3loc.commands.translation_state import load_execution_items
from bg3loc.execution_state import TranslationExecutionStore
from bg3loc.production_finalize import (
    ProductionFinalizeRequest,
    finalize_production_workspace,
)
from bg3loc.production_qa_orchestration import resolve_workspace_review, run_workspace_qa
from bg3loc.production_workspace import (
    batch_materials_fingerprint,
    execution_inventory_fingerprint,
    sha256_file,
)
from bg3loc.rebuilder import RebuildFailure
from bg3loc.ruleset_io import load_ruleset


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class FakeFinalizeBackend:
    id = "fake"

    def probe(self):
        raise NotImplementedError

    def list_archive(self, package: Path, expression: str = "*") -> list[ArchiveEntry]:
        return []

    def extract_single_file(self, package: Path, packaged_path: str, destination: Path) -> None:
        raise NotImplementedError

    def extract_package(self, package: Path, destination: Path) -> None:
        raise NotImplementedError

    def create_package(self, source_dir: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"PAK")

    def convert_loca(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    def convert_resource(self, source: Path, destination: Path) -> None:
        raise NotImplementedError


class TestProductionFinalize(unittest.TestCase):
    def _workspace(
        self,
        rows: tuple[dict[str, str], ...],
    ) -> tuple[tempfile.TemporaryDirectory[str], Path, Path, Path]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        workspace = root / "production"
        materials_dir = workspace / "batches" / "materials"
        inputs_dir = workspace / "inputs"
        extract_dir = root / "extract"
        normalized_dir = extract_dir / "normalized"
        locale_dir = extract_dir / "locales" / "ChineseTraditional"
        materials_dir.mkdir(parents=True)
        inputs_dir.mkdir()
        normalized_dir.mkdir(parents=True)
        locale_dir.mkdir(parents=True)

        category = rows[0]["primaryCategory"]
        batch_id = f"{category}-0001"
        material_rows = [
            {
                "ContentUid": row["ContentUid"],
                "SourceText": row["SourceText"],
                "primaryCategory": row["primaryCategory"],
                "batchId": batch_id,
            }
            for row in rows
        ]
        material = materials_dir / f"{batch_id}.jsonl"
        material.write_text(
            "".join(json.dumps(row) + "\n" for row in material_rows),
            encoding="utf-8",
        )
        plan = workspace / "batches" / "batch-plan.json"
        plan.write_text(
            json.dumps(
                {
                    "batchPlanFingerprint": "fp-finalize",
                    "batches": [
                        {
                            "batchId": batch_id,
                            "primaryCategory": category,
                            "recordCount": len(rows),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        ruleset_path = inputs_dir / "ruleset.json"
        ruleset_path.write_text(
            json.dumps(
                {
                    "version": "rules-finalize",
                    "sourceLocale": "English",
                    "targetLocale": "ChineseTraditional",
                    "commonRules": ["Preserve meaning."],
                    "categoryRules": {
                        "bark": ["Keep concise."],
                        "unknown": ["Do not infer."],
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

        source_jsonl = normalized_dir / "English.jsonl"
        target_jsonl = normalized_dir / "ChineseTraditional.jsonl"
        source_jsonl.write_text(
            "".join(
                json.dumps(
                    {
                        "contentUid": row["ContentUid"],
                        "localeId": "English",
                        "text": row["SourceText"],
                        "version": 1,
                    }
                )
                + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )
        target_jsonl.write_text("", encoding="utf-8")
        target_xml = locale_dir / "source.xml"
        target_xml.write_text(
            '<contentList><content contentuid="baseline-only" version="1">保留</content></contentList>',
            encoding="utf-8",
        )
        target_loca = locale_dir / "source.loca"
        target_loca.write_bytes(target_xml.read_bytes())
        target_pak = root / "game" / "ChineseTraditional.pak"
        target_pak.parent.mkdir()
        target_pak.write_bytes(b"PAK")
        extract_manifest = extract_dir / "extract-manifest.json"
        extract_manifest.write_text(
            json.dumps(
                {
                    "schemaVersion": "1.0",
                    "scanManifest": str(root / "scan-manifest.json"),
                    "sourceLocale": "English",
                    "targetLocale": "ChineseTraditional",
                    "referenceLocales": [],
                    "backend": {"id": "fake"},
                    "locales": [
                        {
                            "localeId": "English",
                            "packageFile": str(root / "English.pak"),
                            "locaEntry": "Localization/English/english.loca",
                            "sourceLoca": str(root / "English.loca"),
                            "sourceXml": str(root / "English.xml"),
                            "normalized": str(source_jsonl),
                            "nodeCount": len(rows),
                        },
                        {
                            "localeId": "ChineseTraditional",
                            "packageFile": str(target_pak),
                            "locaEntry": "Localization/ChineseTraditional/chinesetraditional.loca",
                            "sourceLoca": str(target_loca),
                            "sourceXml": str(target_xml),
                            "normalized": str(target_jsonl),
                            "nodeCount": 1,
                        },
                    ],
                    "aligned": str(extract_dir / "aligned.jsonl"),
                    "roundtripValidation": str(extract_dir / "roundtrip.json"),
                }
            ),
            encoding="utf-8",
        )
        manifest = {
            "schemaVersion": "1.1",
            "sourceLocale": "English",
            "targetLocale": "ChineseTraditional",
            "inputs": {
                "extractManifest": {
                    "path": str(extract_manifest.resolve()),
                    "sha256": sha256_file(extract_manifest),
                },
                "ruleset": {
                    "path": "inputs/ruleset.json",
                    "sha256": sha256_file(ruleset_path),
                    "version": ruleset.version,
                    "fingerprint": ruleset.fingerprint(),
                },
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
        return temp, workspace, db, extract_manifest

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

    def _finalize(self, workspace: Path, output: Path):
        return finalize_production_workspace(
            ProductionFinalizeRequest(
                workspace=workspace,
                output=output,
                container="loca-only",
            ),
            rebuild_backend=FakeFinalizeBackend(),
        )

    def test_ready_path_writes_bridge_rebuild_and_final_manifest(self) -> None:
        temp, workspace, db, _extract = self._workspace(
            ({"ContentUid": "uid-ready", "SourceText": "Hello", "primaryCategory": "bark"},)
        )
        self.addCleanup(temp.cleanup)
        self._succeed(db, "uid-ready", "你好")
        run_workspace_qa(workspace)

        output = Path(temp.name) / "final"
        result = self._finalize(workspace, output)

        self.assertEqual(result.manifest["completion"]["mergeReadyCount"], 1)
        self.assertEqual(result.manifest["artifacts"][0]["type"], "loca")
        self.assertTrue((output / "bridge" / "accepted-target.jsonl").is_file())
        self.assertTrue((output / "bridge" / "validate-manifest.json").is_file())
        self.assertTrue((output / "rebuild" / "rebuild-manifest.json").is_file())
        self.assertTrue(result.manifest_path.is_file())

    def test_waiting_translation_fails_before_bridge(self) -> None:
        temp, workspace, _db, _extract = self._workspace(
            ({"ContentUid": "uid-pending", "SourceText": "Hello", "primaryCategory": "bark"},)
        )
        self.addCleanup(temp.cleanup)
        output = Path(temp.name) / "final"
        with self.assertRaisesRegex(RuntimeError, "WAITING_TRANSLATION=1"):
            self._finalize(workspace, output)
        self.assertFalse(output.exists())

    def test_waiting_retry_fails_before_bridge(self) -> None:
        temp, workspace, db, _extract = self._workspace(
            ({"ContentUid": "uid-retry", "SourceText": "Hello {PLAYER}", "primaryCategory": "bark"},)
        )
        self.addCleanup(temp.cleanup)
        self._succeed(db, "uid-retry", "你好")
        run_workspace_qa(workspace)
        with self.assertRaisesRegex(RuntimeError, "WAITING_RETRY=1"):
            self._finalize(workspace, Path(temp.name) / "final")

    def test_waiting_review_fails_before_bridge(self) -> None:
        source = "Open the ancient gate"
        temp, workspace, db, _extract = self._workspace(
            ({"ContentUid": "uid-review", "SourceText": source, "primaryCategory": "bark"},)
        )
        self.addCleanup(temp.cleanup)
        self._succeed(db, "uid-review", source)
        run_workspace_qa(workspace)
        with self.assertRaisesRegex(RuntimeError, "WAITING_REVIEW=1"):
            self._finalize(workspace, Path(temp.name) / "final")

    def test_blocked_fails_before_bridge(self) -> None:
        temp, workspace, db, _extract = self._workspace(
            ({"ContentUid": "uid-blocked", "SourceText": "Hello", "primaryCategory": "unknown"},)
        )
        self.addCleanup(temp.cleanup)
        self._succeed(db, "uid-blocked", "你好")
        run_workspace_qa(workspace)
        with self.assertRaisesRegex(RuntimeError, "BLOCKED=1"):
            self._finalize(workspace, Path(temp.name) / "final")

    def test_stale_qa_after_review_revision_fails(self) -> None:
        source = "Open the ancient gate"
        temp, workspace, db, _extract = self._workspace(
            ({"ContentUid": "uid-review", "SourceText": source, "primaryCategory": "bark"},)
        )
        self.addCleanup(temp.cleanup)
        self._succeed(db, "uid-review", source)
        run_workspace_qa(workspace)
        resolve_workspace_review(
            workspace,
            content_uid="uid-review",
            decision="revise",
            reviewer="reviewer",
            note="",
            text="開啟古老的大門",
        )
        with self.assertRaisesRegex(RuntimeError, "BLOCKED=1"):
            self._finalize(workspace, Path(temp.name) / "final")

    def test_workspace_substitution_fails_before_bridge(self) -> None:
        for target in ("plan", "material", "ruleset", "inventory"):
            with self.subTest(target=target):
                temp, workspace, db, _extract = self._workspace(
                    ({"ContentUid": "uid-ready", "SourceText": "Hello", "primaryCategory": "bark"},)
                )
                self.addCleanup(temp.cleanup)
                self._succeed(db, "uid-ready", "你好")
                run_workspace_qa(workspace)
                if target == "plan":
                    path = workspace / "batches" / "batch-plan.json"
                    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
                elif target == "material":
                    path = workspace / "batches" / "materials" / "bark-0001.jsonl"
                    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
                elif target == "ruleset":
                    path = workspace / "inputs" / "ruleset.json"
                    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
                else:
                    with closing(sqlite3.connect(db)) as conn, conn:
                        conn.execute(
                            "UPDATE content_state SET input_hash='tampered' WHERE content_uid='uid-ready'"
                        )
                with self.assertRaises(RuntimeError):
                    self._finalize(workspace, Path(temp.name) / "final")
                self.assertFalse((Path(temp.name) / "final").exists())

    def test_non_empty_output_fails_closed(self) -> None:
        temp, workspace, db, _extract = self._workspace(
            ({"ContentUid": "uid-ready", "SourceText": "Hello", "primaryCategory": "bark"},)
        )
        self.addCleanup(temp.cleanup)
        self._succeed(db, "uid-ready", "你好")
        run_workspace_qa(workspace)
        output = Path(temp.name) / "final"
        output.mkdir()
        (output / "keep.txt").write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "not empty"):
            self._finalize(workspace, output)
        self.assertEqual((output / "keep.txt").read_text(encoding="utf-8"), "keep")

    def test_rebuild_failure_never_writes_final_manifest(self) -> None:
        temp, workspace, db, _extract = self._workspace(
            ({"ContentUid": "uid-ready", "SourceText": "Hello", "primaryCategory": "bark"},)
        )
        self.addCleanup(temp.cleanup)
        self._succeed(db, "uid-ready", "你好")
        run_workspace_qa(workspace)
        output = Path(temp.name) / "final"
        with patch(
            "bg3loc.production_finalize.run_rebuild",
            side_effect=RebuildFailure(44, "LOCA_SERIALIZATION_FAILED", "boom"),
        ):
            with self.assertRaisesRegex(RuntimeError, "LOCA_SERIALIZATION_FAILED"):
                self._finalize(workspace, output)
        self.assertTrue((output / "bridge" / "bridge-manifest.json").is_file())
        self.assertFalse((output / "production-final-manifest.json").exists())

    def test_cli_summary_uses_final_result(self) -> None:
        temp, workspace, db, _extract = self._workspace(
            ({"ContentUid": "uid-ready", "SourceText": "Hello", "primaryCategory": "bark"},)
        )
        self.addCleanup(temp.cleanup)
        self._succeed(db, "uid-ready", "你好")
        run_workspace_qa(workspace)
        output = Path(temp.name) / "final"
        captured = io.StringIO()
        with patch(
            "bg3loc.commands.production.finalize_production_workspace",
            side_effect=lambda request: self._finalize(request.workspace, request.output),
        ), redirect_stdout(captured):
            self.assertEqual(
                main(
                    [
                        "production",
                        "finalize",
                        "--workspace",
                        str(workspace),
                        "--output",
                        str(output),
                        "--container",
                        "loca-only",
                    ]
                ),
                0,
            )
        text = captured.getvalue()
        self.assertIn("Finalize PASS", text)
        self.assertIn("MERGE_READY count: 1", text)
        self.assertIn("LOCA SHA256:", text)

    def test_prepare_execute_qa_review_finalize_share_one_provenance_chain(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            extract_dir = root / "extract"
            normalized = extract_dir / "normalized"
            target_dir = extract_dir / "locales" / "ChineseTraditional"
            normalized.mkdir(parents=True)
            target_dir.mkdir(parents=True)
            uid = "uid-controlled-e2e"
            source = normalized / "English.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "contentUid": uid,
                        "localeId": "English",
                        "text": "Open the ancient gate",
                        "version": 1,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            target = normalized / "ChineseTraditional.jsonl"
            target.write_text("", encoding="utf-8")
            target_xml = target_dir / "source.xml"
            target_xml.write_text(
                '<contentList><content contentuid="baseline-only" version="1">保留</content></contentList>',
                encoding="utf-8",
            )
            target_loca = target_dir / "source.loca"
            target_loca.write_bytes(target_xml.read_bytes())
            target_pak = root / "game" / "ChineseTraditional.pak"
            target_pak.parent.mkdir()
            target_pak.write_bytes(b"PAK")
            extract = extract_dir / "extract-manifest.json"
            extract.write_text(
                json.dumps(
                    {
                        "schemaVersion": "1.0",
                        "scanManifest": str(root / "scan-manifest.json"),
                        "sourceLocale": "English",
                        "targetLocale": "ChineseTraditional",
                        "referenceLocales": [],
                        "backend": {"id": "fake"},
                        "locales": [
                            {
                                "localeId": "English",
                                "packageFile": str(root / "English.pak"),
                                "locaEntry": "Localization/English/english.loca",
                                "sourceLoca": str(root / "English.loca"),
                                "sourceXml": str(root / "English.xml"),
                                "normalized": str(source),
                                "nodeCount": 1,
                            },
                            {
                                "localeId": "ChineseTraditional",
                                "packageFile": str(target_pak),
                                "locaEntry": "Localization/ChineseTraditional/chinesetraditional.loca",
                                "sourceLoca": str(target_loca),
                                "sourceXml": str(target_xml),
                                "normalized": str(target),
                                "nodeCount": 1,
                            },
                        ],
                        "aligned": str(extract_dir / "aligned.jsonl"),
                        "roundtripValidation": str(extract_dir / "roundtrip.json"),
                    }
                ),
                encoding="utf-8",
            )
            mappings = root / "research-mappings.jsonl"
            mappings.write_text(
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
                + "\n",
                encoding="utf-8",
            )
            ruleset = root / "ruleset.json"
            ruleset.write_text(
                json.dumps(
                    {
                        "version": "controlled-e2e-v1",
                        "sourceLocale": "English",
                        "targetLocale": "ChineseTraditional",
                        "commonRules": ["Preserve meaning."],
                        "categoryRules": {"bark": ["Keep concise."]},
                        "glossary": [],
                    }
                ),
                encoding="utf-8",
            )
            workspace = root / "production"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "production", "prepare", "--extract", str(extract),
                            "--source", str(source), "--research-mappings", str(mappings),
                            "--ruleset", str(ruleset), "--output", str(workspace),
                        ]
                    ),
                    0,
                )

            def fake_post(_self, *, url, headers, payload, timeout_seconds):
                return 200, {
                    "id": "req-controlled-e2e",
                    "choices": [{"message": {"content": "Open the ancient gate"}}],
                }

            with patch(
                "bg3loc.providers.openai_compatible.UrllibJsonTransport.post_json",
                new=fake_post,
            ), redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "production", "execute-openai-compatible",
                            "--workspace", str(workspace),
                            "--base-url", "http://localhost:8080",
                            "--model", "mock-model", "--run-id", "run-e2e",
                            "--worker-id", "worker-e2e",
                        ]
                    ),
                    0,
                )
            run_workspace_qa(workspace)
            resolve_workspace_review(
                workspace,
                content_uid=uid,
                decision="revise",
                reviewer="integration-reviewer",
                note="",
                text="開啟古老的大門",
            )
            run_workspace_qa(workspace)

            result = self._finalize(workspace, root / "final")
            self.assertEqual(result.manifest["completion"]["mergeReadyCount"], 1)
            self.assertEqual(
                result.manifest["productionWorkspace"]["batchPlanFingerprint"],
                json.loads(
                    (workspace / "production-manifest.json").read_text(encoding="utf-8")
                )["batching"]["batchPlanFingerprint"],
            )


if __name__ == "__main__":
    unittest.main()
