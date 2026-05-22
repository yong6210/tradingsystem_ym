#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.session import SessionLocal, init_db
from app.services.live_order_lifecycle import LiveOrderLifecycleReporter
from scripts.operation_report_io import atomic_write_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a live order lifecycle report from intent/submission/fill/ledger rows.")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--symbol", default="")
    parser.add_argument("--symbols", default="", help="Comma-separated symbol allowlist. Overrides current-contract symbols.")
    parser.add_argument(
        "--strategy-family",
        action="append",
        default=[],
        help="Strategy family filter. Can be repeated or comma-separated. Overrides current-contract families.",
    )
    parser.add_argument(
        "--all-contracts",
        action="store_true",
        help="Include historical symbols/families outside the current live contract.",
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--include-paper", action="store_true", help="Include paper/test submissions instead of live-only rows.")
    parser.add_argument("--report-dir", default="reports/operations/live_order_lifecycle")
    parser.add_argument("--no-write-report", action="store_true")
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


def _csv_items(raw: str | list[str] | tuple[str, ...] | set[str] | None, *, upper: bool = False) -> list[str]:
    items: list[str] = []
    if isinstance(raw, (list, tuple, set)):
        tokens: list[str] = []
        for value in raw:
            tokens.extend(str(value or "").split(","))
    else:
        tokens = str(raw or "").split(",")
    for token in tokens:
        item = token.strip()
        if not item:
            continue
        items.append(item.upper() if upper else item)
    return items


def _current_contract_filters(settings: Any) -> tuple[list[str], list[str]]:
    symbols = _csv_items(getattr(settings, "auto_trading_micro_live_allowed_symbols", ""), upper=True)
    if not symbols:
        symbols = _csv_items(getattr(settings, "auto_trading_allowed_symbols", ""), upper=True)
    families = _csv_items(getattr(settings, "auto_trading_micro_live_allowed_families", ""))
    if not families:
        families = _csv_items(getattr(settings, "auto_trading_allowed_families", ""))
    return symbols, families


def _parse_generated_at(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = dict(payload.get("summary") or {})
    live_intents = dict(summary.get("live_intents") or {})
    rows = list(payload.get("rows") or [])

    lines = [
        "# Live Order Lifecycle Report",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- window_start: {payload.get('window_start')}",
        f"- window_days: {payload.get('window_days')}",
        f"- symbol: {payload.get('symbol') or 'ALL'}",
        f"- symbols: {','.join(payload.get('symbols') or []) or 'ALL'}",
        f"- strategy_families: {','.join(dict(summary.get('live_intents') or {}).get('family_filter') or []) or 'ALL'}",
        f"- contract_filter: {dict(payload.get('contract_filter') or {}).get('mode', 'custom')}",
        f"- live_only: {payload.get('live_only')}",
        "",
        "## Summary",
        "",
        f"- submissions: {summary.get('submission_count', 0)}",
        f"- requested_live: {summary.get('requested_live_count', 0)}",
        f"- entry_fills: {summary.get('entry_fill_count', 0)}",
        f"- closed: {summary.get('closed_count', 0)}",
        f"- open_after_entry: {summary.get('open_after_entry_count', 0)}",
        f"- exchange_flat_after_entry: {summary.get('exchange_flat_after_entry_count', 0)}",
        f"- submitted_without_entry_fill: {summary.get('submitted_without_entry_fill_count', 0)}",
        f"- rejected_or_error: {summary.get('rejected_or_error_count', 0)}",
        f"- avg_entry_slippage_bps: {summary.get('avg_entry_slippage_bps')}",
        f"- avg_realized_r: {summary.get('avg_realized_r')}",
        f"- total_fee: {summary.get('total_fee', 0.0)}",
        "",
        "## Live Intent Funnel",
        "",
        f"- intents: {live_intents.get('total', 0)}",
        f"- submit_ready: {live_intents.get('submit_ready', 0)}",
        f"- blocked: {live_intents.get('blocked', 0)}",
    ]
    top_reasons = dict(live_intents.get("top_block_reasons") or {})
    if top_reasons:
        lines.append("- top_reasons: " + ", ".join(f"{key}={value}" for key, value in list(top_reasons.items())[:8]))

    lines.extend(["", "## Recent Rows", ""])
    if not rows:
        lines.append("- none")
    for row in rows[:20]:
        lines.append(
            "- "
            f"{row.get('symbol')} {row.get('lifecycle_status')} "
            f"mode={row.get('execution_mode')} state={row.get('state')} submit={row.get('submit_status')} "
            f"entry={row.get('entry_avg_price')} slip_bps={row.get('entry_slippage_bps')} "
            f"r={row.get('realized_r')} reason={row.get('exit_reason') or row.get('decision_reason_code')}"
        )

    lines.extend(["", "## Raw Payload", "", "```json"])
    lines.append(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    lines.append("```")
    atomic_write_text(path, "\n".join(lines))


def main() -> int:
    args = parse_args()
    settings = get_settings()
    explicit_symbols = _csv_items(args.symbols, upper=True)
    explicit_families = _csv_items(args.strategy_family)
    current_symbols, current_families = _current_contract_filters(settings)
    symbol = str(args.symbol or "").strip().upper() or None
    symbols = [] if symbol else explicit_symbols
    strategy_families = explicit_families
    contract_mode = "custom"
    if not args.all_contracts:
        if not symbol and not symbols:
            symbols = current_symbols
        if not strategy_families:
            strategy_families = current_families
        contract_mode = "current_live_contract" if (symbols or strategy_families) else "custom"
    else:
        contract_mode = "all_contracts"

    init_db()
    with SessionLocal() as db:
        payload = LiveOrderLifecycleReporter(db).generate(
            days=max(1, int(args.days)),
            symbol=symbol,
            symbols=symbols,
            live_only=not bool(args.include_paper),
            limit=max(1, int(args.limit)),
            strategy_families=strategy_families,
        )
    payload["contract_filter"] = {
        "mode": contract_mode,
        "symbol": symbol or "",
        "symbols": list(symbols),
        "strategy_families": list(strategy_families),
        "all_contracts": bool(args.all_contracts),
    }
    if not args.no_write_report:
        generated = _parse_generated_at(payload["generated_at"])
        symbol = str(payload.get("symbol") or "ALL")
        report_path = ROOT_DIR / args.report_dir / f"live_order_lifecycle_{symbol}_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
        _write_report(report_path, payload)
        payload["report_path"] = _display_path(report_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
