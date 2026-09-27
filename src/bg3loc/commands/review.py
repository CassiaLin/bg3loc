from __future__ import annotations

import argparse
import json
from pathlib import Path

from bg3loc.review.bark import prepare_bark_review, validate_bark_review
from bg3loc.review.multilingual import prepare_multilingual_review, validate_multilingual_review
from bg3loc.review.quest import prepare_quest_review, validate_quest_review
from bg3loc.review.taiwan_usage import prepare_taiwan_usage_review, validate_taiwan_usage_review
from bg3loc.review.ui_skill import prepare_ui_skill_review, validate_ui_skill_review


def _add_prepare_validate(
    domain_parser: argparse.ArgumentParser,
    *,
    domain: str,
    default_output: str,
    prepare_handler,
    validate_handler,
) -> None:
    actions = domain_parser.add_subparsers(dest="review_action", required=True)

    prepare = actions.add_parser("prepare", help=f"Generate blind-first {domain} review surfaces")
    prepare.add_argument("--mappings", required=True, help="Deterministic research-mappings.jsonl")
    prepare.add_argument("--extract", required=True, help="Extract manifest providing source and comparison locales")
    prepare.add_argument("--output", default=default_output, help="New or empty output directory")
    prepare.add_argument("--include-pass2", action="store_true", help="Also generate the separated comparison surface")
    prepare.set_defaults(handler=prepare_handler)

    validate = actions.add_parser("validate", help=f"Validate a reviewer-completed {domain} CSV")
    validate.add_argument("--input", required=True, help="Completed Pass 1 or Pass 2 CSV")
    validate.add_argument("--manifest", help=f"{domain.title()} package manifest; defaults beside the input CSV")
    validate.add_argument("--output", default=f"{default_output}-validation", help="Validation output directory")
    validate.set_defaults(handler=validate_handler)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    review = subparsers.add_parser("review", help="Reviewer-facing evidence workflows")
    domains = review.add_subparsers(dest="review_domain", required=True)

    bark = domains.add_parser("bark", help="Prepare and validate Bark review packages")
    _add_prepare_validate(
        bark,
        domain="bark",
        default_output="workspace/bark-review",
        prepare_handler=run_bark_prepare,
        validate_handler=run_bark_validate,
    )

    quest = domains.add_parser("quest", help="Prepare and validate Quest review packages")
    _add_prepare_validate(
        quest,
        domain="quest",
        default_output="workspace/quest-review",
        prepare_handler=run_quest_prepare,
        validate_handler=run_quest_validate,
    )

    multilingual = domains.add_parser("multilingual", help="Prepare and validate multilingual auxiliary-evidence review packages")
    _add_prepare_validate(
        multilingual,
        domain="multilingual",
        default_output="workspace/multilingual-review",
        prepare_handler=run_multilingual_prepare,
        validate_handler=run_multilingual_validate,
    )

    taiwan_usage = domains.add_parser("taiwan-usage", help="Prepare and validate reviewer-supplied Taiwan usage QA packages")
    tw_actions = taiwan_usage.add_subparsers(dest="review_action", required=True)
    tw_prepare = tw_actions.add_parser("prepare", help="Scan the current target locale with a reviewer-supplied usage rule set")
    tw_prepare.add_argument("--extract", required=True, help="Extract manifest providing current source and target locales")
    tw_prepare.add_argument("--rules", required=True, help="Taiwan usage rule-set JSON")
    tw_prepare.add_argument("--output", default="workspace/taiwan-usage-review", help="New or empty output directory")
    tw_prepare.set_defaults(handler=run_taiwan_usage_prepare)

    tw_validate = tw_actions.add_parser("validate", help="Validate a reviewer-completed Taiwan usage CSV")
    tw_validate.add_argument("--input", required=True, help="Completed Taiwan usage review CSV")
    tw_validate.add_argument("--manifest", help="Taiwan usage package manifest; defaults beside the input CSV")
    tw_validate.add_argument("--output", default="workspace/taiwan-usage-review-validation", help="Validation output directory")
    tw_validate.set_defaults(handler=run_taiwan_usage_validate)

    ui_skill = domains.add_parser("ui-skill", help="Prepare and validate UI / Skill review packages")
    ui_actions = ui_skill.add_subparsers(dest="review_action", required=True)
    ui_prepare = ui_actions.add_parser("prepare", help="Generate blind-first UI / Skill review surfaces")
    ui_prepare.add_argument(
        "--universe", required=True,
        help="Deterministic ui-skill-universe.csv relation evidence from research map",
    )
    ui_prepare.add_argument("--extract", required=True, help="Extract manifest providing source and comparison locales")
    ui_prepare.add_argument("--output", default="workspace/ui-skill-review", help="New or empty output directory")
    ui_prepare.add_argument("--include-pass2", action="store_true", help="Also generate the separated comparison surface")
    ui_prepare.set_defaults(handler=run_ui_skill_prepare)

    ui_validate = ui_actions.add_parser("validate", help="Validate a reviewer-completed UI / Skill CSV")
    ui_validate.add_argument("--input", required=True, help="Completed Pass 1 or Pass 2 CSV")
    ui_validate.add_argument("--manifest", help="UI / Skill package manifest; defaults beside the input CSV")
    ui_validate.add_argument("--output", default="workspace/ui-skill-review-validation", help="Validation output directory")
    ui_validate.set_defaults(handler=run_ui_skill_validate)


def _run_prepare(args: argparse.Namespace, *, domain: str, prepare_fn) -> int:
    try:
        result = prepare_fn(
            mappings_path=Path(args.mappings),
            extract_manifest=Path(args.extract),
            output_dir=Path(args.output),
            include_pass2=bool(args.include_pass2),
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {domain.title()} review preparation failed: {exc}")
        return 1
    counts = result["counts"]
    if domain == "bark":
        detail = f"{counts['SingleSpeaker']} SingleSpeaker, {counts['SharedSpeaker']} SharedSpeaker"
    elif domain == "quest":
        detail = f"{counts['QuestTitle']} QuestTitle, {counts['QuestDescription']} QuestDescription, {counts['occurrences']} occurrences"
    else:
        detail = ", ".join(f"{key}={value}" for key, value in sorted(counts.get("classifications", {}).items()))
    print(f"{domain.title()} review prepare PASS: {counts['total']} candidates ({detail})")
    print(f"Manifest: {Path(args.output) / f'{domain}-review-manifest.json'}")
    return 0


def _run_validate(args: argparse.Namespace, *, domain: str, validate_fn) -> int:
    input_path = Path(args.input)
    manifest_path = Path(args.manifest) if args.manifest else input_path.parent / f"{domain}-review-manifest.json"
    try:
        result = validate_fn(
            input_path=input_path,
            manifest_path=manifest_path,
            output_dir=Path(args.output),
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {domain.title()} review validation failed: {exc}")
        return 1
    print(f"{domain.title()} review validation {result['status'].upper()}: {result['findingCount']} finding(s)")
    print(f"Reviewed output: {result['reviewedOutput']}")
    return 0 if result["status"] == "passed" else 1


def run_bark_prepare(args: argparse.Namespace) -> int:
    return _run_prepare(args, domain="bark", prepare_fn=prepare_bark_review)


def run_bark_validate(args: argparse.Namespace) -> int:
    return _run_validate(args, domain="bark", validate_fn=validate_bark_review)


def run_quest_prepare(args: argparse.Namespace) -> int:
    return _run_prepare(args, domain="quest", prepare_fn=prepare_quest_review)


def run_quest_validate(args: argparse.Namespace) -> int:
    return _run_validate(args, domain="quest", validate_fn=validate_quest_review)


def run_multilingual_prepare(args: argparse.Namespace) -> int:
    return _run_prepare(args, domain="multilingual", prepare_fn=prepare_multilingual_review)


def run_multilingual_validate(args: argparse.Namespace) -> int:
    return _run_validate(args, domain="multilingual", validate_fn=validate_multilingual_review)


def run_taiwan_usage_prepare(args: argparse.Namespace) -> int:
    try:
        result = prepare_taiwan_usage_review(
            extract_manifest=Path(args.extract),
            rules_path=Path(args.rules),
            output_dir=Path(args.output),
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[ERROR] Taiwan usage review preparation failed: {exc}")
        return 1
    counts = result["counts"]
    print(
        f"Taiwan usage review prepare PASS: {counts['total']} candidates "
        f"({counts['findings']} findings, {len(counts['rules'])} rules)"
    )
    print(f"Manifest: {Path(args.output) / 'taiwan-usage-review-manifest.json'}")
    return 0


def run_taiwan_usage_validate(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    manifest_path = Path(args.manifest) if args.manifest else input_path.parent / "taiwan-usage-review-manifest.json"
    try:
        result = validate_taiwan_usage_review(
            input_path=input_path,
            manifest_path=manifest_path,
            output_dir=Path(args.output),
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[ERROR] Taiwan usage review validation failed: {exc}")
        return 1
    print(f"Taiwan usage review validation {result['status'].upper()}: {result['findingCount']} finding(s)")
    print(f"Reviewed output: {result['reviewedOutput']}")
    return 0 if result["status"] == "passed" else 1


def run_ui_skill_prepare(args: argparse.Namespace) -> int:
    try:
        result = prepare_ui_skill_review(
            universe_path=Path(args.universe),
            extract_manifest=Path(args.extract),
            output_dir=Path(args.output),
            include_pass2=bool(args.include_pass2),
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[ERROR] UI / Skill review preparation failed: {exc}")
        return 1
    counts = result["counts"]
    print(
        f"UI / Skill review prepare PASS: {counts['total']} candidates "
        f"({counts['relations']} relations, {len(counts['workstreams'])} workstreams)"
    )
    print(f"Manifest: {Path(args.output) / 'ui-skill-review-manifest.json'}")
    return 0


def run_ui_skill_validate(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    manifest_path = Path(args.manifest) if args.manifest else input_path.parent / "ui-skill-review-manifest.json"
    try:
        result = validate_ui_skill_review(
            input_path=input_path,
            manifest_path=manifest_path,
            output_dir=Path(args.output),
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[ERROR] UI / Skill review validation failed: {exc}")
        return 1
    print(f"UI / Skill review validation {result['status'].upper()}: {result['findingCount']} finding(s)")
    print(f"Reviewed output: {result['reviewedOutput']}")
    return 0 if result["status"] == "passed" else 1


# Backward-compatible callable names used by existing unit tests/integrations.
run_prepare = run_bark_prepare
run_validate = run_bark_validate
