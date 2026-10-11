"""Prepare-only adapter and deterministic Policy A materializer.

Never imports execution, prompts, providers or mutable research graph objects.
All evidence families and the complete English snapshot must be supplied before
selecting targets. This integrity contract is not source authentication.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import math
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

from jsonschema import Draft202012Validator, ValidationError

from bg3loc.schema import SchemaStore
from bg3loc.dialogue_context import (
    BUDGET_VERSION, COUNTING_VERSION, MAX_SOURCE_CODEPOINTS, ORDERING_VERSION,
    POLICY_VERSION, SCHEMA_VERSION, DialogueAlternative, DialogueBudgetContract,
    DialogueContext, DialogueSourceVariant, DialogueTargetBinding, DialogueTargetProof,
    NativeChildProof, canonical_bytes, decode_dialogue_context, digest,
    evidence_projection, fail, fingerprint, source_complete, strict_json_loads,
    string, text_hash,
)

ADAPTER_VERSION = "dialogue-public-evidence-adapter/1"
BUILDER_VERSION = "dialogue-context-builder/1"
SUMMARY_VERSION = "dialogue-materialization-summary/1"
ABSENCE_REASONS = (
    "UNSUPPORTED_CATEGORY", "NO_DIALOGUE_OCCURRENCE", "STRUCTURAL_CONFLICT",
    "INCOMPATIBLE_OCCURRENCES", "FALLBACK_IDENTITY", "INCOMPLETE_ENGLISH_CONTEXT",
    "NO_LOCALIZED_RELATION", "BUDGET_EXCEEDED",
)
_FAMILIES = ("dialogue", "node", "occurrence", "edge")
_FIELDS = {
    "dialogue": {"dialogueIdentityOrigin", "definitionFingerprint", "nodeCount", "provenance"},
    "node": {"nodeId", "dialogueIdentityOrigin", "nodeIdentityOrigin", "definitionFingerprint",
             "nodeType", "nodeKind", "speaker", "unresolvedLocalizationHandles", "provenance"},
    "occurrence": {"nodeId", "definitionFingerprint", "contentUid", "version", "fieldRole",
                   "lineId", "variantFingerprint", "provenance"},
    "edge": {"nodeId", "definitionFingerprint", "fromNode", "toNode", "edgeType",
             "relationKind", "childIndex", "referenceParameters", "provenance"},
}


def jsonl_rows(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                fail()
            row = strict_json_loads(line)
            if type(row) is not dict:
                fail()
            yield row


def sealed_evidence_rows(directory: Path):
    """Verify all five P1 ledgers; targetEvidence is sealed, never trusted as graph."""
    summary = strict_json_loads((directory / "dialogue-summary.json").read_bytes())
    if type(summary) is not dict or type(summary.get("ledgerSemanticFingerprints")) is not dict:
        fail()
    for family in (*_FAMILIES, "targetEvidence"):
        expected = summary["ledgerSemanticFingerprints"].get(family)
        digest(expected)
        seal = sha256(b"[")
        first = True
        for row in jsonl_rows(directory / f"dialogue-{family}.jsonl"):
            if row.get("recordType") != family:
                fail()
            if not first:
                seal.update(b",")
            seal.update(canonical_bytes(row))
            first = False
            if family != "targetEvidence":
                yield row
        seal.update(b"]")
        if seal.hexdigest() != expected:
            fail("DLG_FINGERPRINT_MISMATCH")


def load_english_sources(path: Path) -> dict[str, str]:
    sources = {}
    for row in jsonl_rows(path):
        uid, text = row.get("contentUid"), row.get("text")
        string(uid)
        if type(text) is not str or row.get("localeId") != "English" or uid in sources:
            fail("DLG_BINDING_MISMATCH")
        # Empty English rows remain in the full universe for exclusion decisions.
        canonical_bytes(text)
        sources[uid] = text
    return sources


@dataclass(frozen=True, slots=True)
class _Node:
    definition: str
    dialogue_origin: str
    node_origin: str
    kind: str
    node_type: str
    projection_seal: str


@dataclass(frozen=True, slots=True)
class MaterializationResult:
    context: DialogueContext | None
    absence_reason: str | None


@dataclass(frozen=True, slots=True)
class DialogueEvidenceAdapter:
    """Owned immutable projection, constructed only after full-universe checks.

    Inputs are copied into frozen nodes, tuples, frozensets and mapping proxies.
    Speaker data is never used for selection or emitted; its sealed native
    definition closure is retained for conflict detection, as in Phase 1/2.
    """

    sources: Mapping[str, str]
    nodes: Mapping[tuple[str, str], _Node]
    dialogues: Mapping[str, str]
    conflicts: frozenset[tuple[str, str]]
    valid: frozenset[tuple[str, str]]
    occurrences: Mapping[tuple[str, str], Mapping[str, tuple[str, ...]]]
    locations: Mapping[str, frozenset[tuple[str, str]]]
    predecessors: Mapping[tuple[str, str], tuple[tuple[str, str], ...]]
    successors: Mapping[tuple[str, str], tuple[tuple[str, str], ...]]
    child_proofs: Mapping[tuple[tuple[str, str], tuple[str, str]], str]
    input_digests: Mapping[str, str]

    @classmethod
    def from_records(cls, records: Iterable[dict], sources: Mapping[str, str]) -> DialogueEvidenceAdapter:
        """Caller supplies the whole universe, never a target-filtered graph.

        Filesystem callers should use from_workspace(), which additionally
        verifies the complete P1 ledger seals before returning an adapter.
        """
        copied_sources = dict(sources)
        for uid, text in copied_sources.items():
            string(uid)
            if type(text) is not str:
                fail()
            canonical_bytes(text)
        validator = Draft202012Validator(SchemaStore().load("research/dialogue-context-evidence-v1.schema.json"))
        variants = defaultdict(dict)
        dialogues = defaultdict(dict)
        occurrences = defaultdict(lambda: defaultdict(set))
        occurrence_bindings = []
        edges = []
        family_seals = {family: set() for family in _FAMILIES}
        for row in records:
            canonical_bytes(row)
            if type(row) is not dict or row.get("recordType") not in _FAMILIES:
                fail()
            family = row["recordType"]
            allowed = {"schemaVersion", "recordType", "evidenceId", "dialogueId"} | _FIELDS[family]
            if family == "edge" and "structuralStatus" in row:
                allowed = allowed | {"structuralStatus"}
            if set(row) != allowed:
                fail()
            try:
                validator.validate(row)
            except ValidationError:
                fail()
            for field in ("nodeCount", "unresolvedLocalizationHandles", "childIndex"):
                if field in row and row[field] is not None and type(row[field]) is not int:
                    fail()
            original = {k: v for k, v in row.items() if k not in {"evidenceId", "structuralStatus"}}
            if fingerprint(original) != row["evidenceId"]:
                fail("DLG_FINGERPRINT_MISMATCH")
            family_seals[family].add(fingerprint(row))
            d = row["dialogueId"]
            string(d)
            definition = row["definitionFingerprint"]
            if family == "dialogue":
                projection = (row["dialogueIdentityOrigin"], row["nodeCount"])
                if definition in dialogues[d] and dialogues[d][definition] != projection:
                    fail("DLG_BINDING_MISMATCH")
                dialogues[d][definition] = projection
                continue
            key = (d, row["nodeId"])
            string(key[1])
            if family == "node":
                # Compare all projection facts under one digest, without inferring
                # speaker identities or relationships from those opaque facts.
                projection = fingerprint({k: v for k, v in original.items() if k != "provenance"})
                node = _Node(definition, row["dialogueIdentityOrigin"], row["nodeIdentityOrigin"],
                             row["nodeKind"], row["nodeType"], projection)
                if definition in variants[key] and variants[key][definition] != node:
                    fail("DLG_BINDING_MISMATCH")
                variants[key][definition] = node
            elif family == "occurrence":
                # Resource duplicates collapse by native assertion, not source text.
                assertion = {k: v for k, v in original.items() if k not in {"provenance", "schemaVersion", "recordType"}}
                occurrences[key][row["contentUid"]].add(fingerprint(assertion))
                occurrence_bindings.append((key, definition))
            else:
                if row["fromNode"] != row["nodeId"]:
                    fail("DLG_BINDING_MISMATCH")
                if row["edgeType"] == "child":
                    reference = row["referenceParameters"].get("UUID")
                    if (row["relationKind"] != "potential_control_flow" or type(row["childIndex"]) is not int
                            or type(reference) is not dict or reference.get("value") != row["toNode"]
                            or row["provenance"].get("fieldRole") != "children.child.UUID"):
                        fail("DLG_BINDING_MISMATCH")
                elif row["relationKind"] != "reference_only":
                    fail("DLG_BINDING_MISMATCH")
                assertion = {k: v for k, v in original.items() if k not in {"provenance", "schemaVersion", "recordType"}}
                edges.append((key, (d, row["toNode"]), definition, row["edgeType"],
                              fingerprint(assertion), row.get("structuralStatus")))
        # Dangling native Child destinations can exist in the game and are excluded.
        # An occurrence or edge with no owning definition is malformed evidence.
        for key, definition in occurrence_bindings:
            if definition not in variants.get(key, {}) or variants[key][definition].kind != "localized":
                fail("DLG_BINDING_MISMATCH")
        for key, choices in variants.items():
            if key[0] not in dialogues:
                fail("DLG_BINDING_MISMATCH")
            for node in choices.values():
                if not any(origin == node.dialogue_origin for origin, _ in dialogues[key[0]].values()):
                    fail("DLG_BINDING_MISMATCH")
                if node.kind == "localized" and key not in occurrences:
                    fail("DLG_BINDING_MISMATCH")
        conflicts = frozenset(key for key, choices in variants.items()
                              if len(choices) != 1 or len(dialogues[key[0]]) != 1)
        nodes = {key: next(iter(choices.values())) for key, choices in variants.items() if len(choices) == 1}
        valid = frozenset(key for key, node in nodes.items() if key not in conflicts
                          and node.dialogue_origin == node.node_origin == "native_UUID")
        adj, rev, proofs = defaultdict(set), defaultdict(set), defaultdict(set)
        for a, b, definition, edge_type, assertion, declared_status in edges:
            if definition not in variants.get(a, {}):
                fail("DLG_BINDING_MISMATCH")
            status = ("missing_endpoint" if b not in variants else
                      "conflict_or_fallback" if a not in valid or b not in valid else
                      "DIRECT" if edge_type == "child" else "reference_only")
            if declared_status is not None and declared_status != status:
                fail("DLG_BINDING_MISMATCH")
            if edge_type == "child" and a in valid and b in valid and definition == nodes[a].definition:
                adj[a].add(b)
                rev[b].add(a)
                proofs[(a, b)].add(assertion)
        locations = defaultdict(set)
        for key, by_uid in occurrences.items():
            for uid in by_uid:
                locations[uid].add(key)
        return cls(
            MappingProxyType(copied_sources), MappingProxyType(nodes),
            MappingProxyType({d: next(iter(choices)) for d, choices in dialogues.items() if len(choices) == 1}),
            conflicts, valid,
            MappingProxyType({key: MappingProxyType({uid: tuple(sorted(seals)) for uid, seals in by_uid.items()})
                              for key, by_uid in occurrences.items()}),
            MappingProxyType({uid: frozenset(keys) for uid, keys in locations.items()}),
            MappingProxyType({key: tuple(sorted(keys)) for key, keys in rev.items()}),
            MappingProxyType({key: tuple(sorted(keys)) for key, keys in adj.items()}),
            MappingProxyType({key: fingerprint(sorted(seals)) for key, seals in proofs.items()}),
            MappingProxyType({"source": fingerprint({uid: sha256(text.encode("utf-8")).hexdigest()
                                                     for uid, text in copied_sources.items()}),
                              **{family: fingerprint(sorted(seals)) for family, seals in family_seals.items()}}),
        )

    @classmethod
    def from_workspace(cls, evidence_dir: Path, source_snapshot: Path) -> DialogueEvidenceAdapter:
        return cls.from_records(sealed_evidence_rows(evidence_dir), load_english_sources(source_snapshot))

    def materialize(self, content_uid: str, category: str, source_text: str) -> MaterializationResult:
        """Full A set first, original-text count second, atomic budget fallback."""
        if content_uid not in self.sources or self.sources[content_uid] != source_text:
            fail("DLG_BINDING_MISMATCH")
        def absent(reason):
            return MaterializationResult(None, reason)
        if category != "dialogue_general":
            return absent("UNSUPPORTED_CATEGORY")
        locations = self.locations.get(content_uid, frozenset())
        if not locations:
            return absent("NO_DIALOGUE_OCCURRENCE")
        if locations & self.conflicts:
            return absent("STRUCTURAL_CONFLICT")
        if len(locations) != 1:
            return absent("INCOMPATIBLE_OCCURRENCES")
        key = next(iter(locations))
        if key not in self.valid:
            return absent("FALLBACK_IDENTITY")
        directions = []
        incomplete = False
        for adjacency, predecessor in ((self.predecessors, True), (self.successors, False)):
            groups = []
            for candidate in adjacency.get(key, ()):
                node = self.nodes[candidate]
                if candidate == key or node.kind != "localized":
                    continue
                variants = []
                for uid, seals in sorted(self.occurrences[candidate].items()):
                    if uid == content_uid:
                        continue
                    text = self.sources.get(uid)
                    if text is None or not source_complete(text):
                        incomplete = True
                        continue
                    variants.append(DialogueSourceVariant(uid, text, seals))
                if variants:
                    a, b = (candidate, key) if predecessor else (key, candidate)
                    groups.append(DialogueAlternative(candidate[1], "native_UUID", node.definition,
                        NativeChildProof("child", a[1], b[1], self.child_proofs[(a, b)]), tuple(variants)))
            directions.append(tuple(groups))
        if incomplete:
            return absent("INCOMPLETE_ENGLISH_CONTEXT")
        pred, succ = directions
        if not pred and not succ:
            return absent("NO_LOCALIZED_RELATION")
        size = sum(len(v.source_text) for g in pred + succ for v in g.source_variants)
        if size > MAX_SOURCE_CODEPOINTS:
            return absent("BUDGET_EXCEEDED")
        node = self.nodes[key]
        data = {
            "schemaVersion": SCHEMA_VERSION, "policyVersion": POLICY_VERSION,
            "orderingVersion": ORDERING_VERSION, "budgetContract": DialogueBudgetContract().to_dict(),
            "targetBinding": DialogueTargetBinding(content_uid, category, text_hash(source_text)).to_dict(),
            "targetProof": DialogueTargetProof(key[0], "native_UUID", key[1], "native_UUID",
                self.dialogues[key[0]], node.definition,
                fingerprint(self.occurrences[key][content_uid])).to_dict(),
            "possiblePredecessors": [g.to_dict() for g in pred],
            "possibleSuccessors": [g.to_dict() for g in succ], "sourceCodepoints": size,
        }
        data["evidenceFingerprint"] = fingerprint(evidence_projection(data))
        data["contextFingerprint"] = fingerprint(data)
        return MaterializationResult(decode_dialogue_context(data, content_uid=content_uid,
            category=category, source_text=source_text), None)


def _stats(values: list[int]) -> dict:
    if not values:
        return {"mean": 0, "p95": 0, "max": 0}
    values = sorted(values)
    return {"mean": sum(values) / len(values), "p95": values[math.ceil(.95 * len(values)) - 1], "max": values[-1]}


def materialize_inventory(adapter: DialogueEvidenceAdapter, inventory: Mapping[str, str]):
    """Canonical UID inventory, independent of production batch splits/order."""
    results, material, reasons, categories, costs, lines = {}, {}, Counter(), defaultdict(Counter), [], []
    for uid, category in sorted(inventory.items()):
        string(uid)
        string(category)
        if uid not in adapter.sources:
            fail("DLG_BINDING_MISMATCH")
        result = adapter.materialize(uid, category, adapter.sources[uid])
        results[uid] = result
        categories[category]["targets"] += 1
        if result.context is None:
            reasons[result.absence_reason] += 1
            categories[category]["absent"] += 1
            material[uid] = "absent"
        else:
            context = result.context
            material[uid] = context.context_fingerprint
            categories[category]["present"] += 1
            costs.append(context.source_codepoints)
            lines.append(sum(len(g.source_variants) for g in context.possible_predecessors + context.possible_successors))
    summary = {
        "schemaVersion": SUMMARY_VERSION,
        "contract": {"structuralPolicy": POLICY_VERSION, "ordering": ORDERING_VERSION,
                     "budget": BUDGET_VERSION, "adapter": ADAPTER_VERSION, "builder": BUILDER_VERSION},
        "preparedTargets": len(inventory), "withContext": len(costs),
        "absenceReasonCounts": dict(sorted(reasons.items())),
        "byCategory": {category: {k: counts[k] for k in ("targets", "present", "absent")}
                       for category, counts in sorted(categories.items())},
        "sourceCharsStats": _stats(costs), "lineCardinalityStats": _stats(lines),
        "inputDigests": {**adapter.input_digests, "classification": fingerprint(dict(inventory))},
        "dialogueContextMaterialFingerprint": fingerprint(material),
    }
    summary["summaryFingerprint"] = fingerprint(summary)
    return MappingProxyType(results), summary
