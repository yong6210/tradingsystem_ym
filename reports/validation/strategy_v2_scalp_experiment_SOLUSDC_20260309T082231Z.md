# Strategy v2 Scalp Experiment: SOLUSDC

- generated_at_utc: 2026-03-09T08:22:31+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: range
- transition_state: transition_watch
- zone_count: 38
- plan_count: 4
- top_plan: {'plan_id': 'plan_zone_a9ac663398e9_confirm', 'direction': 'short', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4767, 'expected_ev_r': 0.1627, 'expected_ev_at_recommended_size_r': 0.0, 'recommended_risk_r': 0.0, 'expected_summary': 'win≈47.7%, EV≈+0.16R, TP1≈56.2%, TP2≈40.9%, TP3≈25.7%', 'final_rank_score': 75.9232, 'friction_penalty': 1.4025}

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: transition_watch
- zone_count: 36
- plan_count: 0
- top_plan: None

## Comparison
- preferred_branch: baseline
- recommendation_reason: baseline_only_has_ranked_plan
- delta_top_expected_ev_at_size_r: +0.0000
- delta_top_expected_win_prob: -0.4767

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
