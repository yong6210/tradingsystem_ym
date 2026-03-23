#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MICRO_LIVE preflight checks against the local API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--candidate-limit", type=int, default=10)
    parser.add_argument("--report-dir", default="reports/operations/micro_live_preflight")
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


def _truthy_ready(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status", "")).lower()
    checks = payload.get("checks") or {}
    return status == "ready" and all(bool(value) for value in checks.values())


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# MICRO_LIVE Preflight")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- symbol: {payload['symbol']}")
    lines.append(f"- universe: {payload['universe']}")
    lines.append(f"- overall_status: {payload['overall_status']}")
    lines.append("")
    lines.append("## Key Decision")
    lines.append("")
    lines.append(f"- result: {payload['overall_status']}")
    lines.append(f"- summary: {payload['summary_line']}")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    for item in payload["checks"]:
        lines.append(f"- [{item['status']}] {item['name']}: {item['message']}")
    lines.append("")
    lines.append("## Candidate")
    lines.append("")
    candidate = payload.get("candidate") or {}
    if candidate:
        lines.append(f"- plan_id: {candidate.get('plan_id', '')}")
        lines.append(f"- symbol: {candidate.get('symbol', '')}")
        lines.append(f"- family: {candidate.get('strategy_family', '')}")
        lines.append(f"- deployment: {candidate.get('deployment_go_no_go', '')}")
        lines.append(f"- expected_summary: {candidate.get('expected_summary', '')}")
    else:
        lines.append("- no candidate selected")
    lines.append("")
    lines.append("## Next Steps")
    lines.append("")
    for step in payload.get("next_steps", []):
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

    ready = _request_json(args.base_url, "GET", "/health/ready")
    dashboard = _request_json(
        args.base_url,
        "GET",
        "/execution/operator-dashboard",
        query={"symbol": args.symbol, "universe": args.universe, "days": args.days},
    )
    safety = _request_json(
        args.base_url,
        "GET",
        "/execution/safety-state",
        query={"symbol": args.symbol},
    )
    reconcile = _request_json(
        args.base_url,
        "POST",
        "/execution/reconcile",
        query={"apply_lock": "true", "auto_resolve": "true"},
        body={"symbol": args.symbol},
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
    alerts = _request_json(
        args.base_url,
        "GET",
        "/alerts/metrics",
        query={"days": args.days, "write_report": "false"},
    )
    scanner = _request_json(
        args.base_url,
        "GET",
        "/scanner/top",
        query={"universe": args.universe, "limit": args.candidate_limit},
    )

    candidate: dict[str, Any] | None = None
    if isinstance(scanner, list) and scanner:
        matching = [row for row in scanner if str(row.get("symbol", "")).upper() == args.symbol.upper()]
        candidate = matching[0] if matching else scanner[0]

    checks: list[dict[str, str]] = []
    checks.append(
        {
            "name": "health_ready",
            "status": _status(_truthy_ready(ready)),
            "message": f"health status={ready.get('status', 'unknown')} checks={ready.get('checks', {})}",
        }
    )
    checks.append(
        {
            "name": "auto_trading_enabled",
            "status": _status(bool(dashboard.get("auto_trading_enabled", False))),
            "message": f"execution_mode={dashboard.get('execution_mode', 'unknown')}",
        }
    )
    checks.append(
        {
            "name": "new_entries_allowed",
            "status": _status(bool(dashboard.get("new_entries_allowed", False))),
            "message": str(dashboard.get("blocking_reason_message") or "new entries allowed"),
        }
    )
    checks.append(
        {
            "name": "validation_language",
            "status": _status(str(validation.get("deployment_go_no_go", "")) in {"GO", "MANUAL_REVIEW"}),
            "message": f"{validation.get('deployment_go_no_go', '')}: {validation.get('deployment_message', '')}",
        }
    )
    checks.append(
        {
            "name": "checklist_language",
            "status": _status(str(checklist.get("deployment_go_no_go", "")) in {"GO", "MANUAL_REVIEW"}),
            "message": f"{checklist.get('deployment_go_no_go', '')}: {checklist.get('deployment_message', '')}",
        }
    )
    checks.append(
        {
            "name": "safety_state",
            "status": _status(
                not bool(safety.get("kill_switch_active", False))
                and not bool(safety.get("close_only_active", False))
                and not bool(safety.get("config_close_only_active", False))
            ),
            "message": f"kill={safety.get('kill_switch_active', False)} close_only={safety.get('close_only_active', False)} config_close_only={safety.get('config_close_only_active', False)}",
        }
    )
    reconcile_summary = reconcile if isinstance(reconcile, dict) else {}
    reconcile_healthy = bool(reconcile_summary.get("healthy", not bool(reconcile_summary.get("mismatches", []))))
    checks.append(
        {
            "name": "reconciliation",
            "status": _status(reconcile_healthy),
            "message": f"healthy={reconcile_summary.get('healthy', False)} severity={reconcile_summary.get('highest_severity', 'INFO')}",
        }
    )
    latest_validation_alert = (alerts.get("latest_validation_alert") or {}) if isinstance(alerts, dict) else {}
    checks.append(
        {
            "name": "alert_channel",
            "status": _status(bool(latest_validation_alert) or bool((alerts.get("overall") or {}).get("total", 0))),
            "message": f"latest_validation_alert={bool(latest_validation_alert)}",
        }
    )
    checks.append(
        {
            "name": "candidate_available",
            "status": _status(candidate is not None),
            "message": (
                f"{candidate.get('symbol', '')} {candidate.get('strategy_family', '')} {candidate.get('deployment_go_no_go', '')}"
                if candidate
                else "No accepted scanner candidate available."
            ),
        }
    )

    failed = [item for item in checks if item["status"] != "PASS"]
    overall_status = "READY_FOR_MICRO_LIVE" if not failed else "NOT_READY"
    next_steps = [item["message"] for item in failed] if failed else ["Proceed to the live go-live checklist and final operator sign-off."]
    summary_line = (
        "All preflight checks passed; MICRO_LIVE can proceed to final operator sign-off."
        if not failed
        else f"{len(failed)} blocking preflight check(s) remain."
    )

    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "symbol": args.symbol.upper(),
        "universe": args.universe,
        "overall_status": overall_status,
        "summary_line": summary_line,
        "checks": checks,
        "candidate": candidate or {},
        "health_ready": ready,
        "operator_dashboard": dashboard,
        "reconciliation": reconcile,
        "safety_state": safety,
        "validation_report": {
            "deployment_go_no_go": validation.get("deployment_go_no_go", ""),
            "deployment_code": validation.get("deployment_code", ""),
            "deployment_message": validation.get("deployment_message", ""),
            "playbook_go_no_go": validation.get("playbook_go_no_go", ""),
            "playbook_action": validation.get("playbook_action", ""),
        },
        "operations_checklist": {
            "deployment_go_no_go": checklist.get("deployment_go_no_go", ""),
            "deployment_code": checklist.get("deployment_code", ""),
            "deployment_message": checklist.get("deployment_message", ""),
            "playbook_go_no_go": checklist.get("playbook_go_no_go", ""),
            "playbook_action": checklist.get("playbook_action", ""),
        },
        "alert_metrics_summary": {
            "latest_validation_alert": latest_validation_alert,
            "overall": (alerts.get("overall") or {}) if isinstance(alerts, dict) else {},
        },
        "next_steps": next_steps,
    }

    if not args.no_write_report:
        ts = generated_at.strftime("%Y%m%dT%H%M%SZ")
        report_path = ROOT_DIR / args.report_dir / f"micro_live_preflight_{args.symbol.upper()}_{ts}.md"
        _write_report(report_path, payload)
        payload["report_path"] = str(report_path.relative_to(ROOT_DIR))

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
