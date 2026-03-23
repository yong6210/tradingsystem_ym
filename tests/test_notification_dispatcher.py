from __future__ import annotations

from app.core.config import get_settings
from app.services.notification_dispatcher import NotificationDispatcher


def test_dispatcher_system_skips_when_no_route_configured(monkeypatch) -> None:
    NotificationDispatcher.reset_circuit_state()
    settings = get_settings()
    monkeypatch.setattr(settings, "alert_telegram_bot_token", "")
    monkeypatch.setattr(settings, "alert_telegram_chat_id", "")
    monkeypatch.setattr(settings, "alert_discord_webhook_url", "")
    monkeypatch.setattr(settings, "alert_push_webhook_url", "")
    dispatcher = NotificationDispatcher(settings)
    result = dispatcher.dispatch(
        channel="system",
        alert_type="validation_warn",
        symbol="BTCUSDC",
        payload={"status": "WARN"},
    )

    assert result["channel"] == "system"
    assert result["delivered"] is False
    assert result["skipped"] is True
    assert result["reason"] == "system_no_routes_configured"
    assert result["routes"] == []
    assert result["results"] == []


def test_dispatcher_format_message_includes_approval_topline_summary_line() -> None:
    message = NotificationDispatcher._format_message(
        alert_type="validation_warn",
        symbol="BTCUSDC",
        payload={
            "status": "WARN",
            "deployment_go_no_go": "NO_GO",
            "deployment_code": "no_go_proxy_selected_trial_against_replay_backed_worst_scenario",
            "approval_playbook_action": "hold_live_rollout_and_keep_prototype_path",
            "approval_topline_summary_line": (
                "winner=runtime_proxy/runtime_validation_proxy_v1; "
                "worst=shock_concentration/FAIL/replay_output; promotion=stay_on_prototype"
            ),
            "version": "v1",
        },
    )

    assert "deployment=NO_GO/no_go_proxy_selected_trial_against_replay_backed_worst_scenario" in message
    assert "playbook_action=hold_live_rollout_and_keep_prototype_path" in message
    assert "approval=winner=runtime_proxy/runtime_validation_proxy_v1;" in message
    assert "status=WARN" in message
    assert "version=v1" in message


def test_dispatcher_discord_delivery_success(monkeypatch) -> None:
    NotificationDispatcher.reset_circuit_state()
    settings = get_settings()
    old_url = settings.alert_discord_webhook_url

    calls: list[dict] = []

    class _Response:
        status_code = 204

    class _Client:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            pass

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
            return False

        def post(self, url, json=None, headers=None):  # noqa: ANN001
            calls.append({"url": url, "json": json, "headers": headers})
            return _Response()

    try:
        settings.alert_discord_webhook_url = "https://discord.example/webhook"
        monkeypatch.setattr("app.services.notification_dispatcher.httpx.Client", _Client)

        dispatcher = NotificationDispatcher(settings)
        result = dispatcher.dispatch(
            channel="discord",
            alert_type="validation_warn",
            symbol="BTCUSDC",
            payload={"status": "WARN", "version": "v1"},
        )

        assert calls
        assert calls[0]["url"] == "https://discord.example/webhook"
        assert "content" in (calls[0]["json"] or {})
        assert result["delivered"] is True
        assert result["reason"] == "delivered"
        assert result["status_code"] == 204
        assert result["latency_ms"] is not None
    finally:
        settings.alert_discord_webhook_url = old_url


def test_dispatcher_system_fanout_delivers_to_configured_routes(monkeypatch) -> None:
    NotificationDispatcher.reset_circuit_state()
    settings = get_settings()
    old_chat_id = settings.alert_telegram_chat_id
    old_bot_token = settings.alert_telegram_bot_token
    old_discord_url = settings.alert_discord_webhook_url

    calls: list[dict] = []

    class _Response:
        status_code = 200

    class _Client:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            pass

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
            return False

        def post(self, url, json=None, headers=None):  # noqa: ANN001
            calls.append({"url": url, "json": json, "headers": headers})
            return _Response()

    try:
        settings.alert_telegram_bot_token = "token123"
        settings.alert_telegram_chat_id = "chat_1234"
        settings.alert_discord_webhook_url = "https://discord.example/fanout"
        monkeypatch.setattr("app.services.notification_dispatcher.httpx.Client", _Client)

        dispatcher = NotificationDispatcher(settings)
        result = dispatcher.dispatch(
            channel="system",
            alert_type="validation_warn",
            symbol="BTCUSDC",
            payload={"status": "WARN"},
        )

        assert result["delivered"] is True
        assert result["skipped"] is False
        assert result["reason"] == "system_delivered_all"
        assert result["routes"] == ["telegram", "discord"]
        assert len(result["results"]) == 2
        assert len(calls) == 2
        assert any("api.telegram.org" in row["url"] for row in calls)
        assert any("discord.example/fanout" in row["url"] for row in calls)
    finally:
        settings.alert_telegram_bot_token = old_bot_token
        settings.alert_telegram_chat_id = old_chat_id
        settings.alert_discord_webhook_url = old_discord_url


def test_dispatcher_push_skips_if_not_configured() -> None:
    NotificationDispatcher.reset_circuit_state()
    dispatcher = NotificationDispatcher()
    result = dispatcher.dispatch(
        channel="push",
        alert_type="validation_fail",
        symbol="ETHUSDC",
        payload={"status": "FAIL"},
    )

    assert result["channel"] == "push"
    assert result["delivered"] is False
    assert result["skipped"] is True
    assert result["reason"] == "push_not_configured"


def test_dispatcher_retries_on_transient_http_then_delivers(monkeypatch) -> None:
    NotificationDispatcher.reset_circuit_state()
    settings = get_settings()
    old_url = settings.alert_discord_webhook_url
    old_attempts = settings.alert_retry_attempts
    old_backoff = settings.alert_retry_backoff_seconds

    calls: list[dict] = []

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
            calls.append({"url": url, "json": json, "headers": headers})
            if len(calls) == 1:
                return _Response(503)
            return _Response(204)

    try:
        settings.alert_discord_webhook_url = "https://discord.example/retry"
        settings.alert_retry_attempts = 3
        settings.alert_retry_backoff_seconds = 0.0
        monkeypatch.setattr("app.services.notification_dispatcher.httpx.Client", _Client)

        dispatcher = NotificationDispatcher(settings)
        result = dispatcher.dispatch(
            channel="discord",
            alert_type="validation_warn",
            symbol="BTCUSDC",
            payload={"status": "WARN"},
        )

        assert len(calls) == 2
        assert result["delivered"] is True
        assert result["reason"] == "delivered"
        assert result["attempts"] == 2
    finally:
        settings.alert_discord_webhook_url = old_url
        settings.alert_retry_attempts = old_attempts
        settings.alert_retry_backoff_seconds = old_backoff


def test_dispatcher_circuit_breaker_skips_after_threshold(monkeypatch) -> None:
    NotificationDispatcher.reset_circuit_state()
    settings = get_settings()
    old_url = settings.alert_discord_webhook_url
    old_attempts = settings.alert_retry_attempts
    old_failures = settings.alert_circuit_breaker_failures
    old_cooldown = settings.alert_circuit_breaker_cooldown_seconds
    old_backoff = settings.alert_retry_backoff_seconds

    calls: list[dict] = []

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
            calls.append({"url": url, "json": json, "headers": headers})
            return _Response()

    try:
        settings.alert_discord_webhook_url = "https://discord.example/circuit"
        settings.alert_retry_attempts = 1
        settings.alert_retry_backoff_seconds = 0.0
        settings.alert_circuit_breaker_failures = 2
        settings.alert_circuit_breaker_cooldown_seconds = 300
        monkeypatch.setattr("app.services.notification_dispatcher.httpx.Client", _Client)

        dispatcher = NotificationDispatcher(settings)
        first = dispatcher.dispatch(
            channel="discord",
            alert_type="validation_warn",
            symbol="BTCUSDC",
            payload={"status": "WARN"},
        )
        second = dispatcher.dispatch(
            channel="discord",
            alert_type="validation_warn",
            symbol="BTCUSDC",
            payload={"status": "WARN"},
        )
        third = dispatcher.dispatch(
            channel="discord",
            alert_type="validation_warn",
            symbol="BTCUSDC",
            payload={"status": "WARN"},
        )

        assert first["delivered"] is False
        assert second["delivered"] is False
        assert third["delivered"] is False
        assert third["skipped"] is True
        assert third["reason"] == "circuit_open"
        assert len(calls) == 2
        snapshot = NotificationDispatcher.circuit_snapshot()
        assert snapshot["discord"]["open_targets"] == 1
        assert snapshot["discord"]["tracked_targets"] == 1
    finally:
        settings.alert_discord_webhook_url = old_url
        settings.alert_retry_attempts = old_attempts
        settings.alert_retry_backoff_seconds = old_backoff
        settings.alert_circuit_breaker_failures = old_failures
        settings.alert_circuit_breaker_cooldown_seconds = old_cooldown
