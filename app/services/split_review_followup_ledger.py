from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER_PATH = ROOT_DIR / "reports/operations/split_review_followups/review_ledger.jsonl"
FRESH_PACKET_WINDOW_HOURS = 12


def _dict(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict(payload or {})


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _age_minutes(reference: datetime, value: Any) -> int | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    delta = reference - parsed
    return max(int(delta.total_seconds() // 60), 0)


def _target_contract(entry: dict[str, Any] | None) -> dict[str, Any]:
    target = _dict(_dict(entry).get("target_contract"))
    return {
        "action": str(target.get("action") or "none"),
        "axis": str(target.get("axis") or "none"),
        "preferred_variant": str(target.get("preferred_variant") or "none"),
        "symbol": str(target.get("symbol") or "").upper(),
        "status": str(target.get("status") or ""),
        "strategy_family": str(target.get("strategy_family") or ""),
        "block_reason": str(target.get("block_reason") or ""),
        "focus_source": str(target.get("focus_source") or ""),
    }


def _packet_key(entry: dict[str, Any] | None) -> str:
    source = _dict(entry)
    target = _target_contract(source)
    action = str(source.get("selected_action") or target.get("action") or "none")
    return "|".join(
        [
            action or "none",
            str(target.get("axis") or "none"),
            str(target.get("preferred_variant") or "none"),
            str(target.get("symbol") or "none"),
            str(target.get("strategy_family") or "none"),
        ]
    )


def _packet_digest(entry: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    source = _dict(entry)
    edge_experiment = _dict(source.get("edge_experiment_review"))
    edge_evolution = _dict(source.get("edge_evolution_rule"))
    generated_at = str(source.get("generated_at") or "")
    recorded_at = str(source.get("recorded_at") or "")
    return {
        "packet_key": _packet_key(source),
        "action": str(source.get("selected_action") or "none"),
        "status": str(source.get("status") or "UNKNOWN"),
        "selection_reason": str(source.get("selection_reason") or ""),
        "generated_at": generated_at,
        "recorded_at": recorded_at,
        "age_minutes": _age_minutes(now, generated_at or recorded_at),
        "followup_command": str(source.get("followup_command") or ""),
        "target_contract": _target_contract(source),
        "edge_experiment_review": {
            "edge_state": str(edge_experiment.get("edge_state") or "insufficient_edge_measurement"),
            "closed_trade_count": _int(edge_experiment.get("closed_trade_count", 0)),
            "true_edge_ratio": round(_float(edge_experiment.get("true_edge_ratio")), 4),
            "recent_true_edge_ratio": round(_float(edge_experiment.get("recent_true_edge_ratio")), 4),
            "prior_true_edge_ratio": round(_float(edge_experiment.get("prior_true_edge_ratio")), 4),
            "edge_decay_rate": round(_float(edge_experiment.get("edge_decay_rate")), 4),
            "entry_timing_preferred_variant": str(edge_experiment.get("entry_timing_preferred_variant") or "none"),
            "execution_style_preferred_variant": str(
                edge_experiment.get("execution_style_preferred_variant") or "none"
            ),
        },
        "edge_evolution_rule": {
            "evolution_state": str(edge_evolution.get("evolution_state") or "insufficient_sample"),
            "recommended_action": str(edge_evolution.get("recommended_action") or "keep_current_baseline"),
            "allocation_bias": str(edge_evolution.get("allocation_bias") or "hold_current_baseline"),
            "confidence": str(edge_evolution.get("confidence") or "low"),
            "recommendation_strength": str(edge_evolution.get("recommendation_strength") or "baseline"),
            "promotion_candidate_axis": str(edge_evolution.get("promotion_candidate_axis") or "none"),
            "promotion_candidate_variant": str(edge_evolution.get("promotion_candidate_variant") or "none"),
        },
        "report_path": str(source.get("report_path") or ""),
    }


def _leading_action_streak(packets: list[dict[str, Any]], *, action: str) -> int:
    if not action or action == "none":
        return 0
    streak = 0
    for packet in packets:
        if str(_dict(packet).get("action") or "none") != action:
            break
        streak += 1
    return streak


def _leading_status_streak(packets: list[dict[str, Any]], *, action: str, statuses: set[str]) -> int:
    if not action or action == "none":
        return 0
    streak = 0
    for packet in packets:
        item = _dict(packet)
        if str(item.get("action") or "none") != action:
            break
        if str(item.get("status") or "UNKNOWN") not in statuses:
            break
        streak += 1
    return streak


def _relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def split_review_followup_ledger_path(*, ledger_path: str | Path | None = None) -> Path:
    if ledger_path is None:
        return DEFAULT_LEDGER_PATH
    return Path(ledger_path)


def _followup_command(*, action: str, symbol: str, universe: str, days: int) -> str:
    if not action or action == "none" or not symbol:
        return ""
    return (
        f"./.venv/bin/python scripts/run_split_review_followup.py "
        f"--symbol {symbol.upper()} --universe {universe} --days {max(int(days), 1)} --action {action}"
    )


def _normalize_entry_payload(payload: dict[str, Any]) -> dict[str, Any]:
    source = dict(payload or {})
    target = _dict(source.get("target_contract"))
    priority = _dict(source.get("operator_action_priority"))
    edge_experiment = _dict(source.get("edge_experiment_review"))
    edge_evolution = _dict(source.get("edge_evolution_rule"))
    symbol = str(source.get("symbol") or target.get("symbol") or "").upper()
    universe = str(source.get("universe") or "")
    selected_action = str(source.get("selected_action") or "none")
    days = max(_int(source.get("days"), 7), 1)
    report_path = str(source.get("report_path") or "")
    return {
        "recorded_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "generated_at": str(source.get("generated_at") or ""),
        "symbol": symbol,
        "universe": universe,
        "days": days,
        "status": str(source.get("status") or "UNKNOWN"),
        "selected_action": selected_action,
        "selection_reason": str(source.get("selection_reason") or ""),
        "followup_command": _followup_command(
            action=selected_action,
            symbol=str(target.get("symbol") or symbol or ""),
            universe=universe,
            days=days,
        ),
        "operator_action_priority": {
            "top_action": str(priority.get("top_action") or "continue_runtime_monitoring"),
            "top_reason": str(priority.get("top_reason") or ""),
            "priority_level": str(priority.get("priority_level") or "monitor"),
            "priority_source": str(priority.get("priority_source") or "monitor"),
        },
        "edge_experiment_review": {
            "edge_state": str(edge_experiment.get("edge_state") or "insufficient_edge_measurement"),
            "closed_trade_count": _int(edge_experiment.get("closed_trade_count", 0)),
            "true_edge_ratio": round(_float(edge_experiment.get("true_edge_ratio")), 4),
            "recent_true_edge_ratio": round(_float(edge_experiment.get("recent_true_edge_ratio")), 4),
            "prior_true_edge_ratio": round(_float(edge_experiment.get("prior_true_edge_ratio")), 4),
            "edge_decay_rate": round(_float(edge_experiment.get("edge_decay_rate")), 4),
            "entry_timing_preferred_variant": str(edge_experiment.get("entry_timing_preferred_variant") or "none"),
            "execution_style_preferred_variant": str(edge_experiment.get("execution_style_preferred_variant") or "none"),
        },
        "edge_evolution_rule": {
            "evolution_state": str(edge_evolution.get("evolution_state") or "insufficient_sample"),
            "recommended_action": str(edge_evolution.get("recommended_action") or "keep_current_baseline"),
            "allocation_bias": str(edge_evolution.get("allocation_bias") or "hold_current_baseline"),
            "confidence": str(edge_evolution.get("confidence") or "low"),
            "recommendation_strength": str(edge_evolution.get("recommendation_strength") or "baseline"),
            "promotion_candidate_axis": str(edge_evolution.get("promotion_candidate_axis") or "none"),
            "promotion_candidate_variant": str(edge_evolution.get("promotion_candidate_variant") or "none"),
        },
        "target_contract": {
            "action": str(target.get("action") or selected_action or "none"),
            "axis": str(target.get("axis") or "none"),
            "preferred_variant": str(target.get("preferred_variant") or "none"),
            "symbol": str(target.get("symbol") or symbol or "").upper(),
            "status": str(target.get("status") or ""),
            "strategy_family": str(target.get("strategy_family") or ""),
            "block_reason": str(target.get("block_reason") or ""),
            "focus_source": str(target.get("focus_source") or ""),
        },
        "report_path": report_path,
    }


def record_split_review_followup_ledger_entry(
    payload: dict[str, Any] | None,
    *,
    ledger_path: str | Path | None = None,
) -> dict[str, Any]:
    entry = _normalize_entry_payload(_dict(payload))
    path = split_review_followup_ledger_path(ledger_path=ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n")
    return entry


def _read_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def summarize_split_review_followup_ledger(
    *,
    symbol: str,
    universe: str,
    limit: int = 10,
    ledger_path: str | Path | None = None,
) -> dict[str, Any]:
    normalized_symbol = str(symbol or "").upper()
    normalized_universe = str(universe or "")
    path = split_review_followup_ledger_path(ledger_path=ledger_path)
    entries = _read_entries(path)
    now = datetime.now(UTC)
    matching = [
        dict(entry)
        for entry in entries
        if str(entry.get("symbol") or "").upper() == normalized_symbol
        and str(entry.get("universe") or "") == normalized_universe
    ]
    recent = list(reversed(matching[-max(int(limit), 1) :]))
    recent_packets = [_packet_digest(entry, now=now) for entry in recent]
    last = _dict(recent[0] if recent else {})
    last_target = _dict(last.get("target_contract"))
    status_counts = Counter(str(_dict(row).get("status") or "UNKNOWN") for row in recent)
    action_counts = Counter(str(_dict(row).get("selected_action") or "none") for row in recent)
    last_action = str(last.get("selected_action") or "none")
    last_status = str(last.get("status") or "UNKNOWN")
    fresh_ready_packets = [
        packet
        for packet in recent_packets
        if str(_dict(packet).get("status") or "UNKNOWN") == "READY"
        and _int(_dict(packet).get("age_minutes"), FRESH_PACKET_WINDOW_HOURS * 60 + 1)
        <= FRESH_PACKET_WINDOW_HOURS * 60
    ]
    if recent:
        target_symbol = str(last_target.get("symbol") or normalized_symbol or "n/a")
        target_family = str(last_target.get("strategy_family") or "unknown_family")
        if last_status == "READY":
            summary = (
                f"Recent split review follow-up history is active; last `{last_action}` packet targeted "
                f"`{target_symbol}` / `{target_family}` and completed in `{last_status}`."
            )
        else:
            summary = (
                f"Recent split review follow-up history needs review; last `{last_action}` packet ended in "
                f"`{last_status}` for `{target_symbol}` / `{target_family}`."
            )
    else:
        summary = (
            f"No split review follow-up packets have been recorded yet for `{normalized_symbol}` in "
            f"`{normalized_universe}`."
        )

    reason_codes = []
    if recent:
        reason_codes = [
            f"last_status:{last.get('status') or 'UNKNOWN'}",
            f"last_action:{last.get('selected_action') or 'none'}",
            f"recent_entries:{len(recent)}",
        ]
    else:
        reason_codes = ["recent_entries:0", "ledger:not_recorded"]

    return {
        "available": bool(recent),
        "advisory_only": True,
        "symbol": normalized_symbol,
        "universe": normalized_universe,
        "ledger_path": _relative_path(path),
        "total_entry_count": len(matching),
        "recent_entry_count": len(recent),
        "summary": summary,
        "reason_codes": reason_codes,
        "last_generated_at": str(last.get("generated_at") or ""),
        "last_recorded_at": str(last.get("recorded_at") or ""),
        "last_status": str(last.get("status") or "none"),
        "last_action": str(last.get("selected_action") or "none"),
        "last_packet_key": _packet_key(last) if last else "none",
        "last_selection_reason": str(last.get("selection_reason") or ""),
        "last_followup_command": str(last.get("followup_command") or ""),
        "last_report_path": str(last.get("report_path") or ""),
        "last_target_contract": last_target,
        "last_priority_source": str(_dict(last.get("operator_action_priority")).get("priority_source") or "monitor"),
        "last_priority_level": str(_dict(last.get("operator_action_priority")).get("priority_level") or "monitor"),
        "last_edge_state": str(_dict(last.get("edge_experiment_review")).get("edge_state") or "insufficient_edge_measurement"),
        "last_closed_trade_count": _int(_dict(last.get("edge_experiment_review")).get("closed_trade_count", 0)),
        "last_true_edge_ratio": round(_float(_dict(last.get("edge_experiment_review")).get("true_edge_ratio")), 4),
        "last_recent_true_edge_ratio": round(
            _float(_dict(last.get("edge_experiment_review")).get("recent_true_edge_ratio")),
            4,
        ),
        "last_prior_true_edge_ratio": round(
            _float(_dict(last.get("edge_experiment_review")).get("prior_true_edge_ratio")),
            4,
        ),
        "last_edge_decay_rate": round(_float(_dict(last.get("edge_experiment_review")).get("edge_decay_rate")), 4),
        "last_entry_timing_preferred_variant": str(
            _dict(last.get("edge_experiment_review")).get("entry_timing_preferred_variant") or "none"
        ),
        "last_execution_style_preferred_variant": str(
            _dict(last.get("edge_experiment_review")).get("execution_style_preferred_variant") or "none"
        ),
        "last_evolution_state": str(_dict(last.get("edge_evolution_rule")).get("evolution_state") or "insufficient_sample"),
        "last_recommended_action": str(
            _dict(last.get("edge_evolution_rule")).get("recommended_action") or "keep_current_baseline"
        ),
        "last_allocation_bias": str(
            _dict(last.get("edge_evolution_rule")).get("allocation_bias") or "hold_current_baseline"
        ),
        "last_confidence": str(_dict(last.get("edge_evolution_rule")).get("confidence") or "low"),
        "last_recommendation_strength": str(
            _dict(last.get("edge_evolution_rule")).get("recommendation_strength") or "baseline"
        ),
        "last_promotion_candidate_axis": str(
            _dict(last.get("edge_evolution_rule")).get("promotion_candidate_axis") or "none"
        ),
        "last_promotion_candidate_variant": str(
            _dict(last.get("edge_evolution_rule")).get("promotion_candidate_variant") or "none"
        ),
        "fresh_packet_window_hours": FRESH_PACKET_WINDOW_HOURS,
        "fresh_ready_packet_count": len(fresh_ready_packets),
        "latest_action_streak": _leading_action_streak(recent_packets, action=last_action),
        "latest_no_target_action_streak": _leading_status_streak(
            recent_packets,
            action=last_action,
            statuses={"NO_TARGET", "NO_REVIEW_ACTION_AVAILABLE"},
        ),
        "recent_status_counts": dict(status_counts),
        "recent_action_counts": [
            {"action": action, "count": count}
            for action, count in sorted(action_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "recent_packets": recent_packets,
    }
