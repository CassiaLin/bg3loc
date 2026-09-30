# B1-02 Same-Entity Context Experiment / 同實體脈絡實驗

## Status / 狀態

**Framework = READY; Real-Corpus Validation Phase 1 = ACCEPTED; Provider A/B Pilot = PENDING; Human Quality Evaluation = PENDING; Production Integration = NOT STARTED.** This branch supplies an offline experiment format and real source-side measurements. It does not show that context improves translation. / 本分支提供離線實驗框架與真實來源端量測，尚未證明脈絡會改善翻譯。

## Input and policy / 輸入與政策

Run `PYTHONPATH=src python -m bg3loc.research.context_experiment --input records.jsonl --ruleset ruleset.json --output workspace/b1-02`. The output path should be local and ignored by Git. No provider is called. / 使用來源端 JSONL 與既有 ruleset；輸出放本機忽略目錄，不呼叫模型。

Each input line needs `contentUid`, `category`, `fieldRole`, `sourceText`, and `structuralEvidence`. Skill needs `entryName` + `StatsDefinition`; item needs explicit `templateId` + `GameObjectTemplate` + `resourceIdentity`; quest needs explicit `entityId` + `QuestJournal`. Future extractors may instead pass `ContextSourceRecord` through `normalize_records`. Only an allowlist of source-side fields enters the pack; any target translation field is discarded. The upstream adapter must resolve provider precedence and prove identity before emitting records. / 輸入必須有可證明的實體身分；builder 只保留原文與結構白名單，譯文欄位會被丟棄。上游轉接器需先解決來源優先序與身分歧義。

Same category + structural entity key is grouped. Exclude target UID, same field role, empty or nonlinguistic text, duplicate UID, and duplicate source text (case-insensitive). Priority is centralized by category; unknown roles sort afterward. Sort by priority, role, UID, then text. Select at most **4** fields and **4000** source characters. Prefer whole fields; skip a field that could fit whole in a fresh budget. Only a single field longer than the total budget may be cut; it carries `truncated: true`. / 同類與同實體分組；排除目標、相同欄位角色、空白或非文字、重複 UID／原文。依欄位優先序排序，最多四欄、四千字。優先保留完整欄位；只有單欄本身超限才截斷並標記。

Sampling is deterministic: observed field-kind, source-length, and related-field-count strata are round-robin selected, with SHA-256 target order inside each stratum. Canonical JSON yields pack, sample and prompt hashes. The manifest records synthetic sample counts and character deltas only when run on the fictional fixture; those numbers are **not real corpus findings**. / 抽樣以固定分層與雜湊順序執行，並產生可重現指紋；虛構範例的數量與字元成本不能當真實結果。

## Prompt variants / Prompt 版本

A uses the existing pure v1.3 assembly and renderer plus an experiment target field role. B starts with identical ruleset, glossary, protected tokens, target text, category, and field role, then adds source-side related fields and context-only safety instructions. Neither variant gets target-language references. / A 沿用現有純函式組裝與渲染，另標示實驗欄位；B 保留相同規則、詞彙、保護 token、目標原文與類別，只增同實體原文及防污染指令。兩版都不含目標語參考。

Fictional example / 虛構例子:

```text
A user payload: {"primaryCategory":"item","sourceText":"A silver charm that glows at dusk.","targetFieldRole":"Description",...}
B user payload: same target plus {"relatedFields":[{"fieldRole":"DisplayName","sourceText":"Moonstone Charm","truncated":false}]}
B system addition: The related fields are context only. Translate only the target source text.
```

The exact full prompts and hashes are written to `b1-02-prompts.jsonl`; manifest goes to `b1-02-experiment-manifest.json`. / 完整 A/B prompt 與雜湊輸出至 JSONL；manifest 另存 JSON。

## Later validation / 後續驗證

- Real corpus coverage measurement = **COMPLETE** / 真實覆蓋率已測
- Real sample generation = **COMPLETE** / 真實樣本已產生
- Prompt character delta measurement = **COMPLETE**; token estimate = **NOT MEASURED** / 真實字元增量已測，token 估計未測
- Provider A/B pilot = **PENDING** / 模型試驗待做
- Human quality evaluation = **PENDING** / 人工評分待做
- Production integration decision = **PENDING** / 正式整合決策待做

The later pilot should use independent requests with identical provider, model, settings, ruleset, glossary, and protected token policy; its only treatment is related source context. Use blind review and report by category and target/related role pair, including better/worse/tie and contamination cases. / 後續試驗應讓兩版使用相同模型設定與規則、獨立請求；盲評時按類別及欄位組合報告勝負與污染案例。

## Real-Corpus Validation Phase 1 / 真實語料驗證第一階段

The `real_context` adapter consumes three existing research outputs: normalized **English** source JSONL, `research-mappings.jsonl`, and `ui-skill-universe.csv`. It reads no target localization. Stats `entryName` supplies skill/spell identity; Quest Journal `entityId` supplies quest identity; Root Templates `GameObjects` UUID supplies item identity. Stats and item field names and quest field roles remain intact. An unresolved or conflicting UID is excluded and counted. The generic `context_experiment` module remains independent of the game installation and PAK files.

PowerShell reproduction (substitute an accessible archive backend and local output paths):

```powershell
$env:PYTHONPATH = 'src'
$env:BG3LOC_DIVINE_EXE = '<LSLIB_DIVINE_EXE>'
python -m bg3loc research scan --game-dir '<BG3_GAME_DIR>' --output workspace/b1-02/research-scan.json --source English --target ChineseTraditional
python -c "import json,pathlib; p=pathlib.Path('workspace/b1-02/research-scan.json'); d=json.loads(p.read_text(encoding='utf-8')); keep={'StatsResource','JournalQuest','RootTemplates','SourceLocalization','TargetLocalization'}; d['resources']=[r for r in d['resources'] if r['sourceRole'] in keep]; d['resourceCount']=len(d['resources']); pathlib.Path('workspace/b1-02/research-scan-scoped.json').write_text(json.dumps(d,ensure_ascii=False,sort_keys=True),encoding='utf-8')"
$mapDir = 'workspace/b1-02/research-map-context-only'
New-Item -ItemType Directory -Force $mapDir | Out-Null
Set-Content -LiteralPath "$mapDir/story-occurrence-ledger.csv" -Value 'ContentUid,PakName,InternalPath,ResourceFamily,ResourceFormat,StoryDomain,NodeId,AttributeRole,HasSpeaker,HasDialog,HasQuest,IsOldText' -Encoding utf8
python -m bg3loc research map --scan workspace/b1-02/research-scan-scoped.json --output-dir $mapDir
python -m bg3loc scan --game-dir '<BG3_GAME_DIR>' --output workspace/b1-02/extract-scan
python -m bg3loc extract --scan workspace/b1-02/extract-scan/scan-manifest.json --source English --target ChineseTraditional --output workspace/b1-02/extract
python -m bg3loc.research.real_context --source workspace/b1-02/extract/normalized/English.jsonl --mappings "$mapDir/research-mappings.jsonl" --ui-skill-universe "$mapDir/ui-skill-universe.csv" --ruleset docs/lstp/ruleset-example.json --output workspace/b1-02
```

The scoped scan includes only stats, journal, Root Templates, and localization resources. The header-only story occurrence ledger suppresses extraction of dialogue and level evidence, which are outside this phase; the existing map command still parses the scoped stats and journal resources and builds the UI-skill universe for item templates. The ignored `workspace/b1-02/` directory contains `real-context-records.jsonl`, `b1-02-prompts.jsonl`, both experiment manifests, and `real-corpus-summary.json`/`.md`. Re-run the final command with unchanged inputs and compare `sampleFingerprint`, sample order, and `promptVariantHashes`. The summary distinguishes all category UIDs, structurally eligible rows, and rows with usable context. It also reports field roles, entity sizes, related-field counts, character cost, limits, and exclusions. Prompt output contains real English game text and must remain local. The adapter uses no translation provider.
