from __future__ import annotations

import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from bg3loc.backends import ArchiveBackend
from bg3loc.research.ui_skill_precedence import (
    Definition,
    ModuleInfo,
    MODULE_META_FOLDERS,
    definition_uids,
    is_aw_support_provider,
    parse_module_meta,
    parse_stats_definitions,
    reconcile_precedence,
)
from bg3loc.research.ui_skill_universe import (
    PACKAGE_SCOPE,
    UiSkillOccurrence,
    UiSkillProvider,
    UiSkillProviderRole,
)


@dataclass(frozen=True, slots=True)
class RuntimeReconciliation:
    materialized_occurrences: tuple[UiSkillOccurrence, ...]
    hold_uids: frozenset[str]
    warning_uids: frozenset[str]
    candidate_definition_count: int
    support_provider_count: int
    support_definition_count: int
    raw_using_edge_count: int
    inherited_relation_count: int
    ambiguous_edge_count: int
    self_name_warning_edge_count: int
    equivalent_edge_count: int
    direct_dependency_resolved_count: int
    transitive_dependency_resolved_count: int
    package_layer_hold_count: int
    module_count: int
    direct_dependency_count: int


def _module_from_path(path: str) -> str:
    parts = path.replace("\\", "/").split("/")
    return parts[1] if len(parts) >= 2 and parts[0] in {"Public", "Mods"} else ""


def _extract_text(
    game_dir: Path,
    backend: ArchiveBackend,
    *,
    package: str,
    internal_path: str,
    destination: Path,
) -> str:
    backend.extract_single_file(game_dir / "Data" / package, internal_path, destination)
    return destination.read_text(encoding="utf-8-sig", errors="replace")


def _candidate_stats_definitions(
    game_dir: Path,
    backend: ArchiveBackend,
    providers: Sequence[UiSkillProvider],
    temp: Path,
) -> list[Definition]:
    result: list[Definition] = []
    index = 0
    for provider in providers:
        if provider.role is not UiSkillProviderRole.CANDIDATE_EVIDENCE or provider.resource_format != "StatsTXT":
            continue
        text = _extract_text(
            game_dir,
            backend,
            package=provider.package,
            internal_path=provider.internal_path,
            destination=temp / f"candidate-{index:04d}.txt",
        )
        result.extend(
            parse_stats_definitions(
                text,
                provider=provider.identity,
                internal_path=provider.internal_path,
            )
        )
        index += 1
    return result


def _support_stats_definitions(
    game_dir: Path,
    backend: ArchiveBackend,
    temp: Path,
) -> tuple[list[Definition], int]:
    result: list[Definition] = []
    provider_count = 0
    index = 0
    for package in PACKAGE_SCOPE:
        pak = game_dir / "Data" / package
        if not pak.is_file():
            continue
        for entry in backend.list_archive(pak):
            internal_path = entry.path.replace("\\", "/").lstrip("/")
            if not is_aw_support_provider(package, internal_path):
                continue
            provider_count += 1
            text = _extract_text(
                game_dir,
                backend,
                package=package,
                internal_path=internal_path,
                destination=temp / f"support-{index:04d}.txt",
            )
            result.extend(
                parse_stats_definitions(
                    text,
                    provider=f"{package}::{internal_path}",
                    internal_path=internal_path,
                )
            )
            index += 1
    return result, provider_count


def _module_evidence(
    game_dir: Path,
    backend: ArchiveBackend,
    temp: Path,
) -> tuple[dict[str, ModuleInfo], dict[str, set[str]]]:
    modules: dict[str, ModuleInfo] = {}
    dependencies: dict[str, set[str]] = defaultdict(set)
    seen_paths: set[tuple[str, str]] = set()
    index = 0
    for package in PACKAGE_SCOPE:
        pak = game_dir / "Data" / package
        if not pak.is_file():
            continue
        for entry in backend.list_archive(pak):
            internal_path = entry.path.replace("\\", "/").lstrip("/")
            parts = internal_path.split("/")
            if len(parts) != 3 or parts[0] != "Mods" or parts[2] != "meta.lsx" or parts[1] not in MODULE_META_FOLDERS:
                continue
            identity = (package, internal_path)
            if identity in seen_paths:
                continue
            seen_paths.add(identity)
            text = _extract_text(
                game_dir,
                backend,
                package=package,
                internal_path=internal_path,
                destination=temp / f"meta-{index:02d}.lsx",
            )
            info, required = parse_module_meta(text, expected_folder=parts[1])
            index += 1
            if info is None:
                continue
            previous = modules.get(info.folder)
            if previous is not None and previous.uuid != info.uuid:
                continue
            modules[info.folder] = info
            dependencies[info.uuid].update(required)
    return modules, dependencies


def _unique_same_provider_parent_map(
    candidate_definitions: Sequence[Definition],
    *,
    include_self_name: bool,
) -> dict[str, str]:
    by_provider_name: dict[tuple[str, str], list[Definition]] = defaultdict(list)
    for definition in candidate_definitions:
        by_provider_name[(definition.provider, definition.name)].append(definition)
    selected: dict[str, str] = {}
    for child in candidate_definitions:
        if not child.using or (not include_self_name and child.name == child.using):
            continue
        same = [
            item
            for item in by_provider_name.get((child.provider, child.using), ())
            if item.id != child.id
            and (
                not child.entity_type
                or not item.entity_type
                or item.entity_type == child.entity_type
            )
        ]
        if len(same) == 1:
            selected[child.id] = same[0].id
    return selected


def _same_provider_parent_map(candidate_definitions: Sequence[Definition]) -> dict[str, str]:
    return _unique_same_provider_parent_map(candidate_definitions, include_self_name=False)


def _definition_contains_occurrence(definition: Definition, occurrence: UiSkillOccurrence) -> bool:
    raw_value = definition.fields.get(occurrence.field_name)
    if raw_value is None:
        return False
    probe = Definition(
        id=definition.id,
        name=definition.name,
        entity_type=definition.entity_type,
        using=definition.using,
        fields={occurrence.field_name: raw_value},
        provider=definition.provider,
        internal_path=definition.internal_path,
    )
    return occurrence.content_uid in definition_uids(probe)


def _related_content_uids_by_edge(
    direct_occurrences: Sequence[UiSkillOccurrence],
    candidate_definitions: Sequence[Definition],
) -> dict[str, frozenset[str]]:
    by_provider_name: dict[tuple[str, str], list[Definition]] = defaultdict(list)
    for definition in candidate_definitions:
        by_provider_name[(definition.provider, definition.name)].append(definition)

    # Phase 4AV retained a selected same-provider parent for self-name edges even
    # though those edges were withheld from inherited materialization.  Phase 4AW
    # therefore records the unresolved self-name edge and continues through that
    # frozen selected-parent chain.
    frozen_parent = _unique_same_provider_parent_map(candidate_definitions, include_self_name=True)
    definitions_by_id = {definition.id: definition for definition in candidate_definitions}
    related: dict[str, set[str]] = defaultdict(set)

    for occurrence in direct_occurrences:
        if occurrence.comment_only or occurrence.explicit_or_inherited != "explicit":
            continue
        matching_definitions = [
            definition
            for definition in by_provider_name.get((occurrence.provider, occurrence.entity_name), ())
            if (
                occurrence.entity_type == "StatsRecord"
                or not occurrence.entity_type
                or not definition.entity_type
                or definition.entity_type == occurrence.entity_type
            )
        ]
        if len(matching_definitions) > 1:
            exact_field_matches = [
                definition
                for definition in matching_definitions
                if _definition_contains_occurrence(definition, occurrence)
            ]
            if len(exact_field_matches) == 1:
                matching_definitions = exact_field_matches
        if len(matching_definitions) != 1:
            continue

        current = matching_definitions[0]
        seen: set[str] = set()
        while current.id not in seen:
            seen.add(current.id)
            if not current.using:
                break

            parent_id = frozen_parent.get(current.id)
            unresolved = current.name == current.using or parent_id is None
            if unresolved:
                related[current.id].add(occurrence.content_uid)

            if parent_id is None:
                break
            parent = definitions_by_id.get(parent_id)
            if parent is None:
                break
            current = parent

    return {edge_id: frozenset(uids) for edge_id, uids in related.items()}


def _materialize_direct_inheritance(
    direct_occurrences: Sequence[UiSkillOccurrence],
    candidate_definitions: Sequence[Definition],
    providers: Sequence[UiSkillProvider],
) -> list[UiSkillOccurrence]:
    result = [item for item in direct_occurrences if not item.comment_only]
    definitions = {item.id: item for item in candidate_definitions}
    selected_parent = _same_provider_parent_map(candidate_definitions)
    provider_map = {item.identity: item for item in providers}

    for child in candidate_definitions:
        provider_meta = provider_map.get(child.provider)
        if provider_meta is None:
            continue
        seen_fields = set(child.fields)
        seen_defs = {child.id}
        current_id = child.id
        depth = 1
        while current_id in selected_parent:
            parent_id = selected_parent[current_id]
            if parent_id in seen_defs:
                break
            seen_defs.add(parent_id)
            parent = definitions.get(parent_id)
            if parent is None:
                break
            for field_name, raw_value in parent.fields.items():
                if field_name in seen_fields:
                    continue
                seen_fields.add(field_name)
                for uid in definition_uids(
                    Definition(
                        id=parent.id,
                        name=parent.name,
                        entity_type=parent.entity_type,
                        using=parent.using,
                        fields={field_name: raw_value},
                        provider=parent.provider,
                        internal_path=parent.internal_path,
                    )
                ):
                    result.append(
                        UiSkillOccurrence(
                            content_uid=uid,
                            provider=child.provider,
                            package=provider_meta.package,
                            internal_path=provider_meta.internal_path,
                            source_families=provider_meta.source_families,
                            domains=provider_meta.domain_candidates,
                            entity_type=child.entity_type or "StatsRecord",
                            entity_name=child.name,
                            field_name=field_name,
                            parent_name=parent.name,
                            inheritance_depth=depth,
                            explicit_or_inherited="inherited",
                            defining_provider=parent.provider,
                        )
                    )
            current_id = parent_id
            depth += 1
    return result


def _package_layer_hold_uids(
    direct_occurrences: Sequence[UiSkillOccurrence],
    providers: Sequence[UiSkillProvider],
) -> set[str]:
    provider_map = {item.identity: item for item in providers}
    by_path_package: dict[tuple[str, str], set[str]] = defaultdict(set)
    collision_paths: set[str] = set()
    for provider in providers:
        if not provider.collision or provider.resource_format != "XAML":
            continue
        if provider.package not in {"Game.pak", "Patch8_HotFix9.pak"}:
            continue
        normalized = provider.internal_path.casefold()
        # Historical Phase 4AY treated only the unresolved Game/Patch
        # CCLib_c.xaml package-layer collision as blocking.  Derive the UID
        # difference from the current game instead of hard-coding that UID.
        if not normalized.endswith("/gui/library/cclib_c.xaml"):
            continue
        collision_paths.add(normalized)
    for occurrence in direct_occurrences:
        provider = provider_map.get(occurrence.provider)
        if provider is None or provider.internal_path.casefold() not in collision_paths:
            continue
        if provider.package in {"Game.pak", "Patch8_HotFix9.pak"}:
            by_path_package[(provider.internal_path.casefold(), provider.package)].add(occurrence.content_uid)
    holds: set[str] = set()
    for path in collision_paths:
        game = by_path_package.get((path, "Game.pak"), set())
        patch = by_path_package.get((path, "Patch8_HotFix9.pak"), set())
        if game and patch and game != patch:
            holds.update(game ^ patch)
    return holds


def reconcile_ui_skill_runtime(
    game_dir: Path,
    backend: ArchiveBackend,
    providers: Sequence[UiSkillProvider],
    direct_occurrences: Sequence[UiSkillOccurrence],
) -> RuntimeReconciliation:
    target_uids = {item.content_uid for item in direct_occurrences if not item.comment_only}
    with tempfile.TemporaryDirectory() as temp_name:
        temp = Path(temp_name)
        candidate_definitions = _candidate_stats_definitions(game_dir, backend, providers, temp)
        support_definitions, support_provider_count = _support_stats_definitions(game_dir, backend, temp)
        modules, dependencies = _module_evidence(game_dir, backend, temp)

    materialized = _materialize_direct_inheritance(direct_occurrences, candidate_definitions, providers)
    package_holds = _package_layer_hold_uids(direct_occurrences, providers)
    related_content_uids = _related_content_uids_by_edge(direct_occurrences, candidate_definitions)
    outcome = reconcile_precedence(
        candidate_definitions,
        support_definitions,
        target_uids=target_uids,
        related_content_uids_by_edge=related_content_uids,
        modules_by_folder=modules,
        direct_dependencies=dependencies,
        package_layer_hold_uids=package_holds,
    )
    return RuntimeReconciliation(
        materialized_occurrences=tuple(materialized),
        hold_uids=outcome.hold_uids,
        warning_uids=outcome.warning_uids,
        candidate_definition_count=len(candidate_definitions),
        support_provider_count=support_provider_count,
        support_definition_count=len(support_definitions),
        raw_using_edge_count=sum(bool(item.using) for item in candidate_definitions),
        inherited_relation_count=sum(item.explicit_or_inherited == "inherited" for item in materialized),
        ambiguous_edge_count=outcome.ambiguous_edge_count,
        self_name_warning_edge_count=outcome.self_name_warning_edge_count,
        equivalent_edge_count=outcome.equivalent_edge_count,
        direct_dependency_resolved_count=outcome.direct_dependency_resolved_count,
        transitive_dependency_resolved_count=outcome.transitive_dependency_resolved_count,
        package_layer_hold_count=len(package_holds & target_uids),
        module_count=len(modules),
        direct_dependency_count=sum(len(items) for items in dependencies.values()),
    )
