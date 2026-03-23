# Alpha Research Pipeline: usdc_perp_top30

- generated_at_utc: 2026-03-23T16:45:58+00:00
- available: False
- reason: no_alpha_research_candidates
- focus_symbol: PBOENGINE1774284357904898USDC
- analysis_symbol: PBOENGINE1774284357904898USDC

## Summary
- alpha_research_candidate_count: 0
- focus_symbol_candidate_count: 0
- top_reason: None
- top_family: None
- top_regime: None
- top_session: None
- avg_softened_risk_r: 0.0000
- max_expected_ev_at_size_r: 0.0000

## Research Focus Alignment
- available: True
- analysis_symbol: PBOENGINE1774284357904898USDC
- aligned_candidate_count: 0
- top_focus: family_forced_exit
- top_bucket: sweep_reversal

## Recommended Action
- recommended_action: run_shadow_cost_stress_review
- recommended_scope: global
- recommended_reason: stressed cost materially weakens EV
- shadow_experiment_type: cost_stress_review
- confidence: low
- sample_note: sample is thin; treat as research hint only

## Evidence Summary
- available: False
- analysis_symbol: None
- coverage_note: None
- near_miss_top_reason: None
- focus_aligned_candidates: 0
- focus_top: None:None
- top_family_bottleneck: None
- top_regime_bottleneck: None
- top_session_bottleneck: None

## Recommended Actions
- run_shadow_cost_stress_review [global] bucket=shock_concentration: reason=stressed cost materially weakens EV, aligned_candidates=0, confidence=low, observe=['baseline_cost_ev', 'stressed_cost_ev', 'delta_ev_stressed_minus_baseline']
- run_shadow_exit_timing_review [family] bucket=sweep_reversal: reason=forced_exit_rate is elevated for this family, aligned_candidates=0, confidence=medium, observe=['forced_exit_rate', 'time_failure_ratio', 'avg_hold_bars', 'post_cost_ev']
- run_shadow_regime_filter_review [regime] bucket=shock: reason=post-cost EV is negative in this regime, aligned_candidates=0, confidence=low, observe=['ev', 'p5_ev', 'max_drawdown', 'candidate_pass_rate']

## Focus Priorities
- focus family_forced_exit:sweep_reversal: candidates=0, metric=forced_exit_rate, value=0.5714, top_reason=None, top_symbol=None
- focus regime_negative_ev:shock: candidates=0, metric=ev, value=-0.4500, top_reason=None, top_symbol=None
- focus post_cost_ev_deterioration:shock_concentration: candidates=0, metric=delta_ev_stressed_minus_baseline, value=-0.0600, top_reason=None, top_symbol=None

## False Negative Suspects

## Softening Candidate Review
- available: False
- top_candidate: None:None reason=None priority=None action=None

## Promotion Watchlist
- available: False
- watchlist_count: 0

## Priorities

## Candidates

## Next Steps
- wait for new softening candidates that match PBOENGINE1774284357904898USDC or widen the universe review window
