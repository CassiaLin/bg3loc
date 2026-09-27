from __future__ import annotations

import unittest

from bg3loc.research.multilingual import align_multilingual_references


class MultilingualReviewTests(unittest.TestCase):
    def test_default_boundary_is_source_only_and_complete(self) -> None:
        source = {
            "shared": "Shared",
            "missing-a": "No match",
            "missing-b": "No match either",
        }
        target = {"shared": "共用"}

        rows = list(
            align_multilingual_references(
                source,
                target_records=target,
            )
        )

        self.assertEqual(["missing-a", "missing-b"], [row.contentUid for row in rows])
        self.assertTrue(all(row.reviewRequired for row in rows))
        self.assertTrue(all(row.classification == "NoExactReuseCandidate" for row in rows))

    def test_exact_reuse_distinguishes_single_consensus_and_conflict(self) -> None:
        source = {
            "shared-single": "Single",
            "shared-consensus-a": "Consensus",
            "shared-consensus-b": "Consensus",
            "shared-conflict-a": "Conflict",
            "shared-conflict-b": "Conflict",
            "target-single": "Single",
            "target-consensus": "Consensus",
            "target-conflict": "Conflict",
        }
        target = {
            "shared-single": "單一",
            "shared-consensus-a": "共識",
            "shared-consensus-b": "共識",
            "shared-conflict-a": "甲",
            "shared-conflict-b": "乙",
        }
        boundary = {"target-single", "target-consensus", "target-conflict"}

        rows = {
            row.contentUid: row
            for row in align_multilingual_references(
                source,
                target_records=target,
                target_boundary_uids=boundary,
            )
        }

        self.assertEqual("ExactReuseSingle", rows["target-single"].classification)
        self.assertEqual("EXACT_SINGLE", rows["target-single"].metadata["referenceType"])
        self.assertEqual(1, rows["target-single"].metadata["sharedOccurrenceCount"])

        self.assertEqual("ExactReuseConsensus", rows["target-consensus"].classification)
        self.assertEqual("EXACT_CONSENSUS", rows["target-consensus"].metadata["referenceType"])
        self.assertEqual(2, rows["target-consensus"].metadata["sharedOccurrenceCount"])
        self.assertEqual(1, rows["target-consensus"].metadata["reusableTargetCount"])

        self.assertEqual("ExactReuseConflict", rows["target-conflict"].classification)
        self.assertEqual("EXACT_CONFLICT", rows["target-conflict"].metadata["referenceType"])
        self.assertEqual(2, rows["target-conflict"].metadata["reusableTargetCount"])

    def test_same_uid_auxiliary_references_are_preserved(self) -> None:
        source = {"missing": "Source"}
        refs = {
            "ChineseSimplified": {"missing": "简体"},
            "Russian": {"missing": "Русский"},
        }

        row = next(
            align_multilingual_references(
                source,
                reference_records_by_locale=refs,
            )
        )

        self.assertTrue(row.metadata["hasSameUidChineseSimplified"])
        self.assertTrue(row.metadata["hasSameUidRussian"])
        self.assertEqual(2, len(row.evidence))


if __name__ == "__main__":
    unittest.main()
