from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from bg3loc.backends import ArchiveBackend, ArchiveBackendError, backend_from_manifest
from bg3loc.io import read_json, write_json
from bg3loc.schema import SchemaStore
from bg3loc.source_packages import ScanPackageSnapshot, SourcePackageError, no_link


@dataclass(frozen=True, slots=True)
class ExtractRequest:
    scan_manifest: Path
    source: str
    target: str
    references: tuple[str, ...] = ()
    output: Path = Path("workspace/extract")


class ExtractFailure(RuntimeError):
    def __init__(self, exit_code: int, key: str, message: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.key = key
        self.message = message


def run_extract(request: ExtractRequest, backend: ArchiveBackend | None = None) -> dict[str, Any]:
    try:
        scan = read_json(request.scan_manifest)
        SchemaStore().validate("scan.schema.json", scan)
    except Exception as exc:
        raise ExtractFailure(10, "SCAN_MANIFEST_INVALID", str(exc)) from exc

    selected_ids = resolve_locale_roles(scan, [request.source, request.target, *request.references])
    locale_map = _index_locales(scan)
    selected: list[tuple[str, dict[str, Any]]] = []
    for index, locale_id in enumerate(selected_ids):
        role_code = 11 if index == 0 else 12 if index == 1 else 13
        role_key = "SOURCE_LOCALE_NOT_FOUND" if index == 0 else "TARGET_LOCALE_NOT_FOUND" if index == 1 else "REFERENCE_LOCALE_NOT_FOUND"
        locale = locale_map.get(locale_id.casefold())
        if locale is None:
            raise ExtractFailure(role_code, role_key, f"Locale not found in scan manifest: {locale_id}")
        selected.append((locale_id, locale))

    active_backend = backend or backend_from_manifest(scan.get("backend", {}))
    if active_backend is None:
        raise ExtractFailure(14, "EFFECTIVE_PROVIDER_UNRESOLVED", "No usable archive backend recorded in scan manifest.")

    output = request.output.expanduser().absolute()
    if output.is_symlink() or (output.exists() and getattr(output.lstat(), "st_file_attributes", 0) & 0x400):
        raise ExtractFailure(15, "ARCHIVE_EXTRACTION_FAILED", "Linked extract output is unsupported")
    output = output.resolve()
    input_paths = [request.scan_manifest.resolve(), *[Path(locale["packageFile"]).resolve() for _, locale in selected]]
    if any(path.is_relative_to(output) for path in input_paths):
        raise ExtractFailure(15, "ARCHIVE_EXTRACTION_FAILED", "Extract output must not contain scan or source packages")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="extract-stage-", dir=output.parent) as temporary:
            temporary = Path(temporary)
            with ScanPackageSnapshot(scan, selected, temporary / "packages") as packages:
                work = temporary / "output"
                if output.exists():
                    if not output.is_dir():
                        raise ValueError("Extract output is not a directory")
                    # Preserve unrelated files and unselected locale artifacts, as v1 did.
                    for path in (output, *output.rglob("*")):
                        no_link(path)
                    shutil.copytree(output, work)
                else:
                    work.mkdir()
                manifest = _extract_verified(request, scan, selected, active_backend, work, packages)
                _publish_extract(work, output, packages.verify)
        return manifest
    except (SourcePackageError, OSError, ValueError) as exc:
        raise ExtractFailure(15, "ARCHIVE_EXTRACTION_FAILED", str(exc)) from exc


def _publish_extract(work: Path, output: Path, verify) -> None:
    previous = False
    published = False
    recovery = None
    try:
        verify()
        if output.exists():
            # Outside the staging directory: failed rollback must never be
            # erased by automatic staging cleanup.
            recovery = Path(tempfile.mkdtemp(prefix="extract-previous-", dir=output.parent))
            backup = recovery / "output"
            os.replace(output, backup)
            previous = True
        verify()
        os.replace(work, output)
        published = True
        verify()
    except BaseException:
        try:
            if published:
                os.replace(output, work)
            if previous:
                os.replace(backup, output)
        except OSError as exc:
            raise OSError(f"Extract publication rollback failed; recovery preserved at {recovery}") from exc
        raise
    finally:
        if recovery is not None and not (recovery / "output").exists():
            recovery.rmdir()
    if recovery is not None:
        if recovery.resolve().parent != output.parent.resolve() or recovery.is_symlink():
            raise OSError("Unsafe extract recovery cleanup path")
        try:
            shutil.rmtree(recovery)
        except OSError:
            warnings.warn(f"Verified extract published; previous output retained at {recovery}", RuntimeWarning)


def _extract_verified(request, scan, selected, active_backend, work, packages):
    normalized_by_locale: dict[str, list[dict[str, Any]]] = {}
    locale_outputs: list[dict[str, Any]] = []
    roundtrip_reports: list[dict[str, Any]] = []

    for requested_id, locale in selected:
        actual_id = str(locale.get("localeId", requested_id))
        package_path = Path(str(locale["packageFile"]))
        loca_entry = _resolve_primary_loca_entry(locale, actual_id)
        locale_dir = work / "locales" / actual_id
        logical_locale_dir = request.output / "locales" / actual_id
        source_loca = locale_dir / "source.loca"
        source_xml = locale_dir / "source.xml"
        roundtrip_loca = locale_dir / "roundtrip.loca"
        roundtrip_xml = locale_dir / "roundtrip.xml"

        try:
            packages.verify()
            active_backend.extract_single_file(packages.path(actual_id), loca_entry, source_loca)
            packages.verify()
        except ArchiveBackendError as exc:
            raise ExtractFailure(15, "ARCHIVE_EXTRACTION_FAILED", f"{actual_id}: {exc}") from exc

        try:
            active_backend.convert_loca(source_loca, source_xml)
        except ArchiveBackendError as exc:
            raise ExtractFailure(16, "LOCA_CONVERSION_FAILED", f"{actual_id}: {exc}") from exc

        try:
            records = normalize_loca_xml(
                source_xml,
                locale_id=actual_id,
                source_package=str(package_path),
                source_loca_entry=loca_entry,
            )
        except Exception as exc:
            raise ExtractFailure(17, "NORMALIZATION_FAILED", f"{actual_id}: {exc}") from exc

        normalized_path = work / "normalized" / f"{actual_id}.jsonl"
        write_jsonl(normalized_path, records)
        normalized_by_locale[actual_id] = records

        try:
            active_backend.convert_loca(source_xml, roundtrip_loca)
            active_backend.convert_loca(roundtrip_loca, roundtrip_xml)
            roundtrip_records = normalize_loca_xml(
                roundtrip_xml,
                locale_id=actual_id,
                source_package=str(package_path),
                source_loca_entry=loca_entry,
            )
            verify_semantic_roundtrip(records, roundtrip_records)
        except (ArchiveBackendError, ValueError) as exc:
            raise ExtractFailure(18, "ROUNDTRIP_VALIDATION_FAILED", f"{actual_id}: {exc}") from exc

        report = {
            "localeId": actual_id,
            "nodeCount": len(records),
            "contentUidCount": len({record["contentUid"] for record in records}),
            "semanticMatch": True,
        }
        roundtrip_reports.append(report)
        locale_outputs.append({
            "localeId": actual_id,
            "packageFile": str(package_path),
            "locaEntry": loca_entry,
            "sourceLoca": str(logical_locale_dir / "source.loca"),
            "sourceXml": str(logical_locale_dir / "source.xml"),
            "normalized": str(request.output / "normalized" / f"{actual_id}.jsonl"),
            "nodeCount": len(records),
        })

    aligned_path = work / "aligned" / "source-target.jsonl"
    aligned_rows = align_locales(normalized_by_locale)
    write_jsonl(aligned_path, aligned_rows)

    validation_path = work / "validation" / "roundtrip.json"
    write_json(validation_path, {"schemaVersion": "1.0", "locales": roundtrip_reports})

    manifest = {
        "schemaVersion": "1.0",
        "scanManifest": str(request.scan_manifest),
        "sourceLocale": selected[0][0],
        "targetLocale": selected[1][0],
        "referenceLocales": [locale_id for locale_id, _ in selected[2:]],
        "backend": scan.get("backend", {}),
        "locales": locale_outputs,
        "aligned": str(request.output / "aligned" / "source-target.jsonl"),
        "roundtripValidation": str(request.output / "validation" / "roundtrip.json"),
    }
    SchemaStore().validate("extract-manifest.schema.json", manifest)
    write_json(work / "extract-manifest.json", manifest)
    return manifest


def normalize_loca_xml(
    path: Path,
    *,
    locale_id: str,
    source_package: str,
    source_loca_entry: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _event, element in ET.iterparse(path, events=("end",)):
        if element.tag != "content":
            continue
        content_uid = element.attrib.get("contentuid")
        if not content_uid:
            raise ValueError("content element is missing contentuid")
        if content_uid in seen:
            raise ValueError(f"Duplicate ContentUid: {content_uid}")
        seen.add(content_uid)
        version_text = element.attrib.get("version", "1")
        try:
            version: int | str = int(version_text)
        except ValueError:
            version = version_text
        text = element.text or ""
        records.append({
            "contentUid": content_uid,
            "localeId": locale_id,
            "text": text,
            "version": version,
            "sourcePackage": source_package,
            "sourceLocaEntry": source_loca_entry,
            "textHash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "presence": True,
        })
        element.clear()
    if not records:
        raise ValueError(f"No localization content records found in XML: {path}")
    return records


def verify_semantic_roundtrip(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> None:
    before_map = {str(item["contentUid"]): item for item in before}
    after_map = {str(item["contentUid"]): item for item in after}
    if before_map.keys() != after_map.keys():
        missing = sorted(before_map.keys() - after_map.keys())[:5]
        added = sorted(after_map.keys() - before_map.keys())[:5]
        raise ValueError(f"ContentUid set changed; missing={missing}, added={added}")
    if len(before) != len(after):
        raise ValueError(f"Node count changed: {len(before)} -> {len(after)}")
    for content_uid, left in before_map.items():
        right = after_map[content_uid]
        if left["version"] != right["version"]:
            raise ValueError(f"Version changed for {content_uid}: {left['version']} -> {right['version']}")
        if left["text"] != right["text"]:
            raise ValueError(f"Text changed for {content_uid}")


def align_locales(normalized: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    by_locale = {
        locale_id: {str(item["contentUid"]): item for item in records}
        for locale_id, records in normalized.items()
    }
    all_uids: set[str] = set()
    for records in by_locale.values():
        all_uids.update(records)

    rows: list[dict[str, Any]] = []
    for content_uid in sorted(all_uids):
        row: dict[str, Any] = {"contentUid": content_uid, "locales": {}}
        for locale_id, records in by_locale.items():
            item = records.get(content_uid)
            row["locales"][locale_id] = None if item is None else {
                "text": item["text"],
                "version": item["version"],
                "presence": True,
            }
        rows.append(row)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(path)


def _index_locales(scan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in scan.get("locales", []):
        if not isinstance(raw, dict):
            continue
        locale_id = str(raw.get("localeId", ""))
        if not locale_id:
            continue
        key = locale_id.casefold()
        if key in result:
            raise ExtractFailure(14, "EFFECTIVE_PROVIDER_UNRESOLVED", f"Multiple providers remain for locale: {locale_id}")
        result[key] = raw
    return result


def resolve_locale_roles(inventory: dict[str, Any], locale_ids: list[str]) -> list[str]:
    """Resolve input spellings through the existing scanner inventory, never aliases."""
    _ensure_distinct_roles(locale_ids)
    registry = _index_locales(inventory)
    resolved = []
    for index, requested in enumerate(locale_ids):
        entry = registry.get(requested.casefold())
        if entry is None:
            role = "SOURCE" if index == 0 else "TARGET" if index == 1 else "REFERENCE"
            raise ExtractFailure(11 + min(index, 2), f"{role}_LOCALE_NOT_FOUND",
                                 f"Locale not found in inventory: {requested}")
        if entry.get("status", "ready") != "ready":
            raise ExtractFailure(14, "EFFECTIVE_PROVIDER_UNRESOLVED",
                                 f"Locale provider is not ready: {requested}")
        resolved.append(str(entry["localeId"]))
    return resolved


def material_locale_roles(extract: dict[str, Any]) -> list[str]:
    roles = [str(extract["sourceLocale"]), str(extract["targetLocale"]),
             *[str(value) for value in extract.get("referenceLocales", [])]]
    if resolve_locale_roles(extract, roles) != roles:
        raise ValueError("Extract locale roles are not canonical; re-extract from the scan inventory")
    return roles


def validate_material_locales(extract: dict[str, Any], aligned: list[dict[str, Any]],
                             manifest_dir: Path, *, scoped: bool = False) -> None:
    """Bind canonical roles and source/target projections before material publication.

    Legacy aligned-only consumers may lack normalized sidecars; inventory counts
    still bind full alignment. Available normalized sidecars must agree exactly.
    An explicit UID subset compares only its selected projection, not full counts.
    """
    roles = material_locale_roles(extract)
    registry = _index_locales(extract)
    projections: dict[str, dict[str, tuple[Any, Any]]] = {role: {} for role in roles}
    seen = set()
    for row in aligned:
        uid = row.get("contentUid")
        if not isinstance(uid, str) or not uid or uid in seen:
            raise ValueError("Invalid or duplicate aligned ContentUid in locale material")
        seen.add(uid)
        locales = row.get("locales")
        if not isinstance(locales, dict):
            raise ValueError("Invalid aligned locale map")
        for key in locales:
            if not isinstance(key, str):
                raise ValueError("Invalid aligned locale key")
            entry = registry.get(key.casefold())
            if entry is not None and key != entry["localeId"]:
                raise ValueError("Aligned locale keys are not canonical")
        for role in roles:
            cell = locales.get(role)
            if cell is None:
                continue
            if not isinstance(cell, dict) or not isinstance(cell.get("text"), str):
                raise ValueError("Invalid aligned locale text")
            projections[role][uid] = (cell["text"], cell.get("version"))
    for role in roles:
        entry = registry[role.casefold()]
        projection = projections[role]
        if not scoped and len(projection) != entry["nodeCount"]:
            raise ValueError(f"Aligned locale record count mismatch: {role}")
        raw = Path(str(entry["normalized"])).expanduser()
        candidates = [raw] if raw.is_absolute() else [raw, manifest_dir / raw]
        path = next((candidate for candidate in candidates if candidate.is_file()), None)
        if path is None:
            continue  # Existing v1 aligned-only material contract remains supported.
        normalized = {}
        with path.open("r", encoding="utf-8-sig") as stream:
            for line in stream:
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict) or not isinstance(record.get("contentUid"), str):
                    raise ValueError("Invalid normalized locale record")
                uid = record["contentUid"]
                if not uid or uid in normalized or not isinstance(record.get("text"), str):
                    raise ValueError("Invalid or duplicate normalized locale text")
                if record.get("localeId", role) != role:
                    raise ValueError("Normalized locale identity mismatch")
                normalized[uid] = (record["text"], record.get("version"))
        if len(normalized) != entry["nodeCount"]:
            raise ValueError(f"Normalized locale record count mismatch: {role}")
        expected = {uid: value for uid, value in normalized.items() if not scoped or uid in seen}
        if expected != projection:
            raise ValueError(f"Aligned/normalized locale text or version mismatch: {role}")


def validate_material_projection(extract: dict[str, Any], aligned: list[dict[str, Any]],
                                 material: list[dict[str, Any]]) -> None:
    """Check required count and exact immutable source/target projection, including blanks."""
    by_uid = {row["contentUid"]: row for row in aligned}
    seen = set()
    source_role, target_role = extract["sourceLocale"], extract["targetLocale"]
    for row in material:
        uid = row.get("ContentUid")
        if uid not in by_uid or uid in seen:
            raise ValueError("Material locale identity or count mismatch")
        seen.add(uid)
        source = by_uid[uid]["locales"].get(source_role)
        target = by_uid[uid]["locales"].get(target_role)
        expected = {"SourceLocale": source_role, "TargetLocale": target_role,
                    "SourceText": "" if source is None else source["text"],
                    "TranslationRequired": source is not None}
        if "SourceVersion" in row:
            expected["SourceVersion"] = None if source is None else source.get("version")
        if "ExistingTargetText" in row:
            expected["ExistingTargetText"] = "" if target is None else target["text"]
        if "TargetVersion" in row:
            expected["TargetVersion"] = None if target is None else target.get("version")
        if (any(row.get(key) != value for key, value in expected.items())
                or type(row.get("TranslationRequired")) is not bool):
            raise ValueError("Material locale source/target projection or required count mismatch")
    if seen != set(by_uid):
        raise ValueError("Material locale identity or count mismatch")


def _resolve_primary_loca_entry(locale: dict[str, Any], locale_id: str) -> str:
    entries = locale.get("locaEntries")
    entry_count = len(entries) if isinstance(entries, list) else 0
    paths = [_loca_entry_path(item) for item in entries] if isinstance(entries, list) else []
    candidate_paths = [path for path in paths if path is not None]
    matches = [path for path in candidate_paths if _is_primary_loca_path(path, locale_id)]

    if len(matches) == 1:
        return matches[0]
    if not matches:
        displayed = "; ".join(candidate_paths) if candidate_paths else "(none)"
        raise ExtractFailure(
            14,
            "EFFECTIVE_PROVIDER_UNRESOLVED",
            f"Locale {locale_id} has {entry_count} LOCA entries but no canonical primary LOCA; "
            f"candidate paths: {displayed}",
        )
    raise ExtractFailure(
        14,
        "EFFECTIVE_PROVIDER_UNRESOLVED",
        f"Locale {locale_id} has ambiguous canonical primary LOCA paths: {'; '.join(matches)}",
    )


def _loca_entry_path(item: Any) -> str | None:
    if isinstance(item, str) and item:
        return item
    if isinstance(item, dict) and item.get("path"):
        return str(item["path"])
    return None


def _is_primary_loca_path(path: str, locale_id: str) -> bool:
    normalized = PurePosixPath(path.replace("\\", "/"))
    parts = normalized.parts
    return (
        len(parts) == 3
        and parts[0].casefold() == "localization"
        and parts[1].casefold() == locale_id.casefold()
        and normalized.suffix.casefold() == ".loca"
        and normalized.stem.casefold() == locale_id.casefold()
    )


def _ensure_distinct_roles(locale_ids: list[str]) -> None:
    lowered = [item.casefold() for item in locale_ids]
    if len(lowered) != len(set(lowered)):
        raise ExtractFailure(14, "EFFECTIVE_PROVIDER_UNRESOLVED", "Source, target, and reference locale roles must be distinct.")
