#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


@dataclass(frozen=True)
class LaunchdJob:
    name: str
    label: str
    args: list[str]
    start_interval: int | None = None
    start_calendar_interval: dict[str, int] | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate optional launchd schedules for MICRO_LIVE operating guards.")
    parser.add_argument("--output-dir", default="reports/operations/launchd")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--working-dir", default=str(ROOT_DIR))
    parser.add_argument("--label-prefix", default="com.trading.micro-live")
    parser.add_argument("--env-file", default="")
    parser.add_argument("--install", action="store_true", help="Copy generated plists into ~/Library/LaunchAgents.")
    parser.add_argument("--load", action="store_true", help="Run launchctl bootstrap after --install.")
    parser.add_argument("--unload", action="store_true", help="Run launchctl bootout for matching installed plists before loading.")
    return parser.parse_args()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _resolve_root_path(raw_path: str) -> Path:
    path = Path(str(raw_path or "")).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


def _script(path: str) -> str:
    return str(ROOT_DIR / "scripts" / path)


def build_jobs(*, label_prefix: str, python_bin: str) -> list[LaunchdJob]:
    prefix = str(label_prefix or "com.trading.micro-live").strip().rstrip(".")
    py = str(python_bin or sys.executable)
    return [
        LaunchdJob(
            name="runtime_guard",
            label=f"{prefix}.runtime-guard",
            args=[py, _script("run_micro_live_runtime_guard.py"), "--days", "3", "--limit", "200", "--no-fail-exit"],
            start_interval=15 * 60,
        ),
        LaunchdJob(
            name="no_order_watchdog",
            label=f"{prefix}.no-order-watchdog",
            args=[py, _script("run_micro_live_no_order_watchdog.py"), "--days", "3", "--notify", "--no-fail-exit"],
            start_interval=30 * 60,
        ),
        LaunchdJob(
            name="reconciliation_watchdog",
            label=f"{prefix}.reconciliation-watchdog",
            args=[py, _script("run_live_reconciliation_watchdog.py"), "--days", "3", "--notify", "--no-fail-exit"],
            start_interval=5 * 60,
        ),
        LaunchdJob(
            name="synthetic_canary",
            label=f"{prefix}.synthetic-canary",
            args=[py, _script("run_micro_live_synthetic_canary.py"), "--no-network", "--no-fail-exit"],
            start_interval=60 * 60,
        ),
        LaunchdJob(
            name="boot_check",
            label=f"{prefix}.boot-check",
            args=[py, _script("run_micro_live_boot_check.py"), "--days", "3", "--limit", "200", "--no-fail-exit"],
            start_interval=15 * 60,
        ),
        LaunchdJob(
            name="ops_heartbeat",
            label=f"{prefix}.ops-heartbeat",
            args=[py, _script("run_micro_live_ops_heartbeat.py"), "--notify", "--no-fail-exit"],
            start_interval=15 * 60,
        ),
        LaunchdJob(
            name="binance_rule_drift",
            label=f"{prefix}.binance-rule-drift",
            args=[py, _script("run_binance_rule_drift_snapshot.py")],
            start_calendar_interval={"Hour": 3, "Minute": 10},
        ),
        LaunchdJob(
            name="replay_validation_bridge",
            label=f"{prefix}.replay-validation-bridge",
            args=[
                py,
                _script("run_replay_validation_bridge.py"),
                "--all-live-symbols",
                "--no-fail-exit",
            ],
            start_calendar_interval={"Hour": 3, "Minute": 25},
        ),
        LaunchdJob(
            name="session_impulse_retest_runtime_audit",
            label=f"{prefix}.session-impulse-retest-runtime-audit",
            args=[
                py,
                _script("run_session_impulse_retest_runtime_audit_report.py"),
                "--hours",
                "3",
                "--no-fail-exit",
            ],
            start_interval=30 * 60,
        ),
        LaunchdJob(
            name="macro_calendar_blackouts",
            label=f"{prefix}.macro-calendar-blackouts",
            args=[
                py,
                _script("build_micro_live_event_blackouts.py"),
                "--years",
                "2026,2027",
                "--output",
                "reports/validation/contracts/micro_live_event_blackouts_major_us_macro_auto.json",
            ],
            start_calendar_interval={"Hour": 2, "Minute": 30},
        ),
    ]


def _program_arguments(*, args: list[str], working_dir: Path, env_file: str) -> list[str]:
    env_path = str(env_file or "").strip()
    if not env_path:
        return args
    resolved = _resolve_root_path(env_path)
    command = " ".join(
        [
            "cd",
            shlex.quote(str(working_dir)),
            "&&",
            "set -a",
            "&&",
            "source",
            shlex.quote(str(resolved)),
            "&&",
            "set +a",
            "&&",
            "exec",
            *(shlex.quote(str(item)) for item in args),
        ]
    )
    return ["/bin/zsh", "-lc", command]


def plist_payload(*, job: LaunchdJob, working_dir: Path, env_file: str) -> dict[str, Any]:
    logs_dir = ROOT_DIR / "reports/operations/launchd/logs"
    payload: dict[str, Any] = {
        "Label": job.label,
        "ProgramArguments": _program_arguments(args=job.args, working_dir=working_dir, env_file=env_file),
        "WorkingDirectory": str(working_dir),
        "RunAtLoad": False,
        "StandardOutPath": str(logs_dir / f"{job.name}.out.log"),
        "StandardErrorPath": str(logs_dir / f"{job.name}.err.log"),
    }
    if job.start_interval is not None:
        payload["StartInterval"] = int(job.start_interval)
    if job.start_calendar_interval is not None:
        payload["StartCalendarInterval"] = dict(job.start_calendar_interval)
    return payload


def write_plists(*, output_dir: Path, jobs: list[LaunchdJob], working_dir: Path, env_file: str) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (ROOT_DIR / "reports/operations/launchd/logs").mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for job in jobs:
        path = output_dir / f"{job.label}.plist"
        with path.open("wb") as handle:
            plistlib.dump(plist_payload(job=job, working_dir=working_dir, env_file=env_file), handle, sort_keys=True)
        rows.append({"name": job.name, "label": job.label, "path": _display_path(path)})
    return rows


def _launchctl(action: str, plist_path: Path) -> dict[str, Any]:
    domain = f"gui/{os.getuid()}"
    command = ["launchctl", "bootstrap" if action == "load" else "bootout", domain, str(plist_path)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    return {
        "action": action,
        "path": str(plist_path),
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def install_plists(*, rows: list[dict[str, Any]], unload: bool, load: bool) -> list[dict[str, Any]]:
    launch_agents = Path.home() / "Library/LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)
    operations: list[dict[str, Any]] = []
    for row in rows:
        source = _resolve_root_path(str(row["path"]))
        target = launch_agents / source.name
        if unload and target.exists():
            operations.append(_launchctl("unload", target))
        shutil.copy2(source, target)
        op = {"action": "install", "source": _display_path(source), "target": str(target)}
        operations.append(op)
        if load:
            operations.append(_launchctl("load", target))
    return operations


def main() -> int:
    args = parse_args()
    output_dir = _resolve_root_path(str(args.output_dir))
    working_dir = _resolve_root_path(str(args.working_dir))
    jobs = build_jobs(label_prefix=str(args.label_prefix), python_bin=str(args.python))
    rows = write_plists(output_dir=output_dir, jobs=jobs, working_dir=working_dir, env_file=str(args.env_file or ""))
    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "overall_status": "PASS",
        "output_dir": _display_path(output_dir),
        "job_count": len(rows),
        "jobs": rows,
        "installed": False,
        "operations": [],
    }
    if bool(args.install):
        operations = install_plists(rows=rows, unload=bool(args.unload), load=bool(args.load))
        payload["installed"] = True
        payload["operations"] = operations
        if any(int(item.get("returncode", 0)) != 0 for item in operations if item.get("action") in {"load", "unload"}):
            payload["overall_status"] = "WARN"
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
