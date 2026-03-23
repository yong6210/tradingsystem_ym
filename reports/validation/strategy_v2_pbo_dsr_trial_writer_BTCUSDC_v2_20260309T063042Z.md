# Strategy v2 PBO / DSR Trial Writer: BTCUSDC

- generated_at_utc: 2026-03-09T06:30:42+00:00
- strategy_version: v2
- available: False
- implementation_status: runtime_validation_proxy_writer_insufficient_folds
- reason: pbo_dsr_runtime_proxy_writer_insufficient_folds
- evaluation_basis: closed_v2_trades + mode/lock/stress runtime proxies + stored-plan threshold-sweep proxies

## Executive Summary
- eligible_closed_trades: 2
- candidate_trials: 12
- trial_runs_written: 0
- fold_scores_written: 0
- fold_count: 0
- selected_trial_run_id: None
- selection_rule: runtime_validation_proxy_top_in_sample_ev
- parameter_families_present: ['lock_policy', 'mode_policy', 'stress_policy', 'transition_threshold']
- threshold_parameter_families_present: ['transition_threshold']
- candidate_trials_by_family: {'lock_policy': 2, 'mode_policy': 2, 'stress_policy': 5, 'transition_threshold': 3}

## Trial Catalog

## Blockers
- insufficient contiguous samples to produce at least 2 folds

## Next Steps
- increase closed-trade sample size or reduce minimum trades per fold

## Notes
- Current writer seeds both runtime validation proxies and stored-plan threshold-sweep proxy families.
- Fold rows use contiguous time-order partitions and rank trials by in-sample mean EV inside each fold.
- This writer is intended to close lineage between validation/report and the PBO/DSR artifact store.
