import os
import re
from pathlib import Path
from typing import Sequence

from bg3loc.backends import ArchiveBackend, ArchiveEntry, backend_from_probe, resolve_backend
from bg3loc.research.bark import CANONICAL_BARK_CONTAINERS
from bg3loc.research.model import ResearchScanResource

STORY_SCOPE_PAKS = {"Gustav.pak", "Shared.pak", "GustavX.pak", "Patch8_HotFix9.pak"}


def match_story_family(p: str, ext: str) -> tuple[str, str]:
    """Match internal path and extension to one of the 10 story source families."""
    if re.search(r"/Story/Dialogs/", p, re.I) and ext == ".lsj":
        return "DialogsRaw", "LSJ"
    if re.search(r"/Story/DialogsBinary/", p, re.I) and ext == ".lsf":
        return "DialogsBinary", "LSF"
    if re.search(r"/Story/RawFiles/Goals/", p, re.I) and ext == ".txt":
        return "StoryGoals", "TXT"
    if re.search(r"/(Journal|Quest)[^/]*/", p, re.I) and ext in (".lsf", ".lsx", ".lsj", ".txt"):
        return "JournalQuest", ext.replace(".", "").upper()
    if re.search(r"/Localization/", p, re.I) and re.search(r"book|letter|gazette|readable|misc", Path(p).name, re.I):
        return "ReadableLocalizationRegistry", ext.replace(".", "").upper()
    if re.search(r"/Localization/", p, re.I) and ext in (".lsf", ".lsx"):
        return "LocalizationRegistry", ext.replace(".", "").upper()
    if re.search(r"/RootTemplates/_merged\.lsf$", p, re.I):
        return "RootTemplates", "LSF"
    if re.search(r"/(Tags|Characters)/", p, re.I) and ext in (".lsf", ".lsx"):
        return "TagsCharacters", ext.replace(".", "").upper()
    if re.search(r"/Cinematics?/", p, re.I) and ext in (".lsf", ".lsx", ".lsj"):
        return "Cinematics", ext.replace(".", "").upper()
    if re.search(r"(^|/)Levels?/", p, re.I) and ext in (".lsf", ".lsx", ".lsj", ".lsb", ".xml", ".txt"):
        if not re.search(r"(^|/)(Voice|Animations?)($|/)", p, re.I):
            return "LevelResources", ext.replace(".", "").upper()
    return "", ""


def scan_game_research_resources(
    game_dir: str | Path,
    *,
    source_locale: str = "English",
    target_locale: str = "ChineseTraditional",
    reference_locales: list[str] | None = None,
    backend: ArchiveBackend | None = None
) -> list[ResearchScanResource]:
    """Scan game installation and discover research-relevant internal package resources."""
    root = Path(game_dir)
    data_dir = root / "Data" if (root / "Data").is_dir() else root

    if reference_locales is None:
        reference_locales = []

    chosen_backend = backend
    if not chosen_backend:
        probe = resolve_backend()
        chosen_backend = backend_from_probe(probe)

    resources: list[ResearchScanResource] = []
    if not chosen_backend:
        return resources

    # Dynamically derive required packages without hardcoding English or any specific language
    required_paks = {"Gustav.pak", "Shared.pak", "GustavX.pak"}
    required_reference_paks: set[str] = set()
    if source_locale:
        required_paks.add(f"{source_locale}.pak")
    if target_locale:
        required_paks.add(f"{target_locale}.pak")
    if reference_locales:
        for ref_loc in reference_locales:
            pak_name = f"{ref_loc}.pak"
            required_paks.add(pak_name)
            required_reference_paks.add(pak_name)

    # Find PAK files in Data and Data/Localization recursively
    pak_files_set = set(data_dir.glob("*.pak"))
    if (data_dir / "Localization").is_dir():
        pak_files_set.update((data_dir / "Localization").rglob("*.pak"))
    pak_files = sorted(pak_files_set)

    # Reference locales are optional unless explicitly requested.  Once requested,
    # they are a hard contract: fail closed rather than silently producing a
    # multilingual evidence set with zero reference rows.  Source/target retain
    # the existing required-archive behavior below so archive listing failures
    # are still reported with their original diagnostics.
    available_pak_names = {p.name.casefold() for p in pak_files}
    missing_reference_paks = sorted(
        name for name in required_reference_paks
        if name.casefold() not in available_pak_names
    )
    if missing_reference_paks:
        raise RuntimeError(
            "Missing requested localization archive(s): "
            + ", ".join(missing_reference_paks)
        )

    for pak_path in pak_files:
        pak_name = pak_path.name
        try:
            entries: Sequence[ArchiveEntry] = chosen_backend.list_archive(pak_path)
        except Exception as exc:
            if pak_name in required_paks or pak_name.startswith("Patch"):
                raise RuntimeError(f"Failed to list required archive {pak_path}") from exc
            else:
                continue

        for entry in entries:
            path = entry.path.replace("\\", "/")
            lower = path.lower()

            source_role = ""
            fmt = ""

            # Check canonical bark containers first
            if any(bc.lower() in lower for bc in CANONICAL_BARK_CONTAINERS):
                source_role = "BarkContainer"
                fmt = "LSF" if lower.endswith(".lsf") else "LSJ"

            # Check 10 story source families if in the 4 story packages
            if not source_role and pak_name in STORY_SCOPE_PAKS:
                ext = Path(path).suffix.lower()
                fam, family_fmt = match_story_family(path, ext)
                if fam:
                    source_role = fam
                    fmt = family_fmt

            # Check localization (root and auxiliary gender/transition locas)
            if not source_role and "localization/" in lower and lower.endswith(".loca"):
                is_aux = "/gender/" in lower or "_to_" in lower or "_m_to_" in lower or "_f_to_" in lower or "_x_to_" in lower
                if f"/{source_locale.lower()}/" in lower:
                    source_role = "AuxiliarySourceLocalization" if is_aux else "SourceLocalization"
                    fmt = "LOCA"
                elif f"/{target_locale.lower()}/" in lower:
                    source_role = "AuxiliaryTargetLocalization" if is_aux else "TargetLocalization"
                    fmt = "LOCA"
                elif any(f"/{ref.lower()}/" in lower for ref in reference_locales):
                    source_role = "AuxiliaryReferenceLocalization" if is_aux else "ReferenceLocalization"
                    fmt = "LOCA"
            # Check stats
            elif not source_role and "public/" in lower and "/stats/generated/data/" in lower and lower.endswith(".txt"):
                source_role = "StatsResource"
                fmt = "StatsTXT"
            # Check dialogs / barks
            elif not source_role and "story/dialogsbinary/" in lower and (lower.endswith(".lsf") or lower.endswith(".lsj")):
                if any(bc.lower() in lower for bc in CANONICAL_BARK_CONTAINERS):
                    source_role = "BarkContainer"
                else:
                    source_role = "DialogResource"
                fmt = "LSF" if lower.endswith(".lsf") else "LSJ"
            # Check quest journal
            elif not source_role and ("story/journal/" in lower or "story/journal/quests" in lower) and (lower.endswith(".lsx") or lower.endswith(".lsf")):
                source_role = "QuestJournalResource"
                fmt = "LSX" if lower.endswith(".lsx") else "LSF"
            # Check UI / XAML
            elif not source_role and ("gui/" in lower or "content/ui/" in lower) and lower.endswith(".xaml"):
                source_role = "UiResource"
                fmt = "XAML"
            # Auxiliary localization / story evidence files for residual story logic
            elif not source_role and "story/rawfiles/" in lower and lower.endswith(".txt"):
                source_role = "StoryScript"
                fmt = "TXT"

            if source_role:
                resources.append(
                    ResearchScanResource(
                        pakName=pak_name,
                        internalPath=path,
                        resourceFormat=fmt,
                        sourceRole=source_role,
                        size=entry.size,
                    )
                )

    return resources
