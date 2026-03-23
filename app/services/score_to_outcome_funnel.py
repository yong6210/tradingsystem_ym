from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings, get_settings
from app.db.models import OrderSubmission, Plan
from app.db.repositories import ExecutionFillRepository, OrderSubmissionRepository, OutcomeRepository, PlanRepository
from app.services.execution_quality import ExecutionQualityService
from app.services.strategy_v2_stress_validation import StrategyV2StressValidationService
from app.services.strategy_v2_validation import ClosedTradeRecord, StrategyV2ValidationService


class ScoreToOutcomeFunnelService:
    def __init__(
        self,
        *,
        plan_repo: PlanRepository,
        outcome_repo: OutcomeRepository,
        fill_repo: ExecutionFillRepository,
        submission_repo: OrderSubmissionRepository,
        settings: Settings | None = None,
    ):
        self.plan_repo = plan_repo
        self.outcome_repo = outcome_repo
        self.fill_repo = fill_repo
        self.submission_repo = submission_repo
        self.settings = settings or get_settings()
        self.validation = StrategyV2ValidationService(self.settings)
        self.stress_validation = StrategyV2StressValidationService(
            self.settings,
            fill_repo=self.fill_repo,
            candle_repo=None,
        )
        self.execution_quality = ExecutionQualityService(
            plan_repo=self.plan_repo,
            outcome_repo=self.outcome_repo,
            candle_repo=None,
            fill_repo=self.fill_repo,
            settings=self.settings,
        )

    @staticmethod
    def _runtime_session_state(row: dict[str, Any]) -> str:
        return str(((row.get("session_guidance") or {}).get("state")) or "unknown")

    @staticmethod
    def _plan_family(plan: Plan | None) -> str:
        validity = dict(getattr(plan, "validity", {}) or {})
        return str(validity.get("strategy_family") or "unknown")

    @staticmethod
    def _plan_regime(plan: Plan | None) -> str:
        validity = dict(getattr(plan, "validity", {}) or {})
        return str(validity.get("regime") or "unknown")

    def _historical_session(
        self,
        *,
        plan: Plan | None,
        submission: OrderSubmission | None,
        closed_record: ClosedTradeRecord | None,
    ) -> str:
        if closed_record is not None:
            return self.validation._session_bucket(closed_record.closed_ts)

        if submission is not None:
            state = str(((submission.session_guidance or {}).get("state")) or "").strip()
            if state:
                return state

        valid_from = getattr(plan, "valid_from", None)
        if valid_from is not None:
            return self.validation._session_bucket(valid_from)
        return "unknown"

    @staticmethod
    def _validity(plan: Plan | None) -> dict[str, Any]:
        return dict(getattr(plan, "validity", {}) or {})

    @staticmethod
    def _scorecard_raw_components_from_plan(plan: Plan | None) -> dict[str, Any]:
        validity = dict(getattr(plan, "validity", {}) or {})
        return dict(validity.get("strategy_scorecard_raw_components") or {})

    @staticmethod
    def _scorecard_raw_components_from_row(row: dict[str, Any]) -> dict[str, Any]:
        if dict(row or {}).get("strategy_scorecard_raw_components"):
            return dict(row.get("strategy_scorecard_raw_components") or {})
        validity = dict(dict(row or {}).get("validity") or {})
        return dict(validity.get("strategy_scorecard_raw_components") or {})

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _volatility_bucket_from_values(
        cls,
        *,
        atr5: Any = None,
        atr15: Any = None,
        portfolio_volatility: Any = None,
    ) -> str:
        atr5_value = cls._float_or_none(atr5)
        atr15_value = cls._float_or_none(atr15)
        if atr5_value is not None and atr15_value is not None and atr15_value > 0.0:
            ratio = atr5_value / atr15_value
            if ratio <= 0.7:
                return "low_vol"
            if ratio >= 1.3:
                return "high_vol"
            return "normal_vol"
        volatility = cls._float_or_none(portfolio_volatility)
        if volatility is not None:
            if volatility <= 0.015:
                return "low_vol"
            if volatility >= 0.035:
                return "high_vol"
            return "normal_vol"
        return "unknown"

    @classmethod
    def _cost_bucket_from_runtime(cls, *, expected_fee_bps: Any = None, max_slippage_bps: Any = None) -> str:
        fee_bps = cls._float_or_none(expected_fee_bps)
        slippage_bps = cls._float_or_none(max_slippage_bps)
        if fee_bps is None or slippage_bps is None:
            return "unknown"
        total_bps = fee_bps + slippage_bps
        if total_bps <= 8.0:
            return "low_cost"
        if total_bps >= 18.0:
            return "high_cost"
        return "normal_cost"

    @classmethod
    def _cost_bucket_from_historical(cls, *, baseline_cost_r: Any = None) -> str:
        baseline_cost = cls._float_or_none(baseline_cost_r)
        if baseline_cost is None:
            return "unknown"
        if baseline_cost <= 0.05:
            return "low_cost"
        if baseline_cost >= 0.15:
            return "high_cost"
        return "normal_cost"

    @classmethod
    def _liquidity_bucket_from_values(cls, *, liquidity_score: Any = None, max_slippage_bps: Any = None) -> str:
        liquidity = cls._float_or_none(liquidity_score)
        if liquidity is not None:
            if liquidity <= 35.0:
                return "shallow_liquidity"
            if liquidity >= 70.0:
                return "deep_liquidity"
            return "normal_liquidity"
        slippage_bps = cls._float_or_none(max_slippage_bps)
        if slippage_bps is not None:
            if slippage_bps <= 6.0:
                return "deep_liquidity"
            if slippage_bps >= 15.0:
                return "shallow_liquidity"
            return "normal_liquidity"
        return "unknown"

    @staticmethod
    def _latest_submission_by_plan(rows: list[OrderSubmission]) -> dict[str, OrderSubmission]:
        out: dict[str, OrderSubmission] = {}
        for row in rows:
            plan_id = str(getattr(row, "plan_id", "") or "")
            if plan_id and plan_id not in out:
                out[plan_id] = row
        return out

    def _closed_records(
        self,
        *,
        plans: list[Plan],
        symbol: str,
        version: str,
    ) -> dict[str, ClosedTradeRecord]:
        out: dict[str, ClosedTradeRecord] = {}
        for plan in plans:
            record = self.validation._closed_trade(plan, symbol=symbol, version=version)
            if record is not None:
                out[record.plan_id] = record
        return out

    def _baseline_adjusted_by_plan(
        self,
        *,
        plans: list[Plan],
        closed_records: dict[str, ClosedTradeRecord],
    ) -> dict[str, dict[str, Any]]:
        if not closed_records:
            return {}

        fill_map = self.stress_validation._fill_map(plans)
        plan_lookup = {str(plan.plan_id): plan for plan in plans}
        out: dict[str, dict[str, Any]] = {}
        for plan_id, record in closed_records.items():
            plan = plan_lookup.get(plan_id)
            if plan is None:
                continue
            adjusted = self.stress_validation._adjust_trade(
                plan=plan,
                record=record,
                fills=list(fill_map.get(plan_id) or []),
            )
            out[plan_id] = {
                "baseline_adjusted_r": float(adjusted.baseline_adjusted_r),
                "baseline_cost_r": float(adjusted.baseline_cost_r),
                "cost_source": str(adjusted.cost_source),
            }
        return out

    @staticmethod
    def _selection_snapshot(portfolio_budget: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(portfolio_budget or {})
        accepted_rows = list(payload.get("accepted_candidates") or [])
        blocked_rows = list(payload.get("blocked_candidates") or [])
        runtime_candidates = len(accepted_rows) + len(blocked_rows)
        return {
            "runtime_candidates": runtime_candidates,
            "accepted_candidates": len(accepted_rows),
            "blocked_candidates": len(blocked_rows),
            "accept_rate": round((len(accepted_rows) / runtime_candidates), 4) if runtime_candidates > 0 else 0.0,
            "blocked_reason_counts": dict(payload.get("blocked_reason_counts") or {}),
            "blocked_gate_group_counts": dict(payload.get("blocked_gate_group_counts") or {}),
        }

    @staticmethod
    def _bucket_store() -> dict[str, Any]:
        return {
            "runtime_candidates": 0,
            "accepted_candidates": 0,
            "blocked_candidates": 0,
            "submitted_ids": set(),
            "filled_ids": set(),
            "closed_ids": set(),
            "profitable_ids": set(),
            "baseline_cost_profitable_ids": set(),
        }

    def _historical_bucket_key(
        self,
        *,
        axis: str,
        plan: Plan | None,
        submission: OrderSubmission | None,
        closed_record: ClosedTradeRecord | None,
        baseline_adjusted_row: dict[str, Any] | None = None,
    ) -> str:
        if axis == "family":
            return self._plan_family(plan)
        if axis == "regime":
            return self._plan_regime(plan)
        if axis == "session":
            return self._historical_session(plan=plan, submission=submission, closed_record=closed_record)
        validity = self._validity(plan)
        scorecard_raw_components = self._scorecard_raw_components_from_plan(plan)
        if axis == "volatility_condition":
            return self._volatility_bucket_from_values(
                atr5=validity.get("atr5"),
                atr15=validity.get("atr15"),
                portfolio_volatility=validity.get("portfolio_volatility"),
            )
        if axis == "cost_condition":
            return self._cost_bucket_from_historical(
                baseline_cost_r=dict(baseline_adjusted_row or {}).get("baseline_cost_r"),
            )
        if axis == "liquidity_condition":
            return self._liquidity_bucket_from_values(
                liquidity_score=scorecard_raw_components.get("liquidity"),
                max_slippage_bps=validity.get("max_slippage_bps"),
            )
        return "unknown"

    def _runtime_bucket_key(self, *, axis: str, row: dict[str, Any]) -> str:
        if axis == "family":
            return str(row.get("strategy_family") or "unknown")
        if axis == "regime":
            return str(row.get("regime") or "unknown")
        if axis == "session":
            return self._runtime_session_state(row)
        validity = dict(row.get("validity") or {})
        scorecard_raw_components = self._scorecard_raw_components_from_row(row)
        if axis == "volatility_condition":
            return self._volatility_bucket_from_values(
                atr5=row.get("atr5", validity.get("atr5")),
                atr15=row.get("atr15", validity.get("atr15")),
                portfolio_volatility=row.get("portfolio_volatility", validity.get("portfolio_volatility")),
            )
        if axis == "cost_condition":
            return self._cost_bucket_from_runtime(
                expected_fee_bps=row.get("expected_fee_bps", validity.get("expected_fee_bps")),
                max_slippage_bps=row.get("max_slippage_bps", validity.get("max_slippage_bps")),
            )
        if axis == "liquidity_condition":
            return self._liquidity_bucket_from_values(
                liquidity_score=scorecard_raw_components.get("liquidity"),
                max_slippage_bps=row.get("max_slippage_bps", validity.get("max_slippage_bps")),
            )
        return "unknown"

    def _decomposition_rows(
        self,
        *,
        axis: str,
        accepted_rows: list[dict[str, Any]],
        blocked_rows: list[dict[str, Any]],
        plan_lookup: dict[str, Plan],
        submission_lookup: dict[str, OrderSubmission],
        filled_plan_ids: set[str],
        closed_records: dict[str, ClosedTradeRecord],
        baseline_adjusted: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = defaultdict(self._bucket_store)

        for row in accepted_rows:
            key = self._runtime_bucket_key(axis=axis, row=row)
            bucket = buckets[key]
            bucket["runtime_candidates"] += 1
            bucket["accepted_candidates"] += 1

        for row in blocked_rows:
            key = self._runtime_bucket_key(axis=axis, row=row)
            bucket = buckets[key]
            bucket["runtime_candidates"] += 1
            bucket["blocked_candidates"] += 1

        closed_ids = set(closed_records)
        profitable_ids = {plan_id for plan_id, record in closed_records.items() if float(record.realized_r) > 0.0}
        baseline_profitable_ids = {
            plan_id
            for plan_id, payload in baseline_adjusted.items()
            if float(payload.get("baseline_adjusted_r", 0.0) or 0.0) > 0.0
        }

        for plan_id, submission in submission_lookup.items():
            plan = plan_lookup.get(plan_id)
            key = self._historical_bucket_key(axis=axis, plan=plan, submission=submission, closed_record=closed_records.get(plan_id))
            if axis in {"cost_condition"}:
                key = self._historical_bucket_key(
                    axis=axis,
                    plan=plan,
                    submission=submission,
                    closed_record=closed_records.get(plan_id),
                    baseline_adjusted_row=baseline_adjusted.get(plan_id),
                )
            buckets[key]["submitted_ids"].add(plan_id)

        for plan_id in filled_plan_ids:
            plan = plan_lookup.get(plan_id)
            key = self._historical_bucket_key(
                axis=axis,
                plan=plan,
                submission=submission_lookup.get(plan_id),
                closed_record=closed_records.get(plan_id),
                baseline_adjusted_row=baseline_adjusted.get(plan_id),
            )
            buckets[key]["filled_ids"].add(plan_id)

        for plan_id in closed_ids:
            plan = plan_lookup.get(plan_id)
            key = self._historical_bucket_key(
                axis=axis,
                plan=plan,
                submission=submission_lookup.get(plan_id),
                closed_record=closed_records.get(plan_id),
                baseline_adjusted_row=baseline_adjusted.get(plan_id),
            )
            buckets[key]["closed_ids"].add(plan_id)

        for plan_id in profitable_ids:
            plan = plan_lookup.get(plan_id)
            key = self._historical_bucket_key(
                axis=axis,
                plan=plan,
                submission=submission_lookup.get(plan_id),
                closed_record=closed_records.get(plan_id),
                baseline_adjusted_row=baseline_adjusted.get(plan_id),
            )
            buckets[key]["profitable_ids"].add(plan_id)

        for plan_id in baseline_profitable_ids:
            plan = plan_lookup.get(plan_id)
            key = self._historical_bucket_key(
                axis=axis,
                plan=plan,
                submission=submission_lookup.get(plan_id),
                closed_record=closed_records.get(plan_id),
                baseline_adjusted_row=baseline_adjusted.get(plan_id),
            )
            buckets[key]["baseline_cost_profitable_ids"].add(plan_id)

        rows: list[dict[str, Any]] = []
        for key, bucket in buckets.items():
            submitted_ids = set(bucket["submitted_ids"])
            filled_ids = set(bucket["filled_ids"])
            closed_ids = set(bucket["closed_ids"])
            profitable_ids = set(bucket["profitable_ids"])
            baseline_profitable_ids = set(bucket["baseline_cost_profitable_ids"])
            runtime_candidates = int(bucket["runtime_candidates"])
            accepted_candidates = int(bucket["accepted_candidates"])
            blocked_candidates = int(bucket["blocked_candidates"])
            rows.append(
                {
                    "key": key,
                    "runtime_candidates": runtime_candidates,
                    "accepted_candidates": accepted_candidates,
                    "blocked_candidates": blocked_candidates,
                    "submitted": len(submitted_ids),
                    "filled": len(filled_ids),
                    "closed": len(closed_ids),
                    "profitable": len(profitable_ids),
                    "baseline_cost_profitable": len(baseline_profitable_ids),
                    "accept_rate": round((accepted_candidates / runtime_candidates), 4) if runtime_candidates > 0 else 0.0,
                    "fill_rate_from_submitted": round((len(submitted_ids & filled_ids) / len(submitted_ids)), 4)
                    if submitted_ids
                    else 0.0,
                    "close_rate_from_filled": round((len(filled_ids & closed_ids) / len(filled_ids)), 4)
                    if filled_ids
                    else 0.0,
                    "profitable_rate_from_closed": round((len(profitable_ids & closed_ids) / len(closed_ids)), 4)
                    if closed_ids
                    else 0.0,
                    "baseline_cost_profitable_rate_from_closed": round(
                        (len(baseline_profitable_ids & closed_ids) / len(closed_ids)),
                        4,
                    )
                    if closed_ids
                    else 0.0,
                }
            )

        rows.sort(
            key=lambda item: (
                -int(item["runtime_candidates"]),
                -int(item["submitted"]),
                -int(item["closed"]),
                str(item["key"]),
            )
        )
        return rows

    def generate(
        self,
        *,
        symbol: str,
        version: str,
        days: int,
        portfolio_budget: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        report_window_days = max(1, int(days))
        plans = [
            plan
            for plan in self.plan_repo.list_recent(symbol=symbol, days=report_window_days)
            if str(getattr(plan, "strategy_version", "") or "") == str(version)
        ]
        plan_lookup = {str(plan.plan_id): plan for plan in plans}
        plan_ids = list(plan_lookup)

        recent_submissions = [
            row
            for row in self.submission_repo.list_recent(symbol=symbol, days=report_window_days, limit=5000)
            if str(getattr(row, "plan_id", "") or "") in plan_lookup
        ]
        submission_lookup = self._latest_submission_by_plan(recent_submissions)

        fills = self.fill_repo.list_for_plans(plan_ids=plan_ids, symbol=symbol) if plan_ids else []
        matched_entries, _, _ = self.execution_quality._aggregate_actual_entries(fills)
        fallback_entries = self.execution_quality._match_legacy_outcomes(
            plans=plans,
            already_matched_plan_ids=set(matched_entries),
            outcomes=self.outcome_repo.list_recent(symbol=symbol, days=report_window_days),
        )
        matched_entries.update(fallback_entries)
        filled_plan_ids = {plan_id for plan_id in matched_entries if plan_id in plan_lookup}

        closed_records = self._closed_records(plans=plans, symbol=symbol, version=version)
        baseline_adjusted = self._baseline_adjusted_by_plan(plans=plans, closed_records=closed_records)

        accepted_rows = list(dict(portfolio_budget or {}).get("accepted_candidates") or [])
        blocked_rows = list(dict(portfolio_budget or {}).get("blocked_candidates") or [])

        submitted_plan_ids = set(submission_lookup)
        closed_plan_ids = set(closed_records)
        profitable_plan_ids = {plan_id for plan_id, record in closed_records.items() if float(record.realized_r) > 0.0}
        baseline_profitable_plan_ids = {
            plan_id
            for plan_id, payload in baseline_adjusted.items()
            if float(payload.get("baseline_adjusted_r", 0.0) or 0.0) > 0.0
        }

        historical_execution_outcomes = {
            "submitted": len(submitted_plan_ids),
            "filled": len(filled_plan_ids),
            "closed": len(closed_plan_ids),
            "profitable": len(profitable_plan_ids),
            "baseline_cost_profitable": len(baseline_profitable_plan_ids),
            "fill_rate_from_submitted": round((len(submitted_plan_ids & filled_plan_ids) / len(submitted_plan_ids)), 4)
            if submitted_plan_ids
            else 0.0,
            "close_rate_from_filled": round((len(filled_plan_ids & closed_plan_ids) / len(filled_plan_ids)), 4)
            if filled_plan_ids
            else 0.0,
            "profitable_rate_from_closed": round((len(profitable_plan_ids & closed_plan_ids) / len(closed_plan_ids)), 4)
            if closed_plan_ids
            else 0.0,
            "baseline_cost_profitable_rate_from_closed": round(
                (len(baseline_profitable_plan_ids & closed_plan_ids) / len(closed_plan_ids)),
                4,
            )
            if closed_plan_ids
            else 0.0,
        }

        available = bool(accepted_rows or blocked_rows or submitted_plan_ids or filled_plan_ids or closed_plan_ids)
        reason = "ok" if available else "no_runtime_or_recent_execution_data"
        coverage_note = (
            "snapshot_selection is current runtime state, while historical_execution_outcomes is a windowed history; "
            "baseline_cost_profitable uses the stress-validation baseline cost proxy and closed counts only cover eligible "
            "closed v2 trades with family/grade metadata."
        )

        return {
            "available": available,
            "reason": reason,
            "report_window_days": report_window_days,
            "coverage_note": coverage_note,
            "snapshot_selection": self._selection_snapshot(portfolio_budget),
            "historical_execution_outcomes": historical_execution_outcomes,
            "decomposition": {
                axis: self._decomposition_rows(
                    axis=axis,
                    accepted_rows=accepted_rows,
                    blocked_rows=blocked_rows,
                    plan_lookup=plan_lookup,
                    submission_lookup=submission_lookup,
                    filled_plan_ids=filled_plan_ids,
                    closed_records=closed_records,
                    baseline_adjusted=baseline_adjusted,
                )
                for axis in (
                    "family",
                    "regime",
                    "session",
                    "volatility_condition",
                    "cost_condition",
                    "liquidity_condition",
                )
            },
        }
