# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-23T16:45:58+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 200
- candles_5m: 150
- candles_15m: 80

## Baseline (15m zone / 5m execution)
- regime: trend
- transition_state: none
- zone_count: 1
- plan_count: 1
- top_plan: {'plan_id': 'baseline_plan', 'direction': 'long', 'entry_model': 'CONFIRM', 'strategy_family': 'trend_continuation', 'strategy_grade': 'A', 'expected_win_prob': 0.0, 'expected_ev_r': 0.18, 'expected_ev_at_recommended_size_r': 0.045, 'recommended_risk_r': 0.25, 'expected_summary': 'win≈0.0%, EV≈+0.18R, TP1≈0.0%, TP2≈0.0%, TP3≈0.0%', 'final_rank_score': 83.5, 'friction_penalty': 2.0}

## Experiment (5m zone / 1m execution)
- regime: trend
- transition_state: none
- zone_count: 1
- plan_count: 1
- top_plan: {'plan_id': 'experiment_plan', 'direction': 'long', 'entry_model': 'CONFIRM', 'strategy_family': 'trend_continuation', 'strategy_grade': 'A', 'expected_win_prob': 0.0, 'expected_ev_r': 0.34, 'expected_ev_at_recommended_size_r': 0.136, 'recommended_risk_r': 0.4, 'expected_summary': 'win≈0.0%, EV≈+0.34R, TP1≈0.0%, TP2≈0.0%, TP3≈0.0%', 'final_rank_score': 83.5, 'friction_penalty': 2.0}

## Comparison
- preferred_branch: experiment
- recommendation_reason: experiment_has_higher_sized_ev
- delta_top_expected_ev_at_size_r: +0.0910
- delta_top_expected_win_prob: +0.0000

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
