# Strategy v2 Thesis Dedupe Validation: BTCUSDC

- generated_at_utc: 2026-03-08T18:08:44+00:00
- strategy_version: v1
- available: False
- reason: no_closed_v2_trades
- evaluation_scope: portfolio_global

## Executive Summary
- eligible_closed_trades: 0
- after_dedupe_trades: 0
- blocked_duplicate_trades: 0
- blocked_active_cluster_cap_trades: 0
- symbols_included: []
- keep_dedupe_enabled: True
- recommendation_reason: no_thesis_overlap_samples

## Comparison Table
- before_dedupe: trades=0, ev=0.0000, p5=0.0000, p50=0.0000, max_dd=0.0000, ulcer=0.0000, avg_hold_bars=0.00, forced_exit_ratio=0.0000, information_failure_ratio=0.0000
- after_dedupe: trades=0, ev=0.0000, p5=0.0000, p50=0.0000, max_dd=0.0000, ulcer=0.0000, avg_hold_bars=0.00, forced_exit_ratio=0.0000, information_failure_ratio=0.0000
- delta(after - before): trades=0.0000, ev=0.0000, p5=0.0000, max_dd=0.0000, ulcer=0.0000

## Impact Breakdown
- impact_counts: {}
- open_ts_sources: {}

## Deployment Recommendation
- keep_dedupe_enabled: True
- downside_improved: True

## Notes
- Current approximation reconstructs thesis overlap from saved closed v2 plans across the portfolio scope.
- ENTRY fill timestamps are used when available; otherwise `valid_from` is used as the open-time fallback.
- Dedupe removes later overlapping same-thesis trades and blocks new clusters once the active thesis cap is reached.
