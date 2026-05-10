from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any


_BLOCKER_ACTIONS = {
    "validation_do_not_deploy": "Keep live blocked; run validation/report and fix the validation primary cause before probation.",
    "adjusted_score_non_positive": "Keep live blocked; inspect score penalties and candidate quality before any allowlist expansion.",
    "no_runtime_candidate": "Keep live blocked; wait for a fresh runtime setup or re-check candidate/runtime contract alignment.",
    "thesis_active_cap_reached": "Wait for active thesis capacity to clear; do not increase live scope just to force entry.",
    "rollout_session_not_allowed": "Wait for an allowed rollout session; no strategy change needed.",
    "duplicate_active_thesis": "Do not create another entry; existing thesis/cooldown already covers this candidate.",
    "symbol_not_live_enabled": "Keep shadow-only until validation explicitly approves this symbol for MICRO_LIVE.",
    "symbol_not_live_enabled_for_auto_route": "Keep shadow-only until validation explicitly approves this symbol for MICRO_LIVE.",
    "submit_ready": "Submit path should be watched closely; if no live submission follows, investigate routing/submission.",
}


_STATE_RANK = {
    "LIVE_SUBMITTED": 0,
    "SUBMIT_READY_GAP": 1,
    "GATE_BLOCKED": 2,
    "COOLDOWN_WAIT": 3,
    "SHADOW_SIGNAL_ONLY": 4,
    "NO_FRESH_LIVE_CANDIDATE": 5,
    "OBSERVE_RUNTIME": 6,
    "NO_RECENT_RUNTIME_EVIDENCE": 7,
}


_NON_GATE_BLOCKERS = {
    "intent_blocked",
    "live_submission_seen",
    "submit_ready",
    "submit_ready_without_live_submission",
    "recent_intent_cooldown_active",
    "duplicate_active_thesis",
    "thesis_active_cap_reached",
    "rollout_session_not_allowed",
    "symbol_not_live_enabled",
    "symbol_not_live_enabled_for_auto_route",
    "no_fresh_live_candidate",
    "runtime_observed_no_promotion_block",
    "no_recent_runtime_evidence",
}


_COOLDOWN_BLOCKERS = {
    "duplicate_active_thesis",
    "thesis_active_cap_reached",
    "rollout_session_not_allowed",
}


_SHADOW_BLOCKERS = {
    "symbol_not_live_enabled",
    "symbol_not_live_enabled_for_auto_route",
}


_GATE_BLOCKER_PRIORITY = {
    "validation_do_not_deploy": 0,
    "no_runtime_candidate": 10,
    "adjusted_score_non_positive": 20,
    "intent_blocked": 90,
}


class LiveCandidatePromotionReadinessService:
    """Compare-only candidate readiness summary for live promotion decisions.

    This service does not approve, size, rank, or submit orders. It compresses
    existing runtime audits and order-intent decisions into an operator-facing
    state machine so blocked candidates are not treated as ambiguous no-order
    windows.
    """

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _symbol(value: Any) -> str:
        return str(value or "").strip().upper() or "UNKNOWN"

    @staticmethod
    def _family(value: Any) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _action_for(reason: str) -> str:
        normalized = str(reason or "").strip()
        return _BLOCKER_ACTIONS.get(normalized, f"Inspect blocker '{normalized or 'unknown'}' before promotion.")

    @classmethod
    def _candidate_key(cls, symbol: str, family: str) -> str:
        normalized_family = str(family or "").strip().lower() or "unknown"
        return f"{cls._symbol(symbol)}::{normalized_family}"

    @classmethod
    def _primary_gate_blocker(cls, counts: Counter[str]) -> str:
        candidates = [
            (reason, count)
            for reason, count in counts.items()
            if int(count or 0) > 0 and reason and reason not in _NON_GATE_BLOCKERS
        ]
        if not candidates:
            return "intent_blocked"
        reason, _count = min(
            candidates,
            key=lambda item: (
                _GATE_BLOCKER_PRIORITY.get(str(item[0]), 100),
                -int(item[1] or 0),
                str(item[0]),
            ),
        )
        return str(reason)

    @staticmethod
    def _secondary_blockers(counts: Counter[str], primary: str) -> dict[str, int]:
        return {
            str(reason): int(count)
            for reason, count in counts.most_common(5)
            if reason and reason != primary and int(count or 0) > 0
        }

    @staticmethod
    def _timestamp(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            dt = value
        else:
            text = str(value or "").strip()
            if not text:
                return None
            try:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @classmethod
    def _timestamp_iso(cls, value: Any) -> str:
        dt = cls._timestamp(value)
        if dt is None:
            return ""
        return dt.isoformat().replace("+00:00", "Z")

    @classmethod
    def _timestamp_epoch(cls, value: Any) -> float:
        dt = cls._timestamp(value)
        return dt.timestamp() if dt is not None else 0.0

    @classmethod
    def _remember_latest(cls, candidate: dict[str, Any], field: str, value: Any) -> None:
        dt = cls._timestamp(value)
        if dt is None:
            return
        current = candidate.get(f"_{field}_dt")
        if not isinstance(current, datetime) or dt > current:
            candidate[f"_{field}_dt"] = dt
            candidate[field] = dt.isoformat().replace("+00:00", "Z")

    @classmethod
    def _stage(
        cls,
        *,
        audit_status_counts: Counter[str],
        intent_reason_counts: Counter[str],
        micro_live_intent_count: int,
        submit_ready_count: int,
        live_submission_count: int,
    ) -> tuple[str, str, str, str]:
        if live_submission_count > 0:
            return (
                "LIVE_SUBMITTED",
                "ok",
                "live_submission_seen",
                "Monitor lifecycle, fills, and reconciliation; no promotion action needed.",
            )
        if submit_ready_count > 0 and live_submission_count <= 0:
            return (
                "SUBMIT_READY_GAP",
                "fail",
                "submit_ready_without_live_submission",
                cls._action_for("submit_ready"),
            )
        has_gate_blocker = any(
            reason
            for reason, count in intent_reason_counts.items()
            if count > 0 and reason and reason not in _NON_GATE_BLOCKERS
        )
        if has_gate_blocker:
            reason = cls._primary_gate_blocker(intent_reason_counts)
            return ("GATE_BLOCKED", "blocked", reason, cls._action_for(reason))
        if any(intent_reason_counts.get(reason, 0) > 0 for reason in _COOLDOWN_BLOCKERS) or audit_status_counts.get(
            "recent_intent_cooldown_active", 0
        ) > 0:
            reason = next(
                (
                    blocker
                    for blocker in ("duplicate_active_thesis", "thesis_active_cap_reached", "rollout_session_not_allowed")
                    if intent_reason_counts.get(blocker, 0) > 0
                ),
                "recent_intent_cooldown_active",
            )
            return (
                "COOLDOWN_WAIT",
                "wait",
                reason,
                cls._action_for(reason if reason != "recent_intent_cooldown_active" else "duplicate_active_thesis"),
            )
        if any(intent_reason_counts.get(reason, 0) > 0 for reason in _SHADOW_BLOCKERS) or audit_status_counts.get(
            "symbol_not_live_enabled_for_auto_route", 0
        ) > 0:
            reason = next(
                (
                    blocker
                    for blocker in ("symbol_not_live_enabled_for_auto_route", "symbol_not_live_enabled")
                    if intent_reason_counts.get(blocker, 0) > 0
                ),
                "symbol_not_live_enabled_for_auto_route",
            )
            return (
                "SHADOW_SIGNAL_ONLY",
                "watch",
                reason,
                cls._action_for(reason),
            )
        if audit_status_counts.get("intent_blocked", 0) > 0:
            reason = "intent_blocked"
            return ("GATE_BLOCKED", "blocked", reason, cls._action_for(reason))
        if (
            audit_status_counts.get("no_live_route_candidate_plan", 0) > 0
            or audit_status_counts.get("no_session_impulse_retest_plan", 0) > 0
            or audit_status_counts.get("no_fresh_candidates", 0) > 0
            or micro_live_intent_count <= 0
        ):
            return (
                "NO_FRESH_LIVE_CANDIDATE",
                "wait",
                "no_fresh_live_candidate",
                "No structural change needed; wait for a fresh live-eligible runtime candidate.",
            )
        if audit_status_counts:
            return (
                "OBSERVE_RUNTIME",
                "watch",
                "runtime_observed_no_promotion_block",
                "Keep observing; no live authority changes are implied.",
            )
        return (
            "NO_RECENT_RUNTIME_EVIDENCE",
            "watch",
            "no_recent_runtime_evidence",
            "Confirm the candidate is tracked by runtime before promotion review.",
        )

    def build(
        self,
        *,
        hours: int,
        audit_rows: list[dict[str, Any]],
        intent_rows: list[dict[str, Any]],
        submission_rows: list[dict[str, Any]],
        limit: int = 20,
    ) -> dict[str, Any]:
        candidates: dict[str, dict[str, Any]] = {}

        def ensure(symbol: str, family: str = "") -> dict[str, Any]:
            key = self._candidate_key(symbol, family)
            if key not in candidates:
                candidates[key] = {
                    "symbol": self._symbol(symbol),
                    "strategy_family": self._family(family) or "unknown",
                    "audit_status_counts": Counter(),
                    "audit_phase_counts": Counter(),
                    "intent_reason_counts": Counter(),
                    "intent_approval_counts": Counter(),
                    "intent_decision_counts": Counter(),
                    "micro_live_intent_count": 0,
                    "submit_ready_count": 0,
                    "live_submission_count": 0,
                    "submission_state_counts": Counter(),
                    "latest_audit_at": "",
                    "latest_intent_at": "",
                    "latest_submission_at": "",
                    "latest_evidence_at": "",
                }
            return candidates[key]

        for row in audit_rows:
            symbol = self._symbol(row.get("symbol"))
            family = self._family(row.get("strategy_family"))
            candidate = ensure(symbol, family)
            count = self._safe_int(row.get("count"))
            status = str(row.get("status") or "unknown")
            phase = str(row.get("phase") or "unknown")
            candidate["audit_status_counts"][status] += count
            candidate["audit_phase_counts"][phase] += count
            self._remember_latest(candidate, "latest_audit_at", row.get("latest_observed_ts") or row.get("latest_ts"))

        for row in intent_rows:
            symbol = self._symbol(row.get("symbol"))
            family = self._family(row.get("strategy_family"))
            candidate = ensure(symbol, family)
            count = self._safe_int(row.get("count"))
            reason = str(row.get("decision_reason_code") or "")
            approval = str(row.get("approval_state") or "unknown")
            decision = str(row.get("submit_decision") or "unknown")
            mode = str(row.get("execution_mode") or "").upper()
            if reason:
                candidate["intent_reason_counts"][reason] += count
            candidate["intent_approval_counts"][approval] += count
            candidate["intent_decision_counts"][decision] += count
            self._remember_latest(candidate, "latest_intent_at", row.get("latest_created_at") or row.get("latest_ts"))
            if mode == "MICRO_LIVE":
                candidate["micro_live_intent_count"] += count
                if reason == "submit_ready":
                    candidate["submit_ready_count"] += count

        for row in submission_rows:
            symbol = self._symbol(row.get("symbol"))
            family = self._family(row.get("strategy_family"))
            candidate = ensure(symbol, family)
            count = self._safe_int(row.get("count"))
            state = str(row.get("state") or "unknown")
            candidate["live_submission_count"] += count
            candidate["submission_state_counts"][state] += count
            self._remember_latest(
                candidate,
                "latest_submission_at",
                row.get("latest_submitted_at") or row.get("latest_ts"),
            )

        rows: list[dict[str, Any]] = []
        state_counts: Counter[str] = Counter()
        severity_counts: Counter[str] = Counter()
        blocker_counts: Counter[str] = Counter()
        action_counts: Counter[str] = Counter()
        intent_reason_evidence_counts: Counter[str] = Counter()
        audit_status_evidence_counts: Counter[str] = Counter()
        latest_evidence_at = ""
        symbols_by_state: dict[str, list[str]] = defaultdict(list)
        for candidate in candidates.values():
            for field in ("latest_audit_at", "latest_intent_at", "latest_submission_at"):
                self._remember_latest(candidate, "latest_evidence_at", candidate.get(field))
            if self._timestamp_epoch(candidate.get("latest_evidence_at")) > self._timestamp_epoch(latest_evidence_at):
                latest_evidence_at = str(candidate.get("latest_evidence_at") or "")
            state, severity, primary_blocker, next_action = self._stage(
                audit_status_counts=candidate["audit_status_counts"],
                intent_reason_counts=candidate["intent_reason_counts"],
                micro_live_intent_count=int(candidate["micro_live_intent_count"]),
                submit_ready_count=int(candidate["submit_ready_count"]),
                live_submission_count=int(candidate["live_submission_count"]),
            )
            state_counts[state] += 1
            severity_counts[severity] += 1
            blocker_counts[primary_blocker] += 1
            action_counts[next_action] += 1
            intent_reason_evidence_counts.update(candidate["intent_reason_counts"])
            audit_status_evidence_counts.update(candidate["audit_status_counts"])
            symbol = str(candidate["symbol"])
            if symbol not in symbols_by_state[state]:
                symbols_by_state[state].append(symbol)
            rows.append(
                {
                    "symbol": symbol,
                    "strategy_family": str(candidate["strategy_family"]),
                    "promotion_state": state,
                    "severity": severity,
                    "primary_blocker": primary_blocker,
                    "secondary_blockers": self._secondary_blockers(candidate["intent_reason_counts"], primary_blocker),
                    "next_action": next_action,
                    "micro_live_intent_count": int(candidate["micro_live_intent_count"]),
                    "submit_ready_count": int(candidate["submit_ready_count"]),
                    "live_submission_count": int(candidate["live_submission_count"]),
                    "latest_audit_at": str(candidate.get("latest_audit_at") or ""),
                    "latest_intent_at": str(candidate.get("latest_intent_at") or ""),
                    "latest_submission_at": str(candidate.get("latest_submission_at") or ""),
                    "latest_evidence_at": str(candidate.get("latest_evidence_at") or ""),
                    "audit_status_counts": dict(candidate["audit_status_counts"].most_common()),
                    "intent_reason_counts": dict(candidate["intent_reason_counts"].most_common()),
                    "submission_state_counts": dict(candidate["submission_state_counts"].most_common()),
                }
            )

        rows.sort(
            key=lambda item: (
                _STATE_RANK.get(str(item["promotion_state"]), 99),
                -int(item["micro_live_intent_count"]),
                -self._timestamp_epoch(item.get("latest_evidence_at")),
                str(item["symbol"]),
                str(item["strategy_family"]),
            )
        )
        headline = self._headline(state_counts=state_counts, blocker_counts=blocker_counts)
        return {
            "available": bool(rows),
            "advisory_only": True,
            "authority": "compare_only_no_live_authority_change",
            "hours": max(1, int(hours)),
            "latest_evidence_at": latest_evidence_at,
            "headline_state": headline["state"],
            "headline_reason": headline["reason"],
            "headline_action": headline["action"],
            "candidate_count": len(rows),
            "state_counts": dict(state_counts.most_common()),
            "severity_counts": dict(severity_counts.most_common()),
            "top_blockers": dict(blocker_counts.most_common(8)),
            "top_intent_reasons": dict(intent_reason_evidence_counts.most_common(8)),
            "top_audit_statuses": dict(audit_status_evidence_counts.most_common(8)),
            "top_actions": dict(action_counts.most_common(5)),
            "symbols_by_state": {key: sorted(value) for key, value in sorted(symbols_by_state.items())},
            "candidates": rows[: max(1, int(limit))],
        }

    def _headline(self, *, state_counts: Counter[str], blocker_counts: Counter[str]) -> dict[str, str]:
        if state_counts.get("SUBMIT_READY_GAP", 0) > 0:
            return {
                "state": "FAIL",
                "reason": "submit_ready_gap_present",
                "action": self._action_for("submit_ready"),
            }
        if state_counts.get("GATE_BLOCKED", 0) > 0:
            blocker = self._primary_gate_blocker(blocker_counts)
            return {
                "state": "BLOCKED",
                "reason": blocker,
                "action": self._action_for(blocker),
            }
        if state_counts.get("SHADOW_SIGNAL_ONLY", 0) > 0:
            return {
                "state": "WATCH",
                "reason": "shadow_signal_only",
                "action": self._action_for("symbol_not_live_enabled_for_auto_route"),
            }
        if state_counts:
            return {
                "state": "WAIT",
                "reason": "no_promotable_live_candidate",
                "action": "Keep the current validation gates; no live expansion is implied.",
            }
        return {
            "state": "WATCH",
            "reason": "no_recent_candidate_evidence",
            "action": "Confirm runtime tracking and candidate sources before promotion review.",
        }
