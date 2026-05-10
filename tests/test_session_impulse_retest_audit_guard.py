from __future__ import annotations

from datetime import UTC, datetime
from types import MethodType

from app.services.strategy_engine import StrategyEngine


class _FakeDb:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_session_impulse_retest_audit_failure_does_not_hide_auto_route_result() -> None:
    engine = object.__new__(StrategyEngine)
    engine.db = _FakeDb()

    def raise_audit(self, **_kwargs) -> None:
        raise RuntimeError("audit-db-down")

    engine._record_session_impulse_retest_runtime_audit = MethodType(raise_audit, engine)

    response = StrategyEngine._finalize_session_impulse_retest_auto_route_audit(
        engine,
        symbol="BTCUSDC",
        observed_ts=datetime(2026, 5, 10, tzinfo=UTC),
        response={
            "symbol": "BTCUSDC",
            "reason": "submitted",
            "results": [
                {
                    "plan_id": "plan_1",
                    "status": "submitted",
                    "intent": {"decision_reason_code": "submit_ready"},
                }
            ],
        },
    )

    assert response["reason"] == "submitted"
    assert response["runtime_audit_error"] == "RuntimeError:audit-db-down"
    assert engine.db.commits == 0
    assert engine.db.rollbacks == 1
