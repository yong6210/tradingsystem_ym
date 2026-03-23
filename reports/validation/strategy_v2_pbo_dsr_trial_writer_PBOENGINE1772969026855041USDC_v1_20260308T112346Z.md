# Strategy v2 PBO / DSR Trial Writer: PBOENGINE1772969026855041USDC

- generated_at_utc: 2026-03-08T11:23:46+00:00
- strategy_version: v1
- available: True
- implementation_status: runtime_validation_proxy_writer_seeded
- reason: pbo_dsr_runtime_proxy_writer_seeded
- evaluation_basis: closed_v2_trades + mode/lock/stress runtime proxies + stored-plan threshold-sweep proxies

## Executive Summary
- eligible_closed_trades: 8
- candidate_trials: 21
- trial_runs_written: 21
- fold_scores_written: 42
- fold_count: 2
- selected_trial_run_id: PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_mode_pol_5841152f7f
- selection_rule: runtime_validation_proxy_top_in_sample_ev
- parameter_families_present: ['acceptance_rejection_thresholds', 'lock_policy', 'mode_policy', 'scoring_thresholds', 'sizing_clamps', 'stress_policy', 'transition_threshold']
- threshold_parameter_families_present: ['acceptance_rejection_thresholds', 'scoring_thresholds', 'sizing_clamps', 'transition_threshold']
- candidate_trials_by_family: {'acceptance_rejection_thresholds': 3, 'lock_policy': 2, 'mode_policy': 2, 'scoring_thresholds': 3, 'sizing_clamps': 3, 'stress_policy': 5, 'transition_threshold': 3}

## Trial Catalog
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_mode_pol_5841152f7f: family=mode_policy, rank=1, selected=True, in_sample=0.55, out_of_sample=0.55, trades=4
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_lock_pol_230ddd4a7a: family=lock_policy, rank=2, selected=False, in_sample=0.513333, out_of_sample=0.536, trades=5
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_transiti_5e5bd2633b: family=transition_threshold, rank=3, selected=False, in_sample=0.483334, out_of_sample=0.5, trades=5
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_transiti_b60be7bb28: family=transition_threshold, rank=4, selected=False, in_sample=0.316667, out_of_sample=0.316667, trades=6
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_scoring__bc114ab82a: family=scoring_thresholds, rank=5, selected=False, in_sample=0.275, out_of_sample=0.275, trades=4
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_acceptan_4beb720ab5: family=acceptance_rejection_thresholds, rank=6, selected=False, in_sample=0.258333, out_of_sample=0.32, trades=5
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_acceptan_60229d3a47: family=acceptance_rejection_thresholds, rank=7, selected=False, in_sample=0.183334, out_of_sample=0.183333, trades=6
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_scoring__0adc37e7bc: family=scoring_thresholds, rank=8, selected=False, in_sample=0.183334, out_of_sample=0.183333, trades=6
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_transiti_68d8bbc58d: family=transition_threshold, rank=9, selected=False, in_sample=0.158334, out_of_sample=0.214286, trades=7
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_acceptan_95b47eb03a: family=acceptance_rejection_thresholds, rank=10, selected=False, in_sample=0.125, out_of_sample=0.125, trades=8
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_lock_pol_c4c173c932: family=lock_policy, rank=11, selected=False, in_sample=0.125, out_of_sample=0.125, trades=8
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_mode_pol_ccc1b35acf: family=mode_policy, rank=12, selected=False, in_sample=0.125, out_of_sample=0.125, trades=8
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_scoring__fb3d4f7b56: family=scoring_thresholds, rank=13, selected=False, in_sample=0.125, out_of_sample=0.125, trades=8
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_sizing_c_5de5ce6aef: family=sizing_clamps, rank=14, selected=False, in_sample=0.125, out_of_sample=0.125, trades=8
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_stress_p_a7523528d6: family=stress_policy, rank=15, selected=False, in_sample=0.025, out_of_sample=0.025, trades=8
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_stress_p_a06f0e0160: family=stress_policy, rank=16, selected=False, in_sample=0.0125, out_of_sample=0.0125, trades=8
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_stress_p_9fc4269f77: family=stress_policy, rank=17, selected=False, in_sample=0.005, out_of_sample=0.005, trades=8
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_sizing_c_9cfaa406d9: family=sizing_clamps, rank=18, selected=False, in_sample=0.0, out_of_sample=-0.0, trades=8
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_sizing_c_5f3672d698: family=sizing_clamps, rank=19, selected=False, in_sample=-0.025, out_of_sample=-0.025, trades=8
- PBOENGINE1772969026855041USDC_v1_runtime_validation_proxy_v1_stress_p_fd54978cb8: family=stress_policy, rank=20, selected=False, in_sample=-0.035, out_of_sample=-0.035, trades=8

## Blockers

## Next Steps
- review computed PBO/DSR metrics against protocol thresholds
- upgrade stored-plan threshold-sweep proxies to true parameter sweep runners when available

## Notes
- Current writer seeds both runtime validation proxies and stored-plan threshold-sweep proxy families.
- Fold rows use contiguous time-order partitions and rank trials by in-sample mean EV inside each fold.
- This writer is intended to close lineage between validation/report and the PBO/DSR artifact store.
