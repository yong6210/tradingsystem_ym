from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.db.models import AlertSubscription, EventOutbox
from app.db.session import SessionLocal, init_db
from app.services.notification_dispatcher import NotificationDispatcher
from app.services.strategy_engine import StrategyEngine


def test_recompute_learning_emits_validation_warn_alert(monkeypatch) -> None:
    init_db()
    settings = get_settings()
    monkeypatch.setattr(settings, "alert_telegram_bot_token", "")
    monkeypatch.setattr(settings, "alert_telegram_chat_id", "")
    monkeypatch.setattr(settings, "alert_discord_webhook_url", "")
    monkeypatch.setattr(settings, "alert_push_webhook_url", "")
    monkeypatch.setattr(settings, "validation_alert_channel", "system")
    NotificationDispatcher.reset_circuit_state()
    symbol = f"VALA{int(datetime.now(timezone.utc).timestamp())}USDC"

    with SessionLocal() as db:
        db.execute(delete(AlertSubscription).where(AlertSubscription.symbol == symbol))
        db.execute(delete(EventOutbox).where(EventOutbox.event_type == "validation.warn"))
        db.commit()

        engine = StrategyEngine(db)
        payload = engine.recompute_learning(symbol=symbol)

        assert payload["validation_report"]["status"] == "WARN"
        assert payload["validation_alert"] is not None
        assert payload["validation_alert"]["emitted"] is True
        assert payload["validation_alert"]["delivery"]["reason"] == "system_no_routes_configured"
        assert payload["validation_alert"]["deployment_go_no_go"] == payload["validation_report"][
            "deployment_approval_summary"
        ]["playbook_go_no_go"]
        assert payload["validation_alert"]["deployment_code"] == payload["validation_report"][
            "deployment_approval_summary"
        ]["playbook_code"]
        assert payload["validation_alert"]["deployment_message"] == payload["validation_report"][
            "deployment_approval_summary"
        ]["playbook_message"]
        assert payload["validation_alert"]["approval_topline_summary_line"] == payload["validation_report"][
            "deployment_approval_summary"
        ]["topline_summary_line"]
        assert payload["validation_alert"]["approval_playbook_go_no_go"] == payload["validation_report"][
            "deployment_approval_summary"
        ]["playbook_go_no_go"]
        assert payload["validation_alert"]["approval_playbook_code"] == payload["validation_report"][
            "deployment_approval_summary"
        ]["playbook_code"]
        assert payload["validation_alert"]["approval_playbook_action"] == payload["validation_report"][
            "deployment_approval_summary"
        ]["playbook_action"]
        assert payload["validation_alert"]["approval_playbook_message"] == payload["validation_report"][
            "deployment_approval_summary"
        ]["playbook_message"]
        assert payload["validation_alert"]["approval_strip_summary"]["act_value"] == payload["validation_report"][
            "deployment_approval_summary"
        ]["playbook_action"]
        assert payload["parameter_changelog"]["reason"] in {"initialized", "changes_detected", "no_changes"}
        assert payload["parameter_changelog"]["path"]

        alerts = list(
            db.scalars(
                select(AlertSubscription).where(
                    AlertSubscription.symbol == symbol,
                    AlertSubscription.channel == settings.validation_alert_channel,
                    AlertSubscription.type == "validation_warn",
                )
            )
        )
        assert len(alerts) == 1
        assert (alerts[0].payload or {}).get("approval_topline_summary_line") == payload["validation_report"][
            "deployment_approval_summary"
        ]["topline_summary_line"]
        assert (alerts[0].payload or {}).get("approval_playbook_go_no_go") == payload["validation_report"][
            "deployment_approval_summary"
        ]["playbook_go_no_go"]
        assert (alerts[0].payload or {}).get("approval_playbook_code") == payload["validation_report"][
            "deployment_approval_summary"
        ]["playbook_code"]
        assert (alerts[0].payload or {}).get("approval_playbook_action") == payload["validation_report"][
            "deployment_approval_summary"
        ]["playbook_action"]
        assert (alerts[0].payload or {}).get("approval_playbook_message") == payload["validation_report"][
            "deployment_approval_summary"
        ]["playbook_message"]
        assert ((alerts[0].payload or {}).get("approval_strip_summary") or {}).get("act_value") == payload[
            "validation_report"
        ]["deployment_approval_summary"]["playbook_action"]

        outbox = list(db.scalars(select(EventOutbox).where(EventOutbox.event_type == "validation.warn")))
        assert any((row.payload or {}).get("symbol") == symbol for row in outbox)
        assert any(
            (row.payload or {}).get("approval_topline_summary_line")
            == payload["validation_report"]["deployment_approval_summary"]["topline_summary_line"]
            for row in outbox
        )
        assert any(
            (row.payload or {}).get("approval_playbook_go_no_go")
            == payload["validation_report"]["deployment_approval_summary"]["playbook_go_no_go"]
            for row in outbox
        )
        assert any(
            (row.payload or {}).get("approval_playbook_code")
            == payload["validation_report"]["deployment_approval_summary"]["playbook_code"]
            for row in outbox
        )
        assert any(
            (row.payload or {}).get("approval_playbook_action")
            == payload["validation_report"]["deployment_approval_summary"]["playbook_action"]
            for row in outbox
        )
        assert any(
            (row.payload or {}).get("approval_playbook_message")
            == payload["validation_report"]["deployment_approval_summary"]["playbook_message"]
            for row in outbox
        )
        assert any(
            ((row.payload or {}).get("approval_strip_summary") or {}).get("act_value")
            == payload["validation_report"]["deployment_approval_summary"]["playbook_action"]
            for row in outbox
        )


def test_recompute_learning_skips_outcome_updated_event_when_no_zone_updates(monkeypatch) -> None:
    init_db()
    settings = get_settings()
    monkeypatch.setattr(settings, "alert_telegram_bot_token", "")
    monkeypatch.setattr(settings, "alert_telegram_chat_id", "")
    monkeypatch.setattr(settings, "alert_discord_webhook_url", "")
    monkeypatch.setattr(settings, "alert_push_webhook_url", "")
    symbol = f"VALN{int(datetime.now(timezone.utc).timestamp())}USDC"

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        published: list[tuple[str, dict]] = []

        def _publish(event_type: str, payload: dict) -> None:
            published.append((event_type, payload))

        monkeypatch.setattr(engine.events, "publish", _publish)

        payload = engine.recompute_learning(symbol=symbol)

        assert payload["updated_zones"] == 0
        assert all(event_type != "outcome.updated" for event_type, _ in published)


def test_recompute_learning_validation_alert_respects_cooldown() -> None:
    init_db()
    settings = get_settings()
    symbol = f"VALC{int(datetime.now(timezone.utc).timestamp())}USDC"
    old_cooldown = settings.validation_alert_cooldown_seconds
    settings.validation_alert_cooldown_seconds = 3600

    try:
        with SessionLocal() as db:
            db.execute(delete(AlertSubscription).where(AlertSubscription.symbol == symbol))
            db.commit()

            engine = StrategyEngine(db)
            first = engine.recompute_learning(symbol=symbol)
            second = engine.recompute_learning(symbol=symbol)

            assert first["validation_alert"] is not None
            assert first["validation_alert"]["emitted"] is True
            assert second["validation_alert"] is not None
            assert second["validation_alert"]["emitted"] is False
            assert second["validation_alert"]["reason"] == "cooldown_active"
            assert second["validation_alert"]["deployment_go_no_go"] == second["validation_report"][
                "deployment_approval_summary"
            ]["playbook_go_no_go"]
            assert second["validation_alert"]["deployment_code"] == second["validation_report"][
                "deployment_approval_summary"
            ]["playbook_code"]
            assert second["validation_alert"]["approval_topline_summary_line"] == second["validation_report"][
                "deployment_approval_summary"
            ]["topline_summary_line"]
            assert second["validation_alert"]["approval_playbook_go_no_go"] == second["validation_report"][
                "deployment_approval_summary"
            ]["playbook_go_no_go"]
            assert second["validation_alert"]["approval_playbook_code"] == second["validation_report"][
                "deployment_approval_summary"
            ]["playbook_code"]
            assert second["validation_alert"]["approval_playbook_action"] == second["validation_report"][
                "deployment_approval_summary"
            ]["playbook_action"]
            assert second["validation_alert"]["approval_playbook_message"] == second["validation_report"][
                "deployment_approval_summary"
            ]["playbook_message"]
            assert second["validation_alert"]["approval_strip_summary"]["act_value"] == second["validation_report"][
                "deployment_approval_summary"
            ]["playbook_action"]
            assert second["parameter_changelog"]["reason"] in {"changes_detected", "no_changes"}

            alerts = list(
                db.scalars(
                    select(AlertSubscription).where(
                        AlertSubscription.symbol == symbol,
                        AlertSubscription.type == "validation_warn",
                    )
                )
            )
            assert len(alerts) == 1
    finally:
        settings.validation_alert_cooldown_seconds = old_cooldown


def test_recompute_learning_validation_alert_dispatches_external_channel(monkeypatch) -> None:
    init_db()
    settings = get_settings()
    symbol = f"VALD{int(datetime.now(timezone.utc).timestamp())}USDC"
    old_channel = settings.validation_alert_channel
    old_webhook = settings.alert_discord_webhook_url

    calls: list[dict] = []

    def _fake_post_json(self, **kwargs):  # noqa: ANN001
        calls.append(kwargs)
        return {
            "channel": "discord",
            "delivered": True,
            "skipped": False,
            "reason": "delivered",
            "status_code": 204,
            "target": "discord:webhook",
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    monkeypatch.setattr("app.services.notification_dispatcher.NotificationDispatcher._post_json", _fake_post_json)

    try:
        settings.validation_alert_channel = "discord"
        settings.alert_discord_webhook_url = "https://discord.example/webhook"
        with SessionLocal() as db:
            db.execute(delete(AlertSubscription).where(AlertSubscription.symbol == symbol))
            db.execute(delete(EventOutbox).where(EventOutbox.event_type == "validation.warn"))
            db.commit()

            engine = StrategyEngine(db)
            payload = engine.recompute_learning(symbol=symbol)
            assert payload["validation_alert"] is not None
            delivery = payload["validation_alert"]["delivery"]
            assert delivery["channel"] == "discord"
            assert delivery["delivered"] is True
            assert delivery["reason"] == "delivered"
            assert payload["validation_alert"]["deployment_go_no_go"] == payload["validation_report"][
                "deployment_approval_summary"
            ]["playbook_go_no_go"]
            assert payload["validation_alert"]["deployment_code"] == payload["validation_report"][
                "deployment_approval_summary"
            ]["playbook_code"]
            assert payload["validation_alert"]["approval_topline_summary_line"] == payload["validation_report"][
                "deployment_approval_summary"
            ]["topline_summary_line"]
            assert payload["validation_alert"]["approval_playbook_go_no_go"] == payload["validation_report"][
                "deployment_approval_summary"
            ]["playbook_go_no_go"]
            assert payload["validation_alert"]["approval_playbook_code"] == payload["validation_report"][
                "deployment_approval_summary"
            ]["playbook_code"]
            assert payload["validation_alert"]["approval_playbook_action"] == payload["validation_report"][
                "deployment_approval_summary"
            ]["playbook_action"]
            assert payload["validation_alert"]["approval_playbook_message"] == payload["validation_report"][
                "deployment_approval_summary"
            ]["playbook_message"]
            assert calls
            content = calls[0]["json_payload"]["content"]
            assert content.startswith(f"[주의] {symbol} 검증 주의")
            assert "해야 할 일:" in content
            assert "이유:" in content
            assert "리포트:" in content
            assert "contract_trace" not in content
            assert "approval=" not in content

            alerts = list(
                db.scalars(
                    select(AlertSubscription).where(
                        AlertSubscription.symbol == symbol,
                        AlertSubscription.type == "validation_warn",
                    )
                )
            )
            assert len(alerts) == 1
            saved_delivery = (alerts[0].payload or {}).get("delivery", {})
            assert saved_delivery.get("delivered") is True
            assert (alerts[0].payload or {}).get("approval_topline_summary_line") == payload["validation_report"][
                "deployment_approval_summary"
            ]["topline_summary_line"]
            assert (alerts[0].payload or {}).get("approval_playbook_go_no_go") == payload["validation_report"][
                "deployment_approval_summary"
            ]["playbook_go_no_go"]
            assert (alerts[0].payload or {}).get("approval_playbook_code") == payload["validation_report"][
                "deployment_approval_summary"
            ]["playbook_code"]
            assert (alerts[0].payload or {}).get("approval_playbook_action") == payload["validation_report"][
                "deployment_approval_summary"
            ]["playbook_action"]
            assert (alerts[0].payload or {}).get("approval_playbook_message") == payload["validation_report"][
                "deployment_approval_summary"
            ]["playbook_message"]
            assert ((alerts[0].payload or {}).get("approval_strip_summary") or {}).get("act_value") == payload[
                "validation_report"
            ]["deployment_approval_summary"]["playbook_action"]
    finally:
        settings.validation_alert_channel = old_channel
        settings.alert_discord_webhook_url = old_webhook
