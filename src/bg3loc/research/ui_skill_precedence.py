from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


_STATS_ENTRY_RE = re.compile(r'^\s*new\s+entry\s+"(?P<name>[^"]+)"\s*$')
_STATS_TYPE_RE = re.compile(r'^\s*type\s+"(?P<value>[^"]*)"\s*$')
_STATS_USING_RE = re.compile(r'^\s*using\s+"(?P<value>[^"]*)"\s*$')
_STATS_DATA_RE = re.compile(r'^\s*data\s+"(?P<name>[^"]+)"\s+"(?P<value>.*)"\s*$')
_HANDLE_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?P<uid>h[0-9a-f]{8}g[0-9a-f]{4}g[0-9a-f]{4}g[0-9a-f]{4}g[0-9a-f]{12})(?:;(?P<ver>[0-9]+))?(?![A-Za-z0-9_])",
    re.I,
)

AW_SUPPORT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "Gustav.pak",
        re.compile(
            r"^Public/(?:Gustav|GustavDev|Honour)/Stats/Generated/Data/Passive\.txt$|^Public/Honour/Stats/Generated/Data/Spell_Projectile\.txt$"
        ),
    ),
    (
        "GustavX.pak",
        re.compile(r"^Public/(?:GustavX|HonourX|PhotoMode)/Stats/Generated/Data/[^/]+\.txt$"),
    ),
    (
        "Shared.pak",
        re.compile(r"^Public/(?:Shared|SharedDev)/Stats/Generated/Data/[^/]+\.txt$"),
    ),
)

MODULE_META_FOLDERS = frozenset(("Gustav", "GustavDev", "Honour", "GustavX", "Shared", "SharedDev"))


@dataclass(frozen=True, slots=True)
class Definition:
    id: str
    name: str
    entity_type: str
    using: str
    fields: Mapping[str, str]
    provider: str
    internal_path: str


@dataclass(frozen=True, slots=True)
class ModuleInfo:
    folder: str
    uuid: str


@dataclass(frozen=True, slots=True)
class CandidateResolution:
    status: str
    selected_definition_id: str = ""
    related_definition_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PrecedenceOutcome:
    hold_uids: frozenset[str]
    warning_uids: frozenset[str]
    ambiguous_edge_count: int
    self_name_warning_edge_count: int
    equivalent_edge_count: int
    direct_dependency_resolved_count: int
    transitive_dependency_resolved_count: int


def definition_signature(definition: Definition) -> str:
    fields = sorted(definition.fields.items(), key=lambda item: item[0])
    material = json.dumps(
        [definition.entity_type, definition.using, fields],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def definitions_equivalent(definitions: Sequence[Definition]) -> bool:
    return len({definition_signature(item) for item in definitions}) <= 1


def exact_parent_candidates(
    child: Definition,
    definitions_by_name: Mapping[str, Sequence[Definition]],
) -> tuple[Definition, ...]:
    result = []
    for candidate in definitions_by_name.get(child.using, ()):
        if candidate.id == child.id:
            continue
        if child.entity_type and candidate.entity_type and candidate.entity_type != child.entity_type:
            continue
        result.append(candidate)
    return tuple(result)


def module_from_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    if len(parts) >= 2 and parts[0] in {"Public", "Mods"}:
        return parts[1]
    return ""


def is_aw_support_provider(package: str, internal_path: str) -> bool:
    return any(package == expected and pattern.fullmatch(internal_path) for expected, pattern in AW_SUPPORT_RULES)


def parse_stats_definitions(text: str, *, provider: str, internal_path: str) -> list[Definition]:
    definitions: list[Definition] = []
    current_name = ""
    current_type = ""
    current_using = ""
    current_fields: dict[str, str] = {}
    ordinal = 0

    def flush() -> None:
        nonlocal current_name, current_type, current_using, current_fields, ordinal
        if not current_name:
            return
        ordinal += 1
        definitions.append(
            Definition(
                id=f"{provider}::{current_name}::{ordinal}",
                name=current_name,
                entity_type=current_type,
                using=current_using,
                fields=dict(current_fields),
                provider=provider,
                internal_path=internal_path,
            )
        )
        current_name = ""
        current_type = ""
        current_using = ""
        current_fields = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        match = _STATS_ENTRY_RE.match(line)
        if match:
            flush()
            current_name = match.group("name")
            continue
        if not current_name:
            continue
        match = _STATS_TYPE_RE.match(line)
        if match:
            current_type = match.group("value")
            continue
        match = _STATS_USING_RE.match(line)
        if match:
            current_using = match.group("value")
            continue
        match = _STATS_DATA_RE.match(line)
        if match:
            current_fields[match.group("name")] = match.group("value")
    flush()
    return definitions


def definition_uids(definition: Definition) -> set[str]:
    result: set[str] = set()
    for raw_value in definition.fields.values():
        result.update(match.group("uid") for match in _HANDLE_RE.finditer(raw_value))
    return result


def dependency_closure(
    direct_dependencies: Mapping[str, Iterable[str]],
) -> dict[str, dict[str, int]]:
    closure: dict[str, dict[str, int]] = {}
    for start in direct_dependencies:
        distances: dict[str, int] = {}
        queue = deque((dep, 1) for dep in direct_dependencies.get(start, ()))
        while queue:
            current, depth = queue.popleft()
            if current == start:
                continue
            previous = distances.get(current)
            if previous is not None and previous <= depth:
                continue
            distances[current] = depth
            for nxt in direct_dependencies.get(current, ()):
                queue.append((nxt, depth + 1))
        closure[start] = distances
    return closure


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attribute_value(node: ET.Element, attr_id: str) -> str:
    for child in list(node):
        if _local_name(child.tag) == "attribute" and child.attrib.get("id") == attr_id:
            return child.attrib.get("value", "")
    return ""


def _iter_dependency_module_short_desc(
    node: ET.Element,
    *,
    in_dependencies: bool = False,
    in_conflict: bool = False,
):
    node_id = node.attrib.get("id", "") if _local_name(node.tag) == "node" else ""
    dependencies = in_dependencies or node_id == "Dependencies"
    conflict = in_conflict or "conflict" in node_id.casefold()
    if dependencies and not conflict and node_id == "ModuleShortDesc":
        yield node
    for child in list(node):
        yield from _iter_dependency_module_short_desc(
            child,
            in_dependencies=dependencies,
            in_conflict=conflict,
        )


def parse_module_meta(text: str, *, expected_folder: str = "") -> tuple[ModuleInfo | None, tuple[str, ...]]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None, ()
    module_node: ET.Element | None = None
    for node in root.iter():
        if _local_name(node.tag) == "node" and node.attrib.get("id") == "ModuleInfo":
            module_node = node
            break
    if module_node is None:
        return None, ()
    folder = _attribute_value(module_node, "Folder")
    uuid = _attribute_value(module_node, "UUID")
    if not folder or not uuid or (expected_folder and folder != expected_folder):
        return None, ()

    dependencies: list[str] = []
    for node in _iter_dependency_module_short_desc(root):
        dep_uuid = _attribute_value(node, "UUID")
        if dep_uuid and dep_uuid != uuid:
            dependencies.append(dep_uuid)
    return ModuleInfo(folder=folder, uuid=uuid), tuple(dict.fromkeys(dependencies))


def resolve_by_module_dependency(
    child: Definition,
    candidates: Sequence[Definition],
    *,
    modules_by_folder: Mapping[str, ModuleInfo],
    direct_dependencies: Mapping[str, Iterable[str]],
    transitive_dependencies: Mapping[str, Mapping[str, int]],
) -> CandidateResolution:
    child_module = modules_by_folder.get(module_from_path(child.internal_path))
    if child_module is None:
        return CandidateResolution(
            "MetadataDoesNotCoverProvider",
            related_definition_ids=tuple(item.id for item in candidates),
        )

    direct = set(direct_dependencies.get(child_module.uuid, ()))
    transitive = set(transitive_dependencies.get(child_module.uuid, {}))
    direct_supported: list[Definition] = []
    transitive_supported: list[Definition] = []
    metadata_complete = True

    for candidate in candidates:
        candidate_module = modules_by_folder.get(module_from_path(candidate.internal_path))
        if candidate_module is None:
            metadata_complete = False
            continue
        if candidate_module.uuid in direct:
            direct_supported.append(candidate)
        elif candidate_module.uuid in transitive:
            transitive_supported.append(candidate)

    if len(direct_supported) == 1:
        return CandidateResolution(
            "ResolvedByDirectModuleDependency",
            direct_supported[0].id,
            tuple(item.id for item in candidates),
        )
    if not direct_supported and len(transitive_supported) == 1:
        return CandidateResolution(
            "ResolvedByTransitiveModuleDependency",
            transitive_supported[0].id,
            tuple(item.id for item in candidates),
        )
    if direct_supported or transitive_supported:
        return CandidateResolution(
            "AmbiguousMultiplePriorProviders",
            related_definition_ids=tuple(item.id for item in candidates),
        )
    if definitions_equivalent((child, *candidates)):
        return CandidateResolution(
            "EquivalentProviderDefinition",
            related_definition_ids=tuple(item.id for item in candidates),
        )
    return CandidateResolution(
        "SupportedButRuntimeWinnerUnproven" if metadata_complete else "MetadataDoesNotCoverProvider",
        related_definition_ids=tuple(item.id for item in candidates),
    )


def reconcile_definition(
    child: Definition,
    definitions_by_name: Mapping[str, Sequence[Definition]],
    *,
    modules_by_folder: Mapping[str, ModuleInfo],
    direct_dependencies: Mapping[str, Iterable[str]],
    transitive_dependencies: Mapping[str, Mapping[str, int]],
) -> CandidateResolution:
    candidates = exact_parent_candidates(child, definitions_by_name)
    if not candidates:
        return CandidateResolution("InheritedReferenceMissingParent")
    if child.name != child.using:
        if len(candidates) == 1:
            return CandidateResolution(
                "ResolvedUniqueCompatibleDefinition",
                candidates[0].id,
                (candidates[0].id,),
            )
        if definitions_equivalent(candidates):
            return CandidateResolution(
                "EquivalentProviderDefinition",
                related_definition_ids=tuple(item.id for item in candidates),
            )
        return CandidateResolution(
            "AmbiguousMultipleDefinitions",
            related_definition_ids=tuple(item.id for item in candidates),
        )
    return resolve_by_module_dependency(
        child,
        candidates,
        modules_by_folder=modules_by_folder,
        direct_dependencies=direct_dependencies,
        transitive_dependencies=transitive_dependencies,
    )


def inherited_field_map(
    child_fields: Iterable[str],
    parent_chain: Sequence[Definition],
) -> dict[str, tuple[str, str, int]]:
    seen = set(child_fields)
    inherited: dict[str, tuple[str, str, int]] = {}
    for depth, parent in enumerate(parent_chain, 1):
        for field_name, raw_value in parent.fields.items():
            if field_name in seen:
                continue
            seen.add(field_name)
            inherited[field_name] = (raw_value, parent.provider, depth)
    return inherited


def reconcile_precedence(
    candidate_definitions: Sequence[Definition],
    support_definitions: Sequence[Definition],
    *,
    target_uids: set[str],
    related_content_uids_by_edge: Mapping[str, Iterable[str]],
    modules_by_folder: Mapping[str, ModuleInfo],
    direct_dependencies: Mapping[str, Iterable[str]],
    package_layer_hold_uids: Iterable[str] = (),
) -> PrecedenceOutcome:
    all_definitions: dict[str, Definition] = {}
    for definition in (*candidate_definitions, *support_definitions):
        all_definitions.setdefault(definition.id, definition)
    by_name: dict[str, list[Definition]] = defaultdict(list)
    for definition in all_definitions.values():
        by_name[definition.name].append(definition)
    transitive = dependency_closure(direct_dependencies)

    holds = set(package_layer_hold_uids) & target_uids
    warnings: set[str] = set()
    ambiguous_edges = 0
    self_name_warning_edges = 0
    equivalent_edges = 0
    direct_resolved = 0
    transitive_resolved = 0

    for child in candidate_definitions:
        if not child.using:
            continue
        candidates = exact_parent_candidates(child, by_name)
        if not candidates:
            continue

        if child.name != child.using:
            same_provider = tuple(
                candidate for candidate in candidates
                if candidate.provider == child.provider
            )
            if len(same_provider) == 1:
                # Phase 4AV resolves a unique exact parent in the same provider
                # before Phase 4AW/4AX cross-provider reconciliation.
                continue

        related = set(related_content_uids_by_edge.get(child.id, ())) & target_uids

        if child.name != child.using:
            if definitions_equivalent(candidates):
                if len(candidates) > 1:
                    equivalent_edges += 1
                continue
            if len(candidates) > 1:
                ambiguous_edges += 1
                holds.update(related)
            continue

        resolution = resolve_by_module_dependency(
            child,
            candidates,
            modules_by_folder=modules_by_folder,
            direct_dependencies=direct_dependencies,
            transitive_dependencies=transitive,
        )
        if resolution.status == "ResolvedByDirectModuleDependency":
            direct_resolved += 1
        elif resolution.status == "ResolvedByTransitiveModuleDependency":
            transitive_resolved += 1
        elif resolution.status in {"SupportedButRuntimeWinnerUnproven", "MetadataDoesNotCoverProvider"}:
            self_name_warning_edges += 1
            warnings.update(related)
        elif resolution.status == "EquivalentProviderDefinition":
            equivalent_edges += 1
        elif resolution.status == "AmbiguousMultiplePriorProviders":
            self_name_warning_edges += 1
            warnings.update(related)

    return PrecedenceOutcome(
        hold_uids=frozenset(holds),
        warning_uids=frozenset(warnings - holds),
        ambiguous_edge_count=ambiguous_edges,
        self_name_warning_edge_count=self_name_warning_edges,
        equivalent_edge_count=equivalent_edges,
        direct_dependency_resolved_count=direct_resolved,
        transitive_dependency_resolved_count=transitive_resolved,
    )
