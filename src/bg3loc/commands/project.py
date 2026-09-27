from __future__ import annotations

import argparse
import json
from pathlib import Path

from bg3loc.e2e.config import ProjectConfigError, load_project_config
from bg3loc.errors import BG3LocError
from bg3loc.io import write_json


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    project = subparsers.add_parser("project", help="E2E project configuration commands")
    actions = project.add_subparsers(dest="project_action", required=True)

    init = actions.add_parser("init", help="Create a new bg3loc-project.json")
    init.add_argument("--name", required=True)
    init.add_argument("--source", required=True)
    init.add_argument("--target", required=True)
    init.add_argument("--game-dir")
    init.add_argument("--reference", action="append", default=[])
    init.add_argument("--content-uid", action="append", default=[])
    init.add_argument(
        "--evidence-profile", "--profile",
        dest="evidence_profile",
        choices=["basic", "context", "full"],
        default="basic",
    )
    init.add_argument(
        "--translation-strategy", "--strategy",
        dest="translation_strategy",
        choices=["standard", "blind-first"],
        default="standard",
    )
    init.add_argument("--format", choices=["xlsx", "csv", "jsonl"], default="xlsx")
    init.add_argument("--workspace", default="workspace")
    init.add_argument("--output", default="bg3loc-project.json")
    init.set_defaults(handler=run_init)

    check = actions.add_parser("check", help="Validate and resolve a project config")
    check.add_argument("--project", default="bg3loc-project.json")
    check.set_defaults(handler=run_check)


def run_init(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser().resolve(strict=False)
    if output.exists():
        raise BG3LocError(71, "PROJECT_CONFIG_EXISTS", f"Refusing to overwrite existing project config: {output}")

    config = {
        "schemaVersion": "1.0",
        "project": {"name": args.name},
        "game": {"installDir": args.game_dir or None},
        "locales": {
            "source": args.source,
            "target": args.target,
            "references": list(args.reference),
        },
        "workflow": {
            "evidenceProfile": args.evidence_profile,
            "translationStrategy": args.translation_strategy,
        },
        "reviews": {"structural": "profile-default"},
        "qa": {"ruleSets": []},
        "inputs": {"glossary": None},
        "material": {"format": args.format, "maxRowsPerFile": 1500},
        "scope": {"contentUids": list(args.content_uid) if args.content_uid else None},
        "workspace": {"root": args.workspace},
    }
    write_json(output, config)
    try:
        resolved = load_project_config(output)
    except ProjectConfigError as exc:
        output.unlink(missing_ok=True)
        raise BG3LocError(71, "PROJECT_CONFIG_INVALID", str(exc)) from exc

    print("Project init PASS")
    print(f"Config: {output}")
    print(f"Profile: {resolved.effective['workflow']['evidenceProfile']} | Strategy: {resolved.effective['workflow']['translationStrategy']}")
    scope_uids = resolved.effective["scope"].get("contentUids")
    print(f"Scope: {'all' if scope_uids is None else f'{len(scope_uids)} ContentUid(s)'}")
    return 0


def run_check(args: argparse.Namespace) -> int:
    try:
        config = load_project_config(Path(args.project))
    except ProjectConfigError as exc:
        raise BG3LocError(71, "PROJECT_CONFIG_INVALID", str(exc)) from exc
    print("Project check PASS")
    print(f"Project: {config.effective['project']['name']}")
    print(f"Locales: {config.effective['locales']['source']} -> {config.effective['locales']['target']}")
    print(f"Profile: {config.effective['workflow']['evidenceProfile']} | Strategy: {config.effective['workflow']['translationStrategy']}")
    scope_uids = config.effective["scope"].get("contentUids")
    print(f"Scope: {'all' if scope_uids is None else f'{len(scope_uids)} ContentUid(s)'}")
    print(f"Resolved SHA256: {config.sha256}")
    print(json.dumps(config.resolved, ensure_ascii=False, indent=2))
    return 0
