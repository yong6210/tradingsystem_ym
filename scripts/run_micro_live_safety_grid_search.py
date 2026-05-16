#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.report_io import atomic_write_text
from scripts import run_micro_live_safety_drag_audit as safety_audit


@dataclass(frozen=True)
class SafetyCase:
    max_pos: int
    cluster_window: int
    cluster_cap: int
    direction_cap: int
    loss_window: int
    loss_trigger: int
    sat: float


@dataclass(frozen=True)
class PreparedTrade:
    entry_ts: datetime
    exit_ts: datetime
    direction: int
    r_value: float


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Grid-search deployable MICRO_LIVE pacing settings against the current SIR backtest trade list."
    )
    parser.add_argument("--backtest-report", default="", help="Backtest JSON with include-trades output.")
    parser.add_argument("--report-dir", default="reports/validation/micro_live_safety_drag_audits")
    parser.add_argument("--position-caps", default="2,3")
    parser.add_argument("--cluster-windows", default="0,30,60,90,120")
    parser.add_argument("--cluster-caps", default="0,1,2,3")
    parser.add_argument("--direction-caps", default="0,1,2,3")
    parser.add_argument("--loss-windows", default="0,60,90,120")
    parser.add_argument("--loss-triggers", default="0,2,3,4")
    parser.add_argument("--saturday-multipliers", default="0.75,0.9,1.0")
    parser.add_argument("--include-unlimited-diagnostic", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def _int_list(raw: Any) -> list[int]:
    values: list[int] = []
    for token in str(raw or "").split(","):
        text = token.strip()
        if not text:
            continue
        values.append(int(float(text)))
    if not values:
        raise ValueError("grid list must not be empty")
    return values


def _float_list(raw: Any) -> list[float]:
    values: list[float] = []
    for token in str(raw or "").split(","):
        text = token.strip()
        if not text:
            continue
        values.append(float(text))
    if not values:
        raise ValueError("grid list must not be empty")
    return values


def _round_float(value: float) -> float:
    return round(float(value), 4)


def _case_dict(case: SafetyCase) -> dict[str, Any]:
    return {
        "max_pos": int(case.max_pos),
        "cluster_window": int(case.cluster_window),
        "cluster_cap": int(case.cluster_cap),
        "direction_cap": int(case.direction_cap),
        "loss_window": int(case.loss_window),
        "loss_trigger": int(case.loss_trigger),
        "sat": float(case.sat),
    }


def _prepare_trades(rows: list[dict[str, Any]]) -> list[PreparedTrade]:
    prepared: list[PreparedTrade] = []
    for row in rows:
        direction = 1 if safety_audit._direction(row) == "LONG" else -1
        prepared.append(
            PreparedTrade(
                entry_ts=row["entry_ts_dt"],
                exit_ts=row["exit_ts_dt"],
                direction=direction,
                r_value=safety_audit._safe_float(row.get("r_value_float")),
            )
        )
    return prepared


def _simulate_case(
    rows: list[PreparedTrade],
    case: SafetyCase,
    *,
    baseline_closed: int,
    baseline_total_r: float,
    include_risk_stats: bool = False,
) -> dict[str, Any]:
    open_positions: list[PreparedTrade] = []
    recent_loss_exits: list[datetime] = []
    reasons: Counter[str] = Counter()
    accepted_curve: list[tuple[datetime, datetime, float]] = []
    closed = 0
    wins = 0
    losses = 0
    total_r = 0.0
    raw_total_r = 0.0
    loss_r = 0.0

    for row in rows:
        if open_positions:
            still_open: list[PreparedTrade] = []
            for item in open_positions:
                if item.exit_ts <= row.entry_ts:
                    if item.r_value <= 0.0:
                        recent_loss_exits.append(item.exit_ts)
                else:
                    still_open.append(item)
            open_positions = still_open

        if case.loss_window > 0:
            loss_cutoff = row.entry_ts - timedelta(minutes=case.loss_window)
            recent_loss_exits = [ts for ts in recent_loss_exits if ts > loss_cutoff]
        else:
            recent_loss_exits = []

        reason = ""
        if case.max_pos > 0 and len(open_positions) >= case.max_pos:
            reason = "micro_live_position_cap_reached"
        elif case.cluster_window > 0 and case.cluster_cap > 0:
            cluster_cutoff = row.entry_ts - timedelta(minutes=case.cluster_window)
            if sum(1 for item in open_positions if item.entry_ts >= cluster_cutoff) >= case.cluster_cap:
                reason = "live_family_cluster_window_cap_reached"

        if not reason and case.direction_cap > 0:
            if sum(1 for item in open_positions if item.direction == row.direction) >= case.direction_cap:
                reason = "live_family_direction_exposure_cap_reached"

        if not reason and case.loss_window > 0 and case.loss_trigger > 0:
            if len(recent_loss_exits) >= case.loss_trigger:
                reason = "live_family_loss_cooldown_active"

        if reason:
            reasons[reason] += 1
            continue

        risk_multiplier = case.sat if row.entry_ts.weekday() == 5 else 1.0
        adjusted_r = row.r_value * risk_multiplier
        closed += 1
        total_r += adjusted_r
        raw_total_r += row.r_value
        if adjusted_r > 0.0:
            wins += 1
        else:
            losses += 1
            loss_r += adjusted_r
        open_positions.append(row)
        if include_risk_stats:
            accepted_curve.append((row.exit_ts, row.entry_ts, adjusted_r))

    result = {
        **_case_dict(case),
        "closed": closed,
        "total_r": _round_float(total_r),
        "raw_total_r": _round_float(raw_total_r),
        "ev": _round_float(total_r / closed) if closed else 0.0,
        "win": _round_float(wins / closed) if closed else 0.0,
        "loss_count": losses,
        "loss_r": _round_float(loss_r),
        "blocked": len(rows) - closed,
        "reasons": dict(sorted(reasons.items())),
        "closed_delta": closed - baseline_closed,
        "closed_delta_pct": round((closed - baseline_closed) / baseline_closed, 6) if baseline_closed else None,
        "total_r_delta": _round_float(total_r - baseline_total_r),
        "total_r_delta_pct": round((total_r - baseline_total_r) / baseline_total_r, 6) if baseline_total_r else None,
    }

    if include_risk_stats:
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        streak = 0
        worst_loss_streak = 0
        for _, _, adjusted_r in sorted(accepted_curve):
            equity += adjusted_r
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
            if adjusted_r <= 0.0:
                streak += 1
                worst_loss_streak = max(worst_loss_streak, streak)
            else:
                streak = 0
        result["max_dd"] = _round_float(max_dd)
        result["worst_loss_streak"] = worst_loss_streak

    return result


def _is_deployable(row: dict[str, Any]) -> bool:
    return (
        1 <= int(row["max_pos"]) <= 3
        and int(row["cluster_window"]) > 0
        and int(row["cluster_cap"]) > 0
        and int(row["direction_cap"]) > 0
        and int(row["loss_window"]) > 0
        and int(row["loss_trigger"]) > 0
    )


def _sort_key(row: dict[str, Any]) -> tuple[float, float, int]:
    return (
        safety_audit._safe_float(row.get("total_r")),
        safety_audit._safe_float(row.get("ev")),
        safety_audit._safe_int(row.get("closed")),
    )


def _load_contract_pass(backtest_report: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    settings = get_settings()
    report_payload, trades = safety_audit._load_trades(backtest_report)
    event_blackouts = safety_audit._load_event_blackouts(settings)
    plan_blocklist = safety_audit._load_plan_blocklist(settings)
    contract_pass: list[dict[str, Any]] = []
    contract_blocked: list[dict[str, Any]] = []
    for row in trades:
        reason = safety_audit._contract_block_reason(
            settings,
            row,
            event_blackouts=event_blackouts,
            plan_blocklist=plan_blocklist,
        )
        if reason:
            blocked = dict(row)
            blocked["audit_block_reason"] = reason
            contract_blocked.append(blocked)
        else:
            contract_pass.append(dict(row))
    return report_payload, trades, contract_pass + contract_blocked


def _split_contract_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    passed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("audit_block_reason") or "").strip():
            blocked.append(row)
        else:
            passed.append(row)
    return passed, blocked


def build_payload(
    *,
    backtest_report: Path,
    position_caps: list[int],
    cluster_windows: list[int],
    cluster_caps: list[int],
    direction_caps: list[int],
    loss_windows: list[int],
    loss_triggers: list[int],
    saturday_multipliers: list[float],
    include_unlimited_diagnostic: bool = True,
) -> dict[str, Any]:
    report_payload, trades, contract_rows = _load_contract_pass(backtest_report)
    contract_pass, contract_blocked = _split_contract_rows(contract_rows)
    prepared = _prepare_trades(contract_pass)
    baseline = safety_audit._stats(trades)
    contract_stats = safety_audit._stats(contract_pass)
    baseline_closed = safety_audit._safe_int(baseline.get("closed"))
    baseline_total = safety_audit._safe_float(baseline.get("total_r"))

    cases: list[SafetyCase] = []
    for max_pos in position_caps:
        for cluster_window in cluster_windows:
            for cluster_cap in cluster_caps:
                for direction_cap in direction_caps:
                    for loss_window in loss_windows:
                        for loss_trigger in loss_triggers:
                            for sat in saturday_multipliers:
                                cases.append(
                                    SafetyCase(
                                        max_pos=max_pos,
                                        cluster_window=cluster_window,
                                        cluster_cap=cluster_cap,
                                        direction_cap=direction_cap,
                                        loss_window=loss_window,
                                        loss_trigger=loss_trigger,
                                        sat=sat,
                                    )
                                )
    if include_unlimited_diagnostic:
        cases.extend(
            SafetyCase(0, 0, 0, 0, 0, 0, sat)
            for sat in saturday_multipliers
        )

    rows = [
        _simulate_case(
            prepared,
            case,
            baseline_closed=baseline_closed,
            baseline_total_r=baseline_total,
        )
        for case in cases
    ]

    raw_top_base = sorted(rows, key=_sort_key, reverse=True)[:20]
    deployable_base = sorted([row for row in rows if _is_deployable(row)], key=_sort_key, reverse=True)[:50]
    cap2_base = sorted(
        [row for row in rows if _is_deployable(row) and int(row["max_pos"]) == 2],
        key=_sort_key,
        reverse=True,
    )[:30]

    def enrich(row: dict[str, Any]) -> dict[str, Any]:
        case = SafetyCase(
            max_pos=int(row["max_pos"]),
            cluster_window=int(row["cluster_window"]),
            cluster_cap=int(row["cluster_cap"]),
            direction_cap=int(row["direction_cap"]),
            loss_window=int(row["loss_window"]),
            loss_trigger=int(row["loss_trigger"]),
            sat=float(row["sat"]),
        )
        return _simulate_case(
            prepared,
            case,
            baseline_closed=baseline_closed,
            baseline_total_r=baseline_total,
            include_risk_stats=True,
        )

    current_settings = get_settings()
    current_case = SafetyCase(
        max_pos=safety_audit._safe_int(
            getattr(current_settings, "auto_trading_micro_live_max_concurrent_positions", 0)
        ),
        cluster_window=safety_audit._safe_int(
            getattr(current_settings, "auto_trading_live_family_cluster_window_minutes", 0)
        ),
        cluster_cap=safety_audit._safe_int(
            getattr(current_settings, "auto_trading_live_max_same_family_entries_per_window", 0)
        ),
        direction_cap=safety_audit._safe_int(
            getattr(current_settings, "auto_trading_live_max_same_family_direction_exposures", 0)
        ),
        loss_window=safety_audit._safe_int(
            getattr(current_settings, "auto_trading_live_recent_loss_cooldown_minutes", 0)
        ),
        loss_trigger=safety_audit._safe_int(
            getattr(current_settings, "auto_trading_live_recent_loss_trigger_count", 0)
        ),
        sat=safety_audit._safe_float(
            getattr(current_settings, "session_impulse_retest_saturday_risk_multiplier", 1.0),
            1.0,
        ),
    )

    return {
        "schema_version": "micro_live_safety_grid_search_v1",
        "generated_at": safety_audit._now().isoformat().replace("+00:00", "Z"),
        "backtest_report": safety_audit._display_path(backtest_report),
        "backtest_generated_at": report_payload.get("generated_at"),
        "grid": {
            "position_caps": position_caps,
            "cluster_windows": cluster_windows,
            "cluster_caps": cluster_caps,
            "direction_caps": direction_caps,
            "loss_windows": loss_windows,
            "loss_triggers": loss_triggers,
            "saturday_multipliers": saturday_multipliers,
            "include_unlimited_diagnostic": bool(include_unlimited_diagnostic),
            "evaluated_cases": len(cases),
        },
        "selection_policy": {
            "deployable_filter": (
                "1 <= max_pos <= 3, cluster brake active, same-direction brake active, loss cooldown active"
            ),
            "objective": "maximize risk-adjusted total_r, then ev, then closed count",
            "raw_top_note": "raw top may include disabled safety/unlimited exposure and is diagnostic only",
        },
        "baseline": baseline,
        "contract_pass": contract_stats,
        "contract_blocked_count": len(contract_blocked),
        "current": enrich(_simulate_case(
            prepared,
            current_case,
            baseline_closed=baseline_closed,
            baseline_total_r=baseline_total,
        )),
        "recommended": enrich(deployable_base[0]) if deployable_base else None,
        "recommended_cap2": enrich(cap2_base[0]) if cap2_base else None,
        "raw_top_20": [enrich(row) for row in raw_top_base],
        "deployable_top_50": [enrich(row) for row in deployable_base],
        "cap2_top_30": [enrich(row) for row in cap2_base],
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# MICRO_LIVE Safety Grid Search",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- backtest_report: {payload.get('backtest_report')}",
        f"- evaluated_cases: {dict(payload.get('grid') or {}).get('evaluated_cases')}",
        "",
        "## Summary",
        "",
        f"- baseline: {payload.get('baseline')}",
        f"- contract_pass: {payload.get('contract_pass')}",
        f"- current: {payload.get('current')}",
        f"- recommended: {payload.get('recommended')}",
        f"- recommended_cap2: {payload.get('recommended_cap2')}",
        "",
        "## Selection Policy",
        "",
        "```json",
        json.dumps(payload.get("selection_policy") or {}, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Payload",
        "",
        "```json",
        json.dumps(payload, ensure_ascii=False, indent=2, default=safety_audit._json_default),
        "```",
    ]
    atomic_write_text(path, "\n".join(lines) + "\n")


def main() -> int:
    args = _parse_args()
    backtest_report = (
        Path(args.backtest_report)
        if str(args.backtest_report or "").strip()
        else safety_audit._latest_backtest_report()
    )
    if not backtest_report.is_absolute():
        backtest_report = ROOT_DIR / backtest_report

    payload = build_payload(
        backtest_report=backtest_report,
        position_caps=_int_list(args.position_caps),
        cluster_windows=_int_list(args.cluster_windows),
        cluster_caps=_int_list(args.cluster_caps),
        direction_caps=_int_list(args.direction_caps),
        loss_windows=_int_list(args.loss_windows),
        loss_triggers=_int_list(args.loss_triggers),
        saturday_multipliers=_float_list(args.saturday_multipliers),
        include_unlimited_diagnostic=bool(args.include_unlimited_diagnostic),
    )
    if not args.no_write_report:
        report_dir = Path(args.report_dir)
        if not report_dir.is_absolute():
            report_dir = ROOT_DIR / report_dir
        generated = safety_audit._parse_ts(str(payload.get("generated_at")))
        report_path = report_dir / f"micro_live_safety_grid_search_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
        _write_report(report_path, payload)
        payload["report_path"] = safety_audit._display_path(report_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=safety_audit._json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
