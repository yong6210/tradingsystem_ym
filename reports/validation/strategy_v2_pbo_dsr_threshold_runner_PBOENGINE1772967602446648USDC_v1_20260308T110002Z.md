# Strategy v2 PBO / DSR Threshold Runner: PBOENGINE1772967602446648USDC

- generated_at_utc: 2026-03-08T11:00:02+00:00
- strategy_version: v1
- available: True
- implementation_status: true_threshold_sweep_runner_seeded
- reason: pbo_dsr_true_threshold_runner_seeded
- evaluation_basis: closed_v2_trades + separated true threshold-sweep lineage from stored plan metadata
- lineage_namespace: true_threshold_sweep_runner_v1

## Executive Summary
- eligible_closed_trades: 8
- candidate_trials: 21
- trial_runs_written: 21
- fold_scores_written: 42
- fold_count: 2
- selection_rule: true_threshold_sweep_top_in_sample_ev
- selected_trial_run_id: PBOENGINE1772967602446648USDC_v1_transition_threshold_true_max_transition_lt_32_
- parameter_families_present: ['acceptance_rejection_thresholds', 'scoring_thresholds', 'sizing_clamps', 'transition_threshold']
- candidate_trials_by_family: {'acceptance_rejection_thresholds': 3, 'scoring_thresholds': 7, 'sizing_clamps': 4, 'transition_threshold': 7}
- sweep_grid: {'scoring_thresholds': [56.0, 58.0, 60.0, 62.0, 64.0, 66.0, 68.0], 'transition_threshold': [32.5, 35.0, 37.5, 40.0, 42.5, 45.0, 47.5], 'acceptance_rejection_thresholds': [-5.0, 0.0, 5.0], 'sizing_clamps': [0.25, 0.5, 0.75, 1.0]}

## Trial Catalog
- PBOENGINE1772967602446648USDC_v1_transition_threshold_true_max_transition_lt_32_: family=transition_threshold, rank=1, selected=True, in_sample=0.5, out_of_sample=0.5, trades=4
- PBOENGINE1772967602446648USDC_v1_transition_threshold_true_max_transition_lt_35_: family=transition_threshold, rank=2, selected=False, in_sample=0.483334, out_of_sample=0.5, trades=5
- PBOENGINE1772967602446648USDC_v1_transition_threshold_true_max_transition_lt_37_: family=transition_threshold, rank=3, selected=False, in_sample=0.483334, out_of_sample=0.5, trades=5
- PBOENGINE1772967602446648USDC_v1_scoring_thresholds_true_confluence_gte_68_0: family=scoring_thresholds, rank=4, selected=False, in_sample=0.35, out_of_sample=0.566667, trades=3
- PBOENGINE1772967602446648USDC_v1_transition_threshold_true_max_transition_lt_40_: family=transition_threshold, rank=5, selected=False, in_sample=0.316667, out_of_sample=0.316667, trades=6
- PBOENGINE1772967602446648USDC_v1_transition_threshold_true_max_transition_lt_42_: family=transition_threshold, rank=6, selected=False, in_sample=0.316667, out_of_sample=0.316667, trades=6
- PBOENGINE1772967602446648USDC_v1_scoring_thresholds_true_confluence_gte_66_0: family=scoring_thresholds, rank=7, selected=False, in_sample=0.275, out_of_sample=0.275, trades=4
- PBOENGINE1772967602446648USDC_v1_acceptance_rejection_thresholds_true_delta_5_0: family=acceptance_rejection_thresholds, rank=8, selected=False, in_sample=0.258333, out_of_sample=0.32, trades=5
- PBOENGINE1772967602446648USDC_v1_acceptance_rejection_thresholds_true_delta_5_0: family=acceptance_rejection_thresholds, rank=9, selected=False, in_sample=0.258333, out_of_sample=0.125, trades=8
- PBOENGINE1772967602446648USDC_v1_scoring_thresholds_true_confluence_gte_62_0: family=scoring_thresholds, rank=10, selected=False, in_sample=0.183334, out_of_sample=0.183333, trades=6
- PBOENGINE1772967602446648USDC_v1_transition_threshold_true_max_transition_lt_45_: family=transition_threshold, rank=11, selected=False, in_sample=0.158334, out_of_sample=0.214286, trades=7
- PBOENGINE1772967602446648USDC_v1_transition_threshold_true_max_transition_lt_47_: family=transition_threshold, rank=12, selected=False, in_sample=0.158334, out_of_sample=0.214286, trades=7
- PBOENGINE1772967602446648USDC_v1_scoring_thresholds_true_confluence_gte_60_0: family=scoring_thresholds, rank=13, selected=False, in_sample=0.141667, out_of_sample=0.2, trades=7
- PBOENGINE1772967602446648USDC_v1_acceptance_rejection_thresholds_true_delta_0_0: family=acceptance_rejection_thresholds, rank=14, selected=False, in_sample=0.125, out_of_sample=0.125, trades=8
- PBOENGINE1772967602446648USDC_v1_scoring_thresholds_true_confluence_gte_56_0: family=scoring_thresholds, rank=15, selected=False, in_sample=0.125, out_of_sample=0.125, trades=8
- PBOENGINE1772967602446648USDC_v1_scoring_thresholds_true_confluence_gte_58_0: family=scoring_thresholds, rank=16, selected=False, in_sample=0.125, out_of_sample=0.125, trades=8
- PBOENGINE1772967602446648USDC_v1_sizing_clamps_true_max_risk_r_1_0: family=sizing_clamps, rank=17, selected=False, in_sample=0.125, out_of_sample=0.125, trades=8
- PBOENGINE1772967602446648USDC_v1_sizing_clamps_true_max_risk_r_0_75: family=sizing_clamps, rank=18, selected=False, in_sample=0.075, out_of_sample=0.075, trades=8
- PBOENGINE1772967602446648USDC_v1_scoring_thresholds_true_confluence_gte_64_0: family=scoring_thresholds, rank=19, selected=False, in_sample=0.008333, out_of_sample=0.12, trades=5
- PBOENGINE1772967602446648USDC_v1_sizing_clamps_true_max_risk_r_0_5: family=sizing_clamps, rank=20, selected=False, in_sample=0.0, out_of_sample=-0.0, trades=8

## Blockers

## Next Steps
- audit proxy writer vs true threshold runner selected trials
- review combined PBO/DSR metrics against validation protocol thresholds

## Notes
- This runner seeds threshold families into a lineage that is separate from the runtime proxy writer.
- It re-evaluates threshold families from stored closed-plan metadata; it is not a full historical engine replay.
