# Strategy v2 Stressed Cost Validation: BTCUSDC

- generated_at_utc: 2026-03-08T08:09:35+00:00
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
- latency_reference_trades: 2
- shock_regime_trades: 1
- stress_pass: False
- recommendation_reason: scenario_degraded:latency_plus_1_bar
- worst_scenario: latency_plus_1_bar

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

## Additional Stress Scenarios
- latency_plus_1_bar: status=WARN, reason=negative_ev, trades=2, ev=-0.2550, p5=-1.3200, max_dd=1.3200, delta_ev=-0.3400, delta_max_dd=0.6000
- partial_fills_only: status=PASS, reason=within_limits, trades=2, ev=0.0425, p5=-0.3600, max_dd=0.3600, delta_ev=-0.0425, delta_max_dd=-0.3600
- shock_concentration: status=WARN, reason=negative_ev, trades=2, ev=-0.0950, p5=-1.0800, max_dd=1.0800, delta_ev=-0.1800, delta_max_dd=0.3600
- latency_penalty_r avg/p50/p95/max: 0.3400/0.0800/0.0800/0.6000
- partial_fill_factor avg/p50/p95/max: 0.5000/0.5000/0.5000/0.5000
- shock_factor avg/p50/p95/max: 1.2500/1.0000/1.0000/1.5000
- latency_source_counts: {'candle_open:2026-03-07T04:10:00+00:00': 1, 'fallback_slippage:execution_entry_fill': 1}

## Deployment Recommendation
- stress_pass: False
- catastrophic_loss_detected: False
- worst_scenario: latency_plus_1_bar
- stressed_drawdown_limit_r: 4.00

## Notes
- Current approximation starts from saved closed v2 realized R and deducts baseline/stressed cost in R-units.
- execution_fills is preferred for actual fee and entry slippage; missing trades fall back to plan.cost_est decomposition.
- latency +1 bar uses the next available 5m candle open and only applies directional adverse move as penalty.
- partial fills only currently assumes a fixed 50% fill ratio in R-units.
- shock concentration currently amplifies loss impact and compresses upside on trades tagged with regime=shock.
- This comparison is a stress approximation, not a full order-book replay.
