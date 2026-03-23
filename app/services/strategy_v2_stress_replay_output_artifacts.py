from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings


class StrategyV2StressReplayOutputArtifactsService:
    _SCENARIO_ORDER = (
        "shock_concentration",
        "latency_plus_1_bar",
        "partial_fills_only",
    )
    _SCHEMA_VERSION = "strategy_v2_stress_replay_output_artifacts_v1"
    _WORKER_OUTPUT_SCHEMA_VERSION = "strategy_v2_stress_replay_worker_output_v1"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def _base_dir(self, *, symbol: str, version: str) -> Path:
        return Path(self.settings.validation_report_dir) / "stress_replay_worker_outputs" / symbol / version

    @staticmethod
    def _parse_iso(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            text = str(value)
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _artifact_generated_at(cls, *, payload: dict[str, Any], path: Path) -> datetime:
        parsed = cls._parse_iso(payload.get("generated_at"))
        if parsed is not None:
            return parsed
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)

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

    @classmethod
    def _summary_from_payload(cls, payload: dict[str, Any]) -> dict[str, Any]:
        summary = dict(payload.get("summary") or {})
        return {
            "trades": cls._safe_int(summary.get("trades")),
            "ev": round(cls._safe_float(summary.get("ev")), 4),
            "p5_ev": round(cls._safe_float(summary.get("p5_ev")), 4),
            "p50_ev": round(cls._safe_float(summary.get("p50_ev")), 4),
            "max_drawdown": round(cls._safe_float(summary.get("max_drawdown")), 4),
            "ulcer_index": round(cls._safe_float(summary.get("ulcer_index")), 4),
        }

    @staticmethod
    def _coverage_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
        summary = dict(payload.get("summary") or {})
        return dict(summary.get("coverage") or payload.get("coverage") or {})

    @staticmethod
    def _approximation_gap_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
        summary = dict(payload.get("summary") or {})
        return dict(summary.get("approximation_gap") or payload.get("approximation_gap") or {})

    @staticmethod
    def _input_lineage_summary_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
        return dict(payload.get("input_lineage_summary") or {})

    @staticmethod
    def _delta(approximation: dict[str, Any], replay_summary: dict[str, Any]) -> dict[str, float]:
        keys = ("trades", "ev", "p5_ev", "p50_ev", "max_drawdown", "ulcer_index")
        return {
            key: round(float(replay_summary.get(key, 0.0)) - float(approximation.get(key, 0.0)), 4)
            for key in keys
        }

    @classmethod
    def _lineage_summary(cls, *, scenario_outputs: dict[str, Any]) -> dict[str, Any]:
        worker_modes: set[str] = set()
        input_schema_versions: set[str] = set()
        scenarios_with_lineage: list[str] = []
        compared_scenarios: list[str] = []
        input_batch_count = 0
        input_trade_rows = 0
        entry_anchor_sources: dict[str, int] = {}
        exit_anchor_sources: dict[str, int] = {}
        regime_counts: dict[str, int] = {}
        for scenario in cls._SCENARIO_ORDER:
            row = dict(scenario_outputs.get(scenario) or {})
            if not bool(row.get("available", False)):
                continue
            scenarios_with_lineage.append(scenario)
            if dict(row.get("summary") or {}):
                compared_scenarios.append(scenario)
            worker_modes.add(str(row.get("worker_mode", "unknown") or "unknown"))
            lineage_summary = dict(row.get("input_lineage_summary") or {})
            schema_version = str(lineage_summary.get("input_schema_version", "") or "")
            if schema_version:
                input_schema_versions.add(schema_version)
            input_batch_count += cls._safe_int(lineage_summary.get("input_batch_count"))
            input_trade_rows += cls._safe_int(lineage_summary.get("input_trade_rows"))
            for key, value in dict(lineage_summary.get("entry_anchor_sources") or {}).items():
                entry_anchor_sources[str(key)] = int(entry_anchor_sources.get(str(key), 0)) + cls._safe_int(value)
            for key, value in dict(lineage_summary.get("exit_anchor_sources") or {}).items():
                exit_anchor_sources[str(key)] = int(exit_anchor_sources.get(str(key), 0)) + cls._safe_int(value)
            for key, value in dict(lineage_summary.get("regime_counts") or {}).items():
                regime_counts[str(key)] = int(regime_counts.get(str(key), 0)) + cls._safe_int(value)
        return {
            "available": bool(scenarios_with_lineage),
            "worker_modes": sorted(worker_modes),
            "input_schema_versions": sorted(input_schema_versions),
            "scenarios_with_lineage": scenarios_with_lineage,
            "compared_scenarios": compared_scenarios,
            "input_batch_count": input_batch_count,
            "input_trade_rows": input_trade_rows,
            "entry_anchor_sources": dict(sorted(entry_anchor_sources.items())),
            "exit_anchor_sources": dict(sorted(exit_anchor_sources.items())),
            "regime_counts": dict(sorted(regime_counts.items())),
        }

    def _artifact_candidates(self, *, symbol: str, version: str) -> list[tuple[Path, dict[str, Any]]]:
        base_dir = self._base_dir(symbol=symbol, version=version)
        if not base_dir.exists():
            return []
        candidates: list[tuple[Path, dict[str, Any]]] = []
        for path in sorted(base_dir.rglob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if str(payload.get("schema_version", "")) != self._WORKER_OUTPUT_SCHEMA_VERSION:
                continue
            if str(payload.get("symbol", "")) != symbol or str(payload.get("version", "")) != version:
                continue
            if str(payload.get("scenario", "")) not in self._SCENARIO_ORDER:
                continue
            candidates.append((path, payload))
        return candidates

    def _latest_by_scenario(self, *, symbol: str, version: str) -> dict[str, tuple[Path, dict[str, Any]]]:
        selected: dict[str, tuple[Path, dict[str, Any]]] = {}
        for path, payload in self._artifact_candidates(symbol=symbol, version=version):
            scenario = str(payload.get("scenario"))
            current = selected.get(scenario)
            if current is None:
                selected[scenario] = (path, payload)
                continue
            current_ts = self._artifact_generated_at(payload=current[1], path=current[0])
            next_ts = self._artifact_generated_at(payload=payload, path=path)
            if next_ts >= current_ts:
                selected[scenario] = (path, payload)
        return selected

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.validation_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / (
            f"strategy_v2_stress_replay_output_artifacts_{payload['symbol']}_{payload['version']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        )
        summary_counts = dict(payload.get("summary_counts") or {})
        lines = [
            f"# Strategy v2 Stress Replay Output Artifacts: {payload['symbol']}",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- strategy_version: {payload['version']}",
            f"- available: {payload['available']}",
            f"- comparison_ready: {payload['comparison_ready']}",
            f"- reason: {payload['reason']}",
            "",
            "## Summary Counts",
            f"- scenarios_expected: {int(summary_counts.get('scenarios_expected', 0) or 0)}",
            f"- scenarios_with_artifacts: {int(summary_counts.get('scenarios_with_artifacts', 0) or 0)}",
            f"- scenarios_compared: {int(summary_counts.get('scenarios_compared', 0) or 0)}",
            f"- replay_trade_rows: {int(summary_counts.get('replay_trade_rows', 0) or 0)}",
            "",
            "## Lineage Summary",
            f"- lineage_summary: {payload.get('lineage_summary', {})}",
            "",
            "## Scenario Outputs",
        ]
        for scenario in self._SCENARIO_ORDER:
            row = dict((payload.get("scenario_outputs") or {}).get(scenario) or {})
            summary = dict(row.get("summary") or {})
            delta = dict(row.get("comparison_to_approximation") or {})
            lines.append(
                f"- {scenario}: available={bool(row.get('available', False))}, reason={row.get('reason', 'not_available')}, "
                f"trades={int(summary.get('trades', 0) or 0)}, ev={float(summary.get('ev', 0.0)):.4f}, "
                f"p5={float(summary.get('p5_ev', 0.0)):.4f}, max_dd={float(summary.get('max_drawdown', 0.0)):.4f}, "
                f"delta_ev={float(delta.get('ev', 0.0)):.4f}, delta_max_dd={float(delta.get('max_drawdown', 0.0)):.4f}"
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
                "- This payload reads worker-generated replay output artifacts if they exist.",
                "- Missing artifacts are a normal state until the prototype replay worker is connected.",
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
        write_report: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        scenario_metrics = dict((stress_validation or {}).get("scenario_metrics") or {})
        latest = self._latest_by_scenario(symbol=symbol, version=version)
        scenario_outputs: dict[str, Any] = {}
        comparison_to_approximation: dict[str, dict[str, float]] = {}
        blocked_by: list[str] = []
        next_steps: list[str] = []
        scenarios_with_artifacts = 0
        scenarios_compared = 0
        replay_trade_rows = 0

        for scenario in self._SCENARIO_ORDER:
            selected = latest.get(scenario)
            if selected is None:
                scenario_outputs[scenario] = {
                    "available": False,
                    "reason": "artifact_missing",
                    "artifact_path": None,
                    "generated_at": None,
                    "summary": {},
                    "coverage": {},
                    "approximation_gap": {},
                    "comparison_to_approximation": {},
                }
                continue

            path, artifact = selected
            summary = self._summary_from_payload(artifact)
            coverage = self._coverage_from_payload(artifact)
            approximation_gap = self._approximation_gap_from_payload(artifact)
            comparison = self._delta(dict(scenario_metrics.get(scenario) or {}), summary)
            generated_at = self._artifact_generated_at(payload=artifact, path=path).isoformat()
            scenarios_with_artifacts += 1
            replay_trade_rows += int(summary.get("trades", 0) or 0)
            if summary:
                scenarios_compared += 1
                comparison_to_approximation[scenario] = comparison
            scenario_outputs[scenario] = {
                "available": True,
                "reason": "artifact_loaded",
                "artifact_path": str(path),
                "generated_at": generated_at,
                "summary": summary,
                "coverage": coverage,
                "approximation_gap": approximation_gap,
                "comparison_to_approximation": comparison,
                "worker_mode": str(artifact.get("worker_mode", "unknown") or "unknown"),
                "input_lineage_summary": self._input_lineage_summary_from_payload(artifact),
            }

        available = scenarios_with_artifacts > 0
        comparison_ready = scenarios_compared > 0
        lineage_summary = self._lineage_summary(scenario_outputs=scenario_outputs)
        if not available:
            blocked_by.append("stress_replay_worker_output_artifacts_missing")
            next_steps.append("connect prototype replay worker to write scenario output artifacts")
            reason = "no_replay_worker_output_artifacts"
        elif scenarios_with_artifacts < len(self._SCENARIO_ORDER):
            blocked_by.append("stress_replay_worker_output_artifacts_partial")
            next_steps.append("complete replay worker outputs for remaining stress scenarios")
            reason = "partial_replay_worker_output_artifacts"
        else:
            next_steps.append("compare replay-derived outputs against approximation before replacing stress heuristics")
            reason = "replay_worker_output_artifacts_loaded"

        payload: dict[str, Any] = {
            "schema_version": self._SCHEMA_VERSION,
            "symbol": symbol,
            "version": version,
            "generated_at": now.isoformat(),
            "available": available,
            "comparison_ready": comparison_ready,
            "reason": reason,
            "evaluation_basis": "latest replay worker output artifact per scenario vs stress approximation scenario_metrics",
            "summary_counts": {
                "scenarios_expected": len(self._SCENARIO_ORDER),
                "scenarios_with_artifacts": scenarios_with_artifacts,
                "scenarios_compared": scenarios_compared,
                "replay_trade_rows": replay_trade_rows,
            },
            "artifact_contract": {
                "schema_version": self._WORKER_OUTPUT_SCHEMA_VERSION,
                "required_top_level_fields": ["schema_version", "generated_at", "symbol", "version", "scenario", "summary"],
                "required_summary_fields": ["trades", "ev", "p5_ev", "max_drawdown", "ulcer_index"],
                "supported_scenarios": list(self._SCENARIO_ORDER),
                "artifact_path_pattern": "reports/validation/stress_replay_worker_outputs/<SYMBOL>/<VERSION>/<SCENARIO>_<UTC>.json",
            },
            "lineage_summary": lineage_summary,
            "scenario_outputs": scenario_outputs,
            "comparison_to_approximation": comparison_to_approximation,
            "blocked_by": blocked_by,
            "next_steps": next_steps,
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload
