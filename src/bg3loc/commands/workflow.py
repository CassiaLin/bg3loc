from __future__ import annotations

import argparse
from pathlib import Path

from bg3loc.e2e.config import ProjectConfigError, load_project_config
from bg3loc.e2e.state import load_state, state_path
from bg3loc.e2e.prepare import WorkflowPrepareError, run_prepare
from bg3loc.e2e.validate import WorkflowValidateError, run_validate
from bg3loc.e2e.rebuild import WorkflowRebuildError, run_workflow_rebuild
from bg3loc.e2e.install import WorkflowInstallError, run_workflow_install
from bg3loc.e2e.review import (
    WorkflowReviewError,
    integrate_reviews,
    prepare_reviews,
    record_manual_resolutions,
)
from bg3loc.errors import BG3LocError


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    workflow = subparsers.add_parser("workflow", help="High-level E2E translation workflow")
    actions = workflow.add_subparsers(dest="workflow_action", required=True)

    prepare = actions.add_parser("prepare", help="Prepare an E2E translation package")
    prepare.add_argument("--project", default="bg3loc-project.json")
    prepare.set_defaults(handler=run_prepare_command)

    review = actions.add_parser("review", help="Prepare or integrate configured E2E human review")
    review_actions = review.add_subparsers(dest="workflow_review_action", required=True)

    review_prepare = review_actions.add_parser("prepare", help="Prepare configured structural review / QA surfaces")
    review_prepare.add_argument("--project", default="bg3loc-project.json")
    review_prepare.add_argument("--input")
    review_prepare.set_defaults(handler=run_review_prepare_command)

    review_integrate = review_actions.add_parser("integrate", help="Validate, normalize, and reconcile completed reviews")
    review_integrate.add_argument("--project", default="bg3loc-project.json")
    review_integrate.set_defaults(handler=run_review_integrate_command)

    review_resolve = review_actions.add_parser("resolve", help="Record explicit resolutions for current review text conflicts")
    review_resolve.add_argument("--project", default="bg3loc-project.json")
    review_resolve.add_argument("--input", required=True, help="JSONL rows with ContentUid and ResolvedText")
    review_resolve.set_defaults(handler=run_review_resolve_command)

    validate = actions.add_parser("validate", help="Validate returned E2E translation material and review gates")
    validate.add_argument("--project", default="bg3loc-project.json")
    validate.add_argument("--input")
    validate.set_defaults(handler=run_validate_command)

    rebuild = actions.add_parser("rebuild", help="Rebuild from passed E2E validation")
    rebuild.add_argument("--project", default="bg3loc-project.json")
    rebuild.set_defaults(handler=run_rebuild_command)

    install = actions.add_parser("install", help="Dry-run or apply a rebuilt E2E localization")
    install.add_argument("--project", default="bg3loc-project.json")
    install.add_argument("--apply", action="store_true", help="Actually modify the game after a successful dry-run")
    install.set_defaults(handler=run_install_command)

    status = actions.add_parser("status", help="Show E2E workflow state")
    status.add_argument("--project", default="bg3loc-project.json")
    status.set_defaults(handler=run_status)


def run_prepare_command(args: argparse.Namespace) -> int:
    try:
        config = load_project_config(Path(args.project))
        state = run_prepare(config)
    except ProjectConfigError as exc:
        raise BG3LocError(71, "PROJECT_CONFIG_INVALID", str(exc)) from exc
    except WorkflowPrepareError as exc:
        raise BG3LocError(73, "WORKFLOW_PREPARE_FAILED", f"stage={exc.stage}: {exc.message}") from exc
    print("Workflow prepare PASS")
    print(f"Package: {state['artifacts'].get('translationPackage')}")
    print("Next: external translation")
    return 0


def run_review_prepare_command(args: argparse.Namespace) -> int:
    try:
        config = load_project_config(Path(args.project))
        result = prepare_reviews(config, args.input)
    except ProjectConfigError as exc:
        raise BG3LocError(71, "PROJECT_CONFIG_INVALID", str(exc)) from exc
    except (WorkflowReviewError, WorkflowValidateError) as exc:
        stage = getattr(exc, "stage", "review")
        message = getattr(exc, "message", str(exc))
        raise BG3LocError(74, "WORKFLOW_REVIEW_BLOCKED", f"stage={stage}: {message}") from exc
    print("Workflow review prepare PASS")
    print(f"Stage: {result['stage']}")
    if result.get("path"):
        print(f"Review workspace: {result['path']}")
    return 0


def run_review_integrate_command(args: argparse.Namespace) -> int:
    try:
        config = load_project_config(Path(args.project))
        result = integrate_reviews(config)
    except ProjectConfigError as exc:
        raise BG3LocError(71, "PROJECT_CONFIG_INVALID", str(exc)) from exc
    except WorkflowReviewError as exc:
        raise BG3LocError(74, "WORKFLOW_REVIEW_BLOCKED", f"stage={exc.stage}: {exc.message}") from exc
    if result["status"] != "passed":
        stage = result.get("stage", "review")
        path = result.get("path")
        suffix = f" Review workspace: {path}" if path else ""
        raise BG3LocError(74, "WORKFLOW_REVIEW_BLOCKED", f"stage={stage}: review work remains.{suffix}")
    print("Workflow review integrate PASS")
    print(f"Integration: {result['path']}")
    print(f"Final target: {result['finalTarget']}")
    return 0



def run_review_resolve_command(args: argparse.Namespace) -> int:
    try:
        config = load_project_config(Path(args.project))
        result = record_manual_resolutions(config, Path(args.input))
    except ProjectConfigError as exc:
        raise BG3LocError(71, "PROJECT_CONFIG_INVALID", str(exc)) from exc
    except WorkflowReviewError as exc:
        raise BG3LocError(74, "WORKFLOW_REVIEW_BLOCKED", f"stage={exc.stage}: {exc.message}") from exc
    print("Workflow review resolve PASS")
    print(f"Stage: {result['stage']}")
    print(f"Recorded: {result['recordCount']}")
    print(f"Resolutions: {result['path']}")
    print("Next: rerun bg3loc workflow validate")
    return 0

def run_validate_command(args: argparse.Namespace) -> int:
    try:
        config = load_project_config(Path(args.project))
        result = run_validate(config, args.input)
    except ProjectConfigError as exc:
        raise BG3LocError(71, "PROJECT_CONFIG_INVALID", str(exc)) from exc
    except WorkflowValidateError as exc:
        raise BG3LocError(75, "WORKFLOW_VALIDATE_FAILED", f"stage={exc.stage}: {exc.message}") from exc
    if result["status"] == "blocked":
        raise BG3LocError(74, "WORKFLOW_REVIEW_BLOCKED", f"stage={result['blockingStage']}: {result['message']}")
    if result["status"] != "pass":
        raise BG3LocError(75, "WORKFLOW_VALIDATE_FAILED", f"{result['errorCount']} validation error(s)")
    print("Workflow validate PASS")
    print(f"Accepted records: {result['acceptedRecordCount']}")
    print(f"Manifest: {result['validateManifest']}")
    return 0


def run_rebuild_command(args: argparse.Namespace) -> int:
    try:
        config = load_project_config(Path(args.project))
        result = run_workflow_rebuild(config)
    except ProjectConfigError as exc:
        raise BG3LocError(71, "PROJECT_CONFIG_INVALID", str(exc)) from exc
    except WorkflowRebuildError as exc:
        raise BG3LocError(76, "WORKFLOW_REBUILD_FAILED", exc.message) from exc
    artifacts = result.get("artifacts", [])
    print("Workflow rebuild PASS")
    if artifacts:
        print(f"Artifact: {artifacts[-1].get('path')}")
    return 0


def run_install_command(args: argparse.Namespace) -> int:
    try:
        config = load_project_config(Path(args.project))
        result = run_workflow_install(config, apply=bool(args.apply))
    except ProjectConfigError as exc:
        raise BG3LocError(71, "PROJECT_CONFIG_INVALID", str(exc)) from exc
    except WorkflowInstallError as exc:
        raise BG3LocError(77, "WORKFLOW_INSTALL_FAILED", exc.message) from exc
    if args.apply:
        print("Workflow install PASS")
        deployment = result.get("deployment", [])
        if deployment:
            print(f"Installed: {deployment[0].get('destination')}")
    else:
        print("Workflow install dry-run PASS")
        print(f"Target: {result['preflight']['destination']}")
        print("Game modified: no")
    return 0


def run_status(args: argparse.Namespace) -> int:
    try:
        config = load_project_config(Path(args.project))
    except ProjectConfigError as exc:
        raise BG3LocError(71, "PROJECT_CONFIG_INVALID", str(exc)) from exc
    path = state_path(config)
    if not path.is_file():
        print("Workflow status: not started")
        print(f"Project: {config.effective['project']['name']}")
        print(f"State: {path}")
        return 0
    try:
        state = load_state(path)
    except Exception as exc:
        raise BG3LocError(72, "WORKFLOW_STATE_INVALID", str(exc)) from exc

    if state.get("projectConfigSha256") != config.sha256:
        print("Workflow status: invalidated")
        print(f"Project: {config.effective['project']['name']}")
        print("Reason: project config changed since this workflow state was created")
        print("Next: bg3loc workflow prepare")
        return 0

    print(f"Workflow status: {state['currentStage']}")
    print(f"Project: {config.effective['project']['name']}")
    print(
        "Profile: "
        f"{state['evidenceProfile']} | Strategy: {state['translationStrategy']}"
    )
    blocking = [
        stage
        for stage, item in state["stages"].items()
        if item.get("status") == "blocked"
    ]
    if blocking:
        print(f"Blocking stage: {blocking[0]}")
    for stage, item in state["stages"].items():
        print(f"{stage}: {item['status']}")

    artifacts = state.get("artifacts", {})
    for label, key in (
        ("Package", "translationPackage"),
        ("Validation", "validateManifest"),
        ("Rebuild", "rebuildManifest"),
        ("Install dry-run", "installDryRun"),
        ("Install", "installManifest"),
    ):
        value = artifacts.get(key)
        print(f"{label}: {value if value else 'not available'}")
    return 0
