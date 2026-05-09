from pathlib import Path

from app.core.config import ROOT_DIR, Settings, sqlite_database_path_from_url


def test_sqlite_database_url_is_root_anchored_when_relative() -> None:
    settings = Settings(database_url="sqlite:///./trading.db")

    assert settings.database_url == f"sqlite:///{(ROOT_DIR / 'trading.db').resolve()}"


def test_sqlite_database_url_preserves_absolute_path(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    settings = Settings(database_url=f"sqlite:///{db_path}")

    assert settings.database_url == f"sqlite:///{db_path}"


def test_sqlite_pysqlite_database_url_is_root_anchored_when_relative() -> None:
    settings = Settings(database_url="sqlite+pysqlite:///runtime.db?timeout=30")

    assert settings.database_url == f"sqlite+pysqlite:///{(ROOT_DIR / 'runtime.db').resolve()}?timeout=30"


def test_sqlite_database_path_parser_supports_supported_prefixes(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"

    assert sqlite_database_path_from_url(f"sqlite:///{db_path}") == db_path
    assert sqlite_database_path_from_url(f"sqlite+pysqlite:///{db_path}?mode=ro") == db_path
    assert sqlite_database_path_from_url("sqlite:///:memory:") is None


def test_report_paths_are_root_anchored_when_relative() -> None:
    settings = Settings(_env_file=None, validation_report_dir="reports/validation")

    assert settings.validation_report_dir == str((ROOT_DIR / "reports" / "validation").resolve())
