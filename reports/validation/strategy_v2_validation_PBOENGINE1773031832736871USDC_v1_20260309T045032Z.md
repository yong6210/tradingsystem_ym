# Strategy v2 Validation: PBOENGINE1773031832736871USDC

- generated_at_utc: 2026-03-09T04:50:32+00:00
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
- best_ev_family: trend_continuation
- best_ev_session: dead_session

## Comparison Table
- A_ONLY: trades=4, win_rate=0.7500, ev=0.5500, p5=-0.3000, p50=0.5000, max_dd=0.3000, ulcer=0.1500, avg_hold_bars=4.00, forced_exit_ratio=0.2500, information_failure_ratio=0.0000
- A_PLUS_B: trades=8, win_rate=0.5000, ev=0.1250, p5=-0.6000, p50=-0.3000, max_dd=1.5000, ulcer=0.6991, avg_hold_bars=4.00, forced_exit_ratio=0.5000, information_failure_ratio=0.0000
- delta(A_PLUS_B - A_ONLY): trades=4.0000, ev=-0.4250, p5=-0.3000, max_dd=1.2000, ulcer=0.5491, forced_exit_ratio=0.2500, information_failure_ratio=0.0000

## Exit Reason / Failure Decomposition
- A_ONLY exit_reasons: {'target_tp2': 3, 'time_failure': 1}
- A_PLUS_B exit_reasons: {'target_tp2': 4, 'time_failure': 4}

## Family Breakdown
- best_ev_family: {'name': 'trend_continuation', 'ev': 0.8, 'trades': 1}
- best_win_rate_family: {'name': 'trend_continuation', 'win_rate': 1.0, 'trades': 1}
- largest_sample_family: {'name': 'sweep_reversal', 'trades': 7}
- sweep_reversal: trades=7, win_rate=0.4286, ev=0.0286, p5=-0.6000, max_dd=1.5000, time_failure_ratio=0.5714
- trend_continuation: trades=1, win_rate=1.0000, ev=0.8000, p5=0.8000, max_dd=0.0000, time_failure_ratio=0.0000

## Session Breakdown
- best_ev_session: {'name': 'dead_session', 'ev': 0.125, 'trades': 8}
- best_win_rate_session: {'name': 'dead_session', 'win_rate': 0.5, 'trades': 8}
- largest_sample_session: {'name': 'dead_session', 'trades': 8}
- dead_session: trades=8, win_rate=0.5000, ev=0.1250, p5=-0.6000, max_dd=1.5000, time_failure_ratio=0.5000

## Deployment Recommendation
- preferred_live_mode: A_ONLY
- a_only_downside_better: True
- a_only_first_deployment_rule: True

## Notes
- This template currently covers the first frozen comparison axis: A-only vs A+B.
- Lock before/after, thesis dedupe before/after, and stressed-cost comparisons remain separate checklist items.
