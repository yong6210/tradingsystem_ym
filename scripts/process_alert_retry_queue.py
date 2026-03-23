#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.session import SessionLocal, init_db
from app.services.strategy_engine import StrategyEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process alert retry queue or requeue dead-letter items")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--requeue-dead-letter", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    init_db()

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        if args.requeue_dead_letter:
            payload = engine.requeue_dead_letter_alerts(limit=max(1, args.limit))
        else:
            payload = engine.process_alert_retry_queue(limit=max(1, args.limit))
        payload["status"] = engine.alert_retry_queue_status()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
