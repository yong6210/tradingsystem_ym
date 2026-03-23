# Strategy v2 Thesis Dedupe Validation: PBOENGINE1772988950529764USDC

- generated_at_utc: 2026-03-08T16:55:50+00:00
- strategy_version: v1
- available: True
- reason: ok
- evaluation_scope: portfolio_global

## Executive Summary
- eligible_closed_trades: 25
- after_dedupe_trades: 9
- blocked_duplicate_trades: 16
- blocked_active_cluster_cap_trades: 0
- symbols_included: ['PBOENGINE1772988950529764USDC', 'PBOSEED1772988950513838USDC', 'PBOTHR1772988950482921USDC', 'SIGFILL1772988950382275USDC']
- keep_dedupe_enabled: True
- recommendation_reason: dedupe_downside_improved

## Comparison Table
- before_dedupe: trades=25, ev=0.1532, p5=-0.6000, p50=0.3000, max_dd=4.5000, ulcer=1.9463, avg_hold_bars=4.00, forced_exit_ratio=0.4800, information_failure_ratio=0.0000
- after_dedupe: trades=9, ev=0.2033, p5=-0.6000, p50=0.3000, max_dd=1.5000, ulcer=0.6959, avg_hold_bars=4.00, forced_exit_ratio=0.4444, information_failure_ratio=0.0000
- delta(after - before): trades=-16.0000, ev=0.0501, p5=0.0000, max_dd=-3.0000, ulcer=-1.2504

## Impact Breakdown
- impact_counts: {'primary_trade_kept': 9, 'thesis_duplicate_blocked': 16}
- open_ts_sources: {'entry_fill': 1, 'valid_from': 24}

## Deployment Recommendation
- keep_dedupe_enabled: True
- downside_improved: True

## Notes
- Current approximation reconstructs thesis overlap from saved closed v2 plans across the portfolio scope.
- ENTRY fill timestamps are used when available; otherwise `valid_from` is used as the open-time fallback.
- Dedupe removes later overlapping same-thesis trades and blocks new clusters once the active thesis cap is reached.
