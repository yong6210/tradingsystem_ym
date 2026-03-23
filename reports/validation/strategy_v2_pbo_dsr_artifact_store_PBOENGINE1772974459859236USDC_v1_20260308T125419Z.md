# Strategy v2 PBO / DSR Artifact Store: PBOENGINE1772974459859236USDC

- generated_at_utc: 2026-03-08T12:54:19+00:00
- strategy_version: v1
- artifact_store_ready: True
- available: True
- implementation_status: artifact_store_seeded_no_snapshot
- reason: artifact_store_seeded_snapshot_missing

## Counts
- trial_runs: 42
- fold_scores: 84
- snapshots: 0
- parameter_families_present: ['acceptance_rejection_thresholds', 'lock_policy', 'mode_policy', 'scoring_thresholds', 'sizing_clamps', 'stress_policy', 'transition_threshold']
- selection_rule_counts: {'runtime_validation_proxy_top_in_sample_ev': 21, 'true_threshold_sweep_top_in_sample_ev': 21}
- selection_universe_sizes: [21]
- selection_universe_summary: {'combined_artifact_selection_universe_size': 42, 'runtime_proxy_selection_universe_size': 21, 'true_threshold_selection_universe_size': 21, 'full_parameter_sweep_selection_universe_size': 21, 'snapshot_dsr_selection_universe_size': None, 'snapshot_dsr_selection_universe_basis': 'not_recorded', 'selected_trial_lineage_selection_universe_size': None, 'recording_status': 'split_recorded'}

## Latest Snapshot
- none

## Blockers
- snapshot rows are not being written yet
- PBO/DSR metrics are not computed yet

## Next Steps
- keep runtime proxy trial/fold lineage seeded before metric computation
- keep true threshold-sweep lineage seeded when trial families are available
- write summary snapshots into validation_pbo_dsr_snapshots
- compute PBO from selected-vs-oos rank inversions
- compute DSR from best-trial Sharpe with trial-count adjustment

## Notes
- This artifact reports schema and population readiness only.
- Runtime proxy trial/fold lineage may seed this store before a true threshold sweep exists.
