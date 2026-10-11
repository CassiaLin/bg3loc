"""Invented, self-contained ZIP-backed PAKs; never real game content."""
from pathlib import Path
from contextlib import nullcontext
import hashlib
import shutil
import zipfile
from unittest.mock import patch

import pytest

from bg3loc.backends import ArchiveEntry, ArchiveBackendError
from bg3loc.rebuilder import repack_target_package, run_rebuild, RebuildRequest, RebuildFailure

LOCA = 'Localization/French/french.loca'
PAYLOADS = {
    'Public/Fixture/a.bin': b'\x00\xff\x01\x80',
    'Public/Fixture/nested/b.txt': b'invented opaque payload',
    'metadata.json': b'{"fixture":true}',
    'empty.bin': b'',
    'Localization/Other/other.loca': b'unchanged other-language opaque bytes',
}
BASELINE = b'<contentList><content contentuid="fictional-uid" version="1">Old</content></contentList>'
REPLACEMENT = b'<contentList><content contentuid="fictional-uid" version="2">New {TARGET}</content></contentList>'


def make_package(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as archive:
        for name, payload in rows:
            archive.writestr(name, payload)


class ZipBackend:
    id = 'fictional-zip'

    def __init__(self, mutation=None):
        self.mutation = mutation

    def list_archive(self, package, expression='*'):
        with zipfile.ZipFile(package) as archive:
            return [ArchiveEntry(info.filename, info.file_size, info.CRC) for info in archive.infolist()]

    def extract_package(self, package, destination):
        with zipfile.ZipFile(package) as archive:
            archive.extractall(destination)

    def extract_single_file(self, package, packaged_path, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(package) as archive:
            destination.write_bytes(archive.read(packaged_path))

    def create_package(self, source_dir, destination):
        rows = [(p.relative_to(source_dir).as_posix(), p.read_bytes())
                for p in sorted(source_dir.rglob('*')) if p.is_file()]
        if self.mutation:
            rows = self.mutation(rows)
        make_package(destination, rows)

    def convert_loca(self, source, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def fixture(tmp_path):
    source = tmp_path / 'source.pak'
    make_package(source, [(LOCA, BASELINE), *PAYLOADS.items()])
    replacement = tmp_path / 'rebuilt.loca'
    replacement.write_bytes(REPLACEMENT)
    return source, replacement, tmp_path / 'artifacts/result.pak', tmp_path / 'stage'


def invoke(backend, files):
    source, replacement, destination, staging = files
    repack_target_package(backend, target_package=source, loca_entry=LOCA,
                          rebuilt_loca=replacement, destination=destination, staging_root=staging)


@pytest.mark.parametrize('entry', list(PAYLOADS))
def test_each_untouched_entry_corruption_is_rejected_without_publication(tmp_path, entry):
    def corrupt(rows):
        return [(n, (b'x' * len(data) if data else b'x') if n == entry else data) for n, data in rows]
    files = fixture(tmp_path)
    with pytest.raises(ValueError):
        invoke(ZipBackend(corrupt), files)
    assert not files[2].exists()
    assert files[0].is_file()


def test_all_untouched_entries_and_replacement_match(tmp_path):
    files = fixture(tmp_path)
    before = files[0].read_bytes()
    invoke(ZipBackend(), files)
    with zipfile.ZipFile(files[2]) as archive:
        assert set(archive.namelist()) == {LOCA, *PAYLOADS}
        assert archive.read(LOCA) == REPLACEMENT
        for name, payload in PAYLOADS.items():
            assert hashlib.sha256(archive.read(name)).digest() == hashlib.sha256(payload).digest()
    assert files[0].read_bytes() == before


@pytest.mark.parametrize('attack', ['missing', 'extra', 'duplicate', 'case-collision', 'renamed-case', 'file-directory', 'loca'])
def test_bad_entry_inventory_or_loca_preserves_existing_destination(tmp_path, attack):
    def change(rows):
        if attack == 'missing':
            return rows[:-1]
        if attack == 'extra':
            return rows + [('added.txt', b'added')]
        if attack == 'duplicate':
            return rows + [rows[-1]]
        if attack == 'case-collision':
            return rows + [('METADATA.JSON', b'collision')]
        if attack == 'renamed-case':
            return [(n.upper() if n == 'metadata.json' else n, p) for n, p in rows]
        if attack == 'file-directory':
            return rows + [('Public', b'collision')]
        return [(n, BASELINE if n == LOCA else p) for n, p in rows]
    files = fixture(tmp_path)
    files[2].parent.mkdir()
    files[2].write_bytes(b'previous verified artifact')
    with pytest.raises(ValueError):
        invoke(ZipBackend(change), files)
    assert files[2].read_bytes() == b'previous verified artifact'


def test_create_failure_never_replaces_existing_artifact(tmp_path):
    class Failing(ZipBackend):
        def create_package(self, source, destination):
            destination.write_bytes(b'partial package')
            raise ArchiveBackendError('invented create failure')
    files = fixture(tmp_path)
    files[2].parent.mkdir()
    files[2].write_bytes(b'previous verified artifact')
    with pytest.raises(ArchiveBackendError):
        invoke(Failing(), files)
    assert files[2].read_bytes() == b'previous verified artifact'


@pytest.mark.parametrize('bad', ['metadata.json', 'METADATA.JSON', 'Public',
    '../escape', '/absolute', 'Public/./alias', 'Public//alias', 'Public/trailing.',
    'Public/trailing ', 'Public/NUL.txt', 'Public/x:stream', 'Public/x?.bin'])
def test_bad_original_inventory_rejected_before_extraction(tmp_path, bad):
    files = fixture(tmp_path)
    with pytest.warns(UserWarning) if bad == 'metadata.json' else nullcontext():
        make_package(files[0], [(LOCA, BASELINE), *PAYLOADS.items(), (bad, b'invented')])
    backend = ZipBackend()
    with patch.object(backend, 'extract_package', side_effect=AssertionError('must preflight inventory')):
        with pytest.raises(ValueError):
            invoke(backend, files)
    assert not files[2].exists()


def test_output_semantic_mismatch_rejected_even_with_matching_loca_bytes(tmp_path):
    class WrongSemantic(ZipBackend):
        def convert_loca(self, source, destination):
            super().convert_loca(source, destination)
            if 'verify' in source.parts:
                destination.write_bytes(destination.read_bytes().replace(b'version="2"', b'version="99"'))
    files = fixture(tmp_path)
    with pytest.raises(ValueError, match='semantic mismatch'):
        invoke(WrongSemantic(), files)
    assert not files[2].exists()


@pytest.mark.parametrize('mutated', ['source', 'replacement', 'candidate'])
def test_input_or_candidate_mutation_before_publication_is_rejected(tmp_path, mutated):
    files = fixture(tmp_path)
    class Mutates(ZipBackend):
        def create_package(self, source_dir, destination):
            super().create_package(source_dir, destination)
            if mutated == 'source':
                files[0].write_bytes(files[0].read_bytes() + b'mutated')
            if mutated == 'replacement':
                files[1].write_bytes(files[1].read_bytes() + b'mutated')

        def extract_package(self, package, destination):
            super().extract_package(package, destination)
            if mutated == 'candidate' and '.bg3loc-repack-' in str(package.parent):
                package.write_bytes(package.read_bytes() + b'mutated')
    with pytest.raises(ValueError, match='changed before publication'):
        invoke(Mutates(), files)
    assert not files[2].exists()


@pytest.mark.parametrize('change', ['missing', 'extra', 'corrupt'])
def test_full_extraction_must_agree_with_listed_inventory_and_captured_hashes(tmp_path, change):
    files = fixture(tmp_path)
    class Inconsistent(ZipBackend):
        def extract_package(self, package, destination):
            super().extract_package(package, destination)
            if '.bg3loc-repack-' in str(package.parent):
                if change == 'missing':
                    (destination / 'metadata.json').unlink()
                elif change == 'extra':
                    (destination / 'unexpected.txt').write_bytes(b'invented')
                else:
                    (destination / 'metadata.json').write_bytes(b'bad extraction')
    with pytest.raises(ValueError):
        invoke(Inconsistent(), files)
    assert not files[2].exists()


def test_atomic_publish_failure_preserves_previous_bytes(tmp_path):
    files = fixture(tmp_path)
    files[2].parent.mkdir()
    files[2].write_bytes(b'previous bytes')
    with patch.object(Path, 'replace', side_effect=OSError('invented publish failure')):
        with pytest.raises(OSError):
            invoke(ZipBackend(), files)
    assert files[2].read_bytes() == b'previous bytes'
    assert not list(files[2].parent.glob('.bg3loc-repack-*'))


def test_original_package_cannot_be_destination(tmp_path):
    files = fixture(tmp_path)
    original = files[0].read_bytes()
    with pytest.raises(ValueError):
        invoke(ZipBackend(), (files[0], files[1], files[0], files[3]))
    assert files[0].read_bytes() == original


def test_damaged_original_full_extraction_cannot_certify_its_own_hashes(tmp_path):
    files = fixture(tmp_path)
    class BadOriginalRead(ZipBackend):
        def extract_package(self, package, destination):
            super().extract_package(package, destination)
            if package.parent.name == 'source':
                (destination / 'metadata.json').write_bytes(b'wrong baseline payload')
    with pytest.raises(ValueError, match='Original PAK extraction SHA256 mismatch'):
        invoke(BadOriginalRead(), files)
    assert not files[2].exists()


def test_low_level_rebuild_failure_publishes_no_pak_or_manifest(tmp_path):
    import test_rebuild as legacy_fixture
    validate, extract, source = legacy_fixture.RebuildV1Tests()._fixture(tmp_path)
    def corrupt(rows):
        return [(name, b'bad metadata' if name == 'metadata.txt' else data) for name, data in rows]
    output = tmp_path / 'rebuild'
    with pytest.raises(RebuildFailure) as caught:
        run_rebuild(RebuildRequest(validate, extract, container='repack', output=output), ZipBackend(corrupt))
    assert caught.value.exit_code == 48
    assert caught.value.key == 'CONTAINER_REPACK_FAILED'
    assert not (output / 'artifacts' / source.name).exists()
    assert not (output / 'rebuild-manifest.json').exists()
