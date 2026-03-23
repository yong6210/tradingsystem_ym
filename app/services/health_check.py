from __future__ import annotations

import socket
from dataclasses import dataclass

from app.core.config import get_settings
from app.db.session import db_ready
from app.integrations.binance_futures import BinanceFuturesClient


@dataclass(slots=True)
class ReadySnapshot:
    status: str
    checks: dict[str, bool]
    details: dict[str, str]


class HealthCheckService:
    def __init__(self):
        self.settings = get_settings()

    def _check_binance_rest(self) -> tuple[bool, str]:
        client = BinanceFuturesClient(timeout_seconds=self.settings.ready_http_timeout_seconds)
        try:
            ok = client.ping()
        except Exception as exc:
            return False, f"ping_error:{exc.__class__.__name__}"
        if not ok:
            return False, "ping_failed"
        return True, "ok"

    def _check_event_backend(self) -> tuple[bool, str]:
        backend = self.settings.event_backend.lower()
        if backend == "memory":
            return True, "memory"
        if backend == "redis":
            try:
                import redis  # type: ignore
            except Exception:
                return False, "redis_package_missing"
            try:
                client = redis.Redis.from_url(
                    self.settings.event_redis_url,
                    socket_connect_timeout=self.settings.ready_tcp_timeout_seconds,
                    socket_timeout=self.settings.ready_tcp_timeout_seconds,
                    decode_responses=True,
                )
                pong = client.ping()
                return bool(pong), "ok" if pong else "ping_failed"
            except Exception as exc:
                return False, f"redis_error:{exc.__class__.__name__}"
        if backend == "kafka":
            host_port = self.settings.event_kafka_bootstrap_servers.split(",")[0].strip()
            if ":" not in host_port:
                return False, "kafka_host_port_invalid"
            host, port_text = host_port.rsplit(":", 1)
            try:
                port = int(port_text)
            except ValueError:
                return False, "kafka_port_invalid"
            try:
                with socket.create_connection(
                    (host, port),
                    timeout=self.settings.ready_tcp_timeout_seconds,
                ):
                    return True, "ok"
            except Exception as exc:
                return False, f"kafka_error:{exc.__class__.__name__}"
        return False, f"unsupported_backend:{backend}"

    def evaluate(self) -> ReadySnapshot:
        checks: dict[str, bool] = {}
        details: dict[str, str] = {}

        checks["db"] = db_ready()
        details["db"] = "ok" if checks["db"] else "connection_failed"

        checks["binance_rest"] = False
        details["binance_rest"] = "not_checked"
        binance_ok, binance_detail = self._check_binance_rest()
        checks["binance_rest"] = binance_ok
        details["binance_rest"] = binance_detail

        checks["event_backend"] = False
        details["event_backend"] = "not_checked"
        event_ok, event_detail = self._check_event_backend()
        checks["event_backend"] = event_ok
        details["event_backend"] = event_detail

        status = "ready" if all(checks.values()) else "degraded"
        return ReadySnapshot(status=status, checks=checks, details=details)
