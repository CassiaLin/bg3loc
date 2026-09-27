from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from bg3loc.research.model import ResearchEvidence, ResearchMapping

RULE_PATCH_OVERLAY = "BG3-OFFICIAL-PATCH-OVERLAY"
RULE_MATERIALIZATION = "BG3-OFFICIAL-PATCH-OVERLAY-MATERIALIZATION"

# Default fallback layer priority (higher index = higher precedence)
# Official package priority layer hierarchy:
# Base game -> Shared -> SharedDev -> Gustav -> GustavDev -> GustavX -> Patches
DEFAULT_PAK_PRIORITY: list[str] = [
    "Game.pak",
    "Shared.pak",
    "SharedSoundBanks.pak",
    "Gustav.pak",
    "Gustav_Video.pak",
    "Gustav_NavGrid.pak",
    "GustavX.pak",
    "Patch8_HotFix9.pak",
]


@dataclass(slots=True)
class OverlayCandidate:
    internalPath: str
    pakName: str
    size: int = 0
    mtime: float = 0.0
    layerPriority: int = 0


@dataclass(slots=True)
class OverlayResolution:
    internalPath: str
    winningPak: str
    allCandidates: list[str] = field(default_factory=list)
    ruleId: str = RULE_PATCH_OVERLAY


def resolve_overlay_precedence(
    candidates: Sequence[OverlayCandidate],
    priority_order: Sequence[str] | None = None
) -> dict[str, OverlayResolution]:
    """Resolve which package layer wins for duplicate internal resource paths."""
    order = list(priority_order or DEFAULT_PAK_PRIORITY)
    order_map = {name.lower(): idx for idx, name in enumerate(order)}

    by_path: dict[str, list[OverlayCandidate]] = {}
    for c in candidates:
        by_path.setdefault(c.internalPath.replace("\\", "/"), []).append(c)

    results: dict[str, OverlayResolution] = {}
    for path, group in by_path.items():
        if len(group) == 1:
            results[path] = OverlayResolution(
                internalPath=path,
                winningPak=group[0].pakName,
                allCandidates=[group[0].pakName],
                ruleId=RULE_MATERIALIZATION,
            )
            continue

        # Sort group by explicit priority order, then mtime, then size
        def sort_key(cand: OverlayCandidate) -> tuple[int, float, int]:
            prio = order_map.get(cand.pakName.lower(), cand.layerPriority)
            return (prio, cand.mtime, cand.size)

        sorted_group = sorted(group, key=sort_key)
        winner = sorted_group[-1]

        results[path] = OverlayResolution(
            internalPath=path,
            winningPak=winner.pakName,
            allCandidates=[c.pakName for c in group],
            ruleId=RULE_PATCH_OVERLAY,
        )

    return results