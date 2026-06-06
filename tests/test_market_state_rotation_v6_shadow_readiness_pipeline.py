from datetime import UTC, datetime, timedelta

from scripts.run_market_state_rotation_v6_shadow_readiness_pipeline import (
    build_shadow_readiness_pipeline_report,
)


def _stress_report() -> dict:
    return {
        "execution_readiness_checklist": {
            "overall_status": "shadow_only",
            "items": [{"name": "replay_stress_floor", "status": "pass"}],
        },
        "replay_adjusted_worst_stress_summary": {"deployment_readiness_verdict": "pass"},
    }


def _lifecycle_payload() -> dict:
    return {
        "rows": [
            {
                "symbol": "BTCUSDT",
                "strategy_family": "market_state_rotation_v6",
                "intent_id": "intent_1",
                "submission_id": "sub_1",
                "client_order_id": "client_1",
                "execution_mode": "PAPER",
                "requested_live": False,
                "lifecycle_status": "open_after_entry",
                "state": "FILLED",
                "submit_status": "FILLED",
                "side": "BUY",
                "plan_direction": "long",
                "submitted_at": "2026-01-01T00:00:00+00:00",
                "entry_first_fill_at": "2026-01-01T00:00:01+00:00",
                "fill_latency_ms": 1000.0,
                "plan_entry_price": 100.0,
                "entry_avg_price": 100.01,
                "entry_slippage_bps": 1.0,
                "spread_bps": 1.0,
                "binance_orig_qty": 1.0,
                "binance_executed_qty": 1.0,
            }
        ]
    }


def _manual_safety_evidence() -> dict:
    now = datetime.now(UTC) - timedelta(minutes=5)
    controls = {
        name: {
            "verified": True,
            "verified_at": now.isoformat(),
            "evidence": f"{name}_passed",
        }
        for name in [
            "kill_switch_verified",
            "max_daily_loss_verified",
            "position_sync_verified",
            "partial_fill_handling_verified",
            "exchange_reject_handling_verified",
            "reduce_only_exit_verified",
            "leverage_cap_verified",
            "idempotent_client_order_id_verified",
            "stale_signal_block_verified",
            "maintenance_window_block_verified",
        ]
    }
    return {"controls": controls}


def test_shadow_readiness_pipeline_stays_shadow_data_required_without_rows() -> None:
    report = build_shadow_readiness_pipeline_report(
        stress_report=_stress_report(),
        lifecycle_payload={"rows": []},
        min_shadow_fill_samples=1,
        max_report_age_hours=24,
    )

    assert report["overall_status"] == "shadow_data_required"
    assert report["shadow_fill_export"]["row_count"] == 0
    assert "min_shadow_fill_samples" in report["summary"]["failed_gates"]


def test_shadow_readiness_pipeline_can_reach_tiny_canary_with_rows_and_manual_safety() -> None:
    report = build_shadow_readiness_pipeline_report(
        stress_report=_stress_report(),
        lifecycle_payload=_lifecycle_payload(),
        manual_safety_evidence=_manual_safety_evidence(),
        min_shadow_fill_samples=1,
        max_report_age_hours=24,
    )

    assert report["shadow_fill_export"]["row_count"] == 1
    assert report["safety_evidence_collection"]["verified_count"] == 10
    assert report["overall_status"] == "tiny_live_canary_ready"
    assert report["summary"]["ready_for_full_live"] is False
