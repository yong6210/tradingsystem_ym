#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.micro_main_strategy_research import MicroSignal, session_impulse_retest_profile_for_symbol
from app.services.report_io import atomic_write_text
from scripts.run_micro_intrabar_paper_candidate_contract import (
    DEFAULT_EXIT_POLICY_NAME,
    FILTER_CONTRACTS,
)
from scripts.run_micro_main_exit_policy_search import build_exit_policies
from scripts.run_micro_main_intrabar_research import (
    SessionImpulseRetestResearch as IntrabarSessionImpulseRetestResearch,
    intrabar_exit_policy,
)
from scripts.run_micro_main_usdt_proxy_backtest import _fetch_1m_klines, _resample_to_5m


DEFAULT_CONTRACT_PATH = ROOT_DIR / "reports/operations/micro_intrabar_paper_candidate_contract/latest.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watch the micro intrabar paper-only candidate without submitting orders.")
    parser.add_argument("--contract-path", default=str(DEFAULT_CONTRACT_PATH))
    parser.add_argument("--symbols", default="", help="Optional comma-separated symbol override for watch-only scans.")
    parser.add_argument(
        "--symbols-from-expansion-review",
        default="",
        help="Optional expansion review JSON path; uses its shadow_watchlist_symbols as the watch-only symbol override.",
    )
    parser.add_argument("--watch-label", default="primary_paper_candidate")
    parser.add_argument("--lookback-hours", type=int, default=72)
    parser.add_argument("--scan-hours", type=int, default=24)
    parser.add_argument("--freshness-minutes", type=int, default=20)
    parser.add_argument("--report-dir", default="reports/operations/micro_intrabar_paper_candidate_watch")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _resolve_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


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


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _csv_symbols(value: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in str(value or "").split(","):
        symbol = raw.strip().upper()
        if symbol and symbol not in seen:
            out.append(symbol)
            seen.add(symbol)
    return out


def _symbols_from_expansion_review(path: Path) -> list[str]:
    payload = _load_json(path)
    return [
        str(symbol).strip().upper()
        for symbol in list(payload.get("shadow_watchlist_symbols") or [])
        if str(symbol).strip()
    ]


def _report_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def _select_exit_policy(name: str):
    policies = {policy.name: policy for policy in build_exit_policies()}
    if name not in policies:
        raise ValueError(f"unknown exit policy: {name}")
    return intrabar_exit_policy(policies[name])


def _passes_filter_contract(signal: MicroSignal, filter_contract: dict[str, Any]) -> tuple[bool, list[str]]:
    diagnostics = dict(signal.diagnostics or {})
    reasons: list[str] = []
    expected_direction = str(filter_contract.get("direction") or "").strip().lower()
    if expected_direction and expected_direction != "both" and str(signal.direction).lower() != expected_direction:
        reasons.append("direction_mismatch")
    allowed_hours = {_safe_int(hour, -1) for hour in list(filter_contract.get("setup_hour_utc") or [])}
    if allowed_hours and _safe_int(diagnostics.get("setup_hour_utc"), -1) not in allowed_hours:
        reasons.append("setup_hour_not_allowed")
    min_volume_factor = filter_contract.get("min_volume_factor")
    if min_volume_factor is not None and _safe_float(diagnostics.get("volume_factor")) < _safe_float(min_volume_factor):
        reasons.append("volume_factor_below_contract")
    min_reclaim_body_atr = filter_contract.get("min_reclaim_body_atr")
    if min_reclaim_body_atr is not None and _safe_float(diagnostics.get("reclaim_body_atr")) < _safe_float(min_reclaim_body_atr):
        reasons.append("reclaim_body_atr_below_contract")
    min_risk_atr = filter_contract.get("min_risk_atr")
    if min_risk_atr is not None and _safe_float(diagnostics.get("risk_atr")) < _safe_float(min_risk_atr):
        reasons.append("risk_atr_below_contract")
    max_risk_atr = filter_contract.get("max_risk_atr")
    if max_risk_atr is not None and _safe_float(diagnostics.get("risk_atr")) > _safe_float(max_risk_atr):
        reasons.append("risk_atr_above_contract")
    max_retest_wait_minutes = filter_contract.get("max_retest_wait_minutes")
    if max_retest_wait_minutes is not None and _safe_float(diagnostics.get("retest_wait_minutes")) > _safe_float(max_retest_wait_minutes):
        reasons.append("retest_wait_above_contract")
    max_entry_distance_atr = filter_contract.get("max_entry_distance_atr")
    if max_entry_distance_atr is not None and _safe_float(diagnostics.get("entry_distance_atr")) > _safe_float(max_entry_distance_atr):
        reasons.append("entry_distance_atr_above_contract")
    return not reasons, reasons


def _round_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    rounded: dict[str, Any] = {}
    for key, value in sorted(diagnostics.items()):
        if isinstance(value, float):
            rounded[key] = round(value, 8)
        else:
            rounded[key] = value
    return rounded


def _signal_row(symbol: str, signal: MicroSignal, *, filter_reasons: list[str]) -> dict[str, Any]:
    risk_abs = abs(float(signal.entry_price) - float(signal.stop_price))
    return {
        "symbol": symbol,
        "family": signal.family,
        "direction": signal.direction,
        "signal_ts": signal.signal_ts.isoformat(),
        "setup_ts": signal.setup_ts.isoformat(),
        "entry_ts": signal.entry_ts.isoformat(),
        "entry_price": round(float(signal.entry_price), 8),
        "stop_price": round(float(signal.stop_price), 8),
        "target_price": round(float(signal.target_price), 8),
        "risk_pct": round(risk_abs / max(float(signal.entry_price), 1e-9), 8),
        "max_hold_minutes": signal.max_hold_minutes,
        "filter_pass": not filter_reasons,
        "filter_reasons": filter_reasons,
        "diagnostics": _round_diagnostics(dict(signal.diagnostics or {})),
    }


def _collect_symbol_signals(
    *,
    symbol: str,
    engine: IntrabarSessionImpulseRetestResearch,
    scan_start_ts: datetime,
    filter_contract: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_signal_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    if len(engine.candles_5m) < 80 or len(engine.candles_1m) < 600:
        return all_signal_rows, candidate_rows
    start_ts = max(engine.ts_5m[60], scan_start_ts - timedelta(hours=8))
    idx = max(engine._index_1m_by_ts.get(start_ts.replace(second=0, microsecond=0), 0), 0)
    used_setup_buckets: set[datetime] = set()
    while idx < len(engine.candles_1m) - 2:
        partial_bar = engine._partial_5m_bar(idx)
        if partial_bar is None:
            idx += 1
            continue
        bucket_ts = partial_bar["bucket_ts"]
        if bucket_ts in used_setup_buckets:
            idx += 1
            continue
        signal = engine._build_intrabar_signal(idx)
        if signal is None:
            idx += 1
            continue
        used_setup_buckets.add(bucket_ts)
        passed, reasons = _passes_filter_contract(signal, filter_contract)
        row = _signal_row(symbol, signal, filter_reasons=reasons)
        if signal.entry_ts >= scan_start_ts:
            all_signal_rows.append(row)
            if passed:
                candidate_rows.append(row)
        idx += 1
    return all_signal_rows, candidate_rows


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_symbol: dict[str, int] = {}
    by_hour: dict[str, int] = {}
    by_direction: dict[str, int] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "UNKNOWN")
        direction = str(row.get("direction") or "unknown")
        diagnostics = dict(row.get("diagnostics") or {})
        hour = str(diagnostics.get("setup_hour_utc", "unknown"))
        by_symbol[symbol] = by_symbol.get(symbol, 0) + 1
        by_direction[direction] = by_direction.get(direction, 0) + 1
        by_hour[hour] = by_hour.get(hour, 0) + 1
    return {
        "count": len(rows),
        "by_symbol": dict(sorted(by_symbol.items())),
        "by_direction": dict(sorted(by_direction.items())),
        "by_setup_hour_utc": dict(sorted(by_hour.items())),
    }


def build_payload(
    contract_path: Path,
    *,
    generated_at: datetime | None = None,
    lookback_hours: int = 72,
    scan_hours: int = 24,
    freshness_minutes: int = 20,
    symbols_override: list[str] | None = None,
    symbol_source: str = "contract",
    watch_label: str = "primary_paper_candidate",
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    contract_payload = _load_json(contract_path)
    paper_contract = dict(contract_payload.get("paper_contract") or {})
    filter_contract = dict(paper_contract.get("filter_contract") or {})
    symbols = [str(symbol).strip().upper() for symbol in list(paper_contract.get("symbols") or []) if str(symbol).strip()]
    if symbols_override is not None:
        symbols = [str(symbol).strip().upper() for symbol in symbols_override if str(symbol).strip()]
    if not symbols:
        raise ValueError("paper contract has no symbols")
    if not filter_contract:
        filter_contract = FILTER_CONTRACTS.get(str(paper_contract.get("policy_name") or ""), {})
    exit_policy_name = str(paper_contract.get("exit_policy_name") or DEFAULT_EXIT_POLICY_NAME)
    exit_policy = _select_exit_policy(exit_policy_name)
    end_ts = generated_at.replace(second=0, microsecond=0)
    fetch_start_ts = end_ts - timedelta(hours=max(int(lookback_hours), 12))
    scan_start_ts = end_ts - timedelta(hours=max(int(scan_hours), 1))
    fresh_cutoff_ts = end_ts - timedelta(minutes=max(int(freshness_minutes), 1))

    settings = get_settings()
    data_status: dict[str, Any] = {}
    all_signal_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    with (
        httpx.Client(timeout=120.0, follow_redirects=True) as monthly_client,
        httpx.Client(base_url=settings.binance_rest_base_url, timeout=30.0) as rest_client,
    ):
        for symbol in symbols:
            candles_1m = _fetch_1m_klines(
                monthly_client,
                rest_client,
                symbol=symbol,
                start_ts=fetch_start_ts,
                end_ts=end_ts,
            )
            candles_5m = _resample_to_5m(candles_1m)
            data_status[symbol] = {
                "candles_1m": len(candles_1m),
                "candles_5m": len(candles_5m),
                "first_1m_ts": candles_1m[0].ts.isoformat() if candles_1m else None,
                "last_1m_ts": candles_1m[-1].ts.isoformat() if candles_1m else None,
            }
            engine = IntrabarSessionImpulseRetestResearch(
                symbol=symbol,
                candles_1m=candles_1m,
                candles_5m=candles_5m,
                profile_name=session_impulse_retest_profile_for_symbol(symbol),
                exit_policy=exit_policy,
            )
            all_rows, matching_rows = _collect_symbol_signals(
                symbol=symbol,
                engine=engine,
                scan_start_ts=scan_start_ts,
                filter_contract=filter_contract,
            )
            all_signal_rows.extend(all_rows)
            candidate_rows.extend(matching_rows)

    all_signal_rows.sort(key=lambda row: str(row.get("entry_ts") or ""), reverse=True)
    candidate_rows.sort(key=lambda row: str(row.get("entry_ts") or ""), reverse=True)
    fresh_candidates = [
        row
        for row in candidate_rows
        if datetime.fromisoformat(str(row.get("entry_ts")).replace("Z", "+00:00")) >= fresh_cutoff_ts
    ]
    status = "PAPER_SIGNAL_READY" if fresh_candidates else "WATCHING"
    return {
        "schema_version": "micro_intrabar_paper_candidate_watch_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "paper_watch_only_no_order_submission",
        "contract_path": str(contract_path.relative_to(ROOT_DIR) if contract_path.is_relative_to(ROOT_DIR) else contract_path),
        "watch_label": str(watch_label or "primary_paper_candidate"),
        "symbol_source": str(symbol_source or "contract"),
        "recommended_state": "PAPER_ONLY_SHADOW_WATCH",
        "live_action": "KEEP_CLOSE_ONLY",
        "status": status,
        "reason": "fresh_candidate_available" if fresh_candidates else "no_fresh_candidate",
        "scope": {
            "symbols": symbols,
            "lookback_hours": int(lookback_hours),
            "scan_hours": int(scan_hours),
            "freshness_minutes": int(freshness_minutes),
            "fetch_start_ts": fetch_start_ts.isoformat(),
            "scan_start_ts": scan_start_ts.isoformat(),
            "fresh_cutoff_ts": fresh_cutoff_ts.isoformat(),
            "end_ts": end_ts.isoformat(),
            "exit_policy_name": exit_policy_name,
            "filter_contract": filter_contract,
        },
        "data_status": data_status,
        "summary": {
            "base_signals": _summarize_rows(all_signal_rows),
            "paper_candidates": _summarize_rows(candidate_rows),
            "fresh_paper_candidates": _summarize_rows(fresh_candidates),
        },
        "fresh_candidates": fresh_candidates,
        "latest_candidates": candidate_rows[:20],
        "latest_base_signals": all_signal_rows[:20],
        "contract_snapshot": {
            "policy_name": paper_contract.get("policy_name"),
            "candidate": contract_payload.get("candidate") or {},
            "promotion_gates": contract_payload.get("promotion_gates") or {},
            "risk_notes": contract_payload.get("risk_notes") or [],
        },
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    scope = dict(payload.get("scope") or {})
    summary = dict(payload.get("summary") or {})
    paper_summary = dict(summary.get("paper_candidates") or {})
    fresh_summary = dict(summary.get("fresh_paper_candidates") or {})
    lines = [
        "# Micro Intrabar Paper Candidate Watch",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- authority: {payload.get('authority')}",
        f"- watch_label: {payload.get('watch_label')}",
        f"- symbol_source: {payload.get('symbol_source')}",
        f"- status: {payload.get('status')}",
        f"- reason: {payload.get('reason')}",
        f"- live_action: {payload.get('live_action')}",
        f"- symbols: {','.join(list(scope.get('symbols') or []))}",
        f"- scan_hours: {scope.get('scan_hours')}",
        f"- exit_policy_name: {scope.get('exit_policy_name')}",
        f"- paper_candidates: {paper_summary.get('count')}",
        f"- fresh_paper_candidates: {fresh_summary.get('count')}",
        "",
        "This watcher does not submit orders.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    contract_path = _resolve_path(args.contract_path)
    generated_at = datetime.now(UTC)
    symbols_override = _csv_symbols(args.symbols)
    symbol_source = "cli_symbols" if symbols_override else "contract"
    if str(args.symbols_from_expansion_review or "").strip():
        expansion_path = _resolve_path(args.symbols_from_expansion_review)
        symbols_override = _symbols_from_expansion_review(expansion_path)
        symbol_source = str(expansion_path.relative_to(ROOT_DIR) if expansion_path.is_relative_to(ROOT_DIR) else expansion_path)
    payload = build_payload(
        contract_path,
        generated_at=generated_at,
        lookback_hours=args.lookback_hours,
        scan_hours=args.scan_hours,
        freshness_minutes=args.freshness_minutes,
        symbols_override=symbols_override or None,
        symbol_source=symbol_source,
        watch_label=args.watch_label,
    )
    if args.write_report:
        report_dir = _resolve_path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = _report_stamp(generated_at)
        json_path = report_dir / f"micro_intrabar_paper_candidate_watch_{stamp}.json"
        md_path = report_dir / f"micro_intrabar_paper_candidate_watch_{stamp}.md"
        latest_json = report_dir / "latest.json"
        latest_md = report_dir / "latest.md"
        payload["report_path"] = str(json_path.relative_to(ROOT_DIR) if json_path.is_relative_to(ROOT_DIR) else json_path)
        payload["latest_report_path"] = str(latest_json.relative_to(ROOT_DIR) if latest_json.is_relative_to(ROOT_DIR) else latest_json)
        atomic_write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(md_path, _render_markdown(payload))
        atomic_write_text(latest_json, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(latest_md, _render_markdown(payload))
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
