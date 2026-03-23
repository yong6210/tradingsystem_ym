# Operator Session Brief Automation Health

- generated_at: 2026-03-23T17:23:39.022914+00:00
- healthy: True
- channel: system
- max_age_minutes: 30

## Agents

- shift_start: healthy=True state=not running last_exit_code=0 runs=3 mode=shift-start channel=system dry_run=1
- shift_end: healthy=True state=not running last_exit_code=0 runs=3 mode=shift-end channel=system dry_run=1

## Artifacts

- shift_start_latest: healthy=True exists=True modified_at=2026-03-23T17:23:35.872129+00:00 age_seconds=3.150531
- shift_end_latest: healthy=True exists=True modified_at=2026-03-23T17:23:35.906926+00:00 age_seconds=3.115858
- shift_start_state: healthy=True exists=True modified_at=2026-03-23T17:23:35.871886+00:00 age_seconds=3.150949
- shift_end_state: healthy=True exists=True modified_at=2026-03-23T17:23:35.906714+00:00 age_seconds=3.116167

## Issues

- none

## Raw Payload

```json
{
  "generated_at": "2026-03-23T17:23:39.022914+00:00",
  "channel": "system",
  "max_age_minutes": 30,
  "healthy": true,
  "issues": [],
  "agents": {
    "shift_start": {
      "label": "com.yumin.trading.operator-brief-shift-start",
      "state": "not running",
      "last_exit_code": 0,
      "runs": 3,
      "working_directory": "/Users/yumin/Documents/trading",
      "stdout_path": "/Users/yumin/Documents/trading/reports/operations/operator_session_briefs/launchd.shift_start.out.log",
      "stderr_path": "/Users/yumin/Documents/trading/reports/operations/operator_session_briefs/launchd.shift_start.err.log",
      "brief_mode": "shift-start",
      "channel": "system",
      "dry_run": "1",
      "healthy": true,
      "issues": []
    },
    "shift_end": {
      "label": "com.yumin.trading.operator-brief-shift-end",
      "state": "not running",
      "last_exit_code": 0,
      "runs": 3,
      "working_directory": "/Users/yumin/Documents/trading",
      "stdout_path": "/Users/yumin/Documents/trading/reports/operations/operator_session_briefs/launchd.shift_end.out.log",
      "stderr_path": "/Users/yumin/Documents/trading/reports/operations/operator_session_briefs/launchd.shift_end.err.log",
      "brief_mode": "shift-end",
      "channel": "system",
      "dry_run": "1",
      "healthy": true,
      "issues": []
    }
  },
  "artifacts": {
    "shift_start_latest": {
      "path": "/Users/yumin/Documents/trading/reports/operations/operator_session_briefs/latest_operator_session_brief_shift_start.json",
      "exists": true,
      "modified_at": "2026-03-23T17:23:35.872129+00:00",
      "age_seconds": 3.150531,
      "healthy": true,
      "issues": [],
      "payload": {
        "brief_mode": "shift-start",
        "brief_report_path": "reports/operations/operator_session_briefs/operator_session_brief_BTCUSDC_20260323T172334Z.md",
        "changed": false,
        "channel": "system",
        "current": {
          "brief_mode": "shift-start",
          "brief_report_path": "reports/operations/operator_session_briefs/operator_session_brief_BTCUSDC_20260323T172334Z.md",
          "brief_status": "DEPLOYMENT_REVIEW_REQUIRED",
          "channel": "system",
          "checklist_go_no_go": "NO_GO",
          "checklist_playbook_action": "resolve_selected_trial_lineage_before_rollout",
          "dashboard_go_no_go": "GO",
          "dashboard_playbook_action": "continue_candidate_review_under_portfolio_caps",
          "deployment_alignment": "DIVERGED",
          "headline": "dashboard and validation/checklist disagree on deployment posture; dashboard=GO, validation=NO_GO, checklist=NO_GO.",
          "playbook_alignment": "DIVERGED",
          "research_action": "run_shadow_exit_timing_review",
          "snapshot_report_path": "reports/operations/operator_surface_divergence/operator_surface_divergence_BTCUSDC_20260323T172335Z.md",
          "symbol": "BTCUSDC",
          "top_family_bottleneck": "legacy_zone_plan",
          "top_operator_action": "continue_candidate_review_under_portfolio_caps",
          "top_session_bottleneck": "preferred_live_window",
          "ui_all_present": true,
          "universe": "usdc_perp_top30",
          "validation_go_no_go": "NO_GO",
          "validation_playbook_action": "resolve_selected_trial_lineage_before_rollout"
        },
        "dry_run": true,
        "force_send": false,
        "notified": false,
        "previous": {
          "brief_mode": "shift-start",
          "brief_report_path": "reports/operations/operator_session_briefs/operator_session_brief_BTCUSDC_20260323T171911Z.md",
          "brief_status": "DEPLOYMENT_REVIEW_REQUIRED",
          "channel": "system",
          "checklist_go_no_go": "NO_GO",
          "checklist_playbook_action": "resolve_selected_trial_lineage_before_rollout",
          "dashboard_go_no_go": "GO",
          "dashboard_playbook_action": "continue_candidate_review_under_portfolio_caps",
          "deployment_alignment": "DIVERGED",
          "headline": "dashboard and validation/checklist disagree on deployment posture; dashboard=GO, validation=NO_GO, checklist=NO_GO.",
          "playbook_alignment": "DIVERGED",
          "research_action": "run_shadow_exit_timing_review",
          "snapshot_report_path": "reports/operations/operator_surface_divergence/operator_surface_divergence_BTCUSDC_20260323T171912Z.md",
          "symbol": "BTCUSDC",
          "top_family_bottleneck": "legacy_zone_plan",
          "top_operator_action": "continue_candidate_review_under_portfolio_caps",
          "top_session_bottleneck": "preferred_live_window",
          "ui_all_present": true,
          "universe": "usdc_perp_top30",
          "validation_go_no_go": "NO_GO",
          "validation_playbook_action": "resolve_selected_trial_lineage_before_rollout"
        },
        "snapshot_report_path": "reports/operations/operator_surface_divergence/operator_surface_divergence_BTCUSDC_20260323T172335Z.md",
        "state_file": "/Users/yumin/Documents/trading/reports/operations/operator_session_briefs/last_alert_state_shift_start_system.json"
      }
    },
    "shift_end_latest": {
      "path": "/Users/yumin/Documents/trading/reports/operations/operator_session_briefs/latest_operator_session_brief_shift_end.json",
      "exists": true,
      "modified_at": "2026-03-23T17:23:35.906926+00:00",
      "age_seconds": 3.115858,
      "healthy": true,
      "issues": [],
      "payload": {
        "brief_mode": "shift-end",
        "brief_report_path": "reports/operations/operator_session_briefs/operator_session_brief_BTCUSDC_20260323T172334Z.md",
        "changed": false,
        "channel": "system",
        "current": {
          "brief_mode": "shift-end",
          "brief_report_path": "reports/operations/operator_session_briefs/operator_session_brief_BTCUSDC_20260323T172334Z.md",
          "brief_status": "DEPLOYMENT_REVIEW_REQUIRED",
          "channel": "system",
          "checklist_go_no_go": "NO_GO",
          "checklist_playbook_action": "resolve_selected_trial_lineage_before_rollout",
          "dashboard_go_no_go": "GO",
          "dashboard_playbook_action": "continue_candidate_review_under_portfolio_caps",
          "deployment_alignment": "DIVERGED",
          "headline": "dashboard and validation/checklist disagree on deployment posture; dashboard=GO, validation=NO_GO, checklist=NO_GO.",
          "playbook_alignment": "DIVERGED",
          "research_action": "run_shadow_exit_timing_review",
          "snapshot_report_path": "reports/operations/operator_surface_divergence/operator_surface_divergence_BTCUSDC_20260323T172335Z.md",
          "symbol": "BTCUSDC",
          "top_family_bottleneck": "legacy_zone_plan",
          "top_operator_action": "continue_candidate_review_under_portfolio_caps",
          "top_session_bottleneck": "preferred_live_window",
          "ui_all_present": true,
          "universe": "usdc_perp_top30",
          "validation_go_no_go": "NO_GO",
          "validation_playbook_action": "resolve_selected_trial_lineage_before_rollout"
        },
        "dry_run": true,
        "force_send": false,
        "notified": false,
        "previous": {
          "brief_mode": "shift-end",
          "brief_report_path": "reports/operations/operator_session_briefs/operator_session_brief_BTCUSDC_20260323T171911Z.md",
          "brief_status": "DEPLOYMENT_REVIEW_REQUIRED",
          "channel": "system",
          "checklist_go_no_go": "NO_GO",
          "checklist_playbook_action": "resolve_selected_trial_lineage_before_rollout",
          "dashboard_go_no_go": "GO",
          "dashboard_playbook_action": "continue_candidate_review_under_portfolio_caps",
          "deployment_alignment": "DIVERGED",
          "headline": "dashboard and validation/checklist disagree on deployment posture; dashboard=GO, validation=NO_GO, checklist=NO_GO.",
          "playbook_alignment": "DIVERGED",
          "research_action": "run_shadow_exit_timing_review",
          "snapshot_report_path": "reports/operations/operator_surface_divergence/operator_surface_divergence_BTCUSDC_20260323T171912Z.md",
          "symbol": "BTCUSDC",
          "top_family_bottleneck": "legacy_zone_plan",
          "top_operator_action": "continue_candidate_review_under_portfolio_caps",
          "top_session_bottleneck": "preferred_live_window",
          "ui_all_present": true,
          "universe": "usdc_perp_top30",
          "validation_go_no_go": "NO_GO",
          "validation_playbook_action": "resolve_selected_trial_lineage_before_rollout"
        },
        "snapshot_report_path": "reports/operations/operator_surface_divergence/operator_surface_divergence_BTCUSDC_20260323T172335Z.md",
        "state_file": "/Users/yumin/Documents/trading/reports/operations/operator_session_briefs/last_alert_state_shift_end_system.json"
      }
    },
    "shift_start_state": {
      "path": "/Users/yumin/Documents/trading/reports/operations/operator_session_briefs/last_alert_state_shift_start_system.json",
      "exists": true,
      "modified_at": "2026-03-23T17:23:35.871886+00:00",
      "age_seconds": 3.150949,
      "healthy": true,
      "issues": [],
      "payload": {
        "brief_mode": "shift-start",
        "brief_report_path": "reports/operations/operator_session_briefs/operator_session_brief_BTCUSDC_20260323T172334Z.md",
        "brief_status": "DEPLOYMENT_REVIEW_REQUIRED",
        "channel": "system",
        "checklist_go_no_go": "NO_GO",
        "checklist_playbook_action": "resolve_selected_trial_lineage_before_rollout",
        "dashboard_go_no_go": "GO",
        "dashboard_playbook_action": "continue_candidate_review_under_portfolio_caps",
        "deployment_alignment": "DIVERGED",
        "headline": "dashboard and validation/checklist disagree on deployment posture; dashboard=GO, validation=NO_GO, checklist=NO_GO.",
        "playbook_alignment": "DIVERGED",
        "research_action": "run_shadow_exit_timing_review",
        "snapshot_report_path": "reports/operations/operator_surface_divergence/operator_surface_divergence_BTCUSDC_20260323T172335Z.md",
        "symbol": "BTCUSDC",
        "top_family_bottleneck": "legacy_zone_plan",
        "top_operator_action": "continue_candidate_review_under_portfolio_caps",
        "top_session_bottleneck": "preferred_live_window",
        "ui_all_present": true,
        "universe": "usdc_perp_top30",
        "validation_go_no_go": "NO_GO",
        "validation_playbook_action": "resolve_selected_trial_lineage_before_rollout"
      }
    },
    "shift_end_state": {
      "path": "/Users/yumin/Documents/trading/reports/operations/operator_session_briefs/last_alert_state_shift_end_system.json",
      "exists": true,
      "modified_at": "2026-03-23T17:23:35.906714+00:00",
      "age_seconds": 3.116167,
      "healthy": true,
      "issues": [],
      "payload": {
        "brief_mode": "shift-end",
        "brief_report_path": "reports/operations/operator_session_briefs/operator_session_brief_BTCUSDC_20260323T172334Z.md",
        "brief_status": "DEPLOYMENT_REVIEW_REQUIRED",
        "channel": "system",
        "checklist_go_no_go": "NO_GO",
        "checklist_playbook_action": "resolve_selected_trial_lineage_before_rollout",
        "dashboard_go_no_go": "GO",
        "dashboard_playbook_action": "continue_candidate_review_under_portfolio_caps",
        "deployment_alignment": "DIVERGED",
        "headline": "dashboard and validation/checklist disagree on deployment posture; dashboard=GO, validation=NO_GO, checklist=NO_GO.",
        "playbook_alignment": "DIVERGED",
        "research_action": "run_shadow_exit_timing_review",
        "snapshot_report_path": "reports/operations/operator_surface_divergence/operator_surface_divergence_BTCUSDC_20260323T172335Z.md",
        "symbol": "BTCUSDC",
        "top_family_bottleneck": "legacy_zone_plan",
        "top_operator_action": "continue_candidate_review_under_portfolio_caps",
        "top_session_bottleneck": "preferred_live_window",
        "ui_all_present": true,
        "universe": "usdc_perp_top30",
        "validation_go_no_go": "NO_GO",
        "validation_playbook_action": "resolve_selected_trial_lineage_before_rollout"
      }
    }
  }
}
```