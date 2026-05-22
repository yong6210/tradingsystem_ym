#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import CURRENT_MICRO_LIVE_USDT_SYMBOLS, get_settings
from app.services.report_io import atomic_write_text
from scripts.run_micro_main_entry_fixed_exit_search import _csv_contract_paths, _load_signal_contracts
from scripts.run_micro_main_exit_policy_search import build_exit_policies
from scripts.run_micro_main_usdt_proxy_backtest import _build_loss_analysis, _run_symbol


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run direct USDT candle backtest for the micro main strategy.")
    parser.add_argument("--symbols", default=CURRENT_MICRO_LIVE_USDT_SYMBOLS)
    parser.add_argument("--days", type=int, default=1825)
    parser.add_argument("--exit-policy-name", default="")
    parser.add_argument(
        "--entry-timing-model",
        default="confirmed_5m_retest",
        choices=["confirmed_5m_retest", "intrabar_1m_confirm_next_open"],
    )
    parser.add_argument(
        "--contract-path",
        action="append",
        default=[],
        help="Paper/live signal filter contract path. Can be repeated or comma-separated.",
    )
    parser.add_argument("--include-trades", action="store_true")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--write-loss-analysis", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--loss-analysis-min-bucket-trades", type=int, default=12)
    parser.add_argument("--loss-analysis-min-negative-years", type=int, default=2)
    return parser.parse_args()


def _trade_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in results.values():
        if not isinstance(item, dict):
            continue
        for row in list(item.get("trades") or []):
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _first_exit_policy(results: dict[str, Any]) -> dict[str, Any]:
    for item in results.values():
        if not isinstance(item, dict):
            continue
        policy = item.get("exit_policy")
        if isinstance(policy, dict) and policy:
            return dict(policy)
    return {}


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    generated_at = datetime.now(UTC)
    symbols = [item.strip().upper() for item in str(args.symbols or "").split(",") if item.strip()]
    exit_policy_name = str(args.exit_policy_name or "").strip()
    entry_timing_model = str(args.entry_timing_model or "confirmed_5m_retest").strip().lower()
    exit_policy = None
    if exit_policy_name:
        policies = {policy.name: policy for policy in build_exit_policies()}
        exit_policy = policies.get(exit_policy_name)
        if exit_policy is None:
            raise SystemExit(f"unknown exit policy: {exit_policy_name}")
    if exit_policy is not None and entry_timing_model == "intrabar_1m_confirm_next_open":
        exit_policy = replace(exit_policy, entry_confirmation_delay_minutes=0)
    signal_contracts = _load_signal_contracts(_csv_contract_paths(list(args.contract_path or [])))
    results: dict[str, Any] = {}
    aggregate_closed = 0
    aggregate_total_r = 0.0

    out_path: Path | None = None
    if args.write_report:
        out_dir = Path(settings.validation_report_dir) / "micro_main_usdt_backtests"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"micro_main_usdt_backtest_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"

    with (
        httpx.Client(timeout=120.0, follow_redirects=True) as monthly_client,
        httpx.Client(base_url=settings.binance_rest_base_url, timeout=30.0) as rest_client,
    ):
        for symbol in symbols:
            try:
                result = _run_symbol(
                    monthly_client,
                    rest_client,
                    proxy_symbol=symbol,
                    canonical_symbol=symbol,
                    lookback_days=int(args.days),
                    exit_policy=exit_policy,
                    entry_timing_model=entry_timing_model,
                    signal_contracts=signal_contracts,
                    include_trades=bool(args.include_trades or args.write_loss_analysis),
                )
            except Exception as exc:
                if not args.continue_on_error:
                    raise
                result = {
                    "proxy_symbol": symbol,
                    "canonical_symbol": symbol,
                    "profile_name": "baseline",
                    "error": type(exc).__name__,
                    "error_message": str(exc),
                }
            results[symbol] = result
            summary = dict(result.get("summary") or {})
            aggregate_closed += int(summary.get("closed", 0) or 0)
            aggregate_total_r += float(summary.get("total_r", 0.0) or 0.0)
            print(
                json.dumps(
                    {
                        "progress": symbol,
                        "closed": int(summary.get("closed", 0) or 0),
                        "ev_r": float(summary.get("ev_r", 0.0) or 0.0),
                        "decision": summary.get("decision"),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
                flush=True,
            )
            if out_path is not None:
                partial_payload = {
                    "source": "micro_main_usdt_backtest",
                    "quote_asset": "USDT",
                    "generated_at": generated_at.isoformat(),
                    "days": int(args.days),
                    "symbols": symbols,
                    "entry_timing_model": entry_timing_model,
                    "signal_contracts": signal_contracts,
                    "exit_policy_name_requested": exit_policy_name or None,
                    "exit_policy": _first_exit_policy(results),
                    "results": results,
                    "aggregate": {
                        "closed": aggregate_closed,
                        "total_r": round(aggregate_total_r, 4),
                        "ev_r": round(aggregate_total_r / max(aggregate_closed, 1), 4),
                    },
                    "loss_analysis": _build_loss_analysis(
                        _trade_rows(results),
                        min_bucket_trades=int(args.loss_analysis_min_bucket_trades),
                        min_negative_years=int(args.loss_analysis_min_negative_years),
                    )
                    if args.write_loss_analysis
                    else None,
                    "report_path": str(out_path),
                    "status": "running",
                }
                atomic_write_text(out_path, json.dumps(partial_payload, ensure_ascii=False, indent=2))

    payload: dict[str, Any] = {
        "source": "micro_main_usdt_backtest",
        "quote_asset": "USDT",
        "generated_at": generated_at.isoformat(),
        "days": int(args.days),
        "symbols": symbols,
        "entry_timing_model": entry_timing_model,
        "signal_contracts": signal_contracts,
        "exit_policy_name_requested": exit_policy_name or None,
        "exit_policy": _first_exit_policy(results),
        "results": results,
        "aggregate": {
            "closed": aggregate_closed,
            "total_r": round(aggregate_total_r, 4),
            "ev_r": round(aggregate_total_r / max(aggregate_closed, 1), 4),
        },
    }
    if args.write_loss_analysis:
        payload["loss_analysis"] = _build_loss_analysis(
            _trade_rows(results),
            min_bucket_trades=int(args.loss_analysis_min_bucket_trades),
            min_negative_years=int(args.loss_analysis_min_negative_years),
        )
    if out_path is not None:
        payload["report_path"] = str(out_path)
        atomic_write_text(out_path, json.dumps(payload, ensure_ascii=False, indent=2))

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    del results
    gc.collect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
