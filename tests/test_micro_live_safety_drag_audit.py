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


def test_main_default_backtest_selection_uses_current_settings(monkeypatch, tmp_path, capsys) -> None:
    selected_report = tmp_path / "micro_main_usdt_proxy_backtest_20260515T175711Z.json"
    selected_report.write_text(json.dumps({"results": {}}), encoding="utf-8")
    settings = _settings(
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_symbols="BTCUSDC",
    )
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        audit,
        "_parse_args",
        lambda: SimpleNamespace(
            backtest_report="",
            report_dir=str(tmp_path),
            include_samples=False,
            no_write_report=True,
        ),
    )
    monkeypatch.setattr(audit, "get_settings", lambda: settings)
    def _select_backtest_report(selected_settings):
        seen["settings"] = selected_settings
        return selected_report

    monkeypatch.setattr(audit, "_latest_backtest_report", _select_backtest_report)
    monkeypatch.setattr(
        audit,
        "build_payload",
        lambda *, backtest_report, include_samples: {
            "generated_at": "2026-05-16T00:00:00Z",
            "backtest_report": str(backtest_report),
            "include_samples": include_samples,
        },
    )

    assert audit.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert seen["settings"] is settings
    assert payload["backtest_report"] == str(selected_report)
    assert payload["include_samples"] is False


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


def test_build_payload_marks_backtest_live_contract_mismatch(monkeypatch, tmp_path) -> None:
    start = datetime(2026, 5, 16, 1, 0, tzinfo=UTC)
    report = tmp_path / "micro_main_usdt_backtest_20260516T000000Z.json"
    report.write_text(
        json.dumps(
            {
                "source": "micro_main_usdt_backtest",
                "generated_at": start.isoformat(),
                "symbols": ["BTCUSDT"],
                "results": {
                    "BTCUSDT": {
                        "trades": [
                            {
                                "family": "session_impulse_retest",
                                "symbol": "BTCUSDT",
                                "direction": "long",
                                "entry_ts": start.isoformat(),
                                "exit_ts": (start + timedelta(minutes=5)).isoformat(),
                                "entry_price": 100.0,
                                "stop_distance_pct": 0.01,
                                "r_value": 1.0,
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    settings = _settings(
        auto_trading_execution_mode="MICRO_LIVE",
        auto_trading_micro_live_allowed_symbols="BTCUSDC",
    )
    monkeypatch.setattr(audit, "get_settings", lambda: settings)
    monkeypatch.setattr(audit, "_load_event_blackouts", lambda _settings: [])
    monkeypatch.setattr(audit, "_load_plan_blocklist", lambda _settings: set())

    payload = audit.build_payload(backtest_report=report, include_samples=False)

    assert payload["overall_status"] == "CONFIG_MISMATCH"
    assert payload["contract_alignment"]["status"] == "MISMATCH"
    assert payload["contract_alignment"]["missing_from_backtest"] == ["BTCUSDC"]
    assert payload["contract_alignment"]["unexpected_in_backtest"] == ["BTCUSDT"]
