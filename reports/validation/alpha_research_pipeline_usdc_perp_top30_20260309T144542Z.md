# Alpha Research Pipeline: usdc_perp_top30

- generated_at_utc: 2026-03-09T14:45:42+00:00
- available: True
- reason: ok
- focus_symbol: BTCUSDC
- analysis_symbol: BTCUSDC

## Summary
- alpha_research_candidate_count: 2
- focus_symbol_candidate_count: 1
- top_reason: risk_budget_below_min
- top_family: trend_continuation
- top_regime: range
- top_session: dead_session
- avg_softened_risk_r: 0.1500
- max_expected_ev_at_size_r: 0.0900

## Research Focus Alignment
- available: True
- analysis_symbol: BTCUSDC
- aligned_candidate_count: 2
- top_focus: session_negative_ev
- top_bucket: dead_session

## Priorities
- focus session_negative_ev:dead_session: candidates=2, metric=ev, value=-0.3500, top_reason=risk_budget_below_min, top_symbol=ETHUSDC
- focus entry_model_fill_rate:LIMIT: candidates=1, metric=fill_rate, value=0.4000, top_reason=risk_budget_below_min, top_symbol=BTCUSDC
- focus family_information_failure:trend_continuation: candidates=1, metric=information_failure_rate, value=0.4000, top_reason=risk_budget_below_min, top_symbol=BTCUSDC

## Priorities
- risk_budget_below_min: candidates=1, top_family=trend_continuation, top_regime=range, top_session=dead_session, focus_match_count=3, top_focus=family_information_failure, avg_expected_ev_r=0.1800, avg_softened_risk_r=0.2000
- adjusted_score_non_positive: candidates=1, top_family=sweep_reversal, top_regime=range, top_session=dead_session, focus_match_count=1, top_focus=session_negative_ev, avg_expected_ev_r=0.1100, avg_softened_risk_r=0.1000

## Candidates
- BTCUSDC long LIMIT: reason=risk_budget_below_min, gap=4.5000, softened_risk=0.2000R, expected_ev_r=0.1800, expected_ev_at_size_r=0.0900, focus_matches=3, focus_labels=family_information_failure:trend_continuation,session_negative_ev:dead_session,entry_model_fill_rate:LIMIT
- ETHUSDC short CONFIRM: reason=adjusted_score_non_positive, gap=2.0000, softened_risk=0.1000R, expected_ev_r=0.1100, expected_ev_at_size_r=0.0500, focus_matches=1, focus_labels=session_negative_ev:dead_session

## Next Steps
- start with alpha-research candidates that match the top decomposition focus before widening softening
- use the matched family/regime/session bucket as the first shadow-mode experiment cluster
- promote only after the matched focus improves without weakening hard-gate safety or structural controls
