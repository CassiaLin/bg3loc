from __future__ import annotations

import hashlib
import os
import platform as py_platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bg3loc.backends import ArchiveBackend, ArchiveBackendError, backend_from_probe, backend_manifest, resolve_backend
from bg3loc.steam import (
    default_steam_roots,
    discover_library_roots,
    read_app_manifest_for_game_dir,
    resolve_bg3_install,
)


@dataclass(frozen=True, slots=True)
class ScanRequest:
    game_dir: Path | None = None
    steam_library: Path | None = None
    platform: str = "auto"
    backend: str = "auto"


class ScanFailure(RuntimeError):
    def __init__(self, exit_code: int, key: str, message: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.key = key
        self.message = message


def detect_platform(requested: str) -> str:
    if requested != "auto":
        return requested
    system = py_platform.system().lower()
    if system == "windows":
        return "windows"
    if system == "darwin":
        return "macos"
    return "linux"


def discover_game(request: ScanRequest) -> tuple[Path, dict[str, str] | None, str]:
    if request.game_dir is not None:
        game_dir = request.game_dir.expanduser().resolve(strict=False)
        if not game_dir.is_dir():
            raise ScanFailure(2, "GAME_NOT_FOUND", f"Game directory does not exist: {game_dir}")
        steam_manifest = read_app_manifest_for_game_dir(game_dir)
        if request.steam_library is not None:
            library_match = resolve_bg3_install(request.steam_library.expanduser())
            if (
                library_match is None
                or str(library_match[0].resolve(strict=False)).casefold() != str(game_dir).casefold()
            ):
                raise ScanFailure(
                    5,
                    "INSTALLATION_IDENTITY_MISMATCH",
                    "--game-dir and --steam-library do not identify the same BG3 installation.",
                )
            steam_manifest = library_match[1]
        return game_dir, steam_manifest, "explicit"

    roots: list[Path] = []
    if request.steam_library is not None:
        roots.append(request.steam_library.expanduser())
    else:
        for steam_root in default_steam_roots():
            roots.extend(discover_library_roots(steam_root))

    matches: list[tuple[Path, dict[str, str]]] = []
    for library in roots:
        resolved = resolve_bg3_install(library)
        if resolved is not None:
            matches.append(resolved)

    unique: dict[str, tuple[Path, dict[str, str]]] = {}
    for game_dir, manifest in matches:
        unique[str(game_dir.resolve(strict=False)).casefold()] = (game_dir, manifest)

    if not unique:
        raise ScanFailure(2, "GAME_NOT_FOUND", "Unable to locate a Steam installation of Baldur's Gate 3.")
    if len(unique) > 1:
        paths = ", ".join(str(item[0]) for item in unique.values())
        raise ScanFailure(5, "AMBIGUOUS_INSTALLATION", f"Multiple BG3 installations found: {paths}")

    game_dir, manifest = next(iter(unique.values()))
    return game_dir.resolve(strict=False), manifest, "steam"


def resolve_data_dir(game_dir: Path) -> Path:
    direct = game_dir / "Data"
    if direct.is_dir():
        return direct

    candidates = [p for p in game_dir.rglob("Data") if p.is_dir()]
    if len(candidates) == 1:
        return candidates[0]
    raise ScanFailure(3, "DATA_DIRECTORY_NOT_FOUND", f"Unable to resolve BG3 Data directory under: {game_dir}")


def discover_locale_packages(data_dir: Path) -> list[dict[str, Any]]:
    localization_roots = sorted(
        (
            path
            for path in data_dir.iterdir()
            if path.name.casefold() == "localization" and path.is_dir() and not path.is_symlink()
        ),
        key=lambda path: str(path).casefold(),
    )

    package_files: list[Path] = []
    for root in localization_roots:
        package_files.extend(_safe_recursive_packages(root))

    deduped: dict[str, Path] = {}
    for path in package_files:
        deduped[str(path.resolve(strict=False)).casefold()] = path
    package_files = sorted(deduped.values(), key=lambda p: p.name.casefold())

    if not package_files:
        raise ScanFailure(4, "NO_LOCALIZATION_RESOURCES", f"No localization PAK files found under: {data_dir}")

    grouped: dict[str, list[Path]] = {}
    for path in package_files:
        locale_id = path.stem
        grouped.setdefault(locale_id.casefold(), []).append(path)

    locales: list[dict[str, Any]] = []
    for paths in grouped.values():
        status = "ambiguous" if len(paths) > 1 else "ready"
        for path in paths:
            locales.append({
                "localeId": path.stem,
                "packageFile": str(path.resolve(strict=False)),
                "packageSha256": sha256_file(path),
                "locaEntries": [],
                "status": status,
            })
    return locales


def _safe_recursive_packages(root: Path) -> list[Path]:
    resolved_root = root.resolve(strict=True)
    packages: list[Path] = []
    for current, directory_names, file_names in os.walk(resolved_root, followlinks=False):
        current_path = Path(current)
        directory_names[:] = sorted(
            (name for name in directory_names if not (current_path / name).is_symlink()),
            key=str.casefold,
        )
        for name in sorted(file_names, key=str.casefold):
            candidate = current_path / name
            if candidate.suffix.casefold() != ".pak" or candidate.is_symlink() or not candidate.is_file():
                continue
            resolved = candidate.resolve(strict=True)
            try:
                resolved.relative_to(resolved_root)
            except ValueError:
                continue
            packages.append(resolved)
    return packages


def inspect_loca_entries(locales: list[dict[str, Any]], backend: ArchiveBackend) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for locale in locales:
        package = Path(str(locale["packageFile"]))
        try:
            entries = backend.list_archive(package, "*.loca")
        except ArchiveBackendError as exc:
            locale["status"] = "error"
            warnings.append({
                "code": "ARCHIVE_LIST_FAILED",
                "message": f"{package.name}: {exc}",
            })
            continue

        locale["locaEntries"] = [
            {"path": entry.path, "size": entry.size, "crc": entry.crc}
            for entry in entries
        ]
        if not entries:
            locale["status"] = "unsupported"
            warnings.append({
                "code": "NO_LOCA_ENTRY",
                "message": f"No .loca entry found in {package.name}",
            })
            continue

        discovered_ids = _locale_ids_from_entries(entries)
        if len(discovered_ids) == 1:
            locale["localeId"] = discovered_ids[0]
            locale["status"] = "ready"
        elif not discovered_ids:
            locale["status"] = "unsupported"
            warnings.append({
                "code": "NO_VALID_LOCALE_RESOURCE",
                "message": f"No BG3 localization resource path found in {package.name}",
            })
        else:
            locale["status"] = "ambiguous"
            warnings.append({
                "code": "AMBIGUOUS_LOCALE_RESOURCE",
                "message": f"Multiple locale identities found in {package.name}: {', '.join(discovered_ids)}",
            })

    _mark_duplicate_locale_providers(locales)
    return warnings


def _locale_ids_from_entries(entries: list[Any]) -> list[str]:
    locale_ids: dict[str, str] = {}
    for entry in entries:
        parts = str(entry.path).replace("\\", "/").split("/")
        if len(parts) < 3 or parts[0].casefold() != "localization" or not parts[-1].casefold().endswith(".loca"):
            continue
        locale_id = parts[1]
        if locale_id:
            locale_ids.setdefault(locale_id.casefold(), locale_id)
    return [locale_ids[key] for key in sorted(locale_ids)]


def _mark_duplicate_locale_providers(locales: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for locale in locales:
        if locale.get("status") in {"ready", "ambiguous"}:
            grouped.setdefault(str(locale["localeId"]).casefold(), []).append(locale)
    for providers in grouped.values():
        if len(providers) > 1:
            for provider in providers:
                provider["status"] = "ambiguous"


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(request: ScanRequest) -> dict[str, Any]:
    os_name = detect_platform(request.platform)
    game_dir, steam_manifest, install_kind = discover_game(request)
    data_dir = resolve_data_dir(game_dir)
    locales = discover_locale_packages(data_dir)

    probe = resolve_backend(request.backend)
    if not probe.available:
        raise ScanFailure(
            6,
            "BACKEND_UNAVAILABLE",
            probe.reason or f"Archive backend is unavailable: {probe.id}",
        )
    backend = backend_from_probe(probe)
    if backend is None:
        raise ScanFailure(6, "BACKEND_UNAVAILABLE", f"Archive backend is unavailable: {probe.id}")
    warnings = inspect_loca_entries(locales, backend)

    build_id = steam_manifest.get("buildid") if steam_manifest else None
    return {
        "schemaVersion": "1.0",
        "game": {
            "id": "bg3",
            "appId": 1086940,
            "installPath": str(game_dir),
            "dataPath": str(data_dir.resolve(strict=False)),
            "buildId": build_id,
            "gameVersion": None,
        },
        "platform": {
            "os": os_name,
            "installKind": install_kind,
        },
        "backend": backend_manifest(probe),
        "locales": locales,
        "warnings": warnings,
    }
