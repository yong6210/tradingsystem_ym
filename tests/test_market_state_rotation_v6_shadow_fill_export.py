from scripts.run_market_state_rotation_v6_execution_shadow_audit import build_execution_shadow_audit_report
from scripts.run_market_state_rotation_v6_shadow_fill_export import (
    build_shadow_fill_export_report,
    lifecycle_rows_to_shadow_fills,
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
                "acknowledged_at": "2026-01-01T00:00:01+00:00",
                "entry_first_fill_at": "2026-01-01T00:00:02+00:00",
                "ack_latency_ms": 1000.0,
                "fill_latency_ms": 2000.0,
                "plan_entry_price": 100.0,
                "entry_avg_price": 100.02,
                "entry_slippage_bps": 2.0,
                "binance_orig_qty": 1.0,
                "binance_executed_qty": 1.0,
                "fee_total": 0.01,
            },
            {
                "symbol": "BTCUSDT",
                "strategy_family": "market_state_rotation_v6",
                "intent_id": "intent_2",
                "submission_id": "sub_2",
                "client_order_id": "client_2",
                "execution_mode": "PAPER",
                "requested_live": False,
                "lifecycle_status": "rejected_or_error",
                "state": "REJECTED",
                "submit_status": "LIVE_LIQUIDITY_BLOCKED",
                "side": "SELL",
                "plan_direction": "short",
                "submitted_at": "2026-01-01T00:05:00+00:00",
                "ack_latency_ms": 50.0,
                "plan_entry_price": 100.0,
                "entry_avg_price": None,
                "entry_slippage_bps": None,
                "binance_orig_qty": 1.0,
                "binance_executed_qty": 0.0,
            },
            {
                "symbol": "ETHUSDT",
                "strategy_family": "market_state_rotation_v6",
                "intent_id": "intent_3",
                "lifecycle_status": "open_after_entry",
            },
            {
                "symbol": "BTCUSDT",
                "strategy_family": "session_impulse_retest",
                "intent_id": "intent_4",
                "lifecycle_status": "open_after_entry",
            },
        ]
    }


def test_lifecycle_rows_to_shadow_fills_maps_filled_and_rejected_rows() -> None:
    rows = lifecycle_rows_to_shadow_fills(_lifecycle_payload())

    assert len(rows) == 2
    assert rows[0]["status"] == "filled"
    assert rows[0]["action"] == "add"
    assert rows[0]["side"] == "long"
    assert rows[0]["order_side"] == "buy"
    assert rows[0]["latency_ms"] == 2000.0
    assert rows[0]["fill_ratio"] == 1.0
    assert rows[1]["status"] == "rejected"
    assert rows[1]["side"] == "short"
    assert rows[1]["order_side"] == "sell"
    assert rows[1]["latency_ms"] == 50.0
    assert rows[1]["fill_ratio"] == 0.0


def test_shadow_fill_export_report_counts_missing_evidence() -> None:
    report = build_shadow_fill_export_report(_lifecycle_payload())

    assert report["row_count"] == 2
    assert report["status_counts"] == {"filled": 1, "rejected": 1}
    assert report["missing_counts"]["missing_actual_price"] == 0
    assert report["missing_counts"]["missing_slippage_bps"] == 0
    assert report["missing_counts"]["missing_latency_ms"] == 0


def test_shadow_fill_export_can_feed_execution_shadow_audit() -> None:
    export = build_shadow_fill_export_report(_lifecycle_payload())
    audit = build_execution_shadow_audit_report(
        _stress_report(),
        export["rows"],
        min_shadow_fill_samples=1,
        max_reject_rate=0.6,
        max_p95_adverse_slippage_bps=5.0,
        max_max_adverse_slippage_bps=5.0,
        max_p95_latency_ms=2500.0,
    )

    assert audit["shadow_fill_metrics"]["row_count"] == 2
    assert audit["shadow_fill_metrics"]["fill_metric_sample_count"] == 1
    assert "min_shadow_fill_samples" not in audit["summary"]["failed_gates"]
    assert "p95_spread_within_limit" in audit["summary"]["failed_gates"]
