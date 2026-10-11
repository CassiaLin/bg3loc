"""Short-lived scan-bound package snapshots; no build-ID requirement or cache."""
from contextlib import ExitStack
from pathlib import Path
import ctypes
import hashlib
import os
import stat


class SourcePackageError(ValueError):
    pass


def mismatch(message):
    raise SourcePackageError(f"Scan package mismatch: {message}; rerun 'bg3loc scan' before extracting")


def file_identity(info):
    # Windows path/descriptor st_ctime semantics can differ immediately after
    # creation (Python 3.12 deprecates this field). SHA checks remain mandatory.
    identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    return identity if os.name == "nt" else (*identity, info.st_ctime_ns)


def no_link(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        mismatch(f"linked or substituted package path: {path}")
    return info


def stream_hash(stream):
    stream.seek(0)
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


class _ReadPins:
    def __init__(self):
        self.handles = []
        self.paths = {}
        if os.name == "nt":
            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
            self.kernel.CreateFileW.restype = ctypes.c_void_p
            self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]

    def add(self, path):
        path = Path(path).absolute()
        for parent in reversed((path, *path.parents)):
            if parent in self.paths:
                continue
            before = no_link(parent)
            if os.name == "nt":
                # Pin the named object, deny writes/deletion, and never follow a reparse point.
                directory = stat.S_ISDIR(before.st_mode)
                flags = 0x00200000 | (0x02000000 if directory else 0)
                # Directory children must remain writable for staged publication;
                # deny directory deletion, and deny both writes/deletion on files.
                sharing = 3 if directory else 1
                handle = self.kernel.CreateFileW(str(parent), 0x80000000, sharing, None, 3, flags, None)
                if handle == ctypes.c_void_p(-1).value:
                    mismatch(f"package path cannot be held read-only: {parent}")
                self.handles.append(handle)
            after = no_link(parent)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                mismatch(f"package path changed during open: {parent}")
            self.paths[parent] = (after.st_dev, after.st_ino)

    def check(self):
        for path, identity in self.paths.items():
            info = no_link(path)
            if (info.st_dev, info.st_ino) != identity:
                mismatch(f"package path identity changed: {path}")

    def close(self):
        if os.name == "nt":
            for handle in reversed(self.handles):
                self.kernel.CloseHandle(handle)
        self.handles.clear()


class ScanPackageSnapshot:
    """Backends read verified private bytes, never reopen mutable game packages.

    Windows pins both originals and private copies. Other hosts isolate copies
    in an owned directory and recheck originals/copies at extraction/publication
    boundaries. Original mutations cannot contaminate the captured input bytes.
    """
    def __init__(self, scan, selected, directory):
        self.directory = Path(directory)
        self._stack = ExitStack()
        self._pins = _ReadPins()
        self._bindings = {}
        self._closed = False
        try:
            data_root = Path(scan["game"]["dataPath"]).expanduser().resolve(strict=True)
            if not data_root.is_dir():
                mismatch("recorded game data directory is unavailable")
            self.directory.mkdir(parents=True, mode=0o700)
            for index, (locale_id, locale) in enumerate(selected):
                path = Path(locale["packageFile"]).expanduser().absolute()
                if not path.resolve(strict=True).is_relative_to(data_root):
                    mismatch(f"package is outside recorded game data: {path}")
                self._pins.add(path)
                info = no_link(path)
                if not stat.S_ISREG(info.st_mode):
                    mismatch(f"package is not a regular file: {path}")
                stream = self._stack.enter_context(path.open("rb"))
                identity = file_identity(os.fstat(stream.fileno()))
                if identity != file_identity(info):
                    mismatch(f"package changed before capture: {path}")
                captured = self.directory / f"{index:04d}.pak"
                digest = hashlib.sha256()
                with captured.open("xb") as output:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        output.write(chunk)
                        digest.update(chunk)
                expected = locale["packageSha256"].lower()
                if digest.hexdigest() != expected or file_identity(os.fstat(stream.fileno())) != identity:
                    mismatch(f"package bytes differ from scan: {path}")
                if os.name != "nt":
                    captured.chmod(0o400)
                self._pins.add(captured)
                self._bindings[locale_id] = (path, stream, identity, expected, captured)
            self.verify()
        except OSError as exc:
            self.close()
            mismatch(f"recorded package is unavailable: {exc}")
        except BaseException:
            self.close()
            raise

    def path(self, locale_id):
        if self._closed:
            mismatch("package snapshot is closed")
        return self._bindings[locale_id][4]

    def verify(self):
        try:
            self._verify()
        except OSError as exc:
            mismatch(f"package became unavailable during extraction: {exc}")

    def _verify(self):
        if self._closed:
            mismatch("package snapshot is closed")
        self._pins.check()
        for path, stream, identity, expected, captured in self._bindings.values():
            if file_identity(no_link(path)) != identity or file_identity(os.fstat(stream.fileno())) != identity:
                mismatch(f"package changed after validation: {path}")
            if stream_hash(stream) != expected:
                mismatch(f"package bytes changed after validation: {path}")
            with captured.open("rb") as snapshot:
                if stream_hash(snapshot) != expected:
                    mismatch("private package snapshot changed")
            if file_identity(no_link(path)) != identity:
                mismatch(f"package changed during validation: {path}")

    def close(self):
        self._stack.close()
        self._pins.close()
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
