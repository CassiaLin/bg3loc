from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from bg3loc.installer import InstallFailure, InstallRequest, run_install


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class InstallV1Tests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, Path, Path, bytes, bytes]:
        library = root / "Library"
        steamapps = library / "steamapps"
        game = steamapps / "common" / "Baldurs Gate 3"
        destination = game / "Data" / "Localization" / "ChineseTraditional.pak"
        destination.parent.mkdir(parents=True)
        original = b"ORIGINAL-PAK"
        rebuilt = b"REBUILT-PAK"
        destination.write_bytes(original)
        steamapps.mkdir(parents=True, exist_ok=True)
        (steamapps / "appmanifest_1086940.acf").write_text(
            '"AppState"\n{\n  "appid" "1086940"\n  "installdir" "Baldurs Gate 3"\n  "buildid" "24532579"\n}\n',
            encoding="utf-8",
        )

        artifact = root / "workspace" / "rebuild" / "artifacts" / "ChineseTraditional.pak"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(rebuilt)
        rebuild = {
            "schemaVersion": "1.0",
            "targetLocale": "ChineseTraditional",
            "baseline": {"packageFile": str(destination)},
            "merge": {"acceptedRecordCount": 1, "changedUidCount": 1},
            "artifacts": [
                {"type": "pak", "path": str(artifact), "sha256": sha256_bytes(rebuilt)},
            ],
            "validation": {
                "semanticRoundTrip": "pass",
                "acceptedTextMatch": "pass",
                "uidSetIntegrity": "pass",
                "untouchedRecordIntegrity": "pass",
            },
        }
        rebuild_path = root / "workspace" / "rebuild" / "rebuild-manifest.json"
        rebuild_path.write_text(json.dumps(rebuild), encoding="utf-8")

        scan = {
            "schemaVersion": "1.0",
            "game": {
                "id": "bg3",
                "appId": 1086940,
                "installPath": str(game),
                "dataPath": str(game / "Data"),
                "buildId": "24532579",
                "gameVersion": None,
            },
            "platform": {"os": "windows", "installKind": "steam"},
            "backend": {"id": "fake", "version": None},
            "locales": [
                {
                    "localeId": "ChineseTraditional",
                    "packageFile": str(destination),
                    "packageSha256": sha256_bytes(original),
                    "locaEntries": [],
                    "status": "ready",
                }
            ],
            "warnings": [],
        }
        scan_path = root / "workspace" / "scan-manifest.json"
        scan_path.parent.mkdir(parents=True, exist_ok=True)
        scan_path.write_text(json.dumps(scan), encoding="utf-8")
        return rebuild_path, scan_path, game, destination, original, rebuilt

    def test_dry_run_performs_preflight_without_writing_game_or_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rebuild, scan, _game, destination, original, _rebuilt = self._fixture(root)
            backup_dir = root / "backups"
            result = run_install(InstallRequest(rebuild, scan, backup_dir=backup_dir, dry_run=True))
            self.assertEqual(result["status"], "dry-run-pass")
            self.assertEqual(destination.read_bytes(), original)
            self.assertFalse(backup_dir.exists())

    def test_baseline_mismatch_stops_before_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rebuild, scan, _game, destination, _original, _rebuilt = self._fixture(root)
            destination.write_bytes(b"GAME-UPDATED")
            backup_dir = root / "backups"
            with self.assertRaises(InstallFailure) as ctx:
                run_install(InstallRequest(rebuild, scan, backup_dir=backup_dir))
            self.assertEqual(ctx.exception.exit_code, 53)
            self.assertFalse(backup_dir.exists())

    def test_install_creates_backup_and_rollback_restores_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rebuild, scan, _game, destination, original, rebuilt = self._fixture(root)
            result = run_install(InstallRequest(rebuild, scan, backup_dir=root / "backups"))
            self.assertEqual(destination.read_bytes(), rebuilt)
            manifest_path = Path(result["manifestPath"])
            self.assertTrue(manifest_path.is_file())
            backup_path = Path(result["deployment"][0]["backupPath"])
            self.assertEqual(backup_path.read_bytes(), original)

            rollback = run_install(InstallRequest(rebuild, scan, rollback_manifest=manifest_path))
            self.assertEqual(rollback["status"], "rolled-back")
            self.assertEqual(destination.read_bytes(), original)

    def test_rollback_refuses_to_overwrite_externally_changed_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rebuild, scan, _game, destination, _original, _rebuilt = self._fixture(root)
            result = run_install(InstallRequest(rebuild, scan, backup_dir=root / "backups"))
            manifest_path = Path(result["manifestPath"])
            destination.write_bytes(b"NEW-GAME-UPDATE")
            with self.assertRaises(InstallFailure) as ctx:
                run_install(InstallRequest(rebuild, scan, rollback_manifest=manifest_path))
            self.assertEqual(ctx.exception.exit_code, 60)
            self.assertEqual(destination.read_bytes(), b"NEW-GAME-UPDATE")

    def test_build_id_mismatch_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rebuild, scan, game, _destination, _original, _rebuilt = self._fixture(root)
            manifest = game.parent.parent / "appmanifest_1086940.acf"
            manifest.write_text(
                '"AppState"\n{\n  "appid" "1086940"\n  "installdir" "Baldurs Gate 3"\n  "buildid" "99999999"\n}\n',
                encoding="utf-8",
            )
            with self.assertRaises(InstallFailure) as ctx:
                run_install(InstallRequest(rebuild, scan, backup_dir=root / "backups"))
            self.assertEqual(ctx.exception.exit_code, 53)


if __name__ == "__main__":
    unittest.main()
