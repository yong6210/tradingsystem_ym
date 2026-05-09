from __future__ import annotations

import os
import shutil
import socket
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import get_settings, sqlite_database_path_from_url
from app.db.repositories import CandleRepository
from app.db.session import SessionLocal
from app.db.session import db_ready
from app.integrations.binance_futures import BinanceFuturesClient
from app.services.runtime_worker_heartbeat import read_worker_heartbeat


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

    def _check_disk_free(self) -> tuple[bool, str]:
        min_free_mb = int(self.settings.ready_disk_min_free_mb or 0)
        if min_free_mb <= 0:
            return True, "disabled"
        path = os.getcwd()
        db_path = sqlite_database_path_from_url(str(self.settings.database_url or ""))
        if db_path is not None:
            path = str(db_path.parent)
        try:
            usage = shutil.disk_usage(path)
        except Exception as exc:
            return False, f"disk_check_error:{exc.__class__.__name__}"
        free_mb = int(usage.free / (1024 * 1024))
        if free_mb < min_free_mb:
            return False, f"disk_low:{free_mb}MB<{min_free_mb}MB"
        return True, f"ok:{free_mb}MB"

    def _check_runtime_worker(self, role: str) -> tuple[bool, str]:
        if not bool(self.settings.ready_require_runtime_workers):
            return True, "disabled"
        payload = read_worker_heartbeat(role, settings=self.settings)
        if payload is None:
            return False, "heartbeat_missing"
        payload_role = str(payload.get("role") or "").strip().lower()
        if payload_role and payload_role != role:
            return False, f"heartbeat_role_mismatch:{payload_role}"
        status = str(payload.get("status") or "").strip().lower()
        if status != "ok":
            return False, f"heartbeat_status:{status or 'missing'}"
        details_payload = payload.get("details") if isinstance(payload.get("details"), dict) else {}
        phase = str(details_payload.get("phase") or "").strip().lower()
        if phase == "starting":
            return False, "heartbeat_starting"
        pid_raw = payload.get("pid")
        try:
            pid = int(pid_raw)
        except Exception:
            return False, "heartbeat_pid_invalid"
        if pid <= 0:
            return False, "heartbeat_pid_invalid"
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False, f"heartbeat_pid_dead:{pid}"
        except PermissionError:
            pass
        except Exception as exc:
            return False, f"heartbeat_pid_check_error:{exc.__class__.__name__}"
        ts_raw = str(payload.get("ts") or "").strip()
        if not ts_raw:
            return False, "heartbeat_ts_missing"
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return False, "heartbeat_ts_invalid"
        age_seconds = max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())
        max_age = (
            float(self.settings.runtime_worker_loop_heartbeat_max_age_seconds)
            if role == "loop"
            else float(self.settings.runtime_worker_ws_heartbeat_max_age_seconds)
        )
        if age_seconds > max_age:
            return False, f"heartbeat_stale:{int(age_seconds)}s"
        if role == "ws":
            try:
                processed_messages = int(details_payload.get("processed_messages", 0) or 0)
                reconnects = int(details_payload.get("reconnects", 0) or 0)
                ingest_errors = int(details_payload.get("ingest_errors", 0) or 0)
                refresh_errors = int(details_payload.get("refresh_errors", 0) or 0)
                auto_route_errors = int(details_payload.get("auto_route_errors", 0) or 0)
                no_message_max_age = float(self.settings.runtime_worker_ws_no_message_max_age_seconds)
            except (TypeError, ValueError):
                return False, "heartbeat_ws_stats_invalid"
            if ingest_errors > 0:
                last_error = str(details_payload.get("last_ingest_error") or "").strip()
                return False, f"heartbeat_ws_ingest_errors:{ingest_errors}:{last_error or 'unknown'}"
            if refresh_errors > 0:
                last_error = str(details_payload.get("last_refresh_error") or "").strip()
                return False, f"heartbeat_ws_refresh_errors:{refresh_errors}:{last_error or 'unknown'}"
            if auto_route_errors > 0:
                last_error = str(details_payload.get("last_auto_route_error") or "").strip()
                return False, f"heartbeat_ws_auto_route_errors:{auto_route_errors}:{last_error or 'unknown'}"
            started_at_raw = str(details_payload.get("started_at") or "").strip()
            if processed_messages <= 0 and not started_at_raw and no_message_max_age > 0:
                return False, "heartbeat_ws_started_at_missing"
            if processed_messages <= 0 and started_at_raw and no_message_max_age > 0:
                try:
                    started_at = datetime.fromisoformat(started_at_raw.replace("Z", "+00:00")).astimezone(timezone.utc)
                except Exception:
                    return False, "heartbeat_ws_started_at_invalid"
                no_message_age = max(0.0, (datetime.now(timezone.utc) - started_at).total_seconds())
                if no_message_age > no_message_max_age:
                    return False, f"heartbeat_ws_no_messages:{int(no_message_age)}s:reconnects={reconnects}"
            return True, f"ok:{int(age_seconds)}s:processed={processed_messages}:reconnects={reconnects}"
        return True, f"ok:{int(age_seconds)}s"

    def _market_data_probe_symbol(self) -> str:
        allowed = [
            item.strip().upper()
            for item in str(self.settings.session_impulse_retest_allowed_symbols or "").split(",")
            if item.strip()
        ]
        if allowed:
            return allowed[0]
        return str(self.settings.ready_market_data_probe_symbol or "BTCUSDC").upper()

    def _check_market_data_freshness(self, timeframe: str) -> tuple[bool, str]:
        normalized_tf = str(timeframe or "").strip().lower()
        if normalized_tf not in {"1m", "5m"}:
            return False, f"unsupported_timeframe:{timeframe}"
        symbol = self._market_data_probe_symbol()
        with SessionLocal() as db:
            repo = CandleRepository(db)
            row = repo.get_last_candle(symbol, normalized_tf)
        if row is None:
            return False, f"missing_last_candle:{symbol}:{normalized_tf}"
        ts = row.ts if row.ts.tzinfo else row.ts.replace(tzinfo=timezone.utc)
        age_seconds = max(0.0, (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds())
        max_age = (
            float(self.settings.ready_market_data_1m_max_age_seconds)
            if normalized_tf == "1m"
            else float(self.settings.ready_market_data_5m_max_age_seconds)
        )
        if age_seconds > max_age:
            return False, f"stale:{symbol}:{normalized_tf}:{int(age_seconds)}s"
        return True, f"ok:{symbol}:{normalized_tf}:{int(age_seconds)}s"

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

        checks["disk_free"] = False
        details["disk_free"] = "not_checked"
        disk_ok, disk_detail = self._check_disk_free()
        checks["disk_free"] = disk_ok
        details["disk_free"] = disk_detail

        checks["worker_loop"] = False
        details["worker_loop"] = "not_checked"
        worker_loop_ok, worker_loop_detail = self._check_runtime_worker("loop")
        checks["worker_loop"] = worker_loop_ok
        details["worker_loop"] = worker_loop_detail

        checks["worker_ws"] = False
        details["worker_ws"] = "not_checked"
        worker_ws_ok, worker_ws_detail = self._check_runtime_worker("ws")
        checks["worker_ws"] = worker_ws_ok
        details["worker_ws"] = worker_ws_detail

        checks["market_data_1m"] = False
        details["market_data_1m"] = "not_checked"
        market_1m_ok, market_1m_detail = self._check_market_data_freshness("1m")
        checks["market_data_1m"] = market_1m_ok
        details["market_data_1m"] = market_1m_detail

        checks["market_data_5m"] = False
        details["market_data_5m"] = "not_checked"
        market_5m_ok, market_5m_detail = self._check_market_data_freshness("5m")
        checks["market_data_5m"] = market_5m_ok
        details["market_data_5m"] = market_5m_detail

        status = "ready" if all(checks.values()) else "degraded"
        return ReadySnapshot(status=status, checks=checks, details=details)
