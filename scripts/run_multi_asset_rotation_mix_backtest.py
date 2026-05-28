#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text
from scripts import run_multi_asset_rotation_search as rot


SYMBOLS_36 = (
    "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,LINKUSDT,"
    "AVAXUSDT,BCHUSDT,LTCUSDT,NEARUSDT,AAVEUSDT,APTUSDT,ARBUSDT,ATOMUSDT,"
    "DASHUSDT,DOTUSDT,ETCUSDT,FETUSDT,FILUSDT,HBARUSDT,ICPUSDT,INJUSDT,"
    "PENDLEUSDT,QNTUSDT,RUNEUSDT,SUIUSDT,UNIUSDT,XLMUSDT,ZECUSDT,"
    "1000SHIBUSDT,TAOUSDT,1000FLOKIUSDT,STXUSDT,OPUSDT"
)


@dataclass(slots=True)
class Sleeve:
    name: str
    allocation: float
    config: rot.RotationPortfolioConfig
    max_symbol_weight: float
    symbol_quality_lookback_hours: int = 0
    symbol_quality_drop_count: int = 0
    symbol_quality_score_threshold: float = 0.0
    weights: dict[str, float] | None = None
    dispersion_history: deque[float] | None = None
    quality_contribution_history: dict[str, deque[float]] | None = None
    quality_exposure_history: dict[str, deque[float]] | None = None
    quality_active_history: dict[str, deque[int]] | None = None
    quality_block_count: int = 0
    quality_block_symbol_events: int = 0
    quality_block_counts: Counter[str] | None = None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only true bar-level mix backtest for rotation sleeves.")
    parser.add_argument("--mix", required=True, help="Comma list such as aggr:0.6,qual:0.4")
    parser.add_argument("--symbols", default=SYMBOLS_36)
    parser.add_argument("--days", type=int, default=1825)
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--cache-dir", default="reports/validation/multi_asset_rotation_search/cache_refresh_20260521T2035")
    parser.add_argument("--funding-cache-dir", default="reports/validation/multi_asset_rotation_search/funding_cache")
    parser.add_argument("--exchange-rules-cache", default="reports/validation/multi_asset_rotation_search/exchange_rules_cache/exchange_info.json")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument("--holding-cost-bps-per-day", type=float, default=0.0)
    parser.add_argument("--short-cost-bps-per-day", type=float, default=0.0)
    parser.add_argument("--drawdown-guard-pct", type=float, default=20.0)
    parser.add_argument("--drawdown-risk-scale", type=float, default=0.4)
    parser.add_argument("--vol-target-annual-pct", type=float, default=60.0)
    parser.add_argument("--vol-lookback-hours", type=int, default=720)
    parser.add_argument("--vol-min-scale", type=float, default=0.0)
    parser.add_argument("--vol-max-scale", type=float, default=1.0)
    parser.add_argument("--dispersion-lookback-rebalances", type=int, default=250)
    parser.add_argument("--dispersion-guard-quantile", type=float, default=0.8)
    parser.add_argument("--dispersion-risk-scale", type=float, default=1.0)
    parser.add_argument("--symbol-quality-min-active-periods", type=int, default=30)
    parser.add_argument("--symbol-quality-min-abs-exposure", type=float, default=1.0)
    parser.add_argument("--apply-funding", action="store_true")
    parser.add_argument("--apply-exchange-rules", action="store_true")
    parser.add_argument("--maintenance-margin-pct", type=float, default=5.0)
    parser.add_argument("--assumed-capital-usd", type=float, default=100000.0)
    parser.add_argument("--pnl-notional-mode", default="profit95")
    parser.add_argument("--liquidity-notional-mode", default="profit95")
    parser.add_argument("--liquidity-impact-bps-per-1pct-volume", type=float, default=0.25)
    parser.add_argument("--max-trade-volume-pct", type=float, default=0.5)
    parser.add_argument("--capacity-cap-trade-volume-pct", type=float, default=0.5)
    parser.add_argument("--report-dir", default="reports/validation/multi_asset_rotation_mix_backtest")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _cfg(name: str) -> tuple[rot.RotationPortfolioConfig, float, int, int, float]:
    presets: dict[str, tuple[str, int, int, float, float, int, int, float]] = {
        "aggr": ("residual85_funding15_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040", 336, 3, 6.7, 0.725, 0, 0, 0.0),
        "bal": ("residual85_funding15_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040", 336, 3, 5.8, 0.725, 0, 0, 0.0),
        "high": ("residual90_funding10_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_5050", 336, 4, 6.7, 0.70, 0, 0, 0.0),
        "qual": ("residual85_funding15_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040", 336, 3, 6.4, 0.725, 4320, 1, 0.0),
        "q2160": ("residual85_funding15_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040", 336, 3, 6.4, 0.725, 2160, 1, 0.0),
        "q6480": ("residual85_funding15_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040", 336, 3, 6.4, 0.725, 6480, 1, 0.0),
        "q4320d2": ("residual85_funding15_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040", 336, 3, 6.4, 0.725, 4320, 2, 0.0),
        "q2160d2": ("residual85_funding15_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040", 336, 3, 6.4, 0.725, 2160, 2, 0.0),
        "q6480d2": ("residual85_funding15_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040", 336, 3, 6.4, 0.725, 6480, 2, 0.0),
        "q4320g60": ("residual85_funding15_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040", 336, 3, 6.0, 0.725, 4320, 1, 0.0),
        "q4320g67": ("residual85_funding15_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040", 336, 3, 6.7, 0.725, 4320, 1, 0.0),
        "q4320neg": ("residual85_funding15_btc_cash_blend_ex_icp_near_ltc_ex_icp_near_link_6040", 336, 3, 6.4, 0.725, 4320, 1, -0.001),
    }
    mode, lookback_hours, top_k, gross, cap, qlb, qdrop, qth = presets[name]
    interval = "4h"
    config = rot.RotationPortfolioConfig(
        model_id=f"mix_sleeve:{name}:{mode}:lb{lookback_hours}h:k{top_k}:rb8h:gross{gross:g}",
        interval=interval,
        mode=mode,
        lookback_hours=lookback_hours,
        lookback_bars=rot._hours_to_bars(interval, lookback_hours),
        top_k=top_k,
        rebalance_hours=8,
        rebalance_bars=rot._hours_to_bars(interval, 8),
        trend_hours=0,
        trend_bars=0,
        vol_weight=False,
        vol_hours=max(168, lookback_hours),
        vol_bars=rot._hours_to_bars(interval, max(168, lookback_hours)),
        min_symbol_age_hours=2160,
        min_symbol_age_bars=rot._hours_to_bars(interval, 2160),
        gross_leverage=gross,
    )
    return config, cap, qlb, qdrop, qth


def _parse_mix(raw: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for item in raw.split(","):
        name, value = item.split(":", 1)
        out.append((name.strip(), float(value)))
    total = sum(value for _, value in out)
    if total <= 0.0:
        raise ValueError("mix weights must sum positive")
    return [(name, value / total) for name, value in out]


def _period_returns(starts: dict[str, float], ends: dict[str, float]) -> dict[str, float]:
    return {
        key: ends[key] / max(starts.get(key, 1.0), 1e-12) - 1.0
        for key in sorted(ends)
    }


def _top_items(values: dict[str, float], reverse: bool, limit: int = 10) -> dict[str, float]:
    return {key: round(value, 4) for key, value in sorted(values.items(), key=lambda item: item[1], reverse=reverse)[:limit]}


def _build_sleeves(raw_mix: str, frame: rot.MarketFrame, dispersion_lookback: int) -> list[Sleeve]:
    sleeves: list[Sleeve] = []
    for name, allocation in _parse_mix(raw_mix):
        config, cap, qlb, qdrop, qth = _cfg(name)
        quality_bars = rot._hours_to_bars(config.interval, qlb) if qlb > 0 else 0
        sleeve = Sleeve(
            name=name,
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
        sleeves.append(sleeve)
    return sleeves


def _summary(
    *,
    model_id: str,
    frame: rot.MarketFrame,
    first_exec_ts: datetime | None,
    last_period_ts: datetime | None,
    equity: float,
    peak: float,
    min_equity: float,
    wins: int,
    losses: int,
    period_count: int,
    active_periods: int,
    turnover_sum: float,
    cost_drag: float,
    liquidity_impact_drag: float,
    holding_cost_drag: float,
    short_cost_drag: float,
    funding_pnl: float,
    gross_sum: float,
    net_sum: float,
    short_sum: float,
    max_dd: float,
    worst_intrabar_adverse_return: float,
    liquidation_event_count: int,
    max_trade_volume_pct_seen: float,
    capacity_violation_count: int,
    capacity_cap_event_count: int,
    max_capacity_cap_requested_trade_volume_pct: float,
    exchange_rule_adjustment_count: int,
    exchange_rule_drop_count: int,
    symbol_weight_cap_event_count: int,
    by_year_start: dict[str, float],
    by_year_end: dict[str, float],
    by_month_start: dict[str, float],
    by_month_end: dict[str, float],
    by_quarter_start: dict[str, float],
    by_quarter_end: dict[str, float],
    direction_periods: Counter[str],
    symbol_contribution_sum: dict[str, float],
    symbol_abs_exposure_sum: dict[str, float],
    symbol_long_periods: Counter[str],
    symbol_short_periods: Counter[str],
    sleeves: list[Sleeve],
    rebalance_samples: list[dict[str, Any]],
    entry_grade_count: int = 0,
    entry_grade_avg_scale: float = 1.0,
    entry_grade_min_scale_seen: float = 1.0,
    entry_grade_max_scale_seen: float = 1.0,
    entry_grade_avg_strength: float = 0.0,
    market_stress_count: int = 0,
    market_stress_active_count: int = 0,
    market_stress_avg_scale: float = 1.0,
    market_stress_avg_breadth: float = 0.0,
    market_stress_avg_btcema: float = 0.0,
) -> dict[str, Any]:
    years = max(rot._year_fraction(first_exec_ts, last_period_ts), 1e-9)
    total_return = equity - 1.0
    cagr = (equity ** (1.0 / years) - 1.0) if equity > 0.0 else -1.0
    by_year_return = _period_returns(by_year_start, by_year_end)
    by_month_return = _period_returns(by_month_start, by_month_end)
    by_quarter_return = _period_returns(by_quarter_start, by_quarter_end)
    positive_year_fraction = sum(1 for value in by_year_return.values() if value > 0.0) / max(len(by_year_return), 1)
    calmar = cagr / max(max_dd, 1e-9) if max_dd > 0.0 else 0.0
    score = max(calmar, 0.0) * math.log1p(max(total_return, 0.0)) * max(positive_year_fraction, 0.05) if total_return > 0.0 and max_dd > 0.0 else 0.0
    common_days = max(years * 365.25, 1e-9)
    avg_abs_exposure_by_symbol = {
        symbol: value / max(period_count, 1)
        for symbol, value in symbol_abs_exposure_sum.items()
        if abs(value) > 1e-12
    }
    top_exposure = {
        symbol: {
            "avg_abs_exposure": round(avg_abs_exposure_by_symbol.get(symbol, 0.0), 4),
            "long_periods": int(symbol_long_periods.get(symbol, 0)),
            "short_periods": int(symbol_short_periods.get(symbol, 0)),
        }
        for symbol, _ in sorted(avg_abs_exposure_by_symbol.items(), key=lambda item: item[1], reverse=True)[:10]
    }
    return {
        "model_id": model_id,
        "decision": "PAPER_RESEARCH" if cagr >= 0.35 and calmar >= 0.60 and positive_year_fraction >= 0.70 else "WATCH",
        "periods": period_count,
        "first_exec_ts": first_exec_ts.isoformat() if first_exec_ts else None,
        "last_period_ts": last_period_ts.isoformat() if last_period_ts else None,
        "years": round(years, 4),
        "total_return_pct": round(total_return * 100.0, 4),
        "cagr_pct": round(cagr * 100.0, 4),
        "max_drawdown_pct": round(max_dd * 100.0, 4),
        "return_to_dd": round(total_return / max(max_dd, 1e-9), 4),
        "calmar": round(calmar, 4),
        "min_equity": round(min_equity, 6),
        "rebalance_count": sum(1 for sample in rebalance_samples) if rebalance_samples else 0,
        "win_rate_period": round(wins / max(wins + losses, 1), 4),
        "active_fraction": round(active_periods / max(period_count, 1), 4),
        "avg_gross_exposure": round(gross_sum / max(period_count, 1), 4),
        "avg_net_exposure": round(net_sum / max(period_count, 1), 4),
        "avg_short_exposure": round(short_sum / max(period_count, 1), 4),
        "turnover_sum": round(turnover_sum, 4),
        "avg_daily_turnover": round(turnover_sum / common_days, 4),
        "cost_drag_pct_simple_sum": round(cost_drag * 100.0, 4),
        "liquidity_impact_drag_pct_simple_sum": round(liquidity_impact_drag * 100.0, 4),
        "holding_cost_drag_pct_simple_sum": round(holding_cost_drag * 100.0, 4),
        "short_cost_drag_pct_simple_sum": round(short_cost_drag * 100.0, 4),
        "funding_pnl_pct_simple_sum": round(funding_pnl * 100.0, 4),
        "max_trade_volume_pct_seen": round(max_trade_volume_pct_seen, 6),
        "capacity_violation_count": int(capacity_violation_count),
        "capacity_cap_event_count": int(capacity_cap_event_count),
        "max_capacity_cap_requested_trade_volume_pct": round(max_capacity_cap_requested_trade_volume_pct, 6),
        "exchange_rule_adjustment_count": int(exchange_rule_adjustment_count),
        "exchange_rule_drop_count": int(exchange_rule_drop_count),
        "symbol_weight_cap_event_count": int(symbol_weight_cap_event_count),
        "worst_intrabar_adverse_return_pct": round(worst_intrabar_adverse_return * 100.0, 4),
        "liquidation_event_count": int(liquidation_event_count),
        "entry_grade_count": int(entry_grade_count),
        "entry_grade_avg_scale": round(float(entry_grade_avg_scale), 4),
        "entry_grade_min_scale_seen": round(float(entry_grade_min_scale_seen), 4),
        "entry_grade_max_scale_seen": round(float(entry_grade_max_scale_seen), 4),
        "entry_grade_avg_strength": round(float(entry_grade_avg_strength), 4),
        "market_stress_count": int(market_stress_count),
        "market_stress_active_count": int(market_stress_active_count),
        "market_stress_active_fraction": round(float(market_stress_active_count) / max(int(market_stress_count), 1), 4),
        "market_stress_avg_scale": round(float(market_stress_avg_scale), 4),
        "market_stress_avg_breadth": round(float(market_stress_avg_breadth), 4),
        "market_stress_avg_btcema": round(float(market_stress_avg_btcema), 4),
        "positive_year_count": sum(1 for value in by_year_return.values() if value > 0.0),
        "year_count": len(by_year_return),
        "positive_year_fraction": round(positive_year_fraction, 4),
        "by_year_return_pct": {key: round(value * 100.0, 4) for key, value in by_year_return.items()},
        "by_quarter_return_pct": {key: round(value * 100.0, 4) for key, value in by_quarter_return.items()},
        "by_month_return_pct": {key: round(value * 100.0, 4) for key, value in by_month_return.items()},
        "best_year_pct": round(max((value * 100.0 for value in by_year_return.values()), default=0.0), 4),
        "worst_year_pct": round(min((value * 100.0 for value in by_year_return.values()), default=0.0), 4),
        "direction_period_counts": dict(direction_periods),
        "top_symbol_contribution_pct_simple_sum": _top_items({symbol: value * 100.0 for symbol, value in symbol_contribution_sum.items()}, True),
        "bottom_symbol_contribution_pct_simple_sum": _top_items({symbol: value * 100.0 for symbol, value in symbol_contribution_sum.items()}, False),
        "top_symbol_exposure": top_exposure,
        "sleeves": [
            {
                "name": sleeve.name,
                "allocation": sleeve.allocation,
                "config": asdict(sleeve.config),
                "max_symbol_weight": sleeve.max_symbol_weight,
                "symbol_quality_lookback_hours": sleeve.symbol_quality_lookback_hours,
                "symbol_quality_drop_count": sleeve.symbol_quality_drop_count,
                "symbol_quality_block_symbol_events": sleeve.quality_block_symbol_events,
                "symbol_quality_top_block_counts": dict((sleeve.quality_block_counts or Counter()).most_common(10)),
            }
            for sleeve in sleeves
        ],
        "rebalance_samples": rebalance_samples[:8],
        "score": round(score, 8),
    }


def backtest_mix(
    frame: rot.MarketFrame,
    features: rot.FeatureBundle,
    sleeves: list[Sleeve],
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
    first_exec_ts: datetime | None = None
    last_period_ts: datetime | None = None
    by_year_start: dict[str, float] = {}
    by_year_end: dict[str, float] = {}
    by_month_start: dict[str, float] = {}
    by_month_end: dict[str, float] = {}
    by_quarter_start: dict[str, float] = {}
    by_quarter_end: dict[str, float] = {}
    direction_periods: Counter[str] = Counter()
    symbol_contribution_sum: dict[str, float] = {symbol: 0.0 for symbol in frame.symbols}
    symbol_abs_exposure_sum: dict[str, float] = {symbol: 0.0 for symbol in frame.symbols}
    symbol_long_periods: Counter[str] = Counter()
    symbol_short_periods: Counter[str] = Counter()
    realized_returns: deque[float] = deque(maxlen=rot._hours_to_bars(sleeves[0].config.interval, max(int(args.vol_lookback_hours), 1)))
    rebalance_samples: list[dict[str, Any]] = []
    rebalance_count = 0

    for exec_idx in range(first_exec_idx, last_exec_idx + 1):
        if first_exec_ts is None:
            first_exec_ts = frame.ts[exec_idx]
        should_rebalance = (exec_idx - first_exec_idx) % max(sleeves[0].config.rebalance_bars, 1) == 0
        turnover = 0.0
        if should_rebalance:
            signal_idx = exec_idx - 1
            sleeve_scaled_weights: list[dict[str, float]] = []
            old_sleeve_weights = [(sleeve, dict(sleeve.weights or {})) for sleeve in sleeves]
            for sleeve in sleeves:
                config = sleeve.config
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
                    config,
                    signal_idx,
                    funding_period_rates=funding_period_rates,
                    blocked_symbols=blocked_symbols,
                )
                risk_scale = 1.0
                live_drawdown = 1.0 - equity / max(peak, 1e-12)
                if args.drawdown_guard_pct > 0.0 and live_drawdown * 100.0 >= args.drawdown_guard_pct:
                    risk_scale *= max(float(args.drawdown_risk_scale), 0.0)
                if args.vol_target_annual_pct > 0.0 and len(realized_returns) >= max(10, realized_returns.maxlen // 2):
                    mean_return = sum(realized_returns) / len(realized_returns)
                    variance = sum((value - mean_return) * (value - mean_return) for value in realized_returns) / len(realized_returns)
                    period_vol = math.sqrt(max(variance, 0.0))
                    realized_vol = period_vol * math.sqrt(365.25 * 24.0 / max(rot._interval_hours(config.interval), 1e-9))
                    if realized_vol > 1e-9:
                        vol_scale = min(max((args.vol_target_annual_pct / 100.0) / realized_vol, args.vol_min_scale), args.vol_max_scale)
                        risk_scale *= vol_scale
                dispersion_value = rot._cross_sectional_momentum_dispersion(frame, features, config, signal_idx)
                history = sleeve.dispersion_history if sleeve.dispersion_history is not None else deque()
                if (
                    history.maxlen
                    and math.isfinite(dispersion_value)
                    and len(history) >= max(10, history.maxlen // 2)
                    and args.dispersion_guard_quantile > 0.0
                ):
                    threshold = rot._empirical_quantile(list(history), args.dispersion_guard_quantile)
                    if math.isfinite(threshold) and dispersion_value >= threshold:
                        risk_scale *= max(float(args.dispersion_risk_scale), 0.0)
                if history.maxlen and math.isfinite(dispersion_value):
                    history.append(dispersion_value)
                new_weights = rot._scale_weights(new_weights, risk_scale)
                if sleeve.max_symbol_weight > 0.0:
                    new_weights, cap_events = rot._clip_symbol_weights(new_weights, sleeve.max_symbol_weight)
                    symbol_weight_cap_event_count += cap_events
                sleeve_scaled_weights.append({symbol: weight * sleeve.allocation for symbol, weight in new_weights.items()})
            target_weights: dict[str, float] = {}
            for sleeve_weights in sleeve_scaled_weights:
                for symbol, weight in sleeve_weights.items():
                    target_weights[symbol] = target_weights.get(symbol, 0.0) + weight
            pre_rule_sleeve_weights = [
                (sleeve, dict(sleeve_weights))
                for sleeve, sleeve_weights in zip(sleeves, sleeve_scaled_weights, strict=True)
            ]
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
            pre_rule_total_by_symbol: dict[str, float] = {}
            for _, sleeve_weights in pre_rule_sleeve_weights:
                for symbol, weight in sleeve_weights.items():
                    pre_rule_total_by_symbol[symbol] = pre_rule_total_by_symbol.get(symbol, 0.0) + weight
            old_total_by_symbol: dict[str, float] = {}
            for _, sleeve_weights in old_sleeve_weights:
                for symbol, weight in sleeve_weights.items():
                    old_total_by_symbol[symbol] = old_total_by_symbol.get(symbol, 0.0) + weight
            old_weights_by_sleeve = {id(sleeve): sleeve_weights for sleeve, sleeve_weights in old_sleeve_weights}
            all_target_symbols = set(target_weights) | set(pre_rule_total_by_symbol) | set(old_total_by_symbol)
            for sleeve, sleeve_weights in pre_rule_sleeve_weights:
                old_weights = old_weights_by_sleeve.get(id(sleeve), {})
                effective_weights: dict[str, float] = {}
                for symbol in all_target_symbols:
                    sleeve_weight = sleeve_weights.get(symbol, 0.0)
                    old_sleeve_weight = old_weights.get(symbol, 0.0)
                    pre_rule_total = pre_rule_total_by_symbol.get(symbol, 0.0)
                    old_total = old_total_by_symbol.get(symbol, 0.0)
                    final_weight = target_weights.get(symbol, 0.0)
                    if abs(pre_rule_total) <= 1e-12 or abs(final_weight) <= 1e-12:
                        if abs(pre_rule_total) > 1e-12 and abs(final_weight) > 1e-12:
                            effective = final_weight * sleeve_weight / pre_rule_total
                        elif abs(old_total) > 1e-12 and abs(final_weight) > 1e-12:
                            effective = final_weight * old_sleeve_weight / old_total
                        else:
                            effective = 0.0
                    else:
                        delta_total = pre_rule_total - old_total
                        if abs(delta_total) > 1e-12:
                            scale = (final_weight - old_total) / delta_total
                            effective = old_sleeve_weight + scale * (sleeve_weight - old_sleeve_weight)
                        else:
                            effective = final_weight * sleeve_weight / pre_rule_total
                    if abs(effective) > 1e-12:
                        effective_weights[symbol] = effective
                sleeve.weights = effective_weights
            turnover = rot._turnover(combined_weights, target_weights, frame.symbols)
            liquidity_cost_period = 0.0
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
            if turnover > 1e-9:
                rebalance_count += 1
                if len(rebalance_samples) < 8:
                    rebalance_samples.append(
                        {
                            "exec_ts": frame.ts[exec_idx].isoformat(),
                            "signal_ts": frame.ts[signal_idx].isoformat(),
                            "turnover": round(turnover, 4),
                            "weights": rot._weights_sample(target_weights),
                        }
                    )
            combined_weights = target_weights
        else:
            liquidity_cost_period = 0.0

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
        intrabar_adverse_equity_return = rot._basis_return_to_equity_return(
            rot._intrabar_adverse_return(frame, combined_weights, exec_idx),
            equity=equity,
            pnl_notional_mode=args.pnl_notional_mode,
        )
        worst_intrabar_adverse_return = min(worst_intrabar_adverse_return, intrabar_adverse_equity_return)
        if args.maintenance_margin_pct > 0.0 and intrabar_adverse_equity_return <= -(1.0 - args.maintenance_margin_pct / 100.0):
            liquidation_event_count += 1
        portfolio_return = 0.0
        period_symbol_contribution: dict[str, float] = {}
        period_symbol_abs_exposure: dict[str, float] = {}
        for symbol, weight in combined_weights.items():
            symbol_return = frame.returns[symbol][exec_idx]
            if not math.isfinite(symbol_return):
                continue
            contribution = weight * symbol_return
            portfolio_return += contribution
            period_symbol_contribution[symbol] = period_symbol_contribution.get(symbol, 0.0) + contribution
            period_symbol_abs_exposure[symbol] = period_symbol_abs_exposure.get(symbol, 0.0) + abs(weight)
            symbol_contribution_sum[symbol] = symbol_contribution_sum.get(symbol, 0.0) + contribution
            symbol_abs_exposure_sum[symbol] = symbol_abs_exposure_sum.get(symbol, 0.0) + abs(weight)
            if weight > 0.0:
                symbol_long_periods[symbol] += 1
            elif weight < 0.0:
                symbol_short_periods[symbol] += 1
        for sleeve in sleeves:
            if sleeve.symbol_quality_lookback_hours <= 0:
                continue
            sleeve_w = sleeve.weights or {}
            for symbol in frame.symbols:
                weight = sleeve_w.get(symbol, 0.0)
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
        basis_return = portfolio_return + funding_period - cost_period - liquidity_cost_period - holding_cost_period - short_cost_period
        net_return = rot._basis_return_to_equity_return(basis_return, equity=equity, pnl_notional_mode=args.pnl_notional_mode)
        if gross_exposure > 1e-9:
            active_periods += 1
        if net_exposure > 0.05:
            direction_periods["net_long"] += 1
        elif net_exposure < -0.05:
            direction_periods["net_short"] += 1
        else:
            direction_periods["market_neutral_or_flat"] += 1
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
        if equity <= 1e-8:
            break

    out = _summary(
        model_id=f"mix:{args.mix}",
        frame=frame,
        first_exec_ts=first_exec_ts,
        last_period_ts=last_period_ts,
        equity=equity,
        peak=peak,
        min_equity=min_equity,
        wins=wins,
        losses=losses,
        period_count=period_count,
        active_periods=active_periods,
        turnover_sum=turnover_sum,
        cost_drag=cost_drag,
        liquidity_impact_drag=liquidity_impact_drag,
        holding_cost_drag=holding_cost_drag,
        short_cost_drag=short_cost_drag,
        funding_pnl=funding_pnl,
        gross_sum=gross_sum,
        net_sum=net_sum,
        short_sum=short_sum,
        max_dd=max_dd,
        worst_intrabar_adverse_return=worst_intrabar_adverse_return,
        liquidation_event_count=liquidation_event_count,
        max_trade_volume_pct_seen=max_trade_volume_pct_seen,
        capacity_violation_count=capacity_violation_count,
        capacity_cap_event_count=capacity_cap_event_count,
        max_capacity_cap_requested_trade_volume_pct=max_capacity_cap_requested_trade_volume_pct,
        exchange_rule_adjustment_count=exchange_rule_adjustment_count,
        exchange_rule_drop_count=exchange_rule_drop_count,
        symbol_weight_cap_event_count=symbol_weight_cap_event_count,
        by_year_start=by_year_start,
        by_year_end=by_year_end,
        by_month_start=by_month_start,
        by_month_end=by_month_end,
        by_quarter_start=by_quarter_start,
        by_quarter_end=by_quarter_end,
        direction_periods=direction_periods,
        symbol_contribution_sum=symbol_contribution_sum,
        symbol_abs_exposure_sum=symbol_abs_exposure_sum,
        symbol_long_periods=symbol_long_periods,
        symbol_short_periods=symbol_short_periods,
        sleeves=sleeves,
        rebalance_samples=rebalance_samples,
    )
    out["rebalance_count"] = rebalance_count
    return out


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
    frame, status = rot._align_dynamic_frame(args.interval, bars_by_symbol)
    if frame is None:
        raise RuntimeError(f"failed to align frame: {status}")
    sleeves = _build_sleeves(args.mix, frame, args.dispersion_lookback_rebalances)
    features = rot._build_features(frame, [sleeve.config for sleeve in sleeves])
    funding_period_rates: dict[str, list[float]] | None = None
    if args.apply_funding:
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
    exchange_rules = (
        rot._load_exchange_rules(base_url=base_url, cache_path=ROOT_DIR / str(args.exchange_rules_cache))
        if args.apply_exchange_rules
        else {}
    )
    summary = backtest_mix(
        frame,
        features,
        sleeves,
        args=args,
        funding_period_rates=funding_period_rates,
        exchange_rules=exchange_rules,
    )
    output = {
        "schema_version": "multi_asset_rotation_mix_backtest_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "authority": "research_only_no_live_authority_change",
        "scope": {
            "symbols": frame.symbols,
            "days": int(args.days),
            "interval": args.interval,
            "align_mode": "dynamic",
        },
        "data_status": {args.interval: status},
        "cost_model": {
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": float(args.slippage_bps_per_side),
            "apply_funding": bool(args.apply_funding),
            "drawdown_guard_pct": float(args.drawdown_guard_pct),
            "drawdown_risk_scale": float(args.drawdown_risk_scale),
            "vol_target_annual_pct": float(args.vol_target_annual_pct),
            "dispersion_lookback_rebalances": int(args.dispersion_lookback_rebalances),
            "dispersion_guard_quantile": float(args.dispersion_guard_quantile),
            "dispersion_risk_scale": float(args.dispersion_risk_scale),
            "assumed_capital_usd": float(args.assumed_capital_usd),
            "pnl_notional_mode": str(args.pnl_notional_mode),
            "liquidity_notional_mode": str(args.liquidity_notional_mode),
            "liquidity_impact_bps_per_1pct_volume": float(args.liquidity_impact_bps_per_1pct_volume),
            "max_trade_volume_pct": float(args.max_trade_volume_pct),
            "capacity_cap_trade_volume_pct": float(args.capacity_cap_trade_volume_pct),
            "apply_exchange_rules": bool(args.apply_exchange_rules),
        },
        "all_results": [{"config": {"mix": args.mix}, "summary": summary}],
    }
    if args.write_report:
        report_dir = ROOT_DIR / str(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = report_dir / f"multi_asset_rotation_mix_backtest_{stamp}.json"
        latest = report_dir / "latest.json"
        output["report_path"] = str(path.relative_to(ROOT_DIR))
        output["latest_report_path"] = str(latest.relative_to(ROOT_DIR))
        text = json.dumps(output, ensure_ascii=False, indent=2)
        atomic_write_text(path, text)
        atomic_write_text(latest, text)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
