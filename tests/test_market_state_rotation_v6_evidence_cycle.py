import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import scripts.run_market_state_rotation_v6_evidence_cycle as evidence
from scripts.run_market_state_rotation_v6_collection_cycle import CYCLE_REPORT_NAME
from scripts.run_market_state_rotation_v6_evidence_cycle import EVIDENCE_REPORT_NAME, run_evidence_cycle
from scripts.run_market_state_rotation_v6_quote_shadow_audit import build_quote_shadow_row
from scripts.run_market_state_rotation_v6_safety_controls_audit import REQUIRED_SAFETY_CONTROLS


def _book() -> dict:
    return {
        "bids": [["99999", "1.0"], ["99998", "1.0"]],
        "asks": [["100001", "1.0"], ["100002", "1.0"]],
    }


def _cycle_report(
    *,
    bridge_status: str = "not_actionable",
    blockers: list[str] | None = None,
    apply_paper: bool = False,
    market_data_age_minutes: float = 5.0,
    max_cache_age_minutes: int = 30,
) -> dict:
    return {
        "bridge": {
            "overall_status": bridge_status,
            "apply_paper": apply_paper,
            "snapshot_blockers": ["signal_stale"] if blockers is None else blockers,
            "bridge_action": "remove",
            "freshness": {
                "market_data_age_minutes": market_data_age_minutes,
                "signal_age_minutes": 24000.0,
            },
            "runtime_load_context": {
                "days": 120,
                "load_days": 180,
                "source_load_days": 1825,
                "max_cache_age_minutes": max_cache_age_minutes,
                "base_url": "https://fapi.binance.com",
            },
            "event_cadence": {
                "bridge_event_count": 50,
                "add_event_count": 17,
                "remove_event_count": 33,
                "events_per_day": 0.4167,
                "expected_days_per_event": 2.4,
                "median_gap_hours": 24.0,
                "latest_age_to_median_gap": 16.75,
                "wait_state": "latest_signal_age_above_recent_median_gap",
                "add_events_per_day": 0.1417,
                "expected_days_per_add": 7.0588,
                "latest_event_ts": "2026-05-19T10:55:00+00:00",
                "latest_event_age_hours": 402.0,
                "latest_add_ts": "2026-05-19T06:35:00+00:00",
                "latest_add_age_hours": 406.0,
                "median_add_gap_hours": 74.0,
                "latest_add_age_to_median_gap": 5.4,
                "add_wait_state": "latest_add_age_above_recent_median_gap",
            },
            "top_no_trade_reasons": [
                {"reason": "no_trade_MC12_low_confluence", "count": 100},
                {"reason": "no_trade_MC04_no_clear_first_touch", "count": 80},
            ],
            "no_trade_hotspots": {
                "top_no_trade_contexts": {
                    "MC12_low_confluence|long|with_trend|uptrend|normal|score_0-3|edge_0-1|stack_0-1|ext_1.5-2.5|break_0-0.1": 60,
                    "MC04_no_clear_first_touch|long|with_trend|uptrend|normal|score_0-3|edge_0-1|stack_0-1|ext_1.5-2.5|break_0-0.1": 40,
                },
            },
        },
        "collection": {
            "captured_quote_rows": 2,
            "quote_samples": {
                "observed": 40,
                "required": 300,
                "calendar_days": 2,
                "min_calendar_days": 30,
                "distinct_hours": 5,
                "min_distinct_hours": 24,
                "coverage": {
                    "utc_hour_of_day_covered_count": 3,
                    "utc_hour_of_day_covered": ["00", "05", "12"],
                    "utc_hour_of_day_missing": ["01"],
                },
            },
            "paper_fill": {"v6_lifecycle_rows": 0},
            "readiness": {
                "overall_status": "shadow_data_required",
                "max_authorized_stage": "paper",
                "live_order_submission_allowed": False,
                "failed_gates": ["min_shadow_fill_samples"],
                "pending_gates": ["p95_latency_within_limit"],
            },
        },
        "bottleneck_diagnosis": {"paper_missing_shadow_fills": 100},
    }


def _write_hourly_historical_source(path: Path, *, start: datetime, days: int, future_row: bool = False) -> None:
    rows = []
    for day in range(days):
        for hour in range(24):
            ts = start + timedelta(days=day, hours=hour)
            rows.append(
                {
                    "ts": ts.isoformat(),
                    "open_ms": int(ts.timestamp() * 1000),
                    "o": 10000.0,
                    "h": 10100.0,
                    "l": 9900.0,
                    "c": 10050.0,
                    "v": 10.0,
                }
            )
    if future_row:
        future_ts = start + timedelta(days=days + 10)
        rows.append(
            {
                "ts": future_ts.isoformat(),
                "open_ms": int(future_ts.timestamp() * 1000),
                "o": 10000.0,
                "h": 10100.0,
                "l": 9900.0,
                "c": 10050.0,
                "v": 10.0,
            }
        )
    payload = {"symbol": "BTCUSDT", "interval": "1h", "days": days, "rows": rows}
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_lifecycle_summary_source(path: Path) -> None:
    payload = {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "data_status": {
            "5m": {
                "first_ts": "2021-01-01T00:00:00+00:00",
                "last_ts": "2025-12-31T23:55:00+00:00",
            }
        },
        "top": [
            {
                "summary": {
                    "closed": 120,
                    "total_return_pct_1x": 250.0,
                    "max_drawdown_pct_1x": 25.0,
                    "trades_per_year": 24.0,
                    "direction_counts": {"long": 60, "short": 60},
                    "by_year_return_pct": {
                        "2021": 20.0,
                        "2022": -5.0,
                        "2023": 80.0,
                        "2024": 40.0,
                        "2025": 30.0,
                    },
                },
                "sample_trades": [
                    {
                        "direction": "long",
                        "entry_ts": "2021-01-01T00:00:00+00:00",
                        "exit_ts": "2021-01-02T00:00:00+00:00",
                        "entry": 100.0,
                        "exit": 101.0,
                    }
                ],
            }
        ],
        "all_results": [
            {
                "trade_like_events": 500,
                "total_return_pct": -100.0,
                "max_drawdown_pct": 100.0,
                "direction_counts": {"long": 250, "short": 250},
                "by_year_return_pct": {
                    "2021": -100.0,
                    "2022": 0.0,
                    "2023": 0.0,
                    "2024": 0.0,
                    "2025": 0.0,
                },
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_full_safety_controls(path: Path, *, verified_at: datetime) -> None:
    payload = {
        "controls": {
            name: {
                "verified": True,
                "verified_at": verified_at.isoformat(),
                "evidence": f"test evidence for {name}",
            }
            for name in REQUIRED_SAFETY_CONTROLS
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_quote_cadence_preflight_skips_duplicate_utc_hour_when_hour_gate_missing(tmp_path) -> None:
    generated_at = datetime(2026, 1, 2, 7, 30, tzinfo=UTC)
    rows = [
        build_quote_shadow_row(
            order_book=_book(),
            timestamp=generated_at,
            symbol="BTCUSDT",
            strategy_family="market_state_rotation_v6",
            decision_id=f"quote_{idx}",
            side="long",
            order_notional_usdt=100.0,
            latency_ms=50.0,
        )
        for idx in range(2)
    ]
    sample_jsonl = tmp_path / "quote_shadow.jsonl"
    sample_jsonl.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    preflight = evidence._quote_cadence_preflight(
        sample_jsonl=sample_jsonl,
        requested_quote_samples_per_tick=2,
        required_quote_samples=300,
        min_quote_calendar_days=30,
        min_quote_distinct_hours=24,
        symbol="BTCUSDT",
        generated_at=generated_at,
    )

    assert preflight["status"] == "active"
    assert preflight["requested_quote_samples_per_tick"] == 2
    assert preflight["effective_quote_samples_per_tick"] == 0
    assert preflight["decision"] == "skip_duplicate_utc_hour_until_missing_hour_window"
    assert preflight["current_utc_date_already_covered"] is True
    assert preflight["current_utc_hour_already_covered"] is True
    assert preflight["missing_distinct_hours"] == 23


def test_historical_evidence_replay_replaces_quote_calendar_wait_without_future_leakage(tmp_path) -> None:
    source = tmp_path / "BTCUSDT_1h.json"
    start = datetime(2025, 1, 1, tzinfo=UTC)
    _write_hourly_historical_source(source, start=start, days=40, future_row=True)

    replay = evidence._historical_evidence_replay(
        source_path=source,
        generated_at=start + timedelta(days=39, hours=23, minutes=1),
        replay_days=35,
        required_quote_samples=300,
        min_quote_calendar_days=30,
        min_quote_distinct_hours=24,
        symbol="BTCUSDT",
    )

    assert replay["status"] == "passed"
    assert replay["future_leakage_guard"]["status"] == "passed"
    assert replay["future_rows_excluded"] == 1
    assert replay["aggregate_quote_gate"]["quote_samples_passed"] is True
    assert replay["aggregate_quote_gate"]["quote_calendar_days_passed"] is True
    assert replay["aggregate_quote_gate"]["quote_distinct_hours_passed"] is True
    assert replay["rolling_window_confirmation"]["status"] == "passed"
    assert replay["rolling_window_confirmation"]["pass_rate_pct"] == 100.0

    substitution = evidence._historical_gate_substitution(
        collection_progress={
            "quote_missing_samples": 260,
            "quote_missing_calendar_days": 28,
            "quote_missing_distinct_hours": 19,
        },
        readiness_progress={
            "quote_sample_pct": 13.3333,
            "quote_calendar_day_pct": 6.6667,
            "quote_distinct_hour_pct": 20.8333,
            "paper_shadow_fill_pct": 0.0,
            "remaining_work_units": {
                "quote_samples": 260,
                "quote_calendar_days": 28,
                "quote_distinct_hours": 19,
                "paper_shadow_fill_samples": 100,
                "fresh_signal": 1,
            },
            "blocking_gates_ordered": [
                {"gate": "fresh_signal"},
                {"gate": "paper_shadow_fill_samples"},
                {"gate": "quote_calendar_days"},
                {"gate": "quote_distinct_hours"},
                {"gate": "quote_samples"},
            ],
        },
        historical_replay=replay,
    )

    assert substitution["status"] == "quote_wait_replaced_by_historical_walk_forward_proxy"
    assert substitution["realtime_quote_wait_replaced"] is True
    assert substitution["realtime_wait_days_removed"] == 28
    assert substitution["remaining_work_units_after_substitution"]["quote_calendar_days"] == 0
    assert [gate["gate"] for gate in substitution["blocking_gates_after_substitution"]] == [
        "fresh_signal",
        "paper_shadow_fill_samples",
    ]
    policy = substitution["time_substitution_policy"]
    assert policy["research_shadow_quote_calendar_wait"]["substituted"] is True
    assert policy["research_shadow_quote_calendar_wait"]["days_removed"] == 28
    assert policy["research_shadow_quote_sample_hour_wait"]["substituted"] is True
    assert policy["live_launch_current_evidence_wait"]["substitutable"] is False
    assert policy["can_skip_research_quote_calendar_wait"] is True
    assert policy["can_skip_live_current_evidence_wait"] is False


def test_historical_lifecycle_replay_replaces_paper_shadow_fill_proxy(tmp_path) -> None:
    source = tmp_path / "lifecycle_summary.json"
    _write_lifecycle_summary_source(source)

    replay = evidence._historical_lifecycle_replay(
        source_path=source,
        generated_at=datetime(2026, 1, 2, tzinfo=UTC),
        min_shadow_fill_samples=100,
    )

    assert replay["status"] == "passed"
    assert replay["paper_shadow_fill_samples_passed"] is True
    assert replay["proxy_lifecycle_rows"] == 120
    assert replay["future_leakage_guard"]["status"] == "passed"
    assert replay["selected_candidate"]["name"] == "top[0]"
    assert replay["selected_candidate"]["source_ends_before_generated_at"] is True

    quote_source = tmp_path / "BTCUSDT_1h.json"
    start = datetime(2025, 1, 1, tzinfo=UTC)
    _write_hourly_historical_source(quote_source, start=start, days=40)
    quote_replay = evidence._historical_evidence_replay(
        source_path=quote_source,
        generated_at=start + timedelta(days=39, hours=23, minutes=1),
        replay_days=35,
        required_quote_samples=300,
        min_quote_calendar_days=30,
        min_quote_distinct_hours=24,
        symbol="BTCUSDT",
    )
    substitution = evidence._historical_gate_substitution(
        collection_progress={
            "quote_missing_samples": 260,
            "quote_missing_calendar_days": 28,
            "quote_missing_distinct_hours": 19,
        },
        readiness_progress={
            "quote_sample_pct": 13.3333,
            "quote_calendar_day_pct": 6.6667,
            "quote_distinct_hour_pct": 20.8333,
            "paper_shadow_fill_pct": 0.0,
            "remaining_work_units": {
                "quote_samples": 260,
                "quote_calendar_days": 28,
                "quote_distinct_hours": 19,
                "paper_shadow_fill_samples": 100,
                "fresh_signal": 1,
            },
            "blocking_gates_ordered": [
                {"gate": "fresh_signal"},
                {"gate": "paper_shadow_fill_samples"},
                {"gate": "quote_calendar_days"},
                {"gate": "quote_distinct_hours"},
                {"gate": "quote_samples"},
            ],
        },
        historical_replay=quote_replay,
        historical_lifecycle_replay=replay,
    )

    assert substitution["paper_shadow_fill_proxy_replaced"] is True
    assert substitution["remaining_work_units_after_substitution"]["paper_shadow_fill_samples"] == 0
    assert substitution["research_shadow_promotion_readiness_pct_after_substitution"] == 100.0
    assert [gate["gate"] for gate in substitution["blocking_gates_after_substitution"]] == ["fresh_signal"]


def test_next_quote_evidence_window_targets_next_missing_utc_hour() -> None:
    window = evidence._next_quote_evidence_window(
        generated_at=datetime(2026, 1, 2, 7, 30, tzinfo=UTC),
        quote_capture_useful_now=False,
        missing_utc_hours=["01", "08", "22"],
        missing_days=28,
        missing_hours=18,
        missing_samples=200,
    )

    assert window["status"] == "wait"
    assert window["at_utc"] == "2026-01-02T08:00:00+00:00"
    assert window["at_kst"] == "2026-01-02T17:00:00+09:00"
    assert window["valid_until_utc"] == "2026-01-02T09:00:00+00:00"
    assert window["valid_until_kst"] == "2026-01-02T18:00:00+09:00"
    assert window["valid_duration_minutes"] == 60.0
    assert window["wait_minutes"] == 30.0
    assert window["reason"] == "wait_for_next_missing_utc_hour_bucket"
    assert window["window_kind"] == "missing_utc_hour_bucket"
    assert window["urgency"] == "scheduled"
    assert window["missed_window_next_step"] == "rerun_evidence_cycle_to_recompute_next_quote_window"


def test_operator_runbook_promotes_past_scheduled_actions_to_due_now() -> None:
    generated_at = datetime(2026, 1, 2, 8, 30, tzinfo=UTC)
    signal_due = generated_at - timedelta(minutes=5)
    quote_due = generated_at + timedelta(minutes=30)
    plan = evidence._operator_runbook_plan(
        generated_at=generated_at,
        operator_action_plan={
            "top_action": {"action": "wait_for_next_quote_evidence_window"},
            "items": [
                {
                    "priority": 1,
                    "action": "wait_for_next_quote_evidence_window",
                    "stage": "shadow_evidence",
                    "run_now": False,
                    "execute_after_utc": quote_due.isoformat(),
                    "command": "quote-command",
                    "reason": "wait_for_next_missing_utc_hour_bucket",
                    "requires_operator_review": False,
                },
                {
                    "priority": 2,
                    "action": "monitor_fresh_signal_without_quote_capture",
                    "stage": "signal_monitor",
                    "run_now": False,
                    "execute_after_utc": signal_due.isoformat(),
                    "command": "signal-command",
                    "reason": "monitor_due",
                    "requires_operator_review": False,
                },
                {
                    "priority": 3,
                    "action": "optional_bridge_audit_refresh_without_quote_capture",
                    "stage": "paper_readiness_audit",
                    "run_now": True,
                    "command": "bridge-command",
                    "reason": "optional_refresh",
                    "requires_operator_review": False,
                },
                {
                    "priority": 99,
                    "action": "do_not_enable_live_orders",
                    "stage": "live",
                    "run_now": False,
                    "command": None,
                    "reason": "paper_only",
                    "requires_operator_review": True,
                },
            ],
        },
    )

    assert plan["status"] == "run_due_scheduled_action_now"
    assert plan["next_operator_action"]["action"] == "monitor_fresh_signal_without_quote_capture"
    assert plan["next_required_or_scheduled_action"]["action"] == "monitor_fresh_signal_without_quote_capture"
    assert plan["next_optional_action"]["action"] == "optional_bridge_audit_refresh_without_quote_capture"
    assert not plan["required_now_actions"]
    assert [item["action"] for item in plan["optional_now_actions"]] == [
        "optional_bridge_audit_refresh_without_quote_capture"
    ]
    assert "optional_now_action_does_not_replace_required_due_or_scheduled_actions" in plan[
        "coordination_warnings"
    ]
    assert "keep_quote_window_and_signal_monitor_cadences_separate" in plan["coordination_warnings"]
    assert plan["coordination_warning_count"] == 2
    assert [item["action"] for item in plan["due_now_actions"]] == ["monitor_fresh_signal_without_quote_capture"]
    assert [item["action"] for item in plan["scheduled_actions"]] == ["wait_for_next_quote_evidence_window"]
    assert [item["timing"] for item in plan["operator_sequence"][:4]] == [
        "due_now",
        "optional_now",
        "scheduled",
        "blocked",
    ]
    assert plan["required_now_action_count"] == 0
    assert plan["optional_now_action_count"] == 1
    assert plan["due_now_action_count"] == 1
    assert plan["scheduled_action_count"] == 1
    assert plan["no_live_order_sent"] is True


def test_operator_runbook_recovers_expired_quote_window_with_missed_window_command() -> None:
    generated_at = datetime(2026, 1, 2, 8, 30, tzinfo=UTC)
    quote_start = generated_at - timedelta(minutes=90)
    quote_end = generated_at - timedelta(minutes=30)
    signal_due = generated_at + timedelta(minutes=15)
    plan = evidence._operator_runbook_plan(
        generated_at=generated_at,
        operator_action_plan={
            "top_action": {"action": "wait_for_next_quote_evidence_window"},
            "items": [
                {
                    "priority": 1,
                    "action": "wait_for_next_quote_evidence_window",
                    "stage": "shadow_evidence",
                    "run_now": False,
                    "execute_after_utc": quote_start.isoformat(),
                    "execute_before_utc": quote_end.isoformat(),
                    "command": "stale-quote-capture-command",
                    "missed_window_next_step": "rerun_evidence_cycle_to_recompute_next_quote_window",
                    "missed_window_command": "recompute-quote-window-command",
                    "reason": "wait_for_next_missing_utc_hour_bucket",
                    "requires_operator_review": False,
                },
                {
                    "priority": 2,
                    "action": "monitor_fresh_signal_without_quote_capture",
                    "stage": "signal_monitor",
                    "run_now": False,
                    "execute_after_utc": signal_due.isoformat(),
                    "command": "signal-command",
                    "reason": "monitor_future",
                    "requires_operator_review": False,
                },
                {
                    "priority": 99,
                    "action": "do_not_enable_live_orders",
                    "stage": "live",
                    "run_now": False,
                    "command": None,
                    "reason": "paper_only",
                    "requires_operator_review": True,
                },
            ],
        },
    )

    assert plan["status"] == "recover_expired_scheduled_action"
    assert plan["next_operator_action"]["action"] == "wait_for_next_quote_evidence_window"
    assert plan["next_operator_action"]["command"] == "recompute-quote-window-command"
    assert plan["next_operator_action"]["original_command"] == "stale-quote-capture-command"
    assert plan["next_operator_action"]["recovery_action"] == "rerun_evidence_cycle_to_recompute_next_quote_window"
    assert plan["next_operator_action"]["expired_by_minutes"] == 30.0
    assert [item["action"] for item in plan["expired_actions"]] == ["wait_for_next_quote_evidence_window"]
    assert plan["expired_actions"][0]["recovery_command"] == "recompute-quote-window-command"
    assert [item["action"] for item in plan["scheduled_actions"]] == ["monitor_fresh_signal_without_quote_capture"]
    assert "expired_scheduled_window_requires_recompute_before_capture" in plan["coordination_warnings"]
    assert "keep_quote_window_and_signal_monitor_cadences_separate" in plan["coordination_warnings"]
    assert plan["coordination_warning_count"] == 2
    assert [item["timing"] for item in plan["operator_sequence"][:3]] == ["expired", "scheduled", "blocked"]
    assert plan["expired_action_count"] == 1
    assert plan["due_now_action_count"] == 0
    assert plan["no_live_order_sent"] is True


def test_evidence_collection_timeline_builds_quote_signal_day_plan() -> None:
    generated_at = datetime(2026, 1, 2, 8, 30, tzinfo=UTC)
    timeline = evidence._evidence_collection_timeline(
        generated_at=generated_at,
        collection_forecast={
            "recommended_utc_collection_hours": ["09:00Z", "10:00Z", "01:00Z"],
            "minimum_additional_quote_samples": 12,
            "minimum_additional_distinct_hours": 3,
        },
        adaptive_collection_plan={
            "operator_commands": {
                "next_evidence_cycle": (
                    ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                    "--quote-samples-per-tick 2 --report-dir reports/validation/diagnostics/<new_report_dir>"
                )
            },
            "daily_targets": {
                "recommended_utc_collection_hours": ["09:00Z", "10:00Z", "01:00Z"],
                "planned_quote_rows_per_target_hour_cycle": 4,
                "minimum_quote_samples": 8,
                "minimum_new_utc_hour_buckets": 1,
            },
            "next_quote_evidence_window": {
                "status": "wait",
                "at_utc": "2026-01-02T09:00:00+00:00",
                "at_kst": "2026-01-02T18:00:00+09:00",
                "valid_until_utc": "2026-01-02T10:00:00+00:00",
                "valid_until_kst": "2026-01-02T19:00:00+09:00",
                "window_kind": "missing_utc_hour_bucket",
                "reason": "wait_for_next_missing_utc_hour_bucket",
            },
        },
        signal_wait_plan={
            "next_monitor_after_utc": "2026-01-02T08:45:00+00:00",
            "recommended_monitor_interval_minutes": 15,
            "cadence_lag_level": "severe_signal_drought_but_entry_quality_gate_still_blocks_relaxation",
            "command": (
                ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                "--quote-samples-per-tick 0 --report-dir reports/validation/diagnostics/<signal_monitor_report_dir>"
            ),
            "manual_signal_override_allowed": False,
        },
        operator_runbook_plan={
            "optional_now_actions": [
                {
                    "priority": 3,
                    "action": "optional_bridge_audit_refresh_without_quote_capture",
                    "stage": "paper_readiness_audit",
                    "run_now": True,
                    "command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                        "--quote-samples-per-tick 0 --report-dir reports/validation/diagnostics/<bridge_refresh_report_dir>"
                    ),
                    "requires_operator_review": False,
                }
            ],
            "scheduled_actions": [
                {
                    "priority": 1,
                    "action": "wait_for_next_quote_evidence_window",
                    "stage": "shadow_evidence",
                    "run_now": False,
                    "execute_after_utc": "2026-01-02T09:00:00+00:00",
                    "execute_before_utc": "2026-01-02T10:00:00+00:00",
                    "command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                        "--quote-samples-per-tick 2 --report-dir reports/validation/diagnostics/<new_report_dir>"
                    ),
                    "missed_window_command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                        "--quote-samples-per-tick 0 "
                        "--report-dir reports/validation/diagnostics/<missed_quote_window_recompute_report_dir>"
                    ),
                    "requires_operator_review": False,
                },
                {
                    "priority": 2,
                    "action": "monitor_fresh_signal_without_quote_capture",
                    "stage": "signal_monitor",
                    "run_now": False,
                    "execute_after_utc": "2026-01-02T08:45:00+00:00",
                    "command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                        "--quote-samples-per-tick 0 --report-dir reports/validation/diagnostics/<signal_monitor_report_dir>"
                    ),
                    "requires_operator_review": False,
                },
            ],
        },
        market_data_refresh_plan={"fresh_market_data": True},
    )

    assert timeline["status"] == "active_quote_signal_timeline"
    assert timeline["market_data_precondition"] == "fresh"
    assert timeline["signal_monitor"]["run_at_or_after_utc"] == "2026-01-02T08:45:00+00:00"
    assert "<signal_monitor_report_dir>" in timeline["signal_monitor"]["command"]
    assert "<" not in timeline["signal_monitor"]["rendered_command"]
    assert "market_state_rotation_v6_timeline_signal_monitor_20260102_0845Z" in timeline["signal_monitor"][
        "rendered_command"
    ]
    assert timeline["quote_collection_slot_count"] == 3
    assert [slot["run_at_or_after_utc"] for slot in timeline["quote_collection_slots"]] == [
        "2026-01-02T09:00:00+00:00",
        "2026-01-02T10:00:00+00:00",
        "2026-01-03T01:00:00+00:00",
    ]
    assert "<new_report_dir>" in timeline["quote_collection_slots"][0]["command"]
    assert "<missed_quote_window_recompute_report_dir>" in timeline["quote_collection_slots"][0][
        "missed_window_command"
    ]
    assert "<" not in timeline["quote_collection_slots"][0]["rendered_command"]
    assert "<" not in timeline["quote_collection_slots"][0]["rendered_missed_window_command"]
    assert "market_state_rotation_v6_timeline_quote_capture_20260102_0900Z" in timeline[
        "quote_collection_slots"
    ][0]["rendered_command"]
    assert "market_state_rotation_v6_timeline_quote_capture_missed_recompute_20260102_0900Z" in timeline[
        "quote_collection_slots"
    ][0]["rendered_missed_window_command"]
    assert timeline["quote_collection_slots"][0]["suggested_report_dir"].endswith(
        "market_state_rotation_v6_timeline_quote_capture_20260102_0900Z"
    )
    assert timeline["ordered_timeline"][0]["kind"] == "optional_now"
    assert "<" not in timeline["ordered_timeline"][0]["rendered_command"]
    assert timeline["ordered_timeline"][1]["kind"] == "signal_monitor"
    assert "<" not in timeline["ordered_timeline"][1]["rendered_command"]
    assert timeline["next_timeline_event"]["action"] == "optional_bridge_audit_refresh_without_quote_capture"
    assert timeline["next_required_timeline_event"]["action"] == "monitor_fresh_signal_without_quote_capture"
    assert "<" not in timeline["next_required_timeline_event"]["rendered_command"]
    assert [item["kind"] for item in timeline["required_timeline"][:2]] == ["signal_monitor", "quote_collection_slot"]
    assert timeline["command_validation"]["status"] == "ready"
    assert timeline["command_validation"]["issue_count"] == 0
    assert timeline["command_validation"]["unresolved_placeholder_count"] == 0
    assert timeline["command_validation"]["live_order_flag_count"] == 0
    assert timeline["command_validation"]["duplicate_report_dir_count"] == 0
    assert timeline["command_validation"]["command_count"] == len(timeline["command_manifest"])
    assert any(item["command_type"] == "quote_capture" for item in timeline["command_manifest"])
    assert any(item["command_type"] == "missed_quote_window_recompute" for item in timeline["command_manifest"])
    assert timeline["collection_target_forecast"]["status"] == "timeline_covers_daily_collection_targets"
    assert timeline["collection_target_forecast"]["planned_quote_slot_count"] == 3
    assert timeline["collection_target_forecast"]["planned_quote_rows_per_slot"] == 4
    assert timeline["collection_target_forecast"]["estimated_quote_rows_if_all_slots_run"] == 12
    assert timeline["collection_target_forecast"]["minimum_quote_samples_today"] == 8
    assert timeline["collection_target_forecast"]["sample_target_covered"] is True
    assert timeline["collection_target_forecast"]["unique_utc_hour_slots"] == ["01", "09", "10"]
    assert timeline["collection_target_forecast"]["distinct_hour_target_covered"] is True
    assert timeline["collection_target_forecast"]["estimated_remaining_quote_samples_after_timeline"] == 0
    assert timeline["collection_target_forecast"]["estimated_remaining_distinct_hours_after_timeline"] == 0
    assert timeline["collection_target_forecast"]["warning_count"] == 0
    assert timeline["minimum_execution_plan"]["status"] == "minimum_daily_targets_reachable"
    assert timeline["minimum_execution_plan"]["required_quote_slot_count"] == 2
    assert timeline["minimum_execution_plan"]["optional_acceleration_slot_count"] == 1
    assert [slot["run_at_or_after_utc"] for slot in timeline["minimum_execution_plan"]["required_quote_slots"]] == [
        "2026-01-02T09:00:00+00:00",
        "2026-01-02T10:00:00+00:00",
    ]
    assert [slot["run_at_or_after_utc"] for slot in timeline["minimum_execution_plan"]["optional_acceleration_slots"]] == [
        "2026-01-03T01:00:00+00:00"
    ]
    assert timeline["minimum_execution_plan"]["estimated_quote_rows_from_required_slots"] == 8
    assert timeline["minimum_execution_plan"]["required_unique_utc_hours"] == ["09", "10"]
    assert timeline["minimum_execution_plan"]["sample_target_reachable"] is True
    assert timeline["minimum_execution_plan"]["distinct_hour_target_reachable"] is True
    assert timeline["minimum_execution_plan"]["estimated_remaining_quote_samples_after_required_slots"] == 4
    assert timeline["minimum_execution_plan"]["estimated_remaining_distinct_hours_after_required_slots"] == 1
    assert timeline["minimum_execution_plan"]["warning_count"] == 0
    assert timeline["completion_projection"]["status"] == "projected"
    assert timeline["completion_projection"]["minimum_required_slots_daily"]["projected_quote_gate_days"] == 2
    assert timeline["completion_projection"]["full_timeline_daily"]["projected_quote_gate_days"] == 1
    assert timeline["completion_projection"]["days_saved_by_full_timeline_vs_minimum"] == 1
    assert timeline["completion_projection"]["recommendation"] == (
        "run_full_timeline_when_possible_to_pull_forward_quote_gate"
    )
    assert timeline["completion_projection"]["full_timeline_daily"]["dominant_quote_gates"] == [
        "quote_distinct_hours",
        "quote_samples",
    ]
    assert "do_not_enable_live_orders_from_evidence_timeline" in timeline["operator_precautions"]
    assert timeline["no_live_order_sent"] is True


def test_timeline_collection_target_forecast_flags_daily_shortfall() -> None:
    forecast = evidence._timeline_collection_target_forecast(
        collection_forecast={
            "minimum_additional_quote_samples": 20,
            "minimum_additional_distinct_hours": 4,
        },
        adaptive_collection_plan={
            "daily_targets": {
                "planned_quote_rows_per_target_hour_cycle": 2,
                "minimum_quote_samples": 10,
                "minimum_new_utc_hour_buckets": 3,
            }
        },
        quote_slots=[
            {"run_at_or_after_utc": "2026-01-02T09:00:00+00:00"},
            {"run_at_or_after_utc": "2026-01-02T09:30:00+00:00"},
        ],
    )

    assert forecast["status"] == "timeline_below_daily_collection_targets"
    assert forecast["estimated_quote_rows_if_all_slots_run"] == 4
    assert forecast["sample_target_covered"] is False
    assert forecast["sample_shortfall_vs_daily_target"] == 6
    assert forecast["unique_utc_hour_slots"] == ["09"]
    assert forecast["distinct_hour_target_covered"] is False
    assert forecast["distinct_hour_shortfall_vs_daily_target"] == 2
    assert forecast["estimated_remaining_quote_samples_after_timeline"] == 16
    assert forecast["estimated_remaining_distinct_hours_after_timeline"] == 3
    assert set(forecast["warnings"]) == {
        "timeline_quote_slots_below_daily_sample_target",
        "timeline_quote_slots_below_daily_distinct_hour_target",
    }
    assert forecast["no_live_order_sent"] is True


def test_timeline_minimum_execution_plan_flags_unreachable_daily_targets() -> None:
    forecast = evidence._timeline_collection_target_forecast(
        collection_forecast={
            "minimum_additional_quote_samples": 20,
            "minimum_additional_distinct_hours": 4,
        },
        adaptive_collection_plan={
            "daily_targets": {
                "planned_quote_rows_per_target_hour_cycle": 2,
                "minimum_quote_samples": 10,
                "minimum_new_utc_hour_buckets": 3,
            }
        },
        quote_slots=[
            {"run_at_or_after_utc": "2026-01-02T09:00:00+00:00", "run_before_utc": "2026-01-02T10:00:00+00:00"},
            {"run_at_or_after_utc": "2026-01-02T09:30:00+00:00", "run_before_utc": "2026-01-02T10:00:00+00:00"},
        ],
    )

    plan = evidence._timeline_minimum_execution_plan(
        collection_forecast={
            "minimum_additional_quote_samples": 20,
            "minimum_additional_distinct_hours": 4,
        },
        collection_target_forecast=forecast,
        quote_slots=[
            {"run_at_or_after_utc": "2026-01-02T09:00:00+00:00", "run_before_utc": "2026-01-02T10:00:00+00:00"},
            {"run_at_or_after_utc": "2026-01-02T09:30:00+00:00", "run_before_utc": "2026-01-02T10:00:00+00:00"},
        ],
    )

    assert plan["status"] == "minimum_daily_targets_not_reachable"
    assert plan["required_quote_slot_count"] == 2
    assert plan["optional_acceleration_slot_count"] == 0
    assert plan["estimated_quote_rows_from_required_slots"] == 4
    assert plan["required_unique_utc_hours"] == ["09"]
    assert plan["sample_target_reachable"] is False
    assert plan["distinct_hour_target_reachable"] is False
    assert plan["estimated_remaining_quote_samples_after_required_slots"] == 16
    assert plan["estimated_remaining_distinct_hours_after_required_slots"] == 3
    assert set(plan["warnings"]) == {
        "minimum_execution_plan_below_daily_sample_target",
        "minimum_execution_plan_below_daily_distinct_hour_target",
    }
    assert plan["no_live_order_sent"] is True


def test_timeline_completion_projection_identifies_calendar_gate_dominance() -> None:
    projection = evidence._timeline_completion_projection(
        generated_at=datetime(2026, 1, 2, 8, 30, tzinfo=UTC),
        collection_forecast={
            "minimum_additional_quote_samples": 222,
            "minimum_additional_calendar_days": 28,
            "minimum_additional_distinct_hours": 17,
        },
        collection_target_forecast={
            "estimated_quote_rows_if_all_slots_run": 32,
            "unique_utc_hour_slot_count": 8,
        },
        minimum_execution_plan={
            "estimated_quote_rows_from_required_slots": 8,
            "required_unique_utc_hour_count": 2,
        },
    )

    assert projection["status"] == "projected"
    assert projection["minimum_required_slots_daily"]["days_to_quote_sample_gate"] == 28
    assert projection["minimum_required_slots_daily"]["days_to_distinct_hour_gate"] == 9
    assert projection["minimum_required_slots_daily"]["days_to_calendar_day_gate"] == 28
    assert projection["minimum_required_slots_daily"]["projected_quote_gate_days"] == 28
    assert projection["minimum_required_slots_daily"]["projected_quote_gate_date_utc"] == "2026-01-30"
    assert projection["minimum_required_slots_daily"]["dominant_quote_gates"] == [
        "quote_calendar_days",
        "quote_samples",
    ]
    assert projection["full_timeline_daily"]["days_to_quote_sample_gate"] == 7
    assert projection["full_timeline_daily"]["days_to_distinct_hour_gate"] == 3
    assert projection["full_timeline_daily"]["projected_quote_gate_days"] == 28
    assert projection["full_timeline_daily"]["dominant_quote_gates"] == ["quote_calendar_days"]
    assert projection["days_saved_by_full_timeline_vs_minimum"] == 0
    assert projection["recommendation"] == (
        "calendar_gate_dominates_run_minimum_slots_and_use_acceleration_as_buffer"
    )
    assert projection["no_live_order_sent"] is True


def test_timeline_command_validation_flags_unsafe_or_unresolved_commands() -> None:
    manifest = [
        {
            "action": "run_quote_shadow_capture_for_evidence_window",
            "stage": "shadow_evidence",
            "command_type": "quote_capture",
            "report_dir": "reports/validation/diagnostics/dup",
            "rendered_command": (
                ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                "--quote-samples-per-tick 0 --report-dir reports/validation/diagnostics/dup"
            ),
            "placeholders_resolved": True,
            "quote_samples_per_tick": 0,
            "live_order_flags_present": False,
        },
        {
            "action": "monitor_fresh_signal_without_quote_capture",
            "stage": "signal_monitor",
            "command_type": "signal_monitor",
            "report_dir": "reports/validation/diagnostics/dup",
            "rendered_command": (
                ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                "--quote-samples-per-tick 1 --enable-live --report-dir reports/validation/diagnostics/<bad>"
            ),
            "placeholders_resolved": False,
            "quote_samples_per_tick": 1,
            "live_order_flags_present": True,
        },
    ]

    validation = evidence._timeline_command_validation(manifest)

    assert validation["status"] == "review_required"
    assert validation["issue_count"] == 5
    assert validation["duplicate_report_dir_count"] == 1
    assert validation["unresolved_placeholder_count"] == 1
    assert validation["live_order_flag_count"] == 1
    assert {item["issue"] for item in validation["issues"]} == {
        "quote_capture_without_positive_quote_samples",
        "unresolved_placeholder",
        "live_order_flag_present",
        "non_capture_command_must_use_zero_quote_samples",
        "duplicate_report_dir",
    }
    assert validation["no_live_order_sent"] is True


def test_command_has_live_flags_detects_equals_variants_without_false_readiness_match() -> None:
    assert evidence._command_has_live_flags(
        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py --enable-live=true"
    ) is True
    assert evidence._command_has_live_flags(
        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py --submit-live-order=false"
    ) is True
    assert evidence._command_has_live_flags(
        ".venv/bin/python scripts/run_market_state_rotation_v6_live_readiness.py --live-readiness-report report.json"
    ) is False


def test_evidence_cycle_writes_collection_entry_and_drought_bundle(monkeypatch, tmp_path) -> None:
    def fake_collection_cycle(**kwargs):
        report_dir = Path(kwargs["report_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)
        payload = _cycle_report()
        (report_dir / CYCLE_REPORT_NAME).write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(evidence, "run_collection_cycle", fake_collection_cycle)

    report_dir = tmp_path / "evidence"
    report = run_evidence_cycle(
        source_backtest_report_path=tmp_path / "source.json",
        stress_report_path=tmp_path / "stress.json",
        walk_forward_report_path=tmp_path / "walk.json",
        manual_evidence_path=tmp_path / "manual.json",
        sample_jsonl=tmp_path / "sample.jsonl",
        report_dir=report_dir,
    )

    assert report["overall_status"] == "healthy_abstention_waiting_for_quality_signal"
    assert report["no_live_order_sent"] is True
    assert report["decision_state"]["primary_cause"] == "strategy_abstaining_from_low_quality_soft_contexts"
    assert report["decision_state"]["max_authorized_stage"] == "paper"
    assert report["collection_progress"]["quote_missing_samples"] == 260
    assert report["collection_progress"]["quote_missing_calendar_days"] == 28
    assert report["collection_progress"]["quote_missing_distinct_hours"] == 19
    assert report["collection_progress"]["captured_quote_rows_this_cycle"] == 2
    assert report["collection_progress"]["dominant_collection_blocker"] == "quote_calendar_days"
    assert report["quote_cadence_preflight"]["decision"] == "capture_new_utc_date_for_calendar_gate"
    assert report["quote_cadence_preflight"]["effective_quote_samples_per_tick"] == 1
    assert report["collection_forecast"]["minimum_additional_quote_samples"] == 260
    assert report["collection_forecast"]["minimum_additional_calendar_days"] == 28
    assert report["collection_forecast"]["minimum_additional_distinct_hours"] == 19
    assert report["collection_forecast"]["captured_quote_rows_this_cycle"] == 2
    assert report["collection_forecast"]["recommended_min_quote_samples_per_remaining_day"] == 10
    assert report["collection_forecast"]["recommended_min_evidence_cycles_per_remaining_day"] == 5
    assert report["collection_forecast"]["recommended_min_distinct_utc_hours_per_remaining_day"] == 1
    assert report["collection_forecast"]["utc_hour_of_day_covered_count"] == 3
    assert report["collection_forecast"]["utc_hour_of_day_missing"] == ["01"]
    assert report["collection_forecast"]["kst_hour_of_day_missing"] == ["10"]
    assert report["collection_forecast"]["target_next_utc_hour_of_day"] == "01"
    assert report["collection_forecast"]["target_next_kst_hour_of_day"] == "10"
    assert report["collection_forecast"]["recommended_utc_collection_hours"] == ["01:00Z"]
    assert report["collection_forecast"]["recommended_kst_collection_hours"] == ["10:00KST"]
    assert report["collection_forecast"]["assumption"] == (
        "one_or_more_valid_quote_shadow_samples_collected_on_each_new_utc_calendar_day"
    )
    assert report["readiness_progress"]["quote_sample_pct"] == 13.3333
    assert report["readiness_progress"]["quote_calendar_day_pct"] == 6.6667
    assert report["readiness_progress"]["quote_distinct_hour_pct"] == 20.8333
    assert report["readiness_progress"]["quote_hour_of_day_coverage_pct"] == 12.5
    assert report["readiness_progress"]["paper_shadow_fill_pct"] == 0.0
    assert report["readiness_progress"]["fresh_market_data_pct"] == 100.0
    assert report["readiness_progress"]["fresh_signal_pct"] == 0.0
    assert report["readiness_progress"]["quote_evidence_readiness_pct"] == 6.6667
    assert report["readiness_progress"]["shadow_promotion_readiness_pct"] == 0.0
    assert report["readiness_progress"]["paper_apply_readiness_pct"] == 0.0
    assert report["readiness_progress"]["strictest_quote_gate"] == "quote_calendar_days"
    assert report["readiness_progress"]["strictest_deployment_gate"] == "fresh_signal"
    assert report["readiness_progress"]["remaining_work_units"] == {
        "quote_samples": 260,
        "quote_calendar_days": 28,
        "quote_distinct_hours": 19,
        "paper_shadow_fill_samples": 100,
        "execution_parity_samples": 20,
        "execution_parity_contract": 1,
        "market_data_freshness": 0,
        "fresh_signal": 1,
    }
    assert [gate["gate"] for gate in report["readiness_progress"]["blocking_gates_ordered"]] == [
        "fresh_signal",
        "paper_shadow_fill_samples",
        "execution_parity_journal",
        "quote_calendar_days",
        "quote_distinct_hours",
        "quote_samples",
    ]
    assert report["readiness_progress"]["next_unblocked_operator_step"] == "wait_for_fresh_v6_add_or_remove_signal"
    assert report["execution_checklist"]["current_phase"] == "wait_for_fresh_signal_and_continue_shadow_collection"
    assert report["execution_checklist"]["paper_apply_allowed_now"] is False
    assert report["execution_checklist"]["shadow_promotion_ready"] is False
    assert report["execution_checklist"]["live_ready"] is False
    assert report["execution_checklist"]["target_next_kst_hour_of_day"] == "10"
    assert [item["gate"] for item in report["execution_checklist"]["checklist_items"]] == [
        "market_data_freshness",
        "fresh_signal",
        "quote_calendar_days",
        "quote_distinct_hours",
        "quote_samples",
        "paper_shadow_fill_samples",
        "execution_parity_journal",
    ]
    assert report["execution_checklist"]["checklist_items"][0]["status"] == "passed"
    assert report["execution_checklist"]["checklist_items"][1]["status"] == "blocking"
    assert "run_market_state_rotation_v6_evidence_cycle.py" in report["execution_checklist"]["commands"][
        "continue_evidence_cycle"
    ]
    assert report["readiness_trend"]["status"] == "no_prior_evidence_cycles"
    assert report["readiness_trend"]["history_count"] == 0
    assert report["adaptive_collection_plan"]["status"] == "active_collection_plan"
    assert report["adaptive_collection_plan"]["primary_objective"] == (
        "wait_for_fresh_v6_signal_while_collecting_time_diversified_quote_shadow"
    )
    assert report["adaptive_collection_plan"]["useful_to_run_now"] is True
    assert report["adaptive_collection_plan"]["advances_quote_evidence_now"] is True
    assert report["adaptive_collection_plan"]["next_quote_evidence_window"]["status"] == "now"
    assert report["adaptive_collection_plan"]["next_quote_evidence_window"]["wait_minutes"] == 0.0
    assert report["adaptive_collection_plan"]["daily_targets"]["minimum_evidence_cycles_on_target_hours"] == 5
    assert report["adaptive_collection_plan"]["daily_targets"]["planned_quote_rows_per_target_hour_cycle"] == 2
    assert report["adaptive_collection_plan"]["same_utc_hour_repeat_policy"]["allowed"] is False
    assert report["adaptive_collection_plan"]["next_target"] == {
        "utc_hour_of_day": "01",
        "kst_hour_of_day": "10",
        "reason": "first_missing_utc_hour_bucket_after_current_time",
    }
    assert report["adaptive_collection_plan"]["daily_targets"]["minimum_evidence_cycles"] == 5
    assert report["adaptive_collection_plan"]["coverage_directive"][
        "avoid_repeating_covered_hours_until_hour_gate_passes"
    ] is True
    assert report["operator_action_plan"]["status"] == "run_quote_capture_now"
    assert report["operator_action_plan"]["top_action"]["action"] == "run_quote_shadow_capture_now"
    assert report["operator_action_plan"]["top_action"]["run_now"] is True
    assert report["operator_action_plan"]["top_action"]["stage"] == "shadow_evidence"
    assert report["operator_action_plan"]["top_action"]["execution_window"]["status"] == "now"
    assert report["operator_action_plan"]["top_action"]["execution_window"]["window_kind"] in {
        "current_missing_utc_hour_bucket",
        "current_quote_sample_window",
    }
    assert report["operator_action_plan"]["top_action"]["execution_window"]["capture_command"] == report[
        "operator_action_plan"
    ]["top_action"]["command"]
    assert "--quote-samples-per-tick 0" in report["operator_action_plan"]["top_action"]["missed_window_command"]
    assert "--historical-evidence-replay" in report["operator_action_plan"]["top_action"]["missed_window_command"]
    assert "--historical-lifecycle-replay" in report["operator_action_plan"]["top_action"]["missed_window_command"]
    assert report["signal_wait_plan"]["status"] == "blocked_waiting_for_fresh_signal"
    assert report["signal_wait_plan"]["signal_age_minutes"] == 24000.0
    assert report["signal_wait_plan"]["signal_age_hours"] == 400.0
    assert report["signal_wait_plan"]["max_signal_age_minutes"] == 15.0
    assert report["signal_wait_plan"]["signal_stale_by_minutes"] == 23985.0
    assert report["signal_wait_plan"]["expected_days_per_event"] == 2.4
    assert report["signal_wait_plan"]["expected_event_interval_hours"] == 57.6
    assert report["signal_wait_plan"]["median_gap_hours"] == 24.0
    assert report["signal_wait_plan"]["latest_age_to_median_gap"] == 16.75
    assert report["signal_wait_plan"]["event_wait_state"] == "latest_signal_age_above_recent_median_gap"
    assert report["signal_wait_plan"]["bridge_event_count"] == 50
    assert report["signal_wait_plan"]["remove_event_count"] == 33
    assert report["signal_wait_plan"]["latest_add_age_to_median_gap"] == 5.4
    assert report["signal_wait_plan"]["cadence_lag_level"] == (
        "severe_signal_drought_but_entry_quality_gate_still_blocks_relaxation"
    )
    assert report["signal_wait_plan"]["signal_absence_primary_cause"] == (
        "severe_signal_drought_but_quality_gate_blocks_forced_entry"
    )
    assert report["signal_wait_plan"]["signal_pipeline_issue_suspected"] is False
    assert report["signal_wait_plan"]["signal_absence_diagnosis"]["class"] == (
        "quality_gate_protected_signal_drought"
    )
    assert report["signal_wait_plan"]["signal_absence_diagnosis"]["force_signal_allowed"] is False
    assert report["signal_wait_plan"]["signal_absence_diagnosis"]["runtime_filter_relaxation_allowed"] is False
    assert report["signal_wait_plan"]["recommended_monitor_interval_minutes"] == 15
    assert "--max-signal-age-minutes 15" in report["signal_wait_plan"]["command"]
    assert "--refresh-market-data-before-run" in report["signal_wait_plan"]["command"]
    assert "--historical-evidence-replay" in report["signal_wait_plan"]["command"]
    assert "--historical-lifecycle-replay" in report["signal_wait_plan"]["command"]
    assert "<signal_monitor_report_dir>" not in report["signal_wait_plan"]["command"]
    assert "market_state_rotation_v6_signal_monitor_" in report["signal_wait_plan"]["command"]
    signal_monitor_items = [
        item
        for item in report["operator_action_plan"]["items"]
        if item["action"] == "monitor_fresh_signal_without_quote_capture"
    ]
    assert len(signal_monitor_items) == 1
    assert signal_monitor_items[0]["cadence_lag_level"] == report["signal_wait_plan"]["cadence_lag_level"]
    assert signal_monitor_items[0]["manual_signal_override_allowed"] is False
    assert report["operator_runbook_plan"]["status"] == "run_required_action_now"
    assert report["operator_runbook_plan"]["next_operator_action"]["action"] == "run_quote_shadow_capture_now"
    assert report["operator_runbook_plan"]["coordination_rule"] == (
        "run_quote_capture_first_then_monitor_signal_on_its_due_cadence"
    )
    assert [item["action"] for item in report["operator_runbook_plan"]["run_now_actions"]] == [
        "run_quote_shadow_capture_now"
    ]
    assert [item["action"] for item in report["operator_runbook_plan"]["scheduled_actions"]] == [
        "monitor_fresh_signal_without_quote_capture"
    ]
    assert any(item["action"] == "do_not_enable_live_orders" for item in report["operator_runbook_plan"]["guarded_actions"])
    assert report["operator_runbook_plan"]["no_live_order_sent"] is True
    assert report["operator_action_plan"]["live_order_submission_allowed"] is False
    assert "do_not_enable_live_orders_from_collection_plan" in report["adaptive_collection_plan"]["non_negotiables"]
    assert report["paper_bridge_apply_gate"]["status"] == "blocked_waiting_for_fresh_signal"
    assert report["paper_bridge_apply_gate"]["can_request_paper_apply_now"] is False
    assert report["collection_progress"]["execution_parity_journal_rows"] == 0
    assert report["collection_progress"]["execution_parity_missing_samples"] == 20
    assert report["execution_parity_collection_plan"]["status"] == "waiting_for_fresh_signal"
    assert report["execution_parity_collection_plan"]["missing_samples"] == 20
    assert report["execution_parity_collection_plan"]["estimated_future_paper_apply_events_needed"] == 20
    assert report["execution_parity_collection_plan"]["estimated_events_needed_after_current_creditable_apply"] == 20
    assert report["execution_parity_collection_plan"]["will_credit_current_apply_after_operator_review"] is False
    assert report["execution_parity_collection_plan"]["accepted_actions"] == ["add", "remove"]
    assert report["execution_parity_collection_plan"]["currently_creditable_actions"] == []
    assert report["execution_parity_collection_plan"]["backtest_substitution_allowed"] is False
    assert report["execution_parity_collection_plan"]["no_live_order_sent"] is True
    assert report["execution_parity_journal"]["collection_plan"]["status"] == "collecting_samples"
    assert report["execution_parity_journal"]["collection_plan"]["estimated_future_paper_apply_events_needed"] == 20
    assert report["execution_parity_journal"]["collection_plan"]["accepted_actions"] == ["add", "remove"]
    assert report["execution_parity_journal"]["contract_summary"]["blockers"] == [
        "execution_journal_missing",
        "insufficient_execution_sample_count",
    ]
    assert report["entry_quality"]["eligible_probe_context_count"] == 0
    assert report["entry_quality"]["mc04_broad_relaxation_rejected"] is True
    assert report["entry_quality"]["dominant_primary_issue"] == (
        "soft_confluence_filters_are_dominating_current_no_trade_distribution"
    )
    assert report["entry_quality"]["reason_class_counts"]["soft_candidate"] == 180
    assert report["entry_quality"]["top_no_trade_reasons"][0]["reason"] == "no_trade_MC12_low_confluence"
    assert report["entry_quality"]["dominant_no_trade_context"]["reason"] == "MC12_low_confluence"
    assert report["entry_quality"]["probe_quality_reason_counts"]["score_too_low"] == 100
    assert report["entry_quality"]["eligible_probe_contexts"] == []
    assert report["entry_quality"]["top_rejected_soft_contexts"][0]["reason"] == (
        "MC12_low_confluence"
    )
    assert report["entry_quality"]["top_rejected_soft_contexts"][0]["count"] == 60
    assert report["entry_quality"]["entry_filter_context_distribution_scope"][
        "source_field"
    ] == "top_no_trade_contexts"
    assert report["entry_quality"]["operator_interpretation"]["status"] == (
        "wait_for_new_walk_forward_evidence_before_relaxing_soft_contexts"
    )
    assert report["entry_quality"]["safe_experiment_backlog"][0]["name"] == (
        "quality_gated_mc12_near_miss_micro_probe"
    )
    assert report["entry_quality"]["entry_filter_resolution_plan"]["status"] == (
        "blocked_no_quality_probe_context"
    )
    assert report["entry_quality"]["entry_filter_resolution_plan"][
        "dominant_probe_quality_blocker"
    ] == "score_too_low"
    assert report["fresh_signal_resolution_plan"]["status"] == "no_safe_runtime_fix_available"
    assert report["fresh_signal_resolution_plan"]["operator_fixable_now"] is False
    assert report["fresh_signal_resolution_plan"]["mc12_low_confluence_count"] == 100
    assert report["fresh_signal_resolution_plan"]["mc04_no_clear_first_touch_count"] == 80
    assert report["fresh_signal_resolution_plan"]["root_causes"][0]["cause"] == (
        "current_signal_missing_or_stale"
    )
    assert "force_current_fresh_signal" in report["fresh_signal_resolution_plan"]["unsafe_shortcuts"]
    assert (
        report["entry_quality"]["fresh_signal_resolution_plan"]
        == report["fresh_signal_resolution_plan"]
    )
    assert report["fresh_signal_resolution_plan"]["entry_filter_resolution_plan"][
        "dominant_probe_quality_blocker"
    ] == "score_too_low"
    assert "do_not_relax_current_low_quality_soft_contexts" in report["next_actions"]
    assert "continue_quote_shadow_collection_until_samples_calendar_days_and_distinct_hours_pass" in report["next_actions"]
    assert "run_quote_shadow_capture_on_current_valid_quote_window" in report["next_actions"]
    assert "run_evidence_cycle_once_per_new_utc_day_until_quote_calendar_floor_passes" in report["next_actions"]
    assert "spread_quote_shadow_collection_across_missing_utc_hours" in report["next_actions"]
    assert "monitor_fresh_v6_signal_on_signal_wait_plan_cadence_without_forcing_entry" in report["next_actions"]
    assert "do_not_force_signal_or_relax_low_quality_filters_despite_extended_drought" in report["next_actions"]
    assert (report_dir / EVIDENCE_REPORT_NAME).exists()
    assert (report_dir / "entry_filter_sparsity_audit" / "market_state_rotation_v6_entry_filter_sparsity_audit.json").exists()
    assert (report_dir / "signal_drought_audit" / "market_state_rotation_v6_signal_drought_audit.json").exists()
    assert (report_dir / "execution_parity_journal" / "market_state_rotation_v6_execution_parity_journal.json").exists()
    assert (report_dir / "execution_parity_journal" / "market_state_rotation_v6_execution_parity_contract.json").exists()


def test_evidence_cycle_reports_blocked_mc12_probe_full_walk_forward_gate(monkeypatch, tmp_path) -> None:
    def fake_collection_cycle(**kwargs):
        report_dir = Path(kwargs["report_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)
        payload = _cycle_report()
        payload["bridge"]["no_trade_hotspots"]["no_trade_contexts"] = {
            "MC12_low_confluence|long|with_trend|uptrend|normal|score_3-5|edge_2-4|stack_2-4|ext_0.75-1.5|break_0-0.1": 8,
            "MC12_low_confluence|short|with_trend|downtrend|normal|score_3-5|edge_2-4|stack_2-4|ext_0.75-1.5|break_0-0.1": 7,
        }
        (report_dir / CYCLE_REPORT_NAME).write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(evidence, "run_collection_cycle", fake_collection_cycle)
    gate_report = tmp_path / "full_wfo_gate.json"
    gate_report.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-09T10:27:06+00:00",
                "overall_status": "blocked",
                "promotion_type": "blocked",
                "decision": "do_not_promote_to_paper_or_live",
                "failed_checks": [
                    "compounded_return_degradation",
                    "drawdown_worsening",
                    "positive_fold_count_degradation",
                ],
                "deltas": {
                    "compounded_oos_return_pct": -23270.146,
                    "max_fold_drawdown_pct": 15.7602,
                    "positive_fold_count": -3,
                },
                "activity_regression_summary": {
                    "signal_sparsity_fix_failed": True,
                    "probe_activity_regressed": True,
                    "trade_like_activity_regressed": True,
                    "probe_add_delta": -19,
                    "trade_like_events_delta": -3,
                    "diagnostic_labels": [
                        "candidate_reduces_probe_activity_instead_of_solving_signal_sparsity"
                    ],
                },
                "fold_delta_summary": {
                    "matched_fold_count": 16,
                    "return_degraded_fold_count": 16,
                    "positive_fold_lost_count": 3,
                    "drawdown_gate_violation_fold_ids": ["1", "4", "12"],
                    "worst_return_degradation_fold": {"fold": "4", "return_delta_pct": -44.4624},
                },
                "failure_details": {
                    "compounded_return_degradation": {
                        "worst_fold": {"fold": "4", "return_delta_pct": -44.4624}
                    }
                },
                "root_cause_hints": [
                    "candidate_underperforms_baseline_in_every_matched_oos_fold",
                    "candidate_turns_previously_positive_oos_folds_negative",
                ],
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    report = run_evidence_cycle(
        source_backtest_report_path=tmp_path / "source.json",
        stress_report_path=tmp_path / "stress.json",
        walk_forward_report_path=tmp_path / "walk.json",
        manual_evidence_path=tmp_path / "manual.json",
        sample_jsonl=tmp_path / "sample.jsonl",
        report_dir=tmp_path / "evidence",
        entry_probe_full_walk_forward_gate_report_path=gate_report,
    )

    probe_validation = report["entry_quality"]["entry_probe_validation"]
    assert report["entry_quality"]["eligible_probe_context_count"] == 15
    assert len(report["entry_quality"]["eligible_probe_contexts"]) == 2
    assert report["entry_quality"]["eligible_probe_contexts"][0]["reason"] == (
        "MC12_low_confluence"
    )
    assert report["entry_quality"]["eligible_probe_contexts"][0]["count"] == 8
    assert report["entry_quality"]["entry_filter_context_distribution_scope"][
        "uses_full_bucketed_context_distribution"
    ] is True
    assert probe_validation["status"] == "blocked_full_walk_forward_gate"
    assert probe_validation["paper_or_live_promotion_allowed"] is False
    assert probe_validation["runtime_filter_change_allowed"] is False
    assert probe_validation["failed_checks"] == [
        "compounded_return_degradation",
        "drawdown_worsening",
        "positive_fold_count_degradation",
    ]
    assert probe_validation["fold_delta_summary"]["return_degraded_fold_count"] == 16
    assert probe_validation["activity_regression_summary"]["signal_sparsity_fix_failed"] is True
    assert probe_validation["failure_details"]["compounded_return_degradation"]["worst_fold"]["fold"] == "4"
    assert (
        "candidate_underperforms_baseline_in_every_matched_oos_fold"
        in probe_validation["root_cause_hints"]
    )
    resolution = report["fresh_signal_resolution_plan"]
    assert resolution["status"] == "offline_probe_candidate_failed_full_walk_forward_gate"
    assert resolution["operator_fixable_now"] is False
    assert resolution["entry_probe_validation"]["status"] == "blocked_full_walk_forward_gate"
    assert any(
        item["cause"] == "quality_gated_mc12_probe_failed_full_walk_forward_gate"
        for item in resolution["root_causes"]
    )
    full_wfo_cause = next(
        item
        for item in resolution["root_causes"]
        if item["cause"] == "quality_gated_mc12_probe_failed_full_walk_forward_gate"
    )
    assert full_wfo_cause["evidence"]["fold_delta_summary"]["worst_return_degradation_fold"]["fold"] == "4"
    assert full_wfo_cause["evidence"]["activity_regression_summary"]["probe_add_delta"] == -19
    assert "candidate_turns_previously_positive_oos_folds_negative" in full_wfo_cause["evidence"][
        "root_cause_hints"
    ]
    assert "do_not_promote_quality_gated_mc12_probe_after_failed_full_walk_forward_gate" in resolution[
        "safe_actions"
    ]
    assert report["report_paths"]["entry_probe_full_walk_forward_gate"] == str(gate_report)
    assert report["no_live_order_sent"] is True


def test_entry_probe_promotion_gate_accepts_paper_candidate_with_stale_blockers() -> None:
    probe_validation = evidence._entry_probe_validation_state(
        {
            "generated_at": "2026-06-09T15:09:41+00:00",
            "overall_status": "candidate_promoted",
            "active_full_walk_forward_candidate_count": 0,
            "active_full_walk_forward_candidate_names": [],
            "paper_evidence_candidate_count": 1,
            "paper_evidence_candidate_names": ["seeded_mc12_downtrend_react200_mdd20"],
            "downstream_blocked_candidate_names": [
                "quality_gated_mc12_near_miss_micro_probe"
            ],
            "resolution_plan": {
                "status": "full_walk_forward_candidate_passed_paper_evidence_collection_only",
                "safe_next_step": (
                    "collect_paper_evidence_only_after_fresh_signal_and_operator_review"
                ),
                "paper_evidence_collection_allowed": True,
                "paper_evidence_candidate_count": 1,
                "paper_evidence_candidate_names": [
                    "seeded_mc12_downtrend_react200_mdd20"
                ],
            },
            "downstream_full_walk_forward_gates": [
                {
                    "status": "blocked_full_walk_forward_gate",
                    "candidate_name": "quality_gated_mc12_near_miss_micro_probe",
                    "overall_status": "blocked",
                    "decision": "do_not_promote_to_paper_or_live",
                    "failed_checks": ["drawdown_worsening"],
                },
                {
                    "status": "paper_evidence_collection_candidate_available",
                    "candidate_name": "seeded_mc12_downtrend_react200_mdd20",
                    "overall_status": "return_improving",
                    "decision": "eligible_for_paper_evidence_collection_only",
                    "failed_checks": [],
                    "deltas": {
                        "compounded_oos_return_pct": 723.1,
                        "max_fold_drawdown_pct": -1.19,
                    },
                    "activity_regression_summary": {
                        "signal_sparsity_fix_failed": False,
                        "probe_add_delta": 17,
                        "trade_like_events_delta": 206,
                    },
                },
            ],
            "no_live_order_sent": True,
        },
        input_report="promotion_gate.json",
    )

    assert probe_validation["status"] == "paper_evidence_collection_candidate_available"
    assert probe_validation["paper_evidence_collection_allowed"] is True
    assert probe_validation["paper_evidence_candidate_count"] == 1
    assert probe_validation["paper_evidence_candidate_names"] == [
        "seeded_mc12_downtrend_react200_mdd20"
    ]
    assert probe_validation["active_full_walk_forward_candidate_count"] == 0
    assert probe_validation["downstream_blocked_candidate_names"] == [
        "quality_gated_mc12_near_miss_micro_probe"
    ]
    assert probe_validation["safe_next_step"] == (
        "collect_paper_evidence_only_after_fresh_signal_and_operator_review"
    )
    assert probe_validation["primary_downstream_failure"] is None
    assert probe_validation["no_live_order_sent"] is True


def test_evidence_cycle_reports_promotion_gate_when_all_mc12_probe_candidates_block(monkeypatch, tmp_path) -> None:
    def fake_collection_cycle(**kwargs):
        report_dir = Path(kwargs["report_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)
        payload = _cycle_report()
        payload["bridge"]["no_trade_hotspots"]["no_trade_contexts"] = {
            "MC12_low_confluence|long|with_trend|uptrend|normal|score_3-5|edge_2-4|stack_2-4|ext_0.75-1.5|break_0-0.1": 8,
            "MC12_low_confluence|short|with_trend|downtrend|normal|score_3-5|edge_2-4|stack_2-4|ext_0.75-1.5|break_0-0.1": 7,
        }
        (report_dir / CYCLE_REPORT_NAME).write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(evidence, "run_collection_cycle", fake_collection_cycle)
    gate_report = tmp_path / "near_miss_promotion_gate.json"
    gate_report.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-09T11:32:20+00:00",
                "overall_status": "full_walk_forward_candidate_blocked",
                "candidate_count": 18,
                "promoted_candidate_count": 4,
                "active_full_walk_forward_candidate_count": 0,
                "active_full_walk_forward_candidate_names": [],
                "downstream_blocked_candidate_names": [
                    "quality_gated_mc12_near_miss_micro_probe",
                    "quality_gated_mc12_score5_edge2_stack2_ext10_cooldown144",
                ],
                "resolution_plan": {
                    "status": "blocked_by_full_walk_forward_gate",
                    "safe_next_step": "inspect_failed_full_walk_forward_gate_before_any_new_near_miss_recipe",
                },
                "downstream_activity_inversion_summary": {
                    "available": True,
                    "candidate_count": 2,
                    "candidate_names": [
                        "quality_gated_mc12_near_miss_micro_probe",
                        "quality_gated_mc12_score5_edge2_stack2_ext10_cooldown144",
                    ],
                    "diagnostic_label": (
                        "short_window_smoke_activity_increase_inverts_to_full_wfo_activity_regression"
                    ),
                },
                "next_candidate_design_contract": {
                    "status": "required_before_next_near_miss_family",
                    "reason": "current_short_window_activity_gains_do_not_survive_full_walk_forward",
                    "minimum_full_walk_forward_requirements": {
                        "probe_add_delta_min": 0,
                        "trade_like_events_delta_min": 0,
                        "activity_inversion_allowed": False,
                    },
                    "required_validation_sequence": [
                        "full_walk_forward_gate_must_run_with_require_nonregressing_activity"
                    ],
                    "runtime_filter_change_allowed": False,
                    "paper_or_live_promotion_allowed": False,
                    "no_live_order_sent": True,
                },
                "downstream_full_walk_forward_gates": [
                    {
                        "status": "blocked_full_walk_forward_gate",
                        "candidate_name": "quality_gated_mc12_near_miss_micro_probe",
                        "overall_status": "blocked",
                        "decision": "do_not_promote_to_paper_or_live",
                        "failed_checks": ["compounded_return_degradation"],
                        "deltas": {"compounded_oos_return_pct": -22454.192},
                        "activity_regression_summary": {
                            "signal_sparsity_fix_failed": True,
                            "probe_activity_regressed": True,
                            "trade_like_activity_regressed": True,
                            "probe_add_delta": -19,
                            "probe_add_delta_pct": -15.0794,
                            "trade_like_events_delta": -3,
                            "trade_like_events_delta_pct": -1.0067,
                            "diagnostic_labels": [
                                "candidate_reduces_probe_activity_instead_of_solving_signal_sparsity"
                            ],
                        },
                        "fold_delta_summary": {
                            "return_degraded_fold_count": 16,
                            "positive_fold_lost_count": 3,
                            "drawdown_gate_violation_fold_ids": ["1", "4", "12"],
                        },
                        "failure_details": {
                            "compounded_return_degradation": {
                                "worst_fold": {"fold": "4", "return_delta_pct": -44.4624}
                            }
                        },
                        "root_cause_hints": [
                            "candidate_underperforms_baseline_in_every_matched_oos_fold"
                        ],
                    },
                    {
                        "status": "blocked_full_walk_forward_gate",
                        "candidate_name": "quality_gated_mc12_score5_edge2_stack2_ext10_cooldown144",
                        "overall_status": "blocked",
                        "decision": "do_not_promote_to_paper_or_live",
                        "failed_checks": ["drawdown_worsening", "positive_fold_count_degradation"],
                        "deltas": {"compounded_oos_return_pct": -22607.9546},
                        "activity_regression_summary": {
                            "signal_sparsity_fix_failed": True,
                            "probe_activity_regressed": True,
                            "trade_like_activity_regressed": True,
                            "probe_add_delta": -92,
                            "probe_add_delta_pct": -73.0159,
                            "trade_like_events_delta": -75,
                            "trade_like_events_delta_pct": -25.1678,
                            "diagnostic_labels": [
                                "candidate_reduces_probe_activity_instead_of_solving_signal_sparsity",
                                "candidate_reduces_total_trade_like_events",
                            ],
                        },
                        "fold_delta_summary": {
                            "return_degraded_fold_count": 15,
                            "positive_fold_lost_count": 3,
                            "drawdown_gate_violation_fold_ids": ["1", "2", "4", "12"],
                        },
                        "root_cause_hints": [
                            "candidate_turns_previously_positive_oos_folds_negative"
                        ],
                    },
                ],
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    report = run_evidence_cycle(
        source_backtest_report_path=tmp_path / "source.json",
        stress_report_path=tmp_path / "stress.json",
        walk_forward_report_path=tmp_path / "walk.json",
        manual_evidence_path=tmp_path / "manual.json",
        sample_jsonl=tmp_path / "sample.jsonl",
        report_dir=tmp_path / "evidence",
        entry_probe_full_walk_forward_gate_report_path=gate_report,
    )

    probe_validation = report["entry_quality"]["entry_probe_validation"]
    assert probe_validation["status"] == "blocked_full_walk_forward_gate"
    assert probe_validation["promotion_gate_available"] is True
    assert probe_validation["active_full_walk_forward_candidate_count"] == 0
    assert probe_validation["downstream_blocked_candidate_names"] == [
        "quality_gated_mc12_near_miss_micro_probe",
        "quality_gated_mc12_score5_edge2_stack2_ext10_cooldown144",
    ]
    assert probe_validation["failed_checks"] == [
        "compounded_return_degradation",
        "drawdown_worsening",
        "positive_fold_count_degradation",
    ]
    assert probe_validation["fold_delta_summary"]["blocked_candidate_count"] == 2
    assert probe_validation["activity_regression_summary"]["signal_sparsity_fix_failed_candidate_count"] == 2
    assert probe_validation["activity_regression_summary"]["signal_sparsity_fix_failed_candidate_names"] == [
        "quality_gated_mc12_near_miss_micro_probe",
        "quality_gated_mc12_score5_edge2_stack2_ext10_cooldown144",
    ]
    assert (
        "candidate_reduces_probe_activity_instead_of_solving_signal_sparsity"
        in probe_validation["activity_regression_summary"]["diagnostic_labels"]
    )
    assert probe_validation["activity_inversion_summary"]["available"] is True
    assert probe_validation["next_candidate_design_contract"]["status"] == (
        "required_before_next_near_miss_family"
    )
    assert probe_validation["next_candidate_design_contract"]["minimum_full_walk_forward_requirements"][
        "activity_inversion_allowed"
    ] is False
    assert probe_validation["next_candidate_design_contract"]["minimum_full_walk_forward_requirements"][
        "trade_like_events_delta_min"
    ] == 1
    assert probe_validation["next_candidate_design_contract"]["minimum_full_walk_forward_requirements"][
        "trade_like_activity_increase_required"
    ] is True
    assert probe_validation["next_candidate_design_contract"]["minimum_full_walk_forward_requirements"][
        "signal_sparsity_fix_requires_trade_like_events_increase"
    ] is True
    assert probe_validation["primary_downstream_failure"] == (
        "short_window_activity_inversion_and_full_wfo_activity_regression"
    )
    assert probe_validation["safe_next_step"] == (
        "abandon_activity_regressing_near_miss_family_design_non_regressing_signal_candidate_or_wait_native_signal"
    )
    assert (
        probe_validation["fold_delta_summary"]["worst_compounded_return_degradation_candidate"][
            "candidate_name"
        ]
        == "quality_gated_mc12_score5_edge2_stack2_ext10_cooldown144"
    )
    assert report["entry_quality"]["operator_interpretation"]["status"] == (
        "offline_probe_candidates_blocked_by_full_walk_forward_gate"
    )
    resolution = report["fresh_signal_resolution_plan"]
    assert report["overall_status"] == "quality_gated_probe_blocked_by_full_walk_forward"
    assert report["decision_state"]["primary_cause"] == (
        "fresh_signal_missing_and_quality_gated_mc12_probe_failed_full_walk_forward_gate"
    )
    assert resolution["status"] == "offline_probe_candidate_failed_full_walk_forward_gate"
    assert resolution["entry_probe_validation"]["active_full_walk_forward_candidate_count"] == 0
    assert (
        resolution["entry_probe_validation"]["activity_regression_summary"][
            "signal_sparsity_fix_failed_candidate_count"
        ]
        == 2
    )
    assert any(
        item["cause"] == "quality_gated_mc12_probe_failed_full_walk_forward_gate"
        for item in resolution["root_causes"]
    )
    assert report["no_live_order_sent"] is True


def test_evidence_cycle_attaches_historical_replay_gate_substitution(monkeypatch, tmp_path) -> None:
    def fake_collection_cycle(**kwargs):
        report_dir = Path(kwargs["report_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)
        payload = _cycle_report()
        (report_dir / CYCLE_REPORT_NAME).write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(evidence, "run_collection_cycle", fake_collection_cycle)
    source = tmp_path / "BTCUSDT_1h.json"
    start = datetime(2025, 1, 1, tzinfo=UTC)
    _write_hourly_historical_source(source, start=start, days=40)
    lifecycle_source = tmp_path / "lifecycle_summary.json"
    _write_lifecycle_summary_source(lifecycle_source)

    report_dir = tmp_path / "evidence"
    report = run_evidence_cycle(
        source_backtest_report_path=tmp_path / "source.json",
        stress_report_path=tmp_path / "stress.json",
        walk_forward_report_path=tmp_path / "walk.json",
        manual_evidence_path=tmp_path / "manual.json",
        sample_jsonl=tmp_path / "sample.jsonl",
        report_dir=report_dir,
        historical_evidence_replay=True,
        historical_replay_source_path=source,
        historical_replay_days=35,
        historical_lifecycle_replay=True,
        historical_lifecycle_source_path=lifecycle_source,
    )

    assert report["historical_evidence_replay"]["status"] == "passed"
    assert report["historical_lifecycle_replay"]["status"] == "passed"
    assert report["historical_gate_substitution"]["realtime_quote_wait_replaced"] is True
    assert report["historical_gate_substitution"]["paper_shadow_fill_proxy_replaced"] is True
    assert report["historical_gate_substitution"]["realtime_wait_days_removed"] == 28
    assert report["historical_gate_substitution"]["strictest_deployment_gate_after_substitution"] == "fresh_signal"
    assert report["launch_readiness"]["status"] == "research_ready_waiting_for_fresh_signal"
    assert report["launch_readiness"]["research_ready"] is True
    assert report["launch_readiness"]["shadow_ready"] is True
    assert report["launch_readiness"]["paper_operational_ready"] is False
    paper_only = report["launch_readiness"]["paper_only_rehearsal"]
    assert paper_only["status"] == "armed_waiting_for_fresh_signal"
    assert paper_only["system_ready"] is True
    assert paper_only["armed"] is True
    assert paper_only["current_rehearsal_available"] is False
    assert paper_only["first_rehearsal_event_completed"] is False
    assert paper_only["max_substitution_status"] == "max_substitution_complete_realtime_gate_remaining"
    assert paper_only["max_substitution_ready"] is True
    assert paper_only["unresolved_proxy_gates"] == []
    assert paper_only["non_substitutable_remaining_gates"] == [
        "current_fresh_signal",
        "first_real_paper_lifecycle_row",
    ]
    assert "historical_quote_replay" in paper_only["substituted_or_prevalidated_gates"]
    assert "historical_lifecycle_proxy" in paper_only["substituted_or_prevalidated_gates"]
    assert "paper_bridge_command_contract" in paper_only["substituted_or_prevalidated_gates"]
    assert "pre_apply_backup_contract" in paper_only["substituted_or_prevalidated_gates"]
    assert paper_only["live_order_submission_allowed"] is False
    assert "current_fresh_signal" in paper_only["remaining_gates"]
    assert "tiny_canary_evidence_ready" in paper_only["not_required_for_paper_only_goal"]
    assert report["launch_readiness"]["tiny_canary_evidence_ready"] is False
    assert report["launch_readiness"]["tiny_canary_order_submission_allowed"] is False
    assert report["launch_readiness"]["next_blocker"]["gate"] == "current_fresh_signal"
    assert report["launch_readiness"]["paper_bridge_handoff"]["status"] == "blocked_waiting_for_fresh_signal"
    assert report["launch_readiness"]["paper_bridge_handoff"]["apply_allowed_now"] is False
    assert report["launch_readiness"]["paper_bridge_handoff"]["requires_verified_pre_apply_backup"] is True
    resolution = report["launch_readiness"]["resolution_matrix"]
    assert resolution["status"] == "substitution_exhausted_realtime_gates_remaining"
    assert resolution["backtest_substitution_exhausted"] is True
    assert resolution["unresolved_backtest_substitutable_gates"] == []
    assert resolution["research_proxy_resolved_gates"] == [
        "research_historical_quote_replay",
        "research_historical_lifecycle_proxy",
        "real_paper_lifecycle_rows",
        "real_microstructure_execution_evidence",
    ]
    assert "current_fresh_signal" in resolution["non_substitutable_remaining_gates"]
    assert "real_paper_lifecycle_rows" in resolution["non_substitutable_remaining_gates"]
    assert "shadow_runtime_24h_observed" in resolution["non_substitutable_remaining_gates"]
    assert "real_microstructure_execution_evidence" not in resolution["no_live_actionable_remaining_gates"]
    assert "real_microstructure_execution_evidence" in resolution["no_live_progressable_remaining_gates"]
    assert "shadow_runtime_24h_observed" not in resolution["no_live_actionable_remaining_gates"]
    assert "shadow_runtime_24h_observed" in resolution["no_live_progressable_remaining_gates"]
    assert "do_not_count_historical_proxy_as_current_fresh_signal" in report["launch_readiness"]["non_negotiables"]
    safety = report["launch_safety_controls"]
    assert safety["overall_status"] == "INCOMPLETE"
    assert safety["verified_count"] == 0
    safety_gate = next(item for item in report["launch_readiness"]["stage_gates"] if item["gate"] == "order_safety_controls_verified")
    assert safety_gate["passed"] is False
    assert safety_gate["blocker"] == "order_safety_controls_missing_or_incomplete"
    assert "do_not_open_tiny_canary_without_complete_order_safety_controls" in report["launch_readiness"]["non_negotiables"]
    assert (report_dir / "historical_evidence_replay.json").exists()
    assert (report_dir / "historical_lifecycle_replay.json").exists()
    assert (report_dir / "historical_gate_substitution.json").exists()
    assert (report_dir / "launch_safety_controls.json").exists()
    assert (report_dir / "launch_readiness.json").exists()
    markdown = (report_dir / "market_state_rotation_v6_evidence_cycle.md").read_text(encoding="utf-8")
    assert "historical_realtime_quote_wait_replaced: `True`" in markdown
    assert "historical_paper_shadow_fill_proxy_replaced: `True`" in markdown
    assert "launch_readiness_status: `research_ready_waiting_for_fresh_signal`" in markdown
    assert "launch_paper_only_rehearsal_status: `armed_waiting_for_fresh_signal`" in markdown
    assert "launch_paper_only_rehearsal_system_ready: `True`" in markdown
    assert "launch_paper_only_max_substitution_status: `max_substitution_complete_realtime_gate_remaining`" in markdown
    assert "launch_resolution_status: `substitution_exhausted_realtime_gates_remaining`" in markdown
    assert "launch_backtest_substitution_exhausted: `True`" in markdown
    assert "launch_no_live_progressable_remaining_gates:" in markdown
    assert "launch_paper_bridge_handoff_status: `blocked_waiting_for_fresh_signal`" in markdown
    assert "launch_safety_controls_status: `INCOMPLETE`" in markdown


def test_launch_readiness_splits_microstructure_metric_proxy_from_real_time_coverage() -> None:
    report = {
        "collection_progress": {
            "quote_observed": 342,
            "quote_required": 300,
            "quote_calendar_days": 2,
            "quote_min_calendar_days": 30,
            "quote_distinct_hours": 18,
            "quote_min_distinct_hours": 24,
            "paper_fill_rows": 0,
            "quote_blockers": ["calendar_days_missing", "distinct_hours_missing"],
            "pending_gates": [
                "p95_adverse_slippage_within_limit",
                "max_adverse_slippage_within_limit",
                "p95_spread_within_limit",
                "p95_latency_within_limit",
            ],
            "failed_gates": ["min_shadow_fill_samples"],
        },
        "readiness_progress": {
            "remaining_work_units": {
                "quote_samples": 0,
                "quote_calendar_days": 28,
                "quote_distinct_hours": 6,
                "paper_shadow_fill_samples": 100,
            }
        },
        "historical_gate_substitution": {
            "realtime_quote_wait_replaced": True,
            "quote_gate_replacements": {
                "quote_samples": True,
                "quote_calendar_days": True,
                "quote_distinct_hours": True,
            },
            "paper_shadow_fill_proxy_replaced": True,
            "realtime_wait_days_removed": 28,
            "remaining_work_units_after_substitution": {
                "quote_samples": 0,
                "quote_calendar_days": 0,
                "quote_distinct_hours": 0,
                "paper_shadow_fill_samples": 0,
            },
            "research_shadow_promotion_readiness_pct_after_substitution": 100.0,
        },
        "paper_bridge_apply_gate": {
            "fresh_market_data": True,
            "fresh_signal": False,
            "can_request_paper_apply_now": False,
        },
        "signal_wait_plan": {"status": "blocked_waiting_for_fresh_signal"},
        "market_data_refresh_plan": {"status": "fresh", "market_data_age_minutes": 1.0},
        "historical_lifecycle_replay": {"proxy_lifecycle_rows": 120},
        "canary_risk_caps_config": {
            "configured": True,
            "status": "configured_from_file",
            "source": "json_file",
            "path": "reports/operations/market_state_rotation_v6_canary_risk_caps.json",
            "errors": [],
        },
        "launch_safety_controls": {
            "overall_status": "PASS",
            "verified_count": len(REQUIRED_SAFETY_CONTROLS),
            "required_count": len(REQUIRED_SAFETY_CONTROLS),
            "missing_or_failed": [],
        },
    }

    launch = evidence._launch_readiness_state_machine(
        report=report,
        generated_at=datetime(2026, 1, 2, tzinfo=UTC),
        canary_max_notional_usdt=10.0,
        canary_max_leverage=10.0,
        canary_max_daily_loss_usdt=1.0,
        shadow_runtime_observed_hours=7.0,
        shadow_runtime_required_hours=24.0,
    )

    micro_gate = next(item for item in launch["stage_gates"] if item["gate"] == "real_microstructure_execution_evidence")
    assert micro_gate["blocker"] == "real_quote_time_coverage_missing"
    assert micro_gate["detail"]["microstructure_metric_ready"] is True
    assert micro_gate["detail"]["historical_quote_time_proxy_ready"] is True
    assert micro_gate["detail"]["microstructure_proxy_ready_for_research"] is True
    assert micro_gate["detail"]["actual_quote_time_coverage_ready"] is False
    assert micro_gate["detail"]["quote_metric_blockers"] == []
    assert launch["component_readiness"]["microstructure_metric_ready"] is True
    assert launch["component_readiness"]["microstructure_time_proxy_ready"] is True
    assert launch["component_readiness"]["real_microstructure_ready"] is False
    assert launch["substitution_matrix"]["microstructure_time_coverage"]["substituted"] is True
    assert launch["substitution_matrix"]["microstructure_time_coverage"]["scope"] == "research_metric_interpretation_only"
    assert launch["resolution_matrix"]["backtest_substitution_exhausted"] is True
    micro_row = next(
        item for item in launch["resolution_matrix"]["rows"] if item["gate"] == "real_microstructure_execution_evidence"
    )
    assert micro_row["state"] == "research_proxy_resolved_launch_real_evidence_remaining"
    assert micro_row["requires_realtime_evidence_for_launch"] is True
    assert micro_row["remaining_real_requirement"] == "real_l2_quote_calendar_and_hour_coverage"
    assert launch["effective_research_status"] == "substitutable_time_gates_replaced_realtime_gates_remaining"
    assert launch["substituted_time_wait_removed_days"] == 28
    assert launch["live_order_submission_allowed"] is False


def test_evidence_cycle_loads_canary_risk_caps_json_without_enabling_orders(monkeypatch, tmp_path) -> None:
    def fake_collection_cycle(**kwargs):
        report_dir = Path(kwargs["report_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)
        payload = _cycle_report()
        (report_dir / CYCLE_REPORT_NAME).write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(evidence, "run_collection_cycle", fake_collection_cycle)
    caps_path = tmp_path / "canary_caps.json"
    caps_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "scope_symbol": "BTCUSDT",
                "strategy_family": "market_state_rotation_v6",
                "max_notional_usdt": 75.0,
                "max_leverage": 7.5,
                "max_daily_loss_usdt": 15.0,
                "max_daily_order_count": 1,
                "max_consecutive_loss_count": 1,
                "kill_switch_required": True,
                "reduce_only_exit_required": True,
                "operator_acknowledged_no_auto_live_order": True,
            }
        ),
        encoding="utf-8",
    )
    report_dir = tmp_path / "evidence"

    report = run_evidence_cycle(
        source_backtest_report_path=tmp_path / "source.json",
        stress_report_path=tmp_path / "stress.json",
        walk_forward_report_path=tmp_path / "walk.json",
        manual_evidence_path=tmp_path / "manual.json",
        sample_jsonl=tmp_path / "sample.jsonl",
        report_dir=report_dir,
        canary_max_notional_usdt=0.0,
        canary_max_leverage=10.0,
        canary_max_daily_loss_usdt=0.0,
        canary_risk_caps_path=caps_path,
    )

    caps = report["canary_risk_caps_config"]
    assert caps["status"] == "configured_from_file"
    assert caps["configured"] is True
    assert caps["effective"]["max_notional_usdt"] == 75.0
    assert caps["effective"]["max_leverage"] == 7.5
    assert caps["effective"]["max_daily_loss_usdt"] == 15.0
    assert caps["safeguards"]["max_daily_order_count"] == 1
    assert caps["safeguards"]["kill_switch_required"] is True
    assert caps["errors"] == []
    assert caps["operator_review"]["required"] is False
    assert "run_market_state_rotation_v6_canary_risk_caps_audit.py" in caps["operator_review"]["quick_audit_command"]
    assert caps["order_submission_allowed"] is False
    launch = report["launch_readiness"]
    assert launch["canary_policy"]["max_notional_usdt"] == 75.0
    assert launch["canary_policy"]["max_leverage"] == 7.5
    assert launch["canary_policy"]["max_daily_loss_usdt"] == 15.0
    assert launch["canary_policy"]["config_status"] == "configured_from_file"
    assert "--canary-risk-caps-json" in launch["operator_commands"]["paper_bridge_dry_run"]
    assert str(caps_path) in launch["operator_commands"]["paper_bridge_dry_run"]
    assert "--historical-evidence-replay" in launch["operator_commands"]["paper_bridge_dry_run"]
    assert "--historical-lifecycle-replay" in launch["operator_commands"]["paper_bridge_dry_run"]
    assert "--refresh-market-data-before-run" in launch["operator_commands"]["paper_bridge_dry_run"]
    assert "--max-signal-age-minutes 15" in launch["operator_commands"]["paper_bridge_dry_run"]
    assert "--report-dir" in launch["operator_commands"]["paper_bridge_dry_run"]
    assert "--historical-evidence-replay" in launch["operator_commands"]["paper_apply_only_after_fresh_signal"]
    assert "--historical-lifecycle-replay" in launch["operator_commands"]["paper_apply_only_after_fresh_signal"]
    assert "--refresh-market-data-before-run" in launch["operator_commands"]["paper_apply_only_after_fresh_signal"]
    assert "--max-signal-age-minutes 15" in launch["operator_commands"]["paper_apply_only_after_fresh_signal"]
    cap_gate = next(item for item in launch["stage_gates"] if item["gate"] == "tiny_canary_risk_caps_configured")
    assert cap_gate["passed"] is True
    safety_gate = next(item for item in launch["stage_gates"] if item["gate"] == "order_safety_controls_verified")
    assert safety_gate["passed"] is False
    assert report["launch_safety_controls"]["overall_status"] == "INCOMPLETE"
    assert launch["tiny_canary_order_submission_allowed"] is False
    assert launch["live_order_submission_allowed"] is False
    assert (report_dir / "canary_risk_caps_config.json").exists()
    markdown = (report_dir / "market_state_rotation_v6_evidence_cycle.md").read_text(encoding="utf-8")
    assert "launch_canary_risk_caps_status: `configured_from_file`" in markdown
    assert "launch_safety_controls_status: `INCOMPLETE`" in markdown


def test_evidence_cycle_accepts_full_safety_controls_without_enabling_live_orders(monkeypatch, tmp_path) -> None:
    def fake_collection_cycle(**kwargs):
        report_dir = Path(kwargs["report_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)
        payload = _cycle_report()
        (report_dir / CYCLE_REPORT_NAME).write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(evidence, "run_collection_cycle", fake_collection_cycle)
    manual_path = tmp_path / "manual_safety.json"
    _write_full_safety_controls(manual_path, verified_at=datetime.now(UTC))

    report_dir = tmp_path / "evidence"
    report = run_evidence_cycle(
        source_backtest_report_path=tmp_path / "source.json",
        stress_report_path=tmp_path / "stress.json",
        walk_forward_report_path=tmp_path / "walk.json",
        manual_evidence_path=manual_path,
        sample_jsonl=tmp_path / "sample.jsonl",
        report_dir=report_dir,
    )

    safety = report["launch_safety_controls"]
    assert safety["overall_status"] == "PASS"
    assert safety["verified_count"] == len(REQUIRED_SAFETY_CONTROLS)
    assert safety["missing_or_failed"] == []
    launch = report["launch_readiness"]
    safety_gate = next(item for item in launch["stage_gates"] if item["gate"] == "order_safety_controls_verified")
    assert safety_gate["passed"] is True
    assert launch["tiny_canary_order_submission_allowed"] is False
    assert launch["live_order_submission_allowed"] is False
    assert report["no_live_order_sent"] is True
    assert (report_dir / "launch_safety_controls.json").exists()


def test_evidence_cycle_blocks_incomplete_canary_risk_caps_json(monkeypatch, tmp_path) -> None:
    def fake_collection_cycle(**kwargs):
        report_dir = Path(kwargs["report_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)
        payload = _cycle_report()
        (report_dir / CYCLE_REPORT_NAME).write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(evidence, "run_collection_cycle", fake_collection_cycle)
    caps_path = tmp_path / "canary_caps.json"
    caps_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "max_notional_usdt": 75.0,
                "max_leverage": 10.0,
                "max_daily_loss_usdt": 60.0,
            }
        ),
        encoding="utf-8",
    )

    report = run_evidence_cycle(
        source_backtest_report_path=tmp_path / "source.json",
        stress_report_path=tmp_path / "stress.json",
        walk_forward_report_path=tmp_path / "walk.json",
        manual_evidence_path=tmp_path / "manual.json",
        sample_jsonl=tmp_path / "sample.jsonl",
        report_dir=tmp_path / "evidence",
        canary_risk_caps_path=caps_path,
    )

    caps = report["canary_risk_caps_config"]
    assert caps["status"] == "invalid_or_incomplete"
    assert caps["configured"] is False
    assert "scope_symbol_must_be_BTCUSDT" in caps["errors"]
    assert "operator_acknowledged_no_auto_live_order_must_be_true" in caps["errors"]
    assert "max_daily_loss_usdt_must_be_lte_50pct_of_max_notional" in caps["errors"]
    assert caps["operator_review"]["required"] is True
    assert "run_market_state_rotation_v6_canary_risk_caps_audit.py" in caps["operator_review"]["quick_audit_command"]
    assert "run_market_state_rotation_v6_evidence_cycle.py" in caps["operator_review"]["validation_command"]
    assert "keep_max_leverage_lte_10" in caps["operator_review"]["review_checklist"]
    cap_gate = next(item for item in report["launch_readiness"]["stage_gates"] if item["gate"] == "tiny_canary_risk_caps_configured")
    assert cap_gate["passed"] is False
    assert report["launch_readiness"]["tiny_canary_order_submission_allowed"] is False


def test_evidence_cycle_marks_fresh_dry_run_actionable_as_paper_apply_request_available(monkeypatch, tmp_path) -> None:
    def fake_collection_cycle(**kwargs):
        payload = _cycle_report(bridge_status="dry_run_actionable", blockers=[])
        report_dir = Path(kwargs["report_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / CYCLE_REPORT_NAME).write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(evidence, "run_collection_cycle", fake_collection_cycle)

    report = run_evidence_cycle(
        source_backtest_report_path=tmp_path / "source.json",
        stress_report_path=tmp_path / "stress.json",
        walk_forward_report_path=tmp_path / "walk.json",
        manual_evidence_path=tmp_path / "manual.json",
        sample_jsonl=tmp_path / "sample.jsonl",
        report_dir=tmp_path / "evidence",
        apply_paper_bridge=False,
    )

    assert report["paper_bridge_apply_gate"]["status"] == "paper_apply_request_available"
    assert report["paper_bridge_apply_gate"]["can_request_paper_apply_now"] is True
    assert report["paper_bridge_apply_gate"]["required_pre_apply_backup"] is True
    assert report["pre_apply_backup_plan"]["status"] == "ready_required_before_paper_apply"
    assert report["pre_apply_backup_plan"]["backup_dir"] == evidence.DEFAULT_PRE_APPLY_BACKUP_DIR
    assert "pre_apply_backup.quick_check == 'ok'" in report["pre_apply_backup_plan"]["verification_required_fields"]
    assert report["readiness_progress"]["paper_apply_readiness_pct"] == 100.0
    assert report["readiness_progress"]["strictest_deployment_gate"] == "paper_shadow_fill_samples"
    assert report["execution_checklist"]["current_phase"] == "paper_apply_operator_review_available"
    assert report["execution_checklist"]["paper_apply_allowed_now"] is True
    assert report["adaptive_collection_plan"]["primary_objective"] == "operator_review_then_apply_paper_bridge"
    assert report["adaptive_collection_plan"]["same_utc_hour_repeat_policy"]["allowed"] is False
    assert "--max-signal-age-minutes 15" in report["adaptive_collection_plan"]["operator_commands"][
        "paper_apply_only_if_gate_allows"
    ]
    assert report["operator_action_plan"]["status"] == "paper_apply_review_available"
    assert report["operator_action_plan"]["top_action"]["action"] == "operator_review_paper_bridge_apply"
    assert report["operator_action_plan"]["top_action"]["run_now"] is True
    assert report["operator_action_plan"]["top_action"]["requires_operator_review"] is True
    assert "--refresh-market-data-before-run" in report["operator_action_plan"]["top_action"]["command"]
    assert "--max-signal-age-minutes 15" in report["operator_action_plan"]["top_action"]["command"]
    assert report["operator_action_plan"]["top_action"]["pre_apply_backup_plan"]["status"] == (
        "ready_required_before_paper_apply"
    )
    assert report["operator_action_plan"]["top_action"]["post_apply_required_review"] == "execution_parity_review"
    assert report["signal_wait_plan"]["status"] == "fresh_signal_available"
    assert report["signal_wait_plan"]["command"] is None
    assert not [
        item
        for item in report["operator_action_plan"]["items"]
        if item["action"] == "monitor_fresh_signal_without_quote_capture"
    ]
    assert report["operator_runbook_plan"]["status"] == "run_required_action_now"
    assert report["operator_runbook_plan"]["next_operator_action"]["action"] == "operator_review_paper_bridge_apply"
    assert report["operator_runbook_plan"]["coordination_rule"] == "follow_top_operator_action"
    assert report["execution_parity_collection_plan"]["status"] == "ready_to_credit_next_paper_apply"
    assert report["execution_parity_collection_plan"]["currently_creditable_actions"] == ["remove"]
    assert report["execution_parity_collection_plan"]["will_credit_current_apply_after_operator_review"] is True
    assert report["execution_parity_collection_plan"]["projected_journal_rows_after_current_creditable_apply"] == 1
    assert report["execution_parity_collection_plan"]["estimated_events_needed_after_current_creditable_apply"] == 19
    assert report["launch_readiness"]["paper_bridge_handoff"]["pre_apply_backup_plan"]["status"] == (
        "ready_required_before_paper_apply"
    )
    paper_only = report["launch_readiness"]["paper_only_rehearsal"]
    assert paper_only["status"] == "paper_apply_review_available"
    assert paper_only["system_ready"] is True
    assert paper_only["armed"] is False
    assert paper_only["current_rehearsal_available"] is True
    assert paper_only["paper_apply_allowed_now"] is True
    assert paper_only["max_substitution_status"] == "proxy_prechecks_remaining"
    assert paper_only["max_substitution_ready"] is False
    assert "historical_quote_replay" in paper_only["unresolved_proxy_gates"]
    assert paper_only["next_action"] == "operator_review_paper_bridge_dry_run_then_apply_with_verified_backup"
    assert "execution_parity_20_sample_floor_for_live_promotion" in paper_only["not_required_for_paper_only_goal"]
    assert "--pre-apply-backup-dir" in report["launch_readiness"]["paper_bridge_handoff"]["apply_command"]
    assert "operator_may_rerun_with_apply_paper_bridge_after_review_and_backup" in report["next_actions"]
    assert "do_not_apply_paper_bridge_without_verified_pre_apply_backup" in report["non_negotiables"]


def test_evidence_cycle_blocks_remove_apply_when_no_open_paper_plan(monkeypatch, tmp_path) -> None:
    def fake_collection_cycle(**kwargs):
        payload = _cycle_report(bridge_status="dry_run_no_open_v6_paper_plan", blockers=[])
        payload["bridge"]["remove_plan_precheck"] = {
            "status": "no_open_v6_paper_plan",
            "direction": "short",
            "open_plan_count": 0,
            "no_live_order_sent": True,
        }
        report_dir = Path(kwargs["report_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / CYCLE_REPORT_NAME).write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(evidence, "run_collection_cycle", fake_collection_cycle)

    report = run_evidence_cycle(
        source_backtest_report_path=tmp_path / "source.json",
        stress_report_path=tmp_path / "stress.json",
        walk_forward_report_path=tmp_path / "walk.json",
        manual_evidence_path=tmp_path / "manual.json",
        sample_jsonl=tmp_path / "sample.jsonl",
        report_dir=tmp_path / "evidence",
        apply_paper_bridge=False,
    )

    gate = report["paper_bridge_apply_gate"]
    assert gate["status"] == "blocked_no_open_v6_paper_plan"
    assert gate["can_request_paper_apply_now"] is False
    assert gate["remove_plan_precheck"]["status"] == "no_open_v6_paper_plan"
    assert report["pre_apply_backup_plan"]["status"] == "blocked_until_paper_apply_gate_available"
    assert report["execution_parity_collection_plan"]["status"] == "waiting_for_open_paper_plan_after_remove_signal"
    assert "remove_signal_has_no_open_v6_paper_plan" in report["execution_parity_collection_plan"]["blockers"]
    assert report["execution_parity_collection_plan"]["will_credit_current_apply_after_operator_review"] is False
    assert not [
        item
        for item in report["operator_action_plan"]["items"]
        if item["action"] == "operator_review_paper_bridge_apply" and item["run_now"] is True
    ]
    assert report["no_live_order_sent"] is True


def test_signal_wait_plan_caps_monitor_interval_to_fresh_signal_window() -> None:
    plan = evidence._signal_wait_plan(
        cycle_report={
            "bridge": {
                "freshness": {"signal_age_minutes": 120.0},
                "event_cadence": {
                    "expected_days_per_event": 2.0,
                    "expected_days_per_add": 7.0,
                    "latest_add_age_hours": 12.0,
                    "median_add_gap_hours": 48.0,
                    "latest_add_age_to_median_gap": 0.25,
                    "add_wait_state": "within_recent_add_gap_distribution",
                },
            }
        },
        apply_gate={"fresh_signal": False},
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        max_signal_age_minutes=15,
    )

    assert plan["cadence_lag_level"] == "within_recent_add_cadence"
    assert plan["signal_absence_primary_cause"] == "expected_sparse_signal_wait_within_recent_add_cadence"
    assert plan["signal_pipeline_issue_suspected"] is False
    assert plan["signal_absence_diagnosis"]["class"] == "healthy_sparse_cadence_wait"
    assert plan["signal_absence_diagnosis"]["safe_next_step"] == (
        "monitor_on_fresh_signal_window_without_forcing_entry"
    )
    assert plan["cadence_recommended_monitor_interval_minutes"] == 60
    assert plan["recommended_monitor_interval_minutes"] == 15
    assert plan["signal_freshness_capture_window_minutes"] == 15.0
    assert plan["monitor_interval_capped_by_signal_freshness"] is True
    assert plan["monitor_signal_age_alignment"] == "capped_to_fresh_signal_window"
    assert plan["next_monitor_after_utc"] == "2026-01-01T12:15:00+00:00"
    assert "--max-signal-age-minutes 15" in plan["command"]
    assert plan["manual_signal_override_allowed"] is False
    assert plan["no_live_order_sent"] is True


def test_paper_apply_gate_blocks_fresh_signal_when_execution_parity_preflight_fails() -> None:
    gate = evidence._paper_apply_gate(
        {
            "bridge": {
                "overall_status": "dry_run_preflight_blocked",
                "apply_paper": False,
                "snapshot_blockers": [],
                "bridge_action": "add",
                "execution_parity_preflight": {
                    "passed": False,
                    "blockers": ["source_event_ts_missing_or_invalid"],
                },
            }
        }
    )

    assert gate["status"] == "blocked_execution_parity_preflight"
    assert gate["can_request_paper_apply_now"] is False
    assert gate["fresh_signal"] is True
    assert gate["execution_parity_preflight_passed"] is False
    assert gate["next_step"] == "fix_execution_parity_preflight_fields_before_paper_apply"
    plan = evidence._execution_parity_collection_plan(
        collection_progress={
            "execution_parity_journal_rows": 3,
            "execution_parity_required_rows": 20,
            "execution_parity_lifecycle_rows": 3,
            "execution_parity_passed": False,
            "execution_parity_blockers": ["insufficient_execution_sample_count"],
        },
        apply_gate=gate,
        journal_report={"conversion": {"entry_rows_written": 2, "exit_rows_written": 1, "include_exit_rows": True}},
    )
    assert plan["status"] == "blocked_by_execution_parity_preflight"
    assert plan["missing_samples"] == 17
    assert plan["estimated_future_paper_apply_events_needed"] == 17
    assert plan["estimated_events_needed_after_current_creditable_apply"] == 17
    assert plan["will_credit_current_apply_after_operator_review"] is False
    assert plan["accepted_actions"] == ["add", "remove"]
    assert plan["currently_creditable_actions"] == []
    assert plan["next_step"] == "fix_execution_parity_preflight_fields_before_paper_apply"


def test_run_evidence_cycle_can_refresh_market_data_before_run(monkeypatch, tmp_path) -> None:
    refresh_calls = []

    class Completed:
        returncode = 0
        stdout = '{"no_live_order_sent": true}'
        stderr = ""

    def fake_subprocess_run(command, **kwargs):
        refresh_calls.append((command, kwargs))
        return Completed()

    def fake_collection_cycle(**kwargs):
        payload = _cycle_report(market_data_age_minutes=1.0)
        report_dir = Path(kwargs["report_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / CYCLE_REPORT_NAME).write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(evidence.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(evidence, "run_collection_cycle", fake_collection_cycle)

    report = run_evidence_cycle(
        source_backtest_report_path=tmp_path / "source.json",
        stress_report_path=tmp_path / "stress.json",
        walk_forward_report_path=tmp_path / "walk.json",
        manual_evidence_path=tmp_path / "manual.json",
        sample_jsonl=tmp_path / "sample.jsonl",
        report_dir=tmp_path / "evidence",
        refresh_market_data_before_run=True,
    )

    assert len(refresh_calls) == 1
    command = refresh_calls[0][0]
    assert "--data-refresh-only" in command
    assert "--max-cache-age-minutes" in command
    assert report["pre_run_market_data_refresh"]["status"] == "refreshed"
    assert report["pre_run_market_data_refresh"]["no_live_order_sent"] is True
    assert report["market_data_refresh_plan"]["status"] == "fresh"
    assert report["no_live_order_sent"] is True


def test_evidence_cycle_prioritizes_market_data_refresh_when_stale(monkeypatch, tmp_path) -> None:
    def fake_collection_cycle(**kwargs):
        payload = _cycle_report(
            blockers=["market_data_stale", "signal_stale"],
            market_data_age_minutes=31.5,
            max_cache_age_minutes=30,
        )
        report_dir = Path(kwargs["report_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / CYCLE_REPORT_NAME).write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(evidence, "run_collection_cycle", fake_collection_cycle)

    report = run_evidence_cycle(
        source_backtest_report_path=tmp_path / "source.json",
        stress_report_path=tmp_path / "stress.json",
        walk_forward_report_path=tmp_path / "walk.json",
        manual_evidence_path=tmp_path / "manual.json",
        sample_jsonl=tmp_path / "sample.jsonl",
        report_dir=tmp_path / "evidence",
    )

    assert report["paper_bridge_apply_gate"]["fresh_market_data"] is False
    assert report["market_data_refresh_plan"]["status"] == "stale_minor_threshold_breach"
    assert report["market_data_refresh_plan"]["severity"] == "low"
    assert report["market_data_refresh_plan"]["market_data_age_minutes"] == 31.5
    assert report["market_data_refresh_plan"]["max_market_data_age_minutes"] == 30.0
    assert report["market_data_refresh_plan"]["stale_by_minutes"] == 1.5
    assert report["market_data_refresh_plan"]["refresh_days"] == 180
    assert report["market_data_refresh_plan"]["source_load_days"] == 1825
    assert report["market_data_refresh_plan"]["reason"] == "refresh_runtime_load_days_cache_not_source_search_cache"
    assert "--data-refresh-only" in report["market_data_refresh_plan"]["command"]
    assert "--days 180" in report["market_data_refresh_plan"]["command"]
    assert "--max-cache-age-minutes 0" in report["market_data_refresh_plan"]["command"]
    assert "--max-market-data-age-minutes 30" in report["market_data_refresh_plan"]["evidence_rerun_command"]
    assert [item["action"] for item in report["market_data_refresh_plan"]["sequence"]] == [
        "refresh_runtime_market_data_cache",
        "rerun_evidence_cycle_after_cache_refresh",
    ]
    assert report["operator_action_plan"]["status"] == "market_data_refresh_required"
    assert report["operator_action_plan"]["top_action"]["action"] == "refresh_market_data_and_rerun_evidence_cycle"
    assert report["operator_action_plan"]["top_action"]["run_now"] is True
    assert report["operator_action_plan"]["top_action"]["stage"] == "market_data"
    assert report["operator_action_plan"]["top_action"]["stale_by_minutes"] == 1.5
    assert "--data-refresh-only" in report["operator_action_plan"]["top_action"]["command"]
    assert report["operator_runbook_plan"]["status"] == "run_required_action_now"
    assert report["operator_runbook_plan"]["next_operator_action"]["action"] == "refresh_market_data_and_rerun_evidence_cycle"
    assert report["operator_runbook_plan"]["next_required_or_scheduled_action"]["action"] == (
        "refresh_market_data_and_rerun_evidence_cycle"
    )
    assert report["operator_runbook_plan"]["next_optional_action"] is None
    assert report["operator_runbook_plan"]["coordination_rule"] == "refresh_market_data_before_quote_or_signal_decisions"
    assert "market_data_refresh_required_before_downstream_quote_signal_or_paper_actions" in report[
        "operator_runbook_plan"
    ]["coordination_warnings"]
    assert "keep_quote_window_and_signal_monitor_cadences_separate" in report["operator_runbook_plan"][
        "coordination_warnings"
    ]
    assert report["operator_runbook_plan"]["coordination_warning_count"] == 2
    assert [item["action"] for item in report["operator_runbook_plan"]["required_now_actions"]] == [
        "refresh_market_data_and_rerun_evidence_cycle"
    ]
    assert not report["operator_runbook_plan"]["optional_now_actions"]
    assert [item["action"] for item in report["operator_runbook_plan"]["run_now_actions"]] == [
        "refresh_market_data_and_rerun_evidence_cycle"
    ]
    assert not report["operator_runbook_plan"]["scheduled_actions"]
    assert [item["action"] for item in report["operator_runbook_plan"]["blocked_by_market_data_actions"]] == [
        "run_quote_shadow_capture_now",
        "monitor_fresh_signal_without_quote_capture",
    ]
    assert all(
        item["blocked_by"] == "market_data_freshness"
        for item in report["operator_runbook_plan"]["blocked_by_market_data_actions"]
    )
    assert report["operator_runbook_plan"]["blocked_by_market_data_action_count"] == 2
    assert report["operator_runbook_plan"]["required_now_action_count"] == 1
    assert report["operator_runbook_plan"]["optional_now_action_count"] == 0
    assert report["evidence_collection_timeline"]["status"] == "blocked_until_market_data_refresh"
    assert report["evidence_collection_timeline"]["market_data_precondition"] == "refresh_required"
    assert [item["action"] for item in report["evidence_collection_timeline"]["blocked_by_market_data_actions"]] == [
        "run_quote_shadow_capture_now",
        "monitor_fresh_signal_without_quote_capture",
    ]
    assert "blocked_by_market_data" in [
        item["timing"] for item in report["operator_runbook_plan"]["operator_sequence"]
    ]
    assert "refresh_market_data_and_rerun_evidence_cycle_before_signal_or_quote_decisions" in report["next_actions"]


def test_evidence_cycle_compares_against_prior_evidence_cycle(monkeypatch, tmp_path) -> None:
    prior_dir = tmp_path / "prior_evidence"
    prior_dir.mkdir(parents=True)
    prior_payload = {
        "generated_at": "2000-01-01T00:00:00+00:00",
        "collection_progress": {
            "quote_observed": 30,
            "quote_calendar_days": 1,
            "quote_distinct_hours": 4,
            "paper_fill_rows": 0,
        },
        "readiness_progress": {
            "quote_evidence_readiness_pct": 3.3333,
            "shadow_promotion_readiness_pct": 0.0,
        },
        "execution_checklist": {"current_phase": "prior_phase"},
    }
    (prior_dir / EVIDENCE_REPORT_NAME).write_text(json.dumps(prior_payload), encoding="utf-8")

    def fake_collection_cycle(**kwargs):
        payload = _cycle_report()
        report_dir = Path(kwargs["report_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / CYCLE_REPORT_NAME).write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(evidence, "run_collection_cycle", fake_collection_cycle)

    report = run_evidence_cycle(
        source_backtest_report_path=tmp_path / "source.json",
        stress_report_path=tmp_path / "stress.json",
        walk_forward_report_path=tmp_path / "walk.json",
        manual_evidence_path=tmp_path / "manual.json",
        sample_jsonl=tmp_path / "sample.jsonl",
        report_dir=tmp_path / "current_evidence",
    )

    assert report["readiness_trend"]["status"] == "progressing_with_unresolved_gates"
    assert report["readiness_trend"]["history_count"] == 1
    assert report["readiness_trend"]["latest_delta"]["quote_observed"] == 10
    assert report["readiness_trend"]["latest_delta"]["quote_calendar_days"] == 1
    assert report["readiness_trend"]["latest_delta"]["quote_distinct_hours"] == 1
    assert report["readiness_trend"]["latest_delta"]["paper_fill_rows"] == 0
    assert report["readiness_trend"]["latest_delta"]["execution_parity_journal_rows"] == 0
    assert report["readiness_trend"]["latest_delta"]["quote_evidence_readiness_pct"] == 3.3334
    assert report["readiness_trend"]["cycles_to_quote_sample_completion_at_latest_delta"] == 26
    assert report["readiness_trend"]["cycles_to_paper_fill_completion_at_latest_delta"] is None
    assert report["readiness_trend"]["cycles_to_execution_parity_completion_at_latest_delta"] is None
    assert "paper_shadow_fill_no_recent_progress" in report["readiness_trend"]["stagnation_flags"]
    assert "execution_parity_journal_no_recent_progress" in report["readiness_trend"]["stagnation_flags"]
    assert "fresh_signal_waiting" in report["readiness_trend"]["stagnation_flags"]
    assert report["readiness_trend"]["previous_snapshot"]["current_phase"] == "prior_phase"
    assert report["adaptive_collection_plan"]["blockers_to_action"] == [
        "paper_fill_requires_fresh_signal_and_paper_lifecycle_rows",
        "fresh_signal_is_not_operator_forced",
    ]


def test_evidence_cycle_passes_preflight_effective_quote_samples_to_collection(monkeypatch, tmp_path) -> None:
    seen: dict[str, int] = {}

    def fake_preflight(**kwargs):
        return {
            "status": "active",
            "requested_quote_samples_per_tick": kwargs["requested_quote_samples_per_tick"],
            "effective_quote_samples_per_tick": 0,
            "decision": "skip_duplicate_utc_hour_until_missing_hour_window",
            "no_live_order_sent": True,
        }

    def fake_collection_cycle(**kwargs):
        seen["quote_samples_per_tick"] = int(kwargs["quote_samples_per_tick"])
        payload = _cycle_report()
        report_dir = Path(kwargs["report_dir"])
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / CYCLE_REPORT_NAME).write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(evidence, "_quote_cadence_preflight", fake_preflight)
    monkeypatch.setattr(evidence, "run_collection_cycle", fake_collection_cycle)

    report = run_evidence_cycle(
        source_backtest_report_path=tmp_path / "source.json",
        stress_report_path=tmp_path / "stress.json",
        walk_forward_report_path=tmp_path / "walk.json",
        manual_evidence_path=tmp_path / "manual.json",
        sample_jsonl=tmp_path / "sample.jsonl",
        report_dir=tmp_path / "evidence",
        quote_samples_per_tick=2,
    )

    assert seen["quote_samples_per_tick"] == 0
    assert report["quote_cadence_preflight"]["effective_quote_samples_per_tick"] == 0
    assert report["quote_cadence_preflight"]["decision"] == "skip_duplicate_utc_hour_until_missing_hour_window"
    assert report["adaptive_collection_plan"]["useful_to_run_now"] is False
    assert report["adaptive_collection_plan"]["advances_quote_evidence_now"] is False
    assert report["adaptive_collection_plan"]["bridge_audit_refresh_useful_now"] is True
    assert report["adaptive_collection_plan"]["next_quote_evidence_window"]["reason"] in {
        "wait_for_next_missing_utc_hour_bucket",
        "quote_sample_count_can_progress_now_when_requested_samples_are_positive",
    }
    assert report["operator_action_plan"]["status"] == "wait_for_next_quote_window"
    assert report["operator_action_plan"]["top_action"]["action"] == "wait_for_next_quote_evidence_window"
    assert report["operator_action_plan"]["top_action"]["run_now"] is False
    assert "execute_before_utc" in report["operator_action_plan"]["top_action"]
    assert "execute_before_kst" in report["operator_action_plan"]["top_action"]
    assert report["operator_action_plan"]["top_action"]["window_kind"] in {
        "missing_utc_hour_bucket",
        "quote_sample_count",
    }
    assert report["operator_action_plan"]["top_action"]["missed_window_next_step"] == (
        "rerun_evidence_cycle_to_recompute_next_quote_window"
    )
    assert "--quote-samples-per-tick 0" in report["operator_action_plan"]["top_action"]["missed_window_command"]
    assert report["operator_action_plan"]["top_action"]["execution_window"]["status"] in {"now", "wait"}
    assert report["operator_action_plan"]["top_action"]["execution_window"]["capture_command"] == report[
        "operator_action_plan"
    ]["top_action"]["command"]
    assert report["operator_action_plan"]["top_action"]["execution_window"]["missed_window_command"] == report[
        "operator_action_plan"
    ]["top_action"]["missed_window_command"]
    assert any(
        item["action"] == "optional_bridge_audit_refresh_without_quote_capture"
        for item in report["operator_action_plan"]["items"]
    )
    assert any(
        item["action"] == "monitor_fresh_signal_without_quote_capture" for item in report["operator_action_plan"]["items"]
    )
    assert report["operator_runbook_plan"]["status"] == "wait_until_next_scheduled_action"
    assert not report["operator_runbook_plan"]["required_now_actions"]
    assert [item["action"] for item in report["operator_runbook_plan"]["optional_now_actions"]] == [
        "optional_bridge_audit_refresh_without_quote_capture"
    ]
    assert report["operator_runbook_plan"]["next_optional_action"]["action"] == (
        "optional_bridge_audit_refresh_without_quote_capture"
    )
    assert report["operator_runbook_plan"]["required_now_action_count"] == 0
    assert report["operator_runbook_plan"]["optional_now_action_count"] == 1
    assert "optional_now_action_does_not_replace_required_due_or_scheduled_actions" in report[
        "operator_runbook_plan"
    ]["coordination_warnings"]
    assert "keep_quote_window_and_signal_monitor_cadences_separate" in report["operator_runbook_plan"][
        "coordination_warnings"
    ]
    assert report["operator_runbook_plan"]["coordination_warning_count"] == 2
    assert report["operator_runbook_plan"]["coordination_rule"] == (
        "wait_for_quote_window_and_monitor_signal_without_quote_capture_when_due"
    )
    assert report["evidence_collection_timeline"]["status"] == "active_quote_signal_timeline"
    assert report["evidence_collection_timeline"]["market_data_precondition"] == "fresh"
    assert report["evidence_collection_timeline"]["quote_collection_slot_count"] >= 1
    assert report["evidence_collection_timeline"]["signal_monitor"]["command"] == report["signal_wait_plan"]["command"]
    assert "<" not in report["evidence_collection_timeline"]["signal_monitor"]["rendered_command"]
    assert "<" not in report["evidence_collection_timeline"]["next_quote_slot"]["rendered_command"]
    assert "<" not in report["evidence_collection_timeline"]["next_quote_slot"]["rendered_missed_window_command"]
    assert "market_state_rotation_v6_signal_monitor_" in report["evidence_collection_timeline"][
        "signal_monitor"
    ]["rendered_command"]
    assert "market_state_rotation_v6_timeline_quote_capture_" in report["evidence_collection_timeline"][
        "next_quote_slot"
    ]["rendered_command"]
    assert report["evidence_collection_timeline"]["next_required_timeline_event"]["action"] in {
        "monitor_fresh_signal_without_quote_capture",
        "run_quote_shadow_capture_for_evidence_window",
    }
    assert "<" not in report["evidence_collection_timeline"]["next_required_timeline_event"]["rendered_command"]
    assert report["evidence_collection_timeline"]["command_validation"]["status"] == "ready"
    assert report["evidence_collection_timeline"]["command_validation"]["issue_count"] == 0
    assert report["evidence_collection_timeline"]["command_validation"]["unresolved_placeholder_count"] == 0
    assert report["evidence_collection_timeline"]["command_validation"]["live_order_flag_count"] == 0
    assert report["evidence_collection_timeline"]["command_validation"]["duplicate_report_dir_count"] == 0
    assert report["evidence_collection_timeline"]["command_validation"]["command_count"] == len(
        report["evidence_collection_timeline"]["command_manifest"]
    )
    assert report["evidence_collection_timeline"]["collection_target_forecast"]["status"] in {
        "timeline_covers_daily_collection_targets",
        "timeline_below_daily_collection_targets",
    }
    assert report["evidence_collection_timeline"]["collection_target_forecast"]["planned_quote_slot_count"] == report[
        "evidence_collection_timeline"
    ]["quote_collection_slot_count"]
    assert report["evidence_collection_timeline"]["collection_target_forecast"][
        "estimated_quote_rows_if_all_slots_run"
    ] >= 0
    assert report["evidence_collection_timeline"]["collection_target_forecast"]["no_live_order_sent"] is True
    assert report["evidence_collection_timeline"]["minimum_execution_plan"]["status"] in {
        "minimum_daily_targets_reachable",
        "minimum_daily_targets_not_reachable",
        "no_quote_execution_required",
    }
    assert report["evidence_collection_timeline"]["minimum_execution_plan"]["required_quote_slot_count"] <= report[
        "evidence_collection_timeline"
    ]["quote_collection_slot_count"]
    assert report["evidence_collection_timeline"]["minimum_execution_plan"]["optional_acceleration_slot_count"] >= 0
    assert report["evidence_collection_timeline"]["minimum_execution_plan"]["no_live_order_sent"] is True
    assert report["evidence_collection_timeline"]["completion_projection"]["status"] in {
        "projected",
        "unprojectable",
    }
    assert "minimum_required_slots_daily" in report["evidence_collection_timeline"]["completion_projection"]
    assert "full_timeline_daily" in report["evidence_collection_timeline"]["completion_projection"]
    assert report["evidence_collection_timeline"]["completion_projection"]["no_live_order_sent"] is True
    assert "do_not_enable_live_orders_from_evidence_timeline" in report["evidence_collection_timeline"][
        "operator_precautions"
    ]
    assert not report["operator_runbook_plan"]["run_now_actions"] or [
        item["action"] for item in report["operator_runbook_plan"]["run_now_actions"]
    ] == ["optional_bridge_audit_refresh_without_quote_capture"]
    assert any(
        item["action"] == "wait_for_next_quote_evidence_window"
        for item in report["operator_runbook_plan"]["scheduled_actions"]
    )
    assert any(
        item["action"] == "monitor_fresh_signal_without_quote_capture"
        for item in report["operator_runbook_plan"]["scheduled_actions"]
    )
    assert [item["timing"] for item in report["operator_runbook_plan"]["operator_sequence"][:3]] == [
        "optional_now",
        "scheduled",
        "scheduled",
    ]
    assert report["operator_runbook_plan"]["operator_sequence"][0]["action"] == (
        "optional_bridge_audit_refresh_without_quote_capture"
    )
    assert "--historical-evidence-replay" in report["operator_runbook_plan"]["operator_sequence"][0]["command"]
    assert "--historical-lifecycle-replay" in report["operator_runbook_plan"]["operator_sequence"][0]["command"]
    assert "continue_quote_shadow_collection_until_samples_calendar_days_and_distinct_hours_pass" not in report[
        "next_actions"
    ]
    assert "spread_quote_shadow_collection_across_missing_utc_hours" not in report["next_actions"]
    assert "wait_until_next_quote_evidence_window_before_quote_shadow_capture" in report["next_actions"]
    assert "bridge_audit_refresh_optional_now_without_quote_capture" in report["next_actions"]
    assert "monitor_fresh_v6_signal_on_signal_wait_plan_cadence_without_forcing_entry" in report["next_actions"]
