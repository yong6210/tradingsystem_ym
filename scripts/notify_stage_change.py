#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Notify Discord when the operating stage or key blocker signals change."
    )
    parser.add_argument("--stage-file", default=str(ROOT_DIR / "reports/operations/stage_monitor/current_stage.json"))
    parser.add_argument(
        "--state-file",
        default=str(ROOT_DIR / "reports/operations/stage_monitor/last_alert_state.json"),
    )
    parser.add_argument("--webhook-url", default="")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_stage(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise RuntimeError(f"stage file is missing or invalid: {path}")
    return payload


def _webhook_url(cli_value: str) -> str:
    if cli_value.strip():
        return cli_value.strip()
    return str(get_settings().alert_discord_webhook_url or "").strip()


def _changed(previous: dict[str, Any] | None, current: dict[str, Any], key: str) -> bool:
    if previous is None:
        return False
    return previous.get(key) != current.get(key)


def _trial_runs_started(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    before = int(previous.get("trial_runs_written") or 0)
    after = int(current.get("trial_runs_written") or 0)
    return before == 0 and after > 0


def _winner_selected(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return False
    before = previous.get("selected_trial_run_id")
    after = current.get("selected_trial_run_id")
    return before is None and after is not None


def _manual_review_trigger(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    current_status = str(current.get("execution_degradation") or "").lower()
    if current_status != "manual_review":
        return False
    if previous is None:
        return True
    previous_status = str(previous.get("execution_degradation") or "").lower()
    return previous_status != "manual_review"


def _collect_events(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    if previous is None:
        events.append(
            {
                "type": "initial_snapshot",
                "title": "Initial stage snapshot",
                "body": f"Current stage is {current.get('stage')}.",
            }
        )
        return events

    if _changed(previous, current, "stage"):
        events.append(
            {
                "type": "stage_changed",
                "title": "Operating stage changed",
                "body": f"{previous.get('stage')} -> {current.get('stage')}",
            }
        )
    if _changed(previous, current, "close_only_active"):
        events.append(
            {
                "type": "close_only_changed",
                "title": "Close-only state changed",
                "body": f"{previous.get('close_only_active')} -> {current.get('close_only_active')}",
            }
        )
    if _changed(previous, current, "playbook_go_no_go"):
        events.append(
            {
                "type": "playbook_changed",
                "title": "Playbook go/no-go changed",
                "body": f"{previous.get('playbook_go_no_go')} -> {current.get('playbook_go_no_go')}",
            }
        )
    if _trial_runs_started(previous, current):
        events.append(
            {
                "type": "trial_runs_started",
                "title": "Lineage trial runs started",
                "body": f"trial_runs_written: {previous.get('trial_runs_written')} -> {current.get('trial_runs_written')}",
            }
        )
    if _winner_selected(previous, current):
        events.append(
            {
                "type": "winner_selected",
                "title": "Selected trial run became available",
                "body": f"selected_trial_run_id: {current.get('selected_trial_run_id')}",
            }
        )
    if _manual_review_trigger(previous, current):
        events.append(
            {
                "type": "execution_manual_review",
                "title": "Execution manual review required",
                "body": f"execution_degradation: {current.get('execution_degradation')}",
            }
        )
    return events


def _render_message(current: dict[str, Any], events: list[dict[str, str]]) -> str:
    lines = ["Trading engine stage monitor"]
    for event in events:
        lines.append(f"- {event['title']}: {event['body']}")
    lines.extend(
        [
            "",
            f"stage: {current.get('stage')}",
            f"close_only_active: {current.get('close_only_active')}",
            f"playbook_go_no_go: {current.get('playbook_go_no_go')}",
            f"deployment_go_no_go: {current.get('deployment_go_no_go')}",
            f"checklist_status: {current.get('checklist_status')}",
            f"eligible_closed_trades: {current.get('eligible_closed_trades')}",
            f"trial_runs_written: {current.get('trial_runs_written')}",
            f"selected_trial_run_id: {current.get('selected_trial_run_id')}",
            f"execution_degradation: {current.get('execution_degradation')}",
            f"top_operator_action: {current.get('top_operator_action')}",
            f"alpha_research_next_step: {current.get('alpha_research_next_step')}",
        ]
    )
    return "\n".join(lines)


def _post_discord(webhook_url: str, message: str) -> dict[str, Any]:
    payload = json.dumps({"content": message}).encode("utf-8")
    request = Request(
        url=webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return {"ok": True, "status": getattr(response, "status", 204)}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"discord webhook failed with HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"discord webhook failed: {exc.reason}") from exc


def main() -> int:
    args = parse_args()
    stage_file = Path(args.stage_file).resolve()
    state_file = Path(args.state_file).resolve()
    current = _load_stage(stage_file)
    previous = _read_json(state_file)
    events = _collect_events(previous, current)

    result: dict[str, Any] = {
        "stage_file": str(stage_file),
        "state_file": str(state_file),
        "current": current,
        "previous": previous,
        "events": events,
        "notified": False,
        "dry_run": bool(args.dry_run),
    }

    if not events:
        _write_json(state_file, current)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    message = _render_message(current, events)
    result["message"] = message

    if args.dry_run:
        _write_json(state_file, current)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    webhook_url = _webhook_url(args.webhook_url)
    if not webhook_url:
        result["warning"] = "discord webhook url is not configured"
        _write_json(state_file, current)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    delivery = _post_discord(webhook_url, message)
    result["notified"] = True
    result["delivery"] = delivery
    _write_json(state_file, current)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
