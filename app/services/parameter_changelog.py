from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.report_io import atomic_write_text

TRACKED_PARAMETER_KEYS = [
    "strategy_version",
    "atr_period",
    "zone_pivot_len",
    "zone_max_age_days",
    "scalp_zone_hard_max_age_hours",
    "scalp_zone_recent_boost_hours",
    "scalp_zone_age_penalty_per_hour",
    "scalp_plan_validity_minutes",
    "scalp_session_boost_score",
    "scalp_dead_session_penalty_score",
    "scalp_session_lock_penalty_score",
    "friction_threshold",
    "jump_threshold",
    "min_rr",
    "max_consecutive_losses",
    "jump_rate_gate",
    "strong_regime_gate",
    "friction_hard_gate",
    "jump_hard_gate",
    "transition_confirmed_score",
    "transition_watch_score",
    "transition_wick_body_ratio_confirmed",
    "transition_wick_body_ratio_unlock",
    "reaction_classifier_max_reclaim_bars",
    "reaction_classifier_rejection_displacement_atr",
    "reaction_classifier_rejection_max_outside_closes",
    "reaction_classifier_acceptance_min_outside_closes",
    "reaction_classifier_rejection_confirmed_score",
    "reaction_classifier_rejection_tentative_score",
    "reaction_classifier_acceptance_confirmed_score",
    "reaction_classifier_acceptance_tentative_score",
    "sweep_reversal_min_score",
    "sweep_reversal_grade_a_score",
    "sweep_reversal_grade_b_score",
    "sweep_reversal_grade_c_score",
    "sweep_reversal_clean_limit_max_width_atr",
    "sweep_reversal_clean_limit_max_friction",
    "sweep_reversal_clean_limit_max_jump_rate",
    "trend_continuation_min_score",
    "trend_continuation_grade_a_score",
    "trend_continuation_grade_b_score",
    "trend_continuation_grade_c_score",
    "trend_continuation_min_impulse_atr",
    "trend_continuation_pullback_min_atr",
    "trend_continuation_pullback_max_atr",
    "trend_continuation_protected_buffer_atr",
    "range_rotation_min_score",
    "range_rotation_grade_a_score",
    "range_rotation_grade_b_score",
    "range_rotation_grade_c_score",
    "range_rotation_max_center_distance_atr",
    "range_rotation_min_width_atr",
    "range_rotation_max_width_atr",
    "min_confluence_score",
    "dedupe_entry_atr_distance",
    "max_candidate_plans_per_symbol",
    "meta_filter_enabled",
    "meta_filter_min_score_trend",
    "meta_filter_min_score_range",
    "meta_filter_min_score_shock",
    "meta_filter_min_reliability",
    "weight_liquidity",
    "weight_fvg_displacement",
    "weight_htf_alignment",
    "weight_ob_freshness",
    "weight_trend_proxy",
    "weight_zone_ob",
    "weight_zone_fvg",
    "weight_zone_lp",
    "weight_zone_flip",
    "min_zone_sample_for_full_confidence",
    "auto_disable_min_samples",
    "auto_disable_ev_r_threshold",
    "taker_fee_bps",
    "maker_fee_bps",
    "slippage_bps_base",
    "slippage_bps_k",
    "binance_trade_recv_window",
    "binance_trade_live_enabled",
    "validation_wf_train_months",
    "validation_wf_test_months",
    "validation_mc_simulations",
    "pbo_dsr_trial_writer_enabled",
    "pbo_dsr_trial_writer_target_folds",
    "pbo_dsr_trial_writer_min_trades_per_fold",
    "alert_retry_attempts",
    "alert_retry_backoff_seconds",
    "alert_circuit_breaker_failures",
    "alert_circuit_breaker_cooldown_seconds",
    "alert_retry_queue_max_attempts",
    "alert_retry_queue_backoff_seconds",
    "alert_retry_queue_jitter_seconds",
    "alert_retry_queue_max_age_seconds",
    "alert_slo_target_success_rate",
    "alert_slo_warn_success_rate",
    "alert_slo_max_p95_latency_ms",
    "alert_slo_warn_p95_latency_ms",
    "alert_slo_min_attempts",
    "signal_alert_cooldown_seconds",
    "signal_alert_near_atr_multiple",
    "feature_importance_enabled",
    "feature_calibration_enabled",
    "feature_calibration_apply_runtime",
    "feature_calibration_alpha",
    "feature_calibration_max_delta",
    "feature_calibration_min_weight",
    "feature_calibration_min_generated_plans",
    "feature_calibration_lookback_days",
    "feature_calibration_half_life_days",
    "feature_calibration_min_matches",
    "feature_calibration_min_regime_matches",
    "feature_calibration_max_zone_delta",
    "portfolio_overlay_min_risk_budget_score",
    "portfolio_overlay_volatility_target",
    "portfolio_overlay_volatility_hard_cap",
    "portfolio_overlay_penalty_volatility_scale",
    "portfolio_overlay_penalty_exposure_scale",
    "portfolio_overlay_regime_penalty_range",
    "portfolio_overlay_regime_penalty_trend",
    "portfolio_overlay_regime_penalty_shock",
    "portfolio_overlay_cap_multiplier_range",
    "portfolio_overlay_cap_multiplier_trend",
    "portfolio_overlay_cap_multiplier_shock",
    "thesis_dedupe_enabled",
    "thesis_time_bucket_minutes",
    "thesis_max_active_clusters",
    "thesis_duplicate_size_factor",
    "strategy_mode",
    "strategy_mode_a_only_max_daily_trades",
    "strategy_mode_a_only_max_total_risk_r",
    "strategy_mode_a_plus_b_max_daily_trades",
    "strategy_mode_a_plus_b_max_total_risk_r",
    "strategy_mode_research_max_daily_trades",
    "strategy_mode_research_max_total_risk_r",
    "operating_lock_daily_loss_limit_r",
    "operating_lock_daily_consecutive_losses",
    "operating_lock_daily_a_grade_failures",
    "operating_lock_session_loss_limit_r",
    "operating_lock_session_consecutive_losses",
    "trading_session_london_start_hour_utc",
    "trading_session_london_end_hour_utc",
    "trading_session_new_york_start_hour_utc",
    "trading_session_new_york_end_hour_utc",
    "session_guidance_penalty_dead_session",
    "session_guidance_penalty_session_lock",
    "stress_replay_lineage_min_execution_fill_coverage",
    "stress_replay_lineage_min_latency_candle_coverage",
    "stress_replay_lineage_min_candle_path_coverage",
    "stress_true_replay_min_execution_fill_coverage",
    "stress_true_replay_min_latency_candle_coverage",
    "stress_true_replay_min_candle_path_coverage",
    "stress_true_replay_min_scenarios_compared",
    "stress_replay_divergence_warn_ev_delta",
    "stress_replay_divergence_fail_ev_delta",
    "stress_replay_divergence_warn_max_drawdown_delta",
    "stress_replay_divergence_fail_max_drawdown_delta",
    "stress_replay_runner_target_trades_per_job",
    "stress_replay_runner_min_trades_per_job",
    "stress_replay_runner_max_parallel_jobs",
    "auto_trading_trend_proof_regime_floor",
    "auto_trading_trend_proof_min_abs_velocity",
    "auto_trading_trend_proof_max_friction",
    "auto_trading_trend_proof_max_jump_rate",
    "sizing_grade_a_r",
    "sizing_grade_b_r",
    "sizing_grade_c_r",
    "sizing_regime_factor_trend",
    "sizing_regime_factor_range",
    "sizing_regime_factor_shock",
    "sizing_regime_factor_transition",
    "sizing_reaction_factor_confirmed",
    "sizing_reaction_factor_confirm_only",
    "sizing_reaction_factor_mixed",
    "sizing_execution_factor_limit",
    "sizing_execution_factor_confirm",
    "sizing_execution_factor_sweep_confirm",
    "sizing_thesis_factor_none",
    "sizing_thesis_factor_one_active",
    "sizing_thesis_factor_two_or_more",
    "sizing_btc_sweep_reversal_long_factor",
    "btc_sweep_reversal_limit_fast_failure_enabled",
    "btc_sweep_reversal_limit_fast_failure_allowed_sessions",
    "btc_sweep_reversal_limit_fast_failure_max_bars",
    "btc_sweep_reversal_limit_fast_failure_stop_r",
    "btc_sweep_reversal_limit_fast_failure_requires_sl_touch",
    "auto_trading_live_liquidity_gate_enabled",
    "auto_trading_live_liquidity_gate_fail_closed",
    "auto_trading_live_liquidity_gate_orderbook_limit",
    "auto_trading_live_liquidity_gate_min_depth_usdt",
    "auto_trading_live_liquidity_gate_max_depth_participation",
    "auto_trading_live_liquidity_gate_max_1m_volume_participation",
    "auto_trading_live_liquidity_gate_max_5m_volume_participation",
    "auto_trading_live_liquidity_gate_max_spread_bps",
    "auto_trading_live_liquidity_gate_max_market_slippage_bps",
    "auto_trading_live_liquidity_gate_partial_submit_enabled",
    "auto_trading_live_liquidity_gate_max_tranches",
    "auto_trading_live_liquidity_gate_min_tranche_notional_usdt",
    "auto_trading_micro_live_allowed_entry_models",
    "auto_trading_micro_live_session_direction_blocked_hours_utc",
    "auto_trading_micro_live_symbol_family_entry_direction_blocked_hours_utc",
    "auto_trading_micro_live_event_blackout_path",
    "auto_trading_micro_live_strategy_time_contract_path",
    "auto_trading_micro_live_plan_blocklist_path",
]


@dataclass(slots=True)
class ChangelogResult:
    updated: bool
    reason: str
    path: str
    snapshot_path: str
    changes_count: int
    changes: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "updated": self.updated,
            "reason": self.reason,
            "path": self.path,
            "snapshot_path": self.snapshot_path,
            "changes_count": self.changes_count,
            "changes": self.changes,
        }


class ParameterChangelogService:
    def __init__(self):
        self.settings = get_settings()

    def _snapshot_parameters(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key in TRACKED_PARAMETER_KEYS:
            out[key] = getattr(self.settings, key)
        return out

    @staticmethod
    def _latest_snapshot_file(snapshot_dir: Path) -> Path:
        return snapshot_dir / "latest.json"

    @staticmethod
    def _load_latest(snapshot_dir: Path) -> dict[str, Any] | None:
        latest_file = ParameterChangelogService._latest_snapshot_file(snapshot_dir)
        if not latest_file.exists():
            return None
        try:
            return json.loads(latest_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    @staticmethod
    def _format_value(value: Any) -> str:
        return json.dumps(value, ensure_ascii=True, sort_keys=True)

    @staticmethod
    def _diff(old_params: dict[str, Any], new_params: dict[str, Any]) -> dict[str, dict[str, Any]]:
        changes: dict[str, dict[str, Any]] = {}
        keys = sorted(set(old_params.keys()) | set(new_params.keys()))
        for key in keys:
            old_val = old_params.get(key)
            new_val = new_params.get(key)
            if old_val != new_val:
                changes[key] = {"old": old_val, "new": new_val}
        return changes

    def _append_entry(
        self,
        *,
        changelog_path: Path,
        now: datetime,
        version: str,
        trigger: str,
        changes: dict[str, dict[str, Any]],
        initialized: bool,
    ) -> None:
        if not changelog_path.exists():
            header = [
                "# Parameter ChangeLog",
                "",
                "- Auto-generated from strategy settings snapshots.",
                "- Triggered by validation/report workflows.",
                "",
            ]
            atomic_write_text(changelog_path, "\n".join(header))

        lines: list[str] = []
        lines.append(f"## {now.isoformat()} | version={version} | trigger={trigger}")
        if initialized:
            lines.append(f"- initialized parameters snapshot ({len(TRACKED_PARAMETER_KEYS)} keys)")
        else:
            lines.append(f"- changed keys: {len(changes)}")
            for key in sorted(changes):
                old_str = self._format_value(changes[key].get("old"))
                new_str = self._format_value(changes[key].get("new"))
                lines.append(f"- `{key}`: {old_str} -> {new_str}")
        lines.append("")

        existing = changelog_path.read_text(encoding="utf-8") if changelog_path.exists() else ""
        separator = "" if not existing or existing.endswith("\n") else "\n"
        entry = "\n".join(lines)
        atomic_write_text(changelog_path, f"{existing}{separator}{entry}")

    def generate(self, *, version: str, trigger: str = "validation_report") -> dict[str, Any]:
        changelog_path = Path(self.settings.parameter_changelog_path)
        snapshot_dir = Path(self.settings.parameter_snapshot_dir)
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        if not self.settings.parameter_changelog_enabled:
            return ChangelogResult(
                updated=False,
                reason="parameter_changelog_disabled",
                path=str(changelog_path),
                snapshot_path="",
                changes_count=0,
                changes={},
            ).to_dict()

        now = datetime.now(timezone.utc).replace(microsecond=0)
        params = self._snapshot_parameters()
        payload = {
            "generated_at": now.isoformat(),
            "version": version,
            "trigger": trigger,
            "parameters": params,
        }

        snapshot_file = snapshot_dir / f"params_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
        if snapshot_file.exists():
            # Handle back-to-back runs inside the same second without clobbering evidence.
            suffix = datetime.now(timezone.utc).strftime("%f")
            snapshot_file = snapshot_dir / f"params_{now.strftime('%Y%m%dT%H%M%SZ')}_{suffix}.json"
        old_payload = self._load_latest(snapshot_dir)
        if old_payload is None:
            serialized = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
            atomic_write_text(snapshot_file, serialized)
            atomic_write_text(self._latest_snapshot_file(snapshot_dir), serialized)
            self._append_entry(
                changelog_path=changelog_path,
                now=now,
                version=version,
                trigger=trigger,
                changes={},
                initialized=True,
            )
            return ChangelogResult(
                updated=True,
                reason="initialized",
                path=str(changelog_path),
                snapshot_path=str(snapshot_file),
                changes_count=len(params),
                changes={},
            ).to_dict()

        old_params = dict(old_payload.get("parameters", {}))
        changes = self._diff(old_params, params)
        if not changes:
            atomic_write_text(
                self._latest_snapshot_file(snapshot_dir),
                json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
            )
            return ChangelogResult(
                updated=False,
                reason="no_changes",
                path=str(changelog_path),
                snapshot_path="",
                changes_count=0,
                changes={},
            ).to_dict()

        serialized = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
        atomic_write_text(snapshot_file, serialized)
        atomic_write_text(self._latest_snapshot_file(snapshot_dir), serialized)
        self._append_entry(
            changelog_path=changelog_path,
            now=now,
            version=version,
            trigger=trigger,
            changes=changes,
            initialized=False,
        )
        return ChangelogResult(
            updated=True,
            reason="changes_detected",
            path=str(changelog_path),
            snapshot_path=str(snapshot_file),
            changes_count=len(changes),
            changes=changes,
        ).to_dict()
