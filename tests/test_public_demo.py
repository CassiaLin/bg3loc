"""The packaged fictional demo must work from an arbitrary working directory."""

from pathlib import Path
import subprocess
import sys


def test_demo_accepts_relative_output_from_external_cwd(tmp_path: Path) -> None:
    demo = Path(__file__).resolve().parents[1] / "examples" / "demo" / "run_demo.py"
    result = subprocess.run(
        [sys.executable, str(demo), "--output", "demo"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Fictional demo PASS" in result.stdout
