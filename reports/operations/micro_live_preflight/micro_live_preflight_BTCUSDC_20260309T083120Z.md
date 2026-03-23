# MICRO_LIVE Preflight

- generated_at: 2026-03-09T08:31:20.121278+00:00
- symbol: BTCUSDC
- universe: usdc_perp_top30
- overall_status: NOT_READY

## Key Decision

- result: NOT_READY
- summary: 3 blocking preflight check(s) remain.

## Checks

- [PASS] health_ready: health status=ready checks={'db': True, 'binance_rest': True, 'event_backend': True}
- [PASS] auto_trading_enabled: execution_mode=PAPER
- [PASS] new_entries_allowed: new entries allowed
- [FAIL] validation_language: NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.
- [FAIL] checklist_language: NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.
- [PASS] safety_state: kill=False close_only=False config_close_only=False
- [PASS] reconciliation: healthy=True severity=INFO
- [PASS] alert_channel: latest_validation_alert=True
- [FAIL] candidate_available: No accepted scanner candidate available.

## Candidate

- no candidate selected

## Next Steps

- NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.
- NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.
- No accepted scanner candidate available.

## Raw Payload

```json
{
  "generated_at": "2026-03-09T08:31:20.121278+00:00",
  "symbol": "BTCUSDC",
  "universe": "usdc_perp_top30",
  "overall_status": "NOT_READY",
  "summary_line": "3 blocking preflight check(s) remain.",
  "checks": [
    {
      "name": "health_ready",
      "status": "PASS",
      "message": "health status=ready checks={'db': True, 'binance_rest': True, 'event_backend': True}"
    },
    {
      "name": "auto_trading_enabled",
      "status": "PASS",
      "message": "execution_mode=PAPER"
    },
    {
      "name": "new_entries_allowed",
      "status": "PASS",
      "message": "new entries allowed"
    },
    {
      "name": "validation_language",
      "status": "FAIL",
      "message": "NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval."
    },
    {
      "name": "checklist_language",
      "status": "FAIL",
      "message": "NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval."
    },
    {
      "name": "safety_state",
      "status": "PASS",
      "message": "kill=False close_only=False config_close_only=False"
    },
    {
      "name": "reconciliation",
      "status": "PASS",
      "message": "healthy=True severity=INFO"
    },
    {
      "name": "alert_channel",
      "status": "PASS",
      "message": "latest_validation_alert=True"
    },
    {
      "name": "candidate_available",
      "status": "FAIL",
      "message": "No accepted scanner candidate available."
    }
  ],
  "candidate": {},
  "health_ready": {
    "status": "ready",
    "checks": {
      "db": true,
      "binance_rest": true,
      "event_backend": true
    },
    "details": {
      "db": "ok",
      "binance_rest": "ok",
      "event_backend": "memory"
    }
  },
  "operator_dashboard": {
    "generated_at": "2026-03-09T08:31:20.429275Z",
    "symbol": "BTCUSDC",
    "execution_mode": "PAPER",
    "auto_trading_enabled": true,
    "source_of_truth_hint": "execution_runtime_aggregate",
    "new_entries_allowed": true,
    "blocking_reason_code": "",
    "blocking_reason_message": "",
    "deployment_go_no_go": "GO",
    "deployment_code": "go_runtime_gate_open",
    "deployment_message": "GO: runtime gate is open for candidate review.",
    "playbook_go_no_go": "GO",
    "playbook_code": "go_portfolio_runtime_ready",
    "playbook_action": "continue_candidate_review_under_portfolio_caps",
    "playbook_message": "GO: runtime gate is open and portfolio headroom review can proceed under current caps.",
    "kill_switch_active": false,
    "close_only_active": false,
    "config_close_only_active": false,
    "active_locks": [
      {
        "lock_id": "lock_5aa1b8e214c44391ade1",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773037891537820USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773037891537820USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T06:31:31.541068Z",
        "updated_at": "2026-03-09T06:31:31.541069Z"
      },
      {
        "lock_id": "lock_4e95878307eb4f54a5ac",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773037843172702USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773037843172702USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T06:30:43.177765Z",
        "updated_at": "2026-03-09T06:30:43.177766Z"
      },
      {
        "lock_id": "lock_df2900fa0ad4490aa0d2",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773037805754817USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773037805754817USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T06:30:05.758606Z",
        "updated_at": "2026-03-09T06:30:05.758607Z"
      },
      {
        "lock_id": "lock_b48ce412407943d69076",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773037767248429USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773037767248429USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T06:29:27.251928Z",
        "updated_at": "2026-03-09T06:29:27.251928Z"
      },
      {
        "lock_id": "lock_2875ee41400645fb9d11",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773037705721599USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773037705721599USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T06:28:25.725776Z",
        "updated_at": "2026-03-09T06:28:25.725777Z"
      },
      {
        "lock_id": "lock_1f4413f094fd49bebe61",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773037535757210USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773037535757210USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T06:25:35.761644Z",
        "updated_at": "2026-03-09T06:25:35.761645Z"
      },
      {
        "lock_id": "lock_4fa1b245d4c1491ba952",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773037335553985USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773037335553985USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T06:22:15.557864Z",
        "updated_at": "2026-03-09T06:22:15.557865Z"
      }
    ],
    "matching_locks": [],
    "rollout_policies": [
      {
        "strategy_family": "legacy_zone_plan",
        "live_enabled": false,
        "max_execution_mode": "SHADOW",
        "max_risk_r": 0.0,
        "allowed_sessions": [],
        "min_quality_score": 0.0
      },
      {
        "strategy_family": "range_rotation",
        "live_enabled": false,
        "max_execution_mode": "SHADOW",
        "max_risk_r": 0.25,
        "allowed_sessions": [
          "london",
          "new_york"
        ],
        "min_quality_score": 68.0
      },
      {
        "strategy_family": "sweep_reversal",
        "live_enabled": false,
        "max_execution_mode": "PAPER",
        "max_risk_r": 0.5,
        "allowed_sessions": [
          "london",
          "new_york"
        ],
        "min_quality_score": 70.0
      },
      {
        "strategy_family": "trend_continuation",
        "live_enabled": true,
        "max_execution_mode": "MICRO_LIVE",
        "max_risk_r": 1.0,
        "allowed_sessions": [
          "london",
          "new_york"
        ],
        "min_quality_score": 75.0
      }
    ],
    "recent_intent_count": 3,
    "recent_intents": [
      {
        "intent_id": "intent_a7026718cf8f4eba8d9b",
        "plan_id": "plan_zone_2682a953a959_confirm",
        "symbol": "BTCUSDC",
        "strategy_family": "legacy_zone_plan",
        "execution_mode": "PAPER",
        "approval_state": "BLOCKED",
        "submit_decision": "SKIP_BLOCKED",
        "decision_reason_code": "family_not_live_enabled",
        "decision_reason_message": "legacy_zone_plan is not in the current auto-trading family allowlist.",
        "allowed_execution_mode": "SHADOW",
        "deployment_go_no_go": "GO",
        "deployment_code": "go_runtime_gate_open",
        "playbook_go_no_go": "NO_GO",
        "playbook_code": "family_not_live_enabled",
        "playbook_action": "block_new_entries_until_execution_issue_is_cleared",
        "thesis_cluster_id": "",
        "created_at": "2026-03-09T05:49:28.362030"
      },
      {
        "intent_id": "intent_f4ca2e220db04b69a9fb",
        "plan_id": "BTCUSDC_rollout_db_plan_1772999839769191",
        "symbol": "BTCUSDC",
        "strategy_family": "trend_continuation",
        "execution_mode": "MICRO_LIVE",
        "approval_state": "BLOCKED",
        "submit_decision": "SKIP_BLOCKED",
        "decision_reason_code": "mode_total_risk_cap_reached",
        "decision_reason_message": "Blocked: total risk cap would be exceeded.",
        "allowed_execution_mode": "PAPER",
        "deployment_go_no_go": "GO",
        "deployment_code": "go_runtime_gate_open",
        "playbook_go_no_go": "NO_GO",
        "playbook_code": "mode_total_risk_cap_reached",
        "playbook_action": "block_new_entries_until_execution_issue_is_cleared",
        "thesis_cluster_id": "",
        "created_at": "2026-03-08T19:57:19.775737"
      },
      {
        "intent_id": "intent_0264c33874f5404ba73c",
        "plan_id": "BTCUSDC_micro_live_plan_1772999839757172",
        "symbol": "BTCUSDC",
        "strategy_family": "trend_continuation",
        "execution_mode": "MICRO_LIVE",
        "approval_state": "APPROVED_AUTO",
        "submit_decision": "SUBMIT",
        "decision_reason_code": "submit_ready",
        "decision_reason_message": "Intent is approved for MICRO_LIVE submit.",
        "allowed_execution_mode": "MICRO_LIVE",
        "deployment_go_no_go": "GO",
        "deployment_code": "go_runtime_gate_open",
        "playbook_go_no_go": "GO",
        "playbook_code": "micro_live_rollout_enabled",
        "playbook_action": "allow_auto_submit",
        "thesis_cluster_id": "",
        "created_at": "2026-03-08T19:57:19.761583"
      }
    ],
    "open_order_count": 0,
    "open_orders": [],
    "open_position_count": 0,
    "open_positions": [],
    "recent_reconciliation_count": 10,
    "recent_reconciliation_summary": {
      "healthy": false,
      "highest_severity": "CRITICAL",
      "degraded": true,
      "critical_count": 5,
      "lock_required_count": 10
    },
    "recent_reconciliation_events": [
      {
        "event_id": "recon_931b622c64114836b2",
        "symbol": "BTCUSDC",
        "mismatch_type": "FILL_EVENT_GAP",
        "severity": "CRITICAL",
        "message": "Open submissions exist but no execution fill event has been recorded recently.",
        "lock_required": true,
        "lock_applied": true,
        "lock_scope": "SYMBOL",
        "created_at": "2026-03-09T05:36:02.685887"
      },
      {
        "event_id": "recon_356b55e47fa14a8293",
        "symbol": "BTCUSDC",
        "mismatch_type": "ORPHAN_ORDER_LOCAL",
        "severity": "WARNING",
        "message": "Local open submission intent-c33874f5404ba73c is missing from exchange open orders.",
        "lock_required": true,
        "lock_applied": false,
        "lock_scope": null,
        "created_at": "2026-03-09T05:36:02.684041"
      },
      {
        "event_id": "recon_d1e3af1f69c045f88e",
        "symbol": "BTCUSDC",
        "mismatch_type": "FILL_EVENT_GAP",
        "severity": "CRITICAL",
        "message": "Open submissions exist but no execution fill event has been recorded recently.",
        "lock_required": true,
        "lock_applied": true,
        "lock_scope": "SYMBOL",
        "created_at": "2026-03-09T05:29:35.052747"
      },
      {
        "event_id": "recon_a673dd836d3d4b168b",
        "symbol": "BTCUSDC",
        "mismatch_type": "ORPHAN_ORDER_LOCAL",
        "severity": "WARNING",
        "message": "Local open submission intent-c33874f5404ba73c is missing from exchange open orders.",
        "lock_required": true,
        "lock_applied": false,
        "lock_scope": null,
        "created_at": "2026-03-09T05:29:35.051676"
      },
      {
        "event_id": "recon_ac0ebd04fbf4479aa9",
        "symbol": "BTCUSDC",
        "mismatch_type": "FILL_EVENT_GAP",
        "severity": "CRITICAL",
        "message": "Open submissions exist but no execution fill event has been recorded recently.",
        "lock_required": true,
        "lock_applied": true,
        "lock_scope": "SYMBOL",
        "created_at": "2026-03-09T05:29:12.172913"
      },
      {
        "event_id": "recon_f345aacdcbb94ee7b1",
        "symbol": "BTCUSDC",
        "mismatch_type": "ORPHAN_ORDER_LOCAL",
        "severity": "WARNING",
        "message": "Local open submission intent-c33874f5404ba73c is missing from exchange open orders.",
        "lock_required": true,
        "lock_applied": false,
        "lock_scope": null,
        "created_at": "2026-03-09T05:29:12.170942"
      },
      {
        "event_id": "recon_93e6a6928f104a1093",
        "symbol": "BTCUSDC",
        "mismatch_type": "FILL_EVENT_GAP",
        "severity": "CRITICAL",
        "message": "Open submissions exist but no execution fill event has been recorded recently.",
        "lock_required": true,
        "lock_applied": true,
        "lock_scope": "SYMBOL",
        "created_at": "2026-03-09T05:24:47.738792"
      },
      {
        "event_id": "recon_b89126be3671463f8c",
        "symbol": "BTCUSDC",
        "mismatch_type": "ORPHAN_ORDER_LOCAL",
        "severity": "WARNING",
        "message": "Local open submission intent-c33874f5404ba73c is missing from exchange open orders.",
        "lock_required": true,
        "lock_applied": false,
        "lock_scope": null,
        "created_at": "2026-03-09T05:24:47.735624"
      },
      {
        "event_id": "recon_7088b818f00d411b9d",
        "symbol": "BTCUSDC",
        "mismatch_type": "FILL_EVENT_GAP",
        "severity": "CRITICAL",
        "message": "Open submissions exist but no execution fill event has been recorded recently.",
        "lock_required": true,
        "lock_applied": false,
        "lock_scope": null,
        "created_at": "2026-03-09T04:48:05.749678"
      },
      {
        "event_id": "recon_8a045fc7460646d9a9",
        "symbol": "BTCUSDC",
        "mismatch_type": "ORPHAN_ORDER_LOCAL",
        "severity": "WARNING",
        "message": "Local open submission intent-c33874f5404ba73c is missing from exchange open orders.",
        "lock_required": true,
        "lock_applied": false,
        "lock_scope": null,
        "created_at": "2026-03-09T04:48:05.749675"
      }
    ],
    "portfolio_summary": {
      "universe": "usdc_perp_top30",
      "deployment_go_no_go": "GO",
      "deployment_code": "go_runtime_gate_open",
      "deployment_message": "GO: runtime gate is open for candidate review.",
      "playbook_go_no_go": "GO",
      "playbook_code": "go_portfolio_runtime_ready",
      "playbook_action": "continue_candidate_review_under_portfolio_caps",
      "playbook_message": "GO: runtime gate is open and portfolio headroom review can proceed under current caps.",
      "risk_state": "OPEN",
      "risk_reason": "normal",
      "accepted_candidate_count": 0,
      "blocked_candidate_count": 10,
      "current_position_count": 40,
      "headroom_by_regime": {
        "range": {
          "caps": {
            "total": 10,
            "directional": 6,
            "cluster": 2
          },
          "remaining_total": 0,
          "remaining_directional": {
            "long": 0,
            "short": 0
          },
          "remaining_cluster": {
            "long": 0,
            "short": 0
          },
          "current_directional": {
            "long": 21,
            "short": 19
          },
          "current_cluster": {
            "long": 17,
            "short": 18
          },
          "remaining_thesis_clusters": 0
        },
        "trend": {
          "caps": {
            "total": 8,
            "directional": 5,
            "cluster": 1
          },
          "remaining_total": 0,
          "remaining_directional": {
            "long": 0,
            "short": 0
          },
          "remaining_cluster": {
            "long": 0,
            "short": 0
          },
          "current_directional": {
            "long": 21,
            "short": 19
          },
          "current_cluster": {
            "long": 17,
            "short": 18
          },
          "remaining_thesis_clusters": 0
        },
        "shock": {
          "caps": {
            "total": 5,
            "directional": 3,
            "cluster": 1
          },
          "remaining_total": 0,
          "remaining_directional": {
            "long": 0,
            "short": 0
          },
          "remaining_cluster": {
            "long": 0,
            "short": 0
          },
          "current_directional": {
            "long": 21,
            "short": 19
          },
          "current_cluster": {
            "long": 17,
            "short": 18
          },
          "remaining_thesis_clusters": 0
        }
      }
    },
    "alert_summary": {
      "overall": {
        "scope": "leaf_channels",
        "total": 41,
        "attempted": 14,
        "delivered": 12,
        "skipped": 27,
        "failed": 2,
        "success_rate": 0.8571428571428571,
        "failure_rate": 0.14285714285714285,
        "skipped_rate": 0.6585365853658537,
        "latency_ms": {
          "avg": 254.26466666666667,
          "p50": 367.06600000000003,
          "p95": 406.2935,
          "max": 416.861
        },
        "slo": {
          "status": "FAIL",
          "met": false,
          "reason": "outside_warn_band",
          "target_success_rate": 0.995,
          "warn_success_rate": 0.97,
          "target_p95_latency_ms": 3000.0,
          "warn_p95_latency_ms": 5000.0
        },
        "error_budget": {
          "status": "EXHAUSTED",
          "allowed_failures": 0.07,
          "failed": 2,
          "remaining_failures": -1.93,
          "burn_ratio": 28.571428571428545,
          "budget_fraction_remaining": 0.0
        }
      },
      "retry_queue": {
        "counts": {
          "queued": 5
        },
        "backlog_age_seconds": 7190,
        "dead_letter_oldest_age_seconds": 0,
        "next_retry_in_seconds": 0,
        "retry_policy": {
          "max_attempts": 4,
          "retry_backoff_seconds": 30.0,
          "retry_jitter_seconds": 0.0
        }
      },
      "latest_validation_alert": {
        "available": true,
        "alert_id": "alert_retry_arq_1773037891828401_1_1_1773044857907004",
        "symbol": "PBOENGINE1773037891800656USDC",
        "channel": "discord",
        "type": "validation_warn",
        "triggered_ts": "2026-03-09T08:27:37.907004",
        "status": "WARN",
        "deployment_go_no_go": "NO_GO",
        "deployment_code": "no_go_replay_backed_worst_scenario_missing",
        "deployment_message": "NO-GO: worst downside scenario is not replay-backed yet. Keep approval blocked until replay-backed downside evidence exists.",
        "approval_topline_summary_line": "winner=runtime_proxy/runtime_validation_proxy_v1; worst=shock_concentration/WARN/approximation; promotion=keep_current_path",
        "approval_playbook_go_no_go": "NO_GO",
        "approval_playbook_code": "no_go_replay_backed_worst_scenario_missing",
        "approval_playbook_action": "wait_for_replay_backed_downside_evidence",
        "approval_playbook_message": "NO-GO: worst downside scenario is not replay-backed yet. Keep approval blocked until replay-backed downside evidence exists.",
        "delivery_reason": "discord_not_configured",
        "delivery_channel": "discord",
        "delivered": false,
        "skipped": true,
        "failed": false,
        "retry_queued": 0
      }
    },
    "execution_quality_summary": {
      "symbol": "BTCUSDC",
      "fill_rate": 1.0,
      "fill_events_total": 3,
      "slippage_bps": {
        "avg": -5.0000000000004245,
        "p50": -5.0000000000004245,
        "p95": 8.499999999999446,
        "max": 9.999999999999432
      },
      "fees": {
        "total": 0.06,
        "avg_per_fill": 0.02,
        "avg_entry_fee": 0.02
      },
      "target_exit_ratio": 0.5,
      "forced_exit_ratio": 0.5,
      "information_failure_ratio": 0.0,
      "time_failure_ratio": 0.5,
      "report_path": null
    }
  },
  "reconciliation": {
    "symbol": "BTCUSDC",
    "mismatches": [],
    "healthy": true,
    "highest_severity": "INFO",
    "lock_required": false,
    "auto_resolve_requested": true,
    "auto_resolve_applied": false,
    "apply_lock_requested": true,
    "events_recorded": 0,
    "generated_at": "2026-03-09T08:31:20.432845Z"
  },
  "safety_state": {
    "symbol": "BTCUSDC",
    "strategy_family": null,
    "session_name": null,
    "new_entry_allowed": true,
    "blocking_reason_code": "",
    "blocking_reason_message": "",
    "kill_switch_active": false,
    "close_only_active": false,
    "config_close_only_active": false,
    "matching_locks": [],
    "active_locks": [
      {
        "lock_id": "lock_5aa1b8e214c44391ade1",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773037891537820USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773037891537820USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T06:31:31.541068Z",
        "updated_at": "2026-03-09T06:31:31.541069Z"
      },
      {
        "lock_id": "lock_4e95878307eb4f54a5ac",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773037843172702USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773037843172702USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T06:30:43.177765Z",
        "updated_at": "2026-03-09T06:30:43.177766Z"
      },
      {
        "lock_id": "lock_df2900fa0ad4490aa0d2",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773037805754817USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773037805754817USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T06:30:05.758606Z",
        "updated_at": "2026-03-09T06:30:05.758607Z"
      },
      {
        "lock_id": "lock_b48ce412407943d69076",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773037767248429USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773037767248429USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T06:29:27.251928Z",
        "updated_at": "2026-03-09T06:29:27.251928Z"
      },
      {
        "lock_id": "lock_2875ee41400645fb9d11",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773037705721599USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773037705721599USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T06:28:25.725776Z",
        "updated_at": "2026-03-09T06:28:25.725777Z"
      },
      {
        "lock_id": "lock_1f4413f094fd49bebe61",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773037535757210USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773037535757210USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T06:25:35.761644Z",
        "updated_at": "2026-03-09T06:25:35.761645Z"
      },
      {
        "lock_id": "lock_4fa1b245d4c1491ba952",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773037335553985USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773037335553985USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T06:22:15.557864Z",
        "updated_at": "2026-03-09T06:22:15.557865Z"
      }
    ],
    "rollout_policies": [
      {
        "strategy_family": "legacy_zone_plan",
        "live_enabled": false,
        "max_execution_mode": "SHADOW",
        "max_risk_r": 0.0,
        "allowed_sessions": [],
        "min_quality_score": 0.0
      },
      {
        "strategy_family": "range_rotation",
        "live_enabled": false,
        "max_execution_mode": "SHADOW",
        "max_risk_r": 0.25,
        "allowed_sessions": [
          "london",
          "new_york"
        ],
        "min_quality_score": 68.0
      },
      {
        "strategy_family": "sweep_reversal",
        "live_enabled": false,
        "max_execution_mode": "PAPER",
        "max_risk_r": 0.5,
        "allowed_sessions": [
          "london",
          "new_york"
        ],
        "min_quality_score": 70.0
      },
      {
        "strategy_family": "trend_continuation",
        "live_enabled": true,
        "max_execution_mode": "MICRO_LIVE",
        "max_risk_r": 1.0,
        "allowed_sessions": [
          "london",
          "new_york"
        ],
        "min_quality_score": 75.0
      }
    ]
  },
  "validation_report": {
    "deployment_go_no_go": "NO_GO",
    "deployment_code": "no_go_threshold_lineage_winner_unresolved",
    "deployment_message": "NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.",
    "playbook_go_no_go": "NO_GO",
    "playbook_action": "resolve_selected_trial_lineage_before_rollout"
  },
  "operations_checklist": {
    "deployment_go_no_go": "NO_GO",
    "deployment_code": "no_go_threshold_lineage_winner_unresolved",
    "deployment_message": "NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.",
    "playbook_go_no_go": "NO_GO",
    "playbook_action": "resolve_selected_trial_lineage_before_rollout"
  },
  "alert_metrics_summary": {
    "latest_validation_alert": {
      "available": true,
      "alert_id": "alert_retry_arq_1773037891828401_1_1_1773044857907004",
      "symbol": "PBOENGINE1773037891800656USDC",
      "channel": "discord",
      "type": "validation_warn",
      "triggered_ts": "2026-03-09T08:27:37.907004",
      "status": "WARN",
      "deployment_go_no_go": "NO_GO",
      "deployment_code": "no_go_replay_backed_worst_scenario_missing",
      "deployment_message": "NO-GO: worst downside scenario is not replay-backed yet. Keep approval blocked until replay-backed downside evidence exists.",
      "approval_topline_summary_line": "winner=runtime_proxy/runtime_validation_proxy_v1; worst=shock_concentration/WARN/approximation; promotion=keep_current_path",
      "approval_playbook_go_no_go": "NO_GO",
      "approval_playbook_code": "no_go_replay_backed_worst_scenario_missing",
      "approval_playbook_action": "wait_for_replay_backed_downside_evidence",
      "approval_playbook_message": "NO-GO: worst downside scenario is not replay-backed yet. Keep approval blocked until replay-backed downside evidence exists.",
      "delivery_reason": "discord_not_configured",
      "delivery_channel": "discord",
      "delivered": false,
      "skipped": true,
      "failed": false,
      "retry_queued": 0
    },
    "overall": {
      "scope": "leaf_channels",
      "total": 41,
      "attempted": 14,
      "delivered": 12,
      "skipped": 27,
      "failed": 2,
      "success_rate": 0.8571428571428571,
      "failure_rate": 0.14285714285714285,
      "skipped_rate": 0.6585365853658537,
      "latency_ms": {
        "avg": 254.26466666666667,
        "p50": 367.06600000000003,
        "p95": 406.2935,
        "max": 416.861
      },
      "slo": {
        "status": "FAIL",
        "met": false,
        "reason": "outside_warn_band",
        "target_success_rate": 0.995,
        "warn_success_rate": 0.97,
        "target_p95_latency_ms": 3000.0,
        "warn_p95_latency_ms": 5000.0
      },
      "error_budget": {
        "status": "EXHAUSTED",
        "allowed_failures": 0.07,
        "failed": 2,
        "remaining_failures": -1.93,
        "burn_ratio": 28.571428571428545,
        "budget_fraction_remaining": 0.0
      }
    }
  },
  "next_steps": [
    "NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.",
    "NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.",
    "No accepted scanner candidate available."
  ]
}
```