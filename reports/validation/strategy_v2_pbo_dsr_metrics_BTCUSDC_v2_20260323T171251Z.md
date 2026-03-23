# Strategy v2 PBO / DSR Metrics: BTCUSDC

- generated_at_utc: 2026-03-23T17:12:51+00:00
- strategy_version: v2
- available: False
- metrics_complete: False
- reason: pbo_dsr_trial_runs_missing

## Executive Summary
- decision: not_ready
- meets_protocol_gate: False
- recommendation_reason: pbo_dsr_trial_runs_missing
- trial_runs: 0
- fold_scores: 0
- eligible_pbo_folds: 0

## Selected Trial
- none

## Selection Universe
- combined_artifact_selection_universe_size: 0
- runtime_proxy_selection_universe_size: 0
- true_threshold_selection_universe_size: 0
- full_parameter_sweep_selection_universe_size: None
- dsr_selection_universe_size: None
- dsr_selection_universe_basis: combined_artifact_universe
- bias_adjustment_rechecked: False
- recording_status: combined_only

## Lineage Audit
- audit_status: WARN
- reason: selection_rule_counts_missing
- lineage_mix_state: no_lineage
- runtime_proxy_trial_count: 0
- true_threshold_trial_count: 0
- selected_trial_from_runtime_proxy: False
- selected_trial_from_true_threshold: False

## PBO
- available: False
- value: None
- status: not_available
- reason: insufficient_fold_scores
- eligible_folds: 0
- overfit_folds: 0
- selected_rank_percentile_avg: None

## DSR
- available: False
- value: None
- probability: None
- status: not_available
- reason: selected_trial_missing
- selected_trial_sharpe: None
- benchmark_sharpe: None
- sample_size: None
- selection_universe_size: None
- selection_universe_basis: combined_artifact_universe
- legacy_combined_selection_universe_size: None
- legacy_combined_benchmark_sharpe: None
- benchmark_sharpe_delta_vs_legacy_combined: None

## Blockers
- validation_trial_runs is empty
- validation_trial_fold_scores is empty
- insufficient_fold_scores
- selected_trial_missing

## Next Steps
- run validation/report after enough eligible closed v2 trades or connect threshold-sweep trial writer
- write CSCV fold scores into validation_trial_fold_scores
- complete seeded trial/fold lineage so PBO and DSR can both compute

## Notes
- PBO is currently computed as the fraction of CSCV folds where the selected trial lands in the worse half out-of-sample.
- DSR is currently emitted as a signed deflated-Sharpe score plus a Normal CDF probability for interpretation.
