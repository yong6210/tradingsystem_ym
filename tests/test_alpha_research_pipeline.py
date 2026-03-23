from __future__ import annotations

from pathlib import Path

from app.services.alpha_research_pipeline import AlphaResearchPipelineService


def test_alpha_research_pipeline_summarizes_softened_candidates() -> None:
    service = AlphaResearchPipelineService()
    payload = service.generate(
        universe="usdc_perp_top30",
        focus_symbol="BTCUSDC",
        analysis_symbol="BTCUSDC",
        portfolio_budget={
            "alpha_research_candidates": [
                {
                    "symbol": "BTCUSDC",
                    "plan_id": "plan_btc",
                    "direction": "long",
                    "entry_model": "LIMIT",
                    "strategy_family": "trend_continuation",
                    "regime": "range",
                    "session_guidance": {"state": "dead_session"},
                    "alpha_research_candidate": True,
                    "alpha_research_reason": "risk_budget_below_min",
                    "alpha_research_softened_risk_r": 0.2,
                    "alpha_research_gap": 4.5,
                    "expected_ev_r": 0.18,
                    "expected_ev_at_recommended_size_r": 0.09,
                },
                {
                    "symbol": "ETHUSDC",
                    "plan_id": "plan_eth",
                    "direction": "short",
                    "entry_model": "CONFIRM",
                    "strategy_family": "sweep_reversal",
                    "regime": "range",
                    "session_guidance": {"state": "dead_session"},
                    "alpha_research_candidate": True,
                    "alpha_research_reason": "adjusted_score_non_positive",
                    "alpha_research_softened_risk_r": 0.1,
                    "alpha_research_gap": 2.0,
                    "expected_ev_r": 0.11,
                    "expected_ev_at_recommended_size_r": 0.05,
                },
            ]
        },
        performance_decomposition_summary={
            "tuning_focus": [
                {
                    "focus": "family_information_failure",
                    "bucket": "trend_continuation",
                    "metric": "information_failure_rate",
                    "value": 0.4,
                },
                {
                    "focus": "session_negative_ev",
                    "bucket": "dead_session",
                    "metric": "ev",
                    "value": -0.35,
                },
                {
                    "focus": "entry_model_fill_rate",
                    "bucket": "LIMIT",
                    "metric": "fill_rate",
                    "value": 0.4,
                },
            ]
        },
        score_to_outcome_funnel={
            "available": True,
            "report_window_days": 30,
            "coverage_note": "snapshot selection is current-state only; execution outcomes are windowed history.",
            "decomposition": {
                "family": [
                    {
                        "key": "trend_continuation",
                        "runtime_candidates": 6,
                        "accepted_candidates": 2,
                        "submitted": 4,
                        "closed": 3,
                        "baseline_cost_profitable": 1,
                        "profitable_rate_from_closed": 0.6667,
                        "baseline_cost_profitable_rate_from_closed": 0.3333,
                    }
                ],
                "regime": [
                    {
                        "key": "range",
                        "runtime_candidates": 7,
                        "accepted_candidates": 3,
                        "submitted": 5,
                        "closed": 4,
                        "baseline_cost_profitable": 2,
                        "profitable_rate_from_closed": 0.75,
                        "baseline_cost_profitable_rate_from_closed": 0.5,
                    }
                ],
                "session": [
                    {
                        "key": "dead_session",
                        "runtime_candidates": 4,
                        "accepted_candidates": 1,
                        "submitted": 2,
                        "closed": 2,
                        "baseline_cost_profitable": 1,
                        "profitable_rate_from_closed": 0.5,
                        "baseline_cost_profitable_rate_from_closed": 0.5,
                    }
                ],
            },
        },
        execution_degradation_advisory={
            "available": True,
            "status": "watch",
            "healthy": False,
            "summary": "runtime execution drag is rising.",
            "recommended_action": "review_runtime_execution_drag_before_expansion",
            "reason_codes": ["fill_rate_watch"],
        },
        write_report=True,
    )

    assert payload["available"] is True
    assert payload["analysis_symbol"] == "BTCUSDC"
    assert payload["summary"]["alpha_research_candidate_count"] == 2
    assert payload["summary"]["focus_symbol_candidate_count"] == 1
    assert payload["summary"]["aligned_candidate_count"] >= 1
    assert payload["research_focus_alignment"]["analysis_symbol"] == "BTCUSDC"
    assert payload["research_focus_alignment"]["aligned_candidate_count"] >= 1
    assert payload["research_focus_alignment"]["top_focus"] in {
        "family_information_failure",
        "session_negative_ev",
        "entry_model_fill_rate",
    }
    assert payload["recommended_action_summary"]["analysis_symbol"] == "BTCUSDC"
    assert payload["recommended_action_summary"]["recommended_action"] in {
        "run_shadow_exit_review",
        "run_shadow_session_review",
        "run_shadow_entry_model_fill_review",
    }
    assert payload["recommended_action_summary"]["recommended_scope"] in {"family", "session", "entry_model"}
    assert payload["recommended_action_summary"]["confidence"] in {"high", "medium", "low"}
    assert len(payload["recommended_actions"]) >= 1
    assert payload["recommended_actions"][0]["shadow_experiment_type"] in {
        "exit_failure_review",
        "session_filter_review",
        "entry_fill_review",
    }
    assert "observe_metrics" in payload["recommended_actions"][0]
    assert "promotion_guardrails" in payload["recommended_actions"][0]
    assert payload["top_shadow_experiment"]["analysis_symbol"] == "BTCUSDC"
    assert payload["top_shadow_experiment"]["recommended_action"] in {
        "run_shadow_exit_review",
        "run_shadow_session_review",
        "run_shadow_entry_model_fill_review",
    }
    assert payload["top_shadow_experiment"]["experiment_id"] in {
        "shadow_exit_review_family",
        "shadow_session_filter",
        "shadow_entry_model_fill",
    }
    assert payload["top_shadow_experiment"]["target"] in {
        "family=trend_continuation",
        "session=dead_session",
        "entry_model=LIMIT",
    }
    assert len(payload["shadow_experiment_templates"]) >= 1
    assert payload["shadow_experiment_templates"][0]["title"]
    assert len(payload["shadow_experiment_templates"][0]["steps"]) >= 3
    assert len(payload["shadow_experiment_templates"][0]["success_criteria"]) >= 2
    assert len(payload["shadow_experiment_templates"][0]["stop_conditions"]) >= 2
    assert payload["alpha_research_evidence_summary"]["available"] is True
    assert payload["alpha_research_evidence_summary"]["near_miss_reason_summary"]["top_reason"] in {
        "risk_budget_below_min",
        "adjusted_score_non_positive",
    }
    assert payload["alpha_research_evidence_summary"]["focus_alignment_summary"]["top_focus"] in {
        "family_information_failure",
        "session_negative_ev",
        "entry_model_fill_rate",
    }
    assert (
        payload["alpha_research_evidence_summary"]["outcome_alignment_summary"]["top_family_bottleneck"]["key"]
        == "trend_continuation"
    )
    assert len(payload["alpha_research_evidence_summary"]["false_negative_suspects"]) >= 1
    assert payload["softening_candidate_review"]["available"] is True
    assert payload["softening_candidate_review"]["top_candidate"]["reason"] in {
        "risk_budget_below_min",
        "adjusted_score_non_positive",
    }
    assert payload["softening_candidate_review"]["top_candidate"]["review_priority"] in {"p0", "p1", "p2", "p3"}
    assert payload["promotion_watchlist"]["available"] is True
    assert payload["promotion_watchlist"]["watchlist_count"] >= 1
    assert payload["promotion_watchlist"]["watch_items"][0]["focus"] in {
        "family_information_failure",
        "session_negative_ev",
        "entry_model_fill_rate",
    }
    assert payload["summary"]["top_reason"] in {"risk_budget_below_min", "adjusted_score_non_positive"}
    assert payload["priorities"][0]["reason"] in {"risk_budget_below_min", "adjusted_score_non_positive"}
    assert payload["candidates"][0]["symbol"] == "BTCUSDC"
    assert payload["candidates"][0]["research_focus_match_count"] >= 1
    path = Path(payload["report_path"])
    assert path.exists()
    body = path.read_text(encoding="utf-8")
    assert "## Summary" in body
    assert "## Research Focus Alignment" in body
    assert "## Recommended Action" in body
    assert "## Evidence Summary" in body
    assert "## False Negative Suspects" in body
    assert "## Softening Candidate Review" in body
    assert "## Promotion Watchlist" in body
    assert "## Recommended Actions" in body
    assert "## Priorities" in body
    assert "## Candidates" in body
