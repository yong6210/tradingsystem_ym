from app.services.deployment_contracts import (
    alert_contract_defaults,
    approval_summary_passthrough,
    validation_alert_contract,
    validation_alert_strip_summary,
    validation_report_contract,
)


def test_approval_summary_passthrough_maps_summary_fields() -> None:
    summary = {
        "topline_status": "REVIEW REQUIRED",
        "topline_code": "review_required_proxy_selected",
        "topline_message": "REVIEW REQUIRED: proxy lineage selected-trial remains active.",
        "topline_summary_line": "winner=runtime_proxy; worst=shock/FAIL/replay_output; promotion=stay_on_prototype",
        "playbook_go_no_go": "NO_GO",
        "playbook_code": "no_go_proxy_selected_trial_against_replay_backed_worst_scenario",
        "playbook_action": "hold_live_rollout_and_keep_prototype_path",
        "playbook_message": "NO_GO: keep prototype path until threshold lineage wins.",
    }

    contract = approval_summary_passthrough(summary)

    assert contract["deployment_go_no_go"] == "NO_GO"
    assert contract["deployment_code"] == "no_go_proxy_selected_trial_against_replay_backed_worst_scenario"
    assert contract["deployment_message"] == "NO_GO: keep prototype path until threshold lineage wins."
    assert contract["approval_topline_status"] == "REVIEW REQUIRED"
    assert contract["approval_topline_code"] == "review_required_proxy_selected"
    assert contract["approval_topline_summary_line"] == (
        "validation_lineage=runtime_proxy; worst=shock/FAIL/replay_output; recommended_action=stay_on_prototype"
    )
    assert contract["playbook_action"] == "hold_live_rollout_and_keep_prototype_path"


def test_validation_report_contract_prefers_top_level_then_falls_back_to_nested_summary() -> None:
    payload = {
        "validation_report": {
            "deployment_approval_summary": {
                "topline_status": "REVIEW REQUIRED",
                "topline_code": "review_required_nested",
                "topline_message": "nested message",
                "topline_summary_line": "nested summary",
                "playbook_go_no_go": "MANUAL_REVIEW",
                "playbook_code": "manual_review_nested",
                "playbook_action": "review_nested",
                "playbook_message": "nested playbook",
            }
        },
        "deployment_go_no_go": "GO",
        "deployment_code": "go_top_level",
        "deployment_message": "top level deployment",
        "approval_topline_status": "APPROVED",
        "approval_topline_code": "approved_top_level",
        "approval_topline_message": "topline top level",
        "approval_topline_summary_line": "top level summary",
        "playbook_go_no_go": "GO",
        "playbook_code": "go_top_level",
        "playbook_action": "ship_top_level",
        "playbook_message": "ship now",
    }

    contract = validation_report_contract(payload)

    assert contract["deployment_go_no_go"] == "GO"
    assert contract["deployment_code"] == "go_top_level"
    assert contract["approval_topline_status"] == "APPROVED"
    assert contract["playbook_action"] == "ship_top_level"

    nested_only = validation_report_contract({"validation_report": payload["validation_report"]})
    assert nested_only["deployment_go_no_go"] == "MANUAL_REVIEW"
    assert nested_only["deployment_code"] == "manual_review_nested"
    assert nested_only["approval_topline_summary_line"] == "nested summary"
    assert nested_only["playbook_action"] == "review_nested"


def test_validation_report_contract_ignores_malformed_nested_summary() -> None:
    contract = validation_report_contract(
        {
            "validation_report": {
                "deployment_approval_summary": ["broken"],
            },
            "playbook_go_no_go": "MANUAL_REVIEW",
            "playbook_action": "hold_rollout_and_review_alignment_details",
        }
    )

    assert contract["playbook_go_no_go"] == "MANUAL_REVIEW"
    assert contract["playbook_action"] == "hold_rollout_and_review_alignment_details"
    assert contract["deployment_go_no_go"] == ""


def test_validation_alert_contract_accepts_plain_playbook_fields() -> None:
    contract = validation_alert_contract(
        {
            "topline_summary_line": "winner=true_threshold; worst=latency/WARN/approximation; promotion=stay_on_prototype",
            "playbook_go_no_go": "MANUAL_REVIEW",
            "playbook_code": "manual_review_alignment_check",
            "playbook_action": "review_alignment_before_rollout",
            "playbook_message": "MANUAL_REVIEW: review alignment before rollout.",
        }
    )

    assert contract["deployment_go_no_go"] == "MANUAL_REVIEW"
    assert contract["deployment_code"] == "manual_review_alignment_check"
    assert contract["deployment_message"] == "MANUAL_REVIEW: review alignment before rollout."
    assert contract["approval_topline_summary_line"] == (
        "validation_lineage=true_threshold; worst=latency/WARN/approximation; recommended_action=stay_on_prototype"
    )
    assert contract["approval_playbook_go_no_go"] == "MANUAL_REVIEW"
    assert contract["approval_playbook_action"] == "review_alignment_before_rollout"


def test_validation_alert_strip_summary_derives_operator_vocabulary() -> None:
    summary = validation_alert_strip_summary(
        {
            "approval_topline_summary_line": "winner=true_threshold; worst=latency/WARN/approximation; promotion=stay_on_prototype",
            "deployment_go_no_go": "MANUAL_REVIEW",
            "deployment_message": "MANUAL_REVIEW: review alignment before rollout.",
            "approval_playbook_go_no_go": "MANUAL_REVIEW",
            "approval_playbook_action": "review_alignment_before_rollout",
            "approval_playbook_message": "MANUAL_REVIEW: review alignment before rollout.",
        }
    )

    assert summary["approve_value"] == "manual review first"
    assert summary["align_value"] == "aligned"
    assert summary["act_value"] == "review_alignment_before_rollout"
    assert summary["act_priority_level"] == "watch"
    assert summary["primary_reason"].startswith("validation_lineage=true_threshold;")


def test_validation_alert_strip_summary_ignores_malformed_existing_strip() -> None:
    summary = validation_alert_strip_summary(
        {
            "approval_strip_summary": ["broken"],
            "deployment_go_no_go": "GO",
            "approval_playbook_go_no_go": "GO",
            "approval_playbook_action": "proceed_with_configured_rollout",
        }
    )

    assert summary["approve_value"] == "approval usable"
    assert summary["act_value"] == "proceed_with_configured_rollout"


def test_validation_alert_strip_summary_normalizes_legacy_go_language() -> None:
    summary = validation_alert_strip_summary(
        {
            "approval_strip_summary": {
                "primary_reason": "winner=true_threshold/v2; worst=latency/PASS/replay_output; promotion=keep_current_path",
                "approve_value": "approval usable",
                "approve_reason": (
                    "GO: approval template is aligned with replay-backed downside and the current threshold-lineage winner."
                ),
                "align_value": "aligned",
                "align_reason": (
                    "GO: approval template is aligned with replay-backed downside and the current threshold-lineage winner."
                ),
                "act_value": "proceed_with_configured_rollout",
                "act_reason": (
                    "GO: approval template is aligned with replay-backed downside and the current threshold-lineage winner."
                ),
            }
        }
    )

    assert summary["primary_reason"].startswith("validation_lineage=true_threshold/")
    assert "recommended_action=keep_current_path" in summary["primary_reason"]
    assert summary["approve_reason"] == (
        "GO: approval template is aligned with the configured replay-backed validation evidence."
    )
    assert summary["align_reason"] == (
        "GO: approval template is aligned with the configured replay-backed validation evidence."
    )


def test_alert_contract_defaults_fills_manual_review_when_contract_is_missing() -> None:
    contract = alert_contract_defaults({})

    assert contract["deployment_go_no_go"] == "MANUAL_REVIEW"
    assert contract["deployment_code"] == "manual_review_approval_template_missing"
    assert contract["deployment_message"] == "MANUAL REVIEW: approval template deployment language is unavailable."
    assert contract["approval_playbook_go_no_go"] == ""
