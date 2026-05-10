from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.enums import PlanState
from app.db.models import Plan
from app.db.repositories import ExecutionFillRepository, PlanRepository
from app.services.report_io import atomic_write_text
from app.services.strategy_family_edge_review import StrategyFamilyEdgeReviewService


class LiveAlphaOperatingReviewService:
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
        self.family_review = StrategyFamilyEdgeReviewService(
            settings=self.settings,
            plan_repo=self.plan_repo,
            fill_repo=self.fill_repo,
        )

    @staticmethod
    def _monthly_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
        totals = [float(row.get("total_post_cost_r", 0.0) or 0.0) for row in rows]
        if not totals:
            return {
                "months": 0,
                "avg_post_cost_r": 0.0,
                "best_month_r": 0.0,
                "worst_month_r": 0.0,
                "positive_month_ratio": 0.0,
                "latest_month_r": 0.0,
            }
        positives = sum(1 for value in totals if value > 0.0)
        return {
            "months": len(totals),
            "avg_post_cost_r": round(sum(totals) / len(totals), 4),
            "best_month_r": round(max(totals), 4),
            "worst_month_r": round(min(totals), 4),
            "positive_month_ratio": round(positives / len(totals), 4),
            "latest_month_r": round(totals[-1], 4),
        }

    def _family_projection(self, review: dict[str, Any]) -> dict[str, Any]:
        metrics = dict(review.get("target_metrics") or {})
        monthly_stats = self._monthly_stats(list(review.get("monthly_breakdown") or []))
        ev_per_trade = float(metrics.get("ev", 0.0) or 0.0)
        p5_per_trade = float(metrics.get("p5_ev", 0.0) or 0.0)
        trades = int(metrics.get("trades", 0) or 0)
        review_days = max(1, int(review.get("days", 0) or 0))
        # Use the requested review horizon, not the first/last trade span, so thin samples do not over-project.
        trades_per_30d = round((trades / review_days) * 30.0, 4)
        return {
            "family": review.get("family"),
            "role": review.get("role"),
            "edge_state": review.get("edge_state"),
            "analysis_bias": review.get("analysis_bias"),
            "trades": trades,
            "win_rate": float(metrics.get("win_rate", 0.0) or 0.0),
            "ev_per_trade_r": round(ev_per_trade, 4),
            "p5_per_trade_r": round(p5_per_trade, 4),
            "max_drawdown_r": round(float(metrics.get("max_drawdown", 0.0) or 0.0), 4),
            "projection_window_days": review_days,
            "trades_per_30d": round(trades_per_30d, 4),
            "projected_30d_post_cost_r": round(ev_per_trade * trades_per_30d, 4),
            "projected_30d_floor_r": round(p5_per_trade * trades_per_30d, 4),
            "observed_monthly": monthly_stats,
        }

    @staticmethod
    def _merge_monthly(a_rows: list[dict[str, Any]], b_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        totals: dict[str, dict[str, Any]] = defaultdict(lambda: {"total_post_cost_r": 0.0, "trades": 0})
        for row in list(a_rows) + list(b_rows):
            key = str(row.get("key") or "unknown")
            totals[key]["total_post_cost_r"] += float(row.get("total_post_cost_r", 0.0) or 0.0)
            totals[key]["trades"] += int(row.get("trades", 0) or 0)
        merged = []
        for key in sorted(totals):
            total = round(float(totals[key]["total_post_cost_r"]), 4)
            trades = int(totals[key]["trades"])
            merged.append(
                {
                    "key": key,
                    "trades": trades,
                    "total_post_cost_r": total,
                    "avg_post_cost_r": round(total / trades, 4) if trades else 0.0,
                    "win_rate": 1.0 if total > 0.0 else 0.0,
                }
            )
        return merged

    @staticmethod
    def _portfolio_state(a_review: dict[str, Any], b_review: dict[str, Any]) -> tuple[str, str]:
        a_state = str(a_review.get("edge_state") or "insufficient_sample")
        b_state = str(b_review.get("edge_state") or "insufficient_sample")
        if a_state == "insufficient_edge":
            return "anchor_at_risk", "A anchor does not currently clear the minimum after-cost threshold."
        if a_state == "insufficient_sample":
            return "needs_more_a_evidence", "A anchor still needs more closed evidence before sizing confidence can increase."
        if b_state == "validated_edge":
            return "a_anchor_with_b_optional", "A remains the anchor and B now looks optional as a diversification sleeve."
        if b_state == "fragile_edge":
            return "a_anchor_b_guarded", "A remains the anchor while B stays guarded for more diversification evidence."
        if b_state == "insufficient_edge":
            return "a_anchor_only", "A remains the anchor and B should stay out of live confidence decisions."
        return "a_anchor_collecting_b_evidence", "A remains the anchor while B still needs more sample."

    @staticmethod
    def _next_actions(a_review: dict[str, Any], b_review: dict[str, Any], portfolio: dict[str, Any]) -> list[str]:
        actions = [
            "Use after-cost EV, trade frequency, and max drawdown as the first operating lens before any threshold change.",
        ]
        actions.extend(list(a_review.get("next_actions") or [])[:2])
        actions.extend(list(b_review.get("next_actions") or [])[:2])
        correlation_state = str(portfolio.get("correlation_state") or "unknown_overlap")
        if correlation_state == "high_overlap_proxy":
            actions.append("Do not treat B as diversification until overlap drops below the current proxy threshold.")
        deduped: list[str] = []
        seen: set[str] = set()
        for step in actions:
            if step in seen:
                continue
            seen.add(step)
            deduped.append(step)
        return deduped[:5]

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.live_alpha_operating_review_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        scope = str(payload.get("symbol_filter") or "global").lower()
        file_path = out_dir / f"live_alpha_operating_review_{scope}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        a_projection = dict(payload.get("a_projection") or {})
        b_projection = dict(payload.get("b_projection") or {})
        portfolio = dict(payload.get("portfolio_projection") or {})
        lines = [
            "# Live Alpha Operating Review",
            "",
            f"- generated_at: {payload['generated_at']}",
            f"- symbol_filter: {payload.get('symbol_filter') or 'global'}",
            f"- version: {payload['version']}",
            f"- days: {payload['days']}",
            "",
            "## Headline",
            "",
            f"- portfolio_state: {payload['portfolio_state']}",
            f"- summary: {payload['summary']}",
            f"- correlation_state: {portfolio.get('correlation_state')}",
            f"- drawdown_interaction_state: {portfolio.get('drawdown_interaction_state')}",
            "",
            "## A Anchor Review",
            "",
            (
                f"- edge_state: {a_projection.get('edge_state')}, bias: {a_projection.get('analysis_bias')}, "
                f"trades={a_projection.get('trades')}, ev/trade={a_projection.get('ev_per_trade_r')}, "
                f"trades_per_30d={a_projection.get('trades_per_30d')}, projected_30d_r={a_projection.get('projected_30d_post_cost_r')}"
            ),
            (
                f"- observed_monthly: avg={dict(a_projection.get('observed_monthly') or {}).get('avg_post_cost_r')}, "
                f"best={dict(a_projection.get('observed_monthly') or {}).get('best_month_r')}, "
                f"worst={dict(a_projection.get('observed_monthly') or {}).get('worst_month_r')}"
            ),
            "",
            "## B Diversification Review",
            "",
            (
                f"- edge_state: {b_projection.get('edge_state')}, bias: {b_projection.get('analysis_bias')}, "
                f"trades={b_projection.get('trades')}, ev/trade={b_projection.get('ev_per_trade_r')}, "
                f"trades_per_30d={b_projection.get('trades_per_30d')}, projected_30d_r={b_projection.get('projected_30d_post_cost_r')}"
            ),
            (
                f"- observed_monthly: avg={dict(b_projection.get('observed_monthly') or {}).get('avg_post_cost_r')}, "
                f"best={dict(b_projection.get('observed_monthly') or {}).get('best_month_r')}, "
                f"worst={dict(b_projection.get('observed_monthly') or {}).get('worst_month_r')}"
            ),
            "",
            "## Monthly Projection Proxy",
            "",
            f"- projection_basis: {portfolio.get('projection_basis')}",
            f"- combined_projected_30d_post_cost_r: {portfolio.get('combined_projected_30d_post_cost_r')}",
            f"- combined_projected_30d_floor_r: {portfolio.get('combined_projected_30d_floor_r')}",
            (
                f"- observed_monthly: avg={dict(portfolio.get('observed_monthly') or {}).get('avg_post_cost_r')}, "
                f"best={dict(portfolio.get('observed_monthly') or {}).get('best_month_r')}, "
                f"worst={dict(portfolio.get('observed_monthly') or {}).get('worst_month_r')}, "
                f"positive_month_ratio={dict(portfolio.get('observed_monthly') or {}).get('positive_month_ratio')}"
            ),
            "",
            "## Next Actions",
        ]
        for step in payload.get("next_actions") or []:
            lines.append(f"- {step}")
        atomic_write_text(file_path, "\n".join(lines))
        return str(file_path)

    def generate_from_plans(
        self,
        *,
        plans: list[Plan],
        symbol: str | None = None,
        version: str,
        days: int = 180,
        write_report: bool = True,
    ) -> dict[str, Any]:
        a_review = self.family_review.generate_from_plans(
            family="sweep_reversal",
            peer_family="trend_continuation",
            plans=plans,
            symbol=symbol,
            version=version,
            write_report=False,
            days=days,
        )
        b_review = self.family_review.generate_from_plans(
            family="trend_continuation",
            peer_family="sweep_reversal",
            plans=plans,
            symbol=symbol,
            version=version,
            write_report=False,
            days=days,
        )
        a_projection = self._family_projection(a_review)
        b_projection = self._family_projection(b_review)
        merged_monthly = self._merge_monthly(
            list(a_review.get("monthly_breakdown") or []),
            list(b_review.get("monthly_breakdown") or []),
        )
        observed_monthly = self._monthly_stats(merged_monthly)
        b_proxy = dict(b_review.get("diversification_proxy") or {})
        portfolio_projection = {
            "projection_basis": "family_ev_x_trade_frequency_additive_proxy",
            "combined_projected_30d_post_cost_r": round(
                float(a_projection.get("projected_30d_post_cost_r", 0.0) or 0.0)
                + float(b_projection.get("projected_30d_post_cost_r", 0.0) or 0.0),
                4,
            ),
            "combined_projected_30d_floor_r": round(
                float(a_projection.get("projected_30d_floor_r", 0.0) or 0.0)
                + float(b_projection.get("projected_30d_floor_r", 0.0) or 0.0),
                4,
            ),
            "observed_monthly": observed_monthly,
            "correlation_state": b_proxy.get("correlation_state"),
            "drawdown_interaction_state": b_proxy.get("drawdown_contribution_state"),
        }
        portfolio_state, summary = self._portfolio_state(a_review, b_review)
        payload: dict[str, Any] = {
            "schema_version": "live_alpha_operating_review_v1",
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "symbol_filter": symbol.upper() if symbol else None,
            "version": version,
            "days": int(days),
            "portfolio_state": portfolio_state,
            "summary": summary,
            "a_review": a_review,
            "b_review": b_review,
            "a_projection": a_projection,
            "b_projection": b_projection,
            "portfolio_projection": portfolio_projection,
            "next_actions": self._next_actions(a_review, b_review, portfolio_projection),
            "report_path": None,
        }
        if write_report:
            now = datetime.now(timezone.utc).replace(microsecond=0)
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload

    def generate(
        self,
        *,
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
            plans=plans,
            symbol=symbol,
            version=active_version,
            days=days,
            write_report=write_report,
        )
