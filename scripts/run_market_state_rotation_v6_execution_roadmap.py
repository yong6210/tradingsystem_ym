#!/usr/bin/env python3
"""Build an execution roadmap from v6 readiness/progress evidence.

This does not grant live authority.  It turns the current blockers into an
ordered, testable plan with explicit evidence tiers and acceptance gates.
"""

from __future__ import annotations

import argparse
import json
import shlex
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]

QUOTE_SHADOW_REQUIRED_FIELDS = (
    "timestamp",
    "symbol",
    "strategy_family",
    "decision_id",
    "side",
    "best_bid",
    "best_ask",
    "spread_bps",
    "market_slippage_bps",
    "depth_notional",
    "latency_ms",
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _pct(value: float) -> float:
    return round(float(value), 4)


def _eta_for_samples(samples: int, progress: dict[str, Any], *, rate_key: str = "pooled_events_per_day") -> float | None:
    rate = _float(dict(progress.get("historical_event_rates") or {}).get(rate_key))
    if samples <= 0:
        return 0.0
    if rate <= 0.0:
        return None
    return _pct(samples / rate)


def _append_flag(command: str, flag: str) -> str:
    parts = shlex.split(str(command or ""))
    if flag in parts:
        return str(command)
    parts.append(flag)
    return shlex.join(parts)


def _ensure_option(command: str, option: str, value: str) -> str:
    parts = shlex.split(str(command or ""))
    if option in parts:
        return str(command)
    parts.extend([option, value])
    return shlex.join(parts)


def _safe_refresh_command(source: Any, command: Any) -> str:
    normalized_source = str(source or "")
    safe_command = str(command or "")
    if not safe_command:
        return ""
    if "run_live_account_protection_audit.py" in safe_command or normalized_source == "live_account_protection":
        safe_command = _append_flag(safe_command, "--no-flatten-missing-stop")
        safe_command = _append_flag(safe_command, "--no-cancel-unexpected-open-orders")
    if "run_micro_live_synthetic_canary.py" in safe_command or normalized_source == "micro_live_synthetic_canary":
        safe_command = _ensure_option(safe_command, "--symbol", "BTCUSDT")
        safe_command = _append_flag(safe_command, "--no-private-balance")
        safe_command = _append_flag(safe_command, "--no-fail-exit")
    return safe_command


def _shadow_summary(progress: dict[str, Any], *, tiny_canary_min_fill_samples: int) -> dict[str, Any]:
    shadow = dict(progress.get("shadow_collection") or {})
    required_full = _int(shadow.get("required_shadow_fill_samples"), 100)
    observed = _int(shadow.get("observed_shadow_fill_samples"))
    missing_full = max(required_full - observed, 0)
    missing_tiny = max(max(1, int(tiny_canary_min_fill_samples)) - observed, 0)
    return {
        "observed_fill_samples": observed,
        "strict_full_live_required_fill_samples": required_full,
        "strict_full_live_missing_fill_samples": missing_full,
        "tiny_canary_required_fill_samples": max(1, int(tiny_canary_min_fill_samples)),
        "tiny_canary_missing_fill_samples": missing_tiny,
        "strict_full_live_eta_days": dict(shadow.get("eta_days") or {}),
        "tiny_canary_eta_days": {
            "pooled_rate": _eta_for_samples(missing_tiny, progress, rate_key="pooled_events_per_day"),
            "median_fold_rate": _eta_for_samples(missing_tiny, progress, rate_key="median_fold_events_per_day"),
            "p10_slow_fold_rate": _eta_for_samples(missing_tiny, progress, rate_key="p10_fold_events_per_day"),
            "p90_fast_fold_rate": _eta_for_samples(missing_tiny, progress, rate_key="p90_fold_events_per_day"),
        },
    }


def _quote_shadow_contract(
    *,
    required_quote_samples: int,
    min_calendar_days: int,
    min_distinct_hours: int,
    max_p95_spread_bps: float,
    max_p95_market_slippage_bps: float,
    max_p95_latency_ms: float,
) -> dict[str, Any]:
    return {
        "purpose": "measure live top-of-book, spread, market impact proxy, depth, and collection latency without live order authority",
        "required_quote_samples": max(1, int(required_quote_samples)),
        "min_calendar_days": max(1, int(min_calendar_days)),
        "min_distinct_hours": max(1, int(min_distinct_hours)),
        "required_fields": list(QUOTE_SHADOW_REQUIRED_FIELDS),
        "gates": {
            "schema_clean": "0 missing required fields",
            "symbol_family_match": "BTCUSDT and market_state_rotation_v6 only",
            "distinct_hours": f">={max(1, int(min_distinct_hours))}",
            "p95_spread_bps": f"<={float(max_p95_spread_bps)}",
            "p95_market_slippage_bps": f"<={float(max_p95_market_slippage_bps)}",
            "p95_latency_ms": f"<={float(max_p95_latency_ms)}",
        },
        "collection_mode": "record every actionable paper/shadow decision and every skipped setup that reaches execution precheck",
    }


def _safety_plan(progress: dict[str, Any]) -> dict[str, Any]:
    safety = dict(progress.get("safety_collection") or {})
    stale_sources = list(safety.get("stale_sources") or [])
    manual = list(safety.get("manual_only_required") or [])
    refresh_commands = [
        {
            "source": item.get("name"),
            "age_hours": item.get("age_hours"),
            "command": _safe_refresh_command(item.get("name"), item.get("refresh_command")),
        }
        for item in stale_sources
        if item.get("refresh_command")
    ]
    return {
        "verified_count": _int(safety.get("verified_count")),
        "required_count": _int(safety.get("required_count")),
        "missing_or_failed": list(safety.get("missing_or_failed") or []),
        "stale_source_count": len(stale_sources),
        "refresh_commands": refresh_commands,
        "manual_drills": manual,
    }


def _stage(
    order: int,
    name: str,
    *,
    status: str,
    objective: str,
    acceptance: list[str],
    commands: list[str] | None = None,
    blockers: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "order": order,
        "name": name,
        "status": status,
        "objective": objective,
        "acceptance": acceptance,
        "commands": list(commands or []),
        "blockers": list(blockers or []),
    }


def build_execution_roadmap_report(
    progress_report: dict[str, Any],
    *,
    input_progress_report: str | None = None,
    quote_shadow_report: dict[str, Any] | None = None,
    input_quote_shadow_report: str | None = None,
    paper_bridge_report: dict[str, Any] | None = None,
    input_paper_bridge_report: str | None = None,
    paper_bridge_tick_report: dict[str, Any] | None = None,
    input_paper_bridge_tick_report: str | None = None,
    max_fill_only_eta_days: float = 90.0,
    tiny_canary_min_fill_samples: int = 20,
    required_quote_samples: int = 300,
    min_quote_calendar_days: int = 30,
    min_quote_distinct_hours: int = 24,
    max_p95_spread_bps: float = 4.0,
    max_p95_market_slippage_bps: float = 8.0,
    max_p95_latency_ms: float = 1500.0,
) -> dict[str, Any]:
    shadow = _shadow_summary(
        progress_report,
        tiny_canary_min_fill_samples=max(1, int(tiny_canary_min_fill_samples)),
    )
    safety = _safety_plan(progress_report)
    quote_contract = _quote_shadow_contract(
        required_quote_samples=max(1, int(required_quote_samples)),
        min_calendar_days=max(1, int(min_quote_calendar_days)),
        min_distinct_hours=max(1, int(min_quote_distinct_hours)),
        max_p95_spread_bps=float(max_p95_spread_bps),
        max_p95_market_slippage_bps=float(max_p95_market_slippage_bps),
        max_p95_latency_ms=float(max_p95_latency_ms),
    )
    quote_report = dict(quote_shadow_report or {})
    quote_status = str(quote_report.get("overall_status") or "").upper()
    observed_quote_samples = _int(quote_report.get("eligible_row_count"))
    observed_quote_days = _int(quote_report.get("calendar_day_count"))
    observed_quote_hours = _int(quote_report.get("distinct_hour_count"))
    quote_blockers = list(quote_report.get("blockers") or [])
    if quote_report:
        quote_contract["input_quote_shadow_report"] = input_quote_shadow_report
        quote_contract["audit_status"] = quote_status
        quote_contract["observed_quote_samples"] = observed_quote_samples
        quote_contract["observed_calendar_days"] = observed_quote_days
        quote_contract["observed_distinct_hours"] = observed_quote_hours
        quote_contract["audit_metrics"] = dict(quote_report.get("metrics") or {})
        quote_contract["audit_blockers"] = quote_blockers
    quote_stage_done = quote_status == "PASS"
    quote_stage_started = bool(quote_report) and (
        observed_quote_samples > 0 or observed_quote_days > 0 or observed_quote_hours > 0
    )
    paper_bridge = dict(paper_bridge_report or {})
    paper_bridge_status = str(paper_bridge.get("overall_status") or "").lower()
    paper_bridge_blockers = list(paper_bridge.get("blockers") or [])
    paper_bridge_tick = dict(paper_bridge_tick_report or {})
    paper_bridge_tick_status = str(paper_bridge_tick.get("overall_status") or "").lower()
    paper_bridge_tick_snapshot = dict(paper_bridge_tick.get("snapshot") or {})
    paper_bridge_tick_blockers = list(paper_bridge_tick_snapshot.get("blockers") or [])
    paper_bridge_waiting_for_signal = bool(paper_bridge_tick) and (
        paper_bridge_tick_status in {"not_actionable", "dry_run", "dry_run_actionable"}
        and "signal_stale" in paper_bridge_tick_blockers
    )
    paper_bridge_missing = paper_bridge_status == "blocked_runtime_bridge_missing" or any(
        str(item) in {"v6_order_intent_bridge_missing", "v6_order_submission_bridge_missing"}
        for item in paper_bridge_blockers
    )
    paper_stage_blockers = list(paper_bridge_blockers)
    if paper_bridge_waiting_for_signal:
        paper_bridge_missing = False
        paper_stage_blockers = [
            blocker
            for blocker in paper_stage_blockers
            if blocker
            not in {
                "v6_order_intent_bridge_missing",
                "v6_order_submission_bridge_missing",
                "no_submit_ready_v6_intents",
            }
        ]
        paper_stage_blockers.insert(0, "fresh_v6_signal_missing")
    if shadow["tiny_canary_missing_fill_samples"]:
        paper_stage_blockers.append(f"missing_fill_samples:{shadow['tiny_canary_missing_fill_samples']}")
    full_eta = dict(shadow.get("strict_full_live_eta_days") or {}).get("pooled_rate")
    fill_only_impractical = full_eta is None or _float(full_eta) > float(max_fill_only_eta_days)
    stages = [
        _stage(
            1,
            "refresh_operation_reports",
            status="blocked" if safety["stale_source_count"] else "done",
            objective="make automatic safety evidence fresh enough to evaluate",
            acceptance=["all trusted operation sources are fresh", "automatic safety controls pass or expose concrete failures"],
            commands=[str(item.get("command")) for item in safety["refresh_commands"] if item.get("command")],
            blockers=[str(item.get("source")) for item in safety["refresh_commands"] if item.get("source")],
        ),
        _stage(
            2,
            "manual_safety_drills",
            status="blocked" if safety["manual_drills"] else "done",
            objective="prove controls that cannot be trusted from passive reports",
            acceptance=[
                "kill switch blocks new entries",
                "daily loss cap blocks new entries after threshold breach",
                "duplicate client-order-id or intent replay cannot create duplicate orders",
            ],
            blockers=[str(item.get("name")) for item in safety["manual_drills"]],
        ),
        _stage(
            3,
            "quote_liquidity_shadow_collection",
            status="done" if quote_stage_done else ("collecting" if quote_stage_started else "not_started"),
            objective="replace slow fill-only evidence with high-frequency execution-environment evidence",
            acceptance=[
                f"{quote_contract['required_quote_samples']} quote/liquidity samples",
                f"{quote_contract['min_calendar_days']} calendar days minimum",
                f"{quote_contract['min_distinct_hours']} distinct UTC hours minimum",
                f"p95 spread {quote_contract['gates']['p95_spread_bps']}",
                f"p95 market slippage proxy {quote_contract['gates']['p95_market_slippage_bps']}",
                f"p95 latency {quote_contract['gates']['p95_latency_ms']}",
            ],
            blockers=[] if quote_stage_done else quote_blockers,
        ),
        _stage(
            4,
            "paper_fill_collection",
            status="blocked" if paper_stage_blockers else "done",
            objective="collect real paper/shadow order lifecycle rows tied to market_state_rotation_v6 lineage",
            acceptance=[
                f"{shadow['tiny_canary_required_fill_samples']} fill samples for tiny canary review",
                f"{shadow['strict_full_live_required_fill_samples']} fill samples remains full-live floor",
                "p95/max adverse slippage, spread, latency, rejects and partial fills pass execution audit",
            ],
            blockers=paper_stage_blockers,
        ),
        _stage(
            5,
            "tiny_live_canary_review",
            status="locked",
            objective="permit only reduced-size canary after all prior evidence tiers pass",
            acceptance=[
                "execution_shadow_audit overall_status=tiny_live_canary_ready",
                "full_live_order_submission_allowed remains false",
                "daily review cadence active",
            ],
        ),
        _stage(
            6,
            "full_live_review",
            status="locked",
            objective="full live remains disabled until separate canary/live parity evidence exists",
            acceptance=[
                "100 strict fill samples",
                "canary live parity report pass",
                "drawdown and execution degradation remain within limits after canary",
            ],
        ),
    ]
    blockers: list[str] = []
    if fill_only_impractical:
        blockers.append("fill_only_collection_too_slow_for_practical_iteration")
    if safety["stale_source_count"]:
        blockers.append("stale_operation_reports")
    if safety["manual_drills"]:
        blockers.append("manual_safety_drills_missing")
    if quote_report and not quote_stage_done:
        blockers.append("quote_shadow_collection_incomplete")
    if paper_bridge_waiting_for_signal:
        blockers.append("paper_runtime_bridge_waiting_for_fresh_signal")
    elif paper_bridge_missing:
        blockers.append("paper_runtime_bridge_missing")
    if shadow["tiny_canary_missing_fill_samples"]:
        blockers.append("paper_fill_samples_missing")
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "status": "roadmap_ready",
        "input_progress_report": input_progress_report,
        "source_progress_report": input_progress_report,
        "input_quote_shadow_report": input_quote_shadow_report,
        "input_paper_bridge_report": input_paper_bridge_report,
        "input_paper_bridge_tick_report": input_paper_bridge_tick_report,
        "diagnosis": {
            "fill_only_collection_impractical": fill_only_impractical,
            "max_fill_only_eta_days": float(max_fill_only_eta_days),
            "strict_full_live_fill_eta_days_pooled": full_eta,
            "primary_bottleneck": (
                "shadow_fill_collection_and_safety_evidence"
                if blockers
                else "none"
            ),
        },
        "shadow_fill_plan": shadow,
        "paper_bridge_plan": {
            "input_paper_bridge_report": input_paper_bridge_report,
            "input_paper_bridge_tick_report": input_paper_bridge_tick_report,
            "audit_status": paper_bridge.get("overall_status"),
            "counts": dict(paper_bridge.get("counts") or {}),
            "blockers": paper_bridge_blockers,
            "next_actions": list(paper_bridge.get("next_actions") or []),
            "runtime_tick": {
                "status": paper_bridge_tick.get("overall_status"),
                "apply_paper": paper_bridge_tick.get("apply_paper"),
                "snapshot_status": paper_bridge_tick_snapshot.get("overall_status"),
                "snapshot_blockers": paper_bridge_tick_blockers,
                "bridge_action": paper_bridge_tick_snapshot.get("bridge_action"),
                "latest_event": paper_bridge_tick_snapshot.get("latest_event"),
                "freshness": dict(paper_bridge_tick_snapshot.get("freshness") or {}),
            }
            if paper_bridge_tick
            else {},
        } if (paper_bridge or paper_bridge_tick) else {},
        "quote_shadow_contract": quote_contract,
        "safety_plan": safety,
        "stages": stages,
        "blockers": blockers,
        "non_negotiables": [
            "do_not_enable_full_live_from_backtest_only",
            "do_not_count_synthetic_backtest_events_as_execution_fills",
            "do_not_treat_stale_operation_reports_as_verified_safety_controls",
            "do_not_lower_full_live_fill_floor_below_100_without_separate_canary_live_parity_evidence",
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    diagnosis = dict(report.get("diagnosis") or {})
    shadow = dict(report.get("shadow_fill_plan") or {})
    quote = dict(report.get("quote_shadow_contract") or {})
    safety = dict(report.get("safety_plan") or {})
    lines = [
        "# Market State Rotation V6 Execution Roadmap",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Primary bottleneck: `{diagnosis.get('primary_bottleneck')}`",
        f"- Fill-only impractical: `{diagnosis.get('fill_only_collection_impractical')}`",
        f"- Strict full-live fill ETA days: `{diagnosis.get('strict_full_live_fill_eta_days_pooled')}`",
        f"- Tiny canary fill samples: `{shadow.get('observed_fill_samples')}/{shadow.get('tiny_canary_required_fill_samples')}`",
        f"- Full-live fill samples: `{shadow.get('observed_fill_samples')}/{shadow.get('strict_full_live_required_fill_samples')}`",
        f"- Quote samples required: `{quote.get('required_quote_samples')}` over `{quote.get('min_calendar_days')}` days and `{quote.get('min_distinct_hours')}` UTC hours",
        f"- Safety verified: `{safety.get('verified_count')}/{safety.get('required_count')}`",
        "",
        "## Stages",
        "",
    ]
    for stage in list(report.get("stages") or []):
        lines.append(
            f"- {stage.get('order')}. {stage.get('name')}: `{stage.get('status')}` - {stage.get('objective')}"
        )
    lines.extend(["", "## Commands", ""])
    for stage in list(report.get("stages") or []):
        for command in list(stage.get("commands") or []):
            lines.append(f"- `{command}`")
    lines.extend(["", "## Non-Negotiables", ""])
    for item in list(report.get("non_negotiables") or []):
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v6 execution roadmap from collection progress.")
    parser.add_argument("--progress-report", required=True)
    parser.add_argument("--quote-shadow-report", default="")
    parser.add_argument("--paper-bridge-report", default="")
    parser.add_argument("--paper-bridge-tick-report", default="")
    parser.add_argument("--max-fill-only-eta-days", type=float, default=90.0)
    parser.add_argument("--tiny-canary-min-fill-samples", type=int, default=20)
    parser.add_argument("--required-quote-samples", type=int, default=300)
    parser.add_argument("--min-quote-calendar-days", type=int, default=30)
    parser.add_argument("--min-quote-distinct-hours", type=int, default=24)
    parser.add_argument("--report-dir", default="reports/validation/diagnostics/market_state_rotation_v6_execution_roadmap")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    progress_path = Path(args.progress_report)
    if not progress_path.is_absolute():
        progress_path = ROOT_DIR / progress_path
    quote_path = Path(args.quote_shadow_report) if args.quote_shadow_report else None
    if quote_path is not None and not quote_path.is_absolute():
        quote_path = ROOT_DIR / quote_path
    paper_bridge_path = Path(args.paper_bridge_report) if args.paper_bridge_report else None
    if paper_bridge_path is not None and not paper_bridge_path.is_absolute():
        paper_bridge_path = ROOT_DIR / paper_bridge_path
    paper_bridge_tick_path = Path(args.paper_bridge_tick_report) if args.paper_bridge_tick_report else None
    if paper_bridge_tick_path is not None and not paper_bridge_tick_path.is_absolute():
        paper_bridge_tick_path = ROOT_DIR / paper_bridge_tick_path
    report = build_execution_roadmap_report(
        _load_json(progress_path),
        input_progress_report=_display_path(progress_path),
        quote_shadow_report=_load_json(quote_path) if quote_path is not None else None,
        input_quote_shadow_report=_display_path(quote_path) if quote_path is not None else None,
        paper_bridge_report=_load_json(paper_bridge_path) if paper_bridge_path is not None else None,
        input_paper_bridge_report=_display_path(paper_bridge_path) if paper_bridge_path is not None else None,
        paper_bridge_tick_report=_load_json(paper_bridge_tick_path) if paper_bridge_tick_path is not None else None,
        input_paper_bridge_tick_report=(
            _display_path(paper_bridge_tick_path) if paper_bridge_tick_path is not None else None
        ),
        max_fill_only_eta_days=float(args.max_fill_only_eta_days),
        tiny_canary_min_fill_samples=max(1, int(args.tiny_canary_min_fill_samples)),
        required_quote_samples=max(1, int(args.required_quote_samples)),
        min_quote_calendar_days=max(1, int(args.min_quote_calendar_days)),
        min_quote_distinct_hours=max(1, int(args.min_quote_distinct_hours)),
    )
    if args.write_report:
        report_dir = Path(args.report_dir)
        if not report_dir.is_absolute():
            report_dir = ROOT_DIR / report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_execution_roadmap.json"
        md_path = report_dir / "market_state_rotation_v6_execution_roadmap.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
