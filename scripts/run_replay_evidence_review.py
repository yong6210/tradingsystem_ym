#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.repositories import CandleRepository, ExecutionFillRepository, PlanRepository
from app.db.session import SessionLocal, init_db
from app.services.replay_evidence_review import ReplayEvidenceReviewService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run replay-proxy evidence review for a symbol.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--version", default=None)
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def main() -> int:
    args = parse_args()
    init_db()
    settings = get_settings()
    with SessionLocal() as db:
        service = ReplayEvidenceReviewService(
            settings=settings,
            plan_repo=PlanRepository(db),
            fill_repo=ExecutionFillRepository(db),
            candle_repo=CandleRepository(db),
        )
        payload = service.generate(
            symbol=str(args.symbol).upper(),
            days=max(1, int(args.days)),
            version=args.version or settings.strategy_version,
            write_report=not args.no_write_report,
            limit=max(100, int(args.limit)),
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
