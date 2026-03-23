# Strategy v2 PBO / DSR Trial Writer: PBOENGINE1772963260834240USDC

- generated_at_utc: 2026-03-08T09:47:40+00:00
- strategy_version: v1
- available: True
- implementation_status: runtime_validation_proxy_writer_seeded
- reason: pbo_dsr_runtime_proxy_writer_seeded
- evaluation_basis: closed_v2_trades + mode/lock/stress runtime proxies

## Executive Summary
- eligible_closed_trades: 8
- candidate_trials: 9
- trial_runs_written: 9
- fold_scores_written: 18
- fold_count: 2
- selected_trial_run_id: PBOENGINE1772963260834240USDC_v1_mode_policy_a_only
- selection_rule: runtime_validation_proxy_top_in_sample_ev
- parameter_families_present: ['lock_policy', 'mode_policy', 'stress_policy']

## Trial Catalog
- PBOENGINE1772963260834240USDC_v1_mode_policy_a_only: family=mode_policy, rank=1, selected=True, in_sample=0.55, out_of_sample=0.55, trades=4
- PBOENGINE1772963260834240USDC_v1_lock_policy_after_lock: family=lock_policy, rank=2, selected=False, in_sample=0.513333, out_of_sample=0.536, trades=5
- PBOENGINE1772963260834240USDC_v1_lock_policy_before_lock: family=lock_policy, rank=3, selected=False, in_sample=0.125, out_of_sample=0.125, trades=8
- PBOENGINE1772963260834240USDC_v1_mode_policy_a_plus_b: family=mode_policy, rank=4, selected=False, in_sample=0.125, out_of_sample=0.125, trades=8
- PBOENGINE1772963260834240USDC_v1_stress_policy_baseline_cost: family=stress_policy, rank=5, selected=False, in_sample=0.025, out_of_sample=0.025, trades=8
- PBOENGINE1772963260834240USDC_v1_stress_policy_partial_fills_only: family=stress_policy, rank=6, selected=False, in_sample=0.0125, out_of_sample=0.0125, trades=8
- PBOENGINE1772963260834240USDC_v1_stress_policy_latency_plus_1_bar: family=stress_policy, rank=7, selected=False, in_sample=0.005, out_of_sample=0.005, trades=8
- PBOENGINE1772963260834240USDC_v1_stress_policy_stressed_cost: family=stress_policy, rank=8, selected=False, in_sample=-0.035, out_of_sample=-0.035, trades=8
- PBOENGINE1772963260834240USDC_v1_stress_policy_shock_concentration: family=stress_policy, rank=9, selected=False, in_sample=-0.04375, out_of_sample=-0.04375, trades=8

## Blockers

## Next Steps
- review computed PBO/DSR metrics against protocol thresholds
- connect true threshold-sweep trial families when available

## Notes
- Current writer seeds runtime proxy trials from existing validation axes, not from a full threshold sweep.
- Fold rows use contiguous time-order partitions and rank trials by in-sample mean EV inside each fold.
- This writer is intended to close lineage between validation/report and the PBO/DSR artifact store.
