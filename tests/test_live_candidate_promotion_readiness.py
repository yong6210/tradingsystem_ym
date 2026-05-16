from __future__ import annotations

from datetime import UTC, datetime

from app.services.live_candidate_promotion_readiness import LiveCandidatePromotionReadinessService
from app.services.live_candidate_promotion_readiness_runtime import _apply_live_headline_scope
from scripts import run_live_candidate_promotion_readiness


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
    assert payload["promotion_decision"] == "do_not_promote_validation_block"
    assert payload["attention_flags"]["has_hard_validation_block"] is True
    assert payload["attention_flags"]["headline_requires_operator_review"] is True
    assert payload["candidates"][0]["promotion_state"] == "GATE_BLOCKED"
    assert "Keep live blocked" in payload["candidates"][0]["next_action"]
    assert payload["operator_review_items"][0]["attention"] == "validation_report_required"
    assert payload["operator_review_items"][0]["symbol"] == "ADAUSDC"


def test_readiness_script_runtime_scope_keeps_lookback_context(monkeypatch) -> None:
    calls: list[datetime | None] = []

    class FakeSession:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
            return False

    def fake_build_payload(_db, *, hours, limit, symbol, start_at):  # noqa: ANN001
        calls.append(start_at)
        if start_at is not None:
            return {
                "generated_at": "2026-05-10T00:00:00Z",
                "symbol": symbol,
                "strategy_families": ["session_impulse_retest"],
                "window_start": "2026-05-10T00:00:00Z",
                "readiness": {
                    "headline_state": "WAIT",
                    "headline_reason": "no_promotable_live_candidate",
                    "promotion_decision": "wait_for_fresh_promotable_candidate",
                    "candidate_count": 1,
                    "top_intent_reasons": {},
                },
            }
        return {
            "generated_at": "2026-05-10T00:00:00Z",
            "symbol": symbol,
            "strategy_families": ["session_impulse_retest"],
            "window_start": None,
            "readiness": {
                "headline_state": "BLOCKED",
                "headline_reason": "session_impulse_retest_rollout_not_ready",
                "promotion_decision": "do_not_promote_gate_blocked",
                "candidate_count": 2,
                "top_intent_reasons": {"session_impulse_retest_rollout_not_ready": 2},
            },
        }

    monkeypatch.setattr(run_live_candidate_promotion_readiness, "init_db", lambda: None)
    monkeypatch.setattr(run_live_candidate_promotion_readiness, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        run_live_candidate_promotion_readiness,
        "build_live_candidate_promotion_readiness_payload",
        fake_build_payload,
    )

    start_at = datetime(2026, 5, 10, 1, tzinfo=UTC)
    payload = run_live_candidate_promotion_readiness.build_payload(
        hours=24,
        limit=20,
        symbol="BTCUSDC",
        start_at=start_at,
    )

    assert calls == [start_at, None]
    assert payload["readiness_scope"] == "runtime_since_ws_start"
    assert payload["runtime_started_at"] == "2026-05-10T01:00:00Z"
    assert payload["status"] == "PASS"
    assert payload["overall_status"] == "PASS"
    assert payload["state"] == "WAIT"
    assert payload["reason"] == "no_promotable_live_candidate"
    assert payload["status_detail"] == "live_candidate_promotion_readiness_no_promotable_live_candidate"
    assert payload["promotion_decision"] == "wait_for_fresh_promotable_candidate"
    assert payload["readiness"]["headline_reason"] == "no_promotable_live_candidate"
    assert payload["lookback_readiness_summary"]["headline_reason"] == "session_impulse_retest_rollout_not_ready"
    assert payload["lookback_readiness_summary"]["top_intent_reasons"] == {
        "session_impulse_retest_rollout_not_ready": 2
    }


def test_readiness_script_status_fields_map_headline_states() -> None:
    assert run_live_candidate_promotion_readiness._status_fields(
        {
            "headline_state": "WAIT",
            "headline_reason": "no_promotable_live_candidate",
            "promotion_decision": "wait_for_fresh_promotable_candidate",
            "headline_action": "wait",
        }
    ) == {
        "status": "PASS",
        "overall_status": "PASS",
        "state": "WAIT",
        "reason": "no_promotable_live_candidate",
        "status_detail": "live_candidate_promotion_readiness_no_promotable_live_candidate",
        "promotion_decision": "wait_for_fresh_promotable_candidate",
        "action": "wait",
    }
    assert run_live_candidate_promotion_readiness._status_fields(
        {"headline_state": "BLOCKED", "headline_reason": "validation_do_not_deploy"}
    )["status"] == "WATCH"
    assert run_live_candidate_promotion_readiness._status_fields(
        {"headline_state": "FAIL", "headline_reason": "submit_ready_gap_present"}
    )["status"] == "FAIL"


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


def test_runtime_readiness_keeps_shadow_only_as_auxiliary_when_live_symbols_are_waiting() -> None:
    payload = LiveCandidatePromotionReadinessService().build(
        hours=24,
        now="2026-05-10T03:10:00Z",
        audit_rows=[
            {
                "symbol": "BTCUSDC",
                "strategy_family": "session_impulse_retest",
                "phase": "auto_route",
                "status": "no_live_route_candidate_plan",
                "count": 2,
                "latest_observed_ts": "2026-05-10T03:00:00Z",
            },
            {
                "symbol": "SUIUSDC",
                "strategy_family": "session_impulse_retest",
                "phase": "auto_route",
                "status": "symbol_not_live_enabled_for_auto_route",
                "count": 1,
                "latest_observed_ts": "2026-05-10T03:05:00Z",
            },
        ],
        intent_rows=[],
        submission_rows=[],
    )

    scoped = _apply_live_headline_scope(payload, live_symbols={"BTCUSDC"})

    assert scoped["headline_state"] == "WAIT"
    assert scoped["headline_reason"] == "no_promotable_live_candidate"
    assert scoped["headline_scope"] == "live_routable_symbols"
    assert scoped["headline_candidate_symbols"] == ["BTCUSDC"]
    assert scoped["headline_candidate_state_counts"] == {"NO_FRESH_LIVE_CANDIDATE": 1}
    assert scoped["candidate_scope_counts"] == {"total": 2, "live_routable": 1, "auxiliary": 1}
    assert scoped["live_state_counts"] == {"NO_FRESH_LIVE_CANDIDATE": 1}
    assert scoped["auxiliary_state_counts"] == {"SHADOW_SIGNAL_ONLY": 1}
    assert scoped["auxiliary_display_state_counts"] == {"AUXILIARY_SHADOW_SIGNAL_ONLY": 1}
    assert scoped["top_live_blockers"] == {"no_fresh_live_candidate": 1}
    assert scoped["top_auxiliary_blockers"] == {"symbol_not_live_enabled_for_auto_route": 1}
    assert scoped["headline_top_blockers"] == {"no_fresh_live_candidate": 1}
    assert scoped["top_all_blockers"] == {
        "no_fresh_live_candidate": 1,
        "symbol_not_live_enabled_for_auto_route": 1,
    }
    assert scoped["shadow_only_auxiliary"]["symbols"] == ["SUIUSDC"]
    assert scoped["attention_flags"]["has_auxiliary_shadow_only_signal"] is True
    assert scoped["operator_review_items"][0]["symbol"] == "BTCUSDC"


def test_runtime_readiness_scope_blocker_counts_use_full_candidate_set_when_rows_are_limited() -> None:
    live_symbols = {
        "ADAUSDC",
        "AVAXUSDC",
        "BCHUSDC",
        "BNBUSDC",
        "BTCUSDC",
        "ETHUSDC",
        "LINKUSDC",
        "LTCUSDC",
        "NEARUSDC",
        "SOLUSDC",
        "XRPUSDC",
    }
    audit_rows = [
        {
            "symbol": symbol,
            "strategy_family": "session_impulse_retest",
            "phase": "auto_route",
            "status": "no_live_route_candidate_plan",
            "count": 1,
            "latest_observed_ts": "2026-05-10T03:00:00Z",
        }
        for symbol in sorted(live_symbols)
    ]
    audit_rows.extend(
        {
            "symbol": symbol,
            "strategy_family": "session_impulse_retest",
            "phase": "auto_route",
            "status": "symbol_not_live_enabled_for_auto_route",
            "count": 1,
            "latest_observed_ts": "2026-05-10T03:05:00Z",
        }
        for symbol in ("AAVEUSDC", "HBARUSDC", "SUIUSDC")
    )
    payload = LiveCandidatePromotionReadinessService().build(
        hours=24,
        limit=12,
        now="2026-05-10T03:10:00Z",
        audit_rows=audit_rows,
        intent_rows=[],
        submission_rows=[],
    )

    scoped = _apply_live_headline_scope(payload, live_symbols=live_symbols)

    assert len(scoped["candidates"]) == 12
    assert scoped["candidate_count"] == 14
    assert scoped["candidate_scope_counts"] == {"total": 14, "live_routable": 11, "auxiliary": 3}
    assert scoped["live_state_counts"] == {"NO_FRESH_LIVE_CANDIDATE": 11}
    assert scoped["auxiliary_state_counts"] == {"SHADOW_SIGNAL_ONLY": 3}
    assert scoped["top_live_blockers"] == {"no_fresh_live_candidate": 11}
    assert scoped["top_auxiliary_blockers"] == {"symbol_not_live_enabled_for_auto_route": 3}
    assert scoped["headline_top_blockers"] == {"no_fresh_live_candidate": 11}
    assert scoped["top_all_blockers"] == {
        "no_fresh_live_candidate": 11,
        "symbol_not_live_enabled_for_auto_route": 3,
    }


def test_runtime_readiness_wait_headline_uses_live_symbols_only() -> None:
    payload = LiveCandidatePromotionReadinessService().build(
        hours=24,
        now="2026-05-10T03:10:00Z",
        audit_rows=[
            {
                "symbol": "BTCUSDC",
                "strategy_family": "session_impulse_retest",
                "phase": "auto_route",
                "status": "no_live_route_candidate_plan",
                "count": 2,
                "latest_observed_ts": "2026-05-10T03:00:00Z",
            },
            {
                "symbol": "SUIUSDC",
                "strategy_family": "session_impulse_retest",
                "phase": "auto_route",
                "status": "no_live_route_candidate_plan",
                "count": 1,
                "latest_observed_ts": "2026-05-10T03:05:00Z",
            },
        ],
        intent_rows=[],
        submission_rows=[],
    )

    scoped = _apply_live_headline_scope(payload, live_symbols={"BTCUSDC"})

    assert scoped["headline_state"] == "WAIT"
    assert scoped["headline_scope"] == "live_routable_symbols"
    assert scoped["headline_candidate_count"] == 1
    assert scoped["headline_candidate_symbols"] == ["BTCUSDC"]
    assert scoped["candidate_scope_counts"] == {"total": 2, "live_routable": 1, "auxiliary": 1}
    assert scoped["live_state_counts"] == {"NO_FRESH_LIVE_CANDIDATE": 1}
    assert scoped["auxiliary_state_counts"] == {"NO_FRESH_LIVE_CANDIDATE": 1}
    assert scoped["auxiliary_display_state_counts"] == {"AUXILIARY_TRACKED_NO_FRESH_SIGNAL": 1}
    assert scoped["top_live_blockers"] == {"no_fresh_live_candidate": 1}
    assert scoped["top_auxiliary_blockers"] == {"no_fresh_live_candidate": 1}
    assert scoped["headline_top_blockers"] == {"no_fresh_live_candidate": 1}
    assert scoped["top_all_blockers"] == {"no_fresh_live_candidate": 2}
    assert scoped["shadow_only_auxiliary"]["available"] is False
    assert scoped["headline_action"] == "Current live symbols have no fresh live-eligible candidate."


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
        now="2026-05-10T02:10:00Z",
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
    assert row["evidence_age_seconds"] == 600
    assert row["evidence_freshness"] == "fresh"
    assert payload["latest_evidence_age_seconds"] == 600
    assert payload["latest_evidence_freshness"] == "fresh"
    assert payload["evidence_freshness_counts"] == {"fresh": 1}


def test_readiness_marks_stale_and_missing_evidence_freshness() -> None:
    payload = LiveCandidatePromotionReadinessService().build(
        hours=24,
        now="2026-05-10T12:00:00Z",
        audit_rows=[
            {
                "symbol": "ADAUSDC",
                "strategy_family": "session_impulse_retest",
                "phase": "auto_route",
                "status": "recent_intent_cooldown_active",
                "count": 1,
                "latest_observed_ts": "2026-05-10T09:00:00Z",
            },
            {
                "symbol": "DOGEUSDC",
                "strategy_family": "session_impulse_retest",
                "phase": "auto_route",
                "status": "no_live_route_candidate_plan",
                "count": 1,
            },
        ],
        intent_rows=[],
        submission_rows=[],
    )

    by_symbol = {row["symbol"]: row for row in payload["candidates"]}
    assert by_symbol["ADAUSDC"]["evidence_age_seconds"] == 10800
    assert by_symbol["ADAUSDC"]["evidence_freshness"] == "stale"
    assert by_symbol["DOGEUSDC"]["evidence_age_seconds"] is None
    assert by_symbol["DOGEUSDC"]["evidence_freshness"] == "no_evidence"


def test_readiness_tracks_headline_evidence_separately_from_latest_evidence() -> None:
    payload = LiveCandidatePromotionReadinessService().build(
        hours=24,
        now="2026-05-10T03:10:00Z",
        audit_rows=[
            {
                "symbol": "SUIUSDC",
                "strategy_family": "session_impulse_retest",
                "phase": "auto_route",
                "status": "symbol_not_live_enabled_for_auto_route",
                "count": 1,
                "latest_observed_ts": "2026-05-10T03:00:00Z",
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

    assert payload["headline_state"] == "BLOCKED"
    assert payload["headline_reason"] == "validation_do_not_deploy"
    assert payload["latest_evidence_at"] == "2026-05-10T03:00:00Z"
    assert payload["headline_evidence_at"] == "2026-05-10T02:00:00Z"
    assert payload["headline_evidence_age_seconds"] == 4200
    assert payload["headline_evidence_freshness"] == "stale"
    assert payload["headline_candidate_symbols"] == ["ADAUSDC"]
    assert payload["attention_flags"]["has_stale_or_missing_evidence"] is True
    assert payload["attention_flags"]["headline_has_stale_or_missing_evidence"] is True
    assert payload["operator_review_items"] == [
        {
            "symbol": "ADAUSDC",
            "strategy_family": "session_impulse_retest",
            "promotion_state": "GATE_BLOCKED",
            "primary_blocker": "validation_do_not_deploy",
            "secondary_blockers": {},
            "attention": "validation_report_required",
            "latest_evidence_at": "2026-05-10T02:00:00Z",
            "evidence_freshness": "stale",
            "next_action": "Keep live blocked; run validation/report and fix the validation primary cause before probation.",
        }
    ]
