#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.db.session import SessionLocal, init_db
from app.services.live_order_lifecycle import LiveOrderLifecycleReporter
from app.services.notification_dispatcher import NotificationDispatcher
from scripts.operation_report_io import atomic_write_text, parse_report_generated_at
from scripts.run_micro_live_runtime_guard import _blocked_intent_diagnostics


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Alert when MICRO_LIVE intents accumulate but no live order is submitted.")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--min-intents", type=int, default=1)
    parser.add_argument("--cooldown-minutes", type=int, default=360)
    parser.add_argument("--channel", choices=["discord", "system"], default="discord")
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--force-notify", action="store_true")
    parser.add_argument("--report-dir", default="reports/operations/micro_live_no_order_watchdog")
    parser.add_argument("--state-file", default="reports/operations/micro_live_no_order_watchdog/state.json")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--no-fail-exit", action="store_true")
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


def _resolve_root_path(raw_path: str) -> Path:
    path = Path(str(raw_path or "")).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _atomic_write_text(path: Path, content: str) -> None:
    atomic_write_text(path, content)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))


def _top_reasons_text(top_reasons: dict[str, Any], *, limit: int = 4) -> str:
    if not top_reasons:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in list(top_reasons.items())[:limit])


def _diagnostic_actions_text(diagnostics: list[dict[str, Any]], *, limit: int = 4) -> str:
    if not diagnostics:
        return "validation gate와 rollout session gate를 먼저 확인"
    return ", ".join(f"{item.get('reason')}->{item.get('action')}" for item in diagnostics[:limit])


def _diagnostic_detail_text(diagnostics: list[dict[str, Any]]) -> str:
    for item in diagnostics:
        detail = dict(item.get("detail") or {})
        if detail:
            metrics = dict(detail.get("metrics") or {})
            parts = [
                f"cause={detail.get('primary_cause', '') or 'unknown'}",
                f"grade={detail.get('grade', '')}",
                f"risk={detail.get('risk_state', '')}/{detail.get('risk_reason', '')}",
                f"deployment={detail.get('deployment_code', '')}",
            ]
            if "sample_size" in metrics:
                parts.append(f"sample={metrics.get('sample_size')}")
            if "ev" in metrics or "expectancy_r" in metrics:
                parts.append(f"ev={metrics.get('expectancy_r', metrics.get('ev'))}")
            return ", ".join(parts)
    return ""


def evaluate_no_order_watchdog(*, lifecycle: dict[str, Any], min_intents: int) -> dict[str, Any]:
    summary = dict(lifecycle.get("summary") or {})
    live_intents = dict(summary.get("live_intents") or {})
    intent_count = _safe_int(live_intents.get("total"))
    submit_ready = _safe_int(live_intents.get("submit_ready"))
    blocked = _safe_int(live_intents.get("blocked"))
    submission_count = _safe_int(summary.get("submission_count"))
    requested_live_count = _safe_int(summary.get("requested_live_count"))
    rejected_or_error = _safe_int(summary.get("rejected_or_error_count"))
    top_reasons = dict(live_intents.get("top_block_reasons") or {})
    diagnostics = _blocked_intent_diagnostics(lifecycle)

    alert = False
    reason = "no_recent_live_intents"
    severity = "INFO"
    if intent_count >= max(1, int(min_intents)) and requested_live_count == 0:
        alert = True
        severity = "WARN"
        reason = "live_intents_without_live_order_submission"
    if submit_ready > 0 and submission_count == 0:
        alert = True
        severity = "FAIL"
        reason = "submit_ready_intents_without_submission"
    if rejected_or_error > 0:
        alert = True
        severity = "FAIL"
        reason = "live_submission_rejected_or_error"

    message = (
        f"최근 live intent {intent_count}건, live 주문 제출 {requested_live_count}건. "
        f"submit_ready={submit_ready}, blocked={blocked}, reasons={_top_reasons_text(top_reasons)}, "
        f"actions={_diagnostic_actions_text(diagnostics)}"
    )
    return {
        "alert": alert,
        "status": "ALERT" if alert else "OK",
        "severity": severity,
        "reason": reason,
        "message": message,
        "intent_count": intent_count,
        "submit_ready": submit_ready,
        "blocked": blocked,
        "submission_count": submission_count,
        "requested_live_count": requested_live_count,
        "rejected_or_error_count": rejected_or_error,
        "top_block_reasons": top_reasons,
        "blocked_intent_diagnostics": diagnostics,
        "first_block_detail_text": _diagnostic_detail_text(diagnostics),
    }


def _cooldown_allows(*, state_file: Path, dedupe_key: str, cooldown_minutes: int, now: datetime, force: bool) -> bool:
    if force:
        return True
    state = _read_json(state_file)
    if str(state.get("dedupe_key") or "") != dedupe_key:
        return True
    last_sent_raw = str(state.get("last_sent_at") or "")
    try:
        last_sent = datetime.fromisoformat(last_sent_raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    if last_sent.tzinfo is None:
        last_sent = last_sent.replace(tzinfo=UTC)
    return now - last_sent.astimezone(UTC) >= timedelta(minutes=max(1, int(cooldown_minutes)))


def _watchdog_message(payload: dict[str, Any]) -> str:
    evaluation = dict(payload.get("evaluation") or {})
    detail_text = str(evaluation.get("first_block_detail_text") or "")
    top_reasons = _top_reasons_text(dict(evaluation.get("top_block_reasons") or {}), limit=3)
    return "\n".join(
        [
            "MICRO_LIVE 주문 없음",
            (
                f"최근 {payload.get('window_days')}일: intent {evaluation.get('intent_count')}건 / "
                f"제출 {evaluation.get('requested_live_count')}건"
            ),
            f"원인: {top_reasons}",
            f"상세: {detail_text or '없음'}",
            f"다음: {_diagnostic_actions_text(list(evaluation.get('blocked_intent_diagnostics') or []), limit=2)}",
        ]
    )


def build_payload(*, days: int, limit: int, min_intents: int) -> dict[str, Any]:
    init_db()
    with SessionLocal() as db:
        lifecycle = LiveOrderLifecycleReporter(db).generate(days=days, live_only=True, limit=limit)
    evaluation = evaluate_no_order_watchdog(lifecycle=lifecycle, min_intents=min_intents)
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "window_days": max(1, int(days)),
        "min_intents": max(1, int(min_intents)),
        "evaluation": evaluation,
        "lifecycle_summary": dict(lifecycle.get("summary") or {}),
    }


def _write_report(path: Path, payload: dict[str, Any], *, atomic: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    evaluation = dict(payload.get("evaluation") or {})
    lines = [
        "# MICRO_LIVE No-Order Watchdog",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- status: {evaluation.get('status')}",
        f"- severity: {evaluation.get('severity')}",
        f"- reason: {evaluation.get('reason')}",
        f"- message: {evaluation.get('message')}",
        f"- first_block_detail: {evaluation.get('first_block_detail_text') or 'none'}",
        f"- actions: {_diagnostic_actions_text(list(evaluation.get('blocked_intent_diagnostics') or []))}",
        "",
        "```json",
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        "```",
    ]
    content = "\n".join(lines)
    if atomic:
        _atomic_write_text(path, content)
    else:
        _atomic_write_text(path, content)


def _write_latest_aliases(*, report_dir: Path, payload: dict[str, Any]) -> dict[str, str]:
    latest_md = report_dir / "latest.md"
    latest_json = report_dir / "latest.json"
    _write_report(latest_md, payload, atomic=True)
    _atomic_write_text(latest_json, json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return {
        "latest_report_path": _display_path(latest_md),
        "latest_json_path": _display_path(latest_json),
    }


def _notification_delivered(result: dict[str, Any]) -> bool:
    return _safe_bool(dict(result or {}).get("delivered"))


def main() -> int:
    args = parse_args()
    payload = build_payload(days=max(1, int(args.days)), limit=max(1, int(args.limit)), min_intents=max(1, int(args.min_intents)))
    if not args.no_write_report:
        generated = parse_report_generated_at(payload.get("generated_at"))
        report_dir = ROOT_DIR / args.report_dir
        report_path = report_dir / f"micro_live_no_order_watchdog_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
        payload["report_path"] = _display_path(report_path)
        payload["latest_report_path"] = _display_path(report_dir / "latest.md")
        payload["latest_json_path"] = _display_path(report_dir / "latest.json")
        _write_report(report_path, payload, atomic=True)
        payload.update(_write_latest_aliases(report_dir=report_dir, payload=payload))

    evaluation = dict(payload.get("evaluation") or {})
    alert_active = _safe_bool(evaluation.get("alert"))
    if bool(args.notify) and alert_active:
        state_file = _resolve_root_path(str(args.state_file))
        dedupe_key = f"{evaluation.get('reason')}:{_top_reasons_text(dict(evaluation.get('top_block_reasons') or {}), limit=4)}"
        now = datetime.now(UTC)
        if _cooldown_allows(
            state_file=state_file,
            dedupe_key=dedupe_key,
            cooldown_minutes=max(1, int(args.cooldown_minutes)),
            now=now,
            force=bool(args.force_notify),
        ):
            settings = get_settings()
            delivery = NotificationDispatcher(settings).dispatch(
                channel=str(args.channel),
                alert_type="entry_surface_alert",
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
            else:
                payload["notification_state"] = {
                    "skipped": True,
                    "reason": "delivery_not_confirmed",
                    "dedupe_key": dedupe_key,
                }
        else:
            payload["notification"] = {"skipped": True, "reason": "cooldown_active"}

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 1 if alert_active and not bool(args.no_fail_exit) else 0


if __name__ == "__main__":
    raise SystemExit(main())
