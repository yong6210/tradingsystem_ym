import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts import run_market_state_rotation_v6_launch_shadow_watch as watch
from scripts.run_market_state_rotation_v6_quote_shadow_audit import build_quote_shadow_row


def _book() -> dict:
    return {
        "bids": [["99999", "1.0"], ["99998", "1.0"]],
        "asks": [["100001", "1.0"], ["100002", "1.0"]],
    }


def _args(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        iterations=2,
        interval_seconds=0.0,
        target_hours=0.0,
        quote_samples_per_tick=2,
        force_quote_sample=False,
        disable_adaptive_quote_cadence=False,
        sleep_until_next_missing_quote_window=False,
        max_pre_run_wait_seconds=3600.0,
        quote_window_wakeup_buffer_seconds=5.0,
        disable_market_data_refresh_after_quote_window_sleep=False,
        disable_market_data_refresh_before_evidence_run=False,
        report_dir=str(tmp_path / "watch"),
        evidence_report_root=str(tmp_path / "evidence"),
        source_backtest_report=str(tmp_path / "source.json"),
        stress_report=str(tmp_path / "stress.json"),
        walk_forward_report=str(tmp_path / "walk.json"),
        manual_safety_evidence="",
        sample_jsonl=str(tmp_path / "sample.jsonl"),
        historical_replay_source=str(tmp_path / "btc_1h.json"),
        historical_replay_days=30,
        historical_lifecycle_source=str(tmp_path / "lifecycle.json"),
        canary_max_notional_usdt=0.0,
        canary_max_leverage=10.0,
        canary_max_daily_loss_usdt=0.0,
        canary_risk_caps_json=str(tmp_path / "canary_caps.json"),
        microstructure_recent_hours=24.0,
        quiet=True,
    )


def test_launch_shadow_watch_repeats_no_live_evidence_cycles(monkeypatch, tmp_path) -> None:
    calls = []
    sleeps = []

    def fake_run_evidence_cycle(**kwargs):
        calls.append(kwargs)
        iteration = len(calls)
        return {
            "overall_status": "healthy_abstention_waiting_for_quality_signal",
            "no_live_order_sent": True,
            "collection_progress": {
                "quote_observed": 80 + iteration * 2,
                "quote_distinct_hours": 8 + iteration,
                "paper_fill_rows": 0,
            },
            "readiness_progress": {},
            "paper_bridge_apply_gate": {
                "fresh_signal": False,
                "can_request_paper_apply_now": False,
            },
            "quote_cadence_preflight": {
                "decision": "capture_new_utc_hour_for_hour_gate",
                "effective_quote_samples_per_tick": 2,
                "force_quote_sample": False,
            },
            "signal_wait_plan": {
                "status": "blocked_waiting_for_fresh_signal",
            },
            "launch_readiness": {
                "status": "research_ready_waiting_for_fresh_signal",
                "research_ready": True,
                "shadow_ready": True,
                "tiny_canary_evidence_ready": False,
                "next_blocker": {
                    "gate": "current_fresh_signal",
                    "next_action": "monitor_fresh_v6_signal_without_forcing_entry",
                },
                "blocking_gates": [
                    {
                        "gate": "current_fresh_signal",
                        "blocker": "fresh_signal_missing_or_stale",
                        "next_action": "monitor_fresh_v6_signal_without_forcing_entry",
                    }
                ],
                "operator_commands": {
                    "microstructure_quote_capture": "capture",
                    "paper_bridge_dry_run": "dry-run",
                    "paper_apply_only_after_fresh_signal": "paper-apply",
                },
            },
            "historical_gate_substitution": {
                "realtime_quote_wait_replaced": True,
                "paper_shadow_fill_proxy_replaced": True,
            },
            "canary_risk_caps_config": {
                "status": "missing_optional_config_file",
                "configured": False,
                "source": "cli_or_default",
                "errors": ["max_notional_usdt_must_be_positive", "max_daily_loss_usdt_must_be_positive"],
            },
        }

    monkeypatch.setattr(watch, "run_evidence_cycle", fake_run_evidence_cycle)

    summary = watch.run_launch_shadow_watch(_args(tmp_path), sleep_fn=lambda seconds: sleeps.append(seconds))

    assert summary["status"] == "target_observation_complete"
    assert summary["completed_iterations"] == 2
    assert summary["no_live_order_sent"] is True
    assert summary["progress"]["quote_observed_delta"] == 2
    assert summary["progress"]["quote_distinct_hours_delta"] == 1
    assert summary["progress"]["fresh_signal_seen"] is False
    assert summary["launch_week_plan"][0]["objective"] == "fresh_signal_monitor_and_quote_microstructure_collection"
    assert summary["launch_week_plan"][0]["command"] == "capture"
    assert len(calls) == 2
    assert calls[0]["quote_samples_per_tick"] == 2
    assert calls[0]["force_quote_sample"] is False
    assert calls[0]["adaptive_quote_cadence"] is True
    assert calls[0]["historical_evidence_replay"] is True
    assert calls[0]["refresh_market_data_before_run"] is True
    assert calls[0]["historical_lifecycle_replay"] is True
    assert calls[0]["canary_risk_caps_path"] == tmp_path / "canary_caps.json"
    assert calls[0]["shadow_runtime_required_hours"] == 0.0
    assert calls[0]["shadow_runtime_observed_hours"] >= 0.0
    assert sleeps == [0.0]
    latest_json = tmp_path / "watch" / "latest.json"
    latest_md = tmp_path / "watch" / "latest.md"
    assert latest_json.exists()
    assert latest_md.exists()
    payload = json.loads(latest_json.read_text(encoding="utf-8"))
    assert payload["latest_run"]["launch_readiness"]["next_blocker"]["gate"] == "current_fresh_signal"
    assert payload["latest_run"]["quote_cadence_preflight"]["decision"] == "capture_new_utc_hour_for_hour_gate"
    assert payload["progress"]["quote_observed_delta"] == 2
    assert payload["baseline_collection_progress"]["quote_observed"] == 82
    assert payload["canary_risk_caps_config"]["status"] == "missing_optional_config_file"
    assert payload["blocker_resolution_plan"][0]["gate"] == "current_fresh_signal"
    assert payload["blocker_resolution_plan"][0]["can_resolve_now"] is False
    assert "launch_next_blocker: `current_fresh_signal`" in latest_md.read_text(encoding="utf-8")
    assert "quote_observed_delta: `2`" in latest_md.read_text(encoding="utf-8")
    assert "quote_cadence_decision: `capture_new_utc_hour_for_hour_gate`" in latest_md.read_text(encoding="utf-8")
    assert "## Blocker Resolution Plan" in latest_md.read_text(encoding="utf-8")


def test_launch_shadow_watch_explains_order_safety_controls_blocker(monkeypatch, tmp_path) -> None:
    args = _args(tmp_path)
    args.iterations = 1
    args.target_hours = 0.0

    def fake_run_evidence_cycle(**kwargs):
        return {
            "overall_status": "healthy_abstention_waiting_for_quality_signal",
            "no_live_order_sent": True,
            "collection_progress": {"quote_observed": 300, "quote_distinct_hours": 24, "paper_fill_rows": 100},
            "readiness_progress": {},
            "paper_bridge_apply_gate": {"fresh_signal": True, "can_request_paper_apply_now": False},
            "signal_wait_plan": {},
            "launch_readiness": {
                "status": "shadow_ready_waiting_for_order_safety_controls",
                "research_ready": True,
                "shadow_ready": True,
                "tiny_canary_evidence_ready": False,
                "next_blocker": {
                    "gate": "order_safety_controls_verified",
                    "blocker": "order_safety_controls_missing_or_incomplete",
                },
                "blocking_gates": [
                    {
                        "gate": "order_safety_controls_verified",
                        "blocker": "order_safety_controls_missing_or_incomplete",
                        "next_action": "run_manual_safety_drills_and_safety_controls_audit_until_all_required_controls_pass",
                    }
                ],
                "operator_commands": {},
            },
            "launch_safety_controls": {
                "overall_status": "INCOMPLETE",
                "verified_count": 3,
                "required_count": 10,
                "missing_or_failed": ["position_sync_verified", "reduce_only_exit_verified"],
            },
            "historical_gate_substitution": {},
            "canary_risk_caps_config": {"configured": True, "status": "configured_from_file", "errors": []},
        }

    monkeypatch.setattr(watch, "run_evidence_cycle", fake_run_evidence_cycle)

    summary = watch.run_launch_shadow_watch(args, sleep_fn=lambda seconds: None)

    plan = summary["blocker_resolution_plan"][0]
    assert plan["gate"] == "order_safety_controls_verified"
    assert plan["can_resolve_now"] is True
    assert plan["requires_operator_review"] is True
    assert "run_market_state_rotation_v6_manual_safety_drills.py" in plan["command"]
    assert "run_market_state_rotation_v6_safety_controls_audit.py" in plan["follow_up_command"]
    assert plan["verified_count"] == 3
    assert plan["required_count"] == 10
    assert plan["missing_or_failed"] == ["position_sync_verified", "reduce_only_exit_verified"]
    assert summary["no_live_order_sent"] is True


def test_blocker_plan_does_not_surface_paper_apply_command_before_fresh_signal() -> None:
    plan = watch._blocker_resolution_plan(
        latest={
            "paper_bridge_apply_gate": {
                "fresh_signal": False,
                "can_request_paper_apply_now": False,
            },
            "signal_wait_plan": {
                "command": "monitor-signal",
            },
            "collection_progress": {
                "paper_fill_rows": 0,
            },
            "launch_readiness": {
                "blocking_gates": [
                    {
                        "gate": "real_paper_lifecycle_rows",
                        "blocker": "real_paper_lifecycle_rows_missing",
                        "next_action": "apply_paper_bridge_only_after_fresh_signal_and_verified_backup",
                    }
                ],
                "operator_commands": {
                    "paper_bridge_dry_run": "dry-run",
                    "paper_apply_only_after_fresh_signal": "paper-apply",
                },
            },
        },
        progress={},
        runtime_progress={},
        risk_caps={},
        microstructure_watch={},
        operator_handoff={
            "paper_apply_allowed_now": False,
            "paper_handoff_status": "blocked_waiting_for_fresh_signal",
            "paper_dry_run_command": "dry-run",
            "paper_apply_command": "paper-apply",
        },
    )

    item = plan[0]
    assert item["gate"] == "real_paper_lifecycle_rows"
    assert item["can_resolve_now"] is False
    assert item["command"] is None
    assert item["monitor_command"] == "monitor-signal"
    assert item["paper_apply_command_when_gate_allows"] == "paper-apply"
    assert item["reason"] == "must_wait_for_fresh_signal_before_paper_bridge_apply"
    assert item["fresh_signal"] is False
    assert item["order_submission_allowed"] is False
    assert item["no_live_order_sent"] is True


def test_blocker_plan_surfaces_paper_apply_command_only_when_gate_allows() -> None:
    plan = watch._blocker_resolution_plan(
        latest={
            "paper_bridge_apply_gate": {
                "fresh_signal": True,
                "can_request_paper_apply_now": True,
            },
            "collection_progress": {
                "paper_fill_rows": 0,
            },
            "launch_readiness": {
                "blocking_gates": [
                    {
                        "gate": "real_paper_lifecycle_rows",
                        "blocker": "real_paper_lifecycle_rows_missing",
                        "next_action": "apply_paper_bridge_only_after_fresh_signal_and_verified_backup",
                    }
                ],
                "operator_commands": {
                    "paper_bridge_dry_run": "dry-run",
                    "paper_apply_only_after_fresh_signal": "paper-apply",
                },
            },
        },
        progress={},
        runtime_progress={},
        risk_caps={},
        microstructure_watch={},
        operator_handoff={
            "paper_apply_allowed_now": True,
            "paper_handoff_status": "paper_apply_review_available",
            "paper_dry_run_command": "dry-run",
            "paper_apply_command": "paper-apply",
        },
    )

    item = plan[0]
    assert item["gate"] == "real_paper_lifecycle_rows"
    assert item["can_resolve_now"] is True
    assert item["requires_operator_review"] is True
    assert item["command"] == "paper-apply"
    assert item["reason"] == "paper_bridge_apply_available_after_operator_review_and_verified_backup"
    assert item["fresh_signal"] is True
    assert item["can_request_paper_apply_now"] is True
    assert item["order_submission_allowed"] is False


def test_safe_next_action_prioritizes_current_microstructure_capture() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "current_fresh_signal",
                "command": "monitor-signal",
                "reason": "must_wait_for_realtime_v6_add_or_remove_signal_do_not_force_entry",
            },
            {
                "gate": "real_microstructure_execution_evidence",
                "can_resolve_now": True,
                "command": "capture-quote",
                "reason": "collect_current_missing_utc_hour_now",
                "coverage_plan": {
                    "next_missing_utc_hour": "12",
                    "remaining_distinct_hours": 14,
                    "remaining_calendar_days": 28,
                },
            },
            {
                "gate": "shadow_runtime_24h_observed",
                "reason": "requires_calendar_runtime_observation_not_backtest_substitution",
            },
        ],
        runtime_progress={"remaining_hours": 22.0, "progress_pct": 8.0},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    assert plan["status"] == "safe_actions_available"
    assert plan["primary_action"]["action_type"] == "capture_microstructure_quote_window_now"
    assert plan["primary_action"]["command"] == "capture-quote"
    assert plan["primary_action"]["order_submission_allowed"] is False
    assert [item["action_type"] for item in plan["actions"]][:2] == [
        "capture_microstructure_quote_window_now",
        "monitor_fresh_signal",
    ]


def test_safe_next_action_uses_signal_monitor_when_quote_window_waits() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "current_fresh_signal",
                "command": "monitor-signal",
                "reason": "must_wait_for_realtime_v6_add_or_remove_signal_do_not_force_entry",
            },
            {
                "gate": "real_microstructure_execution_evidence",
                "can_resolve_now": False,
                "reason": "requires_new_calendar_days_or_missing_utc_hour_windows",
                "coverage_plan": {
                    "next_missing_utc_at": "2026-01-01T12:00:00+00:00",
                    "next_missing_kst_at": "2026-01-01T21:00:00+09:00",
                    "wait_minutes": 30.0,
                    "remaining_distinct_hours": 14,
                    "remaining_calendar_days": 28,
                },
            },
            {
                "gate": "tiny_canary_risk_caps_configured",
                "reason": "missing_optional_config_file",
                "quick_audit_command": "audit-caps",
                "errors": ["canary_risk_caps_json_required"],
            },
        ],
        runtime_progress={"remaining_hours": 22.0, "progress_pct": 8.0},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    assert plan["status"] == "safe_actions_available"
    assert plan["primary_action"]["action_type"] == "monitor_fresh_signal"
    assert plan["primary_action"]["command"] == "monitor-signal"
    assert all("can_start_now" in item for item in plan["actions"])
    assert all("waits_until_execution_window" in item for item in plan["actions"])
    wait_action = next(item for item in plan["actions"] if item["action_type"] == "wait_for_next_microstructure_quote_window")
    assert wait_action["can_run_now"] is False
    assert wait_action["can_start_now"] is True
    assert wait_action["waits_until_execution_window"] is True
    assert wait_action["execute_after_utc"] == "2026-01-01T12:00:00+00:00"
    assert wait_action["execute_after_kst"] == "2026-01-01T21:00:00+09:00"
    assert plan["next_scheduled_action"]["action_type"] == "wait_for_next_microstructure_quote_window"
    assert plan["next_startable_wait_action"]["action_type"] == "wait_for_next_microstructure_quote_window"
    assert plan["startable_action_count"] >= 1
    assert any(item["action_type"] == "audit_canary_risk_caps" for item in plan["actions"])
    assert plan["order_submission_allowed"] is False
    assert plan["no_live_order_sent"] is True


def test_safe_next_action_waits_for_next_quote_coverage_when_calendar_day_is_earlier() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "real_microstructure_execution_evidence",
                "can_resolve_now": False,
                "reason": "requires_new_calendar_days_or_missing_utc_hour_windows",
                "coverage_plan": {
                    "next_quote_coverage_kind": "next_utc_calendar_day",
                    "next_quote_coverage_at": "2026-01-02T00:00:00+00:00",
                    "next_quote_coverage_kst_at": "2026-01-02T09:00:00+09:00",
                    "next_quote_coverage_wait_minutes": 5.0,
                    "next_missing_utc_at": "2026-01-02T03:00:00+00:00",
                    "next_missing_kst_at": "2026-01-02T12:00:00+09:00",
                    "next_missing_utc_hour": "03",
                    "wait_minutes": 185.0,
                    "remaining_distinct_hours": 1,
                    "remaining_calendar_days": 1,
                },
            },
            {
                "gate": "shadow_runtime_24h_observed",
                "reason": "requires_calendar_runtime_observation_not_backtest_substitution",
            },
        ],
        runtime_progress={"remaining_hours": 22.0, "progress_pct": 8.0},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 23, 55, tzinfo=UTC),
    )

    action = plan["primary_action"]
    assert action["action_type"] == "wait_for_next_microstructure_quote_window"
    assert action["reason"] == "wait_until_next_quote_coverage_window"
    assert action["execute_after_utc"] == "2026-01-02T00:00:00+00:00"
    assert action["next_quote_coverage_kind"] == "next_utc_calendar_day"
    assert action["next_missing_utc_at"] == "2026-01-02T03:00:00+00:00"
    assert "--sleep-until-next-quote-coverage-window" in action["command"]
    assert "--max-pre-run-wait-seconds 3600" in action["command"]
    assert action["no_live_order_sent"] is True


def test_safe_next_action_waits_until_signal_monitor_cadence() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "current_fresh_signal",
                "command": "monitor-signal",
                "reason": "must_wait_for_realtime_v6_add_or_remove_signal_do_not_force_entry",
                "next_monitor_after_utc": "2026-01-01T12:15:00+00:00",
                "next_monitor_after_kst": "2026-01-01T21:15:00+09:00",
                "recommended_monitor_interval_minutes": 15,
                "cadence_lag_level": "extended_signal_drought",
            },
            {
                "gate": "shadow_runtime_24h_observed",
                "reason": "requires_calendar_runtime_observation_not_backtest_substitution",
            },
        ],
        runtime_progress={"remaining_hours": 22.0, "progress_pct": 8.0},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    monitor = next(item for item in plan["actions"] if item["action_type"] == "monitor_fresh_signal")
    assert monitor["can_run_now"] is False
    assert monitor["reason"] == "wait_until_signal_monitor_cadence"
    assert monitor["execute_after_utc"] == "2026-01-01T12:15:00+00:00"
    assert monitor["wait_minutes"] == 15.0
    assert monitor["recommended_monitor_interval_minutes"] == 15
    assert plan["next_scheduled_action"]["action_type"] == "monitor_fresh_signal"
    assert plan["next_startable_wait_action"] is None
    assert plan["primary_action"]["action_type"] == "continue_no_live_shadow_watch"
    assert plan["primary_action"]["can_run_now"] is True


def test_safe_next_action_prioritizes_earlier_monitor_before_startable_quote_window_wait() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "current_fresh_signal",
                "command": "monitor-signal",
                "reason": "must_wait_for_realtime_v6_add_or_remove_signal_do_not_force_entry",
                "next_monitor_after_utc": "2026-01-01T12:15:00+00:00",
            },
            {
                "gate": "real_microstructure_execution_evidence",
                "can_resolve_now": False,
                "reason": "requires_new_calendar_days_or_missing_utc_hour_windows",
                "coverage_plan": {
                    "next_missing_utc_at": "2026-01-01T12:30:00+00:00",
                    "next_missing_kst_at": "2026-01-01T21:30:00+09:00",
                    "wait_minutes": 180.0,
                    "remaining_distinct_hours": 6,
                    "remaining_calendar_days": 28,
                },
            },
            {
                "gate": "real_paper_lifecycle_rows",
                "fresh_signal": False,
                "monitor_command": "monitor-signal",
                "next_monitor_after_utc": "2026-01-01T12:15:00+00:00",
                "reason": "must_wait_for_fresh_signal_before_paper_bridge_apply",
            },
            {
                "gate": "shadow_runtime_24h_observed",
                "reason": "requires_calendar_runtime_observation_not_backtest_substitution",
            },
        ],
        runtime_progress={"remaining_hours": 16.0, "progress_pct": 33.0},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    assert plan["status"] == "waiting_for_earlier_scheduled_action_before_quote_window_wait"
    assert plan["primary_action"]["action_type"] == "monitor_fresh_signal"
    assert plan["primary_action"]["execute_after_utc"] == "2026-01-01T12:15:00+00:00"
    assert plan["next_startable_wait_action"]["action_type"] == "wait_for_next_microstructure_quote_window"
    assert plan["next_startable_wait_action"]["execute_after_utc"] == "2026-01-01T12:30:00+00:00"
    assert "--max-pre-run-wait-seconds 10920" in plan["next_startable_wait_action"]["command"]
    assert plan["pre_wait_scheduled_action_count"] == 1
    assert plan["pre_wait_scheduled_actions"][0]["action_type"] == "monitor_fresh_signal"
    assert any(item["action_type"] == "paper_bridge_wait_for_fresh_signal" for item in plan["actions"])
    assert plan["coordination_warnings"] == []
    assert any(item["action_type"] == "continue_no_live_shadow_watch" for item in plan["actions"])
    assert plan["no_live_order_sent"] is True


def test_safe_next_action_materializes_signal_monitor_placeholder() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "current_fresh_signal",
                "command": (
                    ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                    "--quote-samples-per-tick 0 --report-dir "
                    "reports/validation/diagnostics/<signal_monitor_report_dir>"
                ),
                "reason": "must_wait_for_realtime_v6_add_or_remove_signal_do_not_force_entry",
            }
        ],
        runtime_progress={"remaining_hours": 22.0, "progress_pct": 8.0},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    command = plan["primary_action"]["command"]
    assert "<signal_monitor_report_dir>" not in command
    assert "market_state_rotation_v6_launch_monitor_fresh_signal_20260101_120000Z" in command
    assert "raw_command" not in plan["primary_action"]


def test_blocker_plan_marks_microstructure_time_coverage_as_wait_required() -> None:
    plan = watch._blocker_resolution_plan(
        latest={
            "launch_readiness": {
                "blocking_gates": [
                    {
                        "gate": "real_microstructure_execution_evidence",
                        "blocker": "real_spread_slippage_latency_gates_pending",
                        "next_action": "collect_l2_quote_shadow_and_paper_fill_microstructure_until_p95_gates_pass",
                    }
                ],
                "operator_commands": {"microstructure_quote_capture": "capture"},
            }
        },
        progress={},
        runtime_progress={},
        risk_caps={},
        microstructure_watch={
            "status": "collecting_sample_day_hour_coverage",
            "blockers": ["calendar_days_missing", "distinct_hours_missing"],
            "metric_blockers": [],
            "coverage": {
                "utc_hour_of_day_covered_count": 9,
                "utc_hour_of_day_missing": ["11", "12"],
                "latest_sample_age_hours": 0.1,
            },
        },
        operator_handoff={"quote_capture_command": "capture"},
    )

    item = plan[0]
    assert item["gate"] == "real_microstructure_execution_evidence"
    assert item["can_resolve_now"] is False
    assert item["reason"] == "requires_new_calendar_days_or_missing_utc_hour_windows"
    assert item["sample_blockers"] == ["calendar_days_missing", "distinct_hours_missing"]
    assert item["missing_utc_hour_of_day"] == ["11", "12"]


def test_microstructure_coverage_plan_collects_current_missing_hour_now() -> None:
    generated_at = datetime(2026, 1, 1, 11, 35, tzinfo=UTC)

    plan = watch._microstructure_coverage_plan(
        coverage={
            "utc_hour_of_day_covered_count": 22,
            "utc_hour_of_day_missing": ["11", "12"],
            "latest_sample_age_hours": 0.1,
        },
        latest_collection={
            "quote_observed": 300,
            "quote_required": 300,
            "quote_calendar_days": 28,
            "quote_min_calendar_days": 30,
            "quote_distinct_hours": 22,
            "quote_min_distinct_hours": 24,
        },
        microstructure_watch={
            "calendar_day_count": 28,
            "min_calendar_days": 30,
            "calendar_days": ["2026-01-01"],
        },
        generated_at=generated_at,
        quote_capture_command="capture",
    )

    assert plan["status"] == "current_missing_utc_hour_open"
    assert plan["current_utc_hour"] == "11"
    assert plan["current_utc_hour_missing"] is True
    assert plan["next_missing_utc_hour"] == "11"
    assert plan["wait_minutes"] == 0.0
    assert plan["remaining_calendar_days"] == 2
    assert plan["remaining_distinct_hours"] == 2
    assert plan["can_collect_now"] is True
    assert plan["recommended_action"] == "collect_current_missing_utc_hour_now"


def test_microstructure_coverage_plan_prefers_next_utc_day_before_later_missing_hour() -> None:
    generated_at = datetime(2026, 1, 1, 23, 55, tzinfo=UTC)

    plan = watch._microstructure_coverage_plan(
        coverage={
            "utc_hour_of_day_covered_count": 23,
            "utc_hour_of_day_missing": ["03"],
            "latest_sample_age_hours": 0.1,
        },
        latest_collection={
            "quote_observed": 300,
            "quote_required": 300,
            "quote_calendar_days": 1,
            "quote_min_calendar_days": 2,
            "quote_distinct_hours": 23,
            "quote_min_distinct_hours": 24,
        },
        microstructure_watch={
            "calendar_day_count": 1,
            "min_calendar_days": 2,
            "calendar_days": ["2026-01-01"],
            "distinct_hour_count": 23,
            "min_distinct_hours": 24,
            "eligible_row_count": 300,
            "required_quote_samples": 300,
        },
        generated_at=generated_at,
        quote_capture_command="capture",
    )

    assert plan["status"] == "waiting_for_next_quote_coverage_window"
    assert plan["next_quote_coverage_kind"] == "next_utc_calendar_day"
    assert plan["next_quote_coverage_at"] == "2026-01-02T00:00:00+00:00"
    assert plan["next_missing_utc_at"] == "2026-01-02T03:00:00+00:00"
    assert plan["next_quote_coverage_wait_minutes"] == 5.0
    assert plan["recommended_action"] == "wait_until_next_quote_coverage_window"


def test_microstructure_coverage_plan_collects_current_utc_day_now() -> None:
    generated_at = datetime(2026, 1, 2, 0, 5, tzinfo=UTC)

    plan = watch._microstructure_coverage_plan(
        coverage={
            "utc_hour_of_day_covered_count": 23,
            "utc_hour_of_day_missing": ["03"],
            "latest_sample_age_hours": 0.1,
        },
        latest_collection={
            "quote_observed": 300,
            "quote_required": 300,
            "quote_calendar_days": 1,
            "quote_min_calendar_days": 2,
            "quote_distinct_hours": 23,
            "quote_min_distinct_hours": 24,
        },
        microstructure_watch={
            "calendar_day_count": 1,
            "min_calendar_days": 2,
            "calendar_days": ["2026-01-01"],
            "distinct_hour_count": 23,
            "min_distinct_hours": 24,
            "eligible_row_count": 300,
            "required_quote_samples": 300,
        },
        generated_at=generated_at,
        quote_capture_command="capture",
    )

    assert plan["status"] == "current_utc_calendar_day_open"
    assert plan["current_utc_date"] == "2026-01-02"
    assert plan["current_utc_date_missing"] is True
    assert plan["next_quote_coverage_kind"] == "current_utc_calendar_day"
    assert plan["next_quote_coverage_at"] == "2026-01-02T00:05:00+00:00"
    assert plan["can_collect_now"] is True
    assert plan["recommended_action"] == "collect_current_utc_calendar_day_now"


def test_blocker_plan_marks_current_microstructure_hour_as_resolvable_now() -> None:
    plan = watch._blocker_resolution_plan(
        latest={
            "launch_readiness": {
                "blocking_gates": [
                    {
                        "gate": "real_microstructure_execution_evidence",
                        "blocker": "real_spread_slippage_latency_gates_pending",
                        "next_action": "collect_l2_quote_shadow_and_paper_fill_microstructure_until_p95_gates_pass",
                    }
                ],
                "operator_commands": {"microstructure_quote_capture": "capture"},
            }
        },
        progress={},
        runtime_progress={},
        risk_caps={},
        microstructure_watch={
            "status": "collecting_sample_day_hour_coverage",
            "blockers": ["calendar_days_missing", "distinct_hours_missing"],
            "metric_blockers": [],
            "coverage": {
                "utc_hour_of_day_covered_count": 22,
                "utc_hour_of_day_missing": ["11", "12"],
                "latest_sample_age_hours": 0.1,
            },
            "coverage_plan": {
                "current_utc_hour_missing": True,
                "next_missing_utc_hour": "11",
                "next_missing_utc_at": "2026-01-01T11:35:00+00:00",
                "next_missing_kst_at": "2026-01-01T20:35:00+09:00",
                "wait_minutes": 0.0,
                "remaining_calendar_days": 2,
                "remaining_distinct_hours": 2,
                "remaining_quote_samples": 0,
            },
        },
        operator_handoff={"quote_capture_command": "capture"},
    )

    item = plan[0]
    assert item["gate"] == "real_microstructure_execution_evidence"
    assert item["can_resolve_now"] is True
    assert item["reason"] == "collect_current_missing_utc_hour_now"
    assert item["next_missing_utc_hour"] == "11"
    assert item["wait_minutes"] == 0.0


def test_blocker_plan_marks_current_microstructure_calendar_day_as_resolvable_now() -> None:
    plan = watch._blocker_resolution_plan(
        latest={
            "launch_readiness": {
                "blocking_gates": [
                    {
                        "gate": "real_microstructure_execution_evidence",
                        "blocker": "real_spread_slippage_latency_gates_pending",
                        "next_action": "collect_l2_quote_shadow_and_paper_fill_microstructure_until_p95_gates_pass",
                    }
                ],
                "operator_commands": {"microstructure_quote_capture": "capture"},
            }
        },
        progress={},
        runtime_progress={},
        risk_caps={},
        microstructure_watch={
            "status": "collecting_sample_day_hour_coverage",
            "blockers": ["calendar_days_missing", "distinct_hours_missing"],
            "metric_blockers": [],
            "coverage": {
                "utc_hour_of_day_covered_count": 23,
                "utc_hour_of_day_missing": ["03"],
                "latest_sample_age_hours": 0.1,
            },
            "coverage_plan": {
                "current_utc_date": "2026-01-02",
                "current_utc_date_missing": True,
                "current_utc_hour_missing": False,
                "next_quote_coverage_kind": "current_utc_calendar_day",
                "next_quote_coverage_at": "2026-01-02T00:05:00+00:00",
                "next_quote_coverage_kst_at": "2026-01-02T09:05:00+09:00",
                "next_quote_coverage_wait_minutes": 0.0,
                "next_missing_utc_hour": "03",
                "next_missing_utc_at": "2026-01-02T03:00:00+00:00",
                "wait_minutes": 175.0,
                "remaining_calendar_days": 1,
                "remaining_distinct_hours": 1,
                "remaining_quote_samples": 0,
            },
        },
        operator_handoff={"quote_capture_command": "capture"},
    )

    item = plan[0]
    assert item["gate"] == "real_microstructure_execution_evidence"
    assert item["can_resolve_now"] is True
    assert item["reason"] == "collect_current_utc_calendar_day_now"
    assert item["current_utc_date_missing"] is True
    assert item["next_quote_coverage_kind"] == "current_utc_calendar_day"


def test_blocker_plan_includes_canary_risk_caps_quick_audit_command() -> None:
    plan = watch._blocker_resolution_plan(
        latest={
            "launch_readiness": {
                "blocking_gates": [
                    {
                        "gate": "tiny_canary_risk_caps_configured",
                        "blocker": "canary_notional_daily_loss_or_leverage_caps_missing",
                        "next_action": "set_explicit_tiny_canary_notional_leverage_and_daily_loss_caps",
                    }
                ]
            }
        },
        progress={},
        runtime_progress={},
        risk_caps={
            "status": "missing_optional_config_file",
            "errors": ["canary_risk_caps_json_required"],
            "operator_review": {
                "target_config_path": "reports/operations/market_state_rotation_v6_canary_risk_caps.json",
                "quick_audit_command": "quick-audit",
                "validation_command": "evidence-validation",
            },
        },
        microstructure_watch={},
        operator_handoff={},
    )

    item = plan[0]
    assert item["gate"] == "tiny_canary_risk_caps_configured"
    assert item["requires_operator_review"] is True
    assert item["quick_audit_command"] == "quick-audit"
    assert item["validation_command"] == "evidence-validation"
    assert item["no_live_order_sent"] is True


def test_pre_run_quote_window_wait_plan_sleeps_within_limit() -> None:
    plan = watch._pre_run_quote_window_wait_plan(
        previous_payload={
            "microstructure_watch": {
                "coverage_plan": {
                    "status": "waiting_for_next_missing_utc_hour_or_new_calendar_day",
                    "can_collect_now": False,
                    "current_utc_hour_missing": False,
                    "missing_utc_hour_of_day": ["12"],
                    "next_missing_utc_hour": "12",
                    "next_missing_utc_at": "2026-01-01T12:00:00+00:00",
                }
            }
        },
        generated_at=datetime(2026, 1, 1, 11, 55, tzinfo=UTC),
        enabled=True,
        max_wait_seconds=600.0,
        wakeup_buffer_seconds=5.0,
    )

    assert plan["status"] == "sleep_until_next_quote_coverage_window"
    assert plan["should_sleep"] is True
    assert plan["wait_seconds"] == 305.0
    assert plan["next_missing_utc_hour"] == "12"
    assert plan["current_utc_hour"] == "11"
    assert plan["current_utc_hour_missing"] is False
    assert plan["no_live_order_sent"] is True


def test_pre_run_quote_window_wait_plan_prefers_next_calendar_day_before_missing_hour() -> None:
    plan = watch._pre_run_quote_window_wait_plan(
        previous_payload={
            "microstructure_watch": {
                "coverage_plan": {
                    "status": "waiting_for_next_quote_coverage_window",
                    "can_collect_now": False,
                    "current_utc_date": "2026-01-01",
                    "current_utc_date_missing": False,
                    "covered_calendar_days": ["2026-01-01"],
                    "remaining_calendar_days": 1,
                    "current_utc_hour_missing": False,
                    "missing_utc_hour_of_day": ["03"],
                    "next_quote_coverage_kind": "next_utc_calendar_day",
                    "next_quote_coverage_at": "2026-01-02T00:00:00+00:00",
                    "next_quote_coverage_kst_at": "2026-01-02T09:00:00+09:00",
                    "next_missing_utc_hour": "03",
                    "next_missing_utc_at": "2026-01-02T03:00:00+00:00",
                    "next_missing_kst_at": "2026-01-02T12:00:00+09:00",
                    "calendar_day_count": 1,
                }
            }
        },
        generated_at=datetime(2026, 1, 1, 23, 55, tzinfo=UTC),
        enabled=True,
        max_wait_seconds=600.0,
        wakeup_buffer_seconds=5.0,
    )

    assert plan["status"] == "sleep_until_next_quote_coverage_window"
    assert plan["should_sleep"] is True
    assert plan["wait_seconds"] == 305.0
    assert plan["next_quote_coverage_kind"] == "next_utc_calendar_day"
    assert plan["next_quote_coverage_at"] == "2026-01-02T00:00:00+00:00"
    assert plan["next_missing_utc_at"] == "2026-01-02T03:00:00+00:00"
    assert plan["target_utc_date"] == "2026-01-02"
    assert plan["no_live_order_sent"] is True


def test_pre_run_quote_window_wait_plan_recomputes_current_hour_from_missing_list() -> None:
    plan = watch._pre_run_quote_window_wait_plan(
        previous_payload={
            "microstructure_watch": {
                "coverage_plan": {
                    "status": "waiting_for_next_quote_coverage_window",
                    "can_collect_now": False,
                    "current_utc_hour_missing": True,
                    "missing_utc_hour_of_day": ["12"],
                    "next_missing_utc_hour": "12",
                    "next_missing_utc_at": "2026-01-01T12:00:00+00:00",
                }
            }
        },
        generated_at=datetime(2026, 1, 1, 11, 55, tzinfo=UTC),
        enabled=True,
        max_wait_seconds=600.0,
        wakeup_buffer_seconds=5.0,
    )

    assert plan["status"] == "sleep_until_next_quote_coverage_window"
    assert plan["current_utc_hour"] == "11"
    assert plan["current_utc_hour_missing"] is False


def test_pre_run_quote_window_wait_plan_does_not_sleep_beyond_limit() -> None:
    plan = watch._pre_run_quote_window_wait_plan(
        previous_payload={
            "microstructure_watch": {
                "coverage_plan": {
                    "status": "waiting_for_next_quote_coverage_window",
                    "can_collect_now": False,
                    "current_utc_hour_missing": False,
                    "missing_utc_hour_of_day": ["12"],
                    "next_missing_utc_hour": "12",
                    "next_missing_utc_at": "2026-01-01T12:00:00+00:00",
                }
            }
        },
        generated_at=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        enabled=True,
        max_wait_seconds=300.0,
        wakeup_buffer_seconds=5.0,
    )

    assert plan["status"] == "next_quote_window_wait_exceeds_limit"
    assert plan["should_sleep"] is False
    assert plan["reason"] == "rerun_later_or_raise_max_pre_run_wait_seconds"


def test_pre_run_quote_window_wait_plan_opens_when_current_hour_is_missing() -> None:
    plan = watch._pre_run_quote_window_wait_plan(
        previous_payload={
            "microstructure_watch": {
                "coverage_plan": {
                    "status": "waiting_for_next_missing_utc_hour_or_new_calendar_day",
                    "can_collect_now": False,
                    "current_utc_hour_missing": False,
                    "missing_utc_hour_of_day": ["12"],
                    "next_missing_utc_hour": "12",
                    "next_missing_utc_at": "2026-01-01T12:00:00+00:00",
                }
            }
        },
        generated_at=datetime(2026, 1, 1, 12, 5, tzinfo=UTC),
        enabled=True,
        max_wait_seconds=3600.0,
        wakeup_buffer_seconds=5.0,
    )

    assert plan["status"] == "current_quote_window_open"
    assert plan["should_sleep"] is False
    assert plan["wait_seconds"] == 0.0
    assert plan["current_utc_hour"] == "12"
    assert plan["current_utc_hour_missing"] is True
    assert plan["reason"] == "current_utc_hour_can_advance_microstructure_coverage"


def test_pre_run_quote_window_wait_plan_marks_elapsed_non_current_window_stale() -> None:
    plan = watch._pre_run_quote_window_wait_plan(
        previous_payload={
            "microstructure_watch": {
                "coverage_plan": {
                    "status": "waiting_for_next_missing_utc_hour_or_new_calendar_day",
                    "can_collect_now": False,
                    "current_utc_hour_missing": False,
                    "missing_utc_hour_of_day": ["12"],
                    "next_missing_utc_hour": "12",
                    "next_missing_utc_at": "2026-01-01T12:00:00+00:00",
                }
            }
        },
        generated_at=datetime(2026, 1, 1, 13, 5, tzinfo=UTC),
        enabled=True,
        max_wait_seconds=3600.0,
        wakeup_buffer_seconds=5.0,
    )

    assert plan["status"] == "next_quote_coverage_window_reached_or_previous_plan_stale"
    assert plan["should_sleep"] is False
    assert plan["wait_seconds"] == 0.0
    assert plan["current_utc_hour"] == "13"
    assert plan["current_utc_hour_missing"] is False
    assert plan["reason"] == "run_watch_now_to_recompute_or_capture_current_quote_coverage_window"


def test_finalize_pre_run_quote_window_sleep_marks_on_time_wakeup() -> None:
    finalized = watch._finalize_pre_run_quote_window_sleep(
        {
            "status": "sleep_until_next_missing_quote_window",
            "should_sleep": True,
            "wait_seconds": 305.0,
            "next_missing_utc_at": "2026-01-01T12:00:00+00:00",
            "next_missing_utc_hour": "12",
            "no_live_order_sent": True,
        },
        sleep_started_at=datetime(2026, 1, 1, 11, 55, tzinfo=UTC),
        woke_at=datetime(2026, 1, 1, 12, 0, 5, tzinfo=UTC),
    )

    assert finalized["actual_sleep_seconds"] == 305.0
    assert finalized["target_window_start_utc"] == "2026-01-01T12:00:00+00:00"
    assert finalized["target_window_end_utc"] == "2026-01-01T13:00:00+00:00"
    assert finalized["wakeup_lag_seconds"] == 5.0
    assert finalized["target_window_missed"] is False
    assert finalized["overshoot_seconds"] == 0.0
    assert finalized["recovery_action"] is None
    assert finalized["no_live_order_sent"] is True


def test_finalize_pre_run_quote_window_sleep_marks_missed_target_window() -> None:
    finalized = watch._finalize_pre_run_quote_window_sleep(
        {
            "status": "sleep_until_next_missing_quote_window",
            "should_sleep": True,
            "wait_seconds": 305.0,
            "next_missing_utc_at": "2026-01-01T12:00:00+00:00",
            "next_missing_utc_hour": "12",
            "no_live_order_sent": True,
        },
        sleep_started_at=datetime(2026, 1, 1, 11, 55, tzinfo=UTC),
        woke_at=datetime(2026, 1, 1, 14, 5, tzinfo=UTC),
    )

    assert finalized["actual_sleep_seconds"] == 7800.0
    assert finalized["target_window_missed"] is True
    assert finalized["target_window_missed_reason"] == "woke_after_target_window_end"
    assert finalized["wakeup_lag_minutes"] == 125.0
    assert finalized["overshoot_minutes"] == 65.0
    assert finalized["recovery_action"] == "rerun_watch_now_to_capture_current_missing_hour_and_recompute_missed_hours"
    assert finalized["no_live_order_sent"] is True


def test_pre_run_quote_window_capture_outcome_marks_calendar_day_captured() -> None:
    outcome = watch._pre_run_quote_window_capture_outcome(
        pre_run_wait_plan={
            "status": "sleep_until_next_quote_coverage_window",
            "should_sleep": True,
            "actual_sleep_seconds": 305.0,
            "next_quote_coverage_kind": "next_utc_calendar_day",
            "next_quote_coverage_at": "2026-01-02T00:00:00+00:00",
            "calendar_day_count": 1,
            "covered_calendar_days": ["2026-01-01"],
            "target_window_missed": False,
            "no_live_order_sent": True,
        },
        latest_collection={
            "quote_calendar_days": 2,
            "captured_quote_rows_this_cycle": 2,
        },
    )

    assert outcome["status"] == "target_calendar_day_captured"
    assert outcome["target_quote_coverage_kind"] == "next_utc_calendar_day"
    assert outcome["target_utc_date"] == "2026-01-02"
    assert outcome["previous_quote_calendar_days"] == 1
    assert outcome["current_quote_calendar_days"] == 2
    assert outcome["target_calendar_day_covered"] is True
    assert outcome["no_live_order_sent"] is True


def test_pre_run_quote_window_wait_incident_log_appends_missed_window() -> None:
    log = watch._pre_run_quote_window_wait_incident_log(
        previous_payload={
            "pre_run_quote_window_wait_incident_log": [
                {
                    "incident_type": "pre_run_quote_window_target_missed",
                    "woke_at": "2026-01-01T01:00:00+00:00",
                    "no_live_order_sent": True,
                }
            ]
        },
        current_plan={
            "target_window_missed": True,
            "target_window_start_utc": "2026-01-01T12:00:00+00:00",
            "target_window_end_utc": "2026-01-01T13:00:00+00:00",
            "next_missing_utc_hour": "12",
            "sleep_started_at": "2026-01-01T11:55:00+00:00",
            "woke_at": "2026-01-01T14:05:00+00:00",
            "actual_sleep_seconds": 7800.0,
            "wakeup_lag_seconds": 7500.0,
            "overshoot_seconds": 3900.0,
            "overshoot_minutes": 65.0,
            "recovery_action": "rerun_watch_now_to_capture_current_missing_hour_and_recompute_missed_hours",
        },
    )

    assert len(log) == 2
    assert log[-1]["incident_type"] == "pre_run_quote_window_target_missed"
    assert log[-1]["next_missing_utc_hour"] == "12"
    assert log[-1]["overshoot_minutes"] == 65.0
    assert log[-1]["no_live_order_sent"] is True


def test_pre_run_quote_window_wait_incident_log_preserves_previous_when_no_new_incident() -> None:
    log = watch._pre_run_quote_window_wait_incident_log(
        previous_payload={
            "pre_run_quote_window_wait_incident_log": [
                {"incident_type": f"incident_{idx}", "no_live_order_sent": True}
                for idx in range(3)
            ]
        },
        current_plan={"target_window_missed": False},
        max_items=2,
    )

    assert [item["incident_type"] for item in log] == ["incident_1", "incident_2"]


def test_launch_shadow_watch_refreshes_market_data_after_quote_window_sleep(monkeypatch, tmp_path) -> None:
    args = _args(tmp_path)
    args.iterations = 1
    args.sleep_until_next_missing_quote_window = True
    args.max_pre_run_wait_seconds = 7200.0
    args.target_hours = 24.0
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    current_hour = f"{now.hour:02d}"
    next_hour = f"{(now.hour + 1) % 24:02d}"
    next_missing_utc_at = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).isoformat()
    (report_dir / "latest.json").write_text(
        json.dumps(
            {
                "started_at": (now - timedelta(hours=1)).isoformat(),
                "completed_at": (now - timedelta(minutes=5)).isoformat(),
                "no_live_order_sent": True,
                "microstructure_watch": {
                    "coverage_plan": {
                        "status": "waiting_for_next_missing_utc_hour_or_new_calendar_day",
                        "can_collect_now": False,
                        "missing_utc_hour_of_day": [next_hour],
                        "next_missing_utc_at": next_missing_utc_at,
                        "next_missing_utc_hour": next_hour,
                        "current_utc_hour": current_hour,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    evidence_calls = []
    refresh_calls = []

    def fake_run_evidence_cycle(**kwargs):
        evidence_calls.append(kwargs)
        return {
            "overall_status": "healthy_abstention_waiting_for_quality_signal",
            "no_live_order_sent": True,
            "collection_progress": {
                "quote_observed": 330,
                "quote_distinct_hours": 15,
                "captured_quote_rows_this_cycle": 2,
                "paper_fill_rows": 0,
                "quote_coverage": {
                    "utc_hour_of_day_covered": [next_hour],
                    "utc_hour_of_day_missing": [],
                },
            },
            "readiness_progress": {},
            "paper_bridge_apply_gate": {"fresh_signal": False, "can_request_paper_apply_now": False},
            "quote_cadence_preflight": {},
            "market_data_refresh_plan": {"status": "fresh", "fresh_market_data": True},
            "signal_wait_plan": {},
            "launch_readiness": {"status": "research_ready_waiting_for_fresh_signal", "blocking_gates": []},
            "historical_gate_substitution": {},
            "canary_risk_caps_config": {},
        }

    def fake_refresh(**kwargs):
        refresh_calls.append(kwargs)
        return {
            "status": "refreshed",
            "returncode": 0,
            "report_dir": "reports/validation/diagnostics/fake_refresh",
            "no_live_order_sent": True,
        }

    monkeypatch.setattr(watch, "run_evidence_cycle", fake_run_evidence_cycle)

    summary = watch.run_launch_shadow_watch(
        args,
        sleep_fn=lambda seconds: None,
        market_data_refresh_fn=fake_refresh,
    )

    assert len(refresh_calls) == 1
    assert refresh_calls[0]["evidence_root"] == Path(args.evidence_report_root)
    assert len(evidence_calls) == 1
    assert evidence_calls[0]["refresh_market_data_before_run"] is False
    assert summary["pre_run_quote_window_wait_plan"]["status"] == "sleep_until_next_quote_coverage_window"
    assert summary["pre_run_quote_window_capture_outcome"]["status"] == "target_hour_captured"
    assert summary["pre_run_quote_window_capture_outcome"]["target_utc_hour"] == next_hour
    assert summary["pre_run_quote_window_capture_outcome"]["captured_quote_rows_this_cycle"] == 2
    assert summary["pre_run_market_data_refresh"]["status"] == "refreshed"
    assert summary["pre_run_market_data_refresh"]["no_live_order_sent"] is True
    latest_md = (report_dir / "latest.md").read_text(encoding="utf-8")
    assert "pre_run_market_data_refresh_status: `refreshed`" in latest_md
    assert "pre_run_quote_window_capture_status: `target_hour_captured`" in latest_md


def test_launch_shadow_watch_reuses_previous_started_at_for_heartbeat_accumulation(monkeypatch, tmp_path) -> None:
    args = _args(tmp_path)
    args.iterations = 1
    args.target_hours = 24.0
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    prior_started_at = datetime.now(UTC) - timedelta(hours=2)
    (report_dir / "latest.json").write_text(
        json.dumps({"started_at": prior_started_at.isoformat(), "no_live_order_sent": True}),
        encoding="utf-8",
    )

    def fake_run_evidence_cycle(**kwargs):
        return {
            "overall_status": "healthy_abstention_waiting_for_quality_signal",
            "no_live_order_sent": True,
            "collection_progress": {"quote_observed": 80, "quote_distinct_hours": 8, "paper_fill_rows": 0},
            "readiness_progress": {},
            "paper_bridge_apply_gate": {"fresh_signal": False, "can_request_paper_apply_now": False},
            "signal_wait_plan": {},
            "launch_readiness": {"status": "research_ready_waiting_for_fresh_signal", "blocking_gates": []},
            "historical_gate_substitution": {},
            "canary_risk_caps_config": {},
        }

    monkeypatch.setattr(watch, "run_evidence_cycle", fake_run_evidence_cycle)

    summary = watch.run_launch_shadow_watch(args, sleep_fn=lambda seconds: None)

    assert summary["started_at"] == prior_started_at.isoformat()
    assert summary["observed_hours"] >= 1.9
    assert summary["runtime_observation"]["gap_reset"] is False


def test_historical_shadow_runtime_floor_uses_recent_launch_evidence(tmp_path) -> None:
    generated_at = datetime(2026, 1, 2, 0, 45, tzinfo=UTC)
    early_report_dir = tmp_path / "market_state_rotation_v6_launch_shadow_watch_20260101_120000_i001"
    early_report_dir.mkdir(parents=True)
    early_report = {
        "generated_at": datetime(2026, 1, 1, 12, 0, tzinfo=UTC).isoformat(),
        "launch_readiness": {
            "blocking_gates": [
                {
                    "gate": "shadow_runtime_24h_observed",
                    "detail": {"observed_hours": 0.1},
                }
            ]
        },
    }
    (early_report_dir / "market_state_rotation_v6_evidence_cycle.json").write_text(
        json.dumps(early_report),
        encoding="utf-8",
    )
    contaminated_report_dir = tmp_path / "market_state_rotation_v6_launch_shadow_watch_20260102_005500_i001"
    contaminated_report_dir.mkdir(parents=True)
    contaminated_report = {
        "generated_at": datetime(2026, 1, 2, 0, 55, tzinfo=UTC).isoformat(),
        "launch_readiness": {
            "blocking_gates": [
                {
                    "gate": "shadow_runtime_24h_observed",
                    "detail": {"observed_hours": 15.0},
                }
            ]
        },
    }
    (contaminated_report_dir / "market_state_rotation_v6_evidence_cycle.json").write_text(
        json.dumps(contaminated_report),
        encoding="utf-8",
    )
    report_dir = tmp_path / "market_state_rotation_v6_launch_shadow_watch_20260102_004500_i001"
    report_dir.mkdir(parents=True)
    report = {
        "generated_at": generated_at.isoformat(),
        "launch_readiness": {
            "blocking_gates": [
                {
                    "gate": "shadow_runtime_24h_observed",
                    "detail": {"observed_hours": 10.5},
                }
            ]
        },
    }
    (report_dir / "market_state_rotation_v6_evidence_cycle.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    floor = watch._historical_shadow_runtime_floor(
        evidence_root=tmp_path,
        current_at=datetime(2026, 1, 2, 1, 0, tzinfo=UTC),
        min_recovered_start_at=datetime(2026, 1, 1, 13, 0, tzinfo=UTC),
    )

    assert floor["status"] == "available"
    assert floor["source_observed_hours"] == 10.5
    assert floor["recovered_continuous_started_at"] == "2026-01-01T14:15:00+00:00"
    assert floor["projected_observed_hours"] == 10.75
    assert floor["no_live_order_sent"] is True


def test_continuous_runtime_start_recovers_recent_underflow_from_runtime_floor() -> None:
    current_at = datetime(2026, 1, 2, 1, 0, tzinfo=UTC)
    floor_start = datetime(2026, 1, 1, 14, 15, tzinfo=UTC)

    plan = watch._continuous_runtime_start(
        previous_payload={
            "completed_at": (current_at - timedelta(seconds=30)).isoformat(),
            "runtime_observation": {
                "continuous_started_at": (current_at - timedelta(minutes=1)).isoformat(),
                "gap_reset": False,
            },
        },
        fallback_started_at=current_at - timedelta(hours=15),
        current_at=current_at,
        interval_seconds=0.0,
        runtime_floor={
            "status": "available",
            "recovered_continuous_started_at": floor_start.isoformat(),
            "projected_observed_hours": 10.75,
            "source_report": "reports/validation/diagnostics/floor/market_state_rotation_v6_evidence_cycle.json",
            "no_live_order_sent": True,
        },
    )

    assert plan["continuous_started_at"] == floor_start
    assert plan["runtime_floor_recovered"] is True
    assert plan["gap_reset"] is False
    assert plan["runtime_floor"]["status"] == "available"


def test_continuous_runtime_start_replaces_weaker_prior_floor_recovery() -> None:
    current_at = datetime(2026, 1, 2, 1, 0, tzinfo=UTC)
    stronger_floor_start = datetime(2026, 1, 1, 14, 15, tzinfo=UTC)

    plan = watch._continuous_runtime_start(
        previous_payload={
            "completed_at": (current_at - timedelta(seconds=30)).isoformat(),
            "runtime_observation": {
                "continuous_started_at": datetime(2026, 1, 1, 9, 54, tzinfo=UTC).isoformat(),
                "gap_reset": False,
                "runtime_floor_recovered": True,
                "runtime_floor": {
                    "source_observed_hours": 0.02,
                    "recovered_continuous_started_at": datetime(2026, 1, 1, 9, 54, tzinfo=UTC).isoformat(),
                },
            },
        },
        fallback_started_at=current_at - timedelta(hours=15),
        current_at=current_at,
        interval_seconds=0.0,
        runtime_floor={
            "status": "available",
            "recovered_continuous_started_at": stronger_floor_start.isoformat(),
            "projected_observed_hours": 10.75,
            "source_observed_hours": 10.5,
            "no_live_order_sent": True,
        },
    )

    assert plan["continuous_started_at"] == stronger_floor_start
    assert plan["runtime_floor_recovered"] is True


def test_continuous_runtime_start_clamps_start_before_operation_to_floor() -> None:
    current_at = datetime(2026, 1, 2, 1, 0, tzinfo=UTC)
    operation_started_at = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    floor_start = datetime(2026, 1, 1, 14, 15, tzinfo=UTC)

    plan = watch._continuous_runtime_start(
        previous_payload={
            "completed_at": (current_at - timedelta(seconds=30)).isoformat(),
            "runtime_observation": {
                "continuous_started_at": datetime(2026, 1, 1, 9, 54, tzinfo=UTC).isoformat(),
                "gap_reset": False,
            },
        },
        fallback_started_at=operation_started_at,
        current_at=current_at,
        interval_seconds=0.0,
        runtime_floor={
            "status": "available",
            "recovered_continuous_started_at": floor_start.isoformat(),
            "projected_observed_hours": 10.75,
            "source_observed_hours": 10.5,
            "no_live_order_sent": True,
        },
    )

    assert plan["continuous_started_at"] == floor_start
    assert plan["runtime_floor_recovered"] is True
    assert plan["runtime_start_clamped_to_operation_start"] is True


def test_continuous_runtime_start_does_not_recover_floor_after_gap_warning() -> None:
    current_at = datetime(2026, 1, 2, 1, 0, tzinfo=UTC)

    plan = watch._continuous_runtime_start(
        previous_payload={
            "completed_at": (current_at - timedelta(hours=3)).isoformat(),
            "runtime_observation": {
                "continuous_started_at": (current_at - timedelta(hours=20)).isoformat(),
                "gap_reset": False,
            },
        },
        fallback_started_at=current_at - timedelta(hours=20),
        current_at=current_at,
        interval_seconds=0.0,
        runtime_floor={
            "status": "available",
            "recovered_continuous_started_at": (current_at - timedelta(hours=12)).isoformat(),
            "projected_observed_hours": 12.0,
            "no_live_order_sent": True,
        },
    )

    assert plan["continuous_started_at"] == current_at
    assert plan["runtime_floor_recovered"] is False
    assert plan["gap_reset"] is True


def test_launch_shadow_watch_resets_continuous_runtime_after_large_gap(monkeypatch, tmp_path) -> None:
    calls = []
    args = _args(tmp_path)
    args.iterations = 1
    args.target_hours = 24.0
    args.interval_seconds = 0.0
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    prior_started_at = datetime.now(UTC) - timedelta(hours=24)
    prior_completed_at = datetime.now(UTC) - timedelta(hours=3)
    (report_dir / "latest.json").write_text(
        json.dumps(
            {
                "started_at": prior_started_at.isoformat(),
                "completed_at": prior_completed_at.isoformat(),
                "no_live_order_sent": True,
                "runtime_observation": {
                    "continuous_started_at": prior_started_at.isoformat(),
                    "continuous_observed_hours": 21.0,
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_run_evidence_cycle(**kwargs):
        calls.append(kwargs)
        return {
            "overall_status": "healthy_abstention_waiting_for_quality_signal",
            "no_live_order_sent": True,
            "collection_progress": {"quote_observed": 80, "quote_distinct_hours": 8, "paper_fill_rows": 0},
            "readiness_progress": {},
            "paper_bridge_apply_gate": {"fresh_signal": False, "can_request_paper_apply_now": False},
            "signal_wait_plan": {},
            "launch_readiness": {"status": "research_ready_waiting_for_fresh_signal", "blocking_gates": []},
            "historical_gate_substitution": {},
            "canary_risk_caps_config": {},
        }

    monkeypatch.setattr(watch, "run_evidence_cycle", fake_run_evidence_cycle)

    summary = watch.run_launch_shadow_watch(args, sleep_fn=lambda seconds: None)

    assert summary["calendar_elapsed_hours"] >= 23.9
    assert summary["observed_hours"] < 0.1
    assert summary["runtime_observation"]["gap_reset"] is True
    assert summary["runtime_observation"]["gap_warning"] == "watch_gap_exceeded_threshold"
    assert summary["target_observation_complete"] is False
    assert calls[0]["shadow_runtime_observed_hours"] < 0.1


def test_launch_shadow_watch_keeps_previous_quote_baseline_for_heartbeat_delta(monkeypatch, tmp_path) -> None:
    args = _args(tmp_path)
    args.iterations = 1
    args.target_hours = 24.0
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    prior_started_at = datetime.now(UTC) - timedelta(hours=3)
    prior_completed_at = datetime.now(UTC) - timedelta(minutes=30)
    (report_dir / "latest.json").write_text(
        json.dumps(
            {
                "started_at": prior_started_at.isoformat(),
                "completed_at": prior_completed_at.isoformat(),
                "no_live_order_sent": True,
                "baseline_collection_progress": {
                    "quote_observed": 70,
                    "quote_distinct_hours": 6,
                    "paper_fill_rows": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_run_evidence_cycle(**kwargs):
        return {
            "overall_status": "healthy_abstention_waiting_for_quality_signal",
            "no_live_order_sent": True,
            "collection_progress": {"quote_observed": 84, "quote_distinct_hours": 9, "paper_fill_rows": 0},
            "readiness_progress": {},
            "paper_bridge_apply_gate": {"fresh_signal": False, "can_request_paper_apply_now": False},
            "signal_wait_plan": {},
            "launch_readiness": {"status": "research_ready_waiting_for_fresh_signal", "blocking_gates": []},
            "historical_gate_substitution": {},
            "canary_risk_caps_config": {},
        }

    monkeypatch.setattr(watch, "run_evidence_cycle", fake_run_evidence_cycle)

    summary = watch.run_launch_shadow_watch(args, sleep_fn=lambda seconds: None)

    assert summary["progress"]["quote_observed_start"] == 70
    assert summary["progress"]["quote_observed_delta"] == 14
    assert summary["progress"]["quote_progress_state"] == "progressing"
    assert summary["progress"]["quote_distinct_hours_delta"] == 3
    assert summary["watch_continuity"]["status"] == "continuous"


def test_launch_shadow_watch_reports_microstructure_trend_and_operator_handoff(monkeypatch, tmp_path) -> None:
    args = _args(tmp_path)
    args.iterations = 1
    args.target_hours = 24.0
    sample_path = Path(args.sample_jsonl)
    now = datetime.now(UTC).replace(minute=30, second=0, microsecond=0)
    rows = [
        build_quote_shadow_row(
            order_book=_book(),
            timestamp=now - timedelta(minutes=idx),
            symbol="BTCUSDT",
            strategy_family="market_state_rotation_v6",
            decision_id=f"quote_{idx}",
            side="long" if idx % 2 == 0 else "short",
            order_notional_usdt=100.0,
            latency_ms=80.0,
        )
        for idx in range(4)
    ]
    sample_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "latest.json").write_text(
        json.dumps(
            {
                "started_at": (now - timedelta(hours=1)).isoformat(),
                "completed_at": (now - timedelta(minutes=30)).isoformat(),
                "no_live_order_sent": True,
                "microstructure_watch": {
                    "baseline_metrics": {
                        "p95_spread_bps": 1.0,
                        "p95_market_slippage_bps": 1.0,
                        "p95_latency_ms": 200.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_run_evidence_cycle(**kwargs):
        return {
            "overall_status": "healthy_abstention_waiting_for_quality_signal",
            "no_live_order_sent": True,
            "collection_progress": {
                "quote_observed": 4,
                "quote_required": 10,
                "quote_distinct_hours": 1,
                "quote_min_distinct_hours": 3,
                "quote_calendar_days": 1,
                "quote_min_calendar_days": 2,
                "paper_fill_rows": 0,
            },
            "readiness_progress": {},
            "paper_bridge_apply_gate": {"fresh_signal": False, "can_request_paper_apply_now": False},
            "signal_wait_plan": {},
            "launch_readiness": {
                "status": "research_ready_waiting_for_fresh_signal",
                "tiny_canary_evidence_ready": False,
                "next_blocker": {"gate": "current_fresh_signal"},
                "blocking_gates": [{"gate": "current_fresh_signal", "passed": False}],
                "paper_bridge_handoff": {
                    "status": "blocked_waiting_for_fresh_signal",
                    "apply_allowed_now": False,
                    "dry_run_command": "dry-run",
                    "apply_command": "apply",
                },
                "operator_commands": {"microstructure_quote_capture": "capture"},
            },
            "historical_gate_substitution": {},
            "canary_risk_caps_config": {
                "configured": False,
                "status": "missing_optional_config_file",
                "errors": ["max_notional_usdt_must_be_positive"],
            },
        }

    monkeypatch.setattr(watch, "run_evidence_cycle", fake_run_evidence_cycle)

    summary = watch.run_launch_shadow_watch(args, sleep_fn=lambda seconds: None)

    micro = summary["microstructure_watch"]
    assert micro["status"] == "collecting_sample_day_hour_coverage"
    assert micro["eligible_row_count"] == 4
    assert micro["recent_eligible_row_count"] == 4
    assert micro["metric_blockers"] == []
    assert micro["metric_trend"]["p95_latency_ms"]["direction"] == "improved"
    assert micro["calendar_day_count"] == 1
    assert micro["min_calendar_days"] == 2
    assert micro["distinct_hour_count"] == 1
    assert micro["coverage_plan"]["remaining_quote_samples"] == 6
    assert micro["coverage_plan"]["can_collect_now"] is True
    assert micro["coverage_plan"]["recommended_action"] == "collect_quote_samples_now"
    handoff = summary["operator_handoff"]
    assert handoff["status"] == "waiting_for_fresh_signal_and_canary_risk_caps"
    assert handoff["paper_apply_allowed_now"] is False
    assert handoff["order_submission_allowed"] is False
    assert handoff["canary_review_blockers"] == ["current_fresh_signal"]
