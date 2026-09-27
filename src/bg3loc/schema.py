from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


class SchemaStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_schema_root()

    def load(self, name: str) -> dict[str, Any]:
        path = self.root / name
        with path.open("r", encoding="utf-8") as f:
            schema = json.load(f)
        if not isinstance(schema, dict):
            raise ValueError(f"Schema must be a JSON object: {path}")
        Draft202012Validator.check_schema(schema)
        return schema

    def validate(self, name: str, instance: Any) -> None:
        schema = self.load(name)
        Draft202012Validator(schema).validate(instance)


def default_schema_root() -> Path:
    override = os.environ.get("BG3LOC_SCHEMA_DIR")
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_dir():
            return candidate.resolve()
        raise FileNotFoundError(f"BG3LOC_SCHEMA_DIR is not a directory: {candidate}")

    candidates = [
        Path.cwd() / "schemas",
        Path(__file__).resolve().parents[2] / "schemas",
        Path(sys.prefix) / "share" / "bg3loc" / "schemas",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    searched = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(f"Unable to locate BG3Loc schemas; searched: {searched}")
