from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bg3loc.extractor import ExtractFailure, ExtractRequest, _resolve_primary_loca_entry, run_extract


class FakeBackend:
    id = "fake"

    def __init__(self) -> None:
        self.extracted_paths: list[str] = []

    def probe(self):  # pragma: no cover - not used by injected backend
        raise NotImplementedError

    def list_archive(self, package: Path, expression: str = "*"):
        raise NotImplementedError

    def extract_single_file(self, package: Path, packaged_path: str, destination: Path) -> None:
        self.extracted_paths.append(packaged_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"LOCA")

    def convert_loca(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.suffix == ".loca":
            destination.write_bytes(b"LOCA-ROUNDTRIP")
            return
        locale_id = destination.parent.name
        if locale_id == "English":
            contents = [
                ("h001", 1, "Hello"),
                ("h002", 2, "Only source"),
            ]
        else:
            contents = [
                ("h001", 1, "哈囉"),
                ("h003", 3, "只有目標語言"),
            ]
        body = "".join(
            f'<content contentuid="{uid}" version="{version}">{text}</content>'
            for uid, version, text in contents
        )
        destination.write_text(f"<contentList>{body}</contentList>", encoding="utf-8")


class ExtractV1Tests(unittest.TestCase):
    def test_selects_single_canonical_loca(self) -> None:
        locale = {"locaEntries": [{"path": "Localization/English/english.loca"}]}

        selected = _resolve_primary_loca_entry(locale, "English")

        self.assertEqual(selected, "Localization/English/english.loca")

    def test_selects_canonical_loca_among_auxiliary_entries(self) -> None:
        locale = {
            "locaEntries": [
                {"path": "Localization/English/english_gender.loca"},
                {"path": "Localization/English/english.loca"},
                {"path": "Localization/English/english_to_f.loca"},
            ]
        }

        selected = _resolve_primary_loca_entry(locale, "English")

        self.assertEqual(selected, "Localization/English/english.loca")

    def test_primary_selection_is_case_insensitive_and_slash_normalized(self) -> None:
        locale = {
            "locaEntries": [
                {"path": "LOCALIZATION\\ChineseTraditional\\chinesetraditional.LOCA"},
            ]
        }

        selected = _resolve_primary_loca_entry(locale, "ChineseTraditional")

        self.assertEqual(selected, "LOCALIZATION\\ChineseTraditional\\chinesetraditional.LOCA")

    def test_auxiliary_only_entries_fail_closed(self) -> None:
        locale = {
            "locaEntries": [
                {"path": "Localization/English/english_gender.loca"},
                {"path": "Localization/English/english_to_f.loca"},
            ]
        }

        with self.assertRaisesRegex(ExtractFailure, "no canonical primary LOCA") as raised:
            _resolve_primary_loca_entry(locale, "English")

        self.assertIn("2 LOCA entries", str(raised.exception))
        self.assertIn("english_gender.loca", str(raised.exception))

    def test_ambiguous_canonical_entries_fail_closed(self) -> None:
        locale = {
            "locaEntries": [
                {"path": "Localization/English/english.loca"},
                {"path": "LOCALIZATION\\ENGLISH\\ENGLISH.LOCA"},
            ]
        }

        with self.assertRaisesRegex(ExtractFailure, "ambiguous canonical primary LOCA") as raised:
            _resolve_primary_loca_entry(locale, "English")

        self.assertIn("Localization/English/english.loca", str(raised.exception))
        self.assertIn(r"LOCALIZATION\ENGLISH\ENGLISH.LOCA", str(raised.exception))

    def test_wrong_locale_directory_is_not_primary(self) -> None:
        locale = {"locaEntries": [{"path": "Localization/French/english.loca"}]}

        with self.assertRaisesRegex(ExtractFailure, "no canonical primary LOCA"):
            _resolve_primary_loca_entry(locale, "English")

    def test_extract_normalizes_and_full_outer_aligns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packages = root / "packages"
            packages.mkdir()
            english_pak = packages / "English.pak"
            target_pak = packages / "ChineseTraditional.pak"
            english_pak.write_bytes(b"english")
            target_pak.write_bytes(b"target")

            scan = {
                "schemaVersion": "1.0",
                "game": {
                    "id": "bg3",
                    "appId": 1086940,
                    "installPath": str(root / "game"),
                    "dataPath": str(root / "game" / "Data"),
                    "buildId": "24532579",
                    "gameVersion": None,
                },
                "platform": {"os": "windows", "installKind": "explicit"},
                "backend": {"id": "fake", "version": None},
                "locales": [
                    {
                        "localeId": "English",
                        "packageFile": str(english_pak),
                        "packageSha256": "0" * 64,
                        "locaEntries": [
                            {"path": "Localization/English/english_gender.loca"},
                            {"path": "Localization/English/english.loca"},
                            {"path": "Localization/English/english_to_f.loca"},
                        ],
                        "status": "ready",
                    },
                    {
                        "localeId": "ChineseTraditional",
                        "packageFile": str(target_pak),
                        "packageSha256": "1" * 64,
                        "locaEntries": [
                            {"path": "Localization/ChineseTraditional/chinesetraditional_to_f.loca"},
                            {"path": "Localization/ChineseTraditional/chinesetraditional.loca"},
                        ],
                        "status": "ready",
                    },
                ],
                "warnings": [],
            }
            scan_path = root / "scan-manifest.json"
            scan_path.write_text(json.dumps(scan), encoding="utf-8")
            output = root / "extract"

            backend = FakeBackend()
            manifest = run_extract(
                ExtractRequest(
                    scan_manifest=scan_path,
                    source="English",
                    target="ChineseTraditional",
                    output=output,
                ),
                backend=backend,
            )

            self.assertEqual(manifest["sourceLocale"], "English")
            self.assertEqual(manifest["targetLocale"], "ChineseTraditional")
            self.assertEqual(len(manifest["locales"]), 2)
            self.assertEqual(
                backend.extracted_paths,
                [
                    "Localization/English/english.loca",
                    "Localization/ChineseTraditional/chinesetraditional.loca",
                ],
            )
            self.assertEqual(manifest["locales"][0]["locaEntry"], "Localization/English/english.loca")
            self.assertEqual(
                manifest["locales"][1]["locaEntry"],
                "Localization/ChineseTraditional/chinesetraditional.loca",
            )

            english_rows = [
                json.loads(line)
                for line in (output / "normalized" / "English.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([row["contentUid"] for row in english_rows], ["h001", "h002"])
            self.assertEqual(english_rows[0]["version"], 1)

            aligned = [
                json.loads(line)
                for line in (output / "aligned" / "source-target.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([row["contentUid"] for row in aligned], ["h001", "h002", "h003"])
            h002 = next(row for row in aligned if row["contentUid"] == "h002")
            h003 = next(row for row in aligned if row["contentUid"] == "h003")
            self.assertIsNone(h002["locales"]["ChineseTraditional"])
            self.assertIsNone(h003["locales"]["English"])

            roundtrip = json.loads((output / "validation" / "roundtrip.json").read_text(encoding="utf-8"))
            self.assertTrue(all(item["semanticMatch"] for item in roundtrip["locales"]))
            self.assertTrue((output / "extract-manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
