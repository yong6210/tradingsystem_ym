#!/usr/bin/env python3
"""Run the safe v6 collection cycle and its follow-up abstention audits."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.run_market_state_rotation_v6_collection_cycle import (
    CYCLE_REPORT_NAME,
    DEFAULT_CYCLE_REPORT_DIR,
    _json_default,
    _resolve,
    build_collection_cycle_summary,
    run_collection_cycle,
)
from scripts.run_market_state_rotation_v6_collection_tick import (
    DEFAULT_MANUAL_EVIDENCE,
    DEFAULT_SAMPLE_PATH,
    DEFAULT_STRESS_REPORT,
    DEFAULT_WALK_FORWARD_REPORT,
)
from scripts.run_market_state_rotation_v6_entry_filter_sparsity_audit import build_entry_filter_sparsity_audit
from scripts.run_market_state_rotation_v6_execution_parity_journal import (
    DEFAULT_JOURNAL_NAME as EXECUTION_PARITY_JOURNAL_NAME,
    build_execution_parity_journal_report,
)
from scripts.run_market_state_rotation_v6_paper_bridge_tick import (
    DEFAULT_PRE_APPLY_BACKUP_DIR,
    DEFAULT_SOURCE_BACKTEST_REPORT,
    EXPECTED_SYMBOL,
)
from scripts.run_market_state_rotation_v6_quote_shadow_audit import (
    EXPECTED_STRATEGY_FAMILY,
    _load_jsonl,
    build_quote_shadow_audit_report,
)
from scripts.run_market_state_rotation_v6_safety_controls_audit import build_safety_controls_report
from scripts.run_market_state_rotation_v6_signal_drought_audit import build_signal_drought_audit


DEFAULT_EVIDENCE_REPORT_DIR = "reports/validation/diagnostics/market_state_rotation_v6_evidence_cycle"
EVIDENCE_REPORT_NAME = "market_state_rotation_v6_evidence_cycle.json"
DEFAULT_HISTORICAL_REPLAY_SOURCE = "data/binance/BTCUSDT_1h_1831d.json"
DEFAULT_HISTORICAL_LIFECYCLE_REPLAY_SOURCE = "reports/validation/btc_flip_rotation_search/latest.json"
DEFAULT_CANARY_RISK_CAPS_PATH = "reports/operations/market_state_rotation_v6_canary_risk_caps.json"
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


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True, default=_json_default) for row in rows)
        + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _tail_text(value: str, *, max_chars: int = 2000) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _refresh_runtime_market_data_cache(*, report_dir: Path, generated_at: datetime) -> dict[str, Any]:
    refresh_dir = report_dir / "pre_run_market_data_refresh"
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
        _display_path(refresh_dir),
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
            "command": " ".join(shlex.quote(str(item)) for item in command),
            "report_dir": _display_path(refresh_dir),
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
            "command": " ".join(shlex.quote(str(item)) for item in command),
            "report_dir": _display_path(refresh_dir),
            "error": str(exc),
            "order_submission_allowed": False,
            "no_live_order_sent": True,
        }


def _load_json_if_exists(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _float_field(payload: dict[str, Any], key: str, fallback: float) -> float:
    try:
        return float(payload.get(key, fallback))
    except (TypeError, ValueError):
        return float(fallback)


def _int_field(payload: dict[str, Any], key: str, fallback: int) -> int:
    try:
        return int(payload.get(key, fallback))
    except (TypeError, ValueError):
        return int(fallback)


def _bool_field(payload: dict[str, Any], key: str, fallback: bool = False) -> bool:
    value = payload.get(key, fallback)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "acknowledged"}


def load_canary_risk_caps_config(
    *,
    path: Path | None,
    cli_max_notional_usdt: float,
    cli_max_leverage: float,
    cli_max_daily_loss_usdt: float,
) -> dict[str, Any]:
    """Load optional tiny-canary risk caps without ever authorizing order submission."""
    cli_values = {
        "max_notional_usdt": max(0.0, float(cli_max_notional_usdt or 0.0)),
        "max_leverage": max(0.0, float(cli_max_leverage or 0.0)),
        "max_daily_loss_usdt": max(0.0, float(cli_max_daily_loss_usdt or 0.0)),
    }
    source = "cli_or_default"
    raw: dict[str, Any] = {}
    errors: list[str] = []
    warnings: list[str] = []
    path_exists = False
    if path is not None:
        path_exists = path.exists()
        if path_exists:
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                loaded = {}
                errors.append(f"failed_to_read_canary_risk_caps_json:{exc.__class__.__name__}")
            if isinstance(loaded, dict):
                raw = loaded
                source = "json_file"
            else:
                errors.append("canary_risk_caps_json_must_be_object")
    enabled = raw.get("enabled", True) is not False
    effective = dict(cli_values)
    safeguards = {
        "scope_symbol": str(raw.get("scope_symbol") or "").upper(),
        "strategy_family": str(raw.get("strategy_family") or ""),
        "max_daily_order_count": _int_field(raw, "max_daily_order_count", 0),
        "max_consecutive_loss_count": _int_field(raw, "max_consecutive_loss_count", 0),
        "kill_switch_required": _bool_field(raw, "kill_switch_required", False),
        "reduce_only_exit_required": _bool_field(raw, "reduce_only_exit_required", False),
        "operator_acknowledged_no_auto_live_order": _bool_field(
            raw,
            "operator_acknowledged_no_auto_live_order",
            False,
        ),
    }
    if raw and enabled:
        effective = {
            "max_notional_usdt": max(0.0, _float_field(raw, "max_notional_usdt", cli_values["max_notional_usdt"])),
            "max_leverage": max(0.0, _float_field(raw, "max_leverage", cli_values["max_leverage"])),
            "max_daily_loss_usdt": max(
                0.0,
                _float_field(raw, "max_daily_loss_usdt", cli_values["max_daily_loss_usdt"]),
            ),
        }
    elif raw and not enabled:
        errors.append("canary_risk_caps_json_disabled")
    if effective["max_notional_usdt"] <= 0.0:
        errors.append("max_notional_usdt_must_be_positive")
    if effective["max_daily_loss_usdt"] <= 0.0:
        errors.append("max_daily_loss_usdt_must_be_positive")
    if not (0.0 < effective["max_leverage"] <= 10.0):
        errors.append("max_leverage_must_be_between_0_and_10")
    if source != "json_file":
        errors.append("canary_risk_caps_json_required")
    if raw and enabled:
        if safeguards["scope_symbol"] != EXPECTED_SYMBOL:
            errors.append("scope_symbol_must_be_BTCUSDT")
        if safeguards["strategy_family"] != "market_state_rotation_v6":
            errors.append("strategy_family_must_be_market_state_rotation_v6")
        if not (1 <= int(safeguards["max_daily_order_count"]) <= 3):
            errors.append("max_daily_order_count_must_be_between_1_and_3")
        if not (1 <= int(safeguards["max_consecutive_loss_count"]) <= 2):
            errors.append("max_consecutive_loss_count_must_be_between_1_and_2")
        if not safeguards["kill_switch_required"]:
            errors.append("kill_switch_required_must_be_true")
        if not safeguards["reduce_only_exit_required"]:
            errors.append("reduce_only_exit_required_must_be_true")
        if not safeguards["operator_acknowledged_no_auto_live_order"]:
            errors.append("operator_acknowledged_no_auto_live_order_must_be_true")
        if effective["max_daily_loss_usdt"] > effective["max_notional_usdt"] * 0.5:
            errors.append("max_daily_loss_usdt_must_be_lte_50pct_of_max_notional")
        if effective["max_leverage"] > 10.0:
            errors.append("max_leverage_must_not_exceed_nanyotti_observed_cap_10x")
        if effective["max_notional_usdt"] <= 0.0 or effective["max_daily_loss_usdt"] <= 0.0:
            warnings.append("tiny_canary_values_are_placeholders_until_operator_sets_real_caps")
    configured = enabled and not errors
    if configured:
        status = "configured_from_file" if source == "json_file" else "configured_from_cli"
    elif path is not None and not path_exists and source == "cli_or_default":
        status = "missing_optional_config_file"
    elif not enabled:
        status = "disabled"
    else:
        status = "invalid_or_incomplete"
    return {
        "status": status,
        "configured": configured,
        "source": source,
        "path": _display_path(path) if path is not None else None,
        "path_exists": path_exists,
        "enabled": enabled,
        "effective": effective,
        "safeguards": safeguards,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "required_safeguards": {
            "scope_symbol": EXPECTED_SYMBOL,
            "strategy_family": "market_state_rotation_v6",
            "max_notional_usdt": "positive operator-defined tiny canary notional",
            "max_daily_order_count": "integer between 1 and 3",
            "max_consecutive_loss_count": "integer between 1 and 2",
            "kill_switch_required": True,
            "reduce_only_exit_required": True,
            "operator_acknowledged_no_auto_live_order": True,
            "max_daily_loss_usdt": "positive and <= 50% of max_notional_usdt",
            "max_leverage": "<= 10",
        },
        "operator_review": {
            "required": not configured,
            "reason": "tiny_canary_risk_caps_are_operator_defined_and_never_auto_enabled_by_evidence_cycle",
            "target_config_path": _display_path(path) if path is not None else DEFAULT_CANARY_RISK_CAPS_PATH,
            "template_path": "reports/operations/market_state_rotation_v6_canary_risk_caps.template.json",
            "safe_template_copy_command": (
                "cp reports/operations/market_state_rotation_v6_canary_risk_caps.template.json "
                "reports/operations/market_state_rotation_v6_canary_risk_caps.json"
            ),
            "quick_audit_command": (
                ".venv/bin/python scripts/run_market_state_rotation_v6_canary_risk_caps_audit.py "
                "--write-report "
                "--canary-risk-caps-json reports/operations/market_state_rotation_v6_canary_risk_caps.json "
                "--report-dir reports/validation/diagnostics/market_state_rotation_v6_canary_risk_caps_audit"
            ),
            "validation_command": (
                ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                "--quote-samples-per-tick 0 "
                "--canary-risk-caps-json reports/operations/market_state_rotation_v6_canary_risk_caps.json "
                "--report-dir reports/validation/diagnostics/market_state_rotation_v6_canary_risk_caps_review"
            ),
            "review_checklist": [
                "set_enabled_true_only_after_operator_review",
                "keep_scope_symbol_BTCUSDT",
                "keep_strategy_family_market_state_rotation_v6",
                "choose_max_notional_usdt_as_tiny_canary_size",
                "keep_max_leverage_lte_10",
                "keep_max_daily_loss_usdt_positive_and_lte_50pct_of_notional",
                "keep_max_daily_order_count_between_1_and_3",
                "keep_max_consecutive_loss_count_between_1_and_2",
                "set_operator_acknowledged_no_auto_live_order_true_only_after_review",
            ],
            "no_live_order_sent": True,
        },
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _quote_cadence_preflight(
    *,
    sample_jsonl: Path,
    requested_quote_samples_per_tick: int,
    required_quote_samples: int,
    min_quote_calendar_days: int,
    min_quote_distinct_hours: int,
    symbol: str,
    strategy_family: str = EXPECTED_STRATEGY_FAMILY,
    generated_at: datetime | None = None,
    adaptive_quote_cadence: bool = True,
    force_quote_sample: bool = False,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    requested = max(0, int(requested_quote_samples_per_tick))
    if not adaptive_quote_cadence:
        return {
            "status": "disabled",
            "requested_quote_samples_per_tick": requested,
            "effective_quote_samples_per_tick": requested,
            "decision": "use_requested_quote_sample_count",
            "no_live_order_sent": True,
        }
    rows = _load_jsonl(sample_jsonl)
    quote_report = build_quote_shadow_audit_report(
        rows,
        input_sample_path=_display_path(sample_jsonl),
        expected_symbol=symbol,
        expected_strategy_family=strategy_family,
        required_quote_samples=max(1, int(required_quote_samples)),
        min_calendar_days=max(1, int(min_quote_calendar_days)),
        min_distinct_hours=max(1, int(min_quote_distinct_hours)),
        generated_at=generated_at,
    )
    current_utc_date = generated_at.date().isoformat()
    current_utc_hour = f"{generated_at.hour:02d}"
    calendar_days = set(str(item) for item in quote_report.get("calendar_days") or [])
    coverage = dict(quote_report.get("coverage") or {})
    covered_hour_buckets = set(str(item) for item in coverage.get("utc_hour_of_day_covered") or [])
    missing_hour_buckets = list(coverage.get("utc_hour_of_day_missing") or [])
    current_date_covered = current_utc_date in calendar_days
    current_hour_covered = current_utc_hour in covered_hour_buckets
    missing_samples = int(quote_report.get("missing_quote_samples") or 0)
    missing_calendar_days = max(int(quote_report.get("min_calendar_days") or 0) - int(quote_report.get("calendar_day_count") or 0), 0)
    missing_distinct_hours = max(int(quote_report.get("min_distinct_hours") or 0) - int(quote_report.get("distinct_hour_count") or 0), 0)
    if requested <= 0:
        effective = 0
        decision = "quote_capture_not_requested"
    elif force_quote_sample:
        effective = requested
        decision = "forced_quote_capture"
    elif missing_calendar_days <= 0 and missing_distinct_hours <= 0 and missing_samples <= 0:
        effective = 0
        decision = "skip_quote_capture_all_quote_gates_passed"
    elif missing_calendar_days > 0 and not current_date_covered:
        effective = requested
        decision = "capture_new_utc_date_for_calendar_gate"
    elif missing_distinct_hours > 0 and not current_hour_covered:
        effective = requested
        decision = "capture_new_utc_hour_for_hour_gate"
    elif missing_distinct_hours > 0 and current_hour_covered:
        effective = 0
        decision = "skip_duplicate_utc_hour_until_missing_hour_window"
    elif missing_samples > 0:
        effective = requested
        decision = "capture_for_quote_sample_count_gate"
    else:
        effective = 0
        decision = "skip_quote_capture_no_incremental_quote_gate_progress"
    return {
        "status": "active",
        "requested_quote_samples_per_tick": requested,
        "effective_quote_samples_per_tick": effective,
        "decision": decision,
        "force_quote_sample": bool(force_quote_sample),
        "current_utc_date": current_utc_date,
        "current_utc_hour_of_day": current_utc_hour,
        "current_utc_date_already_covered": current_date_covered,
        "current_utc_hour_already_covered": current_hour_covered,
        "missing_quote_samples": missing_samples,
        "missing_calendar_days": missing_calendar_days,
        "missing_distinct_hours": missing_distinct_hours,
        "covered_utc_hour_buckets": sorted(covered_hour_buckets),
        "missing_utc_hour_buckets": missing_hour_buckets,
        "eligible_quote_rows_before_capture": int(quote_report.get("eligible_row_count") or 0),
        "calendar_day_count_before_capture": int(quote_report.get("calendar_day_count") or 0),
        "distinct_hour_count_before_capture": int(quote_report.get("distinct_hour_count") or 0),
        "sample_path": _display_path(sample_jsonl),
        "no_live_order_sent": True,
    }


def _paper_apply_gate(cycle_report: dict[str, Any]) -> dict[str, Any]:
    bridge = dict(cycle_report.get("bridge") or {})
    blockers = set(str(item) for item in bridge.get("snapshot_blockers") or [])
    bridge_status = str(bridge.get("overall_status") or "")
    execution_parity_preflight = dict(bridge.get("execution_parity_preflight") or {})
    preflight_passed = execution_parity_preflight.get("passed") is True or not execution_parity_preflight
    apply_requested = bridge.get("apply_paper") is True
    fresh_market_data = "market_data_stale" not in blockers
    fresh_signal = "signal_stale" not in blockers and "no_recent_v6_trade_event" not in blockers
    if not fresh_market_data:
        status = "blocked_market_data_stale"
        can_request_apply = False
        next_step = "rerun_evidence_cycle_until_market_data_is_fresh"
    elif not fresh_signal:
        status = "blocked_waiting_for_fresh_signal"
        can_request_apply = False
        next_step = "wait_for_fresh_v6_add_or_remove_signal"
    elif not preflight_passed:
        status = "blocked_execution_parity_preflight"
        can_request_apply = False
        next_step = "fix_execution_parity_preflight_fields_before_paper_apply"
    elif not apply_requested and bridge_status == "dry_run_actionable":
        status = "paper_apply_request_available"
        can_request_apply = True
        next_step = "rerun_evidence_cycle_with_apply_paper_bridge_after_operator_review"
    elif apply_requested:
        status = "paper_apply_requested"
        can_request_apply = False
        next_step = "review_paper_bridge_result_and_lifecycle_rows"
    else:
        status = "review_bridge_status"
        can_request_apply = False
        next_step = "inspect_collection_cycle_bridge_report"
    return {
        "status": status,
        "bridge_status": bridge_status,
        "bridge_action": bridge.get("bridge_action"),
        "apply_requested": apply_requested,
        "can_request_paper_apply_now": can_request_apply,
        "fresh_market_data": fresh_market_data,
        "fresh_signal": fresh_signal,
        "execution_parity_preflight_passed": preflight_passed,
        "execution_parity_preflight": execution_parity_preflight,
        "snapshot_blockers": list(bridge.get("snapshot_blockers") or []),
        "required_pre_apply_backup": True,
        "next_step": next_step,
    }


def _pre_apply_backup_plan(*, apply_gate: dict[str, Any], pre_apply_backup_dir: Path | None) -> dict[str, Any]:
    backup_dir = _display_path(pre_apply_backup_dir) if pre_apply_backup_dir is not None else None
    apply_available = apply_gate.get("can_request_paper_apply_now") is True
    fresh_signal = apply_gate.get("fresh_signal") is True
    if apply_available:
        status = "ready_required_before_paper_apply"
        next_action = "operator_must_confirm_sqlite_backup_created_and_quick_check_ok_before_apply"
    elif not fresh_signal:
        status = "armed_waiting_for_fresh_signal"
        next_action = "keep_backup_plan_attached_to_signal_monitor_until_apply_gate_opens"
    else:
        status = "blocked_until_paper_apply_gate_available"
        next_action = "inspect_paper_bridge_apply_gate_before_apply"
    return {
        "status": status,
        "required": apply_gate.get("required_pre_apply_backup") is not False,
        "backup_dir": backup_dir,
        "backup_dir_configured": backup_dir is not None,
        "created_by": "scripts/run_market_state_rotation_v6_paper_bridge_tick.py",
        "created_during": "run_market_state_rotation_v6_evidence_cycle.py --apply-paper-bridge",
        "verification_required": True,
        "verification_required_fields": [
            "pre_apply_backup.created == true",
            "pre_apply_backup.quick_check == 'ok'",
            "pre_apply_backup.backup_path is not empty",
        ],
        "fail_closed_status": "pre_apply_backup_failed",
        "paper_apply_gate_status": apply_gate.get("status"),
        "paper_apply_allowed_now": apply_available,
        "fresh_signal": fresh_signal,
        "next_action": next_action,
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _collection_progress(cycle_report: dict[str, Any]) -> dict[str, Any]:
    collection = dict(cycle_report.get("collection") or {})
    readiness = dict(collection.get("readiness") or {})
    quote = dict(collection.get("quote_samples") or {})
    coverage = dict(quote.get("coverage") or {})
    observed = int(quote.get("observed") or 0)
    required = int(quote.get("required") or 0)
    calendar_days = int(quote.get("calendar_days") or 0)
    min_calendar_days = int(quote.get("min_calendar_days") or 0)
    distinct_hours = int(quote.get("distinct_hours") or 0)
    min_distinct_hours = int(quote.get("min_distinct_hours") or 0)
    missing_samples = max(required - observed, 0)
    missing_days = max(min_calendar_days - calendar_days, 0)
    missing_hours = max(min_distinct_hours - distinct_hours, 0)
    paper_fill_rows = int(dict(collection.get("paper_fill") or {}).get("v6_lifecycle_rows") or 0)
    failed_gates = list(readiness.get("failed_gates") or [])
    captured_quote_rows = int(collection.get("captured_quote_rows") or 0)
    if missing_days > 0:
        dominant_blocker = "quote_calendar_days"
    elif missing_hours > 0:
        dominant_blocker = "quote_distinct_hours"
    elif missing_samples > 0:
        dominant_blocker = "quote_samples"
    elif "min_shadow_fill_samples" in set(str(item) for item in failed_gates):
        dominant_blocker = "paper_shadow_fill_samples"
    else:
        dominant_blocker = "none"
    return {
        "quote_observed": observed,
        "quote_required": required,
        "quote_missing_samples": missing_samples,
        "quote_calendar_days": calendar_days,
        "quote_min_calendar_days": min_calendar_days,
        "quote_missing_calendar_days": missing_days,
        "quote_distinct_hours": distinct_hours,
        "quote_min_distinct_hours": min_distinct_hours,
        "quote_missing_distinct_hours": missing_hours,
        "captured_quote_rows_this_cycle": captured_quote_rows,
        "quote_coverage": coverage,
        "quote_blockers": list(quote.get("blockers") or []),
        "dominant_collection_blocker": dominant_blocker,
        "paper_fill_rows": paper_fill_rows,
        "failed_gates": failed_gates,
        "pending_gates": list(readiness.get("pending_gates") or []),
    }


def _execution_parity_collection_progress(journal_report: dict[str, Any] | None) -> dict[str, Any]:
    if not journal_report:
        return {
            "execution_parity_status": "not_collected",
            "execution_parity_lifecycle_rows": 0,
            "execution_parity_journal_rows": 0,
            "execution_parity_required_rows": 20,
            "execution_parity_missing_samples": 20,
            "execution_parity_passed": False,
            "execution_parity_blockers": ["execution_parity_journal_report_missing"],
        }
    conversion = dict(journal_report.get("conversion") or {})
    summary = dict(journal_report.get("contract_summary") or {})
    required = int(summary.get("min_sample_count") or 20)
    rows = int(conversion.get("journal_row_count") or summary.get("sample_count") or 0)
    return {
        "execution_parity_status": journal_report.get("status"),
        "execution_parity_lifecycle_rows": int(conversion.get("lifecycle_row_count") or 0),
        "execution_parity_journal_rows": rows,
        "execution_parity_required_rows": required,
        "execution_parity_missing_samples": max(required - rows, 0),
        "execution_parity_passed": bool(summary.get("passed")),
        "execution_parity_blockers": list(summary.get("blockers") or []),
    }


def _execution_parity_collection_plan(
    *,
    collection_progress: dict[str, Any],
    apply_gate: dict[str, Any],
    journal_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    conversion = dict(dict(journal_report or {}).get("conversion") or {})
    required = max(1, _int_field(collection_progress, "execution_parity_required_rows", 20))
    journal_rows = max(0, _int_field(collection_progress, "execution_parity_journal_rows", 0))
    lifecycle_rows = max(0, _int_field(collection_progress, "execution_parity_lifecycle_rows", 0))
    missing = max(required - journal_rows, 0)
    entry_rows = max(0, _int_field(conversion, "entry_rows_written", 0))
    exit_rows = max(0, _int_field(conversion, "exit_rows_written", 0))
    include_exit_rows = conversion.get("include_exit_rows") is True
    accepted_actions = ["add", "remove"] if include_exit_rows else ["add"]
    bridge_action = str(apply_gate.get("bridge_action") or "").strip().lower()
    fresh_market_data = apply_gate.get("fresh_market_data") is True
    fresh_signal = apply_gate.get("fresh_signal") is True
    preflight_passed = apply_gate.get("execution_parity_preflight_passed") is True
    paper_apply_available = apply_gate.get("can_request_paper_apply_now") is True
    apply_requested = apply_gate.get("apply_requested") is True
    currently_creditable_actions = (
        [bridge_action]
        if paper_apply_available and bridge_action in set(accepted_actions)
        else []
    )
    will_credit_current_apply = bool(currently_creditable_actions) and missing > 0
    credited_sample_count_after_next_apply = journal_rows + (1 if will_credit_current_apply else 0)
    events_needed_after_next_credit = max(missing - (1 if will_credit_current_apply else 0), 0)
    if missing <= 0 and collection_progress.get("execution_parity_passed") is True:
        status = "passed"
        next_step = "rerun_live_readiness_with_execution_parity_contract"
    elif not fresh_market_data:
        status = "blocked_by_market_data_freshness"
        next_step = "refresh_market_data_before_waiting_for_creditable_signal"
    elif not fresh_signal:
        status = "waiting_for_fresh_signal"
        next_step = "wait_for_fresh_v6_add_or_remove_signal"
    elif not preflight_passed:
        status = "blocked_by_execution_parity_preflight"
        next_step = "fix_execution_parity_preflight_fields_before_paper_apply"
    elif paper_apply_available:
        status = "ready_to_credit_next_paper_apply"
        next_step = "operator_review_then_apply_paper_bridge_to_create_one_real_lifecycle_sample"
    elif apply_requested:
        status = "paper_apply_requested_review_lifecycle_rows"
        next_step = "review_paper_bridge_result_and_rerun_execution_parity_journal"
    else:
        status = "collecting_wait_for_complete_lifecycle_rows"
        next_step = "inspect_collection_cycle_bridge_report"
    return {
        "status": status,
        "required_samples": required,
        "eligible_journal_rows": journal_rows,
        "eligible_lifecycle_rows": lifecycle_rows,
        "entry_rows_written": entry_rows,
        "exit_rows_written": exit_rows,
        "missing_samples": missing,
        "estimated_future_paper_apply_events_needed": missing,
        "estimated_events_needed_after_current_creditable_apply": events_needed_after_next_credit,
        "projected_journal_rows_after_current_creditable_apply": credited_sample_count_after_next_apply,
        "sample_credit_per_completed_paper_apply_event": 1,
        "will_credit_current_apply_after_operator_review": will_credit_current_apply,
        "accepted_actions": accepted_actions,
        "currently_creditable_actions": currently_creditable_actions,
        "next_creditable_event_types": accepted_actions,
        "bridge_action": bridge_action or None,
        "paper_apply_status": apply_gate.get("status"),
        "paper_apply_available_now": paper_apply_available,
        "fresh_market_data": fresh_market_data,
        "fresh_signal": fresh_signal,
        "execution_parity_preflight_passed": preflight_passed,
        "execution_parity_preflight": dict(apply_gate.get("execution_parity_preflight") or {}),
        "blockers": list(collection_progress.get("execution_parity_blockers") or []),
        "next_step": next_step,
        "sample_credit_policy": {
            "add": "one_completed_paper_add_lifecycle_row_counts_as_one_execution_parity_sample",
            "remove": (
                "one_completed_paper_remove_exit_lifecycle_row_counts_as_one_execution_parity_sample"
                if include_exit_rows
                else "remove_rows_are_not_enabled_for_this_journal_run"
            ),
            "backtest_rows": "not_creditable_for_execution_parity",
            "manual_or_synthetic_rows": "not_creditable_for_execution_parity",
        },
        "non_substitutable": True,
        "backtest_substitution_allowed": False,
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _execution_parity_markdown(report: dict[str, Any]) -> str:
    conversion = dict(report.get("conversion") or {})
    summary = dict(report.get("contract_summary") or {})
    return "\n".join(
        [
            "# Market State Rotation V6 Execution Parity Journal",
            "",
            f"- status: `{report.get('status')}`",
            f"- no_live_order_sent: `{report.get('no_live_order_sent')}`",
            f"- lifecycle_rows: `{conversion.get('lifecycle_row_count')}`",
            f"- journal_rows: `{conversion.get('journal_row_count')}/{summary.get('min_sample_count')}`",
            f"- missing_samples: `{conversion.get('missing_to_min_sample_count')}`",
            f"- contract_passed: `{summary.get('passed')}`",
            f"- contract_status: `{summary.get('status')}`",
            f"- blockers: `{', '.join(summary.get('blockers') or [])}`",
            "",
        ]
    )


def _pct(observed: int | float, required: int | float) -> float:
    required_float = float(required or 0)
    if required_float <= 0:
        return 100.0
    value = max(float(observed or 0), 0.0) / required_float * 100.0
    return round(min(value, 100.0), 4)


def _readiness_progress(
    *,
    collection_progress: dict[str, Any],
    collection_forecast: dict[str, Any],
    apply_gate: dict[str, Any],
    min_shadow_fill_samples: int,
) -> dict[str, Any]:
    quote_observed = int(collection_progress.get("quote_observed") or 0)
    quote_required = int(collection_progress.get("quote_required") or 0)
    quote_calendar_days = int(collection_progress.get("quote_calendar_days") or 0)
    quote_min_calendar_days = int(collection_progress.get("quote_min_calendar_days") or 0)
    quote_distinct_hours = int(collection_progress.get("quote_distinct_hours") or 0)
    quote_min_distinct_hours = int(collection_progress.get("quote_min_distinct_hours") or 0)
    paper_fill_rows = int(collection_progress.get("paper_fill_rows") or 0)
    paper_fill_required = max(1, int(min_shadow_fill_samples or 1))
    execution_parity_rows = int(collection_progress.get("execution_parity_journal_rows") or 0)
    execution_parity_required = max(1, int(collection_progress.get("execution_parity_required_rows") or 20))
    execution_parity_missing = max(
        int(collection_progress.get("execution_parity_missing_samples") or 0),
        0,
    )
    execution_parity_passed = collection_progress.get("execution_parity_passed") is True
    execution_parity_blockers = list(collection_progress.get("execution_parity_blockers") or [])
    coverage_count = int(collection_forecast.get("utc_hour_of_day_covered_count") or 0)
    fresh_market_data = apply_gate.get("fresh_market_data") is True
    fresh_signal = apply_gate.get("fresh_signal") is True
    quote_gate_pcts = {
        "quote_samples": _pct(quote_observed, quote_required),
        "quote_calendar_days": _pct(quote_calendar_days, quote_min_calendar_days),
        "quote_distinct_hours": _pct(quote_distinct_hours, quote_min_distinct_hours),
    }
    paper_shadow_fill_pct = _pct(paper_fill_rows, paper_fill_required)
    execution_parity_pct = _pct(execution_parity_rows, execution_parity_required)
    quote_evidence_readiness_pct = min(quote_gate_pcts.values()) if quote_gate_pcts else 100.0
    shadow_promotion_readiness_pct = min(quote_evidence_readiness_pct, paper_shadow_fill_pct)
    paper_apply_readiness_pct = min(100.0 if fresh_market_data else 0.0, 100.0 if fresh_signal else 0.0)
    weighted_shadow_inputs = [*quote_gate_pcts.values(), paper_shadow_fill_pct]
    weighted_shadow_evidence_pct = (
        round(sum(weighted_shadow_inputs) / len(weighted_shadow_inputs), 4) if weighted_shadow_inputs else 100.0
    )
    blocking_gates: list[dict[str, Any]] = []
    if not fresh_market_data:
        blocking_gates.append(
            {
                "gate": "market_data_freshness",
                "pct": 0.0,
                "missing": 1,
                "next_step": "rerun_evidence_cycle_until_market_data_is_fresh",
            }
        )
    if not fresh_signal:
        blocking_gates.append(
            {
                "gate": "fresh_signal",
                "pct": 0.0,
                "missing": 1,
                "next_step": "wait_for_fresh_v6_add_or_remove_signal",
            }
        )
    paper_fill_missing = max(paper_fill_required - paper_fill_rows, 0)
    if paper_fill_missing > 0:
        blocking_gates.append(
            {
                "gate": "paper_shadow_fill_samples",
                "pct": paper_shadow_fill_pct,
                "observed": paper_fill_rows,
                "required": paper_fill_required,
                "missing": paper_fill_missing,
                "next_step": "collect_paper_lifecycle_rows_from_fresh_v6_signals",
            }
        )
    if not execution_parity_passed:
        blocking_gates.append(
            {
                "gate": "execution_parity_journal",
                "pct": execution_parity_pct,
                "observed": execution_parity_rows,
                "required": execution_parity_required,
                "missing": execution_parity_missing,
                "blockers": execution_parity_blockers,
                "next_step": "collect_real_paper_lifecycle_rows_and_rerun_execution_parity_journal",
            }
        )
    quote_missing_days = int(collection_progress.get("quote_missing_calendar_days") or 0)
    if quote_missing_days > 0:
        blocking_gates.append(
            {
                "gate": "quote_calendar_days",
                "pct": quote_gate_pcts["quote_calendar_days"],
                "observed": quote_calendar_days,
                "required": quote_min_calendar_days,
                "missing": quote_missing_days,
                "next_step": "run_evidence_cycle_once_per_new_utc_day_until_quote_calendar_floor_passes",
            }
        )
    quote_missing_hours = int(collection_progress.get("quote_missing_distinct_hours") or 0)
    if quote_missing_hours > 0:
        blocking_gates.append(
            {
                "gate": "quote_distinct_hours",
                "pct": quote_gate_pcts["quote_distinct_hours"],
                "observed": quote_distinct_hours,
                "required": quote_min_distinct_hours,
                "missing": quote_missing_hours,
                "next_step": "spread_quote_shadow_collection_across_missing_utc_hours",
            }
        )
    quote_missing_samples = int(collection_progress.get("quote_missing_samples") or 0)
    if quote_missing_samples > 0:
        blocking_gates.append(
            {
                "gate": "quote_samples",
                "pct": quote_gate_pcts["quote_samples"],
                "observed": quote_observed,
                "required": quote_required,
                "missing": quote_missing_samples,
                "next_step": "collect_additional_quote_shadow_samples",
            }
        )
    strictest_quote_gate = min(quote_gate_pcts.items(), key=lambda item: item[1])[0]
    strictest_deployment_gate = blocking_gates[0]["gate"] if blocking_gates else "none"
    return {
        "quote_sample_pct": quote_gate_pcts["quote_samples"],
        "quote_calendar_day_pct": quote_gate_pcts["quote_calendar_days"],
        "quote_distinct_hour_pct": quote_gate_pcts["quote_distinct_hours"],
        "quote_hour_of_day_coverage_pct": _pct(coverage_count, 24),
        "paper_shadow_fill_pct": paper_shadow_fill_pct,
        "execution_parity_journal_pct": execution_parity_pct,
        "execution_parity_passed": execution_parity_passed,
        "execution_parity_blockers": execution_parity_blockers,
        "fresh_market_data_pct": 100.0 if fresh_market_data else 0.0,
        "fresh_signal_pct": 100.0 if fresh_signal else 0.0,
        "paper_apply_readiness_pct": paper_apply_readiness_pct,
        "quote_evidence_readiness_pct": quote_evidence_readiness_pct,
        "shadow_promotion_readiness_pct": shadow_promotion_readiness_pct,
        "weighted_shadow_evidence_pct": weighted_shadow_evidence_pct,
        "strictest_quote_gate": strictest_quote_gate,
        "strictest_quote_gate_pct": quote_gate_pcts[strictest_quote_gate],
        "strictest_deployment_gate": strictest_deployment_gate,
        "blocking_gates_ordered": blocking_gates,
        "remaining_work_units": {
            "quote_samples": quote_missing_samples,
            "quote_calendar_days": quote_missing_days,
            "quote_distinct_hours": quote_missing_hours,
            "paper_shadow_fill_samples": paper_fill_missing,
            "execution_parity_samples": execution_parity_missing,
            "execution_parity_contract": 0 if execution_parity_passed else 1,
            "market_data_freshness": 0 if fresh_market_data else 1,
            "fresh_signal": 0 if fresh_signal else 1,
        },
        "live_order_gate": {
            "status": "closed_by_design_in_evidence_cycle",
            "reason": "evidence_cycle_can_only_authorize_paper_stage",
        },
        "next_unblocked_operator_step": blocking_gates[0]["next_step"] if blocking_gates else "review_paper_apply_gate",
    }


def _gate_status(is_blocked: bool) -> str:
    return "blocking" if is_blocked else "passed"


def _execution_checklist(
    *,
    collection_progress: dict[str, Any],
    collection_forecast: dict[str, Any],
    readiness_progress: dict[str, Any],
    apply_gate: dict[str, Any],
    report_dir: Path,
) -> dict[str, Any]:
    remaining = dict(readiness_progress.get("remaining_work_units") or {})
    blocking_gate_names = {str(item.get("gate")) for item in readiness_progress.get("blocking_gates_ordered") or []}
    paper_apply_allowed_now = apply_gate.get("can_request_paper_apply_now") is True
    quote_ready = all(
        int(remaining.get(key) or 0) == 0 for key in ("quote_samples", "quote_calendar_days", "quote_distinct_hours")
    )
    paper_shadow_ready = int(remaining.get("paper_shadow_fill_samples") or 0) == 0
    execution_parity_ready = int(remaining.get("execution_parity_contract") or 0) == 0
    fresh_signal_ready = int(remaining.get("fresh_signal") or 0) == 0
    if not fresh_signal_ready:
        current_phase = "wait_for_fresh_signal_and_continue_shadow_collection"
    elif paper_apply_allowed_now:
        current_phase = "paper_apply_operator_review_available"
    elif not quote_ready:
        current_phase = "quote_shadow_collection"
    elif not paper_shadow_ready:
        current_phase = "paper_shadow_fill_collection"
    else:
        current_phase = "shadow_gate_review"
    checklist_items = [
        {
            "gate": "market_data_freshness",
            "status": _gate_status("market_data_freshness" in blocking_gate_names),
            "remaining": int(remaining.get("market_data_freshness") or 0),
        },
        {
            "gate": "fresh_signal",
            "status": _gate_status("fresh_signal" in blocking_gate_names),
            "remaining": int(remaining.get("fresh_signal") or 0),
        },
        {
            "gate": "quote_calendar_days",
            "status": _gate_status("quote_calendar_days" in blocking_gate_names),
            "observed": collection_progress.get("quote_calendar_days"),
            "required": collection_progress.get("quote_min_calendar_days"),
            "remaining": int(remaining.get("quote_calendar_days") or 0),
        },
        {
            "gate": "quote_distinct_hours",
            "status": _gate_status("quote_distinct_hours" in blocking_gate_names),
            "observed": collection_progress.get("quote_distinct_hours"),
            "required": collection_progress.get("quote_min_distinct_hours"),
            "remaining": int(remaining.get("quote_distinct_hours") or 0),
        },
        {
            "gate": "quote_samples",
            "status": _gate_status("quote_samples" in blocking_gate_names),
            "observed": collection_progress.get("quote_observed"),
            "required": collection_progress.get("quote_required"),
            "remaining": int(remaining.get("quote_samples") or 0),
        },
        {
            "gate": "paper_shadow_fill_samples",
            "status": _gate_status("paper_shadow_fill_samples" in blocking_gate_names),
            "observed": collection_progress.get("paper_fill_rows"),
            "remaining": int(remaining.get("paper_shadow_fill_samples") or 0),
        },
        {
            "gate": "execution_parity_journal",
            "status": _gate_status("execution_parity_journal" in blocking_gate_names),
            "observed": collection_progress.get("execution_parity_journal_rows"),
            "required": collection_progress.get("execution_parity_required_rows"),
            "remaining": int(remaining.get("execution_parity_samples") or 0),
            "contract_blocked": int(remaining.get("execution_parity_contract") or 0) > 0,
            "blockers": list(collection_progress.get("execution_parity_blockers") or []),
        },
    ]
    return {
        "current_phase": current_phase,
        "paper_apply_allowed_now": paper_apply_allowed_now,
        "shadow_promotion_ready": quote_ready and paper_shadow_ready,
        "execution_parity_ready": execution_parity_ready,
        "live_ready": False,
        "live_block_reason": "evidence_cycle_is_paper_only_and_live_requires_separate_operator_promotion_gate",
        "target_next_utc_hour_of_day": collection_forecast.get("target_next_utc_hour_of_day"),
        "target_next_kst_hour_of_day": collection_forecast.get("target_next_kst_hour_of_day"),
        "earliest_quote_calendar_gate_date_utc": collection_forecast.get("earliest_quote_calendar_gate_date_utc"),
        "checklist_items": checklist_items,
        "commands": {
            "continue_evidence_cycle": (
                ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                "--quote-samples-per-tick 2 --report-dir reports/validation/diagnostics/<new_report_dir>"
            ),
            "paper_apply_after_operator_review": (
                ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                "--apply-paper-bridge --quote-samples-per-tick 2 "
                "--report-dir reports/validation/diagnostics/<paper_apply_report_dir>"
            ),
        },
    }


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _utc_midnight(day: Any) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _coerce_utc_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        numeric = float(value)
        divisor = 1000.0 if abs(numeric) >= 10_000_000_000 else 1.0
        try:
            return datetime.fromtimestamp(numeric / divisor, UTC)
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        numeric = float(text)
    except ValueError:
        parsed = _parse_dt(text)
        if parsed is None:
            return None
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    divisor = 1000.0 if abs(numeric) >= 10_000_000_000 else 1.0
    try:
        return datetime.fromtimestamp(numeric / divisor, UTC)
    except (OSError, OverflowError, ValueError):
        return None


def _historical_candle_timestamp(row: Any) -> datetime | None:
    if isinstance(row, dict):
        for key in ("ts", "timestamp", "datetime", "open_time", "openTime", "time"):
            parsed = _coerce_utc_datetime(row.get(key))
            if parsed is not None:
                return parsed
        for key in ("open_ms", "open_time_ms", "openTimeMs", "t"):
            parsed = _coerce_utc_datetime(row.get(key))
            if parsed is not None:
                return parsed
        return None
    if isinstance(row, (list, tuple)) and row:
        return _coerce_utc_datetime(row[0])
    return None


def _historical_replay_rolling_windows(
    *,
    timestamps: list[datetime],
    required_quote_samples: int,
    min_quote_calendar_days: int,
    min_quote_distinct_hours: int,
) -> dict[str, Any]:
    if not timestamps:
        return {
            "status": "no_proxy_samples",
            "window_count": 0,
            "no_live_order_sent": True,
        }
    window_days = max(1, int(min_quote_calendar_days or 1))
    samples_by_date: dict[Any, int] = {}
    hours_by_date: dict[Any, set[int]] = {}
    for ts in timestamps:
        day = ts.date()
        samples_by_date[day] = samples_by_date.get(day, 0) + 1
        hours_by_date.setdefault(day, set()).add(ts.hour)
    start_day = min(samples_by_date)
    end_day = max(samples_by_date)
    first_window_end = start_day + timedelta(days=window_days - 1)
    if first_window_end > end_day:
        return {
            "status": "not_enough_calendar_span_for_walk_forward_window",
            "window_days": window_days,
            "calendar_span_days": (end_day - start_day).days + 1,
            "window_count": 0,
            "no_live_order_sent": True,
        }
    current = first_window_end
    window_count = 0
    passed_count = 0
    failing_windows: list[dict[str, Any]] = []
    worst_window: dict[str, Any] | None = None
    first_passing_end: str | None = None
    while current <= end_day:
        window_start = current - timedelta(days=window_days - 1)
        sample_count = 0
        calendar_days = 0
        hours: set[int] = set()
        day = window_start
        while day <= current:
            day_samples = int(samples_by_date.get(day) or 0)
            sample_count += day_samples
            if day_samples > 0:
                calendar_days += 1
            hours.update(hours_by_date.get(day, set()))
            day += timedelta(days=1)
        distinct_hours = len(hours)
        sample_pct = _pct(sample_count, required_quote_samples)
        calendar_pct = _pct(calendar_days, min_quote_calendar_days)
        hour_pct = _pct(distinct_hours, min_quote_distinct_hours)
        bottleneck_pct = min(sample_pct, calendar_pct, hour_pct)
        passed = (
            sample_count >= max(1, int(required_quote_samples or 1))
            and calendar_days >= max(1, int(min_quote_calendar_days or 1))
            and distinct_hours >= max(1, int(min_quote_distinct_hours or 1))
        )
        item = {
            "window_start_utc_date": window_start.isoformat(),
            "window_end_utc_date": current.isoformat(),
            "proxy_quote_samples": sample_count,
            "calendar_days": calendar_days,
            "distinct_utc_hours": distinct_hours,
            "bottleneck_pct": bottleneck_pct,
            "passed": passed,
        }
        if passed:
            passed_count += 1
            first_passing_end = first_passing_end or current.isoformat()
        elif len(failing_windows) < 5:
            failing_windows.append(item)
        if worst_window is None or bottleneck_pct < float(worst_window.get("bottleneck_pct") or 101.0):
            worst_window = item
        window_count += 1
        current += timedelta(days=1)
    pass_rate_pct = round((passed_count / window_count * 100.0) if window_count else 0.0, 4)
    status = "passed" if window_count > 0 and passed_count == window_count else "partial"
    return {
        "status": status,
        "window_days": window_days,
        "window_count": window_count,
        "passed_window_count": passed_count,
        "failed_window_count": window_count - passed_count,
        "pass_rate_pct": pass_rate_pct,
        "first_passing_window_end_utc_date": first_passing_end,
        "worst_window": worst_window,
        "failing_windows_preview": failing_windows,
        "future_visibility_policy": "each_window_uses_only_samples_whose_timestamp_is_on_or_before_that_window_end",
        "no_live_order_sent": True,
    }


def _historical_evidence_replay(
    *,
    source_path: Path,
    generated_at: datetime,
    replay_days: int,
    required_quote_samples: int,
    min_quote_calendar_days: int,
    min_quote_distinct_hours: int,
    symbol: str = EXPECTED_SYMBOL,
) -> dict[str, Any]:
    resolved = _resolve(source_path)
    if not resolved.exists():
        return {
            "status": "source_missing",
            "source_path": _display_path(resolved),
            "no_live_order_sent": True,
        }
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "source_unreadable",
            "source_path": _display_path(resolved),
            "error": str(exc),
            "no_live_order_sent": True,
        }
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return {
            "status": "source_rows_missing",
            "source_path": _display_path(resolved),
            "no_live_order_sent": True,
        }
    source_symbol = str(payload.get("symbol") or "").upper() if isinstance(payload, dict) else ""
    source_interval = payload.get("interval") if isinstance(payload, dict) else None
    source_declared_days = payload.get("days") if isinstance(payload, dict) else None
    generated_at = generated_at.astimezone(UTC)
    timestamps: list[datetime] = []
    invalid_timestamp_rows = 0
    future_rows_excluded = 0
    for row in rows:
        ts = _historical_candle_timestamp(row)
        if ts is None:
            invalid_timestamp_rows += 1
            continue
        ts = ts.astimezone(UTC)
        if ts > generated_at:
            future_rows_excluded += 1
            continue
        timestamps.append(ts)
    timestamps.sort()
    if not timestamps:
        return {
            "status": "no_past_rows_available",
            "source_path": _display_path(resolved),
            "source_row_count": len(rows),
            "invalid_timestamp_rows": invalid_timestamp_rows,
            "future_rows_excluded": future_rows_excluded,
            "replay_cursor_utc": generated_at.isoformat(),
            "no_live_order_sent": True,
        }
    replay_end = timestamps[-1]
    requested_days = max(1, int(replay_days or 1))
    replay_start_day = replay_end.date() - timedelta(days=requested_days - 1)
    replay_start = _utc_midnight(replay_start_day)
    selected = [ts for ts in timestamps if replay_start <= ts <= replay_end]
    calendar_days = sorted({ts.date().isoformat() for ts in selected})
    distinct_hours = sorted({f"{ts.hour:02d}" for ts in selected})
    proxy_samples = len(selected)
    aggregate_gate = {
        "quote_samples_passed": proxy_samples >= max(1, int(required_quote_samples or 1)),
        "quote_calendar_days_passed": len(calendar_days) >= max(1, int(min_quote_calendar_days or 1)),
        "quote_distinct_hours_passed": len(distinct_hours) >= max(1, int(min_quote_distinct_hours or 1)),
        "proxy_quote_samples": proxy_samples,
        "required_quote_samples": max(1, int(required_quote_samples or 1)),
        "calendar_day_count": len(calendar_days),
        "min_quote_calendar_days": max(1, int(min_quote_calendar_days or 1)),
        "distinct_utc_hour_count": len(distinct_hours),
        "min_quote_distinct_hours": max(1, int(min_quote_distinct_hours or 1)),
        "quote_sample_pct": _pct(proxy_samples, required_quote_samples),
        "quote_calendar_day_pct": _pct(len(calendar_days), min_quote_calendar_days),
        "quote_distinct_hour_pct": _pct(len(distinct_hours), min_quote_distinct_hours),
    }
    rolling = _historical_replay_rolling_windows(
        timestamps=selected,
        required_quote_samples=max(1, int(required_quote_samples or 1)),
        min_quote_calendar_days=max(1, int(min_quote_calendar_days or 1)),
        min_quote_distinct_hours=max(1, int(min_quote_distinct_hours or 1)),
    )
    gate_passed = all(
        bool(aggregate_gate.get(key))
        for key in ("quote_samples_passed", "quote_calendar_days_passed", "quote_distinct_hours_passed")
    )
    status = "passed" if gate_passed and rolling.get("status") == "passed" else "partial"
    warnings: list[str] = []
    if source_symbol and source_symbol != str(symbol or "").upper():
        warnings.append("source_symbol_differs_from_requested_symbol")
    return {
        "status": status,
        "source_path": _display_path(resolved),
        "source_symbol": source_symbol or None,
        "requested_symbol": str(symbol or "").upper(),
        "source_interval": source_interval,
        "source_declared_days": source_declared_days,
        "source_row_count": len(rows),
        "usable_past_row_count": len(timestamps),
        "selected_proxy_sample_count": proxy_samples,
        "invalid_timestamp_rows": invalid_timestamp_rows,
        "future_rows_excluded": future_rows_excluded,
        "requested_replay_days": requested_days,
        "selected_replay_start_utc": replay_start.isoformat(),
        "selected_replay_end_utc": replay_end.isoformat(),
        "selected_calendar_day_count": len(calendar_days),
        "selected_distinct_utc_hour_count": len(distinct_hours),
        "covered_utc_hours": distinct_hours,
        "calendar_dates_preview": {
            "first": calendar_days[:5],
            "last": calendar_days[-5:],
        },
        "aggregate_quote_gate": aggregate_gate,
        "rolling_window_confirmation": rolling,
        "future_leakage_guard": {
            "status": "passed",
            "replay_cursor_utc": replay_end.isoformat(),
            "generated_at_utc": generated_at.isoformat(),
            "max_selected_sample_utc": max(selected).isoformat() if selected else None,
            "future_rows_after_generated_at_excluded": future_rows_excluded,
            "policy": "samples_after_generated_at_are_excluded_and_each_walk_forward_window_uses_only_past_or_current_samples",
        },
        "proxy_limitations": [
            "historical_candles_can_replace_calendar_hour_sample_coverage_but_not_real_order_book_microstructure",
            "spread_slippage_latency_still_require_l2_quote_shadow_or_paper_fill_evidence_before_live_promotion",
        ],
        "warnings": warnings,
        "no_live_order_sent": True,
    }


def _first_available_path(payload: dict[str, Any], paths: list[list[str]]) -> Any:
    for path in paths:
        current: Any = payload
        ok = True
        for key in path:
            if not isinstance(current, dict) or key not in current:
                ok = False
                break
            current = current[key]
        if ok:
            return current
    return None


def _historical_source_data_window(payload: dict[str, Any]) -> dict[str, Any]:
    data_status = dict(payload.get("data_status") or {})
    candidates: list[dict[str, Any]] = []
    for interval, meta in data_status.items():
        if not isinstance(meta, dict):
            continue
        first = _coerce_utc_datetime(meta.get("first_ts"))
        last = _coerce_utc_datetime(meta.get("last_ts"))
        if first is not None and last is not None:
            candidates.append({"interval": interval, "first_ts": first, "last_ts": last})
    if candidates:
        candidates.sort(key=lambda item: item["last_ts"])
        chosen = candidates[-1]
        span_days = max((chosen["last_ts"] - chosen["first_ts"]).total_seconds() / 86400.0, 0.0)
        return {
            "interval": chosen["interval"],
            "first_utc": chosen["first_ts"].isoformat(),
            "last_utc": chosen["last_ts"].isoformat(),
            "span_days": round(span_days, 4),
        }
    first_raw = _first_available_path(
        payload,
        [
            ["market_data", "start_ts"],
            ["market_data", "first_ts"],
            ["data_meta", "exec_start"],
            ["data_status", "first_ts"],
        ],
    )
    last_raw = _first_available_path(
        payload,
        [
            ["market_data", "end_ts"],
            ["market_data", "last_ts"],
            ["data_meta", "exec_end"],
            ["data_status", "last_ts"],
        ],
    )
    first = _coerce_utc_datetime(first_raw)
    last = _coerce_utc_datetime(last_raw)
    if first is not None and last is not None:
        span_days = max((last - first).total_seconds() / 86400.0, 0.0)
        return {
            "interval": None,
            "first_utc": first.isoformat(),
            "last_utc": last.isoformat(),
            "span_days": round(span_days, 4),
        }
    return {"interval": None, "first_utc": None, "last_utc": None, "span_days": None}


def _historical_lifecycle_events_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for key in ("sample_events", "recent_events", "sample_ledger"):
        for item in list(result.get(key) or []):
            if not isinstance(item, dict):
                continue
            ts = _coerce_utc_datetime(item.get("ts") or item.get("entry_ts") or item.get("exit_ts"))
            if ts is None:
                continue
            action = str(item.get("action") or item.get("kind") or "")
            side = str(item.get("side") or item.get("direction") or "")
            price = str(item.get("price") or item.get("entry") or item.get("exit") or "")
            identity = (ts.isoformat(), action, side, price)
            if identity in seen:
                continue
            seen.add(identity)
            copied = dict(item)
            copied["ts"] = ts.isoformat()
            events.append(copied)
    events.sort(key=lambda item: str(item.get("ts") or ""))
    return events


def _historical_lifecycle_candidate_from_result(
    *,
    name: str,
    result: dict[str, Any],
    source_window: dict[str, Any],
    generated_at: datetime,
    min_shadow_fill_samples: int,
) -> dict[str, Any] | None:
    summary = dict(result.get("summary") or {})
    if not summary and any(key in result for key in ("trade_like_events", "open_actions", "close_actions", "signals")):
        summary = result
    events = _historical_lifecycle_events_from_result(result)
    event_rows = [event for event in events if _coerce_utc_datetime(event.get("ts")) and _coerce_utc_datetime(event.get("ts")) <= generated_at]
    closed = int(summary.get("closed") or summary.get("trade_like_events") or result.get("trade_like_events") or 0)
    close_actions = int(summary.get("close_actions") or result.get("close_actions") or 0)
    open_actions = int(summary.get("open_actions") or result.get("open_actions") or 0)
    event_like_count = max(len(event_rows), close_actions, closed)
    if event_like_count <= 0:
        return None
    by_year = dict(summary.get("by_year_return_pct") or result.get("by_year_return_pct") or {})
    direction_counts = dict(summary.get("direction_counts") or result.get("direction_counts") or {})
    long_count = int(direction_counts.get("long") or 0)
    short_count = int(direction_counts.get("short") or 0)
    data_end = _coerce_utc_datetime(source_window.get("last_utc"))
    source_ends_before_generated_at = data_end is None or data_end <= generated_at
    sample_passed = event_like_count >= max(1, int(min_shadow_fill_samples or 1))
    long_short_balanced = (long_count > 0 and short_count > 0) if direction_counts else None
    positive_year_count = sum(1 for value in by_year.values() if _num(value, 0.0) and float(value) > 0.0)
    year_count = len(by_year)
    positive_year_fraction = round(positive_year_count / year_count, 4) if year_count else None
    total_return_pct = _num(
        summary.get("total_return_pct_1x")
        or summary.get("total_return_pct")
        or result.get("total_return_pct"),
        None,
    )
    max_drawdown_pct = _num(
        summary.get("max_drawdown_pct_1x")
        or summary.get("max_drawdown_pct")
        or result.get("max_drawdown_pct")
        or result.get("gross_max_drawdown_pct_before_costs"),
        None,
    )
    return_to_dd = _num(summary.get("return_to_dd") or result.get("return_to_dd"), None)
    if return_to_dd is None and total_return_pct is not None and max_drawdown_pct and max_drawdown_pct > 0.0:
        return_to_dd = round(total_return_pct / max_drawdown_pct, 6)
    warnings: list[str] = []
    if not event_rows and closed > 0:
        warnings.append("summary_only_lifecycle_count_without_full_event_timestamps")
    if year_count and positive_year_fraction is not None and positive_year_fraction < 0.5:
        warnings.append("less_than_half_of_years_positive")
    if long_short_balanced is False:
        warnings.append("one_sided_historical_lifecycle_sample")
    if not source_ends_before_generated_at:
        warnings.append("source_data_extends_beyond_generated_at")
    if total_return_pct is not None and total_return_pct <= 0.0:
        warnings.append("non_positive_historical_lifecycle_return")
    if max_drawdown_pct is not None and max_drawdown_pct >= 80.0:
        warnings.append("catastrophic_historical_lifecycle_drawdown")
    quality_passed = (
        (total_return_pct is None or total_return_pct > 0.0)
        and (max_drawdown_pct is None or max_drawdown_pct < 80.0)
        and (positive_year_fraction is None or positive_year_fraction >= 0.5)
        and (long_short_balanced is not False)
    )
    status = (
        "passed"
        if sample_passed and source_ends_before_generated_at and quality_passed
        else "partial"
    )
    return {
        "name": name,
        "status": status,
        "proxy_lifecycle_rows": event_like_count,
        "required_shadow_fill_samples": max(1, int(min_shadow_fill_samples or 1)),
        "paper_shadow_fill_samples_passed": sample_passed and source_ends_before_generated_at and quality_passed,
        "sample_count_passed": sample_passed,
        "quality_passed": quality_passed,
        "closed_trades": closed,
        "open_actions": open_actions,
        "close_actions": close_actions,
        "timestamped_event_rows": len(event_rows),
        "source_window": source_window,
        "source_ends_before_generated_at": source_ends_before_generated_at,
        "direction_counts": direction_counts,
        "long_short_balanced": long_short_balanced,
        "by_year_return_pct": by_year,
        "positive_year_count": positive_year_count if year_count else None,
        "year_count": year_count if year_count else None,
        "positive_year_fraction": positive_year_fraction,
        "total_return_pct": total_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "return_to_dd": return_to_dd,
        "trades_per_year": summary.get("trades_per_year"),
        "event_preview": event_rows[:5],
        "warnings": warnings,
        "no_live_order_sent": True,
    }


def _historical_lifecycle_replay(
    *,
    source_path: Path,
    generated_at: datetime,
    min_shadow_fill_samples: int,
) -> dict[str, Any]:
    resolved = _resolve(source_path)
    if not resolved.exists():
        return {
            "status": "source_missing",
            "source_path": _display_path(resolved),
            "paper_shadow_fill_samples_passed": False,
            "no_live_order_sent": True,
        }
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "source_unreadable",
            "source_path": _display_path(resolved),
            "error": str(exc),
            "paper_shadow_fill_samples_passed": False,
            "no_live_order_sent": True,
        }
    if not isinstance(payload, dict):
        return {
            "status": "source_not_object",
            "source_path": _display_path(resolved),
            "paper_shadow_fill_samples_passed": False,
            "no_live_order_sent": True,
        }
    generated_at = generated_at.astimezone(UTC)
    source_window = _historical_source_data_window(payload)
    raw_candidates: list[tuple[str, dict[str, Any]]] = []
    for key in ("top", "top_results", "all_results"):
        values = payload.get(key)
        if isinstance(values, list):
            for idx, item in enumerate(values[:10]):
                if isinstance(item, dict):
                    raw_candidates.append((f"{key}[{idx}]", item))
    for key in ("best_by_method_score", "best_by_raw_return"):
        item = payload.get(key)
        if isinstance(item, dict):
            raw_candidates.append((key, item))
    candidates: list[dict[str, Any]] = []
    for name, item in raw_candidates:
        candidate = _historical_lifecycle_candidate_from_result(
            name=name,
            result=item,
            source_window=source_window,
            generated_at=generated_at,
            min_shadow_fill_samples=min_shadow_fill_samples,
        )
        if candidate is not None:
            candidates.append(candidate)
    if not candidates:
        return {
            "status": "no_lifecycle_candidates",
            "source_path": _display_path(resolved),
            "source_window": source_window,
            "paper_shadow_fill_samples_passed": False,
            "no_live_order_sent": True,
        }
    candidates.sort(
        key=lambda item: (
            1 if item.get("paper_shadow_fill_samples_passed") is True else 0,
            float(item.get("return_to_dd") or -999999.0),
            float(item.get("positive_year_fraction") or -1.0),
            float(item.get("total_return_pct") or -999999.0),
            -float(item.get("max_drawdown_pct") or 999999.0),
            int(item.get("proxy_lifecycle_rows") or 0),
        ),
        reverse=True,
    )
    best = candidates[0]
    status = "passed" if best.get("paper_shadow_fill_samples_passed") is True else "partial"
    return {
        "status": status,
        "source_path": _display_path(resolved),
        "generated_at_utc": generated_at.isoformat(),
        "selected_candidate": best,
        "candidate_count": len(candidates),
        "candidate_preview": candidates[:5],
        "proxy_lifecycle_rows": best.get("proxy_lifecycle_rows"),
        "required_shadow_fill_samples": max(1, int(min_shadow_fill_samples or 1)),
        "paper_shadow_fill_samples_passed": best.get("paper_shadow_fill_samples_passed") is True,
        "future_leakage_guard": {
            "status": "passed" if best.get("source_ends_before_generated_at") is True else "source_window_review_required",
            "generated_at_utc": generated_at.isoformat(),
            "source_last_utc": dict(best.get("source_window") or {}).get("last_utc"),
            "policy": "summary_or_events_are_only_accepted_when_source_data_window_ends_on_or_before_generated_at",
        },
        "proxy_limitations": [
            "historical_closed_trades_can_replace_research_lifecycle_sample_count_but_not_current_paper_db_rows",
            "live_or_paper_promotion_still_requires_a_current_fresh_signal_and_real_execution_microstructure_evidence",
        ],
        "no_live_order_sent": True,
    }


def _historical_gate_substitution(
    *,
    collection_progress: dict[str, Any],
    readiness_progress: dict[str, Any],
    historical_replay: dict[str, Any],
    historical_lifecycle_replay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not historical_replay or historical_replay.get("status") in {None, "source_missing", "source_unreadable"}:
        return {
            "status": "historical_replay_unavailable",
            "realtime_quote_wait_replaced": False,
            "time_substitution_policy": {
                "status": "historical_replay_unavailable",
                "research_shadow_quote_calendar_wait": {
                    "substitutable": True,
                    "substituted": False,
                    "days_removed": 0,
                    "scope": "research_shadow_readiness_only",
                },
                "live_launch_current_evidence_wait": {
                    "substitutable": False,
                    "substituted": False,
                    "scope": "live_or_unrestricted_canary",
                },
                "non_substitutable_live_gates": [
                    "fresh_signal_requires_realtime_strategy_event",
                    "paper_shadow_fill_samples_require_current_trade_lifecycle_rows",
                    "current_exchange_microstructure_requires_quote_or_paper_fill_evidence",
                ],
            },
            "no_live_order_sent": True,
        }
    aggregate = dict(historical_replay.get("aggregate_quote_gate") or {})
    rolling = dict(historical_replay.get("rolling_window_confirmation") or {})
    rolling_confirmed = rolling.get("status") == "passed"
    aggregate_quote_samples_passed = aggregate.get("quote_samples_passed") is True
    aggregate_quote_calendar_days_passed = aggregate.get("quote_calendar_days_passed") is True
    aggregate_quote_distinct_hours_passed = aggregate.get("quote_distinct_hours_passed") is True
    quote_samples_replaced = aggregate_quote_samples_passed and rolling_confirmed
    quote_calendar_days_replaced = aggregate_quote_calendar_days_passed and rolling_confirmed
    quote_distinct_hours_replaced = aggregate_quote_distinct_hours_passed and rolling_confirmed
    realtime_quote_wait_replaced = (
        quote_samples_replaced and quote_calendar_days_replaced and quote_distinct_hours_replaced and rolling_confirmed
    )
    remaining = dict(readiness_progress.get("remaining_work_units") or {})
    substituted_remaining = dict(remaining)
    replacement_map = {
        "quote_samples": quote_samples_replaced,
        "quote_calendar_days": quote_calendar_days_replaced,
        "quote_distinct_hours": quote_distinct_hours_replaced,
    }
    for gate, replaced in replacement_map.items():
        if replaced:
            substituted_remaining[gate] = 0
    lifecycle = dict(historical_lifecycle_replay or {})
    lifecycle_proxy_replaced = lifecycle.get("paper_shadow_fill_samples_passed") is True
    if lifecycle_proxy_replaced:
        substituted_remaining["paper_shadow_fill_samples"] = 0
    substituted_blockers: list[dict[str, Any]] = []
    for gate in list(readiness_progress.get("blocking_gates_ordered") or []):
        gate_name = str(dict(gate).get("gate") or "")
        if replacement_map.get(gate_name) is True or (gate_name == "paper_shadow_fill_samples" and lifecycle_proxy_replaced):
            continue
        substituted_blockers.append(dict(gate))
    quote_sample_pct = max(
        float(readiness_progress.get("quote_sample_pct") or 0.0),
        float(aggregate.get("quote_sample_pct") or 0.0),
    )
    quote_calendar_pct = max(
        float(readiness_progress.get("quote_calendar_day_pct") or 0.0),
        float(aggregate.get("quote_calendar_day_pct") or 0.0),
    )
    quote_hour_pct = max(
        float(readiness_progress.get("quote_distinct_hour_pct") or 0.0),
        float(aggregate.get("quote_distinct_hour_pct") or 0.0),
    )
    quote_evidence_pct = min(quote_sample_pct, quote_calendar_pct, quote_hour_pct)
    paper_lifecycle_pct = (
        100.0
        if lifecycle_proxy_replaced
        else float(readiness_progress.get("paper_shadow_fill_pct") or 0.0)
    )
    if realtime_quote_wait_replaced:
        status = "quote_wait_replaced_by_historical_walk_forward_proxy"
    elif any(replacement_map.values()):
        status = "partial_quote_wait_replacement"
    else:
        status = "historical_replay_did_not_replace_quote_wait"
    realtime_wait_days_removed = (
        int(collection_progress.get("quote_missing_calendar_days") or 0) if quote_calendar_days_replaced else 0
    )
    time_substitution_policy = {
        "status": status,
        "research_shadow_quote_calendar_wait": {
            "substitutable": True,
            "substituted": quote_calendar_days_replaced,
            "days_removed": realtime_wait_days_removed,
            "scope": "research_shadow_readiness_only",
            "source": "historical_replay_with_future_leakage_guard_and_rolling_window_confirmation",
            "reason": (
                "Historical replay passed aggregate quote-calendar and rolling confirmation gates."
                if quote_calendar_days_replaced
                else "Historical replay did not pass enough quote-calendar and rolling confirmation gates."
            ),
        },
        "research_shadow_quote_sample_hour_wait": {
            "substitutable": True,
            "substituted": quote_samples_replaced and quote_distinct_hours_replaced,
            "sample_gate_substituted": quote_samples_replaced,
            "distinct_hour_gate_substituted": quote_distinct_hours_replaced,
            "scope": "research_shadow_readiness_only",
        },
        "research_shadow_lifecycle_proxy_wait": {
            "substitutable": True,
            "substituted": lifecycle_proxy_replaced,
            "scope": "research_shadow_readiness_only",
            "reason": (
                "Historical closed-trade lifecycle proxy satisfied the research sample count."
                if lifecycle_proxy_replaced
                else "Current paper lifecycle rows are still required unless a valid historical lifecycle proxy is supplied."
            ),
        },
        "live_launch_current_evidence_wait": {
            "substitutable": False,
            "substituted": False,
            "scope": "live_or_unrestricted_canary",
            "reason": (
                "Live launch still requires current fresh signal, paper/apply rows, and current exchange "
                "microstructure evidence; historical replay only removes research wait time."
            ),
        },
        "can_skip_research_quote_calendar_wait": quote_calendar_days_replaced,
        "can_skip_live_current_evidence_wait": False,
        "non_substitutable_live_gates": [
            "fresh_signal_requires_realtime_strategy_event",
            "paper_shadow_fill_samples_require_current_trade_lifecycle_rows",
            "market_data_freshness_requires_current_exchange_cache_when_stale",
            "real_order_book_spread_slippage_latency_require_l2_quote_shadow_or_paper_fill_evidence",
        ],
    }
    return {
        "status": status,
        "realtime_quote_wait_replaced": realtime_quote_wait_replaced,
        "rolling_window_confirmed": rolling_confirmed,
        "aggregate_quote_gate_passed": {
            "quote_samples": aggregate_quote_samples_passed,
            "quote_calendar_days": aggregate_quote_calendar_days_passed,
            "quote_distinct_hours": aggregate_quote_distinct_hours_passed,
        },
        "quote_gate_replacements": {
            "quote_samples": quote_samples_replaced,
            "quote_calendar_days": quote_calendar_days_replaced,
            "quote_distinct_hours": quote_distinct_hours_replaced,
        },
        "paper_shadow_fill_proxy_replaced": lifecycle_proxy_replaced,
        "realtime_wait_days_removed": realtime_wait_days_removed,
        "remaining_work_units_after_substitution": substituted_remaining,
        "blocking_gates_after_substitution": substituted_blockers,
        "strictest_deployment_gate_after_substitution": (
            substituted_blockers[0]["gate"] if substituted_blockers else "none"
        ),
        "quote_evidence_readiness_pct_after_substitution": quote_evidence_pct,
        "paper_lifecycle_readiness_pct_after_historical_substitution": paper_lifecycle_pct,
        "research_shadow_promotion_readiness_pct_after_substitution": min(quote_evidence_pct, paper_lifecycle_pct),
        "shadow_promotion_readiness_pct_after_substitution": min(quote_evidence_pct, paper_lifecycle_pct),
        "next_actions_after_substitution": [
            "treat_quote_calendar_hour_sample_wait_as_replayed_for_research_gate"
            if realtime_quote_wait_replaced
            else "inspect_historical_replay_failures_before_replacing_quote_wait",
            (
                "focus_remaining_work_on_current_fresh_signal_and_live_microstructure_evidence"
                if lifecycle_proxy_replaced
                else "focus_remaining_work_on_fresh_signal_and_paper_lifecycle_evidence"
            ),
            "do_not_promote_live_orders_without_real_microstructure_or_paper_fill_evidence",
        ],
        "time_substitution_policy": time_substitution_policy,
        "non_replaced_live_gates": [
            "fresh_signal_requires_realtime_strategy_event",
            "paper_shadow_fill_samples_require_trade_lifecycle_rows",
            "market_data_freshness_requires_current_exchange_cache_when_stale",
            "real_order_book_spread_slippage_latency_require_l2_quote_shadow_or_paper_fill_evidence",
        ],
        "no_live_order_sent": True,
    }


def _launch_gate_item(
    *,
    gate: str,
    passed: bool,
    blocker: str | None = None,
    detail: dict[str, Any] | None = None,
    next_action: str | None = None,
) -> dict[str, Any]:
    return {
        "gate": gate,
        "status": "passed" if passed else "blocking",
        "passed": bool(passed),
        "blocker": blocker,
        "detail": dict(detail or {}),
        "next_action": next_action,
    }


def _launch_resolution_matrix(
    *,
    stage_gates: list[dict[str, Any]],
    substitution_matrix: dict[str, Any],
    component_readiness: dict[str, Any],
    apply_gate: dict[str, Any],
    shadow_runtime_required_hours: float,
    shadow_runtime_observed_hours: float,
) -> dict[str, Any]:
    substitution_by_gate = {
        "research_historical_quote_replay": "quote_calendar_and_hour_wait",
        "research_historical_lifecycle_proxy": "paper_shadow_fill_samples",
        "real_paper_lifecycle_rows": "paper_shadow_fill_samples",
        "real_microstructure_execution_evidence": "microstructure_time_coverage",
        "current_fresh_signal": "current_fresh_signal",
        "shadow_runtime_24h_observed": "shadow_runtime_24h_observed",
    }
    resolution_type_by_gate = {
        "research_historical_quote_replay": "historical_walk_forward_replay",
        "research_historical_lifecycle_proxy": "historical_lifecycle_replay",
        "current_market_data_fresh": "runtime_market_data_refresh",
        "current_fresh_signal": "wait_for_realtime_strategy_event",
        "real_paper_lifecycle_rows": "paper_bridge_apply_after_fresh_signal",
        "real_microstructure_execution_evidence": "real_l2_quote_shadow_collection",
        "shadow_runtime_24h_observed": "continuous_no_live_runtime_observation",
        "tiny_canary_risk_caps_configured": "operator_defined_tiny_canary_caps",
        "order_safety_controls_verified": "manual_order_safety_drills",
    }
    can_resolve_without_live_order_by_gate = {
        "research_historical_quote_replay": True,
        "research_historical_lifecycle_proxy": True,
        "current_market_data_fresh": True,
        "current_fresh_signal": False,
        "real_paper_lifecycle_rows": apply_gate.get("can_request_paper_apply_now") is True,
        "real_microstructure_execution_evidence": False,
        "shadow_runtime_24h_observed": False,
        "tiny_canary_risk_caps_configured": False,
        "order_safety_controls_verified": False,
    }
    can_progress_without_live_order_by_gate = {
        "research_historical_quote_replay": True,
        "research_historical_lifecycle_proxy": True,
        "current_market_data_fresh": True,
        "current_fresh_signal": True,
        "real_paper_lifecycle_rows": apply_gate.get("can_request_paper_apply_now") is True,
        "real_microstructure_execution_evidence": True,
        "shadow_runtime_24h_observed": True,
        "tiny_canary_risk_caps_configured": False,
        "order_safety_controls_verified": False,
    }
    operator_review_required_by_gate = {
        "real_paper_lifecycle_rows",
        "tiny_canary_risk_caps_configured",
        "order_safety_controls_verified",
    }
    realtime_required_gates = {
        "current_market_data_fresh",
        "current_fresh_signal",
        "real_paper_lifecycle_rows",
        "real_microstructure_execution_evidence",
        "shadow_runtime_24h_observed",
    }
    rows: list[dict[str, Any]] = []
    for gate in stage_gates:
        gate_name = str(gate.get("gate") or "")
        substitution_key = substitution_by_gate.get(gate_name)
        substitution = dict(substitution_matrix.get(substitution_key) or {}) if substitution_key else {}
        substitution_allowed = substitution.get("substitution_allowed") is True
        substituted = substitution.get("substituted") is True
        passed = gate.get("passed") is True
        is_realtime_gate = gate_name in realtime_required_gates
        row = {
            "gate": gate_name,
            "passed": passed,
            "blocker": gate.get("blocker"),
            "resolution_type": resolution_type_by_gate.get(gate_name, "review_gate"),
            "can_backtest_or_replay_substitute": substitution_allowed,
            "substituted_for_research": substituted,
            "substitution_scope": substitution.get("scope"),
            "remaining_real_requirement": substitution.get("remaining_real_requirement"),
            "requires_realtime_evidence_for_launch": is_realtime_gate,
            "can_resolve_without_live_order_now": (
                can_resolve_without_live_order_by_gate.get(gate_name) is True and not passed
            ),
            "can_progress_without_live_order": (
                can_progress_without_live_order_by_gate.get(gate_name) is True and not passed
            ),
            "requires_operator_review": gate_name in operator_review_required_by_gate,
            "next_action": gate.get("next_action"),
            "no_live_order_sent": True,
        }
        if passed:
            row["state"] = "resolved"
        elif substitution_allowed and substituted and is_realtime_gate:
            row["state"] = "research_proxy_resolved_launch_real_evidence_remaining"
        elif substitution_allowed and substituted:
            row["state"] = "resolved_by_research_proxy"
        elif substitution_allowed:
            row["state"] = "substitution_available_but_not_complete"
        else:
            row["state"] = "real_world_gate_remaining"
        rows.append(row)

    blocking_rows = [row for row in rows if row["passed"] is not True]
    unresolved_backtest_substitutable = [
        row["gate"]
        for row in blocking_rows
        if row["can_backtest_or_replay_substitute"] is True and row["substituted_for_research"] is not True
    ]
    research_proxy_resolved = [
        row["gate"]
        for row in rows
        if row["substituted_for_research"] is True
    ]
    non_substitutable_remaining = [
        row["gate"]
        for row in blocking_rows
        if row["can_backtest_or_replay_substitute"] is not True
        or row["requires_realtime_evidence_for_launch"] is True
    ]
    no_live_actionable = [
        row["gate"]
        for row in blocking_rows
        if row["can_resolve_without_live_order_now"] is True
    ]
    no_live_progressable = [
        row["gate"]
        for row in blocking_rows
        if row["can_progress_without_live_order"] is True
    ]
    runtime_remaining_hours = round(max(float(shadow_runtime_required_hours or 0.0) - float(shadow_runtime_observed_hours or 0.0), 0.0), 4)
    return {
        "status": (
            "substitution_exhausted_realtime_gates_remaining"
            if not unresolved_backtest_substitutable and non_substitutable_remaining
            else "all_launch_gates_resolved"
            if not blocking_rows
            else "substitution_or_operator_work_remaining"
        ),
        "backtest_substitution_exhausted": not unresolved_backtest_substitutable,
        "unresolved_backtest_substitutable_gates": unresolved_backtest_substitutable,
        "research_proxy_resolved_gates": research_proxy_resolved,
        "non_substitutable_remaining_gates": non_substitutable_remaining,
        "no_live_actionable_remaining_gates": no_live_actionable,
        "no_live_progressable_remaining_gates": no_live_progressable,
        "operator_review_remaining_gates": [
            row["gate"]
            for row in blocking_rows
            if row["requires_operator_review"] is True
        ],
        "fresh_signal_available": component_readiness.get("current_fresh_signal") is True,
        "paper_apply_available": apply_gate.get("can_request_paper_apply_now") is True,
        "runtime_remaining_hours": runtime_remaining_hours,
        "rows": rows,
        "policy": "historical_replay_can_close_research_waits_but_not_current_signal_real_paper_rows_or_runtime_observation",
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _launch_readiness_state_machine(
    *,
    report: dict[str, Any],
    generated_at: datetime,
    canary_max_notional_usdt: float = 0.0,
    canary_max_leverage: float = 10.0,
    canary_max_daily_loss_usdt: float = 0.0,
    require_real_paper_rows_for_canary: bool = True,
    shadow_runtime_observed_hours: float = 0.0,
    shadow_runtime_required_hours: float = 24.0,
) -> dict[str, Any]:
    progress = dict(report.get("collection_progress") or {})
    readiness = dict(report.get("readiness_progress") or {})
    remaining = dict(readiness.get("remaining_work_units") or {})
    substitution = dict(report.get("historical_gate_substitution") or {})
    substituted_remaining = dict(substitution.get("remaining_work_units_after_substitution") or remaining)
    apply_gate = dict(report.get("paper_bridge_apply_gate") or {})
    pre_apply_backup = dict(report.get("pre_apply_backup_plan") or {})
    signal_wait = dict(report.get("signal_wait_plan") or {})
    market_data_plan = dict(report.get("market_data_refresh_plan") or {})
    lifecycle = dict(report.get("historical_lifecycle_replay") or {})
    risk_caps_config = dict(report.get("canary_risk_caps_config") or {})
    safety_controls = dict(report.get("launch_safety_controls") or {})
    quote_research_ready = (
        int(substituted_remaining.get("quote_samples") or 0) == 0
        and int(substituted_remaining.get("quote_calendar_days") or 0) == 0
        and int(substituted_remaining.get("quote_distinct_hours") or 0) == 0
    )
    lifecycle_research_ready = int(substituted_remaining.get("paper_shadow_fill_samples") or 0) == 0
    research_ready = quote_research_ready and lifecycle_research_ready
    market_data_fresh = apply_gate.get("fresh_market_data") is True
    fresh_signal_ready = apply_gate.get("fresh_signal") is True
    quote_replacements = dict(substitution.get("quote_gate_replacements") or {})
    quote_sample_actual_ready = int(remaining.get("quote_samples") or 0) == 0
    quote_time_actual_ready = (
        int(remaining.get("quote_calendar_days") or 0) == 0
        and int(remaining.get("quote_distinct_hours") or 0) == 0
    )
    quote_time_proxy_ready = (
        quote_replacements.get("quote_calendar_days") is True
        and quote_replacements.get("quote_distinct_hours") is True
    )
    actual_quote_ready = (
        quote_sample_actual_ready
        and quote_time_actual_ready
    )
    actual_paper_rows = int(progress.get("paper_fill_rows") or 0)
    actual_paper_ready = int(remaining.get("paper_shadow_fill_samples") or 0) == 0
    pending_gates = set(str(item) for item in progress.get("pending_gates") or [])
    failed_gates = set(str(item) for item in progress.get("failed_gates") or [])
    quote_blockers = set(str(item) for item in progress.get("quote_blockers") or [])
    microstructure_gate_names = {
        "p95_adverse_slippage_within_limit",
        "max_adverse_slippage_within_limit",
        "p95_spread_within_limit",
        "p95_latency_within_limit",
    }
    quote_metric_blocker_names = {
        "schema_failures",
        "p95_spread_bps_failed",
        "p95_market_slippage_bps_failed",
        "p95_latency_ms_failed",
    }
    legacy_pending_microstructure = sorted(pending_gates & microstructure_gate_names)
    legacy_failed_microstructure = sorted(failed_gates & microstructure_gate_names)
    quote_metric_blockers = sorted(quote_blockers & quote_metric_blocker_names)
    microstructure_metric_ready = quote_sample_actual_ready and not quote_metric_blockers
    microstructure_time_proxy_ready = quote_time_proxy_ready
    microstructure_proxy_ready_for_research = (
        microstructure_metric_ready
        and microstructure_time_proxy_ready
    )
    microstructure_ready = actual_quote_ready and microstructure_metric_ready
    if microstructure_ready:
        microstructure_blocker = None
    elif not quote_sample_actual_ready:
        microstructure_blocker = "real_quote_samples_missing"
    elif quote_metric_blockers:
        microstructure_blocker = "real_spread_slippage_latency_gates_failed"
    elif not quote_time_actual_ready:
        microstructure_blocker = "real_quote_time_coverage_missing"
    else:
        microstructure_blocker = "real_microstructure_execution_evidence_incomplete"
    canary_limits_configured = (
        float(canary_max_notional_usdt or 0.0) > 0.0
        and float(canary_max_daily_loss_usdt or 0.0) > 0.0
        and 0.0 < float(canary_max_leverage or 0.0) <= 10.0
        and risk_caps_config.get("configured") is True
    )
    safety_controls_verified = safety_controls.get("overall_status") == "PASS"
    shadow_runtime_observed_hours = max(0.0, float(shadow_runtime_observed_hours or 0.0))
    shadow_runtime_required_hours = max(0.0, float(shadow_runtime_required_hours or 0.0))
    shadow_runtime_observed = shadow_runtime_observed_hours >= shadow_runtime_required_hours
    paper_ready_for_apply = market_data_fresh and fresh_signal_ready and apply_gate.get("can_request_paper_apply_now") is True
    paper_operational_ready = market_data_fresh and fresh_signal_ready and (paper_ready_for_apply or actual_paper_rows > 0)
    canary_evidence_ready = (
        research_ready
        and fresh_signal_ready
        and microstructure_ready
        and (actual_paper_ready or not require_real_paper_rows_for_canary)
        and shadow_runtime_observed
        and canary_limits_configured
        and safety_controls_verified
    )
    stage_gates = [
        _launch_gate_item(
            gate="research_historical_quote_replay",
            passed=quote_research_ready,
            blocker=None if quote_research_ready else "historical_quote_replay_not_complete",
            detail={
                "quote_realtime_wait_replaced": substitution.get("realtime_quote_wait_replaced"),
                "quote_gate_replacements": substitution.get("quote_gate_replacements"),
            },
            next_action="run_historical_evidence_replay_until_quote_wait_replaced",
        ),
        _launch_gate_item(
            gate="research_historical_lifecycle_proxy",
            passed=lifecycle_research_ready,
            blocker=None if lifecycle_research_ready else "historical_lifecycle_proxy_not_complete",
            detail={
                "paper_shadow_fill_proxy_replaced": substitution.get("paper_shadow_fill_proxy_replaced"),
                "proxy_lifecycle_rows": lifecycle.get("proxy_lifecycle_rows"),
                "selected_candidate": dict(lifecycle.get("selected_candidate") or {}).get("name"),
            },
            next_action="rerun_historical_lifecycle_replay_with_quality_ranked_source",
        ),
        _launch_gate_item(
            gate="current_market_data_fresh",
            passed=market_data_fresh,
            blocker=None if market_data_fresh else "market_data_stale",
            detail={
                "market_data_refresh_status": market_data_plan.get("status"),
                "market_data_age_minutes": market_data_plan.get("market_data_age_minutes"),
            },
            next_action="refresh_market_data_and_rerun_evidence_cycle",
        ),
        _launch_gate_item(
            gate="current_fresh_signal",
            passed=fresh_signal_ready,
            blocker=None if fresh_signal_ready else "fresh_signal_missing_or_stale",
            detail={
                "signal_wait_status": signal_wait.get("status"),
                "signal_age_hours": signal_wait.get("signal_age_hours"),
                "latest_add_age_to_median_gap": signal_wait.get("latest_add_age_to_median_gap"),
                "cadence_lag_level": signal_wait.get("cadence_lag_level"),
            },
            next_action="monitor_fresh_v6_signal_without_forcing_entry",
        ),
        _launch_gate_item(
            gate="real_paper_lifecycle_rows",
            passed=actual_paper_ready,
            blocker=None if actual_paper_ready else "real_paper_lifecycle_rows_missing",
            detail={
                "actual_paper_fill_rows": actual_paper_rows,
                "historical_proxy_passed": substitution.get("paper_shadow_fill_proxy_replaced"),
                "required_real_rows_for_canary": bool(require_real_paper_rows_for_canary),
            },
            next_action="apply_paper_bridge_only_after_fresh_signal_and_verified_backup",
        ),
        _launch_gate_item(
            gate="real_microstructure_execution_evidence",
            passed=microstructure_ready,
            blocker=microstructure_blocker,
            detail={
                "actual_quote_ready": actual_quote_ready,
                "actual_quote_samples_ready": quote_sample_actual_ready,
                "actual_quote_time_coverage_ready": quote_time_actual_ready,
                "historical_quote_time_proxy_ready": microstructure_time_proxy_ready,
                "microstructure_metric_ready": microstructure_metric_ready,
                "microstructure_proxy_ready_for_research": microstructure_proxy_ready_for_research,
                "quote_metric_blockers": quote_metric_blockers,
                "legacy_pending_microstructure_gates": legacy_pending_microstructure,
                "legacy_failed_microstructure_gates": legacy_failed_microstructure,
                "quote_observed": progress.get("quote_observed"),
                "quote_required": progress.get("quote_required"),
                "quote_calendar_days": progress.get("quote_calendar_days"),
                "quote_min_calendar_days": progress.get("quote_min_calendar_days"),
                "quote_distinct_hours": progress.get("quote_distinct_hours"),
                "quote_min_distinct_hours": progress.get("quote_min_distinct_hours"),
                "substitution_scope": (
                    "research_only_actual_launch_gate_still_requires_real_time_coverage"
                    if microstructure_proxy_ready_for_research and not microstructure_ready
                    else "none"
                ),
            },
            next_action="collect_l2_quote_shadow_and_paper_fill_microstructure_until_p95_gates_pass",
        ),
        _launch_gate_item(
            gate="shadow_runtime_24h_observed",
            passed=shadow_runtime_observed,
            blocker=None if shadow_runtime_observed else "shadow_runtime_24h_not_observed",
            detail={
                "required_hours": shadow_runtime_required_hours,
                "observed_hours": round(shadow_runtime_observed_hours, 4),
                "remaining_hours": round(max(shadow_runtime_required_hours - shadow_runtime_observed_hours, 0.0), 4),
                "reason": "calendar_time_cannot_be_replaced_for_process_uptime_restart_and_duplicate_detection",
            },
            next_action="run_shadow_or_paper_daemon_for_24h_without_live_orders",
        ),
        _launch_gate_item(
            gate="tiny_canary_risk_caps_configured",
            passed=canary_limits_configured,
            blocker=None if canary_limits_configured else "canary_notional_daily_loss_or_leverage_caps_missing",
            detail={
                "canary_max_notional_usdt": float(canary_max_notional_usdt or 0.0),
                "canary_max_leverage": float(canary_max_leverage or 0.0),
                "canary_max_daily_loss_usdt": float(canary_max_daily_loss_usdt or 0.0),
                "config_status": risk_caps_config.get("status"),
                "config_source": risk_caps_config.get("source"),
                "config_path": risk_caps_config.get("path"),
                "config_errors": list(risk_caps_config.get("errors") or []),
            },
            next_action="set_explicit_tiny_canary_notional_leverage_and_daily_loss_caps",
        ),
        _launch_gate_item(
            gate="order_safety_controls_verified",
            passed=safety_controls_verified,
            blocker=None if safety_controls_verified else "order_safety_controls_missing_or_incomplete",
            detail={
                "overall_status": safety_controls.get("overall_status"),
                "verified_count": safety_controls.get("verified_count"),
                "required_count": safety_controls.get("required_count"),
                "missing_or_failed": list(safety_controls.get("missing_or_failed") or []),
                "input_evidence": safety_controls.get("input_evidence"),
            },
            next_action="run_manual_safety_drills_and_safety_controls_audit_until_all_required_controls_pass",
        ),
    ]
    blockers = [item for item in stage_gates if item["passed"] is not True]
    if not research_ready:
        current_stage = "research_blocked"
    elif not fresh_signal_ready:
        current_stage = "research_ready_waiting_for_fresh_signal"
    elif not actual_paper_ready:
        current_stage = "fresh_signal_ready_collect_real_paper_lifecycle"
    elif not microstructure_ready:
        current_stage = "paper_lifecycle_ready_collect_microstructure"
    elif not shadow_runtime_observed:
        current_stage = "microstructure_ready_run_24h_shadow"
    elif not canary_limits_configured:
        current_stage = "shadow_ready_waiting_for_canary_risk_caps"
    elif not safety_controls_verified:
        current_stage = "shadow_ready_waiting_for_order_safety_controls"
    elif canary_evidence_ready:
        current_stage = "tiny_canary_review_ready"
    else:
        current_stage = "operator_review_required"
    signal_monitor_command = signal_wait.get("command")
    report_suffix = generated_at.strftime("%Y%m%d_%H%MZ")
    risk_caps_path = str(risk_caps_config.get("path") or "").strip()
    risk_caps_arg = f"--canary-risk-caps-json {shlex.quote(risk_caps_path)} " if risk_caps_path else ""
    backup_dir = str(pre_apply_backup.get("backup_dir") or "").strip()
    backup_arg = f"--pre-apply-backup-dir {shlex.quote(backup_dir)} " if backup_dir else ""
    signal_age_minutes = max(1, int(signal_wait.get("max_signal_age_minutes") or 15))
    signal_age_arg = f"--max-signal-age-minutes {signal_age_minutes} "
    launch_commands = {
        "signal_monitor": signal_monitor_command,
        "paper_bridge_dry_run": (
            ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
            "--quote-samples-per-tick 0 "
            "--refresh-market-data-before-run "
            f"{signal_age_arg}"
            "--historical-evidence-replay --historical-lifecycle-replay "
            f"{risk_caps_arg}"
            f"--report-dir reports/validation/diagnostics/market_state_rotation_v6_launch_paper_dry_run_{report_suffix}"
        ),
        "microstructure_quote_capture": (
            ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
            "--quote-samples-per-tick 2 "
            "--historical-evidence-replay --historical-lifecycle-replay "
            f"{risk_caps_arg}"
            f"--report-dir reports/validation/diagnostics/market_state_rotation_v6_launch_microstructure_{report_suffix}"
        ),
        "paper_apply_only_after_fresh_signal": (
            ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
            "--apply-paper-bridge --quote-samples-per-tick 0 "
            "--refresh-market-data-before-run "
            f"{signal_age_arg}"
            "--historical-evidence-replay --historical-lifecycle-replay "
            f"{risk_caps_arg}"
            f"{backup_arg}"
            f"--report-dir reports/validation/diagnostics/market_state_rotation_v6_launch_paper_apply_{report_suffix}"
        ),
    }
    launch_commands = {key: value for key, value in launch_commands.items() if value}
    component_readiness = {
        "market_data_fresh": market_data_fresh,
        "current_fresh_signal": fresh_signal_ready,
        "quote_research_ready": quote_research_ready,
        "quote_sample_actual_ready": quote_sample_actual_ready,
        "quote_time_actual_ready": quote_time_actual_ready,
        "quote_time_proxy_ready": quote_time_proxy_ready,
        "lifecycle_research_proxy_ready": lifecycle_research_ready,
        "real_paper_lifecycle_ready": actual_paper_ready,
        "microstructure_metric_ready": microstructure_metric_ready,
        "microstructure_time_proxy_ready": microstructure_time_proxy_ready,
        "microstructure_proxy_ready_for_research": microstructure_proxy_ready_for_research,
        "real_microstructure_ready": microstructure_ready,
        "shadow_runtime_observed": shadow_runtime_observed,
        "canary_limits_configured": canary_limits_configured,
        "safety_controls_verified": safety_controls_verified,
    }
    substitution_matrix = {
        "quote_calendar_and_hour_wait": {
            "substitution_allowed": True,
            "substituted": quote_time_proxy_ready,
            "scope": "research_shadow_readiness_only",
            "remaining_real_requirement": None if quote_time_actual_ready else "real_quote_time_coverage_for_launch_evidence",
            "source": "historical_evidence_replay",
            "no_live_order_sent": True,
        },
        "paper_shadow_fill_samples": {
            "substitution_allowed": True,
            "substituted": lifecycle_research_ready,
            "scope": "research_shadow_readiness_only",
            "remaining_real_requirement": None if actual_paper_ready else "real_paper_lifecycle_rows_for_canary",
            "source": "historical_lifecycle_replay",
            "no_live_order_sent": True,
        },
        "microstructure_time_coverage": {
            "substitution_allowed": True,
            "substituted": microstructure_time_proxy_ready,
            "scope": "research_metric_interpretation_only",
            "remaining_real_requirement": None if quote_time_actual_ready else "real_l2_quote_calendar_and_hour_coverage",
            "source": "historical_evidence_replay_plus_current_l2_quote_metrics",
            "no_live_order_sent": True,
        },
        "current_fresh_signal": {
            "substitution_allowed": False,
            "substituted": False,
            "scope": "not_substitutable",
            "remaining_real_requirement": "fresh_realtime_v6_add_or_remove_signal",
            "source": None,
            "no_live_order_sent": True,
        },
        "shadow_runtime_24h_observed": {
            "substitution_allowed": False,
            "substituted": False,
            "scope": "not_substitutable",
            "remaining_real_requirement": "continuous_no_live_runtime_observation",
            "source": None,
            "no_live_order_sent": True,
        },
    }
    resolution_matrix = _launch_resolution_matrix(
        stage_gates=stage_gates,
        substitution_matrix=substitution_matrix,
        component_readiness=component_readiness,
        apply_gate=apply_gate,
        shadow_runtime_required_hours=shadow_runtime_required_hours,
        shadow_runtime_observed_hours=shadow_runtime_observed_hours,
    )
    substituted_time_wait_removed_days = int(substitution.get("realtime_wait_days_removed") or 0)
    effective_research_status = (
        "substitutable_time_gates_replaced_realtime_gates_remaining"
        if research_ready and (not fresh_signal_ready or not shadow_runtime_observed)
        else "research_and_realtime_gates_ready"
        if research_ready
        else "research_substitution_incomplete"
    )
    return {
        "status": current_stage,
        "generated_at": generated_at.isoformat(),
        "research_ready": research_ready,
        "shadow_ready": research_ready and market_data_fresh,
        "paper_operational_ready": paper_operational_ready,
        "tiny_canary_evidence_ready": canary_evidence_ready,
        "tiny_canary_order_submission_allowed": False,
        "live_order_submission_allowed": False,
        "live_block_reason": "evidence_cycle_reports_readiness_only_and_never_submits_live_orders",
        "component_readiness": component_readiness,
        "substitution_matrix": substitution_matrix,
        "resolution_matrix": resolution_matrix,
        "effective_research_status": effective_research_status,
        "substituted_time_wait_removed_days": substituted_time_wait_removed_days,
        "substituted_research_readiness_pct": substitution.get(
            "research_shadow_promotion_readiness_pct_after_substitution",
            100.0 if research_ready else 0.0,
        ),
        "stage_gates": stage_gates,
        "blocking_gate_count": len(blockers),
        "blocking_gates": blockers,
        "next_blocker": blockers[0] if blockers else None,
        "canary_policy": {
            "max_notional_usdt": float(canary_max_notional_usdt or 0.0),
            "max_leverage": float(canary_max_leverage or 0.0),
            "max_daily_loss_usdt": float(canary_max_daily_loss_usdt or 0.0),
            "requires_real_paper_rows": bool(require_real_paper_rows_for_canary),
            "requires_shadow_runtime_hours": shadow_runtime_required_hours,
            "observed_shadow_runtime_hours": round(shadow_runtime_observed_hours, 4),
            "requires_24h_shadow_runtime": shadow_runtime_required_hours >= 24.0,
            "requires_real_microstructure_gates": True,
            "requires_order_safety_controls": True,
            "never_auto_submit_from_evidence_cycle": True,
            "config_status": risk_caps_config.get("status"),
            "config_source": risk_caps_config.get("source"),
            "config_path": risk_caps_config.get("path"),
            "config_errors": list(risk_caps_config.get("errors") or []),
        },
        "next_24h_operator_queue": [
            item["next_action"]
            for item in blockers
            if item.get("next_action")
        ],
        "operator_commands": launch_commands,
        "paper_bridge_handoff": {
            "status": (
                "paper_apply_review_available"
                if paper_ready_for_apply
                else ("blocked_waiting_for_fresh_signal" if not fresh_signal_ready else "blocked_review_paper_bridge_status")
            ),
            "dry_run_command": launch_commands.get("paper_bridge_dry_run"),
            "apply_command": launch_commands.get("paper_apply_only_after_fresh_signal"),
            "apply_allowed_now": bool(paper_ready_for_apply),
            "requires_operator_review": True,
            "requires_verified_pre_apply_backup": True,
            "pre_apply_backup_plan": pre_apply_backup,
            "blocked_by": [
                item["gate"]
                for item in stage_gates
                if item["passed"] is not True and item["gate"] in {"current_fresh_signal", "current_market_data_fresh"}
            ],
            "no_live_order_sent": True,
        },
        "non_negotiables": [
            "do_not_enable_full_live_from_research_proxy",
            "do_not_count_historical_proxy_as_current_fresh_signal",
            "do_not_count_summary_only_lifecycle_as_real_paper_db_rows",
            "do_not_open_tiny_canary_without_explicit_risk_caps_and_24h_shadow_runtime",
            "do_not_open_tiny_canary_without_complete_order_safety_controls",
        ],
        "no_live_order_sent": True,
    }


def _ceil_div(numerator: int, denominator: int) -> int | None:
    if denominator <= 0:
        return None
    return max(0, numerator + denominator - 1) // denominator


def _hour_ints(values: list[Any]) -> list[int]:
    out: list[int] = []
    for value in values:
        text = str(value or "").strip()
        if not text.isdigit():
            continue
        hour = int(text)
        if 0 <= hour <= 23:
            out.append(hour)
    return sorted(set(out))


def _next_quote_evidence_window(
    *,
    generated_at: datetime,
    quote_capture_useful_now: bool,
    missing_utc_hours: list[Any],
    missing_days: int,
    missing_hours: int,
    missing_samples: int,
) -> dict[str, Any]:
    now = generated_at.astimezone(UTC)
    current_hour_end = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    if quote_capture_useful_now:
        valid_until = current_hour_end if missing_hours > 0 else None
        return {
            "status": "now",
            "at_utc": now.isoformat(),
            "at_kst": now.astimezone(KST).isoformat(),
            "valid_until_utc": valid_until.isoformat() if valid_until is not None else None,
            "valid_until_kst": valid_until.astimezone(KST).isoformat() if valid_until is not None else None,
            "valid_duration_minutes": (
                round(max((valid_until - now).total_seconds(), 0.0) / 60.0, 4) if valid_until is not None else None
            ),
            "wait_minutes": 0.0,
            "reason": "current_cycle_advances_quote_evidence",
            "window_kind": "current_missing_utc_hour_bucket" if missing_hours > 0 else "current_quote_sample_window",
            "urgency": "run_now",
            "missed_window_next_step": "rerun_evidence_cycle_to_recompute_next_quote_window",
        }
    next_at: datetime | None = None
    valid_until: datetime | None = None
    window_kind = "none"
    reason = "quote_evidence_gates_already_satisfied"
    if missing_hours > 0:
        start = now.replace(minute=0, second=0, microsecond=0)
        candidates: list[datetime] = []
        for hour in _hour_ints(missing_utc_hours):
            candidate = start.replace(hour=hour)
            if candidate <= now:
                candidate += timedelta(days=1)
            candidates.append(candidate)
        if candidates:
            next_at = min(candidates)
            valid_until = next_at + timedelta(hours=1)
            reason = "wait_for_next_missing_utc_hour_bucket"
            window_kind = "missing_utc_hour_bucket"
    elif missing_days > 0:
        next_at = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        valid_until = next_at + timedelta(days=1)
        reason = "wait_for_next_utc_calendar_day"
        window_kind = "utc_calendar_day"
    elif missing_samples > 0:
        next_at = now
        reason = "quote_sample_count_can_progress_now_when_requested_samples_are_positive"
        window_kind = "quote_sample_count"
    if next_at is None:
        return {
            "status": "no_quote_window_required",
            "at_utc": None,
            "at_kst": None,
            "valid_until_utc": None,
            "valid_until_kst": None,
            "valid_duration_minutes": None,
            "wait_minutes": None,
            "reason": reason,
            "window_kind": window_kind,
            "urgency": "none",
            "missed_window_next_step": None,
        }
    wait_minutes = round(max((next_at - now).total_seconds(), 0.0) / 60.0, 4)
    valid_duration_minutes = (
        round(max((valid_until - next_at).total_seconds(), 0.0) / 60.0, 4) if valid_until is not None else None
    )
    return {
        "status": "wait" if wait_minutes > 0 else "now",
        "at_utc": next_at.isoformat(),
        "at_kst": next_at.astimezone(KST).isoformat(),
        "valid_until_utc": valid_until.isoformat() if valid_until is not None else None,
        "valid_until_kst": valid_until.astimezone(KST).isoformat() if valid_until is not None else None,
        "valid_duration_minutes": valid_duration_minutes,
        "wait_minutes": wait_minutes,
        "reason": reason,
        "window_kind": window_kind,
        "urgency": "run_now" if wait_minutes <= 0 else ("soon" if wait_minutes <= 10.0 else "scheduled"),
        "missed_window_next_step": "rerun_evidence_cycle_to_recompute_next_quote_window",
    }


def _trend_snapshot(report_path: Path, payload: dict[str, Any]) -> dict[str, Any] | None:
    generated_at = _parse_dt(payload.get("generated_at"))
    if generated_at is None:
        return None
    progress = dict(payload.get("collection_progress") or {})
    readiness = dict(payload.get("readiness_progress") or {})
    checklist = dict(payload.get("execution_checklist") or {})
    return {
        "report_path": _display_path(report_path),
        "generated_at": generated_at.isoformat(),
        "quote_observed": int(progress.get("quote_observed") or 0),
        "quote_calendar_days": int(progress.get("quote_calendar_days") or 0),
        "quote_distinct_hours": int(progress.get("quote_distinct_hours") or 0),
        "paper_fill_rows": int(progress.get("paper_fill_rows") or 0),
        "execution_parity_journal_rows": int(progress.get("execution_parity_journal_rows") or 0),
        "execution_parity_missing_samples": int(progress.get("execution_parity_missing_samples") or 0),
        "quote_evidence_readiness_pct": float(readiness.get("quote_evidence_readiness_pct") or 0.0),
        "shadow_promotion_readiness_pct": float(readiness.get("shadow_promotion_readiness_pct") or 0.0),
        "execution_parity_journal_pct": float(readiness.get("execution_parity_journal_pct") or 0.0),
        "current_phase": checklist.get("current_phase"),
    }


def _prior_evidence_snapshots(*, report_dir: Path, current_generated_at: datetime, history_limit: int) -> list[dict[str, Any]]:
    current_report_path = (report_dir / EVIDENCE_REPORT_NAME).resolve()
    snapshots: list[dict[str, Any]] = []
    for path in sorted(report_dir.parent.glob(f"*/{EVIDENCE_REPORT_NAME}")):
        try:
            if path.resolve() == current_report_path:
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        snapshot = _trend_snapshot(path, payload)
        if not snapshot:
            continue
        generated_at = _parse_dt(snapshot.get("generated_at"))
        if generated_at and generated_at <= current_generated_at:
            snapshots.append(snapshot)
    snapshots.sort(key=lambda item: str(item.get("generated_at") or ""))
    return snapshots[-max(1, int(history_limit or 1)) :]


def _readiness_trend(
    *,
    report: dict[str, Any],
    report_dir: Path,
    history_limit: int = 8,
) -> dict[str, Any]:
    current_generated_at = _parse_dt(report.get("generated_at")) or datetime.now(UTC)
    current_snapshot = _trend_snapshot(report_dir / EVIDENCE_REPORT_NAME, report)
    if current_snapshot is None:
        return {
            "status": "current_report_timestamp_unavailable",
            "history_count": 0,
            "no_live_order_sent": True,
        }
    prior = _prior_evidence_snapshots(
        report_dir=report_dir,
        current_generated_at=current_generated_at,
        history_limit=history_limit,
    )
    if not prior:
        return {
            "status": "no_prior_evidence_cycles",
            "history_count": 0,
            "current_snapshot": current_snapshot,
            "no_live_order_sent": True,
            "stagnation_flags": [],
        }
    previous = prior[-1]
    delta = {
        "quote_observed": current_snapshot["quote_observed"] - int(previous.get("quote_observed") or 0),
        "quote_calendar_days": current_snapshot["quote_calendar_days"] - int(previous.get("quote_calendar_days") or 0),
        "quote_distinct_hours": current_snapshot["quote_distinct_hours"] - int(previous.get("quote_distinct_hours") or 0),
        "paper_fill_rows": current_snapshot["paper_fill_rows"] - int(previous.get("paper_fill_rows") or 0),
        "execution_parity_journal_rows": current_snapshot["execution_parity_journal_rows"]
        - int(previous.get("execution_parity_journal_rows") or 0),
        "execution_parity_missing_samples": current_snapshot["execution_parity_missing_samples"]
        - int(previous.get("execution_parity_missing_samples") or 0),
        "quote_evidence_readiness_pct": round(
            current_snapshot["quote_evidence_readiness_pct"] - float(previous.get("quote_evidence_readiness_pct") or 0.0),
            4,
        ),
        "shadow_promotion_readiness_pct": round(
            current_snapshot["shadow_promotion_readiness_pct"]
            - float(previous.get("shadow_promotion_readiness_pct") or 0.0),
            4,
        ),
        "execution_parity_journal_pct": round(
            current_snapshot["execution_parity_journal_pct"]
            - float(previous.get("execution_parity_journal_pct") or 0.0),
            4,
        ),
    }
    elapsed_hours = None
    previous_generated_at = _parse_dt(previous.get("generated_at"))
    if previous_generated_at:
        elapsed_seconds = max((current_generated_at - previous_generated_at).total_seconds(), 0.0)
        elapsed_hours = round(elapsed_seconds / 3600.0, 4)
    remaining = dict(dict(report.get("readiness_progress") or {}).get("remaining_work_units") or {})
    missing_quote_samples = int(remaining.get("quote_samples") or 0)
    missing_calendar_days = int(remaining.get("quote_calendar_days") or 0)
    missing_distinct_hours = int(remaining.get("quote_distinct_hours") or 0)
    missing_paper_fills = int(remaining.get("paper_shadow_fill_samples") or 0)
    missing_execution_parity = int(remaining.get("execution_parity_samples") or 0)
    fresh_signal_missing = int(remaining.get("fresh_signal") or 0)
    stagnation_flags: list[str] = []
    if missing_quote_samples > 0 and delta["quote_observed"] <= 0:
        stagnation_flags.append("quote_samples_no_recent_progress")
    if missing_calendar_days > 0 and delta["quote_calendar_days"] <= 0:
        stagnation_flags.append("quote_calendar_days_waiting_for_new_utc_day")
    if missing_distinct_hours > 0 and delta["quote_distinct_hours"] <= 0:
        stagnation_flags.append("quote_hour_coverage_no_new_bucket")
    if missing_paper_fills > 0 and delta["paper_fill_rows"] <= 0:
        stagnation_flags.append("paper_shadow_fill_no_recent_progress")
    if missing_execution_parity > 0 and delta["execution_parity_journal_rows"] <= 0:
        stagnation_flags.append("execution_parity_journal_no_recent_progress")
    if fresh_signal_missing > 0:
        stagnation_flags.append("fresh_signal_waiting")
    any_progress = any(
        int(delta.get(key) or 0) > 0
        for key in (
            "quote_observed",
            "quote_calendar_days",
            "quote_distinct_hours",
            "paper_fill_rows",
            "execution_parity_journal_rows",
        )
    )
    if any_progress and stagnation_flags:
        status = "progressing_with_unresolved_gates"
    elif any_progress:
        status = "progressing"
    else:
        status = "no_recent_progress"
    cycles_to_quote_sample_completion = _ceil_div(missing_quote_samples, max(delta["quote_observed"], 0))
    cycles_to_paper_fill_completion = _ceil_div(missing_paper_fills, max(delta["paper_fill_rows"], 0))
    cycles_to_execution_parity_completion = _ceil_div(
        missing_execution_parity,
        max(delta["execution_parity_journal_rows"], 0),
    )
    quote_samples_per_hour = None
    if elapsed_hours and elapsed_hours > 0:
        quote_samples_per_hour = round(delta["quote_observed"] / elapsed_hours, 4)
    return {
        "status": status,
        "history_count": len(prior),
        "previous_snapshot": previous,
        "current_snapshot": current_snapshot,
        "latest_delta": delta,
        "elapsed_hours_since_previous": elapsed_hours,
        "quote_samples_per_hour_since_previous": quote_samples_per_hour,
        "cycles_to_quote_sample_completion_at_latest_delta": cycles_to_quote_sample_completion,
        "cycles_to_paper_fill_completion_at_latest_delta": cycles_to_paper_fill_completion,
        "cycles_to_execution_parity_completion_at_latest_delta": cycles_to_execution_parity_completion,
        "calendar_days_still_time_gated": missing_calendar_days,
        "distinct_hours_still_time_gated": missing_distinct_hours,
        "stagnation_flags": stagnation_flags,
        "dominant_unresolved_gate": (dict(report.get("readiness_progress") or {}).get("strictest_deployment_gate")),
        "no_live_order_sent": True,
    }


def _adaptive_collection_plan(
    *,
    generated_at: datetime,
    collection_progress: dict[str, Any],
    collection_forecast: dict[str, Any],
    readiness_progress: dict[str, Any],
    readiness_trend: dict[str, Any],
    apply_gate: dict[str, Any],
    pre_apply_backup_plan: dict[str, Any],
    quote_cadence_preflight: dict[str, Any],
    report_dir: Path,
) -> dict[str, Any]:
    remaining = dict(readiness_progress.get("remaining_work_units") or {})
    missing_days = int(remaining.get("quote_calendar_days") or 0)
    missing_hours = int(remaining.get("quote_distinct_hours") or 0)
    missing_samples = int(remaining.get("quote_samples") or 0)
    missing_paper_fills = int(remaining.get("paper_shadow_fill_samples") or 0)
    fresh_signal_missing = int(remaining.get("fresh_signal") or 0)
    missing_utc_hours = list(collection_forecast.get("utc_hour_of_day_missing") or [])
    covered_utc_hours = list(collection_forecast.get("utc_hour_of_day_covered") or [])
    recommended_utc_hours = list(collection_forecast.get("recommended_utc_collection_hours") or [])
    recommended_kst_hours = list(collection_forecast.get("recommended_kst_collection_hours") or [])
    requested_quote_samples_per_tick = int(quote_cadence_preflight.get("requested_quote_samples_per_tick") or 0)
    effective_quote_samples_per_tick = int(quote_cadence_preflight.get("effective_quote_samples_per_tick") or 0)
    planned_quote_rows_on_target_hour = requested_quote_samples_per_tick * 2
    minimum_samples_per_day = int(collection_forecast.get("recommended_min_quote_samples_per_remaining_day") or 0)
    minimum_cycles_on_target_hours = _ceil_div(minimum_samples_per_day, planned_quote_rows_on_target_hour)
    same_hour_repeat_allowed = missing_hours <= 0
    if fresh_signal_missing > 0:
        primary_objective = "wait_for_fresh_v6_signal_while_collecting_time_diversified_quote_shadow"
    elif apply_gate.get("can_request_paper_apply_now") is True:
        primary_objective = "operator_review_then_apply_paper_bridge"
    elif missing_days > 0 or missing_hours > 0:
        primary_objective = "time_diversified_quote_shadow_collection"
    elif missing_samples > 0:
        primary_objective = "quote_sample_count_collection"
    elif missing_paper_fills > 0:
        primary_objective = "paper_shadow_fill_collection"
    else:
        primary_objective = "review_shadow_promotion_gate"
    blockers_to_action: list[str] = []
    stagnation_flags = set(str(item) for item in readiness_trend.get("stagnation_flags") or [])
    if "quote_hour_coverage_no_new_bucket" in stagnation_flags and missing_hours > 0:
        blockers_to_action.append("same_utc_hour_repeats_are_not_advancing_hour_coverage")
    if "quote_calendar_days_waiting_for_new_utc_day" in stagnation_flags and missing_days > 0:
        blockers_to_action.append("quote_calendar_gate_requires_new_utc_dates")
    if "paper_shadow_fill_no_recent_progress" in stagnation_flags and missing_paper_fills > 0:
        blockers_to_action.append("paper_fill_requires_fresh_signal_and_paper_lifecycle_rows")
    if "fresh_signal_waiting" in stagnation_flags:
        blockers_to_action.append("fresh_signal_is_not_operator_forced")
    quote_capture_useful_now = effective_quote_samples_per_tick > 0
    useful_now = quote_capture_useful_now or apply_gate.get("can_request_paper_apply_now") is True
    backup_dir = str(dict(pre_apply_backup_plan or {}).get("backup_dir") or "").strip()
    backup_arg = f"--pre-apply-backup-dir {shlex.quote(backup_dir)} " if backup_dir else ""
    if missing_days > 0 and not missing_utc_hours and missing_samples <= 0:
        useful_now = False
    next_quote_window = _next_quote_evidence_window(
        generated_at=generated_at,
        quote_capture_useful_now=quote_capture_useful_now,
        missing_utc_hours=missing_utc_hours,
        missing_days=missing_days,
        missing_hours=missing_hours,
        missing_samples=missing_samples,
    )
    return {
        "status": "active_collection_plan",
        "primary_objective": primary_objective,
        "useful_to_run_now": useful_now,
        "advances_quote_evidence_now": quote_capture_useful_now,
        "bridge_audit_refresh_useful_now": True,
        "quote_cadence_decision": quote_cadence_preflight.get("decision"),
        "requested_quote_samples_per_tick": requested_quote_samples_per_tick,
        "effective_quote_samples_per_tick": effective_quote_samples_per_tick,
        "next_quote_evidence_window": next_quote_window,
        "same_utc_hour_repeat_policy": {
            "allowed": same_hour_repeat_allowed,
            "reason": (
                "hour_coverage_gate_already_satisfied"
                if same_hour_repeat_allowed
                else "missing_utc_hour_buckets_must_be_collected_before_same_hour_repeats_help_promotion"
            ),
        },
        "next_target": {
            "utc_hour_of_day": collection_forecast.get("target_next_utc_hour_of_day"),
            "kst_hour_of_day": collection_forecast.get("target_next_kst_hour_of_day"),
            "reason": "first_missing_utc_hour_bucket_after_current_time" if missing_hours > 0 else "sample_count_or_paper_fill",
        },
        "daily_targets": {
            "minimum_quote_samples": collection_forecast.get("recommended_min_quote_samples_per_remaining_day"),
            "minimum_evidence_cycles": collection_forecast.get("recommended_min_evidence_cycles_per_remaining_day"),
            "minimum_evidence_cycles_on_target_hours": minimum_cycles_on_target_hours,
            "planned_quote_rows_per_target_hour_cycle": planned_quote_rows_on_target_hour,
            "minimum_new_utc_hour_buckets": collection_forecast.get(
                "recommended_min_distinct_utc_hours_per_remaining_day"
            ),
            "recommended_utc_collection_hours": recommended_utc_hours,
            "recommended_kst_collection_hours": recommended_kst_hours,
        },
        "coverage_directive": {
            "covered_utc_hours": covered_utc_hours,
            "missing_utc_hours": missing_utc_hours,
            "avoid_repeating_covered_hours_until_hour_gate_passes": missing_hours > 0,
        },
        "blockers_to_action": blockers_to_action,
        "operator_commands": {
            "next_evidence_cycle": (
                ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                "--quote-samples-per-tick 2 "
                "--report-dir reports/validation/diagnostics/<new_report_dir>"
            ),
            "paper_apply_only_if_gate_allows": (
                ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                "--apply-paper-bridge --quote-samples-per-tick 2 "
                "--refresh-market-data-before-run "
                "--max-signal-age-minutes 15 "
                f"{backup_arg}"
                "--report-dir reports/validation/diagnostics/<paper_apply_report_dir>"
            ),
        },
        "non_negotiables": [
            "do_not_repeat_only_the_same_utc_hour_when_quote_distinct_hour_gate_is_missing",
            "do_not_apply_paper_bridge_until_fresh_signal_gate_is_open",
            "do_not_enable_live_orders_from_collection_plan",
        ],
    }


def _quote_collection_forecast(*, progress: dict[str, Any], generated_at: datetime) -> dict[str, Any]:
    missing_samples = int(progress.get("quote_missing_samples") or 0)
    missing_days = int(progress.get("quote_missing_calendar_days") or 0)
    missing_hours = int(progress.get("quote_missing_distinct_hours") or 0)
    captured_this_cycle = int(progress.get("captured_quote_rows_this_cycle") or 0)
    remaining_days_for_sample_plan = max(missing_days, 1)
    recommended_samples_per_day = (
        (missing_samples + remaining_days_for_sample_plan - 1) // remaining_days_for_sample_plan
        if missing_samples > 0
        else 0
    )
    recommended_cycles_per_day = (
        (recommended_samples_per_day + captured_this_cycle - 1) // captured_this_cycle
        if recommended_samples_per_day > 0 and captured_this_cycle > 0
        else None
    )
    recommended_distinct_hours_per_day = (
        (missing_hours + remaining_days_for_sample_plan - 1) // remaining_days_for_sample_plan
        if missing_hours > 0
        else 0
    )
    coverage = dict(progress.get("quote_coverage") or {})
    missing_hour_buckets = list(coverage.get("utc_hour_of_day_missing") or [])
    current_hour = int(generated_at.astimezone(UTC).hour)
    missing_ints = sorted(
        int(item)
        for item in missing_hour_buckets
        if str(item).isdigit() and 0 <= int(item) <= 23
    )
    ordered_missing_ints = [hour for hour in missing_ints if hour >= current_hour] + [
        hour for hour in missing_ints if hour < current_hour
    ]
    target_next_hour = f"{ordered_missing_ints[0]:02d}" if ordered_missing_ints else None
    target_next_kst_hour = f"{(ordered_missing_ints[0] + 9) % 24:02d}" if ordered_missing_ints else None
    recommended_utc_hours = [f"{hour:02d}:00Z" for hour in ordered_missing_ints[:8]]
    recommended_kst_hours = [f"{(hour + 9) % 24:02d}:00KST" for hour in ordered_missing_ints[:8]]
    missing_kst_hour_buckets = [f"{(hour + 9) % 24:02d}" for hour in missing_ints]
    earliest_calendar_gate_date = (generated_at.date() + timedelta(days=missing_days)).isoformat()
    return {
        "dominant_collection_blocker": progress.get("dominant_collection_blocker"),
        "minimum_additional_quote_samples": missing_samples,
        "minimum_additional_calendar_days": missing_days,
        "minimum_additional_distinct_hours": missing_hours,
        "captured_quote_rows_this_cycle": captured_this_cycle,
        "recommended_min_quote_samples_per_remaining_day": recommended_samples_per_day,
        "recommended_min_evidence_cycles_per_remaining_day": recommended_cycles_per_day,
        "recommended_min_distinct_utc_hours_per_remaining_day": recommended_distinct_hours_per_day,
        "utc_hour_of_day_covered_count": coverage.get("utc_hour_of_day_covered_count"),
        "utc_hour_of_day_covered": list(coverage.get("utc_hour_of_day_covered") or []),
        "utc_hour_of_day_missing": missing_hour_buckets,
        "kst_hour_of_day_missing": missing_kst_hour_buckets,
        "target_next_utc_hour_of_day": target_next_hour,
        "target_next_kst_hour_of_day": target_next_kst_hour,
        "recommended_utc_collection_hours": recommended_utc_hours,
        "recommended_kst_collection_hours": recommended_kst_hours,
        "earliest_quote_calendar_gate_date_utc": earliest_calendar_gate_date,
        "assumption": "one_or_more_valid_quote_shadow_samples_collected_on_each_new_utc_calendar_day",
    }


def _dedupe_actions(actions: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for action in actions:
        text = str(action or "")
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _evidence_next_actions(
    *,
    drought_audit: dict[str, Any],
    collection_forecast: dict[str, Any],
    apply_gate: dict[str, Any],
) -> list[str]:
    actions = list(drought_audit.get("next_actions") or [])
    if collection_forecast.get("minimum_additional_calendar_days"):
        actions.append("run_evidence_cycle_once_per_new_utc_day_until_quote_calendar_floor_passes")
    if collection_forecast.get("minimum_additional_distinct_hours"):
        actions.append("spread_quote_shadow_collection_across_missing_utc_hours")
    if apply_gate.get("can_request_paper_apply_now") is True:
        actions.append("operator_may_rerun_with_apply_paper_bridge_after_review_and_backup")
    return _dedupe_actions(actions)


def _adaptive_next_actions(
    *,
    base_actions: list[str],
    adaptive_collection_plan: dict[str, Any],
    apply_gate: dict[str, Any],
    signal_wait_plan: dict[str, Any],
) -> list[str]:
    actions = list(base_actions)
    advances_quote_now = adaptive_collection_plan.get("advances_quote_evidence_now") is True
    useful_now = adaptive_collection_plan.get("useful_to_run_now") is True
    next_window = dict(adaptive_collection_plan.get("next_quote_evidence_window") or {})
    if apply_gate.get("fresh_market_data") is not True:
        actions = [
            "refresh_market_data_and_rerun_evidence_cycle_before_signal_or_quote_decisions",
            *actions,
        ]
    if apply_gate.get("fresh_signal") is not True:
        actions.append("monitor_fresh_v6_signal_on_signal_wait_plan_cadence_without_forcing_entry")
        if signal_wait_plan.get("cadence_lag_level") == "severe_signal_drought_but_entry_quality_gate_still_blocks_relaxation":
            actions.append("do_not_force_signal_or_relax_low_quality_filters_despite_extended_drought")
    if not advances_quote_now:
        actions = [
            action
            for action in actions
            if action
            not in {
                "continue_quote_shadow_collection_until_samples_calendar_days_and_distinct_hours_pass",
                "spread_quote_shadow_collection_across_missing_utc_hours",
            }
        ]
        if next_window.get("status") == "wait":
            actions.append("wait_until_next_quote_evidence_window_before_quote_shadow_capture")
        elif next_window.get("status") == "now":
            actions.append("quote_shadow_capture_can_resume_now")
        else:
            actions.append("skip_quote_shadow_capture_until_quote_gate_requires_more_evidence")
    elif useful_now:
        actions.append("run_quote_shadow_capture_on_current_valid_quote_window")
    if not useful_now and adaptive_collection_plan.get("bridge_audit_refresh_useful_now") is True:
        actions.append("bridge_audit_refresh_optional_now_without_quote_capture")
    if apply_gate.get("can_request_paper_apply_now") is True:
        actions.append("paper_bridge_apply_available_after_operator_review")
    return _dedupe_actions(actions)


def _market_data_refresh_plan(
    *,
    cycle_report: dict[str, Any],
    apply_gate: dict[str, Any],
) -> dict[str, Any]:
    bridge = dict(cycle_report.get("bridge") or {})
    freshness = dict(bridge.get("freshness") or {})
    runtime = dict(bridge.get("runtime_load_context") or {})
    age = _num(freshness.get("market_data_age_minutes"))
    max_age = _num(runtime.get("max_cache_age_minutes"))
    stale_by = round(max(float(age or 0.0) - float(max_age or 0.0), 0.0), 4) if age is not None and max_age else None
    fresh = apply_gate.get("fresh_market_data") is True
    if fresh:
        status = "fresh"
        severity = "none"
        action = "no_market_data_refresh_needed"
    elif age is None:
        status = "market_data_age_unknown"
        severity = "high"
        action = "rerun_evidence_cycle_and_inspect_runtime_load_context"
    elif max_age is None:
        status = "market_data_limit_unknown"
        severity = "medium"
        action = "rerun_evidence_cycle_with_explicit_max_market_data_age_minutes"
    elif stale_by is not None and stale_by <= 5.0:
        status = "stale_minor_threshold_breach"
        severity = "low"
        action = "refresh_market_data_and_rerun_without_quote_capture"
    elif stale_by is not None and stale_by <= 30.0:
        status = "stale_moderate"
        severity = "medium"
        action = "refresh_market_data_and_verify_exchange_cache"
    else:
        status = "stale_major"
        severity = "high"
        action = "inspect_market_data_source_before_interpreting_runtime_signal"
    cache_dir = str(runtime.get("cache_dir") or "reports/validation/btc_flip_rotation_search/cache")
    base_url = str(runtime.get("base_url") or "https://fapi.binance.com")
    runtime_load_days = int(runtime.get("load_days") or runtime.get("days") or 180)
    source_load_days = int(runtime.get("source_load_days") or 0)
    refresh_days = runtime_load_days or source_load_days or 1825
    cache_refresh_command = (
        ".venv/bin/python scripts/run_btc_flip_rotation_search.py "
        "--data-refresh-only --write-report "
        "--symbol BTCUSDT "
        f"--days {max(refresh_days, 30)} "
        "--intervals 5m,1h,4h "
        f"--cache-dir {shlex.quote(cache_dir)} "
        f"--base-url {shlex.quote(base_url)} "
        "--max-cache-age-minutes 0 "
        "--report-dir reports/validation/diagnostics/<market_data_cache_refresh_report_dir>"
    )
    evidence_rerun_command = (
        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
        "--quote-samples-per-tick 0 "
        f"--max-market-data-age-minutes {int(max_age or 30)} "
        "--report-dir reports/validation/diagnostics/<market_data_refresh_report_dir>"
    )
    return {
        "status": status,
        "severity": severity,
        "fresh_market_data": fresh,
        "market_data_age_minutes": age,
        "max_market_data_age_minutes": max_age,
        "stale_by_minutes": stale_by,
        "runtime_load_context": runtime,
        "refresh_days": max(refresh_days, 30),
        "source_load_days": source_load_days or None,
        "reason": "refresh_runtime_load_days_cache_not_source_search_cache",
        "snapshot_blockers": list(apply_gate.get("snapshot_blockers") or []),
        "recommended_action": action,
        "command": None if fresh else cache_refresh_command,
        "cache_refresh_command": None if fresh else cache_refresh_command,
        "evidence_rerun_command": None if fresh else evidence_rerun_command,
        "sequence": []
        if fresh
        else [
            {
                "step": 1,
                "action": "refresh_runtime_market_data_cache",
                "command": cache_refresh_command,
                "no_live_order_sent": True,
            },
            {
                "step": 2,
                "action": "rerun_evidence_cycle_after_cache_refresh",
                "command": evidence_rerun_command,
                "no_live_order_sent": True,
            },
        ],
        "no_live_order_sent": True,
    }


def _signal_wait_plan(
    *,
    cycle_report: dict[str, Any],
    apply_gate: dict[str, Any],
    generated_at: datetime,
    max_signal_age_minutes: int,
) -> dict[str, Any]:
    bridge = dict(cycle_report.get("bridge") or {})
    cadence = dict(bridge.get("event_cadence") or {})
    freshness = dict(bridge.get("freshness") or {})
    fresh_signal = apply_gate.get("fresh_signal") is True
    signal_age_minutes = _num(freshness.get("signal_age_minutes"))
    signal_age_hours = round(signal_age_minutes / 60.0, 4) if signal_age_minutes is not None else None
    max_age = float(max(1, int(max_signal_age_minutes or 1)))
    stale_by = round(max(float(signal_age_minutes or 0.0) - max_age, 0.0), 4) if signal_age_minutes is not None else None
    latest_add_age_hours = _num(cadence.get("latest_add_age_hours"))
    median_gap_hours = _num(cadence.get("median_gap_hours"))
    expected_days_per_event = _num(cadence.get("expected_days_per_event"))
    expected_event_interval_hours = (
        round(float(expected_days_per_event) * 24.0, 4) if expected_days_per_event is not None else None
    )
    latest_age_to_median_gap = _num(cadence.get("latest_age_to_median_gap"))
    median_add_gap_hours = _num(cadence.get("median_add_gap_hours"))
    expected_days_per_add = _num(cadence.get("expected_days_per_add"))
    expected_add_interval_hours = (
        round(float(expected_days_per_add) * 24.0, 4) if expected_days_per_add is not None else None
    )
    latest_add_age_to_median_gap = _num(cadence.get("latest_add_age_to_median_gap"))
    if latest_add_age_to_median_gap is None and latest_add_age_hours is not None and median_add_gap_hours:
        latest_add_age_to_median_gap = round(float(latest_add_age_hours) / float(median_add_gap_hours), 4)

    if fresh_signal:
        status = "fresh_signal_available"
        cadence_lag_level = "none"
        cadence_recommended_interval = None
        recommended_action = "review_paper_apply_gate_if_bridge_is_dry_run_actionable"
    elif latest_add_age_to_median_gap is None:
        status = "blocked_waiting_for_fresh_signal"
        cadence_lag_level = "cadence_unknown"
        cadence_recommended_interval = 30
        recommended_action = "monitor_bridge_without_forcing_entry_relaxation"
    elif latest_add_age_to_median_gap <= 1.0:
        status = "blocked_waiting_for_fresh_signal"
        cadence_lag_level = "within_recent_add_cadence"
        cadence_recommended_interval = 60
        recommended_action = "monitor_bridge_without_forcing_entry_relaxation"
    elif latest_add_age_to_median_gap <= 2.0:
        status = "blocked_waiting_for_fresh_signal"
        cadence_lag_level = "above_recent_median_add_gap"
        cadence_recommended_interval = 30
        recommended_action = "increase_signal_monitoring_without_relaxing_entry_filters"
    elif latest_add_age_to_median_gap <= 5.0:
        status = "blocked_waiting_for_fresh_signal"
        cadence_lag_level = "extended_signal_drought"
        cadence_recommended_interval = 15
        recommended_action = "increase_signal_monitoring_without_relaxing_entry_filters"
    else:
        status = "blocked_waiting_for_fresh_signal"
        cadence_lag_level = "severe_signal_drought_but_entry_quality_gate_still_blocks_relaxation"
        cadence_recommended_interval = 15
        recommended_action = "monitor_frequently_but_do_not_force_signal_or_relax_low_quality_filters"

    recommended_interval = (
        min(int(cadence_recommended_interval), int(max_age))
        if cadence_recommended_interval is not None
        else None
    )
    monitor_interval_capped = (
        cadence_recommended_interval is not None
        and recommended_interval is not None
        and int(recommended_interval) < int(cadence_recommended_interval)
    )
    next_monitor = (
        generated_at.astimezone(UTC) + timedelta(minutes=int(recommended_interval))
        if recommended_interval is not None
        else None
    )
    command = (
        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
        "--quote-samples-per-tick 0 "
        "--refresh-market-data-before-run "
        "--historical-evidence-replay --historical-lifecycle-replay "
        f"--max-signal-age-minutes {int(max_age)} "
        f"--report-dir reports/validation/diagnostics/market_state_rotation_v6_signal_monitor_{generated_at.astimezone(UTC):%Y%m%d_%H%M%SZ}"
    )
    return {
        "status": status,
        "fresh_signal": fresh_signal,
        "signal_age_minutes": signal_age_minutes,
        "signal_age_hours": signal_age_hours,
        "max_signal_age_minutes": max_age,
        "signal_stale_by_minutes": stale_by,
        "latest_event_ts": cadence.get("latest_event_ts"),
        "latest_event_age_hours": _num(cadence.get("latest_event_age_hours")),
        "latest_age_to_median_gap": latest_age_to_median_gap,
        "median_gap_hours": median_gap_hours,
        "expected_days_per_event": expected_days_per_event,
        "expected_event_interval_hours": expected_event_interval_hours,
        "event_wait_state": cadence.get("wait_state"),
        "bridge_event_count": cadence.get("bridge_event_count"),
        "add_event_count": cadence.get("add_event_count"),
        "remove_event_count": cadence.get("remove_event_count"),
        "latest_add_ts": cadence.get("latest_add_ts"),
        "latest_add_age_hours": latest_add_age_hours,
        "median_add_gap_hours": median_add_gap_hours,
        "expected_days_per_add": expected_days_per_add,
        "expected_add_interval_hours": expected_add_interval_hours,
        "latest_add_age_to_median_gap": latest_add_age_to_median_gap,
        "add_wait_state": cadence.get("add_wait_state"),
        "cadence_lag_level": cadence_lag_level,
        "cadence_recommended_monitor_interval_minutes": cadence_recommended_interval,
        "recommended_monitor_interval_minutes": recommended_interval,
        "signal_freshness_capture_window_minutes": max_age,
        "monitor_interval_capped_by_signal_freshness": monitor_interval_capped,
        "monitor_signal_age_alignment": (
            "fresh_signal_available"
            if fresh_signal
            else (
                "capped_to_fresh_signal_window"
                if monitor_interval_capped
                else "interval_within_fresh_signal_window"
            )
        ),
        "next_monitor_after_utc": next_monitor.isoformat() if next_monitor is not None else None,
        "next_monitor_after_kst": next_monitor.astimezone(KST).isoformat() if next_monitor is not None else None,
        "recommended_action": recommended_action,
        "command": None if fresh_signal else command,
        "paper_apply_unblocked_when": "fresh_signal_true_and_bridge_dry_run_actionable_after_operator_review",
        "manual_signal_override_allowed": False,
        "no_live_order_sent": True,
    }


def _quote_window_execution_plan(*, next_window: dict[str, Any], capture_command: str | None) -> dict[str, Any]:
    status = str(next_window.get("status") or "")
    if status not in {"now", "wait"}:
        return {}
    missed_window_command = (
        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
        "--quote-samples-per-tick 0 "
        "--historical-evidence-replay --historical-lifecycle-replay "
        "--report-dir reports/validation/diagnostics/<missed_quote_window_recompute_report_dir>"
    )
    return {
        "status": status,
        "window_kind": next_window.get("window_kind"),
        "urgency": next_window.get("urgency"),
        "run_at_or_after_utc": next_window.get("at_utc"),
        "run_at_or_after_kst": next_window.get("at_kst"),
        "run_before_utc": next_window.get("valid_until_utc"),
        "run_before_kst": next_window.get("valid_until_kst"),
        "wait_minutes": next_window.get("wait_minutes"),
        "valid_duration_minutes": next_window.get("valid_duration_minutes"),
        "capture_command": capture_command,
        "missed_window_next_step": next_window.get("missed_window_next_step"),
        "missed_window_command": missed_window_command if next_window.get("missed_window_next_step") else None,
        "no_live_order_sent": True,
    }


def _operator_action_plan(
    *,
    adaptive_collection_plan: dict[str, Any],
    apply_gate: dict[str, Any],
    market_data_refresh_plan: dict[str, Any],
    pre_apply_backup_plan: dict[str, Any],
    signal_wait_plan: dict[str, Any],
) -> dict[str, Any]:
    commands = dict(adaptive_collection_plan.get("operator_commands") or {})
    next_window = dict(adaptive_collection_plan.get("next_quote_evidence_window") or {})
    quote_window_execution = _quote_window_execution_plan(
        next_window=next_window,
        capture_command=commands.get("next_evidence_cycle"),
    )
    items: list[dict[str, Any]] = []
    if apply_gate.get("fresh_market_data") is not True:
        items.append(
            {
                "priority": 0,
                "action": "refresh_market_data_and_rerun_evidence_cycle",
                "run_now": True,
                "stage": "market_data",
                "command": market_data_refresh_plan.get("command"),
                "reason": market_data_refresh_plan.get("status") or "market_data_freshness_gate_closed",
                "market_data_age_minutes": market_data_refresh_plan.get("market_data_age_minutes"),
                "max_market_data_age_minutes": market_data_refresh_plan.get("max_market_data_age_minutes"),
                "stale_by_minutes": market_data_refresh_plan.get("stale_by_minutes"),
                "requires_operator_review": False,
            }
        )
    if apply_gate.get("can_request_paper_apply_now") is True:
        items.append(
            {
                "priority": 0,
                "action": "operator_review_paper_bridge_apply",
                "run_now": True,
                "stage": "paper",
                "command": commands.get("paper_apply_only_if_gate_allows"),
                "reason": "fresh_signal_gate_open_and_bridge_is_dry_run_actionable",
                "requires_operator_review": True,
                "pre_apply_backup_plan": dict(pre_apply_backup_plan or {}),
                "pre_apply_verification_required": True,
                "post_apply_required_review": "execution_parity_review",
            }
        )
    if adaptive_collection_plan.get("advances_quote_evidence_now") is True:
        items.append(
            {
                "priority": 1,
                "action": "run_quote_shadow_capture_now",
                "run_now": True,
                "stage": "shadow_evidence",
                "execute_before_utc": next_window.get("valid_until_utc"),
                "execute_before_kst": next_window.get("valid_until_kst"),
                "valid_duration_minutes": next_window.get("valid_duration_minutes"),
                "window_kind": next_window.get("window_kind"),
                "window_urgency": next_window.get("urgency"),
                "missed_window_next_step": next_window.get("missed_window_next_step"),
                "missed_window_command": quote_window_execution.get("missed_window_command"),
                "execution_window": quote_window_execution,
                "command": commands.get("next_evidence_cycle"),
                "reason": "current_utc_date_or_hour_advances_quote_evidence",
                "requires_operator_review": False,
            }
        )
    else:
        if next_window.get("status") == "wait":
            items.append(
                {
                    "priority": 1,
                    "action": "wait_for_next_quote_evidence_window",
                    "run_now": False,
                    "stage": "shadow_evidence",
                    "execute_after_utc": next_window.get("at_utc"),
                    "execute_after_kst": next_window.get("at_kst"),
                    "execute_before_utc": next_window.get("valid_until_utc"),
                    "execute_before_kst": next_window.get("valid_until_kst"),
                    "wait_minutes": next_window.get("wait_minutes"),
                    "valid_duration_minutes": next_window.get("valid_duration_minutes"),
                    "window_kind": next_window.get("window_kind"),
                    "window_urgency": next_window.get("urgency"),
                    "missed_window_next_step": next_window.get("missed_window_next_step"),
                    "missed_window_command": quote_window_execution.get("missed_window_command"),
                    "execution_window": quote_window_execution,
                    "command": commands.get("next_evidence_cycle"),
                    "reason": next_window.get("reason"),
                    "requires_operator_review": False,
                }
            )
        elif next_window.get("status") == "now":
            items.append(
                {
                    "priority": 1,
                    "action": "quote_shadow_capture_can_resume_now",
                    "run_now": True,
                    "stage": "shadow_evidence",
                    "execute_before_utc": next_window.get("valid_until_utc"),
                    "execute_before_kst": next_window.get("valid_until_kst"),
                    "valid_duration_minutes": next_window.get("valid_duration_minutes"),
                    "window_kind": next_window.get("window_kind"),
                    "window_urgency": next_window.get("urgency"),
                    "missed_window_next_step": next_window.get("missed_window_next_step"),
                    "missed_window_command": quote_window_execution.get("missed_window_command"),
                    "execution_window": quote_window_execution,
                    "command": commands.get("next_evidence_cycle"),
                    "reason": next_window.get("reason"),
                    "requires_operator_review": False,
            }
        )
    if apply_gate.get("fresh_signal") is not True:
        items.append(
            {
                "priority": 2,
                "action": "monitor_fresh_signal_without_quote_capture",
                "run_now": False,
                "stage": "signal_monitor",
                "execute_after_utc": signal_wait_plan.get("next_monitor_after_utc"),
                "execute_after_kst": signal_wait_plan.get("next_monitor_after_kst"),
                "recommended_monitor_interval_minutes": signal_wait_plan.get("recommended_monitor_interval_minutes"),
                "latest_add_age_to_median_gap": signal_wait_plan.get("latest_add_age_to_median_gap"),
                "cadence_lag_level": signal_wait_plan.get("cadence_lag_level"),
                "command": signal_wait_plan.get("command"),
                "reason": signal_wait_plan.get("recommended_action"),
                "manual_signal_override_allowed": False,
                "requires_operator_review": False,
            }
        )
    if (
        adaptive_collection_plan.get("bridge_audit_refresh_useful_now") is True
        and adaptive_collection_plan.get("advances_quote_evidence_now") is not True
    ):
        items.append(
            {
                "priority": 3,
                "action": "optional_bridge_audit_refresh_without_quote_capture",
                "run_now": True,
                "stage": "paper_readiness_audit",
                "command": (
                    ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                    "--quote-samples-per-tick 0 "
                    "--historical-evidence-replay --historical-lifecycle-replay "
                    "--report-dir reports/validation/diagnostics/<bridge_refresh_report_dir>"
                ),
                "reason": "refresh_bridge_and_drought_audits_without_adding_duplicate_quote_samples",
                "requires_operator_review": False,
            }
        )
    if apply_gate.get("fresh_signal") is not True:
        items.append(
            {
                "priority": 4,
                "action": "wait_for_fresh_v6_signal_for_paper_fill",
                "run_now": False,
                "stage": "paper_fill",
                "command": None,
                "reason": "fresh_signal_gate_closed",
                "requires_operator_review": False,
            }
        )
    items.append(
        {
            "priority": 99,
            "action": "do_not_enable_live_orders",
            "run_now": False,
            "stage": "live",
            "command": None,
            "reason": "evidence_cycle_is_paper_only_and_live_requires_separate_promotion_gate",
            "requires_operator_review": True,
        }
    )
    items = sorted(items, key=lambda item: int(item.get("priority") or 0))
    top_action = items[0] if items else {}
    if top_action.get("action") == "refresh_market_data_and_rerun_evidence_cycle":
        status = "market_data_refresh_required"
    elif top_action.get("action") == "operator_review_paper_bridge_apply":
        status = "paper_apply_review_available"
    elif top_action.get("action") == "run_quote_shadow_capture_now":
        status = "run_quote_capture_now"
    elif top_action.get("action") == "wait_for_next_quote_evidence_window":
        status = "wait_for_next_quote_window"
    elif top_action.get("action") == "monitor_fresh_signal_without_quote_capture":
        status = "signal_monitor_wait"
    elif top_action.get("action") == "optional_bridge_audit_refresh_without_quote_capture":
        status = "optional_bridge_refresh_only"
    else:
        status = "review_required"
    return {
        "status": status,
        "top_action": top_action,
        "items": items,
        "live_order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _compact_operator_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "priority": item.get("priority"),
        "action": item.get("action"),
        "stage": item.get("stage"),
        "run_now": item.get("run_now"),
        "execute_after_utc": item.get("execute_after_utc"),
        "execute_after_kst": item.get("execute_after_kst"),
        "execute_before_utc": item.get("execute_before_utc"),
        "execute_before_kst": item.get("execute_before_kst"),
        "command": item.get("command"),
        "missed_window_next_step": item.get("missed_window_next_step"),
        "missed_window_command": item.get("missed_window_command"),
        "recovery_action": item.get("recovery_action"),
        "recovery_command": item.get("recovery_command"),
        "original_command": item.get("original_command"),
        "expired_at_utc": item.get("expired_at_utc"),
        "expired_by_minutes": item.get("expired_by_minutes"),
        "blocked_by": item.get("blocked_by"),
        "blocked_until": item.get("blocked_until"),
        "reason": item.get("reason"),
        "requires_operator_review": item.get("requires_operator_review"),
        "pre_apply_backup_plan": item.get("pre_apply_backup_plan"),
        "pre_apply_verification_required": item.get("pre_apply_verification_required"),
        "post_apply_required_review": item.get("post_apply_required_review"),
    }


def _expired_operator_item(item: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    expired_at = _parse_dt(item.get("execute_before_utc"))
    recovery = dict(item)
    recovery["original_command"] = item.get("command")
    recovery["expired_at_utc"] = expired_at.astimezone(UTC).isoformat() if expired_at is not None else None
    recovery["expired_by_minutes"] = (
        round(max((now - expired_at.astimezone(UTC)).total_seconds(), 0.0) / 60.0, 4)
        if expired_at is not None
        else None
    )
    recovery["recovery_action"] = item.get("missed_window_next_step") or "rerun_evidence_cycle_to_recompute_operator_runbook"
    recovery["recovery_command"] = item.get("missed_window_command") or item.get("command")
    recovery["command"] = recovery["recovery_command"]
    recovery["reason"] = recovery["recovery_action"]
    return recovery


def _operator_runbook_plan(*, operator_action_plan: dict[str, Any], generated_at: datetime) -> dict[str, Any]:
    now = generated_at.astimezone(UTC)
    items = [dict(item) for item in operator_action_plan.get("items") or []]
    run_now = [
        item
        for item in items
        if item.get("run_now") is True and str(item.get("stage") or "") != "live"
    ]
    scheduled = [
        item
        for item in items
        if item.get("run_now") is not True and item.get("execute_after_utc") and str(item.get("stage") or "") != "live"
    ]
    guarded = [
        item
        for item in items
        if str(item.get("stage") or "") == "live"
        or (item.get("run_now") is not True and not item.get("command") and not item.get("execute_after_utc"))
    ]
    run_now = sorted(run_now, key=lambda item: int(item.get("priority") or 0))
    scheduled = sorted(
        scheduled,
        key=lambda item: (
            _parse_dt(item.get("execute_after_utc")) or datetime.max.replace(tzinfo=UTC),
            int(item.get("priority") or 0),
        ),
    )
    guarded = sorted(guarded, key=lambda item: int(item.get("priority") or 0))
    expired_scheduled_raw = [
        item
        for item in scheduled
        if (before := _parse_dt(item.get("execute_before_utc"))) is not None and before.astimezone(UTC) <= now
    ]
    active_scheduled = [item for item in scheduled if item not in expired_scheduled_raw]
    due_scheduled = [
        item
        for item in active_scheduled
        if (_parse_dt(item.get("execute_after_utc")) or datetime.max.replace(tzinfo=UTC)).astimezone(UTC) <= now
    ]
    future_scheduled = [item for item in active_scheduled if item not in due_scheduled]
    expired_scheduled = [_expired_operator_item(item, now=now) for item in expired_scheduled_raw]
    top_action = dict(operator_action_plan.get("top_action") or {})
    quote_item = next((item for item in items if str(item.get("stage") or "") == "shadow_evidence"), None)
    signal_item = next((item for item in items if str(item.get("stage") or "") == "signal_monitor"), None)
    market_item = next((item for item in items if str(item.get("stage") or "") == "market_data"), None)
    market_refresh_required = market_item is not None and market_item.get("run_now") is True
    if market_refresh_required:
        blocked_by_market_data_raw = [
            item
            for item in [*run_now, *expired_scheduled, *due_scheduled, *future_scheduled]
            if str(item.get("stage") or "")
            in {"shadow_evidence", "signal_monitor", "paper_readiness_audit", "paper_fill"}
        ]
        blocked_by_market_data = []
        for item in blocked_by_market_data_raw:
            blocked = dict(item)
            blocked["blocked_by"] = "market_data_freshness"
            blocked["blocked_until"] = "rerun_evidence_cycle_after_market_data_refresh"
            blocked["reason"] = "market_data_refresh_required_before_quote_signal_or_paper_fill_actions"
            blocked_by_market_data.append(blocked)
        expired_scheduled = [item for item in expired_scheduled if item not in blocked_by_market_data_raw]
        due_scheduled = [item for item in due_scheduled if item not in blocked_by_market_data_raw]
        future_scheduled = [item for item in future_scheduled if item not in blocked_by_market_data_raw]
        run_now = [item for item in run_now if item not in blocked_by_market_data_raw]
    else:
        blocked_by_market_data = []
    required_now = [item for item in run_now if int(item.get("priority") or 0) <= 1]
    optional_now = [item for item in run_now if int(item.get("priority") or 0) > 1]
    if market_item and market_item.get("run_now") is True:
        coordination_rule = "refresh_market_data_before_quote_or_signal_decisions"
    elif quote_item and quote_item.get("run_now") is True and signal_item:
        coordination_rule = "run_quote_capture_first_then_monitor_signal_on_its_due_cadence"
    elif quote_item and quote_item.get("run_now") is not True and signal_item:
        coordination_rule = "wait_for_quote_window_and_monitor_signal_without_quote_capture_when_due"
    elif signal_item:
        coordination_rule = "signal_monitor_only_until_quote_window_or_fresh_signal_changes"
    else:
        coordination_rule = "follow_top_operator_action"

    coordination_warnings: list[str] = []
    if blocked_by_market_data:
        coordination_warnings.append("market_data_refresh_required_before_downstream_quote_signal_or_paper_actions")
    if expired_scheduled:
        coordination_warnings.append("expired_scheduled_window_requires_recompute_before_capture")
    if optional_now and (required_now or expired_scheduled or due_scheduled or future_scheduled):
        coordination_warnings.append("optional_now_action_does_not_replace_required_due_or_scheduled_actions")
    if quote_item and signal_item:
        coordination_warnings.append("keep_quote_window_and_signal_monitor_cadences_separate")

    if required_now:
        status = "run_required_action_now"
        next_action = required_now[0]
    elif expired_scheduled:
        status = "recover_expired_scheduled_action"
        next_action = expired_scheduled[0]
    elif due_scheduled:
        status = "run_due_scheduled_action_now"
        next_action = due_scheduled[0]
    elif future_scheduled:
        status = "wait_until_next_scheduled_action"
        next_action = future_scheduled[0]
    elif optional_now:
        status = "optional_action_available"
        next_action = optional_now[0]
    else:
        status = "guarded_wait"
        next_action = top_action

    next_optional_action = optional_now[0] if optional_now else None

    sequence: list[dict[str, Any]] = []
    for item in required_now:
        sequence.append({"step": len(sequence) + 1, "timing": "now", **_compact_operator_item(item)})
    for item in expired_scheduled:
        sequence.append({"step": len(sequence) + 1, "timing": "expired", **_compact_operator_item(item)})
    for item in due_scheduled:
        sequence.append({"step": len(sequence) + 1, "timing": "due_now", **_compact_operator_item(item)})
    for item in optional_now:
        sequence.append({"step": len(sequence) + 1, "timing": "optional_now", **_compact_operator_item(item)})
    for item in future_scheduled[:3]:
        sequence.append({"step": len(sequence) + 1, "timing": "scheduled", **_compact_operator_item(item)})
    for item in blocked_by_market_data:
        sequence.append({"step": len(sequence) + 1, "timing": "blocked_by_market_data", **_compact_operator_item(item)})
    for item in guarded:
        if str(item.get("stage") or "") == "live":
            sequence.append({"step": len(sequence) + 1, "timing": "blocked", **_compact_operator_item(item)})

    return {
        "status": status,
        "generated_at": generated_at.astimezone(UTC).isoformat(),
        "next_operator_action": _compact_operator_item(next_action),
        "next_required_or_scheduled_action": _compact_operator_item(next_action)
        if status != "optional_action_available"
        else None,
        "next_optional_action": _compact_operator_item(next_optional_action) if next_optional_action else None,
        "required_now_actions": [_compact_operator_item(item) for item in required_now],
        "optional_now_actions": [_compact_operator_item(item) for item in optional_now],
        "run_now_actions": [_compact_operator_item(item) for item in run_now],
        "expired_actions": [_compact_operator_item(item) for item in expired_scheduled],
        "due_now_actions": [_compact_operator_item(item) for item in due_scheduled],
        "scheduled_actions": [_compact_operator_item(item) for item in future_scheduled],
        "blocked_by_market_data_actions": [_compact_operator_item(item) for item in blocked_by_market_data],
        "guarded_actions": [_compact_operator_item(item) for item in guarded],
        "operator_sequence": sequence,
        "coordination_rule": coordination_rule,
        "coordination_warnings": coordination_warnings,
        "coordination_warning_count": len(coordination_warnings),
        "required_now_action_count": len(required_now),
        "optional_now_action_count": len(optional_now),
        "run_now_action_count": len(run_now),
        "expired_action_count": len(expired_scheduled),
        "due_now_action_count": len(due_scheduled),
        "scheduled_action_count": len(future_scheduled),
        "blocked_by_market_data_action_count": len(blocked_by_market_data),
        "guarded_action_count": len(guarded),
        "live_order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _recommended_utc_hour_int(value: Any) -> int | None:
    text = str(value or "").strip()
    if ":" in text:
        text = text.split(":", 1)[0]
    text = text.rstrip("Zz")
    if not text.isdigit():
        return None
    hour = int(text)
    return hour if 0 <= hour <= 23 else None


def _future_utc_hour_window(*, generated_at: datetime, hour: int) -> tuple[datetime, datetime]:
    now = generated_at.astimezone(UTC)
    start = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if start <= now:
        start += timedelta(days=1)
    return start, start + timedelta(hours=1)


def _operator_item_from_runbook(runbook: dict[str, Any], *, stage: str) -> dict[str, Any]:
    for key in (
        "required_now_actions",
        "expired_actions",
        "due_now_actions",
        "scheduled_actions",
        "optional_now_actions",
        "run_now_actions",
    ):
        for item in list(runbook.get(key) or []):
            if str(dict(item).get("stage") or "") == stage:
                return dict(item)
    return {}


def _timeline_report_stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%d_%H%MZ")


def _timeline_report_dir(kind: str, value: datetime) -> str:
    safe_kind = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(kind or "event").lower()).strip("_")
    return f"market_state_rotation_v6_timeline_{safe_kind}_{_timeline_report_stamp(value)}"


def _render_timeline_command(command: Any, *, kind: str, value: datetime) -> str | None:
    if not command:
        return None
    text = str(command)
    replacements = {
        "<new_report_dir>": _timeline_report_dir(kind, value),
        "<missed_quote_window_recompute_report_dir>": _timeline_report_dir(f"{kind}_missed_recompute", value),
        "<signal_monitor_report_dir>": _timeline_report_dir(kind, value),
        "<bridge_refresh_report_dir>": _timeline_report_dir(kind, value),
        "<market_data_refresh_report_dir>": _timeline_report_dir(kind, value),
        "<paper_apply_report_dir>": _timeline_report_dir(kind, value),
    }
    for placeholder, replacement in replacements.items():
        text = text.replace(placeholder, replacement)
    return text


def _command_tokens(command: Any) -> list[str]:
    if not command:
        return []
    try:
        return shlex.split(str(command))
    except ValueError:
        return str(command).split()


def _command_arg_value(command: Any, flag: str) -> str | None:
    tokens = _command_tokens(command)
    for idx, token in enumerate(tokens):
        if token == flag and idx + 1 < len(tokens):
            return tokens[idx + 1]
        if token.startswith(f"{flag}="):
            return token.split("=", 1)[1]
    return None


def _command_has_live_flags(command: Any) -> bool:
    live_flags = {
        "--live",
        "--enable-live",
        "--enable-live-orders",
        "--submit-live-order",
        "--live-order",
        "--allow-live-orders",
        "--live-trading",
    }
    return any(str(token or "").strip().split("=", 1)[0] in live_flags for token in _command_tokens(command))


def _quote_samples_per_tick(command: Any) -> int | None:
    value = _command_arg_value(command, "--quote-samples-per-tick")
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _timeline_command_manifest(
    *,
    immediate_actions: list[dict[str, Any]],
    signal_monitor: dict[str, Any] | None,
    quote_slots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []

    def add(
        *,
        source: str,
        action: Any,
        stage: Any,
        command_type: str,
        rendered_command: Any,
        run_at_or_after_utc: Any,
        suggested_report_dir: Any = None,
    ) -> None:
        if not rendered_command:
            return
        command = str(rendered_command)
        report_dir = _command_arg_value(command, "--report-dir")
        quote_samples = _quote_samples_per_tick(command)
        manifest.append(
            {
                "source": source,
                "action": action,
                "stage": stage,
                "command_type": command_type,
                "run_at_or_after_utc": run_at_or_after_utc,
                "suggested_report_dir": suggested_report_dir,
                "report_dir": report_dir,
                "rendered_command": command,
                "placeholders_resolved": "<" not in command and ">" not in command,
                "quote_samples_per_tick": quote_samples,
                "live_order_flags_present": _command_has_live_flags(command),
                "no_live_order_sent": True,
            }
        )

    for item in immediate_actions:
        add(
            source=str(item.get("urgency") or "immediate"),
            action=item.get("action"),
            stage=item.get("stage"),
            command_type="immediate",
            rendered_command=item.get("rendered_command"),
            run_at_or_after_utc=item.get("run_at_or_after_utc"),
            suggested_report_dir=item.get("suggested_report_dir"),
        )
    if signal_monitor:
        add(
            source="signal_monitor",
            action=signal_monitor.get("action"),
            stage=signal_monitor.get("stage"),
            command_type="signal_monitor",
            rendered_command=signal_monitor.get("rendered_command"),
            run_at_or_after_utc=signal_monitor.get("run_at_or_after_utc"),
            suggested_report_dir=signal_monitor.get("suggested_report_dir"),
        )
    for slot in quote_slots:
        add(
            source=str(slot.get("source") or "quote_slot"),
            action=slot.get("action"),
            stage=slot.get("stage"),
            command_type="quote_capture",
            rendered_command=slot.get("rendered_command"),
            run_at_or_after_utc=slot.get("run_at_or_after_utc"),
            suggested_report_dir=slot.get("suggested_report_dir"),
        )
        add(
            source=str(slot.get("source") or "quote_slot"),
            action="recompute_after_missed_quote_window",
            stage=slot.get("stage"),
            command_type="missed_quote_window_recompute",
            rendered_command=slot.get("rendered_missed_window_command"),
            run_at_or_after_utc=slot.get("run_before_utc"),
            suggested_report_dir=None,
        )
    return manifest


def _timeline_command_validation(manifest: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    report_dirs = [str(item.get("report_dir") or "") for item in manifest if item.get("report_dir")]
    duplicate_report_dirs = sorted({path for path in report_dirs if report_dirs.count(path) > 1})
    for item in manifest:
        command_type = str(item.get("command_type") or "")
        report_dir = item.get("report_dir")
        quote_samples = item.get("quote_samples_per_tick")
        if item.get("placeholders_resolved") is not True:
            issues.append({"issue": "unresolved_placeholder", "command_type": command_type, "action": item.get("action")})
        if not report_dir:
            issues.append({"issue": "missing_report_dir", "command_type": command_type, "action": item.get("action")})
        if item.get("live_order_flags_present") is True:
            issues.append({"issue": "live_order_flag_present", "command_type": command_type, "action": item.get("action")})
        if command_type == "quote_capture" and (quote_samples is None or quote_samples <= 0):
            issues.append({"issue": "quote_capture_without_positive_quote_samples", "action": item.get("action")})
        if command_type in {"signal_monitor", "missed_quote_window_recompute"} and quote_samples != 0:
            issues.append({"issue": "non_capture_command_must_use_zero_quote_samples", "command_type": command_type})
        if command_type == "immediate" and str(item.get("stage") or "") in {"paper_readiness_audit", "market_data"} and quote_samples != 0:
            issues.append({"issue": "audit_or_market_data_command_must_use_zero_quote_samples", "action": item.get("action")})
    for report_dir in duplicate_report_dirs:
        issues.append({"issue": "duplicate_report_dir", "report_dir": report_dir})
    return {
        "status": "ready" if not issues else "review_required",
        "command_count": len(manifest),
        "unique_report_dir_count": len(set(report_dirs)),
        "duplicate_report_dir_count": len(duplicate_report_dirs),
        "unresolved_placeholder_count": sum(1 for item in manifest if item.get("placeholders_resolved") is not True),
        "live_order_flag_count": sum(1 for item in manifest if item.get("live_order_flags_present") is True),
        "issue_count": len(issues),
        "issues": issues,
        "no_live_order_sent": True,
    }


def _timeline_slot_utc_hour(slot: dict[str, Any]) -> str | None:
    started_at = _parse_dt(slot.get("run_at_or_after_utc"))
    if started_at is None:
        return None
    return f"{started_at.astimezone(UTC).hour:02d}"


def _timeline_collection_target_forecast(
    *,
    collection_forecast: dict[str, Any],
    adaptive_collection_plan: dict[str, Any],
    quote_slots: list[dict[str, Any]],
) -> dict[str, Any]:
    daily_targets = dict(adaptive_collection_plan.get("daily_targets") or {})
    planned_rows_per_slot = int(daily_targets.get("planned_quote_rows_per_target_hour_cycle") or 0)
    minimum_quote_samples_today = int(daily_targets.get("minimum_quote_samples") or 0)
    minimum_new_utc_hours_today = int(daily_targets.get("minimum_new_utc_hour_buckets") or 0)
    missing_quote_samples = int(collection_forecast.get("minimum_additional_quote_samples") or 0)
    missing_distinct_hours = int(collection_forecast.get("minimum_additional_distinct_hours") or 0)
    unique_slot_hours = sorted(
        {
            hour
            for slot in quote_slots
            if (hour := _timeline_slot_utc_hour(slot)) is not None
        }
    )
    estimated_quote_rows = len(quote_slots) * max(planned_rows_per_slot, 0)
    sample_shortfall = max(minimum_quote_samples_today - estimated_quote_rows, 0)
    hour_shortfall = max(minimum_new_utc_hours_today - len(unique_slot_hours), 0)
    warnings: list[str] = []
    if missing_quote_samples > 0 and planned_rows_per_slot <= 0:
        warnings.append("planned_quote_rows_per_slot_unknown_or_zero")
    if sample_shortfall > 0:
        warnings.append("timeline_quote_slots_below_daily_sample_target")
    if hour_shortfall > 0:
        warnings.append("timeline_quote_slots_below_daily_distinct_hour_target")
    if not quote_slots and (missing_quote_samples > 0 or missing_distinct_hours > 0):
        warnings.append("no_quote_collection_slots_planned_despite_missing_quote_evidence")
    if missing_quote_samples <= 0 and missing_distinct_hours <= 0:
        status = "quote_targets_already_satisfied"
    elif warnings:
        status = "timeline_below_daily_collection_targets"
    else:
        status = "timeline_covers_daily_collection_targets"
    return {
        "status": status,
        "planned_quote_slot_count": len(quote_slots),
        "planned_quote_rows_per_slot": planned_rows_per_slot,
        "estimated_quote_rows_if_all_slots_run": estimated_quote_rows,
        "minimum_quote_samples_today": minimum_quote_samples_today,
        "sample_target_covered": sample_shortfall == 0,
        "sample_shortfall_vs_daily_target": sample_shortfall,
        "unique_utc_hour_slots": unique_slot_hours,
        "unique_utc_hour_slot_count": len(unique_slot_hours),
        "minimum_new_utc_hour_buckets_today": minimum_new_utc_hours_today,
        "distinct_hour_target_covered": hour_shortfall == 0,
        "distinct_hour_shortfall_vs_daily_target": hour_shortfall,
        "estimated_remaining_quote_samples_after_timeline": max(missing_quote_samples - estimated_quote_rows, 0),
        "estimated_remaining_distinct_hours_after_timeline": max(missing_distinct_hours - len(unique_slot_hours), 0),
        "warning_count": len(warnings),
        "warnings": warnings,
        "no_live_order_sent": True,
    }


def _timeline_minimum_execution_plan(
    *,
    collection_forecast: dict[str, Any],
    collection_target_forecast: dict[str, Any],
    quote_slots: list[dict[str, Any]],
) -> dict[str, Any]:
    planned_rows_per_slot = int(collection_target_forecast.get("planned_quote_rows_per_slot") or 0)
    minimum_quote_samples_today = int(collection_target_forecast.get("minimum_quote_samples_today") or 0)
    minimum_new_utc_hours_today = int(collection_target_forecast.get("minimum_new_utc_hour_buckets_today") or 0)
    missing_quote_samples = int(collection_forecast.get("minimum_additional_quote_samples") or 0)
    missing_distinct_hours = int(collection_forecast.get("minimum_additional_distinct_hours") or 0)
    if missing_quote_samples <= 0 and missing_distinct_hours <= 0:
        return {
            "status": "no_quote_execution_required",
            "required_quote_slots": [],
            "optional_acceleration_slots": [],
            "required_quote_slot_count": 0,
            "optional_acceleration_slot_count": 0,
            "estimated_quote_rows_from_required_slots": 0,
            "required_unique_utc_hours": [],
            "required_unique_utc_hour_count": 0,
            "required_until_utc": None,
            "required_until_kst": None,
            "sample_target_reachable": True,
            "distinct_hour_target_reachable": True,
            "estimated_remaining_quote_samples_after_required_slots": 0,
            "estimated_remaining_distinct_hours_after_required_slots": 0,
            "warning_count": 0,
            "warnings": [],
            "no_live_order_sent": True,
        }

    required_slots: list[dict[str, Any]] = []
    selected_indexes: set[int] = set()
    selected_hours: set[str] = set()
    estimated_rows = 0
    for idx, slot in enumerate(quote_slots):
        hour = _timeline_slot_utc_hour(slot)
        need_samples = estimated_rows < minimum_quote_samples_today
        need_hours = len(selected_hours) < minimum_new_utc_hours_today and hour is not None and hour not in selected_hours
        if not need_samples and not need_hours:
            break
        required_slots.append(slot)
        selected_indexes.add(idx)
        estimated_rows += max(planned_rows_per_slot, 0)
        if hour is not None:
            selected_hours.add(hour)

    optional_slots = [slot for idx, slot in enumerate(quote_slots) if idx not in selected_indexes]
    required_unique_hours = sorted(selected_hours)
    sample_target_reachable = estimated_rows >= minimum_quote_samples_today
    distinct_hour_target_reachable = len(required_unique_hours) >= minimum_new_utc_hours_today
    warnings: list[str] = []
    if quote_slots and planned_rows_per_slot <= 0 and missing_quote_samples > 0:
        warnings.append("required_slot_sample_yield_unknown_or_zero")
    if not sample_target_reachable:
        warnings.append("minimum_execution_plan_below_daily_sample_target")
    if not distinct_hour_target_reachable:
        warnings.append("minimum_execution_plan_below_daily_distinct_hour_target")
    if not required_slots and (missing_quote_samples > 0 or missing_distinct_hours > 0):
        warnings.append("no_required_quote_slots_available")
    last_required_slot = required_slots[-1] if required_slots else {}
    status = "minimum_daily_targets_reachable" if not warnings else "minimum_daily_targets_not_reachable"
    return {
        "status": status,
        "required_quote_slots": required_slots,
        "optional_acceleration_slots": optional_slots,
        "required_quote_slot_count": len(required_slots),
        "optional_acceleration_slot_count": len(optional_slots),
        "estimated_quote_rows_from_required_slots": estimated_rows,
        "required_unique_utc_hours": required_unique_hours,
        "required_unique_utc_hour_count": len(required_unique_hours),
        "required_until_utc": last_required_slot.get("run_before_utc"),
        "required_until_kst": last_required_slot.get("run_before_kst"),
        "sample_target_reachable": sample_target_reachable,
        "distinct_hour_target_reachable": distinct_hour_target_reachable,
        "estimated_remaining_quote_samples_after_required_slots": max(missing_quote_samples - estimated_rows, 0),
        "estimated_remaining_distinct_hours_after_required_slots": max(missing_distinct_hours - len(required_unique_hours), 0),
        "warning_count": len(warnings),
        "warnings": warnings,
        "no_live_order_sent": True,
    }


def _timeline_completion_projection(
    *,
    generated_at: datetime,
    collection_forecast: dict[str, Any],
    collection_target_forecast: dict[str, Any],
    minimum_execution_plan: dict[str, Any],
) -> dict[str, Any]:
    generated_date = generated_at.astimezone(UTC).date()
    missing_samples = int(collection_forecast.get("minimum_additional_quote_samples") or 0)
    missing_days = int(collection_forecast.get("minimum_additional_calendar_days") or 0)
    missing_hours = int(collection_forecast.get("minimum_additional_distinct_hours") or 0)

    def scenario(name: str, rows_per_day: int, hours_per_day: int) -> dict[str, Any]:
        sample_days = _ceil_div(missing_samples, rows_per_day) if missing_samples > 0 else 0
        distinct_hour_days = _ceil_div(missing_hours, hours_per_day) if missing_hours > 0 else 0
        calendar_days = missing_days
        unprojectable: list[str] = []
        if missing_samples > 0 and sample_days is None:
            unprojectable.append("quote_samples")
        if missing_hours > 0 and distinct_hour_days is None:
            unprojectable.append("quote_distinct_hours")
        if unprojectable:
            projected_days = None
            projected_date = None
            dominant_gates = unprojectable
            status = "unprojectable_due_to_zero_collection_rate"
        else:
            projected_days = max(int(sample_days or 0), int(distinct_hour_days or 0), int(calendar_days or 0))
            projected_date = (generated_date + timedelta(days=projected_days)).isoformat()
            candidates = {
                "quote_samples": int(sample_days or 0),
                "quote_distinct_hours": int(distinct_hour_days or 0),
                "quote_calendar_days": int(calendar_days or 0),
            }
            dominant_gates = sorted(gate for gate, days in candidates.items() if days == projected_days and days > 0)
            status = "projected" if projected_days > 0 else "already_satisfied"
        return {
            "mode": name,
            "quote_rows_per_day": rows_per_day,
            "new_utc_hour_buckets_per_day": hours_per_day,
            "days_to_quote_sample_gate": sample_days,
            "days_to_distinct_hour_gate": distinct_hour_days,
            "days_to_calendar_day_gate": calendar_days,
            "projected_quote_gate_days": projected_days,
            "projected_quote_gate_date_utc": projected_date,
            "dominant_quote_gates": dominant_gates,
            "status": status,
        }

    minimum = scenario(
        "minimum_required_slots_daily",
        int(minimum_execution_plan.get("estimated_quote_rows_from_required_slots") or 0),
        int(minimum_execution_plan.get("required_unique_utc_hour_count") or 0),
    )
    full = scenario(
        "full_timeline_daily",
        int(collection_target_forecast.get("estimated_quote_rows_if_all_slots_run") or 0),
        int(collection_target_forecast.get("unique_utc_hour_slot_count") or 0),
    )
    min_days = minimum.get("projected_quote_gate_days")
    full_days = full.get("projected_quote_gate_days")
    days_saved = int(min_days) - int(full_days) if min_days is not None and full_days is not None else None
    if days_saved is None:
        recommendation = "fix_collection_rate_before_using_projection"
    elif days_saved > 0:
        recommendation = "run_full_timeline_when_possible_to_pull_forward_quote_gate"
    elif "quote_calendar_days" in list(full.get("dominant_quote_gates") or []):
        recommendation = "calendar_gate_dominates_run_minimum_slots_and_use_acceleration_as_buffer"
    else:
        recommendation = "minimum_required_slots_keep_same_projected_quote_gate_date"
    return {
        "status": "projected" if minimum.get("status") != "unprojectable_due_to_zero_collection_rate" else "unprojectable",
        "generated_date_utc": generated_date.isoformat(),
        "missing_quote_samples": missing_samples,
        "missing_quote_calendar_days": missing_days,
        "missing_quote_distinct_hours": missing_hours,
        "minimum_required_slots_daily": minimum,
        "full_timeline_daily": full,
        "days_saved_by_full_timeline_vs_minimum": days_saved,
        "recommendation": recommendation,
        "no_live_order_sent": True,
    }


def _evidence_collection_timeline(
    *,
    generated_at: datetime,
    collection_forecast: dict[str, Any],
    adaptive_collection_plan: dict[str, Any],
    signal_wait_plan: dict[str, Any],
    operator_runbook_plan: dict[str, Any],
    market_data_refresh_plan: dict[str, Any],
) -> dict[str, Any]:
    now = generated_at.astimezone(UTC)
    commands = dict(adaptive_collection_plan.get("operator_commands") or {})
    quote_operator_item = _operator_item_from_runbook(operator_runbook_plan, stage="shadow_evidence")
    signal_operator_item = _operator_item_from_runbook(operator_runbook_plan, stage="signal_monitor")
    quote_command = quote_operator_item.get("command") or commands.get("next_evidence_cycle")
    quote_missed_command = quote_operator_item.get("missed_window_command") or (
        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
        "--quote-samples-per-tick 0 --report-dir reports/validation/diagnostics/<missed_quote_window_recompute_report_dir>"
    )
    quote_slots: list[dict[str, Any]] = []
    seen_quote_starts: set[str] = set()

    def add_quote_slot(*, start: datetime, end: datetime | None, source: str, window_kind: str | None, reason: str | None) -> None:
        start = start.astimezone(UTC)
        end = end.astimezone(UTC) if end is not None else None
        start_key = start.isoformat()
        if start_key in seen_quote_starts:
            return
        seen_quote_starts.add(start_key)
        suggested_report_dir = _timeline_report_dir("quote_capture", start)
        quote_slots.append(
            {
                "source": source,
                "action": "run_quote_shadow_capture_for_evidence_window",
                "stage": "shadow_evidence",
                "run_at_or_after_utc": start_key,
                "run_at_or_after_kst": start.astimezone(KST).isoformat(),
                "run_before_utc": end.isoformat() if end is not None else None,
                "run_before_kst": end.astimezone(KST).isoformat() if end is not None else None,
                "wait_minutes": round(max((start - now).total_seconds(), 0.0) / 60.0, 4),
                "valid_duration_minutes": (
                    round(max((end - start).total_seconds(), 0.0) / 60.0, 4) if end is not None else None
                ),
                "window_kind": window_kind,
                "reason": reason,
                "command": quote_command,
                "missed_window_command": quote_missed_command,
                "suggested_report_dir": f"reports/validation/diagnostics/{suggested_report_dir}",
                "rendered_command": _render_timeline_command(quote_command, kind="quote_capture", value=start),
                "rendered_missed_window_command": _render_timeline_command(
                    quote_missed_command,
                    kind="quote_capture",
                    value=start,
                ),
                "no_live_order_sent": True,
            }
        )

    next_window = dict(adaptive_collection_plan.get("next_quote_evidence_window") or {})
    next_window_start = _parse_dt(next_window.get("at_utc"))
    next_window_end = _parse_dt(next_window.get("valid_until_utc"))
    if str(next_window.get("status") or "") in {"now", "wait"} and next_window_start is not None:
        add_quote_slot(
            start=next_window_start,
            end=next_window_end,
            source="next_quote_evidence_window",
            window_kind=next_window.get("window_kind"),
            reason=next_window.get("reason"),
        )

    daily_targets = dict(adaptive_collection_plan.get("daily_targets") or {})
    recommended_hours = list(
        daily_targets.get("recommended_utc_collection_hours")
        or collection_forecast.get("recommended_utc_collection_hours")
        or []
    )
    for value in recommended_hours[:8]:
        hour = _recommended_utc_hour_int(value)
        if hour is None:
            continue
        start, end = _future_utc_hour_window(generated_at=generated_at, hour=hour)
        add_quote_slot(
            start=start,
            end=end,
            source="recommended_missing_utc_hour_bucket",
            window_kind="missing_utc_hour_bucket",
            reason="spread_quote_shadow_collection_across_missing_utc_hours",
        )
    quote_slots.sort(key=lambda item: str(item.get("run_at_or_after_utc") or ""))

    signal_next = _parse_dt(signal_wait_plan.get("next_monitor_after_utc"))
    signal_monitor = None
    if signal_next is not None and signal_wait_plan.get("command"):
        signal_when = signal_next.astimezone(UTC)
        signal_monitor = {
            "action": "monitor_fresh_signal_without_quote_capture",
            "stage": "signal_monitor",
            "run_at_or_after_utc": signal_when.isoformat(),
            "run_at_or_after_kst": signal_next.astimezone(KST).isoformat(),
            "wait_minutes": round(max((signal_when - now).total_seconds(), 0.0) / 60.0, 4),
            "recommended_monitor_interval_minutes": signal_wait_plan.get("recommended_monitor_interval_minutes"),
            "cadence_lag_level": signal_wait_plan.get("cadence_lag_level"),
            "command": signal_operator_item.get("command") or signal_wait_plan.get("command"),
            "suggested_report_dir": f"reports/validation/diagnostics/{_timeline_report_dir('signal_monitor', signal_when)}",
            "rendered_command": _render_timeline_command(
                signal_operator_item.get("command") or signal_wait_plan.get("command"),
                kind="signal_monitor",
                value=signal_when,
            ),
            "manual_signal_override_allowed": signal_wait_plan.get("manual_signal_override_allowed") is True,
            "no_live_order_sent": True,
        }

    immediate_actions = []
    for urgency, key in (("required_now", "required_now_actions"), ("optional_now", "optional_now_actions")):
        for item in list(operator_runbook_plan.get(key) or []):
            item_command = dict(item).get("command")
            suggested_kind = str(dict(item).get("action") or urgency)
            immediate_actions.append(
                {
                    "urgency": urgency,
                    "run_at_or_after_utc": now.isoformat(),
                    "run_at_or_after_kst": now.astimezone(KST).isoformat(),
                    "suggested_report_dir": f"reports/validation/diagnostics/{_timeline_report_dir(suggested_kind, now)}",
                    "rendered_command": _render_timeline_command(item_command, kind=suggested_kind, value=now),
                    **_compact_operator_item(dict(item)),
                }
            )

    ordered_events: list[dict[str, Any]] = []
    for item in immediate_actions:
        ordered_events.append(
            {
                "kind": item["urgency"],
                "action": item.get("action"),
                "stage": item.get("stage"),
                "run_at_or_after_utc": item.get("run_at_or_after_utc"),
                "run_at_or_after_kst": item.get("run_at_or_after_kst"),
                "command": item.get("command"),
                "suggested_report_dir": item.get("suggested_report_dir"),
                "rendered_command": item.get("rendered_command"),
                "no_live_order_sent": True,
            }
        )
    if signal_monitor:
        ordered_events.append(
            {
                "kind": "signal_monitor",
                "action": signal_monitor.get("action"),
                "stage": signal_monitor.get("stage"),
                "run_at_or_after_utc": signal_monitor.get("run_at_or_after_utc"),
                "run_at_or_after_kst": signal_monitor.get("run_at_or_after_kst"),
                "command": signal_monitor.get("command"),
                "suggested_report_dir": signal_monitor.get("suggested_report_dir"),
                "rendered_command": signal_monitor.get("rendered_command"),
                "no_live_order_sent": True,
            }
        )
    for slot in quote_slots:
        ordered_events.append(
            {
                "kind": "quote_collection_slot",
                "action": slot.get("action"),
                "stage": slot.get("stage"),
                "run_at_or_after_utc": slot.get("run_at_or_after_utc"),
                "run_at_or_after_kst": slot.get("run_at_or_after_kst"),
                "run_before_utc": slot.get("run_before_utc"),
                "command": slot.get("command"),
                "suggested_report_dir": slot.get("suggested_report_dir"),
                "rendered_command": slot.get("rendered_command"),
                "no_live_order_sent": True,
            }
        )
    ordered_events.sort(
        key=lambda item: (
            str(item.get("run_at_or_after_utc") or ""),
            {"required_now": 0, "optional_now": 1, "signal_monitor": 2, "quote_collection_slot": 3}.get(
                str(item.get("kind") or ""),
                9,
            ),
        )
    )
    required_timeline_events = [
        item
        for item in ordered_events
        if str(item.get("kind") or "") in {"required_now", "signal_monitor", "quote_collection_slot"}
    ]
    command_manifest = _timeline_command_manifest(
        immediate_actions=immediate_actions,
        signal_monitor=signal_monitor,
        quote_slots=quote_slots,
    )
    command_validation = _timeline_command_validation(command_manifest)
    collection_target_forecast = _timeline_collection_target_forecast(
        collection_forecast=collection_forecast,
        adaptive_collection_plan=adaptive_collection_plan,
        quote_slots=quote_slots,
    )
    minimum_execution_plan = _timeline_minimum_execution_plan(
        collection_forecast=collection_forecast,
        collection_target_forecast=collection_target_forecast,
        quote_slots=quote_slots,
    )
    completion_projection = _timeline_completion_projection(
        generated_at=generated_at,
        collection_forecast=collection_forecast,
        collection_target_forecast=collection_target_forecast,
        minimum_execution_plan=minimum_execution_plan,
    )

    blocked_by_market_data = list(operator_runbook_plan.get("blocked_by_market_data_actions") or [])
    if blocked_by_market_data or market_data_refresh_plan.get("fresh_market_data") is not True:
        status = "blocked_until_market_data_refresh"
    elif quote_slots and signal_monitor:
        status = "active_quote_signal_timeline"
    elif quote_slots:
        status = "active_quote_collection_timeline"
    elif signal_monitor:
        status = "active_signal_monitor_timeline"
    else:
        status = "no_collection_timeline_required"

    return {
        "status": status,
        "generated_at": now.isoformat(),
        "horizon_hours": 24,
        "market_data_precondition": (
            "fresh" if market_data_refresh_plan.get("fresh_market_data") is True else "refresh_required"
        ),
        "immediate_actions": immediate_actions,
        "signal_monitor": signal_monitor,
        "quote_collection_slots": quote_slots,
        "quote_collection_slot_count": len(quote_slots),
        "next_quote_slot": quote_slots[0] if quote_slots else None,
        "next_timeline_event": ordered_events[0] if ordered_events else None,
        "next_required_timeline_event": required_timeline_events[0] if required_timeline_events else None,
        "ordered_timeline": ordered_events[:12],
        "required_timeline": required_timeline_events[:12],
        "command_manifest": command_manifest,
        "command_validation": command_validation,
        "collection_target_forecast": collection_target_forecast,
        "minimum_execution_plan": minimum_execution_plan,
        "completion_projection": completion_projection,
        "blocked_by_market_data_actions": [_compact_operator_item(dict(item)) for item in blocked_by_market_data],
        "operator_precautions": [
            "do_not_run_quote_capture_before_the_window_start",
            "use_quote_samples_per_tick_0_for_signal_monitor_or_recompute_only_runs",
            "do_not_enable_live_orders_from_evidence_timeline",
        ],
        "no_live_order_sent": True,
    }


def _summary(
    *,
    cycle_report: dict[str, Any],
    entry_audit: dict[str, Any],
    drought_audit: dict[str, Any],
    report_dir: Path,
    execution_parity_journal_report: dict[str, Any] | None = None,
    generated_at: datetime | None = None,
    max_signal_age_minutes: int = 15,
    min_shadow_fill_samples: int = 100,
    quote_cadence_preflight: dict[str, Any] | None = None,
    pre_apply_backup_dir: Path | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    collection = dict(cycle_report.get("collection") or {})
    readiness = dict(collection.get("readiness") or {})
    drought_classification = dict(drought_audit.get("classification") or {})
    entry_quality = dict(drought_audit.get("entry_quality") or {})
    apply_gate = _paper_apply_gate(cycle_report)
    collection_progress = _collection_progress(cycle_report)
    collection_progress.update(_execution_parity_collection_progress(execution_parity_journal_report))
    collection_forecast = _quote_collection_forecast(progress=collection_progress, generated_at=generated_at)
    readiness_progress = _readiness_progress(
        collection_progress=collection_progress,
        collection_forecast=collection_forecast,
        apply_gate=apply_gate,
        min_shadow_fill_samples=min_shadow_fill_samples,
    )
    execution_checklist = _execution_checklist(
        collection_progress=collection_progress,
        collection_forecast=collection_forecast,
        readiness_progress=readiness_progress,
        apply_gate=apply_gate,
        report_dir=report_dir,
    )
    base_next_actions = _evidence_next_actions(
        drought_audit=drought_audit,
        collection_forecast=collection_forecast,
        apply_gate=apply_gate,
    )
    report = {
        "generated_at": generated_at.isoformat(),
        "overall_status": drought_audit.get("status"),
        "no_live_order_sent": True,
        "decision_state": {
            "primary_cause": drought_classification.get("primary_cause"),
            "confidence": drought_classification.get("confidence"),
            "market_data_stale": drought_classification.get("market_data_stale"),
            "signal_stale": drought_classification.get("signal_stale"),
            "max_authorized_stage": readiness.get("max_authorized_stage"),
            "live_order_submission_allowed": readiness.get("live_order_submission_allowed"),
        },
        "collection_progress": collection_progress,
        "collection_forecast": collection_forecast,
        "quote_cadence_preflight": dict(quote_cadence_preflight or {}),
        "pre_apply_backup_plan": _pre_apply_backup_plan(
            apply_gate=apply_gate,
            pre_apply_backup_dir=pre_apply_backup_dir,
        ),
        "execution_parity_journal": {
            "status": dict(execution_parity_journal_report or {}).get("status"),
            "no_live_order_sent": dict(execution_parity_journal_report or {}).get("no_live_order_sent", True),
            "conversion": dict(dict(execution_parity_journal_report or {}).get("conversion") or {}),
            "collection_plan": dict(dict(execution_parity_journal_report or {}).get("collection_plan") or {}),
            "contract_summary": dict(dict(execution_parity_journal_report or {}).get("contract_summary") or {}),
            "contract_observed": dict(dict(execution_parity_journal_report or {}).get("contract_observed") or {}),
            "next_actions": list(dict(execution_parity_journal_report or {}).get("next_actions") or []),
        },
        "execution_parity_collection_plan": _execution_parity_collection_plan(
            collection_progress=collection_progress,
            apply_gate=apply_gate,
            journal_report=execution_parity_journal_report,
        ),
        "readiness_progress": readiness_progress,
        "execution_checklist": execution_checklist,
        "paper_bridge_apply_gate": apply_gate,
        "market_data_refresh_plan": _market_data_refresh_plan(cycle_report=cycle_report, apply_gate=apply_gate),
        "signal_wait_plan": _signal_wait_plan(
            cycle_report=cycle_report,
            apply_gate=apply_gate,
            generated_at=generated_at,
            max_signal_age_minutes=max_signal_age_minutes,
        ),
        "entry_quality": {
            "audit_status": entry_audit.get("status"),
            "recommended_experiment_scope": entry_quality.get("recommended_experiment_scope"),
            "eligible_probe_context_count": entry_quality.get("eligible_probe_context_count"),
            "rejected_soft_context_count": entry_quality.get("rejected_soft_context_count"),
            "mc04_broad_relaxation_rejected": entry_quality.get("mc04_broad_relaxation_rejected"),
        },
        "next_actions": base_next_actions,
        "report_paths": {
            "collection_cycle": _display_path(report_dir / "collection_cycle" / CYCLE_REPORT_NAME),
            "entry_sparsity_audit": _display_path(
                report_dir / "entry_filter_sparsity_audit" / "market_state_rotation_v6_entry_filter_sparsity_audit.json"
            ),
            "signal_drought_audit": _display_path(
                report_dir / "signal_drought_audit" / "market_state_rotation_v6_signal_drought_audit.json"
            ),
            "execution_parity_journal": _display_path(
                report_dir / "execution_parity_journal" / "market_state_rotation_v6_execution_parity_journal.json"
            ),
            "execution_parity_contract": _display_path(
                report_dir / "execution_parity_journal" / "market_state_rotation_v6_execution_parity_contract.json"
            ),
            "execution_parity_journal_jsonl": _display_path(
                report_dir / "execution_parity_journal" / EXECUTION_PARITY_JOURNAL_NAME
            ),
        },
        "non_negotiables": [
            "do_not_enable_live_orders_from_evidence_cycle",
            "do_not_apply_paper_bridge_without_fresh_v6_signal",
            "do_not_apply_paper_bridge_without_verified_pre_apply_backup",
            "do_not_relax_low_quality_soft_contexts_without_new_walk_forward_evidence",
        ],
    }
    report["readiness_trend"] = _readiness_trend(report=report, report_dir=report_dir)
    report["adaptive_collection_plan"] = _adaptive_collection_plan(
        generated_at=generated_at,
        collection_progress=collection_progress,
        collection_forecast=collection_forecast,
        readiness_progress=readiness_progress,
        readiness_trend=dict(report.get("readiness_trend") or {}),
        apply_gate=apply_gate,
        pre_apply_backup_plan=dict(report.get("pre_apply_backup_plan") or {}),
        quote_cadence_preflight=dict(report.get("quote_cadence_preflight") or {}),
        report_dir=report_dir,
    )
    report["next_actions"] = _adaptive_next_actions(
        base_actions=base_next_actions,
        adaptive_collection_plan=dict(report.get("adaptive_collection_plan") or {}),
        apply_gate=apply_gate,
        signal_wait_plan=dict(report.get("signal_wait_plan") or {}),
    )
    report["operator_action_plan"] = _operator_action_plan(
        adaptive_collection_plan=dict(report.get("adaptive_collection_plan") or {}),
        apply_gate=apply_gate,
        market_data_refresh_plan=dict(report.get("market_data_refresh_plan") or {}),
        pre_apply_backup_plan=dict(report.get("pre_apply_backup_plan") or {}),
        signal_wait_plan=dict(report.get("signal_wait_plan") or {}),
    )
    report["operator_runbook_plan"] = _operator_runbook_plan(
        operator_action_plan=dict(report.get("operator_action_plan") or {}),
        generated_at=generated_at,
    )
    report["evidence_collection_timeline"] = _evidence_collection_timeline(
        generated_at=generated_at,
        collection_forecast=dict(report.get("collection_forecast") or {}),
        adaptive_collection_plan=dict(report.get("adaptive_collection_plan") or {}),
        signal_wait_plan=dict(report.get("signal_wait_plan") or {}),
        operator_runbook_plan=dict(report.get("operator_runbook_plan") or {}),
        market_data_refresh_plan=dict(report.get("market_data_refresh_plan") or {}),
    )
    return report


def _markdown(report: dict[str, Any]) -> str:
    decision = dict(report.get("decision_state") or {})
    progress = dict(report.get("collection_progress") or {})
    forecast = dict(report.get("collection_forecast") or {})
    preflight = dict(report.get("quote_cadence_preflight") or {})
    readiness_progress = dict(report.get("readiness_progress") or {})
    trend = dict(report.get("readiness_trend") or {})
    collection_plan = dict(report.get("adaptive_collection_plan") or {})
    operator_plan = dict(report.get("operator_action_plan") or {})
    runbook = dict(report.get("operator_runbook_plan") or {})
    timeline = dict(report.get("evidence_collection_timeline") or {})
    timeline_next_event = dict(timeline.get("next_timeline_event") or {})
    timeline_next_required_event = dict(timeline.get("next_required_timeline_event") or {})
    timeline_signal = dict(timeline.get("signal_monitor") or {})
    timeline_command_validation = dict(timeline.get("command_validation") or {})
    timeline_collection_forecast = dict(timeline.get("collection_target_forecast") or {})
    timeline_minimum_execution = dict(timeline.get("minimum_execution_plan") or {})
    timeline_completion_projection = dict(timeline.get("completion_projection") or {})
    timeline_minimum_projection = dict(timeline_completion_projection.get("minimum_required_slots_daily") or {})
    timeline_full_projection = dict(timeline_completion_projection.get("full_timeline_daily") or {})
    top_operator_action = dict(operator_plan.get("top_action") or {})
    market_data_plan = dict(report.get("market_data_refresh_plan") or {})
    signal_wait_plan = dict(report.get("signal_wait_plan") or {})
    historical_replay = dict(report.get("historical_evidence_replay") or {})
    historical_aggregate = dict(historical_replay.get("aggregate_quote_gate") or {})
    historical_rolling = dict(historical_replay.get("rolling_window_confirmation") or {})
    historical_lifecycle = dict(report.get("historical_lifecycle_replay") or {})
    historical_lifecycle_selected = dict(historical_lifecycle.get("selected_candidate") or {})
    historical_substitution = dict(report.get("historical_gate_substitution") or {})
    execution_parity = dict(report.get("execution_parity_journal") or {})
    execution_parity_conversion = dict(execution_parity.get("conversion") or {})
    execution_parity_summary = dict(execution_parity.get("contract_summary") or {})
    execution_parity_plan = dict(report.get("execution_parity_collection_plan") or {})
    launch_readiness = dict(report.get("launch_readiness") or {})
    launch_next_blocker = dict(launch_readiness.get("next_blocker") or {})
    launch_canary_policy = dict(launch_readiness.get("canary_policy") or {})
    launch_paper_handoff = dict(launch_readiness.get("paper_bridge_handoff") or {})
    launch_components = dict(launch_readiness.get("component_readiness") or {})
    launch_substitution = dict(launch_readiness.get("substitution_matrix") or {})
    launch_resolution = dict(launch_readiness.get("resolution_matrix") or {})
    microstructure_substitution = dict(launch_substitution.get("microstructure_time_coverage") or {})
    launch_safety_controls = dict(report.get("launch_safety_controls") or {})
    checklist = dict(report.get("execution_checklist") or {})
    apply_gate = dict(report.get("paper_bridge_apply_gate") or {})
    pre_apply_backup = dict(report.get("pre_apply_backup_plan") or {})
    entry = dict(report.get("entry_quality") or {})
    lines = [
        "# Market State Rotation V6 Evidence Cycle",
        "",
        f"- status: `{report.get('overall_status')}`",
        f"- no_live_order_sent: `{report.get('no_live_order_sent')}`",
        f"- primary_cause: `{decision.get('primary_cause')}`",
        f"- confidence: `{decision.get('confidence')}`",
        f"- market_data_stale: `{decision.get('market_data_stale')}`",
        f"- market_data_refresh_status: `{market_data_plan.get('status')}`",
        f"- market_data_age_minutes: `{market_data_plan.get('market_data_age_minutes')}`",
        f"- market_data_stale_by_minutes: `{market_data_plan.get('stale_by_minutes')}`",
        f"- signal_stale: `{decision.get('signal_stale')}`",
        f"- signal_wait_status: `{signal_wait_plan.get('status')}`",
        f"- signal_age_hours: `{signal_wait_plan.get('signal_age_hours')}`",
        f"- latest_add_age_to_median_gap: `{signal_wait_plan.get('latest_add_age_to_median_gap')}`",
        f"- signal_cadence_lag_level: `{signal_wait_plan.get('cadence_lag_level')}`",
        f"- signal_cadence_recommended_monitor_interval_minutes: `{signal_wait_plan.get('cadence_recommended_monitor_interval_minutes')}`",
        f"- signal_recommended_monitor_interval_minutes: `{signal_wait_plan.get('recommended_monitor_interval_minutes')}`",
        f"- signal_freshness_capture_window_minutes: `{signal_wait_plan.get('signal_freshness_capture_window_minutes')}`",
        f"- signal_monitor_interval_capped_by_freshness: `{signal_wait_plan.get('monitor_interval_capped_by_signal_freshness')}`",
        f"- signal_monitor_age_alignment: `{signal_wait_plan.get('monitor_signal_age_alignment')}`",
        f"- signal_next_monitor_after_utc: `{signal_wait_plan.get('next_monitor_after_utc')}`",
        f"- max_authorized_stage: `{decision.get('max_authorized_stage')}`",
        f"- live_order_submission_allowed: `{decision.get('live_order_submission_allowed')}`",
        f"- quote_samples: `{progress.get('quote_observed')}/{progress.get('quote_required')}`",
        f"- quote_missing_samples: `{progress.get('quote_missing_samples')}`",
        f"- quote_days: `{progress.get('quote_calendar_days')}/{progress.get('quote_min_calendar_days')}`",
        f"- quote_missing_calendar_days: `{progress.get('quote_missing_calendar_days')}`",
        f"- quote_hours: `{progress.get('quote_distinct_hours')}/{progress.get('quote_min_distinct_hours')}`",
        f"- quote_missing_distinct_hours: `{progress.get('quote_missing_distinct_hours')}`",
        f"- captured_quote_rows_this_cycle: `{progress.get('captured_quote_rows_this_cycle')}`",
        f"- quote_cadence_decision: `{preflight.get('decision')}`",
        f"- effective_quote_samples_per_tick: `{preflight.get('effective_quote_samples_per_tick')}`",
        f"- dominant_collection_blocker: `{progress.get('dominant_collection_blocker')}`",
        f"- quote_evidence_readiness_pct: `{readiness_progress.get('quote_evidence_readiness_pct')}`",
        f"- shadow_promotion_readiness_pct: `{readiness_progress.get('shadow_promotion_readiness_pct')}`",
        f"- paper_apply_readiness_pct: `{readiness_progress.get('paper_apply_readiness_pct')}`",
        f"- execution_parity_status: `{execution_parity.get('status')}`",
        f"- execution_parity_journal_rows: `{progress.get('execution_parity_journal_rows')}/{progress.get('execution_parity_required_rows')}`",
        f"- execution_parity_missing_samples: `{progress.get('execution_parity_missing_samples')}`",
        f"- execution_parity_contract_passed: `{execution_parity_summary.get('passed')}`",
        f"- execution_parity_blockers: `{execution_parity_summary.get('blockers')}`",
        f"- execution_parity_lifecycle_rows: `{execution_parity_conversion.get('lifecycle_row_count')}`",
        f"- execution_parity_collection_status: `{execution_parity_plan.get('status')}`",
        f"- execution_parity_events_needed: `{execution_parity_plan.get('estimated_future_paper_apply_events_needed')}`",
        f"- execution_parity_creditable_actions: `{execution_parity_plan.get('currently_creditable_actions')}`",
        f"- execution_parity_next_step: `{execution_parity_plan.get('next_step')}`",
        f"- strictest_deployment_gate: `{readiness_progress.get('strictest_deployment_gate')}`",
        f"- current_phase: `{checklist.get('current_phase')}`",
        f"- paper_apply_allowed_now: `{checklist.get('paper_apply_allowed_now')}`",
        f"- pre_apply_backup_status: `{pre_apply_backup.get('status')}`",
        f"- pre_apply_backup_required: `{pre_apply_backup.get('required')}`",
        f"- pre_apply_backup_dir: `{pre_apply_backup.get('backup_dir')}`",
        f"- pre_apply_backup_verification_required: `{pre_apply_backup.get('verification_required')}`",
        f"- shadow_promotion_ready: `{checklist.get('shadow_promotion_ready')}`",
        f"- next_unblocked_operator_step: `{readiness_progress.get('next_unblocked_operator_step')}`",
        f"- readiness_trend_status: `{trend.get('status')}`",
        f"- latest_quote_sample_delta: `{dict(trend.get('latest_delta') or {}).get('quote_observed')}`",
        f"- cycles_to_quote_sample_completion_at_latest_delta: `{trend.get('cycles_to_quote_sample_completion_at_latest_delta')}`",
        f"- adaptive_primary_objective: `{collection_plan.get('primary_objective')}`",
        f"- useful_to_run_now: `{collection_plan.get('useful_to_run_now')}`",
        f"- advances_quote_evidence_now: `{collection_plan.get('advances_quote_evidence_now')}`",
        f"- next_quote_window_utc: `{dict(collection_plan.get('next_quote_evidence_window') or {}).get('at_utc')}`",
        f"- next_quote_window_kst: `{dict(collection_plan.get('next_quote_evidence_window') or {}).get('at_kst')}`",
        f"- next_quote_window_wait_minutes: `{dict(collection_plan.get('next_quote_evidence_window') or {}).get('wait_minutes')}`",
        f"- same_utc_hour_repeat_allowed: `{dict(collection_plan.get('same_utc_hour_repeat_policy') or {}).get('allowed')}`",
        f"- operator_action_status: `{operator_plan.get('status')}`",
        f"- operator_runbook_status: `{runbook.get('status')}`",
        f"- operator_runbook_coordination_rule: `{runbook.get('coordination_rule')}`",
        f"- operator_runbook_coordination_warning_count: `{runbook.get('coordination_warning_count')}`",
        f"- operator_runbook_required_now_action_count: `{runbook.get('required_now_action_count')}`",
        f"- operator_runbook_optional_now_action_count: `{runbook.get('optional_now_action_count')}`",
        f"- operator_runbook_run_now_action_count: `{runbook.get('run_now_action_count')}`",
        f"- operator_runbook_expired_action_count: `{runbook.get('expired_action_count')}`",
        f"- operator_runbook_due_now_action_count: `{runbook.get('due_now_action_count')}`",
        f"- operator_runbook_scheduled_action_count: `{runbook.get('scheduled_action_count')}`",
        f"- operator_runbook_blocked_by_market_data_action_count: `{runbook.get('blocked_by_market_data_action_count')}`",
        f"- evidence_timeline_status: `{timeline.get('status')}`",
        f"- evidence_timeline_market_data_precondition: `{timeline.get('market_data_precondition')}`",
        f"- evidence_timeline_quote_slot_count: `{timeline.get('quote_collection_slot_count')}`",
        f"- evidence_timeline_signal_next_utc: `{timeline_signal.get('run_at_or_after_utc')}`",
        f"- evidence_timeline_next_event: `{timeline_next_event.get('action')}`",
        f"- evidence_timeline_next_required_event: `{timeline_next_required_event.get('action')}`",
        f"- evidence_timeline_command_validation_status: `{timeline_command_validation.get('status')}`",
        f"- evidence_timeline_command_issue_count: `{timeline_command_validation.get('issue_count')}`",
        f"- evidence_timeline_command_count: `{timeline_command_validation.get('command_count')}`",
        f"- evidence_timeline_collection_target_status: `{timeline_collection_forecast.get('status')}`",
        f"- evidence_timeline_estimated_quote_rows: `{timeline_collection_forecast.get('estimated_quote_rows_if_all_slots_run')}`",
        f"- evidence_timeline_sample_target_covered: `{timeline_collection_forecast.get('sample_target_covered')}`",
        f"- evidence_timeline_distinct_hour_target_covered: `{timeline_collection_forecast.get('distinct_hour_target_covered')}`",
        f"- evidence_timeline_minimum_execution_status: `{timeline_minimum_execution.get('status')}`",
        f"- evidence_timeline_required_quote_slot_count: `{timeline_minimum_execution.get('required_quote_slot_count')}`",
        f"- evidence_timeline_optional_acceleration_slot_count: `{timeline_minimum_execution.get('optional_acceleration_slot_count')}`",
        f"- evidence_timeline_completion_projection_status: `{timeline_completion_projection.get('status')}`",
        f"- evidence_timeline_minimum_projected_quote_gate_days: `{timeline_minimum_projection.get('projected_quote_gate_days')}`",
        f"- evidence_timeline_full_projected_quote_gate_days: `{timeline_full_projection.get('projected_quote_gate_days')}`",
        f"- evidence_timeline_days_saved_by_full_timeline: `{timeline_completion_projection.get('days_saved_by_full_timeline_vs_minimum')}`",
        f"- evidence_timeline_projection_recommendation: `{timeline_completion_projection.get('recommendation')}`",
        f"- historical_replay_status: `{historical_replay.get('status')}`",
        f"- historical_replay_source: `{historical_replay.get('source_path')}`",
        f"- historical_replay_proxy_samples: `{historical_aggregate.get('proxy_quote_samples')}`",
        f"- historical_replay_calendar_days: `{historical_aggregate.get('calendar_day_count')}`",
        f"- historical_replay_distinct_hours: `{historical_aggregate.get('distinct_utc_hour_count')}`",
        f"- historical_replay_rolling_pass_rate_pct: `{historical_rolling.get('pass_rate_pct')}`",
        f"- historical_lifecycle_status: `{historical_lifecycle.get('status')}`",
        f"- historical_lifecycle_source: `{historical_lifecycle.get('source_path')}`",
        f"- historical_lifecycle_proxy_rows: `{historical_lifecycle.get('proxy_lifecycle_rows')}`",
        f"- historical_lifecycle_required_rows: `{historical_lifecycle.get('required_shadow_fill_samples')}`",
        f"- historical_lifecycle_proxy_passed: `{historical_lifecycle.get('paper_shadow_fill_samples_passed')}`",
        f"- historical_lifecycle_selected_candidate: `{historical_lifecycle_selected.get('name')}`",
        f"- historical_realtime_quote_wait_replaced: `{historical_substitution.get('realtime_quote_wait_replaced')}`",
        f"- historical_paper_shadow_fill_proxy_replaced: `{historical_substitution.get('paper_shadow_fill_proxy_replaced')}`",
        f"- historical_realtime_wait_days_removed: `{historical_substitution.get('realtime_wait_days_removed')}`",
        f"- historical_strictest_gate_after_substitution: `{historical_substitution.get('strictest_deployment_gate_after_substitution')}`",
        f"- historical_research_shadow_promotion_readiness_pct: `{historical_substitution.get('research_shadow_promotion_readiness_pct_after_substitution')}`",
        f"- launch_readiness_status: `{launch_readiness.get('status')}`",
        f"- launch_effective_research_status: `{launch_readiness.get('effective_research_status')}`",
        f"- launch_resolution_status: `{launch_resolution.get('status')}`",
        f"- launch_backtest_substitution_exhausted: `{launch_resolution.get('backtest_substitution_exhausted')}`",
        f"- launch_non_substitutable_remaining_gates: `{launch_resolution.get('non_substitutable_remaining_gates')}`",
        f"- launch_no_live_actionable_remaining_gates: `{launch_resolution.get('no_live_actionable_remaining_gates')}`",
        f"- launch_no_live_progressable_remaining_gates: `{launch_resolution.get('no_live_progressable_remaining_gates')}`",
        f"- launch_substituted_time_wait_removed_days: `{launch_readiness.get('substituted_time_wait_removed_days')}`",
        f"- launch_substituted_research_readiness_pct: `{launch_readiness.get('substituted_research_readiness_pct')}`",
        f"- launch_research_ready: `{launch_readiness.get('research_ready')}`",
        f"- launch_shadow_ready: `{launch_readiness.get('shadow_ready')}`",
        f"- launch_paper_operational_ready: `{launch_readiness.get('paper_operational_ready')}`",
        f"- launch_tiny_canary_evidence_ready: `{launch_readiness.get('tiny_canary_evidence_ready')}`",
        f"- launch_tiny_canary_order_submission_allowed: `{launch_readiness.get('tiny_canary_order_submission_allowed')}`",
        f"- launch_quote_time_proxy_ready: `{launch_components.get('quote_time_proxy_ready')}`",
        f"- launch_microstructure_metric_ready: `{launch_components.get('microstructure_metric_ready')}`",
        f"- launch_microstructure_time_proxy_ready: `{launch_components.get('microstructure_time_proxy_ready')}`",
        f"- launch_microstructure_proxy_scope: `{microstructure_substitution.get('scope')}`",
        f"- launch_real_microstructure_ready: `{launch_components.get('real_microstructure_ready')}`",
        f"- launch_next_blocker: `{launch_next_blocker.get('gate')}`",
        f"- launch_next_blocker_action: `{launch_next_blocker.get('next_action')}`",
        f"- launch_shadow_runtime_observed_hours: `{launch_canary_policy.get('observed_shadow_runtime_hours')}`",
        f"- launch_shadow_runtime_required_hours: `{launch_canary_policy.get('requires_shadow_runtime_hours')}`",
        f"- launch_canary_risk_caps_status: `{launch_canary_policy.get('config_status')}`",
        f"- launch_canary_risk_caps_source: `{launch_canary_policy.get('config_source')}`",
        f"- launch_canary_risk_caps_errors: `{launch_canary_policy.get('config_errors')}`",
        f"- launch_safety_controls_status: `{launch_safety_controls.get('overall_status')}`",
        f"- launch_safety_controls_verified: `{launch_safety_controls.get('verified_count')}/{launch_safety_controls.get('required_count')}`",
        f"- launch_safety_controls_missing: `{launch_safety_controls.get('missing_or_failed')}`",
        f"- launch_paper_bridge_handoff_status: `{launch_paper_handoff.get('status')}`",
        f"- launch_paper_bridge_apply_allowed_now: `{launch_paper_handoff.get('apply_allowed_now')}`",
        f"- launch_paper_bridge_pre_apply_backup_status: `{dict(launch_paper_handoff.get('pre_apply_backup_plan') or {}).get('status')}`",
        f"- top_operator_action: `{top_operator_action.get('action')}`",
        f"- top_operator_action_run_now: `{top_operator_action.get('run_now')}`",
        f"- top_operator_action_execute_after_utc: `{top_operator_action.get('execute_after_utc')}`",
        f"- top_operator_action_execute_before_utc: `{top_operator_action.get('execute_before_utc')}`",
        f"- top_operator_action_window_kind: `{top_operator_action.get('window_kind')}`",
        f"- top_operator_action_window_urgency: `{top_operator_action.get('window_urgency')}`",
        f"- top_operator_action_missed_window_next_step: `{top_operator_action.get('missed_window_next_step')}`",
        f"- recommended_min_quote_samples_per_remaining_day: `{forecast.get('recommended_min_quote_samples_per_remaining_day')}`",
        f"- recommended_min_evidence_cycles_per_remaining_day: `{forecast.get('recommended_min_evidence_cycles_per_remaining_day')}`",
        f"- target_next_utc_hour_of_day: `{forecast.get('target_next_utc_hour_of_day')}`",
        f"- target_next_kst_hour_of_day: `{forecast.get('target_next_kst_hour_of_day')}`",
        f"- earliest_quote_calendar_gate_date_utc: `{forecast.get('earliest_quote_calendar_gate_date_utc')}`",
        f"- paper_apply_gate: `{apply_gate.get('status')}`",
        f"- can_request_paper_apply_now: `{apply_gate.get('can_request_paper_apply_now')}`",
        f"- entry_scope: `{entry.get('recommended_experiment_scope')}`",
        f"- eligible_probe_context_count: `{entry.get('eligible_probe_context_count')}`",
        "",
        "## Next Actions",
        "",
    ]
    for action in list(report.get("next_actions") or []):
        lines.append(f"- {action}")
    return "\n".join(lines) + "\n"


def run_evidence_cycle(
    *,
    source_backtest_report_path: Path,
    stress_report_path: Path,
    walk_forward_report_path: Path,
    manual_evidence_path: Path | None,
    sample_jsonl: Path,
    report_dir: Path,
    apply_paper_bridge: bool = False,
    pre_apply_backup_dir: Path | None = _resolve(DEFAULT_PRE_APPLY_BACKUP_DIR),
    symbol: str = EXPECTED_SYMBOL,
    bridge_days: int = 120,
    bridge_load_days: int = 0,
    max_signal_age_minutes: int = 15,
    max_market_data_age_minutes: int = 30,
    plan_valid_minutes: int = 15,
    quote_samples_per_tick: int = 1,
    quote_sample_sleep_seconds: float = 0.0,
    adaptive_quote_cadence: bool = True,
    force_quote_sample: bool = False,
    required_quote_samples: int = 300,
    min_quote_calendar_days: int = 30,
    min_quote_distinct_hours: int = 24,
    min_shadow_fill_samples: int = 100,
    lifecycle_days: int = 30,
    lifecycle_limit: int = 500,
    refresh_market_data_before_run: bool = False,
    historical_evidence_replay: bool = False,
    historical_replay_source_path: Path | None = None,
    historical_replay_days: int = 1095,
    historical_lifecycle_replay: bool = False,
    historical_lifecycle_source_path: Path | None = None,
    canary_max_notional_usdt: float = 0.0,
    canary_max_leverage: float = 10.0,
    canary_max_daily_loss_usdt: float = 0.0,
    canary_risk_caps_path: Path | None = None,
    allow_canary_without_real_paper_rows: bool = False,
    shadow_runtime_observed_hours: float = 0.0,
    shadow_runtime_required_hours: float = 24.0,
) -> dict[str, Any]:
    report_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC)
    pre_run_market_data_refresh: dict[str, Any] = {}
    if refresh_market_data_before_run:
        pre_run_market_data_refresh = _refresh_runtime_market_data_cache(
            report_dir=report_dir,
            generated_at=generated_at,
        )
    quote_preflight = _quote_cadence_preflight(
        sample_jsonl=sample_jsonl,
        requested_quote_samples_per_tick=max(0, int(quote_samples_per_tick)),
        required_quote_samples=required_quote_samples,
        min_quote_calendar_days=min_quote_calendar_days,
        min_quote_distinct_hours=min_quote_distinct_hours,
        symbol=str(symbol or EXPECTED_SYMBOL).upper(),
        generated_at=generated_at,
        adaptive_quote_cadence=bool(adaptive_quote_cadence),
        force_quote_sample=bool(force_quote_sample),
    )
    cycle_dir = report_dir / "collection_cycle"
    cycle_report = run_collection_cycle(
        source_backtest_report_path=source_backtest_report_path,
        stress_report_path=stress_report_path,
        walk_forward_report_path=walk_forward_report_path,
        manual_evidence_path=manual_evidence_path,
        sample_jsonl=sample_jsonl,
        report_dir=cycle_dir,
        apply_paper_bridge=bool(apply_paper_bridge),
        pre_apply_backup_dir=pre_apply_backup_dir,
        require_pre_apply_backup=True,
        symbol=symbol,
        bridge_days=bridge_days,
        bridge_load_days=bridge_load_days,
        max_signal_age_minutes=max_signal_age_minutes,
        max_market_data_age_minutes=max_market_data_age_minutes,
        plan_valid_minutes=plan_valid_minutes,
        quote_samples_per_tick=int(quote_preflight.get("effective_quote_samples_per_tick") or 0),
        quote_sample_sleep_seconds=quote_sample_sleep_seconds,
        required_quote_samples=required_quote_samples,
        min_quote_calendar_days=min_quote_calendar_days,
        min_quote_distinct_hours=min_quote_distinct_hours,
        min_shadow_fill_samples=min_shadow_fill_samples,
        lifecycle_days=lifecycle_days,
        lifecycle_limit=lifecycle_limit,
    )
    entry_audit = build_entry_filter_sparsity_audit(
        cycle_report,
        input_cycle_report=_display_path(cycle_dir / CYCLE_REPORT_NAME),
    )
    entry_dir = report_dir / "entry_filter_sparsity_audit"
    _write_json(entry_dir / "market_state_rotation_v6_entry_filter_sparsity_audit.json", entry_audit)
    _write_text(
        entry_dir / "market_state_rotation_v6_entry_filter_sparsity_audit.md",
        "# Market State Rotation V6 Entry Filter Sparsity Audit\n\n"
        f"- status: `{entry_audit.get('status')}`\n"
        f"- no_live_order_sent: `{entry_audit.get('no_live_order_sent')}`\n",
    )
    drought_audit = build_signal_drought_audit(
        cycle_report,
        entry_audit,
        input_cycle_report=_display_path(cycle_dir / CYCLE_REPORT_NAME),
        input_entry_sparsity_audit=_display_path(
            entry_dir / "market_state_rotation_v6_entry_filter_sparsity_audit.json"
        ),
    )
    drought_dir = report_dir / "signal_drought_audit"
    _write_json(drought_dir / "market_state_rotation_v6_signal_drought_audit.json", drought_audit)
    _write_text(
        drought_dir / "market_state_rotation_v6_signal_drought_audit.md",
        "# Market State Rotation V6 Signal Drought Audit\n\n"
        f"- status: `{drought_audit.get('status')}`\n"
        f"- no_live_order_sent: `{drought_audit.get('no_live_order_sent')}`\n",
    )
    execution_parity_dir = report_dir / "execution_parity_journal"
    execution_parity_journal_path = execution_parity_dir / EXECUTION_PARITY_JOURNAL_NAME
    lifecycle_export_path = cycle_dir / "collection_tick" / "market_state_rotation_v6_shadow_fill_export.json"
    lifecycle_payload = _load_json_if_exists(lifecycle_export_path) or {"rows": []}
    walk_report = _load_json_if_exists(walk_forward_report_path) or {}
    execution_parity_journal_report, execution_parity_journal_rows = build_execution_parity_journal_report(
        walk_report=walk_report,
        lifecycle_payload=lifecycle_payload,
        input_walk_report=_display_path(walk_forward_report_path),
        input_lifecycle_report=_display_path(lifecycle_export_path) if lifecycle_export_path.exists() else None,
        input_execution_journal=_display_path(execution_parity_journal_path),
        symbol=str(symbol or EXPECTED_SYMBOL).upper(),
        strategy_family="market_state_rotation_v6",
        interval_minutes=5,
        min_sample_count=20,
        include_exit_rows=True,
        generated_at=generated_at,
    )
    _write_jsonl(execution_parity_journal_path, execution_parity_journal_rows)
    _write_json(
        execution_parity_dir / "market_state_rotation_v6_execution_parity_journal.json",
        execution_parity_journal_report,
    )
    _write_json(
        execution_parity_dir / "market_state_rotation_v6_execution_parity_contract.json",
        dict(execution_parity_journal_report.get("contract_report") or {}),
    )
    _write_text(
        execution_parity_dir / "market_state_rotation_v6_execution_parity_journal.md",
        _execution_parity_markdown(execution_parity_journal_report),
    )
    report = _summary(
        cycle_report=cycle_report,
        entry_audit=entry_audit,
        drought_audit=drought_audit,
        execution_parity_journal_report=execution_parity_journal_report,
        report_dir=report_dir,
        generated_at=generated_at,
        max_signal_age_minutes=max_signal_age_minutes,
        min_shadow_fill_samples=min_shadow_fill_samples,
        quote_cadence_preflight=quote_preflight,
        pre_apply_backup_dir=pre_apply_backup_dir,
    )
    report["pre_run_market_data_refresh"] = pre_run_market_data_refresh
    if pre_run_market_data_refresh:
        report["report_paths"]["pre_run_market_data_refresh"] = pre_run_market_data_refresh.get("report_dir")
    if historical_evidence_replay or historical_lifecycle_replay:
        replay: dict[str, Any] = {}
        lifecycle_replay: dict[str, Any] = {}
    if historical_evidence_replay:
        replay = _historical_evidence_replay(
            source_path=historical_replay_source_path or _resolve(DEFAULT_HISTORICAL_REPLAY_SOURCE),
            generated_at=generated_at,
            replay_days=max(1, int(historical_replay_days or 1)),
            required_quote_samples=required_quote_samples,
            min_quote_calendar_days=min_quote_calendar_days,
            min_quote_distinct_hours=min_quote_distinct_hours,
            symbol=str(symbol or EXPECTED_SYMBOL).upper(),
        )
        report["historical_evidence_replay"] = replay
        report["report_paths"]["historical_evidence_replay"] = _display_path(
            report_dir / "historical_evidence_replay.json"
        )
        _write_json(report_dir / "historical_evidence_replay.json", replay)
    if historical_lifecycle_replay:
        lifecycle_replay = _historical_lifecycle_replay(
            source_path=historical_lifecycle_source_path or _resolve(DEFAULT_HISTORICAL_LIFECYCLE_REPLAY_SOURCE),
            generated_at=generated_at,
            min_shadow_fill_samples=min_shadow_fill_samples,
        )
        report["historical_lifecycle_replay"] = lifecycle_replay
        report["report_paths"]["historical_lifecycle_replay"] = _display_path(
            report_dir / "historical_lifecycle_replay.json"
        )
        _write_json(report_dir / "historical_lifecycle_replay.json", lifecycle_replay)
    if historical_evidence_replay:
        substitution = _historical_gate_substitution(
            collection_progress=dict(report.get("collection_progress") or {}),
            readiness_progress=dict(report.get("readiness_progress") or {}),
            historical_replay=replay,
            historical_lifecycle_replay=lifecycle_replay,
        )
        report["historical_gate_substitution"] = substitution
        report["report_paths"]["historical_gate_substitution"] = _display_path(
            report_dir / "historical_gate_substitution.json"
        )
        _write_json(report_dir / "historical_gate_substitution.json", substitution)
    canary_risk_caps_config = load_canary_risk_caps_config(
        path=canary_risk_caps_path,
        cli_max_notional_usdt=max(0.0, float(canary_max_notional_usdt or 0.0)),
        cli_max_leverage=max(0.0, float(canary_max_leverage or 0.0)),
        cli_max_daily_loss_usdt=max(0.0, float(canary_max_daily_loss_usdt or 0.0)),
    )
    canary_effective = dict(canary_risk_caps_config.get("effective") or {})
    report["canary_risk_caps_config"] = canary_risk_caps_config
    report["report_paths"]["canary_risk_caps_config"] = _display_path(report_dir / "canary_risk_caps_config.json")
    _write_json(report_dir / "canary_risk_caps_config.json", canary_risk_caps_config)
    manual_safety_evidence = _load_json_if_exists(manual_evidence_path)
    launch_safety_controls = build_safety_controls_report(
        manual_safety_evidence,
        now=generated_at,
        max_evidence_age_days=7,
    )
    if manual_evidence_path is not None:
        launch_safety_controls["input_evidence"] = _display_path(manual_evidence_path)
    report["launch_safety_controls"] = launch_safety_controls
    report["report_paths"]["launch_safety_controls"] = _display_path(report_dir / "launch_safety_controls.json")
    _write_json(report_dir / "launch_safety_controls.json", launch_safety_controls)
    launch_readiness = _launch_readiness_state_machine(
        report=report,
        generated_at=generated_at,
        canary_max_notional_usdt=max(0.0, float(canary_effective.get("max_notional_usdt") or 0.0)),
        canary_max_leverage=max(0.0, float(canary_effective.get("max_leverage") or 0.0)),
        canary_max_daily_loss_usdt=max(0.0, float(canary_effective.get("max_daily_loss_usdt") or 0.0)),
        require_real_paper_rows_for_canary=not bool(allow_canary_without_real_paper_rows),
        shadow_runtime_observed_hours=max(0.0, float(shadow_runtime_observed_hours or 0.0)),
        shadow_runtime_required_hours=max(0.0, float(shadow_runtime_required_hours or 0.0)),
    )
    report["launch_readiness"] = launch_readiness
    report["report_paths"]["launch_readiness"] = _display_path(report_dir / "launch_readiness.json")
    _write_json(report_dir / "launch_readiness.json", launch_readiness)
    _write_json(report_dir / EVIDENCE_REPORT_NAME, report)
    _write_text(report_dir / "market_state_rotation_v6_evidence_cycle.md", _markdown(report))
    report["report_dir"] = _display_path(report_dir)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run v6 collection cycle plus entry and drought audits.")
    parser.add_argument("--source-backtest-report", default=DEFAULT_SOURCE_BACKTEST_REPORT)
    parser.add_argument("--stress-report", default=DEFAULT_STRESS_REPORT)
    parser.add_argument("--walk-forward-report", default=DEFAULT_WALK_FORWARD_REPORT)
    parser.add_argument("--manual-safety-evidence", default=DEFAULT_MANUAL_EVIDENCE)
    parser.add_argument("--sample-jsonl", default=DEFAULT_SAMPLE_PATH)
    parser.add_argument("--report-dir", default=DEFAULT_EVIDENCE_REPORT_DIR)
    parser.add_argument("--apply-paper-bridge", action="store_true")
    parser.add_argument("--pre-apply-backup-dir", default=DEFAULT_PRE_APPLY_BACKUP_DIR)
    parser.add_argument("--symbol", default=EXPECTED_SYMBOL)
    parser.add_argument("--bridge-days", type=int, default=120)
    parser.add_argument("--bridge-load-days", type=int, default=0)
    parser.add_argument("--max-signal-age-minutes", type=int, default=15)
    parser.add_argument("--max-market-data-age-minutes", type=int, default=30)
    parser.add_argument("--plan-valid-minutes", type=int, default=15)
    parser.add_argument("--quote-samples-per-tick", type=int, default=1)
    parser.add_argument("--quote-sample-sleep-seconds", type=float, default=0.0)
    parser.add_argument("--disable-adaptive-quote-cadence", action="store_true")
    parser.add_argument("--force-quote-sample", action="store_true")
    parser.add_argument("--required-quote-samples", type=int, default=300)
    parser.add_argument("--min-quote-calendar-days", type=int, default=30)
    parser.add_argument("--min-quote-distinct-hours", type=int, default=24)
    parser.add_argument("--min-shadow-fill-samples", type=int, default=100)
    parser.add_argument("--lifecycle-days", type=int, default=30)
    parser.add_argument("--lifecycle-limit", type=int, default=500)
    parser.add_argument("--refresh-market-data-before-run", action="store_true")
    parser.add_argument("--historical-evidence-replay", action="store_true")
    parser.add_argument("--historical-replay-source", default=DEFAULT_HISTORICAL_REPLAY_SOURCE)
    parser.add_argument("--historical-replay-days", type=int, default=1095)
    parser.add_argument("--historical-lifecycle-replay", action="store_true")
    parser.add_argument("--historical-lifecycle-source", default=DEFAULT_HISTORICAL_LIFECYCLE_REPLAY_SOURCE)
    parser.add_argument("--canary-max-notional-usdt", type=float, default=0.0)
    parser.add_argument("--canary-max-leverage", type=float, default=10.0)
    parser.add_argument("--canary-max-daily-loss-usdt", type=float, default=0.0)
    parser.add_argument("--canary-risk-caps-json", default=DEFAULT_CANARY_RISK_CAPS_PATH)
    parser.add_argument("--allow-canary-without-real-paper-rows", action="store_true")
    parser.add_argument("--shadow-runtime-observed-hours", type=float, default=0.0)
    parser.add_argument("--shadow-runtime-required-hours", type=float, default=24.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manual_path = _resolve(args.manual_safety_evidence) if args.manual_safety_evidence else None
    report = run_evidence_cycle(
        source_backtest_report_path=_resolve(args.source_backtest_report),
        stress_report_path=_resolve(args.stress_report),
        walk_forward_report_path=_resolve(args.walk_forward_report),
        manual_evidence_path=manual_path,
        sample_jsonl=_resolve(args.sample_jsonl),
        report_dir=_resolve(args.report_dir),
        apply_paper_bridge=bool(args.apply_paper_bridge),
        pre_apply_backup_dir=_resolve(args.pre_apply_backup_dir),
        symbol=str(args.symbol or EXPECTED_SYMBOL).upper(),
        bridge_days=max(1, int(args.bridge_days)),
        bridge_load_days=max(0, int(args.bridge_load_days)),
        max_signal_age_minutes=max(1, int(args.max_signal_age_minutes)),
        max_market_data_age_minutes=max(1, int(args.max_market_data_age_minutes)),
        plan_valid_minutes=max(1, int(args.plan_valid_minutes)),
        quote_samples_per_tick=max(0, int(args.quote_samples_per_tick)),
        quote_sample_sleep_seconds=max(0.0, float(args.quote_sample_sleep_seconds)),
        adaptive_quote_cadence=not bool(args.disable_adaptive_quote_cadence),
        force_quote_sample=bool(args.force_quote_sample),
        required_quote_samples=max(1, int(args.required_quote_samples)),
        min_quote_calendar_days=max(1, int(args.min_quote_calendar_days)),
        min_quote_distinct_hours=max(1, int(args.min_quote_distinct_hours)),
        min_shadow_fill_samples=max(1, int(args.min_shadow_fill_samples)),
        lifecycle_days=max(1, int(args.lifecycle_days)),
        lifecycle_limit=max(1, int(args.lifecycle_limit)),
        refresh_market_data_before_run=bool(args.refresh_market_data_before_run),
        historical_evidence_replay=bool(args.historical_evidence_replay),
        historical_replay_source_path=_resolve(args.historical_replay_source),
        historical_replay_days=max(1, int(args.historical_replay_days)),
        historical_lifecycle_replay=bool(args.historical_lifecycle_replay),
        historical_lifecycle_source_path=_resolve(args.historical_lifecycle_source),
        canary_max_notional_usdt=max(0.0, float(args.canary_max_notional_usdt)),
        canary_max_leverage=max(0.0, float(args.canary_max_leverage)),
        canary_max_daily_loss_usdt=max(0.0, float(args.canary_max_daily_loss_usdt)),
        canary_risk_caps_path=_resolve(args.canary_risk_caps_json) if args.canary_risk_caps_json else None,
        allow_canary_without_real_paper_rows=bool(args.allow_canary_without_real_paper_rows),
        shadow_runtime_observed_hours=max(0.0, float(args.shadow_runtime_observed_hours)),
        shadow_runtime_required_hours=max(0.0, float(args.shadow_runtime_required_hours)),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
