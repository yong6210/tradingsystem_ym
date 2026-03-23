from __future__ import annotations

from app.core.config import get_settings
from app.services.notification_dispatcher import NotificationDispatcher
from scripts.check_operator_session_brief_delivery_preflight import evaluate_delivery_preflight


def test_delivery_preflight_marks_system_unhealthy_without_routes(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "alert_telegram_bot_token", "")
    monkeypatch.setattr(settings, "alert_telegram_chat_id", "")
    monkeypatch.setattr(settings, "alert_discord_webhook_url", "")
    monkeypatch.setattr(settings, "alert_push_webhook_url", "")
    monkeypatch.setattr(
        "scripts.check_operator_session_brief_delivery_preflight.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "scripts.check_operator_session_brief_delivery_preflight._launchctl_getenv",
        lambda name: "system" if name == "OPERATOR_BRIEF_CHANNEL" else "",
    )
    NotificationDispatcher.reset_circuit_state()

    payload = evaluate_delivery_preflight(["system", "discord"])

    assert payload["healthy"] is False
    assert "system: system_no_routes_configured" in payload["issues"]
    assert "launchd_channel_not_ready:system" in payload["issues"]
    assert payload["channels"]["system"]["healthy"] is False
    assert payload["channels"]["system"]["routes"] == []
    assert payload["channels"]["discord"]["healthy"] is False


def test_delivery_preflight_marks_system_healthy_with_discord_route(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "alert_telegram_bot_token", "")
    monkeypatch.setattr(settings, "alert_telegram_chat_id", "")
    monkeypatch.setattr(settings, "alert_discord_webhook_url", "https://discord.example/webhook")
    monkeypatch.setattr(settings, "alert_push_webhook_url", "")
    monkeypatch.setattr(
        "scripts.check_operator_session_brief_delivery_preflight.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "scripts.check_operator_session_brief_delivery_preflight._launchctl_getenv",
        lambda name: {
            "OPERATOR_BRIEF_CHANNEL": "system",
            "OPERATOR_BRIEF_DRY_RUN": "1",
            "OPERATOR_BRIEF_ALLOW_LIVE_SEND": "",
            "OPERATOR_BRIEF_DISCORD_WEBHOOK_URL": "1",
        }.get(name, ""),
    )
    NotificationDispatcher.reset_circuit_state()

    payload = evaluate_delivery_preflight(["system", "discord"])

    assert payload["healthy"] is True
    assert payload["issues"] == []
    assert payload["channels"]["system"]["healthy"] is True
    assert payload["channels"]["system"]["routes"] == ["discord"]
    assert payload["channels"]["discord"]["healthy"] is True
    assert payload["launchd_env"]["OPERATOR_BRIEF_CHANNEL"] == "system"
    assert payload["launchd_env"]["OPERATOR_BRIEF_ALLOW_LIVE_SEND"] == ""
