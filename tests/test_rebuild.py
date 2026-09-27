from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from bg3loc.backends import ArchiveEntry
from bg3loc.rebuilder import RebuildRequest, run_rebuild, safe_archive_relative_path


class FakeRebuildBackend:
    id = "fake"

    def __init__(self, package_source: Path | None = None) -> None:
        self.package_source = package_source

    def probe(self):
        raise NotImplementedError

    def list_archive(self, package: Path, expression: str = "*") -> list[ArchiveEntry]:
        root = Path(str(package) + ".contents")
        entries: list[ArchiveEntry] = []
        if not root.is_dir():
            return entries
        for path in root.rglob("*"):
            if path.is_file() and (expression == "*" or path.suffix == ".loca"):
                rel = path.relative_to(root).as_posix()
                entries.append(ArchiveEntry(rel, path.stat().st_size, 0))
        return entries

    def extract_single_file(self, package: Path, packaged_path: str, destination: Path) -> None:
        source = Path(str(package) + ".contents").joinpath(*packaged_path.replace("\\", "/").split("/"))
        if not source.is_file():
            raise FileNotFoundError(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    def extract_package(self, package: Path, destination: Path) -> None:
        source = self.package_source or Path(str(package) + ".contents")
        shutil.copytree(source, destination, dirs_exist_ok=True)

    def create_package(self, source_dir: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"PAK")
        contents = Path(str(destination) + ".contents")
        shutil.copytree(source_dir, contents, dirs_exist_ok=True)

    def convert_loca(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix == ".xml" and destination.suffix == ".loca":
            destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        elif source.suffix == ".loca" and destination.suffix == ".xml":
            destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            raise ValueError("unexpected fake conversion")


class RebuildV1Tests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, Path]:
        target_xml = root / "extract" / "locales" / "ChineseTraditional" / "source.xml"
        target_xml.parent.mkdir(parents=True)
        target_xml.write_text(
            '<contentList>'
            '<content contentuid="h001" version="1">舊譯</content>'
            '<content contentuid="h003" version="3">目標限定</content>'
            '</contentList>',
            encoding="utf-8",
        )
        target_loca = target_xml.with_name("source.loca")
        target_loca.write_text(target_xml.read_text(encoding="utf-8"), encoding="utf-8")

        source_jsonl = root / "extract" / "normalized" / "English.jsonl"
        source_jsonl.parent.mkdir(parents=True)
        source_jsonl.write_text(
            json.dumps({"contentUid": "h001", "localeId": "English", "text": "Hello", "version": 1}) + "\n" +
            json.dumps({"contentUid": "h002", "localeId": "English", "text": "Source only", "version": 2}) + "\n",
            encoding="utf-8",
        )
        target_jsonl = root / "extract" / "normalized" / "ChineseTraditional.jsonl"
        target_jsonl.write_text(
            json.dumps({"contentUid": "h001", "localeId": "ChineseTraditional", "text": "舊譯", "version": 1}, ensure_ascii=False) + "\n" +
            json.dumps({"contentUid": "h003", "localeId": "ChineseTraditional", "text": "目標限定", "version": 3}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        target_pak = root / "game" / "Data" / "Localization" / "ChineseTraditional.pak"
        target_pak.parent.mkdir(parents=True)
        target_pak.write_bytes(b"ORIGINAL-PAK")
        package_contents = Path(str(target_pak) + ".contents")
        loca_in_package = package_contents / "Localization" / "ChineseTraditional" / "chinesetraditional.loca"
        loca_in_package.parent.mkdir(parents=True)
        loca_in_package.write_text(target_xml.read_text(encoding="utf-8"), encoding="utf-8")
        (package_contents / "metadata.txt").write_text("preserve me", encoding="utf-8")

        extract_manifest = {
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
                    "sourceLoca": str(root / "extract" / "locales" / "English" / "source.loca"),
                    "sourceXml": str(root / "extract" / "locales" / "English" / "source.xml"),
                    "normalized": str(source_jsonl),
                    "nodeCount": 2,
                },
                {
                    "localeId": "ChineseTraditional",
                    "packageFile": str(target_pak),
                    "locaEntry": "Localization/ChineseTraditional/chinesetraditional.loca",
                    "sourceLoca": str(target_loca),
                    "sourceXml": str(target_xml),
                    "normalized": str(target_jsonl),
                    "nodeCount": 2,
                },
            ],
            "aligned": str(root / "extract" / "aligned" / "source-target.jsonl"),
            "roundtripValidation": str(root / "extract" / "validation" / "roundtrip.json"),
        }
        extract_path = root / "extract" / "extract-manifest.json"
        extract_path.write_text(json.dumps(extract_manifest), encoding="utf-8")

        accepted = root / "validate" / "accepted" / "normalized-target.jsonl"
        accepted.parent.mkdir(parents=True)
        accepted.write_text(
            json.dumps({"contentUid": "h001", "localeId": "ChineseTraditional", "text": "新譯", "version": 1}, ensure_ascii=False) + "\n" +
            json.dumps({"contentUid": "h002", "localeId": "ChineseTraditional", "text": "新增譯文", "version": 2}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        rejected = root / "validate" / "rejected" / "rejected-rows.jsonl"
        rejected.parent.mkdir(parents=True)
        rejected.write_text("", encoding="utf-8")
        validate_manifest = {
            "schemaVersion": "1.0",
            "buildManifest": str(root / "build" / "build-manifest.json"),
            "strict": True,
            "accepted": {"path": str(accepted), "recordCount": 2},
            "rejected": {"path": str(rejected), "recordCount": 0},
            "summary": {"status": "pass", "errorCount": 0, "warningCount": 0, "independentEvaluationCoverage": None},
        }
        validate_path = root / "validate" / "validate-manifest.json"
        validate_path.write_text(json.dumps(validate_manifest), encoding="utf-8")
        return validate_path, extract_path, target_pak

    def test_loca_only_merges_from_target_baseline_and_preserves_target_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            validate_path, extract_path, _target_pak = self._fixture(root)
            output = root / "rebuild"
            manifest = run_rebuild(
                RebuildRequest(validate_path, extract_path, container="loca-only", output=output),
                backend=FakeRebuildBackend(),
            )
            self.assertEqual(manifest["containerAction"], "loca-only")
            self.assertEqual(manifest["merge"]["newTargetNodeCount"], 1)
            self.assertEqual(manifest["merge"]["preservedTargetOnlyCount"], 1)
            xml = ET.parse(output / "validation" / "ChineseTraditional.roundtrip.xml")
            records = {node.attrib["contentuid"]: node.text or "" for node in xml.getroot().findall("content")}
            self.assertEqual(records, {"h001": "新譯", "h003": "目標限定", "h002": "新增譯文"})
            self.assertEqual(len(manifest["artifacts"]), 1)

    def test_auto_repack_preserves_non_loca_package_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            validate_path, extract_path, target_pak = self._fixture(root)
            output = root / "rebuild"
            manifest = run_rebuild(
                RebuildRequest(validate_path, extract_path, container="auto", output=output),
                backend=FakeRebuildBackend(Path(str(target_pak) + ".contents")),
            )
            self.assertEqual(manifest["containerAction"], "repack")
            pak = output / "artifacts" / "ChineseTraditional.pak"
            self.assertTrue(pak.is_file())
            repacked_contents = Path(str(pak) + ".contents")
            self.assertEqual((repacked_contents / "metadata.txt").read_text(encoding="utf-8"), "preserve me")
            loca = repacked_contents / "Localization" / "ChineseTraditional" / "chinesetraditional.loca"
            artifact_loca = output / "artifacts" / "ChineseTraditional.loca"
            self.assertEqual(loca.read_bytes(), artifact_loca.read_bytes())
            text = loca.read_text(encoding="utf-8")
            self.assertIn("新譯", text)
            self.assertIn("目標限定", text)
            self.assertEqual({item["type"] for item in manifest["artifacts"]}, {"loca", "pak"})
            self.assertEqual(
                {entry.path for entry in FakeRebuildBackend().list_archive(target_pak)},
                {entry.path for entry in FakeRebuildBackend().list_archive(pak)},
            )

    def test_archive_entry_path_rejects_unsafe_forms(self) -> None:
        for raw in ("/absolute/file.loca", "../escape.loca", "Localization/../escape.loca", "C:/escape.loca"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    safe_archive_relative_path(raw)
        self.assertEqual(
            safe_archive_relative_path(r"Localization\ChineseTraditional\chinesetraditional.loca").as_posix(),
            "Localization/ChineseTraditional/chinesetraditional.loca",
        )


if __name__ == "__main__":
    unittest.main()
