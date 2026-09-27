from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

# Canonical BG3 localization handle pattern (e.g. h12345678g1234g1234g1234g123456789abc;1)
HANDLE_PATTERN = re.compile(
    r'(?<![A-Za-z0-9_])(?P<uid>h[0-9a-f]{8}g[0-9a-f]{4}g[0-9a-f]{4}g[0-9a-f]{4}g[0-9a-f]{12})(?:;(?P<ver>[0-9]+))?(?![A-Za-z0-9_])',
    re.IGNORECASE
)


@dataclass(slots=True)
class ResearchEvidence:
    sourceRole: str
    resourcePath: str
    evidenceType: str
    ruleId: str
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "sourceRole": self.sourceRole,
            "resourcePath": self.resourcePath,
            "evidenceType": self.evidenceType,
            "ruleId": self.ruleId,
        }
        if self.properties:
            d["properties"] = self.properties
        return d


@dataclass(slots=True)
class ResearchMapping:
    contentUid: str
    mappingType: str
    classification: str
    evidence: list[ResearchEvidence] = field(default_factory=list)
    version: str = ""
    reviewRequired: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "contentUid": self.contentUid,
            "mappingType": self.mappingType,
            "classification": self.classification,
            "reviewRequired": self.reviewRequired,
            "evidence": [e.to_dict() for e in self.evidence],
        }
        if self.version:
            d["version"] = self.version
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass(slots=True)
class ResearchScanResource:
    pakName: str
    internalPath: str
    resourceFormat: str
    sourceRole: str
    size: int = 0
    sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ResearchRunManifest:
    buildId: str
    gameVersion: str
    researchSchemaVersion: str = "1.0.0"
    generatedAtUtc: str = ""
    resourceCounts: dict[str, int] = field(default_factory=dict)
    mappingCounts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)