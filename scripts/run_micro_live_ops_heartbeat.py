#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.notification_dispatcher import NotificationDispatcher
from scripts.operation_report_io import atomic_write_text, parse_report_generated_at


_DEFAULT_JOBS: dict[str, Any] = {
    "runtime_guard": {
        "pattern": "reports/operations/micro_live_runtime_guard/*.md",
        "max_age_minutes": 35,
        "pass_statuses": {"PASS"},
        "watch_statuses": {"WATCH"},
        "requires_current_runtime": True,
    },
    "no_order_watchdog": {
        "pattern": "reports/operations/micro_live_no_order_watchdog/*.md",
        "max_age_minutes": 75,
        "pass_statuses": {"OK", "PASS"},
        "watch_statuses": {"ALERT", "WATCH", "WARN"},
        "requires_current_runtime": True,
    },
    "reconciliation_watchdog": {
        "pattern": "reports/operations/live_reconciliation_watchdog/*.md",
        "max_age_minutes": 20,
        "pass_statuses": {"OK", "PASS"},
        "watch_statuses": {"WATCH", "WARN"},
    },
    "live_account_protection_audit": {
        "pattern": "reports/operations/live_account_protection_audit/*.md",
        "max_age_minutes": 20,
        "pass_statuses": {"OK", "PASS"},
        "watch_statuses": {"ALERT", "WATCH", "WARN"},
    },
    "live_leverage_cap_sync": {
        "pattern": "reports/operations/live_leverage_cap_sync/*.md",
        "max_age_minutes": 75,
        "pass_statuses": {"OK", "PASS"},
        "watch_statuses": {"WATCH", "WARN"},
    },
    "synthetic_canary": {
        "pattern": "reports/operations/micro_live_synthetic_canary/*.md",
        "max_age_minutes": 130,
        "pass_statuses": {"PASS"},
    },
    "liquidity_universe": {
        "pattern": "reports/operations/micro_live_liquidity_universe/*.md",
        "max_age_minutes": 190,
        "pass_statuses": {"PASS", "WATCH"},
    },
    "boot_check": {
        "pattern": "reports/operations/micro_live_boot_check/*.md",
        "max_age_minutes": 35,
        "pass_statuses": {"PASS"},
        "requires_current_runtime": True,
    },
    "live_candidate_promotion_readiness": {
        "pattern": "reports/operations/live_candidate_promotion_readiness/*.md",
        "max_age_minutes": 20,
        "pass_statuses": {"PASS"},
        "watch_statuses": {"WATCH"},
        "requires_current_runtime": True,
    },
    "validation_report_refresh": {
        "pattern": "reports/operations/validation_report_refresh/*.md",
        "max_age_minutes": 300,
        "pass_statuses": {"PASS"},
    },
    "binance_rule_drift": {
        "pattern": "reports/operations/binance_rule_snapshots/latest.json",
        "max_age_minutes": 1800,
        "pass_statuses": {"PASS"},
        "watch_statuses": {"DRIFT", "WATCH"},
    },
    "replay_validation_bridge": {
        "pattern": "reports/operations/replay_validation_bridge/*.md",
        "max_age_minutes": 1800,
        "pass_statuses": {"PASS"},
        "watch_statuses": {"WATCH", "ALERT"},
    },
    "live_replay_parity": {
        "pattern": "reports/operations/live_replay_parity/*.md",
        "max_age_minutes": 130,
        "pass_statuses": {"PASS"},
        "watch_statuses": {"WATCH"},
        "requires_current_runtime": True,
    },
    "session_impulse_retest_runtime_audit": {
        "pattern": "reports/operations/session_impulse_retest_runtime_audit/*.md",
        "max_age_minutes": 75,
        "pass_statuses": {"PASS"},
        "watch_statuses": {"WATCH"},
        "requires_current_runtime": True,
    },
    "entry_surface": {
        "pattern": "reports/operations/entry_surface/latest_entry_alert_run.json",
        "max_age_minutes": 15,
        "content_type": "entry_surface_run",
        "pass_statuses": {"PASS"},
        "watch_statuses": {"WATCH"},
        "requires_current_runtime": True,
    },
    "failure_drill": {
        "pattern": "reports/operations/micro_live_failure_drill/*.md",
        "max_age_minutes": 1800,
        "pass_statuses": {"PASS"},
    },
    "macro_calendar_blackouts": {
        "pattern": "reports/validation/contracts/micro_live_event_blackouts_*",
        "path_setting": "auto_trading_micro_live_event_blackout_path",
        "max_age_minutes": 1800,
        "content_type": "macro_blackout_contract",
        "pass_statuses": {"PASS"},
        "stale_status": "WATCH",
    },
    "competing_trading_runtime": {
        "pattern": "",
        "max_age_minutes": 0,
        "content_type": "competing_trading_runtime",
        "pass_statuses": {"PASS"},
        "watch_statuses": {"WATCH"},
    },
}

_DEFAULT_FORBIDDEN_LAUNCHD_LABELS = (
    "com.yumin.real.bybitbot",
    "com.yumin.real.retrain",
)

_DEFAULT_FORBIDDEN_PROCESS_PATTERNS = (
    r"IdeaProjects/real1",
    r"\bbot\.main\b",
    r"\bpybit\b",
)


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


def _csv_values(raw_value: str, *, defaults: tuple[str, ...]) -> list[str]:
    value = str(raw_value or "").strip()
    if not value:
        return list(defaults)
    if value.lower() in {"none", "off", "disabled", "0"}:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _forbidden_launchd_labels() -> list[str]:
    return _csv_values(
        os.environ.get("TRADING_FORBIDDEN_LAUNCHD_LABELS", ""),
        defaults=_DEFAULT_FORBIDDEN_LAUNCHD_LABELS,
    )


def _forbidden_process_patterns() -> list[str]:
    return _csv_values(
        os.environ.get("TRADING_FORBIDDEN_PROCESS_PATTERNS", ""),
        defaults=_DEFAULT_FORBIDDEN_PROCESS_PATTERNS,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check that scheduled MICRO_LIVE operating guard reports are still being produced.")
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--force-notify", action="store_true")
    parser.add_argument("--cooldown-minutes", type=int, default=360)
    parser.add_argument("--channel", choices=["discord", "system"], default="discord")
    parser.add_argument("--report-dir", default="reports/operations/micro_live_ops_heartbeat")
    parser.add_argument("--state-file", default="reports/operations/micro_live_ops_heartbeat/state.json")
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


def _report_root_dir() -> Path:
    configured = (
        os.environ.get("TRADING_OPS_HEARTBEAT_REPORT_ROOT")
        or os.environ.get("TRADING_OPERATIONS_REPORT_ROOT")
        or ""
    )
    if configured.strip():
        return Path(configured).expanduser()
    runtime_root = Path(
        os.environ.get("TRADING_TMP_RUNTIME_ROOT")
        or str(Path.home() / "Library/Application Support/trading/runtime_src")
    ).expanduser()
    try:
        if runtime_root.resolve() != ROOT_DIR.resolve() and (runtime_root / "reports").is_dir():
            return runtime_root
    except OSError:
        pass
    return ROOT_DIR


def _resolve_report_path(raw_path: str) -> Path:
    path = Path(str(raw_path or "")).expanduser()
    return path if path.is_absolute() else _report_root_dir() / path


def _latest_match(pattern: str) -> Path | None:
    resolved = _resolve_report_path(pattern)
    matches = [Path(path) for path in glob.glob(str(resolved))]
    files = [path for path in matches if path.is_file() and not path.name.startswith(".")]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def _coerce_job_config(raw_config: Any) -> dict[str, Any]:
    if isinstance(raw_config, dict):
        return {
            "pattern": str(raw_config.get("pattern") or ""),
            "path_setting": str(raw_config.get("path_setting") or ""),
            "max_age_minutes": int(raw_config.get("max_age_minutes") or 0),
            "content_type": str(raw_config.get("content_type") or ""),
            "min_horizon_days": raw_config.get("min_horizon_days"),
            "stale_status": str(raw_config.get("stale_status") or "FAIL").upper(),
            "requires_current_runtime": _safe_bool(raw_config.get("requires_current_runtime")),
            "pass_statuses": {str(item).upper() for item in set(raw_config.get("pass_statuses") or set())},
            "watch_statuses": {str(item).upper() for item in set(raw_config.get("watch_statuses") or set())},
        }
    pattern, max_age_minutes = raw_config
    return {
        "pattern": str(pattern),
        "path_setting": "",
        "max_age_minutes": int(max_age_minutes),
        "content_type": "",
        "min_horizon_days": None,
        "stale_status": "FAIL",
        "requires_current_runtime": False,
        "pass_statuses": {"PASS", "OK"},
        "watch_statuses": set(),
    }


def _json_payload_from_markdown(text: str) -> dict[str, Any]:
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _status_payload_from_markdown(text: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in ("overall_status", "status"):
        match = re.search(rf"^- {key}:\s*([^\n]+)", text, flags=re.MULTILINE)
        if match:
            payload[key] = match.group(1).strip()
    return payload


def _read_report_payload(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return dict(payload) if isinstance(payload, dict) else {}
    return _json_payload_from_markdown(text) or _status_payload_from_markdown(text)


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


def _configured_path_from_setting(setting_name: str) -> Path | None:
    if not setting_name:
        return None
    raw_path = str(getattr(get_settings(), setting_name, "") or "").strip()
    if not raw_path:
        return None
    return _resolve_report_path(raw_path)


def _parse_utc_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _report_generated_at(payload: dict[str, Any], *, fallback_mtime: datetime) -> datetime:
    candidates = [
        payload.get("generated_at"),
        dict(payload.get("evaluation") or {}).get("generated_at"),
        dict(payload.get("readiness") or {}).get("evaluated_at"),
    ]
    current = dict(payload.get("current") or {})
    if current:
        candidates.append(current.get("generated_at"))
    for value in candidates:
        parsed = _parse_utc_ts(value)
        if parsed is not None:
            return parsed
    return fallback_mtime.astimezone(UTC) if fallback_mtime.tzinfo is not None else fallback_mtime.replace(tzinfo=UTC)


def _runtime_started_at_from_heartbeat() -> datetime | None:
    heartbeat_dir = (
        os.environ.get("RUNTIME_WORKER_HEARTBEAT_DIR")
        or os.environ.get("TRADING_HEARTBEAT_DIR")
        or str(getattr(get_settings(), "runtime_worker_heartbeat_dir", "") or "")
        or str(Path.home() / "Library/Application Support/trading/heartbeats")
    )
    payload = _read_json(Path(heartbeat_dir).expanduser() / "ws.json")
    details = dict(payload.get("details") or {}) if isinstance(payload, dict) else {}
    return _parse_utc_ts(details.get("started_at") or payload.get("started_at"))


def _macro_blackout_contract_status(*, payload: dict[str, Any], now: datetime, min_horizon_days: int) -> dict[str, Any]:
    windows = payload.get("windows") if isinstance(payload, dict) else []
    if not isinstance(windows, list) or not windows:
        return {
            "overall_status": "FAIL",
            "status_detail": "macro_blackout_contract_has_no_windows",
            "horizon_days": 0.0,
            "upcoming_windows": 0,
            "invalid_windows": 0,
        }
    current = now.astimezone(UTC) if now.tzinfo is not None else now.replace(tzinfo=UTC)
    dated_windows: list[tuple[datetime, datetime, str]] = []
    invalid_count = 0
    for item in windows:
        row = dict(item or {}) if isinstance(item, dict) else {}
        start_utc = _parse_utc_ts(row.get("start_utc"))
        end_utc = _parse_utc_ts(row.get("end_utc"))
        if start_utc is None or end_utc is None or end_utc <= start_utc:
            invalid_count += 1
            continue
        dated_windows.append((start_utc, end_utc, str(row.get("label") or "unnamed")))
    if not dated_windows:
        return {
            "overall_status": "FAIL",
            "status_detail": "macro_blackout_contract_has_no_valid_windows",
            "horizon_days": 0.0,
            "upcoming_windows": 0,
            "invalid_windows": invalid_count,
        }
    future_windows = sorted((row for row in dated_windows if row[1] > current), key=lambda row: row[0])
    if not future_windows:
        last_end = max(row[1] for row in dated_windows)
        return {
            "overall_status": "FAIL",
            "status_detail": "macro_blackout_contract_expired",
            "horizon_days": 0.0,
            "upcoming_windows": 0,
            "invalid_windows": invalid_count,
            "last_end": last_end.isoformat().replace("+00:00", "Z"),
        }
    max_end = max(row[1] for row in future_windows)
    horizon_days = max((max_end - current).total_seconds(), 0.0) / 86400.0
    next_start, next_end, next_label = future_windows[0]
    threshold = max(1, int(min_horizon_days))
    return {
        "overall_status": "PASS" if horizon_days >= threshold else "FAIL",
        "status_detail": "macro_blackout_horizon_ok" if horizon_days >= threshold else "macro_blackout_horizon_below_minimum",
        "horizon_days": round(horizon_days, 2),
        "min_horizon_days": threshold,
        "upcoming_windows": len(future_windows),
        "invalid_windows": invalid_count,
        "next_window": {
            "label": next_label,
            "start_utc": next_start.isoformat().replace("+00:00", "Z"),
            "end_utc": next_end.isoformat().replace("+00:00", "Z"),
        },
    }


def _entry_surface_run_status(*, payload: dict[str, Any]) -> dict[str, Any]:
    reason = str(payload.get("reason") or "").strip()
    if reason == "source_request_failed":
        return {
            "overall_status": "FAIL",
            "reason": "entry_surface_source_request_failed",
            "status_detail": "entry_surface_source_request_failed",
            "message": str(payload.get("error") or reason),
        }
    if reason == "entry_surface_tick_already_running":
        return {
            "overall_status": "WATCH",
            "reason": "entry_surface_previous_tick_still_running",
            "status_detail": "entry_surface_previous_tick_still_running",
            "message": reason,
        }
    delivery = dict(payload.get("delivery") or {}) if isinstance(payload.get("delivery"), dict) else {}
    if delivery and not _safe_bool(delivery.get("delivered")) and not _safe_bool(delivery.get("skipped")):
        return {
            "overall_status": "WATCH",
            "reason": "entry_surface_delivery_not_confirmed",
            "status_detail": "entry_surface_delivery_not_confirmed",
            "message": str(delivery.get("reason") or "delivery_not_confirmed"),
        }
    if not isinstance(payload.get("snapshot"), dict):
        return {
            "overall_status": "FAIL",
            "reason": "entry_surface_snapshot_missing",
            "status_detail": "entry_surface_snapshot_missing",
            "message": reason or "entry_surface_snapshot_missing",
        }
    expected_universe = _configured_universe_name()
    observed_universe = _entry_surface_observed_universe(payload)
    if expected_universe and observed_universe and observed_universe != expected_universe:
        operator_action = _entry_surface_operator_action(payload)
        return {
            "overall_status": "WATCH",
            "reason": "entry_surface_universe_mismatch",
            "status_detail": (
                f"entry_surface_universe_mismatch observed={observed_universe} expected={expected_universe}"
            ),
            "message": (
                f"entry surface is reading {observed_universe}, but live universe is {expected_universe}"
            ),
            "entry_surface_operator_action_state": str(operator_action.get("state") or ""),
            "entry_surface_operator_next_action": str(operator_action.get("next_action") or ""),
            "entry_surface_operator_route_reason": str(operator_action.get("top_route_mismatch_reason") or ""),
        }
    operator_action = _entry_surface_operator_action(payload)
    status_detail = _entry_surface_status_detail(reason or "entry_surface_run_ok", operator_action)
    message = str(operator_action.get("message") or "").strip() or reason or "entry_surface_run_ok"
    report_status = str(payload.get("overall_status") or payload.get("status") or "").strip().upper()
    if report_status not in {"PASS", "WATCH", "FAIL"}:
        operator_state = str(operator_action.get("state") or "").strip()
        report_status = "WATCH" if operator_state in {"live_order_candidate_present", "live_order_candidate_blocked"} else "PASS"
    return {
        "overall_status": report_status,
        "reason": reason or "entry_surface_run_ok",
        "status_detail": status_detail,
        "message": message,
        "entry_surface_operator_action_state": str(operator_action.get("state") or ""),
        "entry_surface_operator_next_action": str(operator_action.get("next_action") or ""),
        "entry_surface_operator_route_reason": str(operator_action.get("top_route_mismatch_reason") or ""),
    }


def _configured_universe_name() -> str:
    try:
        raw = getattr(get_settings(), "universe_name", "")
    except Exception:
        raw = ""
    return str(raw or "").strip().lower()


def _entry_surface_observed_universe(payload: dict[str, Any]) -> str:
    snapshot = dict(payload.get("snapshot") or {}) if isinstance(payload.get("snapshot"), dict) else {}
    for value in (payload.get("universe"), snapshot.get("universe"), snapshot.get("scope")):
        normalized = str(value or "").strip().lower()
        if normalized:
            return normalized
    return ""


def _entry_surface_operator_action(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("operator_action_summary")
    if not isinstance(raw, dict):
        snapshot = dict(payload.get("snapshot") or {})
        raw = snapshot.get("operator_action_summary")
    if not isinstance(raw, dict):
        return {}
    return {
        "state": str(raw.get("state") or "").strip(),
        "next_action": str(raw.get("next_action") or "").strip(),
        "message": str(raw.get("message") or "").strip(),
        "top_route_mismatch_reason": str(raw.get("top_route_mismatch_reason") or "").strip(),
    }


def _entry_surface_status_detail(base_reason: str, operator_action: dict[str, str]) -> str:
    base = str(base_reason or "entry_surface_run_ok").strip() or "entry_surface_run_ok"
    state = str(operator_action.get("state") or "").strip()
    if not state:
        return base
    parts = [base, f"operator_action={state}"]
    next_action = str(operator_action.get("next_action") or "").strip()
    if next_action:
        parts.append(f"next={next_action}")
    route_reason = str(operator_action.get("top_route_mismatch_reason") or "").strip()
    if route_reason and route_reason != "none":
        parts.append(f"route_reason={route_reason}")
    return " | ".join(parts)


def _launchctl_label_loaded(label: str) -> bool | None:
    launchctl = shutil.which("launchctl")
    if not launchctl or sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            [launchctl, "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.returncode == 0


def _matching_forbidden_processes(patterns: list[str]) -> list[dict[str, str]]:
    if not patterns:
        return []
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for pattern in patterns:
        try:
            compiled.append((pattern, re.compile(pattern)))
        except re.error:
            continue
    own_pid = str(os.getpid())
    matches: list[dict[str, str]] = []
    for raw_line in str(result.stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        pid, _, command = line.partition(" ")
        if pid.strip() == own_pid:
            continue
        for pattern, regex in compiled:
            if regex.search(command):
                matches.append(
                    {
                        "pid": pid.strip(),
                        "pattern": pattern,
                        "command": command[:300],
                    }
                )
                break
    return matches


def _competing_trading_runtime_status() -> dict[str, Any]:
    labels = _forbidden_launchd_labels()
    loaded_labels = [label for label in labels if _launchctl_label_loaded(label) is True]
    launchctl_checked = bool(shutil.which("launchctl") and sys.platform == "darwin")
    process_matches = _matching_forbidden_processes(_forbidden_process_patterns())
    if loaded_labels or process_matches:
        return {
            "overall_status": "FAIL",
            "status_detail": "competing_trading_runtime_detected",
            "message": "forbidden launchd label or stale trading process is active",
            "forbidden_launchd_labels_loaded": loaded_labels,
            "forbidden_process_matches": process_matches,
            "launchctl_checked": launchctl_checked,
        }
    return {
        "overall_status": "PASS",
        "status_detail": "no_competing_trading_runtime_detected",
        "message": "no forbidden launchd labels or stale trading processes detected",
        "forbidden_launchd_labels_loaded": [],
        "forbidden_process_matches": [],
        "launchctl_checked": launchctl_checked,
    }


def _report_status(payload: dict[str, Any]) -> str:
    for container in (payload, dict(payload.get("evaluation") or {})):
        for key in ("overall_status", "status"):
            value = str(container.get(key) or "").strip().upper()
            if value:
                return value
    return ""


def _report_reason(payload: dict[str, Any]) -> str:
    evaluation = dict(payload.get("evaluation") or {})
    for container in (evaluation, payload):
        for key in ("reason", "status_detail", "message"):
            value = str(container.get(key) or "").strip()
            if value:
                return value
    return ""


def _content_status_row(*, report_status: str, pass_statuses: set[str], watch_statuses: set[str]) -> dict[str, str]:
    if not pass_statuses:
        return {"content_status": "UNKNOWN", "content_reason": "content_status_not_checked"}
    if not report_status:
        return {"content_status": "FAIL", "content_reason": "content_status_missing"}
    if report_status in pass_statuses:
        return {"content_status": "PASS", "content_reason": "content_status_pass"}
    if report_status in watch_statuses:
        return {"content_status": "WATCH", "content_reason": f"content_status_{report_status.lower()}"}
    return {"content_status": "FAIL", "content_reason": f"content_status_{report_status.lower() or 'unaccepted'}"}


def _advisory_status_row(payload: dict[str, Any]) -> dict[str, str]:
    evaluation = dict(payload.get("evaluation") or {})
    if _safe_bool(evaluation.get("historical_advisory")):
        return {
            "advisory_status": "INFO",
            "advisory_reason": str(evaluation.get("reason") or "historical_advisory"),
            "advisory_detail": str(evaluation.get("next_action_text") or evaluation.get("message") or ""),
        }
    if _safe_bool(evaluation.get("lookback_advisory")):
        lookback_status = str(evaluation.get("lookback_status") or "WATCH").lower()
        lookback_reason = str(evaluation.get("lookback_reason") or "lookback_advisory")
        return {
            "advisory_status": "INFO",
            "advisory_reason": f"lookback_{lookback_status}_{lookback_reason}",
            "advisory_detail": str(evaluation.get("diagnosis") or lookback_reason),
        }
    return {"advisory_status": "", "advisory_reason": "", "advisory_detail": ""}


def evaluate_ops_heartbeat(*, now: datetime | None = None, jobs: dict[str, Any] | None = None) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    runtime_started_at = _runtime_started_at_from_heartbeat()
    report_root = _report_root_dir()
    rows: list[dict[str, Any]] = []
    for name, raw_config in (jobs or _DEFAULT_JOBS).items():
        config = _coerce_job_config(raw_config)
        pattern = str(config.get("pattern") or "")
        max_age_minutes = int(config.get("max_age_minutes") or 0)
        if str(config.get("content_type") or "") == "competing_trading_runtime":
            status_payload = _competing_trading_runtime_status()
            report_status = _report_status(status_payload)
            report_reason = _report_reason(status_payload)
            content = _content_status_row(
                report_status=report_status,
                pass_statuses=set(config.get("pass_statuses") or set()),
                watch_statuses=set(config.get("watch_statuses") or set()),
            )
            row_status = "FAIL" if content["content_status"] == "FAIL" else content["content_status"]
            if row_status == "UNKNOWN":
                row_status = "PASS"
            rows.append(
                {
                    "name": name,
                    "status": row_status,
                    "reason": content["content_reason"],
                    "pattern": pattern,
                    "path_source": "direct_check",
                    "configured_path": "",
                    "latest_path": "direct_check",
                    "latest_mtime": current.isoformat().replace("+00:00", "Z"),
                    "report_generated_at": current.isoformat().replace("+00:00", "Z"),
                    "runtime_started_at": runtime_started_at.isoformat().replace("+00:00", "Z")
                    if runtime_started_at is not None
                    else "",
                    "requires_current_runtime": False,
                    "age_minutes": 0.0,
                    "max_age_minutes": max_age_minutes,
                    "freshness_status": "PASS",
                    "report_status": report_status,
                    "report_reason": report_reason,
                    "status_detail": status_payload.get("status_detail", "") or report_reason,
                    **content,
                    "forbidden_launchd_labels_loaded": status_payload.get("forbidden_launchd_labels_loaded", []),
                    "forbidden_process_matches": status_payload.get("forbidden_process_matches", []),
                    "launchctl_checked": status_payload.get("launchctl_checked", False),
                }
            )
            continue
        configured_path = _configured_path_from_setting(str(config.get("path_setting") or ""))
        path_source = "configured_path" if configured_path is not None else "pattern_latest"
        latest = configured_path if configured_path is not None and configured_path.is_file() else _latest_match(pattern)
        if configured_path is not None and not configured_path.is_file():
            latest = None
        if latest is None:
            rows.append(
                {
                    "name": name,
                    "status": "FAIL",
                    "reason": "missing_report",
                    "pattern": pattern,
                    "path_source": path_source,
                    "configured_path": _display_path(configured_path) if configured_path is not None else "",
                    "latest_path": "",
                    "age_minutes": None,
                    "max_age_minutes": max_age_minutes,
                }
            )
            continue
        mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=UTC)
        age_minutes = max(0.0, (current - mtime).total_seconds() / 60.0)
        stale = age_minutes > float(max_age_minutes)
        report_payload = _read_report_payload(latest)
        report_generated_at = _report_generated_at(report_payload, fallback_mtime=mtime)
        status_payload: dict[str, Any] = {}
        if str(config.get("content_type") or "") == "macro_blackout_contract":
            min_horizon_raw = config.get("min_horizon_days")
            if min_horizon_raw in {None, ""}:
                min_horizon_raw = getattr(get_settings(), "auto_trading_micro_live_event_blackout_min_horizon_days", 45)
            status_payload = _macro_blackout_contract_status(
                payload=report_payload,
                now=current,
                min_horizon_days=int(min_horizon_raw or 45),
            )
            report_payload = {**report_payload, **status_payload}
        elif str(config.get("content_type") or "") == "entry_surface_run":
            status_payload = _entry_surface_run_status(payload=report_payload)
            report_payload = {**report_payload, **status_payload}
        report_status = _report_status(report_payload)
        report_reason = _report_reason(report_payload)
        content = _content_status_row(
            report_status=report_status,
            pass_statuses=set(config.get("pass_statuses") or set()),
            watch_statuses=set(config.get("watch_statuses") or set()),
        )
        advisory = _advisory_status_row(report_payload)
        stale_status = str(config.get("stale_status") or "FAIL").upper()
        if stale and stale_status not in {"PASS", "WATCH", "FAIL"}:
            stale_status = "FAIL"
        freshness_status = stale_status if stale else "PASS"
        pre_runtime_restart = (
            _safe_bool(config.get("requires_current_runtime"))
            and runtime_started_at is not None
            and report_generated_at < runtime_started_at - timedelta(seconds=5)
        )
        if pre_runtime_restart:
            freshness_status = "WATCH"
        row_status = "FAIL" if freshness_status == "FAIL" or content["content_status"] == "FAIL" else content["content_status"]
        if freshness_status == "WATCH" and row_status == "PASS":
            row_status = "WATCH"
        if row_status == "UNKNOWN":
            row_status = "PASS"
        rows.append(
            {
                "name": name,
                "status": row_status,
                "reason": "stale_report" if stale else content["content_reason"],
                "pattern": pattern,
                "path_source": path_source,
                "configured_path": _display_path(configured_path) if configured_path is not None else "",
                "latest_path": _display_path(latest),
                "latest_mtime": mtime.isoformat().replace("+00:00", "Z"),
                "report_generated_at": report_generated_at.isoformat().replace("+00:00", "Z"),
                "runtime_started_at": runtime_started_at.isoformat().replace("+00:00", "Z")
                if runtime_started_at is not None
                else "",
                "requires_current_runtime": _safe_bool(config.get("requires_current_runtime")),
                "age_minutes": round(age_minutes, 2),
                "max_age_minutes": max_age_minutes,
                "freshness_status": freshness_status,
                "report_status": report_status,
                "report_reason": report_reason,
                "status_detail": status_payload.get("status_detail", "") or report_reason,
                "entry_surface_operator_action_state": status_payload.get("entry_surface_operator_action_state"),
                "entry_surface_operator_next_action": status_payload.get("entry_surface_operator_next_action"),
                "entry_surface_operator_route_reason": status_payload.get("entry_surface_operator_route_reason"),
                "horizon_days": status_payload.get("horizon_days"),
                "upcoming_windows": status_payload.get("upcoming_windows"),
                "invalid_windows": status_payload.get("invalid_windows"),
                **content,
                **advisory,
            }
        )
        if pre_runtime_restart:
            rows[-1]["reason"] = "report_before_current_runtime_start"
            rows[-1]["status_detail"] = (
                f"report_generated_at={report_generated_at.isoformat().replace('+00:00', 'Z')} "
                f"runtime_started_at={runtime_started_at.isoformat().replace('+00:00', 'Z')}"
            )
    hard_failures = [row for row in rows if row["status"] == "FAIL"]
    warnings = [row for row in rows if row["status"] == "WATCH"]
    advisories = [row for row in rows if row.get("advisory_status")]
    issues = hard_failures + warnings
    status = "FAIL" if hard_failures else "WATCH" if warnings else "PASS"
    return {
        "status": status,
        "report_root": _display_path(report_root),
        "issue_count": len(issues),
        "advisory_count": len(advisories),
        "failure_count": len(hard_failures),
        "hard_failure_count": len(hard_failures),
        "warning_count": len(warnings),
        "jobs": rows,
        "issues": issues,
        "advisories": advisories,
        "failures": hard_failures,
        "hard_failures": hard_failures,
        "warnings": warnings,
    }


def build_payload() -> dict[str, Any]:
    generated_at = datetime.now(UTC)
    evaluation = evaluate_ops_heartbeat(now=generated_at)
    return {
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "overall_status": evaluation["status"],
        "evaluation": evaluation,
    }


def _write_report(path: Path, payload: dict[str, Any], *, atomic: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    evaluation = dict(payload.get("evaluation") or {})
    lines = [
        "# MICRO_LIVE Ops Heartbeat",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- overall_status: {payload.get('overall_status')}",
        f"- issue_count: {evaluation.get('issue_count')}",
        f"- failure_count: {evaluation.get('failure_count')}",
        f"- hard_failure_count: {evaluation.get('hard_failure_count')}",
        f"- warning_count: {evaluation.get('warning_count')}",
        "",
    ]
    for row in list(evaluation.get("jobs") or []):
        detail = ""
        if row.get("status_detail"):
            detail = f" | detail={row.get('status_detail')}"
        if row.get("horizon_days") is not None:
            detail += f" | horizon_days={row.get('horizon_days')}"
        if row.get("advisory_reason"):
            detail += f" | advisory={row.get('advisory_reason')}"
        lines.append(
            f"- {row.get('name')}: {row.get('status')} | {row.get('reason')} | report_status={row.get('report_status') or 'n/a'}{detail} | source={row.get('path_source') or 'n/a'} | latest={row.get('latest_path') or 'none'} | age={row.get('age_minutes')}"
        )
    lines.extend(["", "```json", json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), "```"])
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


def _issue_line(row: dict[str, Any]) -> str:
    name = str(row.get("name") or "unknown")
    status = str(row.get("status") or "UNKNOWN")
    report_status = str(row.get("report_status") or "n/a")
    reason = str(row.get("reason") or "unknown")
    parts = [f"{name}={status}/{report_status}", reason]
    if row.get("status_detail"):
        parts.append(str(row.get("status_detail")))
    if row.get("horizon_days") is not None:
        parts.append(f"horizon={row.get('horizon_days')}")
    if row.get("age_minutes") is not None:
        parts.append(f"age={row.get('age_minutes')}")
    return " ".join(parts)


def _issue_summary(rows: list[dict[str, Any]], *, limit: int = 3) -> str:
    if not rows:
        return "없음"
    clipped = rows[: max(1, int(limit))]
    suffix = f" 외 {len(rows) - len(clipped)}개" if len(rows) > len(clipped) else ""
    return "; ".join(_issue_line(dict(row)) for row in clipped) + suffix


def _advisory_line(row: dict[str, Any]) -> str:
    name = str(row.get("name") or "unknown")
    reason = str(row.get("advisory_reason") or "advisory")
    detail = str(row.get("advisory_detail") or "").strip()
    if len(detail) > 120:
        detail = f"{detail[:117]}..."
    return f"{name}={reason}" + (f" {detail}" if detail else "")


def _advisory_summary(rows: list[dict[str, Any]], *, limit: int = 3) -> str:
    if not rows:
        return "없음"
    clipped = rows[: max(1, int(limit))]
    suffix = f" 외 {len(rows) - len(clipped)}개" if len(rows) > len(clipped) else ""
    return "; ".join(_advisory_line(dict(row)) for row in clipped) + suffix


def _message(payload: dict[str, Any]) -> str:
    evaluation = dict(payload.get("evaluation") or {})
    hard_failures = list(evaluation.get("hard_failures") or [])
    warnings = list(evaluation.get("warnings") or [])
    advisories = list(evaluation.get("advisories") or [])
    next_action = "다음: FAIL은 즉시 조치, WATCH는 해당 리포트 원인 확인"
    if warnings and not hard_failures:
        next_action = "다음: WATCH는 자동 관찰; 반복/악화 시 해당 리포트 확인"
    if advisories and not warnings and not hard_failures:
        next_action = "다음: PASS 유지; 참고 항목은 자동 기록"
    return "\n".join(
        [
            "MICRO_LIVE 운영 점검",
            f"상태: {payload.get('overall_status')} / fail={evaluation.get('hard_failure_count')} watch={evaluation.get('warning_count')} advisory={evaluation.get('advisory_count', 0)}",
            f"긴급: {_issue_summary([dict(item) for item in hard_failures], limit=3)}",
            f"주의: {_issue_summary([dict(item) for item in warnings], limit=3)}",
            f"참고: {_advisory_summary([dict(item) for item in advisories], limit=3)}",
            next_action,
        ]
    )


def _issue_dedupe_key(payload: dict[str, Any]) -> str:
    evaluation = dict(payload.get("evaluation") or {})
    rows = [dict(item) for item in list(evaluation.get("issues") or []) if isinstance(item, dict)]
    parts = [
        "|".join(
            [
                str(row.get("name") or ""),
                str(row.get("status") or ""),
                str(row.get("report_status") or ""),
                str(row.get("reason") or ""),
                str(row.get("status_detail") or ""),
            ]
        )
        for row in rows
    ]
    return f"{payload.get('overall_status')}:" + ";".join(sorted(parts))


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


def _notification_delivered(result: dict[str, Any]) -> bool:
    return _safe_bool(dict(result or {}).get("delivered"))


def main() -> int:
    args = parse_args()
    payload = build_payload()
    if not args.no_write_report:
        generated = parse_report_generated_at(payload.get("generated_at"))
        report_dir = ROOT_DIR / args.report_dir
        report_path = report_dir / f"micro_live_ops_heartbeat_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
        payload["report_path"] = _display_path(report_path)
        payload["latest_report_path"] = _display_path(report_dir / "latest.md")
        payload["latest_json_path"] = _display_path(report_dir / "latest.json")
        _write_report(report_path, payload, atomic=True)
        payload.update(_write_latest_aliases(report_dir=report_dir, payload=payload))
    if bool(args.notify) and payload["overall_status"] != "PASS":
        state_file = _resolve_root_path(str(args.state_file))
        dedupe_key = _issue_dedupe_key(payload)
        now = datetime.now(UTC)
        if _cooldown_allows(
            state_file=state_file,
            dedupe_key=dedupe_key,
            cooldown_minutes=max(1, int(args.cooldown_minutes)),
            now=now,
            force=bool(args.force_notify),
        ):
            delivery = NotificationDispatcher(get_settings()).dispatch(
                channel=str(args.channel),
                alert_type="micro_live_ops_heartbeat",
                symbol="MICRO_LIVE",
                payload={
                    "status": "WARN",
                    "force_send": True,
                    "message": _message(payload),
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
            payload["notification"] = {"skipped": True, "reason": "cooldown_active", "dedupe_key": dedupe_key}
    if not bool(args.quiet):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 1 if payload["overall_status"] == "FAIL" and not bool(args.no_fail_exit) else 0


if __name__ == "__main__":
    raise SystemExit(main())
