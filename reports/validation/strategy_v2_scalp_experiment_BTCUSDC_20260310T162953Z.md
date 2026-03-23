# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-10T16:29:53+00:00
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
- plan_count: 2
- top_plan: {'plan_id': 'plan_zone_3229ebb6a366_confirm', 'direction': 'short', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4984, 'expected_ev_r': 0.3044, 'expected_ev_at_recommended_size_r': 0.0724, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈49.8%, EV≈+0.30R, TP1≈57.8%, TP2≈42.2%, TP3≈26.7%', 'final_rank_score': 74.6786, 'friction_penalty': 1.0864}

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: transition_watch
- zone_count: 24
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_0748f87de050_confirm', 'direction': 'long', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.472, 'expected_ev_r': 0.1044, 'expected_ev_at_recommended_size_r': 0.0, 'recommended_risk_r': 0.0, 'expected_summary': 'win≈47.2%, EV≈+0.10R, TP1≈55.8%, TP2≈40.6%, TP3≈25.5%', 'final_rank_score': 60.2799, 'friction_penalty': 1.1091}

## Comparison
- preferred_branch: baseline
- recommendation_reason: baseline_has_higher_sized_ev
- delta_top_expected_ev_at_size_r: -0.0724
- delta_top_expected_win_prob: -0.0264

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
