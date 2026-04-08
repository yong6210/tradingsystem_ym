from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
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
        lineage_sample_scope="family_global",
        lineage_families="sweep_reversal",
        lineage_proof_goal_closed_trades=100,
        lineage_sample_days=180,
        alert_test_lookback_hours=24,
        stage_file=str(tmp_path / "current_stage.json"),
        latest_board_file=str(tmp_path / "latest_stage_board.json"),
        state_file=str(tmp_path / "last_alert_state.json"),
        webhook_url="",
        edge_sample_stall_hours=24,
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


def test_run_notifier_returns_warning_without_writing_state_on_failed_delivery(monkeypatch, tmp_path):
    stage_file = tmp_path / "current_stage.json"
    state_file = tmp_path / "last_alert_state.json"
    stage_file.write_text(json.dumps({"stage": "0_BLOCKED"}, ensure_ascii=False), encoding="utf-8")

    args = stage_monitor_tick.argparse.Namespace(
        base_url="http://127.0.0.1:8000",
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        limit=20,
        days=30,
        lineage_sample_scope="family_global",
        lineage_families="sweep_reversal",
        lineage_proof_goal_closed_trades=100,
        lineage_sample_days=180,
        alert_test_lookback_hours=24,
        stage_file=str(stage_file),
        latest_board_file=str(tmp_path / "latest_stage_board.json"),
        state_file=str(state_file),
        webhook_url="",
        edge_sample_stall_hours=24,
        dry_run=False,
    )

    monkeypatch.setattr(
        stage_monitor_tick.notify_stage_change,
        "_dispatch_stage_notification",
        lambda current, *, message, webhook_url: {
            "channel": "discord",
            "delivered": False,
            "skipped": False,
            "reason": "http_403",
            "status_code": 403,
        },
    )

    result = stage_monitor_tick._run_notifier(args)

    assert result["notified"] is False
    assert result["delivery"]["reason"] == "http_403"
    assert result["warning"] == "discord delivery not completed: http_403"
    assert state_file.exists() is False


def test_apply_edge_sample_stall_marks_stalled_after_threshold() -> None:
    now = datetime(2026, 3, 27, 9, 0, tzinfo=timezone.utc)
    previous = {
        "generated_at": (now - timedelta(hours=49)).isoformat(),
        "edge_experiment_review": {
            "daily_edge_kpis": {
                "closed_trade_count": 2,
            }
        },
        "edge_sample_gate_ready": False,
        "edge_sample_stall": {
            "active": False,
            "threshold_hours": 24,
            "hours_since_progress": 1.0,
            "progress_count": 2,
            "current_closed_trade_count": 2,
            "last_progress_at": (now - timedelta(hours=49)).isoformat(),
            "status": "tracking",
        },
    }
    current = {
        "generated_at": now.isoformat(),
        "lineage_sample_summary": {
            "scope": "family_global",
            "families": ["sweep_reversal"],
            "closed_trade_count": 2,
            "proof_goal_closed_trades": 100,
        },
        "edge_sample_gate_ready": False,
    }

    stage_monitor_tick._latest_closed_trade_ts = lambda **kwargs: now - timedelta(hours=49)
    payload = stage_monitor_tick._apply_edge_sample_stall(
        previous,
        current,
        symbol="BTCUSDC",
        lineage_sample_scope="family_global",
        lineage_families=["sweep_reversal"],
        lineage_sample_days=180,
        threshold_hours=24,
        now=now,
    )

    assert payload["edge_sample_stall"]["active"] is True
    assert payload["edge_sample_stall"]["progress_count"] == 2
    assert payload["edge_sample_stall"]["current_closed_trade_count"] == 2
    assert payload["edge_sample_stall"]["hours_since_progress"] == 49.0
    assert payload["edge_sample_stall"]["scope"] == "family_global"


def test_latest_family_closed_trade_ts_uses_closed_fill_metrics(monkeypatch) -> None:
    expected = datetime(2026, 4, 8, 7, 29, tzinfo=timezone.utc)
    monkeypatch.setattr(
        stage_monitor_tick.ops_stage_board,
        "_family_closed_fill_metrics",
        lambda **kwargs: (130, expected),
    )

    latest = stage_monitor_tick._latest_family_closed_trade_ts(
        families=["sweep_reversal", "trend_continuation"],
        sample_days=180,
    )

    assert latest == expected
