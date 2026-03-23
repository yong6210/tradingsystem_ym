# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-10T16:22:56+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: transition
- transition_state: transition_confirmed
- zone_count: 13
- plan_count: 0
- top_plan: None

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: transition_watch
- zone_count: 24
- plan_count: 3
- top_plan: {'plan_id': 'plan_zone_72e1064304ff_confirm', 'direction': 'short', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4824, 'expected_ev_r': 0.0052, 'expected_ev_at_recommended_size_r': 0.0, 'recommended_risk_r': 0.0, 'expected_summary': 'win≈48.2%, EV≈+0.01R, TP1≈56.6%, TP2≈41.3%, TP3≈26.0%', 'final_rank_score': 69.559, 'friction_penalty': 0.3984}

## Comparison
- preferred_branch: experiment
- recommendation_reason: experiment_only_has_ranked_plan
- delta_top_expected_ev_at_size_r: +0.0000
- delta_top_expected_win_prob: +0.4824

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
