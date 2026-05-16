from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings
from app.core.enums import ExecutionMode
from app.services.replay_validation_bridge import UsdtProxyReplayValidationBridge


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        auto_trading_live_risk_per_trade_pct=0.01,
        auto_trading_replay_validation_bridge_backtest_dir=str(tmp_path / "backtests"),
        auto_trading_replay_validation_bridge_portfolio_dir=str(tmp_path / "risk_sweeps"),
        auto_trading_replay_validation_bridge_max_age_days=30.0,
    )


def _write_pass_reports(tmp_path: Path) -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    _write_json(
        tmp_path / "backtests" / "micro_main_usdt_proxy_backtest_20260510T114636Z.json",
        {
            "generated_at": generated_at,
            "days": 1095,
            "results": {
                "BTCUSDT": {
                    "proxy_symbol": "BTCUSDT",
                    "canonical_symbol": "BTCUSDC",
                    "summary": {
                        "closed": 141,
                        "ev_r": 0.5307,
                        "total_r": 74.8267,
                        "win_rate": 0.6454,
                        "decision": "PASS",
                    },
                }
            },
        },
    )
    _write_json(
        tmp_path / "risk_sweeps" / "micro_main_usdt_proxy_yearly_portfolio_replay_20260510T113926Z.json",
        {
            "generated_at": generated_at,
            "symbols": {"BTCUSDC": {"year_1": {}, "year_2": {}, "year_3": {}}},
            "horizons": {
                "year_1": {"1.0%": {"accepted_trades": 1437, "return_pct": 743.83, "max_drawdown_pct": 6.90}},
                "year_2": {"1.0%": {"accepted_trades": 1597, "return_pct": 941.94, "max_drawdown_pct": 10.93}},
                "year_3": {"1.0%": {"accepted_trades": 1363, "return_pct": 740.05, "max_drawdown_pct": 6.16}},
            },
        },
    )


def _write_sweep_walk_forward_cache(tmp_path: Path) -> Path:
    generated_at = datetime.now(timezone.utc).isoformat()
    rows = []
    base_ts = datetime(2024, 1, 8, 8, 0, tzinfo=timezone.utc)
    for index in range(140):
        realized_r = 1.2 if index % 3 != 0 else -0.25
        rows.append(
            {
                "symbol": "BTCUSDC",
                "direction": "LONG" if index % 2 == 0 else "SHORT",
                "strategy_family": "sweep_reversal",
                "entry_model": "LIMIT",
                "generated_ts": (base_ts.replace(day=((index % 20) + 1))).isoformat(),
                "closed_ts": (base_ts.replace(day=((index % 20) + 1), hour=9)).isoformat(),
                "final_exit_realized_r": realized_r,
                "final_exit_reason": "target_tp2" if realized_r > 0 else "structure_failure",
            }
        )
    cache_path = tmp_path / "historical_walk_forward_cache" / "strategy_proof_contract_live_subset.json"
    _write_json(
        cache_path,
        {
            "generated_at": generated_at,
            "simulation_start_ts": "2024-01-01T00:00:00+00:00",
            "simulation_end_ts": "2026-05-01T00:00:00+00:00",
            "trade_rows": rows,
        },
    )
    return cache_path


def test_replay_validation_bridge_promotes_missing_runtime_sample(tmp_path: Path) -> None:
    _write_pass_reports(tmp_path)
    bridge = UsdtProxyReplayValidationBridge(_settings(tmp_path))

    metrics = bridge.apply_to_metrics(
        {
            "grade": "F",
            "recommendation": "do-not-deploy",
            "sample_size": 0,
            "risk_state": "OPEN",
            "risk_reason": "normal",
        },
        symbol="BTCUSDC",
        family="session_impulse_retest",
        requested_mode=ExecutionMode.MICRO_LIVE.value,
    )

    assert metrics["recommendation"] == "paper-and-limited-live"
    assert metrics["grade"] == "B"
    assert metrics["sample_size"] == 141
    assert metrics["ev_r"] == 0.5307
    assert metrics["validation_bridge"]["applied"] is True
    assert "replay_validation_bridge_approval_usable" in metrics["reason_codes"]


def test_replay_validation_bridge_prefers_latest_named_backtest_over_mtime(tmp_path: Path) -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    old_path = tmp_path / "backtests" / "micro_main_usdt_proxy_backtest_20260515T083304Z.json"
    new_path = tmp_path / "backtests" / "micro_main_usdt_proxy_backtest_20260515T175711Z.json"
    _write_json(
        old_path,
        {
            "generated_at": generated_at,
            "days": 1095,
            "results": {
                "BTCUSDT": {
                    "proxy_symbol": "BTCUSDT",
                    "canonical_symbol": "BTCUSDC",
                    "summary": {"closed": 1, "ev_r": -1.0, "total_r": -1.0, "win_rate": 0.0, "decision": "FAIL"},
                }
            },
        },
    )
    _write_json(
        new_path,
        {
            "generated_at": generated_at,
            "days": 1095,
            "results": {
                "BTCUSDT": {
                    "proxy_symbol": "BTCUSDT",
                    "canonical_symbol": "BTCUSDC",
                    "summary": {
                        "closed": 141,
                        "ev_r": 0.5307,
                        "total_r": 74.8267,
                        "win_rate": 0.6454,
                        "decision": "PASS",
                    },
                }
            },
        },
    )
    old_path.touch()
    _write_json(
        tmp_path / "risk_sweeps" / "micro_main_usdt_proxy_yearly_portfolio_replay_20260510T113926Z.json",
        {
            "generated_at": generated_at,
            "symbols": {"BTCUSDC": {"year_1": {}, "year_2": {}, "year_3": {}}},
            "horizons": {
                "year_1": {"1.0%": {"accepted_trades": 1437, "return_pct": 743.83, "max_drawdown_pct": 6.90}},
                "year_2": {"1.0%": {"accepted_trades": 1597, "return_pct": 941.94, "max_drawdown_pct": 10.93}},
                "year_3": {"1.0%": {"accepted_trades": 1363, "return_pct": 740.05, "max_drawdown_pct": 6.16}},
            },
        },
    )
    bridge = UsdtProxyReplayValidationBridge(_settings(tmp_path))

    metrics = bridge.apply_to_metrics(
        {
            "grade": "F",
            "recommendation": "do-not-deploy",
            "sample_size": 0,
            "risk_state": "OPEN",
            "risk_reason": "normal",
        },
        symbol="BTCUSDC",
        family="session_impulse_retest",
        requested_mode=ExecutionMode.MICRO_LIVE.value,
    )

    assert metrics["sample_size"] == 141
    assert "20260515T175711Z" in metrics["validation_bridge"]["source_reports"]["backtest_report"]


def test_replay_validation_bridge_does_not_override_existing_live_sample(tmp_path: Path) -> None:
    _write_pass_reports(tmp_path)
    bridge = UsdtProxyReplayValidationBridge(_settings(tmp_path))

    metrics = bridge.apply_to_metrics(
        {
            "grade": "F",
            "recommendation": "do-not-deploy",
            "sample_size": 45,
            "ev_r": -0.12,
            "risk_state": "OPEN",
            "risk_reason": "normal",
        },
        symbol="BTCUSDC",
        family="session_impulse_retest",
        requested_mode=ExecutionMode.MICRO_LIVE.value,
    )

    assert metrics["recommendation"] == "do-not-deploy"
    assert metrics["sample_size"] == 45
    assert metrics["ev_r"] == -0.12
    assert metrics["validation_bridge"]["applied"] is False
    assert metrics["validation_bridge"]["reason_code"] == "runtime_validation_sample_available"


def test_replay_validation_bridge_promotes_sweep_reversal_limit_active_contract(tmp_path: Path) -> None:
    cache_path = _write_sweep_walk_forward_cache(tmp_path)
    settings = _settings(tmp_path)
    settings.auto_trading_replay_validation_bridge_sweep_reversal_cache_file = str(cache_path)
    settings.auto_trading_micro_live_allowed_sessions = "london,new_york"
    settings.auto_trading_micro_live_direction_contract = "BTCUSDC:LONG|SHORT"
    bridge = UsdtProxyReplayValidationBridge(settings)

    metrics = bridge.apply_to_metrics(
        {
            "grade": "F",
            "recommendation": "do-not-deploy",
            "sample_size": 0,
            "risk_state": "OPEN",
            "risk_reason": "normal",
        },
        symbol="BTCUSDC",
        family="sweep_reversal",
        requested_mode=ExecutionMode.MICRO_LIVE.value,
        entry_model="LIMIT",
    )

    assert metrics["recommendation"] in {"paper-and-limited-live", "deploy-small-capital"}
    assert metrics["sample_size"] == 140
    assert metrics["validation_source"] == "historical_walk_forward_sweep_reversal_bridge"
    assert metrics["validation_bridge"]["source"] == "historical_walk_forward_sweep_reversal_bridge"
    assert metrics["validation_bridge"]["applied"] is True
    assert "historical_walk_forward_sweep_reversal_bridge_approval_usable" in metrics["reason_codes"]


def test_replay_validation_bridge_stresses_sweep_reversal_structure_failure(tmp_path: Path) -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    base_ts = datetime(2024, 1, 8, 8, 0, tzinfo=timezone.utc)
    rows = []
    for index in range(141):
        structure_failure = index < 64
        rows.append(
            {
                "symbol": "BTCUSDC",
                "direction": "LONG",
                "strategy_family": "sweep_reversal",
                "entry_model": "LIMIT",
                "generated_ts": (base_ts.replace(day=((index % 20) + 1))).isoformat(),
                "closed_ts": (base_ts.replace(day=((index % 20) + 1), hour=9)).isoformat(),
                "final_exit_realized_r": -0.0 if structure_failure else 1.2,
                "final_exit_reason": "structure_failure" if structure_failure else "target_tp2",
                "final_exit_trigger_detail": {
                    "policy": "btc_sweep_reversal_limit_initial_guard_stop",
                }
                if structure_failure
                else {},
            }
        )
    cache_path = tmp_path / "historical_walk_forward_cache" / "strategy_proof_contract_live_subset.json"
    _write_json(
        cache_path,
        {
            "generated_at": generated_at,
            "simulation_start_ts": "2024-01-01T00:00:00+00:00",
            "simulation_end_ts": "2026-05-01T00:00:00+00:00",
            "trade_rows": rows,
        },
    )
    settings = _settings(tmp_path)
    settings.auto_trading_replay_validation_bridge_sweep_reversal_cache_file = str(cache_path)
    settings.auto_trading_micro_live_allowed_sessions = "london,new_york"
    bridge = UsdtProxyReplayValidationBridge(settings)

    metrics = bridge.apply_to_metrics(
        {
            "grade": "F",
            "recommendation": "do-not-deploy",
            "sample_size": 0,
            "risk_state": "OPEN",
            "risk_reason": "normal",
        },
        symbol="BTCUSDC",
        family="sweep_reversal",
        requested_mode=ExecutionMode.MICRO_LIVE.value,
        entry_model="LIMIT",
    )

    bridge_payload = metrics["validation_bridge"]
    assert bridge_payload["applied"] is False
    assert bridge_payload["metrics"]["structure_failure_stress_r"] == -1.0
    assert bridge_payload["metrics"]["structure_failure_share"] == 0.4539
    assert "historical_walk_forward_stop_loss_share_above_cap" in bridge_payload["reason_codes"]


def test_replay_validation_bridge_does_not_promote_sweep_reversal_confirm(tmp_path: Path) -> None:
    cache_path = _write_sweep_walk_forward_cache(tmp_path)
    settings = _settings(tmp_path)
    settings.auto_trading_replay_validation_bridge_sweep_reversal_cache_file = str(cache_path)
    bridge = UsdtProxyReplayValidationBridge(settings)

    metrics = bridge.apply_to_metrics(
        {
            "grade": "F",
            "recommendation": "do-not-deploy",
            "sample_size": 0,
            "risk_state": "OPEN",
            "risk_reason": "normal",
        },
        symbol="BTCUSDC",
        family="sweep_reversal",
        requested_mode=ExecutionMode.MICRO_LIVE.value,
        entry_model="CONFIRM",
    )

    assert metrics["recommendation"] == "do-not-deploy"
    assert metrics["validation_bridge"]["applied"] is False
    assert metrics["validation_bridge"]["reason_code"] == "replay_validation_entry_model_not_bridgeable"
