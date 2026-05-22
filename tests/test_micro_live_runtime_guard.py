from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from scripts import run_micro_live_preflight
from scripts import run_micro_live_runtime_guard


class _FakeCandleRepo:
    def __init__(self, counts: dict[tuple[str, str], int]):
        self.counts = counts

    def list_recent(self, *, symbol: str, timeframe: str, limit: int):
        count = self.counts.get((symbol, timeframe), 0)
        return [object()] * min(count, limit)


def test_live_candle_depth_check_fails_when_strategy_history_is_short() -> None:
    check = run_micro_live_runtime_guard._live_candle_depth_check(
        _FakeCandleRepo(
            {
                ("BTCUSDT", "1m"): 599,
                ("BTCUSDT", "5m"): 200,
                ("ETHUSDT", "1m"): 600,
                ("ETHUSDT", "5m"): 199,
            }
        ),
        symbols=["BTCUSDT", "ETHUSDT"],
    )

    assert check["status"] == "FAIL"
    assert check["severity"] == "blocking"
    assert check["deficient_count"] == 2
    assert "BTCUSDT" in check["message"]
    assert "ETHUSDT" in check["message"]


def test_live_candle_depth_check_passes_when_strategy_history_is_ready() -> None:
    check = run_micro_live_runtime_guard._live_candle_depth_check(
        _FakeCandleRepo(
            {
                ("BTCUSDT", "1m"): 900,
                ("BTCUSDT", "5m"): 500,
                ("ETHUSDT", "1m"): 600,
                ("ETHUSDT", "5m"): 200,
            }
        ),
        symbols=["BTCUSDT", "ETHUSDT"],
    )

    assert check["status"] == "PASS"
    assert check["deficient_count"] == 0
    assert "deficient=none" in check["message"]


def test_session_impulse_retest_exit_contract_check_passes_for_live_baseline() -> None:
    check = run_micro_live_runtime_guard._session_impulse_retest_exit_contract_check(
        SimpleNamespace(
            session_impulse_retest_exit_policy_name="legacy_full_2r",
            session_impulse_retest_exit_stop_mode="legacy",
            session_impulse_retest_exit_target_rr=2.0,
            session_impulse_retest_exit_tp1_fraction=0.0,
            session_impulse_retest_exit_tp2_fraction=0.0,
            session_impulse_retest_exit_min_stop_pct=0.0,
            session_impulse_retest_exit_min_risk_atr=0.0,
            session_impulse_retest_exit_adaptive_targets_enabled=False,
            session_impulse_retest_exit_structure_targets_enabled=False,
        )
    )

    assert check["status"] == "PASS"
    assert check["severity"] == "blocking"
    assert check["mismatches"] == []


def test_session_impulse_retest_exit_contract_check_passes_for_approved_structure_candidate() -> None:
    check = run_micro_live_runtime_guard._session_impulse_retest_exit_contract_check(
        SimpleNamespace(
            session_impulse_retest_exit_policy_name="structure_buffered_swing6_stop0.12_tpbuf0.08_pm_stop0.00r_advvol_any",
            session_impulse_retest_exit_stop_mode="structure_floor",
            session_impulse_retest_exit_target_rr=2.5,
            session_impulse_retest_exit_tp1_fraction=0.35,
            session_impulse_retest_exit_tp2_fraction=0.65,
            session_impulse_retest_exit_min_stop_pct=0.003,
            session_impulse_retest_exit_min_risk_atr=0.35,
            session_impulse_retest_exit_adaptive_targets_enabled=True,
            session_impulse_retest_exit_structure_targets_enabled=True,
            session_impulse_retest_exit_structure_stop_swing_bars=6,
            session_impulse_retest_exit_structure_stop_buffer_atr=0.12,
            session_impulse_retest_exit_structure_target_buffer_atr=0.08,
            session_impulse_retest_exit_structure_tp1_min_rr=0.8,
            session_impulse_retest_exit_structure_tp2_min_rr=1.6,
            session_impulse_retest_exit_structure_tp_max_rr=3.2,
            session_impulse_retest_exit_stop_after_partial_rr=0.0,
            session_impulse_retest_exit_adverse_volume_enabled=True,
            session_impulse_retest_exit_adverse_volume_after_partial_only=False,
            session_impulse_retest_exit_adverse_volume_min_factor=3.0,
            session_impulse_retest_exit_adverse_volume_min_body_r=0.35,
            session_impulse_retest_exit_adverse_volume_lookback_bars=20,
            auto_trading_live_breakeven_after_partial_enabled=True,
            auto_trading_live_breakeven_offset_bps=0.0,
            auto_trading_live_breakeven_min_improvement_bps=0.0,
            auto_trading_live_adverse_volume_exit_enabled=True,
            auto_trading_live_adverse_volume_exit_after_partial_only=False,
        )
    )

    assert check["status"] == "PASS"
    assert check["severity"] == "blocking"
    assert check["mismatches"] == []


def test_session_impulse_retest_exit_contract_check_fails_for_unapproved_structure_candidate() -> None:
    check = run_micro_live_runtime_guard._session_impulse_retest_exit_contract_check(
        SimpleNamespace(
            session_impulse_retest_exit_policy_name="structure_buffered_swing6_stop0.12_tpbuf0.08",
            session_impulse_retest_exit_stop_mode="structure_floor",
            session_impulse_retest_exit_target_rr=2.5,
            session_impulse_retest_exit_tp1_fraction=0.35,
            session_impulse_retest_exit_tp2_fraction=0.65,
            session_impulse_retest_exit_min_stop_pct=0.003,
            session_impulse_retest_exit_min_risk_atr=0.35,
            session_impulse_retest_exit_adaptive_targets_enabled=True,
            session_impulse_retest_exit_structure_targets_enabled=True,
        )
    )

    assert check["status"] == "FAIL"
    assert check["severity"] == "blocking"
    assert "policy=structure_buffered_swing6_stop0.12_tpbuf0.08" in check["mismatches"]


def test_live_protection_config_check_passes_for_required_runtime_switches() -> None:
    check = run_micro_live_preflight._live_protection_config_check(
        SimpleNamespace(
            auto_trading_live_protection_orders_enabled=True,
            auto_trading_live_stop_working_type="MARK_PRICE",
            auto_trading_live_stop_precheck_enabled=True,
            auto_trading_live_stop_precheck_fail_closed=True,
            auto_trading_live_stop_precheck_min_tick_cushion=3,
            auto_trading_live_stop_mark_price_guard_enabled=True,
            auto_trading_live_protection_failure_flatten_enabled=True,
            auto_trading_live_protection_verify_after_attach_enabled=True,
            auto_trading_live_protection_verify_fail_closed=True,
            auto_trading_live_protection_verify_attempts=3,
            auto_trading_live_tp_limit_attach_enabled=True,
            auto_trading_live_take_profit_verify_after_attach_enabled=True,
            auto_trading_live_missing_stop_watchdog_flatten_enabled=True,
            auto_trading_live_missing_stop_watchdog_cancel_open_orders=True,
            auto_trading_live_unexpected_open_order_watchdog_cancel_enabled=True,
        )
    )

    assert check["status"] == "PASS"
    assert check["mismatches"] == []


def test_live_protection_config_check_fails_when_required_runtime_switches_are_off() -> None:
    check = run_micro_live_preflight._live_protection_config_check(
        SimpleNamespace(
            auto_trading_live_protection_orders_enabled=True,
            auto_trading_live_stop_working_type="CONTRACT_PRICE",
            auto_trading_live_stop_precheck_enabled=False,
            auto_trading_live_stop_precheck_fail_closed=True,
            auto_trading_live_stop_precheck_min_tick_cushion=0,
            auto_trading_live_stop_mark_price_guard_enabled=False,
            auto_trading_live_protection_failure_flatten_enabled=False,
            auto_trading_live_protection_verify_after_attach_enabled=False,
            auto_trading_live_protection_verify_fail_closed=False,
            auto_trading_live_protection_verify_attempts=0,
            auto_trading_live_tp_limit_attach_enabled=True,
            auto_trading_live_take_profit_verify_after_attach_enabled=False,
            auto_trading_live_missing_stop_watchdog_flatten_enabled=False,
            auto_trading_live_missing_stop_watchdog_cancel_open_orders=False,
            auto_trading_live_unexpected_open_order_watchdog_cancel_enabled=False,
        )
    )

    assert check["status"] == "FAIL"
    assert check["severity"] == "blocking"
    assert "AUTO_TRADING_LIVE_STOP_PRECHECK_ENABLED" in check["mismatches"]
    assert "AUTO_TRADING_LIVE_STOP_WORKING_TYPE=CONTRACT_PRICE" in check["mismatches"]
    assert "AUTO_TRADING_LIVE_STOP_PRECHECK_MIN_TICK_CUSHION=0" in check["mismatches"]
    assert "AUTO_TRADING_LIVE_PROTECTION_VERIFY_ATTEMPTS=0" in check["mismatches"]


def test_live_leverage_cap_sync_report_check_passes_for_fresh_ok_report(tmp_path, monkeypatch) -> None:
    report_dir = tmp_path / "reports/operations/live_leverage_cap_sync"
    report_dir.mkdir(parents=True)
    (report_dir / "latest.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "overall_status": "OK",
                "configured_leverage_cap": 10,
                "target_leverage": 10,
                "pending_count": 0,
                "fail_count": 0,
            }
        )
    )
    monkeypatch.setattr(run_micro_live_runtime_guard, "ROOT_DIR", tmp_path)

    check = run_micro_live_runtime_guard._live_leverage_cap_sync_report_check(max_age_minutes=90)

    assert check["status"] == "PASS"
    assert check["pending_count"] == 0
    assert check["fail_count"] == 0


def test_live_leverage_cap_sync_report_check_fails_for_pending_or_stale_report(tmp_path, monkeypatch) -> None:
    report_dir = tmp_path / "reports/operations/live_leverage_cap_sync"
    report_dir.mkdir(parents=True)
    (report_dir / "latest.json").write_text(
        json.dumps(
            {
                "generated_at": (datetime.now(UTC) - timedelta(minutes=120)).isoformat(),
                "overall_status": "WATCH",
                "configured_leverage_cap": 10,
                "target_leverage": 10,
                "pending_count": 1,
                "fail_count": 0,
            }
        )
    )
    monkeypatch.setattr(run_micro_live_runtime_guard, "ROOT_DIR", tmp_path)

    check = run_micro_live_runtime_guard._live_leverage_cap_sync_report_check(max_age_minutes=90)

    assert check["status"] == "FAIL"
    assert check["pending_count"] == 1
    assert "stale=True" in check["message"]


def test_runtime_guard_reports_blocking_failures_and_blocked_live_intents() -> None:
    checks = [
        {"name": "config_execution_mode", "status": "PASS", "severity": "blocking", "message": "ok"},
        {"name": "macro_blackout_horizon", "status": "FAIL", "severity": "blocking", "message": "expired"},
        {"name": "optional_note", "status": "FAIL", "severity": "warning", "message": "warn"},
    ]
    failures = run_micro_live_runtime_guard._blocking_failures(checks)
    warnings = run_micro_live_runtime_guard._warning_failures(checks)
    lifecycle = {
        "summary": {
            "submission_count": 0,
            "entry_fill_count": 0,
            "rejected_or_error_count": 0,
            "submitted_without_entry_fill_count": 0,
            "live_intents": {
                "total": 3,
                "submit_ready": 0,
                "blocked": 3,
                "top_block_reasons": {"validation_do_not_deploy": 3},
                "recent_blocked_intents": [
                    {
                        "intent_id": "intent_1",
                        "symbol": "BTCUSDC",
                        "strategy_family": "session_impulse_retest",
                        "decision_reason_code": "validation_do_not_deploy",
                    }
                ],
            },
        }
    }

    recommendations = run_micro_live_runtime_guard._recommendations(
        blocking_failures=failures,
        lifecycle=lifecycle,
    )

    assert [item["name"] for item in failures] == ["macro_blackout_horizon"]
    assert [item["name"] for item in warnings] == ["optional_note"]
    assert recommendations == [
        "fix_blocking_runtime_checks:macro_blackout_horizon",
        "all_recent_live_intents_blocked:validation_do_not_deploy=3",
        "inspect_validation_report_approval_surface:validation_do_not_deploy=3",
    ]
    diagnostics = run_micro_live_runtime_guard._blocked_intent_diagnostics(lifecycle)
    assert diagnostics == [
        {
            "reason": "validation_do_not_deploy",
            "count": 3,
            "action": "inspect_validation_report_approval_surface",
            "detail": {},
            "recent_samples": [
                {
                    "intent_id": "intent_1",
                    "symbol": "BTCUSDC",
                    "strategy_family": "session_impulse_retest",
                    "decision_reason_code": "validation_do_not_deploy",
                }
            ],
        }
    ]
    assert run_micro_live_runtime_guard._operational_status(blocking_failures=[], lifecycle=lifecycle) == "WATCH"
    assert run_micro_live_runtime_guard._operational_status(
        blocking_failures=[],
        warning_failures=warnings,
        lifecycle={"summary": {"live_intents": {"total": 0, "submit_ready": 0, "blocked": 0}}},
    ) == "WATCH"
    assert run_micro_live_runtime_guard._operational_status(blocking_failures=failures, lifecycle=lifecycle) == "FAIL"
