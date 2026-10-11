from __future__ import annotations

from pathlib import Path
from typing import Any
import uuid

from bg3loc.e2e.config import ResolvedProjectConfig
from bg3loc.e2e.package import sha256_file
from bg3loc.io import read_json, write_json
from bg3loc.e2e.state import fingerprint_data, load_state, stage_reusable, state_path, write_state
from bg3loc.rebuilder import RebuildFailure, RebuildRequest, run_rebuild


class WorkflowRebuildError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def run_workflow_rebuild(config: ResolvedProjectConfig) -> dict[str, Any]:
    from bg3loc.e2e.baseline import validated_baseline
    from bg3loc.e2e.eligibility import current_eligibility, revoke_downstream, is_basic
    if not state_path(config).is_file():
        raise WorkflowRebuildError('Workflow state not found')
    state = load_state(state_path(config))
    try:
        with validated_baseline(config, state) as baseline:
            with current_eligibility(config, state) as eligibility:
                return _run_workflow_rebuild(config, state, baseline, eligibility)
    except ValueError as exc:
        if is_basic(config):
            revoke_downstream(state, 'rebuild', 'Rebuild eligibility failed')
        state['stages']['rebuild']['status']='failed'
        state['stages']['rebuild']['message']=str(exc)
        write_state(state_path(config), state)
        raise WorkflowRebuildError(str(exc)) from exc
    except BaseException:
        if is_basic(config):
            state = load_state(state_path(config))
            revoke_downstream(state, 'rebuild', 'Rebuild failed or was interrupted')
            state['stages']['rebuild']['status'] = 'failed'
            write_state(state_path(config), state)
        raise


def _run_workflow_rebuild(config, state, baseline, eligibility=None) -> dict[str, Any]:
    state_file = state_path(config)
    if not state_file.is_file():
        raise WorkflowRebuildError("Workflow state not found")
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
        if eligibility is not None:
            from bg3loc.e2e.eligibility import rebuild_binding
            rebuild_binding(state, eligibility.validation)
        manifest_path = Path(str(state["stages"]["rebuild"]["artifact"]))
        import json
        return json.loads(manifest_path.read_text(encoding="utf-8-sig"))

    output = Path(config.resolved["workspace"]["root"]) / "e2e" / "rebuild"
    output_root = output
    if eligibility is not None:
        from bg3loc.source_packages import no_link
        from bg3loc.e2e.eligibility import revoke_downstream
        output_root.mkdir(parents=True, exist_ok=True)
        no_link(output_root)
        for directory in ('history', 'failed'):
            child = output_root / directory
            child.mkdir(exist_ok=True)
            no_link(child)
        output = output_root / ('pending-' + uuid.uuid4().hex)
        revoke_downstream(state, 'install-dry-run', 'New rebuild is in progress')
    state["stages"]["rebuild"]["status"] = "running"
    state["currentStage"] = "rebuild"
    write_state(state_file, state)
    try:
        manifest = run_rebuild(RebuildRequest(
            validate_manifest=validate_path,
            extract_manifest=extract_path if baseline is None else baseline.private_extract,
            container="auto",
            backend="auto",
            output=output,
        ))
        if baseline is not None:
            baseline.check()
            baseline.restore_rebuild_provenance(manifest)
            write_json(output / 'rebuild-manifest.json', manifest)
        if eligibility is not None:
            eligibility.check()
            final = output_root / 'history' / output.name.removeprefix('pending-')
            manifest = _relocate_paths(manifest, output, final)
            write_json(output / 'rebuild-manifest.json', manifest)
            _move_owned_output(output, final, output_root)
            output = final
    except RebuildFailure as exc:
        if eligibility is not None and output.exists():
            _move_owned_output(output, output_root / 'failed' / output.name.removeprefix('pending-'), output_root)
        state["stages"]["rebuild"]["status"] = "failed"
        state["stages"]["rebuild"]["message"] = f"[{exc.key}] {exc.message}"
        write_state(state_file, state)
        raise WorkflowRebuildError(f"[{exc.key}] {exc.message}") from exc
    except BaseException:
        if eligibility is not None and output.exists() and output.parent == output_root:
            _move_owned_output(output, output_root / 'failed' / output.name.removeprefix('pending-'), output_root)
        raise

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


def _relocate_paths(value, before, after):
    if isinstance(value, dict):
        return {key: _relocate_paths(item, before, after) for key, item in value.items()}
    if isinstance(value, list):
        return [_relocate_paths(item, before, after) for item in value]
    if isinstance(value, str):
        path = Path(value)
        if path.is_absolute() and path.is_relative_to(before):
            return str(after / path.relative_to(before))
    return value


def _move_owned_output(source, destination, root):
    from bg3loc.source_packages import no_link
    no_link(source)
    no_link(destination.parent)
    if not source.resolve().is_relative_to(root.resolve()) or not destination.resolve().is_relative_to(root.resolve()):
        raise ValueError('Rebuild publication must remain inside its owned output root')
    if destination.exists():
        raise ValueError('Historical rebuild output already exists; refusing overwrite')
    source.rename(destination)
