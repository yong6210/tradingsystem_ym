# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-23T12:24:46+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: range
- transition_state: none
- zone_count: 12
- plan_count: 2
- top_plan: {'plan_id': 'plan_zone_0c1b0e69f53e_confirm', 'direction': 'short', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4789, 'expected_ev_r': 0.1662, 'expected_ev_at_recommended_size_r': 0.0396, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈47.9%, EV≈+0.17R, TP1≈56.3%, TP2≈41.1%, TP3≈25.8%', 'final_rank_score': 72.4677, 'friction_penalty': 0.1255}

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: transition_watch
- zone_count: 19
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_281e9f6b21c0_confirm', 'direction': 'short', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4631, 'expected_ev_r': 0.053, 'expected_ev_at_recommended_size_r': 0.0, 'recommended_risk_r': 0.0, 'expected_summary': 'win≈46.3%, EV≈+0.05R, TP1≈55.1%, TP2≈40.1%, TP3≈25.1%', 'final_rank_score': 60.0561, 'friction_penalty': 0.3942}

## Comparison
- preferred_branch: baseline
- recommendation_reason: baseline_has_higher_sized_ev
- delta_top_expected_ev_at_size_r: -0.0396
- delta_top_expected_win_prob: -0.0158

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
