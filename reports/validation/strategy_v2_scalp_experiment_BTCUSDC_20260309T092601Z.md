# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-09T09:26:01+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: range
- transition_state: none
- zone_count: 8
- plan_count: 0
- top_plan: None

## Experiment (5m zone / 1m execution)
- regime: transition
- transition_state: transition_confirmed
- zone_count: 30
- plan_count: 0
- top_plan: None

## Comparison
- preferred_branch: none
- recommendation_reason: no_ranked_plans_in_either_branch
- delta_top_expected_ev_at_size_r: +0.0000
- delta_top_expected_win_prob: +0.0000

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
