#!/usr/bin/env python3
"""Collect existing operation reports into v6 safety-control evidence."""

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

from scripts.run_market_state_rotation_v6_execution_shadow_audit import REQUIRED_SAFETY_CONTROLS
from scripts.run_market_state_rotation_v6_safety_controls_audit import (
    CONTROL_DESCRIPTIONS,
    build_safety_controls_report,
)


DEFAULT_REPORT_PATHS = {
    "live_account_protection": "reports/operations/live_account_protection_audit/latest.json",
    "live_leverage_cap_sync": "reports/operations/live_leverage_cap_sync/latest.json",
    "live_reconciliation_watchdog": "reports/operations/live_reconciliation_watchdog/latest.json",
    "micro_live_runtime_guard": "reports/operations/micro_live_runtime_guard/latest.json",
    "micro_live_failure_drill": "reports/operations/micro_live_failure_drill/latest.json",
    "micro_live_synthetic_canary": "reports/operations/micro_live_synthetic_canary/latest.json",
}


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(payload) if isinstance(payload, dict) else None


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _resolve(path: str) -> Path:
    raw = Path(path)
    return raw if raw.is_absolute() else ROOT_DIR / raw


def _report_row(name: str, path: Path, *, now: datetime, max_report_age_hours: float) -> dict[str, Any]:
    payload = _load_json(path)
    if payload is None:
        return {
            "name": name,
            "path": _display_path(path),
            "available": False,
            "fresh": False,
            "payload": {},
            "status": "missing_or_invalid",
            "generated_at": None,
            "age_hours": None,
        }
    generated_at = _parse_ts(payload.get("generated_at"))
    age_hours = (
        round(max((now - generated_at).total_seconds(), 0.0) / 3600.0, 4)
        if generated_at is not None
        else None
    )
    fresh = generated_at is not None and age_hours is not None and age_hours <= max(0.01, float(max_report_age_hours))
    return {
        "name": name,
        "path": _display_path(path),
        "available": True,
        "fresh": fresh,
        "payload": payload,
        "status": "fresh" if fresh else "stale",
        "generated_at": generated_at.isoformat() if generated_at is not None else None,
        "age_hours": age_hours,
    }


def _status_ok(value: Any, ok_values: set[str] | None = None) -> bool:
    accepted = ok_values or {"OK", "PASS", "READY"}
    return str(value or "").strip().upper() in accepted


def _check_named(runtime_guard: dict[str, Any], name: str) -> dict[str, Any] | None:
    for item in list(runtime_guard.get("checks") or []):
        if isinstance(item, dict) and str(item.get("name") or "") == name:
            return dict(item)
    return None


def _all_checks_pass(runtime_guard: dict[str, Any], names: list[str]) -> tuple[bool, list[dict[str, Any]]]:
    rows = [_check_named(runtime_guard, name) for name in names]
    existing = [row for row in rows if row is not None]
    return (
        len(existing) == len(names)
        and all(str(row.get("status") or "").upper() == "PASS" for row in existing),
        existing,
    )


def _control(
    name: str,
    *,
    verified: bool,
    source: dict[str, Any] | None,
    evidence: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = dict(source or {})
    payload = {
        "verified": bool(verified),
        "status": "pass" if verified else "missing",
        "verified_at": source.get("generated_at"),
        "evidence": evidence,
        "source": source.get("name"),
        "source_report": source.get("path"),
        "description": CONTROL_DESCRIPTIONS.get(name, ""),
        "details": dict(details or {}),
    }
    if not verified:
        blockers: list[str] = []
        if not source:
            blockers.append("source_missing")
        elif not source.get("available"):
            blockers.append("source_report_missing_or_invalid")
        elif not source.get("fresh"):
            blockers.append("source_report_stale")
        else:
            blockers.append("source_report_not_passing")
        payload["blockers"] = blockers
    return payload


def _collect_controls(
    sources: dict[str, dict[str, Any]],
    *,
    manual_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    controls: dict[str, Any] = {}

    leverage = sources.get("live_leverage_cap_sync", {})
    leverage_payload = dict(leverage.get("payload") or {})
    leverage_ok = (
        bool(leverage.get("fresh"))
        and _status_ok(leverage_payload.get("overall_status"))
        and _safe_int(leverage_payload.get("pending_count")) == 0
        and _safe_int(leverage_payload.get("fail_count")) == 0
        and _safe_int(leverage_payload.get("target_leverage")) == _safe_int(leverage_payload.get("configured_leverage_cap"))
        and _safe_int(leverage_payload.get("target_leverage")) > 0
    )
    controls["leverage_cap_verified"] = _control(
        "leverage_cap_verified",
        verified=leverage_ok,
        source=leverage,
        evidence="Live leverage cap sync latest report is fresh, passing, and target equals configured cap.",
        details={
            "overall_status": leverage_payload.get("overall_status"),
            "pending_count": leverage_payload.get("pending_count"),
            "fail_count": leverage_payload.get("fail_count"),
            "target_leverage": leverage_payload.get("target_leverage"),
            "configured_leverage_cap": leverage_payload.get("configured_leverage_cap"),
        },
    )

    reconciliation = sources.get("live_reconciliation_watchdog", {})
    reconciliation_payload = dict(reconciliation.get("payload") or {})
    evaluation = dict(reconciliation_payload.get("evaluation") or {})
    reconciliation_ok = (
        bool(reconciliation.get("fresh"))
        and _status_ok(reconciliation_payload.get("overall_status"), {"OK", "PASS"})
        and _status_ok(evaluation.get("status"), {"OK", "PASS"})
        and _safe_int(evaluation.get("issue_count")) == 0
        and _safe_int(evaluation.get("fail_count")) == 0
    )
    controls["position_sync_verified"] = _control(
        "position_sync_verified",
        verified=reconciliation_ok,
        source=reconciliation,
        evidence="Live reconciliation watchdog latest report has no local/exchange position issues.",
        details={
            "overall_status": reconciliation_payload.get("overall_status"),
            "evaluation_status": evaluation.get("status"),
            "issue_count": evaluation.get("issue_count"),
            "fail_count": evaluation.get("fail_count"),
        },
    )

    protection = sources.get("live_account_protection", {})
    protection_payload = dict(protection.get("payload") or {})
    protection_ok = (
        bool(protection.get("fresh"))
        and _status_ok(protection_payload.get("overall_status"), {"OK", "PASS"})
        and _safe_int(protection_payload.get("fail_count")) == 0
        and _safe_int(protection_payload.get("issue_count")) == 0
    )
    controls["reduce_only_exit_verified"] = _control(
        "reduce_only_exit_verified",
        verified=protection_ok,
        source=protection,
        evidence="Live account protection audit is fresh and has no open-order or protection failures.",
        details={
            "overall_status": protection_payload.get("overall_status"),
            "fail_count": protection_payload.get("fail_count"),
            "issue_count": protection_payload.get("issue_count"),
            "open_position_count": protection_payload.get("open_position_count"),
        },
    )

    runtime = sources.get("micro_live_runtime_guard", {})
    runtime_payload = dict(runtime.get("payload") or {})
    partial_ok, partial_checks = _all_checks_pass(
        runtime_payload,
        ["live_protection_config", "session_impulse_retest_exit_contract"],
    )
    controls["partial_fill_handling_verified"] = _control(
        "partial_fill_handling_verified",
        verified=bool(runtime.get("fresh")) and partial_ok,
        source=runtime,
        evidence="Runtime guard confirms live protection config and partial/exit policy contract.",
        details={"checks": partial_checks},
    )
    maintenance_ok, maintenance_checks = _all_checks_pass(
        runtime_payload,
        ["macro_blackout_contract", "macro_blackout_live_coverage", "macro_blackout_horizon"],
    )
    controls["maintenance_window_block_verified"] = _control(
        "maintenance_window_block_verified",
        verified=bool(runtime.get("fresh")) and maintenance_ok,
        source=runtime,
        evidence="Runtime guard confirms macro blackout contract, live coverage, and horizon.",
        details={"checks": maintenance_checks},
    )

    failure = sources.get("micro_live_failure_drill", {})
    failure_payload = dict(failure.get("payload") or {})
    failure_ok = (
        bool(failure.get("fresh"))
        and _status_ok(failure_payload.get("overall_status"))
        and _safe_int(failure_payload.get("failed_count")) == 0
        and _safe_int(failure_payload.get("scenario_count")) >= 1
    )
    controls["exchange_reject_handling_verified"] = _control(
        "exchange_reject_handling_verified",
        verified=failure_ok,
        source=failure,
        evidence="Failure drill scenarios pass for malformed, stale, reconciliation, and submission-gap contracts.",
        details={
            "overall_status": failure_payload.get("overall_status"),
            "scenario_count": failure_payload.get("scenario_count"),
            "failed_count": failure_payload.get("failed_count"),
        },
    )
    controls["stale_signal_block_verified"] = _control(
        "stale_signal_block_verified",
        verified=failure_ok,
        source=failure,
        evidence="Failure drill includes stale-report and stale-submission contracts.",
        details={
            "overall_status": failure_payload.get("overall_status"),
            "scenario_count": failure_payload.get("scenario_count"),
            "failed_count": failure_payload.get("failed_count"),
        },
    )

    for name in REQUIRED_SAFETY_CONTROLS:
        controls.setdefault(
            name,
            _control(
                name,
                verified=False,
                source=None,
                evidence=f"No automatic source is trusted for {name}; provide explicit drill evidence.",
            ),
        )

    manual_controls = dict(dict(manual_evidence or {}).get("controls") or manual_evidence or {})
    for name, value in manual_controls.items():
        if name in REQUIRED_SAFETY_CONTROLS:
            payload = dict(value) if isinstance(value, dict) else {"verified": value}
            payload.setdefault("source", "manual_evidence")
            payload.setdefault("evidence", f"Manual evidence supplied for {name}.")
            controls[name] = payload
    return controls


def build_safety_evidence_collection_report(
    *,
    report_paths: dict[str, str] | None = None,
    manual_evidence: dict[str, Any] | None = None,
    now: datetime | None = None,
    max_report_age_hours: float = 24.0,
    max_evidence_age_days: int = 7,
) -> dict[str, Any]:
    normalized_now = (now or datetime.now(UTC)).astimezone(UTC)
    paths = dict(DEFAULT_REPORT_PATHS)
    paths.update(report_paths or {})
    sources = {
        name: _report_row(
            name,
            _resolve(path),
            now=normalized_now,
            max_report_age_hours=float(max_report_age_hours),
        )
        for name, path in sorted(paths.items())
    }
    controls = _collect_controls(sources, manual_evidence=manual_evidence)
    normalized = build_safety_controls_report(
        {"controls": controls},
        now=normalized_now,
        max_evidence_age_days=max(1, int(max_evidence_age_days)),
    )
    return {
        "created_at": normalized_now.isoformat(),
        "max_report_age_hours": float(max_report_age_hours),
        "max_evidence_age_days": max(1, int(max_evidence_age_days)),
        "source_reports": {
            name: {
                key: value
                for key, value in source.items()
                if key != "payload"
            }
            for name, source in sources.items()
        },
        "controls": controls,
        "normalized_safety_controls": normalized,
        "overall_status": normalized.get("overall_status"),
        "verified_count": normalized.get("verified_count"),
        "required_count": normalized.get("required_count"),
        "missing_or_failed": normalized.get("missing_or_failed"),
    }


def _load_optional_json(path_value: str) -> dict[str, Any] | None:
    if not path_value:
        return None
    path = _resolve(path_value)
    payload = _load_json(path)
    return payload if payload is not None else None


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Market State Rotation V6 Safety Evidence Collection",
        "",
        f"- Status: `{report.get('overall_status')}`",
        f"- Verified: `{report.get('verified_count')}/{report.get('required_count')}`",
        f"- Missing or failed: `{', '.join(report.get('missing_or_failed') or [])}`",
        "",
        "## Source Reports",
        "",
    ]
    for name, source in dict(report.get("source_reports") or {}).items():
        lines.append(
            f"- {name}: available=`{source.get('available')}` fresh=`{source.get('fresh')}` "
            f"age_hours=`{source.get('age_hours')}` path=`{source.get('path')}`"
        )
    lines.extend(["", "## Controls", ""])
    for name, control in dict(report.get("controls") or {}).items():
        lines.append(
            f"- {name}: verified=`{control.get('verified')}` source=`{control.get('source')}` "
            f"report=`{control.get('source_report')}`"
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect operation reports into market-state rotation v6 safety-control evidence."
    )
    parser.add_argument("--manual-evidence", default="")
    parser.add_argument("--max-report-age-hours", type=float, default=24.0)
    parser.add_argument("--max-evidence-age-days", type=int, default=7)
    parser.add_argument("--report-dir", default="reports/validation/diagnostics/market_state_rotation_v6_safety_evidence_collect")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_safety_evidence_collection_report(
        manual_evidence=_load_optional_json(args.manual_evidence),
        max_report_age_hours=float(args.max_report_age_hours),
        max_evidence_age_days=max(1, int(args.max_evidence_age_days)),
    )
    if args.write_report:
        report_dir = Path(args.report_dir)
        if not report_dir.is_absolute():
            report_dir = ROOT_DIR / report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_safety_evidence_collect.json"
        md_path = report_dir / "market_state_rotation_v6_safety_evidence_collect.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
