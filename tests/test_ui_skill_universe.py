from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bg3loc.research.ui_skill_universe import (
    DIRECT_FAMILY_RULES,
    UiSkillOccurrence,
    UiSkillProvider,
    UiSkillProviderRole,
    _materialize_inheritance,
    _direct_matches,
    classify_workstream,
    discover_ui_skill_providers,
    extract_ui_skill_universe,
    normalize_internal_path,
    provider_semantic_role,
    resource_format,
    write_ui_skill_provider_ledger,
    write_ui_skill_universe,
)


class UiSkillUniverseRuleTests(unittest.TestCase):
    def test_direct_family_count_is_thirteen(self) -> None:
        self.assertEqual(len(DIRECT_FAMILY_RULES), 13)

    def test_family_selectors_match_recovered_literals(self) -> None:
        cases = [
            ("Gustav.pak", "Public/Gustav/Stats/Generated/Data/Spell_Target.txt", "SpellData"),
            ("Shared.pak", "Public/Shared/Stats/Generated/Data/Passive.txt", "PassiveData"),
            ("GustavX.pak", "Public/GustavX/Stats/Generated/Data/Status_BOOST.txt", "StatusData"),
            ("Gustav.pak", "Public/Gustav/Stats/Generated/Data/Interrupt.txt", "InterruptData"),
            ("Shared.pak", "Public/Shared/Progressions/ProgressionDescriptions.lsx", "Progressions"),
            ("Shared.pak", "Public/Shared/ClassDescriptions.lsx", "ClassDescriptions"),
            ("Shared.pak", "Public/Shared/Feats.lsx", "FeatDescriptions"),
            ("Game.pak", "Public/Game/GUI/ActionResourcePanel.xaml", "ActionResourceDefinitions"),
            ("Gustav.pak", "Public/Gustav/Stats/Generated/Data/Weapon.txt", "Weapon/Armor/Object Stats"),
            ("Shared.pak", "Public/Shared/RootTemplates/_merged.lsf", "Root Templates"),
            ("Game.pak", "Public/Game/Anything/Panel.xaml", "UI/GUI definitions"),
            ("Patch8_HotFix9.pak", "Public/Game/GUI/TutorialPanel.xaml", "Tutorial definitions"),
            ("Game.pak", "Public/Game/GUI/SystemMessageBox.xaml", "System message definitions"),
        ]
        for package, path, expected in cases:
            with self.subTest(expected=expected):
                self.assertIn(expected, {rule.name for rule in _direct_matches(package, path)})

    def test_xaml_family_does_not_require_gui_segment(self) -> None:
        names = {rule.name for rule in _direct_matches("Game.pak", "Content/Whatever/Screen.xaml")}
        self.assertIn("UI/GUI definitions", names)

    def test_path_safety_and_format_dispatch(self) -> None:
        self.assertEqual(normalize_internal_path(r"Public\Game\GUI\Panel.xaml"), "Public/Game/GUI/Panel.xaml")
        self.assertEqual(resource_format("Public/Game/GUI/Panel.xaml"), "XAML")
        self.assertEqual(resource_format("Public/Game/Thing.lsf"), "LSF")
        self.assertEqual(resource_format("Public/Game/Thing.lsx"), "LSX")
        self.assertEqual(resource_format("Public/Game/Stats/Generated/Data/Spell_X.txt"), "StatsTXT")
        self.assertEqual(resource_format("Public/Game/Tutorial.txt"), "OtherTXT")
        for invalid in ("../bad.xaml", "C:/bad.xaml", "bad:*?.xaml"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_internal_path(invalid)

    @staticmethod
    def occurrence(*, families: tuple[str, ...], domains: tuple[str, ...], entity_type: str, provider: str = "P::x") -> UiSkillOccurrence:
        return UiSkillOccurrence(
            content_uid="synthetic",
            provider=provider,
            package="P.pak",
            internal_path="Synthetic/path",
            source_families=families,
            domains=domains,
            entity_type=entity_type,
            entity_name="Entity",
            field_name="Description",
        )

    def test_workstream_priority_matches_recovered_order(self) -> None:
        self.assertEqual(classify_workstream([self.occurrence(families=("SpellData", "Root Templates"), domains=("Ability.Spell",), entity_type="Item")]), "AbilitySkill")
        self.assertEqual(classify_workstream([self.occurrence(families=("Root Templates",), domains=("Item.Unknown",), entity_type="GameObjects")]), "ItemsEquipment")
        self.assertEqual(classify_workstream([self.occurrence(families=("Tutorial definitions",), domains=("UI.Tutorial",), entity_type="Tutorial")]), "TutorialSystem")
        self.assertEqual(classify_workstream([self.occurrence(families=("UI/GUI definitions",), domains=("UI.Unknown",), entity_type="XAML", provider="Game.pak::MainUI/GUI/X.xaml")]), "UserInterface")

    def test_collision_providers_are_all_retained(self) -> None:
        class Backend:
            def list_archive(self, package: Path):
                if package.name in {"Shared.pak", "Gustav.pak"}:
                    return [SimpleNamespace(path="Public/Shared/RootTemplates/Same.lsf")]
                return []

        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            (game / "Data").mkdir()
            for package in ("Shared.pak", "Gustav.pak"):
                (game / "Data" / package).touch()
            providers = discover_ui_skill_providers(game, Backend())
        self.assertEqual(len(providers), 2)
        self.assertTrue(all(item.collision for item in providers))

    def test_provider_semantic_roles_follow_context_routes_without_uid_input(self) -> None:
        cases = [
            (
                {
                    "package": "Game.pak",
                    "internal_path": "Public/Game/GUI/Panel.xaml",
                    "module": "Game",
                    "source_families": ("UI/GUI definitions",),
                    "resource_format_name": "XAML",
                },
                UiSkillProviderRole.CANDIDATE_EVIDENCE,
            ),
            (
                {
                    "package": "GustavX.pak",
                    "internal_path": "Public/GustavX/Stats/Generated/Data/Spell_Target.txt",
                    "module": "GustavX",
                    "source_families": ("SpellData",),
                    "resource_format_name": "StatsTXT",
                },
                UiSkillProviderRole.CONTEXT_EVIDENCE_ONLY,
            ),
            (
                {
                    "package": "Shared.pak",
                    "internal_path": "Public/Shared/Stats/Generated/Data/Status_BOOST.txt",
                    "module": "Shared",
                    "source_families": ("StatusData",),
                    "resource_format_name": "StatsTXT",
                },
                UiSkillProviderRole.CONTEXT_EVIDENCE_AND_COLLISION_PROVENANCE,
            ),
        ]
        for arguments, expected in cases:
            with self.subTest(path=arguments["internal_path"]):
                self.assertEqual(provider_semantic_role(**arguments), expected)

    def test_support_provider_remains_in_ledger_but_emits_no_occurrences(self) -> None:
        candidate_uid = "h00000000g0000g0000g0000g000000000001"
        support_uid = "h00000000g0000g0000g0000g000000000002"

        class Backend:
            extracted_paths: list[str]

            def __init__(self) -> None:
                self.extracted_paths = []

            def list_archive(self, package: Path):
                if package.name == "Game.pak":
                    return [SimpleNamespace(path="Public/Game/GUI/Panel.xaml")]
                if package.name == "GustavX.pak":
                    return [SimpleNamespace(path="Public/GustavX/Stats/Generated/Data/Spell_Target.txt")]
                return []

            def extract_single_file(self, package: Path, packaged_path: str, destination: Path) -> None:
                self.extracted_paths.append(packaged_path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if packaged_path.endswith(".xaml"):
                    destination.write_text(
                        f'<TextBlock Name="Label" Content="{candidate_uid}" />',
                        encoding="utf-8",
                    )
                else:
                    destination.write_text(
                        f'new entry "Support"\ndata "DisplayName" "{support_uid}"',
                        encoding="utf-8",
                    )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "game"
            output = root / "output"
            (game / "Data").mkdir(parents=True)
            for package in ("Game.pak", "GustavX.pak"):
                (game / "Data" / package).touch()
            backend = Backend()
            result = extract_ui_skill_universe(game, backend, output)
            ledger = output / "providers.csv"
            write_ui_skill_provider_ledger(ledger, result.providers)
            with ledger.open(encoding="utf-8", newline="") as stream:
                ledger_rows = list(csv.DictReader(stream))

        self.assertEqual(len(result.providers), 2)
        self.assertEqual(backend.extracted_paths, ["Public/Game/GUI/Panel.xaml"])
        self.assertEqual({item.content_uid for item in result.direct_occurrences}, {candidate_uid})
        self.assertNotIn(support_uid, {item.content_uid for item in result.direct_occurrences})
        self.assertEqual(
            {row["SemanticRole"] for row in ledger_rows},
            {"CandidateEvidence", "ContextEvidenceOnly"},
        )

    def test_collision_support_provider_retains_provenance_metadata(self) -> None:
        class Backend:
            def list_archive(self, package: Path):
                if package.name == "Shared.pak":
                    return [SimpleNamespace(path="Public/Shared/Stats/Generated/Data/Status_BOOST.txt")]
                return []

        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            (game / "Data").mkdir()
            (game / "Data" / "Shared.pak").touch()
            providers = discover_ui_skill_providers(game, Backend())

        self.assertEqual(len(providers), 1)
        self.assertEqual(
            providers[0].role,
            UiSkillProviderRole.CONTEXT_EVIDENCE_AND_COLLISION_PROVENANCE,
        )
        self.assertTrue(providers[0].collision_provenance)

    def test_inheritance_is_preserved_and_cycles_are_held(self) -> None:
        def item(uid: str, entity: str, field: str, parent: str = "") -> UiSkillOccurrence:
            return UiSkillOccurrence(
                uid, "Shared.pak::Stats.txt", "Shared.pak", "Stats.txt",
                ("PassiveData",), ("Ability.Unknown",), "PassiveData", entity, field,
                parent_name=parent,
            )

        materialized, holds = _materialize_inheritance([
            item("parent-uid", "Parent", "Description"),
            item("child-uid", "Child", "DisplayName", "Parent"),
            item("cycle-a", "CycleA", "Description", "CycleB"),
            item("cycle-b", "CycleB", "DisplayName", "CycleA"),
        ])
        inherited = [row for row in materialized if row.entity_name == "Child" and row.explicit_or_inherited == "inherited"]
        self.assertEqual([(row.content_uid, row.field_name, row.inheritance_depth) for row in inherited], [("parent-uid", "Description", 1)])
        self.assertEqual(inherited[0].defining_provider, "Shared.pak::Stats.txt")
        self.assertTrue({"cycle-a", "cycle-b"} <= holds)

    def test_precedence_holds_require_same_resource_entity_and_field(self) -> None:
        def item(uid: str, provider: str, path: str) -> UiSkillOccurrence:
            return UiSkillOccurrence(
                uid, provider, provider.split("::", 1)[0], path,
                ("UI/GUI definitions",), ("UI.Unknown",), "TextBlock",
                "label", "Text",
            )

        _rows, holds = _materialize_inheritance([
            item("first", "Game.pak::same", "Mods/MainUI/GUI/Same.xaml"),
            item("second", "Patch8_HotFix9.pak::same", "Mods/MainUI/GUI/Same.xaml"),
            item("unrelated", "Game.pak::other", "Mods/MainUI/GUI/Other.xaml"),
        ])
        self.assertEqual(holds, {"first", "second"})

    def test_aq_override_and_hold_status_are_written_per_relation(self) -> None:
        ability = self.occurrence(families=("SpellData",), domains=("Ability.Unknown",), entity_type="SpellData")
        held = UiSkillOccurrence(
            "held", ability.provider, ability.package, ability.internal_path,
            ability.source_families, ability.domains, ability.entity_type,
            ability.entity_name, ability.field_name,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ui-skill-universe.csv"
            write_ui_skill_universe(path, [ability, held], hold_uids={"held"}, aq_uids={"synthetic"})
            with path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
        by_uid = {row["ContentUid"]: row for row in rows}
        self.assertEqual(by_uid["synthetic"]["Workstream"], "AQResourceReferencedReview")
        self.assertEqual(by_uid["held"]["Status"], "Hold")
        self.assertEqual(by_uid["synthetic"]["DefiningProvider"], ability.provider)


if __name__ == "__main__":
    unittest.main()
