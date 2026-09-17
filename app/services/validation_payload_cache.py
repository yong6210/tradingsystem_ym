from __future__ import annotations

from collections.abc import Mapping
import copy
import hashlib
import json
from math import isfinite
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

from app.core.config import Settings, sqlite_database_path_from_url


READ_ONLY_RECOMPUTE_CACHE_TTL_SECONDS = 120.0
VALIDATION_PAYLOAD_CACHE_MAX_AGE_SECONDS = 21600.0
READ_ONLY_RECOMPUTE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _safe_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
        return False
    return bool(default)


class ValidationPayloadCacheService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def path(self, symbol: str) -> Path:
        scope = self.scope()
        return Path(self.settings.validation_report_dir) / "runtime_payload_cache" / scope / f"{str(symbol).upper()}.json"

    def scope(self) -> str:
        raw = "|".join(
            [
                str(getattr(self.settings, "database_url", "")),
                str(getattr(self.settings, "strategy_version", "")),
            ]
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def key(self, symbol: str) -> str:
        report_dir = str(Path(self.settings.validation_report_dir).expanduser().resolve())
        return "|".join([report_dir, self.scope(), str(symbol).upper()])

    def sqlite_database_artifact_paths(self) -> list[Path]:
        db_path = sqlite_database_path_from_url(str(getattr(self.settings, "database_url", "")))
        if db_path is None:
            return []
        return [db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")]

    def stale_for_database(self, cache_mtime: float) -> bool:
        for artifact_path in self.sqlite_database_artifact_paths():
            try:
                if artifact_path.exists() and artifact_path.stat().st_mtime > cache_mtime:
                    return True
            except OSError:
                continue
        return False

    def max_age_seconds(self) -> float:
        try:
            value = getattr(
                self.settings,
                "validation_payload_cache_max_age_seconds",
                VALIDATION_PAYLOAD_CACHE_MAX_AGE_SECONDS,
            )
            parsed = float(value)
            return max(1.0, parsed) if isfinite(parsed) else VALIDATION_PAYLOAD_CACHE_MAX_AGE_SECONDS
        except (TypeError, ValueError):
            return VALIDATION_PAYLOAD_CACHE_MAX_AGE_SECONDS

    def stale_on_database_change(self) -> bool:
        return _safe_bool(getattr(self.settings, "validation_payload_cache_stale_on_database_change", False))

    @staticmethod
    def valid_payload(symbol: str, payload: Any) -> bool:
        if not isinstance(payload, dict) or not payload:
            return False
        if str(payload.get("symbol") or "").upper() != str(symbol).upper():
            return False
        return isinstance(payload.get("validation_report"), dict)

    @staticmethod
    def approval_usable(payload: dict[str, Any]) -> bool:
        report = _safe_mapping(payload.get("validation_report"))
        strip = _safe_mapping(report.get("approval_strip_summary"))
        approve_value = str(strip.get("approve_value") or "").strip().lower()
        if approve_value in {"approval usable", "approved", "go"}:
            return True
        if approve_value and approve_value not in {"n/a", "na", "not_available", "unavailable", "unknown"}:
            return False
        deployment_summary = _safe_mapping(report.get("deployment_approval_summary"))
        go_no_go = (
            payload.get("playbook_go_no_go")
            or payload.get("approval_playbook_go_no_go")
            or report.get("playbook_go_no_go")
            or deployment_summary.get("playbook_go_no_go")
            or payload.get("deployment_go_no_go")
            or payload.get("approval_topline_status")
            or report.get("approval_topline_status")
            or deployment_summary.get("topline_status")
        )
        return str(go_no_go or "").strip().upper() in {"GO", "PASS", "APPROVED", "APPROVAL_USABLE"}

    def _load_disk_payload(self, symbol: str) -> tuple[dict[str, Any] | None, float | None]:
        path = self.path(symbol)
        if not path.exists():
            return None, None
        try:
            cache_mtime = path.stat().st_mtime
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, None
        if not self.valid_payload(symbol, payload):
            return None, None
        return payload, cache_mtime

    def memory_entry_stale_for_database(self, symbol: str) -> bool:
        if not self.stale_on_database_change():
            return False
        path = self.path(symbol)
        try:
            if not path.exists():
                return False
            return self.stale_for_database(path.stat().st_mtime)
        except OSError:
            return True

    def load(self, symbol: str) -> dict[str, Any] | None:
        cache_key = self.key(symbol)
        cached_entry = READ_ONLY_RECOMPUTE_CACHE.get(cache_key)
        if cached_entry is not None:
            expires_at, cached_payload = cached_entry
            if expires_at > time.monotonic():
                if self.valid_payload(symbol, cached_payload) and not self.memory_entry_stale_for_database(symbol):
                    return copy.deepcopy(cached_payload)
                READ_ONLY_RECOMPUTE_CACHE.pop(cache_key, None)
                return None
            READ_ONLY_RECOMPUTE_CACHE.pop(cache_key, None)

        payload, cache_mtime = self._load_disk_payload(symbol)
        if payload is None or cache_mtime is None:
            return None
        try:
            age_seconds = max(time.time() - cache_mtime, 0.0)
        except OSError:
            return None
        if age_seconds > self.max_age_seconds():
            return None
        if self.stale_on_database_change() and self.stale_for_database(cache_mtime):
            return None
        READ_ONLY_RECOMPUTE_CACHE[cache_key] = (
            time.monotonic() + min(READ_ONLY_RECOMPUTE_CACHE_TTL_SECONDS, self.max_age_seconds() - age_seconds),
            copy.deepcopy(payload),
        )
        return payload

    def load_stale_conservative(self, symbol: str) -> dict[str, Any] | None:
        payload, _cache_mtime = self._load_disk_payload(symbol)
        if payload is None or self.approval_usable(payload):
            return None
        return copy.deepcopy(payload)

    def store(self, symbol: str, payload: dict[str, Any]) -> None:
        cache_key = self.key(symbol)
        cached_payload = copy.deepcopy(dict(payload))
        if not self.valid_payload(symbol, cached_payload):
            return
        READ_ONLY_RECOMPUTE_CACHE[cache_key] = (
            time.monotonic() + min(READ_ONLY_RECOMPUTE_CACHE_TTL_SECONDS, self.max_age_seconds()),
            cached_payload,
        )
        path = self.path(symbol)
        tmp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(json.dumps(cached_payload, ensure_ascii=False, default=str), encoding="utf-8")
            tmp_path.replace(path)
        except OSError:
            return
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
