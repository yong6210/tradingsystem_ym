from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import CURRENT_MICRO_LIVE_USDT_SYMBOLS, get_settings
from app.core.enums import PlanState, RiskGateState
from app.db.models import Plan
from app.db.repositories import CandleRepository, PlanRepository
from app.services.candidate_expectations import expectation_contract
from app.services.b_continuation_activation import BContinuationActivationService
from app.services.operator_text import entry_condition_message, why_now_message
from app.services.portfolio_risk_overlay import PortfolioRiskOverlayService
from app.services.session_guidance import SessionGuidanceService
from app.services.strategy_cluster_balance import StrategyClusterBalanceService
from app.services.thesis_fingerprint import ThesisFingerprintService
from app.services.multi_strategy_ab import MultiStrategyABExpansionService

# Static bootstrap universe for USDC-margined perpetuals.
USDC_PERP_TOP30 = [
    "BTCUSDC",
    "ETHUSDC",
    "SOLUSDC",
    "BNBUSDC",
    "XRPUSDC",
    "ADAUSDC",
    "DOGEUSDC",
    "AVAXUSDC",
    "DOTUSDC",
    "LINKUSDC",
    "LTCUSDC",
    "BCHUSDC",
    "TRXUSDC",
    "NEARUSDC",
    "ATOMUSDC",
    "APTUSDC",
    "ARBUSDC",
    "OPUSDC",
    "MATICUSDC",
    "SUIUSDC",
    "SEIUSDC",
    "ETCUSDC",
    "INJUSDC",
    "FILUSDC",
    "UNIUSDC",
    "AAVEUSDC",
    "RUNEUSDC",
    "TIAUSDC",
    "WIFUSDC",
    "PEPEUSDC",
]
USDT_RELIABLE_BALANCED_31 = [item for item in CURRENT_MICRO_LIVE_USDT_SYMBOLS.split(",") if item]

_THESIS = ThesisFingerprintService()


def get_universe_symbols(universe: str) -> list[str]:
    normalized = str(universe or "").strip().lower()
    if normalized == "usdt_reliable_balanced_31":
        return USDT_RELIABLE_BALANCED_31
    if normalized == "usdc_perp_top30":
        return USDC_PERP_TOP30
    return []


def list_scanner_items(
    *,
    db: Session,
    universe: str,
    limit: int,
    risk_state: RiskGateState,
) -> list[dict]:
    now = datetime.now(timezone.utc)
    symbols = get_universe_symbols(universe)
    if not symbols:
        return []

    stmt = (
        select(Plan)
        .where(
            Plan.symbol.in_(symbols),
            Plan.state.in_([PlanState.PLANNED.value, PlanState.ARMED.value]),
            Plan.valid_until > now,
        )
        .order_by(desc(Plan.ev), desc(Plan.confidence), desc(Plan.rr_base))
        .limit(max(limit * 4, limit))
    )
    plans = list(db.scalars(stmt))
    rows = [_plan_to_item(plan, risk_state) for plan in plans]
    rows.sort(key=lambda row: row["final_rank_score"], reverse=True)
    return rows[:limit]


def _plan_to_item(plan: Plan, risk_state: RiskGateState) -> dict:
    friction_penalty = max(0.0, plan.cost_est * 100.0)
    rank = plan.ev * 100.0 + plan.confidence * 20.0 + plan.rr_base * 8.0 - friction_penalty
    validity = dict(plan.validity or {})
    runtime_signal_shadow_tilt = dict(
        validity.get("runtime_signal_shadow_tilt")
        or dict(validity.get("strategy_sizing") or {}).get("runtime_signal_shadow_tilt")
        or {}
    )
    expectations = expectation_contract(
        validity=validity,
        ev=float(plan.ev),
        recommended_risk_r=float(validity.get("recommended_risk_r", 0.0) or 0.0),
    )
    validity.update(expectations)
    thesis_fingerprint = _THESIS.build_from_plan(plan)
    active_mode = getattr(get_settings().strategy_mode, "value", str(get_settings().strategy_mode))
    strategy_family_reason = str(validity.get("strategy_family_reason", "") or "").strip()

    if risk_state == RiskGateState.THROTTLED:
        rank *= 0.6
    elif risk_state == RiskGateState.CLOSED:
        rank = 0.0

    return {
        "symbol": plan.symbol,
        "plan_id": plan.plan_id,
        "zone_id": plan.zone_id,
        "direction": plan.direction,
        "strategy_mode": str(active_mode),
        "deployment_go_no_go": "GO",
        "deployment_code": "go_runtime_gate_open",
        "deployment_message": "GO: runtime gate is open for candidate review.",
        "risk_reason": "normal",
        "operating_lock": None,
        "session_guidance": None,
        "session_penalty": 0.0,
        "strategy_family": str(validity.get("strategy_family", "legacy_zone_plan")),
        "strategy_grade": validity.get("strategy_grade"),
        "strategy_family_reason": strategy_family_reason or None,
        "strategy_scorecard": validity.get("strategy_scorecard"),
        "strategy_scorecard_buckets": dict(validity.get("strategy_scorecard_buckets") or {}),
        "strategy_scorecard_raw_components": dict(validity.get("strategy_scorecard_raw_components") or {}),
        "reaction_evidence": validity.get("reaction_evidence"),
        "location_reference": validity.get("location_reference"),
        "session_liquidity_reference": validity.get("session_liquidity_reference"),
        "strategy_sizing": validity.get("strategy_sizing"),
        "runtime_signal_shadow_tilt": runtime_signal_shadow_tilt,
        "recommended_risk_r": float(validity.get("recommended_risk_r", 0.0) or 0.0),
        "expected_win_prob": expectations["expected_win_prob"],
        "expected_ev_r": expectations["expected_ev_r"],
        "expected_tp1_prob": expectations["expected_tp1_prob"],
        "expected_tp2_prob": expectations["expected_tp2_prob"],
        "expected_tp3_prob": expectations["expected_tp3_prob"],
        "expected_ev_at_recommended_size_r": expectations["expected_ev_at_recommended_size_r"],
        "expected_summary": expectations["expected_summary"],
        "entry_condition": entry_condition_message(plan.entry_condition, fallback_entry_model=plan.entry_model),
        "why_now": why_now_message(strategy_family_reason),
        "operator_status": "none",
        "block_reason": None,
        "block_reason_message": None,
        "entry_model": plan.entry_model,
        "regime": str(validity.get("regime", "range")),
        "valid_from": plan.valid_from,
        "validity": validity,
        "final_rank_score": round(rank, 4),
        "ev": plan.ev,
        "rr_base": plan.rr_base,
        "friction_penalty": round(friction_penalty, 4),
        "portfolio_penalty": 0.0,
        "portfolio_high_corr_count": 0,
        "risk_budget_score": 100.0,
        "portfolio_volatility": 0.0,
        "portfolio_total_cap": 0,
        "portfolio_directional_cap": 0,
        "portfolio_cluster_cap": 0,
        "thesis_fingerprint": thesis_fingerprint,
        "thesis_cluster_id": str(validity.get("thesis_cluster_id") or _THESIS.thesis_cluster_id(thesis_fingerprint)),
        "thesis_cluster_size": int(validity.get("thesis_cluster_size", 1) or 1),
        "thesis_primary_symbol": validity.get("thesis_primary_symbol") or plan.symbol,
        "thesis_rejected_reason": validity.get("thesis_rejected_reason"),
    }


def _runtime_deployment_language(
    *,
    risk_state: RiskGateState,
    risk_reason: str,
    operating_lock: dict | None,
) -> dict[str, str]:
    lock = dict(operating_lock or {})
    if PortfolioRiskOverlayService._safe_bool(lock.get("active")):
        reason = str(lock.get("reason", "operating_lock_active"))
        return {
            "deployment_go_no_go": "NO_GO",
            "deployment_code": "no_go_operating_lock_active",
            "deployment_message": (
                f"NO_GO: operating lock is active ({reason}). Scanner candidates are view-only until the lock is cleared."
            ),
        }
    if risk_state == RiskGateState.CLOSED:
        return {
            "deployment_go_no_go": "NO_GO",
            "deployment_code": "no_go_risk_gate_closed",
            "deployment_message": (
                f"NO_GO: runtime risk gate is closed ({risk_reason}). Scanner candidates are view-only."
            ),
        }
    if risk_state == RiskGateState.THROTTLED:
        return {
            "deployment_go_no_go": "MANUAL_REVIEW",
            "deployment_code": "manual_review_risk_gate_throttled",
            "deployment_message": (
                f"MANUAL_REVIEW: runtime risk gate is throttled ({risk_reason}). Reduce size and review before acting."
            ),
        }
    return {
        "deployment_go_no_go": "GO",
        "deployment_code": "go_runtime_gate_open",
        "deployment_message": "GO: runtime gate is open for candidate review.",
    }


class ScannerService:
    """Engine-facing scanner wrapper using repository methods."""

    def __init__(self, plan_repo: PlanRepository, candle_repo: CandleRepository):
        self.plan_repo = plan_repo
        self.overlay = PortfolioRiskOverlayService(candle_repo=candle_repo)
        self.session_guidance = SessionGuidanceService(self.overlay.settings)
        self.multi_strategy_ab = MultiStrategyABExpansionService()
        self.b_continuation_activation = BContinuationActivationService()
        self.strategy_cluster_balance = StrategyClusterBalanceService()

    def plan_to_item(self, *, plan: Plan, risk_state: RiskGateState = RiskGateState.OPEN) -> dict[str, object]:
        return _plan_to_item(plan, risk_state)

    def candidate_rows(
        self,
        *,
        symbols: list[str],
        risk_state: RiskGateState = RiskGateState.OPEN,
        plans_per_symbol: int = 3,
    ) -> list[dict]:
        rows: list[dict] = []
        per_symbol = max(1, int(plans_per_symbol))
        for symbol in symbols:
            plans = self.plan_repo.list_top(symbol=symbol, timeframe="5m", limit=per_symbol)
            rows.extend(_plan_to_item(plan, risk_state) for plan in plans)
        rows.sort(key=lambda row: row["final_rank_score"], reverse=True)
        return self.strategy_cluster_balance.annotate_rows(
            self.b_continuation_activation.annotate_rows(self.multi_strategy_ab.annotate_rows(rows))
        )

    def _decorate_runtime_rows(
        self,
        *,
        rows: list[dict[str, object]],
        risk_state: RiskGateState,
        risk_reason: str,
        operating_lock: dict | None,
    ) -> None:
        guidance = self.session_guidance.snapshot(
            operating_lock=operating_lock,
            strategy_mode=self.overlay.mode.policy().mode,
        )
        deployment_language = _runtime_deployment_language(
            risk_state=risk_state,
            risk_reason=risk_reason,
            operating_lock=operating_lock,
        )
        for row in rows:
            row["deployment_go_no_go"] = deployment_language["deployment_go_no_go"]
            row["deployment_code"] = deployment_language["deployment_code"]
            row["deployment_message"] = deployment_language["deployment_message"]
            row["risk_reason"] = risk_reason
            row["operating_lock"] = dict(operating_lock or {})
            row["session_guidance"] = dict(guidance)
            row["session_penalty"] = float(guidance.get("soft_penalty", 0.0) or 0.0)

    @staticmethod
    def _apply_operator_status(rows: list[dict[str, object]]) -> list[dict[str, object]]:
        for row in rows:
            if PortfolioRiskOverlayService._safe_bool(row.get("accepted")):
                row["operator_status"] = "accepted"
            elif row.get("block_reason"):
                row["operator_status"] = "blocked"
            else:
                row["operator_status"] = "none"
        rows.sort(key=lambda row: float(row.get("final_rank_score", 0.0) or 0.0), reverse=True)
        return rows

    def assess_candidate_rows(
        self,
        *,
        rows: list[dict[str, object]],
        risk_state: RiskGateState = RiskGateState.OPEN,
        risk_reason: str = "normal",
        operating_lock: dict | None = None,
        existing_exposures: list[tuple[str, str] | dict] | list[Plan] | None = None,
        today_trade_count: int = 0,
        outcome_inputs_by_symbol: dict[str, dict[str, object]] | None = None,
    ) -> list[dict]:
        mutable_rows = [dict(row) for row in rows]
        self._decorate_runtime_rows(
            rows=mutable_rows,
            risk_state=risk_state,
            risk_reason=risk_reason,
            operating_lock=operating_lock,
        )
        assessed = self.overlay.assess_rows(
            mutable_rows,
            existing_exposures=existing_exposures,
            today_trade_count=today_trade_count,
            operating_lock=operating_lock,
            outcome_inputs_by_symbol=outcome_inputs_by_symbol,
        )
        annotated: list[dict[str, Any]] = []
        for row in [dict(item) for item in self._apply_operator_status(assessed)]:
            symbol_inputs = dict(
                dict(outcome_inputs_by_symbol or {}).get(str(row.get("symbol") or "").upper()) or {}
            )
            item = self.multi_strategy_ab.annotate_rows(
                [row],
                score_to_outcome_funnel=dict(symbol_inputs.get("score_to_outcome_funnel_summary") or {}),
                family_execution_degradation_advisory=dict(
                    symbol_inputs.get("family_execution_degradation_advisory_summary") or {}
                ),
                rollout_recommendation=dict(symbol_inputs.get("rollout_recommendation_summary") or {}),
            )[0]
            annotated.append(dict(item))
        return self.strategy_cluster_balance.annotate_rows(
            self.b_continuation_activation.annotate_rows(
                annotated,
                outcome_inputs_by_symbol=outcome_inputs_by_symbol,
            )
        )

    def assessed_symbol_candidates(
        self,
        *,
        symbol: str,
        risk_state: RiskGateState = RiskGateState.OPEN,
        risk_reason: str = "normal",
        operating_lock: dict | None = None,
        existing_exposures: list[tuple[str, str] | dict] | list[Plan] | None = None,
        today_trade_count: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        plans = self.plan_repo.list_active_for_symbol(symbol=symbol, timeframe="5m", limit=limit)
        rows = [self.plan_to_item(plan=plan, risk_state=risk_state) for plan in plans]
        if not rows:
            return []
        return self.assess_candidate_rows(
            rows=rows,
            risk_state=risk_state,
            risk_reason=risk_reason,
            operating_lock=operating_lock,
            existing_exposures=existing_exposures,
            today_trade_count=today_trade_count,
        )

    def top_assessed_candidate(
        self,
        *,
        symbol: str,
        risk_state: RiskGateState = RiskGateState.OPEN,
        risk_reason: str = "normal",
        operating_lock: dict | None = None,
        existing_exposures: list[tuple[str, str] | dict] | list[Plan] | None = None,
        today_trade_count: int = 0,
        limit: int = 100,
    ) -> dict | None:
        rows = self.assessed_symbol_candidates(
            symbol=symbol,
            risk_state=risk_state,
            risk_reason=risk_reason,
            operating_lock=operating_lock,
            existing_exposures=existing_exposures,
            today_trade_count=today_trade_count,
            limit=limit,
        )
        return dict(rows[0]) if rows else None

    def top_opportunities(
        self,
        *,
        symbols: list[str],
        limit: int = 20,
        risk_state: RiskGateState = RiskGateState.OPEN,
        risk_reason: str = "normal",
        operating_lock: dict | None = None,
        existing_exposures: list[tuple[str, str] | dict] | list[Plan] | None = None,
        today_trade_count: int = 0,
        outcome_inputs_by_symbol: dict[str, dict[str, object]] | None = None,
    ) -> list[dict]:
        rows = self.candidate_rows(symbols=symbols, risk_state=risk_state, plans_per_symbol=3)
        self._decorate_runtime_rows(
            rows=rows,
            risk_state=risk_state,
            risk_reason=risk_reason,
            operating_lock=operating_lock,
        )
        if risk_state == RiskGateState.CLOSED:
            return rows[:limit]
        assessed = self.assess_candidate_rows(
            rows=rows,
            risk_state=risk_state,
            risk_reason=risk_reason,
            operating_lock=operating_lock,
            existing_exposures=existing_exposures,
            today_trade_count=today_trade_count,
            outcome_inputs_by_symbol=outcome_inputs_by_symbol,
        )
        accepted = [row for row in assessed if PortfolioRiskOverlayService._safe_bool(row.get("accepted"))]
        accepted.sort(key=lambda row: float(row.get("final_rank_score", 0.0) or 0.0), reverse=True)
        return accepted[:limit]
