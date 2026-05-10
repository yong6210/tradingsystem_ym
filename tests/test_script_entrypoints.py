from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

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
import scripts.paper_lineage_watch_tick as paper_lineage_watch_tick
import scripts.install_micro_live_ops_launchd as install_micro_live_ops_launchd
import scripts.run_micro_main_data_backfill as micro_data_backfill
import scripts.run_micro_main_futures_csv_backtest as futures_csv_backtest
import scripts.run_worker as run_worker
import scripts.run_execution_incident_drill as incident_drill
import scripts.run_reaction_gate_variant_backtest as reaction_variant_backtest
import scripts.run_binance_rule_drift_snapshot as binance_rule_drift
import scripts.run_live_reconciliation_watchdog as live_reconciliation_watchdog
import scripts.run_live_replay_parity_audit as live_replay_parity
import scripts.run_replay_validation_bridge as replay_validation_bridge
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
        ROOT_DIR / "scripts" / "run_live_reconciliation_watchdog.py",
        ROOT_DIR / "scripts" / "run_replay_validation_bridge.py",
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
        "reconnects": 0,
        "ingest_errors": 0,
        "skipped_reverse_timestamp": 4,
        "refresh_errors": 5,
        "auto_route_errors": 6,
        "progress_callback_errors": 3,
        "last_ingest_error": "",
        "last_refresh_error": "",
        "last_auto_route_error": "",
        "last_progress_callback_error": "RuntimeError: boom",
        "last_ingest_success_at": "",
        "last_ingest_error_at": "",
        "last_refresh_success_at": "",
        "last_refresh_error_at": "",
        "last_auto_route_success_at": "",
        "last_auto_route_error_at": "",
        "last_progress_callback_success_at": "",
        "last_progress_callback_error_at": "",
        "last_stream_error": "ConnectionClosed: test",
    }
