from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bg3loc.backends import (
    ArchiveBackendError,
    BackendProbe,
    LSLibDotnetCliBackend,
    LSLibWindowsExeBackend,
    parse_list_output,
    resolve_backend,
)


class ArchiveBackendProbeTests(unittest.TestCase):
    def test_windows_exe_probe_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            divine = Path(tmp) / "Divine.exe"
            divine.write_bytes(b"stub")
            with patch.dict(os.environ, {"BG3LOC_DIVINE_EXE": str(divine)}, clear=False):
                probe = LSLibWindowsExeBackend().probe()
            self.assertTrue(probe.available)
            self.assertEqual(probe.id, "lslib-windows-exe")
            self.assertEqual(probe.executable, divine.resolve())

    def test_dotnet_probe_requires_configured_assembly(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            probe = LSLibDotnetCliBackend().probe()
        self.assertFalse(probe.available)
        self.assertIn("Divine.dll", probe.reason or "")

    def test_windows_probe_explains_environment_setup(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch("bg3loc.backends.shutil.which", return_value=None):
            probe = LSLibWindowsExeBackend().probe()
        self.assertFalse(probe.available)
        self.assertIn("BG3LOC_DIVINE_EXE", probe.reason or "")
        self.assertIn("Divine.exe", probe.reason or "")

    def test_unknown_backend_id_is_not_available(self) -> None:
        probe = resolve_backend("unknown-backend")
        self.assertFalse(probe.available)
        self.assertEqual(probe.id, "unknown-backend")
        self.assertIn("Unknown", probe.reason or "")

    def test_auto_backend_preserves_fallback_to_available_candidate(self) -> None:
        windows_probe = BackendProbe(id="lslib-windows-exe", available=False, reason="missing executable")
        dotnet_probe = BackendProbe(
            id="lslib-dotnet-cli",
            available=True,
            executable=Path("dotnet"),
            assembly=Path("Divine.dll"),
        )
        with patch.object(LSLibWindowsExeBackend, "probe", return_value=windows_probe), patch.object(
            LSLibDotnetCliBackend, "probe", return_value=dotnet_probe
        ):
            probe = resolve_backend("auto")

        self.assertEqual(probe, dotnet_probe)

    def test_parse_list_output(self) -> None:
        entries = parse_list_output(
            "Localization/English/english.loca\t30345488\t12345\n"
            "Localization/Game/game.loca\t42\t0\n"
        )
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].path, "Localization/English/english.loca")
        self.assertEqual(entries[0].size, 30345488)
        self.assertEqual(entries[0].crc, 12345)

    def test_parse_list_output_rejects_unexpected_line(self) -> None:
        with self.assertRaises(ArchiveBackendError):
            parse_list_output("not-a-three-column-line\n")


if __name__ == "__main__":
    unittest.main()
