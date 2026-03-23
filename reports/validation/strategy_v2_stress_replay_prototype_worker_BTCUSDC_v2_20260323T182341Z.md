# Strategy v2 Stress Replay Prototype Worker: BTCUSDC

- generated_at_utc: 2026-03-23T18:23:41+00:00
- strategy_version: v2
- available: True
- executed: False
- runtime_job_ready: False
- reason: stress_replay_prototype_worker_not_ready
- evaluation_basis: stress replay lineage batch artifacts -> prototype replay worker output artifacts

## Sample Counts
- ready_scenarios: 0
- executed_scenarios: 0
- input_batches_read: 0
- replay_trade_rows_written: 0

## Scenario Runs
- shock_concentration: ready=False, executed=False, batches_read=0, trades=0, ev=0.0000, max_dd=0.0000
- latency_plus_1_bar: ready=False, executed=False, batches_read=0, trades=0, ev=0.0000, max_dd=0.0000
- partial_fills_only: ready=False, executed=False, batches_read=0, trades=0, ev=0.0000, max_dd=0.0000

## Blockers
- execution_fill_coverage_below_threshold
- candle_path_coverage_below_threshold
- stress_replay_worker_runtime_job_not_ready

## Next Steps
- backfill execution fill writers so entry/closed stages exist for more closed v2 trades
- add contiguous candle-path validation before marking replay lineage as ready
- close runtime lineage gaps before creating replay batches
- generate replay lineage batches before running prototype replay worker

## Notes
- This worker consumes lineage batch artifacts and writes replay output artifacts plus per-scenario markdown.
- It is a prototype execution path for contract validation, not a production-grade replay engine.
