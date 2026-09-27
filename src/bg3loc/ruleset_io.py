from __future__ import annotations

import json
from pathlib import Path

from bg3loc.prompt_assembly import GlossaryEntry, TranslationRuleSet


def load_ruleset(path: str | Path) -> TranslationRuleSet:
    ruleset_path = Path(path)
    if not ruleset_path.is_file():
        raise RuntimeError(f"ruleset not found: {ruleset_path}")

    with ruleset_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, dict):
        raise RuntimeError("ruleset root must be a JSON object")

    version = str(payload.get("version", "")).strip()
    if not version:
        raise RuntimeError("ruleset.version is required")

    source_locale = str(payload.get("sourceLocale", "")).strip()
    target_locale = str(payload.get("targetLocale", "")).strip()
    if not source_locale:
        raise RuntimeError("ruleset.sourceLocale is required")
    if not target_locale:
        raise RuntimeError("ruleset.targetLocale is required")

    if "commonRules" not in payload:
        raise RuntimeError("ruleset.commonRules is required")
    common_raw = payload["commonRules"]
    if not isinstance(common_raw, list) or not all(isinstance(item, str) for item in common_raw):
        raise RuntimeError("ruleset.commonRules must be a string array")

    category_raw = payload.get("categoryRules")
    if not isinstance(category_raw, dict) or not category_raw:
        raise RuntimeError("ruleset.categoryRules must be a non-empty object")

    category_rules: dict[str, tuple[str, ...]] = {}
    for category, rules in category_raw.items():
        if not isinstance(category, str) or not category.strip():
            raise RuntimeError("ruleset category names must be non-empty strings")
        if not isinstance(rules, list) or not all(isinstance(item, str) for item in rules):
            raise RuntimeError(f"ruleset.categoryRules.{category} must be a string array")
        category_rules[category] = tuple(rules)

    glossary_raw = payload.get("glossary", [])
    if not isinstance(glossary_raw, list):
        raise RuntimeError("ruleset.glossary must be an array")

    glossary: list[GlossaryEntry] = []
    for index, item in enumerate(glossary_raw):
        if not isinstance(item, dict):
            raise RuntimeError(f"ruleset.glossary[{index}] must be an object")
        source = str(item.get("source", ""))
        target = str(item.get("target", ""))
        if not source or not target:
            raise RuntimeError(f"ruleset.glossary[{index}] requires source and target")
        glossary.append(GlossaryEntry(source=source, target=target))

    return TranslationRuleSet(
        version=version,
        common_rules=tuple(common_raw),
        category_rules=category_rules,
        source_locale=source_locale,
        target_locale=target_locale,
        glossary=tuple(glossary),
    )
