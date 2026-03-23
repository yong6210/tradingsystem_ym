from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from math import sqrt
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.enums import PlanState
from app.db.models import Plan
from app.db.repositories import ExecutionFillRepository, PlanRepository
from app.services.strategy_v2_stress_validation import StrategyV2StressValidationService
from app.services.strategy_v2_validation import ClosedTradeRecord, StrategyV2ValidationService


class StrategyFamilyEdgeReviewService:
    _MIN_SAMPLE = 4
    _MATURE_SAMPLE = 8

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        plan_repo: PlanRepository | None = None,
        fill_repo: ExecutionFillRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.plan_repo = plan_repo
        self.fill_repo = fill_repo
        self.validation = StrategyV2ValidationService(self.settings)
        self.stress = StrategyV2StressValidationService(
            self.settings,
            fill_repo=self.fill_repo,
            candle_repo=None,
        )

    @staticmethod
    def _default_peer_family(family: str) -> str:
        normalized = str(family or "").strip().lower()
        if normalized == "sweep_reversal":
            return "trend_continuation"
        if normalized == "trend_continuation":
            return "sweep_reversal"
        return ""

    @staticmethod
    def _role(family: str) -> str:
        normalized = str(family or "").strip().lower()
        if normalized == "sweep_reversal":
            return "a_anchor"
        if normalized == "trend_continuation":
            return "b_diversification"
        return "generic_family"

    def _closed_trade(self, plan: Plan, *, symbol: str | None, version: str) -> ClosedTradeRecord | None:
        if symbol and str(plan.symbol) != str(symbol):
            return None
        if str(plan.strategy_version) != str(version) or str(plan.state) != PlanState.CLOSED.value:
            return None
        validity = dict(plan.validity or {})
        family = str(validity.get("strategy_family") or "").strip()
        grade = str(validity.get("strategy_grade") or "").strip().upper()
        if not family or family == "legacy_zone_plan" or grade not in {"A", "B", "C"}:
            return None
        closed_ts = self.validation._parse_ts(validity.get("final_exit_ts") or validity.get("last_exit_ts"))
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
            plan_id=str(plan.plan_id),
            symbol=str(plan.symbol),
            closed_ts=closed_ts,
            realized_r=realized_r,
            held_bars=held_bars,
            exit_reason=exit_reason,
            regime=regime,
            strategy_family=family,
            strategy_grade=grade,
            strategy_version=str(plan.strategy_version),
        )

    @staticmethod
    def _to_adjusted_record(adjusted: Any) -> ClosedTradeRecord:
        base = adjusted.base
        return ClosedTradeRecord(
            plan_id=base.plan_id,
            symbol=base.symbol,
            closed_ts=base.closed_ts,
            realized_r=float(adjusted.baseline_adjusted_r),
            held_bars=base.held_bars,
            exit_reason=base.exit_reason,
            regime=base.regime,
            strategy_family=base.strategy_family,
            strategy_grade=base.strategy_grade,
            strategy_version=base.strategy_version,
        )

    @staticmethod
    def _frequency(records: list[ClosedTradeRecord]) -> dict[str, Any]:
        if not records:
            return {
                "trades": 0,
                "active_days": 0,
                "active_weeks": 0,
                "active_months": 0,
                "window_days": 0,
                "trades_per_7d": 0.0,
                "trades_per_30d": 0.0,
            }
        ordered = sorted(records, key=lambda record: record.closed_ts)
        first_ts = ordered[0].closed_ts
        last_ts = ordered[-1].closed_ts
        window_days = max(1, (last_ts.date() - first_ts.date()).days + 1)
        active_days = len({record.closed_ts.date() for record in ordered})
        active_weeks = len({record.closed_ts.isocalendar()[:2] for record in ordered})
        active_months = len({(record.closed_ts.year, record.closed_ts.month) for record in ordered})
        trades = len(ordered)
        return {
            "trades": trades,
            "active_days": active_days,
            "active_weeks": active_weeks,
            "active_months": active_months,
            "window_days": window_days,
            "trades_per_7d": round((trades / window_days) * 7.0, 4),
            "trades_per_30d": round((trades / window_days) * 30.0, 4),
        }

    def _group_metrics(
        self,
        records: list[ClosedTradeRecord],
        *,
        key_func: Any,
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[ClosedTradeRecord]] = defaultdict(list)
        for record in records:
            key = str(key_func(record) or "unknown")
            grouped[key].append(record)
        rows: list[dict[str, Any]] = []
        for key, bucket in sorted(grouped.items()):
            metrics = self.validation._mode_metrics(sorted(bucket, key=lambda record: record.closed_ts))
            rows.append(
                {
                    "key": key,
                    "trades": int(metrics.get("trades", 0)),
                    "win_rate": float(metrics.get("win_rate", 0.0) or 0.0),
                    "ev": float(metrics.get("ev", 0.0) or 0.0),
                    "p5_ev": float(metrics.get("p5_ev", 0.0) or 0.0),
                    "p50_ev": float(metrics.get("p50_ev", 0.0) or 0.0),
                    "max_drawdown": float(metrics.get("max_drawdown", 0.0) or 0.0),
                    "forced_exit_ratio": float(metrics.get("forced_exit_ratio", 0.0) or 0.0),
                    "information_failure_ratio": float(metrics.get("information_failure_ratio", 0.0) or 0.0),
                    "time_failure_ratio": float(metrics.get("time_failure_ratio", 0.0) or 0.0),
                }
            )
        rows.sort(key=lambda row: (-int(row["trades"]), str(row["key"])))
        return rows

    @staticmethod
    def _calendar_rows(records: list[ClosedTradeRecord], *, by: str) -> list[dict[str, Any]]:
        grouped: dict[str, list[ClosedTradeRecord]] = defaultdict(list)
        for record in records:
            if by == "month":
                key = f"{record.closed_ts.year:04d}-{record.closed_ts.month:02d}"
            else:
                year, week, _ = record.closed_ts.isocalendar()
                key = f"{year:04d}-W{int(week):02d}"
            grouped[key].append(record)
        rows: list[dict[str, Any]] = []
        for key, bucket in sorted(grouped.items()):
            trades = len(bucket)
            returns = [float(record.realized_r) for record in bucket]
            wins = sum(1 for value in returns if value > 0.0)
            rows.append(
                {
                    "key": key,
                    "trades": trades,
                    "total_post_cost_r": round(sum(returns), 4),
                    "avg_post_cost_r": round(sum(returns) / trades, 4) if trades else 0.0,
                    "win_rate": round(wins / trades, 4) if trades else 0.0,
                }
            )
        rows.sort(key=lambda row: str(row["key"]))
        return rows

    @staticmethod
    def _daily_return_map(records: list[ClosedTradeRecord]) -> dict[date, float]:
        daily: dict[date, float] = defaultdict(float)
        for record in records:
            daily[record.closed_ts.date()] += float(record.realized_r)
        return {key: round(value, 4) for key, value in sorted(daily.items())}

    @staticmethod
    def _pearson(xs: list[float], ys: list[float]) -> float | None:
        if len(xs) != len(ys) or len(xs) < 2:
            return None
        mean_x = sum(xs) / len(xs)
        mean_y = sum(ys) / len(ys)
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        den_x = sqrt(sum((x - mean_x) ** 2 for x in xs))
        den_y = sqrt(sum((y - mean_y) ** 2 for y in ys))
        if den_x <= 0.0 or den_y <= 0.0:
            return None
        return round(num / (den_x * den_y), 4)

    @staticmethod
    def _correlation_state(value: float | None) -> str:
        if value is None:
            return "unknown_overlap"
        if value <= 0.25:
            return "low_overlap_proxy"
        if value <= 0.6:
            return "mixed_overlap_proxy"
        return "high_overlap_proxy"

    def _drawdown_metrics(self, returns: list[float]) -> dict[str, float]:
        max_drawdown, ulcer_index = self.validation._drawdown_metrics(returns)
        return {
            "max_drawdown": round(float(max_drawdown), 4),
            "ulcer_index": round(float(ulcer_index), 4),
        }

    def _diversification_proxy(
        self,
        *,
        target_daily: dict[date, float],
        peer_daily: dict[date, float],
    ) -> dict[str, Any]:
        union_days = sorted(set(target_daily) | set(peer_daily))
        overlap_days = sorted(set(target_daily) & set(peer_daily))
        overlap_ratio = round((len(overlap_days) / len(union_days)), 4) if union_days else 0.0
        overlap_x = [float(target_daily[day]) for day in overlap_days]
        overlap_y = [float(peer_daily[day]) for day in overlap_days]
        correlation = self._pearson(overlap_x, overlap_y)

        union_target = [float(target_daily.get(day, 0.0)) for day in union_days]
        union_peer = [float(peer_daily.get(day, 0.0)) for day in union_days]
        combined = [round(x + y, 4) for x, y in zip(union_target, union_peer)]
        target_dd = self._drawdown_metrics(union_target)
        peer_dd = self._drawdown_metrics(union_peer)
        combined_dd = self._drawdown_metrics(combined)
        delta_vs_peer = round(
            float(combined_dd.get("max_drawdown", 0.0)) - float(peer_dd.get("max_drawdown", 0.0)),
            4,
        )
        if delta_vs_peer <= -0.2:
            drawdown_state = "drawdown_buffering"
        elif delta_vs_peer >= 0.2:
            drawdown_state = "drawdown_additive"
        else:
            drawdown_state = "drawdown_neutral"
        return {
            "daily_post_cost_correlation": correlation,
            "correlation_state": self._correlation_state(correlation),
            "overlap_days": len(overlap_days),
            "union_days": len(union_days),
            "overlap_ratio": overlap_ratio,
            "target_drawdown": target_dd,
            "peer_drawdown": peer_dd,
            "combined_drawdown": combined_dd,
            "drawdown_delta_vs_peer": delta_vs_peer,
            "drawdown_contribution_state": drawdown_state,
        }

    @staticmethod
    def _positive_rate(records: list[ClosedTradeRecord]) -> float:
        if not records:
            return 0.0
        positives = sum(1 for record in records if float(record.realized_r) > 0.0)
        return round(positives / len(records), 4)

    def _edge_decision(
        self,
        *,
        role: str,
        metrics: dict[str, Any],
        positive_rate: float,
        diversification_proxy: dict[str, Any] | None,
    ) -> tuple[str, str, str]:
        trades = int(metrics.get("trades", 0) or 0)
        ev = float(metrics.get("ev", 0.0) or 0.0)
        p5_ev = float(metrics.get("p5_ev", 0.0) or 0.0)
        max_drawdown = float(metrics.get("max_drawdown", 0.0) or 0.0)
        if trades < self._MIN_SAMPLE:
            if role == "a_anchor":
                return "insufficient_sample", "gather_more_evidence", "sample is too thin to trust anchor confidence."
            if role == "b_diversification":
                return "insufficient_sample", "gather_more_evidence", "sample is too thin to trust B diversification."
            return "insufficient_sample", "gather_more_evidence", "sample is too thin to trust this family edge."
        if ev <= 0.0 or positive_rate <= 0.4:
            if role == "a_anchor":
                return "insufficient_edge", "reduce_anchor_confidence", "post-cost edge is not strong enough to justify current A anchor confidence."
            if role == "b_diversification":
                return "insufficient_edge", "reduce_b_confidence", "B does not clear the minimum post-cost edge threshold."
            return "insufficient_edge", "reduce_confidence", "post-cost edge is not strong enough to justify current family confidence."
        if role == "a_anchor":
            if trades >= self._MATURE_SAMPLE and positive_rate >= 0.5 and p5_ev > -1.2 and max_drawdown <= 3.0:
                return "validated_edge", "keep_anchor", "A still clears the current post-cost anchor threshold."
            return "fragile_edge", "monitor_fragility", "A is still positive, but downside or sample quality is not strong enough to treat it as a fully comfortable anchor."
        if role == "b_diversification":
            proxy = dict(diversification_proxy or {})
            correlation_state = str(proxy.get("correlation_state") or "unknown_overlap")
            drawdown_state = str(proxy.get("drawdown_contribution_state") or "drawdown_neutral")
            if correlation_state == "high_overlap_proxy" and drawdown_state == "drawdown_additive":
                return "insufficient_edge", "reduce_b_confidence", "B looks too correlated and too drawdown-additive to justify guarded activation confidence."
            if (
                trades >= self._MATURE_SAMPLE
                and positive_rate >= 0.5
                and correlation_state in {"low_overlap_proxy", "mixed_overlap_proxy"}
                and drawdown_state in {"drawdown_buffering", "drawdown_neutral"}
            ):
                return "validated_edge", "support_guarded_activation", "B still looks like a useful diversification source on a post-cost basis."
            return "fragile_edge", "monitor_diversification", "B is positive, but diversification evidence is still too mixed to treat it as comfortable activation support."
        if trades >= self._MATURE_SAMPLE and positive_rate >= 0.5 and p5_ev > -1.2:
            return "validated_edge", "keep_current", "Family still clears the current post-cost edge threshold."
        return "fragile_edge", "monitor_fragility", "Family remains positive, but not comfortably enough to remove monitoring."

    @staticmethod
    def _next_actions(
        *,
        role: str,
        edge_state: str,
        frequency: dict[str, Any],
        top_regime: dict[str, Any] | None,
        top_session: dict[str, Any] | None,
        diversification_proxy: dict[str, Any] | None,
    ) -> list[str]:
        actions: list[str] = []
        if edge_state == "insufficient_sample":
            actions.append("Keep collecting closed trades before changing deployment confidence.")
        elif edge_state == "insufficient_edge":
            actions.append("Do not increase live confidence from this family until post-cost edge improves.")
        elif edge_state == "fragile_edge":
            actions.append("Keep current posture, but review the weakest downside bucket before any expansion.")
        else:
            actions.append("Hold current deployment posture and continue monitoring post-cost drift.")

        if float(frequency.get("trades_per_30d", 0.0) or 0.0) < 4.0:
            actions.append("Trade frequency is low enough that the next review should wait for more closed samples.")
        if top_regime and top_regime.get("key"):
            actions.append(f"Watch regime bucket `{top_regime['key']}` because it currently has the largest sample concentration.")
        if top_session and top_session.get("key"):
            actions.append(f"Watch session bucket `{top_session['key']}` because current timing concentration is still high.")
        if role == "b_diversification":
            proxy = dict(diversification_proxy or {})
            actions.append(
                "Keep B guarded until daily correlation and drawdown contribution stay acceptable over another review window."
                if proxy.get("drawdown_contribution_state") != "drawdown_buffering"
                else "Keep B guarded, but current drawdown interaction is supportive enough for continued observation."
            )
        return actions[:4]

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.strategy_family_edge_review_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / (
            f"strategy_family_edge_review_{payload['family']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        )
        target = dict(payload.get("target_metrics") or {})
        raw = dict(payload.get("raw_metrics") or {})
        peer = dict(payload.get("peer_metrics") or {})
        freq = dict(payload.get("trade_frequency") or {})
        proxy = dict(payload.get("diversification_proxy") or {})
        lines = [
            f"# Strategy Family Edge Review: {payload['family']}",
            "",
            f"- generated_at: {payload['generated_at']}",
            f"- family: {payload['family']}",
            f"- peer_family: {payload.get('peer_family') or 'n/a'}",
            f"- role: {payload['role']}",
            f"- symbol_filter: {payload.get('symbol_filter') or 'global'}",
            f"- version: {payload['version']}",
            f"- days: {payload['days']}",
            f"- actual_money_basis: {payload['actual_money_basis']}",
            "",
            "## Headline",
            "",
            f"- edge_state: {payload['edge_state']}",
            f"- analysis_bias: {payload['analysis_bias']}",
            f"- summary: {payload['summary']}",
            "",
            "## Core Metrics",
            "",
            (
                f"- post_cost: trades={int(target.get('trades', 0))}, win_rate={float(target.get('win_rate', 0.0)):.4f}, "
                f"ev={float(target.get('ev', 0.0)):.4f}, p5={float(target.get('p5_ev', 0.0)):.4f}, "
                f"max_dd={float(target.get('max_drawdown', 0.0)):.4f}, ulcer={float(target.get('ulcer_index', 0.0)):.4f}"
            ),
            (
                f"- raw_realized: trades={int(raw.get('trades', 0))}, win_rate={float(raw.get('win_rate', 0.0)):.4f}, "
                f"ev={float(raw.get('ev', 0.0)):.4f}, max_dd={float(raw.get('max_drawdown', 0.0)):.4f}"
            ),
            (
                f"- trade_frequency: trades_per_7d={float(freq.get('trades_per_7d', 0.0)):.4f}, "
                f"trades_per_30d={float(freq.get('trades_per_30d', 0.0)):.4f}, active_weeks={int(freq.get('active_weeks', 0))}, "
                f"active_months={int(freq.get('active_months', 0))}"
            ),
            "",
            "## Regime Breakdown",
        ]
        for row in payload.get("regime_breakdown") or []:
            lines.append(
                f"- {row['key']}: trades={int(row['trades'])}, ev={float(row['ev']):.4f}, p5={float(row['p5_ev']):.4f}, "
                f"max_dd={float(row['max_drawdown']):.4f}, time_failure_ratio={float(row['time_failure_ratio']):.4f}"
            )
        lines.extend(["", "## Session Breakdown"])
        for row in payload.get("session_breakdown") or []:
            lines.append(
                f"- {row['key']}: trades={int(row['trades'])}, ev={float(row['ev']):.4f}, p5={float(row['p5_ev']):.4f}, "
                f"max_dd={float(row['max_drawdown']):.4f}, time_failure_ratio={float(row['time_failure_ratio']):.4f}"
            )
        lines.extend(["", "## Calendar Breakdown"])
        for row in payload.get("monthly_breakdown") or []:
            lines.append(
                f"- month {row['key']}: trades={int(row['trades'])}, total_post_cost_r={float(row['total_post_cost_r']):.4f}, "
                f"avg_post_cost_r={float(row['avg_post_cost_r']):.4f}, win_rate={float(row['win_rate']):.4f}"
            )
        lines.extend(["", "## Peer Comparison"])
        lines.append(
            f"- peer_metrics: trades={int(peer.get('trades', 0))}, ev={float(peer.get('ev', 0.0)):.4f}, "
            f"max_dd={float(peer.get('max_drawdown', 0.0)):.4f}"
        )
        lines.append(
            f"- comparison_gap: ev_gap={float(payload.get('ev_gap_vs_peer', 0.0)):.4f}, "
            f"max_drawdown_gap={float(payload.get('max_drawdown_gap_vs_peer', 0.0)):.4f}"
        )
        if proxy:
            lines.extend(
                [
                    "",
                    "## Diversification Proxy",
                    f"- daily_post_cost_correlation: {proxy.get('daily_post_cost_correlation')}",
                    f"- correlation_state: {proxy.get('correlation_state')}",
                    f"- overlap_ratio: {float(proxy.get('overlap_ratio', 0.0)):.4f}",
                    f"- drawdown_contribution_state: {proxy.get('drawdown_contribution_state')}",
                    f"- combined_max_drawdown: {float(dict(proxy.get('combined_drawdown') or {}).get('max_drawdown', 0.0)):.4f}",
                    f"- drawdown_delta_vs_peer: {float(proxy.get('drawdown_delta_vs_peer', 0.0)):.4f}",
                ]
            )
        lines.extend(["", "## Next Actions"])
        for step in payload.get("next_actions") or []:
            lines.append(f"- {step}")
        file_path.write_text("\n".join(lines), encoding="utf-8")
        return str(file_path)

    def generate_from_plans(
        self,
        *,
        family: str,
        peer_family: str | None = None,
        plans: list[Plan],
        symbol: str | None = None,
        version: str,
        write_report: bool = True,
        days: int = 180,
    ) -> dict[str, Any]:
        normalized_family = str(family or "").strip().lower()
        normalized_peer = str(peer_family or self._default_peer_family(normalized_family)).strip().lower()
        role = self._role(normalized_family)
        closed_records = [
            record
            for record in (self._closed_trade(plan, symbol=symbol, version=version) for plan in plans)
            if record is not None
        ]
        fill_map = self.stress._fill_map(plans)
        plan_lookup = {str(plan.plan_id): plan for plan in plans}
        adjusted_records = []
        for record in closed_records:
            plan = plan_lookup.get(record.plan_id)
            if plan is None:
                continue
            adjusted_records.append(
                self.stress._adjust_trade(
                    plan=plan,
                    record=record,
                    fills=list(fill_map.get(record.plan_id) or []),
                )
            )
        target_adjusted = [row for row in adjusted_records if row.base.strategy_family == normalized_family]
        peer_adjusted = [row for row in adjusted_records if row.base.strategy_family == normalized_peer]
        target_post_cost = [self._to_adjusted_record(row) for row in target_adjusted]
        peer_post_cost = [self._to_adjusted_record(row) for row in peer_adjusted]
        target_raw = [row.base for row in target_adjusted]
        peer_raw = [row.base for row in peer_adjusted]

        target_metrics = self.validation._mode_metrics(target_post_cost)
        peer_metrics = self.validation._mode_metrics(peer_post_cost)
        raw_metrics = self.validation._mode_metrics(target_raw)
        trade_frequency = self._frequency(target_post_cost)
        regime_breakdown = self._group_metrics(target_post_cost, key_func=lambda record: record.regime)
        session_breakdown = self._group_metrics(
            target_post_cost,
            key_func=lambda record: self.validation._session_bucket(record.closed_ts),
        )
        monthly_breakdown = self._calendar_rows(target_post_cost, by="month")
        weekly_breakdown = self._calendar_rows(target_post_cost, by="week")
        positive_rate = self._positive_rate(target_post_cost)
        diversification_proxy = self._diversification_proxy(
            target_daily=self._daily_return_map(target_post_cost),
            peer_daily=self._daily_return_map(peer_post_cost),
        ) if normalized_peer else {}
        edge_state, analysis_bias, summary = self._edge_decision(
            role=role,
            metrics=target_metrics,
            positive_rate=positive_rate,
            diversification_proxy=diversification_proxy,
        )
        top_regime = regime_breakdown[0] if regime_breakdown else None
        top_session = session_breakdown[0] if session_breakdown else None
        payload: dict[str, Any] = {
            "schema_version": "strategy_family_edge_review_v1",
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "family": normalized_family,
            "peer_family": normalized_peer or None,
            "role": role,
            "symbol_filter": symbol.upper() if symbol else None,
            "version": version,
            "days": int(days),
            "available": bool(target_post_cost),
            "actual_money_basis": "post_cost_realized_r_baseline_adjusted",
            "edge_state": edge_state,
            "analysis_bias": analysis_bias,
            "summary": summary,
            "target_metrics": target_metrics,
            "raw_metrics": raw_metrics,
            "peer_metrics": peer_metrics,
            "positive_rate": positive_rate,
            "trade_frequency": trade_frequency,
            "regime_breakdown": regime_breakdown,
            "session_breakdown": session_breakdown,
            "monthly_breakdown": monthly_breakdown,
            "weekly_breakdown": weekly_breakdown,
            "diversification_proxy": diversification_proxy,
            "ev_gap_vs_peer": round(
                float(target_metrics.get("ev", 0.0) or 0.0) - float(peer_metrics.get("ev", 0.0) or 0.0),
                4,
            ),
            "max_drawdown_gap_vs_peer": round(
                float(target_metrics.get("max_drawdown", 0.0) or 0.0) - float(peer_metrics.get("max_drawdown", 0.0) or 0.0),
                4,
            ),
            "next_actions": self._next_actions(
                role=role,
                edge_state=edge_state,
                frequency=trade_frequency,
                top_regime=top_regime,
                top_session=top_session,
                diversification_proxy=diversification_proxy,
            ),
            "report_path": None,
        }
        if write_report:
            now = datetime.now(timezone.utc).replace(microsecond=0)
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload

    def generate(
        self,
        *,
        family: str,
        peer_family: str | None = None,
        days: int = 180,
        symbol: str | None = None,
        version: str | None = None,
        write_report: bool = True,
        limit: int = 10000,
    ) -> dict[str, Any]:
        if self.plan_repo is None:
            raise RuntimeError("plan_repo_not_configured")
        active_version = str(version or self.settings.strategy_version)
        if symbol:
            plans = self.plan_repo.list_recent(symbol=symbol, days=days)
            plans = [plan for plan in plans if str(plan.state) == PlanState.CLOSED.value]
        else:
            plans = self.plan_repo.list_recent_global(
                timeframe="5m",
                days=days,
                states=[PlanState.CLOSED.value],
                limit=limit,
            )
        return self.generate_from_plans(
            family=family,
            peer_family=peer_family,
            plans=plans,
            symbol=symbol,
            version=active_version,
            write_report=write_report,
            days=days,
        )
