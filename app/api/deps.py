from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db, init_db
from app.services.strategy_engine import StrategyEngine


def get_engine(db: Session = Depends(get_db)) -> StrategyEngine:
    init_db()
    return StrategyEngine(db)
