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
    """Parse Larian stats text grammar and extract localization handle mappings."""
    current_entry: str | None = None
    current_type: str = ""
    current_using: str = ""

    lines = text.splitlines()
    for line_idx, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue

        entry_m = RE_ENTRY.match(line)
        if entry_m:
            current_entry = entry_m.group("name")
            current_type = ""
            current_using = ""
            continue

        if not current_entry:
            continue

        type_m = RE_TYPE.match(line)
        if type_m:
            current_type = type_m.group("type")
            continue

        using_m = RE_USING.match(line)
        if using_m:
            current_using = using_m.group("using")
            continue

        data_m = RE_DATA.match(line)
        if data_m:
            field_name = data_m.group("field")
            field_val = data_m.group("value")

            if not all_fields and field_name not in STAT_LOCALIZATION_FIELDS:
                # Still check if value matches handle pattern directly
                if not HANDLE_PATTERN.search(field_val):
                    continue

            for match in HANDLE_PATTERN.finditer(field_val):
                uid = match.group("uid")
                ver = match.group("ver") or ""

                evidence = ResearchEvidence(
                    sourceRole="StatsRecordField",
                    resourcePath=resource_path,
                    evidenceType="StatsDefinition",
                    ruleId=RULE_STAT_DIRECT,
                    properties={
                        "entryName": current_entry,
                        "entryType": current_type,
                        "using": current_using,
                        "fieldName": field_name,
                        "line": line_idx,
                        "provider": provider,
                    }
                )

                yield ResearchMapping(
                    contentUid=uid,
                    mappingType="stat-reference",
                    classification="StatLocalizationReference",
                    evidence=[evidence],
                    version=ver,
                    metadata={
                        "entryName": current_entry,
                        "fieldName": field_name,
                    }
                )