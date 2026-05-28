#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text
from scripts import analyze_multi_asset_rotation_walkforward as wf
from scripts import run_hybrid_strategy_mix_search as hybrid
from scripts import run_multi_asset_rotation_search as rot


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only bar-level re-simulation of a causal hybrid strategy walk-forward selector."
    )
    parser.add_argument("--reports", nargs="+", required=True)
    parser.add_argument("--model-id", default="", help="Optional fixed model_id/candidate_id to re-simulate instead of selecting.")
    parser.add_argument("--preselect-top", type=int, default=0, help="Optional train-score candidate cap for scan scripts.")
    parser.add_argument("--symbols", default=hybrid.SYMBOLS_36)
    parser.add_argument("--days", type=int, default=1825)
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--period", choices=("year", "quarter", "month"), default="quarter")
    parser.add_argument("--min-train-periods", type=int, default=8)
    parser.add_argument("--train-window-periods", type=int, default=0)
    parser.add_argument("--selector-mode", choices=("balanced", "calmar", "consistency", "minimax"), default="calmar")
    parser.add_argument("--max-train-worst-year-pct", type=float, default=-100.0)
    parser.add_argument("--max-train-period-dd-pct", type=float, default=100.0)
    parser.add_argument("--min-train-positive-fraction", type=float, default=0.0)
    parser.add_argument("--max-full-sample-dd-pct", type=float, default=45.0)
    parser.add_argument("--cache-dir", default="reports/validation/multi_asset_rotation_search/cache")
    parser.add_argument("--funding-cache-dir", default="reports/validation/multi_asset_rotation_search/funding_cache")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument("--holding-cost-bps-per-day", type=float, default=0.0)
    parser.add_argument("--short-cost-bps-per-day", type=float, default=0.0)
    parser.add_argument("--drawdown-guard-pct", type=float, default=12.0)
    parser.add_argument("--drawdown-risk-scale", type=float, default=0.25)
    parser.add_argument("--drawdown-ladder", default="")
    parser.add_argument("--vol-target-annual-pct", type=float, default=45.0)
    parser.add_argument("--vol-target-mode", choices=("all", "downside"), default="all")
    parser.add_argument("--vol-lookback-hours", type=int, default=720)
    parser.add_argument("--vol-min-scale", type=float, default=0.0)
    parser.add_argument("--vol-max-scale", type=float, default=1.0)
    parser.add_argument("--max-symbol-weight", type=float, default=0.75)
    parser.add_argument("--assumed-capital-usd", type=float, default=100000.0)
    parser.add_argument("--pnl-notional-mode", default="profit95")
    parser.add_argument("--liquidity-notional-mode", default="profit95")
    parser.add_argument("--liquidity-impact-bps-per-1pct-volume", type=float, default=0.25)
    parser.add_argument("--capacity-cap-trade-volume-pct", type=float, default=0.5)
    parser.add_argument("--min-rebalance-turnover", type=float, default=0.0)
    parser.add_argument("--rebalance-fill-fraction", type=float, default=1.0)
    parser.add_argument(
        "--entry-gate-mode",
        choices=("none", "agreement", "external_confirm", "net_weight", "graded_agreement", "graded_external"),
        default="none",
    )
    parser.add_argument("--entry-gate-min-agree", type=int, default=2)
    parser.add_argument("--entry-gate-sleeve-threshold", type=float, default=0.02)
    parser.add_argument("--entry-gate-min-abs-weight", type=float, default=0.10)
    parser.add_argument("--entry-gate-rescale-survivors", action="store_true")
    parser.add_argument("--dispersion-scale-mode", choices=("none", "global", "momentum_sleeves"), default="none")
    parser.add_argument("--dispersion-lookback-hours", type=int, default=168)
    parser.add_argument("--dispersion-threshold-pct", type=float, default=0.0)
    parser.add_argument("--dispersion-risk-scale", type=float, default=1.0)
    parser.add_argument("--dispersion-min-symbols", type=int, default=8)
    parser.add_argument(
        "--market-gate-mode",
        choices=("none", "btc_momentum", "btc_abs_momentum", "btc_momentum_or_abs", "breadth_momentum"),
        default="none",
    )
    parser.add_argument("--market-gate-lookback-hours", type=int, default=720)
    parser.add_argument("--market-gate-threshold-pct", type=float, default=0.0)
    parser.add_argument("--market-gate-abs-threshold-pct", type=float, default=0.0)
    parser.add_argument("--market-gate-min-breadth-pct", type=float, default=50.0)
    parser.add_argument("--market-gate-risk-scale", type=float, default=1.0)
    parser.add_argument("--long-weight-scale", type=float, default=1.0)
    parser.add_argument("--short-weight-scale", type=float, default=1.0)
    parser.add_argument("--report-dir", default="reports/validation/hybrid_walkforward_bar_resim")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _period_field(period: str) -> str:
    return {
        "year": "by_year_return_pct",
        "quarter": "by_quarter_return_pct",
        "month": "by_month_return_pct",
    }[period]


def _period_start(period: str, key: str) -> datetime:
    if period == "year":
        return datetime(int(key), 1, 1, tzinfo=UTC)
    if period == "quarter":
        year, quarter = key.split("Q", 1)
        month = (int(quarter) - 1) * 3 + 1
        return datetime(int(year), month, 1, tzinfo=UTC)
    year, month = key.split("-", 1)
    return datetime(int(year), int(month), 1, tzinfo=UTC)


def _period_end(period: str, key: str) -> datetime:
    start = _period_start(period, key)
    if period == "year":
        return datetime(start.year + 1, 1, 1, tzinfo=UTC)
    if period == "quarter":
        next_month = start.month + 3
        year = start.year + ((next_month - 1) // 12)
        month = ((next_month - 1) % 12) + 1
        return datetime(year, month, 1, tzinfo=UTC)
    next_month = start.month + 1
    year = start.year + ((next_month - 1) // 12)
    month = ((next_month - 1) % 12) + 1
    return datetime(year, month, 1, tzinfo=UTC)


def _candidate_period_returns(candidates: list[dict[str, Any]], period: str) -> dict[str, dict[str, float]]:
    field = _period_field(period)
    out: dict[str, dict[str, float]] = {}
    for row in candidates:
        candidate_id = str(row.get("candidate_id") or "")
        summary = dict(row.get("summary") or {})
        returns = {
            str(key): wf._as_float(value, math.nan)
            for key, value in dict(summary.get(field) or {}).items()
        }
        if candidate_id and returns:
            out[candidate_id] = returns
    return out


def _select_candidate(
    *,
    candidate_returns: dict[str, dict[str, float]],
    train_periods: list[str],
    test_period: str,
    args: argparse.Namespace,
) -> tuple[str | None, float | None]:
    ranked: list[tuple[float, str]] = []
    for candidate_id, returns in candidate_returns.items():
        if test_period not in returns:
            continue
        score = wf._train_score(
            returns,
            train_periods,
            max_train_worst_year_pct=float(args.max_train_worst_year_pct),
            max_train_period_dd_pct=float(args.max_train_period_dd_pct),
            min_train_positive_fraction=float(args.min_train_positive_fraction),
            selector_mode=str(args.selector_mode),
        )
        if math.isfinite(score):
            ranked.append((score, candidate_id))
    if not ranked:
        return None, None
    score, candidate_id = max(ranked, key=lambda item: item[0])
    return candidate_id, score


def _find_candidate(candidates: list[dict[str, Any]], model_id: str) -> dict[str, Any] | None:
    needle = model_id.strip()
    if not needle:
        return None
    for candidate in candidates:
        summary = dict(candidate.get("summary") or {})
        candidate_id = str(candidate.get("candidate_id") or "")
        summary_model_id = str(summary.get("model_id") or "")
        if needle == candidate_id or needle == summary_model_id or needle in candidate_id:
            return candidate
    return None


def _specs_from_candidate(candidate: dict[str, Any], interval: str) -> list[hybrid.SleeveSpec]:
    config = dict(candidate.get("config") or {})
    mix = list(config.get("mix") or [])
    specs: list[hybrid.SleeveSpec] = []
    for sleeve in mix:
        payload = dict(sleeve or {})
        name = str(payload.get("name") or "")
        allocation = float(payload.get("allocation") or 0.0)
        if name and allocation > 0.0:
            specs.append(hybrid._make_spec(name, allocation, interval))
    if not specs:
        model_id = str(dict(candidate.get("summary") or {}).get("model_id") or "")
        if model_id.startswith("hybrid:"):
            for item in model_id.removeprefix("hybrid:").split(","):
                name, _, weight = item.rpartition(":")
                if name:
                    specs.append(hybrid._make_spec(name, float(weight), interval))
    if not specs:
        raise ValueError(f"candidate has no parsable mix: {candidate.get('candidate_id')}")
    return specs


def _max_drawdown(equity_curve: list[float]) -> float:
    peak = equity_curve[0] if equity_curve else 1.0
    max_dd = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        max_dd = max(max_dd, 1.0 - equity / max(peak, 1e-12))
    return max_dd


def _load_market(
    args: argparse.Namespace,
    specs: list[hybrid.SleeveSpec] | None = None,
) -> tuple[rot.MarketFrame, dict[str, Any], rot.FeatureBundle, hybrid.ext.IndicatorCache, dict[str, list[float]]]:
    settings = get_settings()
    base_url = str(args.base_url or settings.binance_rest_base_url or "https://fapi.binance.com").rstrip("/")
    symbols = [symbol.upper() for symbol in rot._csv(args.symbols)]
    bars_by_symbol = {
        symbol: rot._load_bars(
            symbol=symbol,
            interval=args.interval,
            days=max(int(args.days), 30),
            cache_dir=ROOT_DIR / str(args.cache_dir),
            base_url=base_url,
            sleep_seconds=float(args.sleep_seconds),
        )
        for symbol in symbols
    }
    for symbol, bars in bars_by_symbol.items():
        print(json.dumps({"loaded": symbol, "bars": len(bars)}, ensure_ascii=False), flush=True)
    frame, data_status = rot._align_dynamic_frame(args.interval, bars_by_symbol)
    if frame is None:
        raise SystemExit(f"failed to align frame: {data_status}")

    if specs is None:
        mixes = hybrid._vwap_family_candidate_mixes(args.interval)
        specs = [spec for mix in mixes for spec in mix]
    internal_configs = [spec.internal_config for spec in specs if spec.internal_config is not None]
    external_configs = [spec.external_config for spec in specs if spec.external_config is not None]
    features = rot._build_features(frame, [config for config in internal_configs if config is not None])
    indicators = hybrid.ext._build_indicators(frame, [config for config in external_configs if config is not None])

    funding_cache_dir = ROOT_DIR / str(args.funding_cache_dir)
    funding_rates = {
        symbol: rot._load_funding_rates(
            symbol=symbol,
            start_ms=int(frame.open_ms[0]),
            end_ms=int(frame.open_ms[-1]),
            cache_dir=funding_cache_dir,
            base_url=base_url,
            sleep_seconds=float(args.sleep_seconds),
        )
        for symbol in frame.symbols
    }
    funding_period_rates = rot._build_funding_period_rates(frame, funding_rates)
    return frame, data_status, features, indicators, funding_period_rates


def main() -> int:
    args = _parse_args()
    candidates = wf._load_candidates(
        [str(path) for path in args.reports],
        max_full_sample_dd_pct=float(args.max_full_sample_dd_pct),
    )
    candidate_by_id = {str(row["candidate_id"]): row for row in candidates}
    fixed_candidate_id = ""
    if str(args.model_id or "").strip():
        fixed_candidate = _find_candidate(candidates, str(args.model_id))
        if fixed_candidate is None:
            raise SystemExit(f"fixed model not found: {args.model_id}")
        fixed_candidate_id = str(fixed_candidate.get("candidate_id") or "")
    returns_by_candidate = _candidate_period_returns(candidates, str(args.period))
    periods = sorted({period for returns in returns_by_candidate.values() for period in returns})
    if len(periods) <= int(args.min_train_periods):
        raise SystemExit(f"too few periods for walk-forward: {len(periods)}")

    all_specs: list[hybrid.SleeveSpec] = []
    for candidate in candidates:
        try:
            all_specs.extend(_specs_from_candidate(candidate, str(args.interval)))
        except Exception:
            continue
    frame, data_status, features, indicators, funding_period_rates = _load_market(args, all_specs or None)
    equity = 1.0
    equity_curve = [equity]
    selected_period_dd_values: list[float] = []
    folds: list[dict[str, Any]] = []

    for test_idx in range(int(args.min_train_periods), len(periods)):
        test_period = periods[test_idx]
        if int(args.train_window_periods or 0) > 0:
            train_periods = periods[max(0, test_idx - int(args.train_window_periods)):test_idx]
        else:
            train_periods = periods[:test_idx]
        if fixed_candidate_id:
            candidate_id = fixed_candidate_id
            fixed_returns = returns_by_candidate.get(fixed_candidate_id, {})
            train_score = wf._train_score(
                fixed_returns,
                train_periods,
                max_train_worst_year_pct=float(args.max_train_worst_year_pct),
                max_train_period_dd_pct=float(args.max_train_period_dd_pct),
                min_train_positive_fraction=float(args.min_train_positive_fraction),
                selector_mode=str(args.selector_mode),
            )
            if test_period not in fixed_returns:
                candidate_id = None
        else:
            candidate_id, train_score = _select_candidate(
                candidate_returns=returns_by_candidate,
                train_periods=train_periods,
                test_period=test_period,
                args=args,
            )
        if candidate_id is None:
            folds.append({"test_period": test_period, "decision": "NO_ELIGIBLE_MODEL"})
            equity_curve.append(equity)
            continue
        candidate = candidate_by_id[candidate_id]
        specs = _specs_from_candidate(candidate, str(args.interval))
        start = _period_start(str(args.period), test_period)
        end = _period_end(str(args.period), test_period)
        period_args = argparse.Namespace(**vars(args))
        period_args.evaluation_start = start.isoformat()
        period_args.evaluation_end = end.isoformat()
        summary = hybrid._backtest_mix(
            frame,
            features,
            indicators,
            specs,
            args=period_args,
            funding_period_rates=funding_period_rates,
        )
        period_return_pct = wf._as_float(summary.get("total_return_pct"), 0.0)
        period_multiple = max(1.0 + period_return_pct / 100.0, 1e-12)
        equity *= period_multiple
        equity_curve.append(equity)
        period_dd = wf._as_float(summary.get("max_drawdown_pct"), math.nan)
        if math.isfinite(period_dd):
            selected_period_dd_values.append(period_dd)
        folds.append(
            {
                "test_period": test_period,
                "test_start": start.isoformat(),
                "test_end": end.isoformat(),
                "selected_candidate_id": candidate_id,
                "selected_model_id": dict(candidate.get("summary") or {}).get("model_id"),
                "train_periods": train_periods,
                "train_score": round(float(train_score), 8)
                if train_score is not None and math.isfinite(float(train_score))
                else None,
                "bar_resim_return_pct": round(period_return_pct, 4),
                "bar_resim_max_drawdown_pct": round(period_dd, 4) if math.isfinite(period_dd) else None,
                "bar_resim_periods": summary.get("periods"),
                "rebalance_count": summary.get("rebalance_count"),
            }
        )

    completed = [fold for fold in folds if fold.get("selected_candidate_id")]
    periods_per_year = {"year": 1.0, "quarter": 4.0, "month": 12.0}[str(args.period)]
    years_tested = len(completed) / periods_per_year if completed else 0.0
    total_return = equity - 1.0
    annualized = equity ** (1.0 / max(years_tested, 1e-9)) - 1.0 if equity > 0.0 else -1.0
    step_dd = _max_drawdown(equity_curve)
    aggregate = {
        "period": str(args.period),
        "selector_mode": str(args.selector_mode),
        "test_period_count": len(completed),
        "years_tested": round(years_tested, 4),
        "ending_equity_multiple": round(equity, 6),
        "total_return_pct": round(total_return * 100.0, 4),
        "annualized_return_pct": round(annualized * 100.0, 4),
        "max_drawdown_on_period_steps_pct": round(step_dd * 100.0, 4),
        "max_selected_period_drawdown_pct": round(max(selected_period_dd_values), 4)
        if selected_period_dd_values
        else None,
        "positive_period_fraction": round(
            sum(1 for fold in completed if wf._as_float(fold.get("bar_resim_return_pct")) > 0.0)
            / max(len(completed), 1),
            4,
        ),
    }
    output = {
        "schema_version": "hybrid_walkforward_bar_resim_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "authority": "research_only_no_live_authority_change",
        "input_reports": [str(path) for path in args.reports],
        "candidate_count": len(candidates),
        "data_status": data_status,
        "method": {
            "selector": (
                f"fixed model_id: {args.model_id}"
                if fixed_candidate_id
                else "causal prior-period selector; each selected test fold is re-run on 4h bars"
            ),
            "limitations": [
                "folds are re-simulated flat-to-flat, so boundary turnover is conservative but state carry is reset",
                "does not place orders and has no live authority",
            ],
        },
        "cost_model": {
            key: getattr(args, key)
            for key in (
                "fee_bps_per_side",
                "slippage_bps_per_side",
                "holding_cost_bps_per_day",
                "short_cost_bps_per_day",
                "drawdown_guard_pct",
                "drawdown_risk_scale",
                "drawdown_ladder",
                "vol_target_annual_pct",
                "vol_target_mode",
                "vol_lookback_hours",
                "vol_min_scale",
                "vol_max_scale",
                "max_symbol_weight",
                "min_rebalance_turnover",
                "rebalance_fill_fraction",
                "market_gate_mode",
                "market_gate_risk_scale",
            )
        },
        "aggregate": aggregate,
        "folds": folds,
    }
    if bool(args.write_report):
        report_dir = ROOT_DIR / str(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out_path = report_dir / f"hybrid_walkforward_bar_resim_{stamp}.json"
        latest_path = report_dir / "latest.json"
        output["report_path"] = str(out_path.relative_to(ROOT_DIR))
        output["latest_report_path"] = str(latest_path.relative_to(ROOT_DIR))
        text = json.dumps(output, ensure_ascii=False, indent=2, default=str)
        atomic_write_text(out_path, text)
        atomic_write_text(latest_path, text)
    print(json.dumps({"aggregate": aggregate, "report_dir": str(args.report_dir)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
