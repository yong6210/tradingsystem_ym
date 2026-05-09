from __future__ import annotations

from datetime import datetime, timedelta, timezone
from inspect import signature

from app.core.enums import PlanState
from app.db.models import Plan
from app.db.repositories import PlanRepository
from app.db.session import SessionLocal, init_db


def _plan(*, plan_id: str, valid_from: datetime, valid_until: datetime, ev: float = 0.1) -> Plan:
    return Plan(
        plan_id=plan_id,
        zone_id=f"{plan_id}_zone",
        symbol="BUGUSDC",
        timeframe="5m",
        direction="long",
        entry_model="CONFIRM",
        entry_price=100.0,
        entry_condition="repo_test",
        sl=99.0,
        tp1=101.0,
        tp2=102.0,
        tp3=103.0,
        split={"tp1": 0.5, "tp2": 0.3, "runner": 0.2},
        rr_min=1.0,
        rr_base=1.5,
        rr_opt=2.0,
        ev=ev,
        cost_est=0.01,
        confidence=0.7,
        validity={"strategy_family": "repo_test"},
        state=PlanState.PLANNED.value,
        valid_from=valid_from,
        valid_until=valid_until,
        strategy_version="test",
    )


def test_plan_repository_list_recent_contract_keeps_limit_and_open_recent_plans() -> None:
    init_db()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    old_but_still_open = _plan(
        plan_id="repo_recent_open",
        valid_from=now - timedelta(days=10),
        valid_until=now + timedelta(hours=1),
        ev=0.9,
    )
    recent = _plan(
        plan_id="repo_recent_new",
        valid_from=now - timedelta(hours=2),
        valid_until=now + timedelta(hours=3),
        ev=0.5,
    )
    stale = _plan(
        plan_id="repo_recent_stale",
        valid_from=now - timedelta(days=10),
        valid_until=now - timedelta(days=8),
        ev=1.0,
    )

    with SessionLocal() as db:
        repo = PlanRepository(db)
        repo.upsert_many([old_but_still_open, recent, stale])
        db.commit()

        assert "limit" in signature(PlanRepository.list_recent).parameters
        rows = repo.list_recent(symbol="BUGUSDC", timeframe="5m", days=1, limit=1)
        assert [row.plan_id for row in rows] == ["repo_recent_new"]

        rows = repo.list_recent(symbol="BUGUSDC", timeframe="5m", days=1, limit=10)
        assert {row.plan_id for row in rows} == {"repo_recent_open", "repo_recent_new"}
