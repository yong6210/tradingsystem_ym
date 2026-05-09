from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from threading import Lock
import time
from typing import Any, ClassVar

import httpx

from app.core.config import Settings, get_settings
from app.services.deployment_contracts import validation_alert_contract, validation_alert_strip_summary


@dataclass(slots=True)
class DispatchResult:
    channel: str
    delivered: bool
    skipped: bool
    reason: str
    status_code: int | None = None
    target: str | None = None
    latency_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "delivered": self.delivered,
            "skipped": self.skipped,
            "reason": self.reason,
            "status_code": self.status_code,
            "target": self.target,
            "latency_ms": self.latency_ms,
            "ts": datetime.now(timezone.utc).isoformat(),
        }


@dataclass(slots=True)
class _CircuitState:
    failures: int = 0
    open_until: datetime | None = None


class NotificationDispatcher:
    """Dispatches operational alerts to external channels."""

    SUPPORTED_CHANNELS: ClassVar[set[str]] = {"telegram", "discord", "push", "system"}
    _DISCORD_MAX_MESSAGE_CHARS = 1800
    _circuit_states: ClassVar[dict[str, _CircuitState]] = {}
    _circuit_lock: ClassVar[Lock] = Lock()

    def __init__(self, settings: Settings | None = None):
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

    @classmethod
    def reset_circuit_state(cls) -> None:
        with cls._circuit_lock:
            cls._circuit_states.clear()

    @classmethod
    def circuit_snapshot(cls) -> dict[str, dict[str, Any]]:
        now = datetime.now(timezone.utc)
        grouped: dict[str, dict[str, Any]] = {}
        with cls._circuit_lock:
            for circuit_key, state in cls._circuit_states.items():
                channel, target = circuit_key.split(":", 1)
                entry = grouped.setdefault(
                    channel,
                    {
                        "tracked_targets": 0,
                        "open_targets": 0,
                        "max_failures": 0,
                        "targets": {},
                    },
                )
                is_open = bool(state.open_until and now < state.open_until)
                entry["tracked_targets"] = int(entry["tracked_targets"]) + 1
                if is_open:
                    entry["open_targets"] = int(entry["open_targets"]) + 1
                entry["max_failures"] = max(int(entry["max_failures"]), int(state.failures))
                entry["targets"][target] = {
                    "failures": int(state.failures),
                    "open": is_open,
                    "open_until": state.open_until.isoformat() if state.open_until else None,
                }
        return grouped

    def dispatch(self, *, channel: str, alert_type: str, symbol: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = channel.strip().lower()
        if normalized not in self.SUPPORTED_CHANNELS:
            return DispatchResult(
                channel=normalized or channel,
                delivered=False,
                skipped=True,
                reason="unsupported_channel",
                latency_ms=0.0,
            ).to_dict()

        if normalized == "system":
            return self._dispatch_system(alert_type=alert_type, symbol=symbol, payload=payload)

        if normalized == "discord":
            skip_reason = self._discord_skip_reason(alert_type=alert_type, payload=payload)
            if skip_reason:
                return DispatchResult(
                    channel="discord",
                    delivered=False,
                    skipped=True,
                    reason=skip_reason,
                    target="discord:webhook",
                    latency_ms=0.0,
                ).to_dict()
            message = self._format_discord_message(alert_type=alert_type, symbol=symbol, payload=payload)
            return self._send_discord(message=message)

        message = self._format_message(alert_type=alert_type, symbol=symbol, payload=payload)
        if normalized == "telegram":
            return self._send_telegram(message=message)
        return self._send_push(alert_type=alert_type, symbol=symbol, message=message, payload=payload)

    def _configured_system_routes(self) -> list[str]:
        routes: list[str] = []
        if self.settings.alert_telegram_bot_token.strip() and self.settings.alert_telegram_chat_id.strip():
            routes.append("telegram")
        if self.settings.alert_discord_webhook_url.strip():
            routes.append("discord")
        if self.settings.alert_push_webhook_url.strip():
            routes.append("push")
        return routes

    def _dispatch_system(self, *, alert_type: str, symbol: str, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        routes = self._configured_system_routes()
        if not routes:
            result = DispatchResult(
                channel="system",
                delivered=False,
                skipped=True,
                reason="system_no_routes_configured",
                latency_ms=0.0,
            ).to_dict()
            result["routes"] = []
            result["results"] = []
            return result

        results = [
            self.dispatch(
                channel=route,
                alert_type=alert_type,
                symbol=symbol,
                payload=payload,
            )
            for route in routes
        ]
        delivered_count = sum(1 for item in results if bool(item.get("delivered")))
        if delivered_count == len(results):
            reason = "system_delivered_all"
            skipped = False
            delivered = True
        elif delivered_count > 0:
            reason = "system_partial_delivery"
            skipped = False
            delivered = True
        else:
            skipped = all(bool(item.get("skipped")) for item in results)
            reason = "system_all_skipped" if skipped else "system_delivery_failed"
            delivered = False

        result = DispatchResult(
            channel="system",
            delivered=delivered,
            skipped=skipped,
            reason=reason,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
        ).to_dict()
        result["attempts"] = 1
        result["routes"] = routes
        result["results"] = results
        return result

    def _send_telegram(self, *, message: str) -> dict[str, Any]:
        token = self.settings.alert_telegram_bot_token.strip()
        chat_id = self.settings.alert_telegram_chat_id.strip()
        if not token or not chat_id:
            return DispatchResult(
                channel="telegram",
                delivered=False,
                skipped=True,
                reason="telegram_not_configured",
                latency_ms=0.0,
            ).to_dict()

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": True,
        }
        return self._post_json(
            channel="telegram",
            url=url,
            json_payload=payload,
            target=f"telegram:{chat_id}",
        )

    def _send_discord(self, *, message: str) -> dict[str, Any]:
        webhook_url = self.settings.alert_discord_webhook_url.strip()
        if not webhook_url:
            return DispatchResult(
                channel="discord",
                delivered=False,
                skipped=True,
                reason="discord_not_configured",
                latency_ms=0.0,
            ).to_dict()

        payload = {"content": self._discord_safe_message(message)}
        return self._post_json(
            channel="discord",
            url=webhook_url,
            json_payload=payload,
            target="discord:webhook",
        )

    @classmethod
    def _discord_safe_message(cls, message: str) -> str:
        content = str(message or "")
        if len(content) <= cls._DISCORD_MAX_MESSAGE_CHARS:
            return content
        suffix = "\n...[truncated]"
        budget = max(0, cls._DISCORD_MAX_MESSAGE_CHARS - len(suffix))
        return content[:budget].rstrip() + suffix

    def _send_push(self, *, alert_type: str, symbol: str, message: str, payload: dict[str, Any]) -> dict[str, Any]:
        webhook_url = self.settings.alert_push_webhook_url.strip()
        if not webhook_url:
            return DispatchResult(
                channel="push",
                delivered=False,
                skipped=True,
                reason="push_not_configured",
                latency_ms=0.0,
            ).to_dict()

        headers: dict[str, str] = {}
        token = self.settings.alert_push_bearer_token.strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        body = {
            "title": f"Trading Alert: {alert_type}",
            "message": message,
            "symbol": symbol,
            "type": alert_type,
            "payload": payload,
        }
        return self._post_json(
            channel="push",
            url=webhook_url,
            json_payload=body,
            headers=headers,
            target="push:webhook",
        )

    def _post_json(
        self,
        *,
        channel: str,
        url: str,
        json_payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        target: str,
    ) -> dict[str, Any]:
        circuit_key = self._circuit_key(channel=channel, target=target)
        if self._is_circuit_open(circuit_key):
            result = DispatchResult(
                channel=channel,
                delivered=False,
                skipped=True,
                reason="circuit_open",
                target=target,
                latency_ms=0.0,
            ).to_dict()
            result["attempts"] = 0
            return result

        attempts = max(1, self._safe_int(self.settings.alert_retry_attempts, default=3))
        base_backoff = max(0.0, self._safe_float(self.settings.alert_retry_backoff_seconds, default=0.4))
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                with httpx.Client(timeout=self._safe_float(self.settings.alert_http_timeout_seconds, default=5.0)) as client:
                    response = client.post(url, json=json_payload, headers=headers)
                elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)

                if 200 <= response.status_code < 300:
                    self._record_send_result(circuit_key, success=True)
                    result = DispatchResult(
                        channel=channel,
                        delivered=True,
                        skipped=False,
                        reason="delivered",
                        status_code=response.status_code,
                        target=target,
                        latency_ms=elapsed_ms,
                    ).to_dict()
                    result["attempts"] = attempt
                    return result

                retryable = self._is_retryable_status(response.status_code)
                if not retryable or attempt >= attempts:
                    self._record_send_result(circuit_key, success=False)
                    result = DispatchResult(
                        channel=channel,
                        delivered=False,
                        skipped=False,
                        reason=f"http_{response.status_code}",
                        status_code=response.status_code,
                        target=target,
                        latency_ms=elapsed_ms,
                    ).to_dict()
                    result["attempts"] = attempt
                    return result
            except Exception as exc:
                elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
                if attempt >= attempts:
                    self._record_send_result(circuit_key, success=False)
                    result = DispatchResult(
                        channel=channel,
                        delivered=False,
                        skipped=False,
                        reason=f"exception:{exc.__class__.__name__}",
                        target=target,
                        latency_ms=elapsed_ms,
                    ).to_dict()
                    result["attempts"] = attempt
                    return result

            if base_backoff > 0 and attempt < attempts:
                time.sleep(base_backoff * (2 ** (attempt - 1)))

        self._record_send_result(circuit_key, success=False)
        result = DispatchResult(
            channel=channel,
            delivered=False,
            skipped=False,
            reason="delivery_failed_unknown",
            target=target,
            latency_ms=0.0,
        ).to_dict()
        result["attempts"] = attempts
        return result

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return status_code == 429 or status_code >= 500

    @staticmethod
    def _circuit_key(*, channel: str, target: str) -> str:
        return f"{channel}:{target}"

    def _record_send_result(self, circuit_key: str, *, success: bool) -> None:
        threshold = max(1, self._safe_int(self.settings.alert_circuit_breaker_failures, default=3))
        cooldown_seconds = max(0, self._safe_int(self.settings.alert_circuit_breaker_cooldown_seconds, default=90))
        now = datetime.now(timezone.utc)
        with self._circuit_lock:
            state = self._circuit_states.setdefault(circuit_key, _CircuitState())
            if success:
                state.failures = 0
                state.open_until = None
                return

            state.failures += 1
            if state.failures >= threshold:
                state.open_until = now + timedelta(seconds=cooldown_seconds)

    def _is_circuit_open(self, circuit_key: str) -> bool:
        now = datetime.now(timezone.utc)
        with self._circuit_lock:
            state = self._circuit_states.get(circuit_key)
            if state is None:
                return False
            if state.open_until is None:
                return False
            if now >= state.open_until:
                state.failures = 0
                state.open_until = None
                return False
            return True

    @staticmethod
    def _format_message(*, alert_type: str, symbol: str, payload: dict[str, Any]) -> str:
        custom_message = str(payload.get("message") or "").strip()
        status = str(payload.get("status") or "").upper()
        version = str(payload.get("version") or "")
        generated_at = str(payload.get("generated_at") or "")
        report_path = str(payload.get("report_path") or "")
        contract = validation_alert_contract(payload)
        approval_strip = validation_alert_strip_summary(payload)
        deployment_go_no_go = contract["deployment_go_no_go"].strip()
        deployment_code = contract["deployment_code"].strip()
        approval_playbook_go_no_go = str(contract["approval_playbook_go_no_go"] or "").strip()
        approval_playbook_code = str(contract["approval_playbook_code"] or "").strip()
        approval_playbook_action = str(
            contract["approval_playbook_action"] or payload.get("playbook_action") or ""
        ).strip()
        approval_topline_summary_line = str(
            contract["approval_topline_summary_line"] or payload.get("topline_summary_line") or ""
        ).strip()
        has_approval_contract = any(
            (
                bool(payload.get("approval_strip_summary")),
                bool(deployment_go_no_go),
                bool(deployment_code),
                bool(approval_playbook_go_no_go),
                bool(approval_playbook_code),
                bool(approval_playbook_action),
                bool(approval_topline_summary_line),
            )
        )

        lines = [f"[{alert_type.upper()}] {symbol}"]
        if custom_message:
            lines.append(custom_message)
        if status:
            lines.append(f"status={status}")
        if has_approval_contract:
            lines.append(
                "approval_strip: "
                f"approve={approval_strip.get('approve_value', 'n/a')} | "
                f"align={approval_strip.get('align_value', 'n/a')} | "
                f"act={approval_strip.get('act_value', 'review_validation_alert_contract')} | "
                f"priority={approval_strip.get('act_priority_level', 'monitor')}"
            )
        if approval_topline_summary_line:
            lines.append(f"approval={approval_topline_summary_line}")
        trace_parts: list[str] = []
        if deployment_go_no_go and deployment_code:
            trace_parts.append(f"deployment={deployment_go_no_go}/{deployment_code}")
        elif deployment_go_no_go:
            trace_parts.append(f"deployment={deployment_go_no_go}")
        if approval_playbook_go_no_go and approval_playbook_code:
            trace_parts.append(f"playbook={approval_playbook_go_no_go}/{approval_playbook_code}")
        elif approval_playbook_go_no_go:
            trace_parts.append(f"playbook={approval_playbook_go_no_go}")
        if approval_playbook_action:
            trace_parts.append(f"playbook_action={approval_playbook_action}")
        if trace_parts:
            lines.append("contract_trace: " + " | ".join(trace_parts))
        if version:
            lines.append(f"version={version}")
        if generated_at:
            lines.append(f"generated_at={generated_at}")
        if report_path:
            lines.append(f"report={report_path}")

        use_multiline = (
            alert_type.startswith("validation_")
            or alert_type == "test"
            or has_approval_contract
        )
        return "\n".join(lines) if use_multiline else " | ".join(lines)

    @classmethod
    def _discord_skip_reason(cls, *, alert_type: str, payload: dict[str, Any]) -> str:
        normalized_type = str(alert_type or "").strip().lower()
        if bool(payload.get("force_send")) or bool(payload.get("force_alert")):
            return ""
        if normalized_type in {"test"}:
            return ""
        if normalized_type in {"near", "touch"}:
            return "discord_low_importance_signal_suppressed"

        status = str(payload.get("status") or "").strip().upper()
        if status in {"FAIL", "WARN", "MISS", "BLOCKED", "NO_GO", "ERROR"}:
            return ""

        important_types = {
            "validation_fail",
            "validation_warn",
            "session_impulse_retest_miss",
            "entry",
            "confirm",
            "tp",
            "closed",
            "stop",
            "exit",
            "fill",
            "entry_surface_alert",
            "stage_monitor_alert",
        }
        if normalized_type in important_types:
            return ""

        if normalized_type.startswith("operator_session_brief"):
            message = str(payload.get("message") or "").lower()
            urgent_terms = (
                "urgent",
                "manual_review",
                "no_go",
                "fail",
                "blocked",
                "warning",
                "주의",
                "긴급",
                "차단",
            )
            return "" if any(term in message for term in urgent_terms) else "discord_low_importance_brief_suppressed"

        if status in {"OK", "PASS", "READY", "MONITOR", "INFO", "NORMAL"}:
            return "discord_low_importance_status_suppressed"
        return "discord_low_importance_alert_suppressed"

    @classmethod
    def _format_discord_message(cls, *, alert_type: str, symbol: str, payload: dict[str, Any]) -> str:
        normalized_type = str(alert_type or "").strip().lower()
        if normalized_type in {"entry", "confirm", "tp", "closed", "stop", "exit", "fill"}:
            return cls._format_discord_trade_signal(alert_type=normalized_type, symbol=symbol, payload=payload)
        if normalized_type == "session_impulse_retest_miss":
            return cls._format_discord_session_miss(symbol=symbol, payload=payload)
        if normalized_type.startswith("validation_"):
            return cls._format_discord_validation(alert_type=normalized_type, symbol=symbol, payload=payload)
        if normalized_type in {"entry_surface_alert", "stage_monitor_alert"} or normalized_type.startswith(
            "operator_session_brief"
        ):
            return cls._format_discord_operational(alert_type=normalized_type, symbol=symbol, payload=payload)
        if normalized_type == "test":
            return cls._format_discord_test(symbol=symbol, payload=payload)
        return cls._format_discord_operational(alert_type=normalized_type, symbol=symbol, payload=payload)

    @staticmethod
    def _clean_label(value: Any, *, fallback: str = "-") -> str:
        text = str(value or "").strip()
        if not text:
            return fallback
        return text.replace("_", " ")

    @staticmethod
    def _short_text(value: Any, *, max_chars: int = 120) -> str:
        text = " ".join(str(value or "").strip().split())
        if len(text) <= max_chars:
            return text
        return text[: max(0, max_chars - 3)].rstrip() + "..."

    @classmethod
    def _format_discord_trade_signal(cls, *, alert_type: str, symbol: str, payload: dict[str, Any]) -> str:
        title_by_type = {
            "confirm": "진입 확인 신호",
            "entry": "진입 발생",
            "tp": "목표가 도달",
            "closed": "거래 종료",
            "stop": "손절/무효화",
            "exit": "청산 신호",
            "fill": "체결 발생",
        }
        title = title_by_type.get(alert_type, "거래 신호")
        direction = str(payload.get("direction") or "").upper()
        plan_id = str(payload.get("plan_id") or "").strip()
        price = payload.get("event_price") or payload.get("price") or payload.get("entry_price")
        expected = payload.get("expected_summary")

        lines = [f"[중요] {symbol} {title}"]
        if direction or price:
            parts = []
            if direction:
                parts.append(f"방향: {direction}")
            if price is not None:
                parts.append(f"가격: {price}")
            lines.append(" | ".join(parts))
        if expected:
            lines.append(f"기대값: {cls._short_text(expected, max_chars=100)}")
        if plan_id:
            lines.append(f"플랜: {plan_id}")
        return "\n".join(lines)

    @classmethod
    def _format_discord_validation(cls, *, alert_type: str, symbol: str, payload: dict[str, Any]) -> str:
        contract = validation_alert_contract(payload)
        approval_strip = validation_alert_strip_summary(payload)
        status = str(payload.get("status") or ("FAIL" if alert_type.endswith("fail") else "WARN")).upper()
        action = (
            contract.get("approval_playbook_action")
            or payload.get("playbook_action")
            or approval_strip.get("act_value")
            or "검증 리포트 확인"
        )
        reason = contract.get("deployment_code") or contract.get("approval_playbook_code") or payload.get("reason")
        report_path = payload.get("report_path")

        title = "검증 실패" if status == "FAIL" else "검증 주의"
        lines = [f"[주의] {symbol} {title}"]
        lines.append(f"상태: {status}")
        lines.append(f"해야 할 일: {cls._clean_label(action)}")
        if reason:
            lines.append(f"이유: {cls._clean_label(reason)}")
        if report_path:
            lines.append(f"리포트: {report_path}")
        return "\n".join(lines)

    @classmethod
    def _format_discord_session_miss(cls, *, symbol: str, payload: dict[str, Any]) -> str:
        miss_count = int(payload.get("miss_count") or 0)
        lookback_hours = int(payload.get("lookback_hours") or 0)
        symbols = ", ".join(list(payload.get("symbols_with_misses") or [])[:8])
        report_path = payload.get("report_path")

        lines = [f"[주의] {symbol} 신호 누락 가능성"]
        lines.append(f"누락: {miss_count}건 | 기간: {lookback_hours}h")
        if symbols:
            lines.append(f"심볼: {symbols}")
        if report_path:
            lines.append(f"리포트: {report_path}")
        return "\n".join(lines)

    @classmethod
    def _format_discord_operational(cls, *, alert_type: str, symbol: str, payload: dict[str, Any]) -> str:
        message = str(payload.get("message") or "").strip()
        summary_lines = [line.strip("- ").strip() for line in message.splitlines() if line.strip()]
        headline = cls._short_text(summary_lines[0] if summary_lines else alert_type, max_chars=140)
        report_path = payload.get("report_path")

        lines = [f"[운영] {symbol} 확인 필요"]
        lines.append(f"요약: {headline}")
        if len(summary_lines) > 1:
            lines.append(f"추가: {cls._short_text(summary_lines[1], max_chars=120)}")
        if report_path:
            lines.append(f"리포트: {report_path}")
        return "\n".join(lines)

    @classmethod
    def _format_discord_test(cls, *, symbol: str, payload: dict[str, Any]) -> str:
        message = cls._short_text(payload.get("message") or "테스트 알림", max_chars=120)
        return f"[테스트] {symbol}\n{message}"
