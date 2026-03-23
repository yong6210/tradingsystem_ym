# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-23T14:16:18+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: range
- transition_state: none
- zone_count: 11
- plan_count: 2
- top_plan: {'plan_id': 'plan_zone_ac4e4216fdd6_confirm', 'direction': 'short', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.488, 'expected_ev_r': 0.2558, 'expected_ev_at_recommended_size_r': 0.0609, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈48.8%, EV≈+0.26R, TP1≈57.0%, TP2≈41.6%, TP3≈26.2%', 'final_rank_score': 75.3816, 'friction_penalty': 0.1255}

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: transition_watch
- zone_count: 15
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_3887c78e291e_confirm', 'direction': 'long', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4453, 'expected_ev_r': 0.0314, 'expected_ev_at_recommended_size_r': 0.0, 'recommended_risk_r': 0.0, 'expected_summary': 'win≈44.5%, EV≈+0.03R, TP1≈53.8%, TP2≈39.0%, TP3≈24.3%', 'final_rank_score': 50.5556, 'friction_penalty': 0.3942}

## Comparison
- preferred_branch: baseline
- recommendation_reason: baseline_has_higher_sized_ev
- delta_top_expected_ev_at_size_r: -0.0609
- delta_top_expected_win_prob: -0.0427

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
