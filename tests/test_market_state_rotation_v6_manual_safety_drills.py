from datetime import UTC, datetime

from scripts.run_market_state_rotation_v6_manual_safety_drills import (
    build_manual_safety_drill_report,
)


def test_manual_safety_drill_report_passes_required_non_live_controls() -> None:
    report = build_manual_safety_drill_report(now=datetime(2026, 1, 2, 3, 4, tzinfo=UTC))

    assert report["overall_status"] == "PASS"
    assert report["no_live_order_sent"] is True
    assert report["verified_count"] == 10
    assert report["required_count"] == 10
    assert report["missing_or_failed"] == []
    assert report["controls"]["kill_switch_verified"]["verified"] is True
    assert report["controls"]["max_daily_loss_verified"]["verified"] is True
    assert report["controls"]["position_sync_verified"]["verified"] is True
    assert report["controls"]["partial_fill_handling_verified"]["verified"] is True
    assert report["controls"]["exchange_reject_handling_verified"]["verified"] is True
    assert report["controls"]["reduce_only_exit_verified"]["verified"] is True
    assert report["controls"]["leverage_cap_verified"]["verified"] is True
    assert report["controls"]["idempotent_client_order_id_verified"]["verified"] is True
    assert report["controls"]["stale_signal_block_verified"]["verified"] is True
    assert report["controls"]["maintenance_window_block_verified"]["verified"] is True
    assert (
        report["controls"]["idempotent_client_order_id_verified"]["details"]["submitter_calls"]
        == 0
    )
    assert (
        report["controls"]["kill_switch_verified"]["details"]["after"]["blocking_reason_code"]
        == "kill_switch_active"
    )
    assert (
        report["controls"]["max_daily_loss_verified"]["details"]["snapshot"]["reason"]
        == "daily_loss_limit_reached"
    )
    assert (
        report["controls"]["partial_fill_handling_verified"]["details"]["submit_status"]
        == "PARTIALLY_FILLED"
    )
    assert (
        report["controls"]["exchange_reject_handling_verified"]["details"]["submit_status"]
        == "REJECTED"
    )
    assert (
        report["controls"]["stale_signal_block_verified"]["details"]["playbook_code"]
        == "stale_plan_expired"
    )
    assert (
        report["controls"]["maintenance_window_block_verified"]["details"]["playbook_code"]
        == "micro_live_session_direction_hour_not_allowed"
    )
