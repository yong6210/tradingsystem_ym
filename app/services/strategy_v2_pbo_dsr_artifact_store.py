from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.db.models import ValidationPboDsrSnapshot
from app.db.repositories import ValidationArtifactRepository
from app.services.report_io import atomic_write_text


class StrategyV2PboDsrArtifactStoreService:
    _RUNTIME_PROXY_SELECTION_RULE_PREFIXES = ("runtime_validation_proxy",)
    _TRUE_THRESHOLD_SELECTION_RULE_PREFIXES = ("true_threshold_sweep",)

    def __init__(
        self,
        settings: Settings | None = None,
        repo: ValidationArtifactRepository | None = None,
    ):
        self.settings = settings or get_settings()
        self.repo = repo

    @staticmethod
    def _snapshot_payload(row: ValidationPboDsrSnapshot | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "snapshot_id": row.snapshot_id,
            "selected_trial_run_id": row.selected_trial_run_id,
            "trial_run_count": int(row.trial_run_count or 0),
            "fold_score_count": int(row.fold_score_count or 0),
            "selection_universe_size": row.selection_universe_size,
            "pbo_value": row.pbo_value,
            "dsr_value": row.dsr_value,
            "pbo_available": bool(row.pbo_available),
            "dsr_available": bool(row.dsr_available),
            "computation_state": row.computation_state,
            "payload": dict(row.payload or {}),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def _status_payload(
        self,
        *,
        counts: dict[str, int],
        latest_snapshot: ValidationPboDsrSnapshot | None,
        selection_universe_sizes: list[int],
        selection_rule_counts: dict[str, int],
    ) -> tuple[str, str, list[str], list[str], bool]:
        seeded = any(int(value or 0) > 0 for value in counts.values())
        has_true_threshold_runner = "true_threshold_sweep_top_in_sample_ev" in selection_rule_counts
        has_runtime_proxy = "runtime_validation_proxy_top_in_sample_ev" in selection_rule_counts
        if not seeded:
            return (
                "artifact_store_schema_ready_empty",
                "artifact_store_tables_ready_not_populated",
                [
                    "runtime proxy trial writer has not seeded validation_trial_runs yet",
                    "fold-level CSCV scores have not been written yet",
                    "PBO/DSR metrics are not computed yet",
                ],
                [
                    "run validation/report after enough eligible closed v2 trades",
                    "keep runtime proxy trial writer enabled until a separated true threshold runner can seed trials",
                    "persist CSCV fold scores into validation_trial_fold_scores",
                    "write summary snapshots into validation_pbo_dsr_snapshots",
                ],
                False,
            )

        if latest_snapshot is None:
            return (
                "artifact_store_seeded_no_snapshot",
                "artifact_store_seeded_snapshot_missing",
                [
                    "snapshot rows are not being written yet",
                    "PBO/DSR metrics are not computed yet",
                ],
                [
                    "keep runtime proxy trial/fold lineage seeded before metric computation",
                    "keep true threshold-sweep lineage seeded when trial families are available",
                    "write summary snapshots into validation_pbo_dsr_snapshots",
                    "compute PBO from selected-vs-oos rank inversions",
                    "compute DSR from best-trial Sharpe with trial-count adjustment",
                ],
                False,
            )

        if latest_snapshot.pbo_available and latest_snapshot.dsr_available:
            return (
                "artifact_store_metrics_available",
                "artifact_store_contains_computed_metrics",
                [],
                ["keep fold/trial snapshot lineage intact for future validations"],
                True,
            )

        blocked_by = ["PBO/DSR metrics are not computed yet"]
        if not selection_universe_sizes:
            blocked_by.append("selection-universe split recording is not available")
        next_steps = [
            "compute PBO from selected-vs-oos rank inversions",
            "compute DSR from best-trial Sharpe with trial-count adjustment",
            "preserve split selection-universe recording on snapshots and selected trials",
        ]
        if has_true_threshold_runner and has_runtime_proxy:
            next_steps.insert(0, "audit runtime proxy lineage vs true threshold runner lineage before deployment")
        return (
            "artifact_store_seeded_not_computed",
            "artifact_store_seeded_metrics_pending",
            blocked_by,
            next_steps,
            False,
        )

    @classmethod
    def _lineage_count(cls, selection_rule_counts: dict[str, int], prefixes: tuple[str, ...]) -> int:
        total = 0
        for key, value in selection_rule_counts.items():
            if str(key).startswith(prefixes):
                total += int(value or 0)
        return total

    @classmethod
    def _selection_universe_summary(
        cls,
        *,
        trial_runs: list[Any],
        selection_rule_counts: dict[str, int],
        latest_snapshot: ValidationPboDsrSnapshot | None,
    ) -> dict[str, Any]:
        latest_payload = dict((latest_snapshot.payload or {}) if latest_snapshot is not None else {})
        latest_summary = dict(latest_payload.get("selection_universe_summary") or {})
        runtime_proxy_universe = cls._lineage_count(
            selection_rule_counts=selection_rule_counts,
            prefixes=cls._RUNTIME_PROXY_SELECTION_RULE_PREFIXES,
        )
        true_threshold_universe = cls._lineage_count(
            selection_rule_counts=selection_rule_counts,
            prefixes=cls._TRUE_THRESHOLD_SELECTION_RULE_PREFIXES,
        )
        full_parameter_sweep_universe = true_threshold_universe if true_threshold_universe > 0 else None
        return {
            "combined_artifact_selection_universe_size": len(trial_runs),
            "runtime_proxy_selection_universe_size": runtime_proxy_universe,
            "true_threshold_selection_universe_size": true_threshold_universe,
            "full_parameter_sweep_selection_universe_size": full_parameter_sweep_universe,
            "snapshot_dsr_selection_universe_size": (
                int(latest_snapshot.selection_universe_size) if latest_snapshot and latest_snapshot.selection_universe_size is not None else None
            ),
            "snapshot_dsr_selection_universe_basis": latest_summary.get("dsr_selection_universe_basis", "not_recorded"),
            "selected_trial_lineage_selection_universe_size": latest_summary.get(
                "selected_trial_lineage_selection_universe_size"
            ),
            "recording_status": "split_recorded" if full_parameter_sweep_universe is not None else "combined_only",
        }

    def _write_report(self, *, payload: dict[str, Any], now: datetime) -> str:
        out_dir = Path(self.settings.validation_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / (
            f"strategy_v2_pbo_dsr_artifact_store_{payload['symbol']}_{payload['version']}_{now.strftime('%Y%m%dT%H%M%SZ')}.md"
        )

        lines = [
            f"# Strategy v2 PBO / DSR Artifact Store: {payload['symbol']}",
            "",
            f"- generated_at_utc: {payload['generated_at']}",
            f"- strategy_version: {payload['version']}",
            f"- artifact_store_ready: {payload['artifact_store_ready']}",
            f"- available: {payload['available']}",
            f"- implementation_status: {payload['implementation_status']}",
            f"- reason: {payload['reason']}",
            "",
            "## Counts",
            f"- trial_runs: {int((payload.get('counts') or {}).get('trial_runs', 0))}",
            f"- fold_scores: {int((payload.get('counts') or {}).get('fold_scores', 0))}",
            f"- snapshots: {int((payload.get('counts') or {}).get('snapshots', 0))}",
            f"- parameter_families_present: {payload.get('parameter_families_present', [])}",
            f"- selection_rule_counts: {payload.get('selection_rule_counts', {})}",
            f"- selection_universe_sizes: {payload.get('selection_universe_sizes', [])}",
            f"- selection_universe_summary: {payload.get('selection_universe_summary', {})}",
            "",
            "## Latest Snapshot",
        ]
        latest_snapshot = dict(payload.get("latest_snapshot") or {})
        if latest_snapshot:
            lines.extend(
                [
                    f"- snapshot_id: {latest_snapshot.get('snapshot_id')}",
                    f"- selected_trial_run_id: {latest_snapshot.get('selected_trial_run_id')}",
                    f"- computation_state: {latest_snapshot.get('computation_state')}",
                    f"- pbo_available: {latest_snapshot.get('pbo_available')}",
                    f"- dsr_available: {latest_snapshot.get('dsr_available')}",
                    f"- pbo_value: {latest_snapshot.get('pbo_value')}",
                    f"- dsr_value: {latest_snapshot.get('dsr_value')}",
                ]
            )
        else:
            lines.append("- none")
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
                "- This artifact reports schema and population readiness only.",
                "- Runtime proxy trial/fold lineage may seed this store before a true threshold sweep exists.",
                "",
            ]
        )
        atomic_write_text(file_path, "\n".join(lines))
        return str(file_path)

    def generate(self, *, symbol: str, version: str, write_report: bool = True) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        if self.repo is None:
            raise RuntimeError("ValidationArtifactRepository is required")

        counts = self.repo.counts(symbol=symbol, version=version)
        trial_runs = self.repo.list_trial_runs(symbol=symbol, version=version, limit=1000)
        latest_snapshot = self.repo.latest_snapshot(symbol=symbol, version=version)
        selection_rule_counts = self.repo.selection_rule_counts(symbol=symbol, version=version)
        parameter_families_present = sorted({str(row.parameter_family) for row in trial_runs if row.parameter_family})
        selection_universe_sizes = sorted(
            {
                int(size)
                for size in [
                    *(row.selection_universe_size for row in trial_runs),
                    latest_snapshot.selection_universe_size if latest_snapshot else None,
                ]
                if size is not None
            }
        )
        selection_universe_summary = self._selection_universe_summary(
            trial_runs=trial_runs,
            selection_rule_counts=selection_rule_counts,
            latest_snapshot=latest_snapshot,
        )
        implementation_status, reason, blocked_by, next_steps, metrics_available = self._status_payload(
            counts=counts,
            latest_snapshot=latest_snapshot,
            selection_universe_sizes=selection_universe_sizes,
            selection_rule_counts=selection_rule_counts,
        )

        payload: dict[str, Any] = {
            "schema_version": "strategy_v2_pbo_dsr_artifact_store_v1",
            "symbol": symbol,
            "version": version,
            "generated_at": now.isoformat(),
            "artifact_store_ready": True,
            "available": any(int(value or 0) > 0 for value in counts.values()),
            "metrics_available": metrics_available,
            "implementation_status": implementation_status,
            "reason": reason,
            "counts": counts,
            "parameter_families_present": parameter_families_present,
            "selection_rule_counts": selection_rule_counts,
            "selection_universe_sizes": selection_universe_sizes,
            "selection_universe_summary": selection_universe_summary,
            "latest_snapshot": self._snapshot_payload(latest_snapshot),
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
            "blocked_by": blocked_by,
            "next_steps": next_steps,
            "report_path": None,
        }
        if write_report:
            payload["report_path"] = self._write_report(payload=payload, now=now)
        return payload
