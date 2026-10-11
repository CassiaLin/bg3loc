# Windows Basic｜高階 CLI

[English](high-level-cli.md) · [新手指南](../getting-started.zh-TW.md)

此頁反映已接受 M2-B1／B2 的當前行為，標準路徑停在唯讀 Dry-run；Apply／Rollback 與 Stable Release 驗收仍 pending。

## 指令與實際參數

Project／workflow 預設讀 `bg3loc-project.json`，不同位置用 `--project <FILE>`；`project init` 的輸出參數是 `--output`，不是 `--project`。

| 指令 | 參數／行為 |
| --- | --- |
| `project init` | 必填 `--name --source --target`；可用 `--game-dir`、重複 `--content-uid`／`--reference`、`--format xlsx|jsonl|csv`、`--workspace`、`--output`。預設 basic／standard，拒絕覆寫 config。 |
| `project check` | `--project`；驗 schema／路徑／角色／scope，不 Prepare，也不證明當前遊戲 hashes。 |
| `workflow prepare` | `--project`；自行 scan/extract、receipt、package、returns。此處沒有 `--scan`、`--source`、`--force` 或 `--format`。 |
| `workflow validate` | `--project`、可選 `--input <FILE_OR_DIRECTORY>`；current input／receipt／technical QA，綁定實際 explicit input，不直接匯入一般 AI response。 |
| `workflow rebuild` | `--project`；要求 current accepted snapshot，使用 auto container。沒有高階 `--container` 或 `--output`，會印 artifact 路徑。 |
| `workflow install` | `--project`；預設每次 fresh dry-run。沒有高階 `--dry-run`；`--apply` 才寫遊戲，須另行授權／驗收。 |
| `workflow status` | `--project`；讀 state 印進度與 paths，不是完整 live preflight。 |

`workflow review prepare/integrate/resolve`、context/full 是進階。Basic 預設 structural review set／language ruleSets 為空；仍有 required rows、immutable identity/source、placeholders／markup 的技術驗證，不會自動執行 Quest／UI／拼字／語意審查，也不建立 Production DB。

## 回填與 UID scope

只改 `returns/*.xlsx`／`returns/*.jsonl` 生成副本，不改 package delivery baseline。填 `ProposedTargetText`、`TranslationStatus=translated`；notes/name 選填。`ContentUid`、locale、原文、presence、required flag、tokens、evidence/context/comparison，以及生成的 versions 保持原樣。XLSX 留原欄名；JSONL 留型別及每行一個 object。`intentionally-empty` 是明確空譯決定，不能拿來略過未做工作。[虛構範例](../../examples/windows-basic/README.md)不可當作真實專案輸入。

建立專案時重複 `--content-uid` 只限制翻譯列，選中 required rows 都須回填；仍讀完整語言 baseline，重建完整 LOCA／PAK 並保留其他內容。不是只在檔案系統安裝一行文字，不推斷對話關係。沒有 scope 時選全部列。

## Receipt 與當前资格

Prepare 在 `workspace/e2e/package/internal/bindings/basic-source-baseline.json` 自動封存 receipt，綁定原 source/target/reference PAK、Scan/Extract、完整 normalized/XML/LOCA/aligned。Internal 只留本機，不編輯、不交外部 AI、不手工替舊 workspace 補 evidence。後續驗證／重建／install 要核對原 paths／bytes 與 origin，仍需 Divine。改動來源須 fresh Prepare，不寫新 hash 來假裝舊素材合法。

Current eligibility 與歷史成功不同。新 validation 開始／失敗／中斷撤銷下游資格；回填改動須重新 Validate。未改且合法的 validated/rebuilt snapshot 可重用，但 Basic dry-run 每次檢查當前 artifact／destination，不能直接回報 cached PASS。磁碟有歷史檔不等於當前可安裝。

Runtime file 是 `workspace/e2e/workflow-state.json`；`e2e-workflow-state.schema.json` 只是 public 定義。看 current stage status 與 CLI output；artifacts/history aliases 可保留 last success，即使 current eligibility 已撤銷。

| `workspace/e2e/` 下位置 | 含義 |
| --- | --- |
| `validation/snapshots/<operation>/` | 獨立驗證 snapshot／diagnostics，FAIL 不覆寫 prior accepted bytes |
| `rebuild/pending-<operation>/` | 處理中的候選，不是 current success |
| `rebuild/history/<operation>/` | 成功 artifact snapshot，仍須 current eligibility |
| `rebuild/failed/<operation>/` | 隔離失敗候選，partial LOCA／舊 manifest 不代表此次成功 |

用 state 的 `artifacts.rebuildManifest` 與 CLI 印出的 path，不硬寫舊固定檔名。不要刪／改 state 或手動 promote failed files。History 不自動清理，磁碟用量會成長。

## 復原與寫入邊界

修正回填後 Validate → Rebuild → Dry-run。遊戲／來源更新、baseline 改／缺、舊 workspace 無 receipt、edited returns 屬於舊 package 時，保留舊專案，改用全新 workspace；核對 current UID/source/version 後人工 rebase。不會自動遷移或補 historical evidence。詳見[新手指南復原](../getting-started.zh-TW.md#復原)。

Dry-run 只寫 project evidence，不寫遊戲、不建遊戲備份；不證明遊戲載入、語意、crash safety 或 Stable Release。`workflow install --apply`、`install --rollback <MANIFEST>` 會寫遊戲，須另行明確計畫／授權／验收。低階 `install` 沒 `--dry-run` 會預設 apply，也不檢查 current workflow；history package 可能獨立 preflight PASS，但不能自動繞過高階失敗。

Production／Provider、B1-02、context/full research review、Legacy Production Finalize 不在第一版 Basic RC 範圍；B1-03 OFF、transport blocked。維持單一操作者／原路徑／Windows，不宣稱 detached portability、並行寫入／更新、native Linux/macOS 或通用對話語意安全。

## 保留的 E2E-01E 歷史紀錄

以下原 milestone 與歷史 synthetic count 保留，不代表當前 Basic RC release verdict。當前證據／門檻見 [M3 報告](../research/bg3loc-mainline-m3-public-docs-rc-readiness.md)。

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
