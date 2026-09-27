"""Research reproduction layer for Baldur's Gate 3 localization mapping."""

from bg3loc.research.model import (
    HANDLE_PATTERN,
    ResearchEvidence,
    ResearchMapping,
    ResearchRunManifest,
    ResearchScanResource,
)
from bg3loc.research.stats import parse_stats_text
from bg3loc.research.overlay import resolve_overlay_precedence, OverlayCandidate, OverlayResolution
from bg3loc.research.dialog import traverse_dialog_json
from bg3loc.research.bark import parse_bark_container, CANONICAL_BARK_CONTAINERS
from bg3loc.research.quest import parse_quest_xml, filter_quest_context_candidates
from bg3loc.research.context import ContextAggregator
from bg3loc.research.multilingual import align_multilingual_references
from bg3loc.research.ui_skill import parse_ui_skill_xml
from bg3loc.research.story import evaluate_residual_story_candidates
from bg3loc.research.scanner import scan_game_research_resources
from bg3loc.research.output import (
    write_mappings_jsonl,
    write_scan_manifest,
    write_research_summary,
)
from bg3loc.research.batching import (
    BATCHING_RULE_VERSION,
    DEFAULT_MAX_RECORDS,
    BatchInputRecord,
    BatchManifest,
    BatchPlan,
    BatchRecord,
    batch_plan_fingerprint,
    build_batch_plan,
    normalize_dialog_resource,
)
from bg3loc.research.classification import (
    PRIMARY_CATEGORIES,
    SUPPORTED_V1_CATEGORIES,
    ClassificationEvidence,
    FunctionalClassification,
    classify_functional_ownership,
    summarize_functional_classification,
)

__all__ = [
    "HANDLE_PATTERN",
    "ResearchEvidence",
    "ResearchMapping",
    "ResearchRunManifest",
    "ResearchScanResource",
    "parse_stats_text",
    "resolve_overlay_precedence",
    "OverlayCandidate",
    "OverlayResolution",
    "traverse_dialog_json",
    "parse_bark_container",
    "CANONICAL_BARK_CONTAINERS",
    "parse_quest_xml",
    "filter_quest_context_candidates",
    "ContextAggregator",
    "align_multilingual_references",
    "parse_ui_skill_xml",
    "evaluate_residual_story_candidates",
    "scan_game_research_resources",
    "write_mappings_jsonl",
    "write_scan_manifest",
    "write_research_summary",
    "BATCHING_RULE_VERSION",
    "DEFAULT_MAX_RECORDS",
    "BatchInputRecord",
    "BatchManifest",
    "BatchPlan",
    "BatchRecord",
    "batch_plan_fingerprint",
    "build_batch_plan",
    "normalize_dialog_resource",
    "PRIMARY_CATEGORIES",
    "SUPPORTED_V1_CATEGORIES",
    "ClassificationEvidence",
    "FunctionalClassification",
    "classify_functional_ownership",
    "summarize_functional_classification",
]