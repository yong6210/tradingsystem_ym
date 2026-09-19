"""Explicit release of one tranche frozen before initial entry."""
from dataclasses import dataclass
from .evidence import Evidence, timestamp
from .models import require_flags
from .zone_observer import ZoneObserver


@dataclass(frozen=True)
class SplitSubmission:
    plan_id: str
    index: int
    decision_ms: int
    support: ZoneObserver
    target: ZoneObserver
    context: Evidence
    thesis_valid: bool
    context_known: bool
    conflicts_resolved: bool
    reason: str

    def __post_init__(self):
        timestamp(self.decision_ms)
        require_flags(self.thesis_valid, self.context_known, self.conflicts_resolved)
        if type(self.index) is not int or self.index < 0 or not self.plan_id.strip():
            raise ValueError("declared campaign and tranche index required")
