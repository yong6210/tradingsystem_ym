from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from math import isfinite
from pathlib import Path
from typing import Any


SESSION_IMPULSE_RETEST_FAMILY = "session_impulse_retest"
SESSION_IMPULSE_RETEST_ENTRY_MODEL = "CONFIRM"


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


def _recent_json_files(directory: Path, pattern: str) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        [path for path in directory.glob(pattern) if path.is_file()],
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )


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
    directory = resolve_report_dir(
        settings,
        str(getattr(settings, "auto_trading_replay_validation_bridge_backtest_dir", "") or ""),
        default="reports/validation/micro_main_usdt_proxy_backtests",
    )

    for path in _recent_json_files(directory, "micro_main_usdt_proxy_backtest_*.json"):
        try:
            payload = json.loads(path.read_text())
        except Exception:
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
            proxy_symbol = str(raw_entry.get("proxy_symbol") or key or "").strip().upper()
            canonical = canonical_symbol_from_proxy(raw_entry.get("canonical_symbol") or proxy_symbol)
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
            return {
                "source": "micro_main_usdt_proxy_backtest",
                "source_path": str(path),
                "generated_at": str(payload.get("generated_at") or ""),
                "days": max(safe_int(payload.get("days"), 0), 0),
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
