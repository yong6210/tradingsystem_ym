# Strategy v2 Transition/Shock Lock Validation: BTCUSDC

- generated_at_utc: 2026-03-09T05:36:45+00:00
- strategy_version: v1
- available: False
- reason: no_closed_v2_trades

## Executive Summary
- eligible_closed_trades: 0
- after_lock_trades: 0
- blocked_transition_trades: 0
- blocked_shock_trades: 0
- shock_clamped_trades: 0
- keep_lock_enabled: True
- recommendation_reason: no_transition_samples

## Comparison Table
- before_lock: trades=0, ev=0.0000, p5=0.0000, p50=0.0000, max_dd=0.0000, ulcer=0.0000, avg_hold_bars=0.00, forced_exit_ratio=0.0000, information_failure_ratio=0.0000
- after_lock: trades=0, ev=0.0000, p5=0.0000, p50=0.0000, max_dd=0.0000, ulcer=0.0000, avg_hold_bars=0.00, forced_exit_ratio=0.0000, information_failure_ratio=0.0000
- delta(after - before): trades=0.0000, ev=0.0000, p5=0.0000, max_dd=0.0000, ulcer=0.0000

## Impact Breakdown
- impact_counts: {}
- after_lock impact_reasons: {}

## Deployment Recommendation
- keep_lock_enabled: True
- downside_improved: True

## Notes
- Current approximation applies the runtime lock contract available in saved plan metadata.
- Transition lock removes trades; shock lock clamps realized R by the current shock regime factor.
