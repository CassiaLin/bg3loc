from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

from bg3loc.cli import main
from bg3loc.research.batching import BatchInputRecord, build_batch_plan
from bg3loc.research.classification_resolution import resolve_unclassified


class TestUnclassifiedResolution(unittest.TestCase):
    def _fixture(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        classification = root / "functional-classification.jsonl"
        rows = [
            {"contentUid":"uid-known","primaryCategory":"ui","tags":[],"classificationStatus":"classified","classificationConfidence":"high","classificationEvidence":[]},
            {"contentUid":"uid-assign","primaryCategory":"other","tags":[],"classificationStatus":"unclassified","classificationConfidence":"low","classificationEvidence":[]},
            {"contentUid":"uid-exclude","primaryCategory":"other","tags":[],"classificationStatus":"unclassified","classificationConfidence":"low","classificationEvidence":[]},
            {"contentUid":"uid-pending","primaryCategory":"other","tags":[],"classificationStatus":"unclassified","classificationConfidence":"low","classificationEvidence":[]},
        ]
        classification.write_text("".join(json.dumps(row)+"\n" for row in rows), encoding="utf-8")
        return temp, root, classification

    def test_assign_exclude_and_pending_are_separate(self) -> None:
        temp, root, classification = self._fixture()
        self.addCleanup(temp.cleanup)
        decisions = root / "decisions.jsonl"
        rows = [
            {"ContentUid":"uid-assign","action":"assign","category":"item","reviewer":"r1","note":"manual structural review","decidedAt":"2026-09-27T01:00:00Z"},
            {"ContentUid":"uid-exclude","action":"exclude","reviewer":"r1","note":"not translation content","decidedAt":"2026-09-27T01:01:00Z"},
            {"ContentUid":"uid-pending","action":"pending","note":"needs more evidence"},
        ]
        decisions.write_text("".join(json.dumps(row)+"\n" for row in rows), encoding="utf-8")
        output = root / "resolved.jsonl"
        summary = resolve_unclassified(classification_path=classification, decisions_path=decisions, output_path=output)
        self.assertEqual(summary.total_unresolved_input, 3)
        self.assertEqual(summary.assigned, 1)
        self.assertEqual(summary.excluded, 1)
        self.assertEqual(summary.pending, 1)
        self.assertEqual(summary.unresolved_without_decision, 0)
        resolved = {row["contentUid"]: row for row in (json.loads(line) for line in output.read_text(encoding="utf-8").splitlines())}
        self.assertEqual(resolved["uid-assign"]["classificationStatus"], "classified")
        self.assertEqual(resolved["uid-assign"]["primaryCategory"], "item")
        self.assertEqual(resolved["uid-exclude"]["classificationStatus"], "excluded")
        self.assertEqual(resolved["uid-pending"]["classificationStatus"], "unclassified")
        self.assertNotIn("resolution", resolved["uid-known"])

    def test_batch_plan_separates_excluded_from_unresolved(self) -> None:
        plan = build_batch_plan([
            BatchInputRecord("uid-known", "Known", "ui", "classified"),
            BatchInputRecord("uid-assign", "Assigned", "item", "classified"),
            BatchInputRecord("uid-exclude", "Excluded", "other", "excluded"),
            BatchInputRecord("uid-pending", "Pending", "other", "unclassified"),
        ])
        self.assertEqual(plan.excluded_uids, ("uid-exclude",))
        self.assertEqual(plan.unresolved_uids, ("uid-pending",))
        self.assertEqual(set(plan.batched_uids), {"uid-known", "uid-assign"})

    def test_cannot_override_already_classified_uid(self) -> None:
        temp, root, classification = self._fixture()
        self.addCleanup(temp.cleanup)
        decisions = root / "decisions.jsonl"
        decisions.write_text(json.dumps({"ContentUid":"uid-known","action":"assign","category":"item","reviewer":"r1","decidedAt":"2026-09-27T01:00:00Z"})+"\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "not unresolved"):
            resolve_unclassified(classification_path=classification, decisions_path=decisions, output_path=root/"out.jsonl")

    def test_invalid_category_duplicate_and_foreign_fail_closed(self) -> None:
        temp, root, classification = self._fixture()
        self.addCleanup(temp.cleanup)

        invalid = root / "invalid.jsonl"
        invalid.write_text(json.dumps({"ContentUid":"uid-assign","action":"assign","category":"other","reviewer":"r1","decidedAt":"2026-09-27T01:00:00Z"})+"\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "invalid assigned category"):
            resolve_unclassified(classification_path=classification, decisions_path=invalid, output_path=root/"invalid-out.jsonl")

        duplicate = root / "duplicate.jsonl"
        row={"ContentUid":"uid-assign","action":"pending"}
        duplicate.write_text(json.dumps(row)+"\n"+json.dumps(row)+"\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "duplicate ContentUid"):
            resolve_unclassified(classification_path=classification, decisions_path=duplicate, output_path=root/"duplicate-out.jsonl")

        foreign = root / "foreign.jsonl"
        foreign.write_text(json.dumps({"ContentUid":"uid-foreign","action":"pending"})+"\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "not found in classification ledger"):
            resolve_unclassified(classification_path=classification, decisions_path=foreign, output_path=root/"foreign-out.jsonl")

    def test_cli_resolve_unclassified(self) -> None:
        temp, root, classification = self._fixture()
        self.addCleanup(temp.cleanup)
        decisions = root / "decisions.jsonl"
        decisions.write_text(json.dumps({"ContentUid":"uid-assign","action":"assign","category":"item","reviewer":"cli","note":"checked","decidedAt":"2026-09-27T01:00:00Z"})+"\n", encoding="utf-8")
        output = root / "resolved.jsonl"
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = main(["research","resolve-unclassified","--classification",str(classification),"--decisions",str(decisions),"--output",str(output)])
        self.assertEqual(rc, 0)
        text = stdout.getvalue()
        self.assertIn("Unclassified resolution PASS", text)
        self.assertIn("Assigned: 1", text)
        self.assertIn("No decision yet: 2", text)
        self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()