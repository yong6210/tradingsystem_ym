from __future__ import annotations

import os
import shutil
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any

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

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        if value in (None, "", "None"):
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if isfinite(parsed) else default

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        if value in (None, "", "None"):
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return int(parsed) if isfinite(parsed) else default

    @staticmethod
    def _safe_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return bool(default)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value) if isfinite(float(value)) else bool(default)
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
        return bool(default)

    @classmethod
    def _parse_required_int(cls, value: Any) -> int | None:
        if value in (None, "", "None"):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return int(parsed) if isfinite(parsed) else None

    @staticmethod
    def _parse_optional_datetime(value: Any) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _error_recovered(cls, details: dict[str, Any], *, error_at_key: str, success_at_key: str) -> bool:
        error_at = cls._parse_optional_datetime(details.get(error_at_key))
        success_at = cls._parse_optional_datetime(details.get(success_at_key))
        return error_at is not None and success_at is not None and success_at >= error_at

    @staticmethod
    def _legacy_sqlite_lock_recovered(details: dict[str, Any], *, error_key: str, processed_messages: int) -> bool:
        last_error = str(details.get(error_key) or "").lower()
        return processed_messages > 0 and "database is locked" in last_error

    def _check_binance_rest(self) -> tuple[bool, str]:
        client = BinanceFuturesClient(timeout_seconds=self._safe_float(self.settings.ready_http_timeout_seconds, default=2.0))
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
                import redis  # type: ignore[import-not-found,import-untyped]
            except Exception:
                return False, "redis_package_missing"
            try:
                client = redis.Redis.from_url(
                    self.settings.event_redis_url,
                    socket_connect_timeout=self._safe_float(self.settings.ready_tcp_timeout_seconds, default=2.0),
                    socket_timeout=self._safe_float(self.settings.ready_tcp_timeout_seconds, default=2.0),
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
                port = int(float(port_text))
            except (TypeError, ValueError, OverflowError):
                return False, "kafka_port_invalid"
            try:
                with socket.create_connection(
                    (host, port),
                    timeout=self._safe_float(self.settings.ready_tcp_timeout_seconds, default=2.0),
                ):
                    return True, "ok"
            except Exception as exc:
                return False, f"kafka_error:{exc.__class__.__name__}"
        return False, f"unsupported_backend:{backend}"

    def _check_disk_free(self) -> tuple[bool, str]:
        min_free_mb = self._safe_int(self.settings.ready_disk_min_free_mb, default=1024)
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
        if not self._safe_bool(self.settings.ready_require_runtime_workers):
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
            pid = int(float(pid_raw))
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
        ts = self._parse_optional_datetime(ts_raw)
        if ts is None:
            return False, "heartbeat_ts_invalid"
        age_seconds = max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())
        max_age = (
            self._safe_float(self.settings.runtime_worker_loop_heartbeat_max_age_seconds, default=420.0)
            if role == "loop"
            else self._safe_float(self.settings.runtime_worker_ws_heartbeat_max_age_seconds, default=180.0)
        )
        if age_seconds > max_age:
            return False, f"heartbeat_stale:{int(age_seconds)}s"
        if role == "ws":
            try:
                processed_messages = self._parse_required_int(details_payload.get("processed_messages", 0) or 0)
                reconnects = self._parse_required_int(details_payload.get("reconnects", 0) or 0)
                ingest_errors = self._parse_required_int(details_payload.get("ingest_errors", 0) or 0)
                refresh_errors = self._parse_required_int(details_payload.get("refresh_errors", 0) or 0)
                auto_route_errors = self._parse_required_int(details_payload.get("auto_route_errors", 0) or 0)
                progress_callback_errors = self._parse_required_int(details_payload.get("progress_callback_errors", 0) or 0)
                no_message_max_age = self._safe_float(self.settings.runtime_worker_ws_no_message_max_age_seconds, default=180.0)
            except (TypeError, ValueError, OverflowError):
                return False, "heartbeat_ws_stats_invalid"
            if (
                processed_messages is None
                or reconnects is None
                or ingest_errors is None
                or refresh_errors is None
                or auto_route_errors is None
                or progress_callback_errors is None
            ):
                return False, "heartbeat_ws_stats_invalid"
            if ingest_errors > 0:
                last_error = str(details_payload.get("last_ingest_error") or "").strip()
                if not self._error_recovered(
                    details_payload,
                    error_at_key="last_ingest_error_at",
                    success_at_key="last_ingest_success_at",
                ) and not self._legacy_sqlite_lock_recovered(
                    details_payload,
                    error_key="last_ingest_error",
                    processed_messages=processed_messages,
                ):
                    return False, f"heartbeat_ws_ingest_errors:{ingest_errors}:{last_error or 'unknown'}"
            if refresh_errors > 0:
                last_error = str(details_payload.get("last_refresh_error") or "").strip()
                if not self._error_recovered(
                    details_payload,
                    error_at_key="last_refresh_error_at",
                    success_at_key="last_refresh_success_at",
                ):
                    return False, f"heartbeat_ws_refresh_errors:{refresh_errors}:{last_error or 'unknown'}"
            if auto_route_errors > 0:
                last_error = str(details_payload.get("last_auto_route_error") or "").strip()
                if not self._error_recovered(
                    details_payload,
                    error_at_key="last_auto_route_error_at",
                    success_at_key="last_auto_route_success_at",
                ):
                    return False, f"heartbeat_ws_auto_route_errors:{auto_route_errors}:{last_error or 'unknown'}"
            if progress_callback_errors > 0:
                last_error = str(details_payload.get("last_progress_callback_error") or "").strip()
                if not self._error_recovered(
                    details_payload,
                    error_at_key="last_progress_callback_error_at",
                    success_at_key="last_progress_callback_success_at",
                ):
                    return False, f"heartbeat_ws_progress_callback_errors:{progress_callback_errors}:{last_error or 'unknown'}"
            started_at_raw = str(details_payload.get("started_at") or "").strip()
            if processed_messages <= 0 and not started_at_raw and no_message_max_age > 0:
                return False, "heartbeat_ws_started_at_missing"
            if processed_messages <= 0 and started_at_raw and no_message_max_age > 0:
                started_at = self._parse_optional_datetime(started_at_raw)
                if started_at is None:
                    return False, "heartbeat_ws_started_at_invalid"
                no_message_age = max(0.0, (datetime.now(timezone.utc) - started_at).total_seconds())
                if no_message_age > no_message_max_age:
                    return False, f"heartbeat_ws_no_messages:{int(no_message_age)}s:reconnects={reconnects}"
            return True, f"ok:{int(age_seconds)}s:processed={processed_messages}:reconnects={reconnects}"
        return True, f"ok:{int(age_seconds)}s"

    def _market_data_probe_symbols(self) -> list[str]:
        raw_groups = [
            str(getattr(self.settings, "auto_trading_micro_live_allowed_symbols", "") or ""),
            str(getattr(self.settings, "session_impulse_retest_allowed_symbols", "") or ""),
            str(getattr(self.settings, "ready_market_data_probe_symbol", "") or "BTCUSDC"),
        ]
        symbols: list[str] = []
        seen: set[str] = set()
        for raw in raw_groups:
            for item in str(raw or "").split(","):
                symbol = item.strip().upper()
                if not symbol or symbol in seen:
                    continue
                seen.add(symbol)
                symbols.append(symbol)
        return symbols[:12] or ["BTCUSDC"]

    def _check_market_data_freshness(self, timeframe: str) -> tuple[bool, str]:
        normalized_tf = str(timeframe or "").strip().lower()
        if normalized_tf not in {"1m", "5m"}:
            return False, f"unsupported_timeframe:{timeframe}"
        symbols = self._market_data_probe_symbols()
        with SessionLocal() as db:
            repo = CandleRepository(db)
            rows = {symbol: repo.get_last_candle(symbol, normalized_tf) for symbol in symbols}
        max_age = (
            self._safe_float(self.settings.ready_market_data_1m_max_age_seconds, default=180.0)
            if normalized_tf == "1m"
            else self._safe_float(self.settings.ready_market_data_5m_max_age_seconds, default=600.0)
        )
        now = datetime.now(timezone.utc)
        fresh: list[tuple[str, int]] = []
        stale: list[str] = []
        missing: list[str] = []
        for symbol, row in rows.items():
            if row is None:
                missing.append(symbol)
                continue
            ts = row.ts if row.ts.tzinfo else row.ts.replace(tzinfo=timezone.utc)
            age_seconds = max(0.0, (now - ts.astimezone(timezone.utc)).total_seconds())
            if age_seconds <= max_age:
                fresh.append((symbol, int(age_seconds)))
            else:
                stale.append(f"{symbol}:{int(age_seconds)}s")
        required_fresh = min(3, len(symbols))
        if len(fresh) >= required_fresh:
            oldest_fresh = max(age for _, age in fresh)
            stale_suffix = f" stale={','.join(stale[:4])}" if stale else ""
            missing_suffix = f" missing={','.join(missing[:4])}" if missing else ""
            return (
                True,
                f"ok:{normalized_tf}:fresh={len(fresh)}/{len(symbols)}:oldest_fresh={oldest_fresh}s"
                f"{stale_suffix}{missing_suffix}",
            )
        stale_detail = ",".join(stale[:4]) if stale else "none"
        missing_detail = ",".join(missing[:4]) if missing else "none"
        return (
            False,
            f"stale:{normalized_tf}:fresh={len(fresh)}/{len(symbols)}:required={required_fresh}:"
            f"stale={stale_detail}:missing={missing_detail}",
        )

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
