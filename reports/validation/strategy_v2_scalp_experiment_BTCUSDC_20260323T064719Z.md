# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-23T06:47:19+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: range
- transition_state: none
- zone_count: 9
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_4d630143ba9e_confirm', 'direction': 'short', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4796, 'expected_ev_r': 0.2033, 'expected_ev_at_recommended_size_r': 0.0484, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈48.0%, EV≈+0.20R, TP1≈56.4%, TP2≈41.1%, TP3≈25.8%', 'final_rank_score': 73.7777, 'friction_penalty': 0.1255}

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: transition_watch
- zone_count: 20
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_11109508abf0_confirm', 'direction': 'short', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4468, 'expected_ev_r': 0.088, 'expected_ev_at_recommended_size_r': 0.0, 'recommended_risk_r': 0.0, 'expected_summary': 'win≈44.7%, EV≈+0.09R, TP1≈53.9%, TP2≈39.1%, TP3≈24.4%', 'final_rank_score': 55.0077, 'friction_penalty': 0.3942}

## Comparison
- preferred_branch: baseline
- recommendation_reason: baseline_has_higher_sized_ev
- delta_top_expected_ev_at_size_r: -0.0484
- delta_top_expected_win_prob: -0.0328

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
