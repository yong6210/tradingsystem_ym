#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, deque
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text
from scripts import run_multi_asset_rotation_search as rot
from scripts.run_btc_flip_rotation_search import _INTERVAL_MS, _csv


SYMBOLS_36 = (
    "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,"
    "LINKUSDT,AVAXUSDT,BCHUSDT,LTCUSDT,NEARUSDT,AAVEUSDT,APTUSDT,"
    "ARBUSDT,ATOMUSDT,DASHUSDT,DOTUSDT,ETCUSDT,FETUSDT,FILUSDT,"
    "HBARUSDT,ICPUSDT,INJUSDT,PENDLEUSDT,QNTUSDT,RUNEUSDT,SUIUSDT,"
    "UNIUSDT,XLMUSDT,ZECUSDT,1000SHIBUSDT,TAOUSDT,1000FLOKIUSDT,"
    "STXUSDT,OPUSDT"
)


@dataclass(frozen=True, slots=True)
class ExternalStrategyConfig:
    model_id: str
    interval: str
    mode: str
    lookback_hours: int
    lookback_bars: int
    exit_hours: int
    exit_bars: int
    fast_hours: int
    fast_bars: int
    slow_hours: int
    slow_bars: int
    rebalance_hours: int
    rebalance_bars: int
    top_k: int
    gross_leverage: float
    vol_weight: bool
    min_symbol_age_hours: int
    min_symbol_age_bars: int


@dataclass(slots=True)
class IndicatorCache:
    sma: dict[int, dict[str, list[float]]]
    ema: dict[int, dict[str, list[float]]]
    std: dict[int, dict[str, list[float]]]
    vwap: dict[int, dict[str, list[float]]]
    volume_sma: dict[int, dict[str, list[float]]]
    ratio_z: dict[int, dict[str, list[float]]]
    rsi: dict[int, dict[str, list[float]]]
    adx: dict[int, dict[str, list[float]]]
    atr: dict[int, dict[str, list[float]]]
    rolling_high: dict[int, dict[str, list[float]]]
    rolling_low: dict[int, dict[str, list[float]]]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Research-only external strategy zoo: Donchian, MA, RSI/ADX, Bollinger mean-reversion, "
            "supertrend, and scorecard-style verified-method ensembles."
        )
    )
    parser.add_argument("--symbols", default=SYMBOLS_36)
    parser.add_argument("--days", type=int, default=1825)
    parser.add_argument("--interval", default="4h")
    parser.add_argument(
        "--modes",
        default=(
            "btc_sma_long,btc_ma_cross_long,btc_ma_cross_flip,donchian_btc_long,"
            "donchian_btc_flip,donchian_xs_long,rsi_adx_btc,bb_rsi_mr,supertrend_btc_long"
            ",combo_donchian_rsi,combo_donchian_sma,combo_donchian_supertrend"
            ",macd_adx_btc,macd_adx_xs,stochrsi_supertrend_btc,vwap_breakout_xs"
            ",volume_breakout_xs,ratio_reversal_btc,ratio_momentum_btc"
        ),
    )
    parser.add_argument("--lookback-hours", default="168,336,720,1200")
    parser.add_argument("--exit-hours", default="72,168,336")
    parser.add_argument("--fast-hours", default="72,168")
    parser.add_argument("--slow-hours", default="336,720,1200")
    parser.add_argument("--rebalance-hours", default="4,24")
    parser.add_argument("--top-k", default="1,2,4,6")
    parser.add_argument("--gross-leverage", default="1.0,1.5,2.2,3.0")
    parser.add_argument("--vol-weight", default="false,true")
    parser.add_argument("--min-symbol-age-hours", default="720,1440")
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument("--holding-cost-bps-per-day", type=float, default=0.0)
    parser.add_argument("--short-cost-bps-per-day", type=float, default=0.0)
    parser.add_argument("--drawdown-guard-pct", type=float, default=12.0)
    parser.add_argument("--drawdown-risk-scale", type=float, default=0.25)
    parser.add_argument("--vol-target-annual-pct", type=float, default=45.0)
    parser.add_argument("--vol-lookback-hours", type=int, default=720)
    parser.add_argument("--vol-min-scale", type=float, default=0.0)
    parser.add_argument("--vol-max-scale", type=float, default=1.0)
    parser.add_argument("--max-symbol-weight", type=float, default=0.75)
    parser.add_argument("--assumed-capital-usd", type=float, default=100000.0)
    parser.add_argument(
        "--pnl-notional-mode",
        choices=(
            "compounded",
            "starting",
            "profit25",
            "profit50",
            "profit55",
            "profit60",
            "profit65",
            "profit70",
            "profit75",
            "profit80",
            "profit85",
            "profit90",
            "profit95",
        ),
        default="profit95",
    )
    parser.add_argument(
        "--liquidity-notional-mode",
        choices=(
            "compounded",
            "starting",
            "profit25",
            "profit50",
            "profit55",
            "profit60",
            "profit65",
            "profit70",
            "profit75",
            "profit80",
            "profit85",
            "profit90",
            "profit95",
        ),
        default="profit95",
    )
    parser.add_argument("--liquidity-impact-bps-per-1pct-volume", type=float, default=0.25)
    parser.add_argument("--capacity-cap-trade-volume-pct", type=float, default=0.5)
    parser.add_argument("--min-common-days", type=int, default=1000)
    parser.add_argument("--max-models", type=int, default=0)
    parser.add_argument("--cache-dir", default="reports/validation/multi_asset_rotation_search/cache")
    parser.add_argument("--report-dir", default="reports/validation/external_strategy_zoo")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _parse_int_csv(raw: str, *, minimum: int = 0) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for item in _csv(raw):
        try:
            value = int(float(item))
        except ValueError:
            continue
        if value >= minimum and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _parse_float_csv(raw: str, *, minimum: float = 0.0) -> list[float]:
    out: list[float] = []
    seen: set[float] = set()
    for item in _csv(raw):
        try:
            value = float(item)
        except ValueError:
            continue
        if value >= minimum and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _parse_bool_csv(raw: str) -> list[bool]:
    values: list[bool] = []
    for item in _csv(raw):
        value = item.strip().lower() in {"1", "true", "t", "yes", "y"}
        if value not in values:
            values.append(value)
    return values or [False]


def _rolling_mean(values: list[float], length: int) -> list[float]:
    length = max(int(length), 1)
    out = [math.nan] * len(values)
    q: deque[float] = deque()
    total = 0.0
    finite_count = 0
    for idx, value in enumerate(values):
        if math.isfinite(value):
            q.append(value)
            total += value
            finite_count += 1
        else:
            q.append(math.nan)
        if len(q) > length:
            old = q.popleft()
            if math.isfinite(old):
                total -= old
                finite_count -= 1
        if finite_count >= length:
            out[idx] = total / finite_count
    return out


def _rolling_std(values: list[float], length: int) -> list[float]:
    length = max(int(length), 2)
    out = [math.nan] * len(values)
    q: deque[float] = deque()
    total = 0.0
    total_sq = 0.0
    finite_count = 0
    for idx, value in enumerate(values):
        if math.isfinite(value):
            q.append(value)
            total += value
            total_sq += value * value
            finite_count += 1
        else:
            q.append(math.nan)
        if len(q) > length:
            old = q.popleft()
            if math.isfinite(old):
                total -= old
                total_sq -= old * old
                finite_count -= 1
        if finite_count >= length:
            mean = total / finite_count
            variance = max(total_sq / finite_count - mean * mean, 0.0)
            out[idx] = math.sqrt(variance)
    return out


def _rolling_vwap(closes: list[float], volumes: list[float], length: int) -> list[float]:
    length = max(int(length), 1)
    out = [math.nan] * len(closes)
    price_volume_q: deque[float] = deque()
    volume_q: deque[float] = deque()
    price_volume_sum = 0.0
    volume_sum = 0.0
    finite_count = 0
    for idx, (close, volume) in enumerate(zip(closes, volumes, strict=False)):
        if math.isfinite(close) and close > 0.0 and math.isfinite(volume) and volume > 0.0:
            price_volume = close * volume
            price_volume_q.append(price_volume)
            volume_q.append(volume)
            price_volume_sum += price_volume
            volume_sum += volume
            finite_count += 1
        else:
            price_volume_q.append(math.nan)
            volume_q.append(math.nan)
        if len(price_volume_q) > length:
            old_pv = price_volume_q.popleft()
            old_volume = volume_q.popleft()
            if math.isfinite(old_pv):
                price_volume_sum -= old_pv
            if math.isfinite(old_volume):
                volume_sum -= old_volume
                finite_count -= 1
        if finite_count >= length and volume_sum > 0.0:
            out[idx] = price_volume_sum / volume_sum
    return out


def _ratio_z_series(frame: rot.MarketFrame, symbol: str, market_symbol: str, length: int) -> list[float]:
    ratios: list[float] = []
    for left, right in zip(frame.closes[symbol], frame.closes[market_symbol], strict=False):
        if math.isfinite(left) and left > 0.0 and math.isfinite(right) and right > 0.0:
            ratios.append(math.log(left / right))
        else:
            ratios.append(math.nan)
    means = _rolling_mean(ratios, length)
    stds = _rolling_std(ratios, max(length, 2))
    out = [math.nan] * len(ratios)
    for idx, value in enumerate(ratios):
        mean = means[idx]
        std = stds[idx]
        if math.isfinite(value) and math.isfinite(mean) and math.isfinite(std) and std > 1e-12:
            out[idx] = (value - mean) / std
    return out


def _rolling_extreme_shifted(values: list[float], length: int, *, highest: bool) -> list[float]:
    length = max(int(length), 1)
    out = [math.nan] * len(values)
    q: deque[tuple[int, bool]] = deque()
    mono: deque[tuple[int, float]] = deque()
    finite_count = 0
    for idx, value in enumerate(values):
        stale_before = idx - length
        while q and q[0][0] < stale_before:
            _, was_finite = q.popleft()
            if was_finite:
                finite_count -= 1
        while mono and mono[0][0] < stale_before:
            mono.popleft()
        if finite_count >= length and mono:
            out[idx] = mono[0][1]

        is_finite = math.isfinite(value)
        q.append((idx, is_finite))
        if not is_finite:
            continue
        finite_count += 1
        if highest:
            while mono and mono[-1][1] <= value:
                mono.pop()
        else:
            while mono and mono[-1][1] >= value:
                mono.pop()
        mono.append((idx, value))
    return out


def _rsi(values: list[float], length: int) -> list[float]:
    length = max(int(length), 2)
    out = [math.nan] * len(values)
    gains: deque[float] = deque()
    losses: deque[float] = deque()
    gain_sum = 0.0
    loss_sum = 0.0
    for idx in range(1, len(values)):
        prev = values[idx - 1]
        current = values[idx]
        if not (math.isfinite(prev) and math.isfinite(current)):
            gain = 0.0
            loss = 0.0
        else:
            delta = current - prev
            gain = max(delta, 0.0)
            loss = max(-delta, 0.0)
        gains.append(gain)
        losses.append(loss)
        gain_sum += gain
        loss_sum += loss
        if len(gains) > length:
            gain_sum -= gains.popleft()
            loss_sum -= losses.popleft()
        if len(gains) >= length:
            avg_gain = gain_sum / length
            avg_loss = loss_sum / length
            if avg_loss <= 1e-12:
                out[idx] = 100.0
            else:
                rs = avg_gain / avg_loss
                out[idx] = 100.0 - 100.0 / (1.0 + rs)
    return out


def _true_range(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    out = [math.nan] * len(closes)
    for idx in range(len(closes)):
        high = highs[idx]
        low = lows[idx]
        prev_close = closes[idx - 1] if idx > 0 else closes[idx]
        if math.isfinite(high) and math.isfinite(low) and math.isfinite(prev_close):
            out[idx] = max(high - low, abs(high - prev_close), abs(low - prev_close))
    return out


def _adx(highs: list[float], lows: list[float], closes: list[float], length: int) -> tuple[list[float], list[float]]:
    length = max(int(length), 2)
    tr = _true_range(highs, lows, closes)
    atr = _rolling_mean(tr, length)
    plus_dm = [0.0] * len(closes)
    minus_dm = [0.0] * len(closes)
    for idx in range(1, len(closes)):
        up_move = highs[idx] - highs[idx - 1] if math.isfinite(highs[idx]) and math.isfinite(highs[idx - 1]) else math.nan
        down_move = lows[idx - 1] - lows[idx] if math.isfinite(lows[idx]) and math.isfinite(lows[idx - 1]) else math.nan
        if math.isfinite(up_move) and math.isfinite(down_move):
            plus_dm[idx] = up_move if up_move > down_move and up_move > 0.0 else 0.0
            minus_dm[idx] = down_move if down_move > up_move and down_move > 0.0 else 0.0
    plus_avg = _rolling_mean(plus_dm, length)
    minus_avg = _rolling_mean(minus_dm, length)
    dx = [math.nan] * len(closes)
    for idx in range(len(closes)):
        if not (math.isfinite(atr[idx]) and atr[idx] > 0.0):
            continue
        plus_di = 100.0 * plus_avg[idx] / atr[idx]
        minus_di = 100.0 * minus_avg[idx] / atr[idx]
        denom = plus_di + minus_di
        if denom > 1e-12:
            dx[idx] = 100.0 * abs(plus_di - minus_di) / denom
    return _rolling_mean(dx, length), atr


def _supertrend_direction(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    atr: list[float],
    *,
    multiplier: float = 3.0,
) -> list[int]:
    direction = [0] * len(closes)
    final_upper = [math.nan] * len(closes)
    final_lower = [math.nan] * len(closes)
    for idx in range(len(closes)):
        if not (
            math.isfinite(highs[idx])
            and math.isfinite(lows[idx])
            and math.isfinite(closes[idx])
            and math.isfinite(atr[idx])
            and atr[idx] > 0.0
        ):
            direction[idx] = direction[idx - 1] if idx > 0 else 0
            continue
        hl2 = (highs[idx] + lows[idx]) / 2.0
        upper = hl2 + multiplier * atr[idx]
        lower = hl2 - multiplier * atr[idx]
        if idx == 0 or not math.isfinite(final_upper[idx - 1]):
            final_upper[idx] = upper
            final_lower[idx] = lower
            direction[idx] = 1 if closes[idx] >= hl2 else -1
            continue
        prev_close = closes[idx - 1]
        final_upper[idx] = upper if upper < final_upper[idx - 1] or prev_close > final_upper[idx - 1] else final_upper[idx - 1]
        final_lower[idx] = lower if lower > final_lower[idx - 1] or prev_close < final_lower[idx - 1] else final_lower[idx - 1]
        if closes[idx] > final_upper[idx - 1]:
            direction[idx] = 1
        elif closes[idx] < final_lower[idx - 1]:
            direction[idx] = -1
        else:
            direction[idx] = direction[idx - 1]
    return direction


def _build_configs(args: argparse.Namespace) -> list[ExternalStrategyConfig]:
    interval = str(args.interval)
    modes = [
        mode
        for mode in _csv(args.modes)
        if mode
        in {
            "btc_sma_long",
            "btc_sma_flip",
            "btc_ma_cross_long",
            "btc_ma_cross_flip",
            "donchian_btc_long",
            "donchian_btc_flip",
            "donchian_xs_long",
            "rsi_adx_btc",
            "bb_rsi_mr",
            "supertrend_btc_long",
            "combo_donchian_rsi",
            "combo_donchian_sma",
            "combo_donchian_supertrend",
            "scorecard_momentum",
            "scorecard_breakout",
            "macd_adx_btc",
            "macd_adx_xs",
            "stochrsi_supertrend_btc",
            "vwap_breakout_xs",
            "volume_breakout_xs",
            "ratio_reversal_btc",
            "ratio_momentum_btc",
        }
    ]
    lookbacks = _parse_int_csv(args.lookback_hours, minimum=1) or [336]
    exits = _parse_int_csv(args.exit_hours, minimum=1) or [168]
    fasts = _parse_int_csv(args.fast_hours, minimum=1) or [168]
    slows = _parse_int_csv(args.slow_hours, minimum=1) or [720]
    rebalances = _parse_int_csv(args.rebalance_hours, minimum=1) or [24]
    top_ks = _parse_int_csv(args.top_k, minimum=1) or [1]
    gross_values = _parse_float_csv(args.gross_leverage, minimum=0.01) or [1.0]
    vol_weights = _parse_bool_csv(args.vol_weight)
    ages = _parse_int_csv(args.min_symbol_age_hours, minimum=0) or [0]

    configs: list[ExternalStrategyConfig] = []
    for mode in modes:
        for lookback in lookbacks:
            for exit_hours in exits:
                if mode.startswith("donchian") and exit_hours > lookback:
                    continue
                for fast in fasts:
                    for slow in slows:
                        if mode.startswith("btc_ma_cross") and fast >= slow:
                            continue
                        for rebalance in rebalances:
                            for top_k in top_ks:
                                if mode.startswith("btc_") or mode in {
                                    "donchian_btc_long",
                                    "donchian_btc_flip",
                                    "rsi_adx_btc",
                                    "supertrend_btc_long",
                                    "macd_adx_btc",
                                    "stochrsi_supertrend_btc",
                                }:
                                    if top_k != top_ks[0]:
                                        continue
                                for gross in gross_values:
                                    for vol_weight in vol_weights:
                                        for age in ages:
                                            model_id = (
                                                f"{interval}:{mode}:lb{lookback}h:exit{exit_hours}h:"
                                                f"fast{fast}h:slow{slow}h:k{top_k}:rb{rebalance}h:"
                                                f"volw{int(vol_weight)}:age{age}h:gross{gross:g}"
                                            )
                                            configs.append(
                                                ExternalStrategyConfig(
                                                    model_id=model_id,
                                                    interval=interval,
                                                    mode=mode,
                                                    lookback_hours=lookback,
                                                    lookback_bars=rot._hours_to_bars(interval, lookback),
                                                    exit_hours=exit_hours,
                                                    exit_bars=rot._hours_to_bars(interval, exit_hours),
                                                    fast_hours=fast,
                                                    fast_bars=rot._hours_to_bars(interval, fast),
                                                    slow_hours=slow,
                                                    slow_bars=rot._hours_to_bars(interval, slow),
                                                    rebalance_hours=rebalance,
                                                    rebalance_bars=rot._hours_to_bars(interval, rebalance),
                                                    top_k=top_k,
                                                    gross_leverage=float(gross),
                                                    vol_weight=vol_weight,
                                                    min_symbol_age_hours=age,
                                                    min_symbol_age_bars=rot._hours_to_bars(interval, age) if age > 0 else 0,
                                                )
                                            )
    if int(args.max_models or 0) > 0:
        return configs[: int(args.max_models)]
    return configs


def _build_indicators(frame: rot.MarketFrame, configs: list[ExternalStrategyConfig]) -> IndicatorCache:
    flat_lengths = sorted(
        {
            value
            for config in configs
            for value in (
                2,
                7,
                config.lookback_bars,
                config.exit_bars,
                config.fast_bars,
                config.slow_bars,
                max(config.fast_bars, 2),
                max(config.slow_bars, 2),
            )
        }
    )
    sma: dict[int, dict[str, list[float]]] = {}
    ema: dict[int, dict[str, list[float]]] = {}
    std: dict[int, dict[str, list[float]]] = {}
    vwap: dict[int, dict[str, list[float]]] = {}
    volume_sma: dict[int, dict[str, list[float]]] = {}
    ratio_z: dict[int, dict[str, list[float]]] = {}
    rsi: dict[int, dict[str, list[float]]] = {}
    adx: dict[int, dict[str, list[float]]] = {}
    atr: dict[int, dict[str, list[float]]] = {}
    rolling_high: dict[int, dict[str, list[float]]] = {}
    rolling_low: dict[int, dict[str, list[float]]] = {}
    market_symbol = "BTCUSDT" if "BTCUSDT" in frame.symbols else frame.symbols[0]
    for length in flat_lengths:
        sma[length] = {}
        ema[length] = {}
        std[length] = {}
        vwap[length] = {}
        volume_sma[length] = {}
        ratio_z[length] = {}
        rsi[length] = {}
        adx[length] = {}
        atr[length] = {}
        rolling_high[length] = {}
        rolling_low[length] = {}
        for symbol in frame.symbols:
            closes = frame.closes[symbol]
            sma[length][symbol] = _rolling_mean(closes, length)
            ema[length][symbol] = rot._ema(closes, length)
            std[length][symbol] = _rolling_std(closes, length)
            vwap[length][symbol] = _rolling_vwap(closes, frame.volumes[symbol], length)
            volume_sma[length][symbol] = _rolling_mean(frame.volumes[symbol], length)
            ratio_z[length][symbol] = _ratio_z_series(frame, symbol, market_symbol, length) if symbol != market_symbol else [math.nan] * len(closes)
            rsi[length][symbol] = _rsi(closes, length)
            adx_series, atr_series = _adx(frame.highs[symbol], frame.lows[symbol], closes, length)
            adx[length][symbol] = adx_series
            atr[length][symbol] = atr_series
            rolling_high[length][symbol] = _rolling_extreme_shifted(closes, length, highest=True)
            rolling_low[length][symbol] = _rolling_extreme_shifted(closes, length, highest=False)
    return IndicatorCache(
        sma=sma,
        ema=ema,
        std=std,
        vwap=vwap,
        volume_sma=volume_sma,
        ratio_z=ratio_z,
        rsi=rsi,
        adx=adx,
        atr=atr,
        rolling_high=rolling_high,
        rolling_low=rolling_low,
    )


def _eligible_symbols(frame: rot.MarketFrame, config: ExternalStrategyConfig, signal_idx: int) -> list[str]:
    out: list[str] = []
    for symbol in frame.symbols:
        first_valid = frame.first_valid_index.get(symbol)
        if first_valid is None or signal_idx - first_valid < config.min_symbol_age_bars:
            continue
        close = frame.closes[symbol][signal_idx]
        if math.isfinite(close) and close > 0.0:
            out.append(symbol)
    return out


def _normalize_weights(rows: list[tuple[str, float, float]], *, gross: float, vol_weight: bool) -> dict[str, float]:
    raw: list[tuple[str, float]] = []
    for symbol, side, vol in rows:
        unit = 1.0 / max(vol, 1e-5) if vol_weight and math.isfinite(vol) and vol > 0.0 else 1.0
        raw.append((symbol, side * min(unit, 100_000.0)))
    total = sum(abs(value) for _, value in raw)
    if total <= 1e-12:
        return {}
    return {symbol: float(gross) * value / total for symbol, value in raw if abs(value) > 1e-12}


def _scorecard_rows(
    frame: rot.MarketFrame,
    indicators: IndicatorCache,
    config: ExternalStrategyConfig,
    signal_idx: int,
    *,
    require_breakout_position: dict[str, int] | None = None,
) -> list[tuple[str, float, float]]:
    rows: list[tuple[str, float, float]] = []
    for symbol in _eligible_symbols(frame, config, signal_idx):
        if require_breakout_position is not None and int(require_breakout_position.get(symbol, 0)) <= 0:
            continue
        past_idx = signal_idx - config.lookback_bars
        if past_idx < 0:
            continue
        symbol_close = frame.closes[symbol][signal_idx]
        past_close = frame.closes[symbol][past_idx]
        slow_sma = indicators.sma[config.slow_bars][symbol][signal_idx]
        rsi_value = indicators.rsi[max(config.exit_bars, 2)][symbol][signal_idx]
        adx_value = indicators.adx[max(config.exit_bars, 2)][symbol][signal_idx]
        atr_value = indicators.atr[max(config.exit_bars, 2)][symbol][signal_idx]
        if not (
            math.isfinite(symbol_close)
            and symbol_close > 0.0
            and math.isfinite(past_close)
            and past_close > 0.0
            and math.isfinite(slow_sma)
            and slow_sma > 0.0
            and math.isfinite(rsi_value)
            and math.isfinite(adx_value)
            and math.isfinite(atr_value)
            and atr_value > 0.0
        ):
            continue
        lookback_return = symbol_close / past_close - 1.0
        trend_gap = symbol_close / slow_sma - 1.0
        atr_pct = atr_value / symbol_close
        if lookback_return <= 0.0 or trend_gap <= 0.0 or rsi_value < 45.0 or adx_value < 15.0:
            continue
        trend_strength = min(max(adx_value / 35.0, 0.0), 2.0)
        rsi_balance = 1.0 - min(abs(rsi_value - 60.0) / 40.0, 1.0)
        score = 0.55 * lookback_return + 0.25 * trend_gap + 0.15 * trend_strength + 0.05 * rsi_balance - 1.25 * atr_pct
        if score > 0.0:
            rows.append((symbol, score, atr_pct))
    return rows


def _ratio_zscore(frame: rot.MarketFrame, symbol: str, market_symbol: str, signal_idx: int, lookback: int) -> float:
    start = max(0, signal_idx - max(int(lookback), 2) + 1)
    values: list[float] = []
    for idx in range(start, signal_idx + 1):
        left = frame.closes[symbol][idx]
        right = frame.closes[market_symbol][idx]
        if math.isfinite(left) and left > 0.0 and math.isfinite(right) and right > 0.0:
            values.append(math.log(left / right))
    if len(values) < max(20, min(int(lookback), 120) // 2):
        return math.nan
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    std = math.sqrt(max(variance, 0.0))
    if std <= 1e-12:
        return math.nan
    return (values[-1] - mean) / std


def _stoch_rsi_value(indicators: IndicatorCache, config: ExternalStrategyConfig, symbol: str, signal_idx: int) -> float:
    length = max(config.exit_bars, 2)
    series = indicators.rsi[length][symbol]
    start = max(0, signal_idx - length + 1)
    values = [value for value in series[start : signal_idx + 1] if math.isfinite(value)]
    current = series[signal_idx]
    if len(values) < max(5, length // 2) or not math.isfinite(current):
        return math.nan
    low = min(values)
    high = max(values)
    if high - low <= 1e-12:
        return math.nan
    return (current - low) / (high - low)


def _target_weights(
    frame: rot.MarketFrame,
    indicators: IndicatorCache,
    config: ExternalStrategyConfig,
    signal_idx: int,
    state: dict[str, Any],
) -> dict[str, float]:
    market_symbol = "BTCUSDT" if "BTCUSDT" in frame.symbols else frame.symbols[0]
    close = frame.closes[market_symbol][signal_idx]
    if not math.isfinite(close):
        return {}

    gross = max(float(config.gross_leverage), 0.0)
    if config.mode in {"combo_donchian_rsi", "combo_donchian_sma", "combo_donchian_supertrend"}:
        # External-source ensemble: a diversified Donchian/Turtle sleeve carries the
        # trend edge, while a simple BTC trend sleeve stabilizes the market regime.
        donchian_cfg = replace(config, mode="donchian_xs_long", gross_leverage=gross * 0.75)
        if config.mode == "combo_donchian_rsi":
            btc_cfg = replace(config, mode="rsi_adx_btc", gross_leverage=gross * 0.25)
        elif config.mode == "combo_donchian_sma":
            btc_cfg = replace(config, mode="btc_sma_long", gross_leverage=gross * 0.25)
        else:
            btc_cfg = replace(config, mode="supertrend_btc_long", gross_leverage=gross * 0.25)
        combined: dict[str, float] = {}
        for sleeve_name, sleeve_cfg in (("donchian", donchian_cfg), ("btc", btc_cfg)):
            sleeve_state = state.setdefault(sleeve_name, {})
            sleeve_weights = _target_weights(frame, indicators, sleeve_cfg, signal_idx, sleeve_state)
            for symbol, value in sleeve_weights.items():
                combined[symbol] = combined.get(symbol, 0.0) + value
        return {symbol: value for symbol, value in combined.items() if abs(value) > 1e-12}

    if config.mode == "btc_sma_long":
        sma = indicators.sma[config.slow_bars][market_symbol][signal_idx]
        return {market_symbol: gross} if math.isfinite(sma) and close > sma else {}

    if config.mode == "btc_sma_flip":
        sma = indicators.sma[config.slow_bars][market_symbol][signal_idx]
        if not math.isfinite(sma):
            return {}
        return {market_symbol: gross if close > sma else -gross}

    if config.mode in {"btc_ma_cross_long", "btc_ma_cross_flip"}:
        fast = indicators.ema[config.fast_bars][market_symbol][signal_idx]
        slow = indicators.ema[config.slow_bars][market_symbol][signal_idx]
        if not (math.isfinite(fast) and math.isfinite(slow)):
            return {}
        if fast > slow:
            return {market_symbol: gross}
        return {market_symbol: -gross} if config.mode.endswith("_flip") else {}

    if config.mode in {"donchian_btc_long", "donchian_btc_flip"}:
        upper = indicators.rolling_high[config.lookback_bars][market_symbol][signal_idx]
        lower = indicators.rolling_low[config.exit_bars][market_symbol][signal_idx]
        position = int(state.get("position", 0))
        if math.isfinite(upper) and close > upper:
            position = 1
        elif math.isfinite(lower) and close < lower:
            position = -1 if config.mode.endswith("_flip") else 0
        state["position"] = position
        return {market_symbol: gross * position} if position else {}

    if config.mode == "rsi_adx_btc":
        sma = indicators.sma[config.slow_bars][market_symbol][signal_idx]
        ema_fast = indicators.ema[config.fast_bars][market_symbol][signal_idx]
        rsi_value = indicators.rsi[max(config.exit_bars, 2)][market_symbol][signal_idx]
        adx_value = indicators.adx[max(config.exit_bars, 2)][market_symbol][signal_idx]
        position = int(state.get("position", 0))
        if (
            math.isfinite(sma)
            and math.isfinite(ema_fast)
            and math.isfinite(rsi_value)
            and math.isfinite(adx_value)
            and close > sma
            and close > ema_fast
            and rsi_value > adx_value
        ):
            position = 1
        elif math.isfinite(rsi_value) and math.isfinite(adx_value) and rsi_value < adx_value:
            position = 0
        state["position"] = position
        return {market_symbol: gross} if position > 0 else {}

    if config.mode == "supertrend_btc_long":
        direction_by_symbol = state.get("supertrend_direction")
        if direction_by_symbol is None:
            direction_by_symbol = _supertrend_direction(
                frame.highs[market_symbol],
                frame.lows[market_symbol],
                frame.closes[market_symbol],
                indicators.atr[config.exit_bars][market_symbol],
            )
            state["supertrend_direction"] = direction_by_symbol
        return {market_symbol: gross} if direction_by_symbol[signal_idx] > 0 else {}

    if config.mode == "macd_adx_btc":
        fast = indicators.ema[config.fast_bars][market_symbol][signal_idx]
        slow = indicators.ema[config.slow_bars][market_symbol][signal_idx]
        adx_value = indicators.adx[max(config.exit_bars, 2)][market_symbol][signal_idx]
        rsi_value = indicators.rsi[max(config.exit_bars, 2)][market_symbol][signal_idx]
        if (
            math.isfinite(fast)
            and math.isfinite(slow)
            and math.isfinite(adx_value)
            and math.isfinite(rsi_value)
            and fast > slow
            and adx_value >= 20.0
            and rsi_value >= 50.0
        ):
            return {market_symbol: gross}
        return {}

    if config.mode == "stochrsi_supertrend_btc":
        direction_by_symbol = state.get("supertrend_direction")
        if direction_by_symbol is None:
            direction_by_symbol = _supertrend_direction(
                frame.highs[market_symbol],
                frame.lows[market_symbol],
                frame.closes[market_symbol],
                indicators.atr[max(config.exit_bars, 2)][market_symbol],
                multiplier=2.5,
            )
            state["supertrend_direction"] = direction_by_symbol
        slow = indicators.ema[config.slow_bars][market_symbol][signal_idx]
        stoch_rsi = _stoch_rsi_value(indicators, config, market_symbol, signal_idx)
        if (
            direction_by_symbol[signal_idx] > 0
            and math.isfinite(slow)
            and close > slow
            and math.isfinite(stoch_rsi)
            and 0.20 <= stoch_rsi <= 0.85
        ):
            return {market_symbol: gross}
        return {}

    if config.mode in {"macd_adx_xs", "vwap_breakout_xs", "volume_breakout_xs"}:
        rows: list[tuple[str, float, float]] = []
        for symbol in _eligible_symbols(frame, config, signal_idx):
            symbol_close = frame.closes[symbol][signal_idx]
            if not (math.isfinite(symbol_close) and symbol_close > 0.0):
                continue
            fast = indicators.ema[config.fast_bars][symbol][signal_idx]
            slow = indicators.ema[config.slow_bars][symbol][signal_idx]
            adx_value = indicators.adx[max(config.exit_bars, 2)][symbol][signal_idx]
            rsi_value = indicators.rsi[max(config.exit_bars, 2)][symbol][signal_idx]
            atr_value = indicators.atr[max(config.exit_bars, 2)][symbol][signal_idx]
            if not (
                math.isfinite(fast)
                and math.isfinite(slow)
                and slow > 0.0
                and math.isfinite(adx_value)
                and math.isfinite(rsi_value)
                and math.isfinite(atr_value)
                and atr_value > 0.0
            ):
                continue
            atr_pct = atr_value / symbol_close
            if config.mode == "macd_adx_xs":
                if fast <= slow or adx_value < 20.0 or rsi_value < 50.0:
                    continue
                score = (fast / slow - 1.0) + 0.015 * (adx_value - 20.0) + 0.005 * (rsi_value - 50.0)
            elif config.mode == "vwap_breakout_xs":
                vwap = indicators.vwap[config.lookback_bars][symbol][signal_idx]
                volume = frame.volumes[symbol][signal_idx]
                volume_avg = indicators.volume_sma[config.exit_bars][symbol][signal_idx]
                if not (
                    math.isfinite(vwap)
                    and vwap > 0.0
                    and math.isfinite(volume)
                    and math.isfinite(volume_avg)
                    and volume_avg > 0.0
                ):
                    continue
                volume_ratio = volume / volume_avg
                if symbol_close <= vwap or rsi_value < 55.0 or adx_value < 18.0 or volume_ratio < 1.05:
                    continue
                score = (symbol_close / vwap - 1.0) + 0.20 * math.log(max(volume_ratio, 1e-12))
            else:
                upper = indicators.rolling_high[config.lookback_bars][symbol][signal_idx]
                volume = frame.volumes[symbol][signal_idx]
                volume_avg = indicators.volume_sma[config.exit_bars][symbol][signal_idx]
                if not (
                    math.isfinite(upper)
                    and math.isfinite(volume)
                    and math.isfinite(volume_avg)
                    and volume_avg > 0.0
                ):
                    continue
                volume_ratio = volume / volume_avg
                if symbol_close <= upper or adx_value < 18.0 or volume_ratio < 1.30:
                    continue
                score = (symbol_close / upper - 1.0) + 0.30 * math.log(max(volume_ratio, 1e-12))
            if score > 0.0:
                rows.append((symbol, score, atr_pct))
        selected = sorted(rows, key=lambda row: row[1], reverse=True)[: max(config.top_k, 1)]
        return _normalize_weights([(symbol, max(score, 0.01), vol) for symbol, score, vol in selected], gross=gross, vol_weight=True)

    if config.mode in {"ratio_reversal_btc", "ratio_momentum_btc"}:
        rows: list[tuple[str, float, float]] = []
        for symbol in _eligible_symbols(frame, config, signal_idx):
            if symbol == market_symbol:
                continue
            symbol_close = frame.closes[symbol][signal_idx]
            atr_value = indicators.atr[max(config.exit_bars, 2)][symbol][signal_idx]
            zscore = indicators.ratio_z[config.lookback_bars][symbol][signal_idx]
            if not (
                math.isfinite(symbol_close)
                and symbol_close > 0.0
                and math.isfinite(atr_value)
                and atr_value > 0.0
                and math.isfinite(zscore)
            ):
                continue
            threshold = 1.25
            if abs(zscore) < threshold:
                continue
            side = -1.0 if zscore > 0.0 else 1.0
            if config.mode == "ratio_momentum_btc":
                side *= -1.0
            rows.append((symbol, side * abs(zscore), atr_value / symbol_close))
        selected = sorted(rows, key=lambda row: abs(row[1]), reverse=True)[: max(config.top_k, 1)]
        if not selected:
            return {}
        per_alt_abs = gross / (2.0 * len(selected))
        weights: dict[str, float] = {}
        for symbol, signed_score, _vol in selected:
            side = 1.0 if signed_score > 0.0 else -1.0
            weights[symbol] = weights.get(symbol, 0.0) + side * per_alt_abs
            weights[market_symbol] = weights.get(market_symbol, 0.0) - side * per_alt_abs
        return {symbol: value for symbol, value in weights.items() if abs(value) > 1e-12}

    if config.mode in {"scorecard_momentum", "scorecard_breakout"}:
        btc_sma = indicators.sma[config.slow_bars][market_symbol][signal_idx]
        if not (math.isfinite(btc_sma) and close > btc_sma):
            return {}
        direction_by_symbol = state.get("btc_supertrend_direction")
        if direction_by_symbol is None:
            direction_by_symbol = _supertrend_direction(
                frame.highs[market_symbol],
                frame.lows[market_symbol],
                frame.closes[market_symbol],
                indicators.atr[max(config.exit_bars, 2)][market_symbol],
            )
            state["btc_supertrend_direction"] = direction_by_symbol
        if direction_by_symbol[signal_idx] <= 0:
            return {}

        positions: dict[str, int] | None = None
        if config.mode == "scorecard_breakout":
            positions = dict(state.get("positions") or {})
            for symbol in _eligible_symbols(frame, config, signal_idx):
                symbol_close = frame.closes[symbol][signal_idx]
                upper = indicators.rolling_high[config.lookback_bars][symbol][signal_idx]
                lower = indicators.rolling_low[config.exit_bars][symbol][signal_idx]
                position = int(positions.get(symbol, 0))
                if math.isfinite(upper) and symbol_close > upper:
                    position = 1
                elif math.isfinite(lower) and symbol_close < lower:
                    position = 0
                positions[symbol] = position
            state["positions"] = positions

        rows = _scorecard_rows(
            frame,
            indicators,
            config,
            signal_idx,
            require_breakout_position=positions,
        )
        selected = sorted(rows, key=lambda row: row[1], reverse=True)[: max(config.top_k, 1)]
        weighted_rows = [(symbol, max(score, 0.01), vol) for symbol, score, vol in selected]
        return _normalize_weights(weighted_rows, gross=gross, vol_weight=True)

    if config.mode == "donchian_xs_long":
        positions: dict[str, int] = dict(state.get("positions") or {})
        candidates: list[tuple[str, float, float]] = []
        for symbol in _eligible_symbols(frame, config, signal_idx):
            symbol_close = frame.closes[symbol][signal_idx]
            upper = indicators.rolling_high[config.lookback_bars][symbol][signal_idx]
            lower = indicators.rolling_low[config.exit_bars][symbol][signal_idx]
            position = int(positions.get(symbol, 0))
            if math.isfinite(upper) and symbol_close > upper:
                position = 1
            elif math.isfinite(lower) and symbol_close < lower:
                position = 0
            positions[symbol] = position
            if position > 0:
                momentum = symbol_close / max(indicators.rolling_low[config.lookback_bars][symbol][signal_idx], 1e-12) - 1.0
                vol = indicators.atr[config.exit_bars][symbol][signal_idx] / max(symbol_close, 1e-12)
                candidates.append((symbol, momentum if math.isfinite(momentum) else 0.0, vol))
        state["positions"] = positions
        selected = sorted(candidates, key=lambda row: row[1], reverse=True)[: max(config.top_k, 1)]
        return _normalize_weights([(symbol, 1.0, vol) for symbol, _, vol in selected], gross=gross, vol_weight=config.vol_weight)

    if config.mode == "bb_rsi_mr":
        positions: dict[str, int] = dict(state.get("positions") or {})
        rows: list[tuple[str, float, float, float]] = []
        for symbol in _eligible_symbols(frame, config, signal_idx):
            symbol_close = frame.closes[symbol][signal_idx]
            mid = indicators.sma[config.lookback_bars][symbol][signal_idx]
            std = indicators.std[config.lookback_bars][symbol][signal_idx]
            rsi_value = indicators.rsi[config.exit_bars][symbol][signal_idx]
            if not (math.isfinite(symbol_close) and math.isfinite(mid) and math.isfinite(std) and math.isfinite(rsi_value)):
                continue
            lower = mid - 2.0 * std
            upper = mid + 2.0 * std
            position = int(positions.get(symbol, 0))
            if position == 0:
                if symbol_close < lower and rsi_value < 25.0:
                    position = 1
                elif symbol_close > upper and rsi_value > 75.0:
                    position = -1
            elif position > 0 and (symbol_close >= mid or rsi_value >= 50.0):
                position = 0
            elif position < 0 and (symbol_close <= mid or rsi_value <= 50.0):
                position = 0
            positions[symbol] = position
            if position:
                zscore = abs(symbol_close - mid) / max(std, 1e-12)
                vol = indicators.atr[config.exit_bars][symbol][signal_idx] / max(symbol_close, 1e-12)
                rows.append((symbol, float(position), zscore, vol))
        state["positions"] = positions
        selected = sorted(rows, key=lambda row: row[2], reverse=True)[: max(config.top_k, 1)]
        return _normalize_weights([(symbol, side, vol) for symbol, side, _, vol in selected], gross=gross, vol_weight=config.vol_weight)

    return {}


def _weights_sample(weights: dict[str, float], limit: int = 6) -> dict[str, float]:
    return {
        symbol: round(value, 4)
        for symbol, value in sorted(weights.items(), key=lambda item: abs(item[1]), reverse=True)[:limit]
        if abs(value) > 1e-12
    }


def _backtest_config(
    frame: rot.MarketFrame,
    indicators: IndicatorCache,
    config: ExternalStrategyConfig,
    *,
    cost_bps_per_turnover: float,
    holding_cost_bps_per_day: float,
    short_cost_bps_per_day: float,
    drawdown_guard_pct: float,
    drawdown_risk_scale: float,
    vol_target_annual_pct: float,
    vol_lookback_hours: int,
    vol_min_scale: float,
    vol_max_scale: float,
    max_symbol_weight: float,
    assumed_capital_usd: float,
    pnl_notional_mode: str,
    liquidity_notional_mode: str,
    liquidity_impact_bps_per_1pct_volume: float,
    capacity_cap_trade_volume_pct: float,
) -> dict[str, Any]:
    warmup = max(
        config.lookback_bars,
        config.exit_bars,
        config.fast_bars,
        config.slow_bars,
        config.min_symbol_age_bars,
        10,
    ) + 2
    if len(frame.ts) < warmup + 10:
        return {"decision": "REJECT_SAMPLE", "model_id": config.model_id, "periods": 0}

    cost = max(float(cost_bps_per_turnover), 0.0) / 10_000.0
    weights: dict[str, float] = {}
    state: dict[str, Any] = {}
    equity = 1.0
    peak = 1.0
    min_equity = 1.0
    max_dd = 0.0
    period_count = 0
    active_periods = 0
    wins = 0
    losses = 0
    rebalance_count = 0
    turnover_sum = 0.0
    cost_drag = 0.0
    holding_cost_drag = 0.0
    short_cost_drag = 0.0
    liquidity_drag = 0.0
    capacity_cap_event_count = 0
    max_capacity_cap_requested_pct = 0.0
    symbol_weight_cap_event_count = 0
    gross_sum = 0.0
    net_sum = 0.0
    short_sum = 0.0
    direction_counts: Counter[str] = Counter()
    by_year_start: dict[str, float] = {}
    by_year_end: dict[str, float] = {}
    by_quarter_start: dict[str, float] = {}
    by_quarter_end: dict[str, float] = {}
    by_month_start: dict[str, float] = {}
    by_month_end: dict[str, float] = {}
    symbol_contribution_sum = {symbol: 0.0 for symbol in frame.symbols}
    symbol_abs_exposure_sum = {symbol: 0.0 for symbol in frame.symbols}
    rebalance_samples: list[dict[str, Any]] = []
    realized_returns: deque[float] = deque(maxlen=rot._hours_to_bars(config.interval, max(int(vol_lookback_hours), 1)))
    risk_scale_sum = 0.0
    risk_scale_count = 0
    drawdown_guard_count = 0
    vol_target_count = 0

    first_exec_ts: datetime | None = None
    last_period_ts: datetime | None = None
    first_exec_idx = warmup + 1
    last_exec_idx = len(frame.ts) - 2
    for exec_idx in range(first_exec_idx, last_exec_idx + 1):
        if first_exec_ts is None:
            first_exec_ts = frame.ts[exec_idx]
        should_rebalance = (exec_idx - first_exec_idx) % max(config.rebalance_bars, 1) == 0
        turnover = 0.0
        liquidity_cost_period = 0.0
        if should_rebalance:
            signal_idx = exec_idx - 1
            new_weights = _target_weights(frame, indicators, config, signal_idx, state)
            raw_gross = sum(abs(value) for value in new_weights.values())
            risk_scale = 1.0
            live_drawdown = 1.0 - equity / max(peak, 1e-12)
            guard_active = drawdown_guard_pct > 0.0 and live_drawdown * 100.0 >= drawdown_guard_pct
            if guard_active:
                risk_scale *= max(float(drawdown_risk_scale), 0.0)
                drawdown_guard_count += 1
            vol_scale = 1.0
            if vol_target_annual_pct > 0.0 and len(realized_returns) >= max(10, realized_returns.maxlen // 2):
                mean_return = sum(realized_returns) / len(realized_returns)
                variance = sum((value - mean_return) ** 2 for value in realized_returns) / len(realized_returns)
                period_vol = math.sqrt(max(variance, 0.0))
                bars_per_year = 365.25 * 24.0 / max(rot._interval_hours(config.interval), 1e-9)
                realized_vol = period_vol * math.sqrt(bars_per_year)
                if realized_vol > 1e-12:
                    vol_scale = min(
                        max((vol_target_annual_pct / 100.0) / realized_vol, max(float(vol_min_scale), 0.0)),
                        max(float(vol_max_scale), 0.0),
                    )
                    risk_scale *= vol_scale
                    vol_target_count += 1
            new_weights = rot._scale_weights(new_weights, risk_scale)
            if max_symbol_weight > 0.0:
                new_weights, cap_events = rot._clip_symbol_weights(new_weights, max_symbol_weight)
                symbol_weight_cap_event_count += cap_events
            else:
                cap_events = 0
            if capacity_cap_trade_volume_pct > 0.0:
                new_weights, capacity_events, requested_pct = rot._apply_capacity_cap(
                    frame,
                    old_weights=weights,
                    new_weights=new_weights,
                    signal_idx=signal_idx,
                    equity=equity,
                    assumed_capital_usd=assumed_capital_usd,
                    max_trade_volume_pct=capacity_cap_trade_volume_pct,
                    liquidity_notional_mode=liquidity_notional_mode,
                )
                capacity_cap_event_count += capacity_events
                max_capacity_cap_requested_pct = max(max_capacity_cap_requested_pct, requested_pct)
            turnover = rot._turnover(weights, new_weights, frame.symbols)
            if (
                turnover > 1e-9
                and assumed_capital_usd > 0.0
                and liquidity_impact_bps_per_1pct_volume > 0.0
            ):
                for symbol in frame.symbols:
                    delta_weight = abs(new_weights.get(symbol, 0.0) - weights.get(symbol, 0.0))
                    if delta_weight <= 1e-12:
                        continue
                    quote_volume = rot._quote_volume_at(frame, symbol, signal_idx)
                    if not math.isfinite(quote_volume) or quote_volume <= 0.0:
                        continue
                    trade_volume_pct = rot._trade_volume_pct_for_delta(
                        delta_weight=delta_weight,
                        equity=equity,
                        assumed_capital_usd=assumed_capital_usd,
                        quote_volume=quote_volume,
                        liquidity_notional_mode=liquidity_notional_mode,
                    )
                    liquidity_cost_period += (
                        delta_weight
                        * rot._execution_to_pnl_basis_multiplier(
                            equity=equity,
                            execution_notional_mode=liquidity_notional_mode,
                            pnl_notional_mode=pnl_notional_mode,
                        )
                        * liquidity_impact_bps_per_1pct_volume
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
                            "raw_gross": round(raw_gross, 4),
                            "risk_scale": round(risk_scale, 4),
                            "drawdown_pct": round(live_drawdown * 100.0, 4),
                            "vol_scale": round(vol_scale, 4),
                            "symbol_weight_cap_events": int(cap_events),
                            "weights": _weights_sample(new_weights),
                        }
                    )
            risk_scale_sum += risk_scale
            risk_scale_count += 1
            weights = new_weights

        gross_exposure = sum(abs(value) for value in weights.values())
        net_exposure = sum(weights.values())
        short_exposure = sum(abs(value) for value in weights.values() if value < 0.0)
        gross_sum += gross_exposure
        net_sum += net_exposure
        short_sum += short_exposure
        turnover_sum += turnover
        cost_period = turnover * cost
        cost_drag += cost_period
        liquidity_drag += liquidity_cost_period
        period_days = max((frame.ts[exec_idx + 1] - frame.ts[exec_idx]).total_seconds() / 86_400.0, 0.0)
        holding_cost_period = gross_exposure * max(holding_cost_bps_per_day, 0.0) / 10_000.0 * period_days
        short_cost_period = short_exposure * max(short_cost_bps_per_day, 0.0) / 10_000.0 * period_days
        holding_cost_drag += holding_cost_period
        short_cost_drag += short_cost_period
        portfolio_return = 0.0
        for symbol, weight in weights.items():
            symbol_return = frame.returns[symbol][exec_idx]
            if not math.isfinite(symbol_return):
                continue
            contribution = weight * symbol_return
            portfolio_return += contribution
            symbol_contribution_sum[symbol] += contribution
            symbol_abs_exposure_sum[symbol] += abs(weight)
        basis_return = portfolio_return - cost_period - liquidity_cost_period - holding_cost_period - short_cost_period
        net_return = rot._basis_return_to_equity_return(
            basis_return,
            equity=equity,
            pnl_notional_mode=pnl_notional_mode,
        )
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
        if net_return <= -0.999:
            equity = 1e-9
        else:
            equity *= 1.0 + net_return
        by_year_end[year] = equity
        by_quarter_end[quarter] = equity
        by_month_end[month] = equity
        peak = max(peak, equity)
        min_equity = min(min_equity, equity)
        max_dd = max(max_dd, 1.0 - equity / max(peak, 1e-12))
        if net_return > 0:
            wins += 1
        elif net_return < 0:
            losses += 1
        realized_returns.append(net_return)
        period_count += 1
        last_period_ts = frame.ts[exec_idx + 1]
        if equity <= 1e-8:
            break

    years = max(rot._year_fraction(first_exec_ts, last_period_ts), 1e-9)
    total_return = equity - 1.0
    cagr = equity ** (1.0 / years) - 1.0 if equity > 0.0 else -1.0
    by_year_return = {
        year: by_year_end[year] / max(by_year_start.get(year, 1.0), 1e-12) - 1.0
        for year in sorted(by_year_end)
    }
    by_quarter_return = {
        quarter: by_quarter_end[quarter] / max(by_quarter_start.get(quarter, 1.0), 1e-12) - 1.0
        for quarter in sorted(by_quarter_end)
    }
    by_month_return = {
        month: by_month_end[month] / max(by_month_start.get(month, 1.0), 1e-12) - 1.0
        for month in sorted(by_month_end)
    }
    positive_years = sum(1 for value in by_year_return.values() if value > 0.0)
    positive_year_fraction = positive_years / max(len(by_year_return), 1)
    calmar = cagr / max(max_dd, 1e-9) if max_dd > 0.0 else 0.0
    score = 0.0
    if total_return > 0.0 and max_dd > 0.0:
        score = max(calmar, 0.0) * math.log1p(max(total_return, 0.0)) * max(positive_year_fraction, 0.05)
        if max_dd > 0.50:
            score *= 0.45
    if period_count <= 0 or years < 1.0:
        decision = "REJECT_SAMPLE"
    elif equity <= 1e-6:
        decision = "REJECT_BANKRUPT"
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

    return {
        "model_id": config.model_id,
        "decision": decision,
        "periods": period_count,
        "first_exec_ts": first_exec_ts.isoformat() if first_exec_ts else None,
        "last_period_ts": last_period_ts.isoformat() if last_period_ts else None,
        "years": round(years, 4),
        "total_return_pct": round(total_return * 100.0, 4),
        "cagr_pct": round(cagr * 100.0, 4),
        "max_drawdown_pct": round(max_dd * 100.0, 4),
        "calmar": round(calmar, 4),
        "min_equity": round(min_equity, 6),
        "rebalance_count": int(rebalance_count),
        "win_rate_period": round(wins / max(wins + losses, 1), 4),
        "active_fraction": round(active_periods / max(period_count, 1), 4),
        "avg_gross_exposure": round(gross_sum / max(period_count, 1), 4),
        "avg_net_exposure": round(net_sum / max(period_count, 1), 4),
        "avg_short_exposure": round(short_sum / max(period_count, 1), 4),
        "turnover_sum": round(turnover_sum, 4),
        "avg_daily_turnover": round(turnover_sum / max(years * 365.25, 1e-9), 4),
        "cost_drag_pct_simple_sum": round(cost_drag * 100.0, 4),
        "liquidity_impact_drag_pct_simple_sum": round(liquidity_drag * 100.0, 4),
        "holding_cost_drag_pct_simple_sum": round(holding_cost_drag * 100.0, 4),
        "short_cost_drag_pct_simple_sum": round(short_cost_drag * 100.0, 4),
        "capacity_cap_event_count": int(capacity_cap_event_count),
        "max_capacity_cap_requested_trade_volume_pct": round(max_capacity_cap_requested_pct, 6),
        "symbol_weight_cap_event_count": int(symbol_weight_cap_event_count),
        "positive_year_count": int(positive_years),
        "year_count": len(by_year_return),
        "positive_year_fraction": round(positive_year_fraction, 4),
        "by_year_return_pct": {year: round(value * 100.0, 4) for year, value in by_year_return.items()},
        "by_quarter_return_pct": {
            quarter: round(value * 100.0, 4) for quarter, value in by_quarter_return.items()
        },
        "by_month_return_pct": {month: round(value * 100.0, 4) for month, value in by_month_return.items()},
        "best_year_pct": round(max(by_year_return.values()) * 100.0, 4) if by_year_return else 0.0,
        "worst_year_pct": round(min(by_year_return.values()) * 100.0, 4) if by_year_return else 0.0,
        "direction_period_counts": dict(sorted(direction_counts.items())),
        "risk_overlay": {
            "drawdown_guard_pct": float(drawdown_guard_pct),
            "drawdown_risk_scale": float(drawdown_risk_scale),
            "vol_target_annual_pct": float(vol_target_annual_pct),
            "vol_lookback_hours": int(vol_lookback_hours),
            "vol_min_scale": float(vol_min_scale),
            "vol_max_scale": float(vol_max_scale),
            "avg_risk_scale_at_rebalance": round(risk_scale_sum / max(risk_scale_count, 1), 4),
            "drawdown_guard_rebalance_count": int(drawdown_guard_count),
            "vol_target_rebalance_count": int(vol_target_count),
        },
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
        "rebalance_samples": rebalance_samples,
        "score": round(score, 8),
    }


def _rank_rows(rows: list[dict[str, Any]], key: str, limit: int = 30) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            float(dict(row.get("summary") or {}).get(key, 0.0) or 0.0),
            float(dict(row.get("summary") or {}).get("score", 0.0) or 0.0),
        ),
        reverse=True,
    )[:limit]


def main() -> int:
    args = _parse_args()
    if args.interval not in _INTERVAL_MS:
        raise SystemExit(f"unsupported interval: {args.interval}")
    settings = get_settings()
    generated_at = datetime.now(UTC)
    symbols = [symbol.upper() for symbol in _csv(args.symbols)]
    cache_dir = ROOT_DIR / str(args.cache_dir)
    base_url = str(args.base_url or settings.binance_rest_base_url or "https://fapi.binance.com").rstrip("/")
    bars_by_symbol = {
        symbol: rot._load_bars(
            symbol=symbol,
            interval=args.interval,
            days=max(int(args.days), 30),
            cache_dir=cache_dir,
            base_url=base_url,
            sleep_seconds=float(args.sleep_seconds),
        )
        for symbol in symbols
    }
    for symbol, bars in bars_by_symbol.items():
        print(json.dumps({"loaded": symbol, "interval": args.interval, "bars": len(bars)}, ensure_ascii=False), flush=True)
    frame, data_status = rot._align_dynamic_frame(args.interval, bars_by_symbol)
    if frame is None:
        raise SystemExit(f"failed to build frame: {data_status}")
    if float(data_status.get("common_days") or 0.0) < int(args.min_common_days):
        raise SystemExit(f"common_days too short: {data_status}")

    configs = _build_configs(args)
    indicators = _build_indicators(frame, configs)
    cost_bps = max(float(args.fee_bps_per_side) + float(args.slippage_bps_per_side), 0.0)
    rows: list[dict[str, Any]] = []
    for idx, config in enumerate(configs, start=1):
        summary = _backtest_config(
            frame,
            indicators,
            config,
            cost_bps_per_turnover=cost_bps,
            holding_cost_bps_per_day=max(float(args.holding_cost_bps_per_day), 0.0),
            short_cost_bps_per_day=max(float(args.short_cost_bps_per_day), 0.0),
            drawdown_guard_pct=max(float(args.drawdown_guard_pct), 0.0),
            drawdown_risk_scale=max(float(args.drawdown_risk_scale), 0.0),
            vol_target_annual_pct=max(float(args.vol_target_annual_pct), 0.0),
            vol_lookback_hours=max(int(args.vol_lookback_hours), 1),
            vol_min_scale=max(float(args.vol_min_scale), 0.0),
            vol_max_scale=max(float(args.vol_max_scale), 0.0),
            max_symbol_weight=max(float(args.max_symbol_weight), 0.0),
            assumed_capital_usd=max(float(args.assumed_capital_usd), 0.0),
            pnl_notional_mode=str(args.pnl_notional_mode),
            liquidity_notional_mode=str(args.liquidity_notional_mode),
            liquidity_impact_bps_per_1pct_volume=max(float(args.liquidity_impact_bps_per_1pct_volume), 0.0),
            capacity_cap_trade_volume_pct=max(float(args.capacity_cap_trade_volume_pct), 0.0),
        )
        rows.append({"config": asdict(config), "summary": summary})
        if idx % 250 == 0:
            print(
                json.dumps(
                    {"progress": idx, "models_total": len(configs), "latest_model": config.model_id},
                    ensure_ascii=False,
                ),
                flush=True,
            )

    output = {
        "schema_version": "external_strategy_zoo_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "research_only_no_live_authority_change",
        "strategy_sources": [
            "Moskowitz/Ooi/Pedersen time-series momentum",
            "Donchian/Turtle breakout variants from public crypto backtests and YouTube summaries",
            "Reddit BTC SMA/EMA/RSI/ADX long-only rule",
            "RSI+Bollinger mean-reversion rule, included as a negative/control candidate",
            "Supertrend/ATR trend-following rule",
        ],
        "scope": {
            "symbols": symbols,
            "days": int(args.days),
            "interval": str(args.interval),
            "model_count": len(rows),
            "min_common_days": int(args.min_common_days),
        },
        "cost_model": {
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": float(args.slippage_bps_per_side),
            "cost_bps_per_turnover": cost_bps,
            "holding_cost_bps_per_day": float(args.holding_cost_bps_per_day),
            "short_cost_bps_per_day": float(args.short_cost_bps_per_day),
            "drawdown_guard_pct": float(args.drawdown_guard_pct),
            "drawdown_risk_scale": float(args.drawdown_risk_scale),
            "vol_target_annual_pct": float(args.vol_target_annual_pct),
            "vol_lookback_hours": int(args.vol_lookback_hours),
            "max_symbol_weight": float(args.max_symbol_weight),
            "assumed_capital_usd": float(args.assumed_capital_usd),
            "pnl_notional_mode": str(args.pnl_notional_mode),
            "liquidity_notional_mode": str(args.liquidity_notional_mode),
            "liquidity_impact_bps_per_1pct_volume": float(args.liquidity_impact_bps_per_1pct_volume),
            "capacity_cap_trade_volume_pct": float(args.capacity_cap_trade_volume_pct),
            "notes": [
                "signals use completed candles and execute at next candle open",
                "external community strategies are re-tested with fees, slippage, liquidity, vol target, and drawdown guard",
                "this is a research backtest only, not live-trading authority",
            ],
        },
        "data_status": data_status,
        "decision_counts": dict(sorted(Counter(str(row["summary"].get("decision")) for row in rows).items())),
        "mode_counts": dict(sorted(Counter(str(row["config"].get("mode")) for row in rows).items())),
        "top_by_score": sorted(
            rows,
            key=lambda row: (
                float(row["summary"].get("score", 0.0) or 0.0),
                float(row["summary"].get("cagr_pct", 0.0) or 0.0),
            ),
            reverse=True,
        )[:30],
        "top_by_return": _rank_rows(rows, "total_return_pct"),
        "top_by_calmar": _rank_rows(rows, "calmar"),
        "all_results": rows,
    }
    if bool(args.write_report):
        report_dir = ROOT_DIR / str(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        out_path = report_dir / f"external_strategy_zoo_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        latest_path = report_dir / "latest.json"
        output["report_path"] = str(out_path.relative_to(ROOT_DIR))
        output["latest_report_path"] = str(latest_path.relative_to(ROOT_DIR))
        atomic_write_text(out_path, json.dumps(output, ensure_ascii=False, indent=2))
        atomic_write_text(latest_path, json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps(output, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
