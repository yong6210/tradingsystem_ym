#!/usr/bin/env python3
"""Run one safe v6 evidence collection tick.

The tick captures BTCUSDT quote/liquidity shadow samples, refreshes the v6
readiness/progress/roadmap bundle, and records why paper/shadow fill collection
is still blocked when no market_state_rotation_v6 lifecycle rows exist.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.run_market_state_rotation_v6_execution_roadmap import build_execution_roadmap_report
from scripts.run_market_state_rotation_v6_quote_shadow_audit import (
    DEFAULT_SAMPLE_PATH,
    EXPECTED_STRATEGY_FAMILY,
    EXPECTED_SYMBOL,
    _append_jsonl,
    _load_jsonl,
    build_quote_shadow_audit_report,
    capture_quote_shadow_rows,
)
from scripts.run_market_state_rotation_v6_paper_bridge_audit import build_paper_bridge_audit_report
from scripts.run_market_state_rotation_v6_shadow_collection_progress import build_collection_progress_report
from scripts.run_market_state_rotation_v6_shadow_readiness_pipeline import (
    _lifecycle_payload_from_db,
    build_shadow_readiness_pipeline_report,
)


DEFAULT_STRESS_REPORT = (
    "reports/validation/diagnostics/"
    "market_state_rotation_v6_imp491_current_system_stress_after_top_audit/"
    "market_state_rotation_v6_current_system_stress.json"
)
DEFAULT_WALK_FORWARD_REPORT = (
    "reports/validation/diagnostics/"
    "market_state_rotation_v6_imp490_current_top_candidate_audit/"
    "market_state_rotation_v6_walk_forward_BTCUSDT_5m_latest.json"
)
DEFAULT_MANUAL_EVIDENCE = (
    "reports/validation/diagnostics/"
    "market_state_rotation_v6_manual_safety_drills/"
    "market_state_rotation_v6_manual_safety_evidence.json"
)


def _resolve(path: str | Path) -> Path:
    raw = Path(path)
    return raw if raw.is_absolute() else ROOT_DIR / raw


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _paper_fill_status(
    readiness_report: dict[str, Any],
    paper_bridge_report: dict[str, Any] | None = None,
    paper_bridge_tick_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    shadow = dict(readiness_report.get("shadow_fill_export") or {})
    bridge = dict(paper_bridge_report or {})
    bridge_counts = dict(bridge.get("counts") or {})
    bridge_tick = dict(paper_bridge_tick_report or {})
    bridge_tick_snapshot = dict(bridge_tick.get("snapshot") or {})
    bridge_tick_blockers = list(bridge_tick_snapshot.get("blockers") or [])
    rows = list(shadow.get("rows") or [])
    row_count = int(shadow.get("row_count") or len(rows))
    waiting_for_signal = str(bridge_tick.get("overall_status") or "") == "not_actionable" and "signal_stale" in bridge_tick_blockers
    bridge_status = (
        "runtime_bridge_waiting_for_fresh_signal"
        if waiting_for_signal
        else bridge.get("overall_status")
    )
    bridge_blockers = ["fresh_v6_signal_missing"] if waiting_for_signal else list(bridge.get("blockers") or [])
    return {
        "status": "collecting_required" if row_count <= 0 else "collecting",
        "v6_lifecycle_rows": row_count,
        "bridge_status": bridge_status,
        "v6_intents": bridge_counts.get("v6_intents"),
        "v6_submit_ready_intents": bridge_counts.get("v6_submit_ready_intents"),
        "bridge_blockers": bridge_blockers,
        "runtime_bridge_tick": {
            "status": bridge_tick.get("overall_status"),
            "snapshot_status": bridge_tick_snapshot.get("overall_status"),
            "snapshot_blockers": bridge_tick_blockers,
            "bridge_action": bridge_tick_snapshot.get("bridge_action"),
            "freshness": dict(bridge_tick_snapshot.get("freshness") or {}),
        }
        if bridge_tick
        else {},
        "reason": (
            "runtime_bridge_implemented_waiting_for_fresh_v6_signal"
            if waiting_for_signal
            else
            "no_market_state_rotation_v6_lifecycle_rows_in_current_db_window"
            if row_count <= 0
            else "market_state_rotation_v6_lifecycle_rows_present"
        ),
        "next_action": (
            "run_apply_paper_bridge_tick_when_fresh_v6_signal_appears"
            if waiting_for_signal
            else
            "connect_market_state_rotation_v6_runtime_decisions_to_paper_order_lifecycle"
            if row_count <= 0
            else "continue_until_min_shadow_fill_samples_is_met"
        ),
    }


def _quote_status(quote_report: dict[str, Any]) -> dict[str, Any]:
    return {
        "overall_status": quote_report.get("overall_status"),
        "eligible_row_count": int(quote_report.get("eligible_row_count") or 0),
        "required_quote_samples": int(quote_report.get("required_quote_samples") or 0),
        "missing_quote_samples": int(quote_report.get("missing_quote_samples") or 0),
        "calendar_day_count": int(quote_report.get("calendar_day_count") or 0),
        "min_calendar_days": int(quote_report.get("min_calendar_days") or 0),
        "distinct_hour_count": int(quote_report.get("distinct_hour_count") or 0),
        "min_distinct_hours": int(quote_report.get("min_distinct_hours") or 0),
        "calendar_days": list(quote_report.get("calendar_days") or []),
        "distinct_hours": list(quote_report.get("distinct_hours") or []),
        "coverage": dict(quote_report.get("coverage") or {}),
        "metrics": dict(quote_report.get("metrics") or {}),
        "blockers": list(quote_report.get("blockers") or []),
    }


def _collection_bottleneck_diagnosis(
    *,
    quote_status: dict[str, Any],
    paper_fill_status: dict[str, Any],
    readiness_status: dict[str, Any],
    shadow_fill_progress: dict[str, Any],
) -> dict[str, Any]:
    quote_missing_samples = max(
        int(quote_status.get("required_quote_samples") or 0) - int(quote_status.get("eligible_row_count") or 0),
        0,
    )
    quote_missing_days = max(
        int(quote_status.get("min_calendar_days") or 0) - int(quote_status.get("calendar_day_count") or 0),
        0,
    )
    quote_missing_hours = max(
        int(quote_status.get("min_distinct_hours") or 0) - int(quote_status.get("distinct_hour_count") or 0),
        0,
    )
    missing_shadow_fills = max(int(shadow_fill_progress.get("missing") or 0), 0)
    waiting_for_fresh_signal = (
        str(paper_fill_status.get("bridge_status") or "") == "runtime_bridge_waiting_for_fresh_signal"
        or "fresh_v6_signal_missing" in set(str(item) for item in paper_fill_status.get("bridge_blockers") or [])
    )
    quote_incomplete = bool(quote_missing_samples or quote_missing_days or quote_missing_hours)
    live_allowed = readiness_status.get("live_order_submission_allowed") is True

    if waiting_for_fresh_signal and missing_shadow_fills > 0:
        primary = "fresh_v6_signal_missing_for_paper_fill_collection"
    elif quote_incomplete:
        primary = "quote_shadow_collection_incomplete"
    elif missing_shadow_fills > 0:
        primary = "paper_fill_samples_missing"
    elif not live_allowed:
        primary = "readiness_gates_pending"
    else:
        primary = "ready_for_next_gate"

    collectable_now: list[str] = []
    if quote_incomplete:
        collectable_now.append("quote_shadow_samples")
    if missing_shadow_fills > 0 and not waiting_for_fresh_signal:
        collectable_now.append("paper_shadow_fill_samples")

    blocked_until: list[str] = []
    if waiting_for_fresh_signal:
        blocked_until.append("fresh_market_state_rotation_v6_add_or_remove_signal")
    if missing_shadow_fills > 0:
        blocked_until.append("min_shadow_fill_samples")
    if quote_incomplete:
        blocked_until.append("quote_shadow_sample_calendar_and_hour_floor")
    if not live_allowed:
        blocked_until.append("readiness_live_order_gate")

    return {
        "primary_bottleneck": primary,
        "waiting_for_fresh_signal": waiting_for_fresh_signal,
        "collectable_without_fresh_signal": collectable_now,
        "blocked_until": blocked_until,
        "quote_missing": {
            "samples": quote_missing_samples,
            "calendar_days": quote_missing_days,
            "distinct_hours": quote_missing_hours,
        },
        "paper_missing_shadow_fills": missing_shadow_fills,
        "max_authorized_stage": readiness_status.get("max_authorized_stage"),
        "live_order_submission_allowed": live_allowed,
    }


def build_collection_tick_summary(
    *,
    captured_quote_rows: int,
    quote_report: dict[str, Any],
    readiness_report: dict[str, Any],
    progress_report: dict[str, Any],
    roadmap_report: dict[str, Any],
    paper_bridge_report: dict[str, Any] | None = None,
    paper_bridge_tick_report: dict[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    readiness_summary = dict(readiness_report.get("summary") or {})
    progress_shadow = dict(progress_report.get("shadow_collection") or {})
    roadmap_stages = list(roadmap_report.get("stages") or [])
    quote_status = _quote_status(quote_report)
    paper_status = _paper_fill_status(
        readiness_report,
        paper_bridge_report=paper_bridge_report,
        paper_bridge_tick_report=paper_bridge_tick_report,
    )
    readiness_status = {
        "overall_status": readiness_report.get("overall_status"),
        "max_authorized_stage": readiness_summary.get("max_authorized_stage"),
        "ready_for_paper": readiness_summary.get("ready_for_paper"),
        "ready_for_tiny_live_canary": readiness_summary.get("ready_for_tiny_live_canary"),
        "live_order_submission_allowed": readiness_summary.get("live_order_submission_allowed"),
        "failed_gates": list(readiness_summary.get("failed_gates") or []),
        "pending_gates": list(readiness_summary.get("pending_gates") or []),
    }
    shadow_progress = {
        "observed": int(progress_shadow.get("observed_shadow_fill_samples") or 0),
        "required": int(progress_shadow.get("required_shadow_fill_samples") or 0),
        "missing": int(progress_shadow.get("missing_shadow_fill_samples") or 0),
        "eta_days": dict(progress_shadow.get("eta_days") or {}),
    }
    return {
        "generated_at": generated_at.isoformat(),
        "overall_status": "collecting" if roadmap_report.get("blockers") else "ready_for_next_gate",
        "no_live_order_sent": True,
        "captured_quote_rows": int(captured_quote_rows),
        "quote_shadow": quote_status,
        "paper_fill": paper_status,
        "readiness": readiness_status,
        "shadow_fill_progress": shadow_progress,
        "bottleneck_diagnosis": _collection_bottleneck_diagnosis(
            quote_status=quote_status,
            paper_fill_status=paper_status,
            readiness_status=readiness_status,
            shadow_fill_progress=shadow_progress,
        ),
        "roadmap": {
            "blockers": list(roadmap_report.get("blockers") or []),
            "stages": [
                {
                    "order": stage.get("order"),
                    "name": stage.get("name"),
                    "status": stage.get("status"),
                    "blockers": list(stage.get("blockers") or []),
                }
                for stage in roadmap_stages
            ],
        },
    }


def _markdown(report: dict[str, Any]) -> str:
    quote = dict(report.get("quote_shadow") or {})
    paper = dict(report.get("paper_fill") or {})
    readiness = dict(report.get("readiness") or {})
    shadow = dict(report.get("shadow_fill_progress") or {})
    roadmap = dict(report.get("roadmap") or {})
    lines = [
        "# Market State Rotation V6 Collection Tick",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- status: `{report.get('overall_status')}`",
        f"- no_live_order_sent: `{report.get('no_live_order_sent')}`",
        f"- captured_quote_rows: `{report.get('captured_quote_rows')}`",
        f"- quote_samples: `{quote.get('eligible_row_count')}/{quote.get('required_quote_samples')}`",
        f"- quote_days: `{quote.get('calendar_day_count')}/{quote.get('min_calendar_days')}`",
        f"- paper_fill_rows: `{paper.get('v6_lifecycle_rows')}`",
        f"- shadow_fill_samples: `{shadow.get('observed')}/{shadow.get('required')}`",
        f"- readiness: `{readiness.get('overall_status')}` / stage `{readiness.get('max_authorized_stage')}`",
        f"- blockers: `{', '.join(roadmap.get('blockers') or [])}`",
        "",
    ]
    return "\n".join(lines)


def run_collection_tick(
    *,
    sample_jsonl: Path,
    stress_report_path: Path,
    walk_forward_report_path: Path,
    manual_evidence_path: Path | None,
    paper_bridge_tick_report_path: Path | None = None,
    quote_samples_per_tick: int = 1,
    quote_sample_sleep_seconds: float = 0.0,
    required_quote_samples: int = 300,
    min_quote_calendar_days: int = 30,
    min_quote_distinct_hours: int = 24,
    min_shadow_fill_samples: int = 100,
    days: int = 30,
    limit: int = 500,
    symbol: str = EXPECTED_SYMBOL,
    strategy_family: str = EXPECTED_STRATEGY_FAMILY,
    report_dir: Path | None = None,
) -> dict[str, Any]:
    captured_rows: list[dict[str, Any]] = []
    for idx in range(max(0, int(quote_samples_per_tick))):
        if idx > 0 and quote_sample_sleep_seconds > 0.0:
            time.sleep(float(quote_sample_sleep_seconds))
        captured_rows.extend(
            capture_quote_shadow_rows(
                symbol=symbol,
                strategy_family=strategy_family,
                side="both",
                order_notional_usdt=125.0,
            )
        )
    if captured_rows:
        _append_jsonl(sample_jsonl, captured_rows)

    quote_rows = _load_jsonl(sample_jsonl)
    quote_report = build_quote_shadow_audit_report(
        quote_rows,
        input_sample_path=_display_path(sample_jsonl),
        expected_symbol=symbol,
        expected_strategy_family=strategy_family,
        required_quote_samples=max(1, int(required_quote_samples)),
        min_calendar_days=max(1, int(min_quote_calendar_days)),
        min_distinct_hours=max(1, int(min_quote_distinct_hours)),
    )
    quote_report["captured_row_count"] = len(captured_rows)

    manual_evidence = _load_json(manual_evidence_path) if manual_evidence_path is not None and manual_evidence_path.exists() else None
    paper_bridge_tick_report = (
        _load_json(paper_bridge_tick_report_path)
        if paper_bridge_tick_report_path is not None and paper_bridge_tick_report_path.exists()
        else None
    )
    lifecycle_payload = _lifecycle_payload_from_db(
        symbol=symbol,
        strategy_family=strategy_family,
        days=max(1, int(days)),
        limit=max(1, int(limit)),
        include_paper=True,
    )
    paper_bridge_report = build_paper_bridge_audit_report(
        lifecycle_payload,
        symbol=symbol,
        strategy_family=strategy_family,
        min_tiny_canary_fill_samples=20,
        min_full_live_fill_samples=max(1, int(min_shadow_fill_samples)),
    )
    readiness_report = build_shadow_readiness_pipeline_report(
        stress_report=_load_json(stress_report_path),
        lifecycle_payload=lifecycle_payload,
        manual_safety_evidence=manual_evidence,
        input_stress_report=_display_path(stress_report_path),
        input_lifecycle_report="generated_from_db",
        symbol=symbol,
        strategy_family=strategy_family,
        min_shadow_fill_samples=max(1, int(min_shadow_fill_samples)),
    )
    progress_report = build_collection_progress_report(
        _load_json(walk_forward_report_path),
        readiness_report,
        input_walk_report=_display_path(walk_forward_report_path),
        input_readiness_report="collection_tick:shadow_readiness_pipeline",
        min_shadow_fill_samples=max(1, int(min_shadow_fill_samples)),
    )
    roadmap_report = build_execution_roadmap_report(
        progress_report,
        input_progress_report="collection_tick:shadow_collection_progress",
        quote_shadow_report=quote_report,
        input_quote_shadow_report="collection_tick:quote_shadow_audit",
        paper_bridge_report=paper_bridge_report,
        input_paper_bridge_report="collection_tick:paper_bridge_audit",
        paper_bridge_tick_report=paper_bridge_tick_report,
        input_paper_bridge_tick_report=(
            _display_path(paper_bridge_tick_report_path)
            if paper_bridge_tick_report_path is not None and paper_bridge_tick_report_path.exists()
            else None
        ),
        required_quote_samples=max(1, int(required_quote_samples)),
        min_quote_calendar_days=max(1, int(min_quote_calendar_days)),
        min_quote_distinct_hours=max(1, int(min_quote_distinct_hours)),
    )
    tick_report = build_collection_tick_summary(
        captured_quote_rows=len(captured_rows),
        quote_report=quote_report,
        readiness_report=readiness_report,
        progress_report=progress_report,
        roadmap_report=roadmap_report,
        paper_bridge_report=paper_bridge_report,
        paper_bridge_tick_report=paper_bridge_tick_report,
    )
    if report_dir is not None:
        report_dir.mkdir(parents=True, exist_ok=True)
        _write_json(report_dir / "market_state_rotation_v6_quote_shadow_audit.json", quote_report)
        _write_json(report_dir / "market_state_rotation_v6_shadow_readiness_pipeline.json", readiness_report)
        shadow_export = dict(readiness_report.get("shadow_fill_export") or {})
        _write_json(report_dir / "market_state_rotation_v6_shadow_fill_export.json", shadow_export)
        _write_jsonl(report_dir / "market_state_rotation_v6_shadow_fills.jsonl", list(shadow_export.get("rows") or []))
        _write_json(report_dir / "market_state_rotation_v6_shadow_collection_progress.json", progress_report)
        _write_json(report_dir / "market_state_rotation_v6_execution_roadmap.json", roadmap_report)
        _write_json(report_dir / "market_state_rotation_v6_paper_bridge_audit.json", paper_bridge_report)
        _write_json(report_dir / "market_state_rotation_v6_collection_tick.json", tick_report)
        (report_dir / "market_state_rotation_v6_collection_tick.md").write_text(_markdown(tick_report), encoding="utf-8")
        tick_report["report_dir"] = _display_path(report_dir)
    return tick_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one safe market-state rotation v6 collection tick.")
    parser.add_argument("--sample-jsonl", default=DEFAULT_SAMPLE_PATH)
    parser.add_argument("--stress-report", default=DEFAULT_STRESS_REPORT)
    parser.add_argument("--walk-forward-report", default=DEFAULT_WALK_FORWARD_REPORT)
    parser.add_argument("--manual-safety-evidence", default=DEFAULT_MANUAL_EVIDENCE)
    parser.add_argument("--paper-bridge-tick-report", default="")
    parser.add_argument("--quote-samples-per-tick", type=int, default=1)
    parser.add_argument("--quote-sample-sleep-seconds", type=float, default=0.0)
    parser.add_argument("--required-quote-samples", type=int, default=300)
    parser.add_argument("--min-quote-calendar-days", type=int, default=30)
    parser.add_argument("--min-quote-distinct-hours", type=int, default=24)
    parser.add_argument("--min-shadow-fill-samples", type=int, default=100)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--symbol", default=EXPECTED_SYMBOL)
    parser.add_argument("--strategy-family", default=EXPECTED_STRATEGY_FAMILY)
    parser.add_argument("--report-dir", default="reports/validation/diagnostics/market_state_rotation_v6_collection_tick")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manual_path = _resolve(args.manual_safety_evidence) if args.manual_safety_evidence else None
    bridge_tick_path = _resolve(args.paper_bridge_tick_report) if args.paper_bridge_tick_report else None
    report = run_collection_tick(
        sample_jsonl=_resolve(args.sample_jsonl),
        stress_report_path=_resolve(args.stress_report),
        walk_forward_report_path=_resolve(args.walk_forward_report),
        manual_evidence_path=manual_path,
        paper_bridge_tick_report_path=bridge_tick_path,
        quote_samples_per_tick=max(0, int(args.quote_samples_per_tick)),
        quote_sample_sleep_seconds=max(0.0, float(args.quote_sample_sleep_seconds)),
        required_quote_samples=max(1, int(args.required_quote_samples)),
        min_quote_calendar_days=max(1, int(args.min_quote_calendar_days)),
        min_quote_distinct_hours=max(1, int(args.min_quote_distinct_hours)),
        min_shadow_fill_samples=max(1, int(args.min_shadow_fill_samples)),
        days=max(1, int(args.days)),
        limit=max(1, int(args.limit)),
        symbol=str(args.symbol or EXPECTED_SYMBOL).upper(),
        strategy_family=str(args.strategy_family or EXPECTED_STRATEGY_FAMILY),
        report_dir=_resolve(args.report_dir) if args.write_report else None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
