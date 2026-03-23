# Strategy v2 Stress Replay Assessment: PBOENGINE1772972235656568USDC

- generated_at_utc: 2026-03-08T12:17:15+00:00
- strategy_version: v1
- available: True
- reason: insufficient_stress_samples
- evaluation_basis: strategy_v2_stress_validation_v2 + strategy_v2_stress_replay_lineage_v1

## Coverage
- eligible_closed_trades: 8
- execution_fill_coverage: 0.0000
- estimate_only_share: 1.0000
- latency_candle_coverage: 0.0000
- candle_path_coverage: 0.0000
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
- scenario_statuses: {'latency_plus_1_bar': {'status': 'PASS', 'catastrophic_loss_detected': False, 'reason': 'within_limits', 'source': 'approximation', 'artifact_reason': 'artifact_missing'}, 'partial_fills_only': {'status': 'PASS', 'catastrophic_loss_detected': False, 'reason': 'within_limits', 'source': 'approximation', 'artifact_reason': 'artifact_missing'}, 'shock_concentration': {'status': 'WARN', 'catastrophic_loss_detected': False, 'reason': 'negative_ev', 'source': 'approximation', 'artifact_reason': 'artifact_missing'}}

## Deployment Recommendation
- replacement_recommended: False
- decision: keep_approximation
- priority: low
- reason: insufficient_stress_samples
- true_runner_promotion_gate_applied: False
- true_runner_promotion_ready: False
- true_runner_promotion_status: NOT_APPLICABLE
- true_runner_promotion_action: keep_current_path
- true_runner_promotion_reason: insufficient_stress_samples
- threshold_lineage_audit_status: WARN
- threshold_lineage_audit_reason: selected_trial_from_runtime_proxy_while_true_threshold_lineage_exists
- selected_trial_writer_source: runtime_validation_proxy_v1
- selected_trial_selection_rule: runtime_validation_proxy_top_in_sample_ev

## True Runner Readiness
- true_runner_ready: False
- stage: prototype_only
- critical_scenarios: ['shock_concentration']
- critical_scenarios_with_outputs: []
- prototype_output_available_scenarios: []
- scenarios_compared: 0
- true_runner_gate_thresholds: exec=0.85, latency=0.80, path=0.90, scenarios=2

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
