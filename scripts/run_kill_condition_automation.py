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
from app.services.strategy_engine import StrategyEngine
from scripts.operation_report_io import atomic_write_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run kill-condition automation review or explicit-arm live apply.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--universe", default="usdt_reliable_balanced_31")
    parser.add_argument("--family", default=None)
    parser.add_argument("--session-name", default=None)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--portfolio-limit", type=int, default=10)
    parser.add_argument("--intent-limit", type=int, default=10)
    parser.add_argument("--reconcile-limit", type=int, default=10)
    parser.add_argument("--allow-live-write", action="store_true")
    parser.add_argument("--arm-token", default=None)
    parser.add_argument("--updated-by", default="kill_condition_script")
    parser.add_argument("--unlock-at", default=None, help="Optional ISO8601 unlock time for live close-only or kill-switch writes.")
    parser.add_argument("--no-dry-run", action="store_true")
    parser.add_argument("--report-dir", default=None)
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


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Kill Condition Automation",
        "",
        f"- generated_at: {payload['generated_at']}",
        f"- symbol: {payload.get('symbol') or 'n/a'}",
        f"- universe: {payload.get('universe') or 'n/a'}",
        f"- dry_run: {payload.get('dry_run')}",
        f"- allow_live_write: {payload.get('allow_live_write')}",
        f"- arm_valid: {payload.get('arm_valid')}",
        f"- eligible_for_live_write: {payload.get('eligible_for_live_write')}",
        f"- action_applied: {payload.get('action_applied')}",
        f"- unlock_at: {payload.get('unlock_at') or 'n/a'}",
        "",
        "## Verdict",
        "",
        f"- kill_condition_state: {payload.get('kill_condition_state')}",
        f"- automation_bias: {payload.get('automation_bias')}",
        f"- trigger_axis: {payload.get('trigger_axis')}",
        f"- effective_write_scope: {payload.get('effective_write_scope')}",
        f"- action_target: {payload.get('action_target')}",
        f"- action_reason_code: {payload.get('action_reason_code') or 'none'}",
        f"- action_reason_message: {payload.get('action_reason_message') or 'none'}",
        "",
        "## Summary",
        "",
        f"- summary: {dict(payload.get('kill_condition_automation_summary') or {}).get('summary') or 'n/a'}",
        f"- reason_codes: {list(dict(payload.get('kill_condition_automation_summary') or {}).get('reason_codes') or [])}",
        "",
        "## Safety State Before",
        "",
        "```json",
        json.dumps(payload.get("safety_state_before") or {}, ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Safety State After",
        "",
        "```json",
        json.dumps(payload.get("safety_state_after") or {}, ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Raw Payload",
        "",
        "```json",
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        "```",
    ]
    atomic_write_text(path, "\n".join(lines))


def _parse_unlock_at(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid --unlock-at ISO8601 timestamp: {value}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def main() -> int:
    args = parse_args()
    init_db()
    settings = get_settings()
    report_dir_input = Path(args.report_dir or settings.kill_condition_automation_report_dir)
    report_dir = report_dir_input if report_dir_input.is_absolute() else ROOT_DIR / report_dir_input
    try:
        unlock_at = _parse_unlock_at(args.unlock_at)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        payload = engine.apply_kill_condition_automation(
            symbol=args.symbol,
            universe=args.universe,
            family=args.family,
            session_name=args.session_name,
            days=max(1, args.days),
            portfolio_limit=max(1, args.portfolio_limit),
            intent_limit=max(1, args.intent_limit),
            reconcile_limit=max(1, args.reconcile_limit),
            dry_run=not args.no_dry_run,
            allow_live_write=bool(args.allow_live_write),
            arm_token=args.arm_token,
            updated_by=args.updated_by,
            unlock_at=unlock_at,
        )

    payload["generated_at"] = payload["generated_at"].isoformat()
    payload["unlock_at"] = unlock_at.isoformat() if unlock_at else None
    report_path = report_dir / f"kill_condition_automation_{args.symbol}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.md"
    payload["report_path"] = _display_path(report_path)
    if not args.no_write_report:
        _write_report(report_path, payload)

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
