from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bg3loc.schema import SchemaStore


class ProjectConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedProjectConfig:
    source_path: Path
    raw: dict[str, Any]
    effective: dict[str, Any]
    resolved: dict[str, Any]
    sha256: str


_DEFAULTS: dict[str, Any] = {
    "game": {"installDir": None},
    "locales": {"references": []},
    "reviews": {"structural": "profile-default"},
    "qa": {"ruleSets": []},
    "inputs": {"glossary": None},
    "material": {"format": "xlsx", "maxRowsPerFile": 1500},
    "scope": {"contentUids": None},
    "workspace": {"root": "workspace"},
}


def load_project_config(path: Path) -> ResolvedProjectConfig:
    source = path.expanduser().resolve(strict=False)
    if not source.is_file():
        raise ProjectConfigError(f"Project config not found: {source}")
    try:
        with source.open("r", encoding="utf-8-sig") as stream:
            raw = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectConfigError(f"Unable to read project config: {exc}") from exc
    if not isinstance(raw, dict):
        raise ProjectConfigError("Project config must be a JSON object")
    try:
        SchemaStore().validate("project-config.schema.json", raw)
    except Exception as exc:
        raise ProjectConfigError(f"Project config schema validation failed: {exc}") from exc

    effective = _apply_defaults(raw)
    _semantic_validate(effective)
    resolved = _resolve_paths(effective, source.parent)
    canonical = json.dumps(resolved, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return ResolvedProjectConfig(
        source_path=source,
        raw=raw,
        effective=effective,
        resolved=resolved,
        sha256=hashlib.sha256(canonical).hexdigest(),
    )


def _apply_defaults(raw: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(raw, ensure_ascii=False))
    for section, defaults in _DEFAULTS.items():
        current = value.setdefault(section, {})
        if not isinstance(current, dict):
            raise ProjectConfigError(f"Project config section must be an object: {section}")
        for key, default in defaults.items():
            if key not in current:
                current[key] = json.loads(json.dumps(default))
    return value


def _semantic_validate(config: dict[str, Any]) -> None:
    locales = config["locales"]
    source = str(locales["source"]).strip()
    target = str(locales["target"]).strip()
    if source.casefold() == target.casefold():
        raise ProjectConfigError("Source and target locales must be different")

    seen: set[str] = set()
    for item in locales.get("references", []):
        text = str(item).strip()
        folded = text.casefold()
        if folded in seen:
            raise ProjectConfigError(f"Duplicate reference locale: {text}")
        if folded in {source.casefold(), target.casefold()}:
            raise ProjectConfigError(f"Reference locale duplicates source/target: {text}")
        seen.add(folded)

    profile = str(config["workflow"]["evidenceProfile"])
    structural = config["reviews"].get("structural", "profile-default")
    if isinstance(structural, list):
        if len({str(item).casefold() for item in structural}) != len(structural):
            raise ProjectConfigError("Duplicate structural review ID")
        if structural and profile != "full":
            raise ProjectConfigError("Explicit structural reviews require evidenceProfile=full")

    scope_uids = config["scope"].get("contentUids")
    if scope_uids is not None:
        if profile == "full":
            raise ProjectConfigError(
                "Scoped ContentUid projects currently support evidenceProfile=basic or context"
            )
        normalized_scope = [str(item).strip() for item in scope_uids]
        if any(not item for item in normalized_scope):
            raise ProjectConfigError("Scoped ContentUid values must be non-empty")
        if len(set(normalized_scope)) != len(normalized_scope):
            raise ProjectConfigError("Duplicate scoped ContentUid")

    qa_ids: set[str] = set()
    for item in config["qa"].get("ruleSets", []):
        ident = str(item["id"]).casefold()
        if ident in qa_ids:
            raise ProjectConfigError(f"Duplicate QA rule-set id: {item['id']}")
        qa_ids.add(ident)


def _resolve_paths(config: dict[str, Any], base: Path) -> dict[str, Any]:
    value = json.loads(json.dumps(config, ensure_ascii=False))

    def resolve_optional(raw: str | None) -> str | None:
        if raw is None:
            return None
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = base / candidate
        return str(candidate.resolve(strict=False))

    value["game"]["installDir"] = resolve_optional(value["game"].get("installDir"))
    value["inputs"]["glossary"] = resolve_optional(value["inputs"].get("glossary"))
    value["workspace"]["root"] = resolve_optional(value["workspace"]["root"])
    for item in value["qa"].get("ruleSets", []):
        item["path"] = resolve_optional(item["path"])
    return value


def profile_default_reviews(profile: str) -> list[str]:
    if profile == "full":
        return ["bark", "quest", "ui-skill", "multilingual"]
    return []


def resolved_structural_reviews(config: ResolvedProjectConfig) -> list[str]:
    raw = config.effective["reviews"]["structural"]
    if raw == "profile-default":
        return profile_default_reviews(str(config.effective["workflow"]["evidenceProfile"]))
    return [str(item) for item in raw]
