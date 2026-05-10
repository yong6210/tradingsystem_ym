from __future__ import annotations

from typing import Any


_STATUS_RANK = {
    "healthy": 0,
    "watch": 1,
    "manual_review": 2,
}

_APPROVAL_TIER_RANK = {
    "none": 0,
    "reason_only": 1,
    "downgrade_to_manual": 2,
}

_SIZING_TIER_RANK = {
    "none": 0,
    "soft_clamp": 1,
    "hard_clamp": 2,
}

def _mode_row_thin(row: dict[str, Any]) -> bool:
    if not row:
        return True
    if str(row.get("confidence") or "low").lower() == "low":
        return True
    sample_note = str(row.get("sample_note") or "").lower()
    return "thin" in sample_note


def _adverse_mode_rows(payload: dict[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    source = dict(payload or {})
    for axis in ("family", "regime", "session"):
        for row in list(source.get(axis) or []):
            item = dict(row)
            advisory_state = str(item.get("advisory_state") or "").lower()
            if advisory_state in {"watch", "research_only"} and not _mode_row_thin(item):
                rows.append((axis, item))
    return rows


def _find_first_negative_row(rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    for row in list(rows or []):
        item = dict(row)
        closed = int(item.get("closed", 0) or 0)
        rate = float(item.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0)
        if closed >= 4 and rate <= 0.3:
            return item
    return {}


def _find_first_positive_row(rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    for row in list(rows or []):
        item = dict(row)
        closed = int(item.get("closed", 0) or 0)
        rate = float(item.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0)
        if closed >= 4 and rate >= 0.5:
            return item
    return {}


def _find_worst_family_execution_row(payload: dict[str, Any] | None) -> dict[str, Any]:
    worst: dict[str, Any] = {}
    for row in list(dict(payload or {}).get("families") or []):
        item = dict(row)
        if _STATUS_RANK.get(str(item.get("status") or "healthy").lower(), 0) > _STATUS_RANK.get(
            str(worst.get("status") or "healthy").lower(),
            0,
        ):
            worst = item
    return worst


def _dedup_reason_codes(*groups: list[str]) -> list[str]:
    codes: list[str] = []
    for group in groups:
        for code in group:
            if code and code not in codes:
                codes.append(code)
    return codes


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
        return False
    return bool(default)


def _trace_summary(approval: dict[str, Any], sizing: dict[str, Any], portfolio: dict[str, Any]) -> str:
    approval_text = "approval unchanged"
    if str(approval.get("penalty_tier") or "") == "downgrade_to_manual":
        approval_text = "approval downgraded"
    elif _safe_bool(approval.get("applied")):
        approval_text = "approval review raised"

    sizing_text = "risk allowance unchanged"
    if _safe_bool(sizing.get("applied")):
        sizing_text = "risk allowance reduced"

    portfolio_tier = str(portfolio.get("tier") or "neutral")
    if portfolio_tier == "negative":
        portfolio_text = "portfolio ordering bias stayed negative"
    elif portfolio_tier == "positive":
        portfolio_text = "portfolio ordering bias stayed positive"
    else:
        portfolio_text = "portfolio ordering bias stayed neutral"

    return f"{approval_text}; {sizing_text}; {portfolio_text}"


def build_outcome_control_trace(
    *,
    execution_degradation_advisory: dict[str, Any] | None,
    family_execution_degradation_advisory: dict[str, Any] | None,
    mode_advisory: dict[str, Any] | None,
    score_to_outcome_funnel: dict[str, Any] | None,
) -> dict[str, Any] | None:
    execution_degradation = dict(execution_degradation_advisory or {})
    family_execution_degradation = dict(family_execution_degradation_advisory or {})
    mode_payload = dict(mode_advisory or {})
    score_to_outcome = dict(score_to_outcome_funnel or {})
    if not any([execution_degradation, family_execution_degradation, mode_payload, score_to_outcome]):
        return None

    degradation_status = str(execution_degradation.get("status") or "healthy").lower()
    decomposition = dict(score_to_outcome.get("decomposition") or {})
    historical = dict(score_to_outcome.get("historical_execution_outcomes") or {})
    adverse_mode_rows = _adverse_mode_rows(mode_payload)
    adverse_mode_reasons = [
        f"mode_advisory:{axis}:{str(row.get('advisory_state') or '').lower()}" for axis, row in adverse_mode_rows
    ]

    family_negative = _find_first_negative_row(list(decomposition.get("family") or []))
    regime_negative = _find_first_negative_row(list(decomposition.get("regime") or []))
    session_negative = _find_first_negative_row(list(decomposition.get("session") or []))
    family_positive = _find_first_positive_row(list(decomposition.get("family") or []))
    regime_positive = _find_first_positive_row(list(decomposition.get("regime") or []))
    session_positive = _find_first_positive_row(list(decomposition.get("session") or []))

    approval_reason_codes: list[str] = []
    if degradation_status in {"watch", "manual_review"}:
        approval_reason_codes.append(f"execution_degradation:{degradation_status}")
    if family_negative:
        approval_reason_codes.append("post_cost_conversion:weak_family_alignment")
    elif regime_negative:
        approval_reason_codes.append("post_cost_conversion:weak_regime_alignment")
    elif session_negative:
        approval_reason_codes.append("post_cost_conversion:weak_session_alignment")
    approval_reason_codes.extend(adverse_mode_reasons)
    approval_reason_codes = _dedup_reason_codes(approval_reason_codes)

    if not approval_reason_codes:
        approval_penalty = {
            "status": "healthy",
            "penalty_tier": "none",
            "applied": False,
            "reason_codes": [],
            "summary": "approval remained unchanged by execution and outcome controls",
        }
    else:
        approval_status = "watch"
        approval_tier = "reason_only"
        if degradation_status == "manual_review" or (family_negative and adverse_mode_rows):
            approval_status = "manual_review"
            approval_tier = "downgrade_to_manual"
        approval_penalty = {
            "status": approval_status,
            "penalty_tier": approval_tier,
            "applied": True,
            "reason_codes": approval_reason_codes,
            "summary": (
                "approval downgraded because execution degradation elevated and post-cost outcome weakened"
                if approval_tier == "downgrade_to_manual"
                else "approval reasons were raised because execution or post-cost outcome drifted"
            ),
        }

    family_execution_row = _find_worst_family_execution_row(family_execution_degradation)
    family_execution_status = str(family_execution_row.get("status") or "healthy").lower()
    family_execution_reason = (
        [f"family_execution_degradation:{family_execution_status}"]
        if family_execution_status in {"watch", "manual_review"}
        else []
    )

    sizing_multiplier = 1.0
    sizing_status = "healthy"
    sizing_tier = "none"
    sizing_reason_codes: list[str] = []
    if family_execution_status == "manual_review":
        sizing_multiplier = min(sizing_multiplier, 0.5)
        sizing_status = "manual_review"
        sizing_tier = "hard_clamp"
        sizing_reason_codes.extend(family_execution_reason)
    elif family_execution_status == "watch":
        sizing_multiplier = min(sizing_multiplier, 0.75)
        sizing_status = "watch"
        sizing_tier = "soft_clamp"
        sizing_reason_codes.extend(family_execution_reason)

    if family_negative:
        sizing_multiplier = min(sizing_multiplier, 0.5)
        sizing_status = "manual_review"
        sizing_tier = "hard_clamp"
        sizing_reason_codes.append("post_cost_conversion:weak_family_alignment")

    if adverse_mode_rows:
        sizing_multiplier = min(sizing_multiplier, 0.75)
        if sizing_tier == "none":
            sizing_status = "watch"
            sizing_tier = "soft_clamp"
        sizing_reason_codes.extend(adverse_mode_reasons)

    if regime_negative:
        sizing_multiplier = min(sizing_multiplier, 0.75)
        if sizing_tier == "none":
            sizing_status = "watch"
            sizing_tier = "soft_clamp"
        sizing_reason_codes.append("regime_outcome:weak_alignment")
    if session_negative:
        sizing_multiplier = min(sizing_multiplier, 0.75)
        if sizing_tier == "none":
            sizing_status = "watch"
            sizing_tier = "soft_clamp"
        sizing_reason_codes.append("session_outcome:weak_alignment")

    sizing_reason_codes = _dedup_reason_codes(sizing_reason_codes)
    sizing_penalty = {
        "status": sizing_status,
        "penalty_tier": sizing_tier,
        "applied": sizing_multiplier < 1.0,
        "multiplier": round(sizing_multiplier, 4),
        "reason_codes": sizing_reason_codes,
        "summary": (
            "risk allowance reduced because family execution quality or post-cost conversion is weak"
            if sizing_tier == "hard_clamp"
            else (
                "risk allowance reduced because bucket-level outcome or mode signals drifted"
                if sizing_tier == "soft_clamp"
                else "risk allowance remained unchanged by outcome controls"
            )
        ),
    }

    score_delta = 0.0
    portfolio_reason_codes: list[str] = []
    if family_negative:
        score_delta -= 2.5
        portfolio_reason_codes.append("family_outcome:negative")
    elif family_positive:
        score_delta += 2.5
        portfolio_reason_codes.append("family_outcome:positive")
    if regime_negative:
        score_delta -= 0.5
        portfolio_reason_codes.append("regime_outcome:negative")
    elif regime_positive:
        score_delta += 0.5
        portfolio_reason_codes.append("regime_outcome:positive")
    if session_negative:
        score_delta -= 0.5
        portfolio_reason_codes.append("session_outcome:negative")
    elif session_positive:
        score_delta += 0.5
        portfolio_reason_codes.append("session_outcome:positive")
    score_delta = max(min(score_delta, 3.0), -3.0)
    portfolio_tier = "neutral"
    if score_delta < 0:
        portfolio_tier = "negative"
    elif score_delta > 0:
        portfolio_tier = "positive"
    portfolio_bias = {
        "tier": portfolio_tier,
        "applied": score_delta != 0.0,
        "score_delta": round(score_delta, 4),
        "reason_codes": _dedup_reason_codes(portfolio_reason_codes),
        "summary": (
            "portfolio ordering bias stayed negative"
            if portfolio_tier == "negative"
            else ("portfolio ordering bias stayed positive" if portfolio_tier == "positive" else "portfolio ordering bias stayed neutral")
        ),
    }

    return {
        "available": True,
        "summary": _trace_summary(approval_penalty, sizing_penalty, portfolio_bias),
        "approval_penalty": approval_penalty,
        "sizing_penalty": sizing_penalty,
        "portfolio_bias": portfolio_bias,
        "source_summary": {
            "execution_degradation_status": degradation_status or "healthy",
            "family_execution_status": family_execution_status or "healthy",
            "mode_advisory_state": str((adverse_mode_rows[:1] or [("", {})])[0][1].get("advisory_state") or "keep_current_mode"),
            "baseline_cost_profitable_rate_from_closed": float(
                historical.get("baseline_cost_profitable_rate_from_closed", 0.0) or 0.0
            ),
        },
    }


def summarize_outcome_control_trace(trace: dict[str, Any] | None) -> dict[str, Any] | None:
    payload = dict(trace or {})
    if not payload:
        return None
    approval = dict(payload.get("approval_penalty") or {})
    sizing = dict(payload.get("sizing_penalty") or {})
    portfolio = dict(payload.get("portfolio_bias") or {})
    reason_codes = _dedup_reason_codes(
        list(approval.get("reason_codes") or []),
        list(sizing.get("reason_codes") or []),
        list(portfolio.get("reason_codes") or []),
    )
    return {
        "available": _safe_bool(payload.get("available", False)),
        "summary": str(payload.get("summary") or ""),
        "approval_penalty_status": str(approval.get("status") or "healthy"),
        "approval_penalty_tier": str(approval.get("penalty_tier") or "none"),
        "sizing_penalty_status": str(sizing.get("status") or "healthy"),
        "sizing_penalty_tier": str(sizing.get("penalty_tier") or "none"),
        "sizing_multiplier": float(sizing.get("multiplier", 1.0) or 1.0),
        "portfolio_bias_tier": str(portfolio.get("tier") or "neutral"),
        "portfolio_bias_score_delta": float(portfolio.get("score_delta", 0.0) or 0.0),
        "top_reason_codes": reason_codes[:5],
    }


def runtime_outcome_control_trace(
    *,
    recent_intents: list[dict[str, Any]],
    accepted_candidate_rows: list[dict[str, Any]],
    blocked_candidate_rows: list[dict[str, Any]],
    fallback_trace: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    approval_rows = [
        dict(item.get("outcome_approval_penalty") or {})
        for item in recent_intents
        if isinstance(item, dict) and item.get("outcome_approval_penalty")
    ]
    approval_penalty = max(
        approval_rows,
        key=lambda item: _APPROVAL_TIER_RANK.get(str(item.get("penalty_tier") or "none"), 0),
        default=dict(dict(fallback_trace or {}).get("approval_penalty") or {}),
    )

    candidate_rows = [dict(row) for row in [*accepted_candidate_rows, *blocked_candidate_rows]]
    sizing_rows = []
    for row in candidate_rows:
        strategy_sizing = dict(row.get("strategy_sizing") or {})
        adjustment = dict(strategy_sizing.get("outcome_risk_adjustment") or {})
        if adjustment:
            sizing_rows.append(adjustment)
    sizing_penalty = max(
        sizing_rows,
        key=lambda item: (
            _SIZING_TIER_RANK.get(str(item.get("penalty_tier") or "none"), 0),
            -float(item.get("multiplier", 1.0) or 1.0),
        ),
        default=dict(dict(fallback_trace or {}).get("sizing_penalty") or {}),
    )

    bias_rows = [dict(row.get("outcome_bias") or {}) for row in candidate_rows if dict(row.get("outcome_bias") or {})]
    positive_count = sum(1 for row in bias_rows if str(row.get("tier") or "") == "positive")
    negative_count = sum(1 for row in bias_rows if str(row.get("tier") or "") == "negative")
    neutral_count = sum(1 for row in bias_rows if str(row.get("tier") or "neutral") == "neutral")
    average_score_delta = round(
        sum(float(row.get("score_delta", 0.0) or 0.0) for row in bias_rows) / len(bias_rows),
        4,
    ) if bias_rows else float(dict(dict(fallback_trace or {}).get("portfolio_bias") or {}).get("score_delta", 0.0) or 0.0)
    portfolio_bias = dict(dict(fallback_trace or {}).get("portfolio_bias") or {})
    if bias_rows:
        if negative_count > positive_count:
            tier = "negative"
        elif positive_count > negative_count:
            tier = "positive"
        else:
            tier = "neutral"
        portfolio_bias = {
            "tier": tier,
            "applied": any(_safe_bool(row.get("applied")) for row in bias_rows),
            "score_delta": average_score_delta,
            "reason_codes": _dedup_reason_codes(*[list(row.get("reason_codes") or []) for row in bias_rows]),
            "distribution": {
                "positive": positive_count,
                "negative": negative_count,
                "neutral": neutral_count,
            },
        }
    else:
        portfolio_bias.setdefault("distribution", {"positive": 0, "negative": 0, "neutral": 0})

    if not any([approval_penalty, sizing_penalty, portfolio_bias]):
        return None

    trace = {
        "available": True,
        "summary": _trace_summary(approval_penalty, sizing_penalty, portfolio_bias),
        "approval_penalty": approval_penalty or {
            "status": "healthy",
            "penalty_tier": "none",
            "applied": False,
            "reason_codes": [],
        },
        "sizing_penalty": sizing_penalty or {
            "status": "healthy",
            "penalty_tier": "none",
            "applied": False,
            "multiplier": 1.0,
            "reason_codes": [],
        },
        "portfolio_bias": portfolio_bias or {
            "tier": "neutral",
            "applied": False,
            "score_delta": 0.0,
            "reason_codes": [],
            "distribution": {"positive": 0, "negative": 0, "neutral": 0},
        },
    }
    return trace
