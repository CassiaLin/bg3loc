"""Explicit Stage 1 opt-in: local-only, NON-EXECUTABLE prepare artifacts.

No production manifest, batch plan, execution database or prompt is emitted.
The staging envelope deliberately cannot be consumed as execution material.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
import tempfile

from bg3loc.dialogue_context import canonical_bytes, digest, fail, strict_json_loads, string
from bg3loc.dialogue_materialization import DialogueEvidenceAdapter, jsonl_rows, materialize_inventory
from bg3loc.production_context import context_from_material

STAGE_VERSION = "dialogue-stage1-prepare/1"


def _file_seal(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_prepared_inventory(batch_plan: Path, sources) -> tuple[dict[str, str], tuple[Path, ...]]:
    """Read existing plan, verifying inventory and exact English target text.

    Batch IDs locate contained material files, never arbitrary recorded paths.
    Staging does not adopt the plan's execution identity or publish it again.
    """
    plan = strict_json_loads(batch_plan.read_bytes())
    if type(plan) is not dict or type(plan.get("batches")) is not list:
        fail()
    digest(plan.get("batchPlanFingerprint"))
    root = batch_plan.resolve().parent
    result, paths, batch_ids = {}, [], set()
    for batch in plan["batches"]:
        if type(batch) is not dict:
            fail()
        batch_id = batch.get("batchId")
        if type(batch_id) is not str or not re.fullmatch(r"[a-zA-Z0-9_-]+", batch_id) or batch_id in batch_ids:
            fail()
        batch_ids.add(batch_id)
        category = batch.get("primaryCategory")
        string(category)
        count, uids = batch.get("recordCount"), batch.get("contentUids")
        if type(count) is not int or count < 1 or type(uids) is not list:
            fail()
        if any(type(uid) is not str for uid in uids) or len(uids) != count or len(set(uids)) != count:
            fail()
        material = root / "materials" / f"{batch_id}.jsonl"
        if not material.resolve().is_relative_to(root) or material.is_symlink():
            fail()
        paths.append(material)
        found = set()
        for row in jsonl_rows(material):
            if "dialogueContext" in row and "sameEntityContext" in row:
                fail("BOTH_CONTEXT_FAMILIES")
            if "dialogueContext" in row:
                fail("CONTEXT_CONTRACT_MISMATCH")
            if "sameEntityContext" in row:
                # Reuse B1-02's prepare-side validator. Never silently drop a
                # malformed-present input or create a competing family.
                try:
                    context_from_material(row)
                except (ValueError, RuntimeError, TypeError, KeyError):
                    fail("DLG_SHAPE_INVALID")
            uid = row.get("contentUid")
            string(uid)
            if (uid in result or row.get("batchId") != batch_id or row.get("primaryCategory") != category
                    or uid not in sources or sources[uid] != row.get("sourceText")):
                fail("DLG_BINDING_MISMATCH")
            found.add(uid)
            result[uid] = category
        if found != set(uids):
            fail("DLG_BINDING_MISMATCH")
    if not result:
        fail()
    return result, tuple(paths)


def prepare_dialogue_stage(*, evidence_dir: Path, source_snapshot: Path,
                           batch_plan: Path, output_dir: Path, enabled: bool = False) -> dict:
    """Validate everything before atomic publication; existing output is refused.

    Artifacts contain proprietary source/proofs and must stay in local-only
    storage. This Stage 1 API never calls production prepare or run_init.
    """
    if enabled is not True:
        fail("CONTEXT_CONTRACT_MISMATCH")
    if output_dir.exists():
        fail("CONTEXT_CONTRACT_MISMATCH")
    inputs = (source_snapshot, batch_plan, evidence_dir / "dialogue-summary.json",
              *(evidence_dir / f"dialogue-{family}.jsonl" for family in (
                  "dialogue", "node", "occurrence", "edge", "targetEvidence")))
    before = {path: _file_seal(path) for path in inputs}
    adapter = DialogueEvidenceAdapter.from_workspace(evidence_dir, source_snapshot)
    inventory, materials = load_prepared_inventory(batch_plan, adapter.sources)
    material_seals = {path: _file_seal(path) for path in materials}
    inventory_again, _ = load_prepared_inventory(batch_plan, adapter.sources)
    if inventory_again != inventory:
        fail("DLG_BINDING_MISMATCH")
    results, summary = materialize_inventory(adapter, inventory)
    if any(_file_seal(path) != seal for path, seal in {**before, **material_seals}.items()):
        fail("DLG_FINGERPRINT_MISMATCH")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".dialogue-stage1-", dir=output_dir.parent) as temporary:
        staging = Path(temporary) / "artifact"
        staging.mkdir()
        records = staging / "stage1-target-contexts.jsonl"
        with records.open("wb") as handle:
            for uid, result in results.items():
                row = {"stageSchemaVersion": STAGE_VERSION,
                       "target": {"contentUid": uid, "primaryCategory": inventory[uid],
                                  "sourceTextSha256": sha256(adapter.sources[uid].encode("utf-8")).hexdigest()}}
                if result.context is not None:
                    row["dialogueContext"] = result.context.to_dict()
                handle.write(canonical_bytes(row) + b"\n")
        summary_path = staging / "dialogue-context-materialization-summary.json"
        summary_path.write_bytes(canonical_bytes(summary) + b"\n")
        manifest = {"stageSchemaVersion": STAGE_VERSION, "status": "NOT_EXECUTABLE",
                    "localOnly": True, "productionActivation": False,
                    "records": {"path": records.name, "sha256": _file_seal(records)},
                    "summary": {"path": summary_path.name, "sha256": _file_seal(summary_path),
                                "fingerprint": summary["summaryFingerprint"]}}
        (staging / "stage1-manifest.json").write_bytes(canonical_bytes(manifest) + b"\n")
        (staging / "README.txt").write_text(
            "B1-03 Stage 1: LOCAL ONLY / NOT EXECUTABLE\n"
            "Staged target envelopes are not batch materials. No production manifest,\n"
            "batch plan, execution DB, renderer, HD identity, QA gate or D7 assets.\n"
            "Do not pass these artifacts to run_init, workers or providers.\n",
            encoding="utf-8")
        staging.rename(output_dir)
    return summary
