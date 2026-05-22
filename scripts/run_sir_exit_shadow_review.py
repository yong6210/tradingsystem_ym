#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text


DEFAULT_VALIDATION_REPORTS = (
    "reports/validation/micro_main_important_zone_entry_fixed_3y/latest.json,"
    "reports/validation/micro_main_important_zone_entry_fixed_5y_top/latest.json"
)
DEFAULT_CANDIDATE_POLICIES = (
    "important_zone:lookback42:hold40:stopoff:ideal2.2:tpmax2.8,"
    "important_zone:lookback42:hold40:stopoff:ideal2.2:tpmax3.5"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Review SIR important-zone exit candidates as shadow-only alternatives to the live baseline."
    )
    parser.add_argument("--baseline-policy", default="legacy_full_2r")
    parser.add_argument("--candidate-policies", default=DEFAULT_CANDIDATE_POLICIES)
    parser.add_argument("--validation-reports", default=DEFAULT_VALIDATION_REPORTS)
    parser.add_argument("--trade-count-floor-ratio", type=float, default=0.98)
    parser.add_argument("--promotion-total-r-ratio", type=float, default=1.0)
    parser.add_argument("--promotion-cost-x2-ratio", type=float, default=1.0)
    parser.add_argument("--report-dir", default="reports/operations/sir_exit_shadow_review")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def _csv(value: str) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for raw in str(value or "").split(","):
        item = raw.strip()
        if item and item not in seen:
            items.append(item)
            seen.add(item)
    return items


def _resolve_path(path: str) -> Path:
    raw = Path(path)
    if raw.is_absolute():
        return raw
    env_roots = [
        Path(value).expanduser()
        for value in (
            os.environ.get("TRADING_RESEARCH_ROOT"),
            os.environ.get("TRADING_WORKSPACE_ROOT"),
        )
        if value
    ]
    search_roots = [
        ROOT_DIR,
        ROOT_DIR.parent,
        *env_roots,
        Path.home() / "Documents/trading",
    ]
    for root in search_roots:
        candidate = root / raw
        if candidate.exists():
            return candidate
    return ROOT_DIR / raw


def _resolve_output_path(path: str) -> Path:
    candidate = Path(str(path or "")).expanduser()
    if candidate.is_absolute():
        return candidate
    return ROOT_DIR / candidate


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _load_report_payloads(paths: list[Path]) -> list[tuple[Path, dict[str, Any] | None, str | None]]:
    payloads: list[tuple[Path, dict[str, Any] | None, str | None]] = []
    for path in paths:
        if not path.exists():
            payloads.append((path, None, "validation_report_missing"))
            continue
        try:
            payloads.append((path, _load_json(path), None))
        except Exception as exc:
            payloads.append((path, None, f"validation_report_load_error:{exc.__class__.__name__}"))
    return payloads


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


def _policy_name(row: dict[str, Any]) -> str:
    policy = row.get("policy")
    if isinstance(policy, dict):
        return str(policy.get("name") or "")
    return str(policy or "")


def _policy_rows(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = report.get("all_results") or []
    if not isinstance(rows, list):
        return {}
    return {_policy_name(dict(row)): dict(row) for row in rows if isinstance(row, dict)}


def _metrics(row: dict[str, Any]) -> dict[str, float | int]:
    summary = dict(row.get("summary") or {})
    cost_x2 = dict(dict(row.get("cost_stress") or {}).get("cost_x2_0") or {})
    return {
        "closed": _safe_int(summary.get("closed")),
        "total_r": round(_safe_float(summary.get("total_r")), 4),
        "ev_r": round(_safe_float(summary.get("ev_r")), 4),
        "win_rate": round(_safe_float(summary.get("win_rate")), 4),
        "max_dd_r": round(_safe_float(summary.get("max_dd_r")), 4),
        "score": round(_safe_float(summary.get("score")), 6),
        "cost_x2_total_r": round(_safe_float(cost_x2.get("total_r")), 4),
    }


def _ratio(numerator: float, denominator: float) -> float:
    if abs(float(denominator)) <= 1e-12:
        return 0.0
    return round(float(numerator) / float(denominator), 6)


def _candidate_report_review(
    *,
    report_path: Path,
    report: dict[str, Any] | None,
    load_error: str | None = None,
    baseline_policy: str,
    candidate_policy: str,
    trade_count_floor_ratio: float,
    promotion_total_r_ratio: float,
    promotion_cost_x2_ratio: float,
) -> dict[str, Any]:
    report_payload = dict(report or {})
    rows = _policy_rows(report_payload)
    baseline_row = rows.get(baseline_policy)
    candidate_row = rows.get(candidate_policy)
    scope = dict(report_payload.get("scope") or {})
    review: dict[str, Any] = {
        "report_path": str(report_path.relative_to(ROOT_DIR) if report_path.is_relative_to(ROOT_DIR) else report_path),
        "days": _safe_int(scope.get("days")),
        "entry_delay_minutes": _safe_int(scope.get("entry_delay_minutes")),
        "baseline_policy": baseline_policy,
        "candidate_policy": candidate_policy,
        "status": "MISSING",
        "pass_promotion_gate": False,
        "reasons": [],
    }
    if load_error:
        review["reasons"].append(load_error)
        return review
    if baseline_row is None:
        review["reasons"].append("baseline_missing")
        return review
    if candidate_row is None:
        review["reasons"].append("candidate_missing")
        review["baseline"] = _metrics(baseline_row)
        return review

    baseline = _metrics(baseline_row)
    candidate = _metrics(candidate_row)
    review["baseline"] = baseline
    review["candidate"] = candidate
    review["deltas"] = {
        "closed": int(candidate["closed"]) - int(baseline["closed"]),
        "total_r": round(float(candidate["total_r"]) - float(baseline["total_r"]), 4),
        "ev_r": round(float(candidate["ev_r"]) - float(baseline["ev_r"]), 4),
        "win_rate": round(float(candidate["win_rate"]) - float(baseline["win_rate"]), 4),
        "max_dd_r": round(float(candidate["max_dd_r"]) - float(baseline["max_dd_r"]), 4),
        "score": round(float(candidate["score"]) - float(baseline["score"]), 6),
        "cost_x2_total_r": round(float(candidate["cost_x2_total_r"]) - float(baseline["cost_x2_total_r"]), 4),
        "total_r_ratio": _ratio(float(candidate["total_r"]), float(baseline["total_r"])),
        "cost_x2_ratio": _ratio(float(candidate["cost_x2_total_r"]), float(baseline["cost_x2_total_r"])),
        "max_dd_ratio": _ratio(float(candidate["max_dd_r"]), float(baseline["max_dd_r"])),
    }

    floor = int(max(0.0, min(float(trade_count_floor_ratio), 1.0)) * max(int(baseline["closed"]), 1))
    if int(candidate["closed"]) < floor:
        review["reasons"].append("trade_count_below_floor")
    if float(candidate["total_r"]) < float(baseline["total_r"]) * max(float(promotion_total_r_ratio), 0.0):
        review["reasons"].append("total_r_does_not_beat_live_baseline")
    if float(candidate["cost_x2_total_r"]) < float(baseline["cost_x2_total_r"]) * max(float(promotion_cost_x2_ratio), 0.0):
        review["reasons"].append("cost_stress_does_not_beat_live_baseline")
    if float(candidate["score"]) > float(baseline["score"]) and float(candidate["total_r"]) < float(baseline["total_r"]):
        review["reasons"].append("risk_adjusted_improvement_only_total_return_lower")

    review["status"] = "PASS" if not review["reasons"] else "SHADOW_ONLY"
    review["pass_promotion_gate"] = not review["reasons"]
    return review


def build_payload(
    *,
    baseline_policy: str,
    candidate_policies: list[str],
    validation_reports: list[Path],
    generated_at: datetime | None = None,
    trade_count_floor_ratio: float = 0.98,
    promotion_total_r_ratio: float = 1.0,
    promotion_cost_x2_ratio: float = 1.0,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    settings = get_settings()
    live_policy = str(getattr(settings, "session_impulse_retest_exit_policy_name", "") or "")
    report_payloads = _load_report_payloads(validation_reports)
    loaded_reports = [dict(report or {}) for _path, report, load_error in report_payloads if report is not None and not load_error]
    live_policy_present_in_reports = bool(live_policy) and bool(loaded_reports) and all(
        live_policy in _policy_rows(report)
        for report in loaded_reports
    )
    baseline_is_current_live_policy = bool(live_policy) and live_policy == baseline_policy

    candidates: list[dict[str, Any]] = []
    for candidate_policy in candidate_policies:
        report_reviews = [
            _candidate_report_review(
                report_path=path,
                report=report,
                load_error=load_error,
                baseline_policy=baseline_policy,
                candidate_policy=candidate_policy,
                trade_count_floor_ratio=trade_count_floor_ratio,
                promotion_total_r_ratio=promotion_total_r_ratio,
                promotion_cost_x2_ratio=promotion_cost_x2_ratio,
            )
            for path, report, load_error in report_payloads
        ]
        pass_all = bool(report_reviews) and all(bool(item.get("pass_promotion_gate")) for item in report_reviews)
        total_deficit = sum(
            abs(_safe_float(dict(item.get("deltas") or {}).get("total_r")))
            for item in report_reviews
            if "total_r_does_not_beat_live_baseline" in list(item.get("reasons") or [])
        )
        candidates.append(
            {
                "policy": candidate_policy,
                "candidate_policy": candidate_policy,
                "status": "PROMOTION_READY_FOR_PAPER_REVIEW" if pass_all else "SHADOW_ONLY",
                "pass_all_promotion_gates": pass_all,
                "total_r_deficit_sum": round(total_deficit, 4),
                "report_reviews": report_reviews,
            }
        )

    promotion_ready = [item for item in candidates if bool(item.get("pass_all_promotion_gates"))]
    if promotion_ready:
        decision = (
            "PROMOTE_CANDIDATE_TO_PAPER_REVIEW"
            if baseline_is_current_live_policy
            else "PAPER_REVIEW_REQUIRED_WITH_CURRENT_LIVE_BASELINE"
        )
    else:
        decision = "KEEP_CURRENT_LIVE_ROUTE_UNCHANGED"
    overall_status = "WATCH" if promotion_ready else "PASS"
    comparison_scope_status = (
        "current_live_policy_baseline"
        if baseline_is_current_live_policy
        else "comparison_baseline_not_current_live_policy"
    )
    if not live_policy_present_in_reports:
        comparison_scope_status = f"{comparison_scope_status}:live_policy_not_in_validation_reports"
    return {
        "schema_version": "sir_exit_shadow_review_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "sir_exit_shadow_review_only_no_order_submission",
        "overall_status": overall_status,
        "live_exit_policy": live_policy,
        "baseline_policy": baseline_policy,
        "comparison_baseline_is_current_live_policy": baseline_is_current_live_policy,
        "live_policy_present_in_validation_reports": live_policy_present_in_reports,
        "comparison_scope_status": comparison_scope_status,
        "live_action": "KEEP_CURRENT_LIVE_ROUTE_UNCHANGED",
        "live_ready": False,
        "order_submission_allowed": False,
        "order_submission_authority": "shadow_review_has_no_live_order_authority",
        "live_contract": {
            "strategy_family": "session_impulse_retest",
            "live_policy": live_policy,
            "baseline_policy": baseline_policy,
            "live_policy_matches_baseline": live_policy == baseline_policy,
            "live_policy_present_in_validation_reports": live_policy_present_in_reports,
            "config_close_only_active": bool(getattr(settings, "auto_trading_close_only", False)),
            "order_submission_allowed": False,
            "order_submission_authority": "shadow_review_has_no_live_order_authority",
        },
        "scope": {
            "validation_reports": [
                str(path.relative_to(ROOT_DIR) if path.is_relative_to(ROOT_DIR) else path) for path in validation_reports
            ],
            "candidate_policies": candidate_policies,
            "trade_count_floor_ratio": float(trade_count_floor_ratio),
            "promotion_total_r_ratio": float(promotion_total_r_ratio),
            "promotion_cost_x2_ratio": float(promotion_cost_x2_ratio),
        },
        "decision": decision,
        "candidate_action": "SHADOW_ONLY" if not promotion_ready else "PAPER_REVIEW_REQUIRED_BEFORE_LIVE",
        "promotion_ready_candidates": promotion_ready,
        "candidates": candidates,
        "operator_summary": {
            "action": "Keep the current live route unchanged; do not promote this exit policy without separate paper review.",
            "baseline_policy": baseline_policy,
            "comparison_scope_status": comparison_scope_status,
            "promotion_ready_candidate_count": len(promotion_ready),
            "order_submission_allowed": False,
            "order_submission_authority": "shadow_review_has_no_live_order_authority",
        },
    }


def main() -> int:
    args = _parse_args()
    validation_reports = [_resolve_path(item) for item in _csv(args.validation_reports)]
    candidate_policies = _csv(args.candidate_policies)
    payload = build_payload(
        baseline_policy=str(args.baseline_policy or "legacy_full_2r").strip(),
        candidate_policies=candidate_policies,
        validation_reports=validation_reports,
        trade_count_floor_ratio=float(args.trade_count_floor_ratio),
        promotion_total_r_ratio=float(args.promotion_total_r_ratio),
        promotion_cost_x2_ratio=float(args.promotion_cost_x2_ratio),
    )
    if args.write_report:
        out_dir = _resolve_output_path(str(args.report_dir))
        out_dir.mkdir(parents=True, exist_ok=True)
        generated = datetime.fromisoformat(str(payload["generated_at"]))
        out_path = out_dir / f"sir_exit_shadow_review_{generated.strftime('%Y%m%dT%H%M%SZ')}.json"
        atomic_write_text(out_path, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(out_dir / "latest.json", json.dumps({**payload, "report_path": str(out_path)}, ensure_ascii=False, indent=2, default=str))
        payload["report_path"] = str(out_path.relative_to(ROOT_DIR) if out_path.is_relative_to(ROOT_DIR) else out_path)
    if not args.quiet:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
