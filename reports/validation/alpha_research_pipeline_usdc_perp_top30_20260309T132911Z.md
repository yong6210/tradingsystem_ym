# Alpha Research Pipeline: usdc_perp_top30

- generated_at_utc: 2026-03-09T13:29:11+00:00
- available: True
- reason: ok
- focus_symbol: BTCUSDC

## Summary
- alpha_research_candidate_count: 2
- focus_symbol_candidate_count: 1
- top_reason: risk_budget_below_min
- top_family: trend_continuation
- top_regime: range
- top_session: dead_session
- avg_softened_risk_r: 0.1500
- max_expected_ev_at_size_r: 0.0900

## Priorities
- risk_budget_below_min: candidates=1, top_family=trend_continuation, top_regime=range, top_session=dead_session, avg_expected_ev_r=0.1800, avg_softened_risk_r=0.2000
- adjusted_score_non_positive: candidates=1, top_family=sweep_reversal, top_regime=range, top_session=dead_session, avg_expected_ev_r=0.1100, avg_softened_risk_r=0.1000

## Candidates
- BTCUSDC long LIMIT: reason=risk_budget_below_min, gap=4.5000, softened_risk=0.2000R, expected_ev_r=0.1800, expected_ev_at_size_r=0.0900
- ETHUSDC short CONFIRM: reason=adjusted_score_non_positive, gap=2.0000, softened_risk=0.1000R, expected_ev_r=0.1100, expected_ev_at_size_r=0.0500

## Next Steps
- review the top alpha-research candidate in shadow mode before any rollout change
- compare repeated near-miss reasons against execution/operator-dashboard quality softening priorities
- promote only when research evidence clears the same reason across family, regime, and session clusters
