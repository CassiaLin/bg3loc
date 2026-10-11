"""Frozen Stage 0 Dialogue Context contract. Pure DTOs; no execution hooks.

Native evidence authenticity/completeness belongs to the prepare adapter. An
opaque proof digest alone cannot authenticate a game resource at execution.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from hashlib import sha256
import json
import re

SCHEMA_VERSION = "dialogue-context/1"
POLICY_VERSION = "b1-03-policy-a/1"
ORDERING_VERSION = "dialogue-node-uid-order/1"
BUDGET_VERSION = "dialogue-budget/1"
COUNTING_VERSION = "unicode-codepoints/1"
MAX_SOURCE_CODEPOINTS = 2000
_HEX = re.compile(r"[0-9a-f]{64}\Z")


class DialogueContextValidationError(ValueError):
    """Stable public code; never include private source or structural keys."""

    def __init__(self, code: str = "DLG_SHAPE_INVALID") -> None:
        self.code = code
        super().__init__(code)


def fail(code: str = "DLG_SHAPE_INVALID") -> None:
    raise DialogueContextValidationError(code)


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError):
        fail()


def fingerprint(value: object) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def text_hash(value: str) -> str:
    string(value)
    return sha256(value.encode("utf-8")).hexdigest()


def strict_json_loads(value: str | bytes) -> object:
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                fail()
            result[key] = item
        return result
    try:
        if type(value) is bytes:
            value = value.decode("utf-8")
        if type(value) is not str:
            fail()
        result = json.loads(value, object_pairs_hook=pairs,
                            parse_constant=lambda _: fail())
        canonical_bytes(result)  # Reject escaped invalid Unicode too.
        return result
    except (ValueError, TypeError, UnicodeError):
        fail()


def string(value: object) -> None:
    if type(value) is not str or not value:
        fail()
    try:
        value.encode("utf-8")
    except UnicodeError:
        fail()


def digest(value: object) -> None:
    if type(value) is not str or not _HEX.fullmatch(value):
        fail()


def constant(value: object, expected: object, code: str = "DLG_VERSION_UNSUPPORTED") -> None:
    if type(value) is not type(expected) or value != expected:
        fail(code)


def source_complete(value: str) -> bool:
    return bool(value.strip()) and value.strip() != "%%% EMPTY"


def ordered(values: tuple) -> None:
    if values != tuple(sorted(set(values))):
        fail("DLG_ORDER_INVALID")


def collection(value: object, item_type: type, *, nonempty: bool = False) -> None:
    if type(value) is not tuple or (nonempty and not value):
        fail()
    if any(type(item) is not item_type for item in value):
        fail()


def _camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part.title() for part in tail)


class _Wire:
    __slots__ = ()

    def to_dict(self) -> dict:
        def wire(value):
            if isinstance(value, _Wire):
                return value.to_dict()
            if type(value) is tuple:
                return [wire(item) for item in value]
            return value
        return {_camel(field.name): wire(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True, slots=True)
class DialogueBudgetContract(_Wire):
    version: str = BUDGET_VERSION
    counting_version: str = COUNTING_VERSION
    max_source_codepoints: int = MAX_SOURCE_CODEPOINTS

    def __post_init__(self):
        constant(self.version, BUDGET_VERSION)
        constant(self.counting_version, COUNTING_VERSION)
        constant(self.max_source_codepoints, MAX_SOURCE_CODEPOINTS)


@dataclass(frozen=True, slots=True)
class DialogueTargetBinding(_Wire):
    content_uid: str
    category: str
    source_text_sha256: str

    def __post_init__(self):
        string(self.content_uid)
        constant(self.category, "dialogue_general", "DLG_BINDING_MISMATCH")
        digest(self.source_text_sha256)


@dataclass(frozen=True, slots=True)
class DialogueTargetProof(_Wire):
    dialogue_id: str
    dialogue_identity_origin: str
    node_id: str
    node_identity_origin: str
    dialogue_definition_fingerprint: str
    node_definition_fingerprint: str
    source_occurrence_fingerprint: str

    def __post_init__(self):
        string(self.dialogue_id)
        string(self.node_id)
        constant(self.dialogue_identity_origin, "native_UUID", "DLG_BINDING_MISMATCH")
        constant(self.node_identity_origin, "native_UUID", "DLG_BINDING_MISMATCH")
        for value in (self.dialogue_definition_fingerprint, self.node_definition_fingerprint,
                      self.source_occurrence_fingerprint):
            digest(value)


@dataclass(frozen=True, slots=True)
class NativeChildProof(_Wire):
    edge_type: str
    from_node_id: str
    to_node_id: str
    edge_definition_fingerprint: str

    def __post_init__(self):
        constant(self.edge_type, "child", "DLG_BINDING_MISMATCH")
        string(self.from_node_id)
        string(self.to_node_id)
        digest(self.edge_definition_fingerprint)


@dataclass(frozen=True, slots=True)
class DialogueSourceVariant(_Wire):
    content_uid: str
    source_text: str
    occurrence_fingerprints: tuple[str, ...]

    def __post_init__(self):
        string(self.content_uid)
        string(self.source_text)
        if not source_complete(self.source_text):
            fail()
        collection(self.occurrence_fingerprints, str, nonempty=True)
        for value in self.occurrence_fingerprints:
            digest(value)
        ordered(self.occurrence_fingerprints)


@dataclass(frozen=True, slots=True)
class DialogueAlternative(_Wire):
    node_id: str
    node_identity_origin: str
    node_definition_fingerprint: str
    native_child_proof: NativeChildProof
    source_variants: tuple[DialogueSourceVariant, ...]

    def __post_init__(self):
        string(self.node_id)
        constant(self.node_identity_origin, "native_UUID", "DLG_BINDING_MISMATCH")
        digest(self.node_definition_fingerprint)
        if type(self.native_child_proof) is not NativeChildProof:
            fail()
        collection(self.source_variants, DialogueSourceVariant, nonempty=True)
        ordered(tuple(v.content_uid for v in self.source_variants))


def evidence_projection(data: dict) -> dict:
    result = {key: data[key] for key in ("targetBinding", "targetProof")}
    for direction in ("possiblePredecessors", "possibleSuccessors"):
        result[direction] = [{**{key: group[key] for key in (
            "nodeId", "nodeIdentityOrigin", "nodeDefinitionFingerprint", "nativeChildProof")},
            "sourceVariants": [{"contentUid": variant["contentUid"],
                                "sourceTextSha256": text_hash(variant["sourceText"]),
                                "occurrenceFingerprints": variant["occurrenceFingerprints"]}
                               for variant in group["sourceVariants"]]} for group in data[direction]]
    return result


@dataclass(frozen=True, slots=True)
class DialogueContext(_Wire):
    schema_version: str
    policy_version: str
    ordering_version: str
    budget_contract: DialogueBudgetContract
    target_binding: DialogueTargetBinding
    target_proof: DialogueTargetProof
    possible_predecessors: tuple[DialogueAlternative, ...]
    possible_successors: tuple[DialogueAlternative, ...]
    source_codepoints: int
    evidence_fingerprint: str
    context_fingerprint: str

    def __post_init__(self):
        constant(self.schema_version, SCHEMA_VERSION)
        constant(self.policy_version, POLICY_VERSION)
        constant(self.ordering_version, ORDERING_VERSION)
        for value, kind in ((self.budget_contract, DialogueBudgetContract),
                            (self.target_binding, DialogueTargetBinding),
                            (self.target_proof, DialogueTargetProof)):
            if type(value) is not kind:
                fail()
        for groups, predecessor in ((self.possible_predecessors, True),
                                    (self.possible_successors, False)):
            collection(groups, DialogueAlternative)
            ordered(tuple(g.node_id for g in groups))
            for group in groups:
                edge = group.native_child_proof
                expected = (group.node_id, self.target_proof.node_id) if predecessor else (
                    self.target_proof.node_id, group.node_id)
                if (edge.from_node_id, edge.to_node_id) != expected or group.node_id == self.target_proof.node_id:
                    fail("DLG_BINDING_MISMATCH")
                if any(v.content_uid == self.target_binding.content_uid for v in group.source_variants):
                    fail("DLG_BINDING_MISMATCH")
        actual = sum(len(v.source_text) for g in self.possible_predecessors + self.possible_successors
                     for v in g.source_variants)
        if type(self.source_codepoints) is not int or self.source_codepoints != actual or not 1 <= actual <= MAX_SOURCE_CODEPOINTS:
            fail("DLG_BUDGET_MISMATCH")
        digest(self.evidence_fingerprint)
        digest(self.context_fingerprint)
        data = self.to_dict()
        if self.evidence_fingerprint != fingerprint(evidence_projection(data)):
            fail("DLG_FINGERPRINT_MISMATCH")
        del data["contextFingerprint"]
        if self.context_fingerprint != fingerprint(data):
            fail("DLG_FINGERPRINT_MISMATCH")


_CHILDREN = {
    DialogueContext: {"budget_contract": DialogueBudgetContract, "target_binding": DialogueTargetBinding,
                     "target_proof": DialogueTargetProof, "possible_predecessors": DialogueAlternative,
                     "possible_successors": DialogueAlternative},
    DialogueAlternative: {"native_child_proof": NativeChildProof, "source_variants": DialogueSourceVariant},
}
_ARRAYS = {"possible_predecessors", "possible_successors", "source_variants", "occurrence_fingerprints"}


def _arguments(kind: type, value: object) -> dict:
    if type(value) is not dict or set(value) != {_camel(f.name) for f in fields(kind)}:
        fail()
    arguments = {}
    for field in fields(kind):
        item = value[_camel(field.name)]
        child = _CHILDREN.get(kind, {}).get(field.name)
        if field.name in _ARRAYS:
            if type(item) is not list:
                fail()
            item = tuple(_decode(child, v) if child else v for v in item)
        elif child:
            item = _decode(child, item)
        arguments[field.name] = item
    return arguments


def _decode(kind: type, value: object):
    return kind(**_arguments(kind, value))


def decode_dialogue_context(value: object, *, content_uid: str, category: str,
                            source_text: str, source_locale: str = "English") -> DialogueContext:
    """Decode already-parsed JSON, with exact material/source binding."""
    arguments = _arguments(DialogueContext, value)
    constant(arguments["schema_version"], SCHEMA_VERSION)
    constant(arguments["policy_version"], POLICY_VERSION)
    constant(arguments["ordering_version"], ORDERING_VERSION)
    if source_locale != "English" or arguments["target_binding"] != DialogueTargetBinding(
            content_uid, category, text_hash(source_text)):
        fail("DLG_BINDING_MISMATCH")
    return DialogueContext(**arguments)


def dialogue_context_from_material(row: dict, *, source_locale: str = "English") -> DialogueContext | None:
    """Prepare-side validation helper only; deliberately not wired into workers."""
    if type(row) is not dict:
        fail()
    if "dialogueContext" in row and "sameEntityContext" in row:
        fail("BOTH_CONTEXT_FAMILIES")
    if "dialogueContext" not in row:
        return None
    try:
        return decode_dialogue_context(row["dialogueContext"], content_uid=row["contentUid"],
            category=row["primaryCategory"], source_text=row["sourceText"], source_locale=source_locale)
    except KeyError:
        fail()
