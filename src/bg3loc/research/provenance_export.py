"""Rebuild public definition/occurrence ledgers from a user's game archives."""
from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Sequence

from bg3loc.backends import ArchiveBackend
from bg3loc.research.model import ResearchScanResource
from bg3loc.research.structural_provenance import (
    parse_structural_stats, parse_structural_xml, relative_resource,
    write_structural_provenance,
)
from bg3loc.research.ui_skill_universe import discover_ui_skill_providers


def export_public_structural_provenance(
    game_dir: Path, backend: ArchiveBackend, output_dir: Path,
    resources: Sequence[ResearchScanResource],
) -> dict:
    # Raw scan entries plus public UI/template discovery, never overlay winners.
    selected: dict[tuple[str, str], str] = {}
    for resource in resources:
        path = relative_resource(resource.internalPath)
        package = relative_resource(resource.pakName)
        if resource.sourceRole == "StatsResource" or "/stats/generated/data/" in path.lower():
            kind = "stats"
        elif resource.sourceRole in {"QuestJournalResource", "JournalQuest"}:
            kind = "quest"
        elif resource.sourceRole == "RootTemplates" or "/roottemplates/" in path.lower():
            kind = "item"
        else:
            continue
        if Path(path).suffix.lower() not in {".txt", ".lsx", ".lsf", ".lsb", ".xml"}:
            raise ValueError("unsupported structural resource format")
        selected[(package, path)] = kind
    for provider in discover_ui_skill_providers(game_dir, backend):
        if provider.resource_format == "StatsTXT":
            selected[(provider.package, provider.internal_path)] = "stats"
        elif "Root Templates" in provider.source_families:
            selected[(provider.package, provider.internal_path)] = "item"

    output_dir.mkdir(parents=True, exist_ok=True)
    definitions = []
    with tempfile.TemporaryDirectory(dir=output_dir) as temporary:
        for index, ((package, path), kind) in enumerate(sorted(selected.items())):
            archive = game_dir / "Data" / package
            # Fail closed: no silent omission of a selected definition source.
            if not archive.is_file():
                raise ValueError("selected structural archive is missing")
            extracted = Path(temporary) / f"{index:06d}{Path(path).suffix}"
            backend.extract_single_file(archive, path, extracted)
            converted = extracted
            if extracted.suffix.lower() in {".lsf", ".lsb"}:
                converted = extracted.with_suffix(".lsx")
                backend.convert_resource(extracted, converted)
            text = converted.read_text(encoding="utf-8-sig")
            if kind == "stats":
                definitions.extend(parse_structural_stats(text, resource_path=path, package=package))
            else:
                definitions.extend(parse_structural_xml(text, resource_path=path, package=package, kind=kind))
    summary = write_structural_provenance(output_dir, definitions)
    return summary
