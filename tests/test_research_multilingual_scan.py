from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bg3loc.backends import ArchiveEntry
from bg3loc.research.scanner import scan_game_research_resources


class _FakeBackend:
    def list_archive(self, package: Path):
        locale = package.stem
        return [
            ArchiveEntry(
                path=f"Localization/{locale}/{locale.lower()}.loca",
                size=123,
                crc=456,
            )
        ]


class ResearchMultilingualScanTests(unittest.TestCase):
    def test_missing_requested_reference_locales_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "Baldurs Gate 3"
            localization = game / "Data" / "Localization"
            localization.mkdir(parents=True)
            (localization / "English.pak").write_bytes(b"english")
            (localization / "ChineseTraditional.pak").write_bytes(b"traditional")

            with self.assertRaisesRegex(
                RuntimeError,
                r"Missing requested localization archive\(s\): .*Chinese\.pak.*Russian\.pak",
            ):
                scan_game_research_resources(
                    game,
                    source_locale="English",
                    target_locale="ChineseTraditional",
                    reference_locales=["Chinese", "Russian"],
                    backend=_FakeBackend(),
                )

    def test_requested_reference_locales_are_classified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "Baldurs Gate 3"
            localization = game / "Data" / "Localization"
            localization.mkdir(parents=True)
            for locale in ("English", "ChineseTraditional", "Chinese", "Russian"):
                (localization / f"{locale}.pak").write_bytes(locale.encode("ascii"))

            rows = scan_game_research_resources(
                game,
                source_locale="English",
                target_locale="ChineseTraditional",
                reference_locales=["Chinese", "Russian"],
                backend=_FakeBackend(),
            )

            by_package = {row.pakName: row.sourceRole for row in rows}
            self.assertEqual(by_package["English.pak"], "SourceLocalization")
            self.assertEqual(by_package["ChineseTraditional.pak"], "TargetLocalization")
            self.assertEqual(by_package["Chinese.pak"], "ReferenceLocalization")
            self.assertEqual(by_package["Russian.pak"], "ReferenceLocalization")


if __name__ == "__main__":
    unittest.main()
