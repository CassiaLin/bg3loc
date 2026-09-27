from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class BackendProbe:
    id: str
    available: bool
    version: str | None = None
    executable: Path | None = None
    assembly: Path | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    path: str
    size: int
    crc: int


class ArchiveBackendError(RuntimeError):
    pass


class ArchiveBackend(Protocol):
    id: str

    def probe(self) -> BackendProbe: ...
    def list_archive(self, package: Path, expression: str = "*") -> list[ArchiveEntry]: ...
    def extract_single_file(self, package: Path, packaged_path: str, destination: Path) -> None: ...
    def extract_package(self, package: Path, destination: Path) -> None: ...
    def create_package(self, source_dir: Path, destination: Path) -> None: ...
    def convert_loca(self, source: Path, destination: Path) -> None: ...
    def convert_resource(self, source: Path, destination: Path) -> None: ...


class LSLibWindowsExeBackend:
    id = "lslib-windows-exe"

    def __init__(self, executable: Path | None = None) -> None:
        self.executable = executable

    def probe(self) -> BackendProbe:
        candidate = self.executable or _env_path("BG3LOC_DIVINE_EXE")
        if candidate is None:
            resolved = shutil.which("Divine.exe") or shutil.which("Divine")
            candidate = Path(resolved) if resolved else None
        if candidate is None:
            return BackendProbe(
                self.id,
                False,
                reason="Divine.exe not found; set BG3LOC_DIVINE_EXE to the extracted executable path",
            )
        candidate = candidate.expanduser()
        if not candidate.is_file():
            return BackendProbe(
                self.id,
                False,
                executable=candidate,
                reason=f"BG3LOC_DIVINE_EXE does not point to a Divine.exe file: {candidate}",
            )
        return BackendProbe(self.id, True, executable=candidate.resolve())

    def _prefix(self) -> list[str]:
        probe = self.probe()
        if not probe.available or probe.executable is None:
            raise ArchiveBackendError(probe.reason or "Divine executable unavailable")
        return [str(probe.executable)]

    def list_archive(self, package: Path, expression: str = "*") -> list[ArchiveEntry]:
        completed = _run_command(self._prefix() + ["-a", "list-package", "-g", "bg3", "-s", str(package.resolve()), "-x", expression])
        return parse_list_output(completed.stdout)

    def extract_single_file(self, package: Path, packaged_path: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _run_command(self._prefix() + ["-a", "extract-single-file", "-g", "bg3", "-s", str(package.resolve()), "-d", str(destination.resolve()), "-f", packaged_path])
        if not destination.is_file():
            raise ArchiveBackendError(f"Archive extraction reported success but output is missing: {destination}")

    def extract_package(self, package: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        _run_command(self._prefix() + ["-a", "extract-package", "-g", "bg3", "-s", str(package.resolve()), "-d", str(destination.resolve())])

    def create_package(self, source_dir: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _run_command(self._prefix() + ["-a", "create-package", "-g", "bg3", "-s", str(source_dir.resolve()), "-d", str(destination.resolve())])
        if not destination.is_file():
            raise ArchiveBackendError(f"Package creation reported success but output is missing: {destination}")

    def convert_loca(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _run_command(self._prefix() + ["-a", "convert-loca", "-g", "bg3", "-s", str(source.resolve()), "-d", str(destination.resolve())])
        if not destination.is_file():
            raise ArchiveBackendError(f"LOCA conversion reported success but output is missing: {destination}")

    def convert_resource(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _run_command(self._prefix() + ["-a", "convert-resource", "-g", "bg3", "-s", str(source.resolve()), "-d", str(destination.resolve())])
        if not destination.is_file():
            raise ArchiveBackendError(f"Resource conversion reported success but output is missing: {destination}")


class LSLibDotnetCliBackend:
    id = "lslib-dotnet-cli"

    def __init__(self, assembly: Path | None = None, dotnet: Path | None = None) -> None:
        self.assembly = assembly
        self.dotnet = dotnet

    def probe(self) -> BackendProbe:
        assembly = self.assembly or _env_path("BG3LOC_DIVINE_DLL")
        if assembly is None:
            return BackendProbe(self.id, False, reason="Divine.dll path not configured")
        assembly = assembly.expanduser()
        if not assembly.is_file():
            return BackendProbe(self.id, False, assembly=assembly, reason="Divine.dll path is not a file")
        dotnet = self.dotnet
        if dotnet is None:
            resolved = shutil.which("dotnet")
            dotnet = Path(resolved) if resolved else None
        if dotnet is None or not dotnet.is_file():
            return BackendProbe(self.id, False, assembly=assembly, reason="dotnet runtime not found")
        return BackendProbe(self.id, True, executable=dotnet.resolve(), assembly=assembly.resolve())

    def _prefix(self) -> list[str]:
        probe = self.probe()
        if not probe.available or probe.executable is None or probe.assembly is None:
            raise ArchiveBackendError(probe.reason or "Divine dotnet CLI unavailable")
        return [str(probe.executable), str(probe.assembly)]

    def list_archive(self, package: Path, expression: str = "*") -> list[ArchiveEntry]:
        completed = _run_command(self._prefix() + ["-a", "list-package", "-g", "bg3", "-s", str(package.resolve()), "-x", expression])
        return parse_list_output(completed.stdout)

    def extract_single_file(self, package: Path, packaged_path: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _run_command(self._prefix() + ["-a", "extract-single-file", "-g", "bg3", "-s", str(package.resolve()), "-d", str(destination.resolve()), "-f", packaged_path])
        if not destination.is_file():
            raise ArchiveBackendError(f"Archive extraction reported success but output is missing: {destination}")

    def extract_package(self, package: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        _run_command(self._prefix() + ["-a", "extract-package", "-g", "bg3", "-s", str(package.resolve()), "-d", str(destination.resolve())])

    def create_package(self, source_dir: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _run_command(self._prefix() + ["-a", "create-package", "-g", "bg3", "-s", str(source_dir.resolve()), "-d", str(destination.resolve())])
        if not destination.is_file():
            raise ArchiveBackendError(f"Package creation reported success but output is missing: {destination}")

    def convert_loca(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _run_command(self._prefix() + ["-a", "convert-loca", "-g", "bg3", "-s", str(source.resolve()), "-d", str(destination.resolve())])
        if not destination.is_file():
            raise ArchiveBackendError(f"LOCA conversion reported success but output is missing: {destination}")

    def convert_resource(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _run_command(self._prefix() + ["-a", "convert-resource", "-g", "bg3", "-s", str(source.resolve()), "-d", str(destination.resolve())])
        if not destination.is_file():
            raise ArchiveBackendError(f"Resource conversion reported success but output is missing: {destination}")


def backend_from_probe(probe: BackendProbe) -> ArchiveBackend | None:
    if not probe.available:
        return None
    if probe.id == "lslib-windows-exe" and probe.executable is not None:
        return LSLibWindowsExeBackend(probe.executable)
    if probe.id == "lslib-dotnet-cli" and probe.executable is not None and probe.assembly is not None:
        return LSLibDotnetCliBackend(probe.assembly, probe.executable)
    return None


def backend_from_manifest(data: Mapping[str, object]) -> ArchiveBackend | None:
    backend_id = str(data.get("id", ""))
    executable_raw = data.get("executable")
    assembly_raw = data.get("assembly")
    executable = Path(str(executable_raw)) if executable_raw else None
    assembly = Path(str(assembly_raw)) if assembly_raw else None
    if backend_id == "lslib-windows-exe" and executable is not None:
        return LSLibWindowsExeBackend(executable)
    if backend_id == "lslib-dotnet-cli" and executable is not None and assembly is not None:
        return LSLibDotnetCliBackend(assembly=assembly, dotnet=executable)
    return None


def resolve_backend(requested: str = "auto") -> BackendProbe:
    if requested == "lslib-windows-exe":
        return LSLibWindowsExeBackend().probe()
    if requested == "lslib-dotnet-cli":
        return LSLibDotnetCliBackend().probe()
    if requested != "auto":
        return BackendProbe(requested, False, reason="Unknown archive backend id")
    candidates = [LSLibWindowsExeBackend().probe(), LSLibDotnetCliBackend().probe()]
    for probe in candidates:
        if probe.available:
            return probe
    reasons = "; ".join(f"{probe.id}: {probe.reason}" for probe in candidates)
    return BackendProbe("unresolved", False, reason=reasons)


def backend_manifest(probe: BackendProbe) -> dict[str, object]:
    result: dict[str, object] = {"id": probe.id, "version": probe.version}
    if probe.executable is not None:
        result["executable"] = str(probe.executable)
    if probe.assembly is not None:
        result["assembly"] = str(probe.assembly)
    if probe.reason is not None:
        result["reason"] = probe.reason
    return result


def parse_list_output(stdout: str) -> list[ArchiveEntry]:
    entries: list[ArchiveEntry] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            raise ArchiveBackendError(f"Unexpected list-package output line: {raw_line!r}")
        path, size_text, crc_text = parts
        try:
            size = int(size_text)
            crc = int(crc_text)
        except ValueError as exc:
            raise ArchiveBackendError(f"Invalid list-package numeric field: {raw_line!r}") from exc
        entries.append(ArchiveEntry(path=path, size=size, crc=crc))
    return entries


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ArchiveBackendError(f"Unable to execute archive backend: {exc}") from exc
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f"exit code {completed.returncode}"
        raise ArchiveBackendError(f"Archive backend command failed: {message}")
    return completed


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None
