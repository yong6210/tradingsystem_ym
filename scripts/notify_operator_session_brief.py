#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.notification_dispatcher import NotificationDispatcher


BRIEF_SCRIPT = ROOT_DIR / "scripts" / "generate_operator_session_brief.py"


def _env_default(name: str, fallback: str) -> str:
    value = os.environ.get(name)
    if value is None:
        return fallback
    return value


def _env_flag(name: str) -> bool:
    return _env_default(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def _default_state_file(*, brief_mode: str, channel: str) -> Path:
    mode_slug = brief_mode.replace("-", "_")
    channel_slug = channel.replace("-", "_")
    return ROOT_DIR / "reports" / "operations" / "operator_session_briefs" / f"last_alert_state_{mode_slug}_{channel_slug}.json"


def _default_latest_run_file(*, brief_mode: str) -> Path:
    mode_slug = brief_mode.replace("-", "_")
    return ROOT_DIR / "reports" / "operations" / "operator_session_briefs" / f"latest_operator_session_brief_{mode_slug}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate or read the latest operator session brief and send a concise handoff message when state changes."
    )
    parser.add_argument("--symbol", default=_env_default("OPERATOR_BRIEF_SYMBOL", "BTCUSDC"))
    parser.add_argument("--universe", default=_env_default("OPERATOR_BRIEF_UNIVERSE", "usdc_perp_top30"))
    parser.add_argument("--days", type=int, default=int(_env_default("OPERATOR_BRIEF_DAYS", "7")))
    parser.add_argument("--portfolio-limit", type=int, default=int(_env_default("OPERATOR_BRIEF_PORTFOLIO_LIMIT", "5")))
    parser.add_argument("--intent-limit", type=int, default=int(_env_default("OPERATOR_BRIEF_INTENT_LIMIT", "5")))
    parser.add_argument("--reconcile-limit", type=int, default=int(_env_default("OPERATOR_BRIEF_RECONCILE_LIMIT", "5")))
    parser.add_argument(
        "--state-file",
        default=_env_default("OPERATOR_BRIEF_STATE_FILE", ""),
    )
    parser.add_argument(
        "--latest-run-file",
        default=_env_default("OPERATOR_BRIEF_LATEST_RUN_FILE", ""),
    )
    parser.add_argument("--channel", choices=["discord", "system"], default=_env_default("OPERATOR_BRIEF_CHANNEL", "system"))
    parser.add_argument("--brief-mode", choices=["shift-start", "shift-end"], default=_env_default("OPERATOR_BRIEF_MODE", "shift-start"))
    parser.add_argument("--webhook-url", default=_env_default("OPERATOR_BRIEF_DISCORD_WEBHOOK_URL", ""))
    parser.add_argument("--allow-live-send", action="store_true")
    parser.add_argument("--force-send", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.allow_live_send and _env_flag("OPERATOR_BRIEF_ALLOW_LIVE_SEND"):
        args.allow_live_send = True
    if not args.force_send and _env_default("OPERATOR_BRIEF_FORCE_SEND", "0") == "1":
        args.force_send = True
    if not args.dry_run and _env_flag("OPERATOR_BRIEF_DRY_RUN"):
        args.dry_run = True
    return args


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"state file is invalid: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_brief(args: argparse.Namespace) -> dict[str, Any]:
    command = [
        sys.executable,
        str(BRIEF_SCRIPT),
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
        raise RuntimeError(f"brief script failed: {stderr}")
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("brief payload must be an object")
    return payload


def _alert_state(brief: dict[str, Any]) -> dict[str, Any]:
    snapshot = brief.get("snapshot") or {}
    dashboard = snapshot.get("dashboard_summary") or {}
    validation = snapshot.get("validation_summary") or {}
    checklist = snapshot.get("checklist_summary") or {}
    funnel = snapshot.get("signal_funnel_snapshot") or {}
    sections = snapshot.get("operator_ui_sections") or {}
    return {
        "symbol": str(brief.get("symbol") or ""),
        "universe": str(brief.get("universe") or ""),
        "channel": "",
        "brief_mode": "",
        "brief_status": str(brief.get("brief_status") or ""),
        "headline": str(brief.get("headline") or ""),
        "deployment_alignment": str(snapshot.get("deployment_alignment") or ""),
        "playbook_alignment": str(snapshot.get("playbook_alignment") or ""),
        "top_operator_action": str(dashboard.get("top_operator_action") or ""),
        "dashboard_go_no_go": str(dashboard.get("deployment_go_no_go") or ""),
        "validation_go_no_go": str(validation.get("deployment_go_no_go") or ""),
        "checklist_go_no_go": str(checklist.get("deployment_go_no_go") or ""),
        "dashboard_playbook_action": str(dashboard.get("playbook_action") or ""),
        "validation_playbook_action": str(validation.get("playbook_action") or ""),
        "checklist_playbook_action": str(checklist.get("playbook_action") or ""),
        "research_action": str(funnel.get("research_action") or ""),
        "top_family_bottleneck": str(funnel.get("top_family_bottleneck") or ""),
        "top_session_bottleneck": str(funnel.get("top_session_bottleneck") or ""),
        "ui_all_present": bool(sections.get("all_present")),
        "brief_report_path": str(brief.get("report_path") or ""),
        "snapshot_report_path": str(snapshot.get("report_path") or ""),
    }


def _changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return True
    keys = (
        "channel",
        "brief_mode",
        "brief_status",
        "headline",
        "deployment_alignment",
        "playbook_alignment",
        "top_operator_action",
        "dashboard_go_no_go",
        "validation_go_no_go",
        "checklist_go_no_go",
        "dashboard_playbook_action",
        "validation_playbook_action",
        "checklist_playbook_action",
        "research_action",
        "top_family_bottleneck",
        "top_session_bottleneck",
        "ui_all_present",
    )
    return any(previous.get(key) != current.get(key) for key in keys)


def _render_message(brief: dict[str, Any]) -> str:
    return _render_shift_start_message(brief)


def _render_shift_start_message(brief: dict[str, Any]) -> str:
    snapshot = brief.get("snapshot") or {}
    dashboard = snapshot.get("dashboard_summary") or {}
    validation = snapshot.get("validation_summary") or {}
    checklist = snapshot.get("checklist_summary") or {}
    sections = snapshot.get("operator_ui_sections") or {}
    funnel = snapshot.get("signal_funnel_snapshot") or {}
    lines = [
        "Operator session handoff",
        f"- brief_status: {brief.get('brief_status')}",
        f"- headline: {brief.get('headline')}",
        (
            f"- deployment: dashboard={dashboard.get('deployment_go_no_go')} "
            f"/ validation={validation.get('deployment_go_no_go')} "
            f"/ checklist={checklist.get('deployment_go_no_go')}"
        ),
        (
            f"- playbook: dashboard={dashboard.get('playbook_action')} "
            f"/ validation={validation.get('playbook_action')} "
            f"/ checklist={checklist.get('playbook_action')}"
        ),
        f"- top_operator_action: {dashboard.get('top_operator_action')}",
        (
            f"- research/funnel: action={funnel.get('research_action')} "
            f"| family_bottleneck={funnel.get('top_family_bottleneck')} "
            f"| session_bottleneck={funnel.get('top_session_bottleneck')}"
        ),
        f"- operator_ui_sections_ready: {sections.get('all_present')}",
        f"- brief_report: {brief.get('report_path') or 'missing'}",
        f"- snapshot_report: {snapshot.get('report_path') or 'missing'}",
    ]
    for step in brief.get("next_steps") or []:
        lines.append(f"- next_step: {step}")
    return "\n".join(lines)

def _render_shift_end_message(brief: dict[str, Any]) -> str:
    snapshot = brief.get("snapshot") or {}
    dashboard = snapshot.get("dashboard_summary") or {}
    validation = snapshot.get("validation_summary") or {}
    checklist = snapshot.get("checklist_summary") or {}
    funnel = snapshot.get("signal_funnel_snapshot") or {}
    lines = [
        "Operator shift-end summary",
        f"- closing_status: {brief.get('brief_status')}",
        f"- closing_headline: {brief.get('headline')}",
        (
            f"- closing_alignment: deployment={snapshot.get('deployment_alignment')} "
            f"| playbook={snapshot.get('playbook_alignment')}"
        ),
        (
            f"- final_surface: dashboard={dashboard.get('deployment_go_no_go')} "
            f"/ validation={validation.get('deployment_go_no_go')} "
            f"/ checklist={checklist.get('deployment_go_no_go')}"
        ),
        f"- final_top_action: {dashboard.get('top_operator_action')}",
        (
            f"- carryover_focus: research={funnel.get('research_action')} "
            f"| family_bottleneck={funnel.get('top_family_bottleneck')} "
            f"| session_bottleneck={funnel.get('top_session_bottleneck')}"
        ),
        f"- handoff_brief: {brief.get('report_path') or 'missing'}",
        f"- supporting_snapshot: {snapshot.get('report_path') or 'missing'}",
    ]
    for step in brief.get("next_steps") or []:
        lines.append(f"- carryover_step: {step}")
    return "\n".join(lines)


def _render_message(brief: dict[str, Any], *, brief_mode: str) -> str:
    if brief_mode == "shift-end":
        return _render_shift_end_message(brief)
    return _render_shift_start_message(brief)


def main() -> int:
    args = parse_args()
    state_file = (
        Path(args.state_file).resolve()
        if str(args.state_file).strip()
        else _default_state_file(brief_mode=args.brief_mode, channel=args.channel)
    )
    latest_run_file = (
        Path(args.latest_run_file).resolve()
        if str(args.latest_run_file).strip()
        else _default_latest_run_file(brief_mode=args.brief_mode)
    )
    brief = _run_brief(args)
    current = _alert_state(brief)
    current["channel"] = args.channel
    current["brief_mode"] = args.brief_mode
    previous = _read_json(state_file)
    changed = _changed(previous, current)

    result: dict[str, Any] = {
        "state_file": str(state_file),
        "channel": args.channel,
        "brief_mode": args.brief_mode,
        "brief_report_path": brief.get("report_path"),
        "snapshot_report_path": (brief.get("snapshot") or {}).get("report_path"),
        "current": current,
        "previous": previous,
        "changed": changed,
        "allow_live_send": bool(args.allow_live_send),
        "force_send": bool(args.force_send),
        "dry_run": bool(args.dry_run),
        "notified": False,
    }

    message = _render_message(brief, brief_mode=args.brief_mode)
    result["message"] = message

    if not changed and not args.force_send:
        _write_json(state_file, current)
        _write_json(latest_run_file, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.dry_run:
        _write_json(state_file, current)
        _write_json(latest_run_file, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if not args.allow_live_send:
        result["delivery"] = {
            "channel": args.channel,
            "delivered": False,
            "skipped": True,
            "reason": "live_send_not_allowed",
        }
        _write_json(latest_run_file, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    settings = get_settings()
    if args.webhook_url.strip():
        settings.alert_discord_webhook_url = args.webhook_url.strip()

    dispatcher = NotificationDispatcher(settings)
    delivery = dispatcher.dispatch(
        channel=args.channel,
        alert_type=f"operator_session_brief_{args.brief_mode.replace('-', '_')}",
        symbol=str(brief.get("symbol") or args.symbol).upper(),
        payload={"message": message},
    )
    result["delivery"] = delivery
    result["notified"] = bool(delivery.get("delivered"))
    _write_json(state_file, current)
    _write_json(latest_run_file, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
