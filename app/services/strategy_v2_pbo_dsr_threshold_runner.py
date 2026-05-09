from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.db.repositories import ValidationArtifactRepository
from app.services.strategy_v2_pbo_dsr_trial_writer import (
    StrategyV2PboDsrTrialWriterService,
    _RuntimeTrialSeries,
)


class StrategyV2PboDsrThresholdRunnerService(StrategyV2PboDsrTrialWriterService):
    _SELECTION_RULE = "true_threshold_sweep_top_in_sample_ev"
    _WRITER_SOURCE = "true_threshold_sweep_runner_v1"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        repo: ValidationArtifactRepository | None = None,
        fill_repo: Any | None = None,
        candle_repo: Any | None = None,
    ):
        super().__init__(
            settings=settings,
            repo=repo,
            fill_repo=fill_repo,
            candle_repo=candle_repo,
        )
        self.settings = settings or get_settings()

    @staticmethod
    def _numeric_grid(*, center: float, step: float, radius_steps: int, floor: float = 0.0) -> list[float]:
        return sorted(
            {
                round(max(floor, float(center) + (float(step) * offset)), 4)
                for offset in range(-int(radius_steps), int(radius_steps) + 1)
            }
        )

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        if value in (None, "", "None"):
            return default
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if isfinite(parsed) else default

    def _scoring_threshold_trials(self, *, plan_pairs: list[tuple[Any, Any]]) -> list[_RuntimeTrialSeries]:
        if not plan_pairs:
            return []
        thresholds = self._numeric_grid(
            center=self._safe_float(self.settings.min_confluence_score, 62.0),
            step=2.0,
            radius_steps=3,
        )
        trials: list[_RuntimeTrialSeries] = []
        for threshold in thresholds:
            subset = [
                record
                for plan, record in plan_pairs
                if float(self._validity(plan).get("confluence_score", 0.0) or 0.0) >= float(threshold)
            ]
            trial = self._series(
                trial_key=f"scoring_thresholds:true_confluence_gte_{self._sanitize(str(threshold))}",
                parameter_family="scoring_thresholds",
                parameter_values={"confluence_score_min": float(threshold)},
                closed_trades=subset,
                returns=[float(record.realized_r) for record in subset],
                payload={
                    "source": "true_threshold_sweep_runner",
                    "variant": f"confluence_gte_{threshold}",
                    "approximation": "stored_plan_threshold_rerun_light",
                    "lineage_namespace": self._WRITER_SOURCE,
                },
            )
            if trial is not None:
                trials.append(trial)
        return trials

    def _transition_threshold_trials(self, *, plan_pairs: list[tuple[Any, Any]]) -> list[_RuntimeTrialSeries]:
        if not plan_pairs:
            return []
        center = self._safe_float(self.settings.transition_watch_score, 40.0)
        thresholds = self._numeric_grid(center=center, step=2.5, radius_steps=3)
        transition_confirmed_score = self._safe_float(self.settings.transition_confirmed_score, 55.0)
        max_threshold = transition_confirmed_score + 2.5
        trials: list[_RuntimeTrialSeries] = []
        for threshold in [value for value in thresholds if value <= max_threshold]:
            subset = [
                record
                for plan, record in plan_pairs
                if float(self._validity(plan).get("transition_score", 0.0) or 0.0) < float(threshold)
            ]
            trial = self._series(
                trial_key=f"transition_threshold:true_max_transition_lt_{self._sanitize(str(threshold))}",
                parameter_family="transition_threshold",
                parameter_values={
                    "max_transition_score": float(threshold),
                    "transition_confirmed_score": transition_confirmed_score,
                },
                closed_trades=subset,
                returns=[float(record.realized_r) for record in subset],
                payload={
                    "source": "true_threshold_sweep_runner",
                    "variant": f"max_transition_score_lt_{threshold}",
                    "approximation": "stored_transition_score_rerun_light",
                    "lineage_namespace": self._WRITER_SOURCE,
                },
            )
            if trial is not None:
                trials.append(trial)
        return trials

    def _acceptance_rejection_threshold_trials(
        self,
        *,
        plan_pairs: list[tuple[Any, Any]],
    ) -> list[_RuntimeTrialSeries]:
        if not plan_pairs:
            return []
        deltas = (-5.0, 0.0, 5.0)
        trials: list[_RuntimeTrialSeries] = []

        def passes(plan: Any, delta: float) -> bool:
            classification, score = self._reaction_score_for_plan(plan)
            if classification.startswith("rejection"):
                confirmed = self._safe_float(self.settings.reaction_classifier_rejection_confirmed_score, 75.0) + delta
                tentative = self._safe_float(self.settings.reaction_classifier_rejection_tentative_score, 60.0) + delta
            elif classification.startswith("acceptance"):
                confirmed = self._safe_float(self.settings.reaction_classifier_acceptance_confirmed_score, 70.0) + delta
                tentative = self._safe_float(self.settings.reaction_classifier_acceptance_tentative_score, 55.0) + delta
            else:
                return False
            if classification.endswith("confirmed"):
                return score >= confirmed
            if classification.endswith("tentative"):
                return score >= tentative
            return False

        for delta in deltas:
            delta_label = f"{delta:+.1f}".replace("+", "p").replace("-", "m")
            subset = [record for plan, record in plan_pairs if passes(plan, delta)]
            trial = self._series(
                trial_key=f"acceptance_rejection_thresholds:true_delta_{delta_label}",
                parameter_family="acceptance_rejection_thresholds",
                parameter_values={
                    "delta": float(delta),
                    "rejection_confirmed_score": self._safe_float(
                        self.settings.reaction_classifier_rejection_confirmed_score, 75.0
                    )
                    + delta,
                    "rejection_tentative_score": self._safe_float(
                        self.settings.reaction_classifier_rejection_tentative_score, 60.0
                    )
                    + delta,
                    "acceptance_confirmed_score": self._safe_float(
                        self.settings.reaction_classifier_acceptance_confirmed_score, 70.0
                    )
                    + delta,
                    "acceptance_tentative_score": self._safe_float(
                        self.settings.reaction_classifier_acceptance_tentative_score, 55.0
                    )
                    + delta,
                },
                closed_trades=subset,
                returns=[float(record.realized_r) for record in subset],
                payload={
                    "source": "true_threshold_sweep_runner",
                    "variant": f"delta_{delta_label}",
                    "approximation": "stored_reaction_threshold_rerun_light",
                    "lineage_namespace": self._WRITER_SOURCE,
                },
            )
            if trial is not None:
                trials.append(trial)
        return trials

    def _sizing_clamp_trials(self, *, plan_pairs: list[tuple[Any, Any]]) -> list[_RuntimeTrialSeries]:
        if not plan_pairs:
            return []
        caps = sorted(
            {
                self._safe_float(self.settings.sizing_grade_c_r, 0.25),
                0.75,
                self._safe_float(self.settings.sizing_grade_b_r, 0.5),
                self._safe_float(self.settings.sizing_grade_a_r, 1.0),
            }
        )
        trials: list[_RuntimeTrialSeries] = []
        for cap in caps:
            closed_trades = []
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
                trial_key=f"sizing_clamps:true_max_risk_r_{self._sanitize(str(cap))}",
                parameter_family="sizing_clamps",
                parameter_values={"max_risk_r": float(cap)},
                closed_trades=closed_trades,
                returns=returns,
                payload={
                    "source": "true_threshold_sweep_runner",
                    "variant": f"max_risk_r_{cap}",
                    "approximation": "stored_size_clamp_rerun_light",
                    "lineage_namespace": self._WRITER_SOURCE,
                },
            )
            if trial is not None:
                trials.append(trial)
        return trials

    def _candidate_trials(self, *, plans: list[Any], symbol: str, version: str) -> tuple[list[_RuntimeTrialSeries], int]:
        plan_pairs = self._closed_plan_pairs(plans=plans, symbol=symbol, version=version)
        trials = [
            *self._scoring_threshold_trials(plan_pairs=plan_pairs),
            *self._transition_threshold_trials(plan_pairs=plan_pairs),
            *self._acceptance_rejection_threshold_trials(plan_pairs=plan_pairs),
            *self._sizing_clamp_trials(plan_pairs=plan_pairs),
        ]
        return trials, len(plan_pairs)

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.validation_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / (
            f"strategy_v2_pbo_dsr_threshold_runner_{payload['symbol']}_{payload['version']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        )
        lines = [
            f"# Strategy v2 PBO / DSR Threshold Runner: {payload['symbol']}",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- strategy_version: {payload['version']}",
            f"- available: {payload['available']}",
            f"- implementation_status: {payload['implementation_status']}",
            f"- reason: {payload['reason']}",
            f"- evaluation_basis: {payload.get('evaluation_basis', 'true_threshold_sweep_runner')}",
            f"- lineage_namespace: {payload.get('lineage_namespace', self._WRITER_SOURCE)}",
            "",
            "## Executive Summary",
            f"- eligible_closed_trades: {int((payload.get('sample_counts') or {}).get('eligible_closed_trades', 0))}",
            f"- candidate_trials: {int((payload.get('sample_counts') or {}).get('candidate_trials', 0))}",
            f"- trial_runs_written: {int((payload.get('sample_counts') or {}).get('trial_runs_written', 0))}",
            f"- fold_scores_written: {int((payload.get('sample_counts') or {}).get('fold_scores_written', 0))}",
            f"- fold_count: {int((payload.get('sample_counts') or {}).get('fold_count', 0))}",
            f"- selection_rule: {payload.get('selection_rule', self._SELECTION_RULE)}",
            f"- selected_trial_run_id: {payload.get('selected_trial_run_id')}",
            f"- parameter_families_present: {payload.get('parameter_families_present', [])}",
            f"- candidate_trials_by_family: {payload.get('candidate_trials_by_family', {})}",
            f"- sweep_grid: {payload.get('sweep_grid', {})}",
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
                "- This runner seeds threshold families into a lineage that is separate from the runtime proxy writer.",
                "- It re-evaluates threshold families from stored closed-plan metadata; it is not a full historical engine replay.",
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
        plans: list[Any],
        write_report: bool = True,
        persist: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        if self.repo is None:
            raise RuntimeError("ValidationArtifactRepository is required")

        candidate_trials, eligible_closed_trade_count = self._candidate_trials(plans=plans, symbol=symbol, version=version)
        fold_count = self._global_fold_count(candidate_trials)
        blocked_by: list[str] = []
        next_steps: list[str] = []

        if eligible_closed_trade_count == 0:
            blocked_by.append("no eligible closed v2 trades for true threshold runner")
            next_steps.append("accumulate eligible closed v2 trades before seeding true threshold-sweep lineage")
        if len(candidate_trials) < 2:
            blocked_by.append("true threshold runner produced fewer than 2 candidate trials")
            next_steps.append("keep threshold families populated so CSCV can rank multiple threshold trials")
        if fold_count < 2:
            blocked_by.append("insufficient contiguous samples for true threshold runner folds")
            next_steps.append("increase closed-trade sample size or reduce minimum trades per fold")

        trial_rows = []
        fold_rows = []
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
            implementation_status = "true_threshold_sweep_runner_seeded"
            reason = "pbo_dsr_true_threshold_runner_seeded"
            next_steps.append("audit proxy writer vs true threshold runner selected trials")
            next_steps.append("review combined PBO/DSR metrics against validation protocol thresholds")
        elif eligible_closed_trade_count == 0:
            implementation_status = "true_threshold_sweep_runner_no_closed_trades"
            reason = "pbo_dsr_true_threshold_runner_no_closed_trades"
        elif len(candidate_trials) < 2:
            implementation_status = "true_threshold_sweep_runner_insufficient_trials"
            reason = "pbo_dsr_true_threshold_runner_insufficient_trials"
        else:
            implementation_status = "true_threshold_sweep_runner_insufficient_folds"
            reason = "pbo_dsr_true_threshold_runner_insufficient_folds"

        blocked_by = list(dict.fromkeys(blocked_by))
        next_steps = list(dict.fromkeys(next_steps))
        payload: dict[str, Any] = {
            "schema_version": "strategy_v2_pbo_dsr_threshold_runner_v1",
            "symbol": symbol,
            "version": version,
            "generated_at": now.isoformat(),
            "available": available,
            "implementation_status": implementation_status,
            "reason": reason,
            "evaluation_basis": "closed_v2_trades + separated true threshold-sweep lineage from stored plan metadata",
            "lineage_namespace": self._WRITER_SOURCE,
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
            "candidate_trials_by_family": {
                family: sum(1 for trial in candidate_trials if trial.parameter_family == family)
                for family in sorted({trial.parameter_family for trial in candidate_trials})
            },
            "sweep_grid": {
                "scoring_thresholds": self._numeric_grid(
                    center=self._safe_float(self.settings.min_confluence_score, 62.0),
                    step=2.0,
                    radius_steps=3,
                ),
                "transition_threshold": [
                    value
                    for value in self._numeric_grid(
                        center=self._safe_float(self.settings.transition_watch_score, 40.0),
                        step=2.5,
                        radius_steps=3,
                    )
                    if value <= self._safe_float(self.settings.transition_confirmed_score, 55.0) + 2.5
                ],
                "acceptance_rejection_thresholds": [-5.0, 0.0, 5.0],
                "sizing_clamps": sorted(
                    {
                        self._safe_float(self.settings.sizing_grade_c_r, 0.25),
                        0.75,
                        self._safe_float(self.settings.sizing_grade_b_r, 0.5),
                        self._safe_float(self.settings.sizing_grade_a_r, 1.0),
                    }
                ),
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
