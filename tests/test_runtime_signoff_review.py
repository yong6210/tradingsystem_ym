from __future__ import annotations

import http.client
import importlib.util
import json
from pathlib import Path


ROOT_DIR = Path("/Users/yumin/Documents/trading")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime_signoff_review = _load_module(
    "runtime_signoff_review_test_module",
    ROOT_DIR / "scripts/run_runtime_signoff_review.py",
)


def test_build_payload_surfaces_primary_required_review():
    stage = {
        "runtime_reopen_status": {
            "status": "ready_to_reopen_runtime",
            "ready": True,
        },
        "runtime_signoff_summary": {
            "status": "manual_signoff_required",
            "operator_recommendation": "hold_runtime_reopen",
            "operator_recommendation_reason": "replay-derived worst scenario still fails",
            "required_reviews": [
                {
                    "code": "approval_template_review",
                    "summary": "approval template warning remains",
                    "current_value": "topline_code=true_threshold_winner_with_replay_fail_worst_scenario",
                    "clear_when": "validation topline REVIEW clears",
                    "worst_scenario": "latency_plus_1_bar",
                    "worst_scenario_status": "FAIL",
                    "worst_scenario_reason": "catastrophic_drawdown:replay_output",
                }
            ],
            "advisory_reviews": [
                {
                    "code": "symbol_edge_thin",
                    "summary": "BTCUSDC symbol proof is still thin",
                }
            ],
        },
        "lineage_sample_summary": {
            "closed_trade_count": 183,
            "proof_goal_closed_trades": 100,
        },
        "risk_gate_summary": {
            "status": "PASS",
            "risk_state": "OPEN",
        },
        "validation_approval_strip": {
            "approve_value": "manual review first",
            "align_value": "playbook_drift",
            "act_value": "continue_candidate_review_under_portfolio_caps",
        },
    }

    payload = runtime_signoff_review._build_payload(
        stage,
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=30,
    )

    assert payload["status"] == "MANUAL_SIGNOFF_REQUIRED"
    assert payload["operator_recommendation"] == "hold_runtime_reopen"
    assert payload["operator_recommendation_reason"].startswith("replay-derived worst scenario still fails")
    assert payload["primary_required_review"]["code"] == "approval_template_review"
    assert payload["primary_required_review"]["worst_scenario"] == "latency_plus_1_bar"
    assert payload["primary_required_review"]["worst_scenario_status"] == "FAIL"
    assert payload["lineage_sample"]["closed_trade_count"] == 183
    assert payload["runtime_signoff_review_command"].endswith(
        "--symbol BTCUSDC --universe usdc_perp_top30 --days 30"
    )


def test_request_json_with_retry_wraps_remote_disconnected_as_runtime_error():
    attempts = {"count": 0}

    def _raise_remote_disconnect(*args, **kwargs):
        attempts["count"] += 1
        raise http.client.RemoteDisconnected("Remote end closed connection without response")

    try:
        runtime_signoff_review._request_json_with_retry(
            "http://127.0.0.1:8000",
            "/validation/stress-replay-assessment",
            query={"symbol": "LINEAGE_GLOBAL"},
            request_json_fn=_raise_remote_disconnect,
            attempts=2,
            sleep_seconds=0.0,
        )
    except RuntimeError as exc:
        assert "Remote end closed connection without response" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert attempts["count"] == 2


def test_build_payload_marks_ready_when_no_required_reviews():
    stage = {
        "runtime_reopen_status": {
            "status": "ready_to_reopen_runtime",
            "ready": True,
        },
        "runtime_signoff_summary": {
            "status": "ready_for_operator_signoff",
            "operator_recommendation": "proceed_to_operator_signoff",
            "operator_recommendation_reason": "runtime is reopen-ready and no required operator review items remain",
            "required_reviews": [],
            "advisory_reviews": [],
        },
        "lineage_sample_summary": {
            "closed_trade_count": 183,
            "proof_goal_closed_trades": 100,
        },
        "risk_gate_summary": {
            "status": "PASS",
            "risk_state": "OPEN",
        },
        "validation_approval_strip": {
            "approve_value": "approval usable",
            "align_value": "aligned",
            "act_value": "continue_candidate_review_under_portfolio_caps",
        },
    }

    payload = runtime_signoff_review._build_payload(
        stage,
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=30,
    )

    assert payload["status"] == "READY_FOR_OPERATOR_SIGNOFF"
    assert payload["operator_recommendation"] == "proceed_to_operator_signoff"
    assert payload["primary_required_review"] is None
    assert payload["required_reviews"] == []


def test_build_payload_treats_pending_bundle_window_as_signoff_eligible():
    stage = {
        "runtime_reopen_status": {
            "status": "review_window_open_pending_bundle",
            "ready": False,
        },
        "runtime_signoff_summary": {
            "status": "manual_signoff_required",
            "operator_recommendation": "hold_runtime_reopen",
            "operator_recommendation_reason": "replay-derived worst scenario still fails",
            "required_reviews": [
                {
                    "code": "approval_template_review",
                    "summary": "approval template warning remains",
                    "current_value": "topline_code=true_threshold_winner_with_replay_fail_worst_scenario",
                    "clear_when": "validation topline REVIEW clears",
                    "worst_scenario": "latency_plus_1_bar",
                    "worst_scenario_status": "FAIL",
                    "worst_scenario_reason": "catastrophic_drawdown:replay_output",
                }
            ],
            "advisory_reviews": [],
        },
        "lineage_sample_summary": {
            "closed_trade_count": 232,
            "proof_goal_closed_trades": 100,
        },
        "risk_gate_summary": {
            "status": "PASS",
            "risk_state": "OPEN",
        },
        "validation_approval_strip": {
            "approve_value": "manual review first",
            "align_value": "playbook_drift",
            "act_value": "continue_candidate_review_under_portfolio_caps",
        },
    }

    payload = runtime_signoff_review._build_payload(stage, symbol="BTCUSDC", universe="usdc_perp_top30", days=30)

    assert payload["status"] == "MANUAL_SIGNOFF_REQUIRED"


def test_build_runtime_decision_marks_red_hold_for_large_replay_drawdown():
    decision = runtime_signoff_review._build_runtime_decision(
        runtime_ready=True,
        required_reviews=[
            {
                "code": "approval_template_review",
                "worst_scenario_status": "FAIL",
            }
        ],
        approval_template_focus={
            "replay_max_drawdown_r": 10.1003,
            "replay_p5_r": -1.05,
            "downside_profile": {
                "stop_loss_share": 0.5341,
                "worst_loss_streak": 9,
            },
        },
    )

    assert decision["band"] == "RED_HOLD"
    assert decision["effective_action"] == "hold_runtime_reopen"
    assert decision["allowed_reopen_scope"] == "none"
    assert {item["code"] for item in decision["breached_thresholds"]} == {
        "max_drawdown_red",
        "p5_red",
        "stop_loss_share_red",
        "loss_streak_red",
    }


def test_build_runtime_decision_uses_post_patch_override_for_conditional_micro_live():
    decision = runtime_signoff_review._build_runtime_decision(
        runtime_ready=True,
        required_reviews=[
            {
                "code": "approval_template_review",
                "worst_scenario_status": "FAIL",
            }
        ],
        approval_template_focus={
            "replay_max_drawdown_r": 10.1003,
            "replay_p5_r": -1.05,
            "downside_profile": {
                "stop_loss_share": 0.5341,
                "worst_loss_streak": 9,
            },
            "post_patch_sample_summary": {
                "closed_trade_count": 50,
                "ready_for_replay_refresh": True,
                "replay_max_drawdown_r": 3.25,
                "replay_p5_r": -1.05,
                "stop_loss_share": 0.3,
                "worst_loss_streak": 4,
            },
        },
    )

    assert decision["band"] == "AMBER_CONDITIONAL"
    assert decision["effective_action"] == "conditional_micro_live_signoff"
    assert decision["allowed_reopen_scope"] == "MICRO_LIVE_ONLY"
    assert decision["post_patch_override_active"] is True


def test_build_runtime_decision_uses_post_patch_override_for_conditional_full_live():
    decision = runtime_signoff_review._build_runtime_decision(
        runtime_ready=True,
        required_reviews=[
            {
                "code": "approval_template_review",
                "worst_scenario_status": "FAIL",
            }
        ],
        approval_template_focus={
            "replay_max_drawdown_r": 10.1003,
            "replay_p5_r": -1.05,
            "downside_profile": {
                "stop_loss_share": 0.5341,
                "worst_loss_streak": 9,
            },
            "post_patch_sample_summary": {
                "closed_trade_count": 80,
                "ready_for_replay_refresh": True,
                "replay_max_drawdown_r": 4.5,
                "replay_p5_r": -0.95,
                "stop_loss_share": 0.3,
                "worst_loss_streak": 4,
            },
        },
    )

    assert decision["band"] == "AMBER_CONDITIONAL"
    assert decision["effective_action"] == "conditional_full_live_signoff"
    assert decision["allowed_reopen_scope"] == "MICRO_LIVE_OR_LIVE"
    assert decision["post_patch_override_active"] is True


def test_apply_runtime_decision_syncs_operator_recommendation_from_decision():
    payload = runtime_signoff_review._apply_runtime_decision(
        {
            "runtime_reopen_status": {"ready": True},
            "required_reviews": [{"code": "approval_template_review", "worst_scenario_status": "FAIL"}],
            "approval_template_focus": {
                "replay_max_drawdown_r": 10.1003,
                "replay_p5_r": -1.05,
                "downside_profile": {"stop_loss_share": 0.5341, "worst_loss_streak": 9},
                "post_patch_sample_summary": {
                    "closed_trade_count": 50,
                    "ready_for_replay_refresh": True,
                    "replay_max_drawdown_r": 3.25,
                    "replay_p5_r": -1.05,
                    "stop_loss_share": 0.3,
                    "worst_loss_streak": 4,
                },
            },
            "operator_recommendation": "hold_runtime_reopen",
        }
    )

    assert payload["runtime_decision"]["band"] == "AMBER_CONDITIONAL"


def test_build_runtime_decision_keeps_red_when_post_patch_sample_count_is_below_micro_live_min():
    decision = runtime_signoff_review._build_runtime_decision(
        runtime_ready=True,
        required_reviews=[
            {
                "code": "approval_template_review",
                "worst_scenario_status": "FAIL",
            }
        ],
        approval_template_focus={
            "replay_max_drawdown_r": 10.1003,
            "replay_p5_r": -1.05,
            "downside_profile": {
                "stop_loss_share": 0.5341,
                "worst_loss_streak": 9,
            },
            "post_patch_sample_summary": {
                "closed_trade_count": 41,
                "ready_for_replay_refresh": True,
                "replay_max_drawdown_r": 4.3114,
                "replay_p5_r": -1.05,
                "stop_loss_share": 0.3171,
                "worst_loss_streak": 4,
            },
        },
    )

    assert decision["band"] == "RED_HOLD"
    assert {item["code"] for item in decision["post_patch_breached_thresholds"]} == {"post_patch_sample_count_min"}


def test_build_runtime_decision_keeps_micro_live_only_when_full_live_thresholds_still_fail():
    decision = runtime_signoff_review._build_runtime_decision(
        runtime_ready=True,
        required_reviews=[
            {
                "code": "approval_template_review",
                "worst_scenario_status": "FAIL",
            }
        ],
        approval_template_focus={
            "replay_max_drawdown_r": 10.1003,
            "replay_p5_r": -1.05,
            "downside_profile": {
                "stop_loss_share": 0.5341,
                "worst_loss_streak": 9,
            },
            "post_patch_sample_summary": {
                "closed_trade_count": 80,
                "ready_for_replay_refresh": True,
                "replay_max_drawdown_r": 4.3114,
                "replay_p5_r": -1.05,
                "stop_loss_share": 0.3,
                "worst_loss_streak": 4,
            },
        },
    )

    assert decision["band"] == "AMBER_CONDITIONAL"
    assert decision["effective_action"] == "conditional_micro_live_signoff"
    assert decision["allowed_reopen_scope"] == "MICRO_LIVE_ONLY"


def test_apply_runtime_decision_attaches_reopen_gate_summary():
    payload = runtime_signoff_review._apply_runtime_decision(
        {
            "runtime_reopen_status": {"status": "ready_to_reopen_runtime", "ready": True},
            "required_reviews": [{"code": "approval_template_review", "worst_scenario_status": "FAIL"}],
            "approval_template_focus": {
                "replay_max_drawdown_r": 10.1003,
                "replay_p5_r": -1.05,
                "downside_profile": {"stop_loss_share": 0.5341, "worst_loss_streak": 9},
                "post_patch_sample_summary": {
                    "closed_trade_count": 50,
                    "ready_for_replay_refresh": True,
                    "replay_max_drawdown_r": 4.3114,
                    "replay_p5_r": -1.05,
                    "stop_loss_share": 0.3,
                    "worst_loss_streak": 4,
                },
            },
        }
    )

    gate = payload["runtime_reopen_gate_summary"]
    assert gate["active_scope"] == "MICRO_LIVE_ONLY"
    assert gate["micro_live"]["status"] == "ready"
    assert gate["full_live"]["status"] == "not_ready"
    assert {item["code"] for item in gate["full_live"]["breached_thresholds"]} == {
        "post_patch_full_live_sample_count_min",
        "post_patch_full_live_p5_red",
    }


def test_build_runtime_operator_signoff_summary_marks_manual_micro_live_ready():
    summary = runtime_signoff_review._build_runtime_operator_signoff_summary(
        runtime_decision={
            "effective_action": "conditional_micro_live_signoff",
            "allowed_reopen_scope": "MICRO_LIVE_ONLY",
        },
        runtime_preflight_summary={
            "status": "READY_FOR_MICRO_LIVE",
        },
        runtime_signoff_summary={
            "required_reviews": [
                {"code": "approval_template_review"},
                {"code": "execution_reconciliation_review"},
            ]
        },
    )

    assert summary["active"] is True
    assert summary["status"] == "ready_for_manual_micro_live_signoff"
    assert summary["allowed_scope"] == "MICRO_LIVE_ONLY"
    assert summary["first_required_review_code"] == "approval_template_review"
    assert summary["next_step"] == "review_required_warning_and_record_micro_live_signoff"


def test_approval_template_focus_symbol_uses_global_lineage_namespace():
    stage = {
        "selected_trial_run_id": "LINEAGE_GLOBAL_v2_true_threshold_sweep_runner_v1_acceptance_rejection_8309223c59",
        "lineage_sample_summary": {
            "scope": "family_global",
        },
    }

    assert runtime_signoff_review._approval_template_focus_symbol(stage, symbol="BTCUSDC") == "LINEAGE_GLOBAL"


def test_attach_approval_template_focus_surfaces_replay_metrics():
    payload = {
        "primary_required_review": {
            "code": "approval_template_review",
            "worst_scenario": "latency_plus_1_bar",
        }
    }
    stage = {
        "selected_trial_run_id": "LINEAGE_GLOBAL_v2_true_threshold_sweep_runner_v1_acceptance_rejection_8309223c59",
        "lineage_sample_summary": {
            "scope": "family_global",
        },
    }

    responses = {
        "/validation/stress-replay-assessment": {
            "scenario_evidence": {
                "scenario_statuses": {
                    "latency_plus_1_bar": {
                        "status": "FAIL",
                        "reason": "catastrophic_drawdown:replay_output",
                        "source": "replay_output",
                        "divergence_status": "FAIL",
                        "divergence_reason": "replay_divergence_fail:max_drawdown",
                    }
                }
            }
        },
        "/validation/stress-replay-output-artifacts": {
            "summary_counts": {
                "replay_trade_rows": 352,
                "scenarios_compared": 2,
            },
            "scenario_outputs": {
                "latency_plus_1_bar": {
                    "artifact_path": "reports/validation/stress_replay_worker_outputs/LINEAGE_GLOBAL/v2/latency_plus_1_bar.json",
                    "summary": {
                        "ev": 0.9744,
                        "p5_ev": -1.05,
                        "max_drawdown": 10.1003,
                    },
                    "approximation_gap": {
                        "ev": -0.05,
                        "max_drawdown": 0.95,
                    },
                }
            },
        },
    }

    def _request_json(base_url: str, path: str, *, query: dict[str, object]):
        assert base_url == "http://127.0.0.1:8000"
        assert query["symbol"] == "LINEAGE_GLOBAL"
        assert query["write_report"] is False
        return responses[path]

    enriched = runtime_signoff_review._attach_approval_template_focus(
        payload,
        stage=stage,
        symbol="BTCUSDC",
        base_url="http://127.0.0.1:8000",
        request_json_fn=_request_json,
    )

    focus = enriched["approval_template_focus"]
    assert focus["focus_symbol"] == "LINEAGE_GLOBAL"
    assert focus["worst_scenario"] == "latency_plus_1_bar"
    assert focus["worst_scenario_status"] == "FAIL"
    assert focus["replay_max_drawdown_r"] == 10.1003
    assert focus["approximation_gap_max_drawdown_r"] == 0.95
    assert focus["replay_trade_rows"] == 352


def test_attach_approval_template_focus_retries_on_transient_500(monkeypatch):
    payload = {
        "primary_required_review": {
            "code": "approval_template_review",
            "worst_scenario": "latency_plus_1_bar",
        }
    }
    stage = {
        "selected_trial_run_id": "LINEAGE_GLOBAL_v2_true_threshold_sweep_runner_v1_acceptance_rejection_8309223c59",
        "lineage_sample_summary": {
            "scope": "family_global",
        },
    }
    calls = {"/validation/stress-replay-assessment": 0, "/validation/stress-replay-output-artifacts": 0}

    def _request_json(base_url: str, path: str, *, query: dict[str, object]):
        assert query["write_report"] is False
        calls[path] += 1
        if path == "/validation/stress-replay-assessment" and calls[path] == 1:
            raise RuntimeError("request failed: HTTP Error 500: Internal Server Error")
        if path == "/validation/stress-replay-assessment":
            return {
                "scenario_evidence": {
                    "scenario_statuses": {
                        "latency_plus_1_bar": {
                            "status": "FAIL",
                            "reason": "catastrophic_drawdown:replay_output",
                            "source": "replay_output",
                        }
                    }
                }
            }
        return {
            "summary_counts": {"replay_trade_rows": 1, "scenarios_compared": 1},
            "scenario_outputs": {
                "latency_plus_1_bar": {
                    "artifact_path": "",
                    "summary": {"ev": 0.0, "p5_ev": 0.0, "max_drawdown": 1.0},
                    "approximation_gap": {"ev": 0.0, "max_drawdown": 0.0},
                }
            },
        }

    monkeypatch.setattr(runtime_signoff_review.time, "sleep", lambda _: None)
    enriched = runtime_signoff_review._attach_approval_template_focus(
        payload,
        stage=stage,
        symbol="BTCUSDC",
        base_url="http://127.0.0.1:8000",
        request_json_fn=_request_json,
    )

    assert calls["/validation/stress-replay-assessment"] == 2
    assert enriched["approval_template_focus"]["worst_scenario_status"] == "FAIL"


def test_build_post_patch_sample_summary_counts_recent_closes(monkeypatch):
    artifact_path = "reports/validation/mock_runtime_review.json"
    input_path = "reports/validation/mock_runtime_inputs.json"
    artifact_payload = {
        "input_artifact_paths": [input_path],
        "trade_rows": [
            {
                "plan_id": "plan_confirm_recent",
                "closed_ts": "2026-04-10T01:00:00+00:00",
                "replayed_realized_r": -1.2,
                "final_exit_reason": "stop_loss",
            },
            {
                "plan_id": "plan_limit_recent",
                "closed_ts": "2026-04-10T02:00:00+00:00",
                "replayed_realized_r": 0.7,
                "final_exit_reason": "tp3",
            },
            {
                "plan_id": "plan_confirm_old",
                "closed_ts": "2026-04-09T10:00:00+00:00",
                "replayed_realized_r": -0.8,
                "final_exit_reason": "stop_loss",
            },
        ],
    }
    input_payload = {
        "trade_rows": [
            {"plan_id": "plan_confirm_recent", "symbol": "WIFUSDC", "final_exit_held_bars": 42},
            {"plan_id": "plan_limit_recent", "symbol": "SOLUSDC", "final_exit_held_bars": 11},
            {"plan_id": "plan_confirm_old", "symbol": "NEARUSDC", "final_exit_held_bars": 99},
        ]
    }

    def _load_json_file(path):
        text = str(path)
        if text.endswith("mock_runtime_review.json"):
            return artifact_payload
        if text.endswith("mock_runtime_inputs.json"):
            return input_payload
        return None

    monkeypatch.setattr(runtime_signoff_review, "_load_json_file", _load_json_file)

    summary = runtime_signoff_review._build_post_patch_sample_summary(
        artifact_path=artifact_path,
        baseline_ts=runtime_signoff_review._parse_ts("2026-04-10T00:00:00+00:00"),
        target_closed_trades=20,
    )

    assert summary["closed_trade_count"] == 2
    assert summary["remaining_to_target"] == 18
    assert summary["stop_loss_share"] == 0.5
    assert summary["confirm_named_loss_share"] == 1.0
    assert summary["top_symbols"][0]["symbol"] == "WIFUSDC"


def test_build_approval_template_downside_profile_summarizes_loss_cluster(monkeypatch):
    artifact_payload = {
        "trade_rows": [
            {
                "plan_id": "plan_a",
                "replayed_realized_r": -1.05,
                "final_exit_reason": "stop_loss",
            },
            {
                "plan_id": "plan_b",
                "replayed_realized_r": -1.05,
                "final_exit_reason": "stop_loss",
            },
            {
                "plan_id": "plan_c",
                "replayed_realized_r": 2.95,
                "final_exit_reason": "target_tp3",
            },
        ],
        "input_artifact_paths": ["reports/validation/batch_01.json"],
    }
    batch_payload = {
        "trade_rows": [
            {"plan_id": "plan_a", "symbol": "WIFUSDC", "regime": "range", "final_exit_held_bars": 12, "entry_anchor_source": "execution_entry_fill"},
            {"plan_id": "plan_b", "symbol": "WIFUSDC", "regime": "range", "final_exit_held_bars": 16, "entry_anchor_source": "execution_entry_fill"},
            {"plan_id": "plan_c", "symbol": "BTCUSDC", "regime": "range", "final_exit_held_bars": 4, "entry_anchor_source": "execution_entry_fill"},
        ]
    }

    def _fake_load_json(path):  # noqa: ANN001
        text = str(path)
        if text.endswith("latency_plus_1_bar.json"):
            return artifact_payload
        if text.endswith("batch_01.json"):
            return batch_payload
        return None

    monkeypatch.setattr(runtime_signoff_review, "_load_json_file", _fake_load_json)

    profile = runtime_signoff_review._build_approval_template_downside_profile(
        artifact_path="reports/validation/latency_plus_1_bar.json"
    )

    assert profile["trade_count"] == 3
    assert profile["dominant_regime"] == "range"
    assert profile["stop_loss_count"] == 2
    assert profile["stop_loss_share"] == 0.6667
    assert profile["worst_loss_streak"] == 2
    assert profile["worst_loss_block_sum_r"] == -2.1
    assert profile["worst_loss_block_len"] == 2
    assert profile["confirm_named_loss_share"] == 0.0
    assert profile["median_loss_held_bars"] == 16.0
    assert profile["primary_failure_mode"] == "clustered_stop_loss_wave"
    assert profile["top_loss_symbols"][0]["symbol"] == "WIFUSDC"
    assert profile["top_loss_symbols"][0]["negative_r"] == -2.1
    assert profile["top_loss_waves"][0]["loss_trade_count"] == 2
    assert [item["code"] for item in profile["mitigation_focus"]] == ["loss_wave_cluster_review"]


def test_build_approval_template_downside_profile_marks_confirm_entry_loss_wave(monkeypatch):
    artifact_payload = {
        "trade_rows": [
            {
                "plan_id": "plan_a_confirm",
                "replayed_realized_r": -1.05,
                "final_exit_reason": "stop_loss",
                "closed_ts": "2026-04-08T12:24:00+00:00",
            },
            {
                "plan_id": "plan_b_confirm",
                "replayed_realized_r": -1.05,
                "final_exit_reason": "stop_loss",
                "closed_ts": "2026-04-08T12:24:00+00:00",
            },
            {
                "plan_id": "plan_c_confirm",
                "replayed_realized_r": -1.05,
                "final_exit_reason": "stop_loss",
                "closed_ts": "2026-04-08T12:24:00+00:00",
            },
            {
                "plan_id": "plan_d",
                "replayed_realized_r": 2.95,
                "final_exit_reason": "target_tp3",
                "closed_ts": "2026-04-08T12:40:00+00:00",
            },
        ],
        "input_artifact_paths": ["reports/validation/batch_02.json"],
    }
    batch_payload = {
        "trade_rows": [
            {"plan_id": "plan_a_confirm", "symbol": "WIFUSDC", "regime": "range", "final_exit_held_bars": 300, "entry_anchor_source": "execution_entry_fill"},
            {"plan_id": "plan_b_confirm", "symbol": "SOLUSDC", "regime": "range", "final_exit_held_bars": 360, "entry_anchor_source": "execution_entry_fill"},
            {"plan_id": "plan_c_confirm", "symbol": "NEARUSDC", "regime": "range", "final_exit_held_bars": 420, "entry_anchor_source": "execution_entry_fill"},
            {"plan_id": "plan_d", "symbol": "BTCUSDC", "regime": "range", "final_exit_held_bars": 8, "entry_anchor_source": "execution_entry_fill"},
        ]
    }

    def _fake_load_json(path):  # noqa: ANN001
        text = str(path)
        if text.endswith("latency_plus_1_bar_confirm.json"):
            return artifact_payload
        if text.endswith("batch_02.json"):
            return batch_payload
        return None

    monkeypatch.setattr(runtime_signoff_review, "_load_json_file", _fake_load_json)

    profile = runtime_signoff_review._build_approval_template_downside_profile(
        artifact_path="reports/validation/latency_plus_1_bar_confirm.json"
    )

    assert profile["confirm_named_loss_share"] == 1.0
    assert profile["long_hold_loss_share"] == 1.0
    assert profile["top_loss_wave_share_of_losses"] == 1.0
    assert profile["primary_failure_mode"] == "range_confirm_entry_loss_wave"


def test_build_confirm_loss_cluster_summary_summarizes_confirm_losses(monkeypatch):
    artifact_payload = {
        "trade_rows": [
            {
                "plan_id": "plan_a_confirm",
                "replayed_realized_r": -1.05,
                "final_exit_reason": "stop_loss",
                "closed_ts": "2026-04-08T12:24:00+00:00",
            },
            {
                "plan_id": "plan_b_confirm",
                "replayed_realized_r": -1.05,
                "final_exit_reason": "stop_loss",
                "closed_ts": "2026-04-08T12:24:00+00:00",
            },
            {
                "plan_id": "plan_c",
                "replayed_realized_r": 2.95,
                "final_exit_reason": "target_tp3",
                "closed_ts": "2026-04-08T12:40:00+00:00",
            },
        ],
        "input_artifact_paths": ["reports/validation/batch_03.json"],
    }
    batch_payload = {
        "trade_rows": [
            {"plan_id": "plan_a_confirm", "symbol": "WIFUSDC", "final_exit_held_bars": 300},
            {"plan_id": "plan_b_confirm", "symbol": "SOLUSDC", "final_exit_held_bars": 360},
            {"plan_id": "plan_c", "symbol": "BTCUSDC", "final_exit_held_bars": 8},
        ]
    }

    def _fake_load_json(path):  # noqa: ANN001
        text = str(path)
        if text.endswith("latency_plus_1_bar_confirm_cluster.json"):
            return artifact_payload
        if text.endswith("batch_03.json"):
            return batch_payload
        return None

    monkeypatch.setattr(runtime_signoff_review, "_load_json_file", _fake_load_json)

    summary = runtime_signoff_review._build_confirm_loss_cluster_summary(
        artifact_path="reports/validation/latency_plus_1_bar_confirm_cluster.json"
    )

    assert summary is not None
    assert summary["loss_trade_count"] == 2
    assert summary["median_held_bars"] == 360.0
    assert summary["top_symbols"][0]["symbol"] == "WIFUSDC"
    assert summary["top_symbols"][0]["median_held_bars"] == 300.0
    assert summary["top_waves"][0]["loss_trade_count"] == 2
    assert summary["top_waves"][0]["negative_r"] == -2.1
    assert summary["held_bar_bands"]["over_240"] == 2
    assert summary["held_bar_bands"]["over_1000"] == 0
    assert summary["review_priority"][0]["symbol"] == "WIFUSDC"


def test_main_writes_confirm_loss_cluster_report(monkeypatch, tmp_path, capsys):
    stage_file = tmp_path / "current_stage.json"
    stage_file.write_text(
        json.dumps(
            {
                "runtime_reopen_status": {"status": "ready_to_reopen_runtime", "ready": True},
                "runtime_signoff_summary": {
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
                "lineage_sample_summary": {"closed_trade_count": 183, "proof_goal_closed_trades": 100, "scope": "family_global"},
                "risk_gate_summary": {"status": "PASS", "risk_state": "OPEN"},
                "validation_approval_strip": {"approve_value": "manual review first", "align_value": "playbook_drift", "act_value": "continue_candidate_review_under_portfolio_caps"},
                "selected_trial_run_id": "LINEAGE_GLOBAL_v2_true_threshold",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        runtime_signoff_review,
        "parse_args",
        lambda: runtime_signoff_review.argparse.Namespace(
            base_url="http://127.0.0.1:8000",
            symbol="BTCUSDC",
            universe="usdc_perp_top30",
            days=30,
            stage_file=str(stage_file),
            report_dir=str(tmp_path / "reports"),
            no_write_report=False,
        ),
    )
    monkeypatch.setattr(
        runtime_signoff_review,
        "_attach_approval_template_focus",
        lambda payload, **kwargs: {
            **payload,
            "approval_template_focus": {
                "focus_symbol": "LINEAGE_GLOBAL",
                "worst_scenario": "latency_plus_1_bar",
                "confirm_loss_cluster_summary": {
                    "loss_trade_count": 2,
                    "median_held_bars": 330.0,
                    "p75_held_bars": 360,
                    "held_bar_bands": {"over_240": 2, "over_1000": 0, "over_2000": 0},
                    "top_symbols": [{
                        "symbol": "WIFUSDC",
                        "loss_trade_count": 2,
                        "negative_r": -2.1,
                        "median_held_bars": 330.0,
                        "p75_held_bars": 360,
                    }],
                    "top_waves": [{
                        "closed_ts": "2026-04-08T12:24:00+00:00",
                        "loss_trade_count": 2,
                        "negative_r": -2.1,
                        "top_symbols": [{"symbol": "WIFUSDC", "loss_trade_count": 2}],
                    }],
                    "review_priority": [{
                        "symbol": "WIFUSDC",
                        "negative_r": -2.1,
                        "loss_trade_count": 2,
                        "median_held_bars": 330.0,
                    }],
                },
                "downside_profile": {
                    "loss_trade_count": 2,
                    "confirm_named_loss_share": 1.0,
                    "top_loss_wave_share_of_losses": 1.0,
                    "primary_failure_mode": "range_confirm_entry_loss_wave",
                    "primary_failure_summary": "range regime losses are dominated by confirm-entry stop-outs that stay open too long and cluster in the same close wave",
                },
                "entry_timing_loss_profile": {
                    "dominant_loss_cohort": "confirm",
                    "confirm_loss_share": 1.0,
                    "confirm_negative_r_share": 1.0,
                    "held_bar_gap_confirm_minus_non_confirm": 330.0,
                    "confirm": {
                        "loss_trade_count": 2,
                        "negative_r": -2.1,
                        "median_held_bars": 330.0,
                        "p75_held_bars": 360,
                        "top_symbols": [{"symbol": "WIFUSDC", "loss_trade_count": 2, "negative_r": -2.1}],
                    },
                    "non_confirm": {
                        "loss_trade_count": 0,
                        "negative_r": 0.0,
                        "median_held_bars": 0.0,
                        "p75_held_bars": 0,
                        "top_symbols": [],
                    },
                    "summary": "confirm losses dominate and hold longer",
                },
                "entry_timing_priority_summary": {
                    "primary_focus_code": "confirm_entry_tighten",
                    "primary_summary": "confirm 손실 비중이 높아 range confirm-entry를 먼저 줄여야 함",
                    "secondary_focus_code": "non_confirm_fail_fast",
                    "secondary_summary": "non-confirm 손실은 수는 적지만 더 오래 끌려서 fail-fast shadow 검토가 필요함",
                    "ordered_focus": ["confirm_entry_tighten", "non_confirm_fail_fast"],
                },
                "mitigation_execution_plan": {
                    "primary_focus_label": "confirm 진입 타이밍 축소",
                    "primary_status": "candidate_review_pending",
                    "primary_command": "cmd-entry",
                    "secondary_focus_label": "non-confirm fail-fast",
                    "secondary_status": "deferred_by_experiment_sequence",
                    "secondary_command": "",
                    "ordered_steps": [],
                },
            },
        },
    )

    exit_code = runtime_signoff_review.main()

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert "confirm_loss_cluster_report_path" in payload
    assert "entry_timing_loss_report_path" in payload
    assert "runtime_mitigation_plan_report_path" in payload
    confirm_report = tmp_path / payload["confirm_loss_cluster_report_path"]
    assert confirm_report.exists()
    report_text = confirm_report.read_text(encoding="utf-8")
    assert "held_bar_bands: >240=2, >1000=0, >2000=0" in report_text
    assert "WIFUSDC: 2 losses / -2.1000R / median=330 bars / p75=360 bars" in report_text
    assert "2026-04-08T12:24:00+00:00: 2 confirm losses / -2.1000R / top=WIFUSDC(2)" in report_text
    entry_timing_report = tmp_path / payload["entry_timing_loss_report_path"]
    assert entry_timing_report.exists()
    entry_timing_text = entry_timing_report.read_text(encoding="utf-8")
    assert "dominant_loss_cohort: confirm" in entry_timing_text
    assert "confirm_loss_share: 100.00% / confirm_negative_r_share: 100.00%" in entry_timing_text
    assert "losses: 2 / -2.1000R / median=330 bars / p75=360 bars" in entry_timing_text
    assert "priority: primary=confirm_entry_tighten / confirm 손실 비중이 높아 range confirm-entry를 먼저 줄여야 함" in entry_timing_text
    assert "execution_plan: primary=confirm 진입 타이밍 축소 / candidate_review_pending / cmd=cmd-entry" in entry_timing_text
    mitigation_plan_report = tmp_path / payload["runtime_mitigation_plan_report_path"]
    assert mitigation_plan_report.exists()
    mitigation_plan_text = mitigation_plan_report.read_text(encoding="utf-8")
    assert "1st: confirm 진입 타이밍 축소 / candidate_review_pending" in mitigation_plan_text
    assert "2nd: non-confirm fail-fast / deferred_by_experiment_sequence" in mitigation_plan_text


def test_build_entry_timing_loss_profile_summarizes_confirm_vs_non_confirm(monkeypatch):
    artifact_payload = {
        "trade_rows": [
            {
                "plan_id": "plan_a_confirm",
                "replayed_realized_r": -1.05,
                "closed_ts": "2026-04-08T12:24:00+00:00",
            },
            {
                "plan_id": "plan_b_confirm",
                "replayed_realized_r": -2.10,
                "closed_ts": "2026-04-08T12:24:00+00:00",
            },
            {
                "plan_id": "plan_c_early",
                "replayed_realized_r": -0.50,
                "closed_ts": "2026-04-08T12:25:00+00:00",
            },
        ],
        "input_artifact_paths": ["reports/validation/batch_04.json"],
    }
    batch_payload = {
        "trade_rows": [
            {"plan_id": "plan_a_confirm", "symbol": "WIFUSDC", "final_exit_held_bars": 300},
            {"plan_id": "plan_b_confirm", "symbol": "SOLUSDC", "final_exit_held_bars": 360},
            {"plan_id": "plan_c_early", "symbol": "BTCUSDC", "final_exit_held_bars": 12},
        ]
    }

    def _fake_load_json(path):  # noqa: ANN001
        text = str(path)
        if text.endswith("latency_plus_1_bar_entry_timing.json"):
            return artifact_payload
        if text.endswith("batch_04.json"):
            return batch_payload
        return None

    monkeypatch.setattr(runtime_signoff_review, "_load_json_file", _fake_load_json)

    profile = runtime_signoff_review._build_entry_timing_loss_profile(
        artifact_path="reports/validation/latency_plus_1_bar_entry_timing.json"
    )

    assert profile is not None
    assert profile["dominant_loss_cohort"] == "confirm"
    assert profile["confirm_loss_share"] == 0.6667
    assert profile["confirm_negative_r_share"] == 0.863
    assert profile["held_bar_gap_confirm_minus_non_confirm"] == 348.0
    assert profile["confirm"]["loss_trade_count"] == 2
    assert profile["non_confirm"]["loss_trade_count"] == 1
    assert profile["summary"] == "confirm losses dominate and hold longer"


def test_build_entry_timing_priority_summary_prefers_confirm_then_non_confirm_fail_fast():
    summary = runtime_signoff_review._build_entry_timing_priority_summary(
        {
            "confirm_loss_share": 0.883,
            "confirm_negative_r_share": 0.883,
            "held_bar_gap_confirm_minus_non_confirm": -1029.0,
            "confirm": {"loss_trade_count": 83},
            "non_confirm": {"loss_trade_count": 11},
        }
    )

    assert summary is not None
    assert summary["primary_focus_code"] == "confirm_entry_tighten"
    assert summary["secondary_focus_code"] == "non_confirm_fail_fast"


def test_build_mitigation_execution_plan_maps_priority_to_review_steps():
    plan = runtime_signoff_review._build_mitigation_execution_plan(
        priority_summary={
            "ordered_focus": ["confirm_entry_tighten", "non_confirm_fail_fast"],
        },
        mitigation_review_summary={
            "items": [
                {
                    "code": "range_entry_timing_review",
                    "review_mode": "live_split_review",
                    "status": "candidate_review_pending",
                    "command": "cmd-entry",
                    "current_constraint": "waiting",
                },
                {
                    "code": "shadow_fail_fast_review",
                    "review_mode": "shadow_only",
                    "status": "deferred_by_experiment_sequence",
                    "command": "",
                    "current_constraint": "deferred",
                },
            ]
        },
    )

    assert plan is not None
    assert plan["primary_focus_code"] == "confirm_entry_tighten"
    assert plan["primary_focus_label"] == "confirm 진입 타이밍 축소"
    assert plan["primary_status"] == "candidate_review_pending"
    assert plan["secondary_focus_code"] == "non_confirm_fail_fast"
    assert plan["secondary_status"] == "deferred_by_experiment_sequence"


def test_build_mitigation_review_summary_maps_commands_and_statuses():
    profile = {
        "mitigation_focus": [
            {"code": "range_entry_timing_review", "summary": "review entry timing"},
            {"code": "shadow_fail_fast_review", "summary": "review fail fast in shadow"},
            {"code": "loss_wave_cluster_review", "summary": "review loss wave clustering"},
        ]
    }
    stage = {
        "entry_timing_review_target": {},
    }

    summary = runtime_signoff_review._build_mitigation_review_summary(
        downside_profile=profile,
        stage=stage,
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=30,
    )

    assert summary is not None
    assert summary["primary_action_code"] == "range_entry_timing_review"
    assert summary["primary_action_status"] == "candidate_review_pending"
    assert summary["candidate_pending_count"] == 1
    assert summary["deferred_count"] == 1
    assert summary["research_only_count"] == 1
    items = {item["code"]: item for item in summary["items"]}
    assert items["range_entry_timing_review"]["command"].endswith(
        "--symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_entry_timing_split_review"
    )
    assert items["shadow_fail_fast_review"]["status"] == "deferred_by_experiment_sequence"
    assert items["shadow_fail_fast_review"]["shadow_hypothesis"] == "fail_fast_no_reaction_within_3_bars"
    assert items["loss_wave_cluster_review"]["status"] == "manual_operator_review"
