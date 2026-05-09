from collections.abc import Generator
from dataclasses import dataclass
from threading import Lock

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings, sqlite_database_path_from_url
from app.db.base import Base

settings = get_settings()
_SQLITE_BUSY_TIMEOUT_MS = 30_000
_SQLITE_WAL_ENABLED = ":memory:" not in settings.database_url and "mode=memory" not in settings.database_url


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    db_path = sqlite_database_path_from_url(str(database_url or ""))
    if db_path is not None:
        db_path.parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_parent_dir(settings.database_url)

engine_kwargs = {"future": True, "pool_pre_ping": True}
if settings.database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"timeout": _SQLITE_BUSY_TIMEOUT_MS / 1000.0}

engine = create_engine(settings.database_url, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
_init_lock = Lock()


@dataclass
class _InitState:
    initialized: bool = False


_init_state = _InitState()


if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
            cursor.execute("PRAGMA foreign_keys=ON")
            if _SQLITE_WAL_ENABLED:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.fetchone()
                cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


def init_db() -> None:
    if _init_state.initialized:
        return
    with _init_lock:
        if _init_state.initialized:
            return
        from app.db import models  # noqa: F401

        Base.metadata.create_all(bind=engine)
        _init_state.initialized = True


def db_ready() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
