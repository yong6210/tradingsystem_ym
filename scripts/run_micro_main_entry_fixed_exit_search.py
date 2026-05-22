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
    MicroSignal,
    MicroTrade,
    SessionImpulseRetestExitPolicy,
    SessionImpulseRetestResearch,
    session_impulse_retest_profile_for_symbol,
)
from app.services.report_io import atomic_write_text
from scripts.run_micro_main_exit_policy_search import _csv, _trade_row, build_exit_policies, summarize_rows
from scripts.run_micro_main_usdt_proxy_backtest import _fetch_1m_klines, _resample_to_5m


BASELINE_POLICY_NAME = "legacy_full_2r"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search exit policies while keeping the original session_impulse_retest entries fixed."
    )
    parser.add_argument("--symbols", default=CURRENT_MICRO_LIVE_USDT_SYMBOLS)
    parser.add_argument(
        "--contract-path",
        action="append",
        default=[],
        help="Paper/live filter contract path. Can be repeated or comma-separated.",
    )
    parser.add_argument("--days", type=int, default=1095)
    parser.add_argument("--max-policies", type=int, default=0)
    parser.add_argument("--policy-names", default="")
    parser.add_argument("--baseline-policy-name", default=BASELINE_POLICY_NAME)
    parser.add_argument("--entry-delay-minutes", type=int, default=5)
    parser.add_argument("--trade-count-floor-ratio", type=float, default=0.98)
    parser.add_argument("--top-limit", type=int, default=50)
    parser.add_argument("--report-dir", default="reports/validation/micro_main_entry_fixed_exit_search")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--include-trades", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed == parsed else default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _resolve_path(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


def _csv_contract_paths(values: list[str]) -> list[Path]:
    out: list[Path] = []
    seen: set[Path] = set()
    for value in values or []:
        for raw in str(value or "").split(","):
            if not raw.strip():
                continue
            path = _resolve_path(raw.strip())
            if path not in seen:
                out.append(path)
                seen.add(path)
    return out


def _load_signal_contracts(paths: list[Path]) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        paper_contract = dict(payload.get("paper_contract") or payload)
        symbols = {
            str(symbol).strip().upper()
            for symbol in list(paper_contract.get("symbols") or [])
            if str(symbol).strip()
        }
        contracts.append(
            {
                "path": str(path.relative_to(ROOT_DIR) if path.is_relative_to(ROOT_DIR) else path),
                "policy_name": paper_contract.get("policy_name"),
                "exit_policy_name": paper_contract.get("exit_policy_name"),
                "symbols": sorted(symbols),
                "filter_contract": dict(paper_contract.get("filter_contract") or {}),
            }
        )
    return contracts


def _passes_signal_contract(signal: MicroSignal, *, symbol: str, contract: dict[str, Any]) -> bool:
    symbols = {str(item).strip().upper() for item in list(contract.get("symbols") or []) if str(item).strip()}
    if symbols and str(symbol or "").strip().upper() not in symbols:
        return False

    filter_contract = dict(contract.get("filter_contract") or {})
    diagnostics = dict(signal.diagnostics or {})

    expected_direction = str(filter_contract.get("direction") or "").strip().lower()
    if expected_direction and expected_direction != "both" and str(signal.direction).strip().lower() != expected_direction:
        return False

    allowed_hours = {_safe_int(hour, -1) for hour in list(filter_contract.get("setup_hour_utc") or [])}
    if allowed_hours and _safe_int(diagnostics.get("setup_hour_utc"), -1) not in allowed_hours:
        return False

    min_volume_factor = filter_contract.get("min_volume_factor")
    if min_volume_factor is not None and _safe_float(diagnostics.get("volume_factor")) < _safe_float(min_volume_factor):
        return False

    min_reclaim_body_atr = filter_contract.get("min_reclaim_body_atr")
    if (
        min_reclaim_body_atr is not None
        and _safe_float(diagnostics.get("reclaim_body_atr")) < _safe_float(min_reclaim_body_atr)
    ):
        return False

    min_risk_atr = filter_contract.get("min_risk_atr")
    if min_risk_atr is not None and _safe_float(diagnostics.get("risk_atr")) < _safe_float(min_risk_atr):
        return False

    max_risk_atr = filter_contract.get("max_risk_atr")
    if max_risk_atr is not None and _safe_float(diagnostics.get("risk_atr")) > _safe_float(max_risk_atr):
        return False

    max_retest_wait_minutes = filter_contract.get("max_retest_wait_minutes")
    if (
        max_retest_wait_minutes is not None
        and _safe_float(diagnostics.get("retest_wait_minutes")) > _safe_float(max_retest_wait_minutes)
    ):
        return False

    max_entry_distance_atr = filter_contract.get("max_entry_distance_atr")
    if (
        max_entry_distance_atr is not None
        and _safe_float(diagnostics.get("entry_distance_atr")) > _safe_float(max_entry_distance_atr)
    ):
        return False

    return True


def _filter_base_signals(
    *,
    symbol: str,
    base_signals: list[MicroSignal],
    signal_contracts: list[dict[str, Any]],
) -> tuple[list[MicroSignal], dict[str, int]]:
    if not signal_contracts:
        return list(base_signals), {}
    selected: list[MicroSignal] = []
    matched_by_contract = {str(contract.get("path") or idx): 0 for idx, contract in enumerate(signal_contracts)}
    for signal in base_signals:
        for idx, contract in enumerate(signal_contracts):
            key = str(contract.get("path") or idx)
            if _passes_signal_contract(signal, symbol=symbol, contract=contract):
                matched_by_contract[key] = matched_by_contract.get(key, 0) + 1
                selected.append(signal)
                break
    return selected, matched_by_contract


def _entry_fixed_policy(
    policy: SessionImpulseRetestExitPolicy,
    *,
    entry_delay_minutes: int = 5,
) -> SessionImpulseRetestExitPolicy:
    return replace(
        policy,
        entry_confirmation_delay_minutes=max(int(entry_delay_minutes), 0),
        structure_entry_max_distance_atr=0.0,
        higher_timeframe_entry_min_score=0.0,
        max_stop_pct=0.0,
        max_risk_atr=0.0,
    )


def _select_policies(
    policy_names: str,
    max_policies: int,
    *,
    entry_delay_minutes: int = 5,
) -> list[SessionImpulseRetestExitPolicy]:
    policies = [
        _entry_fixed_policy(policy, entry_delay_minutes=entry_delay_minutes) for policy in build_exit_policies()
    ]
    if policy_names.strip():
        wanted: list[str] = []
        seen: set[str] = set()
        for raw in str(policy_names or "").split(","):
            item = raw.strip()
            if item and item not in seen:
                wanted.append(item)
                seen.add(item)
        by_name = {policy.name: policy for policy in policies}
        missing = [name for name in wanted if name not in by_name]
        if missing:
            raise SystemExit(f"unknown policies: {','.join(missing)}")
        policies = [by_name[name] for name in wanted]
    if max_policies > 0:
        policies = policies[:max_policies]
    return policies


def _collect_base_signals(engine: SessionImpulseRetestResearch) -> list[MicroSignal]:
    signals: list[MicroSignal] = []
    if len(engine.candles_5m) < 80 or len(engine.candles_1m) < 600:
        return signals
    idx = 60
    while idx < len(engine.candles_5m) - 2:
        signal = engine._build_signal(idx)
        if signal is not None:
            signals.append(signal)
        idx += 1
    return signals


def _simulate_policy(
    engine: SessionImpulseRetestResearch,
    *,
    policy: SessionImpulseRetestExitPolicy,
    base_signals: list[MicroSignal],
    structure_context_cache: dict[tuple[Any, ...], dict[str, Any]] | None = None,
) -> tuple[list[MicroTrade], int]:
    previous_policy = engine.exit_policy
    engine.exit_policy = policy
    trades: list[MicroTrade] = []
    rejected = 0
    try:
        for signal in base_signals:
            candidate_signal = signal
            if (
                (policy.higher_timeframe_structure_enabled or policy.important_zone_exit_enabled)
                and not dict(signal.diagnostics or {}).get("htf_structure_enabled")
            ):
                setup_idx = engine._index_5m_by_ts.get(engine._normalize_ts(signal.setup_ts))
                if setup_idx is not None:
                    atr = max(float(engine.atr_5m[setup_idx]), 1e-9)
                    cache_key = (
                        int(policy.higher_timeframe_lookback_days),
                        bool(policy.higher_timeframe_target_enabled),
                        bool(policy.higher_timeframe_stop_enabled),
                        signal.direction,
                        signal.setup_ts.isoformat(),
                        round(float(signal.entry_price), 8),
                        round(float(atr), 8),
                    )
                    cache = structure_context_cache if structure_context_cache is not None else {}
                    context = cache.get(cache_key)
                    if context is None:
                        context = engine._higher_timeframe_structure_context(
                            setup_idx=setup_idx,
                            direction=signal.direction,
                            entry_price=float(signal.entry_price),
                            atr=atr,
                        )
                        cache[cache_key] = context
                    candidate_signal = replace(signal, diagnostics={**dict(signal.diagnostics or {}), **context})
            adjusted = engine._apply_exit_policy(candidate_signal)
            if adjusted is None:
                rejected += 1
                continue
            trade = engine._simulate_trade(adjusted)
            if trade is not None:
                trades.append(trade)
    finally:
        engine.exit_policy = previous_policy
    return trades, rejected


def _cost_stress(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_r = sum(_safe_float(row.get("r_value")) for row in rows)
    gross_r = sum(_safe_float(row.get("gross_r")) for row in rows)
    cost_r = sum(_safe_float(row.get("cost_r")) for row in rows)
    closed = len(rows)
    return {
        "extra_0_05r_per_trade": {
            "total_r": round(total_r - 0.05 * closed, 4),
            "ev_r": round((total_r - 0.05 * closed) / max(closed, 1), 4),
        },
        "cost_x2_0": {
            "total_r": round(gross_r - 2.0 * cost_r, 4),
            "ev_r": round((gross_r - 2.0 * cost_r) / max(closed, 1), 4),
        },
        "cost_x2_0_extra_0_03r_per_trade": {
            "total_r": round(gross_r - 2.0 * cost_r - 0.03 * closed, 4),
            "ev_r": round((gross_r - 2.0 * cost_r - 0.03 * closed) / max(closed, 1), 4),
        },
    }


def _rank_key(row: dict[str, Any]) -> tuple[float, float, float, float]:
    summary = dict(row.get("summary") or {})
    cost_stress = dict(row.get("cost_stress") or {})
    cost_x2 = dict(cost_stress.get("cost_x2_0") or {})
    return (
        _safe_float(summary.get("score")),
        _safe_float(summary.get("total_r")),
        _safe_float(cost_x2.get("total_r")),
        _safe_float(summary.get("ev_r")),
    )


def _total_key(row: dict[str, Any]) -> tuple[float, float, float]:
    summary = dict(row.get("summary") or {})
    return (
        _safe_float(summary.get("total_r")),
        _safe_float(summary.get("ev_r")),
        -_safe_float(summary.get("max_dd_r")),
    )


def _policy_short(policy: SessionImpulseRetestExitPolicy) -> dict[str, Any]:
    payload = asdict(policy)
    return {
        key: value
        for key, value in payload.items()
        if value not in (None, False, 0, 0.0, "")
        or key in {"name", "stop_mode", "target_rr", "max_hold_minutes", "entry_confirmation_delay_minutes"}
    }


def _run_symbol(
    *,
    monthly_client: httpx.Client,
    rest_client: httpx.Client,
    symbol: str,
    start_ts: datetime,
    end_ts: datetime,
    policies: list[SessionImpulseRetestExitPolicy],
    entry_delay_minutes: int,
    baseline_policy_name: str,
    signal_contracts: list[dict[str, Any]],
    rows_by_policy: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    candles_1m = _fetch_1m_klines(monthly_client, rest_client, symbol=symbol, start_ts=start_ts, end_ts=end_ts)
    candles_5m = _resample_to_5m(candles_1m)
    status: dict[str, Any] = {
        "candles_1m": len(candles_1m),
        "candles_5m": len(candles_5m),
        "first_1m_ts": candles_1m[0].ts.isoformat() if candles_1m else None,
        "last_1m_ts": candles_1m[-1].ts.isoformat() if candles_1m else None,
        "base_signal_count": 0,
    }
    if len(candles_1m) < 600 or len(candles_5m) < 200:
        status["status"] = "insufficient_candles"
        return status

    engine = SessionImpulseRetestResearch(
        symbol=symbol,
        candles_1m=candles_1m,
        candles_5m=candles_5m,
        profile_name=session_impulse_retest_profile_for_symbol(symbol),
        exit_policy=SessionImpulseRetestExitPolicy(
            name=baseline_policy_name,
            entry_confirmation_delay_minutes=max(int(entry_delay_minutes), 0),
        ),
    )
    raw_base_signals = _collect_base_signals(engine)
    base_signals, matched_by_contract = _filter_base_signals(
        symbol=symbol,
        base_signals=raw_base_signals,
        signal_contracts=signal_contracts,
    )
    status["raw_base_signal_count"] = len(raw_base_signals)
    status["base_signal_count"] = len(base_signals)
    status["contract_matched_signal_count"] = matched_by_contract
    status["status"] = "done"
    status["policy_rejected_signals"] = {}
    structure_context_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
    for policy in policies:
        trades, rejected = _simulate_policy(
            engine,
            policy=policy,
            base_signals=base_signals,
            structure_context_cache=structure_context_cache,
        )
        status["policy_rejected_signals"][policy.name] = rejected
        rows_by_policy[policy.name].extend(_trade_row(trade, policy=policy) for trade in trades)
    return status


def build_report(
    *,
    symbols: list[str],
    days: int,
    policies: list[SessionImpulseRetestExitPolicy],
    generated_at: datetime,
    start_ts: datetime,
    end_ts: datetime,
    data_status: dict[str, Any],
    rows_by_policy: dict[str, list[dict[str, Any]]],
    trade_count_floor_ratio: float,
    top_limit: int,
    include_trades: bool,
    signal_contracts: list[dict[str, Any]],
    baseline_policy_name: str = BASELINE_POLICY_NAME,
    entry_delay_minutes: int = 5,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for policy in policies:
        rows = rows_by_policy.get(policy.name, [])
        item: dict[str, Any] = {
            "policy": _policy_short(policy),
            "summary": summarize_rows(rows),
            "cost_stress": _cost_stress(rows),
            "trade_count_by_symbol": {
                symbol: sum(1 for row in rows if str(row.get("symbol") or "") == symbol) for symbol in symbols
            },
            "rejected_signal_count": sum(
                _safe_int(dict(status.get("policy_rejected_signals") or {}).get(policy.name))
                for status in data_status.values()
                if isinstance(status, dict)
            ),
        }
        if include_trades:
            item["trades"] = rows
        results.append(item)

    baseline = next((row for row in results if dict(row.get("policy") or {}).get("name") == baseline_policy_name), None)
    baseline_closed = _safe_int(dict((baseline or {}).get("summary") or {}).get("closed"))
    floor = int(max(0.0, min(float(trade_count_floor_ratio), 1.0)) * max(baseline_closed, 1))
    same_entry_results = [row for row in results if _safe_int(dict(row.get("summary") or {}).get("closed")) >= floor]
    better_than_baseline: list[dict[str, Any]] = []
    if baseline is not None:
        baseline_summary = dict(baseline.get("summary") or {})
        baseline_total = _safe_float(baseline_summary.get("total_r"))
        baseline_score = _safe_float(baseline_summary.get("score"))
        baseline_cost_x2 = _safe_float(dict(dict(baseline.get("cost_stress") or {}).get("cost_x2_0") or {}).get("total_r"))
        for row in same_entry_results:
            summary = dict(row.get("summary") or {})
            cost_x2 = _safe_float(dict(dict(row.get("cost_stress") or {}).get("cost_x2_0") or {}).get("total_r"))
            if (
                _safe_float(summary.get("total_r")) > baseline_total
                or _safe_float(summary.get("score")) > baseline_score
                or cost_x2 > baseline_cost_x2
            ):
                better_than_baseline.append(row)

    return {
        "schema_version": "micro_main_entry_fixed_exit_search_v1",
        "generated_at": generated_at.isoformat(),
        "scope": {
            "symbols": symbols,
            "days": int(days),
            "start_ts": start_ts.isoformat(),
            "end_ts": end_ts.isoformat(),
            "policy_count": len(policies),
            "baseline_policy_name": baseline_policy_name,
            "entry_delay_minutes": max(int(entry_delay_minutes), 0),
            "filter_contracts": signal_contracts,
            "trade_count_floor_ratio": float(trade_count_floor_ratio),
            "trade_count_floor": floor,
            "notes": [
                "Original session_impulse_retest entries are collected once with the configured actionable entry delay.",
                "Each candidate then reuses exactly those entries and changes only stop, target, time-exit, partial-exit, and position-management behavior.",
                "Entry-distance, higher-timeframe score, max stop, and max risk rejection fields are disabled in this report so a TP/SL candidate cannot look better by silently removing entries.",
                "Same-minute stop and target collision is still treated as stop-first.",
            ],
        },
        "data_status": data_status,
        "baseline": baseline,
        "top_by_score_same_entry": sorted(same_entry_results, key=_rank_key, reverse=True)[:top_limit],
        "top_by_total_r_same_entry": sorted(same_entry_results, key=_total_key, reverse=True)[:top_limit],
        "better_than_baseline_same_entry": sorted(better_than_baseline, key=_rank_key, reverse=True)[:top_limit],
        "all_results": results,
    }


def main() -> int:
    args = _parse_args()
    generated_at = datetime.now(UTC)
    settings = get_settings()
    symbols = _csv(args.symbols)
    contract_paths = _csv_contract_paths(list(args.contract_path or []))
    signal_contracts = _load_signal_contracts(contract_paths)
    baseline_policy_name = str(args.baseline_policy_name or BASELINE_POLICY_NAME).strip() or BASELINE_POLICY_NAME
    entry_delay_minutes = max(int(args.entry_delay_minutes), 0)
    policies = _select_policies(
        str(args.policy_names or ""),
        int(args.max_policies or 0),
        entry_delay_minutes=entry_delay_minutes,
    )
    if baseline_policy_name not in {policy.name for policy in policies}:
        policies = [
            SessionImpulseRetestExitPolicy(
                name=baseline_policy_name,
                entry_confirmation_delay_minutes=entry_delay_minutes,
            ),
            *policies,
        ]
    end_ts = datetime.now(UTC).replace(second=0, microsecond=0)
    start_ts = end_ts - timedelta(days=max(int(args.days), 1))
    rows_by_policy: dict[str, list[dict[str, Any]]] = {policy.name: [] for policy in policies}
    data_status: dict[str, Any] = {}

    with (
        httpx.Client(timeout=120.0, follow_redirects=True) as monthly_client,
        httpx.Client(base_url=settings.binance_rest_base_url, timeout=30.0) as rest_client,
    ):
        for symbol in symbols:
            status = _run_symbol(
                monthly_client=monthly_client,
                rest_client=rest_client,
                symbol=symbol,
                start_ts=start_ts,
                end_ts=end_ts,
                policies=policies,
                rows_by_policy=rows_by_policy,
                entry_delay_minutes=entry_delay_minutes,
                baseline_policy_name=baseline_policy_name,
                signal_contracts=signal_contracts,
            )
            data_status[symbol] = status
            print(
                json.dumps(
                    {
                        "symbol": symbol,
                        "status": status.get("status"),
                        "raw_base_signal_count": status.get("raw_base_signal_count"),
                        "base_signal_count": status.get("base_signal_count"),
                        "candles_1m": status.get("candles_1m"),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
                flush=True,
            )

    output = build_report(
        symbols=symbols,
        days=int(args.days),
        policies=policies,
        generated_at=generated_at,
        start_ts=start_ts,
        end_ts=end_ts,
        data_status=data_status,
        rows_by_policy=rows_by_policy,
        trade_count_floor_ratio=float(args.trade_count_floor_ratio),
        top_limit=int(args.top_limit),
        include_trades=bool(args.include_trades),
        signal_contracts=signal_contracts,
        baseline_policy_name=baseline_policy_name,
        entry_delay_minutes=entry_delay_minutes,
    )
    if args.write_report:
        out_dir = ROOT_DIR / str(args.report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"micro_main_entry_fixed_exit_search_{generated_at.strftime('%Y%m%dT%H%M%S%fZ')}.json"
        atomic_write_text(out_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))
        latest_path = out_dir / "latest.json"
        atomic_write_text(latest_path, json.dumps(output, ensure_ascii=False, indent=2, default=str))
        output["report_path"] = str(out_path.relative_to(ROOT_DIR))
    if not args.quiet:
        print(json.dumps({key: value for key, value in output.items() if key != "all_results"}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
