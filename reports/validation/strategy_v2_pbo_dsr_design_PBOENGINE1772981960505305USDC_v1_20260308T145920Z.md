# Strategy v2 PBO / DSR Design: PBOENGINE1772981960505305USDC

- generated_at_utc: 2026-03-08T14:59:20+00:00
- strategy_version: v1
- design_ready: True
- implementation_status: design_ready_dual_lineage_seeded_metrics_pending
- reason: pbo_dsr_dual_lineage_seeded_metrics_pending

## PBO Design
- method: CSCV
- objective_metric: out_of_sample_mean_ev
- pass_threshold: 0.20
- warn_threshold: 0.35
- fail_threshold: 0.35
- parameter_families: ['scoring_thresholds', 'transition_threshold', 'acceptance_rejection_thresholds', 'sizing_clamps']
- required_inputs: ['parameter_sweep_trials', 'fold_level_out_of_sample_scores', 'selected_vs_non_selected_rankings']

## DSR Design
- method: deflated_sharpe_ratio
- min_threshold: 0.00
- required_inputs: ['trade_sequence_returns', 'trial_count', 'selection_universe_size', 'sharpe_estimate', 'return_skew_kurtosis']
- selection_bias_inputs: ['number_of_trials', 'selection_rule', 'best_trial_oos_sharpe']

## Proposed Storage Contract
- artifacts: ['validation_trial_runs', 'validation_trial_fold_scores', 'validation_pbo_dsr_snapshots']
- fields: ['trial_id', 'parameter_family', 'parameter_values', 'fold_id', 'in_sample_metric', 'out_of_sample_metric', 'selection_rank', 'selected_flag', 'sharpe_like_score']

## Runtime Artifact Store
- artifact_store_ready: True
- available: True
- metrics_available: False
- implementation_status: artifact_store_seeded_no_snapshot
- counts: {'trial_runs': 42, 'fold_scores': 84, 'snapshots': 0}
- selection_rule_counts: {'runtime_validation_proxy_top_in_sample_ev': 21, 'true_threshold_sweep_top_in_sample_ev': 21}

## Blockers
- PBO/DSR metrics are not computed yet
- threshold-sweep bias-adjusted DSR snapshot is not available yet

## Next Implementation Steps
- compute PBO/DSR and persist snapshot-level selection_universe_basis
- audit selected-trial source between runtime proxy and true threshold runner lineages
- persist selected trial writer_source into snapshots and reports

## Notes
- This artifact freezes the future PBO / DSR contract but does not compute either metric yet.
- The runtime validation path can now expose design readiness without overstating implementation status.
