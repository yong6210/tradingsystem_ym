# Strategy v2 Transition/Shock Lock Validation: BTCUSDC

- generated_at_utc: 2026-03-09T08:35:23+00:00
- strategy_version: v2
- available: True
- reason: ok

## Executive Summary
- eligible_closed_trades: 2
- after_lock_trades: 2
- blocked_transition_trades: 0
- blocked_shock_trades: 0
- shock_clamped_trades: 0
- keep_lock_enabled: True
- recommendation_reason: no_transition_samples

## Comparison Table
- before_lock: trades=2, ev=0.4000, p5=-0.7000, p50=-0.7000, max_dd=0.7000, ulcer=0.4950, avg_hold_bars=4.50, forced_exit_ratio=0.5000, information_failure_ratio=0.0000
- after_lock: trades=2, ev=0.4000, p5=-0.7000, p50=-0.7000, max_dd=0.7000, ulcer=0.4950, avg_hold_bars=4.50, forced_exit_ratio=0.5000, information_failure_ratio=0.0000
- delta(after - before): trades=0.0000, ev=0.0000, p5=0.0000, max_dd=0.0000, ulcer=0.0000

## Impact Breakdown
- impact_counts: {'no_lock_adjustment': 2}
- after_lock impact_reasons: {'no_lock_adjustment': 2}

## Deployment Recommendation
- keep_lock_enabled: True
- downside_improved: True

## Notes
- Current approximation applies the runtime lock contract available in saved plan metadata.
- Transition lock removes trades; shock lock clamps realized R by the current shock regime factor.
