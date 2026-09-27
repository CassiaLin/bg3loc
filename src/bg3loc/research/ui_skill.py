from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterator

from bg3loc.research.model import HANDLE_PATTERN, ResearchEvidence, ResearchMapping

RULE_UI_SKILL_PROVIDER = "BG3-UI-SKILL-PROVIDER-INHERITANCE"

# Known domain patterns for provider files
DOMAIN_KEYWORDS: dict[str, str] = {
    "ability": "AbilityOrSkill",
    "spell": "AbilityOrSkill",
    "status": "AbilityOrSkill",
    "passive": "AbilityOrSkill",
    "item": "ItemsAndEquipment",
    "armor": "ItemsAndEquipment",
    "weapon": "ItemsAndEquipment",
    "tutorial": "TutorialAndSystem",
    "system": "TutorialAndSystem",
    "ui": "UserInterface",
    "hud": "UserInterface",
    "tooltip": "UserInterface",
}


def classify_domain_by_path(path: str) -> str:
    """Infer domain candidate from internal path."""
    lower = path.lower()
    for kw, domain in DOMAIN_KEYWORDS.items():
        if kw in lower:
            return domain
    return "GenericUiSkill"


@dataclass(slots=True)
class UiSkillProvider:
    providerIdentity: str
    internalPath: str
    resourceFormat: str
    domain: str
    entities: dict[str, str] = field(default_factory=dict)  # name -> using
    handles: list[str] = field(default_factory=list)


def parse_ui_skill_xml(
    xml_text: str,
    *,
    resource_path: str = "",
    provider: str = ""
) -> Iterator[ResearchMapping]:
    """Parse XAML or LSX UI/skill file and extract candidate localization mappings."""
    domain = classify_domain_by_path(resource_path)

    for m in HANDLE_PATTERN.finditer(xml_text):
        uid = m.group("uid")
        ver = m.group("ver") or ""

        evidence = ResearchEvidence(
            sourceRole="UiSkillResourceOccurrence",
            resourcePath=resource_path,
            evidenceType="UiSkillProvider",
            ruleId=RULE_UI_SKILL_PROVIDER,
            properties={
                "provider": provider,
                "domain": domain,
            }
        )

        yield ResearchMapping(
            contentUid=uid,
            mappingType="ui-skill-candidate",
            classification=domain,
            evidence=[evidence],
            version=ver,
            reviewRequired=True,
            metadata={
                "domain": domain,
                "provider": provider,
            }
        )