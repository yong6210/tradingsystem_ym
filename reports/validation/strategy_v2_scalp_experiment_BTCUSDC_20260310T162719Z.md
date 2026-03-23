# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-10T16:27:19+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: range
- transition_state: none
- zone_count: 13
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_75f72527d939_confirm', 'direction': 'long', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.49, 'expected_ev_r': 0.1192, 'expected_ev_at_recommended_size_r': 0.0284, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈49.0%, EV≈+0.12R, TP1≈57.2%, TP2≈41.7%, TP3≈26.3%', 'final_rank_score': 72.8586, 'friction_penalty': 2.5596}

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: none
- zone_count: 24
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_a1dc7a9fb112_confirm', 'direction': 'long', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.5048, 'expected_ev_r': 0.1262, 'expected_ev_at_recommended_size_r': 0.03, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈50.5%, EV≈+0.13R, TP1≈58.3%, TP2≈42.6%, TP3≈27.0%', 'final_rank_score': 66.3645, 'friction_penalty': 2.4782}

## Comparison
- preferred_branch: experiment
- recommendation_reason: experiment_has_higher_win_probability
- delta_top_expected_ev_at_size_r: +0.0016
- delta_top_expected_win_prob: +0.0148

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
