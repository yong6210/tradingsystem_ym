#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import CURRENT_MICRO_LIVE_USDT_SYMBOLS, get_settings
from app.services.micro_main_strategy_research import (
    SessionImpulseRetestExitPolicy,
    SessionImpulseRetestResearch,
    session_impulse_retest_profile_for_symbol,
)
from app.services.report_io import atomic_write_text
from scripts.run_micro_main_exit_policy_search import _csv, _safe_float, _trade_row, build_exit_policies, summarize_rows
from scripts.run_micro_main_usdt_proxy_backtest import _fetch_1m_klines, _resample_to_5m


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare old same-bar SIR entry timing with no-lookahead timing.")
    parser.add_argument("--symbols", default=CURRENT_MICRO_LIVE_USDT_SYMBOLS)
    parser.add_argument("--days", type=int, default=1095)
    parser.add_argument(
        "--policies",
        default=(
            "legacy_full_2r,"
            "legacy_live_split_1r35_2r65,"
            "structure_adaptive_floor_min_0_003_live_split,"
            "pm_structure_adaptive_stop_after_partial_0.10r"
        ),
    )
    parser.add_argument("--old-delay-minutes", type=int, default=0)
    parser.add_argument("--new-delay-minutes", type=int, default=5)
    parser.add_argument("--report-dir", default="reports/validation/micro_main_entry_timing_compare")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _select_policies(names: list[str]) -> list[SessionImpulseRetestExitPolicy]:
    by_name = {policy.name: policy for policy in build_exit_policies()}
    selected: list[SessionImpulseRetestExitPolicy] = []
    missing: list[str] = []
    for name in names:
        policy = by_name.get(name)
        if policy is None:
            missing.append(name)
            continue
        selected.append(policy)
    if missing:
        raise SystemExit(f"unknown policies: {','.join(missing)}")
    return selected


def _policy_names(value: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in str(value or "").split(","):
        item = raw.strip()
        if item and item not in seen:
            out.append(item)
            seen.add(item)
    return out


def _delta(new: dict[str, Any], old: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "closed",
        "total_r",
        "gross_r",
        "ev_r",
        "win_rate",
        "max_dd_r",
        "profit_to_dd",
        "positive_symbol_fraction",
        "positive_year_fraction",
        "avg_hold_minutes",
    ]
    return {key: round(_safe_float(new.get(key)) - _safe_float(old.get(key)), 6) for key in keys}


def _label(delay_minutes: int, *, old_delay: int, new_delay: int) -> str:
    if delay_minutes == old_delay:
        return "old_same_5m_bar_allowed"
    if delay_minutes == new_delay:
        return "new_no_lookahead_after_5m_close"
    return f"entry_delay_{delay_minutes}m"


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    generated_at = datetime.now(UTC)
    symbols = _csv(args.symbols)
    policy_names = _policy_names(args.policies)
    selected_policies = _select_policies(policy_names)
    delays = [int(args.old_delay_minutes), int(args.new_delay_minutes)]
    end_ts = datetime.now(UTC).replace(second=0, microsecond=0)
    start_ts = end_ts - timedelta(days=max(int(args.days), 1))

    rows_by_key: dict[str, list[dict[str, Any]]] = {}
    data_status: dict[str, Any] = {}
    for policy in selected_policies:
        for delay in delays:
            rows_by_key[f"{policy.name}:{delay}"] = []

    with (
        httpx.Client(timeout=120.0, follow_redirects=True) as monthly_client,
        httpx.Client(base_url=settings.binance_rest_base_url, timeout=30.0) as rest_client,
    ):
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
            for base_policy in selected_policies:
                for delay in delays:
                    policy = replace(base_policy, entry_confirmation_delay_minutes=delay)
                    engine = SessionImpulseRetestResearch(
                        symbol=symbol,
                        candles_1m=candles_1m,
                        candles_5m=candles_5m,
                        profile_name=session_impulse_retest_profile_for_symbol(symbol),
                        exit_policy=policy,
                    )
                    trades = engine.backtest()
                    rows_by_key[f"{base_policy.name}:{delay}"].extend(
                        _trade_row(trade, policy=policy) for trade in trades
                    )
            print(json.dumps({"symbol": symbol, "status": "done", **data_status[symbol]}), file=sys.stderr, flush=True)

    policy_results: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    for base_policy in selected_policies:
        by_delay: dict[str, Any] = {}
        for delay in delays:
            key = f"{base_policy.name}:{delay}"
            summary = summarize_rows(rows_by_key[key])
            label = _label(delay, old_delay=int(args.old_delay_minutes), new_delay=int(args.new_delay_minutes))
            by_delay[label] = {
                "delay_minutes": delay,
                "policy": asdict(replace(base_policy, entry_confirmation_delay_minutes=delay)),
                "summary": summary,
            }
            policy_results.append({"policy_name": base_policy.name, "timing_label": label, **by_delay[label]})
        old_label = _label(int(args.old_delay_minutes), old_delay=int(args.old_delay_minutes), new_delay=int(args.new_delay_minutes))
        new_label = _label(int(args.new_delay_minutes), old_delay=int(args.old_delay_minutes), new_delay=int(args.new_delay_minutes))
        old_summary = dict(by_delay[old_label]["summary"])
        new_summary = dict(by_delay[new_label]["summary"])
        comparisons.append(
            {
                "policy_name": base_policy.name,
                "old": old_summary,
                "new": new_summary,
                "delta_new_minus_old": _delta(new_summary, old_summary),
            }
        )

    output = {
        "schema_version": "micro_main_entry_timing_compare_v1",
        "generated_at": generated_at.isoformat(),
        "scope": {
            "symbols": symbols,
            "days": int(args.days),
            "start_ts": start_ts.isoformat(),
            "end_ts": end_ts.isoformat(),
            "old_delay_minutes": int(args.old_delay_minutes),
            "new_delay_minutes": int(args.new_delay_minutes),
            "policy_names": policy_names,
            "notes": [
                "old_delay_minutes=0 reproduces the prior same-5m-bar entry search timing",
                "new_delay_minutes=5 allows 1m entry search only after the completed 5m setup candle is actionable",
                "both timings use the same fetched 1m candles, same symbols, same policies, and same fee model",
            ],
        },
        "data_status": data_status,
        "policy_results": policy_results,
        "comparisons": comparisons,
    }
    if args.write_report:
        out_dir = ROOT_DIR / str(args.report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"micro_main_entry_timing_compare_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
        atomic_write_text(out_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))
        output["report_path"] = str(out_path.relative_to(ROOT_DIR))
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
