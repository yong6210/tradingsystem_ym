#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
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
        "--lineage-sample-scope",
        choices=["symbol_edge_proof", "family_global"],
        default=os.environ.get("STAGE_MONITOR_LINEAGE_SAMPLE_SCOPE", "symbol_edge_proof"),
    )
    parser.add_argument(
        "--lineage-families",
        default=os.environ.get("STAGE_MONITOR_LINEAGE_FAMILIES", "sweep_reversal"),
    )
    parser.add_argument(
        "--lineage-proof-goal-closed-trades",
        type=int,
        default=int(os.environ.get("STAGE_MONITOR_LINEAGE_PROOF_GOAL_CLOSED_TRADES", "100")),
    )
    parser.add_argument(
        "--lineage-sample-days",
        type=int,
        default=int(os.environ.get("STAGE_MONITOR_LINEAGE_SAMPLE_DAYS", "180")),
    )
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
    parser.add_argument(
        "--edge-sample-stall-hours",
        type=int,
        default=int(os.environ.get("STAGE_MONITOR_EDGE_SAMPLE_STALL_HOURS", "24")),
    )
    parser.add_argument("--dry-run", action="store_true", default=os.environ.get("STAGE_MONITOR_DRY_RUN", "0") == "1")
    return parser.parse_args()


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _lineage_closed_trade_count(payload: dict[str, Any] | None) -> int:
    summary = dict((payload or {}).get("lineage_sample_summary") or {})
    if summary:
        return int(summary.get("closed_trade_count", 0) or 0)
    source = dict((payload or {}).get("edge_experiment_review") or {})
    kpis = dict(source.get("daily_edge_kpis") or {})
    return int(kpis.get("closed_trade_count", source.get("closed_trade_count", 0)) or 0)


def _latest_closed_trade_ts(
    *,
    symbol: str,
    scope: str,
    families: list[str],
    sample_days: int,
) -> datetime | None:
    if str(scope or "symbol_edge_proof") != "family_global":
        return _latest_symbol_closed_trade_ts(symbol)
    return _latest_family_closed_trade_ts(families=families, sample_days=sample_days)


def _latest_symbol_closed_trade_ts(symbol: str) -> datetime | None:
    from app.core.enums import PlanState
    from app.db.models import Plan
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        rows = db.query(Plan).filter(Plan.symbol == symbol, Plan.state == PlanState.CLOSED.value).all()
        latest: datetime | None = None
        for row in rows:
            validity = dict(getattr(row, "validity", {}) or {})
            candidate = _parse_ts(validity.get("final_exit_ts") or validity.get("last_exit_ts"))
            if candidate is None:
                continue
            if latest is None or candidate > latest:
                latest = candidate
        return latest
    finally:
        db.close()


def _latest_family_closed_trade_ts(*, families: list[str], sample_days: int) -> datetime | None:
    from datetime import timedelta

    from app.core.config import get_settings
    from app.core.enums import PlanState
    from app.db.models import Plan
    from app.db.session import SessionLocal
    from app.services.strategy_v2_validation import StrategyV2ValidationService

    settings = get_settings()
    validation = StrategyV2ValidationService(settings)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, sample_days))
    db = SessionLocal()
    try:
        rows = (
            db.query(Plan)
            .filter(Plan.state == PlanState.CLOSED.value, Plan.strategy_version == settings.strategy_version)
            .all()
        )
        latest: datetime | None = None
        normalized_families = {str(item).strip().lower() for item in families if str(item).strip()}
        for row in rows:
            validity = dict(getattr(row, "validity", {}) or {})
            family = str(validity.get("strategy_family") or "").strip().lower()
            if family not in normalized_families:
                continue
            candidate = validation._parse_ts(validity.get("final_exit_ts") or validity.get("last_exit_ts"))
            if candidate is None or candidate < cutoff:
                continue
            if latest is None or candidate > latest:
                latest = candidate
        return latest
    finally:
        db.close()


def _apply_edge_sample_stall(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    *,
    symbol: str,
    lineage_sample_scope: str,
    lineage_families: list[str],
    lineage_sample_days: int,
    threshold_hours: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    snapshot = dict(current or {})
    current_generated_at = _parse_ts(snapshot.get("generated_at")) or now or datetime.now(timezone.utc)
    current_closed_count = _lineage_closed_trade_count(snapshot)
    previous_stall = dict((previous or {}).get("edge_sample_stall") or {})

    prior_progress_count = int(previous_stall.get("progress_count", current_closed_count) or 0)
    prior_progress_at = _parse_ts(previous_stall.get("last_progress_at")) or _parse_ts((previous or {}).get("generated_at"))
    latest_closed_at = _latest_closed_trade_ts(
        symbol=symbol,
        scope=lineage_sample_scope,
        families=lineage_families,
        sample_days=lineage_sample_days,
    )

    if previous is None or current_closed_count != prior_progress_count:
        progress_count = current_closed_count
        last_progress_at = latest_closed_at or current_generated_at
    elif prior_progress_at is None:
        progress_count = current_closed_count
        last_progress_at = latest_closed_at or current_generated_at
    else:
        progress_count = prior_progress_count
        last_progress_at = prior_progress_at
        if latest_closed_at is not None and latest_closed_at < last_progress_at:
            last_progress_at = latest_closed_at

    elapsed_hours = max((current_generated_at - last_progress_at).total_seconds() / 3600.0, 0.0)
    active = (
        current_closed_count > 0
        and not bool(snapshot.get("edge_sample_gate_ready", False))
        and elapsed_hours >= float(max(1, threshold_hours))
    )
    snapshot["edge_sample_stall"] = {
        "active": active,
        "threshold_hours": int(max(1, threshold_hours)),
        "hours_since_progress": round(elapsed_hours, 2),
        "progress_count": int(progress_count),
        "current_closed_trade_count": int(current_closed_count),
        "last_progress_at": last_progress_at.isoformat(),
        "scope": str(lineage_sample_scope),
        "families": list(lineage_families),
        "status": "stalled" if active else "tracking",
        "summary": (
            f"closed_trade_count unchanged at {current_closed_count} for {elapsed_hours:.1f}h "
            f"(threshold={max(1, threshold_hours)}h)"
        ),
    }
    return snapshot


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
        lineage_sample_scope=args.lineage_sample_scope,
        lineage_families=args.lineage_families,
        lineage_proof_goal_closed_trades=args.lineage_proof_goal_closed_trades,
        lineage_sample_days=args.lineage_sample_days,
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
    current = _apply_edge_sample_stall(
        previous,
        current,
        symbol=args.symbol,
        lineage_sample_scope=args.lineage_sample_scope,
        lineage_families=ops_stage_board._family_set(args.lineage_families),
        lineage_sample_days=args.lineage_sample_days,
        threshold_hours=args.edge_sample_stall_hours,
    )
    notify_stage_change._write_json(stage_file, current)
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

    delivery = notify_stage_change._dispatch_stage_notification(
        current,
        message=message,
        webhook_url=args.webhook_url,
    )
    result["delivery"] = delivery
    result["notified"] = bool(delivery.get("delivered"))
    if not result["notified"]:
        result["warning"] = f"discord delivery not completed: {delivery.get('reason')}"
        return result

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
