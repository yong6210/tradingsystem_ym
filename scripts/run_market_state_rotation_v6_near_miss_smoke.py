#!/usr/bin/env python3
"""Fast current-window smoke test for v6 near-miss micro-probe candidates."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import fields, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.run_market_state_rotation_v6_backtest import (
    MarketStateConfig,
    _carry_rate_per_bar,
    _load_feature_sets,
    backtest_config,
)
from scripts.run_market_state_rotation_v6_paper_bridge_tick import (
    DEFAULT_SOURCE_BACKTEST_REPORT,
    EXPECTED_SYMBOL,
    _optional_float,
    _optional_positive_int,
    _runtime_namespace,
    _source_arg,
)


DEFAULT_REPORT_DIR = "reports/validation/diagnostics/market_state_rotation_v6_near_miss_smoke"


def _resolve(path: str | Path) -> Path:
    raw = Path(path)
    return raw if raw.is_absolute() else ROOT_DIR / raw


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _load_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _coerce_config(raw: dict[str, Any]) -> MarketStateConfig:
    allowed = {item.name for item in fields(MarketStateConfig)}
    return MarketStateConfig(**{key: value for key, value in raw.items() if key in allowed})


def _source_config(report: dict[str, Any]) -> MarketStateConfig:
    for key in ("best_by_method_score", "best_by_raw_return"):
        section = dict(report.get(key) or {})
        config = dict(section.get("config") or {})
        if config:
            return _coerce_config(config)
    for item in list(report.get("top_results") or []):
        config = dict(dict(item or {}).get("config") or {})
        if config:
            return _coerce_config(config)
    raise ValueError("source_backtest_config_missing")


def _candidate_configs(base: MarketStateConfig) -> list[tuple[str, dict[str, Any], MarketStateConfig]]:
    recipes: list[tuple[str, dict[str, Any]]] = [
        ("base", {}),
        (
            "near_miss_mc12_mc04_trend_normal_0001_score3_ext15",
            {
                "near_miss_probe_units": 0.0001,
                "near_miss_probe_min_score": 3,
                "near_miss_probe_min_score_edge": 0,
                "near_miss_probe_min_reason_stack": 1,
                "near_miss_probe_cooldown_bars": 36,
                "near_miss_probe_max_extension_atr": 1.5,
                "near_miss_probe_failure_guard_count": 2,
                "near_miss_probe_failure_guard_window_bars": 1440,
                "near_miss_probe_failure_cooldown_bars": 4320,
                "near_miss_probe_allowed_soft_reasons": ("MC12_low_confluence", "MC04_no_clear_first_touch"),
                "near_miss_probe_allowed_alignments": ("with_trend",),
                "near_miss_probe_allowed_execution_contexts": ("normal",),
                "near_miss_probe_allowed_regimes": ("uptrend", "downtrend"),
            },
        ),
        (
            "near_miss_mc12_mc04_trend_normal_0001_score3_ext20",
            {
                "near_miss_probe_units": 0.0001,
                "near_miss_probe_min_score": 3,
                "near_miss_probe_min_score_edge": 0,
                "near_miss_probe_min_reason_stack": 1,
                "near_miss_probe_cooldown_bars": 36,
                "near_miss_probe_max_extension_atr": 2.0,
                "near_miss_probe_failure_guard_count": 2,
                "near_miss_probe_failure_guard_window_bars": 1440,
                "near_miss_probe_failure_cooldown_bars": 4320,
                "near_miss_probe_allowed_soft_reasons": ("MC12_low_confluence", "MC04_no_clear_first_touch"),
                "near_miss_probe_allowed_alignments": ("with_trend",),
                "near_miss_probe_allowed_execution_contexts": ("normal",),
                "near_miss_probe_allowed_regimes": ("uptrend", "downtrend"),
            },
        ),
        (
            "near_miss_mc12_mc04_trend_normal_00025_score3_ext15",
            {
                "near_miss_probe_units": 0.00025,
                "near_miss_probe_min_score": 3,
                "near_miss_probe_min_score_edge": 0,
                "near_miss_probe_min_reason_stack": 1,
                "near_miss_probe_cooldown_bars": 36,
                "near_miss_probe_max_extension_atr": 1.5,
                "near_miss_probe_failure_guard_count": 2,
                "near_miss_probe_failure_guard_window_bars": 1440,
                "near_miss_probe_failure_cooldown_bars": 4320,
                "near_miss_probe_allowed_soft_reasons": ("MC12_low_confluence", "MC04_no_clear_first_touch"),
                "near_miss_probe_allowed_alignments": ("with_trend",),
                "near_miss_probe_allowed_execution_contexts": ("normal",),
                "near_miss_probe_allowed_regimes": ("uptrend", "downtrend"),
            },
        ),
        (
            "near_miss_mc12_mc04_trend_normal_00025_score3_ext20",
            {
                "near_miss_probe_units": 0.00025,
                "near_miss_probe_min_score": 3,
                "near_miss_probe_min_score_edge": 0,
                "near_miss_probe_min_reason_stack": 1,
                "near_miss_probe_cooldown_bars": 36,
                "near_miss_probe_max_extension_atr": 2.0,
                "near_miss_probe_failure_guard_count": 2,
                "near_miss_probe_failure_guard_window_bars": 1440,
                "near_miss_probe_failure_cooldown_bars": 4320,
                "near_miss_probe_allowed_soft_reasons": ("MC12_low_confluence", "MC04_no_clear_first_touch"),
                "near_miss_probe_allowed_alignments": ("with_trend",),
                "near_miss_probe_allowed_execution_contexts": ("normal",),
                "near_miss_probe_allowed_regimes": ("uptrend", "downtrend"),
            },
        ),
        (
            "near_miss_mc12_mc04_trend_normal_0001_score2_ext15_review",
            {
                "near_miss_probe_units": 0.0001,
                "near_miss_probe_min_score": 2,
                "near_miss_probe_min_score_edge": 0,
                "near_miss_probe_min_reason_stack": 1,
                "near_miss_probe_cooldown_bars": 48,
                "near_miss_probe_max_extension_atr": 1.5,
                "near_miss_probe_failure_guard_count": 2,
                "near_miss_probe_failure_guard_window_bars": 1440,
                "near_miss_probe_failure_cooldown_bars": 4320,
                "near_miss_probe_allowed_soft_reasons": ("MC12_low_confluence", "MC04_no_clear_first_touch"),
                "near_miss_probe_allowed_alignments": ("with_trend",),
                "near_miss_probe_allowed_execution_contexts": ("normal",),
                "near_miss_probe_allowed_regimes": ("uptrend", "downtrend"),
            },
        ),
        (
            "near_miss_mc12_trend_normal_00025",
            {
                "near_miss_probe_units": 0.00025,
                "near_miss_probe_min_score": 4,
                "near_miss_probe_min_score_edge": 0,
                "near_miss_probe_min_reason_stack": 1,
                "near_miss_probe_cooldown_bars": 36,
                "near_miss_probe_max_extension_atr": 1.75,
                "near_miss_probe_failure_guard_count": 2,
                "near_miss_probe_failure_guard_window_bars": 1440,
                "near_miss_probe_failure_cooldown_bars": 4320,
                "near_miss_probe_allowed_soft_reasons": ("MC12_low_confluence",),
                "near_miss_probe_allowed_alignments": ("with_trend",),
                "near_miss_probe_allowed_execution_contexts": ("normal",),
                "near_miss_probe_allowed_regimes": ("uptrend", "downtrend"),
            },
        ),
        (
            "near_miss_mc12_trend_normal_00025_edge1",
            {
                "near_miss_probe_units": 0.00025,
                "near_miss_probe_min_score": 5,
                "near_miss_probe_min_score_edge": 1,
                "near_miss_probe_min_reason_stack": 1,
                "near_miss_probe_cooldown_bars": 36,
                "near_miss_probe_max_extension_atr": 1.75,
                "near_miss_probe_failure_guard_count": 2,
                "near_miss_probe_failure_guard_window_bars": 1440,
                "near_miss_probe_failure_cooldown_bars": 4320,
                "near_miss_probe_allowed_soft_reasons": ("MC12_low_confluence",),
                "near_miss_probe_allowed_alignments": ("with_trend",),
                "near_miss_probe_allowed_execution_contexts": ("normal",),
                "near_miss_probe_allowed_regimes": ("uptrend", "downtrend"),
            },
        ),
        (
            "near_miss_mc12_trend_normal_001_edge1",
            {
                "near_miss_probe_units": 0.001,
                "near_miss_probe_min_score": 5,
                "near_miss_probe_min_score_edge": 1,
                "near_miss_probe_min_reason_stack": 1,
                "near_miss_probe_cooldown_bars": 36,
                "near_miss_probe_max_extension_atr": 1.75,
                "near_miss_probe_failure_guard_count": 2,
                "near_miss_probe_failure_guard_window_bars": 1440,
                "near_miss_probe_failure_cooldown_bars": 4320,
                "near_miss_probe_allowed_soft_reasons": ("MC12_low_confluence",),
                "near_miss_probe_allowed_alignments": ("with_trend",),
                "near_miss_probe_allowed_execution_contexts": ("normal",),
                "near_miss_probe_allowed_regimes": ("uptrend", "downtrend"),
            },
        ),
        (
            "near_miss_mc12_trend_normal_00025_stack2",
            {
                "near_miss_probe_units": 0.00025,
                "near_miss_probe_min_score": 5,
                "near_miss_probe_min_score_edge": 1,
                "near_miss_probe_min_reason_stack": 2,
                "near_miss_probe_cooldown_bars": 36,
                "near_miss_probe_max_extension_atr": 1.75,
                "near_miss_probe_failure_guard_count": 2,
                "near_miss_probe_failure_guard_window_bars": 1440,
                "near_miss_probe_failure_cooldown_bars": 4320,
                "near_miss_probe_allowed_soft_reasons": ("MC12_low_confluence",),
                "near_miss_probe_allowed_alignments": ("with_trend",),
                "near_miss_probe_allowed_execution_contexts": ("normal",),
                "near_miss_probe_allowed_regimes": ("uptrend", "downtrend"),
            },
        ),
        (
            "near_miss_probe_00025_guarded",
            {
                "near_miss_probe_units": 0.00025,
                "near_miss_probe_min_score": 4,
                "near_miss_probe_min_score_edge": 0,
                "near_miss_probe_min_reason_stack": 1,
                "near_miss_probe_cooldown_bars": 36,
                "near_miss_probe_max_extension_atr": 2.0,
                "near_miss_probe_failure_guard_count": 2,
                "near_miss_probe_failure_guard_window_bars": 1440,
                "near_miss_probe_failure_cooldown_bars": 4320,
            },
        ),
        (
            "near_miss_probe_001_guarded",
            {
                "near_miss_probe_units": 0.001,
                "near_miss_probe_min_score": 4,
                "near_miss_probe_min_score_edge": 0,
                "near_miss_probe_min_reason_stack": 1,
                "near_miss_probe_cooldown_bars": 36,
                "near_miss_probe_max_extension_atr": 2.0,
                "near_miss_probe_failure_guard_count": 2,
                "near_miss_probe_failure_guard_window_bars": 1440,
                "near_miss_probe_failure_cooldown_bars": 4320,
            },
        ),
        (
            "near_miss_probe_0025_guarded",
            {
                "near_miss_probe_units": 0.0025,
                "near_miss_probe_min_score": 4,
                "near_miss_probe_min_score_edge": 0,
                "near_miss_probe_min_reason_stack": 1,
                "near_miss_probe_cooldown_bars": 36,
                "near_miss_probe_max_extension_atr": 2.0,
                "near_miss_probe_failure_guard_count": 2,
                "near_miss_probe_failure_guard_window_bars": 1440,
                "near_miss_probe_failure_cooldown_bars": 4320,
            },
        ),
    ]
    candidates: list[tuple[str, dict[str, Any], MarketStateConfig]] = []
    for name, change in recipes:
        candidates.append((name, change, replace(base, **change) if change else base))
    return candidates


def _summarize_result(name: str, change: dict[str, Any], result: dict[str, Any] | None) -> dict[str, Any]:
    if result is None:
        return {"name": name, "status": "no_result", "config_change": change}
    diagnostics = dict(result.get("event_diagnostics") or {})
    ratios = dict(diagnostics.get("ratios") or {})
    return {
        "name": name,
        "status": "ok",
        "config_change": change,
        "model_id": result.get("model_id"),
        "total_return_pct": _safe_float(result.get("total_return_pct")),
        "max_drawdown_pct": _safe_float(result.get("max_drawdown_pct")),
        "trade_like_events": _safe_int(result.get("trade_like_events")),
        "add_events": _safe_int(diagnostics.get("add_events")),
        "remove_events": _safe_int(diagnostics.get("remove_events")),
        "turnover_events_per_add": _safe_float(ratios.get("turnover_events_per_add")),
        "probe_add_per_add": _safe_float(ratios.get("probe_add_per_add")),
        "one_way_forced_trim_per_add": _safe_float(ratios.get("one_way_forced_trim_per_add")),
        "sample_events": list(result.get("recent_events") or result.get("sample_events") or [])[-12:],
    }


def _with_deltas(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = next((item for item in candidates if item.get("name") == "base" and item.get("status") == "ok"), None)
    if base is None:
        return candidates
    base_return = _safe_float(base.get("total_return_pct"))
    base_dd = _safe_float(base.get("max_drawdown_pct"))
    base_adds = _safe_int(base.get("add_events"))
    rows: list[dict[str, Any]] = []
    for item in candidates:
        row = dict(item)
        if row.get("status") == "ok":
            row["delta_vs_base"] = {
                "return_pct": round(_safe_float(row.get("total_return_pct")) - base_return, 4),
                "max_drawdown_pct": round(_safe_float(row.get("max_drawdown_pct")) - base_dd, 4),
                "add_events": _safe_int(row.get("add_events")) - base_adds,
            }
            delta = dict(row["delta_vs_base"])
            row["smoke_decision"] = (
                "promote_to_full_walk_forward_evidence_probe_candidate"
                if _safe_int(delta.get("add_events")) > 0
                and _safe_float(delta.get("max_drawdown_pct")) <= 3.0
                and _safe_float(delta.get("return_pct")) >= -5.0
                else "reject_or_keep_for_manual_review"
                if row.get("name") != "base"
                else "baseline"
            )
            row["primary_use"] = (
                "baseline"
                if row.get("name") == "base"
                else "paper_evidence_collection_probe"
                if row["smoke_decision"] == "promote_to_full_walk_forward_evidence_probe_candidate"
                else "manual_review_only"
            )
        rows.append(row)
    return rows


def build_near_miss_smoke_report(
    *,
    source_report: dict[str, Any],
    symbol: str = EXPECTED_SYMBOL,
    days: int = 120,
    load_days: int | None = None,
    exec_interval: str | None = None,
    scenario_intervals: str | None = None,
    cache_dir: str | None = None,
    base_url: str | None = None,
    sleep_seconds: float | None = None,
    fee_bps_per_side: float | None = None,
    slippage_bps_per_side: float | None = None,
    funding_bps_per_8h: float | None = None,
    borrow_bps_per_day: float | None = None,
    min_periods: int | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    base_config = _source_config(source_report)
    inherited_load_days = _optional_positive_int(_source_arg(source_report, "load_days", None))
    resolved_load_days = _optional_positive_int(load_days) or inherited_load_days or 365
    resolved_exec_interval = str(exec_interval or _source_arg(source_report, "exec_interval", "5m") or "5m")
    resolved_scenario_intervals = str(
        scenario_intervals or _source_arg(source_report, "scenario_intervals", "1h,4h") or "1h,4h"
    )
    resolved_cache_dir = str(
        cache_dir
        or _source_arg(source_report, "cache_dir", "reports/validation/btc_flip_rotation_search/cache")
        or "reports/validation/btc_flip_rotation_search/cache"
    )
    resolved_base_url = str(base_url if base_url is not None else _source_arg(source_report, "base_url", ""))
    resolved_sleep_seconds = (
        _optional_float(sleep_seconds)
        if sleep_seconds is not None
        else _optional_float(_source_arg(source_report, "sleep_seconds", 0.03))
    )
    resolved_fee_bps = (
        _optional_float(fee_bps_per_side)
        if fee_bps_per_side is not None
        else _optional_float(_source_arg(source_report, "fee_bps_per_side", 4.0))
    )
    resolved_slippage_bps = (
        _optional_float(slippage_bps_per_side)
        if slippage_bps_per_side is not None
        else _optional_float(_source_arg(source_report, "slippage_bps_per_side", 1.0))
    )
    resolved_funding_bps = (
        _optional_float(funding_bps_per_8h)
        if funding_bps_per_8h is not None
        else _optional_float(_source_arg(source_report, "funding_bps_per_8h", 0.0))
    )
    resolved_borrow_bps = (
        _optional_float(borrow_bps_per_day)
        if borrow_bps_per_day is not None
        else _optional_float(_source_arg(source_report, "borrow_bps_per_day", 0.0))
    )
    resolved_min_periods = (
        _optional_positive_int(min_periods)
        or _optional_positive_int(_source_arg(source_report, "min_periods", 5000))
        or 5000
    )
    namespace = _runtime_namespace(
        symbol=symbol,
        days=days,
        load_days=resolved_load_days,
        exec_interval=resolved_exec_interval,
        scenario_intervals=resolved_scenario_intervals,
        cache_dir=resolved_cache_dir,
        base_url=resolved_base_url,
        sleep_seconds=resolved_sleep_seconds if resolved_sleep_seconds is not None else 0.03,
    )
    features, scenario_features, scenario_maps, data_meta = _load_feature_sets(namespace)
    cost_rate = (max(float(resolved_fee_bps or 0.0), 0.0) + max(float(resolved_slippage_bps or 0.0), 0.0)) / 10_000.0
    carry_rate = _carry_rate_per_bar(
        exec_interval=resolved_exec_interval,
        funding_bps_per_8h=float(resolved_funding_bps or 0.0),
        borrow_bps_per_day=float(resolved_borrow_bps or 0.0),
    )
    summaries: list[dict[str, Any]] = []
    for name, change, config in _candidate_configs(base_config):
        result = backtest_config(
            symbol=symbol,
            features=features,
            scenario_features=scenario_features,
            scenario_maps=scenario_maps,
            config=config,
            cost_rate=cost_rate,
            min_periods=max(1, int(resolved_min_periods)),
            carry_rate_per_bar=carry_rate,
            recent_event_limit=80,
        )
        summaries.append(_summarize_result(name, change, result))
    candidates = _with_deltas(summaries)
    promoted = [
        item
        for item in candidates
        if item.get("smoke_decision") == "promote_to_full_walk_forward_evidence_probe_candidate"
    ]
    return {
        "generated_at": generated_at.isoformat(),
        "status": "candidate_found" if promoted else "no_candidate_promoted",
        "no_live_order_sent": True,
        "symbol": symbol,
        "window": {"days": int(days), "load_days": int(resolved_load_days), "data": data_meta},
        "resolved_runtime_args": {
            "exec_interval": resolved_exec_interval,
            "scenario_intervals": resolved_scenario_intervals,
            "cache_dir": resolved_cache_dir,
            "base_url": resolved_base_url,
            "sleep_seconds": resolved_sleep_seconds if resolved_sleep_seconds is not None else 0.03,
            "fee_bps_per_side": resolved_fee_bps if resolved_fee_bps is not None else 4.0,
            "slippage_bps_per_side": resolved_slippage_bps if resolved_slippage_bps is not None else 1.0,
            "funding_bps_per_8h": resolved_funding_bps if resolved_funding_bps is not None else 0.0,
            "borrow_bps_per_day": resolved_borrow_bps if resolved_borrow_bps is not None else 0.0,
            "min_periods": int(resolved_min_periods),
        },
        "source_model_id": base_config.model_id,
        "candidate_count": len(candidates),
        "promoted_candidate_count": len(promoted),
        "best_promoted_candidate": max(
            promoted,
            key=lambda item: (
                _safe_int(dict(item.get("delta_vs_base") or {}).get("add_events")),
                _safe_float(dict(item.get("delta_vs_base") or {}).get("return_pct")),
            ),
            default=None,
        ),
        "candidates": candidates,
        "non_negotiables": [
            "smoke_test_is_not_full_walk_forward_approval",
            "do_not_enable_live_orders_from_near_miss_smoke",
            "promoted_candidates_must_pass_full_walk_forward_and_paper_evidence",
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Market State Rotation V6 Near-Miss Smoke",
        "",
        f"- status: `{report.get('status')}`",
        f"- no_live_order_sent: `{report.get('no_live_order_sent')}`",
        f"- candidates: `{report.get('candidate_count')}`",
        f"- promoted: `{report.get('promoted_candidate_count')}`",
        "",
    ]
    for item in list(report.get("candidates") or []):
        delta = dict(item.get("delta_vs_base") or {})
        lines.append(
            f"- `{item.get('name')}` return `{item.get('total_return_pct')}` dd `{item.get('max_drawdown_pct')}` "
            f"adds `{item.get('add_events')}` decision `{item.get('smoke_decision')}` "
            f"delta `{delta}`"
        )
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run fast v6 near-miss micro-probe smoke test.")
    parser.add_argument("--source-backtest-report", default=DEFAULT_SOURCE_BACKTEST_REPORT)
    parser.add_argument("--symbol", default=EXPECTED_SYMBOL)
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--load-days", type=int, default=0, help="0 inherits source report args.load_days.")
    parser.add_argument("--min-periods", type=int, default=5000)
    parser.add_argument("--cache-dir", default="reports/validation/btc_flip_rotation_search/cache")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    parser.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_path = _resolve(args.source_backtest_report)
    report = build_near_miss_smoke_report(
        source_report=_load_json(source_path),
        symbol=str(args.symbol or EXPECTED_SYMBOL).upper(),
        days=max(1, int(args.days)),
        load_days=int(args.load_days) if int(args.load_days) > 0 else None,
        cache_dir=str(args.cache_dir),
        base_url=str(args.base_url or ""),
        sleep_seconds=max(0.0, float(args.sleep_seconds)),
        min_periods=max(1, int(args.min_periods)),
    )
    report["input_source_backtest_report"] = _display_path(source_path)
    if args.write_report:
        report_dir = _resolve(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_near_miss_smoke.json"
        md_path = report_dir / "market_state_rotation_v6_near_miss_smoke.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        report["report_path"] = _display_path(json_path)
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
