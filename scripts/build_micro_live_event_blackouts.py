#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from scripts.operation_report_io import write_json
from scripts.run_micro_live_preflight import _csv_set


FED_FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BLS_CPI_URL = "https://www.bls.gov/schedule/news_release/cpi.htm"
BLS_EMPSIT_URL = "https://www.bls.gov/schedule/news_release/empsit.htm"
BLS_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
NY_TZ = ZoneInfo("America/New_York")
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build MICRO_LIVE macro-event blackout contract from official calendars.")
    parser.add_argument("--years", default="2026,2027")
    parser.add_argument("--symbols", default="")
    parser.add_argument("--families", default="")
    parser.add_argument("--entry-models", default="")
    parser.add_argument("--pre-minutes", type=int, default=15)
    parser.add_argument("--post-minutes", type=int, default=30)
    parser.add_argument(
        "--output",
        default="reports/validation/contracts/micro_live_event_blackouts_major_us_macro_auto.json",
    )
    parser.add_argument(
        "--fallback-input",
        default="",
        help="Existing blackout contract used to fill gaps when an official source blocks automated fetching.",
    )
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--write-on-source-error", action="store_true")
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


def _fetch_text(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            ),
            "Accept": "text/html,text/calendar,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310
        return response.read().decode("utf-8", errors="replace")


def _html_lines(raw: str) -> list[str]:
    text = re.sub(r"<script\b.*?</script>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = html.unescape(text)
    return [line.strip() for line in text.splitlines() if line.strip()]


def _month_number(value: str) -> int | None:
    tokens = [token for token in re.split(r"[/\s]+", str(value or "").strip().lower()) if token]
    for token in reversed(tokens):
        if token in MONTHS:
            return MONTHS[token]
    return None


def _to_utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=NY_TZ).astimezone(UTC)


def parse_fomc_events(raw_html: str, *, years: set[int]) -> list[dict[str, Any]]:
    lines = _html_lines(raw_html)
    events: list[dict[str, Any]] = []
    current_year: int | None = None
    current_month_text = ""
    for line in lines:
        year_match = re.fullmatch(r"(\d{4})\s+FOMC Meetings", line, flags=re.IGNORECASE)
        if year_match:
            current_year = int(year_match.group(1))
            current_month_text = ""
            continue
        if current_year is None:
            continue
        if re.fullmatch(r"\d{4}", line) or line.lower().startswith("future year"):
            current_year = None
            current_month_text = ""
            continue
        month = _month_number(line)
        if month is not None and not re.search(r"\d", line):
            current_month_text = line
            continue
        if current_year not in years or not current_month_text:
            continue
        date_match = re.fullmatch(r"(\d{1,2})(?:-(\d{1,2}))?\*?", line)
        if not date_match:
            continue
        event_month = _month_number(current_month_text)
        if event_month is None:
            continue
        end_day = int(date_match.group(2) or date_match.group(1))
        # Cross-month legacy rows like Apr/May 30-1 end in the last month token.
        if "-" in line and int(date_match.group(2) or 0) < int(date_match.group(1)):
            event_month = _month_number(current_month_text)
        event_ts = _to_utc(current_year, event_month, end_day, 14, 0)
        events.append(
            {
                "code": "FOMC",
                "label": f"FOMC_{event_ts.strftime('%Y_%m_%d')}",
                "event_ts_utc": event_ts,
                "source": FED_FOMC_URL,
            }
        )
    return events


def parse_bls_release_events(raw_html: str, *, code: str, years: set[int], source: str) -> list[dict[str, Any]]:
    text = " ".join(_html_lines(raw_html))
    pattern = re.compile(
        r"([A-Za-z]+)\s+(\d{4})\s+([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s+(\d{4})\s+(\d{1,2}):(\d{2})\s+(AM|PM)",
        flags=re.IGNORECASE,
    )
    events: list[dict[str, Any]] = []
    for match in pattern.finditer(text):
        release_month = _month_number(match.group(3))
        release_day = int(match.group(4))
        release_year = int(match.group(5))
        if release_month is None or release_year not in years:
            continue
        hour = int(match.group(6))
        minute = int(match.group(7))
        ampm = match.group(8).upper()
        if ampm == "PM" and hour != 12:
            hour += 12
        if ampm == "AM" and hour == 12:
            hour = 0
        event_ts = _to_utc(release_year, release_month, release_day, hour, minute)
        events.append(
            {
                "code": code,
                "label": f"{code}_{event_ts.strftime('%Y_%m_%d')}",
                "event_ts_utc": event_ts,
                "source": source,
            }
        )
    return events


def _unfold_ics_lines(raw_ics: str) -> list[str]:
    lines: list[str] = []
    for raw_line in raw_ics.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw_line.startswith((" ", "\t")) and lines:
            lines[-1] += raw_line[1:]
        elif raw_line:
            lines.append(raw_line)
    return lines


def _ics_value(line: str) -> tuple[str, str]:
    head, _, value = line.partition(":")
    key = head.split(";", 1)[0].upper()
    return key, value.replace("\\,", ",").replace("\\n", "\n")


def parse_bls_ics_events(raw_ics: str, *, code: str, years: set[int], source: str = BLS_ICS_URL) -> list[dict[str, Any]]:
    summary_token = {
        "CPI": "consumer price index",
        "NFP": "employment situation",
    }.get(code.upper())
    if not summary_token:
        return []

    events: list[dict[str, Any]] = []
    current: dict[str, str] | None = None
    for line in _unfold_ics_lines(raw_ics):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            row = dict(current or {})
            current = None
            summary = row.get("SUMMARY", "")
            if summary_token not in summary.lower():
                continue
            raw_start = row.get("DTSTART", "")
            match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(?:\d{2})?", raw_start)
            if not match:
                continue
            year = int(match.group(1))
            if year not in years:
                continue
            event_ts = _to_utc(
                year,
                int(match.group(2)),
                int(match.group(3)),
                int(match.group(4)),
                int(match.group(5)),
            )
            events.append(
                {
                    "code": code.upper(),
                    "label": f"{code.upper()}_{event_ts.strftime('%Y_%m_%d')}",
                    "event_ts_utc": event_ts,
                    "source": source,
                }
            )
            continue
        if current is not None:
            key, value = _ics_value(line)
            current[key] = value
    return events


def _window(event: dict[str, Any], *, symbols: list[str], families: list[str], entry_models: list[str], pre_minutes: int, post_minutes: int) -> dict[str, Any]:
    event_ts = event["event_ts_utc"]
    start = event_ts - timedelta(minutes=max(0, int(pre_minutes)))
    end = event_ts + timedelta(minutes=max(0, int(post_minutes)))
    return {
        "label": event["label"],
        "start_utc": start.isoformat().replace("+00:00", "Z"),
        "end_utc": end.isoformat().replace("+00:00", "Z"),
        "symbols": symbols,
        "strategy_families": families,
        "entry_models": entry_models,
        "source": event["source"],
    }


def _events_from_fallback_contract(
    raw_path: str,
    *,
    years: set[int],
    pre_minutes: int,
    needed_codes: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not raw_path:
        return []
    path = _resolve_root_path(raw_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("windows") if isinstance(payload, dict) else []
    events: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        item = dict(row or {}) if isinstance(row, dict) else {}
        label = str(item.get("label") or "")
        code = label.split("_", 1)[0].upper()
        if code not in {"FOMC", "CPI", "NFP"}:
            continue
        if needed_codes is not None and code not in needed_codes:
            continue
        raw_event_ts = str(item.get("event_ts_utc") or "")
        raw_start = str(item.get("start_utc") or "")
        try:
            event_ts = (
                datetime.fromisoformat(raw_event_ts.replace("Z", "+00:00"))
                if raw_event_ts
                else datetime.fromisoformat(raw_start.replace("Z", "+00:00")) + timedelta(minutes=max(0, int(pre_minutes)))
            )
        except ValueError:
            continue
        if event_ts.tzinfo is None:
            event_ts = event_ts.replace(tzinfo=UTC)
        event_ts = event_ts.astimezone(UTC)
        if event_ts.year not in years:
            continue
        events.append(
            {
                "code": code,
                "label": label or f"{code}_{event_ts.strftime('%Y_%m_%d')}",
                "event_ts_utc": event_ts,
                "source": f"fallback:{_display_path(path)}",
            }
        )
    return events


def _dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for event in events:
        key = str(event.get("label") or "")
        if key and key not in deduped:
            deduped[key] = event
    return list(deduped.values())


def build_contract(
    *,
    years: set[int],
    symbols: list[str],
    families: list[str],
    entry_models: list[str],
    pre_minutes: int,
    post_minutes: int,
    fallback_input: str = "",
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    source_warnings: list[dict[str, str]] = []
    fatal_errors: list[dict[str, str]] = []
    try:
        events.extend(parse_fomc_events(_fetch_text(FED_FOMC_URL), years=years))
    except Exception as exc:
        source_warnings.append({"source": FED_FOMC_URL, "error": f"{exc.__class__.__name__}:{exc}"})
    try:
        events.extend(parse_bls_release_events(_fetch_text(BLS_CPI_URL), code="CPI", years=years, source=BLS_CPI_URL))
    except Exception as exc:
        source_warnings.append({"source": BLS_CPI_URL, "error": f"{exc.__class__.__name__}:{exc}"})
    try:
        events.extend(parse_bls_release_events(_fetch_text(BLS_EMPSIT_URL), code="NFP", years=years, source=BLS_EMPSIT_URL))
    except Exception as exc:
        source_warnings.append({"source": BLS_EMPSIT_URL, "error": f"{exc.__class__.__name__}:{exc}"})

    present_codes = {str(event.get("code") or "").upper() for event in events}
    if "CPI" not in present_codes or "NFP" not in present_codes:
        try:
            raw_ics = _fetch_text(BLS_ICS_URL)
            if "CPI" not in present_codes:
                events.extend(parse_bls_ics_events(raw_ics, code="CPI", years=years))
            if "NFP" not in present_codes:
                events.extend(parse_bls_ics_events(raw_ics, code="NFP", years=years))
        except Exception as exc:
            source_warnings.append({"source": BLS_ICS_URL, "error": f"{exc.__class__.__name__}:{exc}"})

    present_codes = {str(event.get("code") or "").upper() for event in events}
    fallback_events: list[dict[str, Any]] = []
    missing_before_fallback = {"FOMC", "CPI", "NFP"} - present_codes
    if fallback_input and missing_before_fallback:
        fallback_events = _events_from_fallback_contract(
            fallback_input,
            years=years,
            pre_minutes=pre_minutes,
            needed_codes=missing_before_fallback,
        )
        events.extend(fallback_events)

    events = _dedupe_events(events)
    present_codes = {str(event.get("code") or "").upper() for event in events}
    missing_codes = sorted({"FOMC", "CPI", "NFP"} - present_codes)
    for code in missing_codes:
        fatal_errors.append({"source": code, "error": "no events available from primary, ICS, or fallback sources"})

    events.sort(key=lambda item: item["event_ts_utc"])
    windows = [
        _window(
            event,
            symbols=symbols,
            families=families,
            entry_models=entry_models,
            pre_minutes=pre_minutes,
            post_minutes=post_minutes,
        )
        for event in events
    ]
    return {
        "schema_version": "micro_live_event_blackout_v1",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "overall_status": "SOURCE_ERROR" if fatal_errors else ("PASS_WITH_WARNINGS" if source_warnings else "PASS"),
        "source_errors": fatal_errors,
        "source_warnings": source_warnings,
        "fallback_input": fallback_input,
        "fallback_window_count": len(fallback_events),
        "source_notes": [
            f"FOMC dates are parsed from {FED_FOMC_URL}; statement release is treated as 2:00 p.m. America/New_York.",
            f"CPI release dates are parsed from {BLS_CPI_URL}, with {BLS_ICS_URL} and fallback contract recovery.",
            f"Employment Situation/NFP release dates are parsed from {BLS_EMPSIT_URL}, with {BLS_ICS_URL} and fallback contract recovery.",
            f"Windows block new MICRO_LIVE entries from {pre_minutes} minutes before to {post_minutes} minutes after.",
        ],
        "windows": windows,
    }


def main() -> int:
    args = parse_args()
    settings = get_settings()
    years = {int(item) for item in str(args.years or "").split(",") if item.strip()}
    symbols = sorted(_csv_set(args.symbols or getattr(settings, "auto_trading_micro_live_allowed_symbols", "")))
    families = sorted(_csv_set(args.families or getattr(settings, "auto_trading_micro_live_allowed_families", ""), lower=True))
    entry_models = sorted(_csv_set(args.entry_models or getattr(settings, "auto_trading_micro_live_allowed_entry_models", "")))
    fallback_input = str(args.fallback_input or getattr(settings, "auto_trading_micro_live_event_blackout_path", "") or "")
    payload = build_contract(
        years=years,
        symbols=symbols,
        families=families,
        entry_models=entry_models,
        pre_minutes=max(0, int(args.pre_minutes)),
        post_minutes=max(0, int(args.post_minutes)),
        fallback_input=fallback_input,
    )
    if not args.no_write and (payload["overall_status"] != "SOURCE_ERROR" or bool(args.write_on_source_error)):
        output_path = _resolve_root_path(str(args.output))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload["output_path"] = _display_path(output_path)
        write_json(output_path, payload, json_default=_json_default)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 1 if payload["overall_status"] == "SOURCE_ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
