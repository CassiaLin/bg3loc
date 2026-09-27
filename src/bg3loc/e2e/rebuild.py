from __future__ import annotations

from pathlib import Path
from typing import Any

from bg3loc.e2e.config import ResolvedProjectConfig
from bg3loc.e2e.package import sha256_file
from bg3loc.io import read_json
from bg3loc.e2e.state import fingerprint_data, load_state, stage_reusable, state_path, write_state
from bg3loc.rebuilder import RebuildFailure, RebuildRequest, run_rebuild


class WorkflowRebuildError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def run_workflow_rebuild(config: ResolvedProjectConfig) -> dict[str, Any]:
    state_file = state_path(config)
    if not state_file.is_file():
        raise WorkflowRebuildError("Workflow state not found")
    state = load_state(state_file)
    if state["projectConfigSha256"] != config.sha256:
        raise WorkflowRebuildError("Workflow state project binding does not match current config")
    if state["stages"]["validate"]["status"] != "completed":
        raise WorkflowRebuildError("Workflow validation has not passed")

    validate_path = Path(str(state["artifacts"].get("validateManifest") or ""))
    extract_path = Path(str(state["artifacts"].get("extractManifest") or ""))
    if not validate_path.is_file() or not extract_path.is_file():
        raise WorkflowRebuildError("Validated or extracted workflow artifact is missing")
    if sha256_file(validate_path) != state["bindings"].get("validationManifestSha256"):
        raise WorkflowRebuildError("Validation manifest binding is stale")
    validate_manifest = read_json(validate_path)
    accepted_path = Path(str(validate_manifest.get("accepted", {}).get("path", "")))
    expected_accepted_sha = state["bindings"].get("validationAcceptedSha256")
    if (
        not accepted_path.is_file()
        or not expected_accepted_sha
        or sha256_file(accepted_path) != expected_accepted_sha
    ):
        raise WorkflowRebuildError("Accepted validation target binding is stale")

    rebuild_fingerprint = fingerprint_data({
        "validationManifestSha256": state["bindings"]["validationManifestSha256"],
        "validationAcceptedSha256": state["bindings"]["validationAcceptedSha256"],
        "extractManifestSha256": state["bindings"].get("extractManifestSha256"),
    })
    if stage_reusable(state, "rebuild", rebuild_fingerprint):
        manifest_path = Path(str(state["stages"]["rebuild"]["artifact"]))
        import json
        return json.loads(manifest_path.read_text(encoding="utf-8-sig"))

    output = Path(config.resolved["workspace"]["root"]) / "e2e" / "rebuild"
    state["stages"]["rebuild"]["status"] = "running"
    state["currentStage"] = "rebuild"
    write_state(state_file, state)
    try:
        manifest = run_rebuild(RebuildRequest(
            validate_manifest=validate_path,
            extract_manifest=extract_path,
            container="auto",
            backend="auto",
            output=output,
        ))
    except RebuildFailure as exc:
        state["stages"]["rebuild"]["status"] = "failed"
        state["stages"]["rebuild"]["message"] = f"[{exc.key}] {exc.message}"
        write_state(state_file, state)
        raise WorkflowRebuildError(f"[{exc.key}] {exc.message}") from exc

    manifest_path = output / "rebuild-manifest.json"
    digest = sha256_file(manifest_path)
    state["stages"]["rebuild"].update({
        "status": "completed",
        "artifact": str(manifest_path),
        "sha256": digest,
        "fingerprint": rebuild_fingerprint,
        "message": None,
    })
    state["bindings"]["rebuildManifestSha256"] = digest
    state["artifacts"]["rebuildManifest"] = str(manifest_path)
    state["stages"]["install-dry-run"]["status"] = "ready"
    state["currentStage"] = "install-dry-run"
    write_state(state_file, state)
    return manifest
