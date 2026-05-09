from __future__ import annotations

import os
import time
from types import SimpleNamespace

from app.services.validation_payload_cache import READ_ONLY_RECOMPUTE_CACHE, ValidationPayloadCacheService


def test_validation_payload_cache_invalidates_memory_when_database_is_newer(tmp_path) -> None:
    READ_ONLY_RECOMPUTE_CACHE.clear()
    try:
        db_path = tmp_path / "trading.db"
        db_path.write_text("", encoding="utf-8")
        cache = ValidationPayloadCacheService(
            SimpleNamespace(
                database_url=f"sqlite:///{db_path}",
                strategy_version="v1",
                validation_report_dir=str(tmp_path / "reports"),
            )
        )
        payload = {"symbol": "BTCUSDC", "validation_report": {"cached": True}}

        cache.store("BTCUSDC", payload)
        assert cache.load("BTCUSDC") == payload

        cache_path = cache.path("BTCUSDC")
        newer_mtime = max(time.time(), cache_path.stat().st_mtime) + 5.0
        os.utime(db_path, (newer_mtime, newer_mtime))

        assert cache.load("BTCUSDC") is None
    finally:
        READ_ONLY_RECOMPUTE_CACHE.clear()


def test_validation_payload_cache_tracks_sqlite_pysqlite_artifacts(tmp_path) -> None:
    db_path = tmp_path / "trading.db"
    cache = ValidationPayloadCacheService(
        SimpleNamespace(
            database_url=f"sqlite+pysqlite:///{db_path}?mode=ro",
            strategy_version="v1",
            validation_report_dir=str(tmp_path / "reports"),
        )
    )

    assert cache.sqlite_database_artifact_paths() == [
        db_path,
        tmp_path / "trading.db-wal",
        tmp_path / "trading.db-shm",
    ]
