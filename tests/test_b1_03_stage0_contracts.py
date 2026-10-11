"""Synthetic documentation-contract models, NOT production implementations.

No import of a future DialogueContext API: tests deliberately implement a small
independent model of the frozen spec and exercise existing compatibility/merge
primitives. Runtime production integration remains absent.
"""
from copy import deepcopy
from dataclasses import FrozenInstanceError, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from types import MappingProxyType

from jsonschema import Draft202012Validator
import pytest

from bg3loc.rebuilder import LocaRecord, merge_records, validate_rebuilt_records
from bg3loc.translation_identity import translation_input_hash
from test_context_execution_identity import parameters, item_hash
from test_same_entity_prompt_integration import baseline_request, with_context, ruleset
from bg3loc.prompt_assembly import assemble_translation_prompt
from bg3loc.chat_prompt import render_chat_messages, chat_messages_fingerprint

DOC = Path(__file__).resolve().parents[1] / 'docs/research/b1-03-stage0-contracts'
REGISTRY = json.loads((DOC/'version-registry.json').read_text(encoding='utf-8'))
V = REGISTRY['versions']


def canonical(x):
    return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def fingerprint(x):
    return sha256(canonical(x).encode('utf-8')).hexdigest()


def text_hash(x):
    return sha256(x.encode('utf-8')).hexdigest()


def proof_projection(dto):
    result={'targetBinding':dto['targetBinding'],'targetProof':dto['targetProof']}
    for direction in ['possiblePredecessors','possibleSuccessors']:
        result[direction]=[{**{k:g[k] for k in ['nodeId','nodeIdentityOrigin','nodeDefinitionFingerprint','nativeChildProof']},
            'sourceVariants':[{'contentUid':s['contentUid'],'sourceTextSha256':text_hash(s['sourceText']),
                               'occurrenceFingerprints':s['occurrenceFingerprints']} for s in g['sourceVariants']]}
            for g in dto[direction]]
    return result


def resign(dto):
    dto['sourceCodepoints']=sum(len(s['sourceText']) for d in ['possiblePredecessors','possibleSuccessors']
                               for g in dto[d] for s in g['sourceVariants'])
    dto['evidenceFingerprint']=fingerprint(proof_projection(dto))
    dto['contextFingerprint']=fingerprint({k:v for k,v in dto.items() if k!='contextFingerprint'})
    return dto


def fixture(text='Fictional predecessor.'):
    dto={'schemaVersion':V['dialogueSchema'],'policyVersion':V['structuralPolicy'],
         'orderingVersion':V['ordering'],'budgetContract':REGISTRY['budgetContract'],
         'targetBinding':{'contentUid':'fictional-target','category':'dialogue_general','sourceTextSha256':text_hash('Target.')},
         'targetProof':{'dialogueId':'fictional-dialogue','dialogueIdentityOrigin':'native_UUID','nodeId':'target-node',
             'nodeIdentityOrigin':'native_UUID','dialogueDefinitionFingerprint':fingerprint('dialogue'),
             'nodeDefinitionFingerprint':fingerprint('target'),'sourceOccurrenceFingerprint':fingerprint('occurrence')},
         'possiblePredecessors':[{'nodeId':'parent-node','nodeIdentityOrigin':'native_UUID','nodeDefinitionFingerprint':fingerprint('parent'),
             'nativeChildProof':{'edgeType':'child','fromNodeId':'parent-node','toNodeId':'target-node','edgeDefinitionFingerprint':fingerprint('edge')},
             'sourceVariants':[{'contentUid':'fictional-neighbour','sourceText':text,'occurrenceFingerprints':[fingerprint('variant')]}]}],
         'possibleSuccessors':[]}
    return resign(deepcopy(dto))


def deep_freeze(value):
    if isinstance(value,dict):return MappingProxyType({k:deep_freeze(v) for k,v in value.items()})
    if isinstance(value,list):return tuple(deep_freeze(v) for v in value)
    return value


@dataclass(frozen=True)
class SyntheticFrozenDTO:
    data: object


def model_decode(dto,uid='fictional-target',category='dialogue_general',source='Target.'):
    schema=json.loads((DOC/'dialogue-context.schema.json').read_text())
    Draft202012Validator(schema).validate(dto)
    assert type(dto['sourceCodepoints']) is int
    assert type(dto['budgetContract']['maxSourceCodepoints']) is int
    assert dto['targetBinding']=={'contentUid':uid,'category':category,'sourceTextSha256':text_hash(source)}
    target=dto['targetProof']['nodeId']
    for direction in ['possiblePredecessors','possibleSuccessors']:
        groups=dto[direction];ids=[g['nodeId'] for g in groups]
        assert ids==sorted(set(ids)) and target not in ids
        for group in groups:
            edge=group['nativeChildProof']
            assert (edge['fromNodeId'],edge['toNodeId'])==((group['nodeId'],target) if direction=='possiblePredecessors' else (target,group['nodeId']))
            variants=group['sourceVariants'];uids=[s['contentUid'] for s in variants]
            assert uids==sorted(set(uids)) and uid not in uids
            for variant in variants:
                text=variant['sourceText'];assert text.strip() and text.strip()!='%%% EMPTY';text.encode('utf-8')
                fps=variant['occurrenceFingerprints'];assert fps==sorted(set(fps))
    count=sum(len(s['sourceText']) for d in ['possiblePredecessors','possibleSuccessors'] for g in dto[d] for s in g['sourceVariants'])
    assert count==dto['sourceCodepoints'] and count<=2000
    assert fingerprint(proof_projection(dto))==dto['evidenceFingerprint']
    assert fingerprint({k:v for k,v in dto.items() if k!='contextFingerprint'})==dto['contextFingerprint']
    return SyntheticFrozenDTO(deep_freeze(dto))


def safe_wire(dto):
    model_decode(dto)
    return {'relationType':'nativeChild','relationSemantics':'possibleStructuralAlternatives',
            **{d:[{'sourceVariants':[{'sourceText':s['sourceText']} for s in g['sourceVariants']]} for g in dto[d]]
               for d in ['possiblePredecessors','possibleSuccessors']}}


def model_hash(request,dialogue=None):
    if dialogue is not None and request.same_entity_context is not None:raise ValueError('BOTH_CONTEXT_FAMILIES')
    if dialogue is None:return item_hash(request)
    model_decode(dialogue,uid=request.content_uid,category=request.primary_category,source=request.source_text)
    params=parameters()
    base={'ContentUid':request.content_uid,'SourceText':request.source_text,'primaryCategory':request.primary_category,
          'protectedSyntax':None,'promptVersion':params.prompt_version,'rulesetFingerprint':params.ruleset_fingerprint,
          'sourceLocale':params.source_locale,'targetLocale':params.target_locale}
    base.update(inputIdentityVersion=V['dialogueInputIdentity'],dialogueContext={
        'schemaVersion':V['dialogueSchema'],'policyVersion':V['structuralPolicy'],'contextFingerprint':dialogue['contextFingerprint'],
        'orderingVersion':V['ordering'],'budgetContract':REGISTRY['budgetContract'],'promptRendererVersion':V['promptRenderer'],
        'promptSafetyVersion':V['promptSafety'],'promptPolicyFingerprint':REGISTRY['promptPolicyFingerprint'],
        'semanticReviewPolicyVersion':V['semanticReview'],'semanticReviewPolicyFingerprint':REGISTRY['semanticReviewPolicyFingerprint']})
    return fingerprint(base)


def model_safe_path(root,raw):
    assert isinstance(raw,str) and raw and not raw.startswith('/') and not re.search(r'[:\\\x00-\x1f]',raw)
    parts=raw.split('/');assert all(p not in {'','.', '..'} and not p.endswith((' ','.')) for p in parts)
    assert all(p.split('.')[0].upper() not in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]} for p in parts)
    candidate=root.joinpath(*parts)
    for ancestor in [candidate,*candidate.parents]:
        if ancestor==root.parent:break
        assert not ancestor.is_symlink()
    assert candidate.resolve().is_relative_to(root.resolve())
    return candidate


def test_documentation_schemas_and_version_registry_consistent():
    for file in DOC.glob('*.schema.json'):Draft202012Validator.check_schema(json.loads(file.read_text()))
    assert REGISTRY['budgetContract']=={'version':V['budget'],'countingVersion':V['counting'],'maxSourceCodepoints':2000}
    assert REGISTRY['promptPolicyFingerprint']==fingerprint({'promptRendererVersion':V['promptRenderer'],
        'promptSafetyVersion':V['promptSafety'],'safetyInstructions':REGISTRY['dialogueSafetyInstructions']})
    assert REGISTRY['semanticReviewPolicyFingerprint']==fingerprint(REGISTRY['semanticReviewRouting'])
    assert V['productionManifest']=='1.3' and V['dialogueInputIdentity']=='translation-input/3'


def test_frozen_DTO_and_safe_projection():
    dto=fixture();value=model_decode(dto)
    with pytest.raises(FrozenInstanceError):value.data={}
    with pytest.raises(TypeError):value.data['policyVersion']='other'
    with pytest.raises(TypeError):value.data['possiblePredecessors'][0]['sourceVariants'][0]['sourceText']='edited'
    assert safe_wire(dto)=={'relationType':'nativeChild','relationSemantics':'possibleStructuralAlternatives',
        'possiblePredecessors':[{'sourceVariants':[{'sourceText':'Fictional predecessor.'}]}],'possibleSuccessors':[]}


@pytest.mark.parametrize('length',[1999,2000,2001])
def test_whole_set_budget_boundaries_and_nonBMP_codepoints(length):
    dto=fixture('📜'*length)
    if length<=2000:assert model_decode(dto).data['sourceCodepoints']==length
    else:
        with pytest.raises(Exception):model_decode(dto)
    # Prepare decides absence atomically; never construct a truncated DTO.
    assert ('present' if dto['sourceCodepoints']<=2000 else 'absent')==('present' if length<=2000 else 'absent')


@pytest.mark.parametrize('mutation',['speaker','null','empty','wrong_edge','wrong_target','wrong_version','count','evidence','context','float'])
def test_strict_decoder_failures(mutation):
    dto=fixture()
    if mutation=='speaker':dto['speaker']={'slot':0}
    elif mutation=='null':dto=None
    elif mutation=='empty':dto['possiblePredecessors']=[];resign(dto)
    elif mutation=='wrong_edge':dto['possiblePredecessors'][0]['nativeChildProof']['fromNodeId']='wrong';resign(dto)
    elif mutation=='wrong_target':dto['targetBinding']['category']='bark';resign(dto)
    elif mutation=='wrong_version':dto['schemaVersion']='future'
    elif mutation=='count':dto['sourceCodepoints']+=1
    elif mutation=='evidence':dto['evidenceFingerprint']='0'*64
    elif mutation=='context':dto['contextFingerprint']='0'*64
    elif mutation=='float':dto['budgetContract']['maxSourceCodepoints']=2000.0;resign(dto)
    with pytest.raises(Exception):model_decode(dto)


def test_distinct_nodes_directions_with_equal_text_are_not_deduplicated():
    dto=fixture('same')
    other=deepcopy(dto['possiblePredecessors'][0]);other['nodeId']='successor-node';other['sourceVariants'][0]['contentUid']='second-uid'
    other['nativeChildProof'].update(fromNodeId='target-node',toNodeId='successor-node')
    dto['possibleSuccessors']=[other];resign(dto)
    assert model_decode(dto).data['sourceCodepoints']==8
    assert len(safe_wire(dto)['possibleSuccessors'])==1


def test_legacy_and_B1_02_preservation_feasibility_uses_existing_functions():
    golden=json.loads((DOC/'synthetic-existing-goldens.json').read_text())
    for mode,request in [('H0',baseline_request()),('HSE',with_context())]:
        assert model_hash(request)==golden[mode]['inputHash']
        prompt=assemble_translation_prompt(request,ruleset())
        assert prompt.effective_prompt_hash==golden[mode]['effectivePromptHash']
        assert chat_messages_fingerprint(render_chat_messages(prompt))==golden[mode]['messagesFingerprint']
    with pytest.raises(ValueError,match='BOTH_CONTEXT'):model_hash(with_context(),fixture())


def test_HD_changed_removed_added_identity_and_proof_only_change():
    from dataclasses import replace
    request=replace(baseline_request(),content_uid='fictional-target',source_text='Target.',primary_category='dialogue_general',same_entity_context=None)
    dto=fixture();h0=model_hash(request);hd=model_hash(request,dto)
    assert hd!=h0 and model_hash(request,None)==h0
    changed=deepcopy(dto);changed['targetProof']['sourceOccurrenceFingerprint']=fingerprint('changed');resign(changed)
    assert model_hash(request,changed)!=hd and safe_wire(changed)==safe_wire(dto)


@pytest.mark.parametrize('mode',['H0','HSE','HD'])
@pytest.mark.parametrize('technical',['PASS','REVIEW','RETRY','FAIL'])
def test_semantic_routing_does_not_change_other_families(mode,technical):
    route='REVIEW' if mode=='HD' and technical=='PASS' else technical
    assert route==('REVIEW' if mode=='HD' and technical in {'PASS','REVIEW'} else technical)
    if mode!='HD':assert route==technical


def test_review_required_completion_consistency():
    def complete(route,input_ok,output_ok,accepted):
        return route=='REVIEW' and input_ok and output_ok and accepted
    assert not complete('PASS',True,True,True)
    assert not complete('REVIEW',False,True,True)
    assert not complete('REVIEW',True,False,True)
    assert not complete('REVIEW',True,True,False)
    assert complete('REVIEW',True,True,True)


@pytest.mark.parametrize('path',['../escape','a/../escape','/absolute','drive:/escape','a\\escape','a//b','a/./b','NUL.bin','a/','a.','a '])
def test_portable_paths_reject_unsafe_lexemes(tmp_path,path):
    with pytest.raises(AssertionError):model_safe_path(tmp_path,path)


def test_asset_relocation_hash_and_traversal_rules(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b';a.mkdir();b.mkdir()
    for root in [a,b]:
        path=model_safe_path(root,'inputs/finalize-assets/objects/payload.bin');path.parent.mkdir(parents=True);path.write_bytes(b'fictional bytes')
    assert model_safe_path(a,'inputs/finalize-assets/objects/payload.bin').read_bytes()==model_safe_path(b,'inputs/finalize-assets/objects/payload.bin').read_bytes()
    expected=sha256(b'fictional bytes').hexdigest();assert sha256(model_safe_path(b,'inputs/finalize-assets/objects/payload.bin').read_bytes()).hexdigest()==expected
    model_safe_path(b,'inputs/finalize-assets/objects/payload.bin').write_bytes(b'changed')
    assert sha256(model_safe_path(b,'inputs/finalize-assets/objects/payload.bin').read_bytes()).hexdigest()!=expected


def test_existing_merge_preserves_versions_blanks_target_only_and_adds_source_only():
    baseline=[LocaRecord('shared',8,'舊譯'),LocaRecord('target-only',99,'保留'),LocaRecord('blank',4,'')]
    source={'shared':{'version':3},'source-only':{'version':7}}
    accepted={'shared':{'version':8,'text':'修訂'},'source-only':{'version':7,'text':'新增'}}
    merged,changed,new=merge_records(baseline,source,accepted)
    assert merged==[LocaRecord('shared',8,'修訂'),LocaRecord('target-only',99,'保留'),LocaRecord('blank',4,''),LocaRecord('source-only',7,'新增')]
    assert new=={'source-only'} and changed=={'shared','source-only'}
    validate_rebuilt_records(baseline,merged,merged,accepted,changed)


def test_portable_archive_entry_closure_replaces_only_loca(tmp_path):
    entries={'Localization/Fictional/target.loca':b'original loca',
             'Auxiliary/untouched.bin':b'fictional auxiliary bytes'}
    root=tmp_path/'workspace';root.mkdir();manifest=[]
    for name,payload in sorted(entries.items()):
        digest=sha256(payload).hexdigest();relative=f'inputs/finalize-assets/objects/{digest}.bin'
        file=model_safe_path(root,relative);file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(payload)
        manifest.append({'entryPath':name,'snapshot':{'path':relative,'sha256':digest,'size':len(payload)}})
    restored={r['entryPath']:model_safe_path(root,r['snapshot']['path']).read_bytes() for r in manifest}
    assert restored==entries
    for r in manifest:assert sha256(restored[r['entryPath']]).hexdigest()==r['snapshot']['sha256']
    restored['Localization/Fictional/target.loca']=b'updated fictional loca'
    assert set(restored)==set(entries) and restored['Auxiliary/untouched.bin']==entries['Auxiliary/untouched.bin']


@pytest.mark.parametrize('threat',['downgrade','strip','missing_metadata','unknown_version','missing_asset_bundle'])
def test_manifest_stripping_and_downgrade_contract_model(threat):
    snapshot={'schemaVersion':'1.3','dialogueDeclared':True,'metadataContract':'sealed','assetBundle':True}
    if threat=='downgrade':snapshot['schemaVersion']='1.2'
    elif threat=='strip':snapshot['schemaVersion']=None
    elif threat=='missing_metadata':snapshot['metadataContract']=None
    elif threat=='unknown_version':snapshot['schemaVersion']='future'
    elif threat=='missing_asset_bundle':snapshot['assetBundle']=False
    valid=(snapshot['schemaVersion']=='1.3' and snapshot['metadataContract']=='sealed' and snapshot['assetBundle'])
    assert not valid  # No legacy fallback for declared dialogue or a sealed DB.


def test_manifest_1_3_schema_fixed_family_versions_and_legacy_metadata_shape(tmp_path):
    from test_b1_02_activation_gate import prepare_fixture
    (tmp_path/'old').mkdir()
    _,_,old=prepare_fixture(tmp_path/'old')
    schema=json.loads((DOC/'production-manifest-1.3.schema.json').read_text())
    old_schema=schema['properties']['sameEntityContext']
    Draft202012Validator(old_schema).validate(old['sameEntityContext'])
    contract_schema=schema['properties']['execution']['properties']['contextContract']
    d=contract_schema['properties']['families']['properties']['dialogue']
    descriptor={k:v['const'] for k,v in d['properties'].items() if 'const' in v}
    descriptor.update(budgetContract=REGISTRY['budgetContract'],dialogueContextMaterialFingerprint=fingerprint('material'))
    contract={'schemaVersion':V['contextExecutionContract'],'families':{'sameEntity':old['execution']['contextContract'],'dialogue':descriptor}}
    contract['contextContractFingerprint']=fingerprint(contract)
    Draft202012Validator(contract_schema).validate(contract)
    changed=deepcopy(contract);changed['families']['dialogue']['budgetContract']['maxSourceCodepoints']=4000
    with pytest.raises(Exception):Draft202012Validator(contract_schema).validate(changed)


def test_portable_asset_schema_declares_required_full_closure_roles():
    file={'path':'inputs/finalize-assets/objects/fictional.bin','sha256':fingerprint('bytes'),'size':1}
    bundle={'schemaVersion':V['finalizeAssets'],'pathPolicyVersion':V['assetPaths'],
        'finalizePolicyVersion':V['finalizePolicy'],'versionIndexSchemaVersion':V['versionIndex'],
        'sourceLocale':'English','targetLocale':'FictionalLocale','sourceUidCount':2,'targetUidCount':3,
        'originExtractManifestSha256':fingerprint('extract'),
        **{k:deepcopy(file) for k in ['sourceVersionIndex','targetVersionIndex','targetBaselineXml','targetBaselineLoca']},
        'targetPackage':{'kind':'pak','originalPackageName':'FictionalLocale.pak','locaEntry':'Localization/Fictional/target.loca',
                         'entries':[{'entryPath':'Localization/Fictional/target.loca','snapshot':deepcopy(file)}]}}
    bundle['assetFingerprint']=fingerprint(bundle)
    validator=Draft202012Validator(json.loads((DOC/'finalize-assets.schema.json').read_text()))
    validator.validate(bundle)
    for key in ['sourceVersionIndex','targetVersionIndex','targetBaselineXml','targetBaselineLoca','targetPackage']:
        changed=deepcopy(bundle);del changed[key]
        with pytest.raises(Exception):validator.validate(changed)
