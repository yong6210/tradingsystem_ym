# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-22T21:55:22+00:00
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
- plan_count: 2
- top_plan: {'plan_id': 'plan_zone_04729c039c0a_confirm', 'direction': 'short', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4801, 'expected_ev_r': 0.2138, 'expected_ev_at_recommended_size_r': 0.0509, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈48.0%, EV≈+0.21R, TP1≈56.4%, TP2≈41.1%, TP3≈25.9%', 'final_rank_score': 73.9963, 'friction_penalty': 0.1255}

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: transition_watch
- zone_count: 19
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_76a03e7a0679_confirm', 'direction': 'short', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4573, 'expected_ev_r': 0.0279, 'expected_ev_at_recommended_size_r': 0.0, 'recommended_risk_r': 0.0, 'expected_summary': 'win≈45.7%, EV≈+0.03R, TP1≈54.7%, TP2≈39.8%, TP3≈24.8%', 'final_rank_score': 52.7677, 'friction_penalty': 0.3942}

## Comparison
- preferred_branch: baseline
- recommendation_reason: baseline_has_higher_sized_ev
- delta_top_expected_ev_at_size_r: -0.0509
- delta_top_expected_win_prob: -0.0228

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
