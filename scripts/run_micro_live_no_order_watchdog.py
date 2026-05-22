#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.session import SessionLocal, init_db
from app.services.live_order_lifecycle import LiveOrderLifecycleReporter
from app.services.micro_main_strategy_research import (
    SessionImpulseRetestResearch,
    session_impulse_retest_profile_for_symbol,
)
from app.services.notification_dispatcher import NotificationDispatcher
from app.services.runtime_worker_heartbeat import read_worker_heartbeat
from app.services.strategy_engine import StrategyEngine
from scripts.operation_report_io import atomic_write_text, parse_report_generated_at
from scripts.run_micro_live_runtime_guard import _blocked_intent_diagnostics


_SIR_HARD_STATUSES = {"intent_creation_failed", "submit_error"}
_SIR_WATCH_STATUSES = {
    "auto_trading_disabled_or_shadow_mode",
    "family_disabled",
    "family_shadow_only",
    "symbol_not_live_enabled_for_auto_route",
}
_SIR_ORDER_BLOCKING_STATUSES = {"intent_blocked", "intent_creation_failed", "submit_error"}
_SIR_NON_BLOCKING_STATUSES = {
    "duplicate_active_thesis",
    "recent_intent_cooldown_active",
    "skipped_duplicate_active_thesis",
    "ws_stream_active_route_suppressed",
}
_SIR_NO_CANDIDATE_STATUSES = {"no_fresh_candidates", "no_live_route_candidate_plan"}
_KST = timezone(timedelta(hours=9))


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
    return True if value else False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Alert when MICRO_LIVE intents accumulate but no live order is submitted.")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--min-intents", type=int, default=1)
    parser.add_argument("--cooldown-minutes", type=int, default=360)
    parser.add_argument("--channel", choices=["discord", "system"], default="discord")
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--force-notify", action="store_true")
    parser.add_argument("--report-dir", default="reports/operations/micro_live_no_order_watchdog")
    parser.add_argument("--state-file", default="reports/operations/micro_live_no_order_watchdog/state.json")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--no-fail-exit", action="store_true")
    parser.add_argument("--quiet", action="store_true", help="Do not print the JSON payload to stdout.")
    return parser.parse_args()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _resolve_root_path(raw_path: str) -> Path:
    path = Path(str(raw_path or "")).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _maybe_float(value: Any) -> float | None:
    if value in (None, "", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _csv_set(value: Any) -> set[str]:
    return {item.strip() for item in str(value or "").split(",") if item.strip()}


def _csv_upper_set(value: Any) -> set[str]:
    return {item.strip().upper() for item in str(value or "").split(",") if item.strip()}


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


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _atomic_write_text(path: Path, content: str) -> None:
    atomic_write_text(path, content)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))


def _top_reasons_text(top_reasons: dict[str, Any], *, limit: int = 4) -> str:
    if not top_reasons:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in list(top_reasons.items())[:limit])


def _diagnostic_actions_text(
    diagnostics: list[dict[str, Any]],
    *,
    limit: int = 4,
    fallback: str = "fresh live 후보 대기; 현재 차단 사유 없음",
) -> str:
    if not diagnostics:
        return fallback
    return ", ".join(f"{item.get('reason')}->{item.get('action')}" for item in diagnostics[:limit])


def _diagnostic_detail_text(diagnostics: list[dict[str, Any]]) -> str:
    for item in diagnostics:
        detail = dict(item.get("detail") or {})
        if detail:
            metrics = dict(detail.get("metrics") or {})
            parts = [
                f"cause={detail.get('primary_cause', '') or 'unknown'}",
                f"grade={detail.get('grade', '')}",
                f"risk={detail.get('risk_state', '')}/{detail.get('risk_reason', '')}",
                f"deployment={detail.get('deployment_code', '')}",
            ]
            if "sample_size" in metrics:
                parts.append(f"sample={metrics.get('sample_size')}")
            if "ev" in metrics or "expectancy_r" in metrics:
                parts.append(f"ev={metrics.get('expectancy_r', metrics.get('ev'))}")
            return ", ".join(parts)
    return ""


def _summary_intent_plan_counts(summary: dict[str, Any]) -> tuple[int, int, int, int]:
    live_intents = dict(summary.get("live_intents") or {})
    total = _safe_int(live_intents.get("total"))
    distinct = _safe_int(live_intents.get("distinct_plan_count"), default=total)
    duplicate = _safe_int(live_intents.get("duplicate_plan_intent_count"))
    submissions = _safe_int(summary.get("requested_live_count"))
    return total, distinct, duplicate, submissions


def _intent_count_text(intent_count: Any, distinct_plan_count: Any = None, duplicate_intent_count: Any = None) -> str:
    total = _safe_int(intent_count)
    distinct = _safe_int(distinct_plan_count, default=total)
    duplicate = _safe_int(duplicate_intent_count)
    if duplicate > 0 and distinct != total:
        return f"intent {total}건(계획 {distinct}개, 중복 {duplicate}건)"
    return f"intent {total}건"


def _runtime_age_minutes(*, generated_at: datetime, runtime_started_at: datetime | None) -> float | None:
    if runtime_started_at is None:
        return None
    return round(max(0.0, (generated_at - runtime_started_at).total_seconds() / 60.0), 2)


def _runtime_age_text(value: Any) -> str:
    try:
        age = float(value)
    except (TypeError, ValueError):
        return ""
    if age < 60:
        return f"{age:.1f}분"
    return f"{age / 60.0:.1f}시간"


def _lookback_hours_label(value: Any, *, fallback_days: Any = None) -> str:
    hours = _safe_int(value)
    if hours <= 0 and fallback_days is not None:
        days = max(1, _safe_int(fallback_days, default=1))
        return f"최근 {days}일"
    if hours <= 0:
        return ""
    if hours % 24 == 0:
        return f"최근 {max(1, hours // 24)}일"
    return f"최근 {hours}시간"


def _opportunity_coverage_text(coverage: dict[str, Any]) -> str:
    if not coverage:
        return ""
    if not _safe_bool(coverage.get("coverage_limited")):
        return ""
    hours = coverage.get("min_local_1m_coverage_hours")
    try:
        parsed_hours = float(hours)
    except (TypeError, ValueError):
        parsed_hours = 0.0
    if parsed_hours > 0:
        return f"로컬 캔들 커버리지 약 {parsed_hours:.1f}시간"
    return "로컬 캔들 커버리지 제한"


def _watchdog_scope_label(*, runtime_started_at: datetime | None, days: int) -> str:
    if runtime_started_at is not None:
        return "런타임 재시작 이후"
    return f"최근 {max(1, int(days))}일"


def _as_utc(value: datetime | None) -> datetime:
    parsed = value or datetime.now(UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _window_time_label(start: Any, end: Any) -> str:
    start_dt = _parse_utc_ts(start)
    end_dt = _parse_utc_ts(end)
    if start_dt is None or end_dt is None:
        return ""
    start_kst = start_dt.astimezone(_KST)
    end_kst = end_dt.astimezone(_KST)
    if start_kst.date() == end_kst.date():
        return f"{start_kst.strftime('%m-%d %H:%M')}-{end_kst.strftime('%H:%M')} KST"
    return f"{start_kst.strftime('%m-%d %H:%M')}-{end_kst.strftime('%m-%d %H:%M')} KST"


def _session_impulse_retest_signal_window_context(
    *,
    symbols: list[str] | set[str] | tuple[str, ...],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _as_utc(generated_at)
    normalized_symbols = sorted({str(symbol or "").strip().upper() for symbol in symbols if str(symbol or "").strip()})
    profile_counts = Counter(
        session_impulse_retest_profile_for_symbol(symbol)
        for symbol in normalized_symbols
    )
    if not profile_counts:
        return {}

    defaults = SessionImpulseRetestResearch._PROFILE_DEFAULTS
    profile_offsets: dict[str, dict[str, int]] = {}
    for profile_name in sorted(profile_counts):
        profile = dict(defaults.get(profile_name) or defaults.get("baseline") or {})
        min_bars = max(0, _safe_int(profile.get("min_offset_bars"), default=0))
        max_bars = max(min_bars, _safe_int(profile.get("max_offset_bars"), default=min_bars))
        profile_offsets[profile_name] = {
            "min_offset_bars_5m": min_bars,
            "max_offset_bars_5m": max_bars,
            "min_offset_minutes": min_bars * 5,
            "max_offset_minutes": max_bars * 5,
        }

    anchor_hours = tuple(int(hour) for hour in SessionImpulseRetestResearch._session_anchor_hours())
    windows: list[dict[str, Any]] = []
    base_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for day_offset in range(-1, 3):
        day_start = base_midnight + timedelta(days=day_offset)
        for anchor_hour in anchor_hours:
            anchor = day_start + timedelta(hours=anchor_hour)
            profile_windows: dict[str, dict[str, Any]] = {}
            starts: list[datetime] = []
            ends: list[datetime] = []
            for profile_name, offsets in profile_offsets.items():
                start = anchor + timedelta(minutes=int(offsets["min_offset_minutes"]))
                end = anchor + timedelta(minutes=int(offsets["max_offset_minutes"]))
                starts.append(start)
                ends.append(end)
                profile_windows[profile_name] = {
                    "symbol_count": _safe_int(profile_counts.get(profile_name)),
                    "start_utc": _iso_z(start),
                    "end_utc": _iso_z(end),
                    "label_kst": _window_time_label(start, end),
                    **offsets,
                }
            start = min(starts)
            end = max(ends)
            if end < now:
                continue
            windows.append(
                {
                    "anchor_hour_utc": anchor_hour,
                    "anchor_utc": _iso_z(anchor),
                    "start_utc": _iso_z(start),
                    "end_utc": _iso_z(end),
                    "label_kst": _window_time_label(start, end),
                    "is_current": start <= now <= end,
                    "profile_windows": profile_windows,
                }
            )

    windows.sort(key=lambda item: str(item.get("start_utc") or ""))
    current_window = next((dict(item) for item in windows if _safe_bool(item.get("is_current"))), None)
    next_window = next((dict(item) for item in windows if not _safe_bool(item.get("is_current"))), None)
    return {
        "source": "session_impulse_retest_research_profile_offsets",
        "generated_at": _iso_z(now),
        "anchor_hours_utc": list(anchor_hours),
        "profile_counts": dict(profile_counts.most_common()),
        "current_window": current_window or {},
        "next_window": next_window or {},
        "upcoming_windows": windows[:3],
        "note": "approximate setup signal window; all strategy filters still must pass",
    }


def _signal_window_summary_text(schedule: dict[str, Any]) -> str:
    if not schedule:
        return ""
    current_window = dict(schedule.get("current_window") or {})
    if current_window:
        label = _window_time_label(current_window.get("start_utc"), current_window.get("end_utc")) or str(
            current_window.get("label_kst") or ""
        )
        return f"현재 관찰창 {label}".strip()
    next_window = dict(schedule.get("next_window") or {})
    if next_window:
        label = _window_time_label(next_window.get("start_utc"), next_window.get("end_utc")) or str(
            next_window.get("label_kst") or ""
        )
        return f"다음 관찰창 {label}".strip()
    return ""


def _signal_window_note(schedule: dict[str, Any]) -> str:
    summary = _signal_window_summary_text(schedule)
    return f"; {summary}" if summary else ""


def _rows_since(rows: list[dict[str, Any]], start_at: datetime | None) -> list[dict[str, Any]]:
    if start_at is None:
        return list(rows)
    return [
        row
        for row in rows
        if (observed_at := _parse_utc_ts(row.get("observed_ts"))) is not None
        and observed_at >= start_at
    ]


def _rows_created_since(rows: list[dict[str, Any]], start_at: datetime | None) -> list[dict[str, Any]]:
    if start_at is None:
        return list(rows)
    return [
        row
        for row in rows
        if (created_at := _parse_utc_ts(row.get("created_at"))) is not None
        and created_at >= start_at
    ]


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return dict(counter.most_common())


def _counts_summary_text(counts: dict[str, Any], *, limit: int = 3) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in list(counts.items())[: max(1, int(limit))])


def _lookback_blocking_reason_counts(reason_counts: dict[str, Any]) -> dict[str, int]:
    blocking: dict[str, int] = {}
    non_blocking_reasons = {
        "FILLED",
        "PARTIALLY_FILLED",
        "ACKNOWLEDGED",
        "SUBMITTED",
        "LIVE_SUBMITTING",
    }
    for raw_reason, raw_count in dict(reason_counts or {}).items():
        reason = str(raw_reason or "").strip()
        count = _safe_int(raw_count)
        if not reason or count <= 0:
            continue
        if reason == "before_runtime_start" or reason.startswith("before_runtime_start_"):
            continue
        if reason.upper() in non_blocking_reasons:
            continue
        blocking[reason] = count
    return blocking


def _session_impulse_retest_candidate_context(
    *,
    db: Any,
    hours: int,
    limit: int,
    runtime_started_at: datetime | None,
) -> dict[str, Any]:
    engine = StrategyEngine(db)
    lookback_rows = list(
        engine.session_impulse_retest_runtime_audits_recent(
            hours=max(1, int(hours)),
            phase="auto_route",
            limit=max(1, int(limit)),
        )
        or []
    )
    refresh_lookback_rows = list(
        engine.session_impulse_retest_runtime_audits_recent(
            hours=max(1, int(hours)),
            phase="refresh",
            limit=max(1, int(limit)),
        )
        or []
    )
    rows = _rows_since(lookback_rows, runtime_started_at)
    refresh_rows = _rows_created_since(refresh_lookback_rows, runtime_started_at)
    status_counts = Counter(str(row.get("status") or "unknown") for row in rows)
    hard = Counter({key: value for key, value in status_counts.items() if key in _SIR_HARD_STATUSES or key.endswith("_error")})
    watch = Counter({key: value for key, value in status_counts.items() if key in _SIR_WATCH_STATUSES})
    no_candidate: Counter[str] = Counter()
    non_blocking: Counter[str] = Counter()
    order_blocking: Counter[str] = Counter()
    signal_status_counts: Counter[str] = Counter()
    signal_reason_counts: Counter[str] = Counter()
    closest_setup_reason_counts: Counter[str] = Counter()
    latest_signal_sample: dict[str, Any] = {}
    for row in rows:
        status = str(row.get("status") or "unknown")
        payload = dict(row.get("payload") or {}) if isinstance(row.get("payload"), dict) else {}
        blocking_live_route = payload.get("blocking_live_route")
        if status in _SIR_NO_CANDIDATE_STATUSES:
            no_candidate[status] += 1
        if status in _SIR_NON_BLOCKING_STATUSES or blocking_live_route is False:
            non_blocking[status] += 1
        if status in _SIR_ORDER_BLOCKING_STATUSES or blocking_live_route is True:
            order_blocking[status] += 1
    for row in refresh_rows:
        payload = dict(row.get("payload") or {}) if isinstance(row.get("payload"), dict) else {}
        generation = dict(payload.get("plan_generation_diagnostics") or {})
        signal = dict(generation.get("session_impulse_retest_latest_signal") or {})
        if not signal:
            continue
        if not latest_signal_sample:
            latest_signal_sample = {
                "symbol": row.get("symbol"),
                "status": signal.get("status"),
                "reason": signal.get("reason"),
                "latest_checked_reason": dict(signal.get("latest_checked") or {}).get("reason"),
                "closest_setup_reason": dict(signal.get("closest_setup") or {}).get("reason"),
            }
        status = str(signal.get("status") or "unknown")
        reason = str(signal.get("reason") or "unknown")
        closest_reason = str(dict(signal.get("closest_setup") or {}).get("reason") or "")
        signal_status_counts[status] += 1
        signal_reason_counts[reason] += 1
        if closest_reason:
            closest_setup_reason_counts[closest_reason] += 1
    return {
        "source": "session_impulse_retest_runtime_audit",
        "scope": "runtime_since_ws_start" if runtime_started_at is not None else "lookback_window",
        "hours": max(1, int(hours)),
        "audit_count": len(rows),
        "refresh_audit_count": len(refresh_rows),
        "status_counts": _counter_dict(status_counts),
        "hard_status_counts": _counter_dict(hard),
        "watch_status_counts": _counter_dict(watch),
        "order_blocking_status_counts": _counter_dict(order_blocking),
        "non_blocking_status_counts": _counter_dict(non_blocking),
        "no_candidate_status_counts": _counter_dict(no_candidate),
        "latest_signal_status_counts": _counter_dict(signal_status_counts),
        "latest_signal_reason_counts": _counter_dict(signal_reason_counts),
        "latest_signal_closest_setup_reason_counts": _counter_dict(closest_setup_reason_counts),
        "latest_signal_sample": latest_signal_sample,
        "lookback_audit_count": len(lookback_rows),
        "lookback_refresh_audit_count": len(refresh_lookback_rows),
    }


def _disabled_sir_candidate_context() -> dict[str, Any]:
    return {
        "source": "session_impulse_retest_runtime_audit",
        "scope": "disabled_by_family_filter",
        "audit_count": 0,
        "status_counts": {},
        "hard_status_counts": {},
        "watch_status_counts": {},
        "order_blocking_status_counts": {},
        "non_blocking_status_counts": {},
        "no_candidate_status_counts": {},
    }


def _session_impulse_retest_opportunity_context(*, hours: int) -> dict[str, Any]:
    try:
        from scripts.run_session_impulse_retest_opportunity_report import build_report

        report = build_report(lookback_hours=max(1, int(hours)))
    except Exception as exc:  # pragma: no cover - defensive runtime diagnostics
        return {
            "source": "session_impulse_retest_opportunity_report",
            "status": "error",
            "error": str(exc),
        }
    return {
        "source": "session_impulse_retest_opportunity_report",
        "status": "ok",
        "generated_at": report.get("generated_at"),
        "lookback_hours": report.get("lookback_hours"),
        "opportunity_scope": report.get("opportunity_scope"),
        "runtime_started_at": report.get("runtime_started_at"),
        "coverage": dict(report.get("coverage") or {}),
        "contract": dict(report.get("contract") or {}),
        "direction_filtered_count": _safe_int(report.get("direction_filtered_count")),
        "direction_filtered_samples": list(report.get("direction_filtered_samples") or [])[:10],
        "summary": dict(report.get("summary") or {}),
        "lookback_summary": dict(report.get("lookback_summary") or {}),
    }


def _augment_no_order_evaluation(
    evaluation: dict[str, Any],
    *,
    candidate_context: dict[str, Any],
    opportunity_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    enriched = dict(evaluation)
    context = dict(candidate_context or {})
    if context:
        enriched["candidate_generation_context"] = context
    opportunity = dict(opportunity_context or {})
    if opportunity:
        enriched["session_impulse_retest_opportunity_context"] = opportunity
    if str(enriched.get("reason") or "") != "no_recent_live_intents":
        return enriched
    active_opportunity_summary = dict(opportunity.get("summary") or {})
    lookback_opportunity_summary = dict(opportunity.get("lookback_summary") or {})
    active_expected_orders = _safe_int(active_opportunity_summary.get("expected_order_count"))
    lookback_expected_orders = _safe_int(lookback_opportunity_summary.get("expected_order_count"))
    lookback_pre_restart_orders = _safe_int(lookback_opportunity_summary.get("before_current_runtime_start_count"))
    lookback_reason_counts = dict(lookback_opportunity_summary.get("reason_counts") or {})
    lookback_status_counts = dict(lookback_opportunity_summary.get("status_counts") or {})
    lookback_blocking_reasons = _lookback_blocking_reason_counts(lookback_reason_counts)
    lookback_blocked_or_skipped = _safe_int(lookback_status_counts.get("blocked_or_skipped"))
    lookback_hours = _safe_int(opportunity.get("lookback_hours"))
    direction_filtered_count = _safe_int(opportunity.get("direction_filtered_count"))
    lookback_window_label = _lookback_hours_label(lookback_hours) or "lookback"
    coverage_text = _opportunity_coverage_text(dict(opportunity.get("coverage") or {}))
    coverage_clause = f",coverage={coverage_text}" if coverage_text else ""
    coverage_note = f" ({coverage_text}; 전체 {lookback_window_label} 아님)" if coverage_text else ""
    direction_filter_clause = f",direction_filtered={direction_filtered_count}" if direction_filtered_count > 0 else ""
    direction_filter_note = (
        f"; 라이브 방향 계약으로 제외된 후보 {direction_filtered_count}건"
        if direction_filtered_count > 0
        else ""
    )
    if active_expected_orders > 0:
        enriched["alert"] = True
        enriched["status"] = "ALERT"
        enriched["severity"] = "WARN"
        enriched["reason"] = "sir_backtest_opportunity_without_live_intent"
        enriched["candidate_generation_status"] = "backtest_expected_opportunities_missing_live_intents"
        enriched["next_action_text"] = (
            f"{lookback_window_label} SIR 백테스트 조건 후보 {active_expected_orders}건 재생됨"
            f"{coverage_note}: runtime plan/intent 누락 확인"
        )
        enriched["message"] = (
            f"{enriched.get('message')} "
            f"SIR_opportunity=lookback_hours={lookback_hours},"
            f"active_expected={active_expected_orders},lookback_expected={lookback_expected_orders}"
            f"{direction_filter_clause}"
            f"{coverage_clause}"
        )
        return enriched
    order_blocking = dict(context.get("order_blocking_status_counts") or {})
    no_candidate = dict(context.get("no_candidate_status_counts") or {})
    non_blocking = dict(context.get("non_blocking_status_counts") or {})
    watch = dict(context.get("watch_status_counts") or {})
    signal_reasons = dict(context.get("latest_signal_reason_counts") or {})
    signal_reason_text = _counts_summary_text(signal_reasons, limit=3)
    signal_reason_clause = f" signal_reasons={signal_reason_text}" if signal_reason_text != "none" else ""
    signal_window_schedule = dict(context.get("signal_window_schedule") or {})
    signal_window_text = _signal_window_summary_text(signal_window_schedule)
    signal_window_clause = f" signal_window={signal_window_text}" if signal_window_text else ""
    current_signal_note = f"; 현재 신호 없음 이유: {signal_reason_text}" if signal_reason_text != "none" else ""
    current_signal_note = f"{current_signal_note}{_signal_window_note(signal_window_schedule)}"
    if lookback_expected_orders > 0 and lookback_pre_restart_orders > 0 and not order_blocking and (
        lookback_blocked_or_skipped > 0 or lookback_blocking_reasons
    ):
        reason_summary = _counts_summary_text(lookback_blocking_reasons or lookback_reason_counts, limit=4)
        lookback_perf_total_r = _maybe_float(
            dict(lookback_opportunity_summary.get("potential_performance") or {}).get("total_r")
        )
        non_positive_pre_restart_perf = lookback_perf_total_r is not None and lookback_perf_total_r <= 0.0
        enriched["alert"] = not non_positive_pre_restart_perf
        enriched["status"] = "OK" if non_positive_pre_restart_perf else "ALERT"
        enriched["severity"] = "INFO" if non_positive_pre_restart_perf else "WARN"
        enriched["reason"] = (
            "sir_pre_restart_blocked_opportunities_non_positive_advisory"
            if non_positive_pre_restart_perf
            else "sir_pre_restart_blocked_opportunities"
        )
        enriched["historical_advisory"] = bool(non_positive_pre_restart_perf)
        enriched["historical_blocked_opportunity_count"] = lookback_blocked_or_skipped
        enriched["historical_blocked_reason_counts"] = lookback_blocking_reasons
        enriched["candidate_generation_status"] = (
            "pre_restart_blocked_opportunities_non_positive_advisory"
            if non_positive_pre_restart_perf
            else "pre_restart_blocked_opportunities"
        )
        enriched["next_action_text"] = (
            f"재시작 전 {lookback_window_label} SIR 후보 중 제출 전 차단 이력 확인: "
            f"{reason_summary or 'reason=none'}{coverage_note}; "
            f"{'백테스트상 해당 구간 총 R이 양수가 아니므로 현재 경고가 아닌 참고로 유지' if non_positive_pre_restart_perf else '현재 설정으로 같은 차단이 반복되는지 확인'}"
            f"{current_signal_note}{direction_filter_note}"
        )
        previous_next_action = str(evaluation.get("next_action_text") or "")
        current_message = str(enriched.get("message") or "")
        if previous_next_action and current_message:
            current_message = current_message.replace(
                f"actions={previous_next_action}",
                f"actions={enriched.get('next_action_text')}",
            )
        enriched["message"] = (
            f"{current_message or enriched.get('message')} "
            f"SIR={enriched.get('candidate_generation_status')} "
            f"no_candidate={_counts_summary_text(no_candidate, limit=2)} "
            f"watch={_counts_summary_text(watch, limit=2)} "
            f"non_blocking={_counts_summary_text(non_blocking, limit=2)} "
            f"order_blocking={_counts_summary_text(order_blocking, limit=2)} "
            f"{signal_reason_clause}{signal_window_clause} "
            f"SIR_opportunity=lookback_hours={lookback_hours},"
            f"active_expected={active_expected_orders},"
            f"lookback_expected={lookback_expected_orders},"
            f"pre_restart={lookback_pre_restart_orders},"
            f"blocked_or_skipped={lookback_blocked_or_skipped},"
            f"blocking_reasons={reason_summary or 'none'}"
            f"{direction_filter_clause}"
            f"{coverage_clause}"
        )
        return enriched
    if lookback_expected_orders > 0 and lookback_pre_restart_orders > 0 and not order_blocking:
        reason_summary = _counts_summary_text(lookback_reason_counts, limit=3)
        enriched["alert"] = False
        enriched["status"] = "OK"
        enriched["severity"] = "INFO"
        enriched["reason"] = "sir_pre_restart_expected_orders_advisory"
        enriched["historical_advisory"] = True
        enriched["candidate_generation_status"] = "pre_restart_backtest_opportunities_advisory"
        enriched["next_action_text"] = (
            f"재시작 전 {lookback_window_label} SIR 백테스트조건 후보 {lookback_pre_restart_orders}건이 주문으로 못 간 이력 기록: "
            f"{reason_summary or 'reason=none'}{coverage_note}; 현재 런타임은 다음 fresh 후보 submit_ready 여부만 확인"
            f"{current_signal_note}{direction_filter_note}"
        )
        previous_next_action = str(evaluation.get("next_action_text") or "")
        current_message = str(enriched.get("message") or "")
        if previous_next_action and current_message:
            current_message = current_message.replace(
                f"actions={previous_next_action}",
                f"actions={enriched.get('next_action_text')}",
            )
        enriched["message"] = (
            f"{current_message or enriched.get('message')} "
            f"SIR={enriched.get('candidate_generation_status')} "
            f"no_candidate={_counts_summary_text(no_candidate, limit=2)} "
            f"watch={_counts_summary_text(watch, limit=2)} "
            f"non_blocking={_counts_summary_text(non_blocking, limit=2)} "
            f"order_blocking={_counts_summary_text(order_blocking, limit=2)} "
            f"{signal_reason_clause}{signal_window_clause} "
            f"SIR_opportunity=lookback_hours={lookback_hours},"
            f"active_expected={active_expected_orders},"
            f"lookback_expected={lookback_expected_orders},"
            f"pre_restart={lookback_pre_restart_orders},"
            f"lookback_reasons={reason_summary or 'none'}"
            f"{direction_filter_clause}"
            f"{coverage_clause}"
        )
        return enriched
    if order_blocking:
        enriched["alert"] = True
        enriched["status"] = "ALERT"
        enriched["severity"] = "WARN"
        enriched["reason"] = "sir_runtime_order_blocking_audit_present"
        enriched["candidate_generation_status"] = "order_blocking_audit_present"
        enriched["next_action_text"] = f"SIR runtime audit order_blocking 확인: {_counts_summary_text(order_blocking)}"
    elif no_candidate:
        enriched["candidate_generation_status"] = "no_live_route_candidate"
        signal_text = f"; 신호 없음 이유: {signal_reason_text}" if signal_reason_text != "none" else ""
        enriched["next_action_text"] = (
            f"SIR fresh 후보 대기: {_counts_summary_text(no_candidate)}"
            f"{signal_text}{_signal_window_note(signal_window_schedule)}"
        )
    elif watch:
        enriched["candidate_generation_status"] = "watch_candidate_context"
        enriched["next_action_text"] = f"SIR 후보 생성 watch 확인: {_counts_summary_text(watch)}"
    elif non_blocking:
        enriched["candidate_generation_status"] = "non_blocking_route_context"
        enriched["next_action_text"] = f"SIR route context 확인: {_counts_summary_text(non_blocking)}"
    elif _safe_int(context.get("audit_count")) == 0:
        enriched["candidate_generation_status"] = "no_recent_sir_runtime_audits"
        enriched["next_action_text"] = "SIR runtime audit 최신성 확인; 최근 auto-route audit 없음"
    else:
        enriched["candidate_generation_status"] = "sir_runtime_audit_clean"
    previous_next_action = str(evaluation.get("next_action_text") or "")
    current_message = str(enriched.get("message") or "")
    if previous_next_action and current_message:
        current_message = current_message.replace(
            f"actions={previous_next_action}",
            f"actions={enriched.get('next_action_text')}",
        )
    enriched["message"] = (
        f"{current_message or enriched.get('message')} "
        f"SIR={enriched.get('candidate_generation_status')} "
        f"no_candidate={_counts_summary_text(no_candidate, limit=2)} "
        f"watch={_counts_summary_text(watch, limit=2)} "
        f"non_blocking={_counts_summary_text(non_blocking, limit=2)} "
        f"order_blocking={_counts_summary_text(order_blocking, limit=2)} "
        f"{signal_reason_clause}{signal_window_clause} "
        f"SIR_opportunity=lookback_hours={lookback_hours},"
        f"active_expected={active_expected_orders},lookback_expected={lookback_expected_orders}"
        f"{direction_filter_clause}"
        f"{coverage_clause}"
    )
    return enriched


def evaluate_no_order_watchdog(*, lifecycle: dict[str, Any], min_intents: int) -> dict[str, Any]:
    summary = dict(lifecycle.get("summary") or {})
    live_intents = dict(summary.get("live_intents") or {})
    intent_count = _safe_int(live_intents.get("total"))
    distinct_plan_count = _safe_int(live_intents.get("distinct_plan_count"), default=intent_count)
    duplicate_plan_intent_count = _safe_int(live_intents.get("duplicate_plan_intent_count"))
    submit_ready = _safe_int(live_intents.get("submit_ready"))
    blocked = _safe_int(live_intents.get("blocked"))
    submission_count = _safe_int(summary.get("submission_count"))
    requested_live_count = _safe_int(summary.get("requested_live_count"))
    rejected_or_error = _safe_int(summary.get("rejected_or_error_count"))
    top_reasons = dict(live_intents.get("top_block_reasons") or {})
    diagnostics = _blocked_intent_diagnostics(lifecycle)

    alert = False
    reason = "no_recent_live_intents"
    severity = "INFO"
    if intent_count >= max(1, int(min_intents)) and requested_live_count == 0:
        alert = True
        severity = "WARN"
        reason = "live_intents_without_live_order_submission"
    if submit_ready > 0 and submission_count == 0:
        alert = True
        severity = "FAIL"
        reason = "submit_ready_intents_without_submission"
    if rejected_or_error > 0:
        alert = True
        severity = "FAIL"
        reason = "live_submission_rejected_or_error"

    if diagnostics:
        next_action_text = _diagnostic_actions_text(diagnostics)
    elif reason == "submit_ready_intents_without_submission":
        next_action_text = "submit-ready intent가 live submission으로 이어졌는지 즉시 확인"
    elif reason == "live_submission_rejected_or_error":
        next_action_text = "rejected/error live submission 상세와 exchange adapter 응답 확인"
    elif reason == "live_intents_without_live_order_submission":
        next_action_text = "blocked intent reason payload 확인"
    else:
        next_action_text = "fresh live 후보 대기; 현재 차단 사유 없음"

    duplicate_text = (
        f", distinct_plans={distinct_plan_count}, duplicate_intents={duplicate_plan_intent_count}"
        if duplicate_plan_intent_count > 0
        else ""
    )
    message = (
        f"최근 live intent {intent_count}건, live 주문 제출 {requested_live_count}건. "
        f"submit_ready={submit_ready}, blocked={blocked}, reasons={_top_reasons_text(top_reasons)}, "
        f"actions={next_action_text}{duplicate_text}"
    )
    return {
        "alert": alert,
        "status": "ALERT" if alert else "OK",
        "severity": severity,
        "reason": reason,
        "message": message,
        "intent_count": intent_count,
        "distinct_plan_count": distinct_plan_count,
        "duplicate_plan_intent_count": duplicate_plan_intent_count,
        "top_duplicate_plan_ids": dict(live_intents.get("top_duplicate_plan_ids") or {}),
        "submit_ready": submit_ready,
        "blocked": blocked,
        "submission_count": submission_count,
        "requested_live_count": requested_live_count,
        "rejected_or_error_count": rejected_or_error,
        "top_block_reasons": top_reasons,
        "blocked_intent_diagnostics": diagnostics,
        "first_block_detail_text": _diagnostic_detail_text(diagnostics),
        "next_action_text": next_action_text,
    }


def _cooldown_allows(*, state_file: Path, dedupe_key: str, cooldown_minutes: int, now: datetime, force: bool) -> bool:
    if force:
        return True
    state = _read_json(state_file)
    if str(state.get("dedupe_key") or "") != dedupe_key:
        return True
    last_sent_raw = str(state.get("last_sent_at") or "")
    try:
        last_sent = datetime.fromisoformat(last_sent_raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    if last_sent.tzinfo is None:
        last_sent = last_sent.replace(tzinfo=UTC)
    return now - last_sent.astimezone(UTC) >= timedelta(minutes=max(1, int(cooldown_minutes)))


def _watchdog_message(payload: dict[str, Any]) -> str:
    evaluation = dict(payload.get("evaluation") or {})
    detail_text = str(evaluation.get("first_block_detail_text") or "")
    top_reasons = _top_reasons_text(dict(evaluation.get("top_block_reasons") or {}), limit=3)
    scope_label = str(payload.get("watchdog_scope_label") or f"최근 {payload.get('window_days')}일")
    next_action_text = str(evaluation.get("next_action_text") or "").strip() or _diagnostic_actions_text(
        list(evaluation.get("blocked_intent_diagnostics") or []),
        limit=2,
    )
    lines = [
        "MICRO_LIVE 주문 없음",
        (
            f"{scope_label}: "
            f"{_intent_count_text(evaluation.get('intent_count'), evaluation.get('distinct_plan_count'), evaluation.get('duplicate_plan_intent_count'))} / "
            f"제출 {evaluation.get('requested_live_count')}건"
        ),
    ]
    if str(payload.get("watchdog_scope") or "") == "runtime_since_ws_start":
        runtime_age = _runtime_age_text(payload.get("runtime_age_minutes"))
        if runtime_age:
            lines.append(f"런타임: 재시작 후 {runtime_age} 경과")
        lookback_summary = dict(payload.get("lookback_lifecycle_summary") or {})
        lookback_intents, lookback_distinct_plans, lookback_duplicate_intents, lookback_submissions = _summary_intent_plan_counts(lookback_summary)
        lines.append(
            f"참고: 최근 {payload.get('window_days')}일 전체 "
            f"{_intent_count_text(lookback_intents, lookback_distinct_plans, lookback_duplicate_intents)} / "
            f"제출 {lookback_submissions}건"
        )
    candidate_context = dict(evaluation.get("candidate_generation_context") or payload.get("candidate_generation_context") or {})
    if candidate_context:
        signal_reason_counts = dict(candidate_context.get("latest_signal_reason_counts") or {})
        signal_text = (
            f" / signal_reasons={_counts_summary_text(signal_reason_counts, limit=2)}"
            if signal_reason_counts
            else ""
        )
        lines.append(
            "후보: "
            f"SIR audit {candidate_context.get('audit_count', 0)}건 / "
            f"no_candidate={_counts_summary_text(dict(candidate_context.get('no_candidate_status_counts') or {}), limit=2)} / "
            f"watch={_counts_summary_text(dict(candidate_context.get('watch_status_counts') or {}), limit=2)} / "
            f"non_blocking={_counts_summary_text(dict(candidate_context.get('non_blocking_status_counts') or {}), limit=2)} / "
            f"order_blocking={_counts_summary_text(dict(candidate_context.get('order_blocking_status_counts') or {}), limit=2)}"
            f"{signal_text}"
        )
        signal_window_text = _signal_window_summary_text(dict(candidate_context.get("signal_window_schedule") or {}))
        if signal_window_text:
            lines.append(f"신호창: {signal_window_text}")
    opportunity_context = dict(evaluation.get("session_impulse_retest_opportunity_context") or {})
    if opportunity_context:
        lookback_label = _lookback_hours_label(
            opportunity_context.get("lookback_hours"),
            fallback_days=payload.get("window_days"),
        )
        active_summary = dict(opportunity_context.get("summary") or {})
        lookback_summary = dict(opportunity_context.get("lookback_summary") or {})
        active_perf = dict(active_summary.get("potential_performance") or {})
        lookback_perf = dict(lookback_summary.get("potential_performance") or {})
        pre_restart_count = _safe_int(lookback_summary.get("before_current_runtime_start_count"))
        direction_filtered_count = _safe_int(opportunity_context.get("direction_filtered_count"))
        lookback_reason_text = _counts_summary_text(dict(lookback_summary.get("reason_counts") or {}), limit=3)
        pre_restart_text = (
            f", pre_restart={pre_restart_count}건"
            if pre_restart_count > 0
            else ""
        )
        direction_filtered_text = (
            f", direction_filtered={direction_filtered_count}건"
            if direction_filtered_count > 0
            else ""
        )
        reason_text = (
            f", reasons={lookback_reason_text}"
            if lookback_reason_text
            else ""
        )
        lines.append(
            f"백테스트조건({lookback_label}): "
            f"runtime_expected={active_summary.get('expected_order_count', 0)}건/"
            f"{active_perf.get('total_r', 0)}R, "
            f"lookback_expected={lookback_summary.get('expected_order_count', 0)}건/"
            f"{lookback_perf.get('total_r', 0)}R"
            f"{pre_restart_text}"
            f"{direction_filtered_text}"
            f"{reason_text}"
        )
    lines.extend(
        [
            f"원인: {top_reasons}",
            f"상세: {detail_text or '없음'}",
            f"다음: {next_action_text}",
        ]
    )
    return "\n".join(
        lines
    )


def build_payload(*, days: int, limit: int, min_intents: int) -> dict[str, Any]:
    init_db()
    settings = get_settings()
    family_filter = _csv_set(getattr(settings, "auto_trading_micro_live_allowed_families", ""))
    if not family_filter:
        family_filter = _csv_set(getattr(settings, "auto_trading_allowed_families", ""))
    symbol_filter = _csv_upper_set(getattr(settings, "auto_trading_micro_live_allowed_symbols", ""))
    if not symbol_filter:
        symbol_filter = _csv_upper_set(getattr(settings, "auto_trading_allowed_symbols", ""))
    runtime_started_at = _ws_runtime_started_at()
    generated_at = datetime.now(UTC)
    with SessionLocal() as db:
        reporter = LiveOrderLifecycleReporter(db)
        lookback_lifecycle = reporter.generate(
            days=days,
            live_only=True,
            limit=limit,
            symbols=sorted(symbol_filter),
            strategy_families=sorted(family_filter),
        )
        lifecycle = reporter.generate(
            days=days,
            live_only=True,
            limit=limit,
            start_at=runtime_started_at,
            symbols=sorted(symbol_filter),
            strategy_families=sorted(family_filter),
        ) if runtime_started_at is not None else lookback_lifecycle
        candidate_context = (
            _session_impulse_retest_candidate_context(
                db=db,
                hours=max(1, int(days)) * 24,
                limit=max(1, int(limit)),
                runtime_started_at=runtime_started_at,
            )
            if "session_impulse_retest" in family_filter
            else _disabled_sir_candidate_context()
        )
        if "session_impulse_retest" in family_filter:
            signal_window_schedule = _session_impulse_retest_signal_window_context(
                symbols=sorted(symbol_filter),
                generated_at=generated_at,
            )
            if signal_window_schedule:
                candidate_context["signal_window_schedule"] = signal_window_schedule
        opportunity_context = (
            _session_impulse_retest_opportunity_context(hours=max(1, int(days)) * 24)
            if "session_impulse_retest" in family_filter
            else {}
        )
    evaluation = evaluate_no_order_watchdog(lifecycle=lifecycle, min_intents=min_intents)
    evaluation = _augment_no_order_evaluation(
        evaluation,
        candidate_context=candidate_context,
        opportunity_context=opportunity_context,
    )
    overall_status = str(evaluation.get("status") or ("ALERT" if _safe_bool(evaluation.get("alert")) else "OK")).upper()
    watchdog_scope = "runtime_since_ws_start" if runtime_started_at is not None else "lookback_window"
    runtime_age = _runtime_age_minutes(generated_at=generated_at, runtime_started_at=runtime_started_at)
    runtime_sampling_note = (
        "current runtime scope resets on WS worker restart; use lookback summaries for pre-restart order context"
        if runtime_started_at is not None
        else "lookback window scope"
    )
    return {
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "overall_status": overall_status,
        "window_days": max(1, int(days)),
        "runtime_started_at": runtime_started_at.isoformat() if runtime_started_at else None,
        "runtime_age_minutes": runtime_age,
        "runtime_sampling_note": runtime_sampling_note,
        "watchdog_scope": watchdog_scope,
        "watchdog_scope_label": _watchdog_scope_label(runtime_started_at=runtime_started_at, days=days),
        "lookback_window_start": lookback_lifecycle.get("window_start"),
        "family_filter": sorted(family_filter),
        "symbol_filter": sorted(symbol_filter),
        "min_intents": max(1, int(min_intents)),
        "evaluation": evaluation,
        "candidate_generation_context": candidate_context,
        "session_impulse_retest_opportunity_context": opportunity_context,
        "lifecycle_summary": dict(lifecycle.get("summary") or {}),
        "runtime_lifecycle_summary": dict(lifecycle.get("summary") or {}),
        "lookback_lifecycle_summary": dict(lookback_lifecycle.get("summary") or {}),
    }


def _write_report(path: Path, payload: dict[str, Any], *, atomic: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    evaluation = dict(payload.get("evaluation") or {})
    lines = [
        "# MICRO_LIVE No-Order Watchdog",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- overall_status: {payload.get('overall_status') or evaluation.get('status')}",
        f"- status: {evaluation.get('status')}",
        f"- severity: {evaluation.get('severity')}",
        f"- reason: {evaluation.get('reason')}",
        f"- watchdog_scope: {payload.get('watchdog_scope')}",
        f"- watchdog_scope_label: {payload.get('watchdog_scope_label')}",
        f"- runtime_started_at: {payload.get('runtime_started_at') or 'none'}",
        f"- runtime_age_minutes: {payload.get('runtime_age_minutes') if payload.get('runtime_age_minutes') is not None else 'none'}",
        f"- runtime_sampling_note: {payload.get('runtime_sampling_note') or 'none'}",
        f"- lookback_window_start: {payload.get('lookback_window_start') or 'none'}",
        f"- symbol_filter: {','.join(payload.get('symbol_filter') or []) or 'none'}",
        f"- message: {evaluation.get('message')}",
        f"- first_block_detail: {evaluation.get('first_block_detail_text') or 'none'}",
        f"- actions: {evaluation.get('next_action_text') or _diagnostic_actions_text(list(evaluation.get('blocked_intent_diagnostics') or []))}",
        "",
        "```json",
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        "```",
    ]
    content = "\n".join(lines)
    if atomic:
        _atomic_write_text(path, content)
    else:
        _atomic_write_text(path, content)


def _write_latest_aliases(*, report_dir: Path, payload: dict[str, Any]) -> dict[str, str]:
    latest_md = report_dir / "latest.md"
    latest_json = report_dir / "latest.json"
    _write_report(latest_md, payload, atomic=True)
    _atomic_write_text(latest_json, json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return {
        "latest_report_path": _display_path(latest_md),
        "latest_json_path": _display_path(latest_json),
    }


def _notification_delivered(result: dict[str, Any]) -> bool:
    return _safe_bool(dict(result or {}).get("delivered"))


def main() -> int:
    args = parse_args()
    payload = build_payload(days=max(1, int(args.days)), limit=max(1, int(args.limit)), min_intents=max(1, int(args.min_intents)))
    evaluation = dict(payload.get("evaluation") or {})
    payload.setdefault(
        "overall_status",
        str(evaluation.get("status") or ("ALERT" if _safe_bool(evaluation.get("alert")) else "OK")).upper(),
    )
    if not args.no_write_report:
        generated = parse_report_generated_at(payload.get("generated_at"))
        report_dir = ROOT_DIR / args.report_dir
        report_path = report_dir / f"micro_live_no_order_watchdog_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
        payload["report_path"] = _display_path(report_path)
        payload["latest_report_path"] = _display_path(report_dir / "latest.md")
        payload["latest_json_path"] = _display_path(report_dir / "latest.json")
        _write_report(report_path, payload, atomic=True)
        payload.update(_write_latest_aliases(report_dir=report_dir, payload=payload))

    alert_active = _safe_bool(evaluation.get("alert"))
    if bool(args.notify) and alert_active:
        state_file = _resolve_root_path(str(args.state_file))
        dedupe_key = f"{evaluation.get('reason')}:{_top_reasons_text(dict(evaluation.get('top_block_reasons') or {}), limit=4)}"
        now = datetime.now(UTC)
        if _cooldown_allows(
            state_file=state_file,
            dedupe_key=dedupe_key,
            cooldown_minutes=max(1, int(args.cooldown_minutes)),
            now=now,
            force=bool(args.force_notify),
        ):
            settings = get_settings()
            notification_status = str(evaluation.get("status") or "WARN").upper()
            if str(evaluation.get("severity") or "").upper() == "FAIL":
                notification_status = "FAIL"
            delivery = NotificationDispatcher(settings).dispatch(
                channel=str(args.channel),
                alert_type="micro_live_no_order_watchdog",
                symbol="MICRO_LIVE",
                payload={
                    "status": notification_status,
                    "force_send": True,
                    "message": _watchdog_message(payload),
                    "report_path": payload.get("report_path"),
                },
            )
            payload["notification"] = delivery
            if _notification_delivered(delivery):
                _write_json(state_file, {"dedupe_key": dedupe_key, "last_sent_at": now.isoformat().replace("+00:00", "Z")})
            else:
                payload["notification_state"] = {
                    "skipped": True,
                    "reason": "delivery_not_confirmed",
                    "dedupe_key": dedupe_key,
                }
        else:
            payload["notification"] = {"skipped": True, "reason": "cooldown_active"}

    if not bool(args.quiet):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 1 if alert_active and not bool(args.no_fail_exit) else 0


if __name__ == "__main__":
    raise SystemExit(main())
