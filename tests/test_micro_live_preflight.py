from __future__ import annotations

import importlib.util
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

from app.api.routes import _validation_report_cache_miss_payload
from app.api.routes import validation_report as validation_report_route
from app.schemas.api import ValidationReportOut


ROOT_DIR = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_micro_live_preflight = _load_module(
    "run_micro_live_preflight_test_module",
    ROOT_DIR / "scripts/run_micro_live_preflight.py",
)


class _JsonResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):  # noqa: ANN001
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _ready_payload() -> dict:
    return {"status": "ready", "checks": {"db": True, "binance_rest": True, "event_backend": True}}


def _dashboard_payload() -> dict:
    return {
        "execution_mode": "live",
        "auto_trading_enabled": True,
        "new_entries_allowed": True,
        "blocking_reason_code": "",
        "blocking_reason_message": "",
        "approval_strip_summary": {
            "primary_reason": "dashboard approval aligned",
            "approve_value": "approval usable",
            "approve_reason": "dashboard approval aligned",
            "align_value": "aligned",
            "align_reason": "dashboard approval aligned",
            "act_value": "continue_candidate_review_under_portfolio_caps",
            "act_reason": "continue candidate review",
            "act_priority_level": "monitor",
        },
        "signal_funnel": {
            "edge_experiment_review": {
                "available": True,
                "advisory_only": True,
                "edge_state": "watch_edge",
                "summary": "Prefer split tests before structural rewrites.",
                "true_edge_ratio": 0.82,
                "edge_decay_rate": -0.03,
                "entry_timing_preferred_variant": "early_limit",
                "execution_style_preferred_variant": "passive_limit",
                "edge_proof_goal_closed_trades": 100,
                "remaining_closed_trades_to_edge_proof_goal": 94,
                "edge_proof_posture": {
                    "state": "sample_building",
                    "claim_state": "do_not_claim_edge_yet",
                },
                "daily_edge_kpis": {
                    "closed_trade_count": 6,
                    "sample_maturity_state": "review_ready",
                    "true_edge_ratio": 0.82,
                    "edge_decay_rate": -0.03,
                    "regime_dependency_state": "single_regime_observed",
                },
            },
            "edge_evolution_rule": {
                "available": True,
                "advisory_only": True,
                "evolution_state": "reduce_candidate",
                "recommended_action": "reduce_baseline_allocation_review",
                "allocation_bias": "reduce_baseline",
                "promotion_candidate_axis": "entry_timing",
                "promotion_candidate_variant": "early_limit",
                "summary": "Reduce baseline allocation while split evidence stays fragile.",
            },
            "review_followup_ledger": {
                "available": True,
                "last_status": "READY",
                "last_generated_status": "READY",
                "last_decision_status": "ACKED",
                "last_effective_status": "ACKED",
                "last_action": "reduce_baseline_allocation_review",
                "recent_entry_count": 2,
                "last_followup_command": (
                    "./.venv/bin/python scripts/run_split_review_followup.py "
                    "--symbol BTCUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review"
                ),
                "summary": "Latest review packet generated cleanly and is already acknowledged.",
            },
        },
        "portfolio_summary": {
            "accepted_candidates": [
                {
                    "symbol": "BTCUSDC",
                    "strategy_family": "sweep_reversal",
                    "edge_experiment_focus": {
                        "edge_state": "watch_edge",
                        "entry_timing_preferred_variant": "early_limit",
                        "execution_style_preferred_variant": "passive_limit",
                    },
                }
            ],
            "blocked_candidates": [
                {
                    "symbol": "ETHUSDC",
                    "strategy_family": "trend_continuation",
                    "block_reason": "portfolio_cap",
                    "edge_experiment_focus": {
                        "edge_state": "fragile_edge",
                        "entry_timing_preferred_variant": "reaction_confirmed",
                        "execution_style_preferred_variant": "market",
                    },
                }
            ],
        },
    }


def test_micro_live_config_drift_checks_flag_missing_direction_contract_symbol(monkeypatch, tmp_path) -> None:
    settings = run_micro_live_preflight.get_settings()
    heartbeat_dir = tmp_path / "heartbeats"
    heartbeat_dir.mkdir()
    (heartbeat_dir / "ws.json").write_text(
        json.dumps({"details": {"symbols": ["BTCUSDC", "ETHUSDC"]}}),
        encoding="utf-8",
    )
    blackout_path = tmp_path / "blackouts.json"
    blackout_path.write_text(
        json.dumps({"windows": [{"label": "global_test", "start_utc": "2026-01-01T00:00:00Z", "end_utc": "2026-01-01T01:00:00Z"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "runtime_worker_heartbeat_dir", str(heartbeat_dir))
    monkeypatch.setattr(settings, "auto_trading_execution_mode", "MICRO_LIVE")
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_allowed_symbols", "BTCUSDC,ETHUSDC")
    monkeypatch.setattr(settings, "auto_trading_allowed_families", "sweep_reversal")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", "BTCUSDC,ETHUSDC")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "sweep_reversal")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_entry_models", "LIMIT")
    monkeypatch.setattr(settings, "auto_trading_micro_live_direction_contract", "BTCUSDC:LONG|SHORT")
    monkeypatch.setattr(settings, "auto_trading_micro_live_event_blackout_path", str(blackout_path))
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_fail_closed", True)

    checks = run_micro_live_preflight._micro_live_config_drift_checks()
    by_name = {item["name"]: item for item in checks}

    assert by_name["live_direction_contract_coverage"]["status"] == "FAIL"
    assert "missing=ETHUSDC" in by_name["live_direction_contract_coverage"]["message"]
    assert by_name["ws_universe_contains_live_symbols"]["status"] == "PASS"


def test_micro_live_config_drift_checks_align_current_backtest_contract(monkeypatch, tmp_path) -> None:
    settings = run_micro_live_preflight.get_settings()
    heartbeat_dir = tmp_path / "heartbeats"
    heartbeat_dir.mkdir()
    (heartbeat_dir / "ws.json").write_text(
        json.dumps({"details": {"symbols": ["BTCUSDC", "ETHUSDC"]}}),
        encoding="utf-8",
    )
    report_dir = tmp_path / "backtests"
    report_dir.mkdir()
    (report_dir / "micro_main_usdt_proxy_backtest_20260516T000000Z.json").write_text(
        json.dumps({"proxy_symbols": ["BTCUSDT", "ETHUSDT"], "results": {}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(settings, "runtime_worker_heartbeat_dir", str(heartbeat_dir))
    monkeypatch.setattr(settings, "auto_trading_replay_validation_bridge_backtest_dir", str(report_dir))
    monkeypatch.setattr(settings, "auto_trading_execution_mode", "MICRO_LIVE")
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_allowed_symbols", "BTCUSDC,ETHUSDC")
    monkeypatch.setattr(settings, "auto_trading_allowed_families", "session_impulse_retest")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", "BTCUSDC,ETHUSDC")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "session_impulse_retest")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_entry_models", "CONFIRM")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_sessions", "dead_session,london,new_york")
    monkeypatch.setattr(settings, "auto_trading_micro_live_direction_contract", "BTCUSDC:LONG|SHORT,ETHUSDC:LONG|SHORT")
    monkeypatch.setattr(settings, "auto_trading_micro_live_event_blackout_path", "")
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_fail_closed", True)
    monkeypatch.setattr(settings, "session_impulse_retest_enabled", True)
    monkeypatch.setattr(settings, "session_impulse_retest_shadow_only", False)
    monkeypatch.setattr(settings, "session_impulse_retest_allowed_symbols", "BTCUSDC,ETHUSDC")

    checks = run_micro_live_preflight._micro_live_config_drift_checks()
    alignment = {item["name"]: item for item in checks}["micro_live_backtest_contract_alignment"]

    assert alignment["status"] == "PASS"
    assert "expected_symbols=2" in alignment["message"]
    assert "requested_days=0" in alignment["message"]
    assert "missing_symbols=none" in alignment["message"]
    assert "missing_entry_models=none" in alignment["message"]


def test_micro_live_config_drift_checks_use_latest_matching_live_backtest_contract(monkeypatch, tmp_path) -> None:
    settings = run_micro_live_preflight.get_settings()
    heartbeat_dir = tmp_path / "heartbeats"
    heartbeat_dir.mkdir()
    (heartbeat_dir / "ws.json").write_text(
        json.dumps({"details": {"symbols": ["BTCUSDC", "ETHUSDC"]}}),
        encoding="utf-8",
    )
    report_dir = tmp_path / "backtests"
    report_dir.mkdir()
    matching_path = report_dir / "micro_main_usdt_proxy_backtest_20260515T175711Z.json"
    matching_path.write_text(
        json.dumps({"proxy_symbols": ["BTCUSDT", "ETHUSDT"], "results": {}}),
        encoding="utf-8",
    )
    (report_dir / "micro_main_usdt_proxy_backtest_20260516T095759Z.json").write_text(
        json.dumps({"proxy_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"], "results": {}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(settings, "runtime_worker_heartbeat_dir", str(heartbeat_dir))
    monkeypatch.setattr(settings, "auto_trading_replay_validation_bridge_backtest_dir", str(report_dir))
    monkeypatch.setattr(settings, "auto_trading_execution_mode", "MICRO_LIVE")
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_allowed_symbols", "BTCUSDC,ETHUSDC")
    monkeypatch.setattr(settings, "auto_trading_allowed_families", "session_impulse_retest")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", "BTCUSDC,ETHUSDC")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "session_impulse_retest")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_entry_models", "CONFIRM")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_sessions", "dead_session,london,new_york")
    monkeypatch.setattr(settings, "auto_trading_micro_live_direction_contract", "BTCUSDC:LONG|SHORT,ETHUSDC:LONG|SHORT")
    monkeypatch.setattr(settings, "auto_trading_micro_live_event_blackout_path", "")
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_fail_closed", True)
    monkeypatch.setattr(settings, "session_impulse_retest_enabled", True)
    monkeypatch.setattr(settings, "session_impulse_retest_shadow_only", False)
    monkeypatch.setattr(settings, "session_impulse_retest_allowed_symbols", "BTCUSDC,ETHUSDC")

    checks = run_micro_live_preflight._micro_live_config_drift_checks()
    alignment = {item["name"]: item for item in checks}["micro_live_backtest_contract_alignment"]

    assert alignment["status"] == "PASS"
    assert "20260515T175711Z" in alignment["message"]
    assert "expected_symbols=2" in alignment["message"]


def test_micro_live_backtest_contract_prefers_longer_matching_report(tmp_path) -> None:
    report_dir = tmp_path / "backtests"
    report_dir.mkdir()
    long_path = report_dir / "micro_main_usdt_proxy_backtest_20260515T175711Z.json"
    short_path = report_dir / "micro_main_usdt_proxy_backtest_20260516T184951Z.json"
    payload = {"proxy_symbols": ["BTCUSDT", "ETHUSDT"], "results": {}}
    long_path.write_text(json.dumps({**payload, "days": 1825}), encoding="utf-8")
    short_path.write_text(json.dumps({**payload, "days": 30}), encoding="utf-8")

    settings = SimpleNamespace(auto_trading_replay_validation_bridge_backtest_dir=str(report_dir))

    selected = run_micro_live_preflight._latest_micro_main_backtest_report(
        settings,
        live_symbols={"BTCUSDC", "ETHUSDC"},
    )

    assert selected == long_path


def test_micro_live_backtest_contract_prefers_usdc_report_when_days_match(tmp_path) -> None:
    validation_dir = tmp_path / "reports" / "validation"
    usdt_dir = validation_dir / "micro_main_usdt_proxy_backtests"
    usdc_dir = validation_dir / "micro_main_usdc_backtests"
    usdt_dir.mkdir(parents=True)
    usdc_dir.mkdir(parents=True)
    usdt_path = usdt_dir / "micro_main_usdt_proxy_backtest_20260515T175711Z.json"
    usdc_path = usdc_dir / "micro_main_usdc_backtest_20260515T175711Z.json"
    usdt_path.write_text(
        json.dumps({"proxy_symbols": ["BTCUSDT", "ETHUSDT"], "results": {}, "days": 1825}),
        encoding="utf-8",
    )
    usdc_path.write_text(
        json.dumps({"symbols": ["BTCUSDC", "ETHUSDC"], "results": {}, "days": 1825}),
        encoding="utf-8",
    )

    settings = SimpleNamespace(auto_trading_replay_validation_bridge_backtest_dir=str(usdt_dir))

    selected = run_micro_live_preflight._latest_micro_main_backtest_report(
        settings,
        live_symbols={"BTCUSDC", "ETHUSDC"},
    )

    assert selected == usdc_path


def test_micro_live_backtest_contract_accepts_direct_usdt_report(tmp_path) -> None:
    validation_dir = tmp_path / "reports" / "validation"
    usdt_dir = validation_dir / "micro_main_usdt_backtests"
    usdt_dir.mkdir(parents=True)
    usdt_path = usdt_dir / "micro_main_usdt_backtest_20260515T175711Z.json"
    usdt_path.write_text(
        json.dumps(
            {
                "source": "micro_main_usdt_backtest",
                "symbols": ["BTCUSDT", "ETHUSDT"],
                "results": {},
                "days": 1095,
            }
        ),
        encoding="utf-8",
    )

    settings = SimpleNamespace(auto_trading_replay_validation_bridge_backtest_dir=str(usdt_dir))

    selected = run_micro_live_preflight._latest_micro_main_backtest_report(
        settings,
        live_symbols={"BTCUSDT", "ETHUSDT"},
    )

    assert selected == usdt_path


def test_micro_live_backtest_contract_alignment_reports_effective_days(monkeypatch, tmp_path) -> None:
    settings = run_micro_live_preflight.get_settings()
    heartbeat_dir = tmp_path / "heartbeats"
    heartbeat_dir.mkdir()
    (heartbeat_dir / "ws.json").write_text(
        json.dumps({"details": {"symbols": ["BTCUSDC"]}}),
        encoding="utf-8",
    )
    report_dir = tmp_path / "backtests"
    report_dir.mkdir()
    (report_dir / "micro_main_usdc_backtest_20260516T000000Z.json").write_text(
        json.dumps(
            {
                "days": 1825,
                "symbols": ["BTCUSDC"],
                "results": {
                    "BTCUSDC": {
                        "symbol": "BTCUSDC",
                        "window": {
                            "effective_start_ts": "2026-05-01T00:00:00+00:00",
                            "effective_end_ts": "2026-05-08T00:00:00+00:00",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(settings, "runtime_worker_heartbeat_dir", str(heartbeat_dir))
    monkeypatch.setattr(settings, "auto_trading_replay_validation_bridge_backtest_dir", str(report_dir))
    monkeypatch.setattr(settings, "auto_trading_execution_mode", "MICRO_LIVE")
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_allowed_symbols", "BTCUSDC")
    monkeypatch.setattr(settings, "auto_trading_allowed_families", "session_impulse_retest")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", "BTCUSDC")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "session_impulse_retest")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_entry_models", "CONFIRM")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_sessions", "dead_session,london,new_york")
    monkeypatch.setattr(settings, "auto_trading_micro_live_direction_contract", "BTCUSDC:LONG|SHORT")
    monkeypatch.setattr(settings, "auto_trading_micro_live_event_blackout_path", "")
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_fail_closed", True)
    monkeypatch.setattr(settings, "session_impulse_retest_enabled", True)
    monkeypatch.setattr(settings, "session_impulse_retest_shadow_only", False)
    monkeypatch.setattr(settings, "session_impulse_retest_allowed_symbols", "BTCUSDC")

    checks = run_micro_live_preflight._micro_live_config_drift_checks()
    alignment = {item["name"]: item for item in checks}["micro_live_backtest_contract_alignment"]

    assert alignment["status"] == "PASS"
    assert "requested_days=1825" in alignment["message"]
    assert "effective_days_range=7.0..7.0" in alignment["message"]


def test_micro_live_config_drift_checks_fail_backtest_contract_drift(monkeypatch, tmp_path) -> None:
    settings = run_micro_live_preflight.get_settings()
    heartbeat_dir = tmp_path / "heartbeats"
    heartbeat_dir.mkdir()
    (heartbeat_dir / "ws.json").write_text(
        json.dumps({"details": {"symbols": ["BTCUSDC"]}}),
        encoding="utf-8",
    )
    report_dir = tmp_path / "backtests"
    report_dir.mkdir()
    (report_dir / "micro_main_usdt_proxy_backtest_20260516T000000Z.json").write_text(
        json.dumps({"proxy_symbols": ["BTCUSDT", "ETHUSDT"], "results": {}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(settings, "runtime_worker_heartbeat_dir", str(heartbeat_dir))
    monkeypatch.setattr(settings, "auto_trading_replay_validation_bridge_backtest_dir", str(report_dir))
    monkeypatch.setattr(settings, "auto_trading_execution_mode", "MICRO_LIVE")
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_allowed_symbols", "BTCUSDC")
    monkeypatch.setattr(settings, "auto_trading_allowed_families", "session_impulse_retest")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", "BTCUSDC")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "session_impulse_retest")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_entry_models", "LIMIT")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_sessions", "london,new_york")
    monkeypatch.setattr(settings, "auto_trading_micro_live_direction_contract", "BTCUSDC:LONG")
    monkeypatch.setattr(settings, "auto_trading_micro_live_event_blackout_path", "")
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_fail_closed", True)
    monkeypatch.setattr(settings, "session_impulse_retest_enabled", True)
    monkeypatch.setattr(settings, "session_impulse_retest_shadow_only", False)
    monkeypatch.setattr(settings, "session_impulse_retest_allowed_symbols", "BTCUSDC")

    checks = run_micro_live_preflight._micro_live_config_drift_checks()
    alignment = {item["name"]: item for item in checks}["micro_live_backtest_contract_alignment"]

    assert alignment["status"] == "FAIL"
    assert alignment["severity"] == "blocking"
    assert "missing_symbols=ETHUSDC" in alignment["message"]
    assert "missing_entry_models=CONFIRM" in alignment["message"]
    assert "unexpected_entry_models=LIMIT" in alignment["message"]
    assert "missing_sessions=dead_session" in alignment["message"]
    assert "missing_long_short_direction=BTCUSDC,ETHUSDC" in alignment["message"]


def test_micro_live_config_drift_checks_warn_on_tracked_only_session_symbols(monkeypatch, tmp_path) -> None:
    settings = run_micro_live_preflight.get_settings()
    heartbeat_dir = tmp_path / "heartbeats"
    heartbeat_dir.mkdir()
    (heartbeat_dir / "ws.json").write_text(
        json.dumps({"details": {"symbols": ["BTCUSDC", "ETHUSDC", "SUIUSDC"]}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "runtime_worker_heartbeat_dir", str(heartbeat_dir))
    monkeypatch.setattr(settings, "auto_trading_execution_mode", "MICRO_LIVE")
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_allowed_symbols", "BTCUSDC,ETHUSDC")
    monkeypatch.setattr(settings, "auto_trading_allowed_families", "session_impulse_retest")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", "BTCUSDC,ETHUSDC")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "session_impulse_retest")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_entry_models", "LIMIT,CONFIRM")
    monkeypatch.setattr(settings, "auto_trading_micro_live_direction_contract", "BTCUSDC:LONG|SHORT,ETHUSDC:LONG|SHORT")
    monkeypatch.setattr(settings, "auto_trading_micro_live_event_blackout_path", "")
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_fail_closed", True)
    monkeypatch.setattr(settings, "session_impulse_retest_enabled", True)
    monkeypatch.setattr(settings, "session_impulse_retest_shadow_only", False)
    monkeypatch.setattr(settings, "session_impulse_retest_allowed_symbols", "BTCUSDC,ETHUSDC,SUIUSDC")

    checks = run_micro_live_preflight._micro_live_config_drift_checks()
    sir_check = {item["name"]: item for item in checks}["session_impulse_retest_live_alignment"]

    assert sir_check["status"] == "PASS"
    assert "tracked_only=SUIUSDC" in sir_check["message"]


def test_micro_live_config_drift_checks_warn_when_live_symbol_is_outside_sir_core_window(
    monkeypatch,
    tmp_path,
) -> None:
    settings = run_micro_live_preflight.get_settings()
    heartbeat_dir = tmp_path / "heartbeats"
    heartbeat_dir.mkdir()
    (heartbeat_dir / "ws.json").write_text(
        json.dumps({"details": {"symbols": ["BTCUSDC", "NEARUSDC"]}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "runtime_worker_heartbeat_dir", str(heartbeat_dir))
    monkeypatch.setattr(settings, "auto_trading_execution_mode", "MICRO_LIVE")
    monkeypatch.setattr(settings, "binance_trade_live_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_allowed_symbols", "BTCUSDC,NEARUSDC")
    monkeypatch.setattr(settings, "auto_trading_allowed_families", "session_impulse_retest")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", "BTCUSDC,NEARUSDC")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_families", "session_impulse_retest")
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_entry_models", "CONFIRM")
    monkeypatch.setattr(settings, "auto_trading_micro_live_direction_contract", "BTCUSDC:LONG|SHORT,NEARUSDC:LONG|SHORT")
    monkeypatch.setattr(settings, "auto_trading_micro_live_event_blackout_path", "")
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_fail_closed", True)
    monkeypatch.setattr(settings, "session_impulse_retest_enabled", True)
    monkeypatch.setattr(settings, "session_impulse_retest_shadow_only", False)
    monkeypatch.setattr(settings, "session_impulse_retest_allowed_symbols", "BTCUSDC,NEARUSDC")
    monkeypatch.setattr(settings, "session_impulse_retest_core_live_slots", 10)
    monkeypatch.setattr(settings, "session_impulse_retest_secondary_live_enabled", False)

    checks = run_micro_live_preflight._micro_live_config_drift_checks()
    window_check = {item["name"]: item for item in checks}["session_impulse_retest_live_rollout_window"]

    assert window_check["status"] == "FAIL"
    assert window_check["severity"] == "warning"
    assert "outside_core_window=NEARUSDC:core11/p12" in window_check["message"]


def test_event_blackout_coverage_check_blocks_missing_live_symbols(tmp_path) -> None:
    blackout_path = tmp_path / "blackouts.json"
    blackout_path.write_text(
        json.dumps(
            {
                "windows": [
                    {
                        "label": "cpi",
                        "start_utc": "2026-01-01T00:00:00Z",
                        "end_utc": "2026-01-01T01:00:00Z",
                        "symbols": ["BTCUSDC"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    check = run_micro_live_preflight._event_blackout_coverage_check(
        raw_path=str(blackout_path),
        live_symbols={"BTCUSDC", "ETHUSDC"},
    )

    assert check["status"] == "FAIL"
    assert check["severity"] == "blocking"
    assert "missing=ETHUSDC" in check["message"]


def test_event_blackout_freshness_check_blocks_expired_contract(tmp_path) -> None:
    blackout_path = tmp_path / "blackouts.json"
    blackout_path.write_text(
        json.dumps(
            {
                "windows": [
                    {
                        "label": "old_cpi",
                        "start_utc": "2026-01-01T00:00:00Z",
                        "end_utc": "2026-01-01T01:00:00Z",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    check = run_micro_live_preflight._event_blackout_freshness_check(
        raw_path=str(blackout_path),
        now=datetime(2026, 5, 10, tzinfo=UTC),
        min_horizon_days=45,
    )

    assert check["status"] == "FAIL"
    assert check["severity"] == "blocking"
    assert "expired" in check["message"]


def test_event_blackout_freshness_check_requires_forward_horizon(tmp_path) -> None:
    blackout_path = tmp_path / "blackouts.json"
    blackout_path.write_text(
        json.dumps(
            {
                "windows": [
                    {
                        "label": "near_cpi",
                        "start_utc": "2026-05-12T12:15:00Z",
                        "end_utc": "2026-05-12T13:00:00Z",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    check = run_micro_live_preflight._event_blackout_freshness_check(
        raw_path=str(blackout_path),
        now=datetime(2026, 5, 10, tzinfo=UTC),
        min_horizon_days=45,
    )

    assert check["status"] == "FAIL"
    assert "horizon_days=2.5" in check["message"]
    assert "min_required=45" in check["message"]


def _validation_payload(*, approve_value: str = "approval usable") -> dict:
    return {
        "deployment_go_no_go": "GO" if approve_value == "approval usable" else "NO_GO",
        "deployment_code": "go_validation" if approve_value == "approval usable" else "no_go_validation",
        "deployment_message": "validation summary",
        "playbook_go_no_go": "GO" if approve_value == "approval usable" else "NO_GO",
        "playbook_action": "review_runtime_execution_drag_before_expansion",
        "validation_report": {
            "approval_strip_summary": {
                "primary_reason": "validation strip summary",
                "approve_value": approve_value,
                "approve_reason": "validation strip summary",
                "align_value": "aligned",
                "align_reason": "validation strip summary",
                "act_value": "review_runtime_execution_drag_before_expansion",
                "act_reason": "review runtime execution drag",
                "act_priority_level": "monitor" if approve_value == "approval usable" else "urgent",
            },
            "operator_action_priority_summary": {
                "top_action": "run_entry_timing_split_review",
                "experiment_context": {
                    "entry_timing_preferred_variant": "early_limit",
                    "execution_style_preferred_variant": "passive_limit",
                    "entry_timing_target": {
                        "symbol": "BTCUSDC",
                        "status": "ACTIONABLE_ENTRY",
                        "strategy_family": "sweep_reversal",
                        "focus_source": "accepted_candidate_focus",
                    },
                    "execution_style_target": {
                        "symbol": "BTCUSDC",
                        "status": "ACTIONABLE_ENTRY",
                        "strategy_family": "sweep_reversal",
                        "focus_source": "accepted_candidate_focus",
                    },
                },
            },
            "edge_evolution_rule_summary": {
                "available": True,
                "advisory_only": True,
                "evolution_state": "reduce_candidate",
                "recommended_action": "reduce_baseline_allocation_review",
                "allocation_bias": "reduce_baseline",
                "promotion_candidate_axis": "entry_timing",
                "promotion_candidate_variant": "early_limit",
                "summary": "Reduce baseline allocation while split evidence stays fragile.",
            },
            "review_followup_ledger_summary": {
                "available": True,
                "last_status": "READY",
                "last_generated_status": "READY",
                "last_decision_status": "ACKED",
                "last_effective_status": "ACKED",
                "last_action": "reduce_baseline_allocation_review",
                "recent_entry_count": 2,
                "last_followup_command": (
                    "./.venv/bin/python scripts/run_split_review_followup.py "
                    "--symbol BTCUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review"
                ),
                "summary": "Latest review packet generated cleanly and is already acknowledged.",
            },
        },
    }


def _checklist_payload(*, approve_value: str = "approval usable") -> dict:
    return {
        "deployment_go_no_go": "GO" if approve_value == "approval usable" else "NO_GO",
        "deployment_code": "go_checklist" if approve_value == "approval usable" else "no_go_checklist",
        "deployment_message": "checklist summary",
        "playbook_go_no_go": "GO" if approve_value == "approval usable" else "NO_GO",
        "playbook_action": "clear_blocking_operational_items_before_rollout",
        "approval_strip_summary": {
            "primary_reason": "checklist strip summary",
            "approve_value": approve_value,
            "approve_reason": "checklist strip summary",
            "align_value": "aligned",
            "align_reason": "checklist strip summary",
            "act_value": "clear_blocking_operational_items_before_rollout",
            "act_reason": "clear blocking items",
            "act_priority_level": "monitor" if approve_value == "approval usable" else "urgent",
        },
        "overall_status": "PASS" if approve_value == "approval usable" else "FAIL",
    }


def _safety_payload() -> dict:
    return {"kill_switch_active": False, "close_only_active": False, "config_close_only_active": False}


def _reconcile_payload() -> dict:
    return {"healthy": True, "highest_severity": "INFO"}


def _alerts_payload() -> dict:
    return {
        "latest_validation_alert": {"deployment_go_no_go": "GO"},
        "overall": {"total": 1},
    }


def _patch_config_drift_pass(monkeypatch) -> None:
    monkeypatch.setattr(
        run_micro_live_preflight,
        "_micro_live_config_drift_checks",
        lambda **_kwargs: [{"name": "config_drift", "status": "PASS", "severity": "blocking", "message": "ok"}],
    )


def test_request_json_retries_after_timeout(monkeypatch) -> None:
    calls = {"count": 0}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return None

        def read(self):
            return b'{"ok": true}'

    def _urlopen(_request, timeout):  # noqa: ANN001
        assert timeout == run_micro_live_preflight._REQUEST_TIMEOUT_SECONDS
        calls["count"] += 1
        if calls["count"] == 1:
            raise TimeoutError("timed out")
        return _Response()

    monkeypatch.setattr(run_micro_live_preflight, "urlopen", _urlopen)

    payload = run_micro_live_preflight._request_json(
        "http://127.0.0.1:8000",
        "GET",
        "/health/live",
    )

    assert payload["ok"] is True
    assert calls["count"] == 2


def _scanner_payload() -> list[dict]:
    return [
        {
            "plan_id": "plan-1",
            "symbol": "BTCUSDC",
            "strategy_family": "sweep_reversal",
            "deployment_go_no_go": "GO",
            "expected_summary": "win≈54.0%, EV≈+0.30R",
        }
    ]


def _empty_scanner_payload() -> list[dict]:
    return []


def _dashboard_with_rollout_policies() -> dict:
    payload = _dashboard_payload()
    payload["execution_mode"] = "MICRO_LIVE"
    payload["rollout_policies"] = [
        {
            "strategy_family": "legacy_zone_plan",
            "live_enabled": False,
            "max_execution_mode": "SHADOW",
        },
        {
            "strategy_family": "sweep_reversal",
            "live_enabled": True,
            "max_execution_mode": "MICRO_LIVE",
        },
    ]
    return payload


def test_surface_strip_summary_prefers_nested_validation_strip() -> None:
    summary = run_micro_live_preflight._surface_strip_summary(
        _validation_payload(approve_value="validation no_go"),
        surface_type="validation",
    )

    assert summary["approve_value"] == "validation no_go"
    assert summary["align_value"] == "aligned"
    assert summary["act_value"] == "review_runtime_execution_drag_before_expansion"


def test_main_emits_approval_surfaces_and_ready_status(monkeypatch, capsys) -> None:
    _patch_config_drift_pass(monkeypatch)
    monkeypatch.setattr(
        run_micro_live_preflight,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            candidate_limit=10,
            report_dir="reports/operations/micro_live_preflight",
            no_write_report=True,
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/health/ready":
            return _ready_payload()
        if path == "/execution/operator-dashboard":
            return _dashboard_payload()
        if path == "/execution/safety-state":
            return _safety_payload()
        if path == "/execution/reconcile":
            return _reconcile_payload()
        if path == "/validation/report":
            return _validation_payload()
        if path == "/operations/checklist":
            return _checklist_payload()
        if path == "/alerts/metrics":
            return _alerts_payload()
        if path == "/scanner/top":
            return _scanner_payload()
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(run_micro_live_preflight, "_request_json", _request_json)

    assert run_micro_live_preflight.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["overall_status"] == "READY_FOR_MICRO_LIVE"
    assert payload["operator_dashboard_summary"]["approval_strip_summary"]["approve_value"] == "approval usable"
    assert payload["validation_report"]["approval_strip_summary"]["act_value"] == "review_runtime_execution_drag_before_expansion"
    assert payload["operations_checklist"]["approval_strip_summary"]["act_value"] == "clear_blocking_operational_items_before_rollout"
    assert payload["approval_surfaces"][0]["label"] == "dashboard"
    assert payload["approval_surfaces"][1]["label"] == "validation"
    assert payload["approval_surfaces"][2]["label"] == "checklist"
    assert payload["edge_experiment_review"]["edge_state"] == "watch_edge"
    assert payload["edge_experiment_review"]["entry_timing_preferred_variant"] == "early_limit"
    assert payload["edge_experiment_review"]["execution_style_preferred_variant"] == "passive_limit"
    assert payload["edge_evolution_rule"]["evolution_state"] == "reduce_candidate"
    assert payload["edge_evolution_rule"]["recommended_action"] == "reduce_baseline_allocation_review"
    assert payload["review_followup_ledger"]["last_status"] == "READY"
    assert payload["review_followup_ledger"]["last_decision_status"] == "ACKED"
    assert payload["experiment_review_targets"]["entry_timing"]["symbol"] == "BTCUSDC"
    assert payload["experiment_review_targets"]["entry_timing"]["action"] == "run_entry_timing_split_review"
    assert payload["experiment_review_targets"]["entry_timing"]["followup_command"].endswith(
        "--symbol BTCUSDC --universe usdc_perp_top30 --days 7 --action run_entry_timing_split_review"
    )
    assert payload["experiment_review_targets"]["execution_style"]["symbol"] == "BTCUSDC"
    assert payload["representative_candidates"]["accepted"]["symbol"] == "BTCUSDC"
    assert payload["representative_candidates"]["accepted"]["edge_state"] == "watch_edge"
    assert payload["representative_candidates"]["blocked"]["symbol"] == "ETHUSDC"
    assert payload["representative_candidates"]["blocked"]["edge_state"] == "fragile_edge"
    assert any("edge proof is still sample-building" in step for step in payload["next_steps"])
    assert any("edge evolution points to baseline reduction" in step for step in payload["next_steps"])
    assert any("scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 7 --action run_entry_timing_split_review" in step for step in payload["next_steps"])
    assert any(
        check["name"] == "validation_language" and "approve=approval usable" in check["message"]
        for check in payload["checks"]
    )


def test_main_keeps_preflight_ready_when_no_candidate_is_live(monkeypatch, capsys) -> None:
    _patch_config_drift_pass(monkeypatch)
    monkeypatch.setattr(
        run_micro_live_preflight,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            candidate_limit=10,
            report_dir="reports/operations/micro_live_preflight",
            no_write_report=True,
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/health/ready":
            return _ready_payload()
        if path == "/execution/operator-dashboard":
            return _dashboard_payload()
        if path == "/execution/safety-state":
            return _safety_payload()
        if path == "/execution/reconcile":
            return _reconcile_payload()
        if path == "/validation/report":
            return _validation_payload()
        if path == "/operations/checklist":
            return _checklist_payload()
        if path == "/alerts/metrics":
            return _alerts_payload()
        if path == "/scanner/top":
            return _empty_scanner_payload()
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(run_micro_live_preflight, "_request_json", _request_json)

    assert run_micro_live_preflight.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["overall_status"] == "READY_FOR_MICRO_LIVE"
    assert "no live-routable scanner candidate" in payload["summary_line"]
    candidate_check = next(item for item in payload["checks"] if item["name"] == "candidate_available")
    assert candidate_check["status"] == "PASS"
    assert "No accepted scanner candidate is live-routable right now" in candidate_check["message"]
    assert any("wait for the next live-routable scanner candidate" in item for item in payload["next_steps"])


def test_main_blocks_preflight_on_manual_review_approval_surface(monkeypatch, capsys) -> None:
    _patch_config_drift_pass(monkeypatch)
    monkeypatch.setattr(
        run_micro_live_preflight,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            candidate_limit=10,
            report_dir="reports/operations/micro_live_preflight",
            no_write_report=True,
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/health/ready":
            return _ready_payload()
        if path == "/execution/operator-dashboard":
            return _dashboard_payload()
        if path == "/execution/safety-state":
            return _safety_payload()
        if path == "/execution/reconcile":
            return _reconcile_payload()
        if path == "/validation/report":
            return _validation_payload(approve_value="manual review first")
        if path == "/operations/checklist":
            return _checklist_payload(approve_value="manual review first")
        if path == "/alerts/metrics":
            return _alerts_payload()
        if path == "/scanner/top":
            return _scanner_payload()
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(run_micro_live_preflight, "_request_json", _request_json)

    assert run_micro_live_preflight.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["overall_status"] == "NOT_READY"
    assert payload["failed_root_causes"] == ["validation_manual_review"]
    assert payload["failed_root_cause_count"] == 1
    assert payload["failed_root_cause_details"][0]["check_names"] == [
        "validation_language",
        "checklist_language",
    ]
    assert payload["failed_root_cause_details"][0]["approve_value"] == "manual review first"
    assert "1 unique root cause" in payload["summary_line"]
    validation_check = next(item for item in payload["checks"] if item["name"] == "validation_language")
    assert validation_check["status"] == "FAIL"
    assert "approve=manual review first" in validation_check["message"]


def test_main_allows_checklist_advisory_manual_review_when_validation_is_go(monkeypatch, capsys) -> None:
    _patch_config_drift_pass(monkeypatch)
    monkeypatch.setattr(
        run_micro_live_preflight,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            candidate_limit=10,
            report_dir="reports/operations/micro_live_preflight",
            no_write_report=True,
        ),
    )

    checklist = _checklist_payload(approve_value="manual review first")
    checklist["deployment_go_no_go"] = "MANUAL_REVIEW"
    checklist["playbook_go_no_go"] = "MANUAL_REVIEW"
    checklist["playbook_action"] = "proceed_with_configured_rollout"
    checklist["overall_status"] = "WARN"
    checklist["blocking_failures"] = 0
    checklist["manual_actions"] = 0
    checklist["warnings"] = 14
    checklist["approval_strip_summary"].update(
        {
            "approve_reason": "GO: approval template is aligned with replay-backed downside.",
            "align_value": "deployment_drift",
            "align_reason": (
                "validation=GO | checklist=MANUAL_REVIEW | validation_action=proceed_with_configured_rollout | "
                "checklist_action=proceed_with_configured_rollout | checklist_status=WARN | "
                "blocking_failures=0 | manual_actions=0 | warnings=14"
            ),
            "act_value": "proceed_with_configured_rollout",
            "act_reason": "GO: approval template is aligned with replay-backed downside.",
            "act_priority_level": "watch",
        }
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/health/ready":
            return _ready_payload()
        if path == "/execution/operator-dashboard":
            return _dashboard_payload()
        if path == "/execution/safety-state":
            return _safety_payload()
        if path == "/execution/reconcile":
            return _reconcile_payload()
        if path == "/validation/report":
            return _validation_payload()
        if path == "/operations/checklist":
            return checklist
        if path == "/alerts/metrics":
            return _alerts_payload()
        if path == "/scanner/top":
            return _empty_scanner_payload()
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(run_micro_live_preflight, "_request_json", _request_json)

    assert run_micro_live_preflight.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["overall_status"] == "READY_FOR_MICRO_LIVE"
    checklist_check = next(item for item in payload["checks"] if item["name"] == "checklist_language")
    assert checklist_check["status"] == "PASS"
    assert "approve=manual review first" in checklist_check["message"]
    assert "classification=advisory_only_checklist_warning_not_order_blocking" in checklist_check["message"]


def test_failed_root_cause_groups_non_manual_approval_surface_failures() -> None:
    details = run_micro_live_preflight._failed_root_cause_details(
        [
            {
                "name": "validation_language",
                "status": "FAIL",
                "message": (
                    "approve=validation no_go | align=playbook_drift | "
                    "act=review_runtime_execution_drag_before_expansion | reason=validation summary"
                ),
            },
            {
                "name": "checklist_language",
                "status": "FAIL",
                "message": (
                    "approve=validation no_go | align=aligned | "
                    "act=clear_blocking_operational_items_before_rollout | reason=checklist summary"
                ),
            },
        ]
    )

    assert len(details) == 1
    assert details[0]["root_cause"] == "validation_approval_surface_validation_no_go"
    assert details[0]["check_names"] == ["validation_language", "checklist_language"]
    assert details[0]["approve_value"] == "validation no_go"


def test_write_report_includes_failed_root_cause_section(tmp_path) -> None:
    report_path = tmp_path / "preflight.md"
    payload = {
        "generated_at": "2026-05-10T00:00:00+00:00",
        "symbol": "BTCUSDC",
        "universe": "usdc_perp_top30",
        "overall_status": "NOT_READY",
        "summary_line": "2 blocking preflight check(s) remain across 1 unique root cause(s).",
        "failed_root_cause_count": 1,
        "failed_root_cause_details": [
            {
                "root_cause": "validation_manual_review",
                "check_names": ["validation_language", "checklist_language"],
                "approve_value": "manual review first",
                "act_value": "hold_rollout_and_review_alignment_details",
                "reason": "MANUAL REVIEW: alignment warning remains.",
            }
        ],
        "checks": [
            {
                "status": "FAIL",
                "name": "validation_language",
                "message": "approve=manual review first | act=hold_rollout_and_review_alignment_details",
            }
        ],
        "surface_timings": [],
        "approval_surfaces": [],
        "edge_experiment_review": {},
        "edge_evolution_rule": {},
        "review_followup_ledger": {},
        "experiment_review_targets": {},
        "representative_candidates": {},
        "candidate": {},
        "next_steps": [],
    }

    run_micro_live_preflight._write_report(report_path, payload)
    raw = report_path.read_text(encoding="utf-8")

    assert "## Failed Root Causes" in raw
    assert "validation_manual_review" in raw
    assert "checks=validation_language, checklist_language" in raw


def test_main_ignores_non_routable_scanner_candidate(monkeypatch, capsys) -> None:
    _patch_config_drift_pass(monkeypatch)
    monkeypatch.setattr(
        run_micro_live_preflight,
        "get_settings",
        lambda: SimpleNamespace(
            auto_trading_allowed_symbols="BTCUSDC,ETHUSDC",
            auto_trading_allowed_families="sweep_reversal",
            auto_trading_micro_live_allowed_symbols="BTCUSDC,ETHUSDC",
            auto_trading_micro_live_allowed_families="sweep_reversal",
        ),
    )
    monkeypatch.setattr(
        run_micro_live_preflight,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            candidate_limit=10,
            report_dir="reports/operations/micro_live_preflight",
            no_write_report=True,
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/health/ready":
            return _ready_payload()
        if path == "/execution/operator-dashboard":
            return _dashboard_with_rollout_policies()
        if path == "/execution/safety-state":
            return _safety_payload()
        if path == "/execution/reconcile":
            return _reconcile_payload()
        if path == "/validation/report":
            return _validation_payload()
        if path == "/operations/checklist":
            return _checklist_payload()
        if path == "/alerts/metrics":
            return _alerts_payload()
        if path == "/scanner/top":
            return [
                {
                    "plan_id": "legacy-plan",
                    "symbol": "BTCUSDC",
                    "strategy_family": "legacy_zone_plan",
                    "deployment_go_no_go": "GO",
                },
                {
                    "plan_id": "sweep-plan",
                    "symbol": "ETHUSDC",
                    "strategy_family": "sweep_reversal",
                    "deployment_go_no_go": "GO",
                },
            ]
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(run_micro_live_preflight, "_request_json", _request_json)

    assert run_micro_live_preflight.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["candidate"]["plan_id"] == "sweep-plan"
    assert payload["ignored_non_routable_candidate_count"] == 1


def test_main_does_not_select_scanner_candidate_when_policy_is_shadow_only(monkeypatch, capsys) -> None:
    _patch_config_drift_pass(monkeypatch)
    monkeypatch.setattr(
        run_micro_live_preflight,
        "get_settings",
        lambda: SimpleNamespace(
            auto_trading_allowed_symbols="BTCUSDC,ETHUSDC",
            auto_trading_allowed_families="sweep_reversal",
            auto_trading_micro_live_allowed_symbols="BTCUSDC,ETHUSDC",
            auto_trading_micro_live_allowed_families="sweep_reversal",
        ),
    )
    monkeypatch.setattr(
        run_micro_live_preflight,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            candidate_limit=10,
            report_dir="reports/operations/micro_live_preflight",
            no_write_report=True,
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/health/ready":
            return _ready_payload()
        if path == "/execution/operator-dashboard":
            return _dashboard_with_rollout_policies()
        if path == "/execution/safety-state":
            return _safety_payload()
        if path == "/execution/reconcile":
            return _reconcile_payload()
        if path == "/validation/report":
            return _validation_payload()
        if path == "/operations/checklist":
            return _checklist_payload()
        if path == "/alerts/metrics":
            return _alerts_payload()
        if path == "/scanner/top":
            return [
                {
                    "plan_id": "legacy-plan",
                    "symbol": "BTCUSDC",
                    "strategy_family": "legacy_zone_plan",
                    "deployment_go_no_go": "GO",
                }
            ]
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(run_micro_live_preflight, "_request_json", _request_json)

    assert run_micro_live_preflight.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["candidate"] == {}
    assert payload["ignored_non_routable_candidate_count"] == 1
    assert "no live-routable scanner candidate" in payload["summary_line"]
    candidate_check = next(item for item in payload["checks"] if item["name"] == "candidate_available")
    assert "ignored_non_routable_candidates=1" in candidate_check["message"]


def test_main_does_not_select_scanner_candidate_outside_symbol_allowlist(monkeypatch, capsys) -> None:
    _patch_config_drift_pass(monkeypatch)
    monkeypatch.setattr(
        run_micro_live_preflight,
        "get_settings",
        lambda: SimpleNamespace(
            auto_trading_allowed_symbols="BTCUSDC,ETHUSDC",
            auto_trading_allowed_families="sweep_reversal",
            auto_trading_micro_live_allowed_symbols="BTCUSDC,ETHUSDC",
            auto_trading_micro_live_allowed_families="sweep_reversal",
        ),
    )
    monkeypatch.setattr(
        run_micro_live_preflight,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            candidate_limit=10,
            report_dir="reports/operations/micro_live_preflight",
            no_write_report=True,
        ),
    )

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        if path == "/health/ready":
            return _ready_payload()
        if path == "/execution/operator-dashboard":
            return _dashboard_with_rollout_policies()
        if path == "/execution/safety-state":
            return _safety_payload()
        if path == "/execution/reconcile":
            return _reconcile_payload()
        if path == "/validation/report":
            return _validation_payload()
        if path == "/operations/checklist":
            return _checklist_payload()
        if path == "/alerts/metrics":
            return _alerts_payload()
        if path == "/scanner/top":
            return [
                {
                    "plan_id": "fil-sweep-plan",
                    "symbol": "FILUSDC",
                    "strategy_family": "sweep_reversal",
                    "deployment_go_no_go": "GO",
                }
            ]
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(run_micro_live_preflight, "_request_json", _request_json)

    assert run_micro_live_preflight.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["candidate"] == {}
    assert payload["ignored_non_routable_candidate_count"] == 1


def test_main_uses_read_only_queries_for_reconcile_validation_and_checklist(monkeypatch, capsys) -> None:
    _patch_config_drift_pass(monkeypatch)
    monkeypatch.setattr(
        run_micro_live_preflight,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=7,
            candidate_limit=10,
            report_dir="reports/operations/micro_live_preflight",
            no_write_report=True,
        ),
    )

    calls: dict[str, dict] = {}

    def _request_json(base_url: str, method: str, path: str, **kwargs):  # noqa: ARG001
        calls[path] = kwargs
        if path == "/health/ready":
            return _ready_payload()
        if path == "/execution/operator-dashboard":
            return _dashboard_payload()
        if path == "/execution/safety-state":
            return _safety_payload()
        if path == "/execution/reconcile":
            return _reconcile_payload()
        if path == "/validation/report":
            return _validation_payload()
        if path == "/operations/checklist":
            return _checklist_payload()
        if path == "/alerts/metrics":
            return _alerts_payload()
        if path == "/scanner/top":
            return _empty_scanner_payload()
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(run_micro_live_preflight, "_request_json", _request_json)

    assert run_micro_live_preflight.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert calls["/execution/reconcile"]["query"] == {"apply_lock": "false", "auto_resolve": "false"}
    assert calls["/execution/operator-dashboard"]["query"] == {
        "symbol": "BTCUSDC",
        "universe": "usdc_perp_top30",
        "days": 7,
        "portfolio_limit": 5,
        "intent_limit": 5,
        "reconcile_limit": 5,
        "fast": "true",
    }
    assert calls["/validation/report"]["query"] == {
        "symbol": "BTCUSDC",
        "refresh": "false",
        "cache_fallback": "true",
    }
    assert calls["/operations/checklist"]["query"] == {"symbol": "BTCUSDC", "write_report": "false"}
    assert calls["/scanner/top"]["query"] == {"universe": "usdc_perp_top30", "limit": 10, "fast": "true"}
    assert [row["path"] for row in payload["surface_timings"]] == [
        "/health/ready",
        "/execution/operator-dashboard",
        "/execution/safety-state",
        "/execution/reconcile",
        "/validation/report",
        "/operations/checklist",
        "/alerts/metrics",
        "/scanner/top",
    ]
    assert {row["status"] for row in payload["surface_timings"]} == {"PASS"}


def test_request_json_refreshes_validation_report_when_read_only_cache_is_missing(monkeypatch) -> None:
    calls: list[dict[str, list[str]]] = []

    def fake_urlopen(request, timeout):  # noqa: ANN001, ARG001
        parsed = urlparse(request.full_url)
        query = parse_qs(parsed.query)
        calls.append(query)
        if query.get("refresh") == ["false"]:
            raise HTTPError(
                request.full_url,
                404,
                "not found",
                hdrs=None,
                fp=io.BytesIO(b'{"detail":"cached validation payload is not available yet; call with refresh=true first"}'),
            )
        return _JsonResponse({"symbol": "BTCUSDC", "validation_report": {"cached": False}})

    monkeypatch.setattr(run_micro_live_preflight, "urlopen", fake_urlopen)

    payload = run_micro_live_preflight._request_json(
        "http://127.0.0.1:8000",
        "POST",
        "/validation/report",
        query={"symbol": "BTCUSDC", "refresh": "false"},
    )

    assert payload == {"symbol": "BTCUSDC", "validation_report": {"cached": False}}
    assert calls == [
        {"symbol": ["BTCUSDC"], "refresh": ["false"]},
        {"symbol": ["BTCUSDC"], "refresh": ["true"]},
    ]


def test_request_json_reports_endpoint_on_timeout(monkeypatch) -> None:
    def fake_urlopen(request, timeout):  # noqa: ANN001, ARG001
        raise TimeoutError("timed out")

    monkeypatch.setattr(run_micro_live_preflight, "urlopen", fake_urlopen)
    monkeypatch.setattr(run_micro_live_preflight, "_REQUEST_RETRY_ATTEMPTS", 1)
    monkeypatch.setattr(run_micro_live_preflight, "_REQUEST_TIMEOUT_SECONDS", 2.0)

    with pytest.raises(RuntimeError, match=r"GET /scanner/top timed out after 2s"):
        run_micro_live_preflight._request_json(
            "http://127.0.0.1:8000",
            "GET",
            "/scanner/top",
            query={"universe": "usdc_perp_top30", "limit": 10},
        )


def test_validation_cache_fallback_is_valid_not_ready_payload() -> None:
    payload = _validation_report_cache_miss_payload("btcusdc")
    parsed = ValidationReportOut(**payload)
    strip = run_micro_live_preflight._surface_strip_summary(
        parsed.model_dump(mode="json"),
        surface_type="validation",
    )

    assert parsed.symbol == "BTCUSDC"
    assert strip["act_value"] == "refresh_validation_report"
    assert run_micro_live_preflight._surface_allows_preflight(strip) is False


def test_validation_cache_fallback_prefers_stale_conservative_payload() -> None:
    class _Engine:
        def _load_cached_validation_payload(self, symbol: str) -> None:  # noqa: ARG002
            return None

        def _load_stale_conservative_validation_payload(self, symbol: str) -> dict:
            return {
                "symbol": symbol,
                "updated_zones": 0,
                "metrics": {},
                "walk_forward": {},
                "monte_carlo": {},
                "validation_report": {
                    "approval_strip_summary": {
                        "approve_value": "manual review first",
                        "align_value": "playbook_drift",
                        "act_value": "hold_rollout_and_review_alignment_details",
                    }
                },
            }

    parsed = validation_report_route(
        symbol="BTCUSDC",
        refresh=False,
        cache_fallback=True,
        engine=_Engine(),
    )

    assert parsed.symbol == "BTCUSDC"
    assert parsed.validation_report["approval_strip_summary"]["approve_value"] == "manual review first"
    assert parsed.validation_report["approval_strip_summary"]["act_value"] == "hold_rollout_and_review_alignment_details"


def test_validation_report_refresh_bypasses_read_only_cache() -> None:
    class _Engine:
        def __init__(self) -> None:
            self.kwargs: dict[str, object] = {}

        def recompute_learning(self, symbol: str, **kwargs) -> dict:
            self.kwargs = kwargs
            return {
                "symbol": symbol,
                "updated_zones": 0,
                "metrics": {},
                "walk_forward": {},
                "monte_carlo": {},
                "validation_report": {
                    "approval_strip_summary": {
                        "approve_value": "manual review first",
                        "align_value": "playbook_drift",
                        "act_value": "hold_rollout_and_review_alignment_details",
                    }
                },
            }

    engine = _Engine()
    parsed = validation_report_route(symbol="BTCUSDC", refresh=True, engine=engine)

    assert parsed.symbol == "BTCUSDC"
    assert engine.kwargs["persist_runtime_validation_artifacts"] is False
    assert engine.kwargs["use_read_only_cache"] is False
