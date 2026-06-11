#!/usr/bin/env python3
"""Run one safe v6 paper-bridge plus evidence-collection cycle."""

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

from scripts.run_market_state_rotation_v6_collection_tick import (
    DEFAULT_MANUAL_EVIDENCE,
    DEFAULT_SAMPLE_PATH,
    DEFAULT_STRESS_REPORT,
    DEFAULT_WALK_FORWARD_REPORT,
    run_collection_tick,
)
from scripts.run_market_state_rotation_v6_paper_bridge_tick import (
    DEFAULT_PRE_APPLY_BACKUP_DIR,
    DEFAULT_SOURCE_BACKTEST_REPORT,
    EXPECTED_SYMBOL,
    run_paper_bridge_tick,
)


DEFAULT_CYCLE_REPORT_DIR = "reports/validation/diagnostics/market_state_rotation_v6_collection_cycle"
BRIDGE_REPORT_NAME = "market_state_rotation_v6_paper_bridge_tick.json"
COLLECTION_REPORT_NAME = "market_state_rotation_v6_collection_tick.json"
CYCLE_REPORT_NAME = "market_state_rotation_v6_collection_cycle.json"


def _resolve(path: str | Path) -> Path:
    raw = Path(path)
    return raw if raw.is_absolute() else ROOT_DIR / raw


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _next_actions(*, bridge_report: dict[str, Any], collection_report: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    snapshot = dict(bridge_report.get("snapshot") or {})
    snapshot_blockers = set(str(item) for item in snapshot.get("blockers") or [])
    cadence = dict(snapshot.get("bridge_event_cadence") or {})
    bridge_status = str(bridge_report.get("overall_status") or "")
    remove_without_open_plan = bridge_status in {"dry_run_no_open_v6_paper_plan", "no_open_v6_paper_plan"}
    if str(bridge_report.get("overall_status") or "") == "not_actionable" and "signal_stale" in snapshot_blockers:
        actions.append("rerun_cycle_until_fresh_v6_add_or_remove_signal_is_seen")
    if remove_without_open_plan:
        actions.append("wait_for_next_add_signal_or_existing_open_paper_plan_before_reapplying_remove")
    if str(cadence.get("add_wait_state") or "") == "latest_add_age_above_recent_median_gap":
        latest_add_age_days = _float(cadence.get("latest_add_age_hours")) / 24.0
        expected_days_per_add = _float(cadence.get("expected_days_per_add"))
        if expected_days_per_add <= 0.0 or latest_add_age_days >= expected_days_per_add * 2.0:
            actions.append("review_v6_entry_filter_sparsity_before_waiting_for_paper_fills")
    if dict(collection_report.get("quote_shadow") or {}).get("overall_status") != "PASS":
        actions.append("continue_quote_shadow_collection_until_samples_calendar_days_and_distinct_hours_pass")
    paper = dict(collection_report.get("paper_fill") or {})
    if int(paper.get("v6_lifecycle_rows") or 0) <= 0:
        actions.append("collect_real_paper_lifecycle_rows_from_fresh_v6_runtime_signals")
    readiness = dict(collection_report.get("readiness") or {})
    if readiness.get("live_order_submission_allowed") is not True:
        actions.append("keep_live_disabled_until_readiness_and_paper_fill_gates_pass")
    return actions


def _cycle_bottleneck_diagnosis(*, bridge_report: dict[str, Any], collection_report: dict[str, Any]) -> dict[str, Any]:
    embedded = dict(collection_report.get("bottleneck_diagnosis") or {})
    if embedded:
        return embedded
    snapshot = dict(bridge_report.get("snapshot") or {})
    snapshot_blockers = set(str(item) for item in snapshot.get("blockers") or [])
    bridge_status = str(bridge_report.get("overall_status") or "")
    quote = dict(collection_report.get("quote_shadow") or {})
    paper = dict(collection_report.get("paper_fill") or {})
    readiness = dict(collection_report.get("readiness") or {})
    quote_missing_samples = max(int(quote.get("required_quote_samples") or 0) - int(quote.get("eligible_row_count") or 0), 0)
    quote_missing_days = max(int(quote.get("min_calendar_days") or 0) - int(quote.get("calendar_day_count") or 0), 0)
    quote_missing_hours = max(int(quote.get("min_distinct_hours") or 0) - int(quote.get("distinct_hour_count") or 0), 0)
    shadow_missing = max(
        int(dict(collection_report.get("shadow_fill_progress") or {}).get("missing") or 0),
        0,
    )
    if shadow_missing <= 0 and int(paper.get("v6_lifecycle_rows") or 0) <= 0:
        failed = set(str(item) for item in readiness.get("failed_gates") or [])
        if "min_shadow_fill_samples" in failed:
            shadow_missing = 1
    waiting_for_signal = "signal_stale" in snapshot_blockers or str(paper.get("bridge_status") or "") == (
        "runtime_bridge_waiting_for_fresh_signal"
    )
    remove_without_open_plan = bridge_status in {"dry_run_no_open_v6_paper_plan", "no_open_v6_paper_plan"}
    quote_incomplete = bool(quote_missing_samples or quote_missing_days or quote_missing_hours)
    live_allowed = readiness.get("live_order_submission_allowed") is True
    if waiting_for_signal and shadow_missing > 0:
        primary = "fresh_v6_signal_missing_for_paper_fill_collection"
    elif remove_without_open_plan and shadow_missing > 0 and not quote_incomplete:
        primary = "remove_signal_without_open_paper_plan"
    elif quote_incomplete:
        primary = "quote_shadow_collection_incomplete"
    elif shadow_missing > 0:
        primary = "paper_fill_samples_missing"
    elif not live_allowed:
        primary = "readiness_gates_pending"
    else:
        primary = "ready_for_next_gate"
    collectable_now = ["quote_shadow_samples"] if quote_incomplete else []
    if shadow_missing > 0 and not waiting_for_signal:
        collectable_now.append("paper_shadow_fill_samples")
    blocked_until: list[str] = []
    if waiting_for_signal:
        blocked_until.append("fresh_market_state_rotation_v6_add_or_remove_signal")
    if remove_without_open_plan:
        blocked_until.append("next_add_signal_or_existing_open_paper_plan")
    if shadow_missing > 0:
        blocked_until.append("min_shadow_fill_samples")
    if quote_incomplete:
        blocked_until.append("quote_shadow_sample_calendar_and_hour_floor")
    if not live_allowed:
        blocked_until.append("readiness_live_order_gate")
    return {
        "primary_bottleneck": primary,
        "waiting_for_fresh_signal": waiting_for_signal,
        "remove_signal_without_open_paper_plan": remove_without_open_plan,
        "collectable_without_fresh_signal": collectable_now,
        "blocked_until": blocked_until,
        "quote_missing": {
            "samples": quote_missing_samples,
            "calendar_days": quote_missing_days,
            "distinct_hours": quote_missing_hours,
        },
        "paper_missing_shadow_fills": shadow_missing,
        "max_authorized_stage": readiness.get("max_authorized_stage"),
        "live_order_submission_allowed": live_allowed,
    }


def build_collection_cycle_summary(
    *,
    bridge_report: dict[str, Any],
    collection_report: dict[str, Any],
    bridge_report_dir: Path,
    collection_report_dir: Path,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    snapshot = dict(bridge_report.get("snapshot") or {})
    quote = dict(collection_report.get("quote_shadow") or {})
    paper = dict(collection_report.get("paper_fill") or {})
    readiness = dict(collection_report.get("readiness") or {})
    roadmap = dict(collection_report.get("roadmap") or {})
    bottleneck = _cycle_bottleneck_diagnosis(bridge_report=bridge_report, collection_report=collection_report)
    return {
        "generated_at": generated_at.isoformat(),
        "overall_status": collection_report.get("overall_status"),
        "no_live_order_sent": True,
        "bottleneck_diagnosis": bottleneck,
        "bridge": {
            "overall_status": bridge_report.get("overall_status"),
            "apply_paper": bridge_report.get("apply_paper"),
            "snapshot_status": snapshot.get("overall_status"),
            "snapshot_blockers": list(snapshot.get("blockers") or []),
            "bridge_action": snapshot.get("bridge_action"),
            "freshness": dict(snapshot.get("freshness") or {}),
            "runtime_load_context": dict(snapshot.get("runtime_load_context") or {}),
            "event_cadence": dict(snapshot.get("bridge_event_cadence") or {}),
            "top_no_trade_reasons": list(snapshot.get("top_no_trade_reasons") or [])[:5],
            "no_trade_hotspots": dict(snapshot.get("no_trade_hotspots") or {}),
            "pre_apply_backup": bridge_report.get("pre_apply_backup"),
            "remove_plan_precheck": dict(bridge_report.get("remove_plan_precheck") or {}),
            "result": dict(bridge_report.get("result") or {}),
            "execution_parity_preflight": dict(bridge_report.get("execution_parity_preflight") or {}),
            "report_path": _display_path(bridge_report_dir / BRIDGE_REPORT_NAME),
        },
        "collection": {
            "overall_status": collection_report.get("overall_status"),
            "captured_quote_rows": collection_report.get("captured_quote_rows"),
            "quote_samples": {
                "observed": quote.get("eligible_row_count"),
                "required": quote.get("required_quote_samples"),
                "calendar_days": quote.get("calendar_day_count"),
                "min_calendar_days": quote.get("min_calendar_days"),
                "distinct_hours": quote.get("distinct_hour_count"),
                "min_distinct_hours": quote.get("min_distinct_hours"),
                "calendar_day_values": list(quote.get("calendar_days") or []),
                "distinct_hour_values": list(quote.get("distinct_hours") or []),
                "coverage": dict(quote.get("coverage") or {}),
                "blockers": list(quote.get("blockers") or []),
            },
            "paper_fill": {
                "status": paper.get("status"),
                "bridge_status": paper.get("bridge_status"),
                "v6_lifecycle_rows": paper.get("v6_lifecycle_rows"),
                "reason": paper.get("reason"),
                "next_action": paper.get("next_action"),
            },
            "readiness": {
                "overall_status": readiness.get("overall_status"),
                "max_authorized_stage": readiness.get("max_authorized_stage"),
                "live_order_submission_allowed": readiness.get("live_order_submission_allowed"),
                "failed_gates": list(readiness.get("failed_gates") or []),
                "pending_gates": list(readiness.get("pending_gates") or []),
            },
            "roadmap_blockers": list(roadmap.get("blockers") or []),
            "report_path": _display_path(collection_report_dir / COLLECTION_REPORT_NAME),
        },
        "next_actions": _next_actions(bridge_report=bridge_report, collection_report=collection_report),
    }


def _markdown(report: dict[str, Any]) -> str:
    bridge = dict(report.get("bridge") or {})
    collection = dict(report.get("collection") or {})
    quote = dict(collection.get("quote_samples") or {})
    paper = dict(collection.get("paper_fill") or {})
    readiness = dict(collection.get("readiness") or {})
    bottleneck = dict(report.get("bottleneck_diagnosis") or {})
    lines = [
        "# Market State Rotation V6 Collection Cycle",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- status: `{report.get('overall_status')}`",
        f"- no_live_order_sent: `{report.get('no_live_order_sent')}`",
        f"- primary_bottleneck: `{bottleneck.get('primary_bottleneck')}`",
        f"- collectable_without_fresh_signal: `{', '.join(bottleneck.get('collectable_without_fresh_signal') or [])}`",
        f"- bridge_status: `{bridge.get('overall_status')}` / `{bridge.get('snapshot_status')}`",
        f"- bridge_blockers: `{', '.join(bridge.get('snapshot_blockers') or [])}`",
        f"- bridge_wait_state: `{dict(bridge.get('event_cadence') or {}).get('wait_state')}`",
        f"- quote_samples: `{quote.get('observed')}/{quote.get('required')}`",
        f"- quote_days: `{quote.get('calendar_days')}/{quote.get('min_calendar_days')}`",
        f"- quote_hours: `{quote.get('distinct_hours')}/{quote.get('min_distinct_hours')}`",
        f"- paper_fill: `{paper.get('status')}` / `{paper.get('bridge_status')}`",
        f"- lifecycle_rows: `{paper.get('v6_lifecycle_rows')}`",
        f"- readiness: `{readiness.get('overall_status')}` / stage `{readiness.get('max_authorized_stage')}`",
        f"- next_actions: `{', '.join(report.get('next_actions') or [])}`",
        "",
    ]
    return "\n".join(lines)


def run_collection_cycle(
    *,
    source_backtest_report_path: Path,
    stress_report_path: Path,
    walk_forward_report_path: Path,
    manual_evidence_path: Path | None,
    sample_jsonl: Path,
    report_dir: Path,
    apply_paper_bridge: bool = False,
    pre_apply_backup_dir: Path | None = _resolve(DEFAULT_PRE_APPLY_BACKUP_DIR),
    require_pre_apply_backup: bool = True,
    symbol: str = EXPECTED_SYMBOL,
    bridge_days: int = 120,
    bridge_load_days: int = 0,
    max_signal_age_minutes: int = 15,
    max_market_data_age_minutes: int = 30,
    plan_valid_minutes: int = 15,
    quote_samples_per_tick: int = 1,
    quote_sample_sleep_seconds: float = 0.0,
    required_quote_samples: int = 300,
    min_quote_calendar_days: int = 30,
    min_quote_distinct_hours: int = 24,
    min_shadow_fill_samples: int = 100,
    lifecycle_days: int = 30,
    lifecycle_limit: int = 500,
) -> dict[str, Any]:
    report_dir.mkdir(parents=True, exist_ok=True)
    bridge_report_dir = report_dir / "paper_bridge_tick"
    collection_report_dir = report_dir / "collection_tick"
    bridge_report = run_paper_bridge_tick(
        source_backtest_report_path=source_backtest_report_path,
        apply_paper=bool(apply_paper_bridge),
        symbol=str(symbol or EXPECTED_SYMBOL).upper(),
        days=max(1, int(bridge_days)),
        load_days=int(bridge_load_days) if int(bridge_load_days) > 0 else None,
        max_signal_age_minutes=max(1, int(max_signal_age_minutes)),
        max_market_data_age_minutes=max(1, int(max_market_data_age_minutes)),
        plan_valid_minutes=max(1, int(plan_valid_minutes)),
        report_dir=bridge_report_dir,
        pre_apply_backup_dir=pre_apply_backup_dir,
        require_pre_apply_backup=bool(require_pre_apply_backup),
    )
    collection_report = run_collection_tick(
        sample_jsonl=sample_jsonl,
        stress_report_path=stress_report_path,
        walk_forward_report_path=walk_forward_report_path,
        manual_evidence_path=manual_evidence_path,
        paper_bridge_tick_report_path=bridge_report_dir / BRIDGE_REPORT_NAME,
        quote_samples_per_tick=max(0, int(quote_samples_per_tick)),
        quote_sample_sleep_seconds=max(0.0, float(quote_sample_sleep_seconds)),
        required_quote_samples=max(1, int(required_quote_samples)),
        min_quote_calendar_days=max(1, int(min_quote_calendar_days)),
        min_quote_distinct_hours=max(1, int(min_quote_distinct_hours)),
        min_shadow_fill_samples=max(1, int(min_shadow_fill_samples)),
        days=max(1, int(lifecycle_days)),
        limit=max(1, int(lifecycle_limit)),
        symbol=str(symbol or EXPECTED_SYMBOL).upper(),
        report_dir=collection_report_dir,
    )
    cycle_report = build_collection_cycle_summary(
        bridge_report=bridge_report,
        collection_report=collection_report,
        bridge_report_dir=bridge_report_dir,
        collection_report_dir=collection_report_dir,
    )
    _write_json(report_dir / CYCLE_REPORT_NAME, cycle_report)
    (report_dir / "market_state_rotation_v6_collection_cycle.md").write_text(_markdown(cycle_report), encoding="utf-8")
    cycle_report["report_dir"] = _display_path(report_dir)
    return cycle_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one v6 paper bridge plus collection evidence cycle.")
    parser.add_argument("--source-backtest-report", default=DEFAULT_SOURCE_BACKTEST_REPORT)
    parser.add_argument("--stress-report", default=DEFAULT_STRESS_REPORT)
    parser.add_argument("--walk-forward-report", default=DEFAULT_WALK_FORWARD_REPORT)
    parser.add_argument("--manual-safety-evidence", default=DEFAULT_MANUAL_EVIDENCE)
    parser.add_argument("--sample-jsonl", default=DEFAULT_SAMPLE_PATH)
    parser.add_argument("--report-dir", default=DEFAULT_CYCLE_REPORT_DIR)
    parser.add_argument("--apply-paper-bridge", action="store_true")
    parser.add_argument("--pre-apply-backup-dir", default=DEFAULT_PRE_APPLY_BACKUP_DIR)
    parser.add_argument("--symbol", default=EXPECTED_SYMBOL)
    parser.add_argument("--bridge-days", type=int, default=120)
    parser.add_argument("--bridge-load-days", type=int, default=0, help="0 uses runtime warmup window instead of source search load_days.")
    parser.add_argument("--max-signal-age-minutes", type=int, default=15)
    parser.add_argument("--max-market-data-age-minutes", type=int, default=30)
    parser.add_argument("--plan-valid-minutes", type=int, default=15)
    parser.add_argument("--quote-samples-per-tick", type=int, default=1)
    parser.add_argument("--quote-sample-sleep-seconds", type=float, default=0.0)
    parser.add_argument("--required-quote-samples", type=int, default=300)
    parser.add_argument("--min-quote-calendar-days", type=int, default=30)
    parser.add_argument("--min-quote-distinct-hours", type=int, default=24)
    parser.add_argument("--min-shadow-fill-samples", type=int, default=100)
    parser.add_argument("--lifecycle-days", type=int, default=30)
    parser.add_argument("--lifecycle-limit", type=int, default=500)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manual_path = _resolve(args.manual_safety_evidence) if args.manual_safety_evidence else None
    report = run_collection_cycle(
        source_backtest_report_path=_resolve(args.source_backtest_report),
        stress_report_path=_resolve(args.stress_report),
        walk_forward_report_path=_resolve(args.walk_forward_report),
        manual_evidence_path=manual_path,
        sample_jsonl=_resolve(args.sample_jsonl),
        report_dir=_resolve(args.report_dir),
        apply_paper_bridge=bool(args.apply_paper_bridge),
        pre_apply_backup_dir=_resolve(args.pre_apply_backup_dir),
        require_pre_apply_backup=True,
        symbol=str(args.symbol or EXPECTED_SYMBOL).upper(),
        bridge_days=max(1, int(args.bridge_days)),
        bridge_load_days=int(args.bridge_load_days),
        max_signal_age_minutes=max(1, int(args.max_signal_age_minutes)),
        max_market_data_age_minutes=max(1, int(args.max_market_data_age_minutes)),
        plan_valid_minutes=max(1, int(args.plan_valid_minutes)),
        quote_samples_per_tick=max(0, int(args.quote_samples_per_tick)),
        quote_sample_sleep_seconds=max(0.0, float(args.quote_sample_sleep_seconds)),
        required_quote_samples=max(1, int(args.required_quote_samples)),
        min_quote_calendar_days=max(1, int(args.min_quote_calendar_days)),
        min_quote_distinct_hours=max(1, int(args.min_quote_distinct_hours)),
        min_shadow_fill_samples=max(1, int(args.min_shadow_fill_samples)),
        lifecycle_days=max(1, int(args.lifecycle_days)),
        lifecycle_limit=max(1, int(args.lifecycle_limit)),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
