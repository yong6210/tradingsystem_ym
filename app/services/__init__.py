from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.metrics import MetricSnapshot, summarize_outcomes
    from app.services.risk_gate import RiskSnapshot, evaluate_risk_gate
    from app.services.scoring import StrategyScore, score_strategy

_EXPORTS = {
    "MetricSnapshot": ("app.services.metrics", "MetricSnapshot"),
    "summarize_outcomes": ("app.services.metrics", "summarize_outcomes"),
    "RiskSnapshot": ("app.services.risk_gate", "RiskSnapshot"),
    "evaluate_risk_gate": ("app.services.risk_gate", "evaluate_risk_gate"),
    "StrategyScore": ("app.services.scoring", "StrategyScore"),
    "score_strategy": ("app.services.scoring", "score_strategy"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
