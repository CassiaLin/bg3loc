from __future__ import annotations

import csv
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from bg3loc.research.model import ResearchEvidence, ResearchMapping

RULE_STORY_PARTITION = "BG3-STORY-MATERIAL-PARTITION"
RULE_RESIDUAL_STORY = "BG3-RESIDUAL-STORY-HOLD-EVALUATION"
RULE_CROSS_DOMAIN = "BG3-CROSS-DOMAIN-OVERLAP"

UID_REGEX = re.compile(r"h[0-9a-f]{8}g[0-9a-f]{4}g[0-9a-f]{4}g[0-9a-f]{4}g[0-9a-f]{12}", re.I)


def classify_story_domain(source_family: str, constructor: str = "", category: str = "", field: str = "", path: str = "") -> str:
    """Classify story occurrence domain according to semantic story domain rules."""
    fam = source_family
    if fam in ("DialogsRaw", "DialogsBinary", "Dialog"):
        if re.search(r"cinematic", path, re.I) or re.search(r"cinematic", category, re.I):
            return "CinematicSubtitle"
        if re.search(r"narrat", constructor, re.I):
            return "Narration"
        if re.search(r"question|player", constructor, re.I):
            return "PlayerDialogueOption"
        if re.search(r"bark", category, re.I):
            return "AmbientDialogue"
        return "NPCDialogue"
    if fam == "Cinematics":
        return "CinematicSubtitle"
    if fam == "JournalQuest":
        if re.search(r"title", field, re.I):
            return "QuestTitle"
        if re.search(r"description|objective", field, re.I):
            return "QuestDescription"
        return "JournalEntry"
    if fam == "ReadableLocalizationRegistry":
        if re.search(r"title|displayname", field, re.I):
            return "BookTitle"
        return "ReadableWorldText"
    if fam in ("TagsCharacters", "RootTemplates", "LocalizationRegistry"):
        return "StoryRelatedTerm"
    if fam in ("StoryGoals", "LevelResources"):
        return "ContextSupportOnly"
    return "Unknown"


def derive_cross_domain_references(
    story_uids: set[str],
    other_domain_uids: set[str],
    existing_383_uids: set[str] | None = None,
) -> set[str]:
    """Dynamically derive cross-domain translation references."""
    ex383 = existing_383_uids or set()
    return (story_uids & other_domain_uids) - ex383


@dataclass(slots=True)
class StoryOccurrence:
    contentUid: str
    sourcePak: str
    internalPath: str
    resourceType: str
    storyDomain: str = "Unknown"
    nodeId: str = ""
    attributeRole: str = ""
    isOldText: bool = False
    hasSpeaker: bool = False
    hasDialog: bool = False
    hasQuest: bool = False


# 10 Family Structural Parsers for File/XML/JSON Content

def parse_dialog_raw_occurrences(content: str, pak_name: str, internal_path: str) -> list[StoryOccurrence]:
    """Parse DialogsRaw JSON (LSJ)."""
    results: list[StoryOccurrence] = []
    try:
        data = json.loads(content)
        dialog = data.get("save", {}).get("regions", {}).get("dialog", {})
        category = str(dialog.get("category", {}).get("value", ""))
        nodes_wrapper = dialog.get("nodes", [{}])[0].get("node", []) if dialog.get("nodes") else []
        for node in nodes_wrapper:
            node_uuid = str(node.get("UUID", {}).get("value", ""))
            ctor = str(node.get("constructor", {}).get("value", ""))
            spk_idx = str(node.get("speaker", {}).get("value", ""))
            has_spk = bool(spk_idx and spk_idx != "-1")

            for m in UID_REGEX.finditer(json.dumps(node.get("TaggedTexts", []))):
                uid = m.group(0).lower()
                dom = classify_story_domain("DialogsRaw", constructor=ctor, category=category, field="TagText", path=internal_path)
                results.append(StoryOccurrence(
                    contentUid=uid,
                    sourcePak=pak_name,
                    internalPath=internal_path,
                    resourceType="DialogsRaw",
                    storyDomain=dom,
                    nodeId=node_uuid,
                    attributeRole="TagText",
                    hasSpeaker=has_spk,
                    hasDialog=True,
                    hasQuest=False,
                    isOldText=False,
                ))
    except Exception:
        pass
    return results


def _parse_xml_occurrences(content: str, pak_name: str, internal_path: str, family: str) -> list[StoryOccurrence]:
    """Parse converted XML resources and retain stable enclosing-node identity."""
    results: list[StoryOccurrence] = []
    try:
        root = ET.fromstring(content)
        node_ord = 0

        def local_name(tag: str) -> str:
            return tag.rsplit("}", 1)[-1]

        def walk(elem: ET.Element, enclosing_node_id: str = "") -> None:
            nonlocal node_ord
            current_node_id = enclosing_node_id
            if local_name(elem.tag) == "node":
                node_ord += 1
                direct_identity = next(
                    (
                        child.get("value", "") or child.get("handle", "")
                        for child in list(elem)
                        if local_name(child.tag) == "attribute"
                        and child.get("id", "") in {"UUID", "MapKey", "Name", "ID", "Guid", "GUID"}
                        and (child.get("value") or child.get("handle"))
                    ),
                    "",
                )
                current_node_id = (
                    direct_identity
                    or elem.get("UUID", "")
                    or elem.get("MapKey", "")
                    or elem.get("Name", "")
                    or f"{elem.get('id', 'node')}#{node_ord}"
                )

            handle = elem.get("handle") or elem.get("value")
            if handle and UID_REGEX.match(handle):
                attr_id = elem.get("id", "")
                is_old = attr_id == "OldText"
                dom = classify_story_domain(family, field=attr_id, path=internal_path)
                results.append(StoryOccurrence(
                    contentUid=handle.lower(),
                    sourcePak=pak_name,
                    internalPath=internal_path,
                    resourceType=family,
                    storyDomain=dom,
                    nodeId=current_node_id,
                    attributeRole=attr_id or "TranslatedString",
                    hasSpeaker=False,
                    hasDialog=family.startswith("Dialog"),
                    hasQuest=(family == "JournalQuest"),
                    isOldText=is_old,
                ))

            for child in list(elem):
                walk(child, current_node_id)

        walk(root)
    except Exception:
        pass
    return results

def parse_dialog_binary_occurrences(xml_content: str, pak_name: str, internal_path: str) -> list[StoryOccurrence]:
    """Parse converted DialogsBinary XML."""
    return _parse_xml_occurrences(xml_content, pak_name, internal_path, "DialogsBinary")


def parse_journal_quest_occurrences(xml_content: str, pak_name: str, internal_path: str) -> list[StoryOccurrence]:
    """Parse converted JournalQuest XML."""
    return _parse_xml_occurrences(xml_content, pak_name, internal_path, "JournalQuest")


def parse_cinematics_occurrences(xml_content: str, pak_name: str, internal_path: str) -> list[StoryOccurrence]:
    """Parse converted Cinematics XML."""
    return _parse_xml_occurrences(xml_content, pak_name, internal_path, "Cinematics")


def parse_level_resources_occurrences(xml_content: str, pak_name: str, internal_path: str) -> list[StoryOccurrence]:
    """Parse converted LevelResources XML."""
    return _parse_xml_occurrences(xml_content, pak_name, internal_path, "LevelResources")


def parse_localization_registry_occurrences(xml_content: str, pak_name: str, internal_path: str) -> list[StoryOccurrence]:
    """Parse converted LocalizationRegistry XML."""
    return _parse_xml_occurrences(xml_content, pak_name, internal_path, "LocalizationRegistry")


def parse_readable_registry_occurrences(xml_content: str, pak_name: str, internal_path: str) -> list[StoryOccurrence]:
    """Parse converted ReadableLocalizationRegistry XML."""
    return _parse_xml_occurrences(xml_content, pak_name, internal_path, "ReadableLocalizationRegistry")


def parse_root_templates_occurrences(xml_content: str, pak_name: str, internal_path: str) -> list[StoryOccurrence]:
    """Parse converted RootTemplates XML."""
    return _parse_xml_occurrences(xml_content, pak_name, internal_path, "RootTemplates")


def parse_tags_characters_occurrences(xml_content: str, pak_name: str, internal_path: str) -> list[StoryOccurrence]:
    """Parse converted TagsCharacters XML."""
    return _parse_xml_occurrences(xml_content, pak_name, internal_path, "TagsCharacters")


def parse_story_goals_occurrences(text_content: str, pak_name: str, internal_path: str) -> list[StoryOccurrence]:
    """Parse raw text StoryGoals for ContentUids."""
    results: list[StoryOccurrence] = []
    for line_idx, line in enumerate(text_content.splitlines(), start=1):
        for m in UID_REGEX.finditer(line):
            uid = m.group(0).lower()
            results.append(StoryOccurrence(
                contentUid=uid,
                sourcePak=pak_name,
                internalPath=internal_path,
                resourceType="StoryGoals",
                storyDomain="ContextSupportOnly",
                nodeId=f"line/{line_idx}",
                attributeRole="StoryGoalText",
                hasSpeaker=False,
                hasDialog=False,
                hasQuest=False,
                isOldText=False,
            ))
    return results


def verify_source_unconfirmed_candidate(
    uid: str,
    occurrences: Sequence[StoryOccurrence],
    english_records: Mapping[str, str],
) -> tuple[bool, str]:
    """Verify if a source-unconfirmed story candidate meets the clearance criteria for translation supplement."""
    text = english_records.get(uid)
    if not text or text == "%%% EMPTY" or not text.strip():
        return False, "MissingOrEmptySourceText"

    if occurrences is not None and len(occurrences) > 0:
        active_occs = [o for o in occurrences if not o.isOldText]
        if not active_occs:
            return False, "OldTextOnly"

    return True, "ClearedForTranslationSupplement"


def write_story_occurrence_ledger(occurrences: Sequence[StoryOccurrence], output_path: str | Path) -> None:
    """Write generated occurrences to story-occurrence-ledger.csv."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "ContentUid", "PakName", "InternalPath", "ResourceFamily", "ResourceFormat",
            "StoryDomain", "NodeId", "AttributeRole", "HasSpeaker", "HasDialog", "HasQuest", "IsOldText"
        ])
        for o in occurrences:
            writer.writerow([
                o.contentUid, o.sourcePak, o.internalPath, o.resourceType,
                "LSJ" if o.resourceType == "DialogsRaw" else ("TXT" if o.resourceType == "StoryGoals" else "LSF"),
                o.storyDomain, o.nodeId, o.attributeRole,
                "True" if o.hasSpeaker else "False",
                "True" if o.hasDialog else "False",
                "True" if o.hasQuest else "False",
                "True" if o.isOldText else "False",
            ])


def read_story_occurrence_ledger(file_path: str | Path) -> list[StoryOccurrence]:
    """Read occurrences back from story-occurrence-ledger.csv."""
    path = Path(file_path)
    occurrences: list[StoryOccurrence] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            occurrences.append(StoryOccurrence(
                contentUid=row["ContentUid"],
                sourcePak=row["PakName"],
                internalPath=row["InternalPath"],
                resourceType=row["ResourceFamily"],
                storyDomain=row["StoryDomain"],
                nodeId=row.get("NodeId", ""),
                attributeRole=row.get("AttributeRole", ""),
                hasSpeaker=row.get("HasSpeaker", "").lower() == "true",
                hasDialog=row.get("HasDialog", "").lower() == "true",
                hasQuest=row.get("HasQuest", "").lower() == "true",
                isOldText=row.get("IsOldText", "").lower() == "true",
            ))
    return occurrences


def write_oldtext_evidence(occurrences: Sequence[StoryOccurrence], output_path: str | Path) -> None:
    """Write OldText occurrences to oldtext-evidence.csv."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ContentUid", "PakName", "InternalPath", "NodeId", "AttributeRole", "StoryDomain"])
        for o in occurrences:
            if o.isOldText:
                writer.writerow([o.contentUid, o.sourcePak, o.internalPath, o.nodeId, o.attributeRole or "OldText", o.storyDomain])


@dataclass(slots=True)
class StoryPartitionResult:
    total_unique_story_uids: int
    new_story_translation_targets: list[str] = field(default_factory=list)
    existing_authority_targets: list[str] = field(default_factory=list)
    cross_domain_references: list[str] = field(default_factory=list)
    story_context_holds: list[str] = field(default_factory=list)
    story_missing_english_holds: list[str] = field(default_factory=list)
    story_source_unconfirmed_holds: list[str] = field(default_factory=list)

    @property
    def total_holds(self) -> int:
        return (
            len(self.story_context_holds)
            + len(self.story_missing_english_holds)
            + len(self.story_source_unconfirmed_holds)
        )


@dataclass(slots=True)
class ResidualResolutionResult:
    total_residual_universe: int
    cleared_for_translation_supplement: list[str] = field(default_factory=list)
    proven_context_support_only: list[str] = field(default_factory=list)
    retained_residual_holds: list[str] = field(default_factory=list)
    requires_external_runtime_evidence: list[str] = field(default_factory=list)


def partition_story_universe(
    occurrences: Sequence[StoryOccurrence],
    *,
    english_records: Mapping[str, str],
    existing_383_uids: set[str] | None = None,
    cross_domain_uids: set[str] | None = None,
    known_context_holds: set[str] | None = None,
) -> StoryPartitionResult:
    ex383 = existing_383_uids or set()
    cd_uids = cross_domain_uids or set()

    by_uid: dict[str, list[StoryOccurrence]] = {}
    for occ in occurrences:
        by_uid.setdefault(occ.contentUid, []).append(occ)

    if known_context_holds is not None:
        ctx_holds = known_context_holds
    else:
        ctx_holds = set()
        for uid, occ_list in by_uid.items():
            # Context hold criteria:
            # 1. RootTemplates with DisplayName, ShortDescription, or GameMasterSpawnSubSection where English is missing/empty
            # 2. Public/Shared/Tags/ with DisplayName where English is official sentinel '%%% EMPTY'
            is_rt = any(
                o.resourceType == "RootTemplates"
                and o.attributeRole in ("DisplayName", "ShortDescription", "GameMasterSpawnSubSection")
                and not o.isOldText
                for o in occ_list
            )
            is_sentinel_tag = any(
                o.resourceType == "TagsCharacters"
                and o.attributeRole == "DisplayName"
                and o.internalPath.startswith("Public/Shared/Tags/")
                and not o.isOldText
                for o in occ_list
            ) and english_records.get(uid) == "%%% EMPTY"

            if is_rt:
                t = english_records.get(uid)
                if t is None or t == "%%% EMPTY" or not t.strip():
                    ctx_holds.add(uid)
            elif is_sentinel_tag:
                ctx_holds.add(uid)

    result = StoryPartitionResult(total_unique_story_uids=len(by_uid))

    for uid, occ_list in by_uid.items():
        if uid in ex383:
            result.existing_authority_targets.append(uid)
        elif uid in ctx_holds:
            result.story_context_holds.append(uid)
        elif uid in cd_uids:
            result.cross_domain_references.append(uid)
        elif uid not in english_records:
            result.story_missing_english_holds.append(uid)
        else:
            domains = set(o.storyDomain for o in occ_list)
            all_context_or_unknown = all(d in ("ContextSupportOnly", "Unknown") for d in domains)
            has_speaker_or_dialog = any(o.hasSpeaker or o.hasDialog or o.hasQuest for o in occ_list)
            if all_context_or_unknown and not has_speaker_or_dialog:
                result.story_source_unconfirmed_holds.append(uid)
            else:
                result.new_story_translation_targets.append(uid)

    return result


def resolve_residual_story_holds(
    partition: StoryPartitionResult,
    *,
    english_records: Mapping[str, str],
    occurrences_by_uid: Mapping[str, Sequence[StoryOccurrence]] | None = None,
    old_text_uids: set[str] | None = None,
    auxiliary_locales: Mapping[str, Mapping[str, str]] | None = None,
    sentinel_uids: set[str] | None = None,
    telemetry_uids: set[str] | None = None,
    **kwargs: Any,
) -> tuple[ResidualResolutionResult, list[ResearchMapping]]:
    old_texts = old_text_uids or set()
    aux = auxiliary_locales or {}
    known_telemetry = set(telemetry_uids or ())
    known_sentinels = set(sentinel_uids or ())
    for k, v in kwargs.items():
        if "telemetry" in k and isinstance(v, (set, list)):
            known_telemetry.update(v)
        elif "sentinel" in k and isinstance(v, (set, list)):
            known_sentinels.update(v)

    res = ResidualResolutionResult(total_residual_universe=partition.total_holds)
    mappings: list[ResearchMapping] = []

    # 1. Resolve StorySourceUnconfirmedHold
    for uid in partition.story_source_unconfirmed_holds:
        occs = occurrences_by_uid.get(uid, []) if occurrences_by_uid else []
        verified, reason = verify_source_unconfirmed_candidate(uid, occs, english_records)
        disp = "ClearedForTranslationSupplement" if verified else "RetainedResidualHold"
        if verified:
            res.cleared_for_translation_supplement.append(uid)
        else:
            res.retained_residual_holds.append(uid)

        ev = ResearchEvidence(
            sourceRole="ResidualStoryHoldResolution",
            resourcePath="Story/ResidualHoldLedger",
            evidenceType=disp,
            ruleId=RULE_RESIDUAL_STORY,
            properties={"resolution": disp, "sourceConfirmed": verified, "reason": reason}
        )
        mappings.append(ResearchMapping(
            contentUid=uid,
            mappingType="residual-story",
            classification=disp,
            evidence=[ev],
            reviewRequired=True,
            metadata={"disposition": disp}
        ))

    # 2. Resolve StoryMissingEnglishHold
    for uid in partition.story_missing_english_holds:
        if uid in old_texts:
            res.proven_context_support_only.append(uid)
            disposition = "ProvenContextSupportOnly"
            review_req = False
        else:
            in_aux = any(uid in loc for loc in aux.values())
            if in_aux:
                res.cleared_for_translation_supplement.append(uid)
                disposition = "ClearedForTranslationSupplement"
                review_req = True
            else:
                res.retained_residual_holds.append(uid)
                disposition = "RetainedResidualHold"
                review_req = True

        ev = ResearchEvidence(
            sourceRole="ResidualStoryHoldResolution",
            resourcePath="Story/ResidualHoldLedger",
            evidenceType=disposition,
            ruleId=RULE_RESIDUAL_STORY,
            properties={"resolution": disposition}
        )
        mappings.append(ResearchMapping(
            contentUid=uid,
            mappingType="residual-story",
            classification=disposition,
            evidence=[ev],
            reviewRequired=review_req,
            metadata={"disposition": disposition}
        ))

    # 3. Resolve StoryContextHold
    for uid in partition.story_context_holds:
        occs = occurrences_by_uid.get(uid, []) if occurrences_by_uid else []
        paks = set(o.sourcePak for o in occs)
        is_telemetry = (
            uid in known_telemetry
            or any(o.attributeRole in ("GameMasterSpawnSubSection", "Telemetry", "EditorOnly") for o in occs)
            or (len(paks) > 1 and any(o.resourceType == "RootTemplates" for o in occs))
        )
        is_empty = (
            uid in known_sentinels
            or english_records.get(uid) == "%%% EMPTY"
            or english_records.get(uid) == ""
        )

        if is_telemetry:
            res.requires_external_runtime_evidence.append(uid)
            disp = "RequiresExternalRuntimeEvidence"
        elif is_empty:
            res.proven_context_support_only.append(uid)
            disp = "ProvenContextSupportOnly"
        else:
            res.retained_residual_holds.append(uid)
            disp = "RetainedResidualHold"

        ev = ResearchEvidence(
            sourceRole="ResidualStoryHoldResolution",
            resourcePath="Story/ResidualHoldLedger",
            evidenceType=disp,
            ruleId=RULE_RESIDUAL_STORY,
            properties={"resolution": disp}
        )
        mappings.append(ResearchMapping(
            contentUid=uid,
            mappingType="residual-story",
            classification=disp,
            evidence=[ev],
            reviewRequired=True,
            metadata={"disposition": disp}
        ))

    return res, mappings


def evaluate_residual_story_candidates(
    candidate_uids: Iterable[str],
    *,
    english_records: Mapping[str, str],
    auxiliary_locales: Mapping[str, Mapping[str, str]] | None = None,
    story_graph_referenced_uids: Iterable[str] | None = None,
) -> Iterator[ResearchMapping]:
    """Compatibility helper evaluating residual story candidates."""
    story_refs = set(story_graph_referenced_uids or ())
    aux = auxiliary_locales or {}

    for uid in candidate_uids:
        in_english = uid in english_records
        in_story_graph = uid in story_refs
        has_aux = any(uid in locale_records for locale_records in aux.values())

        if in_story_graph or has_aux:
            disposition = "ClearedForTranslationSupplement"
            review_required = False
        else:
            disposition = "RetainedResidualHold"
            review_required = True

        evidence = ResearchEvidence(
            sourceRole="ResidualStoryHoldEvaluation",
            resourcePath="Story/ResidualHoldLedger",
            evidenceType="ResidualStoryHold",
            ruleId=RULE_RESIDUAL_STORY,
            properties={
                "inEnglish": in_english,
                "inStoryGraph": in_story_graph,
                "hasAuxiliaryLocalization": has_aux,
                "disposition": disposition,
            }
        )

        yield ResearchMapping(
            contentUid=uid,
            mappingType="residual-story",
            classification=disposition,
            evidence=[evidence],
            reviewRequired=review_required,
            metadata={
                "disposition": disposition,
                "inStoryGraph": in_story_graph,
            }
        )