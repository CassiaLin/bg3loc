from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from bg3loc.e2e.config import ResolvedProjectConfig
from bg3loc.io import read_json, write_json
from bg3loc.schema import SchemaStore


STAGES = [
    "config", "scan", "extract", "evidence", "package", "translate",
    "structural-review", "reconcile", "language-qa", "validate",
    "rebuild", "install-dry-run", "install",
]


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def state_path(config: ResolvedProjectConfig) -> Path:
    return Path(config.resolved["workspace"]["root"]) / "e2e" / "workflow-state.json"


def new_state(config: ResolvedProjectConfig) -> dict[str, Any]:
    profile = str(config.effective["workflow"]["evidenceProfile"])
    strategy = str(config.effective["workflow"]["translationStrategy"])
    stages = {
        stage: {
            "status": "not-started",
            "artifact": None,
            "sha256": None,
            "fingerprint": None,
            "message": None,
        }
        for stage in STAGES
    }
    stages["config"]["status"] = "completed"
    stages["config"]["artifact"] = str(config.source_path)
    stages["config"]["sha256"] = config.sha256
    stages["scan"]["status"] = "ready"
    result = {
        "schemaVersion": "1.0",
        "projectConfig": str(config.source_path),
        "projectConfigSha256": config.sha256,
        "evidenceProfile": profile,
        "translationStrategy": strategy,
        "currentStage": "scan",
        "stages": stages,
        "bindings": {
            "scanManifestSha256": None,
            "extractManifestSha256": None,
            "translationPackageSha256": None,
            "reviewIntegrationSha256": None,
            "validationManifestSha256": None,
            "validationAcceptedSha256": None,
            "rebuildManifestSha256": None,
            "qaRuleSets": [],
        },
        "artifacts": {},
    }
    SchemaStore().validate("e2e-workflow-state.schema.json", result)
    return result


def load_state(path: Path) -> dict[str, Any]:
    state = read_json(path)
    SchemaStore().validate("e2e-workflow-state.schema.json", state)
    return state


def write_state(path: Path, state: dict[str, Any]) -> None:
    SchemaStore().validate("e2e-workflow-state.schema.json", state)
    write_json(path, state)


def fingerprint_data(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def invalidate_from(state: dict[str, Any], stage: str, message: str | None = None) -> None:
    if stage not in STAGES:
        raise ValueError(f"Unknown workflow stage: {stage}")
    start = STAGES.index(stage)
    for name in STAGES[start:]:
        item = state["stages"][name]
        item["status"] = "invalidated"
        item["artifact"] = None
        item["sha256"] = None
        item["fingerprint"] = None
        item["message"] = message if name == stage else None
    state["currentStage"] = stage


def artifact_binding_valid(stage: dict[str, Any]) -> bool:
    raw = stage.get("artifact")
    expected = stage.get("sha256")
    if not raw or not expected:
        return False
    path = Path(str(raw))
    return path.is_file() and sha256_file(path) == expected


def stage_reusable(state: dict[str, Any], stage: str, fingerprint: str) -> bool:
    item = state["stages"][stage]
    return (
        item.get("status") == "completed"
        and item.get("fingerprint") == fingerprint
        and artifact_binding_valid(item)
    )
