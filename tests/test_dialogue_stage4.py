"""Complete fictional portable prepares and offline end-to-end regression."""
from dataclasses import replace
from pathlib import Path
import json
import shutil
import sqlite3
import zipfile
from unittest.mock import Mock

import pytest

from bg3loc.backends import ArchiveEntry
from bg3loc.dialogue_context import canonical_bytes, fingerprint
from bg3loc.dialogue_execution_contract import validate_stage2_workspace
from bg3loc.portable_assets import verify_finalize_assets, PortableAssetsError, safe_file, collision_free
from bg3loc.portable_finalize import finalize_portable_workspace
from bg3loc.production_orchestration import prepare_production_workspace
from bg3loc.rebuilder import LocaRecord, write_loca_xml, parse_loca_xml
from bg3loc.offline_integration import run_offline_integration, OfflineOutcome
from bg3loc.production_context import context_from_material
from bg3loc.production_workspace import verify_production_workspace
from bg3loc.translation_request import BatchMaterialResolver
from bg3loc.dialogue_context import DialogueContextValidationError
from bg3loc.research.dialogue_context import DialogueAudit
from test_production_context import fixture as old_fixture, read_rows, write_rows
from test_dialogue_context_research import parse
from test_dialogue_stage1 import graph_data, sources


class FictionalBackend:
    id='fictional-portability'
    def convert_loca(self,source,destination):
        destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,destination)
    def list_archive(self,package,expression='*'):
        with zipfile.ZipFile(package) as archive:
            return [ArchiveEntry(i.filename,i.file_size,i.CRC) for i in archive.infolist()]
    def extract_single_file(self,package,entry,destination):
        destination.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(package) as archive:destination.write_bytes(archive.read(entry))
    def extract_package(self,package,destination):
        with zipfile.ZipFile(package) as archive:archive.extractall(destination)
    def create_package(self,source_dir,destination):
        with zipfile.ZipFile(destination,'w') as archive:
            for path in sorted(source_dir.rglob('*')):
                if path.is_file():archive.write(path,path.relative_to(source_dir).as_posix())


def inputs(root,kind='pak'):
    root.mkdir(parents=True);request,_=old_fixture(root)
    source=read_rows(request.source);mapping=read_rows(request.research_mappings)
    for row in source:row['version']=1
    for uid,text in sources().items():
        source.append({'contentUid':uid,'localeId':'English','text':text,'version':2})
        mapping.append({'contentUid':uid,'mappingType':'dialog-context','classification':'dialogue_general','evidence':[], 'metadata':{}})
    write_rows(request.source,source);write_rows(request.research_mappings,mapping)
    rules=json.loads(request.ruleset.read_text(encoding='utf-8'));rules['categoryRules']['dialogue_general']=[]
    request.ruleset.write_text(json.dumps(rules),encoding='utf-8')
    assets=root/'assets';assets.mkdir()
    source_xml=assets/'English.xml';write_loca_xml(source_xml,[LocaRecord(r['contentUid'],r['version'],r['text']) for r in source])
    source_loca=assets/'English.loca';shutil.copyfile(source_xml,source_loca)
    baseline=[LocaRecord(source[0]['contentUid'],7,'保留原始譯文'),LocaRecord('fictional-target-only',9,'僅目標語系'),LocaRecord('fictional-blank',0,'')]
    xml=assets/'target.xml';write_loca_xml(xml,baseline);loca=assets/'target.loca';shutil.copyfile(xml,loca)
    target=assets/'target.jsonl';write_rows(target,[{'contentUid':r.content_uid,'version':r.version,'text':r.text,'localeId':'ChineseTraditional'} for r in baseline])
    pak=assets/'Fictional.pak' if kind=='pak' else loca
    entry='Localization/Fictional/target.loca'
    if kind=='pak':
        with zipfile.ZipFile(pak,'w') as archive:
            archive.writestr(entry,loca.read_bytes());archive.writestr('Auxiliary/untouched.bin',b'Fictional opaque payload')
    scan=root/'scan.json';scan.write_bytes(canonical_bytes({'game':{'appId':'1086940','buildId':'fictional-build','gameVersion':'fictional-version'}}))
    research=root/'research-summary.json';research.write_bytes(canonical_bytes({'complete':True,'appId':'1086940','buildId':'fictional-build','gameVersion':'fictional-version'}))
    extract={'schemaVersion':'1.0','scanManifest':str(scan.resolve()),'sourceLocale':'English','targetLocale':'ChineseTraditional','referenceLocales':[],
             'backend':{'id':'fictional'},'aligned':'fictional','roundtripValidation':'fictional','locales':[
                 {'localeId':'English','normalized':str(request.source.resolve()),'sourceXml':str(source_xml.resolve()),'sourceLoca':str(source_loca.resolve()),'packageFile':str(source_loca.resolve()),'locaEntry':'English.loca','nodeCount':len(source)},
                 {'localeId':'ChineseTraditional','normalized':str(target.resolve()),'sourceXml':str(xml.resolve()),'sourceLoca':str(loca.resolve()),'packageFile':str(pak.resolve()),'locaEntry':entry,'nodeCount':len(baseline)}]}
    request.extract_manifest.write_bytes(canonical_bytes(extract))
    evidence=root/'dialogue';audit=DialogueAudit();audit.add(parse(graph_data()));audit.write(evidence)
    summary=json.loads((evidence/'dialogue-summary.json').read_text(encoding='utf-8'));summary['corpus']={'appId':'1086940','buildId':'fictional-build','gameVersion':'fictional-version'}
    (evidence/'dialogue-summary.json').write_bytes(canonical_bytes(summary))
    return replace(request,dialogue_evidence=evidence,source_scan=scan,research_summary=research),FictionalBackend()


def prepared(root,kind='pak'):
    request,backend=inputs(root,kind);manifest=prepare_production_workspace(request,archive_backend=backend)
    return request,backend,manifest


def finish_all(request,backend):
    from test_production_context import material_rows
    rows=material_rows(request.output_dir)
    outcomes={uid:[OfflineOutcome('虛構測試譯文')] for uid in rows}
    human={uid:('ACCEPT',None) for uid in rows}
    return run_offline_integration(request.output_dir,outcomes,human_decisions=human,backend=backend)


def test_complete_prepare_atomic_coexistence_and_never_activates(tmp_path):
    request,backend,manifest=prepared(tmp_path/'input')
    binding=validate_stage2_workspace(request.output_dir)
    assert manifest['schemaVersion']=='1.3' and binding.context_count==4
    assert manifest['sameEntityContext']['withContext']>0
    view=verify_finalize_assets(request.output_dir,manifest['finalizeAssets'],backend=backend)
    assert view.target_versions['fictional-blank']==0 and view.target_versions['fictional-target-only']==9
    assert len(view.bundle['targetPackage']['entries'])==2
    with pytest.raises(DialogueContextValidationError):verify_production_workspace(request.output_dir)
    with pytest.raises(DialogueContextValidationError):BatchMaterialResolver(binding.batch_plan)
    with pytest.raises(PortableAssetsError):prepare_production_workspace(request,archive_backend=backend)


@pytest.mark.parametrize('kind',['loca','pak'])
def test_offline_end_to_end_relocated_finalize_preserves_payload_and_versions(tmp_path,kind,monkeypatch):
    request,backend,manifest=prepared(tmp_path/'input',kind);metrics=finish_all(request,backend)
    assert metrics['productionProviderCalls']==0
    relocated=tmp_path/'relocated';shutil.copytree(request.output_dir,relocated)
    assert (tmp_path/'input').resolve().is_relative_to(tmp_path.resolve())
    shutil.rmtree(tmp_path/'input')  # only this test's newly created input fixtures
    other=tmp_path/'cwd';other.mkdir();monkeypatch.chdir(other)
    validate_stage2_workspace(relocated);verify_finalize_assets(relocated,manifest['finalizeAssets'],backend=backend)
    out=tmp_path/'final';result=finalize_portable_workspace(relocated,out,backend=backend)
    assert result['semanticRoundTrip'] and result['newSourceOnlyCount']>0
    data={r.content_uid:r for r in parse_loca_xml(out/'ChineseTraditional.loca')}
    assert data['fictional-target-only'].text=='僅目標語系' and data['fictional-blank'].text==''
    assert data['fictional-target-only'].version==9 and data['fictional-blank'].version==0
    original=json.loads((relocated/'production-manifest.json').read_text())
    bundle=json.loads((relocated/original['finalizeAssets']['path']).read_text())
    shared=next(r for r in parse_loca_xml(relocated/bundle['targetBaselineXml']['path']) if r.content_uid not in {'fictional-target-only','fictional-blank'})
    assert data[shared.content_uid].version==7
    if kind=='pak':
        with zipfile.ZipFile(out/'Fictional.pak') as archive:
            assert archive.read('Auxiliary/untouched.bin')==b'Fictional opaque payload'
            assert archive.read('Localization/Fictional/target.loca')==(out/'ChineseTraditional.loca').read_bytes()


@pytest.mark.parametrize('attack',['missing','tamper','wrong_size','collision','escape','absolute','link'])
def test_d7_corruption_rejected(tmp_path,attack):
    request,backend,manifest=prepared(tmp_path/'input');root=request.output_dir
    path=root/manifest['finalizeAssets']['path'];bundle=json.loads(path.read_text())
    descriptor=bundle['targetBaselineXml'];file=root/descriptor['path']
    if attack=='missing':file.unlink()
    elif attack=='tamper':file.write_bytes(b'tampered')
    elif attack=='wrong_size':descriptor['size']+=1
    elif attack=='collision':bundle['targetPackage']['entries'].append({**bundle['targetPackage']['entries'][0],'entryPath':bundle['targetPackage']['entries'][0]['entryPath'].upper()})
    elif attack=='escape':descriptor['path']='../outside'
    elif attack=='absolute':descriptor['path']='C:/outside'
    else:
        external=tmp_path/'external';external.write_bytes(file.read_bytes());file.unlink()
        try:file.symlink_to(external)
        except OSError:pytest.skip('host does not permit creating symlinks')
    if attack not in {'missing','tamper','link'}:
        bundle.pop('assetFingerprint');bundle['assetFingerprint']=fingerprint(bundle);path.write_bytes(canonical_bytes(bundle));manifest['finalizeAssets']['sha256']=__import__('hashlib').sha256(path.read_bytes()).hexdigest();manifest['finalizeAssets']['assetFingerprint']=bundle['assetFingerprint']
    with pytest.raises((PortableAssetsError,DialogueContextValidationError)):verify_finalize_assets(root,manifest['finalizeAssets'],backend=backend)


def test_writer_barrier_blocks_concurrent_update_and_atomic_output(tmp_path):
    request,backend,_=prepared(tmp_path/'input');finish_all(request,backend)
    observed=[]
    def writer(conn):
        with sqlite3.connect(request.output_dir/'execution.sqlite3',timeout=.05) as second:
            with pytest.raises(sqlite3.OperationalError):second.execute("UPDATE content_state SET updated_at='raced'")
        observed.append(True)
    result=finalize_portable_workspace(request.output_dir,tmp_path/'final',backend=backend,observer=writer)
    assert observed==[True] and result['writerBarrierSeconds']>0


@pytest.mark.parametrize('names',[['a','A'],['e\u0301','é'],['../escape'],['C:/outside'],['dir\\outside'],['/absolute'],['NUL.bin']])
def test_archive_path_policy(names):
    with pytest.raises(PortableAssetsError):collision_free(names)


def test_prepare_failure_never_publishes_partial_workspace(tmp_path):
    request,backend=inputs(tmp_path/'input')
    summary=json.loads(request.research_summary.read_text());summary['buildId']='other';request.research_summary.write_text(json.dumps(summary))
    with pytest.raises(PortableAssetsError):prepare_production_workspace(request,archive_backend=backend)
    assert not request.output_dir.exists()


def test_batch_split_identity_and_material_determinism(tmp_path):
    request,backend,first=prepared(tmp_path/'input')
    second_request=replace(request,output_dir=tmp_path/'split',max_records=('dialogue_general=2','item=2','skill_spell=2','quest=2'))
    second=prepare_production_workspace(second_request,archive_backend=backend)
    assert first['dialogueContext']==second['dialogueContext']
    assert first['finalizeAssets']==second['finalizeAssets']
    def hashes(root):
        with sqlite3.connect(root/'execution.sqlite3') as conn:return dict(conn.execute('SELECT content_uid,input_hash FROM content_state'))
    assert hashes(request.output_dir)==hashes(second_request.output_dir)


def test_reparse_attribute_is_rejected_without_host_symlink_privilege(tmp_path,monkeypatch):
    from types import SimpleNamespace
    root=tmp_path/'root';root.mkdir();file=root/'data.bin';file.write_bytes(b'fixture')
    original=Path.lstat
    def marked(self,*a,**kw):
        value=original(self,*a,**kw)
        if self==file:return SimpleNamespace(st_file_attributes=0x400,st_mode=value.st_mode)
        return value
    monkeypatch.setattr(Path,'lstat',marked)
    with pytest.raises(PortableAssetsError,match='PATH_ESCAPE_OR_LINK'):safe_file(root,'data.bin')


def test_repack_failure_does_not_publish_output(tmp_path):
    request,backend,_=prepared(tmp_path/'input');finish_all(request,backend)
    class BadBackend(FictionalBackend):
        def create_package(self,source_dir,destination):
            super().create_package(source_dir,destination)
            with zipfile.ZipFile(destination,'a') as archive:archive.writestr('unexpected.bin',b'bad')
    with pytest.raises(PortableAssetsError):finalize_portable_workspace(request.output_dir,tmp_path/'bad-output',backend=BadBackend())
    assert not (tmp_path/'bad-output').exists()
