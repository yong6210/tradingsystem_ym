#!/usr/bin/env python3
"""Classify whether a v6 runtime signal drought is a data issue or deliberate abstention."""

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


DEFAULT_CYCLE_REPORT = (
    "reports/validation/diagnostics/market_state_rotation_v6_imp502_collection_cycle_resolved_runtime_context/"
    "market_state_rotation_v6_collection_cycle.json"
)
DEFAULT_ENTRY_SPARSITY_AUDIT = (
    "reports/validation/diagnostics/market_state_rotation_v6_imp503_entry_sparsity_resolved_runtime_context/"
    "market_state_rotation_v6_entry_filter_sparsity_audit.json"
)


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


def _first_missing_quote_floor(quote: dict[str, Any]) -> str | None:
    if _int(quote.get("observed")) < _int(quote.get("required")):
        return "quote_samples"
    if _int(quote.get("calendar_days")) < _int(quote.get("min_calendar_days")):
        return "quote_calendar_days"
    if _int(quote.get("distinct_hours")) < _int(quote.get("min_distinct_hours")):
        return "quote_distinct_hours"
    return None


def _entry_quality(entry_audit: dict[str, Any] | None) -> dict[str, Any]:
    if not entry_audit:
        return {
            "audit_available": False,
            "dominant_soft_contexts_are_low_quality": None,
            "eligible_probe_context_count": None,
            "rejected_soft_context_count": None,
            "mc04_broad_relaxation_rejected": None,
            "recommended_experiment_scope": "entry_filter_sparsity_audit_required",
        }
    diagnosis = dict(entry_audit.get("diagnosis") or {})
    return {
        "audit_available": True,
        "audit_status": entry_audit.get("status"),
        "dominant_soft_contexts_are_low_quality": diagnosis.get("dominant_soft_contexts_are_low_quality"),
        "eligible_probe_context_count": _int(diagnosis.get("eligible_probe_context_count")),
        "rejected_soft_context_count": _int(diagnosis.get("rejected_soft_context_count")),
        "mc04_soft_context_count": _int(diagnosis.get("mc04_soft_context_count")),
        "mc04_broad_relaxation_rejected": diagnosis.get("mc04_broad_relaxation_rejected"),
        "recommended_experiment_scope": diagnosis.get("recommended_experiment_scope"),
    }


def _classify(
    *,
    snapshot_blockers: list[str],
    freshness: dict[str, Any],
    entry_quality: dict[str, Any],
    paper_missing_shadow_fills: int,
) -> dict[str, Any]:
    blockers = set(snapshot_blockers)
    market_data_stale = "market_data_stale" in blockers
    signal_stale = "signal_stale" in blockers
    entry_audit_available = entry_quality.get("audit_available") is True
    low_quality = entry_quality.get("dominant_soft_contexts_are_low_quality") is True
    eligible = _int(entry_quality.get("eligible_probe_context_count"))
    market_age = _float(freshness.get("market_data_age_minutes"))
    signal_age = _float(freshness.get("signal_age_minutes"))

    if market_data_stale:
        status = "data_refresh_required"
        primary_cause = "market_data_not_fresh_enough_for_runtime_bridge"
        confidence = "high" if market_age > 0.0 else "medium"
    elif signal_stale and entry_audit_available and low_quality and eligible <= 0:
        status = "healthy_abstention_waiting_for_quality_signal"
        primary_cause = "strategy_abstaining_from_low_quality_soft_contexts"
        confidence = "high"
    elif signal_stale and entry_audit_available and eligible > 0:
        status = "quality_gated_probe_review_available"
        primary_cause = "fresh_signal_missing_but_quality_gated_mc12_probe_candidates_exist"
        confidence = "medium"
    elif signal_stale:
        status = "signal_drought_review_required"
        primary_cause = "fresh_signal_missing_without_entry_quality_audit"
        confidence = "medium"
    elif paper_missing_shadow_fills > 0:
        status = "fresh_signal_recent_but_fill_collection_incomplete"
        primary_cause = "paper_shadow_fill_samples_missing"
        confidence = "medium"
    else:
        status = "ready_for_next_gate_review"
        primary_cause = "no_current_signal_drought_blocker"
        confidence = "medium"

    return {
        "status": status,
        "primary_cause": primary_cause,
        "confidence": confidence,
        "market_data_stale": market_data_stale,
        "signal_stale": signal_stale,
        "market_data_age_minutes": market_age,
        "signal_age_minutes": signal_age,
    }


def _next_actions(
    *,
    classification: dict[str, Any],
    entry_quality: dict[str, Any],
    quote: dict[str, Any],
    live_order_submission_allowed: bool,
) -> list[str]:
    actions: list[str] = []
    status = str(classification.get("status") or "")
    if status == "data_refresh_required":
        actions.append("rerun_collection_cycle_with_runtime_fresh_cache_before_interpreting_signal_drought")
    if _first_missing_quote_floor(quote):
        actions.append("continue_quote_shadow_collection_until_samples_calendar_days_and_distinct_hours_pass")
    if status == "healthy_abstention_waiting_for_quality_signal":
        actions.append("do_not_relax_current_low_quality_soft_contexts")
        actions.append("wait_for_fresh_v6_add_or_remove_signal_before_applying_paper_bridge")
    if status == "quality_gated_probe_review_available":
        actions.append("test_only_quality_gated_mc12_micro_probe_in_walk_forward_or_paper")
    if entry_quality.get("mc04_broad_relaxation_rejected") is True:
        actions.append("keep_mc04_broad_first_touch_relaxation_disabled")
    if live_order_submission_allowed is not True:
        actions.append("keep_live_disabled_until_shadow_fill_and_execution_gates_pass")
    return actions


def build_signal_drought_audit(
    cycle_report: dict[str, Any],
    entry_audit: dict[str, Any] | None = None,
    *,
    input_cycle_report: str | None = None,
    input_entry_sparsity_audit: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    bridge = dict(cycle_report.get("bridge") or {})
    collection = dict(cycle_report.get("collection") or {})
    bottleneck = dict(cycle_report.get("bottleneck_diagnosis") or {})
    quote = dict(collection.get("quote_samples") or {})
    readiness = dict(collection.get("readiness") or {})
    paper = dict(collection.get("paper_fill") or {})
    cadence = dict(bridge.get("event_cadence") or {})
    freshness = dict(bridge.get("freshness") or {})
    entry = _entry_quality(entry_audit)
    paper_missing = max(_int(bottleneck.get("paper_missing_shadow_fills")), 0)
    if paper_missing <= 0 and _int(paper.get("v6_lifecycle_rows")) <= 0:
        paper_missing = 1 if "min_shadow_fill_samples" in set(readiness.get("failed_gates") or []) else 0
    classification = _classify(
        snapshot_blockers=[str(item) for item in bridge.get("snapshot_blockers") or []],
        freshness=freshness,
        entry_quality=entry,
        paper_missing_shadow_fills=paper_missing,
    )
    live_allowed = readiness.get("live_order_submission_allowed") is True
    return {
        "generated_at": generated_at.isoformat(),
        "status": classification["status"],
        "input_cycle_report": input_cycle_report,
        "input_entry_sparsity_audit": input_entry_sparsity_audit,
        "no_live_order_sent": True,
        "classification": classification,
        "market_state": {
            "bridge_status": bridge.get("overall_status"),
            "snapshot_blockers": list(bridge.get("snapshot_blockers") or []),
            "bridge_action": bridge.get("bridge_action"),
            "latest_event_ts": cadence.get("latest_event_ts"),
            "latest_event_age_hours": cadence.get("latest_event_age_hours"),
            "latest_add_ts": cadence.get("latest_add_ts"),
            "latest_add_age_hours": cadence.get("latest_add_age_hours"),
            "expected_days_per_add": cadence.get("expected_days_per_add"),
            "add_wait_state": cadence.get("add_wait_state"),
            "runtime_load_context": dict(bridge.get("runtime_load_context") or {}),
        },
        "collection_state": {
            "quote": {
                "observed": quote.get("observed"),
                "required": quote.get("required"),
                "calendar_days": quote.get("calendar_days"),
                "min_calendar_days": quote.get("min_calendar_days"),
                "distinct_hours": quote.get("distinct_hours"),
                "min_distinct_hours": quote.get("min_distinct_hours"),
                "first_missing_floor": _first_missing_quote_floor(quote),
            },
            "paper_fill_rows": paper.get("v6_lifecycle_rows"),
            "paper_missing_shadow_fills": paper_missing,
            "readiness_status": readiness.get("overall_status"),
            "max_authorized_stage": readiness.get("max_authorized_stage"),
            "live_order_submission_allowed": live_allowed,
            "failed_gates": list(readiness.get("failed_gates") or []),
            "pending_gates": list(readiness.get("pending_gates") or []),
        },
        "entry_quality": entry,
        "next_actions": _next_actions(
            classification=classification,
            entry_quality=entry,
            quote=quote,
            live_order_submission_allowed=live_allowed,
        ),
        "non_negotiables": [
            "do_not_enable_live_orders_from_signal_drought_audit",
            "do_not_relax_low_quality_soft_contexts_without_new_walk_forward_evidence",
            "do_not_count_absence_of_signal_as_execution_fill_evidence",
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    classification = dict(report.get("classification") or {})
    market = dict(report.get("market_state") or {})
    collection = dict(report.get("collection_state") or {})
    quote = dict(collection.get("quote") or {})
    entry = dict(report.get("entry_quality") or {})
    lines = [
        "# Market State Rotation V6 Signal Drought Audit",
        "",
        f"- status: `{report.get('status')}`",
        f"- no_live_order_sent: `{report.get('no_live_order_sent')}`",
        f"- primary_cause: `{classification.get('primary_cause')}`",
        f"- market_data_age_minutes: `{classification.get('market_data_age_minutes')}`",
        f"- signal_age_minutes: `{classification.get('signal_age_minutes')}`",
        f"- latest_event_ts: `{market.get('latest_event_ts')}`",
        f"- latest_add_ts: `{market.get('latest_add_ts')}`",
        f"- quote_samples: `{quote.get('observed')}/{quote.get('required')}`",
        f"- quote_days: `{quote.get('calendar_days')}/{quote.get('min_calendar_days')}`",
        f"- quote_hours: `{quote.get('distinct_hours')}/{quote.get('min_distinct_hours')}`",
        f"- entry_scope: `{entry.get('recommended_experiment_scope')}`",
        f"- eligible_probe_context_count: `{entry.get('eligible_probe_context_count')}`",
        f"- live_order_submission_allowed: `{collection.get('live_order_submission_allowed')}`",
        "",
        "## Next Actions",
        "",
    ]
    for action in list(report.get("next_actions") or []):
        lines.append(f"- {action}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify v6 runtime signal drought and collection bottlenecks.")
    parser.add_argument("--cycle-report", default=DEFAULT_CYCLE_REPORT)
    parser.add_argument("--entry-sparsity-audit", default=DEFAULT_ENTRY_SPARSITY_AUDIT)
    parser.add_argument("--report-dir", default="reports/validation/diagnostics/market_state_rotation_v6_signal_drought_audit")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cycle_path = _resolve(args.cycle_report)
    entry_path = _resolve(args.entry_sparsity_audit) if args.entry_sparsity_audit else None
    entry_audit = _load_json(entry_path) if entry_path is not None and entry_path.exists() else None
    report = build_signal_drought_audit(
        _load_json(cycle_path),
        entry_audit,
        input_cycle_report=_display_path(cycle_path),
        input_entry_sparsity_audit=_display_path(entry_path) if entry_path is not None and entry_path.exists() else None,
    )
    if args.write_report:
        report_dir = _resolve(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_signal_drought_audit.json"
        md_path = report_dir / "market_state_rotation_v6_signal_drought_audit.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        report["report_path"] = _display_path(json_path)
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
