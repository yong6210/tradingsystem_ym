#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.notification_dispatcher import NotificationDispatcher


ACTIONABLE_ENTRY = "ACTIONABLE_ENTRY"
BLOCKED_SETUP = "BLOCKED_SETUP"
RESEARCH_ONLY_SETUP = "RESEARCH_ONLY_SETUP"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read the live portfolio budget surface and send a Discord message for actionable, blocked, "
            "or research-only entry setups."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--symbol", default="")
    parser.add_argument("--max-per-status", type=int, default=3)
    parser.add_argument("--channel", choices=["discord", "system"], default="discord")
    parser.add_argument(
        "--state-file",
        default=str(ROOT_DIR / "reports/operations/entry_surface/last_alert_state.json"),
    )
    parser.add_argument("--webhook-url", default="")
    parser.add_argument("--force-send", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"state file is not valid json: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"state file is invalid: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method.upper()} {path} failed with HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method.upper()} {path} failed: {exc.reason}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"{method.upper()} {path} returned a non-object payload")
    return payload


def _candidate_family(row: dict[str, Any]) -> str:
    direct = str(row.get("strategy_family") or "").strip()
    if direct:
        return direct
    thesis = row.get("thesis_fingerprint")
    if isinstance(thesis, dict):
        family = str(thesis.get("strategy_family") or "").strip()
        if family:
            return family
    return "unknown_family"


def _candidate_scope(payload: dict[str, Any], symbol: str) -> str:
    if symbol:
        return symbol.upper()
    return str(payload.get("universe") or "unknown_scope").upper()


def _matches_symbol(row: dict[str, Any], symbol: str) -> bool:
    if not symbol:
        return True
    return str(row.get("symbol") or "").upper() == symbol.upper()


def _filter_rows(rows: Any, *, symbol: str) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict) and _matches_symbol(row, symbol)]


def _blocked_topline_reason(payload: dict[str, Any]) -> tuple[str, str]:
    deployment_state = str(payload.get("deployment_go_no_go") or "MANUAL_REVIEW").upper()
    message = str(payload.get("deployment_message") or "Runtime gate requires manual review.").strip()
    if deployment_state == "NO_GO":
        return ("runtime_topline_no_go", message)
    return ("runtime_topline_manual_review", message)


def _sort_actionable_key(row: dict[str, Any]) -> tuple[float, float, float, str]:
    return (
        float(row.get("adjusted_rank_score", row.get("final_rank_score", 0.0)) or 0.0),
        float(row.get("expected_ev_at_recommended_size_r", row.get("expected_ev_r", 0.0)) or 0.0),
        float(row.get("recommended_risk_r", 0.0) or 0.0),
        str(row.get("symbol") or ""),
    )


def _sort_blocked_key(row: dict[str, Any]) -> tuple[float, float, str]:
    return (
        float(row.get("base_rank_score", row.get("final_rank_score", 0.0)) or 0.0),
        float(row.get("expected_ev_at_recommended_size_r", row.get("expected_ev_r", 0.0)) or 0.0),
        str(row.get("symbol") or ""),
    )


def _sort_research_key(row: dict[str, Any]) -> tuple[float, float, float, str]:
    return (
        float(row.get("expected_ev_at_recommended_size_r", row.get("expected_ev_r", 0.0)) or 0.0),
        float(row.get("alpha_research_softened_risk_r", 0.0) or 0.0),
        -float(row.get("alpha_research_gap", 0.0) or 0.0),
        str(row.get("symbol") or ""),
    )


def build_entry_snapshot(
    payload: dict[str, Any],
    *,
    symbol: str = "",
    max_per_status: int = 3,
) -> dict[str, Any]:
    accepted_rows = _filter_rows(payload.get("accepted_candidates"), symbol=symbol)
    blocked_rows = _filter_rows(payload.get("blocked_candidates"), symbol=symbol)
    research_rows = _filter_rows(payload.get("alpha_research_candidates"), symbol=symbol)

    research_plan_ids = {str(row.get("plan_id") or "") for row in research_rows}
    blocked_non_research = [row for row in blocked_rows if str(row.get("plan_id") or "") not in research_plan_ids]

    deployment_state = str(payload.get("deployment_go_no_go") or "MANUAL_REVIEW").upper()
    actionable_rows: list[dict[str, Any]] = []
    if deployment_state == "GO":
        actionable_rows = accepted_rows
    else:
        reason_code, reason_message = _blocked_topline_reason(payload)
        for row in accepted_rows:
            shadow = dict(row)
            shadow["block_reason"] = shadow.get("block_reason") or reason_code
            shadow["block_reason_message"] = shadow.get("block_reason_message") or reason_message
            blocked_non_research.append(shadow)

    actionable_rows = sorted(actionable_rows, key=_sort_actionable_key, reverse=True)[: max(0, int(max_per_status))]
    blocked_non_research = sorted(blocked_non_research, key=_sort_blocked_key, reverse=True)[: max(0, int(max_per_status))]
    research_rows = sorted(research_rows, key=_sort_research_key, reverse=True)[: max(0, int(max_per_status))]

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": _candidate_scope(payload, symbol),
        "deployment_go_no_go": deployment_state,
        "deployment_code": str(payload.get("deployment_code") or ""),
        "deployment_message": str(payload.get("deployment_message") or ""),
        "playbook_go_no_go": str(payload.get("playbook_go_no_go") or ""),
        "playbook_action": str(payload.get("playbook_action") or ""),
        "counts": {
            ACTIONABLE_ENTRY: len(actionable_rows),
            BLOCKED_SETUP: len(blocked_non_research),
            RESEARCH_ONLY_SETUP: len(research_rows),
        },
        "sections": {
            ACTIONABLE_ENTRY: actionable_rows,
            BLOCKED_SETUP: blocked_non_research,
            RESEARCH_ONLY_SETUP: research_rows,
        },
    }


def build_alert_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    sections = dict(snapshot.get("sections") or {})
    return {
        "scope": str(snapshot.get("scope") or ""),
        "deployment_go_no_go": str(snapshot.get("deployment_go_no_go") or ""),
        "deployment_code": str(snapshot.get("deployment_code") or ""),
        "playbook_go_no_go": str(snapshot.get("playbook_go_no_go") or ""),
        "playbook_action": str(snapshot.get("playbook_action") or ""),
        "counts": {
            ACTIONABLE_ENTRY: int((snapshot.get("counts") or {}).get(ACTIONABLE_ENTRY, 0) or 0),
            BLOCKED_SETUP: int((snapshot.get("counts") or {}).get(BLOCKED_SETUP, 0) or 0),
            RESEARCH_ONLY_SETUP: int((snapshot.get("counts") or {}).get(RESEARCH_ONLY_SETUP, 0) or 0),
        },
        "sections": {
            ACTIONABLE_ENTRY: [_row_alert_identity(ACTIONABLE_ENTRY, row) for row in sections.get(ACTIONABLE_ENTRY) or []],
            BLOCKED_SETUP: [_row_alert_identity(BLOCKED_SETUP, row) for row in sections.get(BLOCKED_SETUP) or []],
            RESEARCH_ONLY_SETUP: [
                _row_alert_identity(RESEARCH_ONLY_SETUP, row) for row in sections.get(RESEARCH_ONLY_SETUP) or []
            ],
        },
    }


def _row_alert_identity(status: str, row: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "symbol": str(row.get("symbol") or ""),
        "plan_id": str(row.get("plan_id") or ""),
        "direction": str(row.get("direction") or "").lower(),
        "entry_model": str(row.get("entry_model") or "").upper(),
        "family": _candidate_family(row),
    }
    if status == BLOCKED_SETUP:
        payload["reason_code"] = str(row.get("block_reason") or "")
    elif status == RESEARCH_ONLY_SETUP:
        payload["reason_code"] = str(row.get("alpha_research_reason") or row.get("block_reason") or "")
    return payload


def _extract_alert_state(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    nested = payload.get("alert_state")
    if isinstance(nested, dict):
        return nested
    return payload


def _format_candidate_line(status: str, row: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or "UNKNOWN")
    direction = str(row.get("direction") or "").lower() or "unknown"
    entry_model = str(row.get("entry_model") or "").upper() or "UNKNOWN"
    family = _candidate_family(row)
    risk_r = float(row.get("recommended_risk_r", 0.0) or 0.0)
    expected_summary = str(row.get("expected_summary") or "").strip()

    parts = [f"{symbol} {direction} {entry_model}", f"family={family}", f"risk={risk_r:.2f}R"]
    if expected_summary:
        parts.append(expected_summary)

    if status == BLOCKED_SETUP:
        message = str(row.get("block_reason_message") or row.get("block_reason") or "blocked").strip()
        parts.append(f"reason={message}")
    elif status == RESEARCH_ONLY_SETUP:
        message = str(
            row.get("alpha_research_reason_message")
            or row.get("alpha_research_reason")
            or row.get("block_reason_message")
            or "research-only"
        ).strip()
        softened_risk = float(row.get("alpha_research_softened_risk_r", 0.0) or 0.0)
        parts.append(f"reason={message}")
        parts.append(f"softened_risk={softened_risk:.2f}R")
    else:
        adjusted_rank = float(row.get("adjusted_rank_score", row.get("final_rank_score", 0.0)) or 0.0)
        parts.append(f"rank={adjusted_rank:.2f}")

    return "- " + " | ".join(parts)


def render_message(snapshot: dict[str, Any]) -> str:
    counts = dict(snapshot.get("counts") or {})
    sections = dict(snapshot.get("sections") or {})
    lines = [
        "Trading entry surface alert",
        f"scope: {snapshot.get('scope')}",
        (
            f"deployment: {snapshot.get('deployment_go_no_go')}/{snapshot.get('deployment_code')} "
            f"| playbook: {snapshot.get('playbook_go_no_go')} "
            f"| action: {snapshot.get('playbook_action')}"
        ),
        f"message: {snapshot.get('deployment_message')}",
        (
            f"counts: {ACTIONABLE_ENTRY}={counts.get(ACTIONABLE_ENTRY, 0)}, "
            f"{BLOCKED_SETUP}={counts.get(BLOCKED_SETUP, 0)}, "
            f"{RESEARCH_ONLY_SETUP}={counts.get(RESEARCH_ONLY_SETUP, 0)}"
        ),
    ]

    for status in (ACTIONABLE_ENTRY, BLOCKED_SETUP, RESEARCH_ONLY_SETUP):
        rows = sections.get(status) or []
        lines.append("")
        lines.append(f"{status}")
        if not rows:
            lines.append("- none")
            continue
        lines.extend(_format_candidate_line(status, row) for row in rows)
    return "\n".join(lines)


def _has_alertable_rows(snapshot: dict[str, Any]) -> bool:
    counts = dict(snapshot.get("counts") or {})
    return any(int(counts.get(status, 0) or 0) > 0 for status in (ACTIONABLE_ENTRY, BLOCKED_SETUP, RESEARCH_ONLY_SETUP))


def main() -> int:
    args = parse_args()
    state_file = Path(args.state_file).resolve()
    payload = _request_json(
        args.base_url,
        "GET",
        "/portfolio/budget",
        query={
            "universe": args.universe,
            "limit": args.limit,
            "write_report": "false",
        },
    )
    snapshot = build_entry_snapshot(
        payload,
        symbol=str(args.symbol or "").strip(),
        max_per_status=max(0, int(args.max_per_status)),
    )
    alert_state = build_alert_state(snapshot)
    state_warning = ""
    try:
        previous_payload = _read_json(state_file)
    except RuntimeError as exc:
        previous_payload = None
        state_warning = str(exc)
    previous_state = _extract_alert_state(previous_payload)

    result: dict[str, Any] = {
        "base_url": args.base_url,
        "universe": args.universe,
        "symbol": str(args.symbol or "").strip() or None,
        "channel": args.channel,
        "state_file": str(state_file),
        "dry_run": bool(args.dry_run),
        "force_send": bool(args.force_send),
        "snapshot": snapshot,
        "alert_state": alert_state,
        "notified": False,
        "state_written": False,
        "dedupe_suppressed": False,
    }
    if state_warning:
        result["state_warning"] = state_warning

    if not _has_alertable_rows(snapshot):
        result["reason"] = "no_alertable_rows"
        if not args.dry_run:
            _write_json(
                state_file,
                {
                    "updated_at": datetime.now(UTC).isoformat(),
                    "alert_state": alert_state,
                    "reason": "no_alertable_rows",
                },
            )
            result["state_written"] = True
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if previous_state == alert_state and not args.force_send:
        result["reason"] = "unchanged_surface_state"
        result["dedupe_suppressed"] = True
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    message = render_message(snapshot)
    result["message"] = message

    if args.dry_run:
        result["reason"] = "dry_run"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    settings = get_settings()
    if args.webhook_url.strip():
        settings.alert_discord_webhook_url = args.webhook_url.strip()

    dispatcher = NotificationDispatcher(settings)
    delivery = dispatcher.dispatch(
        channel=args.channel,
        alert_type="entry_surface_alert",
        symbol=str(snapshot.get("scope") or args.universe).upper(),
        payload={"message": message},
    )
    result["notified"] = bool(delivery.get("delivered"))
    result["delivery"] = delivery
    if bool(delivery.get("delivered")):
        _write_json(
            state_file,
            {
                "updated_at": datetime.now(UTC).isoformat(),
                "alert_state": alert_state,
                "delivery": {
                    "channel": delivery.get("channel"),
                    "reason": delivery.get("reason"),
                    "target": delivery.get("target"),
                },
            },
        )
        result["state_written"] = True
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
