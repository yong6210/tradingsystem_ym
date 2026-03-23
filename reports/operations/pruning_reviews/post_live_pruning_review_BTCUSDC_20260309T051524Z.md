# Post-Live Pruning Review

- generated_at: 2026-03-09T05:15:24.342535+00:00
- symbol: BTCUSDC
- days: 7
- decision: KEEP_OPTIONAL_HOLD

## Summary

- rationale: No complete live operating cycle evidence yet; keep pruning review deferred.
- live_submission_count: 15
- live_binance_submission_count: 15
- live_fill_like_submission_count: 0

## Checks

- [PASS] actual_live_submissions_present: live submissions in lookback=15
- [PASS] actual_binance_live_path_present: binance live submissions in lookback=15
- [FAIL] actual_live_fill_path_present: live filled/partial submissions in lookback=0
- [FAIL] reconciliation_recently_healthy: healthy=False severity=CRITICAL
- [FAIL] validation_not_no_go: NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.
- [FAIL] checklist_not_no_go: NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.

## Next Steps

- Keep contract pruning on optional hold until at least one actual Binance live cycle completes.
- Rerun this review after a session with real requested_live=true Binance submissions and at least one fill-like outcome.

## Raw Payload

```json
{
  "generated_at": "2026-03-09T05:15:24.342535+00:00",
  "symbol": "BTCUSDC",
  "days": 7,
  "decision": "KEEP_OPTIONAL_HOLD",
  "rationale": "No complete live operating cycle evidence yet; keep pruning review deferred.",
  "checks": [
    {
      "name": "actual_live_submissions_present",
      "status": "PASS",
      "message": "live submissions in lookback=15"
    },
    {
      "name": "actual_binance_live_path_present",
      "status": "PASS",
      "message": "binance live submissions in lookback=15"
    },
    {
      "name": "actual_live_fill_path_present",
      "status": "FAIL",
      "message": "live filled/partial submissions in lookback=0"
    },
    {
      "name": "reconciliation_recently_healthy",
      "status": "FAIL",
      "message": "healthy=False severity=CRITICAL"
    },
    {
      "name": "validation_not_no_go",
      "status": "FAIL",
      "message": "NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval."
    },
    {
      "name": "checklist_not_no_go",
      "status": "FAIL",
      "message": "NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval."
    }
  ],
  "db_live_activity": {
    "cutoff": "2026-03-02T05:15:24.342535+00:00",
    "live_submission_count": 15,
    "live_binance_submission_count": 15,
    "filled_like_submission_count": 0
  },
  "operator_dashboard_summary": {
    "execution_mode": "SHADOW",
    "auto_trading_enabled": false,
    "new_entries_allowed": true,
    "blocking_reason_code": "",
    "blocking_reason_message": "",
    "recent_reconciliation_summary": {
      "healthy": false,
      "highest_severity": "CRITICAL",
      "degraded": true,
      "critical_count": 1,
      "lock_required_count": 2
    }
  },
  "validation_summary": {
    "deployment_go_no_go": "NO_GO",
    "deployment_code": "no_go_threshold_lineage_winner_unresolved",
    "deployment_message": "NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.",
    "playbook_go_no_go": "NO_GO",
    "playbook_action": "resolve_selected_trial_lineage_before_rollout"
  },
  "checklist_summary": {
    "deployment_go_no_go": "NO_GO",
    "deployment_code": "no_go_threshold_lineage_winner_unresolved",
    "deployment_message": "NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.",
    "playbook_go_no_go": "NO_GO",
    "playbook_action": "resolve_selected_trial_lineage_before_rollout"
  },
  "next_steps": [
    "Keep contract pruning on optional hold until at least one actual Binance live cycle completes.",
    "Rerun this review after a session with real requested_live=true Binance submissions and at least one fill-like outcome."
  ]
}
```