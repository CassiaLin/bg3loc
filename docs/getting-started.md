# Get started: Windows Basic

[繁體中文](getting-started.zh-TW.md) · [README](../README.md) · [CLI reference](e2e/high-level-cli.md)

This path stops at **Dry-run**. Apply, Rollback and game-load acceptance require a separate explicit decision. The Basic RC has not been declared a stable release. Use a single operator, retain original Extract/baseline paths, and keep game/project data local.

## 1. Install the tools

Use Windows, your own BG3 installation, and Python 3.11+; these commands use Python 3.12. In a checkout that includes the accepted M2-B1/B2 changes:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install .
bg3loc --version
bg3loc project init --help
```

If the Python launcher cannot find 3.12, use an installed supported Python with `python -m venv .venv`. If PowerShell blocks activation, run `.\.venv\Scripts\python.exe` and `.\.venv\Scripts\bg3loc.exe` directly instead of changing machine security settings. The current checkout reports 1.3.0; that version string alone does not certify that a downloaded release includes these changes. A future RC wheel must be identified by its release source and checksum.

Obtain LSLib from the [Norbyte project](https://github.com/Norbyte/lslib). Extract the whole tool distribution and keep its runtime files together. Locate **Divine.exe**, not the GUI converter, and set its actual path:

```powershell
$env:BG3LOC_DIVINE_EXE = 'C:\Tools\LSLib\Packed\Tools\Divine.exe'
Test-Path -LiteralPath $env:BG3LOC_DIVINE_EXE
```

Stop if this prints `False`. The path is illustrative, not a required folder layout. Existing native evidence used a directory labelled LSLib v1.20.4; other versions are not automatically certified. See [backend setup](concepts/archive-backends.md). Basic needs the backend during later source re-verification too. BG3Loc does not bundle LSLib, game packages or translations.

## 2. Inspect your languages and choose a small scope

Create a new project directory outside the game and repository. Replace the game path with your actual installation; English/French are examples, not mandatory languages:

```powershell
$project = 'C:\BG3Projects\basic-pilot'
$game = 'C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3'
New-Item -ItemType Directory -Path $project
Set-Location -LiteralPath $project
bg3loc scan --game-dir $game --output inspection-scan
$scan = Get-Content inspection-scan/scan-manifest.json -Raw | ConvertFrom-Json
$scan.locales | Select-Object localeId, status, packageFile
```

Choose distinct installed locales with `status=ready`. Ambiguous/unknown languages must be resolved, not guessed. A non-Steam installation or unknown build ID is allowed; package bytes still must match their scan. Do not modify source game packages for a test.

```powershell
$source = 'English'
$target = 'French'
bg3loc extract --scan inspection-scan/scan-manifest.json --source $source --target $target --output inspection-extract
$extract = Get-Content inspection-extract/extract-manifest.json -Raw | ConvertFrom-Json
$sourceInfo = $extract.locales | Where-Object { $_.localeId -eq $extract.sourceLocale }
Get-Content -LiteralPath $sourceInfo.normalized | ForEach-Object { $_ | ConvertFrom-Json } | Select-Object -First 10 contentUid, version, text
```

Pick one or two UIDs that actually occur in your source data, preferably easy lines you can review. This listing contains your private game text; do not post it in issues. Paste real IDs into `$uid1`/`$uid2` below. Placeholders and the repository's synthetic examples will not select real game rows.

## 3. Create and prepare the Basic project

```powershell
$uid1 = 'PASTE_REAL_SOURCE_UID_1'
$uid2 = 'PASTE_REAL_SOURCE_UID_2'
bg3loc project init --name 'Basic pilot' --game-dir $game --source $source --target $target --evidence-profile basic --translation-strategy standard --format xlsx --workspace workspace --content-uid $uid1 --content-uid $uid2
bg3loc project check
bg3loc workflow prepare
bg3loc workflow status
```

Stop on a nonzero exit or missing expected output; do not continue a failed command chain. `project init` refuses an existing project file. Use `--format jsonl` at creation for JSONL instead of XLSX; CSV is also implemented but is not this tutorial's example. Paths in the project config resolve relative to that config file.

`workflow prepare` does its own scan/extract under `workspace/e2e/`; it does not consume the inspection directory above. Basic creates no research context, automatic provider run or Production execution DB. A small UID scope limits delivery/required rows, **not** the full baseline read or complete PAK rebuild. Omitting `--content-uid` selects all rows.

Generated locations include:

```text
workspace/e2e/workflow-state.json
workspace/e2e/scan/scan-manifest.json
workspace/e2e/extract/extract-manifest.json
workspace/e2e/package/translation-package-manifest.json
workspace/e2e/package/internal/bindings/basic-source-baseline.json
workspace/e2e/returns/returns-manifest.json
workspace/e2e/returns/001.xlsx                # or 001.jsonl; may be several files
```

The internal receipt binds the original source/target PAK, Extract, normalized text, XML/LOCA and aligned material. It is automatically generated and checked, not an editable form. Keep the entire workspace and original referenced inputs. Do not send `internal/` or receipts to an AI translator.

## 4. Translate and return the files

Edit the generated copies in `workspace/e2e/returns`, not the package's prepared delivery baseline. Save and close the workbook before running CLI checks. Translate manually or use an external AI service of your choice; BG3Loc Basic does not send requests. Share only the selected text and necessary syntax you choose to disclose, never your whole workspace, credentials or game packages.

| Field | What to do |
| --- | --- |
| `ProposedTargetText` | Enter the translation of `SourceText`; preserve placeholders/markup |
| `TranslationStatus` | Set to `translated` for a completed nonempty translation |
| `TranslatorNotes`, `TranslatorName` | Optional notes/attribution |
| `ContentUid`, source/target locales, source text, presence, required flag, protected tokens, evidence/context/comparison fields | Keep exactly as generated; do not change IDs, source or versions |

For a genuinely required empty translation, `TranslationStatus=intentionally-empty` is an explicit decision; do not use it to silence missing work. An empty source is not a licence to invent text. Review meaning yourself: token/markup QA cannot assess all semantic errors.

XLSX: keep the column headers and row identities; edit target/status cells, not source cells. JSONL: keep one complete JSON object per line; retain booleans, arrays and UTF-8 data types. A model's plain prose, Markdown code fence, `{requestId, translationText}` or new column names are **not** a Basic return format. Map external responses back to their original UID rows, then review. [Fictional return examples](../examples/windows-basic/README.md) illustrate fields only; they are not importable into your game project.

## 5. Validate, rebuild, then dry-run

```powershell
bg3loc workflow validate
bg3loc workflow rebuild
bg3loc workflow install
bg3loc workflow status
```

Validate checks IDs/coverage, immutable fields, runtime syntax and the current source receipt. Rebuild requires that exact accepted snapshot and unchanged returns. If you edit returns afterward, run Validate again; an old successful artifact is not current approval. Rebuild preserves target-only/blank/untouched records and checks LOCA UID/version/text roundtrip and all non-replaced PAK entries.

Rebuild prints an artifact path under `workspace/e2e/rebuild/history/<operation>/`; the associated manifest path is in `workflow-state.json` under `artifacts.rebuildManifest`. Current status/eligibility matters too: an `artifacts` history reference alone does not authorize installation. Pending/failed directories are not current success. Do not guess the old fixed rebuild filename.

`workflow install` without `--apply` performs fresh destination/artifact/source/state preflight every time. It changes no game file and creates no game backup; project evidence is written. Dry-run does not prove that the game will load the package or that translations are correct.

## Recovery

| Situation | Recovery |
| --- | --- |
| Return edits or Validate FAIL | Correct only allowed fields, save/close, rerun Validate → Rebuild → Dry-run. A new/failed validation revokes downstream eligibility; old success files remain history. |
| Rebuild fails | Inspect the reported error; retain prior history and isolated failed output. Fix backend/disk problems, then rerun Rebuild if current validation/input still matches. Never copy a failed LOCA/PAK into the game. |
| PAK/game/source update, baseline/Extract mutation or missing original files | Keep the old project/returns. Stop using its stale receipt. Scan/Extract/Prepare/Validate in a new project/workspace for the current installation, then manually rebase suitable translations after UID/source/version comparison. |
| Old workspace has no Basic receipt | Start a fresh prepared workspace; do not hash current files and manufacture a receipt. No automatic historical backfill. |
| Prepare says edited returns belong to an older package | Preserve/archive those files; prefer a new project/workspace. Reprepare does not silently migrate your edits. Do not delete edits just to obtain PASS. |
| `project init` refuses overwrite | Use a new project directory/file. Do not assume `--force` exists. |
| Explicit `workflow validate --input <FILE_OR_DIRECTORY>` | That exact input location is bound to validation; later edits there invalidate current results. Default returns are not automatically substituted. |

To start a replacement project in a fresh folder, use the same verified current locale/UID selection and the `project init` command above. A relative `--workspace workspace` in a new project directory gives a separate workspace. Keep paths short and stable; the project is not a portable bundle independent of its original inputs. Do not rename/edit generated manifests or restore eligibility by hand.

## Where this guide stops

Apply (`workflow install --apply`) and Rollback (`install --rollback <INSTALL_MANIFEST>`) write to the game. They are not commands to run as part of this tutorial. Before either, a separately approved plan must identify destination, original/candidate hashes, scope, verified backup location and recovery steps; the game and all updaters must be stopped. Real-game load/Apply/Rollback acceptance is still pending.

Low-level `install` does not enforce the current high-level workflow state and defaults to applying without `--dry-run`. A historical artifact may pass its standalone checks while your workflow is blocked. Do not use it as an automatic fallback.

Production/Provider, B1-02, research context/full and review protocols remain advanced and outside Basic RC acceptance. B1-03 is default OFF, transport blocked. See the retained [production tutorial](production-getting-started.md) for historical instructions and the [M3 RC gate report](research/bg3loc-mainline-m3-public-docs-rc-readiness.md) for what remains before release.
