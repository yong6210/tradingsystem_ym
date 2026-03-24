from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.db.models import AlertSubscription
from app.db.repositories import AlertRepository
from app.services.deployment_contracts import validation_alert_contract, validation_report_contract
from app.services.session_guidance import SessionGuidanceService


class OperationalChecklistService:
    def __init__(
        self,
        *,
        alert_repo: AlertRepository,
        settings: Settings | None = None,
    ):
        self.alert_repo = alert_repo
        self.settings = settings or get_settings()
        self.session_guidance = SessionGuidanceService(self.settings)

    def _configured_leaf_channels(self) -> list[str]:
        channels: list[str] = []
        if self.settings.alert_telegram_bot_token and self.settings.alert_telegram_chat_id:
            channels.append("telegram")
        if self.settings.alert_discord_webhook_url:
            channels.append("discord")
        if self.settings.alert_push_webhook_url:
            channels.append("push")
        return channels

    @staticmethod
    def _normalize_ts(ts: datetime) -> datetime:
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)

    @staticmethod
    def _leaf_delivery_rows(alert: AlertSubscription) -> list[dict[str, Any]]:
        payload = dict(alert.payload or {})
        delivery = payload.get("delivery")
        if not isinstance(delivery, dict):
            return []

        rows: list[dict[str, Any]] = []
        results = delivery.get("results")
        if isinstance(results, list) and results:
            for item in results:
                if isinstance(item, dict):
                    rows.append(dict(item))
            return rows

        channel = str(delivery.get("channel", ""))
        if channel in {"telegram", "discord", "push"}:
            rows.append(dict(delivery))
        return rows

    def _recent_channel_tests(self, *, lookback_hours: int) -> dict[str, dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(lookback_hours)))
        recent_alerts = self.alert_repo.list_recent(days=max(1, ceil(lookback_hours / 24)))
        latest: dict[str, dict[str, Any]] = {}
        for alert in recent_alerts:
            if str(alert.type) != "test":
                continue
            triggered_ts = self._normalize_ts(alert.triggered_ts)
            if triggered_ts < cutoff:
                continue
            for row in self._leaf_delivery_rows(alert):
                channel = str(row.get("channel", "")).lower()
                if channel not in {"telegram", "discord", "push"}:
                    continue
                candidate = {
                    "channel": channel,
                    "tested_at": triggered_ts.isoformat(),
                    "delivered": bool(row.get("delivered")),
                    "skipped": bool(row.get("skipped")),
                    "reason": str(row.get("reason", "unknown")),
                    "attempts": int(row.get("attempts", 0) or 0),
                    "latency_ms": float(row.get("latency_ms", 0.0) or 0.0),
                    "_ts": triggered_ts,
                }
                current = latest.get(channel)
                if current is None or candidate["_ts"] > current["_ts"]:
                    latest[channel] = candidate
        for row in latest.values():
            row.pop("_ts", None)
        return latest

    @staticmethod
    def _item(
        *,
        item_id: str,
        title: str,
        category: str,
        status: str,
        summary: str,
        blocking: bool,
        source: dict[str, Any],
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "item_id": item_id,
            "title": title,
            "category": category,
            "status": status,
            "summary": summary,
            "blocking": blocking,
            "source": source,
            "evidence": evidence,
        }

    @staticmethod
    def _deployment_language(
        *,
        validation_payload: dict[str, Any],
        overall_status: str,
        blocking_failures: int,
        manual_actions: int,
        warnings: int,
    ) -> dict[str, str]:
        validation_contract = validation_report_contract(validation_payload)
        approval_go_no_go = validation_contract["playbook_go_no_go"]
        approval_code = validation_contract["playbook_code"]
        approval_action = validation_contract["playbook_action"]
        approval_message = validation_contract["playbook_message"]

        if approval_go_no_go == "NO_GO":
            return {
                "deployment_go_no_go": "NO_GO",
                "deployment_code": approval_code or "no_go_validation_approval_template",
                "deployment_message": approval_message or "NO_GO: validation approval template is blocking rollout.",
                "playbook_go_no_go": "NO_GO",
                "playbook_code": approval_code or "no_go_validation_approval_template",
                "playbook_action": approval_action or "hold_live_rollout_and_review_validation_gate",
                "playbook_message": approval_message or "NO_GO: validation approval template is blocking rollout.",
            }
        if blocking_failures > 0 or manual_actions > 0:
            return {
                "deployment_go_no_go": "NO_GO",
                "deployment_code": "no_go_operational_checklist_blocking_items",
                "deployment_message": (
                    "NO_GO: operational checklist has blocking FAIL or MANUAL items. Clear them before live rollout."
                ),
                "playbook_go_no_go": "NO_GO",
                "playbook_code": "no_go_operational_checklist_blocking_items",
                "playbook_action": "clear_blocking_operational_items_before_rollout",
                "playbook_message": (
                    "NO_GO: operational checklist has blocking FAIL or MANUAL items. Clear them before live rollout."
                ),
            }
        if approval_go_no_go == "MANUAL_REVIEW" or overall_status == "WARN" or warnings > 0:
            return {
                "deployment_go_no_go": "MANUAL_REVIEW",
                "deployment_code": approval_code or "manual_review_operational_checklist_warn",
                "deployment_message": approval_message or (
                    "MANUAL_REVIEW: non-blocking warnings remain. Review validation and operations evidence before rollout."
                ),
                "playbook_go_no_go": "MANUAL_REVIEW",
                "playbook_code": approval_code or "manual_review_operational_checklist_warn",
                "playbook_action": approval_action or "review_validation_and_operational_warnings",
                "playbook_message": approval_message or (
                    "MANUAL_REVIEW: non-blocking warnings remain. Review validation and operations evidence before rollout."
                ),
            }
        if approval_go_no_go == "GO" and overall_status == "PASS":
            return {
                "deployment_go_no_go": "GO",
                "deployment_code": "go_operational_checklist_ready",
                "deployment_message": "GO: approval template and operational checklist are aligned for rollout.",
                "playbook_go_no_go": "GO",
                "playbook_code": "go_operational_checklist_ready",
                "playbook_action": "proceed_with_operational_rollout",
                "playbook_message": "GO: approval template and operational checklist are aligned for rollout.",
            }
        return {
            "deployment_go_no_go": "MANUAL_REVIEW",
            "deployment_code": "manual_review_approval_template_missing",
            "deployment_message": (
                "MANUAL_REVIEW: operational checklist passed but approval-template deployment language is unavailable."
            ),
            "playbook_go_no_go": "MANUAL_REVIEW",
            "playbook_code": "manual_review_approval_template_missing",
            "playbook_action": "restore_approval_template_deployment_language",
            "playbook_message": (
                "MANUAL_REVIEW: operational checklist passed but approval-template deployment language is unavailable."
            ),
        }

    @staticmethod
    def _approval_strip_summary(
        *,
        validation_payload: dict[str, Any],
        deployment_language: dict[str, str],
        overall_status: str,
        blocking_failures: int,
        manual_actions: int,
        warnings: int,
    ) -> dict[str, Any]:
        validation_contract = validation_report_contract(validation_payload)
        validation_summary = dict((validation_payload.get("validation_report") or {}).get("approval_strip_summary") or {})

        playbook_go_no_go = str(deployment_language.get("playbook_go_no_go") or "")
        approve_value = "approval usable"
        if playbook_go_no_go == "NO_GO":
            approve_value = "validation/checklist no_go"
        elif playbook_go_no_go == "MANUAL_REVIEW":
            approve_value = "manual review first"

        approve_reason = str(
            deployment_language.get("deployment_message")
            or deployment_language.get("playbook_message")
            or validation_contract.get("playbook_message")
            or "operational approval strip unavailable"
        )

        validation_go_no_go = str(validation_contract.get("playbook_go_no_go") or "")
        validation_action = str(validation_contract.get("playbook_action") or "")
        checklist_action = str(deployment_language.get("playbook_action") or "")
        if validation_go_no_go and playbook_go_no_go and validation_go_no_go != playbook_go_no_go:
            align_value = "deployment_drift"
        elif validation_action and checklist_action and validation_action != checklist_action:
            align_value = "playbook_drift"
        elif validation_go_no_go or playbook_go_no_go:
            align_value = "aligned"
        else:
            align_value = "not_available"

        align_reason_parts = [
            f"validation={validation_go_no_go or 'n/a'}",
            f"checklist={playbook_go_no_go or 'n/a'}",
            f"validation_action={validation_action or 'n/a'}",
            f"checklist_action={checklist_action or 'n/a'}",
        ]
        validation_align_reason = str(validation_summary.get("align_reason") or "")
        if validation_align_reason:
            align_reason_parts.append(f"validation_align={validation_align_reason}")
        if blocking_failures > 0 or manual_actions > 0 or warnings > 0:
            align_reason_parts.append(
                f"checklist_status={overall_status} | blocking_failures={blocking_failures} | manual_actions={manual_actions} | warnings={warnings}"
            )

        act_value = checklist_action or validation_action or "continue_runtime_monitoring"
        act_reason = str(
            deployment_language.get("playbook_message")
            or validation_contract.get("playbook_message")
            or validation_summary.get("act_reason")
            or "operational action unavailable"
        )
        priority_map = {"NO_GO": "urgent", "MANUAL_REVIEW": "watch", "GO": "monitor"}

        return {
            "available": True,
            "approve_value": approve_value,
            "approve_reason": approve_reason,
            "align_value": align_value,
            "align_reason": " | ".join(part for part in align_reason_parts if part),
            "act_value": act_value,
            "act_reason": act_reason,
            "act_priority_level": priority_map.get(playbook_go_no_go, "monitor"),
        }

    def _health_item(self, *, ready: Any) -> dict[str, Any]:
        checks = dict(getattr(ready, "checks", {}) or {})
        details = dict(getattr(ready, "details", {}) or {})
        ready_status = str(getattr(ready, "status", "degraded"))
        ok = ready_status == "ready" and all(bool(value) for value in checks.values())
        return self._item(
            item_id="health_ready",
            title="Health Ready",
            category="infra",
            status="PASS" if ok else "FAIL",
            summary="all readiness checks passed" if ok else f"ready status is {ready_status}",
            blocking=True,
            source={"endpoint": "/health/ready", "fields": ["status", "checks", "details"]},
            evidence={"status": ready_status, "checks": checks, "details": details},
        )

    def _validation_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        validation_contract = validation_report_contract(validation_payload)
        status = str(report.get("status", "FAIL")).upper()
        summary = f"validation report status={status}"
        if status == "PASS":
            item_status = "PASS"
            blocking = False
        elif status == "WARN":
            item_status = "WARN"
            blocking = False
            summary = "validation is WARN; operator review required before live start"
        else:
            item_status = "FAIL"
            blocking = True
        return self._item(
            item_id="validation_report",
            title="Validation Report",
            category="validation",
            status=item_status,
            summary=summary,
            blocking=blocking,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.status",
                    "validation_report.path",
                    "deployment_go_no_go",
                    "deployment_code",
                    "deployment_message",
                    "approval_topline_status",
                    "approval_topline_code",
                    "approval_topline_message",
                    "playbook_go_no_go",
                    "playbook_code",
                    "playbook_action",
                    "playbook_message",
                    "approval_topline_summary_line",
                ],
            },
            evidence={
                "status": status,
                "path": report.get("path"),
                "generated_at": report.get("generated_at"),
                **validation_contract,
            },
        )

    def _validation_alert_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        report_status = str(report.get("status", "FAIL")).upper()
        alert = validation_payload.get("validation_alert")
        if report_status == "PASS":
            return self._item(
                item_id="validation_alert_delivery",
                title="Validation Alert Delivery",
                category="alerts",
                status="PASS",
                summary="no validation alert required for PASS report",
                blocking=False,
                source={"endpoint": "/validation/report", "fields": ["validation_alert", "validation_report.status"]},
                evidence={"report_status": report_status, "validation_alert": None},
            )

        if not isinstance(alert, dict):
            return self._item(
                item_id="validation_alert_delivery",
                title="Validation Alert Delivery",
                category="alerts",
                status="FAIL",
                summary="validation alert payload missing for WARN/FAIL report",
                blocking=True,
                source={"endpoint": "/validation/report", "fields": ["validation_alert"]},
                evidence={"report_status": report_status, "validation_alert": alert},
            )

        if not bool(alert.get("emitted")) and str(alert.get("reason")) == "cooldown_active":
            return self._item(
                item_id="validation_alert_delivery",
                title="Validation Alert Delivery",
                category="alerts",
                status="WARN",
                summary="validation alert cooldown active; latest alert should be checked manually",
                blocking=False,
                source={
                    "endpoint": "/validation/report",
                    "fields": [
                        "validation_alert.reason",
                        "validation_alert.status",
                        "validation_alert.approval_playbook_go_no_go",
                        "validation_alert.approval_playbook_code",
                        "validation_alert.approval_playbook_action",
                        "validation_alert.approval_playbook_message",
                    ],
                },
                evidence=self._validation_alert_evidence(report_status=report_status, alert=alert),
            )

        delivery = dict(alert.get("delivery") or {})
        delivered = bool(delivery.get("delivered"))
        skipped = bool(delivery.get("skipped"))
        if delivered:
            item_status = "PASS"
            summary = "validation alert delivered"
            blocking = False
        elif skipped:
            item_status = "FAIL"
            summary = f"validation alert skipped ({delivery.get('reason', 'unknown')})"
            blocking = True
        else:
            item_status = "FAIL"
            summary = f"validation alert failed ({delivery.get('reason', 'unknown')})"
            blocking = True
        return self._item(
            item_id="validation_alert_delivery",
            title="Validation Alert Delivery",
            category="alerts",
            status=item_status,
            summary=summary,
            blocking=blocking,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_alert.delivery",
                    "validation_alert.retry_queued",
                    "validation_alert.approval_playbook_go_no_go",
                    "validation_alert.approval_playbook_code",
                    "validation_alert.approval_playbook_action",
                    "validation_alert.approval_playbook_message",
                ],
            },
            evidence=self._validation_alert_evidence(report_status=report_status, alert=alert),
        )

    def _alert_slo_item(self, *, alert_metrics: dict[str, Any]) -> dict[str, Any]:
        configured_channels = self._configured_leaf_channels()
        channel_metrics = dict(alert_metrics.get("channel_metrics") or {})
        circuit_state = dict(alert_metrics.get("circuit_state") or {})
        overall = dict(alert_metrics.get("overall") or {})
        latest_validation_alert = dict(alert_metrics.get("latest_validation_alert") or {})
        overall_slo = dict(overall.get("slo") or {})
        overall_budget = dict(overall.get("error_budget") or {})
        failed_channels: list[str] = []
        warned_channels: list[str] = []
        for channel in configured_channels:
            stats = dict(channel_metrics.get(channel) or {})
            if not stats:
                warned_channels.append(f"{channel}:no_metrics")
                continue
            slo = dict(stats.get("slo") or {})
            budget = dict(stats.get("error_budget") or {})
            open_targets = int(dict(circuit_state.get(channel) or {}).get("open_targets", 0))
            if str(slo.get("status")) == "FAIL" or str(budget.get("status")) == "EXHAUSTED" or open_targets > 0:
                failed_channels.append(channel)
            elif str(slo.get("status")) in {"WARN", "INSUFFICIENT_DATA"} or str(budget.get("status")) == "WARN":
                warned_channels.append(channel)

        if failed_channels or str(overall_budget.get("status")) == "EXHAUSTED":
            status = "FAIL"
            blocking = True
            summary = f"alert SLO degraded on {failed_channels or ['overall']}"
        elif warned_channels or str(overall_slo.get("status")) in {"WARN", "INSUFFICIENT_DATA"}:
            status = "WARN"
            blocking = False
            summary = "alert SLO requires review"
        else:
            status = "PASS"
            blocking = False
            summary = "alert SLO within target"
        return self._item(
            item_id="alert_channel_slo",
            title="Alert Channel SLO",
            category="alerts",
            status=status,
            summary=summary,
            blocking=blocking,
            source={"endpoint": "/alerts/metrics", "fields": ["overall.slo", "overall.error_budget", "channel_metrics", "circuit_state"]},
            evidence={
                "configured_channels": configured_channels,
                "overall": overall,
                "failed_channels": failed_channels,
                "warned_channels": warned_channels,
                "latest_validation_alert": latest_validation_alert,
            },
        )

    @staticmethod
    def _validation_alert_evidence(*, report_status: str, alert: dict[str, Any]) -> dict[str, Any]:
        alert_dict = dict(alert or {})
        return {
            "report_status": report_status,
            **validation_alert_contract(alert_dict),
            "validation_alert": alert_dict,
        }

    def _alert_test_item(self, *, lookback_hours: int) -> dict[str, Any]:
        configured_channels = self._configured_leaf_channels()
        recent = self._recent_channel_tests(lookback_hours=lookback_hours)
        if not configured_channels:
            return self._item(
                item_id="alert_test_recent",
                title="Recent Alert Test",
                category="alerts",
                status="FAIL",
                summary="no leaf alert channel configured for live operations",
                blocking=True,
                source={"endpoint": "/alerts/test", "fields": ["delivery", "retry_queued"]},
                evidence={"configured_channels": [], "recent_tests": recent, "lookback_hours": lookback_hours},
            )

        missing = [channel for channel in configured_channels if channel not in recent]
        failed: list[str] = []
        warned: list[str] = []
        for channel in configured_channels:
            row = dict(recent.get(channel) or {})
            if not row:
                continue
            if bool(row.get("delivered")):
                continue
            if bool(row.get("skipped")):
                reason = str(row.get("reason", "unknown"))
                if reason.endswith("_not_configured") or "no_routes" in reason:
                    failed.append(f"{channel}:{reason}")
                else:
                    warned.append(f"{channel}:{reason}")
                continue
            failed.append(f"{channel}:{row.get('reason', 'unknown')}")

        if failed:
            status = "FAIL"
            blocking = True
            summary = f"recent alert test failed on {failed}"
        elif missing:
            status = "MANUAL"
            blocking = True
            summary = f"run /alerts/test for {missing}"
        elif warned:
            status = "WARN"
            blocking = False
            summary = f"recent alert test needs review on {warned}"
        else:
            status = "PASS"
            blocking = False
            summary = "recent alert tests exist for all configured channels"
        return self._item(
            item_id="alert_test_recent",
            title="Recent Alert Test",
            category="alerts",
            status=status,
            summary=summary,
            blocking=blocking,
            source={"endpoint": "/alerts/test", "fields": ["delivery", "retry_queued"], "lookback_hours": lookback_hours},
            evidence={"configured_channels": configured_channels, "recent_tests": recent},
        )

    def _retry_queue_item(self, *, alert_metrics: dict[str, Any]) -> dict[str, Any]:
        retry_queue = dict(alert_metrics.get("retry_queue") or {})
        counts = dict(retry_queue.get("counts") or {})
        dead_letter = int(counts.get("dead_letter", 0))
        queued = int(counts.get("queued", 0))
        if dead_letter > 0:
            status = "FAIL"
            blocking = True
            summary = f"dead-letter alerts present ({dead_letter})"
        elif queued > 0:
            status = "WARN"
            blocking = False
            summary = f"retry queue has queued alerts ({queued})"
        else:
            status = "PASS"
            blocking = False
            summary = "retry queue is clear"
        return self._item(
            item_id="retry_queue",
            title="Retry Queue",
            category="alerts",
            status=status,
            summary=summary,
            blocking=blocking,
            source={"endpoint": "/alerts/metrics", "fields": ["retry_queue.counts", "retry_queue.backlog_age_seconds"]},
            evidence=retry_queue,
        )

    def _outbox_item(self, *, outbox_status: dict[str, Any]) -> dict[str, Any]:
        counts = dict(outbox_status.get("counts") or {})
        pending = int(counts.get("pending", 0))
        failed = int(counts.get("failed", 0))
        backlog_age_seconds = int(outbox_status.get("backlog_age_seconds", 0) or 0)
        if failed > 0 or backlog_age_seconds > int(self.settings.event_late_seconds):
            status = "FAIL"
            blocking = True
            summary = f"outbox backlog unhealthy (failed={failed}, backlog_age_seconds={backlog_age_seconds})"
        elif pending > 0 or backlog_age_seconds > 0:
            status = "WARN"
            blocking = False
            summary = f"outbox backlog present (pending={pending}, backlog_age_seconds={backlog_age_seconds})"
        else:
            status = "PASS"
            blocking = False
            summary = "outbox backlog is clear"
        return self._item(
            item_id="event_outbox",
            title="Event Outbox",
            category="infra",
            status=status,
            summary=summary,
            blocking=blocking,
            source={"endpoint": "/internal/events/outbox/status", "fields": ["counts", "backlog_age_seconds", "retry_policy"]},
            evidence=outbox_status,
        )

    def _risk_gate_item(self, *, strategy_metrics: dict[str, Any]) -> dict[str, Any]:
        risk_state = str(strategy_metrics.get("risk_state", "CLOSED"))
        operating_lock = dict(strategy_metrics.get("operating_lock") or {})
        active_lock = bool(operating_lock.get("active"))
        if risk_state == "OPEN" and not active_lock:
            status = "PASS"
            blocking = False
            summary = "risk gate is OPEN"
        else:
            status = "FAIL"
            blocking = True
            summary = f"risk gate is {risk_state} ({strategy_metrics.get('risk_reason', 'unknown')})"
        return self._item(
            item_id="risk_gate_open",
            title="Risk Gate",
            category="risk",
            status=status,
            summary=summary,
            blocking=blocking,
            source={"endpoint": "/metrics/strategy", "fields": ["risk_state", "risk_reason", "operating_lock"]},
            evidence=strategy_metrics,
        )

    def _session_guidance_item(
        self,
        *,
        strategy_metrics: dict[str, Any],
        portfolio_budget: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        snapshot = self.session_guidance.snapshot(
            operating_lock=dict(strategy_metrics.get("operating_lock") or {}),
            strategy_mode=portfolio_budget.get("strategy_mode"),
            now=now,
        )

        return self._item(
            item_id="session_guidance",
            title="Session / Dead-Session Guidance",
            category="operations",
            status=str(snapshot.get("status", "WARN")),
            summary=str(snapshot.get("summary", "session guidance unavailable")),
            blocking=False,
            source={
                "endpoint": "/metrics/strategy + /portfolio/budget",
                "fields": ["operating_lock.current_session", "operating_lock.scope", "operating_lock.unlock_at", "strategy_mode"],
            },
            evidence=snapshot,
        )

    def _portfolio_item(self, *, portfolio_budget: dict[str, Any]) -> dict[str, Any]:
        blocked_reason_counts = dict(portfolio_budget.get("blocked_reason_counts") or {})
        current_exposure = dict(portfolio_budget.get("current_exposure") or {})
        active_clusters = int(current_exposure.get("active_thesis_clusters", 0) or 0)
        cap_related_blocks = sum(
            int(count)
            for reason, count in blocked_reason_counts.items()
            if reason in {
                "total_cap_reached",
                "directional_cap_reached",
                "cluster_cap_reached",
                "thesis_duplicate_blocked",
                "thesis_active_cap_reached",
            }
        )
        if active_clusters >= int(self.settings.thesis_max_active_clusters) or cap_related_blocks > 0:
            status = "WARN"
            summary = "portfolio headroom is constrained"
        else:
            status = "PASS"
            summary = "portfolio headroom available"
        return self._item(
            item_id="portfolio_headroom",
            title="Portfolio Headroom",
            category="portfolio",
            status=status,
            summary=summary,
            blocking=False,
            source={
                "endpoint": "/portfolio/budget",
                "fields": [
                    "deployment_go_no_go",
                    "deployment_code",
                    "deployment_message",
                    "playbook_go_no_go",
                    "playbook_code",
                    "playbook_action",
                    "playbook_message",
                    "current_exposure",
                    "headroom_by_regime",
                    "blocked_reason_counts",
                ],
            },
            evidence={
                "deployment_go_no_go": str(portfolio_budget.get("deployment_go_no_go", "") or ""),
                "deployment_code": str(portfolio_budget.get("deployment_code", "") or ""),
                "deployment_message": str(portfolio_budget.get("deployment_message", "") or ""),
                "playbook_go_no_go": str(portfolio_budget.get("playbook_go_no_go", "") or ""),
                "playbook_code": str(portfolio_budget.get("playbook_code", "") or ""),
                "playbook_action": str(portfolio_budget.get("playbook_action", "") or ""),
                "playbook_message": str(portfolio_budget.get("playbook_message", "") or ""),
                "current_exposure": current_exposure,
                "blocked_reason_counts": blocked_reason_counts,
                "strategy_mode": portfolio_budget.get("strategy_mode"),
            },
        )

    def _execution_quality_item(self, *, execution_quality: dict[str, Any]) -> dict[str, Any]:
        matured = int(execution_quality.get("plans_matured", 0) or 0)
        fill_events = int(execution_quality.get("fill_events_total", 0) or 0)
        if matured <= 0:
            status = "WARN"
            summary = "no matured plans yet; execution quality not statistically useful"
        elif fill_events <= 0:
            status = "WARN"
            summary = "execution fills are missing; quality report is mostly fallback-derived"
        else:
            status = "PASS"
            summary = "execution quality coverage available"
        return self._item(
            item_id="execution_quality_coverage",
            title="Execution Quality Coverage",
            category="execution",
            status=status,
            summary=summary,
            blocking=False,
            source={"endpoint": "/execution/quality", "fields": ["plans_matured", "fill_events_total", "report_path"]},
            evidence={
                "plans_matured": matured,
                "fill_events_total": fill_events,
                "fill_rate": execution_quality.get("fill_rate"),
                "report_path": execution_quality.get("report_path"),
            },
        )

    def _execution_degradation_advisory_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        advisory = dict(report.get("execution_degradation_advisory_summary") or {})
        available = bool(report.get("execution_degradation_advisory_available", False))
        advisory_status = str(advisory.get("status", "healthy") or "healthy").lower()
        advisory_summary = str(advisory.get("summary", "") or "").strip()
        recommended_action = str(advisory.get("recommended_action", "") or "").strip()

        if not available:
            status = "WARN"
            summary = "execution degradation advisory unavailable; review execution quality directly"
        elif advisory_status == "healthy":
            status = "PASS"
            summary = advisory_summary or "execution degradation advisory is healthy"
        elif advisory_status == "manual_review":
            status = "WARN"
            summary = advisory_summary or "execution degradation advisory recommends manual review before expansion"
        else:
            status = "WARN"
            summary = advisory_summary or "execution degradation advisory recommends closer runtime monitoring"

        return self._item(
            item_id="execution_degradation_advisory",
            title="Execution Degradation Advisory",
            category="execution",
            status=status,
            summary=summary,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.execution_degradation_advisory_available",
                    "validation_report.execution_degradation_advisory_summary.status",
                    "validation_report.execution_degradation_advisory_summary.summary",
                    "validation_report.execution_degradation_advisory_summary.recommended_action",
                ],
            },
            evidence={
                "available": available,
                "status": advisory_status,
                "summary": advisory_summary,
                "recommended_action": recommended_action,
                "reason_codes": list(advisory.get("reason_codes") or []),
                "sample_context": dict(advisory.get("sample_context") or {}),
            },
        )

    @staticmethod
    def _split_review_followup_command(*, action: str, symbol: str, universe: str, days: int) -> str:
        if action not in {"run_entry_timing_split_review", "run_execution_style_split_review"} or not symbol:
            return ""
        return (
            f"./.venv/bin/python scripts/run_split_review_followup.py "
            f"--symbol {symbol.upper()} --universe {universe} --days {max(int(days), 1)} --action {action}"
        )

    def _normalize_operator_action_priority_summary(
        self,
        payload: dict[str, Any] | None,
        *,
        symbol: str,
        universe: str,
        days: int,
    ) -> dict[str, Any]:
        summary = dict(payload or {})
        if not summary:
            return {}

        experiment_context = dict(summary.get("experiment_context") or {})
        for key, action in (
            ("entry_timing_target", "run_entry_timing_split_review"),
            ("execution_style_target", "run_execution_style_split_review"),
        ):
            target = dict(experiment_context.get(key) or {})
            if target and not target.get("followup_command"):
                target["followup_command"] = self._split_review_followup_command(
                    action=action,
                    symbol=str(target.get("symbol") or symbol or ""),
                    universe=universe,
                    days=max(int(days), 1),
                )
                experiment_context[key] = target
        if experiment_context:
            summary["experiment_context"] = experiment_context

        normalized_actions: list[dict[str, Any]] = []
        for row in list(summary.get("next_actions") or []):
            item = dict(row or {})
            if not item.get("followup_command"):
                item["followup_command"] = self._split_review_followup_command(
                    action=str(item.get("action") or ""),
                    symbol=str(item.get("target_symbol") or symbol or ""),
                    universe=universe,
                    days=max(int(days), 1),
                )
            normalized_actions.append(item)
        summary["next_actions"] = normalized_actions

        if not summary.get("top_action_followup_command"):
            top_action = str(summary.get("top_action") or "")
            top_target_key = {
                "run_entry_timing_split_review": "entry_timing_target",
                "run_execution_style_split_review": "execution_style_target",
            }.get(top_action, "")
            top_target = dict(experiment_context.get(top_target_key) or {})
            summary["top_action_followup_command"] = self._split_review_followup_command(
                action=top_action,
                symbol=str(top_target.get("symbol") or symbol or ""),
                universe=universe,
                days=max(int(days), 1),
            )
        return summary

    def _operator_action_priority_item(
        self,
        *,
        validation_payload: dict[str, Any],
        symbol: str,
        universe: str,
    ) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        score_to_outcome_summary = dict(report.get("score_to_outcome_funnel_summary") or {})
        summary_payload = self._normalize_operator_action_priority_summary(
            report.get("operator_action_priority_summary"),
            symbol=symbol,
            universe=universe,
            days=int(score_to_outcome_summary.get("report_window_days") or 7),
        )
        available = bool(summary_payload.get("available", False))
        priority_level = str(summary_payload.get("priority_level", "monitor") or "monitor").lower()
        top_action = str(summary_payload.get("top_action", "") or "").strip()
        top_reason = str(summary_payload.get("top_reason", "") or "").strip()

        if not available:
            status = "WARN"
            summary = "operator action priority unavailable; review validation/playbook directly"
        elif priority_level == "urgent":
            status = "WARN"
            summary = top_reason or "operator action priority highlights an urgent review item"
        elif priority_level == "watch":
            status = "WARN"
            summary = top_reason or "operator action priority highlights a watch-level follow-up"
        elif priority_level == "research":
            status = "PASS"
            summary = top_reason or "operator action priority is research-oriented and non-blocking"
        else:
            status = "PASS"
            summary = top_reason or "operator action priority is monitor-only"

        return self._item(
            item_id="operator_action_priority",
            title="Operator Action Priority",
            category="execution",
            status=status,
            summary=summary,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.operator_action_priority_summary.available",
                    "validation_report.operator_action_priority_summary.top_action",
                    "validation_report.operator_action_priority_summary.top_reason",
                    "validation_report.operator_action_priority_summary.top_action_followup_command",
                    "validation_report.operator_action_priority_summary.priority_level",
                    "validation_report.operator_action_priority_summary.priority_source",
                    "validation_report.operator_action_priority_summary.action_family",
                    "validation_report.operator_action_priority_summary.capture_context",
                    "validation_report.operator_action_priority_summary.experiment_context",
                    "validation_report.operator_action_priority_summary.next_actions",
                ],
            },
            evidence={
                "available": available,
                "top_action": top_action,
                "top_reason": top_reason,
                "top_action_followup_command": str(summary_payload.get("top_action_followup_command", "") or ""),
                "priority_level": priority_level,
                "priority_source": str(summary_payload.get("priority_source", "monitor") or "monitor"),
                "action_family": str(summary_payload.get("action_family", "monitor") or "monitor"),
                "supporting_signals": list(summary_payload.get("supporting_signals") or []),
                "blocking_signals": list(summary_payload.get("blocking_signals") or []),
                "next_actions": [dict(item) for item in list(summary_payload.get("next_actions") or [])[:3]],
                "capture_context": dict(summary_payload.get("capture_context") or {}),
                "experiment_context": dict(summary_payload.get("experiment_context") or {}),
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _outcome_control_trace_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("outcome_control_trace_summary") or {})
        available = bool(report.get("outcome_control_trace_available", False) or summary_payload.get("available", False))
        approval_tier = str(summary_payload.get("approval_penalty_tier", "none") or "none").lower()
        sizing_tier = str(summary_payload.get("sizing_penalty_tier", "none") or "none").lower()
        portfolio_tier = str(summary_payload.get("portfolio_bias_tier", "neutral") or "neutral").lower()
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "WARN"
            message = "outcome control trace unavailable; review approval, sizing, and portfolio penalties directly"
        elif approval_tier == "downgrade_to_manual":
            status = "WARN"
            message = summary or "approval downgraded by outcome-first controls; review before acting"
        elif sizing_tier == "hard_clamp":
            status = "WARN"
            message = summary or "risk allowance was materially reduced by outcome-first controls"
        else:
            status = "PASS"
            message = summary or "outcome-first control trace is informational only"

        return self._item(
            item_id="outcome_control_trace",
            title="Outcome Control Trace",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.outcome_control_trace_available",
                    "validation_report.outcome_control_trace_summary.approval_penalty_tier",
                    "validation_report.outcome_control_trace_summary.sizing_penalty_tier",
                    "validation_report.outcome_control_trace_summary.portfolio_bias_tier",
                    "validation_report.outcome_control_trace_summary.top_reason_codes",
                ],
            },
            evidence={
                "available": available,
                "approval_penalty_status": str(summary_payload.get("approval_penalty_status", "healthy") or "healthy"),
                "approval_penalty_tier": approval_tier,
                "sizing_penalty_status": str(summary_payload.get("sizing_penalty_status", "healthy") or "healthy"),
                "sizing_penalty_tier": sizing_tier,
                "sizing_multiplier": float(summary_payload.get("sizing_multiplier", 1.0) or 1.0),
                "portfolio_bias_tier": portfolio_tier,
                "portfolio_bias_score_delta": float(summary_payload.get("portfolio_bias_score_delta", 0.0) or 0.0),
                "top_reason_codes": list(summary_payload.get("top_reason_codes") or []),
            },
        )

    def _money_funnel_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        score_to_outcome = dict(report.get("score_to_outcome_funnel_summary") or {})
        summary_payload = dict(score_to_outcome.get("money_funnel") or {})
        available = bool(summary_payload.get("available", False))
        historical_expected = dict(summary_payload.get("historical_expected_r") or {})
        historical_realized = dict(summary_payload.get("historical_realized_r") or {})
        historical_gap = dict(summary_payload.get("historical_gap_r") or {})
        submitted_to_filled_gap_r = float(historical_gap.get("submitted_to_filled", 0.0) or 0.0)
        closed_post_cost_delta_r = float(historical_gap.get("closed_expected_to_post_cost_realized", 0.0) or 0.0)
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "money funnel unavailable; keep expected-R conversion review informational only"
        elif submitted_to_filled_gap_r >= 0.25:
            status = "WARN"
            message = summary or "expected R is leaking materially between submit and fill"
        elif closed_post_cost_delta_r <= -0.15:
            status = "WARN"
            message = summary or "closed post-cost realized R is trailing expected closed R"
        else:
            status = "PASS"
            message = summary or "money funnel is informational only"

        return self._item(
            item_id="money_funnel",
            title="Money Funnel",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.score_to_outcome_funnel_summary.money_funnel.available",
                    "validation_report.score_to_outcome_funnel_summary.money_funnel.snapshot_expected_r",
                    "validation_report.score_to_outcome_funnel_summary.money_funnel.historical_expected_r",
                    "validation_report.score_to_outcome_funnel_summary.money_funnel.historical_realized_r",
                    "validation_report.score_to_outcome_funnel_summary.money_funnel.historical_gap_r",
                ],
            },
            evidence={
                "available": available,
                "snapshot_expected_r": dict(summary_payload.get("snapshot_expected_r") or {}),
                "historical_expected_r": historical_expected,
                "historical_realized_r": historical_realized,
                "historical_gap_r": historical_gap,
            },
        )

    def _outcome_attribution_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("outcome_attribution_summary") or {})
        available = bool(report.get("outcome_attribution_available", False) or summary_payload.get("available", False))
        strongest_drag_source = str(summary_payload.get("strongest_drag_source", "none") or "none").lower()
        closed_post_cost_delta_r = float(summary_payload.get("closed_post_cost_delta_r", 0.0) or 0.0)
        fill_capture_gap_r = float(summary_payload.get("fill_capture_gap_r", 0.0) or 0.0)
        closed_trade_count = int(summary_payload.get("closed_trade_count", 0) or 0)
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "outcome attribution unavailable; keep drag decomposition informational only"
        elif strongest_drag_source == "fill_capture_gap" and fill_capture_gap_r >= 0.25:
            status = "WARN"
            message = summary or "expected edge is leaking before fills are captured"
        elif strongest_drag_source in {"execution_component", "condition_component"} and closed_post_cost_delta_r <= -0.15:
            status = "WARN"
            message = summary or "closed post-cost attribution is drifting below expected edge"
        elif closed_trade_count >= 4 and closed_post_cost_delta_r <= -0.15:
            status = "WARN"
            message = summary or "closed post-cost attribution is drifting below expected edge"
        else:
            status = "PASS"
            message = summary or "outcome attribution is informational only"

        return self._item(
            item_id="outcome_attribution",
            title="Outcome Attribution",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.outcome_attribution_available",
                    "validation_report.outcome_attribution_summary.strongest_drag_source",
                    "validation_report.outcome_attribution_summary.strategy_component_r",
                    "validation_report.outcome_attribution_summary.execution_component_r",
                    "validation_report.outcome_attribution_summary.condition_component_r",
                    "validation_report.outcome_attribution_summary.fill_capture_gap_r",
                    "validation_report.outcome_attribution_summary.closed_post_cost_delta_r",
                ],
            },
            evidence={
                "available": available,
                "confidence": str(summary_payload.get("confidence", "low") or "low"),
                "closed_trade_count": closed_trade_count,
                "strongest_drag_source": strongest_drag_source,
                "strategy_component_r": float(summary_payload.get("strategy_component_r", 0.0) or 0.0),
                "execution_component_r": float(summary_payload.get("execution_component_r", 0.0) or 0.0),
                "condition_component_r": float(summary_payload.get("condition_component_r", 0.0) or 0.0),
                "fill_capture_gap_r": fill_capture_gap_r,
                "closed_expected_r": float(summary_payload.get("closed_expected_r", 0.0) or 0.0),
                "closed_post_cost_realized_r": float(summary_payload.get("closed_post_cost_realized_r", 0.0) or 0.0),
                "closed_post_cost_delta_r": closed_post_cost_delta_r,
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "source_summary": dict(summary_payload.get("source_summary") or {}),
            },
        )

    def _edge_experiment_review_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("edge_experiment_review_summary") or {})
        available = bool(report.get("edge_experiment_review_available", False) or summary_payload.get("available", False))
        edge_state = str(summary_payload.get("edge_state", "insufficient_edge_measurement") or "insufficient_edge_measurement")
        true_edge_ratio = float(summary_payload.get("true_edge_ratio", 0.0) or 0.0)
        edge_decay_rate = float(summary_payload.get("edge_decay_rate", 0.0) or 0.0)
        entry_timing_ready = bool(summary_payload.get("entry_timing_comparison_ready", False))
        execution_style_ready = bool(summary_payload.get("execution_style_comparison_ready", False))
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "edge experiment review unavailable; keep timing/style experiments informational only"
        elif edge_state == "fragile_edge":
            status = "WARN"
            message = summary or "post-cost true edge is fragile; prefer controlled split tests before rollout changes"
        elif edge_state == "watch_edge" and (entry_timing_ready or execution_style_ready):
            status = "WARN"
            message = summary or "edge is unstable enough that timing/style split tests should precede expansion"
        else:
            status = "PASS"
            message = summary or "edge experiment review is informational only"

        return self._item(
            item_id="edge_experiment_review",
            title="Edge Experiment Review",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.edge_experiment_review_available",
                    "validation_report.edge_experiment_review_summary.edge_state",
                    "validation_report.edge_experiment_review_summary.true_edge_ratio",
                    "validation_report.edge_experiment_review_summary.edge_decay_rate",
                    "validation_report.edge_experiment_review_summary.entry_timing_preferred_variant",
                    "validation_report.edge_experiment_review_summary.execution_style_preferred_variant",
                ],
            },
            evidence={
                "available": available,
                "edge_state": edge_state,
                "true_edge_ratio": true_edge_ratio,
                "recent_true_edge_ratio": float(summary_payload.get("recent_true_edge_ratio", 0.0) or 0.0),
                "prior_true_edge_ratio": float(summary_payload.get("prior_true_edge_ratio", 0.0) or 0.0),
                "edge_decay_rate": edge_decay_rate,
                "edge_stability": float(summary_payload.get("edge_stability", 0.0) or 0.0),
                "closed_trade_count": int(summary_payload.get("closed_trade_count", 0) or 0),
                "entry_timing_available": bool(summary_payload.get("entry_timing_available", False)),
                "entry_timing_comparison_ready": entry_timing_ready,
                "entry_timing_preferred_variant": str(
                    summary_payload.get("entry_timing_preferred_variant", "none") or "none"
                ),
                "entry_timing_recommendation_reason": str(
                    summary_payload.get("entry_timing_recommendation_reason", "not_available") or "not_available"
                ),
                "execution_style_available": bool(summary_payload.get("execution_style_available", False)),
                "execution_style_comparison_ready": execution_style_ready,
                "execution_style_preferred_variant": str(
                    summary_payload.get("execution_style_preferred_variant", "none") or "none"
                ),
                "execution_style_recommendation_reason": str(
                    summary_payload.get("execution_style_recommendation_reason", "not_available") or "not_available"
                ),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "source_summary": dict(summary_payload.get("source_summary") or {}),
            },
        )

    def _edge_evolution_rule_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("edge_evolution_rule_summary") or {})
        available = bool(report.get("edge_evolution_rule_available", False) or summary_payload.get("available", False))
        evolution_state = str(summary_payload.get("evolution_state", "insufficient_sample") or "insufficient_sample")
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "edge evolution rule unavailable; keep branch promotion and allocation changes advisory only"
        elif evolution_state == "edge_kill_review":
            status = "MANUAL"
            message = summary or "edge deterioration now justifies kill-condition review before trusting further live allocation"
        elif evolution_state == "reduce_candidate":
            status = "WARN"
            message = summary or "baseline allocation should be reduced until preferred branch evidence improves"
        else:
            status = "PASS"
            message = summary or "edge evolution rule is informational only"

        return self._item(
            item_id="edge_evolution_rule",
            title="Edge Evolution Rule",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.edge_evolution_rule_available",
                    "validation_report.edge_evolution_rule_summary.evolution_state",
                    "validation_report.edge_evolution_rule_summary.recommended_action",
                    "validation_report.edge_evolution_rule_summary.allocation_bias",
                    "validation_report.edge_evolution_rule_summary.promotion_candidate_axis",
                    "validation_report.edge_evolution_rule_summary.promotion_candidate_variant",
                ],
            },
            evidence={
                "available": available,
                "evolution_state": evolution_state,
                "recommended_action": str(summary_payload.get("recommended_action", "keep_current_baseline") or "keep_current_baseline"),
                "allocation_bias": str(summary_payload.get("allocation_bias", "hold_current_baseline") or "hold_current_baseline"),
                "confidence": str(summary_payload.get("confidence", "low") or "low"),
                "true_edge_ratio": float(summary_payload.get("true_edge_ratio", 0.0) or 0.0),
                "edge_decay_rate": float(summary_payload.get("edge_decay_rate", 0.0) or 0.0),
                "closed_trade_count": int(summary_payload.get("closed_trade_count", 0) or 0),
                "kill_review_triggered": bool(summary_payload.get("kill_review_triggered", False)),
                "promotion_candidate_axis": str(summary_payload.get("promotion_candidate_axis", "none") or "none"),
                "promotion_candidate_variant": str(summary_payload.get("promotion_candidate_variant", "none") or "none"),
                "promotion_candidate_reason": str(summary_payload.get("promotion_candidate_reason", "not_available") or "not_available"),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "source_summary": dict(summary_payload.get("source_summary") or {}),
            },
        )

    def _rollout_recommendation_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("rollout_recommendation_summary") or {})
        available = bool(report.get("rollout_recommendation_available", False) or summary_payload.get("available", False))
        recommendation = str(summary_payload.get("recommendation", "hold") or "hold").lower()
        current_policy = dict(summary_payload.get("current_policy") or {})
        suggested_delta = dict(summary_payload.get("suggested_policy_delta") or {})
        current_mode = str(current_policy.get("max_execution_mode", "SHADOW") or "SHADOW").upper()
        live_enabled = bool(current_policy.get("live_enabled", False))
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            blocking = False
            message = "rollout recommendation unavailable; keep current family rollout policy unchanged"
        elif recommendation == "reduce" and (live_enabled or current_mode in {"MICRO_LIVE", "LIVE"}):
            status = "MANUAL"
            blocking = True
            message = summary or "live rollout policy should be reviewed for possible reduction"
        elif recommendation in {"reduce", "research_only"}:
            status = "WARN"
            blocking = False
            message = summary or "rollout recommendation suggests caution before expansion"
        else:
            status = "PASS"
            blocking = False
            message = summary or "rollout recommendation is informational only"

        return self._item(
            item_id="rollout_recommendation",
            title="Rollout Recommendation",
            category="execution",
            status=status,
            summary=message,
            blocking=blocking,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.rollout_recommendation_available",
                    "validation_report.rollout_recommendation_summary.family",
                    "validation_report.rollout_recommendation_summary.recommendation",
                    "validation_report.rollout_recommendation_summary.current_policy",
                    "validation_report.rollout_recommendation_summary.suggested_policy_delta",
                ],
            },
            evidence={
                "available": available,
                "family": str(summary_payload.get("family", "") or ""),
                "recommendation": recommendation,
                "confidence": str(summary_payload.get("confidence", "low") or "low"),
                "maturity": str(summary_payload.get("maturity", "thin_sample") or "thin_sample"),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "current_policy": current_policy,
                "suggested_policy_delta": suggested_delta,
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _opportunity_capture_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("opportunity_capture_summary") or {})
        available = bool(report.get("opportunity_capture_available", False) or summary_payload.get("available", False))
        dominant_bottleneck = dict(summary_payload.get("dominant_bottleneck") or {})
        family_focus = dict(summary_payload.get("family_focus") or {})
        capture_gap = dict(summary_payload.get("capture_gap") or {})
        blocked_mix = dict(summary_payload.get("blocked_mix") or {})
        stage = str(dominant_bottleneck.get("stage", "unknown") or "unknown")
        reason = str(dominant_bottleneck.get("reason", "unknown") or "unknown")
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "opportunity capture unavailable; keep throughput review informational only"
        elif reason == "thin_activity_window":
            status = "PASS"
            message = summary or "activity is thin; do not treat throughput scarcity as a threshold problem yet"
        elif stage == "runtime_to_submit" and reason in {"quality_blocking", "rollout_blocking", "structural_blocking"}:
            status = "WARN"
            message = summary or "selection throughput is constrained before submission; review blocking mix"
        elif stage == "submit_to_fill" and reason == "execution_fill_shortfall":
            status = "WARN"
            message = summary or "signal flow reaches submission but degrades at fill; review execution throughput"
        else:
            status = "PASS"
            message = summary or "opportunity capture is informational only"

        return self._item(
            item_id="opportunity_capture",
            title="Opportunity Capture",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.opportunity_capture_available",
                    "validation_report.opportunity_capture_summary.dominant_bottleneck",
                    "validation_report.opportunity_capture_summary.capture_gap",
                    "validation_report.opportunity_capture_summary.family_focus",
                    "validation_report.opportunity_capture_summary.blocked_mix",
                ],
            },
            evidence={
                "available": available,
                "dominant_bottleneck": dominant_bottleneck,
                "capture_gap": capture_gap,
                "family_focus": family_focus,
                "blocked_mix": blocked_mix,
            },
        )

    def _capital_allocator_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("capital_allocator_summary") or {})
        available = bool(report.get("capital_allocator_available", False) or summary_payload.get("available", False))
        allocator_state = str(summary_payload.get("allocator_state", "neutral") or "neutral")
        family_focus = str(summary_payload.get("family_focus", "") or "")
        capital_pressure = str(summary_payload.get("capital_pressure", "neutral") or "neutral")
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "capital allocator unavailable; keep family capital tilt informational only"
        elif capital_pressure == "overallocated_negative":
            status = "WARN"
            message = summary or "negative family concentration is already high; review capital allocation before adding more risk"
        else:
            status = "PASS"
            message = summary or "capital allocator is informational only"

        return self._item(
            item_id="capital_allocator",
            title="Capital Allocator",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.capital_allocator_available",
                    "validation_report.capital_allocator_summary.allocator_state",
                    "validation_report.capital_allocator_summary.family_focus",
                    "validation_report.capital_allocator_summary.capital_pressure",
                    "validation_report.capital_allocator_summary.family_weights",
                ],
            },
            evidence={
                "available": available,
                "allocator_state": allocator_state,
                "family_focus": family_focus,
                "capital_pressure": capital_pressure,
                "family_weights": [dict(item) for item in list(summary_payload.get("family_weights") or [])[:3]],
                "advisory_only": bool(summary_payload.get("advisory_only", False)),
            },
        )

    def _strategy_lifecycle_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("strategy_lifecycle_summary") or {})
        available = bool(report.get("strategy_lifecycle_available", False) or summary_payload.get("available", False))
        state = str(summary_payload.get("state", "research") or "research").lower()
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "strategy lifecycle unavailable; keep governance review informational only"
        elif state == "retired":
            status = "WARN"
            message = summary or "family appears ready to move out of live rotation and remain research backlog only"
        elif state == "degraded":
            status = "WARN"
            message = summary or "family has weakened from probation or production posture and needs governance review"
        elif state == "probation":
            status = "PASS"
            message = summary or "family is in probation and should be monitored before broader promotion"
        elif state == "production":
            status = "PASS"
            message = summary or "family currently reads as production posture"
        else:
            status = "PASS"
            message = summary or "family remains research-led until stronger evidence accumulates"

        return self._item(
            item_id="strategy_lifecycle",
            title="Strategy Lifecycle",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.strategy_lifecycle_available",
                    "validation_report.strategy_lifecycle_summary.state",
                    "validation_report.strategy_lifecycle_summary.transition_bias",
                    "validation_report.strategy_lifecycle_summary.reason_codes",
                ],
            },
            evidence={
                "available": available,
                "family": str(summary_payload.get("family", "") or ""),
                "state": state,
                "previous_state": str(summary_payload.get("previous_state", "research") or "research"),
                "transition_bias": str(summary_payload.get("transition_bias", "hold") or "hold"),
                "confidence": str(summary_payload.get("confidence", "low") or "low"),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "source_summary": dict(summary_payload.get("source_summary") or {}),
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _promotion_governance_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("promotion_governance_summary") or {})
        available = bool(
            report.get("promotion_governance_available", False) or summary_payload.get("available", False)
        )
        state = str(summary_payload.get("state", "defer") or "defer").lower()
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "promotion governance unavailable; keep promotion review informational only"
        elif state == "defer":
            status = "WARN"
            message = summary or "promotion review should be deferred while guardrails remain active"
        elif state == "promotable":
            status = "PASS"
            message = summary or "family can be reviewed as a controlled promotion candidate, not an auto-promotion"
        else:
            status = "PASS"
            message = summary or "keep current posture and continue evidence accumulation before promotion review"

        return self._item(
            item_id="promotion_governance",
            title="Promotion Governance",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.promotion_governance_available",
                    "validation_report.promotion_governance_summary.state",
                    "validation_report.promotion_governance_summary.promotion_bias",
                    "validation_report.promotion_governance_summary.target_posture",
                    "validation_report.promotion_governance_summary.reason_codes",
                ],
            },
            evidence={
                "available": available,
                "family": str(summary_payload.get("family", "") or ""),
                "state": state,
                "promotion_bias": str(summary_payload.get("promotion_bias", "defer") or "defer"),
                "target_posture": str(summary_payload.get("target_posture", "keep_current") or "keep_current"),
                "confidence": str(summary_payload.get("confidence", "low") or "low"),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "source_summary": dict(summary_payload.get("source_summary") or {}),
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _promotion_review_queue_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("promotion_review_queue_summary") or {})
        available = bool(
            report.get("promotion_review_queue_available", False) or summary_payload.get("available", False)
        )
        queue_state = str(summary_payload.get("queue_state", "empty_queue") or "empty_queue").lower()
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "promotion review queue unavailable; keep governance ordering informational only"
        elif queue_state == "defer_first_queue":
            status = "WARN"
            message = summary or "review defer causes first before broader promotion review resumes"
        elif queue_state == "promotion_ready_queue":
            status = "PASS"
            message = summary or "review promotion-ready families first in controlled governance order"
        else:
            status = "PASS"
            message = summary or "keep current families in monitor queue while evidence accumulates"

        return self._item(
            item_id="promotion_review_queue",
            title="Promotion Review Queue",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.promotion_review_queue_available",
                    "validation_report.promotion_review_queue_summary.queue_state",
                    "validation_report.promotion_review_queue_summary.headline_family",
                    "validation_report.promotion_review_queue_summary.top_review_action",
                    "validation_report.promotion_review_queue_summary.reason_codes",
                ],
            },
            evidence={
                "available": available,
                "queue_state": queue_state,
                "headline_family": str(summary_payload.get("headline_family", "") or ""),
                "top_review_action": str(summary_payload.get("top_review_action", "") or ""),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "review_queue": [dict(item) for item in list(summary_payload.get("review_queue") or [])[:5]],
                "source_summary": dict(summary_payload.get("source_summary") or {}),
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _promotion_remediation_queue_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("promotion_remediation_queue_summary") or {})
        available = bool(
            report.get("promotion_remediation_queue_available", False) or summary_payload.get("available", False)
        )
        queue_state = str(summary_payload.get("queue_state", "empty_queue") or "empty_queue").lower()
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "promotion remediation queue unavailable; keep remediation ordering informational only"
        elif queue_state in {"execution_first_queue", "policy_first_queue", "condition_first_queue"}:
            status = "WARN"
            message = summary or "review remediation queue before reopening promotion review"
        else:
            status = "PASS"
            message = summary or "keep current families in observe queue while evidence accumulates"

        return self._item(
            item_id="promotion_remediation_queue",
            title="Promotion Remediation Queue",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.promotion_remediation_queue_available",
                    "validation_report.promotion_remediation_queue_summary.queue_state",
                    "validation_report.promotion_remediation_queue_summary.headline_family",
                    "validation_report.promotion_remediation_queue_summary.top_remediation_action",
                    "validation_report.promotion_remediation_queue_summary.reason_codes",
                ],
            },
            evidence={
                "available": available,
                "queue_state": queue_state,
                "headline_family": str(summary_payload.get("headline_family", "") or ""),
                "top_remediation_action": str(summary_payload.get("top_remediation_action", "") or ""),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "remediation_queue": [dict(item) for item in list(summary_payload.get("remediation_queue") or [])[:5]],
                "source_summary": dict(summary_payload.get("source_summary") or {}),
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _promotion_clearance_tracker_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("promotion_clearance_tracker_summary") or {})
        available = bool(
            report.get("promotion_clearance_tracker_available", False) or summary_payload.get("available", False)
        )
        clearance_state = str(summary_payload.get("clearance_state", "observe_only") or "observe_only").lower()
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "promotion clearance tracker unavailable; keep clearance progress informational only"
        elif clearance_state in {"blocked", "partial_clear"}:
            status = "WARN"
            message = summary or "clearance progress still shows at least one guardrail domain under review"
        else:
            status = "PASS"
            message = summary or "clearance tracking remains informational while review readiness updates"

        return self._item(
            item_id="promotion_clearance_tracker",
            title="Promotion Clearance Tracker",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.promotion_clearance_tracker_available",
                    "validation_report.promotion_clearance_tracker_summary.clearance_state",
                    "validation_report.promotion_clearance_tracker_summary.clearance_bias",
                    "validation_report.promotion_clearance_tracker_summary.reason_codes",
                ],
            },
            evidence={
                "available": available,
                "family": str(summary_payload.get("family", "") or ""),
                "clearance_state": clearance_state,
                "clearance_bias": str(summary_payload.get("clearance_bias", "observe") or "observe"),
                "confidence": str(summary_payload.get("confidence", "low") or "low"),
                "remaining_guardrail_domains": list(summary_payload.get("remaining_guardrail_domains") or []),
                "cleared_guardrail_domains": list(summary_payload.get("cleared_guardrail_domains") or []),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "source_summary": dict(summary_payload.get("source_summary") or {}),
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _promotion_reopen_queue_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("promotion_reopen_queue_summary") or {})
        available = bool(report.get("promotion_reopen_queue_available", False) or summary_payload.get("available", False))
        queue_state = str(summary_payload.get("queue_state", "empty_queue") or "empty_queue").lower()
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "promotion reopen queue unavailable; keep re-open ordering informational only"
        elif queue_state in {"reopen_ready_queue", "clearance_first_queue"}:
            status = "WARN"
            message = summary or "re-open ordering highlights at least one family for immediate review or continued clearance"
        else:
            status = "PASS"
            message = summary or "re-open ordering remains in observe queue while evidence accumulates"

        return self._item(
            item_id="promotion_reopen_queue",
            title="Promotion Reopen Queue",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.promotion_reopen_queue_available",
                    "validation_report.promotion_reopen_queue_summary.queue_state",
                    "validation_report.promotion_reopen_queue_summary.headline_family",
                    "validation_report.promotion_reopen_queue_summary.top_reopen_action",
                    "validation_report.promotion_reopen_queue_summary.reason_codes",
                ],
            },
            evidence={
                "available": available,
                "queue_state": queue_state,
                "headline_family": str(summary_payload.get("headline_family", "") or ""),
                "top_reopen_action": str(summary_payload.get("top_reopen_action", "") or ""),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "reopen_queue": [dict(item) for item in list(summary_payload.get("reopen_queue") or [])[:5]],
                "source_summary": dict(summary_payload.get("source_summary") or {}),
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _promotion_decision_brief_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("promotion_decision_brief_summary") or {})
        available = bool(
            report.get("promotion_decision_brief_available", False) or summary_payload.get("available", False)
        )
        brief_state = str(summary_payload.get("brief_state", "observe_case") or "observe_case").lower()
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "promotion decision brief unavailable; keep family case compression informational only"
        elif brief_state == "clearance_required":
            status = "WARN"
            message = summary or "family still needs clearance work before promotion review should be reopened"
        else:
            status = "PASS"
            message = summary or "family brief remains compare-only while promotion posture is reviewed"

        return self._item(
            item_id="promotion_decision_brief",
            title="Promotion Decision Brief",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.promotion_decision_brief_available",
                    "validation_report.promotion_decision_brief_summary.family",
                    "validation_report.promotion_decision_brief_summary.brief_state",
                    "validation_report.promotion_decision_brief_summary.decision_bias",
                    "validation_report.promotion_decision_brief_summary.reason_codes",
                ],
            },
            evidence={
                "available": available,
                "family": str(summary_payload.get("family", "") or ""),
                "brief_state": brief_state,
                "decision_bias": str(summary_payload.get("decision_bias", "observe_only") or "observe_only"),
                "target_posture": str(summary_payload.get("target_posture", "keep_current") or "keep_current"),
                "confidence": str(summary_payload.get("confidence", "low") or "low"),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "source_summary": dict(summary_payload.get("source_summary") or {}),
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _auto_promotion_rollout_execution_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("auto_promotion_rollout_execution_summary") or {})
        available = bool(
            report.get("auto_promotion_rollout_execution_available", False) or summary_payload.get("available", False)
        )
        execution_stage = str(summary_payload.get("execution_stage", "advisory_only") or "advisory_only").lower()
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "auto promotion rollout execution unavailable; keep execution candidate language informational only"
        elif execution_stage == "auto_execution_blocked":
            status = "WARN"
            message = summary or "auto execution remains blocked while promotion or rollout guardrails stay active"
        else:
            status = "PASS"
            message = summary or "auto promotion rollout execution remains compare-only with no direct write scope"

        return self._item(
            item_id="auto_promotion_rollout_execution",
            title="Auto Promotion Rollout Execution",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.auto_promotion_rollout_execution_available",
                    "validation_report.auto_promotion_rollout_execution_summary.execution_stage",
                    "validation_report.auto_promotion_rollout_execution_summary.execution_bias",
                    "validation_report.auto_promotion_rollout_execution_summary.action_domain",
                    "validation_report.auto_promotion_rollout_execution_summary.reason_codes",
                ],
            },
            evidence={
                "available": available,
                "execution_stage": execution_stage,
                "execution_bias": str(summary_payload.get("execution_bias", "keep_manual") or "keep_manual"),
                "action_domain": str(summary_payload.get("action_domain", "no_write_observe") or "no_write_observe"),
                "target_family": str(summary_payload.get("target_family", "") or ""),
                "target_posture": str(summary_payload.get("target_posture", "keep_current") or "keep_current"),
                "write_scope": str(summary_payload.get("write_scope", "none") or "none"),
                "dry_run_only": bool(summary_payload.get("dry_run_only", False)),
                "confidence": str(summary_payload.get("confidence", "low") or "low"),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "source_summary": dict(summary_payload.get("source_summary") or {}),
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _multi_strategy_ab_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("multi_strategy_ab_summary") or {})
        available = bool(report.get("multi_strategy_ab_available", False) or summary_payload.get("available", False))
        mode = str(summary_payload.get("mode", "A_ONLY") or "A_ONLY").upper()
        b_cluster = dict(summary_payload.get("b_cluster") or {})
        summary = str(summary_payload.get("summary", "") or "").strip()
        b_status = str(b_cluster.get("strategy_cluster_status") or "").lower()

        if not available:
            status = "PASS"
            message = "multi-strategy A/B summary unavailable; keep family coexistence review informational only"
        elif mode == "A_PLUS_B" and b_status in {"available_but_guarded", "compare_only", "research_only"}:
            status = "WARN"
            message = summary or "B family is visible but still guarded; review its rollout and execution guardrails first"
        else:
            status = "PASS"
            message = summary or "A/B expansion remains informational only"

        return self._item(
            item_id="multi_strategy_ab_expansion",
            title="Multi Strategy AB Expansion",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.multi_strategy_ab_available",
                    "validation_report.multi_strategy_ab_summary.mode",
                    "validation_report.multi_strategy_ab_summary.a_cluster",
                    "validation_report.multi_strategy_ab_summary.b_cluster",
                    "validation_report.multi_strategy_ab_summary.family_mix",
                ],
            },
            evidence={
                "available": available,
                "mode": mode,
                "a_cluster": dict(summary_payload.get("a_cluster") or {}),
                "b_cluster": b_cluster,
                "family_mix": [dict(item) for item in list(summary_payload.get("family_mix") or [])[:3]],
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _b_continuation_activation_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("b_continuation_activation_summary") or {})
        available = bool(
            report.get("b_continuation_activation_available", False) or summary_payload.get("available", False)
        )
        activation_state = str(summary_payload.get("activation_state", "research_only") or "research_only").lower()
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "B continuation activation summary unavailable; keep first-wave activation review informational only"
        elif activation_state in {"blocked", "guarded_probation"}:
            status = "WARN"
            message = summary or "B continuation remains guarded; clear first-wave blockers before activation review"
        else:
            status = "PASS"
            message = summary or "B continuation activation remains informational only"

        return self._item(
            item_id="b_continuation_activation",
            title="B Continuation Activation",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.b_continuation_activation_available",
                    "validation_report.b_continuation_activation_summary.family",
                    "validation_report.b_continuation_activation_summary.activation_state",
                    "validation_report.b_continuation_activation_summary.activation_bias",
                    "validation_report.b_continuation_activation_summary.reason_codes",
                ],
            },
            evidence={
                "available": available,
                "family": str(summary_payload.get("family", "trend_continuation") or "trend_continuation"),
                "activation_state": activation_state,
                "activation_bias": str(summary_payload.get("activation_bias", "stay_research") or "stay_research"),
                "target_mode": str(summary_payload.get("target_mode", "A_ONLY") or "A_ONLY"),
                "live_eligible": bool(summary_payload.get("live_eligible", False)),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "source_summary": dict(summary_payload.get("source_summary") or {}),
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _execution_friction_measurement_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("execution_friction_measurement_summary") or {})
        available = bool(
            report.get("execution_friction_measurement_available", False) or summary_payload.get("available", False)
        )
        friction_state = str(summary_payload.get("friction_state", "insufficient_measurement") or "insufficient_measurement")
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "Execution friction measurement unavailable; keep drag review informational only"
        elif friction_state in {"watch_friction", "degraded_friction"}:
            status = "WARN"
            message = summary or "Measured execution drag needs review before trusting current live confidence"
        elif friction_state == "healthy_friction":
            status = "PASS"
            message = summary or "Measured execution friction remains within current operating tolerance"
        else:
            status = "PASS"
            message = summary or "Execution friction evidence is still thin; gather more measured coverage first"

        return self._item(
            item_id="execution_friction_measurement",
            title="Execution Friction Measurement",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.execution_friction_measurement_available",
                    "validation_report.execution_friction_measurement_summary.friction_state",
                    "validation_report.execution_friction_measurement_summary.friction_bias",
                    "validation_report.execution_friction_measurement_summary.reason_codes",
                ],
            },
            evidence={
                "available": available,
                "friction_state": friction_state,
                "friction_bias": str(
                    summary_payload.get("friction_bias", "gather_more_execution_evidence")
                    or "gather_more_execution_evidence"
                ),
                "fill_conversion_state": str(
                    summary_payload.get("fill_conversion_state", "healthy_fill_conversion")
                    or "healthy_fill_conversion"
                ),
                "slippage_state": str(summary_payload.get("slippage_state", "healthy_slippage") or "healthy_slippage"),
                "latency_state": str(summary_payload.get("latency_state", "healthy_latency") or "healthy_latency"),
                "fee_state": str(summary_payload.get("fee_state", "healthy_fee_drag") or "healthy_fee_drag"),
                "reconciliation_state": str(
                    summary_payload.get("reconciliation_state", "healthy_reconciliation") or "healthy_reconciliation"
                ),
                "measurement_coverage_state": str(
                    summary_payload.get("measurement_coverage_state", "thin_measurement") or "thin_measurement"
                ),
                "weakest_axis": str(summary_payload.get("weakest_axis", "") or ""),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "source_summary": dict(summary_payload.get("source_summary") or {}),
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _strategy_cluster_balance_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("strategy_cluster_balance_summary") or {})
        available = bool(
            report.get("strategy_cluster_balance_available", False) or summary_payload.get("available", False)
        )
        balance_state = str(summary_payload.get("balance_state", "a_concentrated") or "a_concentrated").lower()
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "strategy cluster balance summary unavailable; keep A/B mix review informational only"
        elif balance_state in {"a_concentrated", "guarded_rebalance"}:
            status = "WARN"
            message = summary or "A/B cluster mix still needs guarded rebalance review"
        else:
            status = "PASS"
            message = summary or "strategy cluster balance remains informational only"

        return self._item(
            item_id="strategy_cluster_balance",
            title="Strategy Cluster Balance",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.strategy_cluster_balance_available",
                    "validation_report.strategy_cluster_balance_summary.mode",
                    "validation_report.strategy_cluster_balance_summary.balance_state",
                    "validation_report.strategy_cluster_balance_summary.balance_bias",
                    "validation_report.strategy_cluster_balance_summary.family_mix",
                ],
            },
            evidence={
                "available": available,
                "mode": str(summary_payload.get("mode", "A_ONLY") or "A_ONLY"),
                "balance_state": balance_state,
                "balance_bias": str(summary_payload.get("balance_bias", "preserve_a_anchor") or "preserve_a_anchor"),
                "headline_cluster": str(summary_payload.get("headline_cluster", "a_reversal") or "a_reversal"),
                "target_mix": str(summary_payload.get("target_mix", "a_anchor_only") or "a_anchor_only"),
                "family_mix": [dict(item) for item in list(summary_payload.get("family_mix") or [])[:3]],
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "source_summary": dict(summary_payload.get("source_summary") or {}),
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _b_continuation_edge_validation_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("b_continuation_edge_validation_summary") or {})
        available = bool(
            report.get("b_continuation_edge_validation_available", False) or summary_payload.get("available", False)
        )
        edge_state = str(summary_payload.get("edge_state", "insufficient_sample") or "insufficient_sample").lower()
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "B continuation edge validation unavailable; keep diversification-evidence review informational only"
        elif edge_state in {"fragile_edge", "insufficient_edge"}:
            status = "WARN"
            message = summary or "B diversification confidence needs review because post-cost or overlap evidence is weakening"
        elif edge_state == "validated_edge":
            status = "PASS"
            message = summary or "B continuation remains supported by current post-cost and diversification evidence"
        else:
            status = "PASS"
            message = summary or "B continuation evidence is still thin; gather more post-cost observations first"

        return self._item(
            item_id="b_continuation_edge_validation",
            title="B Continuation Edge Validation",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.b_continuation_edge_validation_available",
                    "validation_report.b_continuation_edge_validation_summary.edge_state",
                    "validation_report.b_continuation_edge_validation_summary.validation_bias",
                    "validation_report.b_continuation_edge_validation_summary.reason_codes",
                ],
            },
            evidence={
                "available": available,
                "raw_family": str(
                    summary_payload.get("raw_family", "trend_continuation") or "trend_continuation"
                ),
                "strategy_cluster": str(
                    summary_payload.get("strategy_cluster", "b_continuation") or "b_continuation"
                ),
                "edge_state": edge_state,
                "validation_bias": str(
                    summary_payload.get("validation_bias", "gather_more_evidence") or "gather_more_evidence"
                ),
                "sample_state": str(summary_payload.get("sample_state", "thin_sample") or "thin_sample"),
                "family_post_cost_rate": float(summary_payload.get("family_post_cost_rate", 0.0) or 0.0),
                "diversification_state": str(
                    summary_payload.get("diversification_state", "unclear_diversification")
                    or "unclear_diversification"
                ),
                "drawdown_contribution_state": str(
                    summary_payload.get("drawdown_contribution_state", "drawdown_unknown") or "drawdown_unknown"
                ),
                "a_b_correlation_proxy": str(
                    summary_payload.get("a_b_correlation_proxy", "unknown_proxy") or "unknown_proxy"
                ),
                "weakest_axis": str(summary_payload.get("weakest_axis", "") or ""),
                "weakest_bucket": str(summary_payload.get("weakest_bucket", "") or ""),
                "confidence": str(summary_payload.get("confidence", "low") or "low"),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "source_summary": dict(summary_payload.get("source_summary") or {}),
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _a_strategy_post_cost_edge_validation_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("a_strategy_post_cost_edge_validation_summary") or {})
        available = bool(
            report.get("a_strategy_post_cost_edge_validation_available", False)
            or summary_payload.get("available", False)
        )
        edge_state = str(summary_payload.get("edge_state", "insufficient_sample") or "insufficient_sample").lower()
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "A-strategy post-cost edge validation unavailable; keep anchor-evidence review informational only"
        elif edge_state in {"fragile_edge", "insufficient_edge"}:
            status = "WARN"
            message = summary or "A anchor confidence needs review because post-cost edge support is weakening"
        elif edge_state == "validated_edge":
            status = "PASS"
            message = summary or "A anchor remains supported by current post-cost evidence"
        else:
            status = "PASS"
            message = summary or "A anchor evidence is still thin; gather more post-cost observations first"

        return self._item(
            item_id="a_strategy_post_cost_edge_validation",
            title="A Strategy Post-Cost Edge Validation",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.a_strategy_post_cost_edge_validation_available",
                    "validation_report.a_strategy_post_cost_edge_validation_summary.edge_state",
                    "validation_report.a_strategy_post_cost_edge_validation_summary.validation_bias",
                    "validation_report.a_strategy_post_cost_edge_validation_summary.reason_codes",
                ],
            },
            evidence={
                "available": available,
                "family": str(summary_payload.get("family", "sweep_reversal") or "sweep_reversal"),
                "edge_state": edge_state,
                "validation_bias": str(
                    summary_payload.get("validation_bias", "gather_more_evidence") or "gather_more_evidence"
                ),
                "sample_state": str(summary_payload.get("sample_state", "thin") or "thin"),
                "family_post_cost_rate": float(summary_payload.get("family_post_cost_rate", 0.0) or 0.0),
                "weakest_axis": str(summary_payload.get("weakest_axis", "") or ""),
                "weakest_bucket": str(summary_payload.get("weakest_bucket", "") or ""),
                "confidence": str(summary_payload.get("confidence", "low") or "low"),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "source_summary": dict(summary_payload.get("source_summary") or {}),
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _forward_stress_regime_validation_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("forward_stress_regime_validation_summary") or {})
        available = bool(
            report.get("forward_stress_regime_validation_available", False)
            or summary_payload.get("available", False)
        )
        validation_state = str(
            summary_payload.get("validation_state", "insufficient_evidence") or "insufficient_evidence"
        ).lower()
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "forward/stress/regime validation unavailable; keep generalization review informational only"
        elif validation_state in {"fragile_generalization", "insufficient_generalization"}:
            status = "WARN"
            message = summary or "generalization confidence needs review because forward, stress, or split evidence is weakening"
        elif validation_state == "validated_generalization":
            status = "PASS"
            message = summary or "current validation posture still has usable forward/stress generalization support"
        else:
            status = "PASS"
            message = summary or "validation evidence is still thin; gather more forward and stress coverage first"

        return self._item(
            item_id="forward_stress_regime_validation",
            title="Forward Stress Regime Validation",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.forward_stress_regime_validation_available",
                    "validation_report.forward_stress_regime_validation_summary.validation_state",
                    "validation_report.forward_stress_regime_validation_summary.validation_bias",
                    "validation_report.forward_stress_regime_validation_summary.reason_codes",
                ],
            },
            evidence={
                "available": available,
                "validation_state": validation_state,
                "validation_bias": str(
                    summary_payload.get("validation_bias", "gather_more_validation_evidence")
                    or "gather_more_validation_evidence"
                ),
                "coverage_state": str(summary_payload.get("coverage_state", "thin_validation") or "thin_validation"),
                "walk_forward_state": str(
                    summary_payload.get("walk_forward_state", "insufficient_walk_forward")
                    or "insufficient_walk_forward"
                ),
                "stress_state": str(summary_payload.get("stress_state", "insufficient_stress") or "insufficient_stress"),
                "replay_state": str(summary_payload.get("replay_state", "replay_lineage_thin") or "replay_lineage_thin"),
                "regime_split_state": str(
                    summary_payload.get("regime_split_state", "insufficient_regime_split")
                    or "insufficient_regime_split"
                ),
                "session_split_state": str(
                    summary_payload.get("session_split_state", "insufficient_session_split")
                    or "insufficient_session_split"
                ),
                "preferred_live_mode": str(summary_payload.get("preferred_live_mode", "A_ONLY") or "A_ONLY"),
                "worst_scenario": str(summary_payload.get("worst_scenario", "stressed_cost") or "stressed_cost"),
                "best_regime": str(summary_payload.get("best_regime", "") or ""),
                "best_session": str(summary_payload.get("best_session", "") or ""),
                "weakest_axis": str(summary_payload.get("weakest_axis", "") or ""),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "source_summary": dict(summary_payload.get("source_summary") or {}),
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _kill_condition_automation_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("kill_condition_automation_summary") or {})
        available = bool(
            report.get("kill_condition_automation_available", False) or summary_payload.get("available", False)
        )
        kill_condition_state = str(summary_payload.get("kill_condition_state", "observe_only") or "observe_only").lower()
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "Kill-condition automation unavailable; keep stop review informational only"
        elif kill_condition_state in {"throttle_review", "close_only_review", "kill_switch_review"}:
            status = "WARN"
            message = summary or "Current evidence justifies stop-review escalation before trusting live execution"
        else:
            status = "PASS"
            message = summary or "Current stop evidence remains observational only"

        return self._item(
            item_id="kill_condition_automation",
            title="Kill Condition Automation",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.kill_condition_automation_available",
                    "validation_report.kill_condition_automation_summary.kill_condition_state",
                    "validation_report.kill_condition_automation_summary.automation_bias",
                    "validation_report.kill_condition_automation_summary.reason_codes",
                ],
            },
            evidence={
                "available": available,
                "kill_condition_state": kill_condition_state,
                "automation_bias": str(summary_payload.get("automation_bias", "observe_only") or "observe_only"),
                "write_scope": str(summary_payload.get("write_scope", "none") or "none"),
                "trigger_axis": str(summary_payload.get("trigger_axis", "") or ""),
                "active_manual_override": bool(summary_payload.get("active_manual_override", False)),
                "manual_override_reason": str(summary_payload.get("manual_override_reason", "") or ""),
                "arm_required": bool(summary_payload.get("arm_required", False)),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "trigger_reason_codes": list(summary_payload.get("trigger_reason_codes") or []),
                "source_summary": dict(summary_payload.get("source_summary") or {}),
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _promotion_lifecycle_history_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("promotion_lifecycle_history_summary") or {})
        available = bool(
            report.get("promotion_lifecycle_history_available", False) or summary_payload.get("available", False)
        )
        history_state = str(summary_payload.get("history_state", "history_unavailable") or "history_unavailable").lower()
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "promotion lifecycle history unavailable; keep durable lineage review informational only"
        elif history_state == "history_attention_required":
            status = "WARN"
            message = summary or "durable promotion history still points to active remediation or blocked clearance"
        else:
            status = "PASS"
            message = summary or "promotion lifecycle history remains compare-only lineage context"

        return self._item(
            item_id="promotion_lifecycle_history",
            title="Promotion Lifecycle History",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.promotion_lifecycle_history_available",
                    "validation_report.promotion_lifecycle_history_summary.family",
                    "validation_report.promotion_lifecycle_history_summary.history_state",
                    "validation_report.promotion_lifecycle_history_summary.latest_event_type",
                    "validation_report.promotion_lifecycle_history_summary.reason_codes",
                ],
            },
            evidence={
                "available": available,
                "family": str(summary_payload.get("family", "") or ""),
                "history_state": history_state,
                "latest_event_type": str(summary_payload.get("latest_event_type", "unknown") or "unknown"),
                "latest_event_ts": str(summary_payload.get("latest_event_ts", "") or ""),
                "event_count_30d": int(summary_payload.get("event_count_30d", 0) or 0),
                "recent_transitions": list(summary_payload.get("recent_transitions") or []),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "source_summary": dict(summary_payload.get("source_summary") or {}),
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _research_promotion_operating_loop_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("research_promotion_operating_loop_summary") or {})
        available = bool(
            report.get("research_promotion_operating_loop_available", False) or summary_payload.get("available", False)
        )
        loop_state = str(summary_payload.get("loop_state", "research_backlog") or "research_backlog").lower()
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "research promotion operating loop unavailable; keep research-to-promotion linkage informational only"
        elif loop_state in {"research_backlog", "shadow_test_ready"}:
            status = "WARN"
            message = summary or "research case still needs shadow-test follow-through before probation review"
        else:
            status = "PASS"
            message = summary or "research promotion operating loop remains compare-only while promotion path is reviewed"

        return self._item(
            item_id="research_promotion_operating_loop",
            title="Research Promotion Operating Loop",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.research_promotion_operating_loop_available",
                    "validation_report.research_promotion_operating_loop_summary.family",
                    "validation_report.research_promotion_operating_loop_summary.loop_state",
                    "validation_report.research_promotion_operating_loop_summary.target_stage",
                    "validation_report.research_promotion_operating_loop_summary.reason_codes",
                ],
            },
            evidence={
                "available": available,
                "family": str(summary_payload.get("family", "") or ""),
                "loop_state": loop_state,
                "loop_bias": str(summary_payload.get("loop_bias", "observe_only") or "observe_only"),
                "target_stage": str(summary_payload.get("target_stage", "research") or "research"),
                "recommended_action": str(summary_payload.get("recommended_action", "") or ""),
                "shadow_experiment_id": str(summary_payload.get("shadow_experiment_id", "") or ""),
                "watchlist_ready": bool(summary_payload.get("watchlist_ready", False)),
                "confidence": str(summary_payload.get("confidence", "low") or "low"),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "source_summary": dict(summary_payload.get("source_summary") or {}),
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _positive_evidence_expansion_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("positive_evidence_expansion_summary") or {})
        available = bool(
            report.get("positive_evidence_expansion_available", False) or summary_payload.get("available", False)
        )
        state = str(summary_payload.get("state", "not_ready") or "not_ready").lower()
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "positive evidence expansion unavailable; keep expansion review informational only"
        elif state == "not_ready":
            status = "WARN"
            message = summary or "family is not ready for controlled expansion review while guardrails remain active"
        elif state == "expandable":
            status = "PASS"
            message = summary or "family can be reviewed as a controlled expansion candidate, not an auto-expand"
        else:
            status = "PASS"
            message = summary or "family shows positive evidence but still supports a hold posture before expansion"

        return self._item(
            item_id="positive_evidence_expansion",
            title="Positive Evidence Expansion",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.positive_evidence_expansion_available",
                    "validation_report.positive_evidence_expansion_summary.state",
                    "validation_report.positive_evidence_expansion_summary.expansion_bias",
                    "validation_report.positive_evidence_expansion_summary.reason_codes",
                ],
            },
            evidence={
                "available": available,
                "family": str(summary_payload.get("family", "") or ""),
                "state": state,
                "expansion_bias": str(summary_payload.get("expansion_bias", "hold") or "hold"),
                "confidence": str(summary_payload.get("confidence", "low") or "low"),
                "reason_codes": list(summary_payload.get("reason_codes") or []),
                "source_summary": dict(summary_payload.get("source_summary") or {}),
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _outcome_bucket_granularity_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        report = dict(validation_payload.get("validation_report") or {})
        summary_payload = dict(report.get("outcome_bucket_granularity_summary") or {})
        available = bool(
            report.get("outcome_bucket_granularity_available", False) or summary_payload.get("available", False)
        )
        top_axis = str(summary_payload.get("top_condition_axis", "") or "")
        top_bucket = dict(summary_payload.get("top_condition_bucket") or {})
        confidence = str(summary_payload.get("confidence", "low") or "low")
        summary = str(summary_payload.get("summary", "") or "").strip()

        if not available:
            status = "PASS"
            message = "outcome bucket granularity unavailable; keep condition split review informational only"
        elif top_axis in {"cost_condition", "liquidity_condition"} and confidence in {"medium", "high"}:
            status = "WARN"
            message = summary or "condition split suggests cost or liquidity drag in a specific bucket; review it before changing thresholds"
        else:
            status = "PASS"
            message = summary or "condition split is informational only"

        return self._item(
            item_id="outcome_bucket_granularity",
            title="Outcome Bucket Granularity",
            category="execution",
            status=status,
            summary=message,
            blocking=False,
            source={
                "endpoint": "/validation/report",
                "fields": [
                    "validation_report.outcome_bucket_granularity_available",
                    "validation_report.outcome_bucket_granularity_summary.family_focus",
                    "validation_report.outcome_bucket_granularity_summary.top_condition_axis",
                    "validation_report.outcome_bucket_granularity_summary.top_condition_bucket",
                    "validation_report.outcome_bucket_granularity_summary.condition_axes",
                ],
            },
            evidence={
                "available": available,
                "family_focus": dict(summary_payload.get("family_focus") or {}),
                "top_condition_axis": top_axis,
                "top_condition_bucket": top_bucket,
                "confidence": confidence,
                "condition_axes": [dict(item) for item in list(summary_payload.get("condition_axes") or [])[:3]],
                "advisory_only": bool(summary_payload.get("advisory_only", True)),
            },
        )

    def _pbo_dsr_item(self, *, validation_payload: dict[str, Any]) -> dict[str, Any]:
        pbo_dsr = dict(validation_payload.get("strategy_v2_pbo_dsr_design") or {})
        artifact_store = dict(validation_payload.get("strategy_v2_pbo_dsr_artifact_store") or {})
        pbo_dsr_metrics = dict(validation_payload.get("strategy_v2_pbo_dsr_metrics") or {})
        if not pbo_dsr:
            status = "FAIL"
            blocking = False
            summary = "PBO/DSR design payload missing"
        elif bool(pbo_dsr_metrics.get("metrics_complete")):
            status = "PASS"
            blocking = False
            summary = (
                "PBO/DSR metrics available; "
                f"{(pbo_dsr_metrics.get('deployment_recommendation') or {}).get('decision', 'not_ready')}"
            )
        elif bool(artifact_store.get("artifact_store_ready")):
            status = "PASS"
            blocking = False
            summary = (
                "PBO/DSR design contract frozen; "
                f"artifact store {artifact_store.get('implementation_status', 'unknown')}"
            )
        elif bool(pbo_dsr.get("design_ready")):
            status = "PASS"
            blocking = False
            summary = f"PBO/DSR design contract frozen ({pbo_dsr.get('implementation_status', 'unknown')})"
        else:
            status = "WARN"
            blocking = False
            summary = "PBO/DSR design contract not frozen yet"
        return self._item(
            item_id="pbo_dsr_design",
            title="PBO / DSR Design Contract",
            category="validation",
            status=status,
            summary=summary,
            blocking=blocking,
            source={
                "endpoint": "/validation/report",
                "fields": ["strategy_v2_pbo_dsr_design", "strategy_v2_pbo_dsr_artifact_store", "strategy_v2_pbo_dsr_metrics"],
            },
            evidence={
                "design": pbo_dsr,
                "artifact_store": artifact_store,
                "metrics": pbo_dsr_metrics,
            },
        )

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.operations_checklist_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"operational_checklist_{payload['symbol']}_{payload['strategy_version']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        lines = [
            f"# Operational Checklist: {payload['symbol']}",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- universe: {payload['universe']}",
            f"- strategy_version: {payload['strategy_version']}",
            f"- overall_status: {payload['overall_status']}",
            f"- deployment_go_no_go: {payload['deployment_go_no_go']}",
            f"- deployment_code: {payload['deployment_code']}",
            f"- deployment_message: {payload['deployment_message']}",
            f"- playbook_go_no_go: {payload['playbook_go_no_go']}",
            f"- playbook_code: {payload['playbook_code']}",
            f"- playbook_action: {payload['playbook_action']}",
            f"- playbook_message: {payload['playbook_message']}",
            f"- blocking_failures: {payload['blocking_failures']}",
            f"- warnings: {payload['warnings']}",
            f"- manual_actions: {payload['manual_actions']}",
            "",
            "## Approval Strip",
            (
                f"- approve={payload['approval_strip_summary']['approve_value']} | "
                f"align={payload['approval_strip_summary']['align_value']} | "
                f"act={payload['approval_strip_summary']['act_value']} | "
                f"priority={payload['approval_strip_summary']['act_priority_level']}"
            ),
            f"- approve_reason: {payload['approval_strip_summary']['approve_reason']}",
            f"- align_reason: {payload['approval_strip_summary']['align_reason']}",
            f"- act_reason: {payload['approval_strip_summary']['act_reason']}",
            "",
            "## Checks",
        ]
        for item in payload["checks"]:
            lines.append(
                f"- [{item['status']}] {item['title']} ({item['category']}) | blocking={item['blocking']} | {item['summary']}"
            )
        lines.extend(
            [
                "",
                "## Notes",
                "- This checklist aggregates current API/report evidence for live-readiness review.",
                "- Blocking items with status FAIL or MANUAL should be cleared before live trading.",
                "- WARN items are non-blocking by default, but require operator review.",
                "",
            ]
        )
        file_path.write_text("\n".join(lines), encoding="utf-8")
        return str(file_path)

    def generate(
        self,
        *,
        symbol: str,
        universe: str,
        strategy_version: str,
        ready: Any,
        validation_payload: dict[str, Any],
        alert_metrics: dict[str, Any],
        outbox_status: dict[str, Any],
        strategy_metrics: dict[str, Any],
        portfolio_budget: dict[str, Any],
        execution_quality: dict[str, Any],
        alert_test_lookback_hours: int = 24,
        write_report: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        checks = [
            self._health_item(ready=ready),
            self._validation_item(validation_payload=validation_payload),
            self._validation_alert_item(validation_payload=validation_payload),
            self._alert_slo_item(alert_metrics=alert_metrics),
            self._alert_test_item(lookback_hours=alert_test_lookback_hours),
            self._retry_queue_item(alert_metrics=alert_metrics),
            self._outbox_item(outbox_status=outbox_status),
            self._risk_gate_item(strategy_metrics=strategy_metrics),
            self._session_guidance_item(strategy_metrics=strategy_metrics, portfolio_budget=portfolio_budget, now=now),
            self._portfolio_item(portfolio_budget=portfolio_budget),
            self._execution_quality_item(execution_quality=execution_quality),
            self._execution_friction_measurement_item(validation_payload=validation_payload),
            self._forward_stress_regime_validation_item(validation_payload=validation_payload),
            self._kill_condition_automation_item(validation_payload=validation_payload),
            self._execution_degradation_advisory_item(validation_payload=validation_payload),
            self._operator_action_priority_item(
                validation_payload=validation_payload,
                symbol=symbol,
                universe=universe,
            ),
            self._outcome_control_trace_item(validation_payload=validation_payload),
            self._money_funnel_item(validation_payload=validation_payload),
            self._outcome_attribution_item(validation_payload=validation_payload),
            self._edge_experiment_review_item(validation_payload=validation_payload),
            self._edge_evolution_rule_item(validation_payload=validation_payload),
            self._rollout_recommendation_item(validation_payload=validation_payload),
            self._multi_strategy_ab_item(validation_payload=validation_payload),
            self._b_continuation_activation_item(validation_payload=validation_payload),
            self._b_continuation_edge_validation_item(validation_payload=validation_payload),
            self._strategy_cluster_balance_item(validation_payload=validation_payload),
            self._a_strategy_post_cost_edge_validation_item(validation_payload=validation_payload),
            self._strategy_lifecycle_item(validation_payload=validation_payload),
            self._promotion_governance_item(validation_payload=validation_payload),
            self._promotion_review_queue_item(validation_payload=validation_payload),
            self._promotion_remediation_queue_item(validation_payload=validation_payload),
            self._promotion_clearance_tracker_item(validation_payload=validation_payload),
            self._promotion_reopen_queue_item(validation_payload=validation_payload),
            self._promotion_decision_brief_item(validation_payload=validation_payload),
            self._auto_promotion_rollout_execution_item(validation_payload=validation_payload),
            self._promotion_lifecycle_history_item(validation_payload=validation_payload),
            self._research_promotion_operating_loop_item(validation_payload=validation_payload),
            self._positive_evidence_expansion_item(validation_payload=validation_payload),
            self._outcome_bucket_granularity_item(validation_payload=validation_payload),
            self._opportunity_capture_item(validation_payload=validation_payload),
            self._capital_allocator_item(validation_payload=validation_payload),
            self._pbo_dsr_item(validation_payload=validation_payload),
        ]
        blocking_failures = sum(1 for item in checks if bool(item["blocking"]) and item["status"] == "FAIL")
        manual_actions = sum(1 for item in checks if bool(item["blocking"]) and item["status"] == "MANUAL")
        warnings = sum(1 for item in checks if item["status"] == "WARN")
        if blocking_failures > 0 or manual_actions > 0:
            overall_status = "FAIL"
        elif warnings > 0:
            overall_status = "WARN"
        else:
            overall_status = "PASS"
        deployment_language = self._deployment_language(
            validation_payload=validation_payload,
            overall_status=overall_status,
            blocking_failures=blocking_failures,
            manual_actions=manual_actions,
            warnings=warnings,
        )
        approval_strip_summary = self._approval_strip_summary(
            validation_payload=validation_payload,
            deployment_language=deployment_language,
            overall_status=overall_status,
            blocking_failures=blocking_failures,
            manual_actions=manual_actions,
            warnings=warnings,
        )
        payload: dict[str, Any] = {
            "generated_at": now.isoformat(),
            "symbol": symbol,
            "universe": universe,
            "strategy_version": strategy_version,
            "overall_status": overall_status,
            "deployment_go_no_go": deployment_language["deployment_go_no_go"],
            "deployment_code": deployment_language["deployment_code"],
            "deployment_message": deployment_language["deployment_message"],
            "playbook_go_no_go": deployment_language["playbook_go_no_go"],
            "playbook_code": deployment_language["playbook_code"],
            "playbook_action": deployment_language["playbook_action"],
            "playbook_message": deployment_language["playbook_message"],
            "blocking_failures": blocking_failures,
            "warnings": warnings,
            "manual_actions": manual_actions,
            "approval_strip_summary": approval_strip_summary,
            "checks": checks,
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload
