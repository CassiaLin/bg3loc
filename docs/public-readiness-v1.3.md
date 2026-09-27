# v1.3 Public Readiness Gate

State: **READY FOR PUBLIC REMOTE** (final sanitized local export verified, 2026-09-28)

This report assesses the new, local sanitized public candidate exported from canonical private source HEAD `5185acfe135d862d102dec13d4e055f5bfabb257`. The private canonical baseline was verified before export (464 passed, 75 subtests; one non-blocking Windows Pytest cache warning). This report does not change repository visibility or release the 1.2.0-versioned artifacts. The v1.3 version bump, tag, and release are intentionally deferred.

## Newcomer path

The [English README](../README.md) and [Traditional Chinese README](../README.zh-TW.md) now lead to [getting started](getting-started.md), [ruleset guidance](ruleset-guide.md), and [troubleshooting](troubleshooting.md). A new team can see prerequisites, local-game input, optional provider pricing, project layout, QA/review, finalize status, backup and rollback before reading engineering contracts. The earlier README had an `extract` example without required locale flags, stale test counts, and no complete route to research mappings. The production guide started after research inputs already existed. Those entry gaps are corrected.

The quick-start commands were checked against CLI parsers. The fictional demo exercised prepare → loopback OpenAI-compatible provider → QA → report → finalize. It uses fabricated text and a fake archive adapter; its output must never be installed into a game.

Common errors were triggered with fictional inputs: missing game reports the path, missing research mappings now names `research scan`/`research map`, locale mismatch shows extract and ruleset values, and duplicate run ID advises a new ID. Production preflight `RuntimeError` still prints a Python traceback; its final line contains the actionable guidance. This diagnostic presentation remains a non-blocking UX limitation; no blanket exception handler was introduced.

## Public workflow completeness

| Artifact or step | Status | Evidence and limit |
| --- | --- | --- |
| Game discovery | PUBLICLY REPRODUCIBLE | `scan --game-dir` uses the user's own installation. |
| Extract manifest | PUBLICLY REPRODUCIBLE | `extract --scan --source --target --output` creates it. |
| Normalized source | PUBLICLY REPRODUCIBLE | The same extract creates `normalized/<source>.jsonl`. |
| Research mappings | PUBLICLY REPRODUCIBLE | `research scan` then `research map` generate `research-mappings.jsonl` from local game packages with an archive backend. |
| Story ledger | PARTIAL | `research map` generates `story-occurrence-ledger.csv` when supported story evidence is available; optional for prepare. |
| UI/skill universe | PARTIAL | `research map` generates `ui-skill-universe.csv` when supported resource evidence is available; optional for prepare. |
| Functional classification | PARTIAL | `production prepare` runs classification; some rows may remain unclassified and need explicit human assignment, exclusion, or pending decision. |
| Category batches | PUBLICLY REPRODUCIBLE | `production prepare` batches classified rows, records unresolved separately, and seeds execution. |
| Translation | PARTIAL | CLI executes against a user-selected compatible endpoint; provider availability and output quality are external. |
| QA | PUBLICLY REPRODUCIBLE | `production qa` checks completed candidates and stores routes. |
| Human review | PUBLICLY REPRODUCIBLE | `review-export` and `review-resolve` support a human accept/revise decision; a person must supply the decision. |
| Report | PUBLICLY REPRODUCIBLE | `production report` reads current progress, attempts, usage, and optional user pricing. |
| Finalize/rebuild | PARTIAL | Works when every classified row is merge-ready and the user's archive backend/input files are available. |
| Install/rollback | PARTIAL | Requires the user's live game installation; dry run, backup, and rollback are implemented. |

The full research artifact generation commands exist; no deleted or private acceptance workspace is needed as input. Coverage and structural enrichment still depend on the user's installed game resources. The separate spreadsheet workflow remains available for smaller/manual projects and does not claim to be the production mode.

## Final sanitized history gate

The current tracked tree was exported by `git archive`, without private `.git`, untracked files, workspace, build output, or caches, and initialized as a new root history. Public root commit: `f5ed51a98c82ef4b9ede4e383143930a7038b3a9`; public root tree: `a75d8342f7638cc851c3a16257f6730fff148133`. The final public HEAD is the commit containing this report; retrieve its exact self-referential SHA with `git rev-parse HEAD` (also recorded in the task handoff). No remote is configured. Private ancestry, including private commits `5185acf` and `919b207`, is absent. The forbidden historical object `c601b4c58af2064012fdbd6f2b171f28d35fb10b` and the historical `phase4ba_universe.py` blob are not reachable; mentions here document the exclusion, not Git reachability.

The root has 316 reachable objects. Its largest blob is 105,244-byte `src/bg3loc/commands/research.py`, inspected as source code; it is the only blob over 100 KB. There are no blobs over 500 KB or 1 MB. No tracked PAK, LOCA, SQLite, real-corpus JSONL, research-preservation archive, canonical workspace, build directory, or virtual environment was found. The demo contains fabricated text and identifiers only. Secret keyword matches are code, environment-variable documentation, or intentionally fake test values; no credential was found. `CassiaLin` is the published author/repository identity, and `D:\SteamLibrary` in historical technical docs is an illustrative game path, not a required private path.

## Candidate package and clean-room verification

The final sanitized source passed the focused relative-output demo regression (**1 passed**) and `python -m pytest -q`: **464 passed, 75 subtests passed, zero failures and warnings**. This confirms the canonical `root.resolve()` demo fix is present. `python -m build` produced:

| Candidate | Purpose |
| --- | --- |
| `bg3loc-1.2.0-py3-none-any.whl` | Installable wheel |
| `bg3loc-1.2.0.tar.gz` | Source distribution with docs and demo |

These are local **candidate** artifacts, not a release. The root-stage wheel was 278,860 bytes (SHA-256 `3B7C5E96074D72FE31E7012A78E23EF5B10F316A7C91BAD14DCCBADD6ADF8F77`); the root-stage sdist was 487,162 bytes (SHA-256 `9E8B6AF8B4866E983A9F3D7C6CFA2CCC8F3D8AE4A15B9FD352D643F0935692FD`). These root-stage artifacts passed the clean-room checks below. The sdist is rebuilt after this report commit so it contains the final report; its new exact SHA-256 is recorded in the task handoff, since embedding that value here would change the sdist itself. The wheel contains installed code and runtime schemas; the sdist includes public docs, schemas, and the fictional demo. Neither archive includes a PAK, LOCA, SQLite DB, JSONL corpus, or workspace directory. Runtime dependencies are `jsonschema>=4.23,<5` and `openpyxl>=3.1,<4`; Python minimum is 3.11, with no local-path dependency.

Two independent fresh virtual environments installed only this export's candidate wheel and sdist. In each, `bg3loc --version`, command help, and the fictional demo passed from a separate working directory. The demo fixture was extracted from the sanitized sdist, not read from a source checkout at runtime; `bg3loc.__file__` resolved to each environment's `site-packages`. The loopback provider and fake archive adapter validate prepare → translation → QA → report → finalize, not a game-installable artifact. No private or public source checkout dependency was observed.

## Privacy and package audit

Current tracked files contain no PAK, LOCA, SQLite DB, JSONL corpus, or generated workspace. Public-facing entry documents contain no author-specific absolute path or credential. The historical `D:\SteamLibrary` examples in older technical acceptance documents are illustrative game paths, not a required personal path. `CassiaLin` appears as the repository/issue URL and schema namespace. LICENSE is MIT; README points to the issue tracker and asks reporters to redact game data and secrets.

**Public blockers: none in this local candidate.** The private repository retains its development history and has not been rewritten. A public remote, actual remote clone, v1.3 tag, and release have not been created; after an authorized push, repeat verification from the actual public remote.

## Gate decision

**Sanitized Final Public Candidate = READY FOR PUBLIC REMOTE.** No repository visibility change was made.

Non-blocking product limits: no provider fallback, no global multi-worker quota coordination, no provider invoice reconciliation, and no paid-provider live smoke in this gate. Research mapping and full-game installation require the user's own game and archive tool; the fictional demo cannot verify either.
