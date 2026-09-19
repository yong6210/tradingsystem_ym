"""Purpose-specific increase requests; confirmation belongs to the running engine."""
from dataclasses import dataclass
from decimal import Decimal
from .evidence import Evidence, timestamp
from .models import positive, require_flags
from .zone_observer import ZoneObserver


@dataclass(frozen=True)
class AddSubmission:
    plan_id: str
    decision_ms: int
    confirmed_ms: int
    support: ZoneObserver
    target: ZoneObserver
    context: Evidence
    thesis_valid: bool
    context_known: bool
    conflicts_resolved: bool
    independent_reason: str
    maximum_qty: Decimal
    maximum_loss: Decimal

    def __post_init__(self):
        timestamp(self.decision_ms)
        timestamp(self.confirmed_ms)
        require_flags(self.thesis_valid, self.context_known, self.conflicts_resolved)
        for name in ("maximum_qty", "maximum_loss"):
            object.__setattr__(self, name, positive(getattr(self, name)))
        if not self.plan_id.strip():
            raise ValueError("campaign id required")


@dataclass(frozen=True)
class ReentrySubmission(AddSubmission):
    reduction_fill_id: str

    def __post_init__(self):
        super().__post_init__()
        if not self.reduction_fill_id.strip():
            raise ValueError("actual reduction fill required")


@dataclass(frozen=True)
class ProfitAddSubmission(AddSubmission):
    prior_resistance_key: str
    breakout_end_ms: int

    def __post_init__(self):
        super().__post_init__()
        timestamp(self.breakout_end_ms)
        if not self.prior_resistance_key.strip():
            raise ValueError("registered prior resistance required")
