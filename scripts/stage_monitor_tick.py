#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import notify_stage_change, ops_stage_board


DEFAULT_STAGE_DIR = ROOT_DIR / "reports/operations/stage_monitor"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the stage monitor board build and stage-change notifier in one Python process."
    )
    parser.add_argument("--base-url", default=os.environ.get("STAGE_MONITOR_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--symbol", default=os.environ.get("STAGE_MONITOR_SYMBOL", "BTCUSDC"))
    parser.add_argument("--universe", default=os.environ.get("STAGE_MONITOR_UNIVERSE", "usdc_perp_top30"))
    parser.add_argument("--limit", type=int, default=int(os.environ.get("STAGE_MONITOR_LIMIT", "20")))
    parser.add_argument("--days", type=int, default=int(os.environ.get("STAGE_MONITOR_DAYS", "30")))
    parser.add_argument(
        "--alert-test-lookback-hours",
        type=int,
        default=int(os.environ.get("STAGE_MONITOR_ALERT_TEST_LOOKBACK_HOURS", "24")),
    )
    parser.add_argument(
        "--stage-file",
        default=os.environ.get("STAGE_MONITOR_STAGE_FILE", str(DEFAULT_STAGE_DIR / "current_stage.json")),
    )
    parser.add_argument(
        "--latest-board-file",
        default=os.environ.get("STAGE_MONITOR_LATEST_BOARD_FILE", str(DEFAULT_STAGE_DIR / "latest_stage_board.json")),
    )
    parser.add_argument(
        "--state-file",
        default=os.environ.get("STAGE_MONITOR_STATE_FILE", str(DEFAULT_STAGE_DIR / "last_alert_state.json")),
    )
    parser.add_argument("--webhook-url", default=os.environ.get("STAGE_MONITOR_DISCORD_WEBHOOK_URL", ""))
    parser.add_argument("--dry-run", action="store_true", default=os.environ.get("STAGE_MONITOR_DRY_RUN", "0") == "1")
    return parser.parse_args()


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run_stage_board(args: argparse.Namespace) -> dict[str, object]:
    stage_file = Path(args.stage_file).resolve()
    latest_board_file = Path(args.latest_board_file).resolve()
    validation = ops_stage_board._request_json(
        args.base_url,
        "POST",
        "/validation/report",
        query={"symbol": args.symbol},
    )
    checklist = ops_stage_board._request_json(
        args.base_url,
        "POST",
        "/operations/checklist",
        query={
            "symbol": args.symbol,
            "universe": args.universe,
            "limit": max(1, args.limit),
            "days": max(1, args.days),
            "alert_test_lookback_hours": max(1, args.alert_test_lookback_hours),
        },
    )
    dashboard = ops_stage_board._request_json(
        args.base_url,
        "GET",
        "/execution/operator-dashboard",
        query={
            "symbol": args.symbol,
            "universe": args.universe,
            "portfolio_limit": max(1, args.limit),
            "intent_limit": max(1, args.limit),
            "reconcile_limit": max(1, args.limit),
            "days": max(1, args.days),
        },
    )

    validation_report = validation.get("validation_report") or validation
    payload = ops_stage_board._build_stage_payload(
        validation_report,
        checklist,
        dashboard,
        symbol=args.symbol,
        universe=args.universe,
        days=args.days,
    )
    ops_stage_board._write_stage_file(stage_file, payload)
    output = json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"
    _write_text(latest_board_file, output)
    return payload


def _run_notifier(args: argparse.Namespace) -> dict[str, object]:
    stage_file = Path(args.stage_file).resolve()
    state_file = Path(args.state_file).resolve()
    current = notify_stage_change._load_stage(stage_file)
    previous = notify_stage_change._read_json(state_file)
    events = notify_stage_change._collect_events(previous, current)
    result: dict[str, Any] = {
        "stage_file": str(stage_file),
        "state_file": str(state_file),
        "current": current,
        "previous": previous,
        "events": events,
        "notified": False,
        "dry_run": bool(args.dry_run),
    }
    if not events:
        notify_stage_change._write_json(state_file, current)
        return result

    message = notify_stage_change._render_message(current, events)
    result["message"] = message

    if args.dry_run:
        notify_stage_change._write_json(state_file, current)
        return result

    webhook_url = notify_stage_change._webhook_url(args.webhook_url)
    if not webhook_url:
        result["warning"] = "discord webhook url is not configured"
        notify_stage_change._write_json(state_file, current)
        return result

    delivery = notify_stage_change._post_discord(webhook_url, message)
    result["notified"] = True
    result["delivery"] = delivery
    notify_stage_change._write_json(state_file, current)
    return result


def main() -> int:
    args = parse_args()
    _run_stage_board(args)
    notifier_payload = _run_notifier(args)
    print(json.dumps(notifier_payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
