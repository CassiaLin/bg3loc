from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable


# These lexemes have runtime substitution semantics and therefore remain exact.
# Square-bracket prose and presentation markup are intentionally excluded.
_EXACT_TOKEN_RE = re.compile(r"(\{[^{}]+\}|%(?:\d+\$)?[sdif])")
_LSTAG_RE = re.compile(r"<\s*(/?)\s*LSTag\b([^>]*)>", re.IGNORECASE)
_LSTAG_MARKER_RE = re.compile(r"<\s*/?\s*LSTag\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ProtectedSyntaxIssue:
    kind: str
    details: tuple[str, ...] = ()


def extract_protected_tokens(text: str) -> list[str]:
    """Return exact runtime lexemes in occurrence order, including duplicates."""
    return [match.group(0) for match in _EXACT_TOKEN_RE.finditer(text)]


def validate_protected_syntax(required_tokens: Iterable[str], candidate: str) -> list[ProtectedSyntaxIssue]:
    """Compare exact lexemes and validate candidate BG3 structural markup."""
    required = Counter(str(token) for token in required_tokens)
    actual = Counter(extract_protected_tokens(candidate))
    issues: list[ProtectedSyntaxIssue] = []
    missing = tuple((required - actual).elements())
    added = tuple((actual - required).elements())
    if missing:
        issues.append(ProtectedSyntaxIssue("missing", missing))
    if added:
        issues.append(ProtectedSyntaxIssue("added", added))
    markup_errors = validate_lstag_structure(candidate)
    if markup_errors:
        issues.append(ProtectedSyntaxIssue("markup", tuple(markup_errors)))
    return issues


def validate_lstag_structure(text: str) -> list[str]:
    """Validate LSTag serialization without treating localized payload as identity."""
    matches = list(_LSTAG_RE.finditer(text))
    errors: list[str] = []
    stack: list[int] = []

    # A marker not consumed by the grammar is truncated or otherwise malformed.
    covered_markers = {match.start() for match in matches}
    for marker in _LSTAG_MARKER_RE.finditer(text):
        if marker.start() not in covered_markers:
            errors.append("malformed LSTag")

    for match in matches:
        closing, raw_attributes = match.groups()
        attributes = raw_attributes.strip()
        self_closing = not closing and attributes.endswith("/")
        if closing:
            if attributes:
                errors.append("closing LSTag has attributes")
            if not stack:
                errors.append("unexpected closing LSTag")
            else:
                stack.pop()
            continue

        if not self_closing:
            stack.append(match.start())

    if stack:
        errors.extend("unclosed LSTag" for _ in stack)
    return errors


def has_valid_lstag_structure(text: str) -> bool:
    """Return whether text contains at least one internally valid LSTag envelope."""
    return bool(_LSTAG_RE.search(text)) and not validate_lstag_structure(text)
