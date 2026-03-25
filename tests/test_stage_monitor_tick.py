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


stage_monitor_tick = _load_module(
    "stage_monitor_tick_test_module",
    ROOT_DIR / "scripts/stage_monitor_tick.py",
)


def test_main_prints_notifier_payload(monkeypatch, capsys, tmp_path):
    args = stage_monitor_tick.argparse.Namespace(
        base_url="http://127.0.0.1:8000",
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        limit=20,
        days=30,
        alert_test_lookback_hours=24,
        stage_file=str(tmp_path / "current_stage.json"),
        latest_board_file=str(tmp_path / "latest_stage_board.json"),
        state_file=str(tmp_path / "last_alert_state.json"),
        webhook_url="",
        dry_run=True,
    )

    board_calls: list[stage_monitor_tick.argparse.Namespace] = []
    notify_calls: list[stage_monitor_tick.argparse.Namespace] = []

    def _fake_parse_args():
        return args

    def _fake_run_stage_board(passed_args):
        board_calls.append(passed_args)
        return {"stage": "0_BLOCKED"}

    def _fake_run_notifier(passed_args):
        notify_calls.append(passed_args)
        return {"notified": False, "events": [], "dry_run": True}

    monkeypatch.setattr(stage_monitor_tick, "parse_args", _fake_parse_args)
    monkeypatch.setattr(stage_monitor_tick, "_run_stage_board", _fake_run_stage_board)
    monkeypatch.setattr(stage_monitor_tick, "_run_notifier", _fake_run_notifier)

    exit_code = stage_monitor_tick.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert board_calls == [args]
    assert notify_calls == [args]
    assert '"dry_run": true' in captured.out
