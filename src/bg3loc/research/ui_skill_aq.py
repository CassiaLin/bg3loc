from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Mapping


class ReuseClassification(StrEnum):
    NO_EXACT_CANDIDATE = "NO_EXACT_CANDIDATE"
    EXACT_SINGLE = "EXACT_SINGLE"
    EXACT_CONSENSUS = "EXACT_CONSENSUS"
    EXACT_CONFLICT = "EXACT_CONFLICT"


@dataclass(frozen=True, slots=True)
class ReuseBoundaryRow:
    content_uid: str
    source_text: str
    classification: ReuseClassification
    shared_entry_count: int
    target_translations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReuseBoundaryResult:
    rows: tuple[ReuseBoundaryRow, ...]
    source_only_uids: frozenset[str]
    exact_conflict_uids: frozenset[str]

    @property
    def classification_counts(self) -> dict[str, int]:
        counts = {item.value: 0 for item in ReuseClassification}
        for row in self.rows:
            counts[row.classification.value] += 1
        return counts

    @property
    def exact_candidate_count(self) -> int:
        return sum(
            1 for row in self.rows
            if row.classification is not ReuseClassification.NO_EXACT_CANDIDATE
        )


def derive_reuse_conflict_boundary(
    source_records: Mapping[str, str],
    target_records: Mapping[str, str],
) -> ReuseBoundaryResult:
    """Derive exact-text reuse classifications without normalizing UID or text."""
    source_uids = set(source_records)
    target_uids = set(target_records)
    shared_uids = source_uids & target_uids
    source_only_uids = source_uids - target_uids

    translations_by_source_text: dict[str, set[str]] = {}
    shared_count_by_source_text: dict[str, int] = {}
    for uid in shared_uids:
        source_text = source_records[uid]
        translations_by_source_text.setdefault(source_text, set()).add(target_records[uid])
        shared_count_by_source_text[source_text] = shared_count_by_source_text.get(source_text, 0) + 1

    rows: list[ReuseBoundaryRow] = []
    conflicts: set[str] = set()
    for uid in sorted(source_only_uids):
        source_text = source_records[uid]
        translations = tuple(sorted(translations_by_source_text.get(source_text, ())))
        shared_count = shared_count_by_source_text.get(source_text, 0)
        if shared_count == 0:
            classification = ReuseClassification.NO_EXACT_CANDIDATE
        elif shared_count == 1:
            classification = ReuseClassification.EXACT_SINGLE
        elif len(translations) == 1:
            classification = ReuseClassification.EXACT_CONSENSUS
        else:
            classification = ReuseClassification.EXACT_CONFLICT
            conflicts.add(uid)
        rows.append(ReuseBoundaryRow(uid, source_text, classification, shared_count, translations))

    return ReuseBoundaryResult(
        rows=tuple(rows),
        source_only_uids=frozenset(source_only_uids),
        exact_conflict_uids=frozenset(conflicts),
    )


def accepted_context_coverage(
    *,
    shared_uids: Iterable[str] = (),
    passive_uids: Iterable[str] = (),
    dialog_bark_uids: Iterable[str] = (),
    quest_uids: Iterable[str] = (),
) -> frozenset[str]:
    """Union accepted deterministic evidence using ContentUid identity."""
    return frozenset(shared_uids) | frozenset(passive_uids) | frozenset(dialog_bark_uids) | frozenset(quest_uids)


def derive_aq_boundary(
    formal_exact_conflict_uids: Iterable[str],
    accepted_context_uids: Iterable[str],
) -> frozenset[str]:
    formal = frozenset(formal_exact_conflict_uids)
    accepted = frozenset(accepted_context_uids)
    outside = accepted - formal
    if outside:
        preview = ", ".join(sorted(outside)[:5])
        raise ValueError(f"accepted context ContentUid is outside formal conflict boundary: {preview}")
    return formal - accepted


def derive_aq_resource_referenced(
    aq_boundary_uids: Iterable[str],
    ui_skill_resource_uids: Iterable[str],
) -> frozenset[str]:
    return frozenset(aq_boundary_uids) & frozenset(ui_skill_resource_uids)
