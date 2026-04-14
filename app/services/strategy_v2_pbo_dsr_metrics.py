from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any

from app.core.config import Settings, get_settings
from app.db.models import ValidationPboDsrSnapshot, ValidationTrialFoldScore, ValidationTrialRun
from app.db.repositories import ValidationArtifactRepository


class StrategyV2PboDsrMetricsService:
    _NORMAL = NormalDist()
    _EULER_GAMMA = 0.5772156649015329
    _RUNTIME_PROXY_SELECTION_RULE_PREFIXES = ("runtime_validation_proxy",)
    _TRUE_THRESHOLD_SELECTION_RULE_PREFIXES = ("true_threshold_sweep",)
    _RUNTIME_PROXY_WRITER_SOURCES = {"runtime_validation_proxy_v1"}
    _TRUE_THRESHOLD_WRITER_SOURCES = {"true_threshold_sweep_runner_v1"}

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        repo: ValidationArtifactRepository | None = None,
    ):
        self.settings = settings or get_settings()
        self.repo = repo

    @staticmethod
    def _round(value: float | None, digits: int = 6) -> float | None:
        if value is None:
            return None
        return round(float(value), digits)

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            if value in {None, ""}:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            if value in {None, ""}:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _selected_trial_priority(row: ValidationTrialRun) -> tuple[int, int, float, str]:
        payload = dict(row.payload or {})
        writer_source = str(payload.get("writer_source") or payload.get("source") or "")
        selection_rule = str(row.selection_rule or "")
        if (
            writer_source in StrategyV2PboDsrMetricsService._TRUE_THRESHOLD_WRITER_SOURCES
            or selection_rule.startswith(StrategyV2PboDsrMetricsService._TRUE_THRESHOLD_SELECTION_RULE_PREFIXES)
        ):
            lineage_priority = 0
        elif (
            writer_source in StrategyV2PboDsrMetricsService._RUNTIME_PROXY_WRITER_SOURCES
            or selection_rule.startswith(StrategyV2PboDsrMetricsService._RUNTIME_PROXY_SELECTION_RULE_PREFIXES)
        ):
            lineage_priority = 1
        else:
            lineage_priority = 2
        selection_rank = row.selection_rank if row.selection_rank is not None else 999999
        out_of_sample = float(row.out_of_sample_metric) if row.out_of_sample_metric is not None else -999999.0
        return (lineage_priority, selection_rank, -out_of_sample, str(row.trial_run_id))

    @staticmethod
    def _selected_trial(trial_runs: list[ValidationTrialRun]) -> ValidationTrialRun | None:
        if not trial_runs:
            return None
        def metric_or_floor(value: float | None) -> float:
            return float(value) if value is not None else -999999.0

        selected = [row for row in trial_runs if bool(row.selected_flag)]
        if selected:
            selected.sort(key=StrategyV2PboDsrMetricsService._selected_trial_priority)
            return selected[0]
        ranked = [row for row in trial_runs if row.selection_rank is not None]
        if ranked:
            ranked.sort(key=StrategyV2PboDsrMetricsService._selected_trial_priority)
            return ranked[0]
        ordered = sorted(
            trial_runs,
            key=lambda row: (
                -metric_or_floor(row.out_of_sample_metric),
                -metric_or_floor(row.in_sample_metric),
                str(row.trial_run_id),
            ),
        )
        return ordered[0] if ordered else None

    @staticmethod
    def _selected_fold_row(
        rows: list[ValidationTrialFoldScore],
        *,
        selected_trial_run_id: str | None,
    ) -> ValidationTrialFoldScore | None:
        selected = [row for row in rows if bool(row.selected_flag)]
        if selected:
            selected.sort(
                key=lambda row: (
                    row.selection_rank if row.selection_rank is not None else 999999,
                    str(row.trial_run_id),
                )
            )
            return selected[0]
        if selected_trial_run_id:
            matches = [row for row in rows if str(row.trial_run_id) == selected_trial_run_id]
            if matches:
                matches.sort(
                    key=lambda row: (
                        row.selection_rank if row.selection_rank is not None else 999999,
                        str(row.trial_run_id),
                    )
                )
                return matches[0]
        ranked = [row for row in rows if row.selection_rank is not None]
        if ranked:
            ranked.sort(key=lambda row: (row.selection_rank if row.selection_rank is not None else 999999, str(row.trial_run_id)))
            return ranked[0]
        return None

    @staticmethod
    def _moment_stats(values: list[float]) -> tuple[float, float]:
        if len(values) < 3:
            return 0.0, 3.0
        mean = sum(values) / len(values)
        centered = [float(value) - mean for value in values]
        m2 = sum(value**2 for value in centered) / len(centered)
        if m2 <= 1e-12:
            return 0.0, 3.0
        m3 = sum(value**3 for value in centered) / len(centered)
        m4 = sum(value**4 for value in centered) / len(centered)
        skew = m3 / (m2 ** 1.5)
        kurtosis = m4 / (m2**2)
        return float(skew), float(kurtosis)

    @classmethod
    def _expected_max_sharpe(cls, *, selection_universe_size: int, sample_size: int) -> float:
        if selection_universe_size <= 1 or sample_size <= 1:
            return 0.0
        effective_n = max(2, int(selection_universe_size))
        p1 = min(1.0 - 1e-9, max(1e-9, 1.0 - (1.0 / effective_n)))
        p2 = min(1.0 - 1e-9, max(1e-9, 1.0 - (1.0 / (effective_n * math.e))))
        expected_max_z = (
            (1.0 - cls._EULER_GAMMA) * cls._NORMAL.inv_cdf(p1)
            + cls._EULER_GAMMA * cls._NORMAL.inv_cdf(p2)
        )
        return float(expected_max_z) / math.sqrt(float(max(sample_size - 1, 1)))

    def _compute_pbo(
        self,
        *,
        fold_scores: list[ValidationTrialFoldScore],
        selected_trial_run_id: str | None,
    ) -> dict[str, Any]:
        by_fold: dict[str, list[ValidationTrialFoldScore]] = defaultdict(list)
        for row in fold_scores:
            by_fold[str(row.fold_id)].append(row)

        eligible_folds = 0
        overfit_folds = 0
        rank_percentiles: list[float] = []
        fold_details: list[dict[str, Any]] = []
        for fold_id, rows in sorted(by_fold.items()):
            eligible_rows = [row for row in rows if row.out_of_sample_metric is not None]
            if len(eligible_rows) < 2:
                continue
            selected_row = self._selected_fold_row(rows=eligible_rows, selected_trial_run_id=selected_trial_run_id)
            if selected_row is None or selected_row.out_of_sample_metric is None:
                continue
            ordered = sorted(
                eligible_rows,
                key=lambda row: (
                    -(float(row.out_of_sample_metric) if row.out_of_sample_metric is not None else -999999.0),
                    row.selection_rank if row.selection_rank is not None else 999999,
                    str(row.trial_run_id),
                ),
            )
            selected_rank = next(
                index + 1 for index, row in enumerate(ordered) if str(row.trial_run_id) == str(selected_row.trial_run_id)
            )
            universe_size = len(ordered)
            percentile = float(selected_rank) / float(universe_size)
            worse_half = bool(selected_rank > math.ceil(universe_size / 2.0))
            eligible_folds += 1
            overfit_folds += int(worse_half)
            rank_percentiles.append(percentile)
            fold_details.append(
                {
                    "fold_id": fold_id,
                    "selected_trial_run_id": str(selected_row.trial_run_id),
                    "selected_oos_rank": selected_rank,
                    "selection_universe_size": universe_size,
                    "selected_oos_rank_percentile": round(percentile, 4),
                    "worse_half": worse_half,
                }
            )

        if eligible_folds <= 0:
            return {
                "available": False,
                "reason": "insufficient_fold_scores",
                "value": None,
                "status": "not_available",
                "thresholds": {"pass": 0.20, "warn": 0.35, "fail": 0.35},
                "eligible_folds": 0,
                "overfit_folds": 0,
                "selected_rank_percentile_avg": None,
                "fold_details": [],
            }

        pbo_value = float(overfit_folds) / float(eligible_folds)
        if pbo_value < 0.20:
            status = "PASS"
            reason = "pbo_below_pass_threshold"
        elif pbo_value < 0.35:
            status = "WARN"
            reason = "pbo_between_pass_and_fail_threshold"
        else:
            status = "FAIL"
            reason = "pbo_above_fail_threshold"

        return {
            "available": True,
            "reason": reason,
            "value": self._round(pbo_value),
            "status": status,
            "thresholds": {"pass": 0.20, "warn": 0.35, "fail": 0.35},
            "eligible_folds": eligible_folds,
            "overfit_folds": overfit_folds,
            "selected_rank_percentile_avg": self._round(sum(rank_percentiles) / len(rank_percentiles), 4),
            "fold_details": fold_details[:20],
        }

    def _compute_dsr(
        self,
        *,
        selected_trial: ValidationTrialRun | None,
        selected_trial_fold_scores: list[ValidationTrialFoldScore],
        eligible_trial_count: int,
        selection_rule_counts: dict[str, int],
    ) -> dict[str, Any]:
        if selected_trial is None:
            return {
                "available": False,
                "reason": "selected_trial_missing",
                "value": None,
                "probability": None,
                "status": "not_available",
                "min_threshold": 0.0,
            }

        sharpe_like = self._safe_float(selected_trial.sharpe_like_score)
        if sharpe_like is None:
            return {
                "available": False,
                "reason": "selected_trial_sharpe_missing",
                "value": None,
                "probability": None,
                "status": "not_available",
                "min_threshold": 0.0,
            }

        fold_oos = [
            float(row.out_of_sample_metric)
            for row in selected_trial_fold_scores
            if row.out_of_sample_metric is not None
        ]
        payload = dict(selected_trial.payload or {})
        sample_size = max(
            self._safe_int(payload.get("trade_count")) or 0,
            self._safe_int(selected_trial.trial_count) or 0,
            len(fold_oos),
        )
        if sample_size < 2:
            return {
                "available": False,
                "reason": "insufficient_selected_trial_sample_size",
                "value": None,
                "probability": None,
                "status": "not_available",
                "min_threshold": 0.0,
            }

        legacy_combined_selection_universe_size = max(
            self._safe_int(payload.get("selection_universe_size")) or 0,
            self._safe_int(selected_trial.selection_universe_size) or 0,
            eligible_trial_count,
        )
        if legacy_combined_selection_universe_size <= 0:
            legacy_combined_selection_universe_size = max(eligible_trial_count, 1)
        full_parameter_sweep_selection_universe_size = max(
            self._safe_int(payload.get("full_parameter_sweep_selection_universe_size")) or 0,
            self._lineage_count(
                selection_rule_counts=selection_rule_counts,
                prefixes=self._TRUE_THRESHOLD_SELECTION_RULE_PREFIXES,
            ),
        )
        if full_parameter_sweep_selection_universe_size > 0:
            selection_universe_size = int(full_parameter_sweep_selection_universe_size)
            selection_universe_basis = "full_parameter_sweep_universe"
        else:
            selection_universe_size = int(legacy_combined_selection_universe_size)
            selection_universe_basis = "combined_artifact_universe"

        fold_skew, fold_kurtosis = self._moment_stats(fold_oos)
        skewness = self._safe_float(payload.get("return_skewness"))
        if skewness is None:
            skewness = self._safe_float(payload.get("skewness"))
        kurtosis = self._safe_float(payload.get("return_kurtosis"))
        if kurtosis is None:
            kurtosis = self._safe_float(payload.get("kurtosis"))
        if skewness is None:
            skewness = fold_skew
        if kurtosis is None:
            kurtosis = fold_kurtosis

        benchmark_sharpe = self._expected_max_sharpe(
            selection_universe_size=selection_universe_size,
            sample_size=sample_size,
        )
        legacy_combined_benchmark_sharpe = self._expected_max_sharpe(
            selection_universe_size=legacy_combined_selection_universe_size,
            sample_size=sample_size,
        )
        denominator = 1.0 - (float(skewness) * float(sharpe_like)) + (((float(kurtosis) - 1.0) / 4.0) * (float(sharpe_like) ** 2))
        denominator = max(denominator, 1e-9)
        dsr_score = ((float(sharpe_like) - float(benchmark_sharpe)) * math.sqrt(float(max(sample_size - 1, 1)))) / math.sqrt(denominator)
        dsr_probability = self._NORMAL.cdf(dsr_score)
        status = "PASS" if dsr_score > 0.0 else "FAIL"
        reason = "dsr_positive" if dsr_score > 0.0 else "dsr_non_positive"
        return {
            "available": True,
            "reason": reason,
            "value": self._round(dsr_score),
            "probability": self._round(dsr_probability),
            "status": status,
            "min_threshold": 0.0,
            "selected_trial_run_id": str(selected_trial.trial_run_id),
            "selected_trial_sharpe": self._round(sharpe_like),
            "benchmark_sharpe": self._round(benchmark_sharpe),
            "sample_size": int(sample_size),
            "selection_universe_size": int(selection_universe_size),
            "selection_universe_basis": selection_universe_basis,
            "legacy_combined_selection_universe_size": int(legacy_combined_selection_universe_size),
            "legacy_combined_benchmark_sharpe": self._round(legacy_combined_benchmark_sharpe),
            "full_parameter_sweep_selection_universe_size": (
                int(full_parameter_sweep_selection_universe_size) if full_parameter_sweep_selection_universe_size > 0 else None
            ),
            "bias_adjustment_rechecked": selection_universe_basis == "full_parameter_sweep_universe",
            "benchmark_sharpe_delta_vs_legacy_combined": self._round(
                float(benchmark_sharpe) - float(legacy_combined_benchmark_sharpe)
            ),
            "skewness": self._round(skewness),
            "kurtosis": self._round(kurtosis),
            "selected_trial_fold_count": len(fold_oos),
        }

    @staticmethod
    def _selected_trial_summary(selected_trial: ValidationTrialRun | None) -> dict[str, Any] | None:
        if selected_trial is None:
            return None
        payload = dict(selected_trial.payload or {})
        lineage_selection_universe_size = payload.get("lineage_selection_universe_size")
        if lineage_selection_universe_size in {None, ""}:
            lineage_selection_universe_size = selected_trial.selection_universe_size
        else:
            lineage_selection_universe_size = int(lineage_selection_universe_size)
        full_parameter_sweep_size = payload.get("full_parameter_sweep_selection_universe_size")
        if full_parameter_sweep_size in {None, ""}:
            full_parameter_sweep_size = None
        else:
            full_parameter_sweep_size = int(full_parameter_sweep_size)
        return {
            "trial_run_id": str(selected_trial.trial_run_id),
            "parameter_family": str(selected_trial.parameter_family),
            "parameter_values": dict(selected_trial.parameter_values or {}),
            "selection_rule": str(selected_trial.selection_rule or ""),
            "selected_flag": bool(selected_trial.selected_flag),
            "selection_rank": selected_trial.selection_rank,
            "in_sample_metric": selected_trial.in_sample_metric,
            "out_of_sample_metric": selected_trial.out_of_sample_metric,
            "sharpe_like_score": selected_trial.sharpe_like_score,
            "trial_count": selected_trial.trial_count,
            "selection_universe_size": selected_trial.selection_universe_size,
            "lineage_selection_universe_size": lineage_selection_universe_size,
            "selection_universe_basis": str(payload.get("selection_universe_basis") or "selection_rule_lineage"),
            "full_parameter_sweep_selection_universe_size": full_parameter_sweep_size,
            "writer_source": str(payload.get("writer_source") or payload.get("source") or "unknown"),
            "lineage_namespace": str(payload.get("lineage_namespace") or ""),
            "created_at": selected_trial.created_at.isoformat() if selected_trial.created_at else None,
        }

    @classmethod
    def _selection_universe_summary(
        cls,
        *,
        selection_rule_counts: dict[str, int],
        eligible_trial_count: int,
        selected_trial_summary: dict[str, Any] | None,
        dsr_selection_universe_size: int | None,
        dsr_selection_universe_basis: str | None,
    ) -> dict[str, Any]:
        runtime_proxy_universe = cls._lineage_count(
            selection_rule_counts=selection_rule_counts,
            prefixes=cls._RUNTIME_PROXY_SELECTION_RULE_PREFIXES,
        )
        true_threshold_universe = cls._lineage_count(
            selection_rule_counts=selection_rule_counts,
            prefixes=cls._TRUE_THRESHOLD_SELECTION_RULE_PREFIXES,
        )
        full_parameter_sweep_universe = true_threshold_universe if true_threshold_universe > 0 else None
        selected_trial_lineage_selection_universe_size = None
        if selected_trial_summary is not None and selected_trial_summary.get("lineage_selection_universe_size") is not None:
            selected_trial_lineage_selection_universe_size = int(selected_trial_summary["lineage_selection_universe_size"])
        return {
            "combined_artifact_selection_universe_size": int(max(eligible_trial_count, 0)),
            "runtime_proxy_selection_universe_size": int(runtime_proxy_universe),
            "true_threshold_selection_universe_size": int(true_threshold_universe),
            "full_parameter_sweep_selection_universe_size": full_parameter_sweep_universe,
            "selected_trial_lineage_selection_universe_size": selected_trial_lineage_selection_universe_size,
            "dsr_selection_universe_size": int(dsr_selection_universe_size) if dsr_selection_universe_size is not None else None,
            "dsr_selection_universe_basis": str(dsr_selection_universe_basis or "combined_artifact_universe"),
            "bias_adjustment_rechecked": str(dsr_selection_universe_basis or "") == "full_parameter_sweep_universe",
            "recording_status": "split_recorded" if full_parameter_sweep_universe is not None else "combined_only",
        }

    @classmethod
    def _lineage_count(cls, selection_rule_counts: dict[str, int], prefixes: tuple[str, ...]) -> int:
        total = 0
        for key, value in selection_rule_counts.items():
            if str(key).startswith(prefixes):
                total += int(value or 0)
        return total

    @classmethod
    def _selected_trial_lineage_flags(cls, selected_trial_summary: dict[str, Any] | None) -> tuple[bool, bool]:
        if not selected_trial_summary:
            return False, False
        writer_source = str(selected_trial_summary.get("writer_source") or "unknown")
        selection_rule = str(selected_trial_summary.get("selection_rule") or "")
        lineage_namespace = str(selected_trial_summary.get("lineage_namespace") or "")
        from_runtime_proxy = (
            writer_source in cls._RUNTIME_PROXY_WRITER_SOURCES
            or selection_rule.startswith(cls._RUNTIME_PROXY_SELECTION_RULE_PREFIXES)
            or lineage_namespace in cls._RUNTIME_PROXY_WRITER_SOURCES
        )
        from_true_threshold = (
            writer_source in cls._TRUE_THRESHOLD_WRITER_SOURCES
            or selection_rule.startswith(cls._TRUE_THRESHOLD_SELECTION_RULE_PREFIXES)
            or lineage_namespace in cls._TRUE_THRESHOLD_WRITER_SOURCES
        )
        return from_runtime_proxy, from_true_threshold

    @classmethod
    def _lineage_audit(
        cls,
        *,
        selection_rule_counts: dict[str, int],
        selected_trial_summary: dict[str, Any] | None,
    ) -> dict[str, Any]:
        runtime_proxy_trials = cls._lineage_count(
            selection_rule_counts=selection_rule_counts,
            prefixes=cls._RUNTIME_PROXY_SELECTION_RULE_PREFIXES,
        )
        true_threshold_trials = cls._lineage_count(
            selection_rule_counts=selection_rule_counts,
            prefixes=cls._TRUE_THRESHOLD_SELECTION_RULE_PREFIXES,
        )
        has_runtime_proxy_lineage = runtime_proxy_trials > 0
        has_true_threshold_lineage = true_threshold_trials > 0
        selected_from_runtime_proxy, selected_from_true_threshold = cls._selected_trial_lineage_flags(selected_trial_summary)

        if has_runtime_proxy_lineage and has_true_threshold_lineage:
            lineage_mix_state = "dual_lineage"
        elif has_true_threshold_lineage:
            lineage_mix_state = "true_threshold_only"
        elif has_runtime_proxy_lineage:
            lineage_mix_state = "runtime_proxy_only"
        else:
            lineage_mix_state = "no_lineage"

        if not selection_rule_counts:
            audit_status = "WARN"
            reason = "selection_rule_counts_missing"
        elif not has_runtime_proxy_lineage and not has_true_threshold_lineage:
            audit_status = "PASS"
            reason = "legacy_or_unclassified_selection_rules_only"
        elif selected_trial_summary is None:
            audit_status = "WARN"
            reason = "selected_trial_missing"
        elif has_true_threshold_lineage and has_runtime_proxy_lineage and selected_from_runtime_proxy:
            audit_status = "WARN"
            reason = "selected_trial_from_runtime_proxy_while_true_threshold_lineage_exists"
        elif has_true_threshold_lineage and has_runtime_proxy_lineage and selected_from_true_threshold:
            audit_status = "PASS"
            reason = "selected_trial_from_true_threshold_with_dual_lineage"
        elif has_true_threshold_lineage and not has_runtime_proxy_lineage and selected_from_true_threshold:
            audit_status = "PASS"
            reason = "selected_trial_from_true_threshold_only_lineage"
        elif has_runtime_proxy_lineage and not has_true_threshold_lineage and selected_from_runtime_proxy:
            audit_status = "PASS"
            reason = "runtime_proxy_only_lineage"
        elif has_true_threshold_lineage and selected_from_runtime_proxy:
            audit_status = "WARN"
            reason = "selected_trial_runtime_proxy_but_true_threshold_only_counts"
        elif has_runtime_proxy_lineage and selected_from_true_threshold:
            audit_status = "WARN"
            reason = "selected_trial_true_threshold_but_runtime_proxy_only_counts"
        else:
            audit_status = "WARN"
            reason = "selected_trial_lineage_unresolved"

        return {
            "available": bool(selection_rule_counts or selected_trial_summary),
            "audit_status": audit_status,
            "reason": reason,
            "lineage_mix_state": lineage_mix_state,
            "runtime_proxy_trial_count": runtime_proxy_trials,
            "true_threshold_trial_count": true_threshold_trials,
            "has_runtime_proxy_lineage": has_runtime_proxy_lineage,
            "has_true_threshold_lineage": has_true_threshold_lineage,
            "selected_trial_writer_source": (
                str(selected_trial_summary.get("writer_source") or "unknown") if selected_trial_summary else "unknown"
            ),
            "selected_trial_selection_rule": (
                str(selected_trial_summary.get("selection_rule") or "") if selected_trial_summary else ""
            ),
            "selected_trial_from_runtime_proxy": selected_from_runtime_proxy,
            "selected_trial_from_true_threshold": selected_from_true_threshold,
        }

    @staticmethod
    def _apply_lineage_audit_to_recommendation(
        *,
        recommendation: dict[str, Any],
        lineage_audit: dict[str, Any],
        metrics_complete: bool,
    ) -> dict[str, Any]:
        updated = dict(recommendation)
        base_decision = str(updated.get("decision", "not_ready"))
        base_reason = str(updated.get("reason", "not_available"))
        lineage_status = str(lineage_audit.get("audit_status", "WARN"))
        lineage_reason = str(lineage_audit.get("reason", "not_available"))

        updated["baseline_decision"] = base_decision
        updated["baseline_reason"] = base_reason
        updated["lineage_audit_applied"] = bool(metrics_complete and lineage_status == "WARN")
        updated["lineage_audit_status"] = lineage_status
        updated["lineage_audit_reason"] = lineage_reason
        updated["selected_trial_writer_source"] = lineage_audit.get("selected_trial_writer_source", "unknown")
        updated["selected_trial_selection_rule"] = lineage_audit.get("selected_trial_selection_rule", "")

        if not metrics_complete or lineage_status != "WARN":
            return updated
        if base_decision == "pass_minimum_gate":
            updated["decision"] = "warn_lineage_audit"
            updated["reason"] = lineage_reason
        elif base_decision == "warn_overfit_risk":
            updated["decision"] = "warn_overfit_and_lineage_audit"
            updated["reason"] = f"{base_reason};{lineage_reason}"
        return updated

    def _snapshot_row(
        self,
        *,
        symbol: str,
        version: str,
        now: datetime,
        trial_runs: list[ValidationTrialRun],
        fold_scores: list[ValidationTrialFoldScore],
        selected_trial: ValidationTrialRun | None,
        pbo: dict[str, Any],
        dsr: dict[str, Any],
        selection_universe_summary: dict[str, Any],
    ) -> ValidationPboDsrSnapshot:
        selection_universe_size = None
        if selection_universe_summary.get("dsr_selection_universe_size") is not None:
            selection_universe_size = int(selection_universe_summary["dsr_selection_universe_size"])
        elif dsr.get("selection_universe_size") is not None:
            selection_universe_size = int(dsr["selection_universe_size"])
        elif selected_trial and selected_trial.selection_universe_size is not None:
            selection_universe_size = int(selected_trial.selection_universe_size)
        computation_state = "not_computed"
        if bool(pbo.get("available")) and bool(dsr.get("available")):
            computation_state = "metrics_computed"
        elif bool(pbo.get("available")) or bool(dsr.get("available")):
            computation_state = "partial_metrics_computed"
        payload = {
            "pbo_status": pbo.get("status"),
            "pbo_reason": pbo.get("reason"),
            "pbo_eligible_folds": pbo.get("eligible_folds"),
            "pbo_overfit_folds": pbo.get("overfit_folds"),
            "selected_rank_percentile_avg": pbo.get("selected_rank_percentile_avg"),
            "dsr_status": dsr.get("status"),
            "dsr_reason": dsr.get("reason"),
            "dsr_probability": dsr.get("probability"),
            "selected_trial_sharpe": dsr.get("selected_trial_sharpe"),
            "benchmark_sharpe": dsr.get("benchmark_sharpe"),
            "sample_size": dsr.get("sample_size"),
            "selected_trial": self._selected_trial_summary(selected_trial),
            "selection_universe_summary": dict(selection_universe_summary or {}),
        }
        return ValidationPboDsrSnapshot(
            snapshot_id=f"{symbol}_{version}_{now.strftime('%Y%m%dT%H%M%SZ')}",
            symbol=symbol,
            strategy_version=version,
            selected_trial_run_id=str(selected_trial.trial_run_id) if selected_trial is not None else None,
            trial_run_count=len(trial_runs),
            fold_score_count=len(fold_scores),
            selection_universe_size=selection_universe_size,
            pbo_value=self._safe_float(pbo.get("value")),
            dsr_value=self._safe_float(dsr.get("value")),
            pbo_available=bool(pbo.get("available")),
            dsr_available=bool(dsr.get("available")),
            computation_state=computation_state,
            payload=payload,
        )

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.validation_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / (
            f"strategy_v2_pbo_dsr_metrics_{payload['symbol']}_{payload['version']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        )
        pbo = dict(payload.get("pbo") or {})
        dsr = dict(payload.get("dsr") or {})
        recommendation = dict(payload.get("deployment_recommendation") or {})
        selected_trial = dict(payload.get("selected_trial") or {})
        lineage_audit = dict(payload.get("lineage_audit") or {})
        selection_universe_summary = dict(payload.get("selection_universe_summary") or {})
        lines = [
            f"# Strategy v2 PBO / DSR Metrics: {payload['symbol']}",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- strategy_version: {payload['version']}",
            f"- available: {payload['available']}",
            f"- metrics_complete: {payload['metrics_complete']}",
            f"- reason: {payload['reason']}",
            "",
            "## Executive Summary",
            f"- decision: {recommendation.get('decision', 'not_ready')}",
            f"- meets_protocol_gate: {recommendation.get('meets_protocol_gate', False)}",
            f"- recommendation_reason: {recommendation.get('reason', 'not_available')}",
            f"- trial_runs: {int((payload.get('sample_counts') or {}).get('trial_runs', 0))}",
            f"- fold_scores: {int((payload.get('sample_counts') or {}).get('fold_scores', 0))}",
            f"- eligible_pbo_folds: {int((payload.get('sample_counts') or {}).get('eligible_pbo_folds', 0))}",
            "",
            "## Selected Trial",
        ]
        if selected_trial:
            lines.extend(
                [
                    f"- trial_run_id: {selected_trial.get('trial_run_id')}",
                    f"- parameter_family: {selected_trial.get('parameter_family')}",
                    f"- selection_rank: {selected_trial.get('selection_rank')}",
                    f"- out_of_sample_metric: {selected_trial.get('out_of_sample_metric')}",
                    f"- sharpe_like_score: {selected_trial.get('sharpe_like_score')}",
                    f"- selection_universe_size: {selected_trial.get('selection_universe_size')}",
                    f"- lineage_selection_universe_size: {selected_trial.get('lineage_selection_universe_size')}",
                    f"- selection_universe_basis: {selected_trial.get('selection_universe_basis')}",
                    (
                        "- full_parameter_sweep_selection_universe_size: "
                        f"{selected_trial.get('full_parameter_sweep_selection_universe_size')}"
                    ),
                    f"- writer_source: {selected_trial.get('writer_source', 'unknown')}",
                ]
            )
        else:
            lines.append("- none")
        lines.extend(
            [
                "",
                "## Selection Universe",
                f"- combined_artifact_selection_universe_size: {selection_universe_summary.get('combined_artifact_selection_universe_size')}",
                f"- runtime_proxy_selection_universe_size: {selection_universe_summary.get('runtime_proxy_selection_universe_size')}",
                f"- true_threshold_selection_universe_size: {selection_universe_summary.get('true_threshold_selection_universe_size')}",
                f"- full_parameter_sweep_selection_universe_size: {selection_universe_summary.get('full_parameter_sweep_selection_universe_size')}",
                f"- dsr_selection_universe_size: {selection_universe_summary.get('dsr_selection_universe_size')}",
                f"- dsr_selection_universe_basis: {selection_universe_summary.get('dsr_selection_universe_basis', 'combined_artifact_universe')}",
                f"- bias_adjustment_rechecked: {bool(selection_universe_summary.get('bias_adjustment_rechecked', False))}",
                f"- recording_status: {selection_universe_summary.get('recording_status', 'combined_only')}",
                "",
                "## Lineage Audit",
                f"- audit_status: {lineage_audit.get('audit_status', 'not_available')}",
                f"- reason: {lineage_audit.get('reason', 'not_available')}",
                f"- lineage_mix_state: {lineage_audit.get('lineage_mix_state', 'no_lineage')}",
                f"- runtime_proxy_trial_count: {int(lineage_audit.get('runtime_proxy_trial_count', 0) or 0)}",
                f"- true_threshold_trial_count: {int(lineage_audit.get('true_threshold_trial_count', 0) or 0)}",
                f"- selected_trial_from_runtime_proxy: {bool(lineage_audit.get('selected_trial_from_runtime_proxy', False))}",
                f"- selected_trial_from_true_threshold: {bool(lineage_audit.get('selected_trial_from_true_threshold', False))}",
                "",
                "## PBO",
                f"- available: {bool(pbo.get('available', False))}",
                f"- value: {pbo.get('value')}",
                f"- status: {pbo.get('status', 'not_available')}",
                f"- reason: {pbo.get('reason', 'not_available')}",
                f"- eligible_folds: {int(pbo.get('eligible_folds', 0) or 0)}",
                f"- overfit_folds: {int(pbo.get('overfit_folds', 0) or 0)}",
                f"- selected_rank_percentile_avg: {pbo.get('selected_rank_percentile_avg')}",
                "",
                "## DSR",
                f"- available: {bool(dsr.get('available', False))}",
                f"- value: {dsr.get('value')}",
                f"- probability: {dsr.get('probability')}",
                f"- status: {dsr.get('status', 'not_available')}",
                f"- reason: {dsr.get('reason', 'not_available')}",
                f"- selected_trial_sharpe: {dsr.get('selected_trial_sharpe')}",
                f"- benchmark_sharpe: {dsr.get('benchmark_sharpe')}",
                f"- sample_size: {dsr.get('sample_size')}",
                f"- selection_universe_size: {dsr.get('selection_universe_size')}",
                f"- selection_universe_basis: {dsr.get('selection_universe_basis', 'combined_artifact_universe')}",
                f"- legacy_combined_selection_universe_size: {dsr.get('legacy_combined_selection_universe_size')}",
                f"- legacy_combined_benchmark_sharpe: {dsr.get('legacy_combined_benchmark_sharpe')}",
                (
                    "- benchmark_sharpe_delta_vs_legacy_combined: "
                    f"{dsr.get('benchmark_sharpe_delta_vs_legacy_combined')}"
                ),
                "",
                "## Blockers",
            ]
        )
        for item in payload.get("blocked_by", []):
            lines.append(f"- {item}")
        lines.extend(["", "## Next Steps"])
        for item in payload.get("next_steps", []):
            lines.append(f"- {item}")
        lines.extend(
            [
                "",
                "## Notes",
                "- PBO is currently computed as the fraction of CSCV folds where the selected trial lands in the worse half out-of-sample.",
                "- DSR is currently emitted as a signed deflated-Sharpe score plus a Normal CDF probability for interpretation.",
                "",
            ]
        )
        file_path.write_text("\n".join(lines), encoding="utf-8")
        return str(file_path)

    def generate(
        self,
        *,
        symbol: str,
        version: str,
        write_report: bool = True,
        persist_snapshot: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        if self.repo is None:
            raise RuntimeError("ValidationArtifactRepository is required")

        self.repo.db.flush()
        trial_runs = self.repo.list_trial_runs(symbol=symbol, version=version, limit=5000)
        fold_scores = self.repo.list_fold_scores(symbol=symbol, version=version, limit=20000)
        selection_rule_counts = self.repo.selection_rule_counts(symbol=symbol, version=version)
        selected_trial = self._selected_trial(trial_runs)
        selected_trial_summary = self._selected_trial_summary(selected_trial)
        selected_trial_run_id = str(selected_trial.trial_run_id) if selected_trial is not None else None
        selected_trial_fold_scores = [
            row for row in fold_scores if selected_trial_run_id and str(row.trial_run_id) == selected_trial_run_id
        ]
        eligible_trial_runs = [row for row in trial_runs if row.out_of_sample_metric is not None]

        pbo = self._compute_pbo(
            fold_scores=fold_scores,
            selected_trial_run_id=selected_trial_run_id,
        )
        dsr = self._compute_dsr(
            selected_trial=selected_trial,
            selected_trial_fold_scores=selected_trial_fold_scores,
            eligible_trial_count=len(eligible_trial_runs),
            selection_rule_counts=selection_rule_counts,
        )

        blocked_by: list[str] = []
        next_steps: list[str] = []
        if not trial_runs:
            blocked_by.append("validation_trial_runs is empty")
            next_steps.append("run validation/report after enough eligible closed v2 trades or connect threshold-sweep trial writer")
        if not fold_scores:
            blocked_by.append("validation_trial_fold_scores is empty")
            next_steps.append("write CSCV fold scores into validation_trial_fold_scores")
        if not pbo.get("available"):
            blocked_by.append(str(pbo.get("reason") or "pbo_unavailable"))
        if not dsr.get("available"):
            blocked_by.append(str(dsr.get("reason") or "dsr_unavailable"))
        if pbo.get("available") and dsr.get("available"):
            next_steps.append("compare computed PBO/DSR against validation protocol thresholds")
        else:
            next_steps.append("complete seeded trial/fold lineage so PBO and DSR can both compute")
        blocked_by = list(dict.fromkeys(blocked_by))
        next_steps = list(dict.fromkeys(next_steps))

        metrics_complete = bool(pbo.get("available")) and bool(dsr.get("available"))
        available = bool(pbo.get("available")) or bool(dsr.get("available"))
        if metrics_complete:
            reason = "pbo_dsr_metrics_computed"
        elif available:
            reason = "pbo_dsr_metrics_partially_computed"
        elif not trial_runs:
            reason = "pbo_dsr_trial_runs_missing"
        else:
            reason = "pbo_dsr_inputs_incomplete"

        pbo_value = self._safe_float(pbo.get("value"))
        dsr_value = self._safe_float(dsr.get("value"))
        meets_protocol_gate = (
            metrics_complete
            and pbo_value is not None
            and dsr_value is not None
            and float(pbo_value) < 0.35
            and float(dsr_value) > 0.0
        )
        if not metrics_complete:
            recommendation = {
                "decision": "not_ready",
                "meets_protocol_gate": False,
                "reason": reason,
            }
        elif not meets_protocol_gate:
            recommendation = {
                "decision": "fail_validation_gate",
                "meets_protocol_gate": False,
                "reason": f"pbo_status={pbo.get('status', 'FAIL')},dsr_status={dsr.get('status', 'FAIL')}",
            }
        elif str(pbo.get("status")) == "WARN":
            recommendation = {
                "decision": "warn_overfit_risk",
                "meets_protocol_gate": True,
                "reason": "pbo_warn_threshold",
            }
        else:
            recommendation = {
                "decision": "pass_minimum_gate",
                "meets_protocol_gate": True,
                "reason": "pbo_pass_dsr_positive",
            }
        lineage_audit = self._lineage_audit(
            selection_rule_counts=selection_rule_counts,
            selected_trial_summary=selected_trial_summary,
        )
        selection_universe_summary = self._selection_universe_summary(
            selection_rule_counts=selection_rule_counts,
            eligible_trial_count=len(eligible_trial_runs),
            selected_trial_summary=selected_trial_summary,
            dsr_selection_universe_size=self._safe_int(dsr.get("selection_universe_size")),
            dsr_selection_universe_basis=str(dsr.get("selection_universe_basis") or ""),
        )
        recommendation = self._apply_lineage_audit_to_recommendation(
            recommendation=recommendation,
            lineage_audit=lineage_audit,
            metrics_complete=metrics_complete,
        )
        if metrics_complete and str(lineage_audit.get("audit_status")) == "WARN":
            next_steps.append("audit proxy lineage vs true threshold lineage before deployment approval")
            next_steps = list(dict.fromkeys(next_steps))

        snapshot_summary = None
        if persist_snapshot and trial_runs:
            snapshot_row = self._snapshot_row(
                symbol=symbol,
                version=version,
                now=now,
                trial_runs=trial_runs,
                fold_scores=fold_scores,
                selected_trial=selected_trial,
                pbo=pbo,
                dsr=dsr,
                selection_universe_summary=selection_universe_summary,
            )
            self.repo.upsert_snapshot(snapshot_row)
            snapshot_summary = {
                "snapshot_id": snapshot_row.snapshot_id,
                "computation_state": snapshot_row.computation_state,
                "pbo_available": bool(snapshot_row.pbo_available),
                "dsr_available": bool(snapshot_row.dsr_available),
            }

        payload: dict[str, Any] = {
            "schema_version": "strategy_v2_pbo_dsr_metrics_v1",
            "symbol": symbol,
            "version": version,
            "generated_at": now.isoformat(),
            "available": available,
            "metrics_complete": metrics_complete,
            "reason": reason,
            "evaluation_basis": "seeded_validation_artifacts",
            "sample_counts": {
                "trial_runs": len(trial_runs),
                "eligible_trial_runs": len(eligible_trial_runs),
                "fold_scores": len(fold_scores),
                "eligible_pbo_folds": int(pbo.get("eligible_folds", 0) or 0),
                "selected_trial_fold_scores": len(selected_trial_fold_scores),
            },
            "selection_rule_counts": selection_rule_counts,
            "selection_universe_summary": selection_universe_summary,
            "selected_trial": selected_trial_summary,
            "lineage_audit": lineage_audit,
            "pbo": pbo,
            "dsr": dsr,
            "snapshot_summary": snapshot_summary,
            "blocked_by": blocked_by,
            "next_steps": next_steps,
            "deployment_recommendation": recommendation,
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload
