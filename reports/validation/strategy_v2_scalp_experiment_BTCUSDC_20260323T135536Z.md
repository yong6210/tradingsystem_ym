# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-23T13:55:36+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: range
- transition_state: none
- zone_count: 12
- plan_count: 2
- top_plan: {'plan_id': 'plan_zone_c2cd6eba9b56_limit', 'direction': 'short', 'entry_model': 'LIMIT', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4838, 'expected_ev_r': 0.2738, 'expected_ev_at_recommended_size_r': 0.1095, 'recommended_risk_r': 0.4, 'expected_summary': 'win≈48.4%, EV≈+0.27R, TP1≈56.7%, TP2≈41.4%, TP3≈26.0%', 'final_rank_score': 76.3699, 'friction_penalty': 0.1255}

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: transition_watch
- zone_count: 21
- plan_count: 2
- top_plan: {'plan_id': 'plan_zone_b2af429e1a35_sweep_confirm', 'direction': 'long', 'entry_model': 'SWEEP_CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4612, 'expected_ev_r': 0.0167, 'expected_ev_at_recommended_size_r': 0.0, 'recommended_risk_r': 0.0, 'expected_summary': 'win≈46.1%, EV≈+0.02R, TP1≈55.0%, TP2≈40.0%, TP3≈25.0%', 'final_rank_score': 51.8812, 'friction_penalty': 0.3942}

## Comparison
- preferred_branch: baseline
- recommendation_reason: baseline_has_higher_sized_ev
- delta_top_expected_ev_at_size_r: -0.1095
- delta_top_expected_win_prob: -0.0226

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
