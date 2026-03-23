# Strategy v2 Stress Replay Lineage Writer: PBOENGINE1772979676704186USDC

- generated_at_utc: 2026-03-08T14:21:16+00:00
- strategy_version: v1
- available: True
- artifacts_written: False
- runtime_job_ready: False
- implementation_status: lineage_writer_waiting_for_runtime_job_ready
- reason: stress_replay_runtime_job_not_ready

## Sample Counts
- eligible_closed_trades: 8
- trade_rows_written: 0
- batches_written: 0
- scenarios_written: 0

## Scenario Batches
- shock_concentration: ready=False, candidate_trades=0, batches=0, gating_reason=not_available
- latency_plus_1_bar: ready=False, candidate_trades=0, batches=0, gating_reason=not_available
- partial_fills_only: ready=False, candidate_trades=0, batches=0, gating_reason=not_available

## Blockers
- execution_fill_coverage_below_threshold
- latency_candle_coverage_below_threshold
- candle_path_coverage_below_threshold

## Next Steps
- backfill execution fill writers so entry/closed stages exist for more closed v2 trades
- improve 5m candle retention around entry/exit anchors for replay candidates
- add contiguous candle-path validation before marking replay lineage as ready
- close runtime lineage gaps before creating replay batches

## Notes
- This artifact materializes per-scenario replay lineage batches for future prototype workers.
- It does not execute replay; it only writes batch inputs and readiness metadata.
