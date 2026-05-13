#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.models import Plan
from app.db.session import SessionLocal, init_db
from app.services.report_io import atomic_write_text
from app.services.strategy_engine import StrategyEngine


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replay recent session_impulse_retest opportunities and attribute whether "
            "runtime observed, blocked, or submitted them."
        )
    )
    parser.add_argument("--lookback-hours", type=int, default=72)
    parser.add_argument("--symbols", default="", help="Comma separated symbols. Empty -> current live universe.")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    return parser.parse_args()


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _session_bucket(ts: datetime, settings: Any) -> str:
    current = _to_utc(ts)
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    london_start = day_start.replace(hour=int(getattr(settings, "trading_session_london_start_hour_utc", 7)))
    london_end = day_start.replace(hour=int(getattr(settings, "trading_session_london_end_hour_utc", 12)))
    new_york_start = day_start.replace(hour=int(getattr(settings, "trading_session_new_york_start_hour_utc", 13)))
    new_york_end = day_start.replace(hour=int(getattr(settings, "trading_session_new_york_end_hour_utc", 18)))
    london_active = london_start <= current < london_end
    new_york_active = new_york_start <= current < new_york_end
    if london_active and new_york_active:
        return "london_new_york_overlap"
    if london_active:
        return "london"
    if new_york_active:
        return "new_york"
    return "dead_session"


def _matching_plan_ids(db: Any, plan_id: str) -> list[str]:
    stmt = (
        select(Plan.plan_id)
        .where(or_(Plan.plan_id == plan_id, Plan.plan_id.like(f"{plan_id}_r%")))
        .order_by(Plan.valid_from.asc(), Plan.plan_id.asc())
    )
    return [str(row) for row in db.scalars(stmt)]


def _row_payload(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    return {
        "id": str(getattr(row, "intent_id", getattr(row, "submission_id", "")) or ""),
        "approval_state": str(getattr(row, "approval_state", "") or ""),
        "submit_decision": str(getattr(row, "submit_decision", "") or ""),
        "decision_reason_code": str(getattr(row, "decision_reason_code", "") or ""),
        "decision_reason_message": str(getattr(row, "decision_reason_message", "") or ""),
        "submit_status": str(getattr(row, "submit_status", "") or ""),
        "state": str(getattr(row, "state", "") or ""),
        "message": str(getattr(row, "message", "") or ""),
        "created_at": str(getattr(row, "created_at", "") or ""),
        "submitted_at": str(getattr(row, "submitted_at", "") or ""),
    }


def _sort_ts(row: Any, *attrs: str) -> datetime:
    for attr in attrs:
        value = getattr(row, attr, None)
        if isinstance(value, datetime):
            return _to_utc(value)
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _status_for(*, observed: bool, intents: list[Any], submissions: list[Any]) -> tuple[str, str]:
    if submissions:
        latest = submissions[0]
        return "submitted", str(getattr(latest, "submit_status", "") or getattr(latest, "state", "") or "")
    if intents:
        latest = intents[0]
        decision = str(getattr(latest, "submit_decision", "") or "")
        reason = str(getattr(latest, "decision_reason_code", "") or "")
        if decision == "SUBMIT":
            return "submit_ready_without_submission", reason
        return "blocked_or_skipped", reason
    if observed:
        return "observed_without_intent", "missing_intent"
    return "not_observed", "runtime_plan_not_seen"


def _performance(rows: list[dict[str, Any]], *, risk_pct: float, account_equity: float) -> dict[str, Any]:
    total_r = sum(float(row["r_value"]) for row in rows)
    wins = sum(1 for row in rows if float(row["r_value"]) > 0.0)
    losses = len(rows) - wins
    compounded_equity = 1.0
    for row in rows:
        compounded_equity *= 1.0 + (float(row["r_value"]) * risk_pct)
    simple_return_pct = total_r * risk_pct * 100.0
    compounded_return_pct = (compounded_equity - 1.0) * 100.0
    return {
        "trade_count": len(rows),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(rows), 6) if rows else 0.0,
        "total_r": round(total_r, 6),
        "avg_r": round(total_r / len(rows), 6) if rows else 0.0,
        "risk_per_trade_pct": round(risk_pct * 100.0, 6),
        "simple_return_pct": round(simple_return_pct, 6),
        "compounded_return_pct": round(compounded_return_pct, 6),
        "account_equity_usdt": round(account_equity, 6),
        "simple_pnl_usdt": round(account_equity * simple_return_pct / 100.0, 6) if account_equity > 0 else None,
        "compounded_pnl_usdt": round(account_equity * compounded_return_pct / 100.0, 6) if account_equity > 0 else None,
    }


def _report_path(settings: Any, generated_at: datetime) -> Path:
    out_dir = Path(str(getattr(settings, "validation_report_dir", "reports/validation"))) / "micro_main_opportunity_reports"
    if not out_dir.is_absolute():
        out_dir = ROOT_DIR / out_dir
    return out_dir / f"session_impulse_retest_opportunity_report_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"


def build_report(*, lookback_hours: int, symbols: list[str] | None = None) -> dict[str, Any]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    risk_pct = float(getattr(settings, "auto_trading_live_risk_per_trade_pct", 0.0) or 0.0)
    account_equity = float(getattr(settings, "auto_trading_live_account_equity_usdt", 0.0) or 0.0)

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        target_symbols = engine._session_impulse_retest_miss_detector_symbols(symbols=symbols)
        cutoff = now - timedelta(hours=max(1, int(lookback_hours)))
        runtime_started_at = engine._session_impulse_retest_runtime_started_at()
        opportunities: list[dict[str, Any]] = []

        for symbol in target_symbols:
            trades = engine._session_impulse_retest_recent_replay_trades(
                symbol=symbol,
                cutoff=cutoff,
                end_ts=now,
            )
            for trade in trades:
                entry_ts = engine._to_utc(getattr(trade, "entry_ts"))
                direction = str(getattr(trade, "direction", "") or "").lower()
                plan_id = engine._session_impulse_retest_plan_id_for_entry(
                    symbol=symbol,
                    direction=direction,
                    entry_ts=entry_ts,
                )
                persisted_plan_ids = _matching_plan_ids(db, plan_id)
                observation = engine._session_impulse_retest_runtime_plan_observation(
                    symbol=symbol,
                    entry_ts=entry_ts,
                    direction=direction,
                )
                observed = bool(observation.get("seen")) or bool(persisted_plan_ids)
                lookup_plan_ids = persisted_plan_ids or [plan_id]
                intents = []
                submissions = []
                for lookup_plan_id in lookup_plan_ids:
                    intents.extend(engine.intent_repo.list_for_plan(lookup_plan_id, limit=20))
                    submissions.extend(engine.submission_repo.list_for_plan(lookup_plan_id, limit=20))
                intents.sort(key=lambda row: _sort_ts(row, "created_at"), reverse=True)
                submissions.sort(key=lambda row: _sort_ts(row, "submitted_at", "created_at"), reverse=True)
                status, reason = _status_for(observed=observed, intents=intents, submissions=submissions)
                opportunities.append(
                    {
                        "symbol": symbol,
                        "direction": direction,
                        "session": _session_bucket(entry_ts, settings),
                        "entry_ts": entry_ts.isoformat(),
                        "signal_ts": str(getattr(trade, "signal_ts", "") or ""),
                        "exit_ts": str(getattr(trade, "exit_ts", "") or ""),
                        "exit_reason": str(getattr(trade, "exit_reason", "") or ""),
                        "hold_minutes": int(getattr(trade, "hold_minutes", 0) or 0),
                        "r_value": round(float(getattr(trade, "r_value", 0.0) or 0.0), 6),
                        "return_pct_at_configured_risk": round(
                            float(getattr(trade, "r_value", 0.0) or 0.0) * risk_pct * 100.0,
                            6,
                        ),
                        "expected_plan_id": plan_id,
                        "persisted_plan_ids": persisted_plan_ids,
                        "runtime_observed": observed,
                        "runtime_observation": observation,
                        "intent_count": len(intents),
                        "submission_count": len(submissions),
                        "latest_intent": _row_payload(intents[0] if intents else None),
                        "latest_submission": _row_payload(submissions[0] if submissions else None),
                        "runtime_status": status,
                        "runtime_reason": reason,
                        "before_current_runtime_start": bool(
                            runtime_started_at is not None and entry_ts < runtime_started_at
                        ),
                    }
                )

    opportunities.sort(key=lambda row: str(row.get("entry_ts") or ""))
    status_counts = Counter(str(row["runtime_status"]) for row in opportunities)
    reason_counts = Counter(str(row["runtime_reason"]) for row in opportunities)
    symbol_counts = Counter(str(row["symbol"]) for row in opportunities)
    session_counts = Counter(str(row["session"]) for row in opportunities)
    reason_performance: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in opportunities:
        grouped[str(row["runtime_reason"])].append(row)
    for reason, rows in grouped.items():
        reason_performance[reason] = _performance(rows, risk_pct=risk_pct, account_equity=account_equity)

    payload = {
        "schema_version": "session_impulse_retest_opportunity_report_v1",
        "generated_at": now.isoformat(),
        "lookback_hours": max(1, int(lookback_hours)),
        "window_start": cutoff.isoformat(),
        "window_end": now.isoformat(),
        "runtime_started_at": runtime_started_at.isoformat() if runtime_started_at else None,
        "contract": {
            "family": "session_impulse_retest",
            "entry_model": "CONFIRM",
            "symbols": target_symbols,
            "sessions": str(getattr(settings, "auto_trading_micro_live_allowed_sessions", "")),
            "execution_mode": str(getattr(settings, "auto_trading_execution_mode", "")),
            "risk_per_trade_pct": round(risk_pct * 100.0, 6),
            "account_equity_usdt": round(account_equity, 6),
        },
        "summary": {
            "expected_order_count": len(opportunities),
            "status_counts": dict(sorted(status_counts.items())),
            "reason_counts": dict(sorted(reason_counts.items())),
            "symbol_counts": dict(sorted(symbol_counts.items())),
            "session_counts": dict(sorted(session_counts.items())),
            "before_current_runtime_start_count": sum(
                1 for row in opportunities if bool(row.get("before_current_runtime_start"))
            ),
            "potential_performance": _performance(opportunities, risk_pct=risk_pct, account_equity=account_equity),
            "performance_by_runtime_reason": reason_performance,
        },
        "opportunities": opportunities,
        "report_path": None,
    }
    return payload


def main() -> int:
    args = _parse_args()
    init_db()
    symbols = [item.strip().upper() for item in str(args.symbols or "").split(",") if item.strip()]
    payload = build_report(lookback_hours=args.lookback_hours, symbols=symbols or None)
    if args.write_report:
        path = _report_path(get_settings(), datetime.now(timezone.utc))
        payload["report_path"] = str(path)
        atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    if args.summary_only:
        print(json.dumps({key: payload[key] for key in ("generated_at", "lookback_hours", "contract", "summary", "report_path")}, ensure_ascii=False, indent=2, default=str))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
