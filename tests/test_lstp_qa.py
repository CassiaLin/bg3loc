from __future__ import annotations

import unittest

from bg3loc.qa import (
    ISSUE_CATEGORY_RULE_MISSING,
    ISSUE_LENGTH_RATIO_SUSPICIOUS,
    ISSUE_LSTAG_MALFORMED,
    ISSUE_OUTPUT_EMPTY,
    ISSUE_PROTECTED_TOKEN_ADDED,
    ISSUE_PROTECTED_TOKEN_MISSING,
    ISSUE_SOURCE_EQUALS_TARGET,
    QA_ROUTE_FAIL,
    QA_ROUTE_PASS,
    QA_ROUTE_RETRY,
    QA_ROUTE_REVIEW,
    QaInput,
    evaluate_translation,
)


class TestTranslationQa(unittest.TestCase):
    def test_clean_translation_passes(self) -> None:
        result = evaluate_translation(
            QaInput(
                content_uid="uid-a",
                source_text="Hello {PLAYER}",
                translated_text="你好 {PLAYER}",
                primary_category="dialogue_general",
                required_protected_tokens=("{PLAYER}",),
            )
        )

        self.assertEqual(result.route, QA_ROUTE_PASS)
        self.assertEqual(result.issues, ())

    def test_empty_output_retries(self) -> None:
        result = evaluate_translation(
            QaInput(
                content_uid="uid-a",
                source_text="Hello",
                translated_text="   ",
                primary_category="dialogue_general",
                required_protected_tokens=(),
            )
        )

        self.assertEqual(result.route, QA_ROUTE_RETRY)
        self.assertEqual(
            [issue.issue_code for issue in result.issues],
            [ISSUE_OUTPUT_EMPTY],
        )

    def test_missing_protected_token_retries(self) -> None:
        result = evaluate_translation(
            QaInput(
                content_uid="uid-a",
                source_text="Hello {PLAYER} %s",
                translated_text="你好 {PLAYER}",
                primary_category="dialogue_general",
                required_protected_tokens=("{PLAYER}", "%s"),
            )
        )

        self.assertEqual(result.route, QA_ROUTE_RETRY)
        self.assertEqual(
            [issue.issue_code for issue in result.issues],
            [ISSUE_PROTECTED_TOKEN_MISSING],
        )

    def test_added_protected_token_retries(self) -> None:
        result = evaluate_translation(
            QaInput(
                content_uid="uid-a",
                source_text="Hello {PLAYER}",
                translated_text="你好 {PLAYER} %s",
                primary_category="dialogue_general",
                required_protected_tokens=("{PLAYER}",),
            )
        )

        self.assertEqual(result.route, QA_ROUTE_RETRY)
        self.assertEqual(
            [issue.issue_code for issue in result.issues],
            [ISSUE_PROTECTED_TOKEN_ADDED],
        )

    def test_malformed_lstag_retries(self) -> None:
        result = evaluate_translation(
            QaInput(
                content_uid="uid-a",
                source_text="<LSTag Type=\"X\">Hello</LSTag>",
                translated_text="<LSTag Type=\"X\">你好",
                primary_category="dialogue_general",
                required_protected_tokens=(),
            )
        )

        self.assertEqual(result.route, QA_ROUTE_RETRY)
        self.assertEqual(
            [issue.issue_code for issue in result.issues],
            [ISSUE_LSTAG_MALFORMED],
        )

    def test_source_equals_target_reviews_language_bearing_text(self) -> None:
        result = evaluate_translation(
            QaInput(
                content_uid="uid-a",
                source_text="Open the ancient gate",
                translated_text="Open the ancient gate",
                primary_category="dialogue_general",
                required_protected_tokens=(),
            )
        )

        self.assertEqual(result.route, QA_ROUTE_REVIEW)
        self.assertIn(
            ISSUE_SOURCE_EQUALS_TARGET,
            [issue.issue_code for issue in result.issues],
        )

    def test_language_neutral_equal_text_does_not_review(self) -> None:
        result = evaluate_translation(
            QaInput(
                content_uid="uid-a",
                source_text="12345",
                translated_text="12345",
                primary_category="ui",
                required_protected_tokens=(),
            )
        )

        self.assertEqual(result.route, QA_ROUTE_PASS)

    def test_locale_specific_untranslated_heuristic_is_not_in_core(self) -> None:
        result = evaluate_translation(
            QaInput(
                content_uid="uid-a",
                source_text="Find the Ancient Gate before sunset",
                translated_text="在 sunset 前找到 Ancient Gate",
                primary_category="quest",
                required_protected_tokens=(),
            )
        )

        self.assertEqual(result.route, QA_ROUTE_PASS)

    def test_single_english_name_does_not_trigger_untranslated_review(self) -> None:
        result = evaluate_translation(
            QaInput(
                content_uid="uid-a",
                source_text="Talk to Astarion",
                translated_text="與 Astarion 交談",
                primary_category="quest",
                required_protected_tokens=(),
            )
        )

        self.assertEqual(result.route, QA_ROUTE_PASS)

    def test_extreme_length_ratio_reviews(self) -> None:
        result = evaluate_translation(
            QaInput(
                content_uid="uid-a",
                source_text="This sentence is deliberately long enough for ratio checking.",
                translated_text="短",
                primary_category="dialogue_general",
                required_protected_tokens=(),
            )
        )

        self.assertEqual(result.route, QA_ROUTE_REVIEW)
        self.assertIn(
            ISSUE_LENGTH_RATIO_SUSPICIOUS,
            [issue.issue_code for issue in result.issues],
        )

    def test_retry_has_priority_over_review(self) -> None:
        result = evaluate_translation(
            QaInput(
                content_uid="uid-a",
                source_text="Hello {PLAYER} from Ancient Gate",
                translated_text="Hello Ancient Gate",
                primary_category="dialogue_general",
                required_protected_tokens=("{PLAYER}",),
            )
        )

        self.assertEqual(result.route, QA_ROUTE_RETRY)
        codes = [issue.issue_code for issue in result.issues]
        self.assertIn(ISSUE_PROTECTED_TOKEN_MISSING, codes)

    def test_ui_uses_category_specific_length_policy(self) -> None:
        result = evaluate_translation(
            QaInput(
                content_uid="uid-ui",
                source_text="Open inventory",
                translated_text="這是一段刻意放大的介面文字，用來觸發長度比例檢查，而且會繼續加長到明顯超過原文字串三倍以上的測試內容。",
                primary_category="ui",
                required_protected_tokens=(),
            )
        )

        self.assertEqual(result.route, QA_ROUTE_REVIEW)
        self.assertIn(
            ISSUE_LENGTH_RATIO_SUSPICIOUS,
            [issue.issue_code for issue in result.issues],
        )

    def test_same_text_can_pass_dialogue_ratio_but_review_in_ui(self) -> None:
        source = "Open inventory"
        target = "這是一段刻意加長的介面文字，而且會繼續增加內容直到明顯超過來源字串三倍以上，以驗證不同 category 的長度規則。"

        ui = evaluate_translation(
            QaInput(
                content_uid="uid-ui",
                source_text=source,
                translated_text=target,
                primary_category="ui",
                required_protected_tokens=(),
            )
        )
        dialogue = evaluate_translation(
            QaInput(
                content_uid="uid-dialogue",
                source_text=source,
                translated_text=target,
                primary_category="dialogue_general",
                required_protected_tokens=(),
            )
        )

        self.assertEqual(ui.route, QA_ROUTE_REVIEW)
        self.assertEqual(dialogue.route, QA_ROUTE_PASS)

    def test_unknown_category_fails_closed(self) -> None:
        result = evaluate_translation(
            QaInput(
                content_uid="uid-unknown",
                source_text="Hello",
                translated_text="你好",
                primary_category="not-a-real-category",
                required_protected_tokens=(),
            )
        )

        self.assertEqual(result.route, QA_ROUTE_FAIL)
        self.assertEqual(
            [issue.issue_code for issue in result.issues],
            [ISSUE_CATEGORY_RULE_MISSING],
        )

    def test_all_accepted_categories_have_registered_policy(self) -> None:
        categories = (
            "dialogue_general",
            "dialogue_story",
            "quest",
            "bark",
            "ui",
            "skill_spell",
            "item",
            "book_lore",
            "character_world",
            "system_message",
            "tutorial",
            "other",
        )

        for category in categories:
            with self.subTest(category=category):
                result = evaluate_translation(
                    QaInput(
                        content_uid=f"uid-{category}",
                        source_text="Hello",
                        translated_text="你好",
                        primary_category=category,
                        required_protected_tokens=(),
                    )
                )
                self.assertNotEqual(result.route, QA_ROUTE_FAIL)

    def test_qa_hash_is_deterministic_and_changes_with_output(self) -> None:
        base = QaInput(
            content_uid="uid-a",
            source_text="Hello",
            translated_text="你好",
            primary_category="dialogue_general",
            required_protected_tokens=(),
        )
        same = evaluate_translation(base)
        repeat = evaluate_translation(base)
        changed = evaluate_translation(
            QaInput(
                content_uid="uid-a",
                source_text="Hello",
                translated_text="哈囉",
                primary_category="dialogue_general",
                required_protected_tokens=(),
            )
        )

        self.assertEqual(same.qa_input_hash, repeat.qa_input_hash)
        self.assertNotEqual(same.qa_input_hash, changed.qa_input_hash)


if __name__ == "__main__":
    unittest.main()
