from __future__ import annotations

import unittest

from bg3loc.research.ui_skill_precedence import (
    Definition,
    is_aw_support_provider,
    parse_module_meta,
    parse_stats_definitions,
)
from bg3loc.research.ui_skill_runtime_reconcile import (
    _package_layer_hold_uids,
    _related_content_uids_by_edge,
)
from bg3loc.research.ui_skill_universe import UiSkillOccurrence, UiSkillProvider


class UiSkillRuntimeReconcileTests(unittest.TestCase):
    @staticmethod
    def _definition(
        ident: str,
        name: str,
        *,
        using: str = "",
        provider: str = "Shared.pak::Public/Shared/Stats/Generated/Data/Passive.txt",
        fields: dict[str, str] | None = None,
    ) -> Definition:
        return Definition(
            id=ident,
            name=name,
            entity_type="PassiveData",
            using=using,
            fields=fields or {},
            provider=provider,
            internal_path=provider.split("::", 1)[1],
        )

    @staticmethod
    def _occurrence(uid: str, entity_name: str, *, provider: str) -> UiSkillOccurrence:
        package, internal_path = provider.split("::", 1)
        return UiSkillOccurrence(
            uid,
            provider,
            package,
            internal_path,
            (),
            (),
            "PassiveData",
            entity_name,
            "DisplayName",
        )

    def test_aw_support_boundary_is_semantic_not_history_list(self) -> None:
        self.assertTrue(
            is_aw_support_provider(
                "Gustav.pak",
                "Public/Gustav/Stats/Generated/Data/Passive.txt",
            )
        )
        self.assertTrue(
            is_aw_support_provider(
                "Gustav.pak",
                "Public/Honour/Stats/Generated/Data/Spell_Projectile.txt",
            )
        )
        self.assertTrue(
            is_aw_support_provider(
                "GustavX.pak",
                "Public/PhotoMode/Stats/Generated/Data/Data.txt",
            )
        )
        self.assertTrue(
            is_aw_support_provider(
                "Shared.pak",
                "Public/SharedDev/Stats/Generated/Data/Character.txt",
            )
        )
        self.assertFalse(
            is_aw_support_provider(
                "Game.pak",
                "Public/Game/Stats/Generated/Data/Character.txt",
            )
        )
        self.assertFalse(
            is_aw_support_provider(
                "Shared.pak",
                "Public/Shared/Stats/Generated/Data/Nested/Character.txt",
            )
        )

    def test_stats_definition_parser_preserves_raw_fields(self) -> None:
        text = '''
new entry "Parent"
type "StatusData"
data "DisplayName" "h11111111g1111g1111g1111g111111111111;1"
data "Description" "raw value"
new entry "Child"
type "StatusData"
using "Parent"
data "Description" "override"
'''
        definitions = parse_stats_definitions(
            text,
            provider="Shared.pak::Public/Shared/Stats/Generated/Data/Status_TEST.txt",
            internal_path="Public/Shared/Stats/Generated/Data/Status_TEST.txt",
        )
        self.assertEqual(2, len(definitions))
        self.assertEqual("Parent", definitions[0].name)
        self.assertEqual("", definitions[0].using)
        self.assertEqual("raw value", definitions[0].fields["Description"])
        self.assertEqual("Parent", definitions[1].using)
        self.assertEqual("override", definitions[1].fields["Description"])

    def test_module_meta_parser_extracts_sibling_dependencies_and_skips_conflicts(self) -> None:
        text = '''
<save><region id="Config"><node id="root"><children>
  <node id="ModuleInfo">
    <attribute id="Folder" value="GustavDev" />
    <attribute id="UUID" value="uuid-gustavdev" />
  </node>
  <node id="Dependencies"><children>
    <node id="ModuleShortDesc"><attribute id="UUID" value="uuid-gustav" /></node>
  </children></node>
  <node id="Conflicts"><children>
    <node id="ModuleShortDesc"><attribute id="UUID" value="uuid-ignore" /></node>
  </children></node>
</children></node></region></save>
'''
        info, dependencies = parse_module_meta(text, expected_folder="GustavDev")
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual("GustavDev", info.folder)
        self.assertEqual("uuid-gustavdev", info.uuid)
        self.assertEqual(("uuid-gustav",), dependencies)

    def test_module_meta_parser_ignores_module_descriptions_outside_dependencies(self) -> None:
        text = '''
<save><region id="Config"><node id="root"><children>
  <node id="ModuleInfo">
    <attribute id="Folder" value="TestModule" />
    <attribute id="UUID" value="module-uuid" />
  </node>
  <node id="Dependencies"><children>
    <node id="ModuleShortDesc"><attribute id="UUID" value="real-dependency" /></node>
  </children></node>
  <node id="OtherSection"><children>
    <node id="ModuleShortDesc"><attribute id="UUID" value="not-a-dependency" /></node>
  </children></node>
  <node id="ConflictDependencies"><children>
    <node id="ModuleShortDesc"><attribute id="UUID" value="conflict-dependency" /></node>
  </children></node>
</children></node></region></save>
'''
        info, dependencies = parse_module_meta(text, expected_folder="TestModule")
        self.assertIsNotNone(info)
        self.assertEqual(("real-dependency",), dependencies)

    def test_package_layer_hold_is_limited_to_cclib_collision_family(self) -> None:
        cclib_path = "Public/Game/GUI/Library/CCLib_c.xaml"
        mod_path = "Public/Game/GUI/Pages/ModBrowser_c.xaml"
        providers = [
            UiSkillProvider("Game.pak", cclib_path, "XAML", "Game", (), (), (), collision=True),
            UiSkillProvider("Patch8_HotFix9.pak", cclib_path, "XAML", "Game", (), (), (), collision=True),
            UiSkillProvider("Game.pak", mod_path, "XAML", "Game", (), (), (), collision=True),
            UiSkillProvider("Patch8_HotFix9.pak", mod_path, "XAML", "Game", (), (), (), collision=True),
        ]
        occurrences = [
            UiSkillOccurrence("uid-common", providers[0].identity, "Game.pak", cclib_path, (), (), "X", "E", "F"),
            UiSkillOccurrence("uid-common", providers[1].identity, "Patch8_HotFix9.pak", cclib_path, (), (), "X", "E", "F"),
            UiSkillOccurrence("uid-cclib-patch", providers[1].identity, "Patch8_HotFix9.pak", cclib_path, (), (), "X", "E", "F"),
            UiSkillOccurrence("uid-mod-game", providers[2].identity, "Game.pak", mod_path, (), (), "X", "E", "F"),
            UiSkillOccurrence("uid-mod-patch", providers[3].identity, "Patch8_HotFix9.pak", mod_path, (), (), "X", "E", "F"),
        ]
        self.assertEqual({"uid-cclib-patch"}, _package_layer_hold_uids(occurrences, providers))

    def test_related_uids_follow_resolved_chain_to_unresolved_parent_edge(self) -> None:
        provider = "Shared.pak::Public/Shared/Stats/Generated/Data/Passive.txt"
        definitions = (
            self._definition("child", "Child", using="ParentA", provider=provider),
            self._definition("parent-a", "ParentA", using="ParentB", provider=provider),
        )
        related = _related_content_uids_by_edge(
            (self._occurrence("uid-child", "Child", provider=provider),),
            definitions,
        )
        self.assertNotIn("child", related)
        self.assertEqual(frozenset({"uid-child"}), related["parent-a"])

    def test_related_uids_deduplicate_same_uid_on_same_chain(self) -> None:
        provider = "Shared.pak::Public/Shared/Stats/Generated/Data/Passive.txt"
        definitions = (self._definition("child", "Child", using="Missing", provider=provider),)
        occurrence = self._occurrence("uid-repeat", "Child", provider=provider)
        related = _related_content_uids_by_edge((occurrence, occurrence), definitions)
        self.assertEqual(frozenset({"uid-repeat"}), related["child"])

    def test_related_uid_may_reach_two_unresolved_edges(self) -> None:
        provider = "Shared.pak::Public/Shared/Stats/Generated/Data/Passive.txt"
        definitions = (
            self._definition("child-a", "ChildA", using="MissingA", provider=provider),
            self._definition("child-b", "ChildB", using="MissingB", provider=provider),
        )
        related = _related_content_uids_by_edge(
            (
                self._occurrence("uid-shared", "ChildA", provider=provider),
                self._occurrence("uid-shared", "ChildB", provider=provider),
            ),
            definitions,
        )
        self.assertEqual(frozenset({"uid-shared"}), related["child-a"])
        self.assertEqual(frozenset({"uid-shared"}), related["child-b"])

    def test_related_uid_continues_past_self_name_unresolved_edge(self) -> None:
        provider = "Shared.pak::Public/Shared/Stats/Generated/Data/Passive.txt"
        uid = "h44444444g4444g4444g4444g444444444444"
        definitions = (
            self._definition(
                "same-new",
                "Same",
                using="Same",
                provider=provider,
                fields={"DisplayName": uid},
            ),
            self._definition(
                "same-old",
                "Same",
                using="Missing",
                provider=provider,
                fields={"Description": "older"},
            ),
        )
        related = _related_content_uids_by_edge(
            (self._occurrence(uid, "Same", provider=provider),),
            definitions,
        )
        self.assertEqual(frozenset({uid}), related["same-new"])
        self.assertEqual(frozenset({uid}), related["same-old"])

    def test_related_uids_do_not_include_candidate_definition_field_uids(self) -> None:
        provider = "Shared.pak::Public/Shared/Stats/Generated/Data/Passive.txt"
        definitions = (
            self._definition("child", "Child", using="Parent", provider=provider),
            self._definition(
                "parent-a",
                "Parent",
                provider=provider,
                fields={"DisplayName": "h11111111g1111g1111g1111g111111111111"},
            ),
            self._definition(
                "parent-b",
                "Parent",
                provider=provider,
                fields={"Description": "h22222222g2222g2222g2222g222222222222"},
            ),
        )
        related = _related_content_uids_by_edge(
            (self._occurrence("uid-direct", "Child", provider=provider),),
            definitions,
        )
        self.assertEqual(frozenset({"uid-direct"}), related["child"])


if __name__ == "__main__":
    unittest.main()
