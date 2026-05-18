from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scripts import run_micro_main_intrabar_research as intrabar
from scripts.run_micro_main_exit_policy_search import build_exit_policies


def test_grouped_summaries_support_nested_diagnostics() -> None:
    rows = [
        {
            "policy": "p",
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry_ts": "2026-05-18T00:00:00+00:00",
            "exit_ts": "2026-05-18T00:01:00+00:00",
            "r_value": 1.0,
            "gross_r": 1.1,
            "cost_r": 0.1,
            "stop_distance_pct": 0.01,
            "hold_minutes": 1,
            "exit_reason": "target",
            "entry_year": 2026,
            "diagnostics": {"setup_hour_utc": 0},
        },
        {
            "policy": "p",
            "symbol": "ETHUSDT",
            "direction": "short",
            "entry_ts": "2026-05-18T01:00:00+00:00",
            "exit_ts": "2026-05-18T01:01:00+00:00",
            "r_value": -1.0,
            "gross_r": -0.9,
            "cost_r": 0.1,
            "stop_distance_pct": 0.01,
            "hold_minutes": 1,
            "exit_reason": "stop",
            "entry_year": 2026,
            "diagnostics": {"setup_hour_utc": 1},
        },
    ]

    grouped = intrabar._grouped_summaries(rows, "diagnostics.setup_hour_utc")

    assert grouped["0"]["total_r"] == 1.0
    assert grouped["1"]["total_r"] == -1.0


def test_report_stamp_includes_microseconds_to_avoid_same_second_collision() -> None:
    first = datetime(2026, 5, 18, 0, 0, 0, 1, tzinfo=UTC)
    second = first + timedelta(microseconds=1)

    assert intrabar._report_stamp(first) != intrabar._report_stamp(second)


def test_intrabar_policy_sets_zero_confirmation_delay() -> None:
    policy = intrabar._select_policies(["structure_buffered_swing6_stop0.12_tpbuf0.08"])[0]

    assert policy.entry_confirmation_delay_minutes == 0


def test_structure_buffered_position_management_variants_are_available() -> None:
    names = {policy.name for policy in build_exit_policies()}

    assert "structure_buffered_swing6_stop0.12_tpbuf0.08_pm_stop0.00r" in names
    assert "structure_buffered_swing6_stop0.12_tpbuf0.08_pm_stop0.10r" in names
    assert "structure_buffered_swing6_stop0.12_tpbuf0.08_pm_stop0.10r_advvol_postpartial" in names
