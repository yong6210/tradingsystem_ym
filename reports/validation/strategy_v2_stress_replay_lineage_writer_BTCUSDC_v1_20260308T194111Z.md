# Strategy v2 Stress Replay Lineage Writer: BTCUSDC

- generated_at_utc: 2026-03-08T19:41:11+00:00
- strategy_version: v1
- available: False
- artifacts_written: False
- runtime_job_ready: False
- implementation_status: lineage_writer_waiting_for_dependencies
- reason: stress_replay_lineage_or_runner_contract_unavailable

## Sample Counts
- eligible_closed_trades: 0
- trade_rows_written: 0
- batches_written: 0
- scenarios_written: 0

## Scenario Batches
- shock_concentration: ready=False, candidate_trades=0, batches=0, gating_reason=not_available
- latency_plus_1_bar: ready=False, candidate_trades=0, batches=0, gating_reason=not_available
- partial_fills_only: ready=False, candidate_trades=0, batches=0, gating_reason=not_available

## Blockers
- no_closed_v2_trades
- stress_replay_lineage_unavailable

## Next Steps
- accumulate closed v2 trades before evaluating replay lineage
- compute stress replay lineage before defining runner inputs

## Notes
- This artifact materializes per-scenario replay lineage batches for future prototype workers.
- It does not execute replay; it only writes batch inputs and readiness metadata.
