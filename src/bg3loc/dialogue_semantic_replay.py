"""Small local-only external replay packages; no provider, no automatic verdict."""
from pathlib import Path
from dataclasses import replace
import secrets

from bg3loc.dialogue_context import canonical_bytes, fingerprint, strict_json_loads
from bg3loc.chat_prompt import render_chat_messages
from bg3loc.prompt_assembly import assemble_translation_prompt
from bg3loc.dialogue_prompt import project_dialogue_context, DIALOGUE_CONTEXT_SAFETY_INSTRUCTIONS
from bg3loc.translation_identity import TranslationInputParameters, translation_input_hash
from bg3loc.protected_syntax import extract_protected_tokens, validate_protected_syntax
from bg3loc.research.dialogue_pilot import _markup_lexemes


def _rows(path):
    result=[]
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        row=strict_json_loads(line)
        if type(row) is not dict:raise ValueError('replay object required')
        result.append(row)
    return result


def prepare_semantic_replay(output, request, ruleset, *, case_id='case-006'):
    """Uses the formal renderer twice; anonymous conditions remain local-only."""
    output=Path(output)
    if output.exists() or request.dialogue_context is None:raise ValueError('fresh replay package and dialogue context required')
    params=TranslationInputParameters(ruleset.version,ruleset.fingerprint(),ruleset.source_locale,ruleset.target_locale)
    h0=translation_input_hash(content_uid=request.content_uid,source_text=request.source_text,category=request.primary_category,protected_syntax=None,parameters=params)
    baseline=replace(request,dialogue_context=None,input_hash=h0)
    targets=[('baseline',baseline),('grouped',request)]
    if secrets.randbelow(2):targets.reverse()
    requests=[];assignments=[]
    variants=['variant-1','variant-2'];secrets.SystemRandom().shuffle(variants)
    for (condition,req),variant in zip(targets,variants):
        rid='replay-'+secrets.token_hex(16)
        messages=render_chat_messages(assemble_translation_prompt(req,ruleset))
        requests.append({'requestId':rid,'messages':[{'role':m.role,'content':m.content} for m in messages]})
        assignments.append({'requestId':rid,'caseId':case_id,'variantId':variant,'condition':condition,'executionInputHash':req.input_hash})
    requests.sort(key=lambda r:r['requestId'])
    projection=project_dialogue_context(request.dialogue_context).to_dict()
    template={'caseId':case_id,'targetSource':request.source_text,
        'possiblePredecessors':projection['possiblePredecessors'],'possibleSuccessors':projection['possibleSuccessors'],
        'translations':{'variant-1':None,'variant-2':None},
        'assessment':{'sourceMeaningPreserved':None,'semanticDriftVariant':None,'sourceAbsentInformation':None,'alternativesAsSequence':None,'reviewer':None,'notes':None}}
    manifest={'requestCount':2,'pairCount':1,'requestFingerprint':fingerprint(requests),'assignmentFingerprint':fingerprint(assignments),
        'templateFingerprint':fingerprint(template),'rendererVersion':'dialogue-prompt/1','safetyInstructions':list(DIALOGUE_CONTEXT_SAFETY_INSTRUCTIONS),
        'status':'WAITING_EXTERNAL_TRANSLATIONS','limitedToKnownRiskCase':True,'safetyRegression':'NOT_EVALUATED'}
    output.mkdir(parents=True)
    for name,rows in [('chatgpt-translation-requests.jsonl',requests),('assignments-local-only.jsonl',assignments),('blind-review-template.jsonl',[template])]:
        (output/name).write_bytes(b''.join(canonical_bytes(r)+b'\n' for r in rows))
    (output/'replay-local-manifest.json').write_bytes(canonical_bytes(manifest)+b'\n')
    (output/'README.txt').write_text(
        'LOCAL ONLY. Give ChatGPT ONLY chatgpt-translation-requests.jsonl.\n'
        'Execute each messages array independently. Translate only the top-level sourceText;\n'
        'preserve runtime syntax/markup and return one JSONL row per request:\n'
        '{"requestId":"...","translationText":"..."}\n'
        'Do not send assignments-local-only.jsonl, the local manifest, or prior translations.\n'
        'Import the exact two responses with import_semantic_replay_responses. No repair/partial acceptance.\n'
        'Then give ChatGPT ONLY blind-review-ready.jsonl. Assess source meaning, semantic drift,\n'
        'unsupported additions, and alternatives-as-sequence; fill every assessment field explicitly.\n'
        'Do not unblind during review. This case alone cannot establish general dialogue safety.\n'
        'Validate the completed review with validate_semantic_replay_review before separate local unblinding.\n'
        'No safety PASS is inferred from translation import or technical syntax checks.\n',encoding='utf-8')
    return manifest


def import_semantic_replay_responses(package,responses, *, translation_source):
    package=Path(package)
    if not translation_source.strip():raise ValueError('translation source required')
    manifest=strict_json_loads((package/'replay-local-manifest.json').read_bytes())
    requests=_rows(package/'chatgpt-translation-requests.jsonl');assignments=_rows(package/'assignments-local-only.jsonl')
    templates=_rows(package/'blind-review-template.jsonl')
    if (fingerprint(requests)!=manifest['requestFingerprint'] or fingerprint(assignments)!=manifest['assignmentFingerprint']
            or len(templates)!=1 or fingerprint(templates[0])!=manifest['templateFingerprint'] or len(requests)!=2):raise ValueError('replay seal mismatch')
    request_map={r['requestId']:r for r in requests}
    # Only request/pair/variant columns are used for blind pairing.
    pairing={r['requestId']:(r['caseId'],r['variantId']) for r in assignments}
    if len(request_map)!=2 or len(pairing)!=2 or set(pairing)!=set(request_map) or {v[1] for v in pairing.values()}!={'variant-1','variant-2'}:raise ValueError('replay pairing invalid')
    template=templates[0];texts={}
    for response in _rows(responses):
        if set(response)!={'requestId','translationText'} or type(response['requestId']) is not str or response['requestId'] not in request_map or response['requestId'] in texts:
            raise ValueError('response inventory invalid')
        text=response['translationText']
        if type(text) is not str or not text.strip():raise ValueError('translationText invalid')
        source=template['targetSource']
        if validate_protected_syntax(extract_protected_tokens(source),text) or _markup_lexemes(source)!=_markup_lexemes(text):raise ValueError('protected source syntax changed')
        texts[response['requestId']]=text
    if set(texts)!=set(request_map):raise ValueError('responses incomplete')
    review={**template,'translations':dict(template['translations'])}
    for rid,text in texts.items():
        case,variant=pairing[rid]
        if case!=review['caseId']:raise ValueError('case mismatch')
        review['translations'][variant]=text
    target=package/'blind-review-ready.jsonl'
    if target.exists():raise ValueError('blind review already exists')
    target.write_bytes(canonical_bytes(review)+b'\n')
    report={'imported':2,'pairs':1,'translationSource':translation_source,'blindReviewFingerprint':fingerprint(review),'safetyRegression':'NOT_EVALUATED'}
    (package/'response-import-local.json').write_bytes(canonical_bytes(report)+b'\n')
    return report


def validate_semantic_replay_review(package, completed):
    original=_rows(Path(package)/'blind-review-ready.jsonl');review=_rows(completed)
    imported=strict_json_loads((Path(package)/'response-import-local.json').read_bytes())
    if len(original)!=1 or fingerprint(original[0])!=imported['blindReviewFingerprint']:raise ValueError('original blind review seal mismatch')
    if len(review)!=1 or len(original)!=1 or set(review[0])!=set(original[0]):raise ValueError('review inventory/schema invalid')
    if any(review[0][k]!=original[0][k] for k in original[0] if k!='assessment'):raise ValueError('review source/translation changed')
    assessment=review[0]['assessment']
    if type(assessment) is not dict or set(assessment)!=set(original[0]['assessment']) or any(v is None for v in assessment.values()):raise ValueError('assessment incomplete')
    if assessment['semanticDriftVariant'] not in {'variant-1','variant-2','both','neither','insufficient-evidence'}:raise ValueError('drift assessment invalid')
    for key in ('sourceMeaningPreserved','sourceAbsentInformation','alternativesAsSequence'):
        if type(assessment[key]) is not dict or set(assessment[key])!={'variant-1','variant-2'} or any(type(v) is not bool for v in assessment[key].values()):raise ValueError('variant assessment invalid')
    if not isinstance(assessment['reviewer'],str) or not assessment['reviewer'].strip() or not isinstance(assessment['notes'],str):raise ValueError('reviewer/notes invalid')
    return {'pairsReviewed':1,'reviewFingerprint':fingerprint(review[0]),'scope':'known-risk-case-only','safetyRegression':'REQUIRES_SEPARATE_LOCAL_ADJUDICATION'}
