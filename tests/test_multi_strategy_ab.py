from __future__ import annotations

from app.services.multi_strategy_ab import MultiStrategyABExpansionService
from app.services.strategy_cluster_balance import StrategyClusterBalanceService


def test_multi_strategy_ab_overlay_marks_b_compare_only_under_a_only() -> None:
    service = MultiStrategyABExpansionService()

    overlay = service.overlay_for_row(
        {
            "strategy_family": "trend_continuation",
            "strategy_mode": "A_ONLY",
        }
    )

    assert overlay is not None
    assert overlay["cluster"] == "b_continuation"
    assert overlay["strategy_cluster_status"] == "compare_only"
    assert overlay["live_eligible"] is False
    assert overlay["guarded"] is True
    assert "b_guardrail:mode_a_only" in overlay["guardrail_reasons"]


def test_multi_strategy_ab_summary_keeps_b_guarded_when_samples_are_thin() -> None:
    service = MultiStrategyABExpansionService()

    summary = service.generate(
        portfolio_budget={
            "strategy_mode": "A_PLUS_B",
            "accepted_candidates": [
                {"strategy_family": "sweep_reversal", "accepted": True},
                {"strategy_family": "trend_continuation", "accepted": True},
            ],
        },
        score_to_outcome_funnel={
            "decomposition": {
                "family": [
                    {"key": "sweep_reversal", "closed": 8},
                    {"key": "trend_continuation", "closed": 3},
                ]
            }
        },
        family_execution_degradation_advisory={
            "families": [
                {"family": "trend_continuation", "status": "healthy"},
            ]
        },
        rollout_recommendation={"family": "trend_continuation", "recommendation": "hold"},
        strategy_lifecycle={"family": "trend_continuation", "state": "probation"},
    )

    assert summary["available"] is True
    assert summary["mode"] == "A_PLUS_B"
    assert summary["b_cluster"]["cluster"] == "b_continuation"
    assert summary["b_cluster"]["strategy_cluster_status"] == "available_but_guarded"
    assert summary["b_cluster"]["live_eligible"] is False
    assert "b_guardrail:thin_sample" in summary["b_cluster"]["guardrail_reasons"]


def test_multi_strategy_ab_summary_marks_b_probation_ready_with_cleared_guardrails() -> None:
    service = MultiStrategyABExpansionService()

    summary = service.generate(
        portfolio_budget={
            "strategy_mode": "A_PLUS_B",
            "accepted_candidates": [
                {"strategy_family": "sweep_reversal", "accepted": True},
                {"strategy_family": "trend_continuation", "accepted": True},
            ],
        },
        score_to_outcome_funnel={
            "decomposition": {
                "family": [
                    {"key": "sweep_reversal", "closed": 8},
                    {"key": "trend_continuation", "closed": 6},
                ]
            }
        },
        family_execution_degradation_advisory={
            "families": [
                {"family": "trend_continuation", "status": "healthy"},
            ]
        },
        rollout_recommendation={"family": "trend_continuation", "recommendation": "hold"},
        strategy_lifecycle={"family": "trend_continuation", "state": "probation"},
    )

    assert summary["available"] is True
    assert summary["mode"] == "A_PLUS_B"
    assert summary["b_cluster"]["strategy_cluster_status"] == "probation_ready"
    assert summary["b_cluster"]["live_eligible"] is True
    assert summary["b_cluster"]["guardrail_reasons"] == []


def test_multi_strategy_ab_summary_marks_sir_as_outside_legacy_ab_lens() -> None:
    service = MultiStrategyABExpansionService()

    summary = service.generate(
        portfolio_budget={
            "strategy_mode": "A_ONLY",
            "accepted_candidates": [
                {"strategy_family": "session_impulse_retest", "accepted": True},
            ],
        },
    )

    assert summary["available"] is True
    assert summary["raw_family_anchor"] == "session_impulse_retest"
    assert summary["a_cluster"]["strategy_cluster_status"] == "not_applicable_to_current_live_contract"
    assert summary["current_live_contract"]["cluster"] == "current_live_contract"
    assert "ab_lens:not_applicable_to_current_live_contract" in summary["reason_codes"]


def test_multi_strategy_ab_summary_uses_live_contract_when_candidate_set_is_empty() -> None:
    service = MultiStrategyABExpansionService()

    summary = service.generate(
        portfolio_budget={
            "strategy_mode": "A_ONLY",
            "active_strategy_families": ["session_impulse_retest"],
            "accepted_candidates": [],
            "blocked_candidates": [],
            "alpha_research_candidates": [],
        },
    )

    assert summary["available"] is True
    assert summary["raw_family_anchor"] == "session_impulse_retest"
    assert summary["a_cluster"]["strategy_cluster_status"] == "not_applicable_to_current_live_contract"
    assert summary["current_live_contract"]["total_candidates"] == 0
    assert "A reversal remains the current production anchor" not in summary["summary"]


def test_strategy_cluster_balance_marks_sir_as_outside_legacy_ab_balance() -> None:
    service = StrategyClusterBalanceService()

    summary = service.generate(
        multi_strategy_ab={},
        portfolio_budget={
            "strategy_mode": "A_ONLY",
            "accepted_candidates": [
                {"strategy_family": "session_impulse_retest", "accepted": True},
            ],
        },
    )

    assert summary["available"] is True
    assert summary["balance_state"] == "legacy_ab_not_applicable"
    assert summary["balance_bias"] == "follow_current_live_contract"
    assert summary["headline_cluster"] == "current_live_contract"


def test_strategy_cluster_balance_uses_live_contract_when_candidate_set_is_empty() -> None:
    service = StrategyClusterBalanceService()

    summary = service.generate(
        multi_strategy_ab={},
        portfolio_budget={
            "strategy_mode": "A_ONLY",
            "active_strategy_families": ["session_impulse_retest"],
            "accepted_candidates": [],
            "blocked_candidates": [],
            "alpha_research_candidates": [],
        },
    )

    assert summary["available"] is True
    assert summary["balance_state"] == "legacy_ab_not_applicable"
    assert summary["source_summary"]["current_live_family"] == "session_impulse_retest"
    assert "A remains the live anchor" not in summary["summary"]
