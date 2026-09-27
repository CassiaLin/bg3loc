from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(slots=True)
class Logger:
    verbose: bool = False

    def info(self, message: str) -> None:
        print(message)

    def debug(self, message: str) -> None:
        if self.verbose:
            print(message, file=sys.stderr)

    def error(self, message: str) -> None:
        print(message, file=sys.stderr)
