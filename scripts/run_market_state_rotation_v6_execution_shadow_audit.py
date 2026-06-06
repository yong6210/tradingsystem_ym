#!/usr/bin/env python3
"""Audit market-state rotation v6 shadow/paper execution quality.

The stress report says whether the strategy survived historical replay.  This
script checks the missing deployment evidence: actual shadow/paper fill quality,
exchange rejects/partials, latency, and operational safety controls.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPECTED_STRATEGY_FAMILY = "market_state_rotation_v6"

TS_ALIASES = ("timestamp", "ts", "created_at", "signal_ts", "executed_at", "submitted_at")
DECISION_ID_ALIASES = ("decision_id", "lineage_id", "intent_id", "client_order_id")
ACTION_ALIASES = ("action", "actual_action", "order_action", "event_type", "kind")
SIDE_ALIASES = ("side", "actual_side", "direction", "position_side")
ORDER_SIDE_ALIASES = ("order_side", "execution_side", "order_direction")
STATUS_ALIASES = ("status", "order_status", "submit_status", "state")
EXPECTED_PRICE_ALIASES = ("expected_price", "signal_price", "intended_price", "limit_price", "mark_price")
ACTUAL_PRICE_ALIASES = ("actual_price", "fill_price", "avg_price", "executed_price", "entry_avg_price")
SLIPPAGE_ALIASES = ("slippage_bps", "adverse_slippage_bps", "fee_slippage_bps")
SPREAD_ALIASES = ("spread_bps", "top_of_book_spread_bps")
LATENCY_ALIASES = ("latency_ms", "submit_latency_ms", "ack_latency_ms", "fill_latency_ms")
FILL_RATIO_ALIASES = ("fill_ratio", "partial_fill_ratio", "executed_ratio")
EXECUTED_QTY_ALIASES = ("executed_qty", "filled_qty", "fill_qty", "qty")
ORIG_QTY_ALIASES = ("orig_qty", "requested_qty", "order_qty", "target_qty")
FEE_ALIASES = ("fee_bps", "commission_bps", "fee_rate_bps")

REJECTED_STATUSES = {
    "reject",
    "rejected",
    "error",
    "failed",
    "fail",
    "expired",
    "canceled",
    "cancelled",
}
FILLED_STATUSES = {"filled", "closed", "done", "complete", "completed", "partially_filled", "partial"}

REQUIRED_SAFETY_CONTROLS = (
    "kill_switch_verified",
    "max_daily_loss_verified",
    "position_sync_verified",
    "partial_fill_handling_verified",
    "exchange_reject_handling_verified",
    "reduce_only_exit_verified",
    "leverage_cap_verified",
    "idempotent_client_order_id_verified",
    "stale_signal_block_verified",
    "maintenance_window_block_verified",
)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _pct(value: float) -> float:
    return round(float(value), 4)


def _first(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for key in aliases:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_action(value: Any) -> str:
    text = _normalize_text(value)
    if text in {"open", "entry", "enter", "add", "increase", "scale_in"}:
        return "add"
    if text in {"reduce", "trim", "partial", "close", "exit", "remove", "stop", "take_profit"}:
        return "remove"
    if text in {"flip", "reverse"}:
        return "flip"
    return text


def _normalize_side(value: Any) -> str:
    text = _normalize_text(value)
    if text in {"1", "+1", "long", "buy", "bid"}:
        return "long"
    if text in {"-1", "short", "sell", "ask"}:
        return "short"
    if text in {"0", "flat", "none", "neutral"}:
        return "flat"
    return text


def _normalize_order_side(value: Any) -> str:
    text = _normalize_text(value)
    if text in {"buy", "bid", "long"}:
        return "buy"
    if text in {"sell", "ask", "short"}:
        return "sell"
    return ""


def _infer_order_side(row: dict[str, Any]) -> str:
    explicit = _normalize_order_side(_first(row, ORDER_SIDE_ALIASES))
    if explicit:
        return explicit
    action = _normalize_action(_first(row, ACTION_ALIASES))
    side = _normalize_side(_first(row, SIDE_ALIASES))
    if action in {"add", "open", "entry"}:
        return "buy" if side == "long" else ("sell" if side == "short" else "")
    if action in {"remove", "close", "exit"}:
        return "sell" if side == "long" else ("buy" if side == "short" else "")
    if side == "long":
        return "buy"
    if side == "short":
        return "sell"
    return ""


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


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in {".jsonl", ".ndjson"}:
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
        return rows
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    payload = _load_json(path)
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "fills", "orders", "events", "journal", "submissions"):
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(row) for row in value if isinstance(row, dict)]
    return []


def _compute_spread_bps(row: dict[str, Any]) -> float | None:
    provided = _first(row, SPREAD_ALIASES)
    if provided is not None:
        return abs(_float(provided))
    bid = _first(row, ("best_bid", "bid", "top_bid"))
    ask = _first(row, ("best_ask", "ask", "top_ask"))
    if bid is None or ask is None:
        return None
    bid_value = _float(bid)
    ask_value = _float(ask)
    mid = (bid_value + ask_value) / 2.0
    if mid <= 0.0 or ask_value < bid_value:
        return None
    return abs((ask_value - bid_value) / mid * 10_000.0)


def _compute_adverse_slippage_bps(row: dict[str, Any]) -> float | None:
    provided = _first(row, SLIPPAGE_ALIASES)
    if provided is not None:
        return _float(provided)
    expected = _first(row, EXPECTED_PRICE_ALIASES)
    actual = _first(row, ACTUAL_PRICE_ALIASES)
    order_side = _infer_order_side(row)
    if expected is None or actual is None or order_side not in {"buy", "sell"}:
        return None
    expected_price = _float(expected)
    actual_price = _float(actual)
    if expected_price <= 0.0:
        return None
    if order_side == "buy":
        return (actual_price - expected_price) / expected_price * 10_000.0
    return (expected_price - actual_price) / expected_price * 10_000.0


def _fill_ratio(row: dict[str, Any], status: str) -> float | None:
    provided = _first(row, FILL_RATIO_ALIASES)
    if provided is not None:
        return max(0.0, min(_float(provided), 1.0))
    executed = _first(row, EXECUTED_QTY_ALIASES)
    original = _first(row, ORIG_QTY_ALIASES)
    if executed is not None and original is not None and _float(original) > 0.0:
        return max(0.0, min(_float(executed) / _float(original), 1.0))
    if status in {"filled", "closed", "done", "complete", "completed"}:
        return 1.0
    if status in {"partially_filled", "partial"}:
        return 0.5
    return None


def _gate(name: str, passed: bool, *, value: Any, threshold: Any, severity: str = "blocker") -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "value": value,
        "threshold": threshold,
        "severity": severity,
    }


def _shadow_fill_metrics(
    rows: list[dict[str, Any]],
    *,
    expected_symbol: str = "BTCUSDT",
    expected_strategy_family: str = EXPECTED_STRATEGY_FAMILY,
) -> dict[str, Any]:
    schema_issue_counts = {
        "missing_timestamp": 0,
        "missing_symbol": 0,
        "missing_strategy_family": 0,
        "missing_decision_id": 0,
        "missing_action": 0,
        "missing_side": 0,
        "missing_status": 0,
        "missing_price_or_slippage_for_non_rejected": 0,
        "missing_latency_ms": 0,
        "missing_spread_bps": 0,
    }
    slippage_values: list[float] = []
    adverse_values: list[float] = []
    spread_values: list[float] = []
    latency_values: list[float] = []
    fee_values: list[float] = []
    status_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    symbol_mismatches = 0
    family_mismatches = 0
    rejected = 0
    partial = 0
    non_rejected = 0
    sample_rows: list[dict[str, Any]] = []

    for idx, row in enumerate(rows):
        if _first(row, TS_ALIASES) is None:
            schema_issue_counts["missing_timestamp"] += 1
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            schema_issue_counts["missing_symbol"] += 1
        elif expected_symbol and symbol != expected_symbol.upper():
            symbol_mismatches += 1
        family = str(row.get("strategy_family") or row.get("family") or "")
        if not family:
            schema_issue_counts["missing_strategy_family"] += 1
        elif expected_strategy_family and family != expected_strategy_family:
            family_mismatches += 1
        if _first(row, DECISION_ID_ALIASES) is None:
            schema_issue_counts["missing_decision_id"] += 1

        action = _normalize_action(_first(row, ACTION_ALIASES))
        if not action:
            schema_issue_counts["missing_action"] += 1
        else:
            action_counts[action] = action_counts.get(action, 0) + 1
        if not _normalize_side(_first(row, SIDE_ALIASES)) and not _infer_order_side(row):
            schema_issue_counts["missing_side"] += 1

        status = _normalize_text(_first(row, STATUS_ALIASES))
        if not status:
            schema_issue_counts["missing_status"] += 1
            status = "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        is_rejected = status in REJECTED_STATUSES
        if is_rejected:
            rejected += 1
        else:
            non_rejected += 1
            ratio = _fill_ratio(row, status)
            if ratio is not None and ratio < 0.999:
                partial += 1

        slippage = _compute_adverse_slippage_bps(row)
        if slippage is None:
            if not is_rejected:
                schema_issue_counts["missing_price_or_slippage_for_non_rejected"] += 1
        else:
            slippage_values.append(_pct(slippage))
            adverse_values.append(max(_pct(slippage), 0.0))

        spread = _compute_spread_bps(row)
        if spread is None:
            schema_issue_counts["missing_spread_bps"] += 1
        else:
            spread_values.append(_pct(spread))

        latency = _first(row, LATENCY_ALIASES)
        if latency is None:
            schema_issue_counts["missing_latency_ms"] += 1
        else:
            latency_values.append(max(_float(latency), 0.0))

        fee = _first(row, FEE_ALIASES)
        if fee is not None:
            fee_values.append(abs(_float(fee)))

        if len(sample_rows) < 5:
            sample_rows.append(
                {
                    "row": idx,
                    "timestamp": _first(row, TS_ALIASES),
                    "symbol": symbol or None,
                    "action": action or None,
                    "side": _normalize_side(_first(row, SIDE_ALIASES)) or None,
                    "order_side": _infer_order_side(row) or None,
                    "status": status,
                    "adverse_slippage_bps": _pct(slippage) if slippage is not None else None,
                    "spread_bps": _pct(spread) if spread is not None else None,
                    "latency_ms": _pct(_float(latency)) if latency is not None else None,
                }
            )

    total = len(rows)
    schema_issue_total = sum(schema_issue_counts.values())
    return {
        "row_count": total,
        "fill_metric_sample_count": len(slippage_values),
        "non_rejected_count": non_rejected,
        "rejected_count": rejected,
        "partial_fill_count": partial,
        "reject_rate": _pct(rejected / total) if total else 0.0,
        "partial_fill_rate": _pct(partial / max(non_rejected, 1)) if non_rejected else 0.0,
        "symbol_mismatch_count": symbol_mismatches,
        "strategy_family_mismatch_count": family_mismatches,
        "status_counts": dict(sorted(status_counts.items())),
        "action_counts": dict(sorted(action_counts.items())),
        "schema_issue_counts": schema_issue_counts,
        "schema_issue_total": schema_issue_total,
        "slippage_bps": {
            "avg": _pct(mean(slippage_values)) if slippage_values else None,
            "p95": _percentile(slippage_values, 0.95),
            "max": _pct(max(slippage_values)) if slippage_values else None,
            "p95_adverse": _percentile(adverse_values, 0.95),
            "max_adverse": _pct(max(adverse_values)) if adverse_values else None,
        },
        "spread_bps": {
            "avg": _pct(mean(spread_values)) if spread_values else None,
            "p95": _percentile(spread_values, 0.95),
            "max": _pct(max(spread_values)) if spread_values else None,
        },
        "latency_ms": {
            "avg": _pct(mean(latency_values)) if latency_values else None,
            "p95": _percentile(latency_values, 0.95),
            "max": _pct(max(latency_values)) if latency_values else None,
        },
        "fee_bps": {
            "avg": _pct(mean(fee_values)) if fee_values else None,
            "max": _pct(max(fee_values)) if fee_values else None,
        },
        "sample_rows": sample_rows,
    }


def _source_readiness_summary(stress_report: dict[str, Any]) -> dict[str, Any]:
    checklist = dict(stress_report.get("execution_readiness_checklist") or {})
    items = [dict(item) for item in list(checklist.get("items") or []) if isinstance(item, dict)]
    item_statuses = {str(item.get("name")): str(item.get("status") or "").lower() for item in items}
    hard_blockers: list[str] = []
    warnings: list[str] = []

    replay_status = item_statuses.get("replay_stress_floor")
    if replay_status and replay_status != "pass":
        hard_blockers.append("source_replay_stress_floor_not_passed")
    proxy_status = item_statuses.get("proxy_replay_gap_review")
    if proxy_status in {"watch", "warn", "warning"}:
        warnings.append("source_proxy_replay_gap_watch")
    weak_status = item_statuses.get("weak_fold_watchpoints")
    if weak_status in {"watch", "warn", "warning"}:
        warnings.append("source_weak_fold_watchpoints_watch")

    replay_worst = dict(
        stress_report.get("replay_adjusted_worst_stress_summary")
        or stress_report.get("replay_adjusted_summary")
        or stress_report.get("worst_stress_summary")
        or {}
    )
    replay_verdict = str(
        replay_worst.get("deployment_readiness_verdict")
        or replay_worst.get("verdict")
        or ""
    ).lower()
    if replay_verdict and replay_verdict not in {"pass", "watch"}:
        hard_blockers.append("source_replay_adjusted_worst_stress_not_passed")

    if not checklist and not replay_worst:
        hard_blockers.append("source_stress_readiness_evidence_missing")

    source_status = str(checklist.get("overall_status") or stress_report.get("overall_status") or "").lower()
    return {
        "overall_status": source_status or None,
        "passed_for_shadow_collection": not hard_blockers,
        "replay_verdict": replay_verdict or None,
        "hard_blockers": sorted(set(hard_blockers)),
        "warnings": sorted(set(warnings)),
        "items": items,
    }


def _readiness_value(value: Any) -> bool:
    if isinstance(value, dict):
        status = _normalize_text(value.get("status") or value.get("state") or value.get("result"))
        if status in {"pass", "passed", "verified", "ready", "ok", "true"}:
            return True
        if value.get("verified") is not None:
            return bool(value.get("verified"))
        if value.get("passed") is not None:
            return bool(value.get("passed"))
        return False
    if isinstance(value, str):
        return _normalize_text(value) in {"1", "true", "yes", "y", "pass", "passed", "verified", "ready", "ok"}
    return bool(value)


def _safety_control_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {
            "available": False,
            "passed": False,
            "verified_count": 0,
            "required_count": len(REQUIRED_SAFETY_CONTROLS),
            "missing_or_failed": list(REQUIRED_SAFETY_CONTROLS),
            "controls": [
                {"name": name, "verified": False, "evidence": None}
                for name in REQUIRED_SAFETY_CONTROLS
            ],
        }
    controls_payload = dict(payload.get("controls") or payload)
    controls: list[dict[str, Any]] = []
    missing_or_failed: list[str] = []
    for name in REQUIRED_SAFETY_CONTROLS:
        raw = controls_payload.get(name)
        verified = _readiness_value(raw)
        if not verified:
            missing_or_failed.append(name)
        controls.append(
            {
                "name": name,
                "verified": verified,
                "evidence": raw if isinstance(raw, dict) else raw,
            }
        )
    return {
        "available": True,
        "passed": not missing_or_failed,
        "verified_count": len(REQUIRED_SAFETY_CONTROLS) - len(missing_or_failed),
        "required_count": len(REQUIRED_SAFETY_CONTROLS),
        "missing_or_failed": missing_or_failed,
        "controls": controls,
    }


def _shadow_fill_gates(
    metrics: dict[str, Any],
    *,
    min_shadow_fill_samples: int,
    max_p95_adverse_slippage_bps: float,
    max_max_adverse_slippage_bps: float,
    max_p95_spread_bps: float,
    max_p95_latency_ms: float,
    max_reject_rate: float,
    max_partial_fill_rate: float,
) -> list[dict[str, Any]]:
    slippage = dict(metrics.get("slippage_bps") or {})
    spread = dict(metrics.get("spread_bps") or {})
    latency = dict(metrics.get("latency_ms") or {})
    sample_count = int(metrics.get("fill_metric_sample_count") or 0)
    schema_issue_total = int(metrics.get("schema_issue_total") or 0)
    symbol_mismatches = int(metrics.get("symbol_mismatch_count") or 0)
    family_mismatches = int(metrics.get("strategy_family_mismatch_count") or 0)
    p95_adverse = slippage.get("p95_adverse")
    max_adverse = slippage.get("max_adverse")
    p95_spread = spread.get("p95")
    p95_latency = latency.get("p95")
    reject_rate = _float(metrics.get("reject_rate"))
    partial_rate = _float(metrics.get("partial_fill_rate"))
    sample_ready = sample_count >= min_shadow_fill_samples

    def metric_gate(name: str, value: Any, threshold: str, passed: bool) -> dict[str, Any]:
        if not sample_ready:
            return _gate(
                name,
                False,
                value="not_evaluated_until_min_shadow_fill_samples",
                threshold=threshold,
                severity="pending",
            )
        return _gate(name, passed, value=value, threshold=threshold)

    return [
        _gate(
            "min_shadow_fill_samples",
            sample_count >= min_shadow_fill_samples,
            value=sample_count,
            threshold=f">={min_shadow_fill_samples}",
        ),
        _gate(
            "shadow_fill_schema_clean",
            schema_issue_total == 0,
            value=schema_issue_total,
            threshold="0",
        ),
        _gate(
            "shadow_fill_symbol_family_match",
            symbol_mismatches == 0 and family_mismatches == 0,
            value={"symbol_mismatches": symbol_mismatches, "family_mismatches": family_mismatches},
            threshold="0",
        ),
        _gate(
            "reject_rate_within_limit",
            reject_rate <= max_reject_rate,
            value=reject_rate,
            threshold=f"<={max_reject_rate}",
        ),
        _gate(
            "partial_fill_rate_within_limit",
            partial_rate <= max_partial_fill_rate,
            value=partial_rate,
            threshold=f"<={max_partial_fill_rate}",
        ),
        metric_gate(
            "p95_adverse_slippage_within_limit",
            value=p95_adverse,
            threshold=f"<={max_p95_adverse_slippage_bps}",
            passed=p95_adverse is not None and _float(p95_adverse) <= max_p95_adverse_slippage_bps,
        ),
        metric_gate(
            "max_adverse_slippage_within_limit",
            value=max_adverse,
            threshold=f"<={max_max_adverse_slippage_bps}",
            passed=max_adverse is not None and _float(max_adverse) <= max_max_adverse_slippage_bps,
        ),
        metric_gate(
            "p95_spread_within_limit",
            value=p95_spread,
            threshold=f"<={max_p95_spread_bps}",
            passed=p95_spread is not None and _float(p95_spread) <= max_p95_spread_bps,
        ),
        metric_gate(
            "p95_latency_within_limit",
            value=p95_latency,
            threshold=f"<={max_p95_latency_ms}",
            passed=p95_latency is not None and _float(p95_latency) <= max_p95_latency_ms,
        ),
    ]


def _required_next_actions(
    *,
    source: dict[str, Any],
    shadow_gates: list[dict[str, Any]],
    safety: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    if source.get("hard_blockers"):
        actions.append("repair_source_replay_or_stress_report_before_collecting_live_like_execution_evidence")
    failed_shadow = [gate["name"] for gate in shadow_gates if not gate.get("passed")]
    shadow_sample_ready = all(
        gate.get("passed")
        for gate in shadow_gates
        if gate.get("name") == "min_shadow_fill_samples"
    )
    if "min_shadow_fill_samples" in failed_shadow:
        actions.append("collect_market_state_rotation_v6_shadow_or_paper_fills_until_min_sample_count_is_met")
    if "shadow_fill_schema_clean" in failed_shadow:
        actions.append("fix_shadow_fill_logger_schema_so_each_row_has_lineage_price_latency_spread_and_status")
    if shadow_sample_ready and any(name.endswith("_within_limit") for name in failed_shadow):
        actions.append("reduce_execution_aggression_or_add_submission_filters_until_slippage_spread_latency_rejects_pass")
    if "shadow_fill_symbol_family_match" in failed_shadow:
        actions.append("separate_market_state_rotation_v6_btcusdt_rows_from_other_symbols_or_strategy_families")
    if not safety.get("passed"):
        actions.append("verify_order_safety_controls_before_any_live_canary_authority")
    if not actions:
        actions.append("run_tiny_live_canary_only_with_daily_review_and_keep_full_live_disabled")
    return actions


def build_execution_shadow_audit_report(
    stress_report: dict[str, Any],
    shadow_fills: list[dict[str, Any]] | None = None,
    *,
    safety_controls: dict[str, Any] | None = None,
    input_stress_report: str | None = None,
    input_shadow_fills: str | None = None,
    input_safety_controls: str | None = None,
    expected_symbol: str = "BTCUSDT",
    expected_strategy_family: str = EXPECTED_STRATEGY_FAMILY,
    min_shadow_fill_samples: int = 100,
    max_p95_adverse_slippage_bps: float = 8.0,
    max_max_adverse_slippage_bps: float = 25.0,
    max_p95_spread_bps: float = 4.0,
    max_p95_latency_ms: float = 1500.0,
    max_reject_rate: float = 0.02,
    max_partial_fill_rate: float = 0.05,
) -> dict[str, Any]:
    rows = list(shadow_fills or [])
    source = _source_readiness_summary(stress_report)
    metrics = _shadow_fill_metrics(
        rows,
        expected_symbol=expected_symbol,
        expected_strategy_family=expected_strategy_family,
    )
    shadow_gates = _shadow_fill_gates(
        metrics,
        min_shadow_fill_samples=min_shadow_fill_samples,
        max_p95_adverse_slippage_bps=max_p95_adverse_slippage_bps,
        max_max_adverse_slippage_bps=max_max_adverse_slippage_bps,
        max_p95_spread_bps=max_p95_spread_bps,
        max_p95_latency_ms=max_p95_latency_ms,
        max_reject_rate=max_reject_rate,
        max_partial_fill_rate=max_partial_fill_rate,
    )
    safety = _safety_control_summary(safety_controls)
    source_gate = _gate(
        "source_replay_ready_for_shadow_collection",
        bool(source.get("passed_for_shadow_collection")),
        value=source.get("hard_blockers"),
        threshold="no_hard_blockers",
    )
    safety_gate = _gate(
        "order_safety_controls_verified",
        bool(safety.get("passed")),
        value=f"{safety.get('verified_count')}/{safety.get('required_count')}",
        threshold=f"{safety.get('required_count')}/{safety.get('required_count')}",
    )
    gates = {
        "source": [source_gate],
        "shadow_fills": shadow_gates,
        "safety_controls": [safety_gate],
    }

    source_ready = bool(source_gate["passed"])
    shadow_sample_ready = bool(shadow_gates[0]["passed"])
    shadow_passed = all(
        bool(gate.get("passed"))
        for gate in shadow_gates
        if gate.get("severity") != "pending"
    )
    safety_passed = bool(safety_gate["passed"])
    if not source_ready:
        overall_status = "not_ready"
    elif not shadow_sample_ready:
        overall_status = "shadow_data_required"
    elif not shadow_passed:
        overall_status = "not_ready"
    elif not safety_passed:
        overall_status = "paper_ready"
    else:
        overall_status = "tiny_live_canary_ready"

    failed_gates = [
        gate["name"]
        for group in gates.values()
        for gate in group
        if not gate.get("passed") and gate.get("severity") != "pending"
    ]
    pending_gates = [
        gate["name"]
        for group in gates.values()
        for gate in group
        if not gate.get("passed") and gate.get("severity") == "pending"
    ]
    ready_for_tiny_live = overall_status == "tiny_live_canary_ready"
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "overall_status": overall_status,
        "input_stress_report": input_stress_report,
        "input_shadow_fills": input_shadow_fills,
        "input_safety_controls": input_safety_controls,
        "expected_symbol": expected_symbol.upper(),
        "expected_strategy_family": expected_strategy_family,
        "source_execution_readiness": source,
        "shadow_fill_metrics": metrics,
        "safety_controls": safety,
        "gates": gates,
        "summary": {
            "ready_for_shadow_collection": source_ready,
            "ready_for_paper": source_ready,
            "ready_for_tiny_live_canary": ready_for_tiny_live,
            "ready_for_full_live": False,
            "max_authorized_stage": (
                "tiny_live_canary" if ready_for_tiny_live else ("paper" if source_ready else "none")
            ),
            "live_order_submission_allowed": ready_for_tiny_live,
            "full_live_order_submission_allowed": False,
            "failed_gates": failed_gates,
            "pending_gates": pending_gates,
        },
        "execution_limits": {
            "tiny_live_canary_size_multiplier": 0.10 if ready_for_tiny_live else 0.0,
            "full_live_size_multiplier": 0.0,
            "review_cadence": "daily",
            "promotion_rule": "full_live_requires_separate_live_parity_and_drawdown_review_after_canary",
        },
        "required_shadow_fill_schema": {
            "timestamp": list(TS_ALIASES),
            "symbol": ["symbol"],
            "strategy_family": ["strategy_family", "family"],
            "decision_lineage_id": list(DECISION_ID_ALIASES),
            "action": list(ACTION_ALIASES),
            "side": list(SIDE_ALIASES),
            "status": list(STATUS_ALIASES),
            "expected_price": list(EXPECTED_PRICE_ALIASES),
            "actual_price": list(ACTUAL_PRICE_ALIASES),
            "slippage_bps": list(SLIPPAGE_ALIASES),
            "spread_bps": list(SPREAD_ALIASES) + ["best_bid", "best_ask"],
            "latency_ms": list(LATENCY_ALIASES),
            "fill_ratio": list(FILL_RATIO_ALIASES) + list(EXECUTED_QTY_ALIASES) + list(ORIG_QTY_ALIASES),
        },
        "required_safety_controls": list(REQUIRED_SAFETY_CONTROLS),
        "required_next_actions": _required_next_actions(
            source=source,
            shadow_gates=shadow_gates,
            safety=safety,
        ),
    }


def _markdown(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary") or {})
    metrics = dict(report.get("shadow_fill_metrics") or {})
    slippage = dict(metrics.get("slippage_bps") or {})
    spread = dict(metrics.get("spread_bps") or {})
    latency = dict(metrics.get("latency_ms") or {})
    safety = dict(report.get("safety_controls") or {})
    lines = [
        "# Market State Rotation V6 Execution Shadow Audit",
        "",
        f"- Status: `{report.get('overall_status')}`",
        f"- Ready for paper: `{summary.get('ready_for_paper')}`",
        f"- Ready for tiny live canary: `{summary.get('ready_for_tiny_live_canary')}`",
        f"- Ready for full live: `{summary.get('ready_for_full_live')}`",
        f"- Live order submission allowed: `{summary.get('live_order_submission_allowed')}`",
        f"- Failed gates: `{', '.join(summary.get('failed_gates') or [])}`",
        f"- Pending gates: `{', '.join(summary.get('pending_gates') or [])}`",
        "",
        "## Shadow Fill Metrics",
        "",
        f"- Rows: `{metrics.get('row_count')}`",
        f"- Fill metric samples: `{metrics.get('fill_metric_sample_count')}`",
        f"- Reject rate: `{metrics.get('reject_rate')}`",
        f"- Partial fill rate: `{metrics.get('partial_fill_rate')}`",
        f"- P95 adverse slippage bps: `{slippage.get('p95_adverse')}`",
        f"- Max adverse slippage bps: `{slippage.get('max_adverse')}`",
        f"- P95 spread bps: `{spread.get('p95')}`",
        f"- P95 latency ms: `{latency.get('p95')}`",
        f"- Schema issues: `{json.dumps(metrics.get('schema_issue_counts'), ensure_ascii=False)}`",
        "",
        "## Safety Controls",
        "",
        f"- Available: `{safety.get('available')}`",
        f"- Passed: `{safety.get('passed')}`",
        f"- Verified: `{safety.get('verified_count')}/{safety.get('required_count')}`",
        f"- Missing or failed: `{', '.join(safety.get('missing_or_failed') or [])}`",
        "",
        "## Gates",
        "",
    ]
    for group_name, group in dict(report.get("gates") or {}).items():
        lines.append(f"### {group_name}")
        for gate in list(group or []):
            lines.append(
                f"- {gate.get('name')}: `{'pass' if gate.get('passed') else 'fail'}` "
                f"value=`{gate.get('value')}` threshold=`{gate.get('threshold')}`"
            )
        lines.append("")
    lines.extend(["## Required Next Actions", ""])
    for action in list(report.get("required_next_actions") or []):
        lines.append(f"- {action}")
    lines.extend(["", "## Sample Rows", ""])
    sample_rows = list(metrics.get("sample_rows") or [])
    if not sample_rows:
        lines.append("- none")
    for row in sample_rows:
        lines.append(f"- `{json.dumps(row, ensure_ascii=False)}`")
    return "\n".join(lines) + "\n"


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit market-state rotation v6 shadow/paper fill quality and live canary gates."
    )
    parser.add_argument("--stress-report", required=True)
    parser.add_argument("--shadow-fills", default="")
    parser.add_argument("--safety-controls", default="")
    parser.add_argument("--report-dir", default="reports/validation/diagnostics/market_state_rotation_v6_execution_shadow_audit")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--expected-symbol", default="BTCUSDT")
    parser.add_argument("--min-shadow-fill-samples", type=int, default=100)
    parser.add_argument("--max-p95-adverse-slippage-bps", type=float, default=8.0)
    parser.add_argument("--max-max-adverse-slippage-bps", type=float, default=25.0)
    parser.add_argument("--max-p95-spread-bps", type=float, default=4.0)
    parser.add_argument("--max-p95-latency-ms", type=float, default=1500.0)
    parser.add_argument("--max-reject-rate", type=float, default=0.02)
    parser.add_argument("--max-partial-fill-rate", type=float, default=0.05)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stress_path = Path(args.stress_report)
    if not stress_path.is_absolute():
        stress_path = ROOT_DIR / stress_path
    fills_path = Path(args.shadow_fills) if args.shadow_fills else None
    if fills_path is not None and not fills_path.is_absolute():
        fills_path = ROOT_DIR / fills_path
    safety_path = Path(args.safety_controls) if args.safety_controls else None
    if safety_path is not None and not safety_path.is_absolute():
        safety_path = ROOT_DIR / safety_path

    stress_report = _load_json(stress_path)
    shadow_fills = _load_rows(fills_path) if fills_path is not None else None
    safety_controls = _load_json(safety_path) if safety_path is not None else None
    report = build_execution_shadow_audit_report(
        stress_report,
        shadow_fills,
        safety_controls=safety_controls,
        input_stress_report=_display_path(stress_path),
        input_shadow_fills=_display_path(fills_path) if fills_path is not None else None,
        input_safety_controls=_display_path(safety_path) if safety_path is not None else None,
        expected_symbol=args.expected_symbol,
        min_shadow_fill_samples=max(1, int(args.min_shadow_fill_samples)),
        max_p95_adverse_slippage_bps=float(args.max_p95_adverse_slippage_bps),
        max_max_adverse_slippage_bps=float(args.max_max_adverse_slippage_bps),
        max_p95_spread_bps=float(args.max_p95_spread_bps),
        max_p95_latency_ms=float(args.max_p95_latency_ms),
        max_reject_rate=float(args.max_reject_rate),
        max_partial_fill_rate=float(args.max_partial_fill_rate),
    )
    if args.write_report:
        report_dir = Path(args.report_dir)
        if not report_dir.is_absolute():
            report_dir = ROOT_DIR / report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_execution_shadow_audit.json"
        md_path = report_dir / "market_state_rotation_v6_execution_shadow_audit.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
