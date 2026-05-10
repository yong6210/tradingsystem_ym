from __future__ import annotations

from typing import Any


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
    return True if value else False


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _rate(numerator: float, denominator: float) -> float:
    if abs(float(denominator)) <= 1e-9:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def build_outcome_funnel_operating_kpis(score_to_outcome_funnel: dict[str, Any] | None) -> dict[str, Any] | None:
    payload = dict(score_to_outcome_funnel or {})
    if not payload:
        return None

    snapshot = dict(payload.get("snapshot_selection") or {})
    history = dict(payload.get("historical_execution_outcomes") or {})
    money_funnel = dict(payload.get("money_funnel") or {})
    expected_r = dict(money_funnel.get("historical_expected_r") or {})
    realized_r = dict(money_funnel.get("historical_realized_r") or {})

    runtime_candidates = _int(snapshot.get("runtime_candidates", 0))
    accepted_candidates = _int(snapshot.get("accepted_candidates", 0))
    submitted = _int(history.get("submitted", 0))
    filled = _int(history.get("filled", 0))
    closed = _int(history.get("closed", 0))
    profitable = _int(history.get("profitable", 0))
    baseline_cost_profitable = _int(history.get("baseline_cost_profitable", 0))
    report_window_days = _int(payload.get("report_window_days", 0))

    runtime_accept_rate = _rate(accepted_candidates, runtime_candidates)
    submitted_fill_rate = _rate(filled, submitted)
    filled_close_rate = _rate(closed, filled)
    closed_profit_rate = _rate(profitable, closed)
    closed_post_cost_survival_rate = _rate(baseline_cost_profitable, closed)
    closed_trades_per_day = round(closed / report_window_days, 4) if report_window_days > 0 else 0.0

    return {
        "available": _safe_bool(payload.get("available", False)),
        "primary_focus": "after_cost_edge_proof",
        "report_window_days": report_window_days,
        "closed_trades_per_day": closed_trades_per_day,
        "cost_adjusted_survival_rate": closed_post_cost_survival_rate,
        "stage_conversion_rates": {
            "runtime_to_accepted": runtime_accept_rate,
            "submitted_to_filled": submitted_fill_rate,
            "filled_to_closed": filled_close_rate,
            "closed_to_profitable": closed_profit_rate,
            "closed_to_post_cost_profitable": closed_post_cost_survival_rate,
        },
        "expected_r_per_stage": {
            "generated": round(_float(expected_r.get("generated", 0.0)), 4),
            "submitted": round(_float(expected_r.get("submitted", 0.0)), 4),
            "filled": round(_float(expected_r.get("filled", 0.0)), 4),
            "closed": round(_float(expected_r.get("closed", 0.0)), 4),
        },
        "realized_r_per_stage": {
            "raw_closed": round(_float(realized_r.get("raw_closed", 0.0)), 4),
            "post_cost_closed": round(_float(realized_r.get("post_cost_closed", 0.0)), 4),
            "cost_drag": round(_float(realized_r.get("cost_drag", 0.0)), 4),
        },
        "summary": (
            f"runtime_accept={runtime_accept_rate:.4f} | submitted_fill={submitted_fill_rate:.4f} | "
            f"filled_close={filled_close_rate:.4f} | closed_post_cost_survival={closed_post_cost_survival_rate:.4f} | "
            f"closed_per_day={closed_trades_per_day:.4f}"
        ),
    }
