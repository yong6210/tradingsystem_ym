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
from app.services.runtime_worker_heartbeat import write_worker_heartbeat
from app.services.strategy_engine import StrategyEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trading Engine background worker")
    parser.add_argument("--mode", choices=["once", "loop"], default="once")
    parser.add_argument("--interval-seconds", type=int, default=60)

    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--sync-universe", action="store_true")
    parser.add_argument("--limit-symbols", type=int, default=30)
    parser.add_argument("--symbol-concurrency", type=int, default=1)
    parser.add_argument("--limit-1m", type=int, default=120)
    parser.add_argument("--limit-5m", type=int, default=500)
    parser.add_argument("--limit-15m", type=int, default=500)

    parser.add_argument("--binance-sync", action="store_true")
    parser.add_argument("--ws-stream", action="store_true")
    parser.add_argument("--ws-symbols", default="", help="Comma separated symbols. Empty -> use --symbol or universe.")
    parser.add_argument("--ws-intervals", default="1m,5m,15m", help="Comma separated intervals from [1m,5m,15m].")
    parser.add_argument("--ws-max-messages", type=int, default=0, help="0 means infinite stream.")
    parser.add_argument("--ws-refresh-on-final", dest="ws_refresh_on_final", action="store_true", default=True)
    parser.add_argument("--ws-no-refresh-on-final", dest="ws_refresh_on_final", action="store_false")
    parser.add_argument("--reprocess-events", action="store_true")
    parser.add_argument("--validate", action="store_true")
    return parser.parse_args()


def _parse_csv(raw: str) -> list[str]:
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def _worker_role(args: argparse.Namespace) -> str:
    if bool(args.ws_stream):
        return "ws"
    if str(args.mode) == "loop":
        return "loop"
    return "once"


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
                limit_1m=args.limit_1m,
                limit_5m=args.limit_5m,
                limit_15m=args.limit_15m,
                symbol_concurrency=args.symbol_concurrency,
            )
            result["actions"].append({"sync_universe": payload})
        elif args.binance_sync:
            payload = engine.sync_symbol_from_binance(
                symbol=args.symbol,
                limit_1m=args.limit_1m,
                limit_5m=args.limit_5m,
                limit_15m=args.limit_15m,
            )
            result["actions"].append({"sync_symbol": payload})
        else:
            payload = engine.refresh_symbol(args.symbol)
            route_payload = engine.auto_route_symbol(symbol=args.symbol)
            result["actions"].append({"refresh_symbol": payload, "auto_route": route_payload})

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
                symbols = engine.runtime_sync_symbols(limit_symbols=args.limit_symbols)
            else:
                symbols = [args.symbol.upper()]

        intervals = [iv for iv in _parse_csv(args.ws_intervals.lower()) if iv in {"1M", "5M", "15M", "1m", "5m", "15m"}]
        intervals = [iv.lower() for iv in intervals]
        if not intervals:
            intervals = ["1m", "5m", "15m"]

        max_messages = args.ws_max_messages if args.ws_max_messages > 0 else None
        last_heartbeat_at = 0.0
        ws_started_at = datetime.now(timezone.utc).isoformat()
        latest_stats: dict = {
            "started_at": ws_started_at,
            "processed_messages": 0,
            "refresh_calls": 0,
            "auto_route_calls": 0,
            "auto_route_submit_calls": 0,
            "skipped_reverse_timestamp": 0,
        }

        def _write_ws_heartbeat(stats: dict, *, phase: str = "streaming") -> None:
            write_worker_heartbeat(
                "ws",
                status="ok",
                details={
                    "phase": phase,
                    "started_at": str(stats.get("started_at") or ws_started_at),
                    "symbols": symbols,
                    "intervals": intervals,
                    "processed_messages": int(stats.get("processed_messages", 0) or 0),
                    "refresh_calls": int(stats.get("refresh_calls", 0) or 0),
                    "auto_route_calls": int(stats.get("auto_route_calls", 0) or 0),
                    "auto_route_submit_calls": int(stats.get("auto_route_submit_calls", 0) or 0),
                    "reconnects": int(stats.get("reconnects", 0) or 0),
                    "ingest_errors": int(stats.get("ingest_errors", 0) or 0),
                    "skipped_reverse_timestamp": int(stats.get("skipped_reverse_timestamp", 0) or 0),
                    "refresh_errors": int(stats.get("refresh_errors", 0) or 0),
                    "auto_route_errors": int(stats.get("auto_route_errors", 0) or 0),
                    "last_ingest_error": str(stats.get("last_ingest_error") or ""),
                    "last_refresh_error": str(stats.get("last_refresh_error") or ""),
                    "last_auto_route_error": str(stats.get("last_auto_route_error") or ""),
                    "last_stream_error": str(stats.get("last_stream_error") or ""),
                },
            )

        def _heartbeat(stats: dict) -> None:
            nonlocal last_heartbeat_at
            latest_stats.update(stats)
            now_mono = time.monotonic()
            if now_mono - last_heartbeat_at < 5.0:
                return
            last_heartbeat_at = now_mono
            _write_ws_heartbeat(latest_stats)

        async def _heartbeat_watchdog() -> None:
            while True:
                _write_ws_heartbeat(latest_stats, phase="streaming_watchdog")
                await asyncio.sleep(15.0)

        async def _run_stream_with_heartbeat() -> dict:
            watchdog_task = asyncio.create_task(_heartbeat_watchdog())
            try:
                return await engine.stream_binance_klines(
                    symbols=symbols,
                    intervals=intervals,
                    refresh_on_final=args.ws_refresh_on_final,
                    max_messages=max_messages,
                    progress_callback=_heartbeat,
                )
            finally:
                watchdog_task.cancel()
                await asyncio.gather(watchdog_task, return_exceptions=True)

        write_worker_heartbeat(
            "ws",
            status="ok",
            details={"phase": "starting", "started_at": ws_started_at, "symbols": symbols, "intervals": intervals},
        )
        payload = asyncio.run(_run_stream_with_heartbeat())
        write_worker_heartbeat(
            "ws",
            status="ok",
            details={
                "processed_messages": int(payload.get("processed_messages", 0) or 0),
                "refresh_calls": int(payload.get("refresh_calls", 0) or 0),
                "auto_route_calls": int(payload.get("auto_route_calls", 0) or 0),
                "auto_route_submit_calls": int(payload.get("auto_route_submit_calls", 0) or 0),
            },
        )
        payload["ts"] = datetime.now(timezone.utc).isoformat()
        payload["outbox"] = engine.outbox_status()
        return payload


def main() -> int:
    args = parse_args()
    init_db()
    role = _worker_role(args)

    if args.ws_stream:
        payload = run_ws_stream(args)
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str), flush=True)
        return 0

    if args.mode == "once":
        payload = run_once(args)
        if role == "loop":
            write_worker_heartbeat("loop", status="ok", details={"actions": [list(item.keys())[0] for item in payload.get("actions", [])]})
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str), flush=True)
        return 0

    write_worker_heartbeat(
        "loop",
        status="ok",
        details={"phase": "starting", "interval_seconds": int(args.interval_seconds)},
    )
    while True:
        started = time.time()
        try:
            payload = run_once(args)
            write_worker_heartbeat(
                "loop",
                status="ok",
                details={
                    "actions": [list(item.keys())[0] for item in payload.get("actions", [])],
                    "outbox": payload.get("outbox", {}),
                },
            )
            print(json.dumps(payload, ensure_ascii=False, default=str), flush=True)
        except Exception as exc:
            write_worker_heartbeat("loop", status="error", details={"error": str(exc)})
            error_payload = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            }
            print(json.dumps(error_payload, ensure_ascii=False), flush=True)

        elapsed = time.time() - started
        wait = max(1, args.interval_seconds - int(elapsed))
        time.sleep(wait)


if __name__ == "__main__":
    raise SystemExit(main())
