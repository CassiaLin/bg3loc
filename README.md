# BG3Loc

[繁體中文](README.zh-TW.md)

BG3Loc helps a translation team extract text from its own *Baldur's Gate 3* installation, translate it, check it, rebuild language files, and install the result with a backup. Version 1.3.0 adds a production workflow with resumable provider runs, human review, and progress reports.

BG3Loc does not include game text, official translations, game packages, or the third-party LSLib archive tool. You need a lawful BG3 installation and must obtain LSLib separately. Windows is the primary tested platform; Linux/Proton and macOS have less real-game validation.

## Start here

Install Python 3.11 or newer and [LSLib / Divine](docs/concepts/archive-backends.md). In PowerShell, from this checkout:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install .
bg3loc --version
```

If `py -3.12` is unavailable, use a supported `python -m venv .venv`. Set `BG3LOC_DIVINE_EXE` to the `Divine.exe` you downloaded. Keep your translation project outside this source checkout. `<BG3_INSTALL>` below means your own game directory; a common Steam location is `C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3` (example only).

```text
my-bg3-localization/
  scan/
  extract/
  research/
  ruleset.json
  production/
  output/
```

The shortest production route is:

| Step | Command | Output |
| --- | --- | --- |
| Find game | `bg3loc scan --game-dir <BG3_INSTALL> --output scan` | `scan/scan-manifest.json` |
| Extract languages | `bg3loc extract --scan scan/scan-manifest.json --source English --target French --output extract` | `extract/extract-manifest.json`, `extract/normalized/English.jsonl` |
| Gather context | `bg3loc research scan --game-dir <BG3_INSTALL> --source English --target French --output research/scan.json` then `bg3loc research map --scan research/scan.json --output-dir research` | `research/research-mappings.jsonl` and optional context ledgers |
| Prepare | `bg3loc production prepare --extract extract/extract-manifest.json --source extract/normalized/English.jsonl --research-mappings research/research-mappings.jsonl --ruleset ruleset.json --output production` | `production/production-manifest.json` |
| Translate | `bg3loc production execute-openai-compatible --workspace production --base-url <ENDPOINT> --model <MODEL> --run-id run-001 --worker-id worker-01` | persisted attempts and translations |
| Check and review | `bg3loc production qa --workspace production` | QA routes; resolve REVIEW by a person |
| See progress | `bg3loc production report --workspace production` | progress, errors, provider-reported token usage |
| Finalize | `bg3loc production finalize --workspace production --output output` | validated language artifact and rebuild manifest |
| Install | `bg3loc install --rebuild output/rebuild/rebuild-manifest.json --scan scan/scan-manifest.json --dry-run` | install preflight; repeat without `--dry-run` only when ready |

Replace English and French with the source and target locales present in your installation. The target is not fixed to Traditional Chinese. Copy and adapt the [ruleset example](docs/lstp/ruleset-example.json) so its locale IDs match your extraction; see the [ruleset guide](docs/ruleset-guide.md). An OpenAI-compatible endpoint must implement `/v1/chat/completions`; a local endpoint may work, but compatibility varies. Supply a remote API key through the `BG3LOC_API_KEY` environment variable from your secret manager, never as a CLI argument. Pricing is optional.

The [getting started guide](docs/getting-started.md) gives executable PowerShell commands, explains which files are generated, and covers research input and human decisions. For a smaller, manual spreadsheet workflow, see [the basic workflow](docs/e2e/high-level-cli.md).

## Safety and recovery

`scan`, `extract`, research, translation, QA, report, and finalize write project outputs; only `install` writes to the game. Back up your game installation and project files before installing. `install --dry-run` checks the intended change. A real install creates backup and rollback metadata; use `bg3loc install --rollback <INSTALL_MANIFEST>` to restore it. Close the game before installing. If the game updates, rescan and regenerate dependent evidence.

`production report` answers “where am I?” at any point. Finalize succeeds only when every **classified production row** is `MERGE_READY`; `WAITING_TRANSLATION`, `WAITING_RETRY`, `WAITING_REVIEW`, and `BLOCKED` identify work to resolve. Unclassified rows are reported separately and require a conscious operator decision before claiming whole-corpus coverage.

## Explore and get help

- [Getting started and full workflow](docs/getting-started.md)
- [Ruleset guide](docs/ruleset-guide.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Large-scale operator guide](docs/lstp/large-scale-production-guide.md)
- [Command help](docs/cli/) and `bg3loc --help`
- [Architecture and schemas](docs/architecture.md), [engineering history](docs/lstp/)
- [Fictional local demo](examples/demo/run_demo.py) (no game files or provider account needed)

Report reproducible bugs through [GitHub Issues](https://github.com/CassiaLin/bg3loc/issues). Include the command, redacted error, platform, and BG3Loc version; do not attach proprietary game text, API keys, or a private workspace.

Licensed under [MIT](LICENSE).
