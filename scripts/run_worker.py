#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
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
    parser.add_argument("--skip-boot-check", action="store_true", help="Bypass MICRO_LIVE/LIVE boot check before worker start.")
    parser.add_argument("--boot-check-days", type=int, default=3)
    parser.add_argument("--boot-check-limit", type=int, default=200)
    parser.add_argument("--boot-check-binance-rules", action="store_true")
    parser.add_argument("--boot-check-canary-network", action="store_true")
    parser.add_argument("--reprocess-events", action="store_true")
    parser.add_argument("--validate", action="store_true")
    return parser.parse_args()


def _parse_csv(raw: str) -> list[str]:
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return int(default)


def _top_counts(counter: Counter[str], *, limit: int = 8) -> dict[str, int]:
    return {key: int(value) for key, value in counter.most_common(limit)}


def _compact_sync_universe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    results = [dict(item) for item in list(payload.get("results") or []) if isinstance(item, dict)]
    route_reasons: Counter[str] = Counter()
    sir_states: Counter[str] = Counter()
    worker_statuses: Counter[str] = Counter()
    submit_calls = 0
    intents_created = 0
    sir_generated = 0
    signal_alerts = 0

    for row in results:
        worker_statuses[str(row.get("status") or "unknown")] += 1
        refresh = dict(row.get("refresh") or {})
        auto_route = dict(row.get("auto_route") or {})
        route_reasons[str(auto_route.get("reason") or "none")] += 1
        sir_states[str(refresh.get("session_impulse_retest_generation_state") or refresh.get("legacy_plan_generation_state") or "unknown")] += 1
        submit_calls += _safe_int(auto_route.get("submit_calls"))
        intents_created += _safe_int(auto_route.get("intents_created"))
        sir_generated += _safe_int(refresh.get("session_impulse_retest_generated_count"))
        signal_alerts += _safe_int(dict(refresh.get("signal_alerts") or {}).get("emitted_total"))

    miss = dict(payload.get("session_impulse_retest_miss_detector") or {})
    miss_summary = {
        "enabled": bool(miss.get("enabled")),
        "expected_trade_count": _safe_int(miss.get("expected_trade_count")),
        "runtime_observed_count": _safe_int(miss.get("runtime_observed_count")),
        "miss_count": _safe_int(miss.get("miss_count")),
        "runtime_started_at": miss.get("runtime_started_at"),
    }
    return {
        "universe": payload.get("universe"),
        "requested_symbols": _safe_int(payload.get("requested_symbols")),
        "processed_symbols": _safe_int(payload.get("processed_symbols")),
        "success": _safe_int(payload.get("success")),
        "failed": _safe_int(payload.get("failed")),
        "result_count": len(results),
        "worker_status_counts": _top_counts(worker_statuses),
        "session_impulse_retest_generated_count": sir_generated,
        "session_impulse_retest_generation_state_counts": _top_counts(sir_states),
        "signal_alerts_emitted": signal_alerts,
        "auto_route_submit_calls": submit_calls,
        "auto_route_intents_created": intents_created,
        "auto_route_reason_counts": _top_counts(route_reasons),
        "session_impulse_retest_miss_detector": miss_summary,
    }


def _compact_worker_log_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "ts": payload.get("ts"),
        "actions": [],
        "outbox": payload.get("outbox", {}),
    }
    for action in list(payload.get("actions") or []):
        if not isinstance(action, dict):
            continue
        if "sync_universe" in action and isinstance(action["sync_universe"], dict):
            compact["actions"].append({"sync_universe": _compact_sync_universe_payload(action["sync_universe"])})
            continue
        action_name = next(iter(action.keys()), "action")
        action_payload = action.get(action_name)
        if isinstance(action_payload, dict):
            compact["actions"].append(
                {
                    action_name: {
                        "symbol": action_payload.get("symbol"),
                        "status": action_payload.get("status"),
                        "reason": action_payload.get("reason"),
                        "updated": action_payload.get("updated"),
                    }
                }
            )
        else:
            compact["actions"].append({action_name: str(action_payload)})
    return compact


def _worker_role(args: argparse.Namespace) -> str:
    if bool(args.ws_stream):
        return "ws"
    if str(args.mode) == "loop":
        return "loop"
    return "once"


def _live_mode_requires_boot_check() -> bool:
    settings = get_settings()
    return str(getattr(settings, "auto_trading_execution_mode", "") or "").strip().upper() in {"MICRO_LIVE", "LIVE"}


def _run_boot_check(args: argparse.Namespace) -> dict:
    from scripts import run_micro_live_boot_check

    payload = run_micro_live_boot_check.build_payload(
        days=max(1, int(args.boot_check_days)),
        limit=max(1, int(args.boot_check_limit)),
        symbol=str(args.symbol or ""),
        check_binance_rules=bool(args.boot_check_binance_rules),
        canary_network=bool(args.boot_check_canary_network),
    )
    if str(payload.get("overall_status") or "").upper() != "PASS":
        role = _worker_role(args)
        if role in {"loop", "ws"}:
            write_worker_heartbeat(
                role,
                status="error",
                details={
                    "phase": "boot_check_failed",
                    "overall_status": payload.get("overall_status"),
                    "blocking_failure_count": payload.get("blocking_failure_count"),
                    "next_actions": list(payload.get("next_actions") or []),
                },
            )
    return payload


def run_once(args: argparse.Namespace, *, progress_callback: Any | None = None) -> dict:
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
                progress_callback=progress_callback,
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
            "skipped_non_final_candles": 0,
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
                    "processed_messages": _safe_int(stats.get("processed_messages")),
                    "refresh_calls": _safe_int(stats.get("refresh_calls")),
                    "auto_route_calls": _safe_int(stats.get("auto_route_calls")),
                    "auto_route_submit_calls": _safe_int(stats.get("auto_route_submit_calls")),
                    "reconnects": _safe_int(stats.get("reconnects")),
                    "ingest_errors": _safe_int(stats.get("ingest_errors")),
                    "skipped_non_final_candles": _safe_int(stats.get("skipped_non_final_candles")),
                    "skipped_reverse_timestamp": _safe_int(stats.get("skipped_reverse_timestamp")),
                    "refresh_errors": _safe_int(stats.get("refresh_errors")),
                    "auto_route_errors": _safe_int(stats.get("auto_route_errors")),
                    "progress_callback_errors": _safe_int(stats.get("progress_callback_errors")),
                    "last_ingest_error": str(stats.get("last_ingest_error") or ""),
                    "last_refresh_error": str(stats.get("last_refresh_error") or ""),
                    "last_auto_route_error": str(stats.get("last_auto_route_error") or ""),
                    "last_progress_callback_error": str(stats.get("last_progress_callback_error") or ""),
                    "last_ingest_success_at": str(stats.get("last_ingest_success_at") or ""),
                    "last_ingest_error_at": str(stats.get("last_ingest_error_at") or ""),
                    "last_refresh_success_at": str(stats.get("last_refresh_success_at") or ""),
                    "last_refresh_error_at": str(stats.get("last_refresh_error_at") or ""),
                    "last_auto_route_success_at": str(stats.get("last_auto_route_success_at") or ""),
                    "last_auto_route_error_at": str(stats.get("last_auto_route_error_at") or ""),
                    "last_progress_callback_success_at": str(stats.get("last_progress_callback_success_at") or ""),
                    "last_progress_callback_error_at": str(stats.get("last_progress_callback_error_at") or ""),
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
                "phase": "completed",
                "started_at": ws_started_at,
                "symbols": symbols,
                "intervals": intervals,
                "processed_messages": _safe_int(payload.get("processed_messages")),
                "refresh_calls": _safe_int(payload.get("refresh_calls")),
                "auto_route_calls": _safe_int(payload.get("auto_route_calls")),
                "auto_route_submit_calls": _safe_int(payload.get("auto_route_submit_calls")),
                "reconnects": _safe_int(payload.get("reconnects")),
                "ingest_errors": _safe_int(payload.get("ingest_errors")),
                "skipped_non_final_candles": _safe_int(payload.get("skipped_non_final_candles")),
                "skipped_reverse_timestamp": _safe_int(payload.get("skipped_reverse_timestamp")),
                "refresh_errors": _safe_int(payload.get("refresh_errors")),
                "auto_route_errors": _safe_int(payload.get("auto_route_errors")),
                "progress_callback_errors": _safe_int(payload.get("progress_callback_errors")),
                "last_ingest_error": str(payload.get("last_ingest_error") or ""),
                "last_refresh_error": str(payload.get("last_refresh_error") or ""),
                "last_auto_route_error": str(payload.get("last_auto_route_error") or ""),
                "last_progress_callback_error": str(payload.get("last_progress_callback_error") or ""),
                "last_ingest_success_at": str(payload.get("last_ingest_success_at") or ""),
                "last_ingest_error_at": str(payload.get("last_ingest_error_at") or ""),
                "last_refresh_success_at": str(payload.get("last_refresh_success_at") or ""),
                "last_refresh_error_at": str(payload.get("last_refresh_error_at") or ""),
                "last_auto_route_success_at": str(payload.get("last_auto_route_success_at") or ""),
                "last_auto_route_error_at": str(payload.get("last_auto_route_error_at") or ""),
                "last_progress_callback_success_at": str(payload.get("last_progress_callback_success_at") or ""),
                "last_progress_callback_error_at": str(payload.get("last_progress_callback_error_at") or ""),
                "last_stream_error": str(payload.get("last_stream_error") or ""),
            },
        )
        payload["ts"] = datetime.now(timezone.utc).isoformat()
        payload["outbox"] = engine.outbox_status()
        return payload


def main() -> int:
    args = parse_args()
    init_db()
    role = _worker_role(args)
    if not bool(args.skip_boot_check) and _live_mode_requires_boot_check():
        boot_check = _run_boot_check(args)
        if str(boot_check.get("overall_status") or "").upper() != "PASS":
            payload = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "worker_role": role,
                "error": "micro_live_boot_check_failed",
                "boot_check": boot_check,
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str), flush=True)
            return 2

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
            if args.sync_universe:
                write_worker_heartbeat(
                    "loop",
                    status="ok",
                    details={"phase": "syncing_universe", "interval_seconds": int(args.interval_seconds)},
                )

            def _sync_progress(progress: dict[str, Any]) -> None:
                write_worker_heartbeat(
                    "loop",
                    status="ok",
                    details={
                        "phase": str(progress.get("phase") or "syncing_universe"),
                        "state": str(progress.get("state") or ""),
                        "symbol": str(progress.get("symbol") or ""),
                        "completed_symbols": _safe_int(progress.get("completed_symbols")),
                        "total_symbols": _safe_int(progress.get("total_symbols")),
                        "success": _safe_int(progress.get("success")),
                        "failed": _safe_int(progress.get("failed")),
                        "symbol_concurrency": _safe_int(progress.get("symbol_concurrency")),
                        "interval_seconds": int(args.interval_seconds),
                    },
                )

            payload = run_once(args, progress_callback=_sync_progress if args.sync_universe else None)
            write_worker_heartbeat(
                "loop",
                status="ok",
                details={
                    "actions": [list(item.keys())[0] for item in payload.get("actions", [])],
                    "outbox": payload.get("outbox", {}),
                },
            )
            print(json.dumps(_compact_worker_log_payload(payload), ensure_ascii=False, default=str), flush=True)
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
