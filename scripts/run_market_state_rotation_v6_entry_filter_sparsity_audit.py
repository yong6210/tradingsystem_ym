#!/usr/bin/env python3
"""Audit whether v6 PAPER collection is blocked by overly sparse entry filters."""

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
    "reports/validation/diagnostics/market_state_rotation_v6_imp453_collection_cycle_add_signal_cadence/"
    "market_state_rotation_v6_collection_cycle.json"
)


REASON_CATALOG: dict[str, dict[str, Any]] = {
    "no_trade_MC12_low_confluence": {
        "class": "soft_candidate",
        "meaning": "both sides have some signal, but reason-stack depth is below the configured confluence floor",
        "safe_experiment": "near_miss_micro_probe_only_when_score_edge_and_extension_filters_pass",
    },
    "no_trade_MC04_no_clear_first_touch": {
        "class": "soft_candidate",
        "meaning": "long/short score edge is too small and the first-touch setup is not decisive enough",
        "safe_experiment": "observe_or_micro_probe_only_after_directional_bias_confirms",
    },
    "no_trade_MC27_time_event_chase_risk": {
        "class": "hard_guard",
        "meaning": "hour-open chase setup lacks enough score cushion and is vulnerable to event-time noise",
        "safe_experiment": "do_not_relax_without_separate_event_time_stress_test",
    },
    "no_trade_MC31_unconfirmed_breakout_volume": {
        "class": "hard_guard",
        "meaning": "breakout/chase lacks volume confirmation when the volume layer is enabled",
        "safe_experiment": "do_not_relax_without_liquidity_and_volume_parity_evidence",
    },
    "no_trade_MC32_quiet_tape": {
        "class": "hard_guard",
        "meaning": "quiet tape with weak body and insufficient battle score",
        "safe_experiment": "do_not_relax_for_leveraged_entries",
    },
    "no_trade_MC41_weak_long_round_rsi_reclaim": {
        "class": "context_guard",
        "meaning": "long reclaim is mostly round-level/RSI without enough cloud or structural support",
        "safe_experiment": "only test with higher-timeframe trend confirmation and tiny probe size",
    },
    "no_trade_MC44_mid_extension_heated_short_reject": {
        "class": "context_guard",
        "meaning": "short reject is already extended and RSI is heated in a downtrend",
        "safe_experiment": "only test as reduced-size continuation after pullback confirmation",
    },
}


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


def _annotate_reasons(top_no_trade_reasons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    total = sum(max(0, _int(item.get("count"))) for item in top_no_trade_reasons)
    for item in top_no_trade_reasons:
        reason = str(item.get("reason") or "")
        count = max(0, _int(item.get("count")))
        catalog = dict(REASON_CATALOG.get(reason) or {})
        annotated.append(
            {
                "reason": reason,
                "count": count,
                "share_of_top_reasons": round(count / total, 4) if total > 0 else 0.0,
                "class": catalog.get("class", "unknown"),
                "meaning": catalog.get("meaning", "not mapped yet"),
                "safe_experiment": catalog.get("safe_experiment", "manual_code_review_required_before_experiment"),
            }
        )
    return annotated


def _reason_class(reason: str) -> str:
    normalized = reason if reason.startswith("no_trade_") else f"no_trade_{reason}"
    return str(dict(REASON_CATALOG.get(normalized) or {}).get("class") or "unknown")


def _parse_context_key(key: str, count: int, total: int) -> dict[str, Any]:
    parts = str(key or "").split("|")
    reason = parts[0] if parts else ""
    row = {
        "context": str(key or ""),
        "reason": reason,
        "count": max(0, int(count)),
        "share_of_top_contexts": round(max(0, int(count)) / total, 4) if total > 0 else 0.0,
        "class": _reason_class(reason),
        "side": parts[1] if len(parts) > 1 else "unknown",
        "side_alignment": parts[2] if len(parts) > 2 else "unknown",
        "regime": parts[3] if len(parts) > 3 else "unknown",
        "execution_context": parts[4] if len(parts) > 4 else "unknown",
        "score_bucket": parts[5] if len(parts) > 5 else "unknown",
        "edge_bucket": parts[6] if len(parts) > 6 else "unknown",
        "reason_stack_bucket": parts[7] if len(parts) > 7 else "unknown",
        "extension_bucket": parts[8] if len(parts) > 8 else "unknown",
        "breakout_bucket": parts[9] if len(parts) > 9 else "unknown",
    }
    quality = _soft_context_probe_quality(row)
    row["probe_quality"] = quality["quality"]
    row["probe_quality_reasons"] = quality["reasons"]
    return row


def _soft_context_probe_quality(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("class") != "soft_candidate":
        return {"quality": "not_soft_candidate", "reasons": []}
    reasons: list[str] = []
    if row.get("execution_context") != "normal":
        reasons.append("execution_context_not_normal")
    if row.get("side_alignment") != "with_trend":
        reasons.append("not_with_trend")
    if row.get("regime") not in {"uptrend", "downtrend"}:
        reasons.append("regime_not_directional_trend")
    if row.get("score_bucket") == "score_0-3":
        reasons.append("score_too_low")
    if row.get("edge_bucket") == "edge_0-1":
        reasons.append("edge_too_low")
    if row.get("reason_stack_bucket") == "stack_0-1":
        reasons.append("reason_stack_too_thin")
    if row.get("extension_bucket") not in {"ext_0-0.75", "ext_0.75-1.5"}:
        reasons.append("extension_too_late")
    if row.get("reason") == "MC04_no_clear_first_touch":
        reasons.append("mc04_broad_relaxation_rejected_by_365d_probe")
    if reasons:
        return {"quality": "reject_low_quality_soft_context", "reasons": reasons}
    if row.get("reason") == "MC12_low_confluence":
        return {"quality": "eligible_mc12_quality_gated_micro_probe", "reasons": []}
    return {"quality": "observe_only_soft_context", "reasons": ["unsupported_soft_reason_for_probe"]}


def _annotate_contexts(top_no_trade_contexts: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        (str(key), max(0, _int(value)))
        for key, value in dict(top_no_trade_contexts or {}).items()
        if _int(value) > 0
    ]
    rows.sort(key=lambda item: item[1], reverse=True)
    total = sum(count for _, count in rows)
    return [_parse_context_key(key, count, total) for key, count in rows]


def build_entry_filter_sparsity_audit(
    cycle_report: dict[str, Any],
    *,
    input_cycle_report: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    bridge = dict(cycle_report.get("bridge") or {})
    cadence = dict(bridge.get("event_cadence") or {})
    reasons = _annotate_reasons(list(bridge.get("top_no_trade_reasons") or []))
    hotspots = dict(bridge.get("no_trade_hotspots") or {})
    top_contexts = _annotate_contexts(dict(hotspots.get("top_no_trade_contexts") or {}))
    latest_add_age_days = _float(cadence.get("latest_add_age_hours")) / 24.0
    expected_days_per_add = _float(cadence.get("expected_days_per_add"))
    add_wait_multiple = (
        round(latest_add_age_days / expected_days_per_add, 4)
        if expected_days_per_add > 0.0
        else None
    )
    soft_count = sum(item["count"] for item in reasons if item["class"] == "soft_candidate")
    hard_count = sum(item["count"] for item in reasons if item["class"] == "hard_guard")
    context_count = sum(item["count"] for item in reasons if item["class"] == "context_guard")
    soft_context_count = sum(item["count"] for item in top_contexts if item["class"] == "soft_candidate")
    hour_open_soft_context_count = sum(
        item["count"]
        for item in top_contexts
        if item["class"] == "soft_candidate" and item["execution_context"] == "hour_open"
    )
    normal_soft_context_count = sum(
        item["count"]
        for item in top_contexts
        if item["class"] == "soft_candidate" and item["execution_context"] == "normal"
    )
    probe_quality_counts: dict[str, int] = {}
    for item in top_contexts:
        quality = str(item.get("probe_quality") or "unknown")
        probe_quality_counts[quality] = probe_quality_counts.get(quality, 0) + int(item.get("count") or 0)
    eligible_probe_context_count = int(probe_quality_counts.get("eligible_mc12_quality_gated_micro_probe") or 0)
    rejected_soft_context_count = int(probe_quality_counts.get("reject_low_quality_soft_context") or 0)
    mc04_soft_context_count = sum(
        item["count"]
        for item in top_contexts
        if item["class"] == "soft_candidate" and item["reason"] == "MC04_no_clear_first_touch"
    )
    review_required = (
        str(cadence.get("add_wait_state") or "") == "latest_add_age_above_recent_median_gap"
        and (add_wait_multiple is None or add_wait_multiple >= 2.0)
    )
    if review_required and soft_count > hard_count:
        status = "entry_filter_sparsity_review_required"
    elif review_required:
        status = "entry_filter_waiting_long_but_hard_guards_dominate"
    else:
        status = "monitor"
    experiment_backlog = [
        {
            "name": "quality_gated_mc12_near_miss_micro_probe",
            "target_reasons": ["no_trade_MC12_low_confluence"],
            "constraints": [
                "paper_or_walk_forward_only",
                "probe_units_at_or_below_0.00025_until_full_walk_forward_improves",
                "require_score_above_3_edge_above_1_and_stack_above_1",
                "require_with_trend_uptrend_or_downtrend_context",
                "cap_extension_atr_at_1.5_or_less_before_entry",
                "failure_guard_and_cooldown_required",
                "exclude_mc04_broad_first_touch_relaxation",
            ],
            "acceptance": [
                "improves paper/walk-forward add cadence",
                "does not raise max OOS drawdown beyond existing gate",
                "does not increase hard-guard trades",
            ],
        },
        {
            "name": "mc04_first_touch_observation_only",
            "target_reasons": ["no_trade_MC04_no_clear_first_touch"],
            "constraints": [
                "do_not_promote_without_new_365d_evidence",
                "log_context_frequency_and_wait_for_score_edge_or_stack_improvement",
                "no_broad_relaxation_of_score_0_3_edge_0_1_stack_0_1_contexts",
            ],
            "acceptance": [
                "identifies a narrower high-quality first-touch subset",
                "does not unlock current low-score high-extension hotspots",
            ],
        },
    ]
    return {
        "generated_at": generated_at.isoformat(),
        "status": status,
        "input_cycle_report": input_cycle_report,
        "no_live_order_sent": True,
        "cadence": {
            "add_event_count": cadence.get("add_event_count"),
            "add_events_per_day": cadence.get("add_events_per_day"),
            "expected_days_per_add": cadence.get("expected_days_per_add"),
            "latest_add_age_days": round(latest_add_age_days, 4),
            "add_wait_multiple_vs_expected": add_wait_multiple,
            "median_add_gap_hours": cadence.get("median_add_gap_hours"),
            "latest_add_age_to_median_gap": cadence.get("latest_add_age_to_median_gap"),
            "add_wait_state": cadence.get("add_wait_state"),
        },
        "reason_class_counts": {
            "soft_candidate": soft_count,
            "hard_guard": hard_count,
            "context_guard": context_count,
            "unknown": sum(item["count"] for item in reasons if item["class"] == "unknown"),
        },
        "top_no_trade_reasons": reasons,
        "no_trade_hotspots": {
            "top_contexts": top_contexts,
            "reason_side_counts": dict(hotspots.get("no_trade_reason_side_counts") or {}),
            "reason_regime_counts": dict(hotspots.get("no_trade_reason_regime_counts") or {}),
            "context_class_counts": {
                "soft_candidate": soft_context_count,
                "soft_candidate_normal": normal_soft_context_count,
                "soft_candidate_hour_open": hour_open_soft_context_count,
                **{f"probe_quality_{key}": value for key, value in sorted(probe_quality_counts.items())},
            },
        },
        "diagnosis": {
            "primary_issue": (
                "soft_confluence_filters_are_dominating_current_no_trade_distribution"
                if soft_count > max(hard_count, context_count)
                else "hard_or_context_guards_are_dominating_current_no_trade_distribution"
            ),
            "primary_context": top_contexts[0] if top_contexts else None,
            "soft_contexts_are_mostly_normal_time": normal_soft_context_count > hour_open_soft_context_count,
            "dominant_soft_contexts_are_low_quality": rejected_soft_context_count > eligible_probe_context_count,
            "eligible_probe_context_count": eligible_probe_context_count,
            "rejected_soft_context_count": rejected_soft_context_count,
            "mc04_soft_context_count": mc04_soft_context_count,
            "mc04_broad_relaxation_rejected": mc04_soft_context_count > 0,
            "recommended_experiment_scope": (
                "mc12_quality_gated_micro_probe_only"
                if eligible_probe_context_count > 0
                else "do_not_relax_current_top_soft_contexts_without_new_evidence"
            ),
            "latest_add_signal_is_late_vs_expected": bool(review_required),
            "paper_fill_collection_will_remain_slow_without_fresh_adds": True,
        },
        "experiment_backlog": experiment_backlog,
        "non_negotiables": [
            "do_not_relax_hard_guards_directly",
            "do_not_count_relaxed_experiments_as_live_ready_without_walk_forward_and_paper_evidence",
            "do_not_enable_live_orders_from_this_audit",
            "do_not_bypass_kst_blocked_hours_or_event_time_chase_guards",
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    cadence = dict(report.get("cadence") or {})
    reasons = list(report.get("top_no_trade_reasons") or [])
    lines = [
        "# Market State Rotation V6 Entry Filter Sparsity Audit",
        "",
        f"- status: `{report.get('status')}`",
        f"- no_live_order_sent: `{report.get('no_live_order_sent')}`",
        f"- add_events_per_day: `{cadence.get('add_events_per_day')}`",
        f"- expected_days_per_add: `{cadence.get('expected_days_per_add')}`",
        f"- latest_add_age_days: `{cadence.get('latest_add_age_days')}`",
        f"- add_wait_state: `{cadence.get('add_wait_state')}`",
        "",
        "## Top No-Trade Reasons",
    ]
    for item in reasons[:8]:
        lines.append(f"- `{item.get('reason')}`: `{item.get('count')}` / `{item.get('class')}`")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit market_state_rotation_v6 entry filter sparsity.")
    parser.add_argument("--cycle-report", default=DEFAULT_CYCLE_REPORT)
    parser.add_argument("--report-dir", default="reports/validation/diagnostics/market_state_rotation_v6_entry_filter_sparsity_audit")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cycle_path = _resolve(args.cycle_report)
    report = build_entry_filter_sparsity_audit(
        _load_json(cycle_path),
        input_cycle_report=_display_path(cycle_path),
    )
    if args.write_report:
        report_dir = _resolve(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_entry_filter_sparsity_audit.json"
        md_path = report_dir / "market_state_rotation_v6_entry_filter_sparsity_audit.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        report["report_path"] = _display_path(json_path)
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
