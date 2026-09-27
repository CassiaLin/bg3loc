from __future__ import annotations

import unittest

from bg3loc.research.model import ResearchEvidence, ResearchMapping
from bg3loc.research.quest import filter_quest_context_candidates


class QuestOccurrencePreservationTests(unittest.TestCase):
    def test_candidate_dedup_preserves_all_occurrence_evidence(self) -> None:
        uid = "synthetic-quest-uid"
        first = ResearchMapping(
            contentUid=uid,
            mappingType="quest-journal",
            classification="QuestDescription",
            evidence=[ResearchEvidence(
                sourceRole="QuestJournalField",
                resourcePath="Synthetic/QuestA.lsx",
                evidenceType="QuestJournal",
                ruleId="BG3-QUEST-JOURNAL-EVIDENCE",
                properties={"fieldName": "Description", "fieldRole": "QuestDescription", "pakName": "Synthetic.pak"},
            )],
            reviewRequired=True,
        )
        second = ResearchMapping(
            contentUid=uid,
            mappingType="quest-journal",
            classification="QuestDescription",
            evidence=[ResearchEvidence(
                sourceRole="QuestJournalField",
                resourcePath="Synthetic/QuestB.lsx",
                evidenceType="QuestJournal",
                ruleId="BG3-QUEST-JOURNAL-EVIDENCE",
                properties={"fieldName": "Description", "fieldRole": "QuestDescription", "pakName": "Synthetic.pak"},
            )],
            reviewRequired=True,
        )

        candidates = filter_quest_context_candidates([first, second], uncovered_target_uids={uid})

        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(candidates[0].evidence), 2)
        self.assertEqual(candidates[0].metadata["occurrenceCount"], 2)
        self.assertEqual(
            [item.resourcePath for item in candidates[0].evidence],
            ["Synthetic/QuestA.lsx", "Synthetic/QuestB.lsx"],
        )


if __name__ == "__main__":
    unittest.main()
