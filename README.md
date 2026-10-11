# BG3Loc

[繁體中文](README.zh-TW.md)

BG3Loc prepares text from your own *Baldur's Gate 3* installation, checks returned translations, and rebuilds localization files. Start with **Windows Basic**: a small UID scope, manual or external AI translation, XLSX/JSONL returns, Validate, Rebuild, and a read-only installation dry-run.

The Windows Basic release candidate is being prepared. **Stable release and real-game Apply/Rollback acceptance are still pending.** Technical validation does not judge translation quality or prove that an artifact loads correctly in the game.

## Start with Windows Basic

You need your own BG3 installation, Python 3.11+ (examples use 3.12), and a separately obtained [LSLib / Divine backend](docs/concepts/archive-backends.md). Game text, official translations, PAK/LOCA files, credentials, and LSLib are not distributed here.

From this checkout in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install .
bg3loc --version
$env:BG3LOC_DIVINE_EXE = 'C:\Tools\LSLib\Packed\Tools\Divine.exe'
Test-Path -LiteralPath $env:BG3LOC_DIVINE_EXE
```

Use the actual path to your downloaded `Divine.exe`; the path above is an example. Keep projects outside the game directory and this repository. The [getting started guide](docs/getting-started.md) explains how to inspect installed languages and select real UIDs before creating a small project.

After selecting two UIDs from your own source extract, run these commands from your project folder. Replace every placeholder; English/French are example installed languages:

```powershell
bg3loc project init --name 'Basic pilot' --game-dir '<BG3_INSTALL>' --source English --target French --evidence-profile basic --translation-strategy standard --format xlsx --content-uid '<UID_1>' --content-uid '<UID_2>'
bg3loc project check
bg3loc workflow prepare
# Edit workspace/e2e/returns/*.xlsx, or choose --format jsonl at project init.
bg3loc workflow validate
bg3loc workflow rebuild
bg3loc workflow install
bg3loc workflow status
```

`workflow prepare` scans and extracts the languages itself. Basic makes no automatic provider call. Translate outside BG3Loc, keep the generated identity/source fields intact, fill `ProposedTargetText` and set `TranslationStatus` to `translated`. Preserve runtime placeholders and markup. See the [return fields and command reference](docs/e2e/high-level-cli.md) and [synthetic examples](examples/windows-basic/README.md).

`--content-uid` limits translation rows; it still reads full language baselines and rebuilds a complete localization package. Omitting it selects all available rows. Rebuild prints the current artifact path: use that path or the workflow state, not a guessed old filename.

## Current results and recovery

Basic checks a prepare-time source/baseline receipt, current returned-file hashes, the exact accepted validation snapshot, rebuilt artifact hashes, and fresh destination preflight. Failed or changed validation revokes current install eligibility. Historical successes remain on disk; pending/failed output is isolated and cannot grant workflow install eligibility.

After editing returns, rerun Validate → Rebuild → Dry-run. After a game/source update, missing receipt, or changed Extract/baseline, keep the old project and edited returns, then prepare a **fresh workspace** and manually carry over reviewed translations by UID/source/version. Do not create receipts or repair hashes by hand. See [recovery](docs/getting-started.md#recovery).

## Dry-run and game writes

`bg3loc workflow install` without `--apply` is a dry-run. It checks current state and destination without creating a game backup or changing game files; it writes project evidence. Dry-run is not an in-game load test or authorization to install.

`workflow install --apply` and `install --rollback` write game files. They require a separate, explicit decision and acceptance plan; they are **not part of this guide's executable path**. Low-level `install` defaults to applying changes unless `--dry-run` is supplied. Do not use it to bypass a failed high-level workflow.

## Advanced capabilities and release limits

Production/automatic Provider workflows, Legacy Production Finalize, B1-02 Same-Entity Context, context/full profiles, and research review protocols are outside the first Windows Basic acceptance scope. B1-03 Dialogue Context is default OFF and its production transport remains blocked. Keeping these commands and research does not mean they are activated or accepted for this RC.

Use a single operator and retain original Extract/baseline paths. Detached portability, concurrent game updates, Linux/macOS native acceptance, whole-corpus translation, and general dialogue semantic safety are not promised. RC gates include fresh wheel/sdist privacy checks, all four hosted CI jobs, the real HTTP demo in a socket-capable environment, and separately authorized Windows game-load/Apply/Rollback evidence.

- [Windows Basic tutorial](docs/getting-started.md)
- [Basic high-level CLI reference](docs/e2e/high-level-cli.md)
- [Advanced production instructions](docs/production-getting-started.md) — retained, outside Basic RC acceptance
- [Troubleshooting](docs/troubleshooting.md), [engineering history](docs/lstp/), [research history](docs/research/)
- [M3 documentation and RC gate report](docs/research/bg3loc-mainline-m3-public-docs-rc-readiness.md)

Report bugs through [GitHub Issues](https://github.com/CassiaLin/bg3loc/issues) with commands, redacted errors, platform and version. Do not upload game text, packages, keys, generated receipts/returns, or private workspaces. Licensed under [MIT](LICENSE).
