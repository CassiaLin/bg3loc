from __future__ import annotations

import argparse
from pathlib import Path

from bg3loc.validator import ValidateFailure, ValidateRequest, run_validate


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser("validate", help="Validate returned translation materials")
    p.add_argument("--build", default="workspace/build/build-manifest.json")
    p.add_argument("--input", required=True)
    p.add_argument("--strict", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--output", default="workspace/validate")
    p.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    request = ValidateRequest(
        build_manifest=Path(args.build),
        input_spec=args.input,
        strict=bool(args.strict),
        output=Path(args.output),
    )
    try:
        manifest = run_validate(request)
    except ValidateFailure as exc:
        from bg3loc.errors import BG3LocError
        raise BG3LocError(exc.exit_code, exc.key, exc.message) from exc
    summary = manifest["summary"]
    print(f"Validate {str(summary['status']).upper()}")
    print(
        f"Accepted: {manifest['accepted']['recordCount']} | rejected: {manifest['rejected']['recordCount']} | "
        f"errors: {summary['errorCount']} | warnings: {summary['warningCount']} | "
        f"missing from return: {summary['missingReturnRowCount']}"
    )
    print(f"Manifest: {request.output / 'validate-manifest.json'}")
    return 0
