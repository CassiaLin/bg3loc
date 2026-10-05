from __future__ import annotations

import re
from typing import Iterator

from bg3loc.research.model import HANDLE_PATTERN, ResearchEvidence, ResearchMapping

RULE_STAT_DIRECT = "BG3-STAT-DIRECT-LOCALIZATION-REFERENCE"

RE_ENTRY = re.compile(r'^\s*new\s+entry\s+"(?P<name>[^"]+)"', re.IGNORECASE)
RE_TYPE = re.compile(r'^\s*type\s+"(?P<type>[^"]*)"', re.IGNORECASE)
RE_USING = re.compile(r'^\s*using\s+"(?P<using>[^"]*)"', re.IGNORECASE)
RE_DATA = re.compile(r'^\s*data\s+"(?P<field>[^"]+)"\s+"(?P<value>.*)"', re.IGNORECASE)

# Known stats fields carrying localization handles
STAT_LOCALIZATION_FIELDS = {
    "DisplayName",
    "Description",
    "ExtraDescription",
    "ShortDescription",
    "Tooltip",
    "DisplayName_Male",
    "DisplayName_Female",
    "Description_Male",
    "Description_Female",
}


def parse_stats_text(
    text: str,
    *,
    resource_path: str = "",
    provider: str = "",
    all_fields: bool = False
) -> Iterator[ResearchMapping]:
    """Extract occurrences only after their complete stats entry has been read."""
    from bg3loc.research.structural_provenance import parse_structural_stats

    for definition in parse_structural_stats(text, resource_path=resource_path, package=provider):
        directives = definition.payload["directives"]
        entry_type = directives.get("type", [""])[-1]
        using = directives.get("using", [""])[-1]
        for occurrence in definition.occurrences:
            properties = {
                **definition.provenance(),
                "entryName": definition.entity_identity,
                "entryType": entry_type,
                "using": using,
                "fieldName": occurrence.field_name,
                "fieldRole": occurrence.field_role,
                "line": occurrence.location,
                "provider": provider,
            }
            evidence = ResearchEvidence(
                sourceRole="StatsRecordField", resourcePath=resource_path,
                evidenceType="StatsDefinition", ruleId=RULE_STAT_DIRECT,
                properties=properties,
            )
            yield ResearchMapping(
                contentUid=occurrence.content_uid, mappingType="stat-reference",
                classification="StatLocalizationReference", evidence=[evidence],
                version=occurrence.version,
                metadata={**definition.provenance(), "entryName": definition.entity_identity,
                          "fieldName": occurrence.field_name, "fieldRole": occurrence.field_role},
            )
