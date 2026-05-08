from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal, init_db
from app.services.strategy_engine import StrategyEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Print recent session_impulse_retest runtime audits.")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--phase", type=str, default=None)
    parser.add_argument("--status", type=str, default=None)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    init_db()
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        payload = engine.session_impulse_retest_runtime_audits_recent(
            hours=args.hours,
            symbol=args.symbol,
            phase=args.phase,
            status=args.status,
            limit=args.limit,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
