#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
SNAPSHOT_SCRIPT = ROOT_DIR / "scripts" / "collect_operator_surface_divergence_snapshot.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a markdown operator session brief from the latest operator surface divergence snapshot."
    )
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--portfolio-limit", type=int, default=5)
    parser.add_argument("--intent-limit", type=int, default=5)
    parser.add_argument("--reconcile-limit", type=int, default=5)
    parser.add_argument("--report-dir", default="reports/operations/operator_session_briefs")
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def _now() -> datetime:
    return datetime.now(UTC)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _run_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    command = [
        sys.executable,
        str(SNAPSHOT_SCRIPT),
        "--symbol",
        args.symbol,
        "--universe",
        args.universe,
        "--days",
        str(args.days),
        "--portfolio-limit",
        str(args.portfolio_limit),
        "--intent-limit",
        str(args.intent_limit),
        "--reconcile-limit",
        str(args.reconcile_limit),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, cwd=str(ROOT_DIR))
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"snapshot script failed: {stderr}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"snapshot script returned invalid JSON: {completed.stdout}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("snapshot payload must be an object")
    return payload


def _brief_status(snapshot: dict[str, Any]) -> str:
    if not bool(((snapshot.get("operator_ui_sections") or {}).get("all_present"))):
        return "UI_REGRESSION_REVIEW"
    if str(snapshot.get("deployment_alignment") or "") == "DIVERGED":
        return "DEPLOYMENT_REVIEW_REQUIRED"
    if str(snapshot.get("playbook_alignment") or "") == "DIVERGED":
        return "PLAYBOOK_REVIEW_REQUIRED"
    return "ALIGNED_MONITOR"


def _headline(snapshot: dict[str, Any], status: str) -> str:
    dashboard = snapshot.get("dashboard_summary") or {}
    validation = snapshot.get("validation_summary") or {}
    checklist = snapshot.get("checklist_summary") or {}
    if status == "UI_REGRESSION_REVIEW":
        return "operator UI home-section regression review is required before trusting the home surface."
    if status == "DEPLOYMENT_REVIEW_REQUIRED":
        return (
            "dashboard and validation/checklist disagree on deployment posture; "
            f"dashboard={dashboard.get('deployment_go_no_go', '')}, "
            f"validation={validation.get('deployment_go_no_go', '')}, "
            f"checklist={checklist.get('deployment_go_no_go', '')}."
        )
    if status == "PLAYBOOK_REVIEW_REQUIRED":
        return (
            "deployment posture is aligned but playbook wording differs across surfaces; "
            "review operator wording drift before acting."
        )
    return "dashboard, validation, checklist, and operator UI coverage are aligned enough for normal monitoring."


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = payload["snapshot"]
    dashboard = snapshot["dashboard_summary"]
    validation = snapshot["validation_summary"]
    checklist = snapshot["checklist_summary"]
    sections = snapshot["operator_ui_sections"]
    funnel = snapshot["signal_funnel_snapshot"]

    lines: list[str] = []
    lines.append("# Operator Session Brief")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- symbol: {payload['symbol']}")
    lines.append(f"- universe: {payload['universe']}")
    lines.append(f"- days: {payload['days']}")
    lines.append(f"- brief_status: {payload['brief_status']}")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append(f"- summary: {payload['headline']}")
    lines.append(f"- top_operator_action: {dashboard.get('top_operator_action', '')}")
    lines.append(f"- snapshot_report: {snapshot.get('report_path', '')}")
    lines.append("")
    lines.append("## Surface Alignment")
    lines.append("")
    lines.append(f"- deployment_alignment: {snapshot.get('deployment_alignment', '')}")
    lines.append(f"- playbook_alignment: {snapshot.get('playbook_alignment', '')}")
    lines.append(
        f"- dashboard: {dashboard.get('deployment_go_no_go', '')} / {dashboard.get('playbook_action', '')} / mode={dashboard.get('execution_mode', '')}"
    )
    lines.append(
        f"- validation: {validation.get('deployment_go_no_go', '')} / {validation.get('playbook_action', '')} / approval_topline_status={validation.get('approval_topline_status', '')}"
    )
    lines.append(
        f"- checklist: {checklist.get('deployment_go_no_go', '')} / {checklist.get('playbook_action', '')} / overall_status={checklist.get('overall_status', '')}"
    )
    lines.append("")
    lines.append("## Operator UI Coverage")
    lines.append("")
    lines.append(f"- all_present: {sections.get('all_present', False)}")
    for section in sections.get("present_sections", []):
        lines.append(f"- [PASS] {section}")
    for section in sections.get("missing_sections", []):
        lines.append(f"- [FAIL] {section}")
    lines.append("")
    lines.append("## Promotion / Funnel Snapshot")
    lines.append("")
    lines.append(f"- research_action: {funnel.get('research_action', '')}")
    lines.append(f"- shadow_experiment: {funnel.get('shadow_experiment', '')}")
    lines.append(f"- governance_state: {funnel.get('governance_state', '')}")
    lines.append(f"- review_queue: {funnel.get('review_queue', '')}")
    lines.append(f"- remediation_queue: {funnel.get('remediation_queue', '')}")
    lines.append(f"- clearance_state: {funnel.get('clearance_state', '')}")
    lines.append(f"- reopen_queue: {funnel.get('reopen_queue', '')}")
    lines.append(f"- decision_brief: {funnel.get('decision_brief', '')}")
    lines.append(f"- auto_execution_stage: {funnel.get('auto_execution_stage', '')}")
    lines.append(f"- hard_gate_bottleneck: {funnel.get('hard_gate_bottleneck', '')}")
    lines.append(f"- top_family_bottleneck: {funnel.get('top_family_bottleneck', '')}")
    lines.append(f"- top_regime_bottleneck: {funnel.get('top_regime_bottleneck', '')}")
    lines.append(f"- top_session_bottleneck: {funnel.get('top_session_bottleneck', '')}")
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
    snapshot = _run_snapshot(args)
    brief_status = _brief_status(snapshot)
    headline = _headline(snapshot, brief_status)
    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "symbol": args.symbol.upper(),
        "universe": args.universe,
        "days": args.days,
        "brief_status": brief_status,
        "headline": headline,
        "next_steps": snapshot.get("next_steps") or [],
        "snapshot": snapshot,
    }

    if not args.no_write_report:
        ts = generated_at.strftime("%Y%m%dT%H%M%SZ")
        report_path = ROOT_DIR / args.report_dir / f"operator_session_brief_{args.symbol.upper()}_{ts}.md"
        _write_report(report_path, payload)
        payload["report_path"] = str(report_path.relative_to(ROOT_DIR))

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
