# Strategy v2 PBO / DSR Design: BTCUSDC

- generated_at_utc: 2026-03-07T07:37:09+00:00
- strategy_version: v1
- design_ready: True
- implementation_status: design_ready_artifact_store_schema_ready_empty
- reason: pbo_dsr_artifact_store_ready_not_populated

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
- available: False
- metrics_available: False
- implementation_status: artifact_store_schema_ready_empty
- counts: {'trial_runs': 0, 'fold_scores': 0, 'snapshots': 0}

## Blockers
- parameter sweep result store exists but is not populated
- fold-level trial ranking contract exists but is not populated
- selection-universe count for DSR is not recorded

## Next Implementation Steps
- write parameter sweep trials into validation_trial_runs
- persist CSCV fold scores and selection ranks
- write summary snapshots into validation_pbo_dsr_snapshots

## Notes
- This artifact freezes the future PBO / DSR contract but does not compute either metric yet.
- The runtime validation path can now expose design readiness without overstating implementation status.
