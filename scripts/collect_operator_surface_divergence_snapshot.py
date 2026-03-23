#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.main import app


EXPECTED_OPERATOR_UI_SECTIONS = (
    "Approval Divergence",
    "Validation Case Inspector",
    "Runtime Quality Inspector",
    "Signal Funnel Inspector",
    "Alpha Research Inspector",
    "Policy / Lock Inspector",
    "Intent / Exposure Inspector",
    "Mode / Deployment Inspector",
    "Approval Alignment Inspector",
    "Data Freshness / Source Inspector",
    "Portfolio Candidate Inspector",
    "Report Navigation",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect a dry-run snapshot of dashboard/validation/checklist divergence plus operator UI section readiness."
    )
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--portfolio-limit", type=int, default=5)
    parser.add_argument("--intent-limit", type=int, default=5)
    parser.add_argument("--reconcile-limit", type=int, default=5)
    parser.add_argument("--report-dir", default="reports/operations/operator_surface_divergence")
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def _now() -> datetime:
    return datetime.now(UTC)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _required_json(response: Any, method: str, path: str) -> dict[str, Any]:
    if response.status_code != 200:
        raise RuntimeError(f"{method} {path} failed with HTTP {response.status_code}: {response.text}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{method} {path} returned non-object payload")
    return payload


def _section_readiness(html: str) -> dict[str, Any]:
    present = [section for section in EXPECTED_OPERATOR_UI_SECTIONS if section in html]
    missing = [section for section in EXPECTED_OPERATOR_UI_SECTIONS if section not in html]
    return {
        "expected_sections": list(EXPECTED_OPERATOR_UI_SECTIONS),
        "present_sections": present,
        "missing_sections": missing,
        "all_present": not missing,
    }


def _alignment(values: list[str]) -> str:
    normalized = [value for value in values if value]
    if not normalized:
        return "UNKNOWN"
    return "ALIGNED" if len(set(normalized)) == 1 else "DIVERGED"


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Operator Surface Divergence Snapshot")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- symbol: {payload['symbol']}")
    lines.append(f"- universe: {payload['universe']}")
    lines.append(f"- days: {payload['days']}")
    lines.append(f"- deployment_alignment: {payload['deployment_alignment']}")
    lines.append(f"- playbook_alignment: {payload['playbook_alignment']}")
    lines.append("")
    lines.append("## Dashboard / Validation / Checklist")
    lines.append("")
    dashboard = payload["dashboard_summary"]
    validation = payload["validation_summary"]
    checklist = payload["checklist_summary"]
    lines.append(
        f"- dashboard: {dashboard['deployment_go_no_go']} / {dashboard['playbook_action']} / top_action={dashboard['top_operator_action']}"
    )
    lines.append(
        f"- validation: {validation['deployment_go_no_go']} / {validation['playbook_action']} / approval_topline_status={validation['approval_topline_status']}"
    )
    lines.append(
        f"- checklist: {checklist['deployment_go_no_go']} / {checklist['playbook_action']} / overall_status={checklist['overall_status']}"
    )
    lines.append("")
    lines.append("## Operator UI Sections")
    lines.append("")
    for section in payload["operator_ui_sections"]["present_sections"]:
        lines.append(f"- [PASS] {section}")
    for section in payload["operator_ui_sections"]["missing_sections"]:
        lines.append(f"- [FAIL] {section}")
    lines.append("")
    lines.append("## Signal Funnel Snapshot")
    lines.append("")
    funnel = payload["signal_funnel_snapshot"]
    lines.append(f"- research_action: {funnel['research_action']}")
    lines.append(f"- shadow_experiment: {funnel['shadow_experiment']}")
    lines.append(f"- governance_state: {funnel['governance_state']}")
    lines.append(f"- review_queue: {funnel['review_queue']}")
    lines.append(f"- remediation_queue: {funnel['remediation_queue']}")
    lines.append(f"- clearance_state: {funnel['clearance_state']}")
    lines.append(f"- reopen_queue: {funnel['reopen_queue']}")
    lines.append(f"- decision_brief: {funnel['decision_brief']}")
    lines.append(f"- auto_execution_stage: {funnel['auto_execution_stage']}")
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

    with TestClient(app) as client:
        dashboard = _required_json(
            client.get(
                "/execution/operator-dashboard",
                params={
                    "symbol": args.symbol,
                    "universe": args.universe,
                    "portfolio_limit": args.portfolio_limit,
                    "intent_limit": args.intent_limit,
                    "reconcile_limit": args.reconcile_limit,
                    "days": args.days,
                },
            ),
            "GET",
            "/execution/operator-dashboard",
        )
        validation = _required_json(
            client.post("/validation/report", params={"symbol": args.symbol}),
            "POST",
            "/validation/report",
        )
        checklist = _required_json(
            client.post("/operations/checklist", params={"symbol": args.symbol}),
            "POST",
            "/operations/checklist",
        )
        operator_ui_response = client.get(
            "/execution/operator-ui",
            params={"symbol": args.symbol, "universe": args.universe, "days": args.days},
        )
        if operator_ui_response.status_code != 200:
            raise RuntimeError(
                f"GET /execution/operator-ui failed with HTTP {operator_ui_response.status_code}: {operator_ui_response.text}"
            )
        operator_ui_html = operator_ui_response.text

    signal_funnel = dashboard.get("signal_funnel") or {}
    operator_action_priority = signal_funnel.get("operator_action_priority") or {}
    alpha_research_action = signal_funnel.get("alpha_research_recommended_action") or {}
    alpha_research_experiment = signal_funnel.get("alpha_research_top_shadow_experiment") or {}
    hard_block_summary = signal_funnel.get("hard_block_summary") or {}
    rollout_block_summary = signal_funnel.get("rollout_block_summary") or {}
    family_bottlenecks = signal_funnel.get("family_bottlenecks") or []
    regime_bottlenecks = signal_funnel.get("regime_bottlenecks") or []
    session_bottlenecks = signal_funnel.get("session_bottlenecks") or []
    deployment_alignment = _alignment(
        [
            str(dashboard.get("deployment_go_no_go", "")),
            str(validation.get("deployment_go_no_go", "")),
            str(checklist.get("deployment_go_no_go", "")),
        ]
    )
    playbook_alignment = _alignment(
        [
            str(dashboard.get("playbook_action", "")),
            str(validation.get("playbook_action", "")),
            str(checklist.get("playbook_action", "")),
        ]
    )
    operator_ui_sections = _section_readiness(operator_ui_html)

    next_steps: list[str] = []
    if deployment_alignment == "DIVERGED":
        next_steps.append("dashboard와 validation/checklist의 deployment_go_no_go 방향을 함께 읽고 Approval Divergence 배너 wording을 먼저 확인한다.")
    if playbook_alignment == "DIVERGED":
        next_steps.append("playbook_action drift가 있으면 rollout 승인보다 wording/source drift를 먼저 점검한다.")
    if not operator_ui_sections["all_present"]:
        next_steps.append("누락된 operator UI 홈 섹션을 regression으로 보고 execution_operator_ui와 smoke test를 다시 확인한다.")
    if not next_steps:
        next_steps.append("surface alignment와 operator UI home-section coverage가 현재 dry-run 기준으로 안정적이다.")

    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "symbol": args.symbol.upper(),
        "universe": args.universe,
        "days": args.days,
        "deployment_alignment": deployment_alignment,
        "playbook_alignment": playbook_alignment,
        "dashboard_summary": {
            "execution_mode": dashboard.get("execution_mode", ""),
            "new_entries_allowed": dashboard.get("new_entries_allowed", False),
            "deployment_go_no_go": dashboard.get("deployment_go_no_go", ""),
            "playbook_action": dashboard.get("playbook_action", ""),
            "top_operator_action": (operator_action_priority.get("top_action") or ""),
            "recent_intents": len(dashboard.get("recent_intents") or []),
            "open_orders": len(dashboard.get("open_orders") or []),
            "open_positions": len(dashboard.get("open_positions") or []),
        },
        "validation_summary": {
            "deployment_go_no_go": validation.get("deployment_go_no_go", ""),
            "deployment_code": validation.get("deployment_code", ""),
            "deployment_message": validation.get("deployment_message", ""),
            "playbook_action": validation.get("playbook_action", ""),
            "approval_topline_status": validation.get("approval_topline_status", ""),
        },
        "checklist_summary": {
            "deployment_go_no_go": checklist.get("deployment_go_no_go", ""),
            "deployment_code": checklist.get("deployment_code", ""),
            "deployment_message": checklist.get("deployment_message", ""),
            "playbook_action": checklist.get("playbook_action", ""),
            "overall_status": checklist.get("overall_status", ""),
            "blocking_failures": checklist.get("blocking_failures", 0),
            "manual_actions": checklist.get("manual_actions", 0),
            "warnings": checklist.get("warnings", 0),
        },
        "operator_ui_sections": operator_ui_sections,
        "signal_funnel_snapshot": {
            "research_action": (alpha_research_action.get("recommended_action") or ""),
            "shadow_experiment": (alpha_research_experiment.get("experiment_id") or ""),
            "governance_state": ((signal_funnel.get("promotion_governance") or {}).get("state") or ""),
            "review_queue": ((signal_funnel.get("promotion_review_queue") or {}).get("queue_state") or ""),
            "remediation_queue": ((signal_funnel.get("promotion_remediation_queue") or {}).get("queue_state") or ""),
            "clearance_state": ((signal_funnel.get("promotion_clearance_tracker") or {}).get("clearance_state") or ""),
            "reopen_queue": ((signal_funnel.get("promotion_reopen_queue") or {}).get("queue_state") or ""),
            "decision_brief": ((signal_funnel.get("promotion_decision_brief") or {}).get("brief_state") or ""),
            "auto_execution_stage": ((signal_funnel.get("auto_promotion_rollout_execution") or {}).get("execution_stage") or ""),
            "hard_gate_bottleneck": (hard_block_summary.get("top_reason") or ""),
            "softening_priority_queue": (signal_funnel.get("quality_softening_priorities") or []),
            "rollout_block_reason": (rollout_block_summary.get("top_reason") or ""),
            "top_family_bottleneck": ((family_bottlenecks[0] or {}).get("key") if family_bottlenecks else ""),
            "top_regime_bottleneck": ((regime_bottlenecks[0] or {}).get("key") if regime_bottlenecks else ""),
            "top_session_bottleneck": ((session_bottlenecks[0] or {}).get("key") if session_bottlenecks else ""),
        },
        "next_steps": next_steps,
    }

    if not args.no_write_report:
        ts = generated_at.strftime("%Y%m%dT%H%M%SZ")
        report_path = ROOT_DIR / args.report_dir / f"operator_surface_divergence_{args.symbol.upper()}_{ts}.md"
        _write_report(report_path, payload)
        payload["report_path"] = str(report_path.relative_to(ROOT_DIR))

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
