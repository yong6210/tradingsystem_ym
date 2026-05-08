#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.repositories import CandleRepository
from app.db.session import SessionLocal, init_db
from app.services.pair_strategy_research import PairStrategyResearchEngine, summarize_pair_trades


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BTC-ETH SMT divergence research scan.")
    parser.add_argument("--leader", default="BTCUSDC")
    parser.add_argument("--confirmer", default="ETHUSDC")
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _decision(summary: dict[str, Any]) -> str:
    ev = float(summary.get("ev_r", 0.0) or 0.0)
    closed = int(summary.get("closed", 0) or 0)
    total_r = float(summary.get("total_r", 0.0) or 0.0)
    if total_r <= 0.0 or ev < 0.20 or closed < 20:
        return "REJECT"
    if ev >= 0.30 and closed >= 40:
        return "PASS"
    return "WATCH"


def main() -> int:
    args = _parse_args()
    init_db()
    settings = get_settings()
    leader = str(args.leader).upper()
    confirmer = str(args.confirmer).upper()
    generated_at = datetime.now(UTC)

    with SessionLocal() as db:
        repo = CandleRepository(db)
        last_leader = repo.get_last_candle(leader, "15m")
        first_leader = repo.get_first_candle(leader, "15m")
        last_conf = repo.get_last_candle(confirmer, "15m")
        first_conf = repo.get_first_candle(confirmer, "15m")
        if not all([last_leader, first_leader, last_conf, first_conf]):
            raise RuntimeError("missing 15m candles for leader/confirmer")
        end_ts = min(
            last_leader.ts if last_leader.ts.tzinfo is not None else last_leader.ts.replace(tzinfo=UTC),
            last_conf.ts if last_conf.ts.tzinfo is not None else last_conf.ts.replace(tzinfo=UTC),
        )
        start_ts = max(
            first_leader.ts if first_leader.ts.tzinfo is not None else first_leader.ts.replace(tzinfo=UTC),
            first_conf.ts if first_conf.ts.tzinfo is not None else first_conf.ts.replace(tzinfo=UTC),
            end_ts - timedelta(days=max(int(args.lookback_days), 1)),
        )
        leader_candles = repo.list_range(symbol=leader, timeframe="15m", start_ts=start_ts, end_ts=end_ts)
        confirmer_candles = repo.list_range(symbol=confirmer, timeframe="15m", start_ts=start_ts, end_ts=end_ts)

    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "leader": leader,
        "confirmer": confirmer,
        "lookback_days": int(args.lookback_days),
        "window": {
            "start_ts": start_ts.isoformat(),
            "end_ts": end_ts.isoformat(),
            "leader_candle_count": len(leader_candles),
            "confirmer_candle_count": len(confirmer_candles),
        },
        "results": {},
    }

    for traded_symbol, reference_symbol, traded_candles, reference_candles in (
        (leader, confirmer, leader_candles, confirmer_candles),
        (confirmer, leader, confirmer_candles, leader_candles),
    ):
        engine = PairStrategyResearchEngine(
            leader_symbol=traded_symbol,
            confirmer_symbol=reference_symbol,
            leader_candles=traded_candles,
            confirmer_candles=reference_candles,
        )
        trades = engine.backtest_smt_divergence()
        summary = summarize_pair_trades(trades)
        summary["decision"] = _decision(summary)
        summary["sample_trade_rows"] = [
            {
                "entry_ts": trade.entry_ts.isoformat(),
                "exit_ts": trade.exit_ts.isoformat(),
                "direction": trade.direction,
                "r_value": round(trade.r_value, 4),
                "exit_reason": trade.exit_reason,
            }
            for trade in trades[:5]
        ]
        payload["results"][f"smt_{traded_symbol}_vs_{reference_symbol}"] = summary

    if args.write_report:
        out_dir = Path(settings.validation_report_dir) / "pair_strategy_scans"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"pair_smt_scan_{leader}_{confirmer}_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["report_path"] = str(out_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
