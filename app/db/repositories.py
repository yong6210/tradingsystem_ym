from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import ClassVar, Iterable
from uuid import uuid4

from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.enums import EventStatus, PlanState, ZoneState
from app.db.models import (
    AlertRetryTask,
    AlertSubscription,
    BasisSnapshot,
    BinanceOrderLedger,
    BinancePositionSnapshot,
    Candle,
    CrossAssetBreadthSnapshot,
    ExecutionReconciliationEvent,
    EventOutbox,
    ExecutionFill,
    FamilyRolloutPolicy,
    FundingRateSnapshot,
    LiquidationEvent,
    MacroEvent,
    OpenInterestSnapshot,
    OrderIntent,
    OrderSubmission,
    Plan,
    PromotionLifecycleHistory,
    SafetyLock,
    SessionImpulseRetestRuntimeAudit,
    StrategyMetric,
    ValidationPboDsrSnapshot,
    ValidationTrialFoldScore,
    ValidationTrialRun,
    Zone,
    ZoneOutcome,
    utcnow,
)


class CandleRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _identity_stmt(*, symbol: str, timeframe: str, ts: datetime):
        return select(Candle).where(
            Candle.symbol == symbol,
            Candle.timeframe == timeframe,
            Candle.ts == ts,
        )

    def get_last_candle(self, symbol: str, timeframe: str) -> Candle | None:
        stmt = (
            select(Candle)
            .where(Candle.symbol == symbol, Candle.timeframe == timeframe)
            .order_by(desc(Candle.ts))
            .limit(1)
        )
        return self.db.scalar(stmt)

    def get_first_candle(self, symbol: str, timeframe: str) -> Candle | None:
        stmt = (
            select(Candle)
            .where(Candle.symbol == symbol, Candle.timeframe == timeframe)
            .order_by(Candle.ts.asc())
            .limit(1)
        )
        return self.db.scalar(stmt)

    def upsert(self, candle: Candle) -> Candle:
        stmt = self._identity_stmt(symbol=candle.symbol, timeframe=candle.timeframe, ts=candle.ts)
        values = {
            "symbol": candle.symbol,
            "timeframe": candle.timeframe,
            "ts": candle.ts,
            "o": candle.o,
            "h": candle.h,
            "l": candle.l,
            "c": candle.c,
            "v": candle.v,
            "source": candle.source,
            "is_final": candle.is_final,
            "created_at": candle.created_at or utcnow(),
        }
        update_values = {
            "o": values["o"],
            "h": values["h"],
            "l": values["l"],
            "c": values["c"],
            "v": values["v"],
            "is_final": values["is_final"],
            "source": values["source"],
        }
        bind = self.db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""

        if dialect_name == "sqlite":
            upsert_stmt = sqlite_insert(Candle).values(**values).on_conflict_do_update(
                index_elements=["symbol", "timeframe", "ts"],
                set_=update_values,
            )
            self.db.execute(upsert_stmt)
            return self.db.scalar(stmt) or candle

        if dialect_name == "postgresql":
            upsert_stmt = pg_insert(Candle).values(**values).on_conflict_do_update(
                index_elements=["symbol", "timeframe", "ts"],
                set_=update_values,
            )
            self.db.execute(upsert_stmt)
            return self.db.scalar(stmt) or candle

        existing = self.db.scalar(stmt)
        if existing:
            existing.o = candle.o
            existing.h = candle.h
            existing.l = candle.l
            existing.c = candle.c
            existing.v = candle.v
            existing.is_final = candle.is_final
            existing.source = candle.source
            self.db.add(existing)
            return existing

        self.db.add(candle)
        return candle

    def list_recent(self, symbol: str, timeframe: str, limit: int = 300) -> list[Candle]:
        stmt = (
            select(Candle)
            .where(Candle.symbol == symbol, Candle.timeframe == timeframe)
            .order_by(desc(Candle.ts))
            .limit(limit)
        )
        rows = list(self.db.scalars(stmt))
        rows.reverse()
        return rows

    def list_range(
        self,
        *,
        symbol: str,
        timeframe: str,
        start_ts: datetime,
        end_ts: datetime,
    ) -> list[Candle]:
        stmt = (
            select(Candle)
            .where(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
                Candle.ts >= start_ts,
                Candle.ts <= end_ts,
            )
            .order_by(Candle.ts.asc())
        )
        return list(self.db.scalars(stmt))


class FundingRateRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, row: FundingRateSnapshot) -> FundingRateSnapshot:
        stmt = select(FundingRateSnapshot).where(
            FundingRateSnapshot.symbol == row.symbol,
            FundingRateSnapshot.ts == row.ts,
        )
        existing = self.db.scalar(stmt)
        if existing:
            existing.funding_rate = row.funding_rate
            existing.mark_price = row.mark_price
            existing.source = row.source
            existing.raw = row.raw
            self.db.add(existing)
            return existing
        self.db.add(row)
        return row

    def get_last(self, symbol: str) -> FundingRateSnapshot | None:
        stmt = (
            select(FundingRateSnapshot)
            .where(FundingRateSnapshot.symbol == symbol.upper())
            .order_by(desc(FundingRateSnapshot.ts))
            .limit(1)
        )
        return self.db.scalar(stmt)

    def list_range(self, *, symbol: str, start_ts: datetime, end_ts: datetime) -> list[FundingRateSnapshot]:
        stmt = (
            select(FundingRateSnapshot)
            .where(
                FundingRateSnapshot.symbol == symbol.upper(),
                FundingRateSnapshot.ts >= start_ts,
                FundingRateSnapshot.ts <= end_ts,
            )
            .order_by(FundingRateSnapshot.ts.asc())
        )
        return list(self.db.scalars(stmt))


class OpenInterestRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, row: OpenInterestSnapshot) -> OpenInterestSnapshot:
        stmt = select(OpenInterestSnapshot).where(
            OpenInterestSnapshot.symbol == row.symbol,
            OpenInterestSnapshot.period == row.period,
            OpenInterestSnapshot.ts == row.ts,
        )
        existing = self.db.scalar(stmt)
        if existing:
            existing.open_interest = row.open_interest
            existing.open_interest_value = row.open_interest_value
            existing.source = row.source
            existing.raw = row.raw
            self.db.add(existing)
            return existing
        self.db.add(row)
        return row

    def get_last(self, symbol: str, period: str) -> OpenInterestSnapshot | None:
        stmt = (
            select(OpenInterestSnapshot)
            .where(
                OpenInterestSnapshot.symbol == symbol.upper(),
                OpenInterestSnapshot.period == period,
            )
            .order_by(desc(OpenInterestSnapshot.ts))
            .limit(1)
        )
        return self.db.scalar(stmt)

    def list_range(self, *, symbol: str, period: str, start_ts: datetime, end_ts: datetime) -> list[OpenInterestSnapshot]:
        stmt = (
            select(OpenInterestSnapshot)
            .where(
                OpenInterestSnapshot.symbol == symbol.upper(),
                OpenInterestSnapshot.period == period,
                OpenInterestSnapshot.ts >= start_ts,
                OpenInterestSnapshot.ts <= end_ts,
            )
            .order_by(OpenInterestSnapshot.ts.asc())
        )
        return list(self.db.scalars(stmt))


class BasisSnapshotRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, row: BasisSnapshot) -> BasisSnapshot:
        stmt = select(BasisSnapshot).where(
            BasisSnapshot.symbol == row.symbol,
            BasisSnapshot.timeframe == row.timeframe,
            BasisSnapshot.ts == row.ts,
        )
        existing = self.db.scalar(stmt)
        if existing:
            existing.basis_open = row.basis_open
            existing.basis_high = row.basis_high
            existing.basis_low = row.basis_low
            existing.basis_close = row.basis_close
            existing.basis_bps = row.basis_bps
            existing.source = row.source
            existing.raw = row.raw
            self.db.add(existing)
            return existing
        self.db.add(row)
        return row

    def get_last(self, symbol: str, timeframe: str) -> BasisSnapshot | None:
        stmt = (
            select(BasisSnapshot)
            .where(
                BasisSnapshot.symbol == symbol.upper(),
                BasisSnapshot.timeframe == timeframe,
            )
            .order_by(desc(BasisSnapshot.ts))
            .limit(1)
        )
        return self.db.scalar(stmt)

    def list_range(self, *, symbol: str, timeframe: str, start_ts: datetime, end_ts: datetime) -> list[BasisSnapshot]:
        stmt = (
            select(BasisSnapshot)
            .where(
                BasisSnapshot.symbol == symbol.upper(),
                BasisSnapshot.timeframe == timeframe,
                BasisSnapshot.ts >= start_ts,
                BasisSnapshot.ts <= end_ts,
            )
            .order_by(BasisSnapshot.ts.asc())
        )
        return list(self.db.scalars(stmt))


class LiquidationEventRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, row: LiquidationEvent) -> LiquidationEvent:
        stmt = select(LiquidationEvent).where(
            LiquidationEvent.symbol == row.symbol,
            LiquidationEvent.ts == row.ts,
            LiquidationEvent.side == row.side,
            LiquidationEvent.price == row.price,
            LiquidationEvent.qty == row.qty,
        )
        existing = self.db.scalar(stmt)
        if existing:
            existing.notional = row.notional
            existing.source = row.source
            existing.raw = row.raw
            self.db.add(existing)
            return existing
        self.db.add(row)
        return row

    def list_range(self, *, symbol: str, start_ts: datetime, end_ts: datetime) -> list[LiquidationEvent]:
        stmt = (
            select(LiquidationEvent)
            .where(
                LiquidationEvent.symbol == symbol.upper(),
                LiquidationEvent.ts >= start_ts,
                LiquidationEvent.ts <= end_ts,
            )
            .order_by(LiquidationEvent.ts.asc())
        )
        return list(self.db.scalars(stmt))


class MacroEventRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, row: MacroEvent) -> MacroEvent:
        stmt = select(MacroEvent).where(
            MacroEvent.event_code == row.event_code,
            MacroEvent.event_ts == row.event_ts,
        )
        existing = self.db.scalar(stmt)
        if existing:
            existing.importance = row.importance
            existing.country = row.country
            existing.title = row.title
            existing.source = row.source
            existing.raw = row.raw
            self.db.add(existing)
            return existing
        self.db.add(row)
        return row

    def list_range(self, *, start_ts: datetime, end_ts: datetime) -> list[MacroEvent]:
        stmt = (
            select(MacroEvent)
            .where(
                MacroEvent.event_ts >= start_ts,
                MacroEvent.event_ts <= end_ts,
            )
            .order_by(MacroEvent.event_ts.asc())
        )
        return list(self.db.scalars(stmt))


class CrossAssetBreadthRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, row: CrossAssetBreadthSnapshot) -> CrossAssetBreadthSnapshot:
        stmt = select(CrossAssetBreadthSnapshot).where(
            CrossAssetBreadthSnapshot.leader_symbol == row.leader_symbol,
            CrossAssetBreadthSnapshot.confirm_symbol == row.confirm_symbol,
            CrossAssetBreadthSnapshot.timeframe == row.timeframe,
            CrossAssetBreadthSnapshot.ts == row.ts,
        )
        existing = self.db.scalar(stmt)
        if existing:
            for attr in (
                "leader_close",
                "confirm_close",
                "leader_ret_1h",
                "confirm_ret_1h",
                "leader_ret_4h",
                "confirm_ret_4h",
                "divergence_bps",
                "breadth_score",
                "source",
                "raw",
            ):
                setattr(existing, attr, getattr(row, attr))
            self.db.add(existing)
            return existing
        self.db.add(row)
        return row

    def get_last(self, *, leader_symbol: str, confirm_symbol: str, timeframe: str) -> CrossAssetBreadthSnapshot | None:
        stmt = (
            select(CrossAssetBreadthSnapshot)
            .where(
                CrossAssetBreadthSnapshot.leader_symbol == leader_symbol.upper(),
                CrossAssetBreadthSnapshot.confirm_symbol == confirm_symbol.upper(),
                CrossAssetBreadthSnapshot.timeframe == timeframe,
            )
            .order_by(desc(CrossAssetBreadthSnapshot.ts))
            .limit(1)
        )
        return self.db.scalar(stmt)

    def list_range(
        self,
        *,
        leader_symbol: str | None = None,
        confirm_symbol: str | None = None,
        timeframe: str | None = None,
        start_ts: datetime,
        end_ts: datetime,
    ) -> list[CrossAssetBreadthSnapshot]:
        stmt = select(CrossAssetBreadthSnapshot).where(
            CrossAssetBreadthSnapshot.ts >= start_ts,
            CrossAssetBreadthSnapshot.ts <= end_ts,
        )
        if leader_symbol is not None:
            stmt = stmt.where(CrossAssetBreadthSnapshot.leader_symbol == leader_symbol.upper())
        if confirm_symbol is not None:
            stmt = stmt.where(CrossAssetBreadthSnapshot.confirm_symbol == confirm_symbol.upper())
        if timeframe is not None:
            stmt = stmt.where(CrossAssetBreadthSnapshot.timeframe == timeframe)
        stmt = stmt.order_by(CrossAssetBreadthSnapshot.ts.asc())
        return list(self.db.scalars(stmt))


class ZoneRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert_many(self, zones: Iterable[Zone]) -> None:
        for zone in zones:
            existing = self.db.get(Zone, zone.zone_id)
            if existing:
                for attr in (
                    "low",
                    "high",
                    "mid",
                    "width_atr",
                    "dir_bias",
                    "last_touched_ts",
                    "touch_count",
                    "base_strength",
                    "quality",
                    "state",
                    "merge_group_id",
                    "stats",
                    "strategy_version",
                ):
                    setattr(existing, attr, getattr(zone, attr))
                self.db.add(existing)
            else:
                self.db.add(zone)

    def list_active(self, symbol: str, timeframe: str = "15m") -> list[Zone]:
        stmt = (
            select(Zone)
            .where(
                Zone.symbol == symbol,
                Zone.timeframe == timeframe,
                Zone.state != ZoneState.EXPIRED.value,
            )
            .order_by(desc(Zone.quality), desc(Zone.created_ts))
        )
        return list(self.db.scalars(stmt))

    def list_all(self, symbol: str, timeframe: str = "15m", state: str | None = None) -> list[Zone]:
        stmt = select(Zone).where(Zone.symbol == symbol, Zone.timeframe == timeframe)
        if state:
            stmt = stmt.where(Zone.state == state)
        stmt = stmt.order_by(desc(Zone.quality), desc(Zone.created_ts))
        return list(self.db.scalars(stmt))


class PlanRepository:
    _REPLACEABLE_STATES: ClassVar[set[str]] = {
        PlanState.PLANNED.value,
        PlanState.ARMED.value,
    }
    _ROUTED_SUBMISSION_STATES: ClassVar[set[str]] = {
        "CREATED",
        "SUBMITTED",
        "ACKNOWLEDGED",
        "PARTIALLY_FILLED",
        "FILLED",
    }

    def __init__(self, db: Session):
        self.db = db

    def get(self, plan_id: str) -> Plan | None:
        return self.db.get(Plan, plan_id)

    def _roll_plan_id_for_collision(
        self,
        plan: Plan,
        *,
        previous_plan_id: str,
        existing_state: str,
        collision_artifact: str | None = None,
    ) -> Plan:
        suffix = f"_r{uuid4().hex[:6]}"
        base = str(previous_plan_id or plan.plan_id or "plan")
        max_base_len = max(1, 50 - len(suffix))
        next_plan_id = f"{base[:max_base_len]}{suffix}"
        while self.db.get(Plan, next_plan_id) is not None:
            suffix = f"_r{uuid4().hex[:6]}"
            next_plan_id = f"{base[:max_base_len]}{suffix}"
        validity = dict(plan.validity or {})
        validity["supersedes_plan_id"] = previous_plan_id
        validity["collision_preserved_existing_state"] = str(existing_state or "")
        if collision_artifact:
            validity["collision_preserved_existing_artifact"] = str(collision_artifact)
        plan.plan_id = next_plan_id
        plan.validity = validity
        return plan

    def _existing_plan_has_lifecycle_artifacts(self, plan_id: str) -> str | None:
        fill_stmt = select(ExecutionFill.fill_id).where(ExecutionFill.plan_id == plan_id).limit(1)
        if self.db.scalar(fill_stmt) is not None:
            return "execution_fill"

        submission_stmt = (
            select(OrderSubmission.submission_id)
            .where(
                OrderSubmission.plan_id == plan_id,
                OrderSubmission.adapter != "none",
                OrderSubmission.state.in_(self._ROUTED_SUBMISSION_STATES),
            )
            .limit(1)
        )
        if self.db.scalar(submission_stmt) is not None:
            return "routed_submission"
        return None

    def upsert_many(self, plans: Iterable[Plan]) -> None:
        for plan in plans:
            existing = self.db.get(Plan, plan.plan_id)
            if existing:
                collision_artifact = None
                if str(existing.state or "") in self._REPLACEABLE_STATES:
                    collision_artifact = self._existing_plan_has_lifecycle_artifacts(str(existing.plan_id or ""))
                if str(existing.state or "") not in self._REPLACEABLE_STATES or collision_artifact:
                    self.db.add(
                        self._roll_plan_id_for_collision(
                            plan,
                            previous_plan_id=str(existing.plan_id),
                            existing_state=str(existing.state or ""),
                            collision_artifact=collision_artifact,
                        )
                    )
                    continue
                for attr in (
                    "entry_price",
                    "entry_condition",
                    "sl",
                    "tp1",
                    "tp2",
                    "tp3",
                    "split",
                    "rr_min",
                    "rr_base",
                    "rr_opt",
                    "ev",
                    "cost_est",
                    "confidence",
                    "validity",
                    "state",
                    "valid_from",
                    "valid_until",
                    "strategy_version",
                    "entry_model",
                ):
                    setattr(existing, attr, getattr(plan, attr))
                self.db.add(existing)
            else:
                self.db.add(plan)

    def list_top(self, symbol: str, timeframe: str = "5m", limit: int = 10) -> list[Plan]:
        now = datetime.now(timezone.utc)
        stmt = (
            select(Plan)
            .where(
                Plan.symbol == symbol,
                Plan.timeframe == timeframe,
                Plan.state.in_([PlanState.PLANNED.value, PlanState.ARMED.value]),
                Plan.valid_until > now,
            )
            .order_by(desc(Plan.ev), desc(Plan.confidence), desc(Plan.rr_base))
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def list_active_for_symbol(
        self,
        *,
        symbol: str,
        timeframe: str = "5m",
        states: list[str] | None = None,
        limit: int = 100,
    ) -> list[Plan]:
        now = datetime.now(timezone.utc)
        active_states = states or [PlanState.PLANNED.value, PlanState.ARMED.value]
        stmt = (
            select(Plan)
            .where(
                Plan.symbol == symbol,
                Plan.timeframe == timeframe,
                Plan.state.in_(active_states),
                Plan.valid_until > now,
            )
            .order_by(desc(Plan.ev), desc(Plan.valid_from))
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def count_since(
        self,
        *,
        timeframe: str = "5m",
        start_ts: datetime,
        states: list[str] | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(Plan).where(
            Plan.timeframe == timeframe,
            Plan.valid_from >= start_ts,
        )
        if states is None:
            stmt = stmt.where(Plan.state != PlanState.ARCHIVED.value)
        else:
            stmt = stmt.where(Plan.state.in_(states))
        return int(self.db.scalar(stmt) or 0)

    def list_recent(
        self,
        *,
        symbol: str,
        timeframe: str = "5m",
        days: int = 90,
        limit: int = 5000,
    ) -> list[Plan]:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=max(1, days))
        stmt = (
            select(Plan)
            .where(
                Plan.symbol == symbol,
                Plan.timeframe == timeframe,
                (Plan.valid_from >= cutoff) | (Plan.valid_until >= cutoff),
            )
            .order_by(desc(Plan.valid_from), desc(Plan.ev))
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def list_recent_global(
        self,
        *,
        timeframe: str = "5m",
        days: int = 7,
        states: list[str] | None = None,
        limit: int = 5000,
    ) -> list[Plan]:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=max(1, days))
        stmt = (
            select(Plan)
            .where(
                Plan.timeframe == timeframe,
                (Plan.valid_from >= cutoff) | (Plan.valid_until >= cutoff),
            )
            .order_by(desc(Plan.valid_from), desc(Plan.ev))
            .limit(limit)
        )
        if states is not None:
            stmt = stmt.where(Plan.state.in_(states))
        return list(self.db.scalars(stmt))

    def list_exposure_candidates(
        self,
        *,
        timeframe: str = "5m",
        include_planned: bool = False,
        limit: int = 300,
    ) -> list[Plan]:
        now = datetime.now(timezone.utc)
        states = [
            PlanState.ARMED.value,
            PlanState.TRIGGERED.value,
            PlanState.ENTERED.value,
            PlanState.PARTIAL_EXIT.value,
        ]
        if include_planned:
            states.insert(0, PlanState.PLANNED.value)

        stmt = (
            select(Plan)
            .where(
                Plan.timeframe == timeframe,
                Plan.state.in_(states),
                Plan.valid_until > now,
            )
            .order_by(desc(Plan.valid_from), desc(Plan.ev))
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def invalidate_expired(self) -> int:
        now = datetime.now(timezone.utc)
        stmt = select(Plan).where(
            Plan.valid_until <= now,
            Plan.state.in_([PlanState.PLANNED.value, PlanState.ARMED.value]),
        )
        rows = list(self.db.scalars(stmt))
        for row in rows:
            row.state = PlanState.ARCHIVED.value
            self.db.add(row)
        return len(rows)


class OutcomeRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, outcome: ZoneOutcome) -> ZoneOutcome:
        self.db.add(outcome)
        return outcome

    def list_recent(self, symbol: str, days: int = 90) -> list[ZoneOutcome]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            select(ZoneOutcome)
            .where(ZoneOutcome.symbol == symbol, ZoneOutcome.entry_ts >= cutoff)
            .order_by(desc(ZoneOutcome.entry_ts))
        )
        return list(self.db.scalars(stmt))


class ExecutionFillRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, fill_id: str) -> ExecutionFill | None:
        return self.db.get(ExecutionFill, fill_id)

    def add(self, fill: ExecutionFill) -> ExecutionFill:
        self.db.add(fill)
        return fill

    def list_for_plans(
        self,
        *,
        plan_ids: list[str],
        symbol: str | None = None,
        start_ts: datetime | None = None,
        end_ts: datetime | None = None,
    ) -> list[ExecutionFill]:
        if not plan_ids:
            return []

        stmt = select(ExecutionFill).where(ExecutionFill.plan_id.in_(plan_ids))
        if symbol:
            stmt = stmt.where(ExecutionFill.symbol == symbol)
        if start_ts is not None:
            stmt = stmt.where(ExecutionFill.fill_ts >= start_ts)
        if end_ts is not None:
            stmt = stmt.where(ExecutionFill.fill_ts <= end_ts)
        stmt = stmt.order_by(ExecutionFill.fill_ts.asc(), ExecutionFill.created_at.asc())
        return list(self.db.scalars(stmt))


class BinanceOrderLedgerRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, client_order_id: str) -> BinanceOrderLedger | None:
        return self.db.get(BinanceOrderLedger, client_order_id)

    def get_by_exchange_order_id(self, exchange_order_id: int) -> BinanceOrderLedger | None:
        stmt = (
            select(BinanceOrderLedger)
            .where(BinanceOrderLedger.exchange_order_id == exchange_order_id)
            .order_by(desc(BinanceOrderLedger.updated_at))
            .limit(1)
        )
        return self.db.scalar(stmt)

    def list_recent(self, *, symbol: str | None = None, limit: int = 200) -> list[BinanceOrderLedger]:
        stmt = select(BinanceOrderLedger)
        if symbol:
            stmt = stmt.where(BinanceOrderLedger.symbol == symbol.upper())
        stmt = stmt.order_by(desc(BinanceOrderLedger.updated_at), desc(BinanceOrderLedger.created_at)).limit(limit)
        return list(self.db.scalars(stmt))

    def list_open(self, *, symbol: str | None = None) -> list[BinanceOrderLedger]:
        terminal = {"FILLED", "CANCELED", "CANCELLED", "REJECTED", "EXPIRED"}
        rows = self.list_recent(symbol=symbol, limit=500)
        return [row for row in rows if str(row.status or "").upper() not in terminal]

    def upsert(
        self,
        *,
        client_order_id: str,
        exchange_order_id: int | None,
        plan_id: str | None,
        symbol: str,
        side: str,
        order_type: str,
        status: str,
        reduce_only: bool,
        requested_live: bool,
        live_enabled: bool,
        test_order: bool,
        price: float | None,
        orig_qty: float | None,
        executed_qty: float | None,
        time_in_force: str,
        last_event_type: str | None,
        last_trade_id: int | None,
        last_event_ts: datetime | None,
        raw: dict,
    ) -> BinanceOrderLedger:
        row = self.get(client_order_id)
        if row is None and exchange_order_id is not None:
            row = self.get_by_exchange_order_id(exchange_order_id)
        if row is None:
            row = BinanceOrderLedger(
                client_order_id=client_order_id,
                exchange_order_id=exchange_order_id,
                plan_id=plan_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                status=status,
                reduce_only=reduce_only,
                requested_live=requested_live,
                live_enabled=live_enabled,
                test_order=test_order,
                price=price,
                orig_qty=orig_qty,
                executed_qty=executed_qty,
                time_in_force=time_in_force,
                last_event_type=last_event_type,
                last_trade_id=last_trade_id,
                last_event_ts=last_event_ts,
                raw=raw,
            )
            self.db.add(row)
            return row

        row.exchange_order_id = exchange_order_id or row.exchange_order_id
        row.plan_id = plan_id or row.plan_id
        row.symbol = symbol or row.symbol
        row.side = side or row.side
        row.order_type = order_type or row.order_type
        row.status = status or row.status
        row.reduce_only = bool(reduce_only)
        row.requested_live = bool(requested_live)
        row.live_enabled = bool(live_enabled)
        row.test_order = bool(test_order)
        row.price = price if price is not None else row.price
        row.orig_qty = orig_qty if orig_qty is not None else row.orig_qty
        row.executed_qty = executed_qty if executed_qty is not None else row.executed_qty
        row.time_in_force = time_in_force or row.time_in_force
        row.last_event_type = last_event_type or row.last_event_type
        row.last_trade_id = last_trade_id if last_trade_id is not None else row.last_trade_id
        row.last_event_ts = last_event_ts or row.last_event_ts
        row.raw = raw or row.raw
        self.db.add(row)
        return row


class BinancePositionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, position_key: str) -> BinancePositionSnapshot | None:
        return self.db.get(BinancePositionSnapshot, position_key)

    def upsert_many(self, rows: Iterable[BinancePositionSnapshot]) -> None:
        for row in rows:
            existing = self.get(row.position_key)
            if existing is None:
                self.db.add(row)
                continue
            for attr in (
                "symbol",
                "position_side",
                "position_amt",
                "entry_price",
                "break_even_price",
                "mark_price",
                "liquidation_price",
                "unrealized_pnl",
                "notional",
                "leverage",
                "margin_type",
                "isolated_wallet",
                "update_ts",
                "raw",
            ):
                setattr(existing, attr, getattr(row, attr))
            self.db.add(existing)

    def list_all(self, *, symbol: str | None = None) -> list[BinancePositionSnapshot]:
        stmt = select(BinancePositionSnapshot).order_by(BinancePositionSnapshot.symbol.asc(), BinancePositionSnapshot.position_side.asc())
        if symbol:
            stmt = stmt.where(BinancePositionSnapshot.symbol == symbol.upper())
        return list(self.db.scalars(stmt))

    def list_open(self, *, symbol: str | None = None, min_abs_position: float = 1e-12) -> list[BinancePositionSnapshot]:
        rows = self.list_all(symbol=symbol)
        return [row for row in rows if abs(float(row.position_amt or 0.0)) > min_abs_position]


class OrderIntentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, intent_id: str) -> OrderIntent | None:
        return self.db.get(OrderIntent, intent_id)

    def add(self, row: OrderIntent) -> OrderIntent:
        self.db.add(row)
        return row

    def list_recent(
        self,
        *,
        symbol: str | None = None,
        limit: int = 100,
        days: int | None = None,
    ) -> list[OrderIntent]:
        stmt = select(OrderIntent)
        if symbol:
            stmt = stmt.where(OrderIntent.symbol == symbol.upper())
        if days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
            stmt = stmt.where(OrderIntent.created_at >= cutoff)
        stmt = stmt.order_by(desc(OrderIntent.created_at)).limit(limit)
        return list(self.db.scalars(stmt))

    def latest_for_plan(self, plan_id: str) -> OrderIntent | None:
        stmt = (
            select(OrderIntent)
            .where(OrderIntent.plan_id == plan_id)
            .order_by(desc(OrderIntent.created_at))
            .limit(1)
        )
        return self.db.scalar(stmt)

    def list_for_plan(self, plan_id: str, *, limit: int = 50) -> list[OrderIntent]:
        stmt = (
            select(OrderIntent)
            .where(OrderIntent.plan_id == plan_id)
            .order_by(desc(OrderIntent.created_at))
            .limit(limit)
        )
        return list(self.db.scalars(stmt))


class OrderSubmissionRepository:
    _OPEN_STATES: ClassVar[set[str]] = {
        "CREATED",
        "SUBMITTED",
        "ACKNOWLEDGED",
        "PARTIALLY_FILLED",
    }

    def __init__(self, db: Session):
        self.db = db

    def get(self, submission_id: str) -> OrderSubmission | None:
        return self.db.get(OrderSubmission, submission_id)

    def add(self, row: OrderSubmission) -> OrderSubmission:
        self.db.add(row)
        return row

    def get_by_client_order_id(self, client_order_id: str) -> OrderSubmission | None:
        stmt = (
            select(OrderSubmission)
            .where(OrderSubmission.client_order_id == client_order_id)
            .order_by(desc(OrderSubmission.updated_at), desc(OrderSubmission.submitted_at))
            .limit(1)
        )
        return self.db.scalar(stmt)

    def latest_for_intent(self, intent_id: str) -> OrderSubmission | None:
        stmt = (
            select(OrderSubmission)
            .where(OrderSubmission.intent_id == intent_id)
            .order_by(desc(OrderSubmission.updated_at), desc(OrderSubmission.submitted_at))
            .limit(1)
        )
        return self.db.scalar(stmt)

    def list_for_plan(self, plan_id: str, *, limit: int = 100) -> list[OrderSubmission]:
        stmt = (
            select(OrderSubmission)
            .where(OrderSubmission.plan_id == plan_id)
            .order_by(desc(OrderSubmission.updated_at), desc(OrderSubmission.submitted_at))
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def list_open(self, *, symbol: str | None = None) -> list[OrderSubmission]:
        stmt = (
            select(OrderSubmission)
            .where(OrderSubmission.state.in_(sorted(self._OPEN_STATES)))
            .order_by(desc(OrderSubmission.updated_at), desc(OrderSubmission.submitted_at))
        )
        if symbol:
            stmt = stmt.where(OrderSubmission.symbol == symbol.upper())
        return list(self.db.scalars(stmt))

    def list_recent(
        self,
        *,
        symbol: str | None = None,
        days: int = 90,
        limit: int = 5000,
    ) -> list[OrderSubmission]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
        stmt = select(OrderSubmission).where(OrderSubmission.submitted_at >= cutoff)
        if symbol:
            stmt = stmt.where(OrderSubmission.symbol == symbol.upper())
        stmt = stmt.order_by(desc(OrderSubmission.updated_at), desc(OrderSubmission.submitted_at)).limit(limit)
        return list(self.db.scalars(stmt))

    def transition(
        self,
        row: OrderSubmission,
        *,
        state: str,
        submit_status: str | None = None,
        message: str | None = None,
        raw: dict | None = None,
        attachments: dict | None = None,
        acknowledged_at: datetime | None = None,
        cancelled_at: datetime | None = None,
        exchange_order_id: str | None = None,
    ) -> OrderSubmission:
        row.state = str(state)
        if submit_status is not None:
            row.submit_status = str(submit_status)
        if message is not None:
            row.message = str(message)
        if raw is not None:
            row.raw = dict(raw)
        if attachments is not None:
            row.attachments = dict(attachments)
        if acknowledged_at is not None:
            row.acknowledged_at = acknowledged_at
        if cancelled_at is not None:
            row.cancelled_at = cancelled_at
        if exchange_order_id is not None:
            row.exchange_order_id = exchange_order_id
        self.db.add(row)
        return row


class SafetyLockRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, lock_id: str) -> SafetyLock | None:
        return self.db.get(SafetyLock, lock_id)

    def add(self, row: SafetyLock) -> SafetyLock:
        self.db.add(row)
        return row

    def list_active(self, *, now: datetime | None = None) -> list[SafetyLock]:
        active_now = now or datetime.now(timezone.utc)
        stmt = (
            select(SafetyLock)
            .where(
                SafetyLock.active.is_(True),
                SafetyLock.released_at.is_(None),
            )
            .order_by(desc(SafetyLock.created_at))
        )
        rows = list(self.db.scalars(stmt))
        active_rows: list[SafetyLock] = []
        for row in rows:
            unlock_at = row.unlock_at
            if unlock_at is not None and unlock_at.tzinfo is None:
                unlock_at = unlock_at.replace(tzinfo=timezone.utc)
            elif unlock_at is not None:
                unlock_at = unlock_at.astimezone(timezone.utc)
            if unlock_at is not None and unlock_at <= active_now:
                continue
            active_rows.append(row)
        return active_rows

    def list_scope(self, *, scope_type: str, scope_key: str | None = None, active_only: bool = False) -> list[SafetyLock]:
        stmt = select(SafetyLock).where(SafetyLock.scope_type == scope_type)
        if scope_key is None:
            stmt = stmt.where(SafetyLock.scope_key.is_(None))
        else:
            stmt = stmt.where(SafetyLock.scope_key == scope_key)
        if active_only:
            stmt = stmt.where(SafetyLock.active.is_(True), SafetyLock.released_at.is_(None))
        stmt = stmt.order_by(desc(SafetyLock.created_at))
        return list(self.db.scalars(stmt))

    def release(self, row: SafetyLock, *, released_at: datetime | None = None) -> SafetyLock:
        row.active = False
        row.released_at = released_at or datetime.now(timezone.utc)
        self.db.add(row)
        return row


class FamilyRolloutPolicyRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, family: str) -> FamilyRolloutPolicy | None:
        return self.db.get(FamilyRolloutPolicy, family)

    def upsert(
        self,
        *,
        family: str,
        live_enabled: bool,
        max_execution_mode: str,
        max_risk_r: float,
        allowed_sessions: dict,
        min_quality_score: float,
        updated_by: str | None = None,
        notes: str | None = None,
    ) -> FamilyRolloutPolicy:
        row = self.get(family)
        if row is None:
            row = FamilyRolloutPolicy(family=family)
        row.live_enabled = bool(live_enabled)
        row.max_execution_mode = str(max_execution_mode)
        row.max_risk_r = float(max_risk_r)
        row.allowed_sessions = dict(allowed_sessions or {})
        row.min_quality_score = float(min_quality_score)
        row.updated_by = updated_by
        row.notes = notes
        self.db.add(row)
        return row

    def list_all(self) -> list[FamilyRolloutPolicy]:
        stmt = select(FamilyRolloutPolicy).order_by(FamilyRolloutPolicy.family.asc())
        return list(self.db.scalars(stmt))


class PromotionLifecycleHistoryRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_snapshot_hash(self, snapshot_hash: str) -> PromotionLifecycleHistory | None:
        stmt = select(PromotionLifecycleHistory).where(PromotionLifecycleHistory.snapshot_hash == snapshot_hash)
        return self.db.scalar(stmt)

    def add_if_absent(self, row: PromotionLifecycleHistory) -> PromotionLifecycleHistory:
        existing = self.get_by_snapshot_hash(row.snapshot_hash)
        if existing is not None:
            return existing
        self.db.add(row)
        self.db.flush()
        return row

    def list_recent(
        self,
        *,
        family: str | None = None,
        days: int = 30,
        limit: int = 100,
        now: datetime | None = None,
    ) -> list[PromotionLifecycleHistory]:
        reference_now = now.astimezone(timezone.utc) if now is not None else datetime.now(timezone.utc)
        cutoff = reference_now - timedelta(days=max(1, int(days)))
        stmt = select(PromotionLifecycleHistory).where(PromotionLifecycleHistory.event_ts >= cutoff)
        if family:
            stmt = stmt.where(PromotionLifecycleHistory.family == family)
        stmt = stmt.order_by(desc(PromotionLifecycleHistory.event_ts), desc(PromotionLifecycleHistory.created_at)).limit(limit)
        return list(self.db.scalars(stmt))

    def latest_family(self, family: str) -> PromotionLifecycleHistory | None:
        stmt = (
            select(PromotionLifecycleHistory)
            .where(PromotionLifecycleHistory.family == family)
            .order_by(desc(PromotionLifecycleHistory.event_ts), desc(PromotionLifecycleHistory.created_at))
            .limit(1)
        )
        return self.db.scalar(stmt)


class ExecutionReconciliationEventRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, row: ExecutionReconciliationEvent) -> ExecutionReconciliationEvent:
        self.db.add(row)
        return row

    def list_recent(
        self,
        *,
        symbol: str | None = None,
        limit: int = 100,
        days: int | None = None,
    ) -> list[ExecutionReconciliationEvent]:
        stmt = select(ExecutionReconciliationEvent)
        if symbol:
            stmt = stmt.where(ExecutionReconciliationEvent.symbol == symbol.upper())
        if days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
            stmt = stmt.where(ExecutionReconciliationEvent.created_at >= cutoff)
        stmt = stmt.order_by(desc(ExecutionReconciliationEvent.created_at)).limit(limit)
        return list(self.db.scalars(stmt))


class AlertRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, alert: AlertSubscription) -> AlertSubscription:
        self.db.add(alert)
        return alert

    def list_recent(
        self,
        *,
        days: int = 30,
        limit: int = 5000,
    ) -> list[AlertSubscription]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        stmt = (
            select(AlertSubscription)
            .where(AlertSubscription.triggered_ts >= cutoff)
            .order_by(desc(AlertSubscription.triggered_ts))
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def find_recent(
        self,
        *,
        symbol: str,
        channel: str,
        alert_type: str,
        within_seconds: int,
    ) -> AlertSubscription | None:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(0, within_seconds))
        stmt = (
            select(AlertSubscription)
            .where(
                AlertSubscription.symbol == symbol,
                AlertSubscription.channel == channel,
                AlertSubscription.type == alert_type,
                AlertSubscription.triggered_ts >= cutoff,
            )
            .order_by(desc(AlertSubscription.triggered_ts))
            .limit(1)
        )
        return self.db.scalar(stmt)

    def find_recent_emitted(
        self,
        *,
        symbol: str,
        channel: str,
        alert_type: str,
        plan_id: str | None,
        within_seconds: int,
    ) -> AlertSubscription | None:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(0, within_seconds))
        stmt = (
            select(AlertSubscription)
            .where(
                AlertSubscription.symbol == symbol,
                AlertSubscription.channel == channel,
                AlertSubscription.type == alert_type,
                AlertSubscription.triggered_ts >= cutoff,
            )
            .order_by(desc(AlertSubscription.triggered_ts))
            .limit(20)
        )
        if plan_id is None:
            stmt = stmt.where(AlertSubscription.plan_id.is_(None))
        else:
            stmt = stmt.where(AlertSubscription.plan_id == plan_id)
        rows = list(self.db.scalars(stmt))
        for row in rows:
            if not bool((row.payload or {}).get("subscription_active")):
                return row
        return None

    def list_matching_subscriptions(
        self,
        *,
        symbol: str,
        alert_type: str,
        plan_id: str | None = None,
        limit: int = 500,
    ) -> list[AlertSubscription]:
        stmt = select(AlertSubscription).where(
            AlertSubscription.symbol == symbol,
            AlertSubscription.type == alert_type,
        )
        if plan_id is None:
            stmt = stmt.where(AlertSubscription.plan_id.is_(None))
        else:
            stmt = stmt.where(or_(AlertSubscription.plan_id.is_(None), AlertSubscription.plan_id == plan_id))
        stmt = stmt.order_by(desc(AlertSubscription.triggered_ts)).limit(limit)
        rows = list(self.db.scalars(stmt))
        return [row for row in rows if bool((row.payload or {}).get("subscription_active"))]


class AlertRetryQueueRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, row: AlertRetryTask) -> AlertRetryTask:
        self.db.add(row)
        return row

    def find_open(self, *, dedupe_key: str) -> AlertRetryTask | None:
        stmt = (
            select(AlertRetryTask)
            .where(
                AlertRetryTask.dedupe_key == dedupe_key,
                AlertRetryTask.status == "queued",
            )
            .order_by(desc(AlertRetryTask.created_ts))
            .limit(1)
        )
        return self.db.scalar(stmt)

    def list_due(self, *, limit: int) -> list[AlertRetryTask]:
        now = datetime.now(timezone.utc)
        stmt = (
            select(AlertRetryTask)
            .where(
                AlertRetryTask.status == "queued",
                AlertRetryTask.next_retry_ts <= now,
            )
            .order_by(AlertRetryTask.next_retry_ts.asc(), AlertRetryTask.created_ts.asc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def list_dead_letter(self, *, limit: int) -> list[AlertRetryTask]:
        stmt = (
            select(AlertRetryTask)
            .where(AlertRetryTask.status == "dead_letter")
            .order_by(AlertRetryTask.dead_letter_ts.asc(), AlertRetryTask.created_ts.asc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def mark_delivered(self, row: AlertRetryTask, *, reason: str, status_code: int | None) -> AlertRetryTask:
        row.status = "delivered"
        row.last_reason = reason[:200]
        row.last_status_code = status_code
        row.delivered_ts = datetime.now(timezone.utc)
        self.db.add(row)
        return row

    def reschedule(
        self,
        row: AlertRetryTask,
        *,
        reason: str,
        status_code: int | None,
        next_retry_ts: datetime,
    ) -> AlertRetryTask:
        row.status = "queued"
        row.last_reason = reason[:200]
        row.last_status_code = status_code
        row.next_retry_ts = next_retry_ts
        self.db.add(row)
        return row

    def mark_dead_letter(self, row: AlertRetryTask, *, reason: str, status_code: int | None) -> AlertRetryTask:
        row.status = "dead_letter"
        row.last_reason = reason[:200]
        row.last_status_code = status_code
        row.dead_letter_ts = datetime.now(timezone.utc)
        self.db.add(row)
        return row

    def requeue(self, row: AlertRetryTask, *, next_retry_ts: datetime) -> AlertRetryTask:
        row.status = "queued"
        row.attempts = 0
        row.next_retry_ts = next_retry_ts
        row.dead_letter_ts = None
        self.db.add(row)
        return row

    def increment_attempt(self, row: AlertRetryTask) -> AlertRetryTask:
        row.attempts += 1
        self.db.add(row)
        return row

    def status_counts(self) -> dict[str, int]:
        stmt = select(AlertRetryTask.status, func.count()).group_by(AlertRetryTask.status)
        rows = self.db.execute(stmt).all()
        out: dict[str, int] = {}
        for status, count in rows:
            out[str(status)] = int(count)
        return out

    def oldest_queued(self) -> AlertRetryTask | None:
        stmt = (
            select(AlertRetryTask)
            .where(AlertRetryTask.status == "queued")
            .order_by(AlertRetryTask.created_ts.asc())
            .limit(1)
        )
        return self.db.scalar(stmt)

    def oldest_dead_letter(self) -> AlertRetryTask | None:
        stmt = (
            select(AlertRetryTask)
            .where(AlertRetryTask.status == "dead_letter")
            .order_by(AlertRetryTask.dead_letter_ts.asc(), AlertRetryTask.created_ts.asc())
            .limit(1)
        )
        return self.db.scalar(stmt)


class MetricsRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, symbol: str, version: str, metric: dict) -> StrategyMetric:
        stmt = select(StrategyMetric).where(
            StrategyMetric.symbol == symbol,
            StrategyMetric.version == version,
        )
        row = self.db.scalar(stmt)
        if not row:
            row = StrategyMetric(symbol=symbol, version=version)
        row.win_rate = metric.get("win_rate", 0.0)
        row.avg_win = metric.get("avg_win", 0.0)
        row.avg_loss = metric.get("avg_loss", 0.0)
        row.ev = metric.get("ev", 0.0)
        row.p1r = metric.get("p1r", 0.0)
        row.p2r = metric.get("p2r", 0.0)
        row.p3r = metric.get("p3r", 0.0)
        self.db.add(row)
        return row

    def get(self, symbol: str, version: str) -> StrategyMetric | None:
        stmt = select(StrategyMetric).where(
            StrategyMetric.symbol == symbol,
            StrategyMetric.version == version,
        )
        return self.db.scalar(stmt)

    def count_rows(self, table_name: str) -> int:
        table_map = {
            "candles": Candle,
            "zones": Zone,
            "plans": Plan,
            "zone_outcomes": ZoneOutcome,
            "execution_fills": ExecutionFill,
            "validation_trial_runs": ValidationTrialRun,
            "validation_trial_fold_scores": ValidationTrialFoldScore,
            "validation_pbo_dsr_snapshots": ValidationPboDsrSnapshot,
            "alerts": AlertSubscription,
            "alert_retry_queue": AlertRetryTask,
            "session_impulse_retest_runtime_audits": SessionImpulseRetestRuntimeAudit,
            "event_outbox": EventOutbox,
        }
        model = table_map.get(table_name)
        if model is None:
            return 0
        stmt = select(func.count()).select_from(model)
        return int(self.db.scalar(stmt) or 0)


class SessionImpulseRetestRuntimeAuditRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, row: SessionImpulseRetestRuntimeAudit) -> SessionImpulseRetestRuntimeAudit:
        self.db.add(row)
        return row

    def list_recent(
        self,
        *,
        hours: int = 24,
        symbol: str | None = None,
        phase: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[SessionImpulseRetestRuntimeAudit]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))
        stmt = select(SessionImpulseRetestRuntimeAudit).where(
            SessionImpulseRetestRuntimeAudit.observed_ts >= cutoff
        )
        if symbol:
            stmt = stmt.where(SessionImpulseRetestRuntimeAudit.symbol == symbol.upper())
        if phase:
            stmt = stmt.where(SessionImpulseRetestRuntimeAudit.phase == str(phase))
        if status:
            stmt = stmt.where(SessionImpulseRetestRuntimeAudit.status == str(status))
        stmt = stmt.order_by(desc(SessionImpulseRetestRuntimeAudit.observed_ts)).limit(limit)
        return list(self.db.scalars(stmt))


class ValidationArtifactRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert_trial_run(self, row: ValidationTrialRun) -> ValidationTrialRun:
        existing = self.db.get(ValidationTrialRun, row.trial_run_id)
        if existing:
            for attr in (
                "symbol",
                "strategy_version",
                "parameter_family",
                "parameter_values",
                "selection_rule",
                "selected_flag",
                "selection_rank",
                "in_sample_metric",
                "out_of_sample_metric",
                "sharpe_like_score",
                "trial_count",
                "selection_universe_size",
                "payload",
            ):
                setattr(existing, attr, getattr(row, attr))
            self.db.add(existing)
            return existing
        self.db.add(row)
        return row

    def add_fold_score(self, row: ValidationTrialFoldScore) -> ValidationTrialFoldScore:
        self.db.add(row)
        return row

    def replace_seed(
        self,
        *,
        symbol: str,
        version: str,
        trial_runs: list[ValidationTrialRun],
        fold_scores: list[ValidationTrialFoldScore],
    ) -> dict[str, int]:
        removed_fold_scores = int(
            self.db.execute(
                delete(ValidationTrialFoldScore).where(
                    ValidationTrialFoldScore.symbol == symbol,
                    ValidationTrialFoldScore.strategy_version == version,
                )
            ).rowcount
            or 0
        )
        removed_trial_runs = int(
            self.db.execute(
                delete(ValidationTrialRun).where(
                    ValidationTrialRun.symbol == symbol,
                    ValidationTrialRun.strategy_version == version,
                )
            ).rowcount
            or 0
        )
        for row in trial_runs:
            self.db.add(row)
        for row in fold_scores:
            self.db.add(row)
        return {
            "removed_trial_runs": removed_trial_runs,
            "removed_fold_scores": removed_fold_scores,
            "written_trial_runs": len(trial_runs),
            "written_fold_scores": len(fold_scores),
        }

    def replace_seed_for_selection_rules(
        self,
        *,
        symbol: str,
        version: str,
        selection_rules: list[str],
        trial_runs: list[ValidationTrialRun],
        fold_scores: list[ValidationTrialFoldScore],
    ) -> dict[str, int]:
        normalized_rules = sorted({str(rule) for rule in selection_rules if str(rule)})
        if not normalized_rules:
            return {
                "removed_trial_runs": 0,
                "removed_fold_scores": 0,
                "written_trial_runs": len(trial_runs),
                "written_fold_scores": len(fold_scores),
            }

        existing_trial_ids = list(
            self.db.scalars(
                select(ValidationTrialRun.trial_run_id).where(
                    ValidationTrialRun.symbol == symbol,
                    ValidationTrialRun.strategy_version == version,
                    ValidationTrialRun.selection_rule.in_(normalized_rules),
                )
            )
        )
        removed_fold_scores = 0
        if existing_trial_ids:
            removed_fold_scores = int(
                self.db.execute(
                    delete(ValidationTrialFoldScore).where(
                        ValidationTrialFoldScore.symbol == symbol,
                        ValidationTrialFoldScore.strategy_version == version,
                        ValidationTrialFoldScore.trial_run_id.in_(existing_trial_ids),
                    )
                ).rowcount
                or 0
            )
        removed_trial_runs = int(
            self.db.execute(
                delete(ValidationTrialRun).where(
                    ValidationTrialRun.symbol == symbol,
                    ValidationTrialRun.strategy_version == version,
                    ValidationTrialRun.selection_rule.in_(normalized_rules),
                )
            ).rowcount
            or 0
        )
        for row in trial_runs:
            self.db.add(row)
        for row in fold_scores:
            self.db.add(row)
        return {
            "removed_trial_runs": removed_trial_runs,
            "removed_fold_scores": removed_fold_scores,
            "written_trial_runs": len(trial_runs),
            "written_fold_scores": len(fold_scores),
        }

    def upsert_snapshot(self, row: ValidationPboDsrSnapshot) -> ValidationPboDsrSnapshot:
        existing = self.db.get(ValidationPboDsrSnapshot, row.snapshot_id)
        if existing:
            for attr in (
                "symbol",
                "strategy_version",
                "selected_trial_run_id",
                "trial_run_count",
                "fold_score_count",
                "selection_universe_size",
                "pbo_value",
                "dsr_value",
                "pbo_available",
                "dsr_available",
                "computation_state",
                "payload",
            ):
                setattr(existing, attr, getattr(row, attr))
            self.db.add(existing)
            return existing
        self.db.add(row)
        return row

    def list_trial_runs(
        self,
        *,
        symbol: str,
        version: str,
        selection_rules: list[str] | None = None,
        limit: int = 1000,
    ) -> list[ValidationTrialRun]:
        stmt = (
            select(ValidationTrialRun)
            .where(
                ValidationTrialRun.symbol == symbol,
                ValidationTrialRun.strategy_version == version,
            )
        )
        if selection_rules:
            normalized_rules = [str(rule) for rule in selection_rules if str(rule)]
            if normalized_rules:
                stmt = stmt.where(ValidationTrialRun.selection_rule.in_(normalized_rules))
        stmt = stmt.order_by(desc(ValidationTrialRun.created_at)).limit(limit)
        return list(self.db.scalars(stmt))

    def list_fold_scores(
        self,
        *,
        symbol: str,
        version: str,
        trial_run_id: str | None = None,
        selection_rules: list[str] | None = None,
        limit: int = 5000,
    ) -> list[ValidationTrialFoldScore]:
        stmt = select(ValidationTrialFoldScore).where(
            ValidationTrialFoldScore.symbol == symbol,
            ValidationTrialFoldScore.strategy_version == version,
        )
        if trial_run_id is not None:
            stmt = stmt.where(ValidationTrialFoldScore.trial_run_id == trial_run_id)
        elif selection_rules:
            normalized_rules = [str(rule) for rule in selection_rules if str(rule)]
            if normalized_rules:
                trial_ids_subquery = (
                    select(ValidationTrialRun.trial_run_id)
                    .where(
                        ValidationTrialRun.symbol == symbol,
                        ValidationTrialRun.strategy_version == version,
                        ValidationTrialRun.selection_rule.in_(normalized_rules),
                    )
                )
                stmt = stmt.where(ValidationTrialFoldScore.trial_run_id.in_(trial_ids_subquery))
        stmt = stmt.order_by(
            ValidationTrialFoldScore.created_at.desc(),
            ValidationTrialFoldScore.id.desc(),
        ).limit(limit)
        return list(self.db.scalars(stmt))

    def list_snapshots(
        self,
        *,
        symbol: str,
        version: str,
        limit: int = 100,
    ) -> list[ValidationPboDsrSnapshot]:
        stmt = (
            select(ValidationPboDsrSnapshot)
            .where(
                ValidationPboDsrSnapshot.symbol == symbol,
                ValidationPboDsrSnapshot.strategy_version == version,
            )
            .order_by(desc(ValidationPboDsrSnapshot.created_at))
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def latest_snapshot(self, *, symbol: str, version: str) -> ValidationPboDsrSnapshot | None:
        stmt = (
            select(ValidationPboDsrSnapshot)
            .where(
                ValidationPboDsrSnapshot.symbol == symbol,
                ValidationPboDsrSnapshot.strategy_version == version,
            )
            .order_by(desc(ValidationPboDsrSnapshot.created_at))
            .limit(1)
        )
        return self.db.scalar(stmt)

    def counts(self, *, symbol: str, version: str) -> dict[str, int]:
        return {
            "trial_runs": int(
                self.db.scalar(
                    select(func.count()).select_from(ValidationTrialRun).where(
                        ValidationTrialRun.symbol == symbol,
                        ValidationTrialRun.strategy_version == version,
                    )
                )
                or 0
            ),
            "fold_scores": int(
                self.db.scalar(
                    select(func.count()).select_from(ValidationTrialFoldScore).where(
                        ValidationTrialFoldScore.symbol == symbol,
                        ValidationTrialFoldScore.strategy_version == version,
                    )
                )
                or 0
            ),
            "snapshots": int(
                self.db.scalar(
                    select(func.count()).select_from(ValidationPboDsrSnapshot).where(
                        ValidationPboDsrSnapshot.symbol == symbol,
                        ValidationPboDsrSnapshot.strategy_version == version,
                    )
                )
                or 0
            ),
        }

    def selection_rule_counts(self, *, symbol: str, version: str) -> dict[str, int]:
        stmt = (
            select(ValidationTrialRun.selection_rule, func.count())
            .where(
                ValidationTrialRun.symbol == symbol,
                ValidationTrialRun.strategy_version == version,
            )
            .group_by(ValidationTrialRun.selection_rule)
        )
        rows = self.db.execute(stmt).all()
        return {
            str(selection_rule or ""): int(count or 0)
            for selection_rule, count in rows
            if str(selection_rule or "")
        }


class EventOutboxRepository:
    def __init__(self, db: Session):
        self.db = db

    def find_recent_by_dedupe_key(self, dedupe_key: str, within_seconds: int) -> EventOutbox | None:
        stmt = (
            select(EventOutbox)
            .where(
                EventOutbox.dedupe_key == dedupe_key,
                EventOutbox.status.in_(
                    [
                        EventStatus.PENDING.value,
                        EventStatus.PUBLISHED.value,
                        EventStatus.FAILED.value,
                    ]
                ),
            )
            .order_by(desc(EventOutbox.created_ts))
            .limit(1)
        )
        row = self.db.scalar(stmt)
        if not row:
            return None

        created = row.created_ts
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=within_seconds)
        if created < cutoff:
            return None
        return row

    def add(self, row: EventOutbox) -> EventOutbox:
        self.db.add(row)
        return row

    def mark_duplicate(self, row: EventOutbox) -> EventOutbox:
        row.status = EventStatus.DUPLICATE.value
        self.db.add(row)
        return row

    def mark_skipped_late(self, row: EventOutbox) -> EventOutbox:
        row.status = EventStatus.SKIPPED_LATE.value
        self.db.add(row)
        return row

    def mark_published(self, row: EventOutbox) -> EventOutbox:
        row.status = EventStatus.PUBLISHED.value
        row.published_ts = datetime.now(timezone.utc)
        row.last_error = None
        self.db.add(row)
        return row

    def mark_failed(self, row: EventOutbox, error: str, retry_after_seconds: int) -> EventOutbox:
        row.status = EventStatus.FAILED.value
        row.last_error = error[:500]
        row.next_retry_ts = datetime.now(timezone.utc) + timedelta(seconds=retry_after_seconds)
        self.db.add(row)
        return row

    def increment_attempt(self, row: EventOutbox) -> EventOutbox:
        row.attempts += 1
        self.db.add(row)
        return row

    def list_reprocessable(self, limit: int, max_attempts: int) -> list[EventOutbox]:
        now = datetime.now(timezone.utc)
        stmt = (
            select(EventOutbox)
            .where(
                EventOutbox.status.in_([EventStatus.PENDING.value, EventStatus.FAILED.value]),
                EventOutbox.attempts < max_attempts,
                (EventOutbox.next_retry_ts.is_(None) | (EventOutbox.next_retry_ts <= now)),
            )
            .order_by(EventOutbox.created_ts.asc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def status_counts(self) -> dict[str, int]:
        stmt = (
            select(EventOutbox.status, func.count())
            .group_by(EventOutbox.status)
        )
        rows = self.db.execute(stmt).all()
        out: dict[str, int] = {}
        for status, count in rows:
            out[str(status)] = int(count)
        return out
