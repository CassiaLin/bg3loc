from __future__ import annotations

import unittest

from bg3loc.research.ui_skill_universe import UiSkillOccurrence, classify_workstream


class UiSkillWorkstreamHistoryTests(unittest.TestCase):
    @staticmethod
    def _occurrence(*, domains=(), families=(), entity_type="Document", provider="Game.pak::Public/Game/GUI/Test.xaml") -> UiSkillOccurrence:
        return UiSkillOccurrence(
            content_uid="h11111111g1111g1111g1111g111111111111",
            provider=provider,
            package="Game.pak",
            internal_path="Public/Game/GUI/Test.xaml",
            source_families=tuple(families),
            domains=tuple(domains),
            entity_type=entity_type,
            entity_name="Test",
            field_name="Text",
        )

    def test_item_substring_does_not_preempt_user_interface(self) -> None:
        occurrence = self._occurrence(
            domains=("UI.Unknown",),
            families=("UI/GUI definitions",),
            entity_type="ItemTooltipWidget",
        )
        self.assertEqual("UserInterface", classify_workstream((occurrence,)))

    def test_standalone_item_keeps_items_equipment_priority(self) -> None:
        occurrence = self._occurrence(
            domains=("UI.Unknown",),
            families=("UI/GUI definitions",),
            entity_type="Item",
        )
        self.assertEqual("ItemsEquipment", classify_workstream((occurrence,)))

    def test_gui_substring_does_not_create_user_interface_match(self) -> None:
        occurrence = self._occurrence(
            provider="Game.pak::Public/Game/Guidance/Test.txt",
            entity_type="GuidanceDocument",
        )
        self.assertEqual("OtherMultiDomain", classify_workstream((occurrence,)))


if __name__ == "__main__":
    unittest.main()
