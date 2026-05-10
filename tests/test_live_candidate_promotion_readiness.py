from __future__ import annotations

from app.services.live_candidate_promotion_readiness import LiveCandidatePromotionReadinessService


def test_readiness_marks_validation_block_without_live_authority_change() -> None:
    payload = LiveCandidatePromotionReadinessService().build(
        hours=24,
        audit_rows=[
            {
                "symbol": "ADAUSDC",
                "phase": "auto_route",
                "status": "intent_blocked",
                "count": 2,
            }
        ],
        intent_rows=[
            {
                "symbol": "ADAUSDC",
                "strategy_family": "session_impulse_retest",
                "execution_mode": "MICRO_LIVE",
                "approval_state": "BLOCKED",
                "submit_decision": "SKIP_BLOCKED",
                "decision_reason_code": "validation_do_not_deploy",
                "count": 2,
            }
        ],
        submission_rows=[],
    )

    assert payload["authority"] == "compare_only_no_live_authority_change"
    assert payload["headline_state"] == "BLOCKED"
    assert payload["headline_reason"] == "validation_do_not_deploy"
    assert payload["candidates"][0]["promotion_state"] == "GATE_BLOCKED"
    assert "Keep live blocked" in payload["candidates"][0]["next_action"]


def test_readiness_keeps_secondary_blockers_visible() -> None:
    payload = LiveCandidatePromotionReadinessService().build(
        hours=24,
        audit_rows=[],
        intent_rows=[
            {
                "symbol": "ADAUSDC",
                "strategy_family": "session_impulse_retest",
                "execution_mode": "MICRO_LIVE",
                "approval_state": "BLOCKED",
                "submit_decision": "SKIP_BLOCKED",
                "decision_reason_code": "validation_do_not_deploy",
                "count": 1,
            },
            {
                "symbol": "ADAUSDC",
                "strategy_family": "session_impulse_retest",
                "execution_mode": "MICRO_LIVE",
                "approval_state": "BLOCKED",
                "submit_decision": "SKIP_BLOCKED",
                "decision_reason_code": "adjusted_score_non_positive",
                "count": 4,
            },
        ],
        submission_rows=[],
    )

    assert payload["candidates"][0]["primary_blocker"] == "validation_do_not_deploy"
    assert payload["candidates"][0]["secondary_blockers"] == {"adjusted_score_non_positive": 4}
    assert payload["candidates"][0]["promotion_state"] == "GATE_BLOCKED"
    assert "Keep live blocked" in payload["candidates"][0]["next_action"]


def test_readiness_detects_submit_ready_gap_before_other_wait_states() -> None:
    payload = LiveCandidatePromotionReadinessService().build(
        hours=24,
        audit_rows=[
            {
                "symbol": "BTCUSDC",
                "phase": "auto_route",
                "status": "no_live_route_candidate_plan",
                "count": 5,
            }
        ],
        intent_rows=[
            {
                "symbol": "BTCUSDC",
                "strategy_family": "sweep_reversal",
                "execution_mode": "MICRO_LIVE",
                "approval_state": "APPROVED_AUTO",
                "submit_decision": "SUBMIT",
                "decision_reason_code": "submit_ready",
                "count": 1,
            }
        ],
        submission_rows=[],
    )

    assert payload["headline_state"] == "FAIL"
    assert payload["headline_reason"] == "submit_ready_gap_present"
    assert payload["candidates"][0]["promotion_state"] == "SUBMIT_READY_GAP"


def test_readiness_separates_shadow_signal_from_live_candidate() -> None:
    payload = LiveCandidatePromotionReadinessService().build(
        hours=24,
        audit_rows=[
            {
                "symbol": "SUIUSDC",
                "phase": "auto_route",
                "status": "symbol_not_live_enabled_for_auto_route",
                "count": 3,
            }
        ],
        intent_rows=[],
        submission_rows=[],
    )

    assert payload["headline_state"] == "WATCH"
    assert payload["headline_reason"] == "shadow_signal_only"
    assert payload["candidates"][0]["promotion_state"] == "SHADOW_SIGNAL_ONLY"
    assert "Keep shadow-only" in payload["candidates"][0]["next_action"]


def test_readiness_headline_prefers_actual_gate_blocker_over_wait_reasons() -> None:
    payload = LiveCandidatePromotionReadinessService().build(
        hours=24,
        audit_rows=[
            {
                "symbol": "ADAUSDC",
                "phase": "auto_route",
                "status": "intent_blocked",
                "count": 1,
            },
            {
                "symbol": "DOGEUSDC",
                "phase": "auto_route",
                "status": "no_live_route_candidate_plan",
                "count": 5,
            },
        ],
        intent_rows=[
            {
                "symbol": "ADAUSDC",
                "strategy_family": "session_impulse_retest",
                "execution_mode": "MICRO_LIVE",
                "approval_state": "BLOCKED",
                "submit_decision": "SKIP_BLOCKED",
                "decision_reason_code": "validation_do_not_deploy",
                "count": 1,
            }
        ],
        submission_rows=[],
    )

    assert payload["headline_state"] == "BLOCKED"
    assert payload["headline_reason"] == "validation_do_not_deploy"


def test_readiness_headline_prefers_hard_validation_blocker_over_score_blocker() -> None:
    payload = LiveCandidatePromotionReadinessService().build(
        hours=24,
        audit_rows=[],
        intent_rows=[
            {
                "symbol": "ADAUSDC",
                "strategy_family": "session_impulse_retest",
                "execution_mode": "MICRO_LIVE",
                "approval_state": "BLOCKED",
                "submit_decision": "SKIP_BLOCKED",
                "decision_reason_code": "adjusted_score_non_positive",
                "count": 10,
            },
            {
                "symbol": "AVAXUSDC",
                "strategy_family": "session_impulse_retest",
                "execution_mode": "MICRO_LIVE",
                "approval_state": "BLOCKED",
                "submit_decision": "SKIP_BLOCKED",
                "decision_reason_code": "validation_do_not_deploy",
                "count": 1,
            },
        ],
        submission_rows=[],
    )

    assert payload["headline_state"] == "BLOCKED"
    assert payload["headline_reason"] == "validation_do_not_deploy"
    assert payload["top_intent_reasons"]["adjusted_score_non_positive"] == 10
    assert payload["top_intent_reasons"]["validation_do_not_deploy"] == 1


def test_readiness_classifies_duplicate_thesis_as_cooldown_wait() -> None:
    payload = LiveCandidatePromotionReadinessService().build(
        hours=24,
        audit_rows=[],
        intent_rows=[
            {
                "symbol": "SUIUSDC",
                "strategy_family": "sweep_reversal",
                "execution_mode": "PAPER",
                "approval_state": "APPROVED_AUTO",
                "submit_decision": "SKIP_DUPLICATE",
                "decision_reason_code": "duplicate_active_thesis",
                "count": 3,
            }
        ],
        submission_rows=[],
    )

    assert payload["headline_state"] == "WAIT"
    assert payload["candidates"][0]["promotion_state"] == "COOLDOWN_WAIT"
    assert payload["candidates"][0]["primary_blocker"] == "duplicate_active_thesis"


def test_readiness_tracks_latest_evidence_timestamps() -> None:
    payload = LiveCandidatePromotionReadinessService().build(
        hours=24,
        audit_rows=[
            {
                "symbol": "ADAUSDC",
                "strategy_family": "session_impulse_retest",
                "phase": "auto_route",
                "status": "recent_intent_cooldown_active",
                "count": 1,
                "latest_observed_ts": "2026-05-10T01:00:00Z",
            }
        ],
        intent_rows=[
            {
                "symbol": "ADAUSDC",
                "strategy_family": "session_impulse_retest",
                "execution_mode": "MICRO_LIVE",
                "approval_state": "BLOCKED",
                "submit_decision": "SKIP_BLOCKED",
                "decision_reason_code": "validation_do_not_deploy",
                "count": 1,
                "latest_created_at": "2026-05-10T02:00:00Z",
            }
        ],
        submission_rows=[],
    )

    row = payload["candidates"][0]
    assert payload["latest_evidence_at"] == "2026-05-10T02:00:00Z"
    assert row["latest_audit_at"] == "2026-05-10T01:00:00Z"
    assert row["latest_intent_at"] == "2026-05-10T02:00:00Z"
    assert row["latest_evidence_at"] == "2026-05-10T02:00:00Z"
