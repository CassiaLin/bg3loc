# BG3Loc M7-P6 — Windows Hosted CI Test Portability Fix

2026-10-12。**READY FOR IMPLEMENTATION REVIEW**。修復四個已核准 test-only defects，本機矩陣通過；完整 suite 的環境阻擋仍單獨記錄，未宣稱 Hosted CI / Full PASS。

## 1. Source / Scope

Branch `integration/windows-basic-1.4.0rc1`；HEAD `f81185cf108741e62dcd5772c00b891553cc8ef8`；Tree `e8a2360702c1ec0f5dd92dbd6d6aa0a488d56f31`。C1–C6 親子鏈不變，index 未 Stage。本階段唯四個既有 test files 修改；此指定新報告是未提交交付物，不是第五個程式修復。Production code / CI / schemas / frozen contracts / identity / Receipt / provider guards 完全不變。

Preflight 核對 C6 421 個 source SHA 與 original dirty tree 416 個公開檔案／status。所有 build/test outputs 在 `D:/workspace/codex/BG3/m7-p6-evidence` 及專用外部 basetemp；native 8.3 temp 在允許的 C visualization root `m7-p6-path-repro/runneradmin` 下。没有讀取真實 corpus、付費 Provider 或修改遊戲。

## 2. Root Cause → 最小修正

| 已核准問題 | 修改 | 原 Assertions / Policy |
| --- | --- | --- |
| Portable partial import 的 UTF-8 output 被 default cp1252 解碼，byte 0x81 offset 218 | `tests/test_b1_02_portable_translation.py` 的 16 個已知 UTF-8 JSON/JSONL fixture/output/schema reads 明確 encoding="utf-8" | 2 received / 10 missing / 2 invalid、PROTECTED_TOKEN_MISSING、EMPTY_TRANSLATION、duplicate/unknown ID 全保留 |
| Blind review 原文在 default cp1252 讀成 mojibake，再以 UTF-8 重寫，正式 validator 正確拒絕 | `tests/test_dialogue_stage4r.py` 的 4 個 UTF-8 JSONL reads 明確編碼 | 不改譯文、assessment、seals 或 validator line 108；limited scope / non-PASS / changed source/translation rejection 保留 |
| 未建立的 state file expected root 留在 raw 8.3 spelling | `tests/test_e2e_project.py` expected state path `.resolve(strict=False)` | status/config SHA/完整 suffix 保留；不存在檔案不用 samefile() |
| relocation bindings 已 canonicalize，expected 三個 child paths 仍是 raw 8.3 | `tests/test_production_prepare.py` 三個 expected child paths `.resolve(strict=True)`，另核對 containment / samefile | workspace resolve、relocation、檔案存在與同實體要求保留並增強；不同路徑／實體不因字串或同 SHA 被接受 |

Diff 為 **27 insertions / 24 deletions**，沒有新 skip/exclude，也沒改翻譯內容、protected tokens、ratings、runtime error codes、指紋或來源契約。完整四檔 diff：

```diff
diff --git a/tests/test_b1_02_portable_translation.py b/tests/test_b1_02_portable_translation.py
index 18fffed..5646a62 100644
--- a/tests/test_b1_02_portable_translation.py
+++ b/tests/test_b1_02_portable_translation.py
@@ -56,7 +56,7 @@ def _package(tmp_path: Path, name: str = "package") -> Path:


 def _valid_responses(package: Path) -> list[dict[str, str]]:
-    rows = [json.loads(line) for line in (package / "translation-requests.jsonl").read_text().splitlines()]
+    rows = [json.loads(line) for line in (package / "translation-requests.jsonl").read_text(encoding="utf-8").splitlines()]
     result = []
     for row in rows:
         tokens = " ".join(extract_protected_tokens(row["sourceText"]))
@@ -84,21 +84,21 @@ def test_export_is_deterministic_anonymous_and_schema_valid(tmp_path):
         assert (first / name).read_bytes() == (second / name).read_bytes()
     assert (first / "translation-requests.csv").read_bytes().startswith(b"\xef\xbb\xbf")

-    request_schema = json.loads((ROOT / "schemas/research/portable-translation-request-v1.schema.json").read_text())
-    response_schema = json.loads((ROOT / "schemas/research/portable-translation-response-v1.schema.json").read_text())
-    manifest_schema = json.loads((ROOT / "schemas/research/portable-package-manifest-v1.schema.json").read_text())
+    request_schema = json.loads((ROOT / "schemas/research/portable-translation-request-v1.schema.json").read_text(encoding="utf-8"))
+    response_schema = json.loads((ROOT / "schemas/research/portable-translation-response-v1.schema.json").read_text(encoding="utf-8"))
+    manifest_schema = json.loads((ROOT / "schemas/research/portable-package-manifest-v1.schema.json").read_text(encoding="utf-8"))
     validate(manifest_a, manifest_schema)
-    public = [json.loads(line) for line in (first / "translation-requests.jsonl").read_text().splitlines()]
+    public = [json.loads(line) for line in (first / "translation-requests.jsonl").read_text(encoding="utf-8").splitlines()]
     assert len({row["requestId"] for row in public}) == 12
     for row in public:
         validate(row, request_schema)
         serialized = json.dumps(row)
         assert "sampleId" not in serialized and "ContentUid" not in serialized
         assert '"variant"' not in serialized and '"baseline"' not in serialized
-    internal = json.loads((first / "internal-request-map.json").read_text())
+    internal = json.loads((first / "internal-request-map.json").read_text(encoding="utf-8"))
     assert {(row["sampleId"], row["variant"]) for row in internal} == {
         (row["sampleId"], variant)
-        for row in [json.loads(line) for line in sample.read_text().splitlines()]
+        for row in [json.loads(line) for line in sample.read_text(encoding="utf-8").splitlines()]
         for variant in ("A", "B")
     }
     assert sum(not row["context"] for row in public) == 6
@@ -109,8 +109,8 @@ def test_export_is_deterministic_anonymous_and_schema_valid(tmp_path):
     assert audit["contentUidExposedExternally"] == 0
     assert audit["variantLabelsExposedExternally"] == 0
     assert audit["sampleIdExposedExternally"] == 0
-    assert json.loads((first / "package-audit.json").read_text()) == audit
-    templates = [json.loads(line) for line in (first / "response-template.jsonl").read_text().splitlines()]
+    assert json.loads((first / "package-audit.json").read_text(encoding="utf-8")) == audit
+    templates = [json.loads(line) for line in (first / "response-template.jsonl").read_text(encoding="utf-8").splitlines()]
     assert len(templates) == 12
     for row in templates:
         validate(row, response_schema)
@@ -136,7 +136,7 @@ def test_import_complete_jsonl_and_csv(tmp_path):
 def test_import_partial_empty_and_protected_corruption(tmp_path):
     package = _package(tmp_path)
     rows = _valid_responses(package)
-    public = [json.loads(line) for line in (package / "translation-requests.jsonl").read_text().splitlines()]
+    public = [json.loads(line) for line in (package / "translation-requests.jsonl").read_text(encoding="utf-8").splitlines()]
     protected_id = next(row["requestId"] for row in public if "{Damage}" in row["sourceText"])
     by_id = {row["requestId"]: row for row in rows}
     by_id[protected_id]["translatedText"] = "遺失保護 token"
@@ -148,7 +148,7 @@ def test_import_partial_empty_and_protected_corruption(tmp_path):
     report = import_responses(package, path, tmp_path / "partial-import")
     assert report["complete"] is False
     assert report["received"] == 2 and report["missing"] == 10 and report["invalid"] == 2
-    imported = [json.loads(line) for line in (tmp_path / "partial-import/imported-results.jsonl").read_text().splitlines()]
+    imported = [json.loads(line) for line in (tmp_path / "partial-import/imported-results.jsonl").read_text(encoding="utf-8").splitlines()]
     assert next(row for row in imported if row["requestId"] == protected_id)["errorCodes"] == ["PROTECTED_TOKEN_MISSING"]
     assert next(row for row in imported if row["requestId"] == another_id)["errorCodes"] == ["EMPTY_TRANSLATION"]
     assert sum(row["status"] == "missing" for row in imported) == 10
@@ -166,7 +166,7 @@ def test_import_rejects_duplicate_and_unknown_ids(tmp_path, kind):
     _write_responses(path, rows)
     with pytest.raises(PortableResponseError):
         import_responses(package, path, tmp_path / f"{kind}-import")
-    report = json.loads((tmp_path / f"{kind}-import/import-report.json").read_text())
+    report = json.loads((tmp_path / f"{kind}-import/import-report.json").read_text(encoding="utf-8"))
     assert report[kind] == 1


@@ -177,7 +177,7 @@ def test_blind_review_pairs_only_valid_ab_and_keeps_key_separate(tmp_path):
     import_dir = tmp_path / "import"
     import_responses(package, responses, import_dir)
     imported_path = import_dir / "imported-results.jsonl"
-    imported = [json.loads(line) for line in imported_path.read_text().splitlines()]
+    imported = [json.loads(line) for line in imported_path.read_text(encoding="utf-8").splitlines()]
     excluded_sample = imported[0]["sampleId"]
     imported[0]["status"] = "invalid"
     imported[0]["errorCodes"] = ["SYNTHETIC_INVALID"]
@@ -186,14 +186,14 @@ def test_blind_review_pairs_only_valid_ab_and_keeps_key_separate(tmp_path):
     review_dir = tmp_path / "review"
     summary = build_blind_review(package, imported_path, review_dir)
     assert summary["reviewablePairs"] == 5
-    blind = [json.loads(line) for line in (review_dir / "blind-review.jsonl").read_text().splitlines()]
+    blind = [json.loads(line) for line in (review_dir / "blind-review.jsonl").read_text(encoding="utf-8").splitlines()]
     assert excluded_sample not in {row["sampleId"] for row in blind}
     for row in blind:
         assert not ({"variant", "requestId", "context"} & row.keys())
         assert row["candidate1"] and row["candidate2"]
-    key = json.loads((review_dir / "blind-review-key.json").read_text())
+    key = json.loads((review_dir / "blind-review-key.json").read_text(encoding="utf-8"))
     assert len(key) == 5 and all(set((row["candidate1Variant"], row["candidate2Variant"])) == {"A", "B"} for row in key)
-    diagnostics = [json.loads(line) for line in (review_dir / "diagnostics-context.jsonl").read_text().splitlines()]
+    diagnostics = [json.loads(line) for line in (review_dir / "diagnostics-context.jsonl").read_text(encoding="utf-8").splitlines()]
     assert len(diagnostics) == 5 and all(row["context"] for row in diagnostics)


diff --git a/tests/test_dialogue_stage4r.py b/tests/test_dialogue_stage4r.py
index 3be2533..095b4ff 100644
--- a/tests/test_dialogue_stage4r.py
+++ b/tests/test_dialogue_stage4r.py
@@ -198,7 +198,7 @@ def test_finalize_barrier_release_failure_retracts_published_output(tmp_path,mon

 def replay_fixture(tmp_path):
     package=tmp_path/'replay';prepare_semantic_replay(package,request(context()),ruleset())
-    rows=[json.loads(line) for line in (package/'chatgpt-translation-requests.jsonl').read_text().splitlines()]
+    rows=[json.loads(line) for line in (package/'chatgpt-translation-requests.jsonl').read_text(encoding="utf-8").splitlines()]
     responses=tmp_path/'responses.jsonl';responses.write_bytes(b''.join(canonical_bytes({'requestId':r['requestId'],'translationText':'虛構譯文'})+b'\n' for r in rows))
     return package,rows,responses

@@ -211,7 +211,7 @@ def test_anonymous_formal_replay_and_blind_import_never_verdict(tmp_path):
     assert not any('condition'in r or 'variantId'in r for r in rows)
     result=import_semantic_replay_responses(package,responses,translation_source='external fictional source')
     assert result['safetyRegression']=='NOT_EVALUATED'
-    review=json.loads((package/'blind-review-ready.jsonl').read_text())
+    review=json.loads((package/'blind-review-ready.jsonl').read_text(encoding="utf-8"))
     assert set(review['translations'])=={'variant-1','variant-2'} and 'condition' not in review
     assert all(v is None for v in review['assessment'].values())

@@ -232,7 +232,7 @@ def test_replay_import_rejects_bad_outputs_without_blind_publication(tmp_path,ba

 def test_review_schema_source_translation_binding_and_limited_scope(tmp_path):
     package,_,responses=replay_fixture(tmp_path);import_semantic_replay_responses(package,responses,translation_source='fixture')
-    review=json.loads((package/'blind-review-ready.jsonl').read_text())
+    review=json.loads((package/'blind-review-ready.jsonl').read_text(encoding="utf-8"))
     review['assessment']={'sourceMeaningPreserved':{'variant-1':True,'variant-2':True},'semanticDriftVariant':'neither',
         'sourceAbsentInformation':{'variant-1':False,'variant-2':False},'alternativesAsSequence':{'variant-1':False,'variant-2':False},'reviewer':'fixture','notes':'known-risk case only'}
     completed=tmp_path/'completed.jsonl';completed.write_bytes(canonical_bytes(review)+b'\n')
@@ -243,7 +243,7 @@ def test_review_schema_source_translation_binding_and_limited_scope(tmp_path):

 def test_changed_original_blind_review_cannot_rebind_completed_review(tmp_path):
     package,_,responses=replay_fixture(tmp_path);import_semantic_replay_responses(package,responses,translation_source='fixture')
-    review=json.loads((package/'blind-review-ready.jsonl').read_text());review['targetSource']='changed source'
+    review=json.loads((package/'blind-review-ready.jsonl').read_text(encoding="utf-8"));review['targetSource']='changed source'
     (package/'blind-review-ready.jsonl').write_bytes(canonical_bytes(review)+b'\n')
     completed=tmp_path/'completed.jsonl';completed.write_bytes(canonical_bytes(review)+b'\n')
     with pytest.raises(ValueError,match='seal mismatch'):validate_semantic_replay_review(package,completed)
diff --git a/tests/test_e2e_project.py b/tests/test_e2e_project.py
index ffcb2cf..054f2fb 100644
--- a/tests/test_e2e_project.py
+++ b/tests/test_e2e_project.py
@@ -93,7 +93,7 @@ class E2EProjectConfigTests(unittest.TestCase):
             self.assertEqual(state["stages"]["config"]["status"], "completed")
             self.assertEqual(state["stages"]["scan"]["status"], "ready")
             self.assertEqual(state["projectConfigSha256"], config.sha256)
-            self.assertEqual(state_path(config), root / "workspace" / "e2e" / "workflow-state.json")
+            self.assertEqual(state_path(config), (root / "workspace" / "e2e" / "workflow-state.json").resolve(strict=False))

     def test_project_init_check_and_status_not_started(self) -> None:
         with tempfile.TemporaryDirectory() as tmp:
diff --git a/tests/test_production_prepare.py b/tests/test_production_prepare.py
index 071f4c2..8fb6641 100644
--- a/tests/test_production_prepare.py
+++ b/tests/test_production_prepare.py
@@ -323,9 +323,12 @@ class TestProductionPrepare(unittest.TestCase):
         shutil.move(output, relocated)
         binding = verify_production_workspace(relocated)
         self.assertEqual(binding.workspace, relocated.resolve())
-        self.assertEqual(binding.batch_plan, relocated / "batches" / "batch-plan.json")
-        self.assertEqual(binding.database, relocated / "execution.sqlite3")
-        self.assertEqual(binding.ruleset, relocated / "inputs" / "ruleset.json")
+        self.assertEqual(binding.batch_plan, (relocated / "batches" / "batch-plan.json").resolve(strict=True))
+        self.assertEqual(binding.database, (relocated / "execution.sqlite3").resolve(strict=True))
+        self.assertEqual(binding.ruleset, (relocated / "inputs" / "ruleset.json").resolve(strict=True))
+        for actual in (binding.batch_plan, binding.database, binding.ruleset):
+            self.assertTrue(actual.is_relative_to(binding.workspace))
+            self.assertTrue(actual.samefile(relocated / actual.relative_to(binding.workspace)))


 if __name__ == "__main__":
```

## 3. 原四失敗測試 / Encoding / Native 8.3 matrix

沿用 M7-P5 外部 observer plugin，執行同四個原 node IDs；只觀察／模擬 default read codec，不修改 validators 或 expectation。UTF-8 使用真實 -X utf8；cp1252 是 encoding=None 時的受控注入（本機 ACP cp950，-X utf8=0），没有改系统 locale。修復後這些已知 UTF-8 reads 皆 explicit，cp1252 wrapper 不再改其內容。

短 TEMP 使用真正 GetShortPathNameW 的 `.../RUNNER~1` alias，long/short samefile、File ID、resolve 已驗證，不是以 replace 拼造短路徑。32 個原測試執行全部 PASS：

| Python | 條件 | 原四 tests |
| --- | --- | --- |
| 3.11.9 | utf8-long | 4/4 PASS |
| 3.11.9 | cp1252-long | 4/4 PASS |
| 3.11.9 | utf8-short | 4/4 PASS |
| 3.11.9 | cp1252-short | 4/4 PASS |
| 3.12.10 | utf8-long | 4/4 PASS |
| 3.12.10 | cp1252-long | 4/4 PASS |
| 3.12.10 | utf8-short | 4/4 PASS |
| 3.12.10 | cp1252-short | 4/4 PASS |

Evidence：各 `311/312-*-observed/` 的 command/result、environment、pytest log/JSON/JUnit、raw input/output snapshots、semantic-checkpoints、path-proofs；M7-P5 的 RED traces 保留未覆寫。

## 4. Semantic / Workspace 正負防護

- 八組首次 valid review 在實際 runtime line 108：全部非 assessment fields exact；原 blind/request/assignment/template/source seals PASS，原 fingerprint穩定。沒有 normalize、修補 mojibake 或放寬 equality。
- 八組第二次呼叫仍為原 test 故意 changed translation，且正確拒絕；final completed 檔因此包含刻意的負向資料，first positive 原 bytes 已另存 checkpoint，沒有把 final file 誤當 positive。
- 外部 explicit UTF-8 probes 八組 × 五種：valid accepted（known-risk-case-only / 非 safety PASS）、changed source rejected、changed translation rejected、tampered original seal rejected、key order + ensure_ascii 變化 accepted。`semantic-analysis.json`、`input-integrity.json`。
- Workspace snapshot 真正移到外部 D 後 verification PASS；兩版各拒絕 relative traversal、absolute outside、ruleset byte-only tamper、missing batch plan。同 bytes 的 sibling file 也非 samefile。`311/312-guard-probes.json`。
- State parent 原／canonical path 同實體，short/long config SHA 相同；尚無 state file 時不虛構 File ID。Relocated batch plan/DB/ruleset 有 same File ID/SHA、resolved equality、root containment，正式來源／receipt／inventory checks 未改。

## 5. Targeted / Full available pytest

Targeted 13 modules 包含四修改檔、H0/HSE golden prompt/messages/request fingerprints、HD identity/add/change/remove/proof/guard、Stage 0 frozen contracts、Basic JSONL/XLSX、A1/A6/A8、Receipt/current workflow eligibility。正式 complete suite 未排除 HTTP demo：

| Python | Targeted | Full available |
| --- | --- | --- |
| 3.11.9 | 405 passed, 1 warning in 199.97s (0:03:19) | 1 failed, 1561 passed, 1 skipped, 1 warning in 751.22s (0:12:31) |
| 3.12.10 | 405 passed, 1 warning in 196.32s (0:03:16) | 1 failed, 1561 passed, 1 skipped, 1 warning in 753.03s (0:12:33) |

完整 commands、elapsed times、JUnit、failures/skips 分別保存在 `311/312-targeted.json/.xml/.txt` 與 `311/312-full.json/.xml/.txt`。如果唯一 failure 是 HTTP demo，其 DB attempts 的 WinError 10013 是 **BLOCKED (environment)**，不計 PASS。Host symlink privilege skip 亦是該 coverage **BLOCKED**；duplicate ZIP warning 為既有 deliberate negative fixture。其他 failure 將停止交付，不能以改 schema/CI/Production 繞過。

## 6. Wheel / sdist / Privacy / Fresh Install

只複製核對過的 421 個 C6 公開來源 + 四個當前 test edits 的 snapshot 建置，沒有 ignored workspace／測試輸出。最後本報告在測試後建立，因此不在該 build snapshot，不能將報告產生之後的工作樹誤稱已全部封裝。

3.11 正常建 wheel+sdist；解壓後由 3.12 重建 wheel+sdist。verify_contents / SHA inventory / privacy audit PASS：版本 1.4.0rc1、126 runtime resources、42 schemas、Basic receipt schema、五份公開 synthetic fixtures。兩個 wheel 的所有 entry bytes 完全相同，亦與 M7-P2 runtime baseline 相同（本次沒有 runtime 改動）；不同 archive SHA 源於封裝時間等 container metadata，不宣稱 archive byte deterministic。

| Artifact | Bytes | SHA256 |
| --- | --- | --- |
| `dist311/bg3loc-1.4.0rc1-py3-none-any.whl` | 447145 | `48bf80c8e93b7ceb44c1c174fbc5b6ceae738a4aa2dfbdb51325524a062c0108` |
| `dist311/bg3loc-1.4.0rc1.tar.gz` | 1059207 | `0b968f34fa65835c33d4812a2bb45ccd4aa443936f88eba609877a5a63a54d20` |
| `dist312/bg3loc-1.4.0rc1-py3-none-any.whl` | 447145 | `feb2cd45393ef967818635b8dd6b1438f10db8aad06bd2cce0df19ed00054edd` |
| `dist312/bg3loc-1.4.0rc1.tar.gz` | 1059258 | `c47c4af061f10b466c607d3d7d7cfaf534afe67c5498bcd8b2607d75a2b3cb17` |

`package-audit.json` / inventories 確認無真正 PAK/LOCA/SQLite/API keys/Divine/hidden assignments/proprietary data，entry path/case collision、PE/SQLite magic、credential-pattern audit PASS。

兩版 **全新隔離 uv venv** 由本次 wheel 安裝 runtime+[test]，全部使用公開 cache/wheelhouse，沒有系統安裝或發布。Package/producer stamp、Python -I CLI --version/help/workflow/research/production、Console exe --version 均 PASS。42 schemas 格式驗證 PASS，SchemaStore 39 loads PASS；三份 historical research BOM loads 仍 **BLOCKED**，沒有更動 BOM 或 reader。新 sdist 兩版各 collect 1,563 tests。

兩版 installed Basic JSONL/XLSX smoke 均 PASS：project init/check → prepare → synthetic 回填 → validate → rebuild → install **dry-run** → status；scope 3 fictional UID、source-only/blank/runtime tokens、3 non-LOCA SHA parity、原 synthetic packages 不變、無 backups/apply/rollback。Backend 只用公開 ZIP/XML，不冒稱 Native LSLib 或真實遊戲驗收。

M7-P2 fresh 3.12 DLL policy failure 在**本次 clean312 路徑未重現**（CLI/schema/Basic實際通過）；没有改 Windows policy，不將單次成功描述成系統 policy 已全面修復。初次 uv install 因默认 sandbox TEMP PE-resource 操作受阻，改為外部 writable TEMP後成功；cp312 offline cache 缺 PyYAML，以既有公開 wheelhouse補齊。外部 helper 曾以 packaging.py 命名，造成套件名稱 shadow；已在 evidence 目錄改名 package_audit_run.py 並重驗，沒有動受控程式。

本階段 full pytest 是 checkout source 的本機重跑；Fresh Install 是實際 installed runtime/CLI/Basic smoke 與 sdist collect，**沒有宣稱 fresh-venv full suite 或 Hosted CI 重跑通過**。

## 7. Git / SHA / 原始工作保護

| 允許測試檔 | C6/M7-P5 before SHA256 | M7-P6 after SHA256 |
| --- | --- | --- |
| `tests/test_b1_02_portable_translation.py` | `e2820785d71fe353ed6b8ebbc03d5c1f35a48d0a2678ef618a7d1560aff1bca1` | `6cd1aa4d2ff38d61e48b5578e6789d3c864621b49ac5f6138b286afcdcb8eb05` |
| `tests/test_dialogue_stage4r.py` | `39f41965f39327690bf1fffb930cb9656787912010e315530edcd5b9fca8565e` | `e671651a5956d77c8197729c078103e43d80f4993e4d4806fba61c551122a204` |
| `tests/test_e2e_project.py` | `141b5e21e088f95e2ce899d85fc039986b51e4d29bc6b532f8ba72034316bfc3` | `a10330ae7d238fedeaee663b7b23728c759b54865d584bd4e64f66be82f8272e` |
| `tests/test_production_prepare.py` | `c3514a271e67d1ca2da85046743a6b21f22cc4910aa4d7b31ee310f9b6b5973b` | `99cfa6ccf9edd6c2e4cd96808d428ab6dfbdc8ed651c8c01dd69e20990d21427` |

`source-protection.json` 最終驗證：C1–C6 Chain、HEAD/Tree/Branch不變、index 無 Stage；417 個其他 tracked files raw bytes不變，包括全部 Production/CI/frozen/schema/identity/receipt/guard。原始 dirty checkout 416 個公開 files、HEAD/Branch/status 原样。只有四個 modified tests，以及指定新報告 untracked；本次没有 Commit/Push/CI re-run/Merge/Tag/Release/PyPI 或真實遊戲修改。`git diff --check` PASS。

## 8. 未解驗收範圍與停止

四項已核准 test-only defects 的矩陣已修復；本機 HTTP／symlink／research BOM 的 BLOCKED coverage 仍列示。Hosted Windows/Ubuntu 3.11/3.12 修復後驗收 **NOT RUN / NOT VERIFIED**，須下一階段明確授權；M7-P5 Run 38191492778 是原 C6 的失敗證據，不是當前修復的 CI PASS。沒有任何超出四檔的程式修复。

**BG3Loc M7-P6 — WINDOWS TEST PORTABILITY READY FOR REVIEW**
