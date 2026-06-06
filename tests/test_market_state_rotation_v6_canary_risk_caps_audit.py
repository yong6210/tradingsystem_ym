import json
from datetime import UTC, datetime

from scripts.run_market_state_rotation_v6_canary_risk_caps_audit import build_canary_risk_caps_audit


def test_canary_risk_caps_audit_reports_missing_config_as_incomplete(tmp_path) -> None:
    report = build_canary_risk_caps_audit(
        canary_risk_caps_path=tmp_path / "missing_caps.json",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert report["overall_status"] == "INCOMPLETE"
    assert report["config"]["configured"] is False
    assert "canary_risk_caps_json_required" in report["config"]["errors"]
    assert report["operator_actions"][0]["action"] == (
        "copy_the_disabled_template_to_target_path_then_edit_values_after_operator_review"
    )
    assert report["order_submission_allowed"] is False
    assert report["no_live_order_sent"] is True


def test_canary_risk_caps_audit_passes_complete_operator_config(tmp_path) -> None:
    caps_path = tmp_path / "caps.json"
    caps_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "scope_symbol": "BTCUSDT",
                "strategy_family": "market_state_rotation_v6",
                "max_notional_usdt": 50.0,
                "max_leverage": 10.0,
                "max_daily_loss_usdt": 20.0,
                "max_daily_order_count": 1,
                "max_consecutive_loss_count": 1,
                "kill_switch_required": True,
                "reduce_only_exit_required": True,
                "operator_acknowledged_no_auto_live_order": True,
            }
        ),
        encoding="utf-8",
    )

    report = build_canary_risk_caps_audit(
        canary_risk_caps_path=caps_path,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert report["overall_status"] == "PASS"
    assert report["ready_for_operator_review"] is True
    assert report["config"]["effective"]["max_leverage"] == 10.0
    assert report["config"]["errors"] == []
    assert report["order_submission_allowed"] is False


def test_canary_risk_caps_audit_blocks_oversized_daily_loss(tmp_path) -> None:
    caps_path = tmp_path / "caps.json"
    caps_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "scope_symbol": "BTCUSDT",
                "strategy_family": "market_state_rotation_v6",
                "max_notional_usdt": 50.0,
                "max_leverage": 10.0,
                "max_daily_loss_usdt": 40.0,
                "max_daily_order_count": 1,
                "max_consecutive_loss_count": 1,
                "kill_switch_required": True,
                "reduce_only_exit_required": True,
                "operator_acknowledged_no_auto_live_order": True,
            }
        ),
        encoding="utf-8",
    )

    report = build_canary_risk_caps_audit(
        canary_risk_caps_path=caps_path,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert report["overall_status"] == "FAIL"
    assert "max_daily_loss_usdt_must_be_lte_50pct_of_max_notional" in report["config"]["errors"]
    assert report["operator_actions"] == [
        {
            "error": "max_daily_loss_usdt_must_be_lte_50pct_of_max_notional",
            "action": "lower_daily_loss_cap_to_lte_50pct_of_notional",
        }
    ]
    assert report["no_live_order_sent"] is True
