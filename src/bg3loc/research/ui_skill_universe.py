from __future__ import annotations

import csv
import re
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from bg3loc.backends import ArchiveBackend
from bg3loc.research.model import HANDLE_PATTERN

RULE_UI_SKILL_PROVIDER_UNIVERSE = "BG3-UI-SKILL-PROVIDER-UNIVERSE"
RULE_UI_SKILL_INHERITANCE = "BG3-UI-SKILL-INHERITANCE-CLOSURE"

PACKAGE_SCOPE = ("Game.pak", "Gustav.pak", "GustavX.pak", "Patch8_HotFix9.pak", "Shared.pak")
MODULE_PROJECTIONS = ("Shared", "SharedDev", "Gustav", "GustavDev", "GustavX")
ENGINE_UI_PROJECTION = "Engine/Game UI projection"


class UiSkillProviderRole(StrEnum):
    CANDIDATE_EVIDENCE = "CandidateEvidence"
    CONTEXT_EVIDENCE_ONLY = "ContextEvidenceOnly"
    CONTEXT_EVIDENCE_AND_COLLISION_PROVENANCE = "ContextEvidenceAndCollisionProvenance"


@dataclass(frozen=True, slots=True)
class UiSkillFamilyRule:
    name: str
    packages: frozenset[str]
    pattern: re.Pattern[str]
    subfamily: str
    domains: tuple[str, ...]


DIRECT_FAMILY_RULES: tuple[UiSkillFamilyRule, ...] = (
    UiSkillFamilyRule("SpellData", frozenset(PACKAGE_SCOPE), re.compile(r"/Stats/Generated/Data/Spell_[^/]+\.txt$", re.I), "Spell", ("Ability.Spell", "Ability.Cantrip", "Ability.ClassAction", "Ability.WeaponAction")),
    UiSkillFamilyRule("PassiveData", frozenset(PACKAGE_SCOPE), re.compile(r"/Stats/Generated/Data/Passive\.txt$", re.I), "Passive", ("Ability.Passive", "Ability.ClassFeature")),
    UiSkillFamilyRule("StatusData", frozenset(PACKAGE_SCOPE), re.compile(r"/Stats/Generated/Data/Status_[^/]+\.txt$", re.I), "Status", ("Ability.Status", "Ability.Condition")),
    UiSkillFamilyRule("InterruptData", frozenset(PACKAGE_SCOPE), re.compile(r"/Stats/Generated/Data/Interrupt\.txt$", re.I), "InterruptReaction", ("Ability.Interrupt", "Ability.Reaction")),
    UiSkillFamilyRule("Progressions", frozenset(PACKAGE_SCOPE), re.compile(r"(^|/)[^/]*Progression[^/]*\.(lsx|lsf|txt)$", re.I), "Progression", ("Ability.Progression", "UI.LevelUp")),
    UiSkillFamilyRule("ClassDescriptions", frozenset(PACKAGE_SCOPE), re.compile(r"(^|/)ClassDescriptions?\.(lsx|lsf|txt)$", re.I), "Class", ("Ability.ClassFeature", "UI.CharacterCreation", "UI.LevelUp")),
    UiSkillFamilyRule("FeatDescriptions", frozenset(PACKAGE_SCOPE), re.compile(r"(^|/)(FeatDescriptions?|Feats)\.(lsx|lsf|txt)$", re.I), "Feat", ("Ability.Feat", "UI.LevelUp")),
    UiSkillFamilyRule("ActionResourceDefinitions", frozenset(PACKAGE_SCOPE), re.compile(r"(^|/)[^/]*ActionResource[^/]*\.(lsx|lsf|txt|xaml)$", re.I), "ActionResource", ("Ability.ActionResource", "UI.HUD", "UI.CombatInterface")),
    UiSkillFamilyRule("Weapon/Armor/Object Stats", frozenset(PACKAGE_SCOPE), re.compile(r"/Stats/Generated/Data/(Weapon|Armor|Object)\.txt$", re.I), "WeaponArmorObject", ("Item.Unknown", "Ability.WeaponAction", "UI.Tooltip")),
    UiSkillFamilyRule("Root Templates", frozenset(PACKAGE_SCOPE), re.compile(r"/RootTemplates/[^/]+\.(lsf|lsx)$", re.I), "RootTemplate", ("Item.Unknown", "Ability.Unknown", "UI.Tooltip")),
    UiSkillFamilyRule("UI/GUI definitions", frozenset(PACKAGE_SCOPE), re.compile(r"\.xaml$", re.I), "Xaml", ("UI.Unknown",)),
    UiSkillFamilyRule("Tutorial definitions", frozenset(PACKAGE_SCOPE), re.compile(r"Tutorial[^/]*\.(xaml|lsx|lsf|txt)$", re.I), "Tutorial", ("UI.Tutorial",)),
    UiSkillFamilyRule("System message definitions", frozenset(PACKAGE_SCOPE), re.compile(r"(SystemMessage|MessageBox|Notification)[^/]*\.(xaml|lsx|lsf|txt)$", re.I), "SystemMessage", ("UI.SystemPrompt", "UI.ErrorMessage")),
)

_HANDLE_RE = re.compile(r"(?<![A-Za-z0-9_])(?P<uid>h[0-9a-f]{8}g[0-9a-f]{4}g[0-9a-f]{4}g[0-9a-f]{4}g[0-9a-f]{12})(?:;(?P<ver>[0-9]+))?(?![A-Za-z0-9_])", re.I)
_ENTRY_RE = re.compile(r'^\s*new\s+entry\s+"(?P<name>[^"]+)"\s*$', re.I)
_TYPE_RE = re.compile(r'^\s*type\s+"(?P<value>[^"]*)"\s*$', re.I)
_USING_RE = re.compile(r'^\s*using\s+"(?P<value>[^"]*)"\s*$', re.I)
_DATA_RE = re.compile(r'^\s*data\s+"(?P<name>[^"]+)"\s+"(?P<value>.*)"\s*$', re.I)
_MODULE_RE = re.compile(r"^(Public|Mods)/([^/]+)/", re.I)
_XML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


@dataclass(frozen=True, slots=True)
class UiSkillProvider:
    package: str
    internal_path: str
    resource_format: str
    module: str
    source_families: tuple[str, ...]
    source_subfamilies: tuple[str, ...]
    domain_candidates: tuple[str, ...]
    collision: bool = False
    role: UiSkillProviderRole = UiSkillProviderRole.CANDIDATE_EVIDENCE
    collision_provenance: bool = False

    @property
    def identity(self) -> str:
        return f"{self.package}::{self.internal_path}"


@dataclass(frozen=True, slots=True)
class UiSkillOccurrence:
    content_uid: str
    provider: str
    package: str
    internal_path: str
    source_families: tuple[str, ...]
    domains: tuple[str, ...]
    entity_type: str
    entity_name: str
    field_name: str
    parent_name: str = ""
    inheritance_depth: int = 0
    explicit_or_inherited: str = "explicit"
    comment_only: bool = False
    defining_provider: str = ""


@dataclass(slots=True)
class UiSkillUniverseResult:
    providers: list[UiSkillProvider] = field(default_factory=list)
    direct_occurrences: list[UiSkillOccurrence] = field(default_factory=list)
    materialized_occurrences: list[UiSkillOccurrence] = field(default_factory=list)
    hold_uids: set[str] = field(default_factory=set)
    raw_reference_count: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def unique_uids(self) -> set[str]:
        return {item.content_uid for item in self.materialized_occurrences if not item.comment_only}


def normalize_internal_path(value: str) -> str:
    value = value.replace("\\", "/").lstrip("/")
    if not value or "\x00" in value or ":" in value or any(part == ".." for part in value.split("/")):
        raise ValueError(f"unsafe archive path: {value!r}")
    if any(ch in value for ch in "*?[]"):
        raise ValueError(f"glob archive path is not allowed: {value!r}")
    return value


def resource_format(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".xaml"):
        return "XAML"
    if lower.endswith(".lsx"):
        return "LSX"
    if lower.endswith(".lsf"):
        return "LSF"
    if lower.endswith(".txt") and re.search(r"/Stats/", path, re.I):
        return "StatsTXT"
    if lower.endswith(".txt"):
        return "OtherTXT"
    return "Unknown"


def _module(path: str) -> str:
    match = _MODULE_RE.match(path)
    return match.group(2) if match else "Unresolved"


def _direct_matches(package: str, path: str) -> list[UiSkillFamilyRule]:
    probe = "/" + path
    return [rule for rule in DIRECT_FAMILY_RULES if package in rule.packages and rule.pattern.search(probe)]


def _projection_families(path: str, format_name: str) -> tuple[str, ...]:
    module = _module(path)
    result: list[str] = []
    if module in MODULE_PROJECTIONS:
        result.append(f"{module} module projection")
    if format_name == "XAML" and (module == "Game" or "/GUI/" in f"/{path}"):
        result.append(ENGINE_UI_PROJECTION)
    return tuple(result)


def provider_semantic_role(
    *, package: str, internal_path: str, module: str,
    source_families: Sequence[str], resource_format_name: str,
) -> UiSkillProviderRole:
    """Classify the deterministic context-research provider boundary."""
    normalized = "/" + internal_path.replace("\\", "/").lstrip("/")
    lower = normalized.lower()
    families = set(source_families)

    shared_context = package == "Shared.pak" and (
        "/stats/generated/data/" in lower
        or "/story/rawfiles/goals/" in lower
    )
    gustavx_context = (
        package == "GustavX.pak"
        and resource_format_name == "StatsTXT"
        and "/stats/generated/data/" in lower
    )
    gustav_passive_context = package == "Gustav.pak" and lower.endswith("/passive.txt")
    honour_projectile_pilot = (
        package == "Gustav.pak"
        and module == "Honour"
        and "SpellData" in families
        and lower.endswith("/spell_projectile.txt")
    )

    if shared_context and module in {"Shared", "SharedDev"} and "StatusData" in families and lower.endswith("/status_boost.txt"):
        return UiSkillProviderRole.CONTEXT_EVIDENCE_AND_COLLISION_PROVENANCE
    if shared_context or gustavx_context or gustav_passive_context or honour_projectile_pilot:
        return UiSkillProviderRole.CONTEXT_EVIDENCE_ONLY
    return UiSkillProviderRole.CANDIDATE_EVIDENCE


def discover_ui_skill_providers(game_dir: Path, backend: ArchiveBackend) -> list[UiSkillProvider]:
    raw: dict[tuple[str, str], tuple[list[UiSkillFamilyRule], str]] = {}
    by_normalized_path: dict[str, set[str]] = defaultdict(set)
    data_dir = game_dir / "Data"
    for package in PACKAGE_SCOPE:
        pak = data_dir / package
        if not pak.is_file():
            continue
        for entry in backend.list_archive(pak):
            try:
                path = normalize_internal_path(entry.path)
            except ValueError:
                continue
            matches = _direct_matches(package, path)
            if not matches:
                continue
            raw[(package, entry.path)] = (matches, path)
            by_normalized_path[path.casefold()].add(package)

    providers: list[UiSkillProvider] = []
    for (package, _original), (matches, path) in raw.items():
        collision = len(by_normalized_path[path.casefold()]) > 1
        format_name = resource_format(path)
        source_families = tuple(sorted({
            *(rule.name for rule in matches),
            *_projection_families(path, format_name),
        }))
        module = _module(path)
        role = provider_semantic_role(
            package=package,
            internal_path=path,
            module=module,
            source_families=source_families,
            resource_format_name=format_name,
        )
        providers.append(UiSkillProvider(
            package=package,
            internal_path=path,
            resource_format=format_name,
            module=module,
            source_families=source_families,
            source_subfamilies=tuple(sorted({rule.subfamily for rule in matches})),
            domain_candidates=tuple(sorted({domain for rule in matches for domain in rule.domains})),
            collision=collision,
            role=role,
            collision_provenance=role is UiSkillProviderRole.CONTEXT_EVIDENCE_AND_COLLISION_PROVENANCE,
        ))
    return sorted(providers, key=lambda item: (item.package, item.internal_path))


def _domain(provider: UiSkillProvider) -> tuple[str, ...]:
    families = " ".join(provider.source_families)
    path = provider.internal_path
    if re.search(r"UI|Tutorial|System", families, re.I):
        if re.search(r"Tutorial", path, re.I):
            return ("UI.Tutorial",)
        if re.search(r"Error|Message|Notification", path, re.I):
            return ("UI.SystemPrompt",)
        if re.search(r"Inventory|Equipment", path, re.I):
            return ("UI.Inventory",)
        if re.search(r"HUD|Hotbar|ActionResource", path, re.I):
            return ("UI.HUD",)
        return ("UI.Unknown",)
    if re.search(r"Spell|Passive|Status|Interrupt|Progression|Class|Feat|ActionResource", families, re.I):
        return ("Ability.Unknown",)
    if re.search(r"Weapon|Armor|Object|Template", families, re.I):
        return ("Item.Unknown",)
    return provider.domain_candidates or ("Unknown",)


def _iter_uids(value: str) -> Iterator[str]:
    for match in _HANDLE_RE.finditer(value or ""):
        yield match.group("uid")


def _parse_stats(text: str, provider: UiSkillProvider) -> list[UiSkillOccurrence]:
    result = _line_comment_occurrences(text, provider)
    entity = ""
    entity_type = "StatsRecord"
    parent = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        match = _ENTRY_RE.match(line)
        if match:
            entity = match.group("name")
            entity_type = "StatsRecord"
            parent = ""
            continue
        match = _TYPE_RE.match(line)
        if match and entity:
            entity_type = match.group("value") or "StatsRecord"
            continue
        match = _USING_RE.match(line)
        if match and entity:
            parent = match.group("value")
            continue
        match = _DATA_RE.match(line)
        if match and entity:
            for uid in _iter_uids(match.group("value")):
                result.append(UiSkillOccurrence(
                    content_uid=uid,
                    provider=provider.identity,
                    package=provider.package,
                    internal_path=provider.internal_path,
                    source_families=provider.source_families,
                    domains=_domain(provider),
                    entity_type=entity_type,
                    entity_name=entity,
                    field_name=match.group("name"),
                    parent_name=parent,
                ))
    return result


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_xml(text: str, provider: UiSkillProvider) -> list[UiSkillOccurrence]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    result: list[UiSkillOccurrence] = []
    for index, comment in enumerate(_XML_COMMENT_RE.findall(text), 1):
        for uid in _iter_uids(comment):
            result.append(UiSkillOccurrence(
                uid, provider.identity, provider.package, provider.internal_path,
                provider.source_families, _domain(provider), "Document",
                Path(provider.internal_path).name, f"XmlComment:{index}", comment_only=True,
            ))
    element_ord = 0

    def walk(node: ET.Element, enclosing_entity: str = "", enclosing_type: str = "") -> None:
        nonlocal element_ord
        element_ord += 1
        local = _local_name(node.tag)
        entity_name = enclosing_entity
        entity_type = enclosing_type
        if provider.resource_format == "XAML":
            name = next((value for key, value in node.attrib.items() if _local_name(key) in {"Name", "Key", "MapKey", "UUID"} and value), "")
            if name:
                entity_name = name
                entity_type = local
        elif local == "node":
            entity_type = node.attrib.get("id", "node")
            direct_identity = next(
                (
                    child.attrib.get("value", "") or child.attrib.get("handle", "")
                    for child in list(node)
                    if _local_name(child.tag) == "attribute"
                    and child.attrib.get("id", "") in {"UUID", "MapKey", "Name", "ID", "Guid", "GUID"}
                    and (child.attrib.get("value") or child.attrib.get("handle"))
                ),
                "",
            )
            entity_name = (
                next(
                    (node.attrib.get(key, "") for key in ("Name", "Key", "MapKey", "UUID") if node.attrib.get(key)),
                    "",
                )
                or direct_identity
                or f"{node.attrib.get('id', 'node')}#{element_ord}"
            )

        if provider.resource_format == "XAML":
            for key, value in node.attrib.items():
                field = _local_name(key)
                if field == "xmlns" or key.startswith("{http://www.w3.org/2000/xmlns/"):
                    continue
                for uid in _iter_uids(value):
                    result.append(UiSkillOccurrence(uid, provider.identity, provider.package, provider.internal_path, provider.source_families, _domain(provider), entity_type or local, entity_name or f"{local}#{element_ord}", field))
            if node.text and node.text.strip():
                for uid in _iter_uids(node.text):
                    result.append(UiSkillOccurrence(uid, provider.identity, provider.package, provider.internal_path, provider.source_families, _domain(provider), entity_type or local, entity_name or f"{local}#{element_ord}", "#text"))
        elif local == "attribute":
            field = node.attrib.get("id", "")
            value = node.attrib.get("handle", "") or node.attrib.get("value", "")
            for uid in _iter_uids(value):
                result.append(UiSkillOccurrence(uid, provider.identity, provider.package, provider.internal_path, provider.source_families, _domain(provider), enclosing_type or "node", enclosing_entity or "document", field or "attribute"))

        for child in list(node):
            walk(child, entity_name, entity_type)

    walk(root)
    return result


def _parse_unknown(text: str, provider: UiSkillProvider) -> list[UiSkillOccurrence]:
    result: list[UiSkillOccurrence] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        comment = stripped.startswith("//") or stripped.startswith("#") or "<!--" in line
        for uid in _iter_uids(line):
            result.append(UiSkillOccurrence(uid, provider.identity, provider.package, provider.internal_path, provider.source_families, _domain(provider), "Document", Path(provider.internal_path).name, f"RawLine:{line_no}", comment_only=comment))
    return result


def _line_comment_occurrences(text: str, provider: UiSkillProvider) -> list[UiSkillOccurrence]:
    result: list[UiSkillOccurrence] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if not (stripped.startswith("//") or stripped.startswith("#")):
            continue
        for uid in _iter_uids(line):
            result.append(UiSkillOccurrence(
                uid, provider.identity, provider.package, provider.internal_path,
                provider.source_families, _domain(provider), "Document",
                Path(provider.internal_path).name, f"CommentLine:{line_no}", comment_only=True,
            ))
    return result


def _read_provider_text(path: Path, provider: UiSkillProvider, backend: ArchiveBackend | None) -> str:
    parse_path = path
    if provider.resource_format == "LSF":
        if backend is None:
            raise ValueError("LSF parsing requires archive backend conversion support")
        converted = path.with_suffix(path.suffix + ".lsx")
        backend.convert_resource(path, converted)
        parse_path = converted
    return parse_path.read_text(encoding="utf-8-sig", errors="replace")


def _parse_provider_text(text: str, provider: UiSkillProvider) -> list[UiSkillOccurrence]:
    if provider.resource_format == "StatsTXT":
        return _parse_stats(text, provider)
    if provider.resource_format in {"XAML", "LSX", "LSF"}:
        return _parse_xml(text, provider)
    return _parse_unknown(text, provider)


def parse_ui_skill_provider(path: Path, provider: UiSkillProvider, backend: ArchiveBackend | None = None) -> list[UiSkillOccurrence]:
    return _parse_provider_text(_read_provider_text(path, provider, backend), provider)


def _materialize_inheritance(occurrences: Sequence[UiSkillOccurrence]) -> tuple[list[UiSkillOccurrence], set[str]]:
    direct = [item for item in occurrences if not item.comment_only]
    by_provider_entity: dict[tuple[str, str], list[UiSkillOccurrence]] = defaultdict(list)
    parent_by_provider_entity: dict[tuple[str, str], str] = {}
    for item in direct:
        key = (item.provider, item.entity_name)
        by_provider_entity[key].append(item)
        if item.parent_name:
            parent_by_provider_entity[key] = item.parent_name

    result = list(direct)
    holds: set[str] = set()

    # Multiple package providers are retained.  Precedence is ambiguous only
    # when the same normalized resource/entity/field has non-equivalent values;
    # same-named elements in unrelated resources are not provider definitions.
    definitions: dict[tuple[str, str, str, str], list[UiSkillOccurrence]] = defaultdict(list)
    for item in direct:
        definitions[(
            item.internal_path.casefold(), item.entity_type,
            item.entity_name, item.field_name,
        )].append(item)
    for rows in definitions.values():
        if len({item.provider for item in rows}) > 1 and len({item.content_uid for item in rows}) > 1:
            holds.update(item.content_uid for item in rows)

    global_entities: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for provider, entity in by_provider_entity:
        entity_type = by_provider_entity[(provider, entity)][0].entity_type
        global_entities[(entity_type, entity)].append((provider, entity))

    for key, parent in parent_by_provider_entity.items():
        provider, child_name = key
        child_fields = {item.field_name for item in by_provider_entity[key]}
        visited = {child_name}
        depth = 1
        current = parent
        while current:
            if current in visited:
                holds.update(item.content_uid for item in by_provider_entity[key])
                break
            visited.add(current)
            parent_key = (provider, current)
            parent_records = by_provider_entity.get(parent_key, [])
            if not parent_records:
                entity_type = by_provider_entity[key][0].entity_type
                candidates = global_entities.get((entity_type, current), [])
                signatures = {
                    tuple(sorted((item.field_name, item.content_uid) for item in by_provider_entity[candidate]))
                    for candidate in candidates
                }
                if len(signatures) > 1:
                    holds.update(item.content_uid for item in by_provider_entity[key])
                    holds.update(
                        item.content_uid for candidate in candidates
                        for item in by_provider_entity[candidate]
                    )
                    break
                if candidates:
                    parent_key = sorted(candidates)[0]
                    parent_records = by_provider_entity[parent_key]
            if not parent_records:
                break
            for item in parent_records:
                if item.field_name in child_fields:
                    continue
                child_fields.add(item.field_name)
                result.append(UiSkillOccurrence(
                    content_uid=item.content_uid,
                    provider=provider,
                    package=item.package,
                    internal_path=item.internal_path,
                    source_families=item.source_families,
                    domains=item.domains,
                    entity_type=by_provider_entity[key][0].entity_type,
                    entity_name=child_name,
                    field_name=item.field_name,
                    parent_name=current,
                    inheritance_depth=depth,
                    explicit_or_inherited="inherited",
                    defining_provider=item.defining_provider or item.provider,
                ))
            current = parent_by_provider_entity.get(parent_key, "")
            depth += 1
    return result, holds


def extract_ui_skill_universe(game_dir: Path, backend: ArchiveBackend, output_dir: Path) -> UiSkillUniverseResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    providers = discover_ui_skill_providers(game_dir, backend)
    occurrences: list[UiSkillOccurrence] = []
    raw_reference_count = 0
    with tempfile.TemporaryDirectory(dir=output_dir) as tmp:
        temp = Path(tmp)
        for index, provider in enumerate(providers):
            if provider.role is not UiSkillProviderRole.CANDIDATE_EVIDENCE:
                continue
            package_path = game_dir / "Data" / provider.package
            suffix = Path(provider.internal_path).suffix or ".txt"
            extracted = temp / f"{index:04d}{suffix}"
            backend.extract_single_file(package_path, provider.internal_path, extracted)
            text = _read_provider_text(extracted, provider, backend)
            raw_reference_count += sum(1 for _ in _HANDLE_RE.finditer(text))
            occurrences.extend(_parse_provider_text(text, provider))
    materialized, holds = _materialize_inheritance(occurrences)
    return UiSkillUniverseResult(
        providers=providers,
        direct_occurrences=occurrences,
        materialized_occurrences=materialized,
        hold_uids=holds,
        raw_reference_count=raw_reference_count,
    )


def classify_workstream(occurrences: Sequence[UiSkillOccurrence]) -> str:
    evidence = " ".join(
        [
            *(domain for item in occurrences for domain in item.domains),
            *(family for item in occurrences for family in item.source_families),
            *(item.entity_type for item in occurrences),
            *(item.provider for item in occurrences),
        ]
    )
    if re.search(r"Ability\.|SpellData|StatusData|PassiveData|InterruptData|Progression|ActionResource|ClassFeature|Feat", evidence, re.I):
        return "AbilitySkill"
    if re.search(r"Root Templates|GameObjects|Weapon|Armor|\bItem\b|Template", evidence, re.I):
        return "ItemsEquipment"
    if re.search(r"Tutorial definitions|UnifiedTutorial|ModalTutorial|Tutorials/|SystemMessage", evidence, re.I):
        return "TutorialSystem"
    if re.search(r"UI\.Other|UI/GUI definitions|XAML|MainUI/GUI|\bGUI\b", evidence, re.I):
        return "UserInterface"
    return "OtherMultiDomain"


def write_ui_skill_provider_ledger(path: Path, providers: Sequence[UiSkillProvider]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Package", "InternalPath", "ResourceFormat", "Module", "SourceFamilies", "SourceSubfamilies", "DomainCandidates", "SemanticRole", "ExactPathCollision", "CollisionProvenance"])
        for item in providers:
            writer.writerow([item.package, item.internal_path, item.resource_format, item.module, ";".join(item.source_families), ";".join(item.source_subfamilies), ";".join(item.domain_candidates), item.role.value, str(item.collision).lower(), str(item.collision_provenance).lower()])


def write_ui_skill_universe(
    path: Path,
    occurrences: Sequence[UiSkillOccurrence],
    hold_uids: set[str] | None = None,
    aq_uids: set[str] | None = None,
    locale_hold_uids: set[str] | None = None,
) -> None:
    hold_uids = hold_uids or set()
    aq_uids = aq_uids or set()
    locale_hold_uids = locale_hold_uids or set()
    by_uid: dict[str, list[UiSkillOccurrence]] = defaultdict(list)
    for item in occurrences:
        by_uid[item.content_uid].append(item)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "ContentUid", "Status", "Workstream", "Provider", "Package", "InternalPath",
            "SourceFamilies", "Domains", "EntityType", "EntityName", "FieldName",
            "ParentName", "InheritanceDepth", "ExplicitOrInherited", "CommentOnly",
            "DefiningProvider", "ProviderOverrideApplied",
        ])
        for uid in sorted(by_uid):
            rows = by_uid[uid]
            accepted = [item for item in rows if not item.comment_only]
            workstream = (
                "AQResourceReferencedReview" if uid in aq_uids
                else classify_workstream(accepted or rows)
            )
            uid_status = "Hold" if uid in hold_uids or uid in locale_hold_uids else "Eligible"
            for item in sorted(rows, key=lambda value: (
                value.comment_only, value.provider, value.internal_path, value.entity_name,
                value.field_name, value.inheritance_depth, value.content_uid,
            )):
                writer.writerow([
                    uid,
                    "ExcludedCommentOnly" if item.comment_only else uid_status,
                    workstream,
                    item.provider,
                    item.package,
                    item.internal_path,
                    ";".join(item.source_families),
                    ";".join(item.domains),
                    item.entity_type,
                    item.entity_name,
                    item.field_name,
                    item.parent_name,
                    item.inheritance_depth,
                    item.explicit_or_inherited,
                    str(item.comment_only).lower(),
                    item.defining_provider or item.provider,
                    str(bool(item.defining_provider and item.defining_provider != item.provider)).lower(),
                ])
