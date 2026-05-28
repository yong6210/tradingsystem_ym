#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text
from scripts import run_external_strategy_zoo as ext
from scripts import run_multi_asset_rotation_search as rot


SYMBOLS_36 = ext.SYMBOLS_36
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
MODE_5050 = "residual80_funding20_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_5050"


@dataclass(frozen=True, slots=True)
class SleeveSpec:
    name: str
    kind: str
    allocation: float
    max_symbol_weight: float
    internal_config: rot.RotationPortfolioConfig | None = None
    external_config: ext.ExternalStrategyConfig | None = None
    base_name: str = ""


@dataclass(slots=True)
class SleeveState:
    spec: SleeveSpec
    weights: dict[str, float]
    state: dict[str, Any]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only hybrid internal/external strategy mix scan.")
    parser.add_argument("--symbols", default=SYMBOLS_36)
    parser.add_argument("--days", type=int, default=1825)
    parser.add_argument("--interval", default="4h")
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
    parser.add_argument(
        "--drawdown-ladder",
        default="",
        help="Optional comma-separated drawdown scale ladder, e.g. 5:0.75,10:0.25,15:0.10",
    )
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
    parser.add_argument("--evaluation-start", default="")
    parser.add_argument("--evaluation-end", default="")
    parser.add_argument("--max-mixes", type=int, default=0)
    parser.add_argument(
        "--candidate-set",
        choices=(
            "broad",
            "focus",
            "optimal",
            "cost_aware",
            "adaptive",
            "adaptive_overlay",
            "finalists",
            "vwap_family",
            "weak_sleeve",
            "weak_sleeve_finalists",
            "all",
        ),
        default="broad",
    )
    parser.add_argument("--report-dir", default="reports/validation/hybrid_strategy_mix_search")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _hours_to_bars(interval: str, hours: int) -> int:
    return rot._hours_to_bars(interval, max(int(hours), 1))


def _internal_config(name: str, interval: str) -> rot.RotationPortfolioConfig:
    presets: dict[str, tuple[str, int, int, int, int, float, bool]] = {
        "fallback6040": (MODE_6040, 336, 1, 48, 2160, 2.5, False),
        "res70_k2": ("residual70_funding30", 336, 2, 12, 2160, 2.0, False),
        "res70_k3": ("residual70_funding30", 336, 3, 12, 2160, 2.0, False),
        "res80_cash_k3": ("residual80_funding20_btc_cash", 336, 3, 8, 2160, 3.0, False),
        "blend6040_k3": (MODE_6040, 336, 3, 8, 2160, 5.8, False),
        "blend5050_k3": (MODE_5050, 336, 3, 8, 2160, 5.8, False),
        "blend6040_q": (MODE_6040, 336, 3, 8, 2160, 6.4, False),
        "res70_k3_slow": ("residual70_funding30", 720, 3, 48, 2160, 2.0, False),
        "res70_k3_week": ("residual70_funding30", 720, 3, 72, 2160, 2.0, False),
        "fallback6040_slow": (MODE_6040, 720, 1, 72, 2160, 2.5, False),
        "blend5050_k3_slow": (MODE_5050, 720, 3, 48, 2160, 4.0, False),
    }
    mode, lookback, top_k, rebalance, age, gross, vol_weight = presets[name]
    return rot.RotationPortfolioConfig(
        model_id=f"hybrid_internal:{name}:{mode}:lb{lookback}h:k{top_k}:rb{rebalance}h:gross{gross:g}",
        interval=interval,
        mode=mode,
        lookback_hours=lookback,
        lookback_bars=_hours_to_bars(interval, lookback),
        top_k=top_k,
        rebalance_hours=rebalance,
        rebalance_bars=_hours_to_bars(interval, rebalance),
        trend_hours=0,
        trend_bars=0,
        vol_weight=vol_weight,
        vol_hours=lookback,
        vol_bars=_hours_to_bars(interval, lookback),
        min_symbol_age_hours=age,
        min_symbol_age_bars=_hours_to_bars(interval, age),
        gross_leverage=gross,
    )


def _external_config(name: str, interval: str) -> ext.ExternalStrategyConfig:
    presets: dict[str, tuple[str, int, int, int, int, int, int, float, bool, int]] = {
        "vwap2_k6": ("vwap_breakout_xs", 1200, 72, 72, 720, 24, 6, 2.0, True, 1440),
        "vwap15_k4": ("vwap_breakout_xs", 1200, 72, 72, 720, 24, 4, 1.5, True, 1440),
        "vwap12_k4": ("vwap_breakout_xs", 1200, 72, 72, 720, 24, 4, 1.2, True, 1440),
        "vwap_g3_lb720_k1": ("vwap_breakout_xs", 720, 336, 168, 336, 24, 1, 3.0, False, 1440),
        "vwap_g3_lb720_k2": ("vwap_breakout_xs", 720, 336, 168, 336, 24, 2, 3.0, False, 1440),
        "vwap_g3_lb1200_k1": ("vwap_breakout_xs", 1200, 336, 168, 336, 24, 1, 3.0, False, 1440),
        "vwap_g3_lb1200_k2": ("vwap_breakout_xs", 1200, 336, 168, 336, 24, 2, 3.0, False, 1440),
        "vwap_g2_lb720_k1": ("vwap_breakout_xs", 720, 336, 168, 336, 24, 1, 2.0, False, 1440),
        "vwap_g2_lb1200_k2": ("vwap_breakout_xs", 1200, 336, 168, 336, 24, 2, 2.0, False, 1440),
        "donchian_g15_lb1200_k6": ("donchian_xs_long", 1200, 168, 168, 336, 24, 6, 1.5, True, 1440),
        "score15_k4": ("scorecard_breakout", 1200, 72, 168, 1200, 24, 4, 1.5, True, 1440),
        "score12_k4": ("scorecard_breakout", 1200, 72, 168, 720, 24, 4, 1.2, True, 1440),
        "score15_k6": ("scorecard_breakout", 1200, 72, 168, 720, 24, 6, 1.5, True, 1440),
        "donchian12_k6": ("donchian_xs_long", 1200, 168, 168, 720, 24, 6, 1.2, True, 1440),
        "donchian15_k6": ("donchian_xs_long", 1200, 168, 168, 720, 24, 6, 1.5, True, 1440),
        "vwap2_k6_slow": ("vwap_breakout_xs", 1200, 168, 168, 1200, 72, 6, 2.0, True, 1440),
        "vwap15_k4_slow": ("vwap_breakout_xs", 1200, 168, 168, 1200, 72, 4, 1.5, True, 1440),
        "score15_k4_slow": ("scorecard_breakout", 1200, 168, 168, 1200, 72, 4, 1.5, True, 1440),
        "score15_k6_slow": ("scorecard_breakout", 1200, 168, 168, 1200, 72, 6, 1.5, True, 1440),
        "donchian15_k6_slow": ("donchian_xs_long", 1200, 336, 168, 1200, 72, 6, 1.5, True, 1440),
        "ratio_mom_k4_slow": ("ratio_momentum_btc", 1200, 336, 168, 1200, 72, 4, 1.2, True, 1440),
        "bbmr10_k4": ("bb_rsi_mr", 720, 72, 72, 720, 24, 4, 1.0, True, 1440),
        "bbmr12_k4": ("bb_rsi_mr", 720, 168, 72, 720, 24, 4, 1.2, True, 1440),
        "bbmr10_k6_slow": ("bb_rsi_mr", 1200, 168, 168, 1200, 72, 6, 1.0, True, 1440),
        "ratio_rev08_k4": ("ratio_reversal_btc", 720, 168, 72, 720, 24, 4, 0.8, False, 1440),
        "ratio_rev10_k4_slow": ("ratio_reversal_btc", 1200, 168, 168, 1200, 72, 4, 1.0, False, 1440),
        "ratio_rev12_k6_slow": ("ratio_reversal_btc", 1200, 336, 168, 1200, 72, 6, 1.2, False, 1440),
        "btc_sma08": ("btc_sma_long", 1200, 168, 168, 1200, 24, 1, 0.8, False, 1440),
        "btc_sma12_slow": ("btc_sma_long", 2160, 336, 168, 2160, 72, 1, 1.2, False, 1440),
        "btc_sma_flip08": ("btc_sma_flip", 1200, 168, 168, 1200, 24, 1, 0.8, False, 1440),
        "supertrend_btc08": ("supertrend_btc_long", 720, 72, 72, 720, 24, 1, 0.8, False, 1440),
        "stochsuper_btc08": ("stochrsi_supertrend_btc", 720, 72, 72, 720, 24, 1, 0.8, False, 1440),
        "macd_btc08": ("macd_adx_btc", 720, 72, 72, 720, 24, 1, 0.8, False, 1440),
    }
    mode, lookback, exit_hours, fast, slow, rebalance, top_k, gross, vol_weight, age = presets[name]
    model_id = (
        f"{interval}:{mode}:lb{lookback}h:exit{exit_hours}h:fast{fast}h:slow{slow}h:"
        f"k{top_k}:rb{rebalance}h:volw{int(vol_weight)}:age{age}h:gross{gross:g}"
    )
    return ext.ExternalStrategyConfig(
        model_id=model_id,
        interval=interval,
        mode=mode,
        lookback_hours=lookback,
        lookback_bars=_hours_to_bars(interval, lookback),
        exit_hours=exit_hours,
        exit_bars=_hours_to_bars(interval, exit_hours),
        fast_hours=fast,
        fast_bars=_hours_to_bars(interval, fast),
        slow_hours=slow,
        slow_bars=_hours_to_bars(interval, slow),
        rebalance_hours=rebalance,
        rebalance_bars=_hours_to_bars(interval, rebalance),
        top_k=top_k,
        gross_leverage=gross,
        vol_weight=vol_weight,
        min_symbol_age_hours=age,
        min_symbol_age_bars=_hours_to_bars(interval, age),
    )


def _make_spec(name: str, allocation: float, interval: str) -> SleeveSpec:
    internal_names = {
        "fallback6040",
        "res70_k2",
        "res70_k3",
        "res80_cash_k3",
        "blend6040_k3",
        "blend5050_k3",
        "blend6040_q",
        "res70_k3_slow",
        "res70_k3_week",
        "fallback6040_slow",
        "blend5050_k3_slow",
    }
    if name in internal_names:
        return SleeveSpec(
            name=name,
            kind="internal",
            allocation=float(allocation),
            max_symbol_weight=0.725,
            internal_config=_internal_config(name, interval),
            base_name=name,
        )
    return SleeveSpec(
        name=name,
        kind="external",
        allocation=float(allocation),
        max_symbol_weight=0.75,
        external_config=_external_config(name, interval),
        base_name=name,
    )


def _alias_spec(alias: str, base_name: str, allocation: float, interval: str) -> SleeveSpec:
    base = _make_spec(base_name, allocation, interval)
    return SleeveSpec(
        name=alias,
        kind=base.kind,
        allocation=base.allocation,
        max_symbol_weight=base.max_symbol_weight,
        internal_config=base.internal_config,
        external_config=base.external_config,
        base_name=base_name,
    )


def _base_name(spec: SleeveSpec) -> str:
    return spec.base_name or spec.name


def _mix_id(specs: list[SleeveSpec]) -> str:
    return "hybrid:" + ",".join(f"{spec.name}:{spec.allocation:.3f}" for spec in specs)


def _candidate_mixes(interval: str) -> list[list[SleeveSpec]]:
    internal = ["res70_k2", "res70_k3", "res80_cash_k3", "blend6040_k3", "blend5050_k3", "fallback6040"]
    external = ["vwap2_k6", "vwap15_k4", "score15_k4", "score12_k4", "score15_k6", "donchian12_k6"]
    mixes: list[list[SleeveSpec]] = []

    for name in internal + external:
        mixes.append([_make_spec(name, 1.0, interval)])

    for left in internal:
        for right in external:
            for left_weight in (0.50, 0.60, 0.70, 0.80, 0.90):
                mixes.append([
                    _make_spec(left, left_weight, interval),
                    _make_spec(right, 1.0 - left_weight, interval),
                ])

    for left in ("res70_k2", "res80_cash_k3", "blend6040_k3", "blend5050_k3"):
        for vwap in ("vwap2_k6", "vwap15_k4"):
            for third in ("score15_k4", "score12_k4", "donchian12_k6"):
                for weights in ((0.60, 0.25, 0.15), (0.70, 0.20, 0.10), (0.50, 0.30, 0.20), (0.80, 0.15, 0.05)):
                    mixes.append([
                        _make_spec(left, weights[0], interval),
                        _make_spec(vwap, weights[1], interval),
                        _make_spec(third, weights[2], interval),
                    ])

    seen: set[str] = set()
    unique: list[list[SleeveSpec]] = []
    for mix in mixes:
        key = _mix_id(mix)
        if key not in seen:
            seen.add(key)
            unique.append(mix)
    return unique


def _focused_candidate_mixes(interval: str) -> list[list[SleeveSpec]]:
    mixes: list[list[SleeveSpec]] = []

    pair_axes = (
        ("blend5050_k3", "score15_k6"),
        ("res70_k3", "vwap2_k6"),
        ("fallback6040", "vwap2_k6"),
        ("res70_k2", "score15_k6"),
        ("res80_cash_k3", "vwap2_k6"),
        ("blend6040_k3", "score12_k4"),
        ("blend5050_k3", "score15_k4"),
    )
    for left, right in pair_axes:
        for left_weight in (0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75):
            mixes.append([
                _make_spec(left, left_weight, interval),
                _make_spec(right, 1.0 - left_weight, interval),
            ])

    triple_axes = (
        ("blend5050_k3", "vwap2_k6", "score15_k6"),
        ("blend5050_k3", "vwap15_k4", "score15_k6"),
        ("res70_k3", "vwap2_k6", "score15_k4"),
        ("res70_k3", "vwap2_k6", "score15_k6"),
        ("res80_cash_k3", "vwap2_k6", "score12_k4"),
        ("fallback6040", "vwap2_k6", "score15_k4"),
    )
    weight_grid = (
        (0.40, 0.40, 0.20),
        (0.45, 0.35, 0.20),
        (0.50, 0.30, 0.20),
        (0.55, 0.25, 0.20),
        (0.60, 0.20, 0.20),
        (0.45, 0.25, 0.30),
        (0.50, 0.20, 0.30),
        (0.55, 0.15, 0.30),
        (0.35, 0.35, 0.30),
    )
    for left, middle, right in triple_axes:
        for weights in weight_grid:
            mixes.append([
                _make_spec(left, weights[0], interval),
                _make_spec(middle, weights[1], interval),
                _make_spec(right, weights[2], interval),
            ])

    stacked_axes = (
        ("blend5050_k3", "res70_k3", "score15_k6"),
        ("blend5050_k3", "res70_k3", "vwap2_k6"),
        ("blend6040_k3", "res70_k3", "score15_k6"),
        ("res80_cash_k3", "res70_k3", "vwap2_k6"),
        ("fallback6040", "res70_k3", "vwap2_k6"),
    )
    stacked_weights = (
        (0.45, 0.25, 0.30),
        (0.40, 0.30, 0.30),
        (0.35, 0.35, 0.30),
        (0.50, 0.25, 0.25),
        (0.55, 0.20, 0.25),
    )
    for first, second, third in stacked_axes:
        for weights in stacked_weights:
            mixes.append([
                _make_spec(first, weights[0], interval),
                _make_spec(second, weights[1], interval),
                _make_spec(third, weights[2], interval),
            ])

    seen: set[str] = set()
    unique: list[list[SleeveSpec]] = []
    for mix in mixes:
        key = _mix_id(mix)
        if key not in seen:
            seen.add(key)
            unique.append(mix)
    return unique


def _dedupe_mixes(mixes: list[list[SleeveSpec]]) -> list[list[SleeveSpec]]:
    seen: set[str] = set()
    unique: list[list[SleeveSpec]] = []
    for mix in mixes:
        key = _mix_id(mix)
        if key not in seen:
            seen.add(key)
            unique.append(mix)
    return unique


def _optimal_candidate_mixes(interval: str) -> list[list[SleeveSpec]]:
    mixes: list[list[SleeveSpec]] = []

    def add_pair(left: str, right: str, weights: list[float]) -> None:
        for left_weight in weights:
            right_weight = 1.0 - left_weight
            if left_weight <= 0.0 or right_weight <= 0.0:
                continue
            mixes.append([
                _make_spec(left, left_weight, interval),
                _make_spec(right, right_weight, interval),
            ])

    def add_triple(names: tuple[str, str, str], grids: tuple[list[float], list[float]], bounds: tuple[float, float]) -> None:
        third_min, third_max = bounds
        for first_weight in grids[0]:
            for second_weight in grids[1]:
                third_weight = 1.0 - first_weight - second_weight
                if third_min <= third_weight <= third_max:
                    mixes.append([
                        _make_spec(names[0], first_weight, interval),
                        _make_spec(names[1], second_weight, interval),
                        _make_spec(names[2], third_weight, interval),
                    ])

    def add_quad(names: tuple[str, str, str, str], firsts: list[float], seconds: list[float], thirds: list[float], bounds: tuple[float, float]) -> None:
        fourth_min, fourth_max = bounds
        for first_weight in firsts:
            for second_weight in seconds:
                for third_weight in thirds:
                    fourth_weight = 1.0 - first_weight - second_weight - third_weight
                    if fourth_min <= fourth_weight <= fourth_max:
                        mixes.append([
                            _make_spec(names[0], first_weight, interval),
                            _make_spec(names[1], second_weight, interval),
                            _make_spec(names[2], third_weight, interval),
                            _make_spec(names[3], fourth_weight, interval),
                        ])

    pair_fine = [value / 100.0 for value in range(25, 76, 2)]
    add_pair("fallback6040", "vwap2_k6", pair_fine)
    add_pair("res70_k3", "vwap2_k6", [value / 100.0 for value in range(35, 66, 2)])
    add_pair("blend5050_k3", "score15_k6", [value / 100.0 for value in range(30, 71, 2)])
    add_pair("blend5050_k3", "score15_k4", [value / 100.0 for value in range(30, 61, 2)])

    blend_grid = [value / 100.0 for value in range(30, 66, 5)]
    vwap_grid = [value / 100.0 for value in range(5, 41, 5)]
    fallback_grid = [value / 100.0 for value in range(25, 56, 5)]
    residual_grid = [value / 100.0 for value in range(20, 61, 5)]
    score_grid = [value / 100.0 for value in range(10, 51, 5)]

    add_triple(("blend5050_k3", "vwap2_k6", "score15_k6"), (blend_grid, vwap_grid), (0.15, 0.55))
    add_triple(("blend5050_k3", "vwap2_k6", "score15_k4"), (blend_grid, vwap_grid), (0.15, 0.55))
    add_triple(("blend5050_k3", "vwap15_k4", "score15_k6"), (blend_grid, vwap_grid), (0.15, 0.55))
    add_triple(("fallback6040", "vwap2_k6", "score15_k4"), (fallback_grid, vwap_grid), (0.10, 0.45))
    add_triple(("fallback6040", "vwap2_k6", "score15_k6"), (fallback_grid, vwap_grid), (0.10, 0.45))
    add_triple(("res70_k3", "vwap2_k6", "score15_k6"), (residual_grid, vwap_grid), (0.10, 0.45))
    add_triple(("res70_k3", "vwap2_k6", "score15_k4"), (residual_grid, vwap_grid), (0.10, 0.45))
    add_triple(("blend6040_k3", "res70_k3", "score15_k6"), (blend_grid, residual_grid), (0.10, 0.45))
    add_triple(("blend5050_k3", "res70_k3", "score15_k6"), (blend_grid, residual_grid), (0.10, 0.45))

    add_quad(
        ("blend5050_k3", "res70_k3", "vwap2_k6", "score15_k6"),
        [value / 100.0 for value in range(25, 56, 5)],
        [value / 100.0 for value in range(10, 36, 5)],
        [value / 100.0 for value in range(10, 36, 5)],
        (0.10, 0.45),
    )
    add_quad(
        ("blend5050_k3", "fallback6040", "vwap2_k6", "score15_k6"),
        [value / 100.0 for value in range(20, 51, 5)],
        [value / 100.0 for value in range(10, 36, 5)],
        [value / 100.0 for value in range(10, 46, 5)],
        (0.10, 0.45),
    )
    add_quad(
        ("blend6040_k3", "res70_k3", "vwap2_k6", "score15_k6"),
        [value / 100.0 for value in range(25, 56, 5)],
        [value / 100.0 for value in range(10, 36, 5)],
        [value / 100.0 for value in range(10, 36, 5)],
        (0.10, 0.45),
    )
    add_quad(
        ("fallback6040", "res70_k3", "vwap2_k6", "score15_k4"),
        [value / 100.0 for value in range(20, 51, 5)],
        [value / 100.0 for value in range(10, 36, 5)],
        [value / 100.0 for value in range(15, 51, 5)],
        (0.05, 0.35),
    )

    return _dedupe_mixes(mixes)


def _cost_aware_candidate_mixes(interval: str) -> list[list[SleeveSpec]]:
    mixes: list[list[SleeveSpec]] = []

    internal = ("res70_k3_slow", "res70_k3_week", "fallback6040_slow", "blend5050_k3_slow")
    external = (
        "vwap2_k6_slow",
        "vwap15_k4_slow",
        "score15_k4_slow",
        "score15_k6_slow",
        "donchian15_k6_slow",
        "ratio_mom_k4_slow",
    )

    for name in internal + external:
        mixes.append([_make_spec(name, 1.0, interval)])

    pair_weights = [value / 100.0 for value in range(30, 76, 5)]
    for left in internal:
        for right in external:
            for left_weight in pair_weights:
                mixes.append([
                    _make_spec(left, left_weight, interval),
                    _make_spec(right, 1.0 - left_weight, interval),
                ])

    slow_pairs = (
        ("res70_k3_slow", "vwap2_k6_slow"),
        ("res70_k3_week", "vwap2_k6_slow"),
        ("res70_k3_slow", "score15_k4_slow"),
        ("fallback6040_slow", "vwap2_k6_slow"),
        ("blend5050_k3_slow", "score15_k6_slow"),
        ("blend5050_k3_slow", "score15_k4_slow"),
    )
    for left, right in slow_pairs:
        for left_weight in [value / 100.0 for value in range(35, 76, 2)]:
            mixes.append([
                _make_spec(left, left_weight, interval),
                _make_spec(right, 1.0 - left_weight, interval),
            ])

    triple_specs = (
        ("res70_k3_slow", "vwap2_k6_slow", "score15_k4_slow"),
        ("res70_k3_week", "vwap2_k6_slow", "score15_k4_slow"),
        ("fallback6040_slow", "vwap2_k6_slow", "score15_k4_slow"),
        ("blend5050_k3_slow", "vwap2_k6_slow", "score15_k6_slow"),
        ("res70_k3_slow", "donchian15_k6_slow", "score15_k4_slow"),
        ("res70_k3_slow", "vwap15_k4_slow", "ratio_mom_k4_slow"),
    )
    for names in triple_specs:
        for first in [value / 100.0 for value in range(35, 71, 5)]:
            for second in [value / 100.0 for value in range(15, 51, 5)]:
                third = round(1.0 - first - second, 10)
                if 0.10 <= third <= 0.45:
                    mixes.append([
                        _make_spec(names[0], first, interval),
                        _make_spec(names[1], second, interval),
                        _make_spec(names[2], third, interval),
                    ])

    quad_specs = (
        ("res70_k3_slow", "fallback6040_slow", "vwap2_k6_slow", "score15_k4_slow"),
        ("res70_k3_slow", "blend5050_k3_slow", "vwap2_k6_slow", "score15_k6_slow"),
    )
    for names in quad_specs:
        for first in [value / 100.0 for value in range(25, 56, 5)]:
            for second in [value / 100.0 for value in range(10, 36, 5)]:
                for third in [value / 100.0 for value in range(10, 36, 5)]:
                    fourth = round(1.0 - first - second - third, 10)
                    if 0.10 <= fourth <= 0.40:
                        mixes.append([
                            _make_spec(names[0], first, interval),
                            _make_spec(names[1], second, interval),
                            _make_spec(names[2], third, interval),
                            _make_spec(names[3], fourth, interval),
                        ])

    return _dedupe_mixes(mixes)


def _vwap_family_candidate_mixes(interval: str) -> list[list[SleeveSpec]]:
    mixes: list[list[SleeveSpec]] = []
    g3_core = (
        "vwap_g3_lb720_k1",
        "vwap_g3_lb720_k2",
        "vwap_g3_lb1200_k1",
        "vwap_g3_lb1200_k2",
    )
    g2_core = ("vwap_g2_lb720_k1", "vwap_g2_lb1200_k2")
    stabilizers = ("donchian_g15_lb1200_k6", "score15_k4")

    for name in g3_core + g2_core + stabilizers:
        mixes.append([_make_spec(name, 1.0, interval)])

    mixes.append([_make_spec("vwap_g3_lb720_k1", 0.50, interval), _make_spec("vwap_g3_lb1200_k2", 0.50, interval)])
    mixes.append([_make_spec("vwap_g3_lb720_k1", 0.50, interval), _make_spec("vwap_g3_lb720_k2", 0.50, interval)])
    mixes.append([_make_spec("vwap_g3_lb1200_k1", 0.50, interval), _make_spec("vwap_g3_lb1200_k2", 0.50, interval)])
    mixes.append([_make_spec("vwap_g2_lb720_k1", 0.50, interval), _make_spec("vwap_g2_lb1200_k2", 0.50, interval)])
    mixes.append([_make_spec(name, 0.25, interval) for name in g3_core])
    mixes.append([
        _make_spec("vwap_g3_lb720_k1", 0.35, interval),
        _make_spec("vwap_g3_lb1200_k2", 0.35, interval),
        _make_spec("donchian_g15_lb1200_k6", 0.30, interval),
    ])
    mixes.append([
        _make_spec("vwap_g3_lb720_k1", 0.30, interval),
        _make_spec("vwap_g3_lb1200_k2", 0.30, interval),
        _make_spec("donchian_g15_lb1200_k6", 0.20, interval),
        _make_spec("score15_k4", 0.20, interval),
    ])
    mixes.append([
        _make_spec("vwap_g2_lb720_k1", 0.35, interval),
        _make_spec("vwap_g2_lb1200_k2", 0.35, interval),
        _make_spec("donchian_g15_lb1200_k6", 0.30, interval),
    ])
    return _dedupe_mixes(mixes)


ADAPTIVE_RISK_PROFILES: dict[str, dict[str, float]] = {
    "ag45": {"blend5050_k3": 0.45, "res70_k3": 0.25, "vwap2_k6": 0.10, "score15_k6": 0.20},
    "ag25": {"blend5050_k3": 0.25, "fallback6040": 0.25, "vwap2_k6": 0.20, "score15_k6": 0.30},
    "ag42": {"blend5050_k3": 0.42, "score15_k4": 0.58},
    "ov15": {"res70_k3": 0.5275, "vwap2_k6": 0.5250, "blend5050_k3": 0.0675, "score15_k6": 0.0300},
    "ov25": {"res70_k3": 0.5525, "vwap2_k6": 0.5350, "blend5050_k3": 0.1125, "score15_k6": 0.0500},
    "ov25s": {"res70_k3": 0.4900, "vwap2_k6": 0.5100, "blend5050_k3": 0.1050, "score15_k4": 0.1450},
    "ov35": {"res70_k3": 0.5775, "vwap2_k6": 0.5450, "blend5050_k3": 0.1575, "score15_k6": 0.0700},
}
ADAPTIVE_NEUTRAL_PROFILE = {"res70_k3": 0.49, "vwap2_k6": 0.51}
ADAPTIVE_DEFENSIVE_PROFILE = {"res70_k3": 0.65, "vwap2_k6": 0.35}


def _adaptive_candidate_mixes(interval: str, *, profile_prefix: str = "") -> list[list[SleeveSpec]]:
    mixes: list[list[SleeveSpec]] = []
    for profile_name, risk_profile in ADAPTIVE_RISK_PROFILES.items():
        if profile_prefix and not profile_name.startswith(profile_prefix):
            continue
        sleeve_names = list(dict.fromkeys(
            list(ADAPTIVE_DEFENSIVE_PROFILE)
            + list(ADAPTIVE_NEUTRAL_PROFILE)
            + list(risk_profile)
        ))
        drawdown_grid = (8, 12, 16, 99) if profile_name.startswith("ov") else (8, 12, 16)
        for momentum_pct in (0, 5, 10, 15):
            for drawdown_pct in drawdown_grid:
                for require_breadth in (0, 1):
                    alias = f"adapt_{profile_name}_mom{momentum_pct}_dd{drawdown_pct}_br{require_breadth}_{sleeve_names[0]}"
                    specs: list[SleeveSpec] = []
                    for idx, base_name in enumerate(sleeve_names):
                        allocation = ADAPTIVE_NEUTRAL_PROFILE.get(base_name, 0.0)
                        if idx == 0:
                            specs.append(_alias_spec(alias, base_name, allocation, interval))
                        else:
                            specs.append(_make_spec(base_name, allocation, interval))
                    mixes.append(specs)
    return _dedupe_mixes(mixes)


def _finalist_candidate_mixes(interval: str) -> list[list[SleeveSpec]]:
    raw_mixes = (
        (("fallback6040", 0.20), ("res70_k3", 0.15), ("vwap2_k6", 0.40), ("score15_k4", 0.25)),
        (("fallback6040", 0.25), ("res70_k3", 0.15), ("vwap2_k6", 0.35), ("score15_k4", 0.25)),
        (("fallback6040", 0.20), ("res70_k3", 0.20), ("vwap2_k6", 0.35), ("score15_k4", 0.25)),
        (("fallback6040", 0.20), ("res70_k3", 0.30), ("vwap2_k6", 0.40), ("score15_k4", 0.10)),
        (("fallback6040", 0.25), ("res70_k3", 0.20), ("vwap2_k6", 0.35), ("score15_k4", 0.20)),
        (("fallback6040", 0.35), ("res70_k3", 0.25), ("vwap2_k6", 0.25), ("score15_k4", 0.15)),
        (("fallback6040", 0.40), ("vwap2_k6", 0.60)),
        (("fallback6040", 0.45), ("vwap2_k6", 0.55)),
        (("res70_k3", 0.49), ("vwap2_k6", 0.51)),
        (("res70_k3", 0.50), ("vwap2_k6", 0.50)),
        (("res70_k3", 0.51), ("vwap2_k6", 0.49)),
        (("res70_k3", 0.65), ("vwap2_k6", 0.35)),
        (("blend5050_k3", 0.25), ("fallback6040", 0.25), ("vwap2_k6", 0.20), ("score15_k6", 0.30)),
        (("blend5050_k3", 0.45), ("res70_k3", 0.25), ("vwap2_k6", 0.10), ("score15_k6", 0.20)),
        (("blend5050_k3", 0.40), ("res70_k3", 0.20), ("score15_k6", 0.40)),
        (("blend5050_k3", 0.45), ("res70_k3", 0.20), ("score15_k6", 0.35)),
        (("blend5050_k3", 0.44), ("res70_k3", 0.18), ("score15_k6", 0.38)),
        (("blend5050_k3", 0.42), ("res70_k3", 0.18), ("score15_k6", 0.40)),
        (("res70_k3", 0.50), ("vwap2_k6", 0.15), ("score15_k4", 0.35)),
        (("blend6040_k3", 0.55), ("res70_k3", 0.20), ("score15_k6", 0.25)),
        (("blend5050_k3", 0.50), ("vwap2_k6", 0.20), ("score15_k6", 0.30)),
        (("blend5050_k3", 0.42), ("score15_k4", 0.58)),
        (("blend5050_k3", 0.36), ("score15_k4", 0.64)),
    )
    return _dedupe_mixes([
        [_make_spec(name, allocation, interval) for name, allocation in raw_mix]
        for raw_mix in raw_mixes
    ])


def _weak_sleeve_candidate_mixes(interval: str) -> list[list[SleeveSpec]]:
    core = (
        ("blend5050_k3", 0.44),
        ("res70_k3", 0.18),
        ("score15_k6", 0.38),
    )
    sleeve_names = (
        "bbmr10_k4",
        "bbmr12_k4",
        "bbmr10_k6_slow",
        "ratio_rev08_k4",
        "ratio_rev10_k4_slow",
        "ratio_rev12_k6_slow",
        "btc_sma08",
        "btc_sma12_slow",
        "btc_sma_flip08",
        "supertrend_btc08",
        "stochsuper_btc08",
        "macd_btc08",
    )
    raw_mixes: list[tuple[tuple[str, float], ...]] = [core]
    for sleeve_name in sleeve_names:
        sleeve_allocation = 0.10
        scale = 1.0 - sleeve_allocation
        raw_mixes.append(
            tuple((name, allocation * scale) for name, allocation in core)
            + ((sleeve_name, sleeve_allocation),)
        )
    for sleeve_name in sleeve_names:
        for sleeve_allocation in (0.05, 0.15, 0.20):
            scale = 1.0 - sleeve_allocation
            raw_mixes.append(
                tuple((name, allocation * scale) for name, allocation in core)
                + ((sleeve_name, sleeve_allocation),)
            )

    pair_names = (
        ("bbmr12_k4", "ratio_rev10_k4_slow"),
        ("bbmr12_k4", "btc_sma08"),
        ("ratio_rev10_k4_slow", "btc_sma08"),
        ("ratio_rev10_k4_slow", "supertrend_btc08"),
        ("bbmr10_k6_slow", "stochsuper_btc08"),
        ("btc_sma08", "supertrend_btc08"),
    )
    for left, right in pair_names:
        for sleeve_allocation in (0.10, 0.15, 0.20):
            scale = 1.0 - sleeve_allocation
            half = sleeve_allocation / 2.0
            raw_mixes.append(
                tuple((name, allocation * scale) for name, allocation in core)
                + ((left, half), (right, half))
            )

    return _dedupe_mixes([
        [_make_spec(name, allocation, interval) for name, allocation in raw_mix]
        for raw_mix in raw_mixes
    ])


def _weak_sleeve_finalist_mixes(interval: str) -> list[list[SleeveSpec]]:
    core = (
        ("blend5050_k3", 0.44),
        ("res70_k3", 0.18),
        ("score15_k6", 0.38),
    )
    overlays = (
        ("btc_sma12_slow", 0.03),
        ("btc_sma12_slow", 0.04),
        ("btc_sma12_slow", 0.045),
        ("btc_sma12_slow", 0.05),
        ("btc_sma12_slow", 0.055),
        ("btc_sma12_slow", 0.06),
        ("btc_sma12_slow", 0.075),
        ("btc_sma12_slow", 0.10),
        ("btc_sma12_slow", 0.15),
        ("btc_sma12_slow", 0.20),
        ("supertrend_btc08", 0.03),
        ("supertrend_btc08", 0.05),
        ("supertrend_btc08", 0.075),
        ("supertrend_btc08", 0.10),
        ("stochsuper_btc08", 0.03),
        ("stochsuper_btc08", 0.05),
        ("stochsuper_btc08", 0.075),
        ("stochsuper_btc08", 0.10),
        ("stochsuper_btc08", 0.20),
        ("macd_btc08", 0.05),
        ("macd_btc08", 0.10),
        ("ratio_rev08_k4", 0.025),
        ("ratio_rev08_k4", 0.05),
        ("ratio_rev12_k6_slow", 0.05),
    )
    raw_mixes: list[tuple[tuple[str, float], ...]] = [core]
    for sleeve_name, sleeve_allocation in overlays:
        scale = 1.0 - sleeve_allocation
        raw_mixes.append(
            tuple((name, allocation * scale) for name, allocation in core)
            + ((sleeve_name, sleeve_allocation),)
        )
    return _dedupe_mixes([
        [_make_spec(name, allocation, interval) for name, allocation in raw_mix]
        for raw_mix in raw_mixes
    ])


def _period_returns(starts: dict[str, float], ends: dict[str, float]) -> dict[str, float]:
    return {key: ends[key] / max(starts.get(key, 1.0), 1e-12) - 1.0 for key in sorted(ends)}


def _blend_weights(
    old_weights: dict[str, float],
    new_weights: dict[str, float],
    symbols: list[str],
    fraction: float,
) -> dict[str, float]:
    fraction = min(max(float(fraction), 0.0), 1.0)
    if fraction >= 0.999999:
        return dict(new_weights)
    if fraction <= 1e-12:
        return dict(old_weights)
    blended: dict[str, float] = {}
    for symbol in symbols:
        value = old_weights.get(symbol, 0.0) + (new_weights.get(symbol, 0.0) - old_weights.get(symbol, 0.0)) * fraction
        if abs(value) > 1e-12:
            blended[symbol] = value
    return blended


def _entry_gated_weights(
    target_weights: dict[str, float],
    sleeve_contributions: list[tuple[SleeveSpec, float, dict[str, float]]],
    args: argparse.Namespace,
) -> tuple[dict[str, float], dict[str, float]]:
    mode = str(args.entry_gate_mode or "none")
    if mode == "none" or not target_weights:
        return target_weights, {"gate_events": 0.0, "removed_abs_weight": 0.0}

    sleeve_threshold = max(float(args.entry_gate_sleeve_threshold), 0.0)
    min_abs_weight = max(float(args.entry_gate_min_abs_weight), 0.0)
    min_agree = max(int(args.entry_gate_min_agree), 1)
    survivors: dict[str, float] = {}
    removed_abs_weight = 0.0

    external_names = {
        "vwap2_k6",
        "vwap15_k4",
        "vwap12_k4",
        "score15_k4",
        "score12_k4",
        "score15_k6",
        "donchian12_k6",
        "donchian15_k6",
    }
    for symbol, target in target_weights.items():
        if abs(target) <= 1e-12:
            continue
        side = 1.0 if target > 0.0 else -1.0
        same_side = 0
        external_same_side = False
        for spec, allocation, weights in sleeve_contributions:
            contribution = weights.get(symbol, 0.0) * allocation
            if abs(contribution) < sleeve_threshold:
                continue
            if contribution * side > 0.0:
                same_side += 1
                if spec.kind == "external" or _base_name(spec) in external_names:
                    external_same_side = True

        if mode == "graded_agreement":
            if same_side >= min_agree:
                scale = 1.0
            elif same_side >= max(min_agree - 1, 1):
                scale = 0.55
            elif external_same_side or abs(target) >= min_abs_weight:
                scale = 0.35
            else:
                scale = 0.15
            adjusted = target * scale
            if abs(adjusted) > 1e-12:
                survivors[symbol] = adjusted
            removed_abs_weight += max(abs(target) - abs(adjusted), 0.0)
            continue

        if mode == "graded_external":
            if external_same_side and (same_side >= min_agree or abs(target) >= min_abs_weight):
                scale = 1.0
            elif same_side >= min_agree:
                scale = 0.75
            elif external_same_side:
                scale = 0.50
            elif same_side > 0 and abs(target) >= min_abs_weight:
                scale = 0.35
            else:
                scale = 0.15
            adjusted = target * scale
            if abs(adjusted) > 1e-12:
                survivors[symbol] = adjusted
            removed_abs_weight += max(abs(target) - abs(adjusted), 0.0)
            continue

        keep = False
        if mode == "agreement":
            keep = same_side >= min_agree
        elif mode == "external_confirm":
            keep = external_same_side and (same_side >= min_agree or abs(target) >= min_abs_weight)
        elif mode == "net_weight":
            keep = abs(target) >= min_abs_weight
        if keep:
            survivors[symbol] = target
        else:
            removed_abs_weight += abs(target)

    if not survivors:
        return {}, {"gate_events": 1.0, "removed_abs_weight": removed_abs_weight}

    if bool(args.entry_gate_rescale_survivors):
        old_gross = sum(abs(value) for value in target_weights.values())
        new_gross = sum(abs(value) for value in survivors.values())
        if old_gross > 1e-12 and new_gross > 1e-12:
            scale = old_gross / new_gross
            survivors = {symbol: value * scale for symbol, value in survivors.items()}
    return survivors, {
        "gate_events": 1.0 if removed_abs_weight > 1e-12 else 0.0,
        "removed_abs_weight": removed_abs_weight,
    }


DISPERSION_MOMENTUM_SLEEVES = {
    "fallback6040",
    "fallback6040_slow",
    "blend6040_k3",
    "blend6040_q",
    "blend5050_k3",
    "blend5050_k3_slow",
    "score15_k4",
    "score12_k4",
    "score15_k6",
    "score15_k4_slow",
    "score15_k6_slow",
    "donchian12_k6",
    "donchian15_k6",
    "donchian15_k6_slow",
    "ratio_mom_k4_slow",
}


def _cross_sectional_return_dispersion(
    frame: rot.MarketFrame,
    signal_idx: int,
    lookback_bars: int,
    min_symbols: int,
) -> float:
    if lookback_bars <= 0 or signal_idx < lookback_bars:
        return math.nan
    values: list[float] = []
    past_idx = signal_idx - lookback_bars
    for symbol in frame.symbols:
        current = frame.closes[symbol][signal_idx]
        past = frame.closes[symbol][past_idx]
        if math.isfinite(current) and math.isfinite(past) and past > 0.0:
            values.append(current / past - 1.0)
    if len(values) < max(int(min_symbols), 2):
        return math.nan
    mean_value = sum(values) / len(values)
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    return math.sqrt(max(variance, 0.0))


def _market_gate_scale(
    frame: rot.MarketFrame,
    signal_idx: int,
    args: argparse.Namespace,
) -> tuple[float, dict[str, float]]:
    mode = str(getattr(args, "market_gate_mode", "none") or "none")
    if mode == "none":
        return 1.0, {"gate": 0.0, "momentum": math.nan, "breadth_pct": math.nan}
    lookback_bars = rot._hours_to_bars(args.interval, max(int(args.market_gate_lookback_hours), 1))
    if signal_idx < lookback_bars:
        return 1.0, {"gate": 0.0, "momentum": math.nan, "breadth_pct": math.nan}
    threshold = float(args.market_gate_threshold_pct) / 100.0
    gate_scale = max(float(args.market_gate_risk_scale), 0.0)
    if mode in {"btc_momentum", "btc_momentum_or_abs"}:
        symbol = "BTCUSDT" if "BTCUSDT" in frame.symbols else frame.symbols[0]
        current = frame.closes[symbol][signal_idx]
        past = frame.closes[symbol][signal_idx - lookback_bars]
        if not (math.isfinite(current) and math.isfinite(past) and past > 0.0):
            return 1.0, {"gate": 0.0, "momentum": math.nan, "breadth_pct": math.nan}
        momentum = current / past - 1.0
        abs_threshold = abs(float(getattr(args, "market_gate_abs_threshold_pct", 0.0) or 0.0)) / 100.0
        if momentum < threshold or (mode == "btc_momentum_or_abs" and abs_threshold > 0.0 and abs(momentum) < abs_threshold):
            return gate_scale, {"gate": 1.0, "momentum": momentum, "breadth_pct": math.nan}
        return 1.0, {"gate": 0.0, "momentum": momentum, "breadth_pct": math.nan}
    if mode == "btc_abs_momentum":
        symbol = "BTCUSDT" if "BTCUSDT" in frame.symbols else frame.symbols[0]
        current = frame.closes[symbol][signal_idx]
        past = frame.closes[symbol][signal_idx - lookback_bars]
        if not (math.isfinite(current) and math.isfinite(past) and past > 0.0):
            return 1.0, {"gate": 0.0, "momentum": math.nan, "breadth_pct": math.nan}
        momentum = current / past - 1.0
        abs_threshold = abs(float(getattr(args, "market_gate_abs_threshold_pct", 0.0) or 0.0)) / 100.0
        if abs_threshold <= 0.0:
            abs_threshold = abs(threshold)
        if abs(momentum) < abs_threshold:
            return gate_scale, {"gate": 1.0, "momentum": momentum, "breadth_pct": math.nan}
        return 1.0, {"gate": 0.0, "momentum": momentum, "breadth_pct": math.nan}

    positive = total = 0
    for symbol in frame.symbols:
        current = frame.closes[symbol][signal_idx]
        past = frame.closes[symbol][signal_idx - lookback_bars]
        if not (math.isfinite(current) and math.isfinite(past) and past > 0.0):
            continue
        total += 1
        if current / past - 1.0 > threshold:
            positive += 1
    if total <= 0:
        return 1.0, {"gate": 0.0, "momentum": math.nan, "breadth_pct": math.nan}
    breadth_pct = positive / total * 100.0
    if breadth_pct < float(args.market_gate_min_breadth_pct):
        return gate_scale, {"gate": 1.0, "momentum": math.nan, "breadth_pct": breadth_pct}
    return 1.0, {"gate": 0.0, "momentum": math.nan, "breadth_pct": breadth_pct}


def _scale_weights_by_side(
    weights: dict[str, float],
    *,
    long_scale: float,
    short_scale: float,
) -> dict[str, float]:
    long_scale = max(float(long_scale), 0.0)
    short_scale = max(float(short_scale), 0.0)
    if abs(long_scale - 1.0) <= 1e-12 and abs(short_scale - 1.0) <= 1e-12:
        return weights
    scaled: dict[str, float] = {}
    for symbol, value in weights.items():
        if value > 0.0:
            adjusted = value * long_scale
        elif value < 0.0:
            adjusted = value * short_scale
        else:
            adjusted = 0.0
        if abs(adjusted) > 1e-12:
            scaled[symbol] = adjusted
    return scaled


def _drawdown_ladder_scale(drawdown: float, raw_ladder: str) -> float | None:
    ladder = str(raw_ladder or "").strip()
    if not ladder:
        return None
    selected: float | None = None
    for item in ladder.split(","):
        token = item.strip()
        if not token:
            continue
        if ":" not in token:
            continue
        threshold_raw, scale_raw = token.split(":", 1)
        try:
            threshold = float(threshold_raw) / 100.0
            scale = max(float(scale_raw), 0.0)
        except ValueError:
            continue
        if drawdown >= threshold:
            selected = scale if selected is None else min(selected, scale)
    return selected


def _parse_evaluation_ts(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if len(raw) == 10:
        raw = f"{raw}T00:00:00+00:00"
    elif raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _first_index_at_or_after(frame: rot.MarketFrame, start: datetime, default: int) -> int:
    for idx, ts in enumerate(frame.ts):
        if ts >= start:
            return idx
    return default


def _last_index_before(frame: rot.MarketFrame, end: datetime, default: int) -> int:
    for idx in range(len(frame.ts) - 1, -1, -1):
        if frame.ts[idx] < end:
            return idx
    return default


def _adaptive_policy_from_specs(specs: list[SleeveSpec]) -> dict[str, Any] | None:
    marker = next((spec.name for spec in specs if spec.name.startswith("adapt_")), "")
    if not marker:
        return None
    parts = marker.split("_")
    if len(parts) < 5:
        return None
    profile_name = parts[1]
    if profile_name not in ADAPTIVE_RISK_PROFILES:
        return None
    try:
        momentum_pct = float(parts[2].removeprefix("mom"))
        drawdown_pct = float(parts[3].removeprefix("dd"))
        require_breadth = int(parts[4].removeprefix("br"))
    except ValueError:
        return None
    return {
        "profile": profile_name,
        "momentum_threshold": momentum_pct / 100.0,
        "drawdown_threshold": drawdown_pct / 100.0,
        "require_breadth": bool(require_breadth),
    }


def _normalized_allocation_profile(profile: dict[str, float], specs: list[SleeveSpec]) -> dict[str, float]:
    allowed = {_base_name(spec) for spec in specs}
    filtered = {name: weight for name, weight in profile.items() if name in allowed and weight > 0.0}
    total = sum(filtered.values())
    if total <= 1e-12:
        return {}
    return filtered


def _adaptive_allocations(
    *,
    policy: dict[str, Any],
    specs: list[SleeveSpec],
    frame: rot.MarketFrame,
    signal_idx: int,
    sleeve_weights_by_base: dict[str, dict[str, float]],
    equity: float,
    peak: float,
) -> tuple[dict[str, float], str]:
    market_symbol = "BTCUSDT" if "BTCUSDT" in frame.symbols else frame.symbols[0]
    lookback = rot._hours_to_bars(frame.interval, 720)
    short_lookback = rot._hours_to_bars(frame.interval, 168)
    momentum = math.nan
    short_momentum = math.nan
    if signal_idx >= lookback:
        current = frame.closes[market_symbol][signal_idx]
        past = frame.closes[market_symbol][signal_idx - lookback]
        if math.isfinite(current) and math.isfinite(past) and past > 0.0:
            momentum = current / past - 1.0
    if signal_idx >= short_lookback:
        current = frame.closes[market_symbol][signal_idx]
        past = frame.closes[market_symbol][signal_idx - short_lookback]
        if math.isfinite(current) and math.isfinite(past) and past > 0.0:
            short_momentum = current / past - 1.0

    live_drawdown = 1.0 - equity / max(peak, 1e-12)
    profile_name = str(policy["profile"])
    risk_profile = ADAPTIVE_RISK_PROFILES[profile_name]
    external_signal_count = 0
    for name in ("vwap2_k6", "score15_k6", "score15_k4"):
        weights = sleeve_weights_by_base.get(name) or {}
        if sum(abs(value) for value in weights.values()) > 0.05:
            external_signal_count += 1

    risk_on = (
        math.isfinite(momentum)
        and momentum >= float(policy["momentum_threshold"])
        and (not math.isfinite(short_momentum) or short_momentum > -0.10)
        and (not bool(policy["require_breadth"]) or external_signal_count >= 1)
        and live_drawdown < float(policy["drawdown_threshold"])
    )
    if live_drawdown >= float(policy["drawdown_threshold"]):
        return _normalized_allocation_profile(ADAPTIVE_DEFENSIVE_PROFILE, specs), "defensive_drawdown"
    if math.isfinite(momentum) and momentum < -0.10:
        return _normalized_allocation_profile(ADAPTIVE_DEFENSIVE_PROFILE, specs), "defensive_bear"
    if risk_on:
        return _normalized_allocation_profile(risk_profile, specs), "risk_on"
    return _normalized_allocation_profile(ADAPTIVE_NEUTRAL_PROFILE, specs), "neutral"


def _summary(
    *,
    model_id: str,
    first_exec_ts: datetime | None,
    last_period_ts: datetime | None,
    equity: float,
    min_equity: float,
    max_dd: float,
    period_count: int,
    wins: int,
    losses: int,
    active_periods: int,
    turnover_sum: float,
    cost_drag: float,
    liquidity_drag: float,
    funding_pnl: float,
    gross_sum: float,
    net_sum: float,
    short_sum: float,
    by_year_start: dict[str, float],
    by_year_end: dict[str, float],
    by_year_max_dd: dict[str, float],
    by_quarter_start: dict[str, float],
    by_quarter_end: dict[str, float],
    by_quarter_max_dd: dict[str, float],
    by_month_start: dict[str, float],
    by_month_end: dict[str, float],
    by_month_max_dd: dict[str, float],
    direction_counts: Counter[str],
    symbol_contribution_sum: dict[str, float],
    symbol_abs_exposure_sum: dict[str, float],
    rebalance_count: int,
    skipped_rebalance_count: int,
    entry_gate_count: int,
    entry_gate_removed_abs_weight: float,
    dispersion_scale_count: int,
    dispersion_value_sum: float,
    market_gate_count: int,
    market_gate_momentum_sum: float,
    market_gate_breadth_sum: float,
    final_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    years = max(rot._year_fraction(first_exec_ts, last_period_ts), 1e-9)
    total_return = equity - 1.0
    cagr = equity ** (1.0 / years) - 1.0 if equity > 0.0 else -1.0
    by_year = _period_returns(by_year_start, by_year_end)
    by_quarter = _period_returns(by_quarter_start, by_quarter_end)
    by_month = _period_returns(by_month_start, by_month_end)
    positive_year_fraction = sum(1 for value in by_year.values() if value > 0.0) / max(len(by_year), 1)
    calmar = cagr / max(max_dd, 1e-9) if max_dd > 0.0 else 0.0
    score = 0.0
    if total_return > 0.0 and max_dd > 0.0:
        score = max(calmar, 0.0) * math.log1p(max(total_return, 0.0)) * max(positive_year_fraction, 0.05)
        if max_dd > 0.50:
            score *= 0.45
    if period_count <= 0 or years < 1.0:
        decision = "REJECT_SAMPLE"
    elif total_return <= 0:
        decision = "REJECT_NEGATIVE"
    elif positive_year_fraction < 0.60:
        decision = "REJECT_INCONSISTENT"
    elif max_dd > 0.60:
        decision = "REJECT_DRAWDOWN"
    elif cagr >= 0.35 and calmar >= 0.60 and positive_year_fraction >= 0.70:
        decision = "PAPER_RESEARCH"
    elif cagr >= 0.20 and calmar >= 0.35:
        decision = "WATCH"
    else:
        decision = "REJECT_WEAK"
    final_weights = final_weights or {}
    return {
        "model_id": model_id,
        "decision": decision,
        "periods": int(period_count),
        "first_exec_ts": first_exec_ts.isoformat() if first_exec_ts else None,
        "last_period_ts": last_period_ts.isoformat() if last_period_ts else None,
        "years": round(years, 4),
        "total_return_pct": round(total_return * 100.0, 4),
        "cagr_pct": round(cagr * 100.0, 4),
        "max_drawdown_pct": round(max_dd * 100.0, 4),
        "calmar": round(calmar, 4),
        "min_equity": round(min_equity, 6),
        "rebalance_count": int(rebalance_count),
        "skipped_rebalance_count": int(skipped_rebalance_count),
        "entry_gate_count": int(entry_gate_count),
        "entry_gate_removed_abs_weight_sum": round(entry_gate_removed_abs_weight, 4),
        "dispersion_scale_count": int(dispersion_scale_count),
        "avg_scaled_dispersion_pct": round(
            (dispersion_value_sum / max(dispersion_scale_count, 1)) * 100.0,
            4,
        ),
        "market_gate_count": int(market_gate_count),
        "avg_market_gate_momentum_pct": round(
            (market_gate_momentum_sum / max(market_gate_count, 1)) * 100.0,
            4,
        ),
        "avg_market_gate_breadth_pct": round(
            market_gate_breadth_sum / max(market_gate_count, 1),
            4,
        ),
        "win_rate_period": round(wins / max(wins + losses, 1), 4),
        "active_fraction": round(active_periods / max(period_count, 1), 4),
        "avg_gross_exposure": round(gross_sum / max(period_count, 1), 4),
        "avg_net_exposure": round(net_sum / max(period_count, 1), 4),
        "avg_short_exposure": round(short_sum / max(period_count, 1), 4),
        "turnover_sum": round(turnover_sum, 4),
        "avg_daily_turnover": round(turnover_sum / max(years * 365.25, 1e-9), 4),
        "cost_drag_pct_simple_sum": round(cost_drag * 100.0, 4),
        "liquidity_impact_drag_pct_simple_sum": round(liquidity_drag * 100.0, 4),
        "funding_pnl_pct_simple_sum": round(funding_pnl * 100.0, 4),
        "positive_year_fraction": round(positive_year_fraction, 4),
        "by_year_return_pct": {year: round(value * 100.0, 4) for year, value in by_year.items()},
        "by_year_max_drawdown_pct": {
            year: round(value * 100.0, 4) for year, value in sorted(by_year_max_dd.items())
        },
        "by_quarter_return_pct": {
            quarter: round(value * 100.0, 4) for quarter, value in by_quarter.items()
        },
        "by_quarter_max_drawdown_pct": {
            quarter: round(value * 100.0, 4) for quarter, value in sorted(by_quarter_max_dd.items())
        },
        "by_month_return_pct": {month: round(value * 100.0, 4) for month, value in by_month.items()},
        "by_month_max_drawdown_pct": {
            month: round(value * 100.0, 4) for month, value in sorted(by_month_max_dd.items())
        },
        "best_year_pct": round(max(by_year.values()) * 100.0, 4) if by_year else 0.0,
        "worst_year_pct": round(min(by_year.values()) * 100.0, 4) if by_year else 0.0,
        "direction_period_counts": dict(sorted(direction_counts.items())),
        "top_symbol_contribution_pct_simple_sum": rot._top_float_items(
            {symbol: value * 100.0 for symbol, value in symbol_contribution_sum.items()},
            reverse=True,
        ),
        "bottom_symbol_contribution_pct_simple_sum": rot._top_float_items(
            {symbol: value * 100.0 for symbol, value in symbol_contribution_sum.items()},
            reverse=False,
        ),
        "top_symbol_exposure": {
            symbol: round(value / max(period_count, 1), 4)
            for symbol, value in sorted(symbol_abs_exposure_sum.items(), key=lambda item: item[1], reverse=True)[:10]
            if abs(value) > 1e-12
        },
        "final_gross_exposure": round(sum(abs(value) for value in final_weights.values()), 4),
        "final_net_exposure": round(sum(final_weights.values()), 4),
        "final_short_exposure": round(sum(abs(value) for value in final_weights.values() if value < 0.0), 4),
        "final_top_weights": {
            symbol: round(value, 6)
            for symbol, value in sorted(final_weights.items(), key=lambda item: abs(item[1]), reverse=True)[:20]
            if abs(value) > 1e-9
        },
        "score": round(score, 8),
    }


def _backtest_mix(
    frame: rot.MarketFrame,
    features: rot.FeatureBundle,
    indicators: ext.IndicatorCache,
    specs: list[SleeveSpec],
    *,
    args: argparse.Namespace,
    funding_period_rates: dict[str, list[float]] | None,
) -> dict[str, Any]:
    states = [SleeveState(spec=spec, weights={}, state={}) for spec in specs]
    adaptive_policy = _adaptive_policy_from_specs(specs)
    adaptive_regime_counts: Counter[str] = Counter()
    cost = max(float(args.fee_bps_per_side) + float(args.slippage_bps_per_side), 0.0) / 10_000.0
    warmup = 0
    for spec in specs:
        if spec.internal_config is not None:
            cfg = spec.internal_config
            warmup = max(warmup, cfg.lookback_bars, cfg.vol_bars, cfg.min_symbol_age_bars)
        if spec.external_config is not None:
            cfg2 = spec.external_config
            warmup = max(warmup, cfg2.lookback_bars, cfg2.exit_bars, cfg2.fast_bars, cfg2.slow_bars, cfg2.min_symbol_age_bars)
    warmup += 2
    first_exec_idx = warmup + 1
    last_exec_idx = len(frame.ts) - 2
    evaluation_start = _parse_evaluation_ts(getattr(args, "evaluation_start", ""))
    evaluation_end = _parse_evaluation_ts(getattr(args, "evaluation_end", ""))
    if evaluation_start is not None:
        first_exec_idx = max(first_exec_idx, _first_index_at_or_after(frame, evaluation_start, len(frame.ts) - 1))
    if evaluation_end is not None:
        last_exec_idx = min(last_exec_idx, _last_index_before(frame, evaluation_end, -1), len(frame.ts) - 2)
    if first_exec_idx > last_exec_idx:
        return _summary(
            model_id=_mix_id(specs),
            first_exec_ts=None,
            last_period_ts=None,
            equity=1.0,
            min_equity=1.0,
            max_dd=0.0,
            period_count=0,
            wins=0,
            losses=0,
            active_periods=0,
            turnover_sum=0.0,
            cost_drag=0.0,
            liquidity_drag=0.0,
            funding_pnl=0.0,
            gross_sum=0.0,
            net_sum=0.0,
            short_sum=0.0,
            by_year_start={},
            by_year_end={},
            by_year_max_dd={},
            by_quarter_start={},
            by_quarter_end={},
            by_quarter_max_dd={},
            by_month_start={},
            by_month_end={},
            by_month_max_dd={},
            direction_counts=Counter(),
            symbol_contribution_sum={symbol: 0.0 for symbol in frame.symbols},
            symbol_abs_exposure_sum={symbol: 0.0 for symbol in frame.symbols},
            rebalance_count=0,
            skipped_rebalance_count=0,
            entry_gate_count=0,
            entry_gate_removed_abs_weight=0.0,
            dispersion_scale_count=0,
            dispersion_value_sum=0.0,
            market_gate_count=0,
            market_gate_momentum_sum=0.0,
            market_gate_breadth_sum=0.0,
        )
    combined_weights: dict[str, float] = {}
    equity = peak = min_equity = 1.0
    max_dd = 0.0
    period_count = active_periods = wins = losses = rebalance_count = 0
    skipped_rebalance_count = 0
    entry_gate_count = 0
    entry_gate_removed_abs_weight = 0.0
    dispersion_scale_count = 0
    dispersion_value_sum = 0.0
    market_gate_count = 0
    market_gate_momentum_sum = 0.0
    market_gate_breadth_sum = 0.0
    turnover_sum = cost_drag = liquidity_drag = funding_pnl = 0.0
    gross_sum = net_sum = short_sum = 0.0
    first_exec_ts: datetime | None = None
    last_period_ts: datetime | None = None
    by_year_start: dict[str, float] = {}
    by_year_end: dict[str, float] = {}
    by_year_peak: dict[str, float] = {}
    by_year_max_dd: dict[str, float] = {}
    by_quarter_start: dict[str, float] = {}
    by_quarter_end: dict[str, float] = {}
    by_quarter_peak: dict[str, float] = {}
    by_quarter_max_dd: dict[str, float] = {}
    by_month_start: dict[str, float] = {}
    by_month_end: dict[str, float] = {}
    by_month_peak: dict[str, float] = {}
    by_month_max_dd: dict[str, float] = {}
    direction_counts: Counter[str] = Counter()
    symbol_contribution_sum = {symbol: 0.0 for symbol in frame.symbols}
    symbol_abs_exposure_sum = {symbol: 0.0 for symbol in frame.symbols}
    realized_returns: deque[float] = deque(maxlen=rot._hours_to_bars(args.interval, max(int(args.vol_lookback_hours), 1)))

    for exec_idx in range(first_exec_idx, last_exec_idx + 1):
        if first_exec_ts is None:
            first_exec_ts = frame.ts[exec_idx]
        signal_idx = exec_idx - 1
        changed = False
        for sleeve in states:
            if sleeve.spec.internal_config is not None:
                cfg = sleeve.spec.internal_config
                rebalance_bars = max(cfg.rebalance_bars, 1)
            else:
                cfg = sleeve.spec.external_config
                assert cfg is not None
                rebalance_bars = max(cfg.rebalance_bars, 1)
            if (exec_idx - first_exec_idx) % rebalance_bars != 0:
                continue
            if sleeve.spec.internal_config is not None:
                new_weights = rot._target_weights(
                    frame,
                    features,
                    sleeve.spec.internal_config,
                    signal_idx,
                    funding_period_rates=funding_period_rates,
                )
            else:
                assert sleeve.spec.external_config is not None
                new_weights = ext._target_weights(
                    frame,
                    indicators,
                    sleeve.spec.external_config,
                    signal_idx,
                    sleeve.state,
                )
            if sleeve.spec.max_symbol_weight > 0.0:
                new_weights, _ = rot._clip_symbol_weights(new_weights, sleeve.spec.max_symbol_weight)
            sleeve.weights = new_weights
            changed = True

        turnover = 0.0
        liquidity_cost_period = 0.0
        if changed:
            allocation_by_base: dict[str, float] | None = None
            if adaptive_policy is not None:
                allocation_by_base, regime = _adaptive_allocations(
                    policy=adaptive_policy,
                    specs=specs,
                    frame=frame,
                    signal_idx=signal_idx,
                    sleeve_weights_by_base={_base_name(sleeve.spec): sleeve.weights for sleeve in states},
                    equity=equity,
                    peak=peak,
                )
                adaptive_regime_counts[regime] += 1
            dispersion_scale = 1.0
            dispersion_mode = str(args.dispersion_scale_mode or "none")
            dispersion = math.nan
            if dispersion_mode != "none" and float(args.dispersion_threshold_pct) > 0.0:
                dispersion = _cross_sectional_return_dispersion(
                    frame,
                    signal_idx,
                    rot._hours_to_bars(args.interval, max(int(args.dispersion_lookback_hours), 1)),
                    max(int(args.dispersion_min_symbols), 2),
                )
                if math.isfinite(dispersion) and dispersion * 100.0 >= float(args.dispersion_threshold_pct):
                    dispersion_scale = max(float(args.dispersion_risk_scale), 0.0)
                    dispersion_scale_count += 1
                    dispersion_value_sum += dispersion
            target_weights: dict[str, float] = {}
            sleeve_contributions: list[tuple[SleeveSpec, float, dict[str, float]]] = []
            for sleeve in states:
                allocation = (
                    allocation_by_base.get(_base_name(sleeve.spec), 0.0)
                    if allocation_by_base is not None
                    else sleeve.spec.allocation
                )
                if dispersion_mode == "momentum_sleeves" and _base_name(sleeve.spec) in DISPERSION_MOMENTUM_SLEEVES:
                    allocation *= dispersion_scale
                if allocation > 0.0:
                    sleeve_contributions.append((sleeve.spec, allocation, sleeve.weights))
                for symbol, value in sleeve.weights.items():
                    target_weights[symbol] = target_weights.get(symbol, 0.0) + value * allocation
            target_weights, gate_stats = _entry_gated_weights(target_weights, sleeve_contributions, args)
            entry_gate_count += int(gate_stats["gate_events"])
            entry_gate_removed_abs_weight += float(gate_stats["removed_abs_weight"])
            live_drawdown = 1.0 - equity / max(peak, 1e-12)
            risk_scale = 1.0
            if dispersion_mode == "global":
                risk_scale *= dispersion_scale
            market_scale, market_stats = _market_gate_scale(frame, signal_idx, args)
            risk_scale *= market_scale
            if market_stats["gate"] > 0.0:
                market_gate_count += 1
                if math.isfinite(market_stats["momentum"]):
                    market_gate_momentum_sum += float(market_stats["momentum"])
                if math.isfinite(market_stats["breadth_pct"]):
                    market_gate_breadth_sum += float(market_stats["breadth_pct"])
            ladder_scale = _drawdown_ladder_scale(live_drawdown, getattr(args, "drawdown_ladder", ""))
            if ladder_scale is not None:
                risk_scale *= ladder_scale
            elif args.drawdown_guard_pct > 0.0 and live_drawdown * 100.0 >= args.drawdown_guard_pct:
                risk_scale *= max(float(args.drawdown_risk_scale), 0.0)
            if args.vol_target_annual_pct > 0.0 and len(realized_returns) >= max(10, realized_returns.maxlen // 2):
                if str(getattr(args, "vol_target_mode", "all") or "all") == "downside":
                    variance = sum(min(value, 0.0) ** 2 for value in realized_returns) / len(realized_returns)
                else:
                    mean_return = sum(realized_returns) / len(realized_returns)
                    variance = sum((value - mean_return) ** 2 for value in realized_returns) / len(realized_returns)
                period_vol = math.sqrt(max(variance, 0.0))
                realized_vol = period_vol * math.sqrt(365.25 * 24.0 / max(rot._interval_hours(args.interval), 1e-9))
                if realized_vol > 1e-12:
                    risk_scale *= min(
                        max((args.vol_target_annual_pct / 100.0) / realized_vol, float(args.vol_min_scale)),
                        float(args.vol_max_scale),
                    )
            target_weights = rot._scale_weights(target_weights, risk_scale)
            target_weights = _scale_weights_by_side(
                target_weights,
                long_scale=float(args.long_weight_scale),
                short_scale=float(args.short_weight_scale),
            )
            if args.max_symbol_weight > 0.0:
                target_weights, _ = rot._clip_symbol_weights(target_weights, float(args.max_symbol_weight))
            if args.capacity_cap_trade_volume_pct > 0.0:
                target_weights, _, _ = rot._apply_capacity_cap(
                    frame,
                    old_weights=combined_weights,
                    new_weights=target_weights,
                    signal_idx=signal_idx,
                    equity=equity,
                    assumed_capital_usd=args.assumed_capital_usd,
                    max_trade_volume_pct=max(float(args.capacity_cap_trade_volume_pct), 0.0),
                    liquidity_notional_mode=args.liquidity_notional_mode,
                )
            proposed_turnover = rot._turnover(combined_weights, target_weights, frame.symbols)
            if proposed_turnover > 1e-9 and proposed_turnover < max(float(args.min_rebalance_turnover), 0.0):
                target_weights = dict(combined_weights)
                turnover = 0.0
                skipped_rebalance_count += 1
            else:
                target_weights = _blend_weights(
                    combined_weights,
                    target_weights,
                    frame.symbols,
                    float(args.rebalance_fill_fraction),
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
            if turnover > 1e-9:
                rebalance_count += 1
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
        liquidity_drag += liquidity_cost_period
        funding_period = rot._funding_return_for_period_index(funding_period_rates, combined_weights, exec_idx) if funding_period_rates is not None else 0.0
        funding_pnl += funding_period
        portfolio_return = 0.0
        for symbol, weight in combined_weights.items():
            symbol_return = frame.returns[symbol][exec_idx]
            if not math.isfinite(symbol_return):
                continue
            contribution = weight * symbol_return
            portfolio_return += contribution
            symbol_contribution_sum[symbol] = symbol_contribution_sum.get(symbol, 0.0) + contribution
            symbol_abs_exposure_sum[symbol] = symbol_abs_exposure_sum.get(symbol, 0.0) + abs(weight)
        period_days = max((frame.ts[exec_idx + 1] - frame.ts[exec_idx]).total_seconds() / 86_400.0, 0.0)
        holding_cost = gross_exposure * max(float(args.holding_cost_bps_per_day), 0.0) / 10_000.0 * period_days
        short_cost = short_exposure * max(float(args.short_cost_bps_per_day), 0.0) / 10_000.0 * period_days
        basis_return = portfolio_return + funding_period - cost_period - liquidity_cost_period - holding_cost - short_cost
        net_return = rot._basis_return_to_equity_return(basis_return, equity=equity, pnl_notional_mode=args.pnl_notional_mode)
        if gross_exposure > 1e-9:
            active_periods += 1
        if net_exposure > 0.05:
            direction_counts["net_long"] += 1
        elif net_exposure < -0.05:
            direction_counts["net_short"] += 1
        else:
            direction_counts["market_neutral_or_flat"] += 1
        period_ts = frame.ts[exec_idx + 1]
        year = str(period_ts.year)
        quarter = f"{period_ts.year}Q{((period_ts.month - 1) // 3) + 1}"
        month = f"{period_ts.year}-{period_ts.month:02d}"
        by_year_start.setdefault(year, equity)
        by_quarter_start.setdefault(quarter, equity)
        by_month_start.setdefault(month, equity)
        by_year_peak.setdefault(year, equity)
        by_quarter_peak.setdefault(quarter, equity)
        by_month_peak.setdefault(month, equity)
        equity = 1e-9 if net_return <= -0.999 else equity * (1.0 + net_return)
        by_year_end[year] = equity
        by_quarter_end[quarter] = equity
        by_month_end[month] = equity
        by_year_peak[year] = max(by_year_peak[year], equity)
        by_quarter_peak[quarter] = max(by_quarter_peak[quarter], equity)
        by_month_peak[month] = max(by_month_peak[month], equity)
        by_year_max_dd[year] = max(by_year_max_dd.get(year, 0.0), 1.0 - equity / max(by_year_peak[year], 1e-12))
        by_quarter_max_dd[quarter] = max(
            by_quarter_max_dd.get(quarter, 0.0),
            1.0 - equity / max(by_quarter_peak[quarter], 1e-12),
        )
        by_month_max_dd[month] = max(by_month_max_dd.get(month, 0.0), 1.0 - equity / max(by_month_peak[month], 1e-12))
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
        if equity <= 1e-8:
            break

    summary = _summary(
        model_id=_mix_id(specs),
        first_exec_ts=first_exec_ts,
        last_period_ts=last_period_ts,
        equity=equity,
        min_equity=min_equity,
        max_dd=max_dd,
        period_count=period_count,
        wins=wins,
        losses=losses,
        active_periods=active_periods,
        turnover_sum=turnover_sum,
        cost_drag=cost_drag,
        liquidity_drag=liquidity_drag,
        funding_pnl=funding_pnl,
        gross_sum=gross_sum,
        net_sum=net_sum,
        short_sum=short_sum,
        by_year_start=by_year_start,
        by_year_end=by_year_end,
        by_year_max_dd=by_year_max_dd,
        by_quarter_start=by_quarter_start,
        by_quarter_end=by_quarter_end,
        by_quarter_max_dd=by_quarter_max_dd,
        by_month_start=by_month_start,
        by_month_end=by_month_end,
        by_month_max_dd=by_month_max_dd,
        direction_counts=direction_counts,
        symbol_contribution_sum=symbol_contribution_sum,
        symbol_abs_exposure_sum=symbol_abs_exposure_sum,
        rebalance_count=rebalance_count,
        skipped_rebalance_count=skipped_rebalance_count,
        entry_gate_count=entry_gate_count,
        entry_gate_removed_abs_weight=entry_gate_removed_abs_weight,
        dispersion_scale_count=dispersion_scale_count,
        dispersion_value_sum=dispersion_value_sum,
        market_gate_count=market_gate_count,
        market_gate_momentum_sum=market_gate_momentum_sum,
        market_gate_breadth_sum=market_gate_breadth_sum,
        final_weights=combined_weights,
    )
    if adaptive_policy is not None:
        summary["adaptive_policy"] = adaptive_policy
        summary["adaptive_regime_counts"] = dict(sorted(adaptive_regime_counts.items()))
    return summary


def _rank(rows: list[dict[str, Any]], key: str, limit: int = 30) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            float(row["summary"].get(key, 0.0) or 0.0),
            float(row["summary"].get("score", 0.0) or 0.0),
        ),
        reverse=True,
    )[:limit]


def main() -> int:
    args = _parse_args()
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

    if args.candidate_set == "focus":
        mixes = _focused_candidate_mixes(args.interval)
    elif args.candidate_set == "optimal":
        mixes = _optimal_candidate_mixes(args.interval)
    elif args.candidate_set == "cost_aware":
        mixes = _cost_aware_candidate_mixes(args.interval)
    elif args.candidate_set == "adaptive":
        mixes = _adaptive_candidate_mixes(args.interval)
    elif args.candidate_set == "adaptive_overlay":
        mixes = _adaptive_candidate_mixes(args.interval, profile_prefix="ov")
    elif args.candidate_set == "finalists":
        mixes = _finalist_candidate_mixes(args.interval)
    elif args.candidate_set == "vwap_family":
        mixes = _vwap_family_candidate_mixes(args.interval)
    elif args.candidate_set == "weak_sleeve":
        mixes = _weak_sleeve_candidate_mixes(args.interval)
    elif args.candidate_set == "weak_sleeve_finalists":
        mixes = _weak_sleeve_finalist_mixes(args.interval)
    elif args.candidate_set == "all":
        mixes = (
            _candidate_mixes(args.interval)
            + _focused_candidate_mixes(args.interval)
            + _optimal_candidate_mixes(args.interval)
            + _cost_aware_candidate_mixes(args.interval)
            + _adaptive_candidate_mixes(args.interval)
            + _finalist_candidate_mixes(args.interval)
            + _vwap_family_candidate_mixes(args.interval)
            + _weak_sleeve_candidate_mixes(args.interval)
            + _weak_sleeve_finalist_mixes(args.interval)
        )
    else:
        mixes = _candidate_mixes(args.interval)
    mixes = _dedupe_mixes(mixes)
    if int(args.max_mixes or 0) > 0:
        mixes = mixes[: int(args.max_mixes)]
    internal_configs = [spec.internal_config for mix in mixes for spec in mix if spec.internal_config is not None]
    external_configs = [spec.external_config for mix in mixes for spec in mix if spec.external_config is not None]
    features = rot._build_features(frame, [config for config in internal_configs if config is not None])
    indicators = ext._build_indicators(frame, [config for config in external_configs if config is not None])

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

    rows: list[dict[str, Any]] = []
    for idx, specs in enumerate(mixes, start=1):
        summary = _backtest_mix(frame, features, indicators, specs, args=args, funding_period_rates=funding_period_rates)
        rows.append({
            "config": {
                "mix": [{"name": spec.name, "kind": spec.kind, "allocation": spec.allocation} for spec in specs],
                "mix_id": _mix_id(specs),
            },
            "summary": summary,
        })
        if idx % 25 == 0:
            print(json.dumps({"progress": idx, "mixes_total": len(mixes), "latest": summary["model_id"]}, ensure_ascii=False), flush=True)

    output = {
        "schema_version": "hybrid_strategy_mix_search_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "authority": "research_only_no_live_authority_change",
        "scope": {
            "symbols": frame.symbols,
            "days": int(args.days),
            "interval": str(args.interval),
            "mix_count": len(rows),
        },
        "data_status": data_status,
        "cost_model": {
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": float(args.slippage_bps_per_side),
            "drawdown_guard_pct": float(args.drawdown_guard_pct),
            "drawdown_risk_scale": float(args.drawdown_risk_scale),
            "drawdown_ladder": str(getattr(args, "drawdown_ladder", "") or ""),
            "vol_target_annual_pct": float(args.vol_target_annual_pct),
            "vol_target_mode": str(getattr(args, "vol_target_mode", "all") or "all"),
            "vol_lookback_hours": int(args.vol_lookback_hours),
            "max_symbol_weight": float(args.max_symbol_weight),
            "assumed_capital_usd": float(args.assumed_capital_usd),
            "pnl_notional_mode": str(args.pnl_notional_mode),
            "liquidity_notional_mode": str(args.liquidity_notional_mode),
            "liquidity_impact_bps_per_1pct_volume": float(args.liquidity_impact_bps_per_1pct_volume),
            "capacity_cap_trade_volume_pct": float(args.capacity_cap_trade_volume_pct),
            "min_rebalance_turnover": float(args.min_rebalance_turnover),
            "rebalance_fill_fraction": float(args.rebalance_fill_fraction),
            "entry_gate_mode": str(args.entry_gate_mode),
            "entry_gate_min_agree": int(args.entry_gate_min_agree),
            "entry_gate_sleeve_threshold": float(args.entry_gate_sleeve_threshold),
            "entry_gate_min_abs_weight": float(args.entry_gate_min_abs_weight),
            "entry_gate_rescale_survivors": bool(args.entry_gate_rescale_survivors),
            "dispersion_scale_mode": str(args.dispersion_scale_mode),
            "dispersion_lookback_hours": int(args.dispersion_lookback_hours),
            "dispersion_threshold_pct": float(args.dispersion_threshold_pct),
            "dispersion_risk_scale": float(args.dispersion_risk_scale),
            "dispersion_min_symbols": int(args.dispersion_min_symbols),
            "market_gate_mode": str(args.market_gate_mode),
            "market_gate_lookback_hours": int(args.market_gate_lookback_hours),
            "market_gate_threshold_pct": float(args.market_gate_threshold_pct),
            "market_gate_abs_threshold_pct": float(args.market_gate_abs_threshold_pct),
            "market_gate_min_breadth_pct": float(args.market_gate_min_breadth_pct),
            "market_gate_risk_scale": float(args.market_gate_risk_scale),
            "long_weight_scale": float(args.long_weight_scale),
            "short_weight_scale": float(args.short_weight_scale),
            "evaluation_start": str(args.evaluation_start or ""),
            "evaluation_end": str(args.evaluation_end or ""),
            "funding": "loaded_for_internal_funding_sleeves",
        },
        "decision_counts": dict(sorted(Counter(str(row["summary"].get("decision")) for row in rows).items())),
        "top_by_score": sorted(
            rows,
            key=lambda row: (
                float(row["summary"].get("score", 0.0) or 0.0),
                float(row["summary"].get("cagr_pct", 0.0) or 0.0),
            ),
            reverse=True,
        )[:30],
        "top_by_return": _rank(rows, "total_return_pct"),
        "top_by_calmar": _rank(rows, "calmar"),
        "all_results": rows,
    }
    if args.write_report:
        report_dir = ROOT_DIR / str(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = report_dir / f"hybrid_strategy_mix_search_{stamp}.json"
        latest = report_dir / "latest.json"
        output["report_path"] = str(path.relative_to(ROOT_DIR))
        output["latest_report_path"] = str(latest.relative_to(ROOT_DIR))
        text = json.dumps(output, ensure_ascii=False, indent=2)
        atomic_write_text(path, text)
        atomic_write_text(latest, text)
    print(json.dumps(output, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
