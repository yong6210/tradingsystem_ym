#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text
from scripts.run_btc_flip_rotation_search import _csv, _load_bars, Bar
from scripts.run_message_event_level_backtest import (
    BAD_SNIPPET_TOKENS,
    ENTRY_ACTIONS,
    STRICT_SOURCE_KINDS,
)


@dataclass(frozen=True, slots=True)
class ReactionConfig:
    model_id: str
    validity_hours: int
    reaction_wait_bars: int
    close_position_threshold: float
    reclaim_buffer_atr: float
    max_chase_pct: float
    hold_hours: int
    tp_pct: float
    sl_pct: float
    account_exposure: float
    include_done: bool


@dataclass(frozen=True, slots=True)
class ReactionOrder:
    order_id: str
    event_id: str
    message_id: str
    created_ts: datetime
    side: int
    action: str
    source_kind: str
    snippet: str
    reference_price: float
    entry_level: float


@dataclass(frozen=True, slots=True)
class ReactionEntry:
    order: ReactionOrder
    touch_idx: int
    confirm_idx: int
    entry_idx: int
    entry_price: float
    level: float
    reaction_reason: str


@dataclass(frozen=True, slots=True)
class Trade:
    order_id: str
    event_id: str
    message_id: str
    side: int
    action: str
    source_kind: str
    created_ts: datetime
    touch_ts: datetime
    confirm_ts: datetime
    entry_ts: datetime
    exit_ts: datetime
    level: float
    entry: float
    exit: float
    gross_return_pct: float
    net_return_pct: float
    exit_reason: str
    hold_bars: int
    reaction_reason: str
    snippet: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest message-derived price levels with post-touch reaction confirmation.")
    parser.add_argument("--labels", default="reports/research/nanyotti_export/message_event_dataset/message_event_labels.json")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--load-days", type=int, default=1825)
    parser.add_argument("--validity-hours", default="24,72,168")
    parser.add_argument("--reaction-wait-bars", default="1,3,6,12")
    parser.add_argument("--close-position-thresholds", default="0.55,0.65,0.75")
    parser.add_argument("--reclaim-buffer-atrs", default="0,0.05")
    parser.add_argument("--max-chase-pcts", default="0.3,0.6,1.0")
    parser.add_argument("--hold-hours", default="4,12,24")
    parser.add_argument("--tp-pcts", default="0.3,0.6,1.0,1.5")
    parser.add_argument("--sl-pcts", default="0.3,0.5,0.8,1.2")
    parser.add_argument("--account-exposures", default="1,2,3")
    parser.add_argument("--fee-bps-per-side", type=float, default=4.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=1.0)
    parser.add_argument("--cache-dir", default="reports/validation/btc_flip_rotation_search/cache")
    parser.add_argument("--report-dir", default="reports/research/nanyotti_export/message_event_dataset")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    parser.add_argument("--max-configs", type=int, default=0)
    return parser.parse_args()


def _parse_float_csv(raw: str, fallback: list[float]) -> list[float]:
    out: list[float] = []
    for item in _csv(raw):
        try:
            value = float(item)
        except ValueError:
            continue
        if value >= 0.0:
            out.append(value)
    return out or fallback


def _parse_positive_float_csv(raw: str, fallback: list[float]) -> list[float]:
    return [value for value in _parse_float_csv(raw, fallback) if value > 0.0] or fallback


def _parse_int_csv(raw: str, fallback: list[int]) -> list[int]:
    out: list[int] = []
    for item in _csv(raw):
        try:
            value = int(item)
        except ValueError:
            continue
        if value > 0:
            out.append(value)
    return out or fallback


def _side_label(side: int) -> str:
    return "long" if side > 0 else "short" if side < 0 else "flat"


def _bar_index(open_times: list[int], ts: datetime) -> int | None:
    idx = bisect.bisect_right(open_times, int(ts.timestamp() * 1000)) - 1
    if idx < 0:
        return None
    return idx


def _infer_order_side(event: dict[str, Any], *, infer_neutral_side: bool) -> int:
    side = int(event.get("side_value") or 0)
    if side != 0 or not infer_neutral_side:
        return side

    text = str(event.get("snippet") or "").replace(" ", "")
    if any(token in text for token in ("목표가", "도달시", "정리할계획", "손절", "로스")):
        return 0
    long_hit = any(
        token in text
        for token in (
            "롱",
            "Long",
            "long",
            "매수",
            "저깨롱",
            "눌림롱",
            "내림롱",
            "상방",
            "재진입",
            "진입고려",
            "불타기",
            "눌림추격",
            "현물",
            "매집",
            "지지",
        )
    )
    short_hit = any(
        token in text
        for token in (
            "숏",
            "Short",
            "short",
            "매도",
            "고깨숏",
            "하방",
            "저항",
            "하락",
            "이탈",
            "깨지",
            "패닉",
        )
    )
    if long_hit and not short_hit:
        return 1
    if short_hit and not long_hit:
        return -1
    return 0


def _event_allowed(
    event: dict[str, Any],
    *,
    include_done: bool,
    source_kinds: set[str] | None = None,
    infer_neutral_side: bool = False,
) -> bool:
    allowed_source_kinds = source_kinds or STRICT_SOURCE_KINDS
    if event.get("source_kind") not in allowed_source_kinds:
        return False
    if event.get("action") not in ENTRY_ACTIONS:
        return False
    if event.get("action") == "entry_done" and not include_done:
        return False
    if _infer_order_side(event, infer_neutral_side=infer_neutral_side) == 0:
        return False
    if int(event.get("confidence") or 0) < 70:
        return False
    snippet = str(event.get("snippet") or "")
    if any(token in snippet for token in BAD_SNIPPET_TOKENS):
        return False
    if "없음" in snippet and "승부" in snippet:
        return False
    return True


def _levels_from_event(event: dict[str, Any]) -> list[float]:
    levels = [float(item["value"]) for item in event.get("price_levels") or [] if item.get("value")]
    return sorted(set(level for level in levels if 1_000.0 < level < 300_000.0))


def _level_from_event(event: dict[str, Any], side: int | None = None) -> float | None:
    side = int(event["side_value"] if side is None else side)
    reference = event.get("market", {}).get("price")
    levels = _levels_from_event(event)
    if reference is None or not levels:
        return None
    ref = float(reference)
    snippet = str(event.get("snippet") or "")

    if len(levels) >= 2 and max(levels) / min(levels) <= 1.04:
        return sum(levels) / len(levels)

    if side > 0:
        below = [level for level in levels if level <= ref * 1.01]
        if not below:
            return None
        if "보다는" in snippet or "재진입" in snippet:
            return min(below)
        return max(below)

    above = [level for level in levels if level >= ref * 0.99]
    if not above:
        return None
    if "보다는" in snippet or "재진입" in snippet:
        return max(above)
    return min(above)


def build_orders(
    events: list[dict[str, Any]],
    *,
    include_done: bool,
    source_kinds: set[str] | None = None,
    infer_neutral_side: bool = False,
) -> list[ReactionOrder]:
    orders: list[ReactionOrder] = []
    for event in events:
        if not _event_allowed(
            event,
            include_done=include_done,
            source_kinds=source_kinds,
            infer_neutral_side=infer_neutral_side,
        ):
            continue
        side = _infer_order_side(event, infer_neutral_side=infer_neutral_side)
        level = _level_from_event(event, side)
        if level is None:
            continue
        created_ts = datetime.fromisoformat(str(event["date_utc"]))
        if created_ts.tzinfo is None:
            created_ts = created_ts.replace(tzinfo=UTC)
        reference = event.get("market", {}).get("price")
        if reference is None:
            continue
        orders.append(
            ReactionOrder(
                order_id=f"{event['event_id']}:{round(level, 2)}",
                event_id=str(event["event_id"]),
                message_id=str(event["message_id"]),
                created_ts=created_ts.astimezone(UTC),
                side=side,
                action=str(event["action"]),
                source_kind=str(event["source_kind"]),
                snippet=str(event["snippet"]),
                reference_price=float(reference),
                entry_level=float(level),
            )
        )
    orders.sort(key=lambda order: (order.created_ts, order.order_id))
    return orders


def _atr(bars: list[Bar], length: int = 14) -> list[float]:
    out = [0.0] * len(bars)
    q: list[float] = []
    total = 0.0
    prev_close = bars[0].c if bars else 0.0
    for idx, bar in enumerate(bars):
        tr = max(bar.h - bar.l, abs(bar.h - prev_close), abs(bar.l - prev_close))
        q.append(tr)
        total += tr
        if len(q) > length:
            total -= q.pop(0)
        out[idx] = total / max(len(q), 1)
        prev_close = bar.c
    return out


def _find_touch(order: ReactionOrder, bars: list[Bar], open_times: list[int], config: ReactionConfig) -> int | None:
    start_idx = _bar_index(open_times, order.created_ts)
    if start_idx is None:
        return None
    deadline = order.created_ts + timedelta(hours=config.validity_hours)
    end_idx = bisect.bisect_right(open_times, int(deadline.timestamp() * 1000))
    level = order.entry_level
    for idx in range(start_idx + 1, min(end_idx, len(bars))):
        bar = bars[idx]
        if order.side > 0 and bar.l <= level:
            return idx
        if order.side < 0 and bar.h >= level:
            return idx
    return None


def _close_position(bar: Bar) -> float:
    span = max(bar.h - bar.l, 1e-12)
    return (bar.c - bar.l) / span


def _reaction_confirmed(
    *,
    order: ReactionOrder,
    bars: list[Bar],
    atr: list[float],
    touch_idx: int,
    config: ReactionConfig,
) -> ReactionEntry | None:
    level = order.entry_level
    max_idx = min(touch_idx + config.reaction_wait_bars, len(bars) - 2)
    for confirm_idx in range(touch_idx, max_idx + 1):
        bar = bars[confirm_idx]
        prev = bars[max(confirm_idx - 1, 0)]
        buffer = config.reclaim_buffer_atr * max(atr[confirm_idx], 1e-12)
        close_pos = _close_position(bar)
        if order.side > 0:
            reclaimed = bar.c >= level + buffer
            strong_close = close_pos >= config.close_position_threshold
            directional = bar.c > bar.o or bar.c > prev.c
            chase_pct = max((bar.c / level - 1.0) * 100.0, 0.0)
            if reclaimed and strong_close and directional and chase_pct <= config.max_chase_pct:
                entry_idx = confirm_idx + 1
                return ReactionEntry(
                    order=order,
                    touch_idx=touch_idx,
                    confirm_idx=confirm_idx,
                    entry_idx=entry_idx,
                    entry_price=bars[entry_idx].o,
                    level=level,
                    reaction_reason=f"long_reclaim_closepos_{close_pos:.2f}_chase_{chase_pct:.3f}",
                )
        else:
            rejected = bar.c <= level - buffer
            strong_close = close_pos <= 1.0 - config.close_position_threshold
            directional = bar.c < bar.o or bar.c < prev.c
            chase_pct = max((level / bar.c - 1.0) * 100.0, 0.0) if bar.c > 0 else math.inf
            if rejected and strong_close and directional and chase_pct <= config.max_chase_pct:
                entry_idx = confirm_idx + 1
                return ReactionEntry(
                    order=order,
                    touch_idx=touch_idx,
                    confirm_idx=confirm_idx,
                    entry_idx=entry_idx,
                    entry_price=bars[entry_idx].o,
                    level=level,
                    reaction_reason=f"short_reject_closepos_{close_pos:.2f}_chase_{chase_pct:.3f}",
                )
    return None


def _exit_trade(
    *,
    entry: ReactionEntry,
    bars: list[Bar],
    config: ReactionConfig,
    round_trip_cost_pct: float,
) -> Trade:
    order = entry.order
    side = order.side
    entry_price = entry.entry_price
    max_bars = max(int(config.hold_hours * 60 / 5), 1)
    end_idx = min(entry.entry_idx + max_bars, len(bars) - 1)
    if side > 0:
        tp = entry_price * (1.0 + config.tp_pct / 100.0)
        sl = entry_price * (1.0 - config.sl_pct / 100.0)
    else:
        tp = entry_price * (1.0 - config.tp_pct / 100.0)
        sl = entry_price * (1.0 + config.sl_pct / 100.0)

    exit_idx = end_idx
    exit_price = bars[end_idx].c
    exit_reason = "time_exit"
    for idx in range(entry.entry_idx + 1, end_idx + 1):
        bar = bars[idx]
        if side > 0:
            stop_hit = bar.l <= sl
            target_hit = bar.h >= tp
        else:
            stop_hit = bar.h >= sl
            target_hit = bar.l <= tp
        if stop_hit:
            exit_idx = idx
            exit_price = sl
            exit_reason = "stop"
            break
        if target_hit:
            exit_idx = idx
            exit_price = tp
            exit_reason = "target"
            break

    gross = side * (exit_price / entry_price - 1.0) * 100.0
    net = gross - round_trip_cost_pct
    return Trade(
        order_id=order.order_id,
        event_id=order.event_id,
        message_id=order.message_id,
        side=side,
        action=order.action,
        source_kind=order.source_kind,
        created_ts=order.created_ts,
        touch_ts=bars[entry.touch_idx].ts,
        confirm_ts=bars[entry.confirm_idx].ts,
        entry_ts=bars[entry.entry_idx].ts,
        exit_ts=bars[exit_idx].ts,
        level=entry.level,
        entry=entry_price,
        exit=exit_price,
        gross_return_pct=round(gross, 6),
        net_return_pct=round(net, 6),
        exit_reason=exit_reason,
        hold_bars=exit_idx - entry.entry_idx,
        reaction_reason=entry.reaction_reason,
        snippet=order.snippet,
    )


def simulate_config(
    *,
    orders: list[ReactionOrder],
    bars: list[Bar],
    open_times: list[int],
    atr: list[float],
    config: ReactionConfig,
    round_trip_cost_pct: float,
) -> dict[str, Any]:
    trades: list[Trade] = []
    touched = 0
    confirmed = 0
    for order in orders:
        touch_idx = _find_touch(order, bars, open_times, config)
        if touch_idx is None:
            continue
        touched += 1
        entry = _reaction_confirmed(order=order, bars=bars, atr=atr, touch_idx=touch_idx, config=config)
        if entry is None:
            continue
        confirmed += 1
        trades.append(_exit_trade(entry=entry, bars=bars, config=config, round_trip_cost_pct=round_trip_cost_pct))

    trades.sort(key=lambda trade: (trade.entry_ts, trade.order_id))
    sequential: list[Trade] = []
    busy_until: datetime | None = None
    for trade in trades:
        if busy_until is not None and trade.entry_ts < busy_until:
            continue
        sequential.append(trade)
        busy_until = trade.exit_ts

    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    monthly: dict[str, dict[str, float]] = {}
    for trade in sequential:
        month = trade.exit_ts.strftime("%Y-%m")
        if month not in monthly:
            monthly[month] = {"start": equity, "end": equity}
        equity *= max(1.0 + config.account_exposure * trade.net_return_pct / 100.0, 1e-12)
        monthly[month]["end"] = equity
        peak = max(peak, equity)
        max_dd = max(max_dd, 1.0 - equity / peak)

    values = [trade.net_return_pct for trade in trades]
    seq_values = [trade.net_return_pct for trade in sequential]
    doubled = sum(1 for value in monthly.values() if value["start"] > 0.0 and value["end"] / value["start"] - 1.0 >= 1.0)
    reason_counts: dict[str, int] = {}
    for trade in trades:
        reason_counts[trade.exit_reason] = reason_counts.get(trade.exit_reason, 0) + 1

    return {
        "model_id": config.model_id,
        "validity_hours": config.validity_hours,
        "reaction_wait_bars": config.reaction_wait_bars,
        "close_position_threshold": config.close_position_threshold,
        "reclaim_buffer_atr": config.reclaim_buffer_atr,
        "max_chase_pct": config.max_chase_pct,
        "hold_hours": config.hold_hours,
        "tp_pct": config.tp_pct,
        "sl_pct": config.sl_pct,
        "account_exposure": config.account_exposure,
        "include_done": config.include_done,
        "orders": len(orders),
        "touched_orders": touched,
        "confirmed_orders": confirmed,
        "filled_orders": len(trades),
        "touch_rate": round(touched / len(orders), 6) if orders else 0.0,
        "confirmation_rate": round(confirmed / touched, 6) if touched else 0.0,
        "sequential_trades": len(sequential),
        "avg_net_return_pct": round(mean(values), 6) if values else 0.0,
        "median_net_return_pct": round(median(values), 6) if values else 0.0,
        "win_rate": round(sum(value > 0 for value in values) / len(values), 6) if values else 0.0,
        "sequential_avg_net_return_pct": round(mean(seq_values), 6) if seq_values else 0.0,
        "sequential_win_rate": round(sum(value > 0 for value in seq_values) / len(seq_values), 6) if seq_values else 0.0,
        "final_equity": round(equity, 8),
        "total_return_pct": round((equity - 1.0) * 100.0, 6),
        "max_drawdown_pct": round(max_dd * 100.0, 6),
        "months": len(monthly),
        "months_doubled": doubled,
        "exit_reasons": reason_counts,
        "score": round((equity - 1.0) - 1.25 * max_dd, 6),
        "sample_trades": [_trade_to_dict(trade) for trade in sequential[:10] + sequential[-10:] if sequential],
    }


def _trade_to_dict(trade: Trade) -> dict[str, Any]:
    return {
        "order_id": trade.order_id,
        "message_id": trade.message_id,
        "side": _side_label(trade.side),
        "action": trade.action,
        "source_kind": trade.source_kind,
        "created_ts": trade.created_ts.isoformat(),
        "touch_ts": trade.touch_ts.isoformat(),
        "confirm_ts": trade.confirm_ts.isoformat(),
        "entry_ts": trade.entry_ts.isoformat(),
        "exit_ts": trade.exit_ts.isoformat(),
        "level": round(trade.level, 2),
        "entry": round(trade.entry, 2),
        "exit": round(trade.exit, 2),
        "net_return_pct": trade.net_return_pct,
        "exit_reason": trade.exit_reason,
        "reaction_reason": trade.reaction_reason,
        "snippet": trade.snippet,
    }


def build_configs(args: argparse.Namespace) -> list[ReactionConfig]:
    configs: list[ReactionConfig] = []
    for include_done in (False, True):
        for validity in _parse_int_csv(args.validity_hours, [24, 72, 168]):
            for wait in _parse_int_csv(args.reaction_wait_bars, [1, 3, 6]):
                for close_pos in _parse_positive_float_csv(args.close_position_thresholds, [0.55, 0.65]):
                    for buffer_atr in _parse_float_csv(args.reclaim_buffer_atrs, [0.0, 0.05]):
                        for max_chase in _parse_positive_float_csv(args.max_chase_pcts, [0.3, 0.6]):
                            for hold in _parse_int_csv(args.hold_hours, [4, 12, 24]):
                                for tp in _parse_positive_float_csv(args.tp_pcts, [0.6, 1.0]):
                                    for sl in _parse_positive_float_csv(args.sl_pcts, [0.4, 0.8]):
                                        for exposure in _parse_positive_float_csv(args.account_exposures, [1.0, 2.0]):
                                            configs.append(
                                                ReactionConfig(
                                                    model_id=(
                                                        f"msg_react:valid{validity}h:wait{wait}:"
                                                        f"cp{close_pos:g}:buf{buffer_atr:g}:chase{max_chase:g}:"
                                                        f"hold{hold}h:tp{tp:g}:sl{sl:g}:gross{exposure:g}:"
                                                        f"{'withDone' if include_done else 'plansOnly'}"
                                                    ),
                                                    validity_hours=validity,
                                                    reaction_wait_bars=wait,
                                                    close_position_threshold=close_pos,
                                                    reclaim_buffer_atr=buffer_atr,
                                                    max_chase_pct=max_chase,
                                                    hold_hours=hold,
                                                    tp_pct=tp,
                                                    sl_pct=sl,
                                                    account_exposure=exposure,
                                                    include_done=include_done,
                                                )
                                            )
    if int(args.max_configs) > 0:
        configs = configs[: int(args.max_configs)]
    return configs


def _write_summary_md(path: Path, report: dict[str, Any]) -> None:
    top = report["top_results"][0] if report["top_results"] else {}
    lines = [
        "# 메시지 가격대 반응 확인 백테스트",
        "",
        f"- 생성 시각: {report['created_at']}",
        f"- 주문 후보: {report['orders_plans_only']}개(plans only), {report['orders_with_done']}개(with done)",
        f"- 테스트 조합: {report['tested_configs']}개",
        f"- 최고 조합: `{top.get('model_id', '')}`",
        f"- 최고 조합 총수익: {top.get('total_return_pct', '')}%",
        f"- 최고 조합 MDD: {top.get('max_drawdown_pct', '')}%",
        f"- 최고 조합 순차 거래 수: {top.get('sequential_trades', '')}",
        f"- 월 2배 달성 월 수: {top.get('months_doubled', '')}",
        "",
        "## 상위 10개",
        "",
        "| 순위 | 모델 | 총수익 | MDD | 거래수 | 승률 | 터치율 | 확인율 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for idx, result in enumerate(report["top_results"][:10], start=1):
        lines.append(
            f"| {idx} | `{result['model_id']}` | {result['total_return_pct']} | "
            f"{result['max_drawdown_pct']} | {result['sequential_trades']} | "
            f"{result['sequential_win_rate']} | {result['touch_rate']} | {result['confirmation_rate']} |"
        )
    lines.extend(
        [
            "",
            "## 해석",
            "",
            "이 버전은 가격대에 닿아도 바로 진입하지 않는다. 롱은 레벨 회복과 상단 마감, 숏은 레벨 재이탈과 하단 마감을 확인한 뒤 다음 봉 시가로 진입한다.",
            "같은 봉에서 TP와 SL이 모두 닿으면 보수적으로 SL을 먼저 처리한다.",
        ]
    )
    atomic_write_text(path, "\n".join(lines) + "\n")


def _write_trades_csv(path: Path, model_id: str, trades: list[dict[str, Any]]) -> None:
    fields = [
        "model_id",
        "message_id",
        "side",
        "action",
        "created_ts",
        "touch_ts",
        "confirm_ts",
        "entry_ts",
        "exit_ts",
        "level",
        "entry",
        "exit",
        "net_return_pct",
        "exit_reason",
        "reaction_reason",
        "snippet",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for trade in trades:
            row = {field: trade.get(field) for field in fields}
            row["model_id"] = model_id
            writer.writerow(row)


def main() -> None:
    args = _parse_args()
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    settings = get_settings()
    base_url = str(args.base_url or settings.binance_rest_base_url or "https://fapi.binance.com").rstrip("/")
    bars = _load_bars(
        symbol=args.symbol,
        interval=args.interval,
        days=int(args.load_days),
        cache_dir=Path(args.cache_dir),
        base_url=base_url,
        sleep_seconds=float(args.sleep_seconds),
    )
    open_times = [bar.open_ms for bar in bars]
    atr = _atr(bars)
    round_trip_cost_pct = 2.0 * (max(float(args.fee_bps_per_side), 0.0) + max(float(args.slippage_bps_per_side), 0.0)) / 100.0
    configs = build_configs(args)
    orders_by_done = {
        False: build_orders(labels["events"], include_done=False),
        True: build_orders(labels["events"], include_done=True),
    }

    results: list[dict[str, Any]] = []
    for idx, config in enumerate(configs, start=1):
        result = simulate_config(
            orders=orders_by_done[config.include_done],
            bars=bars,
            open_times=open_times,
            atr=atr,
            config=config,
            round_trip_cost_pct=round_trip_cost_pct,
        )
        results.append(result)
        if idx % 200 == 0:
            print(f"tested {idx}/{len(configs)} configs", flush=True)

    results.sort(
        key=lambda item: (
            item["total_return_pct"],
            item["score"],
            -item["max_drawdown_pct"],
            item["sequential_trades"],
        ),
        reverse=True,
    )
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "labels": str(args.labels),
        "market_data": {
            "symbol": args.symbol,
            "interval": args.interval,
            "rows": len(bars),
            "start": bars[0].ts.isoformat() if bars else None,
            "end": bars[-1].ts.isoformat() if bars else None,
        },
        "round_trip_cost_pct": round(round_trip_cost_pct, 6),
        "orders_plans_only": len(orders_by_done[False]),
        "orders_with_done": len(orders_by_done[True]),
        "tested_configs": len(configs),
        "top_results": results[:30],
        "all_results": results,
    }

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "message_reaction_backtest.json"
    md_path = report_dir / "message_reaction_backtest_summary.md"
    atomic_write_text(json_path, json.dumps(report, ensure_ascii=False, indent=2))
    _write_summary_md(md_path, report)
    if results:
        _write_trades_csv(
            report_dir / "message_reaction_backtest_top_sample_trades.csv",
            results[0]["model_id"],
            results[0]["sample_trades"],
        )
    print(json.dumps({"json": str(json_path), "md": str(md_path), "top_results": results[:5]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
