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


def test_partial_risk_off_uses_active_window_order_coverage() -> None:
    diagnostics = _event_diagnostics(
        events=[{"action": "add", "side": "long"} for _ in range(3)],
        counters=Counter({"equity_soft_circuit_cooldown_bars": 630}),
        exposure_side_bars=Counter({"long": 370, "flat": 630}),
        exposure_bars=1000,
        total_months=4,
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
    assert diagnostics["sample_mode"] == "risk_off_partial"
    assert diagnostics["risk_off_cooldown_share"] == 0.63
    assert diagnostics["diagnostic_thresholds"]["expected_add_events"] == 12
    assert diagnostics["diagnostic_thresholds"]["risk_adjusted_expected_add_events"] == 3
    assert diagnostics["diagnostic_thresholds"]["risk_off_active_share"] == 0.37


def test_short_sample_boundary_concentration_is_borderline_not_watch() -> None:
    events = []
    days = [
        *[f"2025-06-{day:02d}T00:00:00+00:00" for day in range(1, 10)],
        *[f"2025-05-{day:02d}T00:00:00+00:00" for day in range(18, 21)],
        *[f"2025-07-{day:02d}T00:00:00+00:00" for day in range(1, 5)],
        *[f"2025-08-{day:02d}T00:00:00+00:00" for day in range(1, 5)],
    ]
    for idx, ts in enumerate(days):
        ts = ts.replace("T00:", f"T{idx % 20:02d}:")
        events.append({"action": "add", "side": "long" if idx % 2 == 0 else "short", "ts": ts})

    diagnostics = _event_diagnostics(
        events=events,
        counters=Counter({"one_way_forced_trims": 10}),
        exposure_side_bars=Counter({"long": 500, "short": 500}),
        exposure_bars=1000,
        total_months=4,
        config=SimpleNamespace(
            max_possible_units=1.0,
            base_add_units=1.0,
            equity_soft_circuit_force_flat=False,
            equity_soft_circuit_size_mult=1.0,
            equity_soft_circuit_prearm_bars=0,
        ),
    )

    assert diagnostics["health"] == "ok"
    assert diagnostics["flags"] == []
    assert diagnostics["borderline_flags"] == [
        "month_concentration",
        "one_way_forced_trim_overuse",
    ]
    assert diagnostics["max_month_add_share"] == 0.45
    assert diagnostics["ratios"]["one_way_forced_trim_per_add"] == 0.5


def test_role_concentration_reports_single_entry_role_dependency() -> None:
    events = [
        {
            "action": "add",
            "side": "long" if idx % 2 == 0 else "short",
            "role": "base" if idx < 12 else "probe",
            "ts": f"2025-{5 + idx % 4:02d}-{idx + 1:02d}T00:00:00+00:00",
        }
        for idx in range(13)
    ]

    diagnostics = _event_diagnostics(
        events=events,
        counters=Counter(),
        exposure_side_bars=Counter({"long": 500, "short": 500}),
        exposure_bars=1000,
        total_months=4,
        config=SimpleNamespace(
            max_possible_units=1.0,
            base_add_units=1.0,
            equity_soft_circuit_force_flat=False,
            equity_soft_circuit_size_mult=1.0,
            equity_soft_circuit_prearm_bars=0,
        ),
    )

    assert diagnostics["health"] == "watch"
    assert diagnostics["flags"] == ["role_concentration"]
    assert diagnostics["dominant_add_role"] == "base"
    assert diagnostics["max_role_add_share"] == 0.9231
    assert diagnostics["add_role_share"] == {"base": 0.9231, "probe": 0.0769}
