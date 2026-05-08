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
WATCH_SCRIPT = ROOT_DIR / "scripts" / "watch_paper_candidate_drill.py"
EXIT_SCRIPT = ROOT_DIR / "scripts" / "run_paper_exit_monitor.py"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "reports" / "operations" / "paper_candidate_watch"


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one PAPER lineage watch tick and normalize no-candidate outcomes to a healthy exit."
    )
    parser.add_argument("--base-url", default=os.environ.get("PAPER_LINEAGE_WATCH_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument(
        "--families",
        default=os.environ.get("PAPER_LINEAGE_WATCH_FAMILIES", "sweep_reversal,trend_continuation"),
    )
    parser.add_argument("--universe", default=os.environ.get("PAPER_LINEAGE_WATCH_UNIVERSE", "usdc_perp_top30"))
    parser.add_argument("--symbol", default=os.environ.get("PAPER_LINEAGE_WATCH_SYMBOL"))
    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=int(os.environ.get("PAPER_LINEAGE_WATCH_CANDIDATE_LIMIT", "100")),
    )
    parser.add_argument(
        "--limit-symbols",
        type=int,
        default=int(os.environ.get("PAPER_LINEAGE_WATCH_LIMIT_SYMBOLS", "30")),
    )
    parser.add_argument(
        "--symbol-concurrency",
        type=int,
        default=int(os.environ.get("PAPER_LINEAGE_WATCH_SYMBOL_CONCURRENCY", "4")),
    )
    parser.add_argument("--limit-1m", type=int, default=int(os.environ.get("PAPER_LINEAGE_WATCH_LIMIT_1M", "900")))
    parser.add_argument("--limit-5m", type=int, default=int(os.environ.get("PAPER_LINEAGE_WATCH_LIMIT_5M", "500")))
    parser.add_argument("--limit-15m", type=int, default=int(os.environ.get("PAPER_LINEAGE_WATCH_LIMIT_15M", "500")))
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=int(os.environ.get("PAPER_LINEAGE_WATCH_INTERVAL_SECONDS", "1")),
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=int(os.environ.get("PAPER_LINEAGE_WATCH_MAX_ATTEMPTS", "1")),
    )
    parser.add_argument(
        "--submit-paper",
        action="store_true",
        default=_env_flag("PAPER_LINEAGE_WATCH_SUBMIT_PAPER", True),
    )
    parser.add_argument(
        "--paper-lineage-override",
        action="store_true",
        default=_env_flag("PAPER_LINEAGE_WATCH_LINEAGE_OVERRIDE", True),
    )
    parser.add_argument(
        "--include-manual-review",
        action="store_true",
        default=_env_flag("PAPER_LINEAGE_WATCH_INCLUDE_MANUAL_REVIEW", False),
    )
    parser.add_argument(
        "--paper-scenario",
        default=os.environ.get("PAPER_LINEAGE_WATCH_PAPER_SCENARIO", "fill"),
        choices=["fill", "partial_fill", "cancel", "timeout", "reject", "attach_failure"],
    )
    parser.add_argument(
        "--report-dir",
        default=os.environ.get(
            "PAPER_LINEAGE_WATCH_REPORT_DIR",
            "reports/operations/paper_candidate_watch/automation",
        ),
    )
    parser.add_argument(
        "--latest-run-file",
        default=os.environ.get(
            "PAPER_LINEAGE_WATCH_LATEST_RUN_FILE",
            str(DEFAULT_OUTPUT_DIR / "latest_launchd_run.json"),
        ),
    )
    parser.add_argument("--no-write-report", action="store_true", default=_env_flag("PAPER_LINEAGE_WATCH_NO_WRITE_REPORT", False))
    return parser.parse_args()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _build_cmd(args: argparse.Namespace) -> list[str]:
    cmd = [
        sys.executable,
        str(WATCH_SCRIPT),
        "--families",
        args.families,
        "--universe",
        args.universe,
        "--candidate-limit",
        str(max(1, args.candidate_limit)),
        "--limit-symbols",
        str(max(1, args.limit_symbols)),
        "--symbol-concurrency",
        str(max(1, args.symbol_concurrency)),
        "--limit-1m",
        str(max(1, args.limit_1m)),
        "--limit-5m",
        str(max(1, args.limit_5m)),
        "--limit-15m",
        str(max(1, args.limit_15m)),
        "--interval-seconds",
        str(max(1, args.interval_seconds)),
        "--max-attempts",
        str(max(1, args.max_attempts)),
        "--report-dir",
        args.report_dir,
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
    if args.no_write_report:
        cmd.append("--no-write-report")
    return cmd


def _build_exit_cmd(args: argparse.Namespace) -> list[str]:
    return [
        sys.executable,
        str(EXIT_SCRIPT),
        "--families",
        args.families,
    ]


def _active_sample_duplicate_hold(payload: dict[str, Any]) -> bool:
    source = dict(payload or {})
    final_result = dict(source.get("final_result") or {})
    candidate = dict(source.get("candidate") or final_result.get("candidate") or {})
    intent = dict(source.get("intent") or final_result.get("intent") or {})
    if not candidate or not intent:
        return False
    submit_decision = str(intent.get("submit_decision") or "").strip().upper()
    reason_code = str(intent.get("decision_reason_code") or "").strip().lower()
    reason_message = str(intent.get("decision_reason_message") or "").strip().lower()
    if submit_decision == "SUBMIT":
        return False
    duplicate_reason = "duplicate" in reason_code or "duplicate thesis detected against active plan" in reason_message
    return duplicate_reason and bool(candidate.get("symbol"))


def _paper_exit_monitor_summary(payload: dict[str, Any]) -> dict[str, Any]:
    source = dict(payload or {})
    stale_cleanup_events = int(source.get("stale_cleanup_events", 0) or 0)
    closed_events = int(source.get("closed_events", 0) or 0)
    processed_plans = int(source.get("processed_plans", 0) or 0)
    summary = (
        f"processed={processed_plans}"
        f" | closed={closed_events}"
        f" | stale_cleanup={stale_cleanup_events}"
        f" | fill_repairs={int(source.get('fill_repairs', 0) or 0)}"
        f" | state_repairs={int(source.get('state_repairs', 0) or 0)}"
    )
    return {
        "available": bool(source),
        "processed_plans": processed_plans,
        "paper_candidate_plans": int(source.get("paper_candidate_plans", 0) or 0),
        "closed_events": closed_events,
        "stale_cleanup_events": stale_cleanup_events,
        "fill_repairs": int(source.get("fill_repairs", 0) or 0),
        "state_repairs": int(source.get("state_repairs", 0) or 0),
        "closed_validity_repairs": int(source.get("closed_validity_repairs", 0) or 0),
        "summary": summary,
    }


def main() -> int:
    args = parse_args()
    completed = subprocess.run(
        _build_cmd(args),
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = completed.stdout.strip()
    if not stdout:
        raise RuntimeError(
            f"paper lineage watch returned no stdout (code={completed.returncode}) stderr={completed.stderr.strip()}"
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"paper lineage watch returned invalid JSON (code={completed.returncode}) stdout={stdout[:1000]} stderr={completed.stderr.strip()}"
        ) from exc

    if completed.returncode not in {0, 1}:
        raise RuntimeError(
            f"paper lineage watch failed with code={completed.returncode} stderr={completed.stderr.strip()}"
        )

    duplicate_hold = _active_sample_duplicate_hold(payload)
    payload["tick_status"] = (
        "active_sample_already_in_progress"
        if duplicate_hold
        else ("found_eligible_candidate" if completed.returncode == 0 else "no_eligible_candidate")
    )
    payload["active_sample_duplicate_hold"] = duplicate_hold
    payload["treated_as_healthy_tick"] = True
    payload["watch_process_return_code"] = completed.returncode
    payload["watch_process_stderr"] = completed.stderr.strip()

    exit_completed = subprocess.run(
        _build_exit_cmd(args),
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if exit_completed.returncode != 0 or not exit_completed.stdout.strip():
        raise RuntimeError(
            f"paper exit monitor failed with code={exit_completed.returncode} stderr={exit_completed.stderr.strip()}"
        )
    try:
        payload["paper_exit_monitor"] = json.loads(exit_completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"paper exit monitor returned invalid JSON stdout={exit_completed.stdout[:1000]} stderr={exit_completed.stderr.strip()}"
        ) from exc
    payload["paper_exit_monitor_summary"] = _paper_exit_monitor_summary(dict(payload.get("paper_exit_monitor") or {}))
    payload["paper_exit_monitor_stderr"] = exit_completed.stderr.strip()

    latest_run_file = Path(args.latest_run_file).resolve()
    _write_json(latest_run_file, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
