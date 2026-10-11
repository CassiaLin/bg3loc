"""Frozen 1.3 contract foundations, for offline Stage 2 validation only.

Passing these checks does NOT authorize execution. Stage 3 send/review gates
and Stage 4 portable asset semantics remain mandatory and unimplemented.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
import math
from pathlib import Path
import re
import sqlite3

from jsonschema import Draft202012Validator, ValidationError, validators

from bg3loc.dialogue_context import (
    DialogueBudgetContract, DialogueContext, SCHEMA_VERSION, POLICY_VERSION,
    ORDERING_VERSION, canonical_bytes, dialogue_context_from_material, digest,
    fail, fingerprint, strict_json_loads,
)
from bg3loc.dialogue_materialization import ADAPTER_VERSION, BUILDER_VERSION, SUMMARY_VERSION, ABSENCE_REASONS
from bg3loc.dialogue_prompt import (
    DIALOGUE_PROMPT_VERSION, DIALOGUE_SAFETY_VERSION, SEMANTIC_REVIEW_VERSION,
    SEMANTIC_REVIEW_FINGERPRINT, dialogue_prompt_policy_fingerprint,
)
from bg3loc.schema import SchemaStore

MANIFEST_VERSION = "1.3"
CONTRACT_VERSION = "production-context-contract/2"
INPUT_IDENTITY_VERSION = "translation-input/3"


def dialogue_identity_descriptor(context: DialogueContext) -> dict:
    return {"schemaVersion": context.schema_version, "policyVersion": context.policy_version,
            "contextFingerprint": context.context_fingerprint, "orderingVersion": context.ordering_version,
            "budgetContract": context.budget_contract.to_dict(), "promptRendererVersion": DIALOGUE_PROMPT_VERSION,
            "promptSafetyVersion": DIALOGUE_SAFETY_VERSION,
            "promptPolicyFingerprint": dialogue_prompt_policy_fingerprint(),
            "semanticReviewPolicyVersion": SEMANTIC_REVIEW_VERSION,
            "semanticReviewPolicyFingerprint": SEMANTIC_REVIEW_FINGERPRINT}


def execution_context_contract_v2(dialogue_material_fingerprint: str, *,
                                  same_entity_material_fingerprint: str | None = None) -> dict:
    from bg3loc.translation_identity import execution_context_contract
    digest(dialogue_material_fingerprint)
    if same_entity_material_fingerprint is not None:
        digest(same_entity_material_fingerprint)
    descriptor = {"inputIdentityVersion": INPUT_IDENTITY_VERSION, "schemaVersion": SCHEMA_VERSION,
                  "policyVersion": POLICY_VERSION, "orderingVersion": ORDERING_VERSION,
                  "budgetContract": DialogueBudgetContract().to_dict(), "promptRendererVersion": DIALOGUE_PROMPT_VERSION,
                  "promptSafetyVersion": DIALOGUE_SAFETY_VERSION,
                  "promptPolicyFingerprint": dialogue_prompt_policy_fingerprint(),
                  "semanticReviewPolicyVersion": SEMANTIC_REVIEW_VERSION,
                  "semanticReviewPolicyFingerprint": SEMANTIC_REVIEW_FINGERPRINT,
                  "dialogueContextMaterialFingerprint": dialogue_material_fingerprint,
                  "adapterVersion": ADAPTER_VERSION, "builderVersion": BUILDER_VERSION}
    result = {"schemaVersion": CONTRACT_VERSION, "families": {
        "sameEntity": None if same_entity_material_fingerprint is None else execution_context_contract(same_entity_material_fingerprint),
        "dialogue": descriptor}}
    return {**result, "contextContractFingerprint": fingerprint(result)}


def validate_context_contract_v2(value: object, dialogue_material_fingerprint: str,
                                 same_entity_material_fingerprint: str | None = None) -> None:
    # Canonical comparison rejects booleans masquerading as ints, unknown keys
    # and wrong local policies, including the unchanged B1-02 nested contract.
    expected = execution_context_contract_v2(dialogue_material_fingerprint,
                        same_entity_material_fingerprint=same_entity_material_fingerprint)
    if canonical_bytes(value) != canonical_bytes(expected):
        fail("CONTEXT_CONTRACT_MISMATCH")


def _strict_const(validator, expected, instance, schema):
    if type(expected) is not type(instance) or expected != instance:
        yield ValidationError("contract constant mismatch")


_StrictValidator = validators.extend(Draft202012Validator, {"const": _strict_const},
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine("integer", lambda _, v: type(v) is int))

_FROZEN_SCHEMA_FINGERPRINTS = {
    "production-manifest-v1.3.schema.json": "c386a3e2e2b749cd6081c4668f33fe89729aadf51d3b1ef06b0cb435e8547084",
    "production-finalize-assets-v1.schema.json": "6c802f7d0eba1b05affddd7293200c7ac09b11177274cb8da7c738507cf6528b",
}


def _frozen_schema(name: str) -> dict:
    schema = SchemaStore().load(name)
    if fingerprint(schema) != _FROZEN_SCHEMA_FINGERPRINTS[name]:
        fail("CONTEXT_CONTRACT_MISMATCH")
    return schema


def validate_manifest_1_3(value: object) -> dict:
    """Strict frozen shape + cross-field bindings, no upstream resource reads."""
    value = strict_json_loads(canonical_bytes(value))
    try:
        _StrictValidator(_frozen_schema("production-manifest-v1.3.schema.json")).validate(value)
    except ValidationError:
        fail("CONTEXT_CONTRACT_MISMATCH")
    same = value.get("sameEntityContext")
    dialogue = value["dialogueContext"]
    validate_context_contract_v2(value["execution"]["contextContract"], dialogue["dialogueContextMaterialFingerprint"],
        None if same is None else same["sameEntityContextMaterialFingerprint"])
    inputs = value["inputs"]
    binding = {"sourceLocale": value["sourceLocale"], "sourceNormalizedSha256": inputs["source"]["sha256"],
               "originExtractManifestSha256": inputs["extractManifest"]["sha256"],
               "dialogueEvidenceFileSha256s": {k: v["sha256"] for k, v in inputs["dialogueEvidence"].items()}}
    if fingerprint(binding) != value["corpus"]["sourceEvidenceBindingFingerprint"]:
        fail("CONTEXT_CONTRACT_MISMATCH")
    expected_digests = {"source": inputs["source"]["semanticFingerprint"],
                       **{k: v["semanticFingerprint"] for k, v in inputs["dialogueEvidence"].items()}}
    if any(dialogue["inputDigests"][k] != v for k, v in expected_digests.items()):
        fail("CONTEXT_CONTRACT_MISMATCH")
    classification = value["classification"]
    if (classification["resolvedPath"] is None) != (classification["resolvedSha256"] is None):
        fail("CONTEXT_CONTRACT_MISMATCH")
    if (value["execution"]["batchPlanFingerprint"] != value["batching"]["batchPlanFingerprint"]
            or value["execution"]["rulesetFingerprint"] != inputs["ruleset"]["fingerprint"]):
        fail("CONTEXT_CONTRACT_MISMATCH")
    return value


def contained_file(workspace: Path, relative: object) -> Path:
    """Manifest-owned file paths only; no external/cwd/basename fallback."""
    if type(relative) is not str or not relative or any(ord(c) < 32 for c in relative) or any(c in relative for c in "\\:"):
        fail("CONTEXT_CONTRACT_MISMATCH")
    parts = relative.split("/")
    if any(not part or part in {".", ".."} or part.endswith((".", " ")) or
           re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", part.split(".")[0]) for part in parts):
        fail("CONTEXT_CONTRACT_MISMATCH")
    root = workspace.resolve()
    candidate = root.joinpath(*parts)
    for parent in (root, *candidate.parents, candidate):
        if parent == root or parent.is_relative_to(root):
            try:
                attributes = getattr(parent.stat(), "st_file_attributes", 0)
            except OSError:
                fail("CONTEXT_CONTRACT_MISMATCH")
            if parent.is_symlink() or attributes & 0x400:
                fail("CONTEXT_CONTRACT_MISMATCH")
    if not candidate.resolve().is_relative_to(root) or not candidate.is_file():
        fail("CONTEXT_CONTRACT_MISMATCH")
    return candidate


def guard_material_family(row: dict, manifest_version: str | None) -> None:
    if "sameEntityContext" in row and "dialogueContext" in row:
        fail("BOTH_CONTEXT_FAMILIES")
    if "dialogueContext" in row and manifest_version != MANIFEST_VERSION:
        fail("CONTEXT_WORKSPACE_REQUIRED" if manifest_version is None else "CONTEXT_CONTRACT_MISMATCH")


def material_workspace_version(batch_plan: Path) -> str | None:
    root = batch_plan.resolve().parent.parent
    path = root / "production-manifest.json"
    version = None
    if path.is_file():
        manifest = strict_json_loads(path.read_bytes())
        if type(manifest) is not dict:
            fail("CONTEXT_CONTRACT_MISMATCH")
        version = manifest.get("schemaVersion")
        if version not in {"1.0", "1.1", "1.2", MANIFEST_VERSION}:
            fail("CONTEXT_CONTRACT_MISMATCH")
        execution = manifest.get("execution")
        contract = execution.get("contextContract") if type(execution) is dict else None
        contract_version = contract.get("schemaVersion") if type(contract) is dict else None
        declares_namespace = type(contract) is dict and ("families" in contract or
            str(contract_version).startswith("production-context-contract/"))
        if version != MANIFEST_VERSION and ("dialogueContext" in manifest or "finalizeAssets" in manifest or declares_namespace):
            fail("CONTEXT_CONTRACT_MISMATCH")
    if version != MANIFEST_VERSION and (root / "dialogue-context-materialization-summary.json").exists():
        fail("CONTEXT_WORKSPACE_REQUIRED" if version is None else "CONTEXT_CONTRACT_MISMATCH")
    if version != MANIFEST_VERSION:
        # The default prepared DB is also a declaration, including a withContext=0
        # workspace after manifest/summary stripping. Explicit worker DB paths
        # are additionally guarded at their entry point; hashes never infer mode.
        database = root / "execution.sqlite3"
        if database.is_file():
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='metadata'").fetchone():
                    reject_dialogue_execution(dict(conn.execute("SELECT key,value FROM metadata")))
    return version


def reject_dialogue_execution(metadata: dict | None = None) -> None:
    """Stage 2 has no approved Stage 3 send gate. No config flag can enable it."""
    if metadata is None or metadata.get("schemaVersion") == MANIFEST_VERSION or metadata.get(
            "executionContextContractVersion") == CONTRACT_VERSION or "dialogueContextMaterialFingerprint" in metadata:
        fail("CONTEXT_CONTRACT_MISMATCH")
    if metadata.get("schemaVersion", "1.2") not in {"1.0", "1.1", "1.2"}:
        fail("CONTEXT_CONTRACT_MISMATCH")


@dataclass(frozen=True, slots=True)
class Stage2WorkspaceValidation:
    workspace: Path
    batch_plan: Path
    database: Path
    ruleset: Path
    item_count: int
    context_count: int
    context_contract_fingerprint: str


def validate_stage2_workspace(workspace: Path, *, _connection=None, _item_sink=None, _expected_manifest=None) -> Stage2WorkspaceValidation:
    """OFFLINE only. Validates material/identity/DB/descriptor foundations.

    D7 payload semantics and Stage 3 provenance/QA/review are deliberately not
    certified here. verify_production_workspace and workers reject 1.3.
    """
    from bg3loc.production_context import context_from_material, verify_context_materialization
    from bg3loc.production_workspace import sha256_file, batch_materials_fingerprint, execution_inventory_fingerprint
    from bg3loc.ruleset_io import load_ruleset
    from bg3loc.translation_identity import TranslationInputParameters, translation_input_hash

    root = workspace.resolve()
    manifest = validate_manifest_1_3(strict_json_loads((root / "production-manifest.json").read_bytes()))
    if _expected_manifest is not None and canonical_bytes(manifest)!=canonical_bytes(_expected_manifest):
        fail("CONTEXT_CONTRACT_MISMATCH")
    batch = manifest["batching"]
    execution = manifest["execution"]
    plan_path = contained_file(root, batch["batchPlan"])
    db = contained_file(root, execution["database"])
    rules_entry = manifest["inputs"]["ruleset"]
    rules_path = contained_file(root, rules_entry["path"])
    if sha256_file(plan_path) != batch["batchPlanSha256"] or sha256_file(rules_path) != rules_entry["sha256"]:
        fail("CONTEXT_CONTRACT_MISMATCH")
    rules = load_ruleset(rules_path)
    if (rules.fingerprint() != rules_entry["fingerprint"] or rules.version != rules_entry["version"]
            or rules.source_locale != manifest["sourceLocale"] or rules.target_locale != manifest["targetLocale"]):
        fail("CONTEXT_CONTRACT_MISMATCH")
    plan = strict_json_loads(plan_path.read_bytes())
    if (type(plan) is not dict or type(plan.get("batches")) is not list
            or plan.get("batchPlanFingerprint") != batch["batchPlanFingerprint"]
            or len(plan["batches"]) != batch["batchCount"]):
        fail("CONTEXT_CONTRACT_MISMATCH")
    expected, material, categories, costs, lines, inventory = {}, {}, defaultdict(Counter), [], [], {}
    batch_ids = set()
    parameters = TranslationInputParameters(rules.version, rules.fingerprint(), rules.source_locale, rules.target_locale)
    for entry in plan["batches"]:
        batch_id = entry.get("batchId")
        if type(batch_id) is not str or not re.fullmatch(r"[A-Za-z0-9_-]+", batch_id) or batch_id in batch_ids:
            fail("CONTEXT_CONTRACT_MISMATCH")
        batch_ids.add(batch_id)
        rows = []
        path = contained_file(root, str(plan_path.parent.relative_to(root)).replace("\\", "/") + f"/materials/{batch_id}.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines():
            row = strict_json_loads(line)
            if type(row) is not dict:
                fail()
            guard_material_family(row, MANIFEST_VERSION)
            base = {"contentUid", "sourceText", "translationText", "primaryCategory", "batchId", "canonicalGroupKey", "contextGroupKeys"}
            if not base <= set(row) or set(row) - base - {"dialogueContext", "sameEntityContext"}:
                fail()
            if (any(type(row[k]) is not str for k in base - {"contextGroupKeys"})
                    or type(row["contextGroupKeys"]) is not list or any(type(v) is not str for v in row["contextGroupKeys"])):
                fail()
            uid, category = row["contentUid"], row["primaryCategory"]
            if not uid or uid in expected or row["batchId"] != batch_id or category != entry.get("primaryCategory"):
                fail("CONTEXT_CONTRACT_MISMATCH")
            dialogue = dialogue_context_from_material(row, source_locale=rules.source_locale)
            same = context_from_material(row)
            if same is not None and "sameEntityContext" not in manifest:
                fail("CONTEXT_CONTRACT_MISMATCH")
            expected[uid] = (batch_id, translation_input_hash(content_uid=uid, source_text=row["sourceText"], category=category,
                protected_syntax=None, parameters=parameters, context=same, dialogue_context=dialogue))
            if _item_sink is not None:_item_sink(row,dialogue,same,expected[uid][1])
            inventory[uid] = category
            material[uid] = "absent" if dialogue is None else dialogue.context_fingerprint
            categories[category]["targets"] += 1
            categories[category]["present" if dialogue is not None else "absent"] += 1
            if dialogue is not None:
                costs.append(dialogue.source_codepoints)
                lines.append(sum(len(g.source_variants) for g in dialogue.possible_predecessors + dialogue.possible_successors))
            rows.append(uid)
        if type(entry.get("recordCount")) is not int or len(rows) != entry["recordCount"] or sorted(rows) != sorted(entry.get("contentUids", [])):
            fail("CONTEXT_CONTRACT_MISMATCH")
    if (len(expected) != execution["seededContentUidCount"] or len(expected) != batch["classifiedInputCount"]
            or batch_materials_fingerprint(plan_path) != batch["batchMaterialsFingerprint"]):
        fail("CONTEXT_CONTRACT_MISMATCH")
    dlg = manifest["dialogueContext"]
    summary_path = contained_file(root, dlg["summaryPath"])
    if sha256_file(summary_path) != dlg["summarySha256"]:
        fail("CONTEXT_CONTRACT_MISMATCH")
    summary = strict_json_loads(summary_path.read_bytes())
    required = {"schemaVersion", "contract", "preparedTargets", "withContext", "absenceReasonCounts", "byCategory",
                "sourceCharsStats", "lineCardinalityStats", "inputDigests", "dialogueContextMaterialFingerprint", "summaryFingerprint"}
    if type(summary) is not dict or set(summary) != required:
        fail("CONTEXT_CONTRACT_MISMATCH")
    contract = {"structuralPolicy": POLICY_VERSION, "ordering": ORDERING_VERSION,
                "budget": DialogueBudgetContract().version, "adapter": ADAPTER_VERSION, "builder": BUILDER_VERSION}
    def stats(values):
        values = sorted(values)
        return {"mean": sum(values)/len(values), "p95": values[math.ceil(.95*len(values))-1], "max": values[-1]} if values else {"mean":0,"p95":0,"max":0}
    expected_fields = {"schemaVersion": SUMMARY_VERSION, "contract": contract, "preparedTargets": len(expected),
        "withContext": len(costs), "byCategory": {c: {k: v[k] for k in ("targets", "present", "absent")} for c, v in categories.items()},
        "sourceCharsStats": stats(costs), "lineCardinalityStats": stats(lines), "inputDigests": dlg["inputDigests"],
        "dialogueContextMaterialFingerprint": fingerprint(material)}
    if any(canonical_bytes(summary[k]) != canonical_bytes(v) for k, v in expected_fields.items()):
        fail("CONTEXT_CONTRACT_MISMATCH")
    reasons = summary["absenceReasonCounts"]
    if (type(reasons) is not dict or set(reasons) - set(ABSENCE_REASONS)
            or any(type(v) is not int or v < 0 for v in reasons.values())
            or sum(reasons.values()) != len(expected) - len(costs)
            or fingerprint({k:v for k,v in summary.items() if k != "summaryFingerprint"}) != summary["summaryFingerprint"]
            or summary["summaryFingerprint"] != dlg["summaryFingerprint"]
            or dlg["withContext"] != len(costs) or dlg["dialogueContextMaterialFingerprint"] != fingerprint(material)
            or dlg["inputDigests"]["classification"] != fingerprint(inventory)):
        fail("CONTEXT_CONTRACT_MISMATCH")
    c = manifest["classification"]
    if sha256_file(contained_file(root, c["automaticPath"])) != c["automaticSha256"]:
        fail("CONTEXT_CONTRACT_MISMATCH")
    automatic_statuses = Counter()
    automatic_uids = set()
    for line in contained_file(root, c["automaticPath"]).read_text(encoding="utf-8").splitlines():
        row = strict_json_loads(line)
        if row["contentUid"] in automatic_uids:
            fail("CONTEXT_CONTRACT_MISMATCH")
        automatic_uids.add(row["contentUid"])
        automatic_statuses[row.get("classificationStatus", "classified")] += 1
    if any(c["counts"].get(k, 0) != automatic_statuses[k] for k in set(c["counts"]) | set(automatic_statuses)):
        fail("CONTEXT_CONTRACT_MISMATCH")
    if c["resolvedPath"] is not None and sha256_file(contained_file(root, c["resolvedPath"])) != c["resolvedSha256"]:
        fail("CONTEXT_CONTRACT_MISMATCH")
    if c["batchInputPath"] != (c["resolvedPath"] or c["automaticPath"]):
        fail("CONTEXT_CONTRACT_MISMATCH")
    classified, seen_classified, excluded, unresolved = {}, set(), 0, 0
    for line in contained_file(root, c["batchInputPath"]).read_text(encoding="utf-8").splitlines():
        row = strict_json_loads(line)
        if row["contentUid"] in seen_classified:
            fail("CONTEXT_CONTRACT_MISMATCH")
        seen_classified.add(row["contentUid"])
        status = row.get("classificationStatus", "classified")
        excluded += status == "excluded"
        unresolved += status != "excluded" and (status != "classified" or row["primaryCategory"] == "other")
        if row.get("classificationStatus", "classified") == "classified" and row["primaryCategory"] != "other":
            classified[row["contentUid"]] = row["primaryCategory"]
    if classified != inventory or excluded != batch["excludedCount"] or unresolved != batch["unresolvedCount"]:
        fail("CONTEXT_CONTRACT_MISMATCH")
    assets = manifest["finalizeAssets"]
    asset_path = contained_file(root, assets["path"])
    bundle = strict_json_loads(asset_path.read_bytes())
    try:
        _StrictValidator(_frozen_schema("production-finalize-assets-v1.schema.json")).validate(bundle)
    except ValidationError:
        fail("CONTEXT_CONTRACT_MISMATCH")
    if (sha256_file(asset_path) != assets["sha256"] or type(bundle) is not dict
            or bundle.get("schemaVersion") != "production-finalize-assets/1"
            or bundle.get("assetFingerprint") != assets["assetFingerprint"]
            or bundle["sourceLocale"] != manifest["sourceLocale"] or bundle["targetLocale"] != manifest["targetLocale"]
            or bundle["originExtractManifestSha256"] != manifest["inputs"]["extractManifest"]["sha256"]
            or fingerprint({k:v for k,v in bundle.items() if k != "assetFingerprint"}) != assets["assetFingerprint"]):
        fail("CONTEXT_CONTRACT_MISMATCH")
    # Only descriptor/file integrity is checked here; NO portable payload reader.
    if "sameEntityContext" in manifest:
        verify_context_materialization(plan_path, root, {**manifest, "schemaVersion": "1.2"})
    from contextlib import nullcontext
    with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)) if _connection is None else nullcontext(_connection) as conn:
        metadata = dict(conn.execute("SELECT key,value FROM metadata"))
        actual = {uid:(b,h) for uid,b,h in conn.execute("SELECT content_uid,batch_id,input_hash FROM content_state")}
    required_metadata = {"schemaVersion": MANIFEST_VERSION, "executionContextContractVersion": CONTRACT_VERSION,
        "executionContextContractFingerprint": execution["contextContract"]["contextContractFingerprint"],
        "dialogueContextMaterialFingerprint": fingerprint(material), "batchPlanFingerprint": batch["batchPlanFingerprint"],
        "rulesetFingerprint": rules.fingerprint(), "promptVersion": rules.version,
        "sourceLocale": rules.source_locale, "targetLocale": rules.target_locale}
    if (any(metadata.get(k) != v for k,v in required_metadata.items()) or actual != expected
            or execution_inventory_fingerprint(db, _connection=_connection) != execution["inventoryFingerprint"]):
        fail("CONTEXT_CONTRACT_MISMATCH")
    return Stage2WorkspaceValidation(root, plan_path, db, rules_path, len(expected), len(costs),
                                     execution["contextContract"]["contextContractFingerprint"])
