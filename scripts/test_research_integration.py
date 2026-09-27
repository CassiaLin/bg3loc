import os
import subprocess
import tempfile
import json
from pathlib import Path

def main():
    repo_root = Path(__file__).parent.parent
    cli_path = repo_root / "src" / "bg3loc" / "cli.py"
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        game_dir = tmp_path / "game"
        data_dir = game_dir / "Data"
        data_dir.mkdir(parents=True)
        
        # Create a dummy pak file for scanning
        pak_path = data_dir / "English.pak"
        pak_path.touch()
        
        import shutil
        if not shutil.which("Divine.exe") and not os.environ.get("BG3LOC_DIVINE_EXE") and not os.environ.get("BG3LOC_DIVINE_DLL"):
            print("Skipping real integration test because LSLib Divine is not installed in this environment.")
            return 0
            
        # Run scan
        print("Running scan...")
        scan_output = tmp_path / "scan.json"
        res = subprocess.run([
            "python", "-m", "bg3loc.cli", "research", "scan",
            "--game-dir", str(game_dir),
            "--output", str(scan_output),
            "--source", "English",
            "--target", "ChineseTraditional",
            "--reference", "Chinese",
            "--reference", "Russian"
        ], cwd=str(repo_root), capture_output=True, text=True)
        print("Scan stdout:", res.stdout)
        print("Scan stderr:", res.stderr)
        
        if not scan_output.exists():
            print("Failed to produce scan output.")
            return 1
            
        print("Scan produced manifest.")
        
        # Now run map
        print("Running map...")
        map_output_dir = tmp_path / "output"
        res = subprocess.run([
            "python", "-m", "bg3loc.cli", "research", "map",
            "--scan", str(scan_output),
            "--output-dir", str(map_output_dir),
            "--source", "English",
            "--target", "ChineseTraditional",
            "--reference", "Chinese",
            "--reference", "Russian"
        ], cwd=str(repo_root), capture_output=True, text=True)
        
        print("Map stdout:", res.stdout)
        print("Map stderr:", res.stderr)
        
        summary_file = map_output_dir / "research-summary.json"
        if summary_file.exists():
            print(f"Integration test passed. Summary: {summary_file.read_text()}")
        else:
            print("Failed to produce map summary.")
            return 1
            
    return 0

if __name__ == "__main__":
    exit(main())
