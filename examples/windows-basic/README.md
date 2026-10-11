# Windows Basic return example / 回填範例

These are **invented text and a fictional UID**, with no BG3 corpus. [returned-row.example.jsonl](returned-row.example.jsonl) illustrates a complete logical return row; it is not a translation package or a file to import into your game project. JSON schema validity alone cannot establish its binding to a prepared package.

這是**虛構文字與 UID**，不含 BG3 語料。範例展示完整邏輯列，並非可匯入你遊戲專案的翻譯套件。符合 JSON schema 不等於通過 Prepare 的素材綁定。

Start with your own generated `workspace/e2e/returns/*.xlsx` or `*.jsonl`. Edit `ProposedTargetText`, `TranslationStatus`, and optionally `TranslatorNotes` / `TranslatorName`. Preserve every other field exactly, including source, UID, locales, comparison fields, arrays and booleans. Preserve `{name}` and markup when present. The model must translate only the selected source text; manually map an external response back to its original row.

請編輯自己產生的回填檔，只填譯文、完成狀態及選填姓名／備註。其他欄位、資料型別、原文與識別資料保持原樣。保留 runtime tokens 及標記，將外部 AI 回應逐列對回原本 UID，不要把純文字回答或此範例直接當成回填檔。

For XLSX, retain generated column names and rows. The JSONL example's keys correspond to those fields, but it is not an XLSX converter. For JSONL, retain one complete UTF-8 JSON object per line; do not add Markdown fences. An intentionally empty required translation uses `intentionally-empty` only after an explicit decision, not to bypass missing work.

XLSX 保留欄名與列；JSONL 保留每行一個完整 UTF-8 JSON 物件，不加 Markdown 框。必要的空譯文須明確決定使用 `intentionally-empty`，不能藉此跳過未完成翻譯。

Use a small scope of actual UIDs from your own source. UID scope reduces translation rows but still rebuilds a complete language file/package. After saving and closing returns, run Validate → Rebuild → `workflow install` (default Dry-run). Stop on failure. Historical artifacts do not confer current eligibility. This example does not authorize Apply/Rollback.

從自己的原文選少量實際 UID；範圍限制回填列，但仍重建完整語言檔／套件。儲存並關閉回填檔後執行 Validate → Rebuild → 預設 Dry-run；失敗即停止。歷史成果不代表目前可安裝，本範例不授權 Apply／Rollback。

- [English tutorial](../../docs/getting-started.md)
- [繁體中文入門](../../docs/getting-started.zh-TW.md)
