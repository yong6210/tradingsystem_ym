from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

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


def test_health_worker_heartbeat_error_status_is_degraded(tmp_path) -> None:
    service = HealthCheckService()
    service.settings.runtime_worker_heartbeat_dir = str(tmp_path)
    service.settings.ready_require_runtime_workers = True
    settings = get_settings().model_copy(update={"runtime_worker_heartbeat_dir": str(tmp_path)})
    write_worker_heartbeat("loop", settings=settings, status="error", pid=os.getpid())

    ok, detail = service._check_runtime_worker("loop")
    assert ok is False
    assert detail == "heartbeat_status:error"


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
