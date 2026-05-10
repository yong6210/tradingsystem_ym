from __future__ import annotations

import os
import time
from types import SimpleNamespace

from app.services.validation_payload_cache import READ_ONLY_RECOMPUTE_CACHE, ValidationPayloadCacheService


def test_validation_payload_cache_uses_ttl_even_when_database_is_newer_by_default(tmp_path) -> None:
    READ_ONLY_RECOMPUTE_CACHE.clear()
    try:
        db_path = tmp_path / "trading.db"
        db_path.write_text("", encoding="utf-8")
        cache = ValidationPayloadCacheService(
            SimpleNamespace(
                database_url=f"sqlite:///{db_path}",
                strategy_version="v1",
                validation_report_dir=str(tmp_path / "reports"),
                validation_payload_cache_stale_on_database_change=False,
            )
        )
        payload = {"symbol": "BTCUSDC", "validation_report": {"cached": True}}

        cache.store("BTCUSDC", payload)
        assert cache.load("BTCUSDC") == payload

        cache_path = cache.path("BTCUSDC")
        newer_mtime = max(time.time(), cache_path.stat().st_mtime) + 5.0
        os.utime(db_path, (newer_mtime, newer_mtime))

        assert cache.load("BTCUSDC") == payload
    finally:
        READ_ONLY_RECOMPUTE_CACHE.clear()


def test_validation_payload_cache_can_invalidate_when_database_is_newer(tmp_path) -> None:
    READ_ONLY_RECOMPUTE_CACHE.clear()
    try:
        db_path = tmp_path / "trading.db"
        db_path.write_text("", encoding="utf-8")
        cache = ValidationPayloadCacheService(
            SimpleNamespace(
                database_url=f"sqlite:///{db_path}",
                strategy_version="v1",
                validation_report_dir=str(tmp_path / "reports"),
                validation_payload_cache_stale_on_database_change=True,
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


def test_validation_payload_cache_can_load_stale_conservative_payload(tmp_path) -> None:
    READ_ONLY_RECOMPUTE_CACHE.clear()
    try:
        cache = ValidationPayloadCacheService(
            SimpleNamespace(
                database_url=f"sqlite:///{tmp_path / 'trading.db'}",
                strategy_version="v1",
                validation_report_dir=str(tmp_path / "reports"),
                validation_payload_cache_max_age_seconds=1,
                validation_payload_cache_stale_on_database_change=False,
            )
        )
        payload = {
            "symbol": "BTCUSDC",
            "playbook_go_no_go": "MANUAL_REVIEW",
            "validation_report": {
                "approval_strip_summary": {
                    "approve_value": "manual review first",
                }
            },
        }

        cache.store("BTCUSDC", payload)
        cache_path = cache.path("BTCUSDC")
        old_mtime = time.time() - 60.0
        os.utime(cache_path, (old_mtime, old_mtime))
        READ_ONLY_RECOMPUTE_CACHE.clear()

        assert cache.load("BTCUSDC") is None
        assert cache.load_stale_conservative("BTCUSDC") == payload
    finally:
        READ_ONLY_RECOMPUTE_CACHE.clear()


def test_validation_payload_cache_does_not_load_stale_approval_usable_payload(tmp_path) -> None:
    READ_ONLY_RECOMPUTE_CACHE.clear()
    try:
        cache = ValidationPayloadCacheService(
            SimpleNamespace(
                database_url=f"sqlite:///{tmp_path / 'trading.db'}",
                strategy_version="v1",
                validation_report_dir=str(tmp_path / "reports"),
                validation_payload_cache_max_age_seconds=1,
                validation_payload_cache_stale_on_database_change=False,
            )
        )
        payload = {
            "symbol": "BTCUSDC",
            "playbook_go_no_go": "GO",
            "validation_report": {
                "approval_strip_summary": {
                    "approve_value": "approval usable",
                }
            },
        }

        cache.store("BTCUSDC", payload)
        cache_path = cache.path("BTCUSDC")
        old_mtime = time.time() - 60.0
        os.utime(cache_path, (old_mtime, old_mtime))
        READ_ONLY_RECOMPUTE_CACHE.clear()

        assert cache.load("BTCUSDC") is None
        assert cache.load_stale_conservative("BTCUSDC") is None
    finally:
        READ_ONLY_RECOMPUTE_CACHE.clear()


def test_validation_payload_cache_rejects_stale_go_from_deployment_summary(tmp_path) -> None:
    READ_ONLY_RECOMPUTE_CACHE.clear()
    try:
        cache = ValidationPayloadCacheService(
            SimpleNamespace(
                database_url=f"sqlite:///{tmp_path / 'trading.db'}",
                strategy_version="v1",
                validation_report_dir=str(tmp_path / "reports"),
                validation_payload_cache_max_age_seconds=1,
                validation_payload_cache_stale_on_database_change=False,
            )
        )
        payload = {
            "symbol": "BTCUSDC",
            "validation_report": {
                "deployment_approval_summary": {
                    "playbook_go_no_go": "GO",
                    "playbook_action": "proceed_with_configured_rollout",
                },
                "approval_strip_summary": {},
            },
        }

        cache.store("BTCUSDC", payload)
        cache_path = cache.path("BTCUSDC")
        old_mtime = time.time() - 60.0
        os.utime(cache_path, (old_mtime, old_mtime))
        READ_ONLY_RECOMPUTE_CACHE.clear()

        assert cache.load("BTCUSDC") is None
        assert cache.load_stale_conservative("BTCUSDC") is None
    finally:
        READ_ONLY_RECOMPUTE_CACHE.clear()


def test_validation_payload_cache_rejects_stale_pass_topline_when_playbook_missing(tmp_path) -> None:
    READ_ONLY_RECOMPUTE_CACHE.clear()
    try:
        cache = ValidationPayloadCacheService(
            SimpleNamespace(
                database_url=f"sqlite:///{tmp_path / 'trading.db'}",
                strategy_version="v1",
                validation_report_dir=str(tmp_path / "reports"),
                validation_payload_cache_max_age_seconds=1,
                validation_payload_cache_stale_on_database_change=False,
            )
        )
        payload = {
            "symbol": "BTCUSDC",
            "validation_report": {
                "deployment_approval_summary": {
                    "topline_status": "PASS",
                    "topline_code": "approval_template_ready",
                },
                "approval_strip_summary": {},
            },
        }

        cache.store("BTCUSDC", payload)
        cache_path = cache.path("BTCUSDC")
        old_mtime = time.time() - 60.0
        os.utime(cache_path, (old_mtime, old_mtime))
        READ_ONLY_RECOMPUTE_CACHE.clear()

        assert cache.load("BTCUSDC") is None
        assert cache.load_stale_conservative("BTCUSDC") is None
    finally:
        READ_ONLY_RECOMPUTE_CACHE.clear()


def test_validation_payload_cache_rejects_stale_go_when_strip_approve_is_not_informative(tmp_path) -> None:
    READ_ONLY_RECOMPUTE_CACHE.clear()
    try:
        cache = ValidationPayloadCacheService(
            SimpleNamespace(
                database_url=f"sqlite:///{tmp_path / 'trading.db'}",
                strategy_version="v1",
                validation_report_dir=str(tmp_path / "reports"),
                validation_payload_cache_max_age_seconds=1,
                validation_payload_cache_stale_on_database_change=False,
            )
        )
        payload = {
            "symbol": "BTCUSDC",
            "approval_playbook_go_no_go": "GO",
            "validation_report": {
                "approval_strip_summary": {
                    "approve_value": "n/a",
                },
            },
        }

        cache.store("BTCUSDC", payload)
        cache_path = cache.path("BTCUSDC")
        old_mtime = time.time() - 60.0
        os.utime(cache_path, (old_mtime, old_mtime))
        READ_ONLY_RECOMPUTE_CACHE.clear()

        assert cache.load("BTCUSDC") is None
        assert cache.load_stale_conservative("BTCUSDC") is None
    finally:
        READ_ONLY_RECOMPUTE_CACHE.clear()


def test_validation_payload_cache_keeps_stale_manual_review_even_when_topline_passes(tmp_path) -> None:
    READ_ONLY_RECOMPUTE_CACHE.clear()
    try:
        cache = ValidationPayloadCacheService(
            SimpleNamespace(
                database_url=f"sqlite:///{tmp_path / 'trading.db'}",
                strategy_version="v1",
                validation_report_dir=str(tmp_path / "reports"),
                validation_payload_cache_max_age_seconds=1,
                validation_payload_cache_stale_on_database_change=False,
            )
        )
        payload = {
            "symbol": "BTCUSDC",
            "approval_topline_status": "PASS",
            "validation_report": {
                "approval_strip_summary": {
                    "approve_value": "manual review first",
                },
            },
        }

        cache.store("BTCUSDC", payload)
        cache_path = cache.path("BTCUSDC")
        old_mtime = time.time() - 60.0
        os.utime(cache_path, (old_mtime, old_mtime))
        READ_ONLY_RECOMPUTE_CACHE.clear()

        assert cache.load("BTCUSDC") is None
        assert cache.load_stale_conservative("BTCUSDC") == payload
    finally:
        READ_ONLY_RECOMPUTE_CACHE.clear()


def test_validation_payload_cache_handles_malformed_nested_contracts_without_approving_go(tmp_path) -> None:
    READ_ONLY_RECOMPUTE_CACHE.clear()
    try:
        cache = ValidationPayloadCacheService(
            SimpleNamespace(
                database_url=f"sqlite:///{tmp_path / 'trading.db'}",
                strategy_version="v1",
                validation_report_dir=str(tmp_path / "reports"),
                validation_payload_cache_max_age_seconds=1,
                validation_payload_cache_stale_on_database_change=False,
            )
        )
        payload = {
            "symbol": "BTCUSDC",
            "approval_playbook_go_no_go": "GO",
            "validation_report": {
                "approval_strip_summary": ["broken"],
                "deployment_approval_summary": "broken",
            },
        }

        cache.store("BTCUSDC", payload)
        cache_path = cache.path("BTCUSDC")
        old_mtime = time.time() - 60.0
        os.utime(cache_path, (old_mtime, old_mtime))
        READ_ONLY_RECOMPUTE_CACHE.clear()

        assert cache.load("BTCUSDC") is None
        assert cache.load_stale_conservative("BTCUSDC") is None
    finally:
        READ_ONLY_RECOMPUTE_CACHE.clear()


def test_validation_payload_cache_keeps_malformed_nested_contracts_conservative_without_go(tmp_path) -> None:
    READ_ONLY_RECOMPUTE_CACHE.clear()
    try:
        cache = ValidationPayloadCacheService(
            SimpleNamespace(
                database_url=f"sqlite:///{tmp_path / 'trading.db'}",
                strategy_version="v1",
                validation_report_dir=str(tmp_path / "reports"),
                validation_payload_cache_max_age_seconds=1,
                validation_payload_cache_stale_on_database_change=False,
            )
        )
        payload = {
            "symbol": "BTCUSDC",
            "playbook_go_no_go": "MANUAL_REVIEW",
            "validation_report": {
                "approval_strip_summary": ["broken"],
                "deployment_approval_summary": "broken",
            },
        }

        cache.store("BTCUSDC", payload)
        cache_path = cache.path("BTCUSDC")
        old_mtime = time.time() - 60.0
        os.utime(cache_path, (old_mtime, old_mtime))
        READ_ONLY_RECOMPUTE_CACHE.clear()

        assert cache.load("BTCUSDC") is None
        assert cache.load_stale_conservative("BTCUSDC") == payload
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
