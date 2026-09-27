from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re

from bg3loc.protected_syntax import validate_protected_syntax


QA_ROUTE_PASS = "PASS"
QA_ROUTE_RETRY = "RETRY"
QA_ROUTE_REVIEW = "REVIEW"
QA_ROUTE_FAIL = "FAIL"

ISSUE_OUTPUT_EMPTY = "OUTPUT_EMPTY"
ISSUE_PROTECTED_TOKEN_MISSING = "PROTECTED_TOKEN_MISSING"
ISSUE_PROTECTED_TOKEN_ADDED = "PROTECTED_TOKEN_ADDED"
ISSUE_LSTAG_MALFORMED = "LSTAG_MALFORMED"
ISSUE_SOURCE_EQUALS_TARGET = "SOURCE_EQUALS_TARGET"
ISSUE_POSSIBLE_UNTRANSLATED_TEXT = "POSSIBLE_UNTRANSLATED_TEXT"
ISSUE_LENGTH_RATIO_SUSPICIOUS = "LENGTH_RATIO_SUSPICIOUS"
ISSUE_CATEGORY_RULE_MISSING = "CATEGORY_RULE_MISSING"

QA_RULESET_VERSION = "1.2"

_LATIN_WORD_RE = re.compile(r"[A-Za-z]{4,}")
_MARKUP_RE = re.compile(r"<[^>]*>")


@dataclass(frozen=True, slots=True)
class CategoryQaPolicy:
    min_length_for_ratio: int
    min_length_ratio: float
    max_length_ratio: float


# Every category accepted by LSTP-01A is registered explicitly.
# v1.2 only specializes UI, bark, and dialogue. Other known categories use
# conservative shared bounds until category-specific evidence is added.
_CONSERVATIVE_POLICY = CategoryQaPolicy(
    min_length_for_ratio=20,
    min_length_ratio=0.15,
    max_length_ratio=4.0,
)

_CATEGORY_POLICIES: dict[str, CategoryQaPolicy] = {
    "dialogue_general": CategoryQaPolicy(20, 0.15, 4.0),
    "dialogue_story": CategoryQaPolicy(20, 0.15, 4.0),
    "quest": _CONSERVATIVE_POLICY,
    "bark": CategoryQaPolicy(12, 0.20, 3.0),
    "ui": CategoryQaPolicy(8, 0.20, 3.0),
    "skill_spell": _CONSERVATIVE_POLICY,
    "item": _CONSERVATIVE_POLICY,
    "book_lore": _CONSERVATIVE_POLICY,
    "character_world": _CONSERVATIVE_POLICY,
    "system_message": _CONSERVATIVE_POLICY,
    "tutorial": _CONSERVATIVE_POLICY,
    "other": _CONSERVATIVE_POLICY,
}


@dataclass(frozen=True, slots=True)
class QaIssue:
    issue_code: str
    severity: str
    action: str
    message: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class QaInput:
    content_uid: str
    source_text: str
    translated_text: str
    primary_category: str
    required_protected_tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QaResult:
    content_uid: str
    route: str
    issues: tuple[QaIssue, ...]
    qa_rule_set_version: str
    qa_input_hash: str


def qa_input_hash(item: QaInput) -> str:
    payload = {
        "ContentUid": item.content_uid,
        "SourceText": item.source_text,
        "TranslatedText": item.translated_text,
        "primaryCategory": item.primary_category,
        "requiredProtectedTokens": list(item.required_protected_tokens),
        "qaRuleSetVersion": QA_RULESET_VERSION,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _category_policy(item: QaInput) -> CategoryQaPolicy | None:
    return _CATEGORY_POLICIES.get(item.primary_category)


def _review_issues(item: QaInput, policy: CategoryQaPolicy) -> list[QaIssue]:
    source = item.source_text.strip()
    target = item.translated_text.strip()
    issues: list[QaIssue] = []

    if not source or not target:
        return issues

    # Exact identity is suspicious only when the content actually carries language.
    if source == target and _LATIN_WORD_RE.search(source):
        issues.append(
            QaIssue(
                issue_code=ISSUE_SOURCE_EQUALS_TARGET,
                severity="warning",
                action=QA_ROUTE_REVIEW,
                message="Source and translated text are identical.",
            )
        )


    if len(source) >= policy.min_length_for_ratio:
        ratio = len(target) / len(source)
        if ratio < policy.min_length_ratio or ratio > policy.max_length_ratio:
            issues.append(
                QaIssue(
                    issue_code=ISSUE_LENGTH_RATIO_SUSPICIOUS,
                    severity="warning",
                    action=QA_ROUTE_REVIEW,
                    message="Translated text length is unusually different from the source.",
                    details=(
                        f"{ratio:.4f}",
                        item.primary_category,
                        f"{policy.min_length_ratio:.4f}",
                        f"{policy.max_length_ratio:.4f}",
                    ),
                )
            )

    return issues


def evaluate_translation(item: QaInput) -> QaResult:
    issues: list[QaIssue] = []
    policy = _category_policy(item)

    if policy is None:
        issues.append(
            QaIssue(
                issue_code=ISSUE_CATEGORY_RULE_MISSING,
                severity="error",
                action=QA_ROUTE_FAIL,
                message="No QA policy is registered for primaryCategory.",
                details=(item.primary_category,),
            )
        )

    if not item.translated_text.strip():
        issues.append(
            QaIssue(
                issue_code=ISSUE_OUTPUT_EMPTY,
                severity="error",
                action=QA_ROUTE_RETRY,
                message="Translated output is empty.",
            )
        )

    for issue in validate_protected_syntax(
        item.required_protected_tokens,
        item.translated_text,
    ):
        if issue.kind == "missing":
            issues.append(
                QaIssue(
                    issue_code=ISSUE_PROTECTED_TOKEN_MISSING,
                    severity="error",
                    action=QA_ROUTE_RETRY,
                    message="Required protected runtime token is missing.",
                    details=issue.details,
                )
            )
        elif issue.kind == "added":
            issues.append(
                QaIssue(
                    issue_code=ISSUE_PROTECTED_TOKEN_ADDED,
                    severity="error",
                    action=QA_ROUTE_RETRY,
                    message="Unexpected protected runtime token was added.",
                    details=issue.details,
                )
            )
        elif issue.kind == "markup":
            issues.append(
                QaIssue(
                    issue_code=ISSUE_LSTAG_MALFORMED,
                    severity="error",
                    action=QA_ROUTE_RETRY,
                    message="LSTag markup is malformed.",
                    details=issue.details,
                )
            )

    if policy is not None:
        issues.extend(_review_issues(item, policy))

    if any(issue.action == QA_ROUTE_FAIL for issue in issues):
        route = QA_ROUTE_FAIL
    elif any(issue.action == QA_ROUTE_RETRY for issue in issues):
        route = QA_ROUTE_RETRY
    elif any(issue.action == QA_ROUTE_REVIEW for issue in issues):
        route = QA_ROUTE_REVIEW
    else:
        route = QA_ROUTE_PASS

    return QaResult(
        content_uid=item.content_uid,
        route=route,
        issues=tuple(issues),
        qa_rule_set_version=QA_RULESET_VERSION,
        qa_input_hash=qa_input_hash(item),
    )
