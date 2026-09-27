from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Iterable

from bg3loc.research.model import ResearchEvidence, ResearchMapping


PRIMARY_CATEGORIES = (
    "dialogue_general",
    "dialogue_story",
    "quest",
    "bark",
    "ui",
    "skill_spell",
    "item",
    "book_lore",
    "character_world",
    "system_message",
    "tutorial",
    "other",
)

SUPPORTED_V1_CATEGORIES = {
    "bark",
    "quest",
    "skill_spell",
    "item",
    "ui",
    "dialogue_general",
    "book_lore",
    "character_world",
    "system_message",
    "tutorial",
    "other",
}

_SKILL_ENTRY_TYPES = {
    "spelldata",
    "passivedata",
    "statusdata",
    "interruptdata",
}

_ITEM_ENTRY_TYPES = {
    "object",
    "objectdata",
    "weapon",
    "weapondata",
    "armor",
    "armordata",
    "item",
    "itemdata",
}

_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}

_SKILL_RESOURCE_STEMS = {
    "spells",
    "spell",
    "passives",
    "passive",
    "statuses",
    "status",
    "interrupts",
    "interrupt",
}

_ITEM_RESOURCE_STEMS = {
    "weapons",
    "weapon",
    "armor",
    "armors",
    "items",
    "item",
    "objects",
    "object",
}

_PRECEDENCE = {
    "bark": 10,
    "quest": 20,
    "skill_spell": 30,
    "item": 40,
    "book_lore": 45,
    "character_world": 46,
    "system_message": 47,
    "tutorial": 48,
    "ui": 50,
    "dialogue_general": 60,
    "other": 100,
}


@dataclass(slots=True)
class ClassificationEvidence:
    category: str
    mappingType: str
    classification: str
    ruleId: str
    resourcePath: str = ""
    sourceRole: str = ""
    properties: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class FunctionalClassification:
    contentUid: str
    primaryCategory: str
    tags: list[str]
    classificationStatus: str
    classificationConfidence: str
    classificationEvidence: list[ClassificationEvidence]

    def to_dict(self) -> dict[str, object]:
        return {
            "contentUid": self.contentUid,
            "primaryCategory": self.primaryCategory,
            "tags": self.tags,
            "classificationStatus": self.classificationStatus,
            "classificationConfidence": self.classificationConfidence,
            "classificationEvidence": [e.to_dict() for e in self.classificationEvidence],
        }


def _normalized_resource_stem(path: str) -> str:
    normalized = path.replace("\\", "/").casefold()
    return PurePosixPath(normalized).stem


def _matching_evidence(mapping: ResearchMapping, evidence_type: str) -> ResearchEvidence | None:
    return next((ev for ev in mapping.evidence if ev.evidenceType == evidence_type), None)


def _mapping_candidates(
    mapping: ResearchMapping,
) -> list[tuple[str, str, str, ResearchEvidence | None]]:
    """Return structural candidates with the exact evidence occurrence that triggered them."""
    candidates: list[tuple[str, str, str, ResearchEvidence | None]] = []
    evidence_types = {ev.evidenceType for ev in mapping.evidence}

    if mapping.mappingType == "bark-speaker" or "BarkSpeakerStructure" in evidence_types:
        candidates.append(
            ("bark", "high", "bark-structural-mapping", _matching_evidence(mapping, "BarkSpeakerStructure"))
        )

    if mapping.mappingType == "quest-journal" or "QuestJournal" in evidence_types:
        candidates.append(
            ("quest", "high", "quest-journal-mapping", _matching_evidence(mapping, "QuestJournal"))
        )

    domain = str(mapping.metadata.get("domain", ""))
    if mapping.mappingType == "ui-skill-candidate":
        provider_ev = _matching_evidence(mapping, "UiSkillProvider")
        if domain == "AbilityOrSkill":
            candidates.append(("skill_spell", "high", "ui-skill-domain", provider_ev))
        elif domain == "ItemsAndEquipment":
            candidates.append(("item", "high", "ui-skill-domain", provider_ev))
        elif domain == "UserInterface":
            candidates.append(("ui", "high", "ui-skill-domain", provider_ev))

    for ev in mapping.evidence:
        props = ev.properties
        entry_type = str(props.get("entryType", "")).casefold()
        resource_stem = _normalized_resource_stem(ev.resourcePath)

        if mapping.mappingType == "stat-reference" or ev.evidenceType in {"StatsDefinition", "PassiveContext"}:
            if entry_type in _SKILL_ENTRY_TYPES:
                candidates.append(("skill_spell", "high", "stat-entry-type", ev))
            elif entry_type in _ITEM_ENTRY_TYPES:
                candidates.append(("item", "high", "stat-entry-type", ev))
            elif resource_stem in _SKILL_RESOURCE_STEMS:
                candidates.append(("skill_spell", "medium", "stat-resource-path", ev))
            elif resource_stem in _ITEM_RESOURCE_STEMS:
                candidates.append(("item", "medium", "stat-resource-path", ev))

        if ev.evidenceType == "UiSkillProvider":
            ev_domain = str(props.get("domain", ""))
            if ev_domain == "AbilityOrSkill":
                candidates.append(("skill_spell", "high", "ui-skill-provider", ev))
            elif ev_domain == "ItemsAndEquipment":
                candidates.append(("item", "high", "ui-skill-provider", ev))
            elif ev_domain == "UserInterface":
                candidates.append(("ui", "high", "ui-skill-provider", ev))

    if mapping.mappingType == "story-occurrence":
        for ev in mapping.evidence:
            if ev.evidenceType != "StoryOccurrence":
                continue
            props = ev.properties
            family = str(props.get("resourceFamily", ""))
            domain = str(props.get("storyDomain", ""))
            role = str(props.get("attributeRole", ""))
            is_old = bool(props.get("isOldText", False))
            if is_old:
                continue
            if (
                family == "ReadableLocalizationRegistry"
                and domain == "ReadableWorldText"
                and role == "Content"
            ):
                candidates.append(("book_lore", "high", "readable-registry-structure", ev))
            elif family == "TagsCharacters" and domain == "StoryRelatedTerm":
                candidates.append(("character_world", "high", "tags-characters-structure", ev))
            elif family == "LocalizationRegistry" and domain == "StoryRelatedTerm" and role == "Content":
                registry_stem = _normalized_resource_stem(ev.resourcePath)
                if (
                    registry_stem == "levels"
                    or registry_stem == "waypointshrines"
                    or registry_stem == "waypointshrines2"
                    or registry_stem == "subregions"
                    or registry_stem.endswith("_subregions")
                ):
                    candidates.append(("character_world", "high", "world-registry-structure", ev))
                elif registry_stem == "readychecks_descriptions":
                    candidates.append(("system_message", "high", "ready-check-registry-structure", ev))
                elif registry_stem == "itemcombinations":
                    candidates.append(("item", "high", "item-combination-registry-structure", ev))
                else:
                    normalized_path = ev.resourcePath.replace("\\", "/").casefold()
                    path_parts = PurePosixPath(normalized_path).parts
                    localization_child = ""
                    try:
                        localization_index = path_parts.index("localization")
                        if localization_index + 1 < len(path_parts):
                            localization_child = path_parts[localization_index + 1]
                    except ValueError:
                        pass

                    if (
                        registry_stem in {"stats", "status", "shout", "target"}
                        or registry_stem.startswith("stats_")
                        or registry_stem.startswith("status_")
                        or registry_stem.startswith("shout_")
                        or registry_stem.startswith("target_")
                        or localization_child == "stats"
                    ):
                        candidates.append(("skill_spell", "high", "gameplay-registry-structure", ev))
            elif (
                family in {"DialogsRaw", "DialogsBinary", "Cinematics"}
                and domain in {
                    "NPCDialogue",
                    "PlayerDialogueOption",
                    "AmbientDialogue",
                    "CinematicSubtitle",
                    "Narration",
                }
            ):
                candidates.append(("dialogue_general", "high", "story-dialog-structure", ev))

    if mapping.mappingType == "ui-skill-universe":
        for ev in mapping.evidence:
            if ev.evidenceType != "UiSkillUniverse":
                continue
            props = ev.properties
            if str(props.get("status", "")) == "ExcludedCommentOnly":
                continue
            workstream = str(props.get("workstream", ""))
            domains = str(props.get("domains", ""))
            entity_type = str(props.get("entityType", ""))
            field_name = str(props.get("fieldName", ""))
            if workstream == "ItemsEquipment":
                candidates.append(("item", "high", "ui-skill-workstream", ev))
            elif workstream == "AbilitySkill":
                candidates.append(("skill_spell", "high", "ui-skill-workstream", ev))
            elif workstream == "UserInterface":
                candidates.append(("ui", "high", "ui-skill-workstream", ev))
            elif workstream == "TutorialSystem" and domains == "UI.Tutorial":
                candidates.append(("tutorial", "high", "tutorial-workstream-domain", ev))
            elif (
                workstream == "AQResourceReferencedReview"
                and domains == "Ability.Unknown"
                and entity_type == "ActionResourceDefinition"
                and field_name == "DisplayName"
            ):
                candidates.append(("skill_spell", "high", "action-resource-definition", ev))

    if mapping.mappingType == "dialog-context" or "DialogGraph" in evidence_types:
        candidates.append(
            ("dialogue_general", "high", "dialog-context", _matching_evidence(mapping, "DialogGraph"))
        )

    return candidates


def classify_functional_ownership(
    content_uids: Iterable[str],
    mappings: Iterable[ResearchMapping],
) -> list[FunctionalClassification]:
    """Classify each requested ContentUid into one supported LSTP-01A production lane.

    The function is deliberately fail-safe: unsupported or insufficient evidence becomes
    `other`, and higher-priority structural categories win over lower-priority evidence.
    """
    ordered_uids = list(dict.fromkeys(content_uids))
    by_uid: dict[str, list[ResearchMapping]] = {uid: [] for uid in ordered_uids}
    for mapping in mappings:
        if mapping.contentUid in by_uid:
            by_uid[mapping.contentUid].append(mapping)

    results: list[FunctionalClassification] = []
    for uid in ordered_uids:
        category_hits: dict[str, list[tuple[str, ResearchMapping, str, ResearchEvidence | None]]] = {}
        evidence_records: list[ClassificationEvidence] = []

        for mapping in by_uid[uid]:
            for category, confidence, reason, trigger_ev in _mapping_candidates(mapping):
                category_hits.setdefault(category, []).append((confidence, mapping, reason, trigger_ev))
                evidence_records.append(
                    ClassificationEvidence(
                        category=category,
                        mappingType=mapping.mappingType,
                        classification=mapping.classification,
                        ruleId=trigger_ev.ruleId if trigger_ev else reason,
                        resourcePath=trigger_ev.resourcePath if trigger_ev else "",
                        sourceRole=trigger_ev.sourceRole if trigger_ev else "",
                        properties={"reason": reason, "confidence": confidence},
                    )
                )

        if not category_hits:
            results.append(
                FunctionalClassification(
                    contentUid=uid,
                    primaryCategory="other",
                    tags=[],
                    classificationStatus="unclassified",
                    classificationConfidence="low",
                    classificationEvidence=[],
                )
            )
            continue

        strongest_by_category = {
            category: min(_CONFIDENCE_RANK[hit[0]] for hit in hits)
            for category, hits in category_hits.items()
        }
        ranked = sorted(
            category_hits,
            key=lambda c: (strongest_by_category[c], _PRECEDENCE[c]),
        )
        winner = ranked[0]
        winner_hits = category_hits[winner]
        confidence = min(
            (hit[0] for hit in winner_hits),
            key=lambda value: _CONFIDENCE_RANK[value],
        )

        # Overlap is expected across structural surfaces. Precedence resolves supported
        # ownership; retain losing categories as tags for later audit/batching.
        losing = [category for category in ranked[1:] if category != winner]
        tags = [f"also:{category}" for category in losing]

        results.append(
            FunctionalClassification(
                contentUid=uid,
                primaryCategory=winner,
                tags=tags,
                classificationStatus="classified",
                classificationConfidence=confidence,
                classificationEvidence=evidence_records,
            )
        )

    return results


def summarize_functional_classification(
    results: Iterable[FunctionalClassification],
) -> dict[str, object]:
    items = list(results)
    counts = {category: 0 for category in PRIMARY_CATEGORIES}
    status_counts = {"classified": 0, "ambiguous": 0, "unclassified": 0}
    confidence_counts = {"high": 0, "medium": 0, "low": 0}

    seen: set[str] = set()
    duplicate_ownership = 0
    for item in items:
        if item.contentUid in seen:
            duplicate_ownership += 1
        seen.add(item.contentUid)
        counts[item.primaryCategory] += 1
        status_counts[item.classificationStatus] += 1
        confidence_counts[item.classificationConfidence] += 1

    total = len(items)
    classified = status_counts["classified"]
    return {
        "totalContentUidCount": total,
        "categoryCounts": counts,
        "statusCounts": status_counts,
        "confidenceCounts": confidence_counts,
        "classifiedCoveragePercent": (classified / total * 100.0) if total else 0.0,
        "duplicateOwnershipCount": duplicate_ownership,
        "missingContentUidCount": 0,
    }
