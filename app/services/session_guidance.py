from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import Settings, get_settings
from app.core.enums import StrategyMode
from app.services.operating_lock import OperatingLockService, OperatingLockSnapshot


class SessionGuidanceService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.operating_lock = OperatingLockService(self.settings)

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _mode_value(self, mode: StrategyMode | str | None) -> str:
        if isinstance(mode, StrategyMode):
            return mode.value
        if mode is None:
            current = getattr(self.settings, "strategy_mode", StrategyMode.A_ONLY)
            return current.value if isinstance(current, StrategyMode) else str(current)
        return str(mode)

    def session_windows(self, *, now: datetime) -> dict[str, dict[str, Any]]:
        current = self._utc(now)
        day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        london_start = day_start + timedelta(hours=int(self.settings.trading_session_london_start_hour_utc))
        london_end = day_start + timedelta(hours=int(self.settings.trading_session_london_end_hour_utc))
        new_york_start = day_start + timedelta(hours=int(self.settings.trading_session_new_york_start_hour_utc))
        new_york_end = day_start + timedelta(hours=int(self.settings.trading_session_new_york_end_hour_utc))
        overlap_start = max(london_start, new_york_start)
        overlap_end = min(london_end, new_york_end)
        overlap_defined = overlap_start < overlap_end
        return {
            "london": {
                "start": london_start.isoformat(),
                "end": london_end.isoformat(),
                "active": london_start <= current < london_end,
            },
            "new_york": {
                "start": new_york_start.isoformat(),
                "end": new_york_end.isoformat(),
                "active": new_york_start <= current < new_york_end,
            },
            "overlap": {
                "start": overlap_start.isoformat(),
                "end": overlap_end.isoformat(),
                "defined": overlap_defined,
                "active": overlap_defined and overlap_start <= current < overlap_end,
            },
        }

    def snapshot(
        self,
        *,
        operating_lock: OperatingLockSnapshot | dict[str, Any] | None = None,
        strategy_mode: StrategyMode | str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current_now = self._utc(now or datetime.now(timezone.utc))
        if isinstance(operating_lock, OperatingLockSnapshot):
            lock_payload = operating_lock.to_dict()
        else:
            lock_payload = dict(operating_lock or {})

        current_session = dict(lock_payload.get("current_session") or {})
        if not current_session:
            current_session = self.operating_lock.current_session(now=current_now).to_dict()

        session_name = str(current_session.get("name", "inactive"))
        session_active = bool(current_session.get("active"))
        dead_session = (not session_active) or session_name == "inactive"
        session_lock_active = bool(lock_payload.get("active")) and str(lock_payload.get("scope")) == "session"
        preferred_sessions = ["london", "new_york", "overlap"]

        if dead_session:
            state = "dead_session"
            status = "WARN"
            summary = "current window is dead session; live entries are guidance-only discouraged"
            soft_penalty = float(self.settings.session_guidance_penalty_dead_session)
        elif session_lock_active:
            state = "session_lock_active"
            status = "WARN"
            summary = (
                f"{session_name} session is active, but session lock is currently active until "
                f"{lock_payload.get('unlock_at', 'session_end')}"
            )
            soft_penalty = float(self.settings.session_guidance_penalty_session_lock)
        else:
            state = "preferred_live_window"
            status = "PASS"
            summary = f"{session_name} session is within preferred live window"
            soft_penalty = 0.0

        return {
            "state": state,
            "status": status,
            "summary": summary,
            "strategy_mode": self._mode_value(strategy_mode),
            "current_session": current_session,
            "dead_session": dead_session,
            "session_lock_active": session_lock_active,
            "preferred_sessions": preferred_sessions,
            "preferred_windows_utc": self.session_windows(now=current_now),
            "soft_penalty": round(soft_penalty, 4),
            "unlock_at": lock_payload.get("unlock_at"),
            "engine_dead_session_hard_block": False,
            "routing_policy": "guidance_only_soft_penalty",
        }
