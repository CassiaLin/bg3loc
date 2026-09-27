from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bg3loc.e2e.config import ResolvedProjectConfig, resolved_structural_reviews
from bg3loc.e2e.package import read_jsonl, sha256_file, write_jsonl
from bg3loc.e2e.state import fingerprint_data, load_state, stage_reusable, state_path, write_state
from bg3loc.io import read_json, write_json
from bg3loc.protected_syntax import has_valid_lstag_structure, validate_protected_syntax
from bg3loc.schema import SchemaStore
from bg3loc.validator import read_return_material


_INTENTIONAL_EMPTY = {"intentionally-empty", "empty", "not-applicable", "skip"}


class WorkflowValidateError(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message


def run_validate(
    config: ResolvedProjectConfig,
    input_spec: str | None = None,
    *,
    review_gate: bool = True,
) -> dict[str, Any]:
    state_file = state_path(config)
    if not state_file.is_file():
        raise WorkflowValidateError("validate", "Workflow state not found; run workflow prepare first")
    state = load_state(state_file)
    if state["projectConfigSha256"] != config.sha256:
        raise WorkflowValidateError("config", "Workflow state project binding does not match current config")

    package_manifest_path = Path(str(state["artifacts"].get("translationPackage") or ""))
    if not package_manifest_path.is_file():
        raise WorkflowValidateError("package", "Translation package manifest is missing")
    expected_package_sha = state["bindings"].get("translationPackageSha256")
    if expected_package_sha != sha256_file(package_manifest_path):
        raise WorkflowValidateError("package", "Translation package manifest hash changed")

    package = read_json(package_manifest_path)
    SchemaStore().validate("translation-package.schema.json", package)
    package_root = package_manifest_path.parent

    baseline: dict[str, dict[str, Any]] = {}
    for artifact in package["internal"]["immutable"]:
        path = _package_path(package_root, str(artifact["path"]))
        if sha256_file(path) != str(artifact["sha256"]):
            raise WorkflowValidateError("validate", f"Immutable baseline hash mismatch: {path}")
        for row in read_jsonl(path):
            uid = str(row.get("ContentUid", ""))
            if not uid or uid in baseline:
                raise WorkflowValidateError("validate", f"Invalid immutable ContentUid: {uid}")
            baseline[uid] = row

    for item in package["delivery"]["materials"]:
        prepared = _package_path(package_root, str(item["path"]))
        if sha256_file(prepared) != str(item["sha256"]):
            raise WorkflowValidateError(
                "package",
                f"Prepared delivery baseline hash mismatch: {prepared}",
            )

    if input_spec:
        input_files = _expand_input(Path(input_spec))
    else:
        returns_dir = Path(config.resolved["workspace"]["root"]) / "e2e" / "returns"
        binding_path = returns_dir / "returns-manifest.json"
        if not binding_path.is_file():
            raise WorkflowValidateError(
                "translate",
                "Returns binding is missing; rerun workflow prepare and use the generated returns directory.",
            )
        returns_binding = read_json(binding_path)
        if returns_binding.get("sourceTranslationPackageSha256") != expected_package_sha:
            raise WorkflowValidateError(
                "translate",
                "Returned translation material is stale because it belongs to a different translation package.",
            )
        input_files = _expand_input(returns_dir)
    if not input_files:
        raise WorkflowValidateError(
            "validate",
            "No returned translation material found; place completed files under "
            "<workspace>/e2e/returns or pass --input.",
        )

    input_bindings = [
        {"path": str(path.resolve()), "sha256": sha256_file(path)}
        for path in input_files
    ]
    base_validation_fingerprint = fingerprint_data({
        "packageSha256": expected_package_sha,
        "returns": input_bindings,
        "reviewGate": review_gate,
    })
    configured_structural = resolved_structural_reviews(config)
    configured_qa = list(config.effective["qa"].get("ruleSets", []))
    existing_integration_path = (
        Path(config.resolved["workspace"]["root"])
        / "e2e"
        / "review"
        / "e2e-review-integration.json"
    )
    current_review_sha = (
        sha256_file(existing_integration_path)
        if review_gate and (configured_structural or configured_qa) and existing_integration_path.is_file()
        else None
    )
    candidate_validation_fingerprint = fingerprint_data({
        "base": base_validation_fingerprint,
        "reviewIntegrationSha256": current_review_sha,
    })
    if review_gate and stage_reusable(
        state,
        "validate",
        candidate_validation_fingerprint,
    ):
        manifest_path = Path(str(state["stages"]["validate"]["artifact"]))
        manifest = read_json(manifest_path)
        accepted_reuse_path = Path(str(manifest.get("accepted", {}).get("path", "")))
        expected_accepted_sha = state["bindings"].get("validationAcceptedSha256")
        if (
            not accepted_reuse_path.is_file()
            or not expected_accepted_sha
            or sha256_file(accepted_reuse_path) != expected_accepted_sha
        ):
            state["stages"]["validate"]["status"] = "invalidated"
            state["stages"]["validate"]["message"] = "Accepted validation target changed"
        else:
            return {
                "status": "pass",
                "errorCount": int(manifest.get("summary", {}).get("errorCount", 0)),
                "acceptedRecordCount": int(manifest.get("accepted", {}).get("recordCount", 0)),
                "validateManifest": str(manifest_path),
                "reused": True,
            }

    rows: list[dict[str, Any]] = []
    for path in input_files:
        rows.extend(read_return_material(path))

    allowed_fields = set(SchemaStore().load("translation-material-row.schema.json")["properties"])
    seen: set[str] = set()
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    evaluated_required: set[str] = set()

    for row in rows:
        uid = _text(row.get("ContentUid"))
        file_name = _text(row.get("__file__"))
        row_no = row.get("__row__")
        errors: list[str] = []

        if not uid or uid not in baseline:
            errors.append("UNKNOWN_CONTENT_UID")
        elif uid in seen:
            errors.append("DUPLICATE_CONTENT_UID")
        else:
            seen.add(uid)
            immutable = baseline[uid]
            _validate_immutable(row, immutable, allowed_fields, errors)

            status = _text(row.get("TranslationStatus")).casefold()
            candidate = _text(row.get("ProposedTargetText"))
            if bool(immutable.get("TranslationRequired")) and status:
                evaluated_required.add(uid)

            required_tokens = immutable.get("ProtectedTokens", [])
            if candidate:
                if not isinstance(required_tokens, list) or not all(isinstance(item, str) for item in required_tokens):
                    errors.append("PROTECTED_TOKEN_BASELINE_INVALID")
                else:
                    issues = validate_protected_syntax(required_tokens, candidate)
                    errors.extend(f"PROTECTED_SYNTAX_{issue.kind.upper()}" for issue in issues)
                    if (
                        immutable.get("PresenceStatus") == "source-only"
                        and has_valid_lstag_structure(str(immutable.get("SourceText", "")))
                        and not has_valid_lstag_structure(candidate)
                    ):
                        errors.append("LSTAG_STRUCTURE_INVALID")
            elif bool(immutable.get("TranslationRequired")) and status not in _INTENTIONAL_EMPTY:
                errors.append("REQUIRED_TARGET_EMPTY")

            if not errors and (candidate or status in _INTENTIONAL_EMPTY):
                accepted.append({
                    "contentUid": uid,
                    "localeId": str(immutable["TargetLocale"]),
                    "text": candidate,
                    "version": immutable.get("TargetVersion")
                    if immutable.get("TargetVersion") is not None
                    else immutable.get("SourceVersion"),
                    "translationStatus": _text(row.get("TranslationStatus")),
                    "translatorNotes": _text(row.get("TranslatorNotes")),
                    "translatorName": _text(row.get("TranslatorName")),
                })

        if errors:
            rejected.append({
                "contentUid": uid or None,
                "file": file_name,
                "row": row_no,
                "errors": errors,
            })
            for error in errors:
                findings.append({
                    "contentUid": uid or None,
                    "file": file_name,
                    "row": row_no,
                    "severity": "error",
                    "message": error,
                })

    required_uids = {uid for uid, item in baseline.items() if bool(item.get("TranslationRequired"))}
    missing_required = sorted(required_uids - seen)
    for uid in missing_required:
        findings.append({
            "contentUid": uid,
            "file": None,
            "row": None,
            "severity": "error",
            "message": "REQUIRED_ROW_MISSING",
        })

    strategy = str(config.effective["workflow"]["translationStrategy"])
    if strategy == "blind-first":
        for uid in sorted(required_uids - evaluated_required):
            findings.append({
                "contentUid": uid,
                "file": None,
                "row": None,
                "severity": "error",
                "message": "BLIND_FIRST_COVERAGE_INCOMPLETE",
            })

    error_count = sum(1 for item in findings if item["severity"] == "error")
    workspace = Path(config.resolved["workspace"]["root"]) / "e2e"
    validation_dir = workspace / "validation"
    accepted_path = validation_dir / "accepted" / "normalized-target.jsonl"
    rejected_path = validation_dir / "rejected" / "rejected-rows.jsonl"
    findings_path = validation_dir / "reports" / "e2e-findings.json"
    write_jsonl(accepted_path, accepted)
    write_jsonl(rejected_path, rejected)
    write_json(findings_path, {
        "schemaVersion": "1.0",
        "findings": findings,
    })

    if error_count:
        _update_blocked_state(state, state_file, "validate", f"{error_count} translation validation error(s)")
        return {
            "status": "fail",
            "errorCount": error_count,
            "acceptedRecordCount": len(accepted),
            "findings": findings_path,
        }

    if not review_gate:
        return {
            "status": "pass",
            "errorCount": 0,
            "acceptedRecordCount": len(accepted),
            "baseOnly": True,
        }

    structural = configured_structural
    qa_inputs = configured_qa
    if structural or qa_inputs:
        integration_path = workspace / "review" / "e2e-review-integration.json"
        integration_needs_work = True
        if integration_path.is_file():
            try:
                existing_integration = read_json(integration_path)
                SchemaStore().validate("e2e-review-integration.schema.json", existing_integration)
                integration_needs_work = existing_integration.get("status") != "passed"
            except Exception:
                integration_needs_work = True

        if not integration_path.is_file():
            from bg3loc.e2e.review import prepare_reviews
            prepare_reviews(config, input_spec)

        if integration_needs_work:
            from bg3loc.e2e.review import integrate_reviews
            integrated = integrate_reviews(config)
            if integrated.get("status") != "passed":
                stage = str(integrated.get("stage") or state.get("currentStage") or "structural-review")
                path = integrated.get("path")
                message = str(integrated.get("message") or "Human review work remains")
                if path:
                    message = f"{message}; workspace: {path}"
                _update_blocked_state(state, state_file, stage, message)
                return {
                    "status": "blocked",
                    "blockingStage": stage,
                    "message": message,
                    "acceptedRecordCount": len(accepted),
                }

    review_result = _load_review_gate_if_required(config, state, workspace, accepted)
    if review_result["status"] != "passed":
        stage = review_result["stage"]
        _update_blocked_state(state, state_file, stage, review_result["message"])
        return {
            "status": "blocked",
            "blockingStage": stage,
            "message": review_result["message"],
            "acceptedRecordCount": len(accepted),
        }

    final_target = review_result.get("finalTarget")
    if final_target:
        final_rows = read_jsonl(Path(str(final_target)))
        final_errors = _validate_final_target(final_rows, baseline)
        if final_errors:
            for uid, message in final_errors:
                findings.append({
                    "contentUid": uid,
                    "file": str(final_target),
                    "row": None,
                    "severity": "error",
                    "message": message,
                })
            write_json(findings_path, {
                "schemaVersion": "1.0",
                "findings": findings,
            })
            _update_blocked_state(
                state,
                state_file,
                "validate",
                f"{len(final_errors)} final canonical target validation error(s)",
            )
            return {
                "status": "fail",
                "errorCount": len(final_errors),
                "acceptedRecordCount": len(accepted),
                "findings": findings_path,
            }
        accepted = final_rows
        write_jsonl(accepted_path, accepted)

    validate_manifest = {
        "schemaVersion": "1.0",
        "buildManifest": str(package_manifest_path),
        "strict": True,
        "accepted": {"path": str(accepted_path), "recordCount": len(accepted)},
        "rejected": {"path": str(rejected_path), "recordCount": len(rejected)},
        "reports": {"summary": str(findings_path), "errors": str(findings_path)},
        "summary": {
            "status": "pass",
            "errorCount": 0,
            "warningCount": 0,
            "missingReturnRowCount": len(baseline) - len(seen),
            "independentEvaluationCoverage": (
                1.0 if strategy == "blind-first" else None
            ),
        },
    }
    SchemaStore().validate("validate-manifest.schema.json", validate_manifest)
    validate_manifest_path = validation_dir / "validate-manifest.json"
    write_json(validate_manifest_path, validate_manifest)

    translation_fingerprint = fingerprint_data({
        "packageSha256": expected_package_sha,
        "returns": input_bindings,
    })
    state["stages"]["translate"]["status"] = "completed"
    state["stages"]["translate"]["fingerprint"] = translation_fingerprint

    review_sha = state["bindings"].get("reviewIntegrationSha256")
    if structural:
        state["stages"]["structural-review"]["status"] = "completed"
        state["stages"]["structural-review"]["fingerprint"] = review_sha
    else:
        state["stages"]["structural-review"]["status"] = "skipped"
        state["stages"]["structural-review"]["fingerprint"] = None

    if structural or qa_inputs:
        state["stages"]["reconcile"]["status"] = "completed"
        state["stages"]["reconcile"]["fingerprint"] = review_sha
    else:
        state["stages"]["reconcile"]["status"] = "skipped"
        state["stages"]["reconcile"]["fingerprint"] = None

    if qa_inputs:
        state["stages"]["language-qa"]["status"] = "completed"
        state["stages"]["language-qa"]["fingerprint"] = review_sha
    else:
        state["stages"]["language-qa"]["status"] = "skipped"
        state["stages"]["language-qa"]["fingerprint"] = None

    validation_fingerprint = fingerprint_data({
        "base": base_validation_fingerprint,
        "reviewIntegrationSha256": review_sha,
    })
    state["stages"]["validate"]["status"] = "completed"
    state["stages"]["validate"]["artifact"] = str(validate_manifest_path)
    state["stages"]["validate"]["sha256"] = sha256_file(validate_manifest_path)
    state["stages"]["validate"]["fingerprint"] = validation_fingerprint
    state["stages"]["validate"]["message"] = None
    state["bindings"]["validationManifestSha256"] = sha256_file(validate_manifest_path)
    state["bindings"]["validationAcceptedSha256"] = sha256_file(accepted_path)
    state["artifacts"]["validateManifest"] = str(validate_manifest_path)
    state["stages"]["rebuild"]["status"] = "ready"
    state["currentStage"] = "rebuild"
    write_state(state_file, state)

    return {
        "status": "pass",
        "errorCount": 0,
        "acceptedRecordCount": len(accepted),
        "validateManifest": str(validate_manifest_path),
    }


def _load_review_gate_if_required(
    config: ResolvedProjectConfig,
    state: dict[str, Any],
    workspace: Path,
    accepted: list[dict[str, Any]],
) -> dict[str, Any]:
    structural = resolved_structural_reviews(config)
    qa = list(config.effective["qa"].get("ruleSets", []))
    if not structural and not qa:
        return {"status": "passed", "stage": "validate", "message": "", "finalTarget": None}

    integration_path = workspace / "review" / "e2e-review-integration.json"
    if not integration_path.is_file():
        if structural:
            return {
                "status": "blocked",
                "stage": "structural-review",
                "message": "Configured structural review is not complete",
            }
        return {
            "status": "blocked",
            "stage": "language-qa",
            "message": "Configured project-language QA is not complete",
        }

    integration = read_json(integration_path)
    SchemaStore().validate("e2e-review-integration.schema.json", integration)
    if integration.get("translationPackageSha256") != state["bindings"].get("translationPackageSha256"):
        raise WorkflowValidateError("review", "Review integration belongs to a different translation package")
    if integration.get("baseTargetSha256") != _target_snapshot_sha(accepted):
        raise WorkflowValidateError(
            "review",
            "Review integration is stale because canonical translated text changed",
        )
    if integration.get("status") != "passed":
        return {
            "status": "blocked",
            "stage": "structural-review" if structural else "language-qa",
            "message": "Review integration has blocking or pending results",
        }
    if int(integration.get("reconciliation", {}).get("conflictCount", 0)) != 0:
        return {
            "status": "blocked",
            "stage": "reconcile",
            "message": "Review reconciliation still contains conflicts",
        }
    final_target = integration.get("finalTarget", {})
    final_path = Path(str(final_target.get("path", "")))
    if not final_path.is_file():
        raise WorkflowValidateError("review", "Passed review integration final target is missing")
    if sha256_file(final_path) != str(final_target.get("sha256", "")):
        raise WorkflowValidateError("review", "Passed review integration final target hash mismatch")
    final_rows = read_jsonl(final_path)
    if len(final_rows) != int(final_target.get("recordCount", -1)):
        raise WorkflowValidateError("review", "Passed review integration final target count mismatch")
    state["bindings"]["reviewIntegrationSha256"] = sha256_file(integration_path)
    state["artifacts"]["reviewIntegration"] = str(integration_path)
    return {
        "status": "passed",
        "stage": "validate",
        "message": "",
        "finalTarget": str(final_path),
    }



def _validate_final_target(
    rows: list[dict[str, Any]],
    baseline: dict[str, dict[str, Any]],
) -> list[tuple[str | None, str]]:
    errors: list[tuple[str | None, str]] = []
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        uid = str(row.get("contentUid", ""))
        if not uid or uid not in baseline:
            errors.append((uid or None, "FINAL_TARGET_UNKNOWN_CONTENT_UID"))
            continue
        if uid in indexed:
            errors.append((uid, "FINAL_TARGET_DUPLICATE_CONTENT_UID"))
            continue
        indexed[uid] = row

    for uid in sorted(set(baseline) - set(indexed)):
        errors.append((uid, "FINAL_TARGET_MISSING_CONTENT_UID"))

    for uid, row in indexed.items():
        immutable = baseline[uid]
        text = str(row.get("text", ""))
        status = str(row.get("translationStatus", "")).casefold()
        if bool(immutable.get("TranslationRequired")) and not text and status not in _INTENTIONAL_EMPTY:
            errors.append((uid, "FINAL_TARGET_REQUIRED_TEXT_EMPTY"))
            continue
        if not text:
            continue

        required_tokens = immutable.get("ProtectedTokens", [])
        if not isinstance(required_tokens, list) or not all(isinstance(item, str) for item in required_tokens):
            errors.append((uid, "FINAL_TARGET_PROTECTED_TOKEN_BASELINE_INVALID"))
            continue
        for issue in validate_protected_syntax(required_tokens, text):
            errors.append((uid, f"FINAL_TARGET_PROTECTED_SYNTAX_{issue.kind.upper()}"))
        if (
            immutable.get("PresenceStatus") == "source-only"
            and has_valid_lstag_structure(str(immutable.get("SourceText", "")))
            and not has_valid_lstag_structure(text)
        ):
            errors.append((uid, "FINAL_TARGET_LSTAG_STRUCTURE_INVALID"))
    return errors

def _validate_immutable(
    row: dict[str, Any],
    immutable: dict[str, Any],
    allowed_fields: set[str],
    errors: list[str],
) -> None:
    comparisons = {
        "SourceLocale": immutable.get("SourceLocale"),
        "SourceText": immutable.get("SourceText"),
        "TargetLocale": immutable.get("TargetLocale"),
        "PresenceStatus": immutable.get("PresenceStatus"),
        "TranslationRequired": immutable.get("TranslationRequired"),
        "ProtectedTokens": immutable.get("ProtectedTokens", []),
        "EvidenceFlags": immutable.get("EvidenceFlags", []),
        "ContextSummary": immutable.get("ContextSummary", ""),
        "ExistingTargetText": immutable.get("ExistingTargetText", ""),
        "ReferenceTexts": immutable.get("ReferenceTexts", {}),
    }
    for field, expected in comparisons.items():
        if field not in row:
            continue
        if _canonical(row.get(field)) != _canonical(expected):
            errors.append(f"IMMUTABLE_FIELD_MODIFIED:{field}")

    for field, value in row.items():
        if field.startswith("__") or field in allowed_fields:
            continue
        if _canonical(value) != "":
            errors.append(f"UNEXPECTED_FIELD:{field}")


def _canonical(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, str):
        text = value.strip()
        if text.casefold() in {"true", "false"}:
            return text.casefold()
        if text.startswith(("[", "{")):
            try:
                return _canonical(json.loads(text))
            except json.JSONDecodeError:
                return value
        return value
    return str(value)


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _package_path(root: Path, raw: str) -> Path:
    candidate = root / Path(raw)
    resolved_root = root.resolve(strict=False)
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise WorkflowValidateError("package", f"Package path escapes package root: {raw}") from exc
    if not resolved.is_file():
        raise WorkflowValidateError("package", f"Package artifact missing: {raw}")
    return resolved


def _expand_input(path: Path) -> list[Path]:
    direct = path.expanduser()
    if direct.is_file():
        return [direct.resolve()]
    if direct.is_dir():
        result: list[Path] = []
        for suffix in ("*.xlsx", "*.csv", "*.jsonl"):
            result.extend(direct.glob(suffix))
        return sorted({item.resolve() for item in result}, key=lambda item: str(item).casefold())
    return []


def _update_blocked_state(
    state: dict[str, Any],
    state_file: Path,
    stage: str,
    message: str,
) -> None:
    if stage in state["stages"]:
        state["stages"][stage]["status"] = "blocked"
        state["stages"][stage]["message"] = message
    state["currentStage"] = stage
    write_state(state_file, state)


def _target_snapshot_sha(rows: list[dict[str, Any]]) -> str:
    import hashlib
    canonical = {
        str(item["contentUid"]): str(item.get("text", ""))
        for item in rows
    }
    payload = "\n".join(f"{uid}\t{canonical[uid]}" for uid in sorted(canonical))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
