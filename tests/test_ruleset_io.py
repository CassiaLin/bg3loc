from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bg3loc.ruleset_io import load_ruleset


class TestRulesetIo(unittest.TestCase):
    def write_ruleset(self, root: Path, payload: dict[str, object]) -> Path:
        path = root / "ruleset.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def base_payload(self) -> dict[str, object]:
        return {
            "version": "rules-v1",
            "sourceLocale": "English",
            "targetLocale": "ChineseTraditional",
            "commonRules": ["Preserve meaning."],
            "categoryRules": {
                "bark": ["Keep bark lines concise."],
            },
        }

    def test_required_top_level_fields(self) -> None:
        required = (
            "version",
            "sourceLocale",
            "targetLocale",
            "commonRules",
            "categoryRules",
        )

        for field in required:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as td:
                    payload = self.base_payload()
                    del payload[field]
                    path = self.write_ruleset(Path(td), payload)
                    with self.assertRaises(RuntimeError):
                        load_ruleset(path)

    def test_empty_common_rules_is_allowed_when_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            payload = self.base_payload()
            payload["commonRules"] = []
            ruleset = load_ruleset(self.write_ruleset(Path(td), payload))
            self.assertEqual(ruleset.common_rules, ())


if __name__ == "__main__":
    unittest.main()
