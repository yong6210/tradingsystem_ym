# Operator Surface Divergence Snapshot

- generated_at: 2026-03-23T21:39:05.919233+00:00
- symbol: BTCUSDC
- universe: usdc_perp_top30
- days: 7
- deployment_alignment: DIVERGED
- playbook_alignment: DIVERGED

## Dashboard / Validation / Checklist

- dashboard: GO / continue_candidate_review_under_portfolio_caps / top_action=continue_candidate_review_under_portfolio_caps
- validation: NO_GO / resolve_selected_trial_lineage_before_rollout / approval_topline_status=REVIEW
- checklist: NO_GO / resolve_selected_trial_lineage_before_rollout / overall_status=FAIL

## Operator UI Sections

- [PASS] Approval Divergence
- [PASS] Validation Case Inspector
- [PASS] Runtime Quality Inspector
- [PASS] Signal Funnel Inspector
- [PASS] Alpha Research Inspector
- [PASS] Policy / Lock Inspector
- [PASS] Intent / Exposure Inspector
- [PASS] Mode / Deployment Inspector
- [PASS] Approval Alignment Inspector
- [PASS] Data Freshness / Source Inspector
- [PASS] Portfolio Candidate Inspector
- [PASS] Report Navigation

## Signal Funnel Snapshot

- research_action: run_shadow_exit_timing_review
- shadow_experiment: shadow_exit_timing_family
- governance_state: defer
- review_queue: defer_first_queue
- remediation_queue: observe_only_queue
- clearance_state: observe_only
- reopen_queue: observe_only_queue
- decision_brief: observe_case
- auto_execution_stage: auto_execution_blocked

## Next Steps

- dashboard와 validation/checklist의 deployment_go_no_go 방향을 함께 읽고 Approval Divergence 배너 wording을 먼저 확인한다.
- playbook_action drift가 있으면 rollout 승인보다 wording/source drift를 먼저 점검한다.

## Raw Payload

```json
{
  "generated_at": "2026-03-23T21:39:05.919233+00:00",
  "symbol": "BTCUSDC",
  "universe": "usdc_perp_top30",
  "days": 7,
  "deployment_alignment": "DIVERGED",
  "playbook_alignment": "DIVERGED",
  "dashboard_summary": {
    "execution_mode": "PAPER",
    "new_entries_allowed": true,
    "deployment_go_no_go": "GO",
    "playbook_action": "continue_candidate_review_under_portfolio_caps",
    "top_operator_action": "continue_candidate_review_under_portfolio_caps",
    "recent_intents": 0,
    "open_orders": 0,
    "open_positions": 0
  },
  "validation_summary": {
    "deployment_go_no_go": "NO_GO",
    "deployment_code": "no_go_threshold_lineage_winner_unresolved",
    "deployment_message": "NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.",
    "playbook_action": "resolve_selected_trial_lineage_before_rollout",
    "approval_topline_status": "REVIEW"
  },
  "checklist_summary": {
    "deployment_go_no_go": "NO_GO",
    "deployment_code": "no_go_threshold_lineage_winner_unresolved",
    "deployment_message": "NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.",
    "playbook_action": "resolve_selected_trial_lineage_before_rollout",
    "overall_status": "FAIL",
    "blocking_failures": 1,
    "manual_actions": 0,
    "warnings": 14
  },
  "operator_ui_sections": {
    "expected_sections": [
      "Approval Divergence",
      "Validation Case Inspector",
      "Runtime Quality Inspector",
      "Signal Funnel Inspector",
      "Alpha Research Inspector",
      "Policy / Lock Inspector",
      "Intent / Exposure Inspector",
      "Mode / Deployment Inspector",
      "Approval Alignment Inspector",
      "Data Freshness / Source Inspector",
      "Portfolio Candidate Inspector",
      "Report Navigation"
    ],
    "present_sections": [
      "Approval Divergence",
      "Validation Case Inspector",
      "Runtime Quality Inspector",
      "Signal Funnel Inspector",
      "Alpha Research Inspector",
      "Policy / Lock Inspector",
      "Intent / Exposure Inspector",
      "Mode / Deployment Inspector",
      "Approval Alignment Inspector",
      "Data Freshness / Source Inspector",
      "Portfolio Candidate Inspector",
      "Report Navigation"
    ],
    "missing_sections": [],
    "all_present": true
  },
  "signal_funnel_snapshot": {
    "research_action": "run_shadow_exit_timing_review",
    "shadow_experiment": "shadow_exit_timing_family",
    "governance_state": "defer",
    "review_queue": "defer_first_queue",
    "remediation_queue": "observe_only_queue",
    "clearance_state": "observe_only",
    "reopen_queue": "observe_only_queue",
    "decision_brief": "observe_case",
    "auto_execution_stage": "auto_execution_blocked",
    "hard_gate_bottleneck": "thesis_duplicate_blocked",
    "softening_priority_queue": [],
    "rollout_block_reason": "",
    "top_family_bottleneck": "legacy_zone_plan",
    "top_regime_bottleneck": "range",
    "top_session_bottleneck": "dead_session"
  },
  "next_steps": [
    "dashboard와 validation/checklist의 deployment_go_no_go 방향을 함께 읽고 Approval Divergence 배너 wording을 먼저 확인한다.",
    "playbook_action drift가 있으면 rollout 승인보다 wording/source drift를 먼저 점검한다."
  ]
}
```