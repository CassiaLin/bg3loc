from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from bg3loc.review.multilingual import prepare_multilingual_review, validate_multilingual_review


def _write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


class MultilingualHumanReviewTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        source = root / "english.jsonl"
        target = root / "target.jsonl"
        ref = root / "ref.jsonl"
        mappings = root / "research-mappings.jsonl"
        manifest = root / "extract-manifest.json"

        _write_jsonl(source, [
            {"contentUid": "h_shared", "text": "Shared"},
            {"contentUid": "h_boundary", "text": "Shared"},
            {"contentUid": "h_none", "text": "Unique"},
        ])
        _write_jsonl(target, [
            {"contentUid": "h_shared", "text": "共用"},
        ])
        _write_jsonl(ref, [
            {"contentUid": "h_boundary", "text": "參照"},
        ])
        manifest.write_text(json.dumps({
            "sourceLocale": "English",
            "targetLocale": "Target",
            "referenceLocales": ["Reference"],
            "locales": [
                {"localeId": "English", "normalized": source.name},
                {"localeId": "Target", "normalized": target.name},
                {"localeId": "Reference", "normalized": ref.name},
            ],
        }), encoding="utf-8")
        _write_jsonl(mappings, [
            {
                "contentUid": "h_boundary",
                "mappingType": "multilingual-reference",
                "classification": "ExactReuseSingle",
                "metadata": {
                    "referenceType": "EXACT_SINGLE",
                    "reusableTargetOccurrenceCount": 1,
                    "reusableTargetDistinctCount": 1,
                    "hasSameUidReference": True,
                },
            },
            {
                "contentUid": "h_none",
                "mappingType": "multilingual-reference",
                "classification": "NoExactReuseCandidate",
                "metadata": {
                    "referenceType": "NO_EXACT_CANDIDATE",
                    "reusableTargetOccurrenceCount": 0,
                    "reusableTargetDistinctCount": 0,
                    "hasSameUidReference": False,
                },
            },
        ])
        return mappings, manifest

    def test_prepare_is_blind_first_and_pass2_separates_comparison_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mappings, manifest = self._fixture(root)
            output = root / "review"
            result = prepare_multilingual_review(
                mappings_path=mappings,
                extract_manifest=manifest,
                output_dir=output,
                include_pass2=True,
            )
            self.assertEqual(result["counts"]["total"], 2)
            self.assertEqual(result["counts"]["classifications"]["EXACT_SINGLE"], 1)
            pass1 = (output / "multilingual-review-pass1.csv").read_text(encoding="utf-8")
            self.assertNotIn("ExactReuseCandidates", pass1.splitlines()[0])
            self.assertNotIn("ReferenceComparison", pass1.splitlines()[0])
            pass2 = (output / "multilingual-review-pass2.csv").read_text(encoding="utf-8")
            self.assertIn("共用", pass2)
            self.assertIn("參照", pass2)

    def test_boundary_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mappings, manifest = self._fixture(root)
            rows = [json.loads(line) for line in mappings.read_text(encoding="utf-8").splitlines()]
            mappings.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "boundary mismatch"):
                prepare_multilingual_review(
                    mappings_path=mappings,
                    extract_manifest=manifest,
                    output_dir=root / "review",
                )

    def test_validation_rejects_mutated_immutable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mappings, manifest = self._fixture(root)
            output = root / "review"
            prepare_multilingual_review(
                mappings_path=mappings,
                extract_manifest=manifest,
                output_dir=output,
            )
            pass1 = output / "multilingual-review-pass1.csv"
            with pass1.open("r", encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
                fields = list(rows[0].keys())
            rows[0]["ExactReuseClass"] = "EXACT_CONFLICT"
            with pass1.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            result = validate_multilingual_review(
                input_path=pass1,
                manifest_path=output / "multilingual-review-manifest.json",
                output_dir=root / "validation",
            )
            self.assertEqual(result["status"], "failed")
            self.assertTrue(any(item["code"] == "MUL003" for item in result["findings"]))


if __name__ == "__main__":
    unittest.main()
