from __future__ import annotations

import unittest

from bg3loc.protected_syntax import (
    extract_protected_tokens,
    has_valid_lstag_structure,
    validate_lstag_structure,
    validate_protected_syntax,
)


class ProtectedSyntaxTests(unittest.TestCase):
    def test_localized_lstag_payload_attributes_and_square_brackets_are_valid(self) -> None:
        required = extract_protected_tokens(
            'Use <LSTag Type="ActionResource" Tooltip="BonusActionPoint">bonus action</LSTag> [PAUSE] {Player}'
        )
        candidate = '使用<LSTag Tooltip="Bonus_Action">附贈動作</LSTag>[停頓] {Player}'
        self.assertEqual(validate_protected_syntax(required, candidate), [])

    def test_missing_and_added_exact_runtime_placeholders_fail(self) -> None:
        missing = validate_protected_syntax(["{Player}", "%2$s"], "您好 {Player}")
        added = validate_protected_syntax(["{Player}"], "您好 {Player} %s")
        self.assertEqual([issue.kind for issue in missing], ["missing"])
        self.assertEqual([issue.kind for issue in added], ["added"])

    def test_lstag_missing_close_and_truncated_tag_fail(self) -> None:
        self.assertIn("unclosed LSTag", validate_lstag_structure('<LSTag Tooltip="Action">文字'))
        self.assertIn("malformed LSTag", validate_lstag_structure('<LSTag Tooltip="Action" 文字'))
        self.assertIn("unexpected closing LSTag", validate_lstag_structure("文字</LSTag>"))

    def test_evidence_observed_non_xml_attribute_serialization_is_structurally_valid(self) -> None:
        self.assertEqual(
            validate_lstag_structure('<LSTag Type="Status" Tooltip=POISON_CONDITION">文字</LSTag>'),
            [],
        )
        self.assertEqual(validate_lstag_structure(r'<LSTag Type=\"Image\" Info=\"Death\"/>死亡'), [])

    def test_source_only_equivalent_preserves_structure_and_rejects_dropped_close(self) -> None:
        source_only = '<br><LSTag Type="Spell" Tooltip="Target_Web_Spider">Web</LSTag>'
        required = extract_protected_tokens(source_only)
        preserved = '<br><LSTag Type="Spell" Tooltip="Target_Web_Spider">蛛網</LSTag>'
        dropped_close = '<br><LSTag Type="Spell" Tooltip="Target_Web_Spider">蛛網'
        self.assertEqual(validate_protected_syntax(required, preserved), [])
        self.assertEqual([issue.kind for issue in validate_protected_syntax(required, dropped_close)], ["markup"])

    def test_lstag_presence_helper_requires_a_valid_envelope(self) -> None:
        self.assertTrue(has_valid_lstag_structure('<LSTag Tooltip="A">文字</LSTag>'))
        self.assertTrue(has_valid_lstag_structure('<LSTag Type="Image" Info="Icon"/>'))
        self.assertFalse(has_valid_lstag_structure("文字"))
        self.assertFalse(has_valid_lstag_structure('<LSTag Tooltip="A">文字'))


if __name__ == "__main__":
    unittest.main()
