# B1-03 Stage 4R — Final Engineering Acceptance

Date: 2026-10-10. **FINAL ENGINEERING ACCEPTANCE READY FOR REVIEW**.
Stage 5: **NOT STARTED**. Production Activation: **NOT APPROVED**.

## Conclusion and acceptance scope

**VERIFIED**: Windows snapshot integrity and full-scale synthetic reviewed-workload
finalize pass after the minimal corrections below. The remaining engineering
evidence gaps from Stage 4R have been measured at **218,272 targets**, rather
than inferred from the earlier small fixture or pending-only workspace.

**PROPOSED**: open an independent Stage 5 Activation Review to assess these
results and operational limits. This report does not approve transport or
declare business throughput/availability acceptable. The measured O(N) DB
reconciliation, long REVIEW API preflight, and multi-minute finalize writer
barrier require explicit operational acceptance or separately authorized
performance remediation. Native non-Windows acceptance remains unverified.

case-006 semantic regression is already ACCEPTED: scoped **NO OBSERVABLE
REGRESSION**, not GENERAL SAFETY VALIDATED. The original pilot's context-worse
case remains historical evidence; **SAFE WITH RESTRICTIONS** still applies.

## A. SealedRunSnapshot integrity

**VERIFIED**, on this Windows host/filesystem:

- Full startup schema/material/identity/inventory/metadata validation still runs.
  A strict captured manifest is compared with the validator's manifest image.
- Materials remain frozen typed DTOs/tuples in a per-instance read-only mapping;
  no shared mutable global cache. Current source/evidence, both-family rejection,
  budget/ordering/fingerprint validation are preserved.
- Runtime files and ancestor directories are held with deny-write/delete
  Windows handles; the mutable DB permits SQL writes but denies replacement.
  Opens use `FILE_FLAG_OPEN_REPARSE_POINT` and check reparse attributes after
  open, preventing a substituted link from being followed during capture.
- Every use checks process ownership, closed state, paths/reparse/file identity,
  bound metadata, current UID/batch/input and supplied claim/attempt/owner.
  Actual-send persistence still checks live lease and current attempt in its
  writer transaction; pending preview claims are offline-only.
- `data_version` is checked before/after the first SQLite snapshot read and
  after commit. Changed generations reconcile the **whole** input inventory,
  including other UIDs, missing/foreign rows and batch changes. Bounded races
  retry or fail closed; caller-owned transactions always reconcile inventory.
- Borrowed connections now require the same main database and an active
  transaction. A zero-row metadata UPDATE establishes/validates the writer
  barrier without changing values. A stale WAL reader cannot upgrade and is
  rejected; read-only/autocommit/other-DB connections are rejected.
- Close serializes with reads; resume/processes create fresh fully validated
  snapshots. Timeout/retry provenance remains attached to distinct attempts.
- A native Windows pre-existing writable-section bypass probe passes: mapped
  writers cannot silently bypass this snapshot protection on the tested host.

**VERIFIED algorithm tests / UNKNOWN native non-Windows platform acceptance**:
hosts without Windows share denial still rehash the entire runtime closure
before/after each use. Startup now captures material bytes and checks their
declared material fingerprint, then compares each decoded row's canonical hash
with that immutable capture. A transient read followed by restoration cannot
inject unsealed batching/prompt metadata into the DTO. Same-size/same-mtime
tampering is rejected. These paths were exercised on Windows with locking
disabled; native POSIX filesystems, process semantics and performance were not
measured. Do not present this as universal cross-platform activation approval.

D7 runtime validation still validates its descriptor only. Actual finalize
independently verifies all role payloads, sizes, SHA and semantics. No fingerprint
coverage or validation gate was removed to gain speed.

## Minimal fixes and before/after evidence

| File / function | Correction | Evidence |
| --- | --- | --- |
| `sealed_snapshot.py::_PinnedFiles.add` | Open named reparse objects and check after open | Windows flags/race tests, cross-process denial and writable-section probe |
| `SealedRunSnapshot.__init__` | Strict initial manifest and immutable nonlocking row capture | Transient material read reproduced then rejected |
| `SealedRunSnapshot.current_item` | Borrowed DB/transaction/writer-barrier binding | Other DB, autocommit and stale WAL snapshot reproduced then rejected |
| `dialogue_execution_contract.py::validate_stage2_workspace` | Private expected-manifest comparison | Existing strict validator still runs; schema/version unchanged |
| `production_completion.py::build_production_completion_view` | Verify actual output SHA for all families in 1.3 | H0/HSE text changed with unchanged declared hash now BLOCKED |
| `portable_finalize.py::finalize_portable_workspace` | Verify actual output bytes before merge and before publish | Observer/rebuild tampering rejected and rolled back |
| Same finalizer | Non-dot sibling staging prefix | Real LSLib empty-PAK reproduction and full corrected repack |

The logical snapshot canonicalization is unchanged: actual-byte checks are
additional validation, not a new fingerprint field/version. H0/HSE prompt,
input identity and legacy 1.0/1.1/1.2 behavior remain unchanged. The output-byte
completion check applies to the complete 1.3 workspace only.

LSLib 1.20.4 produced a **48-byte empty PAK** beneath `.portable-finalize-*`
ancestors, exited zero, and failed archive listing. Identical bytes under a
non-dot temporary ancestor, with the same temporary-directory ACL policy,
produced a readable 14,318,233-byte / 9-entry package. Both short and original
output basenames were tested. This was a real backend/staging compatibility
defect, not a large-data correctness failure. Only the internal prefix changed;
entry-set, payload SHA, D7, roundtrip and atomic-publication checks remain.
The failed run rejected publication and its diagnostics remain local.

## B. Snapshot / actual worker lifecycle performance

**VERIFIED**: isolated copies of the sealed real workspace; no provider calls.
Final snapshot-code sample: 29 steady HD resolutions, 10 legal-commit
reconciliations, and 12 actual worker-function lifecycle samples (4 each H0,
HSE, HD). One HD sample includes a synthetic timeout and a new retry attempt.

| Measurement | Seconds |
| --- | ---: |
| Full startup | 60.997 |
| First resolution / inventory reconciliation | 0.638 |
| Steady resolution mean / max | 0.0570 / 0.0613 |
| Resolution after each DB commit, mean / max | 0.6114 / 0.6234 |
| H0 lifecycle mean | 1.855 |
| HSE lifecycle mean | 1.851 |
| HD lifecycle mean, including one timeout/retry | 2.165 |
| All 12 lifecycle mean | 1.957 |
| Startup amortization at 218,272 items | 0.000279 per item |

Lifecycle includes actual claim transaction, resolver, single renderer,
actual-send provenance transaction and success transaction. Static source-copy
outputs replace transport; **provider latency is excluded**. It is not a full
218,272-item worker run or measured multi-worker throughput. Startup plus these
samples implies ~7.04 s/item at 12 items, ~2.02 at 1,000, and ~1.957 at 218,272;
these are arithmetic amortizations, not additional measured executions.

Before Stage 4R, resolution alone was 40.07 s and construction 38.93 s.
An earlier engineering run measured startup 44.765 s, steady 0.0384 s and
post-commit 0.4497 s. Final measurements ran alongside engineering regression/
finalize work. Resource contention and sample size prevent claiming an isolated
latency SLO or extrapolating steady 0.057 s to worker throughput.

**VERIFIED separate API costs**: technical QA batch (12 outputs) **62.167 s**;
one synthetic ACCEPT through `ProductionReviewStore.resolve` **155.550 s**.
That API performs repeated full material validation. This report does not
hide it in the 1.957 s worker figure or claim it was optimized. QA evaluated
all 218,272 generated candidates in 6.741 s in the fixture generator, but that
number excludes command preflight, persistence and real review interaction.

**PROPOSED operational decision**: evaluate whether O(N) reconciliation on
every claim/provenance/success and long per-review validation are acceptable.
Heavy legal commit churn may exhaust bounded snapshot retries and fail closed;
sustained multi-process worker throughput/backoff has not been measured.
Do not remove reconciliation or trust mtime/global caches to avoid this cost.

## C. Reviewed-workload composition and limits

**VERIFIED full scale**, not a small stand-in:

- 218,272 original targets: H0 172,255; HSE 18,071; HD 27,946.
- Complete original material/evidence bindings and portable 9-entry D7 bundle.
- Generated output is an explicitly synthetic **exact source copy**, with an
  explicit synthetic string for empty source if needed. No translation/model
  work occurred. Original real prepared workspace remains byte unchanged.
- Actual technical QA: PASS 2,823 / REVIEW 215,449; frozen HD routing yields
  PASS **2,518** / REVIEW **215,754**; **zero RETRY/FAIL**. No rejected route was
  relabeled. Synthetic ACCEPT rows bind current input/output/ruleset/QA hashes.
- Every generated reviewer/note is labeled SYNTHETIC and is **not human semantic
  review**. Full population uses direct bulk fixture loading; only sampled
  worker calls and one review API call exercised real lifecycle functions.
- Output directories and companion README are marked synthetic and must not
  be treated as translated game data or installed into the game.

| Accepted synthetic REVIEW rows | % all targets | Accepted HD / missing HD | MERGE_READY / WAITING_REVIEW |
| ---: | ---: | ---: | ---: |
| 0 | 0% | 0 / 27,946 | 2,518 / 215,754 |
| 107,877 | 49.423% | 13,952 / 13,994 | 110,395 / 107,877 |
| 215,754 | 98.846% | 27,946 / 0 | 218,272 / 0 |

The final layer accepts 100% of required REVIEW rows; the remaining 2,518
already have technical PASS. These highly review-dense source-copy fixtures
stress review-table cardinality, not the distribution or linguistic validity
of real translated content. The previous real pending-only 57.518 s measurement
is retained as a different workload, not reused as completed-workload timing.

## D. Finalize / locks / native package measurements

**VERIFIED**, same full target inventory at all layers:

| Layer | Completion | Writer barrier | Result |
| --- | ---: | ---: | --- |
| Zero reviewed | 75.370 s | 75.469 s | Formal finalize BLOCKED; no output |
| Half reviewed | 62.996 s | 63.503 s | Completion gate BLOCKED; no rebuild/repack |
| Fully reviewed, injected observer failure | 64.108 s | 71.196 s | SQL rollback verified; no output |
| Fully reviewed, final code native finalize | 88.073 s | **184.996 s** | Full merge/rebuild/repack and atomic publication PASS |

Final full finalize total: **248.399 s**. Native LOCA conversion: **0.828 s**;
LOCA back-conversion: **0.806 s**; native PAK creation: **1.797 s**. These backend
phase times exclude XML assembly, validation, directory copies and snapshot
work. The earlier corrected native run was 201.082 s total / 147.539 s barrier;
final-code measurements include output-byte validation and concurrent regression
load. A small-fixture subsecond barrier was never used to infer these timings.

Native results: 218,272 merge-ready targets; 232,774 merged records;
14,089 source-only additions. Untouched/target-only/blank records and versions
pass semantic validation and real LOCA roundtrip. All **8 non-LOCA entry SHA**
values match their original sealed snapshots; the complete 9-entry set is
verified. Output tree is 175,172,723 bytes including validation intermediates;
LOCA is 30,784,580 bytes and PAK 14,318,233 bytes.

**VERIFIED concurrency / rollback / publication**:

- Independent QA and review **processes** cannot write during the barrier;
  their timeout probes are expected BLOCKED outcomes, not successful updates.
- WAL readers remain available (count query ~0.0156 s). A held reader retains
  its prior snapshot across a later committed QA update, then sees it after
  ending its transaction. The probe update is restored.
- The full-size controlled failure after completion rolls back a probe write
  and publishes nothing. Smaller regression tests cover late rebuild/repack
  failure, same-transaction tampering and post-rename commit failure rollback.
- Five native pre-publication checks see no output directory; artifacts are
  published only after all validation. Full zero-review HD cannot finalize.

**PROPOSED operations**: schedule finalize as an exclusive writer maintenance
window, stop/drain claims, allow WAL reads, and handle QA/review lock timeouts.
Expect minutes of writer exclusion on this measured workload; translating
reviews into actual user data, slower disks, concurrent workers and longer
target texts may change costs. They are not measured production guarantees.

## E. Regression, packaging and preservation

Final targeted: **266 passed, 1 skipped**. Full available: **1,202 passed,
1 skipped, 75 subtests passed**. Includes H0/HSE byte parity, HD input/provenance,
retry/review/completion, semantic REVIEW, relocation, D7 and whole-set fallback.
The skip is host denial of creating a symlink; reparse-attribute and native
Windows handle/mapping probes pass. Existing fictional HTTP demo was retried:
**WinError 10013 / environment-blocked**, not PASS, excluded from available count.

Wheel/sdist privacy scan and fresh isolated clean install pass, using local
dependency copies without network installation. Frozen schema data and the
corrected modules import from an empty working directory. Initial native/build
temp-folder ACL failures were preserved and resolved by task-local temp paths;
a missing `typing_extensions` in the manual offline dependency copy was also
resolved. None is counted as an initial PASS or hidden as a product success.

Starting HEAD/branch remain `896b4870b3a24d8506e6d751db3d4602925fb8fb` /
`feat/b1-03-dialogue-context`. Only four prior source files changed:
`sealed_snapshot.py`, `dialogue_execution_contract.py`, `portable_finalize.py`,
`production_completion.py`. New files are the synthetic engineering regression
tests and this report. Stage 0 schemas/registry, Policy A, prompt/DTO/identity,
provider guards, prior reports and all other dirty work remain preserved.
Final Git/byte/privacy audit is saved locally; no commit, push or merge.
It confirms **373 starting repository seals**, exactly the four expected
source changes and two new files, and **313 original sealed-workspace files
byte unchanged**. Git status: **21 modified, 33 untracked**, including preserved
prior-stage work. `git diff --check` passes. All synthetic DBs/packages are
Git-ignored; changed/new source and this report contain no real ContentUID
literals. Earlier reports and the accepted case-006 evidence remain untouched.

## Remaining Stage 5 decisions

**PROPOSED: open independent Activation Review; do not activate now.**

1. Independent human engineering/activation approval of these corrections and
   the Windows scope; no production transport stop guard has been removed.
2. Operational acceptance or separately authorized remediation of ~1.96 s
   sampled worker overhead, ~156 s review API calls and ~185 s finalize writer
   barrier. Native POSIX and sustained multi-worker throughput remain UNKNOWN.
3. Retain SAFE WITH RESTRICTIONS and frozen prepare/build/D7/semantic REVIEW
   gates. Synthetic ACCEPT fixtures cannot substitute for actual semantic
   approval of future production translations.

The original case-006 replay blocker stays resolved for that case only. Full
reviewed-workload **engineering measurement** is now available; it does not
claim a corpus of real human-reviewed translations or broader safety validation.

## Reproduction / local evidence

All corpus, synthetic outputs, DBs and detailed metrics stay ignored under
`workspace/b1-03-stage4r-final-engineering/`. Scripts:
`benchmark-and-load-fixture.py`, `benchmark-final-worker.py`,
`reviewed-workload-harness.py`, `full-finalize-final-build.py`.
These operate on isolated copies with explicit offline/static fixtures.

Key evidence: `final-worker-benchmarks/*.json`, `qa-review-api-benchmark.json`,
`full-technical-qa-composition.json`, `full-fixture-load.json`,
`reviewed-zero.json`, `reviewed-half.json`, `reviewed-full-rollback.json`,
`reviewed-full-finalize-final-build.json`, `native-pak-path-diagnostics.json`,
`native-nondot-staging-diagnostic.json`, `packaging-privacy-clean-install.json`,
`pytest-targeted-final-build.txt`, `pytest-full-final-build.txt`,
`http-demo-environment-blocked.json` and `final-preservation-audit.json`.
Failed reproductions remain beside the successful results.

**B1-03 Stage 4R — FINAL ENGINEERING ACCEPTANCE READY FOR REVIEW**.
