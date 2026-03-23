# Strategy v2 Stressed Cost Validation: BTCUSDC

- generated_at_utc: 2026-03-09T09:31:01+00:00
- strategy_version: v2
- available: True
- reason: ok
- comparison_axis: baseline_vs_stressed_cost
- cost_multiplier: 1.50
- slippage_multiplier: 2.00

## Executive Summary
- eligible_closed_trades: 2
- execution_data_trades: 2
- estimate_only_trades: 0
- latency_reference_trades: 2
- shock_regime_trades: 0
- stress_pass: True
- recommendation_reason: stress_within_drawdown_limit
- worst_scenario: latency_plus_1_bar
- worst_scenario_source: approximation
- replay_gate_applied: False
- replay_gate_reason: approximation_only
- divergence_gate_applied: False
- divergence_problem_scenarios: []
- worst_divergence_scenario: None

## Comparison Table
- baseline_cost: trades=2, ev=0.3100, p5=-0.8100, p50=-0.8100, max_dd=0.8100, ulcer=0.5728, forced_exit_ratio=0.5000, information_failure_ratio=0.0000
- stressed_cost: trades=2, ev=0.2275, p5=-0.9150, p50=-0.9150, max_dd=0.9150, ulcer=0.6470, forced_exit_ratio=0.5000, information_failure_ratio=0.0000
- delta(stressed - baseline): ev=-0.0825, p5=-0.1050, max_dd=0.1050, ulcer=0.0742

## Cost Summary
- baseline_cost_r avg/p50/p95/max: 0.0900/0.0700/0.0700/0.1100
- stressed_cost_r avg/p50/p95/max: 0.1725/0.1300/0.1300/0.2150
- incremental_cost_r avg/p50/p95/max: 0.0825/0.0600/0.0600/0.1050
- fee_component_r avg/p50/p95/max: 0.0150/0.0100/0.0100/0.0200
- slippage_component_r avg/p50/p95/max: 0.0750/0.0500/0.0500/0.1000
- cost_source_counts: {'execution_fills': 2}

## Additional Stress Scenarios
- latency_plus_1_bar: status=PASS, source=approximation, reason=within_limits, trades=2, ev=0.2600, p5=-0.9100, max_dd=0.9100, delta_ev=-0.0500, delta_max_dd=0.1000
  replay_output: available=False, reason=artifact_missing, replay_ev=0.0000, replay_max_dd=0.0000, divergence_status=PASS, divergence_reason=within_divergence_threshold, delta_replay_minus_approx_ev=0.0000, delta_replay_minus_approx_max_dd=0.0000
- partial_fills_only: status=PASS, source=approximation, reason=within_limits, trades=2, ev=0.1550, p5=-0.4050, max_dd=0.4050, delta_ev=-0.1550, delta_max_dd=-0.4050
  replay_output: available=False, reason=artifact_missing, replay_ev=0.0000, replay_max_dd=0.0000, divergence_status=PASS, divergence_reason=within_divergence_threshold, delta_replay_minus_approx_ev=0.0000, delta_replay_minus_approx_max_dd=0.0000
- shock_concentration: status=PASS, source=approximation, reason=within_limits, trades=2, ev=0.3100, p5=-0.8100, max_dd=0.8100, delta_ev=0.0000, delta_max_dd=0.0000
  replay_output: available=False, reason=artifact_missing, replay_ev=0.0000, replay_max_dd=0.0000, divergence_status=PASS, divergence_reason=within_divergence_threshold, delta_replay_minus_approx_ev=0.0000, delta_replay_minus_approx_max_dd=0.0000
- latency_penalty_r avg/p50/p95/max: 0.0500/0.0000/0.0000/0.1000
- partial_fill_factor avg/p50/p95/max: 0.5000/0.5000/0.5000/0.5000
- shock_factor avg/p50/p95/max: 1.0000/1.0000/1.0000/1.0000
- latency_source_counts: {'candle_open:2026-03-08T09:40:00+00:00': 1, 'candle_open:2026-03-08T09:45:00+00:00': 1}

## Replay Output Artifacts
- available: False
- comparison_ready: False
- reason: no_replay_worker_output_artifacts
- summary_counts: {'scenarios_expected': 3, 'scenarios_with_artifacts': 0, 'scenarios_compared': 0, 'replay_trade_rows': 0}

## Deployment Recommendation
- stress_pass: True
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
