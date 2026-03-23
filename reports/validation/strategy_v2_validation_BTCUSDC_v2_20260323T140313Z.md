# Strategy v2 Validation: BTCUSDC

- generated_at_utc: 2026-03-23T14:03:13+00:00
- strategy_version: v2
- available: False
- reason: no_closed_v2_trades

## Executive Summary
- eligible_closed_trades: 0
- A_ONLY trades: 0
- A_PLUS_B trades: 0
- incremental_B trades: 0
- preferred_live_mode: A_ONLY
- recommendation_reason: insufficient_a_only_samples_default
- best_ev_family: None
- best_ev_regime: None
- best_ev_session: None

## Comparison Table
- A_ONLY: trades=0, win_rate=0.0000, ev=0.0000, p5=0.0000, p50=0.0000, max_dd=0.0000, ulcer=0.0000, avg_hold_bars=0.00, forced_exit_ratio=0.0000, information_failure_ratio=0.0000
- A_PLUS_B: trades=0, win_rate=0.0000, ev=0.0000, p5=0.0000, p50=0.0000, max_dd=0.0000, ulcer=0.0000, avg_hold_bars=0.00, forced_exit_ratio=0.0000, information_failure_ratio=0.0000
- delta(A_PLUS_B - A_ONLY): trades=0.0000, ev=0.0000, p5=0.0000, max_dd=0.0000, ulcer=0.0000, forced_exit_ratio=0.0000, information_failure_ratio=0.0000

## Exit Reason / Failure Decomposition
- A_ONLY exit_reasons: {}
- A_PLUS_B exit_reasons: {}

## Family Breakdown
- best_ev_family: {'name': None, 'ev': 0.0, 'trades': 0}
- best_win_rate_family: {'name': None, 'win_rate': 0.0, 'trades': 0}
- largest_sample_family: {'name': None, 'trades': 0}

## Regime Breakdown
- best_ev_regime: {'name': None, 'ev': 0.0, 'trades': 0}
- best_win_rate_regime: {'name': None, 'win_rate': 0.0, 'trades': 0}
- largest_sample_regime: {'name': None, 'trades': 0}

## Session Breakdown
- best_ev_session: {'name': None, 'ev': 0.0, 'trades': 0}
- best_win_rate_session: {'name': None, 'win_rate': 0.0, 'trades': 0}
- largest_sample_session: {'name': None, 'trades': 0}

## Deployment Recommendation
- preferred_live_mode: A_ONLY
- a_only_downside_better: False
- a_only_first_deployment_rule: True

## Notes
- This template currently covers the first frozen comparison axis: A-only vs A+B.
- Lock before/after, thesis dedupe before/after, and stressed-cost comparisons remain separate checklist items.
