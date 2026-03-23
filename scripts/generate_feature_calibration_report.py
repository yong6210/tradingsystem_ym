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
    parser = argparse.ArgumentParser(description="Generate feature calibration report")
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    init_db()

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        if args.refresh:
            engine.refresh_symbol(args.symbol)
        payload = engine.feature_calibration(
            symbol=args.symbol,
            write_report=not args.no_write_report,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
