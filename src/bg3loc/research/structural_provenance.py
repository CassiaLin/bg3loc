"""Public structural definitions, before any overlay/inheritance selection.

Digests cover whole definitions; output contains references, never field values.
This module deliberately has no production reliability or winner policy.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from typing import Iterable
import xml.etree.ElementTree as ET

from bg3loc.research.model import HANDLE_PATTERN

SCHEMA_VERSION = "public-structural-provenance/1"
PROJECTION_VERSION = "structural-definition/1"


class IdentityOrigin(StrEnum):
    UUID = "UUID"
    MAP_KEY = "MAP_KEY"
    NAME = "NAME"
    ENTRY_NAME = "ENTRY_NAME"
    ENTITY_ID = "ENTITY_ID"
    FALLBACK_ORDINAL = "FALLBACK_ORDINAL"
    FALLBACK_NODE = "FALLBACK_NODE"
    UNKNOWN = "UNKNOWN"


def canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def definition_fingerprint(payload: object) -> str:
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def relative_resource(value: str) -> str:
    value = value.replace("\\", "/")
    if (value.startswith("/") or ":" in value or ".." in value.split("/")
            or any(ord(ch) < 32 for ch in value)):
        raise ValueError("source resource must be a relative archive identity")
    return str(PurePosixPath(value)) if value else ""


def source_resource(package: str, resource: str) -> str:
    return "/".join(filter(None, (relative_resource(package), relative_resource(resource))))


@dataclass(frozen=True)
class StructuralOccurrence:
    content_uid: str
    field_name: str
    field_role: str
    version: str = ""
    location: int = 0


@dataclass(frozen=True)
class StructuralDefinition:
    definition_type: str
    entity_identity: str
    identity_origin: IdentityOrigin
    source_kind: str
    source_resource: str
    payload: dict = field(repr=False)
    occurrences: tuple[StructuralOccurrence, ...] = ()

    def __post_init__(self) -> None:
        relative_resource(self.source_resource)

    @cached_property
    def fingerprint(self) -> str:
        return definition_fingerprint(self.payload)

    def provenance(self) -> dict[str, str]:
        return {
            "entityIdentity": self.entity_identity,
            "identityOrigin": self.identity_origin.value,
            "sourceKind": self.source_kind,
            "sourceResource": self.source_resource,
            "definitionType": self.definition_type,
            "definitionFingerprint": self.fingerprint,
            "definitionProjectionVersion": PROJECTION_VERSION,
        }

    def to_dict(self) -> dict:
        row = {"schemaVersion": SCHEMA_VERSION, **self.provenance()}
        if self.definition_type == "StatsEntry":
            directives = self.payload["directives"]
            row.update(entryName=self.entity_identity,
                       entryType=directives.get("type", [""])[-1],
                       using=directives.get("using", [""])[-1])
        return row

    def occurrence_rows(self) -> list[dict]:
        # Preserve physical multiplicity within one definition, while repeated
        # sightings of the exact same definition/source can still deduplicate.
        indices: dict[tuple[str, str, str, str], int] = defaultdict(int)
        result = []
        for item in self.occurrences:
            key = (item.content_uid, item.field_name, item.field_role, item.version)
            indices[key] += 1
            result.append({**self.to_dict(), "contentUid": item.content_uid,
                           "fieldName": item.field_name, "fieldRole": item.field_role,
                           "version": item.version, "occurrenceIndex": indices[key]})
        return result


_ENTRY = re.compile(r'^new\s+entry\s+"([^"]+)"\s*$', re.I)
_DIRECTIVE = re.compile(r'^(type|using)\s+"([^"]*)"\s*$', re.I)
_DATA = re.compile(r'^data\s+"([^"]+)"\s+"(.*)"\s*$', re.I)


def _stats_statement(raw: str) -> str:
    """Strip line comments only outside quoted semantic values."""
    quoted = False
    escaped = False
    for index, char in enumerate(raw):
        if char == '"' and not escaped:
            quoted = not quoted
        if not quoted and (char == "#" or raw[index:index + 2] == "//"):
            return raw[:index].strip()
        escaped = char == "\\" and not escaped
    return raw.strip()


def parse_structural_stats(text: str, *, resource_path: str = "",
                           package: str = "") -> list[StructuralDefinition]:
    resource = source_resource(package, resource_path)
    result: list[StructuralDefinition] = []
    name = ""
    directives: dict[str, list[str]] = defaultdict(list)
    fields: dict[str, list[str]] = defaultdict(list)
    unknown: list[str] = []
    occurrences: list[StructuralOccurrence] = []

    def flush() -> None:
        if not name:
            return
        # Repeated assignments retain their order, distinct fields do not.
        payload = {"projectionVersion": PROJECTION_VERSION,
                   "definitionType": "StatsEntry", "entryName": name,
                   "directives": dict(directives), "fields": dict(fields),
                   "unrecognizedStatements": list(unknown)}
        result.append(StructuralDefinition("StatsEntry", name, IdentityOrigin.ENTRY_NAME,
                                           "StatsDefinition", resource, payload,
                                           tuple(occurrences)))

    for index, raw in enumerate(text.splitlines(), 1):
        line = _stats_statement(raw)
        if not line:
            continue
        match = _ENTRY.fullmatch(line)
        if match:
            flush()
            name = match[1]
            directives = defaultdict(list)
            fields = defaultdict(list)
            unknown = []
            occurrences = []
            continue
        if re.match(r"^new\s+entry\b", line, re.I):
            raise ValueError("malformed stats definition boundary")
        if not name:
            continue
        match = _DIRECTIVE.fullmatch(line)
        if match:
            directives[match[1].lower()].append(match[2])
            continue
        match = _DATA.fullmatch(line)
        if match:
            fields[match[1]].append(match[2])
            occurrences.extend(StructuralOccurrence(handle["uid"], match[1], match[1],
                                handle["ver"] or "", index)
                               for handle in HANDLE_PATTERN.finditer(match[2]))
        else:
            # Do not silently ignore future grammar/structural directives.
            unknown.append(line)
    flush()
    return result


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def xml_projection(node: ET.Element) -> dict:
    """Attribute field order is immaterial; ordered structural children stay ordered.

    Namespace URIs, nested nodes, references, handles/versions and opaque values
    all participate. Indentation/comment formatting does not participate.
    """
    attributes: dict[str, list[dict]] = defaultdict(list)
    for child in node:
        if local_name(child.tag) == "attribute":
            attributes[child.get("id", "")].append(xml_projection(child))
    children = [xml_projection(child) for child in node if local_name(child.tag) != "attribute"]
    return {"tag": node.tag, "attributes": dict(node.attrib),
            "text": node.text if node.text and node.text.strip() else "",
            "tail": node.tail if node.tail and node.tail.strip() else "",
            "fields": dict(attributes), "children": children}


_IDENTITY_FIELDS = ("UUID", "Guid", "GUID", "MapKey", "Key", "Name", "entityId", "EntityId", "ID")


def xml_identity(node: ET.Element, ordinal: int, *, quest: bool = False) -> tuple[str, IdentityOrigin]:
    candidates: dict[str, set[str]] = defaultdict(set)
    for key, value in node.attrib.items():
        if local_name(key) in _IDENTITY_FIELDS and value:
            candidates[local_name(key)].add(value)
    for child in node:
        if local_name(child.tag) == "attribute":
            key = child.get("id", "")
            value = child.get("value", "") or child.get("handle", "")
            if key in _IDENTITY_FIELDS and value:
                candidates[key].add(value)
    for key in _IDENTITY_FIELDS:
        values = candidates.get(key, set())
        if len(values) > 1:
            # Malformed competing native identity fields cannot assert an origin.
            return f"{node.get('id', local_name(node.tag))}#{ordinal}", IdentityOrigin.UNKNOWN
        if values:
            origin = (IdentityOrigin.ENTITY_ID if quest else
                      IdentityOrigin.UUID if key in {"UUID", "Guid", "GUID"} else
                      IdentityOrigin.MAP_KEY if key in {"MapKey", "Key"} else
                      IdentityOrigin.NAME if key == "Name" else IdentityOrigin.ENTITY_ID)
            return next(iter(values)), origin
    return f"{node.get('id', local_name(node.tag))}#{ordinal}", IdentityOrigin.FALLBACK_ORDINAL


def parse_structural_xml(text: str, *, resource_path: str = "", package: str = "",
                         kind: str = "item") -> list[StructuralDefinition]:
    resource = source_resource(package, resource_path)
    root = ET.fromstring(text)
    parents = {child: node for node in root.iter() for child in node}
    nodes = [node for node in root.iter() if local_name(node.tag) == "node"]
    if kind == "item":
        boundaries = [node for node in nodes if node.get("id") == "GameObjects"]
    elif kind == "quest":
        boundaries = nodes or [root]
    else:
        boundaries = nodes or list(root.iter())
    boundary_set = set(boundaries)
    result: list[StructuralDefinition] = []
    for ordinal, node in enumerate(boundaries, 1):
        identity, origin = xml_identity(node, ordinal, quest=kind == "quest")
        if kind == "quest" and not nodes:
            origin = IdentityOrigin.FALLBACK_NODE
        definition_type = {"item": "GameObjectTemplate", "quest": "QuestJournalNode"}.get(kind, "UiNode")
        source_kind = {"item": "GameObjectTemplate", "quest": "QuestJournal"}.get(kind, "UiDefinition")
        payload = {"projectionVersion": PROJECTION_VERSION,
                   "definitionType": definition_type, "node": xml_projection(node)}
        occurrences: list[StructuralOccurrence] = []
        for index, elem in enumerate(node.iter(), 1):
            nearest = elem
            while nearest not in boundary_set and nearest in parents:
                nearest = parents[nearest]
            if nearest is not node:
                continue
            field_name = elem.get("id") or elem.get("name") or local_name(elem.tag)
            role = field_name
            if kind == "quest":
                from bg3loc.research.quest import classify_quest_field_role
                role = classify_quest_field_role(field_name, [elem.tag])
            values = [(field_name, elem.get("handle") or elem.get("value") or elem.text or "")]
            if not nodes and kind == "ui":  # XAML keeps the attribute role rather than a node name.
                values = [(local_name(key), value) for key, value in elem.attrib.items()]
                if elem.text:
                    values.append(("#text", elem.text))
            for field_name, value in values:
                for handle in HANDLE_PATTERN.finditer(value):
                    occurrences.append(StructuralOccurrence(handle["uid"], field_name,
                                       role if kind == "quest" else field_name,
                                       elem.get("version") or handle["ver"] or "", index))
        result.append(StructuralDefinition(definition_type, identity, origin,
                                           source_kind, resource, payload, tuple(occurrences)))
    return result


def write_structural_provenance(output_dir: Path, definitions: Iterable[StructuralDefinition]) -> dict:
    """Exact duplicate rows collapse; identities and differing definitions never do."""
    output_dir.mkdir(parents=True, exist_ok=True)
    definitions = list(definitions)
    if any(not item.source_resource for item in definitions):
        raise ValueError("exported structural definitions require source provenance")
    definition_rows = {canonical_json(item.to_dict()) for item in definitions}
    occurrence_rows = {canonical_json(row) for item in definitions for row in item.occurrence_rows()}
    for filename, rows in (("structural-definitions.jsonl", definition_rows),
                           ("structural-occurrences.jsonl", occurrence_rows)):
        (output_dir / filename).write_text("".join(row + "\n" for row in sorted(rows)), encoding="utf-8", newline="\n")
    by_identity: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    origins: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    occurrence_origins: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for serialized in definition_rows:
        row = json.loads(serialized)
        by_identity[(row["definitionType"], row["entityIdentity"])].add(
            (row["sourceResource"], row["definitionFingerprint"]))
        origins[row["definitionType"]][row["identityOrigin"]] += 1
    for serialized in occurrence_rows:
        row = json.loads(serialized)
        occurrence_origins[row["definitionType"]][row["identityOrigin"]] += 1
    multiple: dict[str, int] = defaultdict(int)
    differing: dict[str, int] = defaultdict(int)
    for (definition_type, _), records in by_identity.items():
        multiple[definition_type] += len(records) > 1
        differing[definition_type] += len({digest for _, digest in records}) > 1
    summary = {"schemaVersion": SCHEMA_VERSION, "definitionCount": len(definition_rows),
               "occurrenceCount": len(occurrence_rows), "definitionOrigins": dict(origins),
               "occurrenceOrigins": dict(occurrence_origins),
               "identitiesWithMultipleDefinitions": dict(multiple),
               "identitiesWithDistinctFingerprints": dict(differing),
               "winnerSelectionPerformed": False}
    (output_dir / "structural-provenance-summary.json").write_text(canonical_json(summary) + "\n", encoding="utf-8", newline="\n")
    return summary
