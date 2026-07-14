from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


PRIORITY_ORDER = {"urgent": 0, "high": 1, "medium": 2, "ux": 3, "info": 4}


@dataclass(slots=True)
class Signal:
    source: str
    event: str
    priority: str
    summary_fa: str
    count: int = 1
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    evidence: dict[str, Any] = field(default_factory=dict)
    source_url: str | None = None

    @property
    def fingerprint(self) -> str:
        discriminator = (
            self.evidence.get("issue_id")
            or self.evidence.get("path")
            or self.evidence.get("metric")
            or self.evidence.get("stage")
            or ""
        )
        raw = f"{self.source}:{self.event}:{discriminator}:{self.evidence.get('stage', '')}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "fingerprint": self.fingerprint}


@dataclass(slots=True)
class Candidate:
    fingerprint: str
    title_fa: str
    problem_fa: str
    priority: str
    confidence: float
    evidence: list[dict[str, Any]]
    reproducible_hint: str
    source_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RunReport:
    run_id: str
    started_at: str
    phase: str
    status: str = "running"
    signals: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    fixes: list[dict[str, Any]] = field(default_factory=list)
    source_health: dict[str, str] = field(default_factory=dict)
    finished_at: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
