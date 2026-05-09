from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.enums import ExecutionMode, OrderLifecycleState, PlanState, RiskGateState
from app.db.models import Plan
from app.db.repositories import OrderSubmissionRepository, PlanRepository
from app.services.b_continuation_activation import BContinuationActivationService
from app.services.edge_experiment_review import build_edge_experiment_review, summarize_edge_experiment_review
from app.services.edge_evolution_rule import build_edge_evolution_rule, summarize_edge_evolution_rule
from app.services.scanner import ScannerService, _runtime_deployment_language
from app.services.split_review_followup_ledger import summarize_split_review_followup_ledger
from app.services.strategy_mode import StrategyModeService
from app.services.strategy_cluster_balance import StrategyClusterBalanceService
from app.services.multi_strategy_ab import MultiStrategyABExpansionService


def _dict(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict(payload or {})


def _plan_regime(plan: Plan) -> str:
    validity = dict(plan.validity or {})
    regime = str(validity.get("regime", "range")).lower()
    if regime in {"trend", "range", "shock"}:
        return regime
    return "range"


def _state_kind(state: str) -> str:
    if state in {PlanState.ENTERED.value, PlanState.PARTIAL_EXIT.value}:
        return "live"
    if state in {PlanState.ARMED.value, PlanState.TRIGGERED.value}:
        return "pre_entry"
    if state == PlanState.PLANNED.value:
        return "planned"
    return "other"


def _portfolio_playbook_mapping(deployment_language: dict[str, str]) -> dict[str, str]:
    deployment_go_no_go = str(deployment_language.get("deployment_go_no_go", "MANUAL_REVIEW") or "MANUAL_REVIEW")
    deployment_code = str(deployment_language.get("deployment_code", "") or "")

    if deployment_code == "no_go_operating_lock_active":
        return {
            "playbook_go_no_go": "NO_GO",
            "playbook_code": "no_go_portfolio_operating_lock_active",
            "playbook_action": "hold_new_entries_until_operating_lock_clears",
            "playbook_message": "NO_GO: operating lock is active. Keep portfolio in monitor-only mode until the lock clears.",
        }
    if deployment_code == "no_go_risk_gate_closed":
        return {
            "playbook_go_no_go": "NO_GO",
            "playbook_code": "no_go_portfolio_risk_gate_closed",
            "playbook_action": "hold_new_entries_until_risk_gate_reopens",
            "playbook_message": "NO_GO: runtime risk gate is closed. Do not add new exposure until the gate reopens.",
        }
    if deployment_code == "manual_review_risk_gate_throttled":
        return {
            "playbook_go_no_go": "MANUAL_REVIEW",
            "playbook_code": "manual_review_portfolio_risk_gate_throttled",
            "playbook_action": "review_throttled_gate_and_reduce_size",
            "playbook_message": "MANUAL_REVIEW: runtime risk gate is throttled. Review headroom and reduce size before acting.",
        }
    if deployment_code == "go_runtime_gate_open":
        return {
            "playbook_go_no_go": "GO",
            "playbook_code": "go_portfolio_runtime_ready",
            "playbook_action": "continue_candidate_review_under_portfolio_caps",
            "playbook_message": "GO: runtime gate is open and portfolio headroom review can proceed under current caps.",
        }
    return {
        "playbook_go_no_go": deployment_go_no_go,
        "playbook_code": f"{str(deployment_go_no_go).lower()}_portfolio_runtime_review".strip("_"),
        "playbook_action": "review_portfolio_runtime_state",
        "playbook_message": str(
            deployment_language.get("deployment_message")
            or "MANUAL_REVIEW: portfolio runtime state requires operator review."
        ),
    }


class PortfolioBudgetReportService:
    @staticmethod
    def _submission_counts_as_live_contract(row: Any) -> bool:
        if str(getattr(row, "adapter", "") or "").lower() == "none":
            return False
        if str(getattr(row, "state", "") or "").upper() not in {
            OrderLifecycleState.CREATED.value,
            OrderLifecycleState.SUBMITTED.value,
            OrderLifecycleState.ACKNOWLEDGED.value,
            OrderLifecycleState.PARTIALLY_FILLED.value,
            OrderLifecycleState.FILLED.value,
        }:
            return False
        execution_mode = str(getattr(row, "execution_mode", "") or "").upper()
        requested_live = bool(getattr(row, "requested_live", False))
        return requested_live or execution_mode in {ExecutionMode.MICRO_LIVE.value, ExecutionMode.LIVE.value}

    def _recent_live_submission_plan_ids(self) -> set[str]:
        live_plan_ids: set[str] = set()
        for row in self.submission_repo.list_recent(days=7, limit=5000):
            plan_id = str(getattr(row, "plan_id", "") or "")
            if not plan_id:
                continue
            if self._submission_counts_as_live_contract(row):
                live_plan_ids.add(plan_id)
        return live_plan_ids

    def _filter_exposure_plans_for_mode(self, exposure_plans: list[Plan]) -> list[Plan]:
        mode_value = str(getattr(self.settings.auto_trading_execution_mode, "value", self.settings.auto_trading_execution_mode) or "").upper()
        if mode_value not in {ExecutionMode.MICRO_LIVE.value, ExecutionMode.LIVE.value}:
            return exposure_plans

        allowed_live_modes = {ExecutionMode.MICRO_LIVE.value, ExecutionMode.LIVE.value}
        recent_live_submission_plan_ids = self._recent_live_submission_plan_ids()
        filtered: list[Plan] = []
        for plan in exposure_plans:
            validity = dict(plan.validity or {})
            execution_mode = str(validity.get("execution_mode") or "").upper()
            if execution_mode in allowed_live_modes or str(getattr(plan, "plan_id", "") or "") in recent_live_submission_plan_ids:
                filtered.append(plan)
        return filtered

    @staticmethod
    def _edge_experiment_summary_lookup(
        *,
        outcome_inputs_by_symbol: dict[str, dict[str, Any]] | None,
    ) -> dict[str, dict[str, Any]]:
        lookup: dict[str, dict[str, Any]] = {}
        for symbol, inputs in dict(outcome_inputs_by_symbol or {}).items():
            symbol_key = str(symbol or "").upper()
            if not symbol_key:
                continue
            symbol_inputs = dict(inputs or {})
            review = summarize_edge_experiment_review(
                build_edge_experiment_review(
                    score_to_outcome_funnel=dict(symbol_inputs.get("score_to_outcome_funnel_summary") or {})
                )
            )
            if not review:
                continue
            lookup[symbol_key] = dict(review)
        return lookup

    @staticmethod
    def _edge_experiment_lookup(
        *,
        edge_experiment_summary_lookup: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        lookup: dict[str, dict[str, Any]] = {}
        for symbol_key, review in dict(edge_experiment_summary_lookup or {}).items():
            lookup[str(symbol_key or "").upper()] = {
                "available": bool(review.get("available", False)),
                "advisory_only": bool(review.get("advisory_only", True)),
                "edge_state": str(review.get("edge_state") or "insufficient_edge_measurement"),
                "true_edge_ratio": round(float(review.get("true_edge_ratio", 0.0) or 0.0), 4),
                "entry_timing_preferred_variant": str(review.get("entry_timing_preferred_variant") or "none"),
                "execution_style_preferred_variant": str(review.get("execution_style_preferred_variant") or "none"),
                "entry_timing_comparison_ready": bool(review.get("entry_timing_comparison_ready", False)),
                "execution_style_comparison_ready": bool(review.get("execution_style_comparison_ready", False)),
                "summary": str(review.get("summary") or ""),
            }
        return lookup

    @staticmethod
    def _annotate_edge_experiment_rows(
        rows: list[dict[str, Any]],
        *,
        edge_experiment_lookup: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        annotated_rows: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            symbol = str(item.get("symbol") or "").upper()
            edge_focus = dict(edge_experiment_lookup.get(symbol) or {})
            item["edge_experiment_focus"] = edge_focus or None
            annotated_rows.append(item)
        return annotated_rows

    @staticmethod
    def _focused_candidate(
        *,
        accepted_candidates: list[dict[str, Any]],
        blocked_candidates: list[dict[str, Any]],
        alpha_research_candidates: list[dict[str, Any]],
    ) -> tuple[str, dict[str, Any]] | None:
        candidate_groups = (
            ("ACTIONABLE_ENTRY", accepted_candidates),
            ("BLOCKED_SETUP", blocked_candidates),
            ("RESEARCH_ONLY_SETUP", alpha_research_candidates),
        )
        for focus_status, rows in candidate_groups:
            for row in rows:
                if dict(row.get("edge_experiment_focus") or {}):
                    return focus_status, dict(row)
        return None

    @staticmethod
    def _edge_experiment_review(
        *,
        accepted_candidates: list[dict[str, Any]],
        blocked_candidates: list[dict[str, Any]],
        alpha_research_candidates: list[dict[str, Any]],
        edge_experiment_summary_lookup: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        focus = PortfolioBudgetReportService._focused_candidate(
            accepted_candidates=accepted_candidates,
            blocked_candidates=blocked_candidates,
            alpha_research_candidates=alpha_research_candidates,
        )
        if not focus:
            return None
        focus_status, row = focus
        symbol = str(row.get("symbol") or "").upper()
        review = dict(edge_experiment_summary_lookup.get(symbol) or row.get("edge_experiment_focus") or {})
        if not review:
            return None
        enriched = dict(review)
        enriched["focus_symbol"] = symbol
        enriched["focus_status"] = focus_status
        enriched["focus_family"] = str(row.get("strategy_family") or "unknown")
        return enriched

    @staticmethod
    def _edge_evolution_review(
        *,
        edge_experiment_review: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not edge_experiment_review:
            return None
        return summarize_edge_evolution_rule(
            build_edge_evolution_rule(
                edge_experiment_review=edge_experiment_review,
            )
        )

    @staticmethod
    def _review_followup_ledger(
        *,
        edge_experiment_review: dict[str, Any] | None,
        universe: str,
    ) -> dict[str, Any] | None:
        focus_symbol = str(_dict(edge_experiment_review).get("focus_symbol") or "").upper()
        if not focus_symbol:
            return None
        return summarize_split_review_followup_ledger(
            symbol=focus_symbol,
            universe=universe,
        )

    @staticmethod
    def _approval_strip_summary(
        *,
        deployment_language: dict[str, str] | None,
        playbook: dict[str, str] | None,
    ) -> dict[str, Any] | None:
        deployment = dict(deployment_language or {})
        playbook_payload = dict(playbook or {})
        if not deployment and not playbook_payload:
            return None

        deployment_go_no_go = str(deployment.get("deployment_go_no_go") or "")
        deployment_code = str(deployment.get("deployment_code") or "")
        deployment_message = str(deployment.get("deployment_message") or "")
        playbook_go_no_go = str(playbook_payload.get("playbook_go_no_go") or "")
        playbook_action = str(playbook_payload.get("playbook_action") or "")
        playbook_message = str(playbook_payload.get("playbook_message") or "")

        approve_value = "approval usable"
        if deployment_go_no_go == "NO_GO":
            approve_value = "runtime no_go"
        elif deployment_go_no_go == "MANUAL_REVIEW":
            approve_value = "manual review first"

        if deployment_go_no_go and playbook_go_no_go and deployment_go_no_go != playbook_go_no_go:
            align_value = "playbook_drift"
            align_reason = " | ".join(
                part
                for part in [
                    f"deployment={deployment_go_no_go}",
                    f"playbook={playbook_go_no_go}",
                    deployment_message or playbook_message,
                ]
                if part
            )
        else:
            align_value = "aligned"
            align_reason = " | ".join(
                part
                for part in [
                    f"deployment={deployment_go_no_go}" if deployment_go_no_go else "",
                    f"playbook={playbook_go_no_go}" if playbook_go_no_go else "",
                    deployment_message or playbook_message,
                ]
                if part
            ) or "portfolio runtime approval is aligned"

        priority_map = {
            "NO_GO": "urgent",
            "MANUAL_REVIEW": "watch",
            "GO": "monitor",
        }
        return {
            "primary_reason": deployment_message or playbook_message or "portfolio approval strip unavailable",
            "approve_value": approve_value,
            "approve_reason": deployment_message or playbook_message or "portfolio runtime approval unavailable",
            "align_value": align_value,
            "align_reason": align_reason,
            "act_value": playbook_action or "review_portfolio_runtime_state",
            "act_reason": playbook_message or deployment_message or "portfolio runtime action unavailable",
            "act_priority_level": priority_map.get(deployment_go_no_go or playbook_go_no_go, "monitor"),
            "deployment_code": deployment_code,
        }

    def __init__(
        self,
        *,
        plan_repo: PlanRepository,
        submission_repo: OrderSubmissionRepository,
        scanner: ScannerService,
        multi_strategy_ab: MultiStrategyABExpansionService | None = None,
        b_continuation_activation: BContinuationActivationService | None = None,
        strategy_cluster_balance: StrategyClusterBalanceService | None = None,
        settings: Settings | None = None,
    ):
        self.plan_repo = plan_repo
        self.submission_repo = submission_repo
        self.scanner = scanner
        self.overlay = scanner.overlay
        self.multi_strategy_ab = multi_strategy_ab or MultiStrategyABExpansionService()
        self.b_continuation_activation = b_continuation_activation or BContinuationActivationService()
        self.strategy_cluster_balance = strategy_cluster_balance or StrategyClusterBalanceService()
        self.settings = settings or get_settings()
        self.mode = StrategyModeService(self.settings)

    def _current_positions(self, exposure_plans: list[Plan]) -> tuple[list[dict[str, Any]], dict[str, Any], list[Plan]]:
        existing_exposures = exposure_plans
        exposure_metrics = self.overlay.exposure_metrics(existing_exposures)
        thesis_clusters = self.overlay.thesis_cluster_summary(existing_exposures)

        positions: list[dict[str, Any]] = []
        by_state = Counter()
        by_direction = Counter()
        by_kind = Counter()
        cluster_by_direction = Counter()

        for plan, metrics in zip(exposure_plans, exposure_metrics):
            direction = str(plan.direction).lower()
            state = str(plan.state)
            regime = _plan_regime(plan)
            high_corr_count = int(metrics.get("portfolio_high_corr_count", 0))
            validity = dict(plan.validity or {})
            positions.append(
                {
                    "plan_id": plan.plan_id,
                    "symbol": plan.symbol,
                    "direction": direction,
                    "state": state,
                    "entry_model": plan.entry_model,
                    "regime": regime,
                    "exposure_kind": _state_kind(state),
                    "ev": float(plan.ev),
                    "rr_base": float(plan.rr_base),
                    "strategy_version": str(plan.strategy_version or "unknown"),
                    "valid_until": plan.valid_until,
                    "portfolio_volatility": float(metrics.get("portfolio_volatility", 0.0)),
                    "portfolio_high_corr_count": high_corr_count,
                    "recommended_risk_r": float(validity.get("recommended_risk_r", 0.0) or 0.0),
                    "strategy_mode": str(validity.get("strategy_mode", self.mode.current_mode().value)),
                    "thesis_cluster_id": metrics.get("thesis_cluster_id"),
                    "thesis_primary_symbol": metrics.get("thesis_primary_symbol"),
                    "thesis_cluster_size": int(metrics.get("thesis_cluster_size", 1) or 1),
                }
            )
            by_state[state] += 1
            by_direction[direction] += 1
            by_kind[_state_kind(state)] += 1
            cluster_by_direction[direction] = max(cluster_by_direction[direction], high_corr_count + 1 if high_corr_count > 0 else 1)

        positions.sort(
            key=lambda row: (
                0 if row["exposure_kind"] == "live" else 1 if row["exposure_kind"] == "pre_entry" else 2,
                -float(row["ev"]),
                row["symbol"],
            )
        )

        summary = {
            "total": len(positions),
            "by_state": dict(sorted(by_state.items())),
            "by_direction": dict(sorted(by_direction.items())),
            "by_kind": dict(sorted(by_kind.items())),
            "cluster_size_by_direction": {
                "long": int(cluster_by_direction.get("long", 0)),
                "short": int(cluster_by_direction.get("short", 0)),
            },
            "active_thesis_clusters": len(thesis_clusters),
            "thesis_clusters": thesis_clusters,
        }
        return positions, summary, existing_exposures

    def _headroom_by_regime(self, *, exposure_summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
        total = int(exposure_summary["total"])
        by_direction = dict(exposure_summary.get("by_direction") or {})
        cluster_sizes = dict(exposure_summary.get("cluster_size_by_direction") or {})
        headroom: dict[str, dict[str, Any]] = {}

        for regime in ("range", "trend", "shock"):
            caps = self.overlay.budget_caps_for_regime(regime)
            long_count = int(by_direction.get("long", 0))
            short_count = int(by_direction.get("short", 0))
            long_cluster = int(cluster_sizes.get("long", 0))
            short_cluster = int(cluster_sizes.get("short", 0))
            headroom[regime] = {
                "caps": caps,
                "remaining_total": max(0, int(caps["total"]) - total),
                "remaining_directional": {
                    "long": max(0, int(caps["directional"]) - long_count),
                    "short": max(0, int(caps["directional"]) - short_count),
                },
                "remaining_cluster": {
                    "long": max(0, int(caps["cluster"]) - long_cluster),
                    "short": max(0, int(caps["cluster"]) - short_cluster),
                },
                "current_directional": {
                    "long": long_count,
                    "short": short_count,
                },
                "current_cluster": {
                    "long": long_cluster,
                    "short": short_cluster,
                },
                "remaining_thesis_clusters": max(0, int(self.settings.thesis_max_active_clusters) - int(exposure_summary.get("active_thesis_clusters", 0))),
            }
        return headroom

    @staticmethod
    def _capital_allocator_summary(
        *,
        accepted_candidates: list[dict[str, Any]],
        blocked_candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        family_rows: dict[str, dict[str, Any]] = {}
        for row in [*accepted_candidates, *blocked_candidates]:
            allocator = dict(row.get("capital_allocator") or {})
            if not allocator:
                continue
            family = str(allocator.get("family") or row.get("strategy_family") or "unknown")
            candidate = {
                "family": family,
                "tier": str(allocator.get("tier", "neutral") or "neutral"),
                "allocation_weight": round(float(allocator.get("allocation_weight", row.get("allocation_weight", 1.0)) or 1.0), 4),
                "allocated_risk_r": round(float(allocator.get("allocated_risk_r", row.get("allocated_risk_r", 0.0)) or 0.0), 4),
                "capital_pressure": str(allocator.get("capital_pressure", row.get("capital_pressure", "neutral")) or "neutral"),
                "summary": str(allocator.get("summary", "") or ""),
                "reason_codes": list(allocator.get("reason_codes") or []),
                "available": bool(allocator.get("available", False)),
            }
            current = family_rows.get(family)
            if current is None:
                family_rows[family] = candidate
                continue
            current_key = (abs(float(current.get("allocation_weight", 1.0)) - 1.0), float(current.get("allocated_risk_r", 0.0)))
            candidate_key = (abs(float(candidate.get("allocation_weight", 1.0)) - 1.0), float(candidate.get("allocated_risk_r", 0.0)))
            if candidate_key > current_key:
                family_rows[family] = candidate

        if not family_rows:
            return {
                "available": False,
                "advisory_only": False,
                "allocator_state": "neutral",
                "family_focus": None,
                "capital_pressure": "neutral",
                "summary": "capital allocator unavailable for the current candidate set",
                "family_weights": [],
            }

        family_weights = sorted(
            family_rows.values(),
            key=lambda item: (abs(float(item.get("allocation_weight", 1.0)) - 1.0), float(item.get("allocated_risk_r", 0.0)), item.get("family", "")),
            reverse=True,
        )
        family_focus = dict((family_weights[:1] or [{}])[0])
        allocator_state = "active" if any(str(item.get("tier", "neutral")) != "neutral" for item in family_weights) else "neutral"
        capital_pressure = str(family_focus.get("capital_pressure", "neutral") or "neutral")
        if allocator_state == "active":
            summary = "capital allowance is tilted toward mature positive families and away from degraded negative families"
        else:
            summary = "allocator evidence does not justify a family-level capital tilt in the current candidate set"
        if capital_pressure == "underallocated_positive":
            summary += "; focus family remains underallocated relative to active risk"
        elif capital_pressure == "overallocated_negative":
            summary += "; focus family is already overallocated relative to active risk"

        return {
            "available": any(bool(item.get("available", False)) for item in family_weights),
            "advisory_only": False,
            "allocator_state": allocator_state,
            "family_focus": family_focus.get("family"),
            "capital_pressure": capital_pressure,
            "summary": summary,
            "family_weights": [
                {
                    "family": item.get("family"),
                    "tier": item.get("tier", "neutral"),
                    "allocation_weight": round(float(item.get("allocation_weight", 1.0) or 1.0), 4),
                    "allocated_risk_r": round(float(item.get("allocated_risk_r", 0.0) or 0.0), 4),
                    "capital_pressure": item.get("capital_pressure", "neutral"),
                }
                for item in family_weights[:3]
            ],
        }

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.portfolio_budget_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"budget_{payload['universe']}_{str(payload['strategy_mode']).lower()}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"

        lines = [
            "# Portfolio Budget Report",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- universe: {payload['universe']}",
            f"- symbols_considered: {payload['symbols_considered']}",
            f"- deployment_go_no_go: {payload['deployment_go_no_go']}",
            f"- deployment_code: {payload['deployment_code']}",
            f"- deployment_message: {payload['deployment_message']}",
            f"- playbook_go_no_go: {payload['playbook_go_no_go']}",
            f"- playbook_code: {payload['playbook_code']}",
            f"- playbook_action: {payload['playbook_action']}",
            f"- playbook_message: {payload['playbook_message']}",
            (
                f"- approval_strip: approve={payload['approval_strip_summary']['approve_value']} | "
                f"align={payload['approval_strip_summary']['align_value']} | "
                f"act={payload['approval_strip_summary']['act_value']} | "
                f"priority={payload['approval_strip_summary']['act_priority_level']}"
            ),
            f"- risk_state: {payload['risk_state']}",
            f"- risk_reason: {payload['risk_reason']}",
            f"- operating_lock: {payload['operating_lock']}",
            f"- strategy_mode: {payload['strategy_mode']}",
            f"- include_planned_exposure: {payload['include_planned_exposure']}",
            f"- mode_policy: {payload['mode_policy']}",
            f"- mode_stats: {payload['mode_stats']}",
            "",
            "## Current Exposure",
            f"- total: {payload['current_exposure']['total']}",
            f"- by_state: {payload['current_exposure']['by_state']}",
            f"- by_direction: {payload['current_exposure']['by_direction']}",
            f"- by_kind: {payload['current_exposure']['by_kind']}",
            f"- active_thesis_clusters: {payload['current_exposure'].get('active_thesis_clusters', 0)}",
            "",
            "## Headroom By Regime",
        ]
        for regime, row in payload["headroom_by_regime"].items():
            caps = row["caps"]
            remaining_directional = row["remaining_directional"]
            remaining_cluster = row["remaining_cluster"]
            lines.append(
                f"- {regime}: caps(total={caps['total']}, directional={caps['directional']}, cluster={caps['cluster']}), "
                f"remaining_total={row['remaining_total']}, remaining_long={remaining_directional['long']}, "
                f"remaining_short={remaining_directional['short']}, cluster_long={remaining_cluster['long']}, "
                f"cluster_short={remaining_cluster['short']}, remaining_thesis_clusters={row['remaining_thesis_clusters']}"
            )

        lines.extend(
            [
                "",
                "## Candidate Summary",
                f"- candidates_considered: {payload['candidates_considered']}",
                f"- accepted_count: {payload['accepted_count']}",
                f"- blocked_count: {payload['blocked_count']}",
                f"- alpha_research_count: {payload.get('alpha_research_count', 0)}",
                f"- blocked_reason_counts: {payload['blocked_reason_counts']}",
                "",
                "## Multi Strategy AB Expansion",
                f"- summary: {(payload.get('multi_strategy_ab_summary') or {}).get('summary', '')}",
                f"- mode: {(payload.get('multi_strategy_ab_summary') or {}).get('mode', '')}",
                f"- raw_family_anchor: {(payload.get('multi_strategy_ab_summary') or {}).get('raw_family_anchor', '')}",
                f"- family_mix: {(payload.get('multi_strategy_ab_summary') or {}).get('family_mix', [])}",
                "",
                "## Strategy Cluster Balance",
                f"- summary: {(payload.get('strategy_cluster_balance_summary') or {}).get('summary', '')}",
                f"- mode: {(payload.get('strategy_cluster_balance_summary') or {}).get('mode', '')}",
                f"- balance_state: {(payload.get('strategy_cluster_balance_summary') or {}).get('balance_state', 'a_concentrated')}",
                f"- balance_bias: {(payload.get('strategy_cluster_balance_summary') or {}).get('balance_bias', 'preserve_a_anchor')}",
                f"- family_mix: {(payload.get('strategy_cluster_balance_summary') or {}).get('family_mix', [])}",
                "",
                "## Capital Allocator",
                f"- summary: {(payload.get('capital_allocator_summary') or {}).get('summary', '')}",
                f"- allocator_state: {(payload.get('capital_allocator_summary') or {}).get('allocator_state', 'neutral')}",
                f"- family_focus: {(payload.get('capital_allocator_summary') or {}).get('family_focus')}",
                f"- capital_pressure: {(payload.get('capital_allocator_summary') or {}).get('capital_pressure', 'neutral')}",
                f"- family_weights: {(payload.get('capital_allocator_summary') or {}).get('family_weights', [])}",
                "",
                "## Accepted Candidates",
            ]
        )
        for row in payload["accepted_candidates"]:
            lines.append(
                f"- {row['symbol']} {row['direction']} {row['entry_model']}: adjusted={row['adjusted_rank_score']:.4f}, "
                f"family={row.get('strategy_family', '')}, cluster={row.get('strategy_cluster', '')}, "
                f"cluster_status={row.get('strategy_cluster_status', '')}, "
                f"outcome_bias={float(row.get('outcome_bias_score', 0.0) or 0.0):.4f}, "
                f"allocator_weight={float(row.get('allocation_weight', 1.0) or 1.0):.4f}, "
                f"allocated_risk={float(row.get('allocated_risk_r', 0.0) or 0.0):.4f}R, "
                f"capital_pressure={row.get('capital_pressure', 'neutral')}, "
                f"allocator_reasons={list((row.get('capital_allocator') or {}).get('reason_codes') or [])}, "
                f"risk_budget_score={row['risk_budget_score']:.4f}, penalty={row['portfolio_penalty']:.4f}, "
                f"session_penalty={row.get('session_penalty', 0.0):.4f}, regime={row['regime']}, "
                f"expected={row.get('expected_summary', '')}"
            )

        lines.extend(["", "## Blocked Candidates"])
        for row in payload["blocked_candidates"]:
            lines.append(
                f"- {row['symbol']} {row['direction']} {row['entry_model']}: reason={row['block_reason']}, "
                f"message={row.get('block_reason_message')}, "
                f"family={row.get('strategy_family', '')}, cluster={row.get('strategy_cluster', '')}, "
                f"cluster_status={row.get('strategy_cluster_status', '')}, "
                f"base={row['base_rank_score']:.4f}, adjusted={row['adjusted_rank_score']:.4f}, "
                f"outcome_bias={float(row.get('outcome_bias_score', 0.0) or 0.0):.4f}, "
                f"allocator_weight={float(row.get('allocation_weight', 1.0) or 1.0):.4f}, "
                f"allocated_risk={float(row.get('allocated_risk_r', 0.0) or 0.0):.4f}R, "
                f"capital_pressure={row.get('capital_pressure', 'neutral')}, "
                f"allocator_reasons={list((row.get('capital_allocator') or {}).get('reason_codes') or [])}, "
                f"risk_budget_score={row['risk_budget_score']:.4f}, session_penalty={row.get('session_penalty', 0.0):.4f}, "
                f"regime={row['regime']}, expected={row.get('expected_summary', '')}"
            )

        lines.extend(["", "## Alpha Research Candidates"])
        for row in payload.get("alpha_research_candidates") or []:
            lines.append(
                f"- {row['symbol']} {row['direction']} {row['entry_model']}: reason={row.get('alpha_research_reason')}, "
                f"family={row.get('strategy_family', '')}, cluster={row.get('strategy_cluster', '')}, "
                f"cluster_status={row.get('strategy_cluster_status', '')}, "
                f"softened_risk={float(row.get('alpha_research_softened_risk_r', 0.0)):.4f}R, "
                f"gap={float(row.get('alpha_research_gap', 0.0)):.4f}, "
                f"regime={row['regime']}, expected={row.get('expected_summary', '')}"
            )

        file_path.write_text("\n".join(lines), encoding="utf-8")
        return str(file_path)

    def generate(
        self,
        *,
        universe: str,
        symbols: list[str],
        limit: int,
        risk_state: RiskGateState,
        risk_reason: str,
        today_trade_count: int,
        operating_lock: dict[str, Any] | None = None,
        outcome_inputs_by_symbol: dict[str, dict[str, Any]] | None = None,
        write_report: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        mode_policy = self.mode.policy()
        exposure_plans = self.plan_repo.list_exposure_candidates(
            timeframe="5m",
            include_planned=self.settings.portfolio_overlay_include_planned_exposure,
            limit=300,
        )
        exposure_plans = self._filter_exposure_plans_for_mode(exposure_plans)
        current_positions, exposure_summary, existing_exposures = self._current_positions(exposure_plans)
        headroom_by_regime = self._headroom_by_regime(exposure_summary=exposure_summary)
        current_total_risk_r = round(sum(float(row.get("recommended_risk_r", 0.0) or 0.0) for row in current_positions), 4)

        candidate_rows = self.scanner.candidate_rows(symbols=symbols, risk_state=risk_state, plans_per_symbol=3)
        assessed = self.overlay.assess_rows(
            candidate_rows,
            existing_exposures=existing_exposures,
            today_trade_count=today_trade_count,
            operating_lock=operating_lock,
            outcome_inputs_by_symbol=outcome_inputs_by_symbol,
            apply_outcome_bias=True,
        )

        accepted_candidates = [row for row in assessed if bool(row.get("accepted"))]
        blocked_candidates = [row for row in assessed if not bool(row.get("accepted"))]
        alpha_research_candidates = [row for row in blocked_candidates if bool(row.get("alpha_research_candidate"))]
        capital_allocator_summary = self._capital_allocator_summary(
            accepted_candidates=accepted_candidates,
            blocked_candidates=blocked_candidates,
        )
        accepted_candidates.sort(
            key=lambda row: float(row.get("post_outcome_final_rank_score", row.get("final_rank_score", 0.0)) or 0.0),
            reverse=True,
        )
        blocked_candidates.sort(key=lambda row: float(row.get("base_rank_score", row.get("final_rank_score", 0.0))), reverse=True)
        alpha_research_candidates.sort(
            key=lambda row: (
                -float(row.get("expected_ev_at_recommended_size_r", row.get("expected_ev_r", 0.0)) or 0.0),
                -float(row.get("alpha_research_softened_risk_r", 0.0) or 0.0),
                float(row.get("alpha_research_gap", 0.0) or 0.0),
                str(row.get("symbol") or ""),
            )
        )
        def _annotate_multi_strategy_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            annotated_rows: list[dict[str, Any]] = []
            for row in rows:
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
                annotated_rows.append(dict(item))
            return annotated_rows

        accepted_candidates = _annotate_multi_strategy_rows(accepted_candidates)
        blocked_candidates = _annotate_multi_strategy_rows(blocked_candidates)
        alpha_research_candidates = _annotate_multi_strategy_rows(alpha_research_candidates)
        accepted_candidates = self.b_continuation_activation.annotate_rows(
            accepted_candidates,
            outcome_inputs_by_symbol=outcome_inputs_by_symbol,
        )
        blocked_candidates = self.b_continuation_activation.annotate_rows(
            blocked_candidates,
            outcome_inputs_by_symbol=outcome_inputs_by_symbol,
        )
        alpha_research_candidates = self.b_continuation_activation.annotate_rows(
            alpha_research_candidates,
            outcome_inputs_by_symbol=outcome_inputs_by_symbol,
        )
        multi_strategy_ab_summary = self.multi_strategy_ab.generate(
            portfolio_budget={
                "strategy_mode": mode_policy.mode.value,
                "accepted_candidates": accepted_candidates,
                "blocked_candidates": blocked_candidates,
                "alpha_research_candidates": alpha_research_candidates,
            }
        )
        strategy_cluster_balance_summary = self.strategy_cluster_balance.generate(
            multi_strategy_ab=multi_strategy_ab_summary,
            capital_allocator=capital_allocator_summary,
            rows=[*accepted_candidates, *blocked_candidates, *alpha_research_candidates],
            portfolio_budget={
                "strategy_mode": mode_policy.mode.value,
                "accepted_candidates": accepted_candidates,
                "blocked_candidates": blocked_candidates,
                "alpha_research_candidates": alpha_research_candidates,
            },
        )
        accepted_candidates = self.strategy_cluster_balance.annotate_rows(
            accepted_candidates,
            strategy_cluster_balance_summary=strategy_cluster_balance_summary,
        )
        blocked_candidates = self.strategy_cluster_balance.annotate_rows(
            blocked_candidates,
            strategy_cluster_balance_summary=strategy_cluster_balance_summary,
        )
        alpha_research_candidates = self.strategy_cluster_balance.annotate_rows(
            alpha_research_candidates,
            strategy_cluster_balance_summary=strategy_cluster_balance_summary,
        )
        edge_experiment_summary_lookup = self._edge_experiment_summary_lookup(
            outcome_inputs_by_symbol=outcome_inputs_by_symbol,
        )
        edge_experiment_lookup = self._edge_experiment_lookup(
            edge_experiment_summary_lookup=edge_experiment_summary_lookup,
        )
        accepted_candidates = self._annotate_edge_experiment_rows(
            accepted_candidates,
            edge_experiment_lookup=edge_experiment_lookup,
        )
        blocked_candidates = self._annotate_edge_experiment_rows(
            blocked_candidates,
            edge_experiment_lookup=edge_experiment_lookup,
        )
        alpha_research_candidates = self._annotate_edge_experiment_rows(
            alpha_research_candidates,
            edge_experiment_lookup=edge_experiment_lookup,
        )

        blocked_reason_counts = Counter(str(row.get("block_reason", "unknown")) for row in blocked_candidates)
        deployment_language = _runtime_deployment_language(
            risk_state=risk_state,
            risk_reason=risk_reason,
            operating_lock=operating_lock,
        )
        playbook = _portfolio_playbook_mapping(deployment_language)
        approval_strip_summary = self._approval_strip_summary(
            deployment_language=deployment_language,
            playbook=playbook,
        )
        edge_experiment_review = self._edge_experiment_review(
            accepted_candidates=accepted_candidates,
            blocked_candidates=blocked_candidates,
            alpha_research_candidates=alpha_research_candidates,
            edge_experiment_summary_lookup=edge_experiment_summary_lookup,
        )
        edge_evolution_rule = self._edge_evolution_review(
            edge_experiment_review=edge_experiment_review,
        )
        review_followup_ledger = self._review_followup_ledger(
            edge_experiment_review=edge_experiment_review,
            universe=universe,
        )

        payload: dict[str, Any] = {
            "generated_at": now.isoformat(),
            "universe": universe,
            "symbols_considered": len(symbols),
            "deployment_go_no_go": deployment_language["deployment_go_no_go"],
            "deployment_code": deployment_language["deployment_code"],
            "deployment_message": deployment_language["deployment_message"],
            "playbook_go_no_go": playbook["playbook_go_no_go"],
            "playbook_code": playbook["playbook_code"],
            "playbook_action": playbook["playbook_action"],
            "playbook_message": playbook["playbook_message"],
            "approval_strip_summary": approval_strip_summary,
            "edge_experiment_review": edge_experiment_review,
            "edge_evolution_rule": edge_evolution_rule,
            "review_followup_ledger": review_followup_ledger,
            "risk_state": risk_state.value,
            "risk_reason": risk_reason,
            "operating_lock": dict(operating_lock or {}),
            "strategy_mode": mode_policy.mode.value,
            "mode_policy": mode_policy.to_dict(),
            "mode_stats": {
                "today_trade_count": int(today_trade_count),
                "daily_trade_limit": int(mode_policy.max_daily_trades),
                "current_total_risk_r": current_total_risk_r,
                "max_total_risk_r": float(mode_policy.max_total_risk_r),
                "shadow_only": bool(mode_policy.shadow_only),
            },
            "include_planned_exposure": bool(self.settings.portfolio_overlay_include_planned_exposure),
            "current_exposure": exposure_summary,
            "headroom_by_regime": headroom_by_regime,
            "current_positions": current_positions,
            "candidates_considered": len(assessed),
            "accepted_count": len(accepted_candidates),
            "blocked_count": len(blocked_candidates),
            "alpha_research_count": len(alpha_research_candidates),
            "blocked_reason_counts": dict(sorted(blocked_reason_counts.items())),
            "multi_strategy_ab_summary": multi_strategy_ab_summary,
            "strategy_cluster_balance_summary": strategy_cluster_balance_summary,
            "capital_allocator_summary": capital_allocator_summary,
            "accepted_candidates": accepted_candidates[:limit],
            "blocked_candidates": blocked_candidates[:limit],
            "alpha_research_candidates": alpha_research_candidates[:limit],
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload
