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
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.operation_report_io import atomic_write_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the immediate post-unlock operating review bundle."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--report-dir", default="reports/operations/post_unlock_reviews")
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def _now() -> datetime:
    return datetime.now(UTC)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _run_json_command(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = str(completed.stdout or "").strip()
    if not stdout:
        stderr = str(completed.stderr or "").strip()
        raise RuntimeError(
            f"command returned empty stdout (exit={completed.returncode}): {' '.join(command)}"
            + (f" | stderr={stderr}" if stderr else "")
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        stderr = str(completed.stderr or "").strip()
        raise RuntimeError(
            f"command did not return JSON (exit={completed.returncode}): {' '.join(command)}"
            + (f" | stderr={stderr}" if stderr else "")
        ) from exc
    if isinstance(payload, dict):
        payload.setdefault("_command_exit_code", int(completed.returncode))
    return payload


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Post-Unlock Review")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- symbol: {payload['symbol']}")
    lines.append(f"- universe: {payload['universe']}")
    lines.append(f"- status: {payload['status']}")
    lines.append(f"- summary: {payload['summary_line']}")
    lines.append("")
    lines.append("## Commands")
    lines.append("")
    lines.append(f"- bundle: {payload['bundle_review_command']}")
    lines.append(f"- preflight: {payload['micro_live_preflight_command']}")
    lines.append(f"- pruning: {payload['post_live_pruning_review_command']}")
    lines.append("")
    lines.append("## Snapshot")
    lines.append("")
    lines.append(f"- preflight: {payload['micro_live_preflight']['overall_status']}")
    lines.append(f"- pruning: {payload['post_live_pruning_review']['decision']}")
    lines.append("")
    lines.append("## Next Steps")
    lines.append("")
    for step in payload.get("next_steps") or []:
        lines.append(f"- {step}")
    lines.append("")
    lines.append("## Raw Payload")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    lines.append("```")
    atomic_write_text(path, "\n".join(lines))


def main() -> int:
    args = parse_args()
    generated_at = _now()

    micro_live_preflight_command = [
        sys.executable,
        "scripts/run_micro_live_preflight.py",
        "--base-url",
        args.base_url,
        "--symbol",
        args.symbol,
        "--universe",
        args.universe,
        "--days",
        str(args.days),
        "--no-write-report",
    ]
    post_live_pruning_review_command = [
        sys.executable,
        "scripts/run_post_live_pruning_review.py",
        "--base-url",
        args.base_url,
        "--symbol",
        args.symbol,
        "--universe",
        args.universe,
        "--days",
        str(args.days),
        "--no-write-report",
    ]

    preflight = _run_json_command(micro_live_preflight_command)
    pruning = _run_json_command(post_live_pruning_review_command)

    preflight_status = str(preflight.get("overall_status") or "UNKNOWN")
    pruning_decision = str(pruning.get("decision") or "UNKNOWN")
    pruning_non_blocking = pruning_decision in {"REOPEN_PRUNING_REVIEW", "KEEP_OPTIONAL_HOLD"}
    ready = preflight_status == "READY_FOR_MICRO_LIVE" and pruning_non_blocking
    status = "READY_TO_REOPEN_RUNTIME" if ready else "MANUAL_REVIEW_REQUIRED"
    summary_line = (
        "Post-unlock review bundle is green; runtime reopen can move to final operator sign-off."
        if ready
        else f"Post-unlock review still requires manual review: preflight={preflight_status}, pruning={pruning_decision}."
    )

    next_steps = []
    if ready:
        next_steps.append("Proceed to final operator sign-off and runtime reopen decision.")
        if pruning_decision == "KEEP_OPTIONAL_HOLD":
            next_steps.append("Keep pruning review on optional hold; this does not block runtime reopen.")
    else:
        next_steps.append("Review micro-live preflight blockers and pruning review rationale before reopening runtime.")
    for step in preflight.get("next_steps") or []:
        if step not in next_steps:
            next_steps.append(str(step))
    for step in pruning.get("next_steps") or []:
        if step not in next_steps:
            next_steps.append(str(step))

    bundle_review_command = (
        f"./.venv/bin/python scripts/run_post_unlock_review.py "
        f"--symbol {args.symbol} --universe {args.universe} --days {args.days}"
    )
    payload = {
        "generated_at": generated_at.isoformat(),
        "symbol": args.symbol.upper(),
        "universe": args.universe,
        "days": int(args.days),
        "status": status,
        "summary_line": summary_line,
        "bundle_review_command": bundle_review_command,
        "micro_live_preflight_command": " ".join(micro_live_preflight_command).replace(f"{sys.executable} ", "./.venv/bin/python "),
        "post_live_pruning_review_command": " ".join(post_live_pruning_review_command).replace(f"{sys.executable} ", "./.venv/bin/python "),
        "micro_live_preflight": {
            "overall_status": preflight_status,
            "summary_line": str(preflight.get("summary_line") or ""),
        },
        "post_live_pruning_review": {
            "decision": pruning_decision,
            "rationale": str(pruning.get("rationale") or ""),
        },
        "next_steps": next_steps,
        "preflight_payload": preflight,
        "pruning_payload": pruning,
    }

    if not args.no_write_report:
        ts = generated_at.strftime("%Y%m%dT%H%M%SZ")
        report_path = ROOT_DIR / args.report_dir / f"post_unlock_review_{args.symbol.upper()}_{ts}.md"
        _write_report(report_path, payload)
        payload["report_path"] = _display_path(report_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
