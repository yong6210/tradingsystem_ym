from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import time
from typing import Any
from urllib.parse import unquote

from app.core.config import Settings


READ_ONLY_RECOMPUTE_CACHE_TTL_SECONDS = 120.0
VALIDATION_PAYLOAD_CACHE_MAX_AGE_SECONDS = 900.0
READ_ONLY_RECOMPUTE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


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

    def _sqlite_database_artifact_paths(self) -> list[Path]:
        database_url = str(getattr(self.settings, "database_url", ""))
        if not database_url.startswith("sqlite:///"):
            return []
        raw_path = unquote(database_url.removeprefix("sqlite:///").split("?", 1)[0])
        if not raw_path or raw_path == ":memory:":
            return []
        db_path = Path(raw_path).expanduser()
        return [db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")]

    def _stale_for_database(self, cache_mtime: float) -> bool:
        for artifact_path in self._sqlite_database_artifact_paths():
            try:
                if artifact_path.exists() and artifact_path.stat().st_mtime > cache_mtime:
                    return True
            except OSError:
                continue
        return False

    @staticmethod
    def _valid_payload(symbol: str, payload: Any) -> bool:
        if not isinstance(payload, dict) or not payload:
            return False
        if str(payload.get("symbol") or "").upper() != str(symbol).upper():
            return False
        return isinstance(payload.get("validation_report"), dict)

    def load(self, symbol: str) -> dict[str, Any] | None:
        cache_key = self.key(symbol)
        cached_entry = READ_ONLY_RECOMPUTE_CACHE.get(cache_key)
        if cached_entry is not None:
            expires_at, cached_payload = cached_entry
            if expires_at > time.monotonic():
                if self._valid_payload(symbol, cached_payload):
                    return copy.deepcopy(cached_payload)
                READ_ONLY_RECOMPUTE_CACHE.pop(cache_key, None)
                return None
            READ_ONLY_RECOMPUTE_CACHE.pop(cache_key, None)

        path = self.path(symbol)
        if not path.exists():
            return None
        try:
            cache_mtime = path.stat().st_mtime
            age_seconds = max(time.time() - cache_mtime, 0.0)
        except OSError:
            return None
        if age_seconds > VALIDATION_PAYLOAD_CACHE_MAX_AGE_SECONDS:
            return None
        if self._stale_for_database(cache_mtime):
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not self._valid_payload(symbol, payload):
            return None
        READ_ONLY_RECOMPUTE_CACHE[cache_key] = (
            time.monotonic() + READ_ONLY_RECOMPUTE_CACHE_TTL_SECONDS,
            copy.deepcopy(payload),
        )
        return payload

    def store(self, symbol: str, payload: dict[str, Any]) -> None:
        cache_key = self.key(symbol)
        cached_payload = copy.deepcopy(dict(payload))
        if not self._valid_payload(symbol, cached_payload):
            return
        READ_ONLY_RECOMPUTE_CACHE[cache_key] = (
            time.monotonic() + READ_ONLY_RECOMPUTE_CACHE_TTL_SECONDS,
            cached_payload,
        )
        path = self.path(symbol)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cached_payload, ensure_ascii=False, default=str), encoding="utf-8")
        except OSError:
            return
