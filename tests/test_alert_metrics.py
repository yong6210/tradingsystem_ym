from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.core.config import get_settings
from app.db.models import AlertRetryTask, AlertSubscription
from app.db.session import SessionLocal, init_db
from app.db.repositories import AlertRepository, AlertRetryQueueRepository
from app.services.alert_metrics import AlertMetricsService
from app.services.notification_dispatcher import NotificationDispatcher


def test_alert_metrics_report_aggregates_leaf_channels_and_system_fanout() -> None:
    init_db()
    NotificationDispatcher.reset_circuit_state()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    settings = get_settings()
    old_min_attempts = settings.alert_slo_min_attempts
    settings.alert_slo_min_attempts = 1

    try:
        with SessionLocal() as db:
            db.execute(delete(AlertSubscription))
            db.execute(delete(AlertRetryTask))
            db.commit()
            db.add_all(
                [
                AlertSubscription(
                    alert_id="alert_discord_ok",
                    plan_id=None,
                    symbol="BTCUSDC",
                    channel="discord",
                    type="validation_warn",
                    payload={
                        "delivery": {
                            "channel": "discord",
                            "delivered": True,
                            "skipped": False,
                            "reason": "delivered",
                            "status_code": 204,
                            "target": "discord:webhook",
                            "latency_ms": 120.0,
                            "attempts": 1,
                            "ts": now.isoformat(),
                        }
                    },
                    triggered_ts=now - timedelta(minutes=30),
                ),
                AlertSubscription(
                    alert_id="alert_discord_fail",
                    plan_id=None,
                    symbol="BTCUSDC",
                    channel="discord",
                    type="validation_warn",
                    payload={
                        "delivery": {
                            "channel": "discord",
                            "delivered": False,
                            "skipped": False,
                            "reason": "http_503",
                            "status_code": 503,
                            "target": "discord:webhook",
                            "latency_ms": 2200.0,
                            "attempts": 3,
                            "ts": now.isoformat(),
                        }
                    },
                    triggered_ts=now - timedelta(minutes=20),
                ),
                AlertSubscription(
                    alert_id="alert_system_partial",
                    plan_id=None,
                    symbol="BTCUSDC",
                    channel="system",
                    type="validation_warn",
                    payload={
                        "status": "WARN",
                        "deployment_go_no_go": "NO_GO",
                        "deployment_code": "no_go_proxy_selected_trial_against_replay_backed_worst_scenario",
                        "deployment_message": "NO-GO: runtime proxy selected-trial is still active while replay-backed downside is worse.",
                        "approval_playbook_go_no_go": "NO_GO",
                        "approval_playbook_code": "no_go_proxy_selected_trial_against_replay_backed_worst_scenario",
                        "approval_playbook_action": "hold_live_rollout_and_keep_prototype_path",
                        "approval_playbook_message": (
                            "NO-GO: runtime proxy selected-trial is still active while replay-backed downside is worse. "
                            "Keep rollout blocked and do not treat this setup as threshold-lineage confirmed."
                        ),
                        "approval_topline_summary_line": "winner=runtime_proxy/runtime_validation_proxy_v1; worst=shock_concentration/FAIL/replay_output; promotion=stay_on_prototype",
                        "delivery": {
                            "channel": "system",
                            "delivered": True,
                            "skipped": False,
                            "reason": "system_partial_delivery",
                            "target": None,
                            "latency_ms": 3600.0,
                            "attempts": 1,
                            "routes": ["telegram", "discord", "push"],
                            "results": [
                                {
                                    "channel": "telegram",
                                    "delivered": True,
                                    "skipped": False,
                                    "reason": "delivered",
                                    "status_code": 200,
                                    "target": "telegram:chat_1",
                                    "latency_ms": 80.0,
                                    "attempts": 1,
                                    "ts": now.isoformat(),
                                },
                                {
                                    "channel": "discord",
                                    "delivered": False,
                                    "skipped": False,
                                    "reason": "http_503",
                                    "status_code": 503,
                                    "target": "discord:webhook",
                                    "latency_ms": 4100.0,
                                    "attempts": 2,
                                    "ts": now.isoformat(),
                                },
                                {
                                    "channel": "push",
                                    "delivered": False,
                                    "skipped": True,
                                    "reason": "circuit_open",
                                    "target": "push:webhook",
                                    "latency_ms": 0.0,
                                    "attempts": 0,
                                    "ts": now.isoformat(),
                                },
                            ],
                            "ts": now.isoformat(),
                        }
                    },
                    triggered_ts=now - timedelta(minutes=10),
                ),
                ]
            )
            db.add_all(
                [
                    AlertRetryTask(
                        task_id="alert_retry_queued",
                        source_alert_id="alert_discord_fail",
                        dedupe_key="alert_discord_fail:discord:discord:webhook",
                        channel="discord",
                        symbol="BTCUSDC",
                        type="validation_warn",
                        target="discord:webhook",
                        payload={"status": "WARN"},
                        status="queued",
                        attempts=1,
                        max_attempts=4,
                        next_retry_ts=now + timedelta(seconds=30),
                        last_reason="http_503",
                        last_status_code=503,
                        created_ts=now - timedelta(minutes=5),
                    ),
                    AlertRetryTask(
                        task_id="alert_retry_dead",
                        source_alert_id="alert_system_partial",
                        dedupe_key="alert_system_partial:push:push:webhook",
                        channel="push",
                        symbol="BTCUSDC",
                        type="validation_warn",
                        target="push:webhook",
                        payload={"status": "WARN"},
                        status="dead_letter",
                        attempts=4,
                        max_attempts=4,
                        next_retry_ts=now - timedelta(minutes=1),
                        last_reason="circuit_open",
                        last_status_code=None,
                        created_ts=now - timedelta(hours=1),
                        dead_letter_ts=now - timedelta(minutes=15),
                    ),
                ]
            )
            db.commit()

            service = AlertMetricsService(
                alert_repo=AlertRepository(db),
                retry_repo=AlertRetryQueueRepository(db),
                settings=settings,
            )
            payload = service.generate(days=10, write_report=False)

            assert payload["alerts_total"] == 3
            assert payload["alerts_with_delivery"] == 3
            assert payload["overall"]["scope"] == "leaf_channels"
            assert payload["overall"]["attempted"] == 4
            assert payload["overall"]["delivered"] == 2
            assert payload["overall"]["failed"] == 2
            assert payload["overall"]["skipped"] == 1
            assert payload["overall"]["success_rate"] == 0.5
            assert payload["channel_metrics"]["discord"]["attempted"] == 3
            assert payload["channel_metrics"]["discord"]["failed"] == 2
            assert payload["channel_metrics"]["discord"]["slo"]["status"] == "FAIL"
            assert payload["channel_metrics"]["discord"]["error_budget"]["status"] == "EXHAUSTED"
            assert payload["channel_metrics"]["telegram"]["delivered"] == 1
            assert payload["channel_metrics"]["push"]["circuit_open_count"] == 1
            assert payload["channel_metrics"]["system"]["slo"]["status"] == "WARN"
            assert payload["overall"]["error_budget"]["status"] == "EXHAUSTED"
            assert payload["latest_validation_alert"]["available"] is True
            assert payload["latest_validation_alert"]["deployment_go_no_go"] == "NO_GO"
            assert (
                payload["latest_validation_alert"]["deployment_code"]
                == "no_go_proxy_selected_trial_against_replay_backed_worst_scenario"
            )
            assert payload["latest_validation_alert"]["approval_playbook_go_no_go"] == "NO_GO"
            assert (
                payload["latest_validation_alert"]["approval_playbook_code"]
                == "no_go_proxy_selected_trial_against_replay_backed_worst_scenario"
            )
            assert (
                payload["latest_validation_alert"]["approval_playbook_action"]
                == "hold_live_rollout_and_keep_prototype_path"
            )
            assert payload["latest_validation_alert"]["approval_strip_summary"]["approve_value"] == "validation no_go"
            assert payload["latest_validation_alert"]["approval_strip_summary"]["act_value"] == (
                "hold_live_rollout_and_keep_prototype_path"
            )
            assert payload["latest_validation_alert"]["approval_topline_summary_line"].startswith(
                "winner=runtime_proxy/"
            )
            assert payload["retry_queue"]["counts"]["queued"] == 1
            assert payload["retry_queue"]["counts"]["dead_letter"] == 1
    finally:
        settings.alert_slo_min_attempts = old_min_attempts


def test_alert_metrics_tolerates_malformed_slo_settings() -> None:
    settings = get_settings().model_copy(deep=True)
    settings.alert_slo_min_attempts = "inf"
    settings.alert_slo_target_success_rate = "bad-target"
    settings.alert_slo_warn_success_rate = "nan"
    settings.alert_slo_max_p95_latency_ms = "bad-latency"
    settings.alert_slo_warn_p95_latency_ms = "inf"
    service = AlertMetricsService(alert_repo=None, settings=settings)

    slo = service._evaluate_slo(success_rate=1.0, p95_latency_ms=100.0, attempted=5)
    budget = service._error_budget(failed=0, attempted=5)

    assert slo["status"] == "PASS"
    assert slo["target_success_rate"] == 0.995
    assert slo["warn_p95_latency_ms"] == 5000.0
    assert budget["status"] == "PASS"


def test_latest_validation_alert_summary_tolerates_malformed_payloads() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    payload = AlertMetricsService._latest_validation_alert_summary(
        [
            AlertSubscription(
                alert_id="val_warn_malformed",
                plan_id=None,
                symbol="BTCUSDC",
                channel="discord",
                type="validation_warn",
                payload=["broken"],
                triggered_ts=now,
            )
        ]
    )

    assert payload["available"] is True
    assert payload["alert_id"] == "val_warn_malformed"
    assert payload["approval_strip_summary"]["approve_value"] == "n/a"
    assert payload["delivery_channel"] == "discord"
    assert payload["failed"] is True


def test_alert_metrics_generate_tolerates_malformed_subscription_payloads() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)

    class _Repo:
        def list_recent(self, *, days: int = 30, limit: int = 5000):  # noqa: ARG002
            return [
                AlertSubscription(
                    alert_id="alert_malformed_payload",
                    plan_id=None,
                    symbol="BTCUSDC",
                    channel="discord",
                    type="validation_warn",
                    payload=["broken"],
                    triggered_ts=now,
                ),
                AlertSubscription(
                    alert_id="alert_delivery_ok",
                    plan_id=None,
                    symbol="BTCUSDC",
                    channel="discord",
                    type="validation_warn",
                    payload={
                        "delivery": {
                            "channel": "discord",
                            "delivered": True,
                            "skipped": False,
                            "reason": "delivered",
                            "attempts": 1,
                        }
                    },
                    triggered_ts=now,
                ),
            ][:limit]

    payload = AlertMetricsService(alert_repo=_Repo(), retry_repo=None).generate(days=1, write_report=False)

    assert payload["alerts_total"] == 2
    assert payload["alerts_with_delivery"] == 1
    assert payload["overall"]["delivered"] == 1
    assert payload["latest_validation_alert"]["available"] is True
