from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Iterable

from bg3loc.builder import write_material
from bg3loc.io import read_json, write_json
from bg3loc.protected_syntax import extract_protected_tokens
from bg3loc.schema import SchemaStore


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as stream:
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


def resolve_extract_aligned(extract_manifest: Path) -> tuple[dict[str, Any], Path]:
    extract = read_json(extract_manifest)
    SchemaStore().validate("extract-manifest.schema.json", extract)
    raw = Path(str(extract["aligned"])).expanduser()
    candidates = [raw]
    if not raw.is_absolute():
        candidates.append(extract_manifest.parent / raw)
    for candidate in candidates:
        if candidate.is_file():
            return extract, candidate.resolve()
    raise FileNotFoundError(f"Aligned localization records not found: {extract['aligned']}")


def build_neighbor_context(
    extract_manifest: Path,
    output: Path,
) -> Path:
    extract, aligned = resolve_extract_aligned(extract_manifest)
    source_locale = str(extract["sourceLocale"])
    rows = read_jsonl(aligned)
    source_texts: list[tuple[str, str]] = []
    for row in rows:
        uid = str(row.get("contentUid", ""))
        locales = row.get("locales", {})
        source = locales.get(source_locale) if isinstance(locales, dict) else None
        text = "" if source is None else str(source.get("text", ""))
        source_texts.append((uid, text))

    evidence: list[dict[str, Any]] = []
    for index, (uid, text) in enumerate(source_texts):
        if not uid or not text:
            continue
        previous = source_texts[index - 1][1] if index > 0 else ""
        following = source_texts[index + 1][1] if index + 1 < len(source_texts) else ""
        if not previous and not following:
            continue
        evidence.append({
            "contentUid": uid,
            "evidenceType": "context",
            "summary": "Adjacent source localization context",
            "classification": "AdjacentSourceContext",
            "payload": {
                "previousSourceText": previous,
                "nextSourceText": following,
            },
            "provenance": {
                "source": "extract-aligned-order",
            },
        })
    SchemaStore().load("translation-evidence-record.schema.json")
    for item in evidence:
        SchemaStore().validate("translation-evidence-record.schema.json", item)
    write_jsonl(output, evidence)
    return output


def research_evidence_sidecars(
    research_dir: Path,
    output_dir: Path,
    *,
    blind_first: bool,
) -> dict[str, Path]:
    mappings_path = research_dir / "research-mappings.jsonl"
    if not mappings_path.is_file():
        raise FileNotFoundError(mappings_path)
    mappings = read_jsonl(mappings_path)
    buckets: dict[str, list[dict[str, Any]]] = {
        "context": [],
        "bark": [],
        "quest": [],
        "ui-skill": [],
        "multilingual": [],
    }

    def classify(mapping_type: str, classification: str) -> str:
        mt = mapping_type.casefold()
        cl = classification.casefold()
        if "multilingual" in mt or "exactreuse" in cl:
            return "multilingual"
        if "bark" in mt or "speaker" in cl:
            return "bark"
        if "quest" in mt or cl.startswith("quest"):
            return "quest"
        if "ui-skill" in mt or "ability" in cl or "item" in cl or "userinterface" in cl or "tutorial" in cl:
            return "ui-skill"
        return "context"

    for mapping in mappings:
        uid = str(mapping.get("contentUid", ""))
        if not uid:
            continue
        mapping_type = str(mapping.get("mappingType", ""))
        classification = str(mapping.get("classification", ""))
        evidence_type = classify(mapping_type, classification)
        evidence_rows = mapping.get("evidence", [])
        if blind_first:
            payload: dict[str, Any] = {
                "mappingType": mapping_type,
                "classification": classification,
                "reviewRequired": bool(mapping.get("reviewRequired")),
                "evidence": [
                    {
                        "sourceRole": item.get("sourceRole"),
                        "resourcePath": item.get("resourcePath"),
                        "evidenceType": item.get("evidenceType"),
                        "ruleId": item.get("ruleId"),
                    }
                    for item in evidence_rows
                    if isinstance(item, dict)
                ],
            }
        else:
            payload = {
                "mappingType": mapping_type,
                "classification": classification,
                "reviewRequired": bool(mapping.get("reviewRequired")),
                "evidence": evidence_rows,
                "metadata": mapping.get("metadata", {}),
            }
        record = {
            "contentUid": uid,
            "evidenceType": evidence_type,
            "summary": classification or mapping_type,
            "classification": classification,
            "payload": payload,
            "provenance": {"source": "research-mappings"},
        }
        SchemaStore().validate("translation-evidence-record.schema.json", record)
        buckets[evidence_type].append(record)

    ui_universe = research_dir / "ui-skill-universe.csv"
    if ui_universe.is_file():
        by_uid: dict[str, list[dict[str, str]]] = {}
        with ui_universe.open("r", encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                uid = str(row.get("ContentUid", ""))
                if uid:
                    by_uid.setdefault(uid, []).append(dict(row))
        for uid, relations in sorted(by_uid.items()):
            record = {
                "contentUid": uid,
                "evidenceType": "ui-skill",
                "summary": f"UI / Skill semantic evidence: {len(relations)} relation(s)",
                "classification": "UiSkillSemanticRelations",
                "payload": {"relations": relations},
                "provenance": {"source": "ui-skill-universe.csv"},
            }
            SchemaStore().validate("translation-evidence-record.schema.json", record)
            buckets["ui-skill"].append(record)

    result: dict[str, Path] = {}
    output_dir.mkdir(parents=True, exist_ok=True)
    for evidence_type, records in buckets.items():
        if not records:
            continue
        path = output_dir / f"{evidence_type}.jsonl"
        write_jsonl(path, records)
        result[evidence_type] = path
    return result



_FORBIDDEN_BLIND_KEYS = {
    "existingtargettext",
    "referencetexts",
    "officialtarget",
    "referencecomparison",
    "exactreusecandidates",
    "approvedauthority",
    "finaltext",
    "retainexisting",
}


def _blind_delivery_record_safe(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).replace("_", "").replace("-", "").casefold()
            if normalized in _FORBIDDEN_BLIND_KEYS:
                return False
            if not _blind_delivery_record_safe(item):
                return False
        return True
    if isinstance(value, list):
        return all(_blind_delivery_record_safe(item) for item in value)
    return True


def prepare_translation_package(
    *,
    extract_manifest: Path,
    project_config_sha256: str,
    evidence_profile: str,
    translation_strategy: str,
    material_format: str,
    max_rows: int,
    output_dir: Path,
    evidence_files: dict[str, Path] | None = None,
    glossary: Path | None = None,
    research_summary: Path | None = None,
    research_mappings: Path | None = None,
    scope_content_uids: set[str] | None = None,
) -> dict[str, Any]:
    extract, aligned_path = resolve_extract_aligned(extract_manifest)
    aligned = read_jsonl(aligned_path)
    if scope_content_uids is not None:
        available_uids = {str(row.get("contentUid", "")) for row in aligned}
        missing_scope = sorted(scope_content_uids - available_uids)
        if missing_scope:
            preview = ", ".join(missing_scope[:10])
            suffix = "" if len(missing_scope) <= 10 else f" (+{len(missing_scope) - 10} more)"
            raise ValueError(f"Scoped ContentUid not found in extracted localization: {preview}{suffix}")
        aligned = [
            row
            for row in aligned
            if str(row.get("contentUid", "")) in scope_content_uids
        ]
        if not aligned:
            raise ValueError("Project scope selected zero localization rows")
    scoped_uid_set = {
        str(row.get("contentUid", ""))
        for row in aligned
        if str(row.get("contentUid", ""))
    }
    source_locale = str(extract["sourceLocale"])
    target_locale = str(extract["targetLocale"])
    references = [str(item) for item in extract.get("referenceLocales", [])]
    blind = translation_strategy == "blind-first"

    package_root = output_dir.with_name(f".{output_dir.name}.staging")
    if package_root.exists():
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True, exist_ok=True)
    delivery_materials = package_root / "delivery" / "materials"
    delivery_evidence = package_root / "delivery" / "evidence"
    internal_immutable = package_root / "internal" / "immutable"
    internal_comparison = package_root / "internal" / "comparison"

    evidence_files = evidence_files or {}
    evidence_by_uid: dict[str, list[dict[str, Any]]] = {}
    copied_evidence: list[dict[str, Any]] = []
    delivery_evidence_records: list[dict[str, Any]] = []
    for evidence_type, source_path in sorted(evidence_files.items()):
        records = [
            record
            for record in read_jsonl(source_path)
            if str(record.get("contentUid", "")) in scoped_uid_set
        ]
        delivery_evidence_records.extend(records)
        for record in records:
            uid = str(record.get("contentUid", ""))
            if uid:
                evidence_by_uid.setdefault(uid, []).append(record)
        destination = delivery_evidence / source_path.name
        write_jsonl(destination, records)
        copied_evidence.append({
            "path": str(destination.relative_to(package_root).as_posix()),
            "sha256": sha256_file(destination),
            "recordCount": len(records),
            "evidenceType": evidence_type,
        })

    rows: list[dict[str, Any]] = []
    immutable_rows: list[dict[str, Any]] = []
    comparison_rows: list[dict[str, Any]] = []
    required_count = 0
    for aligned_row in aligned:
        uid = str(aligned_row.get("contentUid", ""))
        if not uid:
            raise ValueError("Aligned row is missing contentUid")
        locales = aligned_row.get("locales", {})
        if not isinstance(locales, dict):
            raise ValueError(f"Invalid locale map for {uid}")
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
        translation_required = source is not None
        required_count += int(translation_required)
        protected = extract_protected_tokens(source_text)
        uid_evidence = evidence_by_uid.get(uid, [])
        flags = sorted({str(item.get("evidenceType")) for item in uid_evidence if item.get("evidenceType")})
        summaries = [str(item.get("summary", "")).strip() for item in uid_evidence if str(item.get("summary", "")).strip()]
        reference_texts = {
            locale_id: "" if locales.get(locale_id) is None else str(locales[locale_id].get("text", ""))
            for locale_id in references
        }

        row: dict[str, Any] = {
            "ContentUid": uid,
            "SourceLocale": source_locale,
            "SourceText": source_text,
            "TargetLocale": target_locale,
            "PresenceStatus": presence,
            "TranslationRequired": translation_required,
            "ProtectedTokens": protected,
            "EvidenceFlags": flags,
            "ContextSummary": " | ".join(dict.fromkeys(summaries)),
            "ProposedTargetText": "",
            "TranslationStatus": "",
            "TranslatorNotes": "",
            "TranslatorName": "",
        }
        if not blind:
            row["ExistingTargetText"] = target_text
            row["ReferenceTexts"] = reference_texts
        SchemaStore().validate("translation-material-row.schema.json", row)
        rows.append(row)

        immutable_rows.append({
            "ContentUid": uid,
            "SourceLocale": source_locale,
            "SourceText": source_text,
            "SourceVersion": source_version,
            "TargetLocale": target_locale,
            "PresenceStatus": presence,
            "TranslationRequired": translation_required,
            "ProtectedTokens": protected,
            "ExistingTargetText": target_text,
            "TargetVersion": target_version,
            "ReferenceTexts": reference_texts,
            "EvidenceFlags": flags,
            "ContextSummary": " | ".join(dict.fromkeys(summaries)),
        })
        comparison_rows.append({
            "ContentUid": uid,
            "ExistingTargetText": target_text,
            "ReferenceTexts": reference_texts,
        })

    visible_fields = [
        "ContentUid", "SourceLocale", "SourceText", "TargetLocale",
        "PresenceStatus", "TranslationRequired", "ProtectedTokens",
        "EvidenceFlags", "ContextSummary",
    ]
    if not blind:
        visible_fields += ["ExistingTargetText", "ReferenceTexts"]
    visible_fields += ["ProposedTargetText", "TranslationStatus", "TranslatorNotes", "TranslatorName"]

    material_artifacts: list[dict[str, Any]] = []
    immutable_artifacts: list[dict[str, Any]] = []
    for index, start in enumerate(range(0, len(rows), max_rows), start=1):
        batch = rows[start:start + max_rows]
        immutable_batch = immutable_rows[start:start + max_rows]
        batch_id = f"{index:03d}"
        material_path = delivery_materials / f"{batch_id}.{material_format}"
        immutable_path = internal_immutable / f"{batch_id}.jsonl"
        write_material(material_path, material_format, visible_fields, batch)
        write_jsonl(immutable_path, immutable_batch)
        material_artifacts.append({
            "path": str(material_path.relative_to(package_root).as_posix()),
            "sha256": sha256_file(material_path),
            "recordCount": len(batch),
        })
        immutable_artifacts.append({
            "path": str(immutable_path.relative_to(package_root).as_posix()),
            "sha256": sha256_file(immutable_path),
            "recordCount": len(immutable_batch),
        })

    comparison_path = internal_comparison / "comparison.jsonl"
    write_jsonl(comparison_path, comparison_rows)
    comparison_artifacts = [{
        "path": str(comparison_path.relative_to(package_root).as_posix()),
        "sha256": sha256_file(comparison_path),
        "recordCount": len(comparison_rows),
    }]

    support_artifacts: list[dict[str, Any]] = []
    if glossary is not None:
        destination = package_root / "delivery" / "support" / glossary.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(glossary, destination)
        support_artifacts.append({
            "path": str(destination.relative_to(package_root).as_posix()),
            "sha256": sha256_file(destination),
        })

    blind_separated = (
        not blind
        or (
            all(_blind_delivery_record_safe(row) for row in rows)
            and all(_blind_delivery_record_safe(record) for record in delivery_evidence_records)
        )
    )
    if blind and not blind_separated:
        raise ValueError("blind-first delivery contains forbidden comparison evidence")

    source_binding = {
        "extractManifestSha256": sha256_file(extract_manifest),
        "researchSummarySha256": sha256_file(research_summary) if research_summary and research_summary.is_file() else None,
        "researchMappingsSha256": sha256_file(research_mappings) if research_mappings and research_mappings.is_file() else None,
    }
    manifest = {
        "schemaVersion": "1.0",
        "packageType": "E2ETranslationPackage",
        "projectConfigSha256": project_config_sha256,
        "evidenceProfile": evidence_profile,
        "translationStrategy": translation_strategy,
        "sourceLocale": source_locale,
        "targetLocale": target_locale,
        "referenceLocales": references,
        "identityField": "ContentUid",
        "materialFormat": material_format,
        "scope": (
            {"type": "all"}
            if scope_content_uids is None
            else {
                "type": "content-uids",
                "contentUidCount": len(scope_content_uids),
                "contentUidsSha256": hashlib.sha256(
                    "\n".join(sorted(scope_content_uids)).encode("utf-8")
                ).hexdigest(),
            }
        ),
        "counts": {
            "rows": len(rows),
            "uniqueContentUids": len({row["ContentUid"] for row in rows}),
            "translationRequired": required_count,
        },
        "sourceBinding": source_binding,
        "delivery": {
            "materials": material_artifacts,
            "evidence": copied_evidence,
            "support": support_artifacts,
        },
        "internal": {
            "immutable": immutable_artifacts,
            "comparison": comparison_artifacts,
            "bindings": [],
        },
        "validation": {
            "uniqueEditableIdentity": len(rows) == len({row["ContentUid"] for row in rows}),
            "blindFirstDeliverySeparated": blind_separated,
            "packageRelativePaths": True,
        },
    }
    SchemaStore().validate("translation-package.schema.json", manifest)
    write_json(package_root / "translation-package-manifest.json", manifest)

    if output_dir.exists():
        shutil.rmtree(output_dir)
    package_root.replace(output_dir)
    return manifest
