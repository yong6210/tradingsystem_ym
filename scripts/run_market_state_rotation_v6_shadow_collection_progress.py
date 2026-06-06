#!/usr/bin/env python3
"""Estimate v6 shadow collection progress and remaining evidence work."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]

MANUAL_ONLY_SAFETY_CONTROLS = {
    "kill_switch_verified": "run and record an emergency lock or close-only drill that blocks new entries",
    "max_daily_loss_verified": "run and record a daily-loss-cap drill that blocks new entries after threshold breach",
    "idempotent_client_order_id_verified": "run and record duplicate intent/client-order-id rejection evidence",
}

REFRESH_COMMANDS = {
    "live_account_protection": "uv run python scripts/run_live_account_protection_audit.py --no-fail-exit",
    "live_leverage_cap_sync": "uv run python scripts/run_live_leverage_cap_sync.py --no-fail-exit",
    "live_reconciliation_watchdog": "uv run python scripts/run_live_reconciliation_watchdog.py --no-fail-exit",
    "micro_live_failure_drill": "uv run python scripts/run_micro_live_failure_drill.py --no-fail-exit",
    "micro_live_runtime_guard": "uv run python scripts/run_micro_live_runtime_guard.py --no-fail-exit",
    "micro_live_synthetic_canary": "uv run python scripts/run_micro_live_synthetic_canary.py",
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _pct(value: float) -> float:
    return round(float(value), 4)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return _pct(ordered[0])
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return _pct(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _days_between(start: Any, end: Any) -> float:
    start_ts = _parse_ts(start)
    end_ts = _parse_ts(end)
    if start_ts is None or end_ts is None or end_ts <= start_ts:
        return 0.0
    return max((end_ts - start_ts).total_seconds() / 86400.0, 0.0)


def _fold_event_rows(walk_report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fold in list(walk_report.get("folds") or []):
        result = dict(fold.get("test_result") or {})
        start = fold.get("test_start_at") or fold.get("test_start")
        end = fold.get("test_end_at") or fold.get("test_end")
        days = _days_between(start, end)
        events = int(result.get("trade_like_events") or 0)
        rows.append(
            {
                "fold": int(fold.get("fold") or 0),
                "test_start": start,
                "test_end": end,
                "days": _pct(days),
                "trade_like_events": events,
                "events_per_day": _pct(events / days) if days > 0.0 else 0.0,
            }
        )
    return rows


def _event_rate_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rates = [_float(row.get("events_per_day")) for row in rows if _float(row.get("days")) > 0.0]
    total_events = sum(int(row.get("trade_like_events") or 0) for row in rows)
    total_days = sum(_float(row.get("days")) for row in rows)
    return {
        "fold_count": len(rows),
        "total_trade_like_events": total_events,
        "total_oos_days": _pct(total_days),
        "pooled_events_per_day": _pct(total_events / total_days) if total_days > 0.0 else 0.0,
        "avg_fold_events_per_day": _pct(mean(rates)) if rates else 0.0,
        "median_fold_events_per_day": _pct(median(rates)) if rates else 0.0,
        "p10_fold_events_per_day": _percentile(rates, 0.10),
        "p90_fold_events_per_day": _percentile(rates, 0.90),
        "min_fold_events_per_day": _pct(min(rates)) if rates else 0.0,
        "max_fold_events_per_day": _pct(max(rates)) if rates else 0.0,
        "folds": rows,
    }


def _eta_days(missing_samples: int, rate: float | None) -> float | None:
    if rate is None or rate <= 0.0 or missing_samples <= 0:
        return 0.0 if missing_samples <= 0 else None
    return _pct(missing_samples / rate)


def _shadow_progress(readiness_report: dict[str, Any], event_rates: dict[str, Any], min_shadow_fill_samples: int) -> dict[str, Any]:
    shadow_export = dict(readiness_report.get("shadow_fill_export") or {})
    audit = dict(readiness_report.get("execution_shadow_audit") or {})
    audit_metrics = dict(audit.get("shadow_fill_metrics") or {})
    observed = int(
        shadow_export.get("row_count")
        if shadow_export.get("row_count") is not None
        else audit_metrics.get("fill_metric_sample_count") or 0
    )
    required = max(1, int(min_shadow_fill_samples))
    missing = max(required - observed, 0)
    pooled_rate = _float(event_rates.get("pooled_events_per_day"))
    median_rate = _float(event_rates.get("median_fold_events_per_day"))
    p10_rate = event_rates.get("p10_fold_events_per_day")
    p90_rate = event_rates.get("p90_fold_events_per_day")
    return {
        "required_shadow_fill_samples": required,
        "observed_shadow_fill_samples": observed,
        "missing_shadow_fill_samples": missing,
        "progress_pct": _pct(observed / required * 100.0),
        "status": "complete" if missing == 0 else "collecting_required",
        "historical_event_rate_basis": "walk_forward_trade_like_events_per_oos_day",
        "eta_days": {
            "pooled_rate": _eta_days(missing, pooled_rate),
            "median_fold_rate": _eta_days(missing, median_rate),
            "p10_slow_fold_rate": _eta_days(missing, _float(p10_rate) if p10_rate is not None else None),
            "p90_fast_fold_rate": _eta_days(missing, _float(p90_rate) if p90_rate is not None else None),
        },
    }


def _safety_progress(readiness_report: dict[str, Any]) -> dict[str, Any]:
    safety = dict(readiness_report.get("safety_evidence_collection") or {})
    source_reports = dict(safety.get("source_reports") or {})
    missing = list(safety.get("missing_or_failed") or [])
    stale_sources = [
        {
            "name": name,
            "age_hours": source.get("age_hours"),
            "path": source.get("path"),
            "refresh_command": REFRESH_COMMANDS.get(name),
        }
        for name, source in source_reports.items()
        if source.get("available") and not source.get("fresh")
    ]
    unavailable_sources = [
        {
            "name": name,
            "path": source.get("path"),
            "refresh_command": REFRESH_COMMANDS.get(name),
        }
        for name, source in source_reports.items()
        if not source.get("available")
    ]
    manual_required = [
        {
            "name": name,
            "required_evidence": MANUAL_ONLY_SAFETY_CONTROLS[name],
        }
        for name in missing
        if name in MANUAL_ONLY_SAFETY_CONTROLS
    ]
    return {
        "overall_status": safety.get("overall_status"),
        "verified_count": int(safety.get("verified_count") or 0),
        "required_count": int(safety.get("required_count") or 0),
        "missing_or_failed": missing,
        "stale_source_count": len(stale_sources),
        "stale_sources": stale_sources,
        "unavailable_source_count": len(unavailable_sources),
        "unavailable_sources": unavailable_sources,
        "manual_only_required_count": len(manual_required),
        "manual_only_required": manual_required,
    }


def build_collection_progress_report(
    walk_report: dict[str, Any],
    readiness_report: dict[str, Any],
    *,
    input_walk_report: str | None = None,
    input_readiness_report: str | None = None,
    min_shadow_fill_samples: int = 100,
) -> dict[str, Any]:
    fold_rows = _fold_event_rows(walk_report)
    event_rates = _event_rate_summary(fold_rows)
    shadow = _shadow_progress(readiness_report, event_rates, min_shadow_fill_samples)
    safety = _safety_progress(readiness_report)
    readiness_summary = dict(readiness_report.get("summary") or {})
    blockers: list[str] = []
    if shadow.get("missing_shadow_fill_samples"):
        blockers.append("shadow_fill_samples_missing")
    if safety.get("missing_or_failed"):
        blockers.append("safety_controls_missing_or_stale")
    if readiness_summary.get("ready_for_tiny_live_canary"):
        status = "tiny_live_canary_ready"
    elif blockers:
        status = "collection_incomplete"
    else:
        status = "ready_for_next_gate"
    next_actions: list[str] = []
    if "shadow_fill_samples_missing" in blockers:
        next_actions.append("run_market_state_rotation_v6_in_paper_or_shadow_until_required_fill_samples_are_observed")
    if safety.get("stale_source_count"):
        next_actions.append("refresh_stale_operation_reports_then_rerun_shadow_readiness_pipeline")
    if safety.get("manual_only_required_count"):
        next_actions.append("supply_manual_safety_drill_evidence_for_controls_without_trusted_auto_source")
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "status": status,
        "input_walk_report": input_walk_report,
        "input_readiness_report": input_readiness_report,
        "readiness_status": readiness_report.get("overall_status"),
        "readiness_summary": readiness_summary,
        "shadow_collection": shadow,
        "historical_event_rates": event_rates,
        "safety_collection": safety,
        "blockers": blockers,
        "next_actions": next_actions,
    }


def _markdown(report: dict[str, Any]) -> str:
    shadow = dict(report.get("shadow_collection") or {})
    safety = dict(report.get("safety_collection") or {})
    eta = dict(shadow.get("eta_days") or {})
    lines = [
        "# Market State Rotation V6 Shadow Collection Progress",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Readiness status: `{report.get('readiness_status')}`",
        f"- Shadow samples: `{shadow.get('observed_shadow_fill_samples')}/{shadow.get('required_shadow_fill_samples')}`",
        f"- Missing samples: `{shadow.get('missing_shadow_fill_samples')}`",
        f"- ETA days pooled/median/p10/p90: `{eta.get('pooled_rate')}/{eta.get('median_fold_rate')}/{eta.get('p10_slow_fold_rate')}/{eta.get('p90_fast_fold_rate')}`",
        f"- Safety verified: `{safety.get('verified_count')}/{safety.get('required_count')}`",
        f"- Stale safety sources: `{safety.get('stale_source_count')}`",
        f"- Manual-only safety controls: `{safety.get('manual_only_required_count')}`",
        "",
        "## Next Actions",
        "",
    ]
    for action in list(report.get("next_actions") or []):
        lines.append(f"- {action}")
    lines.extend(["", "## Stale Sources", ""])
    for source in list(safety.get("stale_sources") or []):
        lines.append(
            f"- {source.get('name')}: age_hours=`{source.get('age_hours')}` command=`{source.get('refresh_command')}`"
        )
    lines.extend(["", "## Manual Evidence", ""])
    for item in list(safety.get("manual_only_required") or []):
        lines.append(f"- {item.get('name')}: {item.get('required_evidence')}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estimate v6 shadow collection progress, ETA, and remaining safety evidence work."
    )
    parser.add_argument("--walk-forward-report", required=True)
    parser.add_argument("--readiness-report", required=True)
    parser.add_argument("--min-shadow-fill-samples", type=int, default=100)
    parser.add_argument("--report-dir", default="reports/validation/diagnostics/market_state_rotation_v6_shadow_collection_progress")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    walk_path = Path(args.walk_forward_report)
    if not walk_path.is_absolute():
        walk_path = ROOT_DIR / walk_path
    readiness_path = Path(args.readiness_report)
    if not readiness_path.is_absolute():
        readiness_path = ROOT_DIR / readiness_path
    report = build_collection_progress_report(
        _load_json(walk_path),
        _load_json(readiness_path),
        input_walk_report=_display_path(walk_path),
        input_readiness_report=_display_path(readiness_path),
        min_shadow_fill_samples=max(1, int(args.min_shadow_fill_samples)),
    )
    if args.write_report:
        report_dir = Path(args.report_dir)
        if not report_dir.is_absolute():
            report_dir = ROOT_DIR / report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_shadow_collection_progress.json"
        md_path = report_dir / "market_state_rotation_v6_shadow_collection_progress.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
