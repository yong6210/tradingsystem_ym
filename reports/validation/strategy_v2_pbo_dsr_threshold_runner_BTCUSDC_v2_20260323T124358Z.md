# Strategy v2 PBO / DSR Threshold Runner: BTCUSDC

- generated_at_utc: 2026-03-23T12:43:58+00:00
- strategy_version: v2
- available: False
- implementation_status: true_threshold_sweep_runner_no_closed_trades
- reason: pbo_dsr_true_threshold_runner_no_closed_trades
- evaluation_basis: closed_v2_trades + separated true threshold-sweep lineage from stored plan metadata
- lineage_namespace: true_threshold_sweep_runner_v1

## Executive Summary
- eligible_closed_trades: 0
- candidate_trials: 0
- trial_runs_written: 0
- fold_scores_written: 0
- fold_count: 0
- selection_rule: true_threshold_sweep_top_in_sample_ev
- selected_trial_run_id: None
- parameter_families_present: []
- candidate_trials_by_family: {}
- sweep_grid: {'scoring_thresholds': [56.0, 58.0, 60.0, 62.0, 64.0, 66.0, 68.0], 'transition_threshold': [32.5, 35.0, 37.5, 40.0, 42.5, 45.0, 47.5], 'acceptance_rejection_thresholds': [-5.0, 0.0, 5.0], 'sizing_clamps': [0.25, 0.5, 0.75, 1.0]}

## Trial Catalog

## Blockers
- no eligible closed v2 trades for true threshold runner
- true threshold runner produced fewer than 2 candidate trials
- insufficient contiguous samples for true threshold runner folds

## Next Steps
- accumulate eligible closed v2 trades before seeding true threshold-sweep lineage
- keep threshold families populated so CSCV can rank multiple threshold trials
- increase closed-trade sample size or reduce minimum trades per fold

## Notes
- This runner seeds threshold families into a lineage that is separate from the runtime proxy writer.
- It re-evaluates threshold families from stored closed-plan metadata; it is not a full historical engine replay.
