# Strategy v2 Stressed Cost Validation: PBOENGINE1772983696202097USDC

- generated_at_utc: 2026-03-08T15:28:16+00:00
- strategy_version: v1
- available: True
- reason: ok
- comparison_axis: baseline_vs_stressed_cost
- cost_multiplier: 1.50
- slippage_multiplier: 2.00

## Executive Summary
- eligible_closed_trades: 8
- execution_data_trades: 0
- estimate_only_trades: 8
- latency_reference_trades: 8
- shock_regime_trades: 2
- stress_pass: False
- recommendation_reason: scenario_degraded:shock_concentration
- worst_scenario: shock_concentration
- worst_scenario_source: approximation
- replay_gate_applied: False
- replay_gate_reason: approximation_only
- divergence_gate_applied: False
- divergence_problem_scenarios: []
- worst_divergence_scenario: None

## Comparison Table
- baseline_cost: trades=8, ev=0.0250, p5=-0.7000, p50=-0.4000, max_dd=1.8000, ulcer=0.8352, forced_exit_ratio=0.5000, information_failure_ratio=0.0000
- stressed_cost: trades=8, ev=-0.0350, p5=-0.7600, p50=-0.4600, max_dd=1.9800, ulcer=0.9179, forced_exit_ratio=0.5000, information_failure_ratio=0.0000
- delta(stressed - baseline): ev=-0.0600, p5=-0.0600, max_dd=0.1800, ulcer=0.0827

## Cost Summary
- baseline_cost_r avg/p50/p95/max: 0.1000/0.1000/0.1000/0.1000
- stressed_cost_r avg/p50/p95/max: 0.1600/0.1600/0.1600/0.1600
- incremental_cost_r avg/p50/p95/max: 0.0600/0.0600/0.0600/0.0600
- fee_component_r avg/p50/p95/max: 0.0800/0.0800/0.0800/0.0800
- slippage_component_r avg/p50/p95/max: 0.0200/0.0200/0.0200/0.0200
- cost_source_counts: {'plan_cost_est': 8}

## Additional Stress Scenarios
- latency_plus_1_bar: status=PASS, source=approximation, reason=within_limits, trades=8, ev=0.0050, p5=-0.7200, max_dd=1.8600, delta_ev=-0.0200, delta_max_dd=0.0600
  replay_output: available=False, reason=artifact_missing, replay_ev=0.0000, replay_max_dd=0.0000, divergence_status=PASS, divergence_reason=within_divergence_threshold, delta_replay_minus_approx_ev=0.0000, delta_replay_minus_approx_max_dd=0.0000
- partial_fills_only: status=PASS, source=approximation, reason=within_limits, trades=8, ev=0.0125, p5=-0.3500, max_dd=0.9000, delta_ev=-0.0125, delta_max_dd=-0.9000
  replay_output: available=False, reason=artifact_missing, replay_ev=0.0000, replay_max_dd=0.0000, divergence_status=PASS, divergence_reason=within_divergence_threshold, delta_replay_minus_approx_ev=0.0000, delta_replay_minus_approx_max_dd=0.0000
- shock_concentration: status=WARN, source=approximation, reason=negative_ev, trades=8, ev=-0.0437, p5=-1.0500, max_dd=2.1500, delta_ev=-0.0687, delta_max_dd=0.3500
  replay_output: available=False, reason=artifact_missing, replay_ev=0.0000, replay_max_dd=0.0000, divergence_status=PASS, divergence_reason=within_divergence_threshold, delta_replay_minus_approx_ev=0.0000, delta_replay_minus_approx_max_dd=0.0000
- latency_penalty_r avg/p50/p95/max: 0.0200/0.0200/0.0200/0.0200
- partial_fill_factor avg/p50/p95/max: 0.5000/0.5000/0.5000/0.5000
- shock_factor avg/p50/p95/max: 1.1250/1.0000/1.5000/1.5000
- latency_source_counts: {'fallback_slippage:plan_valid_from': 8}

## Replay Output Artifacts
- available: False
- comparison_ready: False
- reason: no_replay_worker_output_artifacts
- summary_counts: {'scenarios_expected': 3, 'scenarios_with_artifacts': 0, 'scenarios_compared': 0, 'replay_trade_rows': 0}

## Deployment Recommendation
- stress_pass: False
- catastrophic_loss_detected: False
- worst_scenario: shock_concentration
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
