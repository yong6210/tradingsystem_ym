from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.enums import RiskGateState
from app.services.metrics import summarize_outcomes
from app.services.scoring import score_strategy


@dataclass(slots=True)
class OutcomeStub:
    hit_1r: bool
    hit_2r: bool
    hit_3r: bool
    regime_at_touch: float
    mae_atr: float
    entry_ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def test_summarize_outcomes_calculates_core_stats() -> None:
    outcomes = [
        OutcomeStub(hit_1r=True, hit_2r=False, hit_3r=False, regime_at_touch=1.0, mae_atr=0.5),
        OutcomeStub(hit_1r=True, hit_2r=True, hit_3r=False, regime_at_touch=1.0, mae_atr=0.6),
        OutcomeStub(hit_1r=True, hit_2r=True, hit_3r=True, regime_at_touch=1.2, mae_atr=0.8),
        OutcomeStub(hit_1r=False, hit_2r=False, hit_3r=False, regime_at_touch=2.0, mae_atr=1.8),
    ]

    snapshot = summarize_outcomes(outcomes)  # type: ignore[arg-type]

    assert snapshot.sample_size == 4
    assert snapshot.win_rate == 0.75
    assert snapshot.avg_win == 2.0
    assert snapshot.avg_loss == 1.0
    assert snapshot.ev == 1.25
    assert snapshot.jump_rate == 0.25


def test_score_strategy_penalizes_throttled_state() -> None:
    outcomes = [
        OutcomeStub(hit_1r=True, hit_2r=False, hit_3r=False, regime_at_touch=1.0, mae_atr=0.4)
        for _ in range(50)
    ]
    snapshot = summarize_outcomes(outcomes)  # type: ignore[arg-type]

    open_score = score_strategy(snapshot, RiskGateState.OPEN)
    throttled_score = score_strategy(snapshot, RiskGateState.THROTTLED)

    assert open_score.total_score > throttled_score.total_score
