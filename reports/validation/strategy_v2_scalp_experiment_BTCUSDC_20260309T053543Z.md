# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-09T05:35:43+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: range
- transition_state: none
- zone_count: 5
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_ada3da26426e_sweep_confirm', 'direction': 'long', 'entry_model': 'SWEEP_CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.483, 'expected_ev_r': 0.4214, 'expected_ev_at_recommended_size_r': 0.1264, 'recommended_risk_r': 0.3, 'expected_summary': 'win≈48.3%, EV≈+0.42R, TP1≈56.6%, TP2≈41.3%, TP3≈26.0%', 'final_rank_score': 68.8103, 'friction_penalty': 0.6055}

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: none
- zone_count: 4
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_cd43f3f53337_confirm', 'direction': 'long', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4541, 'expected_ev_r': 0.2787, 'expected_ev_at_recommended_size_r': 0.0663, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈45.4%, EV≈+0.28R, TP1≈54.5%, TP2≈39.6%, TP3≈24.7%', 'final_rank_score': 60.868, 'friction_penalty': 2.64}

## Comparison
- preferred_branch: baseline
- recommendation_reason: baseline_has_higher_sized_ev
- delta_top_expected_ev_at_size_r: -0.0601
- delta_top_expected_win_prob: -0.0289

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
