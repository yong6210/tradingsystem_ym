# Strategy v2 Thesis Dedupe Validation: BTCUSDC

- generated_at_utc: 2026-03-08T11:00:03+00:00
- strategy_version: v1
- available: True
- reason: ok
- evaluation_scope: portfolio_global

## Executive Summary
- eligible_closed_trades: 24
- after_dedupe_trades: 8
- blocked_duplicate_trades: 16
- blocked_active_cluster_cap_trades: 0
- symbols_included: ['PBOENGINE1772967602446648USDC', 'PBOSEED1772967602290589USDC', 'PBOTHR1772967602684545USDC']
- keep_dedupe_enabled: True
- recommendation_reason: dedupe_downside_improved

## Comparison Table
- before_dedupe: trades=24, ev=0.1250, p5=-0.6000, p50=-0.3000, max_dd=4.5000, ulcer=1.8397, avg_hold_bars=4.00, forced_exit_ratio=0.5000, information_failure_ratio=0.0000
- after_dedupe: trades=8, ev=0.1250, p5=-0.6000, p50=-0.3000, max_dd=1.5000, ulcer=0.6991, avg_hold_bars=4.00, forced_exit_ratio=0.5000, information_failure_ratio=0.0000
- delta(after - before): trades=-16.0000, ev=0.0000, p5=0.0000, max_dd=-3.0000, ulcer=-1.1406

## Impact Breakdown
- impact_counts: {'primary_trade_kept': 8, 'thesis_duplicate_blocked': 16}
- open_ts_sources: {'valid_from': 24}

## Deployment Recommendation
- keep_dedupe_enabled: True
- downside_improved: True

## Notes
- Current approximation reconstructs thesis overlap from saved closed v2 plans across the portfolio scope.
- ENTRY fill timestamps are used when available; otherwise `valid_from` is used as the open-time fallback.
- Dedupe removes later overlapping same-thesis trades and blocks new clusters once the active thesis cap is reached.
