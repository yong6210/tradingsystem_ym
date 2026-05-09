from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.enums import EntryModel, ExecutionFillStage
from app.services.strategy_v2_validation import ClosedTradeRecord, StrategyV2ValidationService


@dataclass(slots=True)
class StressAdjustedTradeRecord:
    base: ClosedTradeRecord
    baseline_adjusted_r: float
    stressed_adjusted_r: float
    latency_plus_1_bar_adjusted_r: float
    partial_fills_only_adjusted_r: float
    shock_concentration_adjusted_r: float
    baseline_cost_r: float
    stressed_cost_r: float
    fee_component_r: float
    slippage_component_r: float
    latency_penalty_r: float
    partial_fill_factor: float
    shock_factor: float
    regime: str
    cost_source: str
    latency_source: str


class StrategyV2StressValidationService:
    _SCENARIO_ORDER = (
        "latency_plus_1_bar",
        "partial_fills_only",
        "shock_concentration",
    )
    _COST_MULTIPLIER = 1.5
    _SLIPPAGE_MULTIPLIER = 2.0
    _LATENCY_BARS = 1
    _PARTIAL_FILL_FACTOR = 0.5
    _SHOCK_LOSS_MULTIPLIER = 1.5
    _SHOCK_WIN_MULTIPLIER = 0.75
    _CATASTROPHIC_DRAWDOWN_R = 4.0

    def __init__(self, settings: Settings | None = None, *, fill_repo: Any | None = None, candle_repo: Any | None = None):
        self.settings = settings or get_settings()
        self.fill_repo = fill_repo
        self.candle_repo = candle_repo
        self._base = StrategyV2ValidationService(self.settings)

    @staticmethod
    def _entry_model(plan: Any) -> str:
        value = getattr(plan, "entry_model", None)
        if isinstance(value, EntryModel):
            return value.value
        return str(value or EntryModel.CONFIRM.value).upper()

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
    def _risk_abs(plan: Any) -> float:
        return abs(float(getattr(plan, "entry_price", 0.0)) - float(getattr(plan, "sl", 0.0)))

    @staticmethod
    def _direction_sign(plan: Any) -> float:
        return 1.0 if str(getattr(plan, "direction", "long")).lower() == "long" else -1.0

    @staticmethod
    def _regime(plan: Any) -> str:
        validity = dict(getattr(plan, "validity", {}) or {})
        regime = str(validity.get("regime", "range")).lower()
        if regime in {"trend", "range", "shock", "transition"}:
            return regime
        return "range"

    @staticmethod
    def _normalize_ts(ts: datetime | None) -> datetime | None:
        if ts is None:
            return None
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)

    @classmethod
    def _parse_ts(cls, value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return cls._normalize_ts(datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            return None

    @classmethod
    def _bar_start_5m(cls, ts: datetime) -> datetime:
        normalized = cls._normalize_ts(ts)
        if normalized is None:
            raise ValueError("5m bar start requires a timestamp")
        minute = (normalized.minute // 5) * 5
        return normalized.replace(minute=minute, second=0, microsecond=0)

    @staticmethod
    def _quantile(values: list[float], q: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(float(value) for value in values)
        idx = max(0, min(len(ordered) - 1, int(q * (len(ordered) - 1))))
        return float(ordered[idx])

    @classmethod
    def _summary(cls, values: list[float]) -> dict[str, float]:
        if not values:
            return {"avg": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
        return {
            "avg": round(float(sum(values) / len(values)), 4),
            "p50": round(cls._quantile(values, 0.50), 4),
            "p95": round(cls._quantile(values, 0.95), 4),
            "max": round(float(max(values)), 4),
        }

    def _fill_map(self, plans: list[Any]) -> dict[str, list[Any]]:
        if self.fill_repo is None:
            return {}
        plan_ids = [str(getattr(plan, "plan_id", "") or "") for plan in plans if getattr(plan, "plan_id", None)]
        if not plan_ids:
            return {}
        rows = self.fill_repo.list_for_plans(plan_ids=plan_ids)
        out: dict[str, list[Any]] = {}
        for row in rows:
            out.setdefault(str(getattr(row, "plan_id", "") or ""), []).append(row)
        return out

    def _estimated_fee_r(self, *, plan: Any, risk_abs: float) -> float:
        if risk_abs <= 1e-9:
            return 0.0
        entry = float(getattr(plan, "entry_price", 0.0) or 0.0)
        model = self._entry_model(plan)
        fee_bps = (
            self._safe_float(self.settings.maker_fee_bps, default=2.0)
            if model == EntryModel.LIMIT.value
            else self._safe_float(self.settings.taker_fee_bps, default=4.0)
        )
        return float((entry * ((fee_bps * 2.0) / 10_000.0)) / risk_abs)

    @staticmethod
    def _actual_fee_r(*, fills: list[Any], risk_abs: float) -> float | None:
        if risk_abs <= 1e-9 or not fills:
            return None
        total = float(sum(float(getattr(fill, "fee", 0.0) or 0.0) for fill in fills))
        return float(total / risk_abs)

    @staticmethod
    def _entry_fill(fills: list[Any]) -> Any | None:
        entries = [fill for fill in fills if str(getattr(fill, "stage", "")) == ExecutionFillStage.ENTRY.value]
        if not entries:
            return None
        entries.sort(key=lambda fill: fill.fill_ts)
        return entries[0]

    def _entry_anchor(self, *, plan: Any, fills: list[Any]) -> tuple[datetime, float, str]:
        entry_fill = self._entry_fill(fills)
        if entry_fill is not None:
            fill_ts = self._normalize_ts(getattr(entry_fill, "fill_ts", None))
            if fill_ts is not None:
                return fill_ts, float(getattr(entry_fill, "price", 0.0) or 0.0), "execution_entry_fill"
        valid_from = self._normalize_ts(getattr(plan, "valid_from", None))
        if valid_from is not None:
            return valid_from, float(getattr(plan, "entry_price", 0.0) or 0.0), "plan_valid_from"
        return datetime.now(timezone.utc), float(getattr(plan, "entry_price", 0.0) or 0.0), "fallback_now"

    @staticmethod
    def _actual_entry_slippage_r(*, plan: Any, fills: list[Any], risk_abs: float) -> float | None:
        if risk_abs <= 1e-9:
            return None
        entry_fill = StrategyV2StressValidationService._entry_fill(fills)
        if entry_fill is None:
            return None
        return float(abs(float(getattr(entry_fill, "price", 0.0)) - float(getattr(plan, "entry_price", 0.0))) / risk_abs)

    def _cost_components(self, *, plan: Any, fills: list[Any]) -> tuple[float, float, str]:
        risk_abs = self._risk_abs(plan)
        if risk_abs <= 1e-9:
            return 0.0, 0.0, "invalid_risk"

        estimated_fee_r = self._estimated_fee_r(plan=plan, risk_abs=risk_abs)
        estimated_slippage_r = max(0.0, float(getattr(plan, "cost_est", 0.0) or 0.0) - estimated_fee_r)

        actual_fee_r = self._actual_fee_r(fills=fills, risk_abs=risk_abs)
        actual_slippage_r = self._actual_entry_slippage_r(plan=plan, fills=fills, risk_abs=risk_abs)

        if actual_fee_r is not None or actual_slippage_r is not None:
            fee_component_r = float(actual_fee_r if actual_fee_r is not None and actual_fee_r > 0.0 else estimated_fee_r)
            slippage_component_r = float(actual_slippage_r if actual_slippage_r is not None else estimated_slippage_r)
            return fee_component_r, slippage_component_r, "execution_fills"

        return float(estimated_fee_r), float(estimated_slippage_r), "plan_cost_est"

    def _latency_penalty_r(
        self,
        *,
        plan: Any,
        fills: list[Any],
        risk_abs: float,
        fallback_slippage_r: float,
    ) -> tuple[float, str]:
        if risk_abs <= 1e-9:
            return 0.0, "invalid_risk"

        anchor_ts, anchor_price, anchor_source = self._entry_anchor(plan=plan, fills=fills)
        if self.candle_repo is None:
            return float(fallback_slippage_r), f"fallback_slippage:{anchor_source}"

        delayed_bar_ts = self._bar_start_5m(anchor_ts) + timedelta(minutes=5 * self._LATENCY_BARS)
        candles = self.candle_repo.list_range(
            symbol=str(getattr(plan, "symbol", "")),
            timeframe="5m",
            start_ts=delayed_bar_ts,
            end_ts=delayed_bar_ts + timedelta(minutes=15),
        )
        delayed_price: float | None = None
        for candle in candles:
            candle_ts = self._normalize_ts(getattr(candle, "ts", None))
            if candle_ts is not None and candle_ts >= delayed_bar_ts:
                delayed_price = float(getattr(candle, "o", 0.0) or 0.0)
                break

        if delayed_price is None:
            return float(fallback_slippage_r), f"fallback_slippage:{anchor_source}"

        adverse_move = self._direction_sign(plan) * (float(delayed_price) - float(anchor_price))
        penalty = max(0.0, float(adverse_move)) / risk_abs
        return float(penalty), f"candle_open:{delayed_bar_ts.isoformat()}"

    def _shock_adjusted_r(self, *, baseline_adjusted_r: float, regime: str) -> tuple[float, float]:
        if regime != "shock":
            return float(baseline_adjusted_r), 1.0
        if baseline_adjusted_r < 0.0:
            factor = self._SHOCK_LOSS_MULTIPLIER
        elif baseline_adjusted_r > 0.0:
            factor = self._SHOCK_WIN_MULTIPLIER
        else:
            factor = 1.0
        return float(baseline_adjusted_r) * factor, float(factor)

    def _adjust_trade(self, *, plan: Any, record: ClosedTradeRecord, fills: list[Any]) -> StressAdjustedTradeRecord:
        fee_component_r, slippage_component_r, cost_source = self._cost_components(plan=plan, fills=fills)
        baseline_cost_r = float(fee_component_r + slippage_component_r)
        stressed_cost_r = float((fee_component_r * self._COST_MULTIPLIER) + (slippage_component_r * self._SLIPPAGE_MULTIPLIER))
        baseline_adjusted_r = round(float(record.realized_r) - baseline_cost_r, 4)
        stressed_adjusted_r = round(float(record.realized_r) - stressed_cost_r, 4)
        latency_penalty_r, latency_source = self._latency_penalty_r(
            plan=plan,
            fills=fills,
            risk_abs=self._risk_abs(plan),
            fallback_slippage_r=slippage_component_r,
        )
        latency_plus_1_bar_adjusted_r = round(baseline_adjusted_r - float(latency_penalty_r), 4)
        partial_fills_only_adjusted_r = round(baseline_adjusted_r * self._PARTIAL_FILL_FACTOR, 4)
        regime = self._regime(plan)
        shock_concentration_adjusted_r, shock_factor = self._shock_adjusted_r(
            baseline_adjusted_r=baseline_adjusted_r,
            regime=regime,
        )
        return StressAdjustedTradeRecord(
            base=record,
            baseline_adjusted_r=baseline_adjusted_r,
            stressed_adjusted_r=stressed_adjusted_r,
            latency_plus_1_bar_adjusted_r=latency_plus_1_bar_adjusted_r,
            partial_fills_only_adjusted_r=partial_fills_only_adjusted_r,
            shock_concentration_adjusted_r=round(shock_concentration_adjusted_r, 4),
            baseline_cost_r=round(baseline_cost_r, 4),
            stressed_cost_r=round(stressed_cost_r, 4),
            fee_component_r=round(fee_component_r, 4),
            slippage_component_r=round(slippage_component_r, 4),
            latency_penalty_r=round(float(latency_penalty_r), 4),
            partial_fill_factor=self._PARTIAL_FILL_FACTOR,
            shock_factor=round(float(shock_factor), 4),
            regime=regime,
            cost_source=cost_source,
            latency_source=latency_source,
        )

    def _metrics(self, records: list[StressAdjustedTradeRecord], *, mode: str) -> dict[str, Any]:
        mode_field = {
            "baseline": "baseline_adjusted_r",
            "stressed": "stressed_adjusted_r",
            "latency_plus_1_bar": "latency_plus_1_bar_adjusted_r",
            "partial_fills_only": "partial_fills_only_adjusted_r",
            "shock_concentration": "shock_concentration_adjusted_r",
        }[mode]
        transformed = [
            ClosedTradeRecord(
                plan_id=record.base.plan_id,
                symbol=record.base.symbol,
                closed_ts=record.base.closed_ts,
                realized_r=float(getattr(record, mode_field)),
                held_bars=record.base.held_bars,
                exit_reason=record.base.exit_reason,
                regime=record.base.regime,
                strategy_family=record.base.strategy_family,
                strategy_grade=record.base.strategy_grade,
                strategy_version=record.base.strategy_version,
            )
            for record in records
        ]
        return self._base._mode_metrics(transformed)

    @classmethod
    def _recommendation(cls, *, baseline: dict[str, Any], stressed: dict[str, Any]) -> dict[str, Any]:
        catastrophic = float(stressed.get("max_drawdown", 0.0)) > cls._CATASTROPHIC_DRAWDOWN_R
        reason = "stress_within_drawdown_limit"
        if catastrophic:
            reason = "stress_catastrophic_drawdown"
        elif float(stressed.get("ev", 0.0)) <= 0.0:
            reason = "stress_negative_ev"
        return {
            "stress_pass": not catastrophic,
            "catastrophic_loss_detected": catastrophic,
            "reason": reason,
            "stressed_drawdown_limit_r": cls._CATASTROPHIC_DRAWDOWN_R,
        }

    @classmethod
    def _scenario_status(cls, *, metrics: dict[str, Any]) -> dict[str, Any]:
        catastrophic = float(metrics.get("max_drawdown", 0.0)) > cls._CATASTROPHIC_DRAWDOWN_R
        negative_ev = float(metrics.get("ev", 0.0)) <= 0.0
        if catastrophic:
            return {
                "status": "FAIL",
                "catastrophic_loss_detected": True,
                "reason": "catastrophic_drawdown",
            }
        if negative_ev:
            return {
                "status": "WARN",
                "catastrophic_loss_detected": False,
                "reason": "negative_ev",
            }
        return {
            "status": "PASS",
            "catastrophic_loss_detected": False,
            "reason": "within_limits",
        }

    @classmethod
    def _scenario_recommendation(
        cls,
        *,
        base_recommendation: dict[str, Any],
        scenario_metrics: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        statuses = {name: cls._scenario_status(metrics=metrics) for name, metrics in scenario_metrics.items()}
        all_rows = {
            "stressed_cost": {
                "status": "PASS" if bool(base_recommendation.get("stress_pass", False)) else "WARN",
                "reason": str(base_recommendation.get("reason", "not_available")),
                "catastrophic_loss_detected": bool(base_recommendation.get("catastrophic_loss_detected", False)),
                "metrics": {},
            }
        }
        for name, row in statuses.items():
            all_rows[name] = {**row, "metrics": dict(scenario_metrics.get(name) or {})}

        def sort_key(item: tuple[str, dict[str, Any]]) -> tuple[float, float]:
            metrics = dict(item[1].get("metrics") or scenario_metrics.get(item[0]) or {})
            return (
                float(metrics.get("max_drawdown", 0.0)),
                -float(metrics.get("ev", 0.0)),
            )

        scenario_items = [(name, row) for name, row in all_rows.items() if name != "stressed_cost"]
        worst_scenario = max(scenario_items, key=sort_key)[0] if scenario_items else "stressed_cost"

        catastrophic = bool(base_recommendation.get("catastrophic_loss_detected", False)) or any(
            bool(row.get("catastrophic_loss_detected", False)) for row in statuses.values()
        )
        warn_exists = (not bool(base_recommendation.get("stress_pass", False))) or any(
            str(row.get("status")) != "PASS" for row in statuses.values()
        )
        if catastrophic:
            reason = f"scenario_catastrophic_drawdown:{worst_scenario}"
            stress_pass = False
        elif warn_exists:
            bad = next(
                (name for name, row in statuses.items() if str(row.get("status")) != "PASS"),
                "stressed_cost",
            )
            reason = f"scenario_degraded:{bad}"
            stress_pass = False
        else:
            reason = str(base_recommendation.get("reason", "stress_within_drawdown_limit"))
            stress_pass = True
        return {
            "stress_pass": stress_pass,
            "catastrophic_loss_detected": catastrophic,
            "reason": reason,
            "stressed_drawdown_limit_r": cls._CATASTROPHIC_DRAWDOWN_R,
            "scenario_statuses": statuses,
            "worst_scenario": worst_scenario,
        }

    @classmethod
    def _scenario_names(cls, *, scenario_metrics: dict[str, dict[str, Any]]) -> list[str]:
        names: list[str] = []
        for name in cls._SCENARIO_ORDER:
            if name in scenario_metrics:
                names.append(name)
        for name in scenario_metrics:
            if name not in names:
                names.append(name)
        return names

    @staticmethod
    def _status_rank(status: str) -> int:
        order = {"PASS": 0, "WARN": 1, "FAIL": 2}
        return int(order.get(str(status).upper(), 0))

    def _replay_divergence_thresholds(self) -> dict[str, float]:
        return {
            "warn_ev_delta": self._safe_float(self.settings.stress_replay_divergence_warn_ev_delta, default=-0.10),
            "fail_ev_delta": self._safe_float(self.settings.stress_replay_divergence_fail_ev_delta, default=-0.25),
            "warn_max_drawdown_delta": self._safe_float(
                self.settings.stress_replay_divergence_warn_max_drawdown_delta,
                default=0.25,
            ),
            "fail_max_drawdown_delta": self._safe_float(
                self.settings.stress_replay_divergence_fail_max_drawdown_delta,
                default=0.75,
            ),
        }

    def _replay_divergence_status(self, *, approximation_delta: dict[str, Any]) -> dict[str, Any]:
        thresholds = self._replay_divergence_thresholds()
        ev_delta = float(approximation_delta.get("ev", 0.0) or 0.0)
        max_drawdown_delta = float(approximation_delta.get("max_drawdown", 0.0) or 0.0)

        fail_axes: list[str] = []
        warn_axes: list[str] = []
        if ev_delta <= thresholds["fail_ev_delta"]:
            fail_axes.append("ev")
        elif ev_delta <= thresholds["warn_ev_delta"]:
            warn_axes.append("ev")
        if max_drawdown_delta >= thresholds["fail_max_drawdown_delta"]:
            fail_axes.append("max_drawdown")
        elif max_drawdown_delta >= thresholds["warn_max_drawdown_delta"]:
            warn_axes.append("max_drawdown")

        if fail_axes:
            return {
                "status": "FAIL",
                "reason": f"replay_divergence_fail:{','.join(fail_axes)}",
                "axes": fail_axes,
                "thresholds": thresholds,
            }
        if warn_axes:
            return {
                "status": "WARN",
                "reason": f"replay_divergence_warn:{','.join(warn_axes)}",
                "axes": warn_axes,
                "thresholds": thresholds,
            }
        return {
            "status": "PASS",
            "reason": "within_divergence_threshold",
            "axes": [],
            "thresholds": thresholds,
        }

    def _effective_recommendation_with_replay_gate(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        recommendation = dict(payload.get("deployment_recommendation") or {})
        scenario_metrics = dict(payload.get("scenario_metrics") or {})
        scenario_names = self._scenario_names(scenario_metrics=scenario_metrics)
        replay_output_artifacts = dict(payload.get("replay_output_artifacts") or {})
        replay_output_comparison = dict(payload.get("replay_output_comparison") or {})
        replay_outputs = dict(replay_output_artifacts.get("scenario_outputs") or {})
        stress_metrics = dict(payload.get("stress_metrics") or {})
        baseline_metrics = dict(stress_metrics.get("baseline_cost") or {})
        stressed_metrics = dict(stress_metrics.get("stressed_cost") or {})
        base_recommendation = self._recommendation(baseline=baseline_metrics, stressed=stressed_metrics)

        effective_statuses: dict[str, dict[str, Any]] = {}
        scenario_sources: dict[str, str] = {}
        replay_scenarios_considered: list[str] = []
        effective_metrics_by_scenario: dict[str, dict[str, Any]] = {}
        divergence_problem_scenarios: list[str] = []
        divergence_fail_scenarios: list[str] = []
        divergence_warn_scenarios: list[str] = []

        for scenario_name in scenario_names:
            approximation_metrics = dict(scenario_metrics.get(scenario_name) or {})
            replay_row = dict(replay_outputs.get(scenario_name) or {})
            replay_summary = dict(replay_row.get("summary") or {})
            replay_available = bool(replay_row.get("available", False)) and bool(replay_summary)
            source = "replay_output" if replay_available else "approximation"
            metrics = replay_summary if replay_available else approximation_metrics
            status = self._scenario_status(metrics=metrics)
            status["source"] = source
            status["artifact_reason"] = str(
                replay_row.get("reason", "artifact_loaded" if replay_available else "artifact_not_used")
            )
            if replay_available:
                approximation_delta = dict(
                    replay_output_comparison.get(scenario_name) or replay_row.get("comparison_to_approximation") or {}
                )
                divergence = self._replay_divergence_status(approximation_delta=approximation_delta)
                status["approximation_delta"] = approximation_delta
                status["divergence_status"] = divergence["status"]
                status["divergence_reason"] = divergence["reason"]
                status["divergence_axes"] = list(divergence["axes"])
                status["divergence_thresholds"] = dict(divergence["thresholds"])
                if self._status_rank(str(divergence["status"])) > self._status_rank(str(status["status"])):
                    status["status"] = str(divergence["status"])
                    status["reason"] = f"{divergence['reason']}:replay_output"
                else:
                    status["reason"] = f"{status['reason']}:replay_output"
                replay_scenarios_considered.append(scenario_name)
                if str(divergence["status"]) != "PASS":
                    divergence_problem_scenarios.append(scenario_name)
                    if str(divergence["status"]) == "FAIL":
                        divergence_fail_scenarios.append(scenario_name)
                    else:
                        divergence_warn_scenarios.append(scenario_name)
            effective_statuses[scenario_name] = status
            scenario_sources[scenario_name] = source
            effective_metrics_by_scenario[scenario_name] = dict(metrics)

        def sort_key(item: tuple[str, dict[str, Any]]) -> tuple[float, float]:
            metrics = dict(item[1] or {})
            return (
                float(metrics.get("max_drawdown", 0.0)),
                -float(metrics.get("ev", 0.0)),
            )

        def divergence_sort_key(item: tuple[str, dict[str, Any]]) -> tuple[int, float, float]:
            delta = dict(item[1].get("approximation_delta") or {})
            return (
                self._status_rank(str(item[1].get("divergence_status", "PASS"))),
                float(delta.get("max_drawdown", 0.0) or 0.0),
                abs(float(delta.get("ev", 0.0) or 0.0)),
            )

        scenario_items = list(effective_metrics_by_scenario.items())
        worst_scenario = max(scenario_items, key=sort_key)[0] if scenario_items else "stressed_cost"
        divergence_items = [
            (name, dict(effective_statuses.get(name) or {}))
            for name in scenario_names
            if str((effective_statuses.get(name) or {}).get("divergence_status", "PASS")) != "PASS"
        ]
        worst_divergence_scenario = max(divergence_items, key=divergence_sort_key)[0] if divergence_items else None
        catastrophic = bool(base_recommendation.get("catastrophic_loss_detected", False)) or any(
            bool(row.get("catastrophic_loss_detected", False)) for row in effective_statuses.values()
        )
        degraded_scenarios = [
            name for name in scenario_names if str((effective_statuses.get(name) or {}).get("status", "PASS")) != "PASS"
        ]
        warn_exists = (not bool(base_recommendation.get("stress_pass", False))) or bool(degraded_scenarios)
        if catastrophic:
            reason = f"scenario_catastrophic_drawdown:{worst_scenario}"
            stress_pass = False
        elif divergence_fail_scenarios:
            reason = f"replay_divergence_fail:{divergence_fail_scenarios[0]}"
            stress_pass = False
        elif divergence_warn_scenarios:
            reason = f"replay_divergence_warn:{divergence_warn_scenarios[0]}"
            stress_pass = False
        elif warn_exists:
            reason = f"scenario_degraded:{degraded_scenarios[0] if degraded_scenarios else 'stressed_cost'}"
            stress_pass = False
        else:
            reason = str(base_recommendation.get("reason", "stress_within_drawdown_limit"))
            stress_pass = True

        recommendation.update(
            {
                "stress_pass": stress_pass,
                "catastrophic_loss_detected": catastrophic,
                "reason": reason,
                "stressed_drawdown_limit_r": self._CATASTROPHIC_DRAWDOWN_R,
                "scenario_statuses": effective_statuses,
                "worst_scenario": worst_scenario,
                "replay_gate_applied": bool(replay_scenarios_considered),
                "replay_gate_reason": (
                    f"replay_output_override:{','.join(replay_scenarios_considered)}"
                    if replay_scenarios_considered
                    else "approximation_only"
                ),
                "divergence_gate_applied": bool(replay_scenarios_considered),
                "divergence_problem_scenarios": divergence_problem_scenarios,
                "divergence_fail_scenarios": divergence_fail_scenarios,
                "divergence_warn_scenarios": divergence_warn_scenarios,
                "worst_divergence_scenario": worst_divergence_scenario,
                "divergence_thresholds": self._replay_divergence_thresholds(),
                "replay_scenarios_considered": replay_scenarios_considered,
                "scenario_sources": scenario_sources,
                "worst_scenario_source": scenario_sources.get(worst_scenario, "stressed_cost"),
            }
        )
        return recommendation

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.validation_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / (
            f"strategy_v2_stress_validation_{payload['symbol']}_{payload['version']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        )

        baseline = dict((payload.get("stress_metrics") or {}).get("baseline_cost") or {})
        stressed = dict((payload.get("stress_metrics") or {}).get("stressed_cost") or {})
        comparison = dict(payload.get("comparison") or {})
        cost_summary = dict(payload.get("cost_summary") or {})
        scenario_metrics = dict(payload.get("scenario_metrics") or {})
        scenario_comparison = dict(payload.get("scenario_comparison") or {})
        scenario_summary = dict(payload.get("scenario_summary") or {})
        replay_output_artifacts = dict(payload.get("replay_output_artifacts") or {})
        replay_output_comparison = dict(payload.get("replay_output_comparison") or {})
        recommendation = dict(payload.get("deployment_recommendation") or {})
        scenario_statuses = dict(recommendation.get("scenario_statuses") or {})
        lines = [
            f"# Strategy v2 Stressed Cost Validation: {payload['symbol']}",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- strategy_version: {payload['version']}",
            f"- available: {payload['available']}",
            f"- reason: {payload['reason']}",
            f"- comparison_axis: {payload.get('comparison_axis', 'baseline_vs_stressed_cost')}",
            f"- cost_multiplier: {self._COST_MULTIPLIER:.2f}",
            f"- slippage_multiplier: {self._SLIPPAGE_MULTIPLIER:.2f}",
            "",
            "## Executive Summary",
            f"- eligible_closed_trades: {payload['sample_counts']['eligible_closed_trades']}",
            f"- execution_data_trades: {payload['sample_counts']['execution_data_trades']}",
            f"- estimate_only_trades: {payload['sample_counts']['estimate_only_trades']}",
            f"- latency_reference_trades: {payload['sample_counts'].get('latency_reference_trades', 0)}",
            f"- shock_regime_trades: {payload['sample_counts'].get('shock_regime_trades', 0)}",
            f"- stress_pass: {recommendation.get('stress_pass', False)}",
            f"- recommendation_reason: {recommendation.get('reason', 'not_available')}",
            f"- worst_scenario: {recommendation.get('worst_scenario', 'stressed_cost')}",
            f"- worst_scenario_source: {recommendation.get('worst_scenario_source', 'stressed_cost')}",
            f"- replay_gate_applied: {bool(recommendation.get('replay_gate_applied', False))}",
            f"- replay_gate_reason: {recommendation.get('replay_gate_reason', 'approximation_only')}",
            f"- divergence_gate_applied: {bool(recommendation.get('divergence_gate_applied', False))}",
            f"- divergence_problem_scenarios: {recommendation.get('divergence_problem_scenarios', [])}",
            f"- worst_divergence_scenario: {recommendation.get('worst_divergence_scenario')}",
            "",
            "## Comparison Table",
            (
                f"- baseline_cost: trades={int(baseline.get('trades', 0))}, ev={float(baseline.get('ev', 0.0)):.4f}, "
                f"p5={float(baseline.get('p5_ev', 0.0)):.4f}, p50={float(baseline.get('p50_ev', 0.0)):.4f}, "
                f"max_dd={float(baseline.get('max_drawdown', 0.0)):.4f}, ulcer={float(baseline.get('ulcer_index', 0.0)):.4f}, "
                f"forced_exit_ratio={float(baseline.get('forced_exit_ratio', 0.0)):.4f}, information_failure_ratio={float(baseline.get('information_failure_ratio', 0.0)):.4f}"
            ),
            (
                f"- stressed_cost: trades={int(stressed.get('trades', 0))}, ev={float(stressed.get('ev', 0.0)):.4f}, "
                f"p5={float(stressed.get('p5_ev', 0.0)):.4f}, p50={float(stressed.get('p50_ev', 0.0)):.4f}, "
                f"max_dd={float(stressed.get('max_drawdown', 0.0)):.4f}, ulcer={float(stressed.get('ulcer_index', 0.0)):.4f}, "
                f"forced_exit_ratio={float(stressed.get('forced_exit_ratio', 0.0)):.4f}, information_failure_ratio={float(stressed.get('information_failure_ratio', 0.0)):.4f}"
            ),
            (
                f"- delta(stressed - baseline): ev={float(comparison.get('ev', 0.0)):.4f}, "
                f"p5={float(comparison.get('p5_ev', 0.0)):.4f}, max_dd={float(comparison.get('max_drawdown', 0.0)):.4f}, "
                f"ulcer={float(comparison.get('ulcer_index', 0.0)):.4f}"
            ),
            "",
            "## Cost Summary",
            f"- baseline_cost_r avg/p50/p95/max: {cost_summary.get('baseline_cost_r', {}).get('avg', 0.0):.4f}/{cost_summary.get('baseline_cost_r', {}).get('p50', 0.0):.4f}/{cost_summary.get('baseline_cost_r', {}).get('p95', 0.0):.4f}/{cost_summary.get('baseline_cost_r', {}).get('max', 0.0):.4f}",
            f"- stressed_cost_r avg/p50/p95/max: {cost_summary.get('stressed_cost_r', {}).get('avg', 0.0):.4f}/{cost_summary.get('stressed_cost_r', {}).get('p50', 0.0):.4f}/{cost_summary.get('stressed_cost_r', {}).get('p95', 0.0):.4f}/{cost_summary.get('stressed_cost_r', {}).get('max', 0.0):.4f}",
            f"- incremental_cost_r avg/p50/p95/max: {cost_summary.get('incremental_cost_r', {}).get('avg', 0.0):.4f}/{cost_summary.get('incremental_cost_r', {}).get('p50', 0.0):.4f}/{cost_summary.get('incremental_cost_r', {}).get('p95', 0.0):.4f}/{cost_summary.get('incremental_cost_r', {}).get('max', 0.0):.4f}",
            f"- fee_component_r avg/p50/p95/max: {cost_summary.get('fee_component_r', {}).get('avg', 0.0):.4f}/{cost_summary.get('fee_component_r', {}).get('p50', 0.0):.4f}/{cost_summary.get('fee_component_r', {}).get('p95', 0.0):.4f}/{cost_summary.get('fee_component_r', {}).get('max', 0.0):.4f}",
            f"- slippage_component_r avg/p50/p95/max: {cost_summary.get('slippage_component_r', {}).get('avg', 0.0):.4f}/{cost_summary.get('slippage_component_r', {}).get('p50', 0.0):.4f}/{cost_summary.get('slippage_component_r', {}).get('p95', 0.0):.4f}/{cost_summary.get('slippage_component_r', {}).get('max', 0.0):.4f}",
            f"- cost_source_counts: {payload.get('cost_source_counts', {})}",
            "",
            "## Additional Stress Scenarios",
        ]
        for scenario_name in ("latency_plus_1_bar", "partial_fills_only", "shock_concentration"):
            metrics = dict(scenario_metrics.get(scenario_name) or {})
            delta = dict(scenario_comparison.get(scenario_name) or {})
            status = dict(scenario_statuses.get(scenario_name) or {})
            replay_row = dict((replay_output_artifacts.get("scenario_outputs") or {}).get(scenario_name) or {})
            replay_summary = dict(replay_row.get("summary") or {})
            replay_delta = dict(replay_output_comparison.get(scenario_name) or replay_row.get("comparison_to_approximation") or {})
            effective_metrics = replay_summary if status.get("source") == "replay_output" and replay_summary else metrics
            effective_delta = self._base._delta(baseline, effective_metrics)
            lines.append(
                f"- {scenario_name}: status={status.get('status', 'n/a')}, source={status.get('source', 'approximation')}, "
                f"reason={status.get('reason', 'n/a')}, "
                f"trades={int(effective_metrics.get('trades', 0))}, ev={float(effective_metrics.get('ev', 0.0)):.4f}, "
                f"p5={float(effective_metrics.get('p5_ev', 0.0)):.4f}, max_dd={float(effective_metrics.get('max_drawdown', 0.0)):.4f}, "
                f"delta_ev={float((replay_delta if status.get('source') == 'replay_output' else delta).get('ev', effective_delta.get('ev', 0.0))):.4f}, "
                f"delta_max_dd={float((replay_delta if status.get('source') == 'replay_output' else delta).get('max_drawdown', effective_delta.get('max_drawdown', 0.0))):.4f}"
            )
            if replay_row:
                lines.append(
                    f"  replay_output: available={bool(replay_row.get('available', False))}, "
                    f"reason={replay_row.get('reason', 'not_available')}, "
                    f"replay_ev={float(replay_summary.get('ev', 0.0)):.4f}, "
                    f"replay_max_dd={float(replay_summary.get('max_drawdown', 0.0)):.4f}, "
                    f"divergence_status={status.get('divergence_status', 'PASS')}, "
                    f"divergence_reason={status.get('divergence_reason', 'within_divergence_threshold')}, "
                    f"delta_replay_minus_approx_ev={float(replay_delta.get('ev', 0.0)):.4f}, "
                    f"delta_replay_minus_approx_max_dd={float(replay_delta.get('max_drawdown', 0.0)):.4f}"
                )
        lines.extend(
            [
                f"- latency_penalty_r avg/p50/p95/max: {scenario_summary.get('latency_penalty_r', {}).get('avg', 0.0):.4f}/{scenario_summary.get('latency_penalty_r', {}).get('p50', 0.0):.4f}/{scenario_summary.get('latency_penalty_r', {}).get('p95', 0.0):.4f}/{scenario_summary.get('latency_penalty_r', {}).get('max', 0.0):.4f}",
                f"- partial_fill_factor avg/p50/p95/max: {scenario_summary.get('partial_fill_factor', {}).get('avg', 0.0):.4f}/{scenario_summary.get('partial_fill_factor', {}).get('p50', 0.0):.4f}/{scenario_summary.get('partial_fill_factor', {}).get('p95', 0.0):.4f}/{scenario_summary.get('partial_fill_factor', {}).get('max', 0.0):.4f}",
                f"- shock_factor avg/p50/p95/max: {scenario_summary.get('shock_factor', {}).get('avg', 0.0):.4f}/{scenario_summary.get('shock_factor', {}).get('p50', 0.0):.4f}/{scenario_summary.get('shock_factor', {}).get('p95', 0.0):.4f}/{scenario_summary.get('shock_factor', {}).get('max', 0.0):.4f}",
                f"- latency_source_counts: {payload.get('latency_source_counts', {})}",
                "",
                "## Replay Output Artifacts",
                f"- available: {bool(replay_output_artifacts.get('available', False))}",
                f"- comparison_ready: {bool(replay_output_artifacts.get('comparison_ready', False))}",
                f"- reason: {replay_output_artifacts.get('reason', 'not_available')}",
                f"- summary_counts: {replay_output_artifacts.get('summary_counts', {})}",
                "",
            "## Deployment Recommendation",
            f"- stress_pass: {recommendation.get('stress_pass', False)}",
            f"- catastrophic_loss_detected: {recommendation.get('catastrophic_loss_detected', False)}",
            f"- worst_scenario: {recommendation.get('worst_scenario', 'stressed_cost')}",
            f"- worst_scenario_source: {recommendation.get('worst_scenario_source', 'stressed_cost')}",
            f"- replay_gate_applied: {bool(recommendation.get('replay_gate_applied', False))}",
            f"- replay_gate_reason: {recommendation.get('replay_gate_reason', 'approximation_only')}",
            f"- divergence_gate_applied: {bool(recommendation.get('divergence_gate_applied', False))}",
            f"- divergence_problem_scenarios: {recommendation.get('divergence_problem_scenarios', [])}",
            f"- worst_divergence_scenario: {recommendation.get('worst_divergence_scenario')}",
            f"- stressed_drawdown_limit_r: {recommendation.get('stressed_drawdown_limit_r', self._CATASTROPHIC_DRAWDOWN_R):.2f}",
            "",
            "## Notes",
            "- Current approximation starts from saved closed v2 realized R and deducts baseline/stressed cost in R-units.",
            "- execution_fills is preferred for actual fee and entry slippage; missing trades fall back to plan.cost_est decomposition.",
            "- latency +1 bar uses the next available 5m candle open and only applies directional adverse move as penalty.",
            "- partial fills only currently assumes a fixed 50% fill ratio in R-units.",
            "- shock concentration currently amplifies loss impact and compresses upside on trades tagged with regime=shock.",
            "- This comparison is a stress approximation, not a full order-book replay.",
            "",
            ]
        )
        file_path.write_text("\n".join(lines), encoding="utf-8")
        return str(file_path)

    def _attach_replay_output_artifacts(
        self,
        *,
        payload: dict[str, Any],
        stress_replay_output_artifacts: dict[str, Any] | None,
    ) -> dict[str, Any]:
        out = dict(payload)
        replay_payload = dict(stress_replay_output_artifacts or {})
        out["replay_output_artifacts"] = {
            "available": bool(replay_payload.get("available", False)),
            "comparison_ready": bool(replay_payload.get("comparison_ready", False)),
            "reason": replay_payload.get("reason", "not_available"),
            "summary_counts": dict(replay_payload.get("summary_counts") or {}),
            "lineage_summary": dict(replay_payload.get("lineage_summary") or {}),
            "scenario_outputs": dict(replay_payload.get("scenario_outputs") or {}),
            "report_path": replay_payload.get("report_path"),
        }
        out["replay_output_comparison"] = dict(replay_payload.get("comparison_to_approximation") or {})
        out["deployment_recommendation"] = self._effective_recommendation_with_replay_gate(payload=out)
        return out

    def attach_replay_output_artifacts(
        self,
        *,
        payload: dict[str, Any],
        stress_replay_output_artifacts: dict[str, Any] | None,
        write_report: bool = True,
    ) -> dict[str, Any]:
        enriched = self._attach_replay_output_artifacts(
            payload=payload,
            stress_replay_output_artifacts=stress_replay_output_artifacts,
        )
        if write_report:
            generated_at = self._parse_ts(enriched.get("generated_at")) or datetime.now(timezone.utc)
            enriched["report_path"] = self._write_report(payload=enriched, now=generated_at)
        return enriched

    def generate(
        self,
        *,
        symbol: str,
        version: str,
        plans: list[Any],
        stress_replay_output_artifacts: dict[str, Any] | None = None,
        write_report: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        fill_map = self._fill_map(plans)
        adjusted_records: list[StressAdjustedTradeRecord] = []
        cost_source_counts: dict[str, int] = {}
        latency_source_counts: dict[str, int] = {}
        baseline_costs: list[float] = []
        stressed_costs: list[float] = []
        incremental_costs: list[float] = []
        fee_components: list[float] = []
        slippage_components: list[float] = []
        latency_penalties: list[float] = []
        partial_fill_factors: list[float] = []
        shock_factors: list[float] = []
        shock_regime_trades = 0

        for plan in plans:
            record = self._base._closed_trade(plan, symbol=symbol, version=version)
            if record is None:
                continue
            adjusted = self._adjust_trade(
                plan=plan,
                record=record,
                fills=fill_map.get(record.plan_id, []),
            )
            adjusted_records.append(adjusted)
            cost_source_counts[adjusted.cost_source] = int(cost_source_counts.get(adjusted.cost_source, 0)) + 1
            latency_source_counts[adjusted.latency_source] = int(latency_source_counts.get(adjusted.latency_source, 0)) + 1
            baseline_costs.append(adjusted.baseline_cost_r)
            stressed_costs.append(adjusted.stressed_cost_r)
            incremental_costs.append(round(adjusted.stressed_cost_r - adjusted.baseline_cost_r, 4))
            fee_components.append(adjusted.fee_component_r)
            slippage_components.append(adjusted.slippage_component_r)
            latency_penalties.append(adjusted.latency_penalty_r)
            partial_fill_factors.append(adjusted.partial_fill_factor)
            shock_factors.append(adjusted.shock_factor)
            if adjusted.regime == "shock":
                shock_regime_trades += 1

        adjusted_records.sort(key=lambda item: item.base.closed_ts)
        baseline_metrics = self._metrics(adjusted_records, mode="baseline")
        stressed_metrics = self._metrics(adjusted_records, mode="stressed")
        comparison = self._base._delta(baseline_metrics, stressed_metrics)
        scenario_metrics = {
            "latency_plus_1_bar": self._metrics(adjusted_records, mode="latency_plus_1_bar"),
            "partial_fills_only": self._metrics(adjusted_records, mode="partial_fills_only"),
            "shock_concentration": self._metrics(adjusted_records, mode="shock_concentration"),
        }
        scenario_comparison = {
            name: self._base._delta(baseline_metrics, metrics)
            for name, metrics in scenario_metrics.items()
        }
        base_recommendation = self._recommendation(baseline=baseline_metrics, stressed=stressed_metrics)
        recommendation = self._scenario_recommendation(
            base_recommendation=base_recommendation,
            scenario_metrics=scenario_metrics,
        )

        payload: dict[str, Any] = {
            "schema_version": "strategy_v2_stress_validation_v2",
            "symbol": symbol,
            "version": version,
            "generated_at": now.isoformat(),
            "available": bool(adjusted_records),
            "reason": "ok" if adjusted_records else "no_closed_v2_trades",
            "comparison_axis": "baseline_vs_stressed_cost",
            "stress_multipliers": {
                "cost": self._COST_MULTIPLIER,
                "slippage": self._SLIPPAGE_MULTIPLIER,
            },
            "sample_counts": {
                "eligible_closed_trades": len(adjusted_records),
                "execution_data_trades": int(cost_source_counts.get("execution_fills", 0)),
                "estimate_only_trades": int(cost_source_counts.get("plan_cost_est", 0)),
                "latency_reference_trades": len(adjusted_records),
                "shock_regime_trades": shock_regime_trades,
            },
            "cost_source_counts": dict(sorted(cost_source_counts.items())),
            "latency_source_counts": dict(sorted(latency_source_counts.items())),
            "cost_summary": {
                "baseline_cost_r": self._summary(baseline_costs),
                "stressed_cost_r": self._summary(stressed_costs),
                "incremental_cost_r": self._summary(incremental_costs),
                "fee_component_r": self._summary(fee_components),
                "slippage_component_r": self._summary(slippage_components),
            },
            "scenario_summary": {
                "latency_penalty_r": self._summary(latency_penalties),
                "partial_fill_factor": self._summary(partial_fill_factors),
                "shock_factor": self._summary(shock_factors),
            },
            "stress_metrics": {
                "baseline_cost": baseline_metrics,
                "stressed_cost": stressed_metrics,
            },
            "comparison": comparison,
            "scenario_metrics": scenario_metrics,
            "scenario_comparison": scenario_comparison,
            "deployment_recommendation": recommendation,
            "report_path": None,
        }
        payload = self._attach_replay_output_artifacts(
            payload=payload,
            stress_replay_output_artifacts=stress_replay_output_artifacts,
        )
        if write_report:
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload
