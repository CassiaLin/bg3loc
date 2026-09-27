from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppConfig:
    workspace: Path = Path("workspace")
    schemas: Path = Path("schemas")
    verbose: bool = False
