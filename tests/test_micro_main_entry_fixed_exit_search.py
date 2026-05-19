from __future__ import annotations

from datetime import UTC, datetime

from app.services.micro_main_strategy_research import SessionImpulseRetestExitPolicy
from scripts import run_micro_main_entry_fixed_exit_search as search
from scripts.run_micro_main_exit_policy_search import build_exit_policies


def _row(policy: str, total_r: float, score: float, closed: int = 100) -> dict:
    return {
        "policy": policy,
        "symbol": "BTCUSDT",
        "direction": "long",
        "entry_ts": "2026-05-18T00:00:00+00:00",
        "exit_ts": "2026-05-18T00:01:00+00:00",
        "entry_price": 100.0,
        "stop_price": 99.0,
        "target_price": 102.0,
        "stop_distance_pct": 0.01,
        "r_value": total_r / closed,
        "gross_r": total_r / closed + 0.1,
        "cost_r": 0.1,
        "hold_minutes": 1,
        "exit_reason": "target",
        "entry_year": 2026,
        "diagnostics": {"score_hint": score},
    }


def test_entry_fixed_policy_disables_entry_rejection_fields() -> None:
    policy = search._entry_fixed_policy(
        SessionImpulseRetestExitPolicy(
            name="candidate",
            structure_targets_enabled=True,
            structure_entry_max_distance_atr=0.45,
            higher_timeframe_structure_enabled=True,
            higher_timeframe_entry_min_score=1.0,
            max_stop_pct=0.01,
            max_risk_atr=1.0,
            entry_confirmation_delay_minutes=0,
        )
    )

    assert policy.entry_confirmation_delay_minutes == 5
    assert policy.structure_entry_max_distance_atr == 0.0
    assert policy.higher_timeframe_entry_min_score == 0.0
    assert policy.max_stop_pct == 0.0
    assert policy.max_risk_atr == 0.0


def test_important_zone_policies_are_available_for_entry_fixed_search() -> None:
    names = {policy.name for policy in build_exit_policies()}

    assert "important_zone:lookback21:hold40:stopon:ideal1.8:tpmax2.8" in names


def test_select_policies_preserves_case_sensitive_policy_names() -> None:
    policies = search._select_policies(
        "important_zone:lookback21:hold40:stopon:ideal1.8:tpmax2.8",
        0,
        entry_delay_minutes=0,
    )

    assert policies[0].name == "important_zone:lookback21:hold40:stopon:ideal1.8:tpmax2.8"
    assert policies[0].entry_confirmation_delay_minutes == 0


def test_build_report_keeps_same_entry_better_than_baseline_bucket() -> None:
    policies = [
        SessionImpulseRetestExitPolicy(name="legacy_full_2r"),
        SessionImpulseRetestExitPolicy(name="candidate"),
    ]
    rows_by_policy = {
        "legacy_full_2r": [_row("legacy_full_2r", 1.0, 1.0)],
        "candidate": [_row("candidate", 1.2, 1.2)],
    }

    report = search.build_report(
        symbols=["BTCUSDT"],
        days=30,
        policies=policies,
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
        start_ts=datetime(2026, 4, 18, tzinfo=UTC),
        end_ts=datetime(2026, 5, 18, tzinfo=UTC),
        data_status={"BTCUSDT": {"policy_rejected_signals": {"legacy_full_2r": 0, "candidate": 0}}},
        rows_by_policy=rows_by_policy,
        trade_count_floor_ratio=0.98,
        top_limit=10,
        include_trades=False,
    )

    assert report["baseline"]["summary"]["closed"] == 1
    assert report["better_than_baseline_same_entry"][0]["policy"]["name"] == "candidate"
