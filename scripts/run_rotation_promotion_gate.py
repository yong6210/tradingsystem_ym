#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.report_io import atomic_write_text


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research-only promotion gate for rotation candidates."
    )
    parser.add_argument("--candidate-report", required=True)
    parser.add_argument("--anti-overfit-reports", nargs="*", default=[])
    parser.add_argument("--walkforward-reports", nargs="*", default=[])
    parser.add_argument("--max-dd-pct", type=float, default=45.0)
    parser.add_argument("--max-research-dd-pct", type=float, default=50.0)
    parser.add_argument("--min-x", type=float, default=3.0)
    parser.add_argument("--min-wf-x", type=float, default=3.0)
    parser.add_argument("--min-wf-annualized-return-pct", type=float, default=25.0)
    parser.add_argument("--max-wf-period-dd-pct", type=float, default=35.0)
    parser.add_argument("--min-wf-positive-fraction", type=float, default=0.50)
    parser.add_argument("--require-audit-pass", action="store_true", default=True)
    parser.add_argument("--require-walkforward-pass", action="store_true", default=False)
    parser.add_argument("--report-dir", default="reports/validation/rotation_promotion_gate")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _as_float(value: Any, default: float = math.nan) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _load_json(raw_path: str) -> tuple[Path, dict[str, Any]]:
    path = Path(raw_path)
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path, json.loads(path.read_text())


def _relpath(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _candidate_metrics(report: dict[str, Any]) -> dict[str, Any]:
    walk_forward = dict(report.get("walk_forward") or {})
    aggregate = dict(report.get("aggregate") or {})
    if aggregate:
        ending_x = _as_float(aggregate.get("ending_equity_multiple"))
        period_step_dd = _as_float(aggregate.get("max_drawdown_on_period_steps_pct"))
        selected_period_dd = _as_float(aggregate.get("max_selected_period_drawdown_pct"))
        dd_values = [value for value in (period_step_dd, selected_period_dd) if math.isfinite(value)]
        return {
            "report_type": "bar_resim_walk_forward",
            "model": "causal_selector",
            "min_x": ending_x,
            "geo": ending_x,
            "max_dd_pct": max(dd_values) if dd_values else math.nan,
            "max_drawdown_on_period_steps_pct": period_step_dd,
            "max_selected_period_drawdown_pct": selected_period_dd,
            "annualized_return_pct": _as_float(aggregate.get("annualized_return_pct")),
            "positive_fraction": _as_float(aggregate.get("positive_period_fraction")),
            "scenario_count": int(aggregate.get("test_period_count") or 0),
            "limitations": list(dict(report.get("method") or {}).get("limitations") or []),
        }
    if walk_forward:
        ending_x = _as_float(walk_forward.get("ending_equity_multiple"))
        period_step_dd = _as_float(walk_forward.get("max_drawdown_on_period_steps_pct"))
        selected_period_dd = _as_float(walk_forward.get("max_selected_period_drawdown_pct"))
        dd_values = [value for value in (period_step_dd, selected_period_dd) if math.isfinite(value)]
        return {
            "report_type": "walk_forward",
            "model": "causal_selector",
            "min_x": ending_x,
            "geo": ending_x,
            "max_dd_pct": max(dd_values) if dd_values else math.nan,
            "max_drawdown_on_period_steps_pct": period_step_dd,
            "max_selected_period_drawdown_pct": selected_period_dd,
            "annualized_return_pct": _as_float(walk_forward.get("annualized_return_pct")),
            "positive_fraction": _as_float(walk_forward.get("positive_year_fraction")),
            "scenario_count": int(walk_forward.get("test_period_count") or 0),
            "limitations": list(dict(report.get("method") or {}).get("limitations") or []),
        }
    rows = list(report.get("all_results") or [])
    if rows:
        ranked = sorted(
            rows,
            key=lambda row: (
                _as_float(dict(row.get("summary") or {}).get("score"), 0.0),
                _as_float(dict(row.get("summary") or {}).get("cagr_pct"), 0.0),
            ),
            reverse=True,
        )
        summary = dict(dict(ranked[0]).get("summary") or {}) if ranked else {}
        total_return_pct = _as_float(summary.get("total_return_pct"), 0.0)
        return {
            "report_type": "all_results",
            "model": summary.get("model_id"),
            "min_x": 1.0 + total_return_pct / 100.0,
            "geo": 1.0 + total_return_pct / 100.0,
            "max_dd_pct": _as_float(summary.get("max_drawdown_pct")),
            "annualized_return_pct": _as_float(summary.get("cagr_pct")),
            "positive_fraction": _as_float(summary.get("positive_year_fraction")),
            "scenario_count": len(rows),
            "worst_year_pct": _as_float(summary.get("worst_year_pct")),
        }
    results = list(report.get("results") or [])
    if not results:
        return {}
    result = dict(results[0])
    return {
        "report_type": "rotation_scenario",
        "mix": result.get("mix"),
        "geo": _as_float(result.get("geo")),
        "min_x": _as_float(result.get("min_x")),
        "max_dd_pct": _as_float(result.get("max_dd_pct")),
        "min_worst_year_pct": _as_float(result.get("min_worst_year_pct")),
        "scenario_count": len(result.get("rows") or []),
    }


def _audit_summary(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    verdict = dict(report.get("verdict") or {})
    split = dict(report.get("split_audit") or {})
    holdout = dict(report.get("holdout_audit") or {})
    return {
        "path": _relpath(path),
        "level": str(verdict.get("level") or "UNKNOWN"),
        "issues": list(verdict.get("issues") or []),
        "period": dict(report.get("input") or {}).get("period"),
        "pbo_proxy": split.get("pbo_proxy"),
        "split_sampling": split.get("split_sampling"),
        "evaluated_split_count": split.get("evaluated_split_count"),
        "selected_holdout_rank_pct": holdout.get("selected_test_rank_pct"),
        "test_periods": holdout.get("test_periods"),
        "test_winner_candidate_id": holdout.get("test_winner_candidate_id"),
    }


def _walkforward_summary(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    walk_forward = dict(report.get("walk_forward") or {})
    aggregate = dict(report.get("aggregate") or {})
    method = dict(report.get("method") or {})
    if aggregate:
        return {
            "path": _relpath(path),
            "period": aggregate.get("period"),
            "selector_mode": aggregate.get("selector_mode"),
            "test_period_count": aggregate.get("test_period_count"),
            "ending_equity_multiple": aggregate.get("ending_equity_multiple"),
            "total_return_pct": aggregate.get("total_return_pct"),
            "annualized_return_pct": aggregate.get("annualized_return_pct"),
            "max_drawdown_on_period_steps_pct": aggregate.get("max_drawdown_on_period_steps_pct"),
            "max_selected_period_drawdown_pct": aggregate.get("max_selected_period_drawdown_pct"),
            "positive_fraction": aggregate.get("positive_period_fraction"),
            "limitations": list(method.get("limitations") or []),
        }
    return {
        "path": _relpath(path),
        "period": walk_forward.get("period"),
        "selector_mode": method.get("selector_mode"),
        "test_period_count": walk_forward.get("test_period_count"),
        "ending_equity_multiple": walk_forward.get("ending_equity_multiple"),
        "total_return_pct": walk_forward.get("total_return_pct"),
        "annualized_return_pct": walk_forward.get("annualized_return_pct"),
        "max_drawdown_on_period_steps_pct": walk_forward.get("max_drawdown_on_period_steps_pct"),
        "max_selected_period_drawdown_pct": walk_forward.get("max_selected_period_drawdown_pct"),
        "positive_fraction": walk_forward.get("positive_year_fraction"),
        "limitations": list(method.get("limitations") or []),
    }


def main() -> int:
    args = _parse_args()
    candidate_path, candidate_report = _load_json(str(args.candidate_report))
    candidate_metrics = _candidate_metrics(candidate_report)
    audits: list[dict[str, Any]] = []
    for raw_path in args.anti_overfit_reports:
        path, report = _load_json(str(raw_path))
        audits.append(_audit_summary(path, report))
    walkforwards: list[dict[str, Any]] = []
    for raw_path in args.walkforward_reports:
        path, report = _load_json(str(raw_path))
        walkforwards.append(_walkforward_summary(path, report))

    blocking_reasons: list[str] = []
    report_type = str(candidate_metrics.get("report_type") or "rotation_scenario")
    max_dd = _as_float(candidate_metrics.get("max_dd_pct"), 100.0)
    min_x = _as_float(candidate_metrics.get("min_x"), 0.0)
    scenario_count = int(candidate_metrics.get("scenario_count") or 0)
    if report_type == "rotation_scenario" and scenario_count < 20:
        blocking_reasons.append("candidate_not_validated_on_full_20_scenarios")
    if max_dd > float(args.max_research_dd_pct):
        blocking_reasons.append("candidate_dd_above_research_limit")
    if max_dd > float(args.max_dd_pct):
        blocking_reasons.append("candidate_dd_above_live_limit")
    if min_x < float(args.min_x):
        blocking_reasons.append("candidate_min_x_below_limit")
    failed_audits = [audit for audit in audits if audit["level"] != "PASS"]
    if bool(args.require_audit_pass) and failed_audits:
        blocking_reasons.append("anti_overfit_audit_failed")
    if bool(args.require_audit_pass) and not audits:
        blocking_reasons.append("anti_overfit_audit_missing")
    failed_walkforwards: list[dict[str, Any]] = []
    for wf in walkforwards:
        wf_x = _as_float(wf.get("ending_equity_multiple"), 0.0)
        wf_return = _as_float(wf.get("annualized_return_pct"), -100.0)
        wf_dd = max(
            _as_float(wf.get("max_drawdown_on_period_steps_pct"), 100.0),
            _as_float(wf.get("max_selected_period_drawdown_pct"), 0.0),
        )
        wf_positive = _as_float(wf.get("positive_fraction"), 0.0)
        failed = (
            wf_x < float(args.min_wf_x)
            or wf_return < float(args.min_wf_annualized_return_pct)
            or wf_dd > float(args.max_wf_period_dd_pct)
            or wf_positive < float(args.min_wf_positive_fraction)
        )
        if failed:
            failed_walkforwards.append(wf)
    if bool(args.require_walkforward_pass) and failed_walkforwards:
        blocking_reasons.append("walkforward_validation_failed")
    if bool(args.require_walkforward_pass) and not walkforwards:
        blocking_reasons.append("walkforward_validation_missing")

    research_allowed = (
        scenario_count >= (5 if report_type != "rotation_scenario" else 20)
        and max_dd <= float(args.max_research_dd_pct)
        and min_x >= float(args.min_x)
    )
    promotion_allowed = not blocking_reasons
    payload = {
        "schema_version": "rotation_promotion_gate_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "authority": "research_only_no_live_authority_change",
        "candidate_report": _relpath(candidate_path),
        "candidate_metrics": candidate_metrics,
        "audits": audits,
        "walkforwards": walkforwards,
        "decision": {
            "level": "PASS" if promotion_allowed else "BLOCK",
            "research_allowed": research_allowed,
            "paper_shadow_allowed": research_allowed and not promotion_allowed,
            "live_trading_allowed": False,
            "promotion_allowed": promotion_allowed,
            "blocking_reasons": blocking_reasons,
        },
        "policy": {
            "max_dd_pct": float(args.max_dd_pct),
            "max_research_dd_pct": float(args.max_research_dd_pct),
            "min_x": float(args.min_x),
            "min_wf_x": float(args.min_wf_x),
            "min_wf_annualized_return_pct": float(args.min_wf_annualized_return_pct),
            "max_wf_period_dd_pct": float(args.max_wf_period_dd_pct),
            "min_wf_positive_fraction": float(args.min_wf_positive_fraction),
            "require_audit_pass": bool(args.require_audit_pass),
            "require_walkforward_pass": bool(args.require_walkforward_pass),
        },
    }

    print(
        json.dumps(
            {
                "decision": payload["decision"]["level"],
                "blocking_reasons": blocking_reasons,
                "research_allowed": payload["decision"]["research_allowed"],
                "paper_shadow_allowed": payload["decision"]["paper_shadow_allowed"],
                "live_trading_allowed": payload["decision"]["live_trading_allowed"],
            },
            ensure_ascii=False,
        )
    )
    if args.write_report:
        report_dir = ROOT_DIR / str(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = report_dir / f"rotation_promotion_gate_{stamp}.json"
        atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
        atomic_write_text(report_dir / "latest.json", json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
        print(json.dumps({"report_path": _relpath(path), "latest_report_path": _relpath(report_dir / "latest.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
