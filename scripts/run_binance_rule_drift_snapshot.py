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
from app.integrations.binance_futures import BinanceFuturesClient
from scripts.operation_report_io import display_path, write_json
from scripts.run_micro_live_preflight import _csv_set


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Snapshot Binance futures trading rules and detect live-symbol rule drift.")
    parser.add_argument("--symbols", default="")
    parser.add_argument("--snapshot-dir", default="reports/operations/binance_rule_snapshots")
    parser.add_argument("--baseline", default="")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--fail-on-drift", action="store_true")
    return parser.parse_args()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _display_path(path: Path) -> str:
    return display_path(path, ROOT_DIR)


def _resolve_root_path(raw_path: str) -> Path:
    path = Path(str(raw_path or "")).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


def _parse_generated_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _rule_row(client: BinanceFuturesClient, symbol: str) -> dict[str, Any]:
    rules = client.fetch_symbol_trading_rules(symbol)
    raw = dict(rules.raw or {})
    return {
        "symbol": rules.symbol,
        "quantity_step": float(rules.quantity_step),
        "min_quantity": float(rules.min_quantity),
        "tick_size": float(rules.tick_size) if rules.tick_size is not None else None,
        "price_precision": rules.price_precision,
        "quantity_precision": rules.quantity_precision,
        "status": str(raw.get("status") or ""),
        "contract_type": str(raw.get("contractType") or ""),
    }


def compare_rule_snapshots(*, previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    previous_rules = {str(row.get("symbol") or "").upper(): dict(row) for row in list(previous.get("rules") or []) if isinstance(row, dict)}
    changes: list[dict[str, Any]] = []
    keys = ["quantity_step", "min_quantity", "tick_size", "price_precision", "quantity_precision", "status", "contract_type"]
    for row in list(current.get("rules") or []):
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        old = previous_rules.get(symbol)
        if old is None:
            changes.append({"symbol": symbol, "change_type": "new_symbol", "fields": {}})
            continue
        fields: dict[str, dict[str, Any]] = {}
        for key in keys:
            if old.get(key) != row.get(key):
                fields[key] = {"old": old.get(key), "new": row.get(key)}
        if fields:
            changes.append({"symbol": symbol, "change_type": "rule_changed", "fields": fields})
    current_symbols = {str(row.get("symbol") or "").upper() for row in list(current.get("rules") or []) if isinstance(row, dict)}
    for symbol in sorted(set(previous_rules) - current_symbols):
        changes.append({"symbol": symbol, "change_type": "missing_from_current", "fields": {}})
    return changes


def build_snapshot(*, symbols: list[str]) -> dict[str, Any]:
    client = BinanceFuturesClient()
    rules = [_rule_row(client, symbol) for symbol in symbols]
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": "binance_futures_exchangeInfo",
        "symbols": symbols,
        "rules": rules,
    }


def main() -> int:
    args = parse_args()
    settings = get_settings()
    symbols = sorted(_csv_set(args.symbols or getattr(settings, "auto_trading_micro_live_allowed_symbols", "")))
    payload = build_snapshot(symbols=symbols)
    snapshot_dir = _resolve_root_path(str(args.snapshot_dir))
    baseline_path = _resolve_root_path(str(args.baseline)) if str(args.baseline or "").strip() else snapshot_dir / "latest.json"
    previous = _read_json(baseline_path)
    changes = compare_rule_snapshots(previous=previous, current=payload) if previous else []
    payload["previous_snapshot"] = _display_path(baseline_path) if previous else ""
    payload["drift_count"] = len(changes)
    payload["drift"] = changes
    payload["overall_status"] = "DRIFT" if changes else "PASS"
    if not args.no_write:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        generated = _parse_generated_at(payload["generated_at"])
        snapshot_path = snapshot_dir / f"binance_rules_{generated.strftime('%Y%m%dT%H%M%SZ')}.json"
        latest_path = snapshot_dir / "latest.json"
        payload["snapshot_path"] = _display_path(snapshot_path)
        payload["latest_path"] = _display_path(latest_path)
        write_json(snapshot_path, payload, json_default=_json_default)
        write_json(latest_path, payload, json_default=_json_default)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 1 if changes and bool(args.fail_on_drift) else 0


if __name__ == "__main__":
    raise SystemExit(main())
