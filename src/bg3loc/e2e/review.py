from __future__ import annotations

import csv
import hashlib
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from bg3loc.e2e.config import ResolvedProjectConfig, resolved_structural_reviews
from bg3loc.e2e.package import read_jsonl, sha256_file, write_jsonl
from bg3loc.e2e.state import load_state, state_path, write_state
from bg3loc.e2e.validate import run_validate
from bg3loc.io import write_json
from bg3loc.review.bark import (
    PASS1_COLUMNS as BARK_PASS1,
    PASS2_COLUMNS as BARK_PASS2,
    load_locales,
    prepare_bark_review,
    validate_bark_review,
)
from bg3loc.review.multilingual import (
    prepare_multilingual_review,
    validate_multilingual_review,
)
from bg3loc.review.quest import (
    prepare_quest_review,
    validate_quest_review,
)
from bg3loc.review.taiwan_usage import (
    REVIEW_COLUMNS as TAIWAN_COLUMNS,
    candidates_from_target,
    load_taiwan_usage_rules,
    validate_taiwan_usage_review,
)
from bg3loc.review.ui_skill import (
    prepare_ui_skill_review,
    validate_ui_skill_review,
)
from bg3loc.schema import SchemaStore


class WorkflowReviewError(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message


_STRUCTURAL: dict[str, tuple[Callable[..., dict[str, Any]], Callable[..., dict[str, Any]], str]] = {
    "bark": (prepare_bark_review, validate_bark_review, "bark-review-manifest.json"),
    "quest": (prepare_quest_review, validate_quest_review, "quest-review-manifest.json"),
    "ui-skill": (prepare_ui_skill_review, validate_ui_skill_review, "ui-skill-review-manifest.json"),
    "multilingual": (prepare_multilingual_review, validate_multilingual_review, "multilingual-review-manifest.json"),
}


def prepare_reviews(config: ResolvedProjectConfig, input_spec: str | None = None) -> dict[str, Any]:
    base_validation = run_validate(config, input_spec, review_gate=False)
    if base_validation["status"] == "fail":
        raise WorkflowReviewError("translate", "Translation material must pass base validation before review")

    state_file = state_path(config)
    state = load_state(state_file)
    workspace = Path(config.resolved["workspace"]["root"]) / "e2e"
    (workspace / "review" / "e2e-review-integration.json").unlink(missing_ok=True)
    accepted_path = workspace / "validation" / "accepted" / "normalized-target.jsonl"
    if not accepted_path.is_file():
        raise WorkflowReviewError("translate", "Accepted canonical translation snapshot is missing")

    canonical = _index_target(read_jsonl(accepted_path))
    canonical_sha = _target_snapshot_sha(canonical)
    snapshot_path = workspace / "review" / "canonical-translation-snapshot.jsonl"
    write_jsonl(snapshot_path, [
        {
            "contentUid": uid,
            "text": record["text"],
            "sha256": _text_sha256(str(record["text"])),
            "version": record.get("version"),
        }
        for uid, record in sorted(canonical.items())
    ])

    structural = resolved_structural_reviews(config)
    if structural:
        mappings_raw = state["artifacts"].get("researchMappings")
        extract_raw = state["artifacts"].get("extractManifest")
        if not mappings_raw or not extract_raw:
            raise WorkflowReviewError("structural-review", "Full research artifacts are missing")
        mappings = Path(str(mappings_raw))
        extract = Path(str(extract_raw))
        research_dir = mappings.parent

        for protocol in structural:
            review_dir = workspace / "review" / "structural" / protocol
            manifest_name = _STRUCTURAL[protocol][2]
            manifest_path = review_dir / manifest_name
            binding_path = review_dir / "e2e-review-base.json"
            if manifest_path.is_file() and not _review_base_binding_current(
                binding_path,
                canonical_sha,
            ):
                _archive_stale_review_dir(
                    workspace,
                    "structural",
                    protocol,
                    review_dir,
                    canonical_sha,
                )
            if not manifest_path.is_file():
                prepare_fn = _STRUCTURAL[protocol][0]
                if protocol == "ui-skill":
                    universe = research_dir / "ui-skill-universe.csv"
                    prepare_fn(
                        universe_path=universe,
                        extract_manifest=extract,
                        output_dir=review_dir,
                        include_pass2=True,
                    )
                else:
                    prepare_fn(
                        mappings_path=mappings,
                        extract_manifest=extract,
                        output_dir=review_dir,
                        include_pass2=True,
                    )
                _prefill_structural_surfaces(review_dir, protocol, canonical)
                write_json(binding_path, {
                    "schemaVersion": "1.0",
                    "baseTargetSha256": canonical_sha,
                })

        state["stages"]["structural-review"]["status"] = "ready"
        state["stages"]["structural-review"]["artifact"] = str(workspace / "review" / "structural")
        state["stages"]["structural-review"]["message"] = "Complete configured structural review CSVs"
        state["currentStage"] = "structural-review"
        write_state(state_file, state)
        return {
            "status": "ready",
            "stage": "structural-review",
            "path": str(workspace / "review" / "structural"),
        }

    qa = list(config.resolved["qa"].get("ruleSets", []))
    if qa:
        _prepare_qa_packages(config, canonical, workspace)
        state["stages"]["language-qa"]["status"] = "ready"
        state["stages"]["language-qa"]["artifact"] = str(workspace / "review" / "qa")
        state["stages"]["language-qa"]["message"] = "Complete configured project-language QA CSVs"
        state["currentStage"] = "language-qa"
        write_state(state_file, state)
        return {
            "status": "ready",
            "stage": "language-qa",
            "path": str(workspace / "review" / "qa"),
        }

    return {"status": "not-required", "stage": "validate", "path": None}


def integrate_reviews(config: ResolvedProjectConfig) -> dict[str, Any]:
    state_file = state_path(config)
    if not state_file.is_file():
        raise WorkflowReviewError("review", "Workflow state not found")
    state = load_state(state_file)
    workspace = Path(config.resolved["workspace"]["root"]) / "e2e"
    package_sha = str(state["bindings"].get("translationPackageSha256") or "")
    accepted_path = workspace / "validation" / "accepted" / "normalized-target.jsonl"
    if not accepted_path.is_file():
        raise WorkflowReviewError("translate", "Accepted translation snapshot is missing")

    base_records = read_jsonl(accepted_path)
    current = _index_target(base_records)
    base_target_sha = _target_snapshot_sha(current)
    structural_gates: list[dict[str, Any]] = []
    structural_results: list[dict[str, Any]] = []
    structural = resolved_structural_reviews(config)

    for protocol in structural:
        normalized, gate = _integrate_structural_protocol(config, workspace, protocol, current)
        structural_results.extend(normalized)
        structural_gates.append(gate)

    if any(item["status"] == "pending" for item in structural_gates):
        _set_review_blocked(state, state_file, "structural-review")
        return {
            "status": "blocked",
            "stage": "structural-review",
            "path": str(workspace / "review" / "structural"),
        }

    structural_reconciliation_path = workspace / "review" / "structural-reconciliation.jsonl"
    structural_target_path = workspace / "review" / "structural-target.jsonl"
    structural_reconciliation, structural_target, conflicts = _reconcile(current, structural_results)
    structural_reconciliation, structural_target, conflicts = _apply_manual_resolutions(
        workspace,
        "structural",
        structural_reconciliation,
        structural_target,
    )
    write_jsonl(structural_reconciliation_path, structural_reconciliation)
    write_jsonl(structural_target_path, structural_target)

    structural_blocking = sum(int(item["blockingCount"]) for item in structural_gates)
    if structural_blocking or conflicts:
        integration = _integration_manifest(
            package_sha=package_sha,
            base_target_sha=base_target_sha,
            structural=structural_gates,
            qa=[],
            reconciliation_path=structural_reconciliation_path,
            conflict_count=conflicts,
            final_target_path=structural_target_path,
            status="blocked",
        )
        path = workspace / "review" / "e2e-review-integration.json"
        write_json(path, integration)
        _set_review_blocked(state, state_file, "reconcile" if conflicts else "structural-review")
        return {"status": "blocked", "path": str(path), "conflictCount": conflicts}

    qa_inputs = list(config.resolved["qa"].get("ruleSets", []))
    structurally_resolved = _index_target(structural_target)
    if qa_inputs:
        qa_root = workspace / "review" / "qa"
        missing_package = any(
            not (qa_root / str(item["id"]) / "e2e-qa-manifest.json").is_file()
            for item in qa_inputs
        )
        if missing_package:
            _prepare_qa_packages(config, structurally_resolved, workspace)
            state["stages"]["structural-review"]["status"] = "completed"
            state["stages"]["reconcile"]["status"] = "completed"
            state["stages"]["language-qa"]["status"] = "ready"
            state["stages"]["language-qa"]["artifact"] = str(qa_root)
            state["stages"]["language-qa"]["message"] = "Complete configured project-language QA CSVs"
            state["currentStage"] = "language-qa"
            write_state(state_file, state)
            return {"status": "blocked", "stage": "language-qa", "path": str(qa_root)}

        qa_base = _load_qa_base(workspace, qa_inputs)
        structural_sha = _target_snapshot_sha(structurally_resolved)
        lineage = _load_qa_lineage(qa_root)
        if lineage.get("structuralBaseSha256") != structural_sha:
            _prepare_qa_packages(
                config,
                structurally_resolved,
                workspace,
                structural_base_sha=structural_sha,
            )
            state["stages"]["language-qa"]["status"] = "ready"
            state["stages"]["language-qa"]["artifact"] = str(qa_root)
            state["stages"]["language-qa"]["message"] = (
                "Canonical target changed; complete the regenerated QA round"
            )
            state["currentStage"] = "language-qa"
            write_state(state_file, state)
            return {
                "status": "blocked",
                "stage": "language-qa",
                "path": str(qa_root),
                "message": "Canonical target changed; a fresh QA round was generated",
            }
        if lineage.get("currentQaBaseSha256") != _target_snapshot_sha(qa_base):
            raise WorkflowReviewError(
                "language-qa",
                "QA lineage binding does not match the current QA base target",
            )
        qa_results: list[dict[str, Any]] = []
        qa_gates: list[dict[str, Any]] = []
        for item in qa_inputs:
            normalized, gate = _integrate_qa_instance(workspace, item, qa_base)
            qa_results.extend(normalized)
            qa_gates.append(gate)

        if any(item["status"] == "pending" for item in qa_gates):
            _set_review_blocked(state, state_file, "language-qa")
            return {
                "status": "blocked",
                "stage": "language-qa",
                "path": str(qa_root),
            }

        qa_reconciliation_path = workspace / "review" / "qa-reconciliation.jsonl"
        final_target_path = workspace / "review" / "final-normalized-target.jsonl"
        qa_reconciliation, final_target, qa_conflicts = _reconcile(qa_base, qa_results)
        qa_reconciliation, final_target, qa_conflicts = _apply_manual_resolutions(
            workspace,
            "language-qa",
            qa_reconciliation,
            final_target,
        )
        write_jsonl(qa_reconciliation_path, qa_reconciliation)
        write_jsonl(final_target_path, final_target)
        qa_blocking = sum(int(item["blockingCount"]) for item in qa_gates)
        if qa_blocking or qa_conflicts:
            integration = _integration_manifest(
                package_sha=package_sha,
                base_target_sha=base_target_sha,
                structural=structural_gates,
                qa=qa_gates,
                reconciliation_path=qa_reconciliation_path,
                conflict_count=qa_conflicts,
                final_target_path=final_target_path,
                status="blocked",
            )
            path = workspace / "review" / "e2e-review-integration.json"
            write_json(path, integration)
            _set_review_blocked(state, state_file, "reconcile" if qa_conflicts else "language-qa")
            return {"status": "blocked", "path": str(path), "conflictCount": qa_conflicts}

        qa_changed = any(
            item["Resolution"] in {
                "adopted-review-revision",
                "manual-conflict-resolution",
            }
            for item in qa_reconciliation
        )
        if qa_changed:
            revised = _index_target(final_target)
            _archive_qa_rounds(config, workspace, qa_base)
            (workspace / "review" / "e2e-review-integration.json").unlink(missing_ok=True)
            _prepare_qa_packages(
                config,
                revised,
                workspace,
                structural_base_sha=_target_snapshot_sha(structurally_resolved),
            )
            state["stages"]["language-qa"]["status"] = "ready"
            state["stages"]["language-qa"]["artifact"] = str(workspace / "review" / "qa")
            state["stages"]["language-qa"]["message"] = (
                "QA revision changed canonical text; complete the new QA round"
            )
            state["currentStage"] = "language-qa"
            write_state(state_file, state)
            return {
                "status": "blocked",
                "stage": "language-qa",
                "path": str(workspace / "review" / "qa"),
                "message": "QA revision changed canonical text; a fresh QA round was generated",
            }

        reconciliation_path = qa_reconciliation_path
    else:
        qa_gates = []
        final_target_path = workspace / "review" / "final-normalized-target.jsonl"
        write_jsonl(final_target_path, structural_target)
        reconciliation_path = structural_reconciliation_path

    integration = _integration_manifest(
        package_sha=package_sha,
        base_target_sha=base_target_sha,
        structural=structural_gates,
        qa=qa_gates,
        reconciliation_path=reconciliation_path,
        conflict_count=0,
        final_target_path=final_target_path,
        status="passed",
    )
    integration_path = workspace / "review" / "e2e-review-integration.json"
    SchemaStore().validate("e2e-review-integration.schema.json", integration)
    write_json(integration_path, integration)

    state["stages"]["structural-review"]["status"] = "completed"
    state["stages"]["reconcile"]["status"] = "completed"
    state["stages"]["language-qa"]["status"] = "completed"
    state["bindings"]["reviewIntegrationSha256"] = sha256_file(integration_path)
    state["artifacts"]["reviewIntegration"] = str(integration_path)
    state["stages"]["validate"]["status"] = "ready"
    state["currentStage"] = "validate"
    write_state(state_file, state)
    return {"status": "passed", "path": str(integration_path), "finalTarget": str(final_target_path)}



def record_manual_resolutions(
    config: ResolvedProjectConfig,
    input_path: Path,
) -> dict[str, Any]:
    state_file = state_path(config)
    if not state_file.is_file():
        raise WorkflowReviewError("reconcile", "Workflow state not found")
    state = load_state(state_file)
    workspace = Path(config.resolved["workspace"]["root"]) / "e2e"
    integration_path = workspace / "review" / "e2e-review-integration.json"
    if not integration_path.is_file():
        raise WorkflowReviewError("reconcile", "No blocked review integration exists")

    integration = json.loads(integration_path.read_text(encoding="utf-8-sig"))
    reconciliation_path = Path(str(integration.get("reconciliation", {}).get("path", "")))
    if not reconciliation_path.is_file():
        raise WorkflowReviewError("reconcile", "Blocked reconciliation artifact is missing")
    if int(integration.get("reconciliation", {}).get("conflictCount", 0)) < 1:
        raise WorkflowReviewError("reconcile", "Review integration has no unresolved text conflict")

    name = reconciliation_path.name
    if name == "structural-reconciliation.jsonl":
        phase = "structural"
    elif name == "qa-reconciliation.jsonl":
        phase = "language-qa"
    else:
        raise WorkflowReviewError(
            "reconcile",
            f"Unsupported reconciliation artifact for manual resolution: {name}",
        )

    conflicts = {
        str(item["ContentUid"]): item
        for item in read_jsonl(reconciliation_path)
        if item.get("Resolution") == "conflict"
    }
    if not conflicts:
        raise WorkflowReviewError("reconcile", "No conflict records remain")

    if not input_path.is_file():
        raise WorkflowReviewError("reconcile", f"Resolution input not found: {input_path}")
    supplied = read_jsonl(input_path)
    if not supplied:
        raise WorkflowReviewError("reconcile", "Resolution input is empty")

    output_dir = workspace / "review" / "manual-resolutions"
    output_path = output_dir / f"{phase}.jsonl"
    existing = {
        str(item["ContentUid"]): item
        for item in read_jsonl(output_path)
    } if output_path.is_file() else {}

    seen: set[str] = set()
    for raw in supplied:
        uid = str(raw.get("ContentUid", ""))
        resolved_text = raw.get("ResolvedText")
        if not uid or not isinstance(resolved_text, str):
            raise WorkflowReviewError(
                "reconcile",
                "Each manual resolution row requires ContentUid and string ResolvedText",
            )
        if uid in seen:
            raise WorkflowReviewError("reconcile", f"Duplicate manual resolution ContentUid: {uid}")
        seen.add(uid)
        conflict = conflicts.get(uid)
        if conflict is None:
            raise WorkflowReviewError(
                "reconcile",
                f"Manual resolution does not match a current conflict: {uid}",
            )
        record = {
            "ReviewStage": phase,
            "ContentUid": uid,
            "BaseTextSha256": str(conflict["BaseTextSha256"]),
            "ResolvedText": resolved_text,
            "ResolvedTextSha256": _text_sha256(resolved_text),
        }
        SchemaStore().validate("e2e-manual-review-resolution.schema.json", record)
        prior = existing.get(uid)
        if prior is not None and prior != record:
            raise WorkflowReviewError(
                "reconcile",
                f"Manual resolution already exists with different content: {uid}",
            )
        existing[uid] = record

    write_jsonl(output_path, [existing[uid] for uid in sorted(existing)])
    state["stages"]["reconcile"]["status"] = "ready"
    state["stages"]["reconcile"]["artifact"] = str(output_path)
    state["stages"]["reconcile"]["message"] = "Manual conflict resolutions recorded; rerun workflow validate"
    state["currentStage"] = "reconcile"
    write_state(state_file, state)
    return {
        "status": "recorded",
        "stage": phase,
        "path": str(output_path),
        "recordCount": len(existing),
    }


def _apply_manual_resolutions(
    workspace: Path,
    phase: str,
    reconciliation: list[dict[str, Any]],
    target_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    path = workspace / "review" / "manual-resolutions" / f"{phase}.jsonl"
    if not path.is_file():
        conflicts = sum(1 for item in reconciliation if item.get("Resolution") == "conflict")
        return reconciliation, target_rows, conflicts

    resolutions = {
        str(item["ContentUid"]): item
        for item in read_jsonl(path)
    }
    targets = {str(item["contentUid"]): item for item in target_rows}
    for item in reconciliation:
        uid = str(item["ContentUid"])
        resolution = resolutions.get(uid)
        if resolution is None:
            continue
        SchemaStore().validate("e2e-manual-review-resolution.schema.json", resolution)
        if item.get("Resolution") != "conflict":
            raise WorkflowReviewError(
                "reconcile",
                f"Manual resolution is stale because the record is no longer conflicted: {uid}",
            )
        if resolution["ReviewStage"] != phase:
            raise WorkflowReviewError("reconcile", f"Manual resolution stage mismatch: {uid}")
        if resolution["BaseTextSha256"] != item["BaseTextSha256"]:
            raise WorkflowReviewError(
                "reconcile",
                f"Manual resolution is stale because base text changed: {uid}",
            )
        resolved_text = str(resolution["ResolvedText"])
        if _text_sha256(resolved_text) != resolution["ResolvedTextSha256"]:
            raise WorkflowReviewError(
                "reconcile",
                f"Manual resolution text hash mismatch: {uid}",
            )
        item["ResolvedText"] = resolved_text
        item["ResolvedTextSha256"] = resolution["ResolvedTextSha256"]
        item["Resolution"] = "manual-conflict-resolution"
        SchemaStore().validate("e2e-review-reconciliation.schema.json", item)
        if uid not in targets:
            raise WorkflowReviewError("reconcile", f"Conflict target row missing: {uid}")
        targets[uid]["text"] = resolved_text

    conflicts = sum(1 for item in reconciliation if item.get("Resolution") == "conflict")
    return reconciliation, target_rows, conflicts

def _integrate_structural_protocol(
    config: ResolvedProjectConfig,
    workspace: Path,
    protocol: str,
    canonical: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    review_dir = workspace / "review" / "structural" / protocol
    manifest_path = review_dir / _STRUCTURAL[protocol][2]
    if not manifest_path.is_file():
        return [], _pending_gate(protocol, protocol)

    binding_path = review_dir / "e2e-review-base.json"
    if not _review_base_binding_current(
        binding_path,
        _target_snapshot_sha(canonical),
    ):
        raise WorkflowReviewError(
            "structural-review",
            f"{protocol} review package is stale because canonical translated text changed",
        )

    pass1 = review_dir / f"{protocol}-review-pass1.csv"
    pass2 = review_dir / f"{protocol}-review-pass2.csv"
    pass1_complete = _decisions_complete(pass1, "ReviewerDecision")
    pass2_complete = _decisions_complete(pass2, "FinalDecision") if pass2.is_file() else False
    strategy = str(config.effective["workflow"]["translationStrategy"])

    if strategy == "blind-first" and pass2_complete and not pass1_complete:
        return [], _pending_gate(protocol, protocol)
    if pass2_complete:
        surface, decision_field, text_field, phase = pass2, "FinalDecision", "FinalText", "pass2"
    elif pass1_complete:
        surface, decision_field, text_field, phase = pass1, "ReviewerDecision", "DraftText", "pass1"
    else:
        return [], _pending_gate(protocol, protocol)

    validation_dir = review_dir / f"validation-{phase}"
    validate_fn = _STRUCTURAL[protocol][1]
    result = validate_fn(input_path=surface, manifest_path=manifest_path, output_dir=validation_dir)
    validation_json = _validation_json_path(validation_dir, protocol)
    if result.get("status") != "passed":
        return [], {
            "protocol": protocol,
            "instanceId": protocol,
            "resultsPath": str(surface),
            "resultsSha256": sha256_file(surface),
            "validationSha256": sha256_file(validation_json),
            "candidateCount": int(result.get("recordCount", 0)),
            "blockingCount": int(result.get("findingCount", 1)),
            "status": "blocked",
        }

    normalized = _normalize_csv(
        surface=surface,
        protocol=protocol,
        instance_id=protocol,
        review_class="structural",
        decision_field=decision_field,
        text_field=text_field,
        canonical=canonical,
        validation_sha=sha256_file(validation_json),
    )
    results_path = workspace / "review" / "normalized" / f"{protocol}.jsonl"
    for item in normalized:
        SchemaStore().validate("e2e-review-result.schema.json", item)
    write_jsonl(results_path, normalized)
    blocking = _blocking_count(normalized)
    return normalized, {
        "protocol": protocol,
        "instanceId": protocol,
        "resultsPath": str(results_path),
        "resultsSha256": sha256_file(results_path),
        "validationSha256": sha256_file(validation_json),
        "candidateCount": len(normalized),
        "blockingCount": blocking,
        "status": "passed" if blocking == 0 else "blocked",
    }


def _prepare_qa_packages(
    config: ResolvedProjectConfig,
    canonical: dict[str, dict[str, Any]],
    workspace: Path,
    *,
    structural_base_sha: str | None = None,
) -> None:
    extract_path = Path(str(load_state(state_path(config))["artifacts"]["extractManifest"]))
    source_locale, target_locale, _, locales = load_locales(extract_path)
    source_records = locales[source_locale]
    target_records = {uid: str(item["text"]) for uid, item in canonical.items()}
    qa_root = workspace / "review" / "qa"
    base_target_path = qa_root / "base-target.jsonl"
    base_target_semantic_sha = _target_snapshot_sha(canonical)
    structural_base_sha = structural_base_sha or base_target_semantic_sha

    qa_inputs = list(config.resolved["qa"].get("ruleSets", []))
    for item in qa_inputs:
        if item["type"] != "taiwan-usage":
            raise WorkflowReviewError("language-qa", f"Unsupported QA type: {item['type']}")
        review_dir = qa_root / str(item["id"])
        manifest_path = review_dir / "e2e-qa-manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rules_path = Path(str(item["path"]))
        current = (
            manifest.get("baseTargetSha256") == base_target_semantic_sha
            and manifest.get("ruleSetSha256") == sha256_file(rules_path)
        )
        if not current:
            _archive_stale_review_dir(
                workspace,
                "language-qa",
                str(item["id"]),
                review_dir,
                base_target_semantic_sha,
            )

    write_jsonl(base_target_path, [dict(canonical[uid]) for uid in sorted(canonical)])
    base_target_artifact_sha = sha256_file(base_target_path)
    write_json(qa_root / "e2e-qa-lineage.json", {
        "schemaVersion": "1.0",
        "structuralBaseSha256": structural_base_sha,
        "currentQaBaseSha256": base_target_semantic_sha,
    })

    for item in qa_inputs:
        review_dir = qa_root / str(item["id"])
        manifest_path = review_dir / "e2e-qa-manifest.json"
        if manifest_path.is_file():
            continue
        review_dir.mkdir(parents=True, exist_ok=True)
        rules_path = Path(str(item["path"]))
        rules = load_taiwan_usage_rules(rules_path)
        candidates = candidates_from_target(
            source_records=source_records,
            target_records=target_records,
            rules=rules,
        )
        review_path = review_dir / "taiwan-usage-review.csv"
        _write_taiwan_csv(review_path, candidates)
        manifest = {
            "schemaVersion": "1.0",
            "packageType": "E2ETaiwanUsageReviewPackage",
            "instanceId": str(item["id"]),
            "sourceLocale": source_locale,
            "targetLocale": target_locale,
            "ruleSet": str(rules_path),
            "ruleSetSha256": sha256_file(rules_path),
            "baseTarget": str(base_target_path),
            "baseTargetArtifactSha256": base_target_artifact_sha,
            "baseTargetSha256": base_target_semantic_sha,
            "candidates": [candidate.to_dict() for candidate in candidates],
        }
        write_json(manifest_path, manifest)

def _load_qa_base(
    workspace: Path,
    qa_inputs: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    qa_root = workspace / "review" / "qa"
    expected_path: Path | None = None
    expected_artifact_sha: str | None = None
    expected_semantic_sha: str | None = None
    for item in qa_inputs:
        manifest_path = qa_root / str(item["id"]) / "e2e-qa-manifest.json"
        if not manifest_path.is_file():
            raise WorkflowReviewError("language-qa", f"QA manifest missing: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        path = Path(str(manifest.get("baseTarget", "")))
        artifact_sha = str(manifest.get("baseTargetArtifactSha256", ""))
        semantic_sha = str(manifest.get("baseTargetSha256", ""))
        if not path.is_file() or sha256_file(path) != artifact_sha:
            raise WorkflowReviewError("language-qa", f"QA base target is missing or stale: {path}")
        if expected_path is None:
            expected_path = path.resolve()
            expected_artifact_sha = artifact_sha
            expected_semantic_sha = semantic_sha
        elif (
            path.resolve() != expected_path
            or artifact_sha != expected_artifact_sha
            or semantic_sha != expected_semantic_sha
        ):
            raise WorkflowReviewError(
                "language-qa",
                "Configured QA instances do not share one canonical base target",
            )
    if expected_path is None:
        return {}
    canonical = _index_target(read_jsonl(expected_path))
    if _target_snapshot_sha(canonical) != expected_semantic_sha:
        raise WorkflowReviewError("language-qa", "QA canonical base target semantic hash mismatch")
    return canonical


def _archive_qa_rounds(
    config: ResolvedProjectConfig,
    workspace: Path,
    base: dict[str, dict[str, Any]],
) -> None:
    qa_root = workspace / "review" / "qa"
    history_root = workspace / "review" / "qa-history"
    round_id = _target_snapshot_sha(base)[:16]
    for item in config.resolved["qa"].get("ruleSets", []):
        instance_id = str(item["id"])
        source = qa_root / instance_id
        if not source.exists():
            continue
        destination = history_root / instance_id / round_id
        if destination.exists():
            raise WorkflowReviewError(
                "language-qa",
                f"QA history round already exists: {destination}",
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
    base_target = qa_root / "base-target.jsonl"
    if base_target.is_file():
        snapshot_destination = history_root / "_base-target" / f"{round_id}.jsonl"
        snapshot_destination.parent.mkdir(parents=True, exist_ok=True)
        if snapshot_destination.exists():
            raise WorkflowReviewError(
                "language-qa",
                f"QA base-target history already exists: {snapshot_destination}",
            )
        shutil.move(str(base_target), str(snapshot_destination))


def _integrate_qa_instance(
    workspace: Path,
    item: dict[str, Any],
    canonical: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    instance_id = str(item["id"])
    review_dir = workspace / "review" / "qa" / instance_id
    manifest_path = review_dir / "e2e-qa-manifest.json"
    review_path = review_dir / "taiwan-usage-review.csv"
    if not manifest_path.is_file() or not review_path.is_file():
        return [], _pending_gate("taiwan-usage", instance_id)
    if not _decisions_complete(review_path, "ReviewerDecision"):
        return [], _pending_gate("taiwan-usage", instance_id)

    validation_dir = review_dir / "validation"
    result = validate_taiwan_usage_review(
        input_path=review_path,
        manifest_path=manifest_path,
        output_dir=validation_dir,
    )
    validation_json = validation_dir / "taiwan-usage-review-validation.json"
    if result.get("status") != "passed":
        return [], {
            "protocol": "taiwan-usage",
            "instanceId": instance_id,
            "resultsPath": str(review_path),
            "resultsSha256": sha256_file(review_path),
            "validationSha256": sha256_file(validation_json),
            "candidateCount": int(result.get("recordCount", 0)),
            "blockingCount": int(result.get("findingCount", 1)),
            "status": "blocked",
        }

    normalized = _normalize_csv(
        surface=review_path,
        protocol="taiwan-usage",
        instance_id=instance_id,
        review_class="language-qa",
        decision_field="ReviewerDecision",
        text_field="ProposedText",
        canonical=canonical,
        validation_sha=sha256_file(validation_json),
    )
    results_path = workspace / "review" / "normalized" / f"qa-{instance_id}.jsonl"
    for record in normalized:
        SchemaStore().validate("e2e-review-result.schema.json", record)
    write_jsonl(results_path, normalized)
    blocking = _blocking_count(normalized)
    return normalized, {
        "protocol": "taiwan-usage",
        "instanceId": instance_id,
        "resultsPath": str(results_path),
        "resultsSha256": sha256_file(results_path),
        "validationSha256": sha256_file(validation_json),
        "candidateCount": len(normalized),
        "blockingCount": blocking,
        "status": "passed" if blocking == 0 else "blocked",
    }


def _normalize_csv(
    *,
    surface: Path,
    protocol: str,
    instance_id: str,
    review_class: str,
    decision_field: str,
    text_field: str,
    canonical: dict[str, dict[str, Any]],
    validation_sha: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    with surface.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            uid = str(row.get("ContentUid", ""))
            if uid not in canonical:
                continue
            source_decision = str(row.get(decision_field, "Pending"))
            decision = _normalize_decision(protocol, source_decision)
            base_text = str(canonical[uid]["text"])
            proposed_raw = str(row.get(text_field, "") or "")
            if proposed_raw != base_text and decision != "revision-required":
                raise WorkflowReviewError(
                    review_class,
                    f"{instance_id}:{uid}: reviewed text changed without a revision decision",
                )
            proposed = proposed_raw if decision == "revision-required" and proposed_raw != base_text else None
            record = {
                "ContentUid": uid,
                "Protocol": protocol,
                "ReviewInstanceId": instance_id,
                "ReviewClass": review_class,
                "Decision": decision,
                "BaseTextSha256": _text_sha256(base_text),
                "CandidateId": str(row.get("CandidateId", "")),
                "SourceValidationSha256": validation_sha,
                "ProposedText": proposed,
                "ReviewerNote": str(row.get("ReviewerNote", "")),
                "Evidence": {
                    "sourceDecision": source_decision,
                    "surface": surface.name,
                },
            }
            result.append(record)
    return result


def _normalize_decision(protocol: str, value: str) -> str:
    if protocol == "taiwan-usage":
        return {
            "Pending": "pending",
            "AcceptAsIs": "clear",
            "Revise": "revision-required",
            "NotApplicable": "not-applicable",
            "NeedsContext": "needs-context",
        }.get(value, "pending")
    return {
        "Pending": "pending",
        "Approved": "clear",
        "NeedsRevision": "revision-required",
        "InsufficientEvidence": "insufficient-evidence",
        "NotApplicable": "not-applicable",
    }.get(value, "pending")


def _reconcile(
    canonical: dict[str, dict[str, Any]],
    results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    by_uid: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        by_uid.setdefault(str(item["ContentUid"]), []).append(item)

    reconciliation: list[dict[str, Any]] = []
    target_rows: list[dict[str, Any]] = []
    conflicts = 0
    for uid, base in sorted(canonical.items()):
        base_text = str(base["text"])
        revisions = [item for item in by_uid.get(uid, []) if item["Decision"] == "revision-required"]
        proposed = {str(item["ProposedText"]) for item in revisions if item.get("ProposedText") is not None}
        unresolved = any(item.get("ProposedText") is None for item in revisions)
        instances = sorted({str(item["ReviewInstanceId"]) for item in by_uid.get(uid, [])})
        if unresolved or len(proposed) > 1:
            resolution = "conflict"
            resolved_text = None
            resolved_sha = None
            conflicts += 1
            target_text = base_text
        elif len(proposed) == 1:
            target_text = next(iter(proposed))
            resolution = "adopted-review-revision"
            resolved_text = target_text
            resolved_sha = _text_sha256(target_text)
        else:
            target_text = base_text
            resolution = "unchanged"
            resolved_text = target_text
            resolved_sha = _text_sha256(target_text)

        record = {
            "ContentUid": uid,
            "BaseTextSha256": _text_sha256(base_text),
            "ResolvedText": resolved_text,
            "ResolvedTextSha256": resolved_sha,
            "ContributingReviewInstances": instances,
            "Resolution": resolution,
        }
        SchemaStore().validate("e2e-review-reconciliation.schema.json", record)
        reconciliation.append(record)

        row = dict(base)
        row["text"] = target_text
        target_rows.append(row)
    return reconciliation, target_rows, conflicts


def _integration_manifest(
    *,
    package_sha: str,
    base_target_sha: str,
    structural: list[dict[str, Any]],
    qa: list[dict[str, Any]],
    reconciliation_path: Path,
    conflict_count: int,
    final_target_path: Path,
    status: str,
) -> dict[str, Any]:
    manifest = {
        "schemaVersion": "1.0",
        "packageType": "E2EReviewIntegration",
        "translationPackageSha256": package_sha,
        "baseTargetSha256": base_target_sha,
        "structural": structural,
        "qa": qa,
        "reconciliation": {
            "path": str(reconciliation_path),
            "sha256": sha256_file(reconciliation_path),
            "conflictCount": conflict_count,
        },
        "finalTarget": {
            "path": str(final_target_path),
            "sha256": sha256_file(final_target_path),
            "recordCount": len(read_jsonl(final_target_path)),
        },
        "status": status,
    }
    SchemaStore().validate("e2e-review-integration.schema.json", manifest)
    return manifest


def _prefill_structural_surfaces(
    review_dir: Path,
    protocol: str,
    canonical: dict[str, dict[str, Any]],
) -> None:
    for phase, field in (("pass1", "DraftText"), ("pass2", "FinalText")):
        path = review_dir / f"{protocol}-review-{phase}.csv"
        if not path.is_file():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = list(reader.fieldnames or [])
            rows = list(reader)
        for row in rows:
            uid = str(row.get("ContentUid", ""))
            if uid in canonical:
                row[field] = str(canonical[uid]["text"])
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    manifest_path = review_dir / _STRUCTURAL[protocol][2]
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for artifact in manifest.get("artifacts", []):
            raw = Path(str(artifact.get("path", "")))
            artifact_path = raw if raw.is_absolute() else review_dir / raw
            if artifact_path.is_file():
                artifact["sha256"] = sha256_file(artifact_path)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _write_taiwan_csv(path: Path, candidates: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    for candidate in candidates:
        rows.append({
            "CandidateId": candidate.candidate_id,
            "ContentUid": candidate.content_uid,
            "SourceText": candidate.source_text,
            "TargetText": candidate.target_text,
            "FindingCount": str(candidate.finding_count),
            "Findings": json.dumps([asdict(item) for item in candidate.findings], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            "ProtectedTokens": json.dumps(list(candidate.protected_tokens), ensure_ascii=False, separators=(",", ":")),
            "ReviewerDecision": "Pending",
            "ReviewerNote": "",
            "ProposedText": "",
            "ValidationStatus": "NotChecked",
        })
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=TAIWAN_COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _decisions_complete(path: Path, field: str) -> bool:
    if not path.is_file():
        return False
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return all(str(row.get(field, "Pending")) != "Pending" for row in rows)


def _validation_json_path(validation_dir: Path, protocol: str) -> Path:
    names = {
        "bark": "bark-review-validation.json",
        "quest": "quest-review-validation.json",
        "ui-skill": "ui-skill-review-validation.json",
        "multilingual": "multilingual-review-validation.json",
    }
    return validation_dir / names[protocol]


def _load_qa_lineage(qa_root: Path) -> dict[str, Any]:
    path = qa_root / "e2e-qa-lineage.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _review_base_binding_current(path: Path, expected_sha: str) -> bool:
    if not path.is_file():
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return value.get("baseTargetSha256") == expected_sha


def _archive_stale_review_dir(
    workspace: Path,
    review_class: str,
    instance_id: str,
    source: Path,
    incoming_base_sha: str,
) -> None:
    if not source.exists():
        return
    history_root = workspace / "review" / "stale" / review_class / instance_id
    history_root.mkdir(parents=True, exist_ok=True)
    stem = f"before-{incoming_base_sha[:16]}"
    destination = history_root / stem
    suffix = 1
    while destination.exists():
        destination = history_root / f"{stem}-{suffix}"
        suffix += 1
    shutil.move(str(source), str(destination))


def _pending_gate(protocol: str, instance_id: str) -> dict[str, Any]:
    return {
        "protocol": protocol,
        "instanceId": instance_id,
        "resultsPath": "pending",
        "resultsSha256": "0" * 64,
        "validationSha256": "0" * 64,
        "candidateCount": 0,
        "blockingCount": 1,
        "status": "pending",
    }


def _blocking_count(results: list[dict[str, Any]]) -> int:
    blocking = {"pending", "needs-context", "insufficient-evidence"}
    count = sum(1 for item in results if item["Decision"] in blocking)
    count += sum(
        1 for item in results
        if item["Decision"] == "revision-required" and item.get("ProposedText") is None
    )
    return count


def _index_target(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item["contentUid"]): dict(item) for item in rows}


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _target_snapshot_sha(canonical: dict[str, dict[str, Any]]) -> str:
    payload = "\n".join(f"{uid}\t{canonical[uid]['text']}" for uid in sorted(canonical))
    return _text_sha256(payload)


def _set_review_blocked(state: dict[str, Any], state_file: Path, stage: str) -> None:
    state["stages"][stage]["status"] = "blocked"
    state["stages"][stage]["message"] = "Review integration contains unresolved work"
    state["currentStage"] = stage
    write_state(state_file, state)
