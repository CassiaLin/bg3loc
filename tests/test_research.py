from __future__ import annotations

import json
from pathlib import Path
import unittest

from bg3loc.research.bark import (
    CANONICAL_BARK_CONTAINERS,
    GENERIC_ORIGIN_CONTAINER,
    classify_bark_mapping,
    parse_bark_container,
)
from bg3loc.research.context import ContextAggregator
from bg3loc.research.dialog import traverse_dialog_json
from bg3loc.research.model import (
    HANDLE_PATTERN,
    ResearchEvidence,
    ResearchMapping,
    ResearchRunManifest,
    ResearchScanResource,
)
from bg3loc.research.multilingual import align_multilingual_references
from bg3loc.research.output import (
    write_mappings_jsonl,
    write_research_summary,
    write_scan_manifest,
)
from bg3loc.research.overlay import (
    OverlayCandidate,
    resolve_overlay_precedence,
)
from bg3loc.research.quest import classify_quest_field_role, parse_quest_xml
from bg3loc.research.stats import parse_stats_text
from bg3loc.research.story import evaluate_residual_story_candidates
from bg3loc.research.ui_skill import classify_domain_by_path, parse_ui_skill_xml


class TestResearchModels(unittest.TestCase):
    def test_handle_pattern(self) -> None:
        text = 'data "DisplayName" "h12345678g1234g1234g1234g123456789abc;2"'
        m = HANDLE_PATTERN.search(text)
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.group("uid"), "h12345678g1234g1234g1234g123456789abc")
        self.assertEqual(m.group("ver"), "2")

    def test_mapping_serialization(self) -> None:
        ev = ResearchEvidence(
            sourceRole="StatsRecordField",
            resourcePath="Public/Shared/Stats/Generated/Data/Spells.txt",
            evidenceType="StatsDefinition",
            ruleId="BG3-STAT-DIRECT-LOCALIZATION-REFERENCE",
            properties={"entryName": "Target_Fireball", "line": 42},
        )
        mapping = ResearchMapping(
            contentUid="h12345678g1234g1234g1234g123456789abc",
            mappingType="stat-reference",
            classification="StatLocalizationReference",
            evidence=[ev],
            version="1",
        )
        d = mapping.to_dict()
        self.assertEqual(d["contentUid"], "h12345678g1234g1234g1234g123456789abc")
        self.assertEqual(len(d["evidence"]), 1)
        self.assertEqual(d["evidence"][0]["ruleId"], "BG3-STAT-DIRECT-LOCALIZATION-REFERENCE")


class TestStatsParsing(unittest.TestCase):
    def test_parse_stats_synthetic(self) -> None:
        stats_text = """
// Synthetic Stats Fixture
new entry "Target_SyntheticSpell"
type "SpellData"
data "SpellType" "Target"
data "DisplayName" "h11111111g2222g3333g4444g555555555555;1"
data "Description" "h66666666g7777g8888g9999g000000000000;2"
using "Target_BaseSpell"

new entry "Target_BaseSpell"
type "SpellData"
data "ExtraDescription" "haaaaaaaagbbbbgccccgddddgeeeeeeeeeeee;1"
"""
        mappings = list(parse_stats_text(stats_text, resource_path="Public/Shared/Stats/Data/Spell.txt", provider="Shared"))
        self.assertEqual(len(mappings), 3)
        uids = [m.contentUid for m in mappings]
        self.assertIn("h11111111g2222g3333g4444g555555555555", uids)
        self.assertIn("h66666666g7777g8888g9999g000000000000", uids)
        self.assertIn("haaaaaaaagbbbbgccccgddddgeeeeeeeeeeee", uids)


class TestOverlayPrecedence(unittest.TestCase):
    def test_overlay_resolution(self) -> None:
        candidates = [
            OverlayCandidate(internalPath="Public/Shared/Stats/Data/Spells.txt", pakName="Shared.pak", layerPriority=1),
            OverlayCandidate(internalPath="Public/Shared/Stats/Data/Spells.txt", pakName="Gustav.pak", layerPriority=3),
            OverlayCandidate(internalPath="Public/Shared/Stats/Data/Spells.txt", pakName="Patch8_HotFix9.pak", layerPriority=7),
            OverlayCandidate(internalPath="Public/Gustav/Unique.txt", pakName="Gustav.pak", layerPriority=3),
        ]
        resolutions = resolve_overlay_precedence(candidates)
        self.assertEqual(len(resolutions), 2)
        self.assertEqual(resolutions["Public/Shared/Stats/Data/Spells.txt"].winningPak, "Patch8_HotFix9.pak")
        self.assertEqual(resolutions["Public/Gustav/Unique.txt"].winningPak, "Gustav.pak")


class TestDialogAndBark(unittest.TestCase):
    def test_dialog_traversal(self) -> None:
        dialog_json = {
            "save": {
                "header": {"uuid": "11111111-2222-3333-4444-555555555555"},
                "nodes": [
                    {
                        "UUID": "node-uuid-001",
                        "speaker": "0",
                        "TaggedTexts": [
                            {"handle": "h12345678g1234g1234g1234g123456789abc", "version": "1"}
                        ]
                    }
                ]
            }
        }
        mappings = list(traverse_dialog_json(dialog_json, resource_path="Story/Dialogs/test.lsj", pak_name="Gustav.pak"))
        self.assertEqual(len(mappings), 1)
        self.assertEqual(mappings[0].contentUid, "h12345678g1234g1234g1234g123456789abc")
        self.assertEqual(mappings[0].metadata["dialogUuid"], "11111111-2222-3333-4444-555555555555")

    def test_bark_classification(self) -> None:
        # Single speaker bark
        dialog_astarion = {
            "save": {
                "header": {"uuid": "cabbd368-456a-f39b-453d-b42007b421cf"},
                "nodes": [{"UUID": "n1", "speaker": "0", "TaggedTexts": [{"handle": "h11111111g1111g1111g1111g111111111111"}]}]
            }
        }
        mappings_astarion = list(parse_bark_container(dialog_astarion, internal_path=CANONICAL_BARK_CONTAINERS[0]))
        self.assertEqual(len(mappings_astarion), 1)
        self.assertEqual(mappings_astarion[0].classification, "SingleSpeaker")

        # Shared speaker bark in GenericOrigin
        dialog_generic = {
            "save": {
                "header": {"uuid": "5b162086-f596-38f3-05de-4a156411048a"},
                "nodes": [{"UUID": "n2", "speaker": "SharedSpeaker", "TaggedTexts": [{"handle": "h22222222g2222g2222g2222g222222222222"}]}],
                "speakerlist": [{"speaker": [{"list": {"value": "member-a;member-b;member-c"}}]}],
            }
        }
        mappings_generic = list(parse_bark_container(dialog_generic, internal_path=GENERIC_ORIGIN_CONTAINER))
        self.assertEqual(len(mappings_generic), 1)
        self.assertEqual(mappings_generic[0].classification, "SharedSpeaker")
        self.assertRegex(mappings_generic[0].metadata.get("sharedGroupId", ""), r"^BARK-GROUP-[0-9A-F]{12}$")
        self.assertEqual(
            [item["identity"] for item in mappings_generic[0].metadata["speakerMembers"]],
            ["member-a", "member-b", "member-c"],
        )


class TestQuestParsing(unittest.TestCase):
    def test_quest_xml_parsing(self) -> None:
        xml_text = """<save>
  <region id="Quests">
    <node id="Quest">
      <attribute id="Title" type="TranslatedString" handle="h33333333g3333g3333g3333g333333333333" version="1" />
      <children>
        <node id="Stage">
          <attribute id="Description" type="TranslatedString" handle="h44444444g4444g4444g4444g444444444444" version="2" />
        </node>
      </children>
    </node>
  </region>
</save>"""
        mappings = list(parse_quest_xml(xml_text, resource_path="Story/Journal/Quests.lsx"))
        self.assertEqual(len(mappings), 2)
        classes = {m.contentUid: m.classification for m in mappings}
        self.assertEqual(classes["h33333333g3333g3333g3333g333333333333"], "QuestTitle")
        self.assertEqual(classes["h44444444g4444g4444g4444g444444444444"], "QuestDescription")


class TestContextAggregator(unittest.TestCase):
    def test_aggregation(self) -> None:
        agg = ContextAggregator()

        ev1 = ResearchEvidence(
            sourceRole="DialogNode",
            resourcePath="dialog.lsj",
            evidenceType="DialogGraph",
            ruleId="BG3-DIALOG-NODE-CONTEXT",
        )
        agg.add_mapping(ResearchMapping(contentUid="h11111111g1111g1111g1111g111111111111", mappingType="dialog", classification="Dialog", evidence=[ev1]))

        ev2 = ResearchEvidence(
            sourceRole="QuestField",
            resourcePath="quest.lsx",
            evidenceType="QuestJournal",
            ruleId="BG3-QUEST-JOURNAL-EVIDENCE",
        )
        agg.add_mapping(ResearchMapping(contentUid="h22222222g2222g2222g2222g222222222222", mappingType="quest", classification="QuestDescription", evidence=[ev2]))

        # Add second evidence to h11111111
        agg.add_mapping(ResearchMapping(contentUid="h11111111g1111g1111g1111g111111111111", mappingType="quest", classification="QuestTitle", evidence=[ev2]))

        self.assertEqual(agg.count(), 2)
        m1 = agg.get_by_uid("h11111111g1111g1111g1111g111111111111")
        assert m1 is not None
        self.assertEqual(len(m1.evidence), 2)
        self.assertTrue(m1.metadata.get("hasDialogGraph"))
        self.assertTrue(m1.metadata.get("hasQuestJournal"))


class TestMultilingualAndStory(unittest.TestCase):
    def test_multilingual_alignment(self) -> None:
        en = {
            "h1": "Exact Match Text",
            "h2": "Target Boundary Text",
            "h3": "Shared Text",
        }
        zht = {
            "h1": "完全相符文字",
            "h3": "共用文字",
        }
        zhs = {
            "h2": "目标边界文本",
        }
        ru = {
            "h2": "Текст границы цели",
        }

        mappings = list(align_multilingual_references(
            source_records=en,
            target_records=zht,
            reference_records_by_locale={"Chinese": zhs, "Russian": ru},
            target_boundary_uids=["h2"]
        ))
        self.assertEqual(len(mappings), 1)
        m = mappings[0]
        self.assertEqual(m.contentUid, "h2")
        self.assertTrue(m.metadata.get("hasSameUidChinese"))
        self.assertTrue(m.metadata.get("hasSameUidRussian"))

    def test_story_residual_evaluation(self) -> None:
        candidates = ["h_cleared", "h_retained"]
        en = {"h_cleared": "Cleared", "h_retained": "Retained"}
        aux = {"Russian": {"h_cleared": "Переведено"}}

        mappings = list(evaluate_residual_story_candidates(candidates, english_records=en, auxiliary_locales=aux, story_graph_referenced_uids=["h_cleared"]))
        self.assertEqual(len(mappings), 2)
        by_uid = {m.contentUid: m.classification for m in mappings}
        self.assertEqual(by_uid["h_cleared"], "ClearedForTranslationSupplement")
        self.assertEqual(by_uid["h_retained"], "RetainedResidualHold")


class TestUiSkillDomainClassification(unittest.TestCase):
    def test_domain_inference(self) -> None:
        self.assertEqual(classify_domain_by_path("Public/Shared/Stats/Generated/Data/Spells.txt"), "AbilityOrSkill")
        self.assertEqual(classify_domain_by_path("Public/Shared/Stats/Generated/Data/Armor.txt"), "ItemsAndEquipment")
        self.assertEqual(classify_domain_by_path("GUI/Library/Tooltips.xaml"), "UserInterface")
        self.assertEqual(classify_domain_by_path("Public/Shared/Tutorials/Tutorials.lsx"), "TutorialAndSystem")


if __name__ == "__main__":
    unittest.main()
