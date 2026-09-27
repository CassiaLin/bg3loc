# Schemas / 機器可讀規格

> **English / 繁體中文**

This directory contains machine-readable contracts for BG3Loc Universal Localization Core v1.  
本目錄收納 BG3Loc Universal Localization Core v1 的機器可讀 contract。

These schemas are normative implementation inputs. Markdown documents explain intent; files in this directory define structures that CLI code and tests should validate.  
這些 schema 是正式的實作輸入。Markdown 文件負責解釋設計意圖；本目錄的檔案則定義 CLI 程式與測試應驗證的資料結構。

## Files / 檔案

| File | Purpose | 用途 |
| --- | --- | --- |
| `scan.schema.json` | `scan-manifest.json` contract | `scan-manifest.json` 結構規格 |
| `extract-manifest.schema.json` | `extract-manifest.json` contract | `extract-manifest.json` 結構規格 |
| `localization-record.schema.json` | Normalized localization record | 正規化語言記錄 |
| `build-manifest.schema.json` | Translation-material build manifest | 翻譯素材 build manifest |
| `validate-manifest.schema.json` | Validation result manifest | 翻譯回傳驗證 manifest |
| `rebuild-manifest.schema.json` | Rebuild artifact manifest | 語言檔重建 artifact manifest |
| `install-manifest.schema.json` | Deployment and rollback manifest | 部署與回滾 manifest |
| `pipeline-state.schema.json` | Cross-command pipeline state | 跨 command pipeline 狀態 |
| `project-config.schema.json` | E2E project intent/config contract | E2E 專案意圖／設定 contract |
| `translation-package.schema.json` | E2E translation package manifest | E2E 翻譯套件 manifest |
| `translation-material-row.schema.json` | E2E logical translation row | E2E 邏輯翻譯列 contract |
| `translation-evidence-record.schema.json` | E2E evidence sidecar record | E2E 證據 sidecar record |
| `e2e-review-result.schema.json` | Normalized E2E review result | 正規化 E2E 審查結果 |
| `e2e-review-reconciliation.schema.json` | E2E review reconciliation record | E2E 審查整合／衝突解決 record |
| `e2e-manual-review-resolution.schema.json` | Explicit manual E2E text-conflict resolution | E2E 人工文字衝突裁決 record |
| `e2e-review-integration.schema.json` | E2E review gate/integration manifest | E2E 審查 gate／整合 manifest |
| `e2e-workflow-state.schema.json` | E2E orchestration runtime state | E2E 編排 runtime state |
| `bark-review-package.schema.json` | Bark evidence and review package | Bark 證據與審閱套件 |
| `quest-review-package.schema.json` | Quest occurrence-evidence review package | Quest occurrence 證據審閱套件 |
| `ui-skill-review-package.schema.json` | UI / Skill semantic-target review package | UI / Skill 語意目標審閱套件 |
| `multilingual-review-package.schema.json` | Multilingual auxiliary-evidence review package | 多語輔助證據審閱套件 |
| `taiwan-usage-rules.schema.json` | Project-supplied Taiwan usage rule-set contract | 專案提供的臺灣用語規則集格式 |
| `taiwan-usage-review-package.schema.json` | Taiwan usage human-review package | 臺灣用語人工審閱套件 |
| `error-catalog.json` | CLI exit codes and row-level validation errors | CLI exit code 與逐列驗證錯誤碼 |

## Canonical identity / Canonical Identity

All schemas that refer to localization content use `ContentUid` / `contentUid` as the canonical content identity.  
所有涉及語言內容的 schema 都以 `ContentUid` / `contentUid` 作為 canonical content identity。

The following must never become content identity:  
以下資訊不得成為內容身份：

- workbook file name / 工作簿名稱
- worksheet / 工作表
- row number / 列號
- batch id
- package order / 套件順序
- locale / 語言
- legacy phase/project ids / 舊 Phase 或專案 ID

## Compatibility rule / 相容性規則

`schemaVersion` changes only when the machine-readable contract changes incompatibly.  
只有在機器可讀 contract 發生不相容變更時，才提升 `schemaVersion`。

Additive optional fields should normally remain compatible within the same schema major version.  
單純增加 optional 欄位原則上應維持同一 schema major version。

## Implementation rule / 實作規則

CLI implementation should validate manifest input before performing the stage operation.  
CLI 在執行各階段操作前，應先驗證輸入 manifest。

A later stage must not silently repair an invalid earlier-stage manifest.  
後續階段不得偷偷修補前一階段的無效 manifest。

Installed packages also include these JSON schemas under `share/bg3loc/schemas`; runtime schema resolution must not depend on the user's current working directory.  
安裝後的套件也會把這些 JSON schema 放在 `share/bg3loc/schemas`；runtime schema 定位不得依賴使用者目前所在目錄。
