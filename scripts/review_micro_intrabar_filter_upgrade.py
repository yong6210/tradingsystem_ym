#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.report_io import atomic_write_text


DEFAULT_CONTRACT_PATH = ROOT_DIR / "reports/operations/micro_intrabar_paper_candidate_contract/latest.json"
DEFAULT_BASELINE_FILTER_POLICY = "volume12_body025_hour13_14_long"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare the active micro intrabar filter against the prior baseline filter.")
    parser.add_argument("--contract-path", default=str(DEFAULT_CONTRACT_PATH))
    parser.add_argument("--subset-report-path", default="")
    parser.add_argument("--baseline-filter-policy", default=DEFAULT_BASELINE_FILTER_POLICY)
    parser.add_argument("--candidate-filter-policy", default="")
    parser.add_argument("--exit-policy", default="")
    parser.add_argument("--report-dir", default="reports/operations/micro_intrabar_filter_upgrade_review")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _resolve_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed == parsed else default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _report_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def _infer_subset_report_path(contract: dict[str, Any]) -> Path:
    source_path = str(dict(contract.get("candidate") or {}).get("source_path") or "").strip()
    if not source_path:
        raise ValueError("contract candidate has no source_path")
    return _resolve_path(source_path)


def _candidate_filter_policy(contract: dict[str, Any], override: str = "") -> str:
    if override.strip():
        return override.strip()
    return str(dict(contract.get("paper_contract") or {}).get("policy_name") or "").strip()


def _candidate_exit_policy(contract: dict[str, Any], override: str = "") -> str:
    if override.strip():
        return override.strip()
    paper_contract = dict(contract.get("paper_contract") or {})
    name = str(paper_contract.get("exit_policy_name") or "").strip()
    if name:
        return name
    source_names = [
        str(item).strip()
        for item in list(dict(contract.get("candidate") or {}).get("source_policy_names") or [])
        if str(item).strip()
    ]
    return source_names[0] if source_names else ""


def _subset_result(payload: dict[str, Any], filter_policy_name: str) -> dict[str, Any] | None:
    for item in list(payload.get("results") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "") == filter_policy_name:
            return item
    return None


def _policy_row(subset_result: dict[str, Any] | None, exit_policy_name: str) -> dict[str, Any] | None:
    if subset_result is None:
        return None
    for item in list(subset_result.get("by_policy") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("policy") or "") == exit_policy_name:
            return item
    return None


def _metric_snapshot(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {}
    summary = dict(row.get("summary") or {})
    stress = dict(row.get("cost_stress") or {})
    extra_005 = dict(stress.get("extra_0_05r_per_trade") or {})
    cost_x2 = dict(stress.get("cost_x2_0") or {})
    cost_x2_extra = dict(stress.get("cost_x2_0_extra_0_03r_per_trade") or {})
    return {
        "policy": row.get("policy"),
        "closed": _safe_int(summary.get("closed")),
        "total_r": round(_safe_float(summary.get("total_r")), 4),
        "ev_r": round(_safe_float(summary.get("ev_r")), 4),
        "win_rate": round(_safe_float(summary.get("win_rate")), 4),
        "max_dd_r": round(_safe_float(summary.get("max_dd_r")), 4),
        "profit_to_dd": round(_safe_float(summary.get("profit_to_dd")), 4),
        "positive_symbol_fraction": round(_safe_float(summary.get("positive_symbol_fraction")), 4),
        "positive_year_fraction": round(_safe_float(summary.get("positive_year_fraction")), 4),
        "extra_0_05r_total_r": round(_safe_float(extra_005.get("total_r")), 4),
        "extra_0_05r_positive_symbol_fraction": round(_safe_float(extra_005.get("positive_symbol_fraction")), 4),
        "extra_0_05r_positive_year_fraction": round(_safe_float(extra_005.get("positive_year_fraction")), 4),
        "cost_x2_total_r": round(_safe_float(cost_x2.get("total_r")), 4),
        "cost_x2_extra_0_03r_total_r": round(_safe_float(cost_x2_extra.get("total_r")), 4),
        "exit_reasons": summary.get("exit_reasons") or {},
    }


def _delta(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "closed",
        "total_r",
        "ev_r",
        "win_rate",
        "max_dd_r",
        "profit_to_dd",
        "positive_symbol_fraction",
        "positive_year_fraction",
        "extra_0_05r_total_r",
        "extra_0_05r_positive_symbol_fraction",
        "extra_0_05r_positive_year_fraction",
        "cost_x2_total_r",
        "cost_x2_extra_0_03r_total_r",
    ]
    return {key: round(_safe_float(candidate.get(key)) - _safe_float(baseline.get(key)), 6) for key in keys}


def _decision(candidate: dict[str, Any], baseline: dict[str, Any]) -> tuple[str, list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    if not candidate:
        blockers.append("candidate_filter_policy_missing_from_subset_report")
    if not baseline:
        blockers.append("baseline_filter_policy_missing_from_subset_report")
    if blockers:
        return "UPGRADE_REVIEW_HOLD", blockers
    if _safe_int(candidate.get("closed")) < _safe_int(baseline.get("closed")) * 0.75:
        warnings.append("candidate_trade_count_materially_lower_than_baseline")
    if _safe_float(candidate.get("total_r")) <= _safe_float(baseline.get("total_r")):
        blockers.append("candidate_total_r_not_above_baseline")
    if _safe_float(candidate.get("ev_r")) <= _safe_float(baseline.get("ev_r")):
        blockers.append("candidate_ev_not_above_baseline")
    if _safe_float(candidate.get("profit_to_dd")) <= _safe_float(baseline.get("profit_to_dd")):
        blockers.append("candidate_profit_to_dd_not_above_baseline")
    if _safe_float(candidate.get("max_dd_r")) > _safe_float(baseline.get("max_dd_r")):
        blockers.append("candidate_max_dd_above_baseline")
    if _safe_float(candidate.get("positive_symbol_fraction")) < _safe_float(baseline.get("positive_symbol_fraction")):
        blockers.append("candidate_symbol_consistency_below_baseline")
    if _safe_float(candidate.get("positive_year_fraction")) < _safe_float(baseline.get("positive_year_fraction")):
        blockers.append("candidate_year_consistency_below_baseline")
    if _safe_float(candidate.get("extra_0_05r_total_r")) <= _safe_float(baseline.get("extra_0_05r_total_r")):
        blockers.append("candidate_extra_0_05r_stress_not_above_baseline")
    if _safe_float(candidate.get("extra_0_05r_positive_year_fraction")) < 0.67:
        blockers.append("candidate_extra_0_05r_year_consistency_too_weak")
    if _safe_float(candidate.get("extra_0_05r_positive_symbol_fraction")) < 0.50:
        blockers.append("candidate_extra_0_05r_symbol_consistency_too_weak")
    if _safe_float(candidate.get("cost_x2_total_r")) <= 0.0:
        blockers.append("candidate_cost_x2_stress_not_positive")
    if _safe_float(candidate.get("cost_x2_total_r")) <= _safe_float(baseline.get("cost_x2_total_r")):
        blockers.append("candidate_cost_x2_stress_not_above_baseline")
    if blockers:
        return "UPGRADE_REVIEW_HOLD", blockers + warnings
    return "UPGRADE_SUPPORTED_FOR_PAPER_ONLY", ["candidate_filter_dominates_baseline_on_core_metrics"] + warnings


def build_payload(
    contract_path: Path,
    *,
    subset_report_path: Path | None = None,
    baseline_filter_policy: str = DEFAULT_BASELINE_FILTER_POLICY,
    candidate_filter_policy: str = "",
    exit_policy: str = "",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    contract = _load_json(contract_path)
    subset_report_path = subset_report_path or _infer_subset_report_path(contract)
    subset_payload = _load_json(subset_report_path)
    candidate_filter = _candidate_filter_policy(contract, candidate_filter_policy)
    active_exit_policy = _candidate_exit_policy(contract, exit_policy)
    baseline_result = _subset_result(subset_payload, baseline_filter_policy)
    candidate_result = _subset_result(subset_payload, candidate_filter)
    baseline = _metric_snapshot(_policy_row(baseline_result, active_exit_policy))
    candidate = _metric_snapshot(_policy_row(candidate_result, active_exit_policy))
    state, reasons = _decision(candidate, baseline)
    return {
        "schema_version": "micro_intrabar_filter_upgrade_review_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "filter_review_only_no_order_submission",
        "contract_path": str(contract_path.relative_to(ROOT_DIR) if contract_path.is_relative_to(ROOT_DIR) else contract_path),
        "subset_report_path": str(
            subset_report_path.relative_to(ROOT_DIR) if subset_report_path.is_relative_to(ROOT_DIR) else subset_report_path
        ),
        "baseline_filter_policy": baseline_filter_policy,
        "candidate_filter_policy": candidate_filter,
        "exit_policy": active_exit_policy,
        "recommended_state": state,
        "reasons": reasons,
        "live_action": "KEEP_CLOSE_ONLY",
        "live_ready": False,
        "baseline": baseline,
        "candidate": candidate,
        "delta_candidate_minus_baseline": _delta(candidate, baseline) if candidate and baseline else {},
        "operator_summary": {
            "action": (
                "Keep live entries disabled; candidate filter is supported for paper-only watch."
                if state == "UPGRADE_SUPPORTED_FOR_PAPER_ONLY"
                else "Hold the filter upgrade and inspect blockers."
            ),
            "order_submission_allowed": False,
        },
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    delta = dict(payload.get("delta_candidate_minus_baseline") or {})
    candidate = dict(payload.get("candidate") or {})
    baseline = dict(payload.get("baseline") or {})
    lines = [
        "# Micro Intrabar Filter Upgrade Review",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- authority: {payload.get('authority')}",
        f"- recommended_state: {payload.get('recommended_state')}",
        f"- reasons: {payload.get('reasons')}",
        f"- live_action: {payload.get('live_action')}",
        f"- baseline_filter_policy: {payload.get('baseline_filter_policy')}",
        f"- candidate_filter_policy: {payload.get('candidate_filter_policy')}",
        f"- exit_policy: {payload.get('exit_policy')}",
        f"- baseline_total_r: {baseline.get('total_r')} candidate_total_r: {candidate.get('total_r')} delta: {delta.get('total_r')}",
        f"- baseline_ev: {baseline.get('ev_r')} candidate_ev: {candidate.get('ev_r')} delta: {delta.get('ev_r')}",
        f"- baseline_max_dd: {baseline.get('max_dd_r')} candidate_max_dd: {candidate.get('max_dd_r')} delta: {delta.get('max_dd_r')}",
        f"- baseline_cost_x2_total_r: {baseline.get('cost_x2_total_r')} candidate_cost_x2_total_r: {candidate.get('cost_x2_total_r')} delta: {delta.get('cost_x2_total_r')}",
        "",
        "This review does not submit orders or enable live routing.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    generated_at = datetime.now(UTC)
    contract_path = _resolve_path(args.contract_path)
    subset_path = _resolve_path(args.subset_report_path) if str(args.subset_report_path or "").strip() else None
    payload = build_payload(
        contract_path,
        subset_report_path=subset_path,
        baseline_filter_policy=str(args.baseline_filter_policy),
        candidate_filter_policy=str(args.candidate_filter_policy),
        exit_policy=str(args.exit_policy),
        generated_at=generated_at,
    )
    if args.write_report:
        report_dir = _resolve_path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = _report_stamp(generated_at)
        json_path = report_dir / f"micro_intrabar_filter_upgrade_review_{stamp}.json"
        md_path = report_dir / f"micro_intrabar_filter_upgrade_review_{stamp}.md"
        latest_json = report_dir / "latest.json"
        latest_md = report_dir / "latest.md"
        payload["report_path"] = str(json_path.relative_to(ROOT_DIR) if json_path.is_relative_to(ROOT_DIR) else json_path)
        payload["latest_report_path"] = str(latest_json.relative_to(ROOT_DIR) if latest_json.is_relative_to(ROOT_DIR) else latest_json)
        atomic_write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(md_path, _render_markdown(payload))
        atomic_write_text(latest_json, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(latest_md, _render_markdown(payload))
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
