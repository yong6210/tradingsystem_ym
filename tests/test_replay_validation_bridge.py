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

