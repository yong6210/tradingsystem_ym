# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-23T06:52:12+00:00
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
- top_plan: {'plan_id': 'plan_zone_0715bca3ad7b_confirm', 'direction': 'short', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4827, 'expected_ev_r': 0.2111, 'expected_ev_at_recommended_size_r': 0.0502, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈48.3%, EV≈+0.21R, TP1≈56.6%, TP2≈41.3%, TP3≈26.0%', 'final_rank_score': 74.8843, 'friction_penalty': 0.1255}

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: transition_watch
- zone_count: 21
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_8216dceacac0_sweep_confirm', 'direction': 'short', 'entry_model': 'SWEEP_CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4603, 'expected_ev_r': 0.1848, 'expected_ev_at_recommended_size_r': 0.0, 'recommended_risk_r': 0.0, 'expected_summary': 'win≈46.0%, EV≈+0.18R, TP1≈54.9%, TP2≈39.9%, TP3≈25.0%', 'final_rank_score': 49.7155, 'friction_penalty': 0.3942}

## Comparison
- preferred_branch: baseline
- recommendation_reason: baseline_has_higher_sized_ev
- delta_top_expected_ev_at_size_r: -0.0502
- delta_top_expected_win_prob: -0.0224

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
