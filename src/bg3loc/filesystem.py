from __future__ import annotations

from pathlib import Path
from typing import Protocol


class FileSystem(Protocol):
    def exists(self, path: Path) -> bool: ...
    def read_bytes(self, path: Path) -> bytes: ...
    def write_bytes_atomic(self, path: Path, data: bytes) -> None: ...


class LocalFileSystem:
    def exists(self, path: Path) -> bool:
        return path.exists()

    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()

    def write_bytes_atomic(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
