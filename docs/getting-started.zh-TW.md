# 新手指南：Windows Basic

[English](getting-started.md) · [README](../README.zh-TW.md) · [CLI 文件](e2e/high-level-cli.zh-TW.md)

此路徑停在 **Dry-run**。Apply／Rollback 與遊戲載入測試必須另行明確決定、規劃及验收；Basic RC 尚未宣告 Stable Release。維持單一操作者、保留原 Extract／baseline 路徑，所有遊戲及專案資料留在本機。

## 1. 安裝工具

使用 Windows、自己的 BG3 安裝與 Python 3.11 以上。範例用 3.12；在包含已接受 M2-B1／B2 的 checkout 執行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install .
bg3loc --version
bg3loc project init --help
```

沒有 3.12 時用已安裝的支援版本 `python -m venv .venv`。若 PowerShell 禁止 activation，可直接呼叫 `.\.venv\Scripts\python.exe` 與 `.\.venv\Scripts\bg3loc.exe`，不必修改整台電腦的安全設定。目前 checkout 回報 1.3.0，但版本字串不能證明下載產物已含這次修改；未來 RC wheel 必須核對來源與 checksum。

從 [Norbyte LSLib 專案](https://github.com/Norbyte/lslib) 自行取得工具，解壓整份 distribution 並保留 runtime 檔案；找 **Divine.exe**，不是 GUI converter。設定實際路徑：

```powershell
$env:BG3LOC_DIVINE_EXE = 'C:\Tools\LSLib\Packed\Tools\Divine.exe'
Test-Path -LiteralPath $env:BG3LOC_DIVINE_EXE
```

印出 `False` 就先停止。路徑只是例子；既有 Native 證據使用目錄標示 LSLib v1.20.4 的工具，不代表其他版本自動驗收。详見 [backend 設定](concepts/archive-backends.zh-TW.md)。後續來源重驗仍需要 backend；BG3Loc 不附 LSLib／遊戲封裝／翻譯。

## 2. 檢視語言、選擇小範圍 UID

在遊戲與 repository 外建立全新專案目錄，填入自己的遊戲路徑；English／French 是例子：

```powershell
$project = 'C:\BG3Projects\basic-pilot'
$game = 'C:\Program Files (x86)\Steam\steamapps\common\Baldurs Gate 3'
New-Item -ItemType Directory -Path $project
Set-Location -LiteralPath $project
bg3loc scan --game-dir $game --output inspection-scan
$scan = Get-Content inspection-scan/scan-manifest.json -Raw | ConvertFrom-Json
$scan.locales | Select-Object localeId, status, packageFile
```

選取不同、已安裝且 `status=ready` 的語言。未知／有歧義的語言要先處理，不自行猜。非 Steam 或未知 build ID 不會直接被拒絕，但 PAK bytes 仍須符合 Scan；不要為了測試改動遊戲來源檔。

```powershell
$source = 'English'
$target = 'French'
bg3loc extract --scan inspection-scan/scan-manifest.json --source $source --target $target --output inspection-extract
$extract = Get-Content inspection-extract/extract-manifest.json -Raw | ConvertFrom-Json
$sourceInfo = $extract.locales | Where-Object { $_.localeId -eq $extract.sourceLocale }
Get-Content -LiteralPath $sourceInfo.normalized | ForEach-Object { $_ | ConvertFrom-Json } | Select-Object -First 10 contentUid, version, text
```

選一、兩個確實存在於 source 的 UID，先挑自己能判斷意思的文字。清單含私人遊戲文本，不要貼到 Issues。下方 `$uid1`／`$uid2` 要填真實 UID；placeholder／repository 虛構範例不能選中你的遊戲列。

## 3. 建立並 Prepare Basic 專案

```powershell
$uid1 = 'PASTE_REAL_SOURCE_UID_1'
$uid2 = 'PASTE_REAL_SOURCE_UID_2'
bg3loc project init --name 'Basic pilot' --game-dir $game --source $source --target $target --evidence-profile basic --translation-strategy standard --format xlsx --workspace workspace --content-uid $uid1 --content-uid $uid2
bg3loc project check
bg3loc workflow prepare
bg3loc workflow status
```

每個指令非零 exit 或缺少預期輸出就先停止。`project init` 不覆寫現有專案檔；建立時可改用 `--format jsonl`。CSV 也有實作，但不在本指南範例路徑。設定檔的相對路徑以它所在目錄解析。

Prepare 會在 `workspace/e2e/` 自行 scan／extract，不直接使用上面的 inspection 目錄。Basic 不建 research context、自動 Provider run 或 Production execution DB。UID scope 只限制 delivery／required rows，**仍讀完整 baseline、重建完整語言 PAK**；省略 `--content-uid` 會選全部列。

主要產物：

```text
workspace/e2e/workflow-state.json
workspace/e2e/scan/scan-manifest.json
workspace/e2e/extract/extract-manifest.json
workspace/e2e/package/translation-package-manifest.json
workspace/e2e/package/internal/bindings/basic-source-baseline.json
workspace/e2e/returns/returns-manifest.json
workspace/e2e/returns/001.xlsx                # 或 001.jsonl，可能有多個檔案
```

Internal receipt 綁定原 Source／Target PAK、Extract、normalized、XML／LOCA 與 aligned material。它由程式產生並驗證，不是可編輯表單。保留完整 Workspace 及參照的來源；不要把 `internal/`／receipt 交給外部 AI。

## 4. 翻譯與回填

編輯 `workspace/e2e/returns` 的生成副本，不改 package delivery baseline。CLI 檢查前先儲存並關閉工作簿。人工或自行操作外部 AI 都可，Basic 不會自動傳送；只分享你決定提供的小範圍文字與必要 syntax，不上傳整個 Workspace／憑證／遊戲封裝。

| 欄位 | 處理方式 |
| --- | --- |
| `ProposedTargetText` | 翻譯 `SourceText`，保留 placeholders／markup |
| `TranslationStatus` | 完成非空譯文設為 `translated` |
| `TranslatorNotes`、`TranslatorName` | 選填筆記／署名 |
| `ContentUid`、locale、source、presence、required flag、protected tokens、evidence/context/comparison | 原樣保留，不改 ID／原文／version |

若确實要讓 required translation 為空，可明確設 `TranslationStatus=intentionally-empty`；不能用它略過尚未完成的工作。空白原文不授權新增內容。請自行審查意思；syntax QA 不能判定所有語意錯誤。

XLSX 保留欄名與列身分，只改 target/status cells。JSONL 每行一個完整 JSON object，維持 UTF-8、boolean／array 資料型別；AI 的一般文字、Markdown code fence、`{requestId, translationText}` 或自訂欄名**不是** Basic 回填格式。依原 UID 列對應外部結果並人工審查。[虛構回填範例](../examples/windows-basic/README.md)只示範欄位，不能匯入真實專案。

## 5. Validate → Rebuild → Dry-run

```powershell
bg3loc workflow validate
bg3loc workflow rebuild
bg3loc workflow install
bg3loc workflow status
```

Validate 核對 UID／coverage、immutable fields、runtime syntax 與 current receipt。Rebuild 要求確切 accepted snapshot 與未變動回填；之後又編輯回填就須重新 Validate，歷史成功產物不是當前核准。重建保留 target-only／blank／untouched records，驗 LOCA UID/version/text roundtrip 及全部未替換 PAK entries。

Rebuild 印出的路徑在 `workspace/e2e/rebuild/history/<operation>/`；manifest 位置由 state 的 `artifacts.rebuildManifest` 記錄。還須看當前 status／eligibility，單獨 history reference 不授予安裝資格。pending／failed 不是 current success，不能猜舊固定檔名。

`workflow install` 不加 `--apply` 每次執行 fresh destination／artifact／source／state preflight；不寫遊戲、不建立遊戲備份，但會保存專案 evidence。這不證明遊戲可載入產物或翻譯品質正確。

## 復原

| 情況 | 步驟 |
| --- | --- |
| 修改回填／Validate FAIL | 修正允許欄位、儲存關閉，重跑 Validate → Rebuild → Dry-run。新驗證／失敗會撤銷下游資格，舊成功檔仍留作歷史。 |
| Rebuild FAIL | 查報錯，保留 prior history／隔離 failed output；修好 backend／磁碟問題，若 current validation/input 仍一致可重跑 Rebuild。不要把 failed LOCA／PAK 放進遊戲。 |
| PAK／遊戲來源更新、baseline／Extract 改動或原檔遺失 | 保留舊專案／回填，停止使用舊 receipt。在新專案／Workspace Scan／Extract／Prepare／Validate，再人工核對 UID／source／version 沿用適合的翻譯。 |
| 舊 Workspace 沒 receipt | Fresh Prepare；不把 current files 新算 SHA 後手動當 historical evidence。 |
| Prepare 表示 edited returns 屬於舊 package | 先保留／archive；優先建立新專案／Workspace，不會靜默搬移 edits，不為取得 PASS 刪除已做翻譯。 |
| `project init` 拒絕覆寫 | 換新專案目錄／檔名，沒有可假設的 `--force`。 |
| 使用 `workflow validate --input <FILE_OR_DIRECTORY>` | 綁定實際輸入位置，該位置再改動就失效；不會自動改用 default returns。 |

替換專案在新目錄用上方相同 CLI 建立，仍要選當前安裝的合法 locale／UID。新目錄下 `--workspace workspace` 是獨立 Workspace。路徑維持短且固定；不是脱離原始素材的 portable bundle。不要改 manifests／手動恢復 eligibility。

## 指南停止點

Apply（`workflow install --apply`）、Rollback（`install --rollback <INSTALL_MANIFEST>`）會寫遊戲，**此指南不要求執行**。需另外明確核准具体 destination、原／候選 hashes、scope、可驗證備份及復原步驟，並停止遊戲與更新者；真實 game-load／Apply／Rollback 驗收仍 pending。

低階 `install` 不檢查當前高階 workflow，未加 `--dry-run` 會預設套用；history artifact 可能獨立 preflight PASS，但 current workflow blocked。不要拿它自動繞過高階拒絕。

Production／Provider、B1-02、research context/full 與 review protocols 是首版 RC 範圍外進階能力；B1-03 預設 OFF、transport blocked。保留的[Production 指南](production-getting-started.md)屬進階／歷史內容，發布待辦見 [M3 報告](research/bg3loc-mainline-m3-public-docs-rc-readiness.md)。
