from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.enums import ExecutionFillStage
from app.services.strategy_v2_validation import ClosedTradeRecord, StrategyV2ValidationService
from app.services.thesis_fingerprint import ThesisFingerprintService


@dataclass(slots=True)
class ThesisTradeRecord:
    base: ClosedTradeRecord
    opened_ts: datetime
    closed_ts: datetime
    thesis_fingerprint: dict[str, str] | None
    thesis_cluster_id: str | None
    priority: tuple[float, float, float, float]


class StrategyV2ThesisValidationService:
    def __init__(self, settings: Settings | None = None, *, fill_repo: Any | None = None):
        self.settings = settings or get_settings()
        self.fill_repo = fill_repo
        self._base = StrategyV2ValidationService(self.settings)
        self.thesis = ThesisFingerprintService(self.settings)

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        if value in (None, "", "None"):
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return int(parsed) if isfinite(parsed) else default

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _entry_fill_ts_by_plan(self, plans: list[Any]) -> dict[str, datetime]:
        if self.fill_repo is None:
            return {}

        plan_ids = [str(getattr(plan, "plan_id", "") or "") for plan in plans if getattr(plan, "plan_id", None)]
        if not plan_ids:
            return {}

        rows = self.fill_repo.list_for_plans(plan_ids=plan_ids)
        entry_ts: dict[str, datetime] = {}
        for row in rows:
            if str(getattr(row, "stage", "")) != ExecutionFillStage.ENTRY.value:
                continue
            plan_id = str(getattr(row, "plan_id", "") or "")
            if not plan_id:
                continue
            fill_ts = self._utc(row.fill_ts)
            current = entry_ts.get(plan_id)
            if current is None or fill_ts < current:
                entry_ts[plan_id] = fill_ts
        return entry_ts

    @staticmethod
    def _priority_signature(plan: Any) -> tuple[float, float, float, float]:
        invalidation = abs(float(getattr(plan, "entry_price", 0.0)) - float(getattr(plan, "sl", 0.0)))
        return (
            round(invalidation, 6),
            round(-float(getattr(plan, "ev", 0.0)), 6),
            round(float(getattr(plan, "cost_est", 0.0)), 6),
            round(-float(getattr(plan, "confidence", 0.0)), 6),
        )

    def _opened_ts(self, plan: Any, *, entry_fill_ts: datetime | None) -> tuple[datetime, str]:
        if entry_fill_ts is not None:
            return entry_fill_ts, "entry_fill"

        validity = dict(getattr(plan, "validity", {}) or {})
        for key in ("entry_ts", "entered_ts", "first_entry_ts", "triggered_ts"):
            parsed = self._base._parse_ts(validity.get(key))
            if parsed is not None:
                return parsed, f"validity:{key}"

        valid_from = getattr(plan, "valid_from", None)
        if isinstance(valid_from, datetime):
            return self._utc(valid_from), "valid_from"

        fallback = self._base._parse_ts(validity.get("final_exit_ts") or validity.get("last_exit_ts")) or datetime.now(timezone.utc)
        return fallback, "closed_fallback"

    def _thesis_trade(
        self,
        *,
        plan: Any,
        record: ClosedTradeRecord,
        entry_fill_ts: datetime | None,
    ) -> tuple[ThesisTradeRecord, str]:
        opened_ts, source = self._opened_ts(plan, entry_fill_ts=entry_fill_ts)
        closed_ts = self._base._parse_ts(dict(getattr(plan, "validity", {}) or {}).get("final_exit_ts") or dict(getattr(plan, "validity", {}) or {}).get("last_exit_ts")) or record.closed_ts
        if closed_ts < opened_ts:
            opened_ts = closed_ts

        fingerprint = self.thesis.build_from_plan(plan)
        validity = dict(getattr(plan, "validity", {}) or {})
        thesis_cluster_id = str(validity.get("thesis_cluster_id") or self.thesis.thesis_cluster_id(fingerprint))
        return (
            ThesisTradeRecord(
                base=record,
                opened_ts=opened_ts,
                closed_ts=closed_ts,
                thesis_fingerprint=fingerprint,
                thesis_cluster_id=thesis_cluster_id,
                priority=self._priority_signature(plan),
            ),
            source,
        )

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.validation_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / (
            f"strategy_v2_thesis_validation_{payload['symbol']}_{payload['version']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        )

        before = dict((payload.get("thesis_metrics") or {}).get("before_dedupe") or {})
        after = dict((payload.get("thesis_metrics") or {}).get("after_dedupe") or {})
        comparison = dict(payload.get("comparison") or {})
        impact_counts = dict(payload.get("impact_counts") or {})
        recommendation = dict(payload.get("deployment_recommendation") or {})
        lines = [
            f"# Strategy v2 Thesis Dedupe Validation: {payload['symbol']}",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- strategy_version: {payload['version']}",
            f"- available: {payload['available']}",
            f"- reason: {payload['reason']}",
            f"- evaluation_scope: {payload.get('evaluation_scope', 'portfolio_global')}",
            "",
            "## Executive Summary",
            f"- eligible_closed_trades: {payload['sample_counts']['eligible_closed_trades']}",
            f"- after_dedupe_trades: {payload['sample_counts']['after_dedupe_trades']}",
            f"- blocked_duplicate_trades: {payload['sample_counts']['blocked_duplicate_trades']}",
            f"- blocked_active_cluster_cap_trades: {payload['sample_counts']['blocked_active_cluster_cap_trades']}",
            f"- symbols_included: {payload.get('symbols_included', [])}",
            f"- keep_dedupe_enabled: {recommendation.get('keep_dedupe_enabled', True)}",
            f"- recommendation_reason: {recommendation.get('reason', 'not_available')}",
            "",
            "## Comparison Table",
            (
                f"- before_dedupe: trades={int(before.get('trades', 0))}, ev={float(before.get('ev', 0.0)):.4f}, "
                f"p5={float(before.get('p5_ev', 0.0)):.4f}, p50={float(before.get('p50_ev', 0.0)):.4f}, "
                f"max_dd={float(before.get('max_drawdown', 0.0)):.4f}, ulcer={float(before.get('ulcer_index', 0.0)):.4f}, "
                f"avg_hold_bars={float(before.get('avg_hold_bars', 0.0)):.2f}, forced_exit_ratio={float(before.get('forced_exit_ratio', 0.0)):.4f}, "
                f"information_failure_ratio={float(before.get('information_failure_ratio', 0.0)):.4f}"
            ),
            (
                f"- after_dedupe: trades={int(after.get('trades', 0))}, ev={float(after.get('ev', 0.0)):.4f}, "
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
            f"- open_ts_sources: {payload.get('open_ts_sources', {})}",
            "",
            "## Deployment Recommendation",
            f"- keep_dedupe_enabled: {recommendation.get('keep_dedupe_enabled', True)}",
            f"- downside_improved: {recommendation.get('downside_improved', False)}",
            "",
            "## Notes",
            "- Current approximation reconstructs thesis overlap from saved closed v2 plans across the portfolio scope.",
            "- ENTRY fill timestamps are used when available; otherwise `valid_from` is used as the open-time fallback.",
            "- Dedupe removes later overlapping same-thesis trades and blocks new clusters once the active thesis cap is reached.",
            "",
        ]
        file_path.write_text("\n".join(lines), encoding="utf-8")
        return str(file_path)

    @staticmethod
    def _recommendation(before: dict[str, Any], after: dict[str, Any], impact_counts: dict[str, int]) -> dict[str, Any]:
        downside_improved = (
            float(after.get("p5_ev", 0.0)) >= float(before.get("p5_ev", 0.0))
            and float(after.get("max_drawdown", 0.0)) <= float(before.get("max_drawdown", 0.0))
            and float(after.get("ulcer_index", 0.0)) <= float(before.get("ulcer_index", 0.0))
        )
        overlap_blocks = int(impact_counts.get("thesis_duplicate_blocked", 0)) + int(
            impact_counts.get("thesis_active_cluster_cap_reached", 0)
        )
        reason = "dedupe_downside_improved" if downside_improved else "dedupe_not_clearly_better"
        if overlap_blocks == 0:
            reason = "no_thesis_overlap_samples"
        return {
            "keep_dedupe_enabled": True,
            "downside_improved": bool(downside_improved),
            "reason": reason,
        }

    def generate(self, *, symbol: str, version: str, plans: list[Any], write_report: bool = True) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        entry_ts_by_plan = self._entry_fill_ts_by_plan(plans)

        eligible: list[ThesisTradeRecord] = []
        open_ts_sources: dict[str, int] = {}
        symbols_included: set[str] = set()
        for plan in plans:
            record = self._base._closed_trade(plan, symbol=str(getattr(plan, "symbol", "") or ""), version=version)
            if record is None:
                continue
            thesis_trade, source = self._thesis_trade(
                plan=plan,
                record=record,
                entry_fill_ts=entry_ts_by_plan.get(record.plan_id),
            )
            eligible.append(thesis_trade)
            open_ts_sources[source] = int(open_ts_sources.get(source, 0)) + 1
            symbols_included.add(record.symbol)

        eligible.sort(key=lambda item: (item.opened_ts, item.priority, item.base.plan_id))

        after_dedupe: list[ThesisTradeRecord] = []
        impact_counts: dict[str, int] = {}
        blocked_duplicate = 0
        blocked_active_cluster_cap = 0

        for trade in eligible:
            active_clusters = [item for item in after_dedupe if item.closed_ts > trade.opened_ts]
            duplicate = next(
                (
                    item
                    for item in active_clusters
                    if self.thesis.same_thesis(item.thesis_fingerprint, trade.thesis_fingerprint)
                ),
                None,
            )
            if duplicate is not None:
                blocked_duplicate += 1
                impact_counts["thesis_duplicate_blocked"] = int(impact_counts.get("thesis_duplicate_blocked", 0)) + 1
                continue

            if len(active_clusters) >= self._safe_int(self.settings.thesis_max_active_clusters, default=2):
                blocked_active_cluster_cap += 1
                impact_counts["thesis_active_cluster_cap_reached"] = int(
                    impact_counts.get("thesis_active_cluster_cap_reached", 0)
                ) + 1
                continue

            after_dedupe.append(trade)
            impact_counts["primary_trade_kept"] = int(impact_counts.get("primary_trade_kept", 0)) + 1

        before_records = [trade.base for trade in eligible]
        after_records = [trade.base for trade in after_dedupe]
        before_metrics = self._base._mode_metrics(before_records)
        after_metrics = self._base._mode_metrics(after_records)
        comparison = self._base._delta(before_metrics, after_metrics)
        recommendation = self._recommendation(before_metrics, after_metrics, impact_counts)

        payload: dict[str, Any] = {
            "schema_version": "strategy_v2_thesis_validation_v1",
            "symbol": symbol,
            "version": version,
            "generated_at": now.isoformat(),
            "available": bool(before_records),
            "reason": "ok" if before_records else "no_closed_v2_trades",
            "comparison_axis": "thesis_dedupe",
            "evaluation_scope": "portfolio_global",
            "symbols_included": sorted(symbols_included),
            "open_ts_sources": dict(sorted(open_ts_sources.items())),
            "sample_counts": {
                "eligible_closed_trades": len(before_records),
                "after_dedupe_trades": len(after_records),
                "blocked_duplicate_trades": blocked_duplicate,
                "blocked_active_cluster_cap_trades": blocked_active_cluster_cap,
            },
            "impact_counts": dict(sorted(impact_counts.items())),
            "thesis_metrics": {
                "before_dedupe": before_metrics,
                "after_dedupe": after_metrics,
            },
            "comparison": comparison,
            "deployment_recommendation": recommendation,
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload
