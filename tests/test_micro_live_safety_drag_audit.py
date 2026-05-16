from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from scripts import run_micro_live_safety_drag_audit as audit


def _settings(**overrides):
    base = {
        "auto_trading_micro_live_max_concurrent_positions": 2,
        "auto_trading_micro_live_max_daily_new_entries": 0,
        "auto_trading_live_family_cluster_window_minutes": 60,
        "auto_trading_live_max_same_family_entries_per_window": 1,
        "auto_trading_live_max_same_family_direction_exposures": 1,
        "auto_trading_live_recent_loss_cooldown_minutes": 90,
        "auto_trading_live_recent_loss_trigger_count": 2,
        "session_impulse_retest_saturday_risk_multiplier": 0.75,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_latest_backtest_report_prefers_matching_live_contract(monkeypatch, tmp_path) -> None:
    backtest_dir = tmp_path / "backtests"
    backtest_dir.mkdir()
    matching = backtest_dir / "micro_main_usdt_proxy_backtest_20260515T175711Z.json"
    matching.write_text(
        json.dumps({"proxy_symbols": ["BTCUSDT"], "results": {}}),
        encoding="utf-8",
    )
    (backtest_dir / "micro_main_usdt_proxy_backtest_20260516T095759Z.json").write_text(
        json.dumps({"proxy_symbols": ["BTCUSDT", "ETHUSDT"], "results": {}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "BACKTEST_DIR", backtest_dir)

    selected = audit._latest_backtest_report(
        _settings(
            auto_trading_execution_mode="MICRO_LIVE",
            auto_trading_micro_live_allowed_symbols="BTCUSDC",
        )
    )

    assert selected == matching


def _row(
    *,
    symbol: str,
    entry_ts: datetime,
    hold_minutes: int,
    direction: str = "long",
    r_value: float = 1.0,
):
    return {
        "family": "session_impulse_retest",
        "symbol": symbol,
        "direction": direction,
        "entry_ts": entry_ts.isoformat(),
        "exit_ts": (entry_ts + timedelta(minutes=hold_minutes)).isoformat(),
        "entry_ts_dt": entry_ts,
        "exit_ts_dt": entry_ts + timedelta(minutes=hold_minutes),
        "r_value": r_value,
        "r_value_float": r_value,
    }


def test_cluster_guard_does_not_block_already_closed_trade_inside_window() -> None:
    start = datetime(2026, 5, 15, 1, 0, tzinfo=UTC)
    rows = [
        _row(symbol="BTCUSDC", entry_ts=start, hold_minutes=5),
        _row(symbol="ETHUSDC", entry_ts=start + timedelta(minutes=30), hold_minutes=5),
    ]

    accepted, blocked = audit._simulate_pacing(_settings(), rows)

    assert len(accepted) == 2
    assert blocked == []


def test_cluster_guard_blocks_open_same_family_position_inside_window() -> None:
    start = datetime(2026, 5, 15, 1, 0, tzinfo=UTC)
    rows = [
        _row(symbol="BTCUSDC", entry_ts=start, hold_minutes=45),
        _row(symbol="ETHUSDC", entry_ts=start + timedelta(minutes=30), hold_minutes=5),
    ]

    accepted, blocked = audit._simulate_pacing(_settings(), rows)

    assert len(accepted) == 1
    assert len(blocked) == 1
    assert blocked[0]["audit_block_reason"] == "live_family_cluster_window_cap_reached"


def test_saturday_risk_multiplier_is_applied_to_accepted_rows() -> None:
    saturday = datetime(2026, 5, 16, 1, 0, tzinfo=UTC)
    rows = [_row(symbol="BTCUSDC", entry_ts=saturday, hold_minutes=5, r_value=2.0)]

    accepted, blocked = audit._simulate_pacing(_settings(), rows)

    assert blocked == []
    assert accepted[0]["audit_risk_multiplier"] == 0.75
    assert accepted[0]["risk_adjusted_r"] == 1.5
