#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
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


ENTRY_ACTIONS = {"entry_plan", "victory_zone", "add_plan", "entry_done"}
STRICT_SOURCE_KINDS = {"scenario", "view", "message"}
BAD_SNIPPET_TOKENS = (
    "진입 X",
    "진입하지",
    "비추",
    "제외",
    "승부구간이 없음",
    "좋아보이지 않",
    "신규 롱 진입보다는",
    "무리하게",
)


@dataclass(frozen=True, slots=True)
class LevelBacktestConfig:
    model_id: str
    validity_hours: int
    hold_hours: int
    tp_pct: float
    sl_pct: float
    account_exposure: float
    include_done: bool


@dataclass(frozen=True, slots=True)
class Order:
    order_id: str
    event_id: str
    message_id: str
    created_ts: datetime
    side: int
    action: str
    source_kind: str
    snippet: str
    reference_price: float
    entry_level: float | None
    is_current_entry: bool


@dataclass(frozen=True, slots=True)
class Trade:
    order_id: str
    event_id: str
    message_id: str
    side: int
    action: str
    source_kind: str
    created_ts: datetime
    entry_ts: datetime
    exit_ts: datetime
    entry: float
    exit: float
    gross_return_pct: float
    net_return_pct: float
    exit_reason: str
    hold_bars: int
    snippet: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest message-derived price-level plans as limit-order events.")
    parser.add_argument("--labels", default="reports/research/nanyotti_export/message_event_dataset/message_event_labels.json")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--load-days", type=int, default=1825)
    parser.add_argument("--validity-hours", default="24,72,168")
    parser.add_argument("--hold-hours", default="4,12,24,72")
    parser.add_argument("--tp-pcts", default="0.3,0.6,1.0,1.5")
    parser.add_argument("--sl-pcts", default="0.4,0.8,1.2,2.0")
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
        if value > 0.0:
            out.append(value)
    return out or fallback


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


def _event_allowed(event: dict[str, Any], *, include_done: bool) -> bool:
    if event.get("source_kind") not in STRICT_SOURCE_KINDS:
        return False
    if event.get("action") not in ENTRY_ACTIONS:
        return False
    if event.get("action") == "entry_done" and not include_done:
        return False
    if int(event.get("side_value") or 0) == 0:
        return False
    if int(event.get("confidence") or 0) < 70:
        return False
    snippet = str(event.get("snippet") or "")
    return not any(token in snippet for token in BAD_SNIPPET_TOKENS)


def _entry_level_from_event(event: dict[str, Any]) -> tuple[float | None, bool]:
    side = int(event["side_value"])
    reference = event.get("market", {}).get("price")
    levels = [float(item["value"]) for item in event.get("price_levels") or [] if item.get("value")]
    levels = sorted(set(level for level in levels if 1_000.0 < level < 300_000.0))
    snippet = str(event.get("snippet") or "")
    if reference is None:
        return None, True

    ref = float(reference)
    if not levels:
        immediate_tokens = (
            "현재부터",
            "현재 구간",
            "현재 포지",
            "현재도",
            "지금",
            "이미",
            "진입했습니다",
            "잡았습니다",
            "받고 있습니다",
            "받아보고 있습니다",
            "돌파, 추격",
            "추격 롱",
            "불타기",
        )
        if event.get("action") == "entry_done" or any(token in snippet for token in immediate_tokens):
            return None, True
        return None, False

    if len(levels) >= 2 and max(levels) / min(levels) <= 1.04:
        level = sum(levels) / len(levels)
    else:
        if side > 0:
            candidates = [level for level in levels if level <= ref * 1.01]
            if not candidates and any(token in snippet for token in ("돌파", "추격", "불타기", "현재")):
                candidates = levels
            if not candidates:
                return None, False
            level = max(candidates)
        else:
            candidates = [level for level in levels if level >= ref * 0.99]
            if not candidates and any(token in snippet for token in ("돌파", "추격", "불타기", "현재")):
                candidates = levels
            if not candidates:
                return None, False
            level = min(candidates)
    return float(level), False


def build_orders(events: list[dict[str, Any]], *, include_done: bool) -> list[Order]:
    orders: list[Order] = []
    for event in events:
        if not _event_allowed(event, include_done=include_done):
            continue
        created_ts = datetime.fromisoformat(str(event["date_utc"]))
        if created_ts.tzinfo is None:
            created_ts = created_ts.replace(tzinfo=UTC)
        level, is_current = _entry_level_from_event(event)
        if level is None and not is_current:
            continue
        reference = event.get("market", {}).get("price")
        if reference is None:
            continue
        side = int(event["side_value"])
        orders.append(
            Order(
                order_id=f"{event['event_id']}:{'now' if is_current else round(level or 0, 2)}",
                event_id=str(event["event_id"]),
                message_id=str(event["message_id"]),
                created_ts=created_ts.astimezone(UTC),
                side=side,
                action=str(event["action"]),
                source_kind=str(event["source_kind"]),
                snippet=str(event["snippet"]),
                reference_price=float(reference),
                entry_level=level,
                is_current_entry=is_current,
            )
        )
    orders.sort(key=lambda order: (order.created_ts, order.order_id))
    return orders


def _fill_order(order: Order, bars: list[Bar], open_times: list[int], config: LevelBacktestConfig) -> tuple[int, float] | None:
    start_idx = _bar_index(open_times, order.created_ts)
    if start_idx is None:
        return None
    if order.is_current_entry:
        idx = min(start_idx + 1, len(bars) - 1)
        return idx, bars[idx].o

    deadline = order.created_ts + timedelta(hours=config.validity_hours)
    end_idx = bisect.bisect_right(open_times, int(deadline.timestamp() * 1000))
    entry_level = float(order.entry_level or 0.0)
    for idx in range(start_idx + 1, min(end_idx, len(bars))):
        bar = bars[idx]
        if order.side > 0 and bar.l <= entry_level:
            return idx, entry_level
        if order.side < 0 and bar.h >= entry_level:
            return idx, entry_level
    return None


def _exit_trade(
    order: Order,
    bars: list[Bar],
    entry_idx: int,
    entry_price: float,
    config: LevelBacktestConfig,
    round_trip_cost_pct: float,
) -> Trade:
    max_bars = max(int(config.hold_hours * 60 / 5), 1)
    end_idx = min(entry_idx + max_bars, len(bars) - 1)
    side = order.side
    if side > 0:
        tp = entry_price * (1.0 + config.tp_pct / 100.0)
        sl = entry_price * (1.0 - config.sl_pct / 100.0)
    else:
        tp = entry_price * (1.0 - config.tp_pct / 100.0)
        sl = entry_price * (1.0 + config.sl_pct / 100.0)

    exit_idx = end_idx
    exit_price = bars[end_idx].c
    exit_reason = "time_exit"
    for idx in range(entry_idx + 1, end_idx + 1):
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
        entry_ts=bars[entry_idx].ts,
        exit_ts=bars[exit_idx].ts,
        entry=entry_price,
        exit=exit_price,
        gross_return_pct=round(gross, 6),
        net_return_pct=round(net, 6),
        exit_reason=exit_reason,
        hold_bars=exit_idx - entry_idx,
        snippet=order.snippet,
    )


def simulate_config(
    *,
    orders: list[Order],
    bars: list[Bar],
    open_times: list[int],
    config: LevelBacktestConfig,
    round_trip_cost_pct: float,
) -> dict[str, Any]:
    all_trades: list[Trade] = []
    filled_order_ids: set[str] = set()
    for order in orders:
        fill = _fill_order(order, bars, open_times, config)
        if fill is None:
            continue
        entry_idx, entry_price = fill
        trade = _exit_trade(order, bars, entry_idx, entry_price, config, round_trip_cost_pct)
        all_trades.append(trade)
        filled_order_ids.add(order.order_id)

    all_trades.sort(key=lambda trade: (trade.entry_ts, trade.order_id))
    sequential: list[Trade] = []
    busy_until: datetime | None = None
    for trade in all_trades:
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

    values = [trade.net_return_pct for trade in all_trades]
    seq_values = [trade.net_return_pct for trade in sequential]
    doubled = 0
    for value in monthly.values():
        start = value["start"]
        if start > 0 and value["end"] / start - 1.0 >= 1.0:
            doubled += 1

    result = {
        "model_id": config.model_id,
        "validity_hours": config.validity_hours,
        "hold_hours": config.hold_hours,
        "tp_pct": config.tp_pct,
        "sl_pct": config.sl_pct,
        "account_exposure": config.account_exposure,
        "include_done": config.include_done,
        "orders": len(orders),
        "filled_orders": len(all_trades),
        "fill_rate": round(len(all_trades) / len(orders), 6) if orders else 0.0,
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
        "exit_reasons": {},
        "score": 0.0,
        "sample_trades": [],
    }
    reason_counts: dict[str, int] = {}
    for trade in all_trades:
        reason_counts[trade.exit_reason] = reason_counts.get(trade.exit_reason, 0) + 1
    result["exit_reasons"] = reason_counts
    result["score"] = round((equity - 1.0) - 1.25 * max_dd, 6)
    result["sample_trades"] = [_trade_to_dict(trade) for trade in sequential[:10] + sequential[-10:] if sequential]
    return result


def _trade_to_dict(trade: Trade) -> dict[str, Any]:
    return {
        "order_id": trade.order_id,
        "message_id": trade.message_id,
        "side": _side_label(trade.side),
        "action": trade.action,
        "source_kind": trade.source_kind,
        "created_ts": trade.created_ts.isoformat(),
        "entry_ts": trade.entry_ts.isoformat(),
        "exit_ts": trade.exit_ts.isoformat(),
        "entry": round(trade.entry, 2),
        "exit": round(trade.exit, 2),
        "gross_return_pct": trade.gross_return_pct,
        "net_return_pct": trade.net_return_pct,
        "exit_reason": trade.exit_reason,
        "hold_bars": trade.hold_bars,
        "snippet": trade.snippet,
    }


def build_configs(args: argparse.Namespace) -> list[LevelBacktestConfig]:
    configs: list[LevelBacktestConfig] = []
    for include_done in (False, True):
        for validity in _parse_int_csv(args.validity_hours, [24, 72, 168]):
            for hold in _parse_int_csv(args.hold_hours, [4, 12, 24, 72]):
                for tp in _parse_float_csv(args.tp_pcts, [0.3, 0.6, 1.0]):
                    for sl in _parse_float_csv(args.sl_pcts, [0.4, 0.8, 1.2]):
                        for exposure in _parse_float_csv(args.account_exposures, [1.0, 2.0, 3.0]):
                            configs.append(
                                LevelBacktestConfig(
                                    model_id=(
                                        f"msg_level:valid{validity}h:hold{hold}h:"
                                        f"tp{tp:g}:sl{sl:g}:gross{exposure:g}:"
                                        f"{'withDone' if include_done else 'plansOnly'}"
                                    ),
                                    validity_hours=validity,
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


def _write_trades_csv(path: Path, trades: list[dict[str, Any]]) -> None:
    fields = [
        "model_id",
        "message_id",
        "side",
        "action",
        "source_kind",
        "created_ts",
        "entry_ts",
        "exit_ts",
        "entry",
        "exit",
        "net_return_pct",
        "exit_reason",
        "snippet",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for trade in trades:
            writer.writerow({field: trade.get(field) for field in fields})


def _write_summary_md(path: Path, report: dict[str, Any]) -> None:
    lines: list[str] = []
    top = report["top_results"][0] if report["top_results"] else {}
    lines.append("# 메시지 가격대 라벨 백테스트")
    lines.append("")
    lines.append(f"- 생성 시각: {report['created_at']}")
    lines.append(f"- 주문 후보: {report['orders_plans_only']}개(plans only), {report['orders_with_done']}개(with done)")
    lines.append(f"- 테스트 조합: {report['tested_configs']}개")
    lines.append(f"- 최고 조합: `{top.get('model_id', '')}`")
    lines.append(f"- 최고 조합 총수익: {top.get('total_return_pct', '')}%")
    lines.append(f"- 최고 조합 MDD: {top.get('max_drawdown_pct', '')}%")
    lines.append(f"- 최고 조합 순차 거래 수: {top.get('sequential_trades', '')}")
    lines.append(f"- 월 2배 달성 월 수: {top.get('months_doubled', '')}")
    lines.append("")
    lines.append("## 상위 10개")
    lines.append("")
    lines.append("| 순위 | 모델 | 총수익 | MDD | 거래수 | 승률 | 체결률 |")
    lines.append("|---:|---|---:|---:|---:|---:|---:|")
    for idx, result in enumerate(report["top_results"][:10], start=1):
        lines.append(
            f"| {idx} | `{result['model_id']}` | {result['total_return_pct']} | "
            f"{result['max_drawdown_pct']} | {result['sequential_trades']} | "
            f"{result['sequential_win_rate']} | {result['fill_rate']} |"
        )
    lines.append("")
    lines.append("## 해석")
    lines.append("")
    lines.append("이 백테스트는 메시지의 가격 구간을 limit order처럼 취급한다. 유효시간 안에 가격이 닿지 않으면 거래하지 않는다. 같은 봉 안에서 TP와 SL이 모두 닿으면 보수적으로 SL을 먼저 처리한다.")
    lines.append("")
    lines.append("이 결과가 양수여도 아직 실전 전략은 아니다. 메시지는 시황 설명과 교육 문장이 섞여 있고, 실제 방송 중 체결/감축 시점은 완전히 포함되어 있지 않다.")
    atomic_write_text(path, "\n".join(lines) + "\n")


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
    configs = build_configs(args)
    round_trip_cost_pct = 2.0 * (max(float(args.fee_bps_per_side), 0.0) + max(float(args.slippage_bps_per_side), 0.0)) / 100.0

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
            config=config,
            round_trip_cost_pct=round_trip_cost_pct,
        )
        results.append(result)
        if idx % 50 == 0:
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
    json_path = report_dir / "message_level_backtest.json"
    md_path = report_dir / "message_level_backtest_summary.md"
    atomic_write_text(json_path, json.dumps(report, ensure_ascii=False, indent=2))
    _write_summary_md(md_path, report)
    if results:
        trades = []
        for trade in results[0]["sample_trades"]:
            item = dict(trade)
            item["model_id"] = results[0]["model_id"]
            trades.append(item)
        _write_trades_csv(report_dir / "message_level_backtest_top_sample_trades.csv", trades)
    print(json.dumps({"json": str(json_path), "md": str(md_path), "top_results": results[:5]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
