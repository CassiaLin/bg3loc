from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bg3loc.commands.research import ResearchBatchRequest, run_research_batch_request
from bg3loc.research.batching import (
    BatchInputRecord,
    build_batch_plan,
    canonical_group_key,
    normalize_dialog_resource,
)
from bg3loc.research.quest import parse_quest_xml
from bg3loc.research.story import parse_readable_registry_occurrences
from bg3loc.research.ui_skill_universe import UiSkillProvider, _parse_xml


def uid(ch: str) -> str:
    return f"h{ch * 8}g{ch * 4}g{ch * 4}g{ch * 4}g{ch * 12}"


class TestCategoryAwareBatching(unittest.TestCase):
    def test_dialog_raw_binary_normalize_to_same_group(self) -> None:
        raw = "Mods/Gustav/Story/Dialogs/Act1/Foo.lsj"
        binary = "Mods/Gustav/Story/DialogsBinary/Act1/Foo.lsf"
        self.assertEqual(normalize_dialog_resource(raw), "dialog:act1/foo")
        self.assertEqual(normalize_dialog_resource(binary), "dialog:act1/foo")

    def test_multiple_groups_choose_one_canonical_group(self) -> None:
        record = BatchInputRecord(
            content_uid=uid("1"),
            source_text="A",
            primary_category="dialogue_general",
            classification_status="classified",
            group_candidates=("dialog:z/path", "dialog:a/path", "dialog:m/path"),
        )
        self.assertEqual(canonical_group_key(record), "dialog:a/path")

    def test_category_pure_sequential_packing_and_unresolved(self) -> None:
        records = [
            BatchInputRecord(uid("1"), "A", "item", "classified", ("entity:a",)),
            BatchInputRecord(uid("2"), "B", "item", "classified", ("entity:a",)),
            BatchInputRecord(uid("3"), "C", "item", "classified", ("entity:b",)),
            BatchInputRecord(uid("4"), "D", "quest", "classified", ("path:q",)),
            BatchInputRecord(uid("5"), "E", "other", "unclassified"),
        ]
        plan = build_batch_plan(records, max_records={"item": 2, "quest": 2})

        self.assertEqual(plan.unresolved_uids, (uid("5"),))
        self.assertEqual([m.batchId for m in plan.batches], [
            "item-0001",
            "item-0002",
            "quest-0001",
        ])
        self.assertEqual(plan.batches[0].contentUids, (uid("1"), uid("2")))
        self.assertEqual(plan.batches[1].contentUids, (uid("3"),))
        self.assertEqual(plan.batches[2].contentUids, (uid("4"),))
        for manifest in plan.batches:
            self.assertTrue(
                all(
                    row.primaryCategory == manifest.primaryCategory
                    for row in plan.records_by_batch[manifest.batchId]
                )
            )

    def test_oversize_group_splits_deterministically(self) -> None:
        records = [
            BatchInputRecord(
                uid(ch),
                ch,
                "tutorial",
                "classified",
                ("entity:tutorial-a",),
                (f"field:{ch}",),
            )
            for ch in "12345"
        ]
        first = build_batch_plan(records, max_records={"tutorial": 2})
        second = build_batch_plan(list(reversed(records)), max_records={"tutorial": 2})

        self.assertEqual(
            [(m.batchId, m.contentUids) for m in first.batches],
            [(m.batchId, m.contentUids) for m in second.batches],
        )
        self.assertEqual([m.recordCount for m in first.batches], [2, 2, 1])
        self.assertTrue(all(m.oversizeGroupSplit for m in first.batches))

    def test_quest_parser_retains_enclosing_entity_identity(self) -> None:
        target = uid("6")
        xml = (
            '<save><region id="Journal"><node id="Quests"><children>'
            '<node id="Quest"><attribute id="UUID" value="quest-uuid-1"/>'
            f'<attribute id="QuestTitle" handle="{target}"/>'
            '</node></children></node></region></save>'
        )
        rows = list(parse_quest_xml(xml, resource_path="Mods/GustavDev/Story/Journal/quest_prototypes.lsx"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].evidence[0].properties["entityId"], "quest-uuid-1")

    def test_story_xml_parser_retains_node_identity(self) -> None:
        target = uid("7")
        xml = (
            '<save><region id="Books"><node id="Book">'
            '<attribute id="UUID" value="book-uuid-1"/>'
            f'<attribute id="Content" handle="{target}"/>'
            '</node></region></save>'
        )
        rows = parse_readable_registry_occurrences(
            xml,
            "GustavDev.pak",
            "Public/GustavDev/Localization/Generated_Books.lsf",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].nodeId, "book-uuid-1")

    def test_ui_xml_parser_retains_child_attribute_entity_identity(self) -> None:
        target = uid("8")
        provider = UiSkillProvider(
            package="Shared.pak",
            internal_path="Public/Shared/RootTemplates/_merged.lsf",
            resource_format="LSX",
            module="Shared",
            source_families=("Root Templates",),
            source_subfamilies=("RootTemplate",),
            domain_candidates=("Item.Unknown",),
        )
        xml = (
            '<save><region id="Templates"><node id="GameObjects"><children>'
            '<node id="GameObject"><attribute id="MapKey" value="object-uuid-1"/>'
            f'<attribute id="DisplayName" handle="{target}"/>'
            '</node></children></node></region></save>'
        )
        rows = _parse_xml(xml, provider)
        hit = next(row for row in rows if row.content_uid == target)
        self.assertEqual(hit.entity_name, "object-uuid-1")
        self.assertEqual(hit.entity_type, "GameObject")

    def test_cli_uses_research_entry_and_node_grouping(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            classification = root / "functional-classification.jsonl"
            source = root / "English.jsonl"
            story = root / "story-occurrence-ledger.csv"
            research = root / "research-mappings.jsonl"
            output = root / "out"

            skill_a = uid("9")
            skill_b = uid("a")
            book_a = uid("b")
            quest_a = uid("c")
            rows = [
                (skill_a, "skill_spell"),
                (skill_b, "skill_spell"),
                (book_a, "book_lore"),
                (quest_a, "quest"),
            ]
            classification.write_text(
                "\n".join(
                    json.dumps({
                        "contentUid": value,
                        "primaryCategory": category,
                        "tags": [],
                        "classificationStatus": "classified",
                        "classificationConfidence": "high",
                        "classificationEvidence": [],
                    })
                    for value, category in rows
                ) + "\n",
                encoding="utf-8",
            )
            source.write_text(
                "\n".join(
                    json.dumps({"contentUid": value, "localeId": "English", "text": value})
                    for value, _ in rows
                ) + "\n",
                encoding="utf-8",
            )
            story.write_text(
                "ContentUid,PakName,InternalPath,ResourceFamily,ResourceFormat,StoryDomain,NodeId,AttributeRole,HasSpeaker,HasDialog,HasQuest,IsOldText\n"
                f"{book_a},GustavDev.pak,Public/GustavDev/Localization/Generated_Books.lsf,ReadableLocalizationRegistry,LSF,ReadableWorldText,book-uuid-1,Content,False,False,False,False\n",
                encoding="utf-8",
            )
            research.write_text(
                "\n".join([
                    json.dumps({
                        "contentUid": skill_a,
                        "mappingType": "stat-reference",
                        "classification": "StatLocalizationReference",
                        "evidence": [{
                            "sourceRole": "StatsRecordField",
                            "resourcePath": "Public/Shared/Stats/Generated/Data/Passive.txt",
                            "evidenceType": "StatsDefinition",
                            "ruleId": "BG3-STAT-DIRECT-LOCALIZATION-REFERENCE",
                            "properties": {"entryName": "Passive_A", "fieldName": "DisplayName"},
                        }],
                    }),
                    json.dumps({
                        "contentUid": skill_b,
                        "mappingType": "stat-reference",
                        "classification": "StatLocalizationReference",
                        "evidence": [{
                            "sourceRole": "StatsRecordField",
                            "resourcePath": "Public/Shared/Stats/Generated/Data/Passive.txt",
                            "evidenceType": "StatsDefinition",
                            "ruleId": "BG3-STAT-DIRECT-LOCALIZATION-REFERENCE",
                            "properties": {"entryName": "Passive_B", "fieldName": "DisplayName"},
                        }],
                    }),
                    json.dumps({
                        "contentUid": quest_a,
                        "mappingType": "quest-journal",
                        "classification": "QuestTitle",
                        "evidence": [{
                            "sourceRole": "QuestJournalField",
                            "resourcePath": "Mods/GustavDev/Story/Journal/quest_prototypes.lsx",
                            "evidenceType": "QuestJournal",
                            "ruleId": "BG3-QUEST-JOURNAL-EVIDENCE",
                            "properties": {"entityId": "quest-uuid-1", "elementIndex": 10, "fieldRole": "QuestTitle"},
                        }],
                    }),
                ]) + "\n",
                encoding="utf-8",
            )

            rc = run_research_batch_request(
                ResearchBatchRequest(
                    classification=classification,
                    source=source,
                    output_dir=output,
                    story_ledger=story,
                    research_mappings=research,
                    max_records=("skill_spell=10", "book_lore=10", "quest=10"),
                )
            )
            self.assertEqual(rc, 0)
            plan = json.loads((output / "batch-plan.json").read_text(encoding="utf-8"))
            group_keys = {
                row["primaryCategory"]: row["groupKeys"]
                for row in plan["batches"]
            }
            self.assertIn("stat:public/shared/stats/generated/data/passive.txt|passive_a", group_keys["skill_spell"])
            self.assertIn("stat:public/shared/stats/generated/data/passive.txt|passive_b", group_keys["skill_spell"])
            self.assertEqual(
                group_keys["book_lore"],
                ["story:public/gustavdev/localization/generated_books.lsf|book-uuid-1"],
            )
            self.assertEqual(
                group_keys["quest"],
                ["quest:mods/gustavdev/story/journal/quest_prototypes.lsx|quest-uuid-1"],
            )

    def test_cli_request_writes_repeatable_plan_and_isolates_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            classification = root / "functional-classification.jsonl"
            source = root / "English.jsonl"
            story = root / "story-occurrence-ledger.csv"
            ui = root / "ui-skill-universe.csv"

            dialog_a = uid("a")
            dialog_b = uid("b")
            item_a = uid("c")
            unresolved = uid("d")
            all_uids = [dialog_a, dialog_b, item_a, unresolved]

            classification_rows = [
                {
                    "contentUid": dialog_a,
                    "primaryCategory": "dialogue_general",
                    "tags": [],
                    "classificationStatus": "classified",
                    "classificationConfidence": "high",
                    "classificationEvidence": [],
                },
                {
                    "contentUid": dialog_b,
                    "primaryCategory": "dialogue_general",
                    "tags": [],
                    "classificationStatus": "classified",
                    "classificationConfidence": "high",
                    "classificationEvidence": [],
                },
                {
                    "contentUid": item_a,
                    "primaryCategory": "item",
                    "tags": [],
                    "classificationStatus": "classified",
                    "classificationConfidence": "high",
                    "classificationEvidence": [],
                },
                {
                    "contentUid": unresolved,
                    "primaryCategory": "other",
                    "tags": [],
                    "classificationStatus": "unclassified",
                    "classificationConfidence": "low",
                    "classificationEvidence": [],
                },
            ]
            classification.write_text(
                "\n".join(json.dumps(row) for row in classification_rows) + "\n",
                encoding="utf-8",
            )
            source.write_text(
                "\n".join(
                    json.dumps({"contentUid": value, "localeId": "English", "text": f"text-{value}"})
                    for value in all_uids
                ) + "\n",
                encoding="utf-8",
            )
            story.write_text(
                "ContentUid,PakName,InternalPath,ResourceFamily,ResourceFormat,StoryDomain,NodeId,AttributeRole,HasSpeaker,HasDialog,HasQuest,IsOldText\n"
                f"{dialog_a},Gustav.pak,Mods/Gustav/Story/Dialogs/Act1/Foo.lsj,DialogsRaw,LSJ,NPCDialogue,n1,TagText,True,True,False,False\n"
                f"{dialog_a},Gustav.pak,Mods/Gustav/Story/DialogsBinary/Act1/Foo.lsf,DialogsBinary,LSF,NPCDialogue,n1,TagText,True,True,False,False\n"
                f"{dialog_b},Gustav.pak,Mods/Gustav/Story/DialogsBinary/Act1/Foo.lsf,DialogsBinary,LSF,NPCDialogue,n2,TagText,True,True,False,False\n",
                encoding="utf-8",
            )
            ui.write_text(
                "ContentUid,Status,Workstream,Provider,Package,InternalPath,SourceFamilies,Domains,EntityType,EntityName,FieldName,ParentName,InheritanceDepth,ExplicitOrInherited,CommentOnly,DefiningProvider,ProviderOverrideApplied\n"
                f"{item_a},Eligible,ItemsEquipment,provider-a,Gustav.pak,Public/Gustav/RootTemplates/A.lsf,Root Templates,Item.Unknown,node,ItemA,DisplayName,,0,explicit,false,provider-a,false\n",
                encoding="utf-8",
            )

            out1 = root / "out1"
            out2 = root / "out2"
            for out in (out1, out2):
                rc = run_research_batch_request(
                    ResearchBatchRequest(
                        classification=classification,
                        source=source,
                        output_dir=out,
                        story_ledger=story,
                        ui_skill_universe=ui,
                        max_records=("dialogue_general=10", "item=10"),
                    )
                )
                self.assertEqual(rc, 0)

            plan1 = json.loads((out1 / "batch-plan.json").read_text(encoding="utf-8"))
            plan2 = json.loads((out2 / "batch-plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan1["batchPlanFingerprint"], plan2["batchPlanFingerprint"])
            self.assertEqual(
                [(row["batchId"], row["contentUids"]) for row in plan1["batches"]],
                [(row["batchId"], row["contentUids"]) for row in plan2["batches"]],
            )

            dialogue_batch = next(row for row in plan1["batches"] if row["primaryCategory"] == "dialogue_general")
            self.assertEqual(set(dialogue_batch["contentUids"]), {dialog_a, dialog_b})
            self.assertEqual(dialogue_batch["groupKeys"], ["dialog:act1/foo"])

            unresolved_rows = [
                json.loads(line)
                for line in (out1 / "unresolved.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual([row["contentUid"] for row in unresolved_rows], [unresolved])

            summary = json.loads((out1 / "batch-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["classifiedInputCount"], 3)
            self.assertEqual(summary["unresolvedCount"], 1)
            self.assertEqual(summary["duplicateBatchedUidCount"], 0)
            self.assertEqual(summary["missingClassifiedUidCount"], 0)
            self.assertEqual(summary["foreignUidCount"], 0)
            self.assertEqual(summary["mixedCategoryBatchCount"], 0)


if __name__ == "__main__":
    unittest.main()
