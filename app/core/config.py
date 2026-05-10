import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote

os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "1")

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import StrategyMode

ROOT_DIR = Path(__file__).resolve().parents[2]
SQLITE_URL_PREFIXES = ("sqlite+pysqlite:///", "sqlite:///")


def sqlite_database_path_from_url(database_url: str) -> Path | None:
    raw = str(database_url or "").strip()
    for prefix in SQLITE_URL_PREFIXES:
        if not raw.startswith(prefix):
            continue
        path_part = unquote(raw[len(prefix) :].split("?", 1)[0])
        if path_part in {"", ":memory:"}:
            return None
        path = Path(path_part).expanduser()
        return path if path.is_absolute() else (ROOT_DIR / path).resolve()
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT_DIR / ".env"), env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Trading Engine v1"
    api_prefix: str = ""
    database_url: str = "sqlite:///./trading.db"
    strategy_version: str = "v1"
    environment: str = "dev"

    atr_period: int = 14
    zone_pivot_len: int = 3
    zone_max_age_days: int = 45
    scalp_zone_hard_max_age_hours: int = 24
    scalp_zone_recent_boost_hours: int = 6
    scalp_zone_age_penalty_per_hour: float = 1.6
    scalp_plan_validity_minutes: int = 90
    scalp_session_boost_score: float = 4.0
    scalp_dead_session_penalty_score: float = 6.0
    scalp_session_lock_penalty_score: float = 3.0

    friction_threshold: float = 0.5
    jump_threshold: float = 1.7
    min_rr: float = 1.2
    max_consecutive_losses: int = 3
    jump_rate_gate: float = 0.35
    strong_regime_gate: float = 0.72
    friction_hard_gate: float = 0.72
    jump_hard_gate: float = 0.32
    transition_confirmed_score: float = 55.0
    transition_watch_score: float = 40.0
    transition_wick_body_ratio_confirmed: float = 2.2
    transition_wick_body_ratio_unlock: float = 1.5
    reaction_classifier_max_reclaim_bars: int = 3
    reaction_classifier_rejection_displacement_atr: float = 1.2
    reaction_classifier_rejection_max_outside_closes: int = 1
    reaction_classifier_acceptance_min_outside_closes: int = 2
    reaction_classifier_rejection_confirmed_score: float = 75.0
    reaction_classifier_rejection_tentative_score: float = 60.0
    reaction_classifier_acceptance_confirmed_score: float = 70.0
    reaction_classifier_acceptance_tentative_score: float = 55.0
    sweep_reversal_min_score: float = 68.0
    sweep_reversal_grade_a_score: float = 85.0
    sweep_reversal_grade_b_score: float = 75.0
    sweep_reversal_grade_c_score: float = 68.0
    sweep_reversal_clean_limit_max_width_atr: float = 0.45
    sweep_reversal_clean_limit_max_friction: float = 0.22
    sweep_reversal_clean_limit_max_jump_rate: float = 0.12
    trend_continuation_min_score: float = 70.0
    trend_continuation_grade_a_score: float = 85.0
    trend_continuation_grade_b_score: float = 75.0
    trend_continuation_grade_c_score: float = 70.0
    trend_continuation_min_impulse_atr: float = 1.2
    trend_continuation_pullback_min_atr: float = 0.4
    trend_continuation_pullback_max_atr: float = 1.6
    trend_continuation_protected_buffer_atr: float = 0.2
    range_rotation_min_score: float = 68.0
    range_rotation_grade_a_score: float = 83.0
    range_rotation_grade_b_score: float = 74.0
    range_rotation_grade_c_score: float = 68.0
    range_rotation_max_center_distance_atr: float = 0.8
    range_rotation_min_width_atr: float = 0.2
    range_rotation_max_width_atr: float = 1.1

    min_confluence_score: float = 62.0
    dedupe_entry_atr_distance: float = 0.45
    max_candidate_plans_per_symbol: int = 8
    meta_filter_enabled: bool = True
    meta_filter_min_score_trend: float = 44.0
    meta_filter_min_score_range: float = 48.0
    meta_filter_min_score_shock: float = 54.0
    meta_filter_min_reliability: float = 0.20

    # Relative factor weights for signal quality.
    weight_liquidity: float = 0.35
    weight_fvg_displacement: float = 0.25
    weight_htf_alignment: float = 0.20
    weight_ob_freshness: float = 0.15
    weight_trend_proxy: float = 0.05
    transition_edge_variant_enabled: bool = False
    transition_edge_variant_shadow_only: bool = True
    transition_edge_variant_min_confluence_delta: float = 8.0
    transition_edge_variant_htf_alignment_weight_multiplier: float = 0.5
    transition_edge_variant_trend_proxy_weight_multiplier: float = 0.25
    transition_edge_variant_fvg_relax_factor: float = 0.7
    transition_edge_variant_risk_multiplier: float = 0.35
    transition_edge_variant_partial_activation_ratio: float = 0.3
    transition_edge_variant_lane_tracker_window: int = 20
    session_impulse_retest_enabled: bool = False
    session_impulse_retest_shadow_only: bool = True
    session_impulse_retest_allowed_symbols: str = "BTCUSDC"
    session_impulse_retest_partial_activation_ratio: float = 0.3
    session_impulse_retest_core_live_slots: int = 2
    session_impulse_retest_secondary_live_enabled: bool = False
    session_impulse_retest_saturday_risk_multiplier: float = 1.0
    session_impulse_retest_miss_detector_enabled: bool = True
    session_impulse_retest_miss_detector_lookback_hours: int = 24
    session_impulse_retest_miss_detector_report_dir: str = "reports/validation/micro_main_miss_detectors"
    session_impulse_retest_miss_alert_enabled: bool = True
    session_impulse_retest_miss_alert_cooldown_seconds: int = 1800

    # Zone type importance multipliers (lower multiplier means less trust).
    weight_zone_ob: float = 1.00
    weight_zone_fvg: float = 0.86
    weight_zone_lp: float = 0.90
    weight_zone_flip: float = 0.72

    min_zone_sample_for_full_confidence: int = 30
    auto_disable_min_samples: int = 40
    auto_disable_ev_r_threshold: float = -0.05

    topn_default: int = 10
    scanner_default_limit: int = 20
    universe_name: str = "usdc_perp_top30"

    taker_fee_bps: float = Field(default=4.0, description="taker fee bps")
    maker_fee_bps: float = Field(default=2.0, description="maker fee bps")
    slippage_bps_base: float = 1.5
    slippage_bps_k: float = 3.5

    # Binance Futures (USDC Perp under USD-M futures API).
    binance_rest_base_url: str = "https://fapi.binance.com"
    binance_ws_base_url: str = "wss://fstream.binancefuture.com/stream"
    binance_timeout_seconds: float = 10.0
    binance_ws_receive_timeout_seconds: float = 30.0
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_trade_recv_window: int = 5000
    binance_trade_live_enabled: bool = False

    # Event bus backend and replay policy.
    event_backend: str = "memory"  # memory | redis | kafka
    event_redis_url: str = "redis://localhost:6379/0"
    event_redis_stream: str = "trading_events"
    event_kafka_bootstrap_servers: str = "localhost:9092"
    event_kafka_topic: str = "trading.events"
    event_late_seconds: int = 90
    event_retry_backoff_seconds: int = 10
    event_max_attempts: int = 8
    event_reprocess_batch_size: int = 100
    event_dedupe_window_seconds: int = 120

    # Validation report output.
    validation_report_dir: str = "reports/validation"
    validation_payload_cache_max_age_seconds: float = 900.0
    validation_payload_cache_stale_on_database_change: bool = False
    operations_checklist_report_dir: str = "reports/operations"
    kill_condition_automation_live_enabled: bool = False
    kill_condition_automation_arm_token: str = ""
    kill_condition_automation_report_dir: str = "reports/operations/kill_condition_automation"
    strategy_family_edge_review_report_dir: str = "reports/validation/edge_reviews"
    live_alpha_operating_review_report_dir: str = "reports/validation/live_alpha_reviews"
    replay_evidence_review_report_dir: str = "reports/validation/replay_evidence_reviews"
    validation_wf_train_months: int = 3
    validation_wf_test_months: int = 1
    validation_mc_simulations: int = 400
    pbo_dsr_trial_writer_enabled: bool = True
    pbo_dsr_trial_writer_target_folds: int = 4
    pbo_dsr_trial_writer_min_trades_per_fold: int = 2
    execution_quality_report_dir: str = "reports/execution"
    validation_alert_channel: str = "system"
    validation_alert_cooldown_seconds: int = 3600
    signal_alert_cooldown_seconds: int = 900
    signal_alert_near_atr_multiple: float = 0.35
    feature_importance_enabled: bool = True
    feature_calibration_enabled: bool = True
    feature_calibration_apply_runtime: bool = True
    feature_calibration_report_dir: str = "reports/calibration"
    feature_calibration_snapshot_dir: str = "reports/calibration/snapshots"
    feature_calibration_alpha: float = 0.35
    feature_calibration_max_delta: float = 0.04
    feature_calibration_min_weight: float = 0.05
    feature_calibration_min_generated_plans: int = 3
    feature_calibration_lookback_days: int = 120
    feature_calibration_half_life_days: float = 21.0
    feature_calibration_min_matches: int = 12
    feature_calibration_min_regime_matches: int = 4
    feature_calibration_max_zone_delta: float = 0.14
    parameter_changelog_enabled: bool = True
    parameter_changelog_path: str = "reports/params/PARAM_CHANGELOG.md"
    parameter_snapshot_dir: str = "reports/params/snapshots"
    alert_http_timeout_seconds: float = 5.0
    alert_retry_attempts: int = 3
    alert_retry_backoff_seconds: float = 0.4
    alert_circuit_breaker_failures: int = 3
    alert_circuit_breaker_cooldown_seconds: int = 90
    alert_retry_queue_max_attempts: int = 4
    alert_retry_queue_backoff_seconds: float = 30.0
    alert_retry_queue_jitter_seconds: float = 0.0
    alert_metrics_report_dir: str = "reports/alerts"
    alert_metrics_default_days: int = 30
    alert_slo_target_success_rate: float = 0.995
    alert_slo_warn_success_rate: float = 0.97
    alert_slo_max_p95_latency_ms: float = 3000.0
    alert_slo_warn_p95_latency_ms: float = 5000.0
    alert_slo_min_attempts: int = 5
    alert_telegram_bot_token: str = ""
    alert_telegram_chat_id: str = ""
    alert_discord_webhook_url: str = ""
    alert_push_webhook_url: str = ""
    alert_push_bearer_token: str = ""

    ws_reconnect_base_seconds: float = 1.0
    ws_reconnect_max_seconds: float = 20.0
    ws_refresh_cooldown_seconds: int = 20
    runtime_worker_heartbeat_dir: str = "/tmp/trading_worker_heartbeats"
    runtime_worker_loop_heartbeat_max_age_seconds: int = 420
    runtime_worker_ws_heartbeat_max_age_seconds: int = 180
    runtime_worker_ws_no_message_max_age_seconds: int = 180
    ready_require_runtime_workers: bool = True
    ready_disk_min_free_mb: int = 1024
    ready_market_data_probe_symbol: str = "BTCUSDC"
    ready_market_data_1m_max_age_seconds: int = 180
    ready_market_data_5m_max_age_seconds: int = 600

    ready_http_timeout_seconds: float = 2.0
    ready_tcp_timeout_seconds: float = 2.0

    portfolio_overlay_enabled: bool = True
    portfolio_overlay_include_planned_exposure: bool = False
    portfolio_overlay_window_bars: int = 240
    portfolio_overlay_min_overlap_bars: int = 60
    portfolio_overlay_high_corr_threshold: float = 0.82
    portfolio_overlay_max_total_exposure: int = 10
    portfolio_overlay_max_directional_exposure: int = 6
    portfolio_overlay_max_cluster_exposure: int = 2
    portfolio_overlay_penalty_per_high_corr: float = 8.0
    portfolio_overlay_penalty_corr_scale: float = 10.0
    portfolio_overlay_min_risk_budget_score: float = 35.0
    portfolio_overlay_volatility_target: float = 0.006
    portfolio_overlay_volatility_hard_cap: float = 0.018
    portfolio_overlay_penalty_volatility_scale: float = 18.0
    portfolio_overlay_penalty_exposure_scale: float = 12.0
    portfolio_overlay_regime_penalty_range: float = 0.0
    portfolio_overlay_regime_penalty_trend: float = 4.0
    portfolio_overlay_regime_penalty_shock: float = 12.0
    quality_gate_softening_enabled: bool = True
    quality_gate_softening_max_risk_budget_gap: float = 10.0
    quality_gate_softening_max_adjusted_score_gap: float = 6.0
    quality_gate_softening_min_expected_ev_r: float = 0.0
    portfolio_overlay_cap_multiplier_range: float = 1.0
    portfolio_overlay_cap_multiplier_trend: float = 0.85
    portfolio_overlay_cap_multiplier_shock: float = 0.5
    thesis_dedupe_enabled: bool = True
    thesis_time_bucket_minutes: int = 30
    thesis_max_active_clusters: int = 2
    thesis_duplicate_size_factor: float = 0.5
    strategy_mode: StrategyMode = StrategyMode.A_ONLY
    strategy_mode_a_only_max_daily_trades: int = 3
    strategy_mode_a_only_max_total_risk_r: float = 1.5
    strategy_mode_a_plus_b_max_daily_trades: int = 5
    strategy_mode_a_plus_b_max_total_risk_r: float = 2.0
    strategy_mode_research_max_daily_trades: int = 99
    strategy_mode_research_max_total_risk_r: float = 0.0
    operating_lock_daily_loss_limit_r: float = -2.0
    operating_lock_daily_consecutive_losses: int = 3
    operating_lock_daily_a_grade_failures: int = 2
    operating_lock_session_loss_limit_r: float = -1.5
    operating_lock_session_consecutive_losses: int = 2
    trading_session_london_start_hour_utc: int = 7
    trading_session_london_end_hour_utc: int = 12
    trading_session_new_york_start_hour_utc: int = 13
    trading_session_new_york_end_hour_utc: int = 18
    session_guidance_penalty_dead_session: float = 6.0
    session_guidance_penalty_session_lock: float = 3.0
    stress_replay_lineage_min_execution_fill_coverage: float = 0.70
    stress_replay_lineage_min_latency_candle_coverage: float = 0.70
    stress_replay_lineage_min_candle_path_coverage: float = 0.80
    stress_true_replay_min_execution_fill_coverage: float = 0.85
    stress_true_replay_min_latency_candle_coverage: float = 0.80
    stress_true_replay_min_candle_path_coverage: float = 0.90
    stress_true_replay_min_scenarios_compared: int = 2
    stress_replay_divergence_warn_ev_delta: float = -0.10
    stress_replay_divergence_fail_ev_delta: float = -0.25
    stress_replay_divergence_warn_max_drawdown_delta: float = 0.25
    stress_replay_divergence_fail_max_drawdown_delta: float = 0.75
    stress_replay_runner_target_trades_per_job: int = 20
    stress_replay_runner_min_trades_per_job: int = 8
    stress_replay_runner_max_parallel_jobs: int = 2
    sizing_grade_a_r: float = 1.0
    sizing_grade_b_r: float = 0.5
    sizing_grade_c_r: float = 0.25
    sizing_regime_factor_trend: float = 1.0
    sizing_regime_factor_range: float = 0.8
    sizing_regime_factor_shock: float = 0.4
    sizing_regime_factor_transition: float = 0.0
    sizing_reaction_factor_confirmed: float = 1.0
    sizing_reaction_factor_confirm_only: float = 0.7
    sizing_reaction_factor_mixed: float = 0.0
    sizing_execution_factor_limit: float = 1.0
    sizing_execution_factor_confirm: float = 0.85
    sizing_execution_factor_sweep_confirm: float = 0.75
    sizing_thesis_factor_none: float = 1.0
    sizing_thesis_factor_one_active: float = 0.6
    sizing_thesis_factor_two_or_more: float = 0.0
    sizing_btc_sweep_reversal_long_factor: float = 0.85
    btc_sweep_reversal_limit_runtime_signal_shadow_tilt_enabled: bool = True
    btc_sweep_reversal_limit_runtime_signal_shadow_tilt_long_weaken_close_vs_ema_fast_atr: float = -0.6978
    btc_sweep_reversal_limit_runtime_signal_shadow_tilt_long_size_factor: float = 0.75
    btc_sweep_reversal_limit_runtime_signal_shadow_tilt_short_strength_sweep_distance_atr: float = 0.4107
    btc_sweep_reversal_limit_runtime_signal_shadow_tilt_short_size_factor: float = 1.4762
    btc_sweep_reversal_limit_fast_failure_enabled: bool = True
    btc_sweep_reversal_limit_fast_failure_allowed_sessions: str = ""
    btc_sweep_reversal_limit_fast_failure_max_bars: int = 18
    btc_sweep_reversal_limit_fast_failure_stop_r: float = 0.00000001
    btc_sweep_reversal_limit_fast_failure_requires_sl_touch: bool = True
    alpha_research_pipeline_enabled: bool = True
    alpha_research_softened_risk_scale: float = 0.35
    alpha_research_max_candidates: int = 8
    portfolio_budget_report_dir: str = "reports/portfolio"
    execution_quality_default_days: int = 30
    auto_trading_enabled: bool = False
    auto_trading_execution_mode: str = "SHADOW"
    auto_trading_intent_recheck_cooldown_seconds: int = 300
    auto_trading_allowed_symbols: str = ""
    auto_trading_allowed_families: str = ""
    auto_trading_close_only: bool = False
    auto_trading_require_validation_go: bool = True
    auto_trading_replay_validation_bridge_enabled: bool = True
    auto_trading_replay_validation_bridge_backtest_dir: str = "reports/validation/micro_main_usdt_proxy_backtests"
    auto_trading_replay_validation_bridge_portfolio_dir: str = "reports/validation/micro_main_risk_sweeps"
    auto_trading_replay_validation_bridge_max_age_days: float = 14.0
    auto_trading_replay_validation_bridge_min_days: int = 1000
    auto_trading_replay_validation_bridge_min_trades: int = 80
    auto_trading_replay_validation_bridge_min_ev_r: float = 0.10
    auto_trading_replay_validation_bridge_min_win_rate: float = 0.40
    auto_trading_replay_validation_bridge_min_score: float = 70.0
    auto_trading_replay_validation_bridge_min_years: int = 3
    auto_trading_replay_validation_bridge_max_portfolio_mdd_pct: float = 25.0
    auto_trading_notional_per_r: float = 25.0
    auto_trading_live_sizing_mode: str = "NOTIONAL_PER_R"
    auto_trading_live_account_equity_usdt: float = 0.0
    auto_trading_live_risk_per_trade_pct: float = 0.0
    auto_trading_live_usable_margin_fraction: float = 0.85
    auto_trading_live_leverage_cap: float = 6.0
    auto_trading_max_slippage_bps: float = 12.0
    auto_trading_live_liquidity_gate_enabled: bool = False
    auto_trading_live_liquidity_gate_fail_closed: bool = True
    auto_trading_live_liquidity_gate_orderbook_limit: int = 100
    auto_trading_live_liquidity_gate_min_depth_usdt: float = 50_000.0
    auto_trading_live_liquidity_gate_max_depth_participation: float = 0.10
    auto_trading_live_liquidity_gate_max_1m_volume_participation: float = 0.02
    auto_trading_live_liquidity_gate_max_5m_volume_participation: float = 0.01
    auto_trading_live_liquidity_gate_max_spread_bps: float = 8.0
    auto_trading_live_liquidity_gate_max_market_slippage_bps: float = 10.0
    auto_trading_live_liquidity_gate_partial_submit_enabled: bool = False
    auto_trading_live_liquidity_gate_max_tranches: int = 3
    auto_trading_live_liquidity_gate_min_tranche_notional_usdt: float = 10.0
    auto_trading_micro_live_allowed_symbols: str = "BTCUSDC,ETHUSDC"
    auto_trading_micro_live_symbol_priority: str = "BTCUSDC,ETHUSDC"
    auto_trading_micro_live_direction_contract: str = "BTCUSDC:LONG|SHORT,ETHUSDC:LONG|SHORT"
    auto_trading_micro_live_session_direction_blocked_hours_utc: str = ""
    auto_trading_micro_live_priority_submit_ready_lookback_minutes: int = 180
    auto_trading_micro_live_allowed_families: str = "sweep_reversal,trend_continuation,session_impulse_retest"
    auto_trading_micro_live_allowed_entry_models: str = "LIMIT"
    auto_trading_micro_live_symbol_family_entry_direction_blocked_hours_utc: str = ""
    auto_trading_micro_live_event_blackout_path: str = ""
    auto_trading_micro_live_event_blackout_min_horizon_days: int = 45
    auto_trading_micro_live_strategy_time_contract_path: str = ""
    auto_trading_micro_live_plan_blocklist_path: str = ""
    auto_trading_micro_live_max_concurrent_positions: int = 2
    auto_trading_micro_live_max_daily_new_entries: int = 2
    auto_trading_micro_live_allowed_sessions: str = ""
    auto_trading_trend_proof_allowed_symbols: str = "BTCUSDC,ETHUSDC"
    auto_trading_trend_proof_regime_floor: float = 0.55
    auto_trading_trend_proof_min_abs_velocity: float = 0.38
    auto_trading_trend_proof_max_friction: float = 0.50
    auto_trading_trend_proof_max_jump_rate: float = 0.26
    auto_trading_historical_walk_forward_cache_hours: float = 6.0
    auto_trading_historical_walk_forward_warmup_5m_bars: int = 300
    auto_trading_historical_walk_forward_min_15m_bars: int = 60
    auto_trading_historical_walk_forward_max_5m_window_bars: int = 300
    auto_trading_historical_walk_forward_max_15m_window_bars: int = 300
    auto_trading_live_family_cluster_window_minutes: int = 60
    auto_trading_live_max_same_family_entries_per_window: int = 1
    auto_trading_live_max_same_family_direction_exposures: int = 0
    auto_trading_live_recent_loss_cooldown_minutes: int = 90
    auto_trading_live_recent_loss_trigger_count: int = 2
    auto_trading_reconciliation_user_stream_stale_seconds: int = 180
    auto_trading_paper_submission_stale_hours: int = 8
    auto_trading_paper_stale_sample_cleanup_hours: int = 12
    binance_live_min_quantity: float = 0.001
    binance_live_quantity_step: float = 0.001

    @field_validator("database_url")
    @classmethod
    def normalize_sqlite_database_url(cls, value: str) -> str:
        raw = str(value or "").strip()
        for prefix in SQLITE_URL_PREFIXES:
            if not raw.startswith(prefix):
                continue
            body = raw[len(prefix) :]
            path_part, separator, query = body.partition("?")
            if path_part in {"", ":memory:"} or path_part.startswith("/"):
                return raw
            absolute_path = (ROOT_DIR / unquote(path_part)).resolve()
            return f"{prefix}{absolute_path}{separator}{query}"
        return raw

    @field_validator(
        "session_impulse_retest_miss_detector_report_dir",
        "validation_report_dir",
        "operations_checklist_report_dir",
        "kill_condition_automation_report_dir",
        "strategy_family_edge_review_report_dir",
        "live_alpha_operating_review_report_dir",
        "replay_evidence_review_report_dir",
        "execution_quality_report_dir",
        "feature_calibration_report_dir",
        "feature_calibration_snapshot_dir",
        "parameter_changelog_path",
        "parameter_snapshot_dir",
        "alert_metrics_report_dir",
        "portfolio_budget_report_dir",
        "auto_trading_replay_validation_bridge_backtest_dir",
        "auto_trading_replay_validation_bridge_portfolio_dir",
    )
    @classmethod
    def normalize_root_relative_path(cls, value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return raw
        path = Path(raw).expanduser()
        return str(path if path.is_absolute() else (ROOT_DIR / path).resolve())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
