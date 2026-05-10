from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.services.report_io import atomic_write_text
from app.services.strategy_v2_validation import ClosedTradeRecord, StrategyV2ValidationService


@dataclass(slots=True)
class LockAdjustedTradeRecord:
    base: ClosedTradeRecord
    adjusted_realized_r: float
    lock_factor: float
    impact_reason: str
    regime: str
    transition_state: str
    reaction_classification: str
    entry_model: str


class StrategyV2LockValidationService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._base = StrategyV2ValidationService(self.settings)

    @staticmethod
    def _exit_reasons(records: list[LockAdjustedTradeRecord]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in records:
            counts[record.base.exit_reason] = int(counts.get(record.base.exit_reason, 0)) + 1
        return dict(sorted(counts.items()))

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        if value in (None, "", "None"):
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if isfinite(parsed) else default

    def _before_metrics(self, records: list[ClosedTradeRecord]) -> dict[str, Any]:
        return self._base._mode_metrics(records)

    def _after_metrics(self, records: list[LockAdjustedTradeRecord]) -> dict[str, Any]:
        transformed = [
            ClosedTradeRecord(
                plan_id=record.base.plan_id,
                symbol=record.base.symbol,
                closed_ts=record.base.closed_ts,
                realized_r=record.adjusted_realized_r,
                held_bars=record.base.held_bars,
                exit_reason=record.base.exit_reason,
                regime=record.base.regime,
                strategy_family=record.base.strategy_family,
                strategy_grade=record.base.strategy_grade,
                strategy_version=record.base.strategy_version,
            )
            for record in records
        ]
        metrics = self._base._mode_metrics(transformed)
        metrics["impact_reasons"] = self._impact_reason_counts(records)
        metrics["raw_exit_reasons"] = self._exit_reasons(records)
        return metrics

    @staticmethod
    def _impact_reason_counts(records: list[LockAdjustedTradeRecord]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in records:
            counts[record.impact_reason] = int(counts.get(record.impact_reason, 0)) + 1
        return dict(sorted(counts.items()))

    def _adjust_trade(self, plan: Any, record: ClosedTradeRecord) -> tuple[LockAdjustedTradeRecord | None, str | None]:
        validity = dict(getattr(plan, "validity", {}) or {})
        regime = str(validity.get("regime") or "range").lower()
        transition_state = str(validity.get("transition_state") or "none").lower()
        reaction = str(validity.get("reaction_classification") or "not_available").lower()
        family = str(validity.get("strategy_family") or record.strategy_family or "legacy_zone_plan")
        grade = str(validity.get("strategy_grade") or record.strategy_grade or "").upper()
        entry_model = str(getattr(plan, "entry_model", validity.get("entry_model", "CONFIRM")) or "CONFIRM").upper()

        if transition_state == "transition_confirmed":
            return None, "transition_confirmed_block"
        if transition_state == "transition_watch" or regime == "transition":
            return None, "transition_zero_risk_block"
        if regime == "shock":
            if family == "sweep_reversal" and not (grade == "A" and reaction == "rejection_confirmed"):
                return None, "shock_requires_a_grade_rejection_block"
            shock_factor = self._safe_float(self.settings.sizing_regime_factor_shock, default=0.4)
            return (
                LockAdjustedTradeRecord(
                    base=record,
                    adjusted_realized_r=round(float(record.realized_r) * shock_factor, 4),
                    lock_factor=shock_factor,
                    impact_reason="shock_size_clamp",
                    regime=regime,
                    transition_state=transition_state,
                    reaction_classification=reaction,
                    entry_model=entry_model,
                ),
                None,
            )
        return (
            LockAdjustedTradeRecord(
                base=record,
                adjusted_realized_r=float(record.realized_r),
                lock_factor=1.0,
                impact_reason="no_lock_adjustment",
                regime=regime,
                transition_state=transition_state,
                reaction_classification=reaction,
                entry_model=entry_model,
            ),
            None,
        )

    @staticmethod
    def _recommendation(before: dict[str, Any], after: dict[str, Any], impact_counts: dict[str, int]) -> dict[str, Any]:
        downside_improved = (
            float(after.get("p5_ev", 0.0)) >= float(before.get("p5_ev", 0.0))
            and float(after.get("max_drawdown", 0.0)) <= float(before.get("max_drawdown", 0.0))
            and float(after.get("ulcer_index", 0.0)) <= float(before.get("ulcer_index", 0.0))
        )
        reason = "lock_downside_improved" if downside_improved else "lock_not_clearly_better"
        if int(impact_counts.get("transition_confirmed_block", 0)) + int(impact_counts.get("transition_zero_risk_block", 0)) == 0:
            reason = "no_transition_samples"
        return {
            "keep_lock_enabled": True,
            "downside_improved": bool(downside_improved),
            "reason": reason,
        }

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.validation_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / (
            f"strategy_v2_lock_validation_{payload['symbol']}_{payload['version']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        )

        before = dict((payload.get("lock_metrics") or {}).get("before_lock") or {})
        after = dict((payload.get("lock_metrics") or {}).get("after_lock") or {})
        comparison = dict(payload.get("comparison") or {})
        impact_counts = dict(payload.get("impact_counts") or {})
        recommendation = dict(payload.get("deployment_recommendation") or {})
        lines = [
            f"# Strategy v2 Transition/Shock Lock Validation: {payload['symbol']}",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- strategy_version: {payload['version']}",
            f"- available: {payload['available']}",
            f"- reason: {payload['reason']}",
            "",
            "## Executive Summary",
            f"- eligible_closed_trades: {payload['sample_counts']['eligible_closed_trades']}",
            f"- after_lock_trades: {payload['sample_counts']['after_lock_trades']}",
            f"- blocked_transition_trades: {payload['sample_counts']['blocked_transition_trades']}",
            f"- blocked_shock_trades: {payload['sample_counts']['blocked_shock_trades']}",
            f"- shock_clamped_trades: {payload['sample_counts']['shock_clamped_trades']}",
            f"- keep_lock_enabled: {recommendation.get('keep_lock_enabled', True)}",
            f"- recommendation_reason: {recommendation.get('reason', 'not_available')}",
            "",
            "## Comparison Table",
            (
                f"- before_lock: trades={int(before.get('trades', 0))}, ev={float(before.get('ev', 0.0)):.4f}, "
                f"p5={float(before.get('p5_ev', 0.0)):.4f}, p50={float(before.get('p50_ev', 0.0)):.4f}, "
                f"max_dd={float(before.get('max_drawdown', 0.0)):.4f}, ulcer={float(before.get('ulcer_index', 0.0)):.4f}, "
                f"avg_hold_bars={float(before.get('avg_hold_bars', 0.0)):.2f}, forced_exit_ratio={float(before.get('forced_exit_ratio', 0.0)):.4f}, "
                f"information_failure_ratio={float(before.get('information_failure_ratio', 0.0)):.4f}"
            ),
            (
                f"- after_lock: trades={int(after.get('trades', 0))}, ev={float(after.get('ev', 0.0)):.4f}, "
                f"p5={float(after.get('p5_ev', 0.0)):.4f}, p50={float(after.get('p50_ev', 0.0)):.4f}, "
                f"max_dd={float(after.get('max_drawdown', 0.0)):.4f}, ulcer={float(after.get('ulcer_index', 0.0)):.4f}, "
                f"avg_hold_bars={float(after.get('avg_hold_bars', 0.0)):.2f}, forced_exit_ratio={float(after.get('forced_exit_ratio', 0.0)):.4f}, "
                f"information_failure_ratio={float(after.get('information_failure_ratio', 0.0)):.4f}"
            ),
            (
                f"- delta(after - before): trades={float(comparison.get('trades', 0.0)):.4f}, ev={float(comparison.get('ev', 0.0)):.4f}, "
                f"p5={float(comparison.get('p5_ev', 0.0)):.4f}, max_dd={float(comparison.get('max_drawdown', 0.0)):.4f}, "
                f"ulcer={float(comparison.get('ulcer_index', 0.0)):.4f}"
            ),
            "",
            "## Impact Breakdown",
            f"- impact_counts: {impact_counts}",
            f"- after_lock impact_reasons: {after.get('impact_reasons', {})}",
            "",
            "## Deployment Recommendation",
            f"- keep_lock_enabled: {recommendation.get('keep_lock_enabled', True)}",
            f"- downside_improved: {recommendation.get('downside_improved', False)}",
            "",
            "## Notes",
            "- Current approximation applies the runtime lock contract available in saved plan metadata.",
            "- Transition lock removes trades; shock lock clamps realized R by the current shock regime factor.",
            "",
        ]
        atomic_write_text(file_path, "\n".join(lines))
        return str(file_path)

    def generate(self, *, symbol: str, version: str, plans: list[Any], write_report: bool = True) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)

        before_records: list[ClosedTradeRecord] = []
        after_records: list[LockAdjustedTradeRecord] = []
        impact_counts: dict[str, int] = {}
        shock_clamped = 0
        blocked_transition = 0
        blocked_shock = 0

        for plan in plans:
            record = self._base._closed_trade(plan, symbol=symbol, version=version)
            if record is None:
                continue
            before_records.append(record)
            adjusted, blocked_reason = self._adjust_trade(plan, record)
            if blocked_reason:
                impact_counts[blocked_reason] = int(impact_counts.get(blocked_reason, 0)) + 1
                if blocked_reason.startswith("transition_"):
                    blocked_transition += 1
                elif blocked_reason.startswith("shock_"):
                    blocked_shock += 1
                continue
            if adjusted is None:
                continue
            after_records.append(adjusted)
            impact_counts[adjusted.impact_reason] = int(impact_counts.get(adjusted.impact_reason, 0)) + 1
            if adjusted.impact_reason == "shock_size_clamp":
                shock_clamped += 1

        before_records.sort(key=lambda item: item.closed_ts)
        after_records.sort(key=lambda item: item.base.closed_ts)

        available = bool(before_records)
        reason = "ok" if available else "no_closed_v2_trades"
        before_metrics = self._before_metrics(before_records)
        after_metrics = self._after_metrics(after_records)
        comparison = self._base._delta(before_metrics, after_metrics)
        recommendation = self._recommendation(before_metrics, after_metrics, impact_counts)

        payload: dict[str, Any] = {
            "schema_version": "strategy_v2_lock_validation_v1",
            "symbol": symbol,
            "version": version,
            "generated_at": now.isoformat(),
            "available": available,
            "reason": reason,
            "comparison_axis": "transition_shock_lock",
            "sample_counts": {
                "eligible_closed_trades": len(before_records),
                "after_lock_trades": len(after_records),
                "blocked_transition_trades": blocked_transition,
                "blocked_shock_trades": blocked_shock,
                "shock_clamped_trades": shock_clamped,
            },
            "impact_counts": dict(sorted(impact_counts.items())),
            "lock_metrics": {
                "before_lock": before_metrics,
                "after_lock": after_metrics,
            },
            "comparison": comparison,
            "deployment_recommendation": recommendation,
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload
