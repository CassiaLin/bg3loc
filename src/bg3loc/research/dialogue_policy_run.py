"""Reproducible research evaluation and optional local safety package."""
from pathlib import Path
import json
from hashlib import sha256

from bg3loc.research.dialogue_policy import (
    PolicyGraph, evaluate, load_inventory, load_sources, verified_foundation,
)
from bg3loc.research.structural_provenance import canonical_json, definition_fingerprint


def file_hash(path: Path) -> str:
    digest=sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): digest.update(chunk)
    return digest.hexdigest()


def run_evaluation(evidence: Path, source: Path, plan: Path, output: Path, *, pilot: bool = False) -> dict:
    foundation=json.loads((evidence/'dialogue-summary.json').read_text(encoding='utf-8'))
    graph=PolicyGraph(verified_foundation(evidence));sources=load_sources(source);inventory=load_inventory(plan,sources)
    report,contexts=evaluate(graph,inventory,sources)
    report['inputs']={'phase1SemanticFingerprints':foundation['ledgerSemanticFingerprints'],
        'corpus':foundation.get('corpus',{}),'englishSnapshotSHA256':file_hash(source),
        'inventoryFingerprint':definition_fingerprint(dict(sorted(inventory.items()))),'batchPlanSHA256':file_hash(plan)}
    report['edgeVerdicts']={'child':'DIRECT potential relation; conditions unevaluated',
        'jumptarget':'UNKNOWN transfer semantics; excluded','SourceNode':'reference reuse; unsafe as temporal flow; excluded',
        'NestedDialogNodeUUID':'UNKNOWN external scope; excluded'}
    report['recommendation']='A' if report['policies']['A']['withContext'] else 'NONE'
    report['verdicts']={'A':'YES for production evaluation; translation safety pending',
        'B':'CONDITIONAL graph reachability; not recommended before control semantics validation',
        'C1':'conditional static-reference relation; low demonstrated semantic value',
        'C2':'static ID available; no demonstrated value justifying ID exposure/overhead'}
    report['status']={'policyEvaluation':'STRUCTURALLY READY','safetyValidation':'PENDING','productionIntegration':'NOT STARTED'}
    if report['recommendation']=='NONE':
        report['status']={'policyEvaluation':'NOT ACCEPTED','safetyValidation':'NOT RUN','productionIntegration':'BLOCKED'}
    output.mkdir(parents=True,exist_ok=True)
    if pilot and report['recommendation']!='NONE':
        from bg3loc.research.dialogue_pilot import prepare_pilot
        report['pilot']=prepare_pilot(output/'safety-pilot',inventory,sources,contexts)
    (output/'policy-evaluation-summary.json').write_text(canonical_json(report)+'\n',encoding='utf-8')
    return report
