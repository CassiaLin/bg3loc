from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from bg3loc.review.quest import (
    PASS1_COLUMNS,
    candidates_from_evidence,
    prepare_quest_review,
    validate_quest_review,
)


def quest_mapping(uid: str, role: str, occurrences: list[tuple[str, str]], text: str) -> tuple[dict, dict[str, str]]:
    evidence = []
    for path, field in occurrences:
        evidence.append({
            "sourceRole": "QuestJournalField",
            "resourcePath": path,
            "evidenceType": "QuestJournal",
            "ruleId": "BG3-QUEST-JOURNAL-EVIDENCE",
            "properties": {
                "fieldName": field,
                "fieldRole": role,
                "pakName": "Synthetic.pak",
            },
        })
    return ({
        "contentUid": uid,
        "mappingType": "context-evidence",
        "classification": role,
        "evidence": evidence,
        "metadata": {"fieldName": occurrences[0][1]},
    }, {uid: text})


class QuestReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        desc, desc_text = quest_mapping(
            "synthetic-quest-desc",
            "QuestDescription",
            [("Synthetic/QuestA.lsx", "Description"), ("Synthetic/QuestB.lsx", "Description")],
            "Find {Player} %s",
        )
        title, title_text = quest_mapping(
            "synthetic-quest-title",
            "QuestTitle",
            [("Synthetic/QuestA.lsx", "Title")],
            "A Synthetic Quest",
        )
        self.mappings = [desc, title]
        self.source = {**desc_text, **title_text}

    def test_candidates_group_occurrences_by_content_uid(self) -> None:
        candidates = candidates_from_evidence(self.mappings, self.source)
        self.assertEqual(len(candidates), 2)
        by_uid = {item.content_uid: item for item in candidates}
        self.assertEqual(by_uid["synthetic-quest-desc"].occurrence_count, 2)
        self.assertEqual(by_uid["synthetic-quest-title"].occurrence_count, 1)
        self.assertEqual(by_uid["synthetic-quest-desc"].quest_role, "QuestDescription")
        self.assertEqual(by_uid["synthetic-quest-desc"].protected_tokens, ("{Player}", "%s"))

    def test_candidate_id_is_stable_across_input_order(self) -> None:
        left = candidates_from_evidence(self.mappings, self.source)
        right = candidates_from_evidence(reversed(self.mappings), self.source)
        self.assertEqual([item.candidate_id for item in left], [item.candidate_id for item in right])

    def _package(self, root: Path, include_pass2: bool = True) -> tuple[Path, Path, Path]:
        mappings = root / "mappings.jsonl"
        mappings.write_text("".join(json.dumps(item) + "\n" for item in self.mappings), encoding="utf-8")
        normalized = {}
        locale_records = {
            "English": self.source,
            "SyntheticTarget": {"synthetic-quest-title": "Synthetic target title"},
            "SyntheticReference": {uid: f"ref-{i}" for i, uid in enumerate(self.source)},
        }
        for locale, records in locale_records.items():
            path = root / f"{locale}.jsonl"
            path.write_text(
                "".join(json.dumps({"contentUid": uid, "text": text}) + "\n" for uid, text in records.items()),
                encoding="utf-8",
            )
            normalized[locale] = path
        manifest = root / "extract-manifest.json"
        manifest.write_text(json.dumps({
            "sourceLocale": "English",
            "targetLocale": "SyntheticTarget",
            "referenceLocales": ["SyntheticReference"],
            "locales": [{"localeId": locale, "normalized": str(path)} for locale, path in normalized.items()],
        }), encoding="utf-8")
        output = root / "review"
        prepare_quest_review(
            mappings_path=mappings,
            extract_manifest=manifest,
            output_dir=output,
            include_pass2=include_pass2,
        )
        return output / "quest-review-pass1.csv", output / "quest-review-pass2.csv", output / "quest-review-manifest.json"

    @staticmethod
    def _read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            return list(reader.fieldnames or []), list(reader)

    @staticmethod
    def _write(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def test_pass1_is_blind_and_pass2_preserves_missing_target_as_blank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pass1, pass2, _manifest = self._package(Path(tmp))
            headers1, _rows1 = self._read(pass1)
            headers2, rows2 = self._read(pass2)
            self.assertEqual(headers1, list(PASS1_COLUMNS))
            self.assertNotIn("OfficialTarget", headers1)
            self.assertNotIn("ReferenceComparison", headers1)
            by_uid = {row["ContentUid"]: row for row in rows2}
            self.assertEqual(by_uid["synthetic-quest-desc"]["OfficialTarget"], "")
            self.assertEqual(by_uid["synthetic-quest-title"]["OfficialTarget"], "Synthetic target title")
            self.assertIn("OfficialTarget", headers2)

    def test_valid_review_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _pass1, pass2, manifest = self._package(root)
            columns, rows = self._read(pass2)
            row = next(item for item in rows if item["ContentUid"] == "synthetic-quest-title")
            row["ReviewerDecision"] = "Approved"
            row["EvidenceSufficient"] = "true"
            row["DraftText"] = "Draft title"
            row["FinalDecision"] = "Approved"
            row["FinalText"] = "Final title"
            row["ApprovedAuthority"] = "OfficialTarget:SyntheticTarget"
            self._write(pass2, columns, rows)
            result = validate_quest_review(input_path=pass2, manifest_path=manifest, output_dir=root / "validated")
            self.assertEqual(result["status"], "passed")

    def test_occurrence_loss_mutation_and_duplicate_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pass1, _pass2, manifest = self._package(root)
            columns, rows = self._read(pass1)
            desc = next(item for item in rows if item["ContentUid"] == "synthetic-quest-desc")
            desc["OccurrenceCount"] = "1"
            occurrences = json.loads(desc["Occurrences"])
            desc["Occurrences"] = json.dumps(occurrences[:1], separators=(",", ":"), sort_keys=True)
            rows.append(dict(rows[0]))
            self._write(pass1, columns, rows)
            result = validate_quest_review(input_path=pass1, manifest_path=manifest, output_dir=root / "validated")
            codes = {item["code"] for item in result["findings"]}
            self.assertTrue({"QST001", "QST002", "QST009"} <= codes)

    def test_invalid_status_authority_and_protected_token_drift_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _pass1, pass2, manifest = self._package(root)
            columns, rows = self._read(pass2)
            row = next(item for item in rows if item["ContentUid"] == "synthetic-quest-desc")
            row["ReviewerDecision"] = "Maybe"
            row["FinalDecision"] = "Maybe"
            row["ApprovedAuthority"] = "HistoricalWorkbook"
            row["FinalText"] = "Dropped protected syntax"
            self._write(pass2, columns, rows)
            result = validate_quest_review(input_path=pass2, manifest_path=manifest, output_dir=root / "validated")
            codes = {item["code"] for item in result["findings"]}
            self.assertTrue({"QST007", "QST010", "QST012"} <= codes)

    def test_pass1_target_column_leakage_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pass1, _pass2, manifest = self._package(root)
            columns, rows = self._read(pass1)
            columns.append("OfficialTarget")
            for row in rows:
                row["OfficialTarget"] = "leaked"
            self._write(pass1, columns, rows)
            result = validate_quest_review(input_path=pass1, manifest_path=manifest, output_dir=root / "validated")
            self.assertIn("QST006", {item["code"] for item in result["findings"]})


if __name__ == "__main__":
    unittest.main()
