#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text


@dataclass(frozen=True, slots=True)
class WeightModel:
    name: str
    weights: dict[str, float]
    note: str = ""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest compare-only weighted filters on a micro-main trade-including backtest report."
    )
    parser.add_argument("--backtest-path", required=True)
    parser.add_argument("--report-dir", default="")
    parser.add_argument("--min-keep-share", type=float, default=0.60)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed == parsed else default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_dt(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _load_rows(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for item in dict(payload.get("results") or {}).values():
        if not isinstance(item, dict):
            continue
        for row in list(item.get("trades") or []):
            if isinstance(row, dict):
                rows.append(row)
    if not rows:
        raise ValueError(f"Backtest report has no trade rows: {path}")
    return payload, rows


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        rows,
        key=lambda row: (_parse_dt(row.get("exit_ts")), _parse_dt(row.get("entry_ts")), str(row.get("symbol") or "")),
    )
    values = [_safe_float(row.get("r_value")) for row in ordered]
    total = sum(values)
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    closed = len(values)
    wins = sum(1 for value in values if value > 0.0)
    return {
        "trades": closed,
        "total_r": round(total, 4),
        "ev_r": round(total / closed, 4) if closed else 0.0,
        "win_rate": round(wins / closed, 4) if closed else 0.0,
        "max_dd_r": round(max_drawdown, 4),
    }


def _group_stats(rows: list[dict[str, Any]], key_fn) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(key_fn(row)), []).append(row)
    return {key: _stats(bucket) for key, bucket in sorted(grouped.items())}


def _clip01(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


def _scale_high(value: Any, low: float, high: float) -> float:
    return _clip01((_safe_float(value) - low) / max(high - low, 1e-12))


def _scale_low(value: Any, low: float, high: float) -> float:
    return 1.0 - _scale_high(value, low, high)


def _diagnostics(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row.get("diagnostics") or {})


def _feature_scores(row: dict[str, Any]) -> dict[str, float]:
    diagnostics = _diagnostics(row)
    return {
        "body": _scale_high(diagnostics.get("reclaim_body_atr"), 0.20, 0.60),
        "volume": _scale_high(diagnostics.get("volume_factor"), 0.90, 2.20),
        "trend": _scale_high(diagnostics.get("trend_strength_atr"), 0.45, 1.25),
        "overshoot": _scale_low(diagnostics.get("reclaim_overshoot_atr"), 0.05, 0.35),
        "risk": _scale_low(diagnostics.get("risk_atr"), 0.30, 1.15),
        "speed": _scale_low(diagnostics.get("retest_wait_minutes"), 0.0, 10.0),
    }


def _weighted_score(row: dict[str, Any], model: WeightModel) -> float:
    scores = _feature_scores(row)
    total_weight = sum(max(float(value), 0.0) for value in model.weights.values())
    if total_weight <= 0.0:
        return 0.0
    score = sum(scores.get(key, 0.0) * max(float(weight), 0.0) for key, weight in model.weights.items()) / total_weight
    return round(score, 6)


def _weight_models() -> list[WeightModel]:
    return [
        WeightModel(
            name="weighted_balanced",
            weights={"body": 1.0, "volume": 1.0, "trend": 1.0, "overshoot": 1.0, "risk": 1.0, "speed": 0.5},
            note="balanced score across confirmation, risk, and retest quality",
        ),
        WeightModel(
            name="weighted_quality",
            weights={"body": 1.4, "volume": 1.2, "trend": 1.2, "overshoot": 1.0, "risk": 0.8, "speed": 0.4},
            note="prioritizes strong reclaim body, volume, and trend",
        ),
        WeightModel(
            name="weighted_safety",
            weights={"body": 1.0, "volume": 1.0, "trend": 1.0, "overshoot": 1.2, "risk": 1.5, "speed": 0.8},
            note="penalizes wide risk and messy retests more heavily",
        ),
        WeightModel(
            name="weighted_frequency",
            weights={"body": 0.8, "volume": 0.9, "trend": 0.8, "overshoot": 0.7, "risk": 0.7, "speed": 0.3},
            note="keeps more signals while still ranking weak setups lower",
        ),
        WeightModel(
            name="weighted_volume_trend",
            weights={"body": 0.9, "volume": 1.6, "trend": 1.5, "overshoot": 0.7, "risk": 0.7, "speed": 0.3},
            note="leans on volume and trend confirmation",
        ),
        WeightModel(
            name="weighted_clean_retest",
            weights={"body": 1.1, "volume": 0.9, "trend": 0.9, "overshoot": 1.5, "risk": 1.1, "speed": 1.0},
            note="leans on clean, fast, low-risk retests",
        ),
    ]


def _percentile(values: list[float], pct: float) -> float:
    clean = sorted(value for value in values if value == value)
    if not clean:
        return 0.0
    idx = int((len(clean) - 1) * _clip01(pct))
    return float(clean[idx])


def _evaluate(rows: list[dict[str, Any]], *, min_keep_share: float) -> dict[str, Any]:
    baseline = _stats(rows)
    baseline_years = _group_stats(rows, lambda row: _parse_dt(row.get("entry_ts")).year)
    baseline_symbols = _group_stats(rows, lambda row: row.get("symbol") or "unknown")
    baseline_trades = int(baseline["trades"])
    min_trades = max(1, int(baseline_trades * _clip01(min_keep_share)))
    results: list[dict[str, Any]] = []

    for model in _weight_models():
        scored_rows = [(row, _weighted_score(row, model)) for row in rows]
        thresholds = {round(x / 100.0, 2) for x in range(40, 86, 5)}
        for keep_share in (0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60):
            thresholds.add(round(_percentile([score for _row, score in scored_rows], 1.0 - keep_share), 4))
        for threshold in sorted(thresholds):
            kept = [row for row, score in scored_rows if score >= threshold]
            if len(kept) < min_trades or len(kept) >= baseline_trades:
                continue
            stats = _stats(kept)
            years = _group_stats(kept, lambda row: _parse_dt(row.get("entry_ts")).year)
            symbols = _group_stats(kept, lambda row: row.get("symbol") or "unknown")
            years_improved = sum(
                1
                for year, item in years.items()
                if _safe_float(item.get("total_r")) > _safe_float(dict(baseline_years.get(year) or {}).get("total_r"), -1e9)
            )
            years_positive = sum(1 for item in years.values() if _safe_float(item.get("total_r")) > 0.0)
            symbol_positive = sum(1 for item in symbols.values() if _safe_float(item.get("total_r")) > 0.0)
            removed = baseline_trades - int(stats["trades"])
            removed_pct = removed / max(baseline_trades, 1)
            results.append(
                {
                    "name": f"{model.name}_score_ge_{threshold:.4f}",
                    "model": model.name,
                    "threshold": round(float(threshold), 4),
                    "weights": dict(model.weights),
                    "note": model.note,
                    "removed": removed,
                    "removed_pct": round(removed_pct, 4),
                    "stats": stats,
                    "delta_total_r": round(_safe_float(stats.get("total_r")) - _safe_float(baseline.get("total_r")), 4),
                    "delta_ev_r": round(_safe_float(stats.get("ev_r")) - _safe_float(baseline.get("ev_r")), 4),
                    "delta_dd_r": round(_safe_float(stats.get("max_dd_r")) - _safe_float(baseline.get("max_dd_r")), 4),
                    "years_improved_total": years_improved,
                    "years_positive": years_positive,
                    "symbols_positive": symbol_positive,
                    "symbol_count": len(symbols),
                    "years": years,
                    "worst_symbols": sorted(
                        (
                            {"symbol": symbol, **item}
                            for symbol, item in symbols.items()
                            if _safe_int(item.get("trades")) >= 10
                        ),
                        key=lambda item: _safe_float(item.get("total_r")),
                    )[:12],
                }
            )

    def score(item: dict[str, Any]) -> float:
        return (
            _safe_float(item.get("delta_total_r"))
            + _safe_float(item.get("delta_ev_r")) * 700.0
            + max(0.0, -_safe_float(item.get("delta_dd_r"))) * 2.0
            - _safe_float(item.get("removed_pct")) * 60.0
            + _safe_int(item.get("years_improved_total")) * 20.0
            + _safe_int(item.get("symbols_positive")) * 1.0
        )

    practical = [
        item
        for item in results
        if _safe_int(dict(item.get("stats") or {}).get("trades")) >= min_trades
        and _safe_int(item.get("years_positive")) >= max(1, len(baseline_years) - 1)
        and _safe_float(item.get("delta_ev_r")) >= 0.0
    ]
    practical.sort(key=score, reverse=True)
    return {
        "baseline": baseline,
        "baseline_years": baseline_years,
        "baseline_symbols": baseline_symbols,
        "min_keep_share": round(float(min_keep_share), 4),
        "top_weighted_filters": practical[:30],
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    baseline = dict(payload.get("baseline") or {})
    lines = [
        "# Micro Main Weighted Filter Backtest",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- source_backtest: {payload.get('source_backtest')}",
        f"- baseline: trades={baseline.get('trades')} total_r={baseline.get('total_r')} ev={baseline.get('ev_r')} win={baseline.get('win_rate')} max_dd={baseline.get('max_dd_r')}",
        "",
        "## Top Weighted Filters",
    ]
    for item in list(payload.get("top_weighted_filters") or [])[:12]:
        stats = dict(item.get("stats") or {})
        lines.append(
            f"- {item.get('name')}: trades={stats.get('trades')} total_r={stats.get('total_r')} "
            f"ev={stats.get('ev_r')} win={stats.get('win_rate')} max_dd={stats.get('max_dd_r')} "
            f"delta_total_r={item.get('delta_total_r')} delta_ev={item.get('delta_ev_r')} "
            f"removed={item.get('removed')} years_improved={item.get('years_improved_total')}"
        )
    lines.extend(["", "This is compare-only. It only filters already generated baseline trades."])
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    source_path = Path(args.backtest_path).expanduser()
    if not source_path.is_absolute():
        source_path = ROOT_DIR / source_path
    backtest_payload, rows = _load_rows(source_path)
    generated_at = datetime.now(UTC)
    payload = {
        "schema_version": "micro_main_weighted_filter_backtest_v1",
        "generated_at": generated_at.isoformat(),
        "source_backtest": str(source_path),
        "source_backtest_generated_at": backtest_payload.get("generated_at"),
        "source_backtest_days": backtest_payload.get("days"),
        "model_definition": (
            "Compare-only weighted filter overlay. Each trade receives a 0-1 score from reclaim body, volume, "
            "trend, overshoot, risk, and retest speed. Higher score trades are kept; lower score trades are removed."
        ),
        **_evaluate(rows, min_keep_share=float(args.min_keep_share)),
    }
    if args.write_report:
        report_dir = (
            Path(args.report_dir).expanduser()
            if str(args.report_dir or "").strip()
            else Path(get_settings().validation_report_dir) / "micro_main_weighted_filter_backtests"
        )
        if not report_dir.is_absolute():
            report_dir = ROOT_DIR / report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        stem = f"micro_main_weighted_filter_backtest_{generated_at.strftime('%Y%m%dT%H%M%SZ')}"
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
