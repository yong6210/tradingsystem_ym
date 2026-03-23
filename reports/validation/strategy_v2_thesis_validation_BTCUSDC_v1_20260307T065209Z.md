# Strategy v2 Thesis Dedupe Validation: BTCUSDC

- generated_at_utc: 2026-03-07T06:52:09+00:00
- strategy_version: v1
- available: True
- reason: ok
- evaluation_scope: portfolio_global

## Executive Summary
- eligible_closed_trades: 5
- after_dedupe_trades: 3
- blocked_duplicate_trades: 1
- blocked_active_cluster_cap_trades: 1
- symbols_included: ['BTCAUSDC', 'BTCBUSDC', 'BTCCUSDC', 'ETHAUSDC', 'SOLAUSDC']
- keep_dedupe_enabled: True
- recommendation_reason: dedupe_downside_improved

## Comparison Table
- before_dedupe: trades=5, ev=-0.1200, p5=-1.2000, p50=-0.2000, max_dd=1.6000, ulcer=1.1145, avg_hold_bars=5.00, forced_exit_ratio=0.6000, information_failure_ratio=0.0000
- after_dedupe: trades=3, ev=0.5000, p5=-0.2000, p50=0.7000, max_dd=0.2000, ulcer=0.1155, avg_hold_bars=5.00, forced_exit_ratio=0.3333, information_failure_ratio=0.0000
- delta(after - before): trades=-2.0000, ev=0.6200, p5=1.0000, max_dd=-1.4000, ulcer=-0.9990

## Impact Breakdown
- impact_counts: {'primary_trade_kept': 3, 'thesis_active_cluster_cap_reached': 1, 'thesis_duplicate_blocked': 1}
- open_ts_sources: {'valid_from': 5}

## Deployment Recommendation
- keep_dedupe_enabled: True
- downside_improved: True

## Notes
- Current approximation reconstructs thesis overlap from saved closed v2 plans across the portfolio scope.
- ENTRY fill timestamps are used when available; otherwise `valid_from` is used as the open-time fallback.
- Dedupe removes later overlapping same-thesis trades and blocks new clusters once the active thesis cap is reached.
