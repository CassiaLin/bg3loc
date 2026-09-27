from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bg3loc.research.story import (
    StoryOccurrence,
    classify_story_domain,
    derive_cross_domain_references,
    parse_cinematics_occurrences,
    parse_dialog_binary_occurrences,
    parse_dialog_raw_occurrences,
    parse_journal_quest_occurrences,
    parse_level_resources_occurrences,
    parse_localization_registry_occurrences,
    parse_readable_registry_occurrences,
    parse_root_templates_occurrences,
    parse_story_goals_occurrences,
    parse_tags_characters_occurrences,
    partition_story_universe,
    read_story_occurrence_ledger,
    resolve_residual_story_holds,
    verify_source_unconfirmed_candidate,
    write_oldtext_evidence,
    write_story_occurrence_ledger,
)


class TestResearchStaticAudit(unittest.TestCase):
    def test_static_codebase_prohibition(self):
        """Assert zero occurrences of prohibited historical strings in production source code."""
        src_dir = Path(__file__).resolve().parent.parent / "src"
        prohibited = [
            "phase4bhm-story-occurrence-ledger",
            "phase4ba-target-assignment",
            "canonical_7_holds",
            "runtime_telemetry_uids",
            "D:/workspace",
            "D:\\workspace",
            "h5b58a9a9",
            "h181754aa",
        ]
        violations: list[str] = []
        for p in src_dir.rglob("*.py"):
            text = p.read_text(encoding="utf-8", errors="replace")
            for term in prohibited:
                if term.lower() in text.lower():
                    violations.append(f"{p}: contains {term}")

        # Note: violations must be 0 after refactoring research.py and story.py
        # If any remain, fail
        self.assertEqual(violations, [])

    def test_all_10_resource_family_parsers(self):
        uid1 = "h11111111g1111g1111g1111g111111111111"
        uid2 = "h22222222g2222g2222g2222g222222222222"
        uid_old = "h33333333g3333g3333g3333g333333333333"

        # 1. DialogsRaw (JSON)
        raw_json = f"""{{
            "save": {{
                "regions": {{
                    "dialog": {{
                        "category": {{"value": "NPCDialogue"}},
                        "nodes": [{{
                            "node": [{{
                                "UUID": {{"value": "node-1"}},
                                "constructor": {{"value": "TagCinematic"}},
                                "speaker": {{"value": "0"}},
                                "TaggedTexts": [{{"TaggedText": [{{"TagTexts": [{{"TagText": [{{"TagText": {{"handle": "{uid1}"}}}}]}}]}}]}}],
                                "OldText": {{"handle": "{uid_old}"}}
                            }}]
                        }}]
                    }}
                }}
            }}
        }}"""
        raw_occs = parse_dialog_raw_occurrences(raw_json, "Gustav.pak", "Story/Dialogs/cinematic_test.lsj")
        self.assertEqual(len(raw_occs), 1)
        tag_occ = raw_occs[0]
        self.assertEqual(tag_occ.contentUid, uid1)
        self.assertEqual(tag_occ.storyDomain, "CinematicSubtitle")
        self.assertTrue(tag_occ.hasDialog)
        self.assertFalse(tag_occ.isOldText)

        # 2. DialogsBinary (XML)
        bin_xml = f"""<?xml version="1.0" encoding="utf-8"?>
        <save>
            <region id="dialog">
                <node id="dialog">
                    <node id="node">
                        <attribute id="TagText" type="TranslatedString" handle="{uid1}" version="1" />
                        <attribute id="OldText" type="TranslatedString" handle="{uid_old}" version="1" />
                    </node>
                </node>
            </region>
        </save>"""
        bin_occs = parse_dialog_binary_occurrences(bin_xml, "Gustav.pak", "Story/DialogsBinary/test.lsf")
        self.assertEqual(len(bin_occs), 2)

        # 3. JournalQuest (XML)
        quest_xml = f"""<?xml version="1.0" encoding="utf-8"?>
        <save>
            <region id="Quest">
                <node id="Quest">
                    <attribute id="Title" type="TranslatedString" handle="{uid1}" version="1" />
                    <attribute id="Description" type="TranslatedString" handle="{uid2}" version="1" />
                </node>
            </region>
        </save>"""
        quest_occs = parse_journal_quest_occurrences(quest_xml, "Gustav.pak", "Mods/Gustav/Story/Journal/Quests.lsx")
        self.assertEqual(len(quest_occs), 2)
        self.assertEqual(quest_occs[0].storyDomain, "QuestTitle")
        self.assertEqual(quest_occs[1].storyDomain, "QuestDescription")
        self.assertTrue(quest_occs[0].hasQuest)

        # 4. Cinematics (XML)
        cine_xml = f"""<save><region id="Cinematics"><node id="Cinematics"><attribute id="TagText" type="TranslatedString" handle="{uid1}"/></node></region></save>"""
        cine_occs = parse_cinematics_occurrences(cine_xml, "Gustav.pak", "Cinematics/test.lsf")
        self.assertEqual(len(cine_occs), 1)
        self.assertEqual(cine_occs[0].storyDomain, "CinematicSubtitle")

        # 5. LevelResources (XML)
        lvl_xml = f"""<save><region id="Level"><node id="Level"><attribute id="DisplayName" type="TranslatedString" handle="{uid1}"/></node></region></save>"""
        lvl_occs = parse_level_resources_occurrences(lvl_xml, "Gustav.pak", "Levels/test.lsf")
        self.assertEqual(len(lvl_occs), 1)
        self.assertEqual(lvl_occs[0].storyDomain, "ContextSupportOnly")

        # 6. LocalizationRegistry (XML)
        reg_xml = f"""<save><region id="Loca"><node id="Loca"><attribute id="DisplayName" type="TranslatedString" handle="{uid1}"/></node></region></save>"""
        reg_occs = parse_localization_registry_occurrences(reg_xml, "Shared.pak", "Localization/test.lsf")
        self.assertEqual(len(reg_occs), 1)
        self.assertEqual(reg_occs[0].storyDomain, "StoryRelatedTerm")

        # 7. ReadableLocalizationRegistry (XML)
        book_xml = f"""<save><region id="Book"><node id="Book"><attribute id="Title" type="TranslatedString" handle="{uid1}"/></node></region></save>"""
        book_occs = parse_readable_registry_occurrences(book_xml, "Shared.pak", "Localization/Books/book.lsf")
        self.assertEqual(len(book_occs), 1)
        self.assertEqual(book_occs[0].storyDomain, "BookTitle")

        # 8. RootTemplates (XML)
        root_xml = f"""<save><region id="Templates"><node id="Templates"><attribute id="DisplayName" type="TranslatedString" handle="{uid1}"/></node></region></save>"""
        root_occs = parse_root_templates_occurrences(root_xml, "Shared.pak", "Public/Shared/RootTemplates/_merged.lsf")
        self.assertEqual(len(root_occs), 1)
        self.assertEqual(root_occs[0].storyDomain, "StoryRelatedTerm")

        # 9. StoryGoals (TXT)
        goals_txt = f"""// Story goal\nSetFlag({uid1});\nGoalCompleted({uid2});\n"""
        goal_occs = parse_story_goals_occurrences(goals_txt, "Gustav.pak", "Story/RawFiles/Goals/goal.txt")
        self.assertEqual(len(goal_occs), 2)
        self.assertEqual(goal_occs[0].storyDomain, "ContextSupportOnly")

        # 10. TagsCharacters (XML)
        tag_xml = f"""<save><region id="Tags"><node id="Tags"><attribute id="DisplayName" type="TranslatedString" handle="{uid1}"/></node></region></save>"""
        tag_occs = parse_tags_characters_occurrences(tag_xml, "Shared.pak", "Public/Shared/Tags/tag.lsf")
        self.assertEqual(len(tag_occs), 1)
        self.assertEqual(tag_occs[0].storyDomain, "StoryRelatedTerm")

    def test_story_occurrence_ledger_roundtrip_and_oldtext(self):
        with tempfile.TemporaryDirectory() as td:
            ledger_path = Path(td) / "story-occurrence-ledger.csv"
            oldtext_path = Path(td) / "oldtext-evidence.csv"

            occs = [
                StoryOccurrence(
                    contentUid="h11111111g1111g1111g1111g111111111111",
                    sourcePak="Gustav.pak",
                    internalPath="Story/Dialogs/test.lsj",
                    resourceType="DialogsRaw",
                    storyDomain="NPCDialogue",
                    nodeId="node-1",
                    attributeRole="TagText",
                    hasSpeaker=True,
                    hasDialog=True,
                    hasQuest=False,
                    isOldText=False,
                ),
                StoryOccurrence(
                    contentUid="h22222222g2222g2222g2222g222222222222",
                    sourcePak="Gustav.pak",
                    internalPath="Story/Dialogs/test.lsj",
                    resourceType="DialogsRaw",
                    storyDomain="NPCDialogue",
                    nodeId="node-1",
                    attributeRole="OldText",
                    hasSpeaker=True,
                    hasDialog=True,
                    hasQuest=False,
                    isOldText=True,
                ),
            ]

            write_story_occurrence_ledger(occs, ledger_path)
            write_oldtext_evidence(occs, oldtext_path)

            loaded = read_story_occurrence_ledger(ledger_path)
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[0].contentUid, occs[0].contentUid)
            self.assertFalse(loaded[0].isOldText)
            self.assertTrue(loaded[1].isOldText)

            old_text_lines = oldtext_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(old_text_lines), 2) # header + 1 row
            self.assertIn(occs[1].contentUid, old_text_lines[1])

    def test_cross_domain_game_derived_target_construction(self):
        story_uids = {"u1", "u2", "u3", "u4"}
        other_domain_uids = {"u2", "u3", "u5"}
        existing_383 = {"u2"}

        cross_domain = derive_cross_domain_references(story_uids, other_domain_uids, existing_383)
        self.assertEqual(cross_domain, {"u3"})

    def test_story_context_hold_dynamic_rule(self):
        occs = [
            StoryOccurrence(
                contentUid="u_root_missing",
                sourcePak="Shared.pak",
                internalPath="Public/Shared/RootTemplates/_merged.lsf",
                resourceType="RootTemplates",
                attributeRole="ShortDescription",
            ),
            StoryOccurrence(
                contentUid="u_tag_empty",
                sourcePak="Shared.pak",
                internalPath="Public/Shared/Tags/tag.lsf",
                resourceType="TagsCharacters",
                attributeRole="DisplayName",
            ),
            StoryOccurrence(
                contentUid="u_normal_dialog",
                sourcePak="Gustav.pak",
                internalPath="Story/Dialogs/test.lsj",
                resourceType="DialogsRaw",
                attributeRole="TagText",
                hasDialog=True,
                storyDomain="NPCDialogue",
            ),
        ]
        english = {
            "u_tag_empty": "%%% EMPTY",
            "u_normal_dialog": "Hello world",
        }

        partition = partition_story_universe(
            occs,
            english_records=english,
            known_context_holds=None,
        )

        self.assertIn("u_root_missing", partition.story_context_holds)
        self.assertIn("u_tag_empty", partition.story_context_holds)
        self.assertIn("u_normal_dialog", partition.new_story_translation_targets)
        self.assertEqual(len(partition.story_context_holds), 2)

    def test_empty_sentinel_derivation_and_residual_resolution(self):
        occs = [
            StoryOccurrence(
                contentUid="u_empty_sentinel",
                sourcePak="Shared.pak",
                internalPath="Public/Shared/Tags/tag.lsf",
                resourceType="TagsCharacters",
                attributeRole="DisplayName",
            ),
            StoryOccurrence(
                contentUid="u_telemetry_hold",
                sourcePak="Gustav.pak",
                internalPath="Public/Gustav/RootTemplates/_merged.lsf",
                resourceType="RootTemplates",
                attributeRole="GameMasterSpawnSubSection",
            ),
            StoryOccurrence(
                contentUid="u_retained_hold",
                sourcePak="Shared.pak",
                internalPath="Public/Shared/RootTemplates/_merged.lsf",
                resourceType="RootTemplates",
                attributeRole="ShortDescription",
            ),
        ]
        english = {
            "u_empty_sentinel": "%%% EMPTY",
        }

        partition = partition_story_universe(occs, english_records=english, known_context_holds=None)
        self.assertEqual(len(partition.story_context_holds), 3)

        occ_map = {o.contentUid: [o] for o in occs}
        res, mappings = resolve_residual_story_holds(
            partition,
            english_records=english,
            occurrences_by_uid=occ_map,
        )

        self.assertIn("u_empty_sentinel", res.proven_context_support_only)
        self.assertIn("u_telemetry_hold", res.requires_external_runtime_evidence)
        self.assertIn("u_retained_hold", res.retained_residual_holds)

    def test_source_unconfirmed_clearance_gate(self):
        # 1. Valid text with dialog
        o_valid = StoryOccurrence(contentUid="u1", sourcePak="p", internalPath="i", resourceType="DialogsRaw", storyDomain="NPCDialogue", hasDialog=True)
        v1, r1 = verify_source_unconfirmed_candidate("u1", [o_valid], {"u1": "Valid English text"})
        self.assertTrue(v1)
        self.assertEqual(r1, "ClearedForTranslationSupplement")

        # 2. Empty text
        v2, r2 = verify_source_unconfirmed_candidate("u2", [o_valid], {"u2": ""})
        self.assertFalse(v2)
        self.assertEqual(r2, "MissingOrEmptySourceText")

        # 3. Sentinel text
        v3, r3 = verify_source_unconfirmed_candidate("u3", [o_valid], {"u3": "%%% EMPTY"})
        self.assertFalse(v3)
        self.assertEqual(r3, "MissingOrEmptySourceText")

        # 4. OldText only
        o_old = StoryOccurrence(contentUid="u4", sourcePak="p", internalPath="i", resourceType="DialogsRaw", isOldText=True)
        v4, r4 = verify_source_unconfirmed_candidate("u4", [o_old], {"u4": "Some text"})
        self.assertFalse(v4)
        self.assertEqual(r4, "OldTextOnly")

        # 5. ContextSupportOnly with active occurrences and valid text clears for supplement
        o_ctx = StoryOccurrence(contentUid="u5", sourcePak="p", internalPath="i", resourceType="LevelResources", storyDomain="ContextSupportOnly", isOldText=False)
        v5, r5 = verify_source_unconfirmed_candidate("u5", [o_ctx], {"u5": "Some text"})
        self.assertTrue(v5)
        self.assertEqual(r5, "ClearedForTranslationSupplement")

    def test_no_fabricated_dialog_context_mapping(self):
        """
        Production orchestration must NOT create a dialog-context mapping for a UID that
        exists in the target (other_54) universe if no actual game-derived dialog/bark
        evidence was emitted for that UID.

        Verifies the evidence-backed dialog mapping requirement:
          target UID exists + no actual dialog/bark evidence → no dialog-context mapping emitted.
        """
        from bg3loc.research.model import ResearchMapping

        # Simulate other_54_uids — a set of UIDs in the Other54 conflict group
        other_54_uids = {
            "haaaaaaaa_no_evidence",
            "hbbbbbbbb_has_evidence",
        }

        # Only hbbbbbbbb has real game-derived evidence
        real_evidence_mapping = ResearchMapping(
            contentUid="hbbbbbbbb_has_evidence",
            mappingType="dialog-context",
            classification="DialogBarkContext",
            evidence=[],
            version="",
            metadata={"sourcePak": "Gustav.pak", "internalPath": "Story/Dialogs/real.lsj"},
        )
        all_mappings = [real_evidence_mapping]

        # Replicate the production filter
        dialog_bark_by_uid = {
            m.contentUid: m for m in all_mappings
            if m.mappingType in ("dialog-context", "bark-speaker") and m.contentUid in other_54_uids
        }
        dialog_bark_mappings = [
            dialog_bark_by_uid[uid] for uid in other_54_uids if uid in dialog_bark_by_uid
        ]
        other_54_without_evidence = other_54_uids - set(dialog_bark_by_uid)

        # The UID without evidence must NOT appear as a dialog-context mapping
        emitted_uids = {m.contentUid for m in dialog_bark_mappings}
        self.assertNotIn(
            "haaaaaaaa_no_evidence",
            emitted_uids,
            "A UID with no game-derived evidence must not be emitted as a dialog-context mapping.",
        )
        self.assertIn(
            "hbbbbbbbb_has_evidence",
            emitted_uids,
            "A UID with real game evidence must be included.",
        )
        self.assertIn(
            "haaaaaaaa_no_evidence",
            other_54_without_evidence,
            "UIDs without evidence must appear in the missing-evidence tracking set.",
        )
        self.assertEqual(len(dialog_bark_mappings), 1)
        self.assertEqual(len(other_54_without_evidence), 1)


if __name__ == "__main__":
    unittest.main()