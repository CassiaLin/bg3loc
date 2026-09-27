from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from bg3loc.commands.research import (
    ResearchMapRequest,
    ResearchScanRequest,
    run_research_map_request,
    run_research_scan_request,
)
from bg3loc.e2e.config import ResolvedProjectConfig, resolved_structural_reviews
from bg3loc.e2e.package import (
    build_neighbor_context,
    prepare_translation_package,
    research_evidence_sidecars,
    sha256_file,
)
from bg3loc.e2e.state import (
    artifact_binding_valid,
    fingerprint_data,
    invalidate_from,
    load_state,
    new_state,
    stage_reusable,
    state_path,
    write_state,
)
from bg3loc.extractor import ExtractFailure, ExtractRequest, run_extract
from bg3loc.io import read_json, write_json
from bg3loc.scanner import ScanFailure, ScanRequest, build_manifest
from bg3loc.schema import SchemaStore


class WorkflowPrepareError(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message


def run_prepare(config: ResolvedProjectConfig) -> dict[str, Any]:
    workspace = Path(config.resolved["workspace"]["root"]) / "e2e"
    state_file = state_path(config)
    if state_file.is_file():
        state = load_state(state_file)
        if state["projectConfigSha256"] != config.sha256:
            state["projectConfigSha256"] = config.sha256
            state["evidenceProfile"] = str(config.effective["workflow"]["evidenceProfile"])
            state["translationStrategy"] = str(config.effective["workflow"]["translationStrategy"])
            state["stages"]["config"].update({
                "status": "completed",
                "artifact": str(config.source_path),
                "sha256": config.sha256,
                "fingerprint": config.sha256,
                "message": None,
            })
            write_state(state_file, state)
    else:
        state = new_state(config)
        state["stages"]["config"]["fingerprint"] = config.sha256
        write_state(state_file, state)

    scan_dir = workspace / "scan"
    extract_dir = workspace / "extract"
    evidence_dir = workspace / "evidence"
    research_dir = workspace / "research"
    package_dir = workspace / "package"

    try:
        game_dir_raw = config.resolved["game"].get("installDir")
        scan_request = ScanRequest(
            game_dir=Path(game_dir_raw) if game_dir_raw else None,
            platform="auto",
            backend="auto",
        )
        scan_manifest = build_manifest(scan_request)
        SchemaStore().validate("scan.schema.json", scan_manifest)
        scan_fingerprint = fingerprint_data(scan_manifest)
        if stage_reusable(state, "scan", scan_fingerprint):
            scan_path = Path(str(state["stages"]["scan"]["artifact"]))
        else:
            if state["stages"]["scan"].get("status") == "completed":
                invalidate_from(state, "extract", "Game/scan evidence changed")
            _stage_running(state, "scan")
            write_state(state_file, state)
            scan_path = scan_dir / "scan-manifest.json"
            write_json(scan_path, scan_manifest)
            _stage_completed(state, "scan", scan_path, fingerprint=scan_fingerprint)
        state["bindings"]["scanManifestSha256"] = sha256_file(scan_path)
        state["artifacts"]["scanManifest"] = str(scan_path)
        state["stages"]["extract"]["status"] = (
            state["stages"]["extract"]["status"]
            if state["stages"]["extract"]["status"] == "completed"
            else "ready"
        )
        state["currentStage"] = "extract"
        write_state(state_file, state)
    except (ScanFailure, OSError, ValueError) as exc:
        _stage_failed(state, "scan", str(exc))
        write_state(state_file, state)
        raise WorkflowPrepareError("scan", str(exc)) from exc

    try:
        locales = config.effective["locales"]
        extract_fingerprint = fingerprint_data({
            "scan": scan_fingerprint,
            "source": locales["source"],
            "target": locales["target"],
            "references": locales.get("references", []),
        })
        if stage_reusable(state, "extract", extract_fingerprint):
            extract_path = Path(str(state["stages"]["extract"]["artifact"]))
        else:
            if state["stages"]["extract"].get("status") == "completed":
                invalidate_from(state, "evidence", "Extraction inputs changed")
            _stage_running(state, "extract")
            write_state(state_file, state)
            extract_request = ExtractRequest(
                scan_manifest=scan_path,
                source=str(locales["source"]),
                target=str(locales["target"]),
                references=tuple(str(item) for item in locales.get("references", [])),
                output=extract_dir,
            )
            run_extract(extract_request)
            extract_path = extract_dir / "extract-manifest.json"
            _stage_completed(state, "extract", extract_path, fingerprint=extract_fingerprint)
        state["bindings"]["extractManifestSha256"] = sha256_file(extract_path)
        state["artifacts"]["extractManifest"] = str(extract_path)
        state["stages"]["evidence"]["status"] = (
            state["stages"]["evidence"]["status"]
            if state["stages"]["evidence"]["status"] == "completed"
            else "ready"
        )
        state["currentStage"] = "evidence"
        write_state(state_file, state)
    except (ExtractFailure, OSError, ValueError) as exc:
        _stage_failed(state, "extract", str(exc))
        write_state(state_file, state)
        raise WorkflowPrepareError("extract", str(exc)) from exc

    profile = str(config.effective["workflow"]["evidenceProfile"])
    strategy = str(config.effective["workflow"]["translationStrategy"])
    scope_raw = config.effective["scope"].get("contentUids")
    scope_content_uids = (
        None
        if scope_raw is None
        else {str(item) for item in scope_raw}
    )

    structural_reviews = resolved_structural_reviews(config)
    previous_structural = state["bindings"].get("structuralReviews")
    if previous_structural is not None and previous_structural != structural_reviews:
        invalidate_from(state, "structural-review", "Structural review selection changed")
    state["bindings"]["structuralReviews"] = structural_reviews

    glossary_raw = config.resolved["inputs"].get("glossary")
    glossary = Path(str(glossary_raw)) if glossary_raw else None
    if glossary is not None and not glossary.is_file():
        raise WorkflowPrepareError("package", f"Glossary not found: {glossary}")
    glossary_sha = sha256_file(glossary) if glossary is not None else None

    qa_bindings: list[dict[str, str]] = []
    for item in config.resolved["qa"].get("ruleSets", []):
        path = Path(str(item["path"]))
        if not path.is_file():
            raise WorkflowPrepareError("package", f"QA rule set not found: {path}")
        qa_bindings.append({"id": str(item["id"]), "sha256": sha256_file(path)})
    previous_qa = state["bindings"].get("qaRuleSets", [])
    if previous_qa != qa_bindings:
        invalidate_from(state, "language-qa", "QA rule-set configuration or contents changed")
    state["bindings"]["qaRuleSets"] = qa_bindings

    evidence_files: dict[str, Path] = {}
    research_summary: Path | None = None
    research_mappings: Path | None = None
    evidence_manifest_path = evidence_dir / "evidence-manifest.json"
    evidence_fingerprint = fingerprint_data({
        "scan": scan_fingerprint,
        "extract": state["bindings"]["extractManifestSha256"],
        "profile": profile,
        "strategy": strategy,
    })

    try:
        if stage_reusable(state, "evidence", evidence_fingerprint):
            (
                evidence_files,
                research_summary,
                research_mappings,
            ) = _load_evidence_checkpoint(
                evidence_manifest_path,
                evidence_fingerprint,
            )
        else:
            if state["stages"]["evidence"].get("status") == "completed":
                invalidate_from(state, "package", "Evidence inputs changed")
            _stage_running(state, "evidence")
            write_state(state_file, state)

            if profile == "context":
                context_path = evidence_dir / "context.jsonl"
                evidence_files["context"] = build_neighbor_context(extract_path, context_path)
            elif profile == "full":
                game_root = Path(str(scan_manifest["game"]["installPath"]))
                research_scan = research_dir / "research-scan-manifest.json"
                scan_code = run_research_scan_request(ResearchScanRequest(
                    game_dir=game_root,
                    output=research_scan,
                    source=str(locales["source"]),
                    target=str(locales["target"]),
                    references=tuple(str(item) for item in locales.get("references", [])),
                ))
                if scan_code != 0:
                    raise WorkflowPrepareError(
                        "evidence",
                        f"Research scan failed with exit code {scan_code}",
                    )
                map_code = run_research_map_request(ResearchMapRequest(
                    scan=research_scan,
                    output_dir=research_dir,
                    source=str(locales["source"]),
                    target=str(locales["target"]),
                    references=tuple(str(item) for item in locales.get("references", [])),
                ))
                if map_code != 0:
                    raise WorkflowPrepareError(
                        "evidence",
                        f"Research map failed with exit code {map_code}",
                    )
                research_summary = research_dir / "research-summary.json"
                research_mappings = research_dir / "research-mappings.jsonl"
                evidence_files = research_evidence_sidecars(
                    research_dir,
                    evidence_dir,
                    blind_first=strategy == "blind-first",
                )

            _write_evidence_checkpoint(
                evidence_manifest_path,
                evidence_fingerprint,
                profile,
                evidence_files,
                research_summary,
                research_mappings,
            )
            _stage_completed(
                state,
                "evidence",
                evidence_manifest_path,
                fingerprint=evidence_fingerprint,
            )

        state["artifacts"]["evidenceManifest"] = str(evidence_manifest_path)
        state["artifacts"]["researchSummary"] = (
            str(research_summary) if research_summary else None
        )
        state["artifacts"]["researchMappings"] = (
            str(research_mappings) if research_mappings else None
        )
        state["stages"]["package"]["status"] = (
            state["stages"]["package"]["status"]
            if state["stages"]["package"]["status"] == "completed"
            else "ready"
        )
        state["currentStage"] = "package"
        write_state(state_file, state)
    except WorkflowPrepareError:
        _stage_failed(state, "evidence", "Research evidence preparation failed")
        write_state(state_file, state)
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        _stage_failed(state, "evidence", str(exc))
        write_state(state_file, state)
        raise WorkflowPrepareError("evidence", str(exc)) from exc

    material = config.effective["material"]
    package_fingerprint = fingerprint_data({
        "extract": state["bindings"]["extractManifestSha256"],
        "evidenceManifestSha256": sha256_file(evidence_manifest_path),
        "profile": profile,
        "strategy": strategy,
        "material": {
            "format": material["format"],
            "maxRowsPerFile": material["maxRowsPerFile"],
        },
        "scopeContentUids": (
            None
            if scope_content_uids is None
            else sorted(scope_content_uids)
        ),
        "glossarySha256": glossary_sha,
    })
    if stage_reusable(state, "package", package_fingerprint):
        package_manifest = Path(str(state["stages"]["package"]["artifact"]))
        returns_dir = workspace / "returns"
        _initialize_returns(package_manifest, package_manifest.parent, returns_dir)
        state["artifacts"]["translationReturns"] = str(returns_dir)
        state["stages"]["translate"]["artifact"] = str(returns_dir)
        state["stages"]["translate"]["status"] = (
            state["stages"]["translate"]["status"]
            if state["stages"]["translate"]["status"] != "invalidated"
            else "ready"
        )
        if (
            state["stages"]["translate"]["status"] != "completed"
            or state["currentStage"] in {"scan", "extract", "evidence", "package"}
        ):
            state["currentStage"] = "translate"
        write_state(state_file, state)
        return state

    try:
        _stage_running(state, "package")
        write_state(state_file, state)
        prepare_translation_package(
            extract_manifest=extract_path,
            project_config_sha256=config.sha256,
            evidence_profile=profile,
            translation_strategy=strategy,
            material_format=str(material["format"]),
            max_rows=int(material["maxRowsPerFile"]),
            output_dir=package_dir,
            evidence_files=evidence_files,
            glossary=glossary,
            research_summary=research_summary,
            research_mappings=research_mappings,
            scope_content_uids=scope_content_uids,
        )
        package_manifest = package_dir / "translation-package-manifest.json"
        package_sha = sha256_file(package_manifest)
        returns_dir = workspace / "returns"
        _initialize_returns(package_manifest, package_dir, returns_dir)
        _stage_completed(
            state,
            "package",
            package_manifest,
            fingerprint=package_fingerprint,
        )
        state["bindings"]["translationPackageSha256"] = package_sha
        state["artifacts"]["translationPackage"] = str(package_manifest)
        state["artifacts"]["translationReturns"] = str(returns_dir)
        state["stages"]["translate"]["status"] = "ready"
        state["stages"]["translate"]["artifact"] = str(returns_dir)
        state["currentStage"] = "translate"
        write_state(state_file, state)
        return state
    except (OSError, ValueError) as exc:
        _stage_failed(state, "package", str(exc))
        write_state(state_file, state)
        raise WorkflowPrepareError("package", str(exc)) from exc


def _stage_running(state: dict[str, Any], stage: str) -> None:
    state["stages"][stage]["status"] = "running"
    state["stages"][stage]["message"] = None
    state["currentStage"] = stage


def _stage_completed(
    state: dict[str, Any],
    stage: str,
    artifact: Path,
    *,
    fingerprint: str | None = None,
) -> None:
    state["stages"][stage]["status"] = "completed"
    state["stages"][stage]["artifact"] = str(artifact)
    state["stages"][stage]["sha256"] = sha256_file(artifact) if artifact.is_file() else None
    state["stages"][stage]["fingerprint"] = fingerprint
    state["stages"][stage]["message"] = None


def _stage_failed(state: dict[str, Any], stage: str, message: str) -> None:
    state["stages"][stage]["status"] = "failed"
    state["stages"][stage]["message"] = message
    state["currentStage"] = stage



def _write_evidence_checkpoint(
    path: Path,
    input_fingerprint: str,
    profile: str,
    evidence_files: dict[str, Path],
    research_summary: Path | None,
    research_mappings: Path | None,
) -> None:
    artifacts: list[dict[str, str]] = []
    for evidence_type, artifact_path in sorted(evidence_files.items()):
        artifacts.append({
            "role": "sidecar",
            "evidenceType": evidence_type,
            "path": str(artifact_path),
            "sha256": sha256_file(artifact_path),
        })
    if research_summary is not None:
        artifacts.append({
            "role": "research-summary",
            "path": str(research_summary),
            "sha256": sha256_file(research_summary),
        })
    if research_mappings is not None:
        artifacts.append({
            "role": "research-mappings",
            "path": str(research_mappings),
            "sha256": sha256_file(research_mappings),
        })
    write_json(path, {
        "schemaVersion": "1.0",
        "inputFingerprint": input_fingerprint,
        "profile": profile,
        "artifacts": artifacts,
    })


def _load_evidence_checkpoint(
    path: Path,
    expected_fingerprint: str,
) -> tuple[dict[str, Path], Path | None, Path | None]:
    if not path.is_file():
        raise FileNotFoundError(path)
    manifest = read_json(path)
    if manifest.get("inputFingerprint") != expected_fingerprint:
        raise ValueError("Evidence checkpoint fingerprint mismatch")

    evidence_files: dict[str, Path] = {}
    research_summary: Path | None = None
    research_mappings: Path | None = None
    for item in manifest.get("artifacts", []):
        artifact_path = Path(str(item.get("path", "")))
        expected_sha = str(item.get("sha256", ""))
        if not artifact_path.is_file() or sha256_file(artifact_path) != expected_sha:
            raise ValueError(f"Evidence checkpoint artifact is stale: {artifact_path}")
        role = str(item.get("role", ""))
        if role == "sidecar":
            evidence_type = str(item.get("evidenceType", ""))
            if not evidence_type:
                raise ValueError("Evidence sidecar is missing evidenceType")
            evidence_files[evidence_type] = artifact_path
        elif role == "research-summary":
            research_summary = artifact_path
        elif role == "research-mappings":
            research_mappings = artifact_path
    return evidence_files, research_summary, research_mappings

def _initialize_returns(package_manifest: Path, package_root: Path, returns_dir: Path) -> None:
    manifest = read_json(package_manifest)
    materials = list(manifest.get("delivery", {}).get("materials", []))
    returns_dir.mkdir(parents=True, exist_ok=True)
    binding_path = returns_dir / "returns-manifest.json"
    package_sha = sha256_file(package_manifest)

    if binding_path.is_file():
        existing = read_json(binding_path)
        if existing.get("sourceTranslationPackageSha256") == package_sha:
            return

        tracked = existing.get("materials", [])
        safe_to_refresh = bool(tracked) and all(
            isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("sha256"), str)
            and (returns_dir / item["name"]).is_file()
            and sha256_file(returns_dir / item["name"]) == item["sha256"]
            for item in tracked
        )
        if not safe_to_refresh:
            raise FileExistsError(
                "Existing return material belongs to an older translation package "
                "and may contain user edits; archive or move the returns directory "
                "before preparing the new package."
            )
        for item in tracked:
            (returns_dir / item["name"]).unlink()
        binding_path.unlink()

    copied: list[dict[str, str]] = []
    for item in materials:
        raw = Path(str(item["path"]))
        source = (package_root / raw).resolve(strict=False)
        try:
            source.relative_to(package_root.resolve(strict=False))
        except ValueError as exc:
            raise ValueError(f"Delivery material path escapes package root: {raw}") from exc
        if not source.is_file():
            raise FileNotFoundError(f"Delivery material missing: {source}")
        destination = returns_dir / source.name
        if destination.exists():
            raise FileExistsError(
                f"Unbound return material already exists; refusing to overwrite: {destination}"
            )
        shutil.copy2(source, destination)
        copied.append({
            "name": destination.name,
            "sha256": sha256_file(destination),
        })

    write_json(binding_path, {
        "schemaVersion": "1.0",
        "sourceTranslationPackageSha256": package_sha,
        "materials": copied,
    })
