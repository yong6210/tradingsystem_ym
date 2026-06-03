from collections import Counter
from types import SimpleNamespace

from scripts.run_market_state_rotation_v6_backtest import (
    RotationMemory,
    _book_open_role_payloads,
    _drawdown_bar_event_payload,
    _event_risk_base_size_multiplier,
    _event_trade_cost,
    _event_diagnostics,
    _one_way_full_exit_ready,
)


def _diagnostic_config(**overrides):
    values = {
        "max_possible_units": 1.0,
        "base_add_units": 1.0,
        "equity_soft_circuit_force_flat": False,
        "equity_soft_circuit_size_mult": 1.0,
        "equity_soft_circuit_prearm_bars": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_book_open_role_payloads_counts_active_tranches_by_role() -> None:
    book = SimpleNamespace(
        tranches=[
            SimpleNamespace(role="base", qty=1.0),
            SimpleNamespace(role="base", qty=0.25),
            SimpleNamespace(role="probe", qty=0.125),
            SimpleNamespace(role="chase", qty=0.0),
        ]
    )

    lot_counts, qty_by_role = _book_open_role_payloads(book)

    assert lot_counts == {"base": 2, "probe": 1}
    assert qty_by_role == {"base": 1.25, "probe": 0.125}


def test_drawdown_bar_event_payload_keeps_recent_core_fields() -> None:
    payload = _drawdown_bar_event_payload(
        [
            {"action": "add", "side": "long", "qty": 1, "price": 100, "reason": "old"},
            {
                "action": "remove",
                "side": "short",
                "qty": 0.5,
                "price": 110,
                "reason": "forced_trim",
                "role": "base",
                "pnl_usd_units": -5.0,
                "extra_noise": "ignored",
            },
        ],
        limit=1,
    )

    assert payload == [
        {"omitted_events": 1},
        {
            "action": "remove",
            "side": "short",
            "qty": 0.5,
            "price": 110,
            "reason": "forced_trim",
            "role": "base",
            "pnl_usd_units": -5.0,
        },
    ]


def test_one_way_full_exit_uses_absolute_score_diff() -> None:
    config = SimpleNamespace(
        one_way_trim_full_exit_min_one_way_score=7.5,
        one_way_trim_full_exit_min_score_diff=5,
    )

    assert _one_way_full_exit_ready(
        config,
        SimpleNamespace(one_way_score=7.7083, score_diff=-5),
    )
    assert _one_way_full_exit_ready(
        config,
        SimpleNamespace(one_way_score=7.7083, score_diff=5),
    )
    assert not _one_way_full_exit_ready(
        config,
        SimpleNamespace(one_way_score=7.4, score_diff=-5),
    )


def test_soft_circuit_recovery_failure_guard_sets_cooldown() -> None:
    memory = RotationMemory()

    assert not memory.record_equity_soft_circuit_recovery_failure(
        100,
        guard_count=2,
        window_bars=50,
        cooldown_bars=200,
    )
    assert not memory.in_equity_soft_circuit_recovery_failure_cooldown(149)

    assert memory.record_equity_soft_circuit_recovery_failure(
        120,
        guard_count=2,
        window_bars=50,
        cooldown_bars=200,
    )
    assert memory.in_equity_soft_circuit_recovery_failure_cooldown(320)
    assert not memory.in_equity_soft_circuit_recovery_failure_cooldown(321)


def test_event_trade_cost_records_cost_breakdown() -> None:
    cost_breakdown = {
        "by_action": Counter(),
        "by_reason": Counter(),
        "by_role": Counter(),
        "by_side": Counter(),
        "by_action_reason": Counter(),
        "by_action_role": Counter(),
    }
    counters = Counter()

    cost = _event_trade_cost(
        config=SimpleNamespace(max_account_exposure=10.0, max_possible_units=1.0),
        new_events=[
            {
                "action": "add",
                "side": "long",
                "qty": 0.5,
                "reason": "base_entry",
                "role": "base",
            },
            {
                "action": "remove",
                "side": "long",
                "qty": 0.5,
                "reason": "hard_intraday_time_exit",
                "role": "base",
            },
        ],
        cost_rate=0.001,
        counters=counters,
        cost_breakdown=cost_breakdown,
    )

    assert round(cost, 8) == 0.00675
    assert round(cost_breakdown["by_action"]["add"], 8) == 0.00175
    assert round(cost_breakdown["by_action"]["remove"], 8) == 0.005
    assert round(cost_breakdown["by_reason"]["base_entry"], 8) == 0.00175
    assert round(cost_breakdown["by_reason"]["hard_intraday_time_exit"], 8) == 0.005
    assert round(cost_breakdown["by_action_reason"]["remove:hard_intraday_time_exit"], 8) == 0.005
    assert counters["passive_cost_events"] == 1
    assert counters["aggressive_cost_events"] == 1


def test_event_risk_base_multiplier_targets_late_hour_open_short_base_only() -> None:
    config = SimpleNamespace(
        event_risk_base_reduce_contexts=("hour_open",),
        event_risk_base_reduce_side="short",
        event_risk_base_reduce_min_extension_atr=2.5,
        event_risk_base_reduce_size_mult=0.25,
    )

    assert _event_risk_base_size_multiplier(
        config,
        SimpleNamespace(execution_context="hour_open", chase_extension_atr=2.6),
        -1,
        "base",
    ) == 0.25
    assert _event_risk_base_size_multiplier(
        config,
        SimpleNamespace(execution_context="normal", chase_extension_atr=2.6),
        -1,
        "base",
    ) == 1.0
    assert _event_risk_base_size_multiplier(
        config,
        SimpleNamespace(execution_context="hour_open", chase_extension_atr=2.4),
        -1,
        "base",
    ) == 1.0
    assert _event_risk_base_size_multiplier(
        config,
        SimpleNamespace(execution_context="hour_open", chase_extension_atr=2.6),
        1,
        "base",
    ) == 1.0
    assert _event_risk_base_size_multiplier(
        config,
        SimpleNamespace(execution_context="hour_open", chase_extension_atr=2.6),
        -1,
        "probe",
    ) == 1.0

    zero_config = SimpleNamespace(
        event_risk_base_reduce_contexts=("hour_open",),
        event_risk_base_reduce_side="short",
        event_risk_base_reduce_min_extension_atr=2.5,
        event_risk_base_reduce_size_mult=0.0,
    )
    assert _event_risk_base_size_multiplier(
        zero_config,
        SimpleNamespace(execution_context="hour_open", chase_extension_atr=2.6),
        -1,
        "base",
    ) == 0.0


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


def test_event_diagnostics_reports_no_trade_context_hotspots() -> None:
    counters = Counter(
        {
            (
                "no_trade_context::"
                "MC12_low_confluence|long|with_trend|uptrend|normal|"
                "score_5-7|edge_1-2|stack_1-2|ext_0.75-1.5|break_0-0.1"
            ): 11,
            (
                "no_trade_context::"
                "MC04_no_clear_first_touch|flat|neutral|mixed|hour_open|"
                "score_3-5|edge_0-1|stack_1-2|ext_0-0.75|break_0-0.1"
            ): 7,
            "no_trade_reason_side::MC12_low_confluence|long": 11,
            "no_trade_reason_side::MC04_no_clear_first_touch|flat": 7,
            "no_trade_reason_regime::MC12_low_confluence|uptrend": 11,
            "no_trade_reason_regime::MC04_no_clear_first_touch|mixed": 7,
        }
    )

    diagnostics = _event_diagnostics(
        events=[],
        counters=counters,
        exposure_side_bars=Counter({"flat": 100}),
        exposure_bars=100,
        total_months=1,
        config=_diagnostic_config(),
    )

    assert diagnostics["top_no_trade_contexts"] == {
        (
            "MC12_low_confluence|long|with_trend|uptrend|normal|"
            "score_5-7|edge_1-2|stack_1-2|ext_0.75-1.5|break_0-0.1"
        ): 11,
        (
            "MC04_no_clear_first_touch|flat|neutral|mixed|hour_open|"
            "score_3-5|edge_0-1|stack_1-2|ext_0-0.75|break_0-0.1"
        ): 7,
    }
    assert diagnostics["no_trade_reason_side_counts"] == {
        "MC12_low_confluence|long": 11,
        "MC04_no_clear_first_touch|flat": 7,
    }
    assert diagnostics["no_trade_reason_regime_counts"] == {
        "MC12_low_confluence|uptrend": 11,
        "MC04_no_clear_first_touch|mixed": 7,
    }


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
        "one_way_forced_trim_overuse",
    ]
    assert diagnostics["month_concentration_context"]["status"] == "borderline_broadly_active"
    assert diagnostics["month_concentration_context"]["flag_suppressed"]
    assert diagnostics["max_month_add_share"] == 0.45
    assert diagnostics["ratios"]["one_way_forced_trim_per_add"] == 0.5


def test_short_sample_missing_month_keeps_month_concentration_borderline() -> None:
    months = [5] * 9 + [6] * 6 + [7] * 5
    events = [
        {
            "action": "add",
            "side": "long" if idx % 2 == 0 else "short",
            "ts": f"2025-{month:02d}-{idx + 1:02d}T{idx % 20:02d}:00:00+00:00",
        }
        for idx, month in enumerate(months)
    ]

    diagnostics = _event_diagnostics(
        events=events,
        counters=Counter(),
        exposure_side_bars=Counter({"long": 500, "short": 500}),
        exposure_bars=1000,
        total_months=4,
        config=_diagnostic_config(),
    )

    assert diagnostics["health"] == "ok"
    assert diagnostics["flags"] == []
    assert diagnostics["borderline_flags"] == ["month_concentration"]
    assert diagnostics["month_concentration_context"]["status"] == "borderline"
    assert not diagnostics["month_concentration_context"]["flag_suppressed"]
    assert diagnostics["month_concentration_context"]["active_months"] == 3
    assert diagnostics["max_month_add_share"] == 0.45


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


def test_profitable_role_mix_suppresses_role_concentration_borderline() -> None:
    events = [
        {
            "action": "add",
            "side": "long" if idx % 2 == 0 else "short",
            "role": "base" if idx < 12 else "probe",
            "ts": f"2025-{5 + idx % 4:02d}-{idx + 1:02d}T00:00:00+00:00",
        }
        for idx in range(14)
    ]
    events.extend(
        [
            {"action": "remove", "side": "long", "role": "base", "pnl_usd_units": 12.0},
            {"action": "remove", "side": "short", "role": "probe", "pnl_usd_units": 1.0},
        ]
    )

    diagnostics = _event_diagnostics(
        events=events,
        counters=Counter(),
        exposure_side_bars=Counter({"long": 500, "short": 500}),
        exposure_bars=1000,
        total_months=4,
        config=_diagnostic_config(),
    )

    assert diagnostics["health"] == "ok"
    assert diagnostics["flags"] == []
    assert diagnostics["borderline_flags"] == []
    assert diagnostics["role_concentration_context"]["status"] == "borderline_profitable_mix"
    assert diagnostics["role_concentration_context"]["flag_suppressed"]
    assert diagnostics["role_concentration_context"]["dominant_role_share"] == 0.8571


def test_losing_role_mix_keeps_role_concentration_borderline() -> None:
    events = [
        {
            "action": "add",
            "side": "long" if idx % 2 == 0 else "short",
            "role": "base" if idx < 12 else "probe",
            "ts": f"2025-{5 + idx % 4:02d}-{idx + 1:02d}T00:00:00+00:00",
        }
        for idx in range(14)
    ]
    events.extend(
        [
            {"action": "remove", "side": "long", "role": "base", "pnl_usd_units": -12.0},
            {"action": "remove", "side": "short", "role": "probe", "pnl_usd_units": 1.0},
        ]
    )

    diagnostics = _event_diagnostics(
        events=events,
        counters=Counter(),
        exposure_side_bars=Counter({"long": 500, "short": 500}),
        exposure_bars=1000,
        total_months=4,
        config=_diagnostic_config(),
    )

    assert diagnostics["health"] == "ok"
    assert diagnostics["flags"] == []
    assert diagnostics["borderline_flags"] == ["role_concentration"]
    assert diagnostics["role_concentration_context"]["status"] == "borderline"
    assert not diagnostics["role_concentration_context"]["flag_suppressed"]


def test_capacity_structure_context_reports_single_unit_battle_saturation() -> None:
    events = [
        {
            "action": "add",
            "side": "long" if idx % 2 == 0 else "short",
            "role": "base",
            "ts": f"2025-{5 + idx % 4:02d}-{idx + 1:02d}T00:00:00+00:00",
        }
        for idx in range(16)
    ]

    diagnostics = _event_diagnostics(
        events=events,
        counters=Counter({"base_adds": 16}),
        exposure_side_bars=Counter({"long": 500, "short": 500}),
        exposure_bars=1000,
        total_months=4,
        config=_diagnostic_config(max_possible_units=1.0, base_add_units=1.0, max_account_exposure=10.0),
    )

    context = diagnostics["capacity_structure_context"]
    assert "battle_capacity_saturated" not in diagnostics["flags"]
    assert diagnostics["ratios"]["battle_capacity_saturated"]
    assert context["status"] == "battle_capacity_saturated"
    assert not context["scale_in_capacity_available"]
    assert context["capacity_after_first_base_units"] == 0.0
    assert context["unit_account_exposure"] == 10.0
    assert context["base_add_account_exposure"] == 10.0
    assert context["base_add_share"] == 1.0


def test_capacity_structure_context_reports_available_scale_in_capacity() -> None:
    events = [
        {
            "action": "add",
            "side": "long",
            "role": "base" if idx < 8 else "battle",
            "ts": f"2025-05-{idx + 1:02d}T00:00:00+00:00",
        }
        for idx in range(12)
    ]

    diagnostics = _event_diagnostics(
        events=events,
        counters=Counter({"base_adds": 8, "battle_adds": 4}),
        exposure_side_bars=Counter({"long": 1000}),
        exposure_bars=1000,
        total_months=4,
        config=_diagnostic_config(
            max_possible_units=3.0,
            base_add_units=1.0,
            base_max_units=2.0,
            max_account_exposure=10.0,
        ),
    )

    context = diagnostics["capacity_structure_context"]
    assert not diagnostics["ratios"]["battle_capacity_saturated"]
    assert context["status"] == "scale_in_capacity_available"
    assert context["scale_in_capacity_available"]
    assert context["capacity_after_first_base_units"] == 2.0
    assert context["unit_account_exposure"] == 3.333333
    assert context["base_add_account_exposure"] == 3.333333
    assert context["battle_add_ratio"] == 0.3333


def test_trend_aligned_side_concentration_is_not_side_imbalance() -> None:
    events = [
        {
            "action": "add",
            "side": "short",
            "regime": "downtrend",
            "ts": f"2025-{5 + idx % 4:02d}-{idx + 1:02d}T{idx % 20:02d}:00:00+00:00",
        }
        for idx in range(12)
    ]
    events.extend(
        [
            {
                "action": "add",
                "side": "long",
                "regime": "uptrend",
                "ts": "2025-08-20T00:00:00+00:00",
            },
            {"action": "remove", "side": "short", "pnl_usd_units": 10.0},
            {"action": "remove", "side": "long", "pnl_usd_units": 1.0},
        ]
    )

    diagnostics = _event_diagnostics(
        events=events,
        counters=Counter(),
        exposure_side_bars=Counter({"long": 100, "short": 900}),
        exposure_bars=1000,
        total_months=4,
        config=_diagnostic_config(),
    )

    assert diagnostics["health"] == "ok"
    assert diagnostics["flags"] == []
    assert diagnostics["side_imbalance_context"]["status"] == "trend_aligned"
    assert diagnostics["side_imbalance_context"]["flag_suppressed"]
    assert diagnostics["side_imbalance_context"]["dominant_side"] == "short"
    assert diagnostics["side_imbalance_context"]["dominant_side_share"] == 0.9231
    assert diagnostics["side_imbalance_context"]["dominant_side_trend_aligned_share"] == 1.0


def test_wrong_regime_side_concentration_still_reports_side_imbalance() -> None:
    events = [
        {
            "action": "add",
            "side": "short",
            "regime": "uptrend",
            "ts": f"2025-{5 + idx % 4:02d}-{idx + 1:02d}T{idx % 20:02d}:00:00+00:00",
        }
        for idx in range(12)
    ]
    events.extend(
        [
            {
                "action": "add",
                "side": "long",
                "regime": "uptrend",
                "ts": "2025-08-20T00:00:00+00:00",
            },
            {"action": "remove", "side": "short", "pnl_usd_units": 10.0},
            {"action": "remove", "side": "long", "pnl_usd_units": 1.0},
        ]
    )

    diagnostics = _event_diagnostics(
        events=events,
        counters=Counter(),
        exposure_side_bars=Counter({"long": 100, "short": 900}),
        exposure_bars=1000,
        total_months=4,
        config=_diagnostic_config(),
    )

    assert diagnostics["health"] == "watch"
    assert diagnostics["flags"] == ["side_imbalance"]
    assert diagnostics["side_imbalance_context"]["status"] == "imbalanced"
    assert not diagnostics["side_imbalance_context"]["flag_suppressed"]
    assert diagnostics["side_imbalance_context"]["dominant_side"] == "short"
    assert diagnostics["side_imbalance_context"]["dominant_side_trend_aligned_share"] == 0.0
