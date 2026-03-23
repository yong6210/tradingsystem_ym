# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-23T12:12:09+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: range
- transition_state: none
- zone_count: 9
- plan_count: 2
- top_plan: {'plan_id': 'plan_zone_dccba3d561dd_limit', 'direction': 'short', 'entry_model': 'LIMIT', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4832, 'expected_ev_r': 0.0789, 'expected_ev_at_recommended_size_r': 0.0316, 'recommended_risk_r': 0.4, 'expected_summary': 'win≈48.3%, EV≈+0.08R, TP1≈56.7%, TP2≈41.3%, TP3≈26.0%', 'final_rank_score': 76.9054, 'friction_penalty': 0.1255}

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: transition_watch
- zone_count: 19
- plan_count: 0
- top_plan: None

## Comparison
- preferred_branch: baseline
- recommendation_reason: baseline_only_has_ranked_plan
- delta_top_expected_ev_at_size_r: -0.0316
- delta_top_expected_win_prob: -0.4832

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
