from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from bg3loc.review.bark import (
    PASS1_COLUMNS,
    candidates_from_evidence,
    prepare_bark_review,
    validate_bark_review,
)


def evidence(uid: str, mode: str, members: list[str], text: str) -> tuple[dict, dict[str, str]]:
    speaker_members = [
        {"identity": member, "provenance": "Synthetic/Container.lsj#speakerlist"}
        for member in members
    ]
    return ({
        "contentUid": uid,
        "mappingType": "context-evidence",
        "classification": mode,
        "evidence": [{
            "sourceRole": "DialogNodeTaggedText",
            "resourcePath": "Synthetic/Container.lsj",
            "evidenceType": "BarkSpeakerStructure",
            "ruleId": "BG3-BARK-SPEAKER-STRUCTURE",
            "properties": {
                "dialogUuid": "synthetic-dialog", "nodeUuid": f"node-{uid}",
                "speakerSlot": "0", "pakName": "Synthetic.pak",
                "speakerMembers": speaker_members,
                "sharedGroupId": "BARK-GROUP-SYNTHETIC" if mode == "SharedSpeaker" else "",
            },
        }],
    }, {uid: text})


class BarkReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        single, single_text = evidence("synthetic-single-uid", "SingleSpeaker", ["Speaker-One"], "Hello {Player} %s")
        shared, shared_text = evidence("synthetic-shared-uid", "SharedSpeaker", ["Member-A", "Member-B", "Member-C"], "Together <LSTag Type=\"X\">now</LSTag>")
        self.mappings = [single, shared]
        self.source = {**single_text, **shared_text}

    def test_candidate_generation_preserves_single_and_shared_evidence(self) -> None:
        candidates = candidates_from_evidence(self.mappings, self.source)
        by_mode = {candidate.speaker_mode: candidate for candidate in candidates}
        self.assertEqual(by_mode["SingleSpeaker"].speaker_count, 1)
        self.assertEqual(by_mode["SharedSpeaker"].speaker_count, 3)
        self.assertEqual([m.identity for m in by_mode["SharedSpeaker"].speakers], ["Member-A", "Member-B", "Member-C"])
        self.assertEqual(by_mode["SingleSpeaker"].protected_tokens, ("{Player}", "%s"))
        self.assertEqual(by_mode["SharedSpeaker"].protected_tokens, ("<LSTag>", "</LSTag>"))

    def test_candidate_id_is_stable(self) -> None:
        left = candidates_from_evidence(self.mappings, self.source)
        right = candidates_from_evidence(reversed(self.mappings), self.source)
        self.assertEqual([item.candidate_id for item in left], [item.candidate_id for item in right])

    def _package(self, root: Path, include_pass2: bool = True) -> tuple[Path, Path, Path]:
        mappings = root / "mappings.jsonl"
        mappings.write_text("".join(json.dumps(item) + "\n" for item in self.mappings), encoding="utf-8")
        normalized = {}
        for locale, records in {
            "English": self.source,
            "SyntheticTarget": {uid: f"target-{index}" for index, uid in enumerate(self.source)},
            "SyntheticReference": {uid: f"reference-{index}" for index, uid in enumerate(self.source)},
        }.items():
            path = root / f"{locale}.jsonl"
            path.write_text("".join(json.dumps({"contentUid": uid, "text": text}) + "\n" for uid, text in records.items()), encoding="utf-8")
            normalized[locale] = path
        manifest = root / "extract-manifest.json"
        manifest.write_text(json.dumps({
            "sourceLocale": "English", "targetLocale": "SyntheticTarget",
            "referenceLocales": ["SyntheticReference"],
            "locales": [{"localeId": locale, "normalized": str(path)} for locale, path in normalized.items()],
        }), encoding="utf-8")
        output = root / "review"
        prepare_bark_review(mappings_path=mappings, extract_manifest=manifest, output_dir=output, include_pass2=include_pass2)
        return output / "bark-review-pass1.csv", output / "bark-review-pass2.csv", output / "bark-review-manifest.json"

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

    def test_pass_surfaces_are_physically_separate_and_pass1_has_no_target_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pass1, pass2, _manifest = self._package(Path(tmp))
            headers1, rows1 = self._read(pass1)
            headers2, rows2 = self._read(pass2)
            self.assertEqual(headers1, list(PASS1_COLUMNS))
            self.assertNotIn("OfficialTarget", headers1)
            self.assertNotIn("ReferenceComparison", headers1)
            self.assertNotIn("target-", pass1.read_text(encoding="utf-8-sig"))
            self.assertIn("OfficialTarget", headers2)
            self.assertTrue(rows2[0]["OfficialTarget"].startswith("target-"))

    def test_valid_status_authority_and_protected_tokens_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _pass1, pass2, manifest = self._package(root)
            columns, rows = self._read(pass2)
            row = next(item for item in rows if item["ContentUid"] == "synthetic-single-uid")
            row["ReviewerDecision"] = "Approved"
            row["EvidenceSufficient"] = "true"
            row["DraftText"] = "Draft {Player} %s"
            row["FinalDecision"] = "Approved"
            row["FinalText"] = "Final {Player} %s"
            row["ApprovedAuthority"] = "OfficialTarget:SyntheticTarget"
            self._write(pass2, columns, rows)
            result = validate_bark_review(input_path=pass2, manifest_path=manifest, output_dir=root / "validated")
            self.assertEqual(result["status"], "passed")

    def test_invalid_status_authority_and_token_drift_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _pass1, pass2, manifest = self._package(root)
            columns, rows = self._read(pass2)
            row = next(item for item in rows if item["ContentUid"] == "synthetic-single-uid")
            row["ReviewerDecision"] = "Maybe"
            row["FinalDecision"] = "Maybe"
            row["ApprovedAuthority"] = "HistoricalWorkbook"
            row["FinalText"] = "Dropped tokens"
            self._write(pass2, columns, rows)
            result = validate_bark_review(input_path=pass2, manifest_path=manifest, output_dir=root / "validated")
            codes = {item["code"] for item in result["findings"]}
            self.assertTrue({"BRK007", "BRK010", "BRK012"} <= codes)

    def test_missing_evidence_duplicate_and_shared_member_loss_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pass1, _pass2, manifest = self._package(root)
            columns, rows = self._read(pass1)
            shared = next(row for row in rows if row["SpeakerMode"] == "SharedSpeaker")
            shared["SpeakerCount"] = "2"
            shared["EvidenceRule"] = ""
            rows.append(dict(rows[0]))
            self._write(pass1, columns, rows)
            result = validate_bark_review(input_path=pass1, manifest_path=manifest, output_dir=root / "validated")
            codes = {item["code"] for item in result["findings"]}
            self.assertTrue({"BRK001", "BRK002", "BRK005", "BRK009"} <= codes)

    def test_pass1_target_column_leakage_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pass1, _pass2, manifest = self._package(root)
            columns, rows = self._read(pass1)
            columns.append("OfficialTarget")
            for row in rows:
                row["OfficialTarget"] = "leaked"
            self._write(pass1, columns, rows)
            result = validate_bark_review(input_path=pass1, manifest_path=manifest, output_dir=root / "validated")
            self.assertIn("BRK006", {item["code"] for item in result["findings"]})

    def test_lstag_removal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _pass1, pass2, manifest = self._package(root)
            columns, rows = self._read(pass2)
            shared = next(item for item in rows if item["ContentUid"] == "synthetic-shared-uid")
            shared["FinalText"] = "No structural envelope"
            self._write(pass2, columns, rows)
            result = validate_bark_review(input_path=pass2, manifest_path=manifest, output_dir=root / "validated")
            self.assertIn("BRK012", {item["code"] for item in result["findings"]})

    def test_changed_or_unavailable_comparison_authority_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _pass1, pass2, manifest = self._package(root)
            columns, rows = self._read(pass2)
            rows[0]["OfficialTarget"] = "altered"
            rows[0]["ApprovedAuthority"] = "ReferenceLocale:SyntheticReference"
            self._write(pass2, columns, rows)
            result = validate_bark_review(input_path=pass2, manifest_path=manifest, output_dir=root / "validated")
            codes = {item["code"] for item in result["findings"]}
            self.assertTrue({"BRK010", "BRK014"} <= codes)


if __name__ == "__main__":
    unittest.main()
