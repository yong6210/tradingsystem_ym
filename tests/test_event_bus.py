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

        db.commit()

        assert first.status == "published"
        assert duplicate.status == "duplicate"
        assert late.status == "skipped_late"
