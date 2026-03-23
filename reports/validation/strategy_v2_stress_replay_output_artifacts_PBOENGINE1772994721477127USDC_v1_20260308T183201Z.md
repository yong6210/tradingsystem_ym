# Strategy v2 Stress Replay Output Artifacts: PBOENGINE1772994721477127USDC

- generated_at_utc: 2026-03-08T18:32:01+00:00
- strategy_version: v1
- available: False
- comparison_ready: False
- reason: no_replay_worker_output_artifacts

## Summary Counts
- scenarios_expected: 3
- scenarios_with_artifacts: 0
- scenarios_compared: 0
- replay_trade_rows: 0

## Lineage Summary
- lineage_summary: {'available': False, 'worker_modes': [], 'input_schema_versions': [], 'scenarios_with_lineage': [], 'compared_scenarios': [], 'input_batch_count': 0, 'input_trade_rows': 0, 'entry_anchor_sources': {}, 'exit_anchor_sources': {}, 'regime_counts': {}}

## Scenario Outputs
- shock_concentration: available=False, reason=artifact_missing, trades=0, ev=0.0000, p5=0.0000, max_dd=0.0000, delta_ev=0.0000, delta_max_dd=0.0000
- latency_plus_1_bar: available=False, reason=artifact_missing, trades=0, ev=0.0000, p5=0.0000, max_dd=0.0000, delta_ev=0.0000, delta_max_dd=0.0000
- partial_fills_only: available=False, reason=artifact_missing, trades=0, ev=0.0000, p5=0.0000, max_dd=0.0000, delta_ev=0.0000, delta_max_dd=0.0000

## Blockers
- stress_replay_worker_output_artifacts_missing

## Next Steps
- connect prototype replay worker to write scenario output artifacts

## Notes
- This payload reads worker-generated replay output artifacts if they exist.
- Missing artifacts are a normal state until the prototype replay worker is connected.
