#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.models import BinanceOrderLedger, BinancePositionSnapshot, ExecutionReconciliationEvent, OrderSubmission
from app.db.session import SessionLocal, init_db
from app.services.notification_dispatcher import NotificationDispatcher
from scripts.operation_report_io import atomic_write_text, display_path, parse_report_generated_at, write_json, write_latest_aliases


_OPEN_SUBMISSION_STATES = {"CREATED", "SUBMITTED", "ACKNOWLEDGED", "PARTIALLY_FILLED"}
_TERMINAL_LEDGER_STATES = {"FILLED", "CANCELED", "CANCELLED", "REJECTED", "EXPIRED"}
_ERROR_SUBMIT_STATES = {"REJECTED", "ERROR", "FAILED", "LIVE_SUBMIT_ERROR"}
_SAFETY_REJECTION_SUBMIT_STATUSES = {"LIVE_LIQUIDITY_BLOCKED", "LIVE_LIQUIDITY_SPLIT_REQUIRED"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watch live order reconciliation gaps before they become silent execution failures.")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--stale-minutes", type=int, default=0, help="Defaults to AUTO_TRADING_RECONCILIATION_USER_STREAM_STALE_SECONDS.")
    parser.add_argument("--event-lookback-minutes", type=int, default=60)
    parser.add_argument("--cooldown-minutes", type=int, default=180)
    parser.add_argument("--channel", choices=["discord", "system"], default="discord")
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--force-notify", action="store_true")
    parser.add_argument("--report-dir", default="reports/operations/live_reconciliation_watchdog")
    parser.add_argument("--state-file", default="reports/operations/live_reconciliation_watchdog/state.json")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--no-fail-exit", action="store_true")
    parser.add_argument("--quiet", action="store_true", help="Do not print the JSON payload to stdout.")
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


def _csv_symbols(raw: str) -> set[str]:
    return {item.strip().upper() for item in str(raw or "").split(",") if item.strip()}


def _as_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, "", "None"):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if isfinite(parsed) else default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", "none", "null", ""}:
            return False
    return True if value else False


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    write_json(path, payload, json_default=_json_default)


def _model_dt(row: Any, attr: str) -> datetime | None:
    return _as_utc(getattr(row, attr, None))


def _submission_dict(row: OrderSubmission) -> dict[str, Any]:
    return {
        "submission_id": row.submission_id,
        "intent_id": row.intent_id,
        "plan_id": row.plan_id,
        "symbol": row.symbol,
        "client_order_id": row.client_order_id,
        "exchange_order_id": row.exchange_order_id,
        "state": row.state,
        "submit_status": row.submit_status,
        "requested_live": _safe_bool(row.requested_live),
        "submitted_at": _model_dt(row, "submitted_at"),
        "updated_at": _model_dt(row, "updated_at"),
    }


def _ledger_dict(row: BinanceOrderLedger) -> dict[str, Any]:
    raw = dict(row.raw or {}) if isinstance(row.raw, dict) else {}
    return {
        "client_order_id": row.client_order_id,
        "exchange_order_id": row.exchange_order_id,
        "plan_id": row.plan_id,
        "symbol": row.symbol,
        "side": row.side,
        "reduce_only": _safe_bool(row.reduce_only),
        "position_side": str(raw.get("positionSide") or raw.get("position_side") or ""),
        "status": row.status,
        "requested_live": _safe_bool(row.requested_live),
        "test_order": _safe_bool(row.test_order),
        "executed_qty": _safe_float(row.executed_qty),
        "last_event_ts": _model_dt(row, "last_event_ts"),
        "updated_at": _model_dt(row, "updated_at"),
        "created_at": _model_dt(row, "created_at"),
    }


def _position_dict(row: BinancePositionSnapshot) -> dict[str, Any]:
    return {
        "position_key": row.position_key,
        "symbol": row.symbol,
        "position_side": row.position_side,
        "position_amt": _safe_float(row.position_amt),
        "update_ts": _model_dt(row, "update_ts"),
        "updated_at": _model_dt(row, "updated_at"),
    }


def _event_dict(row: ExecutionReconciliationEvent) -> dict[str, Any]:
    return {
        "event_id": row.event_id,
        "symbol": row.symbol,
        "mismatch_type": row.mismatch_type,
        "severity": row.severity,
        "message": row.message,
        "lock_required": _safe_bool(row.lock_required),
        "lock_applied": _safe_bool(row.lock_applied),
        "created_at": _model_dt(row, "created_at"),
    }


def _latest(*values: Any) -> datetime | None:
    parsed = [item for item in (_as_utc(value) for value in values) if item is not None]
    return max(parsed) if parsed else None


def _age_minutes(now: datetime, ts: datetime | None) -> float | None:
    if ts is None:
        return None
    return max(0.0, (now - ts).total_seconds() / 60.0)


def _issue(
    issue_type: str,
    severity: str,
    message: str,
    *,
    symbol: str = "",
    client_order_id: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": issue_type,
        "severity": severity,
        "symbol": symbol,
        "client_order_id": client_order_id,
        "message": message,
        "details": dict(details or {}),
    }


def evaluate_reconciliation_watchdog(
    *,
    submissions: list[dict[str, Any]],
    ledgers: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    events: list[dict[str, Any]],
    now: datetime,
    stale_minutes: int,
    event_lookback_minutes: int,
) -> dict[str, Any]:
    normalized_now = _as_utc(now) or datetime.now(UTC)
    stale_delta = timedelta(minutes=max(1, int(stale_minutes)))
    event_delta = timedelta(minutes=max(1, int(event_lookback_minutes)))
    ledger_by_client = {str(row.get("client_order_id") or ""): row for row in ledgers if row.get("client_order_id")}
    open_positions = [row for row in positions if abs(_safe_float(row.get("position_amt"))) > 1e-12]
    issues: list[dict[str, Any]] = []

    def matching_open_position(ledger: dict[str, Any]) -> dict[str, Any] | None:
        symbol = str(ledger.get("symbol") or "")
        desired_side = str(ledger.get("position_side") or "").upper()
        if desired_side not in {"LONG", "SHORT", "BOTH"}:
            desired_side = "LONG" if str(ledger.get("side") or "").upper() == "BUY" else "SHORT"
        for position in open_positions:
            if str(position.get("symbol") or "") != symbol:
                continue
            position_side = str(position.get("position_side") or "").upper()
            if desired_side in {"", "BOTH"} or position_side in {"", "BOTH", desired_side}:
                return position
        return None

    for row in submissions:
        state = str(row.get("state") or "").upper()
        submit_status = str(row.get("submit_status") or "").upper()
        client_order_id = str(row.get("client_order_id") or "")
        symbol = str(row.get("symbol") or "")
        ledger = ledger_by_client.get(client_order_id)
        reference_ts = _latest(row.get("updated_at"), row.get("submitted_at"))
        stale = reference_ts is not None and reference_ts <= normalized_now - stale_delta
        if state in _ERROR_SUBMIT_STATES or submit_status in _ERROR_SUBMIT_STATES:
            safety_rejection = submit_status in _SAFETY_REJECTION_SUBMIT_STATUSES
            issues.append(
                _issue(
                    "live_submission_safety_rejected" if safety_rejection else "live_submission_error",
                    "WARN" if safety_rejection else "FAIL",
                    "라이브 주문이 유동성 안전장치에서 차단됐습니다."
                    if safety_rejection
                    else "라이브 주문 제출이 거절/오류 상태입니다.",
                    symbol=symbol,
                    client_order_id=client_order_id,
                    details={"state": state, "submit_status": submit_status, "age_minutes": _age_minutes(normalized_now, reference_ts)},
                )
            )
            continue
        if state not in _OPEN_SUBMISSION_STATES or not stale:
            continue
        if ledger is None:
            issues.append(
                _issue(
                    "missing_live_ledger_for_open_submission",
                    "FAIL",
                    "오래된 open live submission이 Binance ledger와 매칭되지 않습니다.",
                    symbol=symbol,
                    client_order_id=client_order_id,
                    details={"state": state, "age_minutes": _age_minutes(normalized_now, reference_ts)},
                )
            )
            continue
        ledger_status = str(ledger.get("status") or "").upper()
        if ledger_status in _TERMINAL_LEDGER_STATES:
            issues.append(
                _issue(
                    "submission_open_but_ledger_terminal",
                    "FAIL",
                    "로컬 submission은 open인데 Binance ledger는 terminal 상태입니다.",
                    symbol=symbol,
                    client_order_id=client_order_id,
                    details={"submission_state": state, "ledger_status": ledger_status},
                )
            )
        else:
            issues.append(
                _issue(
                    "stale_open_live_submission",
                    "WARN",
                    "open live submission이 stale 기준을 넘었습니다. 체결/취소 이벤트 유입을 확인해야 합니다.",
                    symbol=symbol,
                    client_order_id=client_order_id,
                    details={"submission_state": state, "ledger_status": ledger_status, "age_minutes": _age_minutes(normalized_now, reference_ts)},
                )
            )

    for row in ledgers:
        status = str(row.get("status") or "").upper()
        if status in _TERMINAL_LEDGER_STATES:
            reference_ts = _latest(row.get("last_event_ts"), row.get("updated_at"), row.get("created_at"))
            stale = reference_ts is not None and reference_ts <= normalized_now - stale_delta
            if (
                status == "FILLED"
                and stale
                and _safe_float(row.get("executed_qty")) > 0.0
                and not _safe_bool(row.get("reduce_only"))
                and matching_open_position(row) is None
            ):
                issues.append(
                    _issue(
                        "filled_entry_without_position_snapshot",
                        "WARN",
                        "체결된 live 진입 주문과 매칭되는 open position snapshot이 없습니다.",
                        symbol=str(row.get("symbol") or ""),
                        client_order_id=str(row.get("client_order_id") or ""),
                        details={
                            "status": status,
                            "side": row.get("side"),
                            "position_side": row.get("position_side"),
                            "executed_qty": row.get("executed_qty"),
                            "age_minutes": _age_minutes(normalized_now, reference_ts),
                        },
                    )
                )
            continue
        reference_ts = _latest(row.get("last_event_ts"), row.get("updated_at"), row.get("created_at"))
        if reference_ts is None or reference_ts <= normalized_now - stale_delta:
            issues.append(
                _issue(
                    "open_ledger_user_stream_stale",
                    "FAIL",
                    "open Binance ledger의 user-stream 이벤트가 stale 상태입니다.",
                    symbol=str(row.get("symbol") or ""),
                    client_order_id=str(row.get("client_order_id") or ""),
                    details={"status": status, "last_event_ts": row.get("last_event_ts"), "age_minutes": _age_minutes(normalized_now, reference_ts)},
                )
            )

    for row in positions:
        if abs(_safe_float(row.get("position_amt"))) <= 1e-12:
            continue
        reference_ts = _latest(row.get("update_ts"), row.get("updated_at"))
        if reference_ts is None or reference_ts <= normalized_now - stale_delta:
            issues.append(
                _issue(
                    "open_position_user_stream_stale",
                    "FAIL",
                    "open position snapshot의 user-stream 갱신이 stale 상태입니다.",
                    symbol=str(row.get("symbol") or ""),
                    details={"position_key": row.get("position_key"), "age_minutes": _age_minutes(normalized_now, reference_ts)},
                )
            )

    for row in events:
        created_at = _as_utc(row.get("created_at"))
        if created_at is None or created_at < normalized_now - event_delta:
            continue
        if str(row.get("severity") or "").upper() == "CRITICAL":
            issues.append(
                _issue(
                    "recent_critical_reconciliation_event",
                    "FAIL",
                    "최근 critical reconciliation event가 기록됐습니다.",
                    symbol=str(row.get("symbol") or ""),
                    details={
                        "event_id": row.get("event_id"),
                        "mismatch_type": row.get("mismatch_type"),
                        "lock_required": row.get("lock_required"),
                        "lock_applied": row.get("lock_applied"),
                    },
                )
            )

    fail_count = sum(1 for item in issues if str(item.get("severity")) == "FAIL")
    warn_count = sum(1 for item in issues if str(item.get("severity")) == "WARN")
    status = "ALERT" if issues else "OK"
    severity = "FAIL" if fail_count else ("WARN" if warn_count else "INFO")
    return {
        "status": status,
        "severity": severity,
        "alert": bool(issues),
        "reason": issues[0]["type"] if issues else "no_reconciliation_gap_detected",
        "message": f"reconciliation issues={len(issues)} fail={fail_count} warn={warn_count}",
        "issue_count": len(issues),
        "fail_count": fail_count,
        "warn_count": warn_count,
        "stale_minutes": max(1, int(stale_minutes)),
        "issues": issues[:50],
        "summary": {
            "live_submission_count": len(submissions),
            "live_ledger_count": len(ledgers),
            "open_position_count": len(open_positions),
            "recent_reconciliation_event_count": len(events),
        },
    }


def _fetch_state(*, symbols: set[str], days: int, limit: int) -> dict[str, list[dict[str, Any]]]:
    cutoff = datetime.now(UTC) - timedelta(days=max(1, int(days)))
    init_db()
    with SessionLocal() as db:
        submission_stmt = (
            select(OrderSubmission)
            .where(OrderSubmission.requested_live.is_(True), OrderSubmission.submitted_at >= cutoff)
            .order_by(desc(OrderSubmission.updated_at), desc(OrderSubmission.submitted_at))
            .limit(max(1, int(limit)))
        )
        if symbols:
            submission_stmt = submission_stmt.where(OrderSubmission.symbol.in_(sorted(symbols)))
        submissions = [_submission_dict(row) for row in db.scalars(submission_stmt)]

        ledger_stmt = (
            select(BinanceOrderLedger)
            .where(BinanceOrderLedger.requested_live.is_(True), BinanceOrderLedger.updated_at >= cutoff)
            .order_by(desc(BinanceOrderLedger.updated_at), desc(BinanceOrderLedger.created_at))
            .limit(max(1, int(limit)))
        )
        if symbols:
            ledger_stmt = ledger_stmt.where(BinanceOrderLedger.symbol.in_(sorted(symbols)))
        ledgers = [_ledger_dict(row) for row in db.scalars(ledger_stmt)]

        position_stmt = select(BinancePositionSnapshot).order_by(BinancePositionSnapshot.symbol.asc())
        if symbols:
            position_stmt = position_stmt.where(BinancePositionSnapshot.symbol.in_(sorted(symbols)))
        positions = [_position_dict(row) for row in db.scalars(position_stmt)]

        event_stmt = (
            select(ExecutionReconciliationEvent)
            .where(ExecutionReconciliationEvent.created_at >= cutoff)
            .order_by(desc(ExecutionReconciliationEvent.created_at))
            .limit(max(1, int(limit)))
        )
        if symbols:
            event_stmt = event_stmt.where(ExecutionReconciliationEvent.symbol.in_(sorted(symbols)))
        events = [_event_dict(row) for row in db.scalars(event_stmt)]
    return {"submissions": submissions, "ledgers": ledgers, "positions": positions, "events": events}


def _default_stale_minutes(explicit: int) -> int:
    if explicit > 0:
        return explicit
    settings = get_settings()
    seconds = int(getattr(settings, "auto_trading_reconciliation_user_stream_stale_seconds", 180) or 180)
    return max(1, int(round(seconds / 60.0)))


def build_payload(*, days: int, symbols: set[str], limit: int, stale_minutes: int, event_lookback_minutes: int) -> dict[str, Any]:
    state = _fetch_state(symbols=symbols, days=days, limit=limit)
    now = datetime.now(UTC)
    evaluation = evaluate_reconciliation_watchdog(
        submissions=state["submissions"],
        ledgers=state["ledgers"],
        positions=state["positions"],
        events=state["events"],
        now=now,
        stale_minutes=stale_minutes,
        event_lookback_minutes=event_lookback_minutes,
    )
    return {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "window_days": max(1, int(days)),
        "symbols": sorted(symbols),
        "overall_status": evaluation["status"],
        "evaluation": evaluation,
    }


def _write_report(path: Path, payload: dict[str, Any], *, atomic: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    evaluation = dict(payload.get("evaluation") or {})
    lines = [
        "# Live Reconciliation Watchdog",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- status: {payload.get('overall_status')}",
        f"- severity: {evaluation.get('severity')}",
        f"- reason: {evaluation.get('reason')}",
        f"- message: {evaluation.get('message')}",
        "",
        "## Issues",
        "",
    ]
    for issue in list(evaluation.get("issues") or [])[:20]:
        lines.append(f"- {issue.get('severity')} {issue.get('type')} {issue.get('symbol')} {issue.get('client_order_id')}: {issue.get('message')}")
    if not evaluation.get("issues"):
        lines.append("- none")
    lines.extend(["", "```json", json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), "```"])
    content = "\n".join(lines)
    if atomic:
        atomic_write_text(path, content)
    else:
        atomic_write_text(path, content)


def _notification_delivered(payload: dict[str, Any]) -> bool:
    return _safe_bool(dict(payload or {}).get("delivered"))


def _cooldown_allows(*, state_file: Path, dedupe_key: str, cooldown_minutes: int, now: datetime, force: bool) -> bool:
    if force:
        return True
    state = _read_json(state_file)
    if str(state.get("dedupe_key") or "") != dedupe_key:
        return True
    last_sent = _as_utc(state.get("last_sent_at"))
    if last_sent is None:
        return True
    return now - last_sent >= timedelta(minutes=max(1, int(cooldown_minutes)))


def _watchdog_message(payload: dict[str, Any]) -> str:
    evaluation = dict(payload.get("evaluation") or {})
    issues = list(evaluation.get("issues") or [])
    head = dict(issues[0]) if issues else {}
    return "\n".join(
        [
            "MICRO_LIVE 체결 동기화 점검",
            f"상태: {evaluation.get('severity')} / {evaluation.get('reason')}",
            f"요약: {evaluation.get('message')}",
            f"대표: {head.get('symbol', '')} {head.get('client_order_id', '')} {head.get('type', 'none')}",
            "조치: Binance ledger, user-stream, reconciliation event를 확인",
        ]
    )


def main() -> int:
    args = parse_args()
    symbols = _csv_symbols(str(args.symbols or ""))
    stale_minutes = _default_stale_minutes(int(args.stale_minutes or 0))
    payload = build_payload(
        days=max(1, int(args.days)),
        symbols=symbols,
        limit=max(1, int(args.limit)),
        stale_minutes=stale_minutes,
        event_lookback_minutes=max(1, int(args.event_lookback_minutes)),
    )
    if not args.no_write_report:
        generated = parse_report_generated_at(payload.get("generated_at"))
        report_dir = ROOT_DIR / args.report_dir
        report_path = report_dir / f"live_reconciliation_watchdog_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
        payload["report_path"] = _display_path(report_path)
        payload["latest_report_path"] = _display_path(report_dir / "latest.md")
        payload["latest_json_path"] = _display_path(report_dir / "latest.json")
        _write_report(report_path, payload, atomic=True)
        payload.update(
            write_latest_aliases(
                report_dir=report_dir,
                payload=payload,
                write_markdown_report=_write_report,
                root_dir=ROOT_DIR,
                json_default=_json_default,
            )
        )

    evaluation = dict(payload.get("evaluation") or {})
    alert_active = _safe_bool(evaluation.get("alert"))
    if bool(args.notify) and alert_active:
        now = datetime.now(UTC)
        first_issue = dict((evaluation.get("issues") or [{}])[0])
        dedupe_key = f"{evaluation.get('reason')}:{first_issue.get('symbol')}:{first_issue.get('client_order_id')}"
        state_file = _resolve_root_path(str(args.state_file))
        if _cooldown_allows(
            state_file=state_file,
            dedupe_key=dedupe_key,
            cooldown_minutes=max(1, int(args.cooldown_minutes)),
            now=now,
            force=bool(args.force_notify),
        ):
            delivery = NotificationDispatcher(get_settings()).dispatch(
                channel=str(args.channel),
                alert_type="live_reconciliation_watchdog",
                symbol="MICRO_LIVE",
                payload={
                    "status": "WARN",
                    "force_send": True,
                    "message": _watchdog_message(payload),
                    "report_path": payload.get("report_path"),
                },
            )
            payload["notification"] = delivery
            if _notification_delivered(delivery):
                _write_json(state_file, {"dedupe_key": dedupe_key, "last_sent_at": now.isoformat().replace("+00:00", "Z")})
                payload["notification_state"] = {"recorded": True, "state_file": _display_path(state_file)}
            else:
                payload["notification_state"] = {"recorded": False, "reason": "delivery_not_confirmed"}
        else:
            payload["notification"] = {"skipped": True, "reason": "cooldown_active"}

    if not bool(args.quiet):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 1 if alert_active and not bool(args.no_fail_exit) else 0


if __name__ == "__main__":
    raise SystemExit(main())
