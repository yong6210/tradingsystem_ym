# Strategy v2 Stress Replay Assessment: BTCUSDC

- generated_at_utc: 2026-03-08T07:48:24+00:00
- strategy_version: v1
- available: True
- reason: multiple_degraded_scenarios:latency_plus_1_bar,partial_fills_only
- evaluation_basis: strategy_v2_stress_validation_v2

## Coverage
- eligible_closed_trades: 60
- execution_fill_coverage: 0.9000
- estimate_only_share: 0.1000
- latency_candle_coverage: 0.8000
- latency_fallback_share: 0.2000
- shock_regime_trade_share: 0.1667

## Readiness Gates
- full_replay_ready: True
- min_sample_size: 30
- min_execution_fill_coverage: 0.70
- min_latency_candle_coverage: 0.70

## Scenario Evidence
- degraded_scenarios: ['latency_plus_1_bar', 'partial_fills_only']
- catastrophic_scenarios: []
- worst_scenario: latency_plus_1_bar
- scenario_statuses: {'latency_plus_1_bar': {'status': 'WARN', 'reason': 'negative_ev', 'catastrophic_loss_detected': False}, 'partial_fills_only': {'status': 'WARN', 'reason': 'negative_ev', 'catastrophic_loss_detected': False}, 'shock_concentration': {'status': 'PASS', 'reason': 'within_limits', 'catastrophic_loss_detected': False}}

## Deployment Recommendation
- replacement_recommended: True
- decision: prepare_full_replay
- priority: medium
- reason: multiple_degraded_scenarios:latency_plus_1_bar,partial_fills_only

## Approximation Limits
- saved closed-v2 realized R is the starting point instead of intrabar execution replay
- partial fills only uses a fixed 50% fill factor
- latency +1 bar uses the next 5m candle open, not order-book path replay
- shock concentration uses heuristic loss amplification / upside compression
- missing execution fills fall back to plan.cost_est decomposition

## Blockers

## Next Steps
- prototype full replay on worst degraded stress scenarios first
- compare replay-derived stress outputs against current approximation payload

## Notes
- This artifact evaluates whether the current stress approximation should remain or be replaced by full replay.
- It does not implement counterfactual order-book replay yet.
