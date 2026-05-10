from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import Settings, get_settings
from app.db.models import AlertRetryTask, AlertSubscription
from app.db.repositories import AlertRepository, AlertRetryQueueRepository
from app.services.notification_dispatcher import NotificationDispatcher


def _safe_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


class AlertRetryQueueService:
    def __init__(
        self,
        *,
        repo: AlertRetryQueueRepository,
        alert_repo: AlertRepository,
        dispatcher: NotificationDispatcher,
        settings: Settings | None = None,
    ):
        self.repo = repo
        self.alert_repo = alert_repo
        self.dispatcher = dispatcher
        self.settings = settings or get_settings()

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

    def capture_delivery_failure(
        self,
        *,
        source_alert_id: str,
        symbol: str,
        alert_type: str,
        payload: dict[str, Any],
        delivery: dict[str, Any],
    ) -> list[AlertRetryTask]:
        now = datetime.now(timezone.utc)
        tasks: list[AlertRetryTask] = []
        for item in self._iter_retry_candidates(delivery):
            if not self._should_queue(item):
                continue

            channel = str(item.get("channel", "")).lower()
            target = self._normalize_target(item.get("target"))
            dedupe_key = f"{source_alert_id}:{channel}:{target or 'none'}"
            existing = self.repo.find_open(dedupe_key=dedupe_key)
            if existing is not None:
                continue

            task = AlertRetryTask(
                task_id=f"arq_{int(now.timestamp() * 1_000_000)}_{len(tasks) + 1}",
                source_alert_id=source_alert_id,
                dedupe_key=dedupe_key,
                channel=channel,
                symbol=symbol,
                type=alert_type,
                target=target,
                payload=_safe_mapping(payload),
                status="queued",
                attempts=0,
                max_attempts=max(1, self._safe_int(self.settings.alert_retry_queue_max_attempts, default=4)),
                next_retry_ts=now + timedelta(seconds=self._next_delay_seconds(reason=str(item.get('reason', '')), attempt=0)),
                last_reason=str(item.get("reason", "unknown"))[:200],
                last_status_code=self._status_code(item),
            )
            self.repo.add(task)
            tasks.append(task)
        return tasks

    def process_due(self, *, limit: int) -> dict[str, int]:
        rows = self.repo.list_due(limit=max(1, limit))
        stats = {
            "scanned": len(rows),
            "delivered": 0,
            "requeued": 0,
            "dead_lettered": 0,
        }
        now = datetime.now(timezone.utc)

        for row in rows:
            self.repo.increment_attempt(row)
            row_payload = _safe_mapping(row.payload)
            delivery = self.dispatcher.dispatch(
                channel=row.channel,
                alert_type=row.type,
                symbol=row.symbol,
                payload=row_payload,
            )
            self.alert_repo.add(
                AlertSubscription(
                    alert_id=f"alert_retry_{row.task_id}_{row.attempts}_{int(now.timestamp() * 1_000_000)}",
                    plan_id=None,
                    symbol=row.symbol,
                    channel=row.channel,
                    type=row.type,
                    payload={
                        **row_payload,
                        "retry_queue": {
                            "task_id": row.task_id,
                            "attempt": row.attempts,
                            "source_alert_id": row.source_alert_id,
                        },
                        "delivery": delivery,
                    },
                    triggered_ts=now,
                )
            )

            if NotificationDispatcher._safe_bool(delivery.get("delivered")):
                self.repo.mark_delivered(
                    row,
                    reason=str(delivery.get("reason", "delivered")),
                    status_code=self._status_code(delivery),
                )
                stats["delivered"] += 1
                continue

            if self._should_queue(delivery) and row.attempts < row.max_attempts:
                next_retry_ts = now + timedelta(
                    seconds=self._next_delay_seconds(reason=str(delivery.get("reason", "")), attempt=row.attempts)
                )
                self.repo.reschedule(
                    row,
                    reason=str(delivery.get("reason", "retry_scheduled")),
                    status_code=self._status_code(delivery),
                    next_retry_ts=next_retry_ts,
                )
                stats["requeued"] += 1
                continue

            self.repo.mark_dead_letter(
                row,
                reason=str(delivery.get("reason", "dead_letter"))[:200],
                status_code=self._status_code(delivery),
            )
            stats["dead_lettered"] += 1

        return stats

    def requeue_dead_letters(self, *, limit: int) -> dict[str, int]:
        rows = self.repo.list_dead_letter(limit=max(1, limit))
        now = datetime.now(timezone.utc)
        for row in rows:
            self.repo.requeue(row, next_retry_ts=now)
        return {
            "scanned": len(rows),
            "requeued": len(rows),
        }

    def status_snapshot(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        counts = self.repo.status_counts()
        oldest_queued = self.repo.oldest_queued()
        oldest_dead_letter = self.repo.oldest_dead_letter()

        backlog_age_seconds = self._age_seconds(now=now, ts=oldest_queued.created_ts if oldest_queued else None)
        dead_letter_oldest_age_seconds = self._age_seconds(
            now=now,
            ts=oldest_dead_letter.dead_letter_ts if oldest_dead_letter else None,
        )
        next_retry_in_seconds = 0
        if oldest_queued is not None:
            retry_ts = oldest_queued.next_retry_ts
            if retry_ts.tzinfo is None:
                retry_ts = retry_ts.replace(tzinfo=timezone.utc)
            next_retry_in_seconds = int(max(0.0, (retry_ts - now).total_seconds()))

        return {
            "counts": counts,
            "backlog_age_seconds": backlog_age_seconds,
            "dead_letter_oldest_age_seconds": dead_letter_oldest_age_seconds,
            "next_retry_in_seconds": next_retry_in_seconds,
            "retry_policy": {
                "max_attempts": self._safe_int(self.settings.alert_retry_queue_max_attempts, default=4),
                "retry_backoff_seconds": self._safe_float(self.settings.alert_retry_queue_backoff_seconds, default=30.0),
                "retry_jitter_seconds": self._safe_float(self.settings.alert_retry_queue_jitter_seconds),
                "circuit_cooldown_seconds": self._safe_int(self.settings.alert_circuit_breaker_cooldown_seconds, default=90),
            },
        }

    @staticmethod
    def _iter_retry_candidates(delivery: dict[str, Any]) -> list[dict[str, Any]]:
        if str(delivery.get("channel")) == "system" and isinstance(delivery.get("results"), list):
            return [item for item in delivery["results"] if isinstance(item, dict)]
        return [delivery]

    @staticmethod
    def _normalize_target(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _status_code(payload: dict[str, Any]) -> int | None:
        value = payload.get("status_code")
        if isinstance(value, int):
            return value
        return None

    @staticmethod
    def _age_seconds(*, now: datetime, ts: datetime | None) -> int:
        if ts is None:
            return 0
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return int(max(0.0, (now - ts).total_seconds()))

    def _should_queue(self, delivery: dict[str, Any]) -> bool:
        if NotificationDispatcher._safe_bool(delivery.get("delivered")):
            return False

        reason = str(delivery.get("reason", ""))
        if NotificationDispatcher._safe_bool(delivery.get("skipped")):
            return reason == "circuit_open"

        if reason == "delivery_failed_unknown":
            return True
        if reason.startswith("exception:"):
            return True
        if reason.startswith("http_"):
            try:
                status_code = int(reason.split("_", 1)[1])
            except ValueError:
                return False
            return status_code == 429 or status_code >= 500
        return False

    def _next_delay_seconds(self, *, reason: str, attempt: int) -> float:
        if reason == "circuit_open":
            return float(max(0, self._safe_int(self.settings.alert_circuit_breaker_cooldown_seconds, default=90)))

        base = max(0.0, self._safe_float(self.settings.alert_retry_queue_backoff_seconds, default=30.0))
        jitter = max(0.0, self._safe_float(self.settings.alert_retry_queue_jitter_seconds))
        delay = base * (2 ** max(0, attempt))
        if jitter > 0:
            delay += random.uniform(0.0, jitter)
        return delay
