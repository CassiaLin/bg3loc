from __future__ import annotations

import inspect
import re
import unittest

from bg3loc.research.ui_skill_aq import (
    ReuseClassification,
    accepted_context_coverage,
    derive_aq_boundary,
    derive_aq_resource_referenced,
    derive_reuse_conflict_boundary,
)


class UiSkillAqTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = {
            "shared-single": "Exact",
            "only-single": "Exact",
            "shared-consensus-a": "Same",
            "shared-consensus-b": "Same",
            "only-consensus": "Same",
            "shared-conflict-a": "Conflict",
            "shared-conflict-b": "Conflict",
            "only-conflict": "Conflict",
            "only-none": "None",
            "only-case": "exact",
            "only-space": "Exact ",
        }
        self.target = {
            "shared-single": "精確",
            "shared-consensus-a": "相同",
            "shared-consensus-b": "相同",
            "shared-conflict-a": "甲",
            "shared-conflict-b": "乙",
        }

    def test_exact_reuse_classifications_without_normalization(self) -> None:
        result = derive_reuse_conflict_boundary(self.source, self.target)
        by_uid = {row.content_uid: row for row in result.rows}
        self.assertEqual(by_uid["only-single"].classification, ReuseClassification.EXACT_SINGLE)
        self.assertEqual(by_uid["only-consensus"].classification, ReuseClassification.EXACT_CONSENSUS)
        self.assertEqual(by_uid["only-conflict"].classification, ReuseClassification.EXACT_CONFLICT)
        self.assertEqual(by_uid["only-none"].classification, ReuseClassification.NO_EXACT_CANDIDATE)
        self.assertEqual(by_uid["only-case"].classification, ReuseClassification.NO_EXACT_CANDIDATE)
        self.assertEqual(by_uid["only-space"].classification, ReuseClassification.NO_EXACT_CANDIDATE)
        self.assertEqual(result.exact_conflict_uids, frozenset({"only-conflict"}))

    def test_coverage_subtraction_and_outside_rejection(self) -> None:
        coverage = accepted_context_coverage(
            shared_uids={"a"}, passive_uids={"b"}, dialog_bark_uids={"c"}, quest_uids={"d"}
        )
        self.assertEqual(coverage, frozenset({"a", "b", "c", "d"}))
        self.assertEqual(derive_aq_boundary({"a", "b", "c", "d", "e"}, coverage), frozenset({"e"}))
        with self.assertRaises(ValueError):
            derive_aq_boundary({"a"}, {"outside"})

    def test_aq_resource_intersection(self) -> None:
        self.assertEqual(
            derive_aq_resource_referenced({"aq-a", "aq-b"}, {"general", "aq-b"}),
            frozenset({"aq-b"}),
        )

    def test_production_module_has_no_historical_uid_membership(self) -> None:
        import bg3loc.research.ui_skill_aq as module

        source = inspect.getsource(module)
        uid_literal = re.compile(r'["\']h[0-9a-f]{8}g[0-9a-f]{4}g[0-9a-f]{4}g[0-9a-f]{4}g[0-9a-f]{12}["\']', re.I)
        self.assertEqual(uid_literal.findall(source), [])


if __name__ == "__main__":
    unittest.main()
