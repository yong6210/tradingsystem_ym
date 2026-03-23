# Operational Checklist: BTCUSDC

- generated_at_utc: 2026-03-09T08:44:31+00:00
- universe: usdc_perp_top30
- strategy_version: v2
- overall_status: FAIL
- deployment_go_no_go: NO_GO
- deployment_code: no_go_threshold_lineage_winner_unresolved
- deployment_message: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.
- playbook_go_no_go: NO_GO
- playbook_code: no_go_threshold_lineage_winner_unresolved
- playbook_action: resolve_selected_trial_lineage_before_rollout
- playbook_message: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.
- blocking_failures: 2
- warnings: 4
- manual_actions: 0

## Checks
- [PASS] Health Ready (infra) | blocking=True | all readiness checks passed
- [WARN] Validation Report (validation) | blocking=False | validation is WARN; operator review required before live start
- [WARN] Validation Alert Delivery (alerts) | blocking=False | validation alert cooldown active; latest alert should be checked manually
- [FAIL] Alert Channel SLO (alerts) | blocking=True | alert SLO degraded on ['discord']
- [FAIL] Recent Alert Test (alerts) | blocking=True | recent alert test failed on ['discord:discord_not_configured']
- [WARN] Retry Queue (alerts) | blocking=False | retry queue has queued alerts (5)
- [PASS] Event Outbox (infra) | blocking=False | outbox backlog is clear
- [PASS] Risk Gate (risk) | blocking=False | risk gate is OPEN
- [PASS] Session / Dead-Session Guidance (operations) | blocking=False | london session is within preferred live window
- [WARN] Portfolio Headroom (portfolio) | blocking=False | portfolio headroom is constrained
- [PASS] Execution Quality Coverage (execution) | blocking=False | execution quality coverage available
- [PASS] PBO / DSR Design Contract (validation) | blocking=False | PBO/DSR design contract frozen; artifact store artifact_store_schema_ready_empty

## Notes
- This checklist aggregates current API/report evidence for live-readiness review.
- Blocking items with status FAIL or MANUAL should be cleared before live trading.
- WARN items are non-blocking by default, but require operator review.
