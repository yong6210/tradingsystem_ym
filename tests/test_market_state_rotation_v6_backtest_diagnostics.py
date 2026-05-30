from collections import Counter
from types import SimpleNamespace

from scripts.run_market_state_rotation_v6_backtest import _event_diagnostics


def test_risk_off_idle_does_not_count_as_too_few_orders() -> None:
    diagnostics = _event_diagnostics(
        events=[],
        counters=Counter({"equity_soft_circuit_cooldown_bars": 100}),
        exposure_side_bars=Counter({"flat": 100}),
        exposure_bars=100,
        total_months=3,
        config=SimpleNamespace(
            max_possible_units=1.0,
            base_add_units=1.0,
            equity_soft_circuit_force_flat=True,
            equity_soft_circuit_size_mult=0.0,
            equity_soft_circuit_prearm_bars=50,
        ),
    )

    assert diagnostics["health"] == "ok"
    assert diagnostics["flags"] == []
    assert diagnostics["sample_mode"] == "risk_off_idle"
    assert diagnostics["risk_off_cooldown_share"] == 1.0


def test_ordinary_idle_still_reports_too_few_orders() -> None:
    diagnostics = _event_diagnostics(
        events=[],
        counters=Counter(),
        exposure_side_bars=Counter({"flat": 100}),
        exposure_bars=100,
        total_months=3,
        config=SimpleNamespace(
            max_possible_units=1.0,
            base_add_units=1.0,
            equity_soft_circuit_force_flat=False,
            equity_soft_circuit_size_mult=1.0,
            equity_soft_circuit_prearm_bars=0,
        ),
    )

    assert diagnostics["health"] == "watch"
    assert diagnostics["flags"] == ["too_few_orders"]
    assert diagnostics["sample_mode"] == "active"
