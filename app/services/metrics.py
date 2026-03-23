from __future__ import annotations

from dataclasses import dataclass

from app.db.models import ZoneOutcome


@dataclass(slots=True)
class MetricSnapshot:
    win_rate: float
    avg_win: float
    avg_loss: float
    ev: float
    p1r: float
    p2r: float
    p3r: float
    sample_size: int
    consecutive_losses: int
    jump_rate: float


def _outcome_to_r(outcome: ZoneOutcome) -> float:
    if outcome.hit_3r:
        return 3.0
    if outcome.hit_2r:
        return 2.0
    if outcome.hit_1r:
        return 1.0
    return -1.0


def _jump_flag(outcome: ZoneOutcome) -> bool:
    return outcome.regime_at_touch >= 1.5 or abs(outcome.mae_atr) >= 1.7


def summarize_outcomes(outcomes: list[ZoneOutcome]) -> MetricSnapshot:
    if not outcomes:
        return MetricSnapshot(
            win_rate=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            ev=0.0,
            p1r=0.0,
            p2r=0.0,
            p3r=0.0,
            sample_size=0,
            consecutive_losses=0,
            jump_rate=0.0,
        )

    rs = [_outcome_to_r(o) for o in outcomes]
    wins = [r for r in rs if r > 0]
    losses = [abs(r) for r in rs if r <= 0]
    count = len(rs)

    p1r = sum(1 for o in outcomes if o.hit_1r) / count
    p2r = sum(1 for o in outcomes if o.hit_2r) / count
    p3r = sum(1 for o in outcomes if o.hit_3r) / count
    jump_rate = sum(1 for o in outcomes if _jump_flag(o)) / count

    return MetricSnapshot(
        win_rate=len(wins) / count,
        avg_win=(sum(wins) / len(wins)) if wins else 0.0,
        avg_loss=(sum(losses) / len(losses)) if losses else 0.0,
        ev=sum(rs) / count,
        p1r=p1r,
        p2r=p2r,
        p3r=p3r,
        sample_size=count,
        consecutive_losses=_compute_consecutive_losses(rs),
        jump_rate=jump_rate,
    )


def _compute_consecutive_losses(r_values: list[float]) -> int:
    # Trailing loss streak from most recent trades first.
    streak = 0
    for value in r_values:
        if value <= 0:
            streak += 1
        else:
            break
    return streak
