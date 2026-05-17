from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.analyze_low_confluence_components as low_confluence
import scripts.analyze_promotion_mismatch_waterfall as promotion_waterfall
import scripts.analyze_replay_runtime_input_diff as replay_input_diff
import scripts.benchmark_timescale_load_retention as benchmark_load_retention
import scripts.benchmark_timescale_retention as benchmark_retention
import scripts.build_micro_live_plan_blocklist as build_blocklist
import scripts.build_micro_live_event_blackouts as build_event_blackouts
import scripts.build_micro_live_strategy_time_contract as build_time_contract
import scripts.check_operator_session_brief_automation as brief_automation
import scripts.check_operator_session_brief_delivery_preflight as delivery_preflight
import scripts.collect_operator_surface_divergence_snapshot as divergence_snapshot
import scripts.generate_operator_session_brief as session_brief
import scripts.notify_entry_surface as notify_entry_surface
import scripts.notify_operator_session_brief as notify_operator_session_brief
import scripts.notify_stage_change as notify_stage_change
import scripts.ops_stage_board as ops_stage_board
import scripts.operation_report_io as operation_report_io
import scripts.paper_lineage_watch_tick as paper_lineage_watch_tick
import scripts.install_micro_live_ops_launchd as install_micro_live_ops_launchd
import scripts.run_micro_main_data_backfill as micro_data_backfill
import scripts.run_micro_main_futures_csv_backtest as futures_csv_backtest
import scripts.run_worker as run_worker
import scripts.run_execution_incident_drill as incident_drill
import scripts.run_reaction_gate_variant_backtest as reaction_variant_backtest
import scripts.run_binance_rule_drift_snapshot as binance_rule_drift
import scripts.run_live_account_protection_audit as live_account_protection_audit
import scripts.run_live_leverage_cap_sync as live_leverage_cap_sync
import scripts.run_live_reconciliation_watchdog as live_reconciliation_watchdog
import scripts.run_live_replay_parity_audit as live_replay_parity
import scripts.run_replay_validation_bridge as replay_validation_bridge
import scripts.run_session_impulse_retest_opportunity_report as sir_opportunity_report
import scripts.run_session_impulse_retest_runtime_audit_report as sir_runtime_audit_report
import scripts.run_micro_live_preflight as micro_live_preflight
import scripts.run_micro_live_boot_check as micro_live_boot_check
import scripts.run_micro_live_no_order_watchdog as micro_live_no_order_watchdog
import scripts.run_micro_live_ops_heartbeat as micro_live_ops_heartbeat
import scripts.run_micro_live_runtime_guard as micro_live_runtime_guard
import scripts.run_micro_live_synthetic_canary as micro_live_synthetic_canary
import scripts.run_live_order_lifecycle_report as live_order_lifecycle_report
import scripts.run_paper_candidate_drill as paper_candidate_drill
import scripts.run_post_live_pruning_review as post_live_pruning
import scripts.run_post_unlock_review as post_unlock
import scripts.run_runtime_signoff_review as runtime_signoff
import scripts.run_split_review_followup as split_review_followup
import scripts.run_timescale_migrations as timescale_migrations
import scripts.run_trend_continuation_scan as trend_scan
import scripts.stage_monitor_tick as stage_monitor_tick
import scripts.verify_timescale_runtime as verify_timescale_runtime
import scripts.watch_paper_candidate_drill as paper_watch


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_runtime_scripts_support_direct_help_from_other_cwd(tmp_path: Path) -> None:
    for script in (
        ROOT_DIR / "scripts" / "run_micro_live_preflight.py",
        ROOT_DIR / "scripts" / "run_micro_live_no_order_watchdog.py",
        ROOT_DIR / "scripts" / "run_micro_live_runtime_guard.py",
        ROOT_DIR / "scripts" / "run_micro_live_synthetic_canary.py",
        ROOT_DIR / "scripts" / "run_micro_main_usdc_backtest.py",
        ROOT_DIR / "scripts" / "run_micro_main_usdt_backtest.py",
        ROOT_DIR / "scripts" / "run_micro_main_usdt_portfolio_replay_from_backtest.py",
        ROOT_DIR / "scripts" / "run_micro_main_weighted_filter_backtest.py",
        ROOT_DIR / "scripts" / "run_live_account_protection_audit.py",
        ROOT_DIR / "scripts" / "run_live_leverage_cap_sync.py",
        ROOT_DIR / "scripts" / "run_live_reconciliation_watchdog.py",
        ROOT_DIR / "scripts" / "run_replay_validation_bridge.py",
        ROOT_DIR / "scripts" / "run_session_impulse_retest_opportunity_report.py",
        ROOT_DIR / "scripts" / "run_micro_live_boot_check.py",
        ROOT_DIR / "scripts" / "run_micro_live_ops_heartbeat.py",
        ROOT_DIR / "scripts" / "install_micro_live_ops_launchd.py",
        ROOT_DIR / "scripts" / "run_runtime_signoff_review.py",
    ):
        completed = subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 0, completed.stderr
        assert "usage:" in completed.stdout.lower()


def test_script_display_paths_allow_absolute_outputs_outside_repo(tmp_path: Path) -> None:
    outside_path = tmp_path / "outside" / "report.md"
    for module in (
        build_blocklist,
        build_event_blackouts,
        build_time_contract,
        binance_rule_drift,
        brief_automation,
        delivery_preflight,
        divergence_snapshot,
        session_brief,
        incident_drill,
        install_micro_live_ops_launchd,
        live_order_lifecycle_report,
        live_leverage_cap_sync,
        live_reconciliation_watchdog,
        live_replay_parity,
        replay_validation_bridge,
        micro_live_boot_check,
        micro_live_no_order_watchdog,
        micro_live_ops_heartbeat,
        micro_live_preflight,
        micro_live_runtime_guard,
        micro_live_synthetic_canary,
        paper_candidate_drill,
        post_live_pruning,
        post_unlock,
        split_review_followup,
        paper_watch,
    ):
        assert module._display_path(outside_path) == str(outside_path)


def test_script_runtime_paths_are_root_anchored_when_relative() -> None:
    for module in (
        brief_automation,
        delivery_preflight,
        notify_entry_surface,
        notify_operator_session_brief,
        notify_stage_change,
        ops_stage_board,
        paper_lineage_watch_tick,
        runtime_signoff,
        stage_monitor_tick,
        timescale_migrations,
        benchmark_load_retention,
        benchmark_retention,
        verify_timescale_runtime,
    ):
        root_dir = getattr(module, "ROOT_DIR", None) or module.PROJECT_ROOT
        assert module._resolve_root_path("reports/test.json") == root_dir / "reports/test.json"


def test_script_timestamp_helpers_tolerate_invalid_legacy_values() -> None:
    start = datetime(2026, 5, 9, tzinfo=UTC)
    end = datetime(2026, 5, 10, tzinfo=UTC)

    assert live_order_lifecycle_report._parse_generated_at("2026-05-10T12:00:00Z").tzinfo == UTC
    assert live_order_lifecycle_report._parse_generated_at("2026-05-10T12:00:00").tzinfo == UTC
    assert operation_report_io.parse_report_generated_at("2026-05-10T12:00:00Z").tzinfo == UTC
    assert operation_report_io.parse_report_generated_at("2026-05-10T12:00:00").tzinfo == UTC
    assert operation_report_io.parse_report_generated_at(datetime(2026, 5, 10, 12, 0, 0)).tzinfo == UTC
    assert binance_rule_drift._parse_generated_at("2026-05-10T12:00:00Z").tzinfo == UTC
    assert binance_rule_drift._parse_generated_at(datetime(2026, 5, 10, 12, 0, 0)).tzinfo == UTC
    assert build_time_contract._parse_ts("legacy-invalid-timestamp") is None
    assert low_confluence._utc_from_iso("legacy-invalid-timestamp") is None
    assert replay_input_diff._utc_from_iso("legacy-invalid-timestamp") is None
    assert promotion_waterfall._utc_from_iso("legacy-invalid-timestamp") is None
    assert trend_scan._daily_pnl([{"closed_ts": "legacy-invalid-timestamp", "final_exit_realized_r": 1.0}]) == {}
    assert trend_scan._daily_pnl([{"closed_ts": start.isoformat(), "final_exit_realized_r": "bad"}]) == {
        start.date().isoformat(): 0.0
    }
    assert reaction_variant_backtest._filtered_rows(
        [{"generated_ts": "legacy-invalid-timestamp", "final_exit_realized_r": 1.0}],
        start_ts=start,
        end_ts=end,
    ) == []
    assert build_time_contract._realized_r({"final_exit_realized_r": "bad"}) == 0.0
    assert low_confluence._safe_float("bad") == 0.0
    assert replay_input_diff._safe_float("bad") == 0.0
    assert promotion_waterfall._safe_float("bad") == 0.0
    with pytest.raises(ValueError, match="invalid ISO8601 timestamp"):
        futures_csv_backtest._parse_optional_ts("legacy-invalid-timestamp")
    with pytest.raises(ValueError, match="invalid --target-date"):
        micro_data_backfill._parse_target_date("legacy-invalid-date")


def test_worker_safe_int_tolerates_malformed_heartbeat_stats() -> None:
    assert run_worker._safe_int("bad") == 0
    assert run_worker._safe_int(None) == 0
    assert run_worker._safe_int("3") == 3


def test_worker_loop_log_compaction_omits_full_universe_results() -> None:
    payload = {
        "ts": "2026-05-16T04:00:00+00:00",
        "actions": [
            {
                "sync_universe": {
                    "universe": "usdc_perp_top30",
                    "requested_symbols": 2,
                    "processed_symbols": 2,
                    "success": 2,
                    "failed": 0,
                    "results": [
                        {
                            "symbol": "BTCUSDC",
                            "status": "ok",
                            "refresh": {
                                "session_impulse_retest_generated_count": 1,
                                "session_impulse_retest_generation_state": "generated",
                                "signal_alerts": {"emitted_total": 2},
                            },
                            "auto_route": {
                                "reason": "no_live_route_candidate_plan",
                                "submit_calls": 0,
                                "intents_created": 0,
                            },
                        },
                        {
                            "symbol": "ETHUSDC",
                            "status": "ok",
                            "refresh": {
                                "session_impulse_retest_generated_count": 0,
                                "session_impulse_retest_generation_state": "no_fresh_candidates",
                            },
                            "auto_route": {
                                "reason": "ws_stream_active_route_suppressed",
                                "submit_calls": 1,
                                "intents_created": 1,
                            },
                        },
                    ],
                    "session_impulse_retest_miss_detector": {
                        "enabled": True,
                        "expected_trade_count": 1,
                        "runtime_observed_count": 1,
                        "observed_submit_ready_intent_count": 0,
                        "observed_non_submit_intent_count": 1,
                        "observed_submission_count": 0,
                        "observed_non_submit_reason_counts": {"outcome_penalty_manual_review": 1},
                        "miss_count": 0,
                        "runtime_started_at": "2026-05-16T03:40:50Z",
                    },
                }
            }
        ],
        "outbox": {"counts": {"published": 1}},
    }

    compact = run_worker._compact_worker_log_payload(payload)
    sync = compact["actions"][0]["sync_universe"]

    assert "results" not in sync
    assert sync["result_count"] == 2
    assert sync["session_impulse_retest_generated_count"] == 1
    assert sync["signal_alerts_emitted"] == 2
    assert sync["auto_route_submit_calls"] == 1
    assert sync["auto_route_reason_counts"] == {
        "no_live_route_candidate_plan": 1,
        "ws_stream_active_route_suppressed": 1,
    }
    assert sync["session_impulse_retest_miss_detector"]["miss_count"] == 0
    assert sync["session_impulse_retest_miss_detector"]["observed_non_submit_reason_counts"] == {
        "outcome_penalty_manual_review": 1
    }


def test_session_impulse_retest_opportunity_report_performance_uses_configured_risk() -> None:
    rows = [{"r_value": 1.0}, {"r_value": -0.5}, {"r_value": 2.0}]

    payload = sir_opportunity_report._performance(rows, risk_pct=0.01, account_equity=200.0)

    assert payload["trade_count"] == 3
    assert payload["wins"] == 2
    assert payload["losses"] == 1
    assert payload["total_r"] == 2.5
    assert payload["simple_return_pct"] == 2.5
    assert payload["simple_pnl_usdt"] == 5.0
    assert payload["compounded_return_pct"] == 2.5049


def test_session_impulse_retest_opportunity_report_status_separates_pre_runtime_backfill() -> None:
    assert sir_opportunity_report._status_for(
        observed=True,
        intents=[],
        submissions=[],
        before_runtime_start=True,
    ) == ("pre_runtime_backfill_without_intent", "before_runtime_start")
    assert sir_opportunity_report._status_for(
        observed=False,
        intents=[],
        submissions=[],
        before_runtime_start=True,
        observation_reason="insufficient_candles",
    ) == ("pre_runtime_unobservable", "before_runtime_start_insufficient_candles")
    assert sir_opportunity_report._status_for(
        observed=False,
        intents=[],
        submissions=[],
        before_runtime_start=False,
        observation_reason="runtime_plan_not_observed",
    ) == ("not_observed", "runtime_plan_not_observed")


def test_session_impulse_retest_opportunity_report_status_keeps_live_intent_truth_first() -> None:
    intent = SimpleNamespace(submit_decision="SKIP_BLOCKED", decision_reason_code="rollout_session_not_allowed")
    submission = SimpleNamespace(submit_status="FILLED", state="FILLED")

    assert sir_opportunity_report._status_for(
        observed=True,
        intents=[intent],
        submissions=[],
        before_runtime_start=True,
    ) == ("blocked_or_skipped", "rollout_session_not_allowed")
    assert sir_opportunity_report._status_for(
        observed=True,
        intents=[intent],
        submissions=[submission],
        before_runtime_start=True,
    ) == ("submitted", "FILLED")


def test_session_impulse_retest_opportunity_summary_can_exclude_pre_runtime_rows() -> None:
    rows = [
        {
            "symbol": "BTCUSDC",
            "session": "new_york",
            "runtime_status": "blocked_or_skipped",
            "runtime_reason": "session_impulse_retest_rollout_not_ready",
            "r_value": 1.5,
            "before_current_runtime_start": True,
        },
        {
            "symbol": "ETHUSDC",
            "session": "london",
            "runtime_status": "submitted",
            "runtime_reason": "FILLED",
            "r_value": -0.5,
            "before_current_runtime_start": False,
        },
    ]

    active = sir_opportunity_report._summary_for_opportunities(
        [row for row in rows if not row["before_current_runtime_start"]],
        risk_pct=0.01,
        account_equity=200.0,
    )
    lookback = sir_opportunity_report._summary_for_opportunities(
        rows,
        risk_pct=0.01,
        account_equity=200.0,
    )

    assert active["expected_order_count"] == 1
    assert active["before_current_runtime_start_count"] == 0
    assert active["potential_performance"]["total_r"] == -0.5
    assert lookback["expected_order_count"] == 2
    assert lookback["before_current_runtime_start_count"] == 1


def test_session_impulse_retest_runtime_audit_summary_separates_sir_from_legacy_generation() -> None:
    compact = sir_runtime_audit_report._compact_audit(
        {
            "audit_id": "audit_1",
            "symbol": "LINKUSDC",
            "phase": "refresh",
            "status": "no_fresh_candidates",
            "decision_code": "normal",
            "observed_ts": "2026-05-14T21:45:00+00:00",
            "payload": {
                "plans": 2,
                "session_impulse_retest_generated_count": 0,
                "plan_generation_diagnostics": {"generation_state": "generated"},
            },
        }
    )

    summary = compact["payload_summary"]
    assert summary["generation_state"] == "no_fresh_candidates"
    assert summary["session_impulse_retest_generation_state"] == "no_fresh_candidates"
    assert summary["legacy_plan_generation_state"] == "generated"


def test_session_impulse_retest_runtime_audit_summary_marks_ws_suppression_non_blocking() -> None:
    compact = sir_runtime_audit_report._compact_audit(
        {
            "audit_id": "audit_2",
            "symbol": "NEARUSDC",
            "phase": "auto_route",
            "status": "ws_stream_active_route_suppressed",
            "decision_code": "",
            "observed_ts": "2026-05-14T22:00:00+00:00",
            "payload": {
                "reason": "ws_stream_active_route_suppressed",
                "reason_detail": "Sync-universe worker skipped duplicate auto-route.",
                "route_owner": "ws_stream",
                "suppression_scope": "sync_universe_duplicate_route_guard",
                "blocking_live_route": False,
                "plans_considered": 1,
            },
        }
    )

    summary = compact["payload_summary"]
    assert summary["route_owner"] == "ws_stream"
    assert summary["suppression_scope"] == "sync_universe_duplicate_route_guard"
    assert summary["blocking_live_route"] is False
    assert "duplicate auto-route" in summary["reason_detail"]


def test_session_impulse_retest_runtime_audit_status_summary_splits_blocking_and_context() -> None:
    summary = sir_runtime_audit_report._status_summary(
        [
            {
                "status": "ws_stream_active_route_suppressed",
                "payload": {"blocking_live_route": False},
            },
            {"status": "no_live_route_candidate_plan", "payload": {}},
            {"status": "intent_blocked", "payload": {"blocking_live_route": True}},
            {"status": "submit_error", "payload": {}},
        ]
    )

    assert summary["overall_status"] == "FAIL"
    assert summary["non_blocking_status_counts"] == {"ws_stream_active_route_suppressed": 1}
    assert summary["no_candidate_status_counts"] == {"no_live_route_candidate_plan": 1}
    assert summary["order_blocking_status_counts"] == {"intent_blocked": 1, "submit_error": 1}


def test_session_impulse_retest_runtime_audit_filters_runtime_scope() -> None:
    rows = [
        {"observed_ts": "2026-05-10T00:00:00Z", "status": "submit_error"},
        {"observed_ts": "2026-05-10T01:00:00Z", "status": "no_fresh_candidates"},
        {"observed_ts": "legacy-invalid-timestamp", "status": "no_fresh_candidates"},
    ]
    start_at = datetime(2026, 5, 10, 0, 30, tzinfo=UTC)

    filtered = sir_runtime_audit_report._rows_since(rows, start_at)

    assert filtered == [{"observed_ts": "2026-05-10T01:00:00Z", "status": "no_fresh_candidates"}]


def test_live_replay_parity_maps_dead_session_guidance_before_inactive_name() -> None:
    row = SimpleNamespace(
        session_guidance={
            "state": "dead_session",
            "dead_session": True,
            "current_session": {"name": "inactive", "active": False},
        },
        approval_snapshot={},
    )

    assert live_replay_parity._intent_session_name(row) == "dead_session"


def test_worker_boot_check_is_required_only_for_live_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = run_worker.get_settings()
    monkeypatch.setattr(settings, "auto_trading_execution_mode", "MICRO_LIVE")
    assert run_worker._live_mode_requires_boot_check() is True
    monkeypatch.setattr(settings, "auto_trading_execution_mode", "SHADOW")
    assert run_worker._live_mode_requires_boot_check() is False


def test_worker_completed_heartbeat_preserves_stream_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, str, dict]] = []

    class FakeSession:
        def __enter__(self) -> object:
            return object()

        def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

    class FakeEngine:
        def __init__(self, db: object) -> None:
            self.db = db

        async def stream_binance_klines(self, **kwargs: object) -> dict:
            assert kwargs["symbols"] == ["BTCUSDC"]
            assert kwargs["intervals"] == ["1m", "5m", "15m"]
            return {
                "processed_messages": "bad",
                "refresh_calls": "2",
                "auto_route_calls": "bad",
                "auto_route_submit_calls": 1,
                "reconnects": None,
                "ingest_errors": "bad",
                "skipped_reverse_timestamp": "4",
                "refresh_errors": "5",
                "auto_route_errors": "6",
                "progress_callback_errors": "3",
                "last_progress_callback_error": "RuntimeError: boom",
                "last_stream_error": "ConnectionClosed: test",
            }

        def outbox_status(self) -> dict:
            return {"pending": 0}

    def fake_heartbeat(role: str, *, status: str, details: dict) -> None:
        captured.append((role, status, details))

    def fake_session_local() -> FakeSession:
        return FakeSession()

    monkeypatch.setattr(run_worker, "SessionLocal", fake_session_local)
    monkeypatch.setattr(run_worker, "StrategyEngine", FakeEngine)
    monkeypatch.setattr(run_worker, "write_worker_heartbeat", fake_heartbeat)

    payload = run_worker.run_ws_stream(
        argparse.Namespace(
            ws_symbols="",
            symbol="BTCUSDC",
            sync_universe=False,
            limit_symbols=30,
            ws_intervals="1m,5m,15m",
            ws_max_messages=1,
            ws_refresh_on_final=True,
        )
    )

    assert payload["outbox"] == {"pending": 0}
    assert captured[-1][0] == "ws"
    assert captured[-1][1] == "ok"
    assert captured[-1][2] == {
        "phase": "completed",
        "started_at": captured[-1][2]["started_at"],
        "symbols": ["BTCUSDC"],
        "intervals": ["1m", "5m", "15m"],
        "processed_messages": 0,
        "refresh_calls": 2,
        "auto_route_calls": 0,
        "auto_route_submit_calls": 1,
        "tp_market_fallback_calls": 0,
        "tp_market_fallback_submitted": 0,
        "reconnects": 0,
        "ingest_errors": 0,
        "skipped_non_final_candles": 0,
        "skipped_reverse_timestamp": 4,
        "refresh_errors": 5,
        "auto_route_errors": 6,
        "tp_market_fallback_errors": 0,
        "progress_callback_errors": 3,
        "last_ingest_error": "",
        "last_refresh_error": "",
        "last_auto_route_error": "",
        "last_tp_market_fallback_error": "",
        "last_progress_callback_error": "RuntimeError: boom",
        "last_ingest_success_at": "",
        "last_ingest_error_at": "",
        "last_refresh_success_at": "",
        "last_refresh_error_at": "",
        "last_auto_route_success_at": "",
        "last_auto_route_error_at": "",
        "last_tp_market_fallback_success_at": "",
        "last_tp_market_fallback_error_at": "",
        "last_progress_callback_success_at": "",
        "last_progress_callback_error_at": "",
        "last_stream_error": "ConnectionClosed: test",
    }
