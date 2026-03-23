from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import EventStatus
from app.db.models import EventOutbox
from app.db.repositories import EventOutboxRepository

logger = logging.getLogger(__name__)


class EventPublisherError(RuntimeError):
    pass


@dataclass(slots=True)
class EventEnvelope:
    event_id: str
    event_type: str
    event_ts: datetime
    payload: dict[str, Any]
    dedupe_key: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event_ts": self.event_ts.isoformat(),
            "payload": self.payload,
            "dedupe_key": self.dedupe_key,
        }


class _MemoryBackend:
    def publish(self, event: EventEnvelope) -> None:
        logger.info("event.memory published=%s", event.to_dict())


class _RedisStreamBackend:
    def __init__(self, redis_url: str, stream: str):
        try:
            import redis  # type: ignore
        except Exception as exc:  # pragma: no cover - dependency optional
            raise EventPublisherError("redis backend requires `redis` package") from exc
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._stream = stream

    def publish(self, event: EventEnvelope) -> None:
        self._redis.xadd(self._stream, {"data": json.dumps(event.to_dict())})


class _KafkaBackend:
    def __init__(self, bootstrap_servers: str, topic: str):
        try:
            from kafka import KafkaProducer  # type: ignore
        except Exception as exc:  # pragma: no cover - dependency optional
            raise EventPublisherError("kafka backend requires `kafka-python` package") from exc

        self._producer = KafkaProducer(
            bootstrap_servers=[x.strip() for x in bootstrap_servers.split(",") if x.strip()],
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda v: v.encode("utf-8"),
            acks="all",
        )
        self._topic = topic

    def publish(self, event: EventEnvelope) -> None:
        future = self._producer.send(self._topic, key=event.dedupe_key, value=event.to_dict())
        future.get(timeout=5)


class EventBus:
    """Event outbox with dedupe + late-event policy and backend dispatch.

    Policy:
    - Duplicates: same `dedupe_key` inside configured dedupe window are marked `duplicate`.
    - Late events: event_ts older than `event_late_seconds` are marked `skipped_late`.
    - Failed publish: status `failed` with retry timestamp for reprocessor.
    """

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.repo = EventOutboxRepository(db)
        self.backend = self._build_backend()

    def _build_backend(self):
        backend = self.settings.event_backend.lower()
        if backend == "redis":
            return _RedisStreamBackend(
                redis_url=self.settings.event_redis_url,
                stream=self.settings.event_redis_stream,
            )
        if backend == "kafka":
            return _KafkaBackend(
                bootstrap_servers=self.settings.event_kafka_bootstrap_servers,
                topic=self.settings.event_kafka_topic,
            )
        return _MemoryBackend()

    @staticmethod
    def _to_utc(value: Any) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        return datetime.now(timezone.utc)

    def _build_envelope(self, event_type: str, payload: dict[str, Any]) -> EventEnvelope:
        event_ts = self._to_utc(payload.get("event_ts"))
        dedupe_key = str(
            payload.get("dedupe_key")
            or f"{event_type}:{payload.get('symbol', '')}:{event_ts.strftime('%Y%m%d%H%M')}"
        )
        return EventEnvelope(
            event_id=f"evt_{uuid.uuid4().hex}",
            event_type=event_type,
            event_ts=event_ts,
            payload=payload,
            dedupe_key=dedupe_key,
        )

    def _dispatch(self, row: EventOutbox) -> None:
        self.repo.increment_attempt(row)
        envelope = EventEnvelope(
            event_id=row.event_id,
            event_type=row.event_type,
            event_ts=self._to_utc(row.event_ts),
            payload=row.payload,
            dedupe_key=row.dedupe_key,
        )
        try:
            self.backend.publish(envelope)
            self.repo.mark_published(row)
        except Exception as exc:  # pragma: no cover - network backend dependent
            logger.exception("event publish failed id=%s type=%s", row.event_id, row.event_type)
            self.repo.mark_failed(
                row=row,
                error=str(exc),
                retry_after_seconds=self.settings.event_retry_backoff_seconds,
            )

    def publish(self, event_type: str, payload: dict[str, Any]) -> EventOutbox:
        # Session uses autoflush=False, force flush so dedupe can see prior events in this txn.
        self.db.flush()
        envelope = self._build_envelope(event_type=event_type, payload=payload)
        prev = self.repo.find_recent_by_dedupe_key(
            dedupe_key=envelope.dedupe_key,
            within_seconds=self.settings.event_dedupe_window_seconds,
        )
        row = EventOutbox(
            event_id=envelope.event_id,
            event_type=envelope.event_type,
            event_ts=envelope.event_ts,
            payload=envelope.payload,
            dedupe_key=envelope.dedupe_key,
            status=EventStatus.PENDING.value,
            backend=self.settings.event_backend,
            attempts=0,
        )
        self.repo.add(row)

        now = datetime.now(timezone.utc)
        if (now - envelope.event_ts).total_seconds() > self.settings.event_late_seconds:
            self.repo.mark_skipped_late(row)
            return row

        if prev:
            self.repo.mark_duplicate(row)
            return row

        self._dispatch(row)
        return row

    def reprocess_pending(self, limit: int | None = None) -> dict[str, int]:
        rows = self.repo.list_reprocessable(
            limit=limit or self.settings.event_reprocess_batch_size,
            max_attempts=self.settings.event_max_attempts,
        )
        stats = {
            "scanned": len(rows),
            "published": 0,
            "failed": 0,
        }
        for row in rows:
            self._dispatch(row)
            if row.status == EventStatus.PUBLISHED.value:
                stats["published"] += 1
            elif row.status == EventStatus.FAILED.value:
                stats["failed"] += 1
        return stats

    def status_snapshot(self) -> dict[str, Any]:
        counts = self.repo.status_counts()
        now = datetime.now(timezone.utc)

        pending_stmt = select(func.min(EventOutbox.created_ts)).where(
            EventOutbox.status.in_([EventStatus.PENDING.value, EventStatus.FAILED.value])
        )
        oldest = self.db.scalar(pending_stmt)
        backlog_age_seconds = 0
        if oldest is not None:
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=timezone.utc)
            backlog_age_seconds = int(max(0.0, (now - oldest).total_seconds()))

        return {
            "backend": self.settings.event_backend,
            "counts": counts,
            "backlog_age_seconds": backlog_age_seconds,
            "retry_policy": {
                "max_attempts": self.settings.event_max_attempts,
                "retry_backoff_seconds": self.settings.event_retry_backoff_seconds,
                "late_seconds": self.settings.event_late_seconds,
                "dedupe_window_seconds": self.settings.event_dedupe_window_seconds,
            },
        }
