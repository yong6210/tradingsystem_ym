from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from scripts import run_micro_live_safety_grid_search as grid


def _prepared(
    *,
    entry_minute: int,
    hold_minutes: int,
    direction: int = 1,
    r_value: float = 1.0,
) -> grid.PreparedTrade:
    entry_ts = datetime(2026, 5, 15, 1, entry_minute, tzinfo=UTC)
    return grid.PreparedTrade(
        entry_ts=entry_ts,
        exit_ts=entry_ts + timedelta(minutes=hold_minutes),
        direction=direction,
        r_value=r_value,
    )


def test_grid_simulation_tracks_position_cap_and_risk_stats() -> None:
    rows = [
        _prepared(entry_minute=0, hold_minutes=20, r_value=1.0),
        _prepared(entry_minute=1, hold_minutes=5, r_value=2.0),
        _prepared(entry_minute=25, hold_minutes=5, r_value=-1.0),
    ]
    case = grid.SafetyCase(
        max_pos=1,
        cluster_window=30,
        cluster_cap=3,
        direction_cap=3,
        loss_window=60,
        loss_trigger=4,
        sat=1.0,
    )

    result = grid._simulate_case(
        rows,
        case,
        baseline_closed=3,
        baseline_total_r=2.0,
        include_risk_stats=True,
    )

    assert result["closed"] == 2
    assert result["total_r"] == 0.0
    assert result["blocked"] == 1
    assert result["reasons"] == {"micro_live_position_cap_reached": 1}
    assert result["max_dd"] == 1.0
    assert result["worst_loss_streak"] == 1


def test_deployable_filter_rejects_disabled_safety_cases() -> None:
    assert not grid._is_deployable(
        {
            "max_pos": 0,
            "cluster_window": 0,
            "cluster_cap": 0,
            "direction_cap": 0,
            "loss_window": 0,
            "loss_trigger": 0,
        }
    )
    assert grid._is_deployable(
        {
            "max_pos": 3,
            "cluster_window": 30,
            "cluster_cap": 3,
            "direction_cap": 3,
            "loss_window": 60,
            "loss_trigger": 4,
        }
    )


def test_prepare_trades_preserves_canonical_input_order() -> None:
    start = datetime(2026, 5, 15, 1, 0, tzinfo=UTC)
    rows = [
        {
            "direction": "long",
            "entry_ts_dt": start,
            "exit_ts_dt": start + timedelta(minutes=20),
            "r_value_float": 1.0,
        },
        {
            "direction": "short",
            "entry_ts_dt": start,
            "exit_ts_dt": start + timedelta(minutes=5),
            "r_value_float": 2.0,
        },
    ]

    prepared = grid._prepare_trades(rows)

    assert [row.r_value for row in prepared] == [1.0, 2.0]


def test_build_payload_separates_raw_top_from_deployable_recommendation(monkeypatch, tmp_path) -> None:
    start = datetime(2026, 5, 15, 1, 0, tzinfo=UTC)
    rows = [
        {
            "family": "session_impulse_retest",
            "symbol": "BTCUSDC",
            "direction": "long",
            "entry_ts": start.isoformat(),
            "exit_ts": (start + timedelta(minutes=20)).isoformat(),
            "entry_ts_dt": start,
            "exit_ts_dt": start + timedelta(minutes=20),
            "r_value": 1.0,
            "r_value_float": 1.0,
        },
        {
            "family": "session_impulse_retest",
            "symbol": "ETHUSDC",
            "direction": "long",
            "entry_ts": (start + timedelta(minutes=1)).isoformat(),
            "exit_ts": (start + timedelta(minutes=6)).isoformat(),
            "entry_ts_dt": start + timedelta(minutes=1),
            "exit_ts_dt": start + timedelta(minutes=6),
            "r_value": 2.0,
            "r_value_float": 2.0,
        },
    ]

    monkeypatch.setattr(
        grid,
        "_load_contract_pass",
        lambda _path: ({"generated_at": "test"}, rows, rows),
    )
    monkeypatch.setattr(
        grid,
        "get_settings",
        lambda: SimpleNamespace(
            auto_trading_micro_live_max_concurrent_positions=1,
            auto_trading_live_family_cluster_window_minutes=30,
            auto_trading_live_max_same_family_entries_per_window=1,
            auto_trading_live_max_same_family_direction_exposures=1,
            auto_trading_live_recent_loss_cooldown_minutes=60,
            auto_trading_live_recent_loss_trigger_count=2,
            session_impulse_retest_saturday_risk_multiplier=1.0,
        ),
    )

    payload = grid.build_payload(
        backtest_report=tmp_path / "backtest.json",
        position_caps=[1],
        cluster_windows=[0, 30],
        cluster_caps=[0, 2],
        direction_caps=[0, 2],
        loss_windows=[0, 60],
        loss_triggers=[0, 2],
        saturday_multipliers=[1.0],
        include_unlimited_diagnostic=True,
    )

    raw_unlimited = [row for row in payload["raw_top_20"] if row["max_pos"] == 0]
    assert raw_unlimited
    assert raw_unlimited[0]["total_r"] == 3.0
    assert payload["recommended"]["max_pos"] == 1
    assert payload["recommended"]["total_r"] == 1.0
