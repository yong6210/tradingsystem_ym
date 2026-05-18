#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import CURRENT_MICRO_LIVE_USDT_SYMBOLS, get_settings
from app.services.report_io import atomic_write_text
from app.services.structure_reaction_strategy_research import (
    StructureReactionPolicy,
    StructureReactionResearch,
    build_structure_reaction_policies,
)
from scripts.run_micro_main_exit_policy_search import _csv, _trade_row, summarize_rows
from scripts.run_micro_main_usdt_proxy_backtest import _fetch_1m_klines, _resample_to_5m


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research HTF structure reaction entries with structure-buffered exits.")
    parser.add_argument("--symbols", default=CURRENT_MICRO_LIVE_USDT_SYMBOLS)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--policies", default=",".join(policy.name for policy in build_structure_reaction_policies()))
    parser.add_argument("--report-dir", default="reports/validation/structure_reaction_research")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--include-trades", action="store_true")
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


def _select_policies(names: list[str]) -> list[StructureReactionPolicy]:
    by_name = {policy.name: policy for policy in build_structure_reaction_policies()}
    missing = [name for name in names if name not in by_name]
    if missing:
        raise SystemExit(f"unknown policies: {','.join(missing)}")
    return [by_name[name] for name in names]


def _diagnostic_value(row: dict[str, Any], key: str, default: str = "unknown") -> str:
    value: Any = row.get("diagnostics")
    if not isinstance(value, dict):
        return default
    for part in key.split("."):
        if not isinstance(value, dict):
            return default
        value = value.get(part)
    if value in (None, ""):
        return default
    return str(value)


def _grouped_summaries(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if key.startswith("diagnostics."):
            group = _diagnostic_value(row, key.split(".", 1)[1])
        else:
            value = row.get(key)
            group = str(value) if value not in (None, "") else "unknown"
        grouped.setdefault(group, []).append(row)
    summaries = {name: summarize_rows(items) for name, items in grouped.items()}
    return dict(
        sorted(
            summaries.items(),
            key=lambda item: float(item[1].get("total_r", 0.0) or 0.0),
            reverse=True,
        )
    )


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
            if len(candles_1m) < 1500 or len(candles_5m) < 300:
                print(
                    json.dumps({"symbol": symbol, "status": "insufficient_candles", **data_status[symbol]}),
                    file=sys.stderr,
                    flush=True,
                )
                continue
            for policy in policies:
                engine = StructureReactionResearch(
                    symbol=symbol,
                    candles_1m=candles_1m,
                    candles_5m=candles_5m,
                    policy=policy,
                )
                trades = engine.backtest()
                rows_by_policy[policy.name].extend(_trade_row(trade, policy=policy.exit_policy()) for trade in trades)
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
                "by_anchor_timeframe": _grouped_summaries(rows, "diagnostics.htf_structure_anchor.timeframe"),
                "by_anchor_kind": _grouped_summaries(rows, "diagnostics.htf_structure_anchor_kind"),
            },
        }
        if args.include_trades:
            item["trades"] = rows
        results.append(item)
    results.sort(key=lambda item: float(item["summary"].get("score", 0.0) or 0.0), reverse=True)
    output = {
        "schema_version": "structure_reaction_research_v1",
        "generated_at": generated_at.isoformat(),
        "scope": {
            "symbols": symbols,
            "days": int(args.days),
            "start_ts": start_ts.isoformat(),
            "end_ts": end_ts.isoformat(),
            "entry_timing_model": "after_completed_5m_reaction_next_1m_open",
            "notes": [
                "Research-only. This does not enable live entries.",
                "HTF structure anchors use only completed 1d/4h/5m data before the setup candle.",
                "Entry is the next 1m open after the completed 5m reaction candle.",
                "SL is placed beyond the touched structure/sweep with an ATR buffer.",
                "TPs are selected before opposite structure targets with an ATR buffer.",
            ],
        },
        "data_status": data_status,
        "results": results,
    }
    if args.write_report:
        out_dir = ROOT_DIR / str(args.report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"structure_reaction_research_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        atomic_write_text(out_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))
        output["report_path"] = str(out_path.relative_to(ROOT_DIR))
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
