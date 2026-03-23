from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete

from app.core.config import get_settings
from app.db.models import AlertRetryTask, AlertSubscription
from app.db.session import SessionLocal, init_db
from app.services.notification_dispatcher import NotificationDispatcher
from app.services.strategy_engine import StrategyEngine


def test_failed_alert_is_enqueued_and_retry_processor_delivers(monkeypatch) -> None:
    init_db()
    NotificationDispatcher.reset_circuit_state()
    settings = get_settings()
    old_url = settings.alert_discord_webhook_url
    old_retry_attempts = settings.alert_retry_attempts
    old_retry_backoff = settings.alert_retry_backoff_seconds
    old_queue_attempts = settings.alert_retry_queue_max_attempts
    old_queue_backoff = settings.alert_retry_queue_backoff_seconds
    old_queue_jitter = settings.alert_retry_queue_jitter_seconds

    calls: list[int] = []

    class _Response:
        def __init__(self, status_code: int):
            self.status_code = status_code

    class _Client:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            pass

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
            return False

        def post(self, url, json=None, headers=None):  # noqa: ANN001
            calls.append(1)
            if len(calls) == 1:
                return _Response(503)
            return _Response(204)

    try:
        settings.alert_discord_webhook_url = "https://discord.example/retry-queue"
        settings.alert_retry_attempts = 1
        settings.alert_retry_backoff_seconds = 0.0
        settings.alert_retry_queue_max_attempts = 3
        settings.alert_retry_queue_backoff_seconds = 0.0
        settings.alert_retry_queue_jitter_seconds = 0.0
        monkeypatch.setattr("app.services.notification_dispatcher.httpx.Client", _Client)

        with SessionLocal() as db:
            db.execute(delete(AlertSubscription))
            db.execute(delete(AlertRetryTask))
            db.commit()
            engine = StrategyEngine(db)
            result = engine.send_test_alert(
                channel="discord",
                symbol="BTCUSDC",
                message="retry queue test",
                payload={"source": "test_alert_retry_queue"},
            )

            assert result["delivery"]["delivered"] is False
            assert result["retry_queued"] == 1

            status_before = engine.alert_retry_queue_status()
            assert status_before["counts"]["queued"] == 1

            processed = engine.process_alert_retry_queue(limit=10)
            assert processed["scanned"] == 1
            assert processed["delivered"] == 1
            assert processed["requeued"] == 0
            assert processed["dead_lettered"] == 0

            status_after = engine.alert_retry_queue_status()
            assert status_after["counts"]["delivered"] == 1
    finally:
        settings.alert_discord_webhook_url = old_url
        settings.alert_retry_attempts = old_retry_attempts
        settings.alert_retry_backoff_seconds = old_retry_backoff
        settings.alert_retry_queue_max_attempts = old_queue_attempts
        settings.alert_retry_queue_backoff_seconds = old_queue_backoff
        settings.alert_retry_queue_jitter_seconds = old_queue_jitter


def test_retry_queue_dead_letters_and_manual_requeue(monkeypatch) -> None:
    init_db()
    NotificationDispatcher.reset_circuit_state()
    settings = get_settings()
    old_url = settings.alert_discord_webhook_url
    old_retry_attempts = settings.alert_retry_attempts
    old_retry_backoff = settings.alert_retry_backoff_seconds
    old_queue_attempts = settings.alert_retry_queue_max_attempts
    old_queue_backoff = settings.alert_retry_queue_backoff_seconds
    old_queue_jitter = settings.alert_retry_queue_jitter_seconds

    class _Response:
        status_code = 503

    class _Client:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            pass

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
            return False

        def post(self, url, json=None, headers=None):  # noqa: ANN001
            return _Response()

    try:
        settings.alert_discord_webhook_url = "https://discord.example/dead-letter"
        settings.alert_retry_attempts = 1
        settings.alert_retry_backoff_seconds = 0.0
        settings.alert_retry_queue_max_attempts = 1
        settings.alert_retry_queue_backoff_seconds = 0.0
        settings.alert_retry_queue_jitter_seconds = 0.0
        monkeypatch.setattr("app.services.notification_dispatcher.httpx.Client", _Client)

        with SessionLocal() as db:
            db.execute(delete(AlertSubscription))
            db.execute(delete(AlertRetryTask))
            db.commit()
            engine = StrategyEngine(db)
            result = engine.send_test_alert(
                channel="discord",
                symbol="ETHUSDC",
                message="dead letter test",
                payload={"source": "test_alert_retry_queue"},
            )

            assert result["retry_queued"] == 1
            processed = engine.process_alert_retry_queue(limit=10)
            assert processed["dead_lettered"] == 1

            status_dead = engine.alert_retry_queue_status()
            assert status_dead["counts"]["dead_letter"] == 1

            requeued = engine.requeue_dead_letter_alerts(limit=10)
            assert requeued["requeued"] == 1

            status_requeued = engine.alert_retry_queue_status()
            assert status_requeued["counts"]["queued"] == 1
    finally:
        settings.alert_discord_webhook_url = old_url
        settings.alert_retry_attempts = old_retry_attempts
        settings.alert_retry_backoff_seconds = old_retry_backoff
        settings.alert_retry_queue_max_attempts = old_queue_attempts
        settings.alert_retry_queue_backoff_seconds = old_queue_backoff
        settings.alert_retry_queue_jitter_seconds = old_queue_jitter
