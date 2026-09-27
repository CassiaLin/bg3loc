import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bg3loc.commands.research import (
    ResearchClassifyRequest,
    run_research_classify_request,
    run_research_map,
)
from bg3loc.backends import ArchiveBackend, ArchiveBackendError
from bg3loc.research.model import ResearchScanResource

class TestOrchestration(unittest.TestCase):
    def test_research_map_orchestration_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            scan_file = tmp_path / 'scan.json'
            output_dir = tmp_path / 'output'
            game_dir = tmp_path / 'game'
            (game_dir / 'Data').mkdir(parents=True)
            
            # Create fake pak
            pak_file = game_dir / 'Data' / 'English.pak'
            pak_file.touch()
            
            # Create scan manifest
            scan_data = {
                'gameDir': str(game_dir),
                'resources': [
                    {
                        'pakName': 'English.pak',
                        'internalPath': 'Localization/English/english.loca',
                        'resourceFormat': 'LOCA',
                        'sourceRole': 'LocaResource',
                        'size': 100
                    }
                ]
            }
            with open(scan_file, 'w', encoding='utf-8') as f:
                json.dump(scan_data, f)
                
            from types import SimpleNamespace
            args = SimpleNamespace(
                scan=str(scan_file),
                output_dir=str(output_dir),
                source="English",
                target="ChineseTraditional",
                reference=[],
            )
                
            # Mock resolve_backend and backend_from_probe
            mock_probe = mock.MagicMock()
            mock_backend = mock.MagicMock(spec=ArchiveBackend)
            
            # Simulate extraction failure
            mock_backend.extract_single_file.side_effect = Exception('Mock extraction failure')
            
            with mock.patch('bg3loc.commands.research.resolve_backend', return_value=mock_probe), \
                 mock.patch('bg3loc.commands.research.backend_from_probe', return_value=mock_backend):
                 
                 with self.assertRaises(RuntimeError) as context:
                     run_research_map(args)
                     
                 self.assertIn('Failed to extract REQUIRED resource', str(context.exception))

    def test_scanner_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            from bg3loc.research.scanner import scan_game_research_resources
            
            game_dir = tmp_path / 'game'
            (game_dir / 'Data').mkdir(parents=True)
            pak_file = game_dir / 'Data' / 'Gustav.pak'
            pak_file.touch()
            
            mock_backend = mock.MagicMock(spec=ArchiveBackend)
            mock_backend.list_archive.side_effect = Exception('Failed to list archive')
            
            with self.assertRaises(RuntimeError) as exc_info:
                scan_game_research_resources(game_dir, backend=mock_backend)
                
            self.assertIn('Failed to list required archive', str(exc_info.exception))

    def test_functional_classify_command_uses_full_source_uid_universe(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            normalized = root / "English.jsonl"
            extract_manifest = root / "extract-manifest.json"
            mappings_path = root / "research-mappings.jsonl"
            output_dir = root / "classification"

            uid_bark = "h11111111g1111g1111g1111g111111111111"
            uid_other = "h22222222g2222g2222g2222g222222222222"

            normalized.write_text(
                json.dumps({"contentUid": uid_bark, "localeId": "English", "text": "A"}) + "\n"
                + json.dumps({"contentUid": uid_other, "localeId": "English", "text": "B"}) + "\n",
                encoding="utf-8",
            )
            extract_manifest.write_text(
                json.dumps(
                    {
                        "sourceLocale": "English",
                        "locales": [
                            {
                                "localeId": "English",
                                "normalized": str(normalized),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            mappings_path.write_text(
                json.dumps(
                    {
                        "contentUid": uid_bark,
                        "mappingType": "bark-speaker",
                        "classification": "SingleSpeaker",
                        "reviewRequired": True,
                        "evidence": [
                            {
                                "sourceRole": "Synthetic",
                                "resourcePath": "Story/DialogsBinary/Bark.lsf",
                                "evidenceType": "BarkSpeakerStructure",
                                "ruleId": "BG3-BARK-SPEAKER-STRUCTURE",
                                "properties": {},
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            rc = run_research_classify_request(
                ResearchClassifyRequest(
                    extract_manifest=extract_manifest,
                    research_mappings=mappings_path,
                    output_dir=output_dir,
                )
            )
            self.assertEqual(rc, 0)

            ledger = [
                json.loads(line)
                for line in (output_dir / "functional-classification.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(ledger), 2)
            by_uid = {row["contentUid"]: row for row in ledger}
            self.assertEqual(by_uid[uid_bark]["primaryCategory"], "bark")
            self.assertEqual(by_uid[uid_other]["primaryCategory"], "other")

            summary = json.loads(
                (output_dir / "functional-classification-summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["totalContentUidCount"], 2)
            self.assertEqual(summary["statusCounts"]["classified"], 1)
            self.assertEqual(summary["statusCounts"]["unclassified"], 1)
            self.assertEqual(summary["duplicateOwnershipCount"], 0)
            self.assertEqual(summary["missingContentUidCount"], 0)

    def test_functional_classify_command_rejects_duplicate_source_uid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            normalized = root / "English.jsonl"
            extract_manifest = root / "extract-manifest.json"
            mappings_path = root / "research-mappings.jsonl"

            repeated = "h33333333g3333g3333g3333g333333333333"
            normalized.write_text(
                json.dumps({"contentUid": repeated}) + "\n" + json.dumps({"contentUid": repeated}) + "\n",
                encoding="utf-8",
            )
            extract_manifest.write_text(
                json.dumps(
                    {
                        "sourceLocale": "English",
                        "locales": [{"localeId": "English", "normalized": str(normalized)}],
                    }
                ),
                encoding="utf-8",
            )
            mappings_path.write_text("", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "duplicate ContentUid"):
                run_research_classify_request(
                    ResearchClassifyRequest(
                        extract_manifest=extract_manifest,
                        research_mappings=mappings_path,
                        output_dir=root / "out",
                    )
                )

    def test_functional_classify_command_auto_ingests_sibling_ledgers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            research_dir = root / "research"
            research_dir.mkdir()
            normalized = root / "English.jsonl"
            extract_manifest = root / "extract-manifest.json"
            mappings_path = research_dir / "research-mappings.jsonl"
            story_ledger = research_dir / "story-occurrence-ledger.csv"
            ui_skill_universe = research_dir / "ui-skill-universe.csv"
            output_dir = root / "classification"

            uid_dialog = "h44444444g4444g4444g4444g444444444444"
            uid_item = "h55555555g5555g5555g5555g555555555555"
            uid_book = "h66666666g6666g6666g6666g666666666666"

            normalized.write_text(
                "\n".join(
                    json.dumps({"contentUid": value, "localeId": "English", "text": value})
                    for value in (uid_dialog, uid_item, uid_book)
                ) + "\n",
                encoding="utf-8",
            )
            extract_manifest.write_text(
                json.dumps(
                    {
                        "sourceLocale": "English",
                        "locales": [{"localeId": "English", "normalized": str(normalized)}],
                    }
                ),
                encoding="utf-8",
            )
            mappings_path.write_text("", encoding="utf-8")
            story_ledger.write_text(
                "ContentUid,PakName,InternalPath,ResourceFamily,ResourceFormat,StoryDomain,NodeId,AttributeRole,HasSpeaker,HasDialog,HasQuest,IsOldText\n"
                f"{uid_dialog},Gustav.pak,Mods/Gustav/Story/DialogsBinary/A.lsf,DialogsBinary,LSF,NPCDialogue,node,TagText,True,True,False,False\n"
                f"{uid_book},Gustav.pak,Mods/Gustav/Localization/Books.lsf,ReadableLocalizationRegistry,LSF,ReadableWorldText,,Content,False,False,False,False\n",
                encoding="utf-8",
            )
            ui_skill_universe.write_text(
                "ContentUid,Status,Workstream,Provider,Package,InternalPath,SourceFamilies,Domains,EntityType,EntityName,FieldName,ParentName,InheritanceDepth,ExplicitOrInherited,CommentOnly,DefiningProvider,ProviderOverrideApplied\n"
                f"{uid_item},Eligible,ItemsEquipment,p,Gustav.pak,Public/Gustav/RootTemplates/A.lsf,Root Templates,Item.Unknown,node,ItemA,DisplayName,,0,explicit,false,p,false\n",
                encoding="utf-8",
            )

            rc = run_research_classify_request(
                ResearchClassifyRequest(
                    extract_manifest=extract_manifest,
                    research_mappings=mappings_path,
                    output_dir=output_dir,
                )
            )
            self.assertEqual(rc, 0)
            ledger = [
                json.loads(line)
                for line in (output_dir / "functional-classification.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            by_uid = {row["contentUid"]: row for row in ledger}
            self.assertEqual(by_uid[uid_dialog]["primaryCategory"], "dialogue_general")
            self.assertEqual(by_uid[uid_item]["primaryCategory"], "item")
            self.assertEqual(by_uid[uid_book]["primaryCategory"], "book_lore")

            summary = json.loads(
                (output_dir / "functional-classification-summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["storyLedger"], str(story_ledger))
            self.assertEqual(summary["uiSkillUniverse"], str(ui_skill_universe))

if __name__ == '__main__':
    unittest.main()
