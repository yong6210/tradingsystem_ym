# Strategy v2 Validation: BTCUSDC

- generated_at_utc: 2026-03-23T17:05:39+00:00
- strategy_version: v2
- available: True
- reason: ok

## Executive Summary
- eligible_closed_trades: 2
- A_ONLY trades: 1
- A_PLUS_B trades: 2
- incremental_B trades: 1
- preferred_live_mode: A_ONLY
- recommendation_reason: a_only_downside_better
- best_ev_family: sweep_reversal
- best_ev_regime: unknown
- best_ev_session: london

## Comparison Table
- A_ONLY: trades=1, win_rate=1.0000, ev=1.5000, p5=1.5000, p50=1.5000, max_dd=0.0000, ulcer=0.0000, avg_hold_bars=4.00, forced_exit_ratio=0.0000, information_failure_ratio=0.0000
- A_PLUS_B: trades=2, win_rate=0.5000, ev=0.4000, p5=-0.7000, p50=-0.7000, max_dd=0.7000, ulcer=0.4950, avg_hold_bars=4.50, forced_exit_ratio=0.5000, information_failure_ratio=0.0000
- delta(A_PLUS_B - A_ONLY): trades=1.0000, ev=-1.1000, p5=-2.2000, max_dd=0.7000, ulcer=0.4950, forced_exit_ratio=0.5000, information_failure_ratio=0.0000

## Exit Reason / Failure Decomposition
- A_ONLY exit_reasons: {'target_tp1': 1}
- A_PLUS_B exit_reasons: {'target_tp1': 1, 'time_failure': 1}

## Family Breakdown
- best_ev_family: {'name': 'sweep_reversal', 'ev': 1.5, 'trades': 1}
- best_win_rate_family: {'name': 'sweep_reversal', 'win_rate': 1.0, 'trades': 1}
- largest_sample_family: {'name': 'trend_continuation', 'trades': 1}
- sweep_reversal: trades=1, win_rate=1.0000, ev=1.5000, p5=1.5000, max_dd=0.0000, time_failure_ratio=0.0000
- trend_continuation: trades=1, win_rate=0.0000, ev=-0.7000, p5=-0.7000, max_dd=0.7000, time_failure_ratio=1.0000

## Regime Breakdown
- best_ev_regime: {'name': 'unknown', 'ev': 0.4, 'trades': 2}
- best_win_rate_regime: {'name': 'unknown', 'win_rate': 0.5, 'trades': 2}
- largest_sample_regime: {'name': 'unknown', 'trades': 2}
- unknown: trades=2, win_rate=0.5000, ev=0.4000, p5=-0.7000, max_dd=0.7000, time_failure_ratio=0.5000

## Session Breakdown
- best_ev_session: {'name': 'london', 'ev': 0.4, 'trades': 2}
- best_win_rate_session: {'name': 'london', 'win_rate': 0.5, 'trades': 2}
- largest_sample_session: {'name': 'london', 'trades': 2}
- london: trades=2, win_rate=0.5000, ev=0.4000, p5=-0.7000, max_dd=0.7000, time_failure_ratio=0.5000

## Deployment Recommendation
- preferred_live_mode: A_ONLY
- a_only_downside_better: True
- a_only_first_deployment_rule: True

## Notes
- This template currently covers the first frozen comparison axis: A-only vs A+B.
- Lock before/after, thesis dedupe before/after, and stressed-cost comparisons remain separate checklist items.
