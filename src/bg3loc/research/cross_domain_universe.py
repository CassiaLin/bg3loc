"""Cross-Domain Target Universe — dynamic extraction from game resources.

This module defines CrossDomainTarget and the extraction logic that builds the
target universe from actual game pak files at research-map time.

No embedded historical payload is present.  All ContentUids are discovered
from the live game installation supplied by the caller.
"""
from __future__ import annotations

import re
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Mapping, Sequence

from bg3loc.backends import ArchiveBackend
from bg3loc.research.model import HANDLE_PATTERN, ResearchScanResource
from bg3loc.research.overlay import (
    DEFAULT_PAK_PRIORITY,
    OverlayCandidate,
    resolve_overlay_precedence,
)

# ---------------------------------------------------------------------------
# Rule identifier
# ---------------------------------------------------------------------------
RULE_CROSS_DOMAIN_UNIVERSE = "BG3-CROSS-DOMAIN-UNIVERSE"

# ---------------------------------------------------------------------------
# Cross-domain pak scope — packages that carry UI/Skill/Stats/RootTemplate data
# ---------------------------------------------------------------------------
CROSS_DOMAIN_SCOPE_PAKS: frozenset[str] = frozenset(
    ["Shared.pak", "Gustav.pak", "GustavX.pak", "Patch8_HotFix9.pak", "Game.pak"]
)

# ---------------------------------------------------------------------------
# Cross-domain resource family rule table
#
# Each rule describes ONE specific resource family that contributes to the
# cross-domain target universe.  Fields:
#   family         – canonical family name
#   paks           – frozenset of pak names this family may appear in
#   path_re        – compiled regex that an internalPath must match
#   formats        – accepted file extensions (lowercase, with dot)
#   domain         – assigned cross-domain domain for matching resources
#   field_re       – optional regex to identify which XML/stats attribute names
#                    are localization-bearing (None = accept all TranslatedString)
#   entity_attr    – XML attribute name used to identify the entity (element name
#                    or attribute id)
#   classification – SemanticTarget or HistoricalCompatibilityReference
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CrossDomainFamilyRule:
    family: str
    paks: frozenset[str]
    path_re: re.Pattern[str]
    formats: frozenset[str]
    domain: str
    field_re: re.Pattern[str] | None = None
    entity_attr: str = "id"
    classification: str = "SemanticTarget"


CROSS_DOMAIN_FAMILY_RULES: tuple[CrossDomainFamilyRule, ...] = (
    # UI / XAML  – files under Content/UI or GUI carrying localised tooltip handles
    CrossDomainFamilyRule(
        family="UIXaml",
        paks=frozenset(["Shared.pak", "Gustav.pak", "GustavX.pak", "Patch8_HotFix9.pak", "Game.pak"]),
        path_re=re.compile(r"(?i)(?:content/ui|(?:^|/)gui)/.*\.xaml$"),
        formats=frozenset([".xaml"]),
        domain="UserInterface",
        field_re=None,  # any handle occurrence in XAML text
        entity_attr="id",
        classification="SemanticTarget",
    ),
    # Progression Descriptions LSX/LSF — character advancement UI semantics
    CrossDomainFamilyRule(
        family="ProgressionDescriptionsLSX",
        paks=frozenset(["Shared.pak", "Gustav.pak", "GustavX.pak", "Patch8_HotFix9.pak"]),
        path_re=re.compile(r"(?i)(?:^|/)public/[^/]+/localization/progressiondescriptions_.*\.lsf$"),
        formats=frozenset([".lsf", ".lsx"]),
        domain="ProgressionUI",
        field_re=re.compile(r"(?i)^(DisplayName|Description|Content)$"),
        entity_attr="id",
        classification="SemanticTarget",
    ),
    # Historical DialogsBinary keyword-heuristic compatibility references
    CrossDomainFamilyRule(
        family="DialogsBinaryHistorical",
        paks=frozenset(["Gustav.pak"]),
        path_re=re.compile(r"(?i)(?:^|/)mods/gustavdev/story/dialogsbinary/act2/.*(?:tutorial|progression).*\.lsf$"),
        formats=frozenset([".lsf", ".lsx"]),
        domain="TutorialAndSystem",
        field_re=re.compile(r"(?i)^TagText$"),
        entity_attr="id",
        classification="HistoricalCompatibilityReference",
    ),
    # Stats — GustavX generated data (spells, passives, statuses, items, weapons, armour)
    CrossDomainFamilyRule(
        family="StatsGeneratedGustavX",
        paks=frozenset(["GustavX.pak"]),
        path_re=re.compile(r"(?i)/stats/generated/data/.*\.txt$"),
        formats=frozenset([".txt"]),
        domain="AbilityOrSkill",
        field_re=re.compile(
            r"(?i)^(DisplayName|Description|ExtraDescription|ShortDescription|Tooltip"
            r"|DisplayName_Male|DisplayName_Female|Description_Male|Description_Female)$"
        ),
        entity_attr="id",
        classification="SemanticTarget",
    ),
    # Stats — Shared generated data
    CrossDomainFamilyRule(
        family="StatsGeneratedShared",
        paks=frozenset(["Shared.pak", "Patch8_HotFix9.pak"]),
        path_re=re.compile(r"(?i)/stats/generated/data/.*\.txt$"),
        formats=frozenset([".txt"]),
        domain="AbilityOrSkill",
        field_re=re.compile(
            r"(?i)^(DisplayName|Description|ExtraDescription|ShortDescription|Tooltip"
            r"|DisplayName_Male|DisplayName_Female|Description_Male|Description_Female)$"
        ),
        entity_attr="id",
        classification="SemanticTarget",
    ),
    # Stats — Gustav generated data
    CrossDomainFamilyRule(
        family="StatsGeneratedGustav",
        paks=frozenset(["Gustav.pak"]),
        path_re=re.compile(r"(?i)/stats/generated/data/.*\.txt$"),
        formats=frozenset([".txt"]),
        domain="AbilityOrSkill",
        field_re=re.compile(
            r"(?i)^(DisplayName|Description|ExtraDescription|ShortDescription|Tooltip"
            r"|DisplayName_Male|DisplayName_Female|Description_Male|Description_Female)$"
        ),
        entity_attr="id",
        classification="SemanticTarget",
    ),
    # RootTemplates _merged LSX/LSF — DisplayName / Description / ShortDescription and expanded semantic fields + GameMaster
    CrossDomainFamilyRule(
        family="RootTemplatesLSX",
        paks=frozenset(["Shared.pak", "Gustav.pak", "GustavX.pak", "Patch8_HotFix9.pak"]),
        path_re=re.compile(r"(?i)/roottemplates/_merged\.(lsf|lsx)$"),
        formats=frozenset([".lsf", ".lsx"]),
        domain="GameObjectDescription",
        field_re=re.compile(
            r"(?i)^(DisplayName|Description|ShortDescription|Title|Tooltip|"
            r"OnUseDescription|DisplayNameAlchemy|TechnicalDescription|"
            r"UnknownDescription|UnknownDisplayName|GameMasterSpawnSubSection)$"
        ),
        entity_attr="id",
        classification="SemanticTarget",
    ),
    # Skill / Spell LSX definitions (not Stats text grammar — actual LSX nodes)
    CrossDomainFamilyRule(
        family="SpellSkillLSX",
        paks=frozenset(["Shared.pak", "Gustav.pak", "GustavX.pak", "Patch8_HotFix9.pak"]),
        path_re=re.compile(r"(?i)/public/[^/]+/(spells|skills|passives|statuses)/.*\.(lsf|lsx)$"),
        formats=frozenset([".lsf", ".lsx"]),
        domain="AbilityOrSkill",
        field_re=re.compile(
            r"(?i)^(DisplayName|Description|ExtraDescription|ShortDescription|Tooltip)$"
        ),
        entity_attr="id",
        classification="SemanticTarget",
    ),
    # Items / Equipment LSX
    CrossDomainFamilyRule(
        family="ItemEquipmentLSX",
        paks=frozenset(["Shared.pak", "Gustav.pak", "GustavX.pak", "Patch8_HotFix9.pak"]),
        path_re=re.compile(r"(?i)/public/[^/]+/(items|equipment|armor|weapon|treasure)/.*\.(lsf|lsx)$"),
        formats=frozenset([".lsf", ".lsx"]),
        domain="ItemsAndEquipment",
        field_re=re.compile(
            r"(?i)^(DisplayName|Description|ShortDescription|Tooltip)$"
        ),
        entity_attr="id",
        classification="SemanticTarget",
    ),
    # Tutorial / System LSX
    CrossDomainFamilyRule(
        family="TutorialSystemLSX",
        paks=frozenset(["Shared.pak", "Gustav.pak", "GustavX.pak", "Patch8_HotFix9.pak"]),
        path_re=re.compile(r"(?i)/public/[^/]+/(tutorial|system|tips)/.*\.(lsf|lsx)$"),
        formats=frozenset([".lsf", ".lsx"]),
        domain="TutorialAndSystem",
        field_re=re.compile(
            r"(?i)^(DisplayName|Description|ShortDescription|Tooltip|Title)$"
        ),
        entity_attr="id",
        classification="SemanticTarget",
    ),
)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(slots=True, frozen=True)
class CrossDomainMaterializedRelation:
    """A single relation-level occurrence in the cross-domain target universe.

    Preserves full entity, field, inheritance closure, and provider provenance
    before late deduplication by ContentUid.
    """
    contentUid: str
    domain: str
    effectiveProvider: str
    definingProvider: str
    internalPath: str
    entity: str                 # stat entry name or XML element/attribute identity
    field: str                  # stats field name or XML attribute id
    inheritedFrom: str = ""     # stats "using" immediate parent or empty if explicit
    inheritanceDepth: int = 0   # 0 = explicit on entity; 1 = inherited from parent; etc.
    explicitOrInherited: str = "explicit"  # "explicit" or "inherited"
    providerOverrideApplied: bool = False
    classification: str = "SemanticTarget"  # "SemanticTarget" or "HistoricalCompatibilityReference"
    ruleId: str = RULE_CROSS_DOMAIN_UNIVERSE

    @property
    def provider(self) -> str:
        """Compatibility property returning '<effectiveProvider>::<internalPath>'."""
        return f"{self.effectiveProvider}::{self.internalPath}"


@dataclass(slots=True, frozen=True)
class CrossDomainEntityLayerAuditRecord:
    """A single layered definition of an entity before effective provider materialization."""
    entity: str
    provider: str
    internalPath: str
    priority: int
    using: str
    explicitFieldCount: int
    selectedAsEffective: bool
    overrideReason: str


@dataclass(slots=True, frozen=True)
class CrossDomainTarget:
    contentUid: str
    domain: str
    provider: str           # "<pakName>::<internalPath>"
    internalPath: str
    entity: str             # stat entry name or XML element/attribute identity
    field: str              # stats field name or XML attribute id
    inheritedFrom: str = "" # stats "using" parent or XML template parent
    classification: str = "SemanticTarget"  # "SemanticTarget" or "HistoricalCompatibilityReference"
    ruleId: str = RULE_CROSS_DOMAIN_UNIVERSE


@dataclass(slots=True)
class CrossDomainExtractionResult:
    """Complete result of cross-domain extraction.

    Preserves relation-level records (materialized with full transitive inheritance
    closure) alongside the deduplicated ContentUid target map and entity layer audit.
    """
    relations: list[CrossDomainMaterializedRelation] = field(default_factory=list)
    targets_by_uid: dict[str, CrossDomainTarget] = field(default_factory=dict)
    layer_audit_records: list[CrossDomainEntityLayerAuditRecord] = field(default_factory=list)
    raw_entity_definitions: int = 0
    multi_provider_entities: int = 0
    provider_overrides_resolved: int = 0
    effective_entities: int = 0
    explicit_relations: int = 0
    inherited_relations: int = 0
    missing_parents: int = 0
    cycles_detected: int = 0

    @property
    def semantic_target_uids(self) -> set[str]:
        return {uid for uid, t in self.targets_by_uid.items() if t.classification == "SemanticTarget"}

    @property
    def historical_compatibility_uids(self) -> set[str]:
        return {uid for uid, t in self.targets_by_uid.items() if t.classification == "HistoricalCompatibilityReference"}

    @property
    def reproduction_universe_uids(self) -> set[str]:
        return set(self.targets_by_uid.keys())

    @property
    def unique_uids(self) -> set[str]:
        return self.reproduction_universe_uids


# ---------------------------------------------------------------------------
# LSX/LSF and Template Inheritance Notes
# ---------------------------------------------------------------------------
# Investigation into RootTemplates and GameObject LSX/LSF hierarchy:
# GameObjects declare 'ParentTemplateId' referencing a parent GameObject template.
# In the engine, localized string attributes (DisplayName, Description, ShortDescription)
# are explicitly authored on the leaf or base templates where applicable, and were
# extracted historically as explicit TranslatedString handle attributes.
# Dynamic template inheritance resolution across the 13,700+ GameObject hierarchy
# does not introduce synthetic translation targets beyond explicitly authored handles.
# Therefore, LSX/LSF resources emit explicit TranslatedString records directly.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Context passed from research map
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CrossDomainExtractionContext:
    """Runtime context explicitly supplied by ``research map`` for cross-domain extraction.

    The caller is responsible for populating all fields; the extractor does not
    perform any implicit discovery.
    """
    game_dir: Path
    backend: ArchiveBackend
    resources: Sequence[ResearchScanResource]
    build_id: str = "local"
    game_version: str = "unknown"
    scan_manifest_sha256: str = ""

    def cache_key(self) -> str:
        """Return a provenance-stable cache key for this extraction context."""
        game_dir_str = str(self.game_dir.resolve())
        return f"{game_dir_str}|{self.build_id}|{self.game_version}|{self.scan_manifest_sha256}"


# ---------------------------------------------------------------------------
# Per-run cache  (owned by the research-map run; NOT a module-level singleton)
# ---------------------------------------------------------------------------

class CrossDomainUniverseCache:
    """Per-run cache keyed by full provenance.

    Instantiate once per ``research map`` invocation and pass to
    ``extract_cross_domain_target_universe``.  Because provenance is part of the key,
    two different game installations or build IDs will never share a cache
    entry.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, CrossDomainTarget]] = {}

    def get(self, key: str) -> dict[str, CrossDomainTarget] | None:
        return self._store.get(key)

    def put(self, key: str, value: dict[str, CrossDomainTarget]) -> None:
        self._store[key] = value


# ---------------------------------------------------------------------------
# Resource selection
# ---------------------------------------------------------------------------

def select_cross_domain_resources(
    resources: Sequence[ResearchScanResource],
) -> list[tuple[CrossDomainFamilyRule, ResearchScanResource]]:
    """Filter scan resources to those matching a cross-domain family rule.

    Returns a list of (rule, resource) pairs; one resource may match at most
    one rule (first match wins in CROSS_DOMAIN_FAMILY_RULES order).
    """
    selected: list[tuple[CrossDomainFamilyRule, ResearchScanResource]] = []
    for res in resources:
        path_lower = res.internalPath.replace("\\", "/")
        ext = Path(path_lower).suffix.lower()
        if res.pakName not in CROSS_DOMAIN_SCOPE_PAKS:
            continue
        for rule in CROSS_DOMAIN_FAMILY_RULES:
            if res.pakName not in rule.paks:
                continue
            if ext not in rule.formats:
                continue
            if rule.path_re.search(path_lower):
                selected.append((rule, res))
                break  # first rule wins per resource
    return selected


# ---------------------------------------------------------------------------
# Provider precedence
# ---------------------------------------------------------------------------

def resolve_cross_domain_provider_precedence(
    selected: list[tuple[CrossDomainFamilyRule, ResearchScanResource]],
    priority_order: Sequence[str] | None = None,
) -> list[tuple[CrossDomainFamilyRule, ResearchScanResource]]:
    """Apply overlay-precedence logic to the cross-domain selected resources.

    When the same internalPath exists in multiple paks the winning pak
    (highest in DEFAULT_PAK_PRIORITY) is kept; the others are discarded.

    Returns the winning (rule, resource) pairs in stable order.
    """
    candidates = [
        OverlayCandidate(
            internalPath=r.internalPath.replace("\\", "/"),
            pakName=r.pakName,
            size=r.size,
        )
        for _, r in selected
    ]
    resolutions = resolve_overlay_precedence(candidates, priority_order or DEFAULT_PAK_PRIORITY)

    winning: list[tuple[CrossDomainFamilyRule, ResearchScanResource]] = []
    for rule, res in selected:
        path_key = res.internalPath.replace("\\", "/")
        resolution = resolutions.get(path_key)
        if resolution and resolution.winningPak == res.pakName:
            winning.append((rule, res))
    return winning


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Stats text extraction & inheritance closure
# ---------------------------------------------------------------------------

RE_ENTRY = re.compile(r'^\s*new\s+entry\s+"(?P<name>[^"]+)"', re.IGNORECASE)
RE_USING = re.compile(r'^\s*using\s+"(?P<using>[^"]*)"', re.IGNORECASE)
RE_DATA = re.compile(r'^\s*data\s+"(?P<field>[^"]+)"\s+"(?P<value>.*)"', re.IGNORECASE)


def compute_provider_priority(pak_name: str, internal_path: str = "") -> int:
    """Compute explicit provider priority for entity-level materialization.

    Priority hierarchy:
    Shared (10-19) < Gustav (20-29) < GustavX (30-39) < Patch (40+)
    """
    pak_lower = pak_name.lower()
    path_lower = internal_path.replace("\\", "/").lower()

    if "patch" in pak_lower or "hotfix" in pak_lower or "patch" in path_lower:
        base = 40
    elif "gustavx" in pak_lower or "honourx" in path_lower or "photomode" in path_lower:
        base = 30
    elif "gustav" in pak_lower:
        base = 20
    elif "shared" in pak_lower:
        base = 10
    else:
        base = 0

    sub = 0
    if "shareddev" in path_lower:
        sub = 5
    elif "gustavdev" in path_lower:
        sub = 5
    elif "honourx" in path_lower:
        sub = 5
    elif "photomode" in path_lower:
        sub = 7
    elif "honour" in path_lower:
        sub = 8

    return base + sub


@dataclass(slots=True)
class _StatEntryRecord:
    name: str
    using: str
    explicit_fields: dict[str, str]  # field_name -> contentUid
    pak_name: str
    internal_path: str
    domain: str
    priority: int = 0
    entry_index: int = 0


def _parse_stats_entries(
    text: str,
    *,
    pak_name: str,
    internal_path: str,
    domain: str,
    field_re: re.Pattern[str] | None,
    priority: int | None = None,
) -> list[_StatEntryRecord]:
    """Parse a Larian stats text file into a list of _StatEntryRecord."""
    entries: list[_StatEntryRecord] = []
    current_entry: str | None = None
    current_using: str = ""
    current_fields: dict[str, str] = {}
    prio = priority if priority is not None else compute_provider_priority(pak_name, internal_path)
    entry_idx = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue

        m_entry = RE_ENTRY.match(line)
        if m_entry:
            if current_entry:
                entries.append(
                    _StatEntryRecord(
                        name=current_entry,
                        using=current_using,
                        explicit_fields=current_fields,
                        pak_name=pak_name,
                        internal_path=internal_path,
                        domain=domain,
                        priority=prio,
                        entry_index=entry_idx,
                    )
                )
                entry_idx += 1
            current_entry = m_entry.group("name")
            current_using = ""
            current_fields = {}
            continue

        if not current_entry:
            continue

        m_using = RE_USING.match(line)
        if m_using:
            current_using = m_using.group("using")
            continue

        m_data = RE_DATA.match(line)
        if m_data:
            field_name = m_data.group("field")
            field_val = m_data.group("value")

            if field_re is not None and not field_re.match(field_name):
                continue

            for hm in HANDLE_PATTERN.finditer(field_val):
                current_fields[field_name] = hm.group("uid")

    if current_entry:
        entries.append(
            _StatEntryRecord(
                name=current_entry,
                using=current_using,
                explicit_fields=current_fields,
                pak_name=pak_name,
                internal_path=internal_path,
                domain=domain,
                priority=prio,
                entry_index=entry_idx,
            )
        )

    return entries


class _ResolvedStatsEntity:
    __slots__ = (
        "name", "effective_pak", "internal_path", "domain",
        "using", "explicit_fields", "defining_providers", "override_applied"
    )

    def __init__(
        self,
        name: str,
        effective_pak: str,
        internal_path: str,
        domain: str,
        using: str,
        explicit_fields: dict[str, str],
        defining_providers: dict[str, str],
        override_applied: bool,
    ) -> None:
        self.name = name
        self.effective_pak = effective_pak
        self.internal_path = internal_path
        self.domain = domain
        self.using = using
        self.explicit_fields = explicit_fields
        self.defining_providers = defining_providers
        self.override_applied = override_applied


def _materialize_stats_entities(
    raw_entries: Sequence[_StatEntryRecord],
) -> tuple[list[CrossDomainMaterializedRelation], list[CrossDomainEntityLayerAuditRecord], dict[str, int]]:
    """Group entity definitions, resolve provider precedence, and perform inheritance closure."""
    by_entity: dict[str, list[_StatEntryRecord]] = defaultdict(list)
    for ent in raw_entries:
        by_entity[ent.name].append(ent)

    sorted_entity_names = sorted(by_entity.keys())
    raw_by_entity: dict[str, list[_StatEntryRecord]] = {}
    layer_audit_records: list[CrossDomainEntityLayerAuditRecord] = []
    multi_provider_entities_count = 0
    provider_overrides_resolved_count = 0

    for name in sorted_entity_names:
        candidates = by_entity[name]
        is_multi = len(candidates) > 1
        if is_multi:
            multi_provider_entities_count += 1
            provider_overrides_resolved_count += 1

        # Sort descending by priority, then internal_path lexicographical, then entry_index
        candidates.sort(
            key=lambda c: (c.priority, c.internal_path, c.entry_index),
            reverse=True,
        )
        raw_by_entity[name] = candidates

        for rank, c in enumerate(candidates):
            is_effective = (rank == 0)
            if is_effective:
                reason = "SoleDefinition" if not is_multi else "HigherProviderPriority"
            else:
                reason = "SupercededByHigherProviderPriority"

            layer_audit_records.append(
                CrossDomainEntityLayerAuditRecord(
                    entity=c.name,
                    provider=c.pak_name,
                    internalPath=c.internal_path,
                    priority=c.priority,
                    using=c.using,
                    explicitFieldCount=len(c.explicit_fields),
                    selectedAsEffective=is_effective,
                    overrideReason=reason,
                )
            )

    effective_entities: dict[str, _ResolvedStatsEntity] = {}
    for name in sorted_entity_names:
        layers = raw_by_entity[name]
        effective_cand = layers[0]
        merged_fields: dict[str, str] = {}
        defining_providers: dict[str, str] = {}
        external_using = ""
        override_applied = len(layers) > 1

        for layer in layers:
            for fn, uid in layer.explicit_fields.items():
                if fn not in merged_fields:
                    merged_fields[fn] = uid
                    defining_providers[fn] = layer.pak_name
            if layer.using != name:
                external_using = layer.using
                break

        effective_entities[name] = _ResolvedStatsEntity(
            name=name,
            effective_pak=effective_cand.pak_name,
            internal_path=effective_cand.internal_path,
            domain=effective_cand.domain,
            using=external_using,
            explicit_fields=merged_fields,
            defining_providers=defining_providers,
            override_applied=override_applied,
        )

    materialized: list[CrossDomainMaterializedRelation] = []
    cycles_detected = 0
    missing_parents = 0

    for name in sorted_entity_names:
        ent = effective_entities[name]

        for fn, uid in ent.explicit_fields.items():
            materialized.append(
                CrossDomainMaterializedRelation(
                    contentUid=uid,
                    domain=ent.domain,
                    effectiveProvider=ent.effective_pak,
                    definingProvider=ent.defining_providers[fn],
                    internalPath=ent.internal_path,
                    entity=name,
                    field=fn,
                    inheritedFrom=ent.using,
                    inheritanceDepth=0,
                    explicitOrInherited="explicit",
                    providerOverrideApplied=ent.override_applied,
                    ruleId=RULE_CROSS_DOMAIN_UNIVERSE,
                )
            )

        if not ent.using:
            continue

        visited = {name}
        curr_parent = ent.using
        depth = 1
        resolved_fields = set(ent.explicit_fields.keys())

        while curr_parent:
            if curr_parent in visited:
                cycles_detected += 1
                break
            visited.add(curr_parent)
            if curr_parent not in effective_entities:
                missing_parents += 1
                break
            parent_ent = effective_entities[curr_parent]

            for p_fn, p_uid in parent_ent.explicit_fields.items():
                if p_fn not in resolved_fields:
                    resolved_fields.add(p_fn)
                    materialized.append(
                        CrossDomainMaterializedRelation(
                            contentUid=p_uid,
                            domain=ent.domain,
                            effectiveProvider=ent.effective_pak,
                            definingProvider=parent_ent.defining_providers[p_fn],
                            internalPath=ent.internal_path,
                            entity=name,
                            field=p_fn,
                            inheritedFrom=curr_parent,
                            inheritanceDepth=depth,
                            explicitOrInherited="inherited",
                            providerOverrideApplied=(ent.override_applied or parent_ent.override_applied),
                            ruleId=RULE_CROSS_DOMAIN_UNIVERSE,
                        )
                    )

            curr_parent = parent_ent.using
            depth += 1

    counts = {
        "raw_entity_definitions": len(raw_entries),
        "multi_provider_entities": multi_provider_entities_count,
        "provider_overrides_resolved": provider_overrides_resolved_count,
        "effective_entities": len(effective_entities),
        "explicit_relations": len([r for r in materialized if r.explicitOrInherited == "explicit"]),
        "inherited_relations": len([r for r in materialized if r.explicitOrInherited == "inherited"]),
        "missing_parents": missing_parents,
        "cycles_detected": cycles_detected,
    }

    return materialized, layer_audit_records, counts


def _resolve_stats_inheritance(
    entries: Mapping[str, _StatEntryRecord] | Sequence[_StatEntryRecord],
) -> list[CrossDomainMaterializedRelation]:
    """Compatibility wrapper: resolves inheritance and materialization."""
    if isinstance(entries, Mapping):
        raw_list = list(entries.values())
    else:
        raw_list = list(entries)
    materialized, _, _ = _materialize_stats_entities(raw_list)
    return materialized


def _extract_from_stats_text(
    text: str,
    *,
    pak_name: str,
    internal_path: str,
    domain: str,
    field_re: re.Pattern[str] | None,
) -> Iterator[CrossDomainTarget]:
    """Parse a single Larian stats text file and yield CrossDomainTarget with
    transitive inheritance closure within the file."""
    entries = _parse_stats_entries(
        text,
        pak_name=pak_name,
        internal_path=internal_path,
        domain=domain,
        field_re=field_re,
    )
    relations, _, _ = _materialize_stats_entities(entries)
    for rel in relations:
        yield CrossDomainTarget(
            contentUid=rel.contentUid,
            domain=rel.domain,
            provider=rel.provider,
            internalPath=rel.internalPath,
            entity=rel.entity,
            field=rel.field,
            inheritedFrom=rel.inheritedFrom,
            classification=rel.classification,
            ruleId=rel.ruleId,
        )


# ---------------------------------------------------------------------------
# LSX / XML extraction
# ---------------------------------------------------------------------------

def _extract_from_lsx_xml(
    xml_text: str,
    *,
    pak_name: str,
    internal_path: str,
    domain: str,
    field_re: re.Pattern[str] | None,
    classification: str = "SemanticTarget",
) -> Iterator[CrossDomainMaterializedRelation]:
    """Parse a converted LSX/XML resource and yield CrossDomainMaterializedRelation for each
    TranslatedString handle found in a qualifying attribute."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError:
        return

    def _walk(node: ET.Element, current_entity: str) -> Iterator[CrossDomainMaterializedRelation]:
        entity = current_entity
        if node.tag == "node":
            node_id = node.get("id", "")
            if node_id:
                entity = node_id

        for child in node:
            if child.tag == "attribute":
                attr_type = child.get("type", "")
                if "TranslatedString" in attr_type:
                    handle = child.get("handle", "")
                    if handle and HANDLE_PATTERN.fullmatch(handle):
                        attr_id = child.get("id", "")
                        if field_re is None or field_re.match(attr_id):
                            rel_cls = classification
                            if attr_id.lower() == "gamemasterspawnsubsection":
                                rel_cls = "HistoricalCompatibilityReference"
                            yield CrossDomainMaterializedRelation(
                                contentUid=handle,
                                domain=domain,
                                effectiveProvider=pak_name,
                                definingProvider=pak_name,
                                internalPath=internal_path,
                                entity=entity,
                                field=attr_id,
                                inheritedFrom="",
                                inheritanceDepth=0,
                                explicitOrInherited="explicit",
                                providerOverrideApplied=False,
                                classification=rel_cls,
                                ruleId=RULE_CROSS_DOMAIN_UNIVERSE,
                            )
            elif child.tag == "node" or len(child) > 0:
                yield from _walk(child, entity)

    yield from _walk(root, "")


# ---------------------------------------------------------------------------
# XAML extraction (raw text scan for handle patterns)
# ---------------------------------------------------------------------------

def _extract_from_xaml(
    text: str,
    *,
    pak_name: str,
    internal_path: str,
    domain: str,
    classification: str = "SemanticTarget",
) -> Iterator[CrossDomainMaterializedRelation]:
    """Scan a XAML file for localization handle occurrences."""
    for hm in HANDLE_PATTERN.finditer(text):
        uid = hm.group("uid")
        start = hm.start()
        snippet = text[max(0, start - 200): start]
        elem_name = ""
        angle = snippet.rfind("<")
        if angle >= 0:
            after = snippet[angle + 1:]
            ws = re.match(r"[\w:.]+", after)
            if ws:
                elem_name = ws.group(0)

        attr_name = ""
        eq_quot = snippet.rfind('="')
        if eq_quot >= 0:
            before_eq = snippet[:eq_quot]
            space_or_start = max(before_eq.rfind(" "), before_eq.rfind("\t"), before_eq.rfind("\n"), -1)
            attr_name = before_eq[space_or_start + 1:]

        yield CrossDomainMaterializedRelation(
            contentUid=uid,
            domain=domain,
            effectiveProvider=pak_name,
            definingProvider=pak_name,
            internalPath=internal_path,
            entity=elem_name or internal_path,
            field=attr_name or "handle",
            inheritedFrom="",
            inheritanceDepth=0,
            explicitOrInherited="explicit",
            providerOverrideApplied=False,
            classification=classification,
            ruleId=RULE_CROSS_DOMAIN_UNIVERSE,
        )


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------

def extract_cross_domain_target_universe(
    ctx: CrossDomainExtractionContext,
    *,
    cache: CrossDomainUniverseCache | None = None,
) -> dict[str, CrossDomainTarget]:
    """Extract the cross-domain target universe from the game resources described
    in *ctx*.

    Parameters
    ----------
    ctx:
        Explicit runtime context supplied by ``research map``; must include
        the game directory, backend, and resolved (overlay-filtered) resources.
    cache:
        Optional per-run cache instance.  When supplied, the result is stored
        and subsequent calls with the same provenance key return the cached
        value without re-extraction.

    Returns
    -------
    A mapping from ContentUid → CrossDomainTarget.
    Deduplication rule: first winning provider per ContentUid is kept
    (consistent with overlay-precedence; lower-priority duplicates discarded).
    """
    if cache is not None:
        key = ctx.cache_key()
        cached = cache.get(key)
        if cached is not None:
            return cached

    result = _run_extraction(ctx)

    if cache is not None:
        cache.put(key, result)

    return result


def extract_cross_domain_result(
    ctx: CrossDomainExtractionContext,
    *,
    cache: CrossDomainUniverseCache | None = None,
) -> CrossDomainExtractionResult:
    """Extract both the relation-level records and unique ContentUid targets."""
    result = _run_extraction_result(ctx)

    if cache is not None:
        key = ctx.cache_key()
        cache.put(key, result.targets_by_uid)

    return result


def _run_extraction(ctx: CrossDomainExtractionContext) -> dict[str, CrossDomainTarget]:
    """Perform the actual extraction without any caching layer."""
    res = _run_extraction_result(ctx)
    return res.targets_by_uid


def _run_extraction_result(ctx: CrossDomainExtractionContext) -> CrossDomainExtractionResult:
    """Perform the actual extraction yielding CrossDomainExtractionResult."""
    selected = select_cross_domain_resources(ctx.resources)
    winning = resolve_cross_domain_provider_precedence(selected)

    game_data_dir = ctx.game_dir / "Data"
    if not game_data_dir.is_dir():
        game_data_dir = ctx.game_dir

    raw_stats_entries: list[_StatEntryRecord] = []
    non_stats_relations: list[CrossDomainMaterializedRelation] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for rule, res in winning:
            pak_path = _find_pak(game_data_dir, res.pakName)
            if pak_path is None:
                continue

            dest = tmp / res.pakName / res.internalPath.replace("\\", "/")
            try:
                ctx.backend.extract_single_file(pak_path, res.internalPath, dest)
            except Exception:
                continue

            ext = Path(res.internalPath).suffix.lower()
            content_path = dest

            if ext == ".lsf":
                converted = dest.with_suffix(".lsx")
                try:
                    ctx.backend.convert_resource(dest, converted)
                    content_path = converted
                except Exception:
                    continue
                ext = ".lsx"

            try:
                content = content_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            if ext == ".txt":
                parsed = _parse_stats_entries(
                    content,
                    pak_name=res.pakName,
                    internal_path=res.internalPath,
                    domain=rule.domain,
                    field_re=rule.field_re,
                )
                raw_stats_entries.extend(parsed)
            elif ext in (".lsx", ".xml"):
                non_stats_relations.extend(
                    _extract_from_lsx_xml(
                        content,
                        pak_name=res.pakName,
                        internal_path=res.internalPath,
                        domain=rule.domain,
                        field_re=rule.field_re,
                        classification=rule.classification,
                    )
                )
            elif ext == ".xaml":
                non_stats_relations.extend(
                    _extract_from_xaml(
                        content,
                        pak_name=res.pakName,
                        internal_path=res.internalPath,
                        domain=rule.domain,
                        classification=rule.classification,
                    )
                )

    # Materialize Stats entities and resolve inheritance closure across all winning entries
    stats_relations, layer_audit, counts = _materialize_stats_entities(raw_stats_entries)
    all_relations = non_stats_relations + stats_relations

    # Deduplicate targets by ContentUid late (first provider wins; SemanticTarget takes precedence over HistoricalCompatibilityReference)
    uid_to_target: dict[str, CrossDomainTarget] = {}
    for rel in all_relations:
        tgt = CrossDomainTarget(
            contentUid=rel.contentUid,
            domain=rel.domain,
            provider=f"{rel.effectiveProvider}::{rel.internalPath}",
            internalPath=rel.internalPath,
            entity=rel.entity,
            field=rel.field,
            inheritedFrom=rel.inheritedFrom,
            classification=rel.classification,
            ruleId=rel.ruleId,
        )
        if rel.contentUid not in uid_to_target:
            uid_to_target[rel.contentUid] = tgt
        elif (
            uid_to_target[rel.contentUid].classification == "HistoricalCompatibilityReference"
            and tgt.classification == "SemanticTarget"
        ):
            uid_to_target[rel.contentUid] = tgt

    return CrossDomainExtractionResult(
        relations=all_relations,
        targets_by_uid=uid_to_target,
        layer_audit_records=layer_audit,
        raw_entity_definitions=counts["raw_entity_definitions"],
        multi_provider_entities=counts["multi_provider_entities"],
        provider_overrides_resolved=counts["provider_overrides_resolved"],
        effective_entities=counts["effective_entities"],
        explicit_relations=counts["explicit_relations"] + len([r for r in non_stats_relations if r.explicitOrInherited == "explicit"]),
        inherited_relations=counts["inherited_relations"],
        missing_parents=counts["missing_parents"],
        cycles_detected=counts["cycles_detected"],
    )


def _find_pak(game_data_dir: Path, pak_name: str) -> Path | None:
    direct = game_data_dir / pak_name
    if direct.is_file():
        return direct
    for candidate in game_data_dir.rglob(pak_name):
        if candidate.is_file():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Compatibility shim for callers that have not yet migrated to the new API
# ---------------------------------------------------------------------------

def get_cross_domain_universe_uids(
    universe: dict[str, CrossDomainTarget],
) -> set[str]:
    """Return the set of ContentUids present in a cross-domain universe dict."""
    return set(universe.keys())
