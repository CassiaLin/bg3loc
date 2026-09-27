# Get started with BG3Loc production

[README](../README.md) · [Ruleset](ruleset-guide.md) · [Troubleshooting](troubleshooting.md)

This guide starts with your own BG3 installation. It uses PowerShell and the v1.3 development branch. Windows is the primary tested platform. Linux and macOS use the same CLI flags but different game paths and archive backend setup.

## 1. Install and choose a project folder

Install Python 3.11+, download [LSLib / Divine](concepts/archive-backends.md), and install BG3Loc from the checked-out branch:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install .
bg3loc --version
```

Point `BG3LOC_DIVINE_EXE` at your own `Divine.exe`. Create a project folder outside the repository; the paths below are examples that you may change:

```powershell
$project = 'C:\my-bg3-localization'
$game = 'C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3'
New-Item -ItemType Directory -Force -Path $project, "$project\scan", "$project\research" | Out-Null
Copy-Item docs/lstp/ruleset-example.json "$project\ruleset.json"
Set-Location $project
```

Use a game path that exists on your computer. Do not copy game text, PAK, LOCA, credentials, or generated research files into the BG3Loc Git repository. The sample ruleset translates English to Traditional Chinese; edit both locale IDs, rules, and glossary for your own language pair before preparing a workspace.

## 2. Find and extract the game text

```powershell
bg3loc scan --game-dir $game --output scan
bg3loc extract --scan scan/scan-manifest.json --source English --target ChineseTraditional --output extract
```

The scan prints the installation and available locales; use those exact locale IDs. Extraction writes `extract/extract-manifest.json` and `extract/normalized/English.jsonl`. This data comes from your lawful local installation. BG3Loc does not distribute it. If your source or target differs, change the command and `ruleset.json` together.

## 3. Generate research inputs from that installation

```powershell
bg3loc research scan --game-dir $game --source English --target ChineseTraditional --output research/research-scan.json
bg3loc research map --scan research/research-scan.json --output-dir research
```

The first command inventories research resources. The second reads those resources and writes `research/research-mappings.jsonl`; it also generates `story-occurrence-ledger.csv` and `ui-skill-universe.csv` where evidence is available. This can take time on a full installation and needs the configured archive backend. The structural ledgers are optional for `production prepare`; mappings are required. `prepare` automatically finds sibling ledgers in the research folder. The project's historical acceptance data is not an input to this workflow.

Inspect `research/research-summary.json` and later `production/classification/functional-classification-summary.json`. Classification can leave `other / unclassified` rows; those are not silently translated or counted as ready. A team must decide whether to assign, exclude, or leave them pending. See [unclassified decisions](lstp/large-scale-production-guide.md) for the supported decision file and command.

## 4. Prepare a translation workspace

```powershell
bg3loc production prepare `
  --extract extract/extract-manifest.json `
  --source extract/normalized/English.jsonl `
  --research-mappings research/research-mappings.jsonl `
  --ruleset ruleset.json `
  --output production
```

Use a fresh `production` directory. The command creates classification, batches, an execution database, and `production/production-manifest.json`. It prints classified and unresolved counts. To use explicit structural files from a different directory, add `--story-ledger` or `--ui-skill-universe` with their paths. The full research path is reproducible from a local BG3 installation; enrichment depends on which resources that installation contains.

## 5. Translate and inspect progress

Choose an endpoint that implements OpenAI-compatible `/v1/chat/completions` and its model name. For a remote provider, place the key in the `BG3LOC_API_KEY` environment variable using your secret manager; do not put the key in a command or committed file. A local llama.cpp or vLLM endpoint may work if its chat response is compatible; verify it with a small bounded run first.

```powershell
bg3loc production execute-openai-compatible `
  --workspace production `
  --base-url 'http://127.0.0.1:8080' `
  --model 'your-model' `
  --run-id run-001 `
  --worker-id worker-01 `
  --max-items 10
bg3loc production report --workspace production
```

The execution command prints the run status and attempt counts; the report shows progress, errors, category status, and provider-reported usage. Use a **new** run ID when continuing later. Temporary provider failures such as HTTP 429 are retried with bounded backoff; see [advanced policy](lstp/large-scale-production-guide.md). Optional `--max-output-tokens`, `--temperature`, `--timeout-seconds`, `--api-key-env`, and pacing flags can be tuned after the small run. `--pricing` on the report is optional and must contain your own exact provider/model prices; it is an accounting estimate, not a provider invoice.

## 6. QA and human decisions

```powershell
bg3loc production qa --workspace production
bg3loc production report --workspace production
bg3loc production review-export --workspace production --output review.jsonl
```

QA reports PASS, RETRY, REVIEW, or FAIL. REVIEW means a person must judge the current candidate; it does not automatically mean the translation is wrong. Read `review.jsonl`, then resolve each current REVIEW item:

```powershell
bg3loc production review-resolve --workspace production --content-uid '<ContentUid>' --decision accept --reviewer 'Your name'
```

For revised text, use `--decision revise --text '<corrected translation>'` and run `production qa` again. For a QA RETRY row, run `production retry --workspace production --content-uid '<ContentUid>'`, then start another provider run with a new run ID. Human approval is never automatic.

## 7. Finalize and install

```powershell
bg3loc production report --workspace production
bg3loc production finalize --workspace production --output output
bg3loc install --rebuild output/rebuild/rebuild-manifest.json --scan scan/scan-manifest.json --dry-run
```

Finalize creates a validated LOCA or PAK and `output/production-final-manifest.json` only when every **classified production row** is `MERGE_READY`. A blocked finalize reports `WAITING_TRANSLATION` (run translation), `WAITING_RETRY` (retry/provider), `WAITING_REVIEW` (human review), and `BLOCKED` (inspect the failure or QA route). Resolve those and use a fresh output directory on the next attempt.

Before a real install, back up your game and project, close the game, review the dry run, then repeat the install command without `--dry-run`. The real install creates backup/rollback metadata and prints an install manifest path. To restore, run `bg3loc install --rollback <INSTALL_MANIFEST>`. If the game changed since the scan, regenerate scan/extract/rebuild evidence.

For a game-free check of the installed package, run the [fictional demo](../examples/demo/run_demo.py) with `python run_demo.py --output <fresh-directory>`. It uses a loopback mock provider and a fake archive adapter. Its output is never game-installable.
