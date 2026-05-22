#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.integrations.binance_futures import BinanceFuturesClient
from app.services.report_io import atomic_write_text
from scripts.review_micro_intrabar_candidate_replay import (
    _infer_intrabar_report_path,
    _load_trade_rows,
    _parse_ts,
    _passes_contract,
)
from scripts.run_micro_main_exit_policy_search import summarize_rows
from scripts.run_micro_main_intrabar_subset_report import _cost_stress
from scripts.run_micro_main_usdt_proxy_portfolio_yearly_replay import (
    PortfolioReplayTrade,
    _replay_window,
    _year_windows,
)


DEFAULT_PRIMARY_CONTRACT = ROOT_DIR / "reports/operations/micro_intrabar_paper_candidate_contract/latest.json"
DEFAULT_SHORT_CONTRACT = ROOT_DIR / "reports/operations/micro_intrabar_short_paper_candidate_contract/latest.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Review a paper-only portfolio mix built from multiple micro intrabar candidate contracts."
    )
    parser.add_argument(
        "--contract-path",
        action="append",
        default=[],
        help="Candidate contract path. Can be repeated or comma-separated.",
    )
    parser.add_argument("--intrabar-report-path", default="")
    parser.add_argument("--days", type=int, default=1825)
    parser.add_argument("--account-equity-usdt", default="170,1000")
    parser.add_argument("--risk-per-trade-pct", type=float, default=0.01)
    parser.add_argument("--usable-margin-fraction", type=float, default=0.85)
    parser.add_argument("--leverage-cap", type=float, default=10.0)
    parser.add_argument("--max-concurrent-positions", default="2")
    parser.add_argument("--report-dir", default="reports/operations/micro_intrabar_candidate_portfolio_mix_review")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _resolve_path(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


def _display_path(path: Path) -> str:
    return str(path.relative_to(ROOT_DIR) if path.is_relative_to(ROOT_DIR) else path)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if math.isfinite(parsed) else float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _csv_paths(values: list[str]) -> list[Path]:
    raw_values = values or [str(DEFAULT_PRIMARY_CONTRACT), str(DEFAULT_SHORT_CONTRACT)]
    out: list[Path] = []
    seen: set[Path] = set()
    for item in raw_values:
        for raw in str(item or "").split(","):
            if not raw.strip():
                continue
            path = _resolve_path(raw.strip())
            if path not in seen:
                out.append(path)
                seen.add(path)
    return out


def _csv_floats(raw: Any, *, default: list[float]) -> list[float]:
    out: list[float] = []
    for part in str(raw or "").split(","):
        if not part.strip():
            continue
        out.append(_safe_float(part))
    return out or list(default)


def _csv_ints(raw: Any, *, default: list[int]) -> list[int]:
    out: list[int] = []
    for part in str(raw or "").split(","):
        if not part.strip():
            continue
        out.append(_safe_int(part))
    return out or list(default)


def _report_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def _trade_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("symbol") or row.get("proxy_symbol") or "").upper(),
        str(row.get("direction") or "").lower(),
        str(row.get("entry_ts") or ""),
        str(row.get("policy") or ""),
    )


def _portfolio_trade(row: dict[str, Any]) -> PortfolioReplayTrade | None:
    entry_ts = _parse_ts(row.get("entry_ts"))
    exit_ts = _parse_ts(row.get("exit_ts"))
    if entry_ts is None or exit_ts is None:
        return None
    symbol = str(row.get("symbol") or row.get("proxy_symbol") or "").strip().upper()
    if not symbol:
        return None
    return PortfolioReplayTrade(
        symbol=symbol,
        proxy_symbol=symbol,
        entry_ts=entry_ts,
        exit_ts=exit_ts,
        entry_price=_safe_float(row.get("entry_price")),
        stop_price=_safe_float(row.get("stop_price")),
        r_value=_safe_float(row.get("r_value")),
    )


def _fetch_symbol_rules(symbols: list[str]) -> dict[str, dict[str, float]]:
    client = BinanceFuturesClient()
    rules: dict[str, dict[str, float]] = {}
    for symbol in symbols:
        item = client.fetch_symbol_trading_rules(symbol)
        rules[symbol] = {
            "quantity_step": float(item.quantity_step),
            "min_quantity": float(item.min_quantity),
        }
    return rules


def _summary_package(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "summary": summarize_rows(rows),
        "cost_stress": _cost_stress(rows),
    }


def _replay_package(
    rows: list[dict[str, Any]],
    *,
    symbol_rules: dict[str, dict[str, float]],
    days: int,
    account_equities: list[float],
    risk_per_trade_pct: float,
    usable_margin_fraction: float,
    leverage_cap: float,
    max_concurrent_positions_values: list[int],
) -> dict[str, Any]:
    trades = [trade for row in rows if (trade := _portfolio_trade(row)) is not None]
    if not trades:
        return {"trade_count": 0, "scenarios": []}
    end_ts = max(trade.exit_ts for trade in trades)
    windows = _year_windows(end_ts=end_ts, days=days)
    scenarios: list[dict[str, Any]] = []
    for equity in account_equities:
        for max_concurrent in max_concurrent_positions_values:
            by_year: dict[str, Any] = {}
            totals = {
                "raw_trades": 0,
                "accepted_trades": 0,
                "skipped_trades_concurrent": 0,
                "rejected_trades_min_qty": 0,
                "capped_trades": 0,
                "sum_yearly_return_pct": 0.0,
                "max_yearly_drawdown_pct": 0.0,
            }
            for label, window_start, window_end in windows:
                window_trades = [trade for trade in trades if window_start <= trade.entry_ts < window_end]
                replay = _replay_window(
                    trades=window_trades,
                    symbol_rules=symbol_rules,
                    account_equity_usdt=equity,
                    risk_per_trade_pct=risk_per_trade_pct,
                    usable_margin_fraction=usable_margin_fraction,
                    leverage_cap=leverage_cap,
                    max_concurrent_positions=max_concurrent,
                )
                by_year[label] = {
                    "window": {"start_ts": window_start.isoformat(), "end_ts": window_end.isoformat()},
                    "raw_trades": len(window_trades),
                    **replay,
                }
                totals["raw_trades"] += len(window_trades)
                totals["accepted_trades"] += _safe_int(replay.get("accepted_trades"))
                totals["skipped_trades_concurrent"] += _safe_int(replay.get("skipped_trades_concurrent"))
                totals["rejected_trades_min_qty"] += _safe_int(replay.get("rejected_trades_min_qty"))
                totals["capped_trades"] += _safe_int(replay.get("capped_trades"))
                totals["sum_yearly_return_pct"] += _safe_float(replay.get("return_pct"))
                totals["max_yearly_drawdown_pct"] = max(
                    totals["max_yearly_drawdown_pct"],
                    _safe_float(replay.get("max_drawdown_pct")),
                )
            full = _replay_window(
                trades=trades,
                symbol_rules=symbol_rules,
                account_equity_usdt=equity,
                risk_per_trade_pct=risk_per_trade_pct,
                usable_margin_fraction=usable_margin_fraction,
                leverage_cap=leverage_cap,
                max_concurrent_positions=max_concurrent,
            )
            scenarios.append(
                {
                    "account_equity_usdt": equity,
                    "risk_per_trade_pct": risk_per_trade_pct,
                    "usable_margin_fraction": usable_margin_fraction,
                    "leverage_cap": leverage_cap,
                    "max_concurrent_positions": max_concurrent,
                    "full_window": full,
                    "yearly_totals": {
                        **totals,
                        "sum_yearly_return_pct": round(totals["sum_yearly_return_pct"], 4),
                        "max_yearly_drawdown_pct": round(totals["max_yearly_drawdown_pct"], 4),
                    },
                    "by_year": by_year,
                }
            )
    return {"trade_count": len(trades), "scenarios": scenarios}


def _decision(combined: dict[str, Any], replay: dict[str, Any]) -> tuple[str, list[str]]:
    summary = dict(combined.get("summary") or {})
    stress = dict(combined.get("cost_stress") or {})
    extra_005 = dict(stress.get("extra_0_05r_per_trade") or {})
    cost_x2 = dict(stress.get("cost_x2_0") or {})
    blockers: list[str] = []
    warnings: list[str] = []
    if _safe_float(summary.get("total_r")) <= 0.0 or _safe_float(summary.get("ev_r")) <= 0.0:
        blockers.append("combined_base_non_positive")
    if _safe_float(extra_005.get("total_r")) <= 0.0:
        blockers.append("combined_extra_0_05r_non_positive")
    if _safe_float(cost_x2.get("total_r")) <= 0.0:
        blockers.append("combined_cost_x2_non_positive")
    if _safe_float(summary.get("positive_year_fraction")) < 0.75:
        blockers.append("combined_year_consistency_below_0_75")
    min_qty_rejections = 0
    skipped = 0
    for scenario in list(replay.get("scenarios") or []):
        totals = dict(scenario.get("yearly_totals") or {})
        min_qty_rejections += _safe_int(totals.get("rejected_trades_min_qty"))
        skipped += _safe_int(totals.get("skipped_trades_concurrent"))
    if min_qty_rejections > 0:
        blockers.append("portfolio_replay_has_min_quantity_rejections")
    if skipped > 0:
        warnings.append("portfolio_replay_skips_some_concurrent_signals")
    if blockers:
        return "PORTFOLIO_MIX_NOT_READY", blockers + warnings
    return "PORTFOLIO_MIX_PAPER_WATCH", ["combined_replay_supports_paper_watch"] + warnings


def _scenario_brief(scenario: dict[str, Any]) -> dict[str, Any]:
    totals = dict(scenario.get("yearly_totals") or {})
    full = dict(scenario.get("full_window") or {})
    raw = _safe_int(totals.get("raw_trades"))
    accepted = _safe_int(totals.get("accepted_trades"))
    accepted_ratio = float(accepted) / float(raw) if raw > 0 else 0.0
    return {
        "account_equity_usdt": _safe_float(scenario.get("account_equity_usdt")),
        "max_concurrent_positions": _safe_int(scenario.get("max_concurrent_positions")),
        "return_pct": round(_safe_float(full.get("return_pct")), 4),
        "max_drawdown_pct": round(_safe_float(full.get("max_drawdown_pct")), 4),
        "raw_trades": raw,
        "accepted_trades": accepted,
        "accepted_trade_ratio": round(accepted_ratio, 6),
        "skipped_trades_concurrent": _safe_int(totals.get("skipped_trades_concurrent")),
        "rejected_trades_min_qty": _safe_int(totals.get("rejected_trades_min_qty")),
    }


def _recommended_scenarios(replay: dict[str, Any]) -> list[dict[str, Any]]:
    scenarios = [dict(item) for item in list(replay.get("scenarios") or [])]
    by_equity: dict[float, list[dict[str, Any]]] = {}
    for scenario in scenarios:
        equity = _safe_float(scenario.get("account_equity_usdt"))
        by_equity.setdefault(equity, []).append(scenario)

    recommendations: list[dict[str, Any]] = []
    for equity, items in sorted(by_equity.items()):
        viable = [
            item
            for item in items
            if _safe_int(dict(item.get("yearly_totals") or {}).get("rejected_trades_min_qty")) == 0
        ] or items
        best = max(viable, key=lambda item: _safe_float(dict(item.get("full_window") or {}).get("return_pct")))
        best_return = _safe_float(dict(best.get("full_window") or {}).get("return_pct"))
        candidates: list[dict[str, Any]] = []
        for item in viable:
            brief = _scenario_brief(item)
            if (
                best_return <= 0.0
                or (
                    float(brief["return_pct"]) >= best_return * 0.98
                    and float(brief["accepted_trade_ratio"]) >= 0.99
                )
            ):
                candidates.append(item)
        chosen = min(candidates or [best], key=lambda item: _safe_int(item.get("max_concurrent_positions")))
        chosen_brief = _scenario_brief(chosen)
        recommendations.append(
            {
                **chosen_brief,
                "best_return_pct": round(best_return, 4),
                "reason": (
                    "smallest_capacity_with_near_best_return"
                    if chosen is not best
                    else "best_return_scenario"
                ),
            }
        )
    return recommendations


def build_payload(
    contract_paths: list[Path],
    *,
    intrabar_report_path: Path | None = None,
    days: int = 1825,
    account_equities: list[float] | None = None,
    risk_per_trade_pct: float = 0.01,
    usable_margin_fraction: float = 0.85,
    leverage_cap: float = 10.0,
    max_concurrent_positions_values: list[int] | None = None,
    symbol_rules: dict[str, dict[str, float]] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    account_equities = list(account_equities or [170.0, 1000.0])
    max_concurrent_positions_values = list(max_concurrent_positions_values or [2])
    contract_paths = list(contract_paths)
    if not contract_paths:
        contract_paths = [DEFAULT_PRIMARY_CONTRACT, DEFAULT_SHORT_CONTRACT]
    contracts = [_load_json(path) for path in contract_paths]
    if intrabar_report_path is None:
        intrabar_report_path = _infer_intrabar_report_path(contracts[0])
    _, raw_rows = _load_trade_rows(intrabar_report_path)

    per_contract: list[dict[str, Any]] = []
    combined_rows_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    duplicate_trade_count = 0
    for path, contract in zip(contract_paths, contracts, strict=True):
        paper_contract = dict(contract.get("paper_contract") or {})
        rows = [row for row in raw_rows if _passes_contract(row, paper_contract)]
        for row in rows:
            key = _trade_key(row)
            if key in combined_rows_by_key:
                duplicate_trade_count += 1
                continue
            item = dict(row)
            item["_source_contract_policy"] = paper_contract.get("policy_name")
            combined_rows_by_key[key] = item
        per_contract.append(
            {
                "path": _display_path(path),
                "policy_name": paper_contract.get("policy_name"),
                "symbols": paper_contract.get("symbols") or [],
                "filter_contract": paper_contract.get("filter_contract") or {},
                **_summary_package(rows),
            }
        )

    combined_rows = sorted(
        combined_rows_by_key.values(),
        key=lambda row: (_parse_ts(row.get("entry_ts")) or datetime.min.replace(tzinfo=UTC), str(row.get("symbol") or "")),
    )
    symbols = sorted({str(row.get("symbol") or "").upper() for row in combined_rows if str(row.get("symbol") or "").strip()})
    if symbol_rules is None:
        symbol_rules = _fetch_symbol_rules(symbols)
    combined = _summary_package(combined_rows)
    replay = _replay_package(
        combined_rows,
        symbol_rules=symbol_rules,
        days=int(days),
        account_equities=account_equities,
        risk_per_trade_pct=float(risk_per_trade_pct),
        usable_margin_fraction=float(usable_margin_fraction),
        leverage_cap=float(leverage_cap),
        max_concurrent_positions_values=max_concurrent_positions_values,
    )
    state, reasons = _decision(combined, replay)
    recommended_scenarios = _recommended_scenarios(replay)
    return {
        "schema_version": "micro_intrabar_candidate_portfolio_mix_review_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "portfolio_mix_review_only_no_order_submission",
        "recommended_state": state,
        "reasons": reasons,
        "live_action": "KEEP_CLOSE_ONLY",
        "live_ready": False,
        "order_submission_allowed": False,
        "intrabar_report_path": _display_path(intrabar_report_path),
        "contract_paths": [_display_path(path) for path in contract_paths],
        "settings": {
            "days": int(days),
            "account_equities": account_equities,
            "risk_per_trade_pct": float(risk_per_trade_pct),
            "usable_margin_fraction": float(usable_margin_fraction),
            "leverage_cap": float(leverage_cap),
            "max_concurrent_positions_values": max_concurrent_positions_values,
        },
        "combined_symbols": symbols,
        "combined_symbol_count": len(symbols),
        "duplicate_trade_count": duplicate_trade_count,
        "per_contract": per_contract,
        "combined": combined,
        "portfolio_replay": replay,
        "recommended_portfolio_replay_scenarios": recommended_scenarios,
        "operator_summary": {
            "action": "Keep live disabled; watch the combined long/short mix in paper first.",
            "candidate_contract_count": len(contract_paths),
            "combined_trade_count": _safe_int(dict(combined.get("summary") or {}).get("closed")),
            "recommended_max_concurrent_positions": (
                _safe_int(recommended_scenarios[0].get("max_concurrent_positions")) if recommended_scenarios else None
            ),
            "order_submission_allowed": False,
        },
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    combined_summary = dict(dict(payload.get("combined") or {}).get("summary") or {})
    stress = dict(dict(payload.get("combined") or {}).get("cost_stress") or {})
    extra = dict(stress.get("extra_0_05r_per_trade") or {})
    cost_x2 = dict(stress.get("cost_x2_0") or {})
    lines = [
        "# Micro Intrabar Candidate Portfolio Mix Review",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- authority: {payload.get('authority')}",
        f"- recommended_state: {payload.get('recommended_state')}",
        f"- reasons: {payload.get('reasons')}",
        f"- live_action: {payload.get('live_action')}",
        f"- order_submission_allowed: {payload.get('order_submission_allowed')}",
        f"- combined_symbols: {','.join(list(payload.get('combined_symbols') or []))}",
        (
            "- combined: "
            f"trades={combined_summary.get('closed')} total_r={combined_summary.get('total_r')} "
            f"ev={combined_summary.get('ev_r')} max_dd={combined_summary.get('max_dd_r')} "
            f"positive_year_fraction={combined_summary.get('positive_year_fraction')}"
        ),
        f"- combined_extra_0_05r_total_r: {extra.get('total_r')}",
        f"- combined_cost_x2_total_r: {cost_x2.get('total_r')}",
        "",
        "## Recommended Capacity",
    ]
    for item in list(payload.get("recommended_portfolio_replay_scenarios") or []):
        lines.append(
            "- "
            f"equity={item.get('account_equity_usdt')} max_pos={item.get('max_concurrent_positions')} "
            f"return={item.get('return_pct')}% best_return={item.get('best_return_pct')}% "
            f"accepted={item.get('accepted_trades')}/{item.get('raw_trades')} "
            f"reason={item.get('reason')}"
        )
    lines += [
        "",
        "## Portfolio Replay",
    ]
    for scenario in list(dict(payload.get("portfolio_replay") or {}).get("scenarios") or []):
        totals = dict(scenario.get("yearly_totals") or {})
        full = dict(scenario.get("full_window") or {})
        lines.append(
            "- "
            f"equity={scenario.get('account_equity_usdt')} max_pos={scenario.get('max_concurrent_positions')} "
            f"accepted={totals.get('accepted_trades')} skipped={totals.get('skipped_trades_concurrent')} "
            f"min_qty_reject={totals.get('rejected_trades_min_qty')} "
            f"sum_yearly_return_pct={totals.get('sum_yearly_return_pct')} "
            f"max_yearly_dd_pct={totals.get('max_yearly_drawdown_pct')} "
            f"full_return_pct={full.get('return_pct')}"
        )
    lines.append("")
    lines.append("This review does not submit orders or enable live routing.")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    generated_at = datetime.now(UTC)
    payload = build_payload(
        _csv_paths(args.contract_path),
        intrabar_report_path=_resolve_path(args.intrabar_report_path) if str(args.intrabar_report_path or "").strip() else None,
        days=int(args.days),
        account_equities=_csv_floats(args.account_equity_usdt, default=[170.0, 1000.0]),
        risk_per_trade_pct=float(args.risk_per_trade_pct),
        usable_margin_fraction=float(args.usable_margin_fraction),
        leverage_cap=float(args.leverage_cap),
        max_concurrent_positions_values=_csv_ints(args.max_concurrent_positions, default=[2]),
        generated_at=generated_at,
    )
    if args.write_report:
        report_dir = _resolve_path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = _report_stamp(generated_at)
        json_path = report_dir / f"micro_intrabar_candidate_portfolio_mix_review_{stamp}.json"
        md_path = report_dir / f"micro_intrabar_candidate_portfolio_mix_review_{stamp}.md"
        latest_json = report_dir / "latest.json"
        latest_md = report_dir / "latest.md"
        payload["report_path"] = _display_path(json_path)
        payload["latest_report_path"] = _display_path(latest_json)
        atomic_write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(md_path, _render_markdown(payload))
        atomic_write_text(latest_json, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(latest_md, _render_markdown(payload))
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
