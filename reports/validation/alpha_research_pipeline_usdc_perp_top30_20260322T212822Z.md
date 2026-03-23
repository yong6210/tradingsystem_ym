# Alpha Research Pipeline: usdc_perp_top30

- generated_at_utc: 2026-03-22T21:28:22+00:00
- available: True
- reason: ok
- focus_symbol: BTCUSDC
- analysis_symbol: BTCUSDC

## Summary
- alpha_research_candidate_count: 1
- focus_symbol_candidate_count: 0
- top_reason: adjusted_score_non_positive
- top_family: legacy_zone_plan
- top_regime: range
- top_session: dead_session
- avg_softened_risk_r: 0.1400
- max_expected_ev_at_size_r: 0.0000

## Research Focus Alignment
- available: True
- analysis_symbol: BTCUSDC
- aligned_candidate_count: 1
- top_focus: family_forced_exit
- top_bucket: legacy_zone_plan

## Recommended Action
- recommended_action: run_shadow_exit_timing_review
- recommended_scope: family
- recommended_reason: forced_exit_rate is elevated for this family
- shadow_experiment_type: exit_timing_review
- confidence: low
- sample_note: sample is thin; treat as research hint only

## Evidence Summary
- available: True
- analysis_symbol: BTCUSDC
- coverage_note: false_negative_suspects are heuristic only; runtime selection is snapshot data and execution outcomes are windowed history.
- near_miss_top_reason: adjusted_score_non_positive
- focus_aligned_candidates: 1
- focus_top: family_forced_exit:legacy_zone_plan
- top_family_bottleneck: None
- top_regime_bottleneck: None
- top_session_bottleneck: None

## Recommended Actions
- run_shadow_exit_timing_review [family] bucket=legacy_zone_plan: reason=forced_exit_rate is elevated for this family, aligned_candidates=1, confidence=low, observe=['forced_exit_rate', 'time_failure_ratio', 'avg_hold_bars', 'post_cost_ev']

## Focus Priorities
- focus family_forced_exit:legacy_zone_plan: candidates=1, metric=forced_exit_rate, value=1.0000, top_reason=adjusted_score_non_positive, top_symbol=SOLUSDC

## False Negative Suspects

## Softening Candidate Review
- available: False
- top_candidate: None:None reason=None priority=None action=None

## Promotion Watchlist
- available: False
- watchlist_count: 0

## Priorities
- adjusted_score_non_positive: candidates=1, top_family=legacy_zone_plan, top_regime=range, top_session=dead_session, focus_match_count=1, top_focus=family_forced_exit, avg_expected_ev_r=0.2500, avg_softened_risk_r=0.1400

## Candidates
- SOLUSDC long LIMIT: reason=adjusted_score_non_positive, gap=0.0000, softened_risk=0.1400R, expected_ev_r=0.2500, expected_ev_at_size_r=0.0000, focus_matches=1, focus_labels=family_forced_exit:legacy_zone_plan

## Next Steps
- start with alpha-research candidates that match the top decomposition focus before widening softening
- use the matched family/regime/session bucket as the first shadow-mode experiment cluster
- promote only after the matched focus improves without weakening hard-gate safety or structural controls
