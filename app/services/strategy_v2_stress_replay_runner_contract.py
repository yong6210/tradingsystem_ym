from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings


class StrategyV2StressReplayRunnerContractService:
    _SCENARIO_ORDER = (
        "shock_concentration",
        "latency_plus_1_bar",
        "partial_fills_only",
    )

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @staticmethod
    def _int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _float(value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _job_count(*, trades: int, min_trades_per_job: int, target_trades_per_job: int) -> int:
        if trades < max(1, int(min_trades_per_job)):
            return 0
        return max(1, int(ceil(float(trades) / float(max(1, int(target_trades_per_job))))))

    def _scenario_contract(
        self,
        *,
        stress_validation: dict[str, Any],
        stress_replay_lineage: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        coverage = dict(stress_replay_lineage.get("coverage") or {})
        fill_path = dict(stress_replay_lineage.get("fill_path") or {})
        sample_counts = dict(stress_replay_lineage.get("sample_counts") or {})
        stress_counts = dict(stress_validation.get("sample_counts") or {})
        scenario_statuses = dict(
            (dict(stress_validation.get("deployment_recommendation") or {})).get("scenario_statuses") or {}
        )
        min_exec = float(self.settings.stress_replay_lineage_min_execution_fill_coverage)
        min_latency = float(self.settings.stress_replay_lineage_min_latency_candle_coverage)
        min_path = float(self.settings.stress_replay_lineage_min_candle_path_coverage)
        target = int(self.settings.stress_replay_runner_target_trades_per_job)
        minimum = int(self.settings.stress_replay_runner_min_trades_per_job)

        runtime_inputs_ready = bool(stress_replay_lineage.get("runtime_inputs_ready", False))
        latency_trades = self._int(sample_counts.get("latency_bar_trades"))
        full_fill_trades = self._int(sample_counts.get("full_fill_path_trades"))
        eligible_trades = self._int(sample_counts.get("eligible_closed_trades"))
        shock_trades = self._int(stress_counts.get("shock_regime_trades"))

        rows: dict[str, dict[str, Any]] = {}
        for index, scenario in enumerate(self._SCENARIO_ORDER, start=1):
            status = dict(scenario_statuses.get(scenario) or {})
            if scenario == "shock_concentration":
                ready = runtime_inputs_ready and shock_trades >= minimum and self._float(coverage.get("candle_path_coverage")) >= min_path
                scenario_trades = shock_trades
                required_inputs = [
                    "closed_v2_trades_in_shock_regime",
                    "entry_to_exit_5m_candle_path",
                    "entry/closed execution fills or anchor fallback",
                ]
                gating_reason = (
                    "ready" if ready else "shock_sample_or_candle_path_below_contract"
                )
            elif scenario == "latency_plus_1_bar":
                ready = runtime_inputs_ready and latency_trades >= minimum and self._float(coverage.get("latency_candle_coverage")) >= min_latency
                scenario_trades = latency_trades
                required_inputs = [
                    "entry anchor timestamp",
                    "latency_plus_1_bar candle open",
                    "entry/closed execution fills or anchor fallback",
                ]
                gating_reason = "ready" if ready else "latency_reference_coverage_below_contract"
            else:
                ready = runtime_inputs_ready and full_fill_trades >= minimum and self._float(fill_path.get("full_fill_path_coverage")) >= min_exec
                scenario_trades = full_fill_trades
                required_inputs = [
                    "entry execution fill",
                    "closed execution fill",
                    "optional partial_exit fills",
                    "entry_to_exit candle path",
                ]
                gating_reason = "ready" if ready else "execution_fill_path_below_contract"

            jobs = self._job_count(
                trades=scenario_trades,
                min_trades_per_job=minimum,
                target_trades_per_job=target,
            )
            rows[scenario] = {
                "priority_rank": index,
                "ready": ready,
                "gating_reason": gating_reason,
                "scenario_status": str(status.get("status", "UNKNOWN")),
                "scenario_reason": str(status.get("reason", "not_available")),
                "catastrophic_loss_detected": bool(status.get("catastrophic_loss_detected", False)),
                "eligible_trade_count": scenario_trades,
                "suggested_job_count": jobs,
                "required_inputs": required_inputs,
                "coverage_snapshot": {
                    "execution_fill_coverage": self._float(coverage.get("execution_fill_coverage")),
                    "latency_candle_coverage": self._float(coverage.get("latency_candle_coverage")),
                    "candle_path_coverage": self._float(coverage.get("candle_path_coverage")),
                    "full_fill_path_coverage": self._float(fill_path.get("full_fill_path_coverage")),
                    "eligible_closed_trades": eligible_trades,
                },
            }
        return rows

    def _status_payload(
        self,
        *,
        stress_replay_lineage: dict[str, Any],
        stress_replay_assessment: dict[str, Any],
        scenario_contract: dict[str, dict[str, Any]],
    ) -> tuple[bool, str, str, list[str], list[str], dict[str, Any], dict[str, Any]]:
        lineage_available = bool(stress_replay_lineage.get("available", False))
        runtime_inputs_ready = bool(stress_replay_lineage.get("runtime_inputs_ready", False))
        full_replay_ready = bool(stress_replay_assessment.get("full_replay_ready", False))
        replacement_recommended = bool(stress_replay_assessment.get("replacement_recommended", False))
        priority = str((dict(stress_replay_assessment.get("deployment_recommendation") or {})).get("priority", "low"))
        true_runner_readiness = dict(stress_replay_assessment.get("true_runner_readiness") or {})
        true_runner_ready = bool(true_runner_readiness.get("true_runner_ready", False))

        ready_scenarios = [name for name, row in scenario_contract.items() if bool(row.get("ready", False))]
        blocked_scenarios = [name for name, row in scenario_contract.items() if not bool(row.get("ready", False))]
        total_jobs = sum(self._int(row.get("suggested_job_count")) for row in scenario_contract.values() if bool(row.get("ready", False)))

        blocked_by = list(dict.fromkeys([*(stress_replay_lineage.get("blocked_by") or [])]))
        next_steps = list(dict.fromkeys([*(stress_replay_lineage.get("next_steps") or [])]))

        if not lineage_available:
            blocked_by.append("stress_replay_lineage_unavailable")
            next_steps.append("compute stress replay lineage before defining runner inputs")
            implementation_status = "runner_contract_defined_waiting_for_lineage"
            reason = "stress_replay_lineage_unavailable"
            runtime_job_ready = False
        elif not runtime_inputs_ready:
            implementation_status = "runner_contract_defined_inputs_incomplete"
            reason = "stress_replay_runtime_inputs_incomplete"
            runtime_job_ready = False
            next_steps.append("close runtime lineage gaps before creating replay batches")
        elif not full_replay_ready:
            blocked_by.append("full_replay_not_ready")
            implementation_status = "runner_contract_defined_waiting_for_upgrade_signal"
            reason = "stress_replay_upgrade_not_ready"
            runtime_job_ready = False
            next_steps.append("keep approximation live and revisit replay once stress evidence accumulates")
        else:
            if true_runner_ready:
                implementation_status = "runner_contract_defined_ready_for_true_market_runner"
                reason = "stress_true_runner_ready"
            else:
                implementation_status = (
                    "runner_contract_defined_high_priority_prototype"
                    if replacement_recommended
                    else "runner_contract_defined_ready_for_prototype"
                )
                reason = (
                    "stress_replay_runner_contract_recommended"
                    if replacement_recommended
                    else "stress_replay_runner_contract_ready"
                )
            runtime_job_ready = bool(ready_scenarios)
            if not runtime_job_ready:
                blocked_by.append("no_ready_replay_scenarios")
            next_steps.extend(
                [
                    "connect replay lineage writer to materialize batch inputs per scenario",
                    "implement prototype worker that writes replay trade rows and scenario summaries",
                ]
            )
            if true_runner_ready:
                next_steps.append("true market replay runner can replace the prototype path when execution/runtime integration is available")
            else:
                next_steps.extend(true_runner_readiness.get("next_steps") or [])

        readiness = {
            "lineage_available": lineage_available,
            "lineage_runtime_inputs_ready": runtime_inputs_ready,
            "full_replay_ready": full_replay_ready,
            "replacement_recommended": replacement_recommended,
            "priority": priority,
            "ready_scenarios": ready_scenarios,
            "blocked_scenarios": blocked_scenarios,
            "suggested_total_jobs": total_jobs,
        }
        return (
            runtime_job_ready,
            implementation_status,
            reason,
            blocked_by,
            list(dict.fromkeys(next_steps)),
            readiness,
            true_runner_readiness,
        )

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.validation_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / (
            f"strategy_v2_stress_replay_runner_contract_{payload['symbol']}_{payload['version']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        )
        readiness = dict(payload.get("readiness") or {})
        runner_contract = dict(payload.get("runner_contract") or {})
        batching = dict(runner_contract.get("batching") or {})
        dependencies = dict(payload.get("dependencies") or {})
        true_runner_readiness = dict(payload.get("true_runner_readiness") or {})
        lines = [
            f"# Strategy v2 Stress Replay Runner Contract: {payload['symbol']}",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- strategy_version: {payload['version']}",
            f"- design_ready: {payload['design_ready']}",
            f"- available: {payload['available']}",
            f"- runtime_job_ready: {payload['runtime_job_ready']}",
            f"- implementation_status: {payload['implementation_status']}",
            f"- reason: {payload['reason']}",
            "",
            "## Readiness",
            f"- lineage_available: {bool(readiness.get('lineage_available', False))}",
            f"- lineage_runtime_inputs_ready: {bool(readiness.get('lineage_runtime_inputs_ready', False))}",
            f"- full_replay_ready: {bool(readiness.get('full_replay_ready', False))}",
            f"- replacement_recommended: {bool(readiness.get('replacement_recommended', False))}",
            f"- priority: {readiness.get('priority', 'low')}",
            f"- ready_scenarios: {readiness.get('ready_scenarios', [])}",
            f"- blocked_scenarios: {readiness.get('blocked_scenarios', [])}",
            f"- suggested_total_jobs: {int(readiness.get('suggested_total_jobs', 0) or 0)}",
            f"- true_runner_ready: {bool(true_runner_readiness.get('true_runner_ready', False))}",
            f"- true_runner_stage: {true_runner_readiness.get('stage', 'prototype_only')}",
            "",
            "## Dependencies",
            f"- lineage_schema_version: {dependencies.get('stress_replay_lineage_schema_version', 'n/a')}",
            f"- assessment_schema_version: {dependencies.get('stress_replay_assessment_schema_version', 'n/a')}",
            f"- stress_validation_schema_version: {dependencies.get('stress_validation_schema_version', 'n/a')}",
            "",
            "## Runner Contract",
            f"- dispatch_mode: {runner_contract.get('dispatch_mode', 'manual_symbol_version_scenario_batch')}",
            f"- queue_backend: {runner_contract.get('queue_backend', 'validation_report_only')}",
            f"- job_key_fields: {runner_contract.get('job_key_fields', [])}",
            f"- idempotency_key_fields: {runner_contract.get('idempotency_key_fields', [])}",
            f"- target_trades_per_job: {int(batching.get('target_trades_per_job', 0) or 0)}",
            f"- min_trades_per_job: {int(batching.get('min_trades_per_job', 0) or 0)}",
            f"- max_parallel_jobs: {int(batching.get('max_parallel_jobs', 0) or 0)}",
            f"- suggested_jobs: {batching.get('suggested_jobs', {})}",
            "",
            "## Scenario Contract",
        ]
        for scenario in self._SCENARIO_ORDER:
            row = dict((payload.get("scenario_contract") or {}).get(scenario) or {})
            lines.append(
                f"- {scenario}: ready={bool(row.get('ready', False))}, status={row.get('scenario_status', 'UNKNOWN')}, "
                f"reason={row.get('gating_reason', 'not_available')}, eligible_trade_count={int(row.get('eligible_trade_count', 0) or 0)}, "
                f"suggested_job_count={int(row.get('suggested_job_count', 0) or 0)}"
            )
        lines.extend(
            [
                "",
                "## Worker Input Contract",
                f"- required_sources: {(payload.get('worker_input_contract') or {}).get('required_sources', [])}",
                f"- required_fields: {(payload.get('worker_input_contract') or {}).get('required_fields', [])}",
                f"- optional_fields: {(payload.get('worker_input_contract') or {}).get('optional_fields', [])}",
                "",
                "## Worker Output Contract",
                f"- trade_level_fields: {(payload.get('worker_output_contract') or {}).get('trade_level_fields', [])}",
                f"- summary_fields: {(payload.get('worker_output_contract') or {}).get('summary_fields', [])}",
                f"- artifact_targets: {(payload.get('worker_output_contract') or {}).get('artifact_targets', [])}",
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
                "- This artifact freezes the minimum runner/worker IO contract for full replay.",
                "- It does not execute replay jobs yet; queueing and lineage writer integration remain follow-up work.",
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
        stress_validation: dict[str, Any],
        stress_replay_lineage: dict[str, Any],
        stress_replay_assessment: dict[str, Any],
        write_report: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        scenario_contract = self._scenario_contract(
            stress_validation=stress_validation,
            stress_replay_lineage=stress_replay_lineage,
        )
        (
            runtime_job_ready,
            implementation_status,
            reason,
            blocked_by,
            next_steps,
            readiness,
            true_runner_readiness,
        ) = self._status_payload(
            stress_replay_lineage=stress_replay_lineage,
            stress_replay_assessment=stress_replay_assessment,
            scenario_contract=scenario_contract,
        )
        ready_scenarios = [name for name, row in scenario_contract.items() if bool(row.get("ready", False))]

        payload: dict[str, Any] = {
            "schema_version": "strategy_v2_stress_replay_runner_contract_v1",
            "symbol": symbol,
            "version": version,
            "generated_at": now.isoformat(),
            "design_ready": True,
            "available": bool(stress_replay_lineage or stress_replay_assessment or stress_validation),
            "runtime_job_ready": runtime_job_ready,
            "implementation_status": implementation_status,
            "reason": reason,
            "evaluation_basis": "stress_validation + stress_replay_lineage + stress_replay_assessment",
            "readiness": readiness,
            "true_runner_readiness": true_runner_readiness,
            "dependencies": {
                "stress_validation_schema_version": stress_validation.get("schema_version", "strategy_v2_stress_validation_v2"),
                "stress_replay_lineage_schema_version": stress_replay_lineage.get(
                    "schema_version",
                    "strategy_v2_stress_replay_lineage_v1",
                ),
                "stress_replay_assessment_schema_version": stress_replay_assessment.get(
                    "schema_version",
                    "strategy_v2_stress_replay_assessment_v1",
                ),
                "lineage_report_path": stress_replay_lineage.get("report_path"),
                "assessment_report_path": stress_replay_assessment.get("report_path"),
            },
            "scenario_contract": scenario_contract,
            "runner_contract": {
                "dispatch_mode": "manual_symbol_version_scenario_batch",
                "queue_backend": "validation_report_only",
                "job_key_fields": [
                    "job_id",
                    "symbol",
                    "version",
                    "scenario",
                    "batch_index",
                    "trade_ids",
                    "requested_at",
                ],
                "idempotency_key_fields": ["symbol", "version", "scenario", "batch_index", "lineage_schema_version"],
                "batching": {
                    "target_trades_per_job": int(self.settings.stress_replay_runner_target_trades_per_job),
                    "min_trades_per_job": int(self.settings.stress_replay_runner_min_trades_per_job),
                    "max_parallel_jobs": int(self.settings.stress_replay_runner_max_parallel_jobs),
                    "suggested_jobs": {
                        name: int((scenario_contract.get(name) or {}).get("suggested_job_count", 0))
                        for name in self._SCENARIO_ORDER
                    },
                    "ready_scenarios": ready_scenarios,
                },
                "artifact_targets": [
                    "reports/validation/strategy_v2_stress_replay_worker_<SYMBOL>_<VERSION>_<SCENARIO>_<UTC>.md",
                ],
            },
            "worker_input_contract": {
                "required_sources": [
                    "closed_v2_plans",
                    "execution_fills",
                    "5m_candles",
                    "strategy_v2_stress_replay_lineage",
                    "strategy_v2_stress_replay_assessment",
                ],
                "required_fields": [
                    "plan_id",
                    "scenario",
                    "entry_anchor_ts",
                    "exit_anchor_ts",
                    "entry_anchor_source",
                    "exit_anchor_source",
                    "final_exit_realized_r",
                    "final_exit_reason",
                ],
                "optional_fields": [
                    "partial_exit_fill_rows",
                    "classification_flip_detail",
                    "latency_reference_bar_ts",
                    "shock_regime_flag",
                ],
                "scenario_specific_requirements": {
                    name: list((row or {}).get("required_inputs", []))
                    for name, row in scenario_contract.items()
                },
            },
            "worker_output_contract": {
                "trade_level_fields": [
                    "plan_id",
                    "scenario",
                    "replayed_entry_price",
                    "replayed_exit_price",
                    "replayed_realized_r",
                    "approximation_delta_r",
                    "coverage_flags",
                    "degraded_reason",
                ],
                "summary_fields": [
                    "trades",
                    "ev",
                    "p5_ev",
                    "max_drawdown",
                    "ulcer_index",
                    "coverage",
                    "approximation_gap",
                ],
                "artifact_targets": [
                    "reports/validation/stress_replay_worker_outputs/<SYMBOL>/<VERSION>/<SCENARIO>_<UTC>.json",
                    "reports/validation/strategy_v2_stress_replay_worker_<SYMBOL>_<VERSION>_<SCENARIO>_<UTC>.md",
                    "future: stress_validation.replay_output_artifacts payload",
                ],
            },
            "blocked_by": blocked_by,
            "next_steps": next_steps,
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload
