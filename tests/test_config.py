from pathlib import Path

from app.core.config import ROOT_DIR, Settings


def test_sqlite_database_url_is_root_anchored_when_relative() -> None:
    settings = Settings(database_url="sqlite:///./trading.db")

    assert settings.database_url == f"sqlite:///{(ROOT_DIR / 'trading.db').resolve()}"


def test_sqlite_database_url_preserves_absolute_path(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    settings = Settings(database_url=f"sqlite:///{db_path}")

    assert settings.database_url == f"sqlite:///{db_path}"
