from __future__ import annotations

import os
import re
import sys
from pathlib import Path

APP_ID = "1086940"

_PAIR_RE = re.compile(r'^\s*"([^"]+)"\s+"([^"]*)"\s*$')


def parse_vdf_pairs(text: str) -> dict[str, str]:
    """Parse flat quoted key/value pairs used by appmanifest metadata."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        match = _PAIR_RE.match(line)
        if match:
            result[match.group(1)] = _decode_vdf_value(match.group(2))
    return result


def iter_vdf_values(text: str, wanted_key: str) -> list[str]:
    """Return every value for a repeated VDF key, preserving file order."""
    values: list[str] = []
    for line in text.splitlines():
        match = _PAIR_RE.match(line)
        if match and match.group(1) == wanted_key:
            values.append(_decode_vdf_value(match.group(2)))
    return values


def default_steam_roots(platform_name: str | None = None) -> list[Path]:
    platform_name = platform_name or sys.platform
    home = Path.home()
    roots: list[Path] = []

    if platform_name.startswith("win"):
        for env_name in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
            value = os.environ.get(env_name)
            if value:
                roots.append(Path(value) / "Steam")
    elif platform_name == "darwin":
        roots.append(home / "Library" / "Application Support" / "Steam")
    else:
        roots.extend([
            home / ".steam" / "steam",
            home / ".local" / "share" / "Steam",
        ])

    return _dedupe_paths(roots)


def discover_library_roots(steam_root: Path) -> list[Path]:
    libraries = [steam_root]
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    if not vdf.is_file():
        return _dedupe_paths(libraries)

    text = vdf.read_text(encoding="utf-8", errors="replace")
    libraries.extend(Path(value) for value in iter_vdf_values(text, "path"))
    return _dedupe_paths(libraries)


def read_app_manifest(library_root: Path) -> dict[str, str] | None:
    manifest = library_root / "steamapps" / f"appmanifest_{APP_ID}.acf"
    if not manifest.is_file():
        return None
    pairs = parse_vdf_pairs(manifest.read_text(encoding="utf-8", errors="replace"))
    return pairs if pairs.get("appid") == APP_ID else None


def resolve_bg3_install(library_root: Path) -> tuple[Path, dict[str, str]] | None:
    manifest = read_app_manifest(library_root)
    if manifest is None:
        return None
    install_dir = manifest.get("installdir")
    if not install_dir:
        return None
    game_dir = library_root / "steamapps" / "common" / install_dir
    if not game_dir.is_dir():
        return None
    return game_dir, manifest


def read_app_manifest_for_game_dir(game_dir: Path) -> dict[str, str] | None:
    """Recover Steam metadata only when *game_dir* proves a standard layout."""
    resolved_game = game_dir.expanduser().resolve(strict=False)
    common_dir = resolved_game.parent
    steamapps_dir = common_dir.parent
    if common_dir.name.casefold() != "common" or steamapps_dir.name.casefold() != "steamapps":
        return None

    manifest = read_app_manifest(steamapps_dir.parent)
    if manifest is None:
        return None
    install_dir = manifest.get("installdir")
    if not install_dir:
        return None

    manifest_game = (steamapps_dir / "common" / install_dir).resolve(strict=False)
    if str(manifest_game).casefold() != str(resolved_game).casefold():
        return None
    return manifest


def _decode_vdf_value(value: str) -> str:
    return value.replace("\\\\", "\\")


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path.expanduser().resolve(strict=False)).casefold()
        if key not in seen:
            seen.add(key)
            result.append(path.expanduser())
    return result
