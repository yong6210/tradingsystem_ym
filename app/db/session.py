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

_SQLITE_RUNTIME_INDEXES = (
    (
        "ix_plans_time_state_valid_from",
        "CREATE INDEX IF NOT EXISTS ix_plans_time_state_valid_from "
        "ON plans (timeframe, state, valid_until, valid_from)",
    ),
    (
        "ix_plans_symbol_time_state_ev",
        "CREATE INDEX IF NOT EXISTS ix_plans_symbol_time_state_ev "
        "ON plans (symbol, timeframe, state, ev, confidence, rr_base)",
    ),
    (
        "ix_sir_runtime_audits_observed_symbol_phase_status",
        "CREATE INDEX IF NOT EXISTS ix_sir_runtime_audits_observed_symbol_phase_status "
        "ON session_impulse_retest_runtime_audits (observed_ts, symbol, phase, status)",
    ),
    (
        "ix_order_intents_family_created_funnel",
        "CREATE INDEX IF NOT EXISTS ix_order_intents_family_created_funnel "
        "ON order_intents ("
        "strategy_family, created_at, symbol, execution_mode, approval_state, submit_decision, decision_reason_code"
        ")",
    ),
    (
        "ix_order_submissions_live_submitted_funnel",
        "CREATE INDEX IF NOT EXISTS ix_order_submissions_live_submitted_funnel "
        "ON order_submissions (requested_live, submitted_at, intent_id, symbol, state)",
    ),
)


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
        if settings.database_url.startswith("sqlite"):
            with engine.begin() as conn:
                for _, statement in _SQLITE_RUNTIME_INDEXES:
                    conn.execute(text(statement))
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
