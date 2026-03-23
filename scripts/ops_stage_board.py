#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_STAGE_FILE = ROOT_DIR / "reports/operations/stage_monitor/current_stage.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show the current operating stage from validation, checklist, and operator dashboard surfaces."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--alert-test-lookback-hours", type=int, default=24)
    parser.add_argument("--json", action="store_true", help="Print full JSON only.")
    parser.add_argument(
        "--stage-file",
        default=str(DEFAULT_STAGE_FILE),
        help="Write the latest stage snapshot to this path.",
    )
    parser.add_argument(
        "--no-write-stage",
        action="store_true",
        help="Do not persist the latest stage snapshot.",
    )
    return parser.parse_args()


def _request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    if query:
        url += f"?{urlencode(query, doseq=True)}"
    request = Request(url=url, headers={"Accept": "application/json"}, method=method.upper())
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method.upper()} {path} failed with HTTP {exc.code}: {payload}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method.upper()} {path} failed: {exc.reason}") from exc


def _write_stage_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _active_close_only(dashboard: dict[str, Any]) -> bool:
    locks = dashboard.get("active_locks")
    if not isinstance(locks, list):
        return False
    return any(str(item.get("reason_code") or "") == "close_only_active" for item in locks if isinstance(item, dict))


def _stage_from_payload(
    validation_report: dict[str, Any],
    checklist: dict[str, Any],
    dashboard: dict[str, Any],
) -> str:
    deployment = validation_report.get("deployment_approval_summary") or {}
    playbook_go_no_go = str(deployment.get("playbook_go_no_go") or "").upper()
    selected_trial_run_id = (
        (
            validation_report.get("strategy_v2_pbo_dsr_trial_writer_summary") or {}
        ).get("selected_trial_run_id")
    )
    sample_counts = (
        (validation_report.get("strategy_v2_pbo_dsr_trial_writer_summary") or {}).get("sample_counts") or {}
    )
    eligible_closed_trades = int(sample_counts.get("eligible_closed_trades") or 0)
    trial_runs_written = int(sample_counts.get("trial_runs_written") or 0)
    close_only_active = _active_close_only(dashboard)

    if (
        dashboard.get("new_entries_allowed") is False
        or close_only_active
        or playbook_go_no_go == "NO_GO"
        or str(checklist.get("overall_status") or "").upper() == "FAIL"
    ):
        return "0_BLOCKED"
    if trial_runs_written == 0 and eligible_closed_trades > 0:
        return "1_SAMPLE_COLLECTION"
    if selected_trial_run_id is not None or trial_runs_written > 0:
        return "2_LINEAGE_READY"
    if playbook_go_no_go in {"MANUAL_REVIEW", "GO"}:
        return "3_APPROVAL_REVIEW"
    return "CHECK_MANUALLY"


def _stage_message_fields(
    stage: str,
    validation_report: dict[str, Any],
    checklist: dict[str, Any],
    dashboard: dict[str, Any],
) -> dict[str, str]:
    deployment = validation_report.get("deployment_approval_summary") or {}
    playbook_go_no_go = str(deployment.get("playbook_go_no_go") or "").upper()
    close_only_active = _active_close_only(dashboard)
    execution_status = str(
        ((validation_report.get("execution_degradation_advisory_summary") or {}).get("status") or "")
    ).lower()
    trial_writer_summary = validation_report.get("strategy_v2_pbo_dsr_trial_writer_summary") or {}
    sample_counts = trial_writer_summary.get("sample_counts") or {}
    eligible_closed_trades = int(sample_counts.get("eligible_closed_trades") or 0)
    trial_runs_written = int(sample_counts.get("trial_runs_written") or 0)
    selected_trial_run_id = trial_writer_summary.get("selected_trial_run_id")

    blockers: list[str] = []
    if close_only_active:
        blockers.append("close_only_active")
    if playbook_go_no_go == "NO_GO":
        blockers.append("NO_GO")
    if execution_status == "manual_review":
        blockers.append("manual_review")

    if stage == "0_BLOCKED":
        return {
            "stage_reason": " + ".join(blockers) if blockers else "operator entry expansion is blocked",
            "next_step_hint": "resolve approval blocker and execution review before reopening entries",
            "sample_progress_hint": "lineage sample collection is not sufficient for a selected trial yet",
        }
    if stage == "1_SAMPLE_COLLECTION":
        return {
            "stage_reason": "eligible closed trades exist but no trial runs have been written",
            "next_step_hint": "continue paper lineage collection during active sessions",
            "sample_progress_hint": "waiting for trial_runs_written > 0 to start lineage selection",
        }
    if stage == "2_LINEAGE_READY":
        return {
            "stage_reason": (
                "selected trial is available"
                if selected_trial_run_id is not None
                else "trial runs have started and lineage selection can progress"
            ),
            "next_step_hint": "review validation and checklist surfaces for approval progression",
            "sample_progress_hint": (
                f"eligible_closed_trades={eligible_closed_trades}, trial_runs_written={trial_runs_written}"
            ),
        }
    if stage == "3_APPROVAL_REVIEW":
        return {
            "stage_reason": "lineage is ready enough for approval review but rollout still needs operator confirmation",
            "next_step_hint": "review validation and checklist before changing any runtime state",
            "sample_progress_hint": (
                f"eligible_closed_trades={eligible_closed_trades}, trial_runs_written={trial_runs_written}"
            ),
        }
    return {
        "stage_reason": "stage needs manual interpretation from validation, checklist, and dashboard surfaces",
        "next_step_hint": "review server-side operator surfaces directly",
        "sample_progress_hint": (
            f"eligible_closed_trades={eligible_closed_trades}, trial_runs_written={trial_runs_written}"
        ),
    }


def _build_stage_payload(
    validation_report: dict[str, Any],
    checklist: dict[str, Any],
    dashboard: dict[str, Any],
) -> dict[str, Any]:
    deployment = validation_report.get("deployment_approval_summary") or {}
    trial_writer_summary = validation_report.get("strategy_v2_pbo_dsr_trial_writer_summary") or {}
    sample_counts = trial_writer_summary.get("sample_counts") or {}
    execution_advisory = validation_report.get("execution_degradation_advisory_summary") or {}
    operator_action_priority = validation_report.get("operator_action_priority_summary") or {}
    alpha_research_pipeline = validation_report.get("alpha_research_pipeline_summary") or {}

    stage = _stage_from_payload(validation_report, checklist, dashboard)
    payload = {
        "stage": stage,
        "close_only_active": _active_close_only(dashboard),
        "playbook_go_no_go": deployment.get("playbook_go_no_go"),
        "deployment_go_no_go": deployment.get("deployment_go_no_go"),
        "checklist_status": checklist.get("overall_status"),
        "eligible_closed_trades": sample_counts.get("eligible_closed_trades"),
        "trial_runs_written": sample_counts.get("trial_runs_written"),
        "selected_trial_run_id": trial_writer_summary.get("selected_trial_run_id"),
        "execution_degradation": execution_advisory.get("status"),
        "top_operator_action": operator_action_priority.get("top_action"),
        "alpha_research_next_step": (
            alpha_research_pipeline.get("recommended_action")
            or alpha_research_pipeline.get("softening_top_bucket")
            or alpha_research_pipeline.get("promotion_top_bucket")
        ),
    }
    payload.update(_stage_message_fields(stage, validation_report, checklist, dashboard))
    return payload


def _print_human(payload: dict[str, Any]) -> None:
    print(f"stage: {payload['stage']}")
    print(f"stage_reason: {payload['stage_reason']}")
    print(f"next_step_hint: {payload['next_step_hint']}")
    print(f"sample_progress_hint: {payload['sample_progress_hint']}")
    print(f"close_only_active: {payload['close_only_active']}")
    print(f"playbook_go_no_go: {payload['playbook_go_no_go']}")
    print(f"deployment_go_no_go: {payload['deployment_go_no_go']}")
    print(f"checklist_status: {payload['checklist_status']}")
    print(f"eligible_closed_trades: {payload['eligible_closed_trades']}")
    print(f"trial_runs_written: {payload['trial_runs_written']}")
    print(f"selected_trial_run_id: {payload['selected_trial_run_id']}")
    print(f"execution_degradation: {payload['execution_degradation']}")
    print(f"top_operator_action: {payload['top_operator_action']}")
    print(f"alpha_research_next_step: {payload['alpha_research_next_step']}")


def main() -> int:
    args = parse_args()
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
        query={
            "symbol": args.symbol,
            "universe": args.universe,
            "limit": max(1, args.limit),
            "days": max(1, args.days),
            "alert_test_lookback_hours": max(1, args.alert_test_lookback_hours),
        },
    )
    dashboard = _request_json(
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
    payload = _build_stage_payload(validation_report, checklist, dashboard)
    if not args.no_write_stage:
        _write_stage_file(Path(args.stage_file).resolve(), payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        _print_human(payload)
        print("")
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
