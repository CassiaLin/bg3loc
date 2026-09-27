from __future__ import annotations

import argparse

from bg3loc.errors import NotImplementedCommandError


def run_not_implemented(args: argparse.Namespace) -> int:
    raise NotImplementedCommandError(args.command)
