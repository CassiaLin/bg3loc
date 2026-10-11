# B1-03 Phase 6 Stage 4 — Integration / Portability / Regression

2026-10-09 · `feat/b1-03-dialogue-context` · HEAD
`896b4870b3a24d8506e6d751db3d4602925fb8fb`.
Stage 3 review ACCEPTED. Frozen contracts/registry/schema, Policy A, 2,000
codepoints, whole-set fallback and H0/HSE/HD identities are unchanged.

**B1-03 Phase 6 Stage 4 — READY FOR IMPLEMENTATION REVIEW**
**Production Activation = NOT APPROVED; Stage 5 = NOT STARTED.**

## Complete prepare / attestation (VERIFIED)

`ProductionPrepareRequest` appends optional `dialogue_evidence`, `source_scan`
and `research_summary`; `production prepare` exposes the corresponding explicit
opt-in flags. Default legacy prepare is unchanged. New
`production_dialogue_prepare.prepare_dialogue_workspace` stages the existing
classification/batching/B1-02 producer, validates the complete sealed public P1
evidence and English universe, appends immutable dialogue material and summary,
seeds a fresh 1.3 DB, snapshots D7 assets, validates all seals and atomically
renames a fresh directory. No context-only execution items are created. Existing
output is refused and failure does not publish an incomplete workspace.

Source normalized text/version/UIDs must equal source XML and LOCA semantics;
source LOCA must match the source package entry. Extract scan identity and complete
research build/version identity must match P1 corpus identity. Unknown/mismatched
attestation fails. All original input/package bytes are checked for mutation.
The frozen source/evidence binding fingerprint pins original extract/source and
all four evidence file SHAs. Prepared runtime inputs contain receipts, not original
executable paths; batch material paths are workspace-relative. These integrity
receipts do not claim cryptographic authentication of upstream extractor assertions.

Local real prepare:

- Corpus app **1086940**, build **25605617**, game **4.1.1.7631656**.
- Exact prepared inventory **218,272**; dialogue contexts **27,946**.
- Whole-set budget rejects **3**; bark stays baseline.
- Dialogue summary is **exactly identical** to accepted Stage 1 summary, including
  material fingerprint `850580acc8d822a91f38b37f3bc7e5f383d59583b55c6072ea0ddf8d12ebdc39`.
- B1-02 metadata/contexts coexist; mixed items retain their exact HSE identity.
- Source/extract/build checks and complete D7 checks passed before publication.

The older extract XML/LOCA paths were unavailable. A separate local input receipt
was rebuilt using read-only package extraction, then checked against retained
normalized snapshots. No existing extract or prior workspace was rewritten.
Full input receipts, recovered assets, complete prepare and relocation are all
under ignored `workspace/b1-03-phase6-stage4/`.

## D7 asset closure / portability (VERIFIED)

`portable_assets.create_finalize_assets` / `verify_finalize_assets` implement
the unchanged `production-finalize-assets/1` schema:

- Full sorted unique source/target UID version indexes, actual integer versions.
- Original target XML and LOCA, with text/version/UID semantic equality.
- Complete package entry inventory and every entry snapshot, size and SHA256.
- Content-addressed objects; identical bytes may share an object while logical
  entries stay distinct. Original package/baseline resources are never runtime
  fallback dependencies.
- Strict relative paths, containment, no absolute/drive/UNC/traversal/backslash/
  control/reserved/trailing-dot-space paths, no symlink/reparse/junction chain,
  casefold/NFC collisions rejected. Each declared file and semantic role checked;
  reads/copies are rechecked for mutation.
- 1.3 uses an injected or environment-probed public backend, not a saved executable
  path or executable inside the asset bundle. Legacy 1.0/1.1/1.2 behavior remains.

LSLib identifies format by filename extension, so content-addressed `.bin` LOCA
roles are copied to a verified temporary `.loca` before conversion. Raw object
bytes/hashes stay unchanged. No XML/LOCA/package payload is read by execution/
QA/resume; role readers are prepare and portable verify/finalize/rebuild only.

`verify_portable_workspace` is complete technical verification. It conveys no
provider activation permission; `verify_production_workspace` and production
transport still reject 1.3 until independent activation gates are approved.

## Finalize / rebuild / repack (VERIFIED)

`portable_finalize.finalize_portable_workspace` is the new 1.3 dispatch in
`production_finalize.finalize_production_workspace`; legacy code path is intact.
It requires all current content MERGE_READY and no live claims. It holds SQLite
`BEGIN IMMEDIATE` through generation, semantic/repack validation and atomic
publication. Completion and DB inventory/namespace validation receive the same
connection; execution/QA/issues/review/metadata are read from the writer-barrier
snapshot. Logical fingerprint includes current bindings and selected current
reviews, not raw source/translation or unrelated review histories. Input/asset
seals and the logical snapshot are rechecked before publish.

Existing `merge_records`, XML writer/parser and `validate_rebuilt_records` are
reused. Existing target versions win; source-only accepted UIDs use source index
versions and are appended in sorted UID order. Target-only, blank, untouched
text/version/order remain preserved. Only current accepted execution targets enter
merge; context-only records cannot be added. LOCA converts back to XML and full
semantic records are compared. Repack starts from complete sealed entries,
replaces the exact LOCA entry, then checks entry set, replacement LOCA SHA and
every non-LOCA SHA after extract. Binary package layout/compression need not match.
Outputs are staged outside the workspace/game install and atomically published
only after all checks; corruption/repack failure leaves no final output.

Synthetic end-to-end tests remove the original input/extract/evidence directory,
relocate the workspace, change cwd and finalize both LOCA-only and PAK modes.
They verify target-only/blank preservation, target-version precedence, source-only
records, non-LOCA bytes, writer blocking and failed-publication cleanup. One
actual symlink creation test is host-permission skipped; reparse-attribute
rejection is independently tested without requiring symlink privileges.

Real local assets: baseline LOCA semantic roundtrip passed; real **9-entry PAK**
repack/extraction passed with all non-LOCA hashes preserved. This is an unchanged
baseline asset validation, **not** a large real-text translation or real reviewed
production finalization. The real prepare remains pending translation/review.

## Stage 2–3 integration / privacy (VERIFIED)

`offline_integration.run_offline_integration` accepts static `OfflineOutcome`
mappings only. It uses the actual sealed resolver, single-render send preparation,
attempt provenance, failure/retry archive, QA routing and explicit human decision
fixtures. There is no HTTP/provider call in this harness. All production init/
start/claim/worker/provider stop guards remain. Human fixtures prove workflow,
not semantic correctness; they cannot stand in for case-006 evaluation.

Errors in this harness use a constant offline transport failure message rather
than echoing source/provider data. D7 errors expose stable error codes. Old H0/HSE
provider/error behavior is preserved. New package files are code/schema/fictional
tests/aggregate docs only; no proprietary corpus or translations in wheel/sdist.

H0/HSE input/effective/messages goldens and original HEAD byte parity tests remain
passing. HD add/change/remove/proof, namespace stripping/downgrade, retry/input
binding, semantic REVIEW and completion/finalize bypass regressions remain passing.
Synthetic batch splits produce identical dialogue summary/material/asset seals
and per-item H0/HSE/HD input hashes.

Wheel/sdist build passed. Fresh isolated venv install from the final wheel passed
from an external cwd, importing package code from that venv, with installed pinned
schemas and all Stage 4 modules. Runtime dependencies were copied from installed
local distributions for offline testing; no network dependency download. Failed
force-reinstall/temp cleanup was not counted as the clean install result; a new
fresh environment verified the final package.

## Case-006 semantic regression (UNKNOWN; Stage 5 blocker)

The real target is preserved with **947 codepoints**, **3 predecessor variants**
and **13 successor variants**. The exact `dialogue-prompt/1` grouped messages,
original blind translations and an unfilled human replay assessment are saved
local-only at `workspace/b1-03-phase6-stage4/case006-production-shaped-review.json`.

**NOT REPLAYED.** No human/external result for the new production-shaped renderer
was supplied or generated; no paid model/provider request or mass real-text
translation was made. The original observation of a worse Context translation
remains. Synthetic workflow PASS does not resolve semantic drift. Stage 5 must
remain blocked on an explicit production-shaped semantic replay and restriction
review; no quality improvement or general safety claim.

## Performance / storage (VERIFIED measurements)

| Measurement | Result |
| --- | ---: |
| Real full prepare | 495.63 s |
| D7 bundle bytes | 94,532,781 |
| Real workspace bytes | 535,177,859 |
| Complete real workspace verify | 47.77 s |
| D7 role verify / LOCA semantic check | 6.28 s |
| Relocated complete verify | 45.89 s |
| Resolver construction | 38.93 s |
| One resolver resolution | 40.07 s |
| Production worker stop guard | 0.00197 s |
| Real baseline LOCA roundtrip | 3.12 s |
| Real PAK repack/closure verification | 2.18 s |
| Synthetic 24-target prepare | 0.342 s |
| Synthetic offline end-to-end | 13.17 s |
| Synthetic finalize / writer barrier | 0.482 s / 0.306 s |

The real repeated full prepared-workspace validation cost is **not production
reasonable**. At ~40 s per resolution, 27,946 context targets alone imply about
13 days of verification overhead before provider time. No integrity check was
removed to hide this. PROPOSED follow-up: profile streaming/schema/hash/DB costs;
review an immutable per-run sealed-material snapshot design with explicit file/
identity change guards, so validation can be amortized without trusting stale
mutable caches. This needs integrity equivalence tests and review before rollout.
Performance remediation is an activation blocker, not an approval to weaken checks.
Real finalization lock duration with all real targets reviewed is unmeasured;
only the synthetic writer-barrier measurement is claimed.

## Tests / evidence / Git (VERIFIED)

- Stage 4: **21 passed, 1 skipped** (22 cases).
- Final targeted: **193 passed, 1 skipped, 4 subtests passed**.
- Full attempt: **1,153 passed, 1 skipped, 75 subtests passed**, plus existing
  fictional HTTP demo **environment-blocked** with WinError 10013; not PASS.
- Final full available suite excluding that diagnosed demo:
  **1,156 passed, 1 skipped, 75 subtests passed**.
- Privacy wheel/sdist and final isolated clean install: PASS.
- Real complete prepare/attestation, exact 27,946 material consistency,
  relocation, real LOCA and PAK asset verification: PASS.
- No production provider transport, no actual new game translation.

Local-only evidence under `workspace/b1-03-phase6-stage4/`:
`real-prepare-metrics.json`, `real-integration-metrics.json`,
`synthetic-performance.json`, `packaging-final-audit.json`,
`case006-production-shaped-review.json`, `pytest-targeted-final.txt`,
`pytest-full.txt`, `pytest-full-final.txt`, `starting-file-seals.json`.
The recovered inputs, real prepare, relocated prepare and rebuilt validation
assets stay ignored there. The original failed `.bin` conversion/reinstall
attempts are preserved as diagnostics, not reported as PASS.

Seven pre-existing sites changed only for necessary Stage 4 integration:
`commands/production.py`, `dialogue_execution_contract.py`, `dialogue_review.py`,
`production_completion.py`, `production_finalize.py`, `production_orchestration.py`,
`production_workspace.py`. Source dictionaries/DTO versions, prompt/hash/provider
guards, Stage 0 schemas/registry, prior tests/docs and all other starting file
bytes are preserved. New files are `portable_assets.py`, `portable_finalize.py`,
`production_dialogue_prepare.py`, `offline_integration.py`, fictional
`test_dialogue_stage4.py`, and this aggregate report. `git diff --check` passes;
all prior dirty work remains, nothing staged/committed/pushed/merged.

## Stage 5 recommendation

Technical implementation is **READY FOR REVIEW**, not activation. Remaining
mandatory blockers: case-006/new grouped-renderer semantic replay, review of
SAFE WITH RESTRICTIONS, measured resolver/preflight performance remediation,
real reviewed-workload concurrency/lock operations, and independent Stage 5
activation approval. Complete portable prepare and synthetic end-to-end evidence
are available to review; no transport guard was opened and Stage 5 was not started.
