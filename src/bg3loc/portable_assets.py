"""D7 closed assets. Only prepare/finalize read payload roles; no game fallback."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from contextlib import closing
import re
import shutil
import tempfile
import unicodedata

from bg3loc.backends import backend_from_probe, resolve_backend
from bg3loc.dialogue_context import canonical_bytes, fingerprint, strict_json_loads, DialogueContextValidationError
from bg3loc.dialogue_execution_contract import _frozen_schema, _StrictValidator
from bg3loc.production_workspace import sha256_file
from bg3loc.rebuilder import parse_loca_xml


class PortableAssetsError(DialogueContextValidationError, RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def reject(code):
    raise PortableAssetsError(code)


def lexical_path(value):
    if type(value) is not str or not value or any(ord(c)<32 for c in value) or any(c in value for c in "\\:"):
        reject("PATH_INVALID")
    try: value.encode("utf-8")
    except UnicodeError: reject("PATH_INVALID")
    parts=value.split("/")
    if any(not p or p in {".",".."} or p.endswith(("."," ")) or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])",p.split(".")[0]) for p in parts):
        reject("PATH_INVALID")
    return parts


def safe_file(root, value):
    root=Path(root).absolute();parts=lexical_path(value);path=root.joinpath(*parts)
    for parent in (root,*[root.joinpath(*parts[:n]) for n in range(1,len(parts)+1)]):
        try: attrs=getattr(parent.lstat(),"st_file_attributes",0)
        except OSError: reject("PORTABLE_ASSETS_INCOMPLETE")
        if parent.is_symlink() or attrs & 0x400: reject("PATH_ESCAPE_OR_LINK")
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file(): reject("PATH_ESCAPE_OR_LINK")
    return path


def collision_free(names):
    seen=set()
    for name in names:
        lexical_path(name)
        key=unicodedata.normalize("NFC",name).casefold()
        if key in seen: reject("ARCHIVE_ENTRY_COLLISION")
        seen.add(key)


def active_backend(injected=None):
    if injected is not None: return injected
    backend=backend_from_probe(resolve_backend("auto"))
    if backend is None: reject("BACKEND_UNAVAILABLE")
    return backend


def records_map(records):
    result={}
    for row in records:
        if row.content_uid in result or type(row.version) is not int or row.version<0: reject("ASSET_SEMANTIC_MISMATCH")
        result[row.content_uid]=(row.version,row.text)
    return result


def normalized_records(path, locale):
    result={}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        row=strict_json_loads(line);uid=row.get("contentUid")
        if (type(uid) is not str or not uid or uid in result or row.get("localeId")!=locale
                or type(row.get("version")) is not int or row["version"]<0 or type(row.get("text")) is not str):
            reject("ASSET_SEMANTIC_MISMATCH")
        result[uid]=(row["version"],row["text"])
    if not result: reject("PORTABLE_ASSETS_INCOMPLETE")
    return result


def read_version_index(path):
    result={};previous=""
    for line in path.read_text(encoding="utf-8").splitlines():
        row=strict_json_loads(line)
        if (type(row) is not dict or set(row)!={"contentUid","version"} or type(row["contentUid"]) is not str
                or row["contentUid"]<=previous or type(row["version"]) is not int or row["version"]<0): reject("ASSET_SEMANTIC_MISMATCH")
        previous=row["contentUid"];result[previous]=row["version"]
    if not result: reject("PORTABLE_ASSETS_INCOMPLETE")
    return result


def _snapshot(root, source):
    before=sha256_file(source);size=source.stat().st_size
    relative=f"inputs/finalize-assets/objects/{before}.bin";target=root/relative
    current=root
    for part in lexical_path(relative)[:-1]:
        current=current/part
        if current.exists() and (current.is_symlink() or getattr(current.lstat(),"st_file_attributes",0)&0x400): reject("PATH_ESCAPE_OR_LINK")
        current.mkdir(exist_ok=True)
    if target.is_symlink(): reject("PATH_ESCAPE_OR_LINK")
    if not target.exists(): shutil.copyfile(source,target)
    if sha256_file(source)!=before or sha256_file(target)!=before or target.stat().st_size!=size: reject("ASSET_HASH_MISMATCH")
    return {"path":relative,"sha256":before,"size":size}


def _version_snapshot(root, records, directory, name):
    path=directory/name
    path.write_bytes(b"".join(canonical_bytes({"contentUid":uid,"version":value[0]})+b"\n" for uid,value in sorted(records.items())))
    return _snapshot(root,path)


def create_finalize_assets(root, *, source_snapshot, target_snapshot, target_xml, target_loca,
                           target_package, loca_entry, source_locale, target_locale, origin_extract_sha256, backend=None):
    root=Path(root);backend=active_backend(backend)
    source=normalized_records(source_snapshot,source_locale);target=normalized_records(target_snapshot,target_locale)
    baseline=records_map(parse_loca_xml(target_xml))
    if baseline!=target: reject("ASSET_SEMANTIC_MISMATCH")
    lexical_path(loca_entry);package=Path(target_package)
    collision_free([package.name])
    kind="pak" if package.suffix.casefold()==".pak" else "loca" if package.suffix.casefold()==".loca" else None
    if kind is None: reject("PORTABLE_ASSETS_INCOMPLETE")
    root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".d7-prepare-",dir=root.parent) as temp:
        directory=Path(temp)
        roundtrip=directory/"target.xml";backend.convert_loca(target_loca,roundtrip)
        if records_map(parse_loca_xml(roundtrip))!=baseline: reject("ASSET_SEMANTIC_MISMATCH")
        entries=[]
        originals=[package]
        if kind=="pak": originals+=sorted(p for p in package.parent.glob(package.stem+"_*.pak") if re.fullmatch(re.escape(package.stem)+r"_\d+\.pak",p.name))
        before={p:sha256_file(p) for p in originals}
        if kind=="pak":
            inventory=backend.list_archive(package);names=[e.path for e in inventory];collision_free(names)
            if loca_entry not in names: reject("PORTABLE_ASSETS_INCOMPLETE")
            staging=directory/"entries";backend.extract_package(package,staging)
            actual={p.relative_to(staging).as_posix():p for p in staging.rglob('*') if p.is_file()}
            if set(actual)!=set(names): reject("PORTABLE_ASSETS_INCOMPLETE")
            for e in sorted(inventory,key=lambda e:e.path):
                file=safe_file(staging,e.path)
                if type(e.size) is not int or e.size!=file.stat().st_size: reject("ASSET_HASH_MISMATCH")
                entries.append({"entryPath":e.path,"snapshot":_snapshot(root,file)})
            if sha256_file(actual[loca_entry])!=sha256_file(target_loca): reject("ASSET_SEMANTIC_MISMATCH")
        else:
            if sha256_file(package)!=sha256_file(target_loca): reject("ASSET_SEMANTIC_MISMATCH")
            entries=[{"entryPath":loca_entry,"snapshot":_snapshot(root,package)}]
        if any(sha256_file(p)!=seal for p,seal in before.items()): reject("ASSET_HASH_MISMATCH")
        bundle={"schemaVersion":"production-finalize-assets/1","pathPolicyVersion":"workspace-relative-path/1",
            "finalizePolicyVersion":"production-portable-finalize/1","versionIndexSchemaVersion":"localization-version-index/1",
            "sourceLocale":source_locale,"targetLocale":target_locale,"originExtractManifestSha256":origin_extract_sha256,
            "sourceUidCount":len(source),"targetUidCount":len(target),
            "sourceVersionIndex":_version_snapshot(root,source,directory,"source-index.jsonl"),
            "targetVersionIndex":_version_snapshot(root,target,directory,"target-index.jsonl"),
            "targetBaselineXml":_snapshot(root,Path(target_xml)),"targetBaselineLoca":_snapshot(root,Path(target_loca)),
            "targetPackage":{"kind":kind,"originalPackageName":package.name,"locaEntry":loca_entry,"entries":entries}}
        bundle["assetFingerprint"]=fingerprint(bundle)
        path=root/"inputs/finalize-assets/manifest.json";path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(canonical_bytes(bundle)+b"\n")
    descriptor={"path":"inputs/finalize-assets/manifest.json","sha256":sha256_file(path),"assetFingerprint":bundle["assetFingerprint"]}
    verify_finalize_assets(root,descriptor,backend=backend)
    return descriptor


@dataclass(frozen=True,slots=True)
class PortableAssetView:
    bundle: dict
    source_versions: dict
    target_versions: dict
    baseline: tuple
    fingerprint: str


def verify_finalize_assets(root, descriptor, *, backend=None):
    backend=active_backend(backend);root=Path(root)
    path=safe_file(root,descriptor["path"])
    if sha256_file(path)!=descriptor["sha256"]: reject("ASSET_HASH_MISMATCH")
    bundle=strict_json_loads(path.read_bytes())
    try: _StrictValidator(_frozen_schema("production-finalize-assets-v1.schema.json")).validate(bundle)
    except Exception: reject("PORTABLE_ASSETS_INCOMPLETE")
    if fingerprint({k:v for k,v in bundle.items() if k!="assetFingerprint"})!=bundle["assetFingerprint"] or bundle["assetFingerprint"]!=descriptor["assetFingerprint"]: reject("ASSET_HASH_MISMATCH")
    entries=bundle["targetPackage"]["entries"];names=[e["entryPath"] for e in entries]
    collision_free(names)
    if names!=sorted(names) or bundle["targetPackage"]["locaEntry"] not in names: reject("ASSET_SEMANTIC_MISMATCH")
    name=bundle["targetPackage"]["originalPackageName"]
    if len(lexical_path(name))!=1: reject("PATH_INVALID")
    descriptors=[bundle[k] for k in ("sourceVersionIndex","targetVersionIndex","targetBaselineXml","targetBaselineLoca")]+[e["snapshot"] for e in entries]
    collision_free(sorted(set(d["path"] for d in descriptors)))
    for d in descriptors:
        file=safe_file(root,d["path"])
        if file.stat().st_size!=d["size"] or sha256_file(file)!=d["sha256"]: reject("ASSET_HASH_MISMATCH")
    source=read_version_index(safe_file(root,bundle["sourceVersionIndex"]["path"]));target=read_version_index(safe_file(root,bundle["targetVersionIndex"]["path"]))
    baseline=parse_loca_xml(safe_file(root,bundle["targetBaselineXml"]["path"]))
    if len(source)!=bundle["sourceUidCount"] or len(target)!=bundle["targetUidCount"] or {u:v[0] for u,v in records_map(baseline).items()}!=target: reject("ASSET_SEMANTIC_MISMATCH")
    entry=next(e for e in entries if e["entryPath"]==bundle["targetPackage"]["locaEntry"])
    if entry["snapshot"]["sha256"]!=bundle["targetBaselineLoca"]["sha256"]: reject("ASSET_SEMANTIC_MISMATCH")
    if bundle["targetPackage"]["kind"]=="loca" and len(entries)!=1: reject("ASSET_SEMANTIC_MISMATCH")
    with tempfile.TemporaryDirectory(prefix=".d7-verify-") as temp:
        xml=Path(temp)/"reread.xml";loca=Path(temp)/"target.loca"
        shutil.copyfile(safe_file(root,bundle["targetBaselineLoca"]["path"]),loca)
        if sha256_file(loca)!=bundle["targetBaselineLoca"]["sha256"]: reject("ASSET_HASH_MISMATCH")
        backend.convert_loca(loca,xml)
        if records_map(parse_loca_xml(xml))!=records_map(baseline): reject("ASSET_SEMANTIC_MISMATCH")
    for d in descriptors:
        if sha256_file(safe_file(root,d["path"]))!=d["sha256"]: reject("ASSET_HASH_MISMATCH")
    return PortableAssetView(bundle,source,target,tuple(baseline),bundle["assetFingerprint"])
