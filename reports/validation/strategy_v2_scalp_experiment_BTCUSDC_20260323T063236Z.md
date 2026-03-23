# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-23T06:32:36+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: range
- transition_state: transition_watch
- zone_count: 12
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_0d11e03ab8eb_sweep_confirm', 'direction': 'long', 'entry_model': 'SWEEP_CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4614, 'expected_ev_r': 0.157, 'expected_ev_at_recommended_size_r': 0.0, 'recommended_risk_r': 0.0, 'expected_summary': 'win≈46.1%, EV≈+0.16R, TP1≈55.0%, TP2≈40.0%, TP3≈25.0%', 'final_rank_score': 57.8081, 'friction_penalty': 0.1255}

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: transition_watch
- zone_count: 16
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_ac7b105e5a1d_sweep_confirm', 'direction': 'short', 'entry_model': 'SWEEP_CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4627, 'expected_ev_r': 0.1434, 'expected_ev_at_recommended_size_r': 0.0, 'recommended_risk_r': 0.0, 'expected_summary': 'win≈46.3%, EV≈+0.14R, TP1≈55.1%, TP2≈40.1%, TP3≈25.1%', 'final_rank_score': 54.4813, 'friction_penalty': 0.3942}

## Comparison
- preferred_branch: baseline
- recommendation_reason: baseline_default_tie_break
- delta_top_expected_ev_at_size_r: +0.0000
- delta_top_expected_win_prob: +0.0013

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
