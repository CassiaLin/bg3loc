from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bg3loc.backends import BackendProbe
from bg3loc.cli import build_parser, main
from bg3loc.commands import build, extract, install, rebuild, scan, validate
from bg3loc.scanner import ScanFailure


class CLIFoundationTests(unittest.TestCase):
    def test_parser_registers_all_commands(self) -> None:
        parser = build_parser()
        for command in ("scan", "extract", "build", "validate", "rebuild", "install", "research", "review", "project", "workflow"):
            with self.subTest(command=command):
                with self.assertRaises(SystemExit) as ctx:
                    parser.parse_args([command, "--help"])
                self.assertEqual(ctx.exception.code, 0)

    def test_scan_without_discoverable_game_returns_game_not_found(self) -> None:
        failure = ScanFailure(2, "GAME_NOT_FOUND", "fixture has no game")
        with patch("bg3loc.commands.scan.build_manifest", side_effect=failure):
            self.assertEqual(main(["scan"]), 2)

    def test_extract_requires_source_and_target(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            build_parser().parse_args(["extract"])
        self.assertEqual(ctx.exception.code, 2)

    def test_build_defaults_to_basic(self) -> None:
        args = build_parser().parse_args(["build"])
        self.assertEqual(args.mode, "basic")
        self.assertEqual(args.max_rows, 1500)

    def test_scan_success_summary(self) -> None:
        args = SimpleNamespace(game_dir=None, steam_library=None, platform="auto", backend="auto", output="workspace")
        manifest = {
            "game": {"installPath": "C:\\Games\\BG3"},
            "locales": [{"status": "ready"}, {"status": "unsupported"}],
            "warnings": [{"code": "EXAMPLE"}],
        }
        stream = io.StringIO()
        with (
            patch("bg3loc.commands.scan.build_manifest", return_value=manifest),
            patch("bg3loc.commands.scan.SchemaStore.validate"),
            patch("bg3loc.commands.scan.write_json"),
            redirect_stdout(stream),
        ):
            self.assertEqual(scan.run(args), 0)
        self.assertIn("Scan PASS", stream.getvalue())
        self.assertIn("1 ready, 1 warning", stream.getvalue())
        self.assertIn("scan-manifest.json", stream.getvalue())

    def test_scan_unavailable_explicit_backend_exits_six_without_success_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "Baldurs Gate 3"
            (game / "Data" / "Localization").mkdir(parents=True)
            (game / "Data" / "Localization" / "English.pak").write_bytes(b"english")
            output = root / "workspace"
            probe = BackendProbe(
                id="lslib-windows-exe",
                available=False,
                reason="Divine.exe not found; set BG3LOC_DIVINE_EXE to the extracted executable path",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                patch("bg3loc.scanner.resolve_backend", return_value=probe),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                code = main([
                    "scan",
                    "--game-dir",
                    str(game),
                    "--platform",
                    "windows",
                    "--backend",
                    "lslib-windows-exe",
                    "--output",
                    str(output),
                ])

            self.assertEqual(code, 6)
            self.assertNotIn("Scan PASS", stdout.getvalue())
            self.assertIn("BACKEND_UNAVAILABLE", stderr.getvalue())
            self.assertIn("Divine.exe", stderr.getvalue())
            self.assertIn("BG3LOC_DIVINE_EXE", stderr.getvalue())
            self.assertFalse((output / "scan-manifest.json").exists())

    def test_extract_success_summary(self) -> None:
        args = SimpleNamespace(scan="scan.json", source="English", target="French", reference=[], output="extract")
        manifest = {"locales": [{"localeId": "English", "nodeCount": 10}, {"localeId": "French", "nodeCount": 9}]}
        stream = io.StringIO()
        with patch("bg3loc.commands.extract.run_extract", return_value=manifest), redirect_stdout(stream):
            self.assertEqual(extract.run(args), 0)
        self.assertIn("Extract PASS", stream.getvalue())
        self.assertIn("English: 10", stream.getvalue())
        self.assertIn("extract-manifest.json", stream.getvalue())

    def test_build_success_summary(self) -> None:
        args = SimpleNamespace(extract="extract.json", mode="basic", format="csv", max_rows=1500, context=None, glossary=None, output="build")
        manifest = {"mode": "basic", "format": "csv", "materials": [{"recordCount": 3}]}
        stream = io.StringIO()
        with patch("bg3loc.commands.build.run_build", return_value=manifest), redirect_stdout(stream):
            self.assertEqual(build.run(args), 0)
        self.assertIn("Build PASS", stream.getvalue())
        self.assertIn("rows: 3", stream.getvalue())
        self.assertIn("build-manifest.json", stream.getvalue())

    def test_validate_success_summary_includes_missing_count(self) -> None:
        args = SimpleNamespace(build="build.json", input="return.csv", strict=True, output="validate")
        manifest = {
            "accepted": {"recordCount": 3},
            "rejected": {"recordCount": 0},
            "summary": {"status": "pass", "errorCount": 0, "warningCount": 0, "missingReturnRowCount": 97},
        }
        stream = io.StringIO()
        with patch("bg3loc.commands.validate.run_validate", return_value=manifest), redirect_stdout(stream):
            self.assertEqual(validate.run(args), 0)
        self.assertIn("Validate PASS", stream.getvalue())
        self.assertIn("missing from return: 97", stream.getvalue())
        self.assertIn("validate-manifest.json", stream.getvalue())

    def test_rebuild_success_summary(self) -> None:
        args = SimpleNamespace(validate="validate.json", extract="extract.json", container="auto", backend="auto", output="rebuild")
        manifest = {"artifacts": [{"type": "pak", "path": "target.pak", "sha256": "abc123"}]}
        stream = io.StringIO()
        with patch("bg3loc.commands.rebuild.run_rebuild", return_value=manifest), redirect_stdout(stream):
            self.assertEqual(rebuild.run(args), 0)
        self.assertIn("Rebuild PASS", stream.getvalue())
        self.assertIn("target.pak", stream.getvalue())
        self.assertIn("abc123", stream.getvalue())

    def test_install_dry_run_success_summary(self) -> None:
        args = SimpleNamespace(rebuild="rebuild.json", scan="scan.json", game_dir=None, backup_dir="backups", dry_run=True, rollback=None)
        result = {"preflight": {"destination": "target.pak"}}
        stream = io.StringIO()
        with patch("bg3loc.commands.install.run_install", return_value=result), redirect_stdout(stream):
            self.assertEqual(install.run(args), 0)
        self.assertIn("Install dry-run PASS", stream.getvalue())
        self.assertIn("Game modified: no", stream.getvalue())

    def test_install_and_rollback_success_summaries(self) -> None:
        install_args = SimpleNamespace(rebuild="rebuild.json", scan="scan.json", game_dir=None, backup_dir="backups", dry_run=False, rollback=None)
        install_result = {"deployment": [{"destination": "target.pak", "backupPath": "backup.pak"}]}
        rollback_args = SimpleNamespace(rebuild="rebuild.json", scan="scan.json", game_dir=None, backup_dir="backups", dry_run=False, rollback="install.json")
        rollback_result = {"destination": "target.pak", "restoredSha256": "original"}
        stream = io.StringIO()
        with patch("bg3loc.commands.install.run_install", side_effect=[install_result, rollback_result]), redirect_stdout(stream):
            self.assertEqual(install.run(install_args), 0)
            self.assertEqual(install.run(rollback_args), 0)
        output = stream.getvalue()
        self.assertIn("Install PASS", output)
        self.assertIn("Rollback available: yes", output)
        self.assertIn("Rollback PASS", output)
        self.assertIn("original", output)


if __name__ == "__main__":
    unittest.main()
