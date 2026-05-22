from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from math import isfinite
from pathlib import Path
from typing import Any


SESSION_IMPULSE_RETEST_FAMILY = "session_impulse_retest"
SESSION_IMPULSE_RETEST_ENTRY_MODEL = "CONFIRM"
USDC_DIRECT_BACKTEST_SOURCE = "micro_main_usdc_backtest"
USDT_DIRECT_BACKTEST_SOURCE = "micro_main_usdt_backtest"
USDT_PROXY_BACKTEST_SOURCE = "micro_main_usdt_proxy_backtest"
PORTFOLIO_MIX_REVIEW_SOURCE = "micro_intrabar_candidate_portfolio_mix_review"
DEFAULT_PORTFOLIO_MIX_REPORT = "reports/operations/micro_intrabar_long_short_portfolio_mix_review_drop_arb/latest.json"


def normalized_string_set(values: list[Any] | tuple[Any, ...] | set[Any] | None, *, case: str) -> set[str]:
    normalized: set[str] = set()
    for raw in values or ():
        value = str(raw or "").strip()
        if not value:
            continue
        if case == "upper":
            normalized.add(value.upper())
        elif case == "lower":
            normalized.add(value.lower())
        else:
            normalized.add(value)
    return normalized


def parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def safe_int(value: Any, default: int = 0) -> int:
    if value in (None, "", "None"):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return int(parsed) if isfinite(parsed) else default


def safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, "", "None"):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return float(parsed) if isfinite(parsed) else default


def session_bucket(settings: Any, ts: datetime | None) -> str:
    if ts is None:
        return "unknown"
    current = ts.astimezone(timezone.utc)
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    london_start = day_start + timedelta(
        hours=safe_int(getattr(settings, "trading_session_london_start_hour_utc", 7), 7)
    )
    london_end = day_start + timedelta(
        hours=safe_int(getattr(settings, "trading_session_london_end_hour_utc", 12), 12)
    )
    if london_start <= current < london_end:
        return "london"
    new_york_start = day_start + timedelta(
        hours=safe_int(getattr(settings, "trading_session_new_york_start_hour_utc", 13), 13)
    )
    new_york_end = day_start + timedelta(
        hours=safe_int(getattr(settings, "trading_session_new_york_end_hour_utc", 18), 18)
    )
    if new_york_start <= current < new_york_end:
        return "new_york"
    return "dead_session"


def resolve_report_dir(settings: Any, raw_path: str, *, default: str) -> Path:
    configured = str(raw_path or default or "").strip()
    path = Path(configured).expanduser()
    if path.is_absolute():
        return path
    validation_dir = Path(str(getattr(settings, "validation_report_dir", "") or "")).expanduser()
    if validation_dir.is_absolute():
        if validation_dir.name == "validation" and validation_dir.parent.name == "reports":
            return validation_dir.parent.parent / path
        return validation_dir.parent / path
    return Path.cwd() / path


def canonical_symbol_from_proxy(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if symbol.endswith("USDT"):
        return f"{symbol[:-4]}USDC"
    return symbol


def contract_symbol_for_source(value: Any, source: str, *, proxy_symbol: bool = False) -> str:
    symbol = str(value or "").strip().upper()
    if source == USDT_PROXY_BACKTEST_SOURCE or proxy_symbol:
        return canonical_symbol_from_proxy(symbol)
    return symbol


def usdt_proxy_contract_symbols(payload: dict[str, Any], *, source_hint: str = "") -> set[str]:
    source = str(payload.get("source") or source_hint or "").strip()
    raw_symbols = payload.get("symbols")
    proxy_symbols = False
    if not isinstance(raw_symbols, list) or not raw_symbols:
        raw_symbols = payload.get("proxy_symbols")
        proxy_symbols = True
    if not isinstance(raw_symbols, list) or not raw_symbols:
        raw_symbols = payload.get("combined_symbols")
        proxy_symbols = False
    if not isinstance(raw_symbols, list) or not raw_symbols:
        results = payload.get("results") if isinstance(payload.get("results"), dict) else {}
        raw_symbols = list(results.keys()) if isinstance(results, dict) else []
    return {
        contract_symbol_for_source(symbol, source, proxy_symbol=proxy_symbols)
        for symbol in raw_symbols
        if str(symbol or "").strip()
    }


def active_micro_live_symbol_contract(settings: Any) -> set[str]:
    mode = str(getattr(settings, "auto_trading_execution_mode", "") or "").strip().upper()
    if mode not in {"MICRO_LIVE", "LIVE"}:
        return set()
    return {
        symbol
        for symbol in normalized_string_set(
            str(getattr(settings, "auto_trading_micro_live_allowed_symbols", "") or "").split(","),
            case="upper",
        )
        if symbol
    }


def _recent_json_files(directory: Path, pattern: str) -> list[Path]:
    if not directory.exists():
        return []
    candidates = [path for path in directory.glob(pattern) if path.is_file()]
    if pattern == "micro_main_usdt_proxy_backtest_*.json":
        candidates = [path for path in candidates if "unseen" not in path.name and "top" not in path.name]
    return sorted(
        candidates,
        key=lambda path: path.name,
        reverse=True,
    )


def _report_source_priority(source: str) -> int:
    if source == PORTFOLIO_MIX_REVIEW_SOURCE:
        return 3
    if source == USDT_DIRECT_BACKTEST_SOURCE:
        return 2
    return 1 if source == USDC_DIRECT_BACKTEST_SOURCE else 0


def _report_days(payload: dict[str, Any]) -> int:
    raw_days = payload.get("days")
    if raw_days is None and isinstance(payload.get("settings"), dict):
        raw_days = dict(payload.get("settings") or {}).get("days")
    return safe_int(raw_days, 0)


def _active_contract_report_dirs(settings: Any) -> list[Path]:
    configured = resolve_report_dir(
        settings,
        str(getattr(settings, "auto_trading_replay_validation_bridge_backtest_dir", "") or ""),
        default="reports/validation/micro_main_usdt_proxy_backtests",
    )
    dirs = [configured]
    if configured.name == "micro_main_usdt_proxy_backtests":
        dirs.extend([configured.parent / "micro_main_usdc_backtests", configured.parent / "micro_main_usdt_backtests"])
    elif configured.name == "micro_main_usdc_backtests":
        dirs.extend([configured.parent / "micro_main_usdt_proxy_backtests", configured.parent / "micro_main_usdt_backtests"])
    elif configured.name == "micro_main_usdt_backtests":
        dirs.extend([configured.parent / "micro_main_usdc_backtests", configured.parent / "micro_main_usdt_proxy_backtests"])
    unique: list[Path] = []
    seen: set[Path] = set()
    for directory in dirs:
        if directory in seen:
            continue
        seen.add(directory)
        unique.append(directory)
    return unique


def _ranked_active_contract_reports(settings: Any) -> list[tuple[Path, dict[str, Any], str]]:
    ranked: list[tuple[int, int, str, Path, dict[str, Any], str]] = []
    patterns = (
        ("micro_main_usdc_backtest_*.json", USDC_DIRECT_BACKTEST_SOURCE),
        ("micro_main_usdt_backtest_*.json", USDT_DIRECT_BACKTEST_SOURCE),
        ("micro_main_usdt_proxy_backtest_*.json", USDT_PROXY_BACKTEST_SOURCE),
    )
    for directory in _active_contract_report_dirs(settings):
        for pattern, source in patterns:
            for path in _recent_json_files(directory, pattern):
                try:
                    payload = json.loads(path.read_text())
                except Exception:
                    continue
                ranked.append(
                    (
                        _report_days(payload),
                        _report_source_priority(source),
                        path.name,
                        path,
                        payload,
                        source,
                    )
                )
    portfolio_mix_path = Path(
        str(
            getattr(
                settings,
                "auto_trading_replay_validation_bridge_portfolio_mix_report_path",
                DEFAULT_PORTFOLIO_MIX_REPORT,
            )
            or DEFAULT_PORTFOLIO_MIX_REPORT
        )
    ).expanduser()
    if not portfolio_mix_path.is_absolute():
        portfolio_mix_path = resolve_report_dir(settings, str(portfolio_mix_path), default=DEFAULT_PORTFOLIO_MIX_REPORT)
    if portfolio_mix_path.is_file():
        try:
            payload = json.loads(portfolio_mix_path.read_text())
        except Exception:
            payload = {}
        if str(payload.get("schema_version") or "") == "micro_intrabar_candidate_portfolio_mix_review_v1":
            ranked.append(
                (
                    _report_days(payload),
                    _report_source_priority(PORTFOLIO_MIX_REVIEW_SOURCE),
                    portfolio_mix_path.name,
                    portfolio_mix_path,
                    payload,
                    PORTFOLIO_MIX_REVIEW_SOURCE,
                )
            )
    return [
        (path, payload, source)
        for _days, _source_priority, _name, path, payload, source in sorted(ranked, reverse=True)
    ]


def _window_days_from_pair(window: dict[str, Any], start_key: str, end_key: str) -> float | None:
    start = parse_ts(window.get(start_key))
    end = parse_ts(window.get(end_key))
    if start is None or end is None or end <= start:
        return None
    return (end - start).total_seconds() / 86400.0


def _entry_effective_window_days(payload: dict[str, Any], raw_entry: dict[str, Any]) -> tuple[float, str]:
    window = dict(raw_entry.get("window") or {})
    for source, start_key, end_key in (
        ("entry_effective_window", "effective_start_ts", "effective_end_ts"),
        ("entry_actual_1m_window", "actual_start_1m_ts", "actual_end_1m_ts"),
        ("entry_requested_window", "requested_start_ts", "requested_end_ts"),
    ):
        days = _window_days_from_pair(window, start_key, end_key)
        if days is not None:
            return max(days, 1e-9), source
    report_days = safe_float(payload.get("days"), 0.0)
    return max(report_days, 0.0), "report_days"


def _portfolio_mix_rows_for_symbol(
    *,
    settings: Any,
    path: Path,
    payload: dict[str, Any],
    symbol: str,
    directions: set[str],
    sessions: set[str],
) -> dict[str, Any] | None:
    report_days = max(safe_float(dict(payload.get("settings") or {}).get("days"), 0.0), 1.0)
    for item in list(payload.get("per_contract") or []):
        if not isinstance(item, dict):
            continue
        contract_symbols = [str(raw or "").strip().upper() for raw in list(item.get("symbols") or []) if str(raw or "").strip()]
        if symbol not in contract_symbols:
            continue
        direction = str(dict(item.get("filter_contract") or {}).get("direction") or "").strip().upper()
        if directions and direction not in directions:
            continue
        setup_hours = [
            safe_int(raw, -1)
            for raw in list(dict(item.get("filter_contract") or {}).get("setup_hour_utc") or [])
        ]
        generated_sessions = {
            session_bucket(settings, datetime(2026, 1, 1, max(0, min(hour, 23)), tzinfo=timezone.utc))
            for hour in setup_hours
            if 0 <= hour <= 23
        }
        if sessions and generated_sessions and not (generated_sessions & sessions):
            continue
        closed = safe_int(dict(item.get("summary") or {}).get("closed"), 0)
        symbol_count = max(len(contract_symbols), 1)
        allocated_rows = max(int(round(closed / symbol_count)), 0)
        generated_session = sorted(generated_sessions)[0] if generated_sessions else ""
        rows = [
            {
                "symbol": symbol,
                "strategy_family": SESSION_IMPULSE_RETEST_FAMILY,
                "entry_model": SESSION_IMPULSE_RETEST_ENTRY_MODEL,
                "direction": direction,
                "generated_session": generated_session,
                "generated_ts": "",
                "portfolio_mix_estimated_row": True,
            }
            for _ in range(allocated_rows)
        ]
        return {
            "source": PORTFOLIO_MIX_REVIEW_SOURCE,
            "source_path": str(path),
            "generated_at": str(payload.get("generated_at") or ""),
            "days": report_days,
            "requested_days": report_days,
            "days_source": "portfolio_mix_settings_days",
            "window": {},
            "summary": dict(item.get("summary") or {}),
            "rows": rows,
            "estimated_rows": True,
            "allocation_method": "per_contract_closed_divided_by_contract_symbol_count",
        }
    return None


def usdt_proxy_rows_for_active_contract(settings: Any, filters: dict[str, Any]) -> dict[str, Any] | None:
    filter_payload = dict(filters or {})
    families = normalized_string_set(filter_payload.get("strategy_families"), case="lower")
    if families and SESSION_IMPULSE_RETEST_FAMILY not in families:
        return None
    entry_models = normalized_string_set(filter_payload.get("entry_models"), case="upper")
    if entry_models and SESSION_IMPULSE_RETEST_ENTRY_MODEL not in entry_models:
        return None

    symbol = str(filter_payload.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    directions = normalized_string_set(filter_payload.get("directions"), case="upper")
    sessions = normalized_string_set(filter_payload.get("sessions"), case="lower")
    active_symbols = active_micro_live_symbol_contract(settings)

    for path, payload, source in _ranked_active_contract_reports(settings):
        if active_symbols and usdt_proxy_contract_symbols(payload, source_hint=source) != active_symbols:
            continue
        if source == PORTFOLIO_MIX_REVIEW_SOURCE:
            portfolio_rows = _portfolio_mix_rows_for_symbol(
                settings=settings,
                path=path,
                payload=payload,
                symbol=symbol,
                directions=directions,
                sessions=sessions,
            )
            if portfolio_rows is not None:
                return portfolio_rows
            continue
        results = payload.get("results")
        if isinstance(results, dict):
            iterable = results.items()
        elif isinstance(results, list):
            iterable = ((None, item) for item in results)
        else:
            continue
        for key, raw_entry in iterable:
            if not isinstance(raw_entry, dict):
                continue
            proxy_symbol = str(raw_entry.get("proxy_symbol") or key or raw_entry.get("symbol") or "").strip().upper()
            canonical = contract_symbol_for_source(
                raw_entry.get("canonical_symbol") or raw_entry.get("symbol") or proxy_symbol,
                source,
                proxy_symbol=bool(raw_entry.get("proxy_symbol")) and not raw_entry.get("canonical_symbol"),
            )
            if canonical != symbol:
                continue
            rows: list[dict[str, Any]] = []
            for raw_trade in list(raw_entry.get("trades") or []):
                if not isinstance(raw_trade, dict):
                    continue
                trade = dict(raw_trade)
                family = str(trade.get("family") or SESSION_IMPULSE_RETEST_FAMILY).strip().lower()
                if family != SESSION_IMPULSE_RETEST_FAMILY:
                    continue
                direction = str(trade.get("direction") or "").strip().upper()
                if directions and direction not in directions:
                    continue
                generated_ts = parse_ts(trade.get("entry_ts") or trade.get("signal_ts"))
                generated_session = session_bucket(settings, generated_ts)
                if sessions and generated_session not in sessions:
                    continue
                rows.append(
                    {
                        **trade,
                        "symbol": canonical,
                        "proxy_symbol": proxy_symbol,
                        "strategy_family": SESSION_IMPULSE_RETEST_FAMILY,
                        "entry_model": SESSION_IMPULSE_RETEST_ENTRY_MODEL,
                        "direction": direction,
                        "generated_ts": generated_ts.isoformat() if generated_ts is not None else "",
                        "generated_session": generated_session,
                    }
                )
            effective_days, effective_days_source = _entry_effective_window_days(payload, raw_entry)
            return {
                "source": source,
                "source_path": str(path),
                "generated_at": str(payload.get("generated_at") or ""),
                "days": effective_days,
                "requested_days": max(safe_float(payload.get("days"), 0.0), 0.0),
                "days_source": effective_days_source,
                "window": dict(raw_entry.get("window") or {}),
                "summary": dict(raw_entry.get("summary") or {}),
                "rows": rows,
            }
    return None


def count_recent_rows(rows: list[dict[str, Any]], *, days: int) -> int:
    timestamps = [parse_ts(row.get("generated_ts") or row.get("entry_ts") or row.get("signal_ts")) for row in rows]
    timestamps = [ts for ts in timestamps if ts is not None]
    if not timestamps:
        return 0
    latest = max(timestamps)
    start = latest - timedelta(days=max(int(days or 1), 1))
    return sum(1 for ts in timestamps if ts >= start)
