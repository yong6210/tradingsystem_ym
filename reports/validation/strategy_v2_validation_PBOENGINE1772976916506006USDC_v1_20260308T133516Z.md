# Strategy v2 Validation: PBOENGINE1772976916506006USDC

- generated_at_utc: 2026-03-08T13:35:16+00:00
- strategy_version: v1
- available: True
- reason: ok

## Executive Summary
- eligible_closed_trades: 8
- A_ONLY trades: 4
- A_PLUS_B trades: 8
- incremental_B trades: 4
- preferred_live_mode: A_ONLY
- recommendation_reason: a_only_downside_better

## Comparison Table
- A_ONLY: trades=4, win_rate=0.7500, ev=0.5500, p5=-0.3000, p50=0.5000, max_dd=0.3000, ulcer=0.1500, avg_hold_bars=4.00, forced_exit_ratio=0.2500, information_failure_ratio=0.0000
- A_PLUS_B: trades=8, win_rate=0.5000, ev=0.1250, p5=-0.6000, p50=-0.3000, max_dd=1.5000, ulcer=0.6991, avg_hold_bars=4.00, forced_exit_ratio=0.5000, information_failure_ratio=0.0000
- delta(A_PLUS_B - A_ONLY): trades=4.0000, ev=-0.4250, p5=-0.3000, max_dd=1.2000, ulcer=0.5491, forced_exit_ratio=0.2500, information_failure_ratio=0.0000

## Exit Reason / Failure Decomposition
- A_ONLY exit_reasons: {'target_tp2': 3, 'time_failure': 1}
- A_PLUS_B exit_reasons: {'target_tp2': 4, 'time_failure': 4}

## Deployment Recommendation
- preferred_live_mode: A_ONLY
- a_only_downside_better: True
- a_only_first_deployment_rule: True

## Notes
- This template currently covers the first frozen comparison axis: A-only vs A+B.
- Lock before/after, thesis dedupe before/after, and stressed-cost comparisons remain separate checklist items.
