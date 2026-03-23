# Strategy v2 Stressed Cost Validation: BTCUSDC

- generated_at_utc: 2026-03-07T07:00:20+00:00
- strategy_version: v1
- available: True
- reason: ok
- comparison_axis: baseline_vs_stressed_cost
- cost_multiplier: 1.50
- slippage_multiplier: 2.00

## Executive Summary
- eligible_closed_trades: 2
- execution_data_trades: 1
- estimate_only_trades: 1
- stress_pass: True
- recommendation_reason: stress_negative_ev

## Comparison Table
- baseline_cost: trades=2, ev=0.0850, p5=-0.7200, p50=-0.7200, max_dd=0.7200, ulcer=0.5091, forced_exit_ratio=0.5000, information_failure_ratio=0.0000
- stressed_cost: trades=2, ev=-0.0125, p5=-0.8200, p50=-0.8200, max_dd=0.8200, ulcer=0.5798, forced_exit_ratio=0.5000, information_failure_ratio=0.0000
- delta(stressed - baseline): ev=-0.0975, p5=-0.1000, max_dd=0.1000, ulcer=0.0707

## Cost Summary
- baseline_cost_r avg/p50/p95/max: 0.1150/0.1100/0.1100/0.1200
- stressed_cost_r avg/p50/p95/max: 0.2125/0.2050/0.2050/0.2200
- incremental_cost_r avg/p50/p95/max: 0.0975/0.0950/0.0950/0.1000
- fee_component_r avg/p50/p95/max: 0.0350/0.0300/0.0300/0.0400
- slippage_component_r avg/p50/p95/max: 0.0800/0.0800/0.0800/0.0800
- cost_source_counts: {'execution_fills': 1, 'plan_cost_est': 1}

## Deployment Recommendation
- stress_pass: True
- catastrophic_loss_detected: False
- stressed_drawdown_limit_r: 4.00

## Notes
- Current approximation starts from saved closed v2 realized R and deducts baseline/stressed cost in R-units.
- execution_fills is preferred for actual fee and entry slippage; missing trades fall back to plan.cost_est decomposition.
- This comparison is a cost-stress lens, not a full order-book replay.
