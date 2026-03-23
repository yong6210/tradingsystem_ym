# Strategy v2 Stressed Cost Validation: BTCUSDC

- generated_at_utc: 2026-03-23T06:26:45+00:00
- strategy_version: v2
- available: False
- reason: no_closed_v2_trades
- comparison_axis: baseline_vs_stressed_cost
- cost_multiplier: 1.50
- slippage_multiplier: 2.00

## Executive Summary
- eligible_closed_trades: 0
- execution_data_trades: 0
- estimate_only_trades: 0
- latency_reference_trades: 0
- shock_regime_trades: 0
- stress_pass: False
- recommendation_reason: scenario_degraded:latency_plus_1_bar
- worst_scenario: latency_plus_1_bar
- worst_scenario_source: approximation
- replay_gate_applied: False
- replay_gate_reason: approximation_only
- divergence_gate_applied: False
- divergence_problem_scenarios: []
- worst_divergence_scenario: None

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

## Additional Stress Scenarios
- latency_plus_1_bar: status=WARN, source=approximation, reason=negative_ev, trades=0, ev=0.0000, p5=0.0000, max_dd=0.0000, delta_ev=0.0000, delta_max_dd=0.0000
  replay_output: available=False, reason=artifact_missing, replay_ev=0.0000, replay_max_dd=0.0000, divergence_status=PASS, divergence_reason=within_divergence_threshold, delta_replay_minus_approx_ev=0.0000, delta_replay_minus_approx_max_dd=0.0000
- partial_fills_only: status=WARN, source=approximation, reason=negative_ev, trades=0, ev=0.0000, p5=0.0000, max_dd=0.0000, delta_ev=0.0000, delta_max_dd=0.0000
  replay_output: available=False, reason=artifact_missing, replay_ev=0.0000, replay_max_dd=0.0000, divergence_status=PASS, divergence_reason=within_divergence_threshold, delta_replay_minus_approx_ev=0.0000, delta_replay_minus_approx_max_dd=0.0000
- shock_concentration: status=WARN, source=approximation, reason=negative_ev, trades=0, ev=0.0000, p5=0.0000, max_dd=0.0000, delta_ev=0.0000, delta_max_dd=0.0000
  replay_output: available=False, reason=artifact_missing, replay_ev=0.0000, replay_max_dd=0.0000, divergence_status=PASS, divergence_reason=within_divergence_threshold, delta_replay_minus_approx_ev=0.0000, delta_replay_minus_approx_max_dd=0.0000
- latency_penalty_r avg/p50/p95/max: 0.0000/0.0000/0.0000/0.0000
- partial_fill_factor avg/p50/p95/max: 0.0000/0.0000/0.0000/0.0000
- shock_factor avg/p50/p95/max: 0.0000/0.0000/0.0000/0.0000
- latency_source_counts: {}

## Replay Output Artifacts
- available: False
- comparison_ready: False
- reason: no_replay_worker_output_artifacts
- summary_counts: {'scenarios_expected': 3, 'scenarios_with_artifacts': 0, 'scenarios_compared': 0, 'replay_trade_rows': 0}

## Deployment Recommendation
- stress_pass: False
- catastrophic_loss_detected: False
- worst_scenario: latency_plus_1_bar
- worst_scenario_source: approximation
- replay_gate_applied: False
- replay_gate_reason: approximation_only
- divergence_gate_applied: False
- divergence_problem_scenarios: []
- worst_divergence_scenario: None
- stressed_drawdown_limit_r: 4.00

## Notes
- Current approximation starts from saved closed v2 realized R and deducts baseline/stressed cost in R-units.
- execution_fills is preferred for actual fee and entry slippage; missing trades fall back to plan.cost_est decomposition.
- latency +1 bar uses the next available 5m candle open and only applies directional adverse move as penalty.
- partial fills only currently assumes a fixed 50% fill ratio in R-units.
- shock concentration currently amplifies loss impact and compresses upside on trades tagged with regime=shock.
- This comparison is a stress approximation, not a full order-book replay.
