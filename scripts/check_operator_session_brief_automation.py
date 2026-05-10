#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
REPORT_DIR = ROOT_DIR / "reports" / "operations" / "operator_session_briefs"
START_LABEL = "com.yumin.trading.operator-brief-shift-start"
END_LABEL = "com.yumin.trading.operator-brief-shift-end"

from scripts.operation_report_io import atomic_write_text


@dataclass
class AgentStatus:
    label: str
    state: str
    last_exit_code: int | None
    runs: int | None
    working_directory: str
    stdout_path: str
    stderr_path: str
    brief_mode: str
    channel: str
    dry_run: str
    healthy: bool
    issues: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check launchd-based operator session brief automation health."
    )
    parser.add_argument("--max-age-minutes", type=int, default=30)
    parser.add_argument("--report-dir", default=str(REPORT_DIR))
    parser.add_argument("--write-report", action="store_true")
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


def _run_launchctl_print(label: str) -> str:
    uid = os.getuid()
    command = [_launchctl_executable(), "print", f"gui/{uid}/{label}"]
    completed = subprocess.run(command, capture_output=True, text=True, cwd=str(ROOT_DIR), check=False)
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"launchctl print failed for {label}: {stderr}")
    return completed.stdout


def _extract_value(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        return ""
    return match.group(1).strip()


def parse_launchctl_print(label: str, raw: str) -> AgentStatus:
    state = _extract_value(r"^\s*state = (.+)$", raw)
    last_exit_code_raw = _extract_value(r"^\s*last exit code = (.+)$", raw)
    runs_raw = _extract_value(r"^\s*runs = (.+)$", raw)
    working_directory = _extract_value(r"^\s*working directory = (.+)$", raw)
    stdout_path = _extract_value(r"^\s*stdout path = (.+)$", raw)
    stderr_path = _extract_value(r"^\s*stderr path = (.+)$", raw)
    brief_mode = _extract_value(r"^\s*OPERATOR_BRIEF_MODE => (.+)$", raw)
    channel = _extract_value(r"^\s*OPERATOR_BRIEF_CHANNEL => (.+)$", raw)
    dry_run = _extract_value(r"^\s*OPERATOR_BRIEF_DRY_RUN => (.+)$", raw)

    issues: list[str] = []
    last_exit_code = int(last_exit_code_raw) if last_exit_code_raw.isdigit() else None
    runs = int(runs_raw) if runs_raw.isdigit() else None

    if state != "not running":
        issues.append(f"unexpected launchd state: {state or 'missing'}")
    if last_exit_code != 0:
        issues.append(f"last exit code is not zero: {last_exit_code_raw or 'missing'}")
    if runs is None or runs < 1:
        issues.append("launchd runs count is missing or zero")
    if Path(working_directory).expanduser() != ROOT_DIR:
        issues.append(f"unexpected working directory: {working_directory or 'missing'}")
    if not stdout_path:
        issues.append("stdout path missing")
    if not stderr_path:
        issues.append("stderr path missing")
    if label.endswith("shift-start") and brief_mode != "shift-start":
        issues.append(f"brief mode mismatch: {brief_mode or 'missing'}")
    if label.endswith("shift-end") and brief_mode != "shift-end":
        issues.append(f"brief mode mismatch: {brief_mode or 'missing'}")
    if channel not in {"system", "discord"}:
        issues.append(f"channel missing or invalid: {channel or 'missing'}")
    if dry_run not in {"", "0", "1"}:
        issues.append(f"dry-run flag invalid: {dry_run}")

    return AgentStatus(
        label=label,
        state=state,
        last_exit_code=last_exit_code,
        runs=runs,
        working_directory=working_directory,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        brief_mode=brief_mode,
        channel=channel,
        dry_run=dry_run,
        healthy=not issues,
        issues=issues,
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


def _artifact_status(path: Path, *, max_age_minutes: int, expected_mode: str) -> dict[str, Any]:
    issues: list[str] = []
    exists = path.exists()
    payload: dict[str, Any] | None = None
    age_seconds: float | None = None
    modified_at: str | None = None
    if not exists:
        issues.append("file missing")
    else:
        stat = path.stat()
        modified = datetime.fromtimestamp(stat.st_mtime, UTC)
        age_seconds = (_now() - modified).total_seconds()
        modified_at = modified.isoformat()
        if age_seconds > max_age_minutes * 60:
            issues.append(f"file older than {max_age_minutes} minutes")
        payload = _read_json(path)
        actual_mode = str(payload.get("brief_mode") or "")
        if actual_mode and actual_mode != expected_mode:
            issues.append(f"brief_mode mismatch: expected {expected_mode}, got {actual_mode}")

    return {
        "path": str(path),
        "exists": exists,
        "modified_at": modified_at,
        "age_seconds": age_seconds,
        "healthy": not issues,
        "issues": issues,
        "payload": payload,
    }


def _mode_paths(report_dir: Path, mode: str, channel: str) -> dict[str, Path]:
    mode_slug = mode.replace("-", "_")
    channel_slug = channel.replace("-", "_")
    return {
        "latest": report_dir / f"latest_operator_session_brief_{mode_slug}.json",
        "state": report_dir / f"last_alert_state_{mode_slug}_{channel_slug}.json",
    }


def _evaluate_status(report_dir: Path, max_age_minutes: int) -> dict[str, Any]:
    start_agent = parse_launchctl_print(START_LABEL, _run_launchctl_print(START_LABEL))
    end_agent = parse_launchctl_print(END_LABEL, _run_launchctl_print(END_LABEL))
    channel = start_agent.channel or end_agent.channel or "system"

    start_paths = _mode_paths(report_dir, "shift-start", channel)
    end_paths = _mode_paths(report_dir, "shift-end", channel)
    start_latest = _artifact_status(start_paths["latest"], max_age_minutes=max_age_minutes, expected_mode="shift-start")
    end_latest = _artifact_status(end_paths["latest"], max_age_minutes=max_age_minutes, expected_mode="shift-end")
    start_state = _artifact_status(start_paths["state"], max_age_minutes=max_age_minutes, expected_mode="shift-start")
    end_state = _artifact_status(end_paths["state"], max_age_minutes=max_age_minutes, expected_mode="shift-end")

    issues: list[str] = []
    for agent in (start_agent, end_agent):
        issues.extend(f"{agent.label}: {issue}" for issue in agent.issues)
    for name, artifact in (
        ("shift_start_latest", start_latest),
        ("shift_end_latest", end_latest),
        ("shift_start_state", start_state),
        ("shift_end_state", end_state),
    ):
        issues.extend(f"{name}: {issue}" for issue in artifact["issues"])

    return {
        "generated_at": _now().isoformat(),
        "channel": channel,
        "max_age_minutes": max_age_minutes,
        "healthy": not issues,
        "issues": issues,
        "agents": {
            "shift_start": asdict(start_agent),
            "shift_end": asdict(end_agent),
        },
        "artifacts": {
            "shift_start_latest": start_latest,
            "shift_end_latest": end_latest,
            "shift_start_state": start_state,
            "shift_end_state": end_state,
        },
    }


def evaluate_status(report_dir: Path, max_age_minutes: int) -> dict[str, Any]:
    return _evaluate_status(report_dir, max_age_minutes)


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Operator Session Brief Automation Health")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- healthy: {payload['healthy']}")
    lines.append(f"- channel: {payload['channel']}")
    lines.append(f"- max_age_minutes: {payload['max_age_minutes']}")
    lines.append("")
    lines.append("## Agents")
    lines.append("")
    for name, agent in payload["agents"].items():
        lines.append(f"- {name}: healthy={agent['healthy']} state={agent['state']} last_exit_code={agent['last_exit_code']} runs={agent['runs']} mode={agent['brief_mode']} channel={agent['channel']} dry_run={agent['dry_run']}")
        for issue in agent["issues"]:
            lines.append(f"  - issue: {issue}")
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    for name, artifact in payload["artifacts"].items():
        lines.append(f"- {name}: healthy={artifact['healthy']} exists={artifact['exists']} modified_at={artifact['modified_at']} age_seconds={artifact['age_seconds']}")
        for issue in artifact["issues"]:
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
    atomic_write_text(path, "\n".join(lines))


def main() -> int:
    args = parse_args()
    report_dir = _resolve_root_path(args.report_dir).resolve()
    payload = evaluate_status(report_dir, args.max_age_minutes)

    if args.write_report:
        timestamp = _now().strftime("%Y%m%dT%H%M%SZ")
        report_path = report_dir / f"operator_session_brief_automation_health_{timestamp}.md"
        _write_report(report_path, payload)
        payload["report_path"] = _display_path(report_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.strict and not payload["healthy"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
