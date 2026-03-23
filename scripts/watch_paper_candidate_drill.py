#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
DRILL_SCRIPT = ROOT_DIR / "scripts" / "run_paper_candidate_drill.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Watch for eligible PAPER lineage candidates and optionally submit the first eligible one."
    )
    parser.add_argument("--interval-seconds", type=int, default=900, help="Polling interval between drill attempts.")
    parser.add_argument("--max-attempts", type=int, default=8, help="Maximum drill attempts before giving up.")
    parser.add_argument("--families", default="trend_continuation,sweep_reversal")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--candidate-limit", type=int, default=100)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--limit-symbols", type=int, default=30)
    parser.add_argument("--symbol-concurrency", type=int, default=4)
    parser.add_argument("--limit-1m", type=int, default=900)
    parser.add_argument("--limit-5m", type=int, default=500)
    parser.add_argument("--limit-15m", type=int, default=500)
    parser.add_argument("--include-manual-review", action="store_true")
    parser.add_argument("--submit-paper", action="store_true", help="Submit the first eligible candidate via PAPER.")
    parser.add_argument(
        "--paper-lineage-override",
        action="store_true",
        help="Allow PAPER-only lineage override when the best eligible family candidate is blocked by active-plan thesis duplication.",
    )
    parser.add_argument(
        "--paper-scenario",
        default="fill",
        choices=["fill", "partial_fill", "cancel", "timeout", "reject", "attach_failure"],
    )
    parser.add_argument(
        "--report-dir",
        default="reports/operations/paper_candidate_watch",
        help="Directory for the watcher markdown report.",
    )
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def _now() -> datetime:
    return datetime.now(UTC)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _run_once(args: argparse.Namespace) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(DRILL_SCRIPT),
        "--no-write-report",
        "--families",
        args.families,
        "--universe",
        args.universe,
        "--candidate-limit",
        str(args.candidate_limit),
        "--limit-symbols",
        str(args.limit_symbols),
        "--symbol-concurrency",
        str(args.symbol_concurrency),
        "--limit-1m",
        str(args.limit_1m),
        "--limit-5m",
        str(args.limit_5m),
        "--limit-15m",
        str(args.limit_15m),
    ]
    if args.symbol:
        cmd.extend(["--symbol", args.symbol])
    if args.include_manual_review:
        cmd.append("--include-manual-review")
    if args.submit_paper:
        cmd.append("--submit-paper")
        cmd.extend(["--paper-scenario", args.paper_scenario])
    if args.paper_lineage_override:
        cmd.append("--paper-lineage-override")

    completed = subprocess.run(
        cmd,
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = completed.stdout.strip()
    if not stdout:
        raise RuntimeError(f"watch drill attempt returned no stdout (code={completed.returncode}) stderr={completed.stderr.strip()}")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"watch drill attempt returned invalid JSON (code={completed.returncode}) stdout={stdout[:1000]} stderr={completed.stderr.strip()}"
        ) from exc
    payload["_return_code"] = completed.returncode
    payload["_stderr"] = completed.stderr.strip()
    return payload


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    attempts = payload.get("attempts", [])
    lines: list[str] = [
        "# PAPER Candidate Watch",
        "",
        f"- generated_at: {payload['generated_at']}",
        f"- overall_status: {payload['overall_status']}",
        f"- summary: {payload['summary_line']}",
        f"- attempts_run: {payload['attempts_run']}",
        "",
        "## Attempts",
        "",
    ]
    for attempt in attempts:
        lines.append(
            f"- attempt {attempt['attempt']}: {attempt['overall_status']} / {attempt['summary_line']}"
        )
    lines.extend(["", "## Raw Payload", "", "```json", json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), "```"])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    generated_at = _now()
    attempts: list[dict[str, Any]] = []
    final_payload: dict[str, Any] | None = None

    for index in range(1, args.max_attempts + 1):
        payload = _run_once(args)
        attempts.append(
            {
                "attempt": index,
                "generated_at": payload.get("generated_at"),
                "overall_status": payload.get("overall_status"),
                "summary_line": payload.get("summary_line"),
                "eligible_candidate_found": next(
                    (row.get("status") == "PASS" for row in payload.get("checks", []) if row.get("name") == "eligible_candidate_found"),
                    False,
                ),
                "candidate": payload.get("candidate"),
                "submission": payload.get("submission"),
                "report_path": payload.get("report_path"),
            }
        )
        eligible = attempts[-1]["eligible_candidate_found"]
        final_payload = payload
        if eligible:
            break
        if index < args.max_attempts:
            time.sleep(max(args.interval_seconds, 1))

    found = bool(attempts and attempts[-1]["eligible_candidate_found"])
    overall_status = "FOUND_ELIGIBLE_CANDIDATE" if found else "NO_ELIGIBLE_CANDIDATE"
    summary_line = (
        f"Eligible PAPER lineage candidate found on attempt {attempts[-1]['attempt']}."
        if found
        else f"No eligible PAPER lineage candidate found after {len(attempts)} attempt(s)."
    )
    next_steps = (
        [
            "Review the candidate/approval/submission payload from the final attempt.",
            "If submit-paper was disabled, rerun run_paper_candidate_drill.py with --submit-paper for the chosen candidate.",
            "After a closed v2 trade is recorded, rerun validation/report and micro-live preflight.",
        ]
        if found
        else [
            "Rerun this watcher during London/New York preferred sessions.",
            "Keep focus on trend_continuation or sweep_reversal families; legacy_zone_plan does not advance MICRO_LIVE lineage.",
            "No PAPER lineage submission occurred because no eligible family candidate appeared.",
        ]
    )

    result = {
        "generated_at": generated_at,
        "overall_status": overall_status,
        "summary_line": summary_line,
        "attempts_run": len(attempts),
        "families": [item.strip() for item in args.families.split(",") if item.strip()],
        "submit_paper": args.submit_paper,
        "interval_seconds": args.interval_seconds,
        "max_attempts": args.max_attempts,
        "attempts": attempts,
        "final_result": final_payload,
        "next_steps": next_steps,
    }

    if not args.no_write_report:
        ts = generated_at.strftime("%Y%m%dT%H%M%SZ")
        report_path = ROOT_DIR / args.report_dir / f"paper_candidate_watch_{ts}.md"
        _write_report(report_path, result)
        result["report_path"] = str(report_path.relative_to(ROOT_DIR))
    else:
        result["report_path"] = None

    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
