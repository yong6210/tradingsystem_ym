# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-09T08:53:01+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: transition
- transition_state: transition_confirmed
- zone_count: 8
- plan_count: 0
- top_plan: None

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: none
- zone_count: 5
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_c41f1d23a569_confirm', 'direction': 'long', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4899, 'expected_ev_r': 0.4266, 'expected_ev_at_recommended_size_r': 0.1015, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈49.0%, EV≈+0.43R, TP1≈57.2%, TP2≈41.7%, TP3≈26.3%', 'final_rank_score': 72.7652, 'friction_penalty': 2.4}

## Comparison
- preferred_branch: experiment
- recommendation_reason: experiment_only_has_ranked_plan
- delta_top_expected_ev_at_size_r: +0.1015
- delta_top_expected_win_prob: +0.4899

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
