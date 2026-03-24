from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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

    SUPPORTED_CHANNELS = {"telegram", "discord", "push", "system"}
    _circuit_states: ClassVar[dict[str, _CircuitState]] = {}
    _circuit_lock: ClassVar[Lock] = Lock()

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

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

        message = self._format_message(alert_type=alert_type, symbol=symbol, payload=payload)
        if normalized == "telegram":
            return self._send_telegram(message=message)
        if normalized == "discord":
            return self._send_discord(message=message)
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

        payload = {"content": message}
        return self._post_json(
            channel="discord",
            url=webhook_url,
            json_payload=payload,
            target="discord:webhook",
        )

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

        attempts = max(1, int(self.settings.alert_retry_attempts))
        base_backoff = max(0.0, float(self.settings.alert_retry_backoff_seconds))
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                with httpx.Client(timeout=self.settings.alert_http_timeout_seconds) as client:
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
        threshold = max(1, int(self.settings.alert_circuit_breaker_failures))
        cooldown_seconds = max(0, int(self.settings.alert_circuit_breaker_cooldown_seconds))
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
