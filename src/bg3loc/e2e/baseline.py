"""CCR-B1-01: scan-rooted Basic evidence and operation-scoped private inputs.

No execution identity, SQLite policy, global cache or historical receipt backfill.
"""
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile

from bg3loc.backends import ArchiveBackendError
from bg3loc import extractor as origin
from jsonschema.exceptions import ValidationError
from bg3loc.extractor import (ExtractRequest, ExtractFailure, _extract_verified, _index_locales,
    _resolve_primary_loca_entry, material_locale_roles, normalize_loca_xml,
    resolve_locale_roles, align_locales)
from bg3loc.io import write_json
from bg3loc.schema import SchemaStore
from bg3loc.source_packages import _ReadPins, ScanPackageSnapshot

VERSION = 'basic-source-baseline/1'
RECEIPT_PATH = 'internal/bindings/basic-source-baseline.json'
GUIDANCE = 'Basic source/baseline integrity failed; rerun Scan / Extract / Prepare / Validate in a fresh workspace; preserve edited returns'

def _unique(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ValueError('Duplicate baseline JSON field')
        value[key]=item
    return value

def _constant(value):raise ValueError('Nonfinite baseline JSON number')
def _json(raw):return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique, parse_constant=_constant)
def _same(left,right):return json.dumps(left,sort_keys=True)==json.dumps(right,sort_keys=True)
def _sha(raw):return hashlib.sha256(raw).hexdigest()
def _file_sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()
def _rows(path):return [_json(line.encode('utf-8')) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]

@dataclass(frozen=True)
class _File:
    role: str
    locale: str | None
    original: Path
    private: Path
    size: int
    digest: str

class BasicSourceSnapshot:
    """Pins and hashes originals AND snapshots until the operation completes."""
    def __init__(self, scan_path, extract_path, scan_sha, extract_sha, *, receipt=None):
        self._stack=ExitStack();self._pins=_ReadPins();self._files=[];self._closed=False
        try:
            self.directory=Path(self._stack.enter_context(tempfile.TemporaryDirectory(prefix='basic-baseline-')))
            self._stack.callback(self._pins.close)
            scan_path=Path(scan_path).absolute();extract_path=Path(extract_path).absolute()
            scan_file=self._capture('scan',None,scan_path,scan_sha)
            extract_file=self._capture('extract',None,extract_path,extract_sha)
            self.scan=_json(scan_file.private.read_bytes());self.extract=_json(extract_file.private.read_bytes())
            SchemaStore().validate('scan.schema.json',self.scan)
            SchemaStore().validate('extract-manifest.schema.json',self.extract)
            self.roles=material_locale_roles(self.extract)
            if resolve_locale_roles(self.scan,self.roles)!=self.roles:raise ValueError('Noncanonical locale roles')
            if self._reference(self.extract['scanManifest'],extract_path.parent)!=scan_path:raise ValueError('Extract belongs to a different scan')
            inventory=_index_locales(self.scan)
            selected=[(role,inventory[role.casefold()]) for role in self.roles]
            self.packages=self._stack.enter_context(ScanPackageSnapshot(self.scan,selected,self.directory/'pak-capture'))
            if len(self.extract['locales'])!=len(self.roles):raise ValueError('Incomplete or duplicate extract locale set')
            infos={r['localeId']:r for r in self.extract['locales']}
            if set(infos)!=set(self.roles):raise ValueError('Extract role mismatch')
            for role,entry in selected:
                info=infos[role]
                pak=Path(entry['packageFile']).absolute()
                if self._reference(info['packageFile'],extract_path.parent)!=pak:raise ValueError('Package identity mismatch')
                if info['locaEntry']!=_resolve_primary_loca_entry(entry,role):raise ValueError('LOCA entry identity mismatch')
                self._capture('pak',role,pak,entry['packageSha256'].lower(),source=self.packages.path(role))
                for label,key in [('normalized','normalized'),('xml','sourceXml'),('loca','sourceLoca')]:
                    self._capture(label,role,self._reference(info[key],extract_path.parent))
            self._capture('aligned',None,self._reference(self.extract['aligned'],extract_path.parent))
            self._receipt=dict(contractVersion=VERSION,scanManifestSha256=scan_sha,extractManifestSha256=extract_sha,
                sourceLocale=self.roles[0],targetLocale=self.roles[1],referenceLocales=self.roles[2:],
                files=[dict(role=f.role,localeId=f.locale,path=str(f.original),sizeBytes=f.size,sha256=f.digest)
                       for f in sorted(self._files,key=lambda f:(f.role,f.locale or ''))])
            SchemaStore().validate('basic-source-baseline-v1.schema.json',self._receipt)
            if receipt is not None:
                SchemaStore().validate('basic-source-baseline-v1.schema.json',receipt)
                if not _same(receipt,self._receipt):raise ValueError('Prepared receipt no longer matches source/baseline files')
            # Reprove origin from the scan-rooted PAK, including on consumption.
            # A schema-valid receipt is not itself evidence that its producer was trusted.
            proof=self.directory/'origin';proof.mkdir()
            backend=origin.backend_from_manifest(self.scan['backend'])
            if backend is None:raise ValueError('Missing backend for prepare-time origin proof')
            derived=_extract_verified(ExtractRequest(scan_path,self.roles[0],self.roles[1],tuple(self.roles[2:]),proof),
                self.scan,selected,backend,proof,self.packages)
            normalized={}
            for role in self.roles:
                known=next(r for r in derived['locales'] if r['localeId']==role)
                expected=_rows(Path(known['normalized']))
                if infos[role]['nodeCount']!=len(expected):raise ValueError('Incomplete locale node count')
                if not _same(_rows(self.file('normalized',role)),expected):raise ValueError('Normalized source/version does not derive from recorded PAK')
                actual=normalize_loca_xml(self.file('xml',role),locale_id=role,
                    source_package=infos[role]['packageFile'],source_loca_entry=infos[role]['locaEntry'])
                if not _same(actual,expected):raise ValueError('XML baseline does not derive from recorded PAK')
                if _file_sha(self.file('loca',role))!=_file_sha(Path(known['sourceLoca'])):raise ValueError('LOCA baseline differs from recorded PAK')
                normalized[role]=expected
            if not _same(_rows(self.file('aligned')),align_locales(normalized)):raise ValueError('Aligned material does not derive from recorded PAK')
            self.private_extract=self.directory/'rebuild-extract.json'
            projection=json.loads(json.dumps(self.extract))
            for info in projection['locales']:
                role=info['localeId']
                for key,label in [('packageFile','pak'),('sourceXml','xml'),('sourceLoca','loca'),('normalized','normalized')]:
                    info[key]=str(self.file(label,role))
            projection['aligned']=str(self.file('aligned'))
            projection['scanManifest']=str(self.file('scan'))
            write_json(self.private_extract,projection);self._pins.add(self.private_extract)
            self._projection_sha=_file_sha(self.private_extract)
            self.check()
        except BaseException:
            self.close();raise

    @staticmethod
    def _reference(raw,base):
        path=Path(raw).expanduser()
        return path.absolute() if path.is_absolute() else (base/path).absolute()

    def _capture(self,role,locale,path,expected=None,*,source=None):
        self._pins.add(path)
        private=self.directory/'files'/f'{len(self._files):04d}'/path.name
        private.parent.mkdir(parents=True)
        shutil.copyfile(source or path,private)
        digest=_file_sha(private)
        if expected is not None and digest!=expected:raise ValueError('Recorded manifest/package SHA mismatch')
        if _file_sha(path)!=digest:raise ValueError('Source changed during capture')
        self._pins.add(private)
        item=_File(role,locale,path,private,private.stat().st_size,digest);self._files.append(item)
        return item

    def file(self,role,locale=None):
        if self._closed:raise ValueError('Baseline snapshot is closed')
        return next(f.private for f in self._files if (f.role,f.locale)==(role,locale))

    @property
    def receipt(self):return json.loads(json.dumps(self._receipt))

    def check(self):
        if self._closed:raise ValueError('Baseline snapshot is closed')
        self._pins.check();self.packages.verify()
        for item in self._files:
            for path in (item.original,item.private):
                if path.stat().st_size!=item.size or _file_sha(path)!=item.digest:raise ValueError('Baseline changed during operation')
        if hasattr(self,'_projection_sha') and _file_sha(self.private_extract)!=self._projection_sha:raise ValueError('Private extract projection changed')

    def restore_rebuild_provenance(self,manifest):
        """Keep existing public manifest path semantics; no dangling private paths."""
        manifest['extractManifest']=str(next(f.original for f in self._files if f.role=='extract'))
        target=next(r for r in self.extract['locales'] if r['localeId']==self.roles[1])
        manifest['baseline']['packageFile']=target['packageFile']
        manifest['baseline']['sourceXml']=target['sourceXml']

    @contextmanager
    def installation_guard(self):
        """Transfer source pins; the installer must be able to replace target PAK.

        The existing installer independently verifies/backs up its target. All
        other original input files stay pinned, with unchanged receipt hashes.
        This is not a game-wide update lock or an installer policy replacement.
        """
        self.check()
        files=tuple(f for f in self._files if not (f.role=='pak' and f.locale==self.roles[1]))
        pins=_ReadPins()
        def check():
            pins.check()
            for f in files:
                if f.original.stat().st_size!=f.size or _file_sha(f.original)!=f.digest:
                    raise ValueError('Source/baseline changed during installation')
        try:
            for f in files:pins.add(f.original)
            check()
            self.close()
            self._installation_handoff=True
            yield
            check()
        finally:pins.close()

    def close(self):
        self._stack.close();self._closed=True
    def __enter__(self):return self
    def __exit__(self,kind,value,traceback):
        try:
            if kind is None and not getattr(self,'_installation_handoff',False):self.check()
        finally:self.close()

@contextmanager
def prepare_baseline(state):
    try:
        with BasicSourceSnapshot(state['artifacts']['scanManifest'],state['artifacts']['extractManifest'],
                state['bindings']['scanManifestSha256'],state['bindings']['extractManifestSha256']) as snapshot:
            yield snapshot
    except (ValueError,KeyError,OSError,StopIteration,ValidationError,ExtractFailure,ArchiveBackendError) as exc:raise ValueError(f'{GUIDANCE}: {exc}') from exc

@contextmanager
def validated_baseline(config,state):
    if config.effective['workflow']['evidenceProfile']!='basic':
        yield None;return
    pins=_ReadPins()
    try:
        package_path=Path(state['artifacts']['translationPackage']).absolute();pins.add(package_path)
        raw=package_path.read_bytes()
        if _sha(raw)!=state['bindings']['translationPackageSha256']:raise ValueError('Package hash changed')
        package=_json(raw);SchemaStore().validate('translation-package.schema.json',package)
        if package['projectConfigSha256']!=config.sha256 or package['evidenceProfile']!='basic':raise ValueError('Package/project binding mismatch')
        entries=[a for a in package['internal']['bindings'] if a.get('path')==RECEIPT_PATH]
        if len(entries)!=1:raise ValueError('Required prepare-time baseline receipt missing or duplicate; no historical backfill')
        receipt_path=package_path.parent/RECEIPT_PATH;pins.add(receipt_path)
        receipt_raw=receipt_path.read_bytes()
        if _sha(receipt_raw)!=entries[0]['sha256']:raise ValueError('Baseline receipt hash changed')
        receipt=_json(receipt_raw)
        if package['sourceBinding']['extractManifestSha256']!=state['bindings']['extractManifestSha256']:raise ValueError('Extract/package binding mismatch')
        with BasicSourceSnapshot(state['artifacts']['scanManifest'],state['artifacts']['extractManifest'],
                state['bindings']['scanManifestSha256'],state['bindings']['extractManifestSha256'],receipt=receipt) as snapshot:
            if [package['sourceLocale'],package['targetLocale'],*package['referenceLocales']]!=snapshot.roles:raise ValueError('Package locale roles mismatch')
            locales=config.effective['locales']
            if resolve_locale_roles(snapshot.scan,[locales['source'],locales['target'],*locales.get('references',[])])!=snapshot.roles:
                raise ValueError('Project locale roles mismatch')
            yield snapshot
            pins.check()
            if package_path.read_bytes()!=raw or receipt_path.read_bytes()!=receipt_raw:raise ValueError('Package/receipt changed during operation')
    except (ValueError,KeyError,OSError,StopIteration,ValidationError) as exc:raise ValueError(f'{GUIDANCE}: {exc}') from exc
    finally:pins.close()
