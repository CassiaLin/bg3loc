from __future__ import annotations

import argparse
from collections.abc import Sequence

from bg3loc import __version__
from bg3loc.commands import build, extract, install, production, project, rebuild, research, review, scan, translation_qa, translation_state, validate, workflow
from bg3loc.errors import BG3LocError
from bg3loc.logging import Logger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bg3loc",
        description="Cross-platform Baldur's Gate 3 localization pipeline",
        epilog=(
            "Start with 'bg3loc scan --help' for a game installation, or "
            "'bg3loc production --help' for a resumable translation project. "
            "See docs/getting-started.md for a complete example."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable diagnostic output")

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    for module in (scan, extract, build, validate, rebuild, install, research, review, project, workflow, translation_state, translation_qa, production):
        module.register(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logger = Logger(verbose=args.verbose)
    try:
        return int(args.handler(args))
    except BG3LocError as exc:
        logger.error(str(exc))
        return exc.code


if __name__ == "__main__":
    raise SystemExit(main())
