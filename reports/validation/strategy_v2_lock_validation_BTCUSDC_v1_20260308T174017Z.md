# Strategy v2 Transition/Shock Lock Validation: BTCUSDC

- generated_at_utc: 2026-03-08T17:40:17+00:00
- strategy_version: v1
- available: True
- reason: ok

## Executive Summary
- eligible_closed_trades: 5
- after_lock_trades: 3
- blocked_transition_trades: 1
- blocked_shock_trades: 1
- shock_clamped_trades: 1
- keep_lock_enabled: True
- recommendation_reason: lock_downside_improved

## Comparison Table
- before_lock: trades=5, ev=-0.0600, p5=-1.0000, p50=-0.3000, max_dd=2.1000, ulcer=1.3153, avg_hold_bars=4.80, forced_exit_ratio=0.6000, information_failure_ratio=0.2000
- after_lock: trades=3, ev=0.1333, p5=-0.4000, p50=-0.3000, max_dd=0.7000, ulcer=0.4655, avg_hold_bars=5.67, forced_exit_ratio=0.6667, information_failure_ratio=0.0000
- delta(after - before): trades=-2.0000, ev=0.1933, p5=0.6000, max_dd=-1.4000, ulcer=-0.8498

## Impact Breakdown
- impact_counts: {'no_lock_adjustment': 2, 'shock_requires_a_grade_rejection_block': 1, 'shock_size_clamp': 1, 'transition_zero_risk_block': 1}
- after_lock impact_reasons: {'no_lock_adjustment': 2, 'shock_size_clamp': 1}

## Deployment Recommendation
- keep_lock_enabled: True
- downside_improved: True

## Notes
- Current approximation applies the runtime lock contract available in saved plan metadata.
- Transition lock removes trades; shock lock clamps realized R by the current shock regime factor.
