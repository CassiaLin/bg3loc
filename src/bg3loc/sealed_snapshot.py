"""Per-run immutable validated material; no global cache or activation switch.

Windows holds deny-write/delete handles on the complete runtime file closure
and its directory chain. Other hosts rehash that closure on each use. DB remains
mutable: data_version changes trigger full input-inventory comparison, while
metadata/current claim/owner are checked in each transaction (WAL aware).
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
import ctypes
import os
import sqlite3
import stat
import threading
import hashlib

from bg3loc.dialogue_context import fail, strict_json_loads, fingerprint
from bg3loc.dialogue_execution_contract import contained_file, validate_stage2_workspace, validate_manifest_1_3
from bg3loc.production_workspace import sha256_file
from bg3loc.ruleset_io import load_ruleset
from bg3loc.translation_identity import TranslationInputParameters
from bg3loc.protected_syntax import extract_protected_tokens


class _PinnedFiles:
    def __init__(self):
        self.handles=[];self.paths=set();self.identities={};self.windows=os.name=='nt'
        if self.windows:
            self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            self.kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
            self.kernel.CreateFileW.restype=ctypes.c_void_p
            self.kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    def add(self,path):
        path=Path(path).absolute()
        for parent in reversed((path,*path.parents)):
            if parent in self.paths:continue
            info=parent.lstat()
            if parent.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:fail('CONTEXT_CONTRACT_MISMATCH')
            if self.windows:
                # Pin the named object itself, never follow a reparse point
                # substituted between lstat and CreateFileW.
                handle=self.kernel.CreateFileW(str(parent),0x80000000,1,None,3,0x00200000|(0x02000000 if parent.is_dir() else 0),None)
                if handle==ctypes.c_void_p(-1).value:fail('CONTEXT_CONTRACT_MISMATCH')
                self.handles.append(handle)
                pinned=parent.lstat()
                if stat.S_ISLNK(pinned.st_mode) or getattr(pinned,'st_file_attributes',0)&0x400:fail('CONTEXT_CONTRACT_MISMATCH')
            self.paths.add(parent)
        info=path.stat();self.identities[path]=(info.st_dev,info.st_ino,info.st_size)
    def check(self):
        for path in self.paths:
            try: info=path.lstat()
            except OSError: fail('CONTEXT_CONTRACT_MISMATCH')
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:fail('CONTEXT_CONTRACT_MISMATCH')
            identity=self.identities.get(path)
            if identity is not None and (info.st_dev,info.st_ino,info.st_size)!=identity:fail('CONTEXT_CONTRACT_MISMATCH')
    def close(self):
        if self.windows:
            for handle in reversed(self.handles):self.kernel.CloseHandle(handle)
        self.handles=[]


@dataclass(frozen=True,slots=True)
class SealedMaterialItem:
    content_uid: str
    batch_id: str
    input_hash: str
    source_text: str
    primary_category: str
    canonical_group_key: str
    context_group_keys: tuple[str,...]
    protected_tokens: tuple[str,...]
    same_entity_context: object
    dialogue_context: object

    def material_copy(self):
        row={'contentUid':self.content_uid,'batchId':self.batch_id,'sourceText':self.source_text,'primaryCategory':self.primary_category,
             'canonicalGroupKey':self.canonical_group_key,'contextGroupKeys':list(self.context_group_keys),'translationText':''}
        if self.same_entity_context is not None:row['sameEntityContext']=self.same_entity_context.to_dict()
        if self.dialogue_context is not None:row['dialogueContext']=self.dialogue_context.to_dict()
        return row


class SealedRunSnapshot:
    def __init__(self,workspace, *, input_parameters=None):
        self.root=Path(workspace).resolve();self._pins=_PinnedFiles();self._closed=False
        self._mutex=threading.RLock();self._owner_pid=os.getpid();self._db=None
        try:
            marker=self.root/'production-manifest.json';self._pins.add(marker)
            manifest_bytes=marker.read_bytes();manifest=validate_manifest_1_3(strict_json_loads(manifest_bytes))
            plan_path=contained_file(self.root,manifest['batching']['batchPlan']);self._pins.add(plan_path)
            plan_bytes=plan_path.read_bytes();plan=strict_json_loads(plan_bytes)
            paths={marker,plan_path,contained_file(self.root,manifest['inputs']['ruleset']['path']),
                   contained_file(self.root,manifest['dialogueContext']['summaryPath']),contained_file(self.root,manifest['finalizeAssets']['path']),
                   contained_file(self.root,manifest['classification']['automaticPath'])}
            if manifest['classification']['resolvedPath'] is not None:paths.add(contained_file(self.root,manifest['classification']['resolvedPath']))
            if 'sameEntityContext' in manifest:paths.add(contained_file(self.root,manifest['sameEntityContext']['summaryPath']))
            for batch in plan['batches']:
                paths.add(contained_file(self.root,plan_path.parent.relative_to(self.root).as_posix()+f"/materials/{batch['batchId']}.jsonl"))
            for path in sorted(paths):self._pins.add(path)
            before={path:sha256_file(path) for path in paths}
            before[marker]=hashlib.sha256(manifest_bytes).hexdigest()
            before[plan_path]=hashlib.sha256(plan_bytes).hexdigest()
            captured_rows=None
            if not self._pins.windows:
                # Bind decoded rows to an immutable byte capture, rather than
                # trusting only equal hashes before/after a transient read.
                from bg3loc.production_workspace import _framed_update
                captured_rows={};material_digest=hashlib.sha256()
                for batch in sorted(plan['batches'],key=lambda b:b['batchId']):
                    path=plan_path.parent/'materials'/f"{batch['batchId']}.jsonl"
                    raw=path.read_bytes();before[path]=hashlib.sha256(raw).hexdigest()
                    _framed_update(material_digest,batch['batchId'],before[path])
                    for line in raw.decode('utf-8').splitlines():
                        row=strict_json_loads(line);uid=row['contentUid']
                        if uid in captured_rows:fail('CONTEXT_CONTRACT_MISMATCH')
                        captured_rows[uid]=fingerprint(row)
                if material_digest.hexdigest()!=manifest['batching']['batchMaterialsFingerprint']:fail('CONTEXT_CONTRACT_MISMATCH')
            items={}
            def collect(row,dialogue,same,item_hash):
                if captured_rows is not None and captured_rows.get(row['contentUid'])!=fingerprint(row):fail('CONTEXT_CONTRACT_MISMATCH')
                item=SealedMaterialItem(row['contentUid'],row['batchId'],item_hash,row['sourceText'],row['primaryCategory'],row['canonicalGroupKey'],
                    tuple(row['contextGroupKeys']),tuple(extract_protected_tokens(row['sourceText'])),same,dialogue)
                items[item.content_uid]=item
            database=contained_file(self.root,manifest['execution']['database'])
            # The database is mutable, but its file identity cannot be replaced
            # beneath a persistent SQLite connection. Permit writes, deny delete.
            self._database_path=database
            info=database.stat();self._database_identity=(info.st_dev,info.st_ino)
            if self._pins.windows:
                handle=self._pins.kernel.CreateFileW(str(database),0x80000000,3,None,3,0x00200000,None)
                if handle==ctypes.c_void_p(-1).value:fail('CONTEXT_CONTRACT_MISMATCH')
                self._pins.handles.append(handle)
            self._db=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,check_same_thread=False)
            self._db.row_factory=sqlite3.Row;self._db.execute('BEGIN')
            binding=validate_stage2_workspace(self.root,_connection=self._db,_item_sink=collect,_expected_manifest=manifest)
            self._metadata=MappingProxyType(dict(self._db.execute('SELECT key,value FROM metadata')))
            self._db.commit()
            self._seals=MappingProxyType(before)
            if any(sha256_file(p)!=seal for p,seal in before.items()):fail('CONTEXT_CONTRACT_MISMATCH')
            self._pins.check()
            rules=load_ruleset(binding.ruleset)
            self.input_parameters=TranslationInputParameters(rules.version,rules.fingerprint(),rules.source_locale,rules.target_locale)
            if input_parameters is not None and input_parameters!=self.input_parameters:fail('CONTEXT_CONTRACT_MISMATCH')
            self.binding=binding;self._items=MappingProxyType(items)
            self._inventory=MappingProxyType({uid:(item.batch_id,item.input_hash) for uid,item in items.items()})
            self._data_version=None  # First use checks DB commits after startup validation.
        except BaseException:
            self.close();raise

    def _files_current(self):
        if self._closed or self._owner_pid!=os.getpid():fail('CONTEXT_CONTRACT_MISMATCH')
        self._pins.check()
        info=self._database_path.lstat()
        if (info.st_dev,info.st_ino)!=self._database_identity or self._database_path.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:
            fail('CONTEXT_CONTRACT_MISMATCH')
        if not self._pins.windows:
            if any(sha256_file(path)!=seal for path,seal in self._seals.items()):fail('CONTEXT_CONTRACT_MISMATCH')

    @property
    def items(self):return self._items

    def current_item(self,uid, *, claim=None, _connection=None, _retry=0):
        with self._mutex:
            self._files_current()
            item=self.items.get(uid)
            if item is None:fail('CONTEXT_CONTRACT_MISMATCH')
            own=_connection is None;conn=self._db if own else _connection
            if not own:
                if not conn.in_transaction:fail('CONTEXT_CONTRACT_MISMATCH')
                main=[row[2] for row in conn.execute('PRAGMA database_list') if row[1]=='main']
                if len(main)!=1 or Path(main[0]).resolve()!=self.binding.database.resolve():fail('CONTEXT_CONTRACT_MISMATCH')
                # Require a current writer barrier, including for accidentally
                # borrowed BEGIN DEFERRED/read-only snapshots. This zero-row
                # write changes no data; stale WAL readers cannot upgrade it.
                try:conn.execute('UPDATE metadata SET value=value WHERE 0')
                except sqlite3.OperationalError:fail('CONTEXT_CONTRACT_MISMATCH')
            starting_version=self._db.execute('PRAGMA data_version').fetchone()[0]
            if own:conn.execute('BEGIN')
            try:
                metadata=dict(conn.execute('SELECT key,value FROM metadata'))
                observed=self._db.execute('PRAGMA data_version').fetchone()[0]
                # A commit between the first SQLite snapshot read and the
                # generation read must not stamp old rows with a new version.
                if own and observed!=starting_version:
                    conn.commit();self._data_version=None
                    if _retry>=2:fail('CONTEXT_CONTRACT_MISMATCH')
                    return self.current_item(uid,claim=claim,_retry=_retry+1)
                if metadata!=self._metadata:fail('CONTEXT_CONTRACT_MISMATCH')
                # Every changed DB generation is checked, including foreign/missing
                # items and batch/input changes. Output/QA/attempt writes are legal.
                if not own or observed!=self._data_version:
                    inventory={key:(batch,ih) for key,batch,ih in conn.execute('SELECT content_uid,batch_id,input_hash FROM content_state')}
                    if inventory!=self._inventory:fail('CONTEXT_CONTRACT_MISMATCH')
                state=conn.execute('SELECT * FROM content_state WHERE content_uid=?',(uid,)).fetchone()
                if state is None or (state['batch_id'],state['input_hash'])!=(item.batch_id,item.input_hash):fail('CONTEXT_CONTRACT_MISMATCH')
                if claim is not None:
                    if (claim.content_uid,claim.batch_id,claim.input_hash)!=(uid,item.batch_id,item.input_hash):raise RuntimeError('claimed input identity does not match current prepared material')
                    attempt=conn.execute('SELECT * FROM attempts WHERE attempt_id=?',(claim.attempt_id,)).fetchone()
                    if state['status']=='running' or attempt is not None:
                        if (state['status']!='running' or state['last_attempt_id']!=claim.attempt_id or state['lease_owner']!=claim.lease_owner or state['lease_expires_at']!=claim.lease_expires_at
                                or attempt is None or attempt['outcome']!='running' or attempt['input_hash']!=item.input_hash
                                or attempt['content_uid']!=uid or attempt['run_id']!=claim.run_id or attempt['attempt_number']!=claim.attempt_number):
                            fail('CONTEXT_CONTRACT_MISMATCH')
                if own:conn.commit()
                if own and self._db.execute('PRAGMA data_version').fetchone()[0]!=observed:
                    self._data_version=None
                    if _retry>=2:fail('CONTEXT_CONTRACT_MISMATCH')
                    return self.current_item(uid,claim=claim,_retry=_retry+1)
                self._data_version=observed if own else None
                self._files_current()
                return item
            except BaseException:
                if own:conn.rollback()
                raise

    def close(self):
        with self._mutex:
            if getattr(self,'_db',None) is not None:self._db.close();self._db=None
            if getattr(self,'_pins',None) is not None:self._pins.close()
            self._closed=True
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
    def __del__(self):self.close()
