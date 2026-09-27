# v1.3 Public Readiness Gate

State: **Actual Public GitHub Remote = VERIFIED** (public clone verified, 2026-09-28)

This report records the public-source boundary and newcomer gate for `CassiaLin/bg3loc`. Its pre-release public `main` HEAD was `8a465cd6a5a90694b57f92274d27ffdad5af397d`. The separate `CassiaLin/bg3loc-development` repository remains private; it is not the release source. Release status and downloadable artifact checksums belong in the GitHub Release, not inside the artifact that is being hashed.

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

The tracked tree was exported by `git archive`, without private `.git`, untracked files, workspace, build output, or caches, and initialized as a new root history. Public root commit: `f5ed51a98c82ef4b9ede4e383143930a7038b3a9`; public root tree: `a75d8342f7638cc851c3a16257f6730fff148133`. The public remote is `https://github.com/CassiaLin/bg3loc.git`; an unauthenticated HTTPS clone of pre-release `main` reproduced exactly two public commits and 320 reachable objects. Private ancestry, including private commits `5185acf` and `919b207`, is absent. The forbidden historical object `c601b4c58af2064012fdbd6f2b171f28d35fb10b` and the historical `phase4ba_universe.py` blob are not reachable; mentions here document the exclusion, not Git reachability.

The root has 316 reachable objects. Its largest blob is 105,244-byte `src/bg3loc/commands/research.py`, inspected as source code; it is the only blob over 100 KB. There are no blobs over 500 KB or 1 MB. No tracked PAK, LOCA, SQLite, real-corpus JSONL, research-preservation archive, canonical workspace, build directory, or virtual environment was found. The demo contains fabricated text and identifiers only. Secret keyword matches are code, environment-variable documentation, or intentionally fake test values; no credential was found. `CassiaLin` is the published author/repository identity, and `D:\SteamLibrary` in historical technical docs is an illustrative game path, not a required private path.

## Actual public remote verification

The public remote clone passed the focused relative-output demo regression (**1 passed**) and `python -m pytest -q`: **464 passed, 75 subtests passed, zero failures and warnings**. The `root.resolve()` demo fix is present in public `main`. The public clone built a wheel and sdist; archive contents contained no PAK, LOCA, SQLite database, real JSONL corpus, workspace, or private path. The remote-clone build's artifact checksums were recorded outside the source tree.

Earlier sanitized-candidate wheel and sdist clean rooms installed from built archives, ran the fictional demo from separate working directories, and loaded `bg3loc` from their own `site-packages`. The actual public clone also ran the demo end-to-end. Its loopback provider and fake archive adapter validate prepare → translation → QA → report → finalize, not a game-installable artifact. The release process repeats wheel/sdist clean-room checks against versioned artifacts built from the release commit.

## Privacy and package audit

Current tracked files contain no PAK, LOCA, SQLite DB, JSONL corpus, or generated workspace. Public-facing entry documents contain no author-specific absolute path or credential. The historical `D:\SteamLibrary` examples in older technical acceptance documents are illustrative game paths, not a required personal path. `CassiaLin` appears as the repository/issue URL and schema namespace. LICENSE is MIT; README points to the issue tracker and asks reporters to redact game data and secrets.

**Public blockers: none.** The private development repository retains its history and private visibility. The public remote was independently cloned and verified. No private branch or tag was pushed into the public repository.

## Gate decision

**Actual Public GitHub Remote = VERIFIED.** The release commit, versioned artifacts, and GitHub Release are handled in the separate release-only process.

Non-blocking product limits: no provider fallback, no global multi-worker quota coordination, no provider invoice reconciliation, and no paid-provider live smoke in this gate. Research mapping and full-game installation require the user's own game and archive tool; the fictional demo cannot verify either.
