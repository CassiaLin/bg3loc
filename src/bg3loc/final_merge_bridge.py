from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from bg3loc.io import read_json, write_json
from bg3loc.qa import QA_RULESET_VERSION
from bg3loc.production_completion import (
    DISPOSITION_MERGE_READY,
    build_production_completion_view,
)
from bg3loc.rebuilder import resolve_reference
from bg3loc.schema import SchemaStore


class FinalMergeBridgeError(RuntimeError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_no, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise FinalMergeBridgeError(
                    f"{path}:{line_no}: expected JSON object"
                )
            rows.append(value)
    return rows


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
    tmp.replace(path)


def _index_normalized(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        uid = str(row.get("contentUid", ""))
        if not uid:
            raise FinalMergeBridgeError(f"normalized row missing contentUid: {path}")
        if uid in result:
            raise FinalMergeBridgeError(
                f"duplicate ContentUid in normalized locale: {uid}"
            )
        result[uid] = row
    return result


def _find_locale(manifest: dict[str, Any], locale_id: str) -> dict[str, Any]:
    matches = [
        item
        for item in manifest.get("locales", [])
        if str(item.get("localeId", "")).casefold() == locale_id.casefold()
    ]
    if len(matches) != 1:
        raise FinalMergeBridgeError(
            f"expected one locale record for {locale_id}; found {len(matches)}"
        )
    return matches[0]


def build_final_merge_bridge(
    *,
    db_path: str | Path,
    batch_plan_path: str | Path,
    extract_manifest_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    db = Path(db_path)
    batch_plan = Path(batch_plan_path)
    extract_manifest = Path(extract_manifest_path)
    output = Path(output_dir)

    if not db.is_file():
        raise FinalMergeBridgeError(f"execution database not found: {db}")
    if not extract_manifest.is_file():
        raise FinalMergeBridgeError(
            f"extract manifest not found: {extract_manifest}"
        )

    completion = build_production_completion_view(db, batch_plan)

    try:
        with batch_plan.open("r", encoding="utf-8-sig") as stream:
            batch_plan_data = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise FinalMergeBridgeError(f"invalid batch plan: {exc}") from exc
    batch_plan_fingerprint = str(
        batch_plan_data.get("batchPlanFingerprint", "")
    )
    if not batch_plan_fingerprint:
        raise FinalMergeBridgeError("batch plan is missing batchPlanFingerprint")
    ready = [
        row
        for row in completion.rows
        if row.disposition == DISPOSITION_MERGE_READY
    ]

    try:
        extract = read_json(extract_manifest)
        SchemaStore().validate("extract-manifest.schema.json", extract)
    except Exception as exc:
        raise FinalMergeBridgeError(f"invalid extract manifest: {exc}") from exc

    source_locale = str(extract["sourceLocale"])
    target_locale = str(extract["targetLocale"])
    source_info = _find_locale(extract, source_locale)
    target_info = _find_locale(extract, target_locale)

    try:
        source_normalized = resolve_reference(
            str(source_info["normalized"]),
            extract_manifest.parent,
            "normalized",
        )
        target_normalized = resolve_reference(
            str(target_info["normalized"]),
            extract_manifest.parent,
            "normalized",
        )
    except Exception as exc:
        raise FinalMergeBridgeError(
            f"unable to resolve normalized locale data: {exc}"
        ) from exc

    source_rows = _index_normalized(source_normalized)
    target_rows = _index_normalized(target_normalized)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    with closing(conn):
        state_rows = conn.execute(
            "SELECT content_uid, translated_text, output_hash "
            "FROM content_state ORDER BY content_uid"
        ).fetchall()
    state_by_uid = {str(row["content_uid"]): row for row in state_rows}

    accepted: list[dict[str, Any]] = []
    merge_ready_export: list[dict[str, Any]] = []
    for item in ready:
        uid = item.content_uid
        state = state_by_uid.get(uid)
        if state is None:
            raise FinalMergeBridgeError(
                f"MERGE_READY ContentUid missing execution state: {uid}"
            )
        text = state["translated_text"]
        output_hash = str(state["output_hash"] or "")
        if not isinstance(text, str):
            raise FinalMergeBridgeError(
                f"MERGE_READY ContentUid has no translated text: {uid}"
            )
        actual_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if not output_hash or actual_hash != output_hash:
            raise FinalMergeBridgeError(
                f"MERGE_READY output hash mismatch: {uid}"
            )

        authoritative = target_rows.get(uid)
        version_source = "target"
        if authoritative is None:
            authoritative = source_rows.get(uid)
            version_source = "source"
        if authoritative is None:
            raise FinalMergeBridgeError(
                f"MERGE_READY ContentUid missing from source and target extraction: {uid}"
            )
        try:
            version = int(authoritative["version"])
        except (KeyError, TypeError, ValueError) as exc:
            raise FinalMergeBridgeError(
                f"authoritative version invalid for {uid}"
            ) from exc

        accepted.append({
            "contentUid": uid,
            "localeId": target_locale,
            "text": text,
            "version": version,
        })
        merge_ready_export.append({
            "ContentUid": uid,
            "outputHash": output_hash,
            "versionSource": version_source,
            "version": version,
        })

    accepted.sort(key=lambda row: str(row["contentUid"]))
    merge_ready_export.sort(key=lambda row: str(row["ContentUid"]))

    output.mkdir(parents=True, exist_ok=True)
    accepted_path = output / "accepted-target.jsonl"
    rejected_path = output / "rejected-empty.jsonl"
    ready_path = output / "merge-ready-binding.jsonl"
    validate_path = output / "validate-manifest.json"
    bridge_path = output / "bridge-manifest.json"

    _write_jsonl(accepted_path, accepted)
    _write_jsonl(rejected_path, [])
    _write_jsonl(ready_path, merge_ready_export)

    validate_manifest = {
        "schemaVersion": "1.0",
        "buildManifest": str(extract_manifest),
        "strict": True,
        "accepted": {
            "path": str(accepted_path),
            "recordCount": len(accepted),
        },
        "rejected": {
            "path": str(rejected_path),
            "recordCount": 0,
        },
        "summary": {
            "status": "pass",
            "errorCount": 0,
            "warningCount": 0,
            "missingReturnRowCount": 0,
        },
    }
    SchemaStore().validate("validate-manifest.schema.json", validate_manifest)
    write_json(validate_path, validate_manifest)

    bridge_manifest = {
        "schemaVersion": "1.0",
        "batchPlan": str(batch_plan),
        "batchPlanFingerprint": batch_plan_fingerprint,
        "batchPlanSha256": _sha256_file(batch_plan),
        "executionDatabase": str(db),
        "executionDatabaseSha256": _sha256_file(db),
        "qaRuleSetVersion": QA_RULESET_VERSION,
        "extractManifest": str(extract_manifest),
        "extractManifestSha256": _sha256_file(extract_manifest),
        "sourceLocale": source_locale,
        "targetLocale": target_locale,
        "mergeReadyCount": len(accepted),
        "mergeReadyBinding": {
            "path": str(ready_path),
            "sha256": _sha256_file(ready_path),
        },
        "acceptedTarget": {
            "path": str(accepted_path),
            "sha256": _sha256_file(accepted_path),
        },
        "validateManifest": {
            "path": str(validate_path),
            "sha256": _sha256_file(validate_path),
        },
    }
    write_json(bridge_path, bridge_manifest)
    return bridge_manifest