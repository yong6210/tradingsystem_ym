# Strategy v2 PBO / DSR Trial Writer: BTCUSDC

- generated_at_utc: 2026-03-08T13:07:30+00:00
- strategy_version: v1
- available: False
- implementation_status: runtime_validation_proxy_writer_no_closed_trades
- reason: pbo_dsr_runtime_proxy_writer_no_closed_trades
- evaluation_basis: closed_v2_trades + mode/lock/stress runtime proxies + stored-plan threshold-sweep proxies

## Executive Summary
- eligible_closed_trades: 0
- candidate_trials: 0
- trial_runs_written: 0
- fold_scores_written: 0
- fold_count: 0
- selected_trial_run_id: None
- selection_rule: runtime_validation_proxy_top_in_sample_ev
- parameter_families_present: []
- threshold_parameter_families_present: []
- candidate_trials_by_family: {}

## Trial Catalog

## Blockers
- no eligible closed v2 trades for runtime proxy writer
- runtime proxy writer produced fewer than 2 candidate trials
- insufficient contiguous samples to produce at least 2 folds

## Next Steps
- accumulate eligible closed v2 trades before seeding PBO/DSR proxy trials
- keep mode/lock/stress validation axes populated so multiple proxy trials remain available
- increase closed-trade sample size or reduce minimum trades per fold

## Notes
- Current writer seeds both runtime validation proxies and stored-plan threshold-sweep proxy families.
- Fold rows use contiguous time-order partitions and rank trials by in-sample mean EV inside each fold.
- This writer is intended to close lineage between validation/report and the PBO/DSR artifact store.
