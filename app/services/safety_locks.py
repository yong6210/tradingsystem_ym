from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.enums import LockScopeType, LockSeverity
from app.db.models import SafetyLock
from app.repositories.execution import SafetyLockRepository

_SEVERITY_RANK = {
    LockSeverity.INFO: 0,
    LockSeverity.WARNING: 1,
    LockSeverity.CRITICAL: 2,
}


class SafetyLockService:
    KILL_SWITCH_REASON = "kill_switch_active"
    CLOSE_ONLY_REASON = "close_only_active"
    TRANSITION_EDGE_VARIANT_DISABLED_REASON = "transition_edge_variant_disabled"

    def __init__(self, *, repo: SafetyLockRepository, settings: Settings | None = None):
        self.repo = repo
        self.settings = settings or get_settings()

    @staticmethod
    def _utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _scope_type(value: LockScopeType | str) -> LockScopeType:
        return value if isinstance(value, LockScopeType) else LockScopeType(str(value).upper())

    @staticmethod
    def _severity(value: LockSeverity | str) -> LockSeverity:
        if isinstance(value, LockSeverity):
            return value
        try:
            return LockSeverity(str(value).upper())
        except ValueError:
            return LockSeverity.WARNING

    @classmethod
    def _normalize_scope_key(cls, scope_type: LockScopeType, scope_key: str | None) -> str | None:
        if scope_type == LockScopeType.GLOBAL:
            return None
        if scope_key is None:
            return None
        text = str(scope_key).strip()
        if not text:
            return None
        if scope_type == LockScopeType.SYMBOL:
            return text.upper()
        return text.lower()

    @classmethod
    def _serialize_lock(cls, row: SafetyLock) -> dict[str, Any]:
        return {
            "lock_id": row.lock_id,
            "scope_type": row.scope_type,
            "scope_key": row.scope_key,
            "severity": row.severity,
            "reason_code": row.reason_code,
            "reason_message": row.reason_message,
            "active": bool(row.active),
            "allow_closes": bool(row.allow_closes),
            "lock_metadata": dict(row.lock_metadata or {}),
            "unlock_at": cls._utc(row.unlock_at),
            "released_at": cls._utc(row.released_at),
            "created_at": cls._utc(row.created_at),
            "updated_at": cls._utc(row.updated_at),
        }

    @staticmethod
    def _reason_priority(reason_code: str) -> int:
        if reason_code == SafetyLockService.KILL_SWITCH_REASON:
            return 30
        if reason_code == SafetyLockService.CLOSE_ONLY_REASON:
            return 20
        if reason_code.startswith("reconciliation_"):
            return 10
        return 0

    def list_active(self, *, now: datetime | None = None) -> list[SafetyLock]:
        return self.repo.list_active(now=now)

    def _matching_locks(
        self,
        *,
        symbol: str | None,
        family: str | None,
        session_name: str | None,
        now: datetime | None = None,
    ) -> list[SafetyLock]:
        symbol_key = self._normalize_scope_key(LockScopeType.SYMBOL, symbol)
        family_key = self._normalize_scope_key(LockScopeType.FAMILY, family)
        session_key = self._normalize_scope_key(LockScopeType.SESSION, session_name)
        matched: list[SafetyLock] = []
        for row in self.list_active(now=now):
            scope_type = self._scope_type(row.scope_type)
            scope_key = self._normalize_scope_key(scope_type, row.scope_key)
            if scope_type == LockScopeType.GLOBAL:
                matched.append(row)
            elif scope_type == LockScopeType.SYMBOL and scope_key == symbol_key:
                matched.append(row)
            elif scope_type == LockScopeType.FAMILY and scope_key == family_key:
                matched.append(row)
            elif scope_type == LockScopeType.SESSION and scope_key == session_key:
                matched.append(row)
        matched.sort(
            key=lambda row: (
                -_SEVERITY_RANK[self._severity(row.severity)],
                -self._reason_priority(str(row.reason_code or "")),
                self._utc(row.created_at) or datetime.min.replace(tzinfo=timezone.utc),
            )
        )
        return matched

    def set_lock(
        self,
        *,
        scope_type: LockScopeType | str,
        scope_key: str | None = None,
        severity: LockSeverity | str = LockSeverity.WARNING,
        reason_code: str,
        reason_message: str,
        allow_closes: bool = True,
        unlock_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SafetyLock:
        normalized_scope_type = self._scope_type(scope_type)
        normalized_scope_key = self._normalize_scope_key(normalized_scope_type, scope_key)
        normalized_reason = str(reason_code or "").strip() or "manual_lock"
        existing = None
        for row in self.repo.list_scope(
            scope_type=normalized_scope_type.value,
            scope_key=normalized_scope_key,
            active_only=True,
        ):
            if str(row.reason_code or "") == normalized_reason:
                existing = row
                break

        target = existing or SafetyLock(
            lock_id=f"lock_{uuid4().hex[:20]}",
            scope_type=normalized_scope_type.value,
            scope_key=normalized_scope_key,
            severity=self._severity(severity).value,
            reason_code=normalized_reason,
            reason_message=str(reason_message or normalized_reason),
            active=True,
            allow_closes=bool(allow_closes),
            lock_metadata=dict(metadata or {}),
            unlock_at=self._utc(unlock_at),
            released_at=None,
        )
        target.scope_type = normalized_scope_type.value
        target.scope_key = normalized_scope_key
        target.severity = self._severity(severity).value
        target.reason_code = normalized_reason
        target.reason_message = str(reason_message or normalized_reason)
        target.active = True
        target.allow_closes = bool(allow_closes)
        target.lock_metadata = dict(metadata or {})
        target.unlock_at = self._utc(unlock_at)
        target.released_at = None
        self.repo.add(target)
        self.repo.db.flush()
        return target

    def release_lock(self, *, lock_id: str) -> SafetyLock | None:
        row = self.repo.get(lock_id)
        if row is None:
            return None
        released = self.repo.release(row)
        self.repo.db.flush()
        return released

    def release_reason(
        self,
        *,
        scope_type: LockScopeType | str,
        scope_key: str | None = None,
        reason_code: str | None = None,
    ) -> list[SafetyLock]:
        normalized_scope_type = self._scope_type(scope_type)
        normalized_scope_key = self._normalize_scope_key(normalized_scope_type, scope_key)
        released: list[SafetyLock] = []
        for row in self.repo.list_scope(
            scope_type=normalized_scope_type.value,
            scope_key=normalized_scope_key,
            active_only=True,
        ):
            if reason_code and str(row.reason_code or "") != reason_code:
                continue
            released.append(self.repo.release(row))
        self.repo.db.flush()
        return released

    def set_kill_switch(
        self,
        *,
        active: bool,
        reason_message: str,
        unlock_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[SafetyLock]:
        if active:
            return [
                self.set_lock(
                    scope_type=LockScopeType.GLOBAL,
                    severity=LockSeverity.CRITICAL,
                    reason_code=self.KILL_SWITCH_REASON,
                    reason_message=reason_message,
                    allow_closes=True,
                    unlock_at=unlock_at,
                    metadata=metadata,
                )
            ]
        return self.release_reason(scope_type=LockScopeType.GLOBAL, reason_code=self.KILL_SWITCH_REASON)

    def set_close_only(
        self,
        *,
        active: bool,
        reason_message: str,
        unlock_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[SafetyLock]:
        if active:
            return [
                self.set_lock(
                    scope_type=LockScopeType.GLOBAL,
                    severity=LockSeverity.WARNING,
                    reason_code=self.CLOSE_ONLY_REASON,
                    reason_message=reason_message,
                    allow_closes=True,
                    unlock_at=unlock_at,
                    metadata=metadata,
                )
            ]
        return self.release_reason(scope_type=LockScopeType.GLOBAL, reason_code=self.CLOSE_ONLY_REASON)

    def set_transition_edge_variant_disabled(
        self,
        *,
        active: bool,
        family: str = "sweep_reversal",
        reason_message: str,
        unlock_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[SafetyLock]:
        scope_key = self._normalize_scope_key(LockScopeType.FAMILY, family)
        if active:
            return [
                self.set_lock(
                    scope_type=LockScopeType.FAMILY,
                    scope_key=scope_key,
                    severity=LockSeverity.WARNING,
                    reason_code=self.TRANSITION_EDGE_VARIANT_DISABLED_REASON,
                    reason_message=reason_message,
                    allow_closes=True,
                    unlock_at=unlock_at,
                    metadata=metadata,
                )
            ]
        return self.release_reason(
            scope_type=LockScopeType.FAMILY,
            scope_key=scope_key,
            reason_code=self.TRANSITION_EDGE_VARIANT_DISABLED_REASON,
        )

    def safety_state(
        self,
        *,
        symbol: str | None = None,
        family: str | None = None,
        session_name: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        active_locks = self.list_active(now=now)
        matching_locks = self._matching_locks(symbol=symbol, family=family, session_name=session_name, now=now)
        transition_edge_variant_matching_locks = [
            row for row in matching_locks if str(row.reason_code or "") == self.TRANSITION_EDGE_VARIANT_DISABLED_REASON
        ]
        blocking_matching_locks = [
            row for row in matching_locks if str(row.reason_code or "") != self.TRANSITION_EDGE_VARIANT_DISABLED_REASON
        ]
        config_close_only = bool(self.settings.auto_trading_close_only)
        kill_switch_active = any(str(row.reason_code or "") == self.KILL_SWITCH_REASON for row in active_locks)
        close_only_active = any(str(row.reason_code or "") == self.CLOSE_ONLY_REASON for row in active_locks)
        transition_edge_variant_disabled_active = bool(transition_edge_variant_matching_locks)

        blocking_reason_code = ""
        blocking_reason_message = ""
        new_entry_allowed = True
        if config_close_only:
            new_entry_allowed = False
            blocking_reason_code = "close_only_mode"
            blocking_reason_message = "Static close-only mode is enabled in settings."
        elif blocking_matching_locks:
            top = blocking_matching_locks[0]
            new_entry_allowed = False
            blocking_reason_code = str(top.reason_code or "safety_lock_active")
            blocking_reason_message = str(top.reason_message or "A safety lock blocks new entries.")

        return {
            "symbol": self._normalize_scope_key(LockScopeType.SYMBOL, symbol),
            "strategy_family": self._normalize_scope_key(LockScopeType.FAMILY, family),
            "session_name": self._normalize_scope_key(LockScopeType.SESSION, session_name),
            "new_entry_allowed": bool(new_entry_allowed),
            "blocking_reason_code": blocking_reason_code,
            "blocking_reason_message": blocking_reason_message,
            "kill_switch_active": kill_switch_active,
            "close_only_active": close_only_active,
            "config_close_only_active": config_close_only,
            "transition_edge_variant_disabled_active": transition_edge_variant_disabled_active,
            "transition_edge_variant_matching_locks": [self._serialize_lock(row) for row in transition_edge_variant_matching_locks],
            "matching_locks": [self._serialize_lock(row) for row in matching_locks],
            "active_locks": [self._serialize_lock(row) for row in active_locks],
        }
