#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text
from scripts.run_btc_flip_rotation_search import _load_bars, Bar


ACTION_ORDER = {
    "entry_done": 100,
    "entry_plan": 92,
    "victory_zone": 88,
    "add_plan": 84,
    "take_profit_done": 78,
    "reduce_done": 74,
    "switch": 70,
    "stop_plan": 64,
    "wait": 50,
    "bias": 42,
    "risk": 36,
    "education": 20,
}

ENTRY_ACTIONS = {"entry_done", "entry_plan", "victory_zone", "add_plan"}


@dataclass(frozen=True, slots=True)
class MarketContext:
    price: float | None
    bar_ts: str | None
    returns: dict[str, float | None]
    side_returns: dict[str, float | None]
    side_mfe: dict[str, float | None]
    side_mae: dict[str, float | None]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build labeled trade-decision events from the Nanyotti Telegram export.")
    parser.add_argument("--messages", default="reports/research/nanyotti_export/messages.json")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--load-days", type=int, default=1825)
    parser.add_argument("--cache-dir", default="reports/validation/btc_flip_rotation_search/cache")
    parser.add_argument("--report-dir", default="reports/research/nanyotti_export/message_event_dataset")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.03)
    return parser.parse_args()


def _parse_message_date(raw: str) -> datetime:
    return datetime.strptime(raw, "%d.%m.%Y %H:%M:%S UTC%z").astimezone(UTC)


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip(" \t-•·")


def _source_kind(text: str) -> str:
    if "스윙계좌" in text:
        return "account_update"
    if "매매 시나리오" in text or "시나리오" in text:
        return "scenario"
    if "관점 공유" in text or "현시점" in text or "금일" in text:
        return "view"
    if "복기" in text or "하이라이트" in text or "라이브" in text:
        return "review"
    if any(token in text for token in ("자료", "영상", "강의", "설명", "방법")):
        return "education"
    return "message"


def _side_from_text(line: str, inherited: int = 0) -> int:
    long_hit = bool(re.search(r"롱|Long|long|매수|저깨롱|눌림롱|내림롱|돌파 롱|추격 롱", line))
    short_hit = bool(re.search(r"숏|Short|short|매도|고깨숏|빅숏", line))
    if long_hit and not short_hit:
        return 1
    if short_hit and not long_hit:
        return -1
    return inherited


def _is_section_header(line: str) -> int:
    if re.search(r"롱\s*\(|롱\(Long\)|롱\s*포지션\s*전략|🟢|Long\)", line):
        return 1
    if re.search(r"숏\s*\(|숏\(Short\)|숏\s*포지션\s*전략|🔴|Short\)", line):
        return -1
    return 0


def _classify_action(line: str, source_kind: str) -> tuple[str | None, int, list[str]]:
    reasons: list[str] = []
    action: str | None = None
    confidence = 0

    def pick(candidate: str, score: int, reason: str) -> None:
        nonlocal action, confidence
        if score > confidence or (score == confidence and ACTION_ORDER.get(candidate, 0) > ACTION_ORDER.get(action or "", 0)):
            action = candidate
            confidence = score
        reasons.append(reason)

    if re.search(r"진입\s*완료|진입했|진입\s*했습니다|받아보고 있습니다|받고 있습니다|잡았습니다|잡았고|매입했|매입한\s*상태|보유\s*현황", line):
        pick("entry_done", 92, "done_entry_phrase")
    if re.search(r"진입\s*예정|진입\s*할|진입하려|진입 고려|잡아볼|잡는다면|열어두|노려|좋은 타점|매수타점|타점|매입해?\s*볼|매입.*예정", line):
        pick("entry_plan", 86, "planned_entry_phrase")
    if re.search(r"1차\s*(진입|매수|저항)|2차\s*(진입|매수|저항)|3차\s*(진입|매수|저항)|차\s*진입", line):
        pick("entry_plan", 88, "tiered_entry_level")
    if re.search(r"승부\s*구간|승부처|최종\s*승부", line):
        pick("victory_zone", 90, "victory_zone_phrase")
    if re.search(r"불타기|추격|추가\s*진입|분할\s*진입|분할로|물량\s*(확보|조절|줄|늘|태우|싣|덜|정리)", line):
        pick("add_plan", 74, "sizing_or_chase_phrase")
    if re.search(r"익절|수익\s*(실현|챙|냈|내고)|잘\s*먹|빠져나오", line):
        pick("take_profit_done", 84, "take_profit_phrase")
    if re.search(r"덜어|줄이|축소|감축|정리|탈출|빠르게\s*익절|개\s*>", line):
        pick("reduce_done", 72, "reduce_or_exit_phrase")
    if re.search(r"손절|로스|컷|이탈\s*시|깨지면|뚫지 않는다면|실패\s*시", line):
        pick("stop_plan", 70, "stop_or_invalidation_phrase")
    if re.search(r"스위칭|전환|취소하고|반대로|바꿔", line):
        pick("switch", 76, "switch_phrase")
    if re.search(r"관망|무포|쉬거나|진입\s*X|진입하지|비추|하지 않는 것|제외", line):
        pick("wait", 66, "wait_or_no_entry_phrase")
    if re.search(r"우세|유리|관점|추세|모멘텀|강세|하방|상방|바라", line):
        pick("bias", 50, "bias_phrase")
    if re.search(r"청산|고배|레버|배율|풀시드|리스크|생존|조심|유의", line):
        pick("risk", 44, "risk_phrase")
    if source_kind == "education" and action is None:
        pick("education", 25, "education_source")

    return action, confidence, reasons


def _extract_price_levels(line: str) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    seen: set[tuple[float, str]] = set()

    def add(value: float, raw: str, kind: str) -> None:
        if value <= 1_000.0 or value >= 300_000.0:
            return
        key = (round(value, 2), raw)
        if key in seen:
            return
        seen.add(key)
        levels.append({"value": round(value, 2), "raw": raw, "kind": kind})

    for match in re.finditer(r"(?<!\d)(\d{2,3}(?:\.\d+)?)\s*[KkＫ]", line):
        raw = match.group(0)
        add(float(match.group(1)) * 1000.0, raw, "explicit_k")

    for match in re.finditer(r"(?<!\d)(\d{2,3}(?:\.\d+)?)\s*(초반|중초반|초|중반|중|후반|후)", line):
        value = float(match.group(1))
        if value < 200:
            add(value * 1000.0, match.group(0), "korean_bucket")

    context_words = r"진입|저항|지지|구간|부근|타점|까지|아래|이상|초반|중반|후반|돌파|이탈|승부|현재"
    for match in re.finditer(r"(?<![\d.])(\d{2,3}(?:\.\d+)?)(?![\d.])", line):
        raw = match.group(1)
        start, end = match.span()
        window = line[max(0, start - 12) : min(len(line), end + 12)]
        if re.search(context_words, window) and not re.search(r"년|월|일|%|개|배|차|BTC|btc", window):
            value = float(raw)
            if value < 200:
                add(value * 1000.0, raw, "implicit_btc_k")

    return levels


def _line_events(message: dict[str, Any]) -> list[dict[str, Any]]:
    text = str(message.get("text") or "")
    source_kind = _source_kind(text)
    inherited_side = 0
    events: list[dict[str, Any]] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = _clean_line(raw_line)
        if not line:
            continue
        header_side = _is_section_header(line)
        if header_side:
            inherited_side = header_side
        side = _side_from_text(line, inherited_side)
        action, confidence, reasons = _classify_action(line, source_kind)
        price_levels = _extract_price_levels(line)
        if action is None and not price_levels:
            continue
        if action is None:
            action = "price_level"
            confidence = 35
            reasons = ["price_level_only"]
        if action == "education" and source_kind != "education":
            continue
        if confidence < 35:
            continue
        events.append(
            {
                "message_id": message.get("id"),
                "line_no": line_no,
                "date_raw": message.get("date"),
                "source_kind": source_kind,
                "side": "long" if side > 0 else "short" if side < 0 else "neutral",
                "side_value": side,
                "action": action,
                "confidence": confidence,
                "reasons": reasons,
                "price_levels": price_levels,
                "snippet": line,
                "media": message.get("media") or [],
            }
        )
    return events


def _nearest_bar_index(open_times: list[int], ts_ms: int) -> int | None:
    idx = bisect.bisect_right(open_times, ts_ms) - 1
    if idx < 0:
        return None
    return idx


def _market_context(bars: list[Bar], open_times: list[int], ts: datetime, side: int) -> MarketContext:
    idx = _nearest_bar_index(open_times, int(ts.timestamp() * 1000))
    if idx is None or idx >= len(bars):
        return MarketContext(None, None, {}, {}, {}, {})

    price = bars[idx].c
    horizons = {"1h": 12, "4h": 48, "24h": 288, "72h": 864}
    returns: dict[str, float | None] = {}
    side_returns: dict[str, float | None] = {}
    side_mfe: dict[str, float | None] = {}
    side_mae: dict[str, float | None] = {}
    for label, bars_ahead in horizons.items():
        end_idx = idx + bars_ahead
        if end_idx >= len(bars):
            returns[label] = None
            side_returns[label] = None
            side_mfe[label] = None
            side_mae[label] = None
            continue
        future = bars[end_idx].c
        raw_ret = future / price - 1.0
        returns[label] = round(raw_ret * 100.0, 4)
        side_returns[label] = round(raw_ret * side * 100.0, 4) if side else None
        window = bars[idx + 1 : end_idx + 1]
        if not window or side == 0:
            side_mfe[label] = None
            side_mae[label] = None
            continue
        max_high = max(bar.h for bar in window)
        min_low = min(bar.l for bar in window)
        if side > 0:
            side_mfe[label] = round((max_high / price - 1.0) * 100.0, 4)
            side_mae[label] = round((min_low / price - 1.0) * 100.0, 4)
        else:
            side_mfe[label] = round((price / min_low - 1.0) * 100.0, 4)
            side_mae[label] = round((price / max_high - 1.0) * 100.0, 4)

    return MarketContext(
        price=round(price, 2),
        bar_ts=bars[idx].ts.isoformat(),
        returns=returns,
        side_returns=side_returns,
        side_mfe=side_mfe,
        side_mae=side_mae,
    )


def _summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_action = Counter(event["action"] for event in events)
    by_side = Counter(event["side"] for event in events)
    by_source = Counter(event["source_kind"] for event in events)
    executable = [
        event
        for event in events
        if event["action"] in ENTRY_ACTIONS and event["side_value"] != 0 and event["confidence"] >= 70
        and event["source_kind"] in {"scenario", "view", "message"}
    ]
    perf: dict[str, dict[str, Any]] = {}
    for key_fn_name, key_fn in {
        "action_side": lambda e: f"{e['action']}:{e['side']}",
        "source_action_side": lambda e: f"{e['source_kind']}:{e['action']}:{e['side']}",
    }.items():
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in executable:
            grouped[key_fn(event)].append(event)
        perf[key_fn_name] = {}
        for key, rows in sorted(grouped.items()):
            item: dict[str, Any] = {"count": len(rows)}
            for horizon in ("1h", "4h", "24h", "72h"):
                values = [
                    float(row["market"]["side_returns"].get(horizon))
                    for row in rows
                    if row["market"]["side_returns"].get(horizon) is not None
                ]
                if values:
                    item[f"{horizon}_avg_side_return_pct"] = round(mean(values), 4)
                    item[f"{horizon}_median_side_return_pct"] = round(median(values), 4)
                    item[f"{horizon}_win_rate"] = round(sum(value > 0 for value in values) / len(values), 4)
            perf[key_fn_name][key] = item

    return {
        "event_count": len(events),
        "executable_event_count": len(executable),
        "by_action": dict(by_action),
        "by_side": dict(by_side),
        "by_source_kind": dict(by_source),
        "performance": perf,
    }


def _write_csv(path: Path, events: list[dict[str, Any]]) -> None:
    fieldnames = [
        "event_id",
        "message_id",
        "date_utc",
        "date_kst",
        "source_kind",
        "action",
        "side",
        "confidence",
        "market_price",
        "ret_1h_side_pct",
        "ret_4h_side_pct",
        "ret_24h_side_pct",
        "ret_72h_side_pct",
        "mfe_4h_side_pct",
        "mae_4h_side_pct",
        "price_levels",
        "snippet",
        "media",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for event in events:
            market = event["market"]
            writer.writerow(
                {
                    "event_id": event["event_id"],
                    "message_id": event["message_id"],
                    "date_utc": event["date_utc"],
                    "date_kst": event["date_kst"],
                    "source_kind": event["source_kind"],
                    "action": event["action"],
                    "side": event["side"],
                    "confidence": event["confidence"],
                    "market_price": market["price"],
                    "ret_1h_side_pct": market["side_returns"].get("1h"),
                    "ret_4h_side_pct": market["side_returns"].get("4h"),
                    "ret_24h_side_pct": market["side_returns"].get("24h"),
                    "ret_72h_side_pct": market["side_returns"].get("72h"),
                    "mfe_4h_side_pct": market["side_mfe"].get("4h"),
                    "mae_4h_side_pct": market["side_mae"].get("4h"),
                    "price_levels": json.dumps(event["price_levels"], ensure_ascii=False, separators=(",", ":")),
                    "snippet": event["snippet"],
                    "media": ",".join(event["media"]),
                }
            )


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    lines: list[str] = []
    lines.append("# 나뇨띠 메시지 판단 이벤트 데이터셋")
    lines.append("")
    lines.append(f"- 생성 시각: {payload['created_at']}")
    lines.append(f"- 메시지 수: {payload['message_count']}")
    lines.append(f"- 라벨 이벤트 수: {summary['event_count']}")
    lines.append(f"- 실행 후보 이벤트 수: {summary['executable_event_count']}")
    lines.append(f"- 데이터 기간: {payload['date_range']['start']} ~ {payload['date_range']['end']}")
    lines.append("")
    lines.append("## 액션별 개수")
    lines.append("")
    for key, value in sorted(summary["by_action"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## 실행 후보 성과 요약")
    lines.append("")
    lines.append("| 그룹 | 개수 | 1h 평균 | 4h 평균 | 24h 평균 | 4h 승률 | 24h 승률 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for key, item in sorted(summary["performance"]["action_side"].items()):
        lines.append(
            "| "
            + " | ".join(
                [
                    key,
                    str(item.get("count", 0)),
                    str(item.get("1h_avg_side_return_pct", "")),
                    str(item.get("4h_avg_side_return_pct", "")),
                    str(item.get("24h_avg_side_return_pct", "")),
                    str(item.get("4h_win_rate", "")),
                    str(item.get("24h_win_rate", "")),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## 고신뢰 실행 후보 샘플")
    lines.append("")
    samples = [
        event
        for event in payload["events"]
        if event["action"] in ENTRY_ACTIONS and event["side_value"] != 0 and event["confidence"] >= 80
    ][:30]
    for event in samples:
        market = event["market"]
        lines.append(
            f"- `{event['date_kst']}` `{event['action']}` `{event['side']}` "
            f"price={market['price']} 4h={market['side_returns'].get('4h')}% "
            f"24h={market['side_returns'].get('24h')}% | {event['snippet']}"
        )
    lines.append("")
    lines.append("## 주의")
    lines.append("")
    lines.append("이 데이터셋은 메시지 텍스트 기반 라벨이다. 영상/이미지 속 실제 체결 화면 OCR, 방송 중 실시간 발화 시점, 미게시된 포지션 변화는 아직 포함하지 않았다.")
    atomic_write_text(path, "\n".join(lines) + "\n")


def main() -> None:
    args = _parse_args()
    messages_path = Path(args.messages)
    messages = json.loads(messages_path.read_text(encoding="utf-8"))
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

    events: list[dict[str, Any]] = []
    for message in messages:
        msg_ts = _parse_message_date(str(message["date"]))
        for event in _line_events(message):
            side = int(event["side_value"])
            market = _market_context(bars, open_times, msg_ts, side)
            event_id = f"{event['message_id']}:{event['line_no']}:{event['action']}:{event['side']}"
            event["event_id"] = event_id
            event["date_utc"] = msg_ts.isoformat()
            event["date_kst"] = msg_ts.astimezone().isoformat()
            event["market"] = {
                "symbol": args.symbol,
                "interval": args.interval,
                "bar_ts": market.bar_ts,
                "price": market.price,
                "returns": market.returns,
                "side_returns": market.side_returns,
                "side_mfe": market.side_mfe,
                "side_mae": market.side_mae,
            }
            events.append(event)

    events.sort(key=lambda item: (item["date_utc"], item["message_id"], item["line_no"]))
    summary = _summarize(events)
    date_values = [_parse_message_date(str(message["date"])) for message in messages]
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "source_messages": str(messages_path),
        "message_count": len(messages),
        "date_range": {
            "start": min(date_values).isoformat() if date_values else None,
            "end": max(date_values).isoformat() if date_values else None,
        },
        "market_data": {
            "symbol": args.symbol,
            "interval": args.interval,
            "rows": len(bars),
            "start": bars[0].ts.isoformat() if bars else None,
            "end": bars[-1].ts.isoformat() if bars else None,
        },
        "label_rules": {
            "entry_actions": sorted(ENTRY_ACTIONS),
            "note": "Labels are text-derived; future returns are appended only for evaluation.",
        },
        "summary": summary,
        "events": events,
    }

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "message_event_labels.json"
    csv_path = report_dir / "message_event_labels.csv"
    md_path = report_dir / "message_event_labels_summary.md"
    atomic_write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2))
    _write_csv(csv_path, events)
    _write_markdown(md_path, payload)
    print(json.dumps({"summary": summary, "json": str(json_path), "csv": str(csv_path), "md": str(md_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
