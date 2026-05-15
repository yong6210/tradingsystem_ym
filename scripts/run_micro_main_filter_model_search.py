#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text


RowFilter = Callable[[dict[str, Any]], bool]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search compare-only filter candidates for session_impulse_retest.")
    parser.add_argument("--backtest-path", default="")
    parser.add_argument("--report-dir", default="")
    parser.add_argument("--min-keep-share", type=float, default=0.75)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_dt(value: Any) -> datetime:
    text = str(value or "").replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _diagnostic_float(row: dict[str, Any], key: str) -> float:
    return _safe_float(dict(row.get("diagnostics") or {}).get(key), default=float("nan"))


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (_parse_dt(row.get("exit_ts")), _parse_dt(row.get("entry_ts")), str(row.get("symbol") or "")))
    r_values = [_safe_float(row.get("r_value")) for row in ordered]
    total = sum(r_values)
    wins = sum(1 for value in r_values if value > 0.0)
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in r_values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    closed = len(r_values)
    return {
        "trades": closed,
        "total_r": round(total, 4),
        "ev_r": round(total / closed, 4) if closed else 0.0,
        "win_rate": round(wins / closed, 4) if closed else 0.0,
        "max_dd_r": round(max_drawdown, 4),
    }


def _group(rows: list[dict[str, Any]], key_fn: Callable[[dict[str, Any]], Any]) -> dict[Any, list[dict[str, Any]]]:
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(key_fn(row), []).append(row)
    return grouped


def _year_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {str(year): _stats(bucket) for year, bucket in sorted(_group(rows, lambda row: _parse_dt(row.get("entry_ts")).year).items())}


def _latest_trade_backtest_path() -> Path:
    base = Path(get_settings().validation_report_dir) / "micro_main_usdt_proxy_backtests"
    candidates = sorted(base.glob("micro_main_usdt_proxy_backtest_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        trade_count = sum(len(dict(item or {}).get("trades") or []) for item in dict(payload.get("results") or {}).values())
        if trade_count > 0:
            return candidate
    raise FileNotFoundError(f"No trade-including micro-main backtest JSON found under {base}")


def _load_rows(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for item in dict(payload.get("results") or {}).values():
        rows.extend(list(dict(item or {}).get("trades") or []))
    return payload, rows


def _candidate_filters(rows: list[dict[str, Any]]) -> list[tuple[str, RowFilter, str]]:
    candidates: list[tuple[str, RowFilter, str]] = []

    def add(name: str, fn: RowFilter, kind: str = "single") -> None:
        candidates.append((name, fn, kind))

    for threshold in (0.22, 0.25, 0.28, 0.30, 0.35, 0.40, 0.45, 0.50):
        add(
            f"reclaim_body_atr >= {threshold:.2f}",
            lambda row, threshold=threshold: _diagnostic_float(row, "reclaim_body_atr") >= threshold,
        )
    for threshold in (0.80, 0.90, 1.00, 1.10, 1.20):
        add(f"risk_atr <= {threshold:.2f}", lambda row, threshold=threshold: _diagnostic_float(row, "risk_atr") <= threshold)
    for threshold in (0.90, 1.00, 1.10, 1.20, 1.30, 1.50):
        add(
            f"volume_factor >= {threshold:.2f}",
            lambda row, threshold=threshold: _diagnostic_float(row, "volume_factor") >= threshold,
        )
    for threshold in (0, 1, 2):
        add(
            f"retest_wait_minutes <= {threshold}",
            lambda row, threshold=threshold: _diagnostic_float(row, "retest_wait_minutes") <= threshold,
        )
    for hour in range(24):
        add(f"block signal_hour_utc == {hour}", lambda row, hour=hour: _safe_int(row.get("signal_hour_utc")) != hour, "hour_block")
    for weekday in range(7):
        add(
            f"block weekday_utc == {weekday}",
            lambda row, weekday=weekday: _safe_int(row.get("entry_weekday_utc")) != weekday,
            "weekday_block",
        )
    for key in ("risk_atr_bucket", "volume_factor_bucket", "retest_wait_bucket"):
        for bucket in sorted({str(row.get(key) or "unknown") for row in rows}):
            add(f"block {key} == {bucket}", lambda row, key=key, bucket=bucket: str(row.get(key) or "unknown") != bucket, "bucket_block")
    for symbol in sorted({str(row.get("symbol") or "") for row in rows if str(row.get("symbol") or "")}):
        for hour in range(24):
            bucket = [row for row in rows if str(row.get("symbol") or "") == symbol and _safe_int(row.get("signal_hour_utc")) == hour]
            if len(bucket) < 8:
                continue
            bucket_stats = _stats(bucket)
            if _safe_float(bucket_stats.get("total_r")) < 0.0 or _safe_float(bucket_stats.get("ev_r")) < 0.05:
                add(
                    f"block {symbol} hour {hour}",
                    lambda row, symbol=symbol, hour=hour: not (
                        str(row.get("symbol") or "") == symbol and _safe_int(row.get("signal_hour_utc")) == hour
                    ),
                    "symbol_hour_block",
                )
    return candidates


def _threshold_metric_name(name: str) -> str | None:
    text = str(name or "")
    for prefix in (
        "reclaim_body_atr >=",
        "risk_atr <=",
        "volume_factor >=",
        "retest_wait_minutes <=",
    ):
        if text.startswith(prefix):
            return prefix
    return None


def _evaluate_candidates(rows: list[dict[str, Any]], *, min_keep_share: float) -> dict[str, Any]:
    baseline = _stats(rows)
    baseline_years = _year_stats(rows)
    baseline_trades = int(baseline["trades"])
    min_trades = max(1, int(baseline_trades * max(min(float(min_keep_share), 1.0), 0.0)))
    candidates = _candidate_filters(rows)
    evaluated: list[dict[str, Any]] = []
    candidate_map: dict[str, RowFilter] = {}

    def record(name: str, kind: str, kept: list[dict[str, Any]]) -> None:
        if len(kept) < min_trades or len(kept) >= baseline_trades:
            return
        stats = _stats(kept)
        years = _year_stats(kept)
        years_improved = sum(
            1
            for year, item in years.items()
            if _safe_float(item.get("total_r")) > _safe_float(dict(baseline_years.get(year) or {}).get("total_r"), -1e9)
        )
        years_positive = sum(1 for item in years.values() if _safe_float(item.get("total_r")) > 0.0)
        evaluated.append(
            {
                "name": name,
                "kind": kind,
                "removed": baseline_trades - int(stats["trades"]),
                "removed_pct": round((baseline_trades - int(stats["trades"])) / max(baseline_trades, 1), 4),
                "stats": stats,
                "delta_total_r": round(_safe_float(stats.get("total_r")) - _safe_float(baseline.get("total_r")), 4),
                "delta_ev_r": round(_safe_float(stats.get("ev_r")) - _safe_float(baseline.get("ev_r")), 4),
                "delta_dd_r": round(_safe_float(stats.get("max_dd_r")) - _safe_float(baseline.get("max_dd_r")), 4),
                "years_improved_total": years_improved,
                "years_positive": years_positive,
                "years": years,
            }
        )

    for name, fn, kind in candidates:
        candidate_map[name] = fn
        record(name, kind, [row for row in rows if fn(row)])

    def score(item: dict[str, Any]) -> float:
        return (
            _safe_float(item.get("delta_total_r"))
            + max(0.0, -_safe_float(item.get("delta_dd_r"))) * 2.0
            + _safe_float(item.get("delta_ev_r")) * 500.0
            - _safe_float(item.get("removed_pct")) * 50.0
            + _safe_int(item.get("years_improved_total")) * 20.0
        )

    pool = [
        str(item.get("name"))
        for item in sorted(evaluated, key=score, reverse=True)
        if _safe_float(item.get("delta_ev_r")) > 0.005
        or _safe_float(item.get("delta_total_r")) > 0.0
        or _safe_float(item.get("delta_dd_r")) < -0.5
    ][:80]
    for left, right in itertools.combinations(pool, 2):
        if _threshold_metric_name(left) and _threshold_metric_name(left) == _threshold_metric_name(right):
            continue
        left_fn = candidate_map.get(left)
        right_fn = candidate_map.get(right)
        if left_fn is None or right_fn is None:
            continue
        record(f"{left} AND {right}", "pair", [row for row in rows if left_fn(row) and right_fn(row)])

    practical = [
        item
        for item in evaluated
        if _safe_float(item.get("delta_ev_r")) > 0.0
        and _safe_int(item.get("years_positive")) >= len(baseline_years)
        and _safe_int(dict(item.get("stats") or {}).get("trades")) >= min_trades
    ]
    practical.sort(key=score, reverse=True)
    return {
        "baseline": baseline,
        "baseline_years": baseline_years,
        "min_keep_share": round(float(min_keep_share), 4),
        "top_practical": practical[:25],
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    baseline = dict(payload.get("baseline") or {})
    lines = [
        "# Micro Main Filter Model Search",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- source_backtest: {payload.get('source_backtest')}",
        f"- baseline: trades={baseline.get('trades')} total_r={baseline.get('total_r')} ev={baseline.get('ev_r')} win={baseline.get('win_rate')} max_dd={baseline.get('max_dd_r')}",
        "",
        "## Top Compare-Only Candidates",
    ]
    for item in list(payload.get("top_practical") or [])[:10]:
        stats = dict(item.get("stats") or {})
        lines.append(
            f"- {item.get('name')}: trades={stats.get('trades')} total_r={stats.get('total_r')} "
            f"ev={stats.get('ev_r')} win={stats.get('win_rate')} max_dd={stats.get('max_dd_r')} "
            f"delta_total_r={item.get('delta_total_r')} delta_ev={item.get('delta_ev_r')} "
            f"removed={item.get('removed')} years_improved={item.get('years_improved_total')}"
        )
    lines.extend(["", "All candidates are compare-only. Do not apply to live routing without a separate approval step."])
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    source_path = Path(args.backtest_path).expanduser() if str(args.backtest_path or "").strip() else _latest_trade_backtest_path()
    if not source_path.is_absolute():
        source_path = ROOT_DIR / source_path
    backtest_payload, rows = _load_rows(source_path)
    if not rows:
        raise SystemExit(f"Backtest report has no trade rows: {source_path}")

    generated_at = datetime.now(UTC)
    result = _evaluate_candidates(rows, min_keep_share=float(args.min_keep_share))
    payload = {
        "schema_version": "micro_main_filter_model_search_v1",
        "generated_at": generated_at.isoformat(),
        "source_backtest": str(source_path),
        "source_backtest_generated_at": backtest_payload.get("generated_at"),
        **result,
    }
    if args.write_report:
        report_dir = Path(args.report_dir) if str(args.report_dir or "").strip() else Path(get_settings().validation_report_dir) / "micro_main_filter_model_searches"
        if not report_dir.is_absolute():
            report_dir = ROOT_DIR / report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        stem = f"micro_main_filter_model_search_{generated_at.strftime('%Y%m%dT%H%M%SZ')}"
        json_path = report_dir / f"{stem}.json"
        md_path = report_dir / f"{stem}.md"
        latest_json = report_dir / "latest.json"
        latest_md = report_dir / "latest.md"
        payload["report_path"] = str(json_path)
        payload["latest_report_path"] = str(latest_json)
        atomic_write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2))
        atomic_write_text(md_path, _render_markdown(payload))
        atomic_write_text(latest_json, json.dumps(payload, ensure_ascii=False, indent=2))
        atomic_write_text(latest_md, _render_markdown(payload))

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
