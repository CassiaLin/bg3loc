"""Public, research-only extraction from the user's current archive installation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from bg3loc.backends import ArchiveBackend
from bg3loc.research.dialogue_context import DialogueAudit, parse_dialogue
from bg3loc.research.structural_provenance import canonical_json, relative_resource


def discover_dialogues(game: Path, backend: ArchiveBackend) -> tuple[list[dict], list[str]]:
    data = game / "Data"
    if not data.is_dir():
        raise ValueError("game installation must contain Data")
    rows = []; parts = []
    for package in sorted(data.glob("*.pak")):
        try:
            entries = backend.list_archive(package)
        except Exception:
            # A multipart continuation is read through its base archive. An
            # unknown unreadable primary archive is never silently omitted.
            match = re.fullmatch(r"(.+)_\d+\.pak", package.name, re.I)
            if match and (data / (match.group(1) + ".pak")).is_file():
                parts.append(package.name); continue
            raise
        for entry in entries:
            path = relative_resource(entry.path)
            if ("/story/dialogs/" in path.lower() and path.lower().endswith(".lsj")
                or "/story/dialogsbinary/" in path.lower() and path.lower().endswith(".lsf")):
                rows.append({"package": package.name, "resource": path})
    if not rows:
        raise ValueError("no dialogue resources discovered")
    return sorted(rows, key=canonical_json), parts


def load_dialogue_targets(classification: Path | None) -> dict[str, str]:
    result = {}
    if classification is None:
        return result
    with classification.open(encoding="utf-8-sig") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            if (row["primaryCategory"] in {"dialogue_general", "bark"}
                and row["classificationStatus"] == "classified"):
                if row["contentUid"] in result:
                    raise ValueError("duplicate dialogue target in classification")
                result[row["contentUid"]] = row["primaryCategory"]
    return result


def export_dialogue_research(game: Path, backend: ArchiveBackend, output: Path,
                             *, classification: Path | None = None) -> dict:
    rows, parts = discover_dialogues(game, backend)
    output.mkdir(parents=True, exist_ok=True)
    audit = DialogueAudit()
    # This cache is newly extracted here; never consume retained private data.
    with tempfile.TemporaryDirectory(dir=output) as td:
        temporary = Path(td)
        probe = backend.probe()
        lslib = probe.executable.parent if probe.executable else None
        pwsh = shutil.which("pwsh")
        if os.name == "nt" and pwsh and lslib and (lslib / "LSLib.dll").is_file():
            inventory = temporary / "inventory.json"
            raw = temporary / "raw.jsonl"
            inventory.write_text(canonical_json(rows), encoding="utf-8")
            subprocess.run([pwsh, "-NoProfile", "-File", str(Path(__file__).with_name("dialogue_extract.ps1")),
                            "-Inventory", str(inventory.resolve()), "-GameDir", str(game.resolve()),
                            "-LSLibDir", str(lslib.resolve()), "-Output", str(raw.resolve())], check=True)
            count = 0
            with raw.open(encoding="utf-8-sig") as f:
                for line in f:
                    record = json.loads(line)
                    audit.add(parse_dialogue(record["data"], package=record["package"], resource=record["resource"]))
                    count += 1
            if count != len(rows):
                raise ValueError("dialogue extraction count mismatch")
        else:
            for index, row in enumerate(rows):
                extracted = temporary / (str(index) + Path(row["resource"]).suffix)
                backend.extract_single_file(game / "Data" / row["package"], row["resource"], extracted)
                converted = extracted
                if extracted.suffix.lower() == ".lsf":
                    converted = extracted.with_suffix(".lsj")
                    backend.convert_resource(extracted, converted)
                audit.add(parse_dialogue(json.loads(converted.read_text(encoding="utf-8-sig")),
                                         package=row["package"], resource=row["resource"]))
    report = audit.write(output, load_dialogue_targets(classification))
    report["extraction"] = {"selectedResources": len(rows), "multipartContinuations": len(parts),
                            "formats": {extension: sum(Path(r["resource"]).suffix == extension for r in rows)
                                        for extension in (".lsj", ".lsf")},
                            "generationInputs": {"gameInstall": True, "privateDataset": False,
                                                  "manualNodeList": False, "retainedRawCache": False}}
    (output / "dialogue-summary.json").write_text(canonical_json(report) + "\n", encoding="utf-8")
    return report
