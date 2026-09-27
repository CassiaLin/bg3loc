from __future__ import annotations

import argparse
from pathlib import Path

from bg3loc.extractor import ExtractFailure, ExtractRequest, run_extract


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser("extract", help="Extract and normalize selected localization resources")
    p.add_argument("--scan", default="workspace/scan-manifest.json")
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--reference", action="append", default=[])
    p.add_argument("--output", default="workspace/extract")
    p.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    request = ExtractRequest(
        scan_manifest=Path(args.scan),
        source=args.source,
        target=args.target,
        references=tuple(args.reference),
        output=Path(args.output),
    )
    try:
        manifest = run_extract(request)
    except ExtractFailure as exc:
        from bg3loc.errors import BG3LocError
        raise BG3LocError(exc.exit_code, exc.key, exc.message) from exc
    locale_counts = " | ".join(
        f"{item['localeId']}: {item['nodeCount']}"
        for item in manifest.get("locales", [])
    )
    print("Extract PASS")
    print(f"Locales: {locale_counts}")
    print(f"Manifest: {request.output / 'extract-manifest.json'}")
    return 0
