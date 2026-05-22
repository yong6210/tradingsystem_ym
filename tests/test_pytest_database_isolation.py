from __future__ import annotations

from pathlib import Path

from app.core.config import sqlite_database_path_from_url
from app.db import session


def test_pytest_database_uses_temp_database() -> None:
    db_path = sqlite_database_path_from_url(str(session.settings.database_url))

    assert db_path is not None
    assert "trading-pytest-" in str(db_path)
    assert "Application Support/trading/data/trading.db" not in str(db_path)
    assert Path(db_path).name == "trading_test.db"
