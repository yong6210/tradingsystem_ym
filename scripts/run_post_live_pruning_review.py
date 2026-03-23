#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import func, select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.models import OrderSubmission
from app.db.session import SessionLocal, init_db


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review whether contract pruning should be reopened after a live cycle.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--report-dir", default="reports/operations/pruning_reviews")
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def _now() -> datetime:
    return datetime.now(UTC)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any] | list[Any]:
    url = f"{base_url.rstrip('/')}{path}"
    if query:
        url += f"?{urlencode(query, doseq=True)}"
    data: bytes | None = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url=url, data=data, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method.upper()} {path} failed with HTTP {exc.code}: {payload}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method.upper()} {path} failed: {exc.reason}") from exc


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Post-Live Pruning Review")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- symbol: {payload['symbol']}")
    lines.append(f"- days: {payload['days']}")
    lines.append(f"- decision: {payload['decision']}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- rationale: {payload['rationale']}")
    lines.append(f"- live_submission_count: {payload['db_live_activity']['live_submission_count']}")
    lines.append(f"- live_binance_submission_count: {payload['db_live_activity']['live_binance_submission_count']}")
    lines.append(f"- live_fill_like_submission_count: {payload['db_live_activity']['filled_like_submission_count']}")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    for row in payload["checks"]:
        lines.append(f"- [{row['status']}] {row['name']}: {row['message']}")
    lines.append("")
    lines.append("## Next Steps")
    lines.append("")
    for step in payload["next_steps"]:
        lines.append(f"- {step}")
    lines.append("")
    lines.append("## Raw Payload")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    lines.append("```")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    generated_at = _now()
    cutoff = generated_at - timedelta(days=max(args.days, 1))

    init_db()
    with SessionLocal() as db:
        live_submission_count = db.scalar(
            select(func.count())
            .select_from(OrderSubmission)
            .where(OrderSubmission.requested_live.is_(True), OrderSubmission.submitted_at >= cutoff)
        ) or 0
        live_binance_submission_count = db.scalar(
            select(func.count())
            .select_from(OrderSubmission)
            .where(
                OrderSubmission.requested_live.is_(True),
                OrderSubmission.adapter == "binance",
                OrderSubmission.submitted_at >= cutoff,
            )
        ) or 0
        filled_like_submission_count = db.scalar(
            select(func.count())
            .select_from(OrderSubmission)
            .where(
                OrderSubmission.requested_live.is_(True),
                OrderSubmission.state.in_(("FILLED", "PARTIALLY_FILLED")),
                OrderSubmission.submitted_at >= cutoff,
            )
        ) or 0

    dashboard = _request_json(
        args.base_url,
        "GET",
        "/execution/operator-dashboard",
        query={"symbol": args.symbol, "universe": args.universe, "days": args.days},
    )
    validation = _request_json(
        args.base_url,
        "POST",
        "/validation/report",
        query={"symbol": args.symbol},
    )
    checklist = _request_json(
        args.base_url,
        "POST",
        "/operations/checklist",
        query={"symbol": args.symbol},
    )

    reconcile_summary = dashboard.get("recent_reconciliation_summary") or {}
    checks = [
        {
            "name": "actual_live_submissions_present",
            "status": "PASS" if live_submission_count > 0 else "FAIL",
            "message": f"live submissions in lookback={live_submission_count}",
        },
        {
            "name": "actual_binance_live_path_present",
            "status": "PASS" if live_binance_submission_count > 0 else "FAIL",
            "message": f"binance live submissions in lookback={live_binance_submission_count}",
        },
        {
            "name": "actual_live_fill_path_present",
            "status": "PASS" if filled_like_submission_count > 0 else "FAIL",
            "message": f"live filled/partial submissions in lookback={filled_like_submission_count}",
        },
        {
            "name": "reconciliation_recently_healthy",
            "status": "PASS" if bool(reconcile_summary.get("healthy", False)) else "FAIL",
            "message": f"healthy={reconcile_summary.get('healthy', False)} severity={reconcile_summary.get('highest_severity', 'UNKNOWN')}",
        },
        {
            "name": "validation_not_no_go",
            "status": "PASS" if str(validation.get("deployment_go_no_go", "")) != "NO_GO" else "FAIL",
            "message": f"{validation.get('deployment_go_no_go', '')}: {validation.get('deployment_message', '')}",
        },
        {
            "name": "checklist_not_no_go",
            "status": "PASS" if str(checklist.get("deployment_go_no_go", "")) != "NO_GO" else "FAIL",
            "message": f"{checklist.get('deployment_go_no_go', '')}: {checklist.get('deployment_message', '')}",
        },
    ]

    should_reopen = (
        live_submission_count > 0
        and live_binance_submission_count > 0
        and filled_like_submission_count > 0
        and bool(reconcile_summary.get("healthy", False))
        and str(validation.get("deployment_go_no_go", "")) != "NO_GO"
        and str(checklist.get("deployment_go_no_go", "")) != "NO_GO"
    )
    decision = "REOPEN_PRUNING_REVIEW" if should_reopen else "KEEP_OPTIONAL_HOLD"
    rationale = (
        "At least one actual Binance live trading cycle exists, with fill-like activity and healthy reconciliation."
        if should_reopen
        else "No complete live operating cycle evidence yet; keep pruning review deferred."
    )
    next_steps = (
        [
            "Open the contract pruning review backlog and compare duplicated top-level vs nested execution/validation payloads.",
            "Audit operator-facing fields after the first live cycle before removing passthrough fields.",
        ]
        if should_reopen
        else [
            "Keep contract pruning on optional hold until at least one actual Binance live cycle completes.",
            "Rerun this review after a session with real requested_live=true Binance submissions and at least one fill-like outcome.",
        ]
    )

    payload = {
        "generated_at": generated_at.isoformat(),
        "symbol": args.symbol.upper(),
        "days": args.days,
        "decision": decision,
        "rationale": rationale,
        "checks": checks,
        "db_live_activity": {
            "cutoff": cutoff.isoformat(),
            "live_submission_count": int(live_submission_count),
            "live_binance_submission_count": int(live_binance_submission_count),
            "filled_like_submission_count": int(filled_like_submission_count),
        },
        "operator_dashboard_summary": {
            "execution_mode": dashboard.get("execution_mode", ""),
            "auto_trading_enabled": dashboard.get("auto_trading_enabled", False),
            "new_entries_allowed": dashboard.get("new_entries_allowed", False),
            "blocking_reason_code": dashboard.get("blocking_reason_code", ""),
            "blocking_reason_message": dashboard.get("blocking_reason_message", ""),
            "recent_reconciliation_summary": reconcile_summary,
        },
        "validation_summary": {
            "deployment_go_no_go": validation.get("deployment_go_no_go", ""),
            "deployment_code": validation.get("deployment_code", ""),
            "deployment_message": validation.get("deployment_message", ""),
            "playbook_go_no_go": validation.get("playbook_go_no_go", ""),
            "playbook_action": validation.get("playbook_action", ""),
        },
        "checklist_summary": {
            "deployment_go_no_go": checklist.get("deployment_go_no_go", ""),
            "deployment_code": checklist.get("deployment_code", ""),
            "deployment_message": checklist.get("deployment_message", ""),
            "playbook_go_no_go": checklist.get("playbook_go_no_go", ""),
            "playbook_action": checklist.get("playbook_action", ""),
        },
        "next_steps": next_steps,
    }

    if not args.no_write_report:
        ts = generated_at.strftime("%Y%m%dT%H%M%SZ")
        report_path = ROOT_DIR / args.report_dir / f"post_live_pruning_review_{args.symbol.upper()}_{ts}.md"
        _write_report(report_path, payload)
        payload["report_path"] = str(report_path.relative_to(ROOT_DIR))

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
