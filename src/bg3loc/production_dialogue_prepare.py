"""Fresh, atomic 1.3 prepare. Stage 5 activation is deliberately not provided."""
from dataclasses import replace
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile

from bg3loc.dialogue_context import canonical_bytes, fingerprint, strict_json_loads, dialogue_context_from_material
from bg3loc.dialogue_materialization import DialogueEvidenceAdapter, materialize_inventory
from bg3loc.dialogue_stage_prepare import load_prepared_inventory
from bg3loc.dialogue_execution_contract import execution_context_contract_v2, validate_stage2_workspace
from bg3loc.portable_assets import create_finalize_assets, normalized_records, records_map, reject, active_backend
from bg3loc.production_workspace import sha256_file, batch_materials_fingerprint, execution_inventory_fingerprint
from bg3loc.production_context import context_from_material
from bg3loc.execution_state import TranslationExecutionStore, ExecutionItem
from bg3loc.ruleset_io import load_ruleset
from bg3loc.translation_identity import TranslationInputParameters, translation_input_hash
from bg3loc.rebuilder import parse_loca_xml


def input_path(raw, anchor):
    if type(raw) is not str or not raw: reject("PORTABLE_ASSETS_INCOMPLETE")
    path=Path(raw)
    if not path.is_absolute(): path=anchor/path
    if not path.is_file(): reject("PORTABLE_ASSETS_INCOMPLETE")
    return path.resolve()


def attest(request,extract,evidence):
    if request.source_scan is None or request.research_summary is None: reject("PORTABLE_ASSETS_INCOMPLETE")
    scan=strict_json_loads(request.source_scan.read_bytes());research=strict_json_loads(request.research_summary.read_bytes())
    corpus=evidence.get("corpus");game=scan.get("game",{})
    if type(corpus) is not dict or not research.get("complete"): reject("PORTABLE_ASSETS_INCOMPLETE")
    expected={"appId":"1086940","buildId":str(research.get("buildId") or ""),"gameVersion":str(research.get("gameVersion") or "")}
    if (not expected["buildId"] or not expected["gameVersion"] or str(research.get("appId"))!="1086940"
            or {k:str(corpus.get(k) or "") for k in expected}!=expected or str(game.get("appId"))!="1086940"
            or str(game.get("buildId") or "")!=expected["buildId"]
            or (game.get("gameVersion") is not None and str(game["gameVersion"])!=expected["gameVersion"])):
        reject("ASSET_SEMANTIC_MISMATCH")
    recorded=input_path(extract.get("scanManifest"),request.extract_manifest.parent)
    if sha256_file(recorded)!=sha256_file(request.source_scan): reject("ASSET_SEMANTIC_MISMATCH")
    return expected


def prepare_dialogue_workspace(request, *, archive_backend=None):
    from bg3loc.production_orchestration import prepare_production_workspace
    output=request.output_dir.resolve()
    if output.exists(): reject("PORTABLE_ASSETS_INCOMPLETE")
    extract=strict_json_loads(request.extract_manifest.read_bytes())
    summary=strict_json_loads((request.dialogue_evidence/"dialogue-summary.json").read_bytes())
    corpus=attest(request,extract,summary)
    if extract.get("sourceLocale")!="English": reject("ASSET_SEMANTIC_MISMATCH")
    backend=active_backend(archive_backend)
    output.parent.mkdir(parents=True,exist_ok=True)
    locales={row["localeId"]:row for row in extract["locales"]}
    if len(locales)!=len(extract["locales"]) or extract["targetLocale"] not in locales: reject("ASSET_SEMANTIC_MISMATCH")
    target=locales[extract["targetLocale"]];source=locales["English"];anchor=request.extract_manifest.parent
    source_xml=input_path(source["sourceXml"],anchor)
    if records_map(parse_loca_xml(source_xml))!=normalized_records(request.source,"English"): reject("ASSET_SEMANTIC_MISMATCH")
    source_loca=input_path(source["sourceLoca"],anchor);source_package=input_path(source["packageFile"],anchor)
    with tempfile.TemporaryDirectory(prefix=".source-attest-",dir=request.output_dir.parent) as temp:
        check=Path(temp)/"source.xml";backend.convert_loca(source_loca,check)
        if records_map(parse_loca_xml(check))!=records_map(parse_loca_xml(source_xml)): reject("ASSET_SEMANTIC_MISMATCH")
        extracted=Path(temp)/"package-source.loca"
        package_seal=sha256_file(source_package)
        if source_package.suffix.casefold()==".pak": backend.extract_single_file(source_package,source["locaEntry"],extracted)
        else:
            import shutil
            shutil.copyfile(source_package,extracted)
        if sha256_file(source_package)!=package_seal or sha256_file(extracted)!=sha256_file(source_loca): reject("ASSET_HASH_MISMATCH")
    paths={"target_snapshot":input_path(target["normalized"],anchor),"target_xml":input_path(target["sourceXml"],anchor),
           "target_loca":input_path(target["sourceLoca"],anchor),"target_package":input_path(target["packageFile"],anchor)}
    inputs=[request.extract_manifest,request.source,request.research_mappings,request.ruleset,request.source_scan,request.research_summary,source_xml,source_loca,source_package,
        *(request.dialogue_evidence/f"dialogue-{f}.jsonl" for f in ("dialogue","node","occurrence","edge","targetEvidence")),
        request.dialogue_evidence/"dialogue-summary.json",*paths.values()]
    seals={path:sha256_file(path) for path in inputs}
    adapter=DialogueEvidenceAdapter.from_workspace(request.dialogue_evidence,request.source)
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".dialogue-prepare-",dir=output.parent) as temporary:
        staging=Path(temporary)/"workspace"
        base=prepare_production_workspace(replace(request,output_dir=staging,dialogue_evidence=None))
        plan=staging/"batches/batch-plan.json"
        inventory,_=load_prepared_inventory(plan,adapter.sources)
        results,material_summary=materialize_inventory(adapter,inventory)
        plan_data=strict_json_loads(plan.read_bytes())
        # Strip prepare-only physical input references; material paths are local.
        for key in ("classificationLedger","sourceInput","storyLedger","uiSkillUniverse","researchMappings"):
            plan_data.pop(key,None)
        items=[];rules=load_ruleset(staging/"inputs/ruleset.json")
        params=TranslationInputParameters(rules.version,rules.fingerprint(),rules.source_locale,rules.target_locale)
        for batch in plan_data["batches"]:
            path=staging/"batches/materials"/(batch["batchId"]+".jsonl")
            pending=[]
            for line in path.read_text(encoding="utf-8").splitlines():
                row=strict_json_loads(line);uid=row["contentUid"];context=results[uid].context
                if context is not None:
                    if "sameEntityContext" in row: reject("ASSET_SEMANTIC_MISMATCH")
                    row["dialogueContext"]=context.to_dict()
                dialogue_context_from_material(row)
                items.append(ExecutionItem(uid,batch["batchId"],translation_input_hash(content_uid=uid,source_text=row["sourceText"],category=row["primaryCategory"],
                    protected_syntax=None,parameters=params,context=context_from_material(row),dialogue_context=context)))
                pending.append(canonical_bytes(row)+b"\n")
            path.write_bytes(b"".join(pending));batch["materialPath"]=f"materials/{batch['batchId']}.jsonl"
        plan.write_bytes(canonical_bytes(plan_data)+b"\n")
        summary_path=staging/"dialogue-context-materialization-summary.json";summary_path.write_bytes(canonical_bytes(material_summary)+b"\n")
        assets=create_finalize_assets(staging,source_snapshot=request.source,source_locale="English",target_locale=extract["targetLocale"],
            origin_extract_sha256=seals[request.extract_manifest],loca_entry=target["locaEntry"],backend=backend,**paths)
        # The legacy seed was created only inside this new temporary prepare.
        for suffix in ("","-wal","-shm"):
            file=staging/("execution.sqlite3"+suffix)
            if not file.resolve().is_relative_to(staging.resolve()): reject("PATH_ESCAPE_OR_LINK")
            if file.exists(): file.unlink()
        db=TranslationExecutionStore(staging/"execution.sqlite3");db.initialize(schema_version="1.3")
        same=base.get("sameEntityContext")
        contract=execution_context_contract_v2(material_summary["dialogueContextMaterialFingerprint"],same_entity_material_fingerprint=None if same is None else same["sameEntityContextMaterialFingerprint"])
        db.seed_items(items,updated_at="prepare:1.3")
        db.set_metadata({"batchPlanFingerprint":plan_data["batchPlanFingerprint"],"rulesetFingerprint":rules.fingerprint(),"promptVersion":rules.version,
            "sourceLocale":rules.source_locale,"targetLocale":rules.target_locale,"executionContextContractVersion":"production-context-contract/2",
            "executionContextContractFingerprint":contract["contextContractFingerprint"],"dialogueContextMaterialFingerprint":material_summary["dialogueContextMaterialFingerprint"]})
        base["schemaVersion"]="1.3";base["finalizeAssets"]=assets
        for name,entry in base["inputs"].items():
            if name=="ruleset": continue
            original=Path(entry.pop("path"))
            if original.suffix==".json": entry["semanticFingerprint"]=fingerprint(strict_json_loads(original.read_bytes()))
            elif original.suffix==".jsonl": entry["semanticFingerprint"]=fingerprint(sorted(fingerprint(strict_json_loads(line)) for line in original.read_text(encoding="utf-8-sig").splitlines()))
            else: entry["semanticFingerprint"]=fingerprint({"sha256":entry["sha256"]})
        base["inputs"]["source"]["semanticFingerprint"]=adapter.input_digests["source"]
        base["inputs"]["dialogueEvidence"]={f:{"sha256":seals[request.dialogue_evidence/f"dialogue-{f}.jsonl"],"semanticFingerprint":adapter.input_digests[f]}
                                              for f in ("dialogue","node","occurrence","edge")}
        base["corpus"]={**corpus,"sourceEvidenceBindingFingerprint":fingerprint({"sourceLocale":"English","sourceNormalizedSha256":base["inputs"]["source"]["sha256"],
            "originExtractManifestSha256":base["inputs"]["extractManifest"]["sha256"],"dialogueEvidenceFileSha256s":{f:v["sha256"] for f,v in base["inputs"]["dialogueEvidence"].items()}})}
        base["dialogueContext"]={"schemaVersion":"dialogue-context/1","policyVersion":"b1-03-policy-a/1","orderingVersion":"dialogue-node-uid-order/1",
            "budgetContract":{"version":"dialogue-budget/1","countingVersion":"unicode-codepoints/1","maxSourceCodepoints":2000},
            "summaryPath":summary_path.name,"summarySha256":sha256_file(summary_path),"summaryFingerprint":material_summary["summaryFingerprint"],
            "withContext":material_summary["withContext"],"dialogueContextMaterialFingerprint":material_summary["dialogueContextMaterialFingerprint"],
            "inputDigests":material_summary["inputDigests"],"adapterVersion":"dialogue-public-evidence-adapter/1","builderVersion":"dialogue-context-builder/1"}
        base["batching"]["batchPlanSha256"]=sha256_file(plan);base["batching"]["batchMaterialsFingerprint"]=batch_materials_fingerprint(plan)
        base["execution"].update(databaseSchemaVersion="1.3",contextContract=contract,inventoryFingerprint=execution_inventory_fingerprint(db.path))
        (staging/"production-manifest.json").write_bytes(canonical_bytes(base)+b"\n")
        validate_stage2_workspace(staging)
        if any(sha256_file(p)!=seal for p,seal in seals.items()): reject("ASSET_HASH_MISMATCH")
        # No live connection or WAL dependency crosses the atomic directory rename.
        with closing(sqlite3.connect(db.path)) as conn: conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        staging.rename(output)
    return base
