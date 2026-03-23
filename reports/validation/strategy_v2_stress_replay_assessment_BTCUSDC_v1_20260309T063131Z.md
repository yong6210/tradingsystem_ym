# Strategy v2 Stress Replay Assessment: BTCUSDC

- generated_at_utc: 2026-03-09T06:31:31+00:00
- strategy_version: v1
- available: True
- reason: multiple_degraded_scenarios:latency_plus_1_bar,partial_fills_only
- evaluation_basis: strategy_v2_stress_validation_v2 + strategy_v2_stress_replay_lineage_v1

## Coverage
- eligible_closed_trades: 60
- execution_fill_coverage: 0.9000
- estimate_only_share: 0.1000
- latency_candle_coverage: 0.8000
- candle_path_coverage: 0.8200
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
- true_runner_promotion_gate_applied: True
- true_runner_promotion_ready: False
- true_runner_promotion_status: BLOCKED
- true_runner_promotion_action: stay_on_prototype
- true_runner_promotion_reason: true_runner_readiness_not_met
- threshold_lineage_audit_status: not_available
- threshold_lineage_audit_reason: not_available
- selected_trial_writer_source: unknown
- selected_trial_selection_rule: 
- replay_output_lineage_alignment_status: NOT_AVAILABLE
- replay_output_lineage_alignment_reason: replay_output_lineage_unavailable
- replay_output_lineage_compared_scenarios: []
- replay_output_lineage_worker_modes: []
- replay_output_lineage_input_batch_count: 0, input_trade_rows: 0
- approval_cross_display: {'available': False, 'cross_display_status': 'NOT_AVAILABLE', 'cross_display_reason': 'approval_cross_display_inputs_unavailable', 'threshold_lineage_winner_run_id': None, 'threshold_lineage_winner_source': 'unknown', 'threshold_lineage_winner_selection_rule': '', 'threshold_lineage_winner_type': 'unresolved', 'threshold_lineage_audit_status': 'not_available', 'replay_derived_worst_scenario': 'latency_plus_1_bar', 'replay_derived_worst_scenario_source': 'stressed_cost', 'replay_derived_worst_scenario_status': 'WARN', 'replay_derived_worst_scenario_reason': 'negative_ev', 'replay_derived_worst_scenario_divergence_status': 'NOT_AVAILABLE', 'replay_derived_worst_scenario_divergence_reason': 'not_available', 'replay_derived_worst_scenario_has_output_lineage': False, 'replay_output_compared_scenarios': [], 'replay_output_input_trade_rows': 0, 'approval_warning_locked': True, 'approval_warning_code': 'threshold_lineage_winner_unresolved', 'approval_warning_message': 'selected-trial lineage winner is unresolved; approval review must stay manual until threshold lineage is identified'}

## True Runner Readiness
- true_runner_ready: False
- stage: prototype_only
- critical_scenarios: ['latency_plus_1_bar', 'partial_fills_only']
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

## Next Steps
- runtime lineage is ready enough to prototype replay runner inputs
- prototype full replay on worst degraded stress scenarios first
- compare replay-derived stress outputs against current approximation payload

## Notes
- This artifact evaluates whether the current stress approximation should remain or be replaced by full replay.
- It does not implement counterfactual order-book replay yet.
