# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-23T14:01:01+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: transition
- transition_state: transition_confirmed
- zone_count: 10
- plan_count: 0
- top_plan: None

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: transition_watch
- zone_count: 20
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_5f6d0444437e_sweep_confirm', 'direction': 'long', 'entry_model': 'SWEEP_CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4612, 'expected_ev_r': 0.0271, 'expected_ev_at_recommended_size_r': 0.0, 'recommended_risk_r': 0.0, 'expected_summary': 'win≈46.1%, EV≈+0.03R, TP1≈55.0%, TP2≈40.0%, TP3≈25.0%', 'final_rank_score': 51.8674, 'friction_penalty': 0.3942}

## Comparison
- preferred_branch: experiment
- recommendation_reason: experiment_only_has_ranked_plan
- delta_top_expected_ev_at_size_r: +0.0000
- delta_top_expected_win_prob: +0.4612

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
