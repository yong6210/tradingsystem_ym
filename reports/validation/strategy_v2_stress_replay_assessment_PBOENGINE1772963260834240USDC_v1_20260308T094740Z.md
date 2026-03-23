# Strategy v2 Stress Replay Assessment: PBOENGINE1772963260834240USDC

- generated_at_utc: 2026-03-08T09:47:40+00:00
- strategy_version: v1
- available: True
- reason: insufficient_stress_samples
- evaluation_basis: strategy_v2_stress_validation_v2 + strategy_v2_stress_replay_lineage_v1

## Coverage
- eligible_closed_trades: 8
- execution_fill_coverage: 0.0000
- estimate_only_share: 1.0000
- latency_candle_coverage: 0.0000
- latency_fallback_share: 1.0000
- shock_regime_trade_share: 0.2500

## Readiness Gates
- full_replay_ready: False
- min_sample_size: 30
- min_execution_fill_coverage: 0.70
- min_latency_candle_coverage: 0.70

## Scenario Evidence
- degraded_scenarios: ['shock_concentration']
- catastrophic_scenarios: []
- worst_scenario: shock_concentration
- scenario_statuses: {'latency_plus_1_bar': {'status': 'PASS', 'catastrophic_loss_detected': False, 'reason': 'within_limits'}, 'partial_fills_only': {'status': 'PASS', 'catastrophic_loss_detected': False, 'reason': 'within_limits'}, 'shock_concentration': {'status': 'WARN', 'catastrophic_loss_detected': False, 'reason': 'negative_ev'}}

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
- execution_fill_coverage_below_threshold
- latency_candle_coverage_below_threshold
- candle_path_coverage_below_threshold
- insufficient_closed_trade_samples_for_replay_upgrade

## Next Steps
- backfill execution fill writers so entry/closed stages exist for more closed v2 trades
- improve 5m candle retention around entry/exit anchors for replay candidates
- add contiguous candle-path validation before marking replay lineage as ready
- accumulate more closed v2 trades before deciding on full replay replacement

## Notes
- This artifact evaluates whether the current stress approximation should remain or be replaced by full replay.
- It does not implement counterfactual order-book replay yet.
