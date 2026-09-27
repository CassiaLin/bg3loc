from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import PurePosixPath
from typing import Iterable, Mapping, Sequence


BATCHING_RULE_VERSION = "1.0"

DEFAULT_MAX_RECORDS: dict[str, int] = {
    "dialogue_general": 1000,
    "bark": 750,
    "quest": 500,
    "skill_spell": 500,
    "item": 500,
    "ui": 500,
    "tutorial": 400,
    "system_message": 400,
    "book_lore": 250,
    "character_world": 500,
}


@dataclass(frozen=True, slots=True)
class BatchInputRecord:
    content_uid: str
    source_text: str
    primary_category: str
    classification_status: str
    group_candidates: tuple[str, ...] = ()
    subkeys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BatchRecord:
    contentUid: str
    sourceText: str
    translationText: str
    primaryCategory: str
    batchId: str
    canonicalGroupKey: str
    contextGroupKeys: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["contextGroupKeys"] = list(self.contextGroupKeys)
        return data


@dataclass(frozen=True, slots=True)
class BatchManifest:
    batchId: str
    primaryCategory: str
    recordCount: int
    contentUids: tuple[str, ...]
    groupKeys: tuple[str, ...]
    batchingRuleVersion: str
    oversizeGroupSplit: bool = False

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["contentUids"] = list(self.contentUids)
        data["groupKeys"] = list(self.groupKeys)
        return data


@dataclass(frozen=True, slots=True)
class BatchPlan:
    batches: tuple[BatchManifest, ...]
    records_by_batch: Mapping[str, tuple[BatchRecord, ...]]
    unresolved_uids: tuple[str, ...]
    excluded_uids: tuple[str, ...] = ()

    @property
    def batched_uids(self) -> tuple[str, ...]:
        return tuple(
            record.contentUid
            for manifest in self.batches
            for record in self.records_by_batch[manifest.batchId]
        )


def _normalize_group_key(value: str) -> str:
    return value.replace("\\", "/").strip().casefold()


def normalize_dialog_resource(path: str) -> str:
    normalized = path.replace("\\", "/").strip().casefold()
    marker_binary = "/story/dialogsbinary/"
    marker_raw = "/story/dialogs/"
    relative = ""
    if marker_binary in normalized:
        relative = normalized.split(marker_binary, 1)[1]
    elif marker_raw in normalized:
        relative = normalized.split(marker_raw, 1)[1]
    else:
        relative = normalized.lstrip("/")
    pure = PurePosixPath(relative)
    without_suffix = str(pure.with_suffix("")) if pure.suffix in {".lsf", ".lsj"} else str(pure)
    return f"dialog:{without_suffix}"


def canonical_group_key(record: BatchInputRecord) -> str:
    candidates = sorted({
        _normalize_group_key(value)
        for value in record.group_candidates
        if value and value.strip()
    })
    return candidates[0] if candidates else f"uid:{record.content_uid.casefold()}"


def _stable_record_key(record: BatchInputRecord) -> tuple[tuple[str, ...], str]:
    return (
        tuple(sorted(_normalize_group_key(value) for value in record.subkeys if value)),
        record.content_uid.casefold(),
    )


def build_batch_plan(
    records: Iterable[BatchInputRecord],
    *,
    max_records: Mapping[str, int] | None = None,
) -> BatchPlan:
    limits = dict(DEFAULT_MAX_RECORDS)
    if max_records:
        for category, value in max_records.items():
            if value <= 0:
                raise ValueError(f"maxRecords must be positive for {category}")
            limits[category] = int(value)

    items = list(records)
    seen: set[str] = set()
    for item in items:
        if item.content_uid in seen:
            raise ValueError(f"duplicate ContentUid in batching input: {item.content_uid}")
        seen.add(item.content_uid)

    excluded = tuple(sorted(
        (
            item.content_uid
            for item in items
            if item.classification_status == "excluded"
        ),
        key=str.casefold,
    ))
    unresolved = tuple(sorted(
        (
            item.content_uid
            for item in items
            if item.classification_status != "excluded"
            and (
                item.classification_status != "classified"
                or item.primary_category == "other"
            )
        ),
        key=str.casefold,
    ))
    eligible = [
        item
        for item in items
        if item.classification_status == "classified"
        and item.primary_category != "other"
    ]

    by_category: dict[str, list[BatchInputRecord]] = {}
    for item in eligible:
        if item.primary_category not in limits:
            raise ValueError(f"no maxRecords configured for category {item.primary_category}")
        by_category.setdefault(item.primary_category, []).append(item)

    manifests: list[BatchManifest] = []
    records_by_batch: dict[str, tuple[BatchRecord, ...]] = {}

    for category in sorted(by_category):
        limit = limits[category]
        grouped: dict[str, list[BatchInputRecord]] = {}
        context_keys: dict[str, tuple[str, ...]] = {}
        for item in by_category[category]:
            key = canonical_group_key(item)
            grouped.setdefault(key, []).append(item)
            context_keys[item.content_uid] = tuple(sorted({
                _normalize_group_key(value)
                for value in item.group_candidates
                if value and value.strip()
            }))

        units: list[tuple[str, list[BatchInputRecord], bool]] = []
        for group_key in sorted(grouped):
            group_records = sorted(grouped[group_key], key=_stable_record_key)
            if len(group_records) <= limit:
                units.append((group_key, group_records, False))
                continue
            for start in range(0, len(group_records), limit):
                chunk = group_records[start:start + limit]
                chunk_key = f"{group_key}#part-{start // limit + 1:04d}"
                units.append((chunk_key, chunk, True))

        current: list[tuple[str, list[BatchInputRecord], bool]] = []
        current_count = 0
        packed: list[list[tuple[str, list[BatchInputRecord], bool]]] = []
        for unit in units:
            unit_count = len(unit[1])
            if current and current_count + unit_count > limit:
                packed.append(current)
                current = []
                current_count = 0
            current.append(unit)
            current_count += unit_count
        if current:
            packed.append(current)

        for ordinal, batch_units in enumerate(packed, start=1):
            batch_id = f"{category}-{ordinal:04d}"
            batch_records: list[BatchRecord] = []
            group_keys: list[str] = []
            oversize = False
            for group_key, unit_records, split_flag in batch_units:
                group_keys.append(group_key)
                oversize = oversize or split_flag
                canonical_base = group_key.split("#part-", 1)[0]
                for item in unit_records:
                    batch_records.append(BatchRecord(
                        contentUid=item.content_uid,
                        sourceText=item.source_text,
                        translationText="",
                        primaryCategory=category,
                        batchId=batch_id,
                        canonicalGroupKey=canonical_base,
                        contextGroupKeys=context_keys[item.content_uid],
                    ))
            content_uids = tuple(item.contentUid for item in batch_records)
            manifests.append(BatchManifest(
                batchId=batch_id,
                primaryCategory=category,
                recordCount=len(batch_records),
                contentUids=content_uids,
                groupKeys=tuple(group_keys),
                batchingRuleVersion=BATCHING_RULE_VERSION,
                oversizeGroupSplit=oversize,
            ))
            records_by_batch[batch_id] = tuple(batch_records)

    return BatchPlan(
        batches=tuple(manifests),
        records_by_batch=records_by_batch,
        unresolved_uids=unresolved,
        excluded_uids=excluded,
    )


def batch_plan_fingerprint(
    *,
    classification_sha256: str,
    source_sha256: str,
    config: Mapping[str, int],
    structural_input_sha256: Mapping[str, str],
) -> str:
    payload = {
        "batchingRuleVersion": BATCHING_RULE_VERSION,
        "classificationSHA256": classification_sha256,
        "sourceSHA256": source_sha256,
        "maxRecords": dict(sorted(config.items())),
        "structuralInputs": dict(sorted(structural_input_sha256.items())),
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
