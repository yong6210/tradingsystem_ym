#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.session import SessionLocal, init_db
from app.services.strategy_engine import StrategyEngine
from app.services.transition_variant_live_readiness import (
    evaluate_transition_variant_live_readiness,
    readiness_to_dict,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize transition edge variant live readiness.")
    parser.add_argument("--symbols", default="BTCUSDC,ETHUSDC")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    init_db()
    settings = get_settings()
    generated_at = datetime.now(UTC)
    symbols = [item.strip().upper() for item in str(args.symbols or "").split(",") if item.strip()]

    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "symbols": symbols,
        "days": int(args.days),
        "readiness": {},
    }

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        for symbol in symbols:
            dashboard = engine.execution_operator_dashboard(
                symbol=symbol,
                universe=str(args.universe),
                portfolio_limit=10,
                intent_limit=10,
                reconcile_limit=10,
                days=int(args.days),
            )
            safety = engine.safety_state(symbol=symbol)
            readiness = evaluate_transition_variant_live_readiness(
                symbol=symbol,
                dashboard_payload=dashboard,
                safety_payload=safety,
            )
            payload["readiness"][symbol] = readiness_to_dict(readiness)

    if args.write_report:
        out_dir = Path(settings.validation_report_dir) / "transition_live_readiness"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"transition_variant_live_readiness_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["report_path"] = str(out_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
