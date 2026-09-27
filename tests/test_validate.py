from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from bg3loc.builder import BuildRequest, run_build
from bg3loc.validator import ValidateFailure, ValidateRequest, run_validate


class ValidateV1Tests(unittest.TestCase):
    def _make_extract_fixture(self, root: Path) -> Path:
        aligned = root / "extract" / "aligned" / "source-target.jsonl"
        aligned.parent.mkdir(parents=True)
        rows = [
            {
                "contentUid": "h001",
                "locales": {
                    "English": {"text": "Hello <LSTag Type=\"Spell\" Tooltip=\"Source_Action\">{Player}</LSTag> [Narrative]", "version": 1, "presence": True},
                    "ChineseTraditional": {"text": "你好 <LSTag Tooltip=\"Localized_Action\">{Player}</LSTag> [本地化]", "version": 1, "presence": True},
                },
            },
            {
                "contentUid": "h002",
                "locales": {
                    "English": {"text": "Source only", "version": 2, "presence": True},
                    "ChineseTraditional": None,
                },
            },
            {
                "contentUid": "h003",
                "locales": {
                    "English": None,
                    "ChineseTraditional": {"text": "Target only", "version": 3, "presence": True},
                },
            },
        ]
        aligned.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        validation = root / "extract" / "validation" / "roundtrip.json"
        validation.parent.mkdir(parents=True)
        validation.write_text("{}", encoding="utf-8")
        manifest = {
            "schemaVersion": "1.0",
            "scanManifest": str(root / "scan-manifest.json"),
            "sourceLocale": "English",
            "targetLocale": "ChineseTraditional",
            "referenceLocales": [],
            "backend": {"id": "fake"},
            "locales": [
                {
                    "localeId": "English",
                    "packageFile": "English.pak",
                    "locaEntry": "english.loca",
                    "sourceLoca": "English/source.loca",
                    "sourceXml": "English/source.xml",
                    "normalized": "English.jsonl",
                    "nodeCount": 2,
                },
                {
                    "localeId": "ChineseTraditional",
                    "packageFile": "ChineseTraditional.pak",
                    "locaEntry": "chinesetraditional.loca",
                    "sourceLoca": "ChineseTraditional/source.loca",
                    "sourceXml": "ChineseTraditional/source.xml",
                    "normalized": "ChineseTraditional.jsonl",
                    "nodeCount": 2,
                },
            ],
            "aligned": str(aligned),
            "roundtripValidation": str(validation),
        }
        path = root / "extract" / "extract-manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def _build_csv(self, root: Path, mode: str) -> tuple[Path, Path]:
        extract = self._make_extract_fixture(root)
        output = root / "build"
        manifest = run_build(BuildRequest(extract_manifest=extract, mode=mode, format="csv", output=output))
        return output / "build-manifest.json", Path(manifest["materials"][0]["path"])

    def _build_source_only_lstag_csv(self, root: Path, source_text: str) -> tuple[Path, Path]:
        extract = self._make_extract_fixture(root)
        aligned = root / "extract" / "aligned" / "source-target.jsonl"
        rows = [json.loads(line) for line in aligned.read_text(encoding="utf-8").splitlines()]
        rows[1]["locales"]["English"]["text"] = source_text
        aligned.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        output = root / "build"
        manifest = run_build(BuildRequest(extract_manifest=extract, mode="basic", format="csv", output=output))
        return output / "build-manifest.json", Path(manifest["materials"][0]["path"])

    def _build_many_csv(self, root: Path, mode: str, row_count: int = 100) -> tuple[Path, Path]:
        extract = self._make_extract_fixture(root)
        aligned = root / "extract" / "aligned" / "source-target.jsonl"
        rows = [
            {
                "contentUid": f"h{index:03d}",
                "locales": {
                    "English": {"text": f"Source {index}", "version": 1, "presence": True},
                    "ChineseTraditional": {"text": f"目標 {index}", "version": 1, "presence": True},
                },
            }
            for index in range(row_count)
        ]
        aligned.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        context = None
        if mode == "context":
            context = root / "context.json"
            context.write_text("{}\n", encoding="utf-8")
        output = root / "build"
        manifest = run_build(BuildRequest(
            extract_manifest=extract,
            mode=mode,
            format="csv",
            context=context,
            output=output,
        ))
        return output / "build-manifest.json", Path(manifest["materials"][0]["path"])

    def _write_partial_csv(self, source: Path, destination: Path, mode: str, row_count: int = 3) -> None:
        with source.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)[:row_count]
        candidate_field = "IndependentTargetText" if mode == "blind-first" else "TranslatedTargetText"
        for row in rows:
            row[candidate_field] = row.get("ExistingTargetText") or f"譯文 {row['ContentUid']}"
            row["TranslationStatus"] = "done"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _rewrite_csv(self, source: Path, destination: Path, edits: dict[str, dict[str, str]]) -> None:
        with source.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)
        for row in rows:
            changes = edits.get(row["ContentUid"], {})
            row.update(changes)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_basic_strict_accepts_valid_translations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_manifest, material = self._build_csv(root, "basic")
            returned = root / "returns" / "001.csv"
            self._rewrite_csv(material, returned, {
                "h001": {"TranslatedTargetText": "您好 <LSTag Tooltip=\"Localized_Action\">{Player}</LSTag> [本地化]", "TranslationStatus": "done"},
                "h002": {"TranslatedTargetText": "僅來源", "TranslationStatus": "done"},
            })

            manifest = run_validate(ValidateRequest(build_manifest=build_manifest, input_spec=str(returned), output=root / "validate"))
            self.assertEqual(manifest["summary"]["status"], "pass")
            self.assertEqual(manifest["accepted"]["recordCount"], 2)
            accepted = [
                json.loads(line)
                for line in Path(manifest["accepted"]["path"]).read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual({item["contentUid"] for item in accepted}, {"h001", "h002"})
            self.assertEqual(next(item for item in accepted if item["contentUid"] == "h002")["version"], 2)

    def test_protected_token_failure_maps_to_exit_35_and_writes_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_manifest, material = self._build_csv(root, "basic")
            returned = root / "returns" / "001.csv"
            self._rewrite_csv(material, returned, {
                "h001": {"TranslatedTargetText": "您好 Player", "TranslationStatus": "done"},
                "h002": {"TranslatedTargetText": "僅來源", "TranslationStatus": "done"},
            })
            output = root / "validate"
            with self.assertRaises(ValidateFailure) as ctx:
                run_validate(ValidateRequest(build_manifest=build_manifest, input_spec=str(returned), output=output))
            self.assertEqual(ctx.exception.exit_code, 35)
            self.assertTrue((output / "validate-manifest.json").is_file())
            errors = (output / "reports" / "validation-errors.csv").read_text(encoding="utf-8-sig")
            self.assertIn("VAL006", errors)

    def test_golden_existing_target_is_valid_without_language_specific_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_manifest, material = self._build_csv(root, "basic")
            returned = root / "returns" / "001.csv"
            self._rewrite_csv(material, returned, {
                "h001": {
                    "TranslatedTargetText": "你好 <LSTag Tooltip=\"Localized_Action\">{Player}</LSTag> [本地化]",
                    "TranslationStatus": "done",
                },
                "h002": {"TranslatedTargetText": "僅來源", "TranslationStatus": "done"},
            })

            manifest = run_validate(ValidateRequest(
                build_manifest=build_manifest,
                input_spec=str(returned),
                output=root / "validate",
            ))
            self.assertEqual(manifest["summary"]["status"], "pass")

    def test_source_target_candidate_may_remove_complete_lstag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_manifest, material = self._build_csv(root, "basic")
            returned = root / "returns" / "001.csv"
            self._rewrite_csv(material, returned, {
                "h001": {"TranslatedTargetText": "您好 {Player}", "TranslationStatus": "done"},
                "h002": {"TranslatedTargetText": "僅來源", "TranslationStatus": "done"},
            })
            manifest = run_validate(ValidateRequest(build_manifest=build_manifest, input_spec=str(returned), output=root / "validate"))
            self.assertEqual(manifest["summary"]["status"], "pass")

    def test_source_only_candidate_cannot_remove_complete_lstag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_manifest, material = self._build_source_only_lstag_csv(
                root, '<LSTag Tooltip="A">Web</LSTag>'
            )
            returned = root / "returns" / "001.csv"
            self._rewrite_csv(material, returned, {
                "h002": {"TranslatedTargetText": "蛛網", "TranslationStatus": "done"},
            })
            output = root / "validate"
            with self.assertRaises(ValidateFailure):
                run_validate(ValidateRequest(build_manifest=build_manifest, input_spec=str(returned), output=output))
            errors = (output / "reports" / "validation-errors.csv").read_text(encoding="utf-8-sig")
            self.assertIn("VAL008", errors)
            self.assertIn("source-only LSTag structure removed", errors)

    def test_source_only_candidate_may_localize_and_reduce_lstag_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_manifest, material = self._build_source_only_lstag_csv(
                root, '<LSTag Tooltip="A">Web</LSTag> and <LSTag Tooltip="B">Net</LSTag>'
            )
            returned = root / "returns" / "001.csv"
            self._rewrite_csv(material, returned, {
                "h002": {
                    "TranslatedTargetText": '<LSTag Tooltip="Localized">蛛網</LSTag>',
                    "TranslationStatus": "done",
                },
            })
            manifest = run_validate(ValidateRequest(build_manifest=build_manifest, input_spec=str(returned), output=root / "validate"))
            self.assertEqual(manifest["summary"]["status"], "pass")

    def test_source_only_self_closing_lstag_presence_policy(self) -> None:
        cases = (
            ('<LSTag Type="Image" Info="Localized"/>圖示', True),
            ('<LSTag Type="Image" Info="One"/><LSTag Type="Image" Info="Two"/>圖示', True),
            ("圖示", False),
        )
        for candidate, should_pass in cases:
            with self.subTest(candidate=candidate), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                build_manifest, material = self._build_source_only_lstag_csv(
                    root, '<LSTag Type="Image" Info="Source"/>Icon'
                )
                returned = root / "returns" / "001.csv"
                self._rewrite_csv(material, returned, {
                    "h002": {"TranslatedTargetText": candidate, "TranslationStatus": "done"},
                })
                request = ValidateRequest(build_manifest=build_manifest, input_spec=str(returned), output=root / "validate")
                if should_pass:
                    manifest = run_validate(request)
                    self.assertEqual(manifest["summary"]["status"], "pass")
                else:
                    with self.assertRaises(ValidateFailure):
                        run_validate(request)
                    errors = (root / "validate" / "reports" / "validation-errors.csv").read_text(encoding="utf-8-sig")
                    self.assertIn("source-only LSTag structure removed", errors)

    def test_source_only_malformed_lstag_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_manifest, material = self._build_source_only_lstag_csv(
                root, '<LSTag Tooltip="A">Web</LSTag>'
            )
            returned = root / "returns" / "001.csv"
            self._rewrite_csv(material, returned, {
                "h002": {"TranslatedTargetText": "<LSTag>蛛網", "TranslationStatus": "done"},
            })
            output = root / "validate"
            with self.assertRaises(ValidateFailure):
                run_validate(ValidateRequest(build_manifest=build_manifest, input_spec=str(returned), output=output))
            errors = (output / "reports" / "validation-errors.csv").read_text(encoding="utf-8-sig")
            self.assertIn("VAL008", errors)

    def test_added_runtime_placeholder_maps_to_val007(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_manifest, material = self._build_csv(root, "basic")
            returned = root / "returns" / "001.csv"
            self._rewrite_csv(material, returned, {
                "h001": {"TranslatedTargetText": "您好 {Player} %s", "TranslationStatus": "done"},
                "h002": {"TranslatedTargetText": "僅來源", "TranslationStatus": "done"},
            })
            output = root / "validate"
            with self.assertRaises(ValidateFailure):
                run_validate(ValidateRequest(build_manifest=build_manifest, input_spec=str(returned), output=output))
            errors = (output / "reports" / "validation-errors.csv").read_text(encoding="utf-8-sig")
            self.assertIn("VAL007", errors)

    def test_malformed_lstag_maps_to_val008_even_when_candidate_matches_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            malformed = "你好 <LSTag Tooltip=\"Localized_Action\">{Player}"
            extract = self._make_extract_fixture(root)
            aligned = root / "extract" / "aligned" / "source-target.jsonl"
            rows = [json.loads(line) for line in aligned.read_text(encoding="utf-8").splitlines()]
            rows[0]["locales"]["ChineseTraditional"]["text"] = malformed
            aligned.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
            build = root / "build"
            manifest = run_build(BuildRequest(extract_manifest=extract, mode="basic", format="csv", output=build))
            build_manifest = build / "build-manifest.json"
            material = Path(manifest["materials"][0]["path"])
            returned = root / "returns" / "001.csv"
            self._rewrite_csv(material, returned, {
                "h001": {
                    "TranslatedTargetText": malformed,
                    "TranslationStatus": "done",
                },
                "h002": {"TranslatedTargetText": "僅來源", "TranslationStatus": "done"},
            })
            output = root / "validate"
            with self.assertRaises(ValidateFailure):
                run_validate(ValidateRequest(build_manifest=build_manifest, input_spec=str(returned), output=output))
            errors = (output / "reports" / "validation-errors.csv").read_text(encoding="utf-8-sig")
            self.assertIn("VAL008", errors)

    def test_non_strict_accepts_valid_subset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_manifest, material = self._build_csv(root, "basic")
            returned = root / "returns" / "001.csv"
            self._rewrite_csv(material, returned, {
                "h001": {"TranslatedTargetText": "broken", "TranslationStatus": "done"},
                "h002": {"TranslatedTargetText": "僅來源", "TranslationStatus": "done"},
            })
            manifest = run_validate(ValidateRequest(
                build_manifest=build_manifest,
                input_spec=str(returned),
                strict=False,
                output=root / "validate",
            ))
            self.assertEqual(manifest["summary"]["status"], "partial")
            self.assertEqual(manifest["accepted"]["recordCount"], 1)
            self.assertEqual(manifest["rejected"]["recordCount"], 1)

    def test_basic_partial_return_aggregates_missing_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_manifest, material = self._build_many_csv(root, "basic")
            returned = root / "returns" / "001.csv"
            self._write_partial_csv(material, returned, "basic")

            manifest = run_validate(ValidateRequest(
                build_manifest=build_manifest,
                input_spec=str(returned),
                output=root / "validate",
            ))
            summary = json.loads((root / "validate" / "reports" / "validation-summary.json").read_text(encoding="utf-8"))
            findings = (root / "validate" / "reports" / "validation-errors.csv").read_text(encoding="utf-8-sig")
            self.assertEqual(manifest["summary"]["status"], "pass")
            self.assertEqual(manifest["accepted"]["recordCount"], 3)
            self.assertEqual(manifest["rejected"]["recordCount"], 0)
            self.assertEqual(manifest["summary"]["errorCount"], 0)
            self.assertEqual(manifest["summary"]["warningCount"], 0)
            self.assertEqual(manifest["summary"]["missingReturnRowCount"], 97)
            self.assertEqual(summary["missingReturnRowCount"], 97)
            self.assertEqual(len(findings.splitlines()), 1)
            self.assertNotIn("ROW_MISSING_FROM_RETURN", findings)

    def test_context_partial_return_aggregates_missing_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_manifest, material = self._build_many_csv(root, "context")
            returned = root / "returns" / "001.csv"
            self._write_partial_csv(material, returned, "context")

            manifest = run_validate(ValidateRequest(
                build_manifest=build_manifest,
                input_spec=str(returned),
                output=root / "validate",
            ))
            findings = (root / "validate" / "reports" / "validation-errors.csv").read_text(encoding="utf-8-sig")
            self.assertEqual(manifest["summary"]["status"], "pass")
            self.assertEqual(manifest["summary"]["warningCount"], 0)
            self.assertEqual(manifest["summary"]["missingReturnRowCount"], 97)
            self.assertEqual(len(findings.splitlines()), 1)

    def test_blind_first_partial_return_still_fails_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_manifest, material = self._build_many_csv(root, "blind-first")
            returned = root / "returns" / "001.csv"
            self._write_partial_csv(material, returned, "blind-first")
            output = root / "validate"

            with self.assertRaises(ValidateFailure) as ctx:
                run_validate(ValidateRequest(build_manifest=build_manifest, input_spec=str(returned), output=output))
            manifest = json.loads((output / "validate-manifest.json").read_text(encoding="utf-8"))
            findings = (output / "reports" / "validation-errors.csv").read_text(encoding="utf-8-sig")
            self.assertEqual(ctx.exception.exit_code, 36)
            self.assertEqual(manifest["summary"]["status"], "fail")
            self.assertEqual(manifest["summary"]["missingReturnRowCount"], 97)
            self.assertEqual(manifest["summary"]["warningCount"], 0)
            self.assertIn("VAL010", findings)

    def test_actionable_warning_remains_in_findings_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_manifest, material = self._build_csv(root, "basic")
            returned = root / "returns" / "001.csv"
            self._rewrite_csv(material, returned, {
                "h001": {
                    "TranslatedTargetText": "您好 <LSTag Tooltip=\"Localized_Action\">{Player}</LSTag>",
                    "TranslationStatus": "needs-more-context",
                },
                "h002": {"TranslatedTargetText": "僅來源", "TranslationStatus": "done"},
            })

            manifest = run_validate(ValidateRequest(
                build_manifest=build_manifest,
                input_spec=str(returned),
                output=root / "validate",
            ))
            findings = (root / "validate" / "reports" / "validation-errors.csv").read_text(encoding="utf-8-sig")
            self.assertEqual(manifest["summary"]["status"], "pass")
            self.assertEqual(manifest["summary"]["warningCount"], 1)
            self.assertEqual(manifest["summary"]["missingReturnRowCount"], 0)
            self.assertIn("VAL102", findings)
            self.assertIn("STATUS_NEEDS_MORE_CONTEXT", findings)

    def test_blind_first_requires_100_percent_independent_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_manifest, material = self._build_csv(root, "blind-first")
            returned = root / "returns" / "001.csv"
            self._rewrite_csv(material, returned, {
                "h001": {"IndependentTargetText": "您好 <LSTag Tooltip=\"Localized_Action\">{Player}</LSTag>", "TranslationStatus": "done"},
            })
            output = root / "validate"
            with self.assertRaises(ValidateFailure) as ctx:
                run_validate(ValidateRequest(build_manifest=build_manifest, input_spec=str(returned), output=output))
            self.assertEqual(ctx.exception.exit_code, 36)
            manifest = json.loads((output / "validate-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["summary"]["independentEvaluationCoverage"], 0.5)
            errors = (output / "reports" / "validation-errors.csv").read_text(encoding="utf-8-sig")
            self.assertIn("VAL010", errors)


if __name__ == "__main__":
    unittest.main()
