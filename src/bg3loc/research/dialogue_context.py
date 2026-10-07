"""Research-only dialogue graphs. Explicit alternatives are never a transcript.

No source text, actor-name inference, prompt policy, or production integration.
Child UUIDs are potential control flow; jumps/aliases/nested calls are retained
as references until their runtime transfer semantics have been verified.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
import json
from pathlib import Path
import re
from typing import Any, Iterable

from bg3loc.research.model import HANDLE_PATTERN
from bg3loc.research.structural_provenance import (
    canonical_json, definition_fingerprint, source_resource,
)

VERSION = "dialogue-context-evidence/1"
PROJECTION = "dialogue-structure/1"
UUID_PATTERN = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I)
STRUCTURAL_TYPES = {"Jump", "Visual State", "RollResult", "PassiveRoll",
                    "FallibleQuestionResult", "Nested Dialog", "Trade"}


def value(obj: Any) -> Any:
    result = obj.get("value", "") if isinstance(obj, dict) else obj
    return "" if result is None else result


def members(obj: Any, key: str) -> list[dict]:
    """Read one named LSJ child collection, never recursively find identities."""
    if isinstance(obj, dict):
        obj = [obj]
    if obj is None:
        return []
    if not isinstance(obj, list):
        raise ValueError("LSJ child collection must be an object or array")
    result = []
    for block in obj:
        if not isinstance(block, dict):
            raise ValueError("LSJ child must be an object")
        child = block.get(key, [])
        if isinstance(child, dict):
            child = [child]
        if not isinstance(child, list) or any(not isinstance(x, dict) for x in child):
            raise ValueError("invalid named LSJ child collection")
        result.extend(child)
    return result


def structural_projection(obj: Any) -> Any:
    """Exclude editor metadata; retain ordered choices, conditions and controls.

    Node-table and speaker-table order are canonicalized by their native keys
    outside this function. Other arrays can encode priority/variant order and
    must not be sorted as though they were sets.
    """
    if isinstance(obj, dict):
        return {k: structural_projection(v) for k, v in obj.items()
                if k != "editorData"}
    if isinstance(obj, list):
        return [structural_projection(x) for x in obj]
    return obj


def text_occurrences(node: dict) -> tuple[list[dict], int]:
    result = []; unresolved = 0
    for tagged in members(node.get("TaggedTexts"), "TaggedText"):
        # Rule groups belong to the variant; text selection is not unique.
        rules = {k: v for k, v in tagged.items() if k != "TagTexts"}
        for leaf in members(tagged.get("TagTexts"), "TagText"):
            text = leaf.get("TagText")
            if not isinstance(text, dict):
                continue
            match = HANDLE_PATTERN.fullmatch(str(text.get("handle", "")))
            if not match:
                if text.get("handle") == "ls::TranslatedStringRepository::s_HandleUnknown":
                    unresolved += 1
                    continue
                if text.get("handle"):
                    raise ValueError("unrecognized dialogue localization handle")
                continue
            result.append({
                "contentUid": match.group("uid"),
                "version": str(text.get("version", match.group("ver") or "")),
                "fieldRole": "TaggedTexts.TaggedText.TagTexts.TagText",
                "lineId": str(value(leaf.get("LineId", ""))),
                "variantFingerprint": definition_fingerprint({"rules": rules, "text": leaf}),
            })
    return result, unresolved


def speaker_evidence(node: dict, mappings: dict[str, list[dict]]) -> dict:
    raw = node.get("speaker")
    slot = str(value(raw)) if raw is not None else ""
    choices = {canonical_json(x): x for x in mappings.get(slot, [])}
    rows = [choices[k] for k in sorted(choices)]
    references = sorted({part for x in rows for part in str(value(x.get("list", ""))).split(";")
                         if part})
    status = "missing" if not slot else "slot_only"
    if len(rows) > 1 or len(references) > 1:
        status = "ambiguous"
    elif (len(references) == 1 and UUID_PATTERN.fullmatch(references[0])
          and references[0] != "00000000-0000-0000-0000-000000000000"):
        status = "explicit_reference"
    return {"slot": slot, "status": status, "references": references,
            "mappingEvidence": rows, "resolution": "static_reference_only"}


def parse_dialogue(data: dict, *, package: str, resource: str) -> list[dict]:
    scope = source_resource(package, resource)
    save = data.get("save", data)
    dialog = save.get("regions", {}).get("dialog")
    if not isinstance(dialog, dict):
        raise ValueError("selected resource has no native dialog region")
    native_id = str(value(dialog.get("UUID", "")))
    dialog_id = native_id or "resource:" + scope
    dialog_origin = "native_UUID" if native_id else "resource_scope"
    maps: dict[str, list[dict]] = defaultdict(list)
    for mapping in members(dialog.get("speakerlist"), "speaker"):
        maps[str(value(mapping.get("index", "")))].append(mapping)
    nodes = members(dialog.get("nodes"), "node")
    rows = []
    node_fingerprints = []
    for ordinal, node in enumerate(nodes):
        native_node = str(value(node.get("UUID", "")))
        node_id = native_node or f"ordinal:{ordinal}"
        node_origin = "native_UUID" if native_node else "fallback_ordinal"
        speaker = speaker_evidence(node, maps)
        # A slot is interpreted by its enclosing dialogue's table. Bind that
        # native table evidence as well, so changed mappings cannot overwrite
        # an otherwise identical node variant during conflict aggregation.
        fingerprint = definition_fingerprint({"projectionVersion": PROJECTION,
                                              "node": structural_projection(node),
                                              "speakerMappingEvidence": speaker["mappingEvidence"]})
        node_fingerprints.append({"nodeId": node_id, "fingerprint": fingerprint})
        texts, unresolved = text_occurrences(node)
        node_type = str(value(node.get("constructor", "")))
        kind = ("localized" if texts else
                "structural_only" if node_type in STRUCTURAL_TYPES else "unknown")
        binding = {"dialogueId": dialog_id, "nodeId": node_id,
                   "definitionFingerprint": fingerprint}
        provenance = {"sourceResource": scope}
        rows.append({"recordType": "node", **binding, "dialogueIdentityOrigin": dialog_origin,
                     "nodeIdentityOrigin": node_origin, "nodeType": node_type,
                     "nodeKind": kind, "speaker": speaker,
                     "unresolvedLocalizationHandles": unresolved,
                     "provenance": provenance})
        for occurrence in texts:
            rows.append({"recordType": "occurrence", **binding, **occurrence,
                         "provenance": provenance})
        for child_index, child in enumerate(members(node.get("children"), "child")):
            target = str(value(child.get("UUID", "")))
            if not target:
                raise ValueError("child edge without native UUID")
            rows.append({"recordType": "edge", **binding, "fromNode": node_id,
                         "toNode": target, "edgeType": "child",
                         "relationKind": "potential_control_flow", "childIndex": child_index,
                         "referenceParameters": structural_projection(child),
                         "provenance": {**provenance, "fieldRole": "children.child.UUID"}})
        for field in ("jumptarget", "SourceNode", "NestedDialogNodeUUID"):
            target = str(value(node.get(field, "")))
            if not target:
                continue
            rows.append({"recordType": "edge", **binding, "fromNode": node_id,
                         "toNode": target, "edgeType": field,
                         "relationKind": "reference_only", "childIndex": None,
                         "referenceParameters": {"target": node[field],
                             "jumptargetpoint": node.get("jumptargetpoint"),
                             "SpeakerLinking": node.get("SpeakerLinking")},
                         "provenance": {**provenance, "fieldRole": field}})
    header = {k: structural_projection(v) for k, v in dialog.items()
              if k not in {"nodes", "speakerlist", "editorData"}}
    speakers = sorted((structural_projection(m) for choices in maps.values() for m in choices),
                      key=canonical_json)
    rows.append({"recordType": "dialogue", "dialogueId": dialog_id,
                 "dialogueIdentityOrigin": dialog_origin,
                 "definitionFingerprint": definition_fingerprint({
                     "projectionVersion": PROJECTION, "definition": header,
                     "speakers": speakers, "nodes": sorted(node_fingerprints, key=canonical_json)}),
                 "nodeCount": len(nodes), "provenance": {"sourceResource": scope}})
    for row in rows:
        row["schemaVersion"] = VERSION
        row["evidenceId"] = definition_fingerprint(row)
    return rows


class DialogueAudit:
    """Retain every definition variant. Resolution is fail-closed, not overlay."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def add(self, records: Iterable[dict]) -> None:
        for row in records:
            self.rows[row["evidenceId"]] = row

    def analyze(self, targets: dict[str, str] | None = None, *, max_hops: int = 8) -> tuple[list[dict], dict]:
        if max_hops < 1:
            raise ValueError("max_hops must be positive")
        nodes: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
        dialogs: dict[str, set[str]] = defaultdict(set)
        node_sources: Counter = Counter()
        dialog_sources: Counter = Counter()
        occurrences: dict[tuple[str, str], list[dict]] = defaultdict(list)
        edge_rows = []
        for row in self.rows.values():
            dialog = row["dialogueId"]
            if row["recordType"] == "dialogue":
                dialogs[dialog].add(row["definitionFingerprint"]); dialog_sources[dialog] += 1
            elif row["recordType"] == "node":
                key = (dialog, row["nodeId"])
                nodes[key][row["definitionFingerprint"]] = row; node_sources[key] += 1
            elif row["recordType"] == "occurrence":
                occurrences[(dialog, row["nodeId"])].append(row)
            elif row["recordType"] == "edge":
                edge_rows.append(row)
        conflicts = {key for key, variants in nodes.items() if len(variants) != 1}
        dialog_conflicts = {d for d, variants in dialogs.items() if len(variants) != 1}
        # A representative is inspected only when there is exactly one variant.
        stable = {k: next(iter(v.values())) for k, v in nodes.items() if k not in conflicts}
        def consensus(key: tuple[str, str], field: str, fallback: Any) -> Any:
            values = {canonical_json(v[field]): v[field] for v in nodes[key].values()}
            return next(iter(values.values())) if len(values) == 1 else fallback

        ambiguous_speaker = {"status": "ambiguous", "slot": "", "references": [],
                             "mappingEvidence": [], "resolution": "static_reference_only"}
        usable = {k for k, n in stable.items() if k[0] not in dialog_conflicts
                  and n["dialogueIdentityOrigin"] == "native_UUID"
                  and n["nodeIdentityOrigin"] == "native_UUID"}
        successors: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
        predecessors: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
        edge_status = Counter()
        resolved_edges = []
        for edge in sorted(edge_rows, key=lambda r: r["evidenceId"]):
            a, b = (edge["dialogueId"], edge["fromNode"]), (edge["dialogueId"], edge["toNode"])
            status = ("missing_endpoint" if b not in nodes else
                      "conflict_or_fallback" if a not in usable or b not in usable else
                      "reference_only" if edge["relationKind"] == "reference_only" else "DIRECT")
            edge_status[status] += 1
            if status == "DIRECT":
                successors[a].add(b); predecessors[b].add(a)
            resolved_edges.append({**edge, "structuralStatus": status})
        localized = {k for k in usable if stable[k]["nodeKind"] == "localized"}

        def nearest(start: tuple[str, str], graph: dict) -> dict:
            frontier = deque((n, 1) for n in sorted(graph.get(start, set())))
            visited = {start}; found = {}; cycles = False; blocked = False; bounded = False
            while frontier:
                node, hops = frontier.popleft()
                if node in visited:
                    # Convergence is not evidence of a runtime history either.
                    cycles = True; continue
                visited.add(node)
                if node in localized:
                    found[node[1]] = hops; continue
                if node not in usable or stable[node]["nodeKind"] != "structural_only":
                    blocked = True; continue
                adjacent = graph.get(node, set())
                if adjacent and hops >= max_hops:
                    bounded = True; continue
                frontier.extend((n, hops + 1) for n in sorted(adjacent))
            return {"nodes": [{"nodeId": n, "hops": found[n]} for n in sorted(found)],
                    "revisitedNode": cycles, "blockedUnknown": blocked, "boundReached": bounded,
                    "maxHops": max_hops, "reliability": "INDIRECT"}

        evidence = []
        speaker_counts = Counter(); pred_counts = Counter(); succ_counts = Counter()
        safe_uids = set(); observed_uids = set(); indirect_nodes = 0
        for key in sorted(occurrences):
            n = stable.get(key)
            safe = key in localized
            pred = sorted(x[1] for x in predecessors.get(key, set())) if safe else []
            succ = sorted(x[1] for x in successors.get(key, set())) if safe else []
            lp = [p for p in pred if (key[0], p) in localized]
            ls = [s for s in succ if (key[0], s) in localized]
            indirect_pred = nearest(key, predecessors) if safe else None
            indirect_succ = nearest(key, successors) if safe else None
            if safe and any(x["hops"] > 1 for result in (indirect_pred, indirect_succ)
                            for x in result["nodes"]):
                indirect_nodes += 1
            status = "AMBIGUOUS" if safe and (len(pred) > 1 or len(succ) > 1) else "DIRECT" if safe and (pred or succ) else "UNSUPPORTED"
            row = {"schemaVersion": VERSION, "recordType": "targetEvidence",
                   "dialogueId": key[0], "nodeId": key[1],
                   "nodeType": consensus(key, "nodeType", ""),
                   "dialogueIdentityOrigins": sorted({v["dialogueIdentityOrigin"] for v in nodes[key].values()}),
                   "nodeIdentityOrigins": sorted({v["nodeIdentityOrigin"] for v in nodes[key].values()}),
                   "definitionFingerprints": sorted(nodes[key]),
                   "dialogueDefinitionFingerprints": sorted(dialogs[key[0]]),
                   "conflict": key in conflicts or key[0] in dialog_conflicts,
                   "speaker": consensus(key, "speaker", ambiguous_speaker),
                   "speakerEvidenceVariants": sorted({canonical_json(v["speaker"]): v["speaker"]
                       for v in nodes[key].values()}.values(), key=canonical_json),
                   "directPredecessors": pred, "directSuccessors": succ,
                   "directLocalizedPredecessors": lp, "directLocalizedSuccessors": ls,
                   "nearestLocalizedPredecessors": indirect_pred,
                   "nearestLocalizedSuccessors": indirect_succ,
                   "relationReliability": status,
                   "occurrenceEvidenceIds": sorted(o["evidenceId"] for o in occurrences[key]),
                   "contentUids": sorted({o["contentUid"] for o in occurrences[key]})}
            row["evidenceId"] = definition_fingerprint(row); evidence.append(row)
            observed_uids.update(row["contentUids"])
            if lp or ls:
                safe_uids.update(row["contentUids"])
            speaker_counts[row["speaker"]["status"]] += 1
            pred_counts["none" if not lp else "one" if len(lp) == 1 else "multiple"] += 1
            succ_counts["none" if not ls else "one" if len(ls) == 1 else "multiple"] += 1
        # A shared ContentUid is not a unique occurrence. Reject coverage when
        # any occurrence lacks the relation, or its structural signature differs.
        uid_signatures: dict[str, set[str]] = defaultdict(set)
        uid_unsafe = set()
        for row in evidence:
            sig = canonical_json({k: row[k] for k in ("dialogueId", "nodeId", "definitionFingerprints",
                                                      "directLocalizedPredecessors", "directLocalizedSuccessors")})
            for uid in row["contentUids"]:
                uid_signatures[uid].add(sig)
                if not (row["directLocalizedPredecessors"] or row["directLocalizedSuccessors"]):
                    uid_unsafe.add(uid)
        unambiguous_uids = {u for u in safe_uids if len(uid_signatures[u]) == 1 and u not in uid_unsafe}
        target_keys = set(targets or {})
        report = {
            "schemaVersion": VERSION, "projectionVersion": PROJECTION,
            "dialogues": len(dialogs), "nodes": len(nodes),
            "nodeDefinitionVariants": sum(len(v) for v in nodes.values()),
            "localizedOccurrenceRecords": sum(len(v) for v in occurrences.values()),
            "uniqueLocalizedOccurrences": len({(r["dialogueId"], r["nodeId"], r["contentUid"],
                r["lineId"], r["variantFingerprint"]) for v in occurrences.values() for r in v}),
            "localizedNodes": len(occurrences),
            "usableNativeNonconflictingNodes": len(usable),
            "unresolvedLocalizationHandleVariants": sum(v["unresolvedLocalizationHandles"] for variants in nodes.values() for v in variants.values()),
            "nodeTypes": dict(sorted(Counter(consensus(k, "nodeType", "ambiguous") for k in nodes).items())),
            "nodeKinds": dict(sorted(Counter(consensus(k, "nodeKind", "ambiguous") for k in nodes).items())),
            "explicitSpeakerNodes": sum(consensus(k, "speaker", ambiguous_speaker)["status"] == "explicit_reference" for k in nodes),
            "speakerAllNodes": dict(Counter(consensus(k, "speaker", ambiguous_speaker)["status"] for k in nodes)),
            "speakerLocalizedNodes": dict(sorted(speaker_counts.items())),
            "directLocalizedPredecessors": dict(pred_counts), "directLocalizedSuccessors": dict(succ_counts),
            "nodesWithDirectPredecessor": len(predecessors), "nodesWithDirectSuccessor": len(successors),
            "nodesWithMultiplePredecessors": sum(len(v) > 1 for v in predecessors.values()),
            "nodesWithMultipleSuccessors": sum(len(v) > 1 for v in successors.values()),
            "indirectLocalizedNodes": indirect_nodes,
            "conflictingDialogues": len(dialog_conflicts), "conflictingNodes": len(conflicts),
            "identicalDuplicateDialogues": sum(dialog_sources[d] > len(dialogs[d]) for d in dialogs),
            "identicalDuplicateNodes": sum(node_sources[k] > len(nodes[k]) for k in nodes),
            "edgeRecords": len(edge_rows), "edgeTypes": dict(Counter(e["edgeType"] for e in edge_rows)),
            "edgeStatus": dict(edge_status),
            "productionEstimate": {"targets": len(target_keys),
                "byCategory": dict(Counter((targets or {}).values())),
                "observedInGraph": len(target_keys & observed_uids),
                "atLeastOneOccurrenceWithDirectRelation": len(target_keys & safe_uids),
                "reliableUnambiguousDirectRelation": len(target_keys & unambiguous_uids),
                "withoutReliableRelation": len(target_keys - unambiguous_uids),
                "coveragePercent": 100 * len(target_keys & unambiguous_uids) / len(target_keys) if target_keys else 0},
            "winnerSelection": False, "providerCalls": 0,
        }
        return resolved_edges + evidence, report

    def write(self, output: Path, targets: dict[str, str] | None = None) -> dict:
        output.mkdir(parents=True, exist_ok=True)
        resolved, report = self.analyze(targets)
        families = defaultdict(list)
        for row in self.rows.values():
            if row["recordType"] != "edge":
                families[row["recordType"]].append(row)
        for row in resolved:
            families[row["recordType"]].append(row)
        hashes = {}
        for family in ("dialogue", "node", "occurrence", "edge", "targetEvidence"):
            rows = sorted(families[family], key=lambda r: r["evidenceId"])
            raw = "".join(canonical_json(r) + "\n" for r in rows).encode("utf-8")
            (output / f"dialogue-{family}.jsonl").write_bytes(raw)
            hashes[family] = definition_fingerprint(rows)
        report["ledgerSemanticFingerprints"] = hashes
        (output / "dialogue-summary.json").write_text(canonical_json(report) + "\n", encoding="utf-8")
        return report
