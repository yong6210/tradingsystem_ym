#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import CURRENT_MICRO_LIVE_USDT_SYMBOLS, get_settings
from app.services.micro_main_strategy_research import (
    MicroTrade,
    SessionImpulseRetestExitPolicy,
    SessionImpulseRetestResearch,
    session_impulse_retest_profile_for_symbol,
)
from app.services.report_io import atomic_write_text
from scripts.run_micro_main_usdt_proxy_backtest import _fetch_1m_klines, _resample_to_5m


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search SL/TP exit policies for session_impulse_retest entries.")
    parser.add_argument("--symbols", default=CURRENT_MICRO_LIVE_USDT_SYMBOLS)
    parser.add_argument("--stage1-symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,AVAXUSDT,LINKUSDT,DOGEUSDT")
    parser.add_argument("--stage1-days", type=int, default=365)
    parser.add_argument("--stage2-days", type=int, default=1095)
    parser.add_argument("--stage2-top", type=int, default=30)
    parser.add_argument("--max-policies", type=int, default=0)
    parser.add_argument("--report-dir", default="reports/validation/micro_main_exit_policy_search")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _csv(value: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in str(value or "").split(","):
        item = raw.strip().upper()
        if item and item not in seen:
            out.append(item)
            seen.add(item)
    return out


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed == parsed else default


def _quantile(values: list[float], q: float) -> float:
    clean = sorted(value for value in values if value == value)
    if not clean:
        return 0.0
    idx = max(0, min(len(clean) - 1, int((len(clean) - 1) * max(0.0, min(float(q), 1.0)))))
    return float(clean[idx])


def _policy_time_guard_suffix(guard: str) -> dict[str, float | None]:
    if guard == "off":
        return {"time_guard_10m_min_mfe_r": None, "time_guard_20m_min_mfe_r": None}
    if guard == "relaxed":
        return {"time_guard_10m_min_mfe_r": 0.05, "time_guard_20m_min_mfe_r": 0.15}
    return {"time_guard_10m_min_mfe_r": 0.20, "time_guard_20m_min_mfe_r": 0.35}


def _add_policy(
    policies: list[SessionImpulseRetestExitPolicy],
    *,
    name: str,
    stop_mode: str,
    swing: int = 0,
    buffer: float | None = None,
    min_stop: float = 0.0,
    min_risk_atr: float = 0.0,
    rr: float = 2.0,
    hold: int = 40,
    guard: str = "current",
    tp_profile: str = "full",
) -> None:
    payload: dict[str, Any] = {
        "name": name,
        "stop_mode": stop_mode,
        "swing_lookback_bars": int(swing),
        "stop_buffer_atr": buffer,
        "min_stop_pct": float(min_stop),
        "min_risk_atr": float(min_risk_atr),
        "target_rr": float(rr),
        "max_hold_minutes": int(hold),
        **_policy_time_guard_suffix(guard),
    }
    if tp_profile == "live_35_65":
        payload.update({"tp1_rr": 1.0, "tp1_fraction": 0.35, "tp2_rr": float(rr), "tp2_fraction": 0.65})
    elif tp_profile == "late_25_75":
        first_rr = min(1.5, max(1.0, float(rr) - 0.5))
        payload.update({"tp1_rr": first_rr, "tp1_fraction": 0.25, "tp2_rr": float(rr), "tp2_fraction": 0.75})
    policies.append(SessionImpulseRetestExitPolicy(**payload))


def build_exit_policies() -> list[SessionImpulseRetestExitPolicy]:
    policies: list[SessionImpulseRetestExitPolicy] = []
    _add_policy(policies, name="legacy_full_2r", stop_mode="legacy", rr=2.0, hold=40, guard="current")
    _add_policy(
        policies,
        name="legacy_live_split_1r35_2r65",
        stop_mode="legacy",
        rr=2.0,
        hold=40,
        guard="current",
        tp_profile="live_35_65",
    )
    for min_stop in (0.003, 0.004, 0.005):
        for min_risk_atr in (0.0, 0.35):
            for rr in (2.0, 2.5, 3.0):
                for hold in (40, 60, 90):
                    for guard in ("current", "off"):
                        for tp_profile in ("full", "live_35_65"):
                            _add_policy(
                                policies,
                                name=(
                                    f"floor:min{min_stop:.4f}:atr{min_risk_atr:.2f}:"
                                    f"rr{rr}:hold{hold}:guard{guard}:tp{tp_profile}"
                                ),
                                stop_mode="floor",
                                min_stop=min_stop,
                                min_risk_atr=min_risk_atr,
                                rr=rr,
                                hold=hold,
                                guard=guard,
                                tp_profile=tp_profile,
                            )
    for swing in (3, 6, 12):
        for buffer in (0.12, 0.20):
            for min_stop in (0.003, 0.004, 0.005):
                for rr in (2.0, 2.5, 3.0):
                    for hold in (60, 90):
                        for guard in ("off",):
                            for tp_profile in ("full", "live_35_65"):
                                _add_policy(
                                    policies,
                                    name=(
                                        f"structure:swing{swing}:buf{buffer:.2f}:min{min_stop:.4f}:"
                                        f"rr{rr}:hold{hold}:guard{guard}:tp{tp_profile}"
                                    ),
                                    stop_mode="structure_floor",
                                    swing=swing,
                                    buffer=buffer,
                                    min_stop=min_stop,
                                    rr=rr,
                                    hold=hold,
                                    guard=guard,
                                    tp_profile=tp_profile,
                                )
    deduped: list[SessionImpulseRetestExitPolicy] = []
    seen: set[str] = set()
    for policy in policies:
        if policy.name in seen:
            continue
        deduped.append(policy)
        seen.add(policy.name)
    return deduped


def _trade_row(trade: MicroTrade, *, policy: SessionImpulseRetestExitPolicy) -> dict[str, Any]:
    risk_abs = abs(float(trade.entry_price) - float(trade.stop_price))
    diagnostics = dict(trade.diagnostics or {})
    return {
        "policy": policy.name,
        "symbol": trade.symbol,
        "direction": trade.direction,
        "entry_ts": trade.entry_ts.astimezone(UTC).isoformat(),
        "exit_ts": trade.exit_ts.astimezone(UTC).isoformat(),
        "entry_price": round(float(trade.entry_price), 8),
        "stop_price": round(float(trade.stop_price), 8),
        "target_price": round(float(trade.target_price), 8),
        "stop_distance_pct": round(risk_abs / max(abs(float(trade.entry_price)), 1e-12), 6),
        "r_value": round(float(trade.r_value), 6),
        "gross_r": round(float(trade.gross_r), 6),
        "cost_r": round(float(trade.cost_r), 6),
        "hold_minutes": int(trade.hold_minutes),
        "exit_reason": trade.exit_reason,
        "entry_year": trade.entry_ts.year,
        "diagnostics": {
            key: round(value, 6) if isinstance(value, float) else value
            for key, value in sorted(diagnostics.items())
        },
    }


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (str(row.get("exit_ts") or ""), str(row.get("symbol") or "")))
    values = [_safe_float(row.get("r_value")) for row in ordered]
    gross = [_safe_float(row.get("gross_r")) for row in ordered]
    costs = [_safe_float(row.get("cost_r")) for row in ordered]
    stops = [_safe_float(row.get("stop_distance_pct")) for row in ordered]
    holds = [_safe_float(row.get("hold_minutes")) for row in ordered]
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    by_year: dict[str, float] = {}
    by_symbol: dict[str, float] = {}
    exit_reasons: Counter[str] = Counter()
    for row, value in zip(ordered, values, strict=False):
        year = str(row.get("entry_year") or str(row.get("entry_ts") or "")[:4])
        symbol = str(row.get("symbol") or "")
        by_year[year] = by_year.get(year, 0.0) + value
        by_symbol[symbol] = by_symbol.get(symbol, 0.0) + value
        exit_reasons[str(row.get("exit_reason") or "unknown")] += 1
    closed = len(values)
    total = sum(values)
    wins = sum(1 for value in values if value > 0.0)
    positive_symbols = sum(1 for value in by_symbol.values() if value > 0.0)
    positive_years = sum(1 for value in by_year.values() if value > 0.0)
    consistency = (positive_symbols / max(len(by_symbol), 1)) * (positive_years / max(len(by_year), 1))
    ev = total / closed if closed else 0.0
    score = (total / max(max_dd, 5.0)) * max(ev, 0.0) * math.log10(closed + 10) * max(consistency, 0.05)
    return {
        "closed": closed,
        "total_r": round(total, 4),
        "gross_r": round(sum(gross), 4),
        "ev_r": round(ev, 4) if closed else 0.0,
        "win_rate": round(wins / closed, 4) if closed else 0.0,
        "max_dd_r": round(max_dd, 4),
        "profit_to_dd": round(total / max(max_dd, 1e-9), 4) if max_dd > 0.0 else 0.0,
        "avg_cost_r": round(sum(costs) / closed, 4) if closed else 0.0,
        "avg_stop_pct": round(sum(stops) / closed, 6) if closed else 0.0,
        "p25_stop_pct": round(_quantile(stops, 0.25), 6),
        "p50_stop_pct": round(_quantile(stops, 0.50), 6),
        "p75_stop_pct": round(_quantile(stops, 0.75), 6),
        "avg_hold_minutes": round(sum(holds) / closed, 2) if closed else 0.0,
        "positive_symbol_count": positive_symbols,
        "symbol_count": len(by_symbol),
        "positive_symbol_fraction": round(positive_symbols / max(len(by_symbol), 1), 4),
        "positive_year_count": positive_years,
        "year_count": len(by_year),
        "positive_year_fraction": round(positive_years / max(len(by_year), 1), 4),
        "by_year_total_r": {key: round(value, 4) for key, value in sorted(by_year.items())},
        "exit_reasons": dict(sorted(exit_reasons.items())),
        "score": round(score, 6),
    }


def run_stage(
    *,
    symbols: list[str],
    policies: list[SessionImpulseRetestExitPolicy],
    days: int,
    monthly_client: httpx.Client,
    rest_client: httpx.Client,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows_by_policy: dict[str, list[dict[str, Any]]] = {policy.name: [] for policy in policies}
    data_status: dict[str, Any] = {}
    end_ts = datetime.now(UTC).replace(second=0, microsecond=0)
    start_ts = end_ts - timedelta(days=max(int(days), 1))
    for symbol in symbols:
        candles_1m = _fetch_1m_klines(monthly_client, rest_client, symbol=symbol, start_ts=start_ts, end_ts=end_ts)
        candles_5m = _resample_to_5m(candles_1m)
        data_status[symbol] = {
            "candles_1m": len(candles_1m),
            "candles_5m": len(candles_5m),
            "first_1m_ts": candles_1m[0].ts.isoformat() if candles_1m else None,
            "last_1m_ts": candles_1m[-1].ts.isoformat() if candles_1m else None,
        }
        if len(candles_1m) < 600 or len(candles_5m) < 200:
            print(json.dumps({"symbol": symbol, "status": "insufficient_candles", **data_status[symbol]}), file=sys.stderr, flush=True)
            continue
        for policy in policies:
            engine = SessionImpulseRetestResearch(
                symbol=symbol,
                candles_1m=candles_1m,
                candles_5m=candles_5m,
                profile_name=session_impulse_retest_profile_for_symbol(symbol),
                exit_policy=policy,
            )
            trades = engine.backtest()
            rows_by_policy[policy.name].extend(_trade_row(trade, policy=policy) for trade in trades)
        print(json.dumps({"symbol": symbol, "status": "done", **data_status[symbol]}), file=sys.stderr, flush=True)
    rows = [
        {
            "policy": asdict(policy),
            "summary": summarize_rows(rows_by_policy[policy.name]),
        }
        for policy in policies
    ]
    return rows, data_status


def _rank(rows: list[dict[str, Any]], *, min_trades: int = 0) -> list[dict[str, Any]]:
    eligible = [row for row in rows if int(dict(row.get("summary") or {}).get("closed", 0) or 0) >= int(min_trades)]
    return sorted(
        eligible,
        key=lambda row: (
            float(dict(row.get("summary") or {}).get("score", 0.0) or 0.0),
            float(dict(row.get("summary") or {}).get("total_r", 0.0) or 0.0),
            float(dict(row.get("summary") or {}).get("ev_r", 0.0) or 0.0),
        ),
        reverse=True,
    )


def _policy_from_row(row: dict[str, Any]) -> SessionImpulseRetestExitPolicy:
    return SessionImpulseRetestExitPolicy(**dict(row.get("policy") or {}))


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    generated_at = datetime.now(UTC)
    symbols = _csv(args.symbols)
    stage1_symbols = [symbol for symbol in _csv(args.stage1_symbols) if symbol in set(symbols)] or symbols[:8]
    policies = build_exit_policies()
    if int(args.max_policies or 0) > 0:
        policies = policies[: int(args.max_policies)]

    with (
        httpx.Client(timeout=120.0, follow_redirects=True) as monthly_client,
        httpx.Client(base_url=settings.binance_rest_base_url, timeout=30.0) as rest_client,
    ):
        stage1_rows, stage1_data = run_stage(
            symbols=stage1_symbols,
            policies=policies,
            days=max(int(args.stage1_days), 30),
            monthly_client=monthly_client,
            rest_client=rest_client,
        )
        stage1_ranked = _rank(stage1_rows, min_trades=max(20, int(args.stage1_days) // 2))
        stage2_policies = [_policy_from_row(row) for row in stage1_ranked[: max(int(args.stage2_top), 1)]]
        stage2_rows, stage2_data = run_stage(
            symbols=symbols,
            policies=stage2_policies,
            days=max(int(args.stage2_days), int(args.stage1_days)),
            monthly_client=monthly_client,
            rest_client=rest_client,
        )

    output = {
        "schema_version": "micro_main_exit_policy_search_v1",
        "generated_at": generated_at.isoformat(),
        "scope": {
            "symbols": symbols,
            "stage1_symbols": stage1_symbols,
            "stage1_days": int(args.stage1_days),
            "stage2_days": int(args.stage2_days),
            "policy_count": len(policies),
            "stage2_policy_count": len(stage2_policies),
            "notes": [
                "entry signal is still session_impulse_retest; this search changes only SL/TP and time-exit behavior",
                "same-minute stop and target collision is treated as stop-first",
                "fee model uses existing round-trip fee assumption from SessionImpulseRetestResearch",
            ],
        },
        "stage1_data_status": stage1_data,
        "stage2_data_status": stage2_data,
        "stage1_top": stage1_ranked[:50],
        "stage2_top": _rank(stage2_rows, min_trades=max(50, int(args.stage2_days) // 2))[:50],
        "stage2_all": stage2_rows,
    }
    if args.write_report:
        out_dir = ROOT_DIR / str(args.report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"micro_main_exit_policy_search_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        atomic_write_text(out_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))
        output["report_path"] = str(out_path.relative_to(ROOT_DIR))
    print(json.dumps({key: value for key, value in output.items() if key != "stage2_all"}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
