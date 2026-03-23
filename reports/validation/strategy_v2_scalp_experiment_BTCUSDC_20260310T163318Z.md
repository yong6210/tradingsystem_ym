# Strategy v2 Scalp Experiment: BTCUSDC

- generated_at_utc: 2026-03-10T16:33:18+00:00
- available: True
- reason: ok

## Sample Counts
- candles_1m: 900
- candles_5m: 300
- candles_15m: 300

## Baseline (15m zone / 5m execution)
- regime: range
- transition_state: none
- zone_count: 13
- plan_count: 1
- top_plan: {'plan_id': 'plan_zone_bdf4c84a7b54_confirm', 'direction': 'short', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.4831, 'expected_ev_r': 0.2394, 'expected_ev_at_recommended_size_r': 0.057, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈48.3%, EV≈+0.24R, TP1≈56.6%, TP2≈41.3%, TP3≈26.0%', 'final_rank_score': 72.0396, 'friction_penalty': 2.8365}

## Experiment (5m zone / 1m execution)
- regime: range
- transition_state: none
- zone_count: 24
- plan_count: 2
- top_plan: {'plan_id': 'plan_zone_d6a7c44a0c39_confirm', 'direction': 'long', 'entry_model': 'CONFIRM', 'strategy_family': 'legacy_zone_plan', 'strategy_grade': None, 'expected_win_prob': 0.5068, 'expected_ev_r': 0.1404, 'expected_ev_at_recommended_size_r': 0.0334, 'recommended_risk_r': 0.238, 'expected_summary': 'win≈50.7%, EV≈+0.14R, TP1≈58.4%, TP2≈42.7%, TP3≈27.1%', 'final_rank_score': 77.2389, 'friction_penalty': 1.7856}

## Comparison
- preferred_branch: baseline
- recommendation_reason: baseline_has_higher_sized_ev
- delta_top_expected_ev_at_size_r: -0.0236
- delta_top_expected_win_prob: +0.0237

## Next Steps
- sync 1m candles before trusting the experiment branch live
- treat the 5m/1m branch as compare-only until execution-quality samples exist
- promote experiment only if top expected EV at recommended size stays better across multiple sessions
