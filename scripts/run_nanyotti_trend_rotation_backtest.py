#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text
from scripts.run_btc_flip_rotation_search import _INTERVAL_MS, _csv, _load_bars, _year_fraction, FeatureSet
from scripts.run_position_rotation_backtest import _updated_average_entry


@dataclass(frozen=True, slots=True)
class TrendRotationConfig:
    model_id: str
    interval: str
    fast: int
    slow: int
    trend_band_atr: float
    exit_band_atr: float
    confirm_bars: int
    max_account_exposure: float
    trail_atr: float
    liquidation_buffer_fraction: float
    exchange_leverage: float
    maintenance_margin_pct: float


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only all-market trend/flip rotation proxy derived from Nanyotti/Wonyotti principles."
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--days", type=int, default=1825)
    parser.add_argument("--intervals", default="2h,4h")
    parser.add_argument("--fast-slow-pairs", default="21:233,34:233,21:144,34:144")
    parser.add_argument("--trend-bands", default="0.6,1.0,1.4")
    parser.add_argument("--exit-bands", default="0.2,0.4")
    parser.add_argument("--confirm-bars", default="2,3")
    parser.add_argument("--max-account-exposures", default="0.25,0.5,0.75,1")
    parser.add_argument("--trail-atrs", default="2.5,4")
    parser.add_argument("--liquidation-buffer-fractions", default="0.45,0.55,0.7")
    parser.add_argument("--exchange-leverage", type=float, default=10.0)
    parser.add_argument("--maintenance-margin-pct", type=float, default=0.5)
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument("--min-periods", type=int, default=500)
    parser.add_argument("--max-models", type=int, default=0)
    parser.add_argument("--cache-dir", default="reports/validation/btc_flip_rotation_search/cache")
    parser.add_argument("--report-dir", default="reports/validation/nanyotti_trend_rotation_backtest")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _parse_float_csv(raw: str, fallback: list[float]) -> list[float]:
    out: list[float] = []
    for item in _csv(raw):
        try:
            value = float(item)
        except ValueError:
            continue
        if value > 0.0:
            out.append(value)
    return out or list(fallback)


def _parse_int_csv(raw: str, fallback: list[int]) -> list[int]:
    out: list[int] = []
    for item in _csv(raw):
        try:
            value = int(item)
        except ValueError:
            continue
        if value > 0:
            out.append(value)
    return out or list(fallback)


def _parse_fast_slow_pairs(raw: str) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for item in _csv(raw):
        if ":" not in item:
            continue
        left, right = item.split(":", 1)
        try:
            fast = int(left)
            slow = int(right)
        except ValueError:
            continue
        if 1 <= fast < slow:
            pairs.append((fast, slow))
    return pairs or [(21, 233), (34, 233)]


def _side_label(side: int) -> str:
    if side > 0:
        return "long"
    if side < 0:
        return "short"
    return "flat"


def _trend_raw_side(*, close: float, slow_ema: float, spread_atr: float, band: float) -> int:
    side = 1 if spread_atr > band else -1 if spread_atr < -band else 0
    if side and close * side < slow_ema * side:
        return 0
    return side


def _buffer_stop_price(
    *,
    weight: float,
    avg_entry: float,
    bar_high: float,
    bar_low: float,
    exchange_leverage: float,
    maintenance_margin_pct: float,
    buffer_fraction: float,
) -> float | None:
    if abs(weight) <= 1e-12 or avg_entry <= 0.0:
        return None
    liquidation_distance = max(1.0 / max(exchange_leverage, 1e-12) - maintenance_margin_pct / 100.0, 0.01)
    stop_distance = liquidation_distance * min(max(buffer_fraction, 0.10), 0.95)
    if weight > 0.0:
        stop_price = avg_entry * (1.0 - stop_distance)
        return stop_price if bar_low <= stop_price else None
    stop_price = avg_entry * (1.0 + stop_distance)
    return stop_price if bar_high >= stop_price else None


def build_configs(args: argparse.Namespace) -> list[TrendRotationConfig]:
    configs: list[TrendRotationConfig] = []
    intervals = [item for item in _csv(args.intervals) if item in _INTERVAL_MS] or ["2h", "4h"]
    for interval in intervals:
        for fast, slow in _parse_fast_slow_pairs(str(args.fast_slow_pairs)):
            for trend_band in _parse_float_csv(str(args.trend_bands), [0.6, 1.0]):
                for exit_band in _parse_float_csv(str(args.exit_bands), [0.2, 0.4]):
                    if exit_band >= trend_band:
                        continue
                    for confirm in _parse_int_csv(str(args.confirm_bars), [2, 3]):
                        for exposure in _parse_float_csv(str(args.max_account_exposures), [0.25, 0.5, 0.75]):
                            for trail_atr in _parse_float_csv(str(args.trail_atrs), [2.5, 4.0]):
                                for buffer_fraction in _parse_float_csv(str(args.liquidation_buffer_fractions), [0.45, 0.55]):
                                    model_id = (
                                        f"{interval}:nanyotti_trend:ema{fast}_{slow}:band{trend_band:g}:"
                                        f"exit{exit_band:g}:confirm{confirm}:gross{exposure:g}:"
                                        f"trail{trail_atr:g}:liqbuf{buffer_fraction:g}:lev{float(args.exchange_leverage):g}"
                                    )
                                    configs.append(
                                        TrendRotationConfig(
                                            model_id=model_id,
                                            interval=interval,
                                            fast=fast,
                                            slow=slow,
                                            trend_band_atr=trend_band,
                                            exit_band_atr=exit_band,
                                            confirm_bars=confirm,
                                            max_account_exposure=exposure,
                                            trail_atr=trail_atr,
                                            liquidation_buffer_fraction=buffer_fraction,
                                            exchange_leverage=max(float(args.exchange_leverage), 1.0),
                                            maintenance_margin_pct=max(float(args.maintenance_margin_pct), 0.0),
                                        )
                                    )
    if int(args.max_models or 0) > 0:
        configs = configs[: int(args.max_models)]
    return configs


def backtest_config(
    *,
    symbol: str,
    features: FeatureSet,
    config: TrendRotationConfig,
    cost_bps_per_side: float,
    min_periods: int,
) -> dict[str, Any]:
    warmup = max(config.slow, 80) + config.confirm_bars + 2
    if len(features.bars) < warmup + 100:
        return {"model_id": config.model_id, "decision": "REJECT_SAMPLE", "periods": 0}

    fast_ema = features.ema(config.fast)
    slow_ema = features.ema(config.slow)
    atr = features.atr
    weight = 0.0
    avg_entry = 0.0
    best_price = 0.0
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    min_equity = 1.0
    turnover_sum = 0.0
    cost_drag = 0.0
    active_periods = 0
    period_count = 0
    wins = 0
    losses = 0
    raw_side_streak = 0
    last_raw_side = 0
    buffer_stop_count = 0
    event_reasons: Counter[str] = Counter()
    direction_periods: Counter[str] = Counter()
    by_year_start: dict[str, float] = {}
    by_year_end: dict[str, float] = {}
    returns: list[float] = []
    samples: list[dict[str, Any]] = []
    first_exec_ts: datetime | None = None
    last_period_ts: datetime | None = None
    cost_rate = max(float(cost_bps_per_side), 0.0) / 10_000.0

    for signal_idx in range(warmup, len(features.bars) - 2):
        exec_idx = signal_idx + 1
        next_idx = exec_idx + 1
        exec_price = features.bars[exec_idx].o
        next_price = features.bars[next_idx].o
        if exec_price <= 0.0 or next_price <= 0.0:
            continue
        if first_exec_ts is None:
            first_exec_ts = features.bars[exec_idx].ts

        close = features.c[signal_idx]
        current_atr = max(atr[signal_idx], 1e-12)
        spread_atr = (fast_ema[signal_idx] - slow_ema[signal_idx]) / current_atr
        raw_side = _trend_raw_side(
            close=close,
            slow_ema=slow_ema[signal_idx],
            spread_atr=spread_atr,
            band=config.trend_band_atr,
        )
        if raw_side != 0 and raw_side == last_raw_side:
            raw_side_streak += 1
        else:
            raw_side_streak = 1 if raw_side else 0
        last_raw_side = raw_side

        current_side = 1 if weight > 0.0 else -1 if weight < 0.0 else 0
        if current_side > 0:
            best_price = max(best_price or close, close)
        elif current_side < 0:
            best_price = min(best_price or close, close)

        target_weight = weight
        reason = "hold"
        if raw_side != 0 and raw_side_streak >= config.confirm_bars:
            target_weight = raw_side * config.max_account_exposure
            reason = "trend_entry_or_flip" if raw_side != current_side else "trend_hold"
        elif current_side != 0:
            weak_trend = abs(spread_atr) < config.exit_band_atr or close * current_side < slow_ema[signal_idx] * current_side
            trailing_stop = bool(best_price) and (best_price - close) * current_side > config.trail_atr * current_atr
            if weak_trend or trailing_stop:
                target_weight = 0.0
                reason = "trend_exit" if weak_trend else "trail_exit"
        else:
            target_weight = 0.0
            reason = "flat"

        previous_weight = weight
        turnover = abs(target_weight - previous_weight)
        cost_period = turnover * cost_rate
        turnover_sum += turnover
        cost_drag += cost_period
        if turnover > 1e-12:
            event_reasons[reason] += 1
            if abs(target_weight) <= 1e-12:
                best_price = 0.0
            elif abs(previous_weight) <= 1e-12 or previous_weight * target_weight < 0.0:
                best_price = exec_price

        avg_entry = _updated_average_entry(
            current_weight=previous_weight,
            current_avg_entry=avg_entry,
            target_weight=target_weight,
            exec_price=exec_price,
        )
        weight = target_weight

        stop_price = _buffer_stop_price(
            weight=weight,
            avg_entry=avg_entry,
            bar_high=features.bars[exec_idx].h,
            bar_low=features.bars[exec_idx].l,
            exchange_leverage=config.exchange_leverage,
            maintenance_margin_pct=config.maintenance_margin_pct,
            buffer_fraction=config.liquidation_buffer_fraction,
        )
        if stop_price is not None:
            net_return = weight * (stop_price / exec_price - 1.0) - cost_period
            weight = 0.0
            avg_entry = 0.0
            best_price = 0.0
            buffer_stop_count += 1
            event_reasons["liquidation_buffer_stop"] += 1
        else:
            net_return = weight * (next_price / exec_price - 1.0) - cost_period

        if abs(weight) > 1e-12:
            active_periods += 1
        direction_periods[_side_label(1 if weight > 0.0 else -1 if weight < 0.0 else 0)] += 1
        year = str(features.bars[next_idx].ts.year)
        by_year_start.setdefault(year, equity)
        equity = equity * max(1.0 + net_return, 1e-9)
        by_year_end[year] = equity
        peak = max(peak, equity)
        min_equity = min(min_equity, equity)
        max_dd = max(max_dd, 1.0 - equity / max(peak, 1e-12))
        if net_return > 0.0:
            wins += 1
        elif net_return < 0.0:
            losses += 1
        returns.append(net_return)
        period_count += 1
        last_period_ts = features.bars[next_idx].ts

        if len(samples) < 20 and (turnover > 1e-12 or stop_price is not None):
            samples.append(
                {
                    "signal_ts": features.bars[signal_idx].ts.isoformat(),
                    "exec_ts": features.bars[exec_idx].ts.isoformat(),
                    "previous_weight": round(previous_weight, 4),
                    "target_weight": round(target_weight, 4),
                    "turnover": round(turnover, 4),
                    "exec_price": round(exec_price, 4),
                    "net_return_pct": round(net_return * 100.0, 4),
                    "stop_price": round(stop_price, 4) if stop_price is not None else None,
                    "reason": reason,
                    "raw_side": _side_label(raw_side),
                    "spread_atr": round(spread_atr, 4),
                    "streak": raw_side_streak,
                }
            )

    years = max(_year_fraction(first_exec_ts, last_period_ts), 1e-9)
    total_return = equity - 1.0
    cagr = equity ** (1.0 / years) - 1.0 if equity > 0.0 else -1.0
    by_year_return = {
        year: by_year_end[year] / max(by_year_start.get(year, 1.0), 1e-12) - 1.0
        for year in sorted(by_year_end)
    }
    positive_years = sum(1 for value in by_year_return.values() if value > 0.0)
    positive_year_fraction = positive_years / max(len(by_year_return), 1)
    worst_year = min(by_year_return.values()) if by_year_return else 0.0
    win_rate = wins / max(wins + losses, 1)
    calmar = cagr / max(max_dd, 1e-9) if max_dd > 0.0 else 0.0
    score = 0.0
    if total_return > 0.0 and max_dd > 0.0:
        score = max(calmar, 0.0) * math.log1p(max(total_return, 0.0)) * max(positive_year_fraction, 0.05)

    if period_count < min_periods or years < 0.5:
        decision = "REJECT_SAMPLE"
    elif total_return <= 0.0:
        decision = "REJECT_NEGATIVE"
    elif max_dd > 0.55:
        decision = "REJECT_DRAWDOWN"
    elif cagr >= 0.20 and calmar >= 0.50 and positive_year_fraction >= 0.65:
        decision = "PAPER_RESEARCH"
    elif cagr >= 0.08 and calmar >= 0.25:
        decision = "WATCH"
    else:
        decision = "REJECT_WEAK"

    return {
        "model_id": config.model_id,
        "symbol": symbol,
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
        "positive_year_count": positive_years,
        "year_count": len(by_year_return),
        "positive_year_fraction": round(positive_year_fraction, 4),
        "worst_year_pct": round(worst_year * 100.0, 4),
        "by_year_return_pct": {year: round(value * 100.0, 4) for year, value in by_year_return.items()},
        "win_rate_period": round(win_rate, 4),
        "active_fraction": round(active_periods / max(period_count, 1), 4),
        "turnover_sum": round(turnover_sum, 4),
        "avg_daily_turnover": round(turnover_sum / max(years * 365.25, 1e-9), 4),
        "cost_drag_pct_simple_sum": round(cost_drag * 100.0, 4),
        "buffer_stop_count": buffer_stop_count,
        "event_reasons": dict(sorted(event_reasons.items())),
        "direction_periods": dict(sorted(direction_periods.items())),
        "score": round(score, 6),
        "samples": samples,
    }


def _buy_hold_benchmark(features: FeatureSet) -> dict[str, Any]:
    if not features.bars:
        return {"return_pct_1x": 0.0, "first_ts": None, "last_ts": None}
    first = features.bars[0]
    last = features.bars[-1]
    return {
        "first_ts": first.ts.isoformat(),
        "last_ts": last.ts.isoformat(),
        "first_close": first.c,
        "last_close": last.c,
        "return_pct_1x": round((last.c / first.c - 1.0) * 100.0, 4) if first.c > 0.0 else 0.0,
    }


def _write_summary_md(path: Path, output: dict[str, Any]) -> None:
    lines = [
        "# 나뇨띠식 범용 추세 순환매 백테스트",
        "",
        f"- 생성 시각: {output['generated_at']}",
        f"- 심볼: {output['scope']['symbol']}",
        f"- 기간: {output['scope']['days']}일",
        f"- 테스트 모델: {output['scope']['model_count']}개",
        f"- 판정 분포: {output['decision_counts']}",
        "",
        "## 상위 결과",
        "",
        "| 순위 | 판정 | 모델 | 총수익 | CAGR | MDD | Calmar | 활성비율 | 버퍼스탑 | 연도별 |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for idx, row in enumerate(output["top"][:20], start=1):
        summary = row["summary"]
        lines.append(
            f"| {idx} | {summary['decision']} | `{summary['model_id']}` | "
            f"{summary['total_return_pct']} | {summary['cagr_pct']} | {summary['max_drawdown_pct']} | "
            f"{summary['calmar']} | {summary['active_fraction']} | {summary['buffer_stop_count']} | "
            f"`{summary['by_year_return_pct']}` |"
        )
    lines.extend(
        [
            "",
            "## 최악 연도 방어 상위",
            "",
            "| 순위 | 판정 | 모델 | 총수익 | CAGR | MDD | 최악연도 | 연도별 |",
            "|---:|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for idx, row in enumerate(output.get("top_robust_year", [])[:10], start=1):
        summary = row["summary"]
        lines.append(
            f"| {idx} | {summary['decision']} | `{summary['model_id']}` | "
            f"{summary['total_return_pct']} | {summary['cagr_pct']} | {summary['max_drawdown_pct']} | "
            f"{summary['worst_year_pct']} | `{summary['by_year_return_pct']}` |"
        )
    lines.extend(
        [
            "",
            "## 해석",
            "",
            "이 버전은 메시지 이벤트를 직접 매수/매도 신호로 쓰지 않고, 메시지에서 반복된 원칙을 가격 기반 규칙으로 바꾼다.",
            "상위 추세가 확인되면 추세 방향 포지션을 유지하고, 약화/트레일/청산가 버퍼 접근 때는 빠진다. 반대 추세가 확인되면 플립한다.",
            "따라서 메시지가 없는 구간도 계속 평가하지만, 횡보장에서는 수수료와 잦은 뒤집기가 성과를 크게 낮출 수 있다.",
        ]
    )
    atomic_write_text(path, "\n".join(lines) + "\n")


def main() -> int:
    args = _parse_args()
    generated_at = datetime.now(UTC)
    settings = get_settings()
    symbol = str(args.symbol or "BTCUSDT").strip().upper()
    base_url = str(args.base_url or settings.binance_rest_base_url or "https://fapi.binance.com").rstrip("/")
    cache_dir = ROOT_DIR / str(args.cache_dir)
    configs = build_configs(args)
    intervals = sorted({config.interval for config in configs})
    cost_bps = max(float(args.fee_bps_per_side) + float(args.slippage_bps_per_side), 0.0)

    features_by_interval: dict[str, FeatureSet] = {}
    data_status: dict[str, Any] = {}
    for interval in intervals:
        bars = _load_bars(
            symbol=symbol,
            interval=interval,
            days=max(int(args.days), 30),
            cache_dir=cache_dir,
            base_url=base_url,
            sleep_seconds=float(args.sleep_seconds),
        )
        features_by_interval[interval] = FeatureSet(bars)
        data_status[interval] = {
            "bars": len(bars),
            "first_ts": bars[0].ts.isoformat() if bars else None,
            "last_ts": bars[-1].ts.isoformat() if bars else None,
        }

    rows: list[dict[str, Any]] = []
    for idx, config in enumerate(configs, start=1):
        summary = backtest_config(
            symbol=symbol,
            features=features_by_interval[config.interval],
            config=config,
            cost_bps_per_side=cost_bps,
            min_periods=max(int(args.min_periods), 1),
        )
        rows.append({"rank_input_order": idx, "config": asdict(config), "summary": summary})
        if idx % 100 == 0:
            print(json.dumps({"progress_models": idx, "latest_model": config.model_id}), flush=True)

    top = sorted(
        rows,
        key=lambda row: (
            float(row["summary"].get("score", 0.0) or 0.0),
            float(row["summary"].get("total_return_pct", 0.0) or 0.0),
            -float(row["summary"].get("max_drawdown_pct", 100.0) or 100.0),
        ),
        reverse=True,
    )[:30]
    top_robust_year = sorted(
        rows,
        key=lambda row: (
            float(row["summary"].get("worst_year_pct", -100.0) or -100.0),
            float(row["summary"].get("total_return_pct", 0.0) or 0.0),
            -float(row["summary"].get("max_drawdown_pct", 100.0) or 100.0),
        ),
        reverse=True,
    )[:30]
    decision_counts = Counter(str(row["summary"].get("decision") or "") for row in rows)
    output = {
        "schema_version": "nanyotti_trend_rotation_backtest_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "research_only_no_live_authority_change",
        "scope": {
            "symbol": symbol,
            "days": max(int(args.days), 30),
            "intervals": intervals,
            "model_count": len(rows),
            "min_periods": max(int(args.min_periods), 1),
        },
        "strategy_proxy": {
            "description": (
                "All-market price-rule proxy: confirmed EMA/ATR trend side, hold while trend persists, "
                "exit on trend weakness/trailing stop/liquidation-buffer pressure, flip only after opposite confirmation."
            ),
            "explicit_non_claims": [
                "This is not a clone of a private discretionary method.",
                "It does not use Telegram messages as future trade signals.",
                "It is a mechanical research proxy intended for falsification and iteration.",
            ],
        },
        "cost_model": {
            "fee_bps_per_side": float(args.fee_bps_per_side),
            "slippage_bps_per_side": float(args.slippage_bps_per_side),
            "base_cost_bps_per_side": cost_bps,
            "notes": [
                "signals use completed candles and execute at next candle open",
                "turnover includes entry, exit, and flip notional changes",
                "funding, queue priority, and gap slippage beyond the buffer stop approximation are not modeled",
            ],
        },
        "data_status": data_status,
        "buy_hold_benchmark_by_interval": {
            interval: _buy_hold_benchmark(features)
            for interval, features in sorted(features_by_interval.items())
        },
        "decision_counts": dict(sorted(decision_counts.items())),
        "top": top,
        "top_robust_year": top_robust_year,
        "all_results": rows,
    }

    if args.write_report:
        report_dir = ROOT_DIR / str(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        out_path = report_dir / f"nanyotti_trend_rotation_backtest_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        latest_path = report_dir / "latest.json"
        summary_path = report_dir / "latest_summary.md"
        output["report_path"] = str(out_path.relative_to(ROOT_DIR))
        output["latest_report_path"] = str(latest_path.relative_to(ROOT_DIR))
        output["latest_summary_path"] = str(summary_path.relative_to(ROOT_DIR))
        atomic_write_text(out_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(latest_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))
        _write_summary_md(summary_path, output)

    print(json.dumps({key: value for key, value in output.items() if key != "all_results"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
