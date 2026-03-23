from __future__ import annotations

from app.services.strategy_cluster_balance import StrategyClusterBalanceService


def test_strategy_cluster_balance_stays_research_only_under_a_only() -> None:
    service = StrategyClusterBalanceService()

    payload = service.generate(
        multi_strategy_ab={
            "available": True,
            "mode": "A_ONLY",
            "family_mix": [
                {
                    "raw_family": "sweep_reversal",
                    "cluster": "a_reversal",
                    "total_candidates": 4,
                    "accepted_candidates": 2,
                    "blocked_candidates": 2,
                    "alpha_research_candidates": 0,
                },
                {
                    "raw_family": "trend_continuation",
                    "cluster": "b_continuation",
                    "total_candidates": 2,
                    "accepted_candidates": 0,
                    "blocked_candidates": 1,
                    "alpha_research_candidates": 1,
                },
            ],
            "b_cluster": {
                "strategy_cluster_status": "compare_only",
            },
        },
        b_continuation_activation={
            "family": "trend_continuation",
            "activation_state": "research_only",
            "activation_bias": "stay_research",
        },
        capital_allocator={
            "family_focus": "trend_continuation",
            "allocator_state": "active",
        },
    )

    assert payload["available"] is True
    assert payload["balance_state"] == "research_only_mix"
    assert payload["balance_bias"] == "stay_a_anchor"
    assert payload["headline_cluster"] == "a_reversal"


def test_strategy_cluster_balance_marks_guarded_rebalance_when_b_is_next_build() -> None:
    service = StrategyClusterBalanceService()

    payload = service.generate(
        multi_strategy_ab={
            "available": True,
            "mode": "A_PLUS_B",
            "family_mix": [
                {
                    "raw_family": "sweep_reversal",
                    "cluster": "a_reversal",
                    "total_candidates": 5,
                    "accepted_candidates": 3,
                    "blocked_candidates": 2,
                    "alpha_research_candidates": 0,
                },
                {
                    "raw_family": "trend_continuation",
                    "cluster": "b_continuation",
                    "total_candidates": 2,
                    "accepted_candidates": 0,
                    "blocked_candidates": 1,
                    "alpha_research_candidates": 1,
                },
            ],
            "b_cluster": {
                "strategy_cluster_status": "probation_ready",
            },
        },
        b_continuation_activation={
            "family": "trend_continuation",
            "activation_state": "guarded_probation",
            "activation_bias": "continue_guarded_probation",
        },
        capital_allocator={
            "family_focus": "trend_continuation",
            "allocator_state": "active",
        },
    )

    assert payload["available"] is True
    assert payload["balance_state"] == "guarded_rebalance"
    assert payload["balance_bias"] == "build_guarded_b_mix"
    assert payload["headline_cluster"] == "b_continuation"
