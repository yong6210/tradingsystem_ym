from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.services.report_io import atomic_write_text
from app.services.strategy_v2_stress_replay_lineage import StrategyV2StressReplayLineageService


class StrategyV2StressReplayLineageWriterService:
    _SCENARIO_ORDER = (
        "shock_concentration",
        "latency_plus_1_bar",
        "partial_fills_only",
    )

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        plan_repo: Any | None = None,
        fill_repo: Any | None = None,
        candle_repo: Any | None = None,
    ):
        self.settings = settings or get_settings()
        self.lineage = StrategyV2StressReplayLineageService(
            self.settings,
            plan_repo=plan_repo,
            fill_repo=fill_repo,
            candle_repo=candle_repo,
        )

    @staticmethod
    def _int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _safe_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return bool(default)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
        return bool(default)

    def _scenario_trade_rows(self, *, scenario: str, trade_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if scenario == "shock_concentration":
            return [row for row in trade_rows if str(row.get("regime", "range")).lower() == "shock"]
        if scenario == "latency_plus_1_bar":
            return [row for row in trade_rows if self._safe_bool(row.get("latency_bar_exists", False))]
        return [row for row in trade_rows if self._safe_bool(row.get("full_fill_path", False))]

    @staticmethod
    def _chunk(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
        if size <= 0:
            return [rows] if rows else []
        return [rows[index : index + size] for index in range(0, len(rows), size)]

    def _batch_dir(self, *, symbol: str, version: str, now: datetime) -> Path:
        out_dir = Path(self.settings.validation_report_dir) / "stress_replay_lineage_batches"
        out_dir = out_dir / symbol / version / now.strftime("%Y%m%dT%H%M%SZ")
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    @staticmethod
    def _batch_payload(
        *,
        symbol: str,
        version: str,
        scenario: str,
        batch_index: int,
        rows: list[dict[str, Any]],
        runner_contract: dict[str, Any],
        lineage_contract: dict[str, Any],
        generated_at: str,
    ) -> dict[str, Any]:
        anchor_sources: dict[str, int] = {}
        regime_counts: dict[str, int] = {}
        for row in rows:
            entry_anchor = str(row.get("entry_anchor_source", "unknown"))
            regime = str(row.get("regime", "range"))
            anchor_sources[entry_anchor] = int(anchor_sources.get(entry_anchor, 0)) + 1
            regime_counts[regime] = int(regime_counts.get(regime, 0)) + 1
        return {
            "schema_version": "strategy_v2_stress_replay_lineage_batch_v1",
            "generated_at": generated_at,
            "symbol": symbol,
            "version": version,
            "scenario": scenario,
            "batch_index": batch_index,
            "trade_count": len(rows),
            "plan_ids": [str(row.get("plan_id", "")) for row in rows],
            "first_trade_ts": rows[0].get("closed_ts") if rows else None,
            "last_trade_ts": rows[-1].get("closed_ts") if rows else None,
            "anchor_sources": dict(sorted(anchor_sources.items())),
            "regime_counts": dict(sorted(regime_counts.items())),
            "runner_contract": runner_contract,
            "lineage_contract": lineage_contract,
            "trade_rows": rows,
        }

    def _write_batch_artifacts(
        self,
        *,
        symbol: str,
        version: str,
        scenario_contract: dict[str, Any],
        runner_contract: dict[str, Any],
        lineage_contract: dict[str, Any],
        trade_rows: list[dict[str, Any]],
        now: datetime,
    ) -> tuple[dict[str, Any], int]:
        batch_dir = self._batch_dir(symbol=symbol, version=version, now=now)
        target = self._int((dict(runner_contract.get("batching") or {})).get("target_trades_per_job"))
        sample_counts: dict[str, Any] = {}
        total_batches_written = 0
        for scenario in self._SCENARIO_ORDER:
            contract_row = dict(scenario_contract.get(scenario) or {})
            scenario_rows = self._scenario_trade_rows(scenario=scenario, trade_rows=trade_rows)
            ready = self._safe_bool(contract_row.get("ready", False))
            prototype_ready = self._safe_bool(contract_row.get("prototype_ready", False))
            executable = ready or prototype_ready
            summary: dict[str, Any] = {
                "ready": ready,
                "prototype_ready": prototype_ready,
                "executable": executable,
                "gating_reason": contract_row.get("gating_reason", "not_available"),
                "candidate_trades": len(scenario_rows),
                "batches": [],
            }
            if not executable:
                sample_counts[scenario] = summary
                continue

            batches = self._chunk(scenario_rows, max(1, target))
            written_batches: list[dict[str, Any]] = []
            for batch_index, rows in enumerate(batches, start=1):
                batch_payload = self._batch_payload(
                    symbol=symbol,
                    version=version,
                    scenario=scenario,
                    batch_index=batch_index,
                    rows=rows,
                    runner_contract=runner_contract,
                    lineage_contract=lineage_contract,
                    generated_at=now.isoformat(),
                )
                file_path = batch_dir / f"{scenario}_batch_{batch_index:02d}.json"
                atomic_write_text(file_path, json.dumps(batch_payload, ensure_ascii=True, indent=2))
                written_batches.append(
                    {
                        "batch_id": f"{symbol}:{version}:{scenario}:{batch_index:02d}",
                        "artifact_path": str(file_path),
                        "trade_count": len(rows),
                        "first_trade_ts": batch_payload.get("first_trade_ts"),
                        "last_trade_ts": batch_payload.get("last_trade_ts"),
                        "plan_ids": batch_payload.get("plan_ids"),
                        "anchor_sources": batch_payload.get("anchor_sources"),
                        "regime_counts": batch_payload.get("regime_counts"),
                    }
                )
                total_batches_written += 1
            summary["batches"] = written_batches
            sample_counts[scenario] = summary
        return sample_counts, total_batches_written

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.validation_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / (
            f"strategy_v2_stress_replay_lineage_writer_{payload['symbol']}_{payload['version']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        )
        lines = [
            f"# Strategy v2 Stress Replay Lineage Writer: {payload['symbol']}",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- strategy_version: {payload['version']}",
            f"- available: {payload['available']}",
            f"- artifacts_written: {payload['artifacts_written']}",
            f"- runtime_job_ready: {payload['runtime_job_ready']}",
            f"- implementation_status: {payload['implementation_status']}",
            f"- reason: {payload['reason']}",
            "",
            "## Sample Counts",
            f"- eligible_closed_trades: {int((payload.get('sample_counts') or {}).get('eligible_closed_trades', 0) or 0)}",
            f"- trade_rows_written: {int((payload.get('sample_counts') or {}).get('trade_rows_written', 0) or 0)}",
            f"- batches_written: {int((payload.get('sample_counts') or {}).get('batches_written', 0) or 0)}",
            f"- scenarios_written: {int((payload.get('sample_counts') or {}).get('scenarios_written', 0) or 0)}",
            "",
            "## Scenario Batches",
        ]
        for scenario in self._SCENARIO_ORDER:
            row = dict((payload.get("scenario_batches") or {}).get(scenario) or {})
            lines.append(
                f"- {scenario}: ready={self._safe_bool(row.get('ready', False))}, prototype_ready={self._safe_bool(row.get('prototype_ready', False))}, "
                f"candidate_trades={int(row.get('candidate_trades', 0) or 0)}, "
                f"batches={len(row.get('batches', []))}, gating_reason={row.get('gating_reason', 'not_available')}"
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
                "- This artifact materializes per-scenario replay lineage batches for future prototype workers.",
                "- It does not execute replay; it only writes batch inputs and readiness metadata.",
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
        stress_replay_lineage: dict[str, Any],
        stress_replay_runner_contract: dict[str, Any],
        write_report: bool = True,
        trade_rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        lineage_payload = dict(stress_replay_lineage or {})
        runner_payload = dict(stress_replay_runner_contract or {})
        rows = list(trade_rows or self.lineage.trade_rows(symbol=symbol, version=version))
        scenario_contract = dict(runner_payload.get("scenario_contract") or {})
        runner_contract = dict(runner_payload.get("runner_contract") or {})
        lineage_contract = dict(lineage_payload.get("lineage_contract") or {})
        available = self._safe_bool(lineage_payload.get("available", False)) and self._safe_bool(
            runner_payload.get("available", False)
        )
        runtime_job_ready = self._safe_bool(runner_payload.get("runtime_job_ready", False))
        blocked_by = list(dict.fromkeys([*(lineage_payload.get("blocked_by") or []), *(runner_payload.get("blocked_by") or [])]))
        next_steps = list(dict.fromkeys([*(lineage_payload.get("next_steps") or []), *(runner_payload.get("next_steps") or [])]))

        scenario_batches: dict[str, Any] = {}
        total_batches_written = 0
        if available and runtime_job_ready and rows:
            scenario_batches, total_batches_written = self._write_batch_artifacts(
                symbol=symbol,
                version=version,
                scenario_contract=scenario_contract,
                runner_contract=runner_contract,
                lineage_contract=lineage_contract,
                trade_rows=rows,
                now=now,
            )
            prototype_batches_written = any(
                row.get("prototype_ready", False) and row.get("batches")
                for row in scenario_batches.values()
            )
            if total_batches_written > 0:
                implementation_status = (
                    "lineage_writer_seeded_prototype_batches"
                    if prototype_batches_written
                    else "lineage_writer_seeded_scenario_batches"
                )
                reason = (
                    "stress_replay_lineage_prototype_batches_written"
                    if prototype_batches_written
                    else "stress_replay_lineage_batches_written"
                )
            else:
                implementation_status = "lineage_writer_no_ready_batches"
                reason = "stress_replay_no_ready_scenarios"
        elif not available:
            implementation_status = "lineage_writer_waiting_for_dependencies"
            reason = "stress_replay_lineage_or_runner_contract_unavailable"
        elif not runtime_job_ready:
            implementation_status = "lineage_writer_waiting_for_runtime_job_ready"
            reason = "stress_replay_runtime_job_not_ready"
        else:
            implementation_status = "lineage_writer_no_trade_rows"
            reason = "stress_replay_trade_rows_unavailable"

        scenarios_written = sum(1 for row in scenario_batches.values() if row.get("batches"))
        payload: dict[str, Any] = {
            "schema_version": "strategy_v2_stress_replay_lineage_writer_v1",
            "symbol": symbol,
            "version": version,
            "generated_at": now.isoformat(),
            "available": available,
            "artifacts_written": total_batches_written > 0,
            "runtime_job_ready": runtime_job_ready,
            "implementation_status": implementation_status,
            "reason": reason,
            "evaluation_basis": "stress_replay_lineage.trade_rows + stress_replay_runner_contract.scenario_contract",
            "sample_counts": {
                "eligible_closed_trades": self._int((lineage_payload.get("sample_counts") or {}).get("eligible_closed_trades")),
                "trade_rows_available": len(rows),
                "trade_rows_written": sum(
                    self._int(batch.get("trade_count"))
                    for row in scenario_batches.values()
                    for batch in row.get("batches", [])
                ),
                "batches_written": total_batches_written,
                "scenarios_written": scenarios_written,
            },
            "writer_contract": {
                "artifact_schema_version": "strategy_v2_stress_replay_lineage_batch_v1",
                "artifact_format": "json",
                "artifact_subdir": "reports/validation/stress_replay_lineage_batches/<symbol>/<version>/<utc>/",
                "required_trade_fields": [
                    "plan_id",
                    "entry_anchor_ts",
                    "exit_anchor_ts",
                    "entry_anchor_source",
                    "exit_anchor_source",
                    "final_exit_realized_r",
                    "final_exit_reason",
                    "path_coverage_ratio",
                ],
                "scenario_filters": {
                    "shock_concentration": "regime == shock",
                    "latency_plus_1_bar": "latency_bar_exists == true",
                    "partial_fills_only": "full_fill_path == true",
                },
            },
            "scenario_batches": scenario_batches,
            "blocked_by": blocked_by,
            "next_steps": next_steps,
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload
