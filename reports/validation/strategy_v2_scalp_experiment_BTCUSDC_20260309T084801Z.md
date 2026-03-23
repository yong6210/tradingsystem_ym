# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-09T08:48:01+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: range
- transition_state: none
- zone_count: 4
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_5574e93b1b62_confirm', 'direction': 'short', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4891, 'expected_ev_r': 0.4482, 'expected_ev_at_recommended_size_r': 0.1067, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈48.9%, EV≈+0.45R, TP1≈57.1%, TP2≈41.7%, TP3≈26.3%', 'final_rank_score': 79.118, 'friction_penalty': 1.0855}

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: none
- zone_count: 6
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_850ee41694c5_confirm', 'direction': 'long', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.5049, 'expected_ev_r': 0.3613, 'expected_ev_at_recommended_size_r': 0.086, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈50.5%, EV≈+0.36R, TP1≈58.3%, TP2≈42.6%, TP3≈27.0%', 'final_rank_score': 82.6123, 'friction_penalty': 2.4}

## Comparison
- preferred_branch: baseline
- recommendation_reason: baseline_has_higher_sized_ev
- delta_top_expected_ev_at_size_r: -0.0207
- delta_top_expected_win_prob: +0.0158

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
