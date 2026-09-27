# Troubleshooting

[Start here](getting-started.md). Run `bg3loc production report --workspace production` whenever you need current progress. Use `bg3loc --verbose ...` for diagnostic output; redact paths, game text, and credentials before sharing logs.

| Symptom | Meaning | Next step |
| --- | --- | --- |
| Game not found | Automatic Steam discovery did not find this installation. | Pass your actual BG3 folder with `scan --game-dir` and `research scan --game-dir`; check that it contains `Data`. |
| Archive backend unavailable | LSLib / Divine is missing or not configured. | Download it separately; set `BG3LOC_DIVINE_EXE` to the actual executable and verify the path. |
| Extract manifest or normalized source missing | A prerequisite command did not produce the file at that path. | Recheck the `extract --output` location and use its `extract-manifest.json` and source JSONL together. |
| Research mappings missing | `production prepare` needs local research evidence. | Run `research scan` then `research map` on your own game installation; pass the generated `research-mappings.jsonl`. |
| Ruleset locale mismatch | `sourceLocale` or `targetLocale` differs from extraction. | Edit your ruleset locale IDs to match the extract command and prepare a fresh workspace. |
| Workspace fingerprint mismatch | A bound input, batch, ruleset, or execution inventory changed. | Restore the original input or prepare a fresh workspace from consistent files; do not edit a prepared workspace's bound materials. |
| Run ID already exists | Each execution run has a unique identity. | Choose a new `--run-id` to resume; inspect `production report` for prior runs. |
| Provider HTTP 401/403 | Endpoint rejected credentials or access. | Check the endpoint, model access, and API key environment variable; do not paste a key into commands or issue reports. |
| Provider HTTP 429 | Provider asked you to slow down. | Let bounded backoff run, lower request pace if needed, then resume with a new run ID. |
| `WAITING_TRANSLATION` | Classified rows have not succeeded. | Run or resume provider execution. |
| `WAITING_RETRY` | A provider failure or QA RETRY is unresolved. | Inspect report errors; use `production retry` for QA RETRY rows, then run a new provider run. |
| `WAITING_REVIEW` | A human decision is required. | Export the review list, inspect it, then accept or revise each current candidate; rerun QA after revisions. |
| `BLOCKED` | A final failure, QA FAIL, stale evidence, or missing output prevents readiness. | Inspect report and relevant row/QA evidence, correct the cause, then rerun the appropriate earlier step. |
| Finalize not ready | At least one classified row is not `MERGE_READY`. | Read the disposition counts in the error/report; resolve each route before trying a fresh output directory. |
| Install preflight stops | The game or artifact no longer matches its scan/rebuild evidence. | Rescan and rebuild from the current game files; never bypass integrity checks. |

For a reproducible software bug, file a [GitHub issue](https://github.com/CassiaLin/bg3loc/issues) with the command, BG3Loc version, platform, and redacted error. Do not attach proprietary game data or secrets.
