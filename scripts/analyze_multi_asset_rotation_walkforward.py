#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.report_io import atomic_write_text


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate multi-asset rotation reports and run a year-by-year walk-forward selector."
    )
    parser.add_argument("--reports", nargs="+", required=True)
    parser.add_argument("--period", choices=("year", "quarter", "month"), default="year")
    parser.add_argument("--min-train-years", type=int, default=2)
    parser.add_argument("--min-train-periods", type=int, default=0)
    parser.add_argument("--train-window-periods", type=int, default=0)
    parser.add_argument(
        "--selector-mode",
        choices=("balanced", "calmar", "consistency", "minimax"),
        default="balanced",
    )
    parser.add_argument("--max-train-worst-year-pct", type=float, default=0.0)
    parser.add_argument("--max-train-period-dd-pct", type=float, default=100.0)
    parser.add_argument("--min-train-positive-fraction", type=float, default=0.0)
    parser.add_argument("--max-full-sample-dd-pct", type=float, default=100.0)
    parser.add_argument("--report-dir", default="reports/validation/multi_asset_rotation_walkforward")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _summary_score(summary: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        _as_float(summary.get("score")),
        _as_float(summary.get("calmar")),
        _as_float(summary.get("cagr_pct")),
        _as_float(summary.get("total_return_pct")),
    )


def _candidate_identity(
    *,
    model_id: str,
    config: dict[str, Any],
    summary: dict[str, Any],
    report: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    cost_model = dict(report.get("cost_model") or {})
    scope = dict(report.get("scope") or {})
    identity = {
        "model_id": model_id,
        "config": {
            key: config.get(key)
            for key in (
                "interval",
                "mode",
                "lookback_hours",
                "top_k",
                "rebalance_hours",
                "trend_hours",
                "vol_weight",
                "min_symbol_age_hours",
                "gross_leverage",
            )
        },
        "cost_model": {
            key: cost_model.get(key)
            for key in (
                "fee_bps_per_side",
                "slippage_bps_per_side",
                "holding_cost_bps_per_day",
                "short_cost_bps_per_day",
                "drawdown_guard_pct",
                "drawdown_risk_scale",
                "vol_target_annual_pct",
                "vol_lookback_hours",
                "vol_min_scale",
                "vol_max_scale",
                "dispersion_lookback_rebalances",
                "dispersion_guard_quantile",
                "dispersion_risk_scale",
                "symbol_quality_lookback_hours",
                "symbol_quality_drop_count",
                "symbol_quality_min_active_periods",
                "symbol_quality_min_abs_exposure",
                "symbol_quality_score_threshold",
                "apply_funding",
                "maintenance_margin_pct",
                "assumed_capital_usd",
                "pnl_notional_mode",
                "liquidity_notional_mode",
                "liquidity_impact_bps_per_1pct_volume",
                "max_symbol_weight",
                "max_trade_volume_pct",
                "capacity_cap_trade_volume_pct",
                "apply_exchange_rules",
            )
        },
        "symbols": sorted(str(symbol) for symbol in scope.get("symbols") or []),
        "align_mode": scope.get("align_mode"),
        "risk_overlay": summary.get("risk_overlay"),
    }
    digest = hashlib.sha1(
        json.dumps(identity, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:12]
    return f"{model_id}|{digest}", identity


def _load_candidates(report_paths: list[str], *, max_full_sample_dd_pct: float) -> list[dict[str, Any]]:
    by_model: dict[str, dict[str, Any]] = {}
    source_paths: dict[str, list[str]] = defaultdict(list)
    for raw_path in report_paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = ROOT_DIR / path
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        rows = list(data.get("all_results") or [])
        if not rows:
            rows = list(data.get("top_by_score") or []) + list(data.get("top_by_return") or [])
        for row in rows:
            config = dict(row.get("config") or {})
            summary = dict(row.get("summary") or {})
            if _as_float(summary.get("max_drawdown_pct"), 100.0) > max_full_sample_dd_pct:
                continue
            model_id = str(summary.get("model_id") or config.get("model_id") or "")
            if not model_id:
                continue
            candidate_id, identity = _candidate_identity(
                model_id=model_id,
                config=config,
                summary=summary,
                report=data,
            )
            current = by_model.get(candidate_id)
            candidate = {"config": config, "summary": summary}
            candidate["candidate_id"] = candidate_id
            candidate["identity"] = identity
            if current is None or _summary_score(summary) > _summary_score(dict(current.get("summary") or {})):
                by_model[candidate_id] = candidate
            source_paths[candidate_id].append(str(path.relative_to(ROOT_DIR)))

    out: list[dict[str, Any]] = []
    for candidate_id, row in by_model.items():
        row["source_reports"] = sorted(set(source_paths.get(candidate_id, [])))
        out.append(row)
    return out


def _train_score(
    yearly_returns_pct: dict[str, float],
    train_years: list[str],
    *,
    max_train_worst_year_pct: float,
    max_train_period_dd_pct: float,
    min_train_positive_fraction: float,
    selector_mode: str,
) -> float:
    values = [yearly_returns_pct[year] / 100.0 for year in train_years if year in yearly_returns_pct]
    if len(values) != len(train_years):
        return -math.inf
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    logs: list[float] = []
    for value in values:
        if value <= -0.999:
            return -math.inf
        equity *= 1.0 + value
        peak = max(peak, equity)
        max_dd = max(max_dd, 1.0 - equity / max(peak, 1e-12))
        logs.append(math.log1p(value))
    worst_pct = min(values) * 100.0
    if worst_pct < max_train_worst_year_pct:
        return -math.inf
    if max_dd * 100.0 > max_train_period_dd_pct:
        return -math.inf
    mean_log = sum(logs) / len(logs)
    if len(logs) >= 2:
        variance = sum((value - mean_log) * (value - mean_log) for value in logs) / len(logs)
        volatility_penalty = math.sqrt(max(variance, 0.0))
    else:
        volatility_penalty = 0.0
    positive_fraction = sum(1 for value in values if value > 0.0) / len(values)
    if positive_fraction < min_train_positive_fraction:
        return -math.inf
    drawdown_penalty = max(0.0, -worst_pct) / 100.0
    total_log = math.log(max(equity, 1e-12))
    downside_logs = [min(value, 0.0) for value in logs]
    downside_penalty = math.sqrt(sum(value * value for value in downside_logs) / len(downside_logs))
    mode = str(selector_mode or "balanced")
    if mode == "calmar":
        return (mean_log / max(max_dd, 0.03)) + 0.20 * positive_fraction - 0.35 * downside_penalty
    if mode == "consistency":
        return mean_log + 0.35 * positive_fraction - 0.75 * volatility_penalty - 0.90 * downside_penalty - 0.50 * max_dd
    if mode == "minimax":
        return worst_pct / 100.0 + 0.35 * mean_log + 0.20 * positive_fraction - 0.20 * max_dd
    return total_log * max(positive_fraction, 0.25) - 0.50 * volatility_penalty - drawdown_penalty


def _max_drawdown(equity_curve: list[float]) -> float:
    peak = equity_curve[0] if equity_curve else 1.0
    max_dd = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        max_dd = max(max_dd, 1.0 - equity / max(peak, 1e-12))
    return max_dd


def _walk_forward(
    candidates: list[dict[str, Any]],
    *,
    period: str,
    min_train_periods: int,
    train_window_periods: int,
    max_train_worst_year_pct: float,
    max_train_period_dd_pct: float,
    min_train_positive_fraction: float,
    selector_mode: str,
) -> dict[str, Any]:
    period_field = {
        "year": "by_year_return_pct",
        "quarter": "by_quarter_return_pct",
        "month": "by_month_return_pct",
    }[period]
    period_dd_field = {
        "year": "by_year_max_drawdown_pct",
        "quarter": "by_quarter_max_drawdown_pct",
        "month": "by_month_max_drawdown_pct",
    }[period]
    years = sorted(
        {
            str(year)
            for row in candidates
            for year in dict(dict(row.get("summary") or {}).get(period_field) or {})
        }
    )
    if len(years) <= min_train_periods:
        return {"error": "too_few_years", "years": years}

    candidate_returns: dict[str, dict[str, float]] = {}
    candidate_lookup: dict[str, dict[str, Any]] = {}
    for row in candidates:
        summary = dict(row.get("summary") or {})
        model_id = str(summary.get("model_id") or dict(row.get("config") or {}).get("model_id") or "")
        candidate_id = str(row.get("candidate_id") or model_id)
        yearly = {
            str(year): _as_float(value, math.nan)
            for year, value in dict(summary.get(period_field) or {}).items()
        }
        if model_id and yearly:
            candidate_returns[candidate_id] = yearly
            candidate_lookup[candidate_id] = row

    equity = 1.0
    equity_curve = [equity]
    selections: list[dict[str, Any]] = []
    selected_period_dd_values: list[float] = []
    for test_idx in range(min_train_periods, len(years)):
        if train_window_periods > 0:
            train_years = years[max(0, test_idx - train_window_periods):test_idx]
        else:
            train_years = years[:test_idx]
        test_year = years[test_idx]
        ranked: list[tuple[float, str]] = []
        for candidate_id, yearly in candidate_returns.items():
            if test_year not in yearly:
                continue
            score = _train_score(
                yearly,
                train_years,
                max_train_worst_year_pct=max_train_worst_year_pct,
                max_train_period_dd_pct=max_train_period_dd_pct,
                min_train_positive_fraction=min_train_positive_fraction,
                selector_mode=selector_mode,
            )
            if math.isfinite(score):
                ranked.append((score, candidate_id))
        if not ranked:
            selections.append({"test_year": test_year, "decision": "NO_ELIGIBLE_MODEL"})
            equity_curve.append(equity)
            continue
        _, candidate_id = max(ranked, key=lambda item: item[0])
        yearly = candidate_returns[candidate_id]
        test_return_pct = yearly[test_year]
        equity *= 1.0 + test_return_pct / 100.0
        equity_curve.append(equity)
        row = candidate_lookup[candidate_id]
        summary = dict(row.get("summary") or {})
        selected_period_dd_pct = _as_float(
            dict(summary.get(period_dd_field) or {}).get(test_year),
            math.nan,
        )
        if math.isfinite(selected_period_dd_pct):
            selected_period_dd_values.append(selected_period_dd_pct)
        model_id = str(summary.get("model_id") or dict(row.get("config") or {}).get("model_id") or "")
        selections.append(
            {
                "test_year": test_year,
                "selected_candidate_id": candidate_id,
                "selected_model_id": model_id,
                "mode": dict(row.get("config") or {}).get("mode"),
                "train_years": train_years,
                "selector_mode": selector_mode,
                "train_score": round(max(ranked, key=lambda item: item[0])[0], 8),
                "test_return_pct": round(test_return_pct, 4),
                "selected_period_max_drawdown_pct": round(selected_period_dd_pct, 4)
                if math.isfinite(selected_period_dd_pct)
                else None,
                "full_sample_total_return_pct": summary.get("total_return_pct"),
                "full_sample_max_drawdown_pct": summary.get("max_drawdown_pct"),
                "source_reports": row.get("source_reports", []),
            }
        )

    completed = [row for row in selections if row.get("selected_model_id")]
    test_year_count = len(completed)
    total_return = equity - 1.0
    periods_per_year = {"year": 1.0, "quarter": 4.0, "month": 12.0}[period]
    years_tested = max(test_year_count / periods_per_year, 1e-9)
    cagr = equity ** (1.0 / years_tested) - 1.0 if equity > 0.0 else -1.0
    positive_year_fraction = (
        sum(1 for row in completed if _as_float(row.get("test_return_pct")) > 0.0)
        / max(test_year_count, 1)
    )
    max_dd = _max_drawdown(equity_curve)
    return {
        "period": period,
        "periods": years,
        "test_period_count": test_year_count,
        "test_year_count": test_year_count,
        "years_tested": round(years_tested, 4),
        "total_return_pct": round(total_return * 100.0, 4),
        "annualized_return_pct": round(cagr * 100.0, 4),
        "max_drawdown_on_period_steps_pct": round(max_dd * 100.0, 4),
        "max_drawdown_on_annual_steps_pct": round(max_dd * 100.0, 4),
        "max_selected_period_drawdown_pct": round(max(selected_period_dd_values), 4)
        if selected_period_dd_values
        else None,
        "positive_year_fraction": round(positive_year_fraction, 4),
        "ending_equity_multiple": round(equity, 6),
        "selections": selections,
    }


def main() -> int:
    args = _parse_args()
    generated_at = datetime.now(UTC)
    min_train_periods = int(args.min_train_periods or 0)
    if min_train_periods <= 0:
        min_train_periods = max(int(args.min_train_years), 1) * {
            "year": 1,
            "quarter": 4,
            "month": 12,
        }[str(args.period)]
    candidates = _load_candidates(
        [str(path) for path in args.reports],
        max_full_sample_dd_pct=float(args.max_full_sample_dd_pct),
    )
    output = {
        "schema_version": "multi_asset_rotation_walkforward_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "research_only_no_live_authority_change",
        "input_reports": [str(path) for path in args.reports],
        "candidate_count": len(candidates),
        "method": {
            "selector": "yearly causal train-score selector using only prior yearly returns",
            "selector_period": str(args.period),
            "selector_mode": str(args.selector_mode),
            "min_train_periods": int(min_train_periods),
            "train_window_periods": int(args.train_window_periods or 0),
            "max_train_worst_year_pct": float(args.max_train_worst_year_pct),
            "max_train_period_dd_pct": float(args.max_train_period_dd_pct),
            "min_train_positive_fraction": float(args.min_train_positive_fraction),
            "max_full_sample_dd_pct": float(args.max_full_sample_dd_pct),
            "limitations": [
                "uses yearly return fields from prior backtest reports",
                "does not resimulate intra-year model switches or order state across model changes",
                "annual-step drawdown understates intrayear drawdown",
            ],
        },
        "walk_forward": _walk_forward(
            candidates,
            period=str(args.period),
            min_train_periods=max(min_train_periods, 1),
            train_window_periods=max(int(args.train_window_periods or 0), 0),
            max_train_worst_year_pct=float(args.max_train_worst_year_pct),
            max_train_period_dd_pct=float(args.max_train_period_dd_pct),
            min_train_positive_fraction=float(args.min_train_positive_fraction),
            selector_mode=str(args.selector_mode),
        ),
        "top_full_sample_candidates": sorted(
            candidates,
            key=lambda row: _summary_score(dict(row.get("summary") or {})),
            reverse=True,
        )[:20],
    }
    if args.write_report:
        report_dir = ROOT_DIR / str(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        out_path = report_dir / f"multi_asset_rotation_walkforward_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        latest_path = report_dir / "latest.json"
        output["report_path"] = str(out_path.relative_to(ROOT_DIR))
        output["latest_report_path"] = str(latest_path.relative_to(ROOT_DIR))
        atomic_write_text(out_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(latest_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))

    printed = {key: value for key, value in output.items() if key != "top_full_sample_candidates"}
    print(json.dumps(printed, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
