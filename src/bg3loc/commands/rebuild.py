from __future__ import annotations

import argparse
from pathlib import Path

from bg3loc.rebuilder import RebuildFailure, RebuildRequest, run_rebuild


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser("rebuild", help="Rebuild validated localization artifacts")
    p.add_argument("--validate", default="workspace/validate/validate-manifest.json")
    p.add_argument("--extract", default="workspace/extract/extract-manifest.json")
    p.add_argument("--container", choices=["auto", "loca-only", "repack"], default="auto")
    p.add_argument("--backend", default="auto")
    p.add_argument("--output", default="workspace/rebuild")
    p.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    request = RebuildRequest(
        validate_manifest=Path(args.validate),
        extract_manifest=Path(args.extract),
        container=args.container,
        backend=args.backend,
        output=Path(args.output),
    )
    try:
        manifest = run_rebuild(request)
    except RebuildFailure as exc:
        from bg3loc.errors import BG3LocError
        raise BG3LocError(exc.exit_code, exc.key, exc.message) from exc
    artifacts = list(manifest.get("artifacts", []))
    artifact = next((item for item in artifacts if item.get("type") == "pak"), artifacts[0] if artifacts else None)
    print("Rebuild PASS")
    if artifact is not None:
        print(f"Artifact: {artifact['path']} | SHA256: {artifact['sha256']}")
    print(f"Manifest: {request.output / 'rebuild-manifest.json'}")
    return 0
