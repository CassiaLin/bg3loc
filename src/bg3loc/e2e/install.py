from __future__ import annotations

from pathlib import Path
from typing import Any

from bg3loc.e2e.config import ResolvedProjectConfig
from bg3loc.e2e.package import sha256_file
from bg3loc.e2e.state import fingerprint_data, load_state, stage_reusable, state_path, write_state
from bg3loc.installer import InstallFailure, InstallRequest, run_install
from bg3loc.io import write_json


class WorkflowInstallError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def run_workflow_install(
    config: ResolvedProjectConfig,
    *,
    apply: bool,
) -> dict[str, Any]:
    state_file = state_path(config)
    if not state_file.is_file():
        raise WorkflowInstallError("Workflow state not found")
    state = load_state(state_file)
    if state["projectConfigSha256"] != config.sha256:
        raise WorkflowInstallError("Workflow state project binding does not match current config")
    if state["stages"]["rebuild"]["status"] != "completed":
        raise WorkflowInstallError("Workflow rebuild has not completed")

    rebuild_path = Path(str(state["artifacts"].get("rebuildManifest") or ""))
    scan_path = Path(str(state["artifacts"].get("scanManifest") or ""))
    if not rebuild_path.is_file() or not scan_path.is_file():
        raise WorkflowInstallError("Rebuild or scan manifest is missing")
    if sha256_file(rebuild_path) != state["bindings"].get("rebuildManifestSha256"):
        raise WorkflowInstallError("Rebuild manifest binding is stale")

    workspace = Path(config.resolved["workspace"]["root"]) / "e2e"
    game_dir_raw = config.resolved["game"].get("installDir")
    game_dir = Path(str(game_dir_raw)) if game_dir_raw else None
    backups = workspace / "backups"

    dry_run_fingerprint = fingerprint_data({
        "rebuildManifestSha256": state["bindings"]["rebuildManifestSha256"],
        "scanManifestSha256": state["bindings"].get("scanManifestSha256"),
    })

    if not apply and stage_reusable(state, "install-dry-run", dry_run_fingerprint):
        import json
        artifact = Path(str(state["stages"]["install-dry-run"]["artifact"]))
        return json.loads(artifact.read_text(encoding="utf-8-sig"))

    if apply and state["stages"]["install-dry-run"]["status"] != "completed":
        raise WorkflowInstallError("Real install requires a successful workflow install dry-run first")
    if apply and state["stages"]["install-dry-run"].get("fingerprint") != dry_run_fingerprint:
        raise WorkflowInstallError("Install dry-run is stale; rerun workflow install without --apply")
    if apply and state["stages"]["install"]["status"] == "completed":
        raise WorkflowInstallError("This workflow state already records a completed real install")

    stage = "install" if apply else "install-dry-run"
    state["stages"][stage]["status"] = "running"
    state["currentStage"] = stage
    write_state(state_file, state)

    try:
        result = run_install(InstallRequest(
            rebuild_manifest=rebuild_path,
            scan_manifest=scan_path,
            game_dir=game_dir,
            backup_dir=backups,
            dry_run=not apply,
        ))
    except InstallFailure as exc:
        state["stages"][stage]["status"] = "failed"
        state["stages"][stage]["message"] = f"[{exc.key}] {exc.message}"
        write_state(state_file, state)
        raise WorkflowInstallError(f"[{exc.key}] {exc.message}") from exc

    if not apply:
        evidence_path = workspace / "install-dry-run.json"
        write_json(evidence_path, result)
        state["stages"]["install-dry-run"].update({
            "status": "completed",
            "artifact": str(evidence_path),
            "sha256": sha256_file(evidence_path),
            "fingerprint": dry_run_fingerprint,
            "message": None,
        })
        state["artifacts"]["installDryRun"] = str(evidence_path)
        state["stages"]["install"]["status"] = "ready"
        state["currentStage"] = "install"
    else:
        manifest_path_raw = result.get("manifestPath")
        artifact = Path(str(manifest_path_raw)) if manifest_path_raw else None
        install_fingerprint = fingerprint_data({
            "dryRunFingerprint": dry_run_fingerprint,
            "dryRunArtifactSha256": state["stages"]["install-dry-run"].get("sha256"),
        })
        state["stages"]["install"].update({
            "status": "completed",
            "artifact": str(artifact) if artifact else None,
            "sha256": sha256_file(artifact) if artifact and artifact.is_file() else None,
            "fingerprint": install_fingerprint,
            "message": None,
        })
        state["artifacts"]["installManifest"] = str(artifact) if artifact else None
        state["currentStage"] = "complete"
    write_state(state_file, state)
    return result
