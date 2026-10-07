"""Local-only, provider-neutral 25-pair pilot preparation. Never sends requests."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from bg3loc.research.dialogue_policy import VERSION, render_research, speaker_relation
from bg3loc.research.structural_provenance import canonical_json, definition_fingerprint


def strata(context: dict, category: str) -> set[str]:
    pred,succ=context["predecessors"],context["successors"]
    pc,sc=len({x["nodeId"] for x in pred}),len({x["nodeId"] for x in succ})
    tags=set()
    if pc==1 and sc<=1: tags.add("linear_single_predecessor")
    if pc>1: tags.add("merge_multiple_predecessors")
    if sc>1: tags.add("multiple_successors")
    if context["targetType"]=="TagQuestion" or any(x["nodeType"]=="TagQuestion" for x in pred+succ): tags.add("choice_proxy")
    if any(speaker_relation(context["speaker"],x["speaker"])=="different_static_reference" for x in pred+succ): tags.add("speaker_change")
    if category=="bark": tags.add("bark")
    return tags


def prepare_pilot(output: Path, inventory: dict, sources: dict, contexts: dict, *, size: int = 25) -> dict:
    if not 1<=size<=25: raise ValueError("pilot must contain at most 25 pairs")
    eligible={u:c for u,c in contexts.items() if c["reason"]=="PRESENT"}
    rank=lambda u:definition_fingerprint({"samplingVersion":VERSION,"uid":u})
    ranked=sorted(eligible,key=rank); picked={}
    for tag,quota in (("linear_single_predecessor",5),("merge_multiple_predecessors",5),
                      ("multiple_successors",4),("choice_proxy",4),("speaker_change",4),("bark",3)):
        for uid in [u for u in ranked if u not in picked and tag in strata(eligible[u],inventory[u])][:min(quota,size-len(picked))]:
            picked[uid]=tag
    for uid in ranked:
        if len(picked)>=size: break
        if uid not in picked: picked[uid]="deterministic_fill"
    output.mkdir(parents=True,exist_ok=True)
    requests=[]; assignments=[]; review=[]
    for index,uid in enumerate(picked,1):
        context=eligible[uid];case=f"case-{index:03d}"
        flip=int(rank(uid)[0],16)%2
        for position in range(2):
            is_context=bool(position^flip); variant=f"variant-{position+1}"
            request_id=definition_fingerprint({"case":case,"variant":variant,"sample":rank(uid)})[:24]
            prompt=render_research(sources[uid],context if is_context else None)
            requests.append({"requestId":request_id,"caseId":case,"variantId":variant,
                "sourceLocale":"English","targetLocale":"ChineseTraditional",
                "system":prompt["system"],"data":prompt["data"]})
            assignments.append({"requestId":request_id,"caseId":case,"variantId":variant,
                                "uid":uid,"isContext":is_context,"policy":"A" if is_context else "baseline"})
        review.append({"caseId":case,"targetSource":sources[uid],
            "possiblePredecessors":[x["sourceText"] for x in context["predecessors"]],
            "possibleSuccessors":[x["sourceText"] for x in context["successors"]],
            "translations":{"variant-1":None,"variant-2":None},
            "assessment":{"worseVariant":None,"sourceAbsentInformation":None,"branchMisunderstanding":None,
                          "alternativesTreatedAsSequence":None,"speakerMisleading":None,"contextTranslatedIntoTarget":None,
                          "noObservableDifference":None}})
    for name,records in (("requests.jsonl",requests),("assignments-local-only.jsonl",assignments),("blind-review-template.jsonl",review)):
        (output/name).write_text("".join(canonical_json(r)+"\n" for r in records),encoding="utf-8")
    summary={"schemaVersion":VERSION,"sampleSize":len(picked),"requestCount":len(requests),"policy":"A",
             "strata":dict(Counter(picked.values())),"sampleFingerprint":definition_fingerprint(sorted(picked,key=rank)),
             "requestFingerprint":definition_fingerprint(requests),"translationSource":None,
             "translationsReceived":0,"safetyValidation":"PENDING","providerCalls":0}
    (output/"pilot-summary.json").write_text(canonical_json(summary)+"\n",encoding="utf-8")
    (output/"README.txt").write_text(
        "LOCAL ONLY: proprietary source payload. No requests have been sent.\n"
        "Give only requests.jsonl to an external translation source. Return requestId and translationText for every request.\n"
        "Keep assignments-local-only.jsonl private from the safety reviewer.\n"
        "The translator necessarily sees available context; condition names are concealed, not context presence.\n"
        "Populate the blind review template with the two anonymous outputs before safety review.\n"
        "No translation quality/safety verdict exists until outputs and review are received.\n",encoding="utf-8")
    return summary


def import_responses(package: Path, response_path: Path, translation_source: str) -> dict:
    """Validate complete external outputs and create a condition-blinded review.

    Translation source is a descriptive provenance label, never a provider call.
    No safety judgement is inferred from receiving outputs.
    """
    from bg3loc.research.dialogue_policy import rows
    if not translation_source.strip(): raise ValueError("translation source label required")
    request_rows=list(rows(package/'requests.jsonl'))
    import json
    manifest=json.loads((package/'pilot-summary.json').read_text(encoding='utf-8'))
    requests={r['requestId']:r for r in request_rows}
    if (definition_fingerprint(request_rows)!=manifest['requestFingerprint']
        or len(requests)!=len(request_rows) or len(requests)!=manifest['requestCount']
        or len(requests)!=2*manifest['sampleSize']):
        raise ValueError("pilot request seal or inventory mismatch")
    outputs={}
    for row in rows(response_path):
        if set(row)!={'requestId','translationText'} or row['requestId'] not in requests:
            raise ValueError("unexpected external response")
        if row['requestId'] in outputs: raise ValueError("duplicate external response")
        if not isinstance(row['translationText'],str) or not row['translationText'].strip():
            raise ValueError("nonempty translationText required")
        outputs[row['requestId']]=row['translationText']
    if outputs.keys()!=requests.keys(): raise ValueError("external response inventory incomplete")
    review={r['caseId']:r for r in rows(package/'blind-review-template.jsonl')}
    cases={r['caseId'] for r in request_rows}
    if set(review)!=cases or any({r['variantId'] for r in request_rows if r['caseId']==case}!= {'variant-1','variant-2'} for case in cases):
        raise ValueError("pilot case bindings mismatch")
    for rid,text in outputs.items():
        request=requests[rid]
        if request['data']['targetSource']!=review[request['caseId']]['targetSource']:
            raise ValueError("pilot review target binding mismatch")
        review[request['caseId']]['translations'][request['variantId']]=text
    (package/'blind-review-ready.jsonl').write_text(
        ''.join(canonical_json(review[k])+'\n' for k in sorted(review)),encoding='utf-8')
    result={'schemaVersion':VERSION,'translationSource':translation_source,'translationsReceived':len(outputs),
            'responseFingerprint':definition_fingerprint(dict(sorted(outputs.items()))),
            'safetyValidation':'PENDING REVIEW','providerCalls':0}
    (package/'response-summary.json').write_text(canonical_json(result)+'\n',encoding='utf-8')
    return result
