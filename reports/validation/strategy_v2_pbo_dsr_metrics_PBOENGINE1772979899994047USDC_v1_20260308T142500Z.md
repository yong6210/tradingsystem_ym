# Strategy v2 PBO / DSR Metrics: PBOENGINE1772979899994047USDC

- generated_at_utc: 2026-03-08T14:25:00+00:00
- strategy_version: v1
- available: True
- metrics_complete: True
- reason: pbo_dsr_metrics_computed

## Executive Summary
- decision: warn_lineage_audit
- meets_protocol_gate: True
- recommendation_reason: selected_trial_from_runtime_proxy_while_true_threshold_lineage_exists
- trial_runs: 42
- fold_scores: 84
- eligible_pbo_folds: 2

## Selected Trial
- trial_run_id: PBOENGINE1772979899994047USDC_v1_runtime_validation_proxy_v1_mode_pol_5841152f7f
- parameter_family: mode_policy
- selection_rank: 1
- out_of_sample_metric: 0.55
- sharpe_like_score: 1.732051
- selection_universe_size: 21
- lineage_selection_universe_size: 21
- selection_universe_basis: runtime_proxy_hybrid_lineage
- full_parameter_sweep_selection_universe_size: None
- writer_source: runtime_validation_proxy_v1

## Selection Universe
- combined_artifact_selection_universe_size: 42
- runtime_proxy_selection_universe_size: 21
- true_threshold_selection_universe_size: 21
- full_parameter_sweep_selection_universe_size: 21
- dsr_selection_universe_size: 21
- dsr_selection_universe_basis: full_parameter_sweep_universe
- bias_adjustment_rechecked: True
- recording_status: split_recorded

## Lineage Audit
- audit_status: WARN
- reason: selected_trial_from_runtime_proxy_while_true_threshold_lineage_exists
- lineage_mix_state: dual_lineage
- runtime_proxy_trial_count: 21
- true_threshold_trial_count: 21
- selected_trial_from_runtime_proxy: True
- selected_trial_from_true_threshold: False

## PBO
- available: True
- value: 0.0
- status: PASS
- reason: pbo_below_pass_threshold
- eligible_folds: 2
- overfit_folds: 0
- selected_rank_percentile_avg: 0.131

## DSR
- available: True
- value: 0.676778
- probability: 0.750727
- status: PASS
- reason: dsr_positive
- selected_trial_sharpe: 1.732051
- benchmark_sharpe: 1.109728
- sample_size: 4
- selection_universe_size: 21
- selection_universe_basis: full_parameter_sweep_universe
- legacy_combined_selection_universe_size: 42
- legacy_combined_benchmark_sharpe: 1.27519
- benchmark_sharpe_delta_vs_legacy_combined: -0.165461

## Blockers

## Next Steps
- compare computed PBO/DSR against validation protocol thresholds
- audit proxy lineage vs true threshold lineage before deployment approval

## Notes
- PBO is currently computed as the fraction of CSCV folds where the selected trial lands in the worse half out-of-sample.
- DSR is currently emitted as a signed deflated-Sharpe score plus a Normal CDF probability for interpretation.
