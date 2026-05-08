from __future__ import annotations

import argparse
import re
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Iterable

from sqlalchemy import delete, select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.models import (
    AlertRetryTask,
    AlertSubscription,
    BinanceOrderLedger,
    BinancePositionSnapshot,
    ExecutionFill,
    ExecutionReconciliationEvent,
    OrderIntent,
    OrderSubmission,
    Plan,
    SafetyLock,
    StrategyMetric,
    ValidationPboDsrSnapshot,
    ValidationTrialFoldScore,
    ValidationTrialRun,
    Zone,
    ZoneOutcome,
)
from app.db.session import SessionLocal, init_db


TEST_SYMBOL_PATTERNS = (
    r"^AQ[0-9]+USDC$",
    r"^BTCPRIO[0-9]+USDC$",
    r"^CLUSTER[0-9]+USDC$",
    r"^OPS[0-9]+USDC$",
    r"^DBG[A-Z0-9]+USDC$",
    r"^ETHPRIO[0-9]+USDC$",
    r"^LOCKSYM[0-9]+USDC$",
    r"^LOCKGLB[0-9]+USDC$",
    r"^LK[0-9]+USDC$",
    r"^LR[0-9]+USDC$",
    r"^LS[0-9]+USDC$",
    r"^OUTCOME[0-9]+USDC$",
    r"^PAPER[0-9]+USDC$",
    r"^PCOLL[0-9]+USDC$",
    r"^PEXCLOSE[0-9]+USDC$",
    r"^PEXFAST[0-9]+USDC$",
    r"^PEXFASTSKIP[0-9]+USDC$",
    r"^PEXIT[0-9]+USDC$",
    r"^PEXTIME[0-9]+USDC$",
    r"^PEXWAIT[0-9]+USDC$",
    r"^PQ[0-9]+USDC$",
    r"^PREENTRY[0-9]+USDC$",
    r"^PRESUB[0-9]+USDC$",
    r"^RECON[0-9]+USDC$",
    r"^DEDUPE[0-9]+USDC$",
    r"^EXECPRE[0-9]+USDC$",
    r"^FILLGAP[0-9]+USDC$",
    r"^PLINE[0-9]+USDC$",
    r"^PLNO[0-9]+USDC$",
    r"^REPOTEST[0-9]+USDC$",
    r"^LIVE[0-9]+USDC$",
    r"^LH[0-9]+USDC$",
    r"^RO[0-9]+USDC$",
    r"^BUS[0-9]+USDC$",
    r"^PBOENGINE[0-9]+USDC$",
    r"^PLALW[0-9]+USDC$",
    r"^PLCF[0-9]+USDC$",
    r"^STALEDUPE[0-9]+USDC$",
    r"^STALESUB[0-9]+USDC$",
    r"^XQ[0-9]+USDC$",
)


def _compile_patterns(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    return [re.compile(pattern) for pattern in patterns]


def _matches_any(symbol: str | None, patterns: list[re.Pattern[str]]) -> bool:
    if not symbol:
        return False
    return any(pattern.match(symbol) for pattern in patterns)


def _collect_symbols(patterns: list[re.Pattern[str]]) -> list[str]:
    models_with_symbol = (
        Plan,
        Zone,
        ZoneOutcome,
        AlertSubscription,
        AlertRetryTask,
        ExecutionFill,
        BinanceOrderLedger,
        BinancePositionSnapshot,
        OrderIntent,
        OrderSubmission,
        ExecutionReconciliationEvent,
        ValidationTrialRun,
        ValidationTrialFoldScore,
        ValidationPboDsrSnapshot,
        StrategyMetric,
    )
    seen: OrderedDict[str, None] = OrderedDict()
    with SessionLocal() as db:
        for model in models_with_symbol:
            rows = db.execute(select(model.symbol).distinct()).scalars().all()
            for symbol in rows:
                if _matches_any(symbol, patterns):
                    seen[str(symbol)] = None
        rows = db.execute(
            select(SafetyLock.scope_key).where(SafetyLock.scope_type == "SYMBOL").distinct()
        ).scalars().all()
        for scope_key in rows:
            if _matches_any(scope_key, patterns):
                seen[str(scope_key)] = None
    return list(seen.keys())


def _count_matches(symbols: list[str]) -> dict[str, int]:
    if not symbols:
        return {}

    def _count(db, stmt) -> int:
        return len(db.execute(stmt).scalars().all())

    counts: dict[str, int] = {}
    with SessionLocal() as db:
        counts["plans"] = _count(db, select(Plan.plan_id).where(Plan.symbol.in_(symbols)))
        counts["zones"] = _count(db, select(Zone.zone_id).where(Zone.symbol.in_(symbols)))
        counts["zone_outcomes"] = _count(db, select(ZoneOutcome.id).where(ZoneOutcome.symbol.in_(symbols)))
        counts["alerts"] = _count(db, select(AlertSubscription.alert_id).where(AlertSubscription.symbol.in_(symbols)))
        counts["alert_retry_queue"] = _count(db, select(AlertRetryTask.task_id).where(AlertRetryTask.symbol.in_(symbols)))
        counts["execution_fills"] = _count(db, select(ExecutionFill.fill_id).where(ExecutionFill.symbol.in_(symbols)))
        counts["binance_order_ledger"] = _count(
            db, select(BinanceOrderLedger.client_order_id).where(BinanceOrderLedger.symbol.in_(symbols))
        )
        counts["binance_positions"] = _count(
            db, select(BinancePositionSnapshot.position_key).where(BinancePositionSnapshot.symbol.in_(symbols))
        )
        counts["order_intents"] = _count(db, select(OrderIntent.intent_id).where(OrderIntent.symbol.in_(symbols)))
        counts["order_submissions"] = _count(
            db, select(OrderSubmission.submission_id).where(OrderSubmission.symbol.in_(symbols))
        )
        counts["execution_reconciliation_events"] = _count(
            db, select(ExecutionReconciliationEvent.event_id).where(ExecutionReconciliationEvent.symbol.in_(symbols))
        )
        counts["validation_trial_runs"] = _count(
            db, select(ValidationTrialRun.trial_run_id).where(ValidationTrialRun.symbol.in_(symbols))
        )
        counts["validation_trial_fold_scores"] = _count(
            db, select(ValidationTrialFoldScore.id).where(ValidationTrialFoldScore.symbol.in_(symbols))
        )
        counts["validation_pbo_dsr_snapshots"] = _count(
            db, select(ValidationPboDsrSnapshot.snapshot_id).where(ValidationPboDsrSnapshot.symbol.in_(symbols))
        )
        counts["strategy_metrics"] = _count(db, select(StrategyMetric.id).where(StrategyMetric.symbol.in_(symbols)))
        counts["safety_locks"] = _count(
            db,
            select(SafetyLock.lock_id).where(SafetyLock.scope_type == "SYMBOL", SafetyLock.scope_key.in_(symbols)),
        )
        counts["global_test_safety_locks"] = _count(
            db,
            select(SafetyLock.lock_id).where(
                SafetyLock.scope_type == "GLOBAL",
                SafetyLock.active.is_(True),
                (
                    SafetyLock.reason_message.ilike("%dashboard test%")
                    | SafetyLock.lock_metadata.ilike("%test_operator_dashboard%")
                ),
            ),
        )
    return counts


def _delete_matches(symbols: list[str]) -> dict[str, int]:
    if not symbols:
        return {}
    deleted: dict[str, int] = {}
    with SessionLocal() as db:
        statements = (
            ("alert_retry_queue", delete(AlertRetryTask).where(AlertRetryTask.symbol.in_(symbols))),
            ("alerts", delete(AlertSubscription).where(AlertSubscription.symbol.in_(symbols))),
            ("execution_fills", delete(ExecutionFill).where(ExecutionFill.symbol.in_(symbols))),
            ("order_submissions", delete(OrderSubmission).where(OrderSubmission.symbol.in_(symbols))),
            ("order_intents", delete(OrderIntent).where(OrderIntent.symbol.in_(symbols))),
            ("binance_order_ledger", delete(BinanceOrderLedger).where(BinanceOrderLedger.symbol.in_(symbols))),
            ("binance_positions", delete(BinancePositionSnapshot).where(BinancePositionSnapshot.symbol.in_(symbols))),
            (
                "execution_reconciliation_events",
                delete(ExecutionReconciliationEvent).where(ExecutionReconciliationEvent.symbol.in_(symbols)),
            ),
            ("zone_outcomes", delete(ZoneOutcome).where(ZoneOutcome.symbol.in_(symbols))),
            ("plans", delete(Plan).where(Plan.symbol.in_(symbols))),
            ("zones", delete(Zone).where(Zone.symbol.in_(symbols))),
            ("validation_trial_fold_scores", delete(ValidationTrialFoldScore).where(ValidationTrialFoldScore.symbol.in_(symbols))),
            ("validation_trial_runs", delete(ValidationTrialRun).where(ValidationTrialRun.symbol.in_(symbols))),
            ("validation_pbo_dsr_snapshots", delete(ValidationPboDsrSnapshot).where(ValidationPboDsrSnapshot.symbol.in_(symbols))),
            ("strategy_metrics", delete(StrategyMetric).where(StrategyMetric.symbol.in_(symbols))),
            (
                "safety_locks",
                delete(SafetyLock).where(SafetyLock.scope_type == "SYMBOL", SafetyLock.scope_key.in_(symbols)),
            ),
            (
                "global_test_safety_locks",
                delete(SafetyLock).where(
                    SafetyLock.scope_type == "GLOBAL",
                    SafetyLock.active.is_(True),
                    (
                        SafetyLock.reason_message.ilike("%dashboard test%")
                        | SafetyLock.lock_metadata.ilike("%test_operator_dashboard%")
                    ),
                ),
            ),
        )
        for label, stmt in statements:
            result = db.execute(stmt)
            deleted[label] = int(result.rowcount or 0)
        db.commit()
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove synthetic execution-test artifacts from the local trading.db state."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply deletions. Without this flag the script only prints a dry-run summary.",
    )
    args = parser.parse_args()

    init_db()
    patterns = _compile_patterns(TEST_SYMBOL_PATTERNS)
    symbols = _collect_symbols(patterns)

    print("mode:", "apply" if args.apply else "dry_run")
    print("matched_symbols:", symbols)
    print("matched_symbol_count:", len(symbols))
    counts = _count_matches(symbols)
    print("row_counts:", counts)

    if not args.apply:
        return 0

    deleted = _delete_matches(symbols)
    print("deleted:", deleted)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
