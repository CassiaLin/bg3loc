"""Prepare-owned public provenance adapter and inline material integrity.

No research CLI, game lookup, provider, request or execution-state dependency.
Only prepare reads source/provenance. Preflight reads sealed inline contexts
and aggregate metadata, never joins their original inputs.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import fmean
from uuid import UUID

from jsonschema import Draft202012Validator

from bg3loc.schema import SchemaStore
from bg3loc.same_entity_context import (
    CATEGORIES, MAX_CONTEXT_CHARS, MAX_RELATED_FIELDS, POLICY_VERSION, SCHEMA_VERSION,
    ContextAbsenceReason as Reason, ContextBuildResult, SameEntityContext,
    SameEntityRelatedField, SameEntitySourceRecord, SameEntityTargetBinding,
    StructuralIdentityKind as Kind, build_same_entity_context, canonical_json,
    fingerprint, validate_same_entity_context,
)

ADAPTER_VERSION = "public-provenance-adapter/1"
BUILDER_VERSION = "same-entity-context-builder/2"
SUMMARY_VERSION = "context-materialization-summary/1"
_SKILL_TYPES = frozenset({"SpellData", "PassiveData", "StatusData", "InterruptData"})
_BINDING = ("definitionType", "entityIdentity", "identityOrigin", "sourceKind",
            "sourceResource", "definitionFingerprint", "definitionProjectionVersion")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path) -> list[dict]:
    result = []
    with path.open(encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise RuntimeError("context input must contain JSON objects")
                result.append(row)
    return result


def _row_digest(rows: list[dict]) -> str:
    return fingerprint(sorted({canonical_json(row) for row in rows}))


def _binding(row: dict) -> tuple:
    return tuple(row[name] for name in _BINDING)


def context_from_material(row: dict) -> SameEntityContext | None:
    """Strict P1 decoding for integrity only; never attached to a request."""
    if "sameEntityContext" not in row:
        return None
    value = row["sameEntityContext"]
    expected = {"schemaVersion", "policyVersion", "targetBinding", "targetFieldRole",
                "entityType", "entityIdentity", "evidenceFingerprint", "relatedFields", "contextFingerprint"}
    if not isinstance(value, dict) or set(value) != expected:
        raise RuntimeError("invalid declared-present sameEntityContext shape")
    binding = value["targetBinding"]
    fields = value["relatedFields"]
    if (not isinstance(binding, dict) or set(binding) != {"contentUid", "category", "sourceTextSha256"}
            or not isinstance(fields, list) or any(not isinstance(field, dict)
            or set(field) != {"contentUid", "fieldRole", "sourceText", "truncated"} for field in fields)):
        raise RuntimeError("invalid sameEntityContext binding/fields")
    context = SameEntityContext(
        value["schemaVersion"], value["policyVersion"],
        SameEntityTargetBinding(binding["contentUid"], binding["category"], binding["sourceTextSha256"]),
        value["targetFieldRole"], value["entityType"], value["entityIdentity"], value["evidenceFingerprint"],
        tuple(SameEntityRelatedField(field["contentUid"], field["fieldRole"], field["sourceText"], field["truncated"])
              for field in fields), value["contextFingerprint"],
    )
    validate_same_entity_context(context, content_uid=row.get("contentUid", row.get("ContentUid", "")),
                                 category=row.get("primaryCategory", ""),
                                 source_text=row.get("sourceText", row.get("SourceText", "")))
    return context


def _materials(batch_plan: Path):
    plan = json.loads(batch_plan.read_text(encoding="utf-8-sig"))
    for batch in plan["batches"]:
        batch_id = batch["batchId"]
        if not isinstance(batch_id, str) or not batch_id or any(c in batch_id for c in "/\\:") or batch_id in {".", ".."}:
            raise RuntimeError("invalid batch ID for context materialization")
        path = batch_plan.parent / "materials" / (batch_id + ".jsonl")
        yield path


def material_context_fingerprint(batch_plan: Path, *, enabled: bool) -> tuple[str, int]:
    states = {}
    present = 0
    for path in _materials(batch_plan):
        for row in _rows(path):
            uid = row.get("contentUid", row.get("ContentUid", ""))
            if not isinstance(uid, str) or not uid or uid in states:
                raise RuntimeError("invalid/duplicate target in context materials")
            if not enabled and "sameEntityContext" in row:
                raise RuntimeError("legacy workspace cannot declare sameEntityContext")
            context = context_from_material(row)
            states[uid] = context.context_fingerprint if context else "absent"
            present += context is not None
    return fingerprint(states), present


def contract_metadata() -> dict:
    return {"schemaVersion": SCHEMA_VERSION, "policyVersion": POLICY_VERSION,
            "adapterVersion": ADAPTER_VERSION, "builderVersion": BUILDER_VERSION,
            "maxRelatedFields": MAX_RELATED_FIELDS, "maxContextChars": MAX_CONTEXT_CHARS,
            "allowedCategories": sorted(CATEGORIES), "promptConsumption": False}


def _hold_uids(ui_skill_universe: Path | None) -> set[str]:
    if ui_skill_universe is None:
        return set()
    with ui_skill_universe.open(encoding="utf-8-sig", newline="") as stream:
        return {row["ContentUid"] for row in csv.DictReader(stream)
                if row.get("ContentUid") and row.get("Status") == "Hold"}


def materialize_contexts(*, batch_plan: Path, classification: Path, source: Path,
                         provenance_dir: Path, summary_path: Path,
                         ui_skill_universe: Path | None = None) -> dict:
    definition_path = provenance_dir / "structural-definitions.jsonl"
    occurrence_path = provenance_dir / "structural-occurrences.jsonl"
    definitions, occurrences = _rows(definition_path), _rows(occurrence_path)
    schemas = SchemaStore()
    for stem, rows in (("definition", definitions), ("occurrence", occurrences)):
        validator = Draft202012Validator(schemas.load(f"research/public-structural-{stem}-v1.schema.json"))
        if any(not validator.is_valid(row) for row in rows):
            # Never include real row contents in schema exception diagnostics.
            raise RuntimeError("invalid public structural " + stem + " provenance")
    definitions = [json.loads(value) for value in sorted({canonical_json(row) for row in definitions})]
    occurrences = [json.loads(value) for value in sorted({canonical_json(row) for row in occurrences})]
    by_definition = {_binding(row): row for row in definitions}
    if len(by_definition) != len(definitions):
        raise RuntimeError("contradictory public definition metadata")
    for row in occurrences:
        definition = by_definition.get(_binding(row))
        if definition is None or any(row.get(name) != definition.get(name)
                                     for name in ("templateType", "identityIsNative", "entryName", "entryType", "using")):
            raise RuntimeError("occurrence does not bind a retained public definition")
    source_rows = _rows(source)
    sources = {}
    for row in source_rows:
        uid, text = row.get("contentUid"), row.get("text", row.get("sourceText"))
        if (not isinstance(uid, str) or not uid or uid in sources or not isinstance(text, str)
                or row.get("localeId", "").casefold() != "english"):
            raise RuntimeError("context source must be unique normalized English records")
        sources[uid] = text
    class_rows = _rows(classification)
    classes = {row["contentUid"]: row for row in class_rows}
    if len(classes) != len(class_rows):
        raise RuntimeError("duplicate context classification UID")
    holds = _hold_uids(ui_skill_universe)
    by_uid = defaultdict(list)
    raw_groups = defaultdict(list)
    uuid_groups = defaultdict(list)

    def retain(record):
        raw_groups[(record.category, record.entity_identity)].append(record)
        if record.category == "item":
            try:
                uuid_groups[str(UUID(record.entity_identity))].append(record)
            except ValueError:
                pass
        if record.content_uid:
            by_uid[record.content_uid].append(record)

    def adapt(row, definition, *, definition_only=False):
        kind_name = definition["definitionType"]
        if kind_name == "StatsEntry":
            category, entity_type = "skill_spell", "StatsEntry"
            kind = Kind.STATS_ENTRY_NAME if definition["identityOrigin"] == "ENTRY_NAME" and definition["entryName"] == definition["entityIdentity"] else Kind.GENERIC_NODE
            supported = definition.get("entryType") in _SKILL_TYPES
            if not definition_only and not supported:
                category = "other"
        elif kind_name == "GameObjectTemplate":
            category, entity_type = "item", "GameObjectTemplate"
            kind = {"UUID": Kind.TEMPLATE_UUID, "MAP_KEY": Kind.TEMPLATE_MAP_KEY}.get(definition["identityOrigin"], Kind.GENERIC_NODE)
            supported = True
            # Retain every competing definition in the item group, but preserve
            # non-item occurrence aliases so shared UIDs fail category checks.
            if not definition_only and definition.get("templateType", "") not in {"", "item"}:
                category = "other"
        elif kind_name == "QuestJournalNode":
            category, entity_type = "quest", "Quest"
            kind = Kind.JOURNAL_ENTITY_ID if definition["identityOrigin"] == "ENTITY_ID" else Kind.ORDINAL_FALLBACK
            supported = True
        else:
            category, entity_type, kind, supported = "other", "UiNode", Kind.GENERIC_NODE, False
        uid = "" if definition_only else row["contentUid"]
        production = classes.get(uid, {})
        eligible = (not definition_only and supported and uid in sources and uid not in holds
                    and production.get("classificationStatus") == "classified"
                    and production.get("primaryCategory") == category)
        return SameEntitySourceRecord(
            uid, category, entity_type, definition["entityIdentity"], "" if definition_only else row["fieldRole"],
            sources.get(uid, ""), kind, definition["sourceResource"], fingerprint(row), definition["definitionFingerprint"],
            entity_scope="source-snapshot", eligible=eligible, identity_origin=definition["identityOrigin"],
            template_type=definition.get("templateType", ""), identity_is_native=definition.get("identityIsNative", False),
            field_is_direct=row.get("fieldIsDirect", False) if not definition_only else False,
        )

    for definition in definitions:
        retain(adapt(definition, definition, definition_only=True))
    for row in occurrences:
        retain(adapt(row, by_definition[_binding(row)]))
    # Index the complete universe. Closure includes every retained same-entity
    # definition and every UID alias needed by the authoritative pure builder.
    closures = {}

    def universe_for(target):
        key = (target.category, target.identity_kind, target.entity_identity)
        if key not in closures:
            group = list(raw_groups[(target.category, target.entity_identity)])
            if target.identity_kind == Kind.TEMPLATE_UUID:
                try:
                    group += uuid_groups[str(UUID(target.entity_identity))]
                except ValueError:
                    pass
            selected = {id(row): row for row in group}
            for uid in {row.content_uid for row in group if row.content_uid}:
                selected.update({id(row): row for row in by_uid[uid]})
            closures[key] = tuple(selected.values())
        return closures[key]

    # Build the complete target result map before walking batch materials.
    # A batch only receives its already-built result; partitioning cannot
    # change the evidence universe or the builder's related-field selection.
    build_results = {}
    for uid in sorted(classes):
        cls = classes[uid]
        category = cls.get("primaryCategory")
        if cls.get("classificationStatus") != "classified" or category == "other":
            continue
        if category not in CATEGORIES:
            result = ContextBuildResult(None, Reason.UNSUPPORTED_CATEGORY)
        elif uid in holds:
            result = ContextBuildResult(None, Reason.HOLD_OR_INELIGIBLE)
        elif not sources.get(uid, "").strip():
            result = ContextBuildResult(None, Reason.MISSING_SOURCE)
        else:
            candidates = sorted((record for record in by_uid.get(uid, ()) if record.category == category),
                                key=lambda record: canonical_json(asdict(record)))
            result = (build_same_entity_context(candidates[0], universe_for(candidates[0]))
                      if candidates else ContextBuildResult(None, Reason.NO_RELIABLE_IDENTITY))
        if result.context is not None:
            validate_same_entity_context(result.context, content_uid=uid, category=category, source_text=sources[uid])
        build_results[uid] = result

    results = {}
    categories = {category: {"preparedTargets": 0, "eligibleTargets": 0, "withContext": 0,
                              "withoutContext": 0, "absenceReasonCounts": {}} for category in sorted(CATEGORIES)}
    reasons = Counter()
    fields, chars, truncated = [], [], 0
    item_sanity = Counter()
    materials = []
    for path in _materials(batch_plan):
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        pending = []
        for line in lines:
            if not line.strip():
                pending.append(line)
                continue
            row = json.loads(line)
            uid, category, text = row["contentUid"], row["primaryCategory"], row["sourceText"]
            if uid in results or "sameEntityContext" in row:
                raise RuntimeError("duplicate/already-materialized context target")
            cls = classes.get(uid, {})
            if sources.get(uid) != text or cls.get("primaryCategory") != category or cls.get("classificationStatus") != "classified":
                raise RuntimeError("material target does not match classified source snapshot")
            eligible = category in CATEGORIES and uid not in holds and bool(text.strip())
            result = build_results[uid]
            context = result.context
            if context is not None:
                validate_same_entity_context(context, content_uid=uid, category=category, source_text=text)
                row["sameEntityContext"] = context.to_dict()
                context_from_material(row)
                fields.append(len(context.related_fields))
                chars.append(sum(len(field.source_text) for field in context.related_fields))
                truncated += any(field.truncated for field in context.related_fields)
                pending.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            else:
                pending.append(line)  # Preserve baseline absence bytes exactly.
                reasons[result.absence_reason.value] += 1
            results[uid] = context.context_fingerprint if context else "absent"
            if category in categories:
                stats = categories[category]
                stats["preparedTargets"] += 1
                stats["eligibleTargets"] += eligible
                stats["withContext"] += context is not None
                if eligible and context is None:
                    stats["withoutContext"] += 1
                if context is None:
                    name = result.absence_reason.value
                    stats["absenceReasonCounts"][name] = stats["absenceReasonCounts"].get(name, 0) + 1
            if category == "item" and eligible:
                candidates = [record for record in by_uid.get(uid, ()) if record.category == category]
                native_items = [record for record in candidates if record.template_type == "item"]
                native_map_keys = [record for record in native_items if record.identity_kind == Kind.TEMPLATE_MAP_KEY and record.identity_is_native and record.field_is_direct]
                verified = any(
                    len({other.definition_fingerprint for other in raw_groups[("item", record.entity_identity)]}) == 1
                    and all(other.template_type == "item" and other.identity_is_native
                            and other.identity_kind == Kind.TEMPLATE_MAP_KEY
                            for other in raw_groups[("item", record.entity_identity)])
                    for record in native_map_keys)
                item_sanity["nativeTypeItemTargets"] += bool(native_items)
                item_sanity["nativeMapKeyProofTargets"] += bool(native_map_keys)
                item_sanity["verifiedMapKeyTargets"] += verified
                item_sanity["structuralConflictExcludedTargets"] += bool(native_map_keys) and result.absence_reason == Reason.STRUCTURAL_CONFLICT
                item_sanity["targetsReceivingContext"] += context is not None
        materials.append((path, pending, lines))
    for stats in categories.values():
        stats["coveragePercent"] = round(100 * stats["withContext"] / stats["eligibleTargets"], 6) if stats["eligibleTargets"] else 0.0
    metadata = contract_metadata()
    summary = {"schemaVersion": SUMMARY_VERSION, "contract": metadata, "categories": categories,
               "preparedTargets": len(results), "withContext": len(fields), "absenceReasonCounts": dict(sorted(reasons.items())),
               "meanRelatedFields": fmean(fields) if fields else 0.0, "maxRelatedFields": max(fields, default=0),
               "truncatedContextRows": truncated, "meanContextChars": fmean(chars) if chars else 0.0,
               "p95ContextChars": sorted(chars)[math.ceil(.95 * len(chars)) - 1] if chars else 0,
               "itemSanity": dict(item_sanity), "sameEntityContextMaterialFingerprint": fingerprint(results),
               "inputDigests": {"normalizedSource": fingerprint(sources), "structuralDefinitions": _row_digest(definitions),
                               "structuralOccurrences": _row_digest(occurrences), "classification": _row_digest(class_rows),
                               "holdInventory": fingerprint(sorted(holds))}}
    summary["summaryFingerprint"] = fingerprint(summary)
    # All contexts validate before any material mutation and before run_init.
    for path, pending, original in materials:
        if pending != original:
            path.write_text("".join(pending), encoding="utf-8", newline="\n")
    summary_path.write_text(canonical_json(summary) + "\n", encoding="utf-8", newline="\n")
    return {**metadata, "summaryPath": summary_path.name, "summarySha256": _sha(summary_path),
            "summaryFingerprint": summary["summaryFingerprint"], "withContext": summary["withContext"],
            "sameEntityContextMaterialFingerprint": summary["sameEntityContextMaterialFingerprint"],
            "inputDigests": summary["inputDigests"],
            "inputSha256": {"normalizedSource": _sha(source), "structuralDefinitions": _sha(definition_path),
                            "structuralOccurrences": _sha(occurrence_path), "classification": _sha(classification)}}


def verify_context_materialization(batch_plan: Path, workspace: Path, manifest: dict) -> None:
    enabled = manifest["schemaVersion"] == "1.2"
    actual, present = material_context_fingerprint(batch_plan, enabled=enabled)
    if not enabled:
        if "sameEntityContext" in manifest:
            raise RuntimeError("legacy manifest cannot declare context materialization")
        return
    metadata = manifest.get("sameEntityContext")
    if not isinstance(metadata, dict) or any(metadata.get(key) != value for key, value in contract_metadata().items()):
        raise RuntimeError("unsupported/missing context materialization contract")
    for name, keys in (("inputDigests", {"normalizedSource", "structuralDefinitions", "structuralOccurrences", "classification", "holdInventory"}),
                       ("inputSha256", {"normalizedSource", "structuralDefinitions", "structuralOccurrences", "classification"})):
        digests = metadata.get(name)
        if (not isinstance(digests, dict) or set(digests) != keys
                or any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None for value in digests.values())):
            raise RuntimeError("invalid context input digests")
    if actual != metadata.get("sameEntityContextMaterialFingerprint") or present != metadata.get("withContext"):
        raise RuntimeError("same-entity context material fingerprint/count mismatch")
    name = metadata.get("summaryPath")
    if name != "context-materialization-summary.json":
        raise RuntimeError("invalid context summary path")
    path = workspace / name
    if not path.is_file() or _sha(path) != metadata.get("summarySha256"):
        raise RuntimeError("context summary integrity mismatch")
    summary = json.loads(path.read_text(encoding="utf-8"))
    declared = summary.pop("summaryFingerprint", None)
    if (declared != fingerprint(summary) or declared != metadata.get("summaryFingerprint")
            or summary.get("schemaVersion") != SUMMARY_VERSION or summary.get("contract") != contract_metadata()
            or summary.get("inputDigests") != metadata.get("inputDigests")
            or summary.get("sameEntityContextMaterialFingerprint") != actual or summary.get("withContext") != present):
        raise RuntimeError("context summary contract/fingerprint mismatch")
