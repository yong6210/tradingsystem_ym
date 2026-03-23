# Replay Evidence Review: BTCUSDC

- generated_at: 2026-03-23T20:18:06+00:00
- symbol: BTCUSDC
- version: v2
- days: 180
- evidence_basis: historical_closed_plans_plus_stress_replay_lineage_proxy
- do_not_treat_as_live_confidence: True

## Headline

- confidence_state: insufficient_replay_lineage
- evidence_bias: gather_more_replay_evidence
- summary: Replay lineage is still incomplete, so historical evidence should stay descriptive only.

## A / B Family Replay Context

- A edge_state: insufficient_sample | bias: gather_more_evidence | trades: 1
- B edge_state: insufficient_sample | bias: gather_more_evidence | trades: 1

## Replay Lineage

- available: True
- runtime_inputs_ready: False
- reason: runtime_lineage_incomplete
- coverage: {'execution_fill_coverage': 0.5, 'latency_candle_coverage': 1.0, 'candle_path_coverage': 0.5, 'estimate_only_share': 0.5}
- blocked_by: ['execution_fill_coverage_below_threshold', 'candle_path_coverage_below_threshold']

## Replay Assessment

- available: True
- full_replay_ready: False
- replacement_recommended: False
- reason: insufficient_stress_samples
- deployment_recommendation: {'decision': 'keep_approximation', 'priority': 'low', 'reason': 'insufficient_stress_samples', 'baseline_decision': 'keep_approximation', 'baseline_reason': 'insufficient_stress_samples', 'true_runner_promotion_gate_applied': False, 'true_runner_promotion_ready': False, 'true_runner_promotion_status': 'NOT_APPLICABLE', 'true_runner_promotion_action': 'keep_current_path', 'true_runner_promotion_reason': 'insufficient_stress_samples', 'threshold_lineage_audit_status': 'not_available', 'threshold_lineage_audit_reason': 'not_available', 'selected_trial_writer_source': 'unknown', 'selected_trial_selection_rule': '', 'selected_trial_from_runtime_proxy': False, 'selected_trial_from_true_threshold': False, 'replay_output_lineage_gate_applied': False, 'replay_output_lineage_alignment_status': 'NOT_AVAILABLE', 'replay_output_lineage_alignment_reason': 'replay_output_lineage_unavailable', 'replay_output_lineage_scenarios_compared': 0, 'replay_output_lineage_compared_scenarios': [], 'replay_output_lineage_worker_modes': [], 'replay_output_lineage_input_batch_count': 0, 'replay_output_lineage_input_trade_rows': 0, 'pbo_dsr_metrics_complete': False, 'pbo_dsr_meets_protocol_gate': False, 'true_runner_promotion_blocked_by': [], 'true_runner_promotion_next_steps': [], 'approval_cross_display': {'available': False, 'cross_display_status': 'NOT_AVAILABLE', 'cross_display_reason': 'approval_cross_display_inputs_unavailable', 'threshold_lineage_winner_run_id': None, 'threshold_lineage_winner_source': 'unknown', 'threshold_lineage_winner_selection_rule': '', 'threshold_lineage_winner_type': 'unresolved', 'threshold_lineage_audit_status': 'not_available', 'replay_derived_worst_scenario': 'latency_plus_1_bar', 'replay_derived_worst_scenario_source': 'approximation', 'replay_derived_worst_scenario_status': 'PASS', 'replay_derived_worst_scenario_reason': 'within_limits', 'replay_derived_worst_scenario_divergence_status': 'NOT_AVAILABLE', 'replay_derived_worst_scenario_divergence_reason': 'not_available', 'replay_derived_worst_scenario_has_output_lineage': False, 'replay_output_compared_scenarios': [], 'replay_output_input_trade_rows': 0, 'approval_warning_locked': True, 'approval_warning_code': 'threshold_lineage_winner_unresolved', 'approval_warning_message': 'selected-trial lineage winner is unresolved; approval review must stay manual until threshold lineage is identified'}}

## Next Actions
- Treat replay evidence as historical context only; do not merge it into live sample counts.
- Keep A/B live confidence decisions anchored to closed live evidence first.
- Keep collecting closed trades before changing deployment confidence.
- Watch regime bucket `unknown` because it currently has the largest sample concentration.
- backfill execution fill writers so entry/closed stages exist for more closed v2 trades