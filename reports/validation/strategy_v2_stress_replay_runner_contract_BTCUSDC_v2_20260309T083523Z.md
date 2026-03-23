# Strategy v2 Stress Replay Runner Contract: BTCUSDC

- generated_at_utc: 2026-03-09T08:35:23+00:00
- strategy_version: v2
- design_ready: True
- available: True
- runtime_job_ready: False
- implementation_status: runner_contract_defined_inputs_incomplete
- reason: stress_replay_runtime_inputs_incomplete

## Readiness
- lineage_available: True
- lineage_runtime_inputs_ready: False
- full_replay_ready: False
- replacement_recommended: False
- priority: low
- ready_scenarios: []
- blocked_scenarios: ['shock_concentration', 'latency_plus_1_bar', 'partial_fills_only']
- suggested_total_jobs: 0
- true_runner_ready: False
- true_runner_stage: prototype_only

## Dependencies
- lineage_schema_version: strategy_v2_stress_replay_lineage_v1
- assessment_schema_version: strategy_v2_stress_replay_assessment_v1
- stress_validation_schema_version: strategy_v2_stress_validation_v2

## Runner Contract
- dispatch_mode: manual_symbol_version_scenario_batch
- queue_backend: validation_report_only
- job_key_fields: ['job_id', 'symbol', 'version', 'scenario', 'batch_index', 'trade_ids', 'requested_at']
- idempotency_key_fields: ['symbol', 'version', 'scenario', 'batch_index', 'lineage_schema_version']
- target_trades_per_job: 20
- min_trades_per_job: 8
- max_parallel_jobs: 2
- suggested_jobs: {'shock_concentration': 0, 'latency_plus_1_bar': 0, 'partial_fills_only': 0}

## Scenario Contract
- shock_concentration: ready=False, status=PASS, reason=shock_sample_or_candle_path_below_contract, eligible_trade_count=0, suggested_job_count=0
- latency_plus_1_bar: ready=False, status=PASS, reason=latency_reference_coverage_below_contract, eligible_trade_count=2, suggested_job_count=0
- partial_fills_only: ready=False, status=PASS, reason=execution_fill_path_below_contract, eligible_trade_count=1, suggested_job_count=0

## Worker Input Contract
- required_sources: ['closed_v2_plans', 'execution_fills', '5m_candles', 'strategy_v2_stress_replay_lineage', 'strategy_v2_stress_replay_assessment']
- required_fields: ['plan_id', 'scenario', 'entry_anchor_ts', 'exit_anchor_ts', 'entry_anchor_source', 'exit_anchor_source', 'final_exit_realized_r', 'final_exit_reason']
- optional_fields: ['partial_exit_fill_rows', 'classification_flip_detail', 'latency_reference_bar_ts', 'shock_regime_flag']

## Worker Output Contract
- trade_level_fields: ['plan_id', 'scenario', 'replayed_entry_price', 'replayed_exit_price', 'replayed_realized_r', 'approximation_delta_r', 'coverage_flags', 'degraded_reason']
- summary_fields: ['trades', 'ev', 'p5_ev', 'max_drawdown', 'ulcer_index', 'coverage', 'approximation_gap']
- artifact_targets: ['reports/validation/stress_replay_worker_outputs/<SYMBOL>/<VERSION>/<SCENARIO>_<UTC>.json', 'reports/validation/strategy_v2_stress_replay_worker_<SYMBOL>_<VERSION>_<SCENARIO>_<UTC>.md', 'future: stress_validation.replay_output_artifacts payload']

## Blockers
- execution_fill_coverage_below_threshold
- candle_path_coverage_below_threshold

## Next Steps
- backfill execution fill writers so entry/closed stages exist for more closed v2 trades
- add contiguous candle-path validation before marking replay lineage as ready
- close runtime lineage gaps before creating replay batches

## Notes
- This artifact freezes the minimum runner/worker IO contract for full replay.
- It does not execute replay jobs yet; queueing and lineage writer integration remain follow-up work.
