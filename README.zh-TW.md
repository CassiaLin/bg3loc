# BG3Loc

[English](README.md)

BG3Loc 從你自己安裝的《柏德之門 3》準備翻譯素材、檢查回填成果並重建語言檔。第一次使用請走 **Windows Basic**：少量 UID、人工或外部 AI 翻譯、XLSX／JSONL 回填、Validate、Rebuild、唯讀安裝 Dry-run。

目前正準備 Windows Basic Release Candidate。**Stable Release 與真實遊戲 Apply／Rollback 驗收仍待完成。** 技術驗證不判斷翻譯品質，也不代表產物已通過遊戲內載入測試。

## 從 Windows Basic 開始

需要自己的 BG3 安裝、Python 3.11 以上（範例使用 3.12），以及自行取得的 [LSLib／Divine backend](docs/concepts/archive-backends.zh-TW.md)。工具不附遊戲文本、官方翻譯、PAK／LOCA、憑證或 LSLib。

在此 checkout 的 PowerShell 執行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install .
bg3loc --version
$env:BG3LOC_DIVINE_EXE = 'C:\Tools\LSLib\Packed\Tools\Divine.exe'
Test-Path -LiteralPath $env:BG3LOC_DIVINE_EXE
```

請填入實際下載的 `Divine.exe` 路徑，上方只是例子。專案放在遊戲目錄與 repository 外。[新手指南](docs/getting-started.zh-TW.md)會先带你查看已安裝語言、從自己的 source extract 選出真實 UID，再建立小範圍專案。

選好兩個 UID 後，在專案目錄執行；所有 placeholder 都必須替換，English／French 只是語言例子：

```powershell
bg3loc project init --name 'Basic pilot' --game-dir '<BG3_INSTALL>' --source English --target French --evidence-profile basic --translation-strategy standard --format xlsx --content-uid '<UID_1>' --content-uid '<UID_2>'
bg3loc project check
bg3loc workflow prepare
# 編輯 workspace/e2e/returns/*.xlsx；建立專案時可改用 --format jsonl。
bg3loc workflow validate
bg3loc workflow rebuild
bg3loc workflow install
bg3loc workflow status
```

`workflow prepare` 會自行 scan／extract。Basic 不自動呼叫 Provider；在工具外翻譯，保留生成的 UID／source 等欄位，把譯文填入 `ProposedTargetText`，`TranslationStatus` 設為 `translated`，保留 runtime placeholders 與 markup。詳見[回填欄位與 CLI](docs/e2e/high-level-cli.zh-TW.md)及[虛構範例](examples/windows-basic/README.md)。

`--content-uid` 只限制翻譯列，仍會讀完整語言 baseline 並重建完整語言封裝；不加此參數會選取全部列。Rebuild 印出當前 artifact 路徑，請使用它或 workflow state，不要猜舊檔名。

## 當前成果與復原

Basic 核對 Prepare 時封存的 source／baseline receipt、當前回填雜湊、確切 accepted validation snapshot、重建 artifact 雜湊與 fresh destination preflight。Validation 失敗或輸入改變會撤銷當前安裝資格；歷史成功成果仍保留，pending／failed 輸出隔離保存，不能代表目前流程成功。

修改回填後重跑 Validate → Rebuild → Dry-run。遊戲／來源更新、舊 Workspace 缺 receipt、Extract／baseline 改動時，保留舊專案與回填，改用**新 Workspace** Prepare，再人工核對 UID／source／version 搬入可沿用的譯文。不要手動建立 receipt 或修改 hashes。詳見[復原](docs/getting-started.zh-TW.md#復原)。

## Dry-run 與遊戲寫入

`bg3loc workflow install` 不加 `--apply` 就是 Dry-run；檢查當前 state 與 destination，不建立遊戲備份、不修改遊戲檔，只寫專案 evidence。Dry-run 不等於遊戲內載入測試，也不是安裝授權。

`workflow install --apply` 與 `install --rollback` 會寫入遊戲，必須另行明確決定與驗收；**不屬於此指南要直接執行的步驟**。低階 `install` 若沒有 `--dry-run`，預設就會套用。不要用它繞過高階 workflow 失敗。

## 進階能力與發布限制

Production／自動 Provider、Legacy Production Finalize、B1-02 Same-Entity Context、context/full profile、研究型 review 都不在首版 Windows Basic 驗收範圍。B1-03 Dialogue Context 預設 OFF，production transport 仍封鎖。程式與研究保留不代表 RC 已啟用或驗收這些功能。

維持單一操作者並保留原 Extract／baseline 路徑；不承諾 detached portability、持續並行遊戲更新、Linux／macOS native 驗收、全語料翻譯或通用對話語意安全。RC 仍須 fresh wheel／sdist privacy audit、四個 hosted CI jobs、允許 socket 的真實 HTTP demo，以及另行授權的 Windows 遊戲載入／Apply／Rollback 證據。

- [Windows Basic 新手指南](docs/getting-started.zh-TW.md)
- [Basic 高階 CLI](docs/e2e/high-level-cli.zh-TW.md)
- [保留的進階 Production 指南](docs/production-getting-started.md) — 不在 Basic RC 驗收範圍
- [疑難排解](docs/troubleshooting.md)、[工程歷史](docs/lstp/)、[研究歷史](docs/research/)
- [M3 文件與 RC 門檻報告](docs/research/bg3loc-mainline-m3-public-docs-rc-readiness.md)

請在 [GitHub Issues](https://github.com/CassiaLin/bg3loc/issues) 提供指令、去識別錯誤、平台與版本；不要上傳遊戲文本、封裝、API key、生成的 receipt／returns 或私人 Workspace。授權條款：[MIT](LICENSE)。
