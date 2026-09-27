from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

RULE_REUSE_CONFLICT = "BG3-MULTILINGUAL-REUSE-CONFLICT"


@dataclass(slots=True)
class ConflictGroup:
    group_id: str
    source_text: str
    member_uids: list[str] = field(default_factory=list)
    distinct_target_translations: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ConflictAnalysisResult:
    source_only_count: int
    shared_count: int
    conflict_items_count: int
    conflict_groups: list[ConflictGroup]
    conflict_001: ConflictGroup | None
    conflict_001_uids: set[str]
    all_conflict_uids: set[str]
    single_reuse_count: int
    consensus_reuse_count: int
    no_candidate_count: int


def derive_reuse_conflict_groups(
    source_records: Mapping[str, str],
    target_records: Mapping[str, str]
) -> ConflictAnalysisResult:
    """
    Derive exact source-target alignment, reverse source-text reuse index,
    and conflicting target translation groups (including CONFLICT-001).
    """
    source_uids = set(source_records.keys())
    target_uids = set(target_records.keys())

    shared_uids = source_uids & target_uids
    source_only_uids = source_uids - target_uids

    # Build reverse lookup index for shared entries: source_text -> set of target translations
    shared_by_text: dict[str, set[str]] = {}
    shared_entries_by_text: dict[str, int] = {}
    for uid in shared_uids:
        src_text = source_records[uid]
        tgt_text = target_records[uid]
        shared_by_text.setdefault(src_text, set()).add(tgt_text)
        shared_entries_by_text[src_text] = shared_entries_by_text.get(src_text, 0) + 1

    single_count = 0
    consensus_count = 0
    no_cand_count = 0

    conflict_by_text: dict[str, list[str]] = {}

    for uid in sorted(source_only_uids):
        src_text = source_records[uid]
        target_texts = shared_by_text.get(src_text)
        if not target_texts:
            no_cand_count += 1
        elif len(target_texts) == 1:
            total_shared = shared_entries_by_text.get(src_text, 0)
            if total_shared == 1:
                single_count += 1
            else:
                consensus_count += 1
        else:
            conflict_by_text.setdefault(src_text, []).append(uid)

    # Sort conflict groups by member count descending, then by source text ascending
    sorted_groups = sorted(
        conflict_by_text.items(),
        key=lambda kv: (-len(kv[1]), kv[0])
    )

    groups: list[ConflictGroup] = []
    conflict_001: ConflictGroup | None = None
    all_conflict_uids: set[str] = set()

    for idx, (text, uids) in enumerate(sorted_groups, start=1):
        gid = f"CONFLICT-{idx:03d}"
        distinct_translations = sorted(shared_by_text[text])
        cg = ConflictGroup(
            group_id=gid,
            source_text=text,
            member_uids=uids,
            distinct_target_translations=distinct_translations
        )
        groups.append(cg)
        all_conflict_uids.update(uids)
        if idx == 1:
            conflict_001 = cg

    conflict_001_uids = set(conflict_001.member_uids) if conflict_001 else set()

    return ConflictAnalysisResult(
        source_only_count=len(source_only_uids),
        shared_count=len(shared_uids),
        conflict_items_count=len(all_conflict_uids),
        conflict_groups=groups,
        conflict_001=conflict_001,
        conflict_001_uids=conflict_001_uids,
        all_conflict_uids=all_conflict_uids,
        single_reuse_count=single_count,
        consensus_reuse_count=consensus_count,
        no_candidate_count=no_cand_count,
    )
