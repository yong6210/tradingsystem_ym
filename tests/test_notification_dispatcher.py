from __future__ import annotations

from app.core.config import get_settings
from app.services.notification_dispatcher import NotificationDispatcher


def test_dispatcher_safe_bool_treats_string_nullish_values_as_false() -> None:
    assert NotificationDispatcher._safe_bool("none", default=True) is False
    assert NotificationDispatcher._safe_bool("null", default=True) is False


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

    assert "approval_strip: approve=validation no_go | align=aligned | act=hold_live_rollout_and_keep_prototype_path | priority=urgent" in message
    assert "approval=winner=runtime_proxy/runtime_validation_proxy_v1;" in message
    assert "contract_trace: deployment=NO_GO/no_go_proxy_selected_trial_against_replay_backed_worst_scenario" in message
    assert "playbook_action=hold_live_rollout_and_keep_prototype_path" in message
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


def test_dispatcher_discord_safe_message_truncates_long_message() -> None:
    message = NotificationDispatcher._discord_safe_message("x" * 2500)

    assert len(message) <= NotificationDispatcher._DISCORD_MAX_MESSAGE_CHARS
    assert message.endswith("...[truncated]")


def test_dispatcher_discord_uses_short_korean_validation_message(monkeypatch) -> None:
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
            payload={
                "status": "WARN",
                "deployment_code": "manual_review_required",
                "approval_playbook_action": "review_before_live_rollout",
                "report_path": "reports/validation/BTCUSDC.json",
            },
        )

        content = calls[0]["json"]["content"]
        assert result["delivered"] is True
        assert content.startswith("[주의] BTCUSDC 검증 주의")
        assert "해야 할 일: review before live rollout" in content
        assert "이유: manual review required" in content
        assert "리포트: reports/validation/BTCUSDC.json" in content
        assert "contract_trace" not in content
    finally:
        settings.alert_discord_webhook_url = old_url


def test_dispatcher_discord_suppresses_low_importance_signal(monkeypatch) -> None:
    NotificationDispatcher.reset_circuit_state()
    settings = get_settings()
    old_url = settings.alert_discord_webhook_url

    try:
        settings.alert_discord_webhook_url = "https://discord.example/webhook"
        dispatcher = NotificationDispatcher(settings)
        result = dispatcher.dispatch(
            channel="discord",
            alert_type="near",
            symbol="BTCUSDC",
            payload={"status": "INFO"},
        )

        assert result["delivered"] is False
        assert result["skipped"] is True
        assert result["reason"] == "discord_low_importance_signal_suppressed"
    finally:
        settings.alert_discord_webhook_url = old_url


def test_dispatcher_entry_surface_context_only_title_is_monitoring() -> None:
    message = NotificationDispatcher._format_discord_message(
        alert_type="entry_surface_alert",
        symbol="USDC_PERP_TOP30",
        payload={
            "message": (
                "Trading entry surface alert: live_order_candidates=0, review_candidates=2\n"
                "scope: USDC_PERP_TOP30 | order_truth=live_candidate_promotion_readiness\n"
                "counts: LIVE_ORDER_CANDIDATE=0, CONTEXT_REVIEW_SETUP=2"
            )
        },
    )

    assert message.startswith("[모니터링] USDC_PERP_TOP30 주문 후보 없음")
    assert "확인 필요" not in message


def test_dispatcher_entry_surface_live_candidate_title_requires_attention() -> None:
    message = NotificationDispatcher._format_discord_message(
        alert_type="entry_surface_alert",
        symbol="USDC_PERP_TOP30",
        payload={
            "message": (
                "Trading entry surface alert: live_order_candidates=1, review_candidates=0\n"
                "scope: USDC_PERP_TOP30 | order_truth=live_candidate_promotion_readiness\n"
                "counts: LIVE_ORDER_CANDIDATE=1, CONTEXT_REVIEW_SETUP=0"
            )
        },
    )

    assert message.startswith("[중요] USDC_PERP_TOP30 라이브 주문 후보 확인")


def test_dispatcher_entry_surface_blocked_live_candidate_title_requires_review() -> None:
    message = NotificationDispatcher._format_discord_message(
        alert_type="entry_surface_alert",
        symbol="USDC_PERP_TOP30",
        payload={
            "message": (
                "Trading entry surface alert: live_order_candidates=0, "
                "review_candidates=0, blocked_live_candidates=1\n"
                "scope: USDC_PERP_TOP30 | order_truth=live_candidate_promotion_readiness\n"
                "counts: LIVE_ORDER_CANDIDATE=0, CONTEXT_REVIEW_SETUP=0, BLOCKED_SETUP=1"
            )
        },
    )

    assert message.startswith("[주의] USDC_PERP_TOP30 라이브 주문 후보 차단")
    assert "주문 후보 없음" not in message


def test_dispatcher_entry_surface_context_only_blocked_title_stays_monitoring() -> None:
    message = NotificationDispatcher._format_discord_message(
        alert_type="entry_surface_alert",
        symbol="USDC_PERP_TOP30",
        payload={
            "message": (
                "Trading entry surface alert: live_order_candidates=0, review_candidates=2, "
                "blocked_live_candidates=0, blocked_context_only=3\n"
                "scope: USDC_PERP_TOP30 | order_truth=live_candidate_promotion_readiness\n"
                "counts: LIVE_ORDER_CANDIDATE=0, CONTEXT_REVIEW_SETUP=2, BLOCKED_SETUP=3 "
                "| blocked_breakdown=live:0,context_only:3"
            )
        },
    )

    assert message.startswith("[모니터링] USDC_PERP_TOP30 주문 후보 없음")
    assert "라이브 주문 후보 차단" not in message


def test_dispatcher_entry_surface_alert_without_entry_counts_uses_operational_title() -> None:
    message = NotificationDispatcher._format_discord_message(
        alert_type="entry_surface_alert",
        symbol="MICRO_LIVE",
        payload={
            "message": (
                "micro live no-order watchdog\n"
                "최근 live intent 0건, live 주문 제출 0건. submit_ready=0"
            )
        },
    )

    assert message.startswith("[운영] MICRO_LIVE 확인 필요")
    assert "주문 후보 없음" not in message


def test_dispatcher_micro_live_no_order_watchdog_uses_operational_title() -> None:
    message = NotificationDispatcher._format_discord_message(
        alert_type="micro_live_no_order_watchdog",
        symbol="MICRO_LIVE",
        payload={
            "message": (
                "MICRO_LIVE 주문 없음\n"
                "런타임 재시작 이후: intent 3건 / 제출 0건\n"
                "원인: validation_do_not_deploy=3"
            )
        },
    )

    assert message.startswith("[운영] MICRO_LIVE 확인 필요")
    assert "주문 후보 없음" not in message


def test_dispatcher_operational_watchdog_types_are_not_low_importance_suppressed() -> None:
    for alert_type in (
        "micro_live_no_order_watchdog",
        "live_reconciliation_watchdog",
        "micro_live_ops_heartbeat",
    ):
        assert NotificationDispatcher._discord_skip_reason(alert_type=alert_type, payload={"message": "watch"}) == ""


def test_dispatcher_operational_heartbeat_includes_watch_detail() -> None:
    message = NotificationDispatcher._format_discord_message(
        alert_type="micro_live_ops_heartbeat",
        symbol="MICRO_LIVE",
        payload={
            "message": (
                "MICRO_LIVE 운영 점검\n"
                "상태: WATCH / fail=0 watch=1\n"
                "긴급: 없음\n"
                "주의: live_replay_parity=WATCH/WATCH content_status_watch "
                "portfolio_symbol_live_flow_and_order_gate_watch\n"
                "다음: WATCH는 자동 관찰; 반복/악화 시 해당 리포트 확인"
            )
        },
    )

    assert message.startswith("[모니터링] MICRO_LIVE 운영 관찰")
    assert "상세: 주의: live_replay_parity=WATCH/WATCH" in message
    assert "portfolio_symbol_live_flow_and_order_gate_watch" in message
    assert "조치: 다음: WATCH는 자동 관찰" in message
    assert "긴급: 없음" not in message


def test_dispatcher_confirm_signal_is_labeled_as_non_order_signal() -> None:
    message = NotificationDispatcher._format_discord_message(
        alert_type="confirm",
        symbol="BTCUSDC",
        payload={
            "direction": "long",
            "plan_id": "plan_confirm",
            "event_price": 100.0,
            "entry_price": 100.1,
        },
    )

    assert message.startswith("[중요] BTCUSDC 조건 확인 신호(주문 아님)")
    assert "주문: 제출 아님" in message
    assert "진입 확인 신호" not in message


def test_dispatcher_partial_exit_and_sl_are_trade_alerts_not_suppressed() -> None:
    for alert_type, title in (
        ("partial_exit", "부분 청산 발생"),
        ("sl", "손절 발생"),
    ):
        assert NotificationDispatcher._discord_skip_reason(alert_type=alert_type, payload={}) == ""
        message = NotificationDispatcher._format_discord_message(
            alert_type=alert_type,
            symbol="BTCUSDC",
            payload={
                "direction": "long",
                "plan_id": "plan_exit",
                "fill_price": 99.5,
                "realized_r": -1.0,
            },
        )
        assert message.startswith(f"[중요] BTCUSDC {title}")
        assert "가격: 99.5" in message
        assert "플랜: plan_exit" in message


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


def test_dispatcher_tolerates_malformed_retry_and_circuit_settings(monkeypatch) -> None:
    NotificationDispatcher.reset_circuit_state()
    settings = get_settings().model_copy(deep=True)
    settings.alert_discord_webhook_url = "https://discord.example/malformed-settings"
    settings.alert_retry_attempts = "bad-attempts"
    settings.alert_retry_backoff_seconds = "nan"
    settings.alert_http_timeout_seconds = "bad-timeout"
    settings.alert_circuit_breaker_failures = "inf"
    settings.alert_circuit_breaker_cooldown_seconds = "bad-cooldown"
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

    monkeypatch.setattr("app.services.notification_dispatcher.httpx.Client", _Client)
    monkeypatch.setattr("app.services.notification_dispatcher.time.sleep", lambda seconds: None)

    result = NotificationDispatcher(settings).dispatch(
        channel="discord",
        alert_type="validation_warn",
        symbol="BTCUSDC",
        payload={"status": "WARN"},
    )

    assert result["attempts"] == 3
    assert result["reason"] == "http_503"
    assert len(calls) == 3
