# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-09T08:50:01+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: range
- transition_state: none
- zone_count: 6
- plan_count: 2
- top_plan: {'plan_id': 'plan_zone_625aa558cf45_confirm', 'direction': 'long', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4909, 'expected_ev_r': 0.4563, 'expected_ev_at_recommended_size_r': 0.1086, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈49.1%, EV≈+0.46R, TP1≈57.2%, TP2≈41.8%, TP3≈26.3%', 'final_rank_score': 79.1411, 'friction_penalty': 1.0855}

## Experiment (5m zone / 1m execution)
- regime: transition
- transition_state: transition_confirmed
- zone_count: 6
- plan_count: 0
- top_plan: None

## Comparison
- preferred_branch: baseline
- recommendation_reason: baseline_only_has_ranked_plan
- delta_top_expected_ev_at_size_r: -0.1086
- delta_top_expected_win_prob: -0.4909

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
