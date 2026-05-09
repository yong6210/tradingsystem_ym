#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.services.notification_dispatcher import NotificationDispatcher


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check operator session brief delivery channel readiness without sending notifications."
    )
    parser.add_argument(
        "--channels",
        default="system,discord",
        help="Comma-separated channels to inspect. Supported: system, discord, telegram, push",
    )
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument(
        "--report-dir",
        default=str(ROOT_DIR / "reports" / "operations" / "operator_session_briefs"),
    )
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def _now() -> datetime:
    return datetime.now(UTC)


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _resolve_root_path(raw_path: str | Path) -> Path:
    path = Path(raw_path).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


def _launchctl_executable() -> str:
    return shutil.which("launchctl") or "/bin/launchctl"


def _launchctl_getenv(name: str) -> str:
    completed = subprocess.run(
        [_launchctl_executable(), "getenv", name],
        capture_output=True,
        text=True,
        cwd=str(ROOT_DIR),
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


def _channel_readiness(channel: str, dispatcher: NotificationDispatcher) -> dict[str, Any]:
    settings = dispatcher.settings
    normalized = channel.strip().lower()
    issues: list[str] = []

    if normalized == "system":
        routes = dispatcher._configured_system_routes()
        if not routes:
            issues.append("system_no_routes_configured")
        return {
            "channel": "system",
            "configured": bool(routes),
            "healthy": bool(routes),
            "routes": routes,
            "issues": issues,
        }

    if normalized == "discord":
        webhook = str(settings.alert_discord_webhook_url or "").strip()
        if not webhook:
            issues.append("discord_not_configured")
        return {
            "channel": "discord",
            "configured": bool(webhook),
            "healthy": bool(webhook),
            "target": _mask_secret(webhook),
            "issues": issues,
        }

    if normalized == "telegram":
        token = str(settings.alert_telegram_bot_token or "").strip()
        chat_id = str(settings.alert_telegram_chat_id or "").strip()
        if not token or not chat_id:
            issues.append("telegram_not_configured")
        return {
            "channel": "telegram",
            "configured": bool(token and chat_id),
            "healthy": bool(token and chat_id),
            "target": f"telegram:{chat_id}" if chat_id else "",
            "issues": issues,
        }

    if normalized == "push":
        webhook = str(settings.alert_push_webhook_url or "").strip()
        if not webhook:
            issues.append("push_not_configured")
        return {
            "channel": "push",
            "configured": bool(webhook),
            "healthy": bool(webhook),
            "target": _mask_secret(webhook),
            "issues": issues,
        }

    return {
        "channel": normalized,
        "configured": False,
        "healthy": False,
        "issues": ["unsupported_channel"],
    }


def evaluate_delivery_preflight(channels: list[str]) -> dict[str, Any]:
    dispatcher = NotificationDispatcher(get_settings())
    channel_status = {channel: _channel_readiness(channel, dispatcher) for channel in channels}
    launchd_env = {
        "OPERATOR_BRIEF_CHANNEL": _launchctl_getenv("OPERATOR_BRIEF_CHANNEL"),
        "OPERATOR_BRIEF_DRY_RUN": _launchctl_getenv("OPERATOR_BRIEF_DRY_RUN"),
        "OPERATOR_BRIEF_ALLOW_LIVE_SEND": _launchctl_getenv("OPERATOR_BRIEF_ALLOW_LIVE_SEND"),
        "OPERATOR_BRIEF_DISCORD_WEBHOOK_URL": bool(_launchctl_getenv("OPERATOR_BRIEF_DISCORD_WEBHOOK_URL")),
    }

    issues: list[str] = []
    for channel, payload in channel_status.items():
        issues.extend(f"{channel}: {issue}" for issue in payload.get("issues") or [])

    requested_channel = launchd_env["OPERATOR_BRIEF_CHANNEL"] or "system"
    if requested_channel in channel_status and not channel_status[requested_channel]["healthy"]:
        issues.append(f"launchd_channel_not_ready:{requested_channel}")

    return {
        "generated_at": _now().isoformat(),
        "healthy": not issues,
        "issues": issues,
        "launchd_env": launchd_env,
        "channels": channel_status,
        "circuit_snapshot": NotificationDispatcher.circuit_snapshot(),
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Operator Session Brief Delivery Preflight")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- healthy: {payload['healthy']}")
    lines.append(f"- launchd_channel: {payload['launchd_env']['OPERATOR_BRIEF_CHANNEL'] or 'unset'}")
    lines.append(f"- launchd_dry_run: {payload['launchd_env']['OPERATOR_BRIEF_DRY_RUN'] or 'unset'}")
    lines.append(f"- launchd_allow_live_send: {payload['launchd_env']['OPERATOR_BRIEF_ALLOW_LIVE_SEND'] or 'unset'}")
    lines.append("")
    lines.append("## Channels")
    lines.append("")
    for name, status in payload["channels"].items():
        lines.append(f"- {name}: healthy={status['healthy']} configured={status['configured']}")
        if "routes" in status:
            lines.append(f"  - routes: {', '.join(status['routes']) or 'none'}")
        if "target" in status:
            lines.append(f"  - target: {status['target'] or 'missing'}")
        for issue in status.get("issues") or []:
            lines.append(f"  - issue: {issue}")
    lines.append("")
    lines.append("## Issues")
    lines.append("")
    if payload["issues"]:
        for issue in payload["issues"]:
            lines.append(f"- {issue}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Raw Payload")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(payload, ensure_ascii=False, indent=2))
    lines.append("```")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    channels = [item.strip().lower() for item in args.channels.split(",") if item.strip()]
    payload = evaluate_delivery_preflight(channels)
    if args.write_report:
        report_dir = _resolve_root_path(args.report_dir).resolve()
        timestamp = _now().strftime("%Y%m%dT%H%M%SZ")
        report_path = report_dir / f"operator_session_brief_delivery_preflight_{timestamp}.md"
        _write_report(report_path, payload)
        payload["report_path"] = _display_path(report_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.strict and not payload["healthy"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
