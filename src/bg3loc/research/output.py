from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Sequence

from bg3loc.research.model import ResearchMapping, ResearchRunManifest, ResearchScanResource


def write_mappings_jsonl(mappings: Iterable[ResearchMapping], output_path: str | Path) -> int:
    """Write research mappings to JSON Lines format."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for m in mappings:
            f.write(json.dumps(m.to_dict(), ensure_ascii=False) + "\n")
            count += 1
    return count


def write_scan_manifest(resources: Sequence[ResearchScanResource], output_path: str | Path, **extra: object) -> None:
    """Write discovered research resources manifest to JSON."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "resourceCount": len(resources),
        "resources": [r.to_dict() for r in resources],
        **extra,
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def write_research_summary(manifest: ResearchRunManifest, output_path: str | Path) -> None:
    """Write research run summary to JSON."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(manifest.to_dict(), f, indent=2, ensure_ascii=False)