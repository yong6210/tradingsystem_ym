from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings


class StrategyV2PboDsrDesignService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.validation_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / (
            f"strategy_v2_pbo_dsr_design_{payload['symbol']}_{payload['version']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        )

        pbo = dict(payload.get("pbo") or {})
        dsr = dict(payload.get("dsr") or {})
        artifact_store = dict(payload.get("artifact_store") or {})
        lines = [
            f"# Strategy v2 PBO / DSR Design: {payload['symbol']}",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- strategy_version: {payload['version']}",
            f"- design_ready: {payload['design_ready']}",
            f"- implementation_status: {payload['implementation_status']}",
            f"- reason: {payload['reason']}",
            "",
            "## PBO Design",
            f"- method: {pbo.get('method', 'CSCV')}",
            f"- objective_metric: {pbo.get('objective_metric', 'out_of_sample_mean_ev')}",
            f"- pass_threshold: {float(pbo.get('pass_threshold', 0.20)):.2f}",
            f"- warn_threshold: {float(pbo.get('warn_threshold', 0.35)):.2f}",
            f"- fail_threshold: {float(pbo.get('fail_threshold', 0.35)):.2f}",
            f"- parameter_families: {pbo.get('parameter_families', [])}",
            f"- required_inputs: {pbo.get('required_inputs', [])}",
            "",
            "## DSR Design",
            f"- method: {dsr.get('method', 'deflated_sharpe_ratio')}",
            f"- min_threshold: {float(dsr.get('min_threshold', 0.0)):.2f}",
            f"- required_inputs: {dsr.get('required_inputs', [])}",
            f"- selection_bias_inputs: {dsr.get('selection_bias_inputs', [])}",
            "",
            "## Proposed Storage Contract",
            f"- artifacts: {(payload.get('storage_contract') or {}).get('artifacts', [])}",
            f"- fields: {(payload.get('storage_contract') or {}).get('required_fields', [])}",
            "",
            "## Runtime Artifact Store",
            f"- artifact_store_ready: {bool(artifact_store.get('artifact_store_ready', False))}",
            f"- available: {bool(artifact_store.get('available', False))}",
            f"- metrics_available: {bool(artifact_store.get('metrics_available', False))}",
            f"- implementation_status: {artifact_store.get('implementation_status', 'not_available')}",
            f"- counts: {(artifact_store.get('counts') or {})}",
            f"- selection_rule_counts: {(artifact_store.get('selection_rule_counts') or {})}",
            "",
            "## Blockers",
        ]
        for item in payload.get("blocked_by", []):
            lines.append(f"- {item}")
        lines.extend(
            [
                "",
                "## Next Implementation Steps",
            ]
        )
        for item in payload.get("next_steps", []):
            lines.append(f"- {item}")
        lines.extend(["", "## Notes"])
        if bool(payload.get("available", False)):
            lines.append("- This artifact now coexists with computed runtime PBO / DSR metrics; design readiness remains the contract source.")
        else:
            lines.append("- This artifact freezes the future PBO / DSR contract but does not compute either metric yet.")
        lines.extend(
            [
                "- The runtime validation path can now expose design readiness without overstating implementation status.",
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
        artifact_store: dict[str, Any] | None = None,
        write_report: bool = True,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        artifact_store = dict(artifact_store or {})
        artifact_ready = bool(artifact_store.get("artifact_store_ready", False))
        artifact_available = bool(artifact_store.get("available", False))
        artifact_metrics_available = bool(artifact_store.get("metrics_available", False))
        selection_rule_counts = dict(artifact_store.get("selection_rule_counts") or {})
        has_true_threshold_runner = "true_threshold_sweep_top_in_sample_ev" in selection_rule_counts
        has_runtime_proxy = "runtime_validation_proxy_top_in_sample_ev" in selection_rule_counts
        if artifact_metrics_available:
            implementation_status = "design_ready_metrics_available_runtime"
            reason = "pbo_dsr_runtime_metrics_available"
            blocked_by: list[str] = []
            next_steps = ["compare computed PBO/DSR against validation protocol thresholds"]
        elif artifact_ready and artifact_available and has_true_threshold_runner and has_runtime_proxy:
            implementation_status = "design_ready_dual_lineage_seeded_metrics_pending"
            reason = "pbo_dsr_dual_lineage_seeded_metrics_pending"
            blocked_by = [
                "PBO/DSR metrics are not computed yet",
                "threshold-sweep bias-adjusted DSR snapshot is not available yet",
            ]
            next_steps = [
                "compute PBO/DSR and persist snapshot-level selection_universe_basis",
                "audit selected-trial source between runtime proxy and true threshold runner lineages",
                "persist selected trial writer_source into snapshots and reports",
            ]
        elif artifact_ready and artifact_available:
            implementation_status = "design_ready_artifact_store_seeded_not_computed"
            reason = "pbo_dsr_artifact_store_seeded_metrics_pending"
            blocked_by = [
                "PBO/DSR metrics are not computed yet",
                "selection-universe split recording may still be incomplete",
            ]
            next_steps = [
                "compute PBO from selected-vs-oos rank inversions",
                "compute DSR from best-trial Sharpe with trial-count adjustment",
                "seed separated true threshold runner lineage when threshold families are available",
            ]
        elif artifact_ready:
            implementation_status = "design_ready_artifact_store_schema_ready_empty"
            reason = "pbo_dsr_artifact_store_ready_not_populated"
            blocked_by = [
                "runtime proxy trial writer has no eligible closed v2 trades yet",
                "fold-level trial ranking contract exists but is not populated",
                "selection-universe split recording is not available",
            ]
            next_steps = [
                "run validation/report after enough eligible closed v2 trades",
                "persist CSCV fold scores and selection ranks",
                "connect threshold-sweep trial families when available",
            ]
        else:
            implementation_status = "design_ready_not_computed"
            reason = "pbo_dsr_contract_frozen_runtime_pending"
            blocked_by = [
                "parameter sweep result store is not implemented",
                "fold-level trial ranking contract is not persisted",
                "selection-universe split recording is not available",
            ]
            next_steps = [
                "add parameter sweep artifact store",
                "persist CSCV fold scores and selection ranks",
                "compute PBO from selected-vs-oos rank inversions",
                "compute DSR from best-trial Sharpe with trial-count adjustment",
            ]
        payload: dict[str, Any] = {
            "schema_version": "strategy_v2_pbo_dsr_design_v1",
            "symbol": symbol,
            "version": version,
            "generated_at": now.isoformat(),
            "design_ready": True,
            "available": bool(artifact_metrics_available),
            "implementation_status": implementation_status,
            "reason": reason,
            "pbo": {
                "method": "CSCV",
                "objective_metric": "out_of_sample_mean_ev",
                "pass_threshold": 0.20,
                "warn_threshold": 0.35,
                "fail_threshold": 0.35,
                "parameter_families": [
                    "scoring_thresholds",
                    "transition_threshold",
                    "acceptance_rejection_thresholds",
                    "sizing_clamps",
                ],
                "required_inputs": [
                    "parameter_sweep_trials",
                    "fold_level_out_of_sample_scores",
                    "selected_vs_non_selected_rankings",
                ],
            },
            "dsr": {
                "method": "deflated_sharpe_ratio",
                "min_threshold": 0.0,
                "required_inputs": [
                    "trade_sequence_returns",
                    "trial_count",
                    "selection_universe_size",
                    "sharpe_estimate",
                    "return_skew_kurtosis",
                ],
                "selection_bias_inputs": [
                    "number_of_trials",
                    "selection_rule",
                    "best_trial_oos_sharpe",
                ],
            },
            "storage_contract": {
                "artifacts": [
                    "validation_trial_runs",
                    "validation_trial_fold_scores",
                    "validation_pbo_dsr_snapshots",
                ],
                "required_fields": [
                    "trial_id",
                    "parameter_family",
                    "parameter_values",
                    "fold_id",
                    "in_sample_metric",
                    "out_of_sample_metric",
                    "selection_rank",
                    "selected_flag",
                    "sharpe_like_score",
                ],
            },
            "artifact_store": {
                "artifact_store_ready": artifact_ready,
                "available": artifact_available,
                "metrics_available": artifact_metrics_available,
                "implementation_status": artifact_store.get("implementation_status", "not_available"),
                "counts": dict(artifact_store.get("counts") or {}),
                "selection_rule_counts": selection_rule_counts,
                "latest_snapshot": dict(artifact_store.get("latest_snapshot") or {}),
            },
            "blocked_by": blocked_by,
            "next_steps": next_steps,
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload
