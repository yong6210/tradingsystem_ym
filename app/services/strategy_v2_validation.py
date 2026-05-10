from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.enums import ExitReason, PlanState, StrategyMode
from app.db.models import Plan
from app.services.report_io import atomic_write_text
from app.services.session_guidance import SessionGuidanceService
from app.services.strategy_mode import StrategyModeService

_TARGET_EXIT_REASONS = {
    ExitReason.TARGET_TP1.value,
    ExitReason.TARGET_TP2.value,
    ExitReason.TARGET_TP3.value,
}


@dataclass(slots=True)
class ClosedTradeRecord:
    plan_id: str
    symbol: str
    closed_ts: datetime
    realized_r: float
    held_bars: int
    exit_reason: str
    regime: str
    strategy_family: str
    strategy_grade: str
    strategy_version: str


class StrategyV2ValidationService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.mode = StrategyModeService(self.settings)
        self.session_guidance = SessionGuidanceService(self.settings)

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _safe_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "y", "on"}:
                return True
            if normalized in {"0", "false", "no", "n", "off", "none", "null", ""}:
                return False
        return True if value else False

    @staticmethod
    def _parse_ts(value: Any) -> datetime | None:
        if value in {None, ""}:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _quantile(values: list[float], q: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(float(value) for value in values)
        idx = max(0, min(len(ordered) - 1, int(q * (len(ordered) - 1))))
        return float(ordered[idx])

    @staticmethod
    def _drawdown_metrics(values: list[float]) -> tuple[float, float]:
        if not values:
            return 0.0, 0.0
        equity = 0.0
        peak = 0.0
        drawdowns: list[float] = []
        for value in values:
            equity += float(value)
            peak = max(peak, equity)
            drawdowns.append(max(0.0, peak - equity))
        max_drawdown = max(drawdowns, default=0.0)
        ulcer_index = sqrt(sum(drawdown * drawdown for drawdown in drawdowns) / len(drawdowns))
        return float(max_drawdown), float(ulcer_index)

    @staticmethod
    def _mode_metrics(records: list[ClosedTradeRecord]) -> dict[str, Any]:
        if not records:
            return {
                "trades": 0,
                "win_rate": 0.0,
                "ev": 0.0,
                "p5_ev": 0.0,
                "p50_ev": 0.0,
                "max_drawdown": 0.0,
                "ulcer_index": 0.0,
                "avg_hold_bars": 0.0,
                "forced_exit_ratio": 0.0,
                "information_failure_ratio": 0.0,
                "time_failure_ratio": 0.0,
                "grade_mix": {},
                "exit_reasons": {},
                "first_trade_ts": None,
                "last_trade_ts": None,
            }

        realized = [float(record.realized_r) for record in records]
        holds = [int(record.held_bars) for record in records]
        exit_reasons: dict[str, int] = {}
        grade_mix: dict[str, int] = {}

        forced_exits = 0
        information_failures = 0
        time_failures = 0
        wins = 0
        for record in records:
            exit_reasons[record.exit_reason] = int(exit_reasons.get(record.exit_reason, 0)) + 1
            grade_mix[record.strategy_grade] = int(grade_mix.get(record.strategy_grade, 0)) + 1
            if record.realized_r > 0.0:
                wins += 1
            if record.exit_reason not in _TARGET_EXIT_REASONS:
                forced_exits += 1
            if record.exit_reason == ExitReason.INFORMATION_FAILURE.value:
                information_failures += 1
            if record.exit_reason == ExitReason.TIME_FAILURE.value:
                time_failures += 1

        max_drawdown, ulcer_index = StrategyV2ValidationService._drawdown_metrics(realized)
        return {
            "trades": len(records),
            "win_rate": round(wins / len(records), 4),
            "ev": round(sum(realized) / len(realized), 4),
            "p5_ev": round(StrategyV2ValidationService._quantile(realized, 0.05), 4),
            "p50_ev": round(StrategyV2ValidationService._quantile(realized, 0.50), 4),
            "max_drawdown": round(max_drawdown, 4),
            "ulcer_index": round(ulcer_index, 4),
            "avg_hold_bars": round(sum(holds) / len(holds), 2),
            "forced_exit_ratio": round(forced_exits / len(records), 4),
            "information_failure_ratio": round(information_failures / len(records), 4),
            "time_failure_ratio": round(time_failures / len(records), 4),
            "grade_mix": dict(sorted(grade_mix.items())),
            "exit_reasons": dict(sorted(exit_reasons.items())),
            "first_trade_ts": records[0].closed_ts.isoformat(),
            "last_trade_ts": records[-1].closed_ts.isoformat(),
        }

    @staticmethod
    def _delta(a_only: dict[str, Any], a_plus_b: dict[str, Any]) -> dict[str, float]:
        keys = (
            "trades",
            "win_rate",
            "ev",
            "p5_ev",
            "p50_ev",
            "max_drawdown",
            "ulcer_index",
            "avg_hold_bars",
            "forced_exit_ratio",
            "information_failure_ratio",
            "time_failure_ratio",
        )
        return {key: round(float(a_plus_b.get(key, 0.0)) - float(a_only.get(key, 0.0)), 4) for key in keys}

    def _session_bucket(self, closed_ts: datetime) -> str:
        guidance = self.session_guidance.snapshot(now=closed_ts)
        windows = dict(guidance.get("preferred_windows_utc") or {})
        if self._safe_bool(dict(windows.get("overlap") or {}).get("active")):
            return "overlap"
        if self._safe_bool(dict(windows.get("london") or {}).get("active")):
            return "london"
        if self._safe_bool(dict(windows.get("new_york") or {}).get("active")):
            return "new_york"
        return "dead_session"

    def _group_metrics(
        self,
        records: list[ClosedTradeRecord],
        *,
        key_func: Any,
    ) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[ClosedTradeRecord]] = {}
        for record in records:
            key = str(key_func(record) or "unknown")
            grouped.setdefault(key, []).append(record)
        return {key: self._mode_metrics(bucket) for key, bucket in sorted(grouped.items())}

    @staticmethod
    def _best_bucket(metrics: dict[str, dict[str, Any]], *, metric_key: str) -> dict[str, Any]:
        if not metrics:
            return {"name": None, metric_key: 0.0, "trades": 0}
        name, payload = max(
            metrics.items(),
            key=lambda item: (
                float((item[1] or {}).get(metric_key, 0.0)),
                int((item[1] or {}).get("trades", 0)),
                str(item[0]),
            ),
        )
        return {
            "name": name,
            metric_key: round(float((payload or {}).get(metric_key, 0.0)), 4),
            "trades": int((payload or {}).get("trades", 0)),
        }

    @staticmethod
    def _largest_bucket(metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
        if not metrics:
            return {"name": None, "trades": 0}
        name, payload = max(metrics.items(), key=lambda item: (int((item[1] or {}).get("trades", 0)), str(item[0])))
        return {"name": name, "trades": int((payload or {}).get("trades", 0))}

    def _closed_trade(self, plan: Plan, *, symbol: str, version: str) -> ClosedTradeRecord | None:
        if str(plan.symbol) != symbol or str(plan.strategy_version) != version or str(plan.state) != PlanState.CLOSED.value:
            return None
        validity = dict(plan.validity or {})
        family = str(validity.get("strategy_family") or "").strip()
        grade = str(validity.get("strategy_grade") or "").strip().upper()
        if not family or family == "legacy_zone_plan" or grade not in {"A", "B", "C"}:
            return None
        closed_ts = self._parse_ts(validity.get("final_exit_ts") or validity.get("last_exit_ts"))
        if closed_ts is None:
            return None
        try:
            realized_r = float(validity.get("final_exit_realized_r"))
        except (TypeError, ValueError):
            return None
        exit_reason = str(validity.get("final_exit_reason") or "unknown").strip() or "unknown"
        held_bars = int(validity.get("final_exit_held_bars") or 0)
        regime = str(validity.get("regime") or "unknown").strip().lower() or "unknown"
        return ClosedTradeRecord(
            plan_id=plan.plan_id,
            symbol=plan.symbol,
            closed_ts=closed_ts,
            realized_r=realized_r,
            held_bars=held_bars,
            exit_reason=exit_reason,
            regime=regime,
            strategy_family=family,
            strategy_grade=grade,
            strategy_version=str(plan.strategy_version),
        )

    def _subset_for_mode(self, records: list[ClosedTradeRecord], *, mode: StrategyMode) -> list[ClosedTradeRecord]:
        policy = self.mode.policy(mode)
        subset = [
            record
            for record in records
            if record.strategy_family in policy.allowed_families and record.strategy_grade in policy.allowed_grades
        ]
        subset.sort(key=lambda record: record.closed_ts)
        return subset

    @staticmethod
    def _deployment_recommendation(
        *,
        a_only: dict[str, Any],
        a_plus_b: dict[str, Any],
        incremental_b_trades: int,
    ) -> dict[str, Any]:
        if int(a_only.get("trades", 0)) == 0:
            return {
                "preferred_live_mode": StrategyMode.A_ONLY.value,
                "reason": "insufficient_a_only_samples_default",
                "a_only_downside_better": False,
                "a_only_first_deployment_rule": True,
            }
        downside_better = (
            float(a_only.get("p5_ev", 0.0)) >= float(a_plus_b.get("p5_ev", 0.0))
            and float(a_only.get("max_drawdown", 0.0)) <= float(a_plus_b.get("max_drawdown", 0.0))
            and float(a_only.get("ulcer_index", 0.0)) <= float(a_plus_b.get("ulcer_index", 0.0))
        )
        if incremental_b_trades <= 0:
            reason = "no_incremental_b_samples_default_a_only"
        elif downside_better:
            reason = "a_only_downside_better"
        else:
            reason = "a_only_first_deployment_rule"
        return {
            "preferred_live_mode": StrategyMode.A_ONLY.value,
            "reason": reason,
            "a_only_downside_better": bool(downside_better),
            "a_only_first_deployment_rule": True,
        }

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.validation_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / (
            f"strategy_v2_validation_{payload['symbol']}_{payload['version']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        )

        a_only = dict((payload.get("mode_metrics") or {}).get(StrategyMode.A_ONLY.value, {}))
        a_plus_b = dict((payload.get("mode_metrics") or {}).get(StrategyMode.A_PLUS_B.value, {}))
        delta = dict(payload.get("comparison") or {})
        recommendation = dict(payload.get("deployment_recommendation") or {})
        family_metrics = dict(payload.get("family_metrics") or {})
        regime_metrics = dict(payload.get("regime_metrics") or {})
        session_metrics = dict(payload.get("session_metrics") or {})
        family_summary = dict(payload.get("family_summary") or {})
        regime_summary = dict(payload.get("regime_summary") or {})
        session_summary = dict(payload.get("session_summary") or {})
        lines = [
            f"# Strategy v2 Validation: {payload['symbol']}",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- strategy_version: {payload['version']}",
            f"- available: {payload['available']}",
            f"- reason: {payload['reason']}",
            "",
            "## Executive Summary",
            f"- eligible_closed_trades: {payload['sample_counts']['eligible_closed_trades']}",
            f"- A_ONLY trades: {payload['sample_counts']['a_only_trades']}",
            f"- A_PLUS_B trades: {payload['sample_counts']['a_plus_b_trades']}",
            f"- incremental_B trades: {payload['sample_counts']['incremental_b_trades']}",
            f"- preferred_live_mode: {recommendation.get('preferred_live_mode', StrategyMode.A_ONLY.value)}",
            f"- recommendation_reason: {recommendation.get('reason', 'not_available')}",
            f"- best_ev_family: {(family_summary.get('best_ev_family') or {}).get('name')}",
            f"- best_ev_regime: {(regime_summary.get('best_ev_regime') or {}).get('name')}",
            f"- best_ev_session: {(session_summary.get('best_ev_session') or {}).get('name')}",
            "",
            "## Comparison Table",
            (
                f"- A_ONLY: trades={a_only.get('trades', 0)}, win_rate={float(a_only.get('win_rate', 0.0)):.4f}, "
                f"ev={float(a_only.get('ev', 0.0)):.4f}, p5={float(a_only.get('p5_ev', 0.0)):.4f}, "
                f"p50={float(a_only.get('p50_ev', 0.0)):.4f}, max_dd={float(a_only.get('max_drawdown', 0.0)):.4f}, "
                f"ulcer={float(a_only.get('ulcer_index', 0.0)):.4f}, avg_hold_bars={float(a_only.get('avg_hold_bars', 0.0)):.2f}, "
                f"forced_exit_ratio={float(a_only.get('forced_exit_ratio', 0.0)):.4f}, "
                f"information_failure_ratio={float(a_only.get('information_failure_ratio', 0.0)):.4f}"
            ),
            (
                f"- A_PLUS_B: trades={a_plus_b.get('trades', 0)}, win_rate={float(a_plus_b.get('win_rate', 0.0)):.4f}, "
                f"ev={float(a_plus_b.get('ev', 0.0)):.4f}, p5={float(a_plus_b.get('p5_ev', 0.0)):.4f}, "
                f"p50={float(a_plus_b.get('p50_ev', 0.0)):.4f}, max_dd={float(a_plus_b.get('max_drawdown', 0.0)):.4f}, "
                f"ulcer={float(a_plus_b.get('ulcer_index', 0.0)):.4f}, avg_hold_bars={float(a_plus_b.get('avg_hold_bars', 0.0)):.2f}, "
                f"forced_exit_ratio={float(a_plus_b.get('forced_exit_ratio', 0.0)):.4f}, "
                f"information_failure_ratio={float(a_plus_b.get('information_failure_ratio', 0.0)):.4f}"
            ),
            (
                f"- delta(A_PLUS_B - A_ONLY): trades={float(delta.get('trades', 0.0)):.4f}, "
                f"ev={float(delta.get('ev', 0.0)):.4f}, p5={float(delta.get('p5_ev', 0.0)):.4f}, "
                f"max_dd={float(delta.get('max_drawdown', 0.0)):.4f}, ulcer={float(delta.get('ulcer_index', 0.0)):.4f}, "
                f"forced_exit_ratio={float(delta.get('forced_exit_ratio', 0.0)):.4f}, "
                f"information_failure_ratio={float(delta.get('information_failure_ratio', 0.0)):.4f}"
            ),
            "",
            "## Exit Reason / Failure Decomposition",
            f"- A_ONLY exit_reasons: {a_only.get('exit_reasons', {})}",
            f"- A_PLUS_B exit_reasons: {a_plus_b.get('exit_reasons', {})}",
            "",
            "## Family Breakdown",
            f"- best_ev_family: {family_summary.get('best_ev_family', {})}",
            f"- best_win_rate_family: {family_summary.get('best_win_rate_family', {})}",
            f"- largest_sample_family: {family_summary.get('largest_sample_family', {})}",
        ]
        for family, metrics in family_metrics.items():
            lines.append(
                f"- {family}: trades={int(metrics.get('trades', 0))}, win_rate={float(metrics.get('win_rate', 0.0)):.4f}, "
                f"ev={float(metrics.get('ev', 0.0)):.4f}, p5={float(metrics.get('p5_ev', 0.0)):.4f}, "
                f"max_dd={float(metrics.get('max_drawdown', 0.0)):.4f}, time_failure_ratio={float(metrics.get('time_failure_ratio', 0.0)):.4f}"
            )
        lines.extend(
            [
                "",
                "## Regime Breakdown",
                f"- best_ev_regime: {regime_summary.get('best_ev_regime', {})}",
                f"- best_win_rate_regime: {regime_summary.get('best_win_rate_regime', {})}",
                f"- largest_sample_regime: {regime_summary.get('largest_sample_regime', {})}",
            ]
        )
        for regime_name, metrics in regime_metrics.items():
            lines.append(
                f"- {regime_name}: trades={int(metrics.get('trades', 0))}, win_rate={float(metrics.get('win_rate', 0.0)):.4f}, "
                f"ev={float(metrics.get('ev', 0.0)):.4f}, p5={float(metrics.get('p5_ev', 0.0)):.4f}, "
                f"max_dd={float(metrics.get('max_drawdown', 0.0)):.4f}, time_failure_ratio={float(metrics.get('time_failure_ratio', 0.0)):.4f}"
            )
        lines.extend(
            [
                "",
                "## Session Breakdown",
                f"- best_ev_session: {session_summary.get('best_ev_session', {})}",
                f"- best_win_rate_session: {session_summary.get('best_win_rate_session', {})}",
                f"- largest_sample_session: {session_summary.get('largest_sample_session', {})}",
            ]
        )
        for session_name, metrics in session_metrics.items():
            lines.append(
                f"- {session_name}: trades={int(metrics.get('trades', 0))}, win_rate={float(metrics.get('win_rate', 0.0)):.4f}, "
                f"ev={float(metrics.get('ev', 0.0)):.4f}, p5={float(metrics.get('p5_ev', 0.0)):.4f}, "
                f"max_dd={float(metrics.get('max_drawdown', 0.0)):.4f}, time_failure_ratio={float(metrics.get('time_failure_ratio', 0.0)):.4f}"
            )
        lines.extend(
            [
                "",
            "## Deployment Recommendation",
            f"- preferred_live_mode: {recommendation.get('preferred_live_mode', StrategyMode.A_ONLY.value)}",
            f"- a_only_downside_better: {recommendation.get('a_only_downside_better', False)}",
            f"- a_only_first_deployment_rule: {recommendation.get('a_only_first_deployment_rule', True)}",
            "",
            "## Notes",
            "- This template currently covers the first frozen comparison axis: A-only vs A+B.",
            "- Lock before/after, thesis dedupe before/after, and stressed-cost comparisons remain separate checklist items.",
            "",
            ]
        )
        atomic_write_text(file_path, "\n".join(lines))
        return str(file_path)

    def generate(
        self,
        *,
        symbol: str,
        version: str,
        plans: list[Plan],
        write_report: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        records = [record for record in (self._closed_trade(plan, symbol=symbol, version=version) for plan in plans) if record]
        records.sort(key=lambda record: record.closed_ts)

        a_only_records = self._subset_for_mode(records, mode=StrategyMode.A_ONLY)
        a_plus_b_records = self._subset_for_mode(records, mode=StrategyMode.A_PLUS_B)
        incremental_b_records = [record for record in a_plus_b_records if record.strategy_grade == "B"]
        family_metrics = self._group_metrics(records, key_func=lambda record: record.strategy_family)
        regime_metrics = self._group_metrics(records, key_func=lambda record: record.regime)
        session_metrics = self._group_metrics(records, key_func=lambda record: self._session_bucket(record.closed_ts))

        available = bool(records)
        reason = "ok" if available else "no_closed_v2_trades"
        mode_metrics = {
            StrategyMode.A_ONLY.value: self._mode_metrics(a_only_records),
            StrategyMode.A_PLUS_B.value: self._mode_metrics(a_plus_b_records),
            "B_INCREMENTAL": self._mode_metrics(incremental_b_records),
        }
        comparison = self._delta(
            dict(mode_metrics[StrategyMode.A_ONLY.value]),
            dict(mode_metrics[StrategyMode.A_PLUS_B.value]),
        )
        recommendation = self._deployment_recommendation(
            a_only=dict(mode_metrics[StrategyMode.A_ONLY.value]),
            a_plus_b=dict(mode_metrics[StrategyMode.A_PLUS_B.value]),
            incremental_b_trades=len(incremental_b_records),
        )
        family_summary = {
            "best_ev_family": self._best_bucket(family_metrics, metric_key="ev"),
            "best_win_rate_family": self._best_bucket(family_metrics, metric_key="win_rate"),
            "largest_sample_family": self._largest_bucket(family_metrics),
        }
        regime_summary = {
            "best_ev_regime": self._best_bucket(regime_metrics, metric_key="ev"),
            "best_win_rate_regime": self._best_bucket(regime_metrics, metric_key="win_rate"),
            "largest_sample_regime": self._largest_bucket(regime_metrics),
        }
        session_summary = {
            "best_ev_session": self._best_bucket(session_metrics, metric_key="ev"),
            "best_win_rate_session": self._best_bucket(session_metrics, metric_key="win_rate"),
            "largest_sample_session": self._largest_bucket(session_metrics),
        }

        payload: dict[str, Any] = {
            "schema_version": "strategy_v2_validation_v1",
            "symbol": symbol,
            "version": version,
            "generated_at": now.isoformat(),
            "available": available,
            "reason": reason,
            "comparison_axis": "strategy_mode",
            "modes": [StrategyMode.A_ONLY.value, StrategyMode.A_PLUS_B.value],
            "sample_counts": {
                "eligible_closed_trades": len(records),
                "a_only_trades": len(a_only_records),
                "a_plus_b_trades": len(a_plus_b_records),
                "incremental_b_trades": len(incremental_b_records),
            },
            "mode_metrics": mode_metrics,
            "family_metrics": family_metrics,
            "regime_metrics": regime_metrics,
            "session_metrics": session_metrics,
            "family_summary": family_summary,
            "regime_summary": regime_summary,
            "session_summary": session_summary,
            "comparison": comparison,
            "deployment_recommendation": recommendation,
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload
