#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.repositories import LiquidationEventRepository
from app.db.session import SessionLocal, init_db
from app.services.liquidation_stream_collector import LiquidationStreamCollector


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture Binance futures liquidation events from forceOrder WS.")
    parser.add_argument("--symbols", default="BTCUSDC,ETHUSDC")
    parser.add_argument("--max-events", type=int, default=25)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--idle-reconnect-seconds", type=float, default=300.0)
    parser.add_argument("--reconnect-backoff-seconds", type=float, default=2.0)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    init_db()
    settings = get_settings()
    symbols = [item.strip().upper() for item in str(args.symbols or "").split(",") if item.strip()]
    generated_at = datetime.now(UTC)
    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "symbols": symbols,
        "max_events": int(args.max_events),
        "timeout_seconds": float(args.timeout_seconds),
        "idle_reconnect_seconds": float(args.idle_reconnect_seconds),
        "reconnect_backoff_seconds": float(args.reconnect_backoff_seconds),
    }
    with SessionLocal() as db:
        collector = LiquidationStreamCollector(repo=LiquidationEventRepository(db))
        summary = await collector.capture(
            symbols=symbols,
            max_events=int(args.max_events) if args.max_events is not None else None,
            timeout_seconds=float(args.timeout_seconds) if args.timeout_seconds is not None else None,
            idle_reconnect_seconds=float(args.idle_reconnect_seconds),
            reconnect_backoff_seconds=float(args.reconnect_backoff_seconds),
        )
        db.commit()
        payload["summary"] = asdict(summary)

    if args.write_report:
        out_dir = Path(settings.validation_report_dir) / "liquidation_captures"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"liquidation_capture_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["report_path"] = str(out_path)
    return payload


def main() -> int:
    args = _parse_args()
    payload = asyncio.run(_run(args))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
