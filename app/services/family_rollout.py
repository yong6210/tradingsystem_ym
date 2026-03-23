from __future__ import annotations

from typing import Any

from app.core.enums import ExecutionMode
from app.repositories.execution import FamilyRolloutPolicyRepository
from app.domain.execution import RolloutPolicy


class RolloutPolicyBootstrap:
    _DEFAULTS: dict[str, RolloutPolicy] = {
        "trend_continuation": RolloutPolicy(
            strategy_family="trend_continuation",
            live_enabled=True,
            max_execution_mode=ExecutionMode.MICRO_LIVE,
            max_risk_r=1.0,
            allowed_sessions=("london", "new_york"),
            min_quality_score=75.0,
        ),
        "sweep_reversal": RolloutPolicy(
            strategy_family="sweep_reversal",
            live_enabled=False,
            max_execution_mode=ExecutionMode.PAPER,
            max_risk_r=0.5,
            allowed_sessions=("london", "new_york"),
            min_quality_score=70.0,
        ),
        "range_rotation": RolloutPolicy(
            strategy_family="range_rotation",
            live_enabled=False,
            max_execution_mode=ExecutionMode.SHADOW,
            max_risk_r=0.25,
            allowed_sessions=("london", "new_york"),
            min_quality_score=68.0,
        ),
    }

    _FALLBACK = RolloutPolicy(
        strategy_family="legacy_zone_plan",
        live_enabled=False,
        max_execution_mode=ExecutionMode.SHADOW,
        max_risk_r=0.0,
        allowed_sessions=(),
        min_quality_score=0.0,
    )

    def get(self, strategy_family: str | None) -> RolloutPolicy:
        family = str(strategy_family or "legacy_zone_plan").strip().lower()
        if family in self._DEFAULTS:
            return self._DEFAULTS[family]
        return RolloutPolicy(
            strategy_family=family or self._FALLBACK.strategy_family,
            live_enabled=self._FALLBACK.live_enabled,
            max_execution_mode=self._FALLBACK.max_execution_mode,
            max_risk_r=self._FALLBACK.max_risk_r,
            allowed_sessions=self._FALLBACK.allowed_sessions,
            min_quality_score=self._FALLBACK.min_quality_score,
        )

    def list_all(self) -> list[RolloutPolicy]:
        return [self._DEFAULTS[key] for key in sorted(self._DEFAULTS)]


class RolloutPolicyService:
    def __init__(
        self,
        *,
        repo: FamilyRolloutPolicyRepository,
        bootstrap: RolloutPolicyBootstrap | None = None,
    ):
        self.repo = repo
        self.bootstrap = bootstrap or RolloutPolicyBootstrap()

    @staticmethod
    def _coerce_mode(value: Any) -> ExecutionMode:
        try:
            return value if isinstance(value, ExecutionMode) else ExecutionMode(str(value).upper())
        except ValueError:
            return ExecutionMode.SHADOW

    @staticmethod
    def _normalize_sessions(value: Any) -> tuple[str, ...]:
        if isinstance(value, dict):
            raw = value.get("items") or value.get("sessions") or []
        elif isinstance(value, (list, tuple, set)):
            raw = value
        else:
            raw = []
        sessions = []
        for item in raw:
            text = str(item or "").strip().lower()
            if text and text not in sessions:
                sessions.append(text)
        return tuple(sessions)

    @staticmethod
    def _serialize_sessions(value: list[str] | tuple[str, ...]) -> dict[str, list[str]]:
        return {"items": [str(item or "").strip().lower() for item in value if str(item or "").strip()]}

    def _from_row(self, row: Any) -> RolloutPolicy:
        return RolloutPolicy(
            strategy_family=str(row.family or "legacy_zone_plan").lower(),
            live_enabled=bool(row.live_enabled),
            max_execution_mode=self._coerce_mode(row.max_execution_mode),
            max_risk_r=float(row.max_risk_r or 0.0),
            allowed_sessions=self._normalize_sessions(row.allowed_sessions),
            min_quality_score=float(row.min_quality_score or 0.0),
        )

    def get(self, strategy_family: str | None) -> RolloutPolicy:
        family = str(strategy_family or "legacy_zone_plan").strip().lower()
        row = self.repo.get(family)
        if row is not None:
            return self._from_row(row)
        return self.bootstrap.get(family)

    def upsert(
        self,
        *,
        family: str,
        live_enabled: bool,
        max_execution_mode: ExecutionMode | str,
        max_risk_r: float,
        allowed_sessions: list[str] | tuple[str, ...],
        min_quality_score: float,
        updated_by: str | None = None,
        notes: str | None = None,
    ) -> RolloutPolicy:
        normalized_family = str(family or "legacy_zone_plan").strip().lower()
        row = self.repo.upsert(
            family=normalized_family,
            live_enabled=bool(live_enabled),
            max_execution_mode=self._coerce_mode(max_execution_mode).value,
            max_risk_r=float(max_risk_r),
            allowed_sessions=self._serialize_sessions(allowed_sessions),
            min_quality_score=float(min_quality_score),
            updated_by=updated_by,
            notes=notes,
        )
        return self._from_row(row)

    def list_all(self) -> list[RolloutPolicy]:
        merged = {item.strategy_family: item for item in self.bootstrap.list_all()}
        for row in self.repo.list_all():
            policy = self._from_row(row)
            merged[policy.strategy_family] = policy
        return [merged[key] for key in sorted(merged)]
