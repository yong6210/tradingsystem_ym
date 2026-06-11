import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts import run_market_state_rotation_v6_launch_shadow_watch as watch
from scripts.run_market_state_rotation_v6_quote_shadow_audit import build_quote_shadow_row


def _book() -> dict:
    return {
        "bids": [["99999", "1.0"], ["99998", "1.0"]],
        "asks": [["100001", "1.0"], ["100002", "1.0"]],
    }


def _args(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        iterations=2,
        interval_seconds=0.0,
        target_hours=0.0,
        quote_samples_per_tick=2,
        force_quote_sample=False,
        disable_adaptive_quote_cadence=False,
        sleep_until_next_missing_quote_window=False,
        max_pre_run_wait_seconds=3600.0,
        quote_window_wakeup_buffer_seconds=5.0,
        disable_market_data_refresh_after_quote_window_sleep=False,
        disable_market_data_refresh_before_evidence_run=False,
        report_dir=str(tmp_path / "watch"),
        evidence_report_root=str(tmp_path / "evidence"),
        source_backtest_report=str(tmp_path / "source.json"),
        stress_report=str(tmp_path / "stress.json"),
        walk_forward_report=str(tmp_path / "walk.json"),
        manual_safety_evidence="",
        sample_jsonl=str(tmp_path / "sample.jsonl"),
        historical_replay_source=str(tmp_path / "btc_1h.json"),
        historical_replay_days=30,
        historical_lifecycle_source=str(tmp_path / "lifecycle.json"),
        canary_max_notional_usdt=0.0,
        canary_max_leverage=10.0,
        canary_max_daily_loss_usdt=0.0,
        canary_risk_caps_json=str(tmp_path / "canary_caps.json"),
        microstructure_recent_hours=24.0,
        quiet=True,
    )


def test_launch_shadow_watch_repeats_no_live_evidence_cycles(monkeypatch, tmp_path) -> None:
    calls = []
    sleeps = []

    def fake_run_evidence_cycle(**kwargs):
        calls.append(kwargs)
        iteration = len(calls)
        return {
            "overall_status": "healthy_abstention_waiting_for_quality_signal",
            "no_live_order_sent": True,
            "decision_state": {
                "primary_cause": "strategy_abstaining_from_low_quality_soft_contexts",
                "signal_stale": True,
                "live_order_submission_allowed": False,
            },
            "entry_quality": {
                "recommended_experiment_scope": "do_not_relax_current_top_soft_contexts_without_new_evidence",
                "eligible_probe_context_count": 0,
                "rejected_soft_context_count": 6543,
                "mc04_broad_relaxation_rejected": True,
                "dominant_primary_issue": (
                    "soft_confluence_filters_are_dominating_current_no_trade_distribution"
                ),
                "reason_class_counts": {"soft_candidate": 21774, "hard_guard": 181},
                "top_no_trade_reasons": [
                    {"reason": "no_trade_MC12_low_confluence", "count": 12220},
                    {"reason": "no_trade_MC04_no_clear_first_touch", "count": 9554},
                ],
                "dominant_no_trade_context": {
                    "reason": "MC04_no_clear_first_touch",
                    "probe_quality": "reject_low_quality_soft_context",
                },
                "safe_experiment_backlog": [
                    {"name": "quality_gated_mc12_near_miss_micro_probe"},
                    {"name": "mc04_first_touch_observation_only"},
                ],
                "operator_interpretation": {
                    "status": "wait_for_new_walk_forward_evidence_before_relaxing_soft_contexts",
                },
                "fresh_signal_resolution_plan": {
                    "status": "no_safe_runtime_fix_available",
                    "root_cause_count": 4,
                    "top_no_trade_reason": {
                        "reason": "no_trade_MC12_low_confluence",
                        "count": 12220,
                    },
                    "operator_fixable_now": False,
                    "primary_safe_experiment": "quality_gated_mc12_near_miss_micro_probe",
                    "safe_actions": [
                        "monitor_fresh_signal_on_capped_interval_without_forcing_entry",
                        "keep_paper_apply_blocked_until_fresh_signal_and_operator_review",
                        "run_or_review_offline_near_miss_walk_forward_before_changing_runtime_filters",
                        "keep_mc04_first_touch_broad_relaxation_observation_only",
                    ],
                    "unsafe_shortcuts": [
                        "force_current_fresh_signal",
                        "broadly_relax_mc04_first_touch",
                        "broadly_lower_confluence_floor_without_walk_forward_evidence",
                        "apply_paper_bridge_without_fresh_signal_and_verified_backup",
                        "enable_live_orders_from_evidence_cycle",
                    ],
                    "no_live_order_sent": True,
                },
            },
            "collection_progress": {
                "quote_observed": 80 + iteration * 2,
                "quote_distinct_hours": 8 + iteration,
                "paper_fill_rows": 0,
            },
            "readiness_progress": {},
            "execution_parity_collection_plan": {
                "status": "waiting_for_fresh_signal",
                "estimated_future_paper_apply_events_needed": 20,
                "estimated_events_needed_after_current_creditable_apply": 20,
                "will_credit_current_apply_after_operator_review": False,
                "currently_creditable_actions": [],
                "next_step": "wait_for_fresh_v6_add_or_remove_signal",
                "non_substitutable": True,
                "no_live_order_sent": True,
            },
            "paper_bridge_apply_gate": {
                "status": "blocked_waiting_for_fresh_signal",
                "fresh_signal": False,
                "can_request_paper_apply_now": False,
                "snapshot_blockers": ["signal_stale"],
            },
            "quote_cadence_preflight": {
                "decision": "capture_new_utc_hour_for_hour_gate",
                "effective_quote_samples_per_tick": 2,
                "force_quote_sample": False,
            },
            "signal_wait_plan": {
                "status": "blocked_waiting_for_fresh_signal",
                "signal_absence_primary_cause": "expected_sparse_signal_wait_within_recent_add_cadence",
                "signal_pipeline_issue_suspected": False,
                "signal_absence_diagnosis": {
                    "primary_cause": "expected_sparse_signal_wait_within_recent_add_cadence",
                    "class": "healthy_sparse_cadence_wait",
                    "pipeline_issue_suspected": False,
                    "force_signal_allowed": False,
                    "runtime_filter_relaxation_allowed": False,
                    "safe_next_step": "monitor_on_fresh_signal_window_without_forcing_entry",
                    "no_live_order_sent": True,
                },
            },
            "launch_readiness": {
                "status": "research_ready_waiting_for_fresh_signal",
                "research_ready": True,
                "shadow_ready": True,
                "tiny_canary_evidence_ready": False,
                "paper_only_rehearsal": {
                    "status": "armed_waiting_for_fresh_signal",
                    "system_ready": True,
                    "armed": True,
                    "current_rehearsal_available": False,
                    "first_rehearsal_event_completed": False,
                    "max_substitution_status": "max_substitution_complete_realtime_gate_remaining",
                    "max_substitution_ready": True,
                    "unresolved_proxy_gates": [],
                    "substituted_or_prevalidated_gates": [
                        "historical_quote_replay",
                        "historical_lifecycle_proxy",
                        "paper_bridge_command_contract",
                        "pre_apply_backup_contract",
                        "no_live_authority_contract",
                    ],
                    "non_substitutable_remaining_gates": [
                        "current_fresh_signal",
                        "first_real_paper_lifecycle_row",
                    ],
                    "remaining_gates": ["current_fresh_signal", "first_real_paper_lifecycle_row"],
                    "live_order_submission_allowed": False,
                    "no_live_order_sent": True,
                },
                "next_blocker": {
                    "gate": "current_fresh_signal",
                    "next_action": "monitor_fresh_v6_signal_without_forcing_entry",
                },
                "blocking_gates": [
                    {
                        "gate": "current_fresh_signal",
                        "blocker": "fresh_signal_missing_or_stale",
                        "next_action": "monitor_fresh_v6_signal_without_forcing_entry",
                    }
                ],
                "operator_commands": {
                    "microstructure_quote_capture": "capture",
                    "paper_bridge_dry_run": "dry-run",
                    "paper_apply_only_after_fresh_signal": "paper-apply",
                },
            },
            "historical_gate_substitution": {
                "realtime_quote_wait_replaced": True,
                "paper_shadow_fill_proxy_replaced": True,
            },
            "canary_risk_caps_config": {
                "status": "missing_optional_config_file",
                "configured": False,
                "source": "cli_or_default",
                "errors": ["max_notional_usdt_must_be_positive", "max_daily_loss_usdt_must_be_positive"],
            },
        }

    monkeypatch.setattr(watch, "run_evidence_cycle", fake_run_evidence_cycle)

    summary = watch.run_launch_shadow_watch(_args(tmp_path), sleep_fn=lambda seconds: sleeps.append(seconds))

    assert summary["status"] == "target_observation_complete_waiting_for_fresh_signal"
    assert summary["target_observation_complete"] is True
    assert summary["target_observation_status"]["launch_next_blocker"] == "current_fresh_signal"
    assert summary["target_observation_status"]["reason"] == (
        "runtime_observation_complete_but_realtime_fresh_signal_gate_still_waiting"
    )
    assert summary["latest_launch_state"]["status"] == (
        "target_observation_complete_waiting_for_fresh_signal"
    )
    assert summary["latest_launch_state"]["launch_status"] == "research_ready_waiting_for_fresh_signal"
    assert summary["latest_launch_state"]["next_blocker_gate"] == "current_fresh_signal"
    assert summary["latest_launch_state"]["fresh_signal_available_seen"] is False
    assert summary["latest_launch_state"]["paper_apply_available_seen"] is False
    assert summary["latest_launch_state"]["paper_apply_allowed_now"] is False
    assert summary["launch_status"] == "research_ready_waiting_for_fresh_signal"
    assert summary["launch_next_blocker"] == "current_fresh_signal"
    assert summary["next_blocker"] == "current_fresh_signal"
    assert summary["fresh_signal"]["seen_during_watch"] is False
    assert summary["fresh_signal_available"] is False
    assert summary["paper_apply"]["seen_during_watch"] is False
    assert summary["paper_apply_available"] is False
    assert summary["quote_progress"]["progress_state"] == "progressing"
    brief = summary["launch_shadow_watch_brief"]
    assert brief["status"] == summary["status"]
    assert brief["generated_at_utc"].endswith("+00:00")
    assert brief["generated_at_kst"].endswith("+09:00")
    assert brief["launch_status"] == "research_ready_waiting_for_fresh_signal"
    assert brief["next_blocker"] == "current_fresh_signal"
    assert brief["quote_progress"]["progress_state"] == "progressing"
    assert brief["fresh_signal"]["available"] is False
    assert brief["paper_apply"]["available"] is False
    assert brief["paper_apply"]["allowed_now"] is False
    assert brief["paper_only_rehearsal"]["status"] == "armed_waiting_for_fresh_signal"
    assert brief["paper_only_rehearsal"]["system_ready"] is True
    assert brief["paper_only_rehearsal"]["armed"] is True
    assert brief["execution_parity"]["missing_samples"] == 20
    assert brief["signal_monitor"]["interval_seconds"] == 300.0
    assert brief["signal_monitor"]["capped_to_fresh_signal_window"] is True
    assert "next_monitor_after_utc" in brief["signal_monitor"]
    assert "next_monitor_after_kst" in brief["signal_monitor"]
    assert brief["operator_next_actions"]["operator_decisions_are_manual_only"] is True
    assert brief["operator_next_actions"]["paper_apply_is_manual_only"] is True
    assert brief["operator_next_actions"]["auto_decision_allowed"] is False
    assert brief["operator_next_actions"]["auto_apply_allowed"] is False
    assert brief["operator_next_actions"]["order_submission_allowed"] is False
    assert brief["operator_next_actions"]["no_live_order_sent"] is True
    assert isinstance(brief["operator_next_actions"]["manual_action_cards"], list)
    assert isinstance(brief["operator_next_actions"]["wait_action_cards"], list)
    assert isinstance(brief["operator_next_actions"]["dependency_blocked_cards"], list)
    assert brief["operator_next_actions"]["manual_batch"]["auto_decision_allowed"] is False
    assert brief["operator_next_actions"]["manual_batch"]["order_submission_allowed"] is False
    assert brief["operator_next_actions"]["manual_batch"]["no_live_order_sent"] is True
    assert "status" in brief["operator_next_actions"]["manual_batch"]
    assert "primary_next_step" in brief["operator_next_actions"]["manual_batch"]
    assert isinstance(brief["operator_next_actions"]["manual_batch"]["batch_order"], list)
    review_file_rollup = brief["operator_next_actions"]["manual_batch"]["review_file_rollup"]
    assert "status" in review_file_rollup
    assert "blocked_file_count" in review_file_rollup
    assert "draft_contract_failed_file_count" in review_file_rollup
    assert isinstance(review_file_rollup["draft_contract_blockers"], list)
    assert isinstance(review_file_rollup["primary_blocked_draft_contract_blockers"], list)
    assert "status_placeholder_failed_file_count" in review_file_rollup
    assert isinstance(review_file_rollup["primary_blocked_status_blockers"], list)
    assert isinstance(review_file_rollup["completion_cli_supplied_fields_pending"], list)
    assert isinstance(review_file_rollup["completion_cli_fixed_fields"], list)
    assert isinstance(
        review_file_rollup["completion_cli_operator_placeholder_fields"], list
    )
    assert isinstance(review_file_rollup["completion_cli_field_mapping"], dict)
    assert review_file_rollup["template_like_fields_are_cli_supplied"] is True
    assert review_file_rollup["template_like_fields_scope"] == (
        "informational_completion_cli_inputs_not_review_file_blockers"
    )
    assert review_file_rollup["review_file_blocks_manual_dry_run"] is False
    assert review_file_rollup["review_file_manual_dry_run_blocker"] is None
    assert isinstance(review_file_rollup["review_file_manual_dry_run_next_action"], str)
    assert review_file_rollup["review_file_manual_dry_run_blocker_scope"] == (
        "review_file_completion_contract_only_command_placeholders_checked_separately"
    )
    assert "quality_failed_file_count" in review_file_rollup
    assert "rationale_quality_failed_file_count" in review_file_rollup
    assert "quality_pending_basic_input_file_count" in review_file_rollup
    assert "rationale_quality_pending_basic_input_file_count" in review_file_rollup
    assert "reviewed_at_quality_failed_file_count" in review_file_rollup
    assert "reviewed_at_quality_pending_basic_input_file_count" in review_file_rollup
    assert isinstance(review_file_rollup["quality_blockers"], list)
    assert isinstance(review_file_rollup["pending_quality_blockers"], list)
    assert isinstance(review_file_rollup["reviewed_at_quality_blockers"], list)
    assert isinstance(review_file_rollup["pending_reviewed_at_quality_blockers"], list)
    assert isinstance(review_file_rollup["primary_blocked_quality_blockers"], list)
    assert isinstance(
        review_file_rollup["primary_blocked_pending_quality_blockers"], list
    )
    assert isinstance(
        review_file_rollup["primary_blocked_reviewed_at_quality_blockers"], list
    )
    assert isinstance(
        review_file_rollup["primary_blocked_pending_reviewed_at_quality_blockers"],
        list,
    )
    assert isinstance(review_file_rollup["blocked_review_reports"], list)
    assert all(
        item["order_submission_allowed"] is False
        for item in review_file_rollup["blocked_review_reports"]
    )
    assert all(
        isinstance(item["rationale_quality"], dict)
        for item in review_file_rollup["blocked_review_reports"]
    )
    assert all(
        isinstance(item["draft_contract_quality"], dict)
        for item in review_file_rollup["blocked_review_reports"]
    )
    assert all(
        isinstance(item["draft_contract_blockers_active"], list)
        for item in review_file_rollup["blocked_review_reports"]
    )
    assert all(
        isinstance(item["status_quality"], dict)
        for item in review_file_rollup["blocked_review_reports"]
    )
    assert all(
        isinstance(item["status_blockers_active"], list)
        for item in review_file_rollup["blocked_review_reports"]
    )
    assert all(
        isinstance(item["quality_blockers_active"], list)
        for item in review_file_rollup["blocked_review_reports"]
    )
    assert all(
        isinstance(item["reviewed_at_quality"], dict)
        for item in review_file_rollup["blocked_review_reports"]
    )
    assert all(
        isinstance(item["reviewed_at_quality_blockers_active"], list)
        for item in review_file_rollup["blocked_review_reports"]
    )
    assert review_file_rollup["write_allowed_now"] is False
    assert review_file_rollup["order_submission_allowed"] is False
    assert review_file_rollup["no_live_order_sent"] is True
    primary_batch = brief["operator_next_actions"]["manual_batch"]["primary_next_step"]
    if primary_batch:
        assert "review_file_state" in primary_batch
        assert primary_batch["review_file_state"]["write_allowed_now"] is False
        assert primary_batch["review_file_state"]["order_submission_allowed"] is False
        assert primary_batch["review_file_state"]["auto_decision_allowed"] is False
        assert primary_batch["review_file_state"]["no_live_order_sent"] is True
        assert primary_batch["safe_default_decision"] == "reject"
        assert primary_batch["dry_run_before_write_required"] is True
        assert primary_batch["write_requires_operator_confirmation"] is True
        assert len(primary_batch["decision_command_options"]) == 2
        assert "--dry-run" in primary_batch["safe_default_dry_run_command"]
        assert "--write-summary" in primary_batch["safe_default_write_command"]
        accept_command = next(
            option
            for option in primary_batch["decision_command_options"]
            if option["decision"] == "accept"
        )
        reject_command = next(
            option
            for option in primary_batch["decision_command_options"]
            if option["decision"] == "reject"
        )
        assert accept_command["operator_input_contract"]["status"] == "operator_inputs_required"
        assert reject_command["operator_input_contract"]["status"] == "operator_inputs_required"
        assert "<operator_name_or_initials>" in accept_command["operator_input_contract"][
            "required_placeholder_tokens"
        ]
        assert "<operator_name_or_initials>" in reject_command["operator_input_contract"][
            "required_placeholder_tokens"
        ]
        assert all(
            "reject_or_hold_rationale" not in token
            for token in accept_command["operator_input_contract"][
                "required_placeholder_tokens"
            ]
        )
        assert all(
            "accept_rationale" not in token
            for token in reject_command["operator_input_contract"][
                "required_placeholder_tokens"
            ]
        )
        assert accept_command["command_safety_summary"]["status"] == (
            "operator_decision_command_waiting_for_operator_inputs"
        )
        assert reject_command["command_safety_summary"]["status"] == (
            "operator_decision_command_waiting_for_operator_inputs"
        )
        assert accept_command["command_safety_summary"]["structural_blockers"] == []
        assert reject_command["command_safety_summary"]["structural_blockers"] == []
        assert accept_command["command_safety_summary"]["dry_run_has_dry_run_flag"] is True
        assert accept_command["command_safety_summary"]["write_has_write_summary_flag"] is True
        assert accept_command["command_safety_summary"]["dry_run_has_backup_dir"] is True
        assert accept_command["command_safety_summary"]["write_has_backup_dir"] is True
        assert accept_command["command_safety_summary"]["live_flag_present"] is False
        assert "dry_run_command_has_unresolved_placeholder" in accept_command[
            "command_safety_summary"
        ]["operator_input_blockers"]
        assert "write_command_has_unresolved_placeholder" in reject_command[
            "command_safety_summary"
        ]["operator_input_blockers"]
        assert accept_command["dry_run_command_executable_now"] is False
        assert reject_command["dry_run_command_executable_now"] is False
        rollup = brief["operator_next_actions"]["manual_batch"]["command_safety_rollup"]
        assert rollup["status"] == "operator_review_batch_waiting_for_operator_inputs"
        assert rollup["next_safety_action"] == "replace_placeholders_before_manual_dry_run"
        assert rollup["structural_blocker_count"] == 0
        assert rollup["operator_input_blocker_count"] >= 1
        assert rollup["live_flag_count"] == 0
        assert rollup["blocked_by_safety_option_count"] == 0
        assert rollup["waiting_for_operator_input_option_count"] >= 1
        assert rollup["write_allowed_now"] is False
        assert "effective_next_safety_action" in rollup
        assert "review_file_blocks_manual_dry_run" in rollup
        assert rollup["effective_ready_for_manual_dry_run_option_count"] <= rollup[
            "ready_for_manual_dry_run_option_count"
        ]
        assert (
            rollup["effective_safe_default_dry_run_executable_now"]
            <= rollup["safe_default_dry_run_executable_now"]
        )
        assert rollup["no_live_order_sent"] is True
        input_rollup = brief["operator_next_actions"]["manual_batch"]["operator_input_rollup"]
        assert input_rollup["status"] == "operator_inputs_required"
        assert input_rollup["next_operator_action"] == (
            "choose_accept_or_reject_then_replace_reviewer_and_selected_rationale_placeholders"
        )
        assert input_rollup["reviewer_placeholder_required"] is True
        assert "<operator_name_or_initials>" in input_rollup["common_placeholder_tokens"]
        assert input_rollup["accept_rationale_placeholder_count"] >= 1
        assert input_rollup["reject_rationale_placeholder_count"] >= 1
        assert input_rollup["options_requiring_input_count"] >= 1
        assert input_rollup["unique_placeholder_count_scope"] == (
            "union_across_all_decision_options_not_single_selected_decision"
        )
        assert input_rollup["selected_decision_placeholder_count_scope"] == (
            "after_operator_chooses_accept_or_reject"
        )
        assert input_rollup["primary_safe_default_decision"] == "reject"
        assert input_rollup["primary_safe_default_placeholder_count"] >= 1
        assert input_rollup["selected_decision_min_placeholder_count"] <= input_rollup[
            "unique_placeholder_count"
        ]
        assert input_rollup["operator_only_needs_one_decision_rationale"] is True
        assert input_rollup["selected_decision_operator_action"] == (
            "choose_one_decision_then_replace_reviewer_and_that_decision_rationale_only"
        )
        assert input_rollup["primary_decision_placeholder_count_by_decision"][
            "accept"
        ] >= 1
        assert input_rollup["primary_decision_placeholder_count_by_decision"][
            "reject"
        ] >= 1
        guide_by_type = {
            item["input_type"]: item
            for item in input_rollup["placeholder_resolution_guide"]
        }
        assert guide_by_type["reviewer"]["required_value_rule"] == (
            "replace_with_operator_name_or_initials"
        )
        assert guide_by_type["accept_rationale"]["minimum_rationale_chars"] == 30
        assert guide_by_type["accept_rationale"]["minimum_evidence_anchors"] == 1
        assert "acceptance_does_not_enable_live_or_tiny_canary" in guide_by_type[
            "accept_rationale"
        ]["quality_requirements"]
        assert guide_by_type["reject_or_hold_rationale"]["minimum_rationale_chars"] == 30
        assert guide_by_type["reject_or_hold_rationale"]["minimum_evidence_anchors"] == 1
        assert "keeps_candidate_or_route_blocked" in guide_by_type[
            "reject_or_hold_rationale"
        ]["quality_requirements"]
        assert input_rollup["write_allowed_now"] is False
        assert input_rollup["reviewed_at_value"] == "now"
        assert isinstance(input_rollup["completion_cli_fixed_fields"], list)
        assert isinstance(input_rollup["completion_cli_operator_placeholder_fields"], list)
        assert isinstance(input_rollup["completion_cli_field_mapping"], dict)
        assert "reviewer" in input_rollup["operator_actionable_cli_fields"]
        assert "rationale" in input_rollup["operator_actionable_cli_fields"]
        assert input_rollup["no_live_order_sent"] is True
        execution_checklist = brief["operator_next_actions"]["manual_batch"][
            "operator_execution_checklist"
        ]
        assert execution_checklist["status"] == (
            "blocked_before_manual_dry_run_waiting_for_operator_inputs"
        )
        assert execution_checklist["current_step"] == "replace_placeholders"
        assert execution_checklist["current_blocker"] == "operator_inputs_required"
        assert execution_checklist["requires_sequential_execution"] is True
        assert execution_checklist["dry_run_before_write_required"] is True
        assert execution_checklist["write_allowed_now"] is False
        assert execution_checklist["review_file_rollup_status"]
        assert execution_checklist["review_file_next_action"]
        assert len(execution_checklist["steps"]) == 8
        assert execution_checklist["steps"][1]["status"] == "blocked_open"
        placeholder_step = execution_checklist["steps"][1]
        assert placeholder_step["required_placeholder_token_scope"] == (
            "union_across_all_decision_options_not_single_selected_decision"
        )
        assert placeholder_step["selected_decision_placeholder_count_scope"] == (
            "after_operator_chooses_accept_or_reject"
        )
        assert placeholder_step["safe_default_decision"] == "reject"
        assert placeholder_step["safe_default_required_placeholder_count"] == 2
        assert placeholder_step["operator_only_needs_one_decision_rationale"] is True
        assert placeholder_step["selected_decision_operator_action"] == (
            "choose_one_decision_then_replace_reviewer_and_that_decision_rationale_only"
        )
        assert placeholder_step["selected_decision_placeholder_count_by_decision"][
            "accept"
        ] == 2
        assert placeholder_step["selected_decision_placeholder_count_by_decision"][
            "reject"
        ] == 2
        assert execution_checklist["steps"][2]["name"] == (
            "verify_operator_review_file_completion_contract"
        )
        assert "completion_cli_supplied_fields_pending" in execution_checklist["steps"][2]
        assert execution_checklist["steps"][2][
            "template_like_fields_are_cli_supplied"
        ] is True
        assert execution_checklist["steps"][2]["order_submission_allowed"] is False
        assert execution_checklist["steps"][3]["name"] == "run_selected_manual_dry_run"
        assert execution_checklist["steps"][3]["status"] in {
            "blocked_until_operator_inputs_complete",
            "blocked_until_review_file_inputs_complete",
            "ready",
            "blocked_until_command_safety_repaired",
            "blocked_until_operator_review_batch_exists",
        }
        assert execution_checklist["no_live_order_sent"] is True
        assert primary_batch["operator_input_contract"]["status"] == "operator_inputs_required"
        assert "<operator_name_or_initials>" in primary_batch["operator_input_contract"][
            "required_placeholder_tokens"
        ]
        assert primary_batch["operator_input_contract"]["unresolved_placeholder_count"] >= 1
        assert (
            primary_batch["operator_input_contract"]["operator_sequence"].index(
                "verify_operator_review_file_completion_contract"
            )
            < primary_batch["operator_input_contract"]["operator_sequence"].index(
                "run_matching_dry_run_command"
            )
        )
        assert primary_batch["operator_input_contract"][
            "safe_default_dry_run_command_executable_now"
        ] is False
        assert primary_batch["operator_input_contract"]["write_allowed_now"] is False
        assert all(
            option["order_submission_allowed"] is False
            for option in primary_batch["decision_command_options"]
        )
        assert brief["operator_next_actions"]["manual_batch"]["batch_order"][0]["step"] == 1
    assert brief["safety_authority"]["scope"] == "paper_only_shadow_watch_no_live_orders"
    assert brief["safety_authority"]["authority"] == "paper_only_no_live_authority_change"
    assert brief["safety_authority"]["live_order_submission_allowed"] is False
    assert brief["safety_authority"]["order_submission_allowed"] is False
    assert brief["safety_authority"]["tiny_canary_allowed"] is False
    assert brief["safety_authority"]["full_live_allowed"] is False
    assert brief["safety_authority"]["auto_decision_allowed"] is False
    assert brief["safety_authority"]["auto_apply_allowed"] is False
    assert brief["safety_authority"]["operator_decisions_are_manual_only"] is True
    assert brief["safety_authority"]["paper_apply_is_manual_only"] is True
    assert brief["safety_authority"]["forbidden_action_count"] >= 1
    assert brief["safety_authority"]["forbidden_actions"][0]["allowed"] is False
    assert brief["safety_authority"]["live_violation_count"] == 0
    assert brief["safety_authority"]["no_live_order_sent"] is True
    assert {
        item["wait_type"] for item in brief["operator_next_actions"]["wait_action_cards"]
    } >= {"signal", "execution_dependency"}
    assert brief["dependency_unlock_plan"]["primary_realtime_gate"] == "current_fresh_signal"
    assert "current_fresh_signal" in brief["dependency_unlock_plan"][
        "first_paper_row_missing_dependencies"
    ]
    assert brief["no_live_order_sent"] is True
    assert summary["completed_iterations"] == 2
    assert summary["no_live_order_sent"] is True
    assert summary["progress"]["quote_observed_delta"] == 2
    assert summary["progress"]["quote_distinct_hours_delta"] == 1
    assert summary["progress"]["fresh_signal_seen"] is False
    assert summary["progress"]["paper_only_rehearsal_statuses_seen"] == ["armed_waiting_for_fresh_signal"]
    assert summary["progress"]["paper_only_rehearsal_armed_seen"] is True
    assert summary["progress"]["paper_only_rehearsal_available_seen"] is False
    assert summary["progress"]["paper_only_rehearsal_first_completed_seen"] is False
    assert summary["progress"]["paper_only_max_substitution_ready_seen"] is True
    assert summary["launch_week_plan"][0]["objective"] == "fresh_signal_monitor_and_quote_microstructure_collection"
    assert summary["launch_week_plan"][0]["command"] == "capture"
    assert len(calls) == 2
    assert calls[0]["quote_samples_per_tick"] == 2
    assert calls[0]["force_quote_sample"] is False
    assert calls[0]["adaptive_quote_cadence"] is True
    assert calls[0]["historical_evidence_replay"] is True
    assert calls[0]["refresh_market_data_before_run"] is True
    assert calls[0]["historical_lifecycle_replay"] is True
    assert calls[0]["canary_risk_caps_path"] == tmp_path / "canary_caps.json"
    assert calls[0]["shadow_runtime_required_hours"] == 0.0
    assert calls[0]["shadow_runtime_observed_hours"] >= 0.0
    assert sleeps == [0.0]
    latest_json = tmp_path / "watch" / "latest.json"
    latest_md = tmp_path / "watch" / "latest.md"
    assert latest_json.exists()
    assert latest_md.exists()
    payload = json.loads(latest_json.read_text(encoding="utf-8"))
    assert payload["latest_run"]["launch_readiness"]["next_blocker"]["gate"] == "current_fresh_signal"
    assert payload["latest_launch_state"]["next_blocker_gate"] == "current_fresh_signal"
    assert payload["latest_launch_state"]["fresh_signal_available_seen"] is False
    assert payload["latest_launch_state"]["paper_apply_available_seen"] is False
    assert payload["latest_launch_state"]["paper_apply_allowed_now"] is False
    assert payload["launch_status"] == "research_ready_waiting_for_fresh_signal"
    assert payload["next_blocker"] == "current_fresh_signal"
    assert payload["fresh_signal"]["seen_during_watch"] is False
    assert payload["paper_apply_available"] is False
    assert payload["quote_progress"]["progress_state"] == "progressing"
    assert payload["launch_shadow_watch_brief"]["status"] == payload["status"]
    assert payload["launch_shadow_watch_brief"]["launch_status"] == (
        "research_ready_waiting_for_fresh_signal"
    )
    assert payload["launch_shadow_watch_brief"]["next_blocker"] == "current_fresh_signal"
    assert payload["launch_shadow_watch_brief"]["generated_at_utc"].endswith("+00:00")
    assert payload["launch_shadow_watch_brief"]["generated_at_kst"].endswith("+09:00")
    assert payload["launch_shadow_watch_brief"]["fresh_signal"]["available"] is False
    assert payload["launch_shadow_watch_brief"]["fresh_signal"][
        "signal_absence_primary_cause"
    ] == "expected_sparse_signal_wait_within_recent_add_cadence"
    assert payload["launch_shadow_watch_brief"]["fresh_signal"]["signal_absence_class"] == (
        "healthy_sparse_cadence_wait"
    )
    assert payload["launch_shadow_watch_brief"]["fresh_signal"][
        "signal_pipeline_issue_suspected"
    ] is False
    assert payload["launch_shadow_watch_brief"]["fresh_signal"][
        "cause_partition_status"
    ] == "healthy_sparse_runtime_wait"
    assert payload["launch_shadow_watch_brief"]["paper_apply"]["allowed_now"] is False
    assert payload["launch_shadow_watch_brief"]["paper_only_rehearsal"]["system_ready"] is True
    assert payload["launch_shadow_watch_brief"]["execution_parity"]["missing_samples"] == 20
    assert payload["launch_shadow_watch_brief"]["signal_monitor"]["interval_seconds"] == 300.0
    assert payload["launch_shadow_watch_brief"]["signal_monitor"][
        "capped_to_fresh_signal_window"
    ] is True
    assert "next_monitor_after_utc" in payload["launch_shadow_watch_brief"]["signal_monitor"]
    assert "next_monitor_after_kst" in payload["launch_shadow_watch_brief"]["signal_monitor"]
    assert payload["launch_shadow_watch_brief"]["operator_next_actions"][
        "operator_decisions_are_manual_only"
    ] is True
    assert payload["launch_shadow_watch_brief"]["operator_next_actions"][
        "paper_apply_is_manual_only"
    ] is True
    assert payload["launch_shadow_watch_brief"]["operator_next_actions"][
        "order_submission_allowed"
    ] is False
    assert payload["launch_shadow_watch_brief"]["operator_next_actions"]["no_live_order_sent"] is True
    assert isinstance(
        payload["launch_shadow_watch_brief"]["operator_next_actions"]["manual_action_cards"],
        list,
    )
    assert isinstance(
        payload["launch_shadow_watch_brief"]["operator_next_actions"]["wait_action_cards"],
        list,
    )
    assert payload["launch_shadow_watch_brief"]["operator_next_actions"]["manual_batch"][
        "auto_decision_allowed"
    ] is False
    assert payload["launch_shadow_watch_brief"]["operator_next_actions"]["manual_batch"][
        "order_submission_allowed"
    ] is False
    assert payload["launch_shadow_watch_brief"]["operator_next_actions"]["manual_batch"][
        "no_live_order_sent"
    ] is True
    assert "primary_next_step" in payload["launch_shadow_watch_brief"]["operator_next_actions"][
        "manual_batch"
    ]
    payload_review_file_rollup = payload["launch_shadow_watch_brief"]["operator_next_actions"][
        "manual_batch"
    ]["review_file_rollup"]
    assert "status" in payload_review_file_rollup
    assert "blocked_file_count" in payload_review_file_rollup
    assert "draft_contract_failed_file_count" in payload_review_file_rollup
    assert isinstance(payload_review_file_rollup["draft_contract_blockers"], list)
    assert isinstance(
        payload_review_file_rollup["primary_blocked_draft_contract_blockers"], list
    )
    assert "status_placeholder_failed_file_count" in payload_review_file_rollup
    assert isinstance(
        payload_review_file_rollup["primary_blocked_status_blockers"], list
    )
    assert isinstance(
        payload_review_file_rollup["completion_cli_supplied_fields_pending"], list
    )
    assert isinstance(payload_review_file_rollup["completion_cli_fixed_fields"], list)
    assert isinstance(
        payload_review_file_rollup["completion_cli_operator_placeholder_fields"], list
    )
    assert isinstance(payload_review_file_rollup["completion_cli_field_mapping"], dict)
    assert payload_review_file_rollup["template_like_fields_are_cli_supplied"] is True
    assert payload_review_file_rollup["template_like_fields_scope"] == (
        "informational_completion_cli_inputs_not_review_file_blockers"
    )
    assert payload_review_file_rollup["review_file_blocks_manual_dry_run"] is False
    assert payload_review_file_rollup["review_file_manual_dry_run_blocker"] is None
    assert isinstance(
        payload_review_file_rollup["review_file_manual_dry_run_next_action"], str
    )
    assert payload_review_file_rollup["review_file_manual_dry_run_blocker_scope"] == (
        "review_file_completion_contract_only_command_placeholders_checked_separately"
    )
    assert "quality_failed_file_count" in payload_review_file_rollup
    assert "rationale_quality_failed_file_count" in payload_review_file_rollup
    assert "quality_pending_basic_input_file_count" in payload_review_file_rollup
    assert (
        "rationale_quality_pending_basic_input_file_count"
        in payload_review_file_rollup
    )
    assert "reviewed_at_quality_failed_file_count" in payload_review_file_rollup
    assert (
        "reviewed_at_quality_pending_basic_input_file_count"
        in payload_review_file_rollup
    )
    assert isinstance(payload_review_file_rollup["quality_blockers"], list)
    assert isinstance(payload_review_file_rollup["pending_quality_blockers"], list)
    assert isinstance(payload_review_file_rollup["reviewed_at_quality_blockers"], list)
    assert isinstance(
        payload_review_file_rollup["pending_reviewed_at_quality_blockers"], list
    )
    assert isinstance(
        payload_review_file_rollup["primary_blocked_quality_blockers"], list
    )
    assert isinstance(
        payload_review_file_rollup["primary_blocked_pending_quality_blockers"], list
    )
    assert isinstance(
        payload_review_file_rollup["primary_blocked_reviewed_at_quality_blockers"],
        list,
    )
    assert isinstance(
        payload_review_file_rollup[
            "primary_blocked_pending_reviewed_at_quality_blockers"
        ],
        list,
    )
    assert isinstance(payload_review_file_rollup["blocked_review_reports"], list)
    assert all(
        item["order_submission_allowed"] is False
        for item in payload_review_file_rollup["blocked_review_reports"]
    )
    assert all(
        isinstance(item["rationale_quality"], dict)
        for item in payload_review_file_rollup["blocked_review_reports"]
    )
    assert all(
        isinstance(item["draft_contract_quality"], dict)
        for item in payload_review_file_rollup["blocked_review_reports"]
    )
    assert all(
        isinstance(item["draft_contract_blockers_active"], list)
        for item in payload_review_file_rollup["blocked_review_reports"]
    )
    assert all(
        isinstance(item["status_quality"], dict)
        for item in payload_review_file_rollup["blocked_review_reports"]
    )
    assert all(
        isinstance(item["status_blockers_active"], list)
        for item in payload_review_file_rollup["blocked_review_reports"]
    )
    assert all(
        isinstance(item["quality_blockers_active"], list)
        for item in payload_review_file_rollup["blocked_review_reports"]
    )
    assert all(
        isinstance(item["reviewed_at_quality"], dict)
        for item in payload_review_file_rollup["blocked_review_reports"]
    )
    assert all(
        isinstance(item["reviewed_at_quality_blockers_active"], list)
        for item in payload_review_file_rollup["blocked_review_reports"]
    )
    assert payload_review_file_rollup["write_allowed_now"] is False
    assert payload_review_file_rollup["order_submission_allowed"] is False
    assert payload_review_file_rollup["no_live_order_sent"] is True
    assert isinstance(
        payload["launch_shadow_watch_brief"]["operator_next_actions"]["manual_batch"][
            "batch_order"
        ],
        list,
    )
    payload_primary_batch = payload["launch_shadow_watch_brief"]["operator_next_actions"][
        "manual_batch"
    ]["primary_next_step"]
    if payload_primary_batch:
        assert "review_file_state" in payload_primary_batch
        assert payload_primary_batch["review_file_state"]["write_allowed_now"] is False
        assert (
            payload_primary_batch["review_file_state"]["order_submission_allowed"] is False
        )
        assert payload_primary_batch["review_file_state"]["auto_decision_allowed"] is False
        assert payload_primary_batch["review_file_state"]["no_live_order_sent"] is True
        assert payload_primary_batch["safe_default_decision"] == "reject"
        assert payload_primary_batch["dry_run_before_write_required"] is True
        assert payload_primary_batch["write_requires_operator_confirmation"] is True
        assert len(payload_primary_batch["decision_command_options"]) == 2
        assert "--dry-run" in payload_primary_batch["safe_default_dry_run_command"]
        assert "--write-summary" in payload_primary_batch["safe_default_write_command"]
        payload_accept_command = next(
            option
            for option in payload_primary_batch["decision_command_options"]
            if option["decision"] == "accept"
        )
        payload_reject_command = next(
            option
            for option in payload_primary_batch["decision_command_options"]
            if option["decision"] == "reject"
        )
        assert payload_accept_command["operator_input_contract"]["status"] == (
            "operator_inputs_required"
        )
        assert payload_reject_command["operator_input_contract"]["status"] == (
            "operator_inputs_required"
        )
        assert payload_accept_command["command_safety_summary"]["status"] == (
            "operator_decision_command_waiting_for_operator_inputs"
        )
        assert payload_accept_command["command_safety_summary"]["structural_blockers"] == []
        assert payload_accept_command["command_safety_summary"]["live_flag_present"] is False
        assert payload_accept_command["command_safety_summary"][
            "dry_run_has_dry_run_flag"
        ] is True
        assert payload_accept_command["command_safety_summary"][
            "write_has_write_summary_flag"
        ] is True
        assert payload_accept_command["dry_run_command_executable_now"] is False
        assert payload_reject_command["dry_run_command_executable_now"] is False
        payload_rollup = payload["launch_shadow_watch_brief"]["operator_next_actions"][
            "manual_batch"
        ]["command_safety_rollup"]
        assert payload_rollup["status"] == "operator_review_batch_waiting_for_operator_inputs"
        assert payload_rollup["structural_blocker_count"] == 0
        assert payload_rollup["live_flag_count"] == 0
        assert payload_rollup["write_allowed_now"] is False
        assert "effective_next_safety_action" in payload_rollup
        assert "review_file_blocks_manual_dry_run" in payload_rollup
        assert payload_rollup["effective_ready_for_manual_dry_run_option_count"] <= (
            payload_rollup["ready_for_manual_dry_run_option_count"]
        )
        assert payload_rollup["effective_safe_default_dry_run_executable_now"] <= (
            payload_rollup["safe_default_dry_run_executable_now"]
        )
        assert payload_rollup["no_live_order_sent"] is True
        payload_input_rollup = payload["launch_shadow_watch_brief"]["operator_next_actions"][
            "manual_batch"
        ]["operator_input_rollup"]
        assert payload_input_rollup["status"] == "operator_inputs_required"
        assert payload_input_rollup["reviewer_placeholder_required"] is True
        assert "<operator_name_or_initials>" in payload_input_rollup[
            "common_placeholder_tokens"
        ]
        assert payload_input_rollup["unique_placeholder_count_scope"] == (
            "union_across_all_decision_options_not_single_selected_decision"
        )
        assert payload_input_rollup["selected_decision_placeholder_count_scope"] == (
            "after_operator_chooses_accept_or_reject"
        )
        assert payload_input_rollup["primary_safe_default_decision"] == "reject"
        assert payload_input_rollup["primary_safe_default_placeholder_count"] >= 1
        assert payload_input_rollup["selected_decision_min_placeholder_count"] <= (
            payload_input_rollup["unique_placeholder_count"]
        )
        assert payload_input_rollup["operator_only_needs_one_decision_rationale"] is True
        assert payload_input_rollup["selected_decision_operator_action"] == (
            "choose_one_decision_then_replace_reviewer_and_that_decision_rationale_only"
        )
        assert payload_input_rollup["primary_decision_placeholder_count_by_decision"][
            "accept"
        ] >= 1
        assert payload_input_rollup["primary_decision_placeholder_count_by_decision"][
            "reject"
        ] >= 1
        payload_guide_by_type = {
            item["input_type"]: item
            for item in payload_input_rollup["placeholder_resolution_guide"]
        }
        assert payload_guide_by_type["reviewer"]["required_value_rule"] == (
            "replace_with_operator_name_or_initials"
        )
        assert payload_guide_by_type["accept_rationale"]["minimum_rationale_chars"] == 30
        assert payload_guide_by_type["reject_or_hold_rationale"][
            "minimum_evidence_anchors"
        ] == 1
        assert payload_input_rollup["write_allowed_now"] is False
        assert payload_input_rollup["reviewed_at_value"] == "now"
        assert isinstance(payload_input_rollup["completion_cli_fixed_fields"], list)
        assert isinstance(
            payload_input_rollup["completion_cli_operator_placeholder_fields"], list
        )
        assert isinstance(payload_input_rollup["completion_cli_field_mapping"], dict)
        assert "reviewer" in payload_input_rollup["operator_actionable_cli_fields"]
        assert "rationale" in payload_input_rollup["operator_actionable_cli_fields"]
        assert payload_input_rollup["no_live_order_sent"] is True
        payload_execution_checklist = payload["launch_shadow_watch_brief"][
            "operator_next_actions"
        ]["manual_batch"]["operator_execution_checklist"]
        assert payload_execution_checklist["status"] == (
            "blocked_before_manual_dry_run_waiting_for_operator_inputs"
        )
        assert payload_execution_checklist["current_step"] == "replace_placeholders"
        assert payload_execution_checklist["write_allowed_now"] is False
        assert payload_execution_checklist["review_file_rollup_status"]
        assert payload_execution_checklist["review_file_next_action"]
        assert len(payload_execution_checklist["steps"]) == 8
        payload_placeholder_step = payload_execution_checklist["steps"][1]
        assert payload_placeholder_step["required_placeholder_token_scope"] == (
            "union_across_all_decision_options_not_single_selected_decision"
        )
        assert payload_placeholder_step["selected_decision_placeholder_count_scope"] == (
            "after_operator_chooses_accept_or_reject"
        )
        assert payload_placeholder_step["safe_default_decision"] == "reject"
        assert payload_placeholder_step["safe_default_required_placeholder_count"] == 2
        assert (
            payload_placeholder_step["operator_only_needs_one_decision_rationale"]
            is True
        )
        assert payload_placeholder_step["selected_decision_operator_action"] == (
            "choose_one_decision_then_replace_reviewer_and_that_decision_rationale_only"
        )
        assert payload_placeholder_step["selected_decision_placeholder_count_by_decision"][
            "accept"
        ] == 2
        assert payload_placeholder_step["selected_decision_placeholder_count_by_decision"][
            "reject"
        ] == 2
        assert payload_execution_checklist["steps"][2]["name"] == (
            "verify_operator_review_file_completion_contract"
        )
        assert (
            "completion_cli_supplied_fields_pending"
            in payload_execution_checklist["steps"][2]
        )
        assert payload_execution_checklist["steps"][2][
            "template_like_fields_are_cli_supplied"
        ] is True
        assert payload_execution_checklist["steps"][3]["name"] == (
            "run_selected_manual_dry_run"
        )
        assert payload_execution_checklist["no_live_order_sent"] is True
        assert payload_primary_batch["operator_input_contract"]["status"] == (
            "operator_inputs_required"
        )
        assert "<operator_name_or_initials>" in payload_primary_batch[
            "operator_input_contract"
        ]["required_placeholder_tokens"]
        assert (
            payload_primary_batch["operator_input_contract"]["operator_sequence"].index(
                "verify_operator_review_file_completion_contract"
            )
            < payload_primary_batch["operator_input_contract"]["operator_sequence"].index(
                "run_matching_dry_run_command"
            )
        )
        assert payload_primary_batch["operator_input_contract"][
            "safe_default_dry_run_command_executable_now"
        ] is False
        assert payload_primary_batch["operator_input_contract"]["write_allowed_now"] is False
        assert payload["launch_shadow_watch_brief"]["operator_next_actions"]["manual_batch"][
            "batch_order"
        ][0]["step"] == 1
        assert payload["launch_shadow_watch_brief"]["operator_next_actions"]["manual_batch"][
            "batch_order"
        ][0]["decision_command_options"][0]["operator_input_contract"]["status"] == (
            "operator_inputs_required"
        )
    assert payload["launch_shadow_watch_brief"]["safety_authority"]["scope"] == (
        "paper_only_shadow_watch_no_live_orders"
    )
    assert payload["launch_shadow_watch_brief"]["safety_authority"][
        "live_order_submission_allowed"
    ] is False
    assert payload["launch_shadow_watch_brief"]["safety_authority"][
        "order_submission_allowed"
    ] is False
    assert payload["launch_shadow_watch_brief"]["safety_authority"][
        "auto_decision_allowed"
    ] is False
    assert payload["launch_shadow_watch_brief"]["safety_authority"]["auto_apply_allowed"] is False
    assert payload["launch_shadow_watch_brief"]["safety_authority"][
        "operator_decisions_are_manual_only"
    ] is True
    assert payload["launch_shadow_watch_brief"]["safety_authority"][
        "paper_apply_is_manual_only"
    ] is True
    assert payload["launch_shadow_watch_brief"]["safety_authority"]["live_violation_count"] == 0
    assert payload["launch_shadow_watch_brief"]["safety_authority"]["no_live_order_sent"] is True
    assert {
        item["wait_type"]
        for item in payload["launch_shadow_watch_brief"]["operator_next_actions"][
            "wait_action_cards"
        ]
    } >= {"signal", "execution_dependency"}
    assert payload["launch_shadow_watch_brief"]["dependency_unlock_plan"][
        "primary_realtime_gate"
    ] == "current_fresh_signal"
    assert payload["launch_shadow_watch_brief"]["no_live_order_sent"] is True
    assert payload["fresh_signal_blocker_diagnostics"]["status"] == "blocked_waiting_for_fresh_signal"
    assert payload["fresh_signal_blocker_diagnostics"]["primary_cause"] == (
        "strategy_abstaining_from_low_quality_soft_contexts"
    )
    assert payload["fresh_signal_blocker_diagnostics"]["signal_stale"] is True
    assert payload["fresh_signal_blocker_diagnostics"]["snapshot_blockers"] == ["signal_stale"]
    assert payload["fresh_signal_blocker_diagnostics"]["signal_absence_primary_cause"] == (
        "expected_sparse_signal_wait_within_recent_add_cadence"
    )
    assert payload["fresh_signal_blocker_diagnostics"]["cause_partition"]["status"] == (
        "healthy_sparse_runtime_wait"
    )
    assert payload["fresh_signal_blocker_diagnostics"]["cause_partition"][
        "runtime_signal_absence"
    ]["healthy_sparse_wait"] is True
    assert payload["fresh_signal_blocker_diagnostics"]["cause_partition"][
        "strategy_design_blocker"
    ]["blocked"] is False
    assert payload["signal_blocker_cause_partition_status"] == "healthy_sparse_runtime_wait"
    assert payload["no_signal_resolution_summary"]["status"] == "healthy_sparse_runtime_wait"
    assert payload["no_signal_resolution_summary"]["root_cause"] == (
        "expected_sparse_signal_wait_within_recent_add_cadence"
    )
    assert payload["no_signal_resolution_summary"]["strategy_candidate_redesign_required"] is False
    assert payload["no_signal_resolution_summary"]["safe_next_action"] == (
        "monitor_fresh_signal_without_forcing_entry"
    )
    assert payload["no_signal_resolution_summary"]["force_signal_allowed"] is False
    assert payload["no_signal_resolution_summary"]["order_submission_allowed"] is False
    assert payload["no_signal_resolution_summary"]["no_live_order_sent"] is True
    assert payload["launch_shadow_watch_brief"]["no_signal_resolution"]["status"] == (
        "healthy_sparse_runtime_wait"
    )
    assert payload["launch_shadow_watch_brief"]["fresh_signal"]["no_signal_root_cause"] == (
        "expected_sparse_signal_wait_within_recent_add_cadence"
    )
    assert payload["signal_absence_primary_cause"] == (
        "expected_sparse_signal_wait_within_recent_add_cadence"
    )
    assert payload["signal_absence_class"] == "healthy_sparse_cadence_wait"
    assert payload["signal_pipeline_issue_suspected"] is False
    assert payload["fresh_signal_blocker_diagnostics"]["signal_pipeline_issue_suspected"] is False
    assert payload["fresh_signal_blocker_diagnostics"]["signal_absence_diagnosis"]["class"] == (
        "healthy_sparse_cadence_wait"
    )
    assert payload["fresh_signal_blocker_diagnostics"]["signal_absence_diagnosis"][
        "force_signal_allowed"
    ] is False
    assert payload["fresh_signal_blocker_diagnostics"]["rejected_soft_context_count"] == 6543
    assert payload["fresh_signal_blocker_diagnostics"]["mc04_broad_relaxation_rejected"] is True
    assert payload["fresh_signal_blocker_diagnostics"]["dominant_primary_issue"] == (
        "soft_confluence_filters_are_dominating_current_no_trade_distribution"
    )
    assert payload["fresh_signal_blocker_diagnostics"]["reason_class_counts"]["soft_candidate"] == 21774
    assert payload["fresh_signal_blocker_diagnostics"]["top_no_trade_reasons"][0]["reason"] == (
        "no_trade_MC12_low_confluence"
    )
    assert payload["launch_shadow_watch_brief"]["fresh_signal"]["top_no_trade_reason"] == (
        "no_trade_MC12_low_confluence"
    )
    assert payload["launch_shadow_watch_brief"]["fresh_signal"][
        "top_no_trade_reason_count"
    ] == 12220
    assert payload["fresh_signal_blocker_diagnostics"]["dominant_no_trade_context"]["reason"] == (
        "MC04_no_clear_first_touch"
    )
    assert payload["launch_shadow_watch_brief"]["fresh_signal"][
        "dominant_no_trade_context_reason"
    ] == "MC04_no_clear_first_touch"
    assert payload["fresh_signal_blocker_diagnostics"]["safe_experiment_backlog"][0]["name"] == (
        "quality_gated_mc12_near_miss_micro_probe"
    )
    assert payload["launch_shadow_watch_brief"]["fresh_signal"]["primary_safe_experiment"] == (
        "quality_gated_mc12_near_miss_micro_probe"
    )
    assert payload["fresh_signal_blocker_diagnostics"]["operator_interpretation"]["status"] == (
        "wait_for_new_walk_forward_evidence_before_relaxing_soft_contexts"
    )
    assert payload["fresh_signal_blocker_diagnostics"]["fresh_signal_resolution_plan"]["status"] == (
        "no_safe_runtime_fix_available"
    )
    assert payload["launch_shadow_watch_brief"]["fresh_signal"][
        "fresh_signal_resolution_status"
    ] == "no_safe_runtime_fix_available"
    assert payload["launch_shadow_watch_brief"]["fresh_signal"]["operator_fixable_now"] is False
    assert (
        payload["fresh_signal_blocker_diagnostics"]["fresh_signal_resolution_plan"][
            "top_no_trade_reason"
        ]["reason"]
        == "no_trade_MC12_low_confluence"
    )
    assert (
        payload["fresh_signal_blocker_diagnostics"]["fresh_signal_resolution_plan"][
            "operator_fixable_now"
        ]
        is False
    )
    assert "force_current_fresh_signal" in payload["fresh_signal_blocker_diagnostics"][
        "fresh_signal_resolution_plan"
    ]["unsafe_shortcuts"]
    assert payload["fresh_signal_blocker_diagnostics"]["safe_operator_next_action"] == (
        "monitor_without_forcing_entry_or_relaxing_low_quality_contexts"
    )
    assert (
        payload["latest_run"]["fresh_signal_blocker_diagnostics"]
        == payload["fresh_signal_blocker_diagnostics"]
    )
    assert payload["paper_only_rehearsal"]["status"] == "armed_waiting_for_fresh_signal"
    assert payload["paper_only_rehearsal"]["system_ready"] is True
    assert payload["paper_only_rehearsal"]["armed"] is True
    assert payload["paper_only_rehearsal"]["remaining_gates"] == [
        "current_fresh_signal",
        "first_real_paper_lifecycle_row",
    ]
    assert payload["paper_only_rehearsal"]["max_substitution_ready"] is True
    assert payload["paper_only_rehearsal"]["substituted_or_prevalidated_gates"] == [
        "historical_quote_replay",
        "historical_lifecycle_proxy",
        "paper_bridge_command_contract",
        "pre_apply_backup_contract",
        "no_live_authority_contract",
    ]
    assert payload["paper_only_rehearsal"]["unresolved_proxy_gates"] == []
    assert payload["latest_run"]["paper_only_rehearsal"] == payload["paper_only_rehearsal"]
    assert payload["signal_monitor"]["recommended_monitor_interval_minutes"] == 5.0
    assert payload["signal_monitor"]["interval_seconds"] == 300.0
    assert payload["signal_monitor"]["capped_to_fresh_signal_window"] is True
    assert payload["signal_monitor"]["monitor_signal_age_alignment"] == (
        "paper_rehearsal_fast_capture_capped_to_fresh_signal_window"
    )
    assert "next_monitor_after_source" in payload["signal_monitor"]
    assert "raw_next_monitor_after_kst" in payload["signal_monitor"]
    assert "covered_next_recheck_after_kst" in payload["signal_monitor"]
    assert payload["signal_monitor"]["no_live_order_sent"] is True
    assert payload["latest_run"]["signal_monitor"] == payload["signal_monitor"]
    assert payload["latest_run"]["quote_cadence_preflight"]["decision"] == "capture_new_utc_hour_for_hour_gate"
    assert payload["progress"]["quote_observed_delta"] == 2
    assert payload["progress"]["execution_parity_collection_status_latest"] == "waiting_for_fresh_signal"
    assert payload["progress"]["execution_parity_events_needed_latest"] == 20
    assert payload["progress"]["execution_parity_events_needed_after_current_apply_latest"] == 20
    assert payload["progress"]["execution_parity_will_credit_current_apply_latest"] is False
    assert payload["progress"]["execution_parity_creditable_actions_latest"] == []
    assert payload["progress"]["execution_parity_non_substitutable_latest"] is True
    assert payload["execution_parity_collection_plan"] == (
        payload["operator_handoff"]["execution_parity_collection_plan"]
    )
    assert payload["execution_parity_status_summary"]["status"] == "waiting_for_fresh_signal"
    assert payload["execution_parity_status_summary"]["eligible_journal_rows"] == 0
    assert payload["execution_parity_status_summary"]["missing_samples"] == 20
    assert payload["execution_parity_status_summary"]["estimated_future_paper_apply_events_needed"] == 20
    assert payload["execution_parity_status_summary"]["non_substitutable"] is True
    assert payload["execution_parity_status_summary"]["no_live_order_sent"] is True
    assert payload["operator_work_queue"]["status"] in {
        "automation_available",
        "automation_and_operator_review_available",
        "automation_available_operator_review_waiting",
        "operator_review_required",
        "operator_review_waiting_for_gate",
        "startable_time_wait_available",
        "waiting_for_scheduled_action",
    }
    assert "operator_review_now_count" in payload["operator_work_queue"]
    assert "operator_review_wait_count" in payload["operator_work_queue"]
    assert payload["operator_review_handoff_summary"]["order_submission_allowed"] is False
    assert payload["operator_review_handoff_summary"]["no_live_order_sent"] is True
    assert payload["launch_blocker_priority_summary"]["status"] == "waiting_for_realtime_evidence"
    assert payload["launch_blocker_priority_summary"]["non_substitutable_problem_count"] == 4
    assert payload["launch_blocker_priority_summary"]["non_substitutable_wait_blocker_count"] == 3
    assert payload["launch_blocker_priority_summary"]["non_substitutable_blocker_count"] == 3
    assert payload["launch_blocker_priority_summary"]["dependency_blocked_count"] == 1
    assert payload["launch_blocker_priority_summary"]["primary_non_substitutable_problem"]["id"] == (
        "current_fresh_signal"
    )
    assert payload["launch_blocker_priority_summary"]["primary_waiting_blocker"]["id"] == "current_fresh_signal"
    assert payload["launch_blocker_priority_summary"]["primary_dependency_blocker"]["id"] == (
        "first_real_paper_lifecycle_row"
    )
    assert payload["launch_blocker_priority_summary"]["order_submission_allowed"] is False
    assert payload["launch_blocker_priority_summary"]["no_live_order_sent"] is True
    assert payload["remaining_work_closure_summary"]["status"] in {
        "automation_continues_operator_and_realtime_gates_remaining",
        "operator_or_realtime_gates_remaining",
        "remaining_work_has_blocked_review_packets",
    }
    assert payload["remaining_work_closure_summary"]["auto_complete_without_future_market_or_operator"] is False
    assert payload["remaining_work_closure_summary"]["dependency_blocked_problem_count"] == 1
    assert payload["remaining_work_closure_summary"]["dependency_blocked_problem_ids"] == [
        "first_real_paper_lifecycle_row"
    ]
    assert payload["remaining_work_closure_summary"]["primary_wait_only_problem"]["id"] == (
        "current_fresh_signal"
    )
    assert payload["remaining_work_closure_summary"]["primary_dependency_blocked_problem"]["id"] == (
        "first_real_paper_lifecycle_row"
    )
    assert payload["remaining_work_closure_summary"]["dependency_unlock_plan"]["status"] == (
        "manual_and_realtime_unlocks_remaining"
    )
    assert payload["remaining_work_closure_summary"]["dependency_unlock_plan"]["primary_unlock_step"][
        "gate"
    ] in {"operator_review_decisions", "current_fresh_signal"}
    assert payload["remaining_work_closure_summary"]["dependency_unlock_plan"]["primary_realtime_unlock_step"][
        "gate"
    ] == "current_fresh_signal"
    assert "current_fresh_signal" in payload["remaining_work_closure_summary"][
        "dependency_unlock_plan"
    ]["first_paper_row_missing_dependencies"]
    assert payload["remaining_work_closure_summary"]["dependency_unlock_plan"][
        "order_submission_allowed"
    ] is False
    assert payload["remaining_work_closure_summary"]["dependency_unlock_plan"][
        "no_live_order_sent"
    ] is True
    assert "safe_useful_automation_now_count" in payload["remaining_work_closure_summary"]
    assert "safe_noop_or_deferred_automation_now_count" in payload["remaining_work_closure_summary"]
    assert isinstance(payload["remaining_work_closure_summary"]["automation_now_usefulness"], list)
    assert "fresh_signal_requires_realtime_market_event" in (
        payload["remaining_work_closure_summary"]["not_auto_completable_reasons"]
    )
    assert "execution_parity_requires_real_reviewed_paper_lifecycle_rows" in (
        payload["remaining_work_closure_summary"]["not_auto_completable_reasons"]
    )
    assert payload["remaining_work_closure_summary"]["order_submission_allowed"] is False
    assert payload["remaining_work_closure_summary"]["no_live_order_sent"] is True
    assert payload["dependency_lanes"] == payload["remaining_work_closure_summary"]["dependency_lanes"]
    assert payload["dependency_lanes"]["order_submission_allowed"] is False
    assert payload["dependency_lanes"]["no_live_order_sent"] is True
    assert (
        payload["actionability_partition"]
        == payload["remaining_work_closure_summary"]["actionability_partition"]
    )
    assert payload["actionability_partition"]["auto_decision_allowed"] is False
    assert payload["actionability_partition"]["order_submission_allowed"] is False
    assert payload["actionability_partition"]["no_live_order_sent"] is True
    assert payload["first_fresh_signal_paper_apply_runbook"]["status"] in {
        "armed_waiting_for_first_fresh_signal",
        "paper_apply_command_safety_blocked",
    }
    assert payload["first_fresh_signal_paper_apply_runbook"]["paper_apply_allowed_now"] is False
    assert payload["first_fresh_signal_paper_apply_runbook"]["auto_apply_allowed"] is False
    assert payload["first_fresh_signal_paper_apply_runbook"]["order_submission_allowed"] is False
    assert payload["first_fresh_signal_paper_apply_runbook"]["no_live_order_sent"] is True
    assert payload["operator_review_decision_aid"]["auto_decision_allowed"] is False
    assert payload["operator_review_decision_aid"]["order_submission_allowed"] is False
    assert payload["operator_review_decision_aid"]["no_live_order_sent"] is True
    assert payload["operator_review_resolution_plan"]["auto_decision_allowed"] is False
    assert payload["operator_review_resolution_plan"]["auto_accept_allowed"] is False
    assert payload["operator_review_resolution_plan"]["auto_reject_allowed"] is False
    assert payload["operator_review_resolution_plan"]["order_submission_allowed"] is False
    assert payload["operator_review_resolution_plan"]["no_live_order_sent"] is True
    assert (
        payload["operator_review_readiness_matrix"]
        == payload["operator_review_resolution_plan"]["readiness_matrix"]
    )
    assert payload["operator_review_readiness_matrix"]["order_submission_allowed"] is False
    assert payload["operator_review_readiness_matrix"]["no_live_order_sent"] is True
    assert (
        payload["manual_batch_handoff"]
        == payload["operator_review_resolution_plan"]["manual_batch_handoff"]
    )
    assert payload["manual_batch_handoff"]["auto_decision_allowed"] is False
    assert payload["manual_batch_handoff"]["order_submission_allowed"] is False
    assert payload["manual_batch_handoff"]["no_live_order_sent"] is True
    assert payload["operator_action_digest"]["status"] in {
        "run_safe_monitoring_and_complete_manual_reviews",
        "run_safe_monitoring",
        "complete_manual_operator_reviews",
        "waiting_on_realtime_or_calendar_gates",
        "repair_command_consistency_before_operator_use",
    }
    assert payload["operator_action_digest"]["next_blocker_gate"] == "current_fresh_signal"
    assert "primary_material_ready_now" in payload["operator_action_digest"]
    assert "primary_material_wait_minutes" in payload["operator_action_digest"]
    assert payload["operator_action_digest"]["safe_auto_command_count"] >= 1
    assert payload["operator_action_digest"]["manual_decision_count"] >= 0
    assert payload["operator_action_digest"]["operator_decisions_are_manual_only"] is True
    assert payload["operator_action_digest"]["paper_apply_is_manual_only"] is True
    assert payload["operator_action_digest"]["auto_decision_allowed"] is False
    assert payload["operator_action_digest"]["auto_apply_allowed"] is False
    assert payload["operator_action_digest"]["order_submission_allowed"] is False
    assert payload["operator_action_digest"]["no_live_order_sent"] is True
    assert payload["gate_substitution_digest"]["status"] == (
        "paper_only_proxy_substitution_complete_realtime_gates_remaining"
    )
    assert payload["gate_substitution_digest"]["max_substitution_ready"] is True
    assert payload["gate_substitution_digest"]["unresolved_proxy_gate_count"] == 0
    assert payload["gate_substitution_digest"]["realtime_wait_count"] >= 1
    assert "current_fresh_signal" in payload["gate_substitution_digest"]["non_substitutable_remaining_gates"]
    assert payload["gate_substitution_digest"]["backtest_substitution_allowed_for_launch_gate"] is False
    assert payload["gate_substitution_digest"]["synthetic_or_backtest_rows_close_realtime_gates"] is False
    assert payload["gate_substitution_digest"]["operator_decision_allowed"] is False
    assert payload["gate_substitution_digest"]["order_submission_allowed"] is False
    assert payload["gate_substitution_digest"]["no_live_order_sent"] is True
    assert payload["gate_eta_digest"]["status"] in {
        "unscheduled_realtime_and_manual_gates_block_paper_apply_eta",
        "unscheduled_realtime_gate_blocks_paper_apply_eta",
        "manual_operator_review_blocks_paper_apply_eta",
        "scheduled_gate_waiting",
    }
    assert payload["gate_eta_digest"]["paper_apply_eta_known"] is False
    assert payload["gate_eta_digest"]["has_unscheduled_realtime_gate"] is True
    assert payload["gate_eta_digest"]["next_unscheduled_gate"] in {
        "current_fresh_signal",
        "first_real_paper_lifecycle_row",
    }
    assert "next_scheduled_event" in payload["gate_eta_digest"]
    assert payload["gate_eta_digest"]["backtest_substitution_allowed_for_launch_gate"] is False
    assert payload["gate_eta_digest"]["synthetic_or_backtest_rows_close_realtime_gates"] is False
    assert payload["gate_eta_digest"]["order_submission_allowed"] is False
    assert payload["gate_eta_digest"]["no_live_order_sent"] is True
    assert payload["launch_progress_scorecard"]["status"] in {
        "paper_only_proxy_complete_realtime_or_manual_gates_open",
        "paper_only_proxy_complete_no_open_scorecard_lanes",
        "paper_apply_manual_review_ready",
    }
    assert payload["launch_progress_scorecard"]["paper_only_research_proxy_complete"] is True
    assert payload["launch_progress_scorecard"]["paper_apply_eta_known"] is False
    assert payload["launch_progress_scorecard"]["ready_for_paper_apply_now"] is False
    assert payload["launch_progress_scorecard"]["ready_for_tiny_canary_or_live"] is False
    assert payload["launch_progress_scorecard"]["auto_decision_allowed"] is False
    assert payload["launch_progress_scorecard"]["auto_apply_allowed"] is False
    assert payload["launch_progress_scorecard"]["order_submission_allowed"] is False
    assert payload["launch_progress_scorecard"]["no_live_order_sent"] is True
    assert "current_fresh_signal" in payload["launch_progress_scorecard"]["blocking_gates"]
    assert payload["launch_progress_scorecard"]["lanes"]["paper_only_proxy"]["complete"] is True
    assert payload["launch_progress_scorecard"]["lanes"]["shadow_runtime"]["complete"] is True
    assert payload["launch_progress_scorecard"]["lanes"]["fresh_signal"]["fresh_signal_available"] is False
    assert payload["launch_progress_scorecard"]["lanes"]["execution_parity"]["missing_samples"] == 20
    assert payload["launch_progress_scorecard"]["critical_path_scorecard"]["status"].startswith(
        "critical_path_blocked_at_"
    )
    assert (
        payload["launch_progress_scorecard"]["critical_path_scorecard"]["next_open_gate"]
        == "current_fresh_signal"
    )
    assert payload["launch_progress_scorecard"]["critical_path_scorecard"]["progress_floor_pct"] == 0.0
    assert (
        payload["launch_progress_scorecard"]["critical_path_scorecard"]["paper_apply_path"]["next_open_gate"]
        == "current_fresh_signal"
    )
    assert (
        payload["launch_progress_scorecard"]["critical_path_scorecard"]["parallel_path"]["next_open_gate"]
        == "microstructure_calendar_day_coverage"
    )
    assert payload["launch_progress_scorecard"]["critical_path_scorecard"]["auto_apply_allowed"] is False
    assert payload["launch_progress_scorecard"]["critical_path_scorecard"]["order_submission_allowed"] is False
    assert payload["launch_progress_scorecard"]["critical_path_scorecard"]["no_live_order_sent"] is True
    assert payload["launch_progress_scorecard"]["complete_lane_count"] >= 2
    assert payload["launch_progress_scorecard"]["measurable_lane_count"] >= 5
    assert payload["launch_execution_matrix"]["status"] in {
        "safe_auto_monitoring_and_manual_reviews_available",
        "safe_auto_monitoring_available",
        "manual_operator_reviews_required",
        "repair_command_consistency_before_operator_use",
    }
    assert payload["launch_execution_matrix"]["urgency_status"] in {
        "overdue_safe_auto_action_ready",
        "safe_auto_action_ready",
        "safe_auto_action_scheduled_future",
        "manual_operator_action_available",
        "repair_required_before_any_operator_use",
    }
    assert "primary_urgency" in payload["launch_execution_matrix"]
    assert payload["launch_execution_matrix"]["effective_urgency_status"] in {
        "overdue_safe_auto_action_ready",
        "safe_auto_action_ready",
        "safe_auto_action_scheduled_future",
        "safe_auto_due_covered_this_iteration_manual_action_available",
        "safe_auto_due_covered_this_iteration_waiting_only",
        "safe_auto_due_covered_this_iteration",
        "manual_operator_action_available",
        "waiting_only",
        "repair_required_before_any_operator_use",
    }
    assert "effective_primary_urgency" in payload["launch_execution_matrix"]
    assert "primary_effective_next_step" in payload["launch_execution_matrix"]
    assert "safe_auto_coverage_status" in payload["launch_execution_matrix"]
    assert payload["launch_execution_matrix"]["safe_auto_action_count"] >= 1
    assert payload["launch_execution_matrix"]["effective_safe_auto_action_count"] >= 0
    assert payload["launch_execution_matrix"]["raw_safe_auto_action_count"] >= 0
    assert payload["launch_execution_matrix"]["raw_useful_safe_auto_action_count"] >= 0
    assert payload["launch_execution_matrix"]["covered_raw_safe_auto_action_count"] >= 0
    assert "safe_auto_count_scope" in payload["launch_execution_matrix"]
    assert payload["launch_execution_matrix"]["ready_safe_auto_action_count"] >= 1
    assert payload["launch_execution_matrix"]["safe_auto_ready_count"] >= 0
    assert payload["launch_execution_matrix"]["safe_auto_effective_ready_count"] >= 0
    assert payload["launch_execution_matrix"]["overdue_safe_auto_action_count"] >= 0
    assert payload["launch_execution_matrix"]["covered_due_safe_auto_action_count"] >= 0
    assert payload["launch_execution_matrix"]["uncovered_ready_safe_auto_action_count"] >= 0
    assert payload["launch_execution_matrix"]["uncovered_overdue_safe_auto_action_count"] >= 0
    assert payload["launch_execution_matrix"]["scheduled_safe_auto_action_count"] >= 0
    assert "max_overdue_minutes" in payload["launch_execution_matrix"]
    assert isinstance(payload["launch_execution_matrix"]["ready_safe_auto_actions"], list)
    assert isinstance(payload["launch_execution_matrix"]["overdue_safe_auto_actions"], list)
    assert isinstance(payload["launch_execution_matrix"]["scheduled_safe_auto_actions"], list)
    assert isinstance(payload["launch_execution_matrix"]["raw_safe_auto_actions"], list)
    assert payload["launch_execution_matrix"]["manual_action_count"] >= 0
    assert payload["launch_execution_matrix"]["manual_ready_count"] >= 0
    assert payload["launch_execution_matrix"]["manual_due_count"] >= 0
    assert payload["launch_execution_matrix"]["manual_wait_count"] >= 0
    assert payload["launch_execution_matrix"]["manual_effective_due_count"] >= 0
    assert payload["launch_execution_matrix"]["manual_readiness_status"] in {
        "manual_reviews_waiting_for_operator_inputs",
        "manual_reviews_ready_for_operator_dry_run",
        "manual_reviews_not_write_ready",
        "no_manual_reviews",
    }
    assert "manual_template_ready_count" in payload["launch_execution_matrix"]
    assert "manual_operator_input_required_count" in payload["launch_execution_matrix"]
    assert "manual_dry_run_ready_count" in payload["launch_execution_matrix"]
    assert payload["launch_execution_matrix"]["manual_write_ready_count"] == 0
    if payload["launch_execution_matrix"]["manual_action_count"] > 0:
        assert set(payload["launch_execution_matrix"]["manual_required_input_names"]) >= {
            "decision",
            "reviewer",
            "reviewed_at",
            "rationale",
        }
        assert payload["launch_execution_matrix"]["primary_manual_input_step"]["item"] in {
            "choose_accept_or_reject",
            "fill_reviewer_reviewed_at_and_rationale",
        }
    for manual_action in payload["launch_execution_matrix"]["manual_actions"]:
        assert "operator_input_required" in manual_action
        assert set(manual_action["operator_required_input_names"]) >= {
            "decision",
            "reviewer",
            "reviewed_at",
            "rationale",
        }
        assert isinstance(manual_action["operator_input_checklist"], list)
        assert manual_action["operator_input_checklist"][0]["auto_decision_allowed"] is False
        assert "operator_input_contract" in manual_action
        assert manual_action["operator_input_contract"]["auto_decision_allowed"] is False
        assert manual_action["operator_input_contract"]["order_submission_allowed"] is False
        assert manual_action["operator_input_contract"]["operator_input_form"]["status"] in {
            "operator_input_form_ready",
            "operator_input_form_ready_without_prompt_card",
        }
        assert manual_action["operator_input_contract"]["operator_input_form"][
            "dry_run_before_write_required"
        ] is True
        decision_field = manual_action["operator_input_contract"]["operator_input_form"][
            "decision_field"
        ]
        assert decision_field["safe_default_alignment"]["decision_is_accepted_value"] is True
        assert decision_field["safe_default_alignment"]["auto_decision_allowed"] is False
        assert decision_field["safe_default_alignment"]["order_submission_allowed"] is False
        assert "manual_dry_run_status" in manual_action
        assert manual_action["manual_write_ready_now"] is False
        assert manual_action["auto_decision_allowed"] is False
        assert manual_action["order_submission_allowed"] is False
    assert payload["launch_execution_matrix"]["wait_gate_count"] >= 1
    assert payload["launch_execution_matrix"]["forbidden_action_count"] >= 4
    assert payload["launch_execution_matrix"]["primary_next_step"]["order_submission_allowed"] is False
    assert "ready_now" in payload["launch_execution_matrix"]["primary_next_step"]
    assert "due_status" in payload["launch_execution_matrix"]["primary_next_step"]
    assert payload["launch_execution_matrix"]["auto_decision_allowed"] is False
    assert payload["launch_execution_matrix"]["auto_apply_allowed"] is False
    assert payload["launch_execution_matrix"]["order_submission_allowed"] is False
    assert payload["launch_execution_matrix"]["no_live_order_sent"] is True
    forbidden_action_types = [
        item["action_type"]
        for item in payload["launch_execution_matrix"]["forbidden_actions"]
    ]
    assert "submit_live_order_or_enable_live_trading" in forbidden_action_types
    assert "auto_accept_or_reject_operator_reviews" in forbidden_action_types
    assert payload["daily_quote_checkpoint_summary"]["backfill_allowed_for_launch_gate"] is False
    assert "next_quote_window_kst" in payload["daily_quote_checkpoint_summary"]
    assert "quote_window_coordination_status" in payload["daily_quote_checkpoint_summary"]
    assert "next_signal_or_add_monitor_window_status" in payload[
        "daily_quote_checkpoint_summary"
    ]
    assert "next_signal_or_add_monitor_overdue_minutes" in payload[
        "daily_quote_checkpoint_summary"
    ]
    assert "do_not_skip_quote_window_for_signal_monitor" in payload["daily_quote_checkpoint_summary"]
    assert payload["daily_quote_checkpoint_summary"]["order_submission_allowed"] is False
    assert payload["daily_quote_checkpoint_summary"]["no_live_order_sent"] is True
    assert payload["next_material_progress_plan"]["order_submission_allowed"] is False
    assert payload["next_material_progress_plan"]["no_live_order_sent"] is True
    assert "primary_next_event" in payload["next_material_progress_plan"]
    assert isinstance(payload["next_material_progress_plan"]["events"], list)
    assert payload["command_consistency_audit"]["order_submission_allowed"] is False
    assert payload["command_consistency_audit"]["no_live_order_sent"] is True
    assert "signal_monitor_command_parity" in payload["command_consistency_audit"]
    assert "shadow_runtime_command_parity" in payload["command_consistency_audit"]
    assert payload["command_consistency_audit"]["shadow_runtime_command_parity"]["status"] in {
        "shadow_runtime_command_match",
        "shadow_runtime_command_match_with_missing_optional_sources",
        "shadow_runtime_command_sources_missing",
    }
    assert "operator_review_command_parity" in payload["command_consistency_audit"]
    assert payload["operator_work_queue"]["order_submission_allowed"] is False
    assert payload["operator_work_queue"]["no_live_order_sent"] is True
    assert payload["latest_run"]["signal_wait_plan"]["paper_rehearsal_fast_capture_enabled"] is True
    assert payload["latest_run"]["signal_wait_plan"]["recommended_monitor_interval_minutes"] == 5.0
    assert (
        payload["latest_run"]["signal_wait_plan"]["monitor_signal_age_alignment"]
        == "paper_rehearsal_fast_capture_capped_to_fresh_signal_window"
    )
    assert payload["baseline_collection_progress"]["quote_observed"] == 82
    assert payload["canary_risk_caps_config"]["status"] == "missing_optional_config_file"
    assert payload["blocker_resolution_plan"][0]["gate"] == "current_fresh_signal"
    assert payload["blocker_resolution_plan"][0]["can_resolve_now"] is False
    unresolved_ids = [item["id"] for item in payload["unresolved_problem_register"]]
    assert "current_fresh_signal" in unresolved_ids
    current_signal_problem = next(
        item for item in payload["unresolved_problem_register"] if item["id"] == "current_fresh_signal"
    )
    assert current_signal_problem["signal_absence_primary_cause"] == (
        "expected_sparse_signal_wait_within_recent_add_cadence"
    )
    assert current_signal_problem["signal_pipeline_issue_suspected"] is False
    assert current_signal_problem["signal_absence_diagnosis"]["class"] == (
        "healthy_sparse_cadence_wait"
    )
    assert "first_real_paper_lifecycle_row" in unresolved_ids
    assert "execution_parity_samples" in unresolved_ids
    assert all(
        item["problem_id"] == item["id"] for item in payload["unresolved_problem_register"]
    )
    assert all(
        item.get("actionability") for item in payload["unresolved_problem_register"]
    )
    assert all(
        "manual_required" in item for item in payload["unresolved_problem_register"]
    )
    assert all(
        "blocked_by" in item for item in payload["unresolved_problem_register"]
    )
    assert all(item["no_live_order_sent"] is True for item in payload["unresolved_problem_register"])
    assert "launch_next_blocker: `current_fresh_signal`" in latest_md.read_text(encoding="utf-8")
    assert "launch_shadow_watch_brief_status: `" in latest_md.read_text(encoding="utf-8")
    assert "launch_shadow_watch_brief_generated_at_kst: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_shadow_watch_brief_next_blocker: `current_fresh_signal`" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_signal_monitor_capped: `True`" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_signal_cause_partition: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_signal_cause_interpretation: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_signal_absence_primary_cause: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_signal_absence_class: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_signal_pipeline_issue_suspected: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_signal_monitor_next_kst: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_operator_next_status: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_operator_manual_count: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_status: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_primary_gate: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_safe_default_decision: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_decision_command_count: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_safe_default_dry_run_command: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_input_contract_status: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_unresolved_placeholder_count: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_write_allowed_now: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_accept_command_safety: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_accept_live_flag_present: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_reject_command_safety: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_reject_live_flag_present: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_command_safety_status: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_next_safety_action: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_command_structural_blocker_count: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_command_live_flag_count: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_effective_ready_option_count: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_effective_next_safety_action: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_review_file_blocks_dry_run: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_operator_input_status: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_next_operator_action: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_unique_placeholder_count: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_unique_placeholder_scope: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_selected_decision_placeholder_scope: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_primary_decision_placeholder_counts: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_primary_safe_default_placeholder_count: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_selected_decision_min_placeholder_count: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_operator_only_needs_one_decision_rationale: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_common_placeholders: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_placeholder_guide_count: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_reviewer_placeholder_rule: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_accept_rationale_min_chars: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_reject_rationale_min_anchors: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_execution_status: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_execution_current_step: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_execution_current_blocker: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_execution_step_count: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_review_file_status: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_review_file_next_action: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_review_file_count: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_review_file_blocked_count: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_primary_blocked_report: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_review_file_template_count: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_review_file_template_fields: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_review_file_template_scope: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_cli_supplied_fields_pending: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_cli_fixed_fields: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_cli_operator_placeholder_fields: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_cli_field_mapping: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_draft_contract_failed_count: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_draft_contract_blockers: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_primary_draft_contract_blockers: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_status_placeholder_failed_count: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_primary_status_blockers: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_quality_failed_count: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_rationale_quality_failed_count: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_manual_batch_review_file_quality_blockers: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_primary_quality_blockers: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_pending_quality_count: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_pending_rationale_quality_count: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_pending_quality_blockers: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_primary_pending_quality_blockers: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_reviewed_at_quality_failed_count: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_reviewed_at_quality_blockers: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_pending_reviewed_at_quality_count: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_pending_reviewed_at_quality_blockers: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert (
        "launch_shadow_watch_brief_manual_batch_review_file_primary_pending_reviewed_at_quality_blockers: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_authority_scope: `paper_only_shadow_watch_no_live_orders`" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_live_order_allowed: `False`" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_auto_decision_allowed: `False`" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_auto_apply_allowed: `False`" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_live_violation_count: `0`" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "launch_shadow_watch_brief_no_live_order_sent: `True`" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "latest_launch_state_next_blocker: `current_fresh_signal`" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "latest_launch_state_fresh_signal_seen: `False`" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "latest_launch_state_paper_apply_seen: `False`" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "quote_progress_observed_latest: `" in latest_md.read_text(encoding="utf-8")
    assert "quote_progress_state: `progressing`" in latest_md.read_text(encoding="utf-8")
    assert "fresh_signal_blocker_primary_cause: `strategy_abstaining_from_low_quality_soft_contexts`" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "fresh_signal_cause_partition_status: `" in latest_md.read_text(encoding="utf-8")
    assert "fresh_signal_cause_partition_interpretation: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert (
        "fresh_signal_absence_primary_cause: `expected_sparse_signal_wait_within_recent_add_cadence`"
        in latest_md.read_text(encoding="utf-8")
    )
    assert "fresh_signal_absence_class: `healthy_sparse_cadence_wait`" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "fresh_signal_pipeline_issue_suspected: `False`" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "fresh_signal_blocker_rejected_soft_context_count: `6543`" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "fresh_signal_blocker_top_no_trade_reason: `no_trade_MC12_low_confluence`" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "fresh_signal_blocker_primary_safe_experiment: `quality_gated_mc12_near_miss_micro_probe`" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "fresh_signal_resolution_status: `no_safe_runtime_fix_available`" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "fresh_signal_resolution_top_no_trade_reason: `no_trade_MC12_low_confluence`" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "fresh_signal_resolution_operator_fixable_now: `False`" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "unresolved_problem_count: `" in latest_md.read_text(encoding="utf-8")
    assert "## Unresolved Problem Register" in latest_md.read_text(encoding="utf-8")
    assert "operator_work_queue_status: `" in latest_md.read_text(encoding="utf-8")
    assert "operator_work_queue_raw_status: `" in latest_md.read_text(encoding="utf-8")
    assert "operator_work_queue_status_scope: `" in latest_md.read_text(encoding="utf-8")
    assert "operator_work_queue_effective_status: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "operator_work_queue_effective_status_scope: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "operator_work_queue_covered_automation_status: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "operator_work_queue_raw_automation_now_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "operator_work_queue_primary_automation_window_status: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "operator_work_queue_effective_automation_now_count: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "operator_work_queue_covered_automation_now_count: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "operator_work_queue_primary_effective_automation: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "operator_work_queue_primary_automation_effective_window_status: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "operator_work_queue_primary_automation_covered_due_by_current_iteration: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "operator_work_queue_primary_automation_effective_next_monitor_after_kst: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "operator_work_queue_primary_automation_raw_next_monitor_after_kst: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "operator_work_queue_primary_automation_covered_next_recheck_after_kst: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "operator_work_queue_primary_automation_retimestampted_after_current_iteration: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "operator_review_handoff_status: `" in latest_md.read_text(encoding="utf-8")
    assert "## Operator Review Handoff" in latest_md.read_text(encoding="utf-8")
    assert "launch_blocker_priority_status: `waiting_for_realtime_evidence`" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_blocker_priority_dependency_blocked_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_blocker_priority_non_substitutable_problem_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_blocker_priority_non_substitutable_wait_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_blocker_priority_primary_non_substitutable: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_blocker_priority_primary_dependency: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "remaining_work_closure_status: `" in latest_md.read_text(encoding="utf-8")
    assert "remaining_work_safe_effective_automation_now_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "remaining_work_safe_covered_automation_now_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "remaining_work_automation_now_usefulness_scope: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "remaining_work_dependency_blocked_problem_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "remaining_work_primary_wait_only_problem: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "remaining_work_primary_dependency_blocked_problem: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "dependency_aware=`" in latest_md.read_text(encoding="utf-8")
    assert "primary_launch_wait=`" in latest_md.read_text(encoding="utf-8")
    assert "primary_human_action=`" in latest_md.read_text(encoding="utf-8")
    assert "no_safe_auto_now=`" in latest_md.read_text(encoding="utf-8")
    assert "actionability_tracks=`" in latest_md.read_text(encoding="utf-8")
    assert "validation_redesign_runbook=`" in latest_md.read_text(encoding="utf-8")
    assert "active_full_wfo_candidates=`" in latest_md.read_text(encoding="utf-8")
    assert "worst_probe_candidate=`" in latest_md.read_text(encoding="utf-8")
    assert "command_templates=`" in latest_md.read_text(encoding="utf-8")
    assert "required_placeholders=`" in latest_md.read_text(encoding="utf-8")
    assert "templates_validation_only=`" in latest_md.read_text(encoding="utf-8")
    assert "dependency_blockers_open=`" in latest_md.read_text(encoding="utf-8")
    assert "dependency_unlock_plan=`" in latest_md.read_text(encoding="utf-8")
    assert "unlock step=`" in latest_md.read_text(encoding="utf-8")
    assert "unlock_mode=`" in latest_md.read_text(encoding="utf-8")
    assert "partial_unlocks=`" in latest_md.read_text(encoding="utf-8")
    assert "dependency_blocked_problem_ids=`" in latest_md.read_text(encoding="utf-8")
    assert "## Remaining Work Closure" in latest_md.read_text(encoding="utf-8")
    assert "command_consistency_shadow_runtime_status: `" in latest_md.read_text(encoding="utf-8")
    assert "operator_action_digest_status: `" in latest_md.read_text(encoding="utf-8")
    assert "operator_action_digest_primary_ready_now: `" in latest_md.read_text(encoding="utf-8")
    assert "operator_action_digest_scope: `" in latest_md.read_text(encoding="utf-8")
    assert "operator_action_digest_primary_launch_wait_gate: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "operator_action_digest_primary_human_action_gate: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "operator_action_digest_no_safe_auto_command_now: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "operator_action_digest_primary_safe_auto_command: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "operator_action_digest_primary_material_command: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "gate_substitution_digest_status: `" in latest_md.read_text(encoding="utf-8")
    assert "gate_eta_digest_status: `" in latest_md.read_text(encoding="utf-8")
    assert "safe_next_primary_action_window_status: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "safe_next_primary_action_effective_window_status: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "safe_next_primary_action_covered_due_by_current_iteration: `" in (
        latest_md.read_text(encoding="utf-8")
    )
    assert "safe_next_covered_due_safe_action_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_progress_scorecard_status: `" in latest_md.read_text(encoding="utf-8")
    assert "launch_progress_scorecard_complete_lanes: `" in latest_md.read_text(encoding="utf-8")
    assert "launch_progress_fresh_signal_available: `False`" in latest_md.read_text(encoding="utf-8")
    assert "launch_progress_fresh_signal_next_monitor_kst: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_progress_fresh_signal_raw_next_monitor_kst: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_progress_fresh_signal_next_monitor_source: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_progress_fresh_signal_retimestampted_after_current_iteration: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_critical_path_status: `" in latest_md.read_text(encoding="utf-8")
    assert "launch_critical_path_next_open_gate: `current_fresh_signal`" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_status: `" in latest_md.read_text(encoding="utf-8")
    assert "launch_execution_matrix_urgency_status: `" in latest_md.read_text(encoding="utf-8")
    assert "launch_execution_matrix_effective_urgency_status: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_safe_auto_effective_ready_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_effective_safe_auto_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_raw_safe_auto_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_raw_useful_safe_auto_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_covered_raw_safe_auto_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_primary_covered_raw_safe_auto: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_safe_auto_count_scope: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_manual_ready_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_manual_effective_due_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_safe_auto_coverage_status: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_primary_step: `" in latest_md.read_text(encoding="utf-8")
    assert "launch_execution_matrix_effective_primary_step: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_ready_safe_auto_count: `" in latest_md.read_text(encoding="utf-8")
    assert "launch_execution_matrix_overdue_safe_auto_count: `" in latest_md.read_text(encoding="utf-8")
    assert "launch_execution_matrix_covered_due_safe_auto_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_uncovered_overdue_safe_auto_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_manual_readiness_status: `" in latest_md.read_text(encoding="utf-8")
    assert "launch_execution_matrix_manual_write_ready_count: `" in latest_md.read_text(encoding="utf-8")
    assert "launch_execution_matrix_manual_required_inputs: `" in latest_md.read_text(encoding="utf-8")
    assert "launch_execution_matrix_manual_input_contract_statuses: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_manual_prompt_card_statuses: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_manual_prompt_card_ready_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_manual_input_form_statuses: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_manual_input_form_ready_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_manual_safe_default_alignment_status: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_manual_safe_default_alignment_statuses: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_manual_safe_default_decisions: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_manual_safe_default_alignment_mismatch_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_manual_safe_default_alignment_next_step: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_manual_rationale_must_address_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_manual_minimum_anchor_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_manual_decision_option_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_manual_decision_dry_run_ready_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_manual_decision_write_ready_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_manual_decision_validation_ready_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_primary_manual_input_item: `" in latest_md.read_text(encoding="utf-8")
    assert "launch_execution_matrix_primary_manual_contract_status: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_primary_manual_contract_next_step: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_primary_manual_prompt_status: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_primary_manual_prompt_safe_default: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_primary_manual_prompt_min_anchors: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_primary_manual_prompt_must_address_count: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_primary_manual_form_status: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_primary_manual_form_required_fields: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_primary_manual_form_safe_default_decision: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_primary_manual_form_safe_default_policy: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_primary_manual_form_safe_default_alignment: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_primary_manual_form_min_rationale_chars: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_primary_manual_form_min_anchors: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_primary_due_status: `" in latest_md.read_text(encoding="utf-8")
    assert "launch_execution_matrix_current_signal_wait_next_monitor_kst: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_current_signal_wait_raw_next_monitor_kst: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "launch_execution_matrix_current_signal_wait_next_monitor_source: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert (
        "launch_execution_matrix_current_signal_wait_retimestampted_after_current_iteration: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert "## First Fresh Signal Runbook" in latest_md.read_text(encoding="utf-8")
    assert "## Operator Review Decision Aid" in latest_md.read_text(encoding="utf-8")
    assert "## Daily Quote Checkpoint" in latest_md.read_text(encoding="utf-8")
    assert "daily_quote_checkpoint_coordination_status: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "daily_quote_checkpoint_next_signal_kst: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "daily_quote_checkpoint_raw_next_signal_kst: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "daily_quote_checkpoint_next_signal_source: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "daily_quote_checkpoint_next_signal_wait_minutes: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "daily_quote_checkpoint_next_signal_retimestampted_after_current_iteration: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "daily_quote_checkpoint_next_signal_window_status: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "safe_next_coordination_raw_next_signal_or_add_monitor_kst: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "safe_next_coordination_next_signal_or_add_monitor_source: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "safe_next_coordination_next_signal_or_add_monitor_wait_minutes: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "safe_next_coordination_next_signal_or_add_monitor_retimestampted_after_current_iteration: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "safe_next_coordination_next_signal_or_add_monitor_window_status: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "safe_next_coordination_next_signal_or_add_monitor_raw_window_status: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "safe_next_pre_wait_primary_action_due_now: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "do_not_skip_quote_window=`" in latest_md.read_text(encoding="utf-8")
    assert "## Launch Blocker Priority" in latest_md.read_text(encoding="utf-8")
    assert "## Operator Work Queue" in latest_md.read_text(encoding="utf-8")
    assert "safe_action=`" in latest_md.read_text(encoding="utf-8")
    assert "next_signal_kst=`" in latest_md.read_text(encoding="utf-8")
    assert "next_quote_kst=`" in latest_md.read_text(encoding="utf-8")
    assert "quote_deferred=`" in latest_md.read_text(encoding="utf-8")
    assert "quote_observed_delta: `2`" in latest_md.read_text(encoding="utf-8")
    assert "quote_cadence_decision: `capture_new_utc_hour_for_hour_gate`" in latest_md.read_text(encoding="utf-8")
    assert "execution_parity_events_needed_latest: `20`" in latest_md.read_text(encoding="utf-8")
    assert "execution_parity_events_needed_after_current_apply_latest: `20`" in latest_md.read_text(encoding="utf-8")
    assert "operator_handoff_execution_parity_events_needed: `20`" in latest_md.read_text(encoding="utf-8")
    assert "operator_handoff_execution_parity_will_credit_current_apply: `False`" in latest_md.read_text(encoding="utf-8")
    assert "execution_parity_status_summary_status: `waiting_for_fresh_signal`" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "execution_parity_status_summary_missing_samples: `20`" in latest_md.read_text(encoding="utf-8")
    assert "safe_next_scheduled_action_command: `" in latest_md.read_text(encoding="utf-8")
    assert "safe_next_scheduled_recommended_monitor_interval_minutes: `" in latest_md.read_text(encoding="utf-8")
    assert "safe_next_scheduled_monitor_interval_capped_by_freshness: `" in latest_md.read_text(encoding="utf-8")
    assert "safe_next_paper_wait_action_type: `" in latest_md.read_text(encoding="utf-8")
    assert "safe_next_paper_wait_apply_when_gate_allows: `" in latest_md.read_text(encoding="utf-8")
    assert "safe_next_paper_wait_safety_dry_run_report_dir: `" in latest_md.read_text(encoding="utf-8")
    assert "safe_next_paper_wait_safety_apply_report_dir: `" in latest_md.read_text(encoding="utf-8")
    assert "scheduled_command_projection_status: `" in latest_md.read_text(encoding="utf-8")
    assert "scheduled_command_projection_raw_scope: `" in latest_md.read_text(encoding="utf-8")
    assert "scheduled_command_projection_use_for_next_action: `" in latest_md.read_text(encoding="utf-8")
    assert "scheduled_command_projection_primary_execute_after_kst: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "scheduled_command_projection_primary_raw_execute_after_kst: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "scheduled_command_projection_primary_execute_after_source: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert (
        "scheduled_command_projection_primary_retimestampted_after_current_iteration: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert "scheduled_command_projection_primary_command: `" in latest_md.read_text(encoding="utf-8")
    assert "scheduled_command_projection_primary_raw_command: `" in latest_md.read_text(encoding="utf-8")
    assert "scheduled_command_projection_primary_report_dir: `" in latest_md.read_text(encoding="utf-8")
    assert "scheduled_command_projection_primary_raw_report_dir: `" in latest_md.read_text(encoding="utf-8")
    assert (
        "scheduled_command_projection_primary_report_dir_retimestampted_to_effective: `"
        in latest_md.read_text(encoding="utf-8")
    )
    assert "scheduled_command_projection_report_dirs_differ_from_raw: `" in latest_md.read_text(
        encoding="utf-8"
    )
    assert "scheduled_command_projection_reason: `" in latest_md.read_text(encoding="utf-8")
    assert "scheduled_command_projection_next_command_source: `" in latest_md.read_text(encoding="utf-8")
    assert "## Blocker Resolution Plan" in latest_md.read_text(encoding="utf-8")


def test_paper_rehearsal_fast_signal_monitor_preserves_schedule_for_same_event() -> None:
    plan = watch._paper_rehearsal_fast_signal_monitor_plan(
        {
            "signal_wait_plan": {
                "fresh_signal": False,
                "latest_event_ts": "2026-01-01T12:00:00+00:00",
                "recommended_monitor_interval_minutes": 60,
                "signal_freshness_capture_window_minutes": 15.0,
                "command": (
                    ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                    "--quote-samples-per-tick 0 --report-dir "
                    "reports/validation/diagnostics/market_state_rotation_v6_signal_monitor_20260101_120300Z"
                ),
            },
            "launch_readiness": {
                "paper_only_rehearsal": {
                    "armed": True,
                    "remaining_gates": ["current_fresh_signal"],
                }
            },
        },
        generated_at=datetime(2026, 1, 1, 12, 3, tzinfo=UTC),
        previous_payload={
            "latest_run": {
                "signal_wait_plan": {
                    "fresh_signal": False,
                    "latest_event_ts": "2026-01-01T12:00:00+00:00",
                    "next_monitor_after_utc": "2026-01-01T12:05:00+00:00",
                }
            },
            "no_live_order_sent": True,
        },
    )

    assert plan["next_monitor_after_utc"] == "2026-01-01T12:05:00+00:00"
    assert plan["next_monitor_after_kst"] == "2026-01-01T21:05:00+09:00"
    assert plan["next_monitor_preserved_from_previous_watch"] is True
    assert plan["next_monitor_anchor"] == "previous_watch_same_latest_signal_event"
    assert "market_state_rotation_v6_signal_monitor_20260101_120500Z" in plan["command"]
    assert "market_state_rotation_v6_signal_monitor_20260101_120300Z" not in plan["command"]
    assert plan["recommended_monitor_interval_minutes"] == 5.0
    assert plan["no_live_order_sent"] is True


def test_paper_rehearsal_fast_signal_monitor_advances_after_completed_monitor_report(tmp_path) -> None:
    report_dir = tmp_path / "signal_monitor"
    report_dir.mkdir()
    (report_dir / "market_state_rotation_v6_evidence_cycle.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T12:05:30+00:00",
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )
    plan = watch._paper_rehearsal_fast_signal_monitor_plan(
        {
            "signal_wait_plan": {
                "fresh_signal": False,
                "latest_event_ts": "2026-01-01T12:00:00+00:00",
                "recommended_monitor_interval_minutes": 60,
                "signal_freshness_capture_window_minutes": 15.0,
                "command": (
                    ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                    "--quote-samples-per-tick 0 --report-dir "
                    "reports/validation/diagnostics/market_state_rotation_v6_signal_monitor_20260101_120500Z"
                ),
            },
            "launch_readiness": {
                "paper_only_rehearsal": {
                    "armed": True,
                    "remaining_gates": ["current_fresh_signal"],
                }
            },
        },
        generated_at=datetime(2026, 1, 1, 12, 6, tzinfo=UTC),
        previous_payload={
            "latest_run": {
                "signal_wait_plan": {
                    "fresh_signal": False,
                    "latest_event_ts": "2026-01-01T12:00:00+00:00",
                    "next_monitor_after_utc": "2026-01-01T12:05:00+00:00",
                    "command": f"monitor --report-dir {report_dir}",
                }
            },
            "no_live_order_sent": True,
        },
    )

    assert plan["previous_monitor_report_completed"] is True
    assert plan["next_monitor_preserved_from_previous_watch"] is False
    assert plan["next_monitor_anchor"] == "previous_watch_monitor_report_completed"
    assert plan["next_monitor_after_utc"] == "2026-01-01T12:11:00+00:00"
    assert "market_state_rotation_v6_signal_monitor_20260101_121100Z" in plan["command"]
    assert plan["no_live_order_sent"] is True


def test_paper_rehearsal_fast_signal_monitor_recognizes_alternate_completed_monitor_report(tmp_path) -> None:
    stale_report_dir = tmp_path / "market_state_rotation_v6_signal_monitor_20260101_120500Z"
    completed_report_dir = tmp_path / "market_state_rotation_v6_signal_monitor_20260101_120530Z"
    completed_report_dir.mkdir()
    (completed_report_dir / "market_state_rotation_v6_evidence_cycle.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T12:05:45+00:00",
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )
    plan = watch._paper_rehearsal_fast_signal_monitor_plan(
        {
            "signal_wait_plan": {
                "fresh_signal": False,
                "latest_event_ts": "2026-01-01T12:00:00+00:00",
                "recommended_monitor_interval_minutes": 60,
                "signal_freshness_capture_window_minutes": 15.0,
                "command": (
                    ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                    "--quote-samples-per-tick 0 --report-dir "
                    "reports/validation/diagnostics/market_state_rotation_v6_signal_monitor_20260101_120500Z"
                ),
            },
            "launch_readiness": {
                "paper_only_rehearsal": {
                    "armed": True,
                    "remaining_gates": ["current_fresh_signal"],
                }
            },
        },
        generated_at=datetime(2026, 1, 1, 12, 6, tzinfo=UTC),
        previous_payload={
            "latest_run": {
                "signal_wait_plan": {
                    "fresh_signal": False,
                    "latest_event_ts": "2026-01-01T12:00:00+00:00",
                    "next_monitor_after_utc": "2026-01-01T12:05:00+00:00",
                    "command": f"monitor --report-dir {stale_report_dir}",
                }
            },
            "no_live_order_sent": True,
        },
    )

    assert plan["previous_monitor_report_completed"] is True
    assert plan["next_monitor_preserved_from_previous_watch"] is False
    assert plan["next_monitor_after_utc"] == "2026-01-01T12:11:00+00:00"
    assert "market_state_rotation_v6_signal_monitor_20260101_121100Z" in plan["command"]
    assert plan["no_live_order_sent"] is True


def test_safe_next_action_marks_preserved_fresh_signal_monitor_due() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "current_fresh_signal",
                "command": "monitor-signal",
                "reason": "must_wait_for_realtime_v6_add_or_remove_signal_do_not_force_entry",
                "next_monitor_after_utc": "2026-01-01T12:05:00+00:00",
                "next_monitor_after_kst": "2026-01-01T21:05:00+09:00",
                "recommended_monitor_interval_minutes": 5.0,
                "signal_freshness_capture_window_minutes": 15.0,
                "monitor_interval_capped_by_signal_freshness": True,
                "monitor_signal_age_alignment": "paper_rehearsal_fast_capture_capped_to_fresh_signal_window",
            }
        ],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 6, tzinfo=UTC),
    )

    action = plan["primary_action"]
    assert plan["status"] == "safe_actions_available"
    assert action["action_type"] == "monitor_fresh_signal"
    assert action["can_run_now"] is True
    assert action["execute_after_utc"] == "2026-01-01T12:05:00+00:00"
    assert action["wait_minutes"] == 0.0
    assert action["monitor_interval_capped_by_signal_freshness"] is True
    assert action["monitor_signal_age_alignment"] == "paper_rehearsal_fast_capture_capped_to_fresh_signal_window"
    assert action["no_live_order_sent"] is True


def test_launch_shadow_watch_explains_order_safety_controls_blocker(monkeypatch, tmp_path) -> None:
    args = _args(tmp_path)
    args.iterations = 1
    args.target_hours = 0.0

    def fake_run_evidence_cycle(**kwargs):
        return {
            "overall_status": "healthy_abstention_waiting_for_quality_signal",
            "no_live_order_sent": True,
            "collection_progress": {"quote_observed": 300, "quote_distinct_hours": 24, "paper_fill_rows": 100},
            "readiness_progress": {},
            "paper_bridge_apply_gate": {"fresh_signal": True, "can_request_paper_apply_now": False},
            "signal_wait_plan": {},
            "launch_readiness": {
                "status": "shadow_ready_waiting_for_order_safety_controls",
                "research_ready": True,
                "shadow_ready": True,
                "tiny_canary_evidence_ready": False,
                "next_blocker": {
                    "gate": "order_safety_controls_verified",
                    "blocker": "order_safety_controls_missing_or_incomplete",
                },
                "blocking_gates": [
                    {
                        "gate": "order_safety_controls_verified",
                        "blocker": "order_safety_controls_missing_or_incomplete",
                        "next_action": "run_manual_safety_drills_and_safety_controls_audit_until_all_required_controls_pass",
                    }
                ],
                "operator_commands": {},
            },
            "launch_safety_controls": {
                "overall_status": "INCOMPLETE",
                "verified_count": 3,
                "required_count": 10,
                "missing_or_failed": ["position_sync_verified", "reduce_only_exit_verified"],
            },
            "historical_gate_substitution": {},
            "canary_risk_caps_config": {"configured": True, "status": "configured_from_file", "errors": []},
        }

    monkeypatch.setattr(watch, "run_evidence_cycle", fake_run_evidence_cycle)

    summary = watch.run_launch_shadow_watch(args, sleep_fn=lambda seconds: None)

    plan = summary["blocker_resolution_plan"][0]
    assert plan["gate"] == "order_safety_controls_verified"
    assert plan["can_resolve_now"] is True
    assert plan["requires_operator_review"] is True
    assert "run_market_state_rotation_v6_manual_safety_drills.py" in plan["command"]
    assert "run_market_state_rotation_v6_safety_controls_audit.py" in plan["follow_up_command"]
    assert plan["verified_count"] == 3
    assert plan["required_count"] == 10
    assert plan["missing_or_failed"] == ["position_sync_verified", "reduce_only_exit_verified"]
    assert summary["no_live_order_sent"] is True


def test_blocker_plan_does_not_surface_paper_apply_command_before_fresh_signal() -> None:
    plan = watch._blocker_resolution_plan(
        latest={
            "paper_bridge_apply_gate": {
                "fresh_signal": False,
                "can_request_paper_apply_now": False,
            },
            "signal_wait_plan": {
                "command": "monitor-signal",
            },
            "collection_progress": {
                "paper_fill_rows": 0,
            },
            "evidence_report": "reports/validation/diagnostics/pre_apply/market_state_rotation_v6_evidence_cycle.json",
            "launch_readiness": {
                "blocking_gates": [
                    {
                        "gate": "real_paper_lifecycle_rows",
                        "blocker": "real_paper_lifecycle_rows_missing",
                        "next_action": "apply_paper_bridge_only_after_fresh_signal_and_verified_backup",
                    }
                ],
                "operator_commands": {
                    "paper_bridge_dry_run": "dry-run",
                    "paper_apply_only_after_fresh_signal": "paper-apply",
                },
            },
            "execution_parity_collection_plan": {
                "status": "ready_to_credit_next_paper_apply",
                "estimated_future_paper_apply_events_needed": 20,
                "estimated_events_needed_after_current_creditable_apply": 19,
                "will_credit_current_apply_after_operator_review": True,
                "currently_creditable_actions": ["remove"],
                "accepted_actions": ["add", "remove"],
                "non_substitutable": True,
            },
        },
        progress={},
        runtime_progress={},
        risk_caps={},
        microstructure_watch={},
        operator_handoff={
            "paper_apply_allowed_now": False,
            "paper_handoff_status": "blocked_waiting_for_fresh_signal",
            "paper_dry_run_command": "dry-run",
            "paper_apply_command": "paper-apply",
        },
    )

    item = plan[0]
    assert item["gate"] == "real_paper_lifecycle_rows"
    assert item["can_resolve_now"] is False
    assert item["command"] is None
    assert item["monitor_command"] == "monitor-signal"
    assert item["paper_apply_command_when_gate_allows"] == "paper-apply"
    assert item["reason"] == "must_wait_for_fresh_signal_before_paper_bridge_apply"
    assert item["fresh_signal"] is False
    assert item["order_submission_allowed"] is False
    assert item["no_live_order_sent"] is True


def test_blocker_plan_retimestamps_waiting_paper_packet_commands_to_next_monitor() -> None:
    stale_dry_run = (
        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
        "--quote-samples-per-tick 0 --refresh-market-data-before-run "
        "--report-dir reports/validation/diagnostics/market_state_rotation_v6_launch_paper_dry_run_20260101_1200Z"
    )
    stale_apply = (
        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
        "--apply-paper-bridge --quote-samples-per-tick 0 --refresh-market-data-before-run "
        "--pre-apply-backup-dir reports/db_recovery/market_state_rotation_v6_bridge_tick "
        "--report-dir reports/validation/diagnostics/market_state_rotation_v6_launch_paper_apply_20260101_1200Z"
    )
    plan = watch._blocker_resolution_plan(
        latest={
            "paper_bridge_apply_gate": {
                "fresh_signal": False,
                "can_request_paper_apply_now": False,
            },
            "signal_wait_plan": {
                "command": "monitor-signal",
                "next_monitor_after_utc": "2026-01-01T12:15:00+00:00",
                "next_monitor_after_kst": "2026-01-01T21:15:00+09:00",
            },
            "collection_progress": {
                "paper_fill_rows": 0,
            },
            "evidence_report": "reports/validation/diagnostics/pre_apply/market_state_rotation_v6_evidence_cycle.json",
            "launch_readiness": {
                "blocking_gates": [
                    {
                        "gate": "real_paper_lifecycle_rows",
                        "blocker": "real_paper_lifecycle_rows_missing",
                        "next_action": "apply_paper_bridge_only_after_fresh_signal_and_verified_backup",
                    }
                ],
            },
            "execution_parity_collection_plan": {
                "status": "waiting_for_fresh_signal",
                "estimated_future_paper_apply_events_needed": 20,
                "estimated_events_needed_after_current_creditable_apply": 20,
                "will_credit_current_apply_after_operator_review": False,
                "currently_creditable_actions": [],
                "accepted_actions": ["add", "remove"],
                "non_substitutable": True,
            },
        },
        progress={},
        runtime_progress={},
        risk_caps={},
        microstructure_watch={},
        operator_handoff={
            "paper_apply_allowed_now": False,
            "paper_handoff_status": "blocked_waiting_for_fresh_signal",
            "paper_dry_run_command": stale_dry_run,
            "paper_apply_command": stale_apply,
            "paper_apply_operator_packet": {
                "status": "armed_waiting_for_fresh_signal",
                "dry_run_command": stale_dry_run,
                "rerun_command_after_deadline": stale_dry_run,
                "apply_command_when_gate_allows": stale_apply,
                "command_safety": {
                    "status": "PASS",
                    "dry_run_report_dir": (
                        "reports/validation/diagnostics/"
                        "market_state_rotation_v6_launch_paper_dry_run_20260101_1200Z"
                    ),
                    "apply_report_dir": (
                        "reports/validation/diagnostics/"
                        "market_state_rotation_v6_launch_paper_apply_20260101_1200Z"
                    ),
                    "apply_pre_apply_backup_dir": "reports/db_recovery/market_state_rotation_v6_bridge_tick",
                },
                "pre_apply_backup_plan": {"required": True},
                "no_live_order_sent": True,
            },
        },
    )

    item = plan[0]
    packet = item["paper_apply_operator_packet"]
    safety = packet["command_safety"]
    assert "market_state_rotation_v6_launch_paper_dry_run_20260101_1215Z" in item["dry_run_command"]
    assert "market_state_rotation_v6_launch_paper_apply_20260101_1215Z" in (
        item["paper_apply_command_when_gate_allows"]
    )
    assert "market_state_rotation_v6_launch_paper_dry_run_20260101_1215Z" in packet["dry_run_command"]
    assert "market_state_rotation_v6_launch_paper_apply_20260101_1215Z" in (
        packet["apply_command_when_gate_allows"]
    )
    assert safety["dry_run_report_dir"].endswith("market_state_rotation_v6_launch_paper_dry_run_20260101_1215Z")
    assert safety["apply_report_dir"].endswith("market_state_rotation_v6_launch_paper_apply_20260101_1215Z")
    assert item["command"] is None
    assert item["can_resolve_now"] is False
    assert item["no_live_order_sent"] is True


def test_scheduled_command_projection_separates_raw_handoff_from_next_safe_commands() -> None:
    projection = watch._scheduled_command_projection(
        operator_handoff={
            "status": "blocked_waiting_for_fresh_signal",
            "paper_dry_run_command": "raw-dry-run",
            "paper_apply_command": "raw-apply",
            "paper_apply_operator_packet": {
                "command_safety": {
                    "dry_run_report_dir": "raw-dry",
                    "apply_report_dir": "raw-apply",
                }
            },
        },
        safe_next_action_plan={
            "primary_action": {
                "action_type": "monitor_fresh_signal",
                "execute_after_utc": "2026-01-01T12:15:00+00:00",
                "execute_after_kst": "2026-01-01T21:15:00+09:00",
                "command": "scheduled-monitor",
            },
            "coordination_plan": {
                "next_signal_or_add_monitor_kst": "2026-01-01T21:15:00+09:00",
                "next_quote_window_kst": "2026-01-02T09:00:00+09:00",
                "quote_window_deferred_by_earlier_monitor": True,
            },
            "actions": [
                {
                    "action_type": "paper_bridge_wait_for_fresh_signal",
                    "execute_after_utc": "2026-01-01T12:15:00+00:00",
                    "execute_after_kst": "2026-01-01T21:15:00+09:00",
                    "command": "scheduled-paper-monitor",
                    "paper_apply_command_when_gate_allows": "scheduled-apply",
                    "paper_apply_operator_packet": {
                        "dry_run_command": "scheduled-dry-run",
                        "apply_command_when_gate_allows": "scheduled-apply",
                        "command_safety": {
                            "dry_run_report_dir": "scheduled-dry",
                            "apply_report_dir": "scheduled-apply",
                        },
                    },
                }
            ],
        },
    )

    assert projection["status"] == "scheduled_safe_next_commands_available"
    assert projection["raw_operator_handoff_scope"] == "evidence_snapshot_not_execution_schedule"
    assert projection["raw_operator_handoff_dry_run_command"] == "raw-dry-run"
    assert projection["raw_operator_handoff_safety_dry_run_report_dir"] == "raw-dry"
    assert projection["primary_command"] == "scheduled-monitor"
    assert projection["paper_wait_monitor_command"] == "scheduled-paper-monitor"
    assert projection["paper_wait_packet_dry_run_command"] == "scheduled-dry-run"
    assert projection["paper_wait_safety_dry_run_report_dir"] == "scheduled-dry"
    assert projection["primary_report_dir"] is None
    assert projection["paper_wait_monitor_report_dir"] is None
    assert projection["paper_wait_apply_report_dir"] is None
    assert projection["paper_wait_report_dirs_differ_from_raw_handoff"] is True
    assert projection["projection_reason"] == "scheduled_report_dirs_retimestampted_to_next_safe_action"
    assert projection["next_operator_command_source"] == "scheduled_command_projection.primary_command"
    assert projection["paper_apply_command_source_when_gate_allows"] == (
        "scheduled_command_projection.paper_wait_apply_command_when_gate_allows"
    )
    assert projection["quote_window_deferred_by_earlier_monitor"] is True
    assert projection["use_projection_for_next_operator_action"] is True
    assert projection["no_live_order_sent"] is True


def test_scheduled_command_projection_retimestamps_covered_signal_monitor_to_effective_next() -> None:
    raw_monitor = (
        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
        "--quote-samples-per-tick 0 --report-dir "
        "reports/validation/diagnostics/market_state_rotation_v6_signal_monitor_20260101_121500Z"
    )
    raw_apply = (
        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
        "--apply-paper-bridge --report-dir "
        "reports/validation/diagnostics/market_state_rotation_v6_launch_paper_apply_20260101_1215Z"
    )
    raw_dry = (
        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
        "--report-dir "
        "reports/validation/diagnostics/market_state_rotation_v6_launch_paper_dry_run_20260101_1215Z"
    )
    coverage = {
        "covered": True,
        "recommended_next_recheck_after_utc": "2026-01-01T12:25:00+00:00",
        "recommended_next_recheck_after_kst": "2026-01-01T21:25:00+09:00",
        "no_live_order_sent": True,
    }
    projection = watch._scheduled_command_projection(
        operator_handoff={
            "status": "blocked_waiting_for_fresh_signal",
            "paper_apply_operator_packet": {
                "command_safety": {
                    "dry_run_report_dir": (
                        "reports/validation/diagnostics/"
                        "market_state_rotation_v6_launch_paper_dry_run_20260101_1215Z"
                    ),
                    "apply_report_dir": (
                        "reports/validation/diagnostics/"
                        "market_state_rotation_v6_launch_paper_apply_20260101_1215Z"
                    ),
                }
            },
        },
        safe_next_action_plan={
            "primary_action": {
                "action_type": "monitor_fresh_signal",
                "execute_after_utc": "2026-01-01T12:15:00+00:00",
                "execute_after_kst": "2026-01-01T21:15:00+09:00",
                "covered_by_current_iteration": True,
                "current_iteration_coverage": coverage,
                "command": raw_monitor,
            },
            "coordination_plan": {
                "next_signal_or_add_monitor_kst": "2026-01-01T21:25:00+09:00",
                "raw_next_signal_or_add_monitor_kst": "2026-01-01T21:15:00+09:00",
            },
            "actions": [
                {
                    "action_type": "paper_bridge_wait_for_fresh_signal",
                    "execute_after_utc": "2026-01-01T12:15:00+00:00",
                    "execute_after_kst": "2026-01-01T21:15:00+09:00",
                    "covered_by_current_iteration": True,
                    "current_iteration_coverage": coverage,
                    "command": raw_monitor,
                    "paper_apply_command_when_gate_allows": raw_apply,
                    "paper_apply_operator_packet": {
                        "dry_run_command": raw_dry,
                        "apply_command_when_gate_allows": raw_apply,
                        "command_safety": {
                            "dry_run_report_dir": (
                                "reports/validation/diagnostics/"
                                "market_state_rotation_v6_launch_paper_dry_run_20260101_1215Z"
                            ),
                            "apply_report_dir": (
                                "reports/validation/diagnostics/"
                                "market_state_rotation_v6_launch_paper_apply_20260101_1215Z"
                            ),
                        },
                    },
                }
            ],
        },
    )

    assert projection["primary_execute_after_kst"] == "2026-01-01T21:25:00+09:00"
    assert projection["primary_raw_execute_after_kst"] == "2026-01-01T21:15:00+09:00"
    assert projection["primary_execute_after_source"] == (
        "current_iteration_coverage.recommended_next_recheck_after"
    )
    assert projection["primary_retimestampted_after_current_iteration"] is True
    assert "market_state_rotation_v6_signal_monitor_20260101_122500Z" in (
        projection["primary_command"]
    )
    assert "market_state_rotation_v6_signal_monitor_20260101_121500Z" in (
        projection["primary_raw_command"]
    )
    assert projection["primary_report_dir"].endswith(
        "market_state_rotation_v6_signal_monitor_20260101_122500Z"
    )
    assert projection["primary_raw_report_dir"].endswith(
        "market_state_rotation_v6_signal_monitor_20260101_121500Z"
    )
    assert projection["primary_report_dir_retimestampted_to_effective"] is True
    assert projection["paper_wait_execute_after_kst"] == "2026-01-01T21:25:00+09:00"
    assert projection["paper_wait_raw_execute_after_kst"] == "2026-01-01T21:15:00+09:00"
    assert "market_state_rotation_v6_signal_monitor_20260101_122500Z" in (
        projection["paper_wait_monitor_command"]
    )
    assert projection["paper_wait_safety_dry_run_report_dir"].endswith(
        "market_state_rotation_v6_launch_paper_dry_run_20260101_1225Z"
    )
    assert projection["paper_wait_safety_apply_report_dir"].endswith(
        "market_state_rotation_v6_launch_paper_apply_20260101_1225Z"
    )
    assert projection["no_live_order_sent"] is True


def test_blocker_plan_surfaces_paper_apply_command_only_when_gate_allows() -> None:
    plan = watch._blocker_resolution_plan(
        latest={
            "paper_bridge_apply_gate": {
                "fresh_signal": True,
                "can_request_paper_apply_now": True,
                "bridge_action": "add",
                "execution_parity_preflight": {
                    "source_event_key": "event-1",
                    "source_event_ts": "2026-01-01T00:00:00+00:00",
                },
            },
            "pre_apply_backup_plan": {
                "status": "ready_required_before_paper_apply",
                "backup_dir": "reports/db_recovery/market_state_rotation_v6_bridge_tick",
                "verification_required_fields": [
                    "pre_apply_backup.created == true",
                    "pre_apply_backup.quick_check == 'ok'",
                ],
                "no_live_order_sent": True,
            },
            "collection_progress": {
                "paper_fill_rows": 0,
            },
            "evidence_report": "reports/validation/diagnostics/pre_apply/market_state_rotation_v6_evidence_cycle.json",
            "launch_readiness": {
                "blocking_gates": [
                    {
                        "gate": "real_paper_lifecycle_rows",
                        "blocker": "real_paper_lifecycle_rows_missing",
                        "next_action": "apply_paper_bridge_only_after_fresh_signal_and_verified_backup",
                    }
                ],
                "operator_commands": {
                    "paper_bridge_dry_run": "dry-run",
                    "paper_apply_only_after_fresh_signal": "paper-apply",
                },
            },
            "execution_parity_collection_plan": {
                "status": "ready_to_credit_next_paper_apply",
                "estimated_future_paper_apply_events_needed": 20,
                "estimated_events_needed_after_current_creditable_apply": 19,
                "will_credit_current_apply_after_operator_review": True,
                "currently_creditable_actions": ["remove"],
                "accepted_actions": ["add", "remove"],
                "non_substitutable": True,
            },
        },
        progress={},
        runtime_progress={},
        risk_caps={},
        microstructure_watch={},
        operator_handoff={
            "paper_apply_allowed_now": True,
            "paper_handoff_status": "paper_apply_review_available",
            "paper_dry_run_command": "dry-run",
            "paper_apply_command": "paper-apply",
            "paper_apply_operator_packet": {
                "status": "ready_for_operator_review",
                "pre_apply_backup_plan": {
                    "status": "ready_required_before_paper_apply",
                    "backup_dir": "reports/db_recovery/market_state_rotation_v6_bridge_tick",
                },
                "post_apply_execution_parity_review_command": (
                    ".venv/bin/python scripts/run_market_state_rotation_v6_paper_apply_parity_review.py "
                    "--before-evidence-report reports/pre.json "
                    "--after-evidence-report <post_apply_evidence_report> "
                    "--report-dir reports/validation/diagnostics/<paper_apply_parity_review_report_dir> "
                    "--write-report"
                ),
                "no_live_order_sent": True,
            },
        },
    )

    item = plan[0]
    assert item["gate"] == "real_paper_lifecycle_rows"
    assert item["can_resolve_now"] is True
    assert item["requires_operator_review"] is True
    assert item["command"] == "paper-apply"
    assert item["reason"] == "paper_bridge_apply_available_after_operator_review_and_verified_backup"
    assert item["fresh_signal"] is True
    assert item["can_request_paper_apply_now"] is True
    assert item["execution_parity_will_credit_current_apply"] is True
    assert item["execution_parity_events_needed"] == 20
    assert item["execution_parity_events_needed_after_current_apply"] == 19
    assert item["execution_parity_creditable_actions"] == ["remove"]
    assert item["execution_parity_non_substitutable"] is True
    assert item["pre_apply_evidence_report"] == (
        "reports/validation/diagnostics/pre_apply/market_state_rotation_v6_evidence_cycle.json"
    )
    assert item["paper_apply_operator_packet"]["status"] == "ready_for_operator_review"
    assert item["pre_apply_backup_plan"]["status"] == "ready_required_before_paper_apply"
    assert "run_market_state_rotation_v6_paper_apply_parity_review.py" in item[
        "post_apply_execution_parity_review_command"
    ]
    assert "--after-evidence-report <post_apply_evidence_report>" in item[
        "post_apply_execution_parity_review_command"
    ]
    assert item["order_submission_allowed"] is False


def test_operator_handoff_builds_pre_apply_operator_packet(tmp_path) -> None:
    evidence_report = tmp_path / "market_state_rotation_v6_evidence_cycle.json"
    evidence_report.write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T00:00:00+00:00",
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )
    handoff = watch._operator_handoff(
        latest={
            "generated_at": "2026-01-01T00:00:00+00:00",
            "evidence_report": str(evidence_report),
            "paper_bridge_apply_gate": {
                "fresh_signal": True,
                "can_request_paper_apply_now": True,
                "bridge_action": "add",
                "execution_parity_preflight": {
                    "source_event_key": "event-1",
                    "source_event_ts": "2026-01-01T00:00:00+00:00",
                },
            },
            "signal_wait_plan": {
                "max_signal_age_minutes": 15,
            },
            "pre_apply_backup_plan": {
                "status": "ready_required_before_paper_apply",
                "backup_dir": "reports/db_recovery/market_state_rotation_v6_bridge_tick",
                "verification_required_fields": [
                    "pre_apply_backup.created == true",
                    "pre_apply_backup.quick_check == 'ok'",
                    "pre_apply_backup.backup_path is not empty",
                ],
                "no_live_order_sent": True,
            },
            "launch_readiness": {
                "tiny_canary_evidence_ready": False,
                "paper_bridge_handoff": {
                    "status": "paper_apply_review_available",
                    "dry_run_command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                        "--quote-samples-per-tick 0 --refresh-market-data-before-run "
                        "--max-signal-age-minutes 15 "
                        "--report-dir reports/dry"
                    ),
                    "apply_command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                        "--apply-paper-bridge --quote-samples-per-tick 0 --refresh-market-data-before-run "
                        "--max-signal-age-minutes 15 "
                        "--pre-apply-backup-dir reports/db_recovery/market_state_rotation_v6_bridge_tick "
                        "--report-dir reports/apply"
                    ),
                    "apply_allowed_now": True,
                },
            },
        },
        progress={},
        runtime_progress={},
        risk_caps={"configured": True},
        microstructure_watch={},
    )

    packet = handoff["paper_apply_operator_packet"]
    assert packet["status"] == "ready_for_operator_review"
    assert packet["source_event_key"] == "event-1"
    assert packet["source_event_ts"] == "2026-01-01T00:00:00+00:00"
    assert packet["bridge_action"] == "add"
    assert packet["packet_generated_at"] == "2026-01-01T00:00:00+00:00"
    assert packet["operator_review_window_minutes"] == 15.0
    assert packet["operator_review_deadline_utc"] == "2026-01-01T00:15:00+00:00"
    assert packet["operator_review_deadline_active"] is True
    assert packet["operator_review_deadline_preserved_from_previous_watch"] is False
    assert packet["operator_review_deadline_anchor"] == "current_pre_apply_evidence_report"
    assert packet["deadline_policy"] == "apply_command_expires_at_operator_review_deadline_rerun_dry_run_after_deadline"
    assert "--refresh-market-data-before-run" in packet["rerun_command_after_deadline"]
    assert "--max-signal-age-minutes 15" in packet["rerun_command_after_deadline"]
    assert packet["command_safety"]["status"] == "PASS"
    assert packet["command_safety"]["blockers"] == []
    assert packet["pre_apply_evidence_report_status"]["status"] == "fresh"
    assert packet["pre_apply_evidence_report_status"]["exists"] is True
    assert packet["pre_apply_evidence_report_status"]["age_minutes"] == 0.0
    assert "--apply-paper-bridge" in packet["apply_command_allowed_now"]
    assert "--apply-paper-bridge" in packet["apply_command_when_gate_allows"]
    assert packet["pre_apply_backup_plan"]["backup_dir"] == "reports/db_recovery/market_state_rotation_v6_bridge_tick"
    assert "pre_apply_backup.quick_check == 'ok'" in packet["backup_verification_required_fields"]
    assert "rerun_dry_run_if_operator_review_deadline_has_passed" in packet["operator_sequence"]
    assert f"--before-evidence-report {evidence_report}" in packet[
        "post_apply_execution_parity_review_command"
    ]
    assert packet["order_submission_allowed"] is False
    assert packet["no_live_order_sent"] is True


def test_operator_handoff_preserves_paper_apply_review_deadline_for_same_signal(tmp_path) -> None:
    evidence_report = tmp_path / "market_state_rotation_v6_evidence_cycle.json"
    evidence_report.write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T00:05:00+00:00",
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )
    previous_payload = {
        "latest_run": {
            "paper_bridge_apply_gate": {
                "execution_parity_preflight": {
                    "source_event_key": "event-1",
                    "source_event_ts": "2026-01-01T00:00:00+00:00",
                }
            }
        },
        "operator_handoff": {
            "paper_apply_operator_packet": {
                "status": "ready_for_operator_review",
                "packet_generated_at": "2026-01-01T00:00:00+00:00",
                "operator_review_deadline_utc": "2026-01-01T00:15:00+00:00",
                "no_live_order_sent": True,
            }
        },
    }

    handoff = watch._operator_handoff(
        latest={
            "generated_at": "2026-01-01T00:10:00+00:00",
            "evidence_report": str(evidence_report),
            "paper_bridge_apply_gate": {
                "fresh_signal": True,
                "can_request_paper_apply_now": True,
                "bridge_action": "add",
                "execution_parity_preflight": {
                    "source_event_key": "event-1",
                    "source_event_ts": "2026-01-01T00:00:00+00:00",
                },
            },
            "signal_wait_plan": {
                "fresh_signal": True,
                "max_signal_age_minutes": 15,
            },
            "launch_readiness": {
                "paper_bridge_handoff": {
                    "status": "paper_apply_review_available",
                    "dry_run_command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                        "--quote-samples-per-tick 0 --refresh-market-data-before-run "
                        "--max-signal-age-minutes 15 "
                        "--report-dir reports/dry"
                    ),
                    "apply_command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                        "--apply-paper-bridge --quote-samples-per-tick 0 --refresh-market-data-before-run "
                        "--max-signal-age-minutes 15 "
                        "--pre-apply-backup-dir reports/db_recovery/market_state_rotation_v6_bridge_tick "
                        "--report-dir reports/apply"
                    ),
                    "apply_allowed_now": True,
                },
            },
        },
        progress={},
        runtime_progress={},
        risk_caps={"configured": True},
        microstructure_watch={},
        previous_payload=previous_payload,
    )

    packet = handoff["paper_apply_operator_packet"]
    assert packet["status"] == "ready_for_operator_review"
    assert packet["packet_generated_at"] == "2026-01-01T00:00:00+00:00"
    assert packet["operator_review_deadline_utc"] == "2026-01-01T00:15:00+00:00"
    assert packet["operator_review_deadline_preserved_from_previous_watch"] is True
    assert packet["operator_review_deadline_anchor"] == "previous_watch_same_source_event"
    assert packet["source_event_key"] == "event-1"
    assert packet["order_submission_allowed"] is False
    assert packet["no_live_order_sent"] is True


def test_operator_handoff_resets_paper_apply_review_deadline_for_new_signal(tmp_path) -> None:
    evidence_report = tmp_path / "market_state_rotation_v6_evidence_cycle.json"
    evidence_report.write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T00:10:00+00:00",
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )
    previous_payload = {
        "latest_run": {
            "paper_bridge_apply_gate": {
                "execution_parity_preflight": {
                    "source_event_key": "event-1",
                    "source_event_ts": "2026-01-01T00:00:00+00:00",
                }
            }
        },
        "operator_handoff": {
            "paper_apply_operator_packet": {
                "status": "ready_for_operator_review",
                "packet_generated_at": "2026-01-01T00:00:00+00:00",
                "operator_review_deadline_utc": "2026-01-01T00:15:00+00:00",
                "no_live_order_sent": True,
            }
        },
    }

    handoff = watch._operator_handoff(
        latest={
            "generated_at": "2026-01-01T00:10:00+00:00",
            "evidence_report": str(evidence_report),
            "paper_bridge_apply_gate": {
                "fresh_signal": True,
                "can_request_paper_apply_now": True,
                "bridge_action": "remove",
                "execution_parity_preflight": {
                    "source_event_key": "event-2",
                    "source_event_ts": "2026-01-01T00:10:00+00:00",
                },
            },
            "signal_wait_plan": {
                "fresh_signal": True,
                "max_signal_age_minutes": 15,
            },
            "launch_readiness": {
                "paper_bridge_handoff": {
                    "status": "paper_apply_review_available",
                    "dry_run_command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                        "--quote-samples-per-tick 0 --refresh-market-data-before-run "
                        "--max-signal-age-minutes 15 "
                        "--report-dir reports/dry"
                    ),
                    "apply_command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                        "--apply-paper-bridge --quote-samples-per-tick 0 --refresh-market-data-before-run "
                        "--max-signal-age-minutes 15 "
                        "--pre-apply-backup-dir reports/db_recovery/market_state_rotation_v6_bridge_tick "
                        "--report-dir reports/apply"
                    ),
                    "apply_allowed_now": True,
                },
            },
        },
        progress={},
        runtime_progress={},
        risk_caps={"configured": True},
        microstructure_watch={},
        previous_payload=previous_payload,
    )

    packet = handoff["paper_apply_operator_packet"]
    assert packet["status"] == "ready_for_operator_review"
    assert packet["packet_generated_at"] == "2026-01-01T00:10:00+00:00"
    assert packet["operator_review_deadline_utc"] == "2026-01-01T00:25:00+00:00"
    assert packet["operator_review_deadline_preserved_from_previous_watch"] is False
    assert packet["operator_review_deadline_anchor"] == "current_pre_apply_evidence_report"
    assert packet["source_event_key"] == "event-2"
    assert packet["order_submission_allowed"] is False
    assert packet["no_live_order_sent"] is True


def test_operator_handoff_blocks_apply_when_operator_command_safety_fails() -> None:
    handoff = watch._operator_handoff(
        latest={
            "generated_at": "2026-01-01T00:00:00+00:00",
            "evidence_report": "reports/pre/market_state_rotation_v6_evidence_cycle.json",
            "paper_bridge_apply_gate": {
                "fresh_signal": True,
                "can_request_paper_apply_now": True,
            },
            "signal_wait_plan": {
                "max_signal_age_minutes": 15,
            },
            "launch_readiness": {
                "tiny_canary_evidence_ready": False,
                "paper_bridge_handoff": {
                    "status": "paper_apply_review_available",
                    "dry_run_command": "dry-run-without-refresh",
                    "apply_command": "paper-apply-without-required-flags",
                    "apply_allowed_now": True,
                },
            },
        },
        progress={},
        runtime_progress={},
        risk_caps={"configured": True},
        microstructure_watch={},
    )

    packet = handoff["paper_apply_operator_packet"]
    assert handoff["status"] == "blocked_by_operator_command_safety"
    assert handoff["next_action"] == "paper_apply_operator_command_safety"
    assert handoff["paper_apply_allowed_now"] is False
    assert packet["status"] == "blocked_by_operator_command_safety"
    assert packet["blocker"] == "paper_apply_operator_command_safety"
    assert packet["apply_command_allowed_now"] is None
    assert packet["operator_review_deadline_active"] is False
    assert packet["command_safety"]["status"] == "FAIL"
    assert "apply_command_must_use_apply_paper_bridge" in packet["command_safety"]["blockers"]
    assert "apply_command_must_refresh_market_data_before_run" in packet["command_safety"]["blockers"]
    assert "apply_command_must_use_max_signal_age_minutes" in packet["command_safety"]["blockers"]
    assert "apply_command_must_write_report_dir" in packet["command_safety"]["blockers"]
    assert "dry_run_command_must_write_report_dir" in packet["command_safety"]["blockers"]
    assert "dry_run_command_must_use_quote_samples_per_tick_0" in packet["command_safety"]["blockers"]
    assert "dry_run_command_must_use_max_signal_age_minutes" in packet["command_safety"]["blockers"]
    assert packet["order_submission_allowed"] is False


def test_operator_handoff_blocks_apply_when_pre_apply_evidence_report_is_stale(tmp_path) -> None:
    evidence_report = tmp_path / "market_state_rotation_v6_evidence_cycle.json"
    evidence_report.write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T00:00:00+00:00",
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    handoff = watch._operator_handoff(
        latest={
            "generated_at": "2026-01-01T00:30:00+00:00",
            "evidence_report": str(evidence_report),
            "paper_bridge_apply_gate": {
                "fresh_signal": True,
                "can_request_paper_apply_now": True,
            },
            "signal_wait_plan": {
                "max_signal_age_minutes": 15,
            },
            "launch_readiness": {
                "tiny_canary_evidence_ready": False,
                "paper_bridge_handoff": {
                    "status": "paper_apply_review_available",
                    "dry_run_command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                        "--quote-samples-per-tick 0 --refresh-market-data-before-run "
                        "--max-signal-age-minutes 15 --report-dir reports/validation/diagnostics/dry"
                    ),
                    "apply_command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                        "--apply-paper-bridge --quote-samples-per-tick 0 --refresh-market-data-before-run "
                        "--max-signal-age-minutes 15 "
                        "--pre-apply-backup-dir reports/db_recovery/market_state_rotation_v6_bridge_tick "
                        "--report-dir reports/validation/diagnostics/apply"
                    ),
                    "apply_allowed_now": True,
                },
            },
        },
        progress={},
        runtime_progress={},
        risk_caps={"configured": True},
        microstructure_watch={},
    )

    packet = handoff["paper_apply_operator_packet"]
    assert handoff["status"] == "blocked_by_pre_apply_evidence_report"
    assert handoff["next_action"] == "pre_apply_evidence_report"
    assert handoff["paper_apply_allowed_now"] is False
    assert packet["status"] == "blocked_by_pre_apply_evidence_report"
    assert packet["blocker"] == "pre_apply_evidence_report"
    assert packet["apply_command_allowed_now"] is None
    assert packet["operator_review_deadline_active"] is False
    assert packet["deadline_policy"] == "pre_apply_evidence_report_failed_rerun_dry_run_before_apply"
    assert packet["pre_apply_evidence_report_status"]["status"] == "pre_apply_evidence_report_stale_for_review_window"
    assert packet["pre_apply_evidence_report_status"]["block_apply"] is True
    assert packet["pre_apply_evidence_report_status"]["age_minutes"] == 30.0
    assert packet["pre_apply_evidence_report_status"]["blockers"] == [
        "pre_apply_evidence_report_stale_for_review_window"
    ]
    assert packet["command_safety"]["status"] == "PASS"
    assert packet["order_submission_allowed"] is False
    assert packet["no_live_order_sent"] is True


def test_operator_handoff_surfaces_command_safety_preflight_before_fresh_signal() -> None:
    handoff = watch._operator_handoff(
        latest={
            "generated_at": "2026-01-01T00:00:00+00:00",
            "evidence_report": "reports/pre/market_state_rotation_v6_evidence_cycle.json",
            "paper_bridge_apply_gate": {
                "fresh_signal": False,
                "can_request_paper_apply_now": False,
            },
            "launch_readiness": {
                "tiny_canary_evidence_ready": False,
                "paper_bridge_handoff": {
                    "status": "blocked_waiting_for_fresh_signal",
                    "dry_run_command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                        "--quote-samples-per-tick 0 --refresh-market-data-before-run "
                        "--max-signal-age-minutes 15 "
                        "--report-dir reports/validation/diagnostics/<paper_dry_run_report_dir>"
                    ),
                    "apply_command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                        "--apply-paper-bridge --quote-samples-per-tick 0 --refresh-market-data-before-run "
                        "--max-signal-age-minutes 15 "
                        "--pre-apply-backup-dir reports/db_recovery/market_state_rotation_v6_bridge_tick "
                        "--report-dir reports/validation/diagnostics/<paper_apply_report_dir>"
                    ),
                    "apply_allowed_now": False,
                },
            },
        },
        progress={},
        runtime_progress={},
        risk_caps={"configured": True},
        microstructure_watch={},
    )

    packet = handoff["paper_apply_operator_packet"]
    assert handoff["status"] == "paper_apply_operator_command_safety_preflight_failed"
    assert handoff["next_action"] == "fix_operator_command_safety_before_waiting_for_fresh_signal"
    assert handoff["paper_apply_allowed_now"] is False
    assert packet["status"] == "operator_command_safety_preflight_failed"
    assert packet["blocker"] == "paper_apply_operator_command_safety"
    assert packet["command_safety"]["status"] == "FAIL"
    assert "dry_run_command_has_unresolved_placeholder" in packet["command_safety"]["blockers"]
    assert "apply_command_has_unresolved_placeholder" in packet["command_safety"]["blockers"]
    assert packet["operator_review_deadline_active"] is False
    assert packet["apply_command_allowed_now"] is None
    assert packet["order_submission_allowed"] is False
    assert packet["no_live_order_sent"] is True


def test_paper_apply_command_safety_blocks_missing_flag_values() -> None:
    safety = watch._paper_apply_command_safety(
        dry_run_command=(
            ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
            "--quote-samples-per-tick 0 --refresh-market-data-before-run --report-dir --dry-extra"
        ),
        apply_command=(
            ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
            "--apply-paper-bridge --quote-samples-per-tick 0 --refresh-market-data-before-run "
            "--pre-apply-backup-dir --report-dir"
        ),
    )

    assert safety["status"] == "FAIL"
    assert "dry_run_command_report_dir_value_missing" in safety["blockers"]
    assert "apply_command_pre_apply_backup_dir_value_missing" in safety["blockers"]
    assert "apply_command_report_dir_value_missing" in safety["blockers"]
    assert safety["order_submission_allowed"] is False
    assert safety["no_live_order_sent"] is True


def test_paper_apply_command_safety_requires_positive_max_signal_age() -> None:
    safety = watch._paper_apply_command_safety(
        dry_run_command=(
            ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
            "--quote-samples-per-tick 0 --refresh-market-data-before-run "
            "--max-signal-age-minutes 0 --report-dir reports/validation/diagnostics/dry"
        ),
        apply_command=(
            ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
            "--apply-paper-bridge --quote-samples-per-tick 0 --refresh-market-data-before-run "
            "--pre-apply-backup-dir reports/db_recovery/market_state_rotation_v6_bridge_tick "
            "--report-dir reports/validation/diagnostics/apply"
        ),
    )

    assert safety["status"] == "FAIL"
    assert "dry_run_command_max_signal_age_minutes_must_be_positive_integer" in safety["blockers"]
    assert "apply_command_must_use_max_signal_age_minutes" in safety["blockers"]
    assert safety["order_submission_allowed"] is False
    assert safety["no_live_order_sent"] is True


def test_paper_apply_command_safety_blocks_live_flag_equals_variants() -> None:
    safety = watch._paper_apply_command_safety(
        dry_run_command=(
            ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
            "--quote-samples-per-tick 0 --refresh-market-data-before-run "
            "--max-signal-age-minutes 15 --report-dir reports/validation/diagnostics/dry "
            "--enable-live=true"
        ),
        apply_command=(
            ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
            "--apply-paper-bridge --quote-samples-per-tick 0 --refresh-market-data-before-run "
            "--max-signal-age-minutes 15 "
            "--pre-apply-backup-dir reports/db_recovery/market_state_rotation_v6_bridge_tick "
            "--report-dir reports/validation/diagnostics/apply --submit-live-order=true"
        ),
    )

    assert safety["status"] == "FAIL"
    assert "live_order_flag_present_in_operator_command" in safety["blockers"]
    assert safety["order_submission_allowed"] is False
    assert safety["no_live_order_sent"] is True


def test_paper_apply_command_safety_blocks_unresolved_placeholders() -> None:
    safety = watch._paper_apply_command_safety(
        dry_run_command=(
            ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
            "--quote-samples-per-tick 0 --refresh-market-data-before-run "
            "--max-signal-age-minutes 15 "
            "--report-dir reports/validation/diagnostics/<paper_dry_run_report_dir>"
        ),
        apply_command=(
            ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
            "--apply-paper-bridge --quote-samples-per-tick 0 --refresh-market-data-before-run "
            "--max-signal-age-minutes 15 "
            "--pre-apply-backup-dir reports/db_recovery/market_state_rotation_v6_bridge_tick "
            "--report-dir reports/validation/diagnostics/<paper_apply_report_dir>"
        ),
    )

    assert safety["status"] == "FAIL"
    assert "dry_run_command_has_unresolved_placeholder" in safety["blockers"]
    assert "apply_command_has_unresolved_placeholder" in safety["blockers"]
    assert safety["order_submission_allowed"] is False
    assert safety["no_live_order_sent"] is True


def test_paper_apply_command_safety_warns_on_nonstandard_report_scopes_without_blocking() -> None:
    safety = watch._paper_apply_command_safety(
        dry_run_command=(
            ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
            "--quote-samples-per-tick 0 --refresh-market-data-before-run "
            "--max-signal-age-minutes 15 --report-dir reports/dry"
        ),
        apply_command=(
            ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
            "--apply-paper-bridge --quote-samples-per-tick 0 --refresh-market-data-before-run "
            "--max-signal-age-minutes 15 "
            "--pre-apply-backup-dir reports/recovery "
            "--report-dir reports/apply"
        ),
    )

    assert safety["status"] == "PASS"
    assert safety["blockers"] == []
    assert "dry_run_report_dir_outside_recommended_diagnostics_scope" in safety["warnings"]
    assert "apply_report_dir_outside_recommended_diagnostics_scope" in safety["warnings"]
    assert "apply_pre_apply_backup_dir_outside_recommended_recovery_scope" in safety["warnings"]
    assert safety["dry_run_report_dir"] == "reports/dry"
    assert safety["apply_report_dir"] == "reports/apply"
    assert safety["apply_pre_apply_backup_dir"] == "reports/recovery"
    assert safety["order_submission_allowed"] is False
    assert safety["no_live_order_sent"] is True


def test_safe_next_action_preserves_execution_parity_credit_forecast_for_paper_apply() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "real_paper_lifecycle_rows",
                "can_resolve_now": True,
                "dry_run_command": "dry-run",
                "command": "paper-apply",
                "reason": "paper_bridge_apply_available_after_operator_review_and_verified_backup",
                "execution_parity_will_credit_current_apply": True,
                "execution_parity_events_needed": 20,
                "execution_parity_events_needed_after_current_apply": 19,
                "execution_parity_creditable_actions": ["remove"],
                "post_apply_execution_parity_review_command": (
                    ".venv/bin/python scripts/run_market_state_rotation_v6_paper_apply_parity_review.py "
                    "--before-evidence-report reports/pre.json "
                    "--after-evidence-report <post_apply_evidence_report> "
                    "--report-dir reports/validation/diagnostics/<paper_apply_parity_review_report_dir> "
                    "--write-report"
                ),
                "paper_apply_operator_packet": {
                    "status": "ready_for_operator_review",
                    "pre_apply_backup_plan": {"status": "ready_required_before_paper_apply"},
                    "operator_review_deadline_utc": "2026-01-01T00:15:00+00:00",
                    "deadline_policy": "apply_command_expires_at_operator_review_deadline_rerun_dry_run_after_deadline",
                    "post_apply_execution_parity_review_command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_paper_apply_parity_review.py "
                        "--before-evidence-report reports/pre.json "
                        "--after-evidence-report <post_apply_evidence_report> "
                        "--report-dir reports/validation/diagnostics/<paper_apply_parity_review_report_dir> "
                        "--write-report"
                    ),
                    "no_live_order_sent": True,
                },
                "no_live_order_sent": True,
            }
        ],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": True},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    action = plan["primary_action"]
    assert action["action_type"] == "operator_review_paper_bridge_apply"
    assert action["execution_parity_will_credit_current_apply"] is True
    assert action["execution_parity_events_needed"] == 20
    assert action["execution_parity_events_needed_after_current_apply"] == 19
    assert action["execution_parity_creditable_actions"] == ["remove"]
    assert action["paper_apply_operator_packet"]["status"] == "ready_for_operator_review"
    assert action["paper_apply_operator_packet"]["pre_apply_backup_plan"]["status"] == (
        "ready_required_before_paper_apply"
    )
    assert action["paper_apply_operator_packet"]["operator_review_deadline_utc"] == "2026-01-01T00:15:00+00:00"
    assert action["paper_apply_operator_packet"]["operator_review_deadline_expired"] is False
    assert action["paper_apply_operator_packet"]["operator_review_deadline_remaining_seconds"] == 900.0
    assert action["paper_apply_operator_packet"]["operator_review_deadline_remaining_minutes"] == 15.0
    assert "run_market_state_rotation_v6_paper_apply_parity_review.py" in action[
        "post_apply_execution_parity_review_command"
    ]
    assert "<paper_apply_parity_review_report_dir>" not in action["post_apply_execution_parity_review_command"]
    assert "--after-evidence-report <post_apply_evidence_report>" in action[
        "post_apply_execution_parity_review_command"
    ]
    assert action["order_submission_allowed"] is False


def test_safe_next_action_reruns_dry_run_when_paper_apply_review_deadline_expired() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "real_paper_lifecycle_rows",
                "can_resolve_now": True,
                "dry_run_command": "dry-run",
                "command": "paper-apply",
                "reason": "paper_bridge_apply_available_after_operator_review_and_verified_backup",
                "paper_apply_operator_packet": {
                    "status": "ready_for_operator_review",
                    "pre_apply_backup_plan": {"status": "ready_required_before_paper_apply"},
                    "operator_review_deadline_utc": "2026-01-01T00:15:00+00:00",
                    "deadline_policy": "apply_command_expires_at_operator_review_deadline_rerun_dry_run_after_deadline",
                    "rerun_command_after_deadline": "dry-run",
                    "apply_command_allowed_now": "paper-apply",
                    "no_live_order_sent": True,
                },
                "no_live_order_sent": True,
            }
        ],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": True},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 0, 16, tzinfo=UTC),
    )

    action = plan["primary_action"]
    assert action["action_type"] == "rerun_paper_bridge_dry_run_after_operator_review_deadline"
    assert action["command"] == "dry-run"
    assert action["follow_up_command_when_reviewed"] is None
    assert action["paper_apply_operator_packet"]["status"] == "operator_review_deadline_expired"
    assert action["paper_apply_operator_packet"]["apply_command_allowed_now"] is None
    assert action["paper_apply_operator_packet"]["operator_review_deadline_expired"] is True
    assert action["paper_apply_operator_packet"]["operator_review_deadline_remaining_seconds"] == 0.0
    assert action["paper_apply_operator_packet"]["operator_review_deadline_remaining_minutes"] == 0.0
    assert action["order_submission_allowed"] is False
    assert action["no_live_order_sent"] is True


def test_safe_next_action_prioritizes_operator_command_safety_failure() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "current_fresh_signal",
                "command": "monitor-signal",
                "reason": "must_wait_for_realtime_v6_add_or_remove_signal_do_not_force_entry",
                "next_monitor_after_utc": "2026-01-01T00:00:00+00:00",
                "no_live_order_sent": True,
            }
        ],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={
            "paper_apply_allowed_now": False,
            "paper_apply_operator_packet": {
                "status": "operator_command_safety_preflight_failed",
                "command_safety": {
                    "status": "FAIL",
                    "blockers": ["dry_run_command_has_unresolved_placeholder"],
                    "warnings": ["dry_run_report_dir_outside_recommended_diagnostics_scope"],
                    "dry_run_report_dir": "reports/<dry>",
                    "apply_report_dir": "reports/validation/diagnostics/apply",
                    "apply_pre_apply_backup_dir": "reports/db_recovery/market_state_rotation_v6_bridge_tick",
                    "no_live_order_sent": True,
                },
                "no_live_order_sent": True,
            },
        },
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    action = plan["primary_action"]
    assert action["action_type"] == "fix_paper_apply_operator_command_safety"
    assert action["target_gate"] == "paper_apply_operator_command_safety"
    assert action["can_run_now"] is True
    assert action["requires_operator_review"] is True
    assert action["command"] is None
    assert action["blockers"] == ["dry_run_command_has_unresolved_placeholder"]
    assert action["warnings"] == ["dry_run_report_dir_outside_recommended_diagnostics_scope"]
    assert action["paper_apply_operator_packet"]["status"] == "operator_command_safety_preflight_failed"
    assert action["order_submission_allowed"] is False
    assert action["no_live_order_sent"] is True


def test_safe_next_action_prioritizes_stale_pre_apply_evidence_report() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "real_paper_lifecycle_rows",
                "can_resolve_now": False,
                "monitor_command": (
                    ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                    "--quote-samples-per-tick 0 --refresh-market-data-before-run "
                    "--report-dir reports/validation/diagnostics/"
                    "market_state_rotation_v6_signal_monitor_20260101_120000Z"
                ),
                "fresh_signal": True,
                "reason": "fresh_signal_seen_but_paper_bridge_apply_gate_not_available",
                "no_live_order_sent": True,
            }
        ],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={
            "paper_apply_allowed_now": False,
            "paper_apply_operator_packet": {
                "status": "blocked_by_pre_apply_evidence_report",
                "rerun_command_after_deadline": "rerun-dry-run",
                "pre_apply_evidence_report_status": {
                    "status": "pre_apply_evidence_report_stale_for_review_window",
                    "block_apply": True,
                    "blockers": ["pre_apply_evidence_report_stale_for_review_window"],
                    "no_live_order_sent": True,
                },
                "no_live_order_sent": True,
            },
        },
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    action = plan["primary_action"]
    assert action["action_type"] == "rerun_paper_bridge_dry_run_for_fresh_pre_apply_evidence_report"
    assert action["target_gate"] == "pre_apply_evidence_report"
    assert action["command"] == "rerun-dry-run"
    assert action["blockers"] == ["pre_apply_evidence_report_stale_for_review_window"]
    assert action["pre_apply_evidence_report_status"]["status"] == (
        "pre_apply_evidence_report_stale_for_review_window"
    )
    assert action["follow_up_command_when_reviewed"] is None
    assert action["order_submission_allowed"] is False
    assert action["no_live_order_sent"] is True


def test_operator_handoff_blocks_repeated_remove_apply_after_no_open_plan() -> None:
    handoff = watch._operator_handoff(
        latest={
            "paper_bridge_apply_gate": {
                "bridge_action": "remove",
                "can_request_paper_apply_now": True,
            },
            "launch_readiness": {
                "paper_bridge_handoff": {
                    "apply_allowed_now": True,
                    "status": "paper_apply_review_available",
                },
                "operator_commands": {
                    "paper_bridge_dry_run": "dry-run",
                    "paper_apply_only_after_fresh_signal": "paper-apply",
                },
                "next_blocker": {"gate": "real_paper_lifecycle_rows"},
            },
            "execution_parity_collection_plan": {
                "estimated_future_paper_apply_events_needed": 20,
                "estimated_events_needed_after_current_creditable_apply": 19,
                "will_credit_current_apply_after_operator_review": True,
                "currently_creditable_actions": ["remove"],
            },
        },
        progress={"fresh_signal_seen": True},
        runtime_progress={},
        risk_caps={"configured": True},
        microstructure_watch={},
        recent_paper_apply={
            "status": "available",
            "generated_at": "2026-01-01T12:00:00+00:00",
            "bridge_action": "remove",
            "bridge_status": "no_open_v6_paper_plan",
            "source_report": "reports/recent.json",
            "no_live_order_sent": True,
        },
        recent_paper_review={
            "status": "available",
            "generated_at": "2026-01-01T12:05:00+00:00",
            "bridge_action": "remove",
            "bridge_status": "dry_run_actionable",
            "source_report": "reports/review.json",
            "no_live_order_sent": True,
        },
    )

    assert handoff["paper_apply_allowed_now"] is False
    assert handoff["status"] == "paper_bridge_remove_apply_no_open_plan_waiting_for_add"
    assert handoff["paper_apply_retry_blocker"]["blocked"] is True
    assert handoff["paper_apply_retry_blocker"]["next_monitor_after_utc"] == "2026-01-01T12:20:00+00:00"
    assert handoff["recent_paper_review"]["source_report"] == "reports/review.json"
    assert handoff["execution_parity_events_needed"] == 20
    assert handoff["execution_parity_events_needed_after_current_apply"] == 19
    assert handoff["execution_parity_creditable_actions"] == ["remove"]
    assert handoff["order_submission_allowed"] is False


def test_operator_handoff_blocks_paper_apply_after_failed_parity_review() -> None:
    handoff = watch._operator_handoff(
        latest={
            "paper_bridge_apply_gate": {
                "bridge_action": "remove",
                "can_request_paper_apply_now": True,
            },
            "launch_readiness": {
                "paper_bridge_handoff": {
                    "apply_allowed_now": True,
                    "status": "paper_apply_review_available",
                },
                "operator_commands": {
                    "paper_bridge_dry_run": "dry-run",
                    "paper_apply_only_after_fresh_signal": "paper-apply",
                },
                "next_blocker": {"gate": "real_paper_lifecycle_rows"},
            },
            "execution_parity_collection_plan": {
                "estimated_future_paper_apply_events_needed": 20,
                "estimated_events_needed_after_current_creditable_apply": 19,
                "will_credit_current_apply_after_operator_review": True,
                "currently_creditable_actions": ["remove"],
            },
        },
        progress={"fresh_signal_seen": True},
        runtime_progress={},
        risk_caps={"configured": True},
        microstructure_watch={},
        recent_paper_apply_parity_review={
            "status": "paper_apply_parity_credit_missing",
            "source_report": "reports/parity_review.json",
            "blocks_next_paper_apply": True,
            "blockers": ["expected_execution_parity_credit_missing"],
            "next_actions": ["inspect_paper_bridge_apply_result_and_lifecycle_export"],
            "recommended_command": (
                ".venv/bin/python scripts/run_market_state_rotation_v6_paper_apply_parity_review.py "
                "--before-evidence-report reports/pre.json "
                "--after-evidence-report reports/apply.json "
                "--report-dir reports/validation/diagnostics/<paper_apply_parity_review_report_dir> "
                "--write-report"
            ),
            "no_live_order_sent": True,
        },
    )

    assert handoff["paper_apply_allowed_now"] is False
    assert handoff["status"] == "paper_apply_parity_review_blocking_next_apply"
    assert handoff["paper_apply_parity_review_blocker"]["blocked"] is True
    assert handoff["paper_apply_parity_review_blocker"]["source_report"] == "reports/parity_review.json"
    assert handoff["paper_apply_parity_review_blocker"]["blockers"] == ["expected_execution_parity_credit_missing"]
    assert "--after-evidence-report reports/apply.json" in handoff["paper_apply_parity_review_blocker"][
        "recommended_command"
    ]
    assert handoff["order_submission_allowed"] is False


def test_safe_next_action_prioritizes_failed_paper_apply_parity_review() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "real_paper_lifecycle_rows",
                "fresh_signal": True,
                "paper_apply_parity_review_blocked": True,
                "paper_apply_parity_review_blocker": {
                    "blocked": True,
                    "status": "paper_apply_parity_credit_missing",
                    "source_report": "reports/parity_review.json",
                    "blockers": ["expected_execution_parity_credit_missing"],
                    "next_actions": ["inspect_paper_bridge_apply_result_and_lifecycle_export"],
                    "recommended_command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_paper_apply_parity_review.py "
                        "--before-evidence-report reports/pre.json "
                        "--after-evidence-report reports/apply.json "
                        "--report-dir reports/validation/diagnostics/<paper_apply_parity_review_report_dir> "
                        "--write-report"
                    ),
                },
                "reason": "recent_paper_apply_parity_review_blocks_next_apply",
            },
            {
                "gate": "shadow_runtime_24h_observed",
                "reason": "requires_calendar_runtime_observation_not_backtest_substitution",
            },
        ],
        runtime_progress={"remaining_hours": 16.0, "progress_pct": 33.0},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    action = plan["primary_action"]
    assert action["action_type"] == "resolve_paper_apply_parity_review_blocker"
    assert action["can_run_now"] is True
    assert action["priority"] == 10
    assert action["source_report"] == "reports/parity_review.json"
    assert action["blockers"] == ["expected_execution_parity_credit_missing"]
    assert action["next_actions"] == ["inspect_paper_bridge_apply_result_and_lifecycle_export"]
    assert "run_market_state_rotation_v6_paper_apply_parity_review.py" in action["command"]
    assert "--after-evidence-report reports/apply.json" in action["command"]
    assert "<paper_apply_parity_review_report_dir>" not in action["command"]
    assert action["order_submission_allowed"] is False


def test_recent_paper_apply_parity_review_detects_blocking_report(tmp_path) -> None:
    report_dir = tmp_path / "evidence" / "market_state_rotation_v6_paper_apply_parity_review_latest"
    report_dir.mkdir(parents=True)
    generated_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    (report_dir / "market_state_rotation_v6_paper_apply_parity_review.json").write_text(
        json.dumps(
            {
                "generated_at": generated_at.isoformat(),
                "status": "paper_apply_parity_credit_missing",
                "no_live_order_sent": True,
                "expected_credit_from_before_forecast": 1,
                "actual_journal_row_delta": 0,
                "new_journal_row_count": 0,
                "credit_confirmed": False,
                "blockers": ["expected_execution_parity_credit_missing"],
                "next_actions": ["inspect_paper_bridge_apply_result_and_lifecycle_export"],
            }
        ),
        encoding="utf-8",
    )

    review = watch._recent_paper_apply_parity_review(
        evidence_root=tmp_path / "evidence",
        current_at=generated_at + timedelta(minutes=5),
    )

    assert review["status"] == "paper_apply_parity_credit_missing"
    assert review["blocks_next_paper_apply"] is True
    assert review["source_report"].endswith("market_state_rotation_v6_paper_apply_parity_review.json")
    assert review["blockers"] == ["expected_execution_parity_credit_missing"]
    assert review["next_actions"] == ["inspect_paper_bridge_apply_result_and_lifecycle_export"]
    assert review["no_live_order_sent"] is True


def test_recent_meta_router_promotion_gate_summarizes_latest_report(tmp_path) -> None:
    report_dir = tmp_path / "evidence" / "market_state_rotation_v6_meta_router_promotion_gate"
    report_dir.mkdir(parents=True)
    generated_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    (report_dir / "market_state_rotation_v6_meta_router_promotion_gate.json").write_text(
        json.dumps(
            {
                "generated_at": generated_at.isoformat(),
                "status": "meta_router_promotion_gate_complete",
                "no_live_order_sent": True,
                "report_path": "reports/validation/diagnostics/promotion_gate.json",
                "expected_operator_lineage_source_report": "reports/validation/diagnostics/promotion_gate.json",
                "promotion_decision": "paper_ready_pending_execution_parity",
                "decision_reasons": ["formal_wfo_passed", "paper_readiness_passed"],
                "next_actions": ["collect_paper_execution_parity_rows_before_tiny_canary_or_full_live"],
                "next_blocker": "live_or_paper_execution_parity_available",
                "input_operator_lineage_review_report": None,
                "operator_lineage_review_template_report": (
                    "reports/validation/diagnostics/market_state_rotation_v6_meta_router_promotion_gate/"
                    "market_state_rotation_v6_operator_lineage_review_template.json"
                ),
                "operator_lineage_review_skeleton_report": (
                    "reports/validation/diagnostics/market_state_rotation_v6_meta_router_promotion_gate/"
                    "market_state_rotation_v6_operator_lineage_review_skeleton.json"
                ),
                "performance_upgrade_ready": False,
                "performance_delta_status": "decomposition_only_no_execution_delta",
                "performance_upgrade_blockers": [
                    "candidate_does_not_change_return_drawdown_cost_or_trade_events"
                ],
                "overfit_blockers": ["conditional_winner_refill_overlay_requires_shadow_holdout_review"],
                "conditional_overfit_holdout_audit": {
                    "status": "historical_proxy_pass_real_shadow_required",
                    "proxy_passed": True,
                    "real_shadow_still_required": True,
                    "tail_holdout_proxy": {"passed": True, "return_delta_pct": 2.3921},
                    "no_live_order_sent": True,
                },
                "readiness_candidate_alignment": {"passed": True, "blockers": []},
                "candidate_switch_policy": {
                    "status": "candidate_switch_blocked_pending_readiness_or_parity",
                    "default_route": "primary_return_candidate",
                    "defensive_route": "risk_adjusted_compression_candidate",
                    "defensive_candidate": {
                        "recipe_id": "selective_mode_loss_after_selection_light",
                        "return_giveback_fraction_vs_baseline": 0.04,
                        "drawdown_reduction_fraction_vs_baseline": 0.1919,
                    },
                    "defensive_lineage_review": {
                        "required": True,
                        "status": "pending_operator_lineage_review",
                        "operator_review": {"status": "missing", "matched": False},
                        "operator_review_template": {
                            "candidate_recipe_id": "selective_mode_loss_after_selection_light",
                            "reviewed_folds": [11],
                            "review_packet_summary": (
                                "lineage_watch_is_limited_to_intentional_size_overlay_folds"
                            ),
                        },
                    },
                    "defensive_route_eligible_after_current_gates": False,
                    "next_action": "keep_primary_candidate_default_until_readiness_execution_parity_and_lineage_review_pass",
                    "promotion_blockers": [
                        "execution_parity_not_passed",
                        "live_or_paper_execution_parity_available",
                    ],
                    "no_live_order_sent": True,
                },
                "candidate": {
                    "recipe_id": "one_way_trim_tax_light_formal",
                    "decision": "promotion_candidate_after_formal_wfo",
                    "compounded_return_pct": 25857.0416,
                    "max_drawdown_pct": 14.9814,
                    "avg_cost_drag_pct": 7.5657,
                    "trade_like_events": 290,
                    "return_delta_vs_baseline_pct": 0.0,
                    "drawdown_delta_vs_baseline_pct": 0.0,
                    "cost_delta_vs_baseline_pct": 0.0,
                    "trade_event_delta_vs_baseline": 0,
                    "execution_change_audit": {
                        "status": "decomposition_only_no_execution_delta",
                        "performance_upgrade_ready": False,
                        "return_delta_vs_baseline_pct": 0.0,
                        "drawdown_delta_vs_baseline_pct": 0.0,
                        "cost_delta_vs_baseline_pct": 0.0,
                        "trade_event_delta_vs_baseline": 0,
                    },
                    "overfit_audit": {
                        "status": "requires_shadow_holdout_review",
                        "blockers": ["conditional_winner_refill_overlay_requires_shadow_holdout_review"],
                    },
                },
                "readiness": {
                    "stage": "paper_only",
                    "ready_for_paper": True,
                    "ready_for_tiny_canary": False,
                    "ready_for_full_live": False,
                    "blockers": ["live_or_paper_execution_parity_available"],
                    "warnings": ["role_add_concentration"],
                    "execution_parity": {"available": True, "passed": False},
                },
            }
        ),
        encoding="utf-8",
    )

    report = watch._recent_meta_router_promotion_gate(
        evidence_root=tmp_path / "evidence",
        current_at=generated_at + timedelta(minutes=5),
    )

    assert report["status"] == "meta_router_promotion_gate_complete"
    assert report["stale"] is False
    assert report["report_path"] == "reports/validation/diagnostics/promotion_gate.json"
    assert report["expected_operator_lineage_source_report"] == (
        "reports/validation/diagnostics/promotion_gate.json"
    )
    assert report["promotion_decision"] == "paper_ready_pending_execution_parity"
    assert report["next_blocker"] == "live_or_paper_execution_parity_available"
    assert report["performance_upgrade_ready"] is False
    assert report["performance_delta_status"] == "decomposition_only_no_execution_delta"
    assert report["performance_upgrade_blockers"] == [
        "candidate_does_not_change_return_drawdown_cost_or_trade_events"
    ]
    assert report["candidate"]["recipe_id"] == "one_way_trim_tax_light_formal"
    assert report["candidate"]["return_delta_vs_baseline_pct"] == 0.0
    assert report["candidate"]["execution_change_audit"]["status"] == "decomposition_only_no_execution_delta"
    assert report["overfit_audit"]["status"] == "requires_shadow_holdout_review"
    assert report["overfit_blockers"] == [
        "conditional_winner_refill_overlay_requires_shadow_holdout_review"
    ]
    assert report["candidate"]["overfit_audit"]["blockers"] == [
        "conditional_winner_refill_overlay_requires_shadow_holdout_review"
    ]
    assert report["conditional_overfit_holdout_audit"]["proxy_passed"] is True
    assert report["conditional_overfit_holdout_audit"]["real_shadow_still_required"] is True
    assert report["conditional_overfit_holdout_audit"]["tail_holdout_proxy"]["return_delta_pct"] == 2.3921
    assert report["readiness_candidate_alignment"]["passed"] is True
    assert report["readiness_candidate_alignment"]["blockers"] == []
    assert report["candidate_switch_policy"]["status"] == (
        "candidate_switch_blocked_pending_readiness_or_parity"
    )
    assert report["candidate_switch_policy"]["default_route"] == "primary_return_candidate"
    assert report["candidate_switch_policy"]["defensive_route"] == "risk_adjusted_compression_candidate"
    assert report["candidate_switch_policy"]["defensive_candidate"]["recipe_id"] == (
        "selective_mode_loss_after_selection_light"
    )
    assert report["candidate_switch_policy"]["defensive_lineage_review"]["status"] == (
        "pending_operator_lineage_review"
    )
    assert (
        report["candidate_switch_policy"]["defensive_lineage_review"]["operator_review_template"][
            "reviewed_folds"
        ]
        == [11]
    )
    assert report["operator_lineage_review_template_report"].endswith(
        "market_state_rotation_v6_operator_lineage_review_template.json"
    )
    assert report["operator_lineage_review_skeleton_report"].endswith(
        "market_state_rotation_v6_operator_lineage_review_skeleton.json"
    )
    assert report["compare_summary"]["candidate_switch_policy"]["promotion_blockers"] == [
        "execution_parity_not_passed",
        "live_or_paper_execution_parity_available",
    ]
    assert report["readiness"]["ready_for_paper"] is True
    assert report["readiness"]["ready_for_tiny_canary"] is False
    assert report["blocks_live_promotion"] is True
    assert report["order_submission_allowed"] is False
    assert report["no_live_order_sent"] is True


def test_recent_meta_router_promotion_gate_validates_lineage_artifact_files(tmp_path) -> None:
    report_dir = tmp_path / "evidence" / "market_state_rotation_v6_meta_router_promotion_gate"
    report_dir.mkdir(parents=True)
    generated_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    promotion_path = report_dir / "market_state_rotation_v6_meta_router_promotion_gate.json"
    template_path = report_dir / "market_state_rotation_v6_operator_lineage_review_template.json"
    skeleton_path = report_dir / "market_state_rotation_v6_operator_lineage_review_skeleton.json"
    template_payload = {
        "source_promotion_gate_report": str(promotion_path),
        "source_promotion_gate_generated_at": generated_at.isoformat(),
        "operator_review_json_skeleton_report": str(skeleton_path),
        "no_live_order_sent": True,
    }
    skeleton_payload = {
        "source_template_report": str(template_path),
        "source_promotion_gate_report": str(promotion_path),
        "source_promotion_gate_generated_at": generated_at.isoformat(),
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    template_path.write_text(json.dumps(template_payload), encoding="utf-8")
    skeleton_path.write_text(json.dumps(skeleton_payload), encoding="utf-8")
    manifest = {
        "fingerprint_algorithm": "sha256_canonical_json",
        "template_report": str(template_path),
        "template_payload_fingerprint": watch._fingerprint_payload(template_payload),
        "skeleton_report": str(skeleton_path),
        "skeleton_payload_fingerprint": watch._fingerprint_payload(skeleton_payload),
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    promotion_path.write_text(
        json.dumps(
            {
                "generated_at": generated_at.isoformat(),
                "status": "meta_router_promotion_gate_complete",
                "no_live_order_sent": True,
                "report_path": str(promotion_path),
                "expected_operator_lineage_source_report": str(promotion_path),
                "promotion_decision": "paper_ready_pending_execution_parity",
                "operator_lineage_review_template_report": str(template_path),
                "operator_lineage_review_skeleton_report": str(skeleton_path),
                "operator_lineage_artifact_manifest": manifest,
                "candidate_switch_policy": {
                    "defensive_lineage_review": {
                        "required": True,
                        "status": "pending_operator_lineage_review",
                    },
                },
                "candidate": {},
                "readiness": {},
            }
        ),
        encoding="utf-8",
    )

    report = watch._recent_meta_router_promotion_gate(
        evidence_root=tmp_path / "evidence",
        current_at=generated_at + timedelta(minutes=5),
    )

    artifacts = report["operator_lineage_review_artifacts"]
    assert artifacts["status"] == "pass"
    assert artifacts["blockers"] == []
    assert artifacts["manifest"]["present"] is True
    assert artifacts["manifest"]["template_payload_fingerprint"] == watch._fingerprint_payload(
        template_payload
    )
    assert artifacts["manifest"]["skeleton_payload_fingerprint"] == watch._fingerprint_payload(
        skeleton_payload
    )
    assert artifacts["template"]["exists"] is True
    assert artifacts["skeleton"]["exists"] is True
    assert artifacts["skeleton"]["order_submission_allowed"] is False
    assert artifacts["no_live_order_sent"] is True


def test_recent_meta_router_promotion_gate_fails_tampered_lineage_artifact(tmp_path) -> None:
    report_dir = tmp_path / "evidence" / "market_state_rotation_v6_meta_router_promotion_gate"
    report_dir.mkdir(parents=True)
    generated_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    promotion_path = report_dir / "market_state_rotation_v6_meta_router_promotion_gate.json"
    template_path = report_dir / "market_state_rotation_v6_operator_lineage_review_template.json"
    skeleton_path = report_dir / "market_state_rotation_v6_operator_lineage_review_skeleton.json"
    template_payload = {
        "source_promotion_gate_report": str(promotion_path),
        "source_promotion_gate_generated_at": generated_at.isoformat(),
        "operator_review_json_skeleton_report": str(skeleton_path),
        "no_live_order_sent": True,
    }
    skeleton_payload = {
        "source_template_report": str(template_path),
        "source_promotion_gate_report": str(promotion_path),
        "source_promotion_gate_generated_at": generated_at.isoformat(),
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    template_path.write_text(json.dumps(template_payload), encoding="utf-8")
    skeleton_path.write_text(
        json.dumps({**skeleton_payload, "rationale": "tampered after manifest"}),
        encoding="utf-8",
    )
    promotion_path.write_text(
        json.dumps(
            {
                "generated_at": generated_at.isoformat(),
                "status": "meta_router_promotion_gate_complete",
                "no_live_order_sent": True,
                "report_path": str(promotion_path),
                "expected_operator_lineage_source_report": str(promotion_path),
                "operator_lineage_review_template_report": str(template_path),
                "operator_lineage_review_skeleton_report": str(skeleton_path),
                "operator_lineage_artifact_manifest": {
                    "fingerprint_algorithm": "sha256_canonical_json",
                    "template_report": str(template_path),
                    "template_payload_fingerprint": watch._fingerprint_payload(template_payload),
                    "skeleton_report": str(skeleton_path),
                    "skeleton_payload_fingerprint": watch._fingerprint_payload(skeleton_payload),
                    "order_submission_allowed": False,
                    "no_live_order_sent": True,
                },
                "candidate_switch_policy": {
                    "defensive_lineage_review": {
                        "required": True,
                        "status": "pending_operator_lineage_review",
                    },
                },
                "candidate": {},
                "readiness": {},
            }
        ),
        encoding="utf-8",
    )

    report = watch._recent_meta_router_promotion_gate(
        evidence_root=tmp_path / "evidence",
        current_at=generated_at + timedelta(minutes=5),
    )

    artifacts = report["operator_lineage_review_artifacts"]
    assert artifacts["status"] == "fail"
    assert "operator_lineage_skeleton_payload_fingerprint_mismatch" in artifacts["blockers"]


def test_recent_meta_router_promotion_gate_marks_stale_report(tmp_path) -> None:
    report_dir = tmp_path / "evidence" / "market_state_rotation_v6_meta_router_promotion_gate"
    report_dir.mkdir(parents=True)
    generated_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    (report_dir / "market_state_rotation_v6_meta_router_promotion_gate.json").write_text(
        json.dumps(
            {
                "generated_at": generated_at.isoformat(),
                "status": "meta_router_promotion_gate_complete",
                "no_live_order_sent": True,
                "promotion_decision": "tiny_canary_gate_passed_manual_approval_required",
                "candidate": {"recipe_id": "candidate"},
                "readiness": {"ready_for_tiny_canary": True},
            }
        ),
        encoding="utf-8",
    )

    report = watch._recent_meta_router_promotion_gate(
        evidence_root=tmp_path / "evidence",
        current_at=generated_at + timedelta(minutes=61),
        max_age_minutes=60,
    )

    assert report["status"] == "stale"
    assert report["stale"] is True
    assert report["blocks_live_promotion"] is True
    assert report["no_live_order_sent"] is True


def test_safe_next_action_refreshes_stale_meta_router_promotion_gate() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        meta_router_promotion_gate={
            "status": "stale",
            "stale": True,
            "source_report": "reports/promotion.json",
            "promotion_decision": "paper_ready_pending_execution_parity",
            "no_live_order_sent": True,
        },
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    action = plan["primary_action"]
    assert action["action_type"] == "refresh_meta_router_promotion_gate"
    assert action["can_run_now"] is True
    assert action["requires_operator_review"] is False
    assert "run_market_state_rotation_v6_meta_router_promotion_gate.py" in action["command"]
    assert action["promotion_gate_stale"] is True
    assert action["promotion_gate_source"] == "reports/promotion.json"
    assert action["order_submission_allowed"] is False
    assert action["no_live_order_sent"] is True


def test_safe_next_action_refreshes_failed_lineage_artifacts() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        meta_router_promotion_gate={
            "status": "meta_router_promotion_gate_complete",
            "stale": False,
            "promotion_decision": "paper_ready_pending_execution_parity",
            "operator_lineage_review_artifacts": {
                "status": "fail",
                "blockers": ["operator_lineage_skeleton_report_file_missing"],
            },
            "no_live_order_sent": True,
        },
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    action = plan["primary_action"]
    assert action["action_type"] == "refresh_meta_router_promotion_gate"
    assert action["reason"] == "operator_lineage_review_artifact_check_failed"
    assert action["operator_lineage_artifact_status"] == "fail"
    assert action["operator_lineage_artifact_blockers"] == [
        "operator_lineage_skeleton_report_file_missing"
    ]
    assert action["order_submission_allowed"] is False
    assert action["no_live_order_sent"] is True


def test_safe_next_action_does_not_refresh_current_meta_router_promotion_gate() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        meta_router_promotion_gate={
            "status": "meta_router_promotion_gate_complete",
            "generated_at": "2026-01-01T11:55:00+00:00",
            "stale": False,
            "promotion_decision": "paper_ready_pending_execution_parity",
            "no_live_order_sent": True,
        },
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    assert plan["primary_action"] is None
    assert plan["action_count"] == 0
    assert plan["status"] == "no_blocking_safe_action"


def test_safe_next_action_surfaces_defensive_lineage_review_template() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        meta_router_promotion_gate={
            "status": "meta_router_promotion_gate_complete",
            "generated_at": "2026-01-01T11:55:00+00:00",
            "stale": False,
            "promotion_decision": "paper_ready_pending_execution_parity",
            "expected_operator_lineage_source_report": "reports/promotion_gate.json",
            "operator_lineage_review_template_report": "reports/lineage_template.json",
            "operator_lineage_review_skeleton_report": "reports/lineage_skeleton.json",
            "operator_lineage_review_artifacts": {
                "status": "pass",
                "blockers": [],
                "manifest": {
                    "present": True,
                    "fingerprint_algorithm": "sha256_canonical_json",
                    "template_payload_fingerprint": "b" * 64,
                    "skeleton_payload_fingerprint": "c" * 64,
                    "no_live_order_sent": True,
                },
                "template": {"payload_fingerprint": "b" * 64},
                "skeleton": {"payload_fingerprint": "c" * 64},
                "no_live_order_sent": True,
            },
            "candidate_switch_policy": {
                "status": "candidate_switch_blocked_pending_readiness_or_parity",
                "promotion_blockers": [
                    "defensive_lineage_review_not_passed",
                    "execution_parity_not_passed",
                ],
                "defensive_lineage_review": {
                    "required": True,
                    "status": "pending_operator_lineage_review",
                    "operator_review": {
                        "status": "missing",
                        "blockers": ["operator_lineage_review_report_missing"],
                    },
                    "operator_review_template": {
                        "candidate_recipe_id": "selective_mode_loss_after_selection_light",
                        "reviewed_folds": [11],
                        "review_packet_summary": (
                            "lineage_watch_is_limited_to_intentional_size_overlay_folds"
                        ),
                        "review_packet_fingerprint": "a" * 64,
                        "required_operator_reviewed_at": True,
                    },
                },
            },
            "no_live_order_sent": True,
        },
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    action = plan["primary_action"]
    assert action["action_type"] == "review_defensive_candidate_lineage_template"
    assert action["can_run_now"] is True
    assert action["requires_operator_review"] is True
    assert action["command"] is None
    assert action["template_report"] == "reports/lineage_template.json"
    assert action["operator_lineage_review_skeleton_report"] == "reports/lineage_skeleton.json"
    assert action["operator_lineage_artifact_status"] == "pass"
    assert action["operator_lineage_artifact_blockers"] == []
    assert action["operator_lineage_artifact_manifest"] == {
        "present": True,
        "fingerprint_algorithm": "sha256_canonical_json",
        "template_payload_fingerprint": "b" * 64,
        "skeleton_payload_fingerprint": "c" * 64,
        "no_live_order_sent": True,
    }
    assert action["operator_lineage_template_payload_fingerprint"] == "b" * 64
    assert action["operator_lineage_skeleton_payload_fingerprint"] == "c" * 64
    assert action["source_promotion_gate_report"] == "reports/promotion_gate.json"
    assert action["source_promotion_gate_generated_at"] == "2026-01-01T11:55:00+00:00"
    assert action["candidate_recipe_id"] == "selective_mode_loss_after_selection_light"
    assert action["reviewed_folds"] == [11]
    assert action["review_packet_fingerprint"] == "a" * 64
    assert action["operator_fields_to_fill"] == {
        "status": "operator_lineage_review_accepted_or_rejected",
        "source_promotion_gate_report": "reports/promotion_gate.json",
        "reviewer": "operator_name_or_initials",
        "reviewed_at": "iso8601_timestamp_after_source_promotion_gate_generated_at",
        "rationale": "why_the_defensive_size_overlay_delta_is_accepted_or_rejected",
        "no_live_order_sent": True,
    }
    assert action["operator_lineage_review_acceptance_contract"] == {
        "source_promotion_gate_report_must_match": "reports/promotion_gate.json",
        "candidate_recipe_id_must_match": "selective_mode_loss_after_selection_light",
        "reviewed_folds_must_match": [11],
        "review_packet_summary_must_match": (
            "lineage_watch_is_limited_to_intentional_size_overlay_folds"
        ),
        "review_packet_fingerprint_must_match": "a" * 64,
        "reviewed_at_must_be_at_or_after_promotion_gate_generated_at": (
            "2026-01-01T11:55:00+00:00"
        ),
        "reviewer_must_be_non_empty": True,
        "rationale_must_be_non_empty": True,
        "no_live_order_sent_must_be_true": True,
        "accepted_status_values": [
            "accepted",
            "operator_lineage_review_accepted",
            "operator_review_accepted",
        ],
    }
    assert action["operator_review_json_skeleton"] == {
        "status": "operator_lineage_review_accepted_or_rejected",
        "candidate_recipe_id": "selective_mode_loss_after_selection_light",
        "reviewed_folds": [11],
        "review_packet_summary": (
            "lineage_watch_is_limited_to_intentional_size_overlay_folds"
        ),
        "review_packet_fingerprint": "a" * 64,
        "source_promotion_gate_report": "reports/promotion_gate.json",
        "source_promotion_gate_generated_at": "2026-01-01T11:55:00+00:00",
        "reviewer": "operator_name_or_initials",
        "reviewed_at": "iso8601_timestamp_after_source_promotion_gate_generated_at",
        "rationale": "why_the_defensive_size_overlay_delta_is_accepted_or_rejected",
        "acceptance_contract": action["operator_lineage_review_acceptance_contract"],
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    assert action["operator_lineage_review_validation_command_template"] == (
        ".venv/bin/python scripts/run_market_state_rotation_v6_meta_router_promotion_gate.py "
        "--operator-lineage-review-report <operator_lineage_review_report.json> "
        "--expected-operator-lineage-source-report reports/promotion_gate.json"
    )
    assert action["operator_lineage_review_validation_contract"] == {
        "expected_operator_lineage_source_report": "reports/promotion_gate.json",
        "expected_operator_review_status_path": (
            "candidate_switch_policy.defensive_lineage_review.operator_review.status"
        ),
        "expected_no_live_order_sent": True,
        "write_report_required_for_validation": False,
        "order_submission_allowed": False,
    }
    assert action["operator_lineage_review_source_report_required"] is True
    assert action["reviewed_at_required"] is True
    assert action["does_not_enable_route_until_execution_parity_passes"] is True
    assert action["order_submission_allowed"] is False
    assert action["no_live_order_sent"] is True


def test_safe_next_action_surfaces_conditional_overfit_operator_review_template() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        meta_router_promotion_gate={
            "status": "meta_router_promotion_gate_complete",
            "generated_at": "2026-01-01T11:55:00+00:00",
            "stale": False,
            "promotion_decision": "blocked_pending_overfit_holdout_review",
            "expected_operator_lineage_source_report": "reports/promotion_gate.json",
            "conditional_overfit_operator_review_template_report": "reports/overfit_template.json",
            "conditional_overfit_operator_review_skeleton_report": "reports/overfit_skeleton.json",
            "conditional_overfit_operator_review_artifacts": {
                "status": "pass",
                "blockers": [],
                "manifest": {
                    "present": True,
                    "fingerprint_algorithm": "sha256_canonical_json",
                    "template_payload_fingerprint": "d" * 64,
                    "skeleton_payload_fingerprint": "e" * 64,
                    "paper_only_scope": True,
                    "real_shadow_still_required_before_tiny_canary_or_live": True,
                    "no_live_order_sent": True,
                },
                "template": {"payload_fingerprint": "d" * 64},
                "skeleton": {"payload_fingerprint": "e" * 64},
                "no_live_order_sent": True,
            },
            "conditional_overfit_operator_review": {
                "required": True,
                "status": "pending_conditional_overfit_operator_review",
                "proxy_passed": True,
                "accepted_for_paper_only": False,
                "operator_review": {
                    "status": "missing",
                    "blockers": ["conditional_overfit_operator_review_report_missing"],
                },
                "operator_review_template": {
                    "candidate_recipe_id": "conditional_refill_formal",
                    "candidate_report": "reports/conditional.json",
                    "overfit_blockers": [
                        "conditional_winner_refill_overlay_requires_shadow_holdout_review"
                    ],
                    "proxy_audit_report": "reports/holdout_proxy.json",
                    "proxy_passed": True,
                    "review_packet_summary": (
                        "conditional_winner_refill_overlay_historical_proxy_requires_operator_overfit_review"
                    ),
                    "review_packet_fingerprint": "f" * 64,
                    "required_decision_values": [
                        "accepted",
                        "conditional_overfit_review_accepted",
                        "operator_overfit_review_accepted",
                        "operator_review_accepted",
                    ],
                },
            },
            "no_live_order_sent": True,
        },
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    action = plan["primary_action"]
    assert action["action_type"] == "review_conditional_overfit_holdout_proxy"
    assert action["target_gate"] == "conditional_overfit_operator_review"
    assert action["can_run_now"] is True
    assert action["requires_operator_review"] is True
    assert action["command"] is None
    assert action["template_report"] == "reports/overfit_template.json"
    assert action["conditional_overfit_operator_review_skeleton_report"] == "reports/overfit_skeleton.json"
    assert action["conditional_overfit_operator_review_artifact_status"] == "pass"
    assert action["conditional_overfit_operator_review_artifact_blockers"] == []
    assert action["conditional_overfit_operator_review_template_payload_fingerprint"] == "d" * 64
    assert action["conditional_overfit_operator_review_skeleton_payload_fingerprint"] == "e" * 64
    assert action["source_promotion_gate_report"] == "reports/promotion_gate.json"
    assert action["source_promotion_gate_generated_at"] == "2026-01-01T11:55:00+00:00"
    assert action["candidate_recipe_id"] == "conditional_refill_formal"
    assert action["candidate_report"] == "reports/conditional.json"
    assert action["proxy_audit_report"] == "reports/holdout_proxy.json"
    assert action["review_packet_fingerprint"] == "f" * 64
    assert action["operator_fields_to_fill"]["paper_only_scope"] is True
    assert (
        action["operator_fields_to_fill"]["real_shadow_still_required_before_tiny_canary_or_live"]
        is True
    )
    assert action["conditional_overfit_operator_review_acceptance_contract"] == {
        "source_promotion_gate_report_must_match": "reports/promotion_gate.json",
        "candidate_recipe_id_must_match": "conditional_refill_formal",
        "candidate_report_must_match": "reports/conditional.json",
        "overfit_blockers_must_match": [
            "conditional_winner_refill_overlay_requires_shadow_holdout_review"
        ],
        "proxy_audit_report_must_match": "reports/holdout_proxy.json",
        "review_packet_summary_must_match": (
            "conditional_winner_refill_overlay_historical_proxy_requires_operator_overfit_review"
        ),
        "review_packet_fingerprint_must_match": "f" * 64,
        "reviewed_at_must_be_at_or_after_promotion_gate_generated_at": (
            "2026-01-01T11:55:00+00:00"
        ),
        "reviewer_must_be_non_empty": True,
        "rationale_must_be_non_empty": True,
        "paper_only_scope_must_be_true": True,
        "real_shadow_still_required_before_tiny_canary_or_live_must_be_true": True,
        "no_live_order_sent_must_be_true": True,
        "accepted_status_values": [
            "accepted",
            "conditional_overfit_review_accepted",
            "operator_overfit_review_accepted",
            "operator_review_accepted",
        ],
    }
    assert action["operator_review_json_skeleton"]["paper_only_scope"] is True
    assert (
        action["operator_review_json_skeleton"][
            "real_shadow_still_required_before_tiny_canary_or_live"
        ]
        is True
    )
    assert action["conditional_overfit_operator_review_validation_command_template"] == (
        ".venv/bin/python scripts/run_market_state_rotation_v6_meta_router_promotion_gate.py "
        "--conditional-overfit-operator-review-report "
        "<conditional_overfit_operator_review_report.json> "
        "--expected-operator-lineage-source-report reports/promotion_gate.json"
    )
    assert action["conditional_overfit_operator_review_validation_contract"] == {
        "expected_operator_lineage_source_report": "reports/promotion_gate.json",
        "expected_operator_review_status_path": "conditional_overfit_operator_review.operator_review.status",
        "expected_no_live_order_sent": True,
        "write_report_required_for_validation": False,
        "paper_only_scope": True,
        "real_shadow_still_required_before_tiny_canary_or_live": True,
        "order_submission_allowed": False,
    }
    assert action["does_not_enable_tiny_canary_or_live_until_real_shadow_passes"] is True
    assert action["order_submission_allowed"] is False
    assert action["no_live_order_sent"] is True


def test_operator_work_queue_separates_automation_review_and_wait_items() -> None:
    queue = watch._operator_work_queue(
        {
            "actions": [
                {
                    "priority": 20,
                    "action_type": "monitor_fresh_signal",
                    "target_gate": "current_fresh_signal",
                    "can_run_now": True,
                    "requires_operator_review": False,
                    "command": (
                        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                        "--report-dir reports/validation/diagnostics/signal_monitor"
                    ),
                    "execute_after_utc": "2026-01-01T00:00:00+00:00",
                    "execute_after_kst": "2026-01-01T09:00:00+09:00",
                    "execution_window_status": "due_or_overdue",
                    "minutes_until_execution_window": 0.0,
                    "overdue_minutes": 5.0,
                    "action_due_now": True,
                    "effective_execution_window_status": "covered_this_iteration",
                    "effective_action_due_now": False,
                    "covered_by_current_iteration": True,
                    "covered_due_by_current_iteration": True,
                    "current_iteration_coverage": {
                        "covered": True,
                        "status": "covered_fresh_signal_still_waiting",
                        "recommended_next_recheck_after_kst": "2026-01-01T09:05:00+09:00",
                        "no_live_order_sent": True,
                    },
                    "no_live_order_sent": True,
                },
                {
                    "priority": 34,
                    "action_type": "review_conditional_overfit_holdout_proxy",
                    "target_gate": "conditional_overfit_operator_review",
                    "can_run_now": True,
                    "requires_operator_review": True,
                    "template_report": "reports/overfit_template.json",
                    "conditional_overfit_operator_review_skeleton_report": (
                        "reports/overfit_skeleton.json"
                    ),
                    "conditional_overfit_operator_review_validation_command_template": (
                        "validate-overfit"
                    ),
                    "paper_only_scope": True,
                    "real_shadow_still_required_before_tiny_canary_or_live": True,
                    "no_live_order_sent": True,
                },
                {
                    "priority": 50,
                    "action_type": "wait_for_next_microstructure_quote_window",
                    "target_gate": "real_microstructure_execution_evidence",
                    "can_run_now": False,
                    "can_start_now": True,
                    "waits_until_execution_window": True,
                    "requires_operator_review": False,
                    "command": "watch --sleep-until-next-quote-coverage-window",
                    "execute_after_kst": "2026-01-02T09:00:00+09:00",
                    "no_live_order_sent": True,
                },
                {
                    "priority": 60,
                    "action_type": "paper_bridge_wait_for_fresh_signal",
                    "target_gate": "real_paper_lifecycle_rows",
                    "can_run_now": False,
                    "requires_operator_review": True,
                    "no_live_order_sent": True,
                },
            ]
        }
    )

    assert queue["status"] == "automation_and_operator_review_available"
    assert queue["raw_status"] == "automation_and_operator_review_available"
    assert queue["status_scope"] == "raw_queue_includes_actions_already_covered_this_iteration"
    assert queue["effective_status"] == "operator_review_required"
    assert queue["effective_status_scope"] == "covered_actions_excluded_from_effective_queue"
    assert queue["covered_automation_status"] == "all_raw_automation_covered_this_iteration"
    assert queue["automation_now_count"] == 1
    assert queue["raw_automation_now_count"] == 1
    assert queue["effective_automation_now_count"] == 0
    assert queue["covered_automation_now_count"] == 1
    assert queue["operator_review_count"] == 2
    assert queue["operator_review_now_count"] == 1
    assert queue["operator_review_wait_count"] == 1
    assert queue["startable_wait_count"] == 1
    assert queue["scheduled_wait_count"] == 0
    assert queue["primary_automation_action"]["action_type"] == "monitor_fresh_signal"
    assert queue["primary_automation_action"]["command_report_dir"] == (
        "reports/validation/diagnostics/signal_monitor"
    )
    assert queue["primary_automation_action"]["execution_window_status"] == "due_or_overdue"
    assert queue["primary_automation_action"]["minutes_until_execution_window"] == 0.0
    assert queue["primary_automation_action"]["overdue_minutes"] == 5.0
    assert queue["primary_automation_action"]["action_due_now"] is True
    assert queue["primary_automation_action"]["effective_execution_window_status"] == (
        "covered_this_iteration"
    )
    assert queue["primary_automation_action"]["effective_action_due_now"] is False
    assert queue["primary_automation_action"]["covered_by_current_iteration"] is True
    assert queue["primary_automation_action"]["covered_due_by_current_iteration"] is True
    assert queue["primary_automation_action"]["raw_next_monitor_after_kst"] == (
        "2026-01-01T09:00:00+09:00"
    )
    assert queue["primary_automation_action"]["effective_next_monitor_after_kst"] == (
        "2026-01-01T09:05:00+09:00"
    )
    assert queue["primary_automation_action"]["covered_next_recheck_after_kst"] == (
        "2026-01-01T09:05:00+09:00"
    )
    assert (
        queue["primary_automation_action"][
            "next_monitor_retimestampted_after_current_iteration"
        ]
        is True
    )
    assert queue["primary_automation_action"]["current_iteration_coverage"]["status"] == (
        "covered_fresh_signal_still_waiting"
    )
    assert queue["primary_automation_action"]["effective_available_now"] is False
    assert queue["primary_effective_automation_action"] is None
    assert queue["primary_covered_automation_action"]["action_type"] == "monitor_fresh_signal"
    assert queue["effective_automation_now"] == []
    assert [item["action_type"] for item in queue["covered_automation_now"]] == [
        "monitor_fresh_signal"
    ]
    assert queue["primary_operator_review_action"]["action_type"] == (
        "review_conditional_overfit_holdout_proxy"
    )
    assert queue["primary_operator_review_action"]["skeleton_report"] == "reports/overfit_skeleton.json"
    assert queue["primary_operator_review_action"]["validation_command_template"] == "validate-overfit"
    assert queue["primary_operator_review_action"]["paper_only_scope"] is True
    assert (
        queue["primary_operator_review_action"][
            "real_shadow_still_required_before_tiny_canary_or_live"
        ]
        is True
    )
    assert queue["primary_operator_review_wait_action"]["action_type"] == (
        "paper_bridge_wait_for_fresh_signal"
    )
    assert [item["action_type"] for item in queue["operator_reviews"]] == [
        "review_conditional_overfit_holdout_proxy"
    ]
    assert [item["action_type"] for item in queue["operator_review_waits"]] == [
        "paper_bridge_wait_for_fresh_signal"
    ]
    assert [item["action_type"] for item in queue["operator_reviews_all"]] == [
        "review_conditional_overfit_holdout_proxy",
        "paper_bridge_wait_for_fresh_signal",
    ]
    assert queue["primary_startable_wait_action"]["action_type"] == (
        "wait_for_next_microstructure_quote_window"
    )
    assert queue["order_submission_allowed"] is False
    assert queue["no_live_order_sent"] is True


def test_operator_review_handoff_summary_marks_ready_blocked_and_waiting_reviews() -> None:
    queue = {
        "operator_reviews": [
            {
                "priority": 34,
                "action_type": "review_conditional_overfit_holdout_proxy",
                "target_gate": "conditional_overfit_operator_review",
                "can_run_now": True,
                "template_report": "reports/overfit_template.json",
                "skeleton_report": "reports/overfit_skeleton.json",
                "validation_command_template": (
                    "validate-overfit <conditional_overfit_operator_review_report.json>"
                ),
                "candidate_recipe_id": "conditional_refill_formal",
                "review_packet_fingerprint": "f" * 64,
                "paper_only_scope": True,
                "real_shadow_still_required_before_tiny_canary_or_live": True,
                "no_live_order_sent": True,
            },
            {
                "priority": 35,
                "action_type": "review_defensive_candidate_lineage_template",
                "target_gate": "defensive_lineage_review",
                "can_run_now": True,
                "template_report": "reports/lineage_template.json",
                "skeleton_report": "reports/lineage_skeleton.json",
                "validation_command_template": "validate-lineage <operator_lineage_review_report.json>",
                "candidate_recipe_id": "selective_mode_loss_after_selection_light",
                "review_packet_fingerprint": "a" * 64,
                "no_live_order_sent": True,
            },
            {
                "priority": 36,
                "action_type": "review_broken_packet",
                "target_gate": "conditional_overfit_operator_review",
                "can_run_now": True,
                "template_report": None,
                "skeleton_report": "reports/broken_skeleton.json",
                "validation_command_template": None,
                "no_live_order_sent": True,
            },
        ],
        "operator_review_waits": [
            {
                "priority": 60,
                "action_type": "paper_bridge_wait_for_fresh_signal",
                "target_gate": "real_paper_lifecycle_rows",
                "can_run_now": False,
                "execute_after_kst": "2026-01-01T21:15:00+09:00",
                "reason": "must_wait_for_fresh_signal_before_paper_bridge_apply",
                "no_live_order_sent": True,
            }
        ],
    }

    handoff = watch._operator_review_handoff_summary(
        operator_work_queue=queue,
        meta_router_promotion_gate={
            "input_conditional_overfit_operator_review_report": None,
            "input_operator_lineage_review_report": None,
            "conditional_overfit_operator_review_artifacts": {
                "status": "pass",
                "blockers": [],
            },
            "conditional_overfit_operator_review": {
                "operator_review": {
                    "status": "missing",
                    "blockers": ["conditional_overfit_operator_review_report_missing"],
                }
            },
            "operator_lineage_review_artifacts": {
                "status": "pass",
                "blockers": [],
            },
            "candidate_switch_policy": {
                "defensive_lineage_review": {
                    "operator_review": {
                        "status": "missing",
                        "blockers": ["operator_lineage_review_report_missing"],
                    }
                }
            },
        },
    )

    assert handoff["status"] == "operator_review_packet_blocked"
    assert handoff["ready_review_count"] == 2
    assert handoff["blocked_review_count"] == 1
    assert handoff["waiting_review_count"] == 1
    assert handoff["primary_ready_review"]["action_type"] == "review_conditional_overfit_holdout_proxy"
    assert handoff["primary_ready_review"]["artifact_status"] == "pass"
    assert handoff["primary_ready_review"]["operator_review_status"] == "missing"
    assert handoff["primary_ready_review"]["active_operator_review_file_status"] == "missing"
    assert handoff["primary_ready_review"]["operator_decision_packet"]["status"] == "draft_preparation_required"
    assert handoff["primary_operator_decision_packet"]["status"] == "draft_preparation_required"
    assert handoff["operator_decision_packet_count"] == 4
    assert handoff["operator_decision_required_count"] == 0
    assert handoff["primary_ready_review"]["operator_decision_required"] is True
    assert handoff["primary_ready_review"]["auto_accept_allowed"] is False
    assert handoff["primary_ready_review"]["suggested_operator_review_report"] == (
        "reports/operations/market_state_rotation_v6_operator_reviews/"
        "conditional_overfit_conditional_refill_formal_ffffffffffff.json"
    )
    assert handoff["primary_ready_review"]["operator_review_file_plan"] == {
        "status": "suggested_review_report_ready",
        "skeleton_source_report": "reports/overfit_skeleton.json",
        "suggested_review_report": (
            "reports/operations/market_state_rotation_v6_operator_reviews/"
            "conditional_overfit_conditional_refill_formal_ffffffffffff.json"
        ),
        "suggested_review_report_exists": False,
        "active_operator_review_report": None,
        "active_operator_review_file_status": "missing",
        "active_operator_review_file_next_action": "prepare_or_attach_operator_review_report",
        "active_operator_review_file_safety_blockers": [],
        "operator_required_fields_remaining": [],
        "draft_prepare_command": (
            ".venv/bin/python scripts/prepare_market_state_rotation_v6_operator_review_draft.py "
            "--skeleton-report reports/overfit_skeleton.json "
            "--output-report reports/operations/market_state_rotation_v6_operator_reviews/"
            "conditional_overfit_conditional_refill_formal_ffffffffffff.json "
            "--min-rationale-chars 30 --min-evidence-anchors 1 --write-summary"
        ),
        "draft_prepare_required": True,
        "validation_command": (
            "validate-overfit reports/operations/market_state_rotation_v6_operator_reviews/"
            "conditional_overfit_conditional_refill_formal_ffffffffffff.json"
        ),
        "next_action": "fill_suggested_review_report_from_skeleton_then_run_validation_command",
        "auto_write_review_report": False,
        "operator_must_choose_accept_or_reject": True,
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    assert handoff["primary_blocked_review"]["action_type"] == "review_broken_packet"
    assert handoff["primary_blocked_review"]["missing_packet_fields"] == [
        "template_report",
        "validation_command_template",
    ]
    assert handoff["primary_waiting_review"]["action_type"] == "paper_bridge_wait_for_fresh_signal"
    assert handoff["primary_waiting_review"]["status"] == "waiting_for_signal_or_time_gate"
    assert handoff["primary_waiting_review"]["suggested_operator_review_report"] is None
    lineage = next(item for item in handoff["reviews"] if item["review_kind"] == "defensive_lineage")
    assert lineage["suggested_operator_review_report"] == (
        "reports/operations/market_state_rotation_v6_operator_reviews/"
        "defensive_lineage_selective_mode_loss_after_selection_light_aaaaaaaaaaaa.json"
    )
    assert lineage["validation_command_with_suggested_report"] == (
        "validate-lineage reports/operations/market_state_rotation_v6_operator_reviews/"
        "defensive_lineage_selective_mode_loss_after_selection_light_aaaaaaaaaaaa.json"
    )
    assert handoff["order_submission_allowed"] is False
    assert handoff["no_live_order_sent"] is True


def test_operator_review_handoff_summary_marks_existing_draft_file_decision_required(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        watch,
        "_resolve",
        lambda value: Path(value) if Path(value).is_absolute() else tmp_path / str(value),
    )
    suggested = (
        "reports/operations/market_state_rotation_v6_operator_reviews/"
        "conditional_overfit_conditional_refill_formal_ffffffffffff.json"
    )
    draft_path = tmp_path / suggested
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(
        json.dumps(
            {
                "status": "conditional_overfit_review_accepted_or_rejected",
                "order_submission_allowed": False,
                "no_live_order_sent": True,
                "draft_metadata": {
                    "status": "operator_review_draft_prepared",
                    "operator_must_choose_accept_or_reject": True,
                    "auto_accept_allowed": False,
                    "min_rationale_chars": 30,
                    "min_evidence_anchors": 1,
                },
            }
        ),
        encoding="utf-8",
    )

    handoff = watch._operator_review_handoff_summary(
        operator_work_queue={
            "operator_reviews": [
                {
                    "priority": 34,
                    "action_type": "review_conditional_overfit_holdout_proxy",
                    "target_gate": "conditional_overfit_operator_review",
                    "can_run_now": True,
                    "template_report": "reports/overfit_template.json",
                    "skeleton_report": "reports/overfit_skeleton.json",
                    "validation_command_template": (
                        "validate-overfit <conditional_overfit_operator_review_report.json>"
                    ),
                    "candidate_recipe_id": "conditional_refill_formal",
                    "review_packet_fingerprint": "f" * 64,
                    "paper_only_scope": True,
                    "real_shadow_still_required_before_tiny_canary_or_live": True,
                    "no_live_order_sent": True,
                }
            ],
            "operator_review_waits": [],
        },
        meta_router_promotion_gate={
            "input_conditional_overfit_operator_review_report": None,
            "conditional_overfit_operator_review_artifacts": {
                "status": "pass",
                "blockers": [],
            },
            "conditional_overfit_operator_review": {
                "operator_review_template": {
                    "required_decision_values": [
                        "accepted",
                        "conditional_overfit_review_accepted",
                    ],
                },
                "operator_review": {
                    "status": "missing",
                    "blockers": ["conditional_overfit_operator_review_report_missing"],
                }
            },
        },
    )

    row = handoff["primary_ready_review"]
    assert row["suggested_operator_review_report_exists"] is True
    assert row["active_operator_review_report"] == suggested
    assert row["active_operator_review_file_status"] == "draft_exists_operator_decision_required"
    assert row["active_operator_review_file_summary"]["draft_status"] == "operator_review_draft_prepared"
    assert row["active_operator_review_file_summary"]["draft_min_rationale_chars"] == 30
    assert row["active_operator_review_file_summary"]["draft_min_evidence_anchors"] == 1
    assert row["active_operator_review_file_summary"]["draft_metadata"]["min_rationale_chars"] == 30
    assert row["active_operator_review_file_summary"]["draft_metadata"]["min_evidence_anchors"] == 1
    assert row["active_operator_review_file_summary"]["operator_required_fields_remaining"] == [
        "status",
        "reviewer",
        "reviewed_at",
        "rationale",
    ]
    assert row["operator_required_fields_remaining"] == [
        "status",
        "reviewer",
        "reviewed_at",
        "rationale",
    ]
    assert row["operator_review_file_plan"]["status"] == "active_review_draft_waiting_for_operator_decision"
    assert row["operator_review_file_plan"]["draft_prepare_required"] is False
    assert row["operator_review_file_plan"]["next_action"] == (
        "operator_fill_reviewer_reviewed_at_rationale_and_accept_or_reject_then_run_validation_command"
    )
    assert row["operator_decision_packet"]["status"] == "operator_decision_required"
    assert row["operator_decision_packet"]["accepted_status_values"] == [
        "accepted",
        "conditional_overfit_review_accepted",
    ]
    assert row["operator_decision_packet"]["reject_or_keep_blocked_status_note"] == (
        "any_non_accepted_status_keeps_this_candidate_or_route_blocked_by_validation"
    )
    assert row["operator_decision_packet"]["validation_command"] == (
        "validate-overfit reports/operations/market_state_rotation_v6_operator_reviews/"
        "conditional_overfit_conditional_refill_formal_ffffffffffff.json"
    )
    assert row["operator_decision_packet"]["decision_dry_run_command_template"] == (
        ".venv/bin/python scripts/complete_market_state_rotation_v6_operator_review_decision.py "
        "--review-report reports/operations/market_state_rotation_v6_operator_reviews/"
        "conditional_overfit_conditional_refill_formal_ffffffffffff.json "
        "--in-place --decision <accept_or_reject> --reviewer <operator_name_or_initials> "
        "--rationale <operator_rationale> --reviewed-at now "
        "--min-rationale-chars 30 --min-evidence-anchors 1 "
        "--backup-dir reports/operations/market_state_rotation_v6_operator_reviews/backups "
        "--dry-run"
    )
    assert row["operator_decision_packet"]["decision_dry_run_command_requires_explicit_accept_or_reject"] is True
    assert row["operator_decision_packet"]["decision_fill_command_template"] == (
        ".venv/bin/python scripts/complete_market_state_rotation_v6_operator_review_decision.py "
        "--review-report reports/operations/market_state_rotation_v6_operator_reviews/"
        "conditional_overfit_conditional_refill_formal_ffffffffffff.json "
        "--in-place --decision <accept_or_reject> --reviewer <operator_name_or_initials> "
        "--rationale <operator_rationale> --reviewed-at now "
        "--min-rationale-chars 30 --min-evidence-anchors 1 "
        "--backup-dir reports/operations/market_state_rotation_v6_operator_reviews/backups "
        "--write-summary"
    )
    assert row["operator_decision_packet"]["decision_fill_command_requires_explicit_accept_or_reject"] is True
    assert row["operator_decision_packet"]["decision_command_safety"]["status"] == "PASS"
    assert row["operator_decision_packet"]["decision_command_safety"]["blockers"] == []
    assert row["operator_decision_packet"]["decision_command_safety"]["missing_required_explicit_placeholders"] == []
    assert row["operator_decision_packet"]["decision_command_safety"]["dry_run_missing_required_explicit_placeholders"] == []
    assert row["operator_decision_packet"]["decision_command_safety"]["dry_run_command_checked"] is True
    assert row["operator_decision_packet"]["decision_command_safety"]["reviewed_at_required"] is True
    assert row["operator_decision_packet"]["decision_command_safety"]["fill_reviewed_at_present"] is True
    assert row["operator_decision_packet"]["decision_command_safety"]["dry_run_reviewed_at_present"] is True
    assert (
        row["operator_decision_packet"]["decision_command_safety"][
            "reviewed_at_source_order_enforced_by_completion_tool"
        ]
        is True
    )
    assert (
        row["operator_decision_packet"]["decision_command_safety"][
            "reviewed_at_future_guard_enforced_by_completion_tool"
        ]
        is True
    )
    assert (
        row["operator_decision_packet"]["decision_command_safety"][
            "rationale_decision_alignment_enforced_by_completion_tool"
        ]
        is True
    )
    assert (
        row["operator_decision_packet"]["decision_command_safety"][
            "review_status_placeholder_required_by_completion_tool"
        ]
        is True
    )
    assert (
        row["operator_decision_packet"]["decision_command_safety"][
            "draft_metadata_required_by_completion_tool"
        ]
        is True
    )
    assert (
        row["operator_decision_packet"]["decision_command_safety"][
            "draft_metadata_contract_enforced_by_completion_tool"
        ]
        is True
    )
    assert (
        row["operator_decision_packet"]["decision_command_safety"][
            "source_skeleton_verified_by_completion_tool"
        ]
        is True
    )
    assert (
        row["operator_decision_packet"]["decision_command_safety"][
            "source_skeleton_fingerprint_verified_when_required_by_completion_tool"
        ]
        is True
    )
    assert row["operator_decision_packet"]["decision_command_safety"]["min_rationale_chars_required"] == 30
    assert row["operator_decision_packet"]["decision_command_safety"]["min_evidence_anchors_required"] == 1
    assert row["operator_decision_packet"]["decision_command_safety"]["fill_min_rationale_chars_present"] is True
    assert row["operator_decision_packet"]["decision_command_safety"]["dry_run_min_rationale_chars_present"] is True
    assert row["operator_decision_packet"]["decision_command_safety"]["fill_min_evidence_anchors_present"] is True
    assert row["operator_decision_packet"]["decision_command_safety"]["dry_run_min_evidence_anchors_present"] is True
    assert row["operator_decision_packet"]["decision_command_safety"]["warnings"] == [
        "decision_fill_command_intentionally_requires_operator_placeholder_replacement"
    ]
    assert row["operator_decision_packet"]["decision_command_safety"]["order_submission_allowed"] is False
    assert row["operator_decision_packet"]["decision_command_safety"]["no_live_order_sent"] is True
    assert handoff["primary_operator_decision_packet"]["status"] == "operator_decision_required"
    assert handoff["operator_decision_required_count"] == 1
    assert row["operator_review_file_plan"]["operator_required_fields_remaining"] == [
        "status",
        "reviewer",
        "reviewed_at",
        "rationale",
    ]
    assert row["operator_review_file_plan"]["active_operator_review_file_safety_blockers"] == []
    assert row["no_live_order_sent"] is True


def test_unresolved_register_merges_operator_review_draft_runtime_state() -> None:
    problems = watch._unresolved_problem_register(
        latest={
            "signal_wait_plan": {"fresh_signal": True},
            "paper_bridge_apply_gate": {
                "status": "blocked_until_apply_gate_available",
                "can_request_paper_apply_now": False,
            },
            "execution_parity_collection_plan": {"missing_samples": 0},
            "execution_parity_journal": {
                "conversion": {"journal_row_count": 20, "missing_to_min_sample_count": 0}
            },
        },
        paper_only_rehearsal={"system_ready": True},
        operator_handoff={},
        execution_parity_eta={"missing_samples": 0},
        microstructure_watch={"coverage_plan": {}},
        meta_router_promotion_gate={
            "conditional_overfit_operator_review": {
                "required": True,
                "proxy_passed": True,
                "accepted_for_paper_only": False,
                "operator_review": {
                    "status": "missing",
                    "blockers": ["conditional_overfit_operator_review_report_missing"],
                },
                "operator_review_template": {
                    "candidate_recipe_id": "conditional_refill_formal",
                    "candidate_report": "reports/candidate.json",
                    "proxy_audit_report": "reports/proxy.json",
                    "review_packet_fingerprint": "f" * 64,
                },
            },
            "conditional_overfit_operator_review_template_report": "reports/overfit_template.json",
            "conditional_overfit_operator_review_skeleton_report": "reports/overfit_skeleton.json",
            "candidate_switch_policy": {
                "promotion_blockers": ["defensive_lineage_review_not_passed"],
                "defensive_lineage_review": {
                    "operator_review": {
                        "status": "missing",
                        "blockers": ["operator_lineage_review_report_missing"],
                    },
                    "operator_review_template": {
                        "candidate_recipe_id": "selective_mode_loss_after_selection_light",
                    }
                },
            },
            "operator_lineage_review_template_report": "reports/lineage_template.json",
            "operator_lineage_review_skeleton_report": "reports/lineage_skeleton.json",
        },
        safe_next_action_plan={
            "primary_action": {"action_type": "monitor_fresh_signal"},
            "coordination_plan": {"status": "parallel_signal_and_microstructure_schedule_ready"},
        },
        operator_review_handoff_summary={
            "reviews": [
                {
                    "target_gate": "conditional_overfit_operator_review",
                    "status": "ready_for_operator_review",
                    "review_kind": "conditional_overfit",
                    "active_operator_review_report": "reports/overfit_draft.json",
                    "active_operator_review_file_status": "draft_exists_operator_decision_required",
                    "operator_required_fields_remaining": [
                        "status",
                        "reviewer",
                        "reviewed_at",
                        "rationale",
                    ],
                    "operator_decision_packet": {
                        "status": "operator_decision_required",
                        "decision_dry_run_command_template": "complete-overfit --dry-run",
                        "decision_command_safety": {"status": "PASS"},
                    },
                    "no_live_order_sent": True,
                },
                {
                    "target_gate": "defensive_lineage_review",
                    "status": "ready_for_operator_review",
                    "review_kind": "defensive_lineage",
                    "active_operator_review_report": "reports/lineage_draft.json",
                    "active_operator_review_file_summary": {
                        "status": "draft_exists_operator_decision_required",
                        "draft_status": "operator_review_draft_prepared",
                        "operator_required_fields_remaining": ["status", "rationale"],
                    },
                    "operator_decision_packet": {
                        "status": "operator_decision_required",
                        "decision_dry_run_command_template": "complete-lineage --dry-run",
                        "decision_command_safety": {"status": "PASS"},
                    },
                    "no_live_order_sent": True,
                },
            ],
            "no_live_order_sent": True,
        },
    )

    conditional = next(item for item in problems if item["id"] == "conditional_overfit_operator_review")
    assert conditional["operator_review_status"] == "missing"
    assert conditional["operator_review_blockers"] == [
        "conditional_overfit_operator_review_report_missing"
    ]
    assert conditional["active_operator_review_report"] == "reports/overfit_draft.json"
    assert conditional["active_operator_review_file_status"] == "draft_exists_operator_decision_required"
    assert conditional["operator_decision_packet_status"] == "operator_decision_required"
    assert conditional["operator_decision_dry_run_ready"] is True
    assert conditional["operator_required_fields_remaining"] == [
        "status",
        "reviewer",
        "reviewed_at",
        "rationale",
    ]
    assert conditional["blocker_interpretation"] == (
        "accepted_review_missing_but_operator_draft_ready_for_manual_decision"
    )
    assert conditional["operator_review_runtime_state"]["next_manual_action"] == (
        "choose_accept_or_reject_replace_placeholders_then_run_dry_run"
    )
    assert conditional["no_live_order_sent"] is True

    lineage = next(item for item in problems if item["id"] == "defensive_lineage_operator_review")
    assert lineage["operator_review_status"] == "missing"
    assert lineage["operator_review_blockers"] == ["operator_lineage_review_report_missing"]
    assert lineage["active_operator_review_report"] == "reports/lineage_draft.json"
    assert lineage["active_operator_review_file_status"] == "draft_exists_operator_decision_required"
    assert lineage["operator_decision_packet_status"] == "operator_decision_required"
    assert lineage["operator_decision_dry_run_ready"] is True
    assert lineage["operator_required_fields_remaining"] == ["status", "rationale"]
    assert lineage["blocker_interpretation"] == (
        "accepted_review_missing_but_operator_draft_ready_for_manual_decision"
    )
    assert lineage["no_live_order_sent"] is True


def test_launch_blocker_priority_summary_splits_waiting_and_ready_review_work() -> None:
    summary = watch._launch_blocker_priority_summary(
        unresolved_problem_register=[
            {
                "id": "current_fresh_signal",
                "status": "open_waiting_for_realtime_signal",
                "severity": "launch_blocker",
                "non_substitutable": True,
                "next_action": "monitor_without_forcing_entry",
                "no_live_order_sent": True,
            },
            {
                "id": "execution_parity_samples",
                "status": "open_collect_real_paper_lifecycle_rows",
                "severity": "live_readiness_blocker",
                "non_substitutable": True,
                "next_action": "collect_reviewed_paper_apply_rows_until_execution_parity_passes",
                "no_live_order_sent": True,
            },
            {
                "id": "conditional_overfit_operator_review",
                "status": "open_operator_review_required_for_paper_only_candidate_activation",
                "severity": "paper_candidate_blocker",
                "non_substitutable": False,
                "next_action": "complete_or_reject_conditional_overfit_proxy_review_for_paper_only_scope",
                "no_live_order_sent": True,
            },
        ],
        operator_review_handoff_summary={
            "reviews": [
                {
                    "action_type": "review_conditional_overfit_holdout_proxy",
                    "target_gate": "conditional_overfit_operator_review",
                    "status": "ready_for_operator_review",
                    "no_live_order_sent": True,
                }
            ],
            "no_live_order_sent": True,
        },
        execution_parity_status_summary={
            "missing_samples": 20,
            "estimated_completion_kst": "2026-07-26T12:00:00+09:00",
            "no_live_order_sent": True,
        },
    )

    assert summary["status"] == "waiting_for_realtime_evidence_with_operator_reviews_ready"
    assert summary["open_problem_count"] == 3
    assert summary["non_substitutable_problem_count"] == 2
    assert summary["non_substitutable_wait_blocker_count"] == 2
    assert summary["non_substitutable_blocker_count"] == 2
    assert summary["operator_review_problem_count"] == 1
    assert summary["operator_review_ready_count"] == 1
    assert summary["execution_parity_missing_samples"] == 20
    assert summary["primary_non_substitutable_problem"]["id"] == "current_fresh_signal"
    assert summary["primary_waiting_blocker"]["id"] == "current_fresh_signal"
    assert summary["primary_operator_review"]["action_type"] == "review_conditional_overfit_holdout_proxy"
    assert [item["id"] for item in summary["priority_items"][:2]] == [
        "current_fresh_signal",
        "execution_parity_samples",
    ]
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_remaining_work_closure_summary_keeps_waits_and_operator_decisions_open() -> None:
    summary = watch._remaining_work_closure_summary(
        unresolved_problem_register=[
            {
                "id": "current_fresh_signal",
                "status": "open_waiting_for_realtime_signal",
                "severity": "launch_blocker",
                "non_substitutable": True,
                "next_action": "monitor_without_forcing_entry",
                "no_live_order_sent": True,
            },
            {
                "id": "execution_parity_samples",
                "status": "open_collect_real_paper_lifecycle_rows",
                "severity": "live_readiness_blocker",
                "non_substitutable": True,
                "next_action": "collect_reviewed_paper_apply_rows_until_execution_parity_passes",
                "no_live_order_sent": True,
            },
            {
                "id": "microstructure_calendar_day_coverage",
                "status": "open_waiting_for_future_calendar_days",
                "severity": "evidence_depth_blocker",
                "non_substitutable": True,
                "next_action": "continue_daily_quote_window_collection",
                "no_live_order_sent": True,
            },
            {
                "id": "conditional_overfit_operator_review",
                "status": "open_operator_review_required_for_paper_only_candidate_activation",
                "severity": "paper_candidate_blocker",
                "non_substitutable": False,
                "next_action": "complete_or_reject_conditional_overfit_proxy_review_for_paper_only_scope",
                "no_live_order_sent": True,
            },
        ],
        operator_work_queue={
            "automation_now": [
                {
                    "action_type": "monitor_fresh_signal",
                    "target_gate": "current_fresh_signal",
                    "no_live_order_sent": True,
                }
            ],
            "startable_waits": [],
            "scheduled_waits": [],
            "primary_automation_action": {
                "action_type": "monitor_fresh_signal",
                "target_gate": "current_fresh_signal",
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
        operator_review_handoff_summary={
            "reviews": [
                {
                    "action_type": "review_conditional_overfit_holdout_proxy",
                    "target_gate": "conditional_overfit_operator_review",
                    "status": "ready_for_operator_review",
                    "active_operator_review_file_status": "draft_exists_operator_decision_required",
                    "operator_decision_packet": {
                        "status": "operator_decision_required",
                        "decision_command_safety": {"status": "PASS"},
                    },
                    "no_live_order_sent": True,
                }
            ],
            "no_live_order_sent": True,
        },
        launch_blocker_priority_summary={
            "status": "waiting_for_realtime_evidence_with_operator_reviews_ready",
        },
        runtime_progress={"remaining_hours": 19.5},
        microstructure_watch={
            "coverage_plan": {
                "remaining_calendar_days": 25,
                "earliest_calendar_completion_kst": "2026-07-03T09:00:00+09:00",
                "next_quote_coverage_kst_at": "2026-06-09T09:00:00+09:00",
            }
        },
        execution_parity_status_summary={
            "missing_samples": 20,
            "estimated_completion_kst": "2026-07-26T16:00:00+09:00",
            "no_live_order_sent": True,
        },
    )

    assert summary["status"] == "automation_continues_operator_and_realtime_gates_remaining"
    assert summary["auto_complete_without_future_market_or_operator"] is False
    assert summary["safe_automation_now_count"] == 1
    assert summary["safe_effective_automation_now_count"] == 1
    assert summary["safe_covered_automation_now_count"] == 0
    assert summary["safe_useful_automation_now_count"] == 1
    assert summary["safe_noop_or_deferred_automation_now_count"] == 0
    assert summary["safe_raw_useful_automation_now_count"] == 1
    assert summary["effective_queue_available"] is False
    assert summary["automation_now_usefulness_scope"] == "raw_queue_no_effective_queue_available"
    assert summary["automation_now_usefulness"][0]["action_type"] == "monitor_fresh_signal"
    assert summary["automation_now_usefulness"][0]["useful_now"] is True
    assert summary["primary_useful_automation_action"]["action_type"] == "monitor_fresh_signal"
    assert summary["primary_raw_useful_automation_action"]["action_type"] == "monitor_fresh_signal"
    assert summary["primary_noop_or_deferred_automation_action"] is None
    assert summary["operator_decision_required_count"] == 1
    assert summary["operator_review_draft_prepared_count"] == 1
    assert summary["operator_decision_command_safety_pass_count"] == 1
    assert summary["non_substitutable_wait_count"] == 4
    assert summary["wait_only_problem_ids"] == [
        "current_fresh_signal",
        "execution_parity_samples",
        "microstructure_calendar_day_coverage",
        "shadow_runtime_24h_observed",
    ]
    assert summary["dependency_blocked_problem_count"] == 0
    assert summary["dependency_blocked_problem_ids"] == []
    assert summary["operator_review_problem_ids"] == ["conditional_overfit_operator_review"]
    assert summary["remaining_calendar_days"] == 25
    assert summary["execution_parity_missing_samples"] == 20
    assert summary["runtime_remaining_hours"] == 19.5
    lanes = summary["dependency_lanes"]
    assert lanes["status"] == "operator_and_realtime_dependencies_open"
    assert lanes["critical_path"] == [
        "current_fresh_signal",
        "operator_review_decisions",
        "first_real_paper_lifecycle_row",
        "execution_parity_samples",
    ]
    assert lanes["parallel_calendar_path"] == [
        "microstructure_calendar_day_coverage",
        "shadow_runtime_24h_observed",
    ]
    assert lanes["operator_input_lane"]["status"] == "operator_inputs_ready_for_manual_decision"
    assert lanes["operator_input_lane"]["decision_required_count"] == 1
    assert lanes["operator_input_lane"]["draft_prepared_count"] == 1
    assert lanes["operator_input_lane"]["command_safety_pass_count"] == 1
    assert lanes["operator_input_lane"]["manual_only"] is True
    assert lanes["realtime_signal_lane"]["status"] == "waiting_for_realtime_fresh_signal"
    assert lanes["realtime_signal_lane"]["monitor_useful_now"] is True
    assert lanes["realtime_signal_lane"]["non_substitutable"] is True
    assert lanes["first_paper_row_lane"]["status"] == "blocked_until_fresh_signal_and_operator_review"
    assert lanes["first_paper_row_lane"]["auto_apply_allowed"] is False
    assert lanes["execution_parity_lane"]["status"] == "waiting_for_real_reviewed_paper_lifecycle_rows"
    assert lanes["execution_parity_lane"]["missing_samples"] == 20
    assert lanes["execution_parity_lane"]["eta_completion_kst"] == "2026-07-26T16:00:00+09:00"
    assert lanes["calendar_coverage_lane"]["status"] == "waiting_for_future_quote_calendar_days"
    assert lanes["calendar_coverage_lane"]["remaining_calendar_days"] == 25
    assert lanes["calendar_coverage_lane"]["backfill_allowed_for_launch_gate"] is False
    assert lanes["runtime_observation_lane"]["status"] == "collecting_shadow_runtime"
    assert lanes["runtime_observation_lane"]["remaining_hours"] == 19.5
    assert lanes["auto_decision_allowed"] is False
    assert lanes["order_submission_allowed"] is False
    assert lanes["no_live_order_sent"] is True
    actionability = summary["actionability_partition"]
    assert actionability["status"] == "parallel_auto_and_manual_actions_available_waits_remain"
    assert actionability["dependency_aware_status"] == (
        "parallel_auto_and_manual_actions_available_waits_and_dependencies_remain"
    )
    assert actionability["waits_open"] is True
    assert actionability["dependency_blockers_open"] is True
    assert actionability["run_now_without_operator_count"] == 1
    assert actionability["manual_now_count"] == 1
    assert actionability["manual_repair_now_count"] == 0
    assert actionability["signal_wait_count"] == 2
    assert actionability["time_wait_count"] == 2
    assert actionability["dependency_blocked_count"] == 1
    assert actionability["dependency_unlock_plan_status"] == "manual_and_realtime_unlocks_remaining"
    assert actionability["primary_dependency_unlock_gate"] == "operator_review_decisions"
    assert actionability["primary_launch_wait_gate"] == "current_fresh_signal"
    assert actionability["primary_human_action_gate"] == "conditional_overfit_operator_review"
    assert actionability["no_safe_auto_command_now"] is False
    tracks = actionability["tracks"]
    assert tracks == summary["actionability_tracks"]
    assert tracks["status"] == "parallel_safe_auto_manual_and_realtime_wait"
    assert tracks["primary_launch_wait_gate"] == "current_fresh_signal"
    assert tracks["primary_human_action_gate"] == "conditional_overfit_operator_review"
    assert tracks["safe_automatable_now"]["count"] == 1
    assert tracks["safe_automatable_now"]["no_safe_auto_command_now"] is False
    assert tracks["manual_operator_required_now"]["count"] == 1
    assert tracks["realtime_wait_required"]["primary_gate"] == "current_fresh_signal"
    assert tracks["dependency_blocked"]["primary_gate"] == "first_real_paper_lifecycle_row"
    assert tracks["blocked_by_validation_redesign"]["count"] == 0
    assert tracks["interpretation"] == (
        "manual_reviews_can_progress_in_parallel_but_launch_primary_wait_is_realtime"
    )
    assert actionability["run_now_without_operator"][0]["action_type"] == "monitor_fresh_signal"
    assert actionability["run_now_without_operator"][0]["safe_to_auto_run_without_operator"] is True
    assert actionability["manual_now"][0]["action_type"] == "review_conditional_overfit_holdout_proxy"
    assert actionability["manual_now"][0]["safe_default_if_uncertain"] == "reject_or_hold_blocked"
    assert actionability["manual_now"][0]["auto_decision_allowed"] is False
    assert [item["problem_id"] for item in actionability["signal_waits"]] == [
        "current_fresh_signal",
        "execution_parity_samples",
    ]
    assert [item["problem_id"] for item in actionability["time_waits"]] == [
        "microstructure_calendar_day_coverage",
        "shadow_runtime_24h_observed",
    ]
    assert actionability["dependency_blocked"][0]["problem_id"] == "first_real_paper_lifecycle_row"
    assert actionability["recommended_parallel_next_moves"] == [
        "run_safe_monitoring_actions_without_live_orders",
        "complete_operator_review_batch_manually",
        "wait_for_realtime_fresh_signal_before_paper_apply",
        "continue_future_quote_calendar_collection",
        "continue_continuous_no_live_shadow_watch",
    ]
    assert actionability["auto_decision_allowed"] is False
    assert actionability["order_submission_allowed"] is False
    assert actionability["no_live_order_sent"] is True
    unlock_plan = summary["dependency_unlock_plan"]
    assert unlock_plan["status"] == "manual_and_realtime_unlocks_remaining"
    assert unlock_plan["step_count"] == 4
    assert unlock_plan["manual_unlock_step_count"] == 1
    assert unlock_plan["realtime_unlock_step_count"] == 2
    assert unlock_plan["primary_unlock_step"]["gate"] == "operator_review_decisions"
    assert unlock_plan["primary_realtime_unlock_step"]["gate"] == "current_fresh_signal"
    assert unlock_plan["first_paper_row_missing_dependencies"] == [
        "current_fresh_signal",
        "operator_review_decisions",
    ]
    assert [step["gate"] for step in unlock_plan["steps"]] == [
        "operator_review_decisions",
        "current_fresh_signal",
        "first_real_paper_lifecycle_row",
        "execution_parity_samples",
    ]
    assert unlock_plan["first_paper_row_requires_all_dependencies"] is True
    assert unlock_plan["steps"][0]["unlock_mode"] == "partial_dependency_clear"
    assert unlock_plan["steps"][0]["direct_unlocks"] == []
    assert unlock_plan["steps"][0]["partial_unlocks"] == ["first_real_paper_lifecycle_row"]
    assert unlock_plan["steps"][0]["combines_with"] == ["current_fresh_signal"]
    assert unlock_plan["steps"][1]["unlock_mode"] == "partial_dependency_clear"
    assert unlock_plan["steps"][1]["partial_unlocks"] == ["first_real_paper_lifecycle_row"]
    assert unlock_plan["steps"][1]["combines_with"] == ["operator_review_decisions"]
    assert unlock_plan["steps"][2]["unlock_mode"] == (
        "all_dependencies_required_before_manual_paper_apply"
    )
    assert unlock_plan["steps"][2]["direct_unlocks"] == ["execution_parity_samples"]
    assert unlock_plan["auto_decision_allowed"] is False
    assert unlock_plan["auto_apply_allowed"] is False
    assert unlock_plan["order_submission_allowed"] is False
    assert unlock_plan["no_live_order_sent"] is True
    assert set(summary["not_auto_completable_reasons"]) == {
        "fresh_signal_requires_realtime_market_event",
        "execution_parity_requires_real_reviewed_paper_lifecycle_rows",
        "quote_calendar_coverage_requires_future_utc_dates",
        "shadow_runtime_requires_continuous_calendar_observation",
        "operator_reviews_require_explicit_accept_or_reject",
    }
    assert summary["primary_automation_action"]["action_type"] == "monitor_fresh_signal"
    assert summary["primary_operator_decision_action"]["action_type"] == (
        "review_conditional_overfit_holdout_proxy"
    )
    assert summary["primary_wait_only_problem"]["id"] == "current_fresh_signal"
    assert summary["primary_dependency_blocked_problem"] is None
    assert summary["next_quote_window_kst"] == "2026-06-09T09:00:00+09:00"
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_remaining_work_closure_tracks_strategy_design_blocker_from_signal_diagnostics() -> None:
    summary = watch._remaining_work_closure_summary(
        unresolved_problem_register=[
            {
                "id": "current_fresh_signal",
                "status": "open_waiting_for_realtime_signal",
                "severity": "launch_blocker",
                "non_substitutable": True,
                "no_live_order_sent": True,
            }
        ],
        operator_work_queue={
            "automation_now": [],
            "effective_automation_now": [],
            "covered_automation_now": [],
            "startable_waits": [],
            "scheduled_waits": [],
            "no_live_order_sent": True,
        },
        operator_review_handoff_summary={"reviews": [], "no_live_order_sent": True},
        launch_blocker_priority_summary={"status": "waiting_for_realtime_evidence"},
        runtime_progress={"remaining_hours": 0.0, "no_live_order_sent": True},
        microstructure_watch={"coverage_plan": {"remaining_calendar_days": 0}},
        execution_parity_status_summary={"missing_samples": 0, "no_live_order_sent": True},
        fresh_signal_blocker_diagnostics={
            "cause_partition": {
                "strategy_design_blocker": {
                    "blocked": True,
                    "status": "offline_probe_candidate_failed_full_walk_forward_gate",
                    "primary_downstream_failure": (
                        "short_window_activity_inversion_and_full_wfo_activity_regression"
                    ),
                    "failed_checks": [
                        "activity_regression_blocks_signal_sparsity_fix"
                    ],
                    "activity_regression_candidate_count": 4,
                    "activity_inversion_candidate_count": 4,
                    "next_candidate_design_contract_status": (
                        "required_before_next_near_miss_family"
                    ),
                    "next_candidate_design_contract_reason": (
                        "current_short_window_activity_gains_do_not_survive_full_walk_forward"
                    ),
                    "runtime_filter_change_allowed": False,
                    "paper_or_live_promotion_allowed": False,
                    "operator_fixable_now": False,
                    "candidate_failure_digest": {
                        "candidate_count": 18,
                        "promoted_candidate_count": 4,
                        "active_full_walk_forward_candidate_count": 0,
                        "downstream_blocked_candidate_names": [
                            "quality_gated_mc12_near_miss_micro_probe"
                        ],
                        "worst_probe_add_delta_candidate": {
                            "candidate_name": "quality_gated_mc12_near_miss_micro_probe",
                            "probe_add_delta": -19,
                            "trade_like_events_delta": -3,
                        },
                    },
                    "root_cause_hints": [
                        "candidate_reduces_probe_activity_instead_of_solving_signal_sparsity"
                    ],
                    "no_live_order_sent": True,
                }
            }
        },
    )

    tracks = summary["actionability_tracks"]
    redesign = tracks["blocked_by_validation_redesign"]
    assert tracks["status"] == "realtime_wait_primary"
    assert tracks["primary_launch_wait_gate"] == "current_fresh_signal"
    assert redesign["count"] == 1
    assert redesign["primary_problem_id"] == "strategy_candidate_redesign_required"
    assert redesign["primary_next_action"] == "design_next_non_regressing_full_wfo_candidate"
    assert redesign["items"][0]["primary_downstream_failure"] == (
        "short_window_activity_inversion_and_full_wfo_activity_regression"
    )
    assert redesign["items"][0]["next_candidate_design_contract_status"] == (
        "required_before_next_near_miss_family"
    )
    assert redesign["items"][0]["minimum_full_walk_forward_requirements"] == {}
    assert redesign["items"][0]["candidate_failure_digest"][
        "active_full_walk_forward_candidate_count"
    ] == 0
    assert redesign["items"][0]["root_cause_hints"] == [
        "candidate_reduces_probe_activity_instead_of_solving_signal_sparsity"
    ]
    assert redesign["items"][0]["runtime_filter_change_allowed"] is False
    assert redesign["items"][0]["paper_or_live_promotion_allowed"] is False
    assert redesign["order_submission_allowed"] is False
    assert redesign["no_live_order_sent"] is True


def test_validation_redesign_runbook_preserves_next_candidate_contract() -> None:
    runbook = watch._validation_redesign_runbook(
        actionability_tracks={
            "blocked_by_validation_redesign": {
                "count": 1,
                "items": [
                    {
                        "id": "strategy_candidate_redesign_required",
                        "next_action": "design_next_non_regressing_full_wfo_candidate",
                        "primary_downstream_failure": (
                            "short_window_activity_inversion_and_full_wfo_activity_regression"
                        ),
                        "failed_checks": [
                            "activity_regression_blocks_signal_sparsity_fix"
                        ],
                        "activity_regression_candidate_count": 4,
                        "activity_inversion_candidate_count": 4,
                        "next_candidate_design_contract_status": (
                            "required_before_next_near_miss_family"
                        ),
                        "next_candidate_design_contract_reason": (
                            "current_short_window_activity_gains_do_not_survive_full_walk_forward"
                        ),
                        "minimum_full_walk_forward_requirements": {
                            "probe_add_delta_min": 0,
                            "trade_like_events_delta_min": 1,
                            "trade_like_activity_increase_required": True,
                            "signal_sparsity_fix_requires_trade_like_events_increase": True,
                            "compounded_return_delta_min_pct": -5.0,
                            "max_drawdown_worsening_max_pct": 3.0,
                            "positive_fold_delta_min": 0,
                            "activity_inversion_allowed": False,
                            "source_replay_lineage_guard_must_pass": True,
                        },
                        "required_validation_sequence": [
                            "smoke_windows_must_pass_activity_non_regression_contract",
                            "full_walk_forward_gate_must_run_with_require_nonregressing_activity",
                        ],
                        "reject_patterns": [
                            "short_window_smoke_activity_increase_inverts_to_full_wfo_activity_regression"
                        ],
                        "runtime_filter_change_allowed": False,
                        "paper_or_live_promotion_allowed": False,
                        "operator_fixable_now": False,
                        "source": (
                            "fresh_signal_blocker_diagnostics.cause_partition.strategy_design_blocker"
                        ),
                        "no_live_order_sent": True,
                    }
                ],
                "no_live_order_sent": True,
            }
        },
        fresh_signal_blocker_diagnostics={
            "top_no_trade_reasons": [
                {"reason": "no_trade_MC12_low_confluence", "count": 12187}
            ],
            "dominant_no_trade_context": {
                "reason": "MC04_no_clear_first_touch",
                "probe_quality": "reject_low_quality_soft_context",
            },
            "safe_experiment_backlog": [
                {"name": "quality_gated_mc12_near_miss_micro_probe"}
            ],
            "dominant_probe_quality_blocker": "score_too_low",
            "probe_quality_blocker_counts": {
                "score_too_low": 120,
                "edge_too_low": 40,
            },
            "eligible_probe_contexts": [
                {
                    "context": (
                        "MC12_low_confluence|short|with_trend|downtrend|normal|"
                        "score_4-5|edge_2-4|stack_2-4|ext_0.75-1.5|break_0-0.1"
                    ),
                    "reason": "MC12_low_confluence",
                    "count": 8,
                    "side": "short",
                    "side_alignment": "with_trend",
                    "regime": "downtrend",
                    "execution_context": "normal",
                    "score_bucket": "score_4-5",
                    "edge_bucket": "edge_2-4",
                    "reason_stack_bucket": "stack_2-4",
                    "extension_bucket": "ext_0.75-1.5",
                    "probe_quality": "eligible_mc12_quality_gated_micro_probe",
                }
            ],
            "top_rejected_soft_contexts": [
                {
                    "reason": "MC04_no_clear_first_touch",
                    "count": 80,
                    "probe_quality": "reject_low_quality_soft_context",
                }
            ],
            "cause_partition": {
                "strategy_design_blocker": {
                    "candidate_failure_digest": {
                        "candidate_count": 18,
                        "promoted_candidate_count": 4,
                        "active_full_walk_forward_candidate_count": 0,
                        "downstream_blocked_candidate_names": [
                            "quality_gated_mc12_near_miss_micro_probe"
                        ],
                        "worst_probe_add_delta_candidate": {
                            "candidate_name": "quality_gated_mc12_near_miss_micro_probe",
                            "probe_add_delta": -19,
                            "trade_like_events_delta": -3,
                        },
                        "worst_trade_like_events_delta_candidate": {
                            "candidate_name": (
                                "quality_gated_mc12_downtrend_score5_edge2_stack2_ext10"
                            ),
                            "probe_add_delta": -111,
                            "trade_like_events_delta": -94,
                        },
                    },
                    "root_cause_hints": [
                        "candidate_reduces_probe_activity_instead_of_solving_signal_sparsity",
                        "candidate_reduces_total_trade_like_events",
                    ],
                }
            }
        },
        strict_activity_revalidation_summary={
            "closest_activity_contract_candidate": {
                "candidate_name": "imp488_mc12_near_miss_00025_full_wf",
                "eligibility_status": "blocked_by_strict_full_walk_forward_gate",
                "why_not_default_candidate": (
                    "strict_revalidation_failed_or_activity_contract_not_met"
                ),
            },
            "next_candidate_design_constraints": {
                "status": "strict_activity_constraints_required",
                "must_increase_trade_like_events_delta_min": 1,
                "must_not_reduce_probe_add_delta_min": 0,
                "reject_if": ["trade_like_events_delta_less_than_1"],
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
    )

    assert runbook["status"] == "non_regressing_candidate_design_required"
    assert runbook["primary_problem_id"] == "strategy_candidate_redesign_required"
    assert runbook["primary_next_action"] == "design_next_non_regressing_full_wfo_candidate"
    assert runbook["primary_downstream_failure"] == (
        "short_window_activity_inversion_and_full_wfo_activity_regression"
    )
    assert runbook["required_design_properties"]["probe_add_delta_min"] == 0
    assert runbook["required_design_properties"]["trade_like_events_delta_min"] == 1
    assert runbook["required_design_properties"]["trade_like_activity_increase_required"] is True
    assert (
        runbook["required_design_properties"][
            "signal_sparsity_fix_requires_trade_like_events_increase"
        ]
        is True
    )
    assert runbook["required_design_properties"]["activity_inversion_allowed"] is False
    assert runbook["required_validation_sequence"] == [
        "smoke_windows_must_pass_activity_non_regression_contract",
        "full_walk_forward_gate_must_run_with_require_nonregressing_activity",
    ]
    assert "force_current_fresh_signal" in runbook["unsafe_shortcuts"]
    assert "run_full_walk_forward_gate_with_require_nonregressing_activity" in runbook[
        "safe_next_steps"
    ]
    assert runbook["current_failed_family_summary"][
        "active_full_walk_forward_candidate_count"
    ] == 0
    assert runbook["current_failed_family_summary"]["worst_probe_add_delta_candidate"][
        "candidate_name"
    ] == "quality_gated_mc12_near_miss_micro_probe"
    assert runbook["current_failed_family_summary"]["worst_trade_like_events_delta_candidate"][
        "trade_like_events_delta"
    ] == -94
    assert runbook["redesign_hypothesis"] == (
        "short_window_activity_gains_must_survive_full_wfo_without_probe_or_trade_like_regression"
    )
    work_order = runbook["candidate_redesign_work_order"]
    assert work_order["status"] == "ready_for_research_only_candidate_design"
    assert work_order["objective"] == (
        "design_non_regressing_signal_sparsity_candidate_that_survives_strict_full_wfo"
    )
    assert work_order["current_no_signal_driver"] == "no_trade_MC12_low_confluence"
    assert work_order["dominant_no_trade_context_quality"] == (
        "reject_low_quality_soft_context"
    )
    assert work_order["primary_safe_experiment_family"] == (
        "quality_gated_mc12_near_miss_micro_probe"
    )
    assert work_order["dominant_probe_quality_blocker"] == "score_too_low"
    assert work_order["probe_quality_blocker_counts"]["score_too_low"] == 120
    assert work_order["candidate_design_seed_contexts"][0]["reason"] == (
        "MC12_low_confluence"
    )
    assert work_order["candidate_design_seed_contexts"][0]["probe_quality"] == (
        "eligible_mc12_quality_gated_micro_probe"
    )
    assert work_order["candidate_design_blueprint_status"] == (
        "seed_context_blueprints_ready"
    )
    assert work_order["candidate_design_blueprint_count"] == 1
    blueprint = work_order["candidate_design_blueprints"][0]
    assert blueprint["id"] == "seeded_mc12_short_downtrend_normal_with_trend_v1"
    assert blueprint["smoke_candidate_recipe_id"] == (
        "seeded_mc12_downtrend_score4_edge2_stack2_ext15_cooldown72"
    )
    assert blueprint["overlay_config"]["near_miss_probe_allowed_regimes"] == [
        "downtrend"
    ]
    assert blueprint["overlay_config"]["near_miss_probe_min_score"] == 4
    assert blueprint["overlay_config"]["near_miss_probe_min_score_edge"] == 2
    assert blueprint["overlay_config"]["near_miss_probe_min_reason_stack"] == 2
    assert "run_market_state_rotation_v6_walk_forward_validation.py" in blueprint[
        "candidate_generation_command_template"
    ]
    assert "--near-miss-probe-allowed-regimes downtrend" in blueprint[
        "candidate_generation_command_template"
    ]
    assert blueprint["smoke_validation_command_templates"][0][
        "expected_candidate_row"
    ] == "seeded_mc12_downtrend_score4_edge2_stack2_ext15_cooldown72"
    assert "--near-miss-probe-allowed-soft-reasons" in blueprint["cli_overlay_args"]
    assert blueprint["validation_only"] is True
    assert blueprint["order_submission_allowed"] is False
    assert work_order["top_rejected_soft_contexts"][0]["reason"] == (
        "MC04_no_clear_first_touch"
    )
    assert work_order["closest_rejected_candidate"]["candidate_name"] == (
        "imp488_mc12_near_miss_00025_full_wf"
    )
    assert work_order["next_candidate_design_constraints"]["status"] == (
        "strict_activity_constraints_required"
    )
    assert work_order["next_candidate_design_constraints"][
        "must_increase_trade_like_events_delta_min"
    ] == 1
    assert "trade_like_events_delta_less_than_1" in work_order[
        "next_candidate_design_constraints"
    ]["reject_if"]
    assert work_order["minimum_acceptance"]["trade_like_events_delta_min"] == 1
    assert work_order["minimum_acceptance"][
        "active_full_walk_forward_candidate_count_min"
    ] == 1
    assert "use_closest_rejected_candidate_as_default" in work_order[
        "forbidden_shortcuts"
    ]
    assert work_order["order_submission_allowed"] is False
    assert work_order["no_live_order_sent"] is True
    assert "candidate_reduces_total_trade_like_events" in runbook["root_cause_hints"]
    assert runbook["required_placeholder_count"] == 7
    assert runbook["validation_command_template_count"] == 4
    assert "<candidate_backtest_report.json>" in runbook["candidate_design_placeholders"]
    commands = [item["command"] for item in runbook["validation_command_templates"]]
    assert commands[0].startswith(
        ".venv/bin/python scripts/run_market_state_rotation_v6_near_miss_smoke.py"
    )
    assert "--days 120" in commands[0]
    assert "--days 365" in commands[1]
    assert "--require-nonregressing-activity" in commands[2]
    assert "scripts/run_market_state_rotation_v6_near_miss_promotion_gate.py" in commands[3]
    assert all(
        item["validation_only"] is True
        and item["order_submission_allowed"] is False
        for item in runbook["validation_command_templates"]
    )
    assert runbook["command_template_safety"] == {
        "templates_are_placeholders": True,
        "validation_only": True,
        "dry_run_or_validation_only": True,
        "requires_operator_supplied_candidate_reports": True,
        "runtime_filter_change_allowed": False,
        "paper_or_live_promotion_allowed": False,
        "order_submission_allowed": False,
        "live_order_submission_allowed": False,
        "no_live_order_sent": True,
    }
    assert runbook["runtime_filter_change_allowed"] is False
    assert runbook["paper_or_live_promotion_allowed"] is False
    assert runbook["order_submission_allowed"] is False
    assert runbook["no_live_order_sent"] is True


def test_no_signal_resolution_summary_separates_wait_from_candidate_redesign() -> None:
    summary = watch._no_signal_resolution_summary(
        fresh_signal_blocker_diagnostics={
            "status": "blocked_waiting_for_fresh_signal",
            "signal_pipeline_issue_suspected": False,
            "rejected_soft_context_count": 6510,
            "eligible_probe_context_count": 1,
            "top_no_trade_reasons": [
                {"reason": "no_trade_MC12_low_confluence", "count": 12188}
            ],
            "dominant_no_trade_context": {
                "reason": "MC04_no_clear_first_touch",
                "probe_quality": "reject_low_quality_soft_context",
            },
            "dominant_probe_quality_blocker": "score_too_low",
            "probe_quality_blocker_counts": {"score_too_low": 120},
            "eligible_probe_contexts": [
                {
                    "context": (
                        "MC12_low_confluence|short|with_trend|downtrend|normal|"
                        "score_4-5|edge_2-4|stack_2-4|ext_0.75-1.5|break_0-0.1"
                    ),
                    "reason": "MC12_low_confluence",
                    "count": 8,
                    "side": "short",
                    "side_alignment": "with_trend",
                    "regime": "downtrend",
                    "execution_context": "normal",
                    "score_bucket": "score_4-5",
                    "edge_bucket": "edge_2-4",
                    "reason_stack_bucket": "stack_2-4",
                    "extension_bucket": "ext_0.75-1.5",
                    "probe_quality": "eligible_mc12_quality_gated_micro_probe",
                }
            ],
            "top_rejected_soft_contexts": [
                {
                    "reason": "MC04_no_clear_first_touch",
                    "count": 80,
                    "probe_quality": "reject_low_quality_soft_context",
                    "probe_quality_reasons": ["score_too_low"],
                }
            ],
            "fresh_signal_resolution_plan": {
                "operator_fixable_now": False,
                "no_live_order_sent": True,
            },
            "cause_partition": {
                "status": "healthy_runtime_wait_strategy_candidate_redesign_required",
                "runtime_signal_absence": {
                    "healthy_sparse_wait": True,
                },
                "strategy_design_blocker": {
                    "blocked": True,
                    "failed_checks": ["activity_regression_blocks_signal_sparsity_fix"],
                    "operator_fixable_now": False,
                    "no_live_order_sent": True,
                },
            },
            "no_live_order_sent": True,
        },
        validation_redesign_runbook={
            "status": "non_regressing_candidate_design_required",
            "current_failed_family_summary": {
                "active_full_walk_forward_candidate_count": 0
            },
            "candidate_redesign_work_order": {
                "minimum_acceptance": {
                    "probe_add_delta_min": 0,
                    "trade_like_events_delta_min": 1,
                },
                "next_candidate_design_constraints": {
                    "status": "strict_activity_constraints_required",
                    "must_increase_trade_like_events_delta_min": 1,
                    "must_not_reduce_probe_add_delta_min": 0,
                    "no_live_order_sent": True,
                },
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
        strict_activity_revalidation_summary={
            "status": "all_strict_revalidations_blocked",
            "report_count": 4,
            "blocked_count": 4,
            "closest_activity_contract_candidate": {
                "candidate_name": "imp488_mc12_near_miss_00025_full_wf",
                "trade_like_events_delta": 0.0,
                "probe_add_delta": 0.0,
                "primary_blockers": [
                    "activity_regression_blocks_signal_sparsity_fix",
                    "trade_like_activity_did_not_increase",
                ],
                "why_not_default_candidate": (
                    "strict_revalidation_failed_or_activity_contract_not_met"
                ),
            },
            "next_candidate_design_constraints": {
                "status": "strict_activity_constraints_required",
                "must_increase_trade_like_events_delta_min": 1,
                "must_not_reduce_probe_add_delta_min": 0,
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
    )

    assert summary["status"] == "healthy_runtime_wait_but_candidate_redesign_required"
    assert summary["root_cause"] == (
        "low_confluence_soft_contexts_current_candidate_failed_strict_activity_contract"
    )
    assert summary["runtime_wait_is_healthy_sparse_cadence"] is True
    assert summary["strategy_candidate_redesign_required"] is True
    assert summary["signal_pipeline_issue_suspected"] is False
    assert summary["top_no_trade_reason"] == "no_trade_MC12_low_confluence"
    assert summary["dominant_no_trade_context_reason"] == "MC04_no_clear_first_touch"
    assert summary["dominant_probe_quality_blocker"] == "score_too_low"
    assert summary["probe_quality_blocker_counts"]["score_too_low"] == 120
    assert summary["candidate_design_seed_context_count"] == 1
    assert summary["candidate_design_seed_contexts"][0]["reason"] == "MC12_low_confluence"
    assert summary["candidate_design_seed_contexts"][0]["edge_bucket"] == "edge_2-4"
    assert summary["candidate_design_blueprint_status"] == "seed_context_blueprints_ready"
    assert summary["candidate_design_blueprint_count"] == 1
    assert summary["candidate_design_blueprints"][0]["target_regime"] == "downtrend"
    assert summary["candidate_design_blueprints"][0]["acceptance_contract"][
        "trade_like_events_delta_min"
    ] == 1
    assert summary["candidate_design_blueprints"][0]["order_submission_allowed"] is False
    assert summary["top_rejected_soft_contexts"][0]["reason"] == (
        "MC04_no_clear_first_touch"
    )
    assert summary["closest_rejected_candidate"] == "imp488_mc12_near_miss_00025_full_wf"
    assert summary["blocked_reasons"] == [
        "activity_regression_blocks_signal_sparsity_fix",
        "trade_like_activity_did_not_increase",
    ]
    assert summary["required_next_candidate_trade_like_events_delta_min"] == 1
    assert summary["required_next_candidate_probe_add_delta_min"] == 0
    assert summary["safe_next_action"] == (
        "design_non_regressing_candidate_then_validate_with_strict_full_wfo_gate"
    )
    assert summary["force_signal_allowed"] is False
    assert summary["runtime_filter_change_allowed"] is False
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_no_signal_resolution_summary_reports_drawdown_repair_after_activity_fix() -> None:
    summary = watch._no_signal_resolution_summary(
        fresh_signal_blocker_diagnostics={
            "status": "blocked_waiting_for_fresh_signal",
            "signal_pipeline_issue_suspected": False,
            "top_no_trade_reasons": [
                {"reason": "no_trade_MC12_low_confluence", "count": 12188}
            ],
            "eligible_probe_contexts": [
                {
                    "context": (
                        "MC12_low_confluence|short|with_trend|downtrend|normal|"
                        "score_4-5|edge_2-4|stack_2-4|ext_0.75-1.5|break_0-0.1"
                    ),
                    "reason": "MC12_low_confluence",
                    "side": "short",
                    "side_alignment": "with_trend",
                    "regime": "downtrend",
                    "execution_context": "normal",
                    "score_bucket": "score_4-5",
                    "edge_bucket": "edge_2-4",
                    "reason_stack_bucket": "stack_2-4",
                    "extension_bucket": "ext_0.75-1.5",
                    "probe_quality": "eligible_mc12_quality_gated_micro_probe",
                }
            ],
            "cause_partition": {
                "status": "healthy_runtime_wait_strategy_candidate_redesign_required",
                "runtime_signal_absence": {"healthy_sparse_wait": True},
                "strategy_design_blocker": {"blocked": True},
            },
            "no_live_order_sent": True,
        },
        validation_redesign_runbook={
            "status": "non_regressing_candidate_design_required",
            "candidate_redesign_work_order": {
                "minimum_acceptance": {
                    "probe_add_delta_min": 0,
                    "trade_like_events_delta_min": 1,
                },
                "next_candidate_design_constraints": {
                    "status": "strict_risk_repair_constraints_required",
                    "activity_contract_solved_by_closest_candidate": True,
                    "remaining_primary_blockers": ["drawdown_worsening"],
                    "must_increase_trade_like_events_delta_min": 1,
                    "must_not_reduce_probe_add_delta_min": 0,
                    "must_keep_max_drawdown_worsening_pct_at_or_below": 3.0,
                },
            },
            "no_live_order_sent": True,
        },
        strict_activity_revalidation_summary={
            "status": "all_strict_revalidations_blocked",
            "activity_contract_solved_by_closest_candidate": True,
            "risk_repair_required": True,
            "remaining_primary_blockers": ["drawdown_worsening"],
            "closest_activity_contract_candidate": {
                "candidate_name": "seeded_mc12_downtrend_ext10",
                "trade_like_events_delta": 206,
                "probe_add_delta": 17,
                "primary_blockers": ["drawdown_worsening"],
            },
            "next_candidate_design_constraints": {
                "status": "strict_risk_repair_constraints_required",
                "activity_contract_solved_by_closest_candidate": True,
                "remaining_primary_blockers": ["drawdown_worsening"],
                "must_increase_trade_like_events_delta_min": 1,
                "must_not_reduce_probe_add_delta_min": 0,
                "must_keep_max_drawdown_worsening_pct_at_or_below": 3.0,
            },
            "no_live_order_sent": True,
        },
    )

    assert summary["status"] == "healthy_runtime_wait_but_risk_repair_required"
    assert summary["root_cause"] == (
        "seeded_mc12_candidate_fixed_signal_sparsity_but_failed_drawdown_contract"
    )
    assert summary["activity_contract_solved_by_closest_candidate"] is True
    assert summary["risk_repair_required"] is True
    assert summary["remaining_validation_blockers"] == ["drawdown_worsening"]
    assert summary["candidate_design_blueprints"][0]["risk_repair_candidate_recipe_ids"] == [
        "seeded_mc12_downtrend_score4_edge2_stack2_ext10_cooldown72",
        "quality_gated_mc12_downtrend_score5_edge2_stack2_ext10",
        "quality_gated_mc12_score5_edge2_stack2_ext10_cooldown144",
    ]
    risk_repair_template = summary["candidate_design_blueprints"][0][
        "risk_repair_command_templates"
    ][0]
    command_template = risk_repair_template["candidate_generation_command_template"]
    assert "--selection-max-reaction-usd 200" in command_template
    assert "--selection-mdd-soft-threshold-pct 20" in command_template
    assert "--selection-mdd-soft-penalty 0.01" in risk_repair_template[
        "candidate_generation_command_template"
    ]
    assert risk_repair_template["selection_safety_config"] == {
        "selection_max_reaction_usd": 200,
        "blocks_known_drawdown_worsening_reaction_usd": 350,
        "selection_mdd_soft_threshold_pct": 20,
        "selection_mdd_soft_penalty": 0.01,
    }
    assert summary["candidate_design_blueprints"][0]["acceptance_contract"][
        "max_drawdown_worsening_pct"
    ] == 3.0
    assert summary["required_next_candidate_trade_like_events_delta_min"] == 1
    assert summary["required_next_candidate_probe_add_delta_min"] == 0
    assert summary["required_next_candidate_constraint_status"] == (
        "strict_risk_repair_constraints_required"
    )
    assert summary["safe_next_action"] == (
        "repair_drawdown_regression_then_validate_with_strict_full_wfo_gate"
    )
    assert summary["no_live_order_sent"] is True


def test_no_signal_resolution_summary_clears_risk_repair_after_strict_pass() -> None:
    summary = watch._no_signal_resolution_summary(
        fresh_signal_blocker_diagnostics={
            "status": "blocked_waiting_for_fresh_signal",
            "signal_pipeline_issue_suspected": False,
            "top_no_trade_reasons": [
                {"reason": "no_trade_MC12_low_confluence", "count": 12188}
            ],
            "eligible_probe_contexts": [
                {
                    "context": (
                        "MC12_low_confluence|short|with_trend|downtrend|normal|"
                        "score_4-5|edge_2-4|stack_2-4|ext_0.75-1.5|break_0-0.1"
                    ),
                    "reason": "MC12_low_confluence",
                    "side": "short",
                    "side_alignment": "with_trend",
                    "regime": "downtrend",
                    "execution_context": "normal",
                    "score_bucket": "score_4-5",
                    "edge_bucket": "edge_2-4",
                    "reason_stack_bucket": "stack_2-4",
                    "extension_bucket": "ext_0.75-1.5",
                    "probe_quality": "eligible_mc12_quality_gated_micro_probe",
                }
            ],
            "cause_partition": {
                "status": "healthy_runtime_wait_strategy_candidate_redesign_required",
                "runtime_signal_absence": {"healthy_sparse_wait": True},
                "strategy_design_blocker": {"blocked": True},
            },
            "no_live_order_sent": True,
        },
        validation_redesign_runbook={
            "status": "non_regressing_candidate_design_required",
            "candidate_redesign_work_order": {
                "minimum_acceptance": {
                    "probe_add_delta_min": 0,
                    "trade_like_events_delta_min": 1,
                },
                "next_candidate_design_constraints": {
                    "status": "strict_risk_repair_constraints_required",
                    "activity_contract_solved_by_closest_candidate": True,
                    "remaining_primary_blockers": ["drawdown_worsening"],
                    "must_increase_trade_like_events_delta_min": 1,
                    "must_not_reduce_probe_add_delta_min": 0,
                    "must_keep_max_drawdown_worsening_pct_at_or_below": 3.0,
                },
            },
            "no_live_order_sent": True,
        },
        strict_activity_revalidation_summary={
            "status": "strict_revalidation_candidate_available",
            "report_count": 9,
            "blocked_count": 8,
            "passed_count": 1,
            "activity_contract_solved_by_closest_candidate": True,
            "risk_repair_required": False,
            "remaining_primary_blockers": [],
            "strict_revalidated_candidate": {
                "candidate_name": (
                    "seeded_mc12_downtrend_score4_edge2_stack2_ext10_cooldown72_"
                    "react200cap_mdd20p01_full_wfo"
                ),
                "decision": "eligible_for_paper_evidence_collection_only",
                "trade_like_events_delta": 206,
                "probe_add_delta": 17,
                "primary_blockers": [],
                "eligibility_status": "eligible_strict_candidate",
            },
            "closest_activity_contract_candidate": {
                "candidate_name": (
                    "seeded_mc12_downtrend_score4_edge2_stack2_ext10_cooldown72_"
                    "react200cap_mdd20p01_full_wfo"
                ),
                "decision": "eligible_for_paper_evidence_collection_only",
                "trade_like_events_delta": 206,
                "probe_add_delta": 17,
                "primary_blockers": [],
                "eligibility_status": "eligible_strict_candidate",
            },
            "next_candidate_design_constraints": {
                "status": "strict_revalidation_candidate_available",
                "activity_contract_solved_by_closest_candidate": True,
                "remaining_primary_blockers": [],
                "must_increase_trade_like_events_delta_min": 1,
                "must_not_reduce_probe_add_delta_min": 0,
            },
            "no_live_order_sent": True,
        },
    )

    assert summary["status"] == "healthy_sparse_runtime_wait"
    assert summary["root_cause"] == (
        "strict_revalidation_candidate_available_waiting_for_fresh_signal"
    )
    assert summary["strategy_candidate_redesign_required"] is False
    assert summary["strict_revalidated_candidate_available"] is True
    assert summary["strict_revalidated_candidate"]["decision"] == (
        "eligible_for_paper_evidence_collection_only"
    )
    assert summary["risk_repair_required"] is False
    assert summary["remaining_validation_blockers"] == []
    assert summary["candidate_design_blueprints"][0]["risk_repair_candidate_recipe_ids"] == []
    assert summary["closest_rejected_candidate"] is None
    assert summary["blocked_reasons"] == []
    assert summary["required_next_candidate_constraint_status"] == (
        "strict_revalidation_candidate_available"
    )
    assert summary["safe_next_action"] == "monitor_fresh_signal_without_forcing_entry"
    assert summary["no_live_order_sent"] is True


def test_candidate_design_blueprints_convert_seed_contexts_to_validation_only_overlays() -> None:
    summary = watch._candidate_design_blueprints_from_seed_contexts(
        [
            {
                "context": (
                    "MC12_low_confluence|long|with_trend|uptrend|normal|"
                    "score_3-5|edge_2-4|stack_1-2|ext_0.75-1.5|break_0-0.1"
                ),
                "reason": "MC12_low_confluence",
                "count": 5,
                "side": "long",
                "side_alignment": "with_trend",
                "regime": "uptrend",
                "execution_context": "normal",
                "score_bucket": "score_3-5",
                "edge_bucket": "edge_2-4",
                "reason_stack_bucket": "stack_1-2",
                "extension_bucket": "ext_0.75-1.5",
                "probe_quality": "eligible_mc12_quality_gated_micro_probe",
            },
            {
                "context": (
                    "MC12_low_confluence|short|with_trend|downtrend|normal|"
                    "score_3-5|edge_2-4|stack_1-2|ext_0.75-1.5|break_0-0.1"
                ),
                "reason": "MC12_low_confluence",
                "count": 4,
                "side": "short",
                "side_alignment": "with_trend",
                "regime": "downtrend",
                "execution_context": "normal",
                "score_bucket": "score_3-5",
                "edge_bucket": "edge_2-4",
                "reason_stack_bucket": "stack_1-2",
                "extension_bucket": "ext_0.75-1.5",
                "probe_quality": "eligible_mc12_quality_gated_micro_probe",
            },
        ],
        top_rejected_soft_contexts=[
            {"reason": "MC04_no_clear_first_touch", "count": 25},
        ],
        constraints={
            "must_not_reduce_probe_add_delta_min": 0,
            "must_increase_trade_like_events_delta_min": 1,
        },
        dominant_probe_quality_blocker="score_too_low",
    )

    assert summary["status"] == "seed_context_blueprints_ready"
    assert summary["blueprint_count"] == 2
    assert summary["excluded_rejected_context_reasons"] == ["MC04_no_clear_first_touch"]
    assert summary["order_submission_allowed"] is False
    long_blueprint = summary["blueprints"][0]
    assert long_blueprint["id"] == "seeded_mc12_long_uptrend_normal_with_trend_v1"
    assert long_blueprint["smoke_candidate_recipe_id"] == (
        "seeded_mc12_uptrend_score4_edge2_stack2_ext15_cooldown72"
    )
    assert long_blueprint["overlay_config"] == {
        "near_miss_probe_units": 0.00025,
        "near_miss_probe_min_score": 4,
        "near_miss_probe_min_score_edge": 2,
        "near_miss_probe_min_reason_stack": 2,
        "near_miss_probe_cooldown_bars": 72,
        "near_miss_probe_max_extension_atr": 1.5,
        "near_miss_probe_failure_guard_count": 2,
        "near_miss_probe_failure_guard_window_bars": 1440,
        "near_miss_probe_failure_cooldown_bars": 4320,
        "near_miss_probe_allowed_soft_reasons": ["MC12_low_confluence"],
        "near_miss_probe_allowed_alignments": ["with_trend"],
        "near_miss_probe_allowed_execution_contexts": ["normal"],
        "near_miss_probe_allowed_regimes": ["uptrend"],
    }
    assert "run_market_state_rotation_v6_walk_forward_validation.py" in long_blueprint[
        "candidate_generation_command_template"
    ]
    assert "--near-miss-probe-allowed-regimes uptrend" in long_blueprint[
        "candidate_generation_command_template"
    ]
    assert len(long_blueprint["smoke_validation_command_templates"]) == 2
    assert long_blueprint["smoke_validation_command_templates"][1]["window_days"] == 365
    assert long_blueprint["smoke_validation_command_templates"][1][
        "validation_only"
    ] is True
    assert "--near-miss-probe-units" in long_blueprint["cli_overlay_args"]
    assert "MC12_low_confluence" in long_blueprint["cli_overlay_args"]
    assert "uptrend" in long_blueprint["cli_overlay_args"]
    assert long_blueprint["acceptance_contract"] == {
        "probe_add_delta_min": 0,
        "trade_like_events_delta_min": 1,
        "max_drawdown_worsening_pct": None,
        "strict_full_walk_forward_require_nonregressing_activity": True,
    }
    assert "trade_like_events_delta_less_than_1" in long_blueprint["reject_if"]
    assert long_blueprint["paper_or_live_promotion_allowed"] is False
    assert long_blueprint["no_live_order_sent"] is True


def test_strict_activity_revalidation_summary_blocks_legacy_candidates(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    first_report = (
        evidence_root
        / "market_state_rotation_v6_imp468_context_guard_block_mid_event_soft_strict_activity_gate"
        / "market_state_rotation_v6_full_walk_forward_gate.json"
    )
    second_report = (
        evidence_root
        / "market_state_rotation_v6_imp488_mc12_near_miss_00025_strict_activity_gate"
        / "market_state_rotation_v6_full_walk_forward_gate.json"
    )
    for path, candidate, probe_delta, trade_delta, sparsity_failure_reasons in [
        (
            first_report,
            "imp468_context_guard_block_mid_event_soft",
            -13,
            -13,
            [],
        ),
        (
            second_report,
            "imp488_mc12_near_miss_00025",
            0,
            0,
            ["trade_like_activity_did_not_increase"],
        ),
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "candidate_name": candidate,
                    "overall_status": "blocked",
                    "decision": "do_not_promote_to_paper_or_live",
                    "failed_checks": [
                        "activity_regression_blocks_signal_sparsity_fix"
                    ],
                    "gates": {"require_nonregressing_activity": True},
                    "deltas": {
                        "compounded_oos_return_pct": 84.0,
                        "max_fold_drawdown_pct": 0.0,
                        "positive_fold_count": 0,
                    },
                    "activity_regression_summary": {
                        "probe_add_delta": probe_delta,
                        "trade_like_events_delta": trade_delta,
                        "diagnostic_labels": [
                            "candidate_reduces_probe_activity_instead_of_solving_signal_sparsity"
                        ],
                        "strict_signal_sparsity_fix_failure_reasons": (
                            sparsity_failure_reasons
                        ),
                    },
                    "no_live_order_sent": True,
                }
            ),
            encoding="utf-8",
        )

    summary = watch._strict_activity_revalidation_summary(evidence_root)

    assert summary["status"] == "all_strict_revalidations_blocked"
    assert summary["report_count"] == 2
    assert summary["blocked_count"] == 2
    assert summary["passed_count"] == 0
    assert summary["strict_gate_present_count"] == 2
    assert summary["strict_gate_missing_count"] == 0
    assert summary["safety_blocked_count"] == 0
    assert summary["strict_revalidated_promoted_legacy_reports_blocked"] is True
    assert summary["all_reports_validation_only"] is True
    assert summary["strict_activity_contract"] == {
        "probe_add_delta_min": 0,
        "trade_like_events_delta_min": 1,
        "trade_like_activity_increase_required": True,
        "signal_sparsity_fix_requires_trade_like_events_increase": True,
    }
    assert summary["strict_signal_sparsity_failure_reason_counts"] == {
        "trade_like_activity_did_not_increase": 1
    }
    assert summary["failed_check_counts"] == {
        "activity_regression_blocks_signal_sparsity_fix": 2
    }
    constraints = summary["next_candidate_design_constraints"]
    assert constraints["status"] == "strict_activity_constraints_required"
    assert constraints["must_run_strict_full_wfo_gate"] is True
    assert constraints["must_have_zero_failed_checks"] is True
    assert constraints["must_increase_trade_like_events_delta_min"] == 1
    assert constraints["must_not_reduce_probe_add_delta_min"] == 0
    assert constraints["must_not_reduce_total_trade_like_events"] is True
    assert constraints["must_beat_closest_rejected_candidate_trade_like_delta"] == 0.0
    assert constraints["must_beat_closest_rejected_candidate_probe_delta"] == 0.0
    assert "trade_like_events_delta_less_than_1" in constraints["reject_if"]
    assert constraints["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True
    assert summary["best_probe_delta_report"]["candidate_name"] == (
        "imp488_mc12_near_miss_00025"
    )
    assert summary["best_trade_like_delta_report"]["trade_like_events_delta"] == 0.0
    closest = summary["closest_activity_contract_candidate"]
    assert closest["candidate_name"] == "imp488_mc12_near_miss_00025"
    assert closest["eligibility_status"] == "blocked_by_strict_full_walk_forward_gate"
    assert closest["why_not_default_candidate"] == (
        "strict_revalidation_failed_or_activity_contract_not_met"
    )
    assert closest["primary_blockers"] == [
        "activity_regression_blocks_signal_sparsity_fix",
        "trade_like_activity_did_not_increase",
    ]
    assert closest["no_live_order_sent"] is True
    assert summary["diagnostic_label_counts"][
        "candidate_reduces_probe_activity_instead_of_solving_signal_sparsity"
    ] == 2


def test_strict_activity_revalidation_summary_switches_to_risk_repair_after_activity_fix(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    report_path = (
        evidence_root
        / "market_state_rotation_v6_seeded_mc12_downtrend_ext10_strict_activity_gate"
        / "market_state_rotation_v6_full_walk_forward_gate.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "candidate_name": "seeded_mc12_downtrend_ext10",
                "overall_status": "blocked",
                "decision": "do_not_promote_to_paper_or_live",
                "failed_checks": ["drawdown_worsening"],
                "gates": {
                    "require_nonregressing_activity": True,
                    "max_drawdown_worsening_pct": 3.0,
                },
                "deltas": {
                    "compounded_oos_return_pct": 69.0,
                    "max_fold_drawdown_pct": 9.03,
                    "positive_fold_count": 0,
                },
                "activity_regression_summary": {
                    "probe_add_delta": 17,
                    "trade_like_events_delta": 206,
                    "diagnostic_labels": [],
                    "strict_signal_sparsity_fix_failure_reasons": [],
                },
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    summary = watch._strict_activity_revalidation_summary(evidence_root)

    assert summary["status"] == "all_strict_revalidations_blocked"
    assert summary["activity_contract_solved_by_closest_candidate"] is True
    assert summary["risk_repair_required"] is True
    assert summary["remaining_primary_blockers"] == ["drawdown_worsening"]
    constraints = summary["next_candidate_design_constraints"]
    assert constraints["status"] == "strict_risk_repair_constraints_required"
    assert constraints["activity_contract_solved_by_closest_candidate"] is True
    assert constraints["remaining_primary_blockers"] == ["drawdown_worsening"]
    assert constraints["must_not_reduce_total_trade_like_events"] is False
    assert constraints["must_keep_max_drawdown_worsening_pct_at_or_below"] == 3.0
    assert constraints["must_beat_closest_rejected_candidate_trade_like_delta"] is None
    assert constraints["must_beat_closest_rejected_candidate_probe_delta"] is None
    assert "drawdown_worsening" in constraints["reject_if"]
    closest = summary["closest_activity_contract_candidate"]
    assert closest["candidate_name"] == "seeded_mc12_downtrend_ext10"
    assert closest["primary_blockers"] == ["drawdown_worsening"]
    assert closest["strict_activity_gate_present"] is True
    assert closest["why_not_default_candidate"] == (
        "strict_revalidation_failed_drawdown_worsening_after_activity_contract_met"
    )


def test_strict_activity_revalidation_summary_prefers_passed_candidate_over_stale_blocker(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    blocked_report = (
        evidence_root
        / "market_state_rotation_v6_seeded_mc12_downtrend_ext15_strict_activity_gate"
        / "market_state_rotation_v6_full_walk_forward_gate.json"
    )
    passed_report = (
        evidence_root
        / "market_state_rotation_v6_seeded_mc12_downtrend_ext10_react200_mdd20_strict_activity_gate"
        / "market_state_rotation_v6_full_walk_forward_gate.json"
    )
    blocked_report.parent.mkdir(parents=True, exist_ok=True)
    passed_report.parent.mkdir(parents=True, exist_ok=True)
    blocked_report.write_text(
        json.dumps(
            {
                "candidate_name": "seeded_mc12_downtrend_ext15",
                "overall_status": "blocked",
                "decision": "do_not_promote_to_paper_or_live",
                "failed_checks": ["drawdown_worsening"],
                "gates": {
                    "require_nonregressing_activity": True,
                    "max_drawdown_worsening_pct": 3.0,
                },
                "deltas": {
                    "compounded_oos_return_pct": 99.3,
                    "max_fold_drawdown_pct": 9.03,
                    "positive_fold_count": 0,
                },
                "activity_regression_summary": {
                    "probe_add_delta": 44,
                    "trade_like_events_delta": 232,
                    "diagnostic_labels": [],
                    "strict_signal_sparsity_fix_failure_reasons": [],
                },
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )
    passed_report.write_text(
        json.dumps(
            {
                "candidate_name": "seeded_mc12_downtrend_ext10_react200_mdd20",
                "overall_status": "return_improving",
                "decision": "eligible_for_paper_evidence_collection_only",
                "failed_checks": [],
                "gates": {
                    "require_nonregressing_activity": True,
                    "max_drawdown_worsening_pct": 3.0,
                },
                "deltas": {
                    "compounded_oos_return_pct": 723.1,
                    "max_fold_drawdown_pct": -1.19,
                    "positive_fold_count": 0,
                },
                "activity_regression_summary": {
                    "probe_add_delta": 17,
                    "trade_like_events_delta": 206,
                    "diagnostic_labels": [],
                    "strict_signal_sparsity_fix_failure_reasons": [],
                },
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    summary = watch._strict_activity_revalidation_summary(evidence_root)

    assert summary["status"] == "strict_revalidation_candidate_available"
    assert summary["passed_count"] == 1
    assert summary["blocked_count"] == 1
    assert summary["activity_contract_solved_by_closest_candidate"] is True
    assert summary["risk_repair_required"] is False
    assert summary["remaining_primary_blockers"] == []
    assert summary["max_drawdown_worsening_pct_required"] is None
    constraints = summary["next_candidate_design_constraints"]
    assert constraints["status"] == "strict_revalidation_candidate_available"
    assert constraints["remaining_primary_blockers"] == []
    assert constraints["must_keep_max_drawdown_worsening_pct_at_or_below"] is None
    assert summary["strict_revalidated_candidate"]["candidate_name"] == (
        "seeded_mc12_downtrend_ext10_react200_mdd20"
    )
    closest = summary["closest_activity_contract_candidate"]
    assert closest["candidate_name"] == "seeded_mc12_downtrend_ext10_react200_mdd20"
    assert closest["primary_blockers"] == []
    assert closest["eligibility_status"] == "eligible_strict_candidate"
    assert closest["why_not_default_candidate"] is None


def test_strict_activity_revalidation_summary_requires_strict_gate_and_safety(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    missing_gate_report = (
        evidence_root
        / "market_state_rotation_v6_missing_gate_strict_activity_gate"
        / "market_state_rotation_v6_full_walk_forward_gate.json"
    )
    safety_report = (
        evidence_root
        / "market_state_rotation_v6_safety_flag_strict_activity_gate"
        / "market_state_rotation_v6_full_walk_forward_gate.json"
    )
    missing_gate_report.parent.mkdir(parents=True, exist_ok=True)
    safety_report.parent.mkdir(parents=True, exist_ok=True)
    missing_gate_report.write_text(
        json.dumps(
            {
                "candidate_name": "missing_gate_candidate",
                "overall_status": "risk_compressed",
                "decision": "eligible_for_paper_evidence_collection_only",
                "failed_checks": [],
                "gates": {"require_nonregressing_activity": False},
                "activity_regression_summary": {
                    "probe_add_delta": 1,
                    "trade_like_events_delta": 1,
                },
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )
    safety_report.write_text(
        json.dumps(
            {
                "candidate_name": "safety_flag_candidate",
                "overall_status": "risk_compressed",
                "decision": "eligible_for_paper_evidence_collection_only",
                "failed_checks": [],
                "gates": {"require_nonregressing_activity": True},
                "activity_regression_summary": {
                    "probe_add_delta": 2,
                    "trade_like_events_delta": 2,
                },
                "no_live_order_sent": False,
            }
        ),
        encoding="utf-8",
    )

    summary = watch._strict_activity_revalidation_summary(evidence_root)

    assert summary["status"] == "all_strict_revalidations_blocked"
    assert summary["report_count"] == 2
    assert summary["blocked_count"] == 2
    assert summary["passed_count"] == 0
    assert summary["strict_gate_present_count"] == 1
    assert summary["strict_gate_missing_count"] == 1
    assert summary["safety_blocked_count"] == 1
    assert summary["no_live_order_sent"] is False
    rows = {row["candidate_name"]: row for row in summary["reports"]}
    assert rows["missing_gate_candidate"]["strict_revalidation_passed"] is False
    assert rows["missing_gate_candidate"]["strict_revalidation_blockers"] == [
        "strict_activity_gate_missing"
    ]
    assert rows["safety_flag_candidate"]["strict_revalidation_blockers"] == [
        "no_live_order_sent_false"
    ]
    assert summary["closest_activity_contract_candidate"]["candidate_name"] == (
        "safety_flag_candidate"
    )
    assert summary["closest_activity_contract_candidate"]["eligibility_status"] == (
        "blocked_by_strict_full_walk_forward_gate"
    )


def test_remaining_work_closure_prefers_effective_queue_over_raw_covered_automation() -> None:
    summary = watch._remaining_work_closure_summary(
        unresolved_problem_register=[
            {
                "id": "current_fresh_signal",
                "status": "open_waiting_for_realtime_signal",
                "severity": "launch_blocker",
                "non_substitutable": True,
                "next_action": "monitor_without_forcing_entry",
                "no_live_order_sent": True,
            },
            {
                "id": "conditional_overfit_operator_review",
                "status": "open_operator_review_required_for_paper_only_candidate_activation",
                "severity": "paper_candidate_blocker",
                "non_substitutable": False,
                "next_action": "complete_or_reject_conditional_overfit_proxy_review_for_paper_only_scope",
                "no_live_order_sent": True,
            },
        ],
        operator_work_queue={
            "automation_now": [
                {
                    "action_type": "monitor_fresh_signal",
                    "target_gate": "current_fresh_signal",
                    "command": "monitor",
                    "execute_after_utc": "2026-01-01T00:05:00+00:00",
                    "execute_after_kst": "2026-01-01T09:05:00+09:00",
                    "covered_by_current_iteration": True,
                    "covered_due_by_current_iteration": True,
                    "current_iteration_coverage": {
                        "covered": True,
                        "status": "covered_fresh_signal_still_waiting",
                        "recommended_next_recheck_after_kst": "2026-01-01T09:15:00+09:00",
                        "no_live_order_sent": True,
                    },
                    "effective_available_now": False,
                    "no_live_order_sent": True,
                }
            ],
            "effective_automation_now": [],
            "covered_automation_now": [
                {
                    "action_type": "monitor_fresh_signal",
                    "target_gate": "current_fresh_signal",
                    "command": "monitor",
                    "execute_after_utc": "2026-01-01T00:05:00+00:00",
                    "execute_after_kst": "2026-01-01T09:05:00+09:00",
                    "covered_by_current_iteration": True,
                    "current_iteration_coverage": {
                        "covered": True,
                        "status": "covered_fresh_signal_still_waiting",
                        "recommended_next_recheck_after_kst": "2026-01-01T09:15:00+09:00",
                        "no_live_order_sent": True,
                    },
                    "no_live_order_sent": True,
                }
            ],
            "startable_waits": [],
            "scheduled_waits": [],
            "no_live_order_sent": True,
        },
        operator_review_handoff_summary={
            "reviews": [
                {
                    "action_type": "review_conditional_overfit_holdout_proxy",
                    "target_gate": "conditional_overfit_operator_review",
                    "status": "ready_for_operator_review",
                    "active_operator_review_file_status": "draft_exists_operator_decision_required",
                    "operator_decision_packet": {
                        "status": "operator_decision_required",
                        "decision_command_safety": {"status": "PASS"},
                    },
                    "no_live_order_sent": True,
                }
            ],
            "no_live_order_sent": True,
        },
        launch_blocker_priority_summary={"status": "waiting_for_realtime_evidence"},
        runtime_progress={"remaining_hours": 0.0},
        microstructure_watch={"coverage_plan": {"remaining_calendar_days": 0}},
        execution_parity_status_summary={"missing_samples": 0, "no_live_order_sent": True},
    )

    assert summary["status"] == "operator_or_realtime_gates_remaining"
    assert summary["safe_automation_now_count"] == 1
    assert summary["safe_effective_automation_now_count"] == 0
    assert summary["safe_covered_automation_now_count"] == 1
    assert summary["safe_useful_automation_now_count"] == 0
    assert summary["safe_raw_useful_automation_now_count"] == 1
    assert summary["effective_queue_available"] is True
    assert summary["automation_now_usefulness_scope"] == (
        "effective_queue_excludes_current_iteration_covered_actions"
    )
    assert summary["automation_now_usefulness"] == []
    assert summary["raw_automation_now_usefulness"][0]["action_type"] == "monitor_fresh_signal"
    assert summary["raw_automation_now_usefulness"][0]["effective_next_monitor_after_kst"] == (
        "2026-01-01T09:15:00+09:00"
    )
    assert summary["raw_automation_now_usefulness"][0]["raw_next_monitor_after_kst"] == (
        "2026-01-01T09:05:00+09:00"
    )
    assert summary["primary_useful_automation_action"] is None
    assert summary["primary_raw_useful_automation_action"]["action_type"] == "monitor_fresh_signal"
    assert summary["primary_covered_automation_action"]["action_type"] == "monitor_fresh_signal"
    assert summary["actionability_partition"]["run_now_without_operator_count"] == 0
    assert summary["actionability_partition"]["manual_now_count"] == 1
    assert summary["actionability_partition"]["status"] == "manual_actions_available_waits_remain"
    assert summary["actionability_partition"]["primary_launch_wait_gate"] == "current_fresh_signal"
    assert summary["actionability_partition"]["primary_human_action_gate"] == (
        "conditional_overfit_operator_review"
    )
    assert summary["actionability_partition"]["no_safe_auto_command_now"] is True
    tracks = summary["actionability_tracks"]
    assert tracks == summary["actionability_partition"]["tracks"]
    assert tracks["status"] == "manual_available_realtime_wait_primary"
    assert tracks["primary_launch_wait_gate"] == "current_fresh_signal"
    assert tracks["primary_human_action_gate"] == "conditional_overfit_operator_review"
    assert tracks["safe_automatable_now"]["count"] == 0
    assert tracks["safe_automatable_now"]["covered_this_iteration_count"] == 1
    assert tracks["safe_automatable_now"]["no_safe_auto_command_now"] is True
    assert tracks["realtime_wait_required"]["next_monitor_kst"] == "2026-01-01T09:15:00+09:00"
    assert tracks["interpretation"] == (
        "manual_reviews_can_progress_in_parallel_but_launch_primary_wait_is_realtime"
    )
    assert summary["actionability_partition"]["dependency_aware_status"] in {
        "manual_actions_available_waits_and_dependencies_remain",
        "manual_actions_available_waits_remain",
    }
    assert "waits_open" in summary["actionability_partition"]
    assert "dependency_blockers_open" in summary["actionability_partition"]
    signal_wait = summary["actionability_partition"]["signal_waits"][0]
    assert signal_wait["next_monitor_kst"] == "2026-01-01T09:15:00+09:00"
    assert signal_wait["raw_next_monitor_kst"] == "2026-01-01T09:05:00+09:00"
    assert signal_wait["covered_next_recheck_after_kst"] == "2026-01-01T09:15:00+09:00"
    assert signal_wait["next_monitor_retimestampted_after_current_iteration"] is True
    assert "run_safe_monitoring_actions_without_live_orders" not in (
        summary["actionability_partition"]["recommended_parallel_next_moves"]
    )
    assert summary["dependency_lanes"]["realtime_signal_lane"]["monitor_useful_now"] is True
    assert summary["dependency_lanes"]["realtime_signal_lane"]["monitor_effective_useful_now"] is False
    assert summary["dependency_lanes"]["realtime_signal_lane"][
        "monitor_effective_next_after_kst"
    ] == "2026-01-01T09:15:00+09:00"
    assert summary["dependency_lanes"]["realtime_signal_lane"]["monitor_raw_next_after_kst"] == (
        "2026-01-01T09:05:00+09:00"
    )
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_remaining_work_closure_marks_current_quote_capture_as_noop_when_window_is_covered() -> None:
    summary = watch._remaining_work_closure_summary(
        unresolved_problem_register=[
            {
                "id": "microstructure_calendar_day_coverage",
                "status": "open_waiting_for_future_calendar_days",
                "severity": "evidence_depth_blocker",
                "non_substitutable": True,
                "next_action": "continue_daily_quote_window_collection",
                "no_live_order_sent": True,
            }
        ],
        operator_work_queue={
            "automation_now": [
                {
                    "action_type": "monitor_fresh_signal",
                    "target_gate": "current_fresh_signal",
                    "priority": 20,
                    "command": "monitor",
                    "no_live_order_sent": True,
                },
                {
                    "action_type": "capture_microstructure_quote_window_now",
                    "target_gate": "real_microstructure_execution_evidence",
                    "priority": 50,
                    "command": "capture",
                    "no_live_order_sent": True,
                },
            ],
            "startable_waits": [],
            "scheduled_waits": [],
            "primary_automation_action": {
                "action_type": "monitor_fresh_signal",
                "target_gate": "current_fresh_signal",
                "command": "monitor",
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
        operator_review_handoff_summary={"reviews": [], "no_live_order_sent": True},
        launch_blocker_priority_summary={"status": "waiting_for_realtime_evidence"},
        runtime_progress={"remaining_hours": 0.0},
        microstructure_watch={
            "coverage_plan": {
                "remaining_quote_samples": 0,
                "remaining_calendar_days": 25,
                "remaining_missing_utc_hour_count": 0,
                "current_utc_date_missing": False,
                "current_utc_hour_missing": False,
                "next_quote_coverage_kst_at": "2026-06-09T09:00:00+09:00",
            }
        },
        execution_parity_status_summary={"missing_samples": 0, "no_live_order_sent": True},
    )

    assert summary["safe_automation_now_count"] == 2
    assert summary["safe_useful_automation_now_count"] == 1
    assert summary["safe_noop_or_deferred_automation_now_count"] == 1
    noop = summary["primary_noop_or_deferred_automation_action"]
    assert noop["action_type"] == "capture_microstructure_quote_window_now"
    assert noop["useful_now"] is False
    assert noop["reason"] == "current_quote_window_already_covered_wait_for_next_utc_calendar_day"
    assert summary["primary_useful_automation_action"]["action_type"] == "monitor_fresh_signal"
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_first_fresh_signal_paper_apply_runbook_never_auto_applies() -> None:
    runbook = watch._first_fresh_signal_paper_apply_runbook(
        operator_handoff={
            "paper_apply_allowed_now": True,
            "execution_parity_will_credit_current_apply": True,
            "execution_parity_events_needed_after_current_apply": 19,
            "paper_apply_operator_packet": {
                "status": "ready_for_operator_review",
                "source_event_key": "event:add:long",
                "source_event_ts": "2026-01-01T00:00:00+00:00",
                "bridge_action": "add",
                "pre_apply_evidence_report": "reports/evidence.json",
                "pre_apply_evidence_report_status": {"status": "fresh", "fresh": True},
                "dry_run_command": "dry-run",
                "apply_command_allowed_now": "apply-now",
                "apply_command_when_gate_allows": "apply-later",
                "post_apply_execution_parity_review_command": "review-after",
                "verified_pre_apply_backup_required": True,
                "pre_apply_backup_plan": {
                    "required": True,
                    "verification_required_fields": ["pre_apply_backup.created == true"],
                    "no_live_order_sent": True,
                },
                "command_safety": {"status": "PASS", "blockers": [], "no_live_order_sent": True},
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
        paper_only_rehearsal={
            "status": "paper_apply_review_available",
            "system_ready": True,
            "armed": False,
            "remaining_gates": ["first_real_paper_lifecycle_row"],
        },
        fresh_signal_blocker_diagnostics={"status": "fresh_signal_available"},
        safe_next_action_plan={"primary_action": {"execute_after_kst": "2026-01-01T09:00:00+09:00"}},
        execution_parity_status_summary={"missing_samples": 20, "no_live_order_sent": True},
    )

    assert runbook["status"] == "paper_apply_operator_review_ready"
    assert runbook["fresh_signal"] is True
    assert runbook["paper_apply_allowed_now"] is True
    assert runbook["pre_apply_evidence_fresh"] is True
    assert runbook["command_safety_status"] == "PASS"
    assert runbook["apply_command_allowed_now"] == "apply-now"
    assert runbook["post_apply_execution_parity_review_command"] == "review-after"
    assert runbook["execution_parity_will_credit_current_apply"] is True
    assert runbook["auto_apply_allowed"] is False
    assert runbook["order_submission_allowed"] is False
    assert runbook["no_live_order_sent"] is True


def test_first_fresh_signal_runbook_uses_current_iteration_recheck_schedule() -> None:
    runbook = watch._first_fresh_signal_paper_apply_runbook(
        operator_handoff={"paper_apply_allowed_now": False, "no_live_order_sent": True},
        paper_only_rehearsal={
            "status": "armed_waiting_for_fresh_signal",
            "system_ready": True,
            "armed": True,
            "remaining_gates": ["current_fresh_signal", "first_real_paper_lifecycle_row"],
        },
        fresh_signal_blocker_diagnostics={
            "status": "waiting_for_fresh_signal",
            "next_monitor_after_kst": "2026-01-01T09:05:00+09:00",
        },
        safe_next_action_plan={
            "primary_action": {
                "action_type": "monitor_fresh_signal",
                "execute_after_utc": "2026-01-01T00:05:00+00:00",
                "execute_after_kst": "2026-01-01T09:05:00+09:00",
                "covered_by_current_iteration": True,
                "current_iteration_coverage": {
                    "covered": True,
                    "recommended_next_recheck_after_utc": "2026-01-01T00:15:00+00:00",
                    "recommended_next_recheck_after_kst": "2026-01-01T09:15:00+09:00",
                    "no_live_order_sent": True,
                },
                "no_live_order_sent": True,
            }
        },
        execution_parity_status_summary={"missing_samples": 20, "no_live_order_sent": True},
    )

    assert runbook["status"] == "armed_waiting_for_first_fresh_signal"
    assert runbook["next_monitor_after_kst"] == "2026-01-01T09:15:00+09:00"
    assert runbook["raw_next_monitor_after_kst"] == "2026-01-01T09:05:00+09:00"
    assert runbook["covered_next_recheck_after_kst"] == "2026-01-01T09:15:00+09:00"
    assert runbook["next_monitor_after_source"] == (
        "current_iteration_coverage.recommended_next_recheck_after"
    )
    assert runbook["next_monitor_retimestampted_after_current_iteration"] is True
    assert runbook["auto_apply_allowed"] is False
    assert runbook["order_submission_allowed"] is False
    assert runbook["no_live_order_sent"] is True


def test_operator_review_decision_aid_summarizes_accept_reject_context() -> None:
    aid = watch._operator_review_decision_aid(
        operator_review_handoff_summary={
            "reviews": [
                {
                    "action_type": "review_conditional_overfit_holdout_proxy",
                    "target_gate": "conditional_overfit_operator_review",
                    "review_kind": "conditional_overfit",
                    "status": "ready_for_operator_review",
                    "paper_only_scope": True,
                    "active_operator_review_file_summary": {
                        "draft_min_rationale_chars": 30,
                        "draft_min_evidence_anchors": 1,
                    },
                    "operator_decision_packet": {
                        "status": "operator_decision_required",
                        "candidate_recipe_id": "candidate_a",
                        "candidate_report": "reports/candidate.json",
                        "proxy_audit_report": "reports/proxy.json",
                        "source_promotion_gate_report": "reports/promotion.json",
                        "review_packet_summary": "proxy_review",
                        "review_packet_fingerprint": "f" * 64,
                        "active_operator_review_report": "reports/review.json",
                        "operator_required_fields_remaining": ["status", "reviewer", "reviewed_at", "rationale"],
                        "accepted_status_values": ["accepted"],
                        "decision_dry_run_command_template": "complete --dry-run",
                        "decision_fill_command_template": "complete --write-summary",
                        "validation_command": "validate",
                        "decision_command_safety": {"status": "PASS", "blockers": []},
                        "no_live_order_sent": True,
                    },
                    "no_live_order_sent": True,
                }
            ],
            "no_live_order_sent": True,
        },
        remaining_work_closure_summary={
            "dependency_lanes": {
                "critical_path": [
                    "current_fresh_signal",
                    "operator_review_decisions",
                    "first_real_paper_lifecycle_row",
                    "execution_parity_samples",
                ],
                "parallel_calendar_path": [
                    "microstructure_calendar_day_coverage",
                    "shadow_runtime_24h_observed",
                ],
                "realtime_signal_lane": {
                    "status": "waiting_for_realtime_fresh_signal",
                    "monitor_action_type": "monitor_fresh_signal",
                    "monitor_execute_after_kst": "2026-01-01T09:05:00+09:00",
                    "non_substitutable": True,
                    "no_live_order_sent": True,
                },
                "operator_input_lane": {
                    "status": "operator_inputs_ready_for_manual_decision",
                    "no_live_order_sent": True,
                },
                "first_paper_row_lane": {
                    "status": "blocked_until_fresh_signal_and_operator_review",
                    "depends_on": ["current_fresh_signal", "operator_review_decisions"],
                    "no_live_order_sent": True,
                },
                "execution_parity_lane": {
                    "status": "waiting_for_real_reviewed_paper_lifecycle_rows",
                    "depends_on": ["first_real_paper_lifecycle_row"],
                    "no_live_order_sent": True,
                },
                "calendar_coverage_lane": {
                    "status": "waiting_for_future_quote_calendar_days",
                    "no_live_order_sent": True,
                },
                "runtime_observation_lane": {
                    "status": "collecting_shadow_runtime",
                    "no_live_order_sent": True,
                },
                "no_live_order_sent": True,
            },
            "operator_review_problem_ids": ["conditional_overfit_operator_review"],
            "no_live_order_sent": True,
        },
    )

    assert aid["status"] == "operator_decisions_ready"
    assert aid["decision_required_count"] == 1
    assert aid["primary_decision"]["candidate_recipe_id"] == "candidate_a"
    assert aid["primary_decision"]["decision_command_safety_status"] == "PASS"
    assert aid["primary_decision"]["paper_only_scope"] is True
    assert aid["primary_decision"]["accept_consequence"] == (
        "allows_paper_only_candidate_activation_but_tiny_canary_or_live_still_requires_real_shadow_and_execution_parity"
    )
    assert aid["primary_decision"]["reject_consequence"] == "keeps_this_candidate_or_route_blocked_by_validation"
    assert aid["auto_decision_allowed"] is False
    assert aid["order_submission_allowed"] is False
    assert aid["no_live_order_sent"] is True


def test_operator_review_resolution_plan_keeps_accept_reject_manual() -> None:
    plan = watch._operator_review_resolution_plan(
        operator_review_decision_aid={
            "status": "operator_decisions_ready",
            "no_live_order_sent": True,
            "waiting_reviews": [{"action_type": "paper_bridge_wait_for_fresh_signal", "no_live_order_sent": True}],
            "decisions": [
                {
                    "action_type": "review_conditional_overfit_holdout_proxy",
                    "target_gate": "conditional_overfit_operator_review",
                    "review_kind": "conditional_overfit",
                    "candidate_recipe_id": "candidate_a",
                    "active_operator_review_report": "reports/review_a.json",
                    "required_fields_remaining": ["status", "reviewer", "reviewed_at", "rationale"],
                    "decision_command_safety_status": "PASS",
                    "decision_command_safety_blockers": [],
                    "decision_dry_run_command_template": "complete-a --dry-run",
                    "decision_fill_command_template": "complete-a --write-summary",
                    "validation_command": "validate-a",
                    "accept_consequence": "paper_candidate_activation_only",
                    "reject_consequence": "candidate_remains_blocked",
                    "paper_only_scope": True,
                    "no_live_order_sent": True,
                },
                {
                    "action_type": "review_defensive_candidate_lineage_template",
                    "target_gate": "defensive_lineage_review",
                    "review_kind": "defensive_lineage",
                    "candidate_recipe_id": "candidate_b",
                    "active_operator_review_report": "reports/review_b.json",
                    "required_fields_remaining": ["status", "reviewer", "reviewed_at", "rationale"],
                    "decision_command_safety_status": "PASS",
                    "decision_command_safety_blockers": [],
                    "decision_dry_run_command_template": "complete-b --dry-run",
                    "decision_fill_command_template": "complete-b --write-summary",
                    "validation_command": "validate-b",
                    "accept_consequence": "defensive_route_validation_only",
                    "reject_consequence": "route_remains_blocked",
                    "paper_only_scope": False,
                    "no_live_order_sent": True,
                },
            ],
        },
        next_material_progress_plan={
            "immediate_operator_events": [{"event_type": "operator_review_decisions"}],
            "no_live_order_sent": True,
        },
    )

    assert plan["status"] == "operator_review_manual_resolution_ready"
    assert plan["decision_count"] == 2
    assert plan["waiting_review_count"] == 1
    assert plan["immediate_operator_event_count"] == 1
    assert plan["all_decision_commands_safe"] is True
    assert plan["primary_step"]["candidate_recipe_id"] == "candidate_a"
    assert plan["primary_step"]["safe_default_if_uncertain"] == "reject_or_hold_blocked"
    assert plan["primary_step"]["can_auto_decide"] is False
    assert plan["primary_step"]["acceptance_does_not_enable_live"] is True
    assert plan["primary_step"]["acceptance_does_not_enable_tiny_canary"] is True
    assert plan["resolution_steps"][1]["acceptance_does_not_enable_tiny_canary"] is False
    assert plan["safe_default_policy"] == "reject_or_hold_blocked_if_evidence_is_not_clear_enough"
    assert plan["auto_decision_allowed"] is False
    assert plan["auto_accept_allowed"] is False
    assert plan["auto_reject_allowed"] is False
    assert plan["order_submission_allowed"] is False
    assert plan["no_live_order_sent"] is True


def test_operator_review_resolution_plan_includes_evidence_snapshot_without_auto_decision(tmp_path: Path) -> None:
    candidate_report = tmp_path / "candidate.json"
    candidate_report.write_text(
        json.dumps(
            {
                "created_at": "2026-01-01T00:00:00+00:00",
                "aggregate": {
                    "fold_count": 4,
                    "positive_fold_count": 4,
                    "compounded_oos_return_pct": 321.5,
                    "avg_oos_return_pct": 42.0,
                    "min_oos_return_pct": 8.0,
                    "max_fold_drawdown_pct": 9.5,
                    "avg_oos_cost_drag_pct": 1.2,
                    "total_trade_like_events": 44,
                    "test_add_by_side_share": {"long": 0.45, "short": 0.55},
                    "test_add_by_role_share": {"base": 0.7, "probe": 0.3},
                    "test_add_distribution_diagnostics": {
                        "dominant_add_side": "short",
                        "dominant_add_side_share": 0.55,
                        "dominant_add_role": "base",
                        "dominant_add_role_share": 0.7,
                    },
                    "drawdown_recovery_diagnostics": {
                        "high_drawdown_count": 1,
                        "high_drawdown_recovered_count": 0,
                    },
                },
                "folds": [{}, {}, {}, {}],
            }
        ),
        encoding="utf-8",
    )
    proxy_report = tmp_path / "proxy.json"
    proxy_report.write_text(
        json.dumps(
            {
                "status": "historical_proxy_pass_real_shadow_required",
                "generated_at": "2026-01-01T00:01:00+00:00",
                "candidate_decision": "promotion_candidate_after_formal_wfo",
                "checks": [
                    {"name": "aggregate_return_improved", "passed": True},
                    {"name": "tail_holdout_proxy_not_worse", "passed": False},
                ],
                "aggregate_delta": {"return_delta_pct": 12.5},
                "fold_delta_summary": {"changed_fold_count": 2},
                "tail_holdout_proxy": {"passed": False, "worse_folds": [4]},
                "blockers": [],
                "warnings": ["historical_proxy_does_not_replace_real_shadow_holdout"],
                "limitations": ["does_not_create_true_future_unseen_market_data"],
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )
    promotion_report = tmp_path / "promotion.json"
    promotion_report.write_text(
        json.dumps(
            {
                "status": "meta_router_promotion_gate_complete",
                "generated_at": "2026-01-01T00:02:00+00:00",
                "promotion_decision": "blocked_pending_overfit_holdout_review",
                "performance_upgrade_ready": True,
                "performance_delta_status": "performance_metric_delta_detected",
                "risk_adjusted_compression_ready": False,
                "risk_compression_ready": False,
                "risk_compression_detected": False,
                "readiness_candidate_alignment": {"passed": True, "blockers": []},
                "overfit_blockers": ["conditional_winner_refill_overlay_requires_shadow_holdout_review"],
                "performance_upgrade_blockers": [],
                "risk_compression_blockers": [],
                "decision_reasons": ["conditional_winner_refill_overlay_requires_shadow_holdout_review"],
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    aid = watch._operator_review_decision_aid(
        operator_review_handoff_summary={
            "reviews": [
                {
                    "action_type": "review_conditional_overfit_holdout_proxy",
                    "target_gate": "conditional_overfit_operator_review",
                    "review_kind": "conditional_overfit",
                    "status": "ready_for_operator_review",
                    "paper_only_scope": True,
                    "operator_decision_packet": {
                        "status": "operator_decision_required",
                        "candidate_recipe_id": "candidate_a",
                        "candidate_report": str(candidate_report),
                        "proxy_audit_report": str(proxy_report),
                        "source_promotion_gate_report": str(promotion_report),
                        "active_operator_review_report": str(tmp_path / "review.json"),
                        "operator_required_fields_remaining": ["status", "reviewer", "reviewed_at", "rationale"],
                        "decision_dry_run_command_template": (
                            "complete --decision <accept_or_reject> "
                            "--reviewer <operator_name_or_initials> "
                            "--rationale <operator_rationale> --dry-run"
                        ),
                        "decision_fill_command_template": (
                            "complete --decision <accept_or_reject> "
                            "--reviewer <operator_name_or_initials> "
                            "--rationale <operator_rationale> --write-summary"
                        ),
                        "validation_command": "validate-review",
                        "decision_command_safety": {"status": "PASS", "blockers": []},
                        "no_live_order_sent": True,
                    },
                    "no_live_order_sent": True,
                }
            ],
            "no_live_order_sent": True,
        },
        remaining_work_closure_summary={"no_live_order_sent": True},
    )
    plan = watch._operator_review_resolution_plan(
        operator_review_decision_aid=aid,
        next_material_progress_plan={
            "immediate_operator_events": [{"event_type": "operator_review_decisions"}],
            "no_live_order_sent": True,
        },
    )

    snapshot = plan["primary_step"]["evidence_snapshot"]
    assert snapshot["status"] == "evidence_snapshot_ready"
    assert snapshot["candidate"]["fold_count"] == 4
    assert snapshot["candidate"]["compounded_oos_return_pct"] == 321.5
    assert len(snapshot["candidate"]["payload_fingerprint"]) == 64
    assert snapshot["proxy_audit"]["failed_check_count"] == 1
    assert len(snapshot["proxy_audit"]["payload_fingerprint"]) == 64
    assert snapshot["proxy_audit"]["warnings"] == ["historical_proxy_does_not_replace_real_shadow_holdout"]
    assert snapshot["promotion_gate"]["promotion_decision"] == "blocked_pending_overfit_holdout_review"
    assert len(snapshot["promotion_gate"]["payload_fingerprint"]) == 64
    assert snapshot["promotion_gate"]["overfit_blockers"] == [
        "conditional_winner_refill_overlay_requires_shadow_holdout_review"
    ]
    assert snapshot["fingerprint_algorithm"] == "sha256_canonical_json"
    assert len(snapshot["evidence_snapshot_fingerprint"]) == 64
    assert snapshot["review_guidance"]["status"] == "guidance_ready"
    assert "candidate_all_walk_forward_folds_positive" in snapshot["review_guidance"]["supporting_evidence"]
    assert "promotion_gate_still_blocked" in snapshot["review_guidance"]["rationale_must_address"]
    assert "proxy_audit_has_failed_checks" in snapshot["review_guidance"]["rationale_must_address"]
    assert "candidate.compounded_oos_return_pct" in snapshot["review_guidance"]["evidence_anchor_candidates"]
    assert snapshot["review_guidance"]["auto_accept_allowed"] is False
    assert snapshot["review_guidance"]["order_submission_allowed"] is False
    contract = plan["primary_step"]["manual_decision_contract"]
    assert contract["status"] == "manual_decision_contract_blocked"
    assert contract["accept_blockers_before_operator_write"] == ["operator_required_fields_still_empty"]
    assert "promotion_gate_still_blocked" in contract["reject_or_hold_triggers"]
    assert "candidate.compounded_oos_return_pct" in contract["required_evidence_anchor_candidates"]
    assert contract["fingerprint_algorithm"] == "sha256_canonical_json"
    assert contract["evidence_snapshot_fingerprint"] == snapshot["evidence_snapshot_fingerprint"]
    assert "rationale_references_evidence_snapshot_fingerprint_or_source_report_paths" in contract["accept_requires"]
    assert contract["safe_default_if_any_contract_item_fails"] == "reject_or_hold_blocked"
    assert contract["auto_accept_allowed"] is False
    assert contract["order_submission_allowed"] is False
    scaffold = plan["primary_step"]["rationale_scaffold"]
    assert scaffold["status"] == "rationale_scaffold_ready"
    assert scaffold["evidence_snapshot_fingerprint"] == snapshot["evidence_snapshot_fingerprint"]
    assert scaffold["minimum_anchor_set"] == [
        "candidate.compounded_oos_return_pct",
        "candidate.fold_count",
        "candidate.positive_fold_count",
    ]
    assert scaffold["operator_write_still_blocked_by_contract"] is True
    assert scaffold["contract_accept_blockers_before_write"] == ["operator_required_fields_still_empty"]
    assert scaffold["accept_rationale_outline"][0]["must_include"] == "explicit_accept"
    assert any(item["concern"] == "promotion_gate_still_blocked" for item in scaffold["concern_response_prompts"])
    assert scaffold["reject_or_hold_rationale_outline"][0]["must_include"] == "explicit_reject_or_hold"
    assert scaffold["auto_decision_allowed"] is False
    assert scaffold["order_submission_allowed"] is False
    command_plan = plan["primary_step"]["decision_command_plan"]
    assert command_plan["status"] == "decision_command_plan_ready"
    assert command_plan["blockers"] == []
    assert command_plan["dry_run_before_write_required"] is True
    assert command_plan["validation_after_write_required"] is True
    accept_option = next(item for item in command_plan["decision_options"] if item["decision"] == "accept")
    reject_option = next(item for item in command_plan["decision_options"] if item["decision"] == "reject")
    assert "--decision accept" in accept_option["dry_run_command"]
    assert "--dry-run" in accept_option["dry_run_command"]
    assert "--write-summary" in accept_option["write_command"]
    assert "--decision reject" in reject_option["dry_run_command"]
    assert reject_option["validation_command"] == "validate-review"
    assert command_plan["auto_execute_allowed"] is False
    assert command_plan["order_submission_allowed"] is False
    readiness_matrix = plan["readiness_matrix"]
    assert readiness_matrix["status"] == "operator_review_matrix_ready_for_manual_dry_run_inputs"
    assert readiness_matrix["row_count"] == 1
    assert readiness_matrix["dry_run_ready_count"] == 1
    assert readiness_matrix["contract_blocked_count"] == 1
    assert readiness_matrix["repair_required_count"] == 0
    assert readiness_matrix["primary_row"]["ready_for_operator_dry_run_template"] is True
    assert readiness_matrix["primary_row"]["next_manual_action"] == (
        "choose_accept_or_reject_replace_placeholders_then_run_dry_run"
    )
    assert readiness_matrix["primary_row"]["contract_accept_blockers_before_write"] == [
        "operator_required_fields_still_empty"
    ]
    prompt_card = readiness_matrix["primary_row"]["operator_prompt_card"]
    assert prompt_card["status"] == "operator_prompt_card_ready"
    assert prompt_card["decision_rule"] == (
        "accept_only_if_all_accept_requires_are_met_and_every_must_address_concern_is_answered"
    )
    assert prompt_card["safe_default_if_uncertain"] == "reject_or_hold_blocked"
    assert prompt_card["rationale_quality_gate"]["minimum_recommended_anchor_count"] == 3
    assert prompt_card["rationale_quality_gate"]["minimum_anchor_set"] == [
        "candidate.compounded_oos_return_pct",
        "candidate.fold_count",
        "candidate.positive_fold_count",
    ]
    assert "promotion_gate_still_blocked" in prompt_card["rationale_must_address"]
    assert prompt_card["acceptance_does_not_enable_live"] is True
    assert readiness_matrix["auto_decision_allowed"] is False
    assert readiness_matrix["order_submission_allowed"] is False
    manual_batch = plan["manual_batch_handoff"]
    assert manual_batch["status"] == "operator_review_batch_waiting_for_operator_inputs"
    assert manual_batch["row_count"] == 1
    assert manual_batch["dry_run_ready_count"] == 1
    assert manual_batch["contract_blocked_count"] == 1
    assert manual_batch["repair_required_count"] == 0
    assert manual_batch["blocked_by_operator_inputs_only"] is True
    assert manual_batch["requires_sequential_validation"] is True
    assert manual_batch["rerun_watch_after_each_written_decision"] is True
    assert len(manual_batch["batch_fingerprint"]) == 64
    assert manual_batch["primary_next_step"]["step"] == 1
    assert manual_batch["primary_next_step"]["review_kind"] == "conditional_overfit"
    assert manual_batch["primary_next_step"]["validation_command"] == "validate-review"
    assert manual_batch["primary_next_step"]["next_manual_action"] == (
        "choose_accept_or_reject_replace_placeholders_then_run_dry_run"
    )
    assert manual_batch["primary_next_step"]["contract_accept_blockers_before_write"] == [
        "operator_required_fields_still_empty"
    ]
    assert manual_batch["primary_next_step"]["operator_prompt_card"]["status"] == (
        "operator_prompt_card_ready"
    )
    assert manual_batch["primary_next_step"]["operator_prompt_card"]["rationale_quality_gate"][
        "must_address_count"
    ] >= 1
    assert manual_batch["primary_next_step"]["after_write_required_actions"] == [
        "run_validation_command_for_this_step",
        "rerun_launch_shadow_watch_before_next_review_step",
        "confirm_gate_status_changed_or_remains_blocked_with_reason",
    ]
    assert [item["decision"] for item in manual_batch["primary_next_step"]["decision_options"]] == [
        "accept",
        "reject",
    ]
    assert manual_batch["auto_execute_allowed"] is False
    assert manual_batch["auto_decision_allowed"] is False
    assert manual_batch["order_submission_allowed"] is False
    assert manual_batch["no_live_order_sent"] is True
    assert snapshot["auto_decision_allowed"] is False
    assert snapshot["order_submission_allowed"] is False
    assert snapshot["no_live_order_sent"] is True
    assert plan["auto_decision_allowed"] is False
    assert plan["order_submission_allowed"] is False
    assert plan["no_live_order_sent"] is True


def test_defensive_lineage_review_uses_lineage_draft_as_evidence_without_candidate_proxy(tmp_path: Path) -> None:
    promotion_report = tmp_path / "promotion.json"
    promotion_report.write_text(
        json.dumps(
            {
                "status": "meta_router_promotion_gate_complete",
                "generated_at": "2026-01-01T00:02:00+00:00",
                "promotion_decision": "blocked_pending_overfit_holdout_review",
                "performance_upgrade_ready": True,
                "readiness_candidate_alignment": {"passed": True, "blockers": []},
                "overfit_blockers": ["operator_lineage_review_required"],
                "decision_reasons": ["operator_lineage_review_required"],
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )
    lineage_report = tmp_path / "lineage.json"
    lineage_report.write_text(
        json.dumps(
            {
                "status": "operator_lineage_review_accepted_or_rejected",
                "candidate_recipe_id": "defensive_route_a",
                "reviewed_folds": [11],
                "review_packet_summary": "lineage_watch_is_limited_to_intentional_size_overlay_folds",
                "review_packet_fingerprint": "a" * 64,
                "source_promotion_gate_report": str(promotion_report),
                "source_promotion_gate_generated_at": "2026-01-01T00:02:00+00:00",
                "source_template_report": "template.json",
                "acceptance_contract": {
                    "accepted_status_values": ["operator_lineage_review_accepted"],
                    "candidate_recipe_id_must_match": "defensive_route_a",
                },
                "validation_contract": {"purpose": "validate_operator_lineage_review"},
                "order_submission_allowed": False,
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )

    aid = watch._operator_review_decision_aid(
        operator_review_handoff_summary={
            "reviews": [
                {
                    "action_type": "review_defensive_candidate_lineage_template",
                    "target_gate": "defensive_lineage_review",
                    "review_kind": "defensive_lineage",
                    "status": "ready_for_operator_review",
                    "paper_only_scope": False,
                    "operator_decision_packet": {
                        "status": "operator_decision_required",
                        "candidate_recipe_id": "defensive_route_a",
                        "candidate_report": None,
                        "proxy_audit_report": None,
                        "source_promotion_gate_report": str(promotion_report),
                        "active_operator_review_report": str(lineage_report),
                        "operator_required_fields_remaining": ["status", "reviewer", "reviewed_at", "rationale"],
                        "decision_dry_run_command_template": (
                            "complete --decision <accept_or_reject> "
                            "--reviewer <operator_name_or_initials> "
                            "--rationale <operator_rationale> --dry-run"
                        ),
                        "decision_fill_command_template": (
                            "complete --decision <accept_or_reject> "
                            "--reviewer <operator_name_or_initials> "
                            "--rationale <operator_rationale> --write-summary"
                        ),
                        "validation_command": "validate-lineage",
                        "decision_command_safety": {"status": "PASS", "blockers": []},
                        "no_live_order_sent": True,
                    },
                    "no_live_order_sent": True,
                }
            ],
            "no_live_order_sent": True,
        },
        remaining_work_closure_summary={"no_live_order_sent": True},
    )
    plan = watch._operator_review_resolution_plan(
        operator_review_decision_aid=aid,
        next_material_progress_plan={"no_live_order_sent": True},
    )

    snapshot = plan["primary_step"]["evidence_snapshot"]
    assert snapshot["status"] == "evidence_snapshot_ready"
    assert snapshot["candidate"]["status"] == "not_applicable_for_defensive_lineage_review"
    assert snapshot["proxy_audit"]["status"] == "not_applicable_for_defensive_lineage_review"
    assert snapshot["lineage_review"]["review_packet_fingerprint"] == "a" * 64
    assert "lineage_review_packet_fingerprint_available" in snapshot["review_guidance"]["supporting_evidence"]
    assert "lineage_review_still_pending_operator_decision" in snapshot["review_guidance"]["rationale_must_address"]
    assert snapshot["review_guidance"]["missing_anchor_sources"] == []
    assert plan["primary_step"]["rationale_scaffold"]["status"] == "rationale_scaffold_ready"
    assert plan["primary_step"]["decision_command_plan"]["status"] == "decision_command_plan_ready"
    assert plan["readiness_matrix"]["status"] == "operator_review_matrix_ready_for_manual_dry_run_inputs"
    assert plan["readiness_matrix"]["repair_required_count"] == 0
    assert plan["manual_batch_handoff"]["status"] == "operator_review_batch_waiting_for_operator_inputs"
    assert plan["manual_batch_handoff"]["dry_run_ready_count"] == 1
    assert plan["manual_batch_handoff"]["blocked_by_operator_inputs_only"] is True
    assert plan["manual_batch_handoff"]["primary_next_step"]["review_kind"] == "defensive_lineage"
    assert plan["manual_batch_handoff"]["primary_next_step"]["validation_command"] == "validate-lineage"
    assert plan["manual_batch_handoff"]["auto_decision_allowed"] is False
    assert plan["manual_batch_handoff"]["order_submission_allowed"] is False
    assert plan["no_live_order_sent"] is True


def test_daily_quote_checkpoint_waits_for_future_calendar_day_without_backfill() -> None:
    checkpoint = watch._daily_quote_checkpoint_summary(
        microstructure_watch={
            "eligible_row_count": 378,
            "required_quote_samples": 300,
            "no_live_order_sent": True,
            "coverage_plan": {
                "remaining_quote_samples": 0,
                "remaining_calendar_days": 25,
                "calendar_day_count": 5,
                "min_calendar_days": 30,
                "covered_calendar_days": ["2026-06-08"],
                "current_utc_date": "2026-06-08",
                "current_utc_date_missing": False,
                "next_quote_coverage_kind": "next_utc_calendar_day",
                "next_quote_coverage_at": "2026-06-09T00:00:00+00:00",
                "next_quote_coverage_kst_at": "2026-06-09T09:00:00+09:00",
                "earliest_calendar_completion_kst": "2026-07-03T09:00:00+09:00",
                "calendar_completion_policy": "one_new_utc_calendar_date_per_day_for_actual_launch_gate",
            },
        },
        safe_next_action_plan={
            "actions": [
                {
                    "action_type": "wait_for_next_microstructure_quote_window",
                    "command": "watch --sleep-until-next-quote-coverage-window",
                }
            ],
            "coordination_plan": {
                "status": "earlier_signal_or_add_monitor_before_quote_window",
                "next_signal_or_add_monitor_kst": "2026-06-09T08:55:00+09:00",
                "next_signal_or_add_monitor_window_status": "due_or_overdue",
                "next_signal_or_add_monitor_overdue_minutes": 5.0,
                "next_quote_window_status": "scheduled_future",
                "next_quote_window_overdue_minutes": 0.0,
                "quote_window_deferred_by_earlier_monitor": True,
                "do_not_skip_quote_window_for_signal_monitor": True,
            },
        },
        remaining_work_closure_summary={
            "not_auto_completable_reasons": ["quote_calendar_coverage_requires_future_utc_dates"],
        },
    )

    assert checkpoint["status"] == "waiting_for_next_utc_calendar_day"
    assert checkpoint["next_action"] == "wait_for_next_quote_calendar_checkpoint"
    assert checkpoint["remaining_calendar_days"] == 25
    assert checkpoint["next_quote_window_utc"] == "2026-06-09T00:00:00+00:00"
    assert checkpoint["next_quote_window_kst"] == "2026-06-09T09:00:00+09:00"
    assert checkpoint["next_quote_coverage_kst_at"] == "2026-06-09T09:00:00+09:00"
    assert checkpoint["quote_window_coordination_status"] == (
        "earlier_signal_or_add_monitor_before_quote_window"
    )
    assert checkpoint["next_signal_or_add_monitor_kst"] == "2026-06-09T08:55:00+09:00"
    assert checkpoint["raw_next_signal_or_add_monitor_kst"] == "2026-06-09T08:55:00+09:00"
    assert checkpoint["next_signal_or_add_monitor_window_status"] == "due_or_overdue"
    assert checkpoint["next_signal_or_add_monitor_overdue_minutes"] == 5.0
    assert checkpoint["next_signal_or_add_monitor_raw_window_status"] == "due_or_overdue"
    assert checkpoint["next_signal_or_add_monitor_raw_overdue_minutes"] == 5.0
    assert checkpoint["next_quote_window_status"] == "scheduled_future"
    assert checkpoint["next_quote_window_overdue_minutes"] == 0.0
    assert checkpoint["wait_command"] == "watch --sleep-until-next-quote-coverage-window"
    assert checkpoint["quote_window_deferred_by_signal_monitor"] is True
    assert checkpoint["do_not_skip_quote_window_for_signal_monitor"] is True
    assert checkpoint["not_auto_completable_until_future_date"] is True
    assert checkpoint["backfill_allowed_for_launch_gate"] is False
    assert checkpoint["order_submission_allowed"] is False
    assert checkpoint["no_live_order_sent"] is True


def test_next_material_progress_plan_orders_auto_operator_and_future_events_without_live_orders() -> None:
    plan = watch._next_material_progress_plan(
        generated_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        runtime_progress={
            "status": "collecting_runtime",
            "observed_hours": 5.0,
            "target_hours": 24.0,
            "remaining_hours": 19.0,
            "progress_pct": 20.8333,
        },
        latest_signal_wait_plan={
            "status": "blocked_waiting_for_fresh_signal",
            "fresh_signal": False,
            "next_monitor_after_utc": "2026-01-01T00:05:00+00:00",
            "next_monitor_after_kst": "2026-01-01T09:05:00+09:00",
            "recommended_monitor_interval_minutes": 5.0,
            "monitor_interval_capped_by_signal_freshness": True,
            "command": "monitor-signal",
            "recommended_action": "monitor_without_forcing_entry",
        },
        daily_quote_checkpoint_summary={
            "status": "waiting_for_next_utc_calendar_day",
            "next_action": "wait_for_next_quote_calendar_checkpoint",
            "next_quote_coverage_utc_at": "2026-01-02T00:00:00+00:00",
            "next_quote_coverage_kst_at": "2026-01-02T09:00:00+09:00",
            "wait_command": "wait-quote",
            "remaining_calendar_days": 25,
            "calendar_day_count": 5,
            "min_calendar_days": 30,
            "backfill_allowed_for_launch_gate": False,
            "no_live_order_sent": True,
        },
        first_fresh_signal_paper_apply_runbook={
            "status": "armed_waiting_for_first_fresh_signal",
            "fresh_signal": False,
            "paper_apply_allowed_now": False,
            "next_operator_step": "monitor_fresh_signal_without_forcing_entry",
            "apply_command_when_gate_allows": "apply-paper-after-fresh-signal",
            "auto_apply_allowed": False,
            "remaining_gates": ["current_fresh_signal", "first_real_paper_lifecycle_row"],
            "no_live_order_sent": True,
        },
        operator_review_decision_aid={
            "status": "operator_decisions_ready",
            "decision_required_count": 2,
            "ready_review_count": 2,
            "blocked_review_count": 0,
            "waiting_review_count": 1,
            "primary_decision": {"decision_dry_run_command_template": "review --dry-run"},
            "no_live_order_sent": True,
        },
        remaining_work_closure_summary={
            "primary_useful_automation_action": {"command": "continue-watch"},
            "actionability_partition": {
                "run_now_without_operator": [
                    {
                        "action_type": "monitor_fresh_signal",
                        "target_gate": "current_fresh_signal",
                        "command": "canonical-monitor-signal",
                        "no_live_order_sent": True,
                    },
                    {
                        "action_type": "continue_no_live_shadow_watch",
                        "target_gate": "shadow_runtime_24h_observed",
                        "command": "canonical-shadow-watch",
                        "no_live_order_sent": True,
                    }
                ],
                "no_live_order_sent": True,
            },
            "not_auto_completable_reasons": ["fresh_signal_requires_realtime_market_event"],
            "no_live_order_sent": True,
        },
        execution_parity_status_summary={
            "status": "execution_parity_journal_collecting",
            "eligible_journal_rows": 0,
            "required_samples": 20,
            "missing_samples": 20,
            "estimated_future_paper_apply_events_needed": 20,
            "estimated_completion_utc": "2026-01-10T00:00:00+00:00",
            "next_step": "collect_real_paper_lifecycle_rows",
            "non_substitutable": True,
            "no_live_order_sent": True,
        },
    )

    assert plan["status"] == "operator_review_ready_realtime_evidence_waiting"
    assert plan["immediate_operator_count"] == 1
    assert plan["immediate_auto_count"] == 0
    assert plan["future_event_count"] == 4
    assert plan["unscheduled_wait_count"] == 1
    assert plan["primary_next_event"]["event_type"] == "operator_review_decisions"
    assert plan["primary_next_event"]["requires_operator_review"] is True
    assert plan["primary_next_event"]["can_auto_run"] is False
    fresh_monitor = next(item for item in plan["future_events"] if item["event_type"] == "fresh_signal_monitor")
    assert fresh_monitor["command"] == "canonical-monitor-signal"
    assert fresh_monitor["details"]["command_source"] == (
        "remaining_work_closure_summary.actionability_partition.run_now_without_operator"
    )
    assert fresh_monitor["details"]["raw_signal_wait_command"] == "monitor-signal"
    assert fresh_monitor["details"]["source_command_mismatch_resolved"] is True
    shadow_runtime = next(
        item for item in plan["future_events"] if item["event_type"] == "shadow_runtime_observation"
    )
    assert shadow_runtime["command"] == "canonical-shadow-watch"
    assert shadow_runtime["details"]["command_source"] == (
        "remaining_work_closure_summary.actionability_partition.run_now_without_operator"
    )
    paper_apply = next(item for item in plan["events"] if item["event_type"] == "first_fresh_signal_paper_apply")
    assert paper_apply["requires_operator_review"] is True
    assert paper_apply["can_auto_run"] is False
    assert paper_apply["details"]["auto_apply_allowed"] is False
    assert plan["order_submission_allowed"] is False
    assert plan["no_live_order_sent"] is True


def test_next_material_progress_uses_raw_covered_signal_command_without_immediate_auto() -> None:
    plan = watch._next_material_progress_plan(
        generated_at=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
        runtime_progress={"remaining_hours": 1.0, "no_live_order_sent": True},
        latest_signal_wait_plan={
            "status": "blocked_waiting_for_fresh_signal",
            "fresh_signal": False,
            "next_monitor_after_utc": "2026-01-01T00:05:00+00:00",
            "command": "old-monitor-report-dir",
            "recommended_action": "monitor_without_forcing_entry",
            "no_live_order_sent": True,
        },
        daily_quote_checkpoint_summary={},
        first_fresh_signal_paper_apply_runbook={
            "status": "armed_waiting_for_first_fresh_signal",
            "paper_apply_allowed_now": False,
            "apply_command_when_gate_allows": "apply-paper-after-fresh-signal",
            "auto_apply_allowed": False,
            "no_live_order_sent": True,
        },
        operator_review_decision_aid={
            "status": "operator_decisions_ready",
            "decision_required_count": 1,
            "primary_decision": {"decision_dry_run_command_template": "review --dry-run"},
            "no_live_order_sent": True,
        },
        remaining_work_closure_summary={
            "primary_useful_automation_action": None,
            "primary_raw_useful_automation_action": {
                "action_type": "monitor_fresh_signal",
                "target_gate": "current_fresh_signal",
                "execute_after_utc": "2026-01-01T00:05:00+00:00",
                "execute_after_kst": "2026-01-01T09:05:00+09:00",
                "current_iteration_coverage": {
                    "covered": True,
                    "recommended_next_recheck_after_utc": "2026-01-01T00:15:00+00:00",
                    "recommended_next_recheck_after_kst": "2026-01-01T09:15:00+09:00",
                    "no_live_order_sent": True,
                },
                "command": "current-safe-next-monitor-report-dir",
                "no_live_order_sent": True,
            },
            "raw_automation_now_usefulness": [
                {
                    "action_type": "monitor_fresh_signal",
                    "target_gate": "current_fresh_signal",
                    "command": "current-safe-next-monitor-report-dir",
                    "useful_now": True,
                    "no_live_order_sent": True,
                },
                {
                    "action_type": "continue_no_live_shadow_watch",
                    "target_gate": "shadow_runtime_24h_observed",
                    "command": "current-safe-next-shadow-watch",
                    "useful_now": True,
                    "no_live_order_sent": True,
                },
            ],
            "actionability_partition": {
                "run_now_without_operator": [],
                "manual_now": [{"action_type": "review_conditional_overfit_holdout_proxy"}],
                "no_live_order_sent": True,
            },
            "not_auto_completable_reasons": ["fresh_signal_requires_realtime_market_event"],
            "no_live_order_sent": True,
        },
        execution_parity_status_summary={
            "status": "execution_parity_sample_floor_satisfied",
            "missing_samples": 0,
            "no_live_order_sent": True,
        },
    )

    fresh_monitor = next(item for item in plan["events"] if item["event_type"] == "fresh_signal_monitor")
    assert plan["primary_next_event"]["event_type"] == "operator_review_decisions"
    assert plan["immediate_auto_count"] == 0
    assert plan["immediate_operator_count"] == 1
    assert fresh_monitor["eta_utc"] == "2026-01-01T00:15:00+00:00"
    assert fresh_monitor["eta_kst"] == "2026-01-01T09:15:00+09:00"
    assert fresh_monitor["ready_now"] is False
    assert fresh_monitor["can_auto_run"] is False
    assert fresh_monitor["command"] == "current-safe-next-monitor-report-dir"
    assert fresh_monitor["details"]["command_source"] == (
        "remaining_work_closure_summary.primary_raw_useful_automation_action"
    )
    assert fresh_monitor["details"]["raw_signal_wait_command"] == "old-monitor-report-dir"
    assert fresh_monitor["details"]["raw_signal_wait_eta_utc"] == "2026-01-01T00:05:00+00:00"
    assert fresh_monitor["details"]["raw_signal_wait_eta_kst"] == "2026-01-01T09:05:00+09:00"
    assert fresh_monitor["details"]["effective_signal_monitor_eta_source"] == (
        "current_iteration_coverage.recommended_next_recheck_after"
    )
    assert fresh_monitor["details"]["covered_next_recheck_after_kst"] == (
        "2026-01-01T09:15:00+09:00"
    )
    assert fresh_monitor["details"]["retimestampted_after_current_iteration"] is True
    assert fresh_monitor["details"]["raw_covered_signal_command"] == (
        "current-safe-next-monitor-report-dir"
    )
    assert fresh_monitor["details"]["effective_auto_run_available"] is False
    assert fresh_monitor["details"]["source_command_mismatch_resolved"] is True
    shadow_runtime = next(
        item for item in plan["events"] if item["event_type"] == "shadow_runtime_observation"
    )
    assert shadow_runtime["ready_now"] is False
    assert shadow_runtime["can_auto_run"] is False
    assert shadow_runtime["command"] == "current-safe-next-shadow-watch"
    assert shadow_runtime["details"]["command_source"] == (
        "remaining_work_closure_summary.raw_automation_now_usefulness.shadow_runtime"
    )
    assert shadow_runtime["details"]["effective_auto_run_available"] is False
    assert plan["order_submission_allowed"] is False
    assert plan["no_live_order_sent"] is True


def test_command_consistency_audit_detects_signal_monitor_command_mismatch() -> None:
    audit = watch._command_consistency_audit(
        safe_next_action_plan={
            "primary_action": {
                "action_type": "monitor_fresh_signal",
                "target_gate": "current_fresh_signal",
                "command": "canonical-monitor --report-dir reports/canonical",
            }
        },
        remaining_work_closure_summary={
            "actionability_partition": {
                "run_now_without_operator": [
                    {
                        "action_type": "monitor_fresh_signal",
                        "target_gate": "current_fresh_signal",
                        "command": "canonical-monitor --report-dir reports/canonical",
                        "no_live_order_sent": True,
                    }
                ],
                "manual_now": [
                    {
                        "dry_run_command_template": "review --dry-run",
                        "no_live_order_sent": True,
                    }
                ],
                "no_live_order_sent": True,
            },
            "primary_operator_decision_action": {
                "operator_decision_packet": {
                    "decision_dry_run_command_template": "review --dry-run",
                    "no_live_order_sent": True,
                },
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
        next_material_progress_plan={
            "events": [
                {
                    "event_type": "fresh_signal_monitor",
                    "command": "stale-monitor --report-dir reports/stale",
                    "no_live_order_sent": True,
                },
                {
                    "event_type": "operator_review_decisions",
                    "command": "review --dry-run",
                    "no_live_order_sent": True,
                }
            ],
            "no_live_order_sent": True,
        },
        scheduled_command_projection={
            "primary_command": "canonical-monitor --report-dir reports/canonical",
            "no_live_order_sent": True,
        },
        signal_monitor={
            "command": "canonical-monitor --report-dir reports/canonical",
            "no_live_order_sent": True,
        },
    )

    parity = audit["signal_monitor_command_parity"]
    assert audit["status"] == "command_consistency_mismatch_detected"
    assert parity["status"] == "signal_monitor_command_mismatch"
    assert parity["canonical_source"] == (
        "remaining_work_closure_summary.actionability_partition.run_now_without_operator"
    )
    assert parity["canonical_command"] == "canonical-monitor --report-dir reports/canonical"
    assert parity["canonical_report_dir"] == "reports/canonical"
    assert parity["mismatch_count"] == 1
    assert parity["mismatches"][0]["source"] == "next_material_progress_plan.fresh_signal_monitor.command"
    assert parity["mismatches"][0]["report_dir"] == "reports/stale"
    operator_parity = audit["operator_review_command_parity"]
    assert operator_parity["status"] == "operator_review_command_match"
    assert operator_parity["mismatch_count"] == 0
    assert audit["auto_execute_allowed"] is False
    assert audit["auto_decision_allowed"] is False
    assert audit["order_submission_allowed"] is False
    assert audit["no_live_order_sent"] is True


def test_command_consistency_accepts_effective_signal_monitor_report_dir_retimestamp() -> None:
    audit = watch._command_consistency_audit(
        safe_next_action_plan={
            "primary_action": {
                "action_type": "monitor_fresh_signal",
                "target_gate": "current_fresh_signal",
                "command": "monitor --report-dir reports/signal_1215",
            }
        },
        remaining_work_closure_summary={
            "actionability_partition": {
                "run_now_without_operator": [],
                "manual_now": [],
                "no_live_order_sent": True,
            },
            "raw_automation_now_usefulness": [
                {
                    "action_type": "monitor_fresh_signal",
                    "target_gate": "current_fresh_signal",
                    "command": "monitor --report-dir reports/signal_1215",
                    "no_live_order_sent": True,
                }
            ],
            "no_live_order_sent": True,
        },
        next_material_progress_plan={
            "events": [
                {
                    "event_type": "fresh_signal_monitor",
                    "command": "monitor --report-dir reports/signal_1225",
                    "details": {
                        "raw_canonical_signal_command": "monitor --report-dir reports/signal_1215",
                        "signal_command_report_dir_retimestampted_to_effective": True,
                    },
                    "no_live_order_sent": True,
                }
            ],
            "no_live_order_sent": True,
        },
        scheduled_command_projection={
            "primary_command": "monitor --report-dir reports/signal_1225",
            "primary_raw_command": "monitor --report-dir reports/signal_1215",
            "primary_report_dir_retimestampted_to_effective": True,
            "no_live_order_sent": True,
        },
        signal_monitor={
            "command": "monitor --report-dir reports/signal_1215",
            "no_live_order_sent": True,
        },
    )

    parity = audit["signal_monitor_command_parity"]
    assert audit["status"] == "command_consistency_pass"
    assert parity["status"] == "signal_monitor_command_match"
    assert parity["canonical_source"] == (
        "remaining_work_closure_summary.raw_automation_now_usefulness.signal_monitor"
    )
    assert parity["mismatch_count"] == 0
    assert parity["retimestamped_equivalent_match_count"] == 2
    assert {
        item["source"] for item in parity["retimestamped_equivalent_matches"]
    } == {
        "next_material_progress_plan.fresh_signal_monitor.command",
        "scheduled_command_projection.primary_command",
    }
    assert parity["no_live_order_sent"] is True


def test_command_consistency_audit_uses_raw_covered_signal_source_when_effective_queue_empty() -> None:
    command = "monitor --report-dir reports/current"
    audit = watch._command_consistency_audit(
        safe_next_action_plan={
            "primary_action": {
                "action_type": "monitor_fresh_signal",
                "target_gate": "current_fresh_signal",
                "command": command,
            }
        },
        remaining_work_closure_summary={
            "raw_automation_now_usefulness": [
                {
                    "action_type": "monitor_fresh_signal",
                    "target_gate": "current_fresh_signal",
                    "command": command,
                    "useful_now": True,
                    "no_live_order_sent": True,
                }
            ],
            "actionability_partition": {
                "run_now_without_operator": [],
                "manual_now": [
                    {
                        "dry_run_command_template": "review --dry-run",
                        "no_live_order_sent": True,
                    }
                ],
                "no_live_order_sent": True,
            },
            "primary_operator_decision_action": {
                "operator_decision_packet": {
                    "decision_dry_run_command_template": "review --dry-run",
                    "no_live_order_sent": True,
                },
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
        next_material_progress_plan={
            "events": [
                {
                    "event_type": "fresh_signal_monitor",
                    "command": command,
                    "no_live_order_sent": True,
                },
                {
                    "event_type": "operator_review_decisions",
                    "command": "review --dry-run",
                    "no_live_order_sent": True,
                },
            ],
            "no_live_order_sent": True,
        },
        scheduled_command_projection={"primary_command": command, "no_live_order_sent": True},
        signal_monitor={"command": command, "no_live_order_sent": True},
    )

    parity = audit["signal_monitor_command_parity"]
    assert audit["status"] == "command_consistency_pass"
    assert parity["status"] == "signal_monitor_command_match"
    assert parity["canonical_source"] == (
        "remaining_work_closure_summary.raw_automation_now_usefulness.signal_monitor"
    )
    assert parity["missing_expected_sources"] == []
    assert parity["mismatch_count"] == 0
    actionability_source = next(
        item
        for item in parity["sources"]
        if item["source"] == "remaining_work_closure_summary.actionability_partition.run_now_without_operator"
    )
    assert actionability_source["expected_to_match"] is False
    assert parity["actionability_effective_queue_empty_but_raw_covered_command_available"] is True
    assert audit["order_submission_allowed"] is False
    assert audit["no_live_order_sent"] is True


def test_operator_action_digest_summarizes_auto_manual_and_wait_gates() -> None:
    digest = watch._operator_action_digest(
        latest={
            "no_live_order_sent": True,
            "signal_wait_plan": {"fresh_signal": False},
            "launch_readiness": {
                "status": "research_ready_waiting_for_fresh_signal",
                "next_blocker": {
                    "gate": "current_fresh_signal",
                    "blocker": "fresh_signal_missing_or_stale",
                },
                "paper_only_rehearsal": {"paper_apply_allowed_now": False},
            },
        },
        actionability_partition={
            "run_now_without_operator": [
                {
                    "action_type": "monitor_fresh_signal",
                    "target_gate": "current_fresh_signal",
                    "command": "monitor-safe",
                    "no_live_order_sent": True,
                }
            ],
            "manual_now": [
                {
                    "action_type": "review_conditional_overfit_holdout_proxy",
                    "target_gate": "conditional_overfit_operator_review",
                    "active_operator_review_report": "review.json",
                    "required_fields_remaining": ["status", "reviewer"],
                    "no_live_order_sent": True,
                }
            ],
            "time_waits": [
                {
                    "problem_id": "microstructure_calendar_day_coverage",
                    "status": "waiting_for_future_quote_calendar_days",
                    "next_kst": "2026-01-02T09:00:00+09:00",
                    "remaining_calendar_days": 1,
                    "no_live_order_sent": True,
                }
            ],
            "signal_waits": [],
            "dependency_blocked": [],
            "no_live_order_sent": True,
        },
        dependency_lanes={
            "status": "operator_and_realtime_dependencies_open",
            "critical_path": ["current_fresh_signal", "operator_review_decisions"],
            "parallel_calendar_path": ["microstructure_calendar_day_coverage"],
            "no_live_order_sent": True,
        },
        manual_batch_handoff={
            "status": "operator_review_batch_waiting_for_operator_inputs",
            "batch_fingerprint": "abc123",
            "no_live_order_sent": True,
        },
        next_material_progress_plan={
            "primary_next_event": {
                "event_type": "fresh_signal_monitor",
                "gate": "current_fresh_signal",
                "eta_kst": "2026-01-01T09:05:00+09:00",
                "ready_now": True,
                "wait_minutes": 0.0,
            },
            "no_live_order_sent": True,
        },
        daily_quote_checkpoint_summary={
            "remaining_calendar_days": 1,
            "next_quote_coverage_kst_at": "2026-01-02T09:00:00+09:00",
            "no_live_order_sent": True,
        },
        execution_parity_status_summary={
            "missing_samples": 20,
            "estimated_completion_kst": "2026-01-10T09:00:00+09:00",
            "no_live_order_sent": True,
        },
        command_consistency_audit={
            "status": "command_consistency_pass",
            "no_live_order_sent": True,
        },
    )

    assert digest["status"] == "run_safe_monitoring_and_complete_manual_reviews"
    assert digest["primary_next"] == "run_primary_safe_auto_command_then_process_manual_review_batch"
    assert digest["primary_material_ready_now"] is True
    assert digest["primary_material_wait_minutes"] == 0.0
    assert digest["operator_action_scope"] == (
        "safe_auto_and_manual_available_but_launch_primary_wait_is_realtime"
    )
    assert digest["primary_launch_wait_gate"] == "current_fresh_signal"
    assert digest["primary_human_action_gate"] == "conditional_overfit_operator_review"
    assert digest["no_safe_auto_command_now"] is False
    assert digest["primary_safe_auto_command"] == "monitor-safe"
    assert digest["manual_decision_count"] == 1
    assert digest["primary_manual_review_report"] == "review.json"
    assert digest["primary_time_wait"]["problem_id"] == "microstructure_calendar_day_coverage"
    assert digest["quote_remaining_calendar_days"] == 1
    assert digest["execution_parity_missing_samples"] == 20
    assert digest["operator_decisions_are_manual_only"] is True
    assert digest["paper_apply_is_manual_only"] is True
    assert digest["auto_decision_allowed"] is False
    assert digest["auto_apply_allowed"] is False
    assert digest["order_submission_allowed"] is False
    assert digest["no_live_order_sent"] is True


def test_operator_action_digest_does_not_label_manual_command_as_safe_auto() -> None:
    digest = watch._operator_action_digest(
        latest={
            "no_live_order_sent": True,
            "signal_wait_plan": {"fresh_signal": False},
            "launch_readiness": {
                "status": "research_ready_waiting_for_fresh_signal",
                "next_blocker": {
                    "gate": "current_fresh_signal",
                    "blocker": "fresh_signal_missing_or_stale",
                },
                "paper_only_rehearsal": {"paper_apply_allowed_now": False},
            },
        },
        actionability_partition={
            "run_now_without_operator": [],
            "manual_now": [
                {
                    "action_type": "review_conditional_overfit_holdout_proxy",
                    "target_gate": "conditional_overfit_operator_review",
                    "active_operator_review_report": "review.json",
                    "required_fields_remaining": ["status", "reviewer"],
                    "no_live_order_sent": True,
                }
            ],
            "time_waits": [],
            "signal_waits": [
                {
                    "problem_id": "current_fresh_signal",
                    "status": "open_waiting_for_realtime_signal",
                    "next_monitor_kst": "2026-01-01T09:15:00+09:00",
                    "no_live_order_sent": True,
                }
            ],
            "dependency_blocked": [],
            "no_live_order_sent": True,
        },
        dependency_lanes={
            "status": "operator_and_realtime_dependencies_open",
            "critical_path": ["current_fresh_signal", "operator_review_decisions"],
            "parallel_calendar_path": [],
            "no_live_order_sent": True,
        },
        manual_batch_handoff={
            "status": "operator_review_batch_waiting_for_operator_inputs",
            "batch_fingerprint": "abc123",
            "no_live_order_sent": True,
        },
        next_material_progress_plan={
            "primary_next_event": {
                "event_type": "operator_review_decisions",
                "gate": "operator_review",
                "eta_kst": "2026-01-01T09:00:00+09:00",
                "ready_now": True,
                "wait_minutes": 0.0,
                "command": "manual-review-dry-run",
            },
            "no_live_order_sent": True,
        },
        daily_quote_checkpoint_summary={"remaining_calendar_days": 0, "no_live_order_sent": True},
        execution_parity_status_summary={"missing_samples": 20, "no_live_order_sent": True},
        command_consistency_audit={"status": "command_consistency_pass", "no_live_order_sent": True},
    )

    assert digest["status"] == "complete_manual_operator_reviews"
    assert digest["safe_auto_command_count"] == 0
    assert digest["primary_safe_auto_action"] is None
    assert digest["primary_safe_auto_command"] is None
    assert digest["primary_material_command"] == "manual-review-dry-run"
    assert digest["operator_action_scope"] == (
        "manual_available_but_launch_primary_wait_is_realtime"
    )
    assert digest["primary_launch_wait_gate"] == "current_fresh_signal"
    assert digest["primary_human_action_gate"] == "conditional_overfit_operator_review"
    assert digest["no_safe_auto_command_now"] is True
    assert digest["primary_signal_wait"]["next_monitor_kst"] == "2026-01-01T09:15:00+09:00"
    assert digest["operator_decisions_are_manual_only"] is True
    assert digest["auto_decision_allowed"] is False
    assert digest["auto_apply_allowed"] is False
    assert digest["order_submission_allowed"] is False
    assert digest["no_live_order_sent"] is True


def test_gate_substitution_digest_separates_proxy_and_realtime_gates() -> None:
    digest = watch._gate_substitution_digest(
        paper_only_rehearsal={
            "system_ready": True,
            "armed": True,
            "max_substitution_status": "max_substitution_complete_realtime_gate_remaining",
            "max_substitution_ready": True,
            "proxy_gates": [
                {
                    "gate": "historical_quote_replay",
                    "passed": True,
                    "substitution_type": "historical_replay",
                },
                {
                    "gate": "paper_bridge_command_contract",
                    "passed": True,
                    "substitution_type": "static_command_preflight",
                },
            ],
            "unresolved_proxy_gates": [],
            "substituted_or_prevalidated_gates": [
                "historical_quote_replay",
                "paper_bridge_command_contract",
            ],
            "non_substitutable_remaining_gates": [
                "current_fresh_signal",
                "first_real_paper_lifecycle_row",
            ],
            "not_required_for_paper_only_goal": ["tiny_canary_order_submission"],
            "still_required_for_live_or_tiny_canary": ["execution_parity_20_sample_floor"],
            "no_live_order_sent": True,
        },
        remaining_work_closure_summary={
            "non_substitutable_problem_ids": [
                "current_fresh_signal",
                "execution_parity_samples",
                "microstructure_calendar_day_coverage",
            ],
            "wait_only_problem_ids": [
                "current_fresh_signal",
                "execution_parity_samples",
                "microstructure_calendar_day_coverage",
            ],
            "no_live_order_sent": True,
        },
        daily_quote_checkpoint_summary={
            "remaining_calendar_days": 25,
            "earliest_calendar_completion_kst": "2026-07-03T09:00:00+09:00",
            "no_live_order_sent": True,
        },
        execution_parity_status_summary={
            "missing_samples": 20,
            "estimated_completion_kst": "2026-07-26T09:00:00+09:00",
            "no_live_order_sent": True,
        },
        runtime_progress={
            "remaining_hours": 16.5,
            "no_live_order_sent": True,
        },
    )

    assert digest["status"] == "paper_only_proxy_substitution_complete_realtime_gates_remaining"
    assert digest["paper_only_system_ready"] is True
    assert digest["proxy_gate_count"] == 2
    assert digest["proxy_gate_passed_count"] == 2
    assert digest["unresolved_proxy_gate_count"] == 0
    assert digest["non_substitutable_remaining_gates"] == [
        "current_fresh_signal",
        "first_real_paper_lifecycle_row",
    ]
    gates = [item["gate"] for item in digest["realtime_waits"]]
    assert "current_fresh_signal" in gates
    assert "first_real_paper_lifecycle_row" in gates
    assert "execution_parity_samples" in gates
    assert "microstructure_calendar_day_coverage" in gates
    assert "shadow_runtime_24h_observed" in gates
    assert digest["backtest_substitution_allowed_for_launch_gate"] is False
    assert digest["synthetic_or_backtest_rows_close_realtime_gates"] is False
    assert digest["paper_only_proxy_completed_but_live_still_blocked"] is True
    assert digest["operator_decision_allowed"] is False
    assert digest["order_submission_allowed"] is False
    assert digest["no_live_order_sent"] is True


def test_gate_eta_digest_marks_paper_apply_eta_unknown_until_signal_and_reviews() -> None:
    digest = watch._gate_eta_digest(
        gate_substitution_digest={
            "realtime_waits": [
                {
                    "gate": "current_fresh_signal",
                    "reason": "requires_realtime_add_or_remove_signal",
                    "eta_kst": None,
                    "non_substitutable": True,
                },
                {
                    "gate": "execution_parity_samples",
                    "reason": "requires_real_reviewed_paper_lifecycle_rows",
                    "eta_kst": "2026-07-26T09:00:00+09:00",
                    "non_substitutable": True,
                },
            ],
            "realtime_wait_count": 2,
            "non_substitutable_problem_ids": [
                "current_fresh_signal",
                "execution_parity_samples",
            ],
            "backtest_substitution_allowed_for_launch_gate": False,
            "synthetic_or_backtest_rows_close_realtime_gates": False,
            "no_live_order_sent": True,
        },
        next_material_progress_plan={
            "immediate_auto_count": 1,
            "immediate_operator_count": 1,
            "future_event_count": 1,
            "unscheduled_wait_count": 1,
            "events": [
                {
                    "event_type": "quote_calendar_checkpoint",
                    "gate": "microstructure_calendar_day_coverage",
                    "eta_kst": "2026-01-02T09:00:00+09:00",
                    "wait_minutes": 60.0,
                    "can_auto_run": True,
                    "requires_operator_review": False,
                },
                {
                    "event_type": "execution_parity_sample_floor",
                    "gate": "execution_parity_samples",
                    "eta_kst": "2026-07-26T09:00:00+09:00",
                },
            ],
            "future_events": [
                {
                    "event_type": "quote_calendar_checkpoint",
                    "gate": "microstructure_calendar_day_coverage",
                    "eta_kst": "2026-01-02T09:00:00+09:00",
                    "wait_minutes": 60.0,
                    "can_auto_run": True,
                    "requires_operator_review": False,
                }
            ],
            "unscheduled_waits": [
                {
                    "event_type": "first_fresh_signal_paper_apply",
                    "gate": "first_real_paper_lifecycle_row",
                    "reason": "monitor_fresh_signal_without_forcing_entry",
                }
            ],
            "no_live_order_sent": True,
        },
        operator_action_digest={
            "manual_decision_count": 2,
            "paper_apply_allowed_now": False,
            "no_live_order_sent": True,
        },
        dependency_lanes={
            "critical_path": [
                "current_fresh_signal",
                "operator_review_decisions",
                "first_real_paper_lifecycle_row",
            ],
            "parallel_calendar_path": ["microstructure_calendar_day_coverage"],
            "no_live_order_sent": True,
        },
        daily_quote_checkpoint_summary={
            "remaining_calendar_days": 25,
            "next_quote_coverage_kst_at": "2026-01-02T09:00:00+09:00",
            "earliest_calendar_completion_kst": "2026-07-03T09:00:00+09:00",
            "no_live_order_sent": True,
        },
        execution_parity_status_summary={
            "missing_samples": 20,
            "estimated_completion_kst": "2026-07-26T09:00:00+09:00",
            "no_live_order_sent": True,
        },
        runtime_progress={
            "remaining_hours": 16.0,
            "no_live_order_sent": True,
        },
    )

    assert digest["status"] == "unscheduled_realtime_and_manual_gates_block_paper_apply_eta"
    assert digest["paper_apply_eta_known"] is False
    assert digest["paper_apply_earliest_known_kst"] is None
    assert digest["has_unscheduled_realtime_gate"] is True
    assert digest["next_unscheduled_gate"] == "current_fresh_signal"
    assert digest["manual_decision_required"] is True
    assert digest["manual_decision_count"] == 2
    assert digest["next_scheduled_event"]["event_type"] == "quote_calendar_checkpoint"
    assert digest["quote_calendar_completion_kst"] == "2026-07-03T09:00:00+09:00"
    assert digest["execution_parity_eta_kst"] == "2026-07-26T09:00:00+09:00"
    assert digest["planning_caveat"] == (
        "paper_apply_eta_is_unknown_until_a_fresh_realtime_signal_exists_and_manual_reviews_are_completed"
    )
    assert digest["backtest_substitution_allowed_for_launch_gate"] is False
    assert digest["synthetic_or_backtest_rows_close_realtime_gates"] is False
    assert digest["order_submission_allowed"] is False
    assert digest["no_live_order_sent"] is True


def test_launch_progress_scorecard_splits_completion_from_open_launch_gates() -> None:
    scorecard = watch._launch_progress_scorecard(
        latest={
            "no_live_order_sent": True,
            "signal_wait_plan": {
                "status": "blocked_waiting_for_fresh_signal",
                "fresh_signal": False,
                "next_monitor_after_kst": "2026-01-01T09:05:00+09:00",
                "recommended_monitor_interval_minutes": 5.0,
                "monitor_interval_capped_by_signal_freshness": True,
                "no_live_order_sent": True,
            },
            "launch_readiness": {
                "status": "research_ready_waiting_for_fresh_signal",
                "paper_only_rehearsal": {"paper_apply_allowed_now": False},
            },
        },
        runtime_progress={
            "status": "collecting_runtime",
            "observed_hours": 8.0,
            "target_hours": 24.0,
            "remaining_hours": 16.0,
            "progress_pct": 33.3333,
            "no_live_order_sent": True,
        },
        daily_quote_checkpoint_summary={
            "status": "waiting_for_next_utc_calendar_day",
            "quote_observed": 40,
            "quote_required": 80,
            "remaining_quote_samples": 40,
            "calendar_day_count": 3,
            "min_calendar_days": 30,
            "remaining_calendar_days": 27,
            "next_quote_coverage_kst_at": "2026-01-02T09:00:00+09:00",
            "earliest_calendar_completion_kst": "2026-01-30T09:00:00+09:00",
            "backfill_allowed_for_launch_gate": False,
            "no_live_order_sent": True,
        },
        gate_substitution_digest={
            "status": "paper_only_proxy_substitution_complete_realtime_gates_remaining",
            "max_substitution_ready": True,
            "proxy_gate_count": 2,
            "proxy_gate_passed_count": 2,
            "unresolved_proxy_gate_count": 0,
            "unresolved_proxy_gates": [],
            "non_substitutable_remaining_gates": [
                "current_fresh_signal",
                "first_real_paper_lifecycle_row",
            ],
            "non_substitutable_problem_ids": [
                "current_fresh_signal",
                "execution_parity_samples",
                "microstructure_calendar_day_coverage",
            ],
            "backtest_substitution_allowed_for_launch_gate": False,
            "synthetic_or_backtest_rows_close_realtime_gates": False,
            "no_live_order_sent": True,
        },
        gate_eta_digest={
            "paper_apply_eta_known": False,
            "paper_apply_earliest_known_kst": None,
            "has_unscheduled_realtime_gate": True,
            "next_unscheduled_gate": "current_fresh_signal",
            "shadow_runtime_completion_eta_kst": "2026-01-02T01:00:00+09:00",
            "quote_calendar_completion_kst": "2026-01-30T09:00:00+09:00",
            "execution_parity_eta_kst": "2026-02-10T09:00:00+09:00",
            "planning_caveat": (
                "paper_apply_eta_is_unknown_until_a_fresh_realtime_signal_exists_and_manual_reviews_are_completed"
            ),
            "no_live_order_sent": True,
        },
        operator_action_digest={
            "next_blocker_gate": "current_fresh_signal",
            "primary_next": "run_primary_safe_auto_command_then_process_manual_review_batch",
            "primary_material_event": "fresh_signal_monitor",
            "primary_material_gate": "current_fresh_signal",
            "manual_decision_count": 1,
            "paper_apply_allowed_now": False,
            "fresh_signal_available": False,
            "no_live_order_sent": True,
        },
        operator_review_handoff_summary={
            "status": "operator_review_ready",
            "ready_review_count": 1,
            "operator_decision_required_count": 1,
            "total_review_count": 1,
            "no_live_order_sent": True,
        },
        operator_review_resolution_plan={
            "status": "operator_review_manual_resolution_ready",
            "readiness_matrix": {
                "status": "operator_review_matrix_ready_for_manual_dry_run",
                "row_count": 1,
                "dry_run_ready_count": 1,
            },
            "manual_batch_handoff": {
                "status": "operator_review_batch_ready_for_manual_dry_run",
            },
            "no_live_order_sent": True,
        },
        execution_parity_status_summary={
            "status": "waiting_for_fresh_signal",
            "eligible_journal_rows": 0,
            "required_samples": 20,
            "missing_samples": 20,
            "estimated_future_paper_apply_events_needed": 20,
            "non_substitutable": True,
            "no_live_order_sent": True,
        },
        next_material_progress_plan={
            "status": "safe_auto_progress_available",
            "immediate_auto_count": 1,
            "immediate_operator_count": 1,
            "future_event_count": 2,
            "unscheduled_wait_count": 1,
            "no_live_order_sent": True,
        },
        remaining_work_closure_summary={
            "operator_review_problem_ids": ["conditional_overfit_operator_review"],
            "dependency_lanes": {
                "realtime_signal_lane": {
                    "monitor_effective_next_after_kst": "2026-01-01T09:15:00+09:00",
                    "monitor_raw_next_after_kst": "2026-01-01T09:05:00+09:00",
                    "monitor_covered_next_recheck_after_kst": "2026-01-01T09:15:00+09:00",
                    "monitor_next_after_source": (
                        "current_iteration_coverage.recommended_next_recheck_after"
                    ),
                    "monitor_next_after_retimestampted_after_current_iteration": True,
                }
            },
            "no_live_order_sent": True,
        },
    )

    assert scorecard["status"] == "paper_only_proxy_complete_realtime_or_manual_gates_open"
    assert scorecard["paper_only_research_proxy_complete"] is True
    assert scorecard["paper_apply_eta_known"] is False
    assert scorecard["ready_for_paper_apply_now"] is False
    assert scorecard["ready_for_tiny_canary_or_live"] is False
    assert scorecard["lanes"]["paper_only_proxy"]["progress_pct"] == 100.0
    assert scorecard["lanes"]["shadow_runtime"]["progress_pct"] == 33.3333
    assert scorecard["lanes"]["quote_microstructure"]["progress_pct"] == 10.0
    assert scorecard["lanes"]["operator_review"]["progress_pct"] == 0.0
    assert scorecard["lanes"]["operator_review"]["template_ready_pct"] == 100.0
    assert scorecard["lanes"]["operator_review"]["manual_decision_completion_pct"] == 0.0
    assert scorecard["lanes"]["execution_parity"]["progress_pct"] == 0.0
    assert scorecard["lanes"]["fresh_signal"]["progress_pct"] == 0.0
    assert scorecard["lanes"]["fresh_signal"]["next_monitor_kst"] == "2026-01-01T09:15:00+09:00"
    assert scorecard["lanes"]["fresh_signal"]["raw_next_monitor_kst"] == (
        "2026-01-01T09:05:00+09:00"
    )
    assert scorecard["lanes"]["fresh_signal"]["covered_next_recheck_after_kst"] == (
        "2026-01-01T09:15:00+09:00"
    )
    assert scorecard["lanes"]["fresh_signal"]["next_monitor_source"] == (
        "current_iteration_coverage.recommended_next_recheck_after"
    )
    assert (
        scorecard["lanes"]["fresh_signal"][
            "next_monitor_retimestampted_after_current_iteration"
        ]
        is True
    )
    fresh_row = scorecard["critical_path_scorecard"]["rows"][0]
    assert fresh_row["gate"] == "current_fresh_signal"
    assert fresh_row["next_action_kst"] == "2026-01-01T09:15:00+09:00"
    assert fresh_row["raw_next_action_kst"] == "2026-01-01T09:05:00+09:00"
    assert fresh_row["covered_next_recheck_after_kst"] == "2026-01-01T09:15:00+09:00"
    assert fresh_row["next_action_source"] == (
        "current_iteration_coverage.recommended_next_recheck_after"
    )
    assert fresh_row["next_action_retimestampted_after_current_iteration"] is True
    assert scorecard["critical_path_scorecard"]["status"] == (
        "critical_path_blocked_at_current_fresh_signal"
    )
    assert scorecard["critical_path_scorecard"]["progress_floor_pct"] == 0.0
    assert scorecard["critical_path_scorecard"]["progress_average_pct"] == 0.0
    assert scorecard["critical_path_scorecard"]["next_open_gate"] == "current_fresh_signal"
    assert scorecard["critical_path_scorecard"]["paper_apply_path"]["status"] == (
        "paper_apply_path_blocked_at_current_fresh_signal"
    )
    assert scorecard["critical_path_scorecard"]["paper_apply_path"]["next_open_gate"] == (
        "current_fresh_signal"
    )
    assert scorecard["critical_path_scorecard"]["parallel_path"]["status"] == (
        "parallel_path_blocked_at_microstructure_calendar_day_coverage"
    )
    assert scorecard["critical_path_scorecard"]["parallel_path"]["progress_floor_pct"] == 10.0
    assert scorecard["critical_path_scorecard"]["paper_apply_ready_now"] is False
    assert scorecard["critical_path_scorecard"]["auto_apply_allowed"] is False
    assert scorecard["critical_path_scorecard"]["order_submission_allowed"] is False
    assert scorecard["critical_path_scorecard"]["no_live_order_sent"] is True
    assert "current_fresh_signal" in scorecard["blocking_gates"]
    assert "operator_review" in scorecard["open_lanes"]
    assert scorecard["auto_decision_allowed"] is False
    assert scorecard["auto_apply_allowed"] is False
    assert scorecard["order_submission_allowed"] is False
    assert scorecard["no_live_order_sent"] is True


def test_launch_execution_matrix_partitions_auto_manual_wait_and_forbidden_actions() -> None:
    matrix = watch._launch_execution_matrix(
        generated_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        launch_progress_scorecard={
            "no_live_order_sent": True,
            "critical_path_scorecard": {
                "launch_blocked_by": "current_fresh_signal",
                "paper_apply_blocked_by": "current_fresh_signal",
                "parallel_blocked_by": "microstructure_calendar_day_coverage",
                "paper_apply_ready_now": False,
                "next_open_gate": "current_fresh_signal",
                "no_live_order_sent": True,
            },
        },
        remaining_work_closure_summary={
            "actionability_partition": {
                "run_now_without_operator": [
                    {
                        "action_type": "monitor_fresh_signal",
                        "target_gate": "current_fresh_signal",
                        "priority": 20,
                        "command": "monitor",
                        "execute_after_kst": None,
                        "reason": "keep_signal_cadence",
                        "safe_to_auto_run_without_operator": True,
                        "no_live_order_sent": True,
                    }
                ],
                "signal_waits": [
                    {
                        "problem_id": "current_fresh_signal",
                        "status": "open_waiting_for_realtime_signal",
                        "next_monitor_kst": "2026-01-01T09:05:00+09:00",
                        "monitor_command": "monitor",
                        "unlocks": ["first_real_paper_lifecycle_row"],
                        "non_substitutable": True,
                        "no_live_order_sent": True,
                    }
                ],
                "time_waits": [],
                "dependency_blocked": [],
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
        operator_review_resolution_plan={
            "manual_batch_handoff": {
                "status": "operator_review_batch_waiting_for_operator_inputs",
                "batch_fingerprint": "abc",
                "batch_order": [
                    {
                        "review_kind": "conditional_overfit",
                        "target_gate": "conditional_overfit_operator_review",
                        "candidate_recipe_id": "candidate",
                        "active_operator_review_report": "review.json",
                        "ready_for_operator_dry_run_template": True,
                        "contract_accept_blockers_before_write": [
                            "operator_required_fields_still_empty"
                        ],
                        "next_manual_action": (
                            "choose_accept_or_reject_replace_placeholders_then_run_dry_run"
                        ),
                        "safe_default_if_uncertain": "reject",
                        "decision_options": [
                            {"decision": "accept", "no_live_order_sent": True},
                            {"decision": "reject", "no_live_order_sent": True},
                        ],
                        "validation_command": "validate",
                        "after_write_required_actions": ["rerun_launch_shadow_watch"],
                        "no_live_order_sent": True,
                    }
                ],
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
        command_consistency_audit={
            "status": "command_consistency_pass",
            "no_live_order_sent": True,
        },
    )

    assert matrix["status"] == "safe_auto_monitoring_and_manual_reviews_available"
    assert matrix["urgency_status"] == "safe_auto_action_ready"
    assert matrix["primary_urgency"] == "ready_safe_auto"
    assert matrix["effective_urgency_status"] == "safe_auto_action_ready"
    assert matrix["effective_primary_urgency"] == "ready_safe_auto"
    assert matrix["safe_auto_coverage_status"] == "ready_safe_auto_actions_uncovered"
    assert matrix["safe_auto_action_count"] == 1
    assert matrix["ready_safe_auto_action_count"] == 1
    assert matrix["safe_auto_ready_count"] == 1
    assert matrix["safe_auto_effective_ready_count"] == 1
    assert matrix["overdue_safe_auto_action_count"] == 0
    assert matrix["covered_due_safe_auto_action_count"] == 0
    assert matrix["uncovered_ready_safe_auto_action_count"] == 1
    assert matrix["uncovered_overdue_safe_auto_action_count"] == 0
    assert matrix["scheduled_safe_auto_action_count"] == 0
    assert matrix["max_overdue_minutes"] == 0.0
    assert matrix["manual_action_count"] == 1
    assert matrix["manual_ready_count"] == 1
    assert matrix["manual_due_count"] == 1
    assert matrix["manual_wait_count"] == 0
    assert matrix["manual_effective_due_count"] == 1
    assert matrix["manual_readiness_status"] == "manual_reviews_waiting_for_operator_inputs"
    assert matrix["manual_template_ready_count"] == 1
    assert matrix["manual_operator_input_required_count"] == 1
    assert matrix["manual_dry_run_ready_count"] == 0
    assert matrix["manual_write_ready_count"] == 0
    assert matrix["manual_required_input_names"] == [
        "decision",
        "rationale",
        "reviewed_at",
        "reviewer",
    ]
    assert matrix["manual_input_contract_statuses"] == [
        "operator_input_contract_command_coverage_incomplete"
    ]
    assert matrix["manual_prompt_card_statuses"] == []
    assert matrix["manual_prompt_card_ready_count"] == 0
    assert matrix["manual_input_form_statuses"] == [
        "operator_input_form_ready_without_prompt_card"
    ]
    assert matrix["manual_input_form_ready_count"] == 1
    assert matrix["manual_safe_default_alignment_status"] == "manual_safe_default_alignment_pass"
    assert matrix["manual_safe_default_alignment_statuses"] == [
        "safe_default_decision_matches_accepted_values"
    ]
    assert matrix["manual_safe_default_decisions"] == ["reject"]
    assert matrix["manual_safe_default_alignment_mismatch_count"] == 0
    assert matrix["manual_safe_default_alignment_next_step"] is None
    assert matrix["manual_safe_default_alignment_requires_repair"] is False
    assert matrix["manual_rationale_must_address_count"] == 0
    assert matrix["manual_minimum_anchor_count"] == 0
    assert matrix["manual_decision_option_count"] == 2
    assert matrix["manual_decision_dry_run_ready_count"] == 0
    assert matrix["manual_decision_write_ready_count"] == 0
    assert matrix["manual_decision_validation_ready_count"] == 2
    assert matrix["primary_manual_input_step"]["item"] == "choose_accept_or_reject"
    assert matrix["primary_manual_input_step"]["status"] == "required"
    assert matrix["primary_manual_input_contract"]["status"] == (
        "operator_input_contract_command_coverage_incomplete"
    )
    assert matrix["primary_manual_input_contract"]["next_contract_step"] == (
        "repair_decision_command_coverage_before_write"
    )
    assert matrix["wait_gate_count"] == 1
    assert matrix["primary_next_step"]["step_type"] == "safe_auto_monitoring"
    assert matrix["primary_next_step"]["target_gate"] == "current_fresh_signal"
    assert matrix["primary_next_step"]["due_status"] == "ready_no_schedule"
    assert matrix["primary_next_step"]["ready_now"] is True
    assert matrix["primary_effective_next_step"]["target_gate"] == "current_fresh_signal"
    assert matrix["primary_effective_next_step"]["effective_due_status"] == "ready_no_schedule"
    assert matrix["primary_effective_next_step"]["covered_due_by_current_iteration"] is False
    assert matrix["manual_actions"][0]["available_decisions"] == ["accept", "reject"]
    assert matrix["manual_actions"][0]["operator_input_contract_status"] == (
        "operator_input_contract_command_coverage_incomplete"
    )
    assert matrix["manual_actions"][0]["ready_now"] is True
    assert matrix["manual_actions"][0]["due_status"] == "operator_input_required_now"
    assert matrix["manual_actions"][0]["effective_due_status"] == "operator_input_required_now"
    assert matrix["manual_actions"][0]["manual_action_due_now"] is True
    assert matrix["manual_actions"][0]["covered_due_by_current_iteration"] is False
    assert matrix["manual_actions"][0]["operator_input_contract"]["accepted_decisions"] == [
        "accept",
        "reject",
    ]
    assert matrix["manual_actions"][0]["operator_input_contract"]["operator_prompt_card"] == {}
    assert matrix["manual_actions"][0]["operator_input_contract"]["operator_input_form_status"] == (
        "operator_input_form_ready_without_prompt_card"
    )
    assert matrix["manual_actions"][0]["operator_input_contract"]["operator_input_form"][
        "required_field_names"
    ] == [
        "decision",
        "reviewer",
        "reviewed_at",
        "rationale",
    ]
    decision_field = matrix["manual_actions"][0]["operator_input_contract"]["operator_input_form"][
        "decision_field"
    ]
    assert decision_field["safe_default_decision_if_uncertain"] == "reject"
    assert decision_field["safe_default_policy_if_uncertain"] == "reject"
    assert decision_field["safe_default_alignment"]["status"] == (
        "safe_default_decision_matches_accepted_values"
    )
    assert decision_field["safe_default_alignment"]["decision_is_accepted_value"] is True
    assert decision_field["safe_default_alignment"]["auto_decision_allowed"] is False
    assert matrix["manual_actions"][0]["operator_input_contract"]["operator_input_form"][
        "rationale_field"
    ]["minimum_rationale_chars"] == 30
    assert matrix["manual_actions"][0]["operator_input_contract"]["rationale_must_address"] == []
    assert matrix["manual_actions"][0]["operator_input_contract"]["evidence_anchor_candidates"] == []
    assert matrix["manual_actions"][0]["operator_input_contract"]["write_blocked_until"] == [
        "operator_inputs_complete",
        "matching_dry_run_passed",
        "operator_confirms_write",
    ]
    assert matrix["manual_actions"][0]["operator_input_required"] is True
    assert matrix["manual_actions"][0]["operator_input_status"] == "operator_inputs_required"
    assert matrix["manual_actions"][0]["operator_input_blockers"] == [
        "operator_required_fields_still_empty"
    ]
    assert matrix["manual_actions"][0]["operator_required_input_names"] == [
        "decision",
        "reviewer",
        "reviewed_at",
        "rationale",
    ]
    assert matrix["manual_actions"][0]["operator_required_inputs"][0]["accepted_values"] == [
        "accept",
        "reject",
    ]
    assert matrix["manual_actions"][0]["operator_input_checklist"][0]["item"] == (
        "choose_accept_or_reject"
    )
    assert matrix["manual_actions"][0]["operator_input_checklist"][2]["status"] == (
        "blocked_until_operator_inputs_complete"
    )
    assert matrix["manual_actions"][0]["manual_dry_run_ready_now"] is False
    assert matrix["manual_actions"][0]["manual_dry_run_status"] == (
        "template_ready_waiting_for_operator_inputs"
    )
    assert matrix["manual_actions"][0]["manual_write_ready_now"] is False
    assert matrix["manual_actions"][0]["manual_write_status"] == (
        "blocked_until_operator_inputs_and_dry_run_pass"
    )
    assert matrix["manual_actions"][0]["auto_decision_allowed"] is False
    assert matrix["forbidden_action_count"] >= 4
    assert {
        item["action_type"] for item in matrix["forbidden_actions"]
    } >= {
        "submit_live_order_or_enable_live_trading",
        "auto_apply_paper_order_after_signal",
        "auto_accept_or_reject_operator_reviews",
    }
    assert matrix["operator_decisions_are_manual_only"] is True
    assert matrix["paper_apply_is_manual_only"] is True
    assert matrix["auto_decision_allowed"] is False
    assert matrix["auto_apply_allowed"] is False
    assert matrix["order_submission_allowed"] is False
    assert matrix["no_live_order_sent"] is True


def test_launch_execution_matrix_flags_manual_safe_default_alignment_repair_when_decisions_missing() -> None:
    matrix = watch._launch_execution_matrix(
        generated_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        launch_progress_scorecard={
            "no_live_order_sent": True,
            "critical_path_scorecard": {
                "launch_blocked_by": "conditional_overfit_operator_review",
                "paper_apply_ready_now": False,
                "next_open_gate": "conditional_overfit_operator_review",
                "no_live_order_sent": True,
            },
        },
        remaining_work_closure_summary={
            "actionability_partition": {
                "run_now_without_operator": [],
                "signal_waits": [],
                "time_waits": [],
                "dependency_blocked": [],
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
        operator_review_resolution_plan={
            "manual_batch_handoff": {
                "status": "operator_review_batch_waiting_for_operator_inputs",
                "batch_fingerprint": "abc",
                "batch_order": [
                    {
                        "review_kind": "conditional_overfit",
                        "target_gate": "conditional_overfit_operator_review",
                        "candidate_recipe_id": "candidate",
                        "active_operator_review_report": "review.json",
                        "ready_for_operator_dry_run_template": True,
                        "contract_accept_blockers_before_write": [
                            "operator_required_fields_still_empty"
                        ],
                        "next_manual_action": "repair_missing_decision_options",
                        "safe_default_if_uncertain": "reject",
                        "decision_options": [],
                        "validation_command": "validate",
                        "after_write_required_actions": ["rerun_launch_shadow_watch"],
                        "no_live_order_sent": True,
                    }
                ],
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
        command_consistency_audit={
            "status": "command_consistency_pass",
            "no_live_order_sent": True,
        },
    )

    assert matrix["manual_readiness_status"] == "manual_safe_default_alignment_repair_required"
    assert matrix["manual_safe_default_alignment_status"] == (
        "manual_safe_default_alignment_repair_required"
    )
    assert matrix["manual_safe_default_alignment_statuses"] == [
        "safe_default_decision_not_in_accepted_values"
    ]
    assert matrix["manual_safe_default_decisions"] == ["reject"]
    assert matrix["manual_safe_default_alignment_mismatch_count"] == 1
    assert matrix["manual_safe_default_alignment_next_step"] == (
        "repair_operator_input_safe_default_decision_options"
    )
    assert matrix["manual_safe_default_alignment_requires_repair"] is True
    decision_field = matrix["manual_actions"][0]["operator_input_contract"]["operator_input_form"][
        "decision_field"
    ]
    assert decision_field["accepted_values"] == []
    assert decision_field["safe_default_decision_if_uncertain"] == "reject"
    assert decision_field["safe_default_alignment"]["decision_is_accepted_value"] is False
    assert decision_field["safe_default_alignment"]["auto_decision_allowed"] is False
    assert matrix["auto_decision_allowed"] is False
    assert matrix["order_submission_allowed"] is False
    assert matrix["no_live_order_sent"] is True


def test_launch_execution_matrix_prioritizes_due_safe_auto_action_over_future_schedule() -> None:
    matrix = watch._launch_execution_matrix(
        generated_at=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
        launch_progress_scorecard={
            "no_live_order_sent": True,
            "critical_path_scorecard": {
                "paper_apply_blocked_by": "current_fresh_signal",
                "next_open_gate": "current_fresh_signal",
                "paper_apply_ready_now": False,
                "no_live_order_sent": True,
            },
        },
        remaining_work_closure_summary={
            "actionability_partition": {
                "run_now_without_operator": [
                    {
                        "action_type": "monitor_fresh_signal",
                        "target_gate": "current_fresh_signal",
                        "priority": 20,
                        "command": "future-monitor",
                        "execute_after_kst": "2026-01-01T09:30:00+09:00",
                        "safe_to_auto_run_without_operator": True,
                        "no_live_order_sent": True,
                    },
                    {
                        "action_type": "continue_no_live_shadow_watch",
                        "target_gate": "shadow_runtime_24h_observed",
                        "priority": 40,
                        "command": "ready-watch",
                        "execute_after_kst": None,
                        "safe_to_auto_run_without_operator": True,
                        "no_live_order_sent": True,
                    },
                    {
                        "action_type": "capture_due_quote_window",
                        "target_gate": "microstructure_calendar_day_coverage",
                        "priority": 30,
                        "command": "due-quote",
                        "execute_after_kst": "2026-01-01T09:00:00+09:00",
                        "safe_to_auto_run_without_operator": True,
                        "no_live_order_sent": True,
                    },
                ],
                "signal_waits": [],
                "time_waits": [],
                "dependency_blocked": [],
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
        operator_review_resolution_plan={
            "manual_batch_handoff": {"batch_order": [], "no_live_order_sent": True},
            "no_live_order_sent": True,
        },
        command_consistency_audit={
            "status": "command_consistency_pass",
            "no_live_order_sent": True,
        },
    )

    assert matrix["safe_auto_action_count"] == 3
    assert matrix["ready_safe_auto_action_count"] == 2
    assert matrix["overdue_safe_auto_action_count"] == 1
    assert matrix["covered_due_safe_auto_action_count"] == 0
    assert matrix["uncovered_ready_safe_auto_action_count"] == 2
    assert matrix["uncovered_overdue_safe_auto_action_count"] == 1
    assert matrix["scheduled_safe_auto_action_count"] == 1
    assert matrix["safe_auto_coverage_status"] == "overdue_safe_auto_actions_uncovered"
    assert matrix["max_overdue_minutes"] == 10.0
    assert matrix["urgency_status"] == "overdue_safe_auto_action_ready"
    assert matrix["primary_urgency"] == "overdue_safe_auto"
    assert [item["action_type"] for item in matrix["overdue_safe_auto_actions"]] == [
        "capture_due_quote_window"
    ]
    assert [item["action_type"] for item in matrix["scheduled_safe_auto_actions"]] == [
        "monitor_fresh_signal"
    ]
    assert matrix["next_scheduled_safe_auto_kst"] == "2026-01-01T09:30:00+09:00"
    assert matrix["next_scheduled_safe_auto_wait_minutes"] == 20.0
    assert matrix["primary_next_step"]["action_type"] == "capture_due_quote_window"
    assert matrix["primary_next_step"]["ready_now"] is True
    assert matrix["primary_next_step"]["due_status"] == "ready_due_or_overdue"
    assert matrix["primary_next_step"]["overdue_minutes"] == 10.0
    assert matrix["primary_effective_next_step"]["action_type"] == "capture_due_quote_window"
    assert matrix["primary_effective_next_step"]["covered_due_by_current_iteration"] is False
    future_row = next(
        item for item in matrix["safe_auto_actions"] if item["action_type"] == "monitor_fresh_signal"
    )
    assert future_row["ready_now"] is False
    assert future_row["due_status"] == "scheduled_future"
    assert future_row["wait_minutes"] == 20.0
    assert matrix["order_submission_allowed"] is False
    assert matrix["no_live_order_sent"] is True


def test_launch_execution_matrix_marks_due_safe_auto_covered_by_current_iteration() -> None:
    matrix = watch._launch_execution_matrix(
        generated_at=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
        launch_progress_scorecard={
            "no_live_order_sent": True,
            "critical_path_scorecard": {
                "paper_apply_blocked_by": "current_fresh_signal",
                "next_open_gate": "current_fresh_signal",
                "paper_apply_ready_now": False,
                "no_live_order_sent": True,
            },
        },
        remaining_work_closure_summary={
            "actionability_partition": {
                "run_now_without_operator": [
                    {
                        "action_type": "monitor_fresh_signal",
                        "target_gate": "current_fresh_signal",
                        "priority": 20,
                        "command": "monitor",
                        "execute_after_kst": "2026-01-01T09:00:00+09:00",
                        "safe_to_auto_run_without_operator": True,
                        "no_live_order_sent": True,
                    },
                    {
                        "action_type": "continue_no_live_shadow_watch",
                        "target_gate": "shadow_runtime_24h_observed",
                        "priority": 40,
                        "command": "watch",
                        "execute_after_kst": None,
                        "safe_to_auto_run_without_operator": True,
                        "no_live_order_sent": True,
                    },
                ],
                "signal_waits": [
                    {
                        "problem_id": "current_fresh_signal",
                        "status": "waiting_for_realtime_fresh_signal",
                        "next_monitor_utc": "2026-01-01T00:15:00+00:00",
                        "next_monitor_kst": "2026-01-01T09:15:00+09:00",
                        "raw_next_monitor_kst": "2026-01-01T09:00:00+09:00",
                        "covered_next_recheck_after_kst": "2026-01-01T09:15:00+09:00",
                        "next_monitor_source": (
                            "current_iteration_coverage.recommended_next_recheck_after"
                        ),
                        "next_monitor_retimestampted_after_current_iteration": True,
                        "monitor_command": "monitor",
                        "non_substitutable": True,
                        "no_live_order_sent": True,
                    }
                ],
                "time_waits": [],
                "dependency_blocked": [],
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
        operator_review_resolution_plan={
            "manual_batch_handoff": {"batch_order": [], "no_live_order_sent": True},
            "no_live_order_sent": True,
        },
        command_consistency_audit={
            "status": "command_consistency_pass",
            "no_live_order_sent": True,
        },
        latest_run={
            "signal_wait_plan": {
                "status": "blocked_waiting_for_fresh_signal",
                "fresh_signal": False,
                "recommended_monitor_interval_minutes": 5.0,
                "no_live_order_sent": True,
            },
            "paper_bridge_apply_gate": {
                "fresh_signal": False,
                "can_request_paper_apply_now": False,
                "no_live_order_sent": True,
            },
            "decision_state": {"signal_stale": True},
            "no_live_order_sent": True,
        },
    )

    assert matrix["overdue_safe_auto_action_count"] == 1
    assert matrix["covered_due_safe_auto_action_count"] == 2
    assert matrix["uncovered_ready_safe_auto_action_count"] == 0
    assert matrix["uncovered_overdue_safe_auto_action_count"] == 0
    assert matrix["safe_auto_coverage_status"] == (
        "all_due_safe_auto_actions_covered_by_current_iteration"
    )
    assert matrix["effective_urgency_status"] == (
        "safe_auto_due_covered_this_iteration_waiting_only"
    )
    assert matrix["effective_primary_urgency"] == "wait"
    assert matrix["primary_effective_next_step"]["step_type"] == "realtime_signal_wait"
    assert matrix["primary_effective_next_step"]["next_monitor_kst"] == (
        "2026-01-01T09:15:00+09:00"
    )
    assert matrix["primary_effective_next_step"]["raw_next_monitor_kst"] == (
        "2026-01-01T09:00:00+09:00"
    )
    assert matrix["primary_effective_next_step"]["covered_next_recheck_after_kst"] == (
        "2026-01-01T09:15:00+09:00"
    )
    assert (
        matrix["primary_effective_next_step"][
            "next_monitor_retimestampted_after_current_iteration"
        ]
        is True
    )
    monitor = next(
        item for item in matrix["safe_auto_actions"] if item["action_type"] == "monitor_fresh_signal"
    )
    assert monitor["due_status"] == "ready_due_or_overdue"
    assert monitor["effective_due_status"] == "covered_this_iteration"
    assert monitor["covered_due_by_current_iteration"] is True
    assert monitor["current_iteration_coverage"]["status"] == "covered_fresh_signal_still_waiting"
    assert monitor["current_iteration_coverage"]["paper_apply_available_after_coverage"] is False
    assert monitor["current_iteration_coverage"]["recommended_next_recheck_after_kst"] == (
        "2026-01-01T09:15:00+09:00"
    )
    assert matrix["order_submission_allowed"] is False
    assert matrix["no_live_order_sent"] is True


def test_launch_execution_matrix_effective_manual_next_step_has_due_status_after_safe_auto_covered() -> None:
    matrix = watch._launch_execution_matrix(
        generated_at=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
        launch_progress_scorecard={
            "no_live_order_sent": True,
            "critical_path_scorecard": {
                "paper_apply_blocked_by": "current_fresh_signal",
                "next_open_gate": "current_fresh_signal",
                "paper_apply_ready_now": False,
                "no_live_order_sent": True,
            },
        },
        remaining_work_closure_summary={
            "actionability_partition": {
                "run_now_without_operator": [
                    {
                        "action_type": "monitor_fresh_signal",
                        "target_gate": "current_fresh_signal",
                        "priority": 20,
                        "command": "monitor",
                        "execute_after_kst": "2026-01-01T09:00:00+09:00",
                        "safe_to_auto_run_without_operator": True,
                        "no_live_order_sent": True,
                    }
                ],
                "signal_waits": [
                    {
                        "problem_id": "current_fresh_signal",
                        "status": "waiting_for_realtime_fresh_signal",
                        "next_monitor_kst": "2026-01-01T09:15:00+09:00",
                        "monitor_command": "monitor",
                        "non_substitutable": True,
                        "no_live_order_sent": True,
                    }
                ],
                "time_waits": [],
                "dependency_blocked": [],
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
        operator_review_resolution_plan={
            "manual_batch_handoff": {
                "status": "operator_review_batch_waiting_for_operator_inputs",
                "batch_order": [
                    {
                        "review_kind": "conditional_overfit",
                        "target_gate": "conditional_overfit_operator_review",
                        "candidate_recipe_id": "candidate",
                        "active_operator_review_report": "review.json",
                        "ready_for_operator_dry_run_template": True,
                        "contract_accept_blockers_before_write": [
                            "operator_required_fields_still_empty"
                        ],
                        "next_manual_action": "choose_accept_or_reject",
                        "safe_default_if_uncertain": "reject",
                        "decision_options": [
                            {"decision": "accept", "no_live_order_sent": True},
                            {"decision": "reject", "no_live_order_sent": True},
                        ],
                        "validation_command": "validate",
                        "after_write_required_actions": ["rerun_launch_shadow_watch"],
                        "no_live_order_sent": True,
                    }
                ],
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
        command_consistency_audit={
            "status": "command_consistency_pass",
            "no_live_order_sent": True,
        },
        latest_run={
            "signal_wait_plan": {
                "status": "blocked_waiting_for_fresh_signal",
                "fresh_signal": False,
                "recommended_monitor_interval_minutes": 5.0,
                "no_live_order_sent": True,
            },
            "paper_bridge_apply_gate": {
                "fresh_signal": False,
                "can_request_paper_apply_now": False,
                "no_live_order_sent": True,
            },
            "decision_state": {"signal_stale": True},
            "no_live_order_sent": True,
        },
    )

    assert matrix["covered_due_safe_auto_action_count"] == 1
    assert matrix["safe_auto_ready_count"] == 1
    assert matrix["safe_auto_effective_ready_count"] == 0
    assert matrix["manual_ready_count"] == 1
    assert matrix["manual_due_count"] == 1
    assert matrix["manual_wait_count"] == 0
    assert matrix["manual_effective_due_count"] == 1
    assert matrix["effective_urgency_status"] == (
        "safe_auto_due_covered_this_iteration_manual_action_available"
    )
    assert matrix["effective_primary_urgency"] == "manual_operator_review"
    effective_step = matrix["primary_effective_next_step"]
    assert effective_step["step_type"] == "manual_operator_review"
    assert effective_step["target_gate"] == "conditional_overfit_operator_review"
    assert effective_step["ready_now"] is True
    assert effective_step["due_status"] == "operator_input_required_now"
    assert effective_step["effective_due_status"] == "operator_input_required_now"
    assert effective_step["manual_action_due_now"] is True
    assert effective_step["order_submission_allowed"] is False
    assert matrix["no_live_order_sent"] is True


def test_launch_execution_matrix_exposes_raw_safe_auto_actions_when_effective_queue_is_empty() -> None:
    matrix = watch._launch_execution_matrix(
        generated_at=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
        launch_progress_scorecard={
            "no_live_order_sent": True,
            "critical_path_scorecard": {
                "paper_apply_blocked_by": "current_fresh_signal",
                "next_open_gate": "current_fresh_signal",
                "paper_apply_ready_now": False,
                "no_live_order_sent": True,
            },
        },
        remaining_work_closure_summary={
            "safe_automation_now_count": 2,
            "safe_effective_automation_now_count": 0,
            "safe_covered_automation_now_count": 2,
            "safe_raw_useful_automation_now_count": 2,
            "raw_automation_now_usefulness": [
                {
                    "action_type": "monitor_fresh_signal",
                    "target_gate": "current_fresh_signal",
                    "priority": 20,
                    "command": "monitor",
                    "useful_now": True,
                    "safe_to_auto_run_without_operator": True,
                    "no_live_order_sent": True,
                },
                {
                    "action_type": "continue_no_live_shadow_watch",
                    "target_gate": "shadow_runtime_24h_observed",
                    "priority": 40,
                    "command": "watch",
                    "useful_now": True,
                    "safe_to_auto_run_without_operator": True,
                    "no_live_order_sent": True,
                },
            ],
            "primary_covered_automation_action": {
                "action_type": "monitor_fresh_signal",
                "target_gate": "current_fresh_signal",
                "command": "monitor",
                "useful_now": True,
                "no_live_order_sent": True,
            },
            "actionability_partition": {
                "run_now_without_operator": [],
                "signal_waits": [
                    {
                        "problem_id": "current_fresh_signal",
                        "status": "waiting_for_realtime_fresh_signal",
                        "next_monitor_kst": "2026-01-01T09:15:00+09:00",
                        "monitor_command": "monitor",
                        "non_substitutable": True,
                        "no_live_order_sent": True,
                    }
                ],
                "time_waits": [],
                "dependency_blocked": [],
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
        operator_review_resolution_plan={
            "manual_batch_handoff": {
                "status": "operator_review_batch_waiting_for_operator_inputs",
                "batch_order": [
                    {
                        "review_kind": "conditional_overfit",
                        "target_gate": "conditional_overfit_operator_review",
                        "candidate_recipe_id": "candidate",
                        "active_operator_review_report": "review.json",
                        "ready_for_operator_dry_run_template": True,
                        "contract_accept_blockers_before_write": [
                            "operator_required_fields_still_empty"
                        ],
                        "next_manual_action": "choose_accept_or_reject",
                        "safe_default_if_uncertain": "reject",
                        "decision_options": [
                            {"decision": "accept", "no_live_order_sent": True},
                            {"decision": "reject", "no_live_order_sent": True},
                        ],
                        "validation_command": "validate",
                        "after_write_required_actions": ["rerun_launch_shadow_watch"],
                        "no_live_order_sent": True,
                    }
                ],
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
        command_consistency_audit={
            "status": "command_consistency_pass",
            "no_live_order_sent": True,
        },
        latest_run={
            "signal_wait_plan": {
                "status": "blocked_waiting_for_fresh_signal",
                "fresh_signal": False,
                "recommended_monitor_interval_minutes": 5.0,
                "no_live_order_sent": True,
            },
            "paper_bridge_apply_gate": {
                "fresh_signal": False,
                "can_request_paper_apply_now": False,
                "no_live_order_sent": True,
            },
            "decision_state": {"signal_stale": True},
            "no_live_order_sent": True,
        },
    )

    assert matrix["status"] == "manual_operator_reviews_required"
    assert matrix["effective_urgency_status"] == "manual_operator_action_available"
    assert matrix["safe_auto_action_count"] == 0
    assert matrix["effective_safe_auto_action_count"] == 0
    assert matrix["raw_safe_auto_action_count"] == 2
    assert matrix["raw_useful_safe_auto_action_count"] == 2
    assert matrix["covered_raw_safe_auto_action_count"] == 2
    assert matrix["primary_covered_raw_safe_auto_action"]["action_type"] == (
        "monitor_fresh_signal"
    )
    assert matrix["safe_auto_count_scope"] == (
        "effective_actionability_partition_excludes_current_iteration_covered_actions"
    )
    assert [item["action_type"] for item in matrix["raw_safe_auto_actions"]] == [
        "monitor_fresh_signal",
        "continue_no_live_shadow_watch",
    ]
    assert matrix["manual_action_count"] == 1
    assert matrix["manual_ready_count"] == 1
    assert matrix["manual_effective_due_count"] == 1
    assert matrix["primary_effective_next_step"]["step_type"] == "manual_operator_review"
    assert matrix["auto_apply_allowed"] is False
    assert matrix["order_submission_allowed"] is False
    assert matrix["no_live_order_sent"] is True


def test_command_consistency_audit_detects_shadow_runtime_command_mismatch() -> None:
    audit = watch._command_consistency_audit(
        safe_next_action_plan={},
        remaining_work_closure_summary={
            "actionability_partition": {
                "run_now_without_operator": [
                    {
                        "action_type": "continue_no_live_shadow_watch",
                        "target_gate": "shadow_runtime_24h_observed",
                        "command": "watch-canonical --report-dir reports/watch",
                        "no_live_order_sent": True,
                    }
                ],
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
        next_material_progress_plan={
            "events": [
                {
                    "event_type": "shadow_runtime_observation",
                    "command": "monitor-stale --report-dir reports/monitor",
                    "no_live_order_sent": True,
                }
            ],
            "no_live_order_sent": True,
        },
        scheduled_command_projection={},
        signal_monitor={},
    )

    parity = audit["shadow_runtime_command_parity"]
    assert audit["status"] == "command_consistency_mismatch_detected"
    assert parity["status"] == "shadow_runtime_command_mismatch"
    assert parity["canonical_source"] == (
        "remaining_work_closure_summary.actionability_partition.run_now_without_operator.shadow_runtime"
    )
    assert parity["canonical_command"] == "watch-canonical --report-dir reports/watch"
    assert parity["canonical_report_dir"] == "reports/watch"
    assert parity["mismatch_count"] == 1
    assert parity["mismatches"][0]["source"] == (
        "next_material_progress_plan.shadow_runtime_observation.command"
    )
    assert parity["mismatches"][0]["report_dir"] == "reports/monitor"
    assert parity["order_submission_allowed"] is False
    assert parity["no_live_order_sent"] is True


def test_command_consistency_audit_detects_operator_review_command_mismatch() -> None:
    audit = watch._command_consistency_audit(
        safe_next_action_plan={},
        remaining_work_closure_summary={
            "actionability_partition": {
                "manual_now": [
                    {
                        "dry_run_command_template": "canonical-review --dry-run",
                        "no_live_order_sent": True,
                    }
                ],
                "no_live_order_sent": True,
            },
            "primary_operator_decision_action": {
                "operator_decision_packet": {
                    "decision_dry_run_command_template": "canonical-review --dry-run",
                    "no_live_order_sent": True,
                },
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
        next_material_progress_plan={
            "events": [
                {
                    "event_type": "operator_review_decisions",
                    "command": "stale-review --dry-run",
                    "no_live_order_sent": True,
                }
            ],
            "no_live_order_sent": True,
        },
        scheduled_command_projection={},
        signal_monitor={},
    )

    parity = audit["operator_review_command_parity"]
    assert audit["status"] == "command_consistency_mismatch_detected"
    assert parity["status"] == "operator_review_command_mismatch"
    assert parity["canonical_source"] == (
        "remaining_work_closure_summary.actionability_partition.manual_now"
    )
    assert parity["canonical_command"] == "canonical-review --dry-run"
    assert parity["mismatch_count"] == 1
    assert parity["mismatches"][0]["source"] == (
        "next_material_progress_plan.operator_review_decisions.command"
    )
    assert audit["auto_execute_allowed"] is False
    assert audit["auto_decision_allowed"] is False
    assert audit["order_submission_allowed"] is False
    assert audit["no_live_order_sent"] is True


def test_execution_parity_eta_plan_uses_signal_cadence_without_substitution() -> None:
    plan = watch._execution_parity_eta_plan(
        execution_parity_plan={
            "required_samples": 20,
            "eligible_journal_rows": 0,
            "missing_samples": 20,
            "estimated_future_paper_apply_events_needed": 20,
            "estimated_events_needed_after_current_creditable_apply": 19,
            "sample_credit_per_completed_paper_apply_event": 1,
            "will_credit_current_apply_after_operator_review": True,
            "currently_creditable_actions": ["remove"],
            "next_creditable_event_types": ["add", "remove"],
            "fresh_signal": True,
            "paper_apply_available_now": True,
            "non_substitutable": True,
            "backtest_substitution_allowed": False,
        },
        signal_wait_plan={
            "expected_days_per_add": 2.5,
            "expected_add_interval_hours": 60.0,
            "median_add_gap_hours": 48.0,
            "latest_add_age_to_median_gap": 0.25,
            "cadence_lag_level": "within_recent_add_cadence",
        },
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    assert plan["status"] == "eta_from_add_only_signal_cadence"
    assert plan["selected_eta_scenario"] == "conservative_add_only"
    assert plan["selected_eta_reason"] == "fallback_to_add_only_cadence"
    assert plan["cadence_source"] == "signal_wait_plan.expected_days_per_add"
    assert plan["estimated_days_at_current_cadence"] == 50.0
    assert plan["estimated_completion_utc"] == "2026-02-20T12:00:00+00:00"
    assert plan["eta_scenarios"]["conservative_add_only"]["estimated_days"] == 50.0
    assert plan["eta_scenarios"]["all_creditable_events"]["available"] is False
    assert plan["estimated_events_needed_after_current_creditable_apply"] == 19
    assert plan["will_credit_current_apply_after_operator_review"] is True
    assert plan["currently_creditable_actions"] == ["remove"]
    assert plan["non_substitutable"] is True
    assert plan["backtest_substitution_allowed"] is False
    assert "not by forced entries or backtest rows" in plan["caveat"]
    assert plan["order_submission_allowed"] is False
    assert plan["no_live_order_sent"] is True

    summary = watch._execution_parity_journal_eta_summary(plan)
    assert summary["status"] == "eta_from_add_only_signal_cadence"
    assert summary["selected_eta_scenario"] == "conservative_add_only"
    assert summary["estimated_days_at_current_cadence"] == 50.0
    assert summary["estimated_completion_kst"] == "2026-02-20T21:00:00+09:00"
    assert summary["estimated_events_needed_after_current_creditable_apply"] == 19
    assert summary["fresh_signal"] is True
    assert summary["paper_apply_available_now"] is True
    assert summary["will_credit_current_apply_after_operator_review"] is True
    assert summary["currently_creditable_actions"] == ["remove"]
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_execution_parity_eta_plan_uses_all_event_cadence_when_add_remove_credit() -> None:
    plan = watch._execution_parity_eta_plan(
        execution_parity_plan={
            "required_samples": 20,
            "eligible_journal_rows": 0,
            "missing_samples": 20,
            "estimated_future_paper_apply_events_needed": 20,
            "estimated_events_needed_after_current_creditable_apply": 20,
            "sample_credit_per_completed_paper_apply_event": 1,
            "next_creditable_event_types": ["add", "remove"],
            "non_substitutable": True,
            "backtest_substitution_allowed": False,
        },
        signal_wait_plan={
            "expected_days_per_event": 1.0,
            "expected_event_interval_hours": 24.0,
            "median_gap_hours": 18.0,
            "expected_days_per_add": 2.5,
            "expected_add_interval_hours": 60.0,
            "median_add_gap_hours": 48.0,
            "latest_age_to_median_gap": 0.5,
            "latest_add_age_to_median_gap": 0.25,
            "event_wait_state": "within_recent_signal_gap_distribution",
            "cadence_lag_level": "within_recent_add_cadence",
            "bridge_event_count": 80,
            "add_event_count": 32,
            "remove_event_count": 48,
        },
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    assert plan["status"] == "eta_from_creditable_event_cadence"
    assert plan["selected_eta_scenario"] == "all_creditable_events"
    assert plan["selected_eta_reason"] == "accepted_actions_include_add_and_remove"
    assert plan["cadence_source"] == "signal_wait_plan.expected_days_per_event"
    assert plan["estimated_days_at_current_cadence"] == 20.0
    assert plan["estimated_completion_utc"] == "2026-01-21T12:00:00+00:00"
    assert plan["eta_scenarios"]["all_creditable_events"]["estimated_days"] == 20.0
    assert plan["eta_scenarios"]["conservative_add_only"]["estimated_days"] == 50.0
    assert plan["bridge_event_count"] == 80
    assert plan["remove_event_count"] == 48
    assert plan["non_substitutable"] is True
    assert plan["order_submission_allowed"] is False
    assert plan["no_live_order_sent"] is True


def test_signal_monitor_cadence_alignment_passes_inside_fresh_window() -> None:
    current = datetime(2026, 1, 1, 12, 15, tzinfo=UTC)
    alignment = watch._signal_monitor_cadence_alignment(
        previous_completed_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        current_completed_at=current,
        signal_wait_plan={
            "recommended_monitor_interval_minutes": 15,
            "signal_freshness_capture_window_minutes": 15.0,
            "monitor_interval_capped_by_signal_freshness": True,
            "monitor_signal_age_alignment": "capped_to_fresh_signal_window",
            "next_monitor_after_utc": current.isoformat(),
        },
    )

    assert alignment["status"] == "aligned"
    assert alignment["gap_minutes"] == 15.0
    assert alignment["warning"] is None
    assert alignment["recommended_monitor_interval_minutes"] == 15.0
    assert alignment["monitor_interval_capped_by_signal_freshness"] is True
    assert alignment["order_submission_allowed"] is False
    assert alignment["no_live_order_sent"] is True


def test_signal_monitor_cadence_alignment_warns_after_fresh_window_gap() -> None:
    alignment = watch._signal_monitor_cadence_alignment(
        previous_completed_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        current_completed_at=datetime(2026, 1, 1, 12, 20, 1, tzinfo=UTC),
        signal_wait_plan={
            "recommended_monitor_interval_minutes": 15,
            "signal_freshness_capture_window_minutes": 15.0,
            "monitor_interval_capped_by_signal_freshness": True,
            "monitor_signal_age_alignment": "capped_to_fresh_signal_window",
        },
    )

    assert alignment["status"] == "monitor_gap_exceeded"
    assert alignment["gap_minutes"] == 20.017
    assert alignment["warning"] == "signal_monitor_gap_exceeded_fresh_capture_cadence"
    assert alignment["warning_threshold_minutes"] == 18.0
    assert alignment["order_submission_allowed"] is False
    assert alignment["no_live_order_sent"] is True


def test_signal_monitor_summary_uses_current_iteration_recheck_after_covered_monitor() -> None:
    summary = watch._signal_monitor_summary(
        signal_wait_plan={
            "status": "blocked_waiting_for_fresh_signal",
            "fresh_signal": False,
            "recommended_monitor_interval_minutes": 5.0,
            "signal_freshness_capture_window_minutes": 15.0,
            "monitor_interval_capped_by_signal_freshness": True,
            "monitor_signal_age_alignment": "capped_to_fresh_signal_window",
            "next_monitor_after_utc": "2026-01-01T00:05:00+00:00",
            "next_monitor_after_kst": "2026-01-01T09:05:00+09:00",
            "command": "monitor --report-dir reports/raw",
            "no_live_order_sent": True,
        },
        cadence_alignment={
            "status": "aligned",
            "gap_minutes": 5.0,
            "monitor_interval_capped_by_signal_freshness": True,
            "no_live_order_sent": True,
        },
        safe_next_action_plan={
            "primary_action": {
                "action_type": "monitor_fresh_signal",
                "command": "monitor --report-dir reports/safe-next",
                "execute_after_utc": "2026-01-01T00:05:00+00:00",
                "execute_after_kst": "2026-01-01T09:05:00+09:00",
                "covered_by_current_iteration": True,
                "covered_due_by_current_iteration": True,
                "current_iteration_coverage": {
                    "status": "covered_fresh_signal_still_waiting",
                    "recommended_next_recheck_after_kst": "2026-01-01T09:15:00+09:00",
                    "no_live_order_sent": True,
                },
                "no_live_order_sent": True,
            },
            "no_live_order_sent": True,
        },
    )

    assert summary["command"] == "monitor --report-dir reports/safe-next"
    assert summary["next_monitor_after_source"] == (
        "current_iteration_coverage.recommended_next_recheck_after"
    )
    assert summary["next_monitor_after_utc"] == "2026-01-01T00:15:00+00:00"
    assert summary["next_monitor_after_kst"] == "2026-01-01T09:15:00+09:00"
    assert summary["raw_next_monitor_after_utc"] == "2026-01-01T00:05:00+00:00"
    assert summary["raw_next_monitor_after_kst"] == "2026-01-01T09:05:00+09:00"
    assert summary["covered_next_recheck_after_utc"] == "2026-01-01T00:15:00+00:00"
    assert summary["covered_next_recheck_after_kst"] == "2026-01-01T09:15:00+09:00"
    assert summary["next_monitor_retimestampted_after_current_iteration"] is True
    assert summary["covered_by_current_iteration"] is True
    assert summary["covered_due_by_current_iteration"] is True
    assert summary["report_dir_retimestampted_to_safe_next_action"] is True
    assert summary["order_submission_allowed"] is False
    assert summary["no_live_order_sent"] is True


def test_paper_apply_parity_review_state_blocks_when_missing_after_recent_apply() -> None:
    state = watch._paper_apply_parity_review_state(
        recent_paper_apply={
            "status": "available",
            "generated_at": "2026-01-01T12:05:00+00:00",
            "source_report": "reports/apply.json",
        },
        recent_paper_review={
            "status": "available",
            "generated_at": "2026-01-01T12:00:00+00:00",
            "source_report": "reports/pre.json",
        },
        recent_parity_review={"status": "unavailable"},
    )

    assert state["status"] == "missing_after_recent_paper_apply"
    assert state["blocks_next_paper_apply"] is True
    assert state["source_report"] == "reports/apply.json"
    assert state["blockers"] == ["post_apply_parity_review_missing"]
    assert state["next_actions"] == ["run_post_apply_parity_review_before_next_paper_apply"]
    assert "--before-evidence-report reports/pre.json" in state["recommended_command"]
    assert "--after-evidence-report reports/apply.json" in state["recommended_command"]
    assert state["no_live_order_sent"] is True


def test_paper_apply_parity_review_state_blocks_when_stale_after_recent_apply() -> None:
    state = watch._paper_apply_parity_review_state(
        recent_paper_apply={
            "status": "available",
            "generated_at": "2026-01-01T12:10:00+00:00",
            "source_report": "reports/apply_latest.json",
        },
        recent_paper_review={
            "status": "available",
            "generated_at": "2026-01-01T12:00:00+00:00",
            "source_report": "reports/pre_latest.json",
        },
        recent_parity_review={
            "status": "paper_apply_parity_credit_confirmed",
            "generated_at": "2026-01-01T12:06:00+00:00",
            "source_report": "reports/parity_old.json",
            "blocks_next_paper_apply": False,
            "no_live_order_sent": True,
        },
    )

    assert state["status"] == "stale_after_recent_paper_apply"
    assert state["blocks_next_paper_apply"] is True
    assert state["recent_parity_review_report"] == "reports/parity_old.json"
    assert state["blockers"] == ["post_apply_parity_review_stale"]
    assert state["next_actions"] == ["rerun_post_apply_parity_review_for_latest_paper_apply"]
    assert "--after-evidence-report reports/apply_latest.json" in state["recommended_command"]
    assert state["no_live_order_sent"] is True


def test_blocker_plan_suppresses_repeated_remove_paper_apply_after_no_open_plan() -> None:
    plan = watch._blocker_resolution_plan(
        latest={
            "paper_bridge_apply_gate": {
                "bridge_action": "remove",
                "fresh_signal": True,
                "can_request_paper_apply_now": True,
            },
            "collection_progress": {
                "paper_fill_rows": 0,
            },
            "launch_readiness": {
                "blocking_gates": [
                    {
                        "gate": "real_paper_lifecycle_rows",
                        "blocker": "real_paper_lifecycle_rows_missing",
                        "next_action": "apply_paper_bridge_only_after_fresh_signal_and_verified_backup",
                    }
                ],
                "operator_commands": {
                    "paper_bridge_dry_run": "dry-run",
                    "paper_apply_only_after_fresh_signal": "paper-apply",
                },
            },
        },
        progress={},
        runtime_progress={},
        risk_caps={},
        microstructure_watch={},
        operator_handoff={
            "paper_apply_allowed_now": False,
            "paper_handoff_status": "paper_apply_review_available",
            "paper_dry_run_command": "dry-run",
            "paper_apply_command": "paper-apply",
            "paper_apply_retry_blocker": {
                "blocked": True,
                "reason": "recent_remove_paper_apply_found_no_open_v6_paper_plan",
                "source_report": "reports/recent.json",
                "next_monitor_after_utc": "2026-01-01T12:15:00+00:00",
            },
        },
    )

    item = plan[0]
    assert item["gate"] == "real_paper_lifecycle_rows"
    assert item["can_resolve_now"] is False
    assert item["command"] is None
    assert item["monitor_command"] == "dry-run"
    assert item["next_monitor_after_utc"] == "2026-01-01T12:15:00+00:00"
    assert item["paper_apply_retry_blocked"] is True
    assert item["paper_apply_retry_blocker"]["source_report"] == "reports/recent.json"
    assert item["reason"] == "recent_remove_paper_apply_found_no_open_v6_paper_plan"
    assert item["fresh_signal"] is True
    assert item["order_submission_allowed"] is False


def test_blocker_plan_treats_current_remove_without_open_plan_as_wait_state() -> None:
    plan = watch._blocker_resolution_plan(
        latest={
            "paper_bridge_apply_gate": {
                "status": "blocked_no_open_v6_paper_plan",
                "bridge_action": "remove",
                "fresh_signal": True,
                "can_request_paper_apply_now": False,
                "remove_plan_precheck": {
                    "status": "no_open_v6_paper_plan",
                    "open_plan_count": 0,
                },
            },
            "collection_progress": {
                "paper_fill_rows": 0,
            },
            "launch_readiness": {
                "blocking_gates": [
                    {
                        "gate": "real_paper_lifecycle_rows",
                        "blocker": "real_paper_lifecycle_rows_missing",
                        "next_action": "apply_paper_bridge_only_after_fresh_signal_and_verified_backup",
                    }
                ],
                "operator_commands": {
                    "paper_bridge_dry_run": "dry-run",
                    "paper_apply_only_after_fresh_signal": "paper-apply",
                },
            },
            "execution_parity_collection_plan": {
                "status": "waiting_for_open_paper_plan_after_remove_signal",
                "estimated_future_paper_apply_events_needed": 20,
                "estimated_events_needed_after_current_creditable_apply": 20,
                "will_credit_current_apply_after_operator_review": False,
                "currently_creditable_actions": [],
            },
        },
        progress={},
        runtime_progress={},
        risk_caps={},
        microstructure_watch={},
        operator_handoff={
            "paper_apply_allowed_now": False,
            "paper_handoff_status": "blocked_until_apply_gate_available",
            "paper_dry_run_command": "dry-run",
            "paper_apply_command": "paper-apply",
        },
    )

    item = plan[0]
    assert item["can_resolve_now"] is False
    assert item["command"] is None
    assert item["paper_apply_no_open_plan"] is True
    assert item["remove_plan_precheck"]["status"] == "no_open_v6_paper_plan"
    assert item["reason"] == "remove_signal_has_no_open_v6_paper_plan"
    assert item["execution_parity_will_credit_current_apply"] is False
    assert item["execution_parity_events_needed_after_current_apply"] == 20
    assert item["execution_parity_creditable_actions"] == []
    assert item["order_submission_allowed"] is False


def test_safe_next_action_schedules_next_add_signal_after_remove_apply_no_open_plan() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "real_paper_lifecycle_rows",
                "fresh_signal": True,
                "monitor_command": "dry-run-monitor",
                "next_monitor_after_utc": "2026-01-01T12:15:00+00:00",
                "paper_apply_retry_blocked": True,
                "paper_apply_retry_blocker": {
                    "blocked": True,
                    "reason": "recent_remove_paper_apply_found_no_open_v6_paper_plan",
                },
                "reason": "recent_remove_paper_apply_found_no_open_v6_paper_plan",
            },
            {
                "gate": "shadow_runtime_24h_observed",
                "reason": "requires_calendar_runtime_observation_not_backtest_substitution",
            },
        ],
        runtime_progress={"remaining_hours": 16.0, "progress_pct": 33.0},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    action = next(item for item in plan["actions"] if item["action_type"] == "paper_bridge_wait_for_next_add_signal")
    assert action["can_run_now"] is False
    assert action["execute_after_utc"] == "2026-01-01T12:15:00+00:00"
    assert action["command"] == "dry-run-monitor"
    assert action["priority"] == 20
    assert action["paper_apply_retry_blocker"]["blocked"] is True
    assert plan["next_scheduled_action"]["action_type"] == "paper_bridge_wait_for_next_add_signal"
    assert plan["no_live_order_sent"] is True


def test_safe_next_action_waits_when_current_remove_has_no_open_plan() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "real_paper_lifecycle_rows",
                "fresh_signal": True,
                "monitor_command": "dry-run-monitor",
                "paper_apply_no_open_plan": True,
                "remove_plan_precheck": {
                    "status": "no_open_v6_paper_plan",
                    "open_plan_count": 0,
                },
                "reason": "remove_signal_has_no_open_v6_paper_plan",
                "signal_freshness_capture_window_minutes": 15.0,
                "latest_add_ts": "2026-01-01T09:00:00+00:00",
                "latest_add_age_hours": 3.0,
                "latest_add_age_to_median_gap": 0.1,
                "add_wait_state": "within_recent_add_gap_distribution",
                "expected_days_per_add": 6.0,
                "expected_add_interval_hours": 144.0,
                "median_add_gap_hours": 72.0,
            }
        ],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    action = plan["primary_action"]
    assert action["action_type"] == "paper_bridge_wait_for_next_add_signal"
    assert action["can_run_now"] is False
    assert action["command"] == "dry-run-monitor"
    assert action["execute_after_utc"] == "2026-01-01T12:15:00+00:00"
    assert action["execute_after_kst"] == "2026-01-01T21:15:00+09:00"
    assert action["wait_minutes"] == 15.0
    assert action["recommended_monitor_interval_minutes"] == 15
    assert action["paper_apply_no_open_plan"] is True
    assert action["remove_plan_precheck"]["status"] == "no_open_v6_paper_plan"
    assert action["next_creditable_add_signal_plan"]["status"] == (
        "waiting_for_next_add_signal_or_existing_open_paper_plan"
    )
    assert action["next_creditable_add_signal_plan"]["expected_add_due"]["due_utc"] == (
        "2026-01-07T09:00:00+00:00"
    )
    assert action["next_creditable_add_signal_plan"]["median_add_due"]["due_utc"] == (
        "2026-01-04T09:00:00+00:00"
    )
    assert action["reason"] == "remove_signal_has_no_open_v6_paper_plan"
    assert action["order_submission_allowed"] is False
    assert action["no_live_order_sent"] is True
    assert plan["coordination_plan"]["status"] == "signal_or_add_monitor_active"
    assert plan["coordination_plan"]["primary_action_type"] == "paper_bridge_wait_for_next_add_signal"
    assert plan["coordination_plan"]["next_signal_or_add_monitor_kst"] == "2026-01-01T21:15:00+09:00"
    assert plan["coordination_plan"]["signal_monitor_interval_capped_by_freshness"] is True
    assert action["monitor_interval_capped_by_signal_freshness"] is True
    assert action["monitor_signal_age_alignment"] == "monitor_interval_capped_to_signal_freshness_window"
    assert plan["coordination_plan"]["no_live_order_sent"] is True


def test_safe_next_action_retimestamps_next_add_monitor_report_dir() -> None:
    stale_command = (
        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
        "--quote-samples-per-tick 0 --refresh-market-data-before-run --max-signal-age-minutes 15 "
        "--report-dir reports/validation/diagnostics/market_state_rotation_v6_launch_paper_dry_run_20260101_1200Z"
    )
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "real_paper_lifecycle_rows",
                "fresh_signal": True,
                "monitor_command": stale_command,
                "paper_apply_no_open_plan": True,
                "remove_plan_precheck": {
                    "status": "no_open_v6_paper_plan",
                    "open_plan_count": 0,
                },
                "reason": "remove_signal_has_no_open_v6_paper_plan",
                "signal_freshness_capture_window_minutes": 15.0,
                "latest_add_ts": "2026-01-01T09:00:00+00:00",
                "expected_add_interval_hours": 144.0,
                "median_add_gap_hours": 72.0,
            }
        ],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    action = plan["primary_action"]
    expected_dir = (
        "reports/validation/diagnostics/"
        "market_state_rotation_v6_launch_paper_dry_run_20260101_1215Z"
    )
    assert f"--report-dir {expected_dir}" in action["command"]
    assert f"--report-dir {expected_dir}" in action["next_creditable_add_signal_plan"]["monitor_command"]
    assert "market_state_rotation_v6_launch_paper_dry_run_20260101_1200Z" not in action["command"]
    assert action["execute_after_utc"] == "2026-01-01T12:15:00+00:00"
    assert action["no_live_order_sent"] is True


def test_safe_next_action_preserves_next_add_monitor_schedule_for_same_remove_event() -> None:
    command = (
        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
        "--quote-samples-per-tick 0 --refresh-market-data-before-run --max-signal-age-minutes 15 "
        "--report-dir reports/validation/diagnostics/market_state_rotation_v6_launch_paper_dry_run_20260101_1200Z"
    )
    previous_payload = {
        "safe_next_action_plan": {
            "primary_action": {
                "action_type": "paper_bridge_wait_for_next_add_signal",
                "execute_after_utc": "2026-01-01T12:15:00+00:00",
                "remove_plan_precheck": {
                    "source_event_key": "remove-event-1",
                    "status": "no_open_v6_paper_plan",
                },
                "next_creditable_add_signal_plan": {
                    "next_monitor_after_utc": "2026-01-01T12:15:00+00:00",
                    "no_live_order_sent": True,
                },
                "no_live_order_sent": True,
            }
        },
        "no_live_order_sent": True,
    }
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "real_paper_lifecycle_rows",
                "fresh_signal": True,
                "monitor_command": command,
                "paper_apply_no_open_plan": True,
                "remove_plan_precheck": {
                    "status": "no_open_v6_paper_plan",
                    "source_event_key": "remove-event-1",
                    "open_plan_count": 0,
                },
                "reason": "remove_signal_has_no_open_v6_paper_plan",
                "signal_freshness_capture_window_minutes": 15.0,
                "latest_add_ts": "2026-01-01T09:00:00+00:00",
            }
        ],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        previous_payload=previous_payload,
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 10, tzinfo=UTC),
    )

    action = plan["primary_action"]
    expected_dir = (
        "reports/validation/diagnostics/"
        "market_state_rotation_v6_launch_paper_dry_run_20260101_1215Z"
    )
    assert action["execute_after_utc"] == "2026-01-01T12:15:00+00:00"
    assert action["execute_after_kst"] == "2026-01-01T21:15:00+09:00"
    assert action["wait_minutes"] == 5.0
    assert action["can_run_now"] is False
    assert f"--report-dir {expected_dir}" in action["command"]
    assert action["next_creditable_add_signal_plan"]["schedule_preserved_from_previous_watch"] is True
    assert action["next_creditable_add_signal_plan"]["schedule_anchor"] == (
        "previous_watch_same_remove_source_event"
    )
    assert action["no_live_order_sent"] is True


def test_safe_next_action_marks_preserved_next_add_monitor_due() -> None:
    previous_payload = {
        "safe_next_action_plan": {
            "primary_action": {
                "action_type": "paper_bridge_wait_for_next_add_signal",
                "execute_after_utc": "2026-01-01T12:15:00+00:00",
                "remove_plan_precheck": {
                    "source_event_key": "remove-event-1",
                    "status": "no_open_v6_paper_plan",
                },
                "next_creditable_add_signal_plan": {
                    "next_monitor_after_utc": "2026-01-01T12:15:00+00:00",
                    "no_live_order_sent": True,
                },
                "no_live_order_sent": True,
            }
        },
        "no_live_order_sent": True,
    }
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "real_paper_lifecycle_rows",
                "fresh_signal": True,
                "monitor_command": "dry-run-monitor",
                "paper_apply_no_open_plan": True,
                "remove_plan_precheck": {
                    "status": "no_open_v6_paper_plan",
                    "source_event_key": "remove-event-1",
                    "open_plan_count": 0,
                },
                "reason": "remove_signal_has_no_open_v6_paper_plan",
                "signal_freshness_capture_window_minutes": 15.0,
            }
        ],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        previous_payload=previous_payload,
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 16, tzinfo=UTC),
    )

    action = plan["primary_action"]
    assert plan["status"] == "safe_actions_available"
    assert action["action_type"] == "paper_bridge_wait_for_next_add_signal"
    assert action["can_run_now"] is True
    assert action["execute_after_utc"] == "2026-01-01T12:15:00+00:00"
    assert action["wait_minutes"] == 0.0
    assert action["next_creditable_add_signal_plan"]["schedule_preserved_from_previous_watch"] is True
    assert plan["coordination_plan"]["next_signal_or_add_monitor_kst"] == "2026-01-01T21:15:00+09:00"
    assert action["order_submission_allowed"] is False
    assert action["no_live_order_sent"] is True


def test_safe_next_action_advances_next_add_monitor_after_completed_monitor_report(tmp_path) -> None:
    report_dir = tmp_path / "next_add_monitor"
    report_dir.mkdir()
    (report_dir / "market_state_rotation_v6_evidence_cycle.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T12:15:30+00:00",
                "no_live_order_sent": True,
            }
        ),
        encoding="utf-8",
    )
    command = (
        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
        "--quote-samples-per-tick 0 --refresh-market-data-before-run --max-signal-age-minutes 15 "
        f"--report-dir {report_dir}"
    )
    previous_payload = {
        "safe_next_action_plan": {
            "primary_action": {
                "action_type": "paper_bridge_wait_for_next_add_signal",
                "command": command,
                "execute_after_utc": "2026-01-01T12:15:00+00:00",
                "remove_plan_precheck": {
                    "source_event_key": "remove-event-1",
                    "status": "no_open_v6_paper_plan",
                },
                "next_creditable_add_signal_plan": {
                    "monitor_command": command,
                    "next_monitor_after_utc": "2026-01-01T12:15:00+00:00",
                    "no_live_order_sent": True,
                },
                "no_live_order_sent": True,
            }
        },
        "no_live_order_sent": True,
    }
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "real_paper_lifecycle_rows",
                "fresh_signal": True,
                "monitor_command": command,
                "paper_apply_no_open_plan": True,
                "remove_plan_precheck": {
                    "status": "no_open_v6_paper_plan",
                    "source_event_key": "remove-event-1",
                    "open_plan_count": 0,
                },
                "reason": "remove_signal_has_no_open_v6_paper_plan",
                "signal_freshness_capture_window_minutes": 15.0,
            }
        ],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        previous_payload=previous_payload,
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 16, tzinfo=UTC),
    )

    action = plan["primary_action"]
    assert action["can_run_now"] is False
    assert action["execute_after_utc"] == "2026-01-01T12:31:00+00:00"
    assert action["wait_minutes"] == 15.0
    assert action["next_creditable_add_signal_plan"]["schedule_preserved_from_previous_watch"] is False
    assert action["next_creditable_add_signal_plan"]["schedule_anchor"] == (
        "current_watch_generated_at_plus_monitor_interval"
    )
    assert action["no_live_order_sent"] is True


def test_unresolved_register_explains_no_open_remove_execution_parity_blocker() -> None:
    problems = watch._unresolved_problem_register(
        latest={
            "signal_wait_plan": {"fresh_signal": True},
            "paper_bridge_apply_gate": {
                "status": "blocked_no_open_v6_paper_plan",
                "bridge_action": "remove",
                "can_request_paper_apply_now": False,
                "remove_plan_precheck": {
                    "status": "no_open_v6_paper_plan",
                    "open_plan_count": 0,
                },
            },
            "execution_parity_collection_plan": {
                "status": "waiting_for_open_paper_plan_after_remove_signal",
                "missing_samples": 20,
                "currently_creditable_actions": [],
                "next_creditable_event_types": ["add", "remove"],
            },
            "execution_parity_journal": {
                "conversion": {
                    "journal_row_count": 0,
                    "missing_to_min_sample_count": 20,
                }
            },
        },
        paper_only_rehearsal={"system_ready": True},
        operator_handoff={},
        execution_parity_eta={
            "status": "eta_from_creditable_event_cadence",
            "missing_samples": 20,
            "estimated_days_at_current_cadence": 48.0,
            "estimated_completion_kst": "2026-01-03T00:00:00+09:00",
            "backtest_substitution_allowed": False,
        },
        microstructure_watch={"coverage_plan": {}},
        meta_router_promotion_gate={},
        safe_next_action_plan={
            "primary_action": {
                "action_type": "paper_bridge_wait_for_next_add_signal",
                "next_creditable_add_signal_plan": {
                    "status": "waiting_for_next_add_signal_or_existing_open_paper_plan",
                    "next_monitor_after_utc": "2026-01-01T12:15:00+00:00",
                    "no_live_order_sent": True,
                },
            },
            "coordination_plan": {
                "status": "parallel_signal_and_microstructure_schedule_ready",
                "next_signal_or_add_monitor_kst": "2026-01-01T21:15:00+09:00",
                "next_quote_window_kst": "2026-01-02T09:00:00+09:00",
                "do_not_skip_quote_window_for_signal_monitor": True,
                "no_live_order_sent": True,
            },
        },
    )

    execution_problem = next(item for item in problems if item["id"] == "execution_parity_samples")
    assert execution_problem["current_blocker"] == "remove_signal_has_no_open_v6_paper_plan"
    assert execution_problem["current_paper_apply_status"] == "blocked_no_open_v6_paper_plan"
    assert execution_problem["remove_plan_precheck"]["status"] == "no_open_v6_paper_plan"
    assert execution_problem["currently_creditable_actions"] == []
    assert execution_problem["next_creditable_event_types"] == ["add", "remove"]
    assert execution_problem["safe_action_type"] == "paper_bridge_wait_for_next_add_signal"
    assert execution_problem["coordination_status"] == "parallel_signal_and_microstructure_schedule_ready"
    assert execution_problem["next_signal_or_add_monitor_kst"] == "2026-01-01T21:15:00+09:00"
    assert execution_problem["next_quote_window_kst"] == "2026-01-02T09:00:00+09:00"
    assert execution_problem["next_creditable_add_signal_plan"]["next_monitor_after_utc"] == (
        "2026-01-01T12:15:00+00:00"
    )
    assert execution_problem["next_action"] == (
        "wait_for_next_add_signal_or_existing_open_paper_plan_before_crediting_remove"
    )
    assert execution_problem["next_action_type"] == "wait_for_next_add_signal_or_open_plan"
    assert execution_problem["problem_id"] == "execution_parity_samples"
    assert execution_problem["blocked_by"] == "remove_signal_has_no_open_v6_paper_plan"
    assert execution_problem["no_live_order_sent"] is True


def test_unresolved_register_coordinates_microstructure_calendar_day_blocker() -> None:
    problems = watch._unresolved_problem_register(
        latest={
            "signal_wait_plan": {"fresh_signal": True},
            "paper_bridge_apply_gate": {
                "status": "blocked_until_apply_gate_available",
                "can_request_paper_apply_now": False,
            },
            "execution_parity_collection_plan": {"missing_samples": 0},
            "execution_parity_journal": {
                "conversion": {"journal_row_count": 20, "missing_to_min_sample_count": 0}
            },
        },
        paper_only_rehearsal={"system_ready": True},
        operator_handoff={},
        execution_parity_eta={"missing_samples": 0},
        microstructure_watch={
            "coverage_plan": {
                "remaining_calendar_days": 26,
                "earliest_calendar_completion_kst": "2026-07-03T09:00:00+09:00",
                "calendar_completion_policy": "one_new_utc_calendar_date_per_day_for_actual_launch_gate",
            }
        },
        meta_router_promotion_gate={},
        safe_next_action_plan={
            "primary_action": {"action_type": "paper_bridge_wait_for_next_add_signal"},
            "coordination_plan": {
                "status": "parallel_signal_and_microstructure_schedule_ready",
                "next_signal_or_add_monitor_kst": "2026-06-08T04:25:00+09:00",
                "next_quote_window_kst": "2026-06-08T09:00:00+09:00",
                "do_not_skip_quote_window_for_signal_monitor": True,
                "no_live_order_sent": True,
            },
        },
    )

    micro_problem = next(item for item in problems if item["id"] == "microstructure_calendar_day_coverage")
    assert micro_problem["remaining_calendar_days"] == 26
    assert micro_problem["safe_action_type"] == "paper_bridge_wait_for_next_add_signal"
    assert micro_problem["coordination_status"] == "parallel_signal_and_microstructure_schedule_ready"
    assert micro_problem["next_signal_or_add_monitor_kst"] == "2026-06-08T04:25:00+09:00"
    assert micro_problem["next_quote_window_kst"] == "2026-06-08T09:00:00+09:00"
    assert micro_problem["do_not_skip_quote_window_for_signal_monitor"] is True
    assert micro_problem["next_action"] == "continue_daily_quote_window_collection"
    assert micro_problem["next_action_type"] == "collect_next_quote_window"
    assert micro_problem["problem_id"] == "microstructure_calendar_day_coverage"
    assert micro_problem["blocked_by"] == "future_calendar_quote_windows"
    assert micro_problem["can_run_now"] is None
    assert micro_problem["effective_can_run_now"] is None
    assert micro_problem["no_live_order_sent"] is True


def test_unresolved_register_includes_open_shadow_runtime_observation() -> None:
    problems = watch._unresolved_problem_register(
        latest={
            "signal_wait_plan": {"fresh_signal": True},
            "paper_bridge_apply_gate": {
                "status": "blocked_until_apply_gate_available",
                "can_request_paper_apply_now": False,
            },
            "execution_parity_collection_plan": {"missing_samples": 0},
            "execution_parity_journal": {
                "conversion": {"journal_row_count": 20, "missing_to_min_sample_count": 0}
            },
        },
        paper_only_rehearsal={"system_ready": True},
        operator_handoff={},
        execution_parity_eta={"missing_samples": 0},
        microstructure_watch={"coverage_plan": {}},
        meta_router_promotion_gate={},
        safe_next_action_plan={
            "primary_action": {"action_type": "monitor_fresh_signal"},
            "actions": [
                {
                    "action_type": "continue_no_live_shadow_watch",
                    "target_gate": "shadow_runtime_24h_observed",
                    "can_run_now": True,
                    "effective_action_due_now": False,
                    "covered_due_by_current_iteration": True,
                    "execution_window_status": "no_execution_window",
                    "effective_execution_window_status": "covered_this_iteration",
                    "no_live_order_sent": True,
                }
            ],
            "coordination_plan": {
                "status": "earlier_signal_or_add_monitor_before_quote_window",
                "no_live_order_sent": True,
            },
        },
        runtime_progress={
            "status": "collecting_runtime",
            "observed_hours": 16.25,
            "target_hours": 24.0,
            "remaining_hours": 7.75,
            "progress_pct": 67.71,
        },
    )

    runtime_problem = next(item for item in problems if item["id"] == "shadow_runtime_24h_observed")
    assert runtime_problem["status"] == "open_collect_continuous_no_live_shadow_runtime"
    assert runtime_problem["severity"] == "runtime_observation_blocker"
    assert runtime_problem["non_substitutable"] is True
    assert runtime_problem["observed_hours"] == 16.25
    assert runtime_problem["target_hours"] == 24.0
    assert runtime_problem["remaining_hours"] == 7.75
    assert runtime_problem["progress_pct"] == 67.71
    assert runtime_problem["safe_action_type"] == "continue_no_live_shadow_watch"
    assert runtime_problem["can_run_now"] is True
    assert runtime_problem["effective_can_run_now"] is False
    assert runtime_problem["safe_action_covered_due_by_current_iteration"] is True
    assert runtime_problem["next_action_type"] == "continue_no_live_shadow_watch"
    assert runtime_problem["blocked_by"] == "continuous_runtime_observation_incomplete"
    assert runtime_problem["actionability"] == "continuous_no_live_runtime_wait"
    assert runtime_problem["backtest_substitution_allowed"] is False
    assert runtime_problem["synthetic_or_backtest_rows_close_gate"] is False
    assert runtime_problem["order_submission_allowed"] is False
    assert runtime_problem["no_live_order_sent"] is True


def test_unresolved_register_includes_first_real_paper_lifecycle_dependency() -> None:
    problems = watch._unresolved_problem_register(
        latest={
            "signal_wait_plan": {
                "fresh_signal": False,
                "status": "blocked_waiting_for_fresh_signal",
            },
            "paper_bridge_apply_gate": {
                "status": "blocked_waiting_for_fresh_signal",
                "can_request_paper_apply_now": False,
            },
            "execution_parity_collection_plan": {"missing_samples": 0},
            "execution_parity_journal": {
                "conversion": {"journal_row_count": 20, "missing_to_min_sample_count": 0}
            },
        },
        paper_only_rehearsal={
            "system_ready": True,
            "remaining_gates": ["current_fresh_signal", "first_real_paper_lifecycle_row"],
            "actual_paper_lifecycle_rows": 0,
            "paper_apply_allowed_now": False,
            "current_rehearsal_available": False,
        },
        operator_handoff={},
        execution_parity_eta={"missing_samples": 0},
        microstructure_watch={"coverage_plan": {}},
        meta_router_promotion_gate={},
        safe_next_action_plan={
            "primary_action": {"action_type": "monitor_fresh_signal"},
            "actions": [
                {
                    "action_type": "paper_bridge_wait_for_fresh_signal",
                    "target_gate": "real_paper_lifecycle_rows",
                    "can_run_now": False,
                    "no_live_order_sent": True,
                }
            ],
            "coordination_plan": {
                "status": "earlier_signal_or_add_monitor_before_quote_window",
                "next_signal_or_add_monitor_kst": "2026-01-01T09:05:00+09:00",
                "no_live_order_sent": True,
            },
        },
    )

    lifecycle_problem = next(
        item for item in problems if item["id"] == "first_real_paper_lifecycle_row"
    )
    assert lifecycle_problem["status"] == "blocked_until_fresh_signal_and_operator_review"
    assert lifecycle_problem["severity"] == "paper_lifecycle_blocker"
    assert lifecycle_problem["non_substitutable"] is True
    assert lifecycle_problem["actual_paper_lifecycle_rows"] == 0
    assert lifecycle_problem["paper_apply_allowed_now"] is False
    assert lifecycle_problem["current_rehearsal_available"] is False
    assert lifecycle_problem["depends_on"] == [
        "current_fresh_signal",
        "operator_review_decisions",
    ]
    assert lifecycle_problem["safe_action_type"] == "paper_bridge_wait_for_fresh_signal"
    assert lifecycle_problem["next_action_type"] == (
        "wait_for_fresh_signal_and_operator_review_decisions"
    )
    assert lifecycle_problem["blocked_by"] == "fresh_signal_or_operator_review_missing"
    assert lifecycle_problem["actionability"] == (
        "dependency_blocked_until_fresh_signal_and_operator_review"
    )
    assert lifecycle_problem["manual_required"] is False
    assert lifecycle_problem["auto_apply_allowed"] is False
    assert lifecycle_problem["order_submission_allowed"] is False
    assert lifecycle_problem["no_live_order_sent"] is True


def test_unresolved_register_coordinates_current_fresh_signal_with_deferred_quote_window() -> None:
    problems = watch._unresolved_problem_register(
        latest={
            "signal_wait_plan": {
                "fresh_signal": False,
                "status": "blocked_waiting_for_fresh_signal",
            },
            "paper_bridge_apply_gate": {
                "status": "blocked_waiting_for_fresh_signal",
                "can_request_paper_apply_now": False,
            },
            "execution_parity_collection_plan": {"missing_samples": 0},
            "execution_parity_journal": {
                "conversion": {"journal_row_count": 20, "missing_to_min_sample_count": 0}
            },
        },
        paper_only_rehearsal={"system_ready": True},
        operator_handoff={},
        execution_parity_eta={"missing_samples": 0},
        microstructure_watch={"coverage_plan": {}},
        meta_router_promotion_gate={},
        safe_next_action_plan={
            "primary_action": {"action_type": "monitor_fresh_signal"},
            "coordination_plan": {
                "status": "earlier_signal_or_add_monitor_before_quote_window",
                "next_signal_or_add_monitor_kst": "2026-06-08T04:37:17+09:00",
                "next_quote_window_kst": "2026-06-08T09:00:00+09:00",
                "quote_window_deferred_by_earlier_monitor": True,
                "do_not_skip_quote_window_for_signal_monitor": True,
                "no_live_order_sent": True,
            },
        },
    )

    signal_problem = next(item for item in problems if item["id"] == "current_fresh_signal")
    assert signal_problem["problem_id"] == "current_fresh_signal"
    assert signal_problem["safe_action_type"] == "monitor_fresh_signal"
    assert signal_problem["next_action_type"] == "monitor_fresh_signal"
    assert signal_problem["blocked_by"] == "fresh_signal_missing_or_stale"
    assert signal_problem["manual_required"] is False
    assert signal_problem["actionability"] == "safe_monitor_scheduled_or_waiting"
    assert signal_problem["coordination_status"] == "earlier_signal_or_add_monitor_before_quote_window"
    assert signal_problem["next_signal_or_add_monitor_kst"] == "2026-06-08T04:37:17+09:00"
    assert signal_problem["next_quote_window_kst"] == "2026-06-08T09:00:00+09:00"
    assert signal_problem["quote_window_deferred_by_earlier_monitor"] is True
    assert signal_problem["do_not_skip_quote_window_for_signal_monitor"] is True
    assert signal_problem["next_action"] == "monitor_without_forcing_entry"
    assert signal_problem["no_live_order_sent"] is True


def test_safe_next_action_prioritizes_current_microstructure_capture() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "current_fresh_signal",
                "command": "monitor-signal",
                "reason": "must_wait_for_realtime_v6_add_or_remove_signal_do_not_force_entry",
            },
            {
                "gate": "real_microstructure_execution_evidence",
                "can_resolve_now": True,
                "command": "capture-quote",
                "reason": "collect_current_missing_utc_hour_now",
                "coverage_plan": {
                    "next_missing_utc_hour": "12",
                    "remaining_distinct_hours": 14,
                    "remaining_calendar_days": 28,
                },
            },
            {
                "gate": "shadow_runtime_24h_observed",
                "reason": "requires_calendar_runtime_observation_not_backtest_substitution",
            },
        ],
        runtime_progress={"remaining_hours": 22.0, "progress_pct": 8.0},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    assert plan["status"] == "safe_actions_available"
    assert plan["primary_action"]["action_type"] == "capture_microstructure_quote_window_now"
    assert plan["primary_action"]["command"] == "capture-quote"
    assert plan["primary_action"]["order_submission_allowed"] is False
    assert [item["action_type"] for item in plan["actions"]][:2] == [
        "capture_microstructure_quote_window_now",
        "monitor_fresh_signal",
    ]


def test_safe_next_action_uses_signal_monitor_when_quote_window_waits() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "current_fresh_signal",
                "command": "monitor-signal",
                "reason": "must_wait_for_realtime_v6_add_or_remove_signal_do_not_force_entry",
            },
            {
                "gate": "real_microstructure_execution_evidence",
                "can_resolve_now": False,
                "reason": "requires_new_calendar_days_or_missing_utc_hour_windows",
                "coverage_plan": {
                    "next_missing_utc_at": "2026-01-01T12:00:00+00:00",
                    "next_missing_kst_at": "2026-01-01T21:00:00+09:00",
                    "wait_minutes": 30.0,
                    "remaining_distinct_hours": 14,
                    "remaining_calendar_days": 28,
                },
            },
            {
                "gate": "tiny_canary_risk_caps_configured",
                "reason": "missing_optional_config_file",
                "quick_audit_command": "audit-caps",
                "errors": ["canary_risk_caps_json_required"],
            },
        ],
        runtime_progress={"remaining_hours": 22.0, "progress_pct": 8.0},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    assert plan["status"] == "safe_actions_available"
    assert plan["primary_action"]["action_type"] == "monitor_fresh_signal"
    assert plan["primary_action"]["command"] == "monitor-signal"
    assert all("can_start_now" in item for item in plan["actions"])
    assert all("waits_until_execution_window" in item for item in plan["actions"])
    wait_action = next(item for item in plan["actions"] if item["action_type"] == "wait_for_next_microstructure_quote_window")
    assert wait_action["can_run_now"] is False
    assert wait_action["can_start_now"] is True
    assert wait_action["waits_until_execution_window"] is True
    assert wait_action["execute_after_utc"] == "2026-01-01T12:00:00+00:00"
    assert wait_action["execute_after_kst"] == "2026-01-01T21:00:00+09:00"
    assert plan["next_scheduled_action"]["action_type"] == "wait_for_next_microstructure_quote_window"
    assert plan["next_startable_wait_action"]["action_type"] == "wait_for_next_microstructure_quote_window"
    assert plan["startable_action_count"] >= 1
    assert any(item["action_type"] == "audit_canary_risk_caps" for item in plan["actions"])
    assert plan["order_submission_allowed"] is False
    assert plan["no_live_order_sent"] is True


def test_safe_next_action_waits_for_next_quote_coverage_when_calendar_day_is_earlier() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "real_microstructure_execution_evidence",
                "can_resolve_now": False,
                "reason": "requires_new_calendar_days_or_missing_utc_hour_windows",
                "coverage_plan": {
                    "next_quote_coverage_kind": "next_utc_calendar_day",
                    "next_quote_coverage_at": "2026-01-02T00:00:00+00:00",
                    "next_quote_coverage_kst_at": "2026-01-02T09:00:00+09:00",
                    "next_quote_coverage_wait_minutes": 5.0,
                    "next_missing_utc_at": "2026-01-02T03:00:00+00:00",
                    "next_missing_kst_at": "2026-01-02T12:00:00+09:00",
                    "next_missing_utc_hour": "03",
                    "wait_minutes": 185.0,
                    "remaining_distinct_hours": 1,
                    "remaining_calendar_days": 1,
                },
            },
            {
                "gate": "shadow_runtime_24h_observed",
                "reason": "requires_calendar_runtime_observation_not_backtest_substitution",
            },
        ],
        runtime_progress={"remaining_hours": 22.0, "progress_pct": 8.0},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 23, 55, tzinfo=UTC),
    )

    action = plan["primary_action"]
    assert action["action_type"] == "wait_for_next_microstructure_quote_window"
    assert action["reason"] == "wait_until_next_quote_coverage_window"
    assert action["execute_after_utc"] == "2026-01-02T00:00:00+00:00"
    assert action["next_quote_coverage_kind"] == "next_utc_calendar_day"
    assert action["next_missing_utc_at"] == "2026-01-02T03:00:00+00:00"
    assert "--sleep-until-next-quote-coverage-window" in action["command"]
    assert "--max-pre-run-wait-seconds 3600" in action["command"]
    assert action["no_live_order_sent"] is True


def test_safe_next_action_waits_for_hour_of_day_balance_before_next_calendar_day() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "real_microstructure_execution_evidence",
                "can_resolve_now": False,
                "reason": "requires_new_calendar_days_or_missing_utc_hour_windows",
                "coverage_plan": {
                    "next_quote_coverage_kind": "missing_hour_of_day_balance_bucket",
                    "next_quote_coverage_at": "2026-06-06T13:00:00+00:00",
                    "next_quote_coverage_kst_at": "2026-06-06T22:00:00+09:00",
                    "next_calendar_day_at": "2026-06-07T00:00:00+00:00",
                    "next_missing_utc_at": "2026-06-06T13:00:00+00:00",
                    "next_missing_kst_at": "2026-06-06T22:00:00+09:00",
                    "next_missing_utc_hour": "13",
                    "wait_minutes": 59.0,
                    "remaining_distinct_hours": 0,
                    "remaining_distinct_hour_bucket_count": 0,
                    "remaining_hour_of_day_bucket_count": 1,
                    "remaining_calendar_days": 27,
                },
            },
            {
                "gate": "shadow_runtime_24h_observed",
                "reason": "requires_calendar_runtime_observation_not_backtest_substitution",
            },
        ],
        runtime_progress={"remaining_hours": 2.0, "progress_pct": 92.0},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 6, 6, 12, 1, tzinfo=UTC),
    )

    action = plan["primary_action"]
    assert action["action_type"] == "wait_for_next_microstructure_quote_window"
    assert action["next_quote_coverage_kind"] == "missing_hour_of_day_balance_bucket"
    assert action["execute_after_utc"] == "2026-06-06T13:00:00+00:00"
    assert action["remaining_distinct_hour_bucket_count"] == 0
    assert action["remaining_hour_of_day_bucket_count"] == 1
    assert "--sleep-until-next-quote-coverage-window" in action["command"]
    assert action["no_live_order_sent"] is True


def test_safe_next_action_waits_until_signal_monitor_cadence() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "current_fresh_signal",
                "command": "monitor-signal",
                "reason": "must_wait_for_realtime_v6_add_or_remove_signal_do_not_force_entry",
                "next_monitor_after_utc": "2026-01-01T12:15:00+00:00",
                "next_monitor_after_kst": "2026-01-01T21:15:00+09:00",
                "recommended_monitor_interval_minutes": 15,
                "cadence_lag_level": "extended_signal_drought",
            },
            {
                "gate": "shadow_runtime_24h_observed",
                "reason": "requires_calendar_runtime_observation_not_backtest_substitution",
            },
        ],
        runtime_progress={"remaining_hours": 22.0, "progress_pct": 8.0},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    monitor = next(item for item in plan["actions"] if item["action_type"] == "monitor_fresh_signal")
    assert monitor["can_run_now"] is False
    assert monitor["reason"] == "wait_until_signal_monitor_cadence"
    assert monitor["execute_after_utc"] == "2026-01-01T12:15:00+00:00"
    assert monitor["wait_minutes"] == 15.0
    assert monitor["recommended_monitor_interval_minutes"] == 15
    assert plan["next_scheduled_action"]["action_type"] == "monitor_fresh_signal"
    assert plan["next_startable_wait_action"] is None
    assert plan["primary_action"]["action_type"] == "continue_no_live_shadow_watch"
    assert plan["primary_action"]["can_run_now"] is True


def test_safe_next_action_retimestamps_scheduled_signal_monitor_report_dir() -> None:
    stale_command = (
        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
        "--quote-samples-per-tick 0 --refresh-market-data-before-run "
        "--report-dir reports/validation/diagnostics/market_state_rotation_v6_signal_monitor_20260101_120000Z"
    )
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "current_fresh_signal",
                "command": stale_command,
                "reason": "must_wait_for_realtime_v6_add_or_remove_signal_do_not_force_entry",
                "next_monitor_after_utc": "2026-01-01T12:15:00+00:00",
                "next_monitor_after_kst": "2026-01-01T21:15:00+09:00",
                "recommended_monitor_interval_minutes": 15,
            }
        ],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    monitor = next(item for item in plan["actions"] if item["action_type"] == "monitor_fresh_signal")
    expected_dir = (
        "reports/validation/diagnostics/"
        "market_state_rotation_v6_signal_monitor_20260101_121500Z"
    )
    assert f"--report-dir {expected_dir}" in monitor["command"]
    assert "market_state_rotation_v6_signal_monitor_20260101_120000Z" not in monitor["command"]
    assert monitor["execute_after_utc"] == "2026-01-01T12:15:00+00:00"
    assert monitor["no_live_order_sent"] is True


def test_safe_next_action_retimestamps_overdue_signal_monitor_report_dir_to_now() -> None:
    stale_command = (
        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
        "--quote-samples-per-tick 0 --refresh-market-data-before-run "
        "--report-dir reports/validation/diagnostics/market_state_rotation_v6_signal_monitor_20260101_120000Z"
    )
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "current_fresh_signal",
                "command": stale_command,
                "reason": "must_wait_for_realtime_v6_add_or_remove_signal_do_not_force_entry",
                "next_monitor_after_utc": "2026-01-01T12:15:00+00:00",
                "next_monitor_after_kst": "2026-01-01T21:15:00+09:00",
                "recommended_monitor_interval_minutes": 15,
            }
        ],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 20, tzinfo=UTC),
    )

    monitor = next(item for item in plan["actions"] if item["action_type"] == "monitor_fresh_signal")
    expected_dir = (
        "reports/validation/diagnostics/"
        "market_state_rotation_v6_signal_monitor_20260101_122000Z"
    )
    assert monitor["can_run_now"] is True
    assert monitor["execute_after_utc"] == "2026-01-01T12:15:00+00:00"
    assert f"--report-dir {expected_dir}" in monitor["command"]
    assert "market_state_rotation_v6_signal_monitor_20260101_121500Z" not in monitor["command"]
    assert monitor["no_live_order_sent"] is True


def test_safe_next_action_retimestamps_waiting_paper_operator_packet_commands() -> None:
    stale_dry_run = (
        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
        "--quote-samples-per-tick 0 --refresh-market-data-before-run "
        "--report-dir reports/validation/diagnostics/market_state_rotation_v6_launch_paper_dry_run_20260101_1200Z"
    )
    stale_apply = (
        ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
        "--apply-paper-bridge --quote-samples-per-tick 0 --refresh-market-data-before-run "
        "--pre-apply-backup-dir reports/db_recovery/market_state_rotation_v6_bridge_tick "
        "--report-dir reports/validation/diagnostics/market_state_rotation_v6_launch_paper_apply_20260101_1200Z"
    )
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "real_paper_lifecycle_rows",
                "fresh_signal": False,
                "monitor_command": (
                    ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                    "--quote-samples-per-tick 0 --refresh-market-data-before-run "
                    "--report-dir reports/validation/diagnostics/"
                    "market_state_rotation_v6_signal_monitor_20260101_120000Z"
                ),
                "next_monitor_after_utc": "2026-01-01T12:15:00+00:00",
                "next_monitor_after_kst": "2026-01-01T21:15:00+09:00",
                "reason": "must_wait_for_fresh_signal_before_paper_bridge_apply",
                "paper_apply_command_when_gate_allows": stale_apply,
                "paper_apply_operator_packet": {
                    "status": "armed_waiting_for_fresh_signal",
                "dry_run_command": stale_dry_run,
                "rerun_command_after_deadline": stale_dry_run,
                "apply_command_when_gate_allows": stale_apply,
                "command_safety": {
                    "status": "PASS",
                    "dry_run_report_dir": (
                        "reports/validation/diagnostics/"
                        "market_state_rotation_v6_launch_paper_dry_run_20260101_1200Z"
                    ),
                    "apply_report_dir": (
                        "reports/validation/diagnostics/"
                        "market_state_rotation_v6_launch_paper_apply_20260101_1200Z"
                    ),
                    "apply_pre_apply_backup_dir": "reports/db_recovery/market_state_rotation_v6_bridge_tick",
                },
                "pre_apply_backup_plan": {"required": True},
                "no_live_order_sent": True,
            },
            }
        ],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    action = next(item for item in plan["actions"] if item["action_type"] == "paper_bridge_wait_for_fresh_signal")
    packet = action["paper_apply_operator_packet"]
    safety = packet["command_safety"]
    assert action["execute_after_utc"] == "2026-01-01T12:15:00+00:00"
    assert "market_state_rotation_v6_signal_monitor_20260101_121500Z" in action["command"]
    assert "market_state_rotation_v6_signal_monitor_20260101_120000Z" not in action["command"]
    assert "market_state_rotation_v6_launch_paper_apply_20260101_1215Z" in (
        action["paper_apply_command_when_gate_allows"]
    )
    assert "market_state_rotation_v6_launch_paper_apply_20260101_1200Z" not in (
        action["paper_apply_command_when_gate_allows"]
    )
    assert "market_state_rotation_v6_launch_paper_dry_run_20260101_1215Z" in packet["dry_run_command"]
    assert "market_state_rotation_v6_launch_paper_dry_run_20260101_1215Z" in (
        packet["rerun_command_after_deadline"]
    )
    assert "market_state_rotation_v6_launch_paper_apply_20260101_1215Z" in (
        packet["apply_command_when_gate_allows"]
    )
    assert safety["dry_run_report_dir"].endswith("market_state_rotation_v6_launch_paper_dry_run_20260101_1215Z")
    assert safety["apply_report_dir"].endswith("market_state_rotation_v6_launch_paper_apply_20260101_1215Z")
    assert action["pre_apply_backup_plan"]["required"] is True
    assert action["no_live_order_sent"] is True


def test_safe_next_action_defers_quote_window_wait_when_signal_monitor_is_earlier() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "current_fresh_signal",
                "command": "monitor-signal",
                "reason": "must_wait_for_realtime_v6_add_or_remove_signal_do_not_force_entry",
                "next_monitor_after_utc": "2026-01-01T12:05:00+00:00",
                "next_monitor_after_kst": "2026-01-01T21:05:00+09:00",
                "recommended_monitor_interval_minutes": 5,
                "monitor_interval_capped_by_signal_freshness": True,
            },
            {
                "gate": "real_microstructure_execution_evidence",
                "can_resolve_now": False,
                "reason": "requires_new_calendar_days_or_missing_utc_hour_windows",
                "coverage_plan": {
                    "next_quote_coverage_kind": "next_utc_calendar_day",
                    "next_quote_coverage_at": "2026-01-01T13:00:00+00:00",
                    "next_quote_coverage_kst_at": "2026-01-01T22:00:00+09:00",
                    "next_quote_coverage_wait_minutes": 60.0,
                    "remaining_calendar_days": 26,
                },
            },
        ],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    assert plan["status"] == "waiting_for_earlier_scheduled_action_before_quote_window_wait"
    assert plan["primary_action"]["action_type"] == "monitor_fresh_signal"
    assert plan["primary_action"]["execute_after_utc"] == "2026-01-01T12:05:00+00:00"
    assert plan["next_startable_wait_action"] is None
    assert plan["next_deferred_wait_action"]["action_type"] == "wait_for_next_microstructure_quote_window"
    assert plan["next_deferred_wait_action"]["can_start_now"] is False
    assert plan["next_deferred_wait_action"]["deferred_until_after_action_type"] == "monitor_fresh_signal"
    assert plan["next_deferred_wait_action"]["deferred_until_after_utc"] == "2026-01-01T12:05:00+00:00"
    assert plan["coordination_plan"]["status"] == "earlier_signal_or_add_monitor_before_quote_window"
    assert plan["coordination_plan"]["quote_window_deferred_by_earlier_monitor"] is True
    assert plan["coordination_plan"]["do_not_skip_quote_window_for_signal_monitor"] is True
    assert plan["no_live_order_sent"] is True


def test_safe_next_action_prioritizes_earlier_monitor_before_startable_quote_window_wait() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "current_fresh_signal",
                "command": "monitor-signal",
                "reason": "must_wait_for_realtime_v6_add_or_remove_signal_do_not_force_entry",
                "next_monitor_after_utc": "2026-01-01T12:15:00+00:00",
            },
            {
                "gate": "real_microstructure_execution_evidence",
                "can_resolve_now": False,
                "reason": "requires_new_calendar_days_or_missing_utc_hour_windows",
                "coverage_plan": {
                    "next_missing_utc_at": "2026-01-01T12:30:00+00:00",
                    "next_missing_kst_at": "2026-01-01T21:30:00+09:00",
                    "wait_minutes": 180.0,
                    "remaining_distinct_hours": 6,
                    "remaining_calendar_days": 28,
                },
            },
            {
                "gate": "real_paper_lifecycle_rows",
                "fresh_signal": False,
                "monitor_command": "monitor-signal",
                "next_monitor_after_utc": "2026-01-01T12:15:00+00:00",
                "reason": "must_wait_for_fresh_signal_before_paper_bridge_apply",
            },
            {
                "gate": "shadow_runtime_24h_observed",
                "reason": "requires_calendar_runtime_observation_not_backtest_substitution",
            },
        ],
        runtime_progress={"remaining_hours": 16.0, "progress_pct": 33.0},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    assert plan["status"] == "waiting_for_earlier_scheduled_action_before_quote_window_wait"
    assert plan["primary_action"]["action_type"] == "monitor_fresh_signal"
    assert plan["primary_action"]["execute_after_utc"] == "2026-01-01T12:15:00+00:00"
    assert plan["next_startable_wait_action"] is None
    assert plan["next_deferred_wait_action"]["action_type"] == "wait_for_next_microstructure_quote_window"
    assert plan["next_deferred_wait_action"]["execute_after_utc"] == "2026-01-01T12:30:00+00:00"
    assert plan["next_deferred_wait_action"]["can_start_now"] is False
    assert plan["next_deferred_wait_action"]["start_recommended_now"] is False
    assert plan["next_deferred_wait_action"]["deferred_by_earlier_scheduled_action"] is True
    assert plan["next_deferred_wait_action"]["deferred_until_after_action_type"] == "monitor_fresh_signal"
    assert plan["next_deferred_wait_action"]["deferred_until_after_utc"] == "2026-01-01T12:15:00+00:00"
    assert "--max-pre-run-wait-seconds 10920" in plan["next_deferred_wait_action"]["command"]
    assert plan["pre_wait_scheduled_action_count"] == 1
    assert plan["pre_wait_scheduled_actions"][0]["action_type"] == "monitor_fresh_signal"
    assert plan["pre_wait_primary_action_type"] == "monitor_fresh_signal"
    assert plan["pre_wait_primary_action_due_now"] is False
    assert plan["pre_wait_primary_action_execute_after_kst"] == "2026-01-01T21:15:00+09:00"
    assert any(item["action_type"] == "paper_bridge_wait_for_fresh_signal" for item in plan["actions"])
    assert plan["coordination_warnings"] == []
    assert plan["coordination_plan"]["status"] == "earlier_signal_or_add_monitor_before_quote_window"
    assert plan["coordination_plan"]["primary_action_type"] == "monitor_fresh_signal"
    assert plan["coordination_plan"]["quote_window_deferred_by_earlier_monitor"] is True
    assert plan["coordination_plan"]["next_signal_or_add_monitor_kst"] == "2026-01-01T21:15:00+09:00"
    assert plan["coordination_plan"]["next_signal_or_add_monitor_window_status"] == (
        "scheduled_future"
    )
    assert plan["coordination_plan"]["next_signal_or_add_monitor_overdue_minutes"] == 0.0
    assert plan["coordination_plan"]["next_quote_window_kst"] == "2026-01-01T21:30:00+09:00"
    assert plan["coordination_plan"]["next_quote_window_status"] == "scheduled_future"
    assert plan["coordination_plan"]["next_action_after_primary"] == "wait_for_next_microstructure_quote_window"
    assert plan["coordination_plan"]["do_not_skip_quote_window_for_signal_monitor"] is True
    assert plan["startable_action_count"] == 1
    assert any(item["action_type"] == "continue_no_live_shadow_watch" for item in plan["actions"])
    assert plan["no_live_order_sent"] is True


def test_safe_next_coordination_marks_overdue_signal_monitor_before_quote_window() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "current_fresh_signal",
                "command": "monitor-signal",
                "reason": "must_wait_for_realtime_v6_add_or_remove_signal_do_not_force_entry",
                "next_monitor_after_utc": "2026-01-01T12:15:00+00:00",
            },
            {
                "gate": "real_microstructure_execution_evidence",
                "can_resolve_now": False,
                "reason": "requires_new_calendar_days_or_missing_utc_hour_windows",
                "coverage_plan": {
                    "next_quote_coverage_kind": "next_utc_calendar_day",
                    "next_quote_coverage_at": "2026-01-01T13:00:00+00:00",
                    "next_quote_coverage_kst_at": "2026-01-01T22:00:00+09:00",
                    "next_quote_coverage_wait_minutes": 40.0,
                    "remaining_calendar_days": 28,
                },
            },
        ],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 20, tzinfo=UTC),
    )

    coordination = plan["coordination_plan"]
    assert plan["status"] == "safe_action_due_before_quote_window_wait"
    assert plan["primary_action"]["action_type"] == "monitor_fresh_signal"
    assert plan["primary_action"]["execution_window_status"] == "due_or_overdue"
    assert plan["primary_action"]["overdue_minutes"] == 5.0
    assert plan["primary_action"]["action_due_now"] is True
    assert plan["primary_action_window_status"] == "due_or_overdue"
    assert plan["primary_action"]["effective_execution_window_status"] == "due_or_overdue"
    assert plan["primary_action"]["effective_action_due_now"] is True
    assert plan["primary_action"]["covered_by_current_iteration"] is False
    assert plan["primary_action"]["covered_due_by_current_iteration"] is False
    assert plan["primary_action_effective_window_status"] == "due_or_overdue"
    assert plan["primary_action_overdue_minutes"] == 5.0
    assert plan["primary_action_due_now"] is True
    assert plan["primary_action_effective_due_now"] is True
    assert plan["primary_action_covered_due_by_current_iteration"] is False
    assert plan["covered_due_safe_action_count"] == 0
    assert plan["uncovered_due_safe_action_count"] == 1
    assert plan["pre_wait_primary_action_type"] == "monitor_fresh_signal"
    assert plan["pre_wait_primary_action_due_now"] is True
    assert plan["pre_wait_primary_action_execute_after_kst"] == "2026-01-01T21:15:00+09:00"
    assert coordination["status"] == "earlier_signal_or_add_monitor_before_quote_window"
    assert coordination["next_signal_or_add_monitor_kst"] == "2026-01-01T21:15:00+09:00"
    assert coordination["next_signal_or_add_monitor_window_status"] == "due_or_overdue"
    assert coordination["next_signal_or_add_monitor_overdue_minutes"] == 5.0
    assert coordination["next_signal_or_add_monitor"]["execution_window_status"] == "due_or_overdue"
    assert coordination["next_signal_or_add_monitor"]["overdue_minutes"] == 5.0
    assert coordination["next_quote_window_kst"] == "2026-01-01T22:00:00+09:00"
    assert coordination["next_quote_window_status"] == "scheduled_future"
    assert coordination["next_quote_window_overdue_minutes"] == 0.0
    assert coordination["quote_window_deferred_by_earlier_monitor"] is True
    assert coordination["do_not_skip_quote_window_for_signal_monitor"] is True
    assert coordination["order_submission_allowed"] is False
    assert coordination["no_live_order_sent"] is True


def test_safe_next_marks_current_iteration_signal_monitor_covered_before_quote_window() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "current_fresh_signal",
                "command": "monitor-signal",
                "reason": "must_wait_for_realtime_v6_add_or_remove_signal_do_not_force_entry",
                "next_monitor_after_utc": "2026-01-01T12:15:00+00:00",
            },
            {
                "gate": "real_microstructure_execution_evidence",
                "can_resolve_now": False,
                "reason": "requires_new_calendar_days_or_missing_utc_hour_windows",
                "coverage_plan": {
                    "next_quote_coverage_kind": "next_utc_calendar_day",
                    "next_quote_coverage_at": "2026-01-01T13:00:00+00:00",
                    "next_quote_coverage_kst_at": "2026-01-01T22:00:00+09:00",
                    "next_quote_coverage_wait_minutes": 40.0,
                    "remaining_calendar_days": 28,
                },
            },
        ],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        latest_run={
            "signal_wait_plan": {
                "status": "blocked_waiting_for_fresh_signal",
                "fresh_signal": False,
                "recommended_monitor_interval_minutes": 5.0,
                "no_live_order_sent": True,
            },
            "paper_bridge_apply_gate": {
                "fresh_signal": False,
                "can_request_paper_apply_now": False,
                "no_live_order_sent": True,
            },
            "decision_state": {"signal_stale": True},
            "no_live_order_sent": True,
        },
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 20, tzinfo=UTC),
    )

    primary = plan["primary_action"]
    coverage = primary["current_iteration_coverage"]
    assert plan["status"] == "safe_action_covered_this_iteration_before_quote_window_wait"
    assert primary["action_type"] == "monitor_fresh_signal"
    assert primary["execution_window_status"] == "due_or_overdue"
    assert primary["action_due_now"] is True
    assert primary["effective_execution_window_status"] == "covered_this_iteration"
    assert primary["effective_action_due_now"] is False
    assert primary["covered_by_current_iteration"] is True
    assert primary["covered_due_by_current_iteration"] is True
    assert coverage["status"] == "covered_fresh_signal_still_waiting"
    assert coverage["paper_apply_available_after_coverage"] is False
    assert coverage["signal_stale"] is True
    assert coverage["recommended_next_recheck_after_kst"] == "2026-01-01T21:25:00+09:00"
    assert plan["primary_action_window_status"] == "due_or_overdue"
    assert plan["primary_action_effective_window_status"] == "covered_this_iteration"
    assert plan["primary_action_due_now"] is True
    assert plan["primary_action_effective_due_now"] is False
    assert plan["primary_action_covered_by_current_iteration"] is True
    assert plan["primary_action_covered_due_by_current_iteration"] is True
    assert plan["covered_due_safe_action_count"] == 1
    assert plan["uncovered_due_safe_action_count"] == 0
    assert plan["next_deferred_wait_action"]["action_type"] == "wait_for_next_microstructure_quote_window"
    coordination = plan["coordination_plan"]
    assert coordination["quote_window_deferred_by_earlier_monitor"] is True
    assert coordination["next_signal_or_add_monitor_kst"] == "2026-01-01T21:25:00+09:00"
    assert coordination["raw_next_signal_or_add_monitor_kst"] == "2026-01-01T21:15:00+09:00"
    assert coordination["next_signal_or_add_monitor_source"] == (
        "current_iteration_coverage.recommended_next_recheck_after"
    )
    assert (
        coordination["next_signal_or_add_monitor_retimestampted_after_current_iteration"]
        is True
    )
    assert coordination["next_signal_or_add_monitor_window_status"] == "scheduled_future"
    assert coordination["next_signal_or_add_monitor_wait_minutes"] == 5.0
    assert coordination["next_signal_or_add_monitor_overdue_minutes"] == 0.0
    assert coordination["next_signal_or_add_monitor_raw_window_status"] == "due_or_overdue"
    assert coordination["next_signal_or_add_monitor_raw_overdue_minutes"] == 5.0
    assert plan["order_submission_allowed"] is False
    assert plan["no_live_order_sent"] is True


def test_safe_next_action_coordinates_next_add_monitor_with_quote_window() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "real_paper_lifecycle_rows",
                "fresh_signal": True,
                "monitor_command": "dry-run-monitor",
                "paper_apply_no_open_plan": True,
                "remove_plan_precheck": {
                    "status": "no_open_v6_paper_plan",
                    "open_plan_count": 0,
                },
                "reason": "remove_signal_has_no_open_v6_paper_plan",
                "signal_freshness_capture_window_minutes": 15.0,
                "latest_add_ts": "2026-01-01T09:00:00+00:00",
                "expected_add_interval_hours": 144.0,
                "median_add_gap_hours": 72.0,
            },
            {
                "gate": "real_microstructure_execution_evidence",
                "can_resolve_now": False,
                "reason": "requires_new_calendar_days_or_missing_utc_hour_windows",
                "coverage_plan": {
                    "next_quote_coverage_kind": "missing_hour_of_day_balance_bucket",
                    "next_quote_coverage_at": "2026-01-01T12:45:00+00:00",
                    "next_quote_coverage_kst_at": "2026-01-01T21:45:00+09:00",
                    "next_missing_utc_at": "2026-01-01T12:45:00+00:00",
                    "next_missing_kst_at": "2026-01-01T21:45:00+09:00",
                    "wait_minutes": 45.0,
                    "remaining_distinct_hour_bucket_count": 0,
                    "remaining_hour_of_day_bucket_count": 1,
                    "remaining_calendar_days": 26,
                },
            },
        ],
        runtime_progress={},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    assert plan["primary_action"]["action_type"] == "paper_bridge_wait_for_next_add_signal"
    assert plan["next_startable_wait_action"] is None
    assert plan["next_deferred_wait_action"]["action_type"] == "wait_for_next_microstructure_quote_window"
    assert plan["next_deferred_wait_action"]["deferred_until_after_action_type"] == (
        "paper_bridge_wait_for_next_add_signal"
    )
    coordination = plan["coordination_plan"]
    assert coordination["status"] == "earlier_signal_or_add_monitor_before_quote_window"
    assert coordination["next_signal_or_add_monitor_kst"] == "2026-01-01T21:15:00+09:00"
    assert coordination["next_quote_window_kst"] == "2026-01-01T21:45:00+09:00"
    assert coordination["next_action_after_primary"] == "wait_for_next_microstructure_quote_window"
    assert coordination["do_not_skip_quote_window_for_signal_monitor"] is True
    assert coordination["quote_window_deferred_by_earlier_monitor"] is True
    assert coordination["signal_monitor_interval_capped_by_freshness"] is True
    assert coordination["next_signal_or_add_monitor"]["action_type"] == "paper_bridge_wait_for_next_add_signal"
    assert coordination["next_quote_window"]["action_type"] == "wait_for_next_microstructure_quote_window"
    assert coordination["order_submission_allowed"] is False
    assert coordination["no_live_order_sent"] is True


def test_safe_next_action_materializes_signal_monitor_placeholder() -> None:
    plan = watch._safe_next_action_plan(
        blocker_resolution_plan=[
            {
                "gate": "current_fresh_signal",
                "command": (
                    ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
                    "--quote-samples-per-tick 0 --report-dir "
                    "reports/validation/diagnostics/<signal_monitor_report_dir>"
                ),
                "reason": "must_wait_for_realtime_v6_add_or_remove_signal_do_not_force_entry",
            }
        ],
        runtime_progress={"remaining_hours": 22.0, "progress_pct": 8.0},
        microstructure_watch={},
        operator_handoff={"paper_apply_allowed_now": False},
        target_hours=24.0,
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )

    command = plan["primary_action"]["command"]
    assert "<signal_monitor_report_dir>" not in command
    assert "market_state_rotation_v6_launch_monitor_fresh_signal_20260101_120000Z" in command
    assert "raw_command" not in plan["primary_action"]


def test_blocker_plan_marks_microstructure_time_coverage_as_wait_required() -> None:
    plan = watch._blocker_resolution_plan(
        latest={
            "launch_readiness": {
                "blocking_gates": [
                    {
                        "gate": "real_microstructure_execution_evidence",
                        "blocker": "real_spread_slippage_latency_gates_pending",
                        "next_action": "collect_l2_quote_shadow_and_paper_fill_microstructure_until_p95_gates_pass",
                    }
                ],
                "operator_commands": {"microstructure_quote_capture": "capture"},
            }
        },
        progress={},
        runtime_progress={},
        risk_caps={},
        microstructure_watch={
            "status": "collecting_sample_day_hour_coverage",
            "blockers": ["calendar_days_missing", "distinct_hours_missing"],
            "metric_blockers": [],
            "coverage": {
                "utc_hour_of_day_covered_count": 9,
                "utc_hour_of_day_missing": ["11", "12"],
                "latest_sample_age_hours": 0.1,
            },
        },
        operator_handoff={"quote_capture_command": "capture"},
    )

    item = plan[0]
    assert item["gate"] == "real_microstructure_execution_evidence"
    assert item["can_resolve_now"] is False
    assert item["reason"] == "requires_new_calendar_days_or_missing_utc_hour_windows"
    assert item["sample_blockers"] == ["calendar_days_missing", "distinct_hours_missing"]
    assert item["missing_utc_hour_of_day"] == ["11", "12"]


def test_microstructure_coverage_plan_collects_current_missing_hour_now() -> None:
    generated_at = datetime(2026, 1, 1, 11, 35, tzinfo=UTC)

    plan = watch._microstructure_coverage_plan(
        coverage={
            "utc_hour_of_day_covered_count": 22,
            "utc_hour_of_day_missing": ["11", "12"],
            "latest_sample_age_hours": 0.1,
        },
        latest_collection={
            "quote_observed": 300,
            "quote_required": 300,
            "quote_calendar_days": 28,
            "quote_min_calendar_days": 30,
            "quote_distinct_hours": 22,
            "quote_min_distinct_hours": 24,
        },
        microstructure_watch={
            "calendar_day_count": 28,
            "min_calendar_days": 30,
            "calendar_days": ["2026-01-01"],
        },
        generated_at=generated_at,
        quote_capture_command="capture",
    )

    assert plan["status"] == "current_missing_utc_hour_open"
    assert plan["current_utc_hour"] == "11"
    assert plan["current_utc_hour_missing"] is True
    assert plan["next_missing_utc_hour"] == "11"
    assert plan["wait_minutes"] == 0.0
    assert plan["remaining_calendar_days"] == 2
    assert plan["remaining_distinct_hours"] == 2
    assert plan["can_collect_now"] is True
    assert plan["recommended_action"] == "collect_current_missing_utc_hour_now"


def test_microstructure_coverage_plan_prefers_next_utc_day_before_later_missing_hour() -> None:
    generated_at = datetime(2026, 1, 1, 23, 55, tzinfo=UTC)

    plan = watch._microstructure_coverage_plan(
        coverage={
            "utc_hour_of_day_covered_count": 23,
            "utc_hour_of_day_missing": ["03"],
            "latest_sample_age_hours": 0.1,
        },
        latest_collection={
            "quote_observed": 300,
            "quote_required": 300,
            "quote_calendar_days": 1,
            "quote_min_calendar_days": 2,
            "quote_distinct_hours": 23,
            "quote_min_distinct_hours": 24,
        },
        microstructure_watch={
            "calendar_day_count": 1,
            "min_calendar_days": 2,
            "calendar_days": ["2026-01-01"],
            "distinct_hour_count": 23,
            "min_distinct_hours": 24,
            "eligible_row_count": 300,
            "required_quote_samples": 300,
        },
        generated_at=generated_at,
        quote_capture_command="capture",
    )

    assert plan["status"] == "waiting_for_next_quote_coverage_window"
    assert plan["next_quote_coverage_kind"] == "next_utc_calendar_day"
    assert plan["next_quote_coverage_at"] == "2026-01-02T00:00:00+00:00"
    assert plan["next_missing_utc_at"] == "2026-01-02T03:00:00+00:00"
    assert plan["next_quote_coverage_wait_minutes"] == 5.0
    assert plan["recommended_action"] == "wait_until_next_quote_coverage_window"


def test_microstructure_coverage_plan_separates_distinct_hour_gate_from_hour_of_day_balance() -> None:
    generated_at = datetime(2026, 1, 1, 10, 50, tzinfo=UTC)

    plan = watch._microstructure_coverage_plan(
        coverage={
            "utc_hour_of_day_covered_count": 22,
            "utc_hour_of_day_missing": ["12", "13"],
            "latest_sample_age_hours": 4.8,
        },
        latest_collection={
            "quote_observed": 362,
            "quote_required": 300,
            "quote_calendar_days": 3,
            "quote_min_calendar_days": 30,
            "quote_distinct_hours": 23,
            "quote_min_distinct_hours": 24,
        },
        microstructure_watch={
            "calendar_day_count": 3,
            "min_calendar_days": 30,
            "calendar_days": ["2026-01-01"],
            "distinct_hour_count": 23,
            "min_distinct_hours": 24,
            "eligible_row_count": 362,
            "required_quote_samples": 300,
        },
        generated_at=generated_at,
        quote_capture_command="capture",
    )

    assert plan["remaining_distinct_hours"] == 1
    assert plan["remaining_distinct_hour_bucket_count"] == 1
    assert plan["remaining_missing_utc_hour_count"] == 2
    assert plan["remaining_hour_of_day_bucket_count"] == 2
    assert plan["hour_of_day_covered_count"] == 22
    assert plan["next_missing_utc_hour"] == "12"
    assert "distinct_hour_bucket_count counts unique UTC hour timestamps" in plan["coverage_accounting_note"]


def test_microstructure_coverage_plan_estimates_calendar_completion_after_covered_current_day() -> None:
    generated_at = datetime(2026, 6, 6, 10, 50, tzinfo=UTC)

    plan = watch._microstructure_coverage_plan(
        coverage={
            "utc_hour_of_day_covered_count": 22,
            "utc_hour_of_day_missing": ["12", "13"],
        },
        latest_collection={
            "quote_observed": 362,
            "quote_required": 300,
            "quote_calendar_days": 3,
            "quote_min_calendar_days": 30,
            "quote_distinct_hours": 23,
            "quote_min_distinct_hours": 24,
        },
        microstructure_watch={
            "calendar_day_count": 3,
            "min_calendar_days": 30,
            "calendar_days": ["2026-06-04", "2026-06-05", "2026-06-06"],
            "distinct_hour_count": 23,
            "min_distinct_hours": 24,
            "eligible_row_count": 362,
            "required_quote_samples": 300,
        },
        generated_at=generated_at,
        quote_capture_command="capture",
    )

    assert plan["remaining_calendar_days"] == 27
    assert plan["next_calendar_day_at"] == "2026-06-07T00:00:00+00:00"
    assert plan["earliest_calendar_completion_utc"] == "2026-07-03T00:00:00+00:00"
    assert plan["earliest_calendar_completion_kst"] == "2026-07-03T09:00:00+09:00"
    assert plan["calendar_completion_policy"] == "one_new_utc_calendar_date_per_day_for_actual_launch_gate"


def test_microstructure_coverage_plan_estimates_calendar_completion_when_current_day_can_count_now() -> None:
    generated_at = datetime(2026, 6, 6, 10, 50, tzinfo=UTC)

    plan = watch._microstructure_coverage_plan(
        coverage={
            "utc_hour_of_day_covered_count": 22,
            "utc_hour_of_day_missing": ["12", "13"],
        },
        latest_collection={
            "quote_observed": 362,
            "quote_required": 300,
            "quote_calendar_days": 3,
            "quote_min_calendar_days": 30,
            "quote_distinct_hours": 23,
            "quote_min_distinct_hours": 24,
        },
        microstructure_watch={
            "calendar_day_count": 3,
            "min_calendar_days": 30,
            "calendar_days": ["2026-06-03", "2026-06-04", "2026-06-05"],
            "distinct_hour_count": 23,
            "min_distinct_hours": 24,
            "eligible_row_count": 362,
            "required_quote_samples": 300,
        },
        generated_at=generated_at,
        quote_capture_command="capture",
    )

    assert plan["current_utc_date_missing"] is True
    assert plan["next_calendar_day_at"] == "2026-06-06T10:50:00+00:00"
    assert plan["earliest_calendar_completion_utc"] == "2026-07-02T00:00:00+00:00"
    assert plan["earliest_calendar_completion_kst"] == "2026-07-02T09:00:00+09:00"


def test_microstructure_coverage_plan_schedules_hour_of_day_balance_after_distinct_gate_passes() -> None:
    generated_at = datetime(2026, 6, 6, 12, 1, tzinfo=UTC)

    plan = watch._microstructure_coverage_plan(
        coverage={
            "utc_hour_of_day_covered_count": 23,
            "utc_hour_of_day_missing": ["13"],
        },
        latest_collection={
            "quote_observed": 366,
            "quote_required": 300,
            "quote_calendar_days": 3,
            "quote_min_calendar_days": 30,
            "quote_distinct_hours": 24,
            "quote_min_distinct_hours": 24,
        },
        microstructure_watch={
            "calendar_day_count": 3,
            "min_calendar_days": 30,
            "calendar_days": ["2026-06-04", "2026-06-05", "2026-06-06"],
            "distinct_hour_count": 24,
            "min_distinct_hours": 24,
            "eligible_row_count": 366,
            "required_quote_samples": 300,
        },
        generated_at=generated_at,
        quote_capture_command="capture",
    )

    assert plan["remaining_distinct_hour_bucket_count"] == 0
    assert plan["remaining_hour_of_day_bucket_count"] == 1
    assert plan["hour_of_day_balance_needed"] is True
    assert plan["next_quote_coverage_kind"] == "missing_hour_of_day_balance_bucket"
    assert plan["next_quote_coverage_at"] == "2026-06-06T13:00:00+00:00"
    assert plan["next_missing_utc_hour"] == "13"
    assert plan["recommended_action"] == "wait_until_next_quote_coverage_window"


def test_microstructure_coverage_plan_collects_current_hour_of_day_balance_now() -> None:
    generated_at = datetime(2026, 6, 6, 13, 5, tzinfo=UTC)

    plan = watch._microstructure_coverage_plan(
        coverage={
            "utc_hour_of_day_covered_count": 23,
            "utc_hour_of_day_missing": ["13"],
        },
        latest_collection={
            "quote_observed": 366,
            "quote_required": 300,
            "quote_calendar_days": 3,
            "quote_min_calendar_days": 30,
            "quote_distinct_hours": 24,
            "quote_min_distinct_hours": 24,
        },
        microstructure_watch={
            "calendar_day_count": 3,
            "min_calendar_days": 30,
            "calendar_days": ["2026-06-04", "2026-06-05", "2026-06-06"],
            "distinct_hour_count": 24,
            "min_distinct_hours": 24,
            "eligible_row_count": 366,
            "required_quote_samples": 300,
        },
        generated_at=generated_at,
        quote_capture_command="capture",
    )

    assert plan["status"] == "current_hour_of_day_balance_open"
    assert plan["current_utc_hour_missing"] is True
    assert plan["remaining_distinct_hour_bucket_count"] == 0
    assert plan["remaining_hour_of_day_bucket_count"] == 1
    assert plan["can_collect_now"] is True
    assert plan["recommended_action"] == "collect_current_hour_of_day_balance_now"


def test_microstructure_coverage_plan_collects_current_utc_day_now() -> None:
    generated_at = datetime(2026, 1, 2, 0, 5, tzinfo=UTC)

    plan = watch._microstructure_coverage_plan(
        coverage={
            "utc_hour_of_day_covered_count": 23,
            "utc_hour_of_day_missing": ["03"],
            "latest_sample_age_hours": 0.1,
        },
        latest_collection={
            "quote_observed": 300,
            "quote_required": 300,
            "quote_calendar_days": 1,
            "quote_min_calendar_days": 2,
            "quote_distinct_hours": 23,
            "quote_min_distinct_hours": 24,
        },
        microstructure_watch={
            "calendar_day_count": 1,
            "min_calendar_days": 2,
            "calendar_days": ["2026-01-01"],
            "distinct_hour_count": 23,
            "min_distinct_hours": 24,
            "eligible_row_count": 300,
            "required_quote_samples": 300,
        },
        generated_at=generated_at,
        quote_capture_command="capture",
    )

    assert plan["status"] == "current_utc_calendar_day_open"
    assert plan["current_utc_date"] == "2026-01-02"
    assert plan["current_utc_date_missing"] is True
    assert plan["next_quote_coverage_kind"] == "current_utc_calendar_day"
    assert plan["next_quote_coverage_at"] == "2026-01-02T00:05:00+00:00"
    assert plan["can_collect_now"] is True
    assert plan["recommended_action"] == "collect_current_utc_calendar_day_now"


def test_blocker_plan_marks_current_microstructure_hour_as_resolvable_now() -> None:
    plan = watch._blocker_resolution_plan(
        latest={
            "launch_readiness": {
                "blocking_gates": [
                    {
                        "gate": "real_microstructure_execution_evidence",
                        "blocker": "real_spread_slippage_latency_gates_pending",
                        "next_action": "collect_l2_quote_shadow_and_paper_fill_microstructure_until_p95_gates_pass",
                    }
                ],
                "operator_commands": {"microstructure_quote_capture": "capture"},
            }
        },
        progress={},
        runtime_progress={},
        risk_caps={},
        microstructure_watch={
            "status": "collecting_sample_day_hour_coverage",
            "blockers": ["calendar_days_missing", "distinct_hours_missing"],
            "metric_blockers": [],
            "coverage": {
                "utc_hour_of_day_covered_count": 22,
                "utc_hour_of_day_missing": ["11", "12"],
                "latest_sample_age_hours": 0.1,
            },
            "coverage_plan": {
                "current_utc_hour_missing": True,
                "next_missing_utc_hour": "11",
                "next_missing_utc_at": "2026-01-01T11:35:00+00:00",
                "next_missing_kst_at": "2026-01-01T20:35:00+09:00",
                "wait_minutes": 0.0,
                "remaining_calendar_days": 2,
                "remaining_distinct_hours": 2,
                "remaining_quote_samples": 0,
            },
        },
        operator_handoff={"quote_capture_command": "capture"},
    )

    item = plan[0]
    assert item["gate"] == "real_microstructure_execution_evidence"
    assert item["can_resolve_now"] is True
    assert item["reason"] == "collect_current_missing_utc_hour_now"
    assert item["next_missing_utc_hour"] == "11"
    assert item["wait_minutes"] == 0.0


def test_blocker_plan_marks_current_microstructure_calendar_day_as_resolvable_now() -> None:
    plan = watch._blocker_resolution_plan(
        latest={
            "launch_readiness": {
                "blocking_gates": [
                    {
                        "gate": "real_microstructure_execution_evidence",
                        "blocker": "real_spread_slippage_latency_gates_pending",
                        "next_action": "collect_l2_quote_shadow_and_paper_fill_microstructure_until_p95_gates_pass",
                    }
                ],
                "operator_commands": {"microstructure_quote_capture": "capture"},
            }
        },
        progress={},
        runtime_progress={},
        risk_caps={},
        microstructure_watch={
            "status": "collecting_sample_day_hour_coverage",
            "blockers": ["calendar_days_missing", "distinct_hours_missing"],
            "metric_blockers": [],
            "coverage": {
                "utc_hour_of_day_covered_count": 23,
                "utc_hour_of_day_missing": ["03"],
                "latest_sample_age_hours": 0.1,
            },
            "coverage_plan": {
                "current_utc_date": "2026-01-02",
                "current_utc_date_missing": True,
                "current_utc_hour_missing": False,
                "next_quote_coverage_kind": "current_utc_calendar_day",
                "next_quote_coverage_at": "2026-01-02T00:05:00+00:00",
                "next_quote_coverage_kst_at": "2026-01-02T09:05:00+09:00",
                "next_quote_coverage_wait_minutes": 0.0,
                "next_missing_utc_hour": "03",
                "next_missing_utc_at": "2026-01-02T03:00:00+00:00",
                "wait_minutes": 175.0,
                "remaining_calendar_days": 1,
                "remaining_distinct_hours": 1,
                "remaining_quote_samples": 0,
            },
        },
        operator_handoff={"quote_capture_command": "capture"},
    )

    item = plan[0]
    assert item["gate"] == "real_microstructure_execution_evidence"
    assert item["can_resolve_now"] is True
    assert item["reason"] == "collect_current_utc_calendar_day_now"
    assert item["current_utc_date_missing"] is True
    assert item["next_quote_coverage_kind"] == "current_utc_calendar_day"


def test_blocker_plan_includes_canary_risk_caps_quick_audit_command() -> None:
    plan = watch._blocker_resolution_plan(
        latest={
            "launch_readiness": {
                "blocking_gates": [
                    {
                        "gate": "tiny_canary_risk_caps_configured",
                        "blocker": "canary_notional_daily_loss_or_leverage_caps_missing",
                        "next_action": "set_explicit_tiny_canary_notional_leverage_and_daily_loss_caps",
                    }
                ]
            }
        },
        progress={},
        runtime_progress={},
        risk_caps={
            "status": "missing_optional_config_file",
            "errors": ["canary_risk_caps_json_required"],
            "operator_review": {
                "target_config_path": "reports/operations/market_state_rotation_v6_canary_risk_caps.json",
                "quick_audit_command": "quick-audit",
                "validation_command": "evidence-validation",
            },
        },
        microstructure_watch={},
        operator_handoff={},
    )

    item = plan[0]
    assert item["gate"] == "tiny_canary_risk_caps_configured"
    assert item["requires_operator_review"] is True
    assert item["quick_audit_command"] == "quick-audit"
    assert item["validation_command"] == "evidence-validation"
    assert item["no_live_order_sent"] is True


def test_pre_run_quote_window_wait_plan_sleeps_within_limit() -> None:
    plan = watch._pre_run_quote_window_wait_plan(
        previous_payload={
            "microstructure_watch": {
                "coverage_plan": {
                    "status": "waiting_for_next_missing_utc_hour_or_new_calendar_day",
                    "can_collect_now": False,
                    "current_utc_hour_missing": False,
                    "missing_utc_hour_of_day": ["12"],
                    "next_missing_utc_hour": "12",
                    "next_missing_utc_at": "2026-01-01T12:00:00+00:00",
                }
            }
        },
        generated_at=datetime(2026, 1, 1, 11, 55, tzinfo=UTC),
        enabled=True,
        max_wait_seconds=600.0,
        wakeup_buffer_seconds=5.0,
    )

    assert plan["status"] == "sleep_until_next_quote_coverage_window"
    assert plan["should_sleep"] is True
    assert plan["wait_seconds"] == 305.0
    assert plan["next_missing_utc_hour"] == "12"
    assert plan["current_utc_hour"] == "11"
    assert plan["current_utc_hour_missing"] is False
    assert plan["no_live_order_sent"] is True


def test_pre_run_quote_window_wait_plan_prefers_next_calendar_day_before_missing_hour() -> None:
    plan = watch._pre_run_quote_window_wait_plan(
        previous_payload={
            "microstructure_watch": {
                "coverage_plan": {
                    "status": "waiting_for_next_quote_coverage_window",
                    "can_collect_now": False,
                    "current_utc_date": "2026-01-01",
                    "current_utc_date_missing": False,
                    "covered_calendar_days": ["2026-01-01"],
                    "remaining_calendar_days": 1,
                    "current_utc_hour_missing": False,
                    "missing_utc_hour_of_day": ["03"],
                    "next_quote_coverage_kind": "next_utc_calendar_day",
                    "next_quote_coverage_at": "2026-01-02T00:00:00+00:00",
                    "next_quote_coverage_kst_at": "2026-01-02T09:00:00+09:00",
                    "next_missing_utc_hour": "03",
                    "next_missing_utc_at": "2026-01-02T03:00:00+00:00",
                    "next_missing_kst_at": "2026-01-02T12:00:00+09:00",
                    "calendar_day_count": 1,
                }
            }
        },
        generated_at=datetime(2026, 1, 1, 23, 55, tzinfo=UTC),
        enabled=True,
        max_wait_seconds=600.0,
        wakeup_buffer_seconds=5.0,
    )

    assert plan["status"] == "sleep_until_next_quote_coverage_window"
    assert plan["should_sleep"] is True
    assert plan["wait_seconds"] == 305.0
    assert plan["next_quote_coverage_kind"] == "next_utc_calendar_day"
    assert plan["next_quote_coverage_at"] == "2026-01-02T00:00:00+00:00"
    assert plan["next_missing_utc_at"] == "2026-01-02T03:00:00+00:00"
    assert plan["target_utc_date"] == "2026-01-02"
    assert plan["no_live_order_sent"] is True


def test_pre_run_quote_window_wait_plan_recomputes_current_hour_from_missing_list() -> None:
    plan = watch._pre_run_quote_window_wait_plan(
        previous_payload={
            "microstructure_watch": {
                "coverage_plan": {
                    "status": "waiting_for_next_quote_coverage_window",
                    "can_collect_now": False,
                    "current_utc_hour_missing": True,
                    "missing_utc_hour_of_day": ["12"],
                    "next_missing_utc_hour": "12",
                    "next_missing_utc_at": "2026-01-01T12:00:00+00:00",
                }
            }
        },
        generated_at=datetime(2026, 1, 1, 11, 55, tzinfo=UTC),
        enabled=True,
        max_wait_seconds=600.0,
        wakeup_buffer_seconds=5.0,
    )

    assert plan["status"] == "sleep_until_next_quote_coverage_window"
    assert plan["current_utc_hour"] == "11"
    assert plan["current_utc_hour_missing"] is False


def test_pre_run_quote_window_wait_plan_does_not_sleep_beyond_limit() -> None:
    plan = watch._pre_run_quote_window_wait_plan(
        previous_payload={
            "microstructure_watch": {
                "coverage_plan": {
                    "status": "waiting_for_next_quote_coverage_window",
                    "can_collect_now": False,
                    "current_utc_hour_missing": False,
                    "missing_utc_hour_of_day": ["12"],
                    "next_missing_utc_hour": "12",
                    "next_missing_utc_at": "2026-01-01T12:00:00+00:00",
                }
            }
        },
        generated_at=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
        enabled=True,
        max_wait_seconds=300.0,
        wakeup_buffer_seconds=5.0,
    )

    assert plan["status"] == "next_quote_window_wait_exceeds_limit"
    assert plan["should_sleep"] is False
    assert plan["reason"] == "rerun_later_or_raise_max_pre_run_wait_seconds"


def test_pre_run_quote_window_wait_plan_opens_when_current_hour_is_missing() -> None:
    plan = watch._pre_run_quote_window_wait_plan(
        previous_payload={
            "microstructure_watch": {
                "coverage_plan": {
                    "status": "waiting_for_next_missing_utc_hour_or_new_calendar_day",
                    "can_collect_now": False,
                    "current_utc_hour_missing": False,
                    "missing_utc_hour_of_day": ["12"],
                    "next_missing_utc_hour": "12",
                    "next_missing_utc_at": "2026-01-01T12:00:00+00:00",
                }
            }
        },
        generated_at=datetime(2026, 1, 1, 12, 5, tzinfo=UTC),
        enabled=True,
        max_wait_seconds=3600.0,
        wakeup_buffer_seconds=5.0,
    )

    assert plan["status"] == "current_quote_window_open"
    assert plan["should_sleep"] is False
    assert plan["wait_seconds"] == 0.0
    assert plan["current_utc_hour"] == "12"
    assert plan["current_utc_hour_missing"] is True
    assert plan["reason"] == "current_utc_hour_can_advance_microstructure_coverage"


def test_pre_run_quote_window_wait_plan_marks_elapsed_non_current_window_stale() -> None:
    plan = watch._pre_run_quote_window_wait_plan(
        previous_payload={
            "microstructure_watch": {
                "coverage_plan": {
                    "status": "waiting_for_next_missing_utc_hour_or_new_calendar_day",
                    "can_collect_now": False,
                    "current_utc_hour_missing": False,
                    "missing_utc_hour_of_day": ["12"],
                    "next_missing_utc_hour": "12",
                    "next_missing_utc_at": "2026-01-01T12:00:00+00:00",
                }
            }
        },
        generated_at=datetime(2026, 1, 1, 13, 5, tzinfo=UTC),
        enabled=True,
        max_wait_seconds=3600.0,
        wakeup_buffer_seconds=5.0,
    )

    assert plan["status"] == "next_quote_coverage_window_reached_or_previous_plan_stale"
    assert plan["should_sleep"] is False
    assert plan["wait_seconds"] == 0.0
    assert plan["current_utc_hour"] == "13"
    assert plan["current_utc_hour_missing"] is False
    assert plan["reason"] == "run_watch_now_to_recompute_or_capture_current_quote_coverage_window"


def test_finalize_pre_run_quote_window_sleep_marks_on_time_wakeup() -> None:
    finalized = watch._finalize_pre_run_quote_window_sleep(
        {
            "status": "sleep_until_next_missing_quote_window",
            "should_sleep": True,
            "wait_seconds": 305.0,
            "next_missing_utc_at": "2026-01-01T12:00:00+00:00",
            "next_missing_utc_hour": "12",
            "no_live_order_sent": True,
        },
        sleep_started_at=datetime(2026, 1, 1, 11, 55, tzinfo=UTC),
        woke_at=datetime(2026, 1, 1, 12, 0, 5, tzinfo=UTC),
    )

    assert finalized["actual_sleep_seconds"] == 305.0
    assert finalized["target_window_start_utc"] == "2026-01-01T12:00:00+00:00"
    assert finalized["target_window_end_utc"] == "2026-01-01T13:00:00+00:00"
    assert finalized["wakeup_lag_seconds"] == 5.0
    assert finalized["target_window_missed"] is False
    assert finalized["overshoot_seconds"] == 0.0
    assert finalized["recovery_action"] is None
    assert finalized["no_live_order_sent"] is True


def test_finalize_pre_run_quote_window_sleep_marks_missed_target_window() -> None:
    finalized = watch._finalize_pre_run_quote_window_sleep(
        {
            "status": "sleep_until_next_missing_quote_window",
            "should_sleep": True,
            "wait_seconds": 305.0,
            "next_missing_utc_at": "2026-01-01T12:00:00+00:00",
            "next_missing_utc_hour": "12",
            "no_live_order_sent": True,
        },
        sleep_started_at=datetime(2026, 1, 1, 11, 55, tzinfo=UTC),
        woke_at=datetime(2026, 1, 1, 14, 5, tzinfo=UTC),
    )

    assert finalized["actual_sleep_seconds"] == 7800.0
    assert finalized["target_window_missed"] is True
    assert finalized["target_window_missed_reason"] == "woke_after_target_window_end"
    assert finalized["wakeup_lag_minutes"] == 125.0
    assert finalized["overshoot_minutes"] == 65.0
    assert finalized["recovery_action"] == "rerun_watch_now_to_capture_current_missing_hour_and_recompute_missed_hours"
    assert finalized["no_live_order_sent"] is True


def test_pre_run_wait_force_quote_sample_for_hour_of_day_balance_window() -> None:
    assert (
        watch._pre_run_wait_force_quote_sample(
            {
                "status": "sleep_until_next_quote_coverage_window",
                "actual_sleep_seconds": 305.0,
                "target_quote_coverage_kind": "missing_hour_of_day_balance_bucket",
                "target_window_missed": False,
                "no_live_order_sent": True,
            }
        )
        is True
    )
    assert (
        watch._pre_run_wait_force_quote_sample(
            {
                "status": "sleep_until_next_quote_coverage_window",
                "next_quote_coverage_kind": "missing_hour_of_day_balance_bucket",
                "target_window_missed": True,
                "no_live_order_sent": True,
            }
        )
        is False
    )


def test_pre_run_quote_window_capture_outcome_marks_calendar_day_captured() -> None:
    outcome = watch._pre_run_quote_window_capture_outcome(
        pre_run_wait_plan={
            "status": "sleep_until_next_quote_coverage_window",
            "should_sleep": True,
            "actual_sleep_seconds": 305.0,
            "next_quote_coverage_kind": "next_utc_calendar_day",
            "next_quote_coverage_at": "2026-01-02T00:00:00+00:00",
            "calendar_day_count": 1,
            "covered_calendar_days": ["2026-01-01"],
            "target_window_missed": False,
            "no_live_order_sent": True,
        },
        latest_collection={
            "quote_calendar_days": 2,
            "captured_quote_rows_this_cycle": 2,
        },
    )

    assert outcome["status"] == "target_calendar_day_captured"
    assert outcome["target_quote_coverage_kind"] == "next_utc_calendar_day"
    assert outcome["target_utc_date"] == "2026-01-02"
    assert outcome["previous_quote_calendar_days"] == 1
    assert outcome["current_quote_calendar_days"] == 2
    assert outcome["target_calendar_day_covered"] is True
    assert outcome["no_live_order_sent"] is True


def test_pre_run_quote_window_wait_incident_log_appends_missed_window() -> None:
    log = watch._pre_run_quote_window_wait_incident_log(
        previous_payload={
            "pre_run_quote_window_wait_incident_log": [
                {
                    "incident_type": "pre_run_quote_window_target_missed",
                    "woke_at": "2026-01-01T01:00:00+00:00",
                    "no_live_order_sent": True,
                }
            ]
        },
        current_plan={
            "target_window_missed": True,
            "target_window_start_utc": "2026-01-01T12:00:00+00:00",
            "target_window_end_utc": "2026-01-01T13:00:00+00:00",
            "next_missing_utc_hour": "12",
            "sleep_started_at": "2026-01-01T11:55:00+00:00",
            "woke_at": "2026-01-01T14:05:00+00:00",
            "actual_sleep_seconds": 7800.0,
            "wakeup_lag_seconds": 7500.0,
            "overshoot_seconds": 3900.0,
            "overshoot_minutes": 65.0,
            "recovery_action": "rerun_watch_now_to_capture_current_missing_hour_and_recompute_missed_hours",
        },
    )

    assert len(log) == 2
    assert log[-1]["incident_type"] == "pre_run_quote_window_target_missed"
    assert log[-1]["next_missing_utc_hour"] == "12"
    assert log[-1]["overshoot_minutes"] == 65.0
    assert log[-1]["no_live_order_sent"] is True


def test_pre_run_quote_window_wait_incident_log_preserves_previous_when_no_new_incident() -> None:
    log = watch._pre_run_quote_window_wait_incident_log(
        previous_payload={
            "pre_run_quote_window_wait_incident_log": [
                {"incident_type": f"incident_{idx}", "no_live_order_sent": True}
                for idx in range(3)
            ]
        },
        current_plan={"target_window_missed": False},
        max_items=2,
    )

    assert [item["incident_type"] for item in log] == ["incident_1", "incident_2"]


def test_launch_shadow_watch_refreshes_market_data_after_quote_window_sleep(monkeypatch, tmp_path) -> None:
    args = _args(tmp_path)
    args.iterations = 1
    args.sleep_until_next_missing_quote_window = True
    args.max_pre_run_wait_seconds = 86400.0
    args.target_hours = 24.0
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    current_hour = f"{now.hour:02d}"
    next_hour = f"{(now.hour + 1) % 24:02d}"
    next_missing_utc_at = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).isoformat()
    (report_dir / "latest.json").write_text(
        json.dumps(
            {
                "started_at": (now - timedelta(hours=1)).isoformat(),
                "completed_at": (now - timedelta(minutes=5)).isoformat(),
                "no_live_order_sent": True,
                "microstructure_watch": {
                    "coverage_plan": {
                        "status": "waiting_for_next_missing_utc_hour_or_new_calendar_day",
                        "can_collect_now": False,
                        "missing_utc_hour_of_day": [next_hour],
                        "next_missing_utc_at": next_missing_utc_at,
                        "next_missing_utc_hour": next_hour,
                        "current_utc_hour": current_hour,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    evidence_calls = []
    refresh_calls = []

    def fake_run_evidence_cycle(**kwargs):
        evidence_calls.append(kwargs)
        return {
            "overall_status": "healthy_abstention_waiting_for_quality_signal",
            "no_live_order_sent": True,
            "collection_progress": {
                "quote_observed": 330,
                "quote_distinct_hours": 15,
                "captured_quote_rows_this_cycle": 2,
                "paper_fill_rows": 0,
                "quote_coverage": {
                    "utc_hour_of_day_covered": [next_hour],
                    "utc_hour_of_day_missing": [],
                },
            },
            "readiness_progress": {},
            "paper_bridge_apply_gate": {"fresh_signal": False, "can_request_paper_apply_now": False},
            "quote_cadence_preflight": {},
            "market_data_refresh_plan": {"status": "fresh", "fresh_market_data": True},
            "signal_wait_plan": {},
            "launch_readiness": {"status": "research_ready_waiting_for_fresh_signal", "blocking_gates": []},
            "historical_gate_substitution": {},
            "canary_risk_caps_config": {},
        }

    def fake_refresh(**kwargs):
        refresh_calls.append(kwargs)
        return {
            "status": "refreshed",
            "returncode": 0,
            "report_dir": "reports/validation/diagnostics/fake_refresh",
            "no_live_order_sent": True,
        }

    monkeypatch.setattr(watch, "run_evidence_cycle", fake_run_evidence_cycle)

    summary = watch.run_launch_shadow_watch(
        args,
        sleep_fn=lambda seconds: None,
        market_data_refresh_fn=fake_refresh,
    )

    assert len(refresh_calls) == 1
    assert refresh_calls[0]["evidence_root"] == Path(args.evidence_report_root)
    assert len(evidence_calls) == 1
    assert evidence_calls[0]["refresh_market_data_before_run"] is False
    assert summary["pre_run_quote_window_wait_plan"]["status"] == "sleep_until_next_quote_coverage_window"
    assert summary["pre_run_quote_window_capture_outcome"]["status"] == "target_hour_captured"
    assert summary["pre_run_quote_window_capture_outcome"]["target_utc_hour"] == next_hour
    assert summary["pre_run_quote_window_capture_outcome"]["captured_quote_rows_this_cycle"] == 2
    assert summary["pre_run_market_data_refresh"]["status"] == "refreshed"
    assert summary["pre_run_market_data_refresh"]["no_live_order_sent"] is True
    latest_md = (report_dir / "latest.md").read_text(encoding="utf-8")
    assert "pre_run_market_data_refresh_status: `refreshed`" in latest_md
    assert "pre_run_quote_window_capture_status: `target_hour_captured`" in latest_md


def test_launch_shadow_watch_forces_quote_sample_after_hour_of_day_balance_wait(monkeypatch, tmp_path) -> None:
    args = _args(tmp_path)
    args.iterations = 1
    args.sleep_until_next_missing_quote_window = True
    args.max_pre_run_wait_seconds = 86400.0
    args.target_hours = 24.0
    args.disable_market_data_refresh_after_quote_window_sleep = True
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    current_hour = f"{now.hour:02d}"
    next_hour = f"{(now.hour + 1) % 24:02d}"
    next_missing_utc_at = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).isoformat()
    (report_dir / "latest.json").write_text(
        json.dumps(
            {
                "started_at": (now - timedelta(hours=1)).isoformat(),
                "completed_at": (now - timedelta(minutes=5)).isoformat(),
                "no_live_order_sent": True,
                "microstructure_watch": {
                    "coverage_plan": {
                        "status": "waiting_for_next_quote_coverage_window",
                        "can_collect_now": False,
                        "missing_utc_hour_of_day": [next_hour],
                        "next_missing_utc_hour": next_hour,
                        "next_missing_utc_at": next_missing_utc_at,
                        "next_quote_coverage_kind": "missing_hour_of_day_balance_bucket",
                        "next_quote_coverage_at": next_missing_utc_at,
                        "current_utc_hour": current_hour,
                        "hour_of_day_balance_needed": True,
                        "remaining_distinct_hour_bucket_count": 0,
                        "remaining_hour_of_day_bucket_count": 1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    evidence_calls = []

    def fake_run_evidence_cycle(**kwargs):
        evidence_calls.append(kwargs)
        return {
            "overall_status": "healthy_abstention_waiting_for_quality_signal",
            "no_live_order_sent": True,
            "collection_progress": {
                "quote_observed": 368,
                "quote_distinct_hours": 24,
                "captured_quote_rows_this_cycle": 2,
                "paper_fill_rows": 0,
                "quote_coverage": {
                    "utc_hour_of_day_covered": [next_hour],
                    "utc_hour_of_day_missing": [],
                },
            },
            "readiness_progress": {},
            "paper_bridge_apply_gate": {"fresh_signal": False, "can_request_paper_apply_now": False},
            "quote_cadence_preflight": {
                "decision": "forced_quote_capture",
                "force_quote_sample": kwargs["force_quote_sample"],
            },
            "market_data_refresh_plan": {"status": "fresh", "fresh_market_data": True},
            "signal_wait_plan": {},
            "launch_readiness": {"status": "research_ready_waiting_for_fresh_signal", "blocking_gates": []},
            "historical_gate_substitution": {},
            "canary_risk_caps_config": {},
        }

    monkeypatch.setattr(watch, "run_evidence_cycle", fake_run_evidence_cycle)

    summary = watch.run_launch_shadow_watch(args, sleep_fn=lambda seconds: None)

    assert len(evidence_calls) == 1
    assert evidence_calls[0]["force_quote_sample"] is True
    assert summary["latest_run"]["quote_cadence_preflight"]["force_quote_sample"] is True
    assert summary["pre_run_quote_window_wait_plan"]["target_quote_coverage_kind"] == "missing_hour_of_day_balance_bucket"
    assert summary["pre_run_quote_window_capture_outcome"]["status"] == "target_hour_captured"
    assert summary["pre_run_quote_window_capture_outcome"]["target_quote_coverage_kind"] == "missing_hour_of_day_balance_bucket"
    assert summary["no_live_order_sent"] is True


def test_launch_shadow_watch_forces_quote_sample_after_calendar_day_wait(monkeypatch, tmp_path) -> None:
    args = _args(tmp_path)
    args.iterations = 1
    args.sleep_until_next_missing_quote_window = True
    args.max_pre_run_wait_seconds = 86400.0
    args.target_hours = 24.0
    args.disable_market_data_refresh_after_quote_window_sleep = True
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    next_day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    (report_dir / "latest.json").write_text(
        json.dumps(
            {
                "started_at": (now - timedelta(hours=1)).isoformat(),
                "completed_at": (now - timedelta(minutes=5)).isoformat(),
                "no_live_order_sent": True,
                "microstructure_watch": {
                    "coverage_plan": {
                        "status": "waiting_for_next_quote_coverage_window",
                        "can_collect_now": False,
                        "current_utc_date": now.date().isoformat(),
                        "current_utc_date_missing": False,
                        "covered_calendar_days": [now.date().isoformat()],
                        "remaining_calendar_days": 1,
                        "next_quote_coverage_kind": "next_utc_calendar_day",
                        "next_quote_coverage_at": next_day.isoformat(),
                        "next_quote_coverage_kst_at": next_day.astimezone(watch.KST).isoformat(),
                        "calendar_day_count": 1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    evidence_calls = []

    def fake_run_evidence_cycle(**kwargs):
        evidence_calls.append(kwargs)
        return {
            "overall_status": "healthy_abstention_waiting_for_quality_signal",
            "no_live_order_sent": True,
            "collection_progress": {
                "quote_observed": 370,
                "quote_calendar_days": 2,
                "quote_distinct_hours": 24,
                "captured_quote_rows_this_cycle": 2,
                "paper_fill_rows": 0,
            },
            "readiness_progress": {},
            "paper_bridge_apply_gate": {"fresh_signal": False, "can_request_paper_apply_now": False},
            "quote_cadence_preflight": {
                "decision": "forced_quote_capture",
                "force_quote_sample": kwargs["force_quote_sample"],
            },
            "market_data_refresh_plan": {"status": "fresh", "fresh_market_data": True},
            "signal_wait_plan": {},
            "launch_readiness": {"status": "research_ready_waiting_for_fresh_signal", "blocking_gates": []},
            "historical_gate_substitution": {},
            "canary_risk_caps_config": {},
        }

    monkeypatch.setattr(watch, "run_evidence_cycle", fake_run_evidence_cycle)

    summary = watch.run_launch_shadow_watch(args, sleep_fn=lambda seconds: None)

    assert len(evidence_calls) == 1
    assert evidence_calls[0]["force_quote_sample"] is True
    assert summary["latest_run"]["quote_cadence_preflight"]["force_quote_sample"] is True
    assert summary["pre_run_quote_window_wait_plan"]["target_quote_coverage_kind"] == "next_utc_calendar_day"
    assert summary["pre_run_quote_window_capture_outcome"]["status"] == "target_calendar_day_captured"
    assert summary["pre_run_quote_window_capture_outcome"]["target_quote_coverage_kind"] == "next_utc_calendar_day"
    assert summary["no_live_order_sent"] is True


def test_launch_shadow_watch_reuses_previous_started_at_for_heartbeat_accumulation(monkeypatch, tmp_path) -> None:
    args = _args(tmp_path)
    args.iterations = 1
    args.target_hours = 24.0
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    prior_started_at = datetime.now(UTC) - timedelta(hours=2)
    (report_dir / "latest.json").write_text(
        json.dumps({"started_at": prior_started_at.isoformat(), "no_live_order_sent": True}),
        encoding="utf-8",
    )

    def fake_run_evidence_cycle(**kwargs):
        return {
            "overall_status": "healthy_abstention_waiting_for_quality_signal",
            "no_live_order_sent": True,
            "collection_progress": {"quote_observed": 80, "quote_distinct_hours": 8, "paper_fill_rows": 0},
            "readiness_progress": {},
            "paper_bridge_apply_gate": {"fresh_signal": False, "can_request_paper_apply_now": False},
            "signal_wait_plan": {},
            "launch_readiness": {"status": "research_ready_waiting_for_fresh_signal", "blocking_gates": []},
            "historical_gate_substitution": {},
            "canary_risk_caps_config": {},
        }

    monkeypatch.setattr(watch, "run_evidence_cycle", fake_run_evidence_cycle)

    summary = watch.run_launch_shadow_watch(args, sleep_fn=lambda seconds: None)

    assert summary["started_at"] == prior_started_at.isoformat()
    assert summary["observed_hours"] >= 1.9
    assert summary["runtime_observation"]["gap_reset"] is False


def test_historical_shadow_runtime_floor_uses_recent_launch_evidence(tmp_path) -> None:
    generated_at = datetime(2026, 1, 2, 0, 45, tzinfo=UTC)
    early_report_dir = tmp_path / "market_state_rotation_v6_launch_shadow_watch_20260101_120000_i001"
    early_report_dir.mkdir(parents=True)
    early_report = {
        "generated_at": datetime(2026, 1, 1, 12, 0, tzinfo=UTC).isoformat(),
        "launch_readiness": {
            "blocking_gates": [
                {
                    "gate": "shadow_runtime_24h_observed",
                    "detail": {"observed_hours": 0.1},
                }
            ]
        },
    }
    (early_report_dir / "market_state_rotation_v6_evidence_cycle.json").write_text(
        json.dumps(early_report),
        encoding="utf-8",
    )
    contaminated_report_dir = tmp_path / "market_state_rotation_v6_launch_shadow_watch_20260102_005500_i001"
    contaminated_report_dir.mkdir(parents=True)
    contaminated_report = {
        "generated_at": datetime(2026, 1, 2, 0, 55, tzinfo=UTC).isoformat(),
        "launch_readiness": {
            "blocking_gates": [
                {
                    "gate": "shadow_runtime_24h_observed",
                    "detail": {"observed_hours": 15.0},
                }
            ]
        },
    }
    (contaminated_report_dir / "market_state_rotation_v6_evidence_cycle.json").write_text(
        json.dumps(contaminated_report),
        encoding="utf-8",
    )
    report_dir = tmp_path / "market_state_rotation_v6_launch_shadow_watch_20260102_004500_i001"
    report_dir.mkdir(parents=True)
    report = {
        "generated_at": generated_at.isoformat(),
        "launch_readiness": {
            "blocking_gates": [
                {
                    "gate": "shadow_runtime_24h_observed",
                    "detail": {"observed_hours": 10.5},
                }
            ]
        },
    }
    (report_dir / "market_state_rotation_v6_evidence_cycle.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    floor = watch._historical_shadow_runtime_floor(
        evidence_root=tmp_path,
        current_at=datetime(2026, 1, 2, 1, 0, tzinfo=UTC),
        min_recovered_start_at=datetime(2026, 1, 1, 13, 0, tzinfo=UTC),
    )

    assert floor["status"] == "available"
    assert floor["source_observed_hours"] == 10.5
    assert floor["recovered_continuous_started_at"] == "2026-01-01T14:15:00+00:00"
    assert floor["projected_observed_hours"] == 10.75
    assert floor["no_live_order_sent"] is True


def test_continuous_runtime_start_recovers_recent_underflow_from_runtime_floor() -> None:
    current_at = datetime(2026, 1, 2, 1, 0, tzinfo=UTC)
    floor_start = datetime(2026, 1, 1, 14, 15, tzinfo=UTC)

    plan = watch._continuous_runtime_start(
        previous_payload={
            "completed_at": (current_at - timedelta(seconds=30)).isoformat(),
            "runtime_observation": {
                "continuous_started_at": (current_at - timedelta(minutes=1)).isoformat(),
                "gap_reset": False,
            },
        },
        fallback_started_at=current_at - timedelta(hours=15),
        current_at=current_at,
        interval_seconds=0.0,
        runtime_floor={
            "status": "available",
            "recovered_continuous_started_at": floor_start.isoformat(),
            "projected_observed_hours": 10.75,
            "source_report": "reports/validation/diagnostics/floor/market_state_rotation_v6_evidence_cycle.json",
            "no_live_order_sent": True,
        },
    )

    assert plan["continuous_started_at"] == floor_start
    assert plan["runtime_floor_recovered"] is True
    assert plan["gap_reset"] is False
    assert plan["runtime_floor"]["status"] == "available"


def test_continuous_runtime_start_replaces_weaker_prior_floor_recovery() -> None:
    current_at = datetime(2026, 1, 2, 1, 0, tzinfo=UTC)
    stronger_floor_start = datetime(2026, 1, 1, 14, 15, tzinfo=UTC)

    plan = watch._continuous_runtime_start(
        previous_payload={
            "completed_at": (current_at - timedelta(seconds=30)).isoformat(),
            "runtime_observation": {
                "continuous_started_at": datetime(2026, 1, 1, 9, 54, tzinfo=UTC).isoformat(),
                "gap_reset": False,
                "runtime_floor_recovered": True,
                "runtime_floor": {
                    "source_observed_hours": 0.02,
                    "recovered_continuous_started_at": datetime(2026, 1, 1, 9, 54, tzinfo=UTC).isoformat(),
                },
            },
        },
        fallback_started_at=current_at - timedelta(hours=15),
        current_at=current_at,
        interval_seconds=0.0,
        runtime_floor={
            "status": "available",
            "recovered_continuous_started_at": stronger_floor_start.isoformat(),
            "projected_observed_hours": 10.75,
            "source_observed_hours": 10.5,
            "no_live_order_sent": True,
        },
    )

    assert plan["continuous_started_at"] == stronger_floor_start
    assert plan["runtime_floor_recovered"] is True


def test_continuous_runtime_start_clamps_start_before_operation_to_floor() -> None:
    current_at = datetime(2026, 1, 2, 1, 0, tzinfo=UTC)
    operation_started_at = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    floor_start = datetime(2026, 1, 1, 14, 15, tzinfo=UTC)

    plan = watch._continuous_runtime_start(
        previous_payload={
            "completed_at": (current_at - timedelta(seconds=30)).isoformat(),
            "runtime_observation": {
                "continuous_started_at": datetime(2026, 1, 1, 9, 54, tzinfo=UTC).isoformat(),
                "gap_reset": False,
            },
        },
        fallback_started_at=operation_started_at,
        current_at=current_at,
        interval_seconds=0.0,
        runtime_floor={
            "status": "available",
            "recovered_continuous_started_at": floor_start.isoformat(),
            "projected_observed_hours": 10.75,
            "source_observed_hours": 10.5,
            "no_live_order_sent": True,
        },
    )

    assert plan["continuous_started_at"] == floor_start
    assert plan["runtime_floor_recovered"] is True
    assert plan["runtime_start_clamped_to_operation_start"] is True


def test_continuous_runtime_start_preserves_scheduled_signal_monitor_gap() -> None:
    previous_completed_at = datetime(2026, 1, 1, 9, 38, 45, tzinfo=UTC)
    current_at = datetime(2026, 1, 1, 10, 39, 14, tzinfo=UTC)
    continuous_started_at = datetime(2025, 12, 31, 14, 13, 50, tzinfo=UTC)

    plan = watch._continuous_runtime_start(
        previous_payload={
            "completed_at": previous_completed_at.isoformat(),
            "runtime_observation": {
                "continuous_started_at": continuous_started_at.isoformat(),
                "gap_reset": False,
            },
            "safe_next_action_plan": {
                "primary_action": {
                    "action_type": "monitor_fresh_signal",
                    "target_gate": "current_fresh_signal",
                    "execute_after_utc": datetime(2026, 1, 1, 10, 38, 14, tzinfo=UTC).isoformat(),
                    "order_submission_allowed": False,
                    "no_live_order_sent": True,
                }
            },
            "no_live_order_sent": True,
        },
        fallback_started_at=continuous_started_at,
        current_at=current_at,
        interval_seconds=0.0,
        runtime_floor={
            "status": "available",
            "recovered_continuous_started_at": continuous_started_at.isoformat(),
            "projected_observed_hours": 20.42,
            "source_observed_hours": 19.41,
            "no_live_order_sent": True,
        },
    )

    assert plan["continuous_started_at"] == continuous_started_at
    assert plan["gap_reset"] is False
    assert plan["gap_warning"] is None
    assert plan["watch_continuity"]["status"] == "continuous"
    assert plan["watch_continuity"]["planned_gap_extension"]["status"] == "planned_gap_allowed"


def test_continuous_runtime_start_preserves_quote_window_gap_after_earlier_signal_monitor_expires() -> None:
    previous_completed_at = datetime(2026, 1, 1, 10, 44, 0, tzinfo=UTC)
    current_at = datetime(2026, 1, 1, 12, 0, 30, tzinfo=UTC)
    continuous_started_at = datetime(2025, 12, 31, 15, 13, 50, tzinfo=UTC)

    plan = watch._continuous_runtime_start(
        previous_payload={
            "completed_at": previous_completed_at.isoformat(),
            "runtime_observation": {
                "continuous_started_at": continuous_started_at.isoformat(),
                "gap_reset": False,
            },
            "safe_next_action_plan": {
                "primary_action": {
                    "action_type": "monitor_fresh_signal",
                    "target_gate": "current_fresh_signal",
                    "execute_after_utc": datetime(2026, 1, 1, 11, 44, 0, tzinfo=UTC).isoformat(),
                    "order_submission_allowed": False,
                    "no_live_order_sent": True,
                },
                "next_deferred_wait_action": {
                    "action_type": "wait_for_next_microstructure_quote_window",
                    "target_gate": "real_microstructure_execution_evidence",
                    "execute_after_utc": datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC).isoformat(),
                    "waits_until_execution_window": True,
                    "deferred_by_earlier_scheduled_action": True,
                    "order_submission_allowed": False,
                    "no_live_order_sent": True,
                },
            },
            "no_live_order_sent": True,
        },
        fallback_started_at=continuous_started_at,
        current_at=current_at,
        interval_seconds=0.0,
        runtime_floor={
            "status": "available",
            "recovered_continuous_started_at": continuous_started_at.isoformat(),
            "projected_observed_hours": 20.75,
            "source_observed_hours": 19.5,
            "no_live_order_sent": True,
        },
    )

    assert plan["continuous_started_at"] == continuous_started_at
    assert plan["gap_reset"] is False
    assert plan["watch_continuity"]["status"] == "continuous"
    assert plan["watch_continuity"]["planned_gap_extension"]["source"] == "next_deferred_wait_action"
    assert plan["watch_continuity"]["planned_gap_extension"]["action_type"] == "wait_for_next_microstructure_quote_window"


def test_continuous_runtime_start_resets_after_expired_scheduled_gap() -> None:
    previous_completed_at = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    current_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    continuous_started_at = datetime(2025, 12, 31, 14, 0, tzinfo=UTC)

    plan = watch._continuous_runtime_start(
        previous_payload={
            "completed_at": previous_completed_at.isoformat(),
            "runtime_observation": {
                "continuous_started_at": continuous_started_at.isoformat(),
                "gap_reset": False,
            },
            "safe_next_action_plan": {
                "primary_action": {
                    "action_type": "monitor_fresh_signal",
                    "target_gate": "current_fresh_signal",
                    "execute_after_utc": datetime(2026, 1, 1, 10, 0, tzinfo=UTC).isoformat(),
                    "order_submission_allowed": False,
                    "no_live_order_sent": True,
                }
            },
            "no_live_order_sent": True,
        },
        fallback_started_at=continuous_started_at,
        current_at=current_at,
        interval_seconds=0.0,
        runtime_floor={
            "status": "available",
            "recovered_continuous_started_at": continuous_started_at.isoformat(),
            "projected_observed_hours": 22.0,
            "source_observed_hours": 19.0,
            "no_live_order_sent": True,
        },
    )

    assert plan["continuous_started_at"] == current_at
    assert plan["gap_reset"] is True
    assert plan["gap_warning"] == "watch_gap_exceeded_threshold"
    assert plan["watch_continuity"]["planned_gap_extension"]["status"] == "planned_gap_expired"


def test_continuous_runtime_start_does_not_recover_floor_after_gap_warning() -> None:
    current_at = datetime(2026, 1, 2, 1, 0, tzinfo=UTC)

    plan = watch._continuous_runtime_start(
        previous_payload={
            "completed_at": (current_at - timedelta(hours=3)).isoformat(),
            "runtime_observation": {
                "continuous_started_at": (current_at - timedelta(hours=20)).isoformat(),
                "gap_reset": False,
            },
        },
        fallback_started_at=current_at - timedelta(hours=20),
        current_at=current_at,
        interval_seconds=0.0,
        runtime_floor={
            "status": "available",
            "recovered_continuous_started_at": (current_at - timedelta(hours=12)).isoformat(),
            "projected_observed_hours": 12.0,
            "no_live_order_sent": True,
        },
    )

    assert plan["continuous_started_at"] == current_at
    assert plan["runtime_floor_recovered"] is False
    assert plan["gap_reset"] is True


def test_launch_shadow_watch_resets_continuous_runtime_after_large_gap(monkeypatch, tmp_path) -> None:
    calls = []
    args = _args(tmp_path)
    args.iterations = 1
    args.target_hours = 24.0
    args.interval_seconds = 0.0
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    prior_started_at = datetime.now(UTC) - timedelta(hours=24)
    prior_completed_at = datetime.now(UTC) - timedelta(hours=3)
    (report_dir / "latest.json").write_text(
        json.dumps(
            {
                "started_at": prior_started_at.isoformat(),
                "completed_at": prior_completed_at.isoformat(),
                "no_live_order_sent": True,
                "runtime_observation": {
                    "continuous_started_at": prior_started_at.isoformat(),
                    "continuous_observed_hours": 21.0,
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_run_evidence_cycle(**kwargs):
        calls.append(kwargs)
        return {
            "overall_status": "healthy_abstention_waiting_for_quality_signal",
            "no_live_order_sent": True,
            "collection_progress": {"quote_observed": 80, "quote_distinct_hours": 8, "paper_fill_rows": 0},
            "readiness_progress": {},
            "paper_bridge_apply_gate": {"fresh_signal": False, "can_request_paper_apply_now": False},
            "signal_wait_plan": {},
            "launch_readiness": {"status": "research_ready_waiting_for_fresh_signal", "blocking_gates": []},
            "historical_gate_substitution": {},
            "canary_risk_caps_config": {},
        }

    monkeypatch.setattr(watch, "run_evidence_cycle", fake_run_evidence_cycle)

    summary = watch.run_launch_shadow_watch(args, sleep_fn=lambda seconds: None)

    assert summary["calendar_elapsed_hours"] >= 23.9
    assert summary["observed_hours"] < 0.1
    assert summary["runtime_observation"]["gap_reset"] is True
    assert summary["runtime_observation"]["gap_warning"] == "watch_gap_exceeded_threshold"
    assert summary["target_observation_complete"] is False
    assert calls[0]["shadow_runtime_observed_hours"] < 0.1


def test_launch_shadow_watch_keeps_previous_quote_baseline_for_heartbeat_delta(monkeypatch, tmp_path) -> None:
    args = _args(tmp_path)
    args.iterations = 1
    args.target_hours = 24.0
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    prior_started_at = datetime.now(UTC) - timedelta(hours=3)
    prior_completed_at = datetime.now(UTC) - timedelta(minutes=30)
    (report_dir / "latest.json").write_text(
        json.dumps(
            {
                "started_at": prior_started_at.isoformat(),
                "completed_at": prior_completed_at.isoformat(),
                "no_live_order_sent": True,
                "baseline_collection_progress": {
                    "quote_observed": 70,
                    "quote_distinct_hours": 6,
                    "paper_fill_rows": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_run_evidence_cycle(**kwargs):
        return {
            "overall_status": "healthy_abstention_waiting_for_quality_signal",
            "no_live_order_sent": True,
            "collection_progress": {"quote_observed": 84, "quote_distinct_hours": 9, "paper_fill_rows": 0},
            "readiness_progress": {},
            "paper_bridge_apply_gate": {"fresh_signal": False, "can_request_paper_apply_now": False},
            "signal_wait_plan": {},
            "launch_readiness": {"status": "research_ready_waiting_for_fresh_signal", "blocking_gates": []},
            "historical_gate_substitution": {},
            "canary_risk_caps_config": {},
        }

    monkeypatch.setattr(watch, "run_evidence_cycle", fake_run_evidence_cycle)

    summary = watch.run_launch_shadow_watch(args, sleep_fn=lambda seconds: None)

    assert summary["progress"]["quote_observed_start"] == 70
    assert summary["progress"]["quote_observed_delta"] == 14
    assert summary["progress"]["quote_progress_state"] == "progressing"
    assert summary["progress"]["quote_distinct_hours_delta"] == 3
    assert summary["watch_continuity"]["status"] == "continuous"


def test_launch_shadow_watch_reports_microstructure_trend_and_operator_handoff(monkeypatch, tmp_path) -> None:
    args = _args(tmp_path)
    args.iterations = 1
    args.target_hours = 24.0
    sample_path = Path(args.sample_jsonl)
    now = datetime.now(UTC).replace(minute=30, second=0, microsecond=0)
    rows = [
        build_quote_shadow_row(
            order_book=_book(),
            timestamp=now - timedelta(minutes=idx),
            symbol="BTCUSDT",
            strategy_family="market_state_rotation_v6",
            decision_id=f"quote_{idx}",
            side="long" if idx % 2 == 0 else "short",
            order_notional_usdt=100.0,
            latency_ms=80.0,
        )
        for idx in range(4)
    ]
    sample_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "latest.json").write_text(
        json.dumps(
            {
                "started_at": (now - timedelta(hours=1)).isoformat(),
                "completed_at": (now - timedelta(minutes=30)).isoformat(),
                "no_live_order_sent": True,
                "microstructure_watch": {
                    "baseline_metrics": {
                        "p95_spread_bps": 1.0,
                        "p95_market_slippage_bps": 1.0,
                        "p95_latency_ms": 200.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_run_evidence_cycle(**kwargs):
        return {
            "overall_status": "healthy_abstention_waiting_for_quality_signal",
            "no_live_order_sent": True,
            "collection_progress": {
                "quote_observed": 4,
                "quote_required": 10,
                "quote_distinct_hours": 1,
                "quote_min_distinct_hours": 3,
                "quote_calendar_days": 1,
                "quote_min_calendar_days": 2,
                "paper_fill_rows": 0,
            },
            "readiness_progress": {},
            "paper_bridge_apply_gate": {"fresh_signal": False, "can_request_paper_apply_now": False},
            "signal_wait_plan": {},
            "launch_readiness": {
                "status": "research_ready_waiting_for_fresh_signal",
                "tiny_canary_evidence_ready": False,
                "next_blocker": {"gate": "current_fresh_signal"},
                "blocking_gates": [{"gate": "current_fresh_signal", "passed": False}],
                "paper_bridge_handoff": {
                    "status": "blocked_waiting_for_fresh_signal",
                    "apply_allowed_now": False,
                    "dry_run_command": "dry-run",
                    "apply_command": "apply",
                },
                "operator_commands": {"microstructure_quote_capture": "capture"},
            },
            "historical_gate_substitution": {},
            "canary_risk_caps_config": {
                "configured": False,
                "status": "missing_optional_config_file",
                "errors": ["max_notional_usdt_must_be_positive"],
            },
        }

    monkeypatch.setattr(watch, "run_evidence_cycle", fake_run_evidence_cycle)

    summary = watch.run_launch_shadow_watch(args, sleep_fn=lambda seconds: None)

    micro = summary["microstructure_watch"]
    assert micro["status"] == "collecting_sample_day_hour_coverage"
    assert micro["eligible_row_count"] == 4
    assert micro["recent_eligible_row_count"] == 4
    assert micro["metric_blockers"] == []
    assert micro["metric_trend"]["p95_latency_ms"]["direction"] == "improved"
    assert micro["calendar_day_count"] == 1
    assert micro["min_calendar_days"] == 2
    assert micro["distinct_hour_count"] == 1
    assert micro["coverage_plan"]["remaining_quote_samples"] == 6
    assert micro["coverage_plan"]["can_collect_now"] is True
    assert micro["coverage_plan"]["recommended_action"] == "collect_quote_samples_now"
    handoff = summary["operator_handoff"]
    assert handoff["status"] == "waiting_for_fresh_signal_and_canary_risk_caps"
    assert handoff["paper_apply_allowed_now"] is False
    assert handoff["order_submission_allowed"] is False
    assert handoff["canary_review_blockers"] == ["current_fresh_signal"]
