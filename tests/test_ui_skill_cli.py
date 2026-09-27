from __future__ import annotations

import unittest

from bg3loc.cli import build_parser


class UiSkillCliTests(unittest.TestCase):
    def test_prepare_parser_wires_universe_and_extract(self) -> None:
        args = build_parser().parse_args([
            "review", "ui-skill", "prepare",
            "--universe", "ui-skill-universe.csv",
            "--extract", "extract-manifest.json",
        ])
        self.assertEqual(args.review_domain, "ui-skill")
        self.assertEqual(args.review_action, "prepare")
        self.assertEqual(args.universe, "ui-skill-universe.csv")
        self.assertEqual(args.extract, "extract-manifest.json")

    def test_validate_parser_uses_ui_skill_domain(self) -> None:
        args = build_parser().parse_args([
            "review", "ui-skill", "validate",
            "--input", "ui-skill-review-pass1.csv",
        ])
        self.assertEqual(args.review_domain, "ui-skill")
        self.assertEqual(args.review_action, "validate")
        self.assertEqual(args.input, "ui-skill-review-pass1.csv")


if __name__ == "__main__":
    unittest.main()
