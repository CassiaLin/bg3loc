# BG3Loc

[English](README.md)

BG3Loc 協助翻譯團隊從**自己合法安裝的《柏德之門 3》**提取文字、翻譯、檢查、重建語言檔，並在備份後安裝。v1.3 production 流程支援續跑 provider、人工審核與進度報表。此分支仍在開發；已發布的套件版本仍是 1.2.0。

Repository 不包含遊戲文本、官方翻譯、遊戲封裝檔或第三方 LSLib 解壓工具；請自行取得遊戲與 LSLib。Windows 是主要驗證平台；Linux/Proton 與 macOS 的真實遊戲驗證較少。

## 從這裡開始

安裝 Python 3.11 以上及 [LSLib / Divine](docs/concepts/archive-backends.zh-TW.md)。在此 checkout 開啟 PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install .
bg3loc --version
```

沒有 `py -3.12` 時，可用支援版本的 `python -m venv .venv`。把 `BG3LOC_DIVINE_EXE` 設為自行下載的 `Divine.exe` 路徑。翻譯專案請放在 source checkout 外。下方 `<BG3_INSTALL>` 代表自己的遊戲目錄；Steam 常見的 `C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3` **只是例子**。

```text
my-bg3-localization/
  scan/
  extract/
  research/
  ruleset.json
  production/
  output/
```

最短 production 路徑：

| 步驟 | 指令 | 產物 |
| --- | --- | --- |
| 找遊戲 | `bg3loc scan --game-dir <BG3_INSTALL> --output scan` | `scan/scan-manifest.json` |
| 提取語言 | `bg3loc extract --scan scan/scan-manifest.json --source English --target French --output extract` | `extract/extract-manifest.json`、`extract/normalized/English.jsonl` |
| 產生脈絡 | `bg3loc research scan --game-dir <BG3_INSTALL> --source English --target French --output research/scan.json`，再執行 `bg3loc research map --scan research/scan.json --output-dir research` | `research/research-mappings.jsonl` 與可選脈絡 ledger |
| 準備 | `bg3loc production prepare --extract extract/extract-manifest.json --source extract/normalized/English.jsonl --research-mappings research/research-mappings.jsonl --ruleset ruleset.json --output production` | `production/production-manifest.json` |
| 翻譯 | `bg3loc production execute-openai-compatible --workspace production --base-url <ENDPOINT> --model <MODEL> --run-id run-001 --worker-id worker-01` | 保存的 attempts 與譯文 |
| 檢查與審核 | `bg3loc production qa --workspace production` | QA routes；REVIEW 由人決定 |
| 查進度 | `bg3loc production report --workspace production` | 進度、錯誤、provider 回報的 token usage |
| Finalize | `bg3loc production finalize --workspace production --output output` | 驗證過的語言檔與 rebuild manifest |
| 安裝 | `bg3loc install --rebuild output/rebuild/rebuild-manifest.json --scan scan/scan-manifest.json --dry-run` | 安裝前檢查；確認後才去掉 `--dry-run` |

請用自己遊戲安裝中的 source/target locale 取代 English/French；目標語言不限繁中。複製並調整 [ruleset 範例](docs/lstp/ruleset-example.json)，讓 locale IDs 與 extract 一致；詳見 [ruleset 指南](docs/ruleset-guide.md)。OpenAI-compatible endpoint 必須支援 `/v1/chat/completions`；本機 endpoint 也可能適用，但各實作相容性不同。遠端 API key 請由 secret manager 設定到 `BG3LOC_API_KEY` 環境變數，不要放入命令參數。Pricing 為可選。

[新手指南](docs/getting-started.md)提供可執行的 PowerShell 指令、每個檔案的來源，以及 research input 與人工決議的說明。小型人工 spreadsheet 專案可參考[基本流程](docs/e2e/high-level-cli.zh-TW.md)。

## 安全與復原

`scan`、`extract`、research、翻譯、QA、report 與 finalize 只寫專案輸出；只有 `install` 寫入遊戲。安裝前請自行備份遊戲與專案。先用 `install --dry-run` 檢查；真正安裝會建立備份及 rollback metadata，可用 `bg3loc install --rollback <INSTALL_MANIFEST>` 還原。安裝前關閉遊戲；遊戲更新後重新掃描並產生相依資料。

不知道進度時，隨時執行 `production report`。Finalize 要求所有**已分類的 production rows** 都是 `MERGE_READY`；`WAITING_TRANSLATION`、`WAITING_RETRY`、`WAITING_REVIEW`、`BLOCKED` 指出尚待處理的工作。未分類 rows 另行列出，若要宣稱整個語料完成，必須先由 operator 作出明確決議。

## 文件與求助

- [新手與完整流程](docs/getting-started.md)
- [Ruleset 指南](docs/ruleset-guide.md)
- [疑難排解](docs/troubleshooting.md)
- [大型專案操作指南](docs/lstp/large-scale-production-guide.md)
- [CLI 文件](docs/cli/)與 `bg3loc --help`
- [架構與 schema](docs/architecture.zh-TW.md)、[工程驗收歷史](docs/lstp/)
- [虛構本機 demo](examples/demo/run_demo.py)（不需要遊戲檔或付費 provider）

請到 [GitHub Issues](https://github.com/CassiaLin/bg3loc/issues) 回報可重現的問題，附上指令、去識別的錯誤、平台及 BG3Loc 版本；不要上傳遊戲文本、API key 或私人 workspace。

授權條款：[MIT](LICENSE)。
