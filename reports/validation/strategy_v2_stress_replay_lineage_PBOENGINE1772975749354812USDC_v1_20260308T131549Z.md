# Strategy v2 Stress Replay Lineage: PBOENGINE1772975749354812USDC

- generated_at_utc: 2026-03-08T13:15:49+00:00
- strategy_version: v1
- available: True
- runtime_inputs_ready: False
- reason: runtime_lineage_incomplete
- evaluation_basis: closed_v2_plans + execution_fills + 5m_candles

## Coverage
- execution_fill_coverage: 0.0000
- latency_candle_coverage: 0.0000
- candle_path_coverage: 0.0000
- estimate_only_share: 1.0000

## Fill Path
- entry_fill_coverage: 0.0000
- close_fill_coverage: 0.0000
- partial_exit_fill_coverage: 0.0000
- full_fill_path_coverage: 0.0000
- entry_anchor_sources: {'plan_valid_from': 8}
- exit_anchor_sources: {'plan_final_exit_ts': 8}

## Candle Path
- entry_bar_coverage: 0.0000
- latency_bar_coverage: 0.0000
- exit_bar_coverage: 0.0000
- avg_path_coverage_ratio: 0.0000
- min_path_coverage_ratio: 0.0000

## Gap Counts
- gaps: {'missing_entry_fill': 8, 'missing_close_fill': 8, 'missing_latency_bar': 8, 'missing_exit_bar': 8, 'candle_path_below_threshold': 8}

## Contract
- lineage_contract: {'required_fill_stages': ['ENTRY', 'CLOSED'], 'optional_fill_stages': ['PARTIAL_EXIT'], 'required_plan_validity_fields': ['final_exit_ts', 'final_exit_realized_r', 'final_exit_reason'], 'candle_timeframe': '5m', 'required_candle_nodes': ['entry_bar', 'latency_plus_1_bar', 'exit_bar'], 'min_execution_fill_coverage': 0.7, 'min_latency_candle_coverage': 0.7, 'min_candle_path_coverage': 0.8}

## Blockers
- execution_fill_coverage_below_threshold
- latency_candle_coverage_below_threshold
- candle_path_coverage_below_threshold

## Next Steps
- backfill execution fill writers so entry/closed stages exist for more closed v2 trades
- improve 5m candle retention around entry/exit anchors for replay candidates
- add contiguous candle-path validation before marking replay lineage as ready

## Notes
- This artifact defines the runtime lineage inputs required before full replay should replace the current approximation.
- It does not execute replay; it only verifies input completeness and anchor quality.
