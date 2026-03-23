# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-14T14:39:52+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: range
- transition_state: none
- zone_count: 37
- plan_count: 6
- top_plan: {'plan_id': 'plan_zone_8796abf4fd1e_confirm', 'direction': 'short', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.504, 'expected_ev_r': 0.0837, 'expected_ev_at_recommended_size_r': 0.0199, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈50.4%, EV≈+0.08R, TP1≈58.2%, TP2≈42.6%, TP3≈26.9%', 'final_rank_score': 77.8412, 'friction_penalty': 0.1255}

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: transition_watch
- zone_count: 31
- plan_count: 0
- top_plan: None

## Comparison
- preferred_branch: baseline
- recommendation_reason: baseline_only_has_ranked_plan
- delta_top_expected_ev_at_size_r: -0.0199
- delta_top_expected_win_prob: -0.5040

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
