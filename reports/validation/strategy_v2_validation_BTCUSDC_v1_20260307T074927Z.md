# Strategy v2 Validation: BTCUSDC

- generated_at_utc: 2026-03-07T07:49:27+00:00
- strategy_version: v1
- available: True
- reason: ok

## Executive Summary
- eligible_closed_trades: 3
- A_ONLY trades: 2
- A_PLUS_B trades: 3
- incremental_B trades: 1
- preferred_live_mode: A_ONLY
- recommendation_reason: a_only_downside_better

## Comparison Table
- A_ONLY: trades=2, win_rate=0.5000, ev=0.4000, p5=-0.4000, p50=-0.4000, max_dd=0.4000, ulcer=0.2828, avg_hold_bars=5.00, forced_exit_ratio=0.5000, information_failure_ratio=0.0000
- A_PLUS_B: trades=3, win_rate=0.3333, ev=-0.1000, p5=-1.1000, p50=-0.4000, max_dd=1.5000, ulcer=0.8963, avg_hold_bars=5.00, forced_exit_ratio=0.6667, information_failure_ratio=0.3333
- delta(A_PLUS_B - A_ONLY): trades=1.0000, ev=-0.5000, p5=-0.7000, max_dd=1.1000, ulcer=0.6135, forced_exit_ratio=0.1667, information_failure_ratio=0.3333

## Exit Reason / Failure Decomposition
- A_ONLY exit_reasons: {'stop_loss': 1, 'target_tp2': 1}
- A_PLUS_B exit_reasons: {'information_failure': 1, 'stop_loss': 1, 'target_tp2': 1}

## Deployment Recommendation
- preferred_live_mode: A_ONLY
- a_only_downside_better: True
- a_only_first_deployment_rule: True

## Notes
- This template currently covers the first frozen comparison axis: A-only vs A+B.
- Lock before/after, thesis dedupe before/after, and stressed-cost comparisons remain separate checklist items.
