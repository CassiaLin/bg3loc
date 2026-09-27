from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from bg3loc.backends import ArchiveBackend, ArchiveBackendError, backend_from_manifest
from bg3loc.io import read_json, write_json
from bg3loc.schema import SchemaStore


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

    selected_ids = [request.source, request.target, *request.references]
    _ensure_distinct_roles(selected_ids)

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

    request.output.mkdir(parents=True, exist_ok=True)
    normalized_by_locale: dict[str, list[dict[str, Any]]] = {}
    locale_outputs: list[dict[str, Any]] = []
    roundtrip_reports: list[dict[str, Any]] = []

    for requested_id, locale in selected:
        actual_id = str(locale.get("localeId", requested_id))
        package_path = Path(str(locale["packageFile"]))
        loca_entry = _resolve_primary_loca_entry(locale, actual_id)
        locale_dir = request.output / "locales" / actual_id
        source_loca = locale_dir / "source.loca"
        source_xml = locale_dir / "source.xml"
        roundtrip_loca = locale_dir / "roundtrip.loca"
        roundtrip_xml = locale_dir / "roundtrip.xml"

        try:
            active_backend.extract_single_file(package_path, loca_entry, source_loca)
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

        normalized_path = request.output / "normalized" / f"{actual_id}.jsonl"
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
            "sourceLoca": str(source_loca),
            "sourceXml": str(source_xml),
            "normalized": str(normalized_path),
            "nodeCount": len(records),
        })

    aligned_path = request.output / "aligned" / "source-target.jsonl"
    aligned_rows = align_locales(normalized_by_locale)
    write_jsonl(aligned_path, aligned_rows)

    validation_path = request.output / "validation" / "roundtrip.json"
    write_json(validation_path, {"schemaVersion": "1.0", "locales": roundtrip_reports})

    manifest = {
        "schemaVersion": "1.0",
        "scanManifest": str(request.scan_manifest),
        "sourceLocale": request.source,
        "targetLocale": request.target,
        "referenceLocales": list(request.references),
        "backend": scan.get("backend", {}),
        "locales": locale_outputs,
        "aligned": str(aligned_path),
        "roundtripValidation": str(validation_path),
    }
    SchemaStore().validate("extract-manifest.schema.json", manifest)
    write_json(request.output / "extract-manifest.json", manifest)
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
