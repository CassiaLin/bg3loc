"""Synthetic scan package bindings; no game data or provider transport."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import os
import zipfile
from unittest.mock import patch

import pytest

from bg3loc.cli import main
from bg3loc.extractor import ExtractFailure, ExtractRequest, run_extract
from test_locale_material_integrity import installed_game, backend_scope


def scanned(root):
    game = installed_game(root)
    scan = root / "scan/scan-manifest.json"
    with backend_scope():
        assert main(["scan", "--game-dir", str(game), "--output", str(scan.parent)]) == 0
    return game, scan


def replace_valid_package(package, *, in_place=False):
    with zipfile.ZipFile(package) as archive:
        entries = [(info.filename, archive.read(info.filename)) for info in archive.infolist()]
    changed = package.with_name(package.name + ".replacement")
    with zipfile.ZipFile(changed, "w") as archive:
        for name, data in entries:
            # Same UTF-8 length, valid XML, valid package. Never rely on size alone.
            data = data.replace(b"Hello", b"Hallo").replace(b"Bonjour", b"Bonzour").replace(b"Hallo", b"Hullo")
            archive.writestr(name, data)
    assert changed.stat().st_size == package.stat().st_size
    if in_place:
        package.write_bytes(changed.read_bytes())
        changed.unlink()
    else:
        changed.replace(package)


@pytest.mark.parametrize("locale", ("English", "French", "German"))
@pytest.mark.parametrize("in_place", (False, True))
def test_old_scan_rejects_valid_same_size_changed_packages_without_output(tmp_path, locale, in_place):
    game, scan = scanned(tmp_path)
    package = game / "Data/Localization" / (locale + ".pak")
    replace_valid_package(package, in_place=in_place)
    output = tmp_path / "must-not-publish"
    with backend_scope(), pytest.raises(ExtractFailure, match="scan"):
        run_extract(ExtractRequest(scan, "english", "french", ("german",), output))
    assert not output.exists()


def test_unchanged_non_steam_unknown_build_scan_extract_build(tmp_path):
    game, scan = scanned(tmp_path)
    manifest = json.loads(scan.read_text())
    assert manifest["game"]["buildId"] is None and manifest["platform"]["installKind"] == "explicit"
    output = tmp_path / "extract"
    with backend_scope():
        assert main(["extract", "--scan", str(scan), "--source", "english", "--target", "french",
                     "--reference", "german", "--output", str(output)]) == 0
    assert main(["build", "--extract", str(output / "extract-manifest.json"), "--format", "jsonl",
                 "--output", str(tmp_path / "build")]) == 0
    meta = json.loads((output / "extract-manifest.json").read_text())
    assert meta["sourceLocale"] == "English" and meta["targetLocale"] == "French"


def test_failed_late_mutation_keeps_existing_output_bytes(tmp_path):
    game, scan = scanned(tmp_path)
    output = tmp_path / "extract"
    with backend_scope():
        run_extract(ExtractRequest(scan, "English", "French", (), output))
    before = {p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    package = game / "Data/Localization/French.pak"
    replace_valid_package(package)
    with backend_scope(), pytest.raises(ExtractFailure, match="scan"):
        run_extract(ExtractRequest(scan, "English", "French", (), output))
    assert {p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()} == before


def contents(directory):
    return {p.relative_to(directory): p.read_bytes() for p in directory.rglob("*") if p.is_file()}


def nonlocking_pins(monkeypatch):
    """Exercise private-copy/check logic without Windows sharing, not native POSIX acceptance."""
    import bg3loc.source_packages as module
    def add(self, path):
        path = Path(path).absolute()
        for parent in (path, *path.parents):
            info = module.no_link(parent)
            self.paths[parent] = (info.st_dev, info.st_ino)
    monkeypatch.setattr(module._ReadPins, "add", add)


@pytest.mark.parametrize("locale", ("English", "French"))
def test_rescan_after_update_restores_legal_extraction(tmp_path, locale):
    game, scan = scanned(tmp_path)
    replace_valid_package(game / "Data/Localization" / (locale + ".pak"))
    with backend_scope():
        assert main(["scan", "--game-dir", str(game), "--output", str(scan.parent)]) == 0
        meta = run_extract(ExtractRequest(scan, "English", "French", (), tmp_path / "extract"))
    assert Path(meta["aligned"]).is_file()


def test_all_selected_packages_validate_before_first_backend_read(tmp_path):
    game, scan = scanned(tmp_path)
    replace_valid_package(game / "Data/Localization/French.pak")
    with backend_scope() as backend, patch.object(backend, "extract_single_file", wraps=backend.extract_single_file) as read:
        with pytest.raises(ExtractFailure, match="scan"):
            run_extract(ExtractRequest(scan, "English", "French", (), tmp_path / "rejected"))
        read.assert_not_called()


@pytest.mark.parametrize("problem", ("missing", "outside_data", "forged_hash", "wrong_game"))
def test_scan_path_hash_and_source_identity_fail_closed(tmp_path, problem):
    game, scan = scanned(tmp_path)
    data = json.loads(scan.read_text())
    entry = next(r for r in data["locales"] if r["localeId"] == "English")
    if problem == "missing":
        Path(entry["packageFile"]).unlink()
    elif problem == "outside_data":
        external = tmp_path / "outside.pak"; external.write_bytes(Path(entry["packageFile"]).read_bytes())
        entry["packageFile"] = str(external)
    elif problem == "forged_hash":
        entry["packageSha256"] = "0" * 64
    else:
        data["game"]["appId"] = 1
    scan.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "rejected"
    with backend_scope(), pytest.raises(ExtractFailure):
        run_extract(ExtractRequest(scan, "English", "French", (), output))
    assert not output.exists()


@pytest.mark.parametrize("phase", ("open", "backend", "conversion", "publish"))
@pytest.mark.parametrize("existing", (False, True))
def test_nonlocking_mutation_at_each_boundary_rolls_back_output(tmp_path, monkeypatch, phase, existing):
    game, scan = scanned(tmp_path)
    output = tmp_path / "extract"
    if existing:
        with backend_scope():run_extract(ExtractRequest(scan, "English", "French", (), output))
        (output / "user-notes.txt").write_text("SYNTHETIC preserve notes", encoding="utf-8")
    before = contents(output) if existing else {}
    package = game / "Data/Localization/English.pak"
    nonlocking_pins(monkeypatch)
    mutated = []
    def mutate():
        if not mutated:
            # Windows Python read streams deny DELETE independently of our pins;
            # in-place writes exercise the nonlocking content-race algorithm.
            replace_valid_package(package, in_place=True);mutated.append(True)
    with backend_scope() as backend:
        if phase == "open":
            original = Path.open
            def racing_open(self, *args, **kwargs):
                if self == package and args and args[0] == "rb":mutate()
                return original(self, *args, **kwargs)
            monkeypatch.setattr(Path, "open", racing_open)
        elif phase == "backend":
            original = backend.extract_single_file
            def racing_backend(snapshot, entry, destination):
                assert snapshot != package
                mutate();return original(snapshot, entry, destination)
            monkeypatch.setattr(backend, "extract_single_file", racing_backend)
        elif phase == "conversion":
            original = backend.convert_loca
            def racing_conversion(source, destination):
                mutate();return original(source, destination)
            monkeypatch.setattr(backend, "convert_loca", racing_conversion)
        else:
            import bg3loc.extractor as module
            original = module.os.replace
            def racing_publish(source, destination):
                result = original(source, destination)
                if Path(destination) == output:mutate()
                return result
            monkeypatch.setattr(module.os, "replace", racing_publish)
        with pytest.raises(ExtractFailure, match="scan"):
            run_extract(ExtractRequest(scan, "English", "French", (), output))
    assert mutated == [True]
    assert contents(output) == before if existing else not output.exists()


def test_transient_live_package_replacement_cannot_contaminate_private_input(tmp_path, monkeypatch):
    game, scan = scanned(tmp_path)
    package = game / "Data/Localization/English.pak"
    before = package.read_bytes();nonlocking_pins(monkeypatch)
    with backend_scope() as backend:
        original = backend.extract_single_file
        def transient(snapshot, entry, destination):
            assert snapshot != package
            replace_valid_package(package, in_place=True)
            try:return original(snapshot, entry, destination)
            finally:package.write_bytes(before)
        monkeypatch.setattr(backend, "extract_single_file", transient)
        with pytest.raises(ExtractFailure, match="scan"):
            run_extract(ExtractRequest(scan, "English", "French", (), tmp_path / "rejected"))
    assert not (tmp_path / "rejected").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows deny-write/delete handles")
def test_windows_denies_live_and_snapshot_writes_and_replacements(tmp_path):
    game, scan = scanned(tmp_path)
    original_package = game / "Data/Localization/English.pak"
    attempts = []
    with backend_scope() as backend:
        read = backend.extract_single_file
        def blocked(snapshot, entry, destination):
            for path in [original_package, snapshot]:
                with pytest.raises(PermissionError):path.write_bytes(b"SYNTHETIC mutation")
                substitute = tmp_path / "substitute.pak";substitute.write_bytes(path.read_bytes())
                with pytest.raises(PermissionError):substitute.replace(path)
            attempts.append(True)
            return read(snapshot, entry, destination)
        with patch.object(backend, "extract_single_file", side_effect=blocked):
            meta = run_extract(ExtractRequest(scan, "English", "French", (), tmp_path / "extract"))
    assert len(attempts) == 2 and Path(meta["aligned"]).is_file()


@pytest.mark.parametrize("existing", (False, True))
def test_late_backend_failure_keeps_output_unpublished(tmp_path, existing):
    game, scan = scanned(tmp_path);output = tmp_path / "extract"
    if existing:
        with backend_scope():run_extract(ExtractRequest(scan, "English", "French", (), output))
    before = contents(output) if existing else {}
    with backend_scope() as backend:
        convert = backend.convert_loca;calls = []
        def fail(source, destination):
            calls.append(True)
            if len(calls) == 4:
                from bg3loc.backends import ArchiveBackendError
                raise ArchiveBackendError("SYNTHETIC late conversion failure")
            return convert(source, destination)
        with patch.object(backend, "convert_loca", side_effect=fail),pytest.raises(ExtractFailure):
            run_extract(ExtractRequest(scan, "English", "French", (), output))
    assert contents(output) == before if existing else not output.exists()


def test_refresh_preserves_notes_unselected_files_and_logical_paths(tmp_path):
    game, scan = scanned(tmp_path);output = tmp_path / "extract"
    with backend_scope():first = run_extract(ExtractRequest(scan, "English", "French", ("German",), output))
    extra = output / "user-note.txt";extra.write_text("SYNTHETIC note", encoding="utf-8")
    german = (output / "normalized/German.jsonl").read_bytes()
    with backend_scope():second = run_extract(ExtractRequest(scan, "English", "French", (), output))
    assert extra.read_text() == "SYNTHETIC note" and (output / "normalized/German.jsonl").read_bytes() == german
    assert second["locales"][:2] == first["locales"][:2]
    assert "extract-stage-" not in json.dumps(second)


def test_snapshot_after_close_is_rejected(tmp_path):
    game, scan = scanned(tmp_path)
    from bg3loc.source_packages import ScanPackageSnapshot, SourcePackageError
    data = json.loads(scan.read_text())
    snapshots = ScanPackageSnapshot(data, [(r["localeId"], r) for r in data["locales"]], tmp_path / "private")
    snapshots.close()
    with pytest.raises(SourcePackageError, match="closed"):snapshots.path("English")
    with pytest.raises(SourcePackageError, match="closed"):snapshots.verify()


@pytest.mark.parametrize("existing", (False, True))
def test_atomic_rename_failure_restores_previous_output(tmp_path, monkeypatch, existing):
    game, scan = scanned(tmp_path);output = tmp_path / "extract"
    if existing:
        with backend_scope():run_extract(ExtractRequest(scan, "English", "French", (), output))
    before = contents(output) if existing else {}
    import bg3loc.extractor as module
    replace = module.os.replace
    def fail_publish(source, destination):
        if Path(destination) == output and "extract-stage-" in str(source):
            raise OSError("SYNTHETIC publication failure")
        return replace(source, destination)
    monkeypatch.setattr(module.os, "replace", fail_publish)
    with backend_scope(),pytest.raises(ExtractFailure, match="publication failure"):
        run_extract(ExtractRequest(scan, "English", "French", (), output))
    assert contents(output) == before if existing else not output.exists()


def test_failed_rollback_keeps_recoverable_old_output(tmp_path, monkeypatch):
    game, scan = scanned(tmp_path);output = tmp_path / "extract"
    with backend_scope():run_extract(ExtractRequest(scan, "English", "French", (), output))
    before = contents(output)
    import bg3loc.extractor as module
    replace = module.os.replace
    def failed_restore(source, destination):
        if Path(destination) == output:
            raise OSError("SYNTHETIC publication and restore failure")
        return replace(source, destination)
    monkeypatch.setattr(module.os, "replace", failed_restore)
    with backend_scope(),pytest.raises(ExtractFailure, match="recovery preserved"):
        run_extract(ExtractRequest(scan, "English", "French", (), output))
    recoveries = list(tmp_path.glob("extract-previous-*/output"))
    assert len(recoveries) == 1 and contents(recoveries[0]) == before


@pytest.mark.skipif(os.name != "nt", reason="Windows writer-sharing preflight")
def test_preexisting_write_owner_blocks_capture_without_publishing(tmp_path):
    game, scan = scanned(tmp_path);package = game / "Data/Localization/English.pak"
    output = tmp_path / "rejected"
    with package.open("r+b"),backend_scope(),pytest.raises(ExtractFailure, match="scan"):
        run_extract(ExtractRequest(scan, "English", "French", (), output))
    assert not output.exists()
