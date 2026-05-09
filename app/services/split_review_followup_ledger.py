from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER_PATH = ROOT_DIR / "reports/operations/split_review_followups/review_ledger.jsonl"
FRESH_PACKET_WINDOW_HOURS = 12
GENERATION_PHASE = "generation"
DECISION_PHASE = "decision"


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


def _recorded_at() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


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


def _status_phase(entry: dict[str, Any] | None) -> str:
    source = _dict(entry)
    phase = str(source.get("status_phase") or source.get("event_type") or "").strip().lower()
    if phase in {DECISION_PHASE, "status_transition", "transition"}:
        return DECISION_PHASE
    return GENERATION_PHASE


def _packet_id(entry: dict[str, Any] | None) -> str:
    source = _dict(entry)
    explicit = str(source.get("packet_id") or "").strip()
    if explicit:
        return explicit

    target = _target_contract(source)
    symbol = str(source.get("symbol") or target.get("symbol") or "").upper()
    universe = str(source.get("universe") or "")
    generated_at = str(source.get("generated_at") or source.get("recorded_at") or "")
    action = str(source.get("selected_action") or target.get("action") or "none")
    axis = str(target.get("axis") or "none")
    target_symbol = str(target.get("symbol") or symbol or "none").upper()
    target_family = str(target.get("strategy_family") or "none")
    if symbol and universe and generated_at:
        return (
            f"review_followup:{symbol}:{universe}:{generated_at}:{action}:{axis}:{target_symbol}:{target_family}"
        )
    return f"review_followup:{uuid4().hex}"


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


def _packet_digest(
    entry: dict[str, Any] | None,
    *,
    now: datetime,
    latest_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = _dict(entry)
    edge_experiment = _dict(source.get("edge_experiment_review"))
    edge_evolution = _dict(source.get("edge_evolution_rule"))
    decision = _dict(latest_decision)
    generated_at = str(source.get("generated_at") or "")
    recorded_at = str(source.get("recorded_at") or "")
    generated_status = str(source.get("generated_status") or source.get("status") or "UNKNOWN")
    decision_status = str(decision.get("status") or "none")
    effective_status = decision_status if decision_status != "none" else generated_status
    return {
        "packet_id": _packet_id(source),
        "packet_key": _packet_key(source),
        "action": str(source.get("selected_action") or "none"),
        "status": generated_status,
        "generated_status": generated_status,
        "decision_status": decision_status,
        "effective_status": effective_status,
        "selection_reason": str(source.get("selection_reason") or ""),
        "generated_at": generated_at,
        "recorded_at": recorded_at,
        "latest_event_recorded_at": str(decision.get("recorded_at") or recorded_at),
        "age_minutes": _age_minutes(now, generated_at or recorded_at),
        "followup_command": str(source.get("followup_command") or ""),
        "decision_actor": str(decision.get("decision_actor") or ""),
        "decision_notes": str(decision.get("decision_notes") or ""),
        "transition_reason": str(decision.get("transition_reason") or ""),
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
    path = Path(ledger_path)
    return path if path.is_absolute() else ROOT_DIR / path


def _followup_command(*, action: str, symbol: str, universe: str, days: int) -> str:
    if not action or action == "none" or not symbol:
        return ""
    return (
        f"./.venv/bin/python scripts/run_split_review_followup.py "
        f"--symbol {symbol.upper()} --universe {universe} --days {max(int(days), 1)} --action {action}"
    )


def _normalize_generation_entry(payload: dict[str, Any]) -> dict[str, Any]:
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
    status = str(source.get("status") or "UNKNOWN")
    return {
        "recorded_at": _recorded_at(),
        "event_type": "packet_generated",
        "status_phase": GENERATION_PHASE,
        "packet_id": str(source.get("packet_id") or f"review_followup:{uuid4().hex}"),
        "generated_at": str(source.get("generated_at") or ""),
        "symbol": symbol,
        "universe": universe,
        "days": days,
        "status": status,
        "generated_status": status,
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
        "previous_status": str(source.get("previous_status") or ""),
        "decision_actor": str(source.get("decision_actor") or ""),
        "decision_notes": str(source.get("decision_notes") or ""),
        "transition_reason": str(source.get("transition_reason") or ""),
        "report_path": report_path,
    }


def _normalized_matching_entries(
    *,
    entries: list[dict[str, Any]],
    symbol: str,
    universe: str,
) -> list[dict[str, Any]]:
    normalized_symbol = str(symbol or "").upper()
    normalized_universe = str(universe or "")
    matching: list[dict[str, Any]] = []
    for row in entries:
        item = dict(row)
        if str(item.get("symbol") or "").upper() != normalized_symbol:
            continue
        if str(item.get("universe") or "") != normalized_universe:
            continue
        item["packet_id"] = _packet_id(item)
        item["status_phase"] = _status_phase(item)
        if item["status_phase"] == GENERATION_PHASE and not item.get("generated_status"):
            item["generated_status"] = str(item.get("status") or "UNKNOWN")
        matching.append(item)
    return matching


def _write_entry(path: Path, entry: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n")
    return entry


def record_split_review_followup_ledger_entry(
    payload: dict[str, Any] | None,
    *,
    ledger_path: str | Path | None = None,
) -> dict[str, Any]:
    entry = _normalize_generation_entry(_dict(payload))
    path = split_review_followup_ledger_path(ledger_path=ledger_path)
    return _write_entry(path, entry)


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


def resolve_split_review_followup_ledger_packet(
    *,
    symbol: str,
    universe: str,
    packet_id: str | None = None,
    selected_action: str | None = None,
    ledger_path: str | Path | None = None,
) -> dict[str, Any] | None:
    path = split_review_followup_ledger_path(ledger_path=ledger_path)
    matching = _normalized_matching_entries(
        entries=_read_entries(path),
        symbol=symbol,
        universe=universe,
    )
    generations = [row for row in matching if row.get("status_phase") == GENERATION_PHASE]
    if not generations:
        return None

    packet_filter = str(packet_id or "").strip()
    action_filter = str(selected_action or "").strip()
    if action_filter in {"", "auto"}:
        action_filter = ""

    generation: dict[str, Any] | None = None
    for row in reversed(generations):
        if packet_filter and str(row.get("packet_id") or "") != packet_filter:
            continue
        if action_filter and str(row.get("selected_action") or "none") != action_filter:
            continue
        generation = dict(row)
        break
    if not generation:
        return None

    resolved_packet_id = str(generation.get("packet_id") or "")
    packet_events = [row for row in matching if str(row.get("packet_id") or "") == resolved_packet_id]
    latest_event = _dict(packet_events[-1] if packet_events else generation)
    latest_decision = _dict(
        next((row for row in reversed(packet_events) if row.get("status_phase") == DECISION_PHASE), {})
    )
    resolved = dict(generation)
    resolved["packet_history_count"] = len(packet_events)
    resolved["latest_event_status"] = str(
        latest_event.get("status") or generation.get("generated_status") or generation.get("status") or "UNKNOWN"
    )
    resolved["latest_event_recorded_at"] = str(
        latest_event.get("recorded_at") or generation.get("recorded_at") or ""
    )
    resolved["latest_decision_status"] = str(latest_decision.get("status") or "none")
    resolved["latest_decision_recorded_at"] = str(latest_decision.get("recorded_at") or "")
    resolved["latest_decision_actor"] = str(latest_decision.get("decision_actor") or "")
    resolved["latest_decision_notes"] = str(latest_decision.get("decision_notes") or "")
    resolved["latest_transition_reason"] = str(latest_decision.get("transition_reason") or "")
    return resolved


def record_split_review_followup_ledger_transition(
    *,
    symbol: str,
    universe: str,
    decision_status: str,
    packet_id: str | None = None,
    selected_action: str | None = None,
    decision_actor: str = "",
    decision_notes: str = "",
    transition_reason: str = "",
    ledger_path: str | Path | None = None,
) -> dict[str, Any]:
    resolved = resolve_split_review_followup_ledger_packet(
        symbol=symbol,
        universe=universe,
        packet_id=packet_id,
        selected_action=selected_action,
        ledger_path=ledger_path,
    )
    if not resolved:
        raise ValueError(
            f"no review followup packet found for symbol={str(symbol or '').upper()} universe={universe}"
        )

    target = _target_contract(resolved)
    entry = {
        "recorded_at": _recorded_at(),
        "event_type": "status_transition",
        "status_phase": DECISION_PHASE,
        "packet_id": str(resolved.get("packet_id") or _packet_id(resolved)),
        "generated_at": str(resolved.get("generated_at") or ""),
        "symbol": str(resolved.get("symbol") or "").upper(),
        "universe": str(resolved.get("universe") or ""),
        "days": max(_int(resolved.get("days"), 7), 1),
        "status": str(decision_status or "UNKNOWN"),
        "generated_status": str(resolved.get("generated_status") or resolved.get("status") or "UNKNOWN"),
        "selected_action": str(resolved.get("selected_action") or "none"),
        "selection_reason": str(resolved.get("selection_reason") or ""),
        "followup_command": str(
            resolved.get("followup_command")
            or _followup_command(
                action=str(resolved.get("selected_action") or "none"),
                symbol=str(target.get("symbol") or resolved.get("symbol") or ""),
                universe=str(resolved.get("universe") or ""),
                days=max(_int(resolved.get("days"), 7), 1),
            )
        ),
        "operator_action_priority": _dict(resolved.get("operator_action_priority")),
        "edge_experiment_review": _dict(resolved.get("edge_experiment_review")),
        "edge_evolution_rule": _dict(resolved.get("edge_evolution_rule")),
        "target_contract": target,
        "previous_status": str(
            resolved.get("latest_event_status") or resolved.get("generated_status") or resolved.get("status") or "UNKNOWN"
        ),
        "decision_actor": str(decision_actor or ""),
        "decision_notes": str(decision_notes or ""),
        "transition_reason": str(transition_reason or ""),
        "report_path": str(resolved.get("report_path") or ""),
    }
    path = split_review_followup_ledger_path(ledger_path=ledger_path)
    return _write_entry(path, entry)


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
    matching = _normalized_matching_entries(
        entries=entries,
        symbol=normalized_symbol,
        universe=normalized_universe,
    )
    generations = [row for row in matching if row.get("status_phase") == GENERATION_PHASE]
    recent = list(reversed(generations[-max(int(limit), 1) :]))
    last = _dict(recent[0] if recent else {})
    last_target = _target_contract(last)
    last_packet_id = str(last.get("packet_id") or "")
    packet_events = [row for row in matching if str(row.get("packet_id") or "") == last_packet_id] if last_packet_id else []
    last_event = _dict(packet_events[-1] if packet_events else last)
    last_decision = _dict(
        next((row for row in reversed(packet_events) if row.get("status_phase") == DECISION_PHASE), {})
    )

    decision_by_packet: dict[str, dict[str, Any]] = {}
    for row in matching:
        if row.get("status_phase") != DECISION_PHASE:
            continue
        packet_key = str(row.get("packet_id") or "")
        if packet_key:
            decision_by_packet[packet_key] = dict(row)

    recent_packets = [
        _packet_digest(
            entry,
            now=now,
            latest_decision=decision_by_packet.get(str(_dict(entry).get("packet_id") or ""), {}),
        )
        for entry in recent
    ]
    status_counts = Counter(str(_dict(row).get("generated_status") or _dict(row).get("status") or "UNKNOWN") for row in recent)
    action_counts = Counter(str(_dict(row).get("selected_action") or "none") for row in recent)
    recent_packet_ids = {
        str(_dict(row).get("packet_id") or "")
        for row in recent
        if str(_dict(row).get("packet_id") or "")
    }
    recent_decisions = [
        row
        for row in matching
        if row.get("status_phase") == DECISION_PHASE and str(row.get("packet_id") or "") in recent_packet_ids
    ]
    decision_status_counts = Counter(str(_dict(row).get("status") or "UNKNOWN") for row in recent_decisions)
    last_action = str(last.get("selected_action") or "none")
    last_status = str(last.get("generated_status") or last.get("status") or ("UNKNOWN" if recent else "none"))
    last_decision_status = str(last_decision.get("status") or "none")
    fresh_ready_packets = [
        packet
        for packet in recent_packets
        if str(_dict(packet).get("generated_status") or "UNKNOWN") == "READY"
        and _int(_dict(packet).get("age_minutes"), FRESH_PACKET_WINDOW_HOURS * 60 + 1)
        <= FRESH_PACKET_WINDOW_HOURS * 60
    ]

    if recent:
        target_symbol = str(last_target.get("symbol") or normalized_symbol or "n/a")
        target_family = str(last_target.get("strategy_family") or "unknown_family")
        if last_decision_status != "none":
            summary = (
                f"Recent split review follow-up history is active; last `{last_action}` packet targeted "
                f"`{target_symbol}` / `{target_family}`, generated as `{last_status}`, and later moved to "
                f"`{last_decision_status}`."
            )
        elif last_status == "READY":
            summary = (
                f"Recent split review follow-up history is active; last `{last_action}` packet targeted "
                f"`{target_symbol}` / `{target_family}` and completed generation in `{last_status}`."
            )
        else:
            summary = (
                f"Recent split review follow-up history needs review; last `{last_action}` packet ended in "
                f"`{last_status}` during packet generation for `{target_symbol}` / `{target_family}`."
            )
    else:
        summary = (
            f"No split review follow-up packets have been recorded yet for `{normalized_symbol}` in "
            f"`{normalized_universe}`."
        )

    if recent:
        reason_codes = [
            f"last_generated_status:{last_status}",
            f"last_effective_status:{last_event.get('status') or last_status}",
            f"last_action:{last_action}",
            f"recent_entries:{len(recent)}",
            f"last_decision_status:{last_decision_status}",
        ]
    else:
        reason_codes = ["recent_entries:0", "ledger:not_recorded"]

    return {
        "available": bool(recent),
        "advisory_only": True,
        "symbol": normalized_symbol,
        "universe": normalized_universe,
        "ledger_path": _relative_path(path),
        "total_entry_count": len(generations),
        "total_event_count": len(matching),
        "recent_entry_count": len(recent),
        "recent_decision_entry_count": len(recent_decisions),
        "summary": summary,
        "reason_codes": reason_codes,
        "last_generated_at": str(last.get("generated_at") or ""),
        "last_recorded_at": str(last_event.get("recorded_at") or last.get("recorded_at") or ""),
        "last_generated_recorded_at": str(last.get("recorded_at") or ""),
        "last_status": last_status,
        "last_generated_status": last_status,
        "last_effective_status": str(last_event.get("status") or last_status or "none"),
        "last_decision_status": last_decision_status,
        "last_decision_recorded_at": str(last_decision.get("recorded_at") or ""),
        "last_decision_actor": str(last_decision.get("decision_actor") or ""),
        "last_decision_notes": str(last_decision.get("decision_notes") or ""),
        "last_transition_reason": str(last_decision.get("transition_reason") or ""),
        "last_previous_status": str(last_decision.get("previous_status") or ""),
        "last_action": last_action,
        "last_packet_id": last_packet_id or "none",
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
        "recent_decision_status_counts": dict(decision_status_counts),
        "recent_action_counts": [
            {"action": action, "count": count}
            for action, count in sorted(action_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "recent_packets": recent_packets,
    }
