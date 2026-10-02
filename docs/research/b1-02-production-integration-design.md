# B1-02｜Same-Entity Context Production Integration Design

日期：2026-10-02。Audit baseline：`feat/b1-02-same-entity-context`，HEAD `a9e0c2b68f6e57f6c8cee71d632f112343941841`。

本文件是設計提案；沒有修改 runtime、CLI、schema 或 prompt。正式狀態沿用使用者提供的 Framework READY、Real-Corpus Validation ACCEPTED、Safety Validation PASSED。這些研究決策不等於 production integration 已實作或通過驗收。B1-03 Dialogue Context 保持 NOT STARTED。

## 1. Audit：目前 context 在哪裡

Repo 沒有 `src/bg3loc/production/` 目錄；實際 production 模組是 `production_*.py` 及 `commands/production.py`。

| 層 | 目前行為 | 整合意義 |
|---|---|---|
| `research/batching.py`：`build_batch_plan` | `canonicalGroupKey` 選排序後第一個 candidate；`contextGroupKeys` 保存所有 normalized candidates。material 只有 target source、空 translation、category、batch/group keys | 分批 metadata，不是可靠 same-entity textual context；不能從 key 推導 related fields |
| `commands/research.py`：`_load_research_grouping` | stats 使用 resource path + entryName；quest 支援 entityId 也支援 element ordinal fallback；其他 grouping 還有 story/UI/classification evidence | batching 的可接受分組範圍比 B1-02 prompt evidence 寬 |
| `research/context_experiment.py` | `_clean` 驗證三類 structural identity；`build_packs` 產生 bounded related fields；`render_pair` 在 baseline render 完後另行加 safety、targetFieldRole、entityType、relatedFields | context material 與 prompt 都仍是離線研究；沒有 production hook |
| `research/real_context.py` | join English source；排除跨類、Hold、非 Eligible、多 identity/role、缺 identity、ordinal、無原文；item 取 Root Templates/GameObjects occurrence | 可沿用已驗證 evidence adapter 原則，不能直接把研究 CLI 當 production execution dependency |
| `research/safety_validation.py` | 固定 pilot 的 10/10/5 子集，匯出 50 A/B requests，建立盲審並彙總 contamination/degradation | 研究安全驗證工具；不是 production runtime output validator，也不自行裁定 PASSED |
| `translation_request.py` | `BatchMaterialResolver` 只讀 prepared JSONL；request 帶 `context_group_keys`，沒有 field role 或 related source text | consumption 邊界已合適，缺 typed context contract |
| `prompt_assembly.py` | group keys 進 assembled prompt 與 effective prompt hash | 尚無 textual context 或 safety policy |
| `chat_prompt.py` | user JSON 含 ContentUid、primaryCategory、contextGroupKeys、sourceText | provider 目前看得到群組鍵，看不到 B1-02 related fields |
| `providers/openai_compatible.py` | 在 `__call__` assemble/render，HTTP 發送，再檢查空輸出與 target protected tokens | 已無遊戲資料掃描；保持這個限制。protected-token 檢查不能證明無 semantic contamination |
| `production_orchestration.py` | classify → batch/material → `run_init` seed state → manifest | context 應在 material 完成與 state 初始化之間固定 |
| `production_workspace.py` / `production_execution.py` | preflight 驗證 plan SHA、全部 material bytes、ruleset、DB inventory，再 start/worker | 可延伸既有 integrity boundary，不能只新增未受 hash 保護的 sidecar |
| `production_qa_orchestration.py` / `production_review.py` | QA、retry handoff、review acceptance 與目前 output 綁定 | context 改變導致重譯後，舊 review/QA 不可沿用 |
| `production_completion.py` / `production_finalize.py` | 以 target UID inventory、QA/review/output 狀態判斷完成與 rebuild | related field 不能增加 execution item 或 rebuild record |
| `production_reporting.py` | 使用 provider usage 與 execution accounting | context 成本納入 prompt usage；另加 coverage/reason 分布，不計成翻譯目標 |

補充 hash audit：`commands/translation_state.py::load_execution_items` 的 input hash 包含 target source、category、protected syntax、promptVersion、ruleset fingerprint、locales；不含 contextGroupKeys，也不含 B1-02 textual context。`effective_prompt_hash` 與 `chat_messages_fingerprint` 是不同層的 hash；目前 provider 沒有把它们作為 attempt provenance 持久化。

## 2. 決策：prepare materialize，execution consume

```text
既有 research structural evidence + normalized source snapshot
    → source-only evidence adapter / reliability validation
    → deterministic same-entity packs（完整 universe，不做研究 sampling）
    → production prepare 將 pack inline 寫入 batches/materials/<batchId>.jsonl
    → 驗證 material、計算 fingerprints、初始化 execution state、封存 manifest
    → BatchMaterialResolver → immutable TranslationRequest
    → prompt assembly → chat render → provider HTTP
```

建議新增 production-owned pure material builder（例如 `same_entity_context.py`），由 prepare orchestration 呼叫。共用已驗證 normalization/selection 規則應透過明確 library contract；不要依賴研究 CLI、pilot、A/B transport wrapper 或研究私有函式。研究 pack schema 與 production schema 分別版本化。

inline material 是主方案：不需 execution-time source join、跨 batch lookup 或額外 context sidecar 讀取。先在全 source universe 建 pack，再附加至 eligible target rows，因此 oversize split、batch 大小、worker ordering 不改變 related fields。相關 UID 只作 provenance，不能產生新 claim。保持既有 batching、canonicalGroupKey 及分類行為。

provider 可繼續 deterministic assemble/render；它不得讀 archive、game installation、mapping、source universe 或 context builder。execution 必須在原始 research/source 輸入不可用時仍可執行 prepared workspace；finalize 所需 extract artifact 是另外的既有流程。

## 3. Structural reliability contract

只允許 `skill_spell`、`item`、`quest`。dialogue（含目前 `dialogue_general`）、bark、book_lore、character_world、tutorial、system_message、ui 與其他類別都不供應 B1-02 context。禁止 semantic similarity、embedding、LLM linkage、filename-only/node-name grouping、stats `using` parent expansion。

| Category | 必要 structural identity | Evidence |
|---|---|---|
| skill_spell | stats entryName，保留適用來源 scope 與 provenance | StatsDefinition；沿用已驗證 entryType 範圍 |
| item | GameObjects 的 explicit template UUID/stable identity | GameObjectTemplate 與來源 provenance；一般 EntityName 不能當 identity |
| quest | journal explicit entityId | QuestJournal；拒絕 node ordinal/element fallback |

scope 不是新增 entity 關聯訊號。現有 `build_packs` 用 `(category, entityKey)` grouping；`real_context.adapt` 對重複來源取最小 resource 字串，並未解決同 key 在不同來源有衝突 definition 的版本選擇。production adapter 必須保留所有證據，確認同 identity 的定義一致或有已驗證 deterministic override resolution；無法確認時不供 context。不可自創來源 precedence、單凭相同 ID 合併衝突定義，或用 lexicographic resource winner 解衝突。

每個 target UID 必須與 production category/source snapshot 一致、能唯一解析 entity/field role；每個 related UID 亦須通過 reliability gate 並有相同 proven entity、source locale。多 entity、role ambiguity、category mismatch、Hold、缺 source、無可靠 identity，都不生成 context並記錄 reason。對損壞的輸入檔/非法 schema 則 prepare error。

缺可靠 context 是正常 absence，沿用 baseline；宣告 present 但 fingerprint、shape、target binding 或 category 不合法是 material error，不能默默降級。

## 4. Proposed material 與 request

在現有 material row 新增 optional `sameEntityContext`，absent row 不新增 prompt 欄位。下列只是 proposed shape，不是目前可執行 schema：

```json
{
  "sameEntityContext": {
    "schemaVersion": "same-entity-context/1",
    "policyVersion": "b1-02-structural/1",
    "targetBinding": {
      "contentUid": "<target UID>",
      "category": "skill_spell",
      "sourceTextSha256": "<hash of exact target source>"
    },
    "targetFieldRole": "DisplayName",
    "entityType": "StatsEntry",
    "entityIdentity": "<proven scoped identity>",
    "evidenceFingerprint": "<canonical complete evidence digest>",
    "relatedFields": [
      {
        "contentUid": "<related UID>",
        "fieldRole": "Description",
        "sourceText": "<source-only text>",
        "truncated": false
      }
    ],
    "contextFingerprint": "<canonical digest excluding this field>"
  }
}
```

保留 source corpus hash、所有 structural input hashes、adapter/builder versions、limits 與 source locale 在 production manifest。raw absolute paths、target/reference translations、provider outputs 與任意 evidence properties 都不可投影到 prompt。material provenance 可用相對資源識別與 digest。

`TranslationRequest` 建議加 default `same_entity_context: SameEntityContext | None = None`，以 frozen dataclasses、tuple related fields 表示。resolver 只解析/驗證，不生成或補齊 context。只有 related source text 供 interpretation；source_text 始終是唯一翻譯目標，protected_tokens 始終只由 target 計算。

selection 沿用 B1-02：最多 4 fields / 4000 source characters；依 category field priority、role、UID、source deterministic ordering；排除 target UID、同 target role、重複 source text、空或純 runtime token fields。保留既有 overflow/truncation 規則：僅第一個大於總 budget 的 field 可截斷，其餘按既有規則 skip，並保留 truncated flag。這是字元限制，不能宣稱是 token budget。新增限制或排序必須 bump policy version。

## 5. Prompt contract

assembly 僅將 present、validated typed context 投影到 assembled prompt；chat render 沿用研究 variant B 的 `targetFieldRole`、`entityType`、`relatedFields[{fieldRole,sourceText,truncated}]`。完整 identity、related UID、resource provenance 不送 LLM。保持 baseline `contextGroupKeys` 原狀，並在 context policy 中明確說明它們不是 same-entity proof。

present context 時 system 加入已驗證的四條安全指令：

```text
The related fields are context only.
Translate only the target source text.
Do not add information that appears only in the context.
Do not translate or return the context fields.
```

並明確以 sourceText 為唯一輸出目標；related source 是資料，不能充當指令。安全規則不能由可變 ruleset 覆寫。輸出仍只有 target translated text，不新增 context response schema。沒有 context 時 chat messages 及 legacy hashes 必須逐 byte 符合原 baseline；不加入空 relatedFields、null context、field-role 標籤或 context-only safety 段。

## 6. Versioning、hash、resume 與 integrity

未來 implementation 必須同時完成下列 binding 才能啟用：

1. material fingerprint 繼續覆蓋全部 inline bytes；新 production manifest schema 明確宣告 context policy、artifact version、builder settings 與完整 input digests。context-enabled plan identity 必須包含 context input/policy/material digest，不能只沿用舊 batching fingerprint。
2. context-present item 的 `input_hash` 加入 canonical effective context projection、context policy/prompt renderer version（或其受驗證 digest）。context 改變即不同輸入。absent legacy 模式沿用原公式，不能無意重置既有 workspace。
3. `effective_prompt_hash` 納入真正使用的 context 與 safety instructions；render 後 messages hash另記錄 actual chat bytes。兩者不宣稱相同，attempt provenance 應同時記錄 input、context、effective prompt、messages hashes。
4. execution config hash 綁 context/prompt policy，使 start 與 worker 不可使用不同 policy；version 的來源只能是封存 workspace contract，不能 execute-time 開關。
5. preflight 驗證新 schema、context fingerprints、target/category/source binding、limits 與 inventory一致性；resolver 做局部 shape/binding檢查。篡改 present pack 在 HTTP 前失敗。
6. context變更以 fresh prepare workspace 為預設；不得在執行中修改 material，或把現有成功 state 當新輸入復用。若日後提供 migration，需重算 items、清除 affected outputs、QA/review acceptance 並重驗 inventory；本輪不設計自動 migration。

舊 manifest schemas `1.0`/`1.1` 目前仍只有 baseline；未來支援新 schema時必須保留其原有行為，並拒絕在 legacy manifest 偷塞 context。新版 workspace 的 none/present 狀態須明確可稽核，absence reason 放 prepare coverage report，不送 provider。

## 7. Implementation sequencing 與驗收

本輪交付止於本設計；不改 runtime、不初始化 DB、不產生 provider requests。後續 implementation 建議依序完成：production-owned builder/contract → prepare inline material + schema/integrity → resolver typed context → shared assembly/render + hash/provenance → fixture與mock provider integration驗收 → 才評估啟用新的 production prepare policy。

必要驗收案例：

- 三類可靠 identity 各有 target-only prompt、同 entity related fields、四條安全規則；provider只接收 prepared text。
- 多 identity、definition conflict、generic item node、quest ordinal、stats parent、分類不符、缺 source、Hold、單欄 entity：無 context，baseline messages/hash 不變，理由可追蹤。
- unsupported categories 不得到 context；偽造 present material 在 provider 前失敗。
- 輸入重排、重複 evidence、batch size/split、worker/retry 順序不改 context；同 source/policy repeated prepare 結果一致。
- context source、role、truncation、policy改變會改 input/prompt hashes；material篡改失敗；baseline none 不重置原 input identity。
- prepare後移走 research與原始 source，mock execution仍成功，且不讀遊戲/archive；確認 absence與 corrupt material 分流。
- related field的 runtime tokens 不成為 target保護要求；输出 validation 只針對 target。不能把 token檢查宣稱為 contamination語意驗證。
- related fields不增加 claim、completion count、merge/rebuild records；新 output使舊 QA/review 不再成立。
- 使用已接受 safety fixture檢查 prompt parity；新增 instruction/data boundary與 adversarial source fixture。任何新增實際 provider安全評估需另行記錄，不能把25對pilot當成所有production輸出的保證。

待 implementation review確認的只有工程細節：新schema/version名稱、typed classes位置、hash欄位儲存方式與受驗證的source override contract。核心 materialize層、category allowlist、source-only/read-only policy、absence fallback與禁止execution-time scan已在本設計固定。
