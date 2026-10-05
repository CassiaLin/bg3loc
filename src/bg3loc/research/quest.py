from __future__ import annotations

from typing import Iterator
import xml.etree.ElementTree as ET

from bg3loc.research.model import ResearchEvidence, ResearchMapping

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

    from bg3loc.research.structural_provenance import parse_structural_xml

    definitions = parse_structural_xml(xml_text, resource_path=resource_path,
                                       package=pak_name, kind="quest")
    # Keep the legacy global elementIndex solely as occurrence location metadata.
    indices = {elem: index for index, elem in enumerate(root.iter(), 1)}
    nodes = [elem for elem in root.iter() if elem.tag.rsplit("}", 1)[-1] == "node"] or [root]
    for node, definition in zip(nodes, definitions):
        local_indices = {index: elem for index, elem in enumerate(node.iter(), 1)}
        for occurrence in definition.occurrences:
            element_index = indices[local_indices[occurrence.location]]
            properties = {
                **definition.provenance(), "fieldName": occurrence.field_name,
                "fieldRole": occurrence.field_role, "pakName": pak_name,
                "elementIndex": element_index, "entityId": definition.entity_identity,
            }
            evidence = ResearchEvidence(
                sourceRole="QuestJournalField", resourcePath=resource_path,
                evidenceType="QuestJournal", ruleId=RULE_QUEST_JOURNAL,
                properties=properties,
            )
            yield ResearchMapping(
                contentUid=occurrence.content_uid, mappingType="quest-journal",
                classification=occurrence.field_role, evidence=[evidence],
                version=occurrence.version, reviewRequired=True,
                metadata={**definition.provenance(), "questFieldRole": occurrence.field_role,
                          "fieldName": occurrence.field_name, "elementIndex": element_index,
                          "entityId": definition.entity_identity},
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
