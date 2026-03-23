# Parameter ChangeLog

- Auto-generated from strategy settings snapshots.
- Triggered by validation/report workflows.
## 2026-03-04T14:23:06+00:00 | version=v1 | trigger=validation_report
- initialized parameters snapshot (40 keys)
## 2026-03-04T14:51:25+00:00 | version=v1 | trigger=validation_report
- changed keys: 5
- `execution_quality_days`: null -> 90
- `execution_quality_max_adverse_p95_bps`: null -> 18.0
- `execution_quality_max_data_gap_ratio`: null -> 0.15
- `execution_quality_min_effective_fill_rate`: null -> 0.45
- `execution_quality_min_trades`: null -> 10
## 2026-03-04T14:54:57+00:00 | version=v1 | trigger=validation_report
- changed keys: 4
- `alert_circuit_breaker_cooldown_seconds`: null -> 90
- `alert_circuit_breaker_failures`: null -> 3
- `alert_retry_attempts`: null -> 3
- `alert_retry_backoff_seconds`: null -> 0.4
## 2026-03-04T14:55:23+00:00 | version=v1 | trigger=validation_report
- changed keys: 5
- `execution_quality_days`: 90 -> null
- `execution_quality_max_adverse_p95_bps`: 18.0 -> null
- `execution_quality_max_data_gap_ratio`: 0.15 -> null
- `execution_quality_min_effective_fill_rate`: 0.45 -> null
- `execution_quality_min_trades`: 10 -> null
## 2026-03-06T16:47:28+00:00 | version=v1 | trigger=validation_report
- changed keys: 5
- `alert_slo_max_p95_latency_ms`: null -> 3000.0
- `alert_slo_min_attempts`: null -> 5
- `alert_slo_target_success_rate`: null -> 0.995
- `alert_slo_warn_p95_latency_ms`: null -> 5000.0
- `alert_slo_warn_success_rate`: null -> 0.97
## 2026-03-06T17:07:43+00:00 | version=v1 | trigger=validation_report
- changed keys: 11
- `feature_calibration_alpha`: null -> 0.35
- `feature_calibration_apply_runtime`: null -> true
- `feature_calibration_enabled`: null -> true
- `feature_calibration_half_life_days`: null -> 21.0
- `feature_calibration_lookback_days`: null -> 120
- `feature_calibration_max_delta`: null -> 0.04
- `feature_calibration_max_zone_delta`: null -> 0.14
- `feature_calibration_min_generated_plans`: null -> 3
- `feature_calibration_min_matches`: null -> 12
- `feature_calibration_min_regime_matches`: null -> 4
- `feature_calibration_min_weight`: null -> 0.05
## 2026-03-06T17:21:19+00:00 | version=v1 | trigger=validation_report
- changed keys: 11
- `portfolio_overlay_cap_multiplier_range`: null -> 1.0
- `portfolio_overlay_cap_multiplier_shock`: null -> 0.5
- `portfolio_overlay_cap_multiplier_trend`: null -> 0.85
- `portfolio_overlay_min_risk_budget_score`: null -> 35.0
- `portfolio_overlay_penalty_exposure_scale`: null -> 12.0
- `portfolio_overlay_penalty_volatility_scale`: null -> 18.0
- `portfolio_overlay_regime_penalty_range`: null -> 0.0
- `portfolio_overlay_regime_penalty_shock`: null -> 12.0
- `portfolio_overlay_regime_penalty_trend`: null -> 4.0
- `portfolio_overlay_volatility_hard_cap`: null -> 0.018
- `portfolio_overlay_volatility_target`: null -> 0.006
## 2026-03-06T18:05:35+00:00 | version=v1 | trigger=validation_report
- changed keys: 3
- `alert_retry_queue_backoff_seconds`: null -> 30.0
- `alert_retry_queue_jitter_seconds`: null -> 0.0
- `alert_retry_queue_max_attempts`: null -> 4
## 2026-03-06T18:34:25+00:00 | version=v1 | trigger=validation_report
- changed keys: 4
- `transition_confirmed_score`: null -> 55.0
- `transition_watch_score`: null -> 40.0
- `transition_wick_body_ratio_confirmed`: null -> 2.2
- `transition_wick_body_ratio_unlock`: null -> 1.5
## 2026-03-06T18:45:10+00:00 | version=v1 | trigger=validation_report
- changed keys: 8
- `reaction_classifier_acceptance_confirmed_score`: null -> 70.0
- `reaction_classifier_acceptance_min_outside_closes`: null -> 2
- `reaction_classifier_acceptance_tentative_score`: null -> 55.0
- `reaction_classifier_max_reclaim_bars`: null -> 3
- `reaction_classifier_rejection_confirmed_score`: null -> 75.0
- `reaction_classifier_rejection_displacement_atr`: null -> 1.2
- `reaction_classifier_rejection_max_outside_closes`: null -> 1
- `reaction_classifier_rejection_tentative_score`: null -> 60.0
## 2026-03-06T18:53:48+00:00 | version=v1 | trigger=validation_report
- changed keys: 7
- `sweep_reversal_clean_limit_max_friction`: null -> 0.22
- `sweep_reversal_clean_limit_max_jump_rate`: null -> 0.12
- `sweep_reversal_clean_limit_max_width_atr`: null -> 0.45
- `sweep_reversal_grade_a_score`: null -> 85.0
- `sweep_reversal_grade_b_score`: null -> 75.0
- `sweep_reversal_grade_c_score`: null -> 68.0
- `sweep_reversal_min_score`: null -> 68.0
## 2026-03-06T19:14:45+00:00 | version=v1 | trigger=validation_report
- changed keys: 8
- `trend_continuation_grade_a_score`: null -> 85.0
- `trend_continuation_grade_b_score`: null -> 75.0
- `trend_continuation_grade_c_score`: null -> 70.0
- `trend_continuation_min_impulse_atr`: null -> 1.2
- `trend_continuation_min_score`: null -> 70.0
- `trend_continuation_protected_buffer_atr`: null -> 0.2
- `trend_continuation_pullback_max_atr`: null -> 1.6
- `trend_continuation_pullback_min_atr`: null -> 0.4
## 2026-03-06T19:21:15+00:00 | version=v1 | trigger=validation_report
- changed keys: 7
- `range_rotation_grade_a_score`: null -> 83.0
- `range_rotation_grade_b_score`: null -> 74.0
- `range_rotation_grade_c_score`: null -> 68.0
- `range_rotation_max_center_distance_atr`: null -> 0.8
- `range_rotation_max_width_atr`: null -> 1.1
- `range_rotation_min_score`: null -> 68.0
- `range_rotation_min_width_atr`: null -> 0.2
## 2026-03-07T03:57:09+00:00 | version=v1 | trigger=validation_report
- changed keys: 4
- `thesis_dedupe_enabled`: null -> true
- `thesis_duplicate_size_factor`: null -> 0.5
- `thesis_max_active_clusters`: null -> 2
- `thesis_time_bucket_minutes`: null -> 30
## 2026-03-07T04:51:15+00:00 | version=v1 | trigger=validation_report
- changed keys: 16
- `sizing_execution_factor_confirm`: null -> 0.85
- `sizing_execution_factor_limit`: null -> 1.0
- `sizing_execution_factor_sweep_confirm`: null -> 0.75
- `sizing_grade_a_r`: null -> 1.0
- `sizing_grade_b_r`: null -> 0.5
- `sizing_grade_c_r`: null -> 0.25
- `sizing_reaction_factor_confirm_only`: null -> 0.7
- `sizing_reaction_factor_confirmed`: null -> 1.0
- `sizing_reaction_factor_mixed`: null -> 0.0
- `sizing_regime_factor_range`: null -> 0.8
- `sizing_regime_factor_shock`: null -> 0.4
- `sizing_regime_factor_transition`: null -> 0.0
- `sizing_regime_factor_trend`: null -> 1.0
- `sizing_thesis_factor_none`: null -> 1.0
- `sizing_thesis_factor_one_active`: null -> 0.6
- `sizing_thesis_factor_two_or_more`: null -> 0.0
## 2026-03-07T05:05:56+00:00 | version=v1 | trigger=validation_report
- changed keys: 7
- `strategy_mode`: null -> "A_ONLY"
- `strategy_mode_a_only_max_daily_trades`: null -> 3
- `strategy_mode_a_only_max_total_risk_r`: null -> 1.5
- `strategy_mode_a_plus_b_max_daily_trades`: null -> 5
- `strategy_mode_a_plus_b_max_total_risk_r`: null -> 2.0
- `strategy_mode_research_max_daily_trades`: null -> 99
- `strategy_mode_research_max_total_risk_r`: null -> 0.0
## 2026-03-07T05:39:36+00:00 | version=v1 | trigger=validation_report
- changed keys: 9
- `operating_lock_daily_a_grade_failures`: null -> 2
- `operating_lock_daily_consecutive_losses`: null -> 3
- `operating_lock_daily_loss_limit_r`: null -> -2.0
- `operating_lock_session_consecutive_losses`: null -> 2
- `operating_lock_session_loss_limit_r`: null -> -1.5
- `trading_session_london_end_hour_utc`: null -> 12
- `trading_session_london_start_hour_utc`: null -> 7
- `trading_session_new_york_end_hour_utc`: null -> 18
- `trading_session_new_york_start_hour_utc`: null -> 13
## 2026-03-08T08:40:57+00:00 | version=v1 | trigger=validation_report
- changed keys: 2
- `session_guidance_penalty_dead_session`: null -> 6.0
- `session_guidance_penalty_session_lock`: null -> 3.0
## 2026-03-08T09:07:13+00:00 | version=v1 | trigger=validation_report
- changed keys: 3
- `stress_replay_lineage_min_candle_path_coverage`: null -> 0.8
- `stress_replay_lineage_min_execution_fill_coverage`: null -> 0.7
- `stress_replay_lineage_min_latency_candle_coverage`: null -> 0.7
## 2026-03-08T09:24:13+00:00 | version=v1 | trigger=validation_report
- changed keys: 3
- `pbo_dsr_trial_writer_enabled`: null -> true
- `pbo_dsr_trial_writer_min_trades_per_fold`: null -> 2
- `pbo_dsr_trial_writer_target_folds`: null -> 4
## 2026-03-08T09:35:37+00:00 | version=v1 | trigger=validation_report
- changed keys: 3
- `stress_replay_runner_max_parallel_jobs`: null -> 2
- `stress_replay_runner_min_trades_per_job`: null -> 8
- `stress_replay_runner_target_trades_per_job`: null -> 20
## 2026-03-08T11:31:42+00:00 | version=v1 | trigger=validation_report
- changed keys: 4
- `stress_true_replay_min_candle_path_coverage`: null -> 0.9
- `stress_true_replay_min_execution_fill_coverage`: null -> 0.85
- `stress_true_replay_min_latency_candle_coverage`: null -> 0.8
- `stress_true_replay_min_scenarios_compared`: null -> 2
## 2026-03-08T11:56:46+00:00 | version=v1 | trigger=validation_report
- changed keys: 4
- `stress_replay_divergence_fail_ev_delta`: null -> -0.25
- `stress_replay_divergence_fail_max_drawdown_delta`: null -> 0.75
- `stress_replay_divergence_warn_ev_delta`: null -> -0.1
- `stress_replay_divergence_warn_max_drawdown_delta`: null -> 0.25
## 2026-03-08T16:31:40+00:00 | version=v1 | trigger=validation_report
- changed keys: 2
- `signal_alert_cooldown_seconds`: null -> 900
- `signal_alert_near_atr_multiple`: null -> 0.35
## 2026-03-08T16:55:50+00:00 | version=v1 | trigger=validation_report
- changed keys: 2
- `binance_trade_live_enabled`: null -> false
- `binance_trade_recv_window`: null -> 5000
## 2026-03-08T18:35:39+00:00 | version=v1 | trigger=validation_report
- changed keys: 7
- `scalp_dead_session_penalty_score`: null -> 6.0
- `scalp_plan_validity_minutes`: null -> 90
- `scalp_session_boost_score`: null -> 4.0
- `scalp_session_lock_penalty_score`: null -> 3.0
- `scalp_zone_age_penalty_per_hour`: null -> 1.6
- `scalp_zone_hard_max_age_hours`: null -> 24
- `scalp_zone_recent_boost_hours`: null -> 6
## 2026-03-09T05:52:46+00:00 | version=v2 | trigger=validation_report
- changed keys: 1
- `strategy_version`: "v1" -> "v2"
