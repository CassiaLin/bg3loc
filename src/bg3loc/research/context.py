from __future__ import annotations

import re
from typing import Any, Iterable, Iterator, Sequence

from bg3loc.research.model import HANDLE_PATTERN, ResearchEvidence, ResearchMapping

RULE_CONTEXT_AGGREGATOR = "BG3-CONTEXT-EVIDENCE-AGGREGATOR"
RULE_SHARED_CONTEXT = "BG3-SHARED-CONTEXT-CONFLICT-REFERENCE"
RULE_PASSIVE_CONTEXT = "BG3-PASSIVE-CONTEXT-GUSTAV-REFERENCE"

RE_PASSIVE_ENTRY = re.compile(r'^\s*new\s+entry\s+"(?P<name>[^"]+)"', re.IGNORECASE)
RE_PASSIVE_TYPE = re.compile(r'^\s*type\s+"(?P<type>[^"]*)"', re.IGNORECASE)
RE_PASSIVE_DATA = re.compile(r'^\s*data\s+"(?P<field>[^"]+)"\s+"(?P<value>.*)"', re.IGNORECASE)

VALID_PASSIVE_FIELDS = {"DisplayName", "Description", "ExtraDescription"}


def extract_shared_context_hits(
    text: str,
    *,
    resource_path: str = "",
    pak_name: str = "Shared.pak",
    target_uids: set[str] | None = None
) -> Iterator[ResearchMapping]:
    """
    Search text / converted resource for occurrences of handles in target_uids (CONFLICT-001).
    Deduplicates on (contentuid, pakName, internalPath, matchLocation).
    """
    if not target_uids:
        return

    seen_dedup: set[tuple[str, str, str, str]] = set()

    for line_idx, line in enumerate(text.splitlines(), start=1):
        for m in HANDLE_PATTERN.finditer(line):
            uid = m.group("uid")
            if uid in target_uids:
                col = m.start() + 1
                loc = f"Line {line_idx}, Column {col}"
                dedup_key = (uid, pak_name, resource_path, loc)
                if dedup_key in seen_dedup:
                    continue
                seen_dedup.add(dedup_key)

                ver = m.group("ver") or "1"
                evidence = ResearchEvidence(
                    sourceRole="SharedContextResource",
                    resourcePath=resource_path,
                    evidenceType="SharedContextHit",
                    ruleId=RULE_SHARED_CONTEXT,
                    properties={
                        "pakName": pak_name,
                        "matchLocation": loc,
                        "line": line_idx,
                        "lineSummary": line.strip()[:100],
                    }
                )

                yield ResearchMapping(
                    contentUid=uid,
                    mappingType="shared-context",
                    classification="SharedContextHit",
                    evidence=[evidence],
                    version=ver,
                    reviewRequired=True,
                    metadata={
                        "pakName": pak_name,
                        "resourcePath": resource_path,
                        "matchLocation": loc,
                    }
                )


def extract_passive_context_hits(
    text: str,
    *,
    resource_path: str = "",
    pak_name: str = "Gustav.pak",
    target_uids: set[str] | None = None
) -> Iterator[ResearchMapping]:
    """
    Parse structured PassiveData in stats files (Gustav, GustavDev, Honour)
    and match valid fields against target_uids (CONFLICT-001).
    """
    if not target_uids:
        return

    # Preserve complete entry provenance even if using/non-localized fields occur
    # after the localization-bearing line.
    from bg3loc.research.stats import parse_stats_text
    provenance = {
        (mapping.evidence[0].properties["line"], mapping.contentUid): mapping.metadata
        for mapping in parse_stats_text(text, resource_path=resource_path, provider=pak_name)
    }

    current_entry: str | None = None
    current_type: str = ""

    lines = text.splitlines()
    for line_idx, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue

        entry_m = RE_PASSIVE_ENTRY.match(line)
        if entry_m:
            current_entry = entry_m.group("name")
            current_type = ""
            continue

        if not current_entry:
            continue

        type_m = RE_PASSIVE_TYPE.match(line)
        if type_m:
            current_type = type_m.group("type")
            continue

        data_m = RE_PASSIVE_DATA.match(line)
        if data_m and current_type.lower() == "passivedata":
            field_name = data_m.group("field")
            field_val = data_m.group("value")

            if field_name not in VALID_PASSIVE_FIELDS:
                continue

            for match in HANDLE_PATTERN.finditer(field_val):
                uid = match.group("uid")
                if uid in target_uids:
                    col = match.start() + 1
                    loc = f"Line {line_idx}, Column {col}"
                    ver = match.group("ver") or "1"

                    evidence = ResearchEvidence(
                        sourceRole="PassiveResource",
                        resourcePath=resource_path,
                        evidenceType="PassiveContext",
                        ruleId=RULE_PASSIVE_CONTEXT,
                        properties={
                            **provenance[(line_idx, uid)],
                            "pakName": pak_name,
                            "entryName": current_entry,
                            "entryType": current_type,
                            "fieldName": field_name,
                            "matchLocation": loc,
                            "parseStatus": "StructuredVerified",
                        }
                    )

                    yield ResearchMapping(
                        contentUid=uid,
                        mappingType="passive-context",
                        classification="StructuredVerified",
                        evidence=[evidence],
                        version=ver,
                        reviewRequired=True,
                        metadata={
                            "pakName": pak_name,
                            "entryName": current_entry,
                            "fieldName": field_name,
                            "resourcePath": resource_path,
                        }
                    )


class ContextAggregator:
    """Aggregates context evidence across Dialog, Quest, Passive, and Shared sources."""

    def __init__(self) -> None:
        self._mappings: dict[str, ResearchMapping] = {}
        self._shared_uids: set[str] = set()
        self._passive_uids: set[str] = set()
        self._dialog_uids: set[str] = set()
        self._quest_uids: set[str] = set()

    def add_mapping(self, mapping: ResearchMapping) -> None:
        uid = mapping.contentUid
        m_type = mapping.mappingType

        # Record specific family sets
        if m_type == "shared-context" or any(ev.evidenceType == "SharedContextHit" for ev in mapping.evidence):
            self._shared_uids.add(uid)
        if m_type == "passive-context" or any(ev.evidenceType == "PassiveContext" for ev in mapping.evidence):
            self._passive_uids.add(uid)
        if m_type in ("dialog-context", "bark-speaker") or any(ev.evidenceType in ("DialogGraph", "DialogNodeGraph", "BarkSpeakerStructure") for ev in mapping.evidence):
            self._dialog_uids.add(uid)
        if m_type == "quest-journal" or any(ev.evidenceType in ("QuestJournal", "QuestStructure") for ev in mapping.evidence):
            self._quest_uids.add(uid)

        if uid not in self._mappings:
            self._mappings[uid] = ResearchMapping(
                contentUid=uid,
                mappingType="context-evidence",
                classification=mapping.classification,
                version=mapping.version,
                reviewRequired=mapping.reviewRequired,
                metadata=dict(mapping.metadata),
            )

        target = self._mappings[uid]
        for ev in mapping.evidence:
            target.evidence.append(ev)

        # Update metadata flags
        for ev in mapping.evidence:
            ev_type = ev.evidenceType
            target.metadata[f"has{ev_type}"] = True

    def add_mappings(self, mappings: Iterable[ResearchMapping]) -> None:
        for m in mappings:
            self.add_mapping(m)

    def get_mappings(self) -> list[ResearchMapping]:
        return list(self._mappings.values())

    def get_by_uid(self, uid: str) -> ResearchMapping | None:
        return self._mappings.get(uid)

    def count(self) -> int:
        return len(self._mappings)

    def summary(self) -> dict[str, Any]:
        shared = self._shared_uids
        passive = self._passive_uids
        dialog = self._dialog_uids
        quest = self._quest_uids

        union_set = shared | passive | dialog | quest

        pairwise_overlaps = {
            "shared_passive": len(shared & passive),
            "shared_dialog": len(shared & dialog),
            "shared_quest": len(shared & quest),
            "passive_dialog": len(passive & dialog),
            "passive_quest": len(passive & quest),
            "dialog_quest": len(dialog & quest),
        }

        return {
            "totalWithContext": len(self._mappings),
            "unionCount": len(union_set),
            "withSharedContext": len(shared),
            "withPassiveContext": len(passive),
            "withDialogEvidence": len(dialog),
            "withQuestEvidence": len(quest),
            "pairwiseOverlaps": pairwise_overlaps,
            "isDisjoint": sum(pairwise_overlaps.values()) == 0,
        }
