#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.replay_validation_bridge import ReplayValidationEvidence, UsdtProxyReplayValidationBridge
from app.services.historical_walk_forward_split_review import HistoricalWalkForwardSplitReviewService
from scripts.operation_report_io import parse_report_generated_at
from scripts.run_live_replay_parity_audit import _active_contract_filters_from_settings, _as_utc, _safe_float


DEFAULT_REPLAY_CACHE = "reports/validation/historical_walk_forward_cache/strategy_proof_contract_live_subset.json"


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
    return True if value else False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit whether replay evidence is strong enough to manually review as a validation bridge."
    )
    parser.add_argument("--symbol", default="")
    parser.add_argument("--all-live-symbols", action="store_true")
    parser.add_argument("--cache-file", default=DEFAULT_REPLAY_CACHE)
    parser.add_argument("--min-sample", type=int, default=120)
    parser.add_argument("--min-ev-r", type=float, default=0.20)
    parser.add_argument("--min-ev-lower-r", type=float, default=0.0)
    parser.add_argument("--min-win-rate", type=float, default=0.48)
    parser.add_argument("--min-p1r", type=float, default=0.0)
    parser.add_argument("--min-slice-sample", type=int, default=30)
    parser.add_argument("--max-stop-loss-share", type=float, default=0.45)
    parser.add_argument("--max-drawdown-r", type=float, default=4.5)
    parser.add_argument("--report-dir", default="reports/operations/replay_validation_bridge")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--no-fail-exit", action="store_true")
    return parser.parse_args()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _resolve_root_path(raw_path: str) -> Path:
    path = Path(str(raw_path or "")).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


def _live_symbols_from_settings() -> list[str]:
    settings = get_settings()
    return sorted(
        {
            item.strip().upper()
            for item in str(getattr(settings, "auto_trading_micro_live_allowed_symbols", "")).split(",")
            if item.strip()
        }
    )


def _load_replay_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def _structure_failure_stress_r() -> float:
    value = getattr(
        get_settings(),
        "auto_trading_replay_validation_bridge_sweep_reversal_structure_failure_stress_r",
        -1.0,
    )
    return _safe_float(value, default=-1.0)


def _is_stressed_structure_failure(row: dict[str, Any], realized_r: float) -> bool:
    family = str(row.get("strategy_family") or "").strip().lower()
    reason = str(row.get("final_exit_reason") or "").strip().lower()
    if family != "sweep_reversal" or reason != "structure_failure":
        return False
    return realized_r <= 0.0


def _realized_r(row: dict[str, Any]) -> float:
    value = row.get("final_exit_realized_r")
    if value in {None, ""}:
        value = row.get("replayed_realized_r")
    realized_r = _safe_float(value)
    if _is_stressed_structure_failure(row, realized_r):
        return _structure_failure_stress_r()
    return realized_r


def _filtered_replay_rows(payload: dict[str, Any], filters: dict[str, Any]) -> list[dict[str, Any]]:
    filter_symbol = str(filters.get("symbol") or "").strip().upper()
    strategy_families = {
        str(item or "").strip().lower() for item in list(filters.get("strategy_families") or []) if str(item or "").strip()
    }
    entry_models = {str(item or "").strip().upper() for item in list(filters.get("entry_models") or []) if str(item or "").strip()}
    directions = {str(item or "").strip().upper() for item in list(filters.get("directions") or []) if str(item or "").strip()}
    sessions = {str(item or "").strip().lower() for item in list(filters.get("sessions") or []) if str(item or "").strip()}
    family_sessions = {
        str(key or "").strip().lower(): {str(item or "").strip().lower() for item in list(value or []) if str(item).strip()}
        for key, value in dict(filters.get("family_sessions") or {}).items()
    }
    split_review = HistoricalWalkForwardSplitReviewService(settings=get_settings())
    rows: list[dict[str, Any]] = []
    for raw_row in list(payload.get("trade_rows") or []):
        if not isinstance(raw_row, dict):
            continue
        row = dict(raw_row)
        family = str(row.get("strategy_family") or "").strip().lower()
        generated_ts = _as_utc(row.get("generated_ts")) or _as_utc(row.get("closed_ts"))
        generated_session = split_review._session_bucket(generated_ts)
        row["generated_session"] = generated_session
        if filter_symbol and str(row.get("symbol") or "").strip().upper() != filter_symbol:
            continue
        if strategy_families and family not in strategy_families:
            continue
        if entry_models and str(row.get("entry_model") or "").strip().upper() not in entry_models:
            continue
        if directions and str(row.get("direction") or "").strip().upper() not in directions:
            continue
        if sessions and generated_session not in sessions:
            continue
        allowed_family_sessions = family_sessions.get(family) or set()
        if allowed_family_sessions and generated_session not in allowed_family_sessions:
            continue
        rows.append(row)
    return rows


def _max_drawdown_r(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return round(max_dd, 4)


def _ev_lower_95(values: list[float]) -> float:
    count = len(values)
    if count <= 0:
        return 0.0
    mean = sum(values) / count
    if count == 1:
        return round(mean, 4)
    variance = sum((value - mean) ** 2 for value in values) / (count - 1)
    return round(mean - 1.96 * math.sqrt(variance / count), 4)


def _wilson_lower_95(*, successes: int, count: int) -> float:
    if count <= 0:
        return 0.0
    z = 1.96
    p = successes / count
    denominator = 1.0 + (z * z / count)
    centre = p + (z * z / (2 * count))
    margin = z * math.sqrt((p * (1.0 - p) / count) + (z * z / (4 * count * count)))
    return round(max(0.0, (centre - margin) / denominator), 4)


def _evidence_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [_realized_r(row) for row in rows]
    count = len(values)
    if count <= 0:
        return {
            "sample_size": 0,
            "win_rate": 0.0,
            "win_rate_lower_95": 0.0,
            "avg_win_r": 0.0,
            "avg_loss_r": 0.0,
            "ev_r": 0.0,
            "ev_r_lower_95": 0.0,
            "p1r": 0.0,
            "p2r": 0.0,
            "p3r": 0.0,
            "stop_loss_share": 0.0,
            "structure_failure_share": 0.0,
            "structure_failure_count": 0,
            "structure_failure_stress_r": _structure_failure_stress_r(),
            "max_drawdown_r": 0.0,
        }
    wins = [value for value in values if value > 0.0]
    losses = [abs(value) for value in values if value <= 0.0]
    structure_failures = [
        row
        for row in rows
        if str(row.get("strategy_family") or "").strip().lower() == "sweep_reversal"
        and str(row.get("final_exit_reason") or "").strip().lower() == "structure_failure"
    ]
    stop_losses = [
        row
        for row, value in zip(rows, values, strict=False)
        if str(row.get("final_exit_reason") or "").lower() == "stop_loss" or value <= -1.0
    ]
    return {
        "sample_size": count,
        "win_rate": round(len(wins) / count, 4),
        "win_rate_lower_95": _wilson_lower_95(successes=len(wins), count=count),
        "avg_win_r": round(sum(wins) / len(wins), 4) if wins else 0.0,
        "avg_loss_r": round(sum(losses) / len(losses), 4) if losses else 0.0,
        "ev_r": round(sum(values) / count, 4),
        "ev_r_lower_95": _ev_lower_95(values),
        "p1r": round(sum(1 for value in values if value >= 1.0) / count, 4),
        "p2r": round(sum(1 for value in values if value >= 2.0) / count, 4),
        "p3r": round(sum(1 for value in values if value >= 3.0) / count, 4),
        "stop_loss_share": round(len(stop_losses) / count, 4),
        "structure_failure_share": round(len(structure_failures) / count, 4),
        "structure_failure_count": len(structure_failures),
        "structure_failure_stress_r": _structure_failure_stress_r(),
        "max_drawdown_r": _max_drawdown_r(values),
    }


def _bridge_decision(metrics: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    if int(metrics.get("sample_size") or 0) < int(thresholds.get("min_sample", 80)):
        blockers.append("sample_below_bridge_floor")
    if _safe_float(metrics.get("ev_r")) < float(thresholds.get("min_ev_r", 0.10)):
        blockers.append("ev_below_bridge_floor")
    if _safe_float(metrics.get("ev_r_lower_95")) < float(thresholds.get("min_ev_lower_r", 0.0)):
        blockers.append("ev_lower_95_below_bridge_floor")
    if _safe_float(metrics.get("win_rate")) < float(thresholds.get("min_win_rate", 0.40)):
        blockers.append("win_rate_below_bridge_floor")
    if _safe_float(metrics.get("p1r")) < float(thresholds.get("min_p1r", 0.30)):
        blockers.append("p1r_below_bridge_floor")
    if _safe_float(metrics.get("stop_loss_share")) > float(thresholds.get("max_stop_loss_share", 0.60)):
        blockers.append("stop_loss_share_above_bridge_cap")
    if _safe_float(metrics.get("max_drawdown_r")) > float(thresholds.get("max_drawdown_r", 25.0)):
        blockers.append("drawdown_above_bridge_cap")

    if blockers:
        return {
            "status": "NOT_ELIGIBLE",
            "reason": blockers[0],
            "blockers": blockers,
            "operator_action": "keep_validation_gate_closed_and_collect_live_or_paper_closed_samples",
        }
    return {
        "status": "ELIGIBLE_FOR_MANUAL_BRIDGE_REVIEW",
        "reason": "replay_evidence_clears_bridge_floor",
        "blockers": [],
        "operator_action": "manual_review_before_enabling_any_replay_backed_micro_live_sampling",
    }


def _slice_key(row: dict[str, Any], field: str) -> str:
    value = str(row.get(field) or "").strip()
    if not value:
        return "unknown"
    return value.upper() if field in {"direction", "entry_model"} else value.lower()


def _slice_diagnostics(rows: list[dict[str, Any]], thresholds: dict[str, Any]) -> list[dict[str, Any]]:
    min_slice_sample = max(1, int(thresholds.get("min_slice_sample") or 30))
    slice_rows: list[dict[str, Any]] = []
    for field in ("direction", "strategy_family", "entry_model"):
        values = sorted({_slice_key(row, field) for row in rows})
        for value in values:
            matched = [row for row in rows if _slice_key(row, field) == value]
            metrics = _evidence_metrics(matched)
            slice_thresholds = dict(thresholds)
            slice_thresholds["min_sample"] = min_slice_sample
            decision = _bridge_decision(metrics, slice_thresholds)
            slice_rows.append(
                {
                    "slice_type": field,
                    "slice_value": value,
                    "material": int(metrics.get("sample_size") or 0) >= min_slice_sample,
                    "replay_metrics": metrics,
                    "bridge_decision": decision,
                }
            )
    return slice_rows


def _row_payload(
    *,
    payload: dict[str, Any],
    symbol: str,
    thresholds: dict[str, Any],
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    filters = dict(filters or _active_contract_filters_from_settings(symbol))
    rows = _filtered_replay_rows(payload, filters)
    metrics = _evidence_metrics(rows)
    decision = _bridge_decision(metrics, thresholds)
    slices = _slice_diagnostics(rows, thresholds)
    weak_material_slices = [
        {
            "slice_type": item["slice_type"],
            "slice_value": item["slice_value"],
            "reason": dict(item.get("bridge_decision") or {}).get("reason"),
            "blockers": list(dict(item.get("bridge_decision") or {}).get("blockers") or []),
            "sample_size": dict(item.get("replay_metrics") or {}).get("sample_size"),
        }
        for item in slices
        if _safe_bool(item.get("material"))
        and str(dict(item.get("bridge_decision") or {}).get("status") or "") == "NOT_ELIGIBLE"
    ]
    if str(decision.get("status") or "") == "ELIGIBLE_FOR_MANUAL_BRIDGE_REVIEW" and weak_material_slices:
        decision = dict(decision)
        decision["status"] = "ELIGIBLE_FOR_MANUAL_BRIDGE_REVIEW_WITH_SLICE_WARNINGS"
        decision["reason"] = "replay_bridge_has_weak_material_slices"
        decision["warnings"] = weak_material_slices[:8]
        decision["operator_action"] = "manual_review_slice_warnings_before_enabling_replay_backed_sampling"
    return {
        "symbol": symbol.upper(),
        "filters": filters,
        "replay_metrics": metrics,
        "slice_diagnostics": slices,
        "bridge_decision": decision,
    }


def _runtime_bridge_metrics(evidence: ReplayValidationEvidence) -> dict[str, Any]:
    metrics = dict(evidence.metrics or {})
    sample_size = max(
        int(_safe_float(metrics.get("sample_size"))),
        int(_safe_float(metrics.get("trade_count"))),
        int(_safe_float(metrics.get("closed_trades"))),
    )
    ev_r = _safe_float(metrics.get("ev_r"), default=_safe_float(metrics.get("expectancy_r"), default=_safe_float(metrics.get("ev"))))
    return {
        "sample_size": sample_size,
        "closed_trades": int(_safe_float(metrics.get("closed_trades"), default=sample_size)),
        "win_rate": round(_safe_float(metrics.get("win_rate")), 4),
        "win_rate_lower_95": round(_safe_float(metrics.get("win_rate_lower_95")), 4),
        "avg_win_r": round(_safe_float(metrics.get("avg_win_r")), 4),
        "avg_loss_r": round(_safe_float(metrics.get("avg_loss_r")), 4),
        "ev_r": round(ev_r, 4),
        "ev_r_lower_95": round(_safe_float(metrics.get("ev_r_lower_95")), 4),
        "p1r": round(_safe_float(metrics.get("p1r")), 4),
        "p2r": round(_safe_float(metrics.get("p2r")), 4),
        "p3r": round(_safe_float(metrics.get("p3r")), 4),
        "stop_loss_share": round(_safe_float(metrics.get("stop_loss_share")), 4),
        "structure_failure_share": round(_safe_float(metrics.get("structure_failure_share")), 4),
        "structure_failure_count": int(_safe_float(metrics.get("structure_failure_count"))),
        "structure_failure_stress_r": metrics.get("structure_failure_stress_r"),
        "max_drawdown_r": round(_safe_float(metrics.get("max_drawdown_r")), 4),
        "max_portfolio_drawdown_pct": round(_safe_float(metrics.get("max_portfolio_drawdown_pct")), 4),
        "portfolio_years": int(_safe_float(metrics.get("portfolio_years"))),
        "min_portfolio_return_pct": round(_safe_float(metrics.get("min_portfolio_return_pct")), 4),
        "total_score": round(_safe_float(metrics.get("total_score")), 2),
        "grade": str(metrics.get("grade") or ""),
        "recommendation": str(metrics.get("recommendation") or ""),
    }


def _runtime_bridge_row_payload(*, symbol: str, family: str, filters: dict[str, Any]) -> dict[str, Any]:
    entry_models = [str(item or "").strip().upper() for item in list(filters.get("entry_models") or []) if str(item).strip()]
    entry_model = entry_models[0] if entry_models else ""
    evidence = UsdtProxyReplayValidationBridge(get_settings()).evaluate(
        symbol=symbol,
        family=family,
        entry_model=entry_model,
    )
    decision = {
        "status": "ELIGIBLE_FOR_RUNTIME_VALIDATION_BRIDGE" if evidence.approval_usable else "NOT_ELIGIBLE",
        "reason": evidence.reason_code,
        "blockers": [] if evidence.approval_usable else list(evidence.reason_codes),
        "operator_action": (
            "runtime_validation_bridge_available_keep_validation_gate_enabled"
            if evidence.approval_usable
            else "keep_validation_gate_closed_and_collect_live_or_paper_closed_samples"
        ),
    }
    family_filters = dict(filters)
    family_filters["strategy_families"] = [family]
    family_filters["family_sessions"] = {
        family: list(dict(filters.get("family_sessions") or {}).get(family) or [])
    }
    return {
        "symbol": symbol.upper(),
        "filters": family_filters,
        "replay_metrics": _runtime_bridge_metrics(evidence),
        "slice_diagnostics": [],
        "bridge_decision": decision,
        "runtime_bridge": {
            "source": str(evidence.source.get("bridge_source") or "usdt_proxy_replay_bridge"),
            "approval_usable": evidence.approval_usable,
            "message": evidence.message,
            "source_reports": evidence.source,
            "reason_codes": list(evidence.reason_codes),
            "failures": list(evidence.failures),
        },
    }


def _family_filters(filters: dict[str, Any], family: str) -> dict[str, Any]:
    scoped = dict(filters)
    scoped["strategy_families"] = [family]
    scoped["family_sessions"] = {
        family: list(dict(filters.get("family_sessions") or {}).get(family) or [])
    }
    return scoped


def _row_payloads_for_symbol(*, payload: dict[str, Any], symbol: str, thresholds: dict[str, Any]) -> list[dict[str, Any]]:
    filters = _active_contract_filters_from_settings(symbol)
    families = [
        str(item or "").strip().lower()
        for item in list(filters.get("strategy_families") or [])
        if str(item or "").strip()
    ]
    if not families:
        return [_row_payload(payload=payload, symbol=symbol, thresholds=thresholds, filters=filters)]

    rows: list[dict[str, Any]] = []
    for family in families:
        scoped_filters = _family_filters(filters, family)
        if family == "session_impulse_retest":
            rows.append(_runtime_bridge_row_payload(symbol=symbol, family=family, filters=scoped_filters))
        else:
            rows.append(
                _row_payload(
                    payload=payload,
                    symbol=symbol,
                    thresholds=thresholds,
                    filters=scoped_filters,
                )
            )
    return rows


def build_payload(*, symbol: str, all_live_symbols: bool, cache_file: str, thresholds: dict[str, Any]) -> dict[str, Any]:
    cache_path = _resolve_root_path(cache_file or DEFAULT_REPLAY_CACHE)
    replay_payload = _load_replay_payload(cache_path)
    if all_live_symbols or not str(symbol or "").strip():
        symbols = _live_symbols_from_settings()
    else:
        symbols = [str(symbol).strip().upper()]
    rows = [
        row
        for item in symbols
        for row in _row_payloads_for_symbol(payload=replay_payload, symbol=item, thresholds=thresholds)
    ]
    decision_counts: dict[str, int] = {}
    blocker_counts: dict[str, int] = {}
    for row in rows:
        decision = dict(row.get("bridge_decision") or {})
        status = str(decision.get("status") or "UNKNOWN")
        decision_counts[status] = decision_counts.get(status, 0) + 1
        for blocker in list(decision.get("blockers") or []):
            key = str(blocker or "")
            blocker_counts[key] = blocker_counts.get(key, 0) + 1
    not_eligible_count = int(decision_counts.get("NOT_ELIGIBLE", 0))
    eligible_count = sum(count for status, count in decision_counts.items() if status.startswith("ELIGIBLE_FOR"))
    warning_count = int(decision_counts.get("ELIGIBLE_FOR_MANUAL_BRIDGE_REVIEW_WITH_SLICE_WARNINGS", 0))
    if not rows:
        overall_status = "INSUFFICIENT_BASELINE"
        reason = "no_symbols_configured"
    elif eligible_count <= 0:
        overall_status = "ALERT"
        reason = "no_symbol_clears_replay_validation_bridge_floor"
    elif not_eligible_count > 0 or warning_count > 0:
        overall_status = "WATCH"
        reason = "mixed_replay_validation_bridge_evidence"
    else:
        overall_status = "PASS"
        reason = "all_symbols_clear_replay_validation_bridge_floor"
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "mode": "audit_only",
        "live_approval_changed": False,
        "cache_file": str(cache_path),
        "cache_simulation_start_ts": replay_payload.get("simulation_start_ts"),
        "cache_simulation_end_ts": replay_payload.get("simulation_end_ts"),
        "cache_loaded": bool(replay_payload),
        "thresholds": thresholds,
        "overall_status": overall_status,
        "reason": reason,
        "decision_counts": dict(sorted(decision_counts.items())),
        "top_blockers": dict(sorted(blocker_counts.items(), key=lambda item: item[1], reverse=True)[:10]),
        "rows": rows,
    }


def _write_report(path: Path, payload: dict[str, Any], *, atomic: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Replay Validation Bridge Audit",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- mode: {payload.get('mode')}",
        f"- live_approval_changed: {payload.get('live_approval_changed')}",
        f"- overall_status: {payload.get('overall_status')}",
        f"- reason: {payload.get('reason')}",
        f"- thresholds: {payload.get('thresholds')}",
        f"- decision_counts: {payload.get('decision_counts')}",
        f"- top_blockers: {payload.get('top_blockers')}",
        "",
        "## Symbol Rows",
        "",
    ]
    for row in list(payload.get("rows") or []):
        metrics = dict(row.get("replay_metrics") or {})
        decision = dict(row.get("bridge_decision") or {})
        warnings = list(decision.get("warnings") or [])
        lines.append(
            f"- {row.get('symbol')}: {decision.get('status')} | reason={decision.get('reason')} | "
            f"sample={metrics.get('sample_size')} ev={metrics.get('ev_r')} ev_l95={metrics.get('ev_r_lower_95')} "
            f"win={metrics.get('win_rate')} win_l95={metrics.get('win_rate_lower_95')} "
            f"p1r={metrics.get('p1r')} stop={metrics.get('stop_loss_share')} "
            f"structure_failure={metrics.get('structure_failure_share')} dd={metrics.get('max_drawdown_r')} "
            f"warnings={len(warnings)}"
        )
    lines.extend(["", "```json", json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), "```"])
    content = "\n".join(lines)
    if atomic:
        _atomic_write_text(path, content)
    else:
        _atomic_write_text(path, content)


def _write_latest_aliases(*, report_dir: Path, payload: dict[str, Any]) -> dict[str, str]:
    latest_md = report_dir / "latest.md"
    latest_json = report_dir / "latest.json"
    _write_report(latest_md, payload, atomic=True)
    _atomic_write_text(latest_json, json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return {
        "latest_report_path": _display_path(latest_md),
        "latest_json_path": _display_path(latest_json),
    }


def main() -> int:
    args = parse_args()
    thresholds = {
        "min_sample": max(1, int(args.min_sample)),
        "min_ev_r": float(args.min_ev_r),
        "min_ev_lower_r": float(args.min_ev_lower_r),
        "min_win_rate": float(args.min_win_rate),
        "min_p1r": float(args.min_p1r),
        "min_slice_sample": max(1, int(args.min_slice_sample)),
        "max_stop_loss_share": float(args.max_stop_loss_share),
        "max_drawdown_r": float(args.max_drawdown_r),
    }
    payload = build_payload(
        symbol=str(args.symbol or ""),
        all_live_symbols=bool(args.all_live_symbols),
        cache_file=str(args.cache_file or DEFAULT_REPLAY_CACHE),
        thresholds=thresholds,
    )
    if not args.no_write_report:
        generated = parse_report_generated_at(payload.get("generated_at"))
        report_dir = ROOT_DIR / args.report_dir
        report_path = report_dir / f"replay_validation_bridge_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
        payload["report_path"] = _display_path(report_path)
        payload["latest_report_path"] = _display_path(report_dir / "latest.md")
        payload["latest_json_path"] = _display_path(report_dir / "latest.json")
        _write_report(report_path, payload, atomic=True)
        payload.update(_write_latest_aliases(report_dir=report_dir, payload=payload))
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    fail = payload["overall_status"] in {"ALERT", "INSUFFICIENT_BASELINE"}
    return 1 if fail and not bool(args.no_fail_exit) else 0


if __name__ == "__main__":
    raise SystemExit(main())
