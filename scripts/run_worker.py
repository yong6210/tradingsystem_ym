#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.session import SessionLocal, init_db
from app.services.strategy_engine import StrategyEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trading Engine background worker")
    parser.add_argument("--mode", choices=["once", "loop"], default="once")
    parser.add_argument("--interval-seconds", type=int, default=60)

    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--sync-universe", action="store_true")
    parser.add_argument("--limit-symbols", type=int, default=30)
    parser.add_argument("--symbol-concurrency", type=int, default=1)
    parser.add_argument("--limit-5m", type=int, default=500)
    parser.add_argument("--limit-15m", type=int, default=500)

    parser.add_argument("--binance-sync", action="store_true")
    parser.add_argument("--ws-stream", action="store_true")
    parser.add_argument("--ws-symbols", default="", help="Comma separated symbols. Empty -> use --symbol or universe.")
    parser.add_argument("--ws-intervals", default="5m,15m", help="Comma separated intervals from [5m,15m].")
    parser.add_argument("--ws-max-messages", type=int, default=0, help="0 means infinite stream.")
    parser.add_argument("--ws-refresh-on-final", dest="ws_refresh_on_final", action="store_true", default=True)
    parser.add_argument("--ws-no-refresh-on-final", dest="ws_refresh_on_final", action="store_false")
    parser.add_argument("--reprocess-events", action="store_true")
    parser.add_argument("--validate", action="store_true")
    return parser.parse_args()


def _parse_csv(raw: str) -> list[str]:
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def run_once(args: argparse.Namespace) -> dict:
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        result: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "actions": [],
        }

        if args.sync_universe:
            payload = engine.sync_universe_from_binance(
                limit_symbols=args.limit_symbols,
                limit_5m=args.limit_5m,
                limit_15m=args.limit_15m,
                symbol_concurrency=args.symbol_concurrency,
            )
            result["actions"].append({"sync_universe": payload})
        elif args.binance_sync:
            payload = engine.sync_symbol_from_binance(
                symbol=args.symbol,
                limit_5m=args.limit_5m,
                limit_15m=args.limit_15m,
            )
            result["actions"].append({"sync_symbol": payload})
        else:
            payload = engine.refresh_symbol(args.symbol)
            result["actions"].append({"refresh_symbol": payload})

        if args.reprocess_events:
            payload = engine.reprocess_events(limit=200)
            result["actions"].append({"reprocess_events": payload})

        if args.validate:
            payload = engine.recompute_learning(args.symbol)
            result["actions"].append({"validation": payload})

        result["outbox"] = engine.outbox_status()
        return result


def run_ws_stream(args: argparse.Namespace) -> dict:
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        symbols = _parse_csv(args.ws_symbols)
        if not symbols:
            if args.sync_universe:
                symbols = engine.market_data.refresh_universe(limit=args.limit_symbols)
            else:
                symbols = [args.symbol.upper()]

        intervals = [iv for iv in _parse_csv(args.ws_intervals.lower()) if iv in {"5M", "15M", "5m", "15m"}]
        intervals = [iv.lower() for iv in intervals]
        if not intervals:
            intervals = ["5m", "15m"]

        max_messages = args.ws_max_messages if args.ws_max_messages > 0 else None
        payload = asyncio.run(
            engine.stream_binance_klines(
                symbols=symbols,
                intervals=intervals,
                refresh_on_final=args.ws_refresh_on_final,
                max_messages=max_messages,
            )
        )
        payload["ts"] = datetime.now(timezone.utc).isoformat()
        payload["outbox"] = engine.outbox_status()
        return payload


def main() -> int:
    args = parse_args()
    init_db()

    if args.ws_stream:
        payload = run_ws_stream(args)
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.mode == "once":
        payload = run_once(args)
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0

    while True:
        started = time.time()
        try:
            payload = run_once(args)
            print(json.dumps(payload, ensure_ascii=False, default=str))
        except Exception as exc:
            error_payload = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            }
            print(json.dumps(error_payload, ensure_ascii=False))

        elapsed = time.time() - started
        wait = max(1, args.interval_seconds - int(elapsed))
        time.sleep(wait)


if __name__ == "__main__":
    raise SystemExit(main())
