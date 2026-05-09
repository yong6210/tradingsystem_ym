from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.services.strategy_v2_validation import ClosedTradeRecord, StrategyV2ValidationService


class StrategyV2StressReplayPrototypeWorkerService:
    _SCENARIO_ORDER = (
        "shock_concentration",
        "latency_plus_1_bar",
        "partial_fills_only",
    )
    _INPUT_SCHEMA_VERSION = "strategy_v2_stress_replay_lineage_batch_v1"
    _OUTPUT_SCHEMA_VERSION = "strategy_v2_stress_replay_worker_output_v1"
    _WORKER_SCHEMA_VERSION = "strategy_v2_stress_replay_prototype_worker_v1"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._base = StrategyV2ValidationService(self.settings)

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _normalize_ts(value: Any) -> datetime | None:
        text = str(value or "")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _output_dir(self, *, symbol: str, version: str) -> Path:
        out_dir = Path(self.settings.validation_report_dir) / "stress_replay_worker_outputs" / symbol / version
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    def _report_dir(self) -> Path:
        out_dir = Path(self.settings.validation_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    @staticmethod
    def _coverage_flags(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "has_entry_fill": bool(row.get("has_entry_fill", False)),
            "has_close_fill": bool(row.get("has_close_fill", False)),
            "has_partial_exit_fill": bool(row.get("has_partial_exit_fill", False)),
            "latency_bar_exists": bool(row.get("latency_bar_exists", False)),
            "full_fill_path": bool(row.get("full_fill_path", False)),
            "complete_candle_path": bool(row.get("complete_candle_path", False)),
            "path_coverage_ratio": round(float(row.get("path_coverage_ratio", 0.0) or 0.0), 4),
            "entry_anchor_source": str(row.get("entry_anchor_source", "unknown")),
            "exit_anchor_source": str(row.get("exit_anchor_source", "unknown")),
        }

    def _scenario_adjustment(self, *, row: dict[str, Any], scenario: str) -> tuple[float, list[str]]:
        base_r = float(row.get("final_exit_realized_r", 0.0) or 0.0)
        path_coverage_ratio = min(1.0, max(0.0, float(row.get("path_coverage_ratio", 0.0) or 0.0)))
        coverage_penalty = round((1.0 - path_coverage_ratio) * 0.12, 4)
        anchor_penalty = 0.0
        reasons: list[str] = []
        if str(row.get("entry_anchor_source", "")) != "execution_entry_fill":
            anchor_penalty += 0.03
            reasons.append("entry_anchor_fallback")
        if str(row.get("exit_anchor_source", "")) != "execution_closed_fill":
            anchor_penalty += 0.02
            reasons.append("exit_anchor_fallback")
        if coverage_penalty > 0.0:
            reasons.append("partial_candle_path")

        if scenario == "latency_plus_1_bar":
            replayed_r = base_r - (0.05 + coverage_penalty + anchor_penalty)
            reasons.append("latency_plus_1_bar_penalty")
        elif scenario == "partial_fills_only":
            fill_factor = 0.75 if bool(row.get("has_partial_exit_fill", False)) else 0.60
            replayed_r = (base_r * fill_factor) - (coverage_penalty + anchor_penalty)
            reasons.append(f"partial_fill_factor:{fill_factor:.2f}")
        else:
            shock_factor = 0.85 if base_r >= 0.0 else 1.15
            replayed_r = (base_r * shock_factor) - ((coverage_penalty * 0.5) + anchor_penalty)
            reasons.append(f"shock_factor:{shock_factor:.2f}")
        return round(replayed_r, 4), reasons

    def _replay_trade_rows(self, *, scenario: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        replay_rows: list[dict[str, Any]] = []
        for row in rows:
            replayed_r, reasons = self._scenario_adjustment(row=row, scenario=scenario)
            base_r = float(row.get("final_exit_realized_r", 0.0) or 0.0)
            replay_rows.append(
                {
                    "plan_id": str(row.get("plan_id", "")),
                    "scenario": scenario,
                    "strategy_family": str(row.get("strategy_family", "")),
                    "strategy_grade": str(row.get("strategy_grade", "")),
                    "closed_ts": str(row.get("closed_ts", "")),
                    "replayed_entry_price": None,
                    "replayed_exit_price": None,
                    "approximation_realized_r": round(base_r, 4),
                    "replayed_realized_r": replayed_r,
                    "approximation_delta_r": round(replayed_r - base_r, 4),
                    "coverage_flags": self._coverage_flags(row),
                    "degraded_reason": ",".join(reasons) if reasons else "none",
                    "final_exit_reason": str(row.get("final_exit_reason", "")),
                    "final_exit_held_bars": self._safe_int(row.get("final_exit_held_bars")),
                }
            )
        replay_rows.sort(key=lambda item: item.get("closed_ts", ""))
        return replay_rows

    def _summary_metrics(self, *, replay_rows: list[dict[str, Any]], version: str, symbol: str) -> dict[str, Any]:
        records: list[ClosedTradeRecord] = []
        for row in replay_rows:
            closed_ts = self._normalize_ts(row.get("closed_ts"))
            if closed_ts is None:
                continue
            records.append(
                ClosedTradeRecord(
                    plan_id=str(row.get("plan_id", "")),
                    symbol=symbol,
                    closed_ts=closed_ts,
                    realized_r=float(row.get("replayed_realized_r", 0.0)),
                    held_bars=self._safe_int(row.get("final_exit_held_bars")),
                    exit_reason=str(row.get("final_exit_reason", "unknown") or "unknown"),
                    regime=str(row.get("regime", "unknown") or "unknown").lower(),
                    strategy_family=str(row.get("strategy_family", "unknown") or "unknown"),
                    strategy_grade=str(row.get("strategy_grade", "C") or "C"),
                    strategy_version=version,
                )
            )
        return self._base._mode_metrics(records)

    def _coverage_summary(self, *, replay_rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not replay_rows:
            return {
                "entry_fill_share": 0.0,
                "close_fill_share": 0.0,
                "partial_exit_fill_share": 0.0,
                "full_fill_path_share": 0.0,
                "complete_candle_path_share": 0.0,
                "avg_path_coverage_ratio": 0.0,
            }
        count = float(len(replay_rows))
        return {
            "entry_fill_share": round(sum(1 for row in replay_rows if row["coverage_flags"]["has_entry_fill"]) / count, 4),
            "close_fill_share": round(sum(1 for row in replay_rows if row["coverage_flags"]["has_close_fill"]) / count, 4),
            "partial_exit_fill_share": round(sum(1 for row in replay_rows if row["coverage_flags"]["has_partial_exit_fill"]) / count, 4),
            "full_fill_path_share": round(sum(1 for row in replay_rows if row["coverage_flags"]["full_fill_path"]) / count, 4),
            "complete_candle_path_share": round(sum(1 for row in replay_rows if row["coverage_flags"]["complete_candle_path"]) / count, 4),
            "avg_path_coverage_ratio": round(
                sum(float(row["coverage_flags"]["path_coverage_ratio"]) for row in replay_rows) / count,
                4,
            ),
        }

    @staticmethod
    def _input_lineage_summary(*, rows: list[dict[str, Any]], input_artifact_paths: list[str]) -> dict[str, Any]:
        entry_anchor_sources: dict[str, int] = {}
        exit_anchor_sources: dict[str, int] = {}
        regime_counts: dict[str, int] = {}
        full_fill_path_count = 0
        complete_candle_path_count = 0
        path_coverage_ratio_sum = 0.0
        for row in rows:
            entry_anchor = str(row.get("entry_anchor_source", "unknown"))
            exit_anchor = str(row.get("exit_anchor_source", "unknown"))
            regime = str(row.get("regime", "range"))
            entry_anchor_sources[entry_anchor] = int(entry_anchor_sources.get(entry_anchor, 0)) + 1
            exit_anchor_sources[exit_anchor] = int(exit_anchor_sources.get(exit_anchor, 0)) + 1
            regime_counts[regime] = int(regime_counts.get(regime, 0)) + 1
            if bool(row.get("full_fill_path", False)):
                full_fill_path_count += 1
            if bool(row.get("complete_candle_path", False)):
                complete_candle_path_count += 1
            path_coverage_ratio_sum += float(row.get("path_coverage_ratio", 0.0) or 0.0)
        total_rows = len(rows)
        return {
            "input_schema_version": StrategyV2StressReplayPrototypeWorkerService._INPUT_SCHEMA_VERSION,
            "input_batch_count": len(input_artifact_paths),
            "input_trade_rows": total_rows,
            "entry_anchor_sources": dict(sorted(entry_anchor_sources.items())),
            "exit_anchor_sources": dict(sorted(exit_anchor_sources.items())),
            "regime_counts": dict(sorted(regime_counts.items())),
            "full_fill_path_share": round((full_fill_path_count / total_rows), 4) if total_rows else 0.0,
            "complete_candle_path_share": round((complete_candle_path_count / total_rows), 4) if total_rows else 0.0,
            "avg_path_coverage_ratio": round((path_coverage_ratio_sum / total_rows), 4) if total_rows else 0.0,
        }

    @staticmethod
    def _delta(*, approximation: dict[str, Any], replay_summary: dict[str, Any]) -> dict[str, float]:
        keys = ("trades", "ev", "p5_ev", "p50_ev", "max_drawdown", "ulcer_index")
        return {
            key: round(float(replay_summary.get(key, 0.0)) - float(approximation.get(key, 0.0)), 4)
            for key in keys
        }

    def _read_batch_rows(self, *, artifact_paths: list[str], symbol: str, version: str, scenario: str) -> tuple[list[dict[str, Any]], list[str]]:
        rows: list[dict[str, Any]] = []
        missing_paths: list[str] = []
        for path_str in artifact_paths:
            path = Path(path_str)
            if not path.exists():
                missing_paths.append(path_str)
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                missing_paths.append(path_str)
                continue
            if str(payload.get("schema_version", "")) != self._INPUT_SCHEMA_VERSION:
                missing_paths.append(path_str)
                continue
            if str(payload.get("symbol", "")) != symbol or str(payload.get("version", "")) != version:
                missing_paths.append(path_str)
                continue
            if str(payload.get("scenario", "")) != scenario:
                missing_paths.append(path_str)
                continue
            rows.extend(list(payload.get("trade_rows") or []))
        rows.sort(key=lambda item: str(item.get("closed_ts", "")))
        return rows, missing_paths

    def _write_output_artifact(
        self,
        *,
        symbol: str,
        version: str,
        scenario: str,
        now: datetime,
        input_artifact_paths: list[str],
        replay_rows: list[dict[str, Any]],
        summary: dict[str, Any],
        coverage: dict[str, Any],
        approximation_gap: dict[str, Any],
        input_lineage_summary: dict[str, Any],
    ) -> str:
        out_dir = self._output_dir(symbol=symbol, version=version)
        file_path = out_dir / f"{scenario}_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
        payload = {
            "schema_version": self._OUTPUT_SCHEMA_VERSION,
            "generated_at": now.isoformat(),
            "symbol": symbol,
            "version": version,
            "scenario": scenario,
            "worker_mode": "prototype_from_lineage_batches",
            "input_artifact_paths": input_artifact_paths,
            "trade_rows": replay_rows,
            "summary": {
                **summary,
                "coverage": coverage,
                "approximation_gap": approximation_gap,
            },
            "coverage": coverage,
            "approximation_gap": approximation_gap,
            "input_lineage_summary": dict(input_lineage_summary or {}),
        }
        file_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        return str(file_path)

    def _write_scenario_report(
        self,
        *,
        symbol: str,
        version: str,
        scenario: str,
        now: datetime,
        summary: dict[str, Any],
        approximation_gap: dict[str, Any],
        output_artifact_path: str,
    ) -> str:
        file_path = self._report_dir() / (
            f"strategy_v2_stress_replay_worker_{symbol}_{version}_{scenario}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        )
        lines = [
            f"# Strategy v2 Stress Replay Prototype Worker: {symbol} / {scenario}",
            "",
            f"- generated_at_utc: {now.isoformat()}",
            f"- strategy_version: {version}",
            f"- trades: {int(summary.get('trades', 0) or 0)}",
            f"- ev: {float(summary.get('ev', 0.0)):.4f}",
            f"- p5_ev: {float(summary.get('p5_ev', 0.0)):.4f}",
            f"- max_drawdown: {float(summary.get('max_drawdown', 0.0)):.4f}",
            f"- ulcer_index: {float(summary.get('ulcer_index', 0.0)):.4f}",
            f"- delta_ev(replay-approx): {float(approximation_gap.get('ev', 0.0)):.4f}",
            f"- delta_max_drawdown(replay-approx): {float(approximation_gap.get('max_drawdown', 0.0)):.4f}",
            f"- output_artifact_path: {output_artifact_path}",
            "",
            "## Notes",
            "- This is a prototype worker result derived from lineage batch artifacts.",
            "- It is a deterministic approximation intended to validate runner/output contracts, not a full market replay.",
            "",
        ]
        file_path.write_text("\n".join(lines), encoding="utf-8")
        return str(file_path)

    def _write_overall_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        file_path = self._report_dir() / (
            f"strategy_v2_stress_replay_prototype_worker_{payload['symbol']}_{payload['version']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        )
        lines = [
            f"# Strategy v2 Stress Replay Prototype Worker: {payload['symbol']}",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- strategy_version: {payload['version']}",
            f"- available: {payload['available']}",
            f"- executed: {payload['executed']}",
            f"- runtime_job_ready: {payload['runtime_job_ready']}",
            f"- reason: {payload['reason']}",
            f"- evaluation_basis: {payload.get('evaluation_basis', 'lineage_batch_artifacts')}",
            "",
            "## Sample Counts",
            f"- ready_scenarios: {int((payload.get('sample_counts') or {}).get('ready_scenarios', 0) or 0)}",
            f"- executed_scenarios: {int((payload.get('sample_counts') or {}).get('executed_scenarios', 0) or 0)}",
            f"- input_batches_read: {int((payload.get('sample_counts') or {}).get('input_batches_read', 0) or 0)}",
            f"- replay_trade_rows_written: {int((payload.get('sample_counts') or {}).get('replay_trade_rows_written', 0) or 0)}",
            "",
            "## Scenario Runs",
        ]
        for scenario in self._SCENARIO_ORDER:
            row = dict((payload.get("scenario_runs") or {}).get(scenario) or {})
            summary = dict(row.get("summary") or {})
            lines.append(
                f"- {scenario}: ready={bool(row.get('ready', False))}, prototype_ready={bool(row.get('prototype_ready', False))}, "
                f"executed={bool(row.get('executed', False))}, "
                f"batches_read={int(row.get('batches_read', 0) or 0)}, trades={int(summary.get('trades', 0) or 0)}, "
                f"ev={float(summary.get('ev', 0.0)):.4f}, max_dd={float(summary.get('max_drawdown', 0.0)):.4f}"
            )
        lines.extend(["", "## Blockers"])
        for item in payload.get("blocked_by", []):
            lines.append(f"- {item}")
        lines.extend(["", "## Next Steps"])
        for item in payload.get("next_steps", []):
            lines.append(f"- {item}")
        lines.extend(
            [
                "",
                "## Notes",
                "- This worker consumes lineage batch artifacts and writes replay output artifacts plus per-scenario markdown.",
                "- It is a prototype execution path for contract validation, not a production-grade replay engine.",
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
        stress_replay_lineage_writer: dict[str, Any],
        stress_replay_runner_contract: dict[str, Any],
        write_report: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        writer_payload = dict(stress_replay_lineage_writer or {})
        runner_payload = dict(stress_replay_runner_contract or {})
        available = bool(writer_payload.get("available", False)) and bool(runner_payload.get("available", False))
        runtime_job_ready = bool(writer_payload.get("runtime_job_ready", False)) and bool(
            runner_payload.get("runtime_job_ready", False)
        )
        blocked_by = list(dict.fromkeys([*(writer_payload.get("blocked_by") or []), *(runner_payload.get("blocked_by") or [])]))
        next_steps = list(dict.fromkeys([*(writer_payload.get("next_steps") or []), *(runner_payload.get("next_steps") or [])]))
        scenario_runs: dict[str, Any] = {}
        input_batches_read = 0
        replay_trade_rows_written = 0
        executed_scenarios = 0
        ready_scenarios = 0
        scenario_batches = dict(writer_payload.get("scenario_batches") or {})
        scenario_contract = dict(runner_payload.get("scenario_contract") or {})
        executed = False

        if available and runtime_job_ready:
            for scenario in self._SCENARIO_ORDER:
                batch_row = dict(scenario_batches.get(scenario) or {})
                contract_row = dict(scenario_contract.get(scenario) or {})
                batch_ready = bool(batch_row.get("ready", False))
                batch_prototype_ready = bool(batch_row.get("prototype_ready", False))
                contract_ready = bool(contract_row.get("ready", False))
                contract_prototype_ready = bool(contract_row.get("prototype_ready", False))
                ready = batch_ready and contract_ready
                prototype_ready = (batch_ready or batch_prototype_ready) and (contract_ready or contract_prototype_ready)
                if prototype_ready:
                    ready_scenarios += 1
                artifact_paths = [str(item.get("artifact_path", "")) for item in list(batch_row.get("batches") or []) if item.get("artifact_path")]
                rows, missing_paths = self._read_batch_rows(
                    artifact_paths=artifact_paths,
                    symbol=symbol,
                    version=version,
                    scenario=scenario,
                )
                if not prototype_ready or not rows:
                    scenario_runs[scenario] = {
                        "ready": ready,
                        "prototype_ready": prototype_ready,
                        "executed": False,
                        "reason": (
                            "no_ready_input_batches"
                            if prototype_ready
                            else str(batch_row.get("gating_reason", "not_ready"))
                        ),
                        "batches_read": len(artifact_paths) - len(missing_paths),
                        "missing_input_artifacts": missing_paths,
                        "input_artifact_paths": artifact_paths,
                        "summary": {},
                        "comparison_to_approximation": {},
                        "output_artifact_path": None,
                        "report_path": None,
                    }
                    if prototype_ready and artifact_paths and missing_paths:
                        blocked_by.append(f"{scenario}:missing_input_batch_artifacts")
                    continue

                replay_rows = self._replay_trade_rows(scenario=scenario, rows=rows)
                approximation = dict((stress_validation.get("scenario_metrics") or {}).get(scenario) or {})
                summary = self._summary_metrics(replay_rows=replay_rows, version=version, symbol=symbol)
                coverage = self._coverage_summary(replay_rows=replay_rows)
                approximation_gap = self._delta(approximation=approximation, replay_summary=summary)
                input_lineage_summary = self._input_lineage_summary(rows=rows, input_artifact_paths=artifact_paths)
                output_artifact_path = self._write_output_artifact(
                    symbol=symbol,
                    version=version,
                    scenario=scenario,
                    now=now,
                    input_artifact_paths=artifact_paths,
                    replay_rows=replay_rows,
                    summary=summary,
                    coverage=coverage,
                    approximation_gap=approximation_gap,
                    input_lineage_summary=input_lineage_summary,
                )
                scenario_report_path = self._write_scenario_report(
                    symbol=symbol,
                    version=version,
                    scenario=scenario,
                    now=now,
                    summary=summary,
                    approximation_gap=approximation_gap,
                    output_artifact_path=output_artifact_path,
                )
                input_batches_read += len(artifact_paths) - len(missing_paths)
                replay_trade_rows_written += len(replay_rows)
                executed_scenarios += 1
                executed = True
                scenario_runs[scenario] = {
                    "ready": ready,
                    "prototype_ready": prototype_ready,
                    "executed": True,
                    "reason": "prototype_replay_completed",
                    "batches_read": len(artifact_paths) - len(missing_paths),
                    "missing_input_artifacts": missing_paths,
                    "input_artifact_paths": artifact_paths,
                    "summary": summary,
                    "coverage": coverage,
                    "comparison_to_approximation": approximation_gap,
                    "input_lineage_summary": input_lineage_summary,
                    "output_artifact_path": output_artifact_path,
                    "report_path": scenario_report_path,
                }
        else:
            if not available:
                blocked_by.append("stress_replay_worker_dependencies_unavailable")
            if available and not runtime_job_ready:
                blocked_by.append("stress_replay_worker_runtime_job_not_ready")
            next_steps.append("generate replay lineage batches before running prototype replay worker")

        if executed:
            reason = "stress_replay_prototype_worker_outputs_written"
            next_steps.append("review replay output deltas before promoting them into deployment gates")
        elif available and runtime_job_ready:
            reason = "stress_replay_prototype_worker_no_ready_batches"
            next_steps.append("ensure ready scenarios have readable input batch artifacts")
        else:
            reason = "stress_replay_prototype_worker_not_ready"

        payload: dict[str, Any] = {
            "schema_version": self._WORKER_SCHEMA_VERSION,
            "symbol": symbol,
            "version": version,
            "generated_at": now.isoformat(),
            "available": available,
            "executed": executed,
            "runtime_job_ready": runtime_job_ready,
            "reason": reason,
            "evaluation_basis": "stress replay lineage batch artifacts -> prototype replay worker output artifacts",
            "dependencies": {
                "lineage_writer_schema_version": str(writer_payload.get("schema_version", "")),
                "runner_contract_schema_version": str(runner_payload.get("schema_version", "")),
            },
            "sample_counts": {
                "ready_scenarios": ready_scenarios,
                "executed_scenarios": executed_scenarios,
                "input_batches_read": input_batches_read,
                "replay_trade_rows_written": replay_trade_rows_written,
            },
            "worker_contract": {
                "worker_input_contract": dict(runner_payload.get("worker_input_contract") or {}),
                "worker_output_contract": dict(runner_payload.get("worker_output_contract") or {}),
            },
            "scenario_runs": scenario_runs,
            "blocked_by": list(dict.fromkeys(blocked_by)),
            "next_steps": list(dict.fromkeys(next_steps)),
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_overall_report(payload=payload, now=now)
        return payload
