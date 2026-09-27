from __future__ import annotations

import re
from typing import Iterator
import xml.etree.ElementTree as ET

from bg3loc.research.model import HANDLE_PATTERN, ResearchEvidence, ResearchMapping

RULE_QUEST_JOURNAL = "BG3-QUEST-JOURNAL-EVIDENCE"

# Roles mapped deterministically from element/attribute names and paths
QUEST_TITLE_KEYWORDS = {"QuestTitle", "JournalTitle", "Title"}
QUEST_DESC_KEYWORDS = {"QuestDescription", "JournalDescription", "Description"}


def classify_quest_field_role(field_name: str, node_tags: list[str]) -> str:
    """Classify field role into QuestTitle, QuestDescription, or Unknown."""
    terms = set(node_tags + [field_name])
    if terms & QUEST_TITLE_KEYWORDS:
        return "QuestTitle"
    if terms & QUEST_DESC_KEYWORDS:
        return "QuestDescription"
    return "QuestField"


def parse_quest_xml(
    xml_text: str,
    *,
    resource_path: str = "",
    pak_name: str = "Gustav.pak"
) -> Iterator[ResearchMapping]:
    """Parse Larian quest XML/LSX definition and yield quest mappings."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return

    # Element index remains deterministic for a converted resource. In addition,
    # retain the nearest enclosing node identity so batching can keep fields from the
    # same journal entity together without treating the index itself as content identity.
    parent_map = {child: parent for parent in root.iter() for child in list(parent)}
    node_ordinals = {
        elem: index
        for index, elem in enumerate(
            (candidate for candidate in root.iter() if candidate.tag.rsplit("}", 1)[-1] == "node"),
            start=1,
        )
    }

    def enclosing_entity_id(elem: ET.Element) -> str:
        current: ET.Element | None = elem
        while current is not None:
            if current.tag.rsplit("}", 1)[-1] == "node":
                direct_identity = next(
                    (
                        child.attrib.get("value", "") or child.attrib.get("handle", "")
                        for child in list(current)
                        if child.tag.rsplit("}", 1)[-1] == "attribute"
                        and child.attrib.get("id", "") in {"UUID", "MapKey", "Name", "ID", "Guid", "GUID"}
                        and (child.attrib.get("value") or child.attrib.get("handle"))
                    ),
                    "",
                )
                if direct_identity:
                    return direct_identity
                return f"{current.attrib.get('id', 'node')}#{node_ordinals.get(current, 0)}"
            current = parent_map.get(current)
        return ""

    for element_index, elem in enumerate(root.iter(), start=1):
        handle = elem.attrib.get("handle") or ""
        field_id = elem.attrib.get("id") or elem.attrib.get("name") or elem.tag
        ver = elem.attrib.get("version") or ""

        if not handle:
            val = elem.attrib.get("value") or elem.text or ""
            m = HANDLE_PATTERN.search(val)
            if m:
                handle = m.group("uid")
                ver = ver or m.group("ver") or ""

        m = HANDLE_PATTERN.search(handle)
        if not m:
            continue

        uid = m.group("uid")
        ver = ver or m.group("ver") or ""
        role = classify_quest_field_role(field_id, [elem.tag])
        entity_id = enclosing_entity_id(elem)

        evidence = ResearchEvidence(
            sourceRole="QuestJournalField",
            resourcePath=resource_path,
            evidenceType="QuestJournal",
            ruleId=RULE_QUEST_JOURNAL,
            properties={
                "fieldName": field_id,
                "fieldRole": role,
                "pakName": pak_name,
                "elementIndex": element_index,
                "entityId": entity_id,
            }
        )

        yield ResearchMapping(
            contentUid=uid,
            mappingType="quest-journal",
            classification=role,
            evidence=[evidence],
            version=ver,
            reviewRequired=True,
            metadata={
                "questFieldRole": role,
                "fieldName": field_id,
                "elementIndex": element_index,
                "entityId": entity_id,
            }
        )


def filter_quest_context_candidates(
    quest_mappings: Iterator[ResearchMapping] | list[ResearchMapping],
    *,
    uncovered_target_uids: set[str] | None = None
) -> list[ResearchMapping]:
    """
    Filter raw quest mappings into the deterministic Quest Context candidate set.

    Translation identity is ContentUid + role, while all matching game-derived
    occurrences are retained as evidence on that candidate. Historical counts
    (94 unique ContentUids / 96 occurrences) are comparison evidence only and do
    not control selection.
    """
    targets = uncovered_target_uids
    candidates_by_key: dict[tuple[str, str], ResearchMapping] = {}

    for mapping in quest_mappings:
        role = mapping.classification
        if role not in ("QuestTitle", "QuestDescription"):
            continue
        if targets is not None and mapping.contentUid not in targets:
            continue

        key = (mapping.contentUid, role)
        existing = candidates_by_key.get(key)
        if existing is None:
            existing = ResearchMapping(
                contentUid=mapping.contentUid,
                mappingType="quest-journal",
                classification=role,
                evidence=list(mapping.evidence),
                version=mapping.version,
                reviewRequired=True,
                metadata=dict(mapping.metadata),
            )
            existing.metadata["occurrenceCount"] = len(existing.evidence)
            candidates_by_key[key] = existing
            continue

        existing.evidence.extend(mapping.evidence)
        existing.metadata["occurrenceCount"] = len(existing.evidence)

    return list(candidates_by_key.values())
