# B1-03 Stage 5 S5-R1 — Decision Integrity Remediation

Date: 2026-10-10. Repository: CassiaLin/bg3loc.
Branch: `feat/b1-03-dialogue-context`.
HEAD: `896b4870b3a24d8506e6d751db3d4602925fb8fb` (unchanged).

## Scope and decision

**S5-R1 — READY FOR IMPLEMENTATION REVIEW**. This change addresses S5-B1 only. It does not approve
activation or implement S5-R2/R3/R4. The independent Stage 5 decision remains
**ACTIVATION DEFERRED — REMEDIATION REQUIRED** until subsequent review and
explicit authorization.

No frozen contract, policy, schema, prompt, translation identity, semantic
review rule, provider guard or historical report was changed. No migration,
real translation, provider request, commit, push or merge was performed.

## Implementation and transaction boundary

**VERIFIED:** the only existing source file changed by this task is
[production_review.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/src/bg3loc/production_review.py:76), `ProductionReviewStore.resolve`:

| Location | Change |
| --- | --- |
| Import from `bg3loc.qa` | Reuse the existing `qa_input_hash` canonicalization; no new identity algorithm |
| Lines 151–153 | For 1.3, SHA256 of the exact current `translated_text.encode("utf-8")` must equal the declared output hash; reject non-text candidate values |
| Lines 164–167 | Compare all four caller expectations against the writer-transaction state/QA rows again |
| Lines 168–171 | Pass the current writer connection into the existing full material/identity validator; preserve the preflight/full validation and material comparison |
| Lines 172–176 | Rebuild the existing `QaInput` from validated target source, actual base text, category and extracted protected tokens; compare its canonical hash with current QA evidence |

These checks run after `BEGIN IMMEDIATE`, before REVISE evaluation, output
updates, QA persistence or decision insertion. The same writer transaction
reads current status/input/output, current QA route/ruleset/hash/input binding,
validated material and the HD semantic gate. Existing expected-token,
input-binding, material and REVIEW checks remain mandatory.

The transaction's SQLite writer reservation prevents another connection from
changing candidate, QA or history between these reads and the decision commit.
DB-backed material/inventory validation now reads through that same connection.
This is a consistency change, not an R2 cache or performance optimization.
Full workspace validation remains in place.

**VERIFIED:** QA binding uses the existing QA 1.2 hash over ContentUID, source,
actual translation, category, protected tokens and ruleset version. It does
not regrade the base candidate or infer a human semantic verdict. REVISE still
evaluates technical QA, rejects FAIL/RETRY, and applies the frozen HD semantic
REVIEW policy before atomic QA/decision persistence.

## Six Stage 5 negative probes

Official regression:
[test_dialogue_stage5_r1.py](D:/workspace/codex/BG3/bg3loc-b1-02-real-corpus/tests/test_dialogue_stage5_r1.py:67),
`test_s5_b1_six_stale_base_byte_probes_reject_without_any_writes`.

Each probe creates a complete fictional 1.3 prepared workspace with all three
families, offline execution and correctly bound technical REVIEW evidence
(plus the HD semantic gate). It then changes only actual candidate text while
leaving declared output/QA/input hashes unchanged, and submits the original
expected snapshot. REVISE supplies a technically valid replacement; the
stale base must still be rejected.

| Family | ACCEPT before | REVISE before | ACCEPT after | REVISE after |
| --- | --- | --- | --- | --- |
| H0 in 1.3 | Incorrectly accepted | Incorrectly accepted | Correctly rejected | Correctly rejected |
| HSE in 1.3 | Incorrectly accepted | Incorrectly accepted | Correctly rejected | Correctly rejected |
| HD in 1.3 | Incorrectly accepted | Incorrectly accepted | Correctly rejected | Correctly rejected |

**VERIFIED:** the six official probes reproduced `DID NOT RAISE ValueError`
against the pre-fix implementation. Post-fix rejection is immediate with
`review base output bytes do not match declared output hash`. Every rejected
probe compares complete logical DB dumps before/after the API call: state,
QA, issues, review decisions, rejected candidates, attempts, other history
and sequences remain unchanged. The intentionally corrupted candidate is
preserved; the API does not silently repair it.

## Additional integrity and compatibility evidence

The new module contains 49 parametrized cases:

| Coverage | Cases | Expected behavior |
| --- | ---: | --- |
| Original stale-byte probes | 6 | Both decisions reject; all tables unchanged |
| Valid current decisions across H0/HSE/HD | 6 | ACCEPT/REVISE execute with correct base/resolved/input bindings |
| QA hash belongs to different actual bytes, including matching caller tokens | 6 | Reject; actual declared SHA alone is insufficient |
| Separate-thread committed byte mutation after QA preflight | 6 | Locked reread detects mutation; no API writes |
| Separate-thread input, declared output, QA hash/ruleset/route/binding mutation | 12 | Reject each changed current snapshot; no API writes |
| Writer attempts during the decision transaction, DELETE and WAL | 4 | Competing writer gets SQLite `locked`; legitimate decision commits |
| Late REVISE decision-insert failure after candidate/QA persistence | 3 | SQLite ABORT rolls back candidate, QA, issues, decisions and history |
| Legacy 1.0/1.1/1.2 decisions and historical NULL | 6 | Optional snapshot callers remain supported; historical NULL remains NULL |

**VERIFIED compatibility:** all new integrity checks are restricted to 1.3.
Normal H0/HSE REVISE may receive technical PASS; HD PASS is routed to semantic
REVIEW. No new mandatory review is imposed on H0/HSE. Legacy REVISE retains
its existing stale-QA behavior. No historical UNKNOWN binding is backfilled.

Existing Stage 3 tests cover REVISE technical failure rollback, missing HD
gate, stale acceptance/QA/context, retry archive atomicity, actual-send
provenance and completion/finalize bypass prevention. Stage 2 tests cover
frozen H0/HSE input/effective-prompt/actual-message fingerprints, HD
add/change/remove/proof identity, mutually exclusive families, version
guards and legacy workspaces.

These are isolated synthetic engineering tests, not human semantic reviews
of proprietary translations or real multi-worker throughput acceptance.
SQLite concurrency coverage uses independent connections/threads and real
DELETE/WAL writer contention; it does not replace future sustained operation
validation. Existing portable/snapshot tests remain part of full regression.

## Regression results and reproducibility

Final targeted regression: **163 passed** (Stage 2, Stage 3, production review
and the 43 initial R1 cases). The six subsequently added legacy cases passed
separately: **6 passed**. These cover all 49 new R1 cases. A separate concurrent
snapshot run also passed all **12** identity/QA mutation cases.

Final full available regression: **1251 passed, 1 skipped, 75 subtests passed**
in **358.17 seconds**, with no test failures. This includes **all 49 new R1
cases**. The single skip is `test_d7_corruption_rejected[link]`: the host does
not permit creating symlinks. It is a coverage limitation, not PASS. Other
portable/snapshot mutation tests, packaging/privacy, H0/HSE frozen byte
fingerprints, HD identity/provenance and semantic gates passed.

Test development evidence is retained: the pre-fix six probes failed as
expected. An initial post-fix test wrongly required H0/HSE REVISE to route to
REVIEW; two assertions failed because the unchanged technical QA returned
PASS. Only that test expectation was corrected. The targeted rerun passed,
and a fresh complete run uses the final expectations and all legacy cases.
No production behavior was altered to make those assertions pass.
The final targeted/legacy runs had a pytest cache warning (WinError 32 during
cache-directory publication); assertions and JUnit succeeded. The final full
run disabled pytest's cache provider and completed without that warning.

Local-only evidence directory: `workspace/b1-03-stage5-r1/`.
Logs and JUnit results contain fictional fixture data only and remain ignored.
Use `python -X utf8` and task-local tempfile/TEMP/TMP directories when running
on this host. Commands use an isolated pytest base directory and cache;
they do not clean the existing working tree.

Test selections (invoked through the task-local Python bootstrap):

```text
pytest -q tests/test_dialogue_stage5_r1.py tests/test_dialogue_stage3.py tests/test_dialogue_stage2.py tests/test_production_review.py
pytest -q tests/test_dialogue_stage5_r1.py -k legacy_decisions
pytest -q --ignore=tests/test_public_demo.py --basetemp=workspace/s5r1full2 -p no:cacheprovider --tb=short --junitxml=workspace/b1-03-stage5-r1/full-final-results.xml
pytest -q tests/test_public_demo.py
```

HTTP demo was separately rerun: **environment-blocked**, not PASS. All three
attempts recorded `PROVIDER_TRANSPORT_ERROR` caused by **WinError 10013**.
This local fictional socket demo did not reach formal 1.3 provider transport.

## Git and preservation audit

Starting status: 21 modified files and 34 untracked status entries.
Before edits, 376 existing tracked/non-ignored untracked files were SHA-sealed.
**VERIFIED:** 375 of 376 starting files are byte-identical; the sole changed
existing file is `production_review.py`. Only the regression module and this
report are newly non-ignored. Final status: **21 modified / 36 untracked status
entries**, including all prior dirty work. HEAD and branch remain unchanged.
`git diff --check` passed. Prior contracts, prompt/identity/provenance modules,
transport guards, reports and tests retain their starting SHA256.

Task delta is limited to:

- `src/bg3loc/production_review.py` — 1.3 decision checks and borrowed writer validation.
- `tests/test_dialogue_stage5_r1.py` — synthetic automated regression.
- This remediation report.

Proprietary corpora, responses, assignments, reviewed-workload copies and prior
sealed real workspaces are untouched. The earlier Stage 5 report's failing
probe observations are retained as historical evidence; this report records
their remediation separately.

## Remaining activation blockers

S5-B1's implementation is submitted for independent acceptance; this report
does not approve its review automatically. Remaining Stage 5 work is unchanged:

- **S5-B2 / R2:** review/export performance and capacity, including the earlier
  155.55-second Review ACCEPT observation and required integrity-equivalent
  remediation. No speedup is claimed here.
- **S5-B3 / R3:** normal guarded 1.3 execution integration, sustained
  multi-worker/QA/review contention and an accepted operational envelope.
- **R4:** release/recovery/rollback plan and rehearsals, with independent
  explicit activation approval.
- Native Linux/macOS acceptance remains unvalidated. Windows evidence does
  not establish cross-platform acceptance.
- SAFE WITH RESTRICTIONS and mandatory HD human REVIEW remain. Original
  pilot context-worse history remains; grouped case-006 replay supports only
  NO OBSERVABLE REGRESSION. General dialogue safety is NOT VALIDATED.

**S5-R1 — READY FOR IMPLEMENTATION REVIEW**.
Production Activation remains deferred; production transport stays blocked.
