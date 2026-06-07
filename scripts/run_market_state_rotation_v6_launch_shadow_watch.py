#!/usr/bin/env python3
"""Run repeated no-live v6 launch readiness checks for shadow/paper observation."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.run_market_state_rotation_v6_evidence_cycle import (
    DEFAULT_CANARY_RISK_CAPS_PATH,
    DEFAULT_HISTORICAL_LIFECYCLE_REPLAY_SOURCE,
    DEFAULT_HISTORICAL_REPLAY_SOURCE,
    DEFAULT_MANUAL_EVIDENCE,
    DEFAULT_PRE_APPLY_BACKUP_DIR,
    DEFAULT_SAMPLE_PATH,
    DEFAULT_SOURCE_BACKTEST_REPORT,
    DEFAULT_STRESS_REPORT,
    DEFAULT_WALK_FORWARD_REPORT,
    EVIDENCE_REPORT_NAME,
    _json_default,
    _resolve,
    run_evidence_cycle,
)
from scripts.run_market_state_rotation_v6_quote_shadow_audit import (
    EXPECTED_STRATEGY_FAMILY,
    EXPECTED_SYMBOL,
    _load_jsonl,
    build_quote_shadow_audit_report,
)


DEFAULT_REPORT_DIR = "reports/operations/market_state_rotation_v6_launch_shadow_watch"
DEFAULT_EVIDENCE_REPORT_ROOT = "reports/validation/diagnostics"
DEFAULT_MARKET_DATA_CACHE_DIR = "reports/validation/btc_flip_rotation_search/cache"
DEFAULT_MARKET_DATA_BASE_URL = "https://fapi.binance.com"
DEFAULT_MARKET_DATA_REFRESH_DAYS = 180
KST = timezone(timedelta(hours=9))


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _command_display(argv: list[str]) -> str:
    return " ".join(argv)


def _tail_text(value: str, *, max_chars: int = 2000) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _refresh_runtime_market_data_cache(*, evidence_root: Path, generated_at: datetime) -> dict[str, Any]:
    report_dir = evidence_root / f"market_state_rotation_v6_launch_shadow_watch_market_data_refresh_{generated_at:%Y%m%d_%H%M%S}"
    command = [
        sys.executable,
        str(ROOT_DIR / "scripts" / "run_btc_flip_rotation_search.py"),
        "--data-refresh-only",
        "--write-report",
        "--symbol",
        EXPECTED_SYMBOL,
        "--days",
        str(DEFAULT_MARKET_DATA_REFRESH_DAYS),
        "--intervals",
        "5m,1h,4h",
        "--cache-dir",
        DEFAULT_MARKET_DATA_CACHE_DIR,
        "--base-url",
        DEFAULT_MARKET_DATA_BASE_URL,
        "--max-cache-age-minutes",
        "0",
        "--report-dir",
        _display_path(report_dir),
    ]
    started_at = datetime.now(UTC)
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        completed_at = datetime.now(UTC)
        return {
            "status": "refreshed" if completed.returncode == 0 else "refresh_failed",
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "elapsed_seconds": round((completed_at - started_at).total_seconds(), 3),
            "returncode": completed.returncode,
            "command": _command_display(command),
            "report_dir": _display_path(report_dir),
            "stdout_tail": _tail_text(completed.stdout),
            "stderr_tail": _tail_text(completed.stderr),
            "order_submission_allowed": False,
            "no_live_order_sent": True,
        }
    except Exception as exc:  # pragma: no cover - defensive operational reporting.
        completed_at = datetime.now(UTC)
        return {
            "status": "refresh_exception",
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "elapsed_seconds": round((completed_at - started_at).total_seconds(), 3),
            "returncode": None,
            "command": _command_display(command),
            "report_dir": _display_path(report_dir),
            "error": str(exc),
            "order_submission_allowed": False,
            "no_live_order_sent": True,
        }


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    latest = dict(payload.get("latest_run") or {})
    launch = dict(latest.get("launch_readiness") or {})
    next_blocker = dict(launch.get("next_blocker") or {})
    launch_components = dict(launch.get("component_readiness") or {})
    launch_substitution = dict(launch.get("substitution_matrix") or {})
    launch_resolution = dict(launch.get("resolution_matrix") or {})
    microstructure_substitution = dict(launch_substitution.get("microstructure_time_coverage") or {})
    progress = dict(payload.get("progress") or {})
    runtime_progress = dict(payload.get("runtime_progress") or {})
    target_observation_status = dict(payload.get("target_observation_status") or {})
    continuity = dict(payload.get("watch_continuity") or {})
    signal_monitor_alignment = dict(payload.get("signal_monitor_cadence_alignment") or {})
    risk_caps = dict(payload.get("canary_risk_caps_config") or {})
    operator_handoff = dict(payload.get("operator_handoff") or {})
    operator_packet = dict(operator_handoff.get("paper_apply_operator_packet") or {})
    operator_packet_backup = dict(operator_packet.get("pre_apply_backup_plan") or {})
    operator_packet_command_safety = dict(operator_packet.get("command_safety") or {})
    operator_packet_pre_apply_evidence = dict(operator_packet.get("pre_apply_evidence_report_status") or {})
    execution_parity_eta = dict(operator_handoff.get("execution_parity_eta_plan") or {})
    eta_scenarios = dict(execution_parity_eta.get("eta_scenarios") or {})
    eta_all_events = dict(eta_scenarios.get("all_creditable_events") or {})
    eta_add_only = dict(eta_scenarios.get("conservative_add_only") or {})
    recent_parity_review = dict(payload.get("recent_paper_apply_parity_review") or {})
    promotion_gate = dict(payload.get("meta_router_promotion_gate") or {})
    promotion_readiness = dict(promotion_gate.get("readiness") or {})
    promotion_candidate = dict(promotion_gate.get("candidate") or {})
    blocker_plan = list(payload.get("blocker_resolution_plan") or [])
    safe_next_action = dict(payload.get("safe_next_action_plan") or {})
    primary_action = dict(safe_next_action.get("primary_action") or {})
    scheduled_action = dict(safe_next_action.get("next_scheduled_action") or {})
    startable_wait_action = dict(safe_next_action.get("next_startable_wait_action") or {})
    deferred_wait_action = dict(safe_next_action.get("next_deferred_wait_action") or {})
    safety = dict(latest.get("launch_safety_controls") or {})
    preflight = dict(latest.get("quote_cadence_preflight") or {})
    pre_run_wait = dict(payload.get("pre_run_quote_window_wait_plan") or {})
    pre_run_capture_outcome = dict(payload.get("pre_run_quote_window_capture_outcome") or {})
    latest_collection = dict(latest.get("collection_progress") or {})
    evidence_pre_run_refresh = dict(latest.get("pre_run_market_data_refresh") or {})
    microstructure = dict(payload.get("microstructure_watch") or {})
    coverage_plan = dict(microstructure.get("coverage_plan") or {})
    lines = [
        "# Market State Rotation V6 Launch Shadow Watch",
        "",
        f"- status: `{payload.get('status')}`",
        f"- no_live_order_sent: `{payload.get('no_live_order_sent')}`",
        f"- target_hours: `{payload.get('target_hours')}`",
        f"- target_observation_runtime_reached: `{target_observation_status.get('runtime_target_reached')}`",
        f"- target_observation_reason: `{target_observation_status.get('reason')}`",
        f"- observed_hours: `{payload.get('observed_hours')}`",
        f"- calendar_elapsed_hours: `{payload.get('calendar_elapsed_hours')}`",
        f"- runtime_remaining_hours: `{runtime_progress.get('remaining_hours')}`",
        f"- runtime_progress_pct: `{runtime_progress.get('progress_pct')}`",
        f"- runtime_gap_reset: `{dict(payload.get('runtime_observation') or {}).get('gap_reset')}`",
        f"- runtime_continuous_started_at: `{dict(payload.get('runtime_observation') or {}).get('continuous_started_at')}`",
        f"- watch_continuity_status: `{continuity.get('status')}`",
        f"- watch_continuity_warning: `{continuity.get('warning')}`",
        f"- signal_monitor_cadence_alignment_status: `{signal_monitor_alignment.get('status')}`",
        f"- signal_monitor_cadence_alignment_warning: `{signal_monitor_alignment.get('warning')}`",
        f"- signal_monitor_cadence_gap_minutes: `{signal_monitor_alignment.get('gap_minutes')}`",
        f"- signal_monitor_cadence_recommended_minutes: `{signal_monitor_alignment.get('recommended_monitor_interval_minutes')}`",
        f"- pre_run_quote_window_wait_status: `{pre_run_wait.get('status')}`",
        f"- pre_run_quote_window_should_sleep: `{pre_run_wait.get('should_sleep')}`",
        f"- pre_run_quote_window_wait_seconds: `{pre_run_wait.get('wait_seconds')}`",
        f"- pre_run_quote_window_next_quote_coverage_kind: `{pre_run_wait.get('next_quote_coverage_kind')}`",
        f"- pre_run_quote_window_next_quote_coverage_utc_at: `{pre_run_wait.get('next_quote_coverage_at')}`",
        f"- pre_run_quote_window_next_missing_utc_at: `{pre_run_wait.get('next_missing_utc_at')}`",
        f"- pre_run_quote_window_sleep_started_at: `{pre_run_wait.get('sleep_started_at')}`",
        f"- pre_run_quote_window_woke_at: `{pre_run_wait.get('woke_at')}`",
        f"- pre_run_quote_window_actual_sleep_seconds: `{pre_run_wait.get('actual_sleep_seconds')}`",
        f"- pre_run_quote_window_target_window_missed: `{pre_run_wait.get('target_window_missed')}`",
        f"- pre_run_quote_window_overshoot_minutes: `{pre_run_wait.get('overshoot_minutes')}`",
        f"- pre_run_quote_window_recovery_action: `{pre_run_wait.get('recovery_action')}`",
        f"- pre_run_quote_window_incident_count: `{len(payload.get('pre_run_quote_window_wait_incident_log') or [])}`",
        (
            "- pre_run_quote_window_latest_incident: "
            f"`{dict(payload.get('latest_pre_run_quote_window_wait_incident') or {}).get('incident_type')}`"
        ),
        f"- pre_run_quote_window_capture_status: `{pre_run_capture_outcome.get('status')}`",
        f"- pre_run_quote_window_capture_target_utc_hour: `{pre_run_capture_outcome.get('target_utc_hour')}`",
        f"- pre_run_quote_window_capture_rows_this_cycle: `{pre_run_capture_outcome.get('captured_quote_rows_this_cycle')}`",
        f"- pre_run_market_data_refresh_status: `{dict(payload.get('pre_run_market_data_refresh') or {}).get('status')}`",
        f"- pre_run_market_data_refresh_returncode: `{dict(payload.get('pre_run_market_data_refresh') or {}).get('returncode')}`",
        f"- evidence_pre_run_market_data_refresh_status: `{evidence_pre_run_refresh.get('status')}`",
        f"- evidence_pre_run_market_data_refresh_returncode: `{evidence_pre_run_refresh.get('returncode')}`",
        f"- completed_iterations: `{payload.get('completed_iterations')}`",
        f"- launch_status: `{launch.get('status')}`",
        f"- launch_effective_research_status: `{launch.get('effective_research_status')}`",
        f"- launch_resolution_status: `{launch_resolution.get('status')}`",
        f"- launch_backtest_substitution_exhausted: `{launch_resolution.get('backtest_substitution_exhausted')}`",
        f"- launch_non_substitutable_remaining_gates: `{launch_resolution.get('non_substitutable_remaining_gates')}`",
        f"- launch_no_live_actionable_remaining_gates: `{launch_resolution.get('no_live_actionable_remaining_gates')}`",
        f"- launch_no_live_progressable_remaining_gates: `{launch_resolution.get('no_live_progressable_remaining_gates')}`",
        f"- launch_substituted_time_wait_removed_days: `{launch.get('substituted_time_wait_removed_days')}`",
        f"- launch_substituted_research_readiness_pct: `{launch.get('substituted_research_readiness_pct')}`",
        f"- meta_router_promotion_status: `{promotion_gate.get('status')}`",
        f"- meta_router_promotion_decision: `{promotion_gate.get('promotion_decision')}`",
        f"- meta_router_promotion_next_blocker: `{promotion_gate.get('next_blocker')}`",
        f"- meta_router_promotion_stale: `{promotion_gate.get('stale')}`",
        f"- meta_router_promotion_source: `{promotion_gate.get('source_report')}`",
        f"- meta_router_candidate: `{promotion_candidate.get('recipe_id')}`",
        f"- meta_router_candidate_return_pct: `{promotion_candidate.get('compounded_return_pct')}`",
        f"- meta_router_candidate_max_drawdown_pct: `{promotion_candidate.get('max_drawdown_pct')}`",
        f"- meta_router_readiness_stage: `{promotion_readiness.get('stage')}`",
        f"- meta_router_ready_for_paper: `{promotion_readiness.get('ready_for_paper')}`",
        f"- meta_router_ready_for_tiny_canary: `{promotion_readiness.get('ready_for_tiny_canary')}`",
        f"- meta_router_ready_for_full_live: `{promotion_readiness.get('ready_for_full_live')}`",
        f"- meta_router_readiness_blockers: `{promotion_readiness.get('blockers')}`",
        f"- launch_research_ready: `{launch.get('research_ready')}`",
        f"- launch_shadow_ready: `{launch.get('shadow_ready')}`",
        f"- launch_tiny_canary_evidence_ready: `{launch.get('tiny_canary_evidence_ready')}`",
        f"- launch_microstructure_metric_ready: `{launch_components.get('microstructure_metric_ready')}`",
        f"- launch_microstructure_time_proxy_ready: `{launch_components.get('microstructure_time_proxy_ready')}`",
        f"- launch_microstructure_proxy_scope: `{microstructure_substitution.get('scope')}`",
        f"- launch_real_microstructure_ready: `{launch_components.get('real_microstructure_ready')}`",
        f"- launch_next_blocker: `{next_blocker.get('gate')}`",
        f"- launch_next_action: `{next_blocker.get('next_action')}`",
        f"- quote_observed_latest: `{latest_collection.get('quote_observed')}`",
        f"- quote_observed_delta: `{progress.get('quote_observed_delta')}`",
        f"- quote_progress_state: `{progress.get('quote_progress_state')}`",
        f"- quote_distinct_hours_latest: `{latest_collection.get('quote_distinct_hours')}`",
        f"- quote_distinct_hours_delta: `{progress.get('quote_distinct_hours_delta')}`",
        f"- quote_hour_progress_state: `{progress.get('quote_hour_progress_state')}`",
        f"- quote_cadence_decision: `{preflight.get('decision')}`",
        f"- effective_quote_samples_per_tick: `{preflight.get('effective_quote_samples_per_tick')}`",
        f"- force_quote_sample: `{preflight.get('force_quote_sample')}`",
        f"- canary_risk_caps_status: `{risk_caps.get('status')}`",
        f"- canary_risk_caps_source: `{risk_caps.get('source')}`",
        f"- canary_risk_caps_errors: `{risk_caps.get('errors')}`",
        f"- microstructure_status: `{microstructure.get('status')}`",
        f"- microstructure_p95_spread_bps: `{dict(microstructure.get('metrics') or {}).get('p95_spread_bps')}`",
        f"- microstructure_p95_slippage_bps: `{dict(microstructure.get('metrics') or {}).get('p95_market_slippage_bps')}`",
        f"- microstructure_p95_latency_ms: `{dict(microstructure.get('metrics') or {}).get('p95_latency_ms')}`",
        f"- microstructure_metric_blockers: `{microstructure.get('metric_blockers')}`",
        f"- microstructure_coverage_status: `{coverage_plan.get('status')}`",
        f"- microstructure_remaining_calendar_days: `{coverage_plan.get('remaining_calendar_days')}`",
        f"- microstructure_earliest_calendar_completion_utc: `{coverage_plan.get('earliest_calendar_completion_utc')}`",
        f"- microstructure_calendar_completion_policy: `{coverage_plan.get('calendar_completion_policy')}`",
        f"- microstructure_remaining_distinct_hours: `{coverage_plan.get('remaining_distinct_hours')}`",
        f"- microstructure_remaining_distinct_hour_buckets: `{coverage_plan.get('remaining_distinct_hour_bucket_count')}`",
        f"- microstructure_remaining_hour_of_day_buckets: `{coverage_plan.get('remaining_hour_of_day_bucket_count')}`",
        f"- microstructure_current_utc_date_missing: `{coverage_plan.get('current_utc_date_missing')}`",
        f"- microstructure_next_quote_coverage_kind: `{coverage_plan.get('next_quote_coverage_kind')}`",
        f"- microstructure_next_quote_coverage_at: `{coverage_plan.get('next_quote_coverage_at')}`",
        f"- microstructure_next_quote_coverage_kst_at: `{coverage_plan.get('next_quote_coverage_kst_at')}`",
        f"- microstructure_current_utc_hour_missing: `{coverage_plan.get('current_utc_hour_missing')}`",
        f"- microstructure_next_missing_utc_hour: `{coverage_plan.get('next_missing_utc_hour')}`",
        f"- microstructure_missing_utc_hour_of_day: `{coverage_plan.get('missing_utc_hour_of_day')}`",
        f"- microstructure_next_missing_utc_at: `{coverage_plan.get('next_missing_utc_at')}`",
        f"- microstructure_next_missing_kst_at: `{coverage_plan.get('next_missing_kst_at')}`",
        f"- microstructure_wait_minutes: `{coverage_plan.get('wait_minutes')}`",
        f"- microstructure_recommended_action: `{coverage_plan.get('recommended_action')}`",
        f"- operator_handoff_status: `{operator_handoff.get('status')}`",
        f"- operator_handoff_next_action: `{operator_handoff.get('next_action')}`",
        f"- operator_handoff_paper_apply_allowed_now: `{operator_handoff.get('paper_apply_allowed_now')}`",
        f"- operator_handoff_paper_packet_status: `{operator_packet.get('status')}`",
        f"- operator_handoff_pre_apply_evidence_status: `{operator_packet_pre_apply_evidence.get('status')}`",
        f"- operator_handoff_pre_apply_evidence_age_minutes: `{operator_packet_pre_apply_evidence.get('age_minutes')}`",
        f"- operator_handoff_pre_apply_evidence_blockers: `{operator_packet_pre_apply_evidence.get('blockers')}`",
        f"- operator_handoff_pre_apply_backup_status: `{operator_packet_backup.get('status')}`",
        f"- operator_handoff_pre_apply_backup_dir: `{operator_packet_backup.get('backup_dir')}`",
        f"- operator_handoff_review_deadline_utc: `{operator_packet.get('operator_review_deadline_utc')}`",
        f"- operator_handoff_review_deadline_policy: `{operator_packet.get('deadline_policy')}`",
        f"- operator_handoff_command_safety_status: `{operator_packet_command_safety.get('status')}`",
        f"- operator_handoff_command_safety_blockers: `{operator_packet_command_safety.get('blockers')}`",
        f"- operator_handoff_command_safety_warnings: `{operator_packet_command_safety.get('warnings')}`",
        f"- operator_handoff_command_safety_dry_run_report_dir: `{operator_packet_command_safety.get('dry_run_report_dir')}`",
        f"- operator_handoff_command_safety_apply_report_dir: `{operator_packet_command_safety.get('apply_report_dir')}`",
        f"- operator_handoff_command_safety_pre_apply_backup_dir: `{operator_packet_command_safety.get('apply_pre_apply_backup_dir')}`",
        f"- operator_handoff_post_apply_review_required: `{operator_packet.get('post_apply_review_required')}`",
        f"- operator_handoff_execution_parity_events_needed: `{operator_handoff.get('execution_parity_events_needed')}`",
        f"- operator_handoff_execution_parity_events_after_current_apply: `{operator_handoff.get('execution_parity_events_needed_after_current_apply')}`",
        f"- operator_handoff_execution_parity_will_credit_current_apply: `{operator_handoff.get('execution_parity_will_credit_current_apply')}`",
        f"- operator_handoff_execution_parity_creditable_actions: `{operator_handoff.get('execution_parity_creditable_actions')}`",
        f"- execution_parity_eta_status: `{execution_parity_eta.get('status')}`",
        f"- execution_parity_eta_selected_scenario: `{execution_parity_eta.get('selected_eta_scenario')}`",
        f"- execution_parity_eta_days_at_current_cadence: `{execution_parity_eta.get('estimated_days_at_current_cadence')}`",
        f"- execution_parity_eta_completion_kst: `{execution_parity_eta.get('estimated_completion_kst')}`",
        f"- execution_parity_eta_cadence_source: `{execution_parity_eta.get('cadence_source')}`",
        f"- execution_parity_eta_all_event_days: `{eta_all_events.get('estimated_days')}`",
        f"- execution_parity_eta_add_only_days: `{eta_add_only.get('estimated_days')}`",
        f"- execution_parity_eta_caveat: `{execution_parity_eta.get('caveat')}`",
        f"- operator_handoff_canary_review_ready: `{operator_handoff.get('canary_review_ready')}`",
        f"- recent_paper_apply_parity_review_status: `{recent_parity_review.get('status')}`",
        f"- recent_paper_apply_parity_review_blocked: `{recent_parity_review.get('blocks_next_paper_apply')}`",
        f"- recent_paper_apply_parity_review_source: `{recent_parity_review.get('source_report')}`",
        f"- recent_paper_apply_parity_review_reason: `{recent_parity_review.get('reason')}`",
        f"- recent_paper_apply_parity_review_blockers: `{recent_parity_review.get('blockers')}`",
        f"- recent_paper_apply_parity_review_next_actions: `{recent_parity_review.get('next_actions')}`",
        f"- recent_paper_apply_parity_review_recommended_command: `{recent_parity_review.get('recommended_command')}`",
        f"- safe_next_action_status: `{safe_next_action.get('status')}`",
        f"- safe_next_action_type: `{primary_action.get('action_type')}`",
        f"- safe_next_action_can_run_now: `{primary_action.get('can_run_now')}`",
        f"- safe_next_action_requires_operator_review: `{primary_action.get('requires_operator_review')}`",
        f"- safe_next_action_command: `{primary_action.get('command')}`",
        f"- safe_next_action_recommended_monitor_interval_minutes: `{primary_action.get('recommended_monitor_interval_minutes')}`",
        f"- safe_next_action_signal_freshness_capture_window_minutes: `{primary_action.get('signal_freshness_capture_window_minutes')}`",
        f"- safe_next_action_monitor_interval_capped_by_freshness: `{primary_action.get('monitor_interval_capped_by_signal_freshness')}`",
        f"- safe_next_action_monitor_signal_age_alignment: `{primary_action.get('monitor_signal_age_alignment')}`",
        f"- safe_next_action_paper_packet_status: `{dict(primary_action.get('paper_apply_operator_packet') or {}).get('status')}`",
        f"- safe_next_scheduled_action_type: `{scheduled_action.get('action_type')}`",
        f"- safe_next_scheduled_execute_after_utc: `{scheduled_action.get('execute_after_utc')}`",
        f"- safe_next_scheduled_wait_minutes: `{scheduled_action.get('wait_minutes')}`",
        f"- safe_next_startable_wait_action_type: `{startable_wait_action.get('action_type')}`",
        f"- safe_next_startable_wait_execute_after_utc: `{startable_wait_action.get('execute_after_utc')}`",
        f"- safe_next_deferred_wait_action_type: `{deferred_wait_action.get('action_type')}`",
        f"- safe_next_deferred_wait_execute_after_utc: `{deferred_wait_action.get('execute_after_utc')}`",
        f"- safe_next_deferred_wait_reason: `{deferred_wait_action.get('deferred_reason')}`",
        f"- safe_next_pre_wait_scheduled_action_count: `{safe_next_action.get('pre_wait_scheduled_action_count')}`",
        f"- safe_next_coordination_warnings: `{safe_next_action.get('coordination_warnings')}`",
        f"- launch_safety_controls_status: `{safety.get('overall_status')}`",
        f"- launch_safety_controls_verified: `{safety.get('verified_count')}/{safety.get('required_count')}`",
        f"- blocker_resolution_count: `{len(blocker_plan)}`",
        f"- fresh_signal_seen: `{progress.get('fresh_signal_seen')}`",
        f"- paper_apply_available_seen: `{progress.get('paper_apply_available_seen')}`",
        f"- tiny_canary_ready_seen: `{progress.get('tiny_canary_ready_seen')}`",
        f"- execution_parity_journal_rows_latest: `{progress.get('execution_parity_journal_rows_latest')}`",
        f"- execution_parity_journal_rows_delta: `{progress.get('execution_parity_journal_rows_delta')}`",
        f"- execution_parity_missing_samples_latest: `{progress.get('execution_parity_missing_samples_latest')}`",
        f"- execution_parity_passed_latest: `{progress.get('execution_parity_passed_latest')}`",
        f"- execution_parity_collection_status_latest: `{progress.get('execution_parity_collection_status_latest')}`",
        f"- execution_parity_events_needed_latest: `{progress.get('execution_parity_events_needed_latest')}`",
        f"- execution_parity_events_needed_after_current_apply_latest: `{progress.get('execution_parity_events_needed_after_current_apply_latest')}`",
        f"- execution_parity_will_credit_current_apply_latest: `{progress.get('execution_parity_will_credit_current_apply_latest')}`",
        f"- execution_parity_creditable_actions_latest: `{progress.get('execution_parity_creditable_actions_latest')}`",
        f"- execution_parity_next_step_latest: `{progress.get('execution_parity_next_step_latest')}`",
        f"- latest_evidence_report: `{latest.get('evidence_report')}`",
        "",
        "## Blocking Gates",
        "",
    ]
    for item in list(launch.get("blocking_gates") or []):
        lines.append(f"- `{item.get('gate')}`: {item.get('blocker')} -> {item.get('next_action')}")
    lines.extend(["", "## Blocker Resolution Plan", ""])
    for item in blocker_plan:
        lines.append(
            f"- `{item.get('gate')}` can_resolve_now=`{item.get('can_resolve_now')}` "
            f"review=`{item.get('requires_operator_review')}` reason=`{item.get('reason')}`"
        )
    lines.extend(["", "## Safe Next Actions", ""])
    for item in list(safe_next_action.get("actions") or []):
        packet = dict(item.get("paper_apply_operator_packet") or {})
        lines.append(
            f"- `{item.get('action_type')}` priority=`{item.get('priority')}` "
            f"can_run_now=`{item.get('can_run_now')}` can_start_now=`{item.get('can_start_now')}` "
            f"review=`{item.get('requires_operator_review')}` wait_minutes=`{item.get('wait_minutes')}` "
            f"execute_after_utc=`{item.get('execute_after_utc')}` reason=`{item.get('reason')}` "
            f"paper_packet=`{packet.get('status')}`"
        )
    _write_text(path, "\n".join(lines) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _previous_started_at(report_dir: Path) -> datetime | None:
    payload = _previous_watch_payload(report_dir)
    if not payload:
        return None
    return _parse_dt(payload.get("started_at"))


def _previous_watch_payload(report_dir: Path) -> dict[str, Any]:
    latest_path = report_dir / "latest.json"
    try:
        payload = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if payload.get("no_live_order_sent") is not True:
        return {}
    return payload


def _baseline_collection_progress(previous_payload: dict[str, Any]) -> dict[str, Any]:
    baseline = dict(previous_payload.get("baseline_collection_progress") or {})
    if baseline:
        return baseline
    latest_run = dict(previous_payload.get("latest_run") or {})
    return dict(latest_run.get("collection_progress") or {})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run safe launch readiness checks repeatedly without live orders.")
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--interval-seconds", type=float, default=900.0)
    parser.add_argument("--target-hours", type=float, default=24.0)
    parser.add_argument("--quote-samples-per-tick", type=int, default=2)
    parser.add_argument("--force-quote-sample", action="store_true")
    parser.add_argument("--disable-adaptive-quote-cadence", action="store_true")
    parser.add_argument(
        "--sleep-until-next-quote-coverage-window",
        "--sleep-until-next-missing-quote-window",
        dest="sleep_until_next_missing_quote_window",
        action="store_true",
    )
    parser.add_argument("--max-pre-run-wait-seconds", type=float, default=3600.0)
    parser.add_argument("--quote-window-wakeup-buffer-seconds", type=float, default=5.0)
    parser.add_argument("--disable-market-data-refresh-after-quote-window-sleep", action="store_true")
    parser.add_argument("--disable-market-data-refresh-before-evidence-run", action="store_true")
    parser.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    parser.add_argument("--evidence-report-root", default=DEFAULT_EVIDENCE_REPORT_ROOT)
    parser.add_argument("--source-backtest-report", default=DEFAULT_SOURCE_BACKTEST_REPORT)
    parser.add_argument("--stress-report", default=DEFAULT_STRESS_REPORT)
    parser.add_argument("--walk-forward-report", default=DEFAULT_WALK_FORWARD_REPORT)
    parser.add_argument("--manual-safety-evidence", default=DEFAULT_MANUAL_EVIDENCE)
    parser.add_argument("--sample-jsonl", default=DEFAULT_SAMPLE_PATH)
    parser.add_argument("--historical-replay-source", default=DEFAULT_HISTORICAL_REPLAY_SOURCE)
    parser.add_argument("--historical-replay-days", type=int, default=1831)
    parser.add_argument("--historical-lifecycle-source", default=DEFAULT_HISTORICAL_LIFECYCLE_REPLAY_SOURCE)
    parser.add_argument("--canary-max-notional-usdt", type=float, default=0.0)
    parser.add_argument("--canary-max-leverage", type=float, default=10.0)
    parser.add_argument("--canary-max-daily-loss-usdt", type=float, default=0.0)
    parser.add_argument("--canary-risk-caps-json", default=DEFAULT_CANARY_RISK_CAPS_PATH)
    parser.add_argument("--microstructure-recent-hours", type=float, default=24.0)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def _run_once(
    args: argparse.Namespace,
    *,
    iteration: int,
    generated_at: datetime,
    observed_hours: float,
    refresh_market_data_before_run: bool = True,
    force_quote_sample: bool = False,
) -> dict[str, Any]:
    evidence_root = _resolve(args.evidence_report_root)
    evidence_dir = evidence_root / f"market_state_rotation_v6_launch_shadow_watch_{generated_at:%Y%m%d_%H%M%S}_i{iteration:03d}"
    manual_path = _resolve(args.manual_safety_evidence) if args.manual_safety_evidence else None
    effective_force_quote_sample = bool(args.force_quote_sample) or bool(force_quote_sample)
    report = run_evidence_cycle(
        source_backtest_report_path=_resolve(args.source_backtest_report),
        stress_report_path=_resolve(args.stress_report),
        walk_forward_report_path=_resolve(args.walk_forward_report),
        manual_evidence_path=manual_path,
        sample_jsonl=_resolve(args.sample_jsonl),
        report_dir=evidence_dir,
        quote_samples_per_tick=max(0, int(args.quote_samples_per_tick)),
        adaptive_quote_cadence=not bool(args.disable_adaptive_quote_cadence),
        force_quote_sample=effective_force_quote_sample,
        historical_evidence_replay=True,
        refresh_market_data_before_run=bool(refresh_market_data_before_run),
        historical_replay_source_path=_resolve(args.historical_replay_source),
        historical_replay_days=max(1, int(args.historical_replay_days)),
        historical_lifecycle_replay=True,
        historical_lifecycle_source_path=_resolve(args.historical_lifecycle_source),
        canary_max_notional_usdt=max(0.0, float(args.canary_max_notional_usdt)),
        canary_max_leverage=max(0.0, float(args.canary_max_leverage)),
        canary_max_daily_loss_usdt=max(0.0, float(args.canary_max_daily_loss_usdt)),
        canary_risk_caps_path=_resolve(args.canary_risk_caps_json) if args.canary_risk_caps_json else None,
        shadow_runtime_observed_hours=max(0.0, float(observed_hours or 0.0)),
        shadow_runtime_required_hours=max(0.0, float(args.target_hours or 0.0)),
    )
    return {
        "iteration": iteration,
        "generated_at": generated_at.isoformat(),
        "shadow_runtime_observed_hours": round(max(0.0, float(observed_hours or 0.0)), 4),
        "shadow_runtime_required_hours": max(0.0, float(args.target_hours or 0.0)),
        "evidence_report_dir": _display_path(evidence_dir),
        "evidence_report": _display_path(evidence_dir / EVIDENCE_REPORT_NAME),
        "overall_status": report.get("overall_status"),
        "no_live_order_sent": report.get("no_live_order_sent") is True,
        "collection_progress": dict(report.get("collection_progress") or {}),
        "readiness_progress": dict(report.get("readiness_progress") or {}),
        "execution_parity_journal": dict(report.get("execution_parity_journal") or {}),
        "execution_parity_collection_plan": dict(report.get("execution_parity_collection_plan") or {}),
        "paper_bridge_apply_gate": dict(report.get("paper_bridge_apply_gate") or {}),
        "pre_apply_backup_plan": dict(report.get("pre_apply_backup_plan") or {}),
        "quote_cadence_preflight": dict(report.get("quote_cadence_preflight") or {}),
        "pre_run_market_data_refresh": dict(report.get("pre_run_market_data_refresh") or {}),
        "market_data_refresh_plan": dict(report.get("market_data_refresh_plan") or {}),
        "signal_wait_plan": dict(report.get("signal_wait_plan") or {}),
        "launch_readiness": dict(report.get("launch_readiness") or {}),
        "launch_safety_controls": dict(report.get("launch_safety_controls") or {}),
        "historical_gate_substitution": dict(report.get("historical_gate_substitution") or {}),
        "canary_risk_caps_config": dict(report.get("canary_risk_caps_config") or {}),
    }


def _watch_progress(runs: list[dict[str, Any]], *, baseline_collection: dict[str, Any] | None = None) -> dict[str, Any]:
    if not runs:
        return {
            "fresh_signal_seen": False,
            "paper_apply_available_seen": False,
            "tiny_canary_ready_seen": False,
        }
    first_collection = dict(baseline_collection or runs[0].get("collection_progress") or {})
    latest_collection = dict(runs[-1].get("collection_progress") or {})
    latest_parity_plan = dict(runs[-1].get("execution_parity_collection_plan") or {})
    launch_statuses = [str(dict(run.get("launch_readiness") or {}).get("status") or "") for run in runs]
    next_blockers = [
        str(dict(dict(run.get("launch_readiness") or {}).get("next_blocker") or {}).get("gate") or "")
        for run in runs
    ]
    fresh_signal_seen = any(
        dict(run.get("paper_bridge_apply_gate") or {}).get("fresh_signal") is True
        for run in runs
    )
    paper_apply_available_seen = any(
        dict(run.get("paper_bridge_apply_gate") or {}).get("can_request_paper_apply_now") is True
        for run in runs
    )
    tiny_canary_ready_seen = any(
        dict(run.get("launch_readiness") or {}).get("tiny_canary_evidence_ready") is True
        for run in runs
    )
    def _int_value(payload: dict[str, Any], key: str) -> int:
        try:
            return int(payload.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    quote_delta = _int_value(latest_collection, "quote_observed") - _int_value(first_collection, "quote_observed")
    hour_delta = _int_value(latest_collection, "quote_distinct_hours") - _int_value(first_collection, "quote_distinct_hours")
    execution_parity_delta = _int_value(latest_collection, "execution_parity_journal_rows") - _int_value(
        first_collection,
        "execution_parity_journal_rows",
    )
    return {
        "launch_statuses_seen": sorted(set(item for item in launch_statuses if item)),
        "next_blockers_seen": sorted(set(item for item in next_blockers if item)),
        "fresh_signal_seen": fresh_signal_seen,
        "paper_apply_available_seen": paper_apply_available_seen,
        "tiny_canary_ready_seen": tiny_canary_ready_seen,
        "quote_observed_start": _int_value(first_collection, "quote_observed"),
        "quote_observed_latest": _int_value(latest_collection, "quote_observed"),
        "quote_observed_delta": quote_delta,
        "quote_progress_state": "progressing" if quote_delta > 0 else "no_new_quote_rows_since_watch_baseline",
        "quote_distinct_hours_start": _int_value(first_collection, "quote_distinct_hours"),
        "quote_distinct_hours_latest": _int_value(latest_collection, "quote_distinct_hours"),
        "quote_distinct_hours_delta": hour_delta,
        "quote_hour_progress_state": "progressing" if hour_delta > 0 else "no_new_utc_hour_since_watch_baseline",
        "paper_fill_rows_latest": _int_value(latest_collection, "paper_fill_rows"),
        "execution_parity_journal_rows_latest": _int_value(latest_collection, "execution_parity_journal_rows"),
        "execution_parity_journal_rows_delta": execution_parity_delta,
        "execution_parity_missing_samples_latest": _int_value(latest_collection, "execution_parity_missing_samples"),
        "execution_parity_passed_latest": latest_collection.get("execution_parity_passed") is True,
        "execution_parity_progress_state": (
            "progressing" if execution_parity_delta > 0 else "no_new_execution_parity_rows_since_watch_baseline"
        ),
        "execution_parity_collection_status_latest": latest_parity_plan.get("status"),
        "execution_parity_events_needed_latest": _int_value(
            latest_parity_plan,
            "estimated_future_paper_apply_events_needed",
        ),
        "execution_parity_events_needed_after_current_apply_latest": _int_value(
            latest_parity_plan,
            "estimated_events_needed_after_current_creditable_apply",
        ),
        "execution_parity_will_credit_current_apply_latest": (
            latest_parity_plan.get("will_credit_current_apply_after_operator_review") is True
        ),
        "execution_parity_creditable_actions_latest": list(
            latest_parity_plan.get("currently_creditable_actions") or []
        ),
        "execution_parity_next_step_latest": latest_parity_plan.get("next_step"),
        "execution_parity_non_substitutable_latest": latest_parity_plan.get("non_substitutable") is True,
    }


def _number_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and parsed not in {float("inf"), float("-inf")} else None


def _int_or_default(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _metric_trend_item(*, current: Any, baseline: Any, lower_is_better: bool = True) -> dict[str, Any]:
    current_value = _number_or_none(current)
    baseline_value = _number_or_none(baseline)
    if current_value is None or baseline_value is None:
        return {
            "baseline": baseline_value,
            "current": current_value,
            "delta": None,
            "direction": "insufficient_data",
        }
    delta = round(current_value - baseline_value, 4)
    if abs(delta) < 1e-9:
        direction = "unchanged"
    elif (delta < 0.0 and lower_is_better) or (delta > 0.0 and not lower_is_better):
        direction = "improved"
    else:
        direction = "worsened"
    return {
        "baseline": baseline_value,
        "current": current_value,
        "delta": delta,
        "direction": direction,
    }


def _pre_run_quote_window_capture_outcome(
    *,
    pre_run_wait_plan: dict[str, Any] | None,
    latest_collection: dict[str, Any] | None,
) -> dict[str, Any]:
    plan = dict(pre_run_wait_plan or {})
    collection = dict(latest_collection or {})
    waited = plan.get("actual_sleep_seconds") is not None or plan.get("should_sleep") is True
    if not waited:
        return {
            "status": "not_applicable",
            "reason": "pre_run_quote_window_sleep_not_used",
            "no_live_order_sent": True,
        }

    target_dt = _parse_dt(
        plan.get("target_window_start_utc")
        or plan.get("next_quote_coverage_at")
        or plan.get("next_missing_utc_at")
    )
    target_kind = str(plan.get("next_quote_coverage_kind") or "")
    target_hour = f"{target_dt.hour:02d}" if target_dt is not None else str(plan.get("next_missing_utc_hour") or "")
    target_date = target_dt.date().isoformat() if target_dt is not None else str(plan.get("target_utc_date") or "")
    coverage = dict(collection.get("quote_coverage") or {})
    covered_hours = {str(item).zfill(2) for item in list(coverage.get("utc_hour_of_day_covered") or [])}
    missing_hours = {str(item).zfill(2) for item in list(coverage.get("utc_hour_of_day_missing") or [])}
    captured_rows = _int_or_default(collection.get("captured_quote_rows_this_cycle"), 0)

    if target_kind in {"current_utc_calendar_day", "next_utc_calendar_day", "new_utc_calendar_day"}:
        previous_calendar_day_count = _int_or_default(plan.get("calendar_day_count"), -1)
        current_calendar_day_count = _int_or_default(collection.get("quote_calendar_days"), -1)
        covered_calendar_days_before = {str(item) for item in list(plan.get("covered_calendar_days") or [])}
        if current_calendar_day_count > previous_calendar_day_count >= 0:
            status = "target_calendar_day_captured"
            reason = "quote_calendar_day_count_increased_after_wait"
        elif captured_rows > 0 and target_date and target_date not in covered_calendar_days_before:
            status = "target_calendar_day_sampled"
            reason = "quote_rows_captured_for_previously_uncovered_calendar_day"
        elif target_date and target_date in covered_calendar_days_before:
            status = "target_calendar_day_already_covered_before_wait"
            reason = "wait_plan_target_calendar_day_was_already_in_previous_coverage"
        else:
            status = "target_calendar_day_still_missing_after_wait"
            reason = "quote_calendar_day_count_did_not_increase_after_wait"
        return {
            "status": status,
            "reason": reason,
            "target_quote_coverage_kind": target_kind,
            "target_utc_date": target_date or None,
            "target_window_start_utc": target_dt.isoformat() if target_dt is not None else None,
            "target_window_missed": plan.get("target_window_missed"),
            "captured_quote_rows_this_cycle": captured_rows,
            "previous_quote_calendar_days": previous_calendar_day_count if previous_calendar_day_count >= 0 else None,
            "current_quote_calendar_days": current_calendar_day_count if current_calendar_day_count >= 0 else None,
            "target_calendar_day_covered": status
            in {"target_calendar_day_captured", "target_calendar_day_sampled", "target_calendar_day_already_covered_before_wait"},
            "covered_calendar_days_before_wait": sorted(covered_calendar_days_before),
            "no_live_order_sent": True,
        }

    if not target_hour:
        status = "target_hour_unknown"
        reason = "wait_plan_missing_target_hour"
    elif target_hour in covered_hours:
        status = "target_hour_captured"
        reason = "target_utc_hour_present_in_latest_quote_coverage"
    elif target_hour in missing_hours:
        status = "target_hour_still_missing_after_wait"
        reason = "target_utc_hour_still_reported_missing_after_evidence_run"
    else:
        status = "coverage_data_insufficient"
        reason = "latest_quote_coverage_does_not_include_target_hour_state"

    return {
        "status": status,
        "reason": reason,
        "target_quote_coverage_kind": target_kind or "missing_utc_hour_bucket",
        "target_utc_hour": target_hour or None,
        "target_utc_date": target_date or None,
        "target_window_start_utc": target_dt.isoformat() if target_dt is not None else None,
        "target_window_missed": plan.get("target_window_missed"),
        "captured_quote_rows_this_cycle": captured_rows,
        "target_hour_covered": bool(target_hour and target_hour in covered_hours),
        "target_hour_missing": bool(target_hour and target_hour in missing_hours),
        "covered_utc_hours": sorted(covered_hours),
        "missing_utc_hours": sorted(missing_hours),
        "no_live_order_sent": True,
    }


def _pre_run_wait_force_quote_sample(pre_run_wait_plan: dict[str, Any] | None) -> bool:
    plan = dict(pre_run_wait_plan or {})
    if not plan or plan.get("target_window_missed") is True:
        return False

    status = str(plan.get("status") or "")
    waited_or_open = plan.get("actual_sleep_seconds") is not None or status in {
        "current_quote_window_open",
        "next_quote_coverage_window_reached_or_previous_plan_stale",
    }
    if not waited_or_open:
        return False

    target_kind = str(plan.get("target_quote_coverage_kind") or plan.get("next_quote_coverage_kind") or "")
    coverage_status = str(plan.get("coverage_status") or "")
    reason = str(plan.get("reason") or "")
    return (
        target_kind in {"missing_hour_of_day_balance_bucket", "current_utc_calendar_day", "next_utc_calendar_day"}
        or coverage_status == "current_hour_of_day_balance_open"
        or coverage_status == "current_utc_calendar_day_open"
        or reason == "current_hour_of_day_balance_can_advance_microstructure_coverage"
        or reason == "current_utc_calendar_day_can_advance_microstructure_coverage"
    )


def _recent_quote_rows(rows: list[dict[str, Any]], *, generated_at: datetime, recent_hours: float) -> list[dict[str, Any]]:
    cutoff = generated_at - timedelta(hours=max(0.0, float(recent_hours or 0.0)))
    recent: list[dict[str, Any]] = []
    for row in rows:
        parsed = _parse_dt(row.get("timestamp"))
        if parsed is not None and parsed >= cutoff:
            recent.append(row)
    return recent


def _microstructure_coverage_plan(
    *,
    coverage: dict[str, Any],
    latest_collection: dict[str, Any],
    microstructure_watch: dict[str, Any],
    generated_at: datetime,
    quote_capture_command: str | None,
) -> dict[str, Any]:
    generated_at = generated_at.astimezone(UTC)
    current_hour = generated_at.hour
    current_utc_date = generated_at.date().isoformat()
    missing_hours: list[int] = []
    for raw in list(coverage.get("utc_hour_of_day_missing") or []):
        hour = _int_or_default(raw, -1)
        if 0 <= hour <= 23 and hour not in missing_hours:
            missing_hours.append(hour)
    missing_hours.sort()

    if missing_hours:
        next_delta, next_hour = min(((hour - current_hour) % 24, hour) for hour in missing_hours)
        if next_delta == 0:
            next_utc = generated_at
            wait_minutes = 0.0
        else:
            next_utc = generated_at.replace(minute=0, second=0, microsecond=0) + timedelta(hours=next_delta)
            wait_minutes = round(max((next_utc - generated_at).total_seconds(), 0.0) / 60.0, 2)
    else:
        next_hour = None
        next_utc = None
        wait_minutes = None

    calendar_day_count = _int_or_default(
        microstructure_watch.get("calendar_day_count"),
        _int_or_default(latest_collection.get("quote_calendar_days"), 0),
    )
    covered_calendar_days = {str(item) for item in list(microstructure_watch.get("calendar_days") or [])}
    min_calendar_days = max(
        1,
        _int_or_default(
            microstructure_watch.get("min_calendar_days"),
            _int_or_default(latest_collection.get("quote_min_calendar_days"), 30),
        ),
    )
    distinct_hour_count = _int_or_default(
        microstructure_watch.get("distinct_hour_count"),
        _int_or_default(latest_collection.get("quote_distinct_hours"), 0),
    )
    min_distinct_hours = max(
        1,
        _int_or_default(
            microstructure_watch.get("min_distinct_hours"),
            _int_or_default(latest_collection.get("quote_min_distinct_hours"), 24),
        ),
    )
    eligible_rows = _int_or_default(
        microstructure_watch.get("eligible_row_count"),
        _int_or_default(latest_collection.get("quote_observed"), 0),
    )
    required_rows = max(
        1,
        _int_or_default(
            microstructure_watch.get("required_quote_samples"),
            _int_or_default(latest_collection.get("quote_required"), 300),
        ),
    )

    remaining_calendar_days = max(min_calendar_days - calendar_day_count, 0)
    remaining_distinct_hours = max(min_distinct_hours - distinct_hour_count, 0)
    remaining_quote_samples = max(required_rows - eligible_rows, 0)
    hour_of_day_covered_count = _int_or_default(coverage.get("utc_hour_of_day_covered_count"), 0)
    min_hour_of_day_buckets = 24
    remaining_hour_of_day_buckets = max(min_hour_of_day_buckets - hour_of_day_covered_count, 0)
    hour_of_day_balance_needed = remaining_hour_of_day_buckets > 0 and remaining_distinct_hours <= 0
    current_hour_missing = current_hour in set(missing_hours)
    current_date_missing = remaining_calendar_days > 0 and current_utc_date not in covered_calendar_days
    if remaining_calendar_days > 0:
        if current_date_missing:
            next_calendar_utc = generated_at
            calendar_wait_minutes = 0.0
        else:
            next_calendar_utc = (generated_at + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            calendar_wait_minutes = round(max((next_calendar_utc - generated_at).total_seconds(), 0.0) / 60.0, 2)
    else:
        next_calendar_utc = None
        calendar_wait_minutes = None
    if remaining_calendar_days <= 0:
        earliest_calendar_completion_utc = None
    elif current_date_missing:
        if remaining_calendar_days <= 1:
            earliest_calendar_completion_utc = generated_at
        else:
            first_future_day = (generated_at + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            earliest_calendar_completion_utc = first_future_day + timedelta(days=remaining_calendar_days - 2)
    else:
        earliest_calendar_completion_utc = (
            next_calendar_utc + timedelta(days=remaining_calendar_days - 1)
            if next_calendar_utc is not None
            else None
        )
    coverage_candidates: list[tuple[datetime, str]] = []
    if next_utc is not None:
        if remaining_distinct_hours > 0:
            coverage_candidates.append((next_utc, "missing_utc_hour_bucket"))
        elif hour_of_day_balance_needed:
            coverage_candidates.append((next_utc, "missing_hour_of_day_balance_bucket"))
    if next_calendar_utc is not None and remaining_calendar_days > 0:
        coverage_candidates.append(
            (
                next_calendar_utc,
                "current_utc_calendar_day" if current_date_missing else "next_utc_calendar_day",
            )
        )
    if coverage_candidates:
        next_quote_coverage_at, next_quote_coverage_kind = min(coverage_candidates, key=lambda item: item[0])
        next_quote_coverage_wait = round(max((next_quote_coverage_at - generated_at).total_seconds(), 0.0) / 60.0, 2)
    else:
        next_quote_coverage_at = None
        next_quote_coverage_kind = None
        next_quote_coverage_wait = None

    if remaining_quote_samples > 0:
        status = "quote_sample_count_incomplete"
        recommended_action = "collect_quote_samples_now"
        can_collect_now = bool(quote_capture_command)
    elif current_date_missing:
        status = "current_utc_calendar_day_open"
        recommended_action = "collect_current_utc_calendar_day_now"
        can_collect_now = bool(quote_capture_command)
    elif remaining_calendar_days <= 0 and remaining_distinct_hours <= 0:
        status = "coverage_complete"
        recommended_action = "none"
        can_collect_now = False
    elif current_hour_missing:
        if hour_of_day_balance_needed:
            status = "current_hour_of_day_balance_open"
            recommended_action = "collect_current_hour_of_day_balance_now"
        else:
            status = "current_missing_utc_hour_open"
            recommended_action = "collect_current_missing_utc_hour_now"
        can_collect_now = bool(quote_capture_command)
    else:
        status = "waiting_for_next_quote_coverage_window"
        recommended_action = "wait_until_next_quote_coverage_window"
        can_collect_now = False

    return {
        "status": status,
        "generated_at": generated_at.isoformat(),
        "current_utc_date": current_utc_date,
        "current_utc_date_missing": current_date_missing,
        "current_utc_hour": f"{current_hour:02d}",
        "current_utc_hour_missing": current_hour_missing,
        "next_quote_coverage_kind": next_quote_coverage_kind,
        "next_quote_coverage_at": next_quote_coverage_at.isoformat() if next_quote_coverage_at is not None else None,
        "next_quote_coverage_kst_at": next_quote_coverage_at.astimezone(KST).isoformat() if next_quote_coverage_at is not None else None,
        "next_quote_coverage_wait_minutes": next_quote_coverage_wait,
        "next_calendar_day_at": next_calendar_utc.isoformat() if next_calendar_utc is not None else None,
        "next_calendar_kst_at": next_calendar_utc.astimezone(KST).isoformat() if next_calendar_utc is not None else None,
        "next_calendar_wait_minutes": calendar_wait_minutes,
        "earliest_calendar_completion_utc": (
            earliest_calendar_completion_utc.isoformat() if earliest_calendar_completion_utc is not None else None
        ),
        "earliest_calendar_completion_kst": (
            earliest_calendar_completion_utc.astimezone(KST).isoformat()
            if earliest_calendar_completion_utc is not None
            else None
        ),
        "calendar_completion_policy": "one_new_utc_calendar_date_per_day_for_actual_launch_gate",
        "next_missing_utc_hour": f"{next_hour:02d}" if next_hour is not None else None,
        "next_missing_utc_at": next_utc.isoformat() if next_utc is not None else None,
        "next_missing_kst_at": next_utc.astimezone(KST).isoformat() if next_utc is not None else None,
        "wait_minutes": wait_minutes,
        "missing_utc_hour_of_day": [f"{hour:02d}" for hour in missing_hours],
        "remaining_missing_utc_hour_count": len(missing_hours),
        "hour_of_day_covered_count": hour_of_day_covered_count,
        "min_hour_of_day_bucket_count": min_hour_of_day_buckets,
        "remaining_hour_of_day_bucket_count": remaining_hour_of_day_buckets,
        "hour_of_day_balance_needed": hour_of_day_balance_needed,
        "calendar_day_count": calendar_day_count,
        "min_calendar_days": min_calendar_days,
        "covered_calendar_days": sorted(covered_calendar_days),
        "remaining_calendar_days": remaining_calendar_days,
        "distinct_hour_count": distinct_hour_count,
        "min_distinct_hours": min_distinct_hours,
        "remaining_distinct_hours": remaining_distinct_hours,
        "distinct_hour_bucket_count": distinct_hour_count,
        "min_distinct_hour_bucket_count": min_distinct_hours,
        "remaining_distinct_hour_bucket_count": remaining_distinct_hours,
        "coverage_accounting_note": (
            "distinct_hour_bucket_count counts unique UTC hour timestamps for the launch gate; "
            "hour_of_day buckets show 00-23 distribution balance for collection scheduling."
        ),
        "eligible_quote_samples": eligible_rows,
        "required_quote_samples": required_rows,
        "remaining_quote_samples": remaining_quote_samples,
        "can_collect_now": can_collect_now,
        "quote_capture_command": quote_capture_command,
        "recommended_action": recommended_action,
        "no_live_order_sent": True,
    }


def _quote_microstructure_watch(
    *,
    sample_jsonl: Path,
    generated_at: datetime,
    latest_collection: dict[str, Any],
    previous_payload: dict[str, Any],
    recent_hours: float,
) -> dict[str, Any]:
    rows = _load_jsonl(sample_jsonl)
    quote_required = max(1, int(latest_collection.get("quote_required") or 300))
    min_calendar_days = max(1, int(latest_collection.get("quote_min_calendar_days") or 30))
    min_distinct_hours = max(1, int(latest_collection.get("quote_min_distinct_hours") or 24))
    audit = build_quote_shadow_audit_report(
        rows,
        input_sample_path=_display_path(sample_jsonl),
        expected_symbol=EXPECTED_SYMBOL,
        expected_strategy_family=EXPECTED_STRATEGY_FAMILY,
        required_quote_samples=quote_required,
        min_calendar_days=min_calendar_days,
        min_distinct_hours=min_distinct_hours,
        generated_at=generated_at,
    )
    recent_rows = _recent_quote_rows(rows, generated_at=generated_at, recent_hours=recent_hours)
    recent_audit = build_quote_shadow_audit_report(
        recent_rows,
        input_sample_path=_display_path(sample_jsonl),
        expected_symbol=EXPECTED_SYMBOL,
        expected_strategy_family=EXPECTED_STRATEGY_FAMILY,
        required_quote_samples=1,
        min_calendar_days=1,
        min_distinct_hours=1,
        generated_at=generated_at,
    )
    metrics = dict(audit.get("metrics") or {})
    previous_micro = dict(previous_payload.get("microstructure_watch") or {})
    baseline_metrics = dict(previous_micro.get("baseline_metrics") or metrics)
    trend = {
        "p95_spread_bps": _metric_trend_item(
            current=metrics.get("p95_spread_bps"),
            baseline=baseline_metrics.get("p95_spread_bps"),
        ),
        "p95_market_slippage_bps": _metric_trend_item(
            current=metrics.get("p95_market_slippage_bps"),
            baseline=baseline_metrics.get("p95_market_slippage_bps"),
        ),
        "p95_latency_ms": _metric_trend_item(
            current=metrics.get("p95_latency_ms"),
            baseline=baseline_metrics.get("p95_latency_ms"),
        ),
    }
    blockers = list(audit.get("blockers") or [])
    metric_blockers = [
        item
        for item in blockers
        if item in {"p95_spread_bps_failed", "p95_market_slippage_bps_failed", "p95_latency_ms_failed"}
    ]
    if audit.get("eligible_row_count", 0) <= 0:
        status = "no_quote_shadow_rows"
    elif metric_blockers:
        status = "metric_gate_blocked"
    elif audit.get("overall_status") == "PASS":
        status = "microstructure_gates_passed"
    else:
        status = "collecting_sample_day_hour_coverage"
    return {
        "status": status,
        "audit_status": audit.get("overall_status"),
        "sample_path": _display_path(sample_jsonl),
        "row_count": audit.get("row_count"),
        "eligible_row_count": audit.get("eligible_row_count"),
        "required_quote_samples": audit.get("required_quote_samples"),
        "calendar_day_count": audit.get("calendar_day_count"),
        "min_calendar_days": audit.get("min_calendar_days"),
        "calendar_days": list(audit.get("calendar_days") or []),
        "distinct_hour_count": audit.get("distinct_hour_count"),
        "min_distinct_hours": audit.get("min_distinct_hours"),
        "distinct_hours": list(audit.get("distinct_hours") or []),
        "recent_hours": max(0.0, float(recent_hours or 0.0)),
        "recent_eligible_row_count": recent_audit.get("eligible_row_count"),
        "coverage": dict(audit.get("coverage") or {}),
        "metrics": metrics,
        "recent_metrics": dict(recent_audit.get("metrics") or {}),
        "baseline_metrics": baseline_metrics,
        "metric_trend": trend,
        "gates": dict(audit.get("gates") or {}),
        "blockers": blockers,
        "metric_blockers": metric_blockers,
        "no_live_order_sent": True,
    }


def _launch_week_plan(latest: dict[str, Any]) -> list[dict[str, Any]]:
    launch = dict(latest.get("launch_readiness") or {})
    commands = dict(launch.get("operator_commands") or {})
    return [
        {
            "day": 1,
            "objective": "fresh_signal_monitor_and_quote_microstructure_collection",
            "status": "active_now",
            "command": commands.get("microstructure_quote_capture"),
            "success_condition": "fresh_signal_seen_or_quote_microstructure_progress_without_live_orders",
        },
        {
            "day": 2,
            "objective": "paper_bridge_dry_run_when_fresh_signal_appears",
            "status": "blocked_until_fresh_signal",
            "command": commands.get("paper_bridge_dry_run"),
            "success_condition": "paper_bridge_apply_gate_reports_paper_apply_request_available",
        },
        {
            "day": 3,
            "objective": "paper_apply_with_verified_backup_only_if_gate_allows",
            "status": "blocked_until_operator_review_and_fresh_signal",
            "command": commands.get("paper_apply_only_after_fresh_signal"),
            "success_condition": "real_paper_lifecycle_rows_start_accumulating",
        },
        {
            "day": 4,
            "objective": "microstructure_gate_completion",
            "status": "collecting",
            "command": commands.get("microstructure_quote_capture"),
            "success_condition": "spread_slippage_latency_pending_gates_clear",
        },
        {
            "day": 5,
            "objective": "risk_cap_and_kill_switch_review",
            "status": "requires_operator_values",
            "command": None,
            "success_condition": "canary_notional_leverage_daily_loss_caps_configured",
        },
        {
            "day": 6,
            "objective": "24h_shadow_runtime_observation",
            "status": "requires_elapsed_runtime",
            "command": (
                ".venv/bin/python scripts/run_market_state_rotation_v6_launch_shadow_watch.py "
                "--iterations 96 --interval-seconds 900 --target-hours 24 --quote-samples-per-tick 2"
            ),
            "success_condition": "24h_no_live_order_no_duplicate_no_stale_runtime_observed",
        },
        {
            "day": 7,
            "objective": "tiny_canary_review_decision",
            "status": "blocked_until_all_prior_gates_pass",
            "command": None,
            "success_condition": "tiny_canary_evidence_ready_true_but_order_submission_still_requires_operator_promotion",
        },
    ]


def _runtime_progress(*, observed_hours: float, target_hours: float) -> dict[str, Any]:
    target = max(0.0, float(target_hours or 0.0))
    observed = max(0.0, float(observed_hours or 0.0))
    remaining = max(target - observed, 0.0)
    pct = 100.0 if target <= 0.0 else min(observed / target * 100.0, 100.0)
    return {
        "status": "target_complete" if remaining <= 0.0 else "collecting_runtime",
        "observed_hours": round(observed, 4),
        "target_hours": target,
        "remaining_hours": round(remaining, 4),
        "progress_pct": round(pct, 4),
    }


def _pre_run_quote_window_wait_plan(
    *,
    previous_payload: dict[str, Any],
    generated_at: datetime,
    enabled: bool,
    max_wait_seconds: float,
    wakeup_buffer_seconds: float,
) -> dict[str, Any]:
    if not enabled:
        return {
            "status": "disabled",
            "should_sleep": False,
            "wait_seconds": 0.0,
            "no_live_order_sent": True,
        }
    coverage_plan = dict(dict(previous_payload.get("microstructure_watch") or {}).get("coverage_plan") or {})
    if not coverage_plan:
        return {
            "status": "no_previous_coverage_plan",
            "should_sleep": False,
            "wait_seconds": 0.0,
            "reason": "run_watch_once_to_build_coverage_plan_first",
            "no_live_order_sent": True,
        }
    now = generated_at.astimezone(UTC)
    missing_hours_now = {f"{_int_or_default(value, -1):02d}" for value in list(coverage_plan.get("missing_utc_hour_of_day") or [])}
    current_hour = f"{now.hour:02d}"
    current_date = now.date().isoformat()
    current_hour_missing_now = current_hour in missing_hours_now
    covered_calendar_days = {str(item) for item in list(coverage_plan.get("covered_calendar_days") or [])}
    remaining_calendar_days = _int_or_default(coverage_plan.get("remaining_calendar_days"), 0)
    if covered_calendar_days:
        current_date_missing_now = remaining_calendar_days > 0 and current_date not in covered_calendar_days
    elif coverage_plan.get("current_utc_date") == current_date and coverage_plan.get("current_utc_date_missing") is False:
        current_date_missing_now = False
    else:
        current_date_missing_now = remaining_calendar_days > 0
    next_kind = str(coverage_plan.get("next_quote_coverage_kind") or "missing_utc_hour_bucket")
    next_at = _parse_dt(coverage_plan.get("next_quote_coverage_at") or coverage_plan.get("next_missing_utc_at"))
    if coverage_plan.get("can_collect_now") is True or current_hour_missing_now or current_date_missing_now:
        if coverage_plan.get("can_collect_now") is True:
            if coverage_plan.get("status") == "current_hour_of_day_balance_open":
                reason = "current_hour_of_day_balance_can_advance_microstructure_coverage"
            elif current_date_missing_now:
                reason = "current_utc_calendar_day_can_advance_microstructure_coverage"
            elif current_hour_missing_now:
                reason = "current_utc_hour_can_advance_microstructure_coverage"
            else:
                reason = "quote_sample_count_can_advance_now"
        elif current_date_missing_now:
            reason = "current_utc_calendar_day_can_advance_microstructure_coverage"
        else:
            reason = "current_utc_hour_can_advance_microstructure_coverage"
        return {
            "status": "current_quote_window_open",
            "should_sleep": False,
            "wait_seconds": 0.0,
            "reason": reason,
            "current_utc_date": current_date,
            "current_utc_date_missing": current_date_missing_now,
            "current_utc_hour": current_hour,
            "current_utc_hour_missing": current_hour_missing_now,
            "next_quote_coverage_kind": next_kind,
            "next_quote_coverage_at": next_at.isoformat() if next_at is not None else coverage_plan.get("next_quote_coverage_at"),
            "next_quote_coverage_kst_at": next_at.astimezone(KST).isoformat() if next_at is not None else coverage_plan.get("next_quote_coverage_kst_at"),
            "next_missing_utc_at": coverage_plan.get("next_missing_utc_at"),
            "next_missing_kst_at": coverage_plan.get("next_missing_kst_at"),
            "next_missing_utc_hour": coverage_plan.get("next_missing_utc_hour"),
            "coverage_status": coverage_plan.get("status"),
            "no_live_order_sent": True,
        }
    if next_at is None:
        return {
            "status": "next_quote_window_unknown",
            "should_sleep": False,
            "wait_seconds": 0.0,
            "reason": "previous_coverage_plan_has_no_next_quote_coverage_at",
            "coverage_status": coverage_plan.get("status"),
            "no_live_order_sent": True,
        }
    if next_at <= now:
        return {
            "status": "next_quote_coverage_window_reached_or_previous_plan_stale",
            "should_sleep": False,
            "wait_seconds": 0.0,
            "current_utc_date": current_date,
            "current_utc_date_missing": current_date_missing_now,
            "current_utc_hour": current_hour,
            "current_utc_hour_missing": current_hour_missing_now,
            "next_quote_coverage_kind": next_kind,
            "next_quote_coverage_at": next_at.isoformat(),
            "next_quote_coverage_kst_at": next_at.astimezone(KST).isoformat(),
            "next_missing_utc_at": coverage_plan.get("next_missing_utc_at"),
            "next_missing_kst_at": coverage_plan.get("next_missing_kst_at"),
            "next_missing_utc_hour": coverage_plan.get("next_missing_utc_hour"),
            "target_utc_date": next_at.date().isoformat(),
            "calendar_day_count": coverage_plan.get("calendar_day_count"),
            "covered_calendar_days": sorted(covered_calendar_days),
            "coverage_status": coverage_plan.get("status"),
            "reason": "run_watch_now_to_recompute_or_capture_current_quote_coverage_window",
            "no_live_order_sent": True,
        }
    wait_seconds = max((next_at - now).total_seconds(), 0.0) + max(0.0, float(wakeup_buffer_seconds or 0.0))
    max_wait = max(0.0, float(max_wait_seconds or 0.0))
    should_sleep = wait_seconds > 0.0 and wait_seconds <= max_wait
    return {
        "status": "sleep_until_next_quote_coverage_window" if should_sleep else "next_quote_window_wait_exceeds_limit",
        "should_sleep": should_sleep,
        "wait_seconds": round(wait_seconds, 3),
        "max_wait_seconds": max_wait,
        "wakeup_buffer_seconds": max(0.0, float(wakeup_buffer_seconds or 0.0)),
        "next_quote_coverage_kind": next_kind,
        "next_quote_coverage_at": next_at.isoformat(),
        "next_quote_coverage_kst_at": next_at.astimezone(KST).isoformat(),
        "next_missing_utc_at": coverage_plan.get("next_missing_utc_at"),
        "next_missing_kst_at": coverage_plan.get("next_missing_kst_at"),
        "next_missing_utc_hour": coverage_plan.get("next_missing_utc_hour"),
        "target_utc_date": next_at.date().isoformat(),
        "calendar_day_count": coverage_plan.get("calendar_day_count"),
        "covered_calendar_days": sorted(covered_calendar_days),
        "current_utc_date": current_date,
        "current_utc_date_missing": current_date_missing_now,
        "current_utc_hour": current_hour,
        "current_utc_hour_missing": current_hour_missing_now,
        "coverage_status": coverage_plan.get("status"),
        "reason": (
            "wait_is_within_configured_limit"
            if should_sleep
            else "rerun_later_or_raise_max_pre_run_wait_seconds"
        ),
        "no_live_order_sent": True,
    }


def _finalize_pre_run_quote_window_sleep(
    plan: dict[str, Any],
    *,
    sleep_started_at: datetime,
    woke_at: datetime,
) -> dict[str, Any]:
    finalized = dict(plan or {})
    started = sleep_started_at.astimezone(UTC)
    woke = woke_at.astimezone(UTC)
    actual_sleep_seconds = max((woke - started).total_seconds(), 0.0)
    finalized.update(
        {
            "sleep_started_at": started.isoformat(),
            "woke_at": woke.isoformat(),
            "actual_sleep_seconds": round(actual_sleep_seconds, 3),
            "no_live_order_sent": True,
        }
    )
    target_at = _parse_dt(finalized.get("next_quote_coverage_at") or finalized.get("next_missing_utc_at"))
    if target_at is None:
        finalized.update(
            {
                "target_window_missed": False,
                "target_window_missed_reason": None,
                "recovery_action": None,
            }
        )
        return finalized

    target_start = target_at.astimezone(UTC)
    target_kind = str(finalized.get("next_quote_coverage_kind") or "missing_utc_hour_bucket")
    if target_kind in {"current_utc_calendar_day", "next_utc_calendar_day", "new_utc_calendar_day"}:
        target_end = (target_start + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        target_end = target_start + timedelta(hours=1)
    wakeup_lag_seconds = max((woke - target_start).total_seconds(), 0.0)
    overshoot_seconds = max((woke - target_end).total_seconds(), 0.0)
    target_window_missed = woke >= target_end
    finalized.update(
        {
            "target_window_start_utc": target_start.isoformat(),
            "target_window_end_utc": target_end.isoformat(),
            "target_quote_coverage_kind": target_kind,
            "wakeup_lag_seconds": round(wakeup_lag_seconds, 3),
            "wakeup_lag_minutes": round(wakeup_lag_seconds / 60.0, 3),
            "target_window_missed": target_window_missed,
            "overshoot_seconds": round(overshoot_seconds, 3),
            "overshoot_minutes": round(overshoot_seconds / 60.0, 3),
            "target_window_missed_reason": "woke_after_target_window_end" if target_window_missed else None,
            "recovery_action": (
                (
                    "rerun_watch_now_to_capture_current_utc_calendar_day_and_recompute_coverage"
                    if target_kind in {"current_utc_calendar_day", "next_utc_calendar_day", "new_utc_calendar_day"}
                    else "rerun_watch_now_to_capture_current_missing_hour_and_recompute_missed_hours"
                )
                if target_window_missed
                else None
            ),
        }
    )
    return finalized


def _pre_run_quote_window_wait_incident_log(
    *,
    previous_payload: dict[str, Any],
    current_plan: dict[str, Any],
    max_items: int = 20,
) -> list[dict[str, Any]]:
    limit = max(1, int(max_items or 20))
    incidents = [
        dict(item)
        for item in list(previous_payload.get("pre_run_quote_window_wait_incident_log") or [])
        if isinstance(item, dict)
    ][-limit:]
    if current_plan.get("target_window_missed") is True:
        incidents.append(
            {
                "incident_type": "pre_run_quote_window_target_missed",
                "target_window_start_utc": current_plan.get("target_window_start_utc"),
                "target_window_end_utc": current_plan.get("target_window_end_utc"),
                "next_missing_utc_hour": current_plan.get("next_missing_utc_hour"),
                "sleep_started_at": current_plan.get("sleep_started_at"),
                "woke_at": current_plan.get("woke_at"),
                "actual_sleep_seconds": current_plan.get("actual_sleep_seconds"),
                "wakeup_lag_seconds": current_plan.get("wakeup_lag_seconds"),
                "overshoot_seconds": current_plan.get("overshoot_seconds"),
                "overshoot_minutes": current_plan.get("overshoot_minutes"),
                "recovery_action": current_plan.get("recovery_action"),
                "no_live_order_sent": True,
            }
        )
    return incidents[-limit:]


def _execution_parity_eta_plan(
    *,
    execution_parity_plan: dict[str, Any],
    signal_wait_plan: dict[str, Any],
    generated_at: datetime,
) -> dict[str, Any]:
    required = _int_or_default(execution_parity_plan.get("required_samples"), 0)
    missing = _int_or_default(execution_parity_plan.get("missing_samples"), 0)
    events_needed = _int_or_default(execution_parity_plan.get("estimated_future_paper_apply_events_needed"), missing)
    events_after_current = _int_or_default(
        execution_parity_plan.get("estimated_events_needed_after_current_creditable_apply"),
        events_needed,
    )
    if missing <= 0 or events_needed <= 0:
        return {
            "status": "execution_parity_complete",
            "required_samples": required,
            "missing_samples": 0,
            "estimated_future_paper_apply_events_needed": 0,
            "estimated_completion_utc": generated_at.astimezone(UTC).isoformat(),
            "estimated_completion_kst": generated_at.astimezone(KST).isoformat(),
            "non_substitutable": execution_parity_plan.get("non_substitutable") is True,
            "order_submission_allowed": False,
            "no_live_order_sent": True,
        }

    expected_days_per_event = _number_or_none(signal_wait_plan.get("expected_days_per_event"))
    expected_event_interval_hours = _number_or_none(signal_wait_plan.get("expected_event_interval_hours"))
    median_gap_hours = _number_or_none(signal_wait_plan.get("median_gap_hours"))
    expected_days_per_add = _number_or_none(signal_wait_plan.get("expected_days_per_add"))
    expected_add_interval_hours = _number_or_none(signal_wait_plan.get("expected_add_interval_hours"))
    median_add_gap_hours = _number_or_none(signal_wait_plan.get("median_add_gap_hours"))
    next_creditable_events = list(execution_parity_plan.get("next_creditable_event_types") or [])

    def _scenario(name: str, cadence_hours: float | None, cadence_source: str, *, description: str) -> dict[str, Any]:
        row: dict[str, Any] = {
            "name": name,
            "cadence_source": cadence_source,
            "cadence_hours": round(float(cadence_hours), 4) if cadence_hours is not None else None,
            "description": description,
            "available": cadence_hours is not None and cadence_hours > 0,
        }
        if cadence_hours is not None and cadence_hours > 0:
            estimated_hours = max(float(events_needed) * float(cadence_hours), 0.0)
            completion = generated_at.astimezone(UTC) + timedelta(hours=estimated_hours)
            row.update(
                {
                    "estimated_hours": round(estimated_hours, 3),
                    "estimated_days": round(estimated_hours / 24.0, 3),
                    "estimated_completion_utc": completion.isoformat(),
                    "estimated_completion_kst": completion.astimezone(KST).isoformat(),
                }
            )
        return row

    all_event_hours: float | None
    all_event_source: str
    if expected_days_per_event and expected_days_per_event > 0:
        all_event_hours = expected_days_per_event * 24.0
        all_event_source = "signal_wait_plan.expected_days_per_event"
    elif expected_event_interval_hours and expected_event_interval_hours > 0:
        all_event_hours = expected_event_interval_hours
        all_event_source = "signal_wait_plan.expected_event_interval_hours"
    elif median_gap_hours and median_gap_hours > 0:
        all_event_hours = median_gap_hours
        all_event_source = "signal_wait_plan.median_gap_hours"
    else:
        all_event_hours = None
        all_event_source = "unknown"

    add_only_hours: float | None
    add_only_source: str
    if expected_days_per_add and expected_days_per_add > 0:
        add_only_hours = expected_days_per_add * 24.0
        add_only_source = "signal_wait_plan.expected_days_per_add"
    elif expected_add_interval_hours and expected_add_interval_hours > 0:
        add_only_hours = expected_add_interval_hours
        add_only_source = "signal_wait_plan.expected_add_interval_hours"
    elif median_add_gap_hours and median_add_gap_hours > 0:
        add_only_hours = median_add_gap_hours
        add_only_source = "signal_wait_plan.median_add_gap_hours"
    else:
        add_only_hours = None
        add_only_source = "unknown"

    all_creditable = {"add", "remove"}.issubset({str(item) for item in next_creditable_events})
    scenarios = {
        "all_creditable_events": _scenario(
            "all_creditable_events",
            all_event_hours,
            all_event_source,
            description="Uses all fresh add/remove bridge events because both actions can credit execution parity.",
        ),
        "conservative_add_only": _scenario(
            "conservative_add_only",
            add_only_hours,
            add_only_source,
            description="Uses only add cadence as a conservative fallback when remove cadence is ignored.",
        ),
    }
    if all_creditable and scenarios["all_creditable_events"]["available"]:
        selected = scenarios["all_creditable_events"]
        selected_reason = "accepted_actions_include_add_and_remove"
    else:
        selected = scenarios["conservative_add_only"]
        selected_reason = "fallback_to_add_only_cadence"
    cadence_hours = _number_or_none(selected.get("cadence_hours"))
    cadence_source = str(selected.get("cadence_source") or "unknown")

    estimate: dict[str, Any] = {
        "status": (
            "eta_unavailable_without_signal_cadence"
            if cadence_hours is None
            else (
                "eta_from_creditable_event_cadence"
                if selected.get("name") == "all_creditable_events"
                else "eta_from_add_only_signal_cadence"
            )
        ),
        "required_samples": required,
        "eligible_journal_rows": _int_or_default(execution_parity_plan.get("eligible_journal_rows"), 0),
        "missing_samples": missing,
        "estimated_future_paper_apply_events_needed": events_needed,
        "estimated_events_needed_after_current_creditable_apply": events_after_current,
        "sample_credit_per_completed_paper_apply_event": execution_parity_plan.get(
            "sample_credit_per_completed_paper_apply_event"
        ),
        "cadence_source": cadence_source,
        "selected_eta_scenario": selected.get("name"),
        "selected_eta_reason": selected_reason,
        "eta_scenarios": scenarios,
        "expected_days_per_event": expected_days_per_event,
        "expected_event_interval_hours": expected_event_interval_hours,
        "median_gap_hours": median_gap_hours,
        "latest_age_to_median_gap": signal_wait_plan.get("latest_age_to_median_gap"),
        "event_wait_state": signal_wait_plan.get("event_wait_state"),
        "bridge_event_count": signal_wait_plan.get("bridge_event_count"),
        "add_event_count": signal_wait_plan.get("add_event_count"),
        "remove_event_count": signal_wait_plan.get("remove_event_count"),
        "expected_days_per_add": expected_days_per_add,
        "expected_add_interval_hours": expected_add_interval_hours,
        "median_add_gap_hours": median_add_gap_hours,
        "latest_add_age_to_median_gap": signal_wait_plan.get("latest_add_age_to_median_gap"),
        "cadence_lag_level": signal_wait_plan.get("cadence_lag_level"),
        "fresh_signal": execution_parity_plan.get("fresh_signal") is True,
        "paper_apply_available_now": execution_parity_plan.get("paper_apply_available_now") is True,
        "will_credit_current_apply_after_operator_review": (
            execution_parity_plan.get("will_credit_current_apply_after_operator_review") is True
        ),
        "currently_creditable_actions": list(execution_parity_plan.get("currently_creditable_actions") or []),
        "next_creditable_event_types": list(execution_parity_plan.get("next_creditable_event_types") or []),
        "non_substitutable": execution_parity_plan.get("non_substitutable") is True,
        "backtest_substitution_allowed": execution_parity_plan.get("backtest_substitution_allowed") is True,
        "caveat": (
            "Cadence ETA is only an operator planning estimate; execution parity can only be credited by "
            "future fresh signals followed by reviewed paper apply rows, not by forced entries or backtest rows."
        ),
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    if cadence_hours is not None:
        estimated_hours = max(float(events_needed) * float(cadence_hours), 0.0)
        completion = generated_at.astimezone(UTC) + timedelta(hours=estimated_hours)
        estimate.update(
            {
                "estimated_hours_at_current_cadence": round(estimated_hours, 3),
                "estimated_days_at_current_cadence": round(estimated_hours / 24.0, 3),
                "estimated_completion_utc": completion.isoformat(),
                "estimated_completion_kst": completion.astimezone(KST).isoformat(),
            }
        )
    return estimate


def _post_apply_execution_parity_review_command(before_evidence_report: Any) -> str:
    before_report = str(before_evidence_report or "<pre_apply_evidence_report>").strip()
    return (
        ".venv/bin/python scripts/run_market_state_rotation_v6_paper_apply_parity_review.py "
        f"--before-evidence-report {before_report} "
        "--after-evidence-report <post_apply_evidence_report> "
        "--report-dir reports/validation/diagnostics/<paper_apply_parity_review_report_dir> "
        "--write-report"
    )


def _command_tokens(command: Any) -> list[str]:
    text = str(command or "").strip()
    if not text:
        return []
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _has_quote_samples(tokens: list[str], expected: str) -> bool:
    for idx, token in enumerate(tokens[:-1]):
        if token == "--quote-samples-per-tick":
            return tokens[idx + 1] == expected
    return False


def _flag_has_value(tokens: list[str], flag: str) -> bool:
    for idx, token in enumerate(tokens[:-1]):
        if token != flag:
            continue
        value = str(tokens[idx + 1] or "").strip()
        if value and not value.startswith("--"):
            return True
    return False


def _flag_value(tokens: list[str], flag: str) -> str | None:
    for idx, token in enumerate(tokens[:-1]):
        if token != flag:
            continue
        value = str(tokens[idx + 1] or "").strip()
        if value and not value.startswith("--"):
            return value
    return None


def _has_unresolved_placeholder(tokens: list[str]) -> bool:
    return any("<" in str(token) or ">" in str(token) for token in tokens)


def _path_scope_warning(*, value: str | None, expected_prefix: str, warning: str) -> str | None:
    if not value:
        return None
    normalized = str(value).strip().lstrip("./")
    expected = expected_prefix.strip().rstrip("/")
    if normalized == expected or normalized.startswith(f"{expected}/"):
        return None
    return warning


def _flag_positive_int_value(tokens: list[str], flag: str) -> bool:
    value = _flag_value(tokens, flag)
    if value is None:
        return False
    try:
        return int(value) > 0
    except ValueError:
        return False


def _is_forbidden_live_flag(token: Any, live_flags: set[str]) -> bool:
    base = str(token or "").strip().split("=", 1)[0]
    return base in live_flags or base.startswith("--live-order") or base.startswith("--submit-live")


def _pre_apply_evidence_report_status(
    *,
    report_path: Any,
    packet_generated_at: datetime | None,
    review_window_minutes: float,
) -> dict[str, Any]:
    text = str(report_path or "").strip()
    base = {
        "report_path": text or None,
        "packet_generated_at": packet_generated_at.isoformat() if packet_generated_at is not None else None,
        "max_age_minutes": round(float(review_window_minutes), 4),
        "exists": False,
        "fresh": False,
        "block_apply": True,
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    if not text:
        return {**base, "status": "missing_pre_apply_evidence_report_path", "blockers": ["pre_apply_evidence_report_path_missing"]}
    if "<" in text or ">" in text:
        return {**base, "status": "unresolved_pre_apply_evidence_report_placeholder", "blockers": ["pre_apply_evidence_report_has_unresolved_placeholder"]}
    resolved = Path(text)
    if not resolved.is_absolute():
        resolved = ROOT_DIR / resolved
    display_path = _display_path(resolved)
    if not resolved.exists():
        return {
            **base,
            "status": "pre_apply_evidence_report_file_missing",
            "report_path": display_path,
            "blockers": ["pre_apply_evidence_report_file_missing"],
        }
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            **base,
            "status": "pre_apply_evidence_report_unreadable",
            "report_path": display_path,
            "exists": True,
            "error": str(exc),
            "blockers": ["pre_apply_evidence_report_unreadable"],
        }
    if not isinstance(payload, dict):
        return {
            **base,
            "status": "pre_apply_evidence_report_payload_not_object",
            "report_path": display_path,
            "exists": True,
            "blockers": ["pre_apply_evidence_report_payload_not_object"],
        }
    report_generated_at = _parse_dt(payload.get("generated_at"))
    if report_generated_at is None or packet_generated_at is None:
        return {
            **base,
            "status": "pre_apply_evidence_report_timestamp_unavailable",
            "report_path": display_path,
            "exists": True,
            "report_generated_at": report_generated_at.isoformat() if report_generated_at is not None else None,
            "report_no_live_order_sent": payload.get("no_live_order_sent"),
            "blockers": ["pre_apply_evidence_report_timestamp_unavailable"],
        }
    if payload.get("no_live_order_sent") is not True:
        return {
            **base,
            "status": "pre_apply_evidence_report_no_live_safety_unconfirmed",
            "report_path": display_path,
            "exists": True,
            "report_generated_at": report_generated_at.isoformat(),
            "report_no_live_order_sent": payload.get("no_live_order_sent"),
            "blockers": ["pre_apply_evidence_report_no_live_order_sent_not_true"],
        }
    age_minutes = max((packet_generated_at.astimezone(UTC) - report_generated_at.astimezone(UTC)).total_seconds(), 0.0) / 60.0
    max_age = max(0.0, float(review_window_minutes or 0.0))
    if max_age > 0.0 and age_minutes > max_age:
        return {
            **base,
            "status": "pre_apply_evidence_report_stale_for_review_window",
            "report_path": display_path,
            "exists": True,
            "report_generated_at": report_generated_at.isoformat(),
            "report_no_live_order_sent": True,
            "age_minutes": round(age_minutes, 4),
            "blockers": ["pre_apply_evidence_report_stale_for_review_window"],
        }
    return {
        **base,
        "status": "fresh",
        "report_path": display_path,
        "exists": True,
        "fresh": True,
        "block_apply": False,
        "report_generated_at": report_generated_at.isoformat(),
        "report_no_live_order_sent": True,
        "age_minutes": round(age_minutes, 4),
        "blockers": [],
    }


def _paper_apply_command_safety(*, dry_run_command: Any, apply_command: Any) -> dict[str, Any]:
    dry_tokens = _command_tokens(dry_run_command)
    apply_tokens = _command_tokens(apply_command)
    blockers: list[str] = []
    warnings: list[str] = []
    live_flags = {
        "--allow-live-orders",
        "--enable-live",
        "--enable-live-orders",
        "--live",
        "--live-order",
        "--live-trading",
        "--submit-live-order",
    }
    if not dry_tokens:
        blockers.append("dry_run_command_missing")
    if not apply_tokens:
        blockers.append("apply_command_missing")
    if dry_tokens and _has_unresolved_placeholder(dry_tokens):
        blockers.append("dry_run_command_has_unresolved_placeholder")
    if apply_tokens and _has_unresolved_placeholder(apply_tokens):
        blockers.append("apply_command_has_unresolved_placeholder")
    if "--apply-paper-bridge" in dry_tokens:
        blockers.append("dry_run_command_must_not_apply_paper_bridge")
    if apply_tokens and "--apply-paper-bridge" not in apply_tokens:
        blockers.append("apply_command_must_use_apply_paper_bridge")
    if apply_tokens and "--pre-apply-backup-dir" not in apply_tokens:
        blockers.append("apply_command_must_use_pre_apply_backup_dir")
    elif apply_tokens and not _flag_has_value(apply_tokens, "--pre-apply-backup-dir"):
        blockers.append("apply_command_pre_apply_backup_dir_value_missing")
    if apply_tokens and "--refresh-market-data-before-run" not in apply_tokens:
        blockers.append("apply_command_must_refresh_market_data_before_run")
    if dry_tokens and "--refresh-market-data-before-run" not in dry_tokens:
        blockers.append("dry_run_command_must_refresh_market_data_before_run")
    if apply_tokens and "--max-signal-age-minutes" not in apply_tokens:
        blockers.append("apply_command_must_use_max_signal_age_minutes")
    elif apply_tokens and not _flag_has_value(apply_tokens, "--max-signal-age-minutes"):
        blockers.append("apply_command_max_signal_age_minutes_value_missing")
    elif apply_tokens and not _flag_positive_int_value(apply_tokens, "--max-signal-age-minutes"):
        blockers.append("apply_command_max_signal_age_minutes_must_be_positive_integer")
    if dry_tokens and "--max-signal-age-minutes" not in dry_tokens:
        blockers.append("dry_run_command_must_use_max_signal_age_minutes")
    elif dry_tokens and not _flag_has_value(dry_tokens, "--max-signal-age-minutes"):
        blockers.append("dry_run_command_max_signal_age_minutes_value_missing")
    elif dry_tokens and not _flag_positive_int_value(dry_tokens, "--max-signal-age-minutes"):
        blockers.append("dry_run_command_max_signal_age_minutes_must_be_positive_integer")
    if apply_tokens and "--report-dir" not in apply_tokens:
        blockers.append("apply_command_must_write_report_dir")
    elif apply_tokens and not _flag_has_value(apply_tokens, "--report-dir"):
        blockers.append("apply_command_report_dir_value_missing")
    if dry_tokens and "--report-dir" not in dry_tokens:
        blockers.append("dry_run_command_must_write_report_dir")
    elif dry_tokens and not _flag_has_value(dry_tokens, "--report-dir"):
        blockers.append("dry_run_command_report_dir_value_missing")
    if dry_tokens and not _has_quote_samples(dry_tokens, "0"):
        blockers.append("dry_run_command_must_use_quote_samples_per_tick_0")
    if apply_tokens and not _has_quote_samples(apply_tokens, "0"):
        blockers.append("apply_command_must_use_quote_samples_per_tick_0")
    if any(_is_forbidden_live_flag(token, live_flags) for token in [*dry_tokens, *apply_tokens]):
        blockers.append("live_order_flag_present_in_operator_command")
    dry_report_dir = _flag_value(dry_tokens, "--report-dir")
    apply_report_dir = _flag_value(apply_tokens, "--report-dir")
    apply_backup_dir = _flag_value(apply_tokens, "--pre-apply-backup-dir")
    for warning in (
        _path_scope_warning(
            value=dry_report_dir,
            expected_prefix="reports/validation/diagnostics",
            warning="dry_run_report_dir_outside_recommended_diagnostics_scope",
        ),
        _path_scope_warning(
            value=apply_report_dir,
            expected_prefix="reports/validation/diagnostics",
            warning="apply_report_dir_outside_recommended_diagnostics_scope",
        ),
        _path_scope_warning(
            value=apply_backup_dir,
            expected_prefix="reports/db_recovery",
            warning="apply_pre_apply_backup_dir_outside_recommended_recovery_scope",
        ),
    ):
        if warning is not None:
            warnings.append(warning)
    return {
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "warnings": warnings,
        "dry_run_command_checked": bool(dry_tokens),
        "apply_command_checked": bool(apply_tokens),
        "dry_run_report_dir": dry_report_dir,
        "apply_report_dir": apply_report_dir,
        "apply_pre_apply_backup_dir": apply_backup_dir,
        "recommended_report_dir_prefix": "reports/validation/diagnostics",
        "recommended_pre_apply_backup_dir_prefix": "reports/db_recovery",
        "required_apply_flags": [
            "--apply-paper-bridge",
            "--quote-samples-per-tick 0",
            "--refresh-market-data-before-run",
            "--max-signal-age-minutes",
            "--pre-apply-backup-dir",
            "--report-dir",
        ],
        "required_dry_run_flags": [
            "--quote-samples-per-tick 0",
            "--refresh-market-data-before-run",
            "--max-signal-age-minutes",
            "--report-dir",
        ],
        "forbidden_flags": sorted(live_flags),
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _paper_apply_operator_packet(
    *,
    latest: dict[str, Any],
    dry_run_command: Any,
    apply_command: Any,
    apply_allowed_now: bool,
    retry_blocker: dict[str, Any],
    parity_review_blocker: dict[str, Any],
) -> dict[str, Any]:
    launch = dict(latest.get("launch_readiness") or {})
    handoff = dict(launch.get("paper_bridge_handoff") or {})
    apply_gate = dict(latest.get("paper_bridge_apply_gate") or {})
    signal_wait = dict(latest.get("signal_wait_plan") or {})
    packet_generated_at = _parse_dt(latest.get("generated_at"))
    review_window_minutes = _number_or_none(
        signal_wait.get("max_signal_age_minutes") or signal_wait.get("signal_freshness_capture_window_minutes")
    )
    if review_window_minutes is None or review_window_minutes <= 0:
        review_window_minutes = 15.0
    review_deadline = (
        packet_generated_at + timedelta(minutes=float(review_window_minutes))
        if packet_generated_at is not None and apply_allowed_now
        else None
    )
    before_report = latest.get("evidence_report")
    pre_apply_evidence_status = _pre_apply_evidence_report_status(
        report_path=before_report,
        packet_generated_at=packet_generated_at,
        review_window_minutes=float(review_window_minutes),
    )
    command_safety = _paper_apply_command_safety(
        dry_run_command=dry_run_command,
        apply_command=apply_command,
    )
    backup_plan = dict(latest.get("pre_apply_backup_plan") or handoff.get("pre_apply_backup_plan") or {})
    if not backup_plan:
        backup_plan = {
            "status": "plan_missing_using_default_backup_dir",
            "required": True,
            "backup_dir": DEFAULT_PRE_APPLY_BACKUP_DIR,
            "verification_required": True,
            "verification_required_fields": [
                "pre_apply_backup.created == true",
                "pre_apply_backup.quick_check == 'ok'",
                "pre_apply_backup.backup_path is not empty",
            ],
            "no_live_order_sent": True,
        }
    if command_safety.get("status") != "PASS" and apply_allowed_now:
        status = "blocked_by_operator_command_safety"
        blocker = "paper_apply_operator_command_safety"
        apply_allowed_now = False
        review_deadline = None
    elif pre_apply_evidence_status.get("block_apply") is True and apply_allowed_now:
        status = "blocked_by_pre_apply_evidence_report"
        blocker = "pre_apply_evidence_report"
        apply_allowed_now = False
        review_deadline = None
    elif command_safety.get("status") != "PASS" and any(
        "run_market_state_rotation_v6_evidence_cycle.py" in str(command or "")
        for command in (dry_run_command, apply_command)
    ):
        status = "operator_command_safety_preflight_failed"
        blocker = "paper_apply_operator_command_safety"
        apply_allowed_now = False
        review_deadline = None
    elif parity_review_blocker.get("blocked") is True:
        status = "blocked_by_post_apply_parity_review"
        blocker = "paper_apply_parity_review_blocker"
    elif retry_blocker.get("blocked") is True:
        status = "blocked_by_retry_guard"
        blocker = "paper_apply_retry_blocker"
    elif apply_allowed_now:
        status = "ready_for_operator_review"
        blocker = None
    elif apply_gate.get("fresh_signal") is not True:
        status = "armed_waiting_for_fresh_signal"
        blocker = "current_fresh_signal"
    else:
        status = "blocked_until_apply_gate_available"
        blocker = "paper_bridge_apply_gate"
    return {
        "status": status,
        "blocker": blocker,
        "pre_apply_evidence_report": before_report,
        "pre_apply_evidence_report_status": pre_apply_evidence_status,
        "packet_generated_at": packet_generated_at.isoformat() if packet_generated_at is not None else None,
        "operator_review_window_minutes": round(float(review_window_minutes), 4),
        "operator_review_deadline_utc": review_deadline.isoformat() if review_deadline is not None else None,
        "operator_review_deadline_kst": review_deadline.astimezone(KST).isoformat()
        if review_deadline is not None
        else None,
        "operator_review_deadline_active": review_deadline is not None,
        "deadline_policy": (
            "operator_command_safety_failed_rerun_dry_run_before_apply"
            if command_safety.get("status") != "PASS"
            else "pre_apply_evidence_report_failed_rerun_dry_run_before_apply"
            if status == "blocked_by_pre_apply_evidence_report"
            else "apply_command_expires_at_operator_review_deadline_rerun_dry_run_after_deadline"
            if review_deadline is not None
            else "deadline_arms_when_fresh_signal_and_apply_gate_open"
        ),
        "rerun_command_after_deadline": dry_run_command,
        "dry_run_command": dry_run_command,
        "apply_command_allowed_now": apply_command if apply_allowed_now else None,
        "apply_command_when_gate_allows": apply_command,
        "command_safety": command_safety,
        "post_apply_execution_parity_review_command": _post_apply_execution_parity_review_command(before_report),
        "pre_apply_backup_plan": backup_plan,
        "verified_pre_apply_backup_required": True,
        "backup_verification_required_fields": list(backup_plan.get("verification_required_fields") or []),
        "post_apply_review_required": True,
        "operator_sequence": [
            "review_current_dry_run_report_and_confirm_bridge_status_dry_run_actionable",
            "confirm_pre_apply_evidence_report_exists_is_fresh_and_no_live_order_sent_true",
            "confirm_current_fresh_signal_and_paper_apply_gate_are_open",
            "rerun_dry_run_if_operator_review_deadline_has_passed",
            "run_apply_command_only_if_apply_command_allowed_now_is_present",
            "verify_pre_apply_backup_created_quick_check_ok_and_backup_path_present",
            "run_post_apply_execution_parity_review_before_next_paper_apply",
        ],
        "paper_apply_retry_blocker": retry_blocker,
        "paper_apply_parity_review_blocker": parity_review_blocker,
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _operator_handoff(
    *,
    latest: dict[str, Any],
    progress: dict[str, Any],
    runtime_progress: dict[str, Any],
    risk_caps: dict[str, Any],
    microstructure_watch: dict[str, Any],
    recent_paper_apply: dict[str, Any] | None = None,
    recent_paper_review: dict[str, Any] | None = None,
    recent_paper_apply_parity_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    launch = dict(latest.get("launch_readiness") or {})
    commands = dict(launch.get("operator_commands") or {})
    handoff = dict(launch.get("paper_bridge_handoff") or {})
    execution_parity_plan = dict(latest.get("execution_parity_collection_plan") or {})
    signal_wait_plan = dict(latest.get("signal_wait_plan") or {})
    next_blocker = dict(launch.get("next_blocker") or {})
    can_request_paper_apply = handoff.get("apply_allowed_now") is True
    paper_apply_retry_blocker = _paper_apply_retry_blocker(
        latest,
        dict(recent_paper_apply or {}),
        dict(recent_paper_review or {}),
    )
    if paper_apply_retry_blocker.get("blocked") is True:
        can_request_paper_apply = False
    parity_review = dict(recent_paper_apply_parity_review or {})
    parity_review_blocks_apply = parity_review.get("blocks_next_paper_apply") is True
    if parity_review_blocks_apply:
        can_request_paper_apply = False
    risk_caps_configured = risk_caps.get("configured") is True
    runtime_complete = runtime_progress.get("status") == "target_complete"
    microstructure_clear = microstructure_watch.get("status") == "microstructure_gates_passed"
    if can_request_paper_apply:
        status = "paper_bridge_operator_review_available"
        next_action = "operator_review_paper_bridge_dry_run_then_apply_with_verified_backup"
    elif parity_review_blocks_apply:
        status = "paper_apply_parity_review_blocking_next_apply"
        next_action = "resolve_recent_paper_apply_parity_review_before_reapplying_paper_bridge"
    elif paper_apply_retry_blocker.get("blocked") is True:
        status = "paper_bridge_remove_apply_no_open_plan_waiting_for_add"
        next_action = "wait_for_next_add_signal_or_existing_open_paper_plan_before_reapplying_remove"
    elif progress.get("fresh_signal_seen") is True:
        status = "fresh_signal_seen_but_paper_apply_not_yet_available"
        next_action = "inspect_paper_bridge_apply_gate_before_any_apply"
    elif not risk_caps_configured:
        status = "waiting_for_fresh_signal_and_canary_risk_caps"
        next_action = "monitor_fresh_signal_and_prepare_canary_risk_caps_file"
    else:
        status = "waiting_for_fresh_signal"
        next_action = "monitor_fresh_signal_without_forcing_entry"
    canary_review_blockers = []
    if not launch.get("tiny_canary_evidence_ready"):
        canary_review_blockers = [
            item.get("gate")
            for item in list(launch.get("blocking_gates") or [])
            if item.get("passed") is not True and item.get("gate")
        ]
    paper_dry_run_command = handoff.get("dry_run_command") or commands.get("paper_bridge_dry_run")
    paper_apply_command = handoff.get("apply_command") or commands.get("paper_apply_only_after_fresh_signal")
    parity_review_blocker = {
        "blocked": parity_review_blocks_apply,
        "status": parity_review.get("status"),
        "source_report": parity_review.get("source_report"),
        "blockers": list(parity_review.get("blockers") or []),
        "next_actions": list(parity_review.get("next_actions") or []),
        "recommended_command": parity_review.get("recommended_command"),
        "no_live_order_sent": True,
    }
    paper_apply_operator_packet = _paper_apply_operator_packet(
        latest=latest,
        dry_run_command=paper_dry_run_command,
        apply_command=paper_apply_command,
        apply_allowed_now=can_request_paper_apply,
        retry_blocker=paper_apply_retry_blocker,
        parity_review_blocker=parity_review_blocker,
    )
    if can_request_paper_apply and paper_apply_operator_packet.get("status") != "ready_for_operator_review":
        can_request_paper_apply = False
        status = str(paper_apply_operator_packet.get("status") or "paper_apply_operator_packet_blocked")
        next_action = str(
            paper_apply_operator_packet.get("blocker")
            or "resolve_paper_apply_operator_packet_before_apply"
        )
    elif paper_apply_operator_packet.get("status") == "operator_command_safety_preflight_failed":
        status = "paper_apply_operator_command_safety_preflight_failed"
        next_action = "fix_operator_command_safety_before_waiting_for_fresh_signal"
    return {
        "status": status,
        "next_action": next_action,
        "next_blocker": next_blocker.get("gate"),
        "paper_apply_allowed_now": can_request_paper_apply,
        "paper_apply_retry_blocker": paper_apply_retry_blocker,
        "recent_paper_apply": dict(recent_paper_apply or {}),
        "recent_paper_review": dict(recent_paper_review or {}),
        "recent_paper_apply_parity_review": parity_review,
        "paper_apply_parity_review_blocker": parity_review_blocker,
        "paper_apply_operator_packet": paper_apply_operator_packet,
        "pre_apply_backup_plan": dict(paper_apply_operator_packet.get("pre_apply_backup_plan") or {}),
        "paper_handoff_status": handoff.get("status"),
        "execution_parity_collection_plan": execution_parity_plan,
        "execution_parity_eta_plan": _execution_parity_eta_plan(
            execution_parity_plan=execution_parity_plan,
            signal_wait_plan=signal_wait_plan,
            generated_at=_parse_dt(latest.get("generated_at")) or datetime.now(UTC),
        ),
        "execution_parity_will_credit_current_apply": (
            execution_parity_plan.get("will_credit_current_apply_after_operator_review") is True
        ),
        "execution_parity_events_needed": execution_parity_plan.get("estimated_future_paper_apply_events_needed"),
        "execution_parity_events_needed_after_current_apply": execution_parity_plan.get(
            "estimated_events_needed_after_current_creditable_apply"
        ),
        "execution_parity_creditable_actions": list(execution_parity_plan.get("currently_creditable_actions") or []),
        "paper_dry_run_command": paper_dry_run_command,
        "paper_apply_command": paper_apply_command,
        "quote_capture_command": commands.get("microstructure_quote_capture"),
        "risk_caps_configured": risk_caps_configured,
        "risk_caps_status": risk_caps.get("status"),
        "risk_caps_errors": list(risk_caps.get("errors") or []),
        "runtime_complete": runtime_complete,
        "runtime_remaining_hours": runtime_progress.get("remaining_hours"),
        "microstructure_clear": microstructure_clear,
        "microstructure_status": microstructure_watch.get("status"),
        "canary_review_ready": launch.get("tiny_canary_evidence_ready") is True,
        "canary_review_blockers": canary_review_blockers,
        "operator_review_required": True,
        "verified_pre_apply_backup_required": True,
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _blocker_resolution_plan(
    *,
    latest: dict[str, Any],
    progress: dict[str, Any],
    runtime_progress: dict[str, Any],
    risk_caps: dict[str, Any],
    microstructure_watch: dict[str, Any],
    operator_handoff: dict[str, Any],
) -> list[dict[str, Any]]:
    launch = dict(latest.get("launch_readiness") or {})
    signal_wait = dict(latest.get("signal_wait_plan") or {})
    market_data = dict(latest.get("market_data_refresh_plan") or {})
    safety = dict(latest.get("launch_safety_controls") or {})
    apply_gate = dict(latest.get("paper_bridge_apply_gate") or {})
    execution_parity_plan = dict(
        latest.get("execution_parity_collection_plan")
        or operator_handoff.get("execution_parity_collection_plan")
        or {}
    )
    latest_collection = dict(latest.get("collection_progress") or {})
    commands = dict(launch.get("operator_commands") or {})
    plans: list[dict[str, Any]] = []
    for gate in list(launch.get("blocking_gates") or []):
        gate_name = str(gate.get("gate") or "")
        item = {
            "gate": gate_name,
            "blocker": gate.get("blocker"),
            "current_status": "blocking",
            "can_resolve_now": False,
            "automation_safe": True,
            "requires_operator_review": False,
            "next_action": gate.get("next_action"),
            "command": None,
            "reason": None,
            "no_live_order_sent": True,
        }
        if gate_name == "current_market_data_fresh":
            item.update(
                {
                    "can_resolve_now": bool(market_data.get("cache_refresh_command")),
                    "command": market_data.get("cache_refresh_command"),
                    "follow_up_command": market_data.get("evidence_rerun_command"),
                    "reason": "refresh_runtime_cache_then_rerun_evidence_cycle",
                }
            )
        elif gate_name == "current_fresh_signal":
            item.update(
                {
                    "can_resolve_now": False,
                    "command": signal_wait.get("command") or commands.get("signal_monitor"),
                    "reason": "must_wait_for_realtime_v6_add_or_remove_signal_do_not_force_entry",
                    "next_monitor_after_utc": signal_wait.get("next_monitor_after_utc"),
                    "next_monitor_after_kst": signal_wait.get("next_monitor_after_kst"),
                    "cadence_recommended_monitor_interval_minutes": signal_wait.get(
                        "cadence_recommended_monitor_interval_minutes"
                    ),
                    "recommended_monitor_interval_minutes": signal_wait.get("recommended_monitor_interval_minutes"),
                    "signal_freshness_capture_window_minutes": signal_wait.get(
                        "signal_freshness_capture_window_minutes"
                    ),
                    "monitor_interval_capped_by_signal_freshness": signal_wait.get(
                        "monitor_interval_capped_by_signal_freshness"
                    )
                    is True,
                    "monitor_signal_age_alignment": signal_wait.get("monitor_signal_age_alignment"),
                    "cadence_lag_level": signal_wait.get("cadence_lag_level"),
                }
            )
        elif gate_name == "real_paper_lifecycle_rows":
            can_apply_paper_now = operator_handoff.get("paper_apply_allowed_now") is True
            paper_apply_retry_blocker = dict(operator_handoff.get("paper_apply_retry_blocker") or {})
            parity_review_blocker = dict(operator_handoff.get("paper_apply_parity_review_blocker") or {})
            paper_apply_operator_packet = dict(operator_handoff.get("paper_apply_operator_packet") or {})
            fresh_signal = apply_gate.get("fresh_signal") is True
            monitor_command = (
                signal_wait.get("command")
                or commands.get("signal_monitor")
                or operator_handoff.get("paper_dry_run_command")
            )
            next_monitor_after_utc = (
                paper_apply_retry_blocker.get("next_monitor_after_utc")
                if paper_apply_retry_blocker.get("blocked") is True
                else signal_wait.get("next_monitor_after_utc")
            )
            next_monitor_after_kst = (
                paper_apply_retry_blocker.get("next_monitor_after_kst")
                if paper_apply_retry_blocker.get("blocked") is True
                else signal_wait.get("next_monitor_after_kst")
            )
            if can_apply_paper_now:
                reason = "paper_bridge_apply_available_after_operator_review_and_verified_backup"
            elif parity_review_blocker.get("blocked") is True:
                reason = "recent_paper_apply_parity_review_blocks_next_apply"
            elif paper_apply_retry_blocker.get("blocked") is True:
                reason = str(
                    paper_apply_retry_blocker.get("reason")
                    or "recent_remove_paper_apply_found_no_open_v6_paper_plan"
                )
            elif fresh_signal:
                reason = "fresh_signal_seen_but_paper_bridge_apply_gate_not_available"
            else:
                reason = "must_wait_for_fresh_signal_before_paper_bridge_apply"
            item.update(
                {
                    "can_resolve_now": can_apply_paper_now,
                    "requires_operator_review": True,
                    "command": operator_handoff.get("paper_apply_command") if can_apply_paper_now else None,
                    "dry_run_command": operator_handoff.get("paper_dry_run_command"),
                    "monitor_command": monitor_command,
                    "next_monitor_after_utc": next_monitor_after_utc,
                    "next_monitor_after_kst": next_monitor_after_kst,
                    "recommended_monitor_interval_minutes": signal_wait.get("recommended_monitor_interval_minutes"),
                    "paper_apply_command_when_gate_allows": operator_handoff.get("paper_apply_command"),
                    "reason": reason,
                    "fresh_signal": fresh_signal,
                    "can_request_paper_apply_now": apply_gate.get("can_request_paper_apply_now") is True,
                    "paper_apply_retry_blocked": paper_apply_retry_blocker.get("blocked") is True,
                    "paper_apply_retry_blocker": paper_apply_retry_blocker,
                    "paper_apply_parity_review_blocked": parity_review_blocker.get("blocked") is True,
                    "paper_apply_parity_review_blocker": parity_review_blocker,
                    "paper_handoff_status": operator_handoff.get("paper_handoff_status"),
                    "paper_fill_rows": latest_collection.get("paper_fill_rows"),
                    "pre_apply_evidence_report": latest.get("evidence_report"),
                    "pre_apply_backup_plan": dict(paper_apply_operator_packet.get("pre_apply_backup_plan") or {}),
                    "paper_apply_operator_packet": paper_apply_operator_packet,
                    "post_apply_execution_parity_review_command": paper_apply_operator_packet.get(
                        "post_apply_execution_parity_review_command"
                    )
                    or _post_apply_execution_parity_review_command(latest.get("evidence_report")),
                    "execution_parity_collection_status": execution_parity_plan.get("status"),
                    "execution_parity_will_credit_current_apply": (
                        execution_parity_plan.get("will_credit_current_apply_after_operator_review") is True
                    ),
                    "execution_parity_events_needed": execution_parity_plan.get(
                        "estimated_future_paper_apply_events_needed"
                    ),
                    "execution_parity_events_needed_after_current_apply": execution_parity_plan.get(
                        "estimated_events_needed_after_current_creditable_apply"
                    ),
                    "execution_parity_creditable_actions": list(
                        execution_parity_plan.get("currently_creditable_actions") or []
                    ),
                    "execution_parity_accepted_actions": list(execution_parity_plan.get("accepted_actions") or []),
                    "execution_parity_non_substitutable": execution_parity_plan.get("non_substitutable") is True,
                    "verified_pre_apply_backup_required": True,
                    "order_submission_allowed": False,
                }
            )
        elif gate_name == "real_microstructure_execution_evidence":
            sample_blockers = [
                blocker
                for blocker in list(microstructure_watch.get("blockers") or [])
                if blocker not in set(microstructure_watch.get("metric_blockers") or [])
            ]
            coverage = dict(microstructure_watch.get("coverage") or {})
            coverage_plan = dict(microstructure_watch.get("coverage_plan") or {})
            immediate_quote_capture = "quote_samples_missing" in set(sample_blockers)
            time_coverage_blocked = bool({"calendar_days_missing", "distinct_hours_missing"} & set(sample_blockers))
            current_missing_hour_open = coverage_plan.get("current_utc_hour_missing") is True
            current_hour_balance_open = coverage_plan.get("status") == "current_hour_of_day_balance_open"
            current_utc_date_open = coverage_plan.get("current_utc_date_missing") is True
            can_capture_now = bool(
                (
                    immediate_quote_capture
                    or (time_coverage_blocked and (current_missing_hour_open or current_utc_date_open))
                )
                and operator_handoff.get("quote_capture_command")
            )
            item.update(
                {
                    "can_resolve_now": can_capture_now,
                    "command": operator_handoff.get("quote_capture_command"),
                    "reason": (
                        "collect_additional_quote_samples_now"
                        if immediate_quote_capture
                        else "collect_current_hour_of_day_balance_now"
                        if current_hour_balance_open
                        else "collect_current_missing_utc_hour_now"
                        if time_coverage_blocked and current_missing_hour_open
                        else "collect_current_utc_calendar_day_now"
                        if time_coverage_blocked and current_utc_date_open
                        else "requires_new_calendar_days_or_missing_utc_hour_windows"
                        if time_coverage_blocked
                        else microstructure_watch.get("status") or "collect_spread_slippage_latency_evidence"
                    ),
                    "metric_blockers": list(microstructure_watch.get("metric_blockers") or []),
                    "sample_blockers": sample_blockers,
                    "missing_utc_hour_of_day": list(coverage.get("utc_hour_of_day_missing") or []),
                    "covered_utc_hour_count": coverage.get("utc_hour_of_day_covered_count"),
                    "latest_sample_age_hours": coverage.get("latest_sample_age_hours"),
                    "coverage_plan": coverage_plan,
                    "current_utc_date": coverage_plan.get("current_utc_date"),
                    "current_utc_date_missing": coverage_plan.get("current_utc_date_missing"),
                    "next_quote_coverage_kind": coverage_plan.get("next_quote_coverage_kind"),
                    "next_quote_coverage_at": coverage_plan.get("next_quote_coverage_at"),
                    "next_quote_coverage_kst_at": coverage_plan.get("next_quote_coverage_kst_at"),
                    "next_quote_coverage_wait_minutes": coverage_plan.get("next_quote_coverage_wait_minutes"),
                    "next_missing_utc_hour": coverage_plan.get("next_missing_utc_hour"),
                    "next_missing_utc_at": coverage_plan.get("next_missing_utc_at"),
                    "next_missing_kst_at": coverage_plan.get("next_missing_kst_at"),
                    "wait_minutes": coverage_plan.get("wait_minutes"),
                    "remaining_calendar_days": coverage_plan.get("remaining_calendar_days"),
                    "earliest_calendar_completion_utc": coverage_plan.get("earliest_calendar_completion_utc"),
                    "earliest_calendar_completion_kst": coverage_plan.get("earliest_calendar_completion_kst"),
                    "calendar_completion_policy": coverage_plan.get("calendar_completion_policy"),
                    "remaining_distinct_hours": coverage_plan.get("remaining_distinct_hours"),
                    "remaining_distinct_hour_bucket_count": coverage_plan.get("remaining_distinct_hour_bucket_count"),
                    "remaining_hour_of_day_bucket_count": coverage_plan.get("remaining_hour_of_day_bucket_count"),
                    "hour_of_day_covered_count": coverage_plan.get("hour_of_day_covered_count"),
                    "remaining_quote_samples": coverage_plan.get("remaining_quote_samples"),
                }
            )
        elif gate_name == "shadow_runtime_24h_observed":
            item.update(
                {
                    "can_resolve_now": False,
                    "reason": "requires_calendar_runtime_observation_not_backtest_substitution",
                    "remaining_hours": runtime_progress.get("remaining_hours"),
                    "progress_pct": runtime_progress.get("progress_pct"),
                }
            )
        elif gate_name == "tiny_canary_risk_caps_configured":
            review = dict(risk_caps.get("operator_review") or {})
            item.update(
                {
                    "can_resolve_now": False,
                    "requires_operator_review": True,
                    "reason": risk_caps.get("status") or "risk_caps_file_missing_or_invalid",
                    "errors": list(risk_caps.get("errors") or []),
                    "required_safeguards": dict(risk_caps.get("required_safeguards") or {}),
                    "template_path": review.get(
                        "template_path",
                        "reports/operations/market_state_rotation_v6_canary_risk_caps.template.json",
                    ),
                    "target_config_path": review.get("target_config_path"),
                    "safe_template_copy_command": review.get("safe_template_copy_command"),
                    "quick_audit_command": review.get("quick_audit_command"),
                    "validation_command": review.get("validation_command"),
                    "review_checklist": list(review.get("review_checklist") or []),
                }
            )
        elif gate_name == "order_safety_controls_verified":
            item.update(
                {
                    "can_resolve_now": True,
                    "requires_operator_review": True,
                    "command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_manual_safety_drills.py "
                        "--write-report --report-dir reports/validation/diagnostics/<manual_safety_drills_report_dir>"
                    ),
                    "follow_up_command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_safety_controls_audit.py "
                        "--evidence reports/validation/diagnostics/<manual_safety_drills_report_dir>/"
                        "market_state_rotation_v6_manual_safety_evidence.json "
                        "--write-report --report-dir reports/validation/diagnostics/<safety_controls_report_dir>"
                    ),
                    "reason": safety.get("overall_status") or "safety_controls_missing_or_incomplete",
                    "verified_count": safety.get("verified_count"),
                    "required_count": safety.get("required_count"),
                    "missing_or_failed": list(safety.get("missing_or_failed") or []),
                }
            )
        plans.append(item)
    return plans


def _action_report_suffix(generated_at: datetime, action_type: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in str(action_type or "action").lower()).strip("_")
    return f"market_state_rotation_v6_launch_{normalized}_{generated_at.astimezone(UTC):%Y%m%d_%H%M%SZ}"


def _materialize_action_command(command: Any, *, generated_at: datetime, action_type: str) -> str | None:
    text = str(command or "").strip()
    if not text:
        return None
    suffix = _action_report_suffix(generated_at, action_type)
    replacements = {
        "<signal_monitor_report_dir>": suffix,
        "<missed_quote_window_recompute_report_dir>": suffix,
        "<manual_safety_drills_report_dir>": suffix,
        "<safety_controls_report_dir>": suffix,
        "<paper_apply_parity_review_report_dir>": suffix,
    }
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    return text


def _materialize_operator_packet(packet: dict[str, Any], *, generated_at: datetime) -> dict[str, Any]:
    if not packet:
        return {}
    out = dict(packet)
    out["post_apply_execution_parity_review_command"] = _materialize_action_command(
        out.get("post_apply_execution_parity_review_command"),
        generated_at=generated_at,
        action_type="paper_apply_parity_review",
    )
    deadline = _parse_dt(out.get("operator_review_deadline_utc"))
    deadline_expired = deadline is not None and generated_at.astimezone(UTC) >= deadline.astimezone(UTC)
    out["operator_review_deadline_expired"] = deadline_expired
    if deadline_expired:
        out["original_status_before_deadline_expiry"] = out.get("status")
        out["status"] = "operator_review_deadline_expired"
        out["blocker"] = "operator_review_deadline_expired"
        out["apply_command_allowed_now"] = None
        out["deadline_policy"] = "operator_review_deadline_expired_rerun_dry_run_before_apply"
    return out


def _action_due_state(scheduled_at: Any, *, generated_at: datetime) -> dict[str, Any]:
    due_at = _parse_dt(scheduled_at)
    if due_at is None:
        return {
            "can_run_now": True,
            "execute_after_utc": None,
            "execute_after_kst": None,
            "wait_minutes": 0.0,
        }
    now = generated_at.astimezone(UTC)
    wait_seconds = max((due_at - now).total_seconds(), 0.0)
    return {
        "can_run_now": wait_seconds <= 0.0,
        "execute_after_utc": due_at.isoformat(),
        "execute_after_kst": due_at.astimezone(KST).isoformat(),
        "wait_minutes": round(wait_seconds / 60.0, 3),
    }


def _safe_next_action_plan(
    *,
    blocker_resolution_plan: list[dict[str, Any]],
    runtime_progress: dict[str, Any],
    microstructure_watch: dict[str, Any],
    operator_handoff: dict[str, Any],
    meta_router_promotion_gate: dict[str, Any] | None = None,
    target_hours: float,
    generated_at: datetime,
) -> dict[str, Any]:
    by_gate = {str(item.get("gate") or ""): dict(item) for item in blocker_resolution_plan}
    actions: list[dict[str, Any]] = []
    operator_packet = _materialize_operator_packet(
        dict(operator_handoff.get("paper_apply_operator_packet") or {}),
        generated_at=generated_at,
    )
    operator_packet_command_safety = dict(operator_packet.get("command_safety") or {})
    operator_packet_pre_apply_evidence = dict(operator_packet.get("pre_apply_evidence_report_status") or {})
    if operator_packet_command_safety.get("status") == "FAIL":
        actions.append(
            {
                "priority": 8,
                "action_type": "fix_paper_apply_operator_command_safety",
                "target_gate": "paper_apply_operator_command_safety",
                "can_run_now": True,
                "requires_operator_review": True,
                "command": None,
                "reason": "operator_command_safety_failed_before_paper_apply",
                "blockers": list(operator_packet_command_safety.get("blockers") or []),
                "warnings": list(operator_packet_command_safety.get("warnings") or []),
                "dry_run_report_dir": operator_packet_command_safety.get("dry_run_report_dir"),
                "apply_report_dir": operator_packet_command_safety.get("apply_report_dir"),
                "pre_apply_backup_dir": operator_packet_command_safety.get("apply_pre_apply_backup_dir"),
                "paper_apply_operator_packet": operator_packet,
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        )
    if operator_packet.get("status") == "blocked_by_pre_apply_evidence_report":
        actions.append(
            {
                "priority": 9,
                "action_type": "rerun_paper_bridge_dry_run_for_fresh_pre_apply_evidence_report",
                "target_gate": "pre_apply_evidence_report",
                "can_run_now": True,
                "requires_operator_review": False,
                "command": operator_packet.get("rerun_command_after_deadline") or operator_packet.get("dry_run_command"),
                "reason": "pre_apply_evidence_report_not_fresh_for_paper_apply",
                "blockers": list(operator_packet_pre_apply_evidence.get("blockers") or []),
                "pre_apply_evidence_report_status": operator_packet_pre_apply_evidence,
                "paper_apply_operator_packet": operator_packet,
                "follow_up_command_when_reviewed": None,
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        )

    micro = by_gate.get("real_microstructure_execution_evidence")
    if micro:
        coverage_plan = dict(micro.get("coverage_plan") or microstructure_watch.get("coverage_plan") or {})
        next_quote_coverage_at = coverage_plan.get("next_quote_coverage_at") or coverage_plan.get("next_missing_utc_at")
        next_quote_coverage_kst_at = coverage_plan.get("next_quote_coverage_kst_at") or coverage_plan.get("next_missing_kst_at")
        wait_minutes = _number_or_none(
            coverage_plan.get("next_quote_coverage_wait_minutes")
            if coverage_plan.get("next_quote_coverage_wait_minutes") is not None
            else coverage_plan.get("wait_minutes")
        )
        max_pre_run_wait_seconds = max(3600, int(float(wait_minutes or 0.0) * 60.0 + 120.0))
        if micro.get("can_resolve_now") is True and micro.get("command"):
            actions.append(
                {
                    "priority": 5,
                    "action_type": "capture_microstructure_quote_window_now",
                    "target_gate": "real_microstructure_execution_evidence",
                    "can_run_now": True,
                    "requires_operator_review": False,
                    "command": micro.get("command"),
                    "reason": micro.get("reason") or "current_quote_window_can_advance_microstructure_coverage",
                    "current_utc_date_missing": coverage_plan.get("current_utc_date_missing"),
                    "next_quote_coverage_kind": coverage_plan.get("next_quote_coverage_kind"),
                    "next_missing_utc_hour": coverage_plan.get("next_missing_utc_hour"),
                    "order_submission_allowed": False,
                    "no_live_order_sent": True,
                }
            )
        elif next_quote_coverage_at:
            actions.append(
                {
                    "priority": 50,
                    "action_type": "wait_for_next_microstructure_quote_window",
                    "target_gate": "real_microstructure_execution_evidence",
                    "can_run_now": False,
                    "can_start_now": True,
                    "waits_until_execution_window": True,
                    "requires_operator_review": False,
                    "command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_launch_shadow_watch.py "
                        "--iterations 1 --interval-seconds 0 "
                        f"--target-hours {float(target_hours or 24.0):g} "
                        "--quote-samples-per-tick 2 "
                        "--sleep-until-next-quote-coverage-window "
                        f"--max-pre-run-wait-seconds {max_pre_run_wait_seconds} "
                        "--report-dir reports/operations/market_state_rotation_v6_launch_shadow_watch_heartbeat "
                        "--evidence-report-root reports/validation/diagnostics --quiet"
                    ),
                    "reason": "wait_until_next_quote_coverage_window",
                    "execute_after_utc": next_quote_coverage_at,
                    "execute_after_kst": next_quote_coverage_kst_at,
                    "next_quote_coverage_kind": coverage_plan.get("next_quote_coverage_kind"),
                    "next_quote_coverage_at": next_quote_coverage_at,
                    "next_quote_coverage_kst_at": next_quote_coverage_kst_at,
                    "next_quote_coverage_wait_minutes": wait_minutes,
                    "current_utc_date": coverage_plan.get("current_utc_date"),
                    "current_utc_date_missing": coverage_plan.get("current_utc_date_missing"),
                    "next_missing_utc_at": coverage_plan.get("next_missing_utc_at"),
                    "next_missing_kst_at": coverage_plan.get("next_missing_kst_at"),
                    "wait_minutes": coverage_plan.get("wait_minutes"),
                    "remaining_distinct_hours": coverage_plan.get("remaining_distinct_hours"),
                    "remaining_distinct_hour_bucket_count": coverage_plan.get("remaining_distinct_hour_bucket_count"),
                    "remaining_hour_of_day_bucket_count": coverage_plan.get("remaining_hour_of_day_bucket_count"),
                    "remaining_calendar_days": coverage_plan.get("remaining_calendar_days"),
                    "earliest_calendar_completion_utc": coverage_plan.get("earliest_calendar_completion_utc"),
                    "earliest_calendar_completion_kst": coverage_plan.get("earliest_calendar_completion_kst"),
                    "calendar_completion_policy": coverage_plan.get("calendar_completion_policy"),
                    "order_submission_allowed": False,
                    "no_live_order_sent": True,
                }
            )

    signal = by_gate.get("current_fresh_signal")
    if signal and signal.get("command"):
        command = _materialize_action_command(
            signal.get("command"),
            generated_at=generated_at,
            action_type="monitor_fresh_signal",
        )
        due = _action_due_state(signal.get("next_monitor_after_utc"), generated_at=generated_at)
        actions.append(
            {
                "priority": 20,
                "action_type": "monitor_fresh_signal",
                "target_gate": "current_fresh_signal",
                "can_run_now": due["can_run_now"],
                "requires_operator_review": False,
                "command": command,
                "reason": (
                    signal.get("reason") or "monitor_without_forcing_entry"
                    if due["can_run_now"]
                    else "wait_until_signal_monitor_cadence"
                ),
                "execute_after_utc": due["execute_after_utc"],
                "execute_after_kst": due["execute_after_kst"],
                "wait_minutes": due["wait_minutes"],
                "cadence_recommended_monitor_interval_minutes": signal.get(
                    "cadence_recommended_monitor_interval_minutes"
                ),
                "recommended_monitor_interval_minutes": signal.get("recommended_monitor_interval_minutes"),
                "signal_freshness_capture_window_minutes": signal.get("signal_freshness_capture_window_minutes"),
                "monitor_interval_capped_by_signal_freshness": signal.get(
                    "monitor_interval_capped_by_signal_freshness"
                )
                is True,
                "monitor_signal_age_alignment": signal.get("monitor_signal_age_alignment"),
                "cadence_lag_level": signal.get("cadence_lag_level"),
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        )

    paper = by_gate.get("real_paper_lifecycle_rows")
    if paper:
        paper_operator_packet = _materialize_operator_packet(
            dict(paper.get("paper_apply_operator_packet") or {}),
            generated_at=generated_at,
        )
        paper_deadline_expired = paper_operator_packet.get("operator_review_deadline_expired") is True
        if paper.get("can_resolve_now") is True and paper_deadline_expired:
            actions.append(
                {
                    "priority": 10,
                    "action_type": "rerun_paper_bridge_dry_run_after_operator_review_deadline",
                    "target_gate": "real_paper_lifecycle_rows",
                    "can_run_now": True,
                    "requires_operator_review": True,
                    "command": paper_operator_packet.get("rerun_command_after_deadline") or paper.get("dry_run_command"),
                    "follow_up_command_when_reviewed": None,
                    "reason": paper_operator_packet.get("deadline_policy"),
                    "paper_apply_operator_packet": paper_operator_packet,
                    "pre_apply_backup_plan": dict(paper_operator_packet.get("pre_apply_backup_plan") or {}),
                    "verified_pre_apply_backup_required": True,
                    "order_submission_allowed": False,
                    "no_live_order_sent": True,
                }
            )
        elif paper.get("can_resolve_now") is True:
            actions.append(
                {
                    "priority": 10,
                    "action_type": "operator_review_paper_bridge_apply",
                    "target_gate": "real_paper_lifecycle_rows",
                    "can_run_now": True,
                    "requires_operator_review": True,
                    "command": paper.get("dry_run_command") or paper.get("command"),
                    "follow_up_command_when_reviewed": paper.get("command"),
                    "post_apply_execution_parity_review_command": _materialize_action_command(
                        paper.get("post_apply_execution_parity_review_command"),
                        generated_at=generated_at,
                        action_type="paper_apply_parity_review",
                    ),
                    "reason": paper.get("reason"),
                    "paper_apply_operator_packet": paper_operator_packet,
                    "pre_apply_backup_plan": dict(paper_operator_packet.get("pre_apply_backup_plan") or {}),
                    "verified_pre_apply_backup_required": True,
                    "execution_parity_will_credit_current_apply": paper.get(
                        "execution_parity_will_credit_current_apply"
                    )
                    is True,
                    "execution_parity_events_needed": paper.get("execution_parity_events_needed"),
                    "execution_parity_events_needed_after_current_apply": paper.get(
                        "execution_parity_events_needed_after_current_apply"
                    ),
                    "execution_parity_creditable_actions": list(paper.get("execution_parity_creditable_actions") or []),
                    "order_submission_allowed": False,
                    "no_live_order_sent": True,
                }
            )
        else:
            command = _materialize_action_command(
                paper.get("monitor_command"),
                generated_at=generated_at,
                action_type="paper_bridge_wait_for_fresh_signal",
            )
            due = _action_due_state(paper.get("next_monitor_after_utc"), generated_at=generated_at)
            retry_blocked = paper.get("paper_apply_retry_blocked") is True
            parity_review_blocked = paper.get("paper_apply_parity_review_blocked") is True
            parity_review_blocker = dict(paper.get("paper_apply_parity_review_blocker") or {})
            actions.append(
                {
                    "priority": 10 if parity_review_blocked else (20 if retry_blocked else 60),
                    "action_type": (
                        "resolve_paper_apply_parity_review_blocker"
                        if parity_review_blocked
                        else (
                        "paper_bridge_wait_for_next_add_signal"
                        if retry_blocked
                        else "paper_bridge_wait_for_fresh_signal"
                        )
                    ),
                    "target_gate": "real_paper_lifecycle_rows",
                    "can_run_now": True
                    if parity_review_blocked
                    else (False if paper.get("fresh_signal") is not True else due["can_run_now"]),
                    "requires_operator_review": True,
                    "command": _materialize_action_command(
                        parity_review_blocker.get("recommended_command"),
                        generated_at=generated_at,
                        action_type="paper_apply_parity_review",
                    )
                    if parity_review_blocked
                    else command,
                    "paper_apply_command_when_gate_allows": paper.get("paper_apply_command_when_gate_allows"),
                    "paper_apply_operator_packet": paper_operator_packet,
                    "pre_apply_backup_plan": dict(paper_operator_packet.get("pre_apply_backup_plan") or {}),
                    "paper_apply_retry_blocker": paper.get("paper_apply_retry_blocker"),
                    "paper_apply_parity_review_blocker": parity_review_blocker,
                    "execution_parity_events_needed": paper.get("execution_parity_events_needed"),
                    "execution_parity_events_needed_after_current_apply": paper.get(
                        "execution_parity_events_needed_after_current_apply"
                    ),
                    "execution_parity_creditable_actions": list(paper.get("execution_parity_creditable_actions") or []),
                    "reason": parity_review_blocker.get("status") if parity_review_blocked else paper.get("reason"),
                    "source_report": parity_review_blocker.get("source_report") if parity_review_blocked else None,
                    "blockers": list(parity_review_blocker.get("blockers") or []) if parity_review_blocked else [],
                    "next_actions": list(parity_review_blocker.get("next_actions") or []) if parity_review_blocked else [],
                    "execute_after_utc": None if parity_review_blocked else due["execute_after_utc"],
                    "execute_after_kst": None if parity_review_blocked else due["execute_after_kst"],
                    "wait_minutes": 0.0 if parity_review_blocked else due["wait_minutes"],
                    "recommended_monitor_interval_minutes": paper.get("recommended_monitor_interval_minutes"),
                    "order_submission_allowed": False,
                    "no_live_order_sent": True,
                }
            )

    promotion_gate = dict(meta_router_promotion_gate or {})
    promotion_needs_refresh = meta_router_promotion_gate is not None and (
        not promotion_gate
        or promotion_gate.get("status") in {None, "", "unavailable", "stale"}
        or promotion_gate.get("stale") is True
        or promotion_gate.get("no_live_order_sent") is not True
    )
    if promotion_needs_refresh:
        actions.append(
            {
                "priority": 25,
                "action_type": "refresh_meta_router_promotion_gate",
                "target_gate": "meta_router_promotion_gate",
                "can_run_now": True,
                "requires_operator_review": False,
                "command": (
                    ".venv/bin/python scripts/run_market_state_rotation_v6_meta_router_promotion_gate.py "
                    "--write-report"
                ),
                "reason": (
                    "promotion_gate_missing_or_stale"
                    if promotion_gate.get("no_live_order_sent", True) is True
                    else "promotion_gate_report_failed_no_live_order_safety_check"
                ),
                "promotion_gate_status": promotion_gate.get("status"),
                "promotion_gate_stale": promotion_gate.get("stale"),
                "promotion_gate_source": promotion_gate.get("source_report"),
                "promotion_decision": promotion_gate.get("promotion_decision"),
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        )

    caps = by_gate.get("tiny_canary_risk_caps_configured")
    if caps and caps.get("quick_audit_command"):
        actions.append(
            {
                "priority": 30,
                "action_type": "audit_canary_risk_caps",
                "target_gate": "tiny_canary_risk_caps_configured",
                "can_run_now": True,
                "requires_operator_review": True,
                "command": caps.get("quick_audit_command"),
                "reason": caps.get("reason"),
                "errors": list(caps.get("errors") or []),
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        )

    runtime = by_gate.get("shadow_runtime_24h_observed")
    if runtime and float(runtime_progress.get("remaining_hours") or 0.0) > 0.0:
        actions.append(
            {
                "priority": 40,
                "action_type": "continue_no_live_shadow_watch",
                "target_gate": "shadow_runtime_24h_observed",
                "can_run_now": True,
                "requires_operator_review": False,
                "command": (
                    ".venv/bin/python scripts/run_market_state_rotation_v6_launch_shadow_watch.py "
                    "--iterations 1 --interval-seconds 0 "
                    f"--target-hours {float(target_hours or 24.0):g} "
                    "--quote-samples-per-tick 2 "
                    "--report-dir reports/operations/market_state_rotation_v6_launch_shadow_watch_heartbeat "
                    "--evidence-report-root reports/validation/diagnostics --quiet"
                ),
                "reason": runtime.get("reason") or "continue_calendar_runtime_observation",
                "remaining_hours": runtime_progress.get("remaining_hours"),
                "progress_pct": runtime_progress.get("progress_pct"),
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        )

    actions = sorted(actions, key=lambda item: (item.get("priority", 999), str(item.get("action_type") or "")))
    for action in actions:
        action.setdefault("can_start_now", action.get("can_run_now") is True)
        action.setdefault("waits_until_execution_window", False)
    runnable = [item for item in actions if item.get("can_run_now") is True]
    startable = [item for item in actions if item.get("can_start_now") is True]
    scheduled = sorted(
        (item for item in actions if _parse_dt(item.get("execute_after_utc")) is not None),
        key=lambda item: (
            _parse_dt(item.get("execute_after_utc")) or datetime.max.replace(tzinfo=UTC),
            int(item.get("priority") or 999),
        ),
    )
    startable_waits = [
        item for item in startable if item.get("waits_until_execution_window") is True and item.get("command")
    ]
    runtime_only_runnable = [
        item for item in runnable if item.get("action_type") == "continue_no_live_shadow_watch"
    ]
    if startable_waits and runnable and len(runtime_only_runnable) == len(runnable):
        primary = startable_waits[0]
    else:
        primary = runnable[0] if runnable else (actions[0] if actions else None)
    if not actions:
        status = "no_blocking_safe_action"
    elif primary and primary.get("waits_until_execution_window") is True:
        status = "safe_wait_action_available"
    elif runnable:
        status = "safe_actions_available"
    else:
        status = "waiting_for_external_or_time_gate"
    primary_execute_after = _parse_dt(dict(primary or {}).get("execute_after_utc"))
    pre_wait_scheduled_actions: list[dict[str, Any]] = []
    coordination_warnings: list[str] = []
    deferred_wait_action: dict[str, Any] | None = None
    if primary and primary.get("waits_until_execution_window") is True and primary_execute_after is not None:
        pre_wait_scheduled_actions = [
            item
            for item in scheduled
            if item is not primary
            and (_parse_dt(item.get("execute_after_utc")) or datetime.max.replace(tzinfo=UTC)) < primary_execute_after
            and not (
                item.get("action_type") == "paper_bridge_wait_for_fresh_signal"
                and item.get("can_run_now") is not True
            )
        ]
        if pre_wait_scheduled_actions:
            coordination_warnings.append(
                "startable_quote_window_wait_sleeps_past_earlier_scheduled_signal_or_review_actions"
            )
            deferred_wait_action = primary
            first_pre_wait_action = pre_wait_scheduled_actions[0]
            deferred_wait_action.update(
                {
                    "can_start_now": False,
                    "start_recommended_now": False,
                    "deferred_by_earlier_scheduled_action": True,
                    "deferred_reason": "earlier_scheduled_action_must_run_before_quote_window_wait",
                    "deferred_until_after_action_type": first_pre_wait_action.get("action_type"),
                    "deferred_until_after_utc": first_pre_wait_action.get("execute_after_utc"),
                    "deferred_until_after_kst": first_pre_wait_action.get("execute_after_kst"),
                }
            )
            primary = pre_wait_scheduled_actions[0]
            status = "waiting_for_earlier_scheduled_action_before_quote_window_wait"
            coordination_warnings = []
            startable = [item for item in actions if item.get("can_start_now") is True]
            startable_waits = [
                item for item in startable if item.get("waits_until_execution_window") is True and item.get("command")
            ]
    return {
        "status": status,
        "primary_action": primary,
        "runnable_action_count": len(runnable),
        "startable_action_count": len(startable),
        "action_count": len(actions),
        "next_scheduled_action": scheduled[0] if scheduled else None,
        "next_startable_wait_action": startable_waits[0] if startable_waits else None,
        "next_deferred_wait_action": deferred_wait_action,
        "pre_wait_scheduled_actions": pre_wait_scheduled_actions,
        "pre_wait_scheduled_action_count": len(pre_wait_scheduled_actions),
        "coordination_warnings": coordination_warnings,
        "actions": actions,
        "paper_apply_allowed_now": operator_handoff.get("paper_apply_allowed_now") is True,
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _planned_gap_extension(
    *,
    previous_payload: dict[str, Any] | None,
    previous_completed_at: datetime | None,
    current_completed_at: datetime,
    gap_seconds: float,
    base_warning_threshold_seconds: float,
    grace_seconds: float = 900.0,
) -> dict[str, Any]:
    if previous_completed_at is None:
        return {"status": "no_previous_watch_summary", "no_live_order_sent": True}
    payload = dict(previous_payload or {})
    safe_next = dict(payload.get("safe_next_action_plan") or {})
    candidates: list[tuple[str, dict[str, Any]]] = []
    for key in ("primary_action", "next_scheduled_action", "next_startable_wait_action", "next_deferred_wait_action"):
        item = safe_next.get(key)
        if isinstance(item, dict):
            candidates.append((key, item))
    for key in ("pre_wait_scheduled_actions", "actions"):
        for item in list(safe_next.get(key) or []):
            if isinstance(item, dict):
                candidates.append((key, item))
    previous = previous_completed_at.astimezone(UTC)
    current = current_completed_at.astimezone(UTC)
    grace = max(0.0, float(grace_seconds or 0.0))
    best_cover: dict[str, Any] | None = None
    nearest: dict[str, Any] | None = None
    seen: set[tuple[str, str, str]] = set()
    for source, item in candidates:
        execute_after = _parse_dt(item.get("execute_after_utc"))
        if execute_after is None:
            continue
        scheduled = execute_after.astimezone(UTC)
        action_type = str(item.get("action_type") or "")
        command = str(item.get("command") or "")
        key = (source, action_type, scheduled.isoformat())
        if key in seen:
            continue
        seen.add(key)
        if scheduled < previous - timedelta(seconds=60):
            continue
        planned_threshold = max(
            base_warning_threshold_seconds,
            (scheduled - previous).total_seconds() + grace,
        )
        detail = {
            "status": "planned_gap_allowed" if gap_seconds <= planned_threshold else "planned_gap_expired",
            "source": source,
            "action_type": action_type or None,
            "target_gate": item.get("target_gate"),
            "execute_after_utc": scheduled.isoformat(),
            "execute_after_kst": scheduled.astimezone(KST).isoformat(),
            "grace_seconds": round(grace, 3),
            "planned_warning_threshold_seconds": round(planned_threshold, 3),
            "scheduled_lag_seconds": round((current - scheduled).total_seconds(), 3),
            "order_submission_allowed": False,
            "no_live_order_sent": True,
        }
        if gap_seconds <= planned_threshold:
            if best_cover is None or planned_threshold < float(
                best_cover.get("planned_warning_threshold_seconds") or 0.0
            ):
                best_cover = detail
        elif nearest is None or scheduled < (
            _parse_dt(nearest.get("execute_after_utc")) or datetime.max.replace(tzinfo=UTC)
        ):
            nearest = detail
        if command:
            detail["command"] = command
    if best_cover is not None:
        return best_cover
    if nearest is not None:
        return nearest
    return {
        "status": "no_planned_gap_action",
        "grace_seconds": round(grace, 3),
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _watch_continuity(
    *,
    previous_completed_at: datetime | None,
    current_completed_at: datetime,
    interval_seconds: float,
    previous_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if previous_completed_at is None:
        return {
            "status": "no_previous_watch_summary",
            "gap_seconds": None,
            "expected_interval_seconds": max(0.0, float(interval_seconds or 0.0)),
            "warning": None,
            "planned_gap_extension": {"status": "no_previous_watch_summary", "no_live_order_sent": True},
        }
    gap_seconds = max((current_completed_at - previous_completed_at).total_seconds(), 0.0)
    expected = max(0.0, float(interval_seconds or 0.0))
    warning_threshold = max(expected * 2.0 + 60.0, 3600.0)
    planned_gap: dict[str, Any] = {
        "status": "not_needed",
        "reason": "gap_within_base_warning_threshold",
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    if gap_seconds > warning_threshold:
        planned_gap = _planned_gap_extension(
            previous_payload=previous_payload,
            previous_completed_at=previous_completed_at,
            current_completed_at=current_completed_at,
            gap_seconds=gap_seconds,
            base_warning_threshold_seconds=warning_threshold,
        )
        if planned_gap.get("status") == "planned_gap_allowed":
            warning_threshold = max(
                warning_threshold,
                float(planned_gap.get("planned_warning_threshold_seconds") or 0.0),
            )
    warning = "watch_gap_exceeded_threshold" if gap_seconds > warning_threshold else None
    return {
        "status": "gap_warning" if warning else "continuous",
        "gap_seconds": round(gap_seconds, 3),
        "expected_interval_seconds": expected,
        "warning_threshold_seconds": round(warning_threshold, 3),
        "warning": warning,
        "planned_gap_extension": planned_gap,
    }


def _signal_monitor_cadence_alignment(
    *,
    previous_completed_at: datetime | None,
    current_completed_at: datetime,
    signal_wait_plan: dict[str, Any],
) -> dict[str, Any]:
    plan = dict(signal_wait_plan or {})
    recommended_minutes = _number_or_none(plan.get("recommended_monitor_interval_minutes"))
    freshness_window_minutes = _number_or_none(plan.get("signal_freshness_capture_window_minutes"))
    if previous_completed_at is None:
        return {
            "status": "no_previous_watch_summary",
            "recommended_monitor_interval_minutes": recommended_minutes,
            "signal_freshness_capture_window_minutes": freshness_window_minutes,
            "gap_minutes": None,
            "warning": None,
            "order_submission_allowed": False,
            "no_live_order_sent": True,
        }
    if recommended_minutes is None or recommended_minutes <= 0:
        return {
            "status": "not_applicable",
            "reason": "no_scheduled_signal_monitor_interval",
            "recommended_monitor_interval_minutes": recommended_minutes,
            "signal_freshness_capture_window_minutes": freshness_window_minutes,
            "gap_minutes": None,
            "warning": None,
            "order_submission_allowed": False,
            "no_live_order_sent": True,
        }
    gap_seconds = max((current_completed_at.astimezone(UTC) - previous_completed_at.astimezone(UTC)).total_seconds(), 0.0)
    recommended_seconds = max(float(recommended_minutes) * 60.0, 1.0)
    grace_seconds = max(120.0, recommended_seconds * 0.2)
    warning_threshold_seconds = recommended_seconds + grace_seconds
    gap_exceeded = gap_seconds > warning_threshold_seconds
    return {
        "status": "monitor_gap_exceeded" if gap_exceeded else "aligned",
        "recommended_monitor_interval_minutes": recommended_minutes,
        "signal_freshness_capture_window_minutes": freshness_window_minutes,
        "gap_seconds": round(gap_seconds, 3),
        "gap_minutes": round(gap_seconds / 60.0, 3),
        "warning_threshold_seconds": round(warning_threshold_seconds, 3),
        "warning_threshold_minutes": round(warning_threshold_seconds / 60.0, 3),
        "warning": "signal_monitor_gap_exceeded_fresh_capture_cadence" if gap_exceeded else None,
        "monitor_interval_capped_by_signal_freshness": plan.get("monitor_interval_capped_by_signal_freshness") is True,
        "monitor_signal_age_alignment": plan.get("monitor_signal_age_alignment"),
        "next_monitor_after_utc": plan.get("next_monitor_after_utc"),
        "next_monitor_after_kst": plan.get("next_monitor_after_kst"),
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _shadow_runtime_observed_hours_from_report(payload: dict[str, Any]) -> float | None:
    launch = dict(payload.get("launch_readiness") or {})
    for gate in list(launch.get("blocking_gates") or []):
        if not isinstance(gate, dict) or gate.get("gate") != "shadow_runtime_24h_observed":
            continue
        observed = _number_or_none(dict(gate.get("detail") or {}).get("observed_hours"))
        if observed is not None:
            return max(0.0, observed)
    return None


def _historical_shadow_runtime_floor(
    *,
    evidence_root: Path,
    current_at: datetime,
    min_recovered_start_at: datetime | None = None,
    max_age_hours: float = 36.0,
) -> dict[str, Any]:
    current = current_at.astimezone(UTC)
    min_start = min_recovered_start_at.astimezone(UTC) if min_recovered_start_at is not None else None
    best: dict[str, Any] = {}
    root = _resolve(evidence_root)
    for path in root.glob("market_state_rotation_v6_launch_shadow_watch_*/market_state_rotation_v6_evidence_cycle.json"):
        payload = _read_json(path)
        generated_at = _parse_dt(payload.get("generated_at"))
        observed_hours = _shadow_runtime_observed_hours_from_report(payload)
        if generated_at is None or observed_hours is None or observed_hours <= 0.0:
            continue
        generated = generated_at.astimezone(UTC)
        age_hours = (current - generated).total_seconds() / 3600.0
        if age_hours < -0.1 or age_hours > max(0.0, float(max_age_hours or 0.0)):
            continue
        recovered_start = generated - timedelta(hours=observed_hours)
        if min_start is not None and recovered_start < min_start:
            continue
        projected_hours = max((current - recovered_start).total_seconds(), 0.0) / 3600.0
        best_source_observed = float(best.get("source_observed_hours") or 0.0)
        best_projected = float(best.get("projected_observed_hours") or 0.0)
        if observed_hours < best_source_observed:
            continue
        if abs(observed_hours - best_source_observed) < 1e-9 and projected_hours <= best_projected:
            continue
        best = {
            "status": "available",
            "source_report": _display_path(path),
            "source_generated_at": generated.isoformat(),
            "source_observed_hours": round(observed_hours, 4),
            "recovered_continuous_started_at": recovered_start.isoformat(),
            "projected_observed_hours": round(projected_hours, 4),
            "max_age_hours": max(0.0, float(max_age_hours or 0.0)),
            "min_recovered_start_at": min_start.isoformat() if min_start is not None else None,
            "no_live_order_sent": True,
        }
    if not best:
        return {
            "status": "unavailable",
            "reason": "no_recent_launch_shadow_runtime_floor_report",
            "max_age_hours": max(0.0, float(max_age_hours or 0.0)),
            "min_recovered_start_at": min_start.isoformat() if min_start is not None else None,
            "no_live_order_sent": True,
        }
    return best


def _recent_paper_apply_result(
    *,
    evidence_root: Path,
    current_at: datetime,
    max_age_minutes: float = 60.0,
) -> dict[str, Any]:
    current = current_at.astimezone(UTC)
    root = _resolve(evidence_root)
    latest: dict[str, Any] = {}
    for report_dir in root.glob("*paper_apply*"):
        path = report_dir / EVIDENCE_REPORT_NAME
        if not path.exists():
            continue
        payload = _read_json(path)
        generated_at = _parse_dt(payload.get("generated_at"))
        if generated_at is None:
            continue
        generated = generated_at.astimezone(UTC)
        age_minutes = (current - generated).total_seconds() / 60.0
        if age_minutes < -0.1 or age_minutes > max(0.0, float(max_age_minutes or 0.0)):
            continue
        apply_gate = dict(payload.get("paper_bridge_apply_gate") or {})
        if apply_gate.get("apply_requested") is not True:
            continue
        existing_generated = _parse_dt(latest.get("generated_at"))
        if existing_generated is not None and generated <= existing_generated.astimezone(UTC):
            continue
        latest = {
            "status": "available",
            "generated_at": generated.isoformat(),
            "age_minutes": round(age_minutes, 3),
            "source_report": _display_path(path),
            "no_live_order_sent": payload.get("no_live_order_sent") is True,
            "overall_status": payload.get("overall_status"),
            "launch_status": dict(payload.get("launch_readiness") or {}).get("status"),
            "bridge_status": apply_gate.get("bridge_status"),
            "bridge_action": apply_gate.get("bridge_action"),
            "apply_requested": True,
            "paper_fill_rows": dict(payload.get("collection_progress") or {}).get("paper_fill_rows"),
        }
    if not latest:
        return {
            "status": "unavailable",
            "reason": "no_recent_paper_apply_report",
            "max_age_minutes": max(0.0, float(max_age_minutes or 0.0)),
            "no_live_order_sent": True,
        }
    return latest


def _recent_paper_bridge_review(
    *,
    evidence_root: Path,
    current_at: datetime,
    max_age_minutes: float = 60.0,
) -> dict[str, Any]:
    current = current_at.astimezone(UTC)
    root = _resolve(evidence_root)
    latest: dict[str, Any] = {}
    for report_dir in root.glob("*paper*"):
        path = report_dir / EVIDENCE_REPORT_NAME
        if not path.exists():
            continue
        payload = _read_json(path)
        generated_at = _parse_dt(payload.get("generated_at"))
        if generated_at is None:
            continue
        generated = generated_at.astimezone(UTC)
        age_minutes = (current - generated).total_seconds() / 60.0
        if age_minutes < -0.1 or age_minutes > max(0.0, float(max_age_minutes or 0.0)):
            continue
        apply_gate = dict(payload.get("paper_bridge_apply_gate") or {})
        if apply_gate.get("fresh_signal") is not True or not apply_gate.get("bridge_action"):
            continue
        existing_generated = _parse_dt(latest.get("generated_at"))
        if existing_generated is not None and generated <= existing_generated.astimezone(UTC):
            continue
        latest = {
            "status": "available",
            "generated_at": generated.isoformat(),
            "age_minutes": round(age_minutes, 3),
            "source_report": _display_path(path),
            "no_live_order_sent": payload.get("no_live_order_sent") is True,
            "overall_status": payload.get("overall_status"),
            "launch_status": dict(payload.get("launch_readiness") or {}).get("status"),
            "bridge_status": apply_gate.get("bridge_status"),
            "bridge_action": apply_gate.get("bridge_action"),
            "apply_requested": apply_gate.get("apply_requested") is True,
            "paper_fill_rows": dict(payload.get("collection_progress") or {}).get("paper_fill_rows"),
        }
    if not latest:
        return {
            "status": "unavailable",
            "reason": "no_recent_paper_bridge_review_report",
            "max_age_minutes": max(0.0, float(max_age_minutes or 0.0)),
            "no_live_order_sent": True,
        }
    return latest


def _recent_paper_apply_parity_review(
    *,
    evidence_root: Path,
    current_at: datetime,
    max_age_minutes: float = 240.0,
) -> dict[str, Any]:
    current = current_at.astimezone(UTC)
    root = _resolve(evidence_root)
    latest: dict[str, Any] = {}
    blocking_statuses = {
        "paper_apply_parity_credit_missing",
        "unexpected_execution_parity_credit_review_required",
        "blocked_live_order_flag_detected",
    }
    for path in root.glob("**/market_state_rotation_v6_paper_apply_parity_review.json"):
        payload = _read_json(path)
        generated_at = _parse_dt(payload.get("generated_at"))
        if generated_at is None:
            continue
        generated = generated_at.astimezone(UTC)
        age_minutes = (current - generated).total_seconds() / 60.0
        if age_minutes < -0.1 or age_minutes > max(0.0, float(max_age_minutes or 0.0)):
            continue
        existing_generated = _parse_dt(latest.get("generated_at"))
        if existing_generated is not None and generated <= existing_generated.astimezone(UTC):
            continue
        status = str(payload.get("status") or "")
        latest = {
            "status": status,
            "generated_at": generated.isoformat(),
            "age_minutes": round(age_minutes, 3),
            "source_report": _display_path(path),
            "no_live_order_sent": payload.get("no_live_order_sent") is True,
            "blocks_next_paper_apply": status in blocking_statuses or payload.get("no_live_order_sent") is not True,
            "expected_credit_from_before_forecast": payload.get("expected_credit_from_before_forecast"),
            "actual_journal_row_delta": payload.get("actual_journal_row_delta"),
            "new_journal_row_count": payload.get("new_journal_row_count"),
            "credit_confirmed": payload.get("credit_confirmed") is True,
            "blockers": list(payload.get("blockers") or []),
            "next_actions": list(payload.get("next_actions") or []),
        }
    if not latest:
        return {
            "status": "unavailable",
            "reason": "no_recent_paper_apply_parity_review_report",
            "max_age_minutes": max(0.0, float(max_age_minutes or 0.0)),
            "blocks_next_paper_apply": False,
            "no_live_order_sent": True,
        }
    return latest


def _recent_meta_router_promotion_gate(
    *,
    evidence_root: Path,
    current_at: datetime,
    max_age_minutes: float = 1440.0,
) -> dict[str, Any]:
    current = current_at.astimezone(UTC)
    root = _resolve(evidence_root)
    latest_payload: dict[str, Any] = {}
    latest_path: Path | None = None
    latest_generated: datetime | None = None
    for path in root.glob("**/market_state_rotation_v6_meta_router_promotion_gate.json"):
        payload = _read_json(path)
        generated_at = _parse_dt(payload.get("generated_at"))
        if generated_at is None:
            continue
        generated = generated_at.astimezone(UTC)
        if latest_generated is not None and generated <= latest_generated:
            continue
        latest_payload = payload
        latest_path = path
        latest_generated = generated

    if latest_generated is None or latest_path is None:
        return {
            "status": "unavailable",
            "reason": "no_meta_router_promotion_gate_report",
            "max_age_minutes": max(0.0, float(max_age_minutes or 0.0)),
            "stale": True,
            "blocks_live_promotion": True,
            "no_live_order_sent": True,
        }

    age_minutes = (current - latest_generated).total_seconds() / 60.0
    stale = age_minutes < -0.1 or age_minutes > max(0.0, float(max_age_minutes or 0.0))
    readiness = dict(latest_payload.get("readiness") or {})
    candidate = dict(latest_payload.get("candidate") or {})
    decision = str(latest_payload.get("promotion_decision") or "")
    live_pass_decisions = {
        "tiny_canary_gate_passed_manual_approval_required",
        "full_live_gate_passed_manual_approval_required",
    }
    return {
        "status": "stale" if stale else latest_payload.get("status"),
        "generated_at": latest_generated.isoformat(),
        "age_minutes": round(age_minutes, 3),
        "source_report": _display_path(latest_path),
        "stale": stale,
        "promotion_decision": decision,
        "decision_reasons": list(latest_payload.get("decision_reasons") or []),
        "next_actions": list(latest_payload.get("next_actions") or []),
        "next_blocker": latest_payload.get("next_blocker"),
        "candidate": {
            "recipe_id": candidate.get("recipe_id"),
            "decision": candidate.get("decision"),
            "compounded_return_pct": candidate.get("compounded_return_pct"),
            "max_drawdown_pct": candidate.get("max_drawdown_pct"),
            "avg_cost_drag_pct": candidate.get("avg_cost_drag_pct"),
            "trade_like_events": candidate.get("trade_like_events"),
            "router_modes": dict(candidate.get("router_modes") or {}),
        },
        "readiness": {
            "stage": readiness.get("stage"),
            "ready_for_paper": readiness.get("ready_for_paper") is True,
            "ready_for_tiny_canary": readiness.get("ready_for_tiny_canary") is True,
            "ready_for_full_live": readiness.get("ready_for_full_live") is True,
            "blockers": list(readiness.get("blockers") or []),
            "warnings": list(readiness.get("warnings") or []),
            "deployment_limits": dict(readiness.get("deployment_limits") or {}),
            "execution_parity": dict(readiness.get("execution_parity") or {}),
            "time_substitution_policy": dict(readiness.get("time_substitution_policy") or {}),
            "upgrade_backlog": dict(readiness.get("upgrade_backlog") or {}),
        },
        "blocks_live_promotion": (
            stale
            or latest_payload.get("no_live_order_sent") is not True
            or decision not in live_pass_decisions
        ),
        "order_submission_allowed": False,
        "no_live_order_sent": latest_payload.get("no_live_order_sent") is True,
    }


def _paper_apply_parity_review_state(
    *,
    recent_paper_apply: dict[str, Any],
    recent_paper_review: dict[str, Any],
    recent_parity_review: dict[str, Any],
) -> dict[str, Any]:
    apply_report = dict(recent_paper_apply or {})
    bridge_review = dict(recent_paper_review or {})
    parity = dict(recent_parity_review or {})
    apply_generated = _parse_dt(apply_report.get("generated_at"))
    parity_generated = _parse_dt(parity.get("generated_at"))
    if apply_report.get("status") == "available" and parity_generated is None:
        source_report = apply_report.get("source_report")
        before_report = bridge_review.get("source_report") or "<pre_apply_evidence_report>"
        return {
            "status": "missing_after_recent_paper_apply",
            "blocks_next_paper_apply": True,
            "reason": "recent_paper_apply_requires_post_apply_parity_review",
            "source_report": source_report,
            "recent_paper_apply_report": source_report,
            "recent_paper_bridge_review_report": bridge_review.get("source_report"),
            "recommended_command": (
                ".venv/bin/python scripts/run_market_state_rotation_v6_paper_apply_parity_review.py "
                f"--before-evidence-report {before_report} "
                f"--after-evidence-report {source_report or '<post_apply_evidence_report>'} "
                "--report-dir reports/validation/diagnostics/<paper_apply_parity_review_report_dir> "
                "--write-report"
            ),
            "blockers": ["post_apply_parity_review_missing"],
            "next_actions": ["run_post_apply_parity_review_before_next_paper_apply"],
            "no_live_order_sent": True,
        }
    if (
        apply_generated is not None
        and parity_generated is not None
        and apply_generated.astimezone(UTC) > parity_generated.astimezone(UTC)
    ):
        source_report = apply_report.get("source_report")
        before_report = bridge_review.get("source_report") or "<pre_apply_evidence_report>"
        return {
            "status": "stale_after_recent_paper_apply",
            "blocks_next_paper_apply": True,
            "reason": "latest_paper_apply_is_newer_than_latest_parity_review",
            "source_report": source_report,
            "recent_paper_apply_report": source_report,
            "recent_paper_apply_generated_at": apply_report.get("generated_at"),
            "recent_parity_review_report": parity.get("source_report"),
            "recent_parity_review_generated_at": parity.get("generated_at"),
            "recommended_command": (
                ".venv/bin/python scripts/run_market_state_rotation_v6_paper_apply_parity_review.py "
                f"--before-evidence-report {before_report} "
                f"--after-evidence-report {source_report or '<post_apply_evidence_report>'} "
                "--report-dir reports/validation/diagnostics/<paper_apply_parity_review_report_dir> "
                "--write-report"
            ),
            "blockers": ["post_apply_parity_review_stale"],
            "next_actions": ["rerun_post_apply_parity_review_for_latest_paper_apply"],
            "no_live_order_sent": True,
        }
    return {
        "status": parity.get("status") or "unavailable",
        "blocks_next_paper_apply": parity.get("blocks_next_paper_apply") is True,
        "reason": parity.get("reason"),
        "source_report": parity.get("source_report"),
        "blockers": list(parity.get("blockers") or []),
        "next_actions": list(parity.get("next_actions") or []),
        "no_live_order_sent": parity.get("no_live_order_sent", True) is True,
    }


def _paper_apply_retry_blocker(
    latest: dict[str, Any],
    recent_paper_apply: dict[str, Any],
    recent_paper_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    apply_gate = dict(latest.get("paper_bridge_apply_gate") or {})
    recent = dict(recent_paper_apply or {})
    if (
        apply_gate.get("can_request_paper_apply_now") is True
        and str(apply_gate.get("bridge_action") or "").lower() == "remove"
        and str(recent.get("bridge_action") or "").lower() == "remove"
        and str(recent.get("bridge_status") or "").lower() == "no_open_v6_paper_plan"
        and recent.get("no_live_order_sent") is True
    ):
        review = dict(recent_paper_review or {})
        recent_generated_at = _parse_dt(review.get("generated_at")) or _parse_dt(recent.get("generated_at"))
        next_monitor_after = (
            recent_generated_at.astimezone(UTC) + timedelta(minutes=15)
            if recent_generated_at is not None
            else None
        )
        return {
            "blocked": True,
            "reason": "recent_remove_paper_apply_found_no_open_v6_paper_plan",
            "source_report": recent.get("source_report"),
            "generated_at": recent.get("generated_at"),
            "age_minutes": recent.get("age_minutes"),
            "bridge_status": recent.get("bridge_status"),
            "bridge_action": recent.get("bridge_action"),
            "next_monitor_after_utc": next_monitor_after.isoformat() if next_monitor_after is not None else None,
            "next_monitor_after_kst": next_monitor_after.astimezone(KST).isoformat()
            if next_monitor_after is not None
            else None,
            "next_action": "wait_for_next_add_signal_or_existing_open_paper_plan_before_reapplying_remove",
            "no_live_order_sent": True,
        }
    return {"blocked": False, "no_live_order_sent": True}


def _continuous_runtime_start(
    *,
    previous_payload: dict[str, Any],
    fallback_started_at: datetime,
    current_at: datetime,
    interval_seconds: float,
    runtime_floor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous_completed_at = _parse_dt(previous_payload.get("completed_at"))
    previous_runtime = dict(previous_payload.get("runtime_observation") or {})
    previous_continuous_started_at = _parse_dt(previous_runtime.get("continuous_started_at"))
    candidate = previous_continuous_started_at or fallback_started_at
    continuity = _watch_continuity(
        previous_completed_at=previous_completed_at,
        current_completed_at=current_at,
        interval_seconds=interval_seconds,
        previous_payload=previous_payload,
    )
    gap_reset = continuity.get("status") == "gap_warning"
    continuous_started_at = current_at if gap_reset else candidate
    floor = dict(runtime_floor or {})
    floor_started_at = _parse_dt(floor.get("recovered_continuous_started_at"))
    floor_projected_hours = _number_or_none(floor.get("projected_observed_hours"))
    floor_source_observed_hours = _number_or_none(floor.get("source_observed_hours"))
    previous_floor = dict(previous_runtime.get("runtime_floor") or {})
    previous_floor_source_observed_hours = _number_or_none(previous_floor.get("source_observed_hours"))
    computed_hours = max((current_at.astimezone(UTC) - continuous_started_at.astimezone(UTC)).total_seconds(), 0.0) / 3600.0
    runtime_floor_recovered = False
    runtime_start_clamped = False
    fallback_start = fallback_started_at.astimezone(UTC)
    if not gap_reset and continuous_started_at.astimezone(UTC) < fallback_start:
        if floor_started_at is not None and floor_started_at.astimezone(UTC) >= fallback_start:
            continuous_started_at = floor_started_at.astimezone(UTC)
            runtime_floor_recovered = True
        else:
            continuous_started_at = fallback_start
        runtime_start_clamped = True
        computed_hours = max((current_at.astimezone(UTC) - continuous_started_at.astimezone(UTC)).total_seconds(), 0.0) / 3600.0
    better_floor_than_previous_recovery = bool(
        previous_runtime.get("runtime_floor_recovered") is True
        and floor_source_observed_hours is not None
        and previous_floor_source_observed_hours is not None
        and floor_source_observed_hours > previous_floor_source_observed_hours + 0.1
    )
    if (
        not gap_reset
        and floor_started_at is not None
        and floor_projected_hours is not None
        and (
            (
                floor_started_at.astimezone(UTC) < continuous_started_at.astimezone(UTC)
                and floor_projected_hours > computed_hours + 0.1
            )
            or better_floor_than_previous_recovery
        )
    ):
        continuous_started_at = floor_started_at.astimezone(UTC)
        runtime_floor_recovered = True
    return {
        "continuous_started_at": continuous_started_at,
        "previous_continuous_started_at": previous_continuous_started_at,
        "gap_reset": gap_reset,
        "gap_seconds": continuity.get("gap_seconds"),
        "gap_warning": continuity.get("warning"),
        "warning_threshold_seconds": continuity.get("warning_threshold_seconds"),
        "watch_continuity": continuity,
        "runtime_floor_recovered": runtime_floor_recovered,
        "runtime_start_clamped_to_operation_start": runtime_start_clamped,
        "runtime_floor": floor,
        "no_live_order_sent": True,
    }


def _build_watch_summary(
    *,
    started_at: datetime,
    completed_at: datetime,
    runs: list[dict[str, Any]],
    target_hours: float,
    continuous_started_at: datetime | None = None,
    baseline_collection: dict[str, Any] | None = None,
    previous_completed_at: datetime | None = None,
    interval_seconds: float = 0.0,
    microstructure_watch: dict[str, Any] | None = None,
    recent_paper_apply: dict[str, Any] | None = None,
    recent_paper_review: dict[str, Any] | None = None,
    recent_paper_apply_parity_review: dict[str, Any] | None = None,
    recent_meta_router_promotion_gate: dict[str, Any] | None = None,
    pre_run_wait_plan: dict[str, Any] | None = None,
    pre_run_wait_incident_log: list[dict[str, Any]] | None = None,
    pre_run_market_data_refresh: dict[str, Any] | None = None,
    runtime_start_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime_start = continuous_started_at or started_at
    observed_hours = round(max((completed_at - runtime_start).total_seconds(), 0.0) / 3600.0, 4)
    calendar_elapsed_hours = round(max((completed_at - started_at).total_seconds(), 0.0) / 3600.0, 4)
    latest = runs[-1] if runs else {}
    live_violation_count = sum(1 for run in runs if run.get("no_live_order_sent") is not True)
    target_reached = observed_hours >= max(float(target_hours or 0.0), 0.0)
    progress = _watch_progress(runs, baseline_collection=baseline_collection)
    launch = dict(latest.get("launch_readiness") or {})
    launch_next_blocker = dict(launch.get("next_blocker") or {})
    launch_next_blocker_gate = str(launch_next_blocker.get("gate") or "").strip()
    if live_violation_count > 0:
        status = "blocked_live_order_violation_detected"
    elif progress.get("paper_apply_available_seen") is True:
        status = "fresh_signal_seen_paper_apply_review_available"
    elif progress.get("fresh_signal_seen") is True:
        status = "fresh_signal_seen_continue_paper_bridge_review"
    elif target_reached and launch_next_blocker_gate == "current_fresh_signal":
        status = "target_observation_complete_waiting_for_fresh_signal"
    elif target_reached and launch_next_blocker_gate:
        status = f"target_observation_complete_blocked_by_{launch_next_blocker_gate}"
    elif target_reached:
        status = "target_observation_complete"
    else:
        status = "watch_in_progress"
    risk_caps = dict(latest.get("canary_risk_caps_config") or {})
    runtime = _runtime_progress(observed_hours=observed_hours, target_hours=float(target_hours or 0.0))
    micro = dict(microstructure_watch or {})
    parity_review_state = _paper_apply_parity_review_state(
        recent_paper_apply=dict(recent_paper_apply or {}),
        recent_paper_review=dict(recent_paper_review or {}),
        recent_parity_review=dict(recent_paper_apply_parity_review or {}),
    )
    operator_handoff = _operator_handoff(
        latest=latest,
        progress=progress,
        runtime_progress=runtime,
        risk_caps=risk_caps,
        microstructure_watch=micro,
        recent_paper_apply=recent_paper_apply,
        recent_paper_review=recent_paper_review,
        recent_paper_apply_parity_review=parity_review_state,
    )
    micro["coverage_plan"] = _microstructure_coverage_plan(
        coverage=dict(micro.get("coverage") or {}),
        latest_collection=dict(latest.get("collection_progress") or {}),
        microstructure_watch=micro,
        generated_at=completed_at,
        quote_capture_command=operator_handoff.get("quote_capture_command"),
    )
    blocker_resolution_plan = _blocker_resolution_plan(
        latest=latest,
        progress=progress,
        runtime_progress=runtime,
        risk_caps=risk_caps,
        microstructure_watch=micro,
        operator_handoff=operator_handoff,
    )
    safe_next_action_plan = _safe_next_action_plan(
        blocker_resolution_plan=blocker_resolution_plan,
        runtime_progress=runtime,
        microstructure_watch=micro,
        operator_handoff=operator_handoff,
        meta_router_promotion_gate=dict(recent_meta_router_promotion_gate or {}),
        target_hours=float(target_hours or 0.0),
        generated_at=completed_at,
    )
    incident_log = list(pre_run_wait_incident_log or [])
    pre_run_capture_outcome = _pre_run_quote_window_capture_outcome(
        pre_run_wait_plan=pre_run_wait_plan,
        latest_collection=dict(latest.get("collection_progress") or {}),
    )
    signal_monitor_cadence_alignment = _signal_monitor_cadence_alignment(
        previous_completed_at=previous_completed_at,
        current_completed_at=completed_at,
        signal_wait_plan=dict(latest.get("signal_wait_plan") or {}),
    )
    return {
        "status": status,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "target_hours": float(target_hours or 0.0),
        "observed_hours": observed_hours,
        "calendar_elapsed_hours": calendar_elapsed_hours,
        "runtime_progress": runtime,
        "runtime_observation": {
            "continuous_started_at": runtime_start.isoformat(),
            "calendar_started_at": started_at.isoformat(),
            "continuous_observed_hours": observed_hours,
            "calendar_elapsed_hours": calendar_elapsed_hours,
            "gap_reset": bool(dict(runtime_start_plan or {}).get("gap_reset")),
            "gap_seconds": dict(runtime_start_plan or {}).get("gap_seconds"),
            "gap_warning": dict(runtime_start_plan or {}).get("gap_warning"),
            "warning_threshold_seconds": dict(runtime_start_plan or {}).get("warning_threshold_seconds"),
            "runtime_floor_recovered": dict(runtime_start_plan or {}).get("runtime_floor_recovered"),
            "runtime_start_clamped_to_operation_start": dict(runtime_start_plan or {}).get(
                "runtime_start_clamped_to_operation_start"
            ),
            "runtime_floor": dict(runtime_start_plan or {}).get("runtime_floor"),
            "no_live_order_sent": True,
        },
        "watch_continuity": dict(runtime_start_plan or {}).get("watch_continuity")
        or _watch_continuity(
            previous_completed_at=previous_completed_at,
            current_completed_at=completed_at,
            interval_seconds=interval_seconds,
        ),
        "signal_monitor_cadence_alignment": signal_monitor_cadence_alignment,
        "pre_run_quote_window_wait_plan": dict(pre_run_wait_plan or {}),
        "pre_run_quote_window_capture_outcome": pre_run_capture_outcome,
        "pre_run_quote_window_wait_incident_log": incident_log,
        "latest_pre_run_quote_window_wait_incident": dict(incident_log[-1]) if incident_log else None,
        "pre_run_market_data_refresh": dict(pre_run_market_data_refresh or {}),
        "completed_iterations": len(runs),
        "target_observation_complete": target_reached,
        "target_observation_status": {
            "runtime_target_reached": target_reached,
            "launch_status": launch.get("status"),
            "launch_next_blocker": launch_next_blocker_gate or None,
            "status": status,
            "reason": (
                "runtime_observation_complete_but_realtime_fresh_signal_gate_still_waiting"
                if status == "target_observation_complete_waiting_for_fresh_signal"
                else "runtime_observation_complete_but_launch_gate_still_blocked"
                if status.startswith("target_observation_complete_blocked_by_")
                else "runtime_observation_complete"
                if status == "target_observation_complete"
                else status
            ),
            "no_live_order_sent": live_violation_count == 0,
        },
        "live_violation_count": live_violation_count,
        "no_live_order_sent": live_violation_count == 0,
        "latest_run": latest,
        "baseline_collection_progress": dict(baseline_collection or latest.get("collection_progress") or {}),
        "progress": progress,
        "microstructure_watch": micro,
        "canary_risk_caps_config": risk_caps,
        "operator_handoff": operator_handoff,
        "execution_parity_eta_plan": dict(operator_handoff.get("execution_parity_eta_plan") or {}),
        "recent_paper_apply_result": dict(recent_paper_apply or {}),
        "recent_paper_bridge_review": dict(recent_paper_review or {}),
        "recent_paper_apply_parity_review": parity_review_state,
        "meta_router_promotion_gate": dict(recent_meta_router_promotion_gate or {}),
        "blocker_resolution_plan": blocker_resolution_plan,
        "safe_next_action_plan": safe_next_action_plan,
        "launch_week_plan": _launch_week_plan(latest),
        "runs": runs,
        "non_negotiables": [
            "watcher_never_enables_live_orders",
            "watcher_repeats_evidence_cycle_only",
            "24h_runtime_observation_cannot_be_replaced_by_backtest",
        ],
    }


def run_launch_shadow_watch(
    args: argparse.Namespace,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
    market_data_refresh_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    report_dir = _resolve(args.report_dir)
    evidence_root = _resolve(args.evidence_report_root)
    previous_payload = _previous_watch_payload(report_dir)
    started_at = _previous_started_at(report_dir) or datetime.now(UTC)
    baseline_collection = _baseline_collection_progress(previous_payload)
    previous_completed_at = _parse_dt(previous_payload.get("completed_at"))
    microstructure_watch: dict[str, Any] = dict(previous_payload.get("microstructure_watch") or {})
    pre_run_wait_plan = _pre_run_quote_window_wait_plan(
        previous_payload=previous_payload,
        generated_at=datetime.now(UTC),
        enabled=bool(args.sleep_until_next_missing_quote_window),
        max_wait_seconds=max(0.0, float(args.max_pre_run_wait_seconds)),
        wakeup_buffer_seconds=max(0.0, float(args.quote_window_wakeup_buffer_seconds)),
    )
    if pre_run_wait_plan.get("should_sleep") is True:
        sleep_started_at = datetime.now(UTC)
        sleep_fn(max(0.0, float(pre_run_wait_plan.get("wait_seconds") or 0.0)))
        pre_run_wait_plan = _finalize_pre_run_quote_window_sleep(
            pre_run_wait_plan,
            sleep_started_at=sleep_started_at,
            woke_at=datetime.now(UTC),
        )
    pre_run_market_data_refresh: dict[str, Any] = {}
    if (
        pre_run_wait_plan.get("actual_sleep_seconds") is not None
        and not bool(getattr(args, "disable_market_data_refresh_after_quote_window_sleep", False))
    ):
        refresh_fn = market_data_refresh_fn or _refresh_runtime_market_data_cache
        pre_run_market_data_refresh = refresh_fn(
            evidence_root=evidence_root,
            generated_at=datetime.now(UTC),
        )
    pre_run_wait_incident_log = _pre_run_quote_window_wait_incident_log(
        previous_payload=previous_payload,
        current_plan=pre_run_wait_plan,
    )
    runtime_floor = _historical_shadow_runtime_floor(
        evidence_root=evidence_root,
        current_at=datetime.now(UTC),
        min_recovered_start_at=started_at,
    )
    runtime_start_plan = _continuous_runtime_start(
        previous_payload=previous_payload,
        fallback_started_at=started_at,
        current_at=datetime.now(UTC),
        interval_seconds=max(0.0, float(args.interval_seconds)),
        runtime_floor=runtime_floor,
    )
    continuous_started_at = runtime_start_plan["continuous_started_at"]
    runs: list[dict[str, Any]] = []
    iterations = max(1, int(args.iterations))
    refresh_before_evidence_run = not bool(getattr(args, "disable_market_data_refresh_before_evidence_run", False))
    pre_run_refresh_succeeded = pre_run_market_data_refresh.get("status") == "refreshed"
    pre_run_force_quote_sample = _pre_run_wait_force_quote_sample(pre_run_wait_plan)
    for idx in range(1, iterations + 1):
        generated_at = datetime.now(UTC)
        observed_hours = max((generated_at - continuous_started_at).total_seconds(), 0.0) / 3600.0
        runs.append(
            _run_once(
                args,
                iteration=idx,
                generated_at=generated_at,
                observed_hours=observed_hours,
                refresh_market_data_before_run=refresh_before_evidence_run
                and not (idx == 1 and pre_run_refresh_succeeded),
                force_quote_sample=pre_run_force_quote_sample and idx == 1,
            )
        )
        if not baseline_collection:
            baseline_collection = dict(runs[0].get("collection_progress") or {})
        microstructure_watch = _quote_microstructure_watch(
            sample_jsonl=_resolve(args.sample_jsonl),
            generated_at=datetime.now(UTC),
            latest_collection=dict(runs[-1].get("collection_progress") or {}),
            previous_payload=previous_payload,
            recent_hours=max(0.0, float(args.microstructure_recent_hours)),
        )
        recent_paper_apply = _recent_paper_apply_result(
            evidence_root=evidence_root,
            current_at=datetime.now(UTC),
        )
        recent_paper_review = _recent_paper_bridge_review(
            evidence_root=evidence_root,
            current_at=datetime.now(UTC),
        )
        recent_paper_apply_parity_review = _recent_paper_apply_parity_review(
            evidence_root=evidence_root,
            current_at=datetime.now(UTC),
        )
        recent_meta_router_promotion_gate = _recent_meta_router_promotion_gate(
            evidence_root=evidence_root,
            current_at=datetime.now(UTC),
        )
        summary = _build_watch_summary(
            started_at=started_at,
            completed_at=datetime.now(UTC),
            runs=runs,
            target_hours=max(0.0, float(args.target_hours)),
            continuous_started_at=continuous_started_at,
            baseline_collection=baseline_collection,
            previous_completed_at=previous_completed_at,
            interval_seconds=max(0.0, float(args.interval_seconds)),
            microstructure_watch=microstructure_watch,
            recent_paper_apply=recent_paper_apply,
            recent_paper_review=recent_paper_review,
            recent_paper_apply_parity_review=recent_paper_apply_parity_review,
            recent_meta_router_promotion_gate=recent_meta_router_promotion_gate,
            pre_run_wait_plan=pre_run_wait_plan,
            pre_run_wait_incident_log=pre_run_wait_incident_log,
            pre_run_market_data_refresh=pre_run_market_data_refresh,
            runtime_start_plan=runtime_start_plan,
        )
        _write_json(report_dir / "latest.json", summary)
        _write_markdown(report_dir / "latest.md", summary)
        if idx < iterations:
            sleep_fn(max(0.0, float(args.interval_seconds)))
    return _build_watch_summary(
        started_at=started_at,
        completed_at=datetime.now(UTC),
        runs=runs,
        target_hours=max(0.0, float(args.target_hours)),
        continuous_started_at=continuous_started_at,
        baseline_collection=baseline_collection,
        previous_completed_at=previous_completed_at,
        interval_seconds=max(0.0, float(args.interval_seconds)),
        microstructure_watch=microstructure_watch,
        recent_paper_apply=_recent_paper_apply_result(
            evidence_root=evidence_root,
            current_at=datetime.now(UTC),
        ),
        recent_paper_review=_recent_paper_bridge_review(
            evidence_root=evidence_root,
            current_at=datetime.now(UTC),
        ),
        recent_paper_apply_parity_review=_recent_paper_apply_parity_review(
            evidence_root=evidence_root,
            current_at=datetime.now(UTC),
        ),
        recent_meta_router_promotion_gate=_recent_meta_router_promotion_gate(
            evidence_root=evidence_root,
            current_at=datetime.now(UTC),
        ),
        pre_run_wait_plan=pre_run_wait_plan,
        pre_run_wait_incident_log=pre_run_wait_incident_log,
        pre_run_market_data_refresh=pre_run_market_data_refresh,
        runtime_start_plan=runtime_start_plan,
    )


def main() -> int:
    args = parse_args()
    summary = run_launch_shadow_watch(args)
    if not args.quiet:
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
