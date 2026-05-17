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
    parser = argparse.ArgumentParser(description="Generate execution quality report")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    init_db()

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        payload = engine.execution_quality_report(
            symbol=args.symbol,
            days=max(1, args.days),
            write_report=not args.no_write_report,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
