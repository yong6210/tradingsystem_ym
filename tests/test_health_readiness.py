from __future__ import annotations

import os
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.core.config import get_settings
from app.services.health_check import HealthCheckService
from app.services.runtime_worker_heartbeat import write_worker_heartbeat


def test_health_ready_is_ready_when_all_dependencies_pass(monkeypatch) -> None:
    service = HealthCheckService()

    monkeypatch.setattr("app.services.health_check.db_ready", lambda: True)
    monkeypatch.setattr(service, "_check_binance_rest", lambda: (True, "ok"))
    monkeypatch.setattr(service, "_check_event_backend", lambda: (True, "ok"))
    monkeypatch.setattr(service, "_check_disk_free", lambda: (True, "ok"))
    monkeypatch.setattr(service, "_check_runtime_worker", lambda role: (True, "ok"))
    monkeypatch.setattr(service, "_check_market_data_freshness", lambda timeframe: (True, "ok"))

    snapshot = service.evaluate()
    assert snapshot.status == "ready"
    assert snapshot.checks["db"] is True
    assert snapshot.checks["binance_rest"] is True
    assert snapshot.checks["event_backend"] is True
    assert snapshot.checks["disk_free"] is True
    assert snapshot.checks["worker_loop"] is True
    assert snapshot.checks["worker_ws"] is True
    assert snapshot.checks["market_data_1m"] is True
    assert snapshot.checks["market_data_5m"] is True


def test_health_ready_is_degraded_when_binance_check_fails(monkeypatch) -> None:
    service = HealthCheckService()

    monkeypatch.setattr("app.services.health_check.db_ready", lambda: True)
    monkeypatch.setattr(service, "_check_binance_rest", lambda: (False, "ping_error:TimeoutException"))
    monkeypatch.setattr(service, "_check_event_backend", lambda: (True, "ok"))
    monkeypatch.setattr(service, "_check_disk_free", lambda: (True, "ok"))
    monkeypatch.setattr(service, "_check_runtime_worker", lambda role: (True, "ok"))
    monkeypatch.setattr(service, "_check_market_data_freshness", lambda timeframe: (True, "ok"))

    snapshot = service.evaluate()
    assert snapshot.status == "degraded"
    assert snapshot.checks["db"] is True
    assert snapshot.checks["binance_rest"] is False
    assert snapshot.checks["event_backend"] is True
    assert snapshot.details["binance_rest"].startswith("ping_error")


def test_health_ready_is_degraded_when_disk_is_low(monkeypatch) -> None:
    service = HealthCheckService()

    monkeypatch.setattr("app.services.health_check.db_ready", lambda: True)
    monkeypatch.setattr(service, "_check_binance_rest", lambda: (True, "ok"))
    monkeypatch.setattr(service, "_check_event_backend", lambda: (True, "ok"))
    monkeypatch.setattr(service, "_check_disk_free", lambda: (False, "disk_low:100MB<1024MB"))
    monkeypatch.setattr(service, "_check_runtime_worker", lambda role: (True, "ok"))
    monkeypatch.setattr(service, "_check_market_data_freshness", lambda timeframe: (True, "ok"))

    snapshot = service.evaluate()
    assert snapshot.status == "degraded"
    assert snapshot.checks["disk_free"] is False
    assert snapshot.details["disk_free"].startswith("disk_low")


def test_health_disk_free_uses_sqlite_pysqlite_database_directory(monkeypatch, tmp_path) -> None:
    service = HealthCheckService()
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    seen: dict[str, str] = {}
    service.settings.database_url = f"sqlite+pysqlite:///{db_dir / 'runtime.db'}?mode=ro"
    service.settings.ready_disk_min_free_mb = 1

    def fake_disk_usage(path: str) -> SimpleNamespace:
        seen["path"] = path
        return SimpleNamespace(free=2 * 1024 * 1024)

    monkeypatch.setattr("app.services.health_check.shutil.disk_usage", fake_disk_usage)

    ok, detail = service._check_disk_free()

    assert ok is True
    assert detail == "ok:2MB"
    assert seen["path"] == str(db_dir)


def test_health_disk_free_tolerates_malformed_min_free_setting(monkeypatch, tmp_path) -> None:
    service = HealthCheckService()
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    service.settings.database_url = f"sqlite+pysqlite:///{db_dir / 'runtime.db'}?mode=ro"
    service.settings.ready_disk_min_free_mb = "bad-min-free"

    def fake_disk_usage(path: str) -> SimpleNamespace:
        return SimpleNamespace(free=2 * 1024 * 1024 * 1024)

    monkeypatch.setattr("app.services.health_check.shutil.disk_usage", fake_disk_usage)

    ok, detail = service._check_disk_free()

    assert ok is True
    assert detail == "ok:2048MB"


def test_health_ready_is_degraded_when_worker_heartbeat_missing(monkeypatch, tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True

    monkeypatch.setattr("app.services.health_check.db_ready", lambda: True)
    monkeypatch.setattr(service, "_check_binance_rest", lambda: (True, "ok"))
    monkeypatch.setattr(service, "_check_event_backend", lambda: (True, "ok"))
    monkeypatch.setattr(service, "_check_disk_free", lambda: (True, "ok"))
    monkeypatch.setattr(service, "_check_market_data_freshness", lambda timeframe: (True, "ok"))

    snapshot = service.evaluate()
    assert snapshot.status == "degraded"
    assert snapshot.checks["worker_loop"] is False
    assert snapshot.checks["worker_ws"] is False


def test_health_ready_is_ready_when_worker_heartbeats_are_fresh(monkeypatch, tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True
    settings = get_settings().model_copy(update={"runtime_worker_heartbeat_dir": str(tmp_path)})
    write_worker_heartbeat("loop", settings=settings, status="ok")
    write_worker_heartbeat(
        "ws",
        settings=settings,
        status="ok",
        details={"phase": "streaming", "started_at": datetime.now(timezone.utc).isoformat(), "processed_messages": 1},
    )

    monkeypatch.setattr("app.services.health_check.db_ready", lambda: True)
    monkeypatch.setattr(service, "_check_binance_rest", lambda: (True, "ok"))
    monkeypatch.setattr(service, "_check_event_backend", lambda: (True, "ok"))
    monkeypatch.setattr(service, "_check_disk_free", lambda: (True, "ok"))
    monkeypatch.setattr(service, "_check_market_data_freshness", lambda timeframe: (True, "ok"))

    snapshot = service.evaluate()
    assert snapshot.status == "ready"
    assert snapshot.checks["worker_loop"] is True
    assert snapshot.checks["worker_ws"] is True


def test_worker_heartbeat_replaces_existing_file_atomically(tmp_path) -> None:
    settings = get_settings().model_copy(update={"runtime_worker_heartbeat_dir": str(tmp_path)})
    target = tmp_path / "loop.json"
    target.write_text("old", encoding="utf-8")

    path = write_worker_heartbeat("loop", settings=settings, status="ok", details={"phase": "test"})

    assert path == str(target)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["role"] == "loop"
    assert payload["status"] == "ok"
    assert payload["details"] == {"phase": "test"}
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob(".*.tmp"))


def test_health_worker_heartbeat_error_status_is_degraded(tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True
    settings = get_settings().model_copy(update={"runtime_worker_heartbeat_dir": str(tmp_path)})
    write_worker_heartbeat("loop", settings=settings, status="error", pid=os.getpid())

    ok, detail = service._check_runtime_worker("loop")
    assert ok is False
    assert detail == "heartbeat_status:error"


def test_health_worker_treats_naive_heartbeat_ts_as_utc(tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True
    service.settings.runtime_worker_loop_heartbeat_max_age_seconds = 120
    naive_utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    settings = get_settings().model_copy(update={"runtime_worker_heartbeat_dir": str(tmp_path)})
    write_worker_heartbeat("loop", settings=settings, status="ok", pid=os.getpid(), at=naive_utc_now)

    ok, detail = service._check_runtime_worker("loop")

    assert ok is True
    assert detail.startswith("ok:")


def test_health_worker_corrupt_heartbeat_is_invalid_not_missing(tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True
    (tmp_path / "loop.json").write_text("{not-json", encoding="utf-8")

    ok, detail = service._check_runtime_worker("loop")
    assert ok is False
    assert detail == "heartbeat_status:invalid"


def test_health_worker_dead_pid_heartbeat_is_degraded(tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True
    settings = get_settings().model_copy(update={"runtime_worker_heartbeat_dir": str(tmp_path)})
    write_worker_heartbeat("loop", settings=settings, status="ok", pid=999999999)

    ok, detail = service._check_runtime_worker("loop")
    assert ok is False
    assert detail.startswith("heartbeat_pid_dead:")


def test_health_worker_starting_heartbeat_is_degraded(tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True
    settings = get_settings().model_copy(update={"runtime_worker_heartbeat_dir": str(tmp_path)})
    write_worker_heartbeat("ws", settings=settings, status="ok", pid=os.getpid(), details={"phase": "starting"})

    ok, detail = service._check_runtime_worker("ws")
    assert ok is False
    assert detail == "heartbeat_starting"


def test_health_worker_syncing_universe_heartbeat_is_ready(tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True
    settings = get_settings().model_copy(update={"runtime_worker_heartbeat_dir": str(tmp_path)})
    write_worker_heartbeat("loop", settings=settings, status="ok", pid=os.getpid(), details={"phase": "syncing_universe"})

    ok, detail = service._check_runtime_worker("loop")
    assert ok is True
    assert detail.startswith("ok:")


def test_health_ws_heartbeat_with_no_messages_becomes_degraded(tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True
    service.settings.runtime_worker_ws_no_message_max_age_seconds = 30
    settings = get_settings().model_copy(update={"runtime_worker_heartbeat_dir": str(tmp_path)})
    started_at = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat()
    write_worker_heartbeat(
        "ws",
        settings=settings,
        status="ok",
        pid=os.getpid(),
        details={"phase": "streaming_watchdog", "started_at": started_at, "processed_messages": 0, "reconnects": 2},
    )

    ok, detail = service._check_runtime_worker("ws")
    assert ok is False
    assert detail.startswith("heartbeat_ws_no_messages:")


def test_health_ws_heartbeat_without_started_at_is_degraded(tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True
    service.settings.runtime_worker_ws_no_message_max_age_seconds = 30
    settings = get_settings().model_copy(update={"runtime_worker_heartbeat_dir": str(tmp_path)})
    write_worker_heartbeat(
        "ws",
        settings=settings,
        status="ok",
        pid=os.getpid(),
        details={"phase": "streaming_watchdog", "processed_messages": 0, "reconnects": 0},
    )

    ok, detail = service._check_runtime_worker("ws")
    assert ok is False
    assert detail == "heartbeat_ws_started_at_missing"


def test_health_ws_heartbeat_with_invalid_stats_is_degraded(tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True
    settings = get_settings().model_copy(update={"runtime_worker_heartbeat_dir": str(tmp_path)})
    write_worker_heartbeat(
        "ws",
        settings=settings,
        status="ok",
        pid=os.getpid(),
        details={"phase": "streaming", "started_at": datetime.now(timezone.utc).isoformat(), "processed_messages": "x"},
    )

    ok, detail = service._check_runtime_worker("ws")
    assert ok is False
    assert detail == "heartbeat_ws_stats_invalid"


def test_health_worker_tolerates_malformed_age_settings(tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True
    service.settings.runtime_worker_loop_heartbeat_max_age_seconds = "inf"
    service.settings.runtime_worker_ws_heartbeat_max_age_seconds = "bad-ws-age"
    service.settings.runtime_worker_ws_no_message_max_age_seconds = "nan"
    settings = get_settings().model_copy(update={"runtime_worker_heartbeat_dir": str(tmp_path)})
    write_worker_heartbeat("loop", settings=settings, status="ok", pid=os.getpid())
    write_worker_heartbeat(
        "ws",
        settings=settings,
        status="ok",
        pid=os.getpid(),
        details={"phase": "streaming", "started_at": datetime.now(timezone.utc).isoformat(), "processed_messages": 1},
    )

    loop_ok, loop_detail = service._check_runtime_worker("loop")
    ws_ok, ws_detail = service._check_runtime_worker("ws")

    assert loop_ok is True
    assert loop_detail.startswith("ok:")
    assert ws_ok is True
    assert "processed=1" in ws_detail


def test_health_ws_heartbeat_with_ingest_errors_is_degraded(tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True
    settings = get_settings().model_copy(update={"runtime_worker_heartbeat_dir": str(tmp_path)})
    write_worker_heartbeat(
        "ws",
        settings=settings,
        status="ok",
        pid=os.getpid(),
        details={
            "phase": "streaming",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "processed_messages": 10,
            "ingest_errors": 1,
            "last_ingest_error": "DataQualityError:invalid ohlc bounds",
        },
    )

    ok, detail = service._check_runtime_worker("ws")
    assert ok is False
    assert detail.startswith("heartbeat_ws_ingest_errors:1:")


def test_health_ws_heartbeat_recovers_after_later_ingest_success(tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True
    settings = get_settings().model_copy(update={"runtime_worker_heartbeat_dir": str(tmp_path)})
    now = datetime.now(timezone.utc)
    write_worker_heartbeat(
        "ws",
        settings=settings,
        status="ok",
        pid=os.getpid(),
        details={
            "phase": "streaming",
            "started_at": now.isoformat(),
            "processed_messages": 11,
            "ingest_errors": 1,
            "last_ingest_error": "OperationalError:database is locked",
            "last_ingest_error_at": (now - timedelta(seconds=10)).isoformat(),
            "last_ingest_success_at": now.isoformat(),
        },
    )

    ok, detail = service._check_runtime_worker("ws")
    assert ok is True
    assert "processed=11" in detail


def test_health_ws_legacy_sqlite_lock_error_recovers_when_stream_progresses(tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True
    settings = get_settings().model_copy(update={"runtime_worker_heartbeat_dir": str(tmp_path)})
    write_worker_heartbeat(
        "ws",
        settings=settings,
        status="ok",
        pid=os.getpid(),
        details={
            "phase": "streaming",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "processed_messages": 10,
            "ingest_errors": 1,
            "last_ingest_error": "OperationalError: database is locked",
        },
    )

    ok, detail = service._check_runtime_worker("ws")
    assert ok is True
    assert "processed=10" in detail


def test_health_ws_heartbeat_with_refresh_errors_is_degraded(tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True
    settings = get_settings().model_copy(update={"runtime_worker_heartbeat_dir": str(tmp_path)})
    write_worker_heartbeat(
        "ws",
        settings=settings,
        status="ok",
        pid=os.getpid(),
        details={
            "phase": "streaming",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "processed_messages": 10,
            "refresh_errors": 1,
            "last_refresh_error": "RuntimeError:refresh failed",
        },
    )

    ok, detail = service._check_runtime_worker("ws")
    assert ok is False
    assert detail.startswith("heartbeat_ws_refresh_errors:1:")


def test_health_ws_heartbeat_with_auto_route_errors_is_degraded(tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True
    settings = get_settings().model_copy(update={"runtime_worker_heartbeat_dir": str(tmp_path)})
    write_worker_heartbeat(
        "ws",
        settings=settings,
        status="ok",
        pid=os.getpid(),
        details={
            "phase": "streaming",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "processed_messages": 10,
            "auto_route_errors": 1,
            "last_auto_route_error": "RuntimeError:route failed",
        },
    )

    ok, detail = service._check_runtime_worker("ws")
    assert ok is False
    assert detail.startswith("heartbeat_ws_auto_route_errors:1:")


def test_health_ws_heartbeat_with_progress_callback_errors_is_degraded(tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True
    settings = get_settings().model_copy(update={"runtime_worker_heartbeat_dir": str(tmp_path)})
    write_worker_heartbeat(
        "ws",
        settings=settings,
        status="ok",
        pid=os.getpid(),
        details={
            "phase": "streaming",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "processed_messages": 10,
            "progress_callback_errors": 1,
            "last_progress_callback_error": "RuntimeError:heartbeat write failed",
        },
    )

    ok, detail = service._check_runtime_worker("ws")
    assert ok is False
    assert detail.startswith("heartbeat_ws_progress_callback_errors:1:")


def test_health_ws_heartbeat_with_messages_remains_ready(tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True
    service.settings.runtime_worker_ws_no_message_max_age_seconds = 30
    settings = get_settings().model_copy(update={"runtime_worker_heartbeat_dir": str(tmp_path)})
    started_at = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat()
    write_worker_heartbeat(
        "ws",
        settings=settings,
        status="ok",
        pid=os.getpid(),
        details={"phase": "streaming", "started_at": started_at, "processed_messages": 1, "reconnects": 0},
    )

    ok, detail = service._check_runtime_worker("ws")
    assert ok is True
    assert "processed=1" in detail


def test_health_ready_is_degraded_when_market_data_is_stale(monkeypatch) -> None:
    service = HealthCheckService()

    monkeypatch.setattr("app.services.health_check.db_ready", lambda: True)
    monkeypatch.setattr(service, "_check_binance_rest", lambda: (True, "ok"))
    monkeypatch.setattr(service, "_check_event_backend", lambda: (True, "ok"))
    monkeypatch.setattr(service, "_check_disk_free", lambda: (True, "ok"))
    monkeypatch.setattr(service, "_check_runtime_worker", lambda role: (True, "ok"))
    monkeypatch.setattr(
        service,
        "_check_market_data_freshness",
        lambda timeframe: (False, "stale:BTCUSDC:1m:999s") if timeframe == "1m" else (True, "ok"),
    )

    snapshot = service.evaluate()
    assert snapshot.status == "degraded"
    assert snapshot.checks["market_data_1m"] is False


def test_health_market_data_freshness_uses_live_symbol_quorum(monkeypatch) -> None:
    service = HealthCheckService()
    now = datetime.now(timezone.utc)
    rows = {
        "BTCUSDC": SimpleNamespace(ts=now - timedelta(seconds=400)),
        "ETHUSDC": SimpleNamespace(ts=now - timedelta(seconds=40)),
        "SOLUSDC": SimpleNamespace(ts=now - timedelta(seconds=50)),
        "LINKUSDC": SimpleNamespace(ts=now - timedelta(seconds=60)),
    }

    class FakeSession:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    class FakeRepo:
        def __init__(self, db):
            pass

        def get_last_candle(self, symbol, timeframe):
            return rows.get(symbol)

    monkeypatch.setattr(service, "_market_data_probe_symbols", lambda: ["BTCUSDC", "ETHUSDC", "SOLUSDC", "LINKUSDC"])
    monkeypatch.setattr("app.services.health_check.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("app.services.health_check.CandleRepository", FakeRepo)

    ok, detail = service._check_market_data_freshness("1m")

    assert ok is True
    assert "fresh=3/4" in detail
    assert "stale=BTCUSDC" in detail


def test_health_market_data_freshness_fails_when_live_symbol_quorum_is_stale(monkeypatch) -> None:
    service = HealthCheckService()
    now = datetime.now(timezone.utc)
    rows = {
        "BTCUSDC": SimpleNamespace(ts=now - timedelta(seconds=400)),
        "ETHUSDC": SimpleNamespace(ts=now - timedelta(seconds=390)),
        "SOLUSDC": SimpleNamespace(ts=now - timedelta(seconds=380)),
        "LINKUSDC": SimpleNamespace(ts=now - timedelta(seconds=40)),
    }

    class FakeSession:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    class FakeRepo:
        def __init__(self, db):
            pass

        def get_last_candle(self, symbol, timeframe):
            return rows.get(symbol)

    monkeypatch.setattr(service, "_market_data_probe_symbols", lambda: ["BTCUSDC", "ETHUSDC", "SOLUSDC", "LINKUSDC"])
    monkeypatch.setattr("app.services.health_check.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("app.services.health_check.CandleRepository", FakeRepo)

    ok, detail = service._check_market_data_freshness("1m")

    assert ok is False
    assert "fresh=1/4" in detail
    assert "required=3" in detail
