from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bg3loc.io import read_json, write_json
from bg3loc.schema import SchemaStore
from bg3loc.steam import parse_vdf_pairs


@dataclass(frozen=True, slots=True)
class InstallRequest:
    rebuild_manifest: Path
    scan_manifest: Path
    game_dir: Path | None = None
    backup_dir: Path = Path("workspace/backups")
    dry_run: bool = False
    rollback_manifest: Path | None = None


class InstallFailure(RuntimeError):
    def __init__(self, exit_code: int, key: str, message: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.key = key
        self.message = message


def run_install(request: InstallRequest) -> dict[str, Any]:
    if request.rollback_manifest is not None:
        return run_rollback(request.rollback_manifest)

    try:
        rebuild = read_json(request.rebuild_manifest)
        SchemaStore().validate("rebuild-manifest.schema.json", rebuild)
    except Exception as exc:
        raise InstallFailure(50, "REBUILD_MANIFEST_INVALID", str(exc)) from exc

    try:
        scan = read_json(request.scan_manifest)
        SchemaStore().validate("scan.schema.json", scan)
    except Exception as exc:
        raise InstallFailure(52, "GAME_IDENTITY_MISMATCH", f"Invalid scan manifest: {exc}") from exc

    game = scan["game"]
    if game.get("id") != "bg3" or int(game.get("appId", 0)) != 1086940:
        raise InstallFailure(52, "GAME_IDENTITY_MISMATCH", "Scan manifest is not Baldur's Gate 3 app 1086940.")

    scanned_root = Path(str(game["installPath"])).expanduser().resolve(strict=False)
    current_root = (request.game_dir or scanned_root).expanduser().resolve(strict=False)
    if not current_root.is_dir() or not (current_root / "Data").is_dir():
        raise InstallFailure(51, "GAME_INSTALL_NOT_FOUND", f"BG3 installation not found: {current_root}")

    scanned_build = _optional_text(game.get("buildId"))
    current_build = discover_build_id(current_root)
    if scanned_build is not None and current_build != scanned_build:
        raise InstallFailure(
            53,
            "BUILD_OR_BASELINE_MISMATCH",
            f"Game build changed since scan: scanned={scanned_build}, current={current_build}",
        )

    target_locale = str(rebuild["targetLocale"])
    locale = find_scan_locale(scan, target_locale)
    scanned_destination = Path(str(locale["packageFile"])).expanduser().resolve(strict=False)
    destination = remap_destination(scanned_destination, scanned_root, current_root)
    if not destination.is_file():
        raise InstallFailure(56, "DESTINATION_UNRESOLVED", f"Target localization destination is missing: {destination}")

    current_baseline_sha = sha256_file(destination)
    expected_baseline_sha = str(locale["packageSha256"]).casefold()
    if current_baseline_sha.casefold() != expected_baseline_sha:
        raise InstallFailure(
            53,
            "BUILD_OR_BASELINE_MISMATCH",
            f"Target localization baseline changed since scan: {destination}",
        )

    artifact = select_deployment_artifact(rebuild, destination)
    artifact_path = resolve_manifest_reference(str(artifact["path"]), request.rebuild_manifest.parent)
    artifact_sha = str(artifact["sha256"]).casefold()
    if sha256_file(artifact_path).casefold() != artifact_sha:
        raise InstallFailure(54, "ARTIFACT_INTEGRITY_FAILED", f"Rebuilt artifact hash mismatch: {artifact_path}")

    preflight = {
        "schemaVersion": "1.0",
        "gameRoot": str(current_root),
        "buildIdAtScan": scanned_build,
        "buildIdAtInstall": current_build,
        "targetLocale": target_locale,
        "destination": str(destination),
        "baselineSha256": current_baseline_sha,
        "artifact": str(artifact_path),
        "artifactSha256": artifact_sha,
        "dryRun": request.dry_run,
    }
    if request.dry_run:
        return {"status": "dry-run-pass", "preflight": preflight}

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = request.backup_dir.expanduser().resolve(strict=False) / f"{timestamp}-{target_locale}"
    backup_path = backup_root / safe_relative(destination, current_root)
    try:
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(destination, backup_path)
    except OSError as exc:
        raise InstallFailure(55, "BACKUP_FAILED", str(exc)) from exc
    backup_sha = sha256_file(backup_path)
    if backup_sha != current_baseline_sha:
        raise InstallFailure(55, "BACKUP_FAILED", "Backup hash does not match original destination.")

    temp_path = destination.with_name(f".{destination.name}.bg3loc-{os.getpid()}.tmp")
    try:
        shutil.copy2(artifact_path, temp_path)
        if sha256_file(temp_path).casefold() != artifact_sha:
            raise InstallFailure(57, "TEMPORARY_WRITE_FAILED", "Temporary deployment file hash mismatch.")
    except InstallFailure:
        _unlink_quietly(temp_path)
        raise
    except OSError as exc:
        _unlink_quietly(temp_path)
        raise InstallFailure(57, "TEMPORARY_WRITE_FAILED", str(exc)) from exc

    try:
        os.replace(temp_path, destination)
    except OSError as exc:
        _unlink_quietly(temp_path)
        raise InstallFailure(58, "REPLACEMENT_FAILED", str(exc)) from exc

    installed_sha = sha256_file(destination)
    if installed_sha.casefold() != artifact_sha:
        rollback_ok = restore_backup(backup_path, destination, backup_sha)
        if not rollback_ok:
            raise InstallFailure(60, "ROLLBACK_FAILED", "Post-install verification failed and automatic rollback also failed.")
        raise InstallFailure(59, "POST_INSTALL_VERIFICATION_FAILED", "Installed artifact hash mismatch; original backup was restored.")

    manifest = {
        "schemaVersion": "1.0",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "game": {
            "id": "bg3",
            "appId": 1086940,
            "installPath": str(current_root),
            "buildIdAtScan": scanned_build,
            "buildIdAtInstall": current_build,
        },
        "targetLocale": target_locale,
        "deployment": [
            {
                "artifact": str(artifact_path),
                "destination": str(destination),
                "artifactSha256": artifact_sha,
                "installedSha256": installed_sha,
                "backupPath": str(backup_path),
                "backupSha256": backup_sha,
                "status": "installed",
            }
        ],
        "rollbackAvailable": True,
    }
    try:
        SchemaStore().validate("install-manifest.schema.json", manifest)
        manifest_path = backup_root / "install-manifest.json"
        write_json(manifest_path, manifest)
        manifest["manifestPath"] = str(manifest_path)
    except Exception as exc:
        rollback_ok = restore_backup(backup_path, destination, backup_sha)
        if not rollback_ok:
            raise InstallFailure(60, "ROLLBACK_FAILED", f"Install manifest failed and rollback failed: {exc}") from exc
        raise InstallFailure(59, "POST_INSTALL_VERIFICATION_FAILED", f"Install manifest failed; original backup was restored: {exc}") from exc
    return manifest


def run_rollback(manifest_path: Path) -> dict[str, Any]:
    try:
        manifest = read_json(manifest_path)
        SchemaStore().validate("install-manifest.schema.json", manifest)
    except Exception as exc:
        raise InstallFailure(60, "ROLLBACK_FAILED", f"Invalid install manifest: {exc}") from exc

    deployment = manifest.get("deployment", [])
    if len(deployment) != 1:
        raise InstallFailure(60, "ROLLBACK_FAILED", "Install v1 rollback requires exactly one deployment record.")
    item = deployment[0]
    destination = Path(str(item["destination"])).expanduser()
    backup = Path(str(item["backupPath"])).expanduser()
    expected_backup = str(item["backupSha256"]).casefold()
    expected_installed = str(item["installedSha256"]).casefold()

    if not backup.is_file() or sha256_file(backup).casefold() != expected_backup:
        raise InstallFailure(60, "ROLLBACK_FAILED", "Backup is missing or its hash is invalid.")
    if not destination.is_file() or sha256_file(destination).casefold() != expected_installed:
        raise InstallFailure(60, "ROLLBACK_FAILED", "Current destination no longer matches the recorded installed artifact; refusing to overwrite it.")
    if not restore_backup(backup, destination, expected_backup):
        raise InstallFailure(60, "ROLLBACK_FAILED", "Unable to restore and verify backup.")

    return {
        "status": "rolled-back",
        "destination": str(destination),
        "restoredSha256": expected_backup,
        "installManifest": str(manifest_path),
    }


def select_deployment_artifact(rebuild: dict[str, Any], destination: Path) -> dict[str, Any]:
    artifacts = list(rebuild.get("artifacts", []))
    destination_suffix = destination.suffix.casefold()
    wanted_type = "pak" if destination_suffix == ".pak" else "loca" if destination_suffix == ".loca" else None
    if wanted_type is None:
        raise InstallFailure(56, "DESTINATION_UNRESOLVED", f"Unsupported localization destination type: {destination}")
    matches = [item for item in artifacts if str(item.get("type", "")).casefold() == wanted_type]
    if len(matches) != 1:
        raise InstallFailure(56, "DESTINATION_UNRESOLVED", f"Expected exactly one {wanted_type} artifact; found {len(matches)}")
    return matches[0]


def find_scan_locale(scan: dict[str, Any], locale_id: str) -> dict[str, Any]:
    matches = [item for item in scan.get("locales", []) if str(item.get("localeId", "")).casefold() == locale_id.casefold()]
    if len(matches) != 1:
        raise InstallFailure(56, "DESTINATION_UNRESOLVED", f"Expected exactly one scan locale for {locale_id}; found {len(matches)}")
    if matches[0].get("status") != "ready":
        raise InstallFailure(56, "DESTINATION_UNRESOLVED", f"Target locale is not ready in scan manifest: {locale_id}")
    return matches[0]


def remap_destination(scanned_destination: Path, scanned_root: Path, current_root: Path) -> Path:
    try:
        relative = scanned_destination.relative_to(scanned_root)
    except ValueError as exc:
        raise InstallFailure(56, "DESTINATION_UNRESOLVED", "Scanned localization path is outside the scanned game root.") from exc
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise InstallFailure(56, "DESTINATION_UNRESOLVED", "Unsafe destination relative path.")
    return current_root.joinpath(*relative.parts)


def safe_relative(path: Path, root: Path) -> Path:
    try:
        relative = path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise InstallFailure(56, "DESTINATION_UNRESOLVED", f"Destination is outside game root: {path}") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise InstallFailure(56, "DESTINATION_UNRESOLVED", f"Unsafe destination path: {path}")
    return relative


def discover_build_id(game_root: Path) -> str | None:
    steamapps = game_root.parent.parent
    if steamapps.name.casefold() != "steamapps":
        return None
    manifest = steamapps / "appmanifest_1086940.acf"
    if not manifest.is_file():
        return None
    pairs = parse_vdf_pairs(manifest.read_text(encoding="utf-8", errors="replace"))
    return _optional_text(pairs.get("buildid"))


def resolve_manifest_reference(raw: str, manifest_dir: Path) -> Path:
    candidate = Path(raw).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    if not candidate.is_absolute():
        relative = manifest_dir / candidate
        if relative.is_file():
            return relative.resolve()
    raise InstallFailure(54, "ARTIFACT_INTEGRITY_FAILED", f"Artifact file not found: {raw}")


def restore_backup(backup: Path, destination: Path, expected_sha: str) -> bool:
    try:
        temp = destination.with_name(f".{destination.name}.bg3loc-rollback-{os.getpid()}.tmp")
        shutil.copy2(backup, temp)
        if sha256_file(temp).casefold() != expected_sha.casefold():
            _unlink_quietly(temp)
            return False
        os.replace(temp, destination)
        return sha256_file(destination).casefold() == expected_sha.casefold()
    except OSError:
        return False


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
