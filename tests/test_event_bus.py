from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.core.config import get_settings
from app.db.models import EventOutbox
from app.db.session import SessionLocal, init_db
from app.services.event_bus import EventBus


def test_event_bus_duplicate_and_late_policy() -> None:
    init_db()
    settings = get_settings()
    with SessionLocal() as db:
        db.execute(delete(EventOutbox))
        db.commit()

        bus = EventBus(db)
        first = bus.publish(
            "zone.created",
            {"symbol": "BTCUSDC", "dedupe_key": "z:btc:1"},
        )
        duplicate = bus.publish(
            "zone.created",
            {"symbol": "BTCUSDC", "dedupe_key": "z:btc:1"},
        )

        old_ts = (datetime.now(timezone.utc) - timedelta(seconds=settings.event_late_seconds + 15)).isoformat()
        late = bus.publish(
            "plan.generated",
            {"symbol": "BTCUSDC", "dedupe_key": "p:btc:1", "event_ts": old_ts},
        )
        malformed_ts = bus.publish(
            "plan.generated",
            {"symbol": "BTCUSDC", "dedupe_key": "p:btc:bad-ts", "event_ts": "legacy-invalid-timestamp"},
        )

        db.commit()

        assert first.status == "published"
        assert duplicate.status == "duplicate"
        assert late.status == "skipped_late"
        assert malformed_ts.status == "published"


def test_event_bus_tolerates_malformed_numeric_settings() -> None:
    init_db()
    settings = get_settings()
    original_values = {
        "event_late_seconds": settings.event_late_seconds,
        "event_retry_backoff_seconds": settings.event_retry_backoff_seconds,
        "event_max_attempts": settings.event_max_attempts,
        "event_reprocess_batch_size": settings.event_reprocess_batch_size,
        "event_dedupe_window_seconds": settings.event_dedupe_window_seconds,
    }
    try:
        settings.event_late_seconds = "bad"
        settings.event_retry_backoff_seconds = float("inf")
        settings.event_max_attempts = "bad"
        settings.event_reprocess_batch_size = "bad"
        settings.event_dedupe_window_seconds = "bad"

        with SessionLocal() as db:
            db.execute(delete(EventOutbox))
            db.commit()

            bus = EventBus(db)
            late = bus.publish(
                "plan.generated",
                {
                    "symbol": "BTCUSDC",
                    "dedupe_key": "p:btc:malformed-settings",
                    "event_ts": (datetime.now(timezone.utc) - timedelta(seconds=91)).isoformat(),
                },
            )
            stats = bus.reprocess_pending()
            snapshot = bus.status_snapshot()
            db.commit()

            assert late.status == "skipped_late"
            assert stats["scanned"] == 0
            assert snapshot["retry_policy"] == {
                "max_attempts": 8,
                "retry_backoff_seconds": 10,
                "late_seconds": 90,
                "dedupe_window_seconds": 120,
            }
    finally:
        for key, value in original_values.items():
            setattr(settings, key, value)
