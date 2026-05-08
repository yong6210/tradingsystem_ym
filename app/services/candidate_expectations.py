from __future__ import annotations

from typing import Any


def expectation_contract(
    *,
    validity: dict[str, Any] | None,
    ev: float = 0.0,
    recommended_risk_r: float = 0.0,
) -> dict[str, Any]:
    payload = dict(validity or {})
    expected_win_prob = float(payload.get("expected_win_prob", 0.0) or 0.0)
    expected_ev_r = float(payload.get("expected_ev_r", ev) or 0.0)
    expected_tp1_prob = float(payload.get("expected_tp1_prob", payload.get("p1r_est", 0.0)) or 0.0)
    expected_tp2_prob = float(payload.get("expected_tp2_prob", payload.get("p2r_est", 0.0)) or 0.0)
    expected_tp3_prob = float(payload.get("expected_tp3_prob", payload.get("p3r_est", 0.0)) or 0.0)
    expected_ev_at_recommended_size_r = float(
        payload.get("expected_ev_at_recommended_size_r", expected_ev_r * float(recommended_risk_r or 0.0)) or 0.0
    )
    expected_summary = str(payload.get("expected_summary", "") or "").strip()
    if not expected_summary:
        expected_summary = (
            f"win≈{expected_win_prob * 100.0:.1f}%, "
            f"EV≈{expected_ev_r:+.2f}R, "
            f"TP1≈{expected_tp1_prob * 100.0:.1f}%, "
            f"TP2≈{expected_tp2_prob * 100.0:.1f}%, "
            f"TP3≈{expected_tp3_prob * 100.0:.1f}%"
        )
    return {
        "expected_win_prob": round(expected_win_prob, 4),
        "expected_ev_r": round(expected_ev_r, 4),
        "expected_tp1_prob": round(expected_tp1_prob, 4),
        "expected_tp2_prob": round(expected_tp2_prob, 4),
        "expected_tp3_prob": round(expected_tp3_prob, 4),
        "expected_ev_at_recommended_size_r": round(expected_ev_at_recommended_size_r, 4),
        "expected_summary": expected_summary,
    }


def block_reason_message(block_reason: str | None) -> str | None:
    reason = str(block_reason or "").strip()
    if not reason:
        return None
    mapping = {
        "thesis_cluster_cap_zero_risk": "Blocked: thesis cluster cap already consumes all allocatable risk.",
        "mode_shadow_only": "Blocked: current mode is shadow-only, so this candidate is monitor-only.",
        "mode_daily_trade_limit_reached": "Blocked: daily trade limit is already reached.",
        "mode_total_risk_cap_reached": "Blocked: total risk cap would be exceeded.",
        "total_cap_reached": "Blocked: portfolio total exposure cap is reached.",
        "directional_cap_reached": "Blocked: same-direction exposure cap is reached.",
        "cluster_cap_reached": "Blocked: correlation cluster cap is reached.",
        "risk_budget_below_min": "Blocked: portfolio risk budget score is below the minimum threshold.",
        "adjusted_score_non_positive": "Blocked: adjusted candidate score is non-positive after penalties.",
        "thesis_duplicate_blocked": "Blocked: an active candidate with the same thesis already exists.",
        "transition_edge_variant_thesis_duplicate_blocked": "Blocked: the transition rescue lane would duplicate an already active thesis.",
        "thesis_active_cap_reached": "Blocked: active thesis cluster cap is reached.",
        "live_limit_only_entry_required": "Blocked: the current live rollout contract accepts limit-only entries.",
        "live_entry_model_not_allowed": "Blocked: the current live rollout contract excludes this entry model.",
        "micro_live_strategy_hour_not_allowed": "Blocked: the current MICRO_LIVE strategy-hour contract excludes this bucket.",
        "micro_live_strategy_time_bucket_not_allowed": "Blocked: the current MICRO_LIVE strategy time-bucket contract excludes this bucket.",
        "micro_live_plan_id_blocklisted": "Blocked: the current MICRO_LIVE historical plan blocklist excludes this exact plan.",
        "live_family_cluster_window_cap_reached": "Blocked: a recent same-family live window is already occupied.",
        "live_family_loss_cooldown_active": "Blocked: recent same-family losses triggered a live cooldown.",
        "invalid_candidate": "Blocked: candidate payload is incomplete or invalid.",
        "sizing_zero_risk": "Blocked: sizing engine reduced the candidate to zero risk.",
    }
    return mapping.get(reason, f"Blocked: {reason}.")
