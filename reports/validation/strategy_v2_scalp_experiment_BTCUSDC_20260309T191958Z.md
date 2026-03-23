# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-09T19:19:58+00:00
- available: False
- reason: insufficient_candles

## Sample Counts
- candles_1m: 0
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: unknown
- transition_state: none
- zone_count: 0
- plan_count: 0
- top_plan: None

## Experiment (5m zone / 1m execution)
- regime: unknown
- transition_state: none
- zone_count: 0
- plan_count: 0
- top_plan: None

## Comparison
- preferred_branch: none
- recommendation_reason: not_available
- delta_top_expected_ev_at_size_r: +0.0000
- delta_top_expected_win_prob: +0.0000

## Next Steps
- sync 1m candles with /internal/binance/sync?limit_1m=...
- keep baseline 15m/5m branch as source-of-truth until experiment coverage exists
