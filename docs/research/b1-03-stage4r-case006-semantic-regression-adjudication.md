# B1-03 Stage 4R — case-006 Semantic Regression Adjudication

Date: 2026-10-10. Status: **SEMANTIC REGRESSION ADJUDICATED**.
Formal verdict: **NO OBSERVABLE REGRESSION**.
Scope: one known-risk case with the production `dialogue-prompt/1` renderer.
Stage 5: **NOT STARTED**. Production Activation: **NOT APPROVED**.

## Validation and evidence

**VERIFIED**: branch `feat/b1-03-dialogue-context`, HEAD
`896b4870b3a24d8506e6d751db3d4602925fb8fb` unchanged.
The user-provided `case006-blind-review-schema-fixed.jsonl` was copied byte for
byte to `blind-review-completed.jsonl`. The replaced file was backed up locally.
Earlier failed validation records and their schema errors remain available;
the assessment was not repaired or inferred by Codex.

`dialogue_semantic_replay.py::validate_semantic_replay_review` returned PASS
before assignments were decoded. Additional read-only checks confirmed:

- Exactly one unique case, two requests, two responses and two neutral variants.
- Closed assessment schema, complete per-variant boolean values and an explicit
  `semanticDriftVariant` of `neither`.
- Original target source, grouped context and translations unchanged.
- Request/template fingerprints and original blind-input import seal match.
- Protected runtime syntax and markup remain intact.
- The blind review contains no request IDs, hidden assignment fields or
  condition metadata. This is an artifact check, not an audit of external
  reviewer access beyond the documented blind handoff.

**VERIFIED local unblind**: only after PASS, the local assignment fingerprint
was checked against the original manifest. Each condition maps uniquely to
one request/neutral variant, and each response exactly matches its assigned
blind translation. Both request targets have the same UID/source; the UID,
condition-to-variant mapping and proprietary texts are omitted from this report.

The sealed requests bind `dialogue-prompt/1` and its unchanged seven safety
instructions. The grouped source projection matches the blind context exactly:
947 codepoints, 3 predecessor variants and 13 successor variants. No IDs,
assignments, translation requests or translations were regenerated.

## Decision

| Observation | Result | Evidence type |
| --- | --- | --- |
| Baseline / grouped translations identical | Yes, UTF-8 byte-identical | Automated exact comparison after unblind |
| Context worse | 0 / 1 pair | Identical outputs plus bound blind assessment |
| Context better | 0 / 1 pair | No observable superiority |
| No observable difference | 1 / 1 pair | Automated exact comparison |
| Meaning preserved | Both candidates: true | External blind assessment; not an automated semantic proof |
| Unsupported additions | Neither observed | External per-variant assessment |
| Alternatives-as-sequence errors | Neither observed | External per-variant assessment |
| Semantic drift | `neither` | External blind assessment |
| Context-specific degradation | Not observed | Identical outputs and bound assessment |
| Context contamination | Not observed | Derived from meaning/addition/sequence/drift assessments and notes; no dedicated contamination score or causality proof |

The formal case-specific conclusion is **NO OBSERVABLE REGRESSION**.
It is **not GENERAL SAFETY VALIDATED**, does not prove translation quality
improvement and does not establish safety for untested dialogue branches.
Codex verified data identity and review binding; the semantic observations
remain the external blind reviewer's judgments rather than technical QA claims.

## Original pilot remains authoritative historical evidence

The original 25-pair pilot observed one context-worse result at case-006 and
supported **SAFE WITH RESTRICTIONS**. That outcome is retained, not overwritten
or retrospectively relabeled.

This new replay uses the production grouped renderer and new independent
translations. It records no observable regression in this run. The different
prompt/run and incompletely specified model conditions do not permit attributing
the difference to the renderer or claiming that the historical risk is fixed
for all future runs. case-006 remains a known-risk regression case.

## Blocker disposition

**VERIFIED**: the pending production-shaped case-006 translation / blind review /
local adjudication requirement is now complete for this case. That specific
Stage 5 evidence blocker is resolved. Stage 4R remains **CONDITIONALLY ACCEPTED**;
this decision does not approve Stage 5 or Production Activation.

Remaining requirements:

1. Real reviewed-workload finalize/concurrency/lock measurement. The previous
   57.518 s measurement was a pending 218,272-target workspace with zero reviewed
   translations; it cannot substitute for a completed-workload finalize test.
2. Sealed snapshot integrity/performance acceptance. Startup and post-commit
   inventory costs remain material; steady resolution latency is not total
   worker throughput. Actual non-Windows behavior/performance is unmeasured.
3. Retain **SAFE WITH RESTRICTIONS**, Policy A, whole-set fallback, 2,000
   codepoints, semantic REVIEW and all existing prepare/build/D7 requirements.
4. Independent Stage 5 Activation Review and explicit authorization. Provider
   transport stop guards remain unchanged.

## Local evidence and preservation

All detailed artifacts are Git-ignored under
`workspace/b1-03-phase6-stage4r/case006-replay/`:

- `schema-fixed-blind-review-validation-local.json`: validation and seals.
- `case006-unblind-results-local.json`: full local mapping, bound original
  assessment, baseline/grouped translations and proprietary source/context.
- `case006-adjudication-summary-local.json`: scoped verdict and blockers.
- `schema-fixed-adjudication-starting-seals-local.json`: preservation baseline.

The Stage 4R aggregate report receives an appended status update; its previous
pending status, test evidence and limitations remain as historical records.
Only reports and ignored local artifacts change. No production code, frozen
contracts, original responses/assessments, IDs or provider guards are changed.
No provider calls, retranslation, resampling, commit, push or merge occurred.

Final audit and targeted validation evidence are recorded in the local
`case006-adjudication-final-audit-local.json`.

Targeted existing replay/strict-review regression tests: **9 passed, 24
deselected**. No production code changed, so the full suite was not rerun;
earlier Stage 4R full-regression evidence remains historical evidence.
Final Git status: **21 modified, 31 untracked**, retaining prior work and adding
this report. `git diff --check` passes. Audit confirms the original aggregate
report remains a byte-preserved prefix and only its appended update changes.

**B1-03 Stage 4R｜case-006 SEMANTIC REGRESSION ADJUDICATED**.
