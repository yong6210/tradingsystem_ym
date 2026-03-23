# Strategy v2 Transition/Shock Lock Validation: PBOENGINE1772964669324541USDC

- generated_at_utc: 2026-03-08T10:11:09+00:00
- strategy_version: v1
- available: True
- reason: ok

## Executive Summary
- eligible_closed_trades: 8
- after_lock_trades: 5
- blocked_transition_trades: 2
- blocked_shock_trades: 1
- shock_clamped_trades: 1
- keep_lock_enabled: True
- recommendation_reason: lock_downside_improved

## Comparison Table
- before_lock: trades=8, ev=0.1250, p5=-0.6000, p50=-0.3000, max_dd=1.5000, ulcer=0.6991, avg_hold_bars=4.00, forced_exit_ratio=0.5000, information_failure_ratio=0.0000
- after_lock: trades=5, ev=0.5360, p5=-0.1200, p50=0.5000, max_dd=0.1200, ulcer=0.0537, avg_hold_bars=4.00, forced_exit_ratio=0.2000, information_failure_ratio=0.0000
- delta(after - before): trades=-3.0000, ev=0.4110, p5=0.4800, max_dd=-1.3800, ulcer=-0.6454

## Impact Breakdown
- impact_counts: {'no_lock_adjustment': 4, 'shock_requires_a_grade_rejection_block': 1, 'shock_size_clamp': 1, 'transition_confirmed_block': 1, 'transition_zero_risk_block': 1}
- after_lock impact_reasons: {'no_lock_adjustment': 4, 'shock_size_clamp': 1}

## Deployment Recommendation
- keep_lock_enabled: True
- downside_improved: True

## Notes
- Current approximation applies the runtime lock contract available in saved plan metadata.
- Transition lock removes trades; shock lock clamps realized R by the current shock regime factor.
