from __future__ import annotations

import unittest
from pathlib import Path
import tempfile
from unittest import mock

from bg3loc.research.conflict import derive_reuse_conflict_groups, ConflictGroup
from bg3loc.research.context import (
    ContextAggregator,
    extract_passive_context_hits,
    extract_shared_context_hits,
    RULE_SHARED_CONTEXT,
    RULE_PASSIVE_CONTEXT,
)
from bg3loc.research.scanner import scan_game_research_resources
from bg3loc.research.story import (
    StoryOccurrence,
    partition_story_universe,
    resolve_residual_story_holds,
)
from bg3loc.research.model import ResearchMapping, ResearchEvidence
from bg3loc.backends import ArchiveBackend, ArchiveEntry


class TestResearchContext(unittest.TestCase):
    def test_reuse_conflict_grouping_and_conflict001(self):
        # Synthetic test: English source vs Target with conflicts
        source = {
            "h1": "Attack",
            "h2": "Attack",
            "h3": "Attack",
            "h4": "Defend",
            "h5": "Defend",
            "h6": "Potion",
            "h7": "UniqueSourceOnly",
        }
        target = {
            "h1": "攻擊A",
            "h2": "攻擊B",  # Conflicting translations for 'Attack'
            "h4": "防禦A",
            "h5": "防禦B",  # Conflicting translations for 'Defend'
            "h6": "藥水",   # Single shared translation
        }
        # h3 is source-only for 'Attack' -> should be in conflict group for 'Attack'
        # h7 is source-only for 'UniqueSourceOnly' -> no candidate
        res = derive_reuse_conflict_groups(source, target)
        self.assertEqual(res.source_only_count, 2) # h3, h7
        self.assertEqual(res.shared_count, 5)
        self.assertEqual(res.conflict_items_count, 1) # h3
        self.assertIsNotNone(res.conflict_001)
        assert res.conflict_001 is not None
        self.assertEqual(res.conflict_001.group_id, "CONFLICT-001")
        self.assertEqual(res.conflict_001.source_text, "Attack")
        self.assertEqual(res.conflict_001.member_uids, ["h3"])
        self.assertEqual(res.conflict_001.distinct_target_translations, ["攻擊A", "攻擊B"])

    def test_shared_context_filtering_and_dedup(self):
        target_uids = {"h10000001g1111g2222g3333g444444444444"}
        text = """
        Line 1: data "DisplayName" "h10000001g1111g2222g3333g444444444444;1"
        Line 2: data "DisplayName" "h10000001g1111g2222g3333g444444444444;1"
        Line 3: data "Description" "h99999999g9999g9999g9999g999999999999;1"
        """
        hits = list(extract_shared_context_hits(
            text,
            resource_path="Public/Shared/Stats/Passive.txt",
            pak_name="Shared.pak",
            target_uids=target_uids
        ))
        # Line 1 and Line 2 are at different lines -> distinct MatchLocation
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0].contentUid, "h10000001g1111g2222g3333g444444444444")
        self.assertEqual(hits[0].evidence[0].ruleId, RULE_SHARED_CONTEXT)

        # Same line again -> deduplicated
        hits_dup = list(extract_shared_context_hits(
            'data "DisplayName" "h10000001g1111g2222g3333g444444444444;1"',
            resource_path="Public/Shared/Stats/Passive.txt",
            pak_name="Shared.pak",
            target_uids=target_uids
        ))
        self.assertEqual(len(hits_dup), 1)

    def test_passive_context_structured_verification_and_membership(self):
        target_uids = {"h20000002g2222g3333g4444g555555555555"}
        text = """
        new entry "Passive_Hero"
        type "PassiveData"
        data "DisplayName" "h20000002g2222g3333g4444g555555555555;1"
        data "Description" "h30000003g3333g4444g5555g666666666666;1"

        new entry "Spell_Fire"
        type "SpellData"
        data "DisplayName" "h20000002g2222g3333g4444g555555555555;1"
        """
        hits = list(extract_passive_context_hits(
            text,
            resource_path="Public/Gustav/Stats/Generated/Data/Passive.txt",
            pak_name="Gustav.pak",
            target_uids=target_uids
        ))
        # Only the PassiveData entry matches, SpellData is ignored
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].contentUid, "h20000002g2222g3333g4444g555555555555")
        self.assertEqual(hits[0].classification, "StructuredVerified")
        self.assertEqual(hits[0].evidence[0].ruleId, RULE_PASSIVE_CONTEXT)
        self.assertEqual(hits[0].evidence[0].properties["entryName"], "Passive_Hero")

    def test_context_aggregator_overlaps_and_union(self):
        agg = ContextAggregator()
        # Add Shared hit
        agg.add_mapping(ResearchMapping(
            contentUid="u1",
            mappingType="shared-context",
            classification="SharedContext",
            evidence=[ResearchEvidence(sourceRole="SharedContextResource", resourcePath="p", evidenceType="SharedContextHit", ruleId=RULE_SHARED_CONTEXT)]
        ))
        # Add Passive hit
        agg.add_mapping(ResearchMapping(
            contentUid="u2",
            mappingType="passive-context",
            classification="PassiveContext",
            evidence=[ResearchEvidence(sourceRole="PassiveResource", resourcePath="p", evidenceType="PassiveContext", ruleId=RULE_PASSIVE_CONTEXT)]
        ))
        # Add Dialog hit
        agg.add_mapping(ResearchMapping(
            contentUid="u3",
            mappingType="dialog-context",
            classification="DialogContext",
            evidence=[ResearchEvidence(sourceRole="DialogResource", resourcePath="p", evidenceType="DialogNodeGraph", ruleId="BG3-DIALOG-NODE-CONTEXT")]
        ))
        # Add Quest hit
        agg.add_mapping(ResearchMapping(
            contentUid="u4",
            mappingType="quest-journal",
            classification="QuestJournal",
            evidence=[ResearchEvidence(sourceRole="QuestJournalResource", resourcePath="p", evidenceType="QuestJournal", ruleId="BG3-QUEST-JOURNAL-EVIDENCE")]
        ))

        summary = agg.summary()
        self.assertEqual(summary["totalWithContext"], 4)
        self.assertEqual(summary["unionCount"], 4)
        self.assertTrue(summary["isDisjoint"])
        self.assertEqual(summary["pairwiseOverlaps"]["shared_passive"], 0)

    def test_story_universe_partition_and_residual_resolution(self):
        english_loca = {
            "u_confirmed": "Confirmed text",
            "u_unconfirmed": "Unconfirmed text",
            "u_new": "New story text",
        }
        occurrences = [
            StoryOccurrence(contentUid="u_missing_en", sourcePak="Gustav.pak", internalPath="story/dialog", resourceType="LSF"),
            StoryOccurrence(contentUid="u_old_text", sourcePak="Gustav.pak", internalPath="story/dialog", resourceType="LSF", isOldText=True),
            StoryOccurrence(contentUid="u_unconfirmed", sourcePak="Gustav.pak", internalPath="story/support", resourceType="LSF", storyDomain="ContextSupportOnly"),
            StoryOccurrence(contentUid="u_new", sourcePak="Gustav.pak", internalPath="story/dialog", resourceType="LSF", storyDomain="MainStory", hasSpeaker=True),
            StoryOccurrence(contentUid="u_ctx_hold", sourcePak="Gustav.pak", internalPath="story/dialog", resourceType="LSF"),
        ]

        partition = partition_story_universe(
            occurrences,
            english_records=english_loca,
            known_context_holds={"u_ctx_hold"}
        )

        self.assertIn("u_new", partition.new_story_translation_targets)
        self.assertIn("u_ctx_hold", partition.story_context_holds)
        self.assertIn("u_missing_en", partition.story_missing_english_holds)
        self.assertIn("u_old_text", partition.story_missing_english_holds)
        self.assertIn("u_unconfirmed", partition.story_source_unconfirmed_holds)
        self.assertEqual(partition.total_holds, 4)

        # Deep resolution
        res, mappings = resolve_residual_story_holds(
            partition,
            english_records=english_loca,
            old_text_uids={"u_old_text"},
        )
        self.assertIn("u_unconfirmed", res.cleared_for_translation_supplement)
        self.assertIn("u_old_text", res.proven_context_support_only)
        self.assertIn("u_missing_en", res.retained_residual_holds)

    def test_generic_locale_does_not_require_english_pak(self):
        with tempfile.TemporaryDirectory() as td:
            game_dir = Path(td)
            (game_dir / "Data").mkdir(parents=True)
            # Create French and German paks
            (game_dir / "Data" / "French.pak").touch()
            (game_dir / "Data" / "German.pak").touch()
            (game_dir / "Data" / "Shared.pak").touch()
            (game_dir / "Data" / "Gustav.pak").touch()
            (game_dir / "Data" / "GustavX.pak").touch()

            mock_backend = mock.MagicMock(spec=ArchiveBackend)
            mock_backend.list_archive.return_value = [
                ArchiveEntry(path="Localization/French/french.loca", size=10, crc=0),
                ArchiveEntry(path="Localization/German/german.loca", size=10, crc=0),
            ]

            # Scan with French -> German
            resources = scan_game_research_resources(
                game_dir,
                source_locale="French",
                target_locale="German",
                reference_locales=[],
                backend=mock_backend
            )
            self.assertTrue(len(resources) > 0)
            # English.pak was not present and no RuntimeError was raised!


if __name__ == "__main__":
    unittest.main()
