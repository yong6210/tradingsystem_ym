from __future__ import annotations

from typing import Any


_SAFETY_REASON_PREFIXES = (
    "reconciliation_",
    "kill_switch",
    "close_only",
    "operating_lock",
    "shock",
    "transition",
    "risk_lock",
    "session_lock",
    "validation_fail",
    "user_stream_stale",
)

_STRUCTURAL_REASONS = {
    "total_cap_reached",
    "directional_cap_reached",
    "cluster_cap_reached",
    "thesis_duplicate_blocked",
    "thesis_active_cap_reached",
    "thesis_cluster_cap_zero_risk",
}

_ROLLOUT_REASONS = {
    "mode_shadow_only",
    "mode_daily_trade_limit_reached",
    "mode_total_risk_cap_reached",
    "live_disabled_family",
    "execution_mode_cap_exceeded",
    "micro_live_session_not_allowed",
    "live_limit_only_entry_required",
    "live_entry_model_not_allowed",
    "micro_live_strategy_hour_not_allowed",
    "micro_live_strategy_time_bucket_not_allowed",
    "micro_live_plan_id_blocklisted",
    "live_family_cluster_window_cap_reached",
    "live_family_loss_cooldown_active",
}

_QUALITY_REASONS = {
    "risk_budget_below_min",
    "adjusted_score_non_positive",
    "invalid_candidate",
    "sizing_zero_risk",
}

_GATE_KEYS = ("quality", "rollout", "structural", "safety", "unknown")
_BOTTLENECK_STAGE_ORDER = {
    "runtime_to_submit": 0,
    "submit_to_fill": 1,
    "fill_to_close": 2,
}


class OpportunityCaptureService:
    @staticmethod
    def _dict(payload: dict[str, Any] | None) -> dict[str, Any]:
        return dict(payload or {})

    @staticmethod
    def _rows(payload: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
        return [dict(item) for item in list(dict(payload or {}).get(key) or [])]

    @staticmethod
    def _round(value: float) -> float:
        return round(float(value), 4)

    @classmethod
    def _rate(cls, numerator: int | float, denominator: int | float) -> float:
        if float(denominator or 0.0) <= 0.0:
            return 0.0
        return cls._round(float(numerator or 0.0) / float(denominator or 0.0))

    @classmethod
    def _per_day(cls, count: int | float, days: int) -> float:
        return cls._rate(count, max(int(days), 1))

    @staticmethod
    def _gate_group_for_reason(reason: str | None) -> str:
        normalized = str(reason or "").strip().lower()
        if not normalized:
            return "unknown"
        if normalized.startswith(_SAFETY_REASON_PREFIXES):
            return "safety"
        if normalized in _STRUCTURAL_REASONS:
            return "structural"
        if normalized in _ROLLOUT_REASONS:
            return "rollout"
        if normalized in _QUALITY_REASONS:
            return "quality"
        return "unknown"

    @classmethod
    def _normalize_gate_counts(cls, counts: dict[str, Any] | None) -> dict[str, int]:
        normalized = {key: 0 for key in _GATE_KEYS}
        for key, value in dict(counts or {}).items():
            gate = str(key or "unknown").strip().lower()
            if gate not in normalized:
                gate = "unknown"
            normalized[gate] += int(value or 0)
        return normalized

    @classmethod
    def _gate_counts_from_reasons(cls, reason_counts: dict[str, Any] | None) -> dict[str, int]:
        grouped = {key: 0 for key in _GATE_KEYS}
        for reason, value in dict(reason_counts or {}).items():
            grouped[cls._gate_group_for_reason(str(reason or ""))] += int(value or 0)
        return grouped

    @classmethod
    def _blocked_mix(
        cls,
        *,
        score_to_outcome_funnel: dict[str, Any] | None,
        portfolio_budget: dict[str, Any] | None,
    ) -> dict[str, int]:
        snapshot = dict(dict(score_to_outcome_funnel or {}).get("snapshot_selection") or {})
        gate_counts = cls._normalize_gate_counts(snapshot.get("blocked_gate_group_counts"))
        if sum(gate_counts.values()) > 0:
            return gate_counts
        reason_counts = dict(snapshot.get("blocked_reason_counts") or {})
        if not reason_counts:
            reason_counts = dict(dict(portfolio_budget or {}).get("blocked_reason_counts") or {})
        return cls._gate_counts_from_reasons(reason_counts)

    @staticmethod
    def _maturity_bucket(history: dict[str, Any]) -> str:
        submitted = int(history.get("submitted", 0) or 0)
        closed = int(history.get("closed", 0) or 0)
        if submitted < 5 or closed < 3:
            return "thin_activity"
        if submitted >= 10 and closed >= 10:
            return "mature_activity"
        return "usable_activity"

    @classmethod
    def _submit_rate_from_runtime(cls, row: dict[str, Any]) -> float:
        return cls._rate(int(row.get("submitted", 0) or 0), int(row.get("runtime_candidates", 0) or 0))

    @classmethod
    def _family_focus_score(cls, row: dict[str, Any]) -> float:
        runtime_candidates = int(row.get("runtime_candidates", 0) or 0)
        runtime_to_submit_gap = 1.0 - cls._submit_rate_from_runtime(row)
        fill_gap = 1.0 - float(row.get("fill_rate_from_submitted", 0.0) or 0.0)
        close_gap = 1.0 - float(row.get("close_rate_from_filled", 0.0) or 0.0)
        return (runtime_candidates * 100.0) + (runtime_to_submit_gap * 10.0) + (fill_gap * 5.0) + (close_gap * 3.0)

    @classmethod
    def _family_focus(cls, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        normalized_rows = [dict(row) for row in rows if dict(row)]
        if not normalized_rows:
            return None
        selected = max(
            normalized_rows,
            key=lambda item: (
                cls._family_focus_score(item),
                int(item.get("runtime_candidates", 0) or 0),
                int(item.get("submitted", 0) or 0),
                int(item.get("closed", 0) or 0),
                str(item.get("key") or ""),
            ),
        )
        return {
            "key": str(selected.get("key") or "unknown"),
            "runtime_candidates": int(selected.get("runtime_candidates", 0) or 0),
            "accepted_candidates": int(selected.get("accepted_candidates", 0) or 0),
            "submitted": int(selected.get("submitted", 0) or 0),
            "filled": int(selected.get("filled", 0) or 0),
            "closed": int(selected.get("closed", 0) or 0),
            "accept_rate": float(selected.get("accept_rate", 0.0) or 0.0),
            "submit_rate_from_runtime": cls._submit_rate_from_runtime(selected),
            "fill_rate_from_submitted": float(selected.get("fill_rate_from_submitted", 0.0) or 0.0),
        }

    @classmethod
    def _modifier_state(cls, row: dict[str, Any]) -> str:
        runtime_candidates = int(row.get("runtime_candidates", 0) or 0)
        submitted = int(row.get("submitted", 0) or 0)
        submit_rate = cls._submit_rate_from_runtime(row)
        fill_rate = float(row.get("fill_rate_from_submitted", 0.0) or 0.0)
        if runtime_candidates == 0 and submitted == 0:
            return "unavailable"
        if runtime_candidates >= 3 and (submit_rate < 0.2 or fill_rate < 0.5):
            return "negative"
        if runtime_candidates >= 3 and submit_rate >= 0.5 and fill_rate >= 0.7:
            return "positive"
        return "neutral"

    @classmethod
    def _modifier(cls, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        normalized_rows = [dict(row) for row in rows if dict(row)]
        if not normalized_rows:
            return None

        candidates = [
            {
                "key": str(row.get("key") or "unknown"),
                "state": cls._modifier_state(row),
                "runtime_candidates": int(row.get("runtime_candidates", 0) or 0),
                "submitted": int(row.get("submitted", 0) or 0),
                "closed": int(row.get("closed", 0) or 0),
            }
            for row in normalized_rows
        ]
        for state in ("negative", "positive", "neutral"):
            state_rows = [row for row in candidates if row["state"] == state]
            if state_rows:
                selected = max(
                    state_rows,
                    key=lambda item: (
                        item["runtime_candidates"],
                        item["submitted"],
                        item["closed"],
                        item["key"],
                    ),
                )
                return {"key": selected["key"], "state": selected["state"]}
        return {"key": "unknown", "state": "unavailable"}

    @staticmethod
    def _dominant_gate_reason(blocked_mix: dict[str, int]) -> str:
        if sum(int(value or 0) for value in dict(blocked_mix or {}).values()) <= 0:
            return "selection_shortfall"
        if blocked_mix.get("quality", 0) >= max(
            blocked_mix.get("rollout", 0),
            blocked_mix.get("structural", 0),
            blocked_mix.get("safety", 0),
            blocked_mix.get("unknown", 0),
        ):
            return "quality_blocking"
        if blocked_mix.get("rollout", 0) >= max(
            blocked_mix.get("structural", 0),
            blocked_mix.get("safety", 0),
            blocked_mix.get("unknown", 0),
        ):
            return "rollout_blocking"
        if (blocked_mix.get("structural", 0) + blocked_mix.get("safety", 0)) > 0:
            return "structural_blocking"
        return "selection_shortfall"

    @classmethod
    def _dominant_bottleneck(
        cls,
        *,
        capture_gap: dict[str, float],
        blocked_mix: dict[str, int],
        execution_quality: dict[str, Any] | None,
        maturity: str,
        history: dict[str, Any],
    ) -> dict[str, Any]:
        submitted = int(history.get("submitted", 0) or 0)
        closed = int(history.get("closed", 0) or 0)
        if maturity == "thin_activity" and (submitted == 0 or closed == 0):
            return {"stage": "runtime_to_submit", "reason": "thin_activity_window"}

        stage = max(
            ("runtime_to_submit", "submit_to_fill", "fill_to_close"),
            key=lambda item: (
                float(capture_gap.get(f"{item}_gap", 0.0) or 0.0),
                -_BOTTLENECK_STAGE_ORDER[item],
            ),
        )

        if stage == "runtime_to_submit":
            return {"stage": stage, "reason": cls._dominant_gate_reason(blocked_mix)}

        if stage == "submit_to_fill":
            eq = dict(execution_quality or {})
            fill_rate = float(eq.get("fill_rate", 0.0) or 0.0)
            fill_events_total = int(eq.get("fill_events_total", 0) or 0)
            if fill_rate < 0.8 or fill_events_total >= 5:
                return {"stage": stage, "reason": "execution_fill_shortfall"}
            return {"stage": stage, "reason": "submission_to_fill_dropoff"}

        close_rate_from_filled = float(history.get("close_rate_from_filled", 0.0) or 0.0)
        if close_rate_from_filled < 0.8:
            return {"stage": stage, "reason": "fill_to_close_dropoff"}
        if maturity == "thin_activity":
            return {"stage": stage, "reason": "thin_activity_window"}
        return {"stage": stage, "reason": "position_resolution_delay"}

    @staticmethod
    def _summary(*, dominant_bottleneck: dict[str, Any], family_focus: dict[str, Any] | None) -> str:
        reason = str(dominant_bottleneck.get("reason") or "")
        stage = str(dominant_bottleneck.get("stage") or "")
        if reason == "thin_activity_window":
            summary = "activity is thin; current window is too small to separate scarcity from degradation"
        elif stage == "runtime_to_submit" and reason in {
            "quality_blocking",
            "rollout_blocking",
            "structural_blocking",
        }:
            summary = "throughput is constrained more by blocking than by fill failure"
        elif stage == "submit_to_fill" and reason == "execution_fill_shortfall":
            summary = "signal flow reaches submission but degrades at fill"
        elif stage == "fill_to_close":
            summary = "fills are occurring, but close throughput lags"
        else:
            summary = "throughput remains below desired capture levels"

        if family_focus and family_focus.get("key"):
            summary = f"{summary}; family focus is {family_focus.get('key')}"
        return summary

    def generate(
        self,
        *,
        score_to_outcome_funnel: dict[str, Any] | None,
        portfolio_budget: dict[str, Any] | None = None,
        execution_quality: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        payload = self._dict(score_to_outcome_funnel)
        if not payload:
            return None

        snapshot = dict(payload.get("snapshot_selection") or {})
        history = dict(payload.get("historical_execution_outcomes") or {})
        decomposition = dict(payload.get("decomposition") or {})
        report_window_days = max(1, int(payload.get("report_window_days", 0) or 0))

        trades_per_day = {
            "submitted": self._per_day(int(history.get("submitted", 0) or 0), report_window_days),
            "filled": self._per_day(int(history.get("filled", 0) or 0), report_window_days),
            "closed": self._per_day(int(history.get("closed", 0) or 0), report_window_days),
        }
        capture_rates = {
            "accept_rate": float(snapshot.get("accept_rate", 0.0) or 0.0),
            "submit_rate_from_runtime": self._rate(
                int(history.get("submitted", 0) or 0),
                int(snapshot.get("runtime_candidates", 0) or 0),
            ),
            "fill_rate_from_submitted": float(history.get("fill_rate_from_submitted", 0.0) or 0.0),
            "close_rate_from_filled": float(history.get("close_rate_from_filled", 0.0) or 0.0),
        }
        capture_gap = {
            "runtime_to_submit_gap": self._round(1.0 - float(capture_rates["submit_rate_from_runtime"])),
            "submit_to_fill_gap": self._round(1.0 - float(capture_rates["fill_rate_from_submitted"])),
            "fill_to_close_gap": self._round(1.0 - float(capture_rates["close_rate_from_filled"])),
        }
        blocked_mix = self._blocked_mix(
            score_to_outcome_funnel=payload,
            portfolio_budget=portfolio_budget,
        )
        maturity = self._maturity_bucket(history)
        family_focus = self._family_focus(self._rows(decomposition, "family"))
        regime_modifier = self._modifier(self._rows(decomposition, "regime"))
        session_modifier = self._modifier(self._rows(decomposition, "session"))
        dominant_bottleneck = self._dominant_bottleneck(
            capture_gap=capture_gap,
            blocked_mix=blocked_mix,
            execution_quality=execution_quality,
            maturity=maturity,
            history=history,
        )

        return {
            "available": bool(payload.get("available", False)),
            "advisory_only": True,
            "summary": self._summary(
                dominant_bottleneck=dominant_bottleneck,
                family_focus=family_focus,
            ),
            "report_window_days": report_window_days,
            "trades_per_day": trades_per_day,
            "capture_rates": capture_rates,
            "capture_gap": capture_gap,
            "blocked_mix": blocked_mix,
            "dominant_bottleneck": dominant_bottleneck,
            "family_focus": family_focus,
            "regime_modifier": regime_modifier,
            "session_modifier": session_modifier,
            "maturity": maturity,
        }
