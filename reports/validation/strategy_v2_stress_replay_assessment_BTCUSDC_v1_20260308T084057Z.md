# Strategy v2 Stress Replay Assessment: BTCUSDC

- generated_at_utc: 2026-03-08T08:40:57+00:00
- strategy_version: v1
- available: False
- reason: no_closed_v2_trades
- evaluation_basis: strategy_v2_stress_validation_v2

## Coverage
- eligible_closed_trades: 0
- execution_fill_coverage: 0.0000
- estimate_only_share: 0.0000
- latency_candle_coverage: 0.0000
- latency_fallback_share: 0.0000
- shock_regime_trade_share: 0.0000

## Readiness Gates
- full_replay_ready: False
- min_sample_size: 30
- min_execution_fill_coverage: 0.70
- min_latency_candle_coverage: 0.70

## Scenario Evidence
- degraded_scenarios: ['latency_plus_1_bar', 'partial_fills_only', 'shock_concentration']
- catastrophic_scenarios: []
- worst_scenario: latency_plus_1_bar
- scenario_statuses: {'latency_plus_1_bar': {'status': 'WARN', 'catastrophic_loss_detected': False, 'reason': 'negative_ev'}, 'partial_fills_only': {'status': 'WARN', 'catastrophic_loss_detected': False, 'reason': 'negative_ev'}, 'shock_concentration': {'status': 'WARN', 'catastrophic_loss_detected': False, 'reason': 'negative_ev'}}

## Deployment Recommendation
- replacement_recommended: False
- decision: keep_approximation
- priority: low
- reason: insufficient_stress_samples

## Approximation Limits
- saved closed-v2 realized R is the starting point instead of intrabar execution replay
- partial fills only uses a fixed 50% fill factor
- latency +1 bar uses the next 5m candle open, not order-book path replay
- shock concentration uses heuristic loss amplification / upside compression
- missing execution fills fall back to plan.cost_est decomposition

## Blockers
- insufficient_closed_trade_samples_for_replay_upgrade

## Next Steps
- accumulate more closed v2 trades before deciding on full replay replacement

## Notes
- This artifact evaluates whether the current stress approximation should remain or be replaced by full replay.
- It does not implement counterfactual order-book replay yet.
