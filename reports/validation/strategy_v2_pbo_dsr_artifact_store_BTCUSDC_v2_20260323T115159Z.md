# Strategy v2 PBO / DSR Artifact Store: BTCUSDC

- generated_at_utc: 2026-03-23T11:51:59+00:00
- strategy_version: v2
- artifact_store_ready: True
- available: False
- implementation_status: artifact_store_schema_ready_empty
- reason: artifact_store_tables_ready_not_populated

## Counts
- trial_runs: 0
- fold_scores: 0
- snapshots: 0
- parameter_families_present: []
- selection_rule_counts: {}
- selection_universe_sizes: []
- selection_universe_summary: {'combined_artifact_selection_universe_size': 0, 'runtime_proxy_selection_universe_size': 0, 'true_threshold_selection_universe_size': 0, 'full_parameter_sweep_selection_universe_size': None, 'snapshot_dsr_selection_universe_size': None, 'snapshot_dsr_selection_universe_basis': 'not_recorded', 'selected_trial_lineage_selection_universe_size': None, 'recording_status': 'combined_only'}

## Latest Snapshot
- none

## Blockers
- runtime proxy trial writer has not seeded validation_trial_runs yet
- fold-level CSCV scores have not been written yet
- PBO/DSR metrics are not computed yet

## Next Steps
- run validation/report after enough eligible closed v2 trades
- keep runtime proxy trial writer enabled until a separated true threshold runner can seed trials
- persist CSCV fold scores into validation_trial_fold_scores
- write summary snapshots into validation_pbo_dsr_snapshots

## Notes
- This artifact reports schema and population readiness only.
- Runtime proxy trial/fold lineage may seed this store before a true threshold sweep exists.
