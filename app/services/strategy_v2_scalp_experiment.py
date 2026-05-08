from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.db.models import Candle, Zone
from app.services.candidate_expectations import expectation_contract
from app.services.context_engine import ContextEngine
from app.services.micro_main_strategy_research import build_session_impulse_retest_shadow_summary
from app.services.plan_generator import PlanGenerator, RankedPlan
from app.services.zone_engine import ZoneEngine


class StrategyV2ScalpExperimentService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        context_engine: ContextEngine | None = None,
        zone_engine: ZoneEngine | None = None,
        plan_generator: PlanGenerator | None = None,
    ):
        self.settings = settings or get_settings()
        self.context_engine = context_engine or ContextEngine()
        self.zone_engine = zone_engine or ZoneEngine()
        self.plan_generator = plan_generator or PlanGenerator()

    @staticmethod
    def _top_plan_summary(ranked_plans: list[RankedPlan]) -> dict[str, Any] | None:
        if not ranked_plans:
            return None
        top = ranked_plans[0]
        plan = top.plan
        validity = dict(plan.validity or {})
        expectations = expectation_contract(
            validity=validity,
            ev=float(plan.ev),
            recommended_risk_r=float(validity.get("recommended_risk_r", 0.0) or 0.0),
        )
        return {
            "plan_id": plan.plan_id,
            "direction": plan.direction,
            "entry_model": str(plan.entry_model),
            "strategy_family": str(validity.get("strategy_family") or "legacy_zone_plan"),
            "strategy_grade": validity.get("strategy_grade"),
            "expected_win_prob": expectations["expected_win_prob"],
            "expected_ev_r": expectations["expected_ev_r"],
            "expected_ev_at_recommended_size_r": expectations["expected_ev_at_recommended_size_r"],
            "recommended_risk_r": round(float(validity.get("recommended_risk_r", 0.0) or 0.0), 4),
            "expected_summary": expectations["expected_summary"],
            "final_rank_score": round(float(top.final_rank_score), 4),
            "friction_penalty": round(float(top.friction_penalty), 4),
        }

    @staticmethod
    def _zone_summary(zones: list[Zone]) -> dict[str, Any]:
        active = [zone for zone in zones if zone.state != "expired"]
        quality_sorted = sorted(active, key=lambda zone: (float(zone.quality), float(zone.base_strength)), reverse=True)
        top = quality_sorted[0] if quality_sorted else None
        return {
            "zone_count": len(active),
            "top_zone_id": top.zone_id if top else None,
            "top_zone_type": top.type if top else None,
            "top_zone_quality": round(float(top.quality), 4) if top else 0.0,
            "avg_quality": round(
                sum(float(zone.quality) for zone in active) / max(len(active), 1),
                4,
            )
            if active
            else 0.0,
        }

    @staticmethod
    def _branch_summary(
        *,
        zone_timeframe: str,
        execution_timeframe: str,
        context: Any,
        zones: list[Zone],
        ranked_plans: list[RankedPlan],
    ) -> dict[str, Any]:
        top_plan = StrategyV2ScalpExperimentService._top_plan_summary(ranked_plans)
        return {
            "zone_timeframe": zone_timeframe,
            "execution_timeframe": execution_timeframe,
            "regime_label": getattr(context, "regime_label", "unknown"),
            "transition_state": getattr(context, "transition_state", "none"),
            "jump_rate": round(float(getattr(context, "jump_rate_5m", 0.0) or 0.0), 4),
            "friction": round(float(getattr(context, "friction_5m", 0.0) or 0.0), 4),
            "zone_summary": StrategyV2ScalpExperimentService._zone_summary(zones),
            "plan_count": len(ranked_plans),
            "top_plan": top_plan,
        }

    @staticmethod
    def _preference_reason(*, baseline_top: dict[str, Any] | None, experiment_top: dict[str, Any] | None) -> tuple[str, str]:
        if baseline_top is None and experiment_top is None:
            return "none", "no_ranked_plans_in_either_branch"
        if baseline_top is None:
            return "experiment", "experiment_only_has_ranked_plan"
        if experiment_top is None:
            return "baseline", "baseline_only_has_ranked_plan"

        baseline_ev = float(baseline_top.get("expected_ev_at_recommended_size_r", 0.0))
        experiment_ev = float(experiment_top.get("expected_ev_at_recommended_size_r", 0.0))
        if experiment_ev > baseline_ev + 0.01:
            return "experiment", "experiment_has_higher_sized_ev"
        if baseline_ev > experiment_ev + 0.01:
            return "baseline", "baseline_has_higher_sized_ev"

        baseline_win = float(baseline_top.get("expected_win_prob", 0.0))
        experiment_win = float(experiment_top.get("expected_win_prob", 0.0))
        if experiment_win > baseline_win + 0.01:
            return "experiment", "experiment_has_higher_win_probability"
        if baseline_win > experiment_win + 0.01:
            return "baseline", "baseline_has_higher_win_probability"
        return "baseline", "baseline_default_tie_break"

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.validation_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / (
            f"strategy_v2_scalp_experiment_{payload['symbol']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        )
        baseline = dict(payload.get("baseline") or {})
        experiment = dict(payload.get("experiment") or {})
        comparison = dict(payload.get("comparison") or {})
        micro_shadow = dict(payload.get("micro_main_shadow") or {})
        lines = [
            f"# Strategy v2 Scalp Experiment: {payload['symbol']}",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- available: {payload['available']}",
            f"- reason: {payload['reason']}",
            "",
            "## Sample Counts",
            f"- candles_1m: {int((payload.get('sample_counts') or {}).get('candles_1m', 0))}",
            f"- candles_5m: {int((payload.get('sample_counts') or {}).get('candles_5m', 0))}",
            f"- candles_15m: {int((payload.get('sample_counts') or {}).get('candles_15m', 0))}",
            "",
            "## Baseline (15m zone / 5m execution)",
            f"- regime: {baseline.get('regime_label', 'unknown')}",
            f"- transition_state: {baseline.get('transition_state', 'none')}",
            f"- zone_count: {int(dict(baseline.get('zone_summary') or {}).get('zone_count', 0))}",
            f"- plan_count: {int(baseline.get('plan_count', 0))}",
            f"- top_plan: {baseline.get('top_plan')}",
            "",
            "## Experiment (5m zone / 1m execution)",
            f"- regime: {experiment.get('regime_label', 'unknown')}",
            f"- transition_state: {experiment.get('transition_state', 'none')}",
            f"- zone_count: {int(dict(experiment.get('zone_summary') or {}).get('zone_count', 0))}",
            f"- plan_count: {int(experiment.get('plan_count', 0))}",
            f"- top_plan: {experiment.get('top_plan')}",
            "",
            "## Comparison",
            f"- preferred_branch: {comparison.get('preferred_branch', 'none')}",
            f"- recommendation_reason: {comparison.get('recommendation_reason', 'not_available')}",
            f"- delta_top_expected_ev_at_size_r: {float(comparison.get('delta_top_expected_ev_at_size_r', 0.0)):+.4f}",
            f"- delta_top_expected_win_prob: {float(comparison.get('delta_top_expected_win_prob', 0.0)):+.4f}",
            "",
            "## Session Impulse Retest (shadow)",
            f"- enabled: {bool(micro_shadow.get('enabled', False))}",
            f"- available: {bool(micro_shadow.get('available', False))}",
            f"- status: {micro_shadow.get('status', 'not_available')}",
            f"- decision: {micro_shadow.get('decision', 'REJECT')}",
            f"- recent_closed: {int(micro_shadow.get('recent_closed', 0) or 0)}",
            f"- ev_r: {float(micro_shadow.get('ev_r', 0.0) or 0.0):+.4f}",
            f"- total_r: {float(micro_shadow.get('total_r', 0.0) or 0.0):+.4f}",
            f"- recent_window_hours: {float(micro_shadow.get('recent_window_hours', 0.0) or 0.0):.2f}",
            f"- latest_trade: {micro_shadow.get('latest_trade')}",
            "",
            "## Next Steps",
        ]
        for step in payload.get("next_steps") or []:
            lines.append(f"- {step}")
        lines.append("")
        file_path.write_text("\n".join(lines), encoding="utf-8")
        return str(file_path)

    def generate(
        self,
        *,
        symbol: str,
        candles_1m: list[Candle],
        candles_5m: list[Candle],
        candles_15m: list[Candle],
        write_report: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        blocked_by: list[str] = []
        if len(candles_1m) < 180:
            blocked_by.append("insufficient_1m_candles")
        if len(candles_5m) < 120:
            blocked_by.append("insufficient_5m_candles")
        if len(candles_15m) < 60:
            blocked_by.append("insufficient_15m_candles")

        available = not blocked_by
        payload: dict[str, Any] = {
            "schema_version": "strategy_v2_scalp_experiment_v1",
            "symbol": symbol,
            "generated_at": now.isoformat(),
            "available": available,
            "reason": "ok" if available else "insufficient_candles",
            "evaluation_basis": "baseline(15m zone / 5m execution) vs experiment(5m zone / 1m execution)",
            "sample_counts": {
                "candles_1m": len(candles_1m),
                "candles_5m": len(candles_5m),
                "candles_15m": len(candles_15m),
            },
            "baseline": {},
            "experiment": {},
            "comparison": {
                "preferred_branch": "none",
                "recommendation_reason": "not_available",
                "delta_top_expected_ev_at_size_r": 0.0,
                "delta_top_expected_win_prob": 0.0,
            },
            "micro_main_shadow": build_session_impulse_retest_shadow_summary(
                symbol=symbol,
                candles_1m=candles_1m,
                candles_5m=candles_5m,
                enabled=bool(self.settings.session_impulse_retest_enabled),
                shadow_only=bool(self.settings.session_impulse_retest_shadow_only),
                allowed_symbols=[
                    item.strip().upper()
                    for item in str(self.settings.session_impulse_retest_allowed_symbols or "").split(",")
                    if item.strip()
                ],
            ),
            "blocked_by": blocked_by,
            "next_steps": [],
            "report_path": None,
        }

        if available:
            branch_now = candles_1m[-1].ts if candles_1m[-1].ts.tzinfo else candles_1m[-1].ts.replace(tzinfo=timezone.utc)
            baseline_context = self.context_engine.build_snapshot(symbol=symbol, candles_5m=candles_5m, candles_15m=candles_15m)
            baseline_zones = [zone for zone in self.zone_engine.refresh(symbol=symbol, candles_15m=candles_15m, existing=[]) if zone.state != "expired"]
            baseline_ranked = self.plan_generator.generate(
                symbol=symbol,
                zones=baseline_zones,
                context=baseline_context,
                candles_5m=candles_5m,
                active_thesis_clusters=0,
                now=branch_now,
            )

            experiment_context = self.context_engine.build_snapshot(symbol=symbol, candles_5m=candles_1m, candles_15m=candles_5m)
            experiment_zones = self.zone_engine.refresh(symbol=symbol, candles_15m=candles_5m, existing=[])
            for zone in experiment_zones:
                zone.timeframe = "5m"
            experiment_zones = [zone for zone in experiment_zones if zone.state != "expired"]
            experiment_ranked = self.plan_generator.generate(
                symbol=symbol,
                zones=experiment_zones,
                context=experiment_context,
                candles_5m=candles_1m,
                active_thesis_clusters=0,
                now=branch_now,
            )

            baseline_summary = self._branch_summary(
                zone_timeframe="15m",
                execution_timeframe="5m",
                context=baseline_context,
                zones=baseline_zones,
                ranked_plans=baseline_ranked,
            )
            experiment_summary = self._branch_summary(
                zone_timeframe="5m",
                execution_timeframe="1m",
                context=experiment_context,
                zones=experiment_zones,
                ranked_plans=experiment_ranked,
            )
            preferred_branch, recommendation_reason = self._preference_reason(
                baseline_top=baseline_summary.get("top_plan"),
                experiment_top=experiment_summary.get("top_plan"),
            )
            baseline_top = dict(baseline_summary.get("top_plan") or {})
            experiment_top = dict(experiment_summary.get("top_plan") or {})
            payload["baseline"] = baseline_summary
            payload["experiment"] = experiment_summary
            payload["comparison"] = {
                "preferred_branch": preferred_branch,
                "recommendation_reason": recommendation_reason,
                "delta_top_expected_ev_at_size_r": round(
                    float(experiment_top.get("expected_ev_at_recommended_size_r", 0.0))
                    - float(baseline_top.get("expected_ev_at_recommended_size_r", 0.0)),
                    4,
                ),
                "delta_top_expected_win_prob": round(
                    float(experiment_top.get("expected_win_prob", 0.0))
                    - float(baseline_top.get("expected_win_prob", 0.0)),
                    4,
                ),
                "baseline_top_plan_id": baseline_top.get("plan_id"),
                "experiment_top_plan_id": experiment_top.get("plan_id"),
            }
            payload["next_steps"] = [
                "sync 1m candles before trusting the experiment branch live",
                "treat the 5m/1m branch as compare-only until execution-quality samples exist",
                "promote experiment only if top expected EV at recommended size stays better across multiple sessions",
            ]
        else:
            payload["next_steps"] = [
                "sync 1m candles with /internal/binance/sync?limit_1m=...",
                "keep baseline 15m/5m branch as source-of-truth until experiment coverage exists",
            ]

        if write_report:
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload
