from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess


ROOT_DIR = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_post_unlock_review = _load_module(
    "run_post_unlock_review_test_module",
    ROOT_DIR / "scripts/run_post_unlock_review.py",
)


def test_main_returns_ready_to_reopen_runtime(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        run_post_unlock_review,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=30,
            report_dir="reports/operations/post_unlock_reviews",
            no_write_report=True,
        ),
    )

    def _run_json_command(command: list[str]) -> dict:
        joined = " ".join(command)
        if "run_micro_live_preflight.py" in joined:
            return {
                "overall_status": "READY_FOR_MICRO_LIVE",
                "summary_line": "All preflight checks passed.",
                "next_steps": ["Proceed to the live go-live checklist."],
            }
        if "run_post_live_pruning_review.py" in joined:
            return {
                "decision": "REOPEN_PRUNING_REVIEW",
                "rationale": "A complete live operating cycle exists.",
                "next_steps": ["Audit operator-facing fields after the first live cycle."],
            }
        raise AssertionError(joined)

    monkeypatch.setattr(run_post_unlock_review, "_run_json_command", _run_json_command)

    exit_code = run_post_unlock_review.main()

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "READY_TO_REOPEN_RUNTIME"
    assert payload["micro_live_preflight"]["overall_status"] == "READY_FOR_MICRO_LIVE"
    assert payload["post_live_pruning_review"]["decision"] == "REOPEN_PRUNING_REVIEW"
    assert payload["bundle_review_command"].endswith(
        "scripts/run_post_unlock_review.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30"
    )


def test_main_returns_manual_review_required(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        run_post_unlock_review,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=30,
            report_dir="reports/operations/post_unlock_reviews",
            no_write_report=True,
        ),
    )

    def _run_json_command(command: list[str]) -> dict:
        joined = " ".join(command)
        if "run_micro_live_preflight.py" in joined:
            return {
                "overall_status": "NOT_READY",
                "summary_line": "2 blocking preflight check(s) remain.",
                "next_steps": ["Resolve approval blocker and execution review before reopening entries."],
            }
        if "run_post_live_pruning_review.py" in joined:
            return {
                "decision": "KEEP_OPTIONAL_HOLD",
                "rationale": "No complete live operating cycle evidence yet.",
                "next_steps": ["Keep contract pruning on optional hold."],
            }
        raise AssertionError(joined)

    monkeypatch.setattr(run_post_unlock_review, "_run_json_command", _run_json_command)

    exit_code = run_post_unlock_review.main()

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "MANUAL_REVIEW_REQUIRED"
    assert payload["micro_live_preflight"]["overall_status"] == "NOT_READY"
    assert payload["post_live_pruning_review"]["decision"] == "KEEP_OPTIONAL_HOLD"
    assert payload["summary_line"].startswith("Post-unlock review still requires manual review")


def test_main_allows_runtime_reopen_when_pruning_is_optional_hold(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        run_post_unlock_review,
        "parse_args",
        lambda: SimpleNamespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=30,
            report_dir="reports/operations/post_unlock_reviews",
            no_write_report=True,
        ),
    )

    def _run_json_command(command: list[str]) -> dict:
        joined = " ".join(command)
        if "run_micro_live_preflight.py" in joined:
            return {
                "overall_status": "READY_FOR_MICRO_LIVE",
                "summary_line": "All preflight checks passed.",
                "next_steps": ["Proceed to the live go-live checklist."],
            }
        if "run_post_live_pruning_review.py" in joined:
            return {
                "decision": "KEEP_OPTIONAL_HOLD",
                "rationale": "No complete live operating cycle evidence yet.",
                "next_steps": ["Keep contract pruning on optional hold."],
            }
        raise AssertionError(joined)

    monkeypatch.setattr(run_post_unlock_review, "_run_json_command", _run_json_command)

    exit_code = run_post_unlock_review.main()

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "READY_TO_REOPEN_RUNTIME"
    assert payload["post_live_pruning_review"]["decision"] == "KEEP_OPTIONAL_HOLD"
    assert any("optional hold" in step.lower() for step in payload["next_steps"])


def test_run_json_command_accepts_json_stdout_from_nonzero_exit(monkeypatch) -> None:
    def _run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0],
            1,
            stdout=json.dumps({"overall_status": "NOT_READY"}),
            stderr="blocking checks remain",
        )

    monkeypatch.setattr(run_post_unlock_review.subprocess, "run", _run)

    payload = run_post_unlock_review._run_json_command(["dummy"])

    assert payload["overall_status"] == "NOT_READY"
    assert payload["_command_exit_code"] == 1
