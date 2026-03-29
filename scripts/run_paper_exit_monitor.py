#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.session import SessionLocal, init_db
from app.services.strategy_engine import StrategyEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate open PAPER positions and ingest exit fills when TP/SL/expiry is reached.")
    parser.add_argument(
        "--families",
        default=os.environ.get("PAPER_EXIT_MONITOR_FAMILIES", "sweep_reversal,trend_continuation"),
    )
    parser.add_argument("--days", type=int, default=int(os.environ.get("PAPER_EXIT_MONITOR_DAYS", "7")))
    parser.add_argument("--limit", type=int, default=int(os.environ.get("PAPER_EXIT_MONITOR_LIMIT", "200")))
    parser.add_argument(
        "--sync-candles",
        action="store_true",
        default=os.environ.get("PAPER_EXIT_MONITOR_SYNC_CANDLES", "1").strip().lower() in {"1", "true", "yes", "on"},
    )
    parser.add_argument("--limit-1m", type=int, default=int(os.environ.get("PAPER_EXIT_MONITOR_LIMIT_1M", "3")))
    parser.add_argument("--limit-5m", type=int, default=int(os.environ.get("PAPER_EXIT_MONITOR_LIMIT_5M", "3")))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    init_db()
    families = [item.strip() for item in str(args.families or "").split(",") if item.strip()]
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        payload = engine.process_paper_exit_tick(
            families=families,
            days=max(1, int(args.days)),
            limit=max(1, int(args.limit)),
            sync_candles=bool(args.sync_candles),
            limit_1m=max(1, int(args.limit_1m)),
            limit_5m=max(1, int(args.limit_5m)),
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
