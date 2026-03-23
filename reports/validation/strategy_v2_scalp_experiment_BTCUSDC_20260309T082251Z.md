# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-09T08:22:51+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 267
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: range
- transition_state: none
- zone_count: 36
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_250fb94669ef_confirm', 'direction': 'long', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4861, 'expected_ev_r': 0.1706, 'expected_ev_at_recommended_size_r': 0.0406, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈48.6%, EV≈+0.17R, TP1≈56.9%, TP2≈41.5%, TP3≈26.1%', 'final_rank_score': 69.4333, 'friction_penalty': 1.9937}

## Experiment (5m zone / 1m execution)
- regime: transition
- transition_state: transition_confirmed
- zone_count: 23
- plan_count: 0
- top_plan: None

## Comparison
- preferred_branch: baseline
- recommendation_reason: baseline_only_has_ranked_plan
- delta_top_expected_ev_at_size_r: -0.0406
- delta_top_expected_win_prob: -0.4861

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
