from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from bg3loc.backends import ArchiveBackend
from bg3loc.final_merge_bridge import FinalMergeBridgeError, build_final_merge_bridge
from bg3loc.io import read_json
from bg3loc.production_completion import (
    DISPOSITION_BLOCKED,
    DISPOSITION_MERGE_READY,
    DISPOSITION_WAITING_RETRY,
    DISPOSITION_WAITING_REVIEW,
    DISPOSITION_WAITING_TRANSLATION,
    build_production_completion_view,
)
from bg3loc.production_workspace import sha256_file, verify_production_workspace
from bg3loc.rebuilder import RebuildFailure, RebuildRequest, run_rebuild
from bg3loc.schema import SchemaStore


_BLOCKING_DISPOSITIONS = (
    DISPOSITION_WAITING_TRANSLATION,
    DISPOSITION_WAITING_RETRY,
    DISPOSITION_WAITING_REVIEW,
    DISPOSITION_BLOCKED,
)


@dataclass(frozen=True, slots=True)
class ProductionFinalizeRequest:
    workspace: Path
    output: Path
    container: str = "auto"
    backend: str = "auto"


@dataclass(frozen=True, slots=True)
class ProductionFinalizeResult:
    manifest: dict[str, Any]
    manifest_path: Path


def _require_fresh_output(output: Path) -> None:
    if output.exists() and not output.is_dir():
        raise RuntimeError(f"finalize output path is not a directory: {output}")
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(
            f"finalize output directory is not empty; use a fresh directory: {output}"
        )


def _resolve_recorded_extract(binding: Any) -> Path:
    inputs = binding.manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise RuntimeError("production manifest missing inputs section")
    entry = inputs.get("extractManifest")
    if not isinstance(entry, dict):
        raise RuntimeError("production manifest missing extract manifest input")
    raw = str(entry.get("path", "")).strip()
    expected_sha = str(entry.get("sha256", "")).strip()
    if not raw or not expected_sha:
        raise RuntimeError("production manifest has incomplete extract manifest provenance")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise RuntimeError(
            "production manifest extract path is relative and ambiguous; "
            "prepare a fresh workspace with the current BG3Loc version"
        )
    path = path.resolve()
    if not path.is_file():
        raise RuntimeError(f"recorded extract manifest not found: {path}")
    if sha256_file(path) != expected_sha:
        raise RuntimeError("recorded extract manifest SHA256 integrity mismatch")
    return path


def _require_completion_ready(completion: Any) -> None:
    blocked = {
        disposition: int(completion.counts.get(disposition, 0))
        for disposition in _BLOCKING_DISPOSITIONS
    }
    merge_ready = int(completion.counts.get(DISPOSITION_MERGE_READY, 0))
    if any(blocked.values()) or merge_ready != int(completion.total):
        details = ", ".join(
            [f"{DISPOSITION_MERGE_READY}={merge_ready}"]
            + [f"{key}={value}" for key, value in blocked.items()]
        )
        raise RuntimeError(
            f"production finalize blocked by completion gate: {details}; "
            "run 'bg3loc production report' and resolve translation, retry, review, or blocked rows"
        )


def _verify_bridge_handoff(
    *,
    bridge_manifest: dict[str, Any],
    bridge_dir: Path,
    expected_count: int,
    expected_database_sha256: str,
) -> tuple[Path, Path]:
    bridge_path = bridge_dir / "bridge-manifest.json"
    validate_path = bridge_dir / "validate-manifest.json"
    if not bridge_path.is_file() or not validate_path.is_file():
        raise RuntimeError("production bridge did not create required manifests")
    if int(bridge_manifest.get("mergeReadyCount", -1)) != expected_count:
        raise RuntimeError("production bridge merge-ready count mismatch")
    if str(bridge_manifest.get("executionDatabaseSha256", "")) != expected_database_sha256:
        raise RuntimeError("production bridge execution database snapshot mismatch")

    for key, filename, label in (
        ("acceptedTarget", "accepted-target.jsonl", "accepted target"),
        ("mergeReadyBinding", "merge-ready-binding.jsonl", "merge-ready binding"),
    ):
        entry = bridge_manifest.get(key)
        path = bridge_dir / filename
        if not isinstance(entry, dict) or not path.is_file():
            raise RuntimeError(f"production bridge missing {label} binding")
        if sha256_file(path) != str(entry.get("sha256", "")):
            raise RuntimeError(f"production bridge {label} integrity mismatch")

    validate_entry = bridge_manifest.get("validateManifest")
    if not isinstance(validate_entry, dict):
        raise RuntimeError("production bridge manifest missing validate binding")
    if sha256_file(validate_path) != str(validate_entry.get("sha256", "")):
        raise RuntimeError("production bridge validate manifest integrity mismatch")

    validate = read_json(validate_path)
    SchemaStore().validate("validate-manifest.schema.json", validate)
    summary = validate.get("summary")
    accepted = validate.get("accepted")
    rejected = validate.get("rejected")
    if (
        not bool(validate.get("strict"))
        or not isinstance(summary, dict)
        or str(summary.get("status", "")) != "pass"
        or not isinstance(accepted, dict)
        or int(accepted.get("recordCount", -1)) != expected_count
        or not isinstance(rejected, dict)
        or int(rejected.get("recordCount", -1)) != 0
    ):
        raise RuntimeError("production bridge validate handoff is not a strict pass")
    return bridge_path, validate_path


def _verified_artifacts(
    rebuild_manifest: dict[str, Any], *, output: Path
) -> list[dict[str, str]]:
    validation = rebuild_manifest.get("validation")
    if not isinstance(validation, dict) or any(
        str(validation.get(key, "")) != "pass"
        for key in (
            "semanticRoundTrip",
            "acceptedTextMatch",
            "uidSetIntegrity",
            "untouchedRecordIntegrity",
        )
    ):
        raise RuntimeError("production rebuild validation did not pass")

    artifacts = rebuild_manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise RuntimeError("production rebuild produced no artifacts")
    root = output.resolve()
    verified: list[dict[str, str]] = []
    for entry in artifacts:
        if not isinstance(entry, dict):
            raise RuntimeError("production rebuild contains an invalid artifact record")
        path = Path(str(entry.get("path", ""))).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise RuntimeError(f"production rebuild artifact is outside finalize output: {path}")
        digest = sha256_file(path)
        if digest != str(entry.get("sha256", "")):
            raise RuntimeError(f"production rebuild artifact SHA256 mismatch: {path}")
        verified.append(
            {
                "type": str(entry.get("type", "")),
                "path": path.relative_to(root).as_posix(),
                "sha256": digest,
            }
        )
    return verified


def finalize_production_workspace(
    request: ProductionFinalizeRequest,
    *,
    rebuild_backend: ArchiveBackend | None = None,
) -> ProductionFinalizeResult:
    binding = verify_production_workspace(request.workspace)
    extract_manifest = _resolve_recorded_extract(binding)
    completion = build_production_completion_view(binding.database, binding.batch_plan)
    _require_completion_ready(completion)
    execution_snapshot_sha256 = sha256_file(binding.database)
    _require_fresh_output(request.output)

    output = request.output.resolve()
    bridge_dir = output / "bridge"
    rebuild_dir = output / "rebuild"
    try:
        bridge_manifest = build_final_merge_bridge(
            db_path=binding.database,
            batch_plan_path=binding.batch_plan,
            extract_manifest_path=extract_manifest,
            output_dir=bridge_dir,
        )
    except FinalMergeBridgeError as exc:
        raise RuntimeError(f"production finalize bridge failed: {exc}") from exc

    bridge_path, validate_path = _verify_bridge_handoff(
        bridge_manifest=bridge_manifest,
        bridge_dir=bridge_dir,
        expected_count=completion.total,
        expected_database_sha256=execution_snapshot_sha256,
    )
    try:
        rebuild_manifest = run_rebuild(
            RebuildRequest(
                validate_manifest=validate_path,
                extract_manifest=extract_manifest,
                container=request.container,
                backend=request.backend,
                output=rebuild_dir,
            ),
            backend=rebuild_backend,
        )
    except RebuildFailure as exc:
        raise RuntimeError(
            f"production finalize rebuild failed: {exc.key}: {exc.message}"
        ) from exc

    rebuild_path = rebuild_dir / "rebuild-manifest.json"
    if not rebuild_path.is_file():
        raise RuntimeError("production rebuild did not create rebuild-manifest.json")
    artifacts = _verified_artifacts(rebuild_manifest, output=output)
    _verify_bridge_handoff(
        bridge_manifest=bridge_manifest,
        bridge_dir=bridge_dir,
        expected_count=completion.total,
        expected_database_sha256=execution_snapshot_sha256,
    )
    if sha256_file(binding.database) != execution_snapshot_sha256:
        raise RuntimeError("production execution database changed during finalize")

    manifest = {
        "schemaVersion": "1.0",
        "status": "pass",
        "sourceLocale": str(binding.manifest["sourceLocale"]),
        "targetLocale": str(binding.manifest["targetLocale"]),
        "productionWorkspace": {
            "manifestSha256": sha256_file(binding.manifest_path),
            "batchPlanFingerprint": str(
                binding.manifest["batching"]["batchPlanFingerprint"]
            ),
            "rulesetFingerprint": str(
                binding.manifest["inputs"]["ruleset"]["fingerprint"]
            ),
            "executionInventoryFingerprint": str(
                binding.manifest["execution"]["inventoryFingerprint"]
            ),
            "executionDatabaseSha256": execution_snapshot_sha256,
        },
        "completion": {
            "total": completion.total,
            "counts": dict(completion.counts),
            "mergeReadyCount": int(
                completion.counts.get(DISPOSITION_MERGE_READY, 0)
            ),
        },
        "bridge": {
            "manifest": bridge_path.relative_to(output).as_posix(),
            "manifestSha256": sha256_file(bridge_path),
            "validateManifest": validate_path.relative_to(output).as_posix(),
            "validateManifestSha256": sha256_file(validate_path),
        },
        "rebuild": {
            "manifest": rebuild_path.relative_to(output).as_posix(),
            "manifestSha256": sha256_file(rebuild_path),
            "containerMode": str(rebuild_manifest.get("containerMode", "")),
            "containerAction": str(rebuild_manifest.get("containerAction", "")),
            "validation": {
                key: str(rebuild_manifest["validation"][key])
                for key in (
                    "semanticRoundTrip",
                    "acceptedTextMatch",
                    "uidSetIntegrity",
                    "untouchedRecordIntegrity",
                )
            },
        },
        "artifacts": artifacts,
    }
    manifest_path = output / "production-final-manifest.json"
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(manifest_path)
    return ProductionFinalizeResult(manifest=manifest, manifest_path=manifest_path)
