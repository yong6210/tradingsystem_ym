# Strategy v2 Stress Replay Lineage: BTCUSDC

- generated_at_utc: 2026-03-09T08:55:55+00:00
- strategy_version: v2
- available: True
- runtime_inputs_ready: False
- reason: runtime_lineage_incomplete
- evaluation_basis: closed_v2_plans + execution_fills + 5m_candles

## Coverage
- execution_fill_coverage: 0.5000
- latency_candle_coverage: 1.0000
- candle_path_coverage: 0.5000
- estimate_only_share: 0.5000

## Fill Path
- entry_fill_coverage: 1.0000
- close_fill_coverage: 0.5000
- partial_exit_fill_coverage: 0.0000
- full_fill_path_coverage: 0.5000
- entry_anchor_sources: {'execution_entry_fill': 2}
- exit_anchor_sources: {'execution_closed_fill': 1, 'plan_final_exit_ts': 1}

## Candle Path
- entry_bar_coverage: 0.5000
- latency_bar_coverage: 1.0000
- exit_bar_coverage: 1.0000
- avg_path_coverage_ratio: 1.0000
- min_path_coverage_ratio: 1.0000

## Gap Counts
- gaps: {'missing_entry_fill': 0, 'missing_close_fill': 1, 'missing_latency_bar': 0, 'missing_exit_bar': 0, 'candle_path_below_threshold': 1}

## Contract
- lineage_contract: {'required_fill_stages': ['ENTRY', 'CLOSED'], 'optional_fill_stages': ['PARTIAL_EXIT'], 'required_plan_validity_fields': ['final_exit_ts', 'final_exit_realized_r', 'final_exit_reason'], 'candle_timeframe': '5m', 'required_candle_nodes': ['entry_bar', 'latency_plus_1_bar', 'exit_bar'], 'min_execution_fill_coverage': 0.7, 'min_latency_candle_coverage': 0.7, 'min_candle_path_coverage': 0.8}

## Blockers
- execution_fill_coverage_below_threshold
- candle_path_coverage_below_threshold

## Next Steps
- backfill execution fill writers so entry/closed stages exist for more closed v2 trades
- add contiguous candle-path validation before marking replay lineage as ready

## Notes
- This artifact defines the runtime lineage inputs required before full replay should replace the current approximation.
- It does not execute replay; it only verifies input completeness and anchor quality.
