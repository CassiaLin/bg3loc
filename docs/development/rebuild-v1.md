# Rebuild v1 safety contract / Rebuild v1 安全契約

## English

`bg3loc rebuild` is baseline-first. It never reconstructs a target locale from returned translation rows alone.

For `--container auto`, a discovered target `.pak` is rebuilt by fully extracting the original package, replacing only the selected LOCA entry, and repacking the complete staging tree.

Repack verification requires:

- the rebuilt package has exactly the same archive entry path set as the original package;
- the expected LOCA entry is still present exactly once;
- extracting the rebuilt LOCA from the rebuilt package produces the same SHA-256 as the standalone rebuilt LOCA artifact;
- unsafe archive paths such as absolute paths, parent traversal, or drive-like paths are rejected before staging.

`loca-only` remains available when only the rebuilt LOCA artifact is desired.

## 繁體中文

`bg3loc rebuild` 採 baseline-first。不得只用翻譯回傳列重新建立整份目標語言資料。

`--container auto` 遇到已發現的目標 `.pak` 時，必須完整解包原始 package，只替換指定 LOCA entry，再以完整 staging tree 重包。

重包後必須驗證：

- 重建 PAK 的 archive entry path set 必須與原 PAK 完全一致；
- 預期 LOCA entry 仍只能存在一次；
- 從重建 PAK 再抽出的 LOCA，其 SHA-256 必須與 standalone rebuilt LOCA artifact 完全一致；
- absolute path、parent traversal、drive-like path 等不安全 archive path 必須在 staging 前拒絕。

若只需要 LOCA artifact，可使用 `loca-only`。
