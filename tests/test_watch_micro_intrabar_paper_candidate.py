from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.services.micro_main_strategy_research import MicroSignal
from scripts import watch_micro_intrabar_paper_candidate as watch


def _signal(**diagnostics):
    return MicroSignal(
        family="session_impulse_retest",
        direction="long",
        signal_ts=datetime(2026, 5, 18, 13, 5, tzinfo=UTC),
        setup_ts=datetime(2026, 5, 18, 13, 5, tzinfo=UTC),
        entry_ts=datetime(2026, 5, 18, 13, 6, tzinfo=UTC),
        entry_price=100.0,
        stop_price=99.0,
        target_price=102.0,
        max_hold_minutes=40,
        regime_hint="session_open_intrabar",
        diagnostics=diagnostics,
    )


def test_passes_filter_contract_for_selected_candidate() -> None:
    passed, reasons = watch._passes_filter_contract(
        _signal(setup_hour_utc=13, volume_factor=1.3, reclaim_body_atr=0.3),
        {
            "direction": "long",
            "setup_hour_utc": [13, 14],
            "min_volume_factor": 1.2,
            "min_reclaim_body_atr": 0.25,
        },
    )

    assert passed is True
    assert reasons == []


def test_passes_filter_contract_for_risk_atr_candidate() -> None:
    passed, reasons = watch._passes_filter_contract(
        _signal(setup_hour_utc=14, volume_factor=1.3, risk_atr=0.55),
        {
            "direction": "long",
            "setup_hour_utc": [13, 14],
            "min_volume_factor": 1.2,
            "min_risk_atr": 0.5,
        },
    )

    assert passed is True
    assert reasons == []


def test_filter_contract_reports_each_failed_condition() -> None:
    signal = _signal(
        setup_hour_utc=7,
        volume_factor=1.1,
        reclaim_body_atr=0.2,
        risk_atr=0.4,
        retest_wait_minutes=4,
        entry_distance_atr=0.8,
    )
    object.__setattr__(signal, "direction", "short")

    passed, reasons = watch._passes_filter_contract(
        signal,
        {
            "direction": "long",
            "setup_hour_utc": [13, 14],
            "min_volume_factor": 1.2,
            "min_reclaim_body_atr": 0.25,
            "min_risk_atr": 0.5,
            "max_retest_wait_minutes": 3,
            "max_entry_distance_atr": 0.5,
        },
    )

    assert passed is False
    assert reasons == [
        "direction_mismatch",
        "setup_hour_not_allowed",
        "volume_factor_below_contract",
        "reclaim_body_atr_below_contract",
        "risk_atr_below_contract",
        "retest_wait_above_contract",
        "entry_distance_atr_above_contract",
    ]


def test_summarize_rows_counts_symbols_hours_and_directions() -> None:
    rows = [
        {"symbol": "BTCUSDT", "direction": "long", "diagnostics": {"setup_hour_utc": 13}},
        {"symbol": "BTCUSDT", "direction": "long", "diagnostics": {"setup_hour_utc": 14}},
        {"symbol": "ETHUSDT", "direction": "short", "diagnostics": {"setup_hour_utc": 13}},
    ]

    summary = watch._summarize_rows(rows)

    assert summary["count"] == 3
    assert summary["by_symbol"] == {"BTCUSDT": 2, "ETHUSDT": 1}
    assert summary["by_direction"] == {"long": 2, "short": 1}
    assert summary["by_setup_hour_utc"] == {"13": 2, "14": 1}


def test_symbols_from_expansion_review(tmp_path: Path) -> None:
    report = tmp_path / "expansion.json"
    report.write_text(
        json.dumps({"shadow_watchlist_symbols": [" solusdt ", "ADAUSDT", ""]}),
        encoding="utf-8",
    )

    assert watch._symbols_from_expansion_review(report) == ["SOLUSDT", "ADAUSDT"]


def test_csv_symbols_dedupes_and_uppercases() -> None:
    assert watch._csv_symbols("btcusdt, ETHUSDT,btcusdt") == ["BTCUSDT", "ETHUSDT"]


def test_watch_uses_intrabar_zero_delay_policy() -> None:
    policy = watch._select_exit_policy("structure_buffered_swing6_stop0.12_tpbuf0.08")

    assert policy.entry_confirmation_delay_minutes == 0
