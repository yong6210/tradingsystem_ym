#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text
from scripts.run_btc_flip_rotation_search import _INTERVAL_MS, _csv, _load_bars, Bar, FeatureSet
from scripts.run_scenario_repair_rotation_backtest import _map_closed_indices
from scripts.run_market_state_rotation_v6_backtest import (
    MarketStateConfig,
    _carry_rate_per_bar,
    _counter_payload,
    _stdout_result_summary,
    backtest_config,
)


DEFAULT_SOURCE_REPORT = (
    "reports/validation/market_state_rotation_v6_backtest/"
    "market_state_rotation_v6_BTCUSDT_5m_365d_latest.json"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Walk-forward validation for market-state rotation v6. "
            "Each fold selects a candidate on the train window and evaluates it on the next unseen window."
        )
    )
    parser.add_argument("--source-report", default=DEFAULT_SOURCE_REPORT)
    parser.add_argument("--report-dir", default="reports/validation/market_state_rotation_v6_backtest")
    parser.add_argument("--symbol", default="")
    parser.add_argument("--exec-interval", default="")
    parser.add_argument("--scenario-intervals", default="")
    parser.add_argument("--load-days", type=int, default=1825)
    parser.add_argument("--train-days", type=int, default=365)
    parser.add_argument("--test-days", type=int, default=90)
    parser.add_argument("--step-days", type=int, default=90)
    parser.add_argument("--top-n", type=int, default=8)
    parser.add_argument("--fold-limit", type=int, default=0)
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument("--funding-bps-per-8h", type=float, default=0.0)
    parser.add_argument("--borrow-bps-per-day", type=float, default=0.0)
    parser.add_argument("--min-periods", type=int, default=5000)
    parser.add_argument("--cache-dir", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _material_config_key(config: MarketStateConfig) -> str:
    payload = {
        key: value
        for key, value in asdict(config).items()
        if key not in {"model_id", "max_battle_bars"}
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _configs_from_source(report: dict[str, Any], *, top_n: int) -> list[MarketStateConfig]:
    candidates: list[dict[str, Any]] = []
    for key in ("best_by_method_score", "best_by_raw_return"):
        result = report.get(key)
        if isinstance(result, dict) and isinstance(result.get("config"), dict):
            candidates.append(result)
    for section in ("top_results", "top_results_by_return", "all_results"):
        for result in report.get(section) or []:
            if isinstance(result, dict) and isinstance(result.get("config"), dict):
                candidates.append(result)

    configs: list[MarketStateConfig] = []
    seen: set[str] = set()
    for result in candidates:
        try:
            config = MarketStateConfig(**result["config"])
        except TypeError:
            continue
        key = _material_config_key(config)
        if key in seen:
            continue
        seen.add(key)
        configs.append(config)
        if len(configs) >= max(1, int(top_n)):
            break
    return configs


def _slice_between(bars: list[Bar], start: datetime, end: datetime) -> list[Bar]:
    return [bar for bar in bars if start <= bar.ts < end]


def _window_feature_sets(
    *,
    exec_bars_all: list[Bar],
    scenario_bars_all: dict[str, list[Bar]],
    start: datetime,
    end: datetime,
    scenario_intervals: list[str],
) -> tuple[FeatureSet, dict[str, FeatureSet], dict[str, list[int]], dict[str, Any]]:
    exec_bars = _slice_between(exec_bars_all, start, end)
    features = FeatureSet(exec_bars)
    scenario_features: dict[str, FeatureSet] = {}
    scenario_maps: dict[str, list[int]] = {}
    for interval in scenario_intervals:
        scenario_start = start - timedelta(milliseconds=_INTERVAL_MS[interval] * 300)
        scenario_bars = _slice_between(scenario_bars_all[interval], scenario_start, end)
        scenario_features[interval] = FeatureSet(scenario_bars)
        scenario_maps[interval] = _map_closed_indices(exec_bars, scenario_bars, interval)
    meta = {
        "exec_rows": len(exec_bars),
        "exec_start": exec_bars[0].ts.isoformat() if exec_bars else None,
        "exec_end": exec_bars[-1].ts.isoformat() if exec_bars else None,
        "scenario_rows": {interval: len(fs.bars) for interval, fs in scenario_features.items()},
    }
    return features, scenario_features, scenario_maps, meta


def _selection_score(result: dict[str, Any]) -> float:
    diagnostics = dict(result.get("event_diagnostics") or {})
    flags = diagnostics.get("flags") or []
    mdd = float(result.get("max_drawdown_pct") or 100.0)
    cost_drag = float(result.get("estimated_cost_drag_pct") or 0.0)
    return (
        float(result.get("score") or -1e9)
        - 0.10 * len(flags)
        - 0.005 * max(mdd - 35.0, 0.0)
        - 0.0005 * max(cost_drag - 250.0, 0.0)
    )


def _run_config(
    *,
    symbol: str,
    features: FeatureSet,
    scenario_features: dict[str, FeatureSet],
    scenario_maps: dict[str, list[int]],
    config: MarketStateConfig,
    cost_rate: float,
    carry_rate_per_bar: float,
    min_periods: int,
) -> dict[str, Any] | None:
    return backtest_config(
        symbol=symbol,
        features=features,
        scenario_features=scenario_features,
        scenario_maps=scenario_maps,
        config=config,
        cost_rate=cost_rate,
        min_periods=min_periods,
        carry_rate_per_bar=carry_rate_per_bar,
    )


def _aggregate_folds(folds: list[dict[str, Any]]) -> dict[str, Any]:
    tests = [fold["test_result"] for fold in folds if fold.get("test_result")]
    if not tests:
        return {}
    equity = 1.0
    returns: list[float] = []
    cost_drags: list[float] = []
    carry_costs: list[float] = []
    max_mdd = 0.0
    selected_counter: Counter[str] = Counter()
    selected_profile_counter: Counter[str] = Counter()
    selected_hold_counter: Counter[str] = Counter()
    selected_max_units_counter: Counter[str] = Counter()
    test_health_counter: Counter[str] = Counter()
    flag_counter: Counter[str] = Counter()
    regime_totals: dict[str, dict[str, Any]] = {}
    for fold in folds:
        result = fold.get("test_result")
        if not result:
            continue
        equity *= float(result.get("final_equity") or 1.0)
        returns.append(float(result.get("total_return_pct") or 0.0))
        cost_drags.append(float(result.get("estimated_cost_drag_pct") or 0.0))
        carry_costs.append(float(result.get("modeled_carry_cost_fraction_sum") or 0.0))
        max_mdd = max(max_mdd, float(result.get("max_drawdown_pct") or 0.0))
        selected_counter[str(fold.get("selected_model_id") or "unknown")] += 1
        selected_config = dict(dict(fold.get("selected_train_result") or {}).get("config") or {})
        model_id = str(selected_config.get("model_id") or fold.get("selected_model_id") or "unknown")
        parts = model_id.split(":")
        selected_profile_counter[parts[2] if len(parts) > 2 else "unknown"] += 1
        selected_hold_counter[str(selected_config.get("max_hold_bars", "unknown"))] += 1
        selected_max_units_counter[str(selected_config.get("max_possible_units", "unknown"))] += 1
        diagnostics = dict(result.get("event_diagnostics") or {})
        test_health_counter[str(diagnostics.get("health") or "unknown")] += 1
        for flag in diagnostics.get("flags") or []:
            flag_counter[str(flag)] += 1
        for regime, stats in dict(result.get("regime_performance") or {}).items():
            regime_stats = dict(stats or {})
            total = regime_totals.setdefault(
                str(regime),
                {
                    "fold_count": 0,
                    "equity": 1.0,
                    "bars": 0,
                    "exposed_bars": 0,
                    "max_drawdown_pct": 0.0,
                    "abs_exposure_weighted_sum": 0.0,
                    "add_events": 0,
                    "remove_events": 0,
                },
            )
            regime_return = float(regime_stats.get("return_pct") or 0.0) / 100.0
            total["fold_count"] += 1
            total["equity"] *= max(1.0 + regime_return, 1e-12)
            bars = int(regime_stats.get("bars") or 0)
            total["bars"] += bars
            total["exposed_bars"] += int(regime_stats.get("exposed_bars") or 0)
            total["max_drawdown_pct"] = max(
                float(total["max_drawdown_pct"]),
                float(regime_stats.get("max_drawdown_pct") or 0.0),
            )
            total["abs_exposure_weighted_sum"] += float(regime_stats.get("avg_abs_account_exposure") or 0.0) * bars
            total["add_events"] += int(regime_stats.get("add_events") or 0)
            total["remove_events"] += int(regime_stats.get("remove_events") or 0)
    regime_performance = {
        regime: {
            "fold_count": int(stats["fold_count"]),
            "compounded_return_pct": round((float(stats["equity"]) - 1.0) * 100.0, 4),
            "bars": int(stats["bars"]),
            "exposed_bars": int(stats["exposed_bars"]),
            "max_drawdown_pct": round(float(stats["max_drawdown_pct"]), 4),
            "avg_abs_account_exposure": round(
                float(stats["abs_exposure_weighted_sum"]) / max(int(stats["bars"]), 1),
                4,
            ),
            "add_events": int(stats["add_events"]),
            "remove_events": int(stats["remove_events"]),
        }
        for regime, stats in sorted(regime_totals.items())
    }
    return {
        "fold_count": len(tests),
        "compounded_oos_return_pct": round((equity - 1.0) * 100.0, 4),
        "avg_oos_return_pct": round(mean(returns), 4),
        "min_oos_return_pct": round(min(returns), 4),
        "max_oos_return_pct": round(max(returns), 4),
        "positive_fold_count": sum(1 for value in returns if value > 0.0),
        "max_fold_drawdown_pct": round(max_mdd, 4),
        "avg_oos_cost_drag_pct": round(mean(cost_drags), 4) if cost_drags else 0.0,
        "max_oos_cost_drag_pct": round(max(cost_drags), 4) if cost_drags else 0.0,
        "avg_modeled_carry_cost_fraction_sum": round(mean(carry_costs), 8) if carry_costs else 0.0,
        "selected_model_counts": _counter_payload(selected_counter),
        "selected_profile_counts": _counter_payload(selected_profile_counter),
        "selected_hold_counts": _counter_payload(selected_hold_counter),
        "selected_max_units_counts": _counter_payload(selected_max_units_counter),
        "test_health_counts": _counter_payload(test_health_counter),
        "test_flag_counts": _counter_payload(flag_counter),
        "test_regime_performance": regime_performance,
    }


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    aggregate = dict(report.get("aggregate") or {})
    lines = [
        "# Market-State Rotation V6 Walk-Forward Validation",
        "",
        f"- Created at: `{report.get('created_at')}`",
        f"- Source report: `{report.get('source_report')}`",
        f"- Symbol: `{report.get('symbol')}`",
        f"- Execution interval: `{report.get('exec_interval')}`",
        f"- Train/test/step days: `{report.get('train_days')}/{report.get('test_days')}/{report.get('step_days')}`",
        f"- Candidate count: `{report.get('candidate_count')}`",
        f"- Fold count: `{aggregate.get('fold_count')}`",
        f"- OOS compounded return: `{aggregate.get('compounded_oos_return_pct')}%`",
        f"- OOS average fold return: `{aggregate.get('avg_oos_return_pct')}%`",
        f"- OOS min/max fold return: `{aggregate.get('min_oos_return_pct')}% / {aggregate.get('max_oos_return_pct')}%`",
        f"- OOS max fold drawdown: `{aggregate.get('max_fold_drawdown_pct')}%`",
        f"- Positive folds: `{aggregate.get('positive_fold_count')}/{aggregate.get('fold_count')}`",
        f"- OOS avg/max cost drag: `{aggregate.get('avg_oos_cost_drag_pct')}% / {aggregate.get('max_oos_cost_drag_pct')}%`",
        f"- OOS avg carry cost fraction sum: `{aggregate.get('avg_modeled_carry_cost_fraction_sum')}`",
        f"- Selected model counts: `{json.dumps(aggregate.get('selected_model_counts', {}), ensure_ascii=False)}`",
        f"- Selected profile counts: `{json.dumps(aggregate.get('selected_profile_counts', {}), ensure_ascii=False)}`",
        f"- Selected hold counts: `{json.dumps(aggregate.get('selected_hold_counts', {}), ensure_ascii=False)}`",
        f"- Selected max-unit counts: `{json.dumps(aggregate.get('selected_max_units_counts', {}), ensure_ascii=False)}`",
        f"- Test health counts: `{json.dumps(aggregate.get('test_health_counts', {}), ensure_ascii=False)}`",
        f"- Test flag counts: `{json.dumps(aggregate.get('test_flag_counts', {}), ensure_ascii=False)}`",
        "",
        "## OOS Regime Performance",
        "",
        f"`{json.dumps(aggregate.get('test_regime_performance', {}), ensure_ascii=False)}`",
        "",
        "## Selection Policy",
        "",
        "The adaptive profile selects from the current top candidates using the previous 365 days, then trades the next 90 days unseen. This is the preferred deployment validation view because it avoids choosing one static model from the same period being evaluated.",
        "",
        "## Folds",
        "",
        "| fold | train | test | selected train return % | selected test return % | test MDD % | flags | selected model |",
        "|---:|---|---|---:|---:|---:|---|---|",
    ]
    for fold in report.get("folds") or []:
        train = dict(fold.get("selected_train_result") or {})
        test = dict(fold.get("test_result") or {})
        diag = dict(test.get("event_diagnostics") or {})
        lines.append(
            f"| {fold.get('fold')} | {fold.get('train_start')} to {fold.get('train_end')} | "
            f"{fold.get('test_start')} to {fold.get('test_end')} | "
            f"{train.get('total_return_pct')} | {test.get('total_return_pct')} | "
            f"{test.get('max_drawdown_pct')} | {', '.join(diag.get('flags') or []) or 'none'} | "
            f"`{fold.get('selected_model_id')}` |"
        )
    lines.append("")
    atomic_write_text(path, "\n".join(lines))


def main() -> None:
    args = _parse_args()
    source_path = Path(args.source_report)
    source_report = json.loads(source_path.read_text())
    source_args = dict(source_report.get("args") or {})
    symbol = args.symbol or str(source_args.get("symbol") or "BTCUSDT")
    exec_interval = args.exec_interval or str(source_args.get("exec_interval") or "5m")
    scenario_intervals = _csv(args.scenario_intervals or str(source_args.get("scenario_intervals") or "1h,4h"))
    if exec_interval not in _INTERVAL_MS:
        raise SystemExit(f"unsupported exec interval: {exec_interval}")
    for interval in scenario_intervals:
        if interval not in _INTERVAL_MS:
            raise SystemExit(f"unsupported scenario interval: {interval}")

    configs = _configs_from_source(source_report, top_n=max(1, int(args.top_n)))
    if not configs:
        raise SystemExit(f"no candidate configs found in {source_path}")

    settings = get_settings()
    base_url = str(args.base_url or source_args.get("base_url") or settings.binance_rest_base_url or "https://fapi.binance.com").rstrip("/")
    cache_dir = Path(args.cache_dir or source_args.get("cache_dir") or "reports/validation/btc_flip_rotation_search/cache")
    exec_bars_all = _load_bars(
        symbol=symbol,
        interval=exec_interval,
        days=max(int(args.load_days), int(args.train_days) + int(args.test_days) + 5),
        cache_dir=cache_dir,
        base_url=base_url,
        sleep_seconds=float(args.sleep_seconds),
    )
    scenario_bars_all = {
        interval: _load_bars(
            symbol=symbol,
            interval=interval,
            days=max(int(args.load_days), int(args.train_days) + int(args.test_days) + 5),
            cache_dir=cache_dir,
            base_url=base_url,
            sleep_seconds=float(args.sleep_seconds),
        )
        for interval in scenario_intervals
    }

    if not exec_bars_all:
        raise SystemExit("no execution bars loaded")
    cost_rate = (max(float(args.fee_bps_per_side), 0.0) + max(float(args.slippage_bps_per_side), 0.0)) / 10_000.0
    carry_rate_per_bar = _carry_rate_per_bar(
        exec_interval=exec_interval,
        funding_bps_per_8h=float(args.funding_bps_per_8h),
        borrow_bps_per_day=float(args.borrow_bps_per_day),
    )

    fold_start = exec_bars_all[0].ts.astimezone(UTC)
    last_ts = exec_bars_all[-1].ts.astimezone(UTC)
    train_delta = timedelta(days=max(int(args.train_days), 1))
    test_delta = timedelta(days=max(int(args.test_days), 1))
    step_delta = timedelta(days=max(int(args.step_days), 1))
    folds: list[dict[str, Any]] = []
    fold_idx = 0
    while fold_start + train_delta + test_delta <= last_ts:
        fold_idx += 1
        train_start = fold_start
        train_end = train_start + train_delta
        test_start = train_end
        test_end = test_start + test_delta
        train_features, train_scenario_features, train_maps, train_meta = _window_feature_sets(
            exec_bars_all=exec_bars_all,
            scenario_bars_all=scenario_bars_all,
            start=train_start,
            end=train_end,
            scenario_intervals=scenario_intervals,
        )
        test_features, test_scenario_features, test_maps, test_meta = _window_feature_sets(
            exec_bars_all=exec_bars_all,
            scenario_bars_all=scenario_bars_all,
            start=test_start,
            end=test_end,
            scenario_intervals=scenario_intervals,
        )
        if len(train_features.bars) < int(args.min_periods) or len(test_features.bars) < int(args.min_periods):
            fold_start += step_delta
            continue

        train_results: list[dict[str, Any]] = []
        for config in configs:
            result = _run_config(
                symbol=symbol,
                features=train_features,
                scenario_features=train_scenario_features,
                scenario_maps=train_maps,
                config=config,
                cost_rate=cost_rate,
                carry_rate_per_bar=carry_rate_per_bar,
                min_periods=int(args.min_periods),
            )
            if result:
                result["walk_forward_selection_score"] = round(_selection_score(result), 6)
                train_results.append(result)
        if not train_results:
            fold_start += step_delta
            continue
        train_results.sort(
            key=lambda item: (
                float(item.get("walk_forward_selection_score") or -1e9),
                float(item.get("cagr_pct") or -1e9),
                -float(item.get("max_drawdown_pct") or math.inf),
            ),
            reverse=True,
        )
        selected_train = train_results[0]
        selected_config = MarketStateConfig(**selected_train["config"])
        test_result = _run_config(
            symbol=symbol,
            features=test_features,
            scenario_features=test_scenario_features,
            scenario_maps=test_maps,
            config=selected_config,
            cost_rate=cost_rate,
            carry_rate_per_bar=carry_rate_per_bar,
            min_periods=int(args.min_periods),
        )
        folds.append(
            {
                "fold": len(folds) + 1,
                "train_start": train_start.date().isoformat(),
                "train_end": train_end.date().isoformat(),
                "test_start": test_start.date().isoformat(),
                "test_end": test_end.date().isoformat(),
                "train_meta": train_meta,
                "test_meta": test_meta,
                "selected_model_id": selected_config.model_id,
                "selected_train_result": selected_train,
                "test_result": test_result,
                "train_top_results": train_results[:5],
            }
        )
        print(f"walk-forward fold {len(folds)} selected {selected_config.model_id}", flush=True)
        if int(args.fold_limit) > 0 and len(folds) >= int(args.fold_limit):
            break
        fold_start += step_delta

    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "source_report": str(source_path),
        "symbol": symbol,
        "exec_interval": exec_interval,
        "scenario_intervals": scenario_intervals,
        "train_days": int(args.train_days),
        "test_days": int(args.test_days),
        "step_days": int(args.step_days),
        "load_days": int(args.load_days),
        "candidate_count": len(configs),
        "cost_model": {
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": float(args.slippage_bps_per_side),
            "funding_bps_per_8h": float(args.funding_bps_per_8h),
            "borrow_bps_per_day": float(args.borrow_bps_per_day),
            "carry_rate_per_bar": carry_rate_per_bar,
        },
        "aggregate": _aggregate_folds(folds),
        "folds": folds,
    }

    if args.write_report:
        report_dir = Path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        json_path = report_dir / f"market_state_rotation_v6_walk_forward_{symbol}_{exec_interval}_{stamp}.json"
        latest_json = report_dir / f"market_state_rotation_v6_walk_forward_{symbol}_{exec_interval}_latest.json"
        summary_md = report_dir / "walk_forward_v6.md"
        text = json.dumps(report, ensure_ascii=False, indent=2)
        atomic_write_text(json_path, text)
        atomic_write_text(latest_json, text)
        _write_markdown(report, summary_md)
        print(f"wrote {json_path}")
        print(f"wrote {latest_json}")
        print(f"wrote {summary_md}")

    print(
        json.dumps(
            {
                "symbol": symbol,
                "exec_interval": exec_interval,
                "candidate_count": len(configs),
                "aggregate": report["aggregate"],
                "folds": [
                    {
                        "fold": fold.get("fold"),
                        "selected_model_id": fold.get("selected_model_id"),
                        "selected_train_result": _stdout_result_summary(fold["selected_train_result"]),
                        "test_result": _stdout_result_summary(fold["test_result"]) if fold.get("test_result") else None,
                    }
                    for fold in folds
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
