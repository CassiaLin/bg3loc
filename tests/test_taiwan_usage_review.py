from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from bg3loc.review.taiwan_usage import (
    TaiwanUsageRule,
    candidates_from_target,
    prepare_taiwan_usage_review,
    validate_taiwan_usage_review,
)


class TaiwanUsageReviewTests(unittest.TestCase):
    def test_candidate_scan_aggregates_rules_per_content_uid(self) -> None:
        rules = (
            TaiwanUsageRule("R1", "literal", "測試詞", "Lexical", "Review this usage", "", False),
            TaiwanUsageRule("R2", "regex", r"甲詞|乙詞", "Terminology", "Synthetic alternative token", "", False),
        )
        rows = candidates_from_target(
            source_records={"h1": "source one", "h2": "source two"},
            target_records={"h1": "測試詞與甲詞", "h2": "沒有命中"},
            rules=rules,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].content_uid, "h1")
        self.assertEqual(rows[0].finding_count, 2)
        self.assertEqual([item.rule_id for item in rows[0].findings], ["R1", "R2"])

    def test_prepare_uses_only_current_corpus_and_supplied_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            normalized = root / "normalized"
            normalized.mkdir()
            (normalized / "English.jsonl").write_text(
                json.dumps({"contentUid": "h1", "text": "Hello"}) + "\n",
                encoding="utf-8-sig",
            )
            (normalized / "ChineseTraditional.jsonl").write_text(
                json.dumps({"contentUid": "h1", "text": "測試詞"}, ensure_ascii=False) + "\n",
                encoding="utf-8-sig",
            )
            extract = root / "extract-manifest.json"
            extract.write_text(json.dumps({
                "sourceLocale": "English",
                "targetLocale": "ChineseTraditional",
                "referenceLocales": [],
                "locales": [
                    {"localeId": "English", "normalized": "normalized/English.jsonl"},
                    {"localeId": "ChineseTraditional", "normalized": "normalized/ChineseTraditional.jsonl"},
                ],
            }), encoding="utf-8-sig")
            rules = root / "rules.json"
            rules.write_text(json.dumps({
                "schemaVersion": "1.0",
                "rules": [{
                    "ruleId": "SYN-001",
                    "kind": "literal",
                    "pattern": "測試詞",
                    "category": "Synthetic",
                    "rationale": "Synthetic fixture only"
                }]
            }, ensure_ascii=False), encoding="utf-8-sig")

            out = root / "review"
            manifest = prepare_taiwan_usage_review(
                extract_manifest=extract,
                rules_path=rules,
                output_dir=out,
            )
            self.assertEqual(manifest["counts"]["total"], 1)
            self.assertEqual(manifest["counts"]["findings"], 1)
            inputs = manifest["generationInputs"]
            self.assertTrue(inputs["reviewerSuppliedRuleSet"])
            self.assertFalse(inputs["historicalWorkbook"])
            self.assertFalse(inputs["historicalUidList"])
            self.assertFalse(inputs["historicalReviewDecision"])
            self.assertFalse(inputs["bundledTaiwanLexicon"])

            validation = validate_taiwan_usage_review(
                input_path=out / "taiwan-usage-review.csv",
                manifest_path=out / "taiwan-usage-review-manifest.json",
                output_dir=root / "validation",
            )
            self.assertEqual(validation["status"], "passed")
            self.assertEqual(validation["findingCount"], 0)

    def test_validator_requires_revision_text_and_preserves_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            normalized = root / "normalized"
            normalized.mkdir()
            (normalized / "English.jsonl").write_text(
                json.dumps({"contentUid": "h1", "text": "Use {name}"}) + "\n",
                encoding="utf-8",
            )
            (normalized / "ChineseTraditional.jsonl").write_text(
                json.dumps({"contentUid": "h1", "text": "測試詞 {name}"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            extract = root / "extract-manifest.json"
            extract.write_text(json.dumps({
                "sourceLocale": "English",
                "targetLocale": "ChineseTraditional",
                "referenceLocales": [],
                "locales": [
                    {"localeId": "English", "normalized": "normalized/English.jsonl"},
                    {"localeId": "ChineseTraditional", "normalized": "normalized/ChineseTraditional.jsonl"},
                ],
            }), encoding="utf-8")
            rules = root / "rules.json"
            rules.write_text(json.dumps({
                "schemaVersion": "1.0",
                "rules": [{
                    "ruleId": "SYN-001", "kind": "literal", "pattern": "測試詞",
                    "category": "Synthetic", "rationale": "Synthetic fixture only"
                }]
            }, ensure_ascii=False), encoding="utf-8")
            out = root / "review"
            prepare_taiwan_usage_review(extract_manifest=extract, rules_path=rules, output_dir=out)

            review_csv = out / "taiwan-usage-review.csv"
            with review_csv.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                rows = list(reader)
                fieldnames = list(reader.fieldnames or [])
            rows[0]["ReviewerDecision"] = "Revise"
            rows[0]["ProposedText"] = "修訂文字"
            with review_csv.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            result = validate_taiwan_usage_review(
                input_path=review_csv,
                manifest_path=out / "taiwan-usage-review-manifest.json",
                output_dir=root / "validation",
            )
            self.assertEqual(result["status"], "failed")
            self.assertTrue(any(item["code"] == "TWU006" for item in result["findings"]))


if __name__ == "__main__":
    unittest.main()
