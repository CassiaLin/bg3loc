from __future__ import annotations

from typing import Iterable, Iterator, Mapping

from bg3loc.research.model import ResearchEvidence, ResearchMapping

RULE_MULTILINGUAL_SAME_UID = "BG3-MULTILINGUAL-SAME-UID-REFERENCE"
RULE_MULTILINGUAL_EXACT_REUSE = "BG3-MULTILINGUAL-EXACT-REUSE-REFERENCE"


def align_multilingual_references(
    source_records: Mapping[str, str],
    *,
    target_records: Mapping[str, str] | None = None,
    reference_records_by_locale: Mapping[str, Mapping[str, str]] | None = None,
    target_boundary_uids: Iterable[str] | None = None,
) -> Iterator[ResearchMapping]:
    """Align a source-only review boundary with exact-reuse and same-UID references.

    The default review boundary is ``source - target``.  Shared source/target
    records outside that boundary form the deterministic exact-text reuse corpus.
    Every boundary UID yields one review mapping, even when no auxiliary evidence
    exists, so the review universe remains complete and auditable.
    """
    target = target_records or {}
    refs = reference_records_by_locale or {}
    boundary = (
        set(target_boundary_uids)
        if target_boundary_uids is not None
        else set(source_records) - set(target)
    )

    shared_text_to_target: dict[str, set[str]] = {}
    shared_occurrence_count: dict[str, int] = {}
    for uid, src_text in source_records.items():
        if uid in target and uid not in boundary:
            shared_text_to_target.setdefault(src_text, set()).add(target[uid])
            shared_occurrence_count[src_text] = shared_occurrence_count.get(src_text, 0) + 1

    for uid in sorted(boundary):
        src_text = source_records.get(uid, "")
        reusable_candidates = shared_text_to_target.get(src_text, set())
        occurrence_count = shared_occurrence_count.get(src_text, 0)
        evidences: list[ResearchEvidence] = []

        if not reusable_candidates:
            classification = "NoExactReuseCandidate"
            reference_type = "NO_EXACT_CANDIDATE"
        elif len(reusable_candidates) == 1 and occurrence_count == 1:
            classification = "ExactReuseSingle"
            reference_type = "EXACT_SINGLE"
        elif len(reusable_candidates) == 1:
            classification = "ExactReuseConsensus"
            reference_type = "EXACT_CONSENSUS"
        else:
            classification = "ExactReuseConflict"
            reference_type = "EXACT_CONFLICT"

        if reusable_candidates:
            evidences.append(
                ResearchEvidence(
                    sourceRole="TargetSharedReuse",
                    resourcePath="Localization/Target",
                    evidenceType=(
                        "ConflictingExactTextReference"
                        if reference_type == "EXACT_CONFLICT"
                        else "ReusableExactTextReference"
                    ),
                    ruleId=RULE_MULTILINGUAL_EXACT_REUSE,
                    properties={
                        "referenceType": reference_type,
                        "sharedOccurrenceCount": occurrence_count,
                        "distinctTargetTranslationCount": len(reusable_candidates),
                    },
                )
            )

        metadata_dict: dict[str, object] = {
            "referenceType": reference_type,
            "sharedOccurrenceCount": occurrence_count,
            "reusableTargetCount": len(reusable_candidates),
        }
        for ref_locale, ref_dict in sorted(refs.items()):
            has_same_uid = uid in ref_dict
            metadata_dict[f"hasSameUid{ref_locale}"] = has_same_uid
            if has_same_uid:
                evidences.append(
                    ResearchEvidence(
                        sourceRole=f"{ref_locale}Localization",
                        resourcePath=f"Localization/{ref_locale}",
                        evidenceType="SameUidAuxiliaryReference",
                        ruleId=RULE_MULTILINGUAL_SAME_UID,
                        properties={"locale": ref_locale},
                    )
                )

        yield ResearchMapping(
            contentUid=uid,
            mappingType="multilingual-reference",
            classification=classification,
            evidence=evidences,
            reviewRequired=True,
            metadata=metadata_dict,
        )
