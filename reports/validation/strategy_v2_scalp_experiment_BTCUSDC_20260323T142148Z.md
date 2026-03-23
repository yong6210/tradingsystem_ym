# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-23T14:21:48+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: range
- transition_state: none
- zone_count: 10
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_f68e13a4e536_confirm', 'direction': 'short', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4883, 'expected_ev_r': 0.2352, 'expected_ev_at_recommended_size_r': 0.056, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈48.8%, EV≈+0.24R, TP1≈57.0%, TP2≈41.6%, TP3≈26.2%', 'final_rank_score': 74.6224, 'friction_penalty': 0.1255}

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: transition_watch
- zone_count: 16
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_43a18fcdd553_sweep_confirm', 'direction': 'short', 'entry_model': 'SWEEP_CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4597, 'expected_ev_r': 0.1106, 'expected_ev_at_recommended_size_r': 0.0, 'recommended_risk_r': 0.0, 'expected_summary': 'win≈46.0%, EV≈+0.11R, TP1≈54.9%, TP2≈39.9%, TP3≈24.9%', 'final_rank_score': 50.2321, 'friction_penalty': 0.3942}

## Comparison
- preferred_branch: baseline
- recommendation_reason: baseline_has_higher_sized_ev
- delta_top_expected_ev_at_size_r: -0.0560
- delta_top_expected_win_prob: -0.0286

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
