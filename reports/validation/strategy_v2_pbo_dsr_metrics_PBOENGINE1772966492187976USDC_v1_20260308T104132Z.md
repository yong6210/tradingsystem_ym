# Strategy v2 PBO / DSR Metrics: PBOENGINE1772966492187976USDC

- generated_at_utc: 2026-03-08T10:41:32+00:00
- strategy_version: v1
- available: True
- metrics_complete: True
- reason: pbo_dsr_metrics_computed

## Executive Summary
- decision: fail_validation_gate
- meets_protocol_gate: False
- recommendation_reason: pbo_status=PASS,dsr_status=PASS
- trial_runs: 21
- fold_scores: 42
- eligible_pbo_folds: 2

## Selected Trial
- trial_run_id: PBOENGINE1772966492187976USDC_v1_mode_policy_a_only
- parameter_family: mode_policy
- selection_rank: 1
- out_of_sample_metric: 0.55
- sharpe_like_score: 1.732051
- selection_universe_size: 21

## PBO
- available: True
- value: 0.0
- status: PASS
- reason: pbo_below_pass_threshold
- eligible_folds: 2
- overfit_folds: 0
- selected_rank_percentile_avg: 0.1429

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

## Blockers

## Next Steps
- compare computed PBO/DSR against validation protocol thresholds

## Notes
- PBO is currently computed as the fraction of CSCV folds where the selected trial lands in the worse half out-of-sample.
- DSR is currently emitted as a signed deflated-Sharpe score plus a Normal CDF probability for interpretation.
