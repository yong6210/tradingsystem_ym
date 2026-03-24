from __future__ import annotations

from typing import Any


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def build_outcome_attribution(
    *,
    score_to_outcome_funnel: dict[str, Any] | None,
    performance_decomposition_summary: dict[str, Any] | None = None,
    execution_friction_measurement: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    funnel_payload = dict(score_to_outcome_funnel or {})
    money_funnel = dict(funnel_payload.get("money_funnel") or {})
    if not money_funnel:
        return None

    history = dict(funnel_payload.get("historical_execution_outcomes") or {})
    historical_expected = dict(money_funnel.get("historical_expected_r") or {})
    historical_realized = dict(money_funnel.get("historical_realized_r") or {})
    historical_gap = dict(money_funnel.get("historical_gap_r") or {})
    performance_payload = dict(performance_decomposition_summary or {})
    execution_payload = dict(execution_friction_measurement or {})

    closed_trade_count = _int(history.get("closed", 0))
    strategy_component_r = round(_float(historical_expected.get("closed", 0.0)), 4)
    raw_realized_r = round(_float(historical_realized.get("raw_closed", 0.0)), 4)
    post_cost_realized_r = round(_float(historical_realized.get("post_cost_closed", 0.0)), 4)
    execution_component_r = round(post_cost_realized_r - raw_realized_r, 4)
    condition_component_r = round(raw_realized_r - strategy_component_r, 4)
    fill_capture_gap_r = round(max(0.0, _float(historical_gap.get("submitted_to_filled", 0.0))), 4)
    closed_post_cost_delta_r = round(post_cost_realized_r - strategy_component_r, 4)

    strongest_drag_source = "none"
    strongest_drag_value = 0.0
    for source, value in (
        ("execution_component", abs(min(execution_component_r, 0.0))),
        ("condition_component", abs(min(condition_component_r, 0.0))),
        ("fill_capture_gap", max(fill_capture_gap_r, 0.0)),
    ):
        if value > strongest_drag_value:
            strongest_drag_source = source
            strongest_drag_value = float(value)

    friction_state = str(execution_payload.get("friction_state") or "unknown").lower()
    weakest_execution_axis = str(execution_payload.get("weakest_axis") or "").strip().lower()
    tuning_focus = dict((list(performance_payload.get("tuning_focus") or [])[:1] or [{}])[0])
    condition_focus = str(tuning_focus.get("focus") or "").strip().lower()
    condition_bucket = str(tuning_focus.get("bucket") or "").strip().lower()

    if closed_trade_count < 4:
        confidence = "low"
    elif friction_state in {"degraded_friction", "insufficient_measurement"}:
        confidence = "medium"
    else:
        confidence = "high"

    if strongest_drag_source == "execution_component":
        summary = (
            "Closed-trade post-cost attribution is being softened mainly by measured execution drag; treat cost and "
            "friction remediation as the first review axis before changing the strategy thesis."
        )
    elif strongest_drag_source == "condition_component":
        summary = (
            "Closed-trade post-cost attribution is being softened mainly by realized condition drift versus expected "
            "edge; treat regime/session fit as the first review axis before rewriting execution assumptions."
        )
    elif strongest_drag_source == "fill_capture_gap":
        summary = (
            "The largest current money leak is expected edge that never converted from submit to fill; treat execution "
            "conversion and missed-fill impact as the first review axis."
        )
    else:
        summary = (
            "Closed-trade post-cost attribution is broadly aligned with current expected edge; keep monitoring for "
            "sample growth before increasing confidence."
        )

    reason_codes = _dedupe(
        [
            f"closed_trades:{closed_trade_count}",
            f"strongest_drag:{strongest_drag_source}",
            f"friction:{friction_state}" if friction_state else "",
            f"execution_axis:{weakest_execution_axis}" if weakest_execution_axis else "",
            f"condition_focus:{condition_focus}" if condition_focus else "",
            f"condition_bucket:{condition_bucket}" if condition_bucket else "",
        ]
    )

    return {
        "available": True,
        "advisory_only": True,
        "confidence": confidence,
        "attribution_basis": "closed_expected_ev_proxy_plus_post_cost_realized_decomposition",
        "closed_trade_count": closed_trade_count,
        "strategy_component_r": strategy_component_r,
        "execution_component_r": execution_component_r,
        "condition_component_r": condition_component_r,
        "fill_capture_gap_r": fill_capture_gap_r,
        "closed_expected_r": strategy_component_r,
        "closed_raw_realized_r": raw_realized_r,
        "closed_post_cost_realized_r": post_cost_realized_r,
        "closed_post_cost_delta_r": closed_post_cost_delta_r,
        "strongest_drag_source": strongest_drag_source,
        "summary": summary,
        "reason_codes": reason_codes,
        "source_summary": {
            "friction_state": friction_state or "unknown",
            "weakest_execution_axis": weakest_execution_axis or None,
            "condition_focus": condition_focus or None,
            "condition_bucket": condition_bucket or None,
            "money_funnel_summary": str(money_funnel.get("summary") or ""),
        },
    }


def summarize_outcome_attribution(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    source = dict(payload or {})
    if not source:
        return None
    return {
        "available": bool(source.get("available", False)),
        "advisory_only": bool(source.get("advisory_only", True)),
        "confidence": str(source.get("confidence") or "low"),
        "closed_trade_count": _int(source.get("closed_trade_count", 0)),
        "strategy_component_r": round(_float(source.get("strategy_component_r", 0.0)), 4),
        "execution_component_r": round(_float(source.get("execution_component_r", 0.0)), 4),
        "condition_component_r": round(_float(source.get("condition_component_r", 0.0)), 4),
        "fill_capture_gap_r": round(_float(source.get("fill_capture_gap_r", 0.0)), 4),
        "closed_expected_r": round(_float(source.get("closed_expected_r", 0.0)), 4),
        "closed_post_cost_realized_r": round(_float(source.get("closed_post_cost_realized_r", 0.0)), 4),
        "closed_post_cost_delta_r": round(_float(source.get("closed_post_cost_delta_r", 0.0)), 4),
        "strongest_drag_source": str(source.get("strongest_drag_source") or "none"),
        "summary": str(source.get("summary") or ""),
        "reason_codes": list(source.get("reason_codes") or []),
        "source_summary": dict(source.get("source_summary") or {}),
    }
