#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.repositories import CandleRepository
from app.db.session import SessionLocal, init_db
from app.services.live_order_lifecycle import LiveOrderLifecycleReporter
from app.services.runtime_worker_heartbeat import read_worker_heartbeat
from scripts.operation_report_io import atomic_write_text, display_path, parse_report_generated_at, write_latest_aliases
from scripts.run_micro_live_preflight import _micro_live_config_drift_checks


SESSION_IMPULSE_RETEST_MIN_1M_CANDLES = 600
SESSION_IMPULSE_RETEST_MIN_5M_CANDLES = 200


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run fast MICRO_LIVE runtime guard checks without calling the local API preflight surfaces."
    )
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--check-binance-rules", action="store_true")
    parser.add_argument("--report-dir", default="reports/operations/micro_live_runtime_guard")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--no-fail-exit", action="store_true", help="Always return exit code 0 after printing the report.")
    parser.add_argument("--quiet", action="store_true", help="Do not print the JSON payload to stdout.")
    return parser.parse_args()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _display_path(path: Path) -> str:
    return display_path(path, ROOT_DIR)


def _csv_set(value: Any) -> set[str]:
    return {item.strip() for item in str(value or "").split(",") if item.strip()}


def _csv_upper_set(value: Any) -> set[str]:
    return {item.strip().upper() for item in str(value or "").split(",") if item.strip()}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if parsed == parsed else float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
    return bool(value)


def _parse_utc_ts(value: Any) -> datetime | None:
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


def _ws_runtime_started_at() -> datetime | None:
    payload = read_worker_heartbeat("ws")
    details = dict(payload.get("details") or {}) if isinstance(payload, dict) else {}
    return _parse_utc_ts(details.get("started_at"))


def _blocking_failures(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in checks
        if str(item.get("severity") or "").lower() == "blocking" and str(item.get("status") or "").upper() != "PASS"
    ]


def _warning_failures(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in checks
        if str(item.get("severity") or "").lower() != "blocking" and str(item.get("status") or "").upper() != "PASS"
    ]


def _live_candle_depth_check(
    candle_repo: Any,
    *,
    symbols: list[str],
    min_1m: int = SESSION_IMPULSE_RETEST_MIN_1M_CANDLES,
    min_5m: int = SESSION_IMPULSE_RETEST_MIN_5M_CANDLES,
) -> dict[str, Any]:
    normalized_symbols = sorted({str(symbol or "").upper().strip() for symbol in symbols if str(symbol or "").strip()})
    deficits: list[dict[str, Any]] = []
    min_observed_1m: int | None = None
    min_observed_5m: int | None = None
    for symbol in normalized_symbols:
        count_1m = len(candle_repo.list_recent(symbol=symbol, timeframe="1m", limit=max(1, int(min_1m))))
        count_5m = len(candle_repo.list_recent(symbol=symbol, timeframe="5m", limit=max(1, int(min_5m))))
        min_observed_1m = count_1m if min_observed_1m is None else min(min_observed_1m, count_1m)
        min_observed_5m = count_5m if min_observed_5m is None else min(min_observed_5m, count_5m)
        if count_1m < int(min_1m) or count_5m < int(min_5m):
            deficits.append(
                {
                    "symbol": symbol,
                    "candles_1m": count_1m,
                    "candles_5m": count_5m,
                    "required_1m": int(min_1m),
                    "required_5m": int(min_5m),
                }
            )

    if not normalized_symbols:
        return {
            "name": "live_candle_depth",
            "status": "FAIL",
            "severity": "blocking",
            "message": "live_symbols=0; cannot verify SIR candle depth",
            "deficits": [],
        }

    deficient_symbols = [str(item["symbol"]) for item in deficits[:8]]
    status = "PASS" if not deficits else "FAIL"
    return {
        "name": "live_candle_depth",
        "status": status,
        "severity": "blocking",
        "message": (
            f"symbols={len(normalized_symbols)}; min_1m={int(min_1m)}; min_5m={int(min_5m)}; "
            f"min_observed_1m={min_observed_1m}; min_observed_5m={min_observed_5m}; "
            f"deficient={','.join(deficient_symbols) if deficient_symbols else 'none'}"
        ),
        "deficient_count": len(deficits),
        "deficits": deficits[:20],
    }


def _live_leverage_cap_sync_report_check(*, max_age_minutes: int = 90) -> dict[str, Any]:
    path = ROOT_DIR / "reports/operations/live_leverage_cap_sync/latest.json"
    if not path.exists():
        return {
            "name": "live_leverage_cap_sync_report",
            "status": "FAIL",
            "severity": "blocking",
            "message": f"missing latest leverage sync report: {_display_path(path)}",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "name": "live_leverage_cap_sync_report",
            "status": "FAIL",
            "severity": "blocking",
            "message": f"invalid latest leverage sync report: {exc.__class__.__name__}",
        }
    try:
        generated_at = parse_report_generated_at(payload.get("generated_at"))
    except Exception as exc:
        return {
            "name": "live_leverage_cap_sync_report",
            "status": "FAIL",
            "severity": "blocking",
            "message": f"latest leverage sync report has invalid generated_at: {exc.__class__.__name__}",
        }
    age_minutes = max(0.0, (datetime.now(UTC) - generated_at).total_seconds() / 60.0)
    overall_status = str(payload.get("overall_status") or "").upper()
    pending_count = int(payload.get("pending_count") or 0)
    fail_count = int(payload.get("fail_count") or 0)
    target_leverage = int(payload.get("target_leverage") or 0)
    configured_cap = int(payload.get("configured_leverage_cap") or 0)
    stale = age_minutes > max(1, int(max_age_minutes))
    unhealthy = overall_status not in {"OK", "PASS"} or pending_count > 0 or fail_count > 0 or target_leverage != configured_cap
    status = "FAIL" if stale or unhealthy else "PASS"
    return {
        "name": "live_leverage_cap_sync_report",
        "status": status,
        "severity": "blocking",
        "message": (
            f"status={overall_status or 'unset'}; age_minutes={age_minutes:.1f}; "
            f"target={target_leverage}; configured_cap={configured_cap}; "
            f"pending={pending_count}; fail={fail_count}; stale={stale}"
        ),
        "age_minutes": round(age_minutes, 2),
        "pending_count": pending_count,
        "fail_count": fail_count,
        "target_leverage": target_leverage,
        "configured_leverage_cap": configured_cap,
    }


def _session_impulse_retest_exit_contract_check(settings: Any) -> dict[str, Any]:
    observed = {
        "policy": str(getattr(settings, "session_impulse_retest_exit_policy_name", "") or ""),
        "stop_mode": str(getattr(settings, "session_impulse_retest_exit_stop_mode", "") or ""),
        "target_rr": _safe_float(getattr(settings, "session_impulse_retest_exit_target_rr", 0.0)),
        "tp1_fraction": _safe_float(getattr(settings, "session_impulse_retest_exit_tp1_fraction", 0.0)),
        "tp2_fraction": _safe_float(getattr(settings, "session_impulse_retest_exit_tp2_fraction", 0.0)),
        "min_stop_pct": _safe_float(getattr(settings, "session_impulse_retest_exit_min_stop_pct", 0.0)),
        "min_risk_atr": _safe_float(getattr(settings, "session_impulse_retest_exit_min_risk_atr", 0.0)),
        "adaptive_targets": _safe_bool(
            getattr(settings, "session_impulse_retest_exit_adaptive_targets_enabled", False)
        ),
        "structure_targets": _safe_bool(
            getattr(settings, "session_impulse_retest_exit_structure_targets_enabled", False)
        ),
        "swing_lookback_bars": _safe_int(getattr(settings, "session_impulse_retest_exit_structure_stop_swing_bars", 0)),
        "stop_buffer_atr": _safe_float(getattr(settings, "session_impulse_retest_exit_structure_stop_buffer_atr", 0.0)),
        "structure_target_buffer_atr": _safe_float(
            getattr(settings, "session_impulse_retest_exit_structure_target_buffer_atr", 0.0)
        ),
        "structure_tp1_min_rr": _safe_float(getattr(settings, "session_impulse_retest_exit_structure_tp1_min_rr", 0.0)),
        "structure_tp2_min_rr": _safe_float(getattr(settings, "session_impulse_retest_exit_structure_tp2_min_rr", 0.0)),
        "structure_tp_max_rr": _safe_float(getattr(settings, "session_impulse_retest_exit_structure_tp_max_rr", 0.0)),
        "important_zone_exit": _safe_bool(
            getattr(settings, "session_impulse_retest_exit_important_zone_exit_enabled", False)
        ),
        "important_zone_stop": _safe_bool(
            getattr(settings, "session_impulse_retest_exit_important_zone_stop_enabled", True),
            default=True,
        ),
        "important_zone_target": _safe_bool(
            getattr(settings, "session_impulse_retest_exit_important_zone_target_enabled", True),
            default=True,
        ),
        "important_zone_stop_buffer_atr": _safe_float(
            getattr(settings, "session_impulse_retest_exit_important_zone_stop_buffer_atr", 0.08)
        ),
        "important_zone_target_buffer_atr": _safe_float(
            getattr(settings, "session_impulse_retest_exit_important_zone_target_buffer_atr", 0.05)
        ),
        "stop_after_partial_rr": _safe_float(getattr(settings, "session_impulse_retest_exit_stop_after_partial_rr", 0.0)),
        "adverse_volume_enabled": _safe_bool(
            getattr(settings, "session_impulse_retest_exit_adverse_volume_enabled", False)
        ),
        "adverse_volume_after_partial_only": _safe_bool(
            getattr(settings, "session_impulse_retest_exit_adverse_volume_after_partial_only", True),
            default=True,
        ),
        "adverse_volume_min_factor": _safe_float(
            getattr(settings, "session_impulse_retest_exit_adverse_volume_min_factor", 3.0)
        ),
        "adverse_volume_min_body_r": _safe_float(
            getattr(settings, "session_impulse_retest_exit_adverse_volume_min_body_r", 0.35)
        ),
        "adverse_volume_lookback_bars": _safe_int(
            getattr(settings, "session_impulse_retest_exit_adverse_volume_lookback_bars", 20)
        ),
        "live_breakeven_after_partial": _safe_bool(
            getattr(settings, "auto_trading_live_breakeven_after_partial_enabled", False)
        ),
        "live_breakeven_offset_bps": _safe_float(getattr(settings, "auto_trading_live_breakeven_offset_bps", 1.0)),
        "live_breakeven_min_improvement_bps": _safe_float(
            getattr(settings, "auto_trading_live_breakeven_min_improvement_bps", 1.0)
        ),
        "live_adverse_volume_exit": _safe_bool(getattr(settings, "auto_trading_live_adverse_volume_exit_enabled", False)),
        "live_adverse_volume_after_partial_only": _safe_bool(
            getattr(settings, "auto_trading_live_adverse_volume_exit_after_partial_only", True),
            default=True,
        ),
    }
    mismatches: list[str] = []
    expected_name = "unknown"

    def _expect_float(key: str, expected: float, *, tolerance: float = 1e-9) -> None:
        if abs(float(observed[key]) - float(expected)) > tolerance:
            mismatches.append(f"{key}={observed[key]}")

    def _expect_int(key: str, expected: int) -> None:
        if int(observed[key]) != int(expected):
            mismatches.append(f"{key}={observed[key]}")

    def _expect_bool(key: str, expected: bool) -> None:
        if bool(observed[key]) is not bool(expected):
            mismatches.append(f"{key}={str(observed[key]).lower()}")

    if observed["policy"] == "legacy_full_2r":
        expected_name = "legacy_full_2r/legacy/full_2R/no_split/no_structure"
        if observed["stop_mode"] != "legacy":
            mismatches.append(f"stop_mode={observed['stop_mode']}")
        _expect_float("target_rr", 2.0)
        for key in ("tp1_fraction", "tp2_fraction", "min_stop_pct", "min_risk_atr"):
            _expect_float(key, 0.0)
        _expect_bool("adaptive_targets", False)
        _expect_bool("structure_targets", False)
        _expect_bool("important_zone_exit", False)
        _expect_bool("adverse_volume_enabled", False)
        _expect_bool("live_adverse_volume_exit", False)
    elif observed["policy"] == "structure_buffered_swing6_stop0.12_tpbuf0.08_pm_stop0.00r_advvol_any":
        expected_name = "structure_buffered_swing6_stop0.12_tpbuf0.08_pm_stop0.00r_advvol_any"
        if observed["stop_mode"] != "structure_floor":
            mismatches.append(f"stop_mode={observed['stop_mode']}")
        _expect_float("target_rr", 2.5)
        _expect_float("tp1_fraction", 0.35)
        _expect_float("tp2_fraction", 0.65)
        _expect_float("min_stop_pct", 0.003)
        _expect_float("min_risk_atr", 0.35)
        _expect_bool("adaptive_targets", True)
        _expect_bool("structure_targets", True)
        _expect_bool("important_zone_exit", False)
        _expect_bool("important_zone_stop", True)
        _expect_bool("important_zone_target", True)
        _expect_int("swing_lookback_bars", 6)
        _expect_float("stop_buffer_atr", 0.12)
        _expect_float("structure_target_buffer_atr", 0.08)
        _expect_float("structure_tp1_min_rr", 0.8)
        _expect_float("structure_tp2_min_rr", 1.6)
        _expect_float("structure_tp_max_rr", 3.2)
        _expect_float("stop_after_partial_rr", 0.0)
        _expect_bool("adverse_volume_enabled", True)
        _expect_bool("adverse_volume_after_partial_only", False)
        _expect_float("adverse_volume_min_factor", 3.0)
        _expect_float("adverse_volume_min_body_r", 0.35)
        _expect_int("adverse_volume_lookback_bars", 20)
        _expect_bool("live_breakeven_after_partial", True)
        _expect_float("live_breakeven_offset_bps", 0.0)
        _expect_float("live_breakeven_min_improvement_bps", 0.0)
        _expect_bool("live_adverse_volume_exit", True)
        _expect_bool("live_adverse_volume_after_partial_only", False)
    else:
        mismatches.append(f"policy={observed['policy']}")

    status = "PASS" if not mismatches else "FAIL"
    return {
        "name": "session_impulse_retest_exit_contract",
        "status": status,
        "severity": "blocking",
        "message": (
            f"expected={expected_name}; "
            f"observed={observed}; mismatches={','.join(mismatches) if mismatches else 'none'}"
        ),
        "observed": observed,
        "mismatches": mismatches,
    }


_BLOCK_REASON_ACTIONS = {
    "validation_do_not_deploy": "inspect_validation_report_approval_surface",
    "rollout_session_not_allowed": "inspect_session_time_contract_or_wait_for_allowed_window",
    "symbol_not_live_enabled": "align_live_symbol_allowlists_before_enabling",
    "strategy_family_not_live_enabled": "align_live_family_allowlists_before_enabling",
    "entry_model_not_live_enabled": "align_live_entry_model_allowlist_before_enabling",
    "adjusted_score_non_positive": "inspect_scoring_and_risk_gate_inputs",
    "live_liquidity_gate_blocked": "inspect_orderbook_liquidity_gate_snapshot",
    "safety_lock_active": "inspect_execution_safety_state",
}


def _blocked_intent_diagnostics(lifecycle: dict[str, Any]) -> list[dict[str, Any]]:
    live_intents = dict((dict(lifecycle.get("summary") or {}).get("live_intents")) or {})
    top_reasons = dict(live_intents.get("top_block_reasons") or {})
    samples = [dict(item) for item in list(live_intents.get("recent_blocked_intents") or []) if isinstance(item, dict)]
    diagnostics: list[dict[str, Any]] = []
    for reason, count in top_reasons.items():
        reason_text = str(reason or "none")
        diagnostics.append(
            {
                "reason": reason_text,
                "count": int(count or 0),
                "action": _BLOCK_REASON_ACTIONS.get(reason_text, "inspect_recent_blocked_intent_samples"),
                "recent_samples": [
                    sample
                    for sample in samples
                    if str(sample.get("decision_reason_code") or "none") == reason_text
                ][:3],
                "detail": next(
                    (
                        dict(sample.get("block_detail") or {})
                        for sample in samples
                        if str(sample.get("decision_reason_code") or "none") == reason_text
                        and isinstance(sample.get("block_detail"), dict)
                        and sample.get("block_detail")
                    ),
                    {},
                ),
            }
        )
    return diagnostics


def _recommendations(*, blocking_failures: list[dict[str, Any]], lifecycle: dict[str, Any]) -> list[str]:
    recommendations: list[str] = []
    if blocking_failures:
        names = ",".join(str(item.get("name") or "unknown") for item in blocking_failures[:8])
        recommendations.append(f"fix_blocking_runtime_checks:{names}")

    live_intents = dict((dict(lifecycle.get("summary") or {}).get("live_intents")) or {})
    total_intents = int(live_intents.get("total") or 0)
    submit_ready = int(live_intents.get("submit_ready") or 0)
    blocked = int(live_intents.get("blocked") or 0)
    if total_intents > 0 and submit_ready == 0 and blocked >= total_intents:
        top_reasons = dict(live_intents.get("top_block_reasons") or {})
        reason_text = ",".join(f"{key}={value}" for key, value in list(top_reasons.items())[:4])
        recommendations.append(f"all_recent_live_intents_blocked:{reason_text or 'unknown'}")
        for item in _blocked_intent_diagnostics(lifecycle)[:3]:
            recommendations.append(f"{item['action']}:{item['reason']}={item['count']}")

    summary = dict(lifecycle.get("summary") or {})
    if int(summary.get("rejected_or_error_count") or 0) > 0:
        recommendations.append("inspect_rejected_or_error_order_submissions")
    if int(summary.get("submitted_without_entry_fill_count") or 0) > 0:
        recommendations.append("inspect_submitted_orders_without_entry_fills")
    return recommendations


def _operational_status(
    *,
    blocking_failures: list[dict[str, Any]],
    lifecycle: dict[str, Any],
    warning_failures: list[dict[str, Any]] | None = None,
) -> str:
    if blocking_failures:
        return "FAIL"
    if warning_failures:
        return "WATCH"
    live_intents = dict((dict(lifecycle.get("summary") or {}).get("live_intents")) or {})
    total_intents = int(live_intents.get("total") or 0)
    submit_ready = int(live_intents.get("submit_ready") or 0)
    blocked = int(live_intents.get("blocked") or 0)
    if total_intents > 0 and submit_ready == 0 and blocked >= total_intents:
        return "WATCH"
    summary = dict(lifecycle.get("summary") or {})
    if int(summary.get("rejected_or_error_count") or 0) > 0:
        return "WATCH"
    return "PASS"


def build_payload(*, days: int, limit: int, check_binance_rules: bool) -> dict[str, Any]:
    settings = get_settings()
    family_filter = _csv_set(getattr(settings, "auto_trading_micro_live_allowed_families", ""))
    if not family_filter:
        family_filter = _csv_set(getattr(settings, "auto_trading_allowed_families", ""))
    symbol_filter = _csv_upper_set(getattr(settings, "auto_trading_micro_live_allowed_symbols", ""))
    if not symbol_filter:
        symbol_filter = _csv_upper_set(getattr(settings, "auto_trading_allowed_symbols", ""))
    runtime_started_at = _ws_runtime_started_at()
    checks = _micro_live_config_drift_checks(check_binance_rules=check_binance_rules)
    if "session_impulse_retest" in family_filter:
        checks.append(_session_impulse_retest_exit_contract_check(settings))
    checks.append(_live_leverage_cap_sync_report_check())
    init_db()
    with SessionLocal() as db:
        checks.append(_live_candle_depth_check(CandleRepository(db), symbols=sorted(symbol_filter)))
        lifecycle = LiveOrderLifecycleReporter(db).generate(
            days=days,
            live_only=True,
            limit=limit,
            start_at=runtime_started_at,
            symbols=sorted(symbol_filter),
            strategy_families=sorted(family_filter),
        )
    failures = _blocking_failures(checks)
    warnings = _warning_failures(checks)
    blocked_diagnostics = _blocked_intent_diagnostics(lifecycle)
    recommendations = _recommendations(blocking_failures=failures, lifecycle=lifecycle)
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "runtime_started_at": runtime_started_at.isoformat() if runtime_started_at else None,
        "family_filter": sorted(family_filter),
        "symbol_filter": sorted(symbol_filter),
        "overall_status": "FAIL" if failures else ("WATCH" if warnings else "PASS"),
        "operational_status": _operational_status(
            blocking_failures=failures,
            warning_failures=warnings,
            lifecycle=lifecycle,
        ),
        "blocking_failures": failures,
        "warning_failures": warnings,
        "checks": checks,
        "lifecycle": lifecycle,
        "blocked_intent_diagnostics": blocked_diagnostics,
        "recommendations": recommendations,
    }


def _write_report(path: Path, payload: dict[str, Any], *, atomic: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lifecycle_summary = dict((dict(payload.get("lifecycle") or {}).get("summary")) or {})
    live_intents = dict(lifecycle_summary.get("live_intents") or {})
    lines = [
        "# MICRO_LIVE Runtime Guard",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- runtime_started_at: {payload.get('runtime_started_at') or 'none'}",
        f"- family_filter: {','.join(payload.get('family_filter') or []) or 'none'}",
        f"- symbol_filter: {','.join(payload.get('symbol_filter') or []) or 'none'}",
        f"- overall_status: {payload.get('overall_status')}",
        f"- operational_status: {payload.get('operational_status')}",
        f"- blocking_failures: {len(payload.get('blocking_failures') or [])}",
        f"- warning_failures: {len(payload.get('warning_failures') or [])}",
        "",
        "## Config Drift",
        "",
    ]
    for check in payload.get("checks") or []:
        lines.append(
            f"- {check.get('name')}: {check.get('status')} {check.get('severity')} | {check.get('message')}"
        )
    lines.extend(
        [
            "",
            "## Live Order Funnel",
            "",
            f"- submissions: {lifecycle_summary.get('submission_count', 0)}",
            f"- entry_fills: {lifecycle_summary.get('entry_fill_count', 0)}",
            f"- rejected_or_error: {lifecycle_summary.get('rejected_or_error_count', 0)}",
            f"- intents: {live_intents.get('total', 0)}",
            f"- submit_ready: {live_intents.get('submit_ready', 0)}",
            f"- blocked: {live_intents.get('blocked', 0)}",
        ]
    )
    top_reasons = dict(live_intents.get("top_block_reasons") or {})
    if top_reasons:
        lines.append("- top_reasons: " + ", ".join(f"{key}={value}" for key, value in list(top_reasons.items())[:8]))
    diagnostics = list(payload.get("blocked_intent_diagnostics") or [])
    if diagnostics:
        lines.extend(["", "## Blocked Intent Diagnostics", ""])
        for item in diagnostics[:8]:
            detail = dict(item.get("detail") or {})
            detail_text = ""
            if detail:
                metrics = dict(detail.get("metrics") or {})
                metric_bits = []
                if "sample_size" in metrics:
                    metric_bits.append(f"sample={metrics.get('sample_size')}")
                if "ev" in metrics or "expectancy_r" in metrics:
                    metric_bits.append(f"ev={metrics.get('expectancy_r', metrics.get('ev'))}")
                metric_text = f" {' '.join(metric_bits)}" if metric_bits else ""
                detail_text = (
                    f" | cause={detail.get('primary_cause', '') or 'unknown'} grade={detail.get('grade', '')} "
                    f"risk={detail.get('risk_state', '')}/{detail.get('risk_reason', '')} "
                    f"deployment={detail.get('deployment_code', '')}{metric_text}"
                )
            lines.append(f"- {item.get('reason')}: {item.get('count')} | action={item.get('action')}{detail_text}")
    lines.extend(["", "## Recommendations", ""])
    recommendations = list(payload.get("recommendations") or [])
    if recommendations:
        lines.extend(f"- {item}" for item in recommendations)
    else:
        lines.append("- none")
    lines.extend(["", "## Raw Payload", "", "```json"])
    lines.append(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    lines.append("```")
    content = "\n".join(lines)
    if atomic:
        atomic_write_text(path, content)
    else:
        atomic_write_text(path, content)


def main() -> int:
    args = parse_args()
    payload = build_payload(
        days=max(1, int(args.days)),
        limit=max(1, int(args.limit)),
        check_binance_rules=bool(args.check_binance_rules),
    )
    if not args.no_write_report:
        generated = parse_report_generated_at(payload.get("generated_at"))
        report_dir = ROOT_DIR / args.report_dir
        report_path = report_dir / f"micro_live_runtime_guard_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
        payload["report_path"] = _display_path(report_path)
        payload["latest_report_path"] = _display_path(report_dir / "latest.md")
        payload["latest_json_path"] = _display_path(report_dir / "latest.json")
        _write_report(report_path, payload, atomic=True)
        payload.update(
            write_latest_aliases(
                report_dir=report_dir,
                payload=payload,
                write_markdown_report=_write_report,
                root_dir=ROOT_DIR,
                json_default=_json_default,
            )
        )
    if not bool(args.quiet):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    if payload["overall_status"] == "FAIL" and not bool(args.no_fail_exit):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
