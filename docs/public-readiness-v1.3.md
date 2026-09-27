# v1.3 Public Readiness Gate

State: **NOT READY** (newcomer audit and local candidate clean-room checks completed, 2026-09-28)

This report assesses the v1.3 development branch as a potential public repository. It does not change repository visibility or release the 1.2.0-versioned candidate artifacts.

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

## Candidate package and clean-room verification

The local source tree passed `python -m pytest -q`: **463 passed, 75 subtests passed, zero failures and warnings**. `python -m build` produced:

| Candidate | Purpose |
| --- | --- |
| `bg3loc-1.2.0-py3-none-any.whl` | Installable wheel |
| `bg3loc-1.2.0.tar.gz` | Source distribution with docs and demo |

These are local **candidate** artifacts, not a release. Final artifact sizes and SHA-256 hashes are recorded in the task handoff because embedding the sdist's own hash in a file inside that sdist would change the hash. The wheel contains installed code and runtime schemas; the sdist includes public docs, schemas, and the fictional demo. Neither archive includes a PAK, LOCA, SQLite DB, JSONL corpus, or workspace directory. Runtime dependencies are `jsonschema>=4.23,<5` and `openpyxl>=3.1,<4`; Python minimum is 3.11, with no local-path dependency.

A fresh private-branch GitHub clone was created in the requested clean-room directory. Two independent fresh virtual environments installed the candidate wheel and sdist. In each, `bg3loc --version`, command help, and the fictional demo passed from a separate work subdirectory in that clean room, not the original development repository; `bg3loc.__file__` resolved to that environment's `site-packages`. The remote clone was at the previous branch HEAD because publishing new commits to the private remote was rejected by automatic approval review. Candidate install tests used the locally built archives, not editable installs or copied generated data.

## Privacy and package audit

Current tracked files contain no PAK, LOCA, SQLite DB, JSONL corpus, or generated workspace. Public-facing entry documents contain no author-specific absolute path or credential. The historical `D:\SteamLibrary` examples in older technical acceptance documents are illustrative game paths, not a required personal path. `CassiaLin` appears as the repository/issue URL and schema namespace. LICENSE is MIT; README points to the issue tracker and asks reporters to redact game data and secrets.

**Public blocker: Git history.** An ancestor of this branch contains a 968,101-byte historical blob at `src/bg3loc/research/phase4ba_universe.py` (object `c601b4c58af2064012fdbd6f2b171f28d35fb10b`) with embedded compressed game-derived ContentUid/resource-reference data (`_DATA`). A later commit replaced it with live game extraction, so the current tree and candidate packages are clean, but a public clone would still obtain the historical object. Provenance/legal review and a deliberately coordinated history-clean publication path are required before making the repository public. This audit did not rewrite Git history.

**Remote candidate not yet present.** Automatic approval review rejected pushing the local public-readiness commits to the private remote because that external export was not explicitly authorized. The clean-room clone therefore validated the remote baseline plus locally built candidate archives, not a fresh clone of the updated branch. After the history issue is resolved and the owner authorizes the publication path, synchronize the intended branch and repeat a clean clone test at that exact commit.

## Gate decision

**v1.3 Public Readiness = NOT READY.** The two blockers above must be cleared and the exact published branch retested. No repository visibility change was made.

Non-blocking product limits: no provider fallback, no global multi-worker quota coordination, no provider invoice reconciliation, and no paid-provider live smoke in this gate. Research mapping and full-game installation require the user's own game and archive tool; the fictional demo cannot verify either.
