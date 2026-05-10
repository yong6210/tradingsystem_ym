from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.enums import StrategyMode
from app.db.models import ValidationTrialFoldScore, ValidationTrialRun
from app.db.repositories import ValidationArtifactRepository
from app.services.report_io import atomic_write_text
from app.services.strategy_v2_lock_validation import StrategyV2LockValidationService
from app.services.strategy_v2_stress_validation import StrategyV2StressValidationService
from app.services.strategy_v2_validation import ClosedTradeRecord, StrategyV2ValidationService


@dataclass(slots=True)
class _RuntimeTrialSeries:
    trial_key: str
    parameter_family: str
    parameter_values: dict[str, Any]
    closed_trades: list[ClosedTradeRecord]
    returns: list[float]
    payload: dict[str, Any]


class StrategyV2PboDsrTrialWriterService:
    _SELECTION_RULE = "runtime_validation_proxy_top_in_sample_ev"
    _WRITER_SOURCE = "runtime_validation_proxy_v1"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        repo: ValidationArtifactRepository | None = None,
        fill_repo: Any | None = None,
        candle_repo: Any | None = None,
    ):
        self.settings = settings or get_settings()
        self.repo = repo
        self._base = StrategyV2ValidationService(self.settings)
        self._lock = StrategyV2LockValidationService(self.settings)
        self._stress = StrategyV2StressValidationService(
            self.settings,
            fill_repo=fill_repo,
            candle_repo=candle_repo,
        )

    @staticmethod
    def _safe_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return bool(default)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value) if math.isfinite(float(value)) else bool(default)
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
        return bool(default)

    @staticmethod
    def _round(value: float, digits: int = 6) -> float:
        return round(float(value), digits)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        if value in (None, "", "None"):
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if math.isfinite(parsed) else default

    @staticmethod
    def _mean(values: list[float]) -> float:
        if not values:
            return 0.0
        return float(sum(float(value) for value in values) / len(values))

    @classmethod
    def _stdev(cls, values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = cls._mean(values)
        variance = sum((float(value) - mean) ** 2 for value in values) / float(len(values) - 1)
        return math.sqrt(max(variance, 0.0))

    @classmethod
    def _sharpe_like(cls, values: list[float]) -> float:
        if not values:
            return 0.0
        mean = cls._mean(values)
        stdev = cls._stdev(values)
        if stdev <= 1e-9:
            return mean * math.sqrt(float(len(values)))
        return (mean / stdev) * math.sqrt(float(len(values)))

    @classmethod
    def _skew_kurtosis(cls, values: list[float]) -> tuple[float, float]:
        if len(values) < 3:
            return 0.0, 3.0
        mean = cls._mean(values)
        centered = [float(value) - mean for value in values]
        m2 = sum(value**2 for value in centered) / len(centered)
        if m2 <= 1e-12:
            return 0.0, 3.0
        m3 = sum(value**3 for value in centered) / len(centered)
        m4 = sum(value**4 for value in centered) / len(centered)
        skew = m3 / (m2 ** 1.5)
        kurtosis = m4 / (m2**2)
        return float(skew), float(kurtosis)

    @staticmethod
    def _sanitize(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        return normalized[:48] or "trial"

    @classmethod
    def _trial_run_id(cls, *, symbol: str, version: str, trial_key: str) -> str:
        namespace = cls._sanitize(getattr(cls, "_WRITER_SOURCE", "") or getattr(cls, "_SELECTION_RULE", "trial"))
        trial_part = cls._sanitize(trial_key)
        digest = hashlib.sha1(f"{namespace}:{trial_key}".encode("utf-8")).hexdigest()[:10]
        prefix = f"{symbol}_{version}_{namespace}_"
        available = max(8, 80 - len(prefix) - len(digest) - 1)
        return f"{prefix}{trial_part[:available]}_{digest}"[:80]

    def _closed_plan_pairs(self, *, plans: list[Any], symbol: str, version: str) -> list[tuple[Any, ClosedTradeRecord]]:
        rows: list[tuple[Any, ClosedTradeRecord]] = []
        for plan in plans:
            record = self._base._closed_trade(plan, symbol=symbol, version=version)
            if record is None:
                continue
            rows.append((plan, record))
        rows.sort(key=lambda item: item[1].closed_ts)
        return rows

    @staticmethod
    def _series(
        *,
        trial_key: str,
        parameter_family: str,
        parameter_values: dict[str, Any],
        closed_trades: list[ClosedTradeRecord],
        returns: list[float],
        payload: dict[str, Any],
    ) -> _RuntimeTrialSeries | None:
        if not closed_trades or not returns or len(closed_trades) != len(returns):
            return None
        ordered = sorted(zip(closed_trades, returns, strict=True), key=lambda item: item[0].closed_ts)
        return _RuntimeTrialSeries(
            trial_key=trial_key,
            parameter_family=parameter_family,
            parameter_values=parameter_values,
            closed_trades=[item[0] for item in ordered],
            returns=[float(item[1]) for item in ordered],
            payload=payload,
        )

    def _mode_trials(self, *, plan_pairs: list[tuple[Any, ClosedTradeRecord]]) -> list[_RuntimeTrialSeries]:
        records = [record for _, record in plan_pairs]
        trials: list[_RuntimeTrialSeries] = []
        for mode in (StrategyMode.A_ONLY, StrategyMode.A_PLUS_B):
            subset = self._base._subset_for_mode(records, mode=mode)
            trial = self._series(
                trial_key=f"mode_policy:{mode.value}",
                parameter_family="mode_policy",
                parameter_values={"mode": mode.value},
                closed_trades=subset,
                returns=[float(record.realized_r) for record in subset],
                payload={
                    "source": "strategy_v2_validation",
                    "variant": mode.value,
                    "approximation": "runtime_validation_proxy",
                },
            )
            if trial is not None:
                trials.append(trial)
        return trials

    def _lock_trials(self, *, plan_pairs: list[tuple[Any, ClosedTradeRecord]]) -> list[_RuntimeTrialSeries]:
        before_records = [record for _, record in plan_pairs]
        after_records: list[ClosedTradeRecord] = []
        blocked_counts: dict[str, int] = {}
        for plan, record in plan_pairs:
            adjusted, blocked_reason = self._lock._adjust_trade(plan, record)
            if blocked_reason:
                blocked_counts[blocked_reason] = int(blocked_counts.get(blocked_reason, 0)) + 1
                continue
            if adjusted is None:
                continue
            after_records.append(
                ClosedTradeRecord(
                    plan_id=adjusted.base.plan_id,
                    symbol=adjusted.base.symbol,
                    closed_ts=adjusted.base.closed_ts,
                    realized_r=float(adjusted.adjusted_realized_r),
                    held_bars=adjusted.base.held_bars,
                    exit_reason=adjusted.base.exit_reason,
                    regime=adjusted.base.regime,
                    strategy_family=adjusted.base.strategy_family,
                    strategy_grade=adjusted.base.strategy_grade,
                    strategy_version=adjusted.base.strategy_version,
                )
            )
        trials: list[_RuntimeTrialSeries] = []
        before_trial = self._series(
            trial_key="lock_policy:before_lock",
            parameter_family="lock_policy",
            parameter_values={"lock_policy": "before_lock"},
            closed_trades=before_records,
            returns=[float(record.realized_r) for record in before_records],
            payload={
                "source": "strategy_v2_lock_validation",
                "variant": "before_lock",
                "approximation": "runtime_validation_proxy",
                "blocked_counts": dict(sorted(blocked_counts.items())),
            },
        )
        after_trial = self._series(
            trial_key="lock_policy:after_lock",
            parameter_family="lock_policy",
            parameter_values={"lock_policy": "after_lock"},
            closed_trades=after_records,
            returns=[float(record.realized_r) for record in after_records],
            payload={
                "source": "strategy_v2_lock_validation",
                "variant": "after_lock",
                "approximation": "runtime_validation_proxy",
                "blocked_counts": dict(sorted(blocked_counts.items())),
            },
        )
        if before_trial is not None:
            trials.append(before_trial)
        if after_trial is not None:
            trials.append(after_trial)
        return trials

    def _stress_trials(self, *, plan_pairs: list[tuple[Any, ClosedTradeRecord]]) -> list[_RuntimeTrialSeries]:
        plans = [plan for plan, _ in plan_pairs]
        fill_map = self._stress._fill_map(plans)
        adjusted = []
        for plan, record in plan_pairs:
            adjusted.append(
                self._stress._adjust_trade(
                    plan=plan,
                    record=record,
                    fills=fill_map.get(record.plan_id, []),
                )
            )

        variant_map = {
            "baseline_cost": lambda row: float(row.baseline_adjusted_r),
            "stressed_cost": lambda row: float(row.stressed_adjusted_r),
            "latency_plus_1_bar": lambda row: float(row.latency_plus_1_bar_adjusted_r),
            "partial_fills_only": lambda row: float(row.partial_fills_only_adjusted_r),
            "shock_concentration": lambda row: float(row.shock_concentration_adjusted_r),
        }
        trials: list[_RuntimeTrialSeries] = []
        for variant, resolver in variant_map.items():
            closed_trades = [
                ClosedTradeRecord(
                    plan_id=row.base.plan_id,
                    symbol=row.base.symbol,
                    closed_ts=row.base.closed_ts,
                    realized_r=resolver(row),
                    held_bars=row.base.held_bars,
                    exit_reason=row.base.exit_reason,
                    regime=row.base.regime,
                    strategy_family=row.base.strategy_family,
                    strategy_grade=row.base.strategy_grade,
                    strategy_version=row.base.strategy_version,
                )
                for row in adjusted
            ]
            trial = self._series(
                trial_key=f"stress_policy:{variant}",
                parameter_family="stress_policy",
                parameter_values={"stress_variant": variant},
                closed_trades=closed_trades,
                returns=[float(record.realized_r) for record in closed_trades],
                payload={
                    "source": "strategy_v2_stress_validation",
                    "variant": variant,
                    "approximation": "runtime_validation_proxy",
                },
            )
            if trial is not None:
                trials.append(trial)
        return trials

    @staticmethod
    def _validity(plan: Any) -> dict[str, Any]:
        return dict(getattr(plan, "validity", {}) or {})

    def _scoring_threshold_trials(self, *, plan_pairs: list[tuple[Any, ClosedTradeRecord]]) -> list[_RuntimeTrialSeries]:
        if not plan_pairs:
            return []
        settings = self.settings
        min_confluence_score = self._safe_float(settings.min_confluence_score, 62.0)
        thresholds = sorted(
            {
                max(0.0, min_confluence_score - 4.0),
                min_confluence_score,
                min_confluence_score + 4.0,
            }
        )
        trials: list[_RuntimeTrialSeries] = []
        for threshold in thresholds:
            subset = [
                record
                for plan, record in plan_pairs
                if float(self._validity(plan).get("confluence_score", 0.0) or 0.0) >= float(threshold)
            ]
            trial = self._series(
                trial_key=f"scoring_thresholds:confluence_gte_{self._sanitize(str(threshold))}",
                parameter_family="scoring_thresholds",
                parameter_values={"confluence_score_min": float(threshold)},
                closed_trades=subset,
                returns=[float(record.realized_r) for record in subset],
                payload={
                    "source": "threshold_sweep_proxy",
                    "variant": f"confluence_gte_{threshold}",
                    "approximation": "stored_plan_validity_filter",
                },
            )
            if trial is not None:
                trials.append(trial)
        return trials

    def _transition_threshold_trials(self, *, plan_pairs: list[tuple[Any, ClosedTradeRecord]]) -> list[_RuntimeTrialSeries]:
        if not plan_pairs:
            return []
        settings = self.settings
        transition_watch_score = self._safe_float(settings.transition_watch_score, 40.0)
        transition_confirmed_score = self._safe_float(settings.transition_confirmed_score, 55.0)
        thresholds = sorted(
            {
                max(0.0, transition_watch_score - 5.0),
                transition_watch_score,
                transition_watch_score + 5.0,
            }
        )
        trials: list[_RuntimeTrialSeries] = []
        for threshold in thresholds:
            subset = [
                record
                for plan, record in plan_pairs
                if float(self._validity(plan).get("transition_score", 0.0) or 0.0) < float(threshold)
            ]
            trial = self._series(
                trial_key=f"transition_threshold:max_transition_score_lt_{self._sanitize(str(threshold))}",
                parameter_family="transition_threshold",
                parameter_values={
                    "max_transition_score": float(threshold),
                    "transition_confirmed_score": transition_confirmed_score,
                },
                closed_trades=subset,
                returns=[float(record.realized_r) for record in subset],
                payload={
                    "source": "threshold_sweep_proxy",
                    "variant": f"max_transition_score_lt_{threshold}",
                    "approximation": "stored_transition_score_filter",
                },
            )
            if trial is not None:
                trials.append(trial)
        return trials

    @classmethod
    def _reaction_score_for_plan(cls, plan: Any) -> tuple[str, float]:
        validity = cls._validity(plan)
        classification = str(validity.get("reaction_classification", "unknown") or "unknown")
        if classification.startswith("rejection"):
            return classification, cls._safe_float(validity.get("reaction_rejection_score", 0.0))
        if classification.startswith("acceptance"):
            return classification, cls._safe_float(validity.get("reaction_acceptance_score", 0.0))
        return classification, 0.0

    def _acceptance_rejection_threshold_trials(
        self,
        *,
        plan_pairs: list[tuple[Any, ClosedTradeRecord]],
    ) -> list[_RuntimeTrialSeries]:
        if not plan_pairs:
            return []
        settings = self.settings

        def passes(plan: Any, variant: str) -> bool:
            classification, score = self._reaction_score_for_plan(plan)
            if classification.startswith("rejection"):
                confirmed = self._safe_float(settings.reaction_classifier_rejection_confirmed_score, 75.0)
                tentative = self._safe_float(settings.reaction_classifier_rejection_tentative_score, 60.0)
            elif classification.startswith("acceptance"):
                confirmed = self._safe_float(settings.reaction_classifier_acceptance_confirmed_score, 70.0)
                tentative = self._safe_float(settings.reaction_classifier_acceptance_tentative_score, 55.0)
            else:
                return False
            if variant == "tentative_enabled":
                return classification.endswith("confirmed") or (
                    classification.endswith("tentative") and score >= tentative
                )
            if variant == "confirmed_only":
                return classification.endswith("confirmed") and score >= confirmed
            if variant == "strict_confirmed":
                return classification.endswith("confirmed") and score >= (confirmed + 5.0)
            return False

        variants = ("tentative_enabled", "confirmed_only", "strict_confirmed")
        trials: list[_RuntimeTrialSeries] = []
        for variant in variants:
            subset = [record for plan, record in plan_pairs if passes(plan, variant)]
            trial = self._series(
                trial_key=f"acceptance_rejection_thresholds:{variant}",
                parameter_family="acceptance_rejection_thresholds",
                parameter_values={
                    "variant": variant,
                    "rejection_confirmed_score": self._safe_float(settings.reaction_classifier_rejection_confirmed_score, 75.0),
                    "rejection_tentative_score": self._safe_float(settings.reaction_classifier_rejection_tentative_score, 60.0),
                    "acceptance_confirmed_score": self._safe_float(settings.reaction_classifier_acceptance_confirmed_score, 70.0),
                    "acceptance_tentative_score": self._safe_float(settings.reaction_classifier_acceptance_tentative_score, 55.0),
                },
                closed_trades=subset,
                returns=[float(record.realized_r) for record in subset],
                payload={
                    "source": "threshold_sweep_proxy",
                    "variant": variant,
                    "approximation": "stored_reaction_scores_filter",
                },
            )
            if trial is not None:
                trials.append(trial)
        return trials

    def _sizing_clamp_trials(self, *, plan_pairs: list[tuple[Any, ClosedTradeRecord]]) -> list[_RuntimeTrialSeries]:
        if not plan_pairs:
            return []
        settings = self.settings
        caps = [
            self._safe_float(settings.sizing_grade_a_r, 1.0),
            self._safe_float(settings.sizing_grade_b_r, 0.5),
            self._safe_float(settings.sizing_grade_c_r, 0.25),
        ]
        trials: list[_RuntimeTrialSeries] = []
        for cap in sorted(set(caps), reverse=True):
            closed_trades: list[ClosedTradeRecord] = []
            returns: list[float] = []
            for plan, record in plan_pairs:
                validity = self._validity(plan)
                recommended = self._safe_float(validity.get("recommended_risk_r", 0.0))
                if recommended <= 0.0:
                    continue
                factor = min(recommended, float(cap)) / recommended
                closed_trades.append(record)
                returns.append(float(record.realized_r) * float(factor))
            trial = self._series(
                trial_key=f"sizing_clamps:max_risk_r_{self._sanitize(str(cap))}",
                parameter_family="sizing_clamps",
                parameter_values={"max_risk_r": float(cap)},
                closed_trades=closed_trades,
                returns=returns,
                payload={
                    "source": "threshold_sweep_proxy",
                    "variant": f"max_risk_r_{cap}",
                    "approximation": "recommended_risk_r_scaling",
                },
            )
            if trial is not None:
                trials.append(trial)
        return trials

    def _candidate_trials(self, *, plans: list[Any], symbol: str, version: str) -> tuple[list[_RuntimeTrialSeries], int]:
        plan_pairs = self._closed_plan_pairs(plans=plans, symbol=symbol, version=version)
        trials = [
            *self._mode_trials(plan_pairs=plan_pairs),
            *self._lock_trials(plan_pairs=plan_pairs),
            *self._stress_trials(plan_pairs=plan_pairs),
            *self._scoring_threshold_trials(plan_pairs=plan_pairs),
            *self._transition_threshold_trials(plan_pairs=plan_pairs),
            *self._acceptance_rejection_threshold_trials(plan_pairs=plan_pairs),
            *self._sizing_clamp_trials(plan_pairs=plan_pairs),
        ]
        return trials, len(plan_pairs)

    def _global_fold_count(self, trials: list[_RuntimeTrialSeries]) -> int:
        min_trades = int(max(1, self.settings.pbo_dsr_trial_writer_min_trades_per_fold))
        target_folds = int(max(2, self.settings.pbo_dsr_trial_writer_target_folds))
        eligible_lengths = [len(trial.returns) for trial in trials if len(trial.returns) >= min_trades * 2]
        if len(eligible_lengths) < 2:
            return 0
        return max(0, min(target_folds, min(eligible_lengths) // min_trades))

    @staticmethod
    def _partition(n: int, fold_count: int) -> list[tuple[int, int]]:
        base = n // fold_count
        remainder = n % fold_count
        cursor = 0
        out: list[tuple[int, int]] = []
        for idx in range(fold_count):
            width = base + (1 if idx < remainder else 0)
            out.append((cursor, cursor + width))
            cursor += width
        return out

    def _build_rows(
        self,
        *,
        symbol: str,
        version: str,
        trials: list[_RuntimeTrialSeries],
        fold_count: int,
    ) -> tuple[list[ValidationTrialRun], list[ValidationTrialFoldScore], dict[str, Any]]:
        fold_metrics_by_trial: dict[str, list[dict[str, Any]]] = {}
        for trial in trials:
            bounds = self._partition(len(trial.returns), fold_count)
            rows: list[dict[str, Any]] = []
            for fold_index, (start, end) in enumerate(bounds, start=1):
                oos = trial.returns[start:end]
                ins = trial.returns[:start] + trial.returns[end:]
                rows.append(
                    {
                        "fold_id": f"fold_{fold_index:02d}",
                        "in_sample_metric": self._round(self._mean(ins), 6),
                        "out_of_sample_metric": self._round(self._mean(oos), 6),
                    }
                )
            fold_metrics_by_trial[trial.trial_key] = rows

        fold_rows: list[ValidationTrialFoldScore] = []
        by_fold: dict[str, list[dict[str, Any]]] = {}
        for trial in trials:
            trial_run_id = self._trial_run_id(symbol=symbol, version=version, trial_key=trial.trial_key)
            for row in fold_metrics_by_trial[trial.trial_key]:
                by_fold.setdefault(str(row["fold_id"]), []).append(
                    {
                        "trial_run_id": trial_run_id,
                        "trial_key": trial.trial_key,
                        "parameter_family": trial.parameter_family,
                        "parameter_values": dict(trial.parameter_values),
                        "in_sample_metric": float(row["in_sample_metric"]),
                        "out_of_sample_metric": float(row["out_of_sample_metric"]),
                    }
                )

        for fold_id, entries in sorted(by_fold.items()):
            entries.sort(
                key=lambda item: (
                    -float(item["in_sample_metric"]),
                    -float(item["out_of_sample_metric"]),
                    str(item["trial_run_id"]),
                )
            )
            for index, entry in enumerate(entries, start=1):
                fold_rows.append(
                    ValidationTrialFoldScore(
                        trial_run_id=str(entry["trial_run_id"]),
                        symbol=symbol,
                        strategy_version=version,
                        fold_id=fold_id,
                        selected_flag=index == 1,
                        selection_rank=index,
                        in_sample_metric=float(entry["in_sample_metric"]),
                        out_of_sample_metric=float(entry["out_of_sample_metric"]),
                        payload={
                            "writer_source": self._WRITER_SOURCE,
                            "parameter_family": entry["parameter_family"],
                            "parameter_values": entry["parameter_values"],
                        },
                    )
                )

        trial_summaries: list[dict[str, Any]] = []
        selection_universe_basis = (
            "true_threshold_sweep_lineage"
            if str(self._SELECTION_RULE).startswith("true_threshold_sweep")
            else "runtime_proxy_hybrid_lineage"
        )
        full_parameter_sweep_selection_universe_size = (
            len(trials) if str(self._SELECTION_RULE).startswith("true_threshold_sweep") else None
        )
        for trial in trials:
            trial_run_id = self._trial_run_id(symbol=symbol, version=version, trial_key=trial.trial_key)
            fold_rows_for_trial = fold_metrics_by_trial[trial.trial_key]
            mean_return = self._mean(trial.returns)
            sharpe_like = self._sharpe_like(trial.returns)
            skewness, kurtosis = self._skew_kurtosis(trial.returns)
            trial_summaries.append(
                {
                    "trial_run_id": trial_run_id,
                    "trial_key": trial.trial_key,
                    "parameter_family": trial.parameter_family,
                    "parameter_values": dict(trial.parameter_values),
                    "selection_rule": self._SELECTION_RULE,
                    "in_sample_metric": self._round(self._mean([row["in_sample_metric"] for row in fold_rows_for_trial]), 6),
                    "out_of_sample_metric": self._round(mean_return, 6),
                    "sharpe_like_score": self._round(sharpe_like, 6),
                    "trial_count": len(trial.returns),
                    "selection_universe_size": len(trials),
                    "payload": {
                        **dict(trial.payload),
                        "writer_source": self._WRITER_SOURCE,
                        "lineage_namespace": self._WRITER_SOURCE,
                        "fold_count": fold_count,
                        "trade_count": len(trial.returns),
                        "lineage_selection_universe_size": len(trials),
                        "selection_universe_basis": selection_universe_basis,
                        "full_parameter_sweep_selection_universe_size": full_parameter_sweep_selection_universe_size,
                        "sample_start_ts": trial.closed_trades[0].closed_ts.isoformat(),
                        "sample_end_ts": trial.closed_trades[-1].closed_ts.isoformat(),
                        "return_skewness": self._round(skewness, 6),
                        "return_kurtosis": self._round(kurtosis, 6),
                    },
                }
            )

        trial_summaries.sort(
            key=lambda item: (
                -float(item["in_sample_metric"]),
                -float(item["out_of_sample_metric"]),
                str(item["trial_run_id"]),
            )
        )
        selected_trial_run_id = trial_summaries[0]["trial_run_id"] if trial_summaries else None
        trial_run_rows = [
            ValidationTrialRun(
                trial_run_id=str(item["trial_run_id"]),
                symbol=symbol,
                strategy_version=version,
                parameter_family=str(item["parameter_family"]),
                parameter_values=dict(item["parameter_values"]),
                selection_rule=str(item["selection_rule"]),
                selected_flag=index == 1,
                selection_rank=index,
                in_sample_metric=float(item["in_sample_metric"]),
                out_of_sample_metric=float(item["out_of_sample_metric"]),
                sharpe_like_score=float(item["sharpe_like_score"]),
                trial_count=int(item["trial_count"]),
                selection_universe_size=int(item["selection_universe_size"]),
                payload=dict(item["payload"]),
            )
            for index, item in enumerate(trial_summaries, start=1)
        ]
        trial_catalog = [
            {
                "trial_run_id": str(item["trial_run_id"]),
                "parameter_family": str(item["parameter_family"]),
                "parameter_values": dict(item["parameter_values"]),
                "selection_rank": index,
                "selected_flag": index == 1,
                "in_sample_metric": float(item["in_sample_metric"]),
                "out_of_sample_metric": float(item["out_of_sample_metric"]),
                "trial_count": int(item["trial_count"]),
            }
            for index, item in enumerate(trial_summaries, start=1)
        ]
        return trial_run_rows, fold_rows, {
            "selected_trial_run_id": selected_trial_run_id,
            "trial_catalog": trial_catalog[:20],
        }

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.validation_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / (
            f"strategy_v2_pbo_dsr_trial_writer_{payload['symbol']}_{payload['version']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        )
        lines = [
            f"# Strategy v2 PBO / DSR Trial Writer: {payload['symbol']}",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- strategy_version: {payload['version']}",
            f"- available: {payload['available']}",
            f"- implementation_status: {payload['implementation_status']}",
            f"- reason: {payload['reason']}",
            f"- evaluation_basis: {payload.get('evaluation_basis', 'runtime_validation_proxy')}",
            "",
            "## Executive Summary",
            f"- eligible_closed_trades: {int((payload.get('sample_counts') or {}).get('eligible_closed_trades', 0))}",
            f"- candidate_trials: {int((payload.get('sample_counts') or {}).get('candidate_trials', 0))}",
            f"- trial_runs_written: {int((payload.get('sample_counts') or {}).get('trial_runs_written', 0))}",
            f"- fold_scores_written: {int((payload.get('sample_counts') or {}).get('fold_scores_written', 0))}",
            f"- fold_count: {int((payload.get('sample_counts') or {}).get('fold_count', 0))}",
            f"- selected_trial_run_id: {payload.get('selected_trial_run_id')}",
            f"- selection_rule: {payload.get('selection_rule', self._SELECTION_RULE)}",
            f"- parameter_families_present: {payload.get('parameter_families_present', [])}",
            f"- threshold_parameter_families_present: {payload.get('threshold_parameter_families_present', [])}",
            f"- candidate_trials_by_family: {payload.get('candidate_trials_by_family', {})}",
            "",
            "## Trial Catalog",
        ]
        for item in list(payload.get("trial_catalog") or []):
            lines.append(
                f"- {item.get('trial_run_id')}: family={item.get('parameter_family')}, rank={item.get('selection_rank')}, "
                f"selected={item.get('selected_flag')}, in_sample={item.get('in_sample_metric')}, "
                f"out_of_sample={item.get('out_of_sample_metric')}, trades={item.get('trial_count')}"
            )
        lines.extend(["", "## Blockers"])
        for item in list(payload.get("blocked_by") or []):
            lines.append(f"- {item}")
        lines.extend(["", "## Next Steps"])
        for item in list(payload.get("next_steps") or []):
            lines.append(f"- {item}")
        lines.extend(
            [
                "",
                "## Notes",
                "- Current writer seeds both runtime validation proxies and stored-plan threshold-sweep proxy families.",
                "- Fold rows use contiguous time-order partitions and rank trials by in-sample mean EV inside each fold.",
                "- This writer is intended to close lineage between validation/report and the PBO/DSR artifact store.",
                "",
            ]
        )
        atomic_write_text(file_path, "\n".join(lines))
        return str(file_path)

    def generate(
        self,
        *,
        symbol: str,
        version: str,
        plans: list[Any],
        write_report: bool = True,
        persist: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        if self.repo is None:
            raise RuntimeError("ValidationArtifactRepository is required")

        if not self._safe_bool(self.settings.pbo_dsr_trial_writer_enabled):
            persist_summary = None
            if persist:
                persist_summary = self.repo.replace_seed_for_selection_rules(
                    symbol=symbol,
                    version=version,
                    selection_rules=[self._SELECTION_RULE],
                    trial_runs=[],
                    fold_scores=[],
                )
            payload = {
                "schema_version": "strategy_v2_pbo_dsr_trial_writer_v1",
                "symbol": symbol,
                "version": version,
                "generated_at": now.isoformat(),
                "available": False,
                "implementation_status": "runtime_validation_proxy_writer_disabled",
                "reason": "pbo_dsr_trial_writer_disabled",
                "evaluation_basis": "runtime_validation_proxy",
                "sample_counts": {
                    "eligible_closed_trades": 0,
                    "candidate_trials": 0,
                    "trial_runs_written": 0,
                    "fold_scores_written": 0,
                    "fold_count": 0,
                },
                "selection_rule": self._SELECTION_RULE,
                "selected_trial_run_id": None,
                "parameter_families_present": [],
                "threshold_parameter_families_present": [],
                "candidate_trials_by_family": {},
                "trial_catalog": [],
                "persist_summary": persist_summary,
                "blocked_by": ["pbo_dsr_trial_writer_enabled=false"],
                "next_steps": ["enable pbo_dsr_trial_writer and rerun validation/report"],
                "report_path": None,
            }
            if write_report:
                payload["report_path"] = self._write_report(payload=payload, now=now)
            return payload

        candidate_trials, eligible_closed_trade_count = self._candidate_trials(plans=plans, symbol=symbol, version=version)
        fold_count = self._global_fold_count(candidate_trials)
        blocked_by: list[str] = []
        next_steps: list[str] = []
        if eligible_closed_trade_count == 0:
            blocked_by.append("no eligible closed v2 trades for runtime proxy writer")
            next_steps.append("accumulate eligible closed v2 trades before seeding PBO/DSR proxy trials")
        if len(candidate_trials) < 2:
            blocked_by.append("runtime proxy writer produced fewer than 2 candidate trials")
            next_steps.append("keep mode/lock/stress validation axes populated so multiple proxy trials remain available")
        if fold_count < 2:
            blocked_by.append("insufficient contiguous samples to produce at least 2 folds")
            next_steps.append("increase closed-trade sample size or reduce minimum trades per fold")

        trial_rows: list[ValidationTrialRun] = []
        fold_rows: list[ValidationTrialFoldScore] = []
        selected_trial_run_id = None
        trial_catalog: list[dict[str, Any]] = []
        if len(candidate_trials) >= 2 and fold_count >= 2:
            trial_rows, fold_rows, summary = self._build_rows(
                symbol=symbol,
                version=version,
                trials=candidate_trials,
                fold_count=fold_count,
            )
            selected_trial_run_id = summary["selected_trial_run_id"]
            trial_catalog = list(summary["trial_catalog"])

        persist_summary = None
        if persist:
            persist_summary = self.repo.replace_seed_for_selection_rules(
                symbol=symbol,
                version=version,
                selection_rules=[self._SELECTION_RULE],
                trial_runs=trial_rows,
                fold_scores=fold_rows,
            )

        available = bool(trial_rows) and bool(fold_rows)
        if available:
            implementation_status = "runtime_validation_proxy_writer_seeded"
            reason = "pbo_dsr_runtime_proxy_writer_seeded"
            next_steps.append("review computed PBO/DSR metrics against protocol thresholds")
            next_steps.append("upgrade stored-plan threshold-sweep proxies to true parameter sweep runners when available")
        elif eligible_closed_trade_count == 0:
            implementation_status = "runtime_validation_proxy_writer_no_closed_trades"
            reason = "pbo_dsr_runtime_proxy_writer_no_closed_trades"
        elif len(candidate_trials) < 2:
            implementation_status = "runtime_validation_proxy_writer_insufficient_trials"
            reason = "pbo_dsr_runtime_proxy_writer_insufficient_trials"
        else:
            implementation_status = "runtime_validation_proxy_writer_insufficient_folds"
            reason = "pbo_dsr_runtime_proxy_writer_insufficient_folds"

        blocked_by = list(dict.fromkeys(blocked_by))
        next_steps = list(dict.fromkeys(next_steps))
        payload: dict[str, Any] = {
            "schema_version": "strategy_v2_pbo_dsr_trial_writer_v1",
            "symbol": symbol,
            "version": version,
            "generated_at": now.isoformat(),
            "available": available,
            "implementation_status": implementation_status,
            "reason": reason,
            "evaluation_basis": "closed_v2_trades + mode/lock/stress runtime proxies + stored-plan threshold-sweep proxies",
            "sample_counts": {
                "eligible_closed_trades": eligible_closed_trade_count,
                "candidate_trials": len(candidate_trials),
                "trial_runs_written": len(trial_rows),
                "fold_scores_written": len(fold_rows),
                "fold_count": fold_count,
            },
            "selection_rule": self._SELECTION_RULE,
            "selected_trial_run_id": selected_trial_run_id,
            "parameter_families_present": sorted({trial.parameter_family for trial in candidate_trials}),
            "threshold_parameter_families_present": sorted(
                {
                    trial.parameter_family
                    for trial in candidate_trials
                    if trial.parameter_family
                    in {
                        "scoring_thresholds",
                        "transition_threshold",
                        "acceptance_rejection_thresholds",
                        "sizing_clamps",
                    }
                }
            ),
            "candidate_trials_by_family": {
                family: sum(1 for trial in candidate_trials if trial.parameter_family == family)
                for family in sorted({trial.parameter_family for trial in candidate_trials})
            },
            "trial_catalog": trial_catalog,
            "persist_summary": persist_summary,
            "blocked_by": blocked_by,
            "next_steps": next_steps,
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload
