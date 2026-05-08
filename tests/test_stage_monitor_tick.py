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


def test_run_stage_board_uses_read_only_report_queries(monkeypatch, tmp_path):
    args = stage_monitor_tick.argparse.Namespace(
        base_url="http://127.0.0.1:8000",
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        limit=20,
        days=30,
        lineage_sample_scope="family_global",
        lineage_families="sweep_reversal,trend_continuation",
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
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def _fake_request_json(base_url: str, method: str, path: str, *, query=None):
        calls.append((method, path, dict(query or {})))
        if path == "/validation/report":
            return {"validation_report": {"deployment_approval_summary": {}, "approval_strip_summary": {}}}
        if path == "/operations/checklist":
            return {"overall_status": "WARN", "items": [], "approval_strip_summary": {}}
        return {"approval_strip_summary": {}}

    monkeypatch.setattr(stage_monitor_tick.ops_stage_board, "_request_json", _fake_request_json)
    monkeypatch.setattr(stage_monitor_tick.ops_stage_board, "_build_stage_payload", lambda *args, **kwargs: {"stage": "x"})
    monkeypatch.setattr(stage_monitor_tick.ops_stage_board, "_write_stage_file", lambda *args, **kwargs: None)

    payload = stage_monitor_tick._run_stage_board(args)

    assert payload == {"stage": "x"}
    assert calls[0][1] == "/validation/report"
    assert calls[0][2]["refresh"] is False
    assert calls[1][1] == "/operations/checklist"
    assert calls[1][2]["write_report"] is False


def test_run_stage_board_falls_back_to_existing_snapshot_on_request_failure(monkeypatch, tmp_path):
    stage_file = tmp_path / "current_stage.json"
    latest_board_file = tmp_path / "latest_stage_board.json"
    stage_file.write_text(json.dumps({"stage": "2_LINEAGE_READY", "post_patch_closed_trade_count": 41}), encoding="utf-8")
    args = stage_monitor_tick.argparse.Namespace(
        base_url="http://127.0.0.1:8000",
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        limit=20,
        days=30,
        lineage_sample_scope="family_global",
        lineage_families="sweep_reversal,trend_continuation",
        lineage_proof_goal_closed_trades=100,
        lineage_sample_days=180,
        alert_test_lookback_hours=24,
        stage_file=str(stage_file),
        latest_board_file=str(latest_board_file),
        state_file=str(tmp_path / "last_alert_state.json"),
        webhook_url="",
        edge_sample_stall_hours=24,
        dry_run=True,
    )
    written: list[dict[str, object]] = []

    def _fake_request_json(*args, **kwargs):
        raise RuntimeError("stage board timed out")

    monkeypatch.setattr(stage_monitor_tick.ops_stage_board, "_request_json", _fake_request_json)
    monkeypatch.setattr(stage_monitor_tick.ops_stage_board, "_write_stage_file", lambda _path, payload: written.append(dict(payload)))

    payload = stage_monitor_tick._run_stage_board(args)

    assert payload["stage"] == "2_LINEAGE_READY"
    assert payload["post_patch_closed_trade_count"] == 41
    assert payload["stage_board_fallback_used"] is True
    assert "timed out" in str(payload["stage_board_error"])
    assert written[-1]["stage_board_fallback_used"] is True


def test_run_stage_board_success_reuses_recent_runtime_monitor_snapshot(monkeypatch, tmp_path):
    stage_file = tmp_path / "current_stage.json"
    latest_board_file = tmp_path / "latest_stage_board.json"
    state_file = tmp_path / "last_alert_state.json"
    state_file.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "stage": "3_APPROVAL_REVIEW",
                "selected_trial_run_id": "LINEAGE_GLOBAL_v2_true_threshold",
                "checklist_status": "WARN",
                "playbook_go_no_go": "MANUAL_REVIEW",
                "lineage_sample_summary": {"closed_trade_count": 278},
                "risk_gate_summary": {"risk_state": "OPEN"},
                "runtime_reopen_status": {"status": "manual_review_required"},
                "runtime_signoff_summary": {
                    "status": "manual_signoff_required",
                    "runtime_decision": {
                        "band": "AMBER_CONDITIONAL",
                        "effective_action": "conditional_micro_live_signoff",
                        "allowed_reopen_scope": "MICRO_LIVE_ONLY",
                    },
                    "runtime_reopen_gate_summary": {
                        "micro_live": {"status": "ready", "closed_trade_count": 50, "min_closed_trades": 50},
                        "full_live": {"status": "not_ready", "closed_trade_count": 50, "min_closed_trades": 80},
                    },
                    "approval_template_focus": {
                        "post_patch_sample_summary": {
                            "closed_trade_count": 50,
                            "target_closed_trades": 20,
                            "remaining_to_target": 0,
                            "ready_for_replay_refresh": True,
                        }
                    },
                },
                "runtime_preflight_summary": {
                    "status": "READY_FOR_MICRO_LIVE",
                },
                "runtime_live_cluster_guard_summary": {
                    "status": "cluster_window_cap_active",
                    "cluster_window_blocked_candidates": 2,
                    "loss_cooldown_blocked_candidates": 0,
                    "families": ["sweep_reversal"],
                    "symbols": ["ETHUSDC"],
                },
            }
        ),
        encoding="utf-8",
    )
    args = stage_monitor_tick.argparse.Namespace(
        base_url="http://127.0.0.1:8000",
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        limit=20,
        days=30,
        lineage_sample_scope="family_global",
        lineage_families="sweep_reversal,trend_continuation",
        lineage_proof_goal_closed_trades=100,
        lineage_sample_days=180,
        alert_test_lookback_hours=24,
        stage_file=str(stage_file),
        latest_board_file=str(latest_board_file),
        state_file=str(state_file),
        webhook_url="",
        edge_sample_stall_hours=24,
        dry_run=True,
    )

    def _fake_request_json(base_url: str, method: str, path: str, *, query=None):
        if path == "/validation/report":
            return {"validation_report": {"deployment_approval_summary": {}, "approval_strip_summary": {}}}
        if path == "/operations/checklist":
            return {"overall_status": "WARN", "items": [], "approval_strip_summary": {}}
        return {"approval_strip_summary": {}}

    monkeypatch.setattr(stage_monitor_tick.ops_stage_board, "_request_json", _fake_request_json)
    monkeypatch.setattr(stage_monitor_tick.ops_stage_board, "_build_stage_payload", lambda *args, **kwargs: {
        "stage": "0_BLOCKED",
        "selected_trial_run_id": "LINEAGE_GLOBAL_v2_true_threshold",
        "checklist_status": "WARN",
        "playbook_go_no_go": "MANUAL_REVIEW",
        "lineage_sample_summary": {"closed_trade_count": 278},
        "risk_gate_summary": {"risk_state": "OPEN"},
    })
    monkeypatch.setattr(stage_monitor_tick.ops_stage_board, "_write_stage_file", lambda *args, **kwargs: None)

    payload = stage_monitor_tick._run_stage_board(args)

    assert payload["stage"] == "3_APPROVAL_REVIEW"
    assert payload["runtime_decision_band"] == "AMBER_CONDITIONAL"
    assert payload["runtime_effective_action"] == "conditional_micro_live_signoff"
    assert payload["runtime_operator_signoff_summary"]["status"] == "ready_for_manual_micro_live_signoff"
    assert payload["runtime_live_cluster_guard_summary"]["status"] == "cluster_window_cap_active"


def test_run_stage_board_fallback_prefers_richer_runtime_snapshot(monkeypatch, tmp_path):
    stage_file = tmp_path / "current_stage.json"
    latest_board_file = tmp_path / "latest_stage_board.json"
    state_file = tmp_path / "last_alert_state.json"
    stage_file.write_text(
        json.dumps({"generated_at": "2026-04-13T21:35:24+00:00", "stage": "2_LINEAGE_READY"}),
        encoding="utf-8",
    )
    state_file.write_text(
        json.dumps(
            {
                "generated_at": "2026-04-13T21:25:03+00:00",
                "stage": "3_APPROVAL_REVIEW",
                "runtime_decision_band": "AMBER_CONDITIONAL",
                "runtime_effective_action": "conditional_micro_live_signoff",
                "runtime_allowed_reopen_scope": "MICRO_LIVE_ONLY",
                "runtime_preflight_summary": {"status": "READY_FOR_MICRO_LIVE"},
            }
        ),
        encoding="utf-8",
    )
    args = stage_monitor_tick.argparse.Namespace(
        base_url="http://127.0.0.1:8000",
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        limit=20,
        days=30,
        lineage_sample_scope="family_global",
        lineage_families="sweep_reversal,trend_continuation",
        lineage_proof_goal_closed_trades=100,
        lineage_sample_days=180,
        alert_test_lookback_hours=24,
        stage_file=str(stage_file),
        latest_board_file=str(latest_board_file),
        state_file=str(state_file),
        webhook_url="",
        edge_sample_stall_hours=24,
        dry_run=True,
    )

    monkeypatch.setattr(stage_monitor_tick.ops_stage_board, "_request_json", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("stage board timed out")))
    monkeypatch.setattr(stage_monitor_tick.ops_stage_board, "_write_stage_file", lambda *args, **kwargs: None)

    payload = stage_monitor_tick._run_stage_board(args)

    assert payload["stage"] == "3_APPROVAL_REVIEW"
    assert payload["runtime_decision_band"] == "AMBER_CONDITIONAL"
    assert payload["runtime_preflight_summary"]["status"] == "READY_FOR_MICRO_LIVE"
    assert payload["stage_board_fallback_used"] is True


def test_apply_post_unlock_review_bundle_waits_until_review_window_opens():
    args = stage_monitor_tick.argparse.Namespace(
        base_url="http://127.0.0.1:8000",
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=30,
    )
    current = {
        "post_unlock_review_summary": {
            "active": True,
            "review_window_open": False,
            "bundle_review_command": "./.venv/bin/python scripts/run_post_unlock_review.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30",
        }
    }

    payload = stage_monitor_tick._apply_post_unlock_review_bundle(current, args)

    assert payload["post_unlock_bundle_result"]["executed"] is False
    assert payload["post_unlock_bundle_result"]["status"] == "waiting_for_review_window"


def test_apply_post_unlock_review_bundle_uses_post_patch_ready_override(monkeypatch):
    args = stage_monitor_tick.argparse.Namespace(
        base_url="http://127.0.0.1:8000",
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=30,
    )
    current = {
        "all_readiness_gates_ready": True,
        "risk_gate_summary": {"status": "PASS", "risk_state": "OPEN"},
        "post_unlock_review_summary": {
            "active": True,
            "review_window_open": False,
            "bundle_review_command": "./.venv/bin/python scripts/run_post_unlock_review.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30",
        },
        "post_patch_ready_for_replay_refresh": True,
    }

    monkeypatch.setattr(
        stage_monitor_tick,
        "_run_post_unlock_review_bundle",
        lambda args: {
            "status": "MANUAL_REVIEW_REQUIRED",
            "summary_line": "manual review still required",
            "bundle_review_command": "./.venv/bin/python scripts/run_post_unlock_review.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30",
            "micro_live_preflight": {"overall_status": "NOT_READY"},
            "post_live_pruning_review": {"decision": "KEEP_OPTIONAL_HOLD"},
        },
    )

    payload = stage_monitor_tick._apply_post_unlock_review_bundle(current, args)

    assert payload["post_unlock_review_summary"]["review_window_open"] is True
    assert payload["post_unlock_bundle_result"]["executed"] is True
    assert payload["post_unlock_bundle_result"]["status"] == "MANUAL_REVIEW_REQUIRED"


def test_apply_post_unlock_review_bundle_runs_when_review_window_opens(monkeypatch):
    args = stage_monitor_tick.argparse.Namespace(
        base_url="http://127.0.0.1:8000",
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=30,
    )
    current = {
        "post_unlock_review_summary": {
            "active": True,
            "review_window_open": True,
            "bundle_review_command": "./.venv/bin/python scripts/run_post_unlock_review.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30",
        }
    }

    monkeypatch.setattr(
        stage_monitor_tick,
        "_run_post_unlock_review_bundle",
        lambda args: {
            "status": "READY_TO_REOPEN_RUNTIME",
            "summary_line": "Post-unlock review bundle is green.",
            "bundle_review_command": "./.venv/bin/python scripts/run_post_unlock_review.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30",
            "micro_live_preflight": {"overall_status": "READY_FOR_MICRO_LIVE"},
            "post_live_pruning_review": {"decision": "REOPEN_PRUNING_REVIEW"},
        },
    )

    payload = stage_monitor_tick._apply_post_unlock_review_bundle(current, args)

    assert payload["post_unlock_bundle_result"]["executed"] is True
    assert payload["post_unlock_bundle_result"]["status"] == "READY_TO_REOPEN_RUNTIME"
    assert payload["post_unlock_bundle_result"]["micro_live_preflight_status"] == "READY_FOR_MICRO_LIVE"
    assert payload["post_unlock_bundle_result"]["post_live_pruning_review_decision"] == "REOPEN_PRUNING_REVIEW"


def test_apply_post_unlock_review_bundle_reuses_recent_previous_result(monkeypatch):
    args = stage_monitor_tick.argparse.Namespace(
        base_url="http://127.0.0.1:8000",
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=30,
    )
    current = {
        "post_unlock_review_summary": {
            "active": True,
            "review_window_open": True,
            "bundle_review_command": "./.venv/bin/python scripts/run_post_unlock_review.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30",
        }
    }
    previous = {
        "post_unlock_bundle_result": {
            "status": "READY_TO_REOPEN_RUNTIME",
            "bundle_review_command": "./.venv/bin/python scripts/run_post_unlock_review.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30",
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "summary": "cached",
        }
    }

    monkeypatch.setattr(
        stage_monitor_tick,
        "_run_post_unlock_review_bundle",
        lambda args: (_ for _ in ()).throw(AssertionError("bundle should be reused")),
    )

    payload = stage_monitor_tick._apply_post_unlock_review_bundle(current, args, previous=previous)

    assert payload["post_unlock_bundle_result"]["status"] == "READY_TO_REOPEN_RUNTIME"
    assert payload["post_unlock_bundle_result"]["cache_reused"] is True


def test_apply_post_unlock_review_bundle_downgrades_failures_to_error(monkeypatch):
    args = stage_monitor_tick.argparse.Namespace(
        base_url="http://127.0.0.1:8000",
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=30,
    )
    current = {
        "post_unlock_review_summary": {
            "active": True,
            "review_window_open": True,
            "bundle_review_command": "./.venv/bin/python scripts/run_post_unlock_review.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30",
        }
    }

    monkeypatch.setattr(
        stage_monitor_tick,
        "_run_post_unlock_review_bundle",
        lambda args: (_ for _ in ()).throw(RuntimeError("bundle blew up")),
    )

    payload = stage_monitor_tick._apply_post_unlock_review_bundle(current, args)

    assert payload["post_unlock_bundle_result"]["status"] == "ERROR"
    assert "bundle blew up" in payload["post_unlock_bundle_result"]["summary"]


def test_apply_runtime_reopen_status_maps_bundle_state():
    current = {
        "risk_gate_summary": {"risk_state": "OPEN"},
        "post_unlock_review_summary": {"review_window_open": True},
        "post_unlock_bundle_result": {"status": "READY_TO_REOPEN_RUNTIME"},
    }

    payload = stage_monitor_tick._apply_runtime_reopen_status(current)

    assert payload["runtime_reopen_status"]["status"] == "ready_to_reopen_runtime"
    assert payload["runtime_reopen_status"]["ready"] is True


def test_apply_runtime_reopen_status_uses_post_patch_ready_override():
    current = {
        "all_readiness_gates_ready": True,
        "post_patch_ready_for_replay_refresh": True,
        "risk_gate_summary": {"status": "PASS", "risk_state": "OPEN"},
        "post_unlock_review_summary": {"review_window_open": False},
        "post_unlock_bundle_result": {"status": "MANUAL_REVIEW_REQUIRED"},
    }

    payload = stage_monitor_tick._apply_runtime_reopen_status(current)

    assert payload["runtime_reopen_status"]["status"] == "manual_review_required"
    assert payload["runtime_reopen_status"]["ready"] is False


def test_apply_runtime_signoff_summary_promotes_required_reviews_when_runtime_is_ready():
    current = {
        "runtime_reopen_status": {"status": "ready_to_reopen_runtime", "ready": True},
        "runtime_signoff_summary": {
            "status": "not_ready",
            "required_reviews": [
                {"code": "approval_template_review", "worst_scenario_status": "FAIL"},
                {"code": "execution_reconciliation_review"},
            ],
            "advisory_reviews": [{"code": "symbol_edge_thin"}],
            "required_count": 2,
            "advisory_count": 1,
            "approval_template_focus": {"worst_scenario": "latency_plus_1_bar"},
        },
    }

    payload = stage_monitor_tick._apply_runtime_signoff_summary(current)

    assert payload["runtime_signoff_summary"]["status"] == "manual_signoff_required"
    assert payload["runtime_signoff_summary"]["required_count"] == 2
    assert payload["runtime_signoff_summary"]["advisory_count"] == 1
    assert payload["runtime_signoff_summary"]["operator_recommendation"] == "hold_runtime_reopen"
    assert payload["runtime_signoff_summary"]["approval_template_focus"]["worst_scenario"] == "latency_plus_1_bar"


def test_apply_runtime_signoff_summary_falls_back_to_snapshot_focus():
    current = {
        "runtime_reopen_status": {"status": "ready_to_reopen_runtime", "ready": True},
        "approval_template_focus": {"worst_scenario": "latency_plus_1_bar"},
        "runtime_signoff_summary": {
            "status": "not_ready",
            "required_reviews": [{"code": "approval_template_review", "worst_scenario_status": "FAIL"}],
            "advisory_reviews": [],
        },
    }

    payload = stage_monitor_tick._apply_runtime_signoff_summary(current)

    assert payload["runtime_signoff_summary"]["approval_template_focus"]["worst_scenario"] == "latency_plus_1_bar"


def test_apply_runtime_signoff_summary_treats_manual_review_required_as_signoff_eligible():
    current = {
        "runtime_reopen_status": {"status": "manual_review_required", "ready": False},
        "runtime_signoff_summary": {
            "status": "not_ready",
            "required_reviews": [{"code": "approval_template_review", "worst_scenario_status": "FAIL"}],
            "advisory_reviews": [],
        },
    }

    payload = stage_monitor_tick._apply_runtime_signoff_summary(current)

    assert payload["runtime_signoff_summary"]["status"] == "manual_signoff_required"
    assert payload["runtime_signoff_summary"]["operator_recommendation"] == "hold_runtime_reopen"


def test_apply_runtime_signoff_summary_treats_pending_bundle_as_signoff_eligible():
    current = {
        "runtime_reopen_status": {"status": "review_window_open_pending_bundle", "ready": False},
        "runtime_signoff_summary": {
            "status": "not_ready",
            "required_reviews": [{"code": "approval_template_review", "worst_scenario_status": "FAIL"}],
            "advisory_reviews": [],
        },
    }

    payload = stage_monitor_tick._apply_runtime_signoff_summary(current)

    assert payload["runtime_signoff_summary"]["status"] == "manual_signoff_required"


def test_apply_runtime_signoff_decision_syncs_operator_recommendation_to_conditional_micro_live():
    current = {
        "runtime_reopen_status": {"status": "manual_review_required", "ready": False},
        "runtime_signoff_summary": {
            "required_reviews": [{"code": "approval_template_review", "worst_scenario_status": "FAIL"}],
            "advisory_reviews": [],
            "approval_template_focus": {
                "replay_max_drawdown_r": 10.1003,
                "replay_p5_r": -1.05,
                "downside_profile": {"stop_loss_share": 0.5341, "worst_loss_streak": 9},
                "post_patch_sample_summary": {
                    "closed_trade_count": 20,
                    "ready_for_replay_refresh": True,
                    "replay_max_drawdown_r": 3.25,
                    "replay_p5_r": -1.0,
                    "stop_loss_share": 0.41,
                    "worst_loss_streak": 4,
                },
            },
            "operator_recommendation": "hold_runtime_reopen",
        },
    }

    payload = stage_monitor_tick._apply_runtime_signoff_decision(current)

    assert payload["runtime_signoff_summary"]["runtime_decision"]["band"] == "AMBER_CONDITIONAL"
    assert payload["runtime_signoff_summary"]["operator_recommendation"] == "conditional_micro_live_signoff"


def test_apply_runtime_signoff_decision_syncs_operator_recommendation_to_conditional_full_live():
    current = {
        "runtime_reopen_status": {"status": "manual_review_required", "ready": False},
        "runtime_signoff_summary": {
            "required_reviews": [{"code": "approval_template_review", "worst_scenario_status": "FAIL"}],
            "advisory_reviews": [],
            "approval_template_focus": {
                "replay_max_drawdown_r": 10.1003,
                "replay_p5_r": -1.05,
                "downside_profile": {"stop_loss_share": 0.5341, "worst_loss_streak": 9},
                "post_patch_sample_summary": {
                    "closed_trade_count": 80,
                    "ready_for_replay_refresh": True,
                    "replay_max_drawdown_r": 4.4,
                    "replay_p5_r": -1.0,
                    "stop_loss_share": 0.29,
                    "worst_loss_streak": 4,
                },
            },
            "operator_recommendation": "hold_runtime_reopen",
        },
    }

    payload = stage_monitor_tick._apply_runtime_signoff_decision(current)

    assert payload["runtime_signoff_summary"]["runtime_decision"]["band"] == "AMBER_CONDITIONAL"
    assert payload["runtime_signoff_summary"]["operator_recommendation"] == "conditional_full_live_signoff"
    assert payload["runtime_signoff_summary"]["runtime_reopen_gate_summary"]["full_live"]["status"] == "ready"


def test_apply_runtime_signoff_decision_marks_red_hold_from_approval_focus():
    current = {
        "runtime_reopen_status": {"status": "ready_to_reopen_runtime", "ready": True},
        "runtime_signoff_summary": {
            "required_reviews": [
                {"code": "approval_template_review", "worst_scenario_status": "FAIL"},
            ],
            "approval_template_focus": {
                "replay_max_drawdown_r": 10.1003,
                "replay_p5_r": -1.05,
                "downside_profile": {
                    "stop_loss_share": 0.5341,
                    "worst_loss_streak": 9,
                },
            },
        },
    }

    payload = stage_monitor_tick._apply_runtime_signoff_decision(current)

    decision = payload["runtime_signoff_summary"]["runtime_decision"]
    assert decision["band"] == "RED_HOLD"
    assert decision["effective_action"] == "hold_runtime_reopen"


def test_apply_runtime_signoff_projection_copies_nested_focus_and_decision():
    current = {
        "runtime_signoff_summary": {
            "status": "manual_signoff_required",
            "required_reviews": [{"code": "approval_template_review", "worst_scenario_status": "FAIL"}],
            "advisory_reviews": [{"code": "portfolio_headroom_review"}],
            "operator_recommendation": "hold_runtime_reopen",
            "approval_template_focus": {
                "worst_scenario": "latency_plus_1_bar",
                "worst_scenario_status": "FAIL",
                "post_patch_sample_summary": {
                    "closed_trade_count": 3,
                    "target_closed_trades": 20,
                    "remaining_to_target": 17,
                    "ready_for_replay_refresh": False,
                },
                "live_eligible_post_patch_sample_summary": {
                    "closed_trade_count": 2,
                    "target_closed_trades": 15,
                    "remaining_to_target": 13,
                    "ready_for_replay_refresh": False,
                    "contract_scope": "limit_only",
                },
                "historical_execution_contract_proof_summary": {
                    "closed_trade_count": 9,
                    "target_closed_trades": 20,
                    "remaining_to_target": 11,
                    "ready_for_replay_refresh": False,
                    "contract_scope": "historical_limit_only",
                    "advisory_only": True,
                    "lookback_days": 180,
                },
                "historical_walk_forward_execution_contract_proof_summary": {
                    "closed_trade_count": 4,
                    "target_closed_trades": 20,
                    "remaining_to_target": 16,
                    "ready_for_replay_refresh": False,
                    "contract_scope": "historical_walk_forward_limit_only",
                    "advisory_only": True,
                },
                "historical_walk_forward_strategy_proof_summary": {
                    "closed_trade_count": 11,
                    "target_closed_trades": 100,
                    "remaining_to_target": 89,
                    "ready_for_replay_refresh": False,
                    "contract_scope": "historical_walk_forward_strategy_level",
                    "advisory_only": True,
                },
                "trend_proof_post_patch_sample_summary": {
                    "closed_trade_count": 1,
                    "target_closed_trades": 5,
                    "remaining_to_target": 4,
                    "ready_for_replay_refresh": False,
                    "contract_scope": "trend_limit_only",
                    "eligible_families": ["trend_continuation"],
                },
                "historical_walk_forward_trend_proof_summary": {
                    "closed_trade_count": 0,
                    "target_closed_trades": 5,
                    "remaining_to_target": 5,
                    "ready_for_replay_refresh": False,
                    "contract_scope": "historical_walk_forward_trend_limit_only",
                    "eligible_families": ["trend_continuation"],
                    "advisory_only": True,
                },
            },
            "runtime_decision": {
                "band": "RED_HOLD",
                "effective_action": "hold_runtime_reopen",
                "allowed_reopen_scope": "none",
            },
            "runtime_reopen_gate_summary": {
                "active_scope": "none",
                "micro_live": {"status": "not_ready", "closed_trade_count": 3, "min_closed_trades": 50},
                "full_live": {"status": "not_ready", "closed_trade_count": 3, "min_closed_trades": 80},
            },
        }
    }

    payload = stage_monitor_tick._apply_runtime_signoff_projection(current)

    assert payload["approval_template_focus"]["worst_scenario"] == "latency_plus_1_bar"
    assert payload["runtime_decision"]["band"] == "RED_HOLD"
    assert payload["runtime_decision"]["effective_action"] == "hold_runtime_reopen"
    assert payload["runtime_signoff_status"] == "manual_signoff_required"
    assert payload["runtime_operator_recommendation"] == "hold_runtime_reopen"
    assert payload["required_reviews"][0]["code"] == "approval_template_review"
    assert payload["advisory_reviews"][0]["code"] == "portfolio_headroom_review"
    assert payload["runtime_required_review_codes"] == ["approval_template_review"]
    assert payload["runtime_advisory_review_codes"] == ["portfolio_headroom_review"]
    assert payload["runtime_decision_band"] == "RED_HOLD"
    assert payload["runtime_effective_action"] == "hold_runtime_reopen"
    assert payload["approval_worst"] == "latency_plus_1_bar"
    assert payload["approval_worst_status"] == "FAIL"
    assert payload["runtime_reopen_gate_summary"]["micro_live"]["status"] == "not_ready"
    assert payload["post_patch_closed_trade_count"] == 3
    assert payload["live_eligible_post_patch_closed_trade_count"] == 2
    assert payload["historical_execution_contract_proof_closed_trade_count"] == 9
    assert payload["historical_walk_forward_execution_contract_proof_closed_trade_count"] == 4
    assert payload["historical_walk_forward_strategy_proof_closed_trade_count"] == 11
    assert payload["trend_proof_post_patch_closed_trade_count"] == 1
    assert payload["historical_walk_forward_trend_proof_closed_trade_count"] == 0
    assert payload["runtime_live_contract_scope"] == "limit_only"
    assert payload["post_patch_target_closed_trades"] == 20
    assert payload["runtime_contract_partition_summary"]["live_contract_scope"] == "limit_only"
    assert payload["runtime_contract_partition_summary"]["live_eligible_closed_trade_count"] == 2
    assert payload["runtime_contract_partition_summary"]["historical_execution_contract_closed_trade_count"] == 9
    assert payload["runtime_contract_partition_summary"]["historical_walk_forward_execution_contract_closed_trade_count"] == 4
    assert payload["runtime_contract_partition_summary"]["historical_walk_forward_strategy_closed_trade_count"] == 11
    assert payload["runtime_contract_partition_summary"]["trend_proof_closed_trade_count"] == 1
    assert payload["runtime_contract_partition_summary"]["historical_walk_forward_trend_closed_trade_count"] == 0
    assert payload["runtime_live_subset_performance_summary"]["historical_execution_subset"]["closed_trade_count"] == 9
    assert payload["runtime_live_subset_performance_summary"]["historical_walk_forward_execution_subset"]["closed_trade_count"] == 4
    assert payload["runtime_live_subset_performance_summary"]["historical_walk_forward_strategy_subset"]["closed_trade_count"] == 11
    assert payload["runtime_live_subset_performance_summary"]["live_subset"]["closed_trade_count"] == 2
    assert payload["runtime_live_subset_performance_summary"]["trend_proof_subset"]["closed_trade_count"] == 1
    assert payload["runtime_live_subset_performance_summary"]["historical_walk_forward_trend_subset"]["closed_trade_count"] == 0
    assert payload["runtime_live_subset_performance_summary"]["full_truth"]["closed_trade_count"] == 3


def test_apply_runtime_signoff_approval_focus_attaches_global_replay_metrics(monkeypatch):
    current = {
        "selected_trial_run_id": "LINEAGE_GLOBAL_v2_true_threshold",
        "lineage_sample_summary": {"scope": "family_global"},
        "runtime_signoff_summary": {
            "status": "manual_signoff_required",
            "required_reviews": [
                {
                    "code": "approval_template_review",
                    "worst_scenario": "latency_plus_1_bar",
                    "worst_scenario_status": "FAIL",
                    "worst_scenario_reason": "catastrophic_drawdown:replay_output",
                }
            ],
            "advisory_reviews": [],
        },
    }

    monkeypatch.setattr(
        stage_monitor_tick.run_runtime_signoff_review,
        "_attach_approval_template_focus",
        lambda payload, *, stage, symbol, base_url, request_json_fn: {
            **payload,
            "approval_template_focus": {
                "focus_symbol": "LINEAGE_GLOBAL",
                "worst_scenario": "latency_plus_1_bar",
                "replay_max_drawdown_r": 10.1003,
                "replay_p5_r": -1.05,
                "approximation_gap_max_drawdown_r": 0.95,
            },
        },
    )

    payload = stage_monitor_tick._apply_runtime_signoff_approval_focus(
        current,
        symbol="BTCUSDC",
        base_url="http://127.0.0.1:8000",
    )

    focus = payload["runtime_signoff_summary"]["approval_template_focus"]
    assert focus["focus_symbol"] == "LINEAGE_GLOBAL"
    assert focus["replay_max_drawdown_r"] == 10.1003
    assert focus["replay_p5_r"] == -1.05
    assert focus["approximation_gap_max_drawdown_r"] == 0.95


def test_apply_runtime_signoff_approval_focus_reuses_recent_previous_focus(monkeypatch):
    current = {
        "selected_trial_run_id": "LINEAGE_GLOBAL_v2_true_threshold",
        "lineage_sample_summary": {"scope": "family_global"},
        "runtime_signoff_summary": {
            "status": "manual_signoff_required",
            "required_reviews": [
                {
                    "code": "approval_template_review",
                    "worst_scenario": "latency_plus_1_bar",
                    "worst_scenario_status": "FAIL",
                }
            ],
            "advisory_reviews": [],
        },
    }
    previous = {
        "runtime_signoff_summary": {
            "approval_template_focus_cached_at": datetime.now(timezone.utc).isoformat(),
            "approval_template_focus": {
                "focus_symbol": "LINEAGE_GLOBAL",
                "worst_scenario": "latency_plus_1_bar",
                "computed_at": datetime.now(timezone.utc).isoformat(),
                "replay_max_drawdown_r": 10.1003,
            },
        }
    }

    monkeypatch.setattr(
        stage_monitor_tick.run_runtime_signoff_review,
        "_attach_approval_template_focus",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("focus should be reused")),
    )

    payload = stage_monitor_tick._apply_runtime_signoff_approval_focus(
        current,
        symbol="BTCUSDC",
        base_url="http://127.0.0.1:8000",
        previous=previous,
    )

    assert payload["runtime_signoff_summary"]["approval_template_focus"]["replay_max_drawdown_r"] == 10.1003


def test_apply_runtime_signoff_approval_focus_preserves_previous_focus_when_refresh_returns_no_payload(
    monkeypatch,
):
    current = {
        "selected_trial_run_id": "LINEAGE_GLOBAL_v2_true_threshold",
        "lineage_sample_summary": {"scope": "family_global"},
        "runtime_signoff_summary": {
            "status": "manual_signoff_required",
            "required_reviews": [
                {
                    "code": "approval_template_review",
                    "worst_scenario": "latency_plus_1_bar",
                    "worst_scenario_status": "FAIL",
                }
            ],
            "advisory_reviews": [],
        },
    }
    previous = {
        "runtime_signoff_summary": {
            "approval_template_focus_cached_at": "2026-04-12T20:00:00+00:00",
            "approval_template_focus": {
                "focus_symbol": "LINEAGE_GLOBAL",
                "worst_scenario": "latency_plus_1_bar",
                "computed_at": "2026-04-12T20:00:00+00:00",
                "replay_max_drawdown_r": 10.1003,
                "replay_p5_r": -1.05,
            },
        }
    }

    monkeypatch.setattr(
        stage_monitor_tick.run_runtime_signoff_review,
        "_attach_approval_template_focus",
        lambda payload, **kwargs: {
            **payload,
            "approval_template_focus_error": "request failed for /validation/stress-replay-assessment: timed out",
        },
    )

    payload = stage_monitor_tick._apply_runtime_signoff_approval_focus(
        current,
        symbol="BTCUSDC",
        base_url="http://127.0.0.1:8000",
        previous=previous,
    )

    focus = payload["runtime_signoff_summary"]["approval_template_focus"]
    assert focus["focus_symbol"] == "LINEAGE_GLOBAL"
    assert focus["replay_max_drawdown_r"] == 10.1003
    assert "approval_template_focus_error" not in payload["runtime_signoff_summary"]


def test_apply_runtime_signoff_approval_focus_reuses_current_snapshot_focus_when_refresh_raises(
    monkeypatch,
):
    current = {
        "selected_trial_run_id": "LINEAGE_GLOBAL_v2_true_threshold",
        "lineage_sample_summary": {"scope": "family_global"},
        "approval_template_focus": {
            "focus_symbol": "LINEAGE_GLOBAL",
            "worst_scenario": "latency_plus_1_bar",
            "computed_at": "2026-04-13T11:32:50+00:00",
            "replay_max_drawdown_r": 10.1003,
            "replay_p5_r": -1.05,
            "post_patch_sample_summary": {"closed_trade_count": 41},
        },
        "runtime_signoff_summary": {
            "status": "manual_signoff_required",
            "required_reviews": [
                {
                    "code": "approval_template_review",
                    "worst_scenario": "latency_plus_1_bar",
                    "worst_scenario_status": "FAIL",
                }
            ],
            "advisory_reviews": [],
        },
    }

    monkeypatch.setattr(
        stage_monitor_tick.run_runtime_signoff_review,
        "_attach_approval_template_focus",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Remote end closed connection without response")),
    )

    payload = stage_monitor_tick._apply_runtime_signoff_approval_focus(
        current,
        symbol="BTCUSDC",
        base_url="http://127.0.0.1:8000",
    )

    focus = payload["runtime_signoff_summary"]["approval_template_focus"]
    assert focus["focus_symbol"] == "LINEAGE_GLOBAL"
    assert focus["post_patch_sample_summary"]["closed_trade_count"] == 41
    assert "approval_template_focus_error" not in payload["runtime_signoff_summary"]


def test_apply_runtime_mitigation_summary_surfaces_primary_action():
    current = {
        "runtime_signoff_summary": {
            "approval_template_focus": {
                "mitigation_execution_plan": {
                    "primary_focus_code": "confirm_entry_tighten",
                    "primary_focus_label": "confirm 진입 타이밍 축소",
                    "secondary_focus_code": "non_confirm_fail_fast",
                    "secondary_focus_label": "non-confirm fail-fast",
                    "secondary_status": "deferred_by_experiment_sequence",
                },
                "mitigation_review_summary": {
                    "primary_action_code": "range_entry_timing_review",
                    "primary_action_status": "candidate_review_pending",
                    "primary_action_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_entry_timing_split_review",
                    "actionable_now_count": 0,
                    "candidate_pending_count": 1,
                    "deferred_count": 1,
                    "research_only_count": 1,
                    "items": [
                        {
                            "code": "range_entry_timing_review",
                            "status": "candidate_review_pending",
                            "current_constraint": "waiting_for_actionable_entry_timing_target",
                        }
                    ],
                }
            }
        }
    }

    payload = stage_monitor_tick._apply_runtime_mitigation_summary(current)

    summary = payload["runtime_mitigation_summary"]
    assert summary["available"] is True
    assert summary["primary_action_code"] == "range_entry_timing_review"
    assert summary["primary_action_status"] == "candidate_review_pending"
    assert summary["primary_action_constraint"] == "waiting_for_actionable_entry_timing_target"
    assert summary["primary_focus_label"] == "confirm 진입 타이밍 축소"
    assert summary["secondary_focus_label"] == "non-confirm fail-fast"
    assert summary["secondary_status"] == "deferred_by_experiment_sequence"


def test_apply_runtime_preflight_summary_runs_for_conditional_micro_live(monkeypatch):
    args = stage_monitor_tick.argparse.Namespace(
        base_url="http://127.0.0.1:8000",
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=30,
    )
    monkeypatch.setattr(
        stage_monitor_tick,
        "_run_micro_live_preflight",
        lambda _args: {
            "overall_status": "READY_FOR_MICRO_LIVE",
            "summary_line": "All preflight checks passed; MICRO_LIVE can proceed to final operator sign-off.",
            "checks": [{"name": "health_ready", "status": "PASS", "message": "ok"}],
        },
    )
    current = {
        "runtime_effective_action": "conditional_micro_live_signoff",
        "post_patch_closed_trade_count": 50,
    }

    payload = stage_monitor_tick._apply_runtime_preflight_summary(current, args)

    summary = payload["runtime_preflight_summary"]
    assert summary["status"] == "READY_FOR_MICRO_LIVE"
    assert summary["effective_action"] == "conditional_micro_live_signoff"
    assert summary["failed_checks"] == []


def test_apply_runtime_preflight_summary_invalidates_cache_when_surface_changes(monkeypatch):
    args = stage_monitor_tick.argparse.Namespace(
        base_url="http://127.0.0.1:8000",
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=30,
    )
    current = {
        "runtime_effective_action": "conditional_micro_live_signoff",
        "runtime_allowed_reopen_scope": "MICRO_LIVE_ONLY",
        "post_patch_closed_trade_count": 50,
        "dashboard_approval_strip": {"approve_value": "approval usable"},
        "validation_approval_strip": {"approve_value": "manual review first"},
        "checklist_approval_strip": {"approve_value": "manual review first"},
    }
    previous = {
        "runtime_preflight_summary": {
            "status": "NOT_READY",
            "command": (
                f"{stage_monitor_tick.sys.executable} scripts/run_micro_live_preflight.py "
                "--base-url http://127.0.0.1:8000 --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --no-write-report"
            ),
            "effective_action": "conditional_micro_live_signoff",
            "post_patch_closed_trade_count": 50,
            "fingerprint": "stale-fingerprint",
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }
    }

    monkeypatch.setattr(
        stage_monitor_tick,
        "_run_micro_live_preflight",
        lambda _args: {
            "overall_status": "READY_FOR_MICRO_LIVE",
            "summary_line": "All preflight checks passed; MICRO_LIVE can proceed to final operator sign-off.",
            "checks": [{"name": "health_ready", "status": "PASS", "message": "ok"}],
        },
    )

    payload = stage_monitor_tick._apply_runtime_preflight_summary(current, args, previous=previous)

    summary = payload["runtime_preflight_summary"]
    assert summary["status"] == "READY_FOR_MICRO_LIVE"
    assert summary.get("cache_reused") is not True
    assert summary["fingerprint"] == stage_monitor_tick._runtime_preflight_fingerprint(current)


def test_apply_runtime_preflight_summary_is_not_applicable_when_runtime_action_is_hold():
    args = stage_monitor_tick.argparse.Namespace(
        base_url="http://127.0.0.1:8000",
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=30,
    )
    current = {
        "runtime_effective_action": "hold_runtime_reopen",
        "post_patch_closed_trade_count": 50,
    }

    payload = stage_monitor_tick._apply_runtime_preflight_summary(current, args)

    assert payload["runtime_preflight_summary"]["status"] == "not_applicable"


def test_apply_runtime_operator_signoff_summary_marks_manual_micro_live_ready():
    current = {
        "runtime_decision": {
            "effective_action": "conditional_micro_live_signoff",
            "allowed_reopen_scope": "MICRO_LIVE_ONLY",
        },
        "runtime_preflight_summary": {
            "status": "READY_FOR_MICRO_LIVE",
        },
        "runtime_reopen_gate_summary": {
            "micro_live": {"contract_scope": "limit_only"},
        },
        "runtime_signoff_summary": {
            "required_reviews": [{"code": "approval_template_review"}],
        },
    }

    args = stage_monitor_tick.argparse.Namespace(
        base_url="http://127.0.0.1:8000",
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=30,
    )

    payload = stage_monitor_tick._apply_runtime_operator_signoff_summary(current, args)

    summary = payload["runtime_operator_signoff_summary"]
    assert summary["status"] == "ready_for_manual_micro_live_signoff"
    assert summary["allowed_scope"] == "MICRO_LIVE_ONLY"
    assert summary["first_required_review_code"] == "approval_template_review"
    assert summary["intent_execution_mode"] == "MICRO_LIVE"
    assert summary["contract_scope"] == "limit_only"


def test_apply_runtime_actionable_live_candidate_summary_marks_recent_intent_outside_family() -> None:
    current = {
        "runtime_operator_signoff_summary": {
            "status": "ready_for_manual_micro_live_signoff",
            "allowed_scope": "MICRO_LIVE_ONLY",
        },
        "representative_candidates": {
            "accepted": None,
            "blocked": {
                "symbol": "ARBUSDC",
                "strategy_family": "legacy_zone_plan",
                "status": "BLOCKED_SETUP",
            },
        },
        "recent_execution_intent_focus": {
            "symbol": "BTCUSDC",
            "strategy_family": "sweep_reversal",
            "allowed_execution_mode": "PAPER",
            "approval_state": "APPROVED_AUTO",
            "decision_reason_code": "submit_ready",
        },
        "recent_contract_matching_intent_summary": {
            "matching_intent_count": 0,
        },
        "runtime_live_contract_history_summary": {
            "matching_intent_count_total": 2,
            "matching_intent_count_30d": 0,
            "symbol_counts_summary": "BTCUSDC=2/0",
        },
        "paper_lineage_watch_summary": {
            "allowed_symbol_family_visibility": {
                "BTCUSDC": ["legacy_zone_plan", "sweep_reversal"],
            },
            "allowed_symbol_family_visibility_line": "BTCUSDC=legacy_zone_plan,sweep_reversal",
            "allowed_symbol_regime_visibility": {
                "BTCUSDC": ["range"],
            },
            "allowed_symbol_regime_visibility_line": "BTCUSDC=range",
        },
    }

    payload = stage_monitor_tick._apply_runtime_actionable_live_candidate_summary(current)

    summary = payload["runtime_actionable_live_candidate_summary"]
    assert summary["status"] == "recent_paper_intent_requires_micro_live_promotion"
    assert summary["reason_code"] == "paper_intent_requires_micro_live_promotion"
    assert summary["candidate_symbol"] == "ARBUSDC"
    assert summary["candidate_family"] == "legacy_zone_plan"
    assert summary["recent_intent_symbol"] == "BTCUSDC"
    assert summary["recent_intent_family"] == "sweep_reversal"
    assert summary["next_trigger"] == "operator_creates_micro_live_intent_for_allowed_candidate"
    assert summary["recent_contract_match_count"] == 0
    assert summary["historical_contract_match_count"] == 2
    assert summary["historical_contract_match_count_30d"] == 0
    assert "no recent operator intents matched the MICRO_LIVE contract" in summary["summary"]
    assert "historical contract intent counts BTCUSDC=2/0" in summary["summary"]
    assert "current watch visibility BTCUSDC=legacy_zone_plan,sweep_reversal" in summary["summary"]
    assert "current watch regime BTCUSDC=range" in summary["summary"]
    assert "is approved but was created by the PAPER drill" in summary["summary"]


def test_apply_runtime_actionable_live_candidate_summary_prefers_recent_contract_match() -> None:
    current = {
        "runtime_operator_signoff_summary": {
            "status": "ready_for_manual_micro_live_signoff",
            "allowed_scope": "MICRO_LIVE_ONLY",
        },
        "representative_candidates": {
            "accepted": None,
            "blocked": {
                "symbol": "ARBUSDC",
                "strategy_family": "legacy_zone_plan",
                "status": "BLOCKED_SETUP",
            },
        },
        "recent_execution_intent_focus": {
            "symbol": "BTCUSDC",
            "strategy_family": "sweep_reversal",
            "entry_type": "stop_market",
            "allowed_execution_mode": "PAPER",
            "approval_state": "APPROVED_AUTO",
            "decision_reason_code": "submit_ready",
        },
        "recent_contract_matching_intent_summary": {
            "matching_intent_count": 3,
            "latest_symbol": "BTCUSDC",
            "latest_family": "sweep_reversal",
            "latest_execution_mode": "PAPER",
            "latest_allowed_execution_mode": "PAPER",
            "latest_approval_state": "APPROVED_AUTO",
            "latest_reason_code": "submit_ready",
            "latest_entry_type": "limit",
            "latest_entry_model": "LIMIT",
        },
    }

    payload = stage_monitor_tick._apply_runtime_actionable_live_candidate_summary(current)

    summary = payload["runtime_actionable_live_candidate_summary"]
    assert summary["status"] == "recent_paper_intent_requires_micro_live_promotion"
    assert summary["reason_code"] == "paper_intent_requires_micro_live_promotion"
    assert summary["recent_intent_symbol"] == "BTCUSDC"
    assert summary["recent_intent_family"] == "sweep_reversal"
    assert summary["recent_intent_entry_type"] == "LIMIT"
    assert summary["recent_contract_match_count"] == 3
    assert summary["next_trigger"] == "operator_creates_micro_live_intent_for_allowed_candidate"
    assert "BTCUSDC/sweep_reversal/PAPER" in summary["summary"]
    assert "STOP_MARKET" not in summary["summary"]


def test_apply_runtime_actionable_live_candidate_summary_marks_recent_contract_match_not_submit_ready() -> None:
    current = {
        "runtime_operator_signoff_summary": {
            "status": "ready_for_manual_micro_live_signoff",
            "allowed_scope": "MICRO_LIVE_ONLY",
        },
        "representative_candidates": {
            "accepted": None,
            "blocked": {
                "symbol": "ARBUSDC",
                "strategy_family": "legacy_zone_plan",
                "status": "BLOCKED_SETUP",
            },
        },
        "recent_execution_intent_focus": {
            "symbol": "BTCUSDC",
            "strategy_family": "sweep_reversal",
            "entry_type": "stop_market",
            "allowed_execution_mode": "PAPER",
            "approval_state": "APPROVED_AUTO",
            "decision_reason_code": "submit_ready",
        },
        "recent_contract_matching_intent_summary": {
            "matching_intent_count": 44,
            "latest_symbol": "TIAUSDC",
            "latest_family": "sweep_reversal",
            "latest_direction": "SHORT",
            "latest_execution_mode": "PAPER",
            "latest_allowed_execution_mode": "PAPER",
            "latest_approval_state": "APPROVED_AUTO",
            "latest_reason_code": "paper lineage override bypassed thesis duplicate block for eligible A-grade PAPER sampling.",
            "latest_entry_type": "limit",
            "latest_entry_model": "LIMIT",
            "latest_submit_ready_symbol": "ETHUSDC",
            "latest_submit_ready_family": "sweep_reversal",
            "latest_submit_ready_direction": "LONG",
            "latest_submit_ready_execution_mode": "PAPER",
            "latest_submit_ready_allowed_execution_mode": "PAPER",
            "latest_submit_ready_approval_state": "APPROVED_AUTO",
            "latest_submit_ready_reason_code": "submit_ready",
            "latest_submit_ready_entry_type": "limit",
            "latest_submit_ready_entry_model": "LIMIT",
            "latest_submit_ready_created_at": "2026-04-15 14:48:09.972149",
        },
    }

    payload = stage_monitor_tick._apply_runtime_actionable_live_candidate_summary(current)

    summary = payload["runtime_actionable_live_candidate_summary"]
    assert summary["status"] == "recent_paper_intent_requires_micro_live_promotion"
    assert summary["reason_code"] == "paper_intent_requires_micro_live_promotion"
    assert summary["recent_intent_symbol"] == "ETHUSDC"
    assert summary["recent_intent_family"] == "sweep_reversal"
    assert summary["recent_intent_entry_type"] == "LIMIT"
    assert summary["recent_intent_direction"] == "LONG"
    assert summary["recent_submit_ready_symbol"] == "ETHUSDC"
    assert summary["recent_submit_ready_family"] == "sweep_reversal"
    assert summary["recent_submit_ready_direction"] == "LONG"
    assert summary["recent_submit_ready_created_at"] == "2026-04-15 14:48:09.972149"
    assert summary["recent_contract_match_count"] == 44
    assert summary["next_trigger"] == "operator_creates_micro_live_intent_for_allowed_candidate"
    assert "latest surfaced intent ETHUSDC/sweep_reversal/PAPER is approved but was created by the PAPER drill" in summary["summary"]
    assert "last submit_ready limit candidate was ETHUSDC/sweep_reversal/LONG at 2026-04-15 14:48:09.972149" in summary["summary"]
    assert "nearest surfaced candidate ARBUSDC/legacy_zone_plan remains blocked" in summary["summary"]


def test_apply_runtime_mitigation_packet_waits_when_not_actionable(monkeypatch):
    args = stage_monitor_tick.argparse.Namespace(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=30,
        dry_run=True,
    )
    monkeypatch.setattr(
        stage_monitor_tick,
        "_load_latest_lineage_watch_summary",
        lambda **kwargs: {"available": False, "fresh": False},
    )
    current = {
        "runtime_mitigation_summary": {
            "available": True,
            "primary_action_code": "range_entry_timing_review",
            "primary_action_status": "candidate_review_pending",
            "primary_action_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_entry_timing_split_review",
            "primary_focus_label": "confirm 진입 타이밍 축소",
            "primary_action_constraint": "waiting_for_actionable_entry_timing_target",
        }
    }

    payload = stage_monitor_tick._apply_runtime_mitigation_packet(current, args)

    assert payload["runtime_mitigation_packet_result"]["status"] == "waiting_for_actionable_mitigation"
    assert payload["runtime_mitigation_packet_result"]["focus_label"] == "confirm 진입 타이밍 축소"
    assert payload["runtime_mitigation_packet_result"]["wait_constraint"] == "waiting_for_actionable_entry_timing_target"


def test_apply_runtime_mitigation_packet_bridges_fresh_watcher_candidate(monkeypatch):
    args = stage_monitor_tick.argparse.Namespace(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=30,
        dry_run=True,
    )
    monkeypatch.setattr(
        stage_monitor_tick,
        "_load_latest_lineage_watch_summary",
        lambda **kwargs: {
            "available": True,
            "fresh": True,
            "tick_status": "found_eligible_candidate",
            "candidate_symbol": "WIFUSDC",
            "candidate_family": "sweep_reversal",
            "candidate_status": "APPROVED_AUTO",
        },
    )
    monkeypatch.setattr(stage_monitor_tick, "_find_fresh_runtime_mitigation_packet", lambda **kwargs: None)
    current = {
        "runtime_mitigation_summary": {
            "available": True,
            "primary_action_code": "range_entry_timing_review",
            "primary_action_status": "candidate_review_pending",
            "primary_action_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_entry_timing_split_review",
            "primary_focus_label": "confirm 진입 타이밍 축소",
            "primary_action_constraint": "waiting_for_actionable_entry_timing_target",
        }
    }

    payload = stage_monitor_tick._apply_runtime_mitigation_packet(current, args)

    assert payload["runtime_mitigation_packet_result"]["status"] == "actionable_pending_dry_run"
    assert payload["runtime_mitigation_packet_result"]["target_symbol"] == "WIFUSDC"
    assert "--symbol WIFUSDC" in payload["runtime_mitigation_packet_result"]["command"]


def test_apply_runtime_mitigation_packet_downgrades_command_failures_to_error(monkeypatch):
    args = stage_monitor_tick.argparse.Namespace(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=30,
        dry_run=False,
    )
    monkeypatch.setattr(stage_monitor_tick, "_load_latest_lineage_watch_summary", lambda **kwargs: {"available": False, "fresh": False})
    monkeypatch.setattr(stage_monitor_tick, "_find_fresh_runtime_mitigation_packet", lambda **kwargs: None)
    monkeypatch.setattr(
        stage_monitor_tick,
        "_run_runtime_mitigation_packet_command",
        lambda command: (_ for _ in ()).throw(RuntimeError("packet command failed")),
    )
    current = {
        "runtime_mitigation_summary": {
            "available": True,
            "primary_action_code": "range_entry_timing_review",
            "primary_action_status": "actionable_now",
            "primary_action_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_entry_timing_split_review",
            "primary_focus_label": "confirm 진입 타이밍 축소",
            "primary_action_constraint": "",
        }
    }

    payload = stage_monitor_tick._apply_runtime_mitigation_packet(current, args)

    assert payload["runtime_mitigation_packet_result"]["status"] == "ERROR"
    assert "packet command failed" in payload["runtime_mitigation_packet_result"]["summary"]


def test_apply_runtime_mitigation_wait_summary_surfaces_no_candidate_visible(monkeypatch):
    monkeypatch.setattr(
        stage_monitor_tick,
        "_runtime_mitigation_session_context",
        lambda **kwargs: {
            "current_session": "london",
            "session_active": True,
            "allowed_sessions": ["london", "new_york"],
        },
    )
    monkeypatch.setattr(
        stage_monitor_tick,
        "_load_latest_lineage_watch_summary",
        lambda **kwargs: {"available": False, "fresh": False},
    )
    current = {
        "runtime_mitigation_summary": {
            "available": True,
            "primary_focus_label": "confirm 진입 타이밍 축소",
            "primary_action_constraint": "waiting_for_actionable_entry_timing_target",
            "primary_action_status": "candidate_review_pending",
        },
        "runtime_mitigation_packet_result": {
            "wait_constraint": "waiting_for_actionable_entry_timing_target",
        },
        "entry_timing_review_target": None,
        "accepted_candidate_focus": None,
        "blocked_candidate_focus": None,
    }

    payload = stage_monitor_tick._apply_runtime_mitigation_wait_summary(current)

    summary = payload["runtime_mitigation_wait_summary"]
    assert summary["status"] == "no_lineage_candidate_visible"
    assert summary["focus_label"] == "confirm 진입 타이밍 축소"
    assert summary["next_trigger"] == "actionable_entry_timing_target_appears"


def test_apply_runtime_mitigation_wait_summary_surfaces_outside_allowed_session(monkeypatch):
    monkeypatch.setattr(
        stage_monitor_tick,
        "_runtime_mitigation_session_context",
        lambda **kwargs: {
            "current_session": "inactive",
            "session_active": False,
            "allowed_sessions": ["london", "new_york"],
        },
    )
    monkeypatch.setattr(
        stage_monitor_tick,
        "_load_latest_lineage_watch_summary",
        lambda **kwargs: {"available": False, "fresh": False},
    )
    current = {
        "runtime_mitigation_summary": {
            "available": True,
            "primary_focus_label": "confirm 진입 타이밍 축소",
            "primary_action_constraint": "waiting_for_actionable_entry_timing_target",
            "primary_action_status": "candidate_review_pending",
        },
        "runtime_mitigation_packet_result": {
            "wait_constraint": "waiting_for_actionable_entry_timing_target",
        },
        "lineage_sample_summary": {"families": ["sweep_reversal", "trend_continuation"]},
        "entry_timing_review_target": None,
        "accepted_candidate_focus": None,
        "blocked_candidate_focus": None,
    }

    payload = stage_monitor_tick._apply_runtime_mitigation_wait_summary(current)

    summary = payload["runtime_mitigation_wait_summary"]
    assert summary["status"] == "outside_allowed_rollout_session"
    assert summary["current_session"] == "inactive"
    assert summary["allowed_sessions"] == ["london", "new_york"]
    assert summary["next_trigger"] == "allowed_rollout_session_opens"


def test_apply_runtime_mitigation_wait_summary_prefers_fresh_watcher_candidate(monkeypatch):
    monkeypatch.setattr(
        stage_monitor_tick,
        "_runtime_mitigation_session_context",
        lambda **kwargs: {
            "current_session": "london",
            "session_active": True,
            "allowed_sessions": ["london", "new_york"],
        },
    )
    monkeypatch.setattr(
        stage_monitor_tick,
        "_load_latest_lineage_watch_summary",
        lambda **kwargs: {
            "available": True,
            "fresh": True,
            "tick_status": "found_eligible_candidate",
            "summary_line": "Eligible PAPER lineage candidate found on attempt 1.",
            "candidate_symbol": "WIFUSDC",
            "candidate_family": "sweep_reversal",
            "candidate_status": "APPROVED_AUTO",
        },
    )
    current = {
        "runtime_mitigation_summary": {
            "available": True,
            "primary_focus_label": "confirm 진입 타이밍 축소",
            "primary_action_constraint": "waiting_for_actionable_entry_timing_target",
            "primary_action_status": "candidate_review_pending",
        },
        "runtime_mitigation_packet_result": {
            "wait_constraint": "waiting_for_actionable_entry_timing_target",
        },
        "lineage_sample_summary": {"families": ["sweep_reversal", "trend_continuation"]},
        "entry_timing_review_target": None,
        "accepted_candidate_focus": None,
        "blocked_candidate_focus": None,
    }

    payload = stage_monitor_tick._apply_runtime_mitigation_wait_summary(current)

    summary = payload["runtime_mitigation_wait_summary"]
    assert summary["status"] == "watcher_found_candidate_pending_review_target"
    assert summary["candidate_symbol"] == "WIFUSDC"
    assert summary["candidate_family"] == "sweep_reversal"
    assert summary["candidate_status"] == "APPROVED_AUTO"
    assert summary["watch_tick_status"] == "found_eligible_candidate"


def test_apply_runtime_mitigation_wait_summary_surfaces_paper_family_guard(monkeypatch):
    monkeypatch.setattr(
        stage_monitor_tick,
        "_runtime_mitigation_session_context",
        lambda **kwargs: {
            "current_session": "london",
            "session_active": True,
            "allowed_sessions": ["london", "new_york"],
        },
    )
    monkeypatch.setattr(
        stage_monitor_tick,
        "_load_latest_lineage_watch_summary",
        lambda **kwargs: {
            "available": True,
            "fresh": True,
            "tick_status": "no_eligible_candidate",
            "summary_line": "No eligible PAPER lineage candidate found after 1 attempt(s).",
            "family_guard_active": True,
            "family_guard_families": ["sweep_reversal"],
            "family_guard_family": "sweep_reversal",
            "family_guard_reason_code": "recent_family_loss_cooldown",
            "family_guard_summary_line": "sweep_reversal:entries=0,losses=2,active=True",
        },
    )
    current = {
        "runtime_mitigation_summary": {
            "available": True,
            "primary_focus_label": "confirm 진입 타이밍 축소",
            "primary_action_constraint": "waiting_for_actionable_entry_timing_target",
            "primary_action_status": "candidate_review_pending",
        },
        "runtime_mitigation_packet_result": {
            "wait_constraint": "waiting_for_actionable_entry_timing_target",
        },
        "lineage_sample_summary": {"families": ["sweep_reversal", "trend_continuation"]},
        "entry_timing_review_target": None,
        "accepted_candidate_focus": None,
        "blocked_candidate_focus": None,
    }

    payload = stage_monitor_tick._apply_runtime_mitigation_wait_summary(current)

    summary = payload["runtime_mitigation_wait_summary"]
    assert summary["status"] == "paper_family_guard_active"
    assert summary["next_trigger"] == "recent_family_loss_cooldown_clears"
    assert summary["candidate_family"] == "sweep_reversal"
    assert summary["candidate_status"] == "recent_family_loss_cooldown"
    assert summary["watch_guard_active"] is True
    assert payload["paper_lineage_watch_summary"]["family_guard_reason_code"] == "recent_family_loss_cooldown"


def test_apply_runtime_mitigation_wait_summary_marks_packet_ready_for_review(monkeypatch):
    monkeypatch.setattr(
        stage_monitor_tick,
        "_runtime_mitigation_session_context",
        lambda **kwargs: {
            "current_session": "london",
            "session_active": True,
            "allowed_sessions": ["london", "new_york"],
        },
    )
    monkeypatch.setattr(
        stage_monitor_tick,
        "_load_latest_lineage_watch_summary",
        lambda **kwargs: {
            "available": True,
            "fresh": True,
            "tick_status": "found_eligible_candidate",
            "candidate_symbol": "FILUSDC",
            "candidate_family": "sweep_reversal",
            "candidate_status": "APPROVED_AUTO",
        },
    )
    current = {
        "runtime_mitigation_summary": {
            "available": True,
            "primary_focus_label": "confirm 진입 타이밍 축소",
            "primary_action_constraint": "waiting_for_actionable_entry_timing_target",
            "primary_action_status": "candidate_review_pending",
        },
        "runtime_mitigation_packet_result": {
            "status": "READY",
            "target_symbol": "FILUSDC",
            "packet_id": "review_followup:abc123",
        },
        "lineage_sample_summary": {"families": ["sweep_reversal", "trend_continuation"]},
        "entry_timing_review_target": None,
        "accepted_candidate_focus": None,
        "blocked_candidate_focus": None,
    }

    payload = stage_monitor_tick._apply_runtime_mitigation_wait_summary(current)

    summary = payload["runtime_mitigation_wait_summary"]
    assert summary["status"] == "packet_ready_for_review"
    assert summary["next_trigger"] == "operator_reviews_ready_packet"
    assert summary["candidate_symbol"] == "FILUSDC"
    assert summary["candidate_status"] == "READY"


def test_apply_runtime_mitigation_wait_summary_projects_trend_and_exit_monitor_watch_fields(monkeypatch):
    monkeypatch.setattr(
        stage_monitor_tick,
        "_runtime_mitigation_session_context",
        lambda **kwargs: {
            "current_session": "london",
            "session_active": True,
            "allowed_sessions": ["london", "new_york"],
        },
    )
    monkeypatch.setattr(
        stage_monitor_tick,
        "_load_latest_lineage_watch_summary",
        lambda **kwargs: {
            "available": True,
            "fresh": True,
            "tick_status": "no_eligible_candidate",
            "trend_proof_candidate_summary": {
                "availability_state": "trend_limit_visible_but_not_runtime_eligible",
                "scanner_candidate_count": 2,
                "scanner_limit_candidate_count": 1,
                "runtime_eligible_candidate_count": 0,
            },
            "paper_exit_monitor_summary": {
                "stale_cleanup_events": 2,
                "closed_events": 3,
            },
        },
    )

    payload = stage_monitor_tick._apply_runtime_mitigation_wait_summary(
        {
            "runtime_mitigation_summary": {
                "available": True,
                "primary_action_status": "candidate_review_pending",
            },
            "runtime_mitigation_packet_result": {},
            "lineage_sample_summary": {"families": ["trend_continuation"]},
        }
    )

    watch = payload["paper_lineage_watch_summary"]
    assert watch["trend_proof_candidate_summary"]["scanner_candidate_count"] == 2
    assert watch["paper_exit_monitor_summary"]["stale_cleanup_events"] == 2


def test_apply_runtime_self_heal_summary_tracks_exit_cleanup_and_stale_unblocks() -> None:
    payload = stage_monitor_tick._apply_runtime_self_heal_summary(
        {
            "paper_lineage_watch_summary": {
                "paper_exit_monitor_summary": {
                    "stale_cleanup_events": 2,
                }
            },
            "recent_contract_matching_intent_summary": {
                "latest_self_heal_summary": {
                    "stale_paper_reentry_block_ignored": True,
                    "stale_paper_duplicate_intents_ignored_count": 1,
                },
                "latest_submit_ready_self_heal_summary": {
                    "applied": True,
                },
            },
        }
    )

    summary = payload["runtime_self_heal_summary"]
    assert summary["active"] is True
    assert summary["stale_cleanup_events"] == 2
    assert summary["latest_reentry_block_ignored"] is True
    assert summary["latest_duplicate_intents_ignored"] == 1
    assert summary["latest_submit_ready_self_heal_applied"] is True


def test_apply_runtime_live_contract_history_summary_filters_non_contract_entry_models(monkeypatch):
    now = datetime.now(timezone.utc)

    class _Intent:
        def __init__(
            self,
            *,
            symbol: str,
            family: str,
            created_at: datetime,
            entry_type: str,
            entry_model: str,
            direction: str,
        ):
            self.symbol = symbol
            self.strategy_family = family
            self.created_at = created_at
            self.payload = {
                "executable_plan": {
                    "entry_type": entry_type,
                    "entry_model": entry_model,
                    "direction": direction,
                }
            }

    intents = [
        _Intent(
            symbol="BTCUSDC",
            family="sweep_reversal",
            created_at=now - timedelta(days=1),
            entry_type="limit",
            entry_model="LIMIT",
            direction="LONG",
        ),
        _Intent(
            symbol="BTCUSDC",
            family="sweep_reversal",
            created_at=now - timedelta(days=1),
            entry_type="stop_market",
            entry_model="CONFIRM",
            direction="LONG",
        ),
        _Intent(
            symbol="BTCUSDC",
            family="sweep_reversal",
            created_at=now - timedelta(days=1),
            entry_type="limit",
            entry_model="LIMIT",
            direction="SHORT",
        ),
    ]

    class _Query:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return intents

    class _Session:
        def query(self, *args, **kwargs):
            return _Query()

        def close(self):
            return None

    class _Settings:
        auto_trading_micro_live_allowed_symbols = "BTCUSDC"
        auto_trading_micro_live_allowed_families = "sweep_reversal"
        auto_trading_micro_live_allowed_entry_models = "LIMIT"
        auto_trading_micro_live_direction_contract = "BTCUSDC:LONG"

    monkeypatch.setattr(stage_monitor_tick, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(stage_monitor_tick, "get_settings", lambda: _Settings())

    payload = stage_monitor_tick._apply_runtime_live_contract_history_summary(
        {
            "runtime_operator_signoff_summary": {
                "allowed_scope": "MICRO_LIVE_ONLY",
            }
        }
    )

    summary = payload["runtime_live_contract_history_summary"]
    assert summary["matching_intent_count_total"] == 1
    assert summary["matching_intent_count_30d"] == 1
    assert summary["symbol_counts_total"]["BTCUSDC"] == 1
    assert summary["symbol_counts_30d"]["BTCUSDC"] == 1
    assert summary["symbol_counts_summary"] == "BTCUSDC=1/1"


def test_apply_runtime_mitigation_packet_reuses_fresh_ready_packet(monkeypatch):
    args = stage_monitor_tick.argparse.Namespace(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=30,
        dry_run=False,
    )
    current = {
        "runtime_mitigation_summary": {
            "available": True,
            "primary_action_code": "range_entry_timing_review",
            "primary_action_status": "actionable_now",
            "primary_action_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_entry_timing_split_review",
        },
        "entry_timing_review_target": {
            "symbol": "WIFUSDC",
            "preferred_variant": "early_limit",
        },
    }

    monkeypatch.setattr(
        stage_monitor_tick,
        "_find_fresh_runtime_mitigation_packet",
        lambda **_: {
            "packet_id": "review_followup:existing",
            "target_contract": {"symbol": "WIFUSDC", "preferred_variant": "early_limit"},
        },
    )

    payload = stage_monitor_tick._apply_runtime_mitigation_packet(current, args)

    result = payload["runtime_mitigation_packet_result"]
    assert result["status"] == "fresh_packet_ready_exists"
    assert result["packet_id"] == "review_followup:existing"


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
