#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import run_live_reconciliation_watchdog
from scripts import run_micro_live_no_order_watchdog
from scripts import run_micro_live_ops_heartbeat
from scripts import run_session_impulse_retest_runtime_audit_report
from scripts.operation_report_io import atomic_write_text, display_path, parse_report_generated_at, write_latest_aliases


SCENARIOS = (
    "ops_missing_report",
    "ops_malformed_report",
    "ops_stale_report",
    "macro_short_horizon",
    "alert_delivery_failure_contract",
    "reconciliation_stale_submission_without_ledger",
    "no_order_submit_ready_gap",
    "runtime_audit_hard_failure_contract",
)


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
    parser = argparse.ArgumentParser(
        description="Run non-live MICRO_LIVE failure contract drills against operating guards.",
    )
    parser.add_argument("--scenario", action="append", choices=SCENARIOS, help="Scenario to run. Defaults to all.")
    parser.add_argument("--report-dir", default="reports/operations/micro_live_failure_drill")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--no-fail-exit", action="store_true")
    return parser.parse_args()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _display_path(path: Path) -> str:
    return display_path(path, ROOT_DIR)


def _result(name: str, *, ok: bool, observed: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "observed": observed,
        "expected": expected,
    }


def _first_issue(evaluation: dict[str, Any]) -> dict[str, Any]:
    for key in ("hard_failures", "failures", "issues", "warnings", "jobs"):
        rows = list(evaluation.get(key) or [])
        if rows:
            return dict(rows[0])
    return {}


def _ops_missing_report(tmp_dir: Path, now: datetime) -> dict[str, Any]:
    evaluation = run_micro_live_ops_heartbeat.evaluate_ops_heartbeat(
        now=now,
        jobs={
            "runtime_guard": {
                "pattern": str(tmp_dir / "missing" / "*.md"),
                "max_age_minutes": 15,
                "pass_statuses": {"PASS"},
            }
        },
    )
    issue = _first_issue(evaluation)
    observed = {
        "status": evaluation.get("status"),
        "reason": issue.get("reason"),
        "hard_failure_count": evaluation.get("hard_failure_count"),
    }
    expected = {"status": "FAIL", "reason": "missing_report"}
    return _result(
        "ops_missing_report",
        ok=observed["status"] == expected["status"] and observed["reason"] == expected["reason"],
        observed=observed,
        expected=expected,
    )


def _ops_malformed_report(tmp_dir: Path, now: datetime) -> dict[str, Any]:
    report = tmp_dir / "malformed.md"
    report.write_text("# malformed report\n", encoding="utf-8")
    evaluation = run_micro_live_ops_heartbeat.evaluate_ops_heartbeat(
        now=now,
        jobs={
            "runtime_guard": {
                "pattern": str(report),
                "max_age_minutes": 15,
                "pass_statuses": {"PASS"},
            }
        },
    )
    issue = _first_issue(evaluation)
    observed = {
        "status": evaluation.get("status"),
        "reason": issue.get("reason"),
        "content_status": issue.get("content_status"),
    }
    expected = {"status": "FAIL", "reason": "content_status_missing", "content_status": "FAIL"}
    return _result(
        "ops_malformed_report",
        ok=observed == expected,
        observed=observed,
        expected=expected,
    )


def _ops_stale_report(tmp_dir: Path, now: datetime) -> dict[str, Any]:
    report = tmp_dir / "runtime_guard.md"
    report.write_text("- overall_status: PASS\n", encoding="utf-8")
    stale_ts = (now - timedelta(minutes=60)).timestamp()
    os.utime(report, (stale_ts, stale_ts))
    evaluation = run_micro_live_ops_heartbeat.evaluate_ops_heartbeat(
        now=now,
        jobs={
            "runtime_guard": {
                "pattern": str(report),
                "max_age_minutes": 15,
                "pass_statuses": {"PASS"},
            }
        },
    )
    issue = _first_issue(evaluation)
    observed = {
        "status": evaluation.get("status"),
        "reason": issue.get("reason"),
        "freshness_status": issue.get("freshness_status"),
        "report_status": issue.get("report_status"),
    }
    expected = {
        "status": "FAIL",
        "reason": "stale_report",
        "freshness_status": "FAIL",
        "report_status": "PASS",
    }
    return _result(
        "ops_stale_report",
        ok=observed == expected,
        observed=observed,
        expected=expected,
    )


def _macro_short_horizon(tmp_dir: Path, now: datetime) -> dict[str, Any]:
    contract = tmp_dir / "micro_live_event_blackouts_short.json"
    contract.write_text(
        json.dumps(
            {
                "windows": [
                    {
                        "label": "CPI_short",
                        "start_utc": (now + timedelta(days=2)).isoformat().replace("+00:00", "Z"),
                        "end_utc": (now + timedelta(days=2, minutes=45)).isoformat().replace("+00:00", "Z"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    evaluation = run_micro_live_ops_heartbeat.evaluate_ops_heartbeat(
        now=now,
        jobs={
            "macro_calendar_blackouts": {
                "pattern": str(contract),
                "max_age_minutes": 15,
                "content_type": "macro_blackout_contract",
                "pass_statuses": {"PASS"},
                "min_horizon_days": 45,
            }
        },
    )
    issue = _first_issue(evaluation)
    observed = {
        "status": evaluation.get("status"),
        "reason": issue.get("reason"),
        "status_detail": issue.get("status_detail"),
        "report_status": issue.get("report_status"),
    }
    expected = {
        "status": "FAIL",
        "reason": "content_status_fail",
        "status_detail": "macro_blackout_horizon_below_minimum",
        "report_status": "FAIL",
    }
    return _result(
        "macro_short_horizon",
        ok=observed == expected,
        observed=observed,
        expected=expected,
    )


def _alert_delivery_failure_contract(_tmp_dir: Path, _now: datetime) -> dict[str, Any]:
    failed_delivery = {"delivered": False, "skipped": True, "reason": "discord_not_configured"}
    string_failed_delivery = {"delivered": "false", "skipped": "true", "reason": "discord_not_configured"}
    delivered = {"delivered": True}
    observed = {
        "heartbeat_failed_delivery": run_micro_live_ops_heartbeat._notification_delivered(failed_delivery),
        "heartbeat_string_failed_delivery": run_micro_live_ops_heartbeat._notification_delivered(string_failed_delivery),
        "heartbeat_success_delivery": run_micro_live_ops_heartbeat._notification_delivered(delivered),
        "no_order_failed_delivery": run_micro_live_no_order_watchdog._notification_delivered(failed_delivery),
        "reconciliation_failed_delivery": run_live_reconciliation_watchdog._notification_delivered(failed_delivery),
    }
    expected = {
        "heartbeat_failed_delivery": False,
        "heartbeat_string_failed_delivery": False,
        "heartbeat_success_delivery": True,
        "no_order_failed_delivery": False,
        "reconciliation_failed_delivery": False,
    }
    return _result(
        "alert_delivery_failure_contract",
        ok=observed == expected,
        observed=observed,
        expected=expected,
    )


def _reconciliation_stale_submission_without_ledger(_tmp_dir: Path, now: datetime) -> dict[str, Any]:
    evaluation = run_live_reconciliation_watchdog.evaluate_reconciliation_watchdog(
        submissions=[
            {
                "submission_id": "sub_drill_1",
                "symbol": "BTCUSDC",
                "client_order_id": "cid_drill_1",
                "state": "SUBMITTED",
                "submit_status": "SUBMITTED",
                "requested_live": True,
                "submitted_at": now - timedelta(minutes=10),
                "updated_at": now - timedelta(minutes=10),
            }
        ],
        ledgers=[],
        positions=[],
        events=[],
        now=now,
        stale_minutes=3,
        event_lookback_minutes=60,
    )
    issue = _first_issue(evaluation)
    observed = {
        "status": evaluation.get("status"),
        "severity": evaluation.get("severity"),
        "reason": evaluation.get("reason"),
        "issue_type": issue.get("type"),
    }
    expected = {
        "status": "ALERT",
        "severity": "FAIL",
        "reason": "missing_live_ledger_for_open_submission",
        "issue_type": "missing_live_ledger_for_open_submission",
    }
    return _result(
        "reconciliation_stale_submission_without_ledger",
        ok=observed == expected,
        observed=observed,
        expected=expected,
    )


def _no_order_submit_ready_gap(_tmp_dir: Path, _now: datetime) -> dict[str, Any]:
    evaluation = run_micro_live_no_order_watchdog.evaluate_no_order_watchdog(
        lifecycle={
            "summary": {
                "submission_count": 0,
                "requested_live_count": 0,
                "rejected_or_error_count": 0,
                "live_intents": {
                    "total": 2,
                    "submit_ready": 1,
                    "blocked": 1,
                    "top_block_reasons": {"validation_do_not_deploy": 1},
                },
            }
        },
        min_intents=1,
    )
    observed = {
        "status": evaluation.get("status"),
        "severity": evaluation.get("severity"),
        "reason": evaluation.get("reason"),
        "submit_ready": evaluation.get("submit_ready"),
    }
    expected = {
        "status": "ALERT",
        "severity": "FAIL",
        "reason": "submit_ready_intents_without_submission",
        "submit_ready": 1,
    }
    return _result(
        "no_order_submit_ready_gap",
        ok=observed == expected,
        observed=observed,
        expected=expected,
    )


def _runtime_audit_hard_failure_contract(_tmp_dir: Path, _now: datetime) -> dict[str, Any]:
    summary = run_session_impulse_retest_runtime_audit_report._status_summary(
        [
            {
                "phase": "auto_route",
                "status": "submit_error",
                "decision_code": "submit_ready",
            }
        ]
    )
    observed = {
        "overall_status": summary.get("overall_status"),
        "reason": summary.get("reason"),
        "hard_status_counts": summary.get("hard_status_counts"),
    }
    expected = {
        "overall_status": "FAIL",
        "reason": "runtime_audit_has_hard_route_failures",
        "hard_status_counts": {"submit_error": 1},
    }
    return _result(
        "runtime_audit_hard_failure_contract",
        ok=observed == expected,
        observed=observed,
        expected=expected,
    )


_SCENARIO_RUNNERS: dict[str, Callable[[Path, datetime], dict[str, Any]]] = {
    "ops_missing_report": _ops_missing_report,
    "ops_malformed_report": _ops_malformed_report,
    "ops_stale_report": _ops_stale_report,
    "macro_short_horizon": _macro_short_horizon,
    "alert_delivery_failure_contract": _alert_delivery_failure_contract,
    "reconciliation_stale_submission_without_ledger": _reconciliation_stale_submission_without_ledger,
    "no_order_submit_ready_gap": _no_order_submit_ready_gap,
    "runtime_audit_hard_failure_contract": _runtime_audit_hard_failure_contract,
}


def _selected_scenarios(raw: list[str] | None) -> list[str]:
    if not raw:
        return list(SCENARIOS)
    selected: list[str] = []
    for item in raw:
        if item not in selected:
            selected.append(item)
    return selected


def build_payload(*, scenarios: list[str] | None = None) -> dict[str, Any]:
    generated_at = datetime.now(UTC)
    selected = _selected_scenarios(scenarios)
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="micro_live_failure_drill_") as tmp_raw:
        tmp_dir = Path(tmp_raw)
        for scenario in selected:
            runner = _SCENARIO_RUNNERS[scenario]
            try:
                result = runner(tmp_dir, generated_at)
            except Exception as exc:  # pragma: no cover - defensive reporting path
                result = _result(
                    scenario,
                    ok=False,
                    observed={"exception": type(exc).__name__, "message": str(exc)},
                    expected={"exception": "none"},
                )
            results.append(result)
    failed = [row for row in results if not _safe_bool(row.get("ok"))]
    return {
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "overall_status": "PASS" if not failed else "FAIL",
        "scenario_count": len(results),
        "failed_count": len(failed),
        "passed_count": len(results) - len(failed),
        "results": results,
    }


def _write_report(path: Path, payload: dict[str, Any], *, atomic: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# MICRO_LIVE Failure Contract Drill",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- overall_status: {payload.get('overall_status')}",
        f"- scenario_count: {payload.get('scenario_count')}",
        f"- failed_count: {payload.get('failed_count')}",
        "",
        "## Scenarios",
        "",
    ]
    for row in list(payload.get("results") or []):
        status = "PASS" if row.get("ok") else "FAIL"
        lines.append(f"- {row.get('name')}: {status}")
    lines.extend(["", "```json", json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), "```"])
    content = "\n".join(lines)
    if atomic:
        atomic_write_text(path, content)
    else:
        atomic_write_text(path, content)


def main() -> int:
    args = parse_args()
    payload = build_payload(scenarios=args.scenario)
    if not args.no_write_report:
        generated = parse_report_generated_at(payload.get("generated_at"))
        report_dir = ROOT_DIR / args.report_dir
        report_path = report_dir / f"micro_live_failure_drill_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
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
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 1 if payload.get("overall_status") == "FAIL" and not bool(args.no_fail_exit) else 0


if __name__ == "__main__":
    raise SystemExit(main())
