# Strategy v2 Stressed Cost Validation: VALA1772867912USDC

- generated_at_utc: 2026-03-07T07:18:32+00:00
- strategy_version: v1
- available: False
- reason: no_closed_v2_trades
- comparison_axis: baseline_vs_stressed_cost
- cost_multiplier: 1.50
- slippage_multiplier: 2.00

## Executive Summary
- eligible_closed_trades: 0
- execution_data_trades: 0
- estimate_only_trades: 0
- stress_pass: True
- recommendation_reason: stress_negative_ev

## Comparison Table
- baseline_cost: trades=0, ev=0.0000, p5=0.0000, p50=0.0000, max_dd=0.0000, ulcer=0.0000, forced_exit_ratio=0.0000, information_failure_ratio=0.0000
- stressed_cost: trades=0, ev=0.0000, p5=0.0000, p50=0.0000, max_dd=0.0000, ulcer=0.0000, forced_exit_ratio=0.0000, information_failure_ratio=0.0000
- delta(stressed - baseline): ev=0.0000, p5=0.0000, max_dd=0.0000, ulcer=0.0000

## Cost Summary
- baseline_cost_r avg/p50/p95/max: 0.0000/0.0000/0.0000/0.0000
- stressed_cost_r avg/p50/p95/max: 0.0000/0.0000/0.0000/0.0000
- incremental_cost_r avg/p50/p95/max: 0.0000/0.0000/0.0000/0.0000
- fee_component_r avg/p50/p95/max: 0.0000/0.0000/0.0000/0.0000
- slippage_component_r avg/p50/p95/max: 0.0000/0.0000/0.0000/0.0000
- cost_source_counts: {}

## Deployment Recommendation
- stress_pass: True
- catastrophic_loss_detected: False
- stressed_drawdown_limit_r: 4.00

## Notes
- Current approximation starts from saved closed v2 realized R and deducts baseline/stressed cost in R-units.
- execution_fills is preferred for actual fee and entry slippage; missing trades fall back to plan.cost_est decomposition.
- This comparison is a cost-stress lens, not a full order-book replay.
