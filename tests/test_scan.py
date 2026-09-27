from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bg3loc.backends import ArchiveEntry, BackendProbe
from bg3loc.cli import main
from bg3loc.scanner import ScanFailure, ScanRequest, build_manifest
from bg3loc.steam import discover_library_roots


class _FakeBackend:
    id = "fake"

    def __init__(self, locale_by_package: dict[str, str] | None = None) -> None:
        self.locale_by_package = locale_by_package or {}
        self.probed_packages: list[Path] = []

    def probe(self) -> BackendProbe:
        return BackendProbe(id="fake", available=True)

    def list_archive(self, package: Path, expression: str = "*") -> list[ArchiveEntry]:
        self.probed_packages.append(package)
        self.last_package = package
        self.last_expression = expression
        locale_id = self.locale_by_package.get(package.name, package.stem)
        return [ArchiveEntry(path=f"Localization/{locale_id}/{locale_id.lower()}.loca", size=123, crc=456)]


def _build_with_fake_backend(request: ScanRequest) -> dict[str, object]:
    fake = _FakeBackend()
    probe = BackendProbe(id="fake", available=True)
    with patch("bg3loc.scanner.resolve_backend", return_value=probe), patch(
        "bg3loc.scanner.backend_from_probe", return_value=fake
    ):
        return build_manifest(request)


class ScanV1Tests(unittest.TestCase):
    def test_discover_library_roots_preserves_multiple_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Steam"
            steamapps = root / "steamapps"
            steamapps.mkdir(parents=True)
            a = Path(tmp) / "LibraryA"
            b = Path(tmp) / "LibraryB"
            (steamapps / "libraryfolders.vdf").write_text(
                f'''"libraryfolders"\n{{\n  "0"\n  {{\n    "path" "{a}"\n  }}\n  "1"\n  {{\n    "path" "{b}"\n  }}\n}}\n''',
                encoding="utf-8",
            )

            libraries = discover_library_roots(root)
            self.assertEqual(libraries, [root, a, b])

    def test_build_manifest_from_explicit_game_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "Baldurs Gate 3"
            localization = game / "Data" / "Localization"
            localization.mkdir(parents=True)
            (localization / "English.pak").write_bytes(b"english")
            (localization / "ChineseTraditional.pak").write_bytes(b"traditional")

            manifest = _build_with_fake_backend(ScanRequest(game_dir=game, platform="windows"))

            self.assertEqual(manifest["game"]["appId"], 1086940)
            self.assertEqual(manifest["platform"]["os"], "windows")
            self.assertEqual(manifest["platform"]["installKind"], "explicit")
            self.assertEqual(
                {item["localeId"] for item in manifest["locales"]},
                {"English", "ChineseTraditional"},
            )
            self.assertTrue(all(len(item["packageSha256"]) == 64 for item in manifest["locales"]))
            self.assertEqual(manifest["backend"]["id"], "fake")
            self.assertEqual(manifest["warnings"], [])

    def test_build_manifest_from_explicit_steam_library(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "Library"
            steamapps = library / "steamapps"
            game = steamapps / "common" / "Baldurs Gate 3"
            localization = game / "Data" / "Localization"
            localization.mkdir(parents=True)
            (localization / "English.pak").write_bytes(b"english")
            steamapps.mkdir(parents=True, exist_ok=True)
            (steamapps / "appmanifest_1086940.acf").write_text(
                '''"AppState"\n{\n  "appid" "1086940"\n  "installdir" "Baldurs Gate 3"\n  "buildid" "24532579"\n}\n''',
                encoding="utf-8",
            )

            manifest = _build_with_fake_backend(ScanRequest(steam_library=library, platform="linux"))

            self.assertEqual(manifest["game"]["buildId"], "24532579")
            self.assertEqual(manifest["platform"]["installKind"], "steam")
            self.assertEqual(manifest["locales"][0]["localeId"], "English")

    def test_explicit_game_dir_recovers_matching_steam_build_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "Library"
            steamapps = library / "steamapps"
            game = steamapps / "common" / "Baldurs Gate 3"
            localization = game / "Data" / "Localization"
            localization.mkdir(parents=True)
            (localization / "English.pak").write_bytes(b"english")
            (steamapps / "appmanifest_1086940.acf").write_text(
                '''"AppState"\n{\n  "appid" "1086940"\n  "installdir" "Baldurs Gate 3"\n  "buildid" "test-build"\n}\n''',
                encoding="utf-8",
            )

            manifest = _build_with_fake_backend(ScanRequest(game_dir=game, platform="windows"))

            self.assertEqual(manifest["game"]["buildId"], "test-build")
            self.assertEqual(manifest["platform"]["installKind"], "explicit")

    def test_non_steam_game_dir_does_not_guess_build_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "Games" / "Baldurs Gate 3"
            localization = game / "Data" / "Localization"
            localization.mkdir(parents=True)
            (localization / "English.pak").write_bytes(b"english")

            manifest = _build_with_fake_backend(ScanRequest(game_dir=game, platform="windows"))

            self.assertIsNone(manifest["game"]["buildId"])

    def test_explicit_game_dir_rejects_wrong_app_manifest_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "Library"
            steamapps = library / "steamapps"
            game = steamapps / "common" / "Baldurs Gate 3"
            localization = game / "Data" / "Localization"
            localization.mkdir(parents=True)
            (localization / "English.pak").write_bytes(b"english")
            (steamapps / "appmanifest_1086940.acf").write_text(
                '''"AppState"\n{\n  "appid" "999"\n  "installdir" "Baldurs Gate 3"\n  "buildid" "wrong-build"\n}\n''',
                encoding="utf-8",
            )

            manifest = _build_with_fake_backend(ScanRequest(game_dir=game, platform="windows"))

            self.assertIsNone(manifest["game"]["buildId"])

    def test_explicit_game_dir_rejects_mismatched_manifest_install_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "Library"
            steamapps = library / "steamapps"
            game = steamapps / "common" / "Baldurs Gate 3"
            localization = game / "Data" / "Localization"
            localization.mkdir(parents=True)
            (localization / "English.pak").write_bytes(b"english")
            (steamapps / "appmanifest_1086940.acf").write_text(
                '''"AppState"\n{\n  "appid" "1086940"\n  "installdir" "Another Copy"\n  "buildid" "wrong-build"\n}\n''',
                encoding="utf-8",
            )

            manifest = _build_with_fake_backend(ScanRequest(game_dir=game, platform="windows"))

            self.assertIsNone(manifest["game"]["buildId"])

    def test_conflicting_game_dir_and_steam_library_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            explicit_game = root / "Games" / "Baldurs Gate 3"
            (explicit_game / "Data" / "Localization").mkdir(parents=True)
            (explicit_game / "Data" / "Localization" / "English.pak").write_bytes(b"english")

            library = root / "Library"
            steamapps = library / "steamapps"
            other_game = steamapps / "common" / "Baldurs Gate 3"
            (other_game / "Data" / "Localization").mkdir(parents=True)
            (steamapps / "appmanifest_1086940.acf").write_text(
                '''"AppState"\n{\n  "appid" "1086940"\n  "installdir" "Baldurs Gate 3"\n  "buildid" "other-build"\n}\n''',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ScanFailure, "do not identify the same"):
                build_manifest(ScanRequest(game_dir=explicit_game, steam_library=library, platform="windows"))

    def test_recursive_discovery_uses_loca_identity_and_ignores_non_paks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "Baldurs Gate 3"
            localization = game / "Data" / "Localization"
            nested = localization / "a" / "b"
            nested.mkdir(parents=True)
            (localization / "English.pak").write_bytes(b"english")
            target = localization / "ChineseTraditional" / "ChineseTraditional.PAK"
            target.parent.mkdir()
            target.write_bytes(b"traditional")
            (nested / "ArbitraryName.pak").write_bytes(b"deep")
            (nested / "readme.txt").write_text("ignore", encoding="utf-8")
            (nested / "foo.bin").write_bytes(b"ignore")
            fake = _FakeBackend({"ArbitraryName.pak": "DeepLocale"})
            probe = BackendProbe(id="fake", available=True)

            with patch("bg3loc.scanner.resolve_backend", return_value=probe), patch(
                "bg3loc.scanner.backend_from_probe", return_value=fake
            ):
                manifest = build_manifest(ScanRequest(game_dir=game, platform="windows", backend="fake"))

            self.assertEqual(
                {item["localeId"] for item in manifest["locales"]},
                {"English", "ChineseTraditional", "DeepLocale"},
            )
            self.assertEqual({path.suffix.casefold() for path in fake.probed_packages}, {".pak"})
            self.assertEqual(len(fake.probed_packages), 3)

    def test_discovery_does_not_search_other_data_subtrees(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "Baldurs Gate 3"
            localization = game / "Data" / "Localization"
            localization.mkdir(parents=True)
            (localization / "English.pak").write_bytes(b"english")
            decoy = game / "Data" / "Other" / "Localization"
            decoy.mkdir(parents=True)
            (decoy / "Hidden.pak").write_bytes(b"hidden")
            fake = _FakeBackend()
            probe = BackendProbe(id="fake", available=True)

            with patch("bg3loc.scanner.resolve_backend", return_value=probe), patch(
                "bg3loc.scanner.backend_from_probe", return_value=fake
            ):
                manifest = build_manifest(ScanRequest(game_dir=game, platform="windows", backend="fake"))

            self.assertEqual([item["localeId"] for item in manifest["locales"]], ["English"])
            self.assertEqual([path.name for path in fake.probed_packages], ["English.pak"])

    def test_duplicate_locale_providers_are_preserved_and_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "Baldurs Gate 3"
            localization = game / "Data" / "Localization"
            (localization / "base").mkdir(parents=True)
            (localization / "patch").mkdir(parents=True)
            (localization / "base" / "BaseLocale.pak").write_bytes(b"base")
            (localization / "patch" / "PatchLocale.pak").write_bytes(b"patch")
            fake = _FakeBackend({"BaseLocale.pak": "SameLocale", "PatchLocale.pak": "SameLocale"})
            probe = BackendProbe(id="fake", available=True)

            with patch("bg3loc.scanner.resolve_backend", return_value=probe), patch(
                "bg3loc.scanner.backend_from_probe", return_value=fake
            ):
                manifest = build_manifest(ScanRequest(game_dir=game, platform="windows", backend="fake"))

            providers = [item for item in manifest["locales"] if item["localeId"] == "SameLocale"]
            self.assertEqual(len(providers), 2)
            self.assertTrue(all(item["status"] == "ambiguous" for item in providers))

    def test_scan_populates_loca_entries_from_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "Baldurs Gate 3"
            localization = game / "Data" / "Localization"
            localization.mkdir(parents=True)
            (localization / "English.pak").write_bytes(b"english")
            fake = _FakeBackend()
            probe = BackendProbe(id="fake", available=True)

            with patch("bg3loc.scanner.resolve_backend", return_value=probe), patch(
                "bg3loc.scanner.backend_from_probe", return_value=fake
            ):
                manifest = build_manifest(ScanRequest(game_dir=game, platform="windows", backend="fake"))

            self.assertEqual(manifest["backend"]["id"], "fake")
            self.assertEqual(manifest["warnings"], [])
            self.assertEqual(
                manifest["locales"][0]["locaEntries"],
                [{"path": "Localization/English/english.loca", "size": 123, "crc": 456}],
            )
            self.assertEqual(fake.last_expression, "*.loca")

    def test_explicit_unavailable_backend_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "Baldurs Gate 3"
            localization = game / "Data" / "Localization"
            localization.mkdir(parents=True)
            (localization / "English.pak").write_bytes(b"english")
            probe = BackendProbe(
                id="lslib-windows-exe",
                available=False,
                reason="Divine.exe not found; set BG3LOC_DIVINE_EXE to the extracted executable path",
            )

            with patch("bg3loc.scanner.resolve_backend", return_value=probe), self.assertRaises(ScanFailure) as ctx:
                build_manifest(
                    ScanRequest(game_dir=game, platform="windows", backend="lslib-windows-exe")
                )

            self.assertEqual(ctx.exception.exit_code, 6)
            self.assertEqual(ctx.exception.key, "BACKEND_UNAVAILABLE")
            self.assertIn("Divine.exe", ctx.exception.message)
            self.assertIn("BG3LOC_DIVINE_EXE", ctx.exception.message)

    def test_auto_with_no_available_backend_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "Baldurs Gate 3"
            localization = game / "Data" / "Localization"
            localization.mkdir(parents=True)
            (localization / "English.pak").write_bytes(b"english")
            probe = BackendProbe(id="unresolved", available=False, reason="No archive backend is available")

            with patch("bg3loc.scanner.resolve_backend", return_value=probe), self.assertRaises(ScanFailure) as ctx:
                build_manifest(ScanRequest(game_dir=game, platform="windows", backend="auto"))

            self.assertEqual(ctx.exception.exit_code, 6)
            self.assertEqual(ctx.exception.key, "BACKEND_UNAVAILABLE")

    def test_cli_scan_writes_schema_valid_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "Baldurs Gate 3"
            localization = game / "Data" / "Localization"
            localization.mkdir(parents=True)
            (localization / "English.pak").write_bytes(b"english")
            output = root / "workspace"

            fake = _FakeBackend()
            probe = BackendProbe(id="fake", available=True)
            with patch("bg3loc.scanner.resolve_backend", return_value=probe), patch(
                "bg3loc.scanner.backend_from_probe", return_value=fake
            ):
                code = main([
                    "scan",
                    "--game-dir",
                    str(game),
                    "--platform",
                    "windows",
                    "--output",
                    str(output),
                ])

            self.assertEqual(code, 0)
            manifest_path = output / "scan-manifest.json"
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schemaVersion"], "1.0")
            self.assertEqual(manifest["locales"][0]["localeId"], "English")


if __name__ == "__main__":
    unittest.main()
