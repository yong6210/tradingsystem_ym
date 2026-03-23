# Strategy v2 PBO / DSR Threshold Runner: BTCUSDC

- generated_at_utc: 2026-03-09T19:34:34+00:00
- strategy_version: v2
- available: False
- implementation_status: true_threshold_sweep_runner_insufficient_folds
- reason: pbo_dsr_true_threshold_runner_insufficient_folds
- evaluation_basis: closed_v2_trades + separated true threshold-sweep lineage from stored plan metadata
- lineage_namespace: true_threshold_sweep_runner_v1

## Executive Summary
- eligible_closed_trades: 2
- candidate_trials: 7
- trial_runs_written: 0
- fold_scores_written: 0
- fold_count: 0
- selection_rule: true_threshold_sweep_top_in_sample_ev
- selected_trial_run_id: None
- parameter_families_present: ['transition_threshold']
- candidate_trials_by_family: {'transition_threshold': 7}
- sweep_grid: {'scoring_thresholds': [56.0, 58.0, 60.0, 62.0, 64.0, 66.0, 68.0], 'transition_threshold': [32.5, 35.0, 37.5, 40.0, 42.5, 45.0, 47.5], 'acceptance_rejection_thresholds': [-5.0, 0.0, 5.0], 'sizing_clamps': [0.25, 0.5, 0.75, 1.0]}

## Trial Catalog

## Blockers
- insufficient contiguous samples for true threshold runner folds

## Next Steps
- increase closed-trade sample size or reduce minimum trades per fold

## Notes
- This runner seeds threshold families into a lineage that is separate from the runtime proxy writer.
- It re-evaluates threshold families from stored closed-plan metadata; it is not a full historical engine replay.
