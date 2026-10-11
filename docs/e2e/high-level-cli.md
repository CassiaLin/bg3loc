# Windows Basic | High-level CLI

[繁體中文（台灣）](high-level-cli.zh-TW.md) · [Tutorial](../getting-started.md)

Current M2-B1/B2 behavior is documented here. The tutorial stops at read-only Dry-run. Apply/Rollback and stable-release acceptance are still pending.

## Command reference

All project/workflow commands default to `bg3loc-project.json`. Use `--project <FILE>` when it has a different name/location; `project init` uses `--output`, not `--project`.

| Command | Actual options and behavior |
| --- | --- |
| `project init` | Required `--name --source --target`; optional `--game-dir`, repeated `--content-uid`/`--reference`, `--format xlsx|jsonl|csv`, `--workspace`, `--output`; default profile `basic`, strategy `standard`. Refuses existing config. |
| `project check` | `--project`; schema/path/role/scope checks. Does not prepare materials or prove current game hashes. |
| `workflow prepare` | `--project`; own scan/extract, source receipt, package and return copies. No `--scan`, `--source`, `--force` or `--format` option here. |
| `workflow validate` | `--project`, optional `--input <FILE_OR_DIRECTORY>`; current package/input receipt and technical QA. Explicit input is the validated location. No direct AI response importer. |
| `workflow rebuild` | `--project`; exact current accepted snapshot and unchanged input/artifacts required. Uses automatic container selection; there is no high-level `--container` or `--output`. Prints artifact path. |
| `workflow install` | `--project`; default read-only dry-run, fresh preflight each invocation. There is no high-level `--dry-run` option. `--apply` changes game files and needs separate acceptance/authorization. |
| `workflow status` | `--project`; reads state and prints progress/paths. Not a full live preflight. |

`workflow review prepare/integrate/resolve` and context/full profiles are advanced; Basic's default structural review set and language ruleSets are empty. Basic technical validation still checks required rows, immutable identity/source, placeholders and markup. It does not silently run Quest/UI/spelling/semantic review and does not create a Production execution database.

## Return fields

Edit generated `returns/*.xlsx` or `returns/*.jsonl`, not package `delivery/` baselines. Complete `ProposedTargetText` and `TranslationStatus=translated`; notes/name are optional. Keep `ContentUid`, locales, `SourceText`, `PresenceStatus`, `TranslationRequired`, protected tokens, evidence/context/comparison fields and any generated versions unchanged. Keep workbook headers; preserve JSONL types and one object per line. `intentionally-empty` is an explicit empty-target decision, not a way to bypass unfinished translation. See [synthetic examples](../../examples/windows-basic/README.md).

Repeated `--content-uid` at project creation selects source UIDs for a small pilot. All selected required rows must be returned. Full source/target baselines are still read, and a complete LOCA/PAK is rebuilt with other content preserved. This does not infer dialogue relationships or install only a single filesystem line. With no scope, all available rows are selected.

## Source receipt and current eligibility

Prepare automatically generates `package/internal/bindings/basic-source-baseline.json` under `workspace/e2e/`. This internal receipt binds source/target/reference PAK, Scan/Extract, full normalized/XML/LOCA and aligned inputs. It stays local and must not be edited, supplied to external AI, or fabricated for an old workspace. Later validation/rebuild/install require original paths and bytes plus source re-verification; Divine must remain available. Changed inputs require fresh preparation, not a new hash written into old evidence.

Current eligibility is separate from historical success. New validation starts/fails/interruption revoke downstream eligibility; edited returns need a new Validate. Unchanged eligible inputs may reuse validated/rebuilt snapshots, but Basic dry-run always performs current artifact/destination checks. A visible history path does not mean the workflow is eligible.

Runtime state is `workspace/e2e/workflow-state.json`; `e2e-workflow-state.schema.json` is its public definition, not the runtime file. Consult current stage status and CLI output. Artifacts/history aliases may retain the last successful result after current eligibility is revoked.

| Location under `workspace/e2e/` | Meaning |
| --- | --- |
| `validation/snapshots/<operation>/` | Distinct validation snapshots/diagnostics; failed validation does not overwrite prior successful accepted bytes |
| `rebuild/pending-<operation>/` | Candidate in progress; not current success |
| `rebuild/history/<operation>/` | Successful artifact snapshot; current eligibility still required |
| `rebuild/failed/<operation>/` | Isolated failed candidate; never treat partial LOCA/old manifest as this run's success |

Use `artifacts.rebuildManifest` and the printed artifact path instead of hardcoding `rebuild/rebuild-manifest.json`. Do not delete/edit state or manually promote failed output. Historical results are retained, so disk usage grows; automatic history cleanup is not implemented.

## Failure recovery and write boundary

Fix return errors and rerun Validate → Rebuild → Dry-run. For game/source updates, changed/missing baseline, old missing receipt, or edited returns belonging to an older package, preserve the old project and create a fresh workspace. Manually rebase only after checking current UID/source/version; no automatic migration or historical backfill. See [tutorial recovery](../getting-started.md#recovery).

Dry-run writes project evidence only: no game writes or game backup. It does not certify game loading, semantics, crash safety or a stable release. `workflow install --apply` and standalone `install --rollback <MANIFEST>` write game files; a separate explicit plan/acceptance is required. Low-level `install` defaults to apply without `--dry-run` and has no current workflow eligibility gate. A historical package may pass standalone preflight while the workflow is blocked; do not use low-level commands as fallback.

Production/Provider, B1-02, context/full research review and Legacy Production Finalize are outside the first Windows Basic RC acceptance. B1-03 stays OFF with production transport blocked. Single operator, stable original paths and Windows scope remain; detached portability, concurrent writers/updates, native Linux/macOS and general dialogue semantic safety are not certified.

## Historical E2E-01E record

The following original milestone record is retained. Its historical synthetic acceptance/count is not the current Basic RC release verdict; current evidence/gates are in the [M3 report](../research/bg3loc-mainline-m3-public-docs-rc-readiness.md).

```text
Milestone: End-to-End Translation Workflow 01E
State: ACCEPTED
Depends on: E2E-01A / 01B / 01C / 01D ACCEPTED
Core reopening: no
```

```text
Synthetic public CLI E2E acceptance: PASS
Local full test suite: 288 passed
E2E-01E | High-level CLI = ACCEPTED
```
