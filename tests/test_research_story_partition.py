from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from bg3loc.research.model import ResearchEvidence, ResearchMapping
from bg3loc.research.quest import filter_quest_context_candidates, classify_quest_field_role
from bg3loc.research.context import ContextAggregator
from bg3loc.research.bark import classify_bark_mapping
from bg3loc.research.story import (
    StoryOccurrence,
    partition_story_universe,
    resolve_residual_story_holds,
)


class TestResearchStoryPartition(unittest.TestCase):
    def test_quest_context_candidate_filtering(self):
        # 4 mappings: Title, Description, other field, and non-target UID
        target_uids = {'uid_q1', 'uid_q2'}
        raw_mappings = [
            ResearchMapping(
                contentUid='uid_q1',
                mappingType='quest-journal',
                classification='QuestTitle',
                evidence=[],
            ),
            ResearchMapping(
                contentUid='uid_q1',
                mappingType='quest-journal',
                classification='QuestDescription',
                evidence=[],
            ),
            ResearchMapping(
                contentUid='uid_q2',
                mappingType='quest-journal',
                classification='QuestDescription',
                evidence=[],
            ),
            ResearchMapping(
                contentUid='uid_q3',
                mappingType='quest-journal',
                classification='QuestDescription',
                evidence=[],
            ),
            ResearchMapping(
                contentUid='uid_q1',
                mappingType='quest-journal',
                classification='QuestField',
                evidence=[],
            ),
            ResearchMapping(
                contentUid='uid_q2',
                mappingType='quest-journal',
                classification='QuestDescription',
                evidence=[],
            ),
        ]

        candidates = filter_quest_context_candidates(
            raw_mappings,
            uncovered_target_uids=target_uids,
        )
        self.assertEqual(len(candidates), 3)
        unique_uids = set(c.contentUid for c in candidates)
        self.assertEqual(unique_uids, {'uid_q1', 'uid_q2'})
        titles = [c for c in candidates if c.classification == 'QuestTitle']
        descs = [c for c in candidates if c.classification == 'QuestDescription']
        self.assertEqual(len(titles), 1)
        self.assertEqual(len(descs), 2)

    def test_dialog_bark_context_and_context_aggregator(self):
        agg = ContextAggregator()

        m_shared = ResearchMapping(
            contentUid='uid_shared',
            mappingType='shared-context',
            classification='SharedContextHit',
            evidence=[ResearchEvidence(sourceRole='Shared', resourcePath='p', evidenceType='SharedContextHit', ruleId='R')],
        )
        m_passive = ResearchMapping(
            contentUid='uid_passive',
            mappingType='passive-context',
            classification='StructuredVerified',
            evidence=[ResearchEvidence(sourceRole='Passive', resourcePath='p', evidenceType='PassiveContext', ruleId='R')],
        )
        m_quest = ResearchMapping(
            contentUid='uid_quest',
            mappingType='quest-journal',
            classification='QuestDescription',
            evidence=[ResearchEvidence(sourceRole='Quest', resourcePath='p', evidenceType='QuestJournal', ruleId='R')],
        )
        m_dialog = ResearchMapping(
            contentUid='uid_dialog',
            mappingType='dialog-context',
            classification='DialogContextNode',
            evidence=[ResearchEvidence(sourceRole='Dialog', resourcePath='p', evidenceType='DialogGraph', ruleId='R')],
        )

        agg.add_mappings([m_shared, m_passive, m_quest, m_dialog])
        summary = agg.summary()

        self.assertEqual(summary['totalWithContext'], 4)
        self.assertEqual(summary['unionCount'], 4)
        self.assertEqual(summary['withSharedContext'], 1)
        self.assertEqual(summary['withPassiveContext'], 1)
        self.assertEqual(summary['withQuestEvidence'], 1)
        self.assertEqual(summary['withDialogEvidence'], 1)
        self.assertTrue(summary['isDisjoint'])

    def test_story_universe_partitioning_and_dynamic_hold_resolution(self):
        occurrences = [
            StoryOccurrence(contentUid='uid_auth', sourcePak='Gustav.pak', internalPath='story/dialog.lsf', resourceType='LSF'),
            StoryOccurrence(contentUid='uid_cross', sourcePak='Gustav.pak', internalPath='story/dialog.lsf', resourceType='LSF'),
            StoryOccurrence(contentUid='uid_ctx_telemetry', sourcePak='Gustav.pak', internalPath='story/dialog.lsf', resourceType='LSF'),
            StoryOccurrence(contentUid='uid_ctx_empty', sourcePak='Gustav.pak', internalPath='story/dialog.lsf', resourceType='LSF'),
            StoryOccurrence(contentUid='uid_ctx_retained', sourcePak='Gustav.pak', internalPath='story/dialog.lsf', resourceType='LSF'),
            StoryOccurrence(contentUid='uid_oldtext', sourcePak='Gustav.pak', internalPath='story/dialog.lsf', resourceType='LSF'),
            StoryOccurrence(contentUid='uid_true_missing', sourcePak='Gustav.pak', internalPath='story/dialog.lsf', resourceType='LSF'),
            StoryOccurrence(contentUid='uid_unconfirmed', sourcePak='Gustav.pak', internalPath='story/other.lsf', resourceType='LSF', storyDomain='ContextSupportOnly'),
            StoryOccurrence(contentUid='uid_new', sourcePak='Gustav.pak', internalPath='story/mainstory.lsf', resourceType='LSF', storyDomain='MainStory'),
        ]

        english_records = {
            'uid_auth': 'Authority English',
            'uid_cross': 'Cross Domain English',
            'uid_ctx_telemetry': 'Telemetry English',
            'uid_ctx_empty': '%%% EMPTY',
            'uid_ctx_retained': 'Retained Hold English',
            'uid_unconfirmed': 'Unconfirmed English',
            'uid_new': 'New Translation English',
        }

        existing_383 = {'uid_auth'}
        cross_domain_uids = {'uid_cross'}
        known_holds = {'uid_ctx_telemetry', 'uid_ctx_empty', 'uid_ctx_retained'}

        partition = partition_story_universe(
            occurrences,
            english_records=english_records,
            existing_383_uids=existing_383,
            cross_domain_uids=cross_domain_uids,
            known_context_holds=known_holds,
        )

        self.assertEqual(len(partition.existing_authority_targets), 1)
        self.assertEqual(len(partition.cross_domain_references), 1)
        self.assertEqual(len(partition.story_context_holds), 3)
        self.assertEqual(len(partition.story_missing_english_holds), 2)
        self.assertEqual(len(partition.story_source_unconfirmed_holds), 1)
        self.assertEqual(len(partition.new_story_translation_targets), 1)

        res, mappings = resolve_residual_story_holds(
            partition,
            english_records=english_records,
            old_text_uids={'uid_oldtext'},
            auxiliary_locales={},
            runtime_telemetry_uids={'uid_ctx_telemetry'},
        )

        self.assertIn('uid_ctx_telemetry', res.requires_external_runtime_evidence)
        self.assertIn('uid_ctx_empty', res.proven_context_support_only)
        self.assertIn('uid_oldtext', res.proven_context_support_only)
        self.assertIn('uid_ctx_retained', res.retained_residual_holds)
        self.assertIn('uid_true_missing', res.retained_residual_holds)
        self.assertIn('uid_unconfirmed', res.cleared_for_translation_supplement)

    def test_lslib_nested_dialog_traversal(self):
        from bg3loc.research.dialog import traverse_dialog_json

        nested_lsj = {
            "save": {
                "header": {"time": 1234, "version": "1.0"},
                "regions": {
                    "dialog": {
                        "UUID": {"type": "FixedString", "value": "d966ac28-f310-cac2-1545-457e8ea521ee"},
                        "nodes": [
                            {
                                "node": [
                                    {
                                        "UUID": {"type": "FixedString", "value": "node-01"},
                                        "constructor": {"type": "FixedString", "value": "TagCinematic"},
                                        "speaker": {"type": "int32", "value": 0},
                                        "TaggedTexts": [
                                            {
                                                "TaggedText": [
                                                    {
                                                        "TagTexts": [
                                                            {
                                                                "TagText": [
                                                                    {
                                                                        "TagText": {
                                                                            "type": "TranslatedString",
                                                                            "handle": "h0cd508f3g6a3cg46b0g9f61g451c550cc354",
                                                                            "version": 5,
                                                                        }
                                                                    }
                                                                ]
                                                            }
                                                        ]
                                                    }
                                                ]
                                            }
                                        ],
                                    }
                                ]
                            }
                        ],
                    }
                },
            }
        }

        mappings = list(traverse_dialog_json(nested_lsj, resource_path="Story/Dialogs/test.lsf", pak_name="Gustav.pak"))
        self.assertEqual(len(mappings), 1)
        m = mappings[0]
        self.assertEqual(m.contentUid, "h0cd508f3g6a3cg46b0g9f61g451c550cc354")
        self.assertEqual(m.version, "5")
        self.assertEqual(m.metadata["dialogUuid"], "d966ac28-f310-cac2-1545-457e8ea521ee")
        self.assertEqual(m.metadata["nodeUuid"], "node-01")
        self.assertEqual(m.metadata["speakerSlot"], "0")


if __name__ == '__main__':
    unittest.main()

