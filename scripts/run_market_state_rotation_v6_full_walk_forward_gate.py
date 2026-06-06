#!/usr/bin/env python3
"""Gate a v6 candidate against a baseline full walk-forward report."""

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


DEFAULT_BASELINE_REPORT = (
    "reports/validation/diagnostics/market_state_rotation_v6_imp416_f8_f11_buffer_source415/"
    "market_state_rotation_v6_walk_forward_BTCUSDT_5m_latest.json"
)
DEFAULT_CANDIDATE_REPORT = (
    "reports/validation/diagnostics/market_state_rotation_v6_imp473_profitable_low_activity_diag/"
    "market_state_rotation_v6_walk_forward_BTCUSDT_5m_latest.json"
)
DEFAULT_REPORT_DIR = "reports/validation/diagnostics/market_state_rotation_v6_full_walk_forward_gate"


def _resolve(path: str | Path) -> Path:
    raw = Path(path)
    return raw if raw.is_absolute() else ROOT_DIR / raw


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _load_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    aggregate = dict(report.get("aggregate") or {})
    return {
        "fold_count": _int(aggregate.get("fold_count"), len(report.get("folds") or [])),
        "compounded_oos_return_pct": _float(aggregate.get("compounded_oos_return_pct")),
        "avg_oos_return_pct": _float(aggregate.get("avg_oos_return_pct")),
        "min_oos_return_pct": _float(aggregate.get("min_oos_return_pct")),
        "positive_fold_count": _int(aggregate.get("positive_fold_count")),
        "max_fold_drawdown_pct": _float(aggregate.get("max_fold_drawdown_pct")),
        "total_trade_like_events": _int(aggregate.get("total_trade_like_events")),
        "avg_trade_like_events": _float(aggregate.get("avg_trade_like_events")),
        "test_add_by_side_counts": dict(aggregate.get("test_add_by_side_counts") or {}),
        "test_add_by_role_counts": dict(aggregate.get("test_add_by_role_counts") or {}),
        "test_flag_counts": dict(aggregate.get("test_flag_counts") or {}),
    }


def _is_neutral_equivalent(deltas: dict[str, Any]) -> bool:
    float_fields = (
        "compounded_oos_return_pct",
        "avg_oos_return_pct",
        "min_oos_return_pct",
        "max_fold_drawdown_pct",
        "avg_trade_like_events",
    )
    int_fields = ("positive_fold_count", "total_trade_like_events")
    return all(abs(_float(deltas.get(field))) <= 1e-9 for field in float_fields) and all(
        _int(deltas.get(field)) == 0 for field in int_fields
    )


def _promotion_type(*, failed_checks: list[str], deltas: dict[str, Any]) -> str:
    if failed_checks:
        return "blocked"
    if _is_neutral_equivalent(deltas):
        return "neutral_equivalent"
    if _float(deltas.get("compounded_oos_return_pct")) > 0.0:
        return "return_improving"
    if _float(deltas.get("max_fold_drawdown_pct")) < 0.0:
        return "risk_reducing_tradeoff"
    if _int(deltas.get("total_trade_like_events")) > 0:
        return "activity_tradeoff"
    return "non_degrading_tradeoff"


def build_full_walk_forward_gate_report(
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    *,
    generated_at: datetime | None = None,
    max_compounded_return_degradation_pct: float = 5.0,
    max_drawdown_worsening_pct: float = 3.0,
    min_positive_fold_delta: int = 0,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    baseline = _summary(baseline_report)
    candidate = _summary(candidate_report)
    deltas = {
        "compounded_oos_return_pct": round(
            candidate["compounded_oos_return_pct"] - baseline["compounded_oos_return_pct"],
            4,
        ),
        "avg_oos_return_pct": round(candidate["avg_oos_return_pct"] - baseline["avg_oos_return_pct"], 4),
        "min_oos_return_pct": round(candidate["min_oos_return_pct"] - baseline["min_oos_return_pct"], 4),
        "positive_fold_count": candidate["positive_fold_count"] - baseline["positive_fold_count"],
        "max_fold_drawdown_pct": round(
            candidate["max_fold_drawdown_pct"] - baseline["max_fold_drawdown_pct"],
            4,
        ),
        "total_trade_like_events": candidate["total_trade_like_events"] - baseline["total_trade_like_events"],
        "avg_trade_like_events": round(candidate["avg_trade_like_events"] - baseline["avg_trade_like_events"], 4),
    }
    failed_checks: list[str] = []
    if deltas["compounded_oos_return_pct"] < -abs(float(max_compounded_return_degradation_pct)):
        failed_checks.append("compounded_return_degradation")
    if deltas["max_fold_drawdown_pct"] > float(max_drawdown_worsening_pct):
        failed_checks.append("drawdown_worsening")
    if deltas["positive_fold_count"] < int(min_positive_fold_delta):
        failed_checks.append("positive_fold_count_degradation")
    lineage_guard = dict(candidate_report.get("source_replay_lineage_guard") or {})
    if bool(lineage_guard.get("failed")):
        failed_checks.append("source_replay_lineage_guard_failed")
    promotion_type = _promotion_type(failed_checks=failed_checks, deltas=deltas)
    overall_status = "blocked" if failed_checks else promotion_type
    decision = (
        "do_not_promote_to_paper_or_live"
        if failed_checks
        else "do_not_replace_current_candidate_without_non_metric_reason"
        if promotion_type == "neutral_equivalent"
        else "eligible_for_paper_evidence_collection_only"
    )
    return {
        "generated_at": generated_at.isoformat(),
        "overall_status": overall_status,
        "no_live_order_sent": True,
        "gates": {
            "max_compounded_return_degradation_pct": float(max_compounded_return_degradation_pct),
            "max_drawdown_worsening_pct": float(max_drawdown_worsening_pct),
            "min_positive_fold_delta": int(min_positive_fold_delta),
            "lineage_guard_must_not_fail": True,
        },
        "failed_checks": failed_checks,
        "baseline": baseline,
        "candidate": candidate,
        "deltas": deltas,
        "promotion_type": promotion_type,
        "candidate_lineage_guard": lineage_guard,
        "decision": decision,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Market State Rotation V6 Full Walk-Forward Gate",
        "",
        f"- status: `{report.get('overall_status')}`",
        f"- promotion_type: `{report.get('promotion_type')}`",
        f"- decision: `{report.get('decision')}`",
        f"- failed_checks: `{json.dumps(report.get('failed_checks') or [], ensure_ascii=False)}`",
        f"- deltas: `{json.dumps(report.get('deltas') or {}, ensure_ascii=False)}`",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gate v6 full walk-forward candidate against baseline.")
    parser.add_argument("--baseline-report", default=DEFAULT_BASELINE_REPORT)
    parser.add_argument("--candidate-report", default=DEFAULT_CANDIDATE_REPORT)
    parser.add_argument("--max-compounded-return-degradation-pct", type=float, default=5.0)
    parser.add_argument("--max-drawdown-worsening-pct", type=float, default=3.0)
    parser.add_argument("--min-positive-fold-delta", type=int, default=0)
    parser.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    baseline_path = _resolve(args.baseline_report)
    candidate_path = _resolve(args.candidate_report)
    report = build_full_walk_forward_gate_report(
        _load_json(baseline_path),
        _load_json(candidate_path),
        max_compounded_return_degradation_pct=float(args.max_compounded_return_degradation_pct),
        max_drawdown_worsening_pct=float(args.max_drawdown_worsening_pct),
        min_positive_fold_delta=int(args.min_positive_fold_delta),
    )
    report["input_baseline_report"] = _display_path(baseline_path)
    report["input_candidate_report"] = _display_path(candidate_path)
    if args.write_report:
        report_dir = _resolve(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_full_walk_forward_gate.json"
        md_path = report_dir / "market_state_rotation_v6_full_walk_forward_gate.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        report["report_path"] = _display_path(json_path)
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
