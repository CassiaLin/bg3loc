"""Production-owned, source-only B1-02 contracts and pure context builder.

No I/O or execution hooks. Callers supply the complete structural occurrence
universe, including ineligible/conflicting evidence, from one source snapshot.
Definition fingerprints must describe the *whole entity definition*, not the
resource file or one field. No override precedence is inferred here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from hashlib import sha256
import json
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import Iterable
from uuid import UUID

from bg3loc.protected_syntax import extract_protected_tokens


SCHEMA_VERSION = "same-entity-context/1"
POLICY_VERSION = "b1-02-structural/2"
MAX_RELATED_FIELDS = 4
MAX_CONTEXT_CHARS = 4000
CATEGORIES = frozenset({"skill_spell", "item", "quest"})
FIELD_PRIORITY = MappingProxyType({
    "skill_spell": ("DisplayName", "Description", "ExtraDescription", "ShortDescription", "Tooltip"),
    "item": ("DisplayName", "Description", "Tooltip"),
    "quest": ("QuestTitle", "QuestDescription", "QuestField"),
})
ENTITY_TYPES = MappingProxyType({
    "skill_spell": "StatsEntry", "item": "GameObjectTemplate", "quest": "Quest",
})


class StructuralIdentityKind(str, Enum):
    STATS_ENTRY_NAME = "stats-entry-name"
    TEMPLATE_UUID = "template-uuid"
    TEMPLATE_MAP_KEY = "template-map-key"
    JOURNAL_ENTITY_ID = "journal-entity-id"
    # Explicit negative kinds make adapter fallbacks auditable.
    STATS_USING_PARENT = "stats-using-parent"
    GENERIC_NODE = "generic-node"
    ORDINAL_FALLBACK = "ordinal-fallback"
    FILE_GROUP = "file-group"


# Default/legacy kinds; item also accepts the conditional TEMPLATE_MAP_KEY gate.
IDENTITY_KINDS = MappingProxyType({
    "skill_spell": StructuralIdentityKind.STATS_ENTRY_NAME,
    "item": StructuralIdentityKind.TEMPLATE_UUID,
    "quest": StructuralIdentityKind.JOURNAL_ENTITY_ID,
})

# MapKey eligibility is additional structural proof, not a selection priority.
_MAP_KEY_ITEM_ROLES = frozenset({
    "displayname", "description", "displaynamealchemy", "onusedescription",
    "technicaldescription", "shortdescription", "unknowndescription", "unknowndisplayname",
})


class ContextAbsenceReason(str, Enum):
    UNSUPPORTED_CATEGORY = "UNSUPPORTED_CATEGORY"
    NO_RELIABLE_IDENTITY = "NO_RELIABLE_IDENTITY"
    STRUCTURAL_CONFLICT = "STRUCTURAL_CONFLICT"
    AMBIGUOUS_FIELD_ROLE = "AMBIGUOUS_FIELD_ROLE"
    MISSING_SOURCE = "MISSING_SOURCE"
    NO_RELATED_FIELDS = "NO_RELATED_FIELDS"
    CATEGORY_MISMATCH = "CATEGORY_MISMATCH"
    HOLD_OR_INELIGIBLE = "HOLD_OR_INELIGIBLE"


class SameEntityContextValidationError(ValueError):
    """A declared-present context is invalid; never silently downgrade it."""


def canonical_json(value: object) -> str:
    """The single JSON byte contract for structural/context fingerprints."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def fingerprint(value: object) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def source_text_sha256(source_text: str) -> str:
    """Bind exact source bytes, including whitespace and Unicode spelling."""
    return sha256(source_text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SameEntitySourceRecord:
    """One normalized structural occurrence, not a localization translation.

    evidence_source is a relative resource identity (or a digest identifier).
    evidence_fingerprint identifies the complete structural occurrence evidence.
    definition_fingerprint identifies the complete entity definition, consistently
    across all of its fields. entity_scope disambiguates namespaces, never paths.
    identity_kind declares the extractor's actual identity origin. A generic node
    with a UUID-looking name must still declare GENERIC_NODE and is rejected.
    The adapter must retain all definitions; this builder cannot detect omitted
    evidence or independently authenticate an upstream structural assertion.
    For TEMPLATE_MAP_KEY, identity_origin must be MAP_KEY, identity_is_native
    must attest a direct identity on the GameObjectTemplate boundary, and
    template_type must come from that boundary's native Type field. entity_type
    declares the definition type. field_is_direct attests occurrence ownership.
    Retain definitions without usable localization as records with empty UID,
    role and text and eligible=False; their provenance still participates.
    """
    content_uid: str
    category: str
    entity_type: str
    entity_identity: str
    field_role: str
    source_text: str
    identity_kind: StructuralIdentityKind
    evidence_source: str
    evidence_fingerprint: str
    definition_fingerprint: str
    entity_scope: str = "default"
    source_locale: str = "English"
    eligible: bool = True
    identity_origin: str = ""
    template_type: str = ""
    identity_is_native: bool = False
    field_is_direct: bool = False

    def __post_init__(self) -> None:
        for name in ("content_uid", "category", "entity_type", "entity_identity", "field_role",
                     "source_text", "evidence_source", "evidence_fingerprint", "definition_fingerprint",
                     "entity_scope", "source_locale", "identity_origin", "template_type"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} must be a string")
        if (not isinstance(self.identity_kind, StructuralIdentityKind)
                or any(type(getattr(self, name)) is not bool
                       for name in ("eligible", "identity_is_native", "field_is_direct"))):
            raise ValueError("identity_kind must be StructuralIdentityKind; evidence flags must be boolean")


@dataclass(frozen=True, slots=True)
class SameEntityRelatedField:
    content_uid: str
    field_role: str
    source_text: str
    truncated: bool

    def __post_init__(self) -> None:
        if (not all(isinstance(value, str) for value in (self.content_uid, self.field_role, self.source_text))
                or type(self.truncated) is not bool):
            raise SameEntityContextValidationError("related field strings and boolean truncated required")

    def to_dict(self) -> dict[str, object]:
        return {"contentUid": self.content_uid, "fieldRole": self.field_role,
                "sourceText": self.source_text, "truncated": self.truncated}


@dataclass(frozen=True, slots=True)
class SameEntityTargetBinding:
    content_uid: str
    category: str
    source_text_sha256: str

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) for value in (self.content_uid, self.category, self.source_text_sha256)):
            raise SameEntityContextValidationError("target binding strings required")

    def to_dict(self) -> dict[str, str]:
        return {"contentUid": self.content_uid, "category": self.category,
                "sourceTextSha256": self.source_text_sha256}


@dataclass(frozen=True, slots=True)
class SameEntityContext:
    schema_version: str
    policy_version: str
    target_binding: SameEntityTargetBinding
    target_field_role: str
    entity_type: str
    entity_identity: str
    evidence_fingerprint: str
    related_fields: tuple[SameEntityRelatedField, ...]
    context_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.related_fields, tuple):
            raise SameEntityContextValidationError("related_fields must be an immutable tuple")
        if (not isinstance(self.target_binding, SameEntityTargetBinding)
                or not all(isinstance(field, SameEntityRelatedField) for field in self.related_fields)
                or not all(isinstance(value, str) for value in (
                    self.schema_version, self.policy_version, self.target_field_role,
                    self.entity_type, self.entity_identity, self.evidence_fingerprint, self.context_fingerprint))):
            raise SameEntityContextValidationError("immutable typed context fields required")

    def fingerprint_payload(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version, "policyVersion": self.policy_version,
            "targetBinding": self.target_binding.to_dict(),
            "targetFieldRole": self.target_field_role, "entityType": self.entity_type,
            "entityIdentity": self.entity_identity, "evidenceFingerprint": self.evidence_fingerprint,
            "relatedFields": [field.to_dict() for field in self.related_fields],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.fingerprint_payload(), "contextFingerprint": self.context_fingerprint}


@dataclass(frozen=True, slots=True)
class ContextBuildResult:
    context: SameEntityContext | None
    absence_reason: ContextAbsenceReason | None

    def __post_init__(self) -> None:
        if (self.context is None) == (self.absence_reason is None):
            raise ValueError("exactly one of context and absence_reason is required")


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MARKUP = re.compile(r"<[^>]*>")


def _is_hash(value: object) -> bool:
    return isinstance(value, str) and bool(_HASH.fullmatch(value))


def _relative_identity(value: str) -> str | None:
    normalized = value.replace("\\", "/").strip()
    if (not normalized or normalized.startswith("/") or ":" in normalized
            or ".." in normalized.split("/") or "\x00" in normalized):
        return None
    return str(PurePosixPath(normalized))


def _identity_text(value: str) -> bool:
    return bool(value and value == value.strip()
                and not any(char in value for char in "#:/\\"))


def _identity(record: SameEntitySourceRecord) -> str | None:
    value = record.entity_identity
    map_key = record.category == "item" and record.identity_kind == StructuralIdentityKind.TEMPLATE_MAP_KEY
    if (record.entity_type != ENTITY_TYPES.get(record.category)
            or (not map_key and record.identity_kind != IDENTITY_KINDS.get(record.category))
            or not _identity_text(value)
            or not _relative_identity(record.entity_scope)):
        return None
    if record.category == "item":
        if map_key:
            if (record.identity_origin != "MAP_KEY" or not record.identity_is_native
                    or record.template_type != "item"):
                return None
            # Native FixedString identity: no UUID inference or case folding.
            return value
        if record.identity_origin not in {"", "UUID"}:
            return None
        try:
            parsed = UUID(value)
        except ValueError:
            return None
        if parsed.int == 0:
            return None
        return str(parsed)
    return value


def _reliable(record: SameEntitySourceRecord) -> bool:
    return bool(_identity(record) and _relative_identity(record.evidence_source)
                and _is_hash(record.evidence_fingerprint)
                and _is_hash(record.definition_fingerprint) and record.source_locale.strip())


def _entity_key(record: SameEntitySourceRecord) -> tuple[str, str, str | None]:
    return record.category, _relative_identity(record.entity_scope) or "", _identity(record)


def _map_key_group_member(record: SameEntitySourceRecord, target: SameEntitySourceRecord) -> bool:
    # Deliberately do not filter by type, origin, eligibility or usable fields.
    # Competing retained definitions must not disappear through reliability gates.
    return (record.category == target.category and record.entity_identity == target.entity_identity
            and _relative_identity(record.entity_scope) == _relative_identity(target.entity_scope))


def _field_verified(record: SameEntitySourceRecord) -> bool:
    return (record.identity_kind != StructuralIdentityKind.TEMPLATE_MAP_KEY
            or (record.field_is_direct and record.field_role.strip().casefold() in _MAP_KEY_ITEM_ROLES))


def _usable(text: str) -> bool:
    # Remove presentation attributes before looking for natural-language letters;
    # a token-only LSTag envelope must not become prose because its attributes do.
    visible = _MARKUP.sub("", text)
    for token in extract_protected_tokens(visible):
        visible = visible.replace(token, "")
    return any(char.isalpha() for char in visible)


def _rank(record: SameEntitySourceRecord) -> tuple[int, str, str, str]:
    role = record.field_role.strip().casefold()
    priority = tuple(value.casefold() for value in FIELD_PRIORITY[record.category])
    return (priority.index(role) if role in priority else len(priority),
            role, record.content_uid.casefold(), record.source_text)


def _evidence_payload(record: SameEntitySourceRecord) -> dict[str, object]:
    return {
        "contentUid": record.content_uid, "category": record.category,
        "entityType": record.entity_type, "entityIdentity": _identity(record),
        "entityScope": _relative_identity(record.entity_scope), "identityKind": record.identity_kind.value,
        "fieldRole": record.field_role, "sourceTextSha256": source_text_sha256(record.source_text),
        "sourceLocale": record.source_locale, "eligible": record.eligible,
        "evidenceSource": _relative_identity(record.evidence_source),
        "evidenceFingerprint": record.evidence_fingerprint,
        "definitionFingerprint": record.definition_fingerprint,
        "identityOrigin": record.identity_origin, "templateType": record.template_type,
        "identityIsNative": record.identity_is_native, "fieldIsDirect": record.field_is_direct,
    }


def build_same_entity_context(
    target: SameEntitySourceRecord,
    records: Iterable[SameEntitySourceRecord],
) -> ContextBuildResult:
    """Build one target's optional context from the complete occurrence universe.

    No sampling, inference, source reads, precedence, or runtime token contract.
    The target can be supplied separately; equivalent repeated evidence is a set.
    """
    def absent(reason: ContextAbsenceReason) -> ContextBuildResult:
        return ContextBuildResult(None, reason)

    if target.category not in CATEGORIES:
        return absent(ContextAbsenceReason.UNSUPPORTED_CATEGORY)
    if not _reliable(target) or not target.content_uid or not _field_verified(target):
        return absent(ContextAbsenceReason.NO_RELIABLE_IDENTITY)
    universe = tuple(records) + (target,)
    map_key = target.identity_kind == StructuralIdentityKind.TEMPLATE_MAP_KEY
    group = tuple(row for row in universe if
                  (_map_key_group_member(row, target) if map_key else _entity_key(row) == _entity_key(target)))
    if map_key:
        if len({row.definition_fingerprint for row in group}) != 1:
            return absent(ContextAbsenceReason.STRUCTURAL_CONFLICT)
        if any(not _reliable(row) or row.identity_kind != StructuralIdentityKind.TEMPLATE_MAP_KEY for row in group):
            return absent(ContextAbsenceReason.NO_RELIABLE_IDENTITY)
    occurrences = tuple(row for row in universe if row.content_uid == target.content_uid)
    if any(row.category != target.category for row in occurrences):
        return absent(ContextAbsenceReason.CATEGORY_MISMATCH)
    if any(not row.eligible for row in occurrences):
        return absent(ContextAbsenceReason.HOLD_OR_INELIGIBLE)
    if any(not _reliable(row) or not _field_verified(row)
           or _entity_key(row) != _entity_key(target) for row in occurrences):
        return absent(ContextAbsenceReason.NO_RELIABLE_IDENTITY)
    if not target.field_role.strip() or len({row.field_role.strip().casefold() for row in occurrences}) != 1:
        return absent(ContextAbsenceReason.AMBIGUOUS_FIELD_ROLE)
    if not _usable(target.source_text):
        return absent(ContextAbsenceReason.MISSING_SOURCE)
    if any(row.source_text != target.source_text or row.source_locale != target.source_locale for row in occurrences):
        return absent(ContextAbsenceReason.STRUCTURAL_CONFLICT)

    # Check all definitions, including evidence later excluded from selection.
    if len({row.definition_fingerprint for row in group}) != 1:
        return absent(ContextAbsenceReason.STRUCTURAL_CONFLICT)
    uid_sources: dict[str, set[str]] = {}
    for row in group:
        uid_sources.setdefault(row.content_uid, set()).add(row.source_text)
    if any(len(texts) > 1 for texts in uid_sources.values()):
        return absent(ContextAbsenceReason.STRUCTURAL_CONFLICT)
    candidates = []
    for row in group:
        if not (_reliable(row) and _field_verified(row) and row.eligible and row.field_role.strip()
                and row.source_locale == target.source_locale):
            continue
        uid_occurrences = tuple(other for other in universe if other.content_uid == row.content_uid)
        if any(not other.eligible or not _reliable(other) or not _field_verified(other)
               or _entity_key(other) != _entity_key(target)
               or other.source_locale != target.source_locale or other.source_text != row.source_text
               or other.field_role.strip().casefold() != row.field_role.strip().casefold()
               for other in uid_occurrences):
            continue
        candidates.append(row)

    selected: list[SameEntityRelatedField] = []
    seen_uids = {target.content_uid}
    seen_texts = {target.source_text.strip().casefold()}
    used = 0
    # Evidence is deduplicated separately below; ties include spelling to avoid
    # stable-sort dependence when inputs differ only in UID/role case.
    for row in sorted(candidates, key=lambda row: (_rank(row), row.content_uid, row.field_role)):
        normalized = row.source_text.strip().casefold()
        if (row.content_uid in seen_uids or normalized in seen_texts
                or row.field_role.strip().casefold() == target.field_role.strip().casefold()
                or not _usable(row.source_text)):
            continue
        seen_uids.add(row.content_uid)
        seen_texts.add(normalized)
        if len(selected) == MAX_RELATED_FIELDS or used == MAX_CONTEXT_CHARS:
            break
        remaining = MAX_CONTEXT_CHARS - used
        if len(row.source_text) > remaining and (selected or len(row.source_text) <= MAX_CONTEXT_CHARS):
            continue
        text = row.source_text[:remaining]
        selected.append(SameEntityRelatedField(row.content_uid, row.field_role, text,
                                              len(text) < len(row.source_text)))
        used += len(text)
    if not selected:
        return absent(ContextAbsenceReason.NO_RELATED_FIELDS)

    # Include the entire reliable entity evidence, not only selected fields.
    evidence = sorted({canonical_json(_evidence_payload(row)) for row in group if _reliable(row)})
    context = SameEntityContext(
        SCHEMA_VERSION, POLICY_VERSION,
        SameEntityTargetBinding(target.content_uid, target.category, source_text_sha256(target.source_text)),
        target.field_role, target.entity_type,
        canonical_json({"scope": _relative_identity(target.entity_scope), "identity": _identity(target)}),
        fingerprint([json.loads(value) for value in evidence]), tuple(selected), "",
    )
    context = replace(context, context_fingerprint=fingerprint(context.fingerprint_payload()))
    validate_same_entity_context(context, content_uid=target.content_uid,
                                 category=target.category, source_text=target.source_text)
    return ContextBuildResult(context, None)


def validate_same_entity_context(
    context: SameEntityContext | None, *, content_uid: str, category: str, source_text: str,
) -> None:
    """Validate present context against the caller's exact target; None is normal.

    Fingerprints bind declared provenance, not external evidence authenticity.
    Evidence reliability itself is established by the source adapter/builder,
    including native MapKey/Type/direct-field proof bound in evidenceFingerprint.
    The serialized context intentionally contains no origin/type proof; this
    validator cannot authenticate an arbitrary digest against omitted evidence.
    """
    if context is None:
        return

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise SameEntityContextValidationError(message)

    require(isinstance(context, SameEntityContext), "expected SameEntityContext")
    require(context.schema_version == SCHEMA_VERSION, "unsupported schema version")
    require(context.policy_version == POLICY_VERSION, "unsupported policy version")
    require(category in CATEGORIES, "unsupported target category")
    binding = context.target_binding
    require(isinstance(binding, SameEntityTargetBinding), "invalid target binding")
    require(bool(content_uid) and binding.content_uid == content_uid, "target UID mismatch")
    require(binding.category == category, "target category mismatch")
    require(binding.source_text_sha256 == source_text_sha256(source_text), "target source hash mismatch")
    require(isinstance(context.target_field_role, str) and bool(context.target_field_role.strip()), "missing target field role")
    require(context.entity_type == ENTITY_TYPES[category], "entity type mismatch")
    require(isinstance(context.entity_identity, str), "invalid entity identity")
    try:
        identity = json.loads(context.entity_identity)
    except (ValueError, TypeError) as exc:
        raise SameEntityContextValidationError("invalid scoped entity identity") from exc
    require(isinstance(identity, dict) and set(identity) == {"scope", "identity"}
            and all(isinstance(value, str) for value in identity.values()), "invalid scoped entity identity")
    probe = SameEntitySourceRecord(content_uid, category, context.entity_type, identity["identity"],
                                   context.target_field_role, source_text, IDENTITY_KINDS[category],
                                   "probe", "", "", entity_scope=identity["scope"])
    if category == "item":
        # Policy v2 also accepts verified native FixedStrings. Their proof is
        # checked before construction and bound in the complete evidence digest.
        require(_identity_text(identity["identity"]) and bool(_relative_identity(identity["scope"])),
                "invalid item entity identity")
    else:
        require(_identity(probe) is not None, "unreliable entity identity")
    require(_is_hash(context.evidence_fingerprint), "invalid evidence fingerprint")
    require(isinstance(context.related_fields, tuple) and 1 <= len(context.related_fields) <= MAX_RELATED_FIELDS,
            "related fields must contain 1..4 immutable entries")
    uids = {content_uid}
    texts = {source_text.strip().casefold()}
    total = 0
    for index, field in enumerate(context.related_fields):
        require(isinstance(field, SameEntityRelatedField), "invalid related field")
        require(isinstance(field.content_uid, str) and bool(field.content_uid) and field.content_uid not in uids,
                "target or duplicate related UID")
        require(isinstance(field.field_role, str) and bool(field.field_role.strip())
                and field.field_role.strip().casefold() != context.target_field_role.strip().casefold(),
                "invalid or target related field role")
        require(isinstance(field.source_text, str) and _usable(field.source_text), "unusable related source")
        require(field.source_text.strip().casefold() not in texts, "duplicate related source")
        require(type(field.truncated) is bool, "truncated must be boolean")
        require(not field.truncated or (index == 0 and len(context.related_fields) == 1
                                       and len(field.source_text) == MAX_CONTEXT_CHARS),
                "invalid truncation boundary")
        total += len(field.source_text)
        uids.add(field.content_uid)
        texts.add(field.source_text.strip().casefold())
    require(total <= MAX_CONTEXT_CHARS, "context character budget exceeded")
    require(_is_hash(context.context_fingerprint)
            and context.context_fingerprint == fingerprint(context.fingerprint_payload()), "context fingerprint mismatch")
