#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import CURRENT_MICRO_LIVE_USDT_SYMBOLS, get_settings
from app.services.micro_main_strategy_research import (
    Direction,
    MicroSignal,
    MicroTrade,
    SessionImpulseRetestExitPolicy,
    SessionImpulseRetestResearch,
    session_impulse_retest_profile_for_symbol,
)
from app.services.report_io import atomic_write_text
from scripts.run_micro_main_exit_policy_search import _csv, _trade_row, build_exit_policies, summarize_rows
from scripts.run_micro_main_usdt_proxy_backtest import _fetch_1m_klines, _resample_to_5m


class IntrabarSessionImpulseRetestResearch(SessionImpulseRetestResearch):
    def _partial_5m_bar(self, one_minute_idx: int) -> dict[str, Any] | None:
        ts = self.ts_1m[one_minute_idx]
        bucket_minute = (ts.minute // 5) * 5
        bucket_ts = ts.replace(minute=bucket_minute, second=0, microsecond=0)
        setup_idx = self._index_5m_by_ts.get(bucket_ts)
        bucket_start_idx = self._index_1m_by_ts.get(bucket_ts)
        if setup_idx is None or bucket_start_idx is None or bucket_start_idx > one_minute_idx:
            return None
        high = max(self.highs_1m[bucket_start_idx:one_minute_idx + 1])
        low = min(self.lows_1m[bucket_start_idx:one_minute_idx + 1])
        volume = sum(self.volumes_1m[bucket_start_idx:one_minute_idx + 1])
        elapsed = one_minute_idx - bucket_start_idx + 1
        return {
            "setup_idx": setup_idx,
            "bucket_ts": bucket_ts,
            "bucket_start_idx": bucket_start_idx,
            "elapsed_minutes": elapsed,
            "o": float(self.opens_1m[bucket_start_idx]),
            "h": float(high),
            "l": float(low),
            "c": float(self.closes_1m[one_minute_idx]),
            "v": float(volume),
            "projected_5m_volume": float(volume) * 5.0 / max(float(elapsed), 1.0),
        }

    @staticmethod
    def _bar_range(bar: dict[str, Any]) -> float:
        return float(bar["h"] - bar["l"])

    @staticmethod
    def _body_size(bar: dict[str, Any]) -> float:
        return float(abs(bar["c"] - bar["o"]))

    @classmethod
    def _close_position(cls, bar: dict[str, Any]) -> float:
        rng = max(cls._bar_range(bar), 1e-9)
        return float((bar["c"] - bar["l"]) / rng)

    def _partial_session_vwap(self, *, setup_idx: int, partial_bar: dict[str, Any]) -> float:
        setup_ts = self.ts_5m[setup_idx]
        cumulative_pv = 0.0
        cumulative_volume = 0.0
        start_idx = setup_idx
        while start_idx > 0 and self.ts_5m[start_idx - 1].date() == setup_ts.date():
            start_idx -= 1
        for idx in range(start_idx, setup_idx):
            typical = (self.highs_5m[idx] + self.lows_5m[idx] + self.closes_5m[idx]) / 3.0
            volume = max(self.volumes_5m[idx], 1e-9)
            cumulative_pv += typical * volume
            cumulative_volume += volume
        partial_volume = max(float(partial_bar["v"]), 1e-9)
        partial_typical = (float(partial_bar["h"]) + float(partial_bar["l"]) + float(partial_bar["c"])) / 3.0
        cumulative_pv += partial_typical * partial_volume
        cumulative_volume += partial_volume
        return float(cumulative_pv / max(cumulative_volume, 1e-9))

    def _build_intrabar_signal(self, one_minute_idx: int) -> MicroSignal | None:
        partial_bar = self._partial_5m_bar(one_minute_idx)
        if partial_bar is None:
            return None
        setup_idx = int(partial_bar["setup_idx"])
        if setup_idx < 60 or setup_idx >= len(self.candles_5m) - 2:
            return None

        next_idx = one_minute_idx + 1
        if next_idx >= len(self.candles_1m):
            return None

        profile = self._signal_filter_profile()
        setup_ts = self.ts_5m[setup_idx]
        if setup_ts.hour in self._blocked_signal_hours():
            return None
        session_anchor = self._session_anchor_index(setup_idx)
        if session_anchor is None:
            return None
        offset = setup_idx - session_anchor
        if offset < int(profile["min_offset_bars"]) or offset > int(profile["max_offset_bars"]):
            return None

        atr_idx = max(setup_idx - 1, 0)
        atr = max(float(self.atr_5m[atr_idx]), 1e-9)
        orb_end = min(session_anchor + 4, len(self.candles_5m))
        if setup_idx <= orb_end:
            return None
        orb_high = self._rolling_high_5m(session_anchor, orb_end)
        orb_low = self._rolling_low_5m(session_anchor, orb_end)
        orb_width = orb_high - orb_low
        if orb_width <= float(profile["min_orb_width_atr"]) * atr or orb_width >= float(profile["max_orb_width_atr"]) * atr:
            return None

        trend_strength = abs(self.ema_fast_5m[atr_idx] - self.ema_slow_5m[atr_idx]) / atr
        if trend_strength < float(profile["min_trend_strength"]):
            return None

        volume_med = self._volume_median_5m(setup_idx - 16, setup_idx)
        drive_high = self._rolling_high_5m(orb_end, setup_idx)
        drive_low = self._rolling_low_5m(orb_end, setup_idx)
        vwap = self._partial_session_vwap(setup_idx=setup_idx, partial_bar=partial_bar)
        volume_factor = float(partial_bar["projected_5m_volume"] / max(volume_med, 1e-9))
        reclaim_body_atr = float(self._body_size(partial_bar) / atr)
        reclaim_close_position = float(self._close_position(partial_bar))
        base_diagnostics: dict[str, Any] = {
            "entry_timing_model": "intrabar_1m_confirm_next_open",
            "setup_hour_utc": setup_ts.hour,
            "setup_weekday_utc": setup_ts.weekday(),
            "offset_bars": offset,
            "orb_width_atr": float(orb_width / atr),
            "trend_strength_atr": float(trend_strength),
            "volume_factor": volume_factor,
            "raw_partial_volume_factor": float(partial_bar["v"] / max(volume_med, 1e-9)),
            "intrabar_elapsed_minutes": int(partial_bar["elapsed_minutes"]),
            "reclaim_body_atr": reclaim_body_atr,
            "reclaim_close_position": reclaim_close_position,
        }

        breakout_long = any(
            self.closes_5m[probe] > orb_high + float(profile["breakout_buffer_atr"]) * max(self.atr_5m[probe], 1e-9)
            and self._body_size_5m(probe) >= float(profile["min_breakout_body_atr"]) * max(self.atr_5m[probe], 1e-9)
            and self._close_position_in_bar_5m(probe) >= float(profile["min_breakout_close_long"])
            for probe in range(orb_end, setup_idx)
        )
        long_reclaim = max(orb_high, vwap)
        if (
            self.ema_fast_5m[atr_idx] > self.ema_slow_5m[atr_idx]
            and drive_high >= orb_high + float(profile["min_drive_extension_atr"]) * atr
            and breakout_long
            and float(partial_bar["l"]) <= long_reclaim + float(profile["reclaim_touch_buffer_atr"]) * atr
            and float(partial_bar["l"]) >= long_reclaim - float(profile["reclaim_overshoot_atr"]) * atr
            and float(partial_bar["c"]) >= long_reclaim + float(profile["reclaim_close_buffer_atr"]) * atr
            and float(partial_bar["c"]) > float(partial_bar["o"])
            and self._body_size(partial_bar) >= float(profile["min_reclaim_body_atr"]) * atr
            and self._close_position(partial_bar) >= float(profile["min_reclaim_close_long"])
            and float(partial_bar["projected_5m_volume"]) >= max(volume_med * float(profile["min_volume_factor"]), 1e-9)
        ):
            return self._intrabar_signal_from_setup(
                setup_idx=setup_idx,
                partial_bar=partial_bar,
                next_idx=next_idx,
                direction="long",
                reclaim_level=long_reclaim,
                atr=atr,
                orb_width=orb_width,
                drive_reference=drive_high,
                drive_extension_atr=float((drive_high - orb_high) / atr),
                reclaim_overshoot_atr=float((long_reclaim - float(partial_bar["l"])) / atr),
                base_diagnostics=base_diagnostics,
            )

        breakout_short = any(
            self.closes_5m[probe] < orb_low - float(profile["breakout_buffer_atr"]) * max(self.atr_5m[probe], 1e-9)
            and self._body_size_5m(probe) >= float(profile["min_breakout_body_atr"]) * max(self.atr_5m[probe], 1e-9)
            and self._close_position_in_bar_5m(probe) <= float(profile["max_breakout_close_short"])
            for probe in range(orb_end, setup_idx)
        )
        short_reclaim = min(orb_low, vwap)
        if (
            self.ema_fast_5m[atr_idx] < self.ema_slow_5m[atr_idx]
            and drive_low <= orb_low - float(profile["min_drive_extension_atr"]) * atr
            and breakout_short
            and float(partial_bar["h"]) >= short_reclaim - float(profile["reclaim_touch_buffer_atr"]) * atr
            and float(partial_bar["h"]) <= short_reclaim + float(profile["reclaim_overshoot_atr"]) * atr
            and float(partial_bar["c"]) <= short_reclaim - float(profile["reclaim_close_buffer_atr"]) * atr
            and float(partial_bar["c"]) < float(partial_bar["o"])
            and self._body_size(partial_bar) >= float(profile["min_reclaim_body_atr"]) * atr
            and self._close_position(partial_bar) <= float(profile["max_reclaim_close_short"])
            and float(partial_bar["projected_5m_volume"]) >= max(volume_med * float(profile["min_volume_factor"]), 1e-9)
        ):
            return self._intrabar_signal_from_setup(
                setup_idx=setup_idx,
                partial_bar=partial_bar,
                next_idx=next_idx,
                direction="short",
                reclaim_level=short_reclaim,
                atr=atr,
                orb_width=orb_width,
                drive_reference=drive_low,
                drive_extension_atr=float((orb_low - drive_low) / atr),
                reclaim_overshoot_atr=float((float(partial_bar["h"]) - short_reclaim) / atr),
                base_diagnostics=base_diagnostics,
            )
        return None

    def _intrabar_signal_from_setup(
        self,
        *,
        setup_idx: int,
        partial_bar: dict[str, Any],
        next_idx: int,
        direction: Direction,
        reclaim_level: float,
        atr: float,
        orb_width: float,
        drive_reference: float,
        drive_extension_atr: float,
        reclaim_overshoot_atr: float,
        base_diagnostics: dict[str, Any],
    ) -> MicroSignal | None:
        profile = self._signal_filter_profile()
        entry_ts = self.ts_1m[next_idx]
        entry_price = float(self.opens_1m[next_idx])
        if direction == "long":
            stop = min(float(partial_bar["l"]), reclaim_level) - float(profile["stop_buffer_atr"]) * atr
            risk_abs = entry_price - stop
            direction_sign = 1.0
        else:
            stop = max(float(partial_bar["h"]), reclaim_level) + float(profile["stop_buffer_atr"]) * atr
            risk_abs = stop - entry_price
            direction_sign = -1.0
        min_risk_abs = max(float(profile["min_risk_atr"]) * atr, entry_price * float(profile["min_risk_pct"]))
        risk_atr = float(risk_abs / atr)
        if risk_abs < min_risk_abs or risk_abs > float(profile["max_risk_atr"]) * atr:
            return None
        if not self._passes_late_retest_risk_filter(profile, risk_atr=risk_atr, retest_wait_minutes=0):
            return None

        structure_context = self._higher_timeframe_structure_context(
            setup_idx=setup_idx,
            direction=direction,
            entry_price=entry_price,
            atr=atr,
        )
        target_prices: list[float]
        target_sources: list[str]
        if direction == "long":
            raw_targets: list[tuple[str, float]] = [
                ("drive_high", drive_reference),
                ("opening_range_measured_move_1x", reclaim_level + orb_width),
                ("opening_range_measured_move_1_5x", reclaim_level + 1.5 * orb_width),
                ("opening_range_measured_move_2x", reclaim_level + 2.0 * orb_width),
            ]
            target_prices = [float(price) for _source, price in raw_targets if float(price) > entry_price]
            target_sources = [source for source, price in raw_targets if float(price) > entry_price]
            htf_ok = lambda value: float(value) > entry_price
        else:
            raw_targets = [
                ("drive_low", drive_reference),
                ("opening_range_measured_move_1x", reclaim_level - orb_width),
                ("opening_range_measured_move_1_5x", reclaim_level - 1.5 * orb_width),
                ("opening_range_measured_move_2x", reclaim_level - 2.0 * orb_width),
            ]
            target_prices = [float(price) for _source, price in raw_targets if 0.0 < float(price) < entry_price]
            target_sources = [source for source, price in raw_targets if 0.0 < float(price) < entry_price]
            htf_ok = lambda value: 0.0 < float(value) < entry_price
        for htf_source, htf_price in zip(
            list(structure_context.get("htf_structure_target_sources") or []),
            list(structure_context.get("htf_structure_target_prices") or []),
            strict=False,
        ):
            if htf_ok(float(htf_price)):
                target_sources.append(f"htf:{htf_source}")
                target_prices.append(float(htf_price))
        diagnostics = {
            **base_diagnostics,
            "setup_ts": self.ts_5m[setup_idx].isoformat(),
            "signal_1m_ts": self.ts_1m[next_idx - 1].isoformat(),
            "entry_key_level": float(reclaim_level),
            "entry_actionable_ts": entry_ts.isoformat(),
            "entry_confirmation_delay_minutes": 0,
            "entry_zone_low": float(reclaim_level - float(profile["entry_retest_buffer_atr"]) * atr),
            "entry_zone_high": float(reclaim_level + float(profile["entry_retest_buffer_atr"]) * atr),
            "entry_distance_atr": float(abs(entry_price - reclaim_level) / atr),
            "stop_key_level": float(min(float(partial_bar["l"]), reclaim_level) if direction == "long" else max(float(partial_bar["h"]), reclaim_level)),
            "structure_target_prices": target_prices,
            "structure_target_sources": target_sources,
            "drive_extension_atr": drive_extension_atr,
            "reclaim_overshoot_atr": reclaim_overshoot_atr,
            "retest_wait_minutes": 0,
            "risk_atr": risk_atr,
            "risk_pct": float(risk_abs / max(entry_price, 1e-9)),
            **structure_context,
        }
        return self._apply_exit_policy(
            MicroSignal(
                family="session_impulse_retest",
                direction=direction,
                signal_ts=self.ts_1m[next_idx - 1],
                setup_ts=self.ts_5m[setup_idx],
                entry_ts=entry_ts,
                entry_price=entry_price,
                stop_price=stop,
                target_price=entry_price + direction_sign * 2.0 * risk_abs,
                max_hold_minutes=self._MAX_HOLD_MINUTES,
                regime_hint="session_open_intrabar",
                diagnostics=diagnostics,
            )
        )

    def intrabar_backtest(self) -> list[MicroTrade]:
        trades: list[MicroTrade] = []
        if len(self.candles_5m) < 80 or len(self.candles_1m) < 600:
            return trades
        used_setup_buckets: set[datetime] = set()
        start_ts = self.ts_5m[60]
        start_idx = self._index_1m_by_ts.get(start_ts, 0)
        idx = max(start_idx, 0)
        while idx < len(self.candles_1m) - 2:
            partial_bar = self._partial_5m_bar(idx)
            if partial_bar is None:
                idx += 1
                continue
            bucket_ts = partial_bar["bucket_ts"]
            if bucket_ts in used_setup_buckets:
                idx += 1
                continue
            signal = self._build_intrabar_signal(idx)
            if signal is None:
                idx += 1
                continue
            trade = self._simulate_trade(signal)
            used_setup_buckets.add(bucket_ts)
            if trade is not None:
                trades.append(trade)
            idx += 1
        return trades


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research live-realistic intrabar SIR entries.")
    parser.add_argument("--symbols", default=CURRENT_MICRO_LIVE_USDT_SYMBOLS)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument(
        "--policies",
        default=(
            "legacy_live_split_1r35_2r65,"
            "structure_adaptive_floor_min_0_003_live_split,"
            "structure_buffered_swing6_stop0.12_tpbuf0.08"
        ),
    )
    parser.add_argument("--report-dir", default="reports/validation/micro_main_intrabar_research")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--include-trades", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def _policy_names(value: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in str(value or "").split(","):
        item = raw.strip()
        if item and item not in seen:
            out.append(item)
            seen.add(item)
    return out


def _select_policies(names: list[str]) -> list[SessionImpulseRetestExitPolicy]:
    by_name = {policy.name: policy for policy in build_exit_policies()}
    missing = [name for name in names if name not in by_name]
    if missing:
        raise SystemExit(f"unknown policies: {','.join(missing)}")
    return [intrabar_exit_policy(by_name[name]) for name in names]


def intrabar_exit_policy(policy: SessionImpulseRetestExitPolicy) -> SessionImpulseRetestExitPolicy:
    return replace(policy, entry_confirmation_delay_minutes=0)


def _nested_value(row: dict[str, Any], key: str, default: str = "unknown") -> str:
    if key.startswith("diagnostics."):
        value: Any = row.get("diagnostics")
        parts = key.split(".")[1:]
    else:
        value = row
        parts = key.split(".")
    for part in parts:
        if not isinstance(value, dict):
            return default
        value = value.get(part)
    if value in (None, ""):
        return default
    return str(value)


def _grouped_summaries(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_nested_value(row, key), []).append(row)
    summaries = {name: summarize_rows(items) for name, items in grouped.items()}
    return dict(
        sorted(
            summaries.items(),
            key=lambda item: float(item[1].get("total_r", 0.0) or 0.0),
            reverse=True,
        )
    )


def _report_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    generated_at = datetime.now(UTC)
    symbols = _csv(args.symbols)
    policies = _select_policies(_policy_names(args.policies))
    end_ts = datetime.now(UTC).replace(second=0, microsecond=0)
    start_ts = end_ts - timedelta(days=max(int(args.days), 1))
    rows_by_policy: dict[str, list[dict[str, Any]]] = {policy.name: [] for policy in policies}
    data_status: dict[str, Any] = {}

    with (
        httpx.Client(timeout=120.0, follow_redirects=True) as monthly_client,
        httpx.Client(base_url=settings.binance_rest_base_url, timeout=30.0) as rest_client,
    ):
        for symbol in symbols:
            candles_1m = _fetch_1m_klines(monthly_client, rest_client, symbol=symbol, start_ts=start_ts, end_ts=end_ts)
            candles_5m = _resample_to_5m(candles_1m)
            data_status[symbol] = {
                "candles_1m": len(candles_1m),
                "candles_5m": len(candles_5m),
                "first_1m_ts": candles_1m[0].ts.isoformat() if candles_1m else None,
                "last_1m_ts": candles_1m[-1].ts.isoformat() if candles_1m else None,
            }
            if len(candles_1m) < 600 or len(candles_5m) < 200:
                print(json.dumps({"symbol": symbol, "status": "insufficient_candles", **data_status[symbol]}), file=sys.stderr, flush=True)
                continue
            for policy in policies:
                engine = IntrabarSessionImpulseRetestResearch(
                    symbol=symbol,
                    candles_1m=candles_1m,
                    candles_5m=candles_5m,
                    profile_name=session_impulse_retest_profile_for_symbol(symbol),
                    exit_policy=policy,
                )
                trades = engine.intrabar_backtest()
                rows_by_policy[policy.name].extend(_trade_row(trade, policy=policy) for trade in trades)
            print(json.dumps({"symbol": symbol, "status": "done", **data_status[symbol]}), file=sys.stderr, flush=True)

    results = []
    for policy in policies:
        rows = rows_by_policy[policy.name]
        item: dict[str, Any] = {
            "policy": asdict(policy),
            "summary": summarize_rows(rows),
            "breakdowns": {
                "by_symbol": _grouped_summaries(rows, "symbol"),
                "by_direction": _grouped_summaries(rows, "direction"),
                "by_exit_reason": _grouped_summaries(rows, "exit_reason"),
                "by_setup_hour_utc": _grouped_summaries(rows, "diagnostics.setup_hour_utc"),
                "by_intrabar_elapsed_minutes": _grouped_summaries(rows, "diagnostics.intrabar_elapsed_minutes"),
            },
        }
        if args.include_trades:
            item["trades"] = rows
        results.append(item)
    output = {
        "schema_version": "micro_main_intrabar_research_v1",
        "generated_at": generated_at.isoformat(),
        "scope": {
            "symbols": symbols,
            "days": int(args.days),
            "start_ts": start_ts.isoformat(),
            "end_ts": end_ts.isoformat(),
            "policy_names": [policy.name for policy in policies],
            "entry_timing_model": "intrabar_1m_confirm_next_open",
            "notes": [
                "Each 1m close builds only the currently known partial 5m OHLCV.",
                "Projected 5m volume is partial_volume * 5 / elapsed_minutes.",
                "Entry is evaluated at the next 1m open after the confirming 1m candle.",
                "This is research-only and does not change live order routing.",
            ],
        },
        "data_status": data_status,
        "results": results,
    }
    if args.write_report:
        out_dir = ROOT_DIR / str(args.report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"micro_main_intrabar_research_{_report_stamp(generated_at)}.json"
        atomic_write_text(out_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))
        output["report_path"] = str(out_path.relative_to(ROOT_DIR))
    if not args.quiet:
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
