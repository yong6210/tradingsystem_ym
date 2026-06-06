#!/usr/bin/env python3
"""Audit whether v6 runtime decisions are connected to PAPER lifecycle rows."""

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

from app.db.session import SessionLocal, init_db
from app.services.live_order_lifecycle import LiveOrderLifecycleReporter


EXPECTED_SYMBOL = "BTCUSDT"
EXPECTED_STRATEGY_FAMILY = "market_state_rotation_v6"


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _load_lifecycle_from_db(*, symbol: str, strategy_family: str, days: int, limit: int) -> dict[str, Any]:
    init_db()
    with SessionLocal() as db:
        return LiveOrderLifecycleReporter(db).generate(
            days=max(1, int(days)),
            symbol=symbol.upper(),
            live_only=False,
            limit=max(1, int(limit)),
            strategy_families=[strategy_family],
        )


def build_paper_bridge_audit_report(
    lifecycle_payload: dict[str, Any],
    *,
    symbol: str = EXPECTED_SYMBOL,
    strategy_family: str = EXPECTED_STRATEGY_FAMILY,
    min_tiny_canary_fill_samples: int = 20,
    min_full_live_fill_samples: int = 100,
) -> dict[str, Any]:
    summary = dict(lifecycle_payload.get("summary") or {})
    live_intents = dict(summary.get("live_intents") or {})
    rows = list(lifecycle_payload.get("rows") or [])
    entry_fill_rows = [
        row
        for row in rows
        if str(row.get("strategy_family") or "") == strategy_family
        and str(row.get("symbol") or "").upper() == symbol.upper()
        and _safe_int(row.get("entry_fill_count")) > 0
    ]
    intent_total = _safe_int(live_intents.get("total"))
    submit_ready = _safe_int(live_intents.get("submit_ready"))
    submission_count = len(rows)
    entry_fill_count = len(entry_fill_rows)

    blockers: list[str] = []
    if intent_total <= 0:
        blockers.append("v6_order_intent_bridge_missing")
    if intent_total > 0 and submit_ready <= 0:
        blockers.append("no_submit_ready_v6_intents")
    if submission_count <= 0:
        blockers.append("v6_order_submission_bridge_missing")
    if entry_fill_count < max(1, int(min_tiny_canary_fill_samples)):
        blockers.append("tiny_canary_paper_fill_samples_missing")
    if entry_fill_count < max(1, int(min_full_live_fill_samples)):
        blockers.append("full_live_paper_fill_samples_missing")

    if "v6_order_intent_bridge_missing" in blockers or "v6_order_submission_bridge_missing" in blockers:
        status = "blocked_runtime_bridge_missing"
    elif "tiny_canary_paper_fill_samples_missing" in blockers:
        status = "collecting_required"
    elif "full_live_paper_fill_samples_missing" in blockers:
        status = "tiny_canary_sample_floor_met"
    else:
        status = "full_live_sample_floor_met"

    next_actions: list[str] = []
    if "v6_order_intent_bridge_missing" in blockers:
        next_actions.append("connect_market_state_rotation_v6_runtime_decisions_to_order_intent_creation_in_paper_mode")
    if "v6_order_submission_bridge_missing" in blockers:
        next_actions.append("route_submit_ready_v6_order_intents_to_paper_order_submission_lifecycle")
    if "tiny_canary_paper_fill_samples_missing" in blockers and submission_count > 0:
        next_actions.append("continue_paper_fill_sampling_until_20_v6_entry_fill_rows_are_observed")
    if "full_live_paper_fill_samples_missing" in blockers and entry_fill_count >= max(1, int(min_tiny_canary_fill_samples)):
        next_actions.append("continue_paper_fill_sampling_until_100_v6_entry_fill_rows_are_observed")

    return {
        "created_at": datetime.now(UTC).isoformat(),
        "overall_status": status,
        "symbol": symbol.upper(),
        "strategy_family": strategy_family,
        "window_start": lifecycle_payload.get("window_start"),
        "window_days": lifecycle_payload.get("window_days"),
        "counts": {
            "v6_intents": intent_total,
            "v6_submit_ready_intents": submit_ready,
            "v6_submissions": submission_count,
            "v6_entry_fill_rows": entry_fill_count,
            "tiny_canary_required_fill_samples": max(1, int(min_tiny_canary_fill_samples)),
            "full_live_required_fill_samples": max(1, int(min_full_live_fill_samples)),
        },
        "intent_summary": live_intents,
        "recent_rows": rows[:10],
        "blockers": blockers,
        "next_actions": next_actions,
        "non_negotiables": [
            "paper_bridge_audit_is_read_only",
            "do_not_create_synthetic_lifecycle_rows_to_satisfy_execution_evidence",
            "do_not_count_non_v6_strategy_families_as_market_state_rotation_v6_samples",
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    counts = dict(report.get("counts") or {})
    return "\n".join(
        [
            "# Market State Rotation V6 Paper Bridge Audit",
            "",
            f"- Status: `{report.get('overall_status')}`",
            f"- v6 intents: `{counts.get('v6_intents')}`",
            f"- v6 submit-ready intents: `{counts.get('v6_submit_ready_intents')}`",
            f"- v6 submissions: `{counts.get('v6_submissions')}`",
            f"- v6 entry fill rows: `{counts.get('v6_entry_fill_rows')}`",
            f"- Blockers: `{', '.join(report.get('blockers') or [])}`",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit v6 PAPER lifecycle bridge readiness.")
    parser.add_argument("--symbol", default=EXPECTED_SYMBOL)
    parser.add_argument("--strategy-family", default=EXPECTED_STRATEGY_FAMILY)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--min-tiny-canary-fill-samples", type=int, default=20)
    parser.add_argument("--min-full-live-fill-samples", type=int, default=100)
    parser.add_argument("--report-dir", default="reports/validation/diagnostics/market_state_rotation_v6_paper_bridge_audit")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    lifecycle = _load_lifecycle_from_db(
        symbol=str(args.symbol or EXPECTED_SYMBOL),
        strategy_family=str(args.strategy_family or EXPECTED_STRATEGY_FAMILY),
        days=max(1, int(args.days)),
        limit=max(1, int(args.limit)),
    )
    report = build_paper_bridge_audit_report(
        lifecycle,
        symbol=str(args.symbol or EXPECTED_SYMBOL),
        strategy_family=str(args.strategy_family or EXPECTED_STRATEGY_FAMILY),
        min_tiny_canary_fill_samples=max(1, int(args.min_tiny_canary_fill_samples)),
        min_full_live_fill_samples=max(1, int(args.min_full_live_fill_samples)),
    )
    if args.write_report:
        report_dir = Path(args.report_dir)
        if not report_dir.is_absolute():
            report_dir = ROOT_DIR / report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_paper_bridge_audit.json"
        md_path = report_dir / "market_state_rotation_v6_paper_bridge_audit.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
