from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from bg3loc.ruleset_io import load_ruleset


SUPPORTED_PRODUCTION_MANIFEST_SCHEMAS = frozenset({"1.0", "1.1"})


@dataclass(frozen=True, slots=True)
class ProductionWorkspaceBinding:
    workspace: Path
    manifest_path: Path
    manifest: dict[str, Any]
    batch_plan: Path
    database: Path
    ruleset: Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


def _framed_update(digest: Any, *values: str) -> None:
    for value in values:
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)


def batch_materials_fingerprint(batch_plan: Path) -> str:
    plan = _load_json(batch_plan)
    batches = plan.get("batches")
    if not isinstance(batches, list):
        raise RuntimeError("batch plan batches must be a list")

    batch_ids: list[str] = []
    seen: set[str] = set()
    for batch in batches:
        if not isinstance(batch, dict):
            raise RuntimeError("batch plan contains a non-object batch")
        batch_id = str(batch.get("batchId", "")).strip()
        if not batch_id:
            raise RuntimeError("batch plan contains a batch without batchId")
        if batch_id in seen:
            raise RuntimeError(f"duplicate batchId in batch plan: {batch_id}")
        seen.add(batch_id)
        batch_ids.append(batch_id)

    digest = hashlib.sha256()
    for batch_id in sorted(batch_ids):
        material = batch_plan.parent / "materials" / f"{batch_id}.jsonl"
        if not material.is_file():
            raise RuntimeError(f"batch material not found: {material}")
        _framed_update(digest, batch_id, sha256_file(material))
    return digest.hexdigest()


def execution_inventory_fingerprint(database: Path) -> str:
    if not database.is_file():
        raise RuntimeError(f"execution database not found: {database}")
    uri = database.resolve().as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            rows = conn.execute(
                """
                SELECT content_uid, batch_id, input_hash
                FROM content_state
                ORDER BY content_uid
                """
            )
            digest = hashlib.sha256()
            count = 0
            for content_uid, batch_id, input_hash in rows:
                _framed_update(
                    digest,
                    str(content_uid),
                    str(batch_id),
                    str(input_hash),
                )
                count += 1
    except sqlite3.Error as exc:
        raise RuntimeError(f"invalid execution database: {exc}") from exc
    _framed_update(digest, str(count))
    return digest.hexdigest()


def _workspace_file(raw: object, *, workspace: Path, label: str) -> Path:
    value = str(raw or "").strip()
    if not value:
        raise RuntimeError(f"production manifest missing {label} path")
    root = workspace.resolve()
    path = Path(value)
    candidate = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not candidate.is_relative_to(root):
        raise RuntimeError(f"{label} is outside production workspace: {value}")
    if not candidate.is_file():
        raise RuntimeError(f"{label} not found: {value}")
    return candidate


def verify_production_workspace(workspace: Path) -> ProductionWorkspaceBinding:
    root = workspace.resolve()
    if not root.is_dir():
        raise RuntimeError(f"production workspace not found: {workspace}")
    manifest_path = root / "production-manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"production manifest not found: {manifest_path}")
    manifest = _load_json(manifest_path)
    schema_version = str(manifest.get("schemaVersion", ""))
    if schema_version not in SUPPORTED_PRODUCTION_MANIFEST_SCHEMAS:
        supported = ", ".join(sorted(SUPPORTED_PRODUCTION_MANIFEST_SCHEMAS))
        raise RuntimeError(
            "unsupported production manifest schemaVersion: "
            f"{schema_version or '<missing>'}; supported: {supported}"
        )

    batching = manifest.get("batching")
    execution = manifest.get("execution")
    inputs = manifest.get("inputs")
    if not isinstance(batching, dict):
        raise RuntimeError("production manifest missing batching section")
    if not isinstance(execution, dict):
        raise RuntimeError("production manifest missing execution section")
    if not isinstance(inputs, dict):
        raise RuntimeError("production manifest missing inputs section")
    ruleset_entry = inputs.get("ruleset")
    if not isinstance(ruleset_entry, dict):
        raise RuntimeError("production manifest missing ruleset input")

    batch_plan = _workspace_file(
        batching.get("batchPlan"), workspace=root, label="batch plan"
    )
    database = _workspace_file(
        execution.get("database"), workspace=root, label="execution database"
    )
    ruleset_path = _workspace_file(
        ruleset_entry.get("path"), workspace=root, label="ruleset"
    )

    expected_plan_sha = str(batching.get("batchPlanSha256", ""))
    if not expected_plan_sha or sha256_file(batch_plan) != expected_plan_sha:
        raise RuntimeError("production manifest batch plan SHA256 integrity mismatch")
    expected_materials = str(batching.get("batchMaterialsFingerprint", ""))
    if (
        not expected_materials
        or batch_materials_fingerprint(batch_plan) != expected_materials
    ):
        raise RuntimeError("production batch material integrity mismatch")

    plan = _load_json(batch_plan)
    plan_fingerprint = str(plan.get("batchPlanFingerprint", ""))
    manifest_fingerprint = str(batching.get("batchPlanFingerprint", ""))
    if not plan_fingerprint or plan_fingerprint != manifest_fingerprint:
        raise RuntimeError("production manifest batch fingerprint does not match batch plan")

    ruleset = load_ruleset(ruleset_path)
    actual_ruleset_fingerprint = ruleset.fingerprint()
    if actual_ruleset_fingerprint != str(ruleset_entry.get("fingerprint", "")):
        raise RuntimeError("production manifest ruleset fingerprint does not match ruleset")
    expected_ruleset_sha = str(ruleset_entry.get("sha256", ""))
    if not expected_ruleset_sha or sha256_file(ruleset_path) != expected_ruleset_sha:
        raise RuntimeError("production manifest ruleset SHA256 does not match ruleset")

    source_locale = str(manifest.get("sourceLocale", ""))
    target_locale = str(manifest.get("targetLocale", ""))
    if not source_locale or not target_locale:
        raise RuntimeError("production manifest missing source/target locale")
    if ruleset.source_locale.casefold() != source_locale.casefold():
        raise RuntimeError("production manifest source locale does not match ruleset")
    if ruleset.target_locale.casefold() != target_locale.casefold():
        raise RuntimeError("production manifest target locale does not match ruleset")

    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        metadata = {
            str(key): str(value)
            for key, value in conn.execute("SELECT key, value FROM metadata")
        }
    if metadata.get("batchPlanFingerprint", "") != manifest_fingerprint:
        raise RuntimeError("execution database batch fingerprint does not match production manifest")
    if metadata.get("rulesetFingerprint", "") != actual_ruleset_fingerprint:
        raise RuntimeError("execution database ruleset fingerprint does not match ruleset")
    if metadata.get("sourceLocale", "").casefold() != ruleset.source_locale.casefold():
        raise RuntimeError("execution database source locale does not match ruleset")
    if metadata.get("targetLocale", "").casefold() != ruleset.target_locale.casefold():
        raise RuntimeError("execution database target locale does not match ruleset")

    expected_inventory = str(execution.get("inventoryFingerprint", ""))
    if (
        not expected_inventory
        or execution_inventory_fingerprint(database) != expected_inventory
    ):
        raise RuntimeError("production execution inventory integrity mismatch")

    return ProductionWorkspaceBinding(
        workspace=root,
        manifest_path=manifest_path,
        manifest=manifest,
        batch_plan=batch_plan,
        database=database,
        ruleset=ruleset_path,
    )
