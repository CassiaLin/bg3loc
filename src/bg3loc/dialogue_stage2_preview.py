"""Read Stage 1 envelopes for OFFLINE validation, never as execution material.

Returns typed contexts only. Does not publish a manifest, seed execution items,
initialize a DB, or invoke a worker/provider. Target text comes from the existing
prepared inventory; neither game archives nor a full source universe is read.
"""
from pathlib import Path
from types import MappingProxyType
from collections import Counter, defaultdict
import math

from bg3loc.dialogue_context import decode_dialogue_context, fingerprint, fail, strict_json_loads, text_hash, digest, canonical_bytes
from bg3loc.dialogue_execution_contract import contained_file
from bg3loc.dialogue_materialization import jsonl_rows, SUMMARY_VERSION, ABSENCE_REASONS, ADAPTER_VERSION, BUILDER_VERSION
from bg3loc.dialogue_context import POLICY_VERSION, ORDERING_VERSION, BUDGET_VERSION
from bg3loc.dialogue_stage_prepare import STAGE_VERSION
from bg3loc.production_context import context_from_material
from bg3loc.production_workspace import sha256_file


def read_stage1_contexts_for_validation(stage_dir: Path, batch_plan: Path):
    """No runtime authorization is conveyed by this read-only typed mapping."""
    marker_path = stage_dir / "stage1-manifest.json"
    marker_seal = sha256_file(marker_path)
    manifest = strict_json_loads(marker_path.read_bytes())
    if (type(manifest) is not dict or set(manifest) != {"stageSchemaVersion", "status", "localOnly", "productionActivation", "records", "summary"}
            or manifest["stageSchemaVersion"] != STAGE_VERSION or manifest["status"] != "NOT_EXECUTABLE"
            or manifest["localOnly"] is not True or manifest["productionActivation"] is not False):
        fail("CONTEXT_CONTRACT_MISMATCH")
    if (type(manifest["records"]) is not dict or set(manifest["records"]) != {"path", "sha256"}
            or type(manifest["summary"]) is not dict or set(manifest["summary"]) != {"path", "sha256", "fingerprint"}):
        fail("CONTEXT_CONTRACT_MISMATCH")
    paths = {}
    for key in ("records", "summary"):
        entry = manifest[key]
        path = contained_file(stage_dir, entry["path"])
        if sha256_file(path) != entry["sha256"]:
            fail("CONTEXT_CONTRACT_MISMATCH")
        paths[key] = path
    prepared = {}
    plan = strict_json_loads(batch_plan.read_bytes())
    if type(plan) is not dict or not plan.get("batchPlanFingerprint") or type(plan.get("batches")) is not list:
        fail("CONTEXT_CONTRACT_MISMATCH")
    batch_ids = set()
    for batch in plan["batches"]:
        batch_id = batch["batchId"]
        if batch_id in batch_ids:
            fail("CONTEXT_CONTRACT_MISMATCH")
        batch_ids.add(batch_id)
        material = contained_file(batch_plan.parent, f"materials/{batch_id}.jsonl")
        found = []
        for row in jsonl_rows(material):
            uid = row["contentUid"]
            if (uid in prepared or row["primaryCategory"] != batch["primaryCategory"] or row["batchId"] != batch_id
                    or "dialogueContext" in row):
                fail("CONTEXT_CONTRACT_MISMATCH")
            context_from_material(row)  # Existing B1-02 strict validation only.
            prepared[uid] = row
            found.append(uid)
        if type(batch["recordCount"]) is not int or len(found) != batch["recordCount"] or sorted(found) != sorted(batch["contentUids"]):
            fail("CONTEXT_CONTRACT_MISMATCH")
    contexts, material_map, present = {}, {}, 0
    previous = ""
    for row in jsonl_rows(paths["records"]):
        if (set(row) not in ({"stageSchemaVersion", "target"}, {"stageSchemaVersion", "target", "dialogueContext"})
                or row["stageSchemaVersion"] != STAGE_VERSION or type(row["target"]) is not dict
                or set(row["target"]) != {"contentUid", "primaryCategory", "sourceTextSha256"}):
            fail()
        target = row["target"]; uid = target["contentUid"]
        if type(uid) is not str or uid <= previous or uid not in prepared:
            fail("DLG_ORDER_INVALID")
        previous = uid
        original = prepared[uid]
        if (target["primaryCategory"] != original["primaryCategory"] or
                target["sourceTextSha256"] != text_hash(original["sourceText"])):
            fail("DLG_BINDING_MISMATCH")
        context = None
        if "dialogueContext" in row:
            if "sameEntityContext" in original:
                fail("BOTH_CONTEXT_FAMILIES")
            context = decode_dialogue_context(row["dialogueContext"], content_uid=uid,
                category=original["primaryCategory"], source_text=original["sourceText"])
            present += 1
        contexts[uid] = context
        material_map[uid] = "absent" if context is None else context.context_fingerprint
    summary = strict_json_loads(paths["summary"].read_bytes())
    fields = {"schemaVersion", "contract", "preparedTargets", "withContext", "absenceReasonCounts", "byCategory",
              "sourceCharsStats", "lineCardinalityStats", "inputDigests", "dialogueContextMaterialFingerprint", "summaryFingerprint"}
    if type(summary) is not dict or set(summary) != fields:
        fail("CONTEXT_CONTRACT_MISMATCH")
    expected_contract = {"structuralPolicy": POLICY_VERSION, "ordering": ORDERING_VERSION, "budget": BUDGET_VERSION,
                         "adapter": ADAPTER_VERSION, "builder": BUILDER_VERSION}
    if canonical_bytes(summary["contract"]) != canonical_bytes(expected_contract):
        fail("CONTEXT_CONTRACT_MISMATCH")
    for key in ("preparedTargets", "withContext"):
        if type(summary[key]) is not int:
            fail("CONTEXT_CONTRACT_MISMATCH")
    digests = summary["inputDigests"]
    if type(digests) is not dict or set(digests) != {"source", "dialogue", "node", "occurrence", "edge", "classification"}:
        fail("CONTEXT_CONTRACT_MISMATCH")
    for seal in digests.values():
        digest(seal)
    reasons = summary["absenceReasonCounts"]
    if (type(reasons) is not dict or any(type(v) is not int or v < 0 for v in reasons.values())
            or sum(reasons.values()) != len(contexts) - present):
        fail("CONTEXT_CONTRACT_MISMATCH")
    categories, costs, lines = defaultdict(Counter), [], []
    for uid, context in contexts.items():
        category = prepared[uid]["primaryCategory"]
        categories[category]["targets"] += 1
        categories[category]["present" if context else "absent"] += 1
        if context:
            costs.append(context.source_codepoints)
            lines.append(sum(len(g.source_variants) for g in context.possible_predecessors + context.possible_successors))
    def stats(values):
        values = sorted(values)
        return {"mean":sum(values)/len(values),"p95":values[math.ceil(.95*len(values))-1],"max":values[-1]} if values else {"mean":0,"p95":0,"max":0}
    if (canonical_bytes(summary["byCategory"]) != canonical_bytes({c:{k:v[k] for k in ("targets","present","absent")} for c,v in categories.items()})
            or canonical_bytes(summary["sourceCharsStats"]) != canonical_bytes(stats(costs))
            or canonical_bytes(summary["lineCardinalityStats"]) != canonical_bytes(stats(lines))):
        fail("CONTEXT_CONTRACT_MISMATCH")
    if (type(summary) is not dict or summary.get("schemaVersion") != SUMMARY_VERSION
            or set(contexts) != set(prepared) or summary.get("preparedTargets") != len(contexts)
            or summary.get("withContext") != present or summary.get("dialogueContextMaterialFingerprint") != fingerprint(material_map)
            or summary.get("summaryFingerprint") != manifest["summary"]["fingerprint"]
            or fingerprint({k:v for k,v in summary.items() if k != "summaryFingerprint"}) != summary.get("summaryFingerprint")
            or summary.get("inputDigests", {}).get("classification") != fingerprint({uid:row["primaryCategory"] for uid,row in prepared.items()})
            or set(summary.get("absenceReasonCounts", {})) - set(ABSENCE_REASONS)):
        fail("CONTEXT_CONTRACT_MISMATCH")
    # Recheck source envelope file seals after the read, including the marker.
    for key, path in paths.items():
        if sha256_file(path) != manifest[key]["sha256"]:
            fail("CONTEXT_CONTRACT_MISMATCH")
    if sha256_file(marker_path) != marker_seal:
        fail("CONTEXT_CONTRACT_MISMATCH")
    return MappingProxyType(contexts)
