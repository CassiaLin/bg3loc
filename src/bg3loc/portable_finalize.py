"""1.3 finalize/rebuild from sealed roles under a SQLite writer barrier."""
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import time
import hashlib

from bg3loc.dialogue_context import canonical_bytes, fingerprint, strict_json_loads
from bg3loc.dialogue_execution_contract import validate_stage2_workspace
from bg3loc.portable_assets import verify_finalize_assets, active_backend, safe_file, reject
from bg3loc.production_workspace import sha256_file
from bg3loc.production_completion import build_production_completion_view
from bg3loc.rebuilder import merge_records, write_loca_xml, parse_loca_xml, validate_rebuilt_records


def logical_snapshot(conn,manifest):
    columns={"content_state":"content_uid,status,input_hash,output_hash,last_attempt_id",
             "qa_results":"content_uid,route,qa_rule_set_version,qa_input_hash,output_hash,execution_input_hash",
             "metadata":"key,value"}
    result={"material":manifest["batching"]["batchMaterialsFingerprint"],"plan":manifest["batching"]["batchPlanFingerprint"],
            "assets":manifest["finalizeAssets"]["assetFingerprint"]}
    for table,selection in columns.items():
        result[table]=[list(row) for row in conn.execute(f"SELECT {selection} FROM {table} ORDER BY 1")]
    selected={}
    for row in conn.execute("""SELECT r.resolution_id,r.content_uid,r.decision,r.qa_rule_set_version,r.qa_input_hash,r.base_output_hash,r.resolved_output_hash,r.execution_input_hash
        FROM qa_review_resolutions r JOIN content_state c USING(content_uid) JOIN qa_results q USING(content_uid)
        WHERE q.route='REVIEW' AND r.qa_input_hash=q.qa_input_hash AND r.qa_rule_set_version=q.qa_rule_set_version
        AND r.execution_input_hash=c.input_hash AND r.resolved_output_hash=c.output_hash
        AND (r.decision='REVISE' OR r.decision='ACCEPT' AND r.base_output_hash=c.output_hash) ORDER BY r.resolution_id"""):
        selected[row[1]]=list(row)
    result["selectedReviews"]=[selected[k] for k in sorted(selected)]
    return fingerprint(result)


def finalize_portable_workspace(workspace, output, *, backend=None, container="auto", observer=None):
    from bg3loc.production_finalize import _require_completion_ready
    backend=active_backend(backend);root=Path(workspace).resolve();output=Path(output).resolve()
    if output.exists() or output.is_relative_to(root) or root.is_relative_to(output): reject("PATH_INVALID")
    if container not in {"auto","loca-only","repack"}: reject("REPACK_CAPABILITY_MISSING")
    binding=validate_stage2_workspace(root)
    manifest_path=root/"production-manifest.json";manifest_seal=sha256_file(manifest_path)
    manifest=strict_json_loads(manifest_path.read_bytes())
    assets=verify_finalize_assets(root,manifest["finalizeAssets"],backend=backend)
    from bg3loc.portable_assets import lexical_path
    if len(lexical_path(manifest["targetLocale"]+".loca"))!=1: reject("PATH_INVALID")
    output.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(binding.database,timeout=5)) as conn:
        started=time.perf_counter();conn.execute("BEGIN IMMEDIATE")
        published=False
        try:
            conn.row_factory=sqlite3.Row
            if conn.execute("SELECT 1 FROM content_state WHERE status='running' OR lease_owner IS NOT NULL LIMIT 1").fetchone(): reject("FINALIZE_SNAPSHOT_CHANGED")
            completion=build_production_completion_view(binding.database,binding.batch_plan,stage3_validation_only=True,_connection=conn)
            _require_completion_ready(completion)
            before=logical_snapshot(conn,manifest)
            if observer is not None: observer(conn)
            state={uid:(text,output_hash) for uid,text,output_hash in conn.execute("SELECT content_uid,translated_text,output_hash FROM content_state ORDER BY content_uid")}
            _validate_output_bytes(state)
            accepted={}
            for row in completion.rows:
                uid=row.content_uid
                if uid not in assets.source_versions and uid not in assets.target_versions: reject("ASSET_SEMANTIC_MISMATCH")
                accepted[uid]={"contentUid":uid,"localeId":manifest["targetLocale"],"version":assets.target_versions.get(uid,assets.source_versions.get(uid)),"text":state[uid][0]}
            accepted=dict(sorted(accepted.items()))
            source={uid:{"version":version} for uid,version in assets.source_versions.items()}
            baseline=list(assets.baseline);merged,changed,new=merge_records(baseline,source,accepted)
            # LSLib filters files beneath dot-prefixed staging ancestors.
            # Keep sibling staging atomic, while letting it enumerate payloads.
            with tempfile.TemporaryDirectory(prefix="portable-finalize-",dir=output.parent) as temporary:
                staging=Path(temporary)/"result";staging.mkdir()
                xml=staging/"merged.xml";loca=staging/(manifest["targetLocale"]+".loca");reread=staging/"roundtrip.xml"
                write_loca_xml(xml,merged);backend.convert_loca(xml,loca);backend.convert_loca(loca,reread)
                validate_rebuilt_records(baseline,merged,parse_loca_xml(reread),accepted,changed)
                artifacts=[{"type":"loca","path":loca.name,"sha256":sha256_file(loca)}]
                package=assets.bundle["targetPackage"]
                repack=container=="repack" or container=="auto" and package["kind"]=="pak"
                if repack:
                    if package["kind"]!="pak": reject("REPACK_CAPABILITY_MISSING")
                    entries=staging/"entries";entries.mkdir()
                    for entry in package["entries"]:
                        target=entries/entry["entryPath"];target.parent.mkdir(parents=True,exist_ok=True)
                        import shutil
                        shutil.copyfile(safe_file(root,entry["snapshot"]["path"]),target)
                    import shutil
                    shutil.copyfile(loca,entries/package["locaEntry"])
                    pak=staging/package["originalPackageName"];backend.create_package(entries,pak)
                    listed=backend.list_archive(pak)
                    if {e.path for e in listed}!={e["entryPath"] for e in package["entries"]}: reject("REBUILD_VALIDATION_FAILED")
                    verification=staging/"repack-verification";backend.extract_package(pak,verification)
                    from bg3loc.portable_assets import collision_free
                    collision_free([e.path for e in listed])
                    if {p.relative_to(verification).as_posix() for p in verification.rglob('*') if p.is_file()}!={e.path for e in listed}: reject("REBUILD_VALIDATION_FAILED")
                    for entry in package["entries"]:
                        expected=sha256_file(loca) if entry["entryPath"]==package["locaEntry"] else entry["snapshot"]["sha256"]
                        if sha256_file(safe_file(verification,entry["entryPath"]))!=expected: reject("REBUILD_VALIDATION_FAILED")
                    artifacts.append({"type":"pak","path":pak.name,"sha256":sha256_file(pak)})
                verify_finalize_assets(root,manifest["finalizeAssets"],backend=backend)
                validate_stage2_workspace(root,_connection=conn)
                current_state={uid:(text,output_hash) for uid,text,output_hash in conn.execute("SELECT content_uid,translated_text,output_hash FROM content_state ORDER BY content_uid")}
                _validate_output_bytes(current_state)
                if current_state!=state:reject("FINALIZE_SNAPSHOT_CHANGED")
                if sha256_file(manifest_path)!=manifest_seal or logical_snapshot(conn,manifest)!=before: reject("FINALIZE_SNAPSHOT_CHANGED")
                report={"schemaVersion":"1.3","sourceLocale":manifest["sourceLocale"],"targetLocale":manifest["targetLocale"],
                        "snapshotFingerprint":before,"assetFingerprint":assets.fingerprint,"mergeReadyCount":len(accepted),
                        "newSourceOnlyCount":len(new),"changedCount":len(changed),"semanticRoundTrip":True,"nonLocaPayloadParity":True if repack else None,
                        "writerBarrierSeconds":time.perf_counter()-started,"artifacts":artifacts}
                (staging/"finalize-manifest.json").write_bytes(canonical_bytes(report)+b"\n")
                staging.rename(output)
                published=True
            conn.commit()
            return report
        except BaseException:
            try:
                conn.rollback()
            finally:
                # This invocation created this validated, previously absent
                # output directory. A barrier-release failure must retract it.
                if published:
                    import shutil
                    shutil.rmtree(output)
            raise


def _validate_output_bytes(state):
    """Bind actual accepted bytes without changing the frozen logical hash."""
    for text,output_hash in state.values():
        if type(text) is not str or hashlib.sha256(text.encode('utf-8')).hexdigest()!=output_hash:
            reject("FINALIZE_SNAPSHOT_CHANGED")
