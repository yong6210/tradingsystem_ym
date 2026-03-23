# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-23T16:45:55+00:00
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
- top_plan: {'plan_id': 'plan_zone_2aadd1a7fa7e_confirm', 'direction': 'short', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4967, 'expected_ev_r': 0.0725, 'expected_ev_at_recommended_size_r': 0.0173, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈49.7%, EV≈+0.07R, TP1≈57.7%, TP2≈42.1%, TP3≈26.6%', 'final_rank_score': 76.8974, 'friction_penalty': 0.1255}

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: transition_watch
- zone_count: 18
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_a572e1a7defa_confirm', 'direction': 'short', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4422, 'expected_ev_r': 0.1396, 'expected_ev_at_recommended_size_r': 0.0, 'recommended_risk_r': 0.0, 'expected_summary': 'win≈44.2%, EV≈+0.14R, TP1≈53.6%, TP2≈38.9%, TP3≈24.1%', 'final_rank_score': 45.5357, 'friction_penalty': 0.3942}

## Comparison
- preferred_branch: baseline
- recommendation_reason: baseline_has_higher_sized_ev
- delta_top_expected_ev_at_size_r: -0.0173
- delta_top_expected_win_prob: -0.0545

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
