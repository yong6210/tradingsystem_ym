#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.report_io import atomic_write_text
from scripts.run_market_state_rotation_v6_backtest import (
    MarketStateConfig,
    _csv,
    _load_feature_sets,
    backtest_config,
)


DEFAULT_SOURCE_REPORT = (
    "reports/validation/market_state_rotation_v6_backtest/"
    "market_state_rotation_v6_BTCUSDT_5m_365d_latest.json"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate top market-state rotation v6 candidates across multiple horizons. "
            "This checks robustness instead of selecting only the latest 365d winner."
        )
    )
    parser.add_argument("--source-report", default=DEFAULT_SOURCE_REPORT)
    parser.add_argument("--report-dir", default="reports/validation/market_state_rotation_v6_backtest")
    parser.add_argument("--days-list", default="365,730,1095,1460,1825")
    parser.add_argument("--load-days", type=int, default=1825)
    parser.add_argument("--top-n", type=int, default=6)
    parser.add_argument("--symbol", default="")
    parser.add_argument("--exec-interval", default="")
    parser.add_argument("--scenario-intervals", default="")
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument("--min-periods", type=int, default=5000)
    parser.add_argument("--cache-dir", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    parser.add_argument("--dedupe-material-configs", action="store_true", default=True)
    parser.add_argument("--keep-battle-bar-duplicates", dest="dedupe_material_configs", action="store_false")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _parse_days_list(raw: str) -> list[int]:
    values: list[int] = []
    for item in _csv(raw):
        try:
            value = int(item)
        except ValueError:
            continue
        if value > 0 and value not in values:
            values.append(value)
    return values or [365]


def _material_config_key(config: MarketStateConfig) -> str:
    payload = {
        key: value
        for key, value in asdict(config).items()
        if key not in {"model_id", "max_battle_bars"}
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _configs_from_source(report: dict[str, Any], *, top_n: int, dedupe_material_configs: bool) -> list[MarketStateConfig]:
    candidates: list[dict[str, Any]] = []
    for section in ("top_results", "top_results_by_return"):
        for result in report.get(section) or []:
            if isinstance(result, dict) and isinstance(result.get("config"), dict):
                candidates.append(result)
    for key in ("best_by_method_score", "best_by_raw_return"):
        result = report.get(key)
        if isinstance(result, dict) and isinstance(result.get("config"), dict):
            candidates.insert(0, result)

    configs: list[MarketStateConfig] = []
    seen: set[str] = set()
    for result in candidates:
        try:
            config = MarketStateConfig(**result["config"])
        except TypeError:
            continue
        key = _material_config_key(config) if dedupe_material_configs else config.model_id
        if key in seen:
            continue
        seen.add(key)
        configs.append(config)
        if len(configs) >= top_n:
            break
    return configs


def _namespace_for_horizon(
    *,
    args: argparse.Namespace,
    source_args: dict[str, Any],
    days: int,
    symbol: str,
    exec_interval: str,
    scenario_intervals: str,
) -> argparse.Namespace:
    cache_dir = args.cache_dir or str(source_args.get("cache_dir") or "reports/validation/btc_flip_rotation_search/cache")
    return argparse.Namespace(
        symbol=symbol,
        days=days,
        load_days=max(int(args.load_days), days),
        exec_interval=exec_interval,
        scenario_intervals=scenario_intervals,
        cache_dir=cache_dir,
        base_url=args.base_url or str(source_args.get("base_url") or ""),
        sleep_seconds=float(args.sleep_seconds),
    )


def _robust_score(results: list[dict[str, Any] | None]) -> float:
    valid = [result for result in results if result]
    if not valid:
        return -1e9
    cagr_values = [float(result.get("cagr_pct") or 0.0) for result in valid]
    mdd_values = [float(result.get("max_drawdown_pct") or 100.0) for result in valid]
    positive_count = sum(1 for result in valid if float(result.get("total_return_pct") or 0.0) > 0.0)
    flag_count = len(
        {
            str(flag)
            for result in valid
            for flag in dict(result.get("event_diagnostics") or {}).get("flags", [])
        }
    )
    missing_count = len(results) - len(valid)
    return round(
        min(cagr_values)
        + 0.35 * (sum(cagr_values) / max(len(cagr_values), 1))
        - 1.45 * max(mdd_values)
        - 4.0 * flag_count
        - 15.0 * (len(results) - positive_count)
        - 25.0 * missing_count,
        4,
    )


def _summarize_candidate(config: MarketStateConfig, horizon_results: dict[int, dict[str, Any] | None]) -> dict[str, Any]:
    results = [horizon_results[days] for days in sorted(horizon_results)]
    valid = [result for result in results if result]
    cagr_values = [float(result.get("cagr_pct") or 0.0) for result in valid]
    mdd_values = [float(result.get("max_drawdown_pct") or 0.0) for result in valid]
    return_values = [float(result.get("total_return_pct") or 0.0) for result in valid]
    flag_union = sorted(
        {
            str(flag)
            for result in valid
            for flag in dict(result.get("event_diagnostics") or {}).get("flags", [])
        }
    )
    return {
        "model_id": config.model_id,
        "config": asdict(config),
        "robust_score": _robust_score(results),
        "positive_horizons": sum(1 for value in return_values if value > 0.0),
        "horizon_count": len(results),
        "min_total_return_pct": round(min(return_values), 4) if return_values else None,
        "max_total_return_pct": round(max(return_values), 4) if return_values else None,
        "min_cagr_pct": round(min(cagr_values), 4) if cagr_values else None,
        "avg_cagr_pct": round(sum(cagr_values) / len(cagr_values), 4) if cagr_values else None,
        "max_drawdown_pct": round(max(mdd_values), 4) if mdd_values else None,
        "flag_union": flag_union,
        "horizons": {str(days): horizon_results[days] for days in sorted(horizon_results)},
    }


def _format_flags(result: dict[str, Any] | None) -> str:
    if not result:
        return "missing"
    flags = dict(result.get("event_diagnostics") or {}).get("flags") or []
    return ", ".join(str(flag) for flag in flags) or "none"


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    candidates = report.get("candidates") or []
    lines = [
        "# Market-State Rotation V6 Multihorizon Validation",
        "",
        f"- Created at: `{report.get('created_at')}`",
        f"- Source report: `{report.get('source_report')}`",
        f"- Symbol: `{report.get('symbol')}`",
        f"- Execution interval: `{report.get('exec_interval')}`",
        f"- Horizons: `{', '.join(str(days) for days in report.get('days_list') or [])}`",
        f"- Validated candidates: `{len(candidates)}`",
        "",
        "## Robust Ranking",
        "",
        "| rank | robust score | min CAGR % | avg CAGR % | max MDD % | positive | hold | max units | flags | model |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for idx, item in enumerate(candidates, start=1):
        config = dict(item.get("config") or {})
        lines.append(
            f"| {idx} | {item.get('robust_score')} | {item.get('min_cagr_pct')} | "
            f"{item.get('avg_cagr_pct')} | {item.get('max_drawdown_pct')} | "
            f"{item.get('positive_horizons')}/{item.get('horizon_count')} | "
            f"{config.get('max_hold_bars')} | {config.get('max_possible_units')} | "
            f"{', '.join(item.get('flag_union') or []) or 'none'} | `{item.get('model_id')}` |"
        )
    lines.extend(["", "## Horizon Detail", ""])
    for item in candidates:
        config = dict(item.get("config") or {})
        lines.extend(
            [
                f"### hold {config.get('max_hold_bars')} / max units {config.get('max_possible_units')}",
                "",
                f"- Model: `{item.get('model_id')}`",
                "",
                "| days | return % | CAGR % | MDD % | events | adds long/short | health | flags |",
                "|---:|---:|---:|---:|---:|---|---|---|",
            ]
        )
        horizons = dict(item.get("horizons") or {})
        for days in sorted(int(key) for key in horizons):
            result = horizons[str(days)]
            if not result:
                lines.append(f"| {days} | missing | missing | missing | missing | missing | missing | missing |")
                continue
            diag = dict(result.get("event_diagnostics") or {})
            adds = dict(diag.get("add_by_side") or {})
            lines.append(
                f"| {days} | {result.get('total_return_pct')} | {result.get('cagr_pct')} | "
                f"{result.get('max_drawdown_pct')} | {result.get('trade_like_events')} | "
                f"{adds.get('long', 0)}/{adds.get('short', 0)} | {diag.get('health')} | {_format_flags(result)} |"
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
    scenario_intervals = args.scenario_intervals or str(source_args.get("scenario_intervals") or "1h,4h")
    days_list = _parse_days_list(args.days_list)
    configs = _configs_from_source(
        source_report,
        top_n=max(1, int(args.top_n)),
        dedupe_material_configs=bool(args.dedupe_material_configs),
    )
    if not configs:
        raise SystemExit(f"no configs found in {source_path}")

    cost_rate = (max(float(args.fee_bps_per_side), 0.0) + max(float(args.slippage_bps_per_side), 0.0)) / 10_000.0
    by_model: dict[str, dict[int, dict[str, Any] | None]] = {
        config.model_id: {} for config in configs
    }

    for days in days_list:
        horizon_args = _namespace_for_horizon(
            args=args,
            source_args=source_args,
            days=days,
            symbol=symbol,
            exec_interval=exec_interval,
            scenario_intervals=scenario_intervals,
        )
        features, scenario_features, scenario_maps, _data_meta = _load_feature_sets(horizon_args)
        for config in configs:
            horizon_config = replace(config, exec_interval=exec_interval)
            result = backtest_config(
                symbol=symbol,
                features=features,
                scenario_features=scenario_features,
                scenario_maps=scenario_maps,
                config=horizon_config,
                cost_rate=cost_rate,
                min_periods=int(args.min_periods),
            )
            by_model[config.model_id][days] = result
        print(f"validated {days}d horizon for {len(configs)} candidates", flush=True)

    candidates = [
        _summarize_candidate(config, by_model[config.model_id])
        for config in configs
    ]
    candidates.sort(
        key=lambda item: (
            float(item.get("robust_score") or -1e9),
            float(item.get("min_cagr_pct") or -1e9),
            -float(item.get("max_drawdown_pct") or math.inf),
        ),
        reverse=True,
    )

    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "source_report": str(source_path),
        "symbol": symbol,
        "exec_interval": exec_interval,
        "scenario_intervals": _csv(scenario_intervals),
        "days_list": days_list,
        "candidate_count": len(candidates),
        "cost_rate": cost_rate,
        "candidates": candidates,
    }

    if args.write_report:
        report_dir = Path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        json_path = report_dir / f"market_state_rotation_v6_multihorizon_{symbol}_{exec_interval}_{stamp}.json"
        latest_json = report_dir / f"market_state_rotation_v6_multihorizon_{symbol}_{exec_interval}_latest.json"
        summary_md = report_dir / "multihorizon_v6.md"
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
                "days_list": days_list,
                "top_candidates": [
                    {
                        "model_id": item.get("model_id"),
                        "robust_score": item.get("robust_score"),
                        "min_cagr_pct": item.get("min_cagr_pct"),
                        "avg_cagr_pct": item.get("avg_cagr_pct"),
                        "max_drawdown_pct": item.get("max_drawdown_pct"),
                        "positive_horizons": item.get("positive_horizons"),
                        "horizon_count": item.get("horizon_count"),
                    }
                    for item in candidates[:5]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
