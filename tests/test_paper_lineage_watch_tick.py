from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT_DIR = Path("/Users/yumin/Documents/trading")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


paper_lineage_watch_tick = _load_module(
    "paper_lineage_watch_tick_test_module",
    ROOT_DIR / "scripts/paper_lineage_watch_tick.py",
)


class _CompletedProcess:
    def __init__(self, returncode: int, stdout: str, stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_main_treats_no_candidate_as_healthy_tick(monkeypatch, capsys, tmp_path):
    args = paper_lineage_watch_tick.argparse.Namespace(
        base_url="http://127.0.0.1:8000",
        families="sweep_reversal",
        universe="usdc_perp_top30",
        symbol="BTCUSDC",
        candidate_limit=100,
        limit_symbols=30,
        symbol_concurrency=4,
        limit_1m=900,
        limit_5m=500,
        limit_15m=500,
        interval_seconds=1,
        max_attempts=1,
        submit_paper=True,
        paper_lineage_override=True,
        include_manual_review=False,
        paper_scenario="fill",
        report_dir="reports/operations/paper_candidate_watch/automation",
        latest_run_file=str(tmp_path / "latest_launchd_run.json"),
        no_write_report=True,
    )

    def _fake_parse_args():
        return args

    def _fake_run(cmd, *_args, **_kwargs):
        if "run_paper_exit_monitor.py" in " ".join(str(item) for item in cmd):
            return _CompletedProcess(
                0,
                stdout='{"processed_plans":1,"paper_candidate_plans":1,"partial_exit_events":0,"closed_events":1,"actions":[]}',
                stderr="",
            )
        return _CompletedProcess(
            1,
            stdout='{"overall_status":"NO_ELIGIBLE_CANDIDATE","summary_line":"no candidate","attempts_run":1}',
            stderr="",
        )

    monkeypatch.setattr(paper_lineage_watch_tick, "parse_args", _fake_parse_args)
    monkeypatch.setattr(paper_lineage_watch_tick.subprocess, "run", _fake_run)

    exit_code = paper_lineage_watch_tick.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"tick_status": "no_eligible_candidate"' in captured.out
    assert '"treated_as_healthy_tick": true' in captured.out
    assert '"closed_events": 1' in captured.out
    assert (tmp_path / "latest_launchd_run.json").exists()


def test_main_marks_duplicate_active_plan_as_existing_sample(monkeypatch, capsys, tmp_path):
    args = paper_lineage_watch_tick.argparse.Namespace(
        base_url="http://127.0.0.1:8000",
        families="sweep_reversal,trend_continuation",
        universe="usdc_perp_top30",
        symbol=None,
        candidate_limit=100,
        limit_symbols=30,
        symbol_concurrency=4,
        limit_1m=900,
        limit_5m=500,
        limit_15m=500,
        interval_seconds=1,
        max_attempts=1,
        submit_paper=True,
        paper_lineage_override=True,
        include_manual_review=False,
        paper_scenario="fill",
        report_dir="reports/operations/paper_candidate_watch/automation",
        latest_run_file=str(tmp_path / "latest_launchd_run.json"),
        no_write_report=True,
    )

    def _fake_parse_args():
        return args

    def _fake_run(cmd, *_args, **_kwargs):
        if "run_paper_exit_monitor.py" in " ".join(str(item) for item in cmd):
            return _CompletedProcess(
                0,
                stdout='{"processed_plans":1,"paper_candidate_plans":1,"partial_exit_events":0,"closed_events":0,"actions":[]}',
                stderr="",
            )
        return _CompletedProcess(
            1,
            stdout=(
                '{"overall_status":"NOT_READY","summary_line":"2 blocking drill check(s) remain.",'
                '"candidate":{"symbol":"ARBUSDC","strategy_family":"sweep_reversal"},'
                '"intent":{"submit_decision":"SKIP_EXISTING_ACTIVE_PLAN","decision_reason_code":"duplicate_active_thesis",'
                '"decision_reason_message":"Duplicate thesis detected against active plan plan_zone_c15debc65a13_confirm."}}'
            ),
            stderr="",
        )

    monkeypatch.setattr(paper_lineage_watch_tick, "parse_args", _fake_parse_args)
    monkeypatch.setattr(paper_lineage_watch_tick.subprocess, "run", _fake_run)

    exit_code = paper_lineage_watch_tick.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"tick_status": "active_sample_already_in_progress"' in captured.out
    assert '"active_sample_duplicate_hold": true' in captured.out


def test_main_prefers_existing_sample_status_even_when_watch_returns_zero(monkeypatch, capsys, tmp_path):
    args = paper_lineage_watch_tick.argparse.Namespace(
        base_url="http://127.0.0.1:8000",
        families="sweep_reversal,trend_continuation",
        universe="usdc_perp_top30",
        symbol=None,
        candidate_limit=100,
        limit_symbols=30,
        symbol_concurrency=4,
        limit_1m=900,
        limit_5m=500,
        limit_15m=500,
        interval_seconds=1,
        max_attempts=1,
        submit_paper=True,
        paper_lineage_override=True,
        include_manual_review=False,
        paper_scenario="fill",
        report_dir="reports/operations/paper_candidate_watch/automation",
        latest_run_file=str(tmp_path / "latest_launchd_run.json"),
        no_write_report=True,
    )

    def _fake_parse_args():
        return args

    def _fake_run(cmd, *_args, **_kwargs):
        if "run_paper_exit_monitor.py" in " ".join(str(item) for item in cmd):
            return _CompletedProcess(
                0,
                stdout='{"processed_plans":1,"paper_candidate_plans":1,"partial_exit_events":0,"closed_events":0,"actions":[]}',
                stderr="",
            )
        return _CompletedProcess(
            0,
            stdout=(
                '{"overall_status":"FOUND_ELIGIBLE_CANDIDATE","summary_line":"Eligible PAPER lineage candidate found on attempt 1.",'
                '"candidate":{"symbol":"ARBUSDC","strategy_family":"sweep_reversal"},'
                '"intent":{"submit_decision":"SKIP_EXISTING_ACTIVE_PLAN","decision_reason_code":"duplicate_active_thesis",'
                '"decision_reason_message":"Duplicate thesis detected against active plan plan_zone_c15debc65a13_confirm."}}'
            ),
            stderr="",
        )

    monkeypatch.setattr(paper_lineage_watch_tick, "parse_args", _fake_parse_args)
    monkeypatch.setattr(paper_lineage_watch_tick.subprocess, "run", _fake_run)

    exit_code = paper_lineage_watch_tick.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"tick_status": "active_sample_already_in_progress"' in captured.out
