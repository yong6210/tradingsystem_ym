from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import Any

from app.db.models import PromotionLifecycleHistory
from app.db.repositories import PromotionLifecycleHistoryRepository


_ACTIVE_REMEDIATION_ACTIONS = {
    "execution_remediation",
    "policy_remediation",
    "condition_remediation",
}


class PromotionLifecycleHistoryService:
    @staticmethod
    def _dict(payload: dict[str, Any] | None) -> dict[str, Any]:
        return dict(payload or {})

    @staticmethod
    def _rows(payload: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
        return [dict(item) for item in list(dict(payload or {}).get(key) or [])]

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        out: list[str] = []
        for value in values:
            if value and value not in out:
                out.append(value)
        return out

    def _select_family(
        self,
        *,
        promotion_decision_brief: dict[str, Any],
        promotion_reopen_queue: dict[str, Any],
        promotion_clearance_tracker: dict[str, Any],
        promotion_governance: dict[str, Any],
        strategy_lifecycle: dict[str, Any],
    ) -> str:
        candidates = [
            str(promotion_decision_brief.get("family") or "").strip().lower(),
            str(promotion_reopen_queue.get("headline_family") or "").strip().lower(),
            str(promotion_clearance_tracker.get("family") or "").strip().lower(),
            str(promotion_governance.get("family") or "").strip().lower(),
            str(strategy_lifecycle.get("family") or "").strip().lower(),
        ]
        for family in candidates:
            if family and family != "unknown":
                return family
        return ""

    @staticmethod
    def _snapshot_hash(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _build_event(
        self,
        *,
        family: str,
        event_type: str,
        event_ts: datetime,
        state_from: str,
        state_to: str,
        bias: str,
        source_key: str,
        source_summary: dict[str, Any],
        reason_codes: list[str],
    ) -> dict[str, Any]:
        day_bucket = event_ts.astimezone(timezone.utc).strftime("%Y-%m-%d")
        fingerprint = {
            "family": family,
            "event_type": event_type,
            "state_from": state_from,
            "state_to": state_to,
            "bias": bias,
            "reason_codes": list(reason_codes),
            "event_day_bucket": day_bucket,
        }
        return {
            "history_id": f"promotion_history_{uuid4().hex}",
            "family": family,
            "event_type": event_type,
            "event_ts": event_ts,
            "state_from": state_from,
            "state_to": state_to,
            "bias": bias,
            "source_key": source_key,
            "source_summary": dict(source_summary or {}),
            "reason_codes": list(reason_codes),
            "snapshot_hash": self._snapshot_hash(fingerprint),
        }

    def _event_candidates(
        self,
        *,
        family: str,
        now: datetime,
        strategy_lifecycle: dict[str, Any],
        promotion_governance: dict[str, Any],
        promotion_review_queue: dict[str, Any],
        promotion_remediation_queue: dict[str, Any],
        promotion_clearance_tracker: dict[str, Any],
        promotion_reopen_queue: dict[str, Any],
        promotion_decision_brief: dict[str, Any],
        auto_promotion_rollout_execution: dict[str, Any],
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []

        lifecycle_state = str(strategy_lifecycle.get("state") or "").lower()
        previous_state = str(strategy_lifecycle.get("previous_state") or "").lower()
        transition_bias = str(strategy_lifecycle.get("transition_bias") or "").lower()
        if previous_state and lifecycle_state and previous_state != lifecycle_state:
            events.append(
                self._build_event(
                    family=family,
                    event_type="lifecycle_transition",
                    event_ts=now + timedelta(microseconds=1),
                    state_from=previous_state,
                    state_to=lifecycle_state,
                    bias=transition_bias or "observe",
                    source_key="strategy_lifecycle",
                    source_summary=dict(strategy_lifecycle.get("source_summary") or {}),
                    reason_codes=self._dedupe(
                        ["history_event:lifecycle_transition", *list(strategy_lifecycle.get("reason_codes") or [])]
                    ),
                )
            )

        review_action = str(promotion_review_queue.get("top_review_action") or "").lower()
        if review_action in {"promote_review", "defer_review"}:
            events.append(
                self._build_event(
                    family=family,
                    event_type="promotion_review_queued",
                    event_ts=now + timedelta(microseconds=2),
                    state_from=str(promotion_governance.get("state") or "hold").lower(),
                    state_to=review_action,
                    bias=str(promotion_governance.get("promotion_bias") or "hold").lower(),
                    source_key="promotion_review_queue",
                    source_summary=dict(promotion_review_queue.get("source_summary") or {}),
                    reason_codes=self._dedupe(
                        ["history_event:promotion_review_queued", *list(promotion_review_queue.get("reason_codes") or [])]
                    ),
                )
            )

        remediation_action = str(promotion_remediation_queue.get("top_remediation_action") or "").lower()
        if remediation_action in _ACTIVE_REMEDIATION_ACTIONS:
            events.append(
                self._build_event(
                    family=family,
                    event_type="remediation_started",
                    event_ts=now + timedelta(microseconds=3),
                    state_from=str(promotion_governance.get("state") or "hold").lower(),
                    state_to=remediation_action,
                    bias=str(promotion_clearance_tracker.get("clearance_bias") or "continue_remediation").lower(),
                    source_key="promotion_remediation_queue",
                    source_summary=dict(promotion_remediation_queue.get("source_summary") or {}),
                    reason_codes=self._dedupe(
                        ["history_event:remediation_started", *list(promotion_remediation_queue.get("reason_codes") or [])]
                    ),
                )
            )

        clearance_state = str(promotion_clearance_tracker.get("clearance_state") or "").lower()
        if clearance_state in {"blocked", "partial_clear", "clearance_ready"}:
            events.append(
                self._build_event(
                    family=family,
                    event_type="clearance_progressed",
                    event_ts=now + timedelta(microseconds=4),
                    state_from=str(promotion_governance.get("state") or "hold").lower(),
                    state_to=clearance_state,
                    bias=str(promotion_clearance_tracker.get("clearance_bias") or "observe").lower(),
                    source_key="promotion_clearance_tracker",
                    source_summary=dict(promotion_clearance_tracker.get("source_summary") or {}),
                    reason_codes=self._dedupe(
                        ["history_event:clearance_progressed", *list(promotion_clearance_tracker.get("reason_codes") or [])]
                    ),
                )
            )

        reopen_action = str(promotion_reopen_queue.get("top_reopen_action") or "").lower()
        if reopen_action == "reopen_review":
            events.append(
                self._build_event(
                    family=family,
                    event_type="promotion_reopen_ready",
                    event_ts=now + timedelta(microseconds=5),
                    state_from=clearance_state or "unknown",
                    state_to=reopen_action,
                    bias=str(promotion_decision_brief.get("decision_bias") or "consider_reopen_review").lower(),
                    source_key="promotion_reopen_queue",
                    source_summary=dict(promotion_reopen_queue.get("source_summary") or {}),
                    reason_codes=self._dedupe(
                        ["history_event:promotion_reopen_ready", *list(promotion_reopen_queue.get("reason_codes") or [])]
                    ),
                )
            )

        execution_stage = str(auto_promotion_rollout_execution.get("execution_stage") or "").lower()
        if execution_stage and execution_stage != "advisory_only":
            events.append(
                self._build_event(
                    family=family,
                    event_type="auto_execution_stage_recorded",
                    event_ts=now + timedelta(microseconds=6),
                    state_from=str(promotion_decision_brief.get("brief_state") or "observe_case").lower(),
                    state_to=execution_stage,
                    bias=str(auto_promotion_rollout_execution.get("execution_bias") or "keep_manual").lower(),
                    source_key="auto_promotion_rollout_execution",
                    source_summary=dict(auto_promotion_rollout_execution.get("source_summary") or {}),
                    reason_codes=self._dedupe(
                        [
                            "history_event:auto_execution_stage_recorded",
                            *list(auto_promotion_rollout_execution.get("reason_codes") or []),
                        ]
                    ),
                )
            )

        return events

    @staticmethod
    def _row_to_dict(row: PromotionLifecycleHistory) -> dict[str, Any]:
        return {
            "history_id": row.history_id,
            "family": row.family,
            "event_type": row.event_type,
            "event_ts": row.event_ts,
            "state_from": row.state_from or "",
            "state_to": row.state_to or "",
            "bias": row.bias or "",
            "source_key": row.source_key,
            "source_summary": dict(row.source_summary or {}),
            "reason_codes": list(row.reason_codes or []),
            "snapshot_hash": row.snapshot_hash,
            "created_at": row.created_at,
        }

    @staticmethod
    def _recent_transition(row: dict[str, Any]) -> str:
        state_from = str(row.get("state_from") or "").strip()
        state_to = str(row.get("state_to") or "").strip()
        if state_from and state_to:
            return f"{state_from} -> {state_to}"
        return str(row.get("event_type") or "unknown")

    @staticmethod
    def _history_state(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "history_unavailable"
        latest = dict(rows[0])
        latest_event_type = str(latest.get("event_type") or "").lower()
        latest_state_to = str(latest.get("state_to") or "").lower()
        if latest_event_type == "remediation_started" or latest_state_to in {"blocked", "partial_clear"}:
            return "history_attention_required"
        if latest_event_type in {"promotion_reopen_ready", "auto_execution_stage_recorded"}:
            return "history_stable"
        return "history_accumulating"

    @staticmethod
    def _summary(*, family: str, history_state: str, latest_event_type: str) -> str:
        if history_state == "history_stable":
            return (
                f"family={family} now has durable promotion history showing a recent {latest_event_type} transition."
            )
        if history_state == "history_attention_required":
            return (
                f"family={family} history still points to active remediation or blocked clearance before promotion can progress."
            )
        if history_state == "history_accumulating":
            return f"family={family} is accumulating promotion lineage, but durable history is still early."
        return f"family={family} has no durable promotion lifecycle history yet."

    def generate(
        self,
        *,
        repo: PromotionLifecycleHistoryRepository | None,
        persist: bool,
        strategy_lifecycle: dict[str, Any] | None,
        promotion_governance: dict[str, Any] | None,
        promotion_review_queue: dict[str, Any] | None,
        promotion_remediation_queue: dict[str, Any] | None,
        promotion_clearance_tracker: dict[str, Any] | None,
        promotion_reopen_queue: dict[str, Any] | None,
        promotion_decision_brief: dict[str, Any] | None,
        auto_promotion_rollout_execution: dict[str, Any] | None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        lifecycle_payload = self._dict(strategy_lifecycle)
        governance_payload = self._dict(promotion_governance)
        review_payload = self._dict(promotion_review_queue)
        remediation_payload = self._dict(promotion_remediation_queue)
        clearance_payload = self._dict(promotion_clearance_tracker)
        reopen_payload = self._dict(promotion_reopen_queue)
        decision_payload = self._dict(promotion_decision_brief)
        auto_execution_payload = self._dict(auto_promotion_rollout_execution)

        if not any(
            [
                lifecycle_payload,
                governance_payload,
                review_payload,
                remediation_payload,
                clearance_payload,
                reopen_payload,
                decision_payload,
                auto_execution_payload,
            ]
        ):
            return {
                "available": False,
                "advisory_only": True,
                "summary": "promotion lifecycle history unavailable",
            }

        family = self._select_family(
            promotion_decision_brief=decision_payload,
            promotion_reopen_queue=reopen_payload,
            promotion_clearance_tracker=clearance_payload,
            promotion_governance=governance_payload,
            strategy_lifecycle=lifecycle_payload,
        )
        if not family:
            return {
                "available": False,
                "advisory_only": True,
                "summary": "promotion lifecycle history unavailable",
            }

        event_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
        event_candidates = self._event_candidates(
            family=family,
            now=event_now,
            strategy_lifecycle=lifecycle_payload,
            promotion_governance=governance_payload,
            promotion_review_queue=review_payload,
            promotion_remediation_queue=remediation_payload,
            promotion_clearance_tracker=clearance_payload,
            promotion_reopen_queue=reopen_payload,
            promotion_decision_brief=decision_payload,
            auto_promotion_rollout_execution=auto_execution_payload,
        )

        if persist and repo is not None:
            for event in event_candidates:
                repo.add_if_absent(
                    PromotionLifecycleHistory(
                        history_id=str(event["history_id"]),
                        family=str(event["family"]),
                        event_type=str(event["event_type"]),
                        event_ts=event["event_ts"],
                        state_from=str(event.get("state_from") or "") or None,
                        state_to=str(event.get("state_to") or "") or None,
                        bias=str(event.get("bias") or "") or None,
                        source_key=str(event["source_key"]),
                        source_summary=dict(event.get("source_summary") or {}),
                        reason_codes=list(event.get("reason_codes") or []),
                        snapshot_hash=str(event["snapshot_hash"]),
                    )
                )

        rows: list[dict[str, Any]] = []
        if repo is not None:
            rows = [self._row_to_dict(row) for row in repo.list_recent(family=family, days=30, limit=20)]

        if not rows and event_candidates:
            rows = [dict(event_candidates[-1])]

        if not rows:
            return {
                "available": False,
                "advisory_only": True,
                "family": family,
                "history_state": "history_unavailable",
                "summary": f"family={family} has no durable promotion lifecycle history yet.",
            }

        latest = dict(rows[0])
        history_state = self._history_state(rows)
        latest_event_type = str(latest.get("event_type") or "unknown")
        latest_event_ts = latest.get("event_ts")
        if isinstance(latest_event_ts, datetime):
            latest_event_ts_value = latest_event_ts.astimezone(timezone.utc).isoformat()
        else:
            latest_event_ts_value = str(latest_event_ts or "")
        reason_codes = self._dedupe(
            [f"history:{history_state}", f"latest_event:{latest_event_type}", *list(latest.get("reason_codes") or [])]
        )

        return {
            "available": True,
            "advisory_only": True,
            "family": family,
            "history_state": history_state,
            "latest_event_type": latest_event_type,
            "latest_event_ts": latest_event_ts_value,
            "event_count_30d": len(rows),
            "recent_transitions": [self._recent_transition(row) for row in rows[:3]],
            "summary": self._summary(
                family=family,
                history_state=history_state,
                latest_event_type=latest_event_type,
            ),
            "reason_codes": reason_codes,
            "source_summary": {
                "latest_source_key": str(latest.get("source_key") or "unknown"),
                "latest_bias": str(latest.get("bias") or "unknown"),
                "latest_state_from": str(latest.get("state_from") or "unknown"),
                "latest_state_to": str(latest.get("state_to") or "unknown"),
            },
        }
