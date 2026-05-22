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
from app.services.market_data import configured_usdt_universe_name
from app.services.strategy_engine import StrategyEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate portfolio budget report")
    parser.add_argument("--universe", default=configured_usdt_universe_name())
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    init_db()

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        payload = engine.portfolio_budget_report(
            universe=args.universe,
            limit=max(1, args.limit),
            write_report=not args.no_write_report,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
