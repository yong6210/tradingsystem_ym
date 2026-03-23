# Strategy v2 PBO / DSR Metrics: PBOEMPTY1772967727866368USDC

- generated_at_utc: 2026-03-08T11:02:07+00:00
- strategy_version: v1
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
