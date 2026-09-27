from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bg3loc.cli import main
from bg3loc.e2e.package import read_jsonl


class E2ECLIAcceptanceTests(unittest.TestCase):
    UID = "h11111111g2222g3333g4444g555555555555"

    def _write_extract_fixture(self, request) -> None:
        root = request.output
        normalized = root / "normalized"
        normalized.mkdir(parents=True, exist_ok=True)

        (normalized / "English.jsonl").write_text(
            json.dumps({
                "contentUid": self.UID,
                "text": "Hello {name}",
                "version": 1,
            }) + "\n",
            encoding="utf-8",
        )
        (normalized / "French.jsonl").write_text(
            json.dumps({
                "contentUid": self.UID,
                "text": "Bonjour {name}",
                "version": 2,
            }) + "\n",
            encoding="utf-8",
        )

        aligned = root / "aligned.jsonl"
        aligned.write_text(
            json.dumps({
                "contentUid": self.UID,
                "locales": {
                    "English": {"text": "Hello {name}", "version": 1},
                    "French": {"text": "Bonjour {name}", "version": 2},
                },
            }) + "\n",
            encoding="utf-8",
        )

        manifest = {
            "schemaVersion": "1.0",
            "scanManifest": str(root.parent / "scan" / "scan-manifest.json"),
            "sourceLocale": "English",
            "targetLocale": "French",
            "referenceLocales": [],
            "backend": {"id": "fixture"},
            "locales": [
                {
                    "localeId": "English",
                    "packageFile": str(root / "English.pak"),
                    "locaEntry": "Localization/English/english.loca",
                    "sourceLoca": str(root / "English.loca"),
                    "sourceXml": str(root / "English.xml"),
                    "normalized": str(normalized / "English.jsonl"),
                    "nodeCount": 1,
                },
                {
                    "localeId": "French",
                    "packageFile": str(root / "French.pak"),
                    "locaEntry": "Localization/French/french.loca",
                    "sourceLoca": str(root / "French.loca"),
                    "sourceXml": str(root / "French.xml"),
                    "normalized": str(normalized / "French.jsonl"),
                    "nodeCount": 1,
                },
            ],
            "aligned": str(aligned),
            "roundtripValidation": str(root / "roundtrip.json"),
        }
        (root / "extract-manifest.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )

    def test_public_cli_basic_standard_runs_to_install_apply_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "game"
            game.mkdir()
            project = root / "bg3loc-project.json"

            self.assertEqual(main([
                "project", "init",
                "--name", "synthetic-acceptance",
                "--source", "English",
                "--target", "French",
                "--game-dir", str(game),
                "--format", "jsonl",
                "--workspace", "workspace",
                "--output", str(project),
            ]), 0)

            scan_manifest = {
                "schemaVersion": "1.0",
                "game": {
                    "installPath": str(game),
                    "buildId": "synthetic",
                },
            }

            def fake_extract(request):
                self._write_extract_fixture(request)
                return {}

            with (
                patch("bg3loc.e2e.prepare.SchemaStore.validate"),
                patch("bg3loc.e2e.prepare.build_manifest", return_value=scan_manifest),
                patch("bg3loc.e2e.prepare.run_extract", side_effect=fake_extract),
            ):
                self.assertEqual(main([
                    "workflow", "prepare",
                    "--project", str(project),
                ]), 0)

            returns = root / "workspace" / "e2e" / "returns"
            material = next(returns.glob("*.jsonl"))
            row = read_jsonl(material)[0]
            row["ProposedTargetText"] = "Salut {name}"
            row["TranslationStatus"] = "translated"
            material.write_text(
                json.dumps(row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            self.assertEqual(main([
                "workflow", "validate",
                "--project", str(project),
            ]), 0)

            def fake_rebuild(request):
                request.output.mkdir(parents=True, exist_ok=True)
                manifest = request.output / "rebuild-manifest.json"
                manifest.write_text("{}", encoding="utf-8")
                return {"artifacts": [{"path": "synthetic-French.pak"}]}

            with patch(
                "bg3loc.e2e.rebuild.run_rebuild",
                side_effect=fake_rebuild,
            ):
                self.assertEqual(main([
                    "workflow", "rebuild",
                    "--project", str(project),
                ]), 0)

            def fake_install(request):
                if request.dry_run:
                    return {
                        "status": "dry-run-pass",
                        "preflight": {"destination": "synthetic-French.pak"},
                    }
                manifest = root / "workspace" / "e2e" / "backups" / "install-manifest.json"
                manifest.parent.mkdir(parents=True, exist_ok=True)
                manifest.write_text("{}", encoding="utf-8")
                return {
                    "deployment": [{"destination": "synthetic-French.pak"}],
                    "manifestPath": str(manifest),
                }

            with patch(
                "bg3loc.e2e.install.run_install",
                side_effect=fake_install,
            ):
                self.assertEqual(main([
                    "workflow", "install",
                    "--project", str(project),
                ]), 0)
                self.assertEqual(main([
                    "workflow", "install",
                    "--project", str(project),
                    "--apply",
                ]), 0)

            state_path = root / "workspace" / "e2e" / "workflow-state.json"
            before_status = state_path.read_bytes()
            self.assertEqual(main([
                "workflow", "status",
                "--project", str(project),
            ]), 0)
            self.assertEqual(state_path.read_bytes(), before_status)

            state = json.loads(
                state_path.read_text(encoding="utf-8")
            )
            self.assertEqual(state["currentStage"], "complete")
            self.assertEqual(state["stages"]["validate"]["status"], "completed")
            self.assertEqual(state["stages"]["rebuild"]["status"], "completed")
            self.assertEqual(state["stages"]["install-dry-run"]["status"], "completed")
            self.assertEqual(state["stages"]["install"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
