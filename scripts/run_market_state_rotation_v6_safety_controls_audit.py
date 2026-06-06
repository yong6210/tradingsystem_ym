#!/usr/bin/env python3
"""Normalize safety-control evidence for market-state rotation v6 canary gates."""

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

from scripts.run_market_state_rotation_v6_execution_shadow_audit import REQUIRED_SAFETY_CONTROLS


CONTROL_DESCRIPTIONS = {
    "kill_switch_verified": "Emergency lock or close-only path has been exercised and blocks new entries.",
    "max_daily_loss_verified": "Daily loss cap has been tested and blocks entries after the configured threshold.",
    "position_sync_verified": "Local plan state and exchange position reconciliation has passed recently.",
    "partial_fill_handling_verified": "Partial entry/exit fills are reconciled without over-sizing or duplicate exits.",
    "exchange_reject_handling_verified": "Exchange/API rejects are recorded, surfaced, and do not leave phantom exposure.",
    "reduce_only_exit_verified": "Exit orders use reduce-only or close-position semantics where applicable.",
    "leverage_cap_verified": "Exchange leverage is at or below the configured cap for all scoped symbols.",
    "idempotent_client_order_id_verified": "Repeated submissions with the same intent cannot create duplicate live orders.",
    "stale_signal_block_verified": "Signals outside the allowed execution window are blocked before submission.",
    "maintenance_window_block_verified": "Entries are blocked during configured maintenance or blackout windows.",
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


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on", "pass", "passed", "verified", "ok", "ready"}


def _raw_controls(evidence: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(evidence or {})
    controls = payload.get("controls")
    if isinstance(controls, dict):
        return dict(controls)
    return payload


def _normalize_control(
    name: str,
    raw: Any,
    *,
    now: datetime,
    max_evidence_age_days: int,
) -> dict[str, Any]:
    payload = dict(raw) if isinstance(raw, dict) else {"verified": raw}
    verified_at = _parse_ts(payload.get("verified_at") or payload.get("created_at") or payload.get("generated_at"))
    age_days = (
        round(max((now - verified_at).total_seconds(), 0.0) / 86400.0, 4)
        if verified_at is not None
        else None
    )
    stale = verified_at is None or age_days is None or age_days > max(1, int(max_evidence_age_days))
    evidence_text = str(payload.get("evidence") or payload.get("report_path") or payload.get("source") or "").strip()
    verified_value = (
        payload.get("verified")
        if "verified" in payload
        else payload.get("passed", payload.get("status", payload.get("overall_status")))
    )
    verified = _truthy(verified_value) and bool(evidence_text) and not stale
    blockers: list[str] = []
    if not _truthy(verified_value):
        blockers.append("not_verified")
    if not evidence_text:
        blockers.append("evidence_missing")
    if verified_at is None:
        blockers.append("verified_at_missing")
    elif stale:
        blockers.append("evidence_stale")
    return {
        "name": name,
        "verified": verified,
        "status": "pass" if verified else "missing",
        "description": CONTROL_DESCRIPTIONS.get(name, ""),
        "verified_at": verified_at.isoformat() if verified_at is not None else None,
        "age_days": age_days,
        "max_evidence_age_days": max(1, int(max_evidence_age_days)),
        "evidence": evidence_text or None,
        "source_payload": payload,
        "blockers": blockers,
    }


def build_safety_controls_report(
    evidence: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    max_evidence_age_days: int = 7,
) -> dict[str, Any]:
    normalized_now = (now or datetime.now(UTC)).astimezone(UTC)
    raw = _raw_controls(evidence)
    controls = [
        _normalize_control(
            name,
            raw.get(name),
            now=normalized_now,
            max_evidence_age_days=max_evidence_age_days,
        )
        for name in REQUIRED_SAFETY_CONTROLS
    ]
    missing_or_failed = [item["name"] for item in controls if not item["verified"]]
    normalized_controls = {
        item["name"]: {
            "verified": bool(item["verified"]),
            "status": item["status"],
            "verified_at": item["verified_at"],
            "evidence": item["evidence"],
            "blockers": list(item.get("blockers") or []),
        }
        for item in controls
    }
    return {
        "created_at": normalized_now.isoformat(),
        "overall_status": "PASS" if not missing_or_failed else "INCOMPLETE",
        "verified_count": len(REQUIRED_SAFETY_CONTROLS) - len(missing_or_failed),
        "required_count": len(REQUIRED_SAFETY_CONTROLS),
        "missing_or_failed": missing_or_failed,
        "controls": normalized_controls,
        "control_details": controls,
        "template": {
            name: {
                "verified": False,
                "verified_at": normalized_now.isoformat(),
                "evidence": CONTROL_DESCRIPTIONS.get(name, ""),
            }
            for name in REQUIRED_SAFETY_CONTROLS
        },
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Market State Rotation V6 Safety Controls Audit",
        "",
        f"- Status: `{report.get('overall_status')}`",
        f"- Verified: `{report.get('verified_count')}/{report.get('required_count')}`",
        f"- Missing or failed: `{', '.join(report.get('missing_or_failed') or [])}`",
        "",
        "## Controls",
        "",
    ]
    for item in list(report.get("control_details") or []):
        lines.append(
            f"- {item.get('name')}: `{item.get('status')}` age_days=`{item.get('age_days')}` "
            f"blockers=`{','.join(item.get('blockers') or [])}`"
        )
    lines.extend(["", "## Template", "", "```json"])
    lines.append(json.dumps({"controls": report.get("template")}, ensure_ascii=False, indent=2))
    lines.append("```")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize market-state rotation v6 safety controls evidence for execution shadow audit."
    )
    parser.add_argument("--evidence", default="")
    parser.add_argument("--max-evidence-age-days", type=int, default=7)
    parser.add_argument("--report-dir", default="reports/validation/diagnostics/market_state_rotation_v6_safety_controls")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evidence_path = Path(args.evidence) if args.evidence else None
    if evidence_path is not None and not evidence_path.is_absolute():
        evidence_path = ROOT_DIR / evidence_path
    evidence = _load_json(evidence_path) if evidence_path is not None else None
    report = build_safety_controls_report(
        evidence,
        max_evidence_age_days=max(1, int(args.max_evidence_age_days)),
    )
    if evidence_path is not None:
        report["input_evidence"] = _display_path(evidence_path)
    if args.write_report:
        report_dir = Path(args.report_dir)
        if not report_dir.is_absolute():
            report_dir = ROOT_DIR / report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_safety_controls.json"
        md_path = report_dir / "market_state_rotation_v6_safety_controls.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
