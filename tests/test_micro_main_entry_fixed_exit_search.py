from __future__ import annotations

from datetime import UTC, datetime

from app.services.micro_main_strategy_research import MicroSignal
from scripts import run_micro_main_entry_fixed_exit_search as fixed_exit_search


def _signal(
    *,
    direction: str = "long",
    setup_hour_utc: int = 14,
    reclaim_body_atr: float = 0.3,
    entry_distance_atr: float = 0.2,
) -> MicroSignal:
    ts = datetime(2026, 5, 19, setup_hour_utc, tzinfo=UTC)
    return MicroSignal(
        family="session_impulse_retest",
        direction=direction,  # type: ignore[arg-type]
        signal_ts=ts,
        setup_ts=ts,
        entry_ts=ts,
        entry_price=100.0,
        stop_price=99.0,
        target_price=102.0,
        max_hold_minutes=40,
        regime_hint="test",
        diagnostics={
            "setup_hour_utc": setup_hour_utc,
            "volume_factor": 1.0,
            "reclaim_body_atr": reclaim_body_atr,
            "risk_atr": 0.5,
            "retest_wait_minutes": 5,
            "entry_distance_atr": entry_distance_atr,
        },
    )


def test_signal_contract_filter_matches_live_direction_hour_and_quality_fields() -> None:
    contract = {
        "symbols": ["ADAUSDT"],
        "filter_contract": {
            "direction": "long",
            "setup_hour_utc": [14],
            "min_reclaim_body_atr": 0.25,
            "max_entry_distance_atr": 0.4,
        },
    }

    assert fixed_exit_search._passes_signal_contract(_signal(), symbol="ADAUSDT", contract=contract)
    assert not fixed_exit_search._passes_signal_contract(
        _signal(setup_hour_utc=13),
        symbol="ADAUSDT",
        contract=contract,
    )
    assert not fixed_exit_search._passes_signal_contract(
        _signal(reclaim_body_atr=0.1),
        symbol="ADAUSDT",
        contract=contract,
    )
    assert not fixed_exit_search._passes_signal_contract(_signal(), symbol="BTCUSDT", contract=contract)


def test_filter_base_signals_keeps_entries_from_any_matching_contract() -> None:
    contracts = [
        {
            "path": "long.json",
            "symbols": ["ADAUSDT"],
            "filter_contract": {"direction": "long", "setup_hour_utc": [14]},
        },
        {
            "path": "short.json",
            "symbols": ["ADAUSDT"],
            "filter_contract": {"direction": "short", "setup_hour_utc": [7]},
        },
    ]
    signals = [
        _signal(direction="long", setup_hour_utc=14),
        _signal(direction="short", setup_hour_utc=7),
        _signal(direction="long", setup_hour_utc=13),
    ]

    selected, counts = fixed_exit_search._filter_base_signals(
        symbol="ADAUSDT",
        base_signals=signals,
        signal_contracts=contracts,
    )

    assert selected == signals[:2]
    assert counts == {"long.json": 1, "short.json": 1}
