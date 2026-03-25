from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from scripts import notify_operator_session_brief


def _fake_brief() -> dict:
    return {
        "symbol": "BTCUSDC",
        "universe": "usdc_perp_top30",
        "brief_status": "DEPLOYMENT_REVIEW_REQUIRED",
        "headline": "headline",
        "report_path": "reports/operations/operator_session_briefs/brief.md",
        "next_steps": ["step-a"],
        "snapshot": {
            "report_path": "reports/operations/operator_surface_divergence/snapshot.md",
            "deployment_alignment": "DIVERGED",
            "playbook_alignment": "DIVERGED",
            "approval_strip": {
                "approve_value": "validation/checklist no_go",
                "align_value": "diverged",
                "act_value": "continue_candidate_review_under_portfolio_caps",
                "act_priority_level": "urgent",
                "primary_reason": "MANUAL_REVIEW",
                "approve_reason": "validation=NO_GO | checklist=NO_GO | dashboard=GO | MANUAL_REVIEW",
                "align_reason": "dashboard / checklist / validation surface가 서로 다른 방향을 가리키고 있습니다.",
                "act_reason": "continue candidate review",
            },
            "kernel_snapshot": {
                "kernel_verdict": "manual_review",
                "money_leak_r": 0.33,
                "strongest_drag_source": "fill_capture_gap",
                "outcome_control_tier": "downgrade_to_manual",
                "rollout_recommendation": "reduce",
                "candidate_surface_priority": "context_only",
            },
            "dashboard_summary": {
                "top_operator_action": "continue_candidate_review_under_portfolio_caps",
                "top_action_followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review",
                "deployment_go_no_go": "GO",
                "playbook_action": "continue_candidate_review_under_portfolio_caps",
                "approval_strip_summary": {
                    "approve_value": "approval usable",
                    "align_value": "aligned",
                    "act_value": "continue_candidate_review_under_portfolio_caps",
                },
            },
            "validation_summary": {
                "deployment_go_no_go": "NO_GO",
                "playbook_action": "resolve_selected_trial_lineage_before_rollout",
                "validation_report": {
                    "approval_strip_summary": {
                        "approve_value": "validation no_go",
                        "align_value": "playbook_drift",
                        "act_value": "review_runtime_execution_drag_before_expansion",
                    }
                },
            },
            "checklist_summary": {
                "deployment_go_no_go": "NO_GO",
                "playbook_action": "resolve_selected_trial_lineage_before_rollout",
                "approval_strip_summary": {
                    "approve_value": "validation/checklist no_go",
                    "align_value": "aligned",
                    "act_value": "clear_blocking_operational_items_before_rollout",
                },
            },
            "signal_funnel_snapshot": {
                "research_action": "run_shadow_exit_timing_review",
                "top_action_followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review",
                "edge_state": "watch_edge",
                "edge_proof_state": "sample_building",
                "edge_claim_state": "do_not_claim_edge_yet",
                "edge_proof_goal_closed_trades": 100,
                "remaining_closed_trades_to_edge_proof_goal": 94,
                "edge_closed_trade_count": 6,
                "edge_regime_dependency_state": "single_regime_observed",
                "edge_true_edge_ratio": 0.82,
                "edge_decay_rate": -0.03,
                "edge_evolution_state": "reduce_candidate",
                "edge_evolution_action": "reduce_baseline_allocation_review",
                "edge_evolution_bias": "reduce_baseline",
                "review_followup_ledger": {
                    "available": True,
                    "last_status": "READY",
                    "last_action": "reduce_baseline_allocation_review",
                    "recent_entry_count": 3,
                    "last_followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review",
                },
                "entry_timing_focus": "early_limit",
                "execution_style_focus": "passive_limit",
                "entry_timing_review_target": {
                    "action": "run_entry_timing_split_review",
                    "preferred_variant": "early_limit",
                    "symbol": "ETHUSDC",
                    "status": "ACTIONABLE_ENTRY",
                    "strategy_family": "sweep_reversal",
                    "focus_source": "accepted_candidate_focus",
                    "followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action run_entry_timing_split_review",
                },
                "execution_style_review_target": {
                    "action": "run_execution_style_split_review",
                    "preferred_variant": "passive_limit",
                    "symbol": "ETHUSDC",
                    "status": "ACTIONABLE_ENTRY",
                    "strategy_family": "sweep_reversal",
                    "focus_source": "accepted_candidate_focus",
                    "followup_command": "./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action run_execution_style_split_review",
                },
                "representative_accepted_candidate": {
                    "symbol": "ETHUSDC",
                    "status": "ACTIONABLE_ENTRY",
                    "strategy_family": "sweep_reversal",
                    "edge_state": "watch_edge",
                    "entry_timing_focus": "early_limit",
                    "execution_style_focus": "passive_limit",
                },
                "representative_blocked_candidate": {
                    "symbol": "BTCUSDC",
                    "status": "BLOCKED_SETUP",
                    "strategy_family": "trend_continuation",
                    "block_reason": "portfolio_cap",
                    "edge_state": "fragile_edge",
                    "entry_timing_focus": "reaction_confirmed",
                    "execution_style_focus": "market",
                },
                "top_family_bottleneck": "legacy_zone_plan",
                "top_session_bottleneck": "preferred_live_window",
            },
            "operator_ui_sections": {
                "all_present": True,
            },
        },
    }


def test_main_blocks_live_send_without_allow_flag(monkeypatch, tmp_path: Path, capsys) -> None:
    state_file = tmp_path / "state.json"
    latest_run_file = tmp_path / "latest.json"
    args = Namespace(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=7,
        portfolio_limit=5,
        intent_limit=5,
        reconcile_limit=5,
        state_file=str(state_file),
        latest_run_file=str(latest_run_file),
        channel="system",
        brief_mode="shift-start",
        webhook_url="",
        allow_live_send=False,
        force_send=True,
        dry_run=False,
    )
    writes: list[Path] = []

    monkeypatch.setattr(notify_operator_session_brief, "parse_args", lambda: args)
    monkeypatch.setattr(notify_operator_session_brief, "_run_brief", lambda _args: _fake_brief())
    monkeypatch.setattr(notify_operator_session_brief, "_read_json", lambda path: None)

    def _write(path: Path, payload: dict) -> None:
        writes.append(path)
        path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(notify_operator_session_brief, "_write_json", _write)

    class _Dispatcher:
        def __init__(self, settings):  # noqa: ANN001
            raise AssertionError("dispatcher should not be created when live send is not allowed")

    monkeypatch.setattr(notify_operator_session_brief, "NotificationDispatcher", _Dispatcher)

    assert notify_operator_session_brief.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["allow_live_send"] is False
    assert payload["delivery"]["reason"] == "live_send_not_allowed"
    assert payload["notified"] is False
    assert "message" in payload
    assert "- approval_strip: approve=validation/checklist no_go | align=diverged | act=continue_candidate_review_under_portfolio_caps | priority=urgent" in payload["message"]
    assert "- kernel: verdict=manual_review | money_leak_r=0.33 | drag_source=fill_capture_gap | control=downgrade_to_manual | rollout=reduce | candidate_surface=context_only" in payload["message"]
    assert "- dashboard_surface: approve=approval usable | align=aligned | act=continue_candidate_review_under_portfolio_caps" in payload["message"]
    assert "- validation_surface: approve=validation no_go | align=playbook_drift | act=review_runtime_execution_drag_before_expansion" in payload["message"]
    assert "- checklist_surface: approve=validation/checklist no_go | align=aligned | act=clear_blocking_operational_items_before_rollout" in payload["message"]
    assert "- top_operator_action: continue_candidate_review_under_portfolio_caps | cmd=./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review" in payload["message"]
    assert "- research/funnel: action=run_shadow_exit_timing_review | edge_state=watch_edge | proof=sample_building/do_not_claim_edge_yet | closes=6/100 | remaining=94 | regime=single_regime_observed | entry_timing=early_limit | execution_style=passive_limit | true_edge=0.8200 | decay=-0.0300 | edge_evolution=reduce_candidate:reduce_baseline_allocation_review:reduce_baseline | review_ledger=READY:reduce_baseline_allocation_review:3 | family_bottleneck=legacy_zone_plan | session_bottleneck=preferred_live_window" in payload["message"]
    assert "proof=sample_building/do_not_claim_edge_yet | closes=6/100 | remaining=94 | regime=single_regime_observed | entry_timing=early_limit | execution_style=passive_limit | true_edge=0.8200 | decay=-0.0300" in payload["message"]
    assert "- review_followup_ledger: status=READY | action=reduce_baseline_allocation_review | entries=3 | cmd=./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review" in payload["message"]
    assert "- entry_timing_review_target: action=run_entry_timing_split_review | target=ETHUSDC | variant=early_limit | status=ACTIONABLE_ENTRY | family=sweep_reversal | focus=accepted_candidate_focus | cmd=./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action run_entry_timing_split_review" in payload["message"]
    assert "- execution_style_review_target: action=run_execution_style_split_review | target=ETHUSDC | variant=passive_limit | status=ACTIONABLE_ENTRY | family=sweep_reversal | focus=accepted_candidate_focus | cmd=./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action run_execution_style_split_review" in payload["message"]
    assert "- accepted_candidate_focus: symbol=ETHUSDC | family=sweep_reversal | edge=watch_edge | split=early_limit/passive_limit | status=ACTIONABLE_ENTRY" in payload["message"]
    assert "- blocked_candidate_focus: symbol=BTCUSDC | family=trend_continuation | edge=fragile_edge | split=reaction_confirmed/market | status=BLOCKED_SETUP | reason=portfolio_cap" in payload["message"]
    assert payload["current"]["kernel_verdict"] == "manual_review"
    assert payload["current"]["money_leak_r"] == 0.33
    assert payload["current"]["candidate_surface_priority"] == "context_only"
    assert payload["current"]["top_action_followup_command"].endswith(
        "--symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review"
    )
    assert payload["current"]["approval_strip_approve"] == "validation/checklist no_go"
    assert payload["current"]["dashboard_approve"] == "approval usable"
    assert payload["current"]["validation_act"] == "review_runtime_execution_drag_before_expansion"
    assert payload["current"]["checklist_act"] == "clear_blocking_operational_items_before_rollout"
    assert payload["current"]["edge_state"] == "watch_edge"
    assert payload["current"]["edge_evolution_state"] == "reduce_candidate"
    assert payload["current"]["edge_evolution_action"] == "reduce_baseline_allocation_review"
    assert payload["current"]["edge_evolution_bias"] == "reduce_baseline"
    assert payload["current"]["review_followup_status"] == "READY"
    assert payload["current"]["review_followup_action"] == "reduce_baseline_allocation_review"
    assert payload["current"]["review_followup_entries"] == 3
    assert payload["current"]["review_followup_command"].endswith(
        "--symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review"
    )
    assert payload["current"]["entry_timing_focus"] == "early_limit"
    assert payload["current"]["execution_style_focus"] == "passive_limit"
    assert payload["current"]["accepted_candidate_symbol"] == "ETHUSDC"
    assert payload["current"]["accepted_candidate_edge_state"] == "watch_edge"
    assert payload["current"]["blocked_candidate_symbol"] == "BTCUSDC"
    assert payload["current"]["blocked_candidate_edge_state"] == "fragile_edge"
    assert payload["current"]["entry_target_symbol"] == "ETHUSDC"
    assert payload["current"]["entry_target_variant"] == "early_limit"
    assert payload["current"]["entry_target_followup_command"].endswith("--symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action run_entry_timing_split_review")
    assert payload["current"]["execution_target_symbol"] == "ETHUSDC"
    assert payload["current"]["execution_target_variant"] == "passive_limit"
    assert payload["current"]["execution_target_followup_command"].endswith("--symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action run_execution_style_split_review")
    assert latest_run_file in writes
    assert state_file not in writes


def test_main_dispatches_when_allow_live_send(monkeypatch, tmp_path: Path, capsys) -> None:
    state_file = tmp_path / "state.json"
    latest_run_file = tmp_path / "latest.json"
    args = Namespace(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=7,
        portfolio_limit=5,
        intent_limit=5,
        reconcile_limit=5,
        state_file=str(state_file),
        latest_run_file=str(latest_run_file),
        channel="discord",
        brief_mode="shift-end",
        webhook_url="https://discord.example/webhook",
        allow_live_send=True,
        force_send=True,
        dry_run=False,
    )
    writes: list[Path] = []
    dispatch_calls: list[dict] = []

    monkeypatch.setattr(notify_operator_session_brief, "parse_args", lambda: args)
    monkeypatch.setattr(notify_operator_session_brief, "_run_brief", lambda _args: _fake_brief())
    monkeypatch.setattr(notify_operator_session_brief, "_read_json", lambda path: None)

    def _write(path: Path, payload: dict) -> None:
        writes.append(path)
        path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(notify_operator_session_brief, "_write_json", _write)

    class _Settings:
        alert_discord_webhook_url = ""

    monkeypatch.setattr(notify_operator_session_brief, "get_settings", lambda: _Settings())

    class _Dispatcher:
        def __init__(self, settings):  # noqa: ANN001
            self.settings = settings

        def dispatch(self, *, channel, alert_type, symbol, payload):  # noqa: ANN001
            dispatch_calls.append(
                {"channel": channel, "alert_type": alert_type, "symbol": symbol, "payload": payload}
            )
            return {"channel": channel, "delivered": True, "skipped": False, "reason": "delivered"}

    monkeypatch.setattr(notify_operator_session_brief, "NotificationDispatcher", _Dispatcher)

    assert notify_operator_session_brief.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["allow_live_send"] is True
    assert payload["notified"] is True
    assert payload["delivery"]["reason"] == "delivered"
    assert "- closing_approval_strip: approve=validation/checklist no_go | align=diverged | act=continue_candidate_review_under_portfolio_caps | priority=urgent" in payload["message"]
    assert "- closing_kernel: verdict=manual_review | money_leak_r=0.33 | drag_source=fill_capture_gap | control=downgrade_to_manual | rollout=reduce | candidate_surface=context_only" in payload["message"]
    assert "- closing_dashboard_surface: approve=approval usable | align=aligned | act=continue_candidate_review_under_portfolio_caps" in payload["message"]
    assert "- closing_validation_surface: approve=validation no_go | align=playbook_drift | act=review_runtime_execution_drag_before_expansion" in payload["message"]
    assert "- closing_checklist_surface: approve=validation/checklist no_go | align=aligned | act=clear_blocking_operational_items_before_rollout" in payload["message"]
    assert "- final_top_action: continue_candidate_review_under_portfolio_caps | cmd=./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review" in payload["message"]
    assert "- carryover_focus: research=run_shadow_exit_timing_review | edge_state=watch_edge | proof=sample_building/do_not_claim_edge_yet | closes=6/100 | remaining=94 | regime=single_regime_observed | entry_timing=early_limit | execution_style=passive_limit | true_edge=0.8200 | decay=-0.0300 | edge_evolution=reduce_candidate:reduce_baseline_allocation_review:reduce_baseline | review_ledger=READY:reduce_baseline_allocation_review:3 | family_bottleneck=legacy_zone_plan | session_bottleneck=preferred_live_window" in payload["message"]
    assert "- carryover_review_followup_ledger: status=READY | action=reduce_baseline_allocation_review | entries=3 | cmd=./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action reduce_baseline_allocation_review" in payload["message"]
    assert "- carryover_entry_timing_review_target: action=run_entry_timing_split_review | target=ETHUSDC | variant=early_limit | status=ACTIONABLE_ENTRY | family=sweep_reversal | focus=accepted_candidate_focus | cmd=./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action run_entry_timing_split_review" in payload["message"]
    assert "- carryover_execution_style_review_target: action=run_execution_style_split_review | target=ETHUSDC | variant=passive_limit | status=ACTIONABLE_ENTRY | family=sweep_reversal | focus=accepted_candidate_focus | cmd=./.venv/bin/python scripts/run_split_review_followup.py --symbol ETHUSDC --universe usdc_perp_top30 --days 7 --action run_execution_style_split_review" in payload["message"]
    assert "- carryover_accepted_candidate: symbol=ETHUSDC | family=sweep_reversal | edge=watch_edge | split=early_limit/passive_limit | status=ACTIONABLE_ENTRY" in payload["message"]
    assert "- carryover_blocked_candidate: symbol=BTCUSDC | family=trend_continuation | edge=fragile_edge | split=reaction_confirmed/market | status=BLOCKED_SETUP | reason=portfolio_cap" in payload["message"]
    assert dispatch_calls[0]["channel"] == "discord"
    assert dispatch_calls[0]["symbol"] == "BTCUSDC"
    assert state_file in writes
    assert latest_run_file in writes
