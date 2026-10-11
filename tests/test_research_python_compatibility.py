"""Exercise the native script generation without running PowerShell or LSLib."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from bg3loc.commands import research


def test_production_sources_parse_with_python311_grammar():
    root = Path(research.__file__).resolve().parents[2]
    for path in root.rglob("*.py"):
        ast.parse(path.read_bytes(), filename=str(path), feature_version=(3, 11))


@pytest.mark.parametrize("folder", ["Synthetic Game", "虛構 遊戲"])
@pytest.mark.parametrize("primary_returncode", [0, 1])
def test_story_script_preserves_paths_and_powershell_fallback(
    tmp_path, monkeypatch, folder, primary_returncode
):
    tools = tmp_path / folder / "tools"
    tools.mkdir(parents=True)
    (tools / "LSLib.dll").write_bytes(b"synthetic probe only")
    game = tmp_path / folder / "game"
    output = tmp_path / folder / "output"
    backend = SimpleNamespace(probe=lambda: SimpleNamespace(executable=tools / "divine.exe"))
    # Replace this module's os binding, without changing platform state globally.
    monkeypatch.setattr(research, "os", SimpleNamespace(name="nt", unlink=research.os.unlink))
    scripts, commands, temporary_paths = [], [], []

    def capture(command, **kwargs):
        path = Path(command[-1])
        temporary_paths.append(path)
        scripts.append(path.read_bytes())
        commands.append(command[0])
        assert kwargs == dict(capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        return SimpleNamespace(returncode=primary_returncode if len(commands) == 1 else 0)

    monkeypatch.setattr(research.subprocess, "run", capture)
    research.extract_and_generate_story_ledger(game, output, backend)
    text = scripts[0].decode("utf-8")
    for filename, variable in [("story-occurrence-ledger.csv", "$lw"), ("oldtext-evidence.csv", "$ow")]:
        escaped = str(output / filename).replace("\\", "\\\\")
        assert f"{variable} = [System.IO.StreamWriter]::new('{escaped}'," in text
    escaped_game = str(game).replace("\\", "\\\\")
    assert f"$pPath = Join-Path (Join-Path '{escaped_game}' \"Data\") $pName" in text
    assert str(tools / "LSLib.dll") in text
    assert commands == (["pwsh"] if primary_returncode == 0 else ["pwsh", "powershell"])
    assert all(script == scripts[0] for script in scripts)
    assert all(not path.exists() for path in temporary_paths)
