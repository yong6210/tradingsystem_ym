from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import Settings, get_settings
from app.core.enums import PlanState, RiskGateState, StrategyMode
from app.db.models import Plan


@dataclass(slots=True)
class ClosedTradeSnapshot:
    plan_id: str
    symbol: str
    closed_ts: datetime
    realized_r: float
    strategy_grade: str | None
    exit_reason: str | None


@dataclass(slots=True)
class SessionWindow:
    name: str
    start: datetime
    end: datetime
    active: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "active": self.active,
        }


@dataclass(slots=True)
class OperatingLockSnapshot:
    state: RiskGateState
    active: bool
    enforced: bool
    reason: str
    scope: str
    strategy_mode: str
    unlock_at: str | None
    current_session: dict[str, Any]
    daily_stats: dict[str, Any]
    session_stats: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "active": self.active,
            "enforced": self.enforced,
            "reason": self.reason,
            "scope": self.scope,
            "strategy_mode": self.strategy_mode,
            "unlock_at": self.unlock_at,
            "current_session": self.current_session,
            "daily_stats": self.daily_stats,
            "session_stats": self.session_stats,
        }


class OperatingLockService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _mode_value(mode: StrategyMode | str | None) -> StrategyMode:
        if isinstance(mode, StrategyMode):
            return mode
        try:
            return StrategyMode(str(mode))
        except ValueError:
            return StrategyMode.A_ONLY

    def _current_mode(self, mode: StrategyMode | str | None = None) -> StrategyMode:
        if mode is not None:
            return self._mode_value(mode)
        return self._mode_value(getattr(self.settings, "strategy_mode", StrategyMode.A_ONLY))

    def current_session(self, *, now: datetime) -> SessionWindow:
        now = self._utc(now)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        london_start = day_start + timedelta(hours=int(self.settings.trading_session_london_start_hour_utc))
        london_end = day_start + timedelta(hours=int(self.settings.trading_session_london_end_hour_utc))
        if london_start <= now < london_end:
            return SessionWindow(name="london", start=london_start, end=london_end, active=True)

        ny_start = day_start + timedelta(hours=int(self.settings.trading_session_new_york_start_hour_utc))
        ny_end = day_start + timedelta(hours=int(self.settings.trading_session_new_york_end_hour_utc))
        if ny_start <= now < ny_end:
            return SessionWindow(name="new_york", start=ny_start, end=ny_end, active=True)

        return SessionWindow(name="inactive", start=now, end=now, active=False)

    @staticmethod
    def _parse_closed_trade(plan: Plan) -> ClosedTradeSnapshot | None:
        if str(plan.state) != PlanState.CLOSED.value:
            return None
        validity = dict(plan.validity or {})
        closed_ts_raw = validity.get("final_exit_ts") or validity.get("last_exit_ts")
        if not closed_ts_raw:
            return None
        try:
            closed_ts = datetime.fromisoformat(str(closed_ts_raw).replace("Z", "+00:00"))
        except ValueError:
            return None
        if closed_ts.tzinfo is None:
            closed_ts = closed_ts.replace(tzinfo=timezone.utc)
        else:
            closed_ts = closed_ts.astimezone(timezone.utc)

        realized_r_raw = validity.get("final_exit_realized_r")
        if realized_r_raw is None:
            return None
        try:
            realized_r = float(realized_r_raw)
        except (TypeError, ValueError):
            return None

        grade = validity.get("strategy_grade")
        exit_reason = validity.get("final_exit_reason")
        return ClosedTradeSnapshot(
            plan_id=plan.plan_id,
            symbol=plan.symbol,
            closed_ts=closed_ts,
            realized_r=realized_r,
            strategy_grade=str(grade) if grade else None,
            exit_reason=str(exit_reason) if exit_reason else None,
        )

    @staticmethod
    def _loss_streak(trades: list[ClosedTradeSnapshot]) -> int:
        streak = 0
        for trade in reversed(trades):
            if trade.realized_r < 0.0:
                streak += 1
                continue
            break
        return streak

    @staticmethod
    def _a_grade_loss_streak(trades: list[ClosedTradeSnapshot]) -> int:
        streak = 0
        for trade in reversed(trades):
            if trade.strategy_grade == "A" and trade.realized_r < 0.0:
                streak += 1
                continue
            break
        return streak

    @staticmethod
    def _trade_dict(trade: ClosedTradeSnapshot | None) -> dict[str, Any] | None:
        if trade is None:
            return None
        return {
            "plan_id": trade.plan_id,
            "symbol": trade.symbol,
            "closed_ts": trade.closed_ts.isoformat(),
            "realized_r": round(trade.realized_r, 4),
            "strategy_grade": trade.strategy_grade,
            "exit_reason": trade.exit_reason,
        }

    def evaluate(
        self,
        *,
        plans: list[Plan],
        now: datetime | None = None,
        mode: StrategyMode | str | None = None,
    ) -> OperatingLockSnapshot:
        now = self._utc(now or datetime.now(timezone.utc))
        active_mode = self._current_mode(mode)
        session = self.current_session(now=now)

        closed_trades = [trade for trade in (self._parse_closed_trade(plan) for plan in plans) if trade is not None]
        closed_trades.sort(key=lambda item: item.closed_ts)

        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        next_day = day_start + timedelta(days=1)
        daily_trades = [trade for trade in closed_trades if day_start <= trade.closed_ts <= now]
        session_trades = (
            [trade for trade in closed_trades if session.start <= trade.closed_ts <= now]
            if session.active
            else []
        )

        daily_realized_r = round(sum(trade.realized_r for trade in daily_trades), 4)
        session_realized_r = round(sum(trade.realized_r for trade in session_trades), 4)
        daily_loss_streak = self._loss_streak(daily_trades)
        daily_a_loss_streak = self._a_grade_loss_streak(daily_trades)
        session_loss_streak = self._loss_streak(session_trades)

        daily_stats = {
            "trades": len(daily_trades),
            "realized_r": daily_realized_r,
            "loss_streak": int(daily_loss_streak),
            "a_grade_loss_streak": int(daily_a_loss_streak),
            "last_trade": self._trade_dict(daily_trades[-1] if daily_trades else None),
            "loss_limit_r": float(self.settings.operating_lock_daily_loss_limit_r),
        }
        session_stats = {
            "trades": len(session_trades),
            "realized_r": session_realized_r,
            "loss_streak": int(session_loss_streak),
            "last_trade": self._trade_dict(session_trades[-1] if session_trades else None),
            "loss_limit_r": float(self.settings.operating_lock_session_loss_limit_r),
        }

        enforced = active_mode != StrategyMode.RESEARCH
        if not enforced:
            return OperatingLockSnapshot(
                state=RiskGateState.OPEN,
                active=False,
                enforced=False,
                reason="research_mode_shadow_only",
                scope="none",
                strategy_mode=active_mode.value,
                unlock_at=None,
                current_session=session.to_dict(),
                daily_stats=daily_stats,
                session_stats=session_stats,
            )

        if daily_realized_r <= float(self.settings.operating_lock_daily_loss_limit_r):
            return OperatingLockSnapshot(
                state=RiskGateState.CLOSED,
                active=True,
                enforced=True,
                reason="daily_loss_limit_reached",
                scope="daily",
                strategy_mode=active_mode.value,
                unlock_at=next_day.isoformat(),
                current_session=session.to_dict(),
                daily_stats=daily_stats,
                session_stats=session_stats,
            )
        if daily_loss_streak >= int(self.settings.operating_lock_daily_consecutive_losses):
            return OperatingLockSnapshot(
                state=RiskGateState.CLOSED,
                active=True,
                enforced=True,
                reason="daily_consecutive_losses_reached",
                scope="daily",
                strategy_mode=active_mode.value,
                unlock_at=next_day.isoformat(),
                current_session=session.to_dict(),
                daily_stats=daily_stats,
                session_stats=session_stats,
            )
        if daily_a_loss_streak >= int(self.settings.operating_lock_daily_a_grade_failures):
            return OperatingLockSnapshot(
                state=RiskGateState.CLOSED,
                active=True,
                enforced=True,
                reason="daily_a_grade_failures_reached",
                scope="daily",
                strategy_mode=active_mode.value,
                unlock_at=next_day.isoformat(),
                current_session=session.to_dict(),
                daily_stats=daily_stats,
                session_stats=session_stats,
            )

        if session.active:
            unlock_at = session.end.isoformat()
            if session_realized_r <= float(self.settings.operating_lock_session_loss_limit_r):
                return OperatingLockSnapshot(
                    state=RiskGateState.CLOSED,
                    active=True,
                    enforced=True,
                    reason="session_loss_limit_reached",
                    scope="session",
                    strategy_mode=active_mode.value,
                    unlock_at=unlock_at,
                    current_session=session.to_dict(),
                    daily_stats=daily_stats,
                    session_stats=session_stats,
                )
            if session_loss_streak >= int(self.settings.operating_lock_session_consecutive_losses):
                return OperatingLockSnapshot(
                    state=RiskGateState.CLOSED,
                    active=True,
                    enforced=True,
                    reason="session_consecutive_losses_reached",
                    scope="session",
                    strategy_mode=active_mode.value,
                    unlock_at=unlock_at,
                    current_session=session.to_dict(),
                    daily_stats=daily_stats,
                    session_stats=session_stats,
                )

        return OperatingLockSnapshot(
            state=RiskGateState.OPEN,
            active=False,
            enforced=True,
            reason="normal",
            scope="none",
            strategy_mode=active_mode.value,
            unlock_at=None,
            current_session=session.to_dict(),
            daily_stats=daily_stats,
            session_stats=session_stats,
        )
