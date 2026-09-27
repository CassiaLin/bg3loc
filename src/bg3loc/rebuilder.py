from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from bg3loc.backends import ArchiveBackend, ArchiveBackendError, backend_from_manifest, backend_from_probe, resolve_backend
from bg3loc.io import read_json, write_json
from bg3loc.schema import SchemaStore


@dataclass(frozen=True, slots=True)
class RebuildRequest:
    validate_manifest: Path
    extract_manifest: Path
    container: str = "auto"
    backend: str = "auto"
    output: Path = Path("workspace/rebuild")


class RebuildFailure(RuntimeError):
    def __init__(self, exit_code: int, key: str, message: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.key = key
        self.message = message


@dataclass(frozen=True, slots=True)
class LocaRecord:
    content_uid: str
    version: int
    text: str


def run_rebuild(request: RebuildRequest, backend: ArchiveBackend | None = None) -> dict[str, Any]:
    if request.container not in {"auto", "loca-only", "repack"}:
        raise RebuildFailure(48, "CONTAINER_REPACK_FAILED", f"Unsupported container mode: {request.container}")

    try:
        validate = read_json(request.validate_manifest)
        SchemaStore().validate("validate-manifest.schema.json", validate)
    except Exception as exc:
        raise RebuildFailure(40, "VALIDATE_MANIFEST_INVALID", str(exc)) from exc

    if bool(validate.get("strict")) and validate.get("summary", {}).get("status") == "fail":
        raise RebuildFailure(40, "VALIDATE_MANIFEST_INVALID", "Strict validation manifest is in fail state.")

    try:
        extract = read_json(request.extract_manifest)
        SchemaStore().validate("extract-manifest.schema.json", extract)
    except Exception as exc:
        raise RebuildFailure(42, "TARGET_BASELINE_MISSING", f"Extract manifest unavailable or invalid: {exc}") from exc

    try:
        accepted_path = resolve_reference(str(validate["accepted"]["path"]), request.validate_manifest.parent, "accepted")
        accepted = read_jsonl(accepted_path)
    except Exception as exc:
        raise RebuildFailure(41, "ACCEPTED_RECORDS_MISSING", str(exc)) from exc

    target_locale = str(extract["targetLocale"])
    source_locale = str(extract["sourceLocale"])
    target_info = find_locale_info(extract, target_locale)
    source_info = find_locale_info(extract, source_locale)
    try:
        target_xml = resolve_reference(str(target_info["sourceXml"]), request.extract_manifest.parent)
        target_package = Path(str(target_info["packageFile"])).expanduser()
        target_loca_entry = str(target_info["locaEntry"])
        source_normalized = resolve_reference(str(source_info["normalized"]), request.extract_manifest.parent, "normalized")
    except Exception as exc:
        raise RebuildFailure(42, "TARGET_BASELINE_MISSING", str(exc)) from exc

    try:
        baseline = parse_loca_xml(target_xml)
        source_records = {str(item["contentUid"]): item for item in read_jsonl(source_normalized)}
        accepted_map = index_accepted(accepted, target_locale)
        merged, changed_uids, new_uids = merge_records(baseline, source_records, accepted_map)
    except RebuildFailure:
        raise
    except Exception as exc:
        raise RebuildFailure(43, "MERGE_FAILED", str(exc)) from exc

    active_backend = resolve_rebuild_backend(request.backend, extract, backend)
    if active_backend is None:
        raise RebuildFailure(44, "LOCA_SERIALIZATION_FAILED", "No usable archive/LOCA backend is available.")

    request.output.mkdir(parents=True, exist_ok=True)
    artifacts_dir = request.output / "artifacts"
    validation_dir = request.output / "validation"
    work_dir = request.output / "work"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    validation_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    merged_xml = work_dir / f"{target_locale}.xml"
    rebuilt_loca = artifacts_dir / f"{target_locale}.loca"
    reread_xml = validation_dir / f"{target_locale}.roundtrip.xml"
    try:
        write_loca_xml(merged_xml, merged)
        active_backend.convert_loca(merged_xml, rebuilt_loca)
    except (ArchiveBackendError, OSError, ValueError) as exc:
        raise RebuildFailure(44, "LOCA_SERIALIZATION_FAILED", str(exc)) from exc

    try:
        active_backend.convert_loca(rebuilt_loca, reread_xml)
        reread = parse_loca_xml(reread_xml)
        validate_rebuilt_records(baseline, merged, reread, accepted_map, changed_uids)
    except ArchiveBackendError as exc:
        raise RebuildFailure(45, "SEMANTIC_ROUNDTRIP_FAILED", str(exc)) from exc

    artifacts: list[dict[str, Any]] = [artifact_record("loca", rebuilt_loca)]
    container_action = choose_container_action(request.container, target_package)
    if container_action == "repack":
        rebuilt_pak = artifacts_dir / target_package.name
        try:
            repack_target_package(
                active_backend,
                target_package=target_package,
                loca_entry=target_loca_entry,
                rebuilt_loca=rebuilt_loca,
                destination=rebuilt_pak,
                staging_root=work_dir,
            )
        except (ArchiveBackendError, OSError, ValueError) as exc:
            raise RebuildFailure(48, "CONTAINER_REPACK_FAILED", str(exc)) from exc
        artifacts.append(artifact_record("pak", rebuilt_pak))

    baseline_map = {item.content_uid: item for item in baseline}
    source_uid_set = set(source_records)
    target_uid_set = set(baseline_map)
    preserved_target_only = len(target_uid_set - source_uid_set)
    changed_path = validation_dir / "changed-uids.jsonl"
    unchanged_path = validation_dir / "unchanged-uids-summary.json"
    rebuild_validation_path = validation_dir / "rebuild-validation.json"
    try:
        write_jsonl(changed_path, [
            {
                "contentUid": uid,
                "wasPresentInTarget": uid in baseline_map,
                "newTargetNode": uid in new_uids,
                "version": accepted_map[uid]["version"],
            }
            for uid in sorted(changed_uids)
        ])
        write_json(unchanged_path, {
            "schemaVersion": "1.0",
            "baselineNodeCount": len(baseline),
            "changedUidCount": len(changed_uids),
            "unchangedBaselineUidCount": len(set(baseline_map) - changed_uids),
            "preservedTargetOnlyCount": preserved_target_only,
        })
        write_json(rebuild_validation_path, {
            "schemaVersion": "1.0",
            "semanticRoundTrip": "pass",
            "acceptedTextMatch": "pass",
            "uidSetIntegrity": "pass",
            "untouchedRecordIntegrity": "pass",
            "expectedNodeCount": len(merged),
            "rereadNodeCount": len(reread),
        })
    except Exception as exc:
        raise RebuildFailure(49, "REBUILD_OUTPUT_FAILED", str(exc)) from exc

    manifest = {
        "schemaVersion": "1.0",
        "validateManifest": str(request.validate_manifest),
        "extractManifest": str(request.extract_manifest),
        "targetLocale": target_locale,
        "containerMode": request.container,
        "containerAction": container_action,
        "baseline": {
            "packageFile": str(target_package),
            "locaEntry": target_loca_entry,
            "sourceXml": str(target_xml),
            "nodeCount": len(baseline),
            "sha256": sha256_file(target_xml),
        },
        "merge": {
            "acceptedRecordCount": len(accepted_map),
            "changedUidCount": len(changed_uids),
            "newTargetNodeCount": len(new_uids),
            "preservedTargetOnlyCount": preserved_target_only,
        },
        "artifacts": artifacts,
        "validation": {
            "semanticRoundTrip": "pass",
            "acceptedTextMatch": "pass",
            "uidSetIntegrity": "pass",
            "untouchedRecordIntegrity": "pass",
            "report": str(rebuild_validation_path),
            "changedUids": str(changed_path),
            "unchangedSummary": str(unchanged_path),
        },
    }
    try:
        SchemaStore().validate("rebuild-manifest.schema.json", manifest)
        write_json(request.output / "rebuild-manifest.json", manifest)
    except Exception as exc:
        raise RebuildFailure(49, "REBUILD_OUTPUT_FAILED", str(exc)) from exc
    return manifest


def resolve_rebuild_backend(requested: str, extract: dict[str, Any], injected: ArchiveBackend | None) -> ArchiveBackend | None:
    if injected is not None:
        return injected
    if requested == "auto":
        recorded = backend_from_manifest(extract.get("backend", {}))
        if recorded is not None:
            return recorded
        return backend_from_probe(resolve_backend("auto"))
    return backend_from_probe(resolve_backend(requested))


def parse_loca_xml(path: Path) -> list[LocaRecord]:
    records: list[LocaRecord] = []
    seen: set[str] = set()
    for _event, element in ET.iterparse(path, events=("end",)):
        if element.tag != "content":
            continue
        uid = element.attrib.get("contentuid")
        if not uid:
            raise ValueError(f"content without contentuid: {path}")
        if uid in seen:
            raise ValueError(f"duplicate ContentUid in baseline: {uid}")
        seen.add(uid)
        version = int(element.attrib.get("version", "1"))
        records.append(LocaRecord(uid, version, element.text or ""))
        element.clear()
    if not records:
        raise ValueError(f"No content records found: {path}")
    return records


def write_loca_xml(path: Path, records: list[LocaRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    root = ET.Element("contentList")
    for record in records:
        node = ET.SubElement(root, "content", {"contentuid": record.content_uid, "version": str(record.version)})
        node.text = record.text
    tree = ET.ElementTree(root)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tree.write(tmp, encoding="utf-8", xml_declaration=True)
    tmp.replace(path)


def index_accepted(rows: list[dict[str, Any]], target_locale: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        uid = str(row.get("contentUid", ""))
        if not uid:
            raise RebuildFailure(43, "MERGE_FAILED", "Accepted record is missing ContentUid.")
        if uid in result:
            raise RebuildFailure(43, "MERGE_FAILED", f"Duplicate accepted ContentUid: {uid}")
        if str(row.get("localeId", "")) != target_locale:
            raise RebuildFailure(43, "MERGE_FAILED", f"Accepted record locale mismatch for {uid}")
        text = row.get("text")
        if not isinstance(text, str):
            raise RebuildFailure(43, "MERGE_FAILED", f"Accepted record text is not a string for {uid}")
        try:
            version = int(row.get("version"))
        except (TypeError, ValueError) as exc:
            raise RebuildFailure(43, "MERGE_FAILED", f"Accepted record version invalid for {uid}") from exc
        result[uid] = {**row, "version": version}
    return result


def merge_records(
    baseline: list[LocaRecord],
    source_records: dict[str, dict[str, Any]],
    accepted: dict[str, dict[str, Any]],
) -> tuple[list[LocaRecord], set[str], set[str]]:
    baseline_map = {item.content_uid: item for item in baseline}
    for uid in accepted:
        if uid not in baseline_map and uid not in source_records:
            raise RebuildFailure(47, "UID_SET_INTEGRITY_FAILED", f"Accepted ContentUid is in neither target baseline nor source: {uid}")

    merged: list[LocaRecord] = []
    changed: set[str] = set()
    for record in baseline:
        edit = accepted.get(record.content_uid)
        if edit is None:
            merged.append(record)
            continue
        updated = LocaRecord(record.content_uid, int(edit["version"]), str(edit["text"]))
        merged.append(updated)
        if updated.version != record.version or updated.text != record.text:
            changed.add(record.content_uid)

    new_uids: set[str] = set()
    for uid, edit in accepted.items():
        if uid in baseline_map:
            continue
        merged.append(LocaRecord(uid, int(edit["version"]), str(edit["text"])))
        changed.add(uid)
        new_uids.add(uid)
    return merged, changed, new_uids


def validate_rebuilt_records(
    baseline: list[LocaRecord],
    expected: list[LocaRecord],
    actual: list[LocaRecord],
    accepted: dict[str, dict[str, Any]],
    changed_uids: set[str],
) -> None:
    expected_map = {item.content_uid: item for item in expected}
    actual_map = {item.content_uid: item for item in actual}
    if set(expected_map) != set(actual_map) or len(expected) != len(actual):
        raise RebuildFailure(47, "UID_SET_INTEGRITY_FAILED", "Rebuilt LOCA ContentUid set or node count differs from expected.")
    for uid, edit in accepted.items():
        item = actual_map.get(uid)
        if item is None or item.text != edit["text"] or item.version != int(edit["version"]):
            raise RebuildFailure(46, "ACCEPTED_TEXT_MISMATCH", f"Accepted text/version mismatch after round-trip: {uid}")
    baseline_map = {item.content_uid: item for item in baseline}
    for uid, original in baseline_map.items():
        if uid in changed_uids:
            continue
        rebuilt = actual_map[uid]
        if rebuilt.text != original.text or rebuilt.version != original.version:
            raise RebuildFailure(45, "SEMANTIC_ROUNDTRIP_FAILED", f"Untouched baseline record changed: {uid}")
    for uid, expected_item in expected_map.items():
        actual_item = actual_map[uid]
        if actual_item.text != expected_item.text or actual_item.version != expected_item.version:
            raise RebuildFailure(45, "SEMANTIC_ROUNDTRIP_FAILED", f"Semantic round-trip mismatch: {uid}")


def choose_container_action(mode: str, target_package: Path) -> str:
    if mode == "loca-only":
        return "loca-only"
    if mode == "repack":
        if target_package.suffix.casefold() != ".pak":
            raise RebuildFailure(48, "CONTAINER_REPACK_FAILED", f"Target baseline is not a PAK: {target_package}")
        return "repack"
    return "repack" if target_package.suffix.casefold() == ".pak" else "loca-only"


def repack_target_package(
    backend: ArchiveBackend,
    *,
    target_package: Path,
    loca_entry: str,
    rebuilt_loca: Path,
    destination: Path,
    staging_root: Path,
) -> None:
    if not target_package.is_file():
        raise FileNotFoundError(target_package)
    expected_entries = {normalize_archive_path(entry.path).casefold() for entry in backend.list_archive(target_package, "*")}
    if not expected_entries:
        raise ValueError(f"Baseline PAK contains no listable entries: {target_package}")
    expected_loca = normalize_archive_path(loca_entry).casefold()
    if expected_loca not in expected_entries:
        raise ValueError(f"Baseline PAK does not contain expected LOCA entry: {loca_entry}")

    staging_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="repack-", dir=staging_root) as temp:
        temp_root = Path(temp)
        extracted = temp_root / "package"
        backend.extract_package(target_package, extracted)
        relative = safe_archive_relative_path(loca_entry)
        replacement = extracted.joinpath(*relative.parts)
        if not replacement.is_file():
            raise ValueError(f"Extracted baseline package does not contain expected LOCA entry: {loca_entry}")
        shutil.copy2(rebuilt_loca, replacement)
        backend.create_package(extracted, destination)

        actual_entries = {normalize_archive_path(entry.path).casefold() for entry in backend.list_archive(destination, "*")}
        if actual_entries != expected_entries:
            missing = sorted(expected_entries - actual_entries)[:10]
            added = sorted(actual_entries - expected_entries)[:10]
            raise ValueError(f"Repacked PAK entry set changed; missing={missing}, added={added}")

        verify_loca = temp_root / "verify" / rebuilt_loca.name
        backend.extract_single_file(destination, loca_entry, verify_loca)
        if sha256_file(verify_loca) != sha256_file(rebuilt_loca):
            raise ValueError(f"Repacked PAK LOCA payload does not match rebuilt artifact: {loca_entry}")


def safe_archive_relative_path(raw: str) -> PurePosixPath:
    normalized = raw.replace("\\", "/")
    if not normalized or normalized.startswith("/"):
        raise ValueError(f"Unsafe archive entry path: {raw}")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Unsafe archive entry path: {raw}")
    if path.parts and ":" in path.parts[0]:
        raise ValueError(f"Unsafe archive entry path: {raw}")
    return path


def normalize_archive_path(raw: str) -> str:
    return str(safe_archive_relative_path(raw))


def find_locale_info(extract: dict[str, Any], locale_id: str) -> dict[str, Any]:
    matches = [item for item in extract.get("locales", []) if str(item.get("localeId", "")).casefold() == locale_id.casefold()]
    if len(matches) != 1:
        raise RebuildFailure(42, "TARGET_BASELINE_MISSING", f"Expected one extracted locale record for {locale_id}; found {len(matches)}")
    return matches[0]


def resolve_reference(raw: str, manifest_dir: Path, fallback_subdir: str | None = None) -> Path:
    candidate = Path(raw).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    if not candidate.is_absolute():
        relative = manifest_dir / candidate
        if relative.is_file():
            return relative.resolve()
    if fallback_subdir:
        fallback = manifest_dir / fallback_subdir / candidate.name
        if fallback.is_file():
            return fallback.resolve()
    raise FileNotFoundError(raw)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL line {line_no} is not an object: {path}")
            rows.append(value)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(path)


def artifact_record(kind: str, path: Path) -> dict[str, Any]:
    return {"type": kind, "path": str(path), "sha256": sha256_file(path)}


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
