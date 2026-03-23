from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import RiskGateState
from app.services.metrics import MetricSnapshot


@dataclass(slots=True)
class StrategyScore:
    total_score: float
    grade: str
    recommendation: str
    edge_score: float
    robustness_score: float
    execution_score: float
    risk_penalty: float


def score_strategy(metric: MetricSnapshot, risk_state: RiskGateState) -> StrategyScore:
    edge_score = _clip((metric.ev + 0.3) / 0.9 * 100.0)
    consistency = _clip((metric.win_rate - 0.35) / 0.35 * 100.0)
    robustness_score = _clip((metric.sample_size / 250.0) * 100.0)
    execution_score = _clip((1.6 - metric.avg_loss) / 1.6 * 100.0)

    blended = (
        edge_score * 0.40
        + consistency * 0.20
        + robustness_score * 0.25
        + execution_score * 0.15
    )

    if risk_state == RiskGateState.THROTTLED:
        risk_penalty = 15.0
    elif risk_state == RiskGateState.CLOSED:
        risk_penalty = 35.0
    else:
        risk_penalty = 0.0

    if metric.sample_size < 40:
        blended = min(blended, 55.0)

    total = _clip(blended - risk_penalty)
    grade, recommendation = _label(total)
    return StrategyScore(
        total_score=round(total, 2),
        grade=grade,
        recommendation=recommendation,
        edge_score=round(edge_score, 2),
        robustness_score=round(robustness_score, 2),
        execution_score=round(execution_score, 2),
        risk_penalty=risk_penalty,
    )


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _label(score: float) -> tuple[str, str]:
    if score >= 80.0:
        return ("A", "deploy-small-capital")
    if score >= 70.0:
        return ("B", "paper-and-limited-live")
    if score >= 60.0:
        return ("C", "improve-before-live")
    if score >= 45.0:
        return ("D", "research-only")
    return ("F", "do-not-deploy")
