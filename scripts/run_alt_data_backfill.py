#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
from app.db.repositories import BasisSnapshotRepository, CandleRepository, CrossAssetBreadthRepository, FundingRateRepository, MacroEventRepository, OpenInterestRepository
from app.db.session import SessionLocal, init_db
from app.services.alt_data_market import AltDataMarketService


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill Binance alt-data series into local DB.")
    parser.add_argument("--symbols", default="BTCUSDC,ETHUSDC")
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument("--oi-period", default="15m")
    parser.add_argument("--basis-timeframe", default="15m")
    parser.add_argument("--breadth-timeframe", default="15m")
    parser.add_argument("--breadth-pairs", default="BTCUSDC:ETHUSDC,ETHUSDC:BTCUSDC")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    init_db()
    settings = get_settings()
    symbols = [item.strip().upper() for item in str(args.symbols or "").split(",") if item.strip()]
    generated_at = datetime.now(UTC)

    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "symbols": symbols,
        "lookback_days": int(args.lookback_days),
        "results": {},
        "breadth_pairs": {},
        "macro_events": {},
    }

    with SessionLocal() as db:
        service = AltDataMarketService(
            funding_repo=FundingRateRepository(db),
            open_interest_repo=OpenInterestRepository(db),
            basis_repo=BasisSnapshotRepository(db),
            macro_event_repo=MacroEventRepository(db),
            candle_repo=CandleRepository(db),
            breadth_repo=CrossAssetBreadthRepository(db),
        )
        for symbol in symbols:
            summary = service.backfill_symbol_alt_data(
                symbol=symbol,
                lookback_days=int(args.lookback_days),
                oi_period=str(args.oi_period),
                basis_timeframe=str(args.basis_timeframe),
            )
            db.commit()
            payload["results"][symbol] = asdict(summary)

        macro_event_rows = service.backfill_macro_events(lookback_days=max(int(args.lookback_days), 730))
        db.commit()
        payload["macro_events"] = {
            "source": "federalreserve_fomc_schedule",
            "rows": int(macro_event_rows),
        }

        breadth_pairs = [item.strip() for item in str(args.breadth_pairs or "").split(",") if item.strip()]
        for pair in breadth_pairs:
            if ":" not in pair:
                continue
            leader_symbol, confirm_symbol = (part.strip().upper() for part in pair.split(":", 1))
            rows = service.backfill_cross_asset_breadth(
                leader_symbol=leader_symbol,
                confirm_symbol=confirm_symbol,
                timeframe=str(args.breadth_timeframe),
                lookback_days=int(args.lookback_days),
            )
            db.commit()
            payload["breadth_pairs"][f"{leader_symbol}:{confirm_symbol}"] = {
                "leader_symbol": leader_symbol,
                "confirm_symbol": confirm_symbol,
                "timeframe": str(args.breadth_timeframe),
                "breadth_rows": int(rows),
            }

    if args.write_report:
        out_dir = Path(settings.validation_report_dir) / "alt_data_backfills"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"alt_data_backfill_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["report_path"] = str(out_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
