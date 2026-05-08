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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect replay/runtime misses for session_impulse_retest.")
    parser.add_argument("--lookback-hours", type=int, default=24)
    parser.add_argument("--symbols", default="", help="Comma separated symbols. Empty -> current live universe.")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    init_db()
    symbols = [item.strip().upper() for item in str(args.symbols or "").split(",") if item.strip()]
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        payload = engine.detect_session_impulse_retest_recent_misses(
            lookback_hours=args.lookback_hours,
            symbols=symbols or None,
            write_report=bool(args.write_report),
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
