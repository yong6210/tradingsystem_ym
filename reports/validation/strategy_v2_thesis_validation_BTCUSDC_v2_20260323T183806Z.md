# Strategy v2 Thesis Dedupe Validation: BTCUSDC

- generated_at_utc: 2026-03-23T18:38:06+00:00
- strategy_version: v2
- available: True
- reason: ok
- evaluation_scope: portfolio_global

## Executive Summary
- eligible_closed_trades: 2
- after_dedupe_trades: 2
- blocked_duplicate_trades: 0
- blocked_active_cluster_cap_trades: 0
- symbols_included: ['BTCUSDC']
- keep_dedupe_enabled: True
- recommendation_reason: no_thesis_overlap_samples

## Comparison Table
- before_dedupe: trades=2, ev=0.4000, p5=-0.7000, p50=-0.7000, max_dd=0.7000, ulcer=0.4950, avg_hold_bars=4.50, forced_exit_ratio=0.5000, information_failure_ratio=0.0000
- after_dedupe: trades=2, ev=0.4000, p5=-0.7000, p50=-0.7000, max_dd=0.7000, ulcer=0.4950, avg_hold_bars=4.50, forced_exit_ratio=0.5000, information_failure_ratio=0.0000
- delta(after - before): trades=0.0000, ev=0.0000, p5=0.0000, max_dd=0.0000, ulcer=0.0000

## Impact Breakdown
- impact_counts: {'primary_trade_kept': 2}
- open_ts_sources: {'entry_fill': 2}

## Deployment Recommendation
- keep_dedupe_enabled: True
- downside_improved: True

## Notes
- Current approximation reconstructs thesis overlap from saved closed v2 plans across the portfolio scope.
- ENTRY fill timestamps are used when available; otherwise `valid_from` is used as the open-time fallback.
- Dedupe removes later overlapping same-thesis trades and blocks new clusters once the active thesis cap is reached.
