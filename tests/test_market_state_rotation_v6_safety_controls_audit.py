from datetime import UTC, datetime, timedelta

from scripts.run_market_state_rotation_v6_execution_shadow_audit import (
    REQUIRED_SAFETY_CONTROLS,
    build_execution_shadow_audit_report,
)
from scripts.run_market_state_rotation_v6_safety_controls_audit import build_safety_controls_report


def _fresh_evidence(now: datetime) -> dict:
    return {
        "controls": {
            name: {
                "verified": True,
                "verified_at": (now - timedelta(hours=1)).isoformat(),
                "evidence": f"{name}_drill_passed",
            }
            for name in REQUIRED_SAFETY_CONTROLS
        }
    }


def _stress_report() -> dict:
    return {
        "execution_readiness_checklist": {
            "overall_status": "shadow_only",
            "items": [{"name": "replay_stress_floor", "status": "pass"}],
        },
        "replay_adjusted_worst_stress_summary": {"deployment_readiness_verdict": "pass"},
    }


def _fills() -> list[dict]:
    return [
        {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "symbol": "BTCUSDT",
            "strategy_family": "market_state_rotation_v6",
            "decision_id": "intent_1",
            "action": "add",
            "side": "long",
            "status": "filled",
            "expected_price": 100.0,
            "actual_price": 100.01,
            "slippage_bps": 1.0,
            "spread_bps": 1.0,
            "latency_ms": 300.0,
            "fill_ratio": 1.0,
        }
    ]


def test_safety_controls_report_is_incomplete_without_evidence() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    report = build_safety_controls_report(now=now)

    assert report["overall_status"] == "INCOMPLETE"
    assert report["verified_count"] == 0
    assert report["missing_or_failed"] == list(REQUIRED_SAFETY_CONTROLS)
    assert report["controls"]["kill_switch_verified"]["verified"] is False
    assert "evidence_missing" in report["controls"]["kill_switch_verified"]["blockers"]


def test_safety_controls_report_passes_fresh_complete_evidence() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    report = build_safety_controls_report(_fresh_evidence(now), now=now)

    assert report["overall_status"] == "PASS"
    assert report["verified_count"] == len(REQUIRED_SAFETY_CONTROLS)
    assert report["missing_or_failed"] == []
    assert report["controls"]["leverage_cap_verified"]["verified"] is True


def test_safety_controls_report_blocks_stale_evidence() -> None:
    now = datetime(2026, 1, 10, tzinfo=UTC)
    evidence = _fresh_evidence(datetime(2026, 1, 1, tzinfo=UTC))

    report = build_safety_controls_report(evidence, now=now, max_evidence_age_days=3)

    assert report["overall_status"] == "INCOMPLETE"
    assert report["verified_count"] == 0
    assert "evidence_stale" in report["controls"]["kill_switch_verified"]["blockers"]


def test_safety_controls_report_feeds_shadow_audit_canary_gate() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    safety = build_safety_controls_report(_fresh_evidence(now), now=now)

    audit = build_execution_shadow_audit_report(
        _stress_report(),
        _fills(),
        safety_controls=safety,
        min_shadow_fill_samples=1,
    )

    assert audit["overall_status"] == "tiny_live_canary_ready"
    assert audit["summary"]["live_order_submission_allowed"] is True
    assert audit["summary"]["ready_for_full_live"] is False
