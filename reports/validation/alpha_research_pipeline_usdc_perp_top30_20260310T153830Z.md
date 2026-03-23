# Alpha Research Pipeline: usdc_perp_top30

- generated_at_utc: 2026-03-10T15:38:30+00:00
- available: False
- reason: no_alpha_research_candidates
- focus_symbol: BTCUSDC
- analysis_symbol: BTCUSDC

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
- analysis_symbol: BTCUSDC
- aligned_candidate_count: 0
- top_focus: family_forced_exit
- top_bucket: trend_continuation

## Recommended Action
- recommended_action: run_shadow_exit_timing_review
- recommended_scope: family
- recommended_reason: forced_exit_rate is elevated for this family
- shadow_experiment_type: exit_timing_review
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
- run_shadow_exit_timing_review [family] bucket=trend_continuation: reason=forced_exit_rate is elevated for this family, aligned_candidates=0, confidence=low, observe=['forced_exit_rate', 'time_failure_ratio', 'avg_hold_bars', 'post_cost_ev']

## Focus Priorities
- focus family_forced_exit:trend_continuation: candidates=0, metric=forced_exit_rate, value=1.0000, top_reason=None, top_symbol=None

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
- wait for new softening candidates that match BTCUSDC or widen the universe review window
