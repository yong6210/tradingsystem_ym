#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, deque
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text
from scripts import run_multi_asset_rotation_mix_backtest as mixbt
from scripts import run_multi_asset_rotation_search as rot


SYMBOLS_36 = mixbt.SYMBOLS_36
TOP_EXCLUDED_ORDER = (
    "RUNEUSDT",
    "INJUSDT",
    "1000FLOKIUSDT",
    "1000SHIBUSDT",
    "ETCUSDT",
    "BCHUSDT",
    "SOLUSDT",
    "FETUSDT",
    "OPUSDT",
    "ZECUSDT",
    "XRPUSDT",
    "XLMUSDT",
    "AVAXUSDT",
    "HBARUSDT",
    "AAVEUSDT",
)
MODE_6040 = "residual85_funding15_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only async rb4/rb8 sleeve mix scan.")
    parser.add_argument("--rb4-weights", default="0.55,0.6,0.65")
    parser.add_argument("--fallback-weights", default="0")
    parser.add_argument("--fallback-mode", default=MODE_6040)
    parser.add_argument("--fallback-lookback-hours", type=int, default=336)
    parser.add_argument("--fallback-top-k", type=int, default=1)
    parser.add_argument("--fallback-rebalance-hours", type=int, default=48)
    parser.add_argument("--fallback-gross", type=float, default=2.5)
    parser.add_argument("--fallback-drawdown-gate-pct", type=float, default=0.0)
    parser.add_argument("--fallback-drawdown-high-weight", type=float, default=-1.0)
    parser.add_argument("--rb4-drawdown-gate-pct", type=float, default=0.0)
    parser.add_argument("--rb4-drawdown-gate-weight", type=float, default=-1.0)
    parser.add_argument("--aux-weights", default="0")
    parser.add_argument("--aux-mode", default=MODE_6040)
    parser.add_argument("--aux-lookback-hours", type=int, default=336)
    parser.add_argument("--aux-top-k", type=int, default=1)
    parser.add_argument("--aux-rebalance-hours", type=int, default=48)
    parser.add_argument("--aux-gross", type=float, default=2.5)
    parser.add_argument("--extra-aux-weights", default="0")
    parser.add_argument("--extra-aux-mode", default=MODE_6040)
    parser.add_argument("--extra-aux-lookback-hours", type=int, default=336)
    parser.add_argument("--extra-aux-top-k", type=int, default=1)
    parser.add_argument("--extra-aux-rebalance-hours", type=int, default=48)
    parser.add_argument("--extra-aux-gross", type=float, default=2.5)
    parser.add_argument("--extra-aux-trend-hours", type=int, default=0)
    parser.add_argument("--main-max-symbol-weight", type=float, default=0.0)
    parser.add_argument("--fallback-max-symbol-weight", type=float, default=0.0)
    parser.add_argument("--aux-max-symbol-weight", type=float, default=0.0)
    parser.add_argument("--extra-aux-max-symbol-weight", type=float, default=0.0)
    parser.add_argument("--main-fast-rebalance-hours", type=int, default=4)
    parser.add_argument("--main-slow-rebalance-hours", type=int, default=8)
    parser.add_argument("--main-lookback-hours", type=int, default=336)
    parser.add_argument("--main-top-k", type=int, default=0)
    parser.add_argument("--main-gross-scale", type=float, default=1.0)
    parser.add_argument("--secondary-main-weight", type=float, default=0.0)
    parser.add_argument("--secondary-main-mode", default="")
    parser.add_argument("--secondary-main-gross-scale", type=float, default=1.0)
    parser.add_argument("--secondary-main-lookback-hours", type=int, default=0)
    parser.add_argument("--secondary-main-top-k", type=int, default=0)
    parser.add_argument("--secondary-main-fast-rebalance-hours", type=int, default=0)
    parser.add_argument("--secondary-main-slow-rebalance-hours", type=int, default=0)
    parser.add_argument("--secondary-main-vol-weight", action="store_true")
    parser.add_argument("--main-vol-weight", action="store_true")
    parser.add_argument("--main-trend-hours", type=int, default=0)
    parser.add_argument("--fallback-trend-hours", type=int, default=0)
    parser.add_argument("--aux-trend-hours", type=int, default=0)
    parser.add_argument("--main-mode", default=MODE_6040)
    parser.add_argument("--rb4-quality-threshold", type=float, default=-0.005)
    parser.add_argument("--rb8-quality-threshold", type=float, default=-0.0005)
    parser.add_argument("--symbols", default=SYMBOLS_36)
    parser.add_argument("--days", type=int, default=1825)
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--drop-last-bars", type=int, default=1)
    parser.add_argument("--cache-dir", default="reports/validation/multi_asset_rotation_search/cache_refresh_20260521T2035")
    parser.add_argument("--funding-cache-dir", default="reports/validation/multi_asset_rotation_search/funding_cache")
    parser.add_argument("--exchange-rules-cache", default="reports/validation/multi_asset_rotation_search/exchange_rules_cache/exchange_info.json")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument("--holding-cost-bps-per-day", type=float, default=0.0)
    parser.add_argument("--short-cost-bps-per-day", type=float, default=0.0)
    parser.add_argument("--drawdown-guard-pct", type=float, default=20.0)
    parser.add_argument("--drawdown-guard-recovery-pct", type=float, default=0.0)
    parser.add_argument("--drawdown-risk-scale", type=float, default=0.4)
    parser.add_argument("--drawdown-ramp-start-pct", type=float, default=0.0)
    parser.add_argument("--drawdown-ramp-full-pct", type=float, default=0.0)
    parser.add_argument("--drawdown-ramp-risk-scale", type=float, default=1.0)
    parser.add_argument("--vol-target-annual-pct", type=float, default=60.0)
    parser.add_argument("--downside-vol-target-annual-pct", type=float, default=0.0)
    parser.add_argument("--vol-lookback-hours", type=int, default=720)
    parser.add_argument("--vol-min-scale", type=float, default=0.0)
    parser.add_argument("--vol-max-scale", type=float, default=1.0)
    parser.add_argument("--dispersion-lookback-rebalances", type=int, default=250)
    parser.add_argument("--dispersion-guard-quantile", type=float, default=0.8)
    parser.add_argument("--dispersion-risk-scale", type=float, default=1.0)
    parser.add_argument("--entry-grade-mode", choices=("off", "signal_quantile", "regime_quantile"), default="off")
    parser.add_argument("--entry-grade-lookback-rebalances", type=int, default=250)
    parser.add_argument("--entry-grade-low-quantile", type=float, default=0.25)
    parser.add_argument("--entry-grade-high-quantile", type=float, default=0.75)
    parser.add_argument("--entry-grade-min-scale", type=float, default=0.35)
    parser.add_argument("--entry-grade-max-scale", type=float, default=1.0)
    parser.add_argument("--market-stress-mode", choices=("off", "breadth", "btcema", "btcema_breadth"), default="off")
    parser.add_argument("--market-stress-breadth-threshold", type=float, default=0.35)
    parser.add_argument("--market-stress-btcema-fast", type=int, default=21)
    parser.add_argument("--market-stress-btcema-slow", type=int, default=144)
    parser.add_argument("--market-stress-btcema-threshold", type=float, default=0.0)
    parser.add_argument("--market-stress-min-net-ratio", type=float, default=0.05)
    parser.add_argument("--market-stress-risk-scale", type=float, default=0.5)
    parser.add_argument("--symbol-quality-min-active-periods", type=int, default=30)
    parser.add_argument("--symbol-quality-min-abs-exposure", type=float, default=1.0)
    parser.add_argument("--maintenance-margin-pct", type=float, default=5.0)
    parser.add_argument("--assumed-capital-usd", type=float, default=100000.0)
    parser.add_argument("--pnl-notional-mode", default="profit95")
    parser.add_argument("--liquidity-notional-mode", default="profit95")
    parser.add_argument("--liquidity-impact-bps-per-1pct-volume", type=float, default=0.25)
    parser.add_argument("--max-trade-volume-pct", type=float, default=0.5)
    parser.add_argument("--capacity-cap-trade-volume-pct", type=float, default=0.5)
    parser.add_argument("--report-dir", default="reports/validation/multi_asset_rotation_async_mix_scan")
    parser.add_argument("--scenario-set", choices=("screen", "full"), default="screen")
    parser.add_argument("--scenario-labels", default="")
    parser.add_argument("--include-ex-top15", action="store_true")
    parser.add_argument("--include-extreme-scenarios", action="store_true")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _float_csv(raw: str) -> list[float]:
    out: list[float] = []
    seen: set[float] = set()
    for item in str(raw or "").split(","):
        try:
            value = float(item.strip())
        except ValueError:
            continue
        if 0.0 <= value <= 1.0 and value not in seen:
            out.append(value)
            seen.add(value)
    return out or [0.6]


def _symbols_excluding(symbols: list[str], count: int) -> list[str]:
    drop = set(TOP_EXCLUDED_ORDER[:count])
    return [symbol for symbol in symbols if symbol not in drop]


def _strategy_cfg(
    kind: str,
    *,
    interval: str,
    lookback_hours: int = 336,
    main_top_k: int = 0,
    rebalance_hours: int,
    quality_threshold: float,
) -> tuple[rot.RotationPortfolioConfig, float, int, int, float]:
    if kind == "aggr":
        gross, top_k, cap, qlb, qdrop, qth = 6.7, 3, 0.725, 0, 0, 0.0
    elif kind == "bal":
        gross, top_k, cap, qlb, qdrop, qth = 5.8, 3, 0.725, 0, 0, 0.0
    elif kind == "qual":
        gross, top_k, cap, qlb, qdrop, qth = 6.4, 3, 0.725, 4320, 1, quality_threshold
    elif kind in {"fallback", "aux"}:
        gross, top_k, cap, qlb, qdrop, qth = 2.5, 1, 0.725, 0, 0, 0.0
    else:
        raise ValueError(f"unknown sleeve kind: {kind}")
    if kind not in {"fallback", "aux"} and int(main_top_k) > 0:
        top_k = max(int(main_top_k), 1)
    lookback_hours = max(int(lookback_hours), 1)
    config = rot.RotationPortfolioConfig(
        model_id=f"async:{kind}:rb{rebalance_hours}:q{qth:g}",
        interval=interval,
        mode=MODE_6040,
        lookback_hours=lookback_hours,
        lookback_bars=rot._hours_to_bars(interval, lookback_hours),
        top_k=top_k,
        rebalance_hours=rebalance_hours,
        rebalance_bars=rot._hours_to_bars(interval, rebalance_hours),
        trend_hours=0,
        trend_bars=0,
        vol_weight=False,
        vol_hours=lookback_hours,
        vol_bars=rot._hours_to_bars(interval, lookback_hours),
        min_symbol_age_hours=2160,
        min_symbol_age_bars=rot._hours_to_bars(interval, 2160),
        gross_leverage=gross,
    )
    return config, cap, qlb, qdrop, qth


def _build_sleeves(
    frame: rot.MarketFrame,
    *,
    interval: str,
    rb4_weight: float,
    fallback_weight: float,
    aux_weight: float,
    extra_aux_weight: float,
    fallback_mode: str,
    fallback_lookback_hours: int,
    fallback_top_k: int,
    fallback_rebalance_hours: int,
    fallback_gross: float,
    aux_mode: str,
    aux_lookback_hours: int,
    aux_top_k: int,
    aux_rebalance_hours: int,
    aux_gross: float,
    extra_aux_mode: str,
    extra_aux_lookback_hours: int,
    extra_aux_top_k: int,
    extra_aux_rebalance_hours: int,
    extra_aux_gross: float,
    main_fast_rebalance_hours: int,
    main_slow_rebalance_hours: int,
    main_lookback_hours: int,
    main_top_k: int,
    main_gross_scale: float,
    secondary_main_weight: float,
    secondary_main_mode: str,
    secondary_main_gross_scale: float,
    secondary_main_lookback_hours: int,
    secondary_main_top_k: int,
    secondary_main_fast_rebalance_hours: int,
    secondary_main_slow_rebalance_hours: int,
    secondary_main_vol_weight: bool,
    main_vol_weight: bool,
    main_max_symbol_weight: float,
    fallback_max_symbol_weight: float,
    aux_max_symbol_weight: float,
    extra_aux_max_symbol_weight: float,
    main_trend_hours: int,
    fallback_trend_hours: int,
    aux_trend_hours: int,
    extra_aux_trend_hours: int,
    main_mode: str,
    rb4_quality_threshold: float,
    rb8_quality_threshold: float,
    dispersion_lookback: int,
) -> list[mixbt.Sleeve]:
    main_weight = max(1.0 - fallback_weight - aux_weight - extra_aux_weight, 0.0)
    definitions: list[tuple[str, str, float, int, float, str, float, int, int, bool, int]] = []
    fast_hours = max(int(main_fast_rebalance_hours), 1)
    slow_hours = max(int(main_slow_rebalance_hours), 1)

    def append_main_sleeves(
        label: str,
        allocation_weight: float,
        mode: str,
        gross_scale: float,
        sleeve_fast_hours: int,
        sleeve_slow_hours: int,
        sleeve_lookback_hours: int,
        sleeve_top_k: int,
        sleeve_vol_weight: bool,
        sleeve_trend_hours: int,
    ) -> None:
        if allocation_weight <= 1e-12:
            return
        for kind, inner in (("aggr", 0.65), ("qual", 0.30), ("bal", 0.05)):
            definitions.append((
                kind,
                label,
                allocation_weight * rb4_weight * inner,
                sleeve_fast_hours,
                rb4_quality_threshold,
                mode,
                gross_scale,
                sleeve_lookback_hours,
                sleeve_top_k,
                sleeve_vol_weight,
                sleeve_trend_hours,
            ))
        for kind, inner in (("aggr", 0.65), ("qual", 0.30), ("bal", 0.05)):
            definitions.append((
                kind,
                label,
                allocation_weight * (1.0 - rb4_weight) * inner,
                sleeve_slow_hours,
                rb8_quality_threshold,
                mode,
                gross_scale,
                sleeve_lookback_hours,
                sleeve_top_k,
                sleeve_vol_weight,
                sleeve_trend_hours,
            ))

    secondary_fraction = min(max(float(secondary_main_weight), 0.0), 1.0)
    secondary_mode = str(secondary_main_mode or "")
    if not secondary_mode:
        secondary_fraction = 0.0
    secondary_fast_hours = max(int(secondary_main_fast_rebalance_hours or fast_hours), 1)
    secondary_slow_hours = max(int(secondary_main_slow_rebalance_hours or slow_hours), 1)
    secondary_lookback_hours = max(int(secondary_main_lookback_hours or main_lookback_hours), 1)
    secondary_top_k = int(secondary_main_top_k or main_top_k)
    append_main_sleeves(
        "",
        main_weight * (1.0 - secondary_fraction),
        str(main_mode),
        float(main_gross_scale),
        fast_hours,
        slow_hours,
        int(main_lookback_hours),
        int(main_top_k),
        bool(main_vol_weight),
        int(main_trend_hours),
    )
    append_main_sleeves(
        "secondary",
        main_weight * secondary_fraction,
        secondary_mode,
        float(secondary_main_gross_scale),
        secondary_fast_hours,
        secondary_slow_hours,
        secondary_lookback_hours,
        secondary_top_k,
        bool(secondary_main_vol_weight),
        int(main_trend_hours),
    )

    if fallback_weight > 1e-12:
        definitions.append(("fallback", "", fallback_weight, fallback_rebalance_hours, 0.0, "", 1.0, int(main_lookback_hours), int(main_top_k), False, 0))
    if aux_weight > 1e-12:
        definitions.append(("aux", "", aux_weight, aux_rebalance_hours, 0.0, "", 1.0, int(main_lookback_hours), int(main_top_k), False, 0))
    if extra_aux_weight > 1e-12:
        definitions.append(("extra_aux", "", extra_aux_weight, extra_aux_rebalance_hours, 0.0, "", 1.0, int(main_lookback_hours), int(main_top_k), False, 0))

    sleeves: list[mixbt.Sleeve] = []
    for (
        kind,
        label,
        allocation,
        rebalance_hours,
        quality_threshold,
        mode_override,
        gross_scale_override,
        sleeve_lookback_hours,
        sleeve_top_k,
        sleeve_vol_weight,
        sleeve_trend_hours,
    ) in definitions:
        if allocation <= 1e-12:
            continue
        cfg_kind = "aux" if kind == "extra_aux" else kind
        config, cap, qlb, qdrop, qth = _strategy_cfg(
            cfg_kind,
            interval=interval,
            lookback_hours=sleeve_lookback_hours,
            main_top_k=sleeve_top_k,
            rebalance_hours=rebalance_hours,
            quality_threshold=quality_threshold,
        )
        if kind in {"aggr", "qual", "bal"} and float(main_max_symbol_weight) > 0.0:
            cap = max(float(main_max_symbol_weight), 0.0)
        elif kind == "fallback" and float(fallback_max_symbol_weight) > 0.0:
            cap = max(float(fallback_max_symbol_weight), 0.0)
        elif kind == "aux" and float(aux_max_symbol_weight) > 0.0:
            cap = max(float(aux_max_symbol_weight), 0.0)
        elif kind == "extra_aux" and float(extra_aux_max_symbol_weight) > 0.0:
            cap = max(float(extra_aux_max_symbol_weight), 0.0)
        if kind not in {"fallback", "aux", "extra_aux"} and str(mode_override) != MODE_6040:
            config = replace(
                config,
                mode=str(mode_override),
                model_id=f"{config.model_id}:main_mode:{str(mode_override)}",
            )
        if kind not in {"fallback", "aux", "extra_aux"} and abs(float(gross_scale_override) - 1.0) > 1e-12:
            gross = max(config.gross_leverage * float(gross_scale_override), 0.0)
            config = replace(
                config,
                gross_leverage=gross,
                model_id=f"{config.model_id}:main_gross_scale{float(gross_scale_override):g}",
            )
        if kind not in {"fallback", "aux", "extra_aux"} and bool(sleeve_vol_weight):
            config = replace(config, vol_weight=True, model_id=f"{config.model_id}:main_vol_weight")
        if kind not in {"fallback", "aux", "extra_aux"} and int(sleeve_trend_hours) > 0:
            trend_hours = int(sleeve_trend_hours)
            config = replace(
                config,
                trend_hours=trend_hours,
                trend_bars=rot._hours_to_bars(config.interval, trend_hours),
                model_id=f"{config.model_id}:main_trend{trend_hours}h",
            )
        if kind in {"fallback", "aux", "extra_aux"}:
            if kind == "fallback":
                mode = str(fallback_mode)
                lookback_hours = int(fallback_lookback_hours)
                top_k = int(fallback_top_k)
                rebalance_hours = int(fallback_rebalance_hours)
                gross = float(fallback_gross)
                trend_hours = int(fallback_trend_hours)
            elif kind == "aux":
                mode = str(aux_mode)
                lookback_hours = int(aux_lookback_hours)
                top_k = int(aux_top_k)
                rebalance_hours = int(aux_rebalance_hours)
                gross = float(aux_gross)
                trend_hours = int(aux_trend_hours)
            else:
                mode = str(extra_aux_mode)
                lookback_hours = int(extra_aux_lookback_hours)
                top_k = int(extra_aux_top_k)
                rebalance_hours = int(extra_aux_rebalance_hours)
                gross = float(extra_aux_gross)
                trend_hours = int(extra_aux_trend_hours)
            config = replace(
                config,
                mode=mode,
                lookback_hours=lookback_hours,
                lookback_bars=rot._hours_to_bars(config.interval, lookback_hours),
                top_k=top_k,
                rebalance_hours=rebalance_hours,
                rebalance_bars=rot._hours_to_bars(config.interval, rebalance_hours),
                trend_hours=max(trend_hours, 0),
                trend_bars=rot._hours_to_bars(config.interval, trend_hours) if trend_hours > 0 else 0,
                vol_hours=max(168, lookback_hours),
                vol_bars=rot._hours_to_bars(config.interval, max(168, lookback_hours)),
                gross_leverage=gross,
                model_id=(
                    f"async:{kind}:{mode}:lb{lookback_hours}h:"
                    f"k{top_k}:rb{rebalance_hours}h:gross{gross:g}"
                ),
            )
        quality_bars = rot._hours_to_bars(config.interval, qlb) if qlb > 0 else 0
        sleeves.append(
            mixbt.Sleeve(
                name=f"{label + '_' if label else ''}{kind}_rb{rebalance_hours}_q{qth:g}",
                allocation=allocation,
                config=config,
                max_symbol_weight=cap,
                symbol_quality_lookback_hours=qlb,
                symbol_quality_drop_count=qdrop,
                symbol_quality_score_threshold=qth,
                weights={},
                dispersion_history=deque(maxlen=max(int(dispersion_lookback), 0)),
                quality_contribution_history={symbol: deque(maxlen=quality_bars) for symbol in frame.symbols},
                quality_exposure_history={symbol: deque(maxlen=quality_bars) for symbol in frame.symbols},
                quality_active_history={symbol: deque(maxlen=quality_bars) for symbol in frame.symbols},
                quality_block_counts=Counter(),
            )
        )
    return sleeves


def _is_fallback_sleeve(sleeve: mixbt.Sleeve) -> bool:
    return sleeve.name.startswith("fallback_")


def _is_aux_sleeve(sleeve: mixbt.Sleeve) -> bool:
    return sleeve.name.startswith("aux_") or sleeve.name.startswith("extra_aux_")


def _is_main_sleeve(sleeve: mixbt.Sleeve) -> bool:
    return not _is_fallback_sleeve(sleeve) and not _is_aux_sleeve(sleeve)


def _set_fallback_allocation(sleeves: list[mixbt.Sleeve], fallback_weight: float) -> None:
    fallback_weight = min(max(float(fallback_weight), 0.0), 1.0)
    fallback_sleeves = [sleeve for sleeve in sleeves if _is_fallback_sleeve(sleeve)]
    main_sleeves = [sleeve for sleeve in sleeves if not _is_fallback_sleeve(sleeve)]
    fallback_total = sum(sleeve.allocation for sleeve in fallback_sleeves)
    main_total = sum(sleeve.allocation for sleeve in main_sleeves)
    if fallback_sleeves:
        for sleeve in fallback_sleeves:
            sleeve.allocation = fallback_weight * (sleeve.allocation / fallback_total if fallback_total > 1e-12 else 1.0 / len(fallback_sleeves))
    if main_sleeves:
        for sleeve in main_sleeves:
            sleeve.allocation = (1.0 - fallback_weight) * (sleeve.allocation / main_total if main_total > 1e-12 else 1.0 / len(main_sleeves))


def _set_main_rb4_allocation(sleeves: list[mixbt.Sleeve], rb4_weight: float) -> None:
    rb4_weight = min(max(float(rb4_weight), 0.0), 1.0)
    main_sleeves = [sleeve for sleeve in sleeves if _is_main_sleeve(sleeve)]
    rb4_sleeves = [sleeve for sleeve in main_sleeves if "_rb4_" in sleeve.name]
    rb8_sleeves = [sleeve for sleeve in main_sleeves if "_rb8_" in sleeve.name]
    if not rb4_sleeves or not rb8_sleeves:
        return
    main_total = sum(sleeve.allocation for sleeve in main_sleeves)
    rb4_total = sum(sleeve.allocation for sleeve in rb4_sleeves)
    rb8_total = sum(sleeve.allocation for sleeve in rb8_sleeves)
    for sleeve in rb4_sleeves:
        sleeve.allocation = main_total * rb4_weight * (
            sleeve.allocation / rb4_total if rb4_total > 1e-12 else 1.0 / len(rb4_sleeves)
        )
    for sleeve in rb8_sleeves:
        sleeve.allocation = main_total * (1.0 - rb4_weight) * (
            sleeve.allocation / rb8_total if rb8_total > 1e-12 else 1.0 / len(rb8_sleeves)
        )


def _empty_summary(
    *,
    model_id: str,
    frame: rot.MarketFrame,
    sleeves: list[mixbt.Sleeve],
    values: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(values)
    by_month_start = dict(payload.pop("by_month_start", {}) or {})
    by_month_end = dict(payload.pop("by_month_end", {}) or {})
    by_quarter_start = dict(payload.pop("by_quarter_start", {}) or {})
    by_quarter_end = dict(payload.pop("by_quarter_end", {}) or {})
    return mixbt._summary(
        model_id=model_id,
        frame=frame,
        sleeves=sleeves,
        by_month_start=by_month_start,
        by_month_end=by_month_end,
        by_quarter_start=by_quarter_start,
        by_quarter_end=by_quarter_end,
        direction_periods=Counter(),
        symbol_contribution_sum={symbol: 0.0 for symbol in frame.symbols},
        symbol_abs_exposure_sum={symbol: 0.0 for symbol in frame.symbols},
        symbol_long_periods=Counter(),
        symbol_short_periods=Counter(),
        rebalance_samples=[],
        **payload,
    )


def _redistribute_sleeve_weights(
    *,
    sleeves: list[mixbt.Sleeve],
    old_sleeve_weights: list[tuple[mixbt.Sleeve, dict[str, float]]],
    pre_rule_sleeve_weights: list[tuple[mixbt.Sleeve, dict[str, float]]],
    target_weights: dict[str, float],
) -> None:
    pre_rule_total: dict[str, float] = {}
    old_total: dict[str, float] = {}
    for _, sleeve_weights in pre_rule_sleeve_weights:
        for symbol, weight in sleeve_weights.items():
            pre_rule_total[symbol] = pre_rule_total.get(symbol, 0.0) + weight
    for _, sleeve_weights in old_sleeve_weights:
        for symbol, weight in sleeve_weights.items():
            old_total[symbol] = old_total.get(symbol, 0.0) + weight
    old_by_sleeve = {id(sleeve): sleeve_weights for sleeve, sleeve_weights in old_sleeve_weights}
    symbols = set(target_weights) | set(pre_rule_total) | set(old_total)
    for sleeve, sleeve_weights in pre_rule_sleeve_weights:
        old_weights = old_by_sleeve.get(id(sleeve), {})
        effective: dict[str, float] = {}
        for symbol in symbols:
            sleeve_weight = sleeve_weights.get(symbol, 0.0)
            old_sleeve_weight = old_weights.get(symbol, 0.0)
            pre_total = pre_rule_total.get(symbol, 0.0)
            old_symbol_total = old_total.get(symbol, 0.0)
            final_weight = target_weights.get(symbol, 0.0)
            if abs(pre_total) <= 1e-12 or abs(final_weight) <= 1e-12:
                if abs(pre_total) > 1e-12 and abs(final_weight) > 1e-12:
                    value = final_weight * sleeve_weight / pre_total
                elif abs(old_symbol_total) > 1e-12 and abs(final_weight) > 1e-12:
                    value = final_weight * old_sleeve_weight / old_symbol_total
                else:
                    value = 0.0
            else:
                delta_total = pre_total - old_symbol_total
                if abs(delta_total) > 1e-12:
                    value = old_sleeve_weight + (final_weight - old_symbol_total) / delta_total * (sleeve_weight - old_sleeve_weight)
                else:
                    value = final_weight * sleeve_weight / pre_total
            if abs(value) > 1e-12:
                effective[symbol] = value
        sleeve.weights = effective


def _entry_signal_strength(
    frame: rot.MarketFrame,
    features: rot.FeatureBundle,
    config: rot.RotationPortfolioConfig,
    signal_idx: int,
    weights: dict[str, float],
) -> float:
    gross = sum(abs(value) for value in weights.values())
    if gross <= 1e-12:
        return math.nan
    mom_by_symbol = features.momentum.get(config.lookback_bars, {})
    raw = 0.0
    used = 0.0
    for symbol, weight in weights.items():
        series = mom_by_symbol.get(symbol)
        if not series or signal_idx >= len(series):
            continue
        momentum = series[signal_idx]
        if not math.isfinite(momentum):
            continue
        raw += abs(weight) * math.copysign(momentum, weight)
        used += abs(weight)
    if used <= 1e-12:
        return math.nan
    strength = raw / used
    dispersion = rot._cross_sectional_momentum_dispersion(frame, features, config, signal_idx)
    if math.isfinite(dispersion) and dispersion > 1e-9:
        strength /= dispersion
    return strength


def _entry_regime_strength(
    frame: rot.MarketFrame,
    features: rot.FeatureBundle,
    config: rot.RotationPortfolioConfig,
    signal_idx: int,
    weights: dict[str, float],
) -> float:
    gross = sum(abs(value) for value in weights.values())
    if gross <= 1e-12:
        return math.nan
    mom_by_symbol = features.momentum.get(config.lookback_bars, {})
    market_symbol = "BTCUSDT" if "BTCUSDT" in frame.symbols else frame.symbols[0]
    market_series = mom_by_symbol.get(market_symbol, [])
    if signal_idx >= len(market_series):
        return math.nan
    market_momentum = market_series[signal_idx]
    if not math.isfinite(market_momentum):
        return math.nan
    values = [
        series[signal_idx]
        for series in mom_by_symbol.values()
        if signal_idx < len(series) and math.isfinite(series[signal_idx])
    ]
    if values:
        breadth = sum(1 for value in values if value > 0.0) / len(values)
    else:
        breadth = 0.5
    net = sum(weights.values())
    if abs(net) <= 0.05:
        directional_edge = abs(market_momentum) + abs(breadth - 0.5)
    elif net > 0.0:
        directional_edge = market_momentum + max(breadth - 0.5, -0.5)
    else:
        directional_edge = -market_momentum + max(0.5 - breadth, -0.5)
    dispersion = rot._cross_sectional_momentum_dispersion(frame, features, config, signal_idx)
    if math.isfinite(dispersion) and dispersion > 1e-9:
        directional_edge /= dispersion
    return directional_edge


def _entry_grade_scale(
    *,
    history: deque[float],
    strength: float,
    low_quantile: float,
    high_quantile: float,
    min_scale: float,
    max_scale: float,
) -> float:
    if not math.isfinite(strength):
        return 1.0
    min_history = max(10, (history.maxlen or 0) // 2)
    if not history.maxlen or len(history) < min_history:
        history.append(strength)
        return 1.0
    low = rot._empirical_quantile(list(history), low_quantile)
    high = rot._empirical_quantile(list(history), high_quantile)
    history.append(strength)
    if not (math.isfinite(low) and math.isfinite(high)) or high <= low + 1e-12:
        return 1.0
    grade = min(max((strength - low) / (high - low), 0.0), 1.0)
    lo = max(float(min_scale), 0.0)
    hi = max(float(max_scale), 0.0)
    if hi < lo:
        lo, hi = hi, lo
    return lo + grade * (hi - lo)


def _market_stress_values(
    frame: rot.MarketFrame,
    features: rot.FeatureBundle,
    config: rot.RotationPortfolioConfig,
    signal_idx: int,
    args: argparse.Namespace,
) -> tuple[float, float]:
    mom_by_symbol = features.momentum.get(config.lookback_bars, {})
    values = [
        series[signal_idx]
        for series in mom_by_symbol.values()
        if signal_idx < len(series) and math.isfinite(series[signal_idx])
    ]
    breadth = sum(1 for value in values if value > 0.0) / len(values) if values else math.nan

    market_symbol = "BTCUSDT" if "BTCUSDT" in frame.symbols else frame.symbols[0]
    fast = max(int(getattr(args, "market_stress_btcema_fast", 21)), 1)
    slow = max(int(getattr(args, "market_stress_btcema_slow", 144)), fast + 1)
    fast_series = features.ema.get(fast, {}).get(market_symbol, [])
    slow_series = features.ema.get(slow, {}).get(market_symbol, [])
    btcema_spread = math.nan
    if signal_idx < len(fast_series) and signal_idx < len(slow_series):
        fast_value = fast_series[signal_idx]
        slow_value = slow_series[signal_idx]
        if math.isfinite(fast_value) and math.isfinite(slow_value) and slow_value > 0.0:
            btcema_spread = fast_value / slow_value - 1.0
    return breadth, btcema_spread


def _market_stress_scale(
    frame: rot.MarketFrame,
    features: rot.FeatureBundle,
    config: rot.RotationPortfolioConfig,
    signal_idx: int,
    weights: dict[str, float],
    args: argparse.Namespace,
) -> tuple[float, float, float, bool]:
    mode = str(getattr(args, "market_stress_mode", "off"))
    if mode == "off":
        return 1.0, math.nan, math.nan, False
    gross = sum(abs(value) for value in weights.values())
    if gross <= 1e-12:
        return 1.0, math.nan, math.nan, False
    net_ratio = sum(weights.values()) / gross
    if net_ratio <= float(getattr(args, "market_stress_min_net_ratio", 0.05)):
        return 1.0, math.nan, math.nan, False

    breadth, btcema_spread = _market_stress_values(frame, features, config, signal_idx, args)
    breadth_threshold = float(getattr(args, "market_stress_breadth_threshold", 0.35))
    btcema_threshold = float(getattr(args, "market_stress_btcema_threshold", 0.0))
    breadth_stress = math.isfinite(breadth) and breadth <= breadth_threshold
    btcema_stress = math.isfinite(btcema_spread) and btcema_spread <= btcema_threshold
    if mode == "breadth":
        stressed = breadth_stress
    elif mode == "btcema":
        stressed = btcema_stress
    else:
        stressed = breadth_stress and btcema_stress
    if not stressed:
        return 1.0, breadth, btcema_spread, False
    return max(float(getattr(args, "market_stress_risk_scale", 0.5)), 0.0), breadth, btcema_spread, True


def backtest_async_mix(
    frame: rot.MarketFrame,
    features: rot.FeatureBundle,
    sleeves: list[mixbt.Sleeve],
    *,
    args: argparse.Namespace,
    funding_period_rates: dict[str, list[float]] | None,
    exchange_rules: dict[str, rot.ExchangeRule],
) -> dict[str, Any]:
    cost = max(args.fee_bps_per_side + args.slippage_bps_per_side, 0.0) / 10_000.0
    warmup = max(max(sleeve.config.lookback_bars for sleeve in sleeves), 10) + 2
    first_exec_idx = warmup + 1
    last_exec_idx = len(frame.ts) - 2
    combined_weights: dict[str, float] = {}
    equity = peak = min_equity = 1.0
    max_dd = 0.0
    wins = losses = period_count = active_periods = 0
    turnover_sum = cost_drag = liquidity_impact_drag = holding_cost_drag = short_cost_drag = funding_pnl = 0.0
    gross_sum = net_sum = short_sum = 0.0
    max_trade_volume_pct_seen = max_capacity_cap_requested_trade_volume_pct = 0.0
    capacity_violation_count = capacity_cap_event_count = exchange_rule_adjustment_count = exchange_rule_drop_count = 0
    symbol_weight_cap_event_count = liquidation_event_count = 0
    worst_intrabar_adverse_return = 0.0
    first_exec_ts = last_period_ts = None
    by_year_start: dict[str, float] = {}
    by_year_end: dict[str, float] = {}
    by_month_start: dict[str, float] = {}
    by_month_end: dict[str, float] = {}
    by_quarter_start: dict[str, float] = {}
    by_quarter_end: dict[str, float] = {}
    realized_returns: deque[float] = deque(maxlen=rot._hours_to_bars(sleeves[0].config.interval, max(int(args.vol_lookback_hours), 1)))
    sleeve_anchor = {id(sleeve): first_exec_idx for sleeve in sleeves}
    entry_grade_histories = {
        id(sleeve): deque(maxlen=max(int(getattr(args, "entry_grade_lookback_rebalances", 0)), 0))
        for sleeve in sleeves
    }
    entry_grade_scale_sum = entry_grade_strength_sum = 0.0
    entry_grade_count = 0
    entry_grade_min_scale = math.inf
    entry_grade_max_scale = 0.0
    market_stress_count = market_stress_active_count = 0
    market_stress_scale_sum = market_stress_breadth_sum = market_stress_btcema_sum = 0.0
    market_stress_breadth_count = market_stress_btcema_count = 0
    current_fallback_weight = float(getattr(args, "fallback_weight", 0.0))
    current_rb4_weight = float(getattr(args, "rb4_weight", 0.0))
    drawdown_guard_active = False

    for exec_idx in range(first_exec_idx, last_exec_idx + 1):
        if first_exec_ts is None:
            first_exec_ts = frame.ts[exec_idx]
        signal_idx = exec_idx - 1
        old_sleeve_weights = [(sleeve, dict(sleeve.weights or {})) for sleeve in sleeves]
        changed = False
        force_rebalance = False
        live_drawdown = 1.0 - equity / max(peak, 1e-12)
        live_drawdown_pct = live_drawdown * 100.0
        drawdown_guard_pct = max(float(getattr(args, "drawdown_guard_pct", 0.0)), 0.0)
        recovery_pct = max(float(getattr(args, "drawdown_guard_recovery_pct", 0.0)), 0.0)
        if drawdown_guard_pct > 0.0:
            exit_pct = recovery_pct if 0.0 < recovery_pct < drawdown_guard_pct else drawdown_guard_pct
            if drawdown_guard_active and live_drawdown_pct <= exit_pct:
                drawdown_guard_active = False
            elif not drawdown_guard_active and live_drawdown_pct >= drawdown_guard_pct:
                drawdown_guard_active = True
        gate_pct = float(getattr(args, "fallback_drawdown_gate_pct", 0.0))
        high_weight = float(getattr(args, "fallback_drawdown_high_weight", -1.0))
        if gate_pct > 0.0 and high_weight >= 0.0:
            desired_fallback_weight = high_weight if live_drawdown * 100.0 >= gate_pct else float(getattr(args, "fallback_weight", 0.0))
            if abs(desired_fallback_weight - current_fallback_weight) > 1e-9:
                _set_fallback_allocation(sleeves, desired_fallback_weight)
                current_fallback_weight = desired_fallback_weight
                changed = True
                force_rebalance = True
        rb4_gate_pct = float(getattr(args, "rb4_drawdown_gate_pct", 0.0))
        rb4_gate_weight = float(getattr(args, "rb4_drawdown_gate_weight", -1.0))
        if rb4_gate_pct > 0.0 and rb4_gate_weight >= 0.0:
            desired_rb4_weight = rb4_gate_weight if live_drawdown * 100.0 >= rb4_gate_pct else float(getattr(args, "rb4_weight", 0.0))
            if abs(desired_rb4_weight - current_rb4_weight) > 1e-9:
                _set_main_rb4_allocation(sleeves, desired_rb4_weight)
                current_rb4_weight = desired_rb4_weight
                changed = True
                force_rebalance = True

        for sleeve in sleeves:
            if not force_rebalance and (exec_idx - sleeve_anchor[id(sleeve)]) % max(sleeve.config.rebalance_bars, 1) != 0:
                continue
            changed = True
            blocked_symbols: set[str] = set()
            if sleeve.symbol_quality_lookback_hours > 0 and sleeve.symbol_quality_drop_count > 0:
                blocked_symbols = rot._symbol_quality_blocklist(
                    frame,
                    contribution_history=sleeve.quality_contribution_history or {},
                    exposure_history=sleeve.quality_exposure_history or {},
                    active_history=sleeve.quality_active_history or {},
                    drop_count=sleeve.symbol_quality_drop_count,
                    min_active_periods=max(int(args.symbol_quality_min_active_periods), 0),
                    min_abs_exposure=max(float(args.symbol_quality_min_abs_exposure), 0.0),
                    score_threshold=sleeve.symbol_quality_score_threshold,
                )
                if blocked_symbols:
                    sleeve.quality_block_count += 1
                    sleeve.quality_block_symbol_events += len(blocked_symbols)
                    if sleeve.quality_block_counts is not None:
                        sleeve.quality_block_counts.update(blocked_symbols)

            new_weights = rot._target_weights(
                frame,
                features,
                sleeve.config,
                signal_idx,
                funding_period_rates=funding_period_rates,
                blocked_symbols=blocked_symbols,
            )
            risk_scale = 1.0
            live_drawdown = 1.0 - equity / max(peak, 1e-12)
            ramp_start = max(float(getattr(args, "drawdown_ramp_start_pct", 0.0)), 0.0)
            ramp_full = max(float(getattr(args, "drawdown_ramp_full_pct", 0.0)), 0.0)
            if ramp_start > 0.0 and ramp_full > ramp_start and live_drawdown * 100.0 >= ramp_start:
                ramp_progress = min(max((live_drawdown * 100.0 - ramp_start) / (ramp_full - ramp_start), 0.0), 1.0)
                ramp_min = max(float(getattr(args, "drawdown_ramp_risk_scale", 1.0)), 0.0)
                risk_scale *= 1.0 - ramp_progress * (1.0 - ramp_min)
            if drawdown_guard_pct > 0.0 and (drawdown_guard_active or live_drawdown * 100.0 >= drawdown_guard_pct):
                risk_scale *= max(float(args.drawdown_risk_scale), 0.0)
            if args.vol_target_annual_pct > 0.0 and len(realized_returns) >= max(10, realized_returns.maxlen // 2):
                mean_return = sum(realized_returns) / len(realized_returns)
                variance = sum((value - mean_return) * (value - mean_return) for value in realized_returns) / len(realized_returns)
                realized_vol = math.sqrt(max(variance, 0.0)) * math.sqrt(365.25 * 24.0 / max(rot._interval_hours(sleeve.config.interval), 1e-9))
                if realized_vol > 1e-9:
                    risk_scale *= min(max((args.vol_target_annual_pct / 100.0) / realized_vol, args.vol_min_scale), args.vol_max_scale)
            if args.downside_vol_target_annual_pct > 0.0 and len(realized_returns) >= max(10, realized_returns.maxlen // 2):
                downside_variance = sum(min(value, 0.0) * min(value, 0.0) for value in realized_returns) / len(realized_returns)
                downside_vol = math.sqrt(max(downside_variance, 0.0)) * math.sqrt(365.25 * 24.0 / max(rot._interval_hours(sleeve.config.interval), 1e-9))
                if downside_vol > 1e-9:
                    risk_scale *= min(max((args.downside_vol_target_annual_pct / 100.0) / downside_vol, args.vol_min_scale), args.vol_max_scale)
            dispersion = rot._cross_sectional_momentum_dispersion(frame, features, sleeve.config, signal_idx)
            history = sleeve.dispersion_history if sleeve.dispersion_history is not None else deque()
            if history.maxlen and math.isfinite(dispersion) and len(history) >= max(10, history.maxlen // 2) and args.dispersion_guard_quantile > 0.0:
                threshold = rot._empirical_quantile(list(history), args.dispersion_guard_quantile)
                if math.isfinite(threshold) and dispersion >= threshold:
                    risk_scale *= max(float(args.dispersion_risk_scale), 0.0)
            if history.maxlen and math.isfinite(dispersion):
                history.append(dispersion)
            entry_grade_mode = str(getattr(args, "entry_grade_mode", "off"))
            if entry_grade_mode != "off" and _is_main_sleeve(sleeve):
                if entry_grade_mode == "regime_quantile":
                    strength = _entry_regime_strength(frame, features, sleeve.config, signal_idx, new_weights)
                else:
                    strength = _entry_signal_strength(frame, features, sleeve.config, signal_idx, new_weights)
                grade_scale = _entry_grade_scale(
                    history=entry_grade_histories[id(sleeve)],
                    strength=strength,
                    low_quantile=float(getattr(args, "entry_grade_low_quantile", 0.25)),
                    high_quantile=float(getattr(args, "entry_grade_high_quantile", 0.75)),
                    min_scale=float(getattr(args, "entry_grade_min_scale", 0.35)),
                    max_scale=float(getattr(args, "entry_grade_max_scale", 1.0)),
                )
                risk_scale *= grade_scale
                if math.isfinite(strength):
                    entry_grade_strength_sum += strength
                entry_grade_scale_sum += grade_scale
                entry_grade_count += 1
                entry_grade_min_scale = min(entry_grade_min_scale, grade_scale)
                entry_grade_max_scale = max(entry_grade_max_scale, grade_scale)
            stress_scale, stress_breadth, stress_btcema, stress_active = _market_stress_scale(
                frame,
                features,
                sleeve.config,
                signal_idx,
                new_weights,
                args,
            )
            if str(getattr(args, "market_stress_mode", "off")) != "off":
                market_stress_count += 1
                market_stress_scale_sum += stress_scale
                if math.isfinite(stress_breadth):
                    market_stress_breadth_sum += stress_breadth
                    market_stress_breadth_count += 1
                if math.isfinite(stress_btcema):
                    market_stress_btcema_sum += stress_btcema
                    market_stress_btcema_count += 1
                if stress_active:
                    market_stress_active_count += 1
            risk_scale *= stress_scale
            new_weights = rot._scale_weights(new_weights, risk_scale)
            if sleeve.max_symbol_weight > 0.0:
                new_weights, cap_events = rot._clip_symbol_weights(new_weights, sleeve.max_symbol_weight)
                symbol_weight_cap_event_count += cap_events
            sleeve.weights = {symbol: weight * sleeve.allocation for symbol, weight in new_weights.items()}

        turnover = 0.0
        liquidity_cost_period = 0.0
        if changed:
            target_weights: dict[str, float] = {}
            for sleeve in sleeves:
                for symbol, weight in (sleeve.weights or {}).items():
                    target_weights[symbol] = target_weights.get(symbol, 0.0) + weight
            pre_rule_sleeve_weights = [(sleeve, dict(sleeve.weights or {})) for sleeve in sleeves]
            if args.capacity_cap_trade_volume_pct > 0.0:
                target_weights, cap_events, cap_requested_pct = rot._apply_capacity_cap(
                    frame,
                    old_weights=combined_weights,
                    new_weights=target_weights,
                    signal_idx=signal_idx,
                    equity=equity,
                    assumed_capital_usd=args.assumed_capital_usd,
                    max_trade_volume_pct=max(float(args.capacity_cap_trade_volume_pct), 0.0),
                    liquidity_notional_mode=args.liquidity_notional_mode,
                )
                capacity_cap_event_count += cap_events
                max_capacity_cap_requested_trade_volume_pct = max(max_capacity_cap_requested_trade_volume_pct, cap_requested_pct)
            if exchange_rules:
                target_weights, adjustments, drops = rot._apply_exchange_rules(
                    frame,
                    weights=target_weights,
                    signal_idx=signal_idx,
                    equity=equity,
                    assumed_capital_usd=args.assumed_capital_usd,
                    pnl_notional_mode=args.pnl_notional_mode,
                    exchange_rules=exchange_rules,
                )
                exchange_rule_adjustment_count += adjustments
                exchange_rule_drop_count += drops
            _redistribute_sleeve_weights(
                sleeves=sleeves,
                old_sleeve_weights=old_sleeve_weights,
                pre_rule_sleeve_weights=pre_rule_sleeve_weights,
                target_weights=target_weights,
            )
            turnover = rot._turnover(combined_weights, target_weights, frame.symbols)
            if turnover > 1e-9 and args.assumed_capital_usd > 0.0 and args.liquidity_impact_bps_per_1pct_volume > 0.0:
                for symbol in frame.symbols:
                    delta_weight = abs(target_weights.get(symbol, 0.0) - combined_weights.get(symbol, 0.0))
                    if delta_weight <= 1e-12:
                        continue
                    quote_volume = rot._quote_volume_at(frame, symbol, signal_idx)
                    if not math.isfinite(quote_volume) or quote_volume <= 0.0:
                        continue
                    trade_volume_pct = rot._trade_volume_pct_for_delta(
                        delta_weight=delta_weight,
                        equity=equity,
                        assumed_capital_usd=args.assumed_capital_usd,
                        quote_volume=quote_volume,
                        liquidity_notional_mode=args.liquidity_notional_mode,
                    )
                    max_trade_volume_pct_seen = max(max_trade_volume_pct_seen, trade_volume_pct)
                    if trade_volume_pct > max(float(args.max_trade_volume_pct), 0.0) * 1.01 + 1e-12:
                        capacity_violation_count += 1
                    liquidity_cost_period += (
                        delta_weight
                        * rot._execution_to_pnl_basis_multiplier(
                            equity=equity,
                            execution_notional_mode=args.liquidity_notional_mode,
                            pnl_notional_mode=args.pnl_notional_mode,
                        )
                        * args.liquidity_impact_bps_per_1pct_volume
                        * trade_volume_pct
                        / 10_000.0
                    )
            combined_weights = target_weights

        gross_exposure = sum(abs(value) for value in combined_weights.values())
        net_exposure = sum(combined_weights.values())
        short_exposure = sum(abs(value) for value in combined_weights.values() if value < 0.0)
        gross_sum += gross_exposure
        net_sum += net_exposure
        short_sum += short_exposure
        turnover_sum += turnover
        cost_period = turnover * cost
        cost_drag += cost_period
        liquidity_impact_drag += liquidity_cost_period
        period_days = max((frame.ts[exec_idx + 1] - frame.ts[exec_idx]).total_seconds() / 86_400, 0.0)
        holding_cost_period = gross_exposure * max(float(args.holding_cost_bps_per_day), 0.0) / 10_000.0 * period_days
        short_cost_period = short_exposure * max(float(args.short_cost_bps_per_day), 0.0) / 10_000.0 * period_days
        holding_cost_drag += holding_cost_period
        short_cost_drag += short_cost_period
        funding_period = rot._funding_return_for_period_index(funding_period_rates, combined_weights, exec_idx) if funding_period_rates is not None else 0.0
        funding_pnl += funding_period
        intrabar_adverse_return = rot._basis_return_to_equity_return(
            rot._intrabar_adverse_return(frame, combined_weights, exec_idx),
            equity=equity,
            pnl_notional_mode=args.pnl_notional_mode,
        )
        worst_intrabar_adverse_return = min(worst_intrabar_adverse_return, intrabar_adverse_return)
        if args.maintenance_margin_pct > 0.0 and intrabar_adverse_return <= -(1.0 - args.maintenance_margin_pct / 100.0):
            liquidation_event_count += 1

        portfolio_return = 0.0
        period_symbol_contribution: dict[str, float] = {}
        for symbol, weight in combined_weights.items():
            symbol_return = frame.returns[symbol][exec_idx]
            if not math.isfinite(symbol_return):
                continue
            contribution = weight * symbol_return
            portfolio_return += contribution
            period_symbol_contribution[symbol] = period_symbol_contribution.get(symbol, 0.0) + contribution

        for sleeve in sleeves:
            if sleeve.symbol_quality_lookback_hours <= 0:
                continue
            sleeve_weights = sleeve.weights or {}
            for symbol in frame.symbols:
                weight = sleeve_weights.get(symbol, 0.0)
                combined_weight = combined_weights.get(symbol, 0.0)
                if abs(combined_weight) > 1e-12 and symbol in period_symbol_contribution:
                    contribution = period_symbol_contribution[symbol] * weight / combined_weight
                    abs_exposure = abs(weight)
                else:
                    contribution = 0.0
                    abs_exposure = 0.0
                if sleeve.quality_contribution_history is not None:
                    sleeve.quality_contribution_history[symbol].append(contribution)
                if sleeve.quality_exposure_history is not None:
                    sleeve.quality_exposure_history[symbol].append(abs_exposure)
                if sleeve.quality_active_history is not None:
                    sleeve.quality_active_history[symbol].append(1 if abs_exposure > 1e-12 else 0)

        net_return = rot._basis_return_to_equity_return(
            portfolio_return + funding_period - cost_period - liquidity_cost_period - holding_cost_period - short_cost_period,
            equity=equity,
            pnl_notional_mode=args.pnl_notional_mode,
        )
        if gross_exposure > 1e-9:
            active_periods += 1
        year = str(frame.ts[exec_idx + 1].year)
        month = frame.ts[exec_idx + 1].strftime("%Y-%m")
        quarter = f"{frame.ts[exec_idx + 1].year}Q{((frame.ts[exec_idx + 1].month - 1) // 3) + 1}"
        by_year_start.setdefault(year, equity)
        by_month_start.setdefault(month, equity)
        by_quarter_start.setdefault(quarter, equity)
        equity = 1e-9 if net_return <= -0.999 else equity * (1.0 + net_return)
        by_year_end[year] = equity
        by_month_end[month] = equity
        by_quarter_end[quarter] = equity
        peak = max(peak, equity)
        min_equity = min(min_equity, equity)
        max_dd = max(max_dd, 1.0 - equity / max(peak, 1e-12))
        if net_return > 0.0:
            wins += 1
        elif net_return < 0.0:
            losses += 1
        realized_returns.append(net_return)
        period_count += 1
        last_period_ts = frame.ts[exec_idx + 1]

    return _empty_summary(
        model_id=(
            f"async_rb4w{args.rb4_weight:g}_rb8w{1.0 - args.rb4_weight:g}"
            f"_fallbackw{getattr(args, 'fallback_weight', 0.0):g}"
            f"_auxw{getattr(args, 'aux_weight', 0.0):g}"
            f"_xauxw{getattr(args, 'extra_aux_weight', 0.0):g}"
            f"_secw{getattr(args, 'secondary_main_weight', 0.0):g}"
        ),
        frame=frame,
        sleeves=sleeves,
        values={
            "first_exec_ts": first_exec_ts,
            "last_period_ts": last_period_ts,
            "equity": equity,
            "peak": peak,
            "min_equity": min_equity,
            "wins": wins,
            "losses": losses,
            "period_count": period_count,
            "active_periods": active_periods,
            "turnover_sum": turnover_sum,
            "cost_drag": cost_drag,
            "liquidity_impact_drag": liquidity_impact_drag,
            "holding_cost_drag": holding_cost_drag,
            "short_cost_drag": short_cost_drag,
            "funding_pnl": funding_pnl,
            "gross_sum": gross_sum,
            "net_sum": net_sum,
            "short_sum": short_sum,
            "max_dd": max_dd,
            "worst_intrabar_adverse_return": worst_intrabar_adverse_return,
            "liquidation_event_count": liquidation_event_count,
            "max_trade_volume_pct_seen": max_trade_volume_pct_seen,
            "capacity_violation_count": capacity_violation_count,
            "capacity_cap_event_count": capacity_cap_event_count,
            "max_capacity_cap_requested_trade_volume_pct": max_capacity_cap_requested_trade_volume_pct,
            "exchange_rule_adjustment_count": exchange_rule_adjustment_count,
            "exchange_rule_drop_count": exchange_rule_drop_count,
            "symbol_weight_cap_event_count": symbol_weight_cap_event_count,
            "entry_grade_count": entry_grade_count,
            "entry_grade_avg_scale": entry_grade_scale_sum / max(entry_grade_count, 1),
            "entry_grade_min_scale_seen": entry_grade_min_scale if math.isfinite(entry_grade_min_scale) else 1.0,
            "entry_grade_max_scale_seen": entry_grade_max_scale if entry_grade_count else 1.0,
            "entry_grade_avg_strength": entry_grade_strength_sum / max(entry_grade_count, 1),
            "market_stress_count": market_stress_count,
            "market_stress_active_count": market_stress_active_count,
            "market_stress_avg_scale": market_stress_scale_sum / max(market_stress_count, 1),
            "market_stress_avg_breadth": market_stress_breadth_sum / max(market_stress_breadth_count, 1),
            "market_stress_avg_btcema": market_stress_btcema_sum / max(market_stress_btcema_count, 1),
            "by_year_start": by_year_start,
            "by_year_end": by_year_end,
            "by_month_start": by_month_start,
            "by_month_end": by_month_end,
            "by_quarter_start": by_quarter_start,
            "by_quarter_end": by_quarter_end,
        },
    )


def _scenario_defs(args: argparse.Namespace, all_symbols: list[str]) -> list[tuple[str, list[str], dict[str, Any]]]:
    screen = [
        ("base", all_symbols, {}),
        ("tradecap010", all_symbols, {"max_trade_volume_pct": 0.10, "capacity_cap_trade_volume_pct": 0.10}),
        ("slip10", all_symbols, {"slippage_bps_per_side": 10.0}),
        ("capital2m", all_symbols, {"assumed_capital_usd": 2_000_000.0}),
        ("ex_top7", _symbols_excluding(all_symbols, 7), {}),
        ("ex_top10", _symbols_excluding(all_symbols, 10), {}),
    ]
    if args.include_ex_top15:
        screen.append(("ex_top15", _symbols_excluding(all_symbols, 15), {}))
    if args.scenario_set == "screen":
        scenarios = screen
    else:
        scenarios = [
            ("base", all_symbols, {}),
            ("tradecap025", all_symbols, {"max_trade_volume_pct": 0.25, "capacity_cap_trade_volume_pct": 0.25}),
            ("slip6", all_symbols, {"slippage_bps_per_side": 6.0}),
            ("capital1m", all_symbols, {"assumed_capital_usd": 1_000_000.0}),
            ("shortcost5", all_symbols, {"short_cost_bps_per_day": 5.0}),
            ("ex_top3", _symbols_excluding(all_symbols, 3), {}),
            ("ex_top5", _symbols_excluding(all_symbols, 5), {}),
            *screen[1:],
            ("shortcost10", all_symbols, {"short_cost_bps_per_day": 10.0}),
        ]
    if args.include_extreme_scenarios:
        scenarios.extend(
            [
                ("tradecap005", all_symbols, {"max_trade_volume_pct": 0.05, "capacity_cap_trade_volume_pct": 0.05}),
                ("slip15", all_symbols, {"slippage_bps_per_side": 15.0}),
                ("fee8", all_symbols, {"fee_bps_per_side": 8.0}),
                ("capital5m", all_symbols, {"assumed_capital_usd": 5_000_000.0}),
                (
                    "slip15_capital2m",
                    all_symbols,
                    {"slippage_bps_per_side": 15.0, "assumed_capital_usd": 2_000_000.0},
                ),
                (
                    "tradecap005_slip10",
                    all_symbols,
                    {
                        "max_trade_volume_pct": 0.05,
                        "capacity_cap_trade_volume_pct": 0.05,
                        "slippage_bps_per_side": 10.0,
                    },
                ),
            ]
        )
    labels = {item.strip() for item in str(args.scenario_labels or "").split(",") if item.strip()}
    if labels:
        scenarios = [scenario for scenario in scenarios if scenario[0] in labels]
    if not scenarios:
        raise ValueError("scenario filter removed all scenarios")
    return scenarios


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    base_url = str(args.base_url or settings.binance_rest_base_url or "https://fapi.binance.com").rstrip("/")
    all_symbols = [symbol.upper() for symbol in rot._csv(args.symbols)]
    scenarios = _scenario_defs(args, all_symbols)
    weights = _float_csv(args.rb4_weights)
    fallback_weights = _float_csv(args.fallback_weights)
    aux_weights = _float_csv(args.aux_weights)
    extra_aux_weights = _float_csv(args.extra_aux_weights)

    bars_by_symbol = {
        symbol: rot._load_bars(
            symbol=symbol,
            interval=args.interval,
            days=max(int(args.days), 30),
            cache_dir=ROOT_DIR / str(args.cache_dir),
            base_url=base_url,
            sleep_seconds=0.0,
        )
        for symbol in all_symbols
    }
    drop_last_bars = max(int(args.drop_last_bars), 0)
    if drop_last_bars:
        bars_by_symbol = {
            symbol: bars[:-drop_last_bars] if len(bars) > drop_last_bars else []
            for symbol, bars in bars_by_symbol.items()
        }
    exchange_rules = rot._load_exchange_rules(
        base_url=base_url,
        cache_path=ROOT_DIR / str(args.exchange_rules_cache),
    )
    prepared: dict[str, tuple[rot.MarketFrame, dict[str, list[float]], dict[str, Any]]] = {}
    for _, symbols, _ in scenarios:
        key = ",".join(symbols)
        if key in prepared:
            continue
        frame, status = rot._align_dynamic_frame(args.interval, {symbol: bars_by_symbol[symbol] for symbol in symbols})
        if frame is None:
            raise RuntimeError(f"failed to align frame: {status}")
        funding_cache_dir = ROOT_DIR / str(args.funding_cache_dir)
        funding_rates = {
            symbol: rot._load_funding_rates(
                symbol=symbol,
                start_ms=int(frame.open_ms[0]),
                end_ms=int(frame.open_ms[-1]),
                cache_dir=funding_cache_dir,
                base_url=base_url,
                sleep_seconds=0.0,
            )
            for symbol in frame.symbols
        }
        prepared[key] = (frame, rot._build_funding_period_rates(frame, funding_rates), status)

    results: list[dict[str, Any]] = []
    for aux_weight in aux_weights:
        for extra_aux_weight in extra_aux_weights:
            for fallback_weight in fallback_weights:
                if fallback_weight + aux_weight + extra_aux_weight > 1.0 + 1e-12:
                    continue
                for rb4_weight in weights:
                    rows: list[dict[str, Any]] = []
                    for label, symbols, overrides in scenarios:
                        frame, funding_period_rates, _ = prepared[",".join(symbols)]
                        run_args = argparse.Namespace(**{**vars(args), **overrides})
                        run_args.rb4_weight = rb4_weight
                        run_args.fallback_weight = fallback_weight
                        run_args.aux_weight = aux_weight
                        run_args.extra_aux_weight = extra_aux_weight
                        sleeves = _build_sleeves(
                            frame,
                            interval=str(args.interval),
                            rb4_weight=rb4_weight,
                            fallback_weight=fallback_weight,
                            aux_weight=aux_weight,
                            extra_aux_weight=extra_aux_weight,
                            fallback_mode=str(args.fallback_mode),
                            fallback_lookback_hours=int(args.fallback_lookback_hours),
                            fallback_top_k=int(args.fallback_top_k),
                            fallback_rebalance_hours=int(args.fallback_rebalance_hours),
                            fallback_gross=float(args.fallback_gross),
                            aux_mode=str(args.aux_mode),
                            aux_lookback_hours=int(args.aux_lookback_hours),
                            aux_top_k=int(args.aux_top_k),
                            aux_rebalance_hours=int(args.aux_rebalance_hours),
                            aux_gross=float(args.aux_gross),
                            extra_aux_mode=str(args.extra_aux_mode),
                            extra_aux_lookback_hours=int(args.extra_aux_lookback_hours),
                            extra_aux_top_k=int(args.extra_aux_top_k),
                            extra_aux_rebalance_hours=int(args.extra_aux_rebalance_hours),
                            extra_aux_gross=float(args.extra_aux_gross),
                            main_fast_rebalance_hours=int(args.main_fast_rebalance_hours),
                            main_slow_rebalance_hours=int(args.main_slow_rebalance_hours),
                            main_lookback_hours=int(args.main_lookback_hours),
                            main_top_k=int(args.main_top_k),
                            main_gross_scale=float(args.main_gross_scale),
                            secondary_main_weight=float(args.secondary_main_weight),
                            secondary_main_mode=str(args.secondary_main_mode),
                            secondary_main_gross_scale=float(args.secondary_main_gross_scale),
                            secondary_main_lookback_hours=int(args.secondary_main_lookback_hours),
                            secondary_main_top_k=int(args.secondary_main_top_k),
                            secondary_main_fast_rebalance_hours=int(args.secondary_main_fast_rebalance_hours),
                            secondary_main_slow_rebalance_hours=int(args.secondary_main_slow_rebalance_hours),
                            secondary_main_vol_weight=bool(args.secondary_main_vol_weight),
                            main_vol_weight=bool(args.main_vol_weight),
                            main_max_symbol_weight=float(args.main_max_symbol_weight),
                            fallback_max_symbol_weight=float(args.fallback_max_symbol_weight),
                            aux_max_symbol_weight=float(args.aux_max_symbol_weight),
                            extra_aux_max_symbol_weight=float(args.extra_aux_max_symbol_weight),
                            main_trend_hours=int(args.main_trend_hours),
                            fallback_trend_hours=int(args.fallback_trend_hours),
                            aux_trend_hours=int(args.aux_trend_hours),
                            extra_aux_trend_hours=int(args.extra_aux_trend_hours),
                            main_mode=str(args.main_mode),
                            rb4_quality_threshold=float(args.rb4_quality_threshold),
                            rb8_quality_threshold=float(args.rb8_quality_threshold),
                            dispersion_lookback=int(args.dispersion_lookback_rebalances),
                        )
                        feature_configs = [sleeve.config for sleeve in sleeves]
                        if str(args.market_stress_mode) in {"btcema", "btcema_breadth"} and feature_configs:
                            fast = max(int(args.market_stress_btcema_fast), 1)
                            slow = max(int(args.market_stress_btcema_slow), fast + 1)
                            feature_configs.append(replace(feature_configs[0], mode=f"{feature_configs[0].mode}_btcema{fast}x{slow}"))
                        features = rot._build_features(frame, feature_configs)
                        summary = backtest_async_mix(
                            frame,
                            features,
                            sleeves,
                            args=run_args,
                            funding_period_rates=funding_period_rates,
                            exchange_rules=exchange_rules,
                        )
                        rows.append(
                            {
                                "label": label,
                                "x": round(1.0 + summary["total_return_pct"] / 100.0, 6),
                                "max_dd_pct": summary["max_drawdown_pct"],
                                "worst_year_pct": summary["worst_year_pct"],
                                "positive_year_fraction": summary.get("positive_year_fraction"),
                                "avg_daily_turnover": summary.get("avg_daily_turnover"),
                                "cost_drag_pct_simple_sum": summary.get("cost_drag_pct_simple_sum"),
                                "liquidity_impact_drag_pct_simple_sum": summary.get("liquidity_impact_drag_pct_simple_sum"),
                                "funding_pnl_pct_simple_sum": summary.get("funding_pnl_pct_simple_sum"),
                                "max_trade_volume_pct_seen": summary.get("max_trade_volume_pct_seen"),
                                "entry_grade_avg_scale": summary.get("entry_grade_avg_scale"),
                                "entry_grade_min_scale_seen": summary.get("entry_grade_min_scale_seen"),
                                "market_stress_active_fraction": summary.get("market_stress_active_fraction"),
                                "market_stress_avg_scale": summary.get("market_stress_avg_scale"),
                                "by_year_return_pct": summary.get("by_year_return_pct"),
                                "by_quarter_return_pct": summary.get("by_quarter_return_pct"),
                                "by_month_return_pct": summary.get("by_month_return_pct"),
                            }
                        )
                    result = {
                        "mix": (
                            f"async_rb4w{rb4_weight:g}_rb8w{1.0 - rb4_weight:g}"
                            f"_fallbackw{fallback_weight:g}_auxw{aux_weight:g}"
                            f"_xauxw{extra_aux_weight:g}"
                            f"_secw{float(args.secondary_main_weight):g}"
                        ),
                        "rb4_weight": rb4_weight,
                        "fallback_weight": fallback_weight,
                        "aux_weight": aux_weight,
                        "extra_aux_weight": extra_aux_weight,
                        "secondary_main_weight": float(args.secondary_main_weight),
                        "geo": math.prod(max(row["x"], 1e-12) for row in rows) ** (1.0 / len(rows)),
                        "min_x": min(row["x"] for row in rows),
                        "max_dd_pct": max(row["max_dd_pct"] for row in rows),
                        "min_worst_year_pct": min(row["worst_year_pct"] for row in rows),
                        "rows": rows,
                    }
                    results.append(result)
                    print(json.dumps({key: (round(value, 4) if isinstance(value, float) else value) for key, value in result.items() if key != "rows"}, ensure_ascii=False), flush=True)

    results.sort(key=lambda row: (row["geo"], row["min_x"], -row["max_dd_pct"], row["min_worst_year_pct"]), reverse=True)
    output = {
        "schema_version": "multi_asset_rotation_async_mix_scan_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "authority": "research_only_no_live_authority_change",
        "scenario_set": args.scenario_set,
        "scenario_labels": [label for label, _, _ in scenarios],
        "quality_thresholds": {
            "rb4": float(args.rb4_quality_threshold),
            "rb8": float(args.rb8_quality_threshold),
        },
        "top_excluded_order": list(TOP_EXCLUDED_ORDER),
        "data_end_utc": prepared[",".join(scenarios[0][1])][2].get("last_ts"),
        "results": results,
    }
    if args.write_report:
        report_dir = ROOT_DIR / str(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = report_dir / f"multi_asset_rotation_async_mix_scan_{stamp}.json"
        latest = report_dir / "latest.json"
        output["report_path"] = str(path.relative_to(ROOT_DIR))
        output["latest_report_path"] = str(latest.relative_to(ROOT_DIR))
        text = json.dumps(output, ensure_ascii=False, indent=2)
        atomic_write_text(path, text)
        atomic_write_text(latest, text)
    print(json.dumps({key: value for key, value in output.items() if key != "results"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
