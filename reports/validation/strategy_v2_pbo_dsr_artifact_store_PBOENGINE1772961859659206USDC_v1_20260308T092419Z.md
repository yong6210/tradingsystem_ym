# Strategy v2 PBO / DSR Artifact Store: PBOENGINE1772961859659206USDC

- generated_at_utc: 2026-03-08T09:24:19+00:00
- strategy_version: v1
- artifact_store_ready: True
- available: True
- implementation_status: artifact_store_seeded_no_snapshot
- reason: artifact_store_seeded_snapshot_missing

## Counts
- trial_runs: 9
- fold_scores: 18
- snapshots: 0
- parameter_families_present: ['lock_policy', 'mode_policy', 'stress_policy']
- selection_universe_sizes: [9]

## Latest Snapshot
- none

## Blockers
- snapshot rows are not being written yet
- PBO/DSR metrics are not computed yet

## Next Steps
- keep runtime proxy trial/fold lineage seeded before metric computation
- write summary snapshots into validation_pbo_dsr_snapshots
- compute PBO from selected-vs-oos rank inversions
- compute DSR from best-trial Sharpe with trial-count adjustment

## Notes
- This artifact reports schema and population readiness only.
- Runtime proxy trial/fold lineage may seed this store before a true threshold sweep exists.
