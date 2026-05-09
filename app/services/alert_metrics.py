from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.db.models import AlertSubscription
from app.db.repositories import AlertRepository, AlertRetryQueueRepository
from app.services.deployment_contracts import validation_alert_contract, validation_alert_strip_summary
from app.services.notification_dispatcher import NotificationDispatcher


@dataclass(slots=True)
class DeliveryObservation:
    channel: str
    delivered: bool
    skipped: bool
    failed: bool
    reason: str
    attempts: int
    latency_ms: float | None
    is_leaf: bool


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, "", "None"):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if isfinite(parsed) else default


def _safe_int(value: Any, default: int = 0) -> int:
    if value in (None, "", "None"):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return int(parsed) if isfinite(parsed) else default


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    index = (len(ordered) - 1) * ratio
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    weight = index - low
    return float(ordered[low] + (ordered[high] - ordered[low]) * weight)


def _latency_summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"avg": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "avg": float(sum(values) / len(values)),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "max": float(max(values)),
    }


class AlertMetricsService:
    def __init__(
        self,
        *,
        alert_repo: AlertRepository,
        retry_repo: AlertRetryQueueRepository | None = None,
        settings: Settings | None = None,
    ):
        self.alert_repo = alert_repo
        self.retry_repo = retry_repo
        self.settings = settings or get_settings()

    @staticmethod
    def _to_observation(result: dict[str, Any], *, is_leaf: bool) -> DeliveryObservation:
        delivered = bool(result.get("delivered"))
        skipped = bool(result.get("skipped"))
        failed = not delivered and not skipped
        latency_raw = result.get("latency_ms")
        latency_ms = float(latency_raw) if isinstance(latency_raw, (int, float)) else None
        attempts = int(result.get("attempts", 0) or 0)
        return DeliveryObservation(
            channel=str(result.get("channel", "unknown")),
            delivered=delivered,
            skipped=skipped,
            failed=failed,
            reason=str(result.get("reason", "unknown")),
            attempts=attempts,
            latency_ms=latency_ms,
            is_leaf=is_leaf,
        )

    def _flatten_deliveries(self, alerts: list[AlertSubscription]) -> list[DeliveryObservation]:
        observations: list[DeliveryObservation] = []
        for alert in alerts:
            payload = alert.payload or {}
            delivery = payload.get("delivery")
            if not isinstance(delivery, dict):
                continue

            results = delivery.get("results")
            has_child_results = isinstance(results, list) and len(results) > 0
            observations.append(
                self._to_observation(delivery, is_leaf=not (str(delivery.get("channel")) == "system" and has_child_results))
            )
            if not has_child_results:
                continue

            for item in results:
                if isinstance(item, dict):
                    observations.append(self._to_observation(item, is_leaf=True))
        return observations

    def _error_budget(self, *, failed: int, attempted: int) -> dict[str, Any]:
        min_attempts = max(1, _safe_int(self.settings.alert_slo_min_attempts, default=5))
        target_success_rate = _safe_float(self.settings.alert_slo_target_success_rate, default=0.995)
        if attempted < min_attempts:
            return {
                "status": "INSUFFICIENT_DATA",
                "allowed_failures": 0.0,
                "failed": failed,
                "remaining_failures": 0.0,
                "burn_ratio": 0.0,
                "budget_fraction_remaining": 0.0,
            }

        allowed_failures = max(0.0, attempted * (1.0 - target_success_rate))
        remaining = allowed_failures - float(failed)
        if allowed_failures == 0.0:
            burn_ratio = 0.0 if failed == 0 else float(failed)
        else:
            burn_ratio = float(failed / allowed_failures)

        if failed > allowed_failures:
            status = "EXHAUSTED"
        elif failed >= allowed_failures * 0.8:
            status = "WARN"
        else:
            status = "PASS"

        return {
            "status": status,
            "allowed_failures": float(round(allowed_failures, 6)),
            "failed": int(failed),
            "remaining_failures": float(round(remaining, 6)),
            "burn_ratio": float(burn_ratio) if burn_ratio != float("inf") else burn_ratio,
            "budget_fraction_remaining": float(max(0.0, remaining / allowed_failures)) if allowed_failures > 0 else 0.0,
        }

    @staticmethod
    def _age_seconds(*, now: datetime, ts: datetime | None) -> int:
        if ts is None:
            return 0
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return int(max(0.0, (now - ts).total_seconds()))

    def _channel_stats(self, observations: list[DeliveryObservation]) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[DeliveryObservation]] = defaultdict(list)
        for row in observations:
            grouped[row.channel].append(row)

        out: dict[str, dict[str, Any]] = {}
        for channel, rows in sorted(grouped.items()):
            total = len(rows)
            delivered = sum(1 for row in rows if row.delivered)
            skipped = sum(1 for row in rows if row.skipped)
            failed = sum(1 for row in rows if row.failed)
            attempted = delivered + failed
            latency_values = [float(row.latency_ms) for row in rows if row.latency_ms is not None and row.attempts > 0]
            circuit_open = sum(1 for row in rows if row.reason == "circuit_open")
            not_configured = sum(1 for row in rows if row.reason.endswith("_not_configured") or row.reason == "system_no_routes_configured")
            success_rate = float(delivered / attempted) if attempted else 0.0
            failure_rate = float(failed / attempted) if attempted else 0.0
            skipped_rate = float(skipped / total) if total else 0.0
            latency = _latency_summary(latency_values)
            out[channel] = {
                "total": total,
                "attempted": attempted,
                "delivered": delivered,
                "skipped": skipped,
                "failed": failed,
                "success_rate": success_rate,
                "failure_rate": failure_rate,
                "skipped_rate": skipped_rate,
                "avg_attempts": float(sum(row.attempts for row in rows) / total) if total else 0.0,
                "latency_ms": latency,
                "circuit_open_count": circuit_open,
                "not_configured_count": not_configured,
                "slo": self._evaluate_slo(success_rate=success_rate, p95_latency_ms=latency["p95"], attempted=attempted),
                "error_budget": self._error_budget(failed=failed, attempted=attempted),
            }
        return out

    def _evaluate_slo(self, *, success_rate: float, p95_latency_ms: float, attempted: int) -> dict[str, Any]:
        min_attempts = max(1, _safe_int(self.settings.alert_slo_min_attempts, default=5))
        target_success_rate = _safe_float(self.settings.alert_slo_target_success_rate, default=0.995)
        warn_success_rate = _safe_float(self.settings.alert_slo_warn_success_rate, default=0.97)
        target_p95_latency_ms = _safe_float(self.settings.alert_slo_max_p95_latency_ms, default=3000.0)
        warn_p95_latency_ms = _safe_float(self.settings.alert_slo_warn_p95_latency_ms, default=5000.0)
        if attempted < min_attempts:
            return {
                "status": "INSUFFICIENT_DATA",
                "met": False,
                "reason": "insufficient_attempts",
                "target_success_rate": target_success_rate,
                "warn_success_rate": warn_success_rate,
                "target_p95_latency_ms": target_p95_latency_ms,
                "warn_p95_latency_ms": warn_p95_latency_ms,
            }

        pass_success = success_rate >= target_success_rate
        pass_latency = p95_latency_ms <= target_p95_latency_ms
        warn_success = success_rate >= warn_success_rate
        warn_latency = p95_latency_ms <= warn_p95_latency_ms

        if pass_success and pass_latency:
            status = "PASS"
            met = True
            reason = "within_target"
        elif warn_success and warn_latency:
            status = "WARN"
            met = False
            reason = "outside_target_within_warn_band"
        else:
            status = "FAIL"
            met = False
            reason = "outside_warn_band"

        return {
            "status": status,
            "met": met,
            "reason": reason,
            "target_success_rate": target_success_rate,
            "warn_success_rate": warn_success_rate,
            "target_p95_latency_ms": target_p95_latency_ms,
            "warn_p95_latency_ms": warn_p95_latency_ms,
        }

    @staticmethod
    def _latest_validation_alert_summary(alerts: list[AlertSubscription]) -> dict[str, Any]:
        for alert in alerts:
            if str(alert.type) not in {"validation_warn", "validation_fail"}:
                continue
            payload = dict(alert.payload or {})
            delivery = dict(payload.get("delivery") or {})
            delivered = bool(delivery.get("delivered"))
            skipped = bool(delivery.get("skipped"))
            failed = not delivered and not skipped
            contract = validation_alert_contract(payload)
            approval_strip_summary = validation_alert_strip_summary(payload)
            return {
                "available": True,
                "alert_id": alert.alert_id,
                "symbol": alert.symbol,
                "channel": alert.channel,
                "type": alert.type,
                "triggered_ts": alert.triggered_ts.isoformat(),
                "status": str(payload.get("status", "") or "").upper(),
                "approval_strip_summary": approval_strip_summary,
                **contract,
                "delivery_reason": str(delivery.get("reason", "") or ""),
                "delivery_channel": str(delivery.get("channel", "") or alert.channel),
                "delivered": delivered,
                "skipped": skipped,
                "failed": failed,
                "retry_queued": int(payload.get("retry_queued", 0) or 0),
            }
        return {
            "available": False,
            "alert_id": None,
            "symbol": None,
            "channel": None,
            "type": None,
            "triggered_ts": None,
            "status": "",
            "approval_strip_summary": {},
            "deployment_go_no_go": "",
            "deployment_code": "",
            "deployment_message": "",
            "approval_playbook_go_no_go": "",
            "approval_playbook_code": "",
            "approval_playbook_action": "",
            "approval_playbook_message": "",
            "approval_topline_summary_line": "",
            "delivery_reason": "",
            "delivery_channel": "",
            "delivered": False,
            "skipped": False,
            "failed": False,
            "retry_queued": 0,
        }

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.alert_metrics_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"alert_metrics_{now.strftime('%Y%m%dT%H%M%SZ')}.md"

        lines = [
            "# Alert Metrics Report",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- lookback_days: {payload['days']}",
            f"- alerts_total: {payload['alerts_total']}",
            f"- alerts_with_delivery: {payload['alerts_with_delivery']}",
            f"- overall_scope: {payload['overall']['scope']}",
            "",
            "## Overall",
            f"- delivered/attempted/failed/skipped: {payload['overall']['delivered']}/{payload['overall']['attempted']}/{payload['overall']['failed']}/{payload['overall']['skipped']}",
            f"- success_rate: {payload['overall']['success_rate']:.4f}",
            f"- failure_rate: {payload['overall']['failure_rate']:.4f}",
            f"- p95_latency_ms: {payload['overall']['latency_ms']['p95']:.2f}",
            f"- slo_status: {payload['overall']['slo']['status']}",
            f"- error_budget_status: {payload['overall']['error_budget']['status']}",
            f"- error_budget_remaining_failures: {payload['overall']['error_budget']['remaining_failures']:.4f}",
            "",
            "## By Channel",
        ]
        for channel, stats in sorted(payload["channel_metrics"].items()):
            lines.append(
                f"- {channel}: success_rate={stats['success_rate']:.4f}, failure_rate={stats['failure_rate']:.4f}, "
                f"attempted={stats['attempted']}, skipped={stats['skipped']}, p95_latency_ms={stats['latency_ms']['p95']:.2f}, "
                f"slo={stats['slo']['status']}, error_budget={stats['error_budget']['status']}, "
                f"circuit_open_count={stats['circuit_open_count']}"
            )

        lines.extend(["", "## Circuit Snapshot"])
        for channel, snapshot in sorted(payload["circuit_state"].items()):
            lines.append(
                f"- {channel}: tracked_targets={snapshot['tracked_targets']}, open_targets={snapshot['open_targets']}, max_failures={snapshot['max_failures']}"
            )

        retry_queue = payload["retry_queue"]
        lines.extend(
            [
                "",
                "## Retry Queue",
                f"- queued/delivered/dead_letter: {retry_queue['counts'].get('queued', 0)}/{retry_queue['counts'].get('delivered', 0)}/{retry_queue['counts'].get('dead_letter', 0)}",
                f"- backlog_age_seconds: {retry_queue['backlog_age_seconds']}",
                f"- dead_letter_oldest_age_seconds: {retry_queue['dead_letter_oldest_age_seconds']}",
                f"- next_retry_in_seconds: {retry_queue['next_retry_in_seconds']}",
            ]
        )

        latest_validation_alert = dict(payload.get("latest_validation_alert") or {})
        latest_alert_strip = dict(latest_validation_alert.get("approval_strip_summary") or {})
        lines.extend(
            [
                "",
                "## Latest Validation Alert",
                f"- available: {latest_validation_alert.get('available', False)}",
                (
                    "- approval_strip: "
                    f"approve={latest_alert_strip.get('approve_value', '')} | "
                    f"align={latest_alert_strip.get('align_value', '')} | "
                    f"act={latest_alert_strip.get('act_value', '')} | "
                    f"priority={latest_alert_strip.get('act_priority_level', '')}"
                ),
                f"- deployment_go_no_go: {latest_validation_alert.get('deployment_go_no_go', '')}",
                f"- deployment_code: {latest_validation_alert.get('deployment_code', '')}",
                f"- deployment_message: {latest_validation_alert.get('deployment_message', '')}",
                f"- approval_playbook_go_no_go: {latest_validation_alert.get('approval_playbook_go_no_go', '')}",
                f"- approval_playbook_code: {latest_validation_alert.get('approval_playbook_code', '')}",
                f"- approval_playbook_action: {latest_validation_alert.get('approval_playbook_action', '')}",
                f"- approval_topline_summary_line: {latest_validation_alert.get('approval_topline_summary_line', '')}",
            ]
        )

        lines.append("")
        file_path.write_text("\n".join(lines), encoding="utf-8")
        return str(file_path)

    def generate(self, *, days: int, write_report: bool = True) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        lookback_days = max(1, int(days))
        alerts = [
            alert
            for alert in self.alert_repo.list_recent(days=lookback_days)
            if not bool((alert.payload or {}).get("subscription_active"))
        ]
        observations = self._flatten_deliveries(alerts)
        leaf_observations = [row for row in observations if row.is_leaf]

        channel_metrics = self._channel_stats(observations)
        total = len(leaf_observations)
        delivered = sum(1 for row in leaf_observations if row.delivered)
        skipped = sum(1 for row in leaf_observations if row.skipped)
        failed = sum(1 for row in leaf_observations if row.failed)
        attempted = delivered + failed
        latencies = [float(row.latency_ms) for row in leaf_observations if row.latency_ms is not None and row.attempts > 0]
        latency_summary = _latency_summary(latencies)
        overall_stats = {
            "scope": "leaf_channels",
            "total": total,
            "attempted": attempted,
            "delivered": delivered,
            "skipped": skipped,
            "failed": failed,
            "success_rate": float(delivered / attempted) if attempted else 0.0,
            "failure_rate": float(failed / attempted) if attempted else 0.0,
            "skipped_rate": float(skipped / total) if total else 0.0,
            "latency_ms": latency_summary,
            "slo": self._evaluate_slo(
                success_rate=float(delivered / attempted) if attempted else 0.0,
                p95_latency_ms=latency_summary["p95"],
                attempted=attempted,
            ),
            "error_budget": self._error_budget(failed=failed, attempted=attempted),
        }

        retry_queue = {
            "counts": {},
            "backlog_age_seconds": 0,
            "dead_letter_oldest_age_seconds": 0,
            "next_retry_in_seconds": 0,
            "retry_policy": {},
        }
        if self.retry_repo is not None:
            now = datetime.now(timezone.utc)
            oldest_queued = self.retry_repo.oldest_queued()
            oldest_dead_letter = self.retry_repo.oldest_dead_letter()
            next_retry_in_seconds = 0
            if oldest_queued is not None:
                retry_ts = oldest_queued.next_retry_ts
                if retry_ts.tzinfo is None:
                    retry_ts = retry_ts.replace(tzinfo=timezone.utc)
                next_retry_in_seconds = int(max(0.0, (retry_ts - now).total_seconds()))
            retry_queue = {
                "counts": self.retry_repo.status_counts(),
                "backlog_age_seconds": self._age_seconds(
                    now=now,
                    ts=oldest_queued.created_ts if oldest_queued is not None else None,
                ),
                "dead_letter_oldest_age_seconds": self._age_seconds(
                    now=now,
                    ts=oldest_dead_letter.dead_letter_ts if oldest_dead_letter is not None else None,
                ),
                "next_retry_in_seconds": next_retry_in_seconds,
                "retry_policy": {
                    "max_attempts": _safe_int(self.settings.alert_retry_queue_max_attempts, default=4),
                    "retry_backoff_seconds": _safe_float(self.settings.alert_retry_queue_backoff_seconds, default=30.0),
                    "retry_jitter_seconds": _safe_float(self.settings.alert_retry_queue_jitter_seconds),
                },
            }

        payload: dict[str, Any] = {
            "generated_at": now.isoformat(),
            "days": lookback_days,
            "alerts_total": len(alerts),
            "alerts_with_delivery": sum(1 for alert in alerts if isinstance((alert.payload or {}).get("delivery"), dict)),
            "overall": overall_stats,
            "channel_metrics": channel_metrics,
            "circuit_state": NotificationDispatcher.circuit_snapshot(),
            "latest_validation_alert": self._latest_validation_alert_summary(alerts),
            "retry_queue": retry_queue,
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload
