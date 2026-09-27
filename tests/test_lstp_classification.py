from __future__ import annotations

import unittest

from bg3loc.research.classification import (
    classify_functional_ownership,
    summarize_functional_classification,
)
from bg3loc.research.model import ResearchEvidence, ResearchMapping


def uid(n: str) -> str:
    return f"h{n * 8}g{n * 4}g{n * 4}g{n * 4}g{n * 12}"


def mapping(
    content_uid: str,
    mapping_type: str,
    classification: str,
    *,
    evidence_type: str,
    rule_id: str,
    path: str = "",
    properties: dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
) -> ResearchMapping:
    return ResearchMapping(
        contentUid=content_uid,
        mappingType=mapping_type,
        classification=classification,
        evidence=[
            ResearchEvidence(
                sourceRole="Synthetic",
                resourcePath=path,
                evidenceType=evidence_type,
                ruleId=rule_id,
                properties=properties or {},
            )
        ],
        metadata=metadata or {},
    )


class TestFunctionalClassification(unittest.TestCase):
    def test_supported_categories_and_fallback(self) -> None:
        uids = [uid(x) for x in "1234567"]
        mappings = [
            mapping(uids[0], "bark-speaker", "SingleSpeaker", evidence_type="BarkSpeakerStructure", rule_id="BARK"),
            mapping(uids[1], "quest-journal", "QuestTitle", evidence_type="QuestJournal", rule_id="QUEST"),
            mapping(
                uids[2],
                "stat-reference",
                "StatLocalizationReference",
                evidence_type="StatsDefinition",
                rule_id="STAT",
                properties={"entryType": "SpellData"},
            ),
            mapping(
                uids[3],
                "stat-reference",
                "StatLocalizationReference",
                evidence_type="StatsDefinition",
                rule_id="STAT",
                properties={"entryType": "Weapon"},
            ),
            mapping(
                uids[4],
                "ui-skill-candidate",
                "UserInterface",
                evidence_type="UiSkillProvider",
                rule_id="UI",
                properties={"domain": "UserInterface"},
                metadata={"domain": "UserInterface"},
            ),
            mapping(uids[5], "dialog-context", "DialogContextNode", evidence_type="DialogGraph", rule_id="DIALOG"),
        ]

        results = classify_functional_ownership(uids, mappings)
        by_uid = {r.contentUid: r for r in results}

        self.assertEqual(by_uid[uids[0]].primaryCategory, "bark")
        self.assertEqual(by_uid[uids[1]].primaryCategory, "quest")
        self.assertEqual(by_uid[uids[2]].primaryCategory, "skill_spell")
        self.assertEqual(by_uid[uids[3]].primaryCategory, "item")
        self.assertEqual(by_uid[uids[4]].primaryCategory, "ui")
        self.assertEqual(by_uid[uids[5]].primaryCategory, "dialogue_general")
        self.assertEqual(by_uid[uids[6]].primaryCategory, "other")
        self.assertEqual(by_uid[uids[6]].classificationStatus, "unclassified")

    def test_precedence_prevents_duplicate_ownership(self) -> None:
        target = uid("a")
        mappings = [
            mapping(target, "dialog-context", "DialogContextNode", evidence_type="DialogGraph", rule_id="DIALOG"),
            mapping(target, "quest-journal", "QuestDescription", evidence_type="QuestJournal", rule_id="QUEST"),
            mapping(target, "ui-skill-candidate", "UserInterface", evidence_type="UiSkillProvider", rule_id="UI", properties={"domain": "UserInterface"}, metadata={"domain": "UserInterface"}),
        ]

        result = classify_functional_ownership([target], mappings)[0]
        self.assertEqual(result.primaryCategory, "quest")
        self.assertIn("also:ui", result.tags)
        self.assertIn("also:dialogue_general", result.tags)

    def test_bark_precedes_dialog(self) -> None:
        target = uid("b")
        mappings = [
            mapping(target, "dialog-context", "DialogContextNode", evidence_type="DialogGraph", rule_id="DIALOG"),
            mapping(target, "bark-speaker", "SharedSpeaker", evidence_type="BarkSpeakerStructure", rule_id="BARK"),
        ]
        result = classify_functional_ownership([target], mappings)[0]
        self.assertEqual(result.primaryCategory, "bark")

    def test_path_fallback_is_medium_confidence(self) -> None:
        target = uid("c")
        mappings = [
            mapping(
                target,
                "stat-reference",
                "StatLocalizationReference",
                evidence_type="StatsDefinition",
                rule_id="STAT",
                path="Public/Shared/Stats/Generated/Data/Spells.txt",
                properties={"entryType": ""},
            )
        ]
        result = classify_functional_ownership([target], mappings)[0]
        self.assertEqual(result.primaryCategory, "skill_spell")
        self.assertEqual(result.classificationConfidence, "medium")

    def test_high_confidence_beats_medium_precedence_candidate(self) -> None:
        target = uid("f")
        mappings = [
            mapping(
                target,
                "stat-reference",
                "StatLocalizationReference",
                evidence_type="StatsDefinition",
                rule_id="PATH",
                path="Public/Shared/Stats/Generated/Data/Spells.txt",
                properties={"entryType": ""},
            ),
            mapping(
                target,
                "ui-skill-candidate",
                "ItemsAndEquipment",
                evidence_type="UiSkillProvider",
                rule_id="ITEM",
                properties={"domain": "ItemsAndEquipment"},
                metadata={"domain": "ItemsAndEquipment"},
            ),
        ]
        result = classify_functional_ownership([target], mappings)[0]
        self.assertEqual(result.primaryCategory, "item")
        self.assertEqual(result.classificationConfidence, "high")
        self.assertIn("also:skill_spell", result.tags)

    def test_resource_path_matching_uses_exact_stem_and_normalizes_windows_separators(self) -> None:
        false_positive = uid("1")
        windows_path = uid("2")
        mappings = [
            mapping(
                false_positive,
                "stat-reference",
                "StatLocalizationReference",
                evidence_type="StatsDefinition",
                rule_id="STAT",
                path="Public/Shared/Stats/Generated/Data/Objectives.txt",
                properties={"entryType": ""},
            ),
            mapping(
                windows_path,
                "stat-reference",
                "StatLocalizationReference",
                evidence_type="StatsDefinition",
                rule_id="STAT",
                path=r"Public\\Shared\\Stats\\Generated\\Data\\Spells.txt",
                properties={"entryType": ""},
            ),
        ]
        results = {r.contentUid: r for r in classify_functional_ownership([false_positive, windows_path], mappings)}
        self.assertEqual(results[false_positive].primaryCategory, "other")
        self.assertEqual(results[windows_path].primaryCategory, "skill_spell")
        self.assertEqual(results[windows_path].classificationConfidence, "medium")

    def test_classification_evidence_points_to_triggering_evidence(self) -> None:
        target = uid("3")
        first = ResearchEvidence(
            sourceRole="Irrelevant",
            resourcePath="Public/Shared/Unrelated.lsx",
            evidenceType="OtherEvidence",
            ruleId="OTHER",
            properties={},
        )
        second = ResearchEvidence(
            sourceRole="UiProvider",
            resourcePath="GUI/Library/Tooltips.xaml",
            evidenceType="UiSkillProvider",
            ruleId="UI-RULE",
            properties={"domain": "UserInterface"},
        )
        mappings = [
            ResearchMapping(
                contentUid=target,
                mappingType="ui-skill-candidate",
                classification="UserInterface",
                evidence=[first, second],
                metadata={"domain": "UserInterface"},
            )
        ]

        result = classify_functional_ownership([target], mappings)[0]
        ui_evidence = [e for e in result.classificationEvidence if e.category == "ui"]
        self.assertTrue(ui_evidence)
        self.assertTrue(all(e.ruleId == "UI-RULE" for e in ui_evidence))
        self.assertTrue(all(e.resourcePath == "GUI/Library/Tooltips.xaml" for e in ui_evidence))

    def test_story_ledger_categories(self) -> None:
        dialogue = uid("4")
        readable = uid("5")
        character = uid("6")
        mappings = [
            mapping(
                dialogue,
                "story-occurrence",
                "NPCDialogue",
                evidence_type="StoryOccurrence",
                rule_id="STORY",
                properties={
                    "resourceFamily": "DialogsBinary",
                    "storyDomain": "NPCDialogue",
                    "attributeRole": "TagText",
                    "isOldText": False,
                },
            ),
            mapping(
                readable,
                "story-occurrence",
                "ReadableWorldText",
                evidence_type="StoryOccurrence",
                rule_id="STORY",
                properties={
                    "resourceFamily": "ReadableLocalizationRegistry",
                    "storyDomain": "ReadableWorldText",
                    "attributeRole": "Content",
                    "isOldText": False,
                },
            ),
            mapping(
                character,
                "story-occurrence",
                "StoryRelatedTerm",
                evidence_type="StoryOccurrence",
                rule_id="STORY",
                properties={
                    "resourceFamily": "TagsCharacters",
                    "storyDomain": "StoryRelatedTerm",
                    "attributeRole": "DisplayName",
                    "isOldText": False,
                },
            ),
        ]
        results = {r.contentUid: r for r in classify_functional_ownership([dialogue, readable, character], mappings)}
        self.assertEqual(results[dialogue].primaryCategory, "dialogue_general")
        self.assertEqual(results[readable].primaryCategory, "book_lore")
        self.assertEqual(results[character].primaryCategory, "character_world")

    def test_ui_skill_universe_items_equipment(self) -> None:
        target = uid("7")
        result = classify_functional_ownership(
            [target],
            [
                mapping(
                    target,
                    "ui-skill-universe",
                    "ItemsEquipment",
                    evidence_type="UiSkillUniverse",
                    rule_id="UI-SKILL",
                    properties={
                        "status": "Eligible",
                        "workstream": "ItemsEquipment",
                        "fieldName": "DisplayName",
                    },
                )
            ],
        )[0]
        self.assertEqual(result.primaryCategory, "item")
        self.assertEqual(result.classificationConfidence, "high")

    def test_remaining_safe_structural_rules(self) -> None:
        tutorial = uid("8")
        action_resource = uid("9")
        world = uid("a")
        system = uid("b")
        item_combo = uid("c")
        gameplay_registry = uid("d")
        quest_timer = uid("e")
        osiris = uid("f")

        mappings = [
            mapping(
                tutorial,
                "ui-skill-universe",
                "TutorialSystem",
                evidence_type="UiSkillUniverse",
                rule_id="UI-SKILL",
                properties={
                    "status": "Eligible",
                    "workstream": "TutorialSystem",
                    "domains": "UI.Tutorial",
                    "entityType": "UnifiedTutorial",
                    "fieldName": "DisplayTitle",
                },
            ),
            mapping(
                action_resource,
                "ui-skill-universe",
                "AQResourceReferencedReview",
                evidence_type="UiSkillUniverse",
                rule_id="UI-SKILL",
                properties={
                    "status": "Eligible",
                    "workstream": "AQResourceReferencedReview",
                    "domains": "Ability.Unknown",
                    "entityType": "ActionResourceDefinition",
                    "fieldName": "DisplayName",
                },
            ),
            mapping(
                world,
                "story-occurrence",
                "StoryRelatedTerm",
                evidence_type="StoryOccurrence",
                rule_id="STORY",
                path="Public/Shared/Localization/Subregions.lsf",
                properties={
                    "resourceFamily": "LocalizationRegistry",
                    "storyDomain": "StoryRelatedTerm",
                    "attributeRole": "Content",
                    "isOldText": False,
                },
            ),
            mapping(
                system,
                "story-occurrence",
                "StoryRelatedTerm",
                evidence_type="StoryOccurrence",
                rule_id="STORY",
                path="Public/Shared/Localization/ReadyChecks_Descriptions.lsf",
                properties={
                    "resourceFamily": "LocalizationRegistry",
                    "storyDomain": "StoryRelatedTerm",
                    "attributeRole": "Content",
                    "isOldText": False,
                },
            ),
            mapping(
                item_combo,
                "story-occurrence",
                "StoryRelatedTerm",
                evidence_type="StoryOccurrence",
                rule_id="STORY",
                path="Public/Shared/Localization/ItemCombinations.lsf",
                properties={
                    "resourceFamily": "LocalizationRegistry",
                    "storyDomain": "StoryRelatedTerm",
                    "attributeRole": "Content",
                    "isOldText": False,
                },
            ),
            mapping(
                gameplay_registry,
                "story-occurrence",
                "StoryRelatedTerm",
                evidence_type="StoryOccurrence",
                rule_id="STORY",
                path="Public/Shared/Localization/Status.lsf",
                properties={
                    "resourceFamily": "LocalizationRegistry",
                    "storyDomain": "StoryRelatedTerm",
                    "attributeRole": "Content",
                    "isOldText": False,
                },
            ),
            mapping(
                quest_timer,
                "story-occurrence",
                "StoryRelatedTerm",
                evidence_type="StoryOccurrence",
                rule_id="STORY",
                path="Public/Shared/Localization/QuestTimers.lsf",
                properties={
                    "resourceFamily": "LocalizationRegistry",
                    "storyDomain": "StoryRelatedTerm",
                    "attributeRole": "Content",
                    "isOldText": False,
                },
            ),
            mapping(
                osiris,
                "story-occurrence",
                "StoryRelatedTerm",
                evidence_type="StoryOccurrence",
                rule_id="STORY",
                path="Public/Shared/Localization/OsirisStrings.lsf",
                properties={
                    "resourceFamily": "LocalizationRegistry",
                    "storyDomain": "StoryRelatedTerm",
                    "attributeRole": "Content",
                    "isOldText": False,
                },
            ),
        ]

        results = {
            r.contentUid: r
            for r in classify_functional_ownership(
                [tutorial, action_resource, world, system, item_combo, gameplay_registry, quest_timer, osiris],
                mappings,
            )
        }

        self.assertEqual(results[tutorial].primaryCategory, "tutorial")
        self.assertEqual(results[action_resource].primaryCategory, "skill_spell")
        self.assertEqual(results[world].primaryCategory, "character_world")
        self.assertEqual(results[system].primaryCategory, "system_message")
        self.assertEqual(results[item_combo].primaryCategory, "item")
        self.assertEqual(results[gameplay_registry].primaryCategory, "skill_spell")
        self.assertEqual(results[quest_timer].primaryCategory, "other")
        self.assertEqual(results[osiris].primaryCategory, "other")

    def test_real_registry_stem_variants(self) -> None:
        cases = [
            ("1", "Public/Shared/Localization/Act3_Subregions.lsf", "character_world"),
            ("2", "Public/Shared/Localization/Waypointshrines2.lsf", "character_world"),
            ("3", "Public/Shared/Localization/Stats/Dome_DisplayName.lsf", "skill_spell"),
            ("4", "Public/Shared/Localization/Stats/Status_KNOCKED_DOWN_Description.lsf", "skill_spell"),
            ("5", "Public/Shared/Localization/Shout_TooltipOnRollFail.lsf", "skill_spell"),
            ("6", "Public/Shared/Localization/Target_TooltipOnRollFail.lsf", "skill_spell"),
            ("7", "Public/Shared/Localization/QuestTimers.lsf", "other"),
            ("8", "Public/Shared/Localization/OsirisStrings.lsf", "other"),
        ]
        mappings = []
        content_uids = []
        expected = {}
        for token, path, category in cases:
            target = uid(token)
            content_uids.append(target)
            expected[target] = category
            mappings.append(
                mapping(
                    target,
                    "story-occurrence",
                    "StoryRelatedTerm",
                    evidence_type="StoryOccurrence",
                    rule_id="STORY",
                    path=path,
                    properties={
                        "resourceFamily": "LocalizationRegistry",
                        "storyDomain": "StoryRelatedTerm",
                        "attributeRole": "Content",
                        "isOldText": False,
                    },
                )
            )

        results = {r.contentUid: r for r in classify_functional_ownership(content_uids, mappings)}
        for target, category in expected.items():
            self.assertEqual(results[target].primaryCategory, category)

    def test_summary_invariants(self) -> None:
        targets = [uid("d"), uid("e")]
        results = classify_functional_ownership(
            targets,
            [mapping(targets[0], "quest-journal", "QuestTitle", evidence_type="QuestJournal", rule_id="QUEST")],
        )
        summary = summarize_functional_classification(results)
        self.assertEqual(summary["totalContentUidCount"], 2)
        self.assertEqual(summary["duplicateOwnershipCount"], 0)
        self.assertEqual(summary["missingContentUidCount"], 0)
        self.assertEqual(summary["statusCounts"]["classified"], 1)
        self.assertEqual(summary["statusCounts"]["unclassified"], 1)


if __name__ == "__main__":
    unittest.main()
