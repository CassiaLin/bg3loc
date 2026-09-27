from __future__ import annotations

import argparse
from pathlib import Path

from bg3loc.builder import BuildFailure, BuildRequest, run_build


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser("build", help="Generate translation materials")
    p.add_argument("--extract", default="workspace/extract/extract-manifest.json")
    p.add_argument("--mode", choices=["basic", "context", "blind-first"], default="basic")
    p.add_argument("--format", choices=["xlsx", "csv", "jsonl"], default="xlsx")
    p.add_argument("--max-rows", type=int, default=1500)
    p.add_argument("--context")
    p.add_argument("--glossary")
    p.add_argument("--output", default="workspace/build")
    p.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    request = BuildRequest(
        extract_manifest=Path(args.extract),
        mode=args.mode,
        format=args.format,
        max_rows=args.max_rows,
        context=Path(args.context) if args.context else None,
        glossary=Path(args.glossary) if args.glossary else None,
        output=Path(args.output),
    )
    try:
        manifest = run_build(request)
    except BuildFailure as exc:
        from bg3loc.errors import BG3LocError
        raise BG3LocError(exc.exit_code, exc.key, exc.message) from exc
    row_count = sum(int(item.get("recordCount", 0)) for item in manifest.get("materials", []))
    print("Build PASS")
    print(f"Mode: {manifest['mode']} | format: {manifest['format']} | rows: {row_count} | batches: {len(manifest.get('materials', []))}")
    print(f"Manifest: {request.output / 'build-manifest.json'}")
    return 0
