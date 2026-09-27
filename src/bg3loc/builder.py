from __future__ import annotations

import csv
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from openpyxl import Workbook
from openpyxl.styles import Font

from bg3loc.io import read_json, write_json
from bg3loc.protected_syntax import extract_protected_tokens
from bg3loc.schema import SchemaStore


@dataclass(frozen=True, slots=True)
class BuildRequest:
    extract_manifest: Path
    mode: str = "basic"
    format: str = "xlsx"
    max_rows: int = 1500
    context: Path | None = None
    glossary: Path | None = None
    output: Path = Path("workspace/build")


class BuildFailure(RuntimeError):
    def __init__(self, exit_code: int, key: str, message: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.key = key
        self.message = message


_VALID_MODES = {"basic", "context", "blind-first"}
_VALID_FORMATS = {"xlsx", "csv", "jsonl"}


def run_build(request: BuildRequest) -> dict[str, Any]:
    if request.mode not in _VALID_MODES:
        raise BuildFailure(21, "MODE_INVALID", f"Unsupported build mode: {request.mode}")
    if request.format not in _VALID_FORMATS:
        raise BuildFailure(23, "WORKBOOK_GENERATION_FAILED", f"Unsupported output format: {request.format}")
    if request.max_rows < 1:
        raise BuildFailure(23, "WORKBOOK_GENERATION_FAILED", "--max-rows must be at least 1")

    try:
        extract = read_json(request.extract_manifest)
        SchemaStore().validate("extract-manifest.schema.json", extract)
    except Exception as exc:
        raise BuildFailure(20, "EXTRACT_MANIFEST_INVALID", str(exc)) from exc

    source_locale = str(extract["sourceLocale"])
    target_locale = str(extract["targetLocale"])
    references = [str(item) for item in extract.get("referenceLocales", [])]

    aligned_path = _resolve_input_path(str(extract["aligned"]), request.extract_manifest.parent)
    try:
        aligned_rows = read_jsonl(aligned_path)
    except Exception as exc:
        raise BuildFailure(20, "EXTRACT_MANIFEST_INVALID", f"Unable to read aligned records: {exc}") from exc

    context_map: dict[str, Any] = {}
    if request.context is not None:
        try:
            context_map = load_keyed_support_data(request.context)
        except Exception as exc:
            raise BuildFailure(22, "CONTEXT_REQUIRED_BUT_MISSING", f"Unable to load context: {exc}") from exc
    elif request.mode == "context":
        raise BuildFailure(22, "CONTEXT_REQUIRED_BUT_MISSING", "context mode requires --context")

    _validate_unique_content_uids(aligned_rows)
    visible_fields, editable_fields = field_contract(request.mode, references)

    material_rows: list[dict[str, Any]] = []
    immutable_rows: list[dict[str, Any]] = []
    for aligned in aligned_rows:
        material, immutable = build_material_row(
            aligned,
            mode=request.mode,
            source_locale=source_locale,
            target_locale=target_locale,
            reference_locales=references,
            context=context_map.get(str(aligned["contentUid"])),
        )
        material_rows.append(material)
        immutable_rows.append(immutable)

    request.output.mkdir(parents=True, exist_ok=True)
    support: dict[str, str] = {}
    if request.context is not None:
        support["context"] = str(_copy_support_file(request.context, request.output / "support"))
    if request.glossary is not None:
        try:
            support["glossary"] = str(_copy_support_file(request.glossary, request.output / "support"))
        except Exception as exc:
            raise BuildFailure(26, "PROTECTED_FIELD_CONTRACT_FAILED", f"Unable to preserve glossary: {exc}") from exc

    workbook_schema = {
        "schemaVersion": "1.0",
        "mode": request.mode,
        "format": request.format,
        "visibleFields": visible_fields,
        "editableFields": editable_fields,
        "identityField": "ContentUid",
        "translationCandidateGeneration": False,
        "blindFirst": request.mode == "blind-first",
        "existingTargetVisible": request.mode != "blind-first",
        "referenceLocalesVisible": request.mode != "blind-first",
    }
    schema_path = request.output / "schemas" / "workbook-schema.json"
    write_json(schema_path, workbook_schema)

    materials: list[dict[str, Any]] = []
    for batch_index, start in enumerate(range(0, len(material_rows), request.max_rows), start=1):
        batch_rows = material_rows[start : start + request.max_rows]
        batch_immutable = immutable_rows[start : start + request.max_rows]
        batch_id = f"{batch_index:03d}"
        material_path = request.output / "materials" / request.mode / f"{batch_id}.{request.format}"
        immutable_path = request.output / "immutable" / f"{batch_id}.jsonl"
        try:
            write_material(material_path, request.format, visible_fields, batch_rows)
            write_jsonl(immutable_path, batch_immutable)
        except Exception as exc:
            raise BuildFailure(23, "WORKBOOK_GENERATION_FAILED", f"Batch {batch_id}: {exc}") from exc
        materials.append({
            "batchId": batch_id,
            "path": str(material_path),
            "immutablePath": str(immutable_path),
            "recordCount": len(batch_rows),
            "sha256": sha256_file(material_path),
        })

    validation = {
        "schemaVersion": "1.0",
        "recordCount": len(material_rows),
        "batchCount": len(materials),
        "uniqueContentUidCount": len({str(row["ContentUid"]) for row in material_rows}),
        "translationCandidateGeneration": False,
        "blindFirstPhysicalSeparation": request.mode != "blind-first" or all(
            "ExistingTargetText" not in row and not any(key.startswith("ReferenceText[") for key in row)
            for row in material_rows
        ),
    }
    if request.mode == "blind-first" and not validation["blindFirstPhysicalSeparation"]:
        raise BuildFailure(26, "PROTECTED_FIELD_CONTRACT_FAILED", "blind-first material leaked existing target or reference text")
    validation_path = request.output / "validation" / "build-validation.json"
    write_json(validation_path, validation)

    manifest = {
        "schemaVersion": "1.0",
        "extractManifest": str(request.extract_manifest),
        "mode": request.mode,
        "format": request.format,
        "sourceLocale": source_locale,
        "targetLocale": target_locale,
        "referenceLocales": references,
        "maxRowsPerWorkbook": request.max_rows,
        "workbookSchema": str(schema_path),
        "support": support,
        "validation": str(validation_path),
        "materials": materials,
    }
    try:
        SchemaStore().validate("build-manifest.schema.json", manifest)
    except Exception as exc:
        raise BuildFailure(24, "SCHEMA_VALIDATION_FAILED", str(exc)) from exc
    write_json(request.output / "build-manifest.json", manifest)
    return manifest


def field_contract(mode: str, reference_locales: list[str]) -> tuple[list[str], list[str]]:
    common = [
        "ContentUid",
        "SourceLocale",
        "SourceText",
        "TargetLocale",
        "SourceVersion",
        "PresenceStatus",
        "TranslationRequired",
        "ProtectedTokens",
    ]
    if mode == "blind-first":
        fields = common + [
            "Context",
            "GlossaryReference",
            "IndependentTargetText",
            "TranslationStatus",
            "TranslatorNotes",
            "TranslatorName",
        ]
        return fields, ["IndependentTargetText", "TranslationStatus", "TranslatorNotes", "TranslatorName"]

    fields = common + ["ExistingTargetText", "TargetVersion"]
    fields.extend(f"ReferenceText[{locale_id}]" for locale_id in reference_locales)
    if mode == "context":
        fields.append("Context")
    fields.extend(["TranslatedTargetText", "TranslationStatus", "TranslatorNotes", "TranslatorName"])
    return fields, ["TranslatedTargetText", "TranslationStatus", "TranslatorNotes", "TranslatorName"]


def build_material_row(
    aligned: dict[str, Any],
    *,
    mode: str,
    source_locale: str,
    target_locale: str,
    reference_locales: list[str],
    context: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    content_uid = str(aligned["contentUid"])
    locales = aligned.get("locales", {})
    if not isinstance(locales, dict):
        raise BuildFailure(26, "PROTECTED_FIELD_CONTRACT_FAILED", f"Invalid locale map for {content_uid}")
    source = locales.get(source_locale)
    target = locales.get(target_locale)
    source_text = "" if source is None else str(source.get("text", ""))
    source_version = None if source is None else source.get("version")
    target_text = "" if target is None else str(target.get("text", ""))
    target_version = None if target is None else target.get("version")

    if source is not None and target is not None:
        presence = "source+target"
    elif source is not None:
        presence = "source-only"
    else:
        presence = "target-only"

    protected = extract_protected_tokens(source_text)
    common: dict[str, Any] = {
        "ContentUid": content_uid,
        "SourceLocale": source_locale,
        "SourceText": source_text,
        "TargetLocale": target_locale,
        "SourceVersion": source_version,
        "PresenceStatus": presence,
        "TranslationRequired": source is not None,
        "ProtectedTokens": json.dumps(protected, ensure_ascii=False, separators=(",", ":")),
    }

    immutable: dict[str, Any] = {
        "ContentUid": content_uid,
        "SourceLocale": source_locale,
        "SourceText": source_text,
        "SourceVersion": source_version,
        "TargetLocale": target_locale,
        "ExistingTargetText": target_text,
        "TargetVersion": target_version,
        "PresenceStatus": presence,
        "TranslationRequired": source is not None,
        "ProtectedTokens": protected,
        "References": {
            locale_id: locales.get(locale_id)
            for locale_id in reference_locales
        },
        "Context": context,
    }

    if mode == "blind-first":
        row = dict(common)
        row.update({
            "Context": serialize_cell(context),
            "GlossaryReference": "support/glossary",
            "IndependentTargetText": "",
            "TranslationStatus": "",
            "TranslatorNotes": "",
            "TranslatorName": "",
        })
        return row, immutable

    row = dict(common)
    row.update({
        "ExistingTargetText": target_text,
        "TargetVersion": target_version,
    })
    for locale_id in reference_locales:
        ref = locales.get(locale_id)
        row[f"ReferenceText[{locale_id}]"] = "" if ref is None else str(ref.get("text", ""))
    if mode == "context":
        row["Context"] = serialize_cell(context)
    row.update({
        "TranslatedTargetText": "",
        "TranslationStatus": "",
        "TranslatorNotes": "",
        "TranslatorName": "",
    })
    return row, immutable


def load_keyed_support_data(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.casefold() == ".jsonl":
        rows = read_jsonl(path)
        result: dict[str, Any] = {}
        for row in rows:
            content_uid = row.get("contentUid") or row.get("ContentUid")
            if not content_uid:
                raise ValueError("support JSONL row is missing contentUid")
            key = str(content_uid)
            if key in result:
                raise ValueError(f"duplicate support ContentUid: {key}")
            result[key] = row
        return result

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return {str(key): value for key, value in data.items()}
    if isinstance(data, list):
        result = {}
        for row in data:
            if not isinstance(row, dict):
                raise ValueError("support JSON array must contain objects")
            content_uid = row.get("contentUid") or row.get("ContentUid")
            if not content_uid:
                raise ValueError("support JSON row is missing contentUid")
            key = str(content_uid)
            if key in result:
                raise ValueError(f"duplicate support ContentUid: {key}")
            result[key] = row
        return result
    raise ValueError("support data must be a JSON object, array, or JSONL")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL line {line_number} is not an object")
            rows.append(value)
    return rows


def write_material(path: Path, format_name: str, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if format_name == "jsonl":
        write_jsonl(path, rows)
        return
    if format_name == "csv":
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({field: serialize_cell(row.get(field)) for field in fields})
        tmp.replace(path)
        return
    if format_name == "xlsx":
        workbook = Workbook(write_only=False)
        sheet = workbook.active
        sheet.title = "Translation"
        sheet.append(fields)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in rows:
            values = [serialize_cell(row.get(field)) for field in fields]
            for field, value in zip(fields, values, strict=True):
                if isinstance(value, str) and len(value) > 32767:
                    raise ValueError(f"XLSX cell exceeds 32767 characters: {field}")
            sheet.append(values)
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        tmp = path.with_suffix(path.suffix + ".tmp")
        workbook.save(tmp)
        tmp.replace(path)
        return
    raise ValueError(f"Unsupported material format: {format_name}")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(path)


def serialize_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_input_path(raw: str, manifest_dir: Path) -> Path:
    candidate = Path(raw).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    relative = manifest_dir / candidate
    if relative.is_file():
        return relative.resolve()
    raise FileNotFoundError(raw)


def _copy_support_file(source: Path, destination_dir: Path) -> Path:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    shutil.copy2(source, destination)
    return destination


def _validate_unique_content_uids(rows: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for row in rows:
        content_uid = str(row.get("contentUid", ""))
        if not content_uid:
            raise BuildFailure(25, "IDENTITY_DUPLICATION_DETECTED", "aligned row is missing ContentUid")
        if content_uid in seen:
            raise BuildFailure(25, "IDENTITY_DUPLICATION_DETECTED", f"Duplicate ContentUid: {content_uid}")
        seen.add(content_uid)
