"""Explicit in-memory fixture harness. No provider/HTTP implementation invoked."""
from dataclasses import dataclass
from pathlib import Path
from contextlib import closing
from datetime import datetime, timedelta, timezone

from bg3loc.dialogue_context import fingerprint
from bg3loc.dialogue_execution_contract import validate_stage2_workspace
from bg3loc.portable_assets import verify_finalize_assets
from bg3loc.execution_state import TranslationExecutionStore, ClaimedAttempt
from bg3loc.translation_request import BatchMaterialResolver
from bg3loc.translation_identity import TranslationInputParameters
from bg3loc.translation_send import prepare_translation_send
from bg3loc.ruleset_io import load_ruleset
from bg3loc.commands.translation_qa import run_qa
from bg3loc.qa_state import TranslationQaStore
from bg3loc.qa import QA_RULESET_VERSION, QaInput, evaluate_translation
from bg3loc.protected_syntax import extract_protected_tokens
from bg3loc.production_review import ProductionReviewStore


@dataclass(frozen=True,slots=True)
class OfflineOutcome:
    text: str | None = None
    error_code: str | None = None


def run_offline_integration(workspace, outcomes, *, human_decisions=None, backend=None):
    """Static outcome mappings only. Human fixtures are never safety verdicts."""
    from argparse import Namespace
    from bg3loc.dialogue_context import strict_json_loads
    root=Path(workspace).resolve();binding=validate_stage2_workspace(root)
    manifest=strict_json_loads((root/"production-manifest.json").read_bytes())
    verify_finalize_assets(root,manifest["finalizeAssets"],backend=backend)
    rules=load_ruleset(binding.ruleset);store=TranslationExecutionStore(binding.database)
    resolver=BatchMaterialResolver(binding.batch_plan,input_parameters=TranslationInputParameters(rules.version,rules.fingerprint(),rules.source_locale,rules.target_locale),stage2_validation_only=True)
    qa=TranslationQaStore(binding.database);qa.initialize();review=ProductionReviewStore(binding.database);review.initialize()
    sends=0
    for uid,sequence in sorted(outcomes.items()):
        if type(sequence) not in {list,tuple} or any(type(v) is not OfflineOutcome for v in sequence): raise ValueError("static offline outcomes required")
        for outcome in sequence:
            now=datetime.now(timezone.utc);stamp=now.isoformat();expiry=(now+timedelta(minutes=5)).isoformat()
            state=store.get_state(uid)
            if state is None or state["status"] not in {"pending","invalidated","failed-retryable"}: raise ValueError("offline item is not executable")
            with closing(store.connect()) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("INSERT OR IGNORE INTO runs(run_id,batch_plan_fingerprint,provider,model,prompt_version,execution_config_hash,started_at,status) VALUES('offline-integration',?,'offline-fixture','static-fixture',?,?,?,'running')",
                    (manifest["batching"]["batchPlanFingerprint"],rules.version,fingerprint(manifest["execution"]["contextContract"]),stamp))
                number=int(state["attempt_count"])+1
                cursor=conn.execute("INSERT INTO attempts(run_id,content_uid,batch_id,attempt_number,provider,model,started_at,outcome,input_hash) VALUES('offline-integration',?,?,?,'offline-fixture','static-fixture',?,'running',?)",(uid,state["batch_id"],number,stamp,state["input_hash"]))
                attempt=cursor.lastrowid
                conn.execute("UPDATE content_state SET status='running',attempt_count=?,last_attempt_id=?,lease_owner='offline-owner',lease_expires_at=? WHERE content_uid=?",(number,attempt,expiry,uid));conn.commit()
            request=resolver.resolve(ClaimedAttempt(attempt,'offline-integration',uid,state["batch_id"],number,state["input_hash"],'offline-owner',expiry))
            prepared=prepare_translation_send(request,rules);p=prepared.provenance
            store.record_prompt_provenance(attempt_id=attempt,worker_id='offline-owner',input_hash=p.input_hash,context_fingerprint=p.context_fingerprint,
                dialogue_context_fingerprint=p.dialogue_context_fingerprint,effective_prompt_hash=p.effective_prompt_hash,chat_messages_fingerprint=p.chat_messages_fingerprint,
                prompt_renderer_version=p.prompt_renderer_version,sent_at=stamp,_sealed_snapshot=resolver._sealed_snapshot)
            sends+=1
            if outcome.error_code is not None:
                store.complete_failure(attempt_id=attempt,worker_id='offline-owner',error_code='OFFLINE_TRANSPORT_FAILURE',error_message='Offline fixture failure',retryable=True,max_attempts=10,finished_at=stamp)
                continue
            if type(outcome.text) is not str: raise ValueError("offline output text required")
            from hashlib import sha256
            store.complete_success(attempt_id=attempt,worker_id='offline-owner',translated_text=outcome.text,output_hash=sha256(outcome.text.encode('utf-8')).hexdigest(),finished_at=stamp,stage3_validation_only=True,_sealed_snapshot=resolver._sealed_snapshot)
            run_qa(Namespace(db=binding.database,batch_plan=binding.batch_plan,max_items=None,stage3_validation_only=True))
            result=qa.get_result(uid,current_rule_set_version=QA_RULESET_VERSION)
            if result.route=='RETRY':
                technical=evaluate_translation(QaInput(uid,request.source_text,outcome.text,request.primary_category,tuple(extract_protected_tokens(request.source_text))))
                qa.handoff_retry(technical,max_attempts=10,rejected_at=stamp,expected_input_hash=result.execution_input_hash,expected_output_hash=result.output_hash)
            elif result.route=='REVIEW' and human_decisions and uid in human_decisions:
                decision,revised=human_decisions[uid]
                review.resolve(content_uid=uid,decision=decision,reviewer='offline-human-fixture',note='synthetic workflow, not semantic replay',resolved_at=stamp,
                    revised_text=revised,stage3_validation_only=True,expected_execution_input_hash=result.execution_input_hash,expected_output_hash=result.output_hash,
                    expected_qa_input_hash=result.qa_input_hash,expected_qa_rule_set_version=result.qa_rule_set_version)
    resolver.close()
    return {"offlineSends":sends,"productionProviderCalls":0,"activation":False}
