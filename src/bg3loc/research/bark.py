from __future__ import annotations

import hashlib
import re
from typing import Any, Iterator

from bg3loc.research.dialog import traverse_dialog_json
from bg3loc.research.model import ResearchEvidence, ResearchMapping

RULE_BARK_SPEAKER = "BG3-BARK-SPEAKER-STRUCTURE"

# The 11 canonical root bark containers
# Note: In game PAKs, internal paths are under Story/DialogsBinary/ with extension .lsf
CANONICAL_BARK_CONTAINERS: list[str] = [
    "Mods/Gustav/Story/DialogsBinary/Global/BG_PointAndClick/GLO_BG_PointNClick_Astarion_NarrativeArc_Start.lsf",
    "Mods/Gustav/Story/DialogsBinary/Global/BG_PointAndClick/GLO_BG_PointNClick_Gale_NarrativeArc_Start.lsf",
    "Mods/Gustav/Story/DialogsBinary/Global/BG_PointAndClick/GLO_BG_PointNClick_GenericOrigin_NarrativeArc_Start.lsf",
    "Mods/Gustav/Story/DialogsBinary/Global/BG_PointAndClick/GLO_BG_PointNClick_Laezel_NarrativeArc_Start.lsf",
    "Mods/Gustav/Story/DialogsBinary/Global/BG_PointAndClick/GLO_BG_PointNClick_Shadowheart_NarrativeArc_Start.lsf",
    "Mods/Gustav/Story/DialogsBinary/Global/BG_PointAndClick/GLO_BG_PointNClick_Wyll_NarrativeArc_Start.lsf",
    "Mods/GustavDev/Story/DialogsBinary/Global/BG_PointAndClick/GLO_BG_PointNClick_Halsin_NarrativeArc_Start.lsf",
    "Mods/GustavDev/Story/DialogsBinary/Global/BG_PointAndClick/GLO_BG_PointNClick_Jaheira_NarrativeArc_Start.lsf",
    "Mods/GustavDev/Story/DialogsBinary/Global/BG_PointAndClick/GLO_BG_PointNClick_Karlach_NarrativeArc_Start.lsf",
    "Mods/GustavDev/Story/DialogsBinary/Global/BG_PointAndClick/GLO_BG_PointNClick_Minsc_NarrativeArc_Start.lsf",
    "Mods/GustavDev/Story/DialogsBinary/Global/BG_PointAndClick/GLO_BG_PointNClick_Minthara_NarrativeArc_Start.lsf",
]

# Alternate .lsj forms used when converted to JSON
CANONICAL_BARK_CONTAINERS_LSJ: list[str] = [
    p.replace("DialogsBinary", "Dialogs").replace(".lsf", ".lsj")
    for p in CANONICAL_BARK_CONTAINERS
]

# GenericOrigin is structurally shared. Its current membership is read from the
# container's speaker list; names and UUIDs are never supplied by a workbook.
GENERIC_ORIGIN_CONTAINER = "GLO_BG_PointNClick_GenericOrigin_NarrativeArc_Start"


def _value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def _dialog_region(dialog_data: dict[str, Any]) -> dict[str, Any]:
    save = dialog_data.get("save") or dialog_data
    regions = save.get("regions") or {}
    dialog = regions.get("dialog") or save
    return dialog if isinstance(dialog, dict) else {}


def derive_speaker_members(dialog_data: dict[str, Any], *, internal_path: str) -> list[dict[str, str]]:
    """Return current-container speaker identities with explicit provenance."""
    dialog = _dialog_region(dialog_data)
    identities: list[str] = []
    speaker_list = dialog.get("speakerlist") or []

    def visit(obj: Any) -> None:
        if isinstance(obj, dict):
            raw_list = _value(obj.get("list"))
            if isinstance(raw_list, str):
                identities.extend(part.strip() for part in raw_list.split(";") if part.strip())
            for child in obj.values():
                visit(child)
        elif isinstance(obj, list):
            for child in obj:
                visit(child)

    visit(speaker_list)
    # Preserve order while removing duplicates introduced by nested serialization.
    identities = list(dict.fromkeys(identities))
    provenance = f"{internal_path}#speakerlist"
    if identities:
        return [{"identity": identity, "provenance": provenance} for identity in identities]

    # A single-speaker bark's semantic character name is encoded by the current
    # container name. This is evidence, not a historical membership list.
    match = re.search(r"GLO_BG_PointNClick_(.+?)_NarrativeArc_Start", internal_path)
    if match and match.group(1) != "GenericOrigin":
        return [{"identity": match.group(1), "provenance": f"{internal_path}#container-name"}]
    return []


def semantic_group_id(members: list[dict[str, str]], *, internal_path: str) -> str:
    material = "\n".join(member["identity"] for member in members) or internal_path.replace("\\", "/")
    return f"BARK-GROUP-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:12].upper()}"


def classify_bark_mapping(
    mapping: ResearchMapping,
    *,
    container_path: str = "",
    speaker_members: list[dict[str, str]] | None = None,
) -> ResearchMapping:
    """Classify bark as SingleSpeaker or SharedSpeaker based on structural container/slot."""
    normalized_path = container_path.replace("\\", "/")

    members = list(speaker_members or [])
    is_shared = len(members) > 1 or "GenericOrigin" in normalized_path or mapping.metadata.get("speakerSlot") == "SharedSpeaker"

    classification = "SharedSpeaker" if is_shared else "SingleSpeaker"

    # Enrich evidence
    for ev in mapping.evidence:
        ev.evidenceType = "BarkSpeakerStructure"
        ev.ruleId = RULE_BARK_SPEAKER
        ev.properties["classification"] = classification
        ev.properties["speakerMembers"] = members
        ev.properties["speakerMemberCount"] = len(members)
        if is_shared:
            ev.properties["sharedGroupId"] = semantic_group_id(members, internal_path=normalized_path)
            ev.properties["translationConstraint"] = "MustFitAllSharedSpeakers"

    mapping.mappingType = "bark-speaker"
    mapping.classification = classification
    mapping.reviewRequired = True
    mapping.metadata["speakerMembers"] = members
    mapping.metadata["sharedGroupId"] = semantic_group_id(members, internal_path=normalized_path) if is_shared else ""
    return mapping


def parse_bark_container(
    dialog_data: dict[str, Any],
    *,
    internal_path: str = "",
    pak_name: str = "Gustav.pak"
) -> Iterator[ResearchMapping]:
    """Parse an ambient bark dialog container and yield classified bark mappings."""
    members = derive_speaker_members(dialog_data, internal_path=internal_path)
    for base_mapping in traverse_dialog_json(dialog_data, resource_path=internal_path, pak_name=pak_name):
        yield classify_bark_mapping(base_mapping, container_path=internal_path, speaker_members=members)
