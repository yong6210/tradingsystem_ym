#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.core import operator_surface_contracts as osc
from app.services.micro_main_universe_policy import build_micro_main_universe_policy_snapshot
from scripts.operation_report_io import atomic_write_text

_REQUEST_RETRY_ATTEMPTS = 3
_REQUEST_RETRY_BASE_DELAY_SECONDS = 0.5
_REQUEST_TIMEOUT_SECONDS = 20.0
_RECENT_SURFACE_TIMINGS: list[dict[str, Any]] = []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MICRO_LIVE preflight checks against the local API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--candidate-limit", type=int, default=10)
    parser.add_argument("--report-dir", default="reports/operations/micro_live_preflight")
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=_REQUEST_TIMEOUT_SECONDS,
        help="Per-request timeout in seconds for each local API surface.",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress per-surface progress messages on stderr.")
    parser.add_argument(
        "--check-binance-rules",
        action="store_true",
        help="Fetch Binance exchangeInfo for current MICRO_LIVE symbols and verify quantity/tick rules.",
    )
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def _now() -> datetime:
    return datetime.now(UTC)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _ensure_http_url(url: str) -> None:
    scheme = urlparse(url).scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError(f"unsupported request URL scheme: {scheme or 'missing'}")


def _request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any] | list[Any]:
    url = f"{base_url.rstrip('/')}{path}"
    if query:
        url += f"?{urlencode(query, doseq=True)}"
    _ensure_http_url(url)
    data: bytes | None = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url=url, data=data, headers=headers, method=method.upper())  # noqa: S310
    last_error: RuntimeError | None = None
    retry_with_refresh = (
        path == "/validation/report"
        and str((query or {}).get("refresh", "")).lower() in {"false", "0"}
    )
    for attempt in range(1, _REQUEST_RETRY_ATTEMPTS + 1):
        try:
            with urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            if retry_with_refresh and exc.code == 404 and "cached validation payload is not available yet" in payload.lower():
                refreshed_query = dict(query or {})
                refreshed_query["refresh"] = "true"
                return _request_json(base_url, method, path, query=refreshed_query, body=body)
            retryable = exc.code >= 500 or "database is locked" in payload.lower()
            last_error = RuntimeError(f"{method.upper()} {path} failed with HTTP {exc.code}: {payload}")
            if retryable and attempt < _REQUEST_RETRY_ATTEMPTS:
                time.sleep(_REQUEST_RETRY_BASE_DELAY_SECONDS * attempt)
                continue
            raise last_error from exc
        except URLError as exc:
            last_error = RuntimeError(f"{method.upper()} {path} failed: {exc.reason}")
            if attempt < _REQUEST_RETRY_ATTEMPTS:
                time.sleep(_REQUEST_RETRY_BASE_DELAY_SECONDS * attempt)
                continue
            raise last_error from exc
        except TimeoutError as exc:
            last_error = RuntimeError(f"{method.upper()} {path} timed out after {_REQUEST_TIMEOUT_SECONDS:g}s")
            if attempt < _REQUEST_RETRY_ATTEMPTS:
                time.sleep(_REQUEST_RETRY_BASE_DELAY_SECONDS * attempt)
                continue
            raise last_error from exc
    raise last_error or RuntimeError(f"{method.upper()} {path} failed without an exception payload")


def _request_surface(
    *,
    args: argparse.Namespace,
    label: str,
    method: str,
    path: str,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any] | list[Any]:
    if not bool(getattr(args, "quiet", False)):
        print(f"[preflight] fetching {label}: {method.upper()} {path}", file=sys.stderr, flush=True)
    started = time.monotonic()
    try:
        payload = _request_json(args.base_url, method, path, query=query, body=body)
    except Exception as exc:
        elapsed = time.monotonic() - started
        _record_surface_timing(args, label=label, method=method, path=path, elapsed=elapsed, status="REQUEST_ERROR", error=exc)
        if not bool(getattr(args, "quiet", False)):
            print(f"[preflight] failed {label} after {elapsed:.1f}s: {exc}", file=sys.stderr, flush=True)
        raise
    elapsed = time.monotonic() - started
    _record_surface_timing(args, label=label, method=method, path=path, elapsed=elapsed, status="PASS")
    if not bool(getattr(args, "quiet", False)):
        print(f"[preflight] fetched {label} in {elapsed:.1f}s", file=sys.stderr, flush=True)
    return payload


def _record_surface_timing(
    args: argparse.Namespace,
    *,
    label: str,
    method: str,
    path: str,
    elapsed: float,
    status: str,
    error: Exception | None = None,
) -> None:
    row: dict[str, Any] = {
        "label": label,
        "method": method.upper(),
        "path": path,
        "status": status,
        "elapsed_ms": round(max(0.0, float(elapsed)) * 1000.0, 1),
    }
    if error is not None:
        row["error"] = str(error)
    timings = getattr(args, "surface_timings", None)
    if isinstance(timings, list):
        timings.append(row)
    else:
        _RECENT_SURFACE_TIMINGS.append(row)


def _truthy_ready(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status", "")).lower()
    checks = payload.get("checks") or {}
    return status == "ready" and all(bool(value) for value in checks.values())


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
        return False
    return True if value else False


def _surface_strip_summary(payload: dict[str, Any] | None, *, surface_type: str = "generic") -> dict[str, str]:
    surface = dict(payload or {})
    if surface_type == "validation":
        summary = dict((surface.get("validation_report") or {}).get("approval_strip_summary") or {})
    else:
        summary = dict(surface.get("approval_strip_summary") or {})
    if summary:
        return {
            "approve_value": str(summary.get("approve_value") or "n/a"),
            "approve_reason": str(summary.get("approve_reason") or ""),
            "align_value": str(summary.get("align_value") or "n/a"),
            "align_reason": str(summary.get("align_reason") or ""),
            "act_value": str(summary.get("act_value") or "continue_runtime_monitoring"),
            "act_reason": str(summary.get("act_reason") or ""),
            "act_priority_level": str(summary.get("act_priority_level") or "monitor"),
            "primary_reason": str(summary.get("primary_reason") or ""),
        }

    deployment_summary = dict(surface.get("deployment_approval_summary") or {})
    return {
        "approve_value": str(
            surface.get("deployment_go_no_go")
            or deployment_summary.get("deployment_go_no_go")
            or surface.get("approval_topline_status")
            or "n/a"
        ),
        "approve_reason": str(
            surface.get("deployment_message")
            or deployment_summary.get("deployment_message")
            or surface.get("approval_topline_summary_line")
            or ""
        ),
        "align_value": str(
            surface.get("playbook_go_no_go")
            or deployment_summary.get("playbook_go_no_go")
            or surface.get("approval_topline_status")
            or "n/a"
        ),
        "align_reason": str(
            surface.get("playbook_message")
            or deployment_summary.get("playbook_message")
            or surface.get("approval_topline_summary_line")
            or ""
        ),
        "act_value": str(
            surface.get("playbook_action")
            or deployment_summary.get("playbook_action")
            or "continue_runtime_monitoring"
        ),
        "act_reason": str(
            surface.get("playbook_message")
            or deployment_summary.get("playbook_message")
            or surface.get("deployment_message")
            or deployment_summary.get("deployment_message")
            or ""
        ),
        "act_priority_level": "monitor",
        "primary_reason": str(
            surface.get("deployment_message")
            or deployment_summary.get("deployment_message")
            or surface.get("playbook_message")
            or deployment_summary.get("playbook_message")
            or ""
        ),
    }


def _surface_summary_line(label: str, summary: dict[str, str]) -> str:
    return (
        f"- {label}: approve={summary.get('approve_value', 'n/a')} | "
        f"align={summary.get('align_value', 'n/a')} | "
        f"act={summary.get('act_value', 'continue_runtime_monitoring')} | "
        f"priority={summary.get('act_priority_level', 'monitor')}"
    )


def _surface_allows_preflight(summary: dict[str, str]) -> bool:
    approve_value = str(summary.get("approve_value") or "").strip().lower()
    return approve_value in {"approval usable", "approved", "go"}


def _checklist_allows_preflight(summary: dict[str, str]) -> bool:
    if _surface_allows_preflight(summary):
        return True
    approve_value = str(summary.get("approve_value") or "").strip().lower()
    act_value = str(summary.get("act_value") or "").strip().lower()
    approve_reason = str(summary.get("approve_reason") or "").strip().lower()
    align_reason = str(summary.get("align_reason") or "").strip().lower()
    if approve_value != "manual review first":
        return False
    if not approve_reason.startswith("go:"):
        return False
    if act_value not in {"proceed_with_configured_rollout", "continue_candidate_review_under_portfolio_caps"}:
        return False
    return "blocking_failures=0" in align_reason and "manual_actions=0" in align_reason


def _root_cause_token(value: str) -> str:
    chars: list[str] = []
    previous_sep = False
    for char in str(value or "").strip().lower():
        if char.isalnum():
            chars.append(char)
            previous_sep = False
        elif not previous_sep:
            chars.append("_")
            previous_sep = True
    return "".join(chars).strip("_")


def _preflight_root_cause(item: dict[str, str]) -> str:
    name = str(item.get("name") or "")
    message = str(item.get("message") or "").lower()
    if name in {"validation_language", "checklist_language"}:
        approve_value = _message_part(message, "approve")
        if approve_value == "manual review first":
            return "validation_manual_review"
        if "refresh_validation_report" in message or approve_value == "validation unavailable":
            return "validation_cache_refresh"
        if approve_value:
            return f"validation_approval_surface_{_root_cause_token(approve_value)}"
    return name or "unknown"


def _message_part(message: str, key: str) -> str:
    prefix = f"{key}="
    for part in str(message or "").split("|"):
        normalized = part.strip()
        if normalized.startswith(prefix):
            return normalized[len(prefix) :].strip()
    return ""


def _failed_root_cause_details(failed: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in failed:
        root_cause = _preflight_root_cause(item)
        row = grouped.setdefault(
            root_cause,
            {
                "root_cause": root_cause,
                "check_names": [],
                "messages": [],
                "primary_message": "",
                "approve_value": "",
                "act_value": "",
                "reason": "",
            },
        )
        name = str(item.get("name") or "")
        message = str(item.get("message") or "")
        if name:
            row["check_names"].append(name)
        if message:
            row["messages"].append(message)
            row["primary_message"] = row["primary_message"] or message
            row["approve_value"] = row["approve_value"] or _message_part(message, "approve")
            row["act_value"] = row["act_value"] or _message_part(message, "act")
            row["reason"] = row["reason"] or _message_part(message, "reason")
    details = [grouped[key] for key in sorted(grouped)]
    for row in details:
        row["check_names"] = _dedupe_text(row["check_names"])
        row["messages"] = _dedupe_text(row["messages"])
    return details


def _dedupe_text(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


_EXECUTION_MODE_RANK = {
    "SHADOW": 0,
    "PAPER": 1,
    "MICRO_LIVE": 2,
    "LIVE": 3,
}


def _csv_set(value: Any, *, lower: bool = False) -> set[str]:
    items = {str(item or "").strip() for item in str(value or "").split(",") if str(item or "").strip()}
    return {item.lower() for item in items} if lower else {item.upper() for item in items}


def _csv_list(value: Any, *, lower: bool = False) -> list[str]:
    items = [str(item or "").strip() for item in str(value or "").split(",") if str(item or "").strip()]
    normalized = [item.lower() for item in items] if lower else [item.upper() for item in items]
    return list(dict.fromkeys(normalized))


def _sir_live_rollout_window_check(
    *,
    live_symbols: set[str],
    core_live_slots: int,
    secondary_live_enabled: bool,
) -> dict[str, Any]:
    policy = build_micro_main_universe_policy_snapshot()
    entries = {
        str(item.get("symbol") or "").upper(): dict(item)
        for item in list(policy.get("entries") or [])
        if str(item.get("symbol") or "").strip()
    }
    core_rank = {
        str(item.get("symbol") or "").upper(): index + 1
        for index, item in enumerate(
            sorted(
                [
                    dict(item)
                    for item in list(policy.get("entries") or [])
                    if str(dict(item).get("tier") or "").strip().lower() == "core"
                ],
                key=lambda row: _int(row.get("rollout_priority"), default=0),
            )
        )
    }
    missing_universe = sorted(symbol for symbol in live_symbols if symbol not in entries)
    outside_core_window: list[str] = []
    secondary_disabled: list[str] = []
    for symbol in sorted(live_symbols):
        entry = entries.get(symbol)
        if not entry:
            continue
        tier = str(entry.get("tier") or "").strip().lower()
        priority = _int(entry.get("rollout_priority"), default=0)
        symbol_core_rank = _int(core_rank.get(symbol), default=0)
        if tier == "core" and core_live_slots > 0 and symbol_core_rank > core_live_slots:
            outside_core_window.append(f"{symbol}:core{symbol_core_rank}/p{priority}")
        if tier == "secondary" and not secondary_live_enabled:
            secondary_disabled.append(f"{symbol}:p{priority}")

    return {
        "name": "session_impulse_retest_live_rollout_window",
        "status": _status(not missing_universe and not outside_core_window and not secondary_disabled),
        "severity": "warning",
        "message": (
            f"core_live_slots={core_live_slots}; secondary_live_enabled={secondary_live_enabled}; "
            f"outside_core_window={','.join(outside_core_window) if outside_core_window else 'none'}; "
            f"secondary_disabled={','.join(secondary_disabled) if secondary_disabled else 'none'}; "
            f"missing_universe={','.join(missing_universe) if missing_universe else 'none'}"
        ),
    }


def _parse_direction_contract(value: Any) -> dict[str, set[str]]:
    contract: dict[str, set[str]] = {}
    for raw_item in str(value or "").split(","):
        item = raw_item.strip()
        if not item or ":" not in item:
            continue
        symbol, directions = item.split(":", 1)
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            continue
        allowed = {
            direction.strip().upper()
            for direction in directions.replace("/", "|").split("|")
            if direction.strip()
        }
        if allowed:
            contract[normalized_symbol] = allowed
    return contract


def _proxy_symbol_to_live_symbol(symbol: Any) -> str:
    text = str(symbol or "").strip().upper()
    if text.endswith("USDT"):
        return f"{text[:-4]}USDC"
    return text


def _backtest_contract_symbols(payload: dict[str, Any]) -> set[str]:
    raw_symbols = payload.get("proxy_symbols")
    if not isinstance(raw_symbols, list) or not raw_symbols:
        results = payload.get("results") if isinstance(payload.get("results"), dict) else {}
        raw_symbols = list(results.keys()) if isinstance(results, dict) else []
    return {_proxy_symbol_to_live_symbol(symbol) for symbol in raw_symbols if str(symbol or "").strip()}


def _latest_micro_main_backtest_report(settings: Any, *, live_symbols: set[str] | None = None) -> Path | None:
    raw_dir = str(
        getattr(
            settings,
            "auto_trading_replay_validation_bridge_backtest_dir",
            "reports/validation/micro_main_usdt_proxy_backtests",
        )
        or "reports/validation/micro_main_usdt_proxy_backtests"
    ).strip()
    report_dir = _resolve_root_path(raw_dir)
    try:
        candidates = sorted(
            path
            for path in report_dir.glob("micro_main_usdt_proxy_backtest_*.json")
            if "unseen" not in path.name and "top" not in path.name
        )
    except OSError:
        return None
    if not candidates:
        return None
    expected_symbols = {str(symbol or "").strip().upper() for symbol in set(live_symbols or set()) if str(symbol or "").strip()}
    if expected_symbols:
        for path in reversed(candidates):
            payload = _read_json_file(path)
            if _backtest_contract_symbols(payload) == expected_symbols:
                return path
    return candidates[-1]


def _micro_live_backtest_contract_alignment_check(
    *,
    settings: Any,
    live_symbols: set[str],
    live_families: set[str],
    live_entry_models: set[str],
    live_sessions: set[str],
    direction_contract: dict[str, set[str]],
) -> dict[str, Any]:
    report_path = _latest_micro_main_backtest_report(settings, live_symbols=live_symbols)
    if report_path is None:
        return {
            "name": "micro_live_backtest_contract_alignment",
            "status": "FAIL",
            "severity": "blocking",
            "message": "no micro_main_usdt_proxy_backtest report found for current MICRO_LIVE contract alignment",
        }
    payload = _read_json_file(report_path)
    expected_symbols = _backtest_contract_symbols(payload)
    expected_families = {"session_impulse_retest"}
    expected_entry_models = {"CONFIRM"}
    expected_sessions = {"dead_session", "london", "new_york"}

    missing_symbols = sorted(expected_symbols - live_symbols)
    unexpected_symbols = sorted(live_symbols - expected_symbols)
    missing_families = sorted(expected_families - live_families)
    unexpected_families = sorted(live_families - expected_families)
    missing_entry_models = sorted(expected_entry_models - live_entry_models)
    unexpected_entry_models = sorted(live_entry_models - expected_entry_models)
    missing_sessions = sorted(expected_sessions - live_sessions)
    unexpected_sessions = sorted(live_sessions - expected_sessions)
    missing_direction_symbols = sorted(
        symbol
        for symbol in expected_symbols
        if not {"LONG", "SHORT"}.issubset(direction_contract.get(symbol, set()))
    )

    aligned = not any(
        [
            missing_symbols,
            unexpected_symbols,
            missing_families,
            unexpected_families,
            missing_entry_models,
            unexpected_entry_models,
            missing_sessions,
            unexpected_sessions,
            missing_direction_symbols,
        ]
    )
    return {
        "name": "micro_live_backtest_contract_alignment",
        "status": _status(aligned),
        "severity": "blocking",
        "message": (
            f"source={_display_path(report_path)}; expected_symbols={len(expected_symbols)}; "
            f"missing_symbols={','.join(missing_symbols) if missing_symbols else 'none'}; "
            f"unexpected_symbols={','.join(unexpected_symbols) if unexpected_symbols else 'none'}; "
            f"missing_families={','.join(missing_families) if missing_families else 'none'}; "
            f"unexpected_families={','.join(unexpected_families) if unexpected_families else 'none'}; "
            f"missing_entry_models={','.join(missing_entry_models) if missing_entry_models else 'none'}; "
            f"unexpected_entry_models={','.join(unexpected_entry_models) if unexpected_entry_models else 'none'}; "
            f"missing_sessions={','.join(missing_sessions) if missing_sessions else 'none'}; "
            f"unexpected_sessions={','.join(unexpected_sessions) if unexpected_sessions else 'none'}; "
            f"missing_long_short_direction={','.join(missing_direction_symbols) if missing_direction_symbols else 'none'}"
        ),
    }


def _resolve_root_path(raw_path: Any) -> Path:
    path = Path(str(raw_path or "")).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


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


def _ws_heartbeat_symbols(settings: Any) -> list[str]:
    heartbeat_path = Path(str(getattr(settings, "runtime_worker_heartbeat_dir", "") or "")) / "ws.json"
    payload = _read_json_file(heartbeat_path)
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    symbols = details.get("symbols") if isinstance(details, dict) else []
    return _csv_list(",".join(str(item) for item in symbols)) if isinstance(symbols, list) else []


def _contract_file_check(*, name: str, raw_path: Any, required: bool) -> dict[str, Any]:
    path_text = str(raw_path or "").strip()
    if not path_text:
        return {
            "name": name,
            "status": "FAIL" if required else "PASS",
            "severity": "blocking" if required else "warning",
            "message": "contract path is not configured" if required else "contract path is optional and not configured",
        }
    path = _resolve_root_path(path_text)
    if not path.exists():
        return {
            "name": name,
            "status": "FAIL",
            "severity": "blocking",
            "message": f"contract path does not exist: {_display_path(path)}",
        }
    payload = _read_json_file(path)
    if not payload:
        return {
            "name": name,
            "status": "FAIL",
            "severity": "blocking",
            "message": f"contract file is missing or invalid JSON: {_display_path(path)}",
        }
    return {
        "name": name,
        "status": "PASS",
        "severity": "blocking",
        "message": f"contract file loaded: {_display_path(path)}",
    }


def _event_blackout_coverage_check(*, raw_path: Any, live_symbols: set[str]) -> dict[str, Any]:
    path_text = str(raw_path or "").strip()
    if not path_text:
        return {
            "name": "macro_blackout_live_coverage",
            "status": "PASS",
            "severity": "warning",
            "message": "macro blackout contract is not configured; event-time entry risk remains operator-managed",
        }
    path = _resolve_root_path(path_text)
    payload = _read_json_file(path)
    windows = payload.get("windows") if isinstance(payload, dict) else []
    if not isinstance(windows, list) or not windows:
        return {
            "name": "macro_blackout_live_coverage",
            "status": "FAIL",
            "severity": "blocking",
            "message": "macro blackout contract has no windows",
        }
    explicitly_covered: set[str] = set()
    has_global_window = False
    for row in windows:
        if not isinstance(row, dict):
            continue
        raw_symbols = row.get("symbols") or []
        if isinstance(raw_symbols, str):
            symbols = _csv_set(raw_symbols)
        else:
            symbols = _csv_set(",".join(str(item) for item in list(raw_symbols)))
        if not symbols:
            has_global_window = True
            continue
        explicitly_covered.update(symbols)
    if has_global_window or not live_symbols:
        return {
            "name": "macro_blackout_live_coverage",
            "status": "PASS",
            "severity": "blocking",
            "message": "macro blackout has at least one global window",
        }
    missing = sorted(live_symbols - explicitly_covered)
    if missing:
        return {
            "name": "macro_blackout_live_coverage",
            "status": "FAIL",
            "severity": "blocking",
            "message": f"blackout windows do not explicitly cover all live symbols; missing={','.join(missing[:12])}",
        }
    return {
        "name": "macro_blackout_live_coverage",
        "status": "PASS",
        "severity": "blocking",
        "message": "macro blackout explicitly covers all current live symbols",
    }


def _event_blackout_freshness_check(*, raw_path: Any, now: datetime, min_horizon_days: int) -> dict[str, Any]:
    path_text = str(raw_path or "").strip()
    if not path_text:
        return {
            "name": "macro_blackout_horizon",
            "status": "PASS",
            "severity": "warning",
            "message": "macro blackout contract is not configured; horizon cannot be monitored",
        }
    payload = _read_json_file(_resolve_root_path(path_text))
    windows = payload.get("windows") if isinstance(payload, dict) else []
    if not isinstance(windows, list) or not windows:
        return {
            "name": "macro_blackout_horizon",
            "status": "FAIL",
            "severity": "blocking",
            "message": "macro blackout contract has no dated windows to monitor",
        }

    normalized_now = now.astimezone(UTC) if now.tzinfo is not None else now.replace(tzinfo=UTC)
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
            "name": "macro_blackout_horizon",
            "status": "FAIL",
            "severity": "blocking",
            "message": f"macro blackout contract has no valid windows; invalid_windows={invalid_count}",
        }

    future_windows = sorted((row for row in dated_windows if row[1] > normalized_now), key=lambda row: row[0])
    if not future_windows:
        last_end = max(row[1] for row in dated_windows)
        return {
            "name": "macro_blackout_horizon",
            "status": "FAIL",
            "severity": "blocking",
            "message": f"macro blackout contract is expired; last_end={last_end.isoformat().replace('+00:00', 'Z')}",
        }

    max_end = max(row[1] for row in future_windows)
    horizon_days = max((max_end - normalized_now).total_seconds(), 0.0) / 86400.0
    next_start, next_end, next_label = future_windows[0]
    threshold = max(1, int(min_horizon_days))
    status = _status(horizon_days >= threshold)
    return {
        "name": "macro_blackout_horizon",
        "status": status,
        "severity": "blocking",
        "message": (
            f"horizon_days={horizon_days:.1f}; min_required={threshold}; upcoming_windows={len(future_windows)}; "
            f"next={next_label} {next_start.isoformat().replace('+00:00', 'Z')}->{next_end.isoformat().replace('+00:00', 'Z')}; "
            f"invalid_windows={invalid_count}"
        ),
    }


def _binance_rule_checks(symbols: set[str]) -> list[dict[str, Any]]:
    if not symbols:
        return []
    try:
        from app.integrations.binance_futures import BinanceFuturesClient
    except Exception as exc:
        return [
            {
                "name": "binance_symbol_trading_rules",
                "status": "FAIL",
                "severity": "blocking",
                "message": f"failed to import Binance client: {exc}",
            }
        ]
    client = BinanceFuturesClient()
    failures: list[str] = []
    checked: list[str] = []
    for symbol in sorted(symbols):
        try:
            rules = client.fetch_symbol_trading_rules(symbol)
        except Exception as exc:
            failures.append(f"{symbol}:{exc}")
            continue
        checked.append(symbol)
        if float(rules.quantity_step or 0.0) <= 0.0 or float(rules.min_quantity or 0.0) <= 0.0:
            failures.append(f"{symbol}:invalid_qty_rules")
        if rules.tick_size is not None and float(rules.tick_size or 0.0) <= 0.0:
            failures.append(f"{symbol}:invalid_tick_size")
    return [
        {
            "name": "binance_symbol_trading_rules",
            "status": "FAIL" if failures else "PASS",
            "severity": "blocking",
            "message": (
                f"failures={';'.join(failures[:8])}; checked={','.join(checked[:12])}"
                if failures
                else f"exchangeInfo trading rules loaded for {len(checked)} live symbol(s)"
            ),
        }
    ]


def _micro_live_config_drift_checks(*, check_binance_rules: bool = False) -> list[dict[str, Any]]:
    settings = get_settings()
    mode = str(getattr(settings, "auto_trading_execution_mode", "") or "").strip().upper()
    live_mode = mode in {"MICRO_LIVE", "LIVE"}
    global_symbols = _csv_set(getattr(settings, "auto_trading_allowed_symbols", ""))
    global_families = _csv_set(getattr(settings, "auto_trading_allowed_families", ""), lower=True)
    live_symbols = _csv_set(getattr(settings, "auto_trading_micro_live_allowed_symbols", ""))
    live_families = _csv_set(getattr(settings, "auto_trading_micro_live_allowed_families", ""), lower=True)
    live_entry_models = _csv_set(getattr(settings, "auto_trading_micro_live_allowed_entry_models", ""))
    direction_contract = _parse_direction_contract(getattr(settings, "auto_trading_micro_live_direction_contract", ""))
    ws_symbols = set(_ws_heartbeat_symbols(settings))
    checks: list[dict[str, Any]] = []

    checks.append(
        {
            "name": "config_execution_mode",
            "status": _status(live_mode),
            "severity": "blocking",
            "message": f"auto_trading_execution_mode={mode or 'unset'}",
        }
    )
    checks.append(
        {
            "name": "binance_live_order_switch",
            "status": _status((not live_mode) or _bool(getattr(settings, "binance_trade_live_enabled", False))),
            "severity": "blocking",
            "message": f"binance_trade_live_enabled={_bool(getattr(settings, 'binance_trade_live_enabled', False))}",
        }
    )
    missing_global = sorted(live_symbols - global_symbols) if global_symbols else []
    checks.append(
        {
            "name": "live_symbol_allowlist_alignment",
            "status": _status(bool(live_symbols) and not missing_global),
            "severity": "blocking",
            "message": (
                f"live_symbols={','.join(sorted(live_symbols))}; "
                f"missing_from_global={','.join(missing_global) if missing_global else 'none'}"
            ),
        }
    )
    missing_families = sorted(live_families - global_families) if global_families else []
    checks.append(
        {
            "name": "live_family_allowlist_alignment",
            "status": _status(bool(live_families) and not missing_families),
            "severity": "blocking",
            "message": (
                f"live_families={','.join(sorted(live_families))}; "
                f"missing_from_global={','.join(missing_families) if missing_families else 'none'}"
            ),
        }
    )
    if direction_contract:
        missing_direction_symbols = sorted(symbol for symbol in live_symbols if symbol not in direction_contract)
        malformed_direction_symbols = sorted(
            symbol for symbol, directions in direction_contract.items() if symbol in live_symbols and not directions.intersection({"LONG", "SHORT"})
        )
    else:
        missing_direction_symbols = []
        malformed_direction_symbols = []
    checks.append(
        {
            "name": "live_direction_contract_coverage",
            "status": _status(not direction_contract or (not missing_direction_symbols and not malformed_direction_symbols)),
            "severity": "blocking",
            "message": (
                f"contract_symbols={len(direction_contract)}; "
                f"missing={','.join(missing_direction_symbols) if missing_direction_symbols else 'none'}; "
                f"malformed={','.join(malformed_direction_symbols) if malformed_direction_symbols else 'none'}"
            ),
        }
    )
    checks.append(
        {
            "name": "live_entry_model_allowlist",
            "status": _status(bool(live_entry_models)),
            "severity": "blocking",
            "message": f"allowed_entry_models={','.join(sorted(live_entry_models)) if live_entry_models else 'none'}",
        }
    )
    live_sessions = _csv_set(getattr(settings, "auto_trading_micro_live_allowed_sessions", ""), lower=True)
    checks.append(
        _micro_live_backtest_contract_alignment_check(
            settings=settings,
            live_symbols=live_symbols,
            live_families=live_families,
            live_entry_models=live_entry_models,
            live_sessions=live_sessions,
            direction_contract=direction_contract,
        )
    )

    if live_mode and ws_symbols:
        missing_ws_symbols = sorted(live_symbols - ws_symbols)
        ws_status = _status(not missing_ws_symbols)
        ws_message = f"ws_symbols={len(ws_symbols)}; missing_live_symbols={','.join(missing_ws_symbols) if missing_ws_symbols else 'none'}"
        ws_severity = "blocking"
    else:
        ws_status = "PASS"
        ws_message = "ws heartbeat symbols unavailable; health_ready remains the primary worker liveness check"
        ws_severity = "warning"
    checks.append(
        {
            "name": "ws_universe_contains_live_symbols",
            "status": ws_status,
            "severity": ws_severity,
            "message": ws_message,
        }
    )

    if "session_impulse_retest" in live_families:
        sir_enabled = _bool(getattr(settings, "session_impulse_retest_enabled", False))
        sir_shadow_only = _bool(getattr(settings, "session_impulse_retest_shadow_only", True), default=True)
        sir_symbols = _csv_set(getattr(settings, "session_impulse_retest_allowed_symbols", ""))
        missing_sir_live_symbols = sorted(live_symbols - sir_symbols) if sir_symbols else []
        tracked_only_symbols = sorted(sir_symbols - live_symbols)
        checks.append(
            {
                "name": "session_impulse_retest_live_alignment",
                "status": _status(sir_enabled and not sir_shadow_only and not missing_sir_live_symbols),
                "severity": "blocking",
                "message": (
                    f"enabled={sir_enabled} shadow_only={sir_shadow_only} "
                    f"missing_live_symbols={','.join(missing_sir_live_symbols) if missing_sir_live_symbols else 'none'} "
                    f"tracked_only={','.join(tracked_only_symbols[:12]) if tracked_only_symbols else 'none'}"
                ),
            }
        )
        checks.append(
            _sir_live_rollout_window_check(
                live_symbols=live_symbols,
                core_live_slots=_int(getattr(settings, "session_impulse_retest_core_live_slots", 0), default=0),
                secondary_live_enabled=_bool(getattr(settings, "session_impulse_retest_secondary_live_enabled", False)),
            )
        )

    checks.append(
        _contract_file_check(
            name="macro_blackout_contract",
            raw_path=getattr(settings, "auto_trading_micro_live_event_blackout_path", ""),
            required=False,
        )
    )
    checks.append(
        _event_blackout_coverage_check(
            raw_path=getattr(settings, "auto_trading_micro_live_event_blackout_path", ""),
            live_symbols=live_symbols,
        )
    )
    checks.append(
        _event_blackout_freshness_check(
            raw_path=getattr(settings, "auto_trading_micro_live_event_blackout_path", ""),
            now=_now(),
            min_horizon_days=_int(getattr(settings, "auto_trading_micro_live_event_blackout_min_horizon_days", 45), default=45),
        )
    )
    checks.append(
        {
            "name": "live_liquidity_gate",
            "status": _status(
                _bool(getattr(settings, "auto_trading_live_liquidity_gate_enabled", False))
                and _bool(getattr(settings, "auto_trading_live_liquidity_gate_fail_closed", True))
            ),
            "severity": "blocking",
            "message": (
                f"enabled={_bool(getattr(settings, 'auto_trading_live_liquidity_gate_enabled', False))} "
                f"fail_closed={_bool(getattr(settings, 'auto_trading_live_liquidity_gate_fail_closed', True))}"
            ),
        }
    )
    if check_binance_rules:
        checks.extend(_binance_rule_checks(live_symbols))
    return checks


def _live_routable_candidate(candidate: dict[str, Any], *, dashboard_payload: dict[str, Any]) -> bool:
    policies = list(dashboard_payload.get("rollout_policies") or [])
    if not policies:
        return True
    family = str(candidate.get("strategy_family") or "").strip().lower()
    symbol = str(candidate.get("symbol") or "").strip().upper()
    if not family:
        return False
    settings = get_settings()
    allowed_symbols = _csv_set(getattr(settings, "auto_trading_allowed_symbols", ""))
    if allowed_symbols and symbol not in allowed_symbols:
        return False
    allowed_families = _csv_set(getattr(settings, "auto_trading_allowed_families", ""), lower=True)
    if allowed_families and family not in allowed_families:
        return False
    policy = next(
        (
            dict(item)
            for item in policies
            if str(item.get("strategy_family") or "").strip().lower() == family
        ),
        None,
    )
    if not policy or not _bool(policy.get("live_enabled")):
        return False
    execution_mode = str(dashboard_payload.get("execution_mode") or "MICRO_LIVE").strip().upper()
    if execution_mode == "MICRO_LIVE":
        micro_live_symbols = _csv_set(getattr(settings, "auto_trading_micro_live_allowed_symbols", ""))
        if micro_live_symbols and symbol not in micro_live_symbols:
            return False
        micro_live_families = _csv_set(
            getattr(settings, "auto_trading_micro_live_allowed_families", ""),
            lower=True,
        )
        if micro_live_families and family not in micro_live_families:
            return False
    max_mode = str(policy.get("max_execution_mode") or "").strip().upper()
    return _EXECUTION_MODE_RANK.get(max_mode, -1) >= _EXECUTION_MODE_RANK.get(execution_mode, 2)


def _select_live_routable_candidate(
    *,
    scanner: list[Any],
    symbol: str,
    dashboard_payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, int]:
    rows = [dict(row) for row in scanner if isinstance(row, dict)]
    routable = [row for row in rows if _live_routable_candidate(row, dashboard_payload=dashboard_payload)]
    ignored_count = max(0, len(rows) - len(routable))
    if not routable:
        return None, ignored_count
    normalized_symbol = str(symbol or "").upper()
    matching = [row for row in routable if str(row.get("symbol", "")).upper() == normalized_symbol]
    return (matching[0] if matching else routable[0]), ignored_count


def _candidate_availability_check(
    *,
    candidate: dict[str, Any] | None,
    dashboard_strip: dict[str, str],
    ignored_non_routable_candidates: int = 0,
) -> dict[str, str]:
    if candidate:
        return {
            "name": "candidate_available",
            "status": "PASS",
            "message": (
                f"{candidate.get('symbol', '')} {candidate.get('strategy_family', '')} "
                f"{candidate.get('deployment_go_no_go', '') or candidate.get('operator_status', '')}"
            ),
        }
    ignored_text = (
        f" ignored_non_routable_candidates={ignored_non_routable_candidates}"
        if ignored_non_routable_candidates
        else ""
    )
    return {
        "name": "candidate_available",
        "status": "PASS",
        "message": (
            "No accepted scanner candidate is live-routable right now; runtime may stay open and wait for the next "
            f"eligible session candidate. act={dashboard_strip.get('act_value', '')}{ignored_text}"
        ),
    }


def _edge_experiment_summary(
    *,
    dashboard_payload: dict[str, Any] | None,
    validation_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    dashboard_source = dict(
        (((dashboard_payload or {}).get("signal_funnel") or {}).get("edge_experiment_review") or {})
    )
    validation_source = dict(
        (((validation_payload or {}).get("validation_report") or validation_payload or {}).get("edge_experiment_review_summary") or {})
    )
    source = dashboard_source or validation_source
    if not source:
        return None

    source_summary = dict(source.get("source_summary") or {})
    edge_proof_posture = dict(source.get("edge_proof_posture") or {})
    daily_edge_kpis = dict(source.get("daily_edge_kpis") or {})
    return {
        "available": _bool(source.get("available", True), default=True),
        "advisory_only": _bool(source.get("advisory_only", True), default=True),
        "edge_state": str(source.get("edge_state") or "insufficient_edge_measurement"),
        "summary": str(source.get("summary") or ""),
        "true_edge_ratio": round(_float(source.get("true_edge_ratio")), 4),
        "edge_decay_rate": round(_float(source.get("edge_decay_rate")), 4),
        "entry_timing_preferred_variant": str(
            source.get("entry_timing_preferred_variant") or source_summary.get("entry_timing_preferred_variant") or "none"
        ),
        "execution_style_preferred_variant": str(
            source.get("execution_style_preferred_variant")
            or source_summary.get("execution_style_preferred_variant")
            or "none"
        ),
        "edge_proof_goal_closed_trades": int(
            source.get("edge_proof_goal_closed_trades") or edge_proof_posture.get("edge_proof_goal_closed_trades") or 0
        ),
        "remaining_closed_trades_to_edge_proof_goal": int(
            source.get("remaining_closed_trades_to_edge_proof_goal")
            or edge_proof_posture.get("remaining_closed_trades_to_edge_proof_goal")
            or 0
        ),
        "edge_proof_posture": {
            "state": str(edge_proof_posture.get("state") or "unknown"),
            "claim_state": str(edge_proof_posture.get("claim_state") or "unknown"),
            "focus": str(edge_proof_posture.get("focus") or ""),
            "summary": str(edge_proof_posture.get("summary") or ""),
        },
        "daily_edge_kpis": {
            "closed_trade_count": int(daily_edge_kpis.get("closed_trade_count", source.get("closed_trade_count", 0)) or 0),
            "sample_maturity_state": str(
                daily_edge_kpis.get("sample_maturity_state") or source.get("sample_maturity_state") or "unknown"
            ),
            "true_edge_ratio": round(_float(daily_edge_kpis.get("true_edge_ratio", source.get("true_edge_ratio"))), 4),
            "edge_decay_rate": round(_float(daily_edge_kpis.get("edge_decay_rate", source.get("edge_decay_rate"))), 4),
            "regime_dependency_state": str(
                daily_edge_kpis.get("regime_dependency_state") or source.get("regime_dependency_state") or "not_available"
            ),
        },
    }


def _edge_experiment_detail_parts(summary: dict[str, Any]) -> dict[str, Any]:
    posture = dict(summary.get("edge_proof_posture") or {})
    kpis = dict(summary.get("daily_edge_kpis") or {})
    return {
        "proof_state": str(posture.get("state") or "unknown"),
        "claim_state": str(posture.get("claim_state") or "unknown"),
        "proof_goal_closed_trades": int(summary.get("edge_proof_goal_closed_trades", 0) or 0),
        "remaining_closed_trades_to_edge_proof_goal": int(
            summary.get("remaining_closed_trades_to_edge_proof_goal", 0) or 0
        ),
        "closed_trade_count": int(kpis.get("closed_trade_count", 0) or 0),
        "true_edge_ratio": round(_float(kpis.get("true_edge_ratio", summary.get("true_edge_ratio"))), 4),
        "edge_decay_rate": round(_float(kpis.get("edge_decay_rate", summary.get("edge_decay_rate"))), 4),
        "regime_dependency_state": str(kpis.get("regime_dependency_state") or "not_available"),
    }


def _edge_experiment_summary_line(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "edge_experiment: unavailable"
    detail = _edge_experiment_detail_parts(summary)
    return (
        f"edge_experiment: state={summary.get('edge_state', 'insufficient_edge_measurement')} | "
        f"entry_timing={summary.get('entry_timing_preferred_variant', 'none')} | "
        f"execution_style={summary.get('execution_style_preferred_variant', 'none')} | "
        f"proof={detail['proof_state']}/{detail['claim_state']} | "
        f"closes={detail['closed_trade_count']}/{detail['proof_goal_closed_trades']} | "
        f"remaining={detail['remaining_closed_trades_to_edge_proof_goal']} | "
        f"regime={detail['regime_dependency_state']} | "
        f"true_edge={detail['true_edge_ratio']:.4f} | "
        f"decay={detail['edge_decay_rate']:.4f}"
    )


def _edge_evolution_summary(
    *,
    dashboard_payload: dict[str, Any] | None,
    validation_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    dashboard_source = dict(((((dashboard_payload or {}).get("signal_funnel") or {}).get("edge_evolution_rule")) or {}))
    validation_source = dict(
        (((validation_payload or {}).get("validation_report") or validation_payload or {}).get("edge_evolution_rule_summary") or {})
    )
    source = dashboard_source or validation_source
    if not source:
        return None
    return {
        "available": _bool(source.get("available", True), default=True),
        "advisory_only": _bool(source.get("advisory_only", True), default=True),
        "evolution_state": str(source.get("evolution_state") or "insufficient_sample"),
        "recommended_action": str(source.get("recommended_action") or "keep_current_baseline"),
        "allocation_bias": str(source.get("allocation_bias") or "hold_current_baseline"),
        "summary": str(source.get("summary") or ""),
        "kill_review_triggered": _bool(source.get("kill_review_triggered", False)),
        "promotion_candidate_axis": str(source.get("promotion_candidate_axis") or "none"),
        "promotion_candidate_variant": str(source.get("promotion_candidate_variant") or "none"),
    }


def _edge_evolution_summary_line(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "edge_evolution: unavailable"
    return (
        f"edge_evolution: state={summary.get('evolution_state', 'insufficient_sample')} | "
        f"action={summary.get('recommended_action', 'keep_current_baseline')} | "
        f"bias={summary.get('allocation_bias', 'hold_current_baseline')} | "
        f"promotion={summary.get('promotion_candidate_axis', 'none')}/{summary.get('promotion_candidate_variant', 'none')}"
    )


def _review_followup_summary(
    *,
    dashboard_payload: dict[str, Any] | None,
    validation_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    dashboard_source = dict(((((dashboard_payload or {}).get("signal_funnel") or {}).get("review_followup_ledger")) or {}))
    validation_source = dict(
        (((validation_payload or {}).get("validation_report") or validation_payload or {}).get("review_followup_ledger_summary") or {})
    )
    source = dashboard_source or validation_source
    if not source:
        return None
    return {
        "available": _bool(source.get("available", False)),
        "last_status": str(source.get("last_status") or "none"),
        "last_generated_status": str(source.get("last_generated_status") or source.get("last_status") or "none"),
        "last_decision_status": str(source.get("last_decision_status") or "none"),
        "last_effective_status": str(source.get("last_effective_status") or source.get("last_status") or "none"),
        "last_action": str(source.get("last_action") or "none"),
        "recent_entry_count": int(source.get("recent_entry_count", 0) or 0),
        "last_followup_command": str(source.get("last_followup_command") or ""),
        "summary": str(source.get("summary") or ""),
    }


def _review_followup_summary_line(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "review_followup_ledger: unavailable"
    return (
        f"review_followup_ledger: generated={summary.get('last_status', 'none')} | "
        f"decision={summary.get('last_decision_status', 'none')} | "
        f"effective={summary.get('last_effective_status', 'none')} | "
        f"action={summary.get('last_action', 'none')} | "
        f"entries={int(summary.get('recent_entry_count', 0) or 0)} | "
        f"cmd={summary.get('last_followup_command', '') or 'none'}"
    )


def _edge_experiment_next_step(summary: dict[str, Any] | None) -> str | None:
    if not summary:
        return None
    detail = _edge_experiment_detail_parts(summary)
    proof_goal = max(int(detail["proof_goal_closed_trades"] or 0), 0)
    remaining = max(int(detail["remaining_closed_trades_to_edge_proof_goal"] or 0), 0)
    if detail["proof_state"] == "sample_building":
        return (
            "Advisory only: edge proof is still sample-building; treat split preferences as directional while "
            f"{remaining} closed trades remain to the {proof_goal}-close proof goal."
        )
    if detail["proof_state"] == "regime_limited":
        return (
            "Advisory only: edge proof goal is met, but regime dependency is still active; do not generalize "
            "promotion until weaker regimes accumulate confirming closes."
        )
    if detail["proof_state"] == "proof_goal_met_but_edge_weak":
        return (
            "Advisory only: the proof goal is met, but current true-edge/decay still looks weak; keep allocation "
            "changes in research mode until metrics stabilize."
        )
    edge_state = str(summary.get("edge_state") or "")
    entry_timing = str(summary.get("entry_timing_preferred_variant") or "none")
    execution_style = str(summary.get("execution_style_preferred_variant") or "none")
    if edge_state == "fragile_edge":
        return (
            "Advisory only: post-cost edge is fragile; run controlled split review "
            f"with entry_timing={entry_timing} and execution_style={execution_style} before widening live scope."
        )
    if edge_state == "watch_edge":
        return (
            "Advisory only: post-cost edge is unstable; prefer controlled split review "
            f"with entry_timing={entry_timing} and execution_style={execution_style} over structural rewrites."
        )
    if edge_state == "insufficient_edge_measurement":
        return "Advisory only: collect more closed post-cost trades before treating edge experiment output as decisive."
    return None


def _edge_evolution_next_step(summary: dict[str, Any] | None) -> str | None:
    if not summary:
        return None
    evolution_state = str(summary.get("evolution_state") or "")
    action = str(summary.get("recommended_action") or "keep_current_baseline")
    axis = str(summary.get("promotion_candidate_axis") or "none")
    variant = str(summary.get("promotion_candidate_variant") or "none")
    if evolution_state == "edge_kill_review":
        return (
            "Advisory only: edge evolution now points to kill review; hold live expansion and run "
            f"{action} before trusting further allocation."
        )
    if evolution_state == "reduce_candidate":
        return (
            "Advisory only: edge evolution points to baseline reduction; keep branch tests active but treat "
            f"{action} as the next allocation review."
        )
    if evolution_state == "promote_candidate":
        return (
            "Advisory only: preferred branch now has promotion-review posture; review "
            f"{axis}={variant} with {action} before broader rollout changes."
        )
    return None


def _review_followup_next_step(summary: dict[str, Any] | None) -> str | None:
    if not summary:
        return None
    generated_status = str(summary.get("last_status") or "none")
    followup_command = str(summary.get("last_followup_command") or "").strip()
    if generated_status in {"NO_TARGET", "NO_REVIEW_ACTION_AVAILABLE"}:
        if followup_command:
            return (
                "Advisory only: the latest review packet stalled during generation at "
                f"`{generated_status}`; fix target contract carryover before rerunning `{followup_command}`."
            )
        return (
            "Advisory only: the latest review packet stalled during generation at "
            f"`{generated_status}`; fix target contract carryover before generating another packet."
        )
    return None


def _operator_action_priority_summary(
    *,
    dashboard_payload: dict[str, Any] | None,
    validation_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    dashboard_source = dict((((dashboard_payload or {}).get("signal_funnel") or {}).get("operator_action_priority") or {}))
    validation_source = dict(
        (((validation_payload or {}).get("validation_report") or validation_payload or {}).get("operator_action_priority_summary") or {})
    )
    return dashboard_source or validation_source


def _experiment_review_target(
    operator_action_priority: dict[str, Any] | None,
    *,
    target_key: str,
    preferred_key: str,
    action: str,
) -> dict[str, Any] | None:
    priority = dict(operator_action_priority or {})
    context = dict(priority.get("experiment_context") or {})
    target = dict(context.get(target_key) or {})
    if not target:
        return None
    return {
        "action": action,
        "preferred_variant": str(context.get(preferred_key) or "none"),
        "symbol": str(target.get("symbol") or ""),
        "status": str(target.get("status") or ""),
        "strategy_family": str(target.get("strategy_family") or ""),
        "block_reason": str(target.get("block_reason") or ""),
        "focus_source": str(target.get("focus_source") or ""),
    }


def _experiment_review_target_line(label: str, target: dict[str, Any] | None) -> str:
    item = dict(target or {})
    if not item:
        return f"{label}: none"
    line = (
        f"{label}: action={item.get('action') or 'unknown'} | "
        f"target={item.get('symbol') or 'unknown'} | "
        f"variant={item.get('preferred_variant') or 'none'} | "
        f"status={item.get('status') or 'unknown'} | "
        f"family={item.get('strategy_family') or 'unknown'}"
    )
    if item.get("block_reason"):
        line = f"{line} | reason={item.get('block_reason')}"
    if item.get("focus_source"):
        line = f"{line} | focus={item.get('focus_source')}"
    return line


def _split_review_followup_command(*, symbol: str, universe: str, days: int, action: str) -> str:
    return (
        f"./.venv/bin/python scripts/run_split_review_followup.py "
        f"--symbol {symbol.upper()} --universe {universe} --days {days} --action {action}"
    )


def _representative_candidates(dashboard_payload: dict[str, Any] | None) -> dict[str, Any]:
    portfolio = dict((dashboard_payload or {}).get("portfolio_summary") or {})

    def _candidate(row: dict[str, Any] | None, *, status: str) -> dict[str, Any] | None:
        item = dict(row or {})
        if not item:
            return None
        focus = dict(item.get("edge_experiment_focus") or {})
        return {
            "symbol": str(item.get("symbol") or ""),
            "status": status,
            "strategy_family": str(item.get("strategy_family") or ""),
            "block_reason": str(item.get("block_reason") or ""),
            "edge_state": str(focus.get("edge_state") or "insufficient_edge_measurement"),
            "entry_timing_preferred_variant": str(focus.get("entry_timing_preferred_variant") or "none"),
            "execution_style_preferred_variant": str(focus.get("execution_style_preferred_variant") or "none"),
        }

    accepted_rows = list(portfolio.get("accepted_candidates") or [])
    blocked_rows = list(portfolio.get("blocked_candidates") or [])
    return {
        "accepted": _candidate(accepted_rows[0] if accepted_rows else None, status="ACTIONABLE_ENTRY"),
        "blocked": _candidate(blocked_rows[0] if blocked_rows else None, status="BLOCKED_SETUP"),
    }


def _representative_candidate_line(label: str, candidate: dict[str, Any] | None) -> str:
    item = dict(candidate or {})
    if not item:
        return f"{label}: none"
    line = (
        f"{label}: {item.get('symbol') or 'unknown'} | "
        f"family={item.get('strategy_family') or 'unknown'} | "
        f"edge={item.get('edge_state') or 'insufficient_edge_measurement'} | "
        f"split={(item.get('entry_timing_preferred_variant') or 'none')}/{(item.get('execution_style_preferred_variant') or 'none')}"
    )
    if item.get("status"):
        line = f"{line} | status={item.get('status')}"
    if item.get("block_reason"):
        line = f"{line} | reason={item.get('block_reason')}"
    return line


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# MICRO_LIVE Preflight")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- symbol: {payload['symbol']}")
    lines.append(f"- universe: {payload['universe']}")
    lines.append(f"- overall_status: {payload['overall_status']}")
    lines.append("")
    lines.append("## Key Decision")
    lines.append("")
    lines.append(f"- result: {payload['overall_status']}")
    lines.append(f"- summary: {payload['summary_line']}")
    if payload.get("failed_root_cause_details"):
        lines.append(f"- failed_root_cause_count: {payload.get('failed_root_cause_count', 0)}")
    lines.append("")
    lines.append("## Failed Root Causes")
    lines.append("")
    root_causes = list(payload.get("failed_root_cause_details") or [])
    if root_causes:
        for item in root_causes:
            checks = ", ".join(str(name) for name in list(item.get("check_names") or []))
            lines.append(
                f"- {item.get('root_cause')}: checks={checks or 'none'} | "
                f"approve={item.get('approve_value') or 'n/a'} | "
                f"act={item.get('act_value') or 'n/a'}"
            )
            if item.get("reason"):
                lines.append(f"  reason={item.get('reason')}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    for item in payload["checks"]:
        lines.append(f"- [{item['status']}] {item['name']}: {item['message']}")
    lines.append("")
    lines.append("## API Surface Timings")
    lines.append("")
    for item in payload.get("surface_timings") or []:
        detail = f"- {item.get('label')}: {item.get('status')} {item.get('elapsed_ms')}ms | {item.get('method')} {item.get('path')}"
        if item.get("error"):
            detail = f"{detail} | error={item.get('error')}"
        lines.append(detail)
    if not payload.get("surface_timings"):
        lines.append("- none")
    lines.append("")
    lines.append("## Approval Surfaces")
    lines.append("")
    for row in payload.get("approval_surfaces") or []:
        lines.append(
            f"- {row['label']}: approve={row['approve_value']} | "
            f"align={row['align_value']} | act={row['act_value']} | "
            f"priority={row['act_priority_level']}"
        )
        lines.append(f"  reason={row['primary_reason'] or row['approve_reason'] or row['act_reason']}")
    lines.append("")
    lines.append("## Edge Experiment")
    lines.append("")
    edge_experiment = payload.get("edge_experiment_review") or {}
    if edge_experiment:
        lines.append(f"- {_edge_experiment_summary_line(edge_experiment)}")
        lines.append(f"- summary: {edge_experiment.get('summary', '')}")
    else:
        lines.append("- edge experiment unavailable")
    edge_evolution = payload.get("edge_evolution_rule") or {}
    if edge_evolution:
        lines.append(f"- {_edge_evolution_summary_line(edge_evolution)}")
        lines.append(f"- summary: {edge_evolution.get('summary', '')}")
    review_followup = payload.get("review_followup_ledger") or {}
    if review_followup:
        lines.append(f"- {_review_followup_summary_line(review_followup)}")
        lines.append(f"- summary: {review_followup.get('summary', '')}")
    experiment_targets = payload.get("experiment_review_targets") or {}
    lines.append(f"- {_experiment_review_target_line('entry_timing_review_target', experiment_targets.get('entry_timing'))}")
    lines.append(f"- {_experiment_review_target_line('execution_style_review_target', experiment_targets.get('execution_style'))}")
    representative_candidates = payload.get("representative_candidates") or {}
    lines.append(f"- {_representative_candidate_line('accepted_candidate_focus', representative_candidates.get('accepted'))}")
    lines.append(f"- {_representative_candidate_line('blocked_candidate_focus', representative_candidates.get('blocked'))}")
    lines.append("")
    lines.append("## Candidate")
    lines.append("")
    candidate = payload.get("candidate") or {}
    if candidate:
        lines.append(f"- plan_id: {candidate.get('plan_id', '')}")
        lines.append(f"- symbol: {candidate.get('symbol', '')}")
        lines.append(f"- family: {candidate.get('strategy_family', '')}")
        lines.append(f"- candidate_surface: {candidate.get('deployment_go_no_go', '') or candidate.get('operator_status', '')}")
        lines.append(f"- expected_summary: {candidate.get('expected_summary', '')}")
    else:
        lines.append("- no candidate selected")
    lines.append("")
    lines.append("## Next Steps")
    lines.append("")
    for step in payload.get("next_steps", []):
        lines.append(f"- {step}")
    lines.append("")
    lines.append("## Raw Payload")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    lines.append("```")
    atomic_write_text(path, "\n".join(lines))


def main() -> int:
    global _REQUEST_TIMEOUT_SECONDS
    args = parse_args()
    _REQUEST_TIMEOUT_SECONDS = max(1.0, float(getattr(args, "request_timeout", _REQUEST_TIMEOUT_SECONDS)))
    _RECENT_SURFACE_TIMINGS.clear()
    args.surface_timings = _RECENT_SURFACE_TIMINGS
    generated_at = _now()
    dashboard_limit = min(max(1, int(args.candidate_limit)), 5)

    ready = _request_surface(
        args=args,
        label="readiness",
        method="GET",
        path="/health/ready",
    )
    dashboard = _request_surface(
        args=args,
        label="operator dashboard",
        method="GET",
        path="/execution/operator-dashboard",
        query={
            "symbol": args.symbol,
            "universe": args.universe,
            "days": args.days,
            "portfolio_limit": dashboard_limit,
            "intent_limit": dashboard_limit,
            "reconcile_limit": dashboard_limit,
            "fast": "true",
        },
    )
    safety = _request_surface(
        args=args,
        label="safety state",
        method="GET",
        path="/execution/safety-state",
        query={"symbol": args.symbol},
    )
    reconcile = _request_surface(
        args=args,
        label="execution reconcile",
        method="POST",
        path="/execution/reconcile",
        query={"apply_lock": "false", "auto_resolve": "false"},
        body={"symbol": args.symbol},
    )
    validation = _request_surface(
        args=args,
        label="validation report",
        method="POST",
        path="/validation/report",
        query={"symbol": args.symbol, "refresh": "false", "cache_fallback": "true"},
    )
    checklist = _request_surface(
        args=args,
        label="operations checklist",
        method="POST",
        path="/operations/checklist",
        query={"symbol": args.symbol, "write_report": "false"},
    )
    alerts = _request_surface(
        args=args,
        label="alert metrics",
        method="GET",
        path="/alerts/metrics",
        query={"days": args.days, "write_report": "false"},
    )
    scanner = _request_surface(
        args=args,
        label="scanner top",
        method="GET",
        path="/scanner/top",
        query={"universe": args.universe, "limit": args.candidate_limit, "fast": "true"},
    )

    candidate: dict[str, Any] | None = None
    ignored_non_routable_candidates = 0
    if isinstance(scanner, list) and scanner:
        candidate, ignored_non_routable_candidates = _select_live_routable_candidate(
            scanner=scanner,
            symbol=args.symbol,
            dashboard_payload=dashboard,
        )
    dashboard_strip = _surface_strip_summary(dashboard, surface_type="dashboard")
    validation_strip = _surface_strip_summary(validation, surface_type="validation")
    checklist_strip = _surface_strip_summary(checklist, surface_type="checklist")
    edge_experiment_review = _edge_experiment_summary(
        dashboard_payload=dashboard,
        validation_payload=validation,
    )
    edge_evolution_rule = _edge_evolution_summary(
        dashboard_payload=dashboard,
        validation_payload=validation,
    )
    review_followup_ledger = _review_followup_summary(
        dashboard_payload=dashboard,
        validation_payload=validation,
    )
    operator_action_priority = _operator_action_priority_summary(
        dashboard_payload=dashboard,
        validation_payload=validation,
    )
    experiment_review_targets = {
        "entry_timing": _experiment_review_target(
            operator_action_priority,
            target_key="entry_timing_target",
            preferred_key="entry_timing_preferred_variant",
            action="run_entry_timing_split_review",
        ),
        "execution_style": _experiment_review_target(
            operator_action_priority,
            target_key="execution_style_target",
            preferred_key="execution_style_preferred_variant",
            action="run_execution_style_split_review",
        ),
    }
    for target in experiment_review_targets.values():
        if target:
            target["followup_command"] = _split_review_followup_command(
                symbol=args.symbol,
                universe=args.universe,
                days=args.days,
                action=str(target.get("action") or ""),
            )
    representative_candidates = _representative_candidates(dashboard)

    checks: list[dict[str, str]] = []
    checks.append(
        {
            "name": "health_ready",
            "status": _status(_truthy_ready(ready)),
            "message": f"health status={ready.get('status', 'unknown')} checks={ready.get('checks', {})}",
        }
    )
    checks.append(
        {
            "name": "auto_trading_enabled",
            "status": _status(_bool(dashboard.get("auto_trading_enabled", False))),
            "message": f"execution_mode={dashboard.get('execution_mode', 'unknown')}",
        }
    )
    checks.append(
        {
            "name": "new_entries_allowed",
            "status": _status(_bool(dashboard.get("new_entries_allowed", False))),
            "message": (
                f"approve={dashboard_strip.get('approve_value', '')} | "
                f"align={dashboard_strip.get('align_value', '')} | "
                f"act={dashboard_strip.get('act_value', '')} | "
                f"reason={dashboard.get('blocking_reason_message') or dashboard_strip.get('approve_reason') or dashboard_strip.get('act_reason') or 'new entries allowed'}"
            ),
        }
    )
    checks.append(
        {
            "name": "validation_language",
            "status": _status(_surface_allows_preflight(validation_strip)),
            "message": (
                f"approve={validation_strip.get('approve_value', '')} | "
                f"align={validation_strip.get('align_value', '')} | "
                f"act={validation_strip.get('act_value', '')} | "
                f"reason={validation_strip.get('approve_reason', '') or validation_strip.get('act_reason', '')}"
            ),
        }
    )
    checklist_allows = _checklist_allows_preflight(checklist_strip)
    checklist_surface_allows = _surface_allows_preflight(checklist_strip)
    if checklist_allows and not checklist_surface_allows:
        checklist_classification = "advisory_only_checklist_warning_not_order_blocking"
    elif checklist_allows:
        checklist_classification = "approval_usable"
    else:
        checklist_classification = "blocking_or_manual_item"
    checks.append(
        {
            "name": "checklist_language",
            "status": _status(checklist_allows),
            "message": (
                f"approve={checklist_strip.get('approve_value', '')} | "
                f"align={checklist_strip.get('align_value', '')} | "
                f"act={checklist_strip.get('act_value', '')} | "
                f"classification={checklist_classification} | "
                f"reason={checklist_strip.get('approve_reason', '') or checklist_strip.get('act_reason', '')}"
            ),
        }
    )
    checks.append(
        {
            "name": "safety_state",
            "status": _status(
                not _bool(safety.get("kill_switch_active", False))
                and not _bool(safety.get("close_only_active", False))
                and not _bool(safety.get("config_close_only_active", False))
            ),
            "message": f"kill={safety.get('kill_switch_active', False)} close_only={safety.get('close_only_active', False)} config_close_only={safety.get('config_close_only_active', False)}",
        }
    )
    reconcile_summary = reconcile if isinstance(reconcile, dict) else {}
    reconcile_healthy = _bool(reconcile_summary.get("healthy", not _bool(reconcile_summary.get("mismatches", []))))
    checks.append(
        {
            "name": "reconciliation",
            "status": _status(reconcile_healthy),
            "message": f"healthy={reconcile_summary.get('healthy', False)} severity={reconcile_summary.get('highest_severity', 'INFO')}",
        }
    )
    latest_validation_alert = (alerts.get("latest_validation_alert") or {}) if isinstance(alerts, dict) else {}
    checks.append(
        {
            "name": "alert_channel",
            "status": _status(_bool(latest_validation_alert) or _bool((alerts.get("overall") or {}).get("total", 0))),
            "message": f"latest_validation_alert={_bool(latest_validation_alert)}",
        }
    )
    config_drift_checks = _micro_live_config_drift_checks(check_binance_rules=bool(getattr(args, "check_binance_rules", False)))
    checks.extend(config_drift_checks)
    checks.append(
        _candidate_availability_check(
            candidate=candidate,
            dashboard_strip=dashboard_strip,
            ignored_non_routable_candidates=ignored_non_routable_candidates,
        )
    )

    failed = [item for item in checks if item["status"] != "PASS"]
    failed_root_cause_details = _failed_root_cause_details(failed)
    failed_root_causes = [str(item.get("root_cause") or "") for item in failed_root_cause_details]
    overall_status = osc.MICRO_LIVE_PREFLIGHT_STATUS_READY if not failed else osc.MICRO_LIVE_PREFLIGHT_STATUS_NOT_READY
    if failed:
        next_steps = [
            str(item.get("primary_message") or "")
            for item in failed_root_cause_details
            if str(item.get("primary_message") or "")
        ]
    elif candidate:
        next_steps = ["Proceed to the live go-live checklist and final operator sign-off."]
    else:
        next_steps = ["Runtime gates are ready; wait for the next live-routable scanner candidate before expecting an order."]
    advisory_next_step = _edge_experiment_next_step(edge_experiment_review)
    if advisory_next_step:
        next_steps.append(advisory_next_step)
    edge_evolution_next_step = _edge_evolution_next_step(edge_evolution_rule)
    if edge_evolution_next_step:
        next_steps.append(edge_evolution_next_step)
    review_followup_next_step = _review_followup_next_step(review_followup_ledger)
    if review_followup_next_step:
        next_steps.append(review_followup_next_step)
    targeted_reviews = [
        str(target.get("followup_command") or "")
        for target in experiment_review_targets.values()
        if target
    ]
    if targeted_reviews:
        next_steps.append("Advisory only: run split review packet(s) with " + "; ".join(targeted_reviews) + ".")
    next_steps = _dedupe_text(next_steps)
    if failed:
        if len(failed_root_causes) < len(failed):
            summary_line = (
                f"{len(failed)} blocking preflight check(s) remain across "
                f"{len(failed_root_causes)} unique root cause(s)."
            )
        else:
            summary_line = f"{len(failed)} blocking preflight check(s) remain."
    elif candidate:
        summary_line = "All preflight checks passed; MICRO_LIVE can proceed to final operator sign-off."
    else:
        summary_line = "Runtime gates are ready; no live-routable scanner candidate is available yet."

    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "symbol": args.symbol.upper(),
        "universe": args.universe,
        "overall_status": overall_status,
        "summary_line": summary_line,
        "failed_root_causes": failed_root_causes,
        "failed_root_cause_count": len(failed_root_causes),
        "failed_root_cause_details": failed_root_cause_details,
        "surface_timings": list(_RECENT_SURFACE_TIMINGS),
        "checks": checks,
        "candidate": candidate or {},
        "ignored_non_routable_candidate_count": ignored_non_routable_candidates,
        "health_ready": ready,
        "operator_dashboard": dashboard,
        "operator_dashboard_summary": {
            "execution_mode": dashboard.get("execution_mode", ""),
            "auto_trading_enabled": dashboard.get("auto_trading_enabled", False),
            "new_entries_allowed": dashboard.get("new_entries_allowed", False),
            "blocking_reason_code": dashboard.get("blocking_reason_code", ""),
            "blocking_reason_message": dashboard.get("blocking_reason_message", ""),
            "approval_strip_summary": dashboard_strip,
        },
        "reconciliation": reconcile,
        "safety_state": safety,
        "validation_report": {
            "deployment_go_no_go": validation.get("deployment_go_no_go", ""),
            "deployment_code": validation.get("deployment_code", ""),
            "deployment_message": validation.get("deployment_message", ""),
            "playbook_go_no_go": validation.get("playbook_go_no_go", ""),
            "playbook_action": validation.get("playbook_action", ""),
            "approval_strip_summary": validation_strip,
        },
        "operations_checklist": {
            "deployment_go_no_go": checklist.get("deployment_go_no_go", ""),
            "deployment_code": checklist.get("deployment_code", ""),
            "deployment_message": checklist.get("deployment_message", ""),
            "playbook_go_no_go": checklist.get("playbook_go_no_go", ""),
            "playbook_action": checklist.get("playbook_action", ""),
            "approval_strip_summary": checklist_strip,
        },
        "approval_surfaces": [
            {"label": "dashboard", **dashboard_strip},
            {"label": "validation", **validation_strip},
            {"label": "checklist", **checklist_strip},
        ],
        "edge_experiment_review": edge_experiment_review,
        "edge_evolution_rule": edge_evolution_rule,
        "review_followup_ledger": review_followup_ledger,
        "experiment_review_targets": experiment_review_targets,
        "representative_candidates": representative_candidates,
        "alert_metrics_summary": {
            "latest_validation_alert": latest_validation_alert,
            "overall": (alerts.get("overall") or {}) if isinstance(alerts, dict) else {},
        },
        "config_drift_checks": config_drift_checks,
        "next_steps": next_steps,
    }

    if not args.no_write_report:
        ts = generated_at.strftime("%Y%m%dT%H%M%SZ")
        report_path = ROOT_DIR / args.report_dir / f"micro_live_preflight_{args.symbol.upper()}_{ts}.md"
        _write_report(report_path, payload)
        payload["report_path"] = _display_path(report_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(
            json.dumps(
                {
                    "overall_status": osc.MICRO_LIVE_PREFLIGHT_STATUS_ERROR,
                    "error": str(exc),
                    "surface_timings": list(_RECENT_SURFACE_TIMINGS),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
