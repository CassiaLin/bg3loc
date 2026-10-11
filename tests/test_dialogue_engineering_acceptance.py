"""Synthetic engineering acceptance, never semantic review or transport."""
import sqlite3
from types import SimpleNamespace

import pytest

from bg3loc.dialogue_context import DialogueContextValidationError
from bg3loc.portable_assets import PortableAssetsError
from bg3loc.portable_finalize import finalize_portable_workspace
from test_dialogue_stage4r import resolver_fixture
from test_dialogue_stage4 import prepared, finish_all
from test_production_context import material_rows


@pytest.mark.parametrize('in_transaction', [False, True])
def test_snapshot_rejects_borrowed_other_database(tmp_path, in_transaction):
    _,store,_,_,resolver,claim=resolver_fixture(tmp_path/'fixture')
    other=tmp_path/'other.sqlite3'
    with store.connect() as source,sqlite3.connect(other) as target:source.backup(target)
    with sqlite3.connect(other) as conn:
        conn.row_factory=sqlite3.Row
        if in_transaction:conn.execute('BEGIN IMMEDIATE')
        with pytest.raises(DialogueContextValidationError):
            resolver._sealed_snapshot.current_item(claim.content_uid,_connection=conn)
    resolver.close()


def test_snapshot_rejects_borrowed_autocommit_connection(tmp_path):
    _,store,_,_,resolver,claim=resolver_fixture(tmp_path/'fixture')
    with store.connect() as conn:
        with pytest.raises(DialogueContextValidationError):
            resolver._sealed_snapshot.current_item(claim.content_uid,_connection=conn)
    resolver.close()


def test_snapshot_rejects_stale_borrowed_read_transaction(tmp_path):
    _,store,_,_,resolver,claim=resolver_fixture(tmp_path/'fixture')
    with store.connect() as old:
        old.execute('BEGIN');old.execute('SELECT * FROM content_state').fetchall()
        with store.connect() as writer:
            writer.execute("UPDATE content_state SET input_hash='changed' WHERE content_uid=?",(claim.content_uid,));writer.commit()
        with pytest.raises(DialogueContextValidationError):
            resolver._sealed_snapshot.current_item(claim.content_uid,_connection=old)
    resolver.close()


def test_windows_reparse_substitution_after_open_fails_closed(tmp_path,monkeypatch):
    from pathlib import Path
    from bg3loc.sealed_snapshot import _PinnedFiles
    original=_PinnedFiles.__init__;lstat=Path.lstat;opened=set()
    def capture(self):
        original(self)
        if not self.windows:pytest.skip('Windows reparse pin race test')
        create=self.kernel.CreateFileW
        def record(*args):
            result=create(*args);opened.add(str(Path(args[0])));return result
        self.kernel=SimpleNamespace(CreateFileW=record,CloseHandle=self.kernel.CloseHandle)
    def substituted(path,*args,**kw):
        value=lstat(path,*args,**kw)
        if path.name=='production-manifest.json' and str(path) in opened:
            return SimpleNamespace(st_mode=value.st_mode,st_file_attributes=0x400)
        return value
    monkeypatch.setattr(_PinnedFiles,'__init__',capture);monkeypatch.setattr(Path,'lstat',substituted)
    with pytest.raises(DialogueContextValidationError):resolver_fixture(tmp_path/'fixture')


def test_nonlocking_capture_rejects_transient_material_read(tmp_path,monkeypatch):
    import json
    from pathlib import Path
    from bg3loc.sealed_snapshot import _PinnedFiles
    from test_dialogue_stage2 import fixture,parameters
    from bg3loc.translation_request import BatchMaterialResolver
    manifest,store,plan,materials,_=fixture(tmp_path/'fixture')
    def no_lock(self):self.handles=[];self.paths=set();self.identities={};self.windows=False
    read=Path.read_text
    def transient(path,*args,**kw):
        text=read(path,*args,**kw)
        if path==materials[0]:
            rows=[json.loads(line) for line in text.splitlines()]
            for row in rows:row['contextGroupKeys'].append('SYNTHETIC transient unsealed metadata')
            return '\n'.join(json.dumps(row) for row in rows)+'\n'
        return text
    monkeypatch.setattr(_PinnedFiles,'__init__',no_lock);monkeypatch.setattr(Path,'read_text',transient)
    with pytest.raises(DialogueContextValidationError):BatchMaterialResolver(plan,input_parameters=parameters(),stage2_validation_only=True)


def test_windows_preexisting_writable_section_cannot_bypass_snapshot(tmp_path):
    import ctypes,os
    from bg3loc.sealed_snapshot import _PinnedFiles
    from test_dialogue_stage2 import fixture,parameters
    from bg3loc.translation_request import BatchMaterialResolver
    from bg3loc.execution_state import ClaimedAttempt
    if os.name!='nt':pytest.skip('Windows mapped-section integrity probe')
    _,store,plan,materials,_=fixture(tmp_path/'fixture');path=materials[0]
    kernel=_PinnedFiles().kernel
    kernel.CreateFileMappingW.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_wchar_p]
    kernel.CreateFileMappingW.restype=ctypes.c_void_p
    kernel.MapViewOfFile.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_size_t]
    kernel.MapViewOfFile.restype=ctypes.c_void_p
    kernel.UnmapViewOfFile.argtypes=[ctypes.c_void_p]
    file=kernel.CreateFileW(str(path),0xc0000000,3,None,3,0,None)
    assert file!=ctypes.c_void_p(-1).value
    section=kernel.CreateFileMappingW(file,None,4,0,0,None);assert section
    view=kernel.MapViewOfFile(section,2,0,0,0);assert view
    kernel.CloseHandle(file)
    original=ctypes.string_at(view,1);resolver=None
    try:
        try:resolver=BatchMaterialResolver(plan,input_parameters=parameters(),stage2_validation_only=True)
        except DialogueContextValidationError:return  # Pin refused a mapped writer.
        state=store.get_state(next(iter(resolver._sealed_snapshot.items)))
        claim=ClaimedAttempt(-1,'preview',state['content_uid'],state['batch_id'],0,state['input_hash'],'none','none')
        ctypes.memmove(view,b' ',1)
        with pytest.raises(DialogueContextValidationError):resolver.resolve(claim)
    finally:
        ctypes.memmove(view,original,1)
        if resolver is not None:resolver.close()
        kernel.UnmapViewOfFile(view);kernel.CloseHandle(section)


def test_finalize_staging_is_enumerable_by_dot_sensitive_backend(tmp_path):
    from test_dialogue_stage4 import FictionalBackend
    import zipfile
    request,_,_=prepared(tmp_path/'input')
    class DotSensitiveBackend(FictionalBackend):
        def create_package(self,source_dir,destination):
            if source_dir.parent.parent.name.startswith('.'):
                with zipfile.ZipFile(destination,'w'):pass
            else:super().create_package(source_dir,destination)
    backend=DotSensitiveBackend();finish_all(request,backend)
    result=finalize_portable_workspace(request.output_dir,tmp_path/'output',backend=backend)
    assert result['nonLocaPayloadParity'] and result['semanticRoundTrip']


@pytest.mark.parametrize('family',['H0','HSE'])
def test_modern_completion_blocks_unbound_non_hd_output(tmp_path,family):
    from bg3loc.production_completion import build_production_completion_view
    request,backend,_=prepared(tmp_path/'input');finish_all(request,backend)
    uid=next(uid for uid,row in material_rows(request.output_dir).items()
        if 'dialogueContext' not in row and ('sameEntityContext' in row)==(family=='HSE'))
    with sqlite3.connect(request.output_dir/'execution.sqlite3') as conn:
        conn.execute('UPDATE content_state SET translated_text=? WHERE content_uid=?',('SYNTHETIC unbound output',uid));conn.commit()
    view=build_production_completion_view(request.output_dir/'execution.sqlite3',request.output_dir/'batches/batch-plan.json',stage3_validation_only=True)
    assert next(row for row in view.rows if row.content_uid==uid).disposition=='BLOCKED'


@pytest.mark.parametrize('phase',['observer','rebuild'])
def test_finalize_rejects_unbound_non_hd_translation_bytes(tmp_path,phase):
    request,backend,_=prepared(tmp_path/'input');finish_all(request,backend)
    uid=next(uid for uid,row in material_rows(request.output_dir).items() if 'dialogueContext' not in row)
    def mutate(conn):
        conn.execute('UPDATE content_state SET translated_text=? WHERE content_uid=?',('SYNTHETIC unbound replacement',uid))
    observer=mutate
    if phase=='rebuild':
        original=backend.convert_loca
        active=[]
        def convert(source,destination):
            if active:mutate(active[0])
            return original(source,destination)
        backend.convert_loca=convert
        observer=lambda conn:active.append(conn)
    with pytest.raises(PortableAssetsError,match='FINALIZE_SNAPSHOT_CHANGED'):
        finalize_portable_workspace(request.output_dir,tmp_path/'output',backend=backend,observer=observer)
    assert not (tmp_path/'output').exists()
    with sqlite3.connect(request.output_dir/'execution.sqlite3') as conn:
        assert conn.execute('SELECT translated_text FROM content_state WHERE content_uid=?',(uid,)).fetchone()[0]=='虛構測試譯文'


def test_windows_pins_open_reparse_points_without_following(tmp_path,monkeypatch):
    from bg3loc.sealed_snapshot import _PinnedFiles
    original=_PinnedFiles.__init__;flags=[]
    def capture(self):
        original(self)
        if not self.windows:pytest.skip('Windows handle flag test')
        create=self.kernel.CreateFileW
        def create_checked(*args):flags.append(args[5]);return create(*args)
        self.kernel=SimpleNamespace(CreateFileW=create_checked,CloseHandle=self.kernel.CloseHandle)
    monkeypatch.setattr(_PinnedFiles,'__init__',capture)
    *_,resolver,claim=resolver_fixture(tmp_path/'fixture')
    try:
        resolver.resolve(claim)
        assert flags and all(value&0x00200000 for value in flags)
    finally:resolver.close()
