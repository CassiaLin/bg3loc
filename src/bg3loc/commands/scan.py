from __future__ import annotations

import argparse
from pathlib import Path

from bg3loc.errors import BG3LocError
from bg3loc.io import write_json
from bg3loc.scanner import ScanFailure, ScanRequest, build_manifest
from bg3loc.schema import SchemaStore


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser("scan", help="Discover BG3 installation and localization resources")
    p.add_argument("--game-dir")
    p.add_argument("--steam-library")
    p.add_argument("--platform", choices=["auto", "windows", "linux", "macos"], default="auto")
    p.add_argument("--backend", default="auto")
    p.add_argument("--output", default="workspace")
    p.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    request = ScanRequest(
        game_dir=Path(args.game_dir) if args.game_dir else None,
        steam_library=Path(args.steam_library) if args.steam_library else None,
        platform=args.platform,
        backend=args.backend,
    )
    try:
        manifest = build_manifest(request)
    except ScanFailure as exc:
        raise BG3LocError(exc.exit_code, exc.key, exc.message) from exc

    try:
        SchemaStore().validate("scan.schema.json", manifest)
    except Exception as exc:
        raise BG3LocError(7, "LOCALIZATION_DISCOVERY_ERROR", f"Generated scan manifest failed schema validation: {exc}") from exc

    output_dir = Path(args.output)
    output_file = output_dir / "scan-manifest.json"
    write_json(output_file, manifest)
    ready_count = sum(1 for item in manifest.get("locales", []) if item.get("status") == "ready")
    warning_count = len(manifest.get("warnings", []))
    print("Scan PASS")
    print(f"Install: {manifest['game']['installPath']}")
    print(f"Locales: {ready_count} ready, {warning_count} warning | Manifest: {output_file}")
    return 0
