from __future__ import annotations

from app.services.health_check import HealthCheckService


def test_health_ready_is_ready_when_all_dependencies_pass(monkeypatch) -> None:
    service = HealthCheckService()

    monkeypatch.setattr("app.services.health_check.db_ready", lambda: True)
    monkeypatch.setattr(service, "_check_binance_rest", lambda: (True, "ok"))
    monkeypatch.setattr(service, "_check_event_backend", lambda: (True, "ok"))

    snapshot = service.evaluate()
    assert snapshot.status == "ready"
    assert snapshot.checks["db"] is True
    assert snapshot.checks["binance_rest"] is True
    assert snapshot.checks["event_backend"] is True


def test_health_ready_is_degraded_when_binance_check_fails(monkeypatch) -> None:
    service = HealthCheckService()

    monkeypatch.setattr("app.services.health_check.db_ready", lambda: True)
    monkeypatch.setattr(service, "_check_binance_rest", lambda: (False, "ping_error:TimeoutException"))
    monkeypatch.setattr(service, "_check_event_backend", lambda: (True, "ok"))

    snapshot = service.evaluate()
    assert snapshot.status == "degraded"
    assert snapshot.checks["db"] is True
    assert snapshot.checks["binance_rest"] is False
    assert snapshot.checks["event_backend"] is True
    assert snapshot.details["binance_rest"].startswith("ping_error")
