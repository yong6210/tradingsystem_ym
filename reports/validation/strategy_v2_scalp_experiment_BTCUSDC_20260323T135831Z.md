# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-23T13:58:31+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: range
- transition_state: none
- zone_count: 10
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_df2ddceefe16_confirm', 'direction': 'short', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4799, 'expected_ev_r': 0.0802, 'expected_ev_at_recommended_size_r': 0.0191, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈48.0%, EV≈+0.08R, TP1≈56.4%, TP2≈41.1%, TP3≈25.8%', 'final_rank_score': 72.1006, 'friction_penalty': 0.1255}

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: transition_watch
- zone_count: 21
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_7a3f5eebba4f_confirm', 'direction': 'short', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4428, 'expected_ev_r': 0.1416, 'expected_ev_at_recommended_size_r': 0.0, 'recommended_risk_r': 0.0, 'expected_summary': 'win≈44.3%, EV≈+0.14R, TP1≈53.6%, TP2≈38.9%, TP3≈24.2%', 'final_rank_score': 47.8672, 'friction_penalty': 0.3942}

## Comparison
- preferred_branch: baseline
- recommendation_reason: baseline_has_higher_sized_ev
- delta_top_expected_ev_at_size_r: -0.0191
- delta_top_expected_win_prob: -0.0371

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
